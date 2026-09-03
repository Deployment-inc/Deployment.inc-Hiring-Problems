"""Span emission for Harbour.

Spans are written one-per-line as JSON to ``$HARBOUR_TRACE_FILE`` (default
``traces/otlp.jsonl``) in a flattened OpenTelemetry GenAI shape:

    {"trace_id", "span_id", "parent_span_id", "name", "start_ms", "end_ms",
     "attributes": {...}}

The file is append-only. Nothing here talks to a collector; the exporter that
ships the JSONL onwards lives outside this package.
"""

from __future__ import annotations

import contextvars
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_TRACE_FILE = "traces/otlp.jsonl"

_write_lock = threading.Lock()

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "harbour_trace_id", default=None
)
_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "harbour_span_id", default=None
)
_case_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "harbour_case_id", default=""
)

# Rupee-free: the gateway bills in USD, so prices are per 1M tokens in USD.
_MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "o4-mini": (1.10, 4.40),
}
_FALLBACK_PRICE = (0.50, 1.50)


def trace_file() -> Path:
    """Absolute path of the JSONL trace sink for this process."""
    return Path(os.environ.get("HARBOUR_TRACE_FILE", DEFAULT_TRACE_FILE)).resolve()


def _new_id(width: int) -> str:
    return uuid.uuid4().hex[:width]


def _price(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost of a single model call, rounded to six decimal places."""
    per_in, per_out = _MODEL_PRICES.get(model, _FALLBACK_PRICE)
    cost = (input_tokens * per_in + output_tokens * per_out) / 1_000_000.0
    return round(cost, 6)


def current_trace_id() -> str:
    """Trace id for the calling context, minting one if the context is fresh."""
    tid = _trace_id.get()
    if tid is None:
        tid = _new_id(32)
        _trace_id.set(tid)
    return tid


def set_case_id(case_id: str) -> None:
    """Tag every span emitted from this context with a case id."""
    _case_id.set(case_id)


def current_case_id() -> str:
    return _case_id.get()


def new_trace(trace_id: str | None = None) -> str:
    """Begin a new trace and return its id. Called once per case."""
    tid = trace_id or _new_id(32)
    _trace_id.set(tid)
    _span_id.set(None)
    return tid


def _emit(record: dict[str, Any]) -> None:
    path = trace_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str, separators=(",", ":"))
    with _write_lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class Span:
    """A span in flight. Attributes may be added until the block exits."""

    def __init__(self, name: str, attributes: dict[str, Any]) -> None:
        self.name = name
        self.attributes = dict(attributes)
        self.trace_id = current_trace_id()
        self.span_id = _new_id(16)
        self.parent_span_id = _span_id.get()
        self.start_ms = int(time.time() * 1000)
        self.end_ms: int | None = None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def update(self, **attrs: Any) -> None:
        self.attributes.update(attrs)

    def to_record(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms if self.end_ms is not None else self.start_ms,
            "attributes": self.attributes,
        }


@contextmanager
def start_span(name: str, **attrs: Any) -> Iterator[Span]:
    """Open a span, yield it so callers can attach attributes, then emit it."""
    span = Span(name, attrs)
    token = _span_id.set(span.span_id)
    try:
        yield span
    except Exception as exc:  # noqa: BLE001 - recorded then re-raised
        span.set_attribute("error.type", type(exc).__name__)
        raise
    finally:
        _span_id.reset(token)
        span.end_ms = int(time.time() * 1000)
        _emit(span.to_record())


def record_tool_call(
    tool: str,
    case_id: str,
    *,
    ok: bool,
    duration_ms: int,
    error: str | None = None,
) -> None:
    """Emit a span describing one backend tool invocation."""
    record = {
        "trace_id": current_trace_id(),
        "span_id": _new_id(16),
        "parent_span_id": _span_id.get(),
        "name": f"tool {tool}",
        "start_ms": int(time.time() * 1000) - duration_ms,
        "end_ms": int(time.time() * 1000),
        "attributes": {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool,
            "harbour.case_id": case_id,
            "harbour.ok": ok,
            "error.type": error,
        },
    }
    _emit(record)
