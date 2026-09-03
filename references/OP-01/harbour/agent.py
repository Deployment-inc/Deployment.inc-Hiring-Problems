"""The shipped Harbour servicing agent.

One tool-calling loop. The system prompt is assembled from ``policy.md`` plus
the JSON schemas of the fourteen backend tools; the agent then reads the
customer message and works the case until it calls ``commit`` or runs out of
steps.

The model is asked for one action at a time as a JSON object, because the
provider's tool-calling surface behaved inconsistently across the snapshots we
tested and the JSON reply path was stable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable

try:  # package import when OP-01 is on sys.path, flat import when harbour/ is
    from . import llm, tracing
except ImportError:  # pragma: no cover - exercised by direct script runs
    import llm  # type: ignore[no-redef]
    import tracing  # type: ignore[no-redef]

# One attempt is one full pass of the conversation. Hard cases sometimes need a
# few passes before the model settles on a clean plan.
MAX_STEPS_PER_ATTEMPT = 12
MAX_ATTEMPTS = 6

TERMINAL_TOOL = "commit"

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "lookup_loan",
        "description": "Fetch a loan row plus the owning customer's name.",
        "parameters": {
            "type": "object",
            "properties": {"loan_id": {"type": "string"}},
            "required": ["loan_id"],
        },
    },
    {
        "name": "payment_history",
        "description": "Recent payments on a loan, newest first.",
        "parameters": {
            "type": "object",
            "properties": {
                "loan_id": {"type": "string"},
                "limit": {"type": "integer", "default": 12},
            },
            "required": ["loan_id"],
        },
    },
    {
        "name": "verify_identity",
        "description": (
            "Verify the customer with the last four digits of the phone number "
            "on file. Required before any money movement."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "last4_phone": {"type": "string"},
            },
            "required": ["customer_id", "last4_phone"],
        },
    },
    {
        "name": "schedule_payment",
        "description": "Schedule a payment of `amount` on `due_on` (YYYY-MM-DD).",
        "parameters": {
            "type": "object",
            "properties": {
                "loan_id": {"type": "string"},
                "amount": {"type": "number"},
                "due_on": {"type": "string"},
            },
            "required": ["loan_id", "amount", "due_on"],
        },
    },
    {
        "name": "cancel_autopay",
        "description": "Turn off autopay on a loan.",
        "parameters": {
            "type": "object",
            "properties": {"loan_id": {"type": "string"}},
            "required": ["loan_id"],
        },
    },
    {
        "name": "waive_fee",
        "description": "Waive an applied fee, subject to the policy cap.",
        "parameters": {
            "type": "object",
            "properties": {"fee_id": {"type": "string"}},
            "required": ["fee_id"],
        },
    },
    {
        "name": "apply_hardship_plan",
        "description": "Apply a hardship plan for a number of months.",
        "parameters": {
            "type": "object",
            "properties": {
                "loan_id": {"type": "string"},
                "months": {"type": "integer"},
            },
            "required": ["loan_id", "months"],
        },
    },
    {
        "name": "raise_dispute",
        "description": "Open a dispute against a specific payment.",
        "parameters": {
            "type": "object",
            "properties": {
                "loan_id": {"type": "string"},
                "payment_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["loan_id", "payment_id", "reason"],
        },
    },
    {
        "name": "close_dispute",
        "description": "Close a dispute with outcome 'upheld' or 'rejected'.",
        "parameters": {
            "type": "object",
            "properties": {
                "dispute_id": {"type": "string"},
                "outcome": {"type": "string", "enum": ["upheld", "rejected"]},
            },
            "required": ["dispute_id", "outcome"],
        },
    },
    {
        "name": "request_document",
        "description": "Ask the customer for a document of a given kind.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "kind": {"type": "string"},
            },
            "required": ["customer_id", "kind"],
        },
    },
    {
        "name": "send_statement",
        "description": "Email a loan statement to an address.",
        "parameters": {
            "type": "object",
            "properties": {
                "loan_id": {"type": "string"},
                "to_email": {"type": "string"},
            },
            "required": ["loan_id", "to_email"],
        },
    },
    {
        "name": "update_contact",
        "description": "Update the phone and/or email on a customer record.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "phone": {"type": ["string", "null"]},
                "email": {"type": ["string", "null"]},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "escalate",
        "description": "Hand the case to a human servicing agent.",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
    {
        "name": TERMINAL_TOOL,
        "description": "End the case with a summary and the list of actions taken.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "actions_taken": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "actions_taken"],
        },
    },
]

_TOOL_NAMES = {schema["name"] for schema in TOOL_SCHEMAS}

_PROMPT_TEMPLATE = """You are Harbour, the loan-servicing agent for a regulated lender.
Work the customer's request using the tools below. Follow the servicing policy exactly.

=== SERVICING POLICY ===
{policy}
=== END POLICY ===

=== TOOLS ===
{tools}
=== END TOOLS ===

Take one action per turn. Reply with a single JSON object and nothing else:

{{"tool": "<tool name>", "args": {{...}}}}

Do not wrap the object in a markdown code fence. Do not write any prose before
or after it. Do not add comments. The first character of your reply must be
'{{' and the last must be '}}'.

When the request is fully handled, call {terminal} with a short summary and the
list of actions you took.
"""


def load_policy() -> str:
    """Read ``policy.md``, checking the package directory then its parent."""
    here = Path(__file__).resolve().parent
    override = os.environ.get("HARBOUR_POLICY_FILE")
    candidates = [Path(override)] if override else []
    candidates += [here / "policy.md", here.parent / "policy.md"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return "(policy.md not found; apply standard servicing rules.)"


def build_system_prompt(policy: str | None = None) -> str:
    tool_lines = "\n".join(
        json.dumps(schema, separators=(",", ":")) for schema in TOOL_SCHEMAS
    )
    return _PROMPT_TEMPLATE.format(
        policy=(policy if policy is not None else load_policy()).strip(),
        tools=tool_lines,
        terminal=TERMINAL_TOOL,
    )


def _parse_action(content: str) -> dict[str, Any] | None:
    """Pull the action object out of a model reply."""
    text = content.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Some snapshots put a full stop or a stray newline after the object.
        try:
            parsed = json.loads(text.rstrip(". \n"))
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None
    tool = parsed.get("tool")
    if not isinstance(tool, str) or tool not in _TOOL_NAMES:
        return None
    args = parsed.get("args")
    return {"tool": tool, "args": args if isinstance(args, dict) else {}}


_FREE_TEXT_KEYS = ("note", "notes", "reason", "comment", "memo", "description")


def _free_text(value: Any) -> Iterable[str]:
    """Yield the operator- and customer-authored prose inside a tool result."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FREE_TEXT_KEYS and isinstance(item, str) and item.strip():
                yield item.strip()
            else:
                yield from _free_text(item)
    elif isinstance(value, list):
        for item in value:
            yield from _free_text(item)


def _render_result(tool: str, result: Any) -> str:
    parts = [f"Result of {tool}: {json.dumps(result, default=str)}"]
    parts.extend(_free_text(result))
    return "\n".join(parts)


def _call_tool(
    backend: Any, case_id: str, tool: str, args: dict[str, Any]
) -> tuple[bool, Any]:
    handler: Callable[..., Any] | None = getattr(backend, tool, None)
    if handler is None:
        return False, f"unknown tool {tool!r}"
    try:
        return True, handler(case_id, **args)
    except Exception as exc:  # noqa: BLE001 - surfaced back to the model
        return False, f"{type(exc).__name__}: {exc}"


def run_case(
    backend: Any,
    case_id: str,
    customer_id: str,
    message: str,
    *,
    loan_id: str | None = None,
) -> dict[str, Any]:
    """Handle one servicing case end to end.

    Returns ``{"case_id", "summary", "actions_taken", "trace_id", "steps"}``.
    """
    trace_id = tracing.new_trace()
    tracing.set_case_id(case_id)

    system_prompt = build_system_prompt()
    opening = (
        f"Case {case_id}. Customer {customer_id}."
        + (f" Loan {loan_id}." if loan_id else "")
        + f"\nCustomer message:\n{message}"
    )

    actions_taken: list[str] = []
    summary = ""
    committed = False
    carried_transcript: list[str] = []
    steps = 0

    with tracing.start_span("case", **{"harbour.case_id": case_id}):
        for attempt in range(MAX_ATTEMPTS):
            messages: list[dict[str, str]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": opening},
            ]
            for note in carried_transcript:
                messages.append({"role": "user", "content": note})

            attempt_actions: list[str] = []
            needs_retry = False

            for _ in range(MAX_STEPS_PER_ATTEMPT):
                steps += 1
                response = llm.complete(messages, max_tokens=800)
                content = response.get("content") or ""
                messages.append({"role": "assistant", "content": content})

                action = _parse_action(content)
                if action is None:
                    # Nothing actionable came back; stop working this case.
                    summary = summary or "No action taken."
                    return {
                        "case_id": case_id,
                        "summary": summary,
                        "actions_taken": actions_taken,
                        "trace_id": trace_id,
                        "steps": steps,
                    }

                tool = action["tool"]
                args = action["args"]

                if tool == TERMINAL_TOOL:
                    summary = str(args.get("summary", ""))
                    reported = args.get("actions_taken")
                    if isinstance(reported, list):
                        attempt_actions.extend(str(a) for a in reported)
                    ok, result = _call_tool(
                        backend,
                        case_id,
                        TERMINAL_TOOL,
                        {
                            "summary": summary,
                            "actions_taken": list(dict.fromkeys(attempt_actions)),
                        },
                    )
                    if ok:
                        committed = True
                        actions_taken = list(dict.fromkeys(attempt_actions))
                        break
                    needs_retry = True
                    messages.append(
                        {"role": "user", "content": _render_result(tool, result)}
                    )
                    break

                ok, result = _call_tool(backend, case_id, tool, args)
                if ok:
                    attempt_actions.append(tool)
                    messages.append(
                        {"role": "user", "content": _render_result(tool, result)}
                    )
                else:
                    needs_retry = True
                    messages.append(
                        {"role": "user", "content": _render_result(tool, result)}
                    )
                    break

            if committed:
                break

            if needs_retry and attempt < MAX_ATTEMPTS - 1:
                # Start the conversation over with what we learned last time, so
                # the model does not repeat the step that failed.
                carried_transcript.append(
                    "Previous attempt transcript:\n"
                    + "\n".join(
                        f"{m['role']}: {m['content']}" for m in messages[2:]
                    )
                )
                continue

            actions_taken = list(dict.fromkeys(attempt_actions))
            break

    if not summary:
        summary = "Case ended without a commit."

    return {
        "case_id": case_id,
        "summary": summary,
        "actions_taken": actions_taken,
        "trace_id": trace_id,
        "steps": steps,
    }
