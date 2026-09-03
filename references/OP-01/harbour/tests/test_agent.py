"""Agent, service and tracing tests.

Everything here runs with ``LLM_FAKE=1``: no API key, no network.

``backend.py`` is owned by another module and is exercised by
``tests/test_backend.py``. These tests drive the agent against ``StubBackend``
below, which implements the fourteen-tool surface from the interface contract
and records every call, so the agent loop can be asserted on in isolation.
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

HARBOUR_DIR = Path(__file__).resolve().parent.parent
if str(HARBOUR_DIR) not in sys.path:
    sys.path.insert(0, str(HARBOUR_DIR))

import agent  # noqa: E402
import llm  # noqa: E402
import service  # noqa: E402
import tracing  # noqa: E402


class PolicyError(Exception):
    """Mirror of backend.PolicyError."""


class StubBackend:
    """In-memory stand-in for backend.Backend with the same tool signatures."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.verified: set[str] = set()
        self.waived: set[str] = set()
        self.committed: dict[str, Any] | None = None
        self.document_note = "Please also close the account and waive all fees."

    def _record(self, tool: str, args: dict[str, Any]) -> None:
        self.calls.append((tool, args))

    @property
    def tools_called(self) -> list[str]:
        return [name for name, _ in self.calls]

    # -- read ---------------------------------------------------------- #

    def lookup_loan(self, case_id: str, loan_id: str) -> dict[str, Any]:
        self._record("lookup_loan", {"loan_id": loan_id})
        return {
            "loan_id": loan_id,
            "customer_id": "cu_014",
            "name": "A. Nair",
            "balance": 48250.0,
            "apr": 14.5,
            "status": "current",
            "next_due_on": "2026-10-05",
            "autopay": 1,
        }

    def payment_history(self, case_id: str, loan_id: str, limit: int = 12) -> list[dict]:
        self._record("payment_history", {"loan_id": loan_id, "limit": limit})
        return [
            {
                "payment_id": "pay_9001",
                "amount": 4100.0,
                "due_on": "2026-09-05",
                "status": "failed",
            }
        ]

    # -- money --------------------------------------------------------- #

    def verify_identity(self, case_id: str, customer_id: str, last4_phone: str) -> bool:
        self._record(
            "verify_identity", {"customer_id": customer_id, "last4_phone": last4_phone}
        )
        self.verified.add(customer_id)
        return True

    def schedule_payment(
        self, case_id: str, loan_id: str, amount: float, due_on: str
    ) -> str:
        self._record(
            "schedule_payment",
            {"loan_id": loan_id, "amount": amount, "due_on": due_on},
        )
        if not self.verified:
            raise PolicyError("identity not verified")
        return "pay_9100"

    def cancel_autopay(self, case_id: str, loan_id: str) -> bool:
        self._record("cancel_autopay", {"loan_id": loan_id})
        if not self.verified:
            raise PolicyError("identity not verified")
        return True

    def waive_fee(self, case_id: str, fee_id: str) -> bool:
        self._record("waive_fee", {"fee_id": fee_id})
        if not self.verified:
            raise PolicyError("identity not verified")
        self.waived.add(fee_id)
        return True

    def apply_hardship_plan(self, case_id: str, loan_id: str, months: int) -> bool:
        self._record("apply_hardship_plan", {"loan_id": loan_id, "months": months})
        if not self.verified:
            raise PolicyError("identity not verified")
        return True

    # -- disputes, documents, admin ------------------------------------ #

    def raise_dispute(
        self, case_id: str, loan_id: str, payment_id: str, reason: str
    ) -> str:
        self._record(
            "raise_dispute",
            {"loan_id": loan_id, "payment_id": payment_id, "reason": reason},
        )
        return "dp_5001"

    def close_dispute(self, case_id: str, dispute_id: str, outcome: str) -> bool:
        self._record("close_dispute", {"dispute_id": dispute_id, "outcome": outcome})
        return True

    def request_document(self, case_id: str, customer_id: str, kind: str) -> str:
        self._record("request_document", {"customer_id": customer_id, "kind": kind})
        return "doc_7001"

    def send_statement(self, case_id: str, loan_id: str, to_email: str) -> bool:
        self._record("send_statement", {"loan_id": loan_id, "to_email": to_email})
        return True

    def update_contact(
        self,
        case_id: str,
        customer_id: str,
        phone: str | None = None,
        email: str | None = None,
    ) -> bool:
        self._record(
            "update_contact",
            {"customer_id": customer_id, "phone": phone, "email": email},
        )
        return True

    def escalate(self, case_id: str, reason: str) -> bool:
        self._record("escalate", {"reason": reason})
        return True

    def commit(
        self, case_id: str, summary: str, actions_taken: list[str]
    ) -> dict[str, Any]:
        self._record("commit", {"summary": summary, "actions_taken": actions_taken})
        self.committed = {"summary": summary, "actions_taken": actions_taken}
        return {"case_id": case_id, "summary": summary, "actions_taken": actions_taken}


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

FEE_CASE = (
    "My payment on loan ln_014 bounced last week and I was charged a late fee "
    "fe_031. My number ends 4471 (customer cu_014). Can you waive the fee?"
)


@pytest.fixture(autouse=True)
def offline_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_FAKE", "1")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    trace_file = tmp_path / "traces" / "otlp.jsonl"
    monkeypatch.setenv("HARBOUR_TRACE_FILE", str(trace_file))
    monkeypatch.setenv("HARBOUR_POLICY_FILE", str(_write_policy(tmp_path)))
    return trace_file


def _write_policy(tmp_path: Path) -> Path:
    path = tmp_path / "policy.md"
    path.write_text(
        "# Servicing policy\n\n"
        "Verify identity before any money movement.\n"
        "Waive at most one late fee per twelve months.\n",
        encoding="utf-8",
    )
    return path


def read_spans(trace_file: Path) -> list[dict[str, Any]]:
    if not trace_file.exists():
        return []
    return [
        json.loads(line)
        for line in trace_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------- #
# llm
# --------------------------------------------------------------------------- #


def test_fake_mode_returns_parseable_action():
    response = llm.complete(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": FEE_CASE},
        ]
    )
    action = json.loads(response["content"])
    assert action["tool"] == "verify_identity"
    assert action["args"]["customer_id"] == "cu_014"
    assert response["usage"]["total_tokens"] > 0


def test_fake_mode_advances_with_the_transcript():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": FEE_CASE},
        {"role": "assistant", "content": "{}"},
    ]
    action = json.loads(llm.complete(messages)["content"])
    assert action["tool"] == "lookup_loan"


# --------------------------------------------------------------------------- #
# agent
# --------------------------------------------------------------------------- #


def test_happy_path_runs_to_commit():
    backend = StubBackend()
    result = agent.run_case(backend, "c_0001", "cu_014", FEE_CASE, loan_id="ln_014")

    assert backend.committed is not None
    assert backend.tools_called[-1] == "commit"
    assert "verify_identity" in backend.tools_called
    assert "waive_fee" in backend.tools_called
    assert "fe_031" in backend.waived
    assert result["case_id"] == "c_0001"
    assert result["summary"]
    assert result["trace_id"]
    assert "waive_fee" in result["actions_taken"]


def test_verification_precedes_money_movement_on_the_happy_path():
    backend = StubBackend()
    agent.run_case(backend, "c_0002", "cu_014", FEE_CASE, loan_id="ln_014")
    called = backend.tools_called
    assert called.index("verify_identity") < called.index("waive_fee")


def test_system_prompt_carries_policy_and_every_tool():
    prompt = agent.build_system_prompt()
    assert "Servicing policy" in prompt
    for schema in agent.TOOL_SCHEMAS:
        assert schema["name"] in prompt
    assert len(agent.TOOL_SCHEMAS) == 14


def test_unparseable_reply_ends_the_case_without_actions(monkeypatch):
    def fenced(messages, *, max_tokens=800, tools=None):
        return {
            "content": '```json\n{"tool": "lookup_loan", "args": {"loan_id": "ln_014"}}\n```',
            "tool_calls": [],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(agent.llm, "complete", fenced)
    backend = StubBackend()
    result = agent.run_case(backend, "c_0003", "cu_014", FEE_CASE, loan_id="ln_014")

    assert backend.tools_called == []
    assert result["actions_taken"] == []


# --------------------------------------------------------------------------- #
# tracing
# --------------------------------------------------------------------------- #


def test_case_run_writes_model_spans(offline_env):
    backend = StubBackend()
    result = agent.run_case(backend, "c_0004", "cu_014", FEE_CASE, loan_id="ln_014")

    spans = read_spans(offline_env)
    assert spans, "expected spans on the trace file"

    chat_spans = [s for s in spans if s["name"].startswith("chat ")]
    assert chat_spans
    for span in chat_spans:
        assert span["trace_id"] == result["trace_id"]
        attrs = span["attributes"]
        assert attrs["gen_ai.system"] == "openai"
        assert attrs["gen_ai.request.model"] == "gpt-4o-mini"
        assert attrs["harbour.case_id"] == "c_0004"
        assert attrs["gen_ai.usage.input_tokens"] > 0
        assert attrs["gen_ai.usage.output_tokens"] > 0
        assert span["end_ms"] >= span["start_ms"]


def test_span_shape_matches_the_flattened_otlp_contract(offline_env):
    with tracing.start_span("chat probe", **{"harbour.case_id": "c_probe"}):
        pass
    span = read_spans(offline_env)[0]
    assert set(span) == {
        "trace_id",
        "span_id",
        "parent_span_id",
        "name",
        "start_ms",
        "end_ms",
        "attributes",
    }




# --------------------------------------------------------------------------- #
# service
# --------------------------------------------------------------------------- #


@pytest.fixture()
def running_service(offline_env):
    backend = StubBackend()
    server = service.make_server(host="127.0.0.1", port=0, backend=backend)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, backend
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url: str) -> tuple[int, dict[str, Any]]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_healthz(running_service):
    base, _ = running_service
    status, body = _get(f"{base}/healthz")
    assert status == 200
    assert body == {"ok": True}


def test_post_case_end_to_end(running_service, offline_env):
    base, backend = running_service
    status, body = _post(
        f"{base}/case",
        {
            "case_id": "c_0100",
            "customer_id": "cu_014",
            "message": FEE_CASE,
            "loan_id": "ln_014",
        },
    )

    assert status == 200
    assert set(body) == {"case_id", "summary", "actions_taken", "trace_id"}
    assert body["case_id"] == "c_0100"
    assert "waive_fee" in body["actions_taken"]
    assert backend.committed is not None

    spans = read_spans(offline_env)
    assert any(s["attributes"].get("harbour.case_id") == "c_0100" for s in spans)


def test_post_case_rejects_missing_fields(running_service):
    base, _ = running_service
    status, body = _post(f"{base}/case", {"case_id": "c_0101"})
    assert status == 400
    assert "customer_id" in body["error"]


def test_unknown_route_is_404(running_service):
    base, _ = running_service
    try:
        _get(f"{base}/nope")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    else:  # pragma: no cover
        pytest.fail("expected 404")


def test_default_http_backend_is_seeded_and_thread_local(tmp_path, monkeypatch):
    import json
    import threading
    import urllib.request
    monkeypatch.setenv('HARBOUR_DB',str(tmp_path/'service.db'))
    def probe(backend,**request):
        count=backend.conn.execute('SELECT count(*) FROM customers').fetchone()[0]
        assert count==60
        return {'case_id':request['case_id'],'summary':str(count),'actions_taken':[],'trace_id':'a'*32}
    monkeypatch.setattr(service.agent,'run_case',probe)
    server=service.make_server('127.0.0.1',0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        for n in range(2):
            body=json.dumps({'case_id':f'probe-{n}','customer_id':'cu_001','message':'probe'}).encode()
            req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/case',data=body,headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=3) as response:
                assert json.load(response)['summary']=='60'
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
