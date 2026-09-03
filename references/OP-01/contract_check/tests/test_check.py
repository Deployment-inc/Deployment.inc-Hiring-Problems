"""End-to-end: the harness against the example service, with a stub OpenAI upstream."""
from __future__ import annotations

import json
import shlex
import struct
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from contract_check import check, otel_collector, proxy

HERE = Path(__file__).resolve().parent
UPSTREAM_KEY = "real-upstream-key"
USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}


def stub_upstream() -> FastAPI:
    """Deterministic chat-completions provider: tool call first, then an answer that depends on the system prompt."""
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        if request.headers.get("authorization") != f"Bearer {UPSTREAM_KEY}":
            return JSONResponse({"error": {"message": "bad key"}}, 401)
        p = await request.json()
        msgs = p["messages"]
        has_system, last = any(m["role"] == "system" for m in msgs), msgs[-1]
        if last["role"] == "user" and p.get("tools"):
            args = json.dumps({"key": last["content"], "field": "value"})
            deltas = [{"role": "assistant", "tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                                            "function": {"name": "lookup", "arguments": args}}]}]
            finish = "tool_calls"
        else:
            text = str(last["content"])
            content = json.dumps({"answer": text.upper() if has_system else text.lower()})
            deltas = [{"role": "assistant", "content": content[i:i + 8]} for i in range(0, len(content), 8)]
            finish = "stop"
        base = {"id": "chatcmpl-stub", "created": 0, "model": "stub-1"}
        if not p.get("stream"):
            msg = {"role": "assistant", "content": "".join(d.get("content") or "" for d in deltas) or None,
                   "tool_calls": deltas[0].get("tool_calls")}
            return {**base, "object": "chat.completion", "usage": USAGE,
                    "choices": [{"index": 0, "message": msg, "finish_reason": finish}]}

        async def gen():
            for i, d in enumerate(deltas):
                fr = finish if i == len(deltas) - 1 else None
                yield f"data: {json.dumps({**base, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': d, 'finish_reason': fr}]})}\n\n"
            yield f"data: {json.dumps({**base, 'object': 'chat.completion.chunk', 'choices': [], 'usage': USAGE})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    filler = "\n".join(f"- step {i}" for i in range(22))
    (tmp_path / "Makefile").write_text(f"eval:\n\t{shlex.quote(sys.executable)} {shlex.quote(str(HERE / 'example_service.py'))} eval\n")
    (tmp_path / "RUNBOOK.md").write_text(f"# Runbook\n{filler}\n## Rollback\nSet APP_VERSION back and restart.\n")
    (tmp_path / "THREAT_MODEL.md").write_text(f"# Threat model\n## Prompt injection\n{filler}\n")
    (tmp_path / "SLO.md").write_text(f"# SLOs\n- availability 99.5 %\n- p95 latency 2 s\n{filler}\n")
    return tmp_path


def test_harness_end_to_end(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPSTREAM_API_KEY", UPSTREAM_KEY)
    price_path = tmp_path / "test-prices.yaml"
    price_path.write_text("stub-1: {input: 1.0, output: 4.0}\n")
    monkeypatch.setenv("PRICES", str(price_path))
    monkeypatch.setenv("EXAMPLE_CALL_TIMEOUT_S", "2")
    monkeypatch.setenv("EXAMPLE_RUN_BUDGET_S", "6")
    upstream = check.ServerThread(stub_upstream(), check.free_port())
    upstream.start()
    port, report_path = check.free_port(), tmp_path / "report.json"
    argv = ["--target", f"http://127.0.0.1:{port}", "--upstream", f"http://127.0.0.1:{upstream.port}/v1",
            "--repo", str(repo), "--report", str(report_path), "--prices", str(price_path),
            "--start-cmd", f"{shlex.quote(sys.executable)} {shlex.quote(str(HERE / 'example_service.py'))}",
            "--proxy-port", str(check.free_port()), "--collector-port", str(check.free_port()),
            "--fault-repeats", "1", "--latency-samples", "5", "--baseline-p95-ms", "5000", "--trace-wait", "5"]
    try:
        code = check.main(argv)
    finally:
        upstream.stop()
    report = json.loads(report_path.read_text())
    failed = {i["id"]: i["reason"] for i in report["items"] if i["status"] != "pass"}
    assert not failed, failed
    assert code == 0
    assert report["summary"]["contract_items_passed"] == 10
    assert report["summary"]["fault_scenarios_passed_pct"] == 100.0
    assert report["summary"]["eval_cases"] == 50 and report["summary"]["eval_regression_threshold"] == 0.9
    assert [r["status"] for r in report["regressions"]] == ["pass"] * 4
    assert report["latency"]["status"] == "pass"
    assert {f["mode"] for f in report["fault_scenarios"]} == set(check.FAULTS)


# --- unit checks for the parts the end-to-end run does not reach ------------------------
def _varint(v: int) -> bytes:
    out = b""
    while True:
        b, v = v & 0x7F, v >> 7
        out += bytes([b | (0x80 if v else 0)])
        if not v:
            return out


def _ld(num: int, payload: bytes) -> bytes:
    return _varint((num << 3) | 2) + _varint(len(payload)) + payload


def _attr(key: str, any_value: bytes) -> bytes:
    return _ld(9, _ld(1, key.encode()) + _ld(2, any_value))


def test_collector_decodes_protobuf() -> None:
    trace_id, span_id = "ab" * 16, "cd" * 8
    span = (_ld(1, bytes.fromhex(trace_id)) + _ld(2, bytes.fromhex(span_id)) + _ld(5, b"chat stub-1")
            + _attr("gen_ai.usage.input_tokens", b"\x18" + _varint(100))          # AnyValue.int_value
            + _attr("gen_ai.usage.cost_usd", b"\x21" + struct.pack("<d", 0.5))    # AnyValue.double_value
            + _attr("gen_ai.response.model", _ld(1, b"stub-1")))                  # AnyValue.string_value
    request = _ld(1, _ld(1, _ld(1, _ld(1, b"service.name") + _ld(2, _ld(1, b"svc")))) + _ld(2, _ld(2, span)))
    collector = otel_collector.Collector()
    assert collector.ingest(request, "application/x-protobuf", "") == 1
    trace = collector.trace(trace_id)
    assert trace and trace["roots"] == [span_id]
    assert trace["model_calls"] == [{"span_id": span_id, "name": "chat stub-1", "model": "stub-1",
                                     "input_tokens": 100, "output_tokens": 0, "cost_usd": 0.5}]
    assert trace["spans"][0]["resource"] == {"service.name": "svc"}


def test_mutations_cover_the_responses_api() -> None:
    req = {"instructions": "be terse", "input": [{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]}
    out = proxy.mutate_request(req, "strip_system_prompt")
    assert "instructions" not in out and [m["role"] for m in out["input"]] == ["user"]
    resp = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "a" * 100}]},
                       {"type": "function_call", "arguments": json.dumps({"a": 1, "b": 2, "c": 3})}]}
    assert len(proxy.mutate_response(resp, "truncate_output", "none")["output"][0]["content"][0]["text"]) == 40
    flipped = proxy.mutate_response(resp, "flip_tool_args", "none")["output"][1]["arguments"]
    assert json.loads(flipped) == {"a": 2, "b": 3, "c": 1}
    with pytest.raises(ValueError):
        json.loads(proxy.mutate_response(resp, "none", "malformed")["output"][1]["arguments"])
    assert json.loads(proxy._flip(json.dumps({"only": 1}))) == {"only": "only"}
    events = proxy.synthesize_stream(proxy.mutate_response(resp, "truncate_output", "none"))
    assert events[-1] == b"data: [DONE]\n\n" and b"response.completed" in events[-2]
    assert proxy.extract_usage({"type": "response.completed", "response": {"model": "m", "usage": {"input_tokens": 3, "output_tokens": 4}}}) == ("m", 3, 4)


def test_async_jobs_are_awaited() -> None:
    app, polls = FastAPI(), {"n": 0}

    @app.get("/jobs/{job}")
    async def job(job: str) -> JSONResponse:
        polls["n"] += 1
        if polls["n"] < 3:
            return JSONResponse({"status": "pending"}, 202)
        return JSONResponse({"output": job.upper(), "trace_id": "0" * 32, "cost_usd": 0.0}, 200)

    srv = check.ServerThread(app, check.free_port())
    srv.start()
    try:
        h = check.Harness(check.parse_args(["--target", f"http://127.0.0.1:{srv.port}", "--job-slo-s", "5"]))
        assert h.await_job({"job_id": "j1"}, h.a.target) == (200, {"output": "J1", "trace_id": "0" * 32, "cost_usd": 0.0})
        assert h.await_job({}, h.a.target)[0] == 202
        pending = {"status": 202, "body": {"error": {"message": "still pending"}}, "elapsed_s": 1.0, "calls": 1}
        assert h.judge_fault("http500", pending).startswith("accepted with 202")
    finally:
        srv.stop()


def test_harbour_text_action_is_scrambled_and_model_identity_drifts():
    action={'tool':'schedule_payment','args':{'loan_id':'loan','amount':20}}
    response={'model':'stub-1','choices':[{'message':{'content':json.dumps(action)}}]}
    mutated=proxy.mutate_response(response,'scramble_tool_args','none')
    assert json.loads(mutated['choices'][0]['message']['content'])['args']=={'loan_id':20,'amount':'loan'}
    assert proxy.mutate_response(response,'model_identity_drift','none')['model']=='stub-1-unapproved'
    assert json.loads(response['choices'][0]['message']['content'])==action


def test_gateway_control_is_not_available_with_candidate_key():
    import asyncio
    import httpx
    async def exercise():
        gateway=proxy.Gateway('http://unused/v1','upstream-secret','candidate-key',{'default':(1,1)},control_key='reviewer-key')
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy.create_app(gateway)),base_url='http://test') as client:
                assert (await client.get('/_stats')).status_code==401
                assert (await client.post('/_control',headers={'Authorization':'Bearer candidate-key'},json={'regression':'truncate_output'})).status_code==401
                assert (await client.post('/_control',headers={'Authorization':'Bearer reviewer-key'},json={'regression':'truncate_output'})).status_code==200
        finally:
            await gateway.client.aclose()
    asyncio.run(exercise())


def test_service_environment_does_not_inherit_provider_keys(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','provider-secret')
    monkeypatch.setenv('UPSTREAM_API_KEY','upstream-secret')
    monkeypatch.setenv('CF_ACCESS_TOKEN','access-secret')
    h=check.Harness(check.parse_args(['--target','http://127.0.0.1:8000']))
    env=h.env()
    assert all(k not in env for k in ('OPENAI_API_KEY','UPSTREAM_API_KEY','CF_ACCESS_TOKEN','GATEWAY_CONTROL_KEY'))
    assert env['LLM_API_KEY']==h.gateway_key
    assert h.control_key not in env.values()
    h.http.close()


def test_stream_usage_is_cumulative_and_ledger_is_per_call():
    import asyncio
    async def exercise():
        gateway=proxy.Gateway('http://unused/v1','','',{'stub-1':(1,2)})
        gateway.ledger.in_flight=1
        entry={'case_id':'case-a','run_id':'run-a','measurement_status':'usage_unavailable'}
        class Stream:
            async def aiter_raw(self):
                for count in (3,5):
                    yield ('data: '+json.dumps({'model':'stub-1','usage':{'prompt_tokens':count,'completion_tokens':1}})+'\n\n').encode()
            async def aclose(self): pass
        import time
        try:
            async for _ in gateway._pipe(Stream(),time.monotonic(),entry): pass
            assert gateway.ledger.input_tokens==5
            assert gateway.ledger.output_tokens==1
            assert entry['input_tokens']==5 and entry['case_id']=='case-a'
            assert entry['measurement_status']=='usage_observed'
        finally:
            await gateway.client.aclose()
    asyncio.run(exercise())
