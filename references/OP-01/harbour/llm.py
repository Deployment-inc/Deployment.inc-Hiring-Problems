"""The only outbound model path in Harbour.

Everything that talks to a model goes through :func:`complete`, so a gateway in
front of ``LLM_BASE_URL`` sees the whole conversation. Standard library only.

Environment:
    LLM_BASE_URL       default https://api.openai.com/v1
    LLM_API_KEY        bearer token
    LLM_MODEL          default gpt-4.1-mini-2025-04-14
    LLM_EXTRA_HEADERS  JSON object of extra headers (gateway auth, tenant tags)
    LLM_FAKE           set to "1" to run fully offline against canned replies
    LLM_TIMEOUT        per-request socket timeout in seconds (default 60)
    LLM_MAX_RETRIES    attempts on 429/5xx before giving up (default 4)

Two wire quirks are deliberate and must not be "cleaned up":

* ``temperature`` is never sent. Current small-tier models reject any value for
  it with a 400, including the provider default of 1.
* the token cap is sent as ``max_completion_tokens``; ``max_tokens`` is refused
  by the same models.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from typing import Any

try:  # package import when OP-01 is on sys.path, flat import when harbour/ is
    from . import tracing
except ImportError:  # pragma: no cover - exercised by direct script runs
    import tracing  # type: ignore[no-redef]

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4.1-mini-2025-04-14"
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """Raised when the model endpoint cannot be reached or returns a hard error."""


def _model() -> str:
    return os.environ.get("LLM_MODEL", DEFAULT_MODEL)


def _extra_headers() -> dict[str, str]:
    raw = os.environ.get("LLM_EXTRA_HEADERS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM_EXTRA_HEADERS is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("LLM_EXTRA_HEADERS must be a JSON object")
    return {str(k): str(v) for k, v in parsed.items()}


def complete(
    messages: list[dict],
    *,
    max_tokens: int = 800,
    tools: list | None = None,
) -> dict:
    """One chat completion.

    Returns ``{"content": str, "tool_calls": list, "usage": dict}``. ``usage``
    carries ``input_tokens`` / ``output_tokens`` / ``total_tokens``.
    """
    model = _model()
    with tracing.start_span(
        f"chat {model}",
        **{
            "gen_ai.system": "openai",
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": model,
            "gen_ai.request.max_tokens": max_tokens,
            "harbour.case_id": tracing.current_case_id(),
        },
    ) as span:
        if os.environ.get("LLM_FAKE") == "1":
            result = _fake_completion(messages, max_tokens=max_tokens, tools=tools)
        else:
            result = _live_completion(messages, max_tokens=max_tokens, tools=tools)

        usage = result["usage"]
        span.update(
            **{
                "gen_ai.usage.input_tokens": usage.get("input_tokens", 0),
                "gen_ai.usage.output_tokens": usage.get("output_tokens", 0),
                "gen_ai.response.model": result.get("model", model),
                "gen_ai.response.finish_reasons": [result.get("finish_reason", "stop")],
            }
        )
        return result


# --------------------------------------------------------------------------- #
# live path
# --------------------------------------------------------------------------- #


def _live_completion(
    messages: list[dict], *, max_tokens: int, tools: list | None
) -> dict:
    base_url = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = _model()

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        # NOT max_tokens: the small-tier models 400 on the legacy field name.
        "max_completion_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
    # No "temperature" key. Any value, including 1, is rejected with a 400.

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(_extra_headers())

    body = json.dumps(payload).encode("utf-8")
    timeout = float(os.environ.get("LLM_TIMEOUT", "60"))
    attempts = max(1, int(os.environ.get("LLM_MAX_RETRIES", "4")))
    last_error: Exception | None = None

    for attempt in range(attempts):
        request = urllib.request.Request(
            f"{base_url}/chat/completions", data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            return _normalise(raw, model)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            last_error = LLMError(f"HTTP {exc.code} from {base_url}: {detail}")
            if exc.code not in _RETRY_STATUS or attempt == attempts - 1:
                raise last_error from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = LLMError(f"transport error talking to {base_url}: {exc}")
            if attempt == attempts - 1:
                raise last_error from exc
        _sleep_backoff(attempt)

    raise last_error or LLMError("model call failed for an unknown reason")


def _sleep_backoff(attempt: int) -> None:
    delay = min(8.0, 0.5 * (2**attempt))
    time.sleep(delay + random.uniform(0.0, 0.25))


def _normalise(raw: dict, model: str) -> dict:
    choices = raw.get("choices") or [{}]
    message = choices[0].get("message") or {}
    usage = raw.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens", 0))
    output_tokens = int(usage.get("completion_tokens", 0))
    return {
        "content": message.get("content") or "",
        "tool_calls": message.get("tool_calls") or [],
        "model": raw.get("model", model),
        "finish_reason": choices[0].get("finish_reason", "stop"),
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(
                usage.get("total_tokens", input_tokens + output_tokens)
            ),
        },
    }


# --------------------------------------------------------------------------- #
# offline path
# --------------------------------------------------------------------------- #
#
# LLM_FAKE=1 replays a deterministic servicing plan so the test suite and the
# published case set run with no API key and no network. The plan is chosen from
# keywords in the customer message and advanced by counting how many assistant
# turns are already in the transcript, which makes each reply a pure function of
# the messages handed in.

_ID_PATTERN = re.compile(r"\b(?:ln|cu|fe|pay|pm|dp|doc)_[A-Za-z0-9]+\b")
_LAST4_PATTERN = re.compile(r"\b(\d{4})\b")

_PLANS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("waive", "fee", "late charge"), ("verify_identity", "lookup_loan", "waive_fee")),
    (
        ("hardship", "lost my job", "reduced income", "furlough"),
        ("verify_identity", "lookup_loan", "apply_hardship_plan"),
    ),
    (
        ("reschedule", "push", "postpone", "move my payment", "later date"),
        ("verify_identity", "lookup_loan", "schedule_payment"),
    ),
    (("autopay", "auto-pay", "auto debit"), ("verify_identity", "cancel_autopay")),
    (("close the dispute", "resolve the dispute", "withdraw"), ("close_dispute",)),
    (("dispute", "did not authorise", "fraud", "wrong charge"), ("raise_dispute",)),
    (("statement", "account summary"), ("lookup_loan", "send_statement")),
    (("document", "upload", "proof of", "payslip"), ("request_document",)),
    (("email", "phone number", "new number", "contact"), ("update_contact",)),
]
_FALLBACK_PLAN = ("lookup_loan", "escalate")


def _transcript_text(messages: list[dict]) -> str:
    parts = [str(m.get("content") or "") for m in messages]
    return "\n".join(parts).lower()


def _customer_text(messages: list[dict]) -> str:
    for message in messages:
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _choose_plan(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    for keywords, plan in _PLANS:
        if any(keyword in lowered for keyword in keywords):
            return plan
    return _FALLBACK_PLAN


def _collect_ids(text: str) -> dict[str, str]:
    ids: dict[str, str] = {}
    for match in _ID_PATTERN.findall(text):
        prefix = match.split("_", 1)[0]
        ids.setdefault(prefix, match)
    return ids


def _args_for(tool: str, ids: dict[str, str], text: str) -> dict[str, Any]:
    loan_id = ids.get("ln", "ln_0001")
    customer_id = ids.get("cu", "cu_0001")
    if tool == "verify_identity":
        candidates = _LAST4_PATTERN.findall(text)
        return {"customer_id": customer_id, "last4_phone": candidates[-1] if candidates else "0000"}
    if tool in {"lookup_loan", "cancel_autopay"}:
        return {"loan_id": loan_id}
    if tool == "payment_history":
        return {"loan_id": loan_id, "limit": 12}
    if tool == "waive_fee":
        return {"fee_id": ids.get("fe", "fe_0001")}
    if tool == "apply_hardship_plan":
        return {"loan_id": loan_id, "months": 3}
    if tool == "schedule_payment":
        return {"loan_id": loan_id, "amount": 5000.0, "due_on": "2026-10-15"}
    if tool == "raise_dispute":
        return {
            "loan_id": loan_id,
            "payment_id": ids.get("pay") or ids.get("pm", "pay_0001"),
            "reason": "Customer reports the charge was not authorised.",
        }
    if tool == "close_dispute":
        return {"dispute_id": ids.get("dp", "dp_0001"), "outcome": "upheld"}
    if tool == "request_document":
        return {"customer_id": customer_id, "kind": "income_proof"}
    if tool == "send_statement":
        return {"loan_id": loan_id, "to_email": "customer@example.com"}
    if tool == "update_contact":
        return {"customer_id": customer_id, "phone": None, "email": "new@example.com"}
    if tool == "escalate":
        return {"reason": "Request needs a human servicing agent."}
    return {}


def _fake_completion(
    messages: list[dict], *, max_tokens: int, tools: list | None
) -> dict:
    customer_text = _customer_text(messages)
    plan = _choose_plan(customer_text)
    ids = _collect_ids(_transcript_text(messages))
    step = sum(1 for m in messages if m.get("role") == "assistant")

    if step < len(plan):
        tool = plan[step]
        action = {"tool": tool, "args": _args_for(tool, ids, customer_text)}
    else:
        action = {
            "tool": "commit",
            "args": {
                "summary": f"Handled the customer request via {', '.join(plan)}.",
                "actions_taken": list(plan),
            },
        }

    content = json.dumps(action)
    prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
    input_tokens = max(1, prompt_chars // 4)
    output_tokens = max(1, len(content) // 4)
    return {
        "content": content,
        "tool_calls": [],
        "model": f"{_model()}-fake",
        "finish_reason": "stop",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }
