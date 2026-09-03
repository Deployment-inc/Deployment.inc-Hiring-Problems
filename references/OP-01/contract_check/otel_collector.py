"""Minimal OTLP/HTTP trace receiver for the OP-01 harness.

Accepts POST /v1/traces in protobuf (the default of every OpenTelemetry SDK) or JSON
encoding, keeps spans in memory, and serves them back by trace id.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import struct
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

MODEL_ATTR = "gen_ai.usage.input_tokens"
TOOL_ATTR = "gen_ai.tool.name"
Span = dict[str, Any]


# --- protobuf wire decoding (opentelemetry/proto/trace/v1/trace.proto) ----------------
def _varint(buf: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return result, i


def fields(buf: bytes) -> list[tuple[int, int, Any]]:
    """Decode one message into (field_number, wire_type, value) triples."""
    out, i = [], 0
    while i < len(buf):
        tag, i = _varint(buf, i)
        num, wt = tag >> 3, tag & 7
        if wt == 0:
            val, i = _varint(buf, i)
        elif wt == 1:
            val, i = buf[i:i + 8], i + 8
        elif wt == 2:
            ln, i = _varint(buf, i)
            val, i = buf[i:i + ln], i + ln
        elif wt == 5:
            val, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wt}")
        out.append((num, wt, val))
    return out


def _any_value(buf: bytes) -> Any:
    for num, _, val in fields(buf):
        if num == 1:
            return val.decode("utf-8", "replace")
        if num == 2:
            return bool(val)
        if num == 3:
            return val - (1 << 64) if val >= 1 << 63 else val
        if num == 4:
            return struct.unpack("<d", val)[0]
        if num == 5:
            return [_any_value(v) for n, _, v in fields(val) if n == 1]
        if num == 6:
            return _kvs([v for n, _, v in fields(val) if n == 1])
        if num == 7:
            return base64.b64encode(val).decode()
    return None


def _kvs(pairs: list[bytes]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kv in pairs:
        key, value = "", None
        for n, _, v in fields(kv):
            if n == 1:
                key = v.decode("utf-8", "replace")
            elif n == 2:
                value = _any_value(v)
        out[key] = value
    return out


def _span_pb(buf: bytes, resource: dict[str, Any]) -> Span:
    s: Span = {"trace_id": "", "span_id": "", "parent_span_id": "", "name": "", "kind": 0,
               "start_ns": 0, "end_ns": 0, "attributes": {}, "status_code": 0, "resource": resource}
    attrs: list[bytes] = []
    for num, _, val in fields(buf):
        if num in (1, 2, 4):
            s[{1: "trace_id", 2: "span_id", 4: "parent_span_id"}[num]] = val.hex()
        elif num == 5:
            s["name"] = val.decode("utf-8", "replace")
        elif num == 6:
            s["kind"] = val
        elif num in (7, 8):
            s["start_ns" if num == 7 else "end_ns"] = struct.unpack("<Q", val)[0]
        elif num == 9:
            attrs.append(val)
        elif num == 15:
            s["status_code"] = next((v for n, _, v in fields(val) if n == 3), 0)
    s["attributes"] = _kvs(attrs)
    return s


def decode_protobuf(body: bytes) -> list[Span]:
    spans: list[Span] = []
    for num, _, rs in fields(body):
        if num != 1:
            continue
        resource: dict[str, Any] = {}
        scope_spans: list[bytes] = []
        for n, _, v in fields(rs):
            if n == 1:
                resource = _kvs([kv for k, _, kv in fields(v) if k == 1])
            elif n == 2:
                scope_spans.append(v)
        for ss in scope_spans:
            spans += [_span_pb(sp, resource) for n, _, sp in fields(ss) if n == 2]
    return spans


# --- JSON encoding -------------------------------------------------------------------
def _g(obj: dict[str, Any], *names: str, default: Any = None) -> Any:
    return next((obj[n] for n in names if n in obj), default)


def _id_json(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    if len(value) in (16, 32) and all(c in "0123456789abcdefABCDEF" for c in value):
        return value.lower()
    try:
        return base64.b64decode(value).hex()
    except ValueError:
        return ""


def _any_json(v: dict[str, Any]) -> Any:
    for camel, snake, cast in (("stringValue", "string_value", str), ("intValue", "int_value", int),
                               ("doubleValue", "double_value", float), ("boolValue", "bool_value", bool),
                               ("bytesValue", "bytes_value", str)):
        if camel in v or snake in v:
            return cast(_g(v, camel, snake))
    if arr := _g(v, "arrayValue", "array_value"):
        return [_any_json(x) for x in arr.get("values", [])]
    if kvl := _g(v, "kvlistValue", "kvlist_value"):
        return _kvs_json(kvl.get("values", []))
    return None


def _kvs_json(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {kv.get("key", ""): _any_json(kv.get("value") or {}) for kv in items}


def decode_json(body: bytes) -> list[Span]:
    spans: list[Span] = []
    for rs in _g(json.loads(body), "resourceSpans", "resource_spans", default=[]):
        resource = _kvs_json((rs.get("resource") or {}).get("attributes", []))
        for ss in _g(rs, "scopeSpans", "scope_spans", default=[]):
            for sp in ss.get("spans", []):
                spans.append({
                    "trace_id": _id_json(_g(sp, "traceId", "trace_id", default="")),
                    "span_id": _id_json(_g(sp, "spanId", "span_id", default="")),
                    "parent_span_id": _id_json(_g(sp, "parentSpanId", "parent_span_id", default="")),
                    "name": sp.get("name", ""), "kind": sp.get("kind", 0),
                    "start_ns": int(_g(sp, "startTimeUnixNano", "start_time_unix_nano", default=0) or 0),
                    "end_ns": int(_g(sp, "endTimeUnixNano", "end_time_unix_nano", default=0) or 0),
                    "attributes": _kvs_json(sp.get("attributes", [])),
                    "status_code": (sp.get("status") or {}).get("code", 0), "resource": resource})
    return spans


# --- store and app -------------------------------------------------------------------
class Collector:
    def __init__(self) -> None:
        self.traces: dict[str, list[Span]] = {}
        self.requests = 0

    def ingest(self, body: bytes, content_type: str, encoding: str) -> int:
        if "gzip" in encoding:
            body = gzip.decompress(body)
        spans = decode_json(body) if "json" in content_type else decode_protobuf(body)
        for s in spans:
            self.traces.setdefault(s["trace_id"], []).append(s)
        self.requests += 1
        return len(spans)

    def trace(self, trace_id: str) -> dict[str, Any] | None:
        spans = self.traces.get(trace_id.lower())
        if spans is None:
            return None
        model = [s for s in spans if MODEL_ATTR in s["attributes"]]
        tools = [s for s in spans if TOOL_ATTR in s["attributes"]]

        def num(s: Span, key: str) -> float:
            v = s["attributes"].get(key)
            return float(v) if isinstance(v, (int, float)) else 0.0

        return {
            "trace_id": trace_id, "span_count": len(spans), "spans": spans,
            "roots": [s["span_id"] for s in spans if not s["parent_span_id"]],
            "model_calls": [{"span_id": s["span_id"], "name": s["name"],
                             "model": s["attributes"].get("gen_ai.response.model"),
                             "input_tokens": int(num(s, "gen_ai.usage.input_tokens")),
                             "output_tokens": int(num(s, "gen_ai.usage.output_tokens")),
                             "cost_usd": num(s, "gen_ai.usage.cost_usd")} for s in model],
            "tool_calls": [{"span_id": s["span_id"], "name": s["name"], "tool": s["attributes"].get(TOOL_ATTR),
                            "operation": s["attributes"].get("gen_ai.operation.name")} for s in tools],
            "totals": {"input_tokens": int(sum(num(s, "gen_ai.usage.input_tokens") for s in model)),
                       "output_tokens": int(sum(num(s, "gen_ai.usage.output_tokens") for s in model)),
                       "cost_usd": sum(num(s, "gen_ai.usage.cost_usd") for s in model)},
        }


def create_app(collector: Collector) -> FastAPI:
    app = FastAPI(title="OP-01 OTLP collector")

    @app.post("/v1/traces")
    async def traces(request: Request) -> Response:
        ctype = request.headers.get("content-type", "application/x-protobuf")
        try:
            collector.ingest(await request.body(), ctype, request.headers.get("content-encoding", ""))
        except Exception as exc:  # malformed payloads are the client's problem, never ours
            return JSONResponse({"error": f"could not decode OTLP payload: {exc}"}, 400)
        return Response(b"{}" if "json" in ctype else b"", media_type=ctype)

    @app.get("/_traces/{trace_id}")
    async def get_trace(trace_id: str) -> Response:
        found = collector.trace(trace_id)
        return JSONResponse(found) if found else JSONResponse({"error": "unknown trace"}, 404)

    @app.get("/_stats")
    async def stats() -> dict[str, int]:
        return {"requests": collector.requests, "traces": len(collector.traces),
                "spans": sum(len(v) for v in collector.traces.values())}

    return app


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="OP-01 in-memory OTLP/HTTP trace collector")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8602)
    args = ap.parse_args(argv)
    uvicorn.run(create_app(Collector()), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
