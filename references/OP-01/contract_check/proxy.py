"""OpenAI-compatible fault-injecting gateway for the OP-01 contract harness.

Sits at LLM_BASE_URL in front of the candidate service, forwards /v1/chat/completions and
/v1/responses (streaming or not) to UPSTREAM_BASE_URL, applies one fault mode and one
prompt regression, and keeps a token/cost ledger from upstream `usage` objects.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import math
import os
import secrets
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import uvicorn
import yaml
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

FAULT_MODES = ("none", "http500", "http429", "slow10x", "malformed", "tool_timeout", "drop_stream")
REGRESSIONS = ("none", "strip_system_prompt", "truncate_output", "scramble_tool_args", "model_identity_drift", "flip_tool_args")
MODEL_PATHS = ("/v1/chat/completions", "/v1/responses")
TRUNCATE_AT = 40
SLOW_FLOOR_S = 35.0
TOOL_TIMEOUT_S = 60.0
Usage = tuple[str, int, int]  # (model, input_tokens, output_tokens)
Prices = dict[str, tuple[float, float]]


class Dropped(Exception):
    """Raised inside a response body to close the socket mid-body (drop_stream)."""


class _QuietDrops(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if isinstance(exc, BaseExceptionGroup):
            exc = exc.exceptions[0]
        return not isinstance(exc, Dropped)


logging.getLogger("uvicorn.error").addFilter(_QuietDrops())


# --- pricing -------------------------------------------------------------------------
def load_prices(path: str | os.PathLike[str]) -> Prices:
    data = yaml.safe_load(Path(path).read_text()) or {}
    result = {}
    for model, values in data.items():
        pair = (values["input"], values["output"])
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in pair):
            raise ValueError(f"invalid price for {model}")
        result[str(model)] = tuple(float(v) for v in pair)
    return result


def load_upstream_headers() -> dict[str, str]:
    """Reviewer-only gateway access headers; never included in candidate environment or logs."""
    headers = json.loads(os.environ.get("UPSTREAM_HEADERS_JSON", "{}"))
    if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str)
            or k.lower() in ("host", "content-length", "authorization")
            or any(c in k + v for c in "\r\n") for k,v in headers.items()):
        raise ValueError("UPSTREAM_HEADERS_JSON must contain safe string header pairs")
    return headers


def price_for(prices: Prices, model: str) -> tuple[float, float] | None:
    # A model's name is not proof that another model's price applies to it.
    return prices.get(model) if model != "default" else None


def cost_of(prices: Prices, usage: Usage) -> float | None:
    model, i, o = usage
    rates = price_for(prices, model)
    if rates is None:
        return None
    pi, po = rates
    return i * pi / 1e6 + o * po / 1e6


def extract_usage(obj: Any) -> Usage | None:
    """(model, input, output) from a chat/responses object or a stream event, else None."""
    if not isinstance(obj, dict):
        return None
    resp = obj.get("response") if obj.get("type") == "response.completed" else obj
    usage = resp.get("usage") if isinstance(resp, dict) else None
    if not isinstance(usage, dict):
        return None
    i = usage.get("prompt_tokens", usage.get("input_tokens"))
    o = usage.get("completion_tokens", usage.get("output_tokens"))
    if type(i) is not int or type(o) is not int or i < 0 or o < 0:
        return None
    model = resp.get("model")
    if not isinstance(model, str) or not model:
        return None
    return model, i, o


# --- mutations (regressions and the `malformed` fault) --------------------------------
def mutate_request(payload: dict[str, Any], regression: str) -> dict[str, Any]:
    if regression != "strip_system_prompt":
        return payload
    p = copy.deepcopy(payload)
    roles = ("system", "developer")
    if isinstance(p.get("messages"), list):
        p["messages"] = [m for m in p["messages"] if m.get("role") not in roles]
    p.pop("instructions", None)
    if isinstance(p.get("input"), list):
        p["input"] = [m for m in p["input"] if not (isinstance(m, dict) and m.get("role") in roles)]
    return p


def _flip(arguments: str) -> str:
    try:
        args = json.loads(arguments)
    except (TypeError, ValueError):
        return arguments
    if not isinstance(args, dict) or not args:
        return arguments
    keys = list(args)
    if len(keys) == 1:
        return json.dumps({keys[0]: keys[0]})
    vals = [args[k] for k in keys]
    return json.dumps(dict(zip(keys, vals[1:] + vals[:1])))


def _text(text: str, regression: str, fault: str) -> str:
    if fault == "malformed":
        return '{"answer": "' + text[:20]
    if regression in ("scramble_tool_args", "flip_tool_args"):
        try:
            action = json.loads(text)
            if isinstance(action, dict) and action.get("tool") and isinstance(action.get("args"), dict):
                action["args"] = json.loads(_flip(json.dumps(action["args"])))
                return json.dumps(action)
        except (ValueError, TypeError):
            pass
    return text[:TRUNCATE_AT] if regression == "truncate_output" else text


def _args(arguments: str, regression: str, fault: str) -> str:
    if fault == "malformed":
        return arguments[: len(arguments) // 2]
    return _flip(arguments) if regression in ("scramble_tool_args", "flip_tool_args") else arguments


def mutate_response(obj: dict[str, Any], regression: str, fault: str) -> dict[str, Any]:
    """Apply output regressions / the malformed fault to a non-streaming chat or responses object."""
    obj = copy.deepcopy(obj)
    if regression == "model_identity_drift":
        obj["model"] = str(obj.get("model", "unknown")) + "-unapproved"
    for choice in obj.get("choices") or []:
        msg = choice.get("message") or {}
        if isinstance(msg.get("content"), str):
            msg["content"] = _text(msg["content"], regression, fault)
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            if isinstance(fn.get("arguments"), str):
                fn["arguments"] = _args(fn["arguments"], regression, fault)
    for item in obj.get("output") or []:
        if item.get("type") == "function_call" and isinstance(item.get("arguments"), str):
            item["arguments"] = _args(item["arguments"], regression, fault)
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                part["text"] = _text(part["text"], regression, fault)
    return obj


def synthesize_stream(obj: dict[str, Any]) -> list[bytes]:
    """Re-emit a non-streaming object as a minimal SSE stream (used after mutation)."""
    events: list[dict[str, Any]] = []
    if "choices" in obj:
        chunk: dict[str, Any] = {k: obj[k] for k in ("id", "created", "model") if k in obj}
        chunk.update(object="chat.completion.chunk", choices=[])
        for ch in obj.get("choices") or []:
            delta = {k: v for k, v in (ch.get("message") or {}).items() if v is not None}
            for i, call in enumerate(delta.get("tool_calls") or []):
                call["index"] = i
            chunk["choices"].append({"index": ch.get("index", 0), "delta": delta, "finish_reason": ch.get("finish_reason")})
        if "usage" in obj:
            chunk["usage"] = obj["usage"]
        events.append(chunk)
    else:
        for item in obj.get("output") or []:
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    events.append({"type": "response.output_text.delta", "delta": part["text"]})
        events.append({"type": "response.completed", "response": obj})
    return [f"data: {json.dumps(e)}\n\n".encode() for e in events] + [b"data: [DONE]\n\n"]


# --- gateway -------------------------------------------------------------------------
def _loads(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _err(status: int, message: str, kind: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": kind}}, status, headers=headers)


async def _stall(request: Request, seconds: float) -> bool:
    """Sleep, polling for client disconnect. False if the client went away."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if await request.is_disconnected():
            return False
        await asyncio.sleep(0.2)
    return True


@dataclass
class Ledger:
    requests: int = 0
    authorized: int = 0
    unauthorized: int = 0
    in_flight: int = 0
    scenario_calls: int = 0
    spend_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    by_model: dict[str, float] = field(default_factory=dict)
    latencies_ms: list[float] = field(default_factory=list)
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, prices: Prices, usage: Usage, entry: dict[str, Any] | None = None) -> None:
        cost = cost_of(prices, usage)
        if entry is not None:
            entry.update(model=usage[0], input_tokens=usage[1], output_tokens=usage[2], cost_usd=cost, measurement_status="usage_observed" if cost is not None else "price_unavailable")
        if cost is not None:
            self.spend_usd += cost
        self.input_tokens += usage[1]
        self.output_tokens += usage[2]
        if cost is not None:
            self.by_model[usage[0]] = self.by_model.get(usage[0], 0.0) + cost


class Gateway:
    def __init__(self, upstream: str, upstream_key: str, gateway_key: str, prices: Prices,
                 fault: str = "none", regression: str = "none", control_key: str | None = None) -> None:
        if fault not in FAULT_MODES or regression not in REGRESSIONS:
            raise ValueError(f"unknown fault {fault!r} or regression {regression!r}")
        self.upstream, self.upstream_key, self.gateway_key = upstream.rstrip("/"), upstream_key, gateway_key
        self.prices, self.fault, self.regression = prices, fault, regression
        self.control_key = control_key or secrets.token_hex(32)
        self.extra_upstream_headers = load_upstream_headers()
        self.case_id: str | None = None
        self.run_id = "local-contract"
        self.ledger = Ledger()
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))

    def stats(self) -> dict[str, Any]:
        led = self.ledger
        med = statistics.median(led.latencies_ms) if led.latencies_ms else None
        return {"requests": led.requests, "authorized": led.authorized, "unauthorized": led.unauthorized,
                "in_flight": led.in_flight, "scenario_calls": led.scenario_calls, "spend_usd": led.spend_usd if all(e["measurement_status"] not in ("usage_unavailable", "price_unavailable") for e in led.entries) else None,
                "observed_priced_spend_usd": led.spend_usd,
                "input_tokens": led.input_tokens, "output_tokens": led.output_tokens, "by_model": led.by_model,
                "median_latency_ms": med, "fault_mode": self.fault, "regression": self.regression,
                "ledger_entries": len(led.entries),
                "unmetered_calls": sum(e["measurement_status"] in ("usage_unavailable", "price_unavailable") for e in led.entries)}

    def control(self, body: dict[str, Any]) -> dict[str, Any]:
        fault = body.get("fault_mode", self.fault)
        regression = body.get("regression", self.regression)
        if fault not in FAULT_MODES or regression not in REGRESSIONS:
            raise ValueError(f"fault_mode must be one of {FAULT_MODES}, regression one of {REGRESSIONS}")
        for key in ("case_id", "run_id"):
            if key in body:
                value = body[key]
                if not isinstance(value, str) or not value or len(value) > 200:
                    raise ValueError(f"{key} must be a nonempty string at most 200 characters")
                setattr(self, key, value)
        self.fault, self.regression, self.ledger.scenario_calls = fault, regression, 0
        return self.stats()

    def _headers(self, request: Request) -> dict[str, str]:
        key = self.upstream_key or request.headers.get("authorization", "").removeprefix("Bearer ")
        return {"authorization": f"Bearer {key}", "content-type": "application/json",
                "accept": request.headers.get("accept", "*/*"), **self.extra_upstream_headers}

    def _latency(self, t0: float) -> None:
        self.ledger.latencies_ms.append((time.monotonic() - t0) * 1000)
        del self.ledger.latencies_ms[:-50]

    async def relay(self, request: Request, path: str) -> Response:
        led, raw = self.ledger, await request.body()
        authorized = not self.gateway_key or request.headers.get("authorization") == f"Bearer {self.gateway_key}"
        if path not in MODEL_PATHS:
            if not authorized:
                return _err(401, "invalid gateway key", "authentication_error")
            return _err(404, "endpoint not metered by this gateway", "unsupported_endpoint")
        led.requests += 1
        if not authorized:
            led.unauthorized += 1
            return _err(401, "invalid gateway key", "authentication_error")
        led.authorized += 1
        led.scenario_calls += 1
        led.in_flight += 1
        response: Response | None = None
        entry = {"run_id": self.run_id, "case_id": self.case_id or f"request-{led.authorized}",
                 "call_id": f"call-{led.authorized}", "model": None, "input_tokens": None,
                 "output_tokens": None, "cost_usd": None, "measurement_status": "usage_unavailable"}
        led.entries.append(entry)
        try:
            response = await self._model_call(request, path, raw, led.scenario_calls, entry)
            return response
        finally:
            if not isinstance(response, StreamingResponse):  # streaming bodies decrement themselves
                led.in_flight -= 1

    async def _model_call(self, request: Request, path: str, raw: bytes, n: int, entry: dict[str, Any]) -> Response:
        fault, regression, led = self.fault, self.regression, self.ledger
        if fault in ("http500", "slow10x", "tool_timeout") or (fault == "http429" and n <= 2):
            entry.update(input_tokens=0, output_tokens=0, cost_usd=0.0, measurement_status="injected_before_provider")
        if fault == "http500":
            return _err(500, "injected upstream failure", "server_error")
        if fault == "http429" and n <= 2:
            return _err(429, "injected rate limit", "rate_limit_error", {"Retry-After": "1"})
        if fault in ("slow10x", "tool_timeout"):
            median_s = (statistics.median(led.latencies_ms) / 1000) if led.latencies_ms else 0.0
            delay = TOOL_TIMEOUT_S if fault == "tool_timeout" else max(SLOW_FLOOR_S, 10 * median_s)
            if not await _stall(request, delay):
                return Response(status_code=499)
        payload = _loads(raw) if raw else {}
        if not isinstance(payload, dict):
            entry.update(input_tokens=0, output_tokens=0, cost_usd=0.0, measurement_status="rejected_before_provider")
            return _err(400, "body must be a JSON object", "invalid_request_error")
        want_stream, mutate = bool(payload.get("stream")), regression != "none" or fault == "malformed"
        drop = fault == "drop_stream" and n == 1
        payload = mutate_request(payload, regression)
        if want_stream and (mutate or drop):
            # Retain complete provider usage before deliberately truncating the client stream.
            payload["stream"] = False
            payload.pop("stream_options", None)
        elif want_stream and path == "/v1/chat/completions":
            payload["stream_options"] = {"include_usage": True}
        entry.update(model=payload.get("model"), input_tokens=None, output_tokens=None, cost_usd=None, measurement_status="usage_unavailable")
        upstream = self.client.build_request("POST", self.upstream + path.removeprefix("/v1"),
                                             content=json.dumps(payload).encode(), headers=self._headers(request))
        t0 = time.monotonic()
        try:
            resp = await self.client.send(upstream, stream=True)
        except httpx.HTTPError as exc:
            return _err(502, f"gateway could not reach upstream: {exc}", "gateway_error")
        entry["upstream_http_status"] = resp.status_code
        if resp.status_code in (301, 302, 303, 307, 308):
            await resp.aclose()
            return _err(502, "upstream redirected; reviewer must check its URL and gateway authentication", "gateway_redirect")
        ctype = resp.headers.get("content-type", "application/json")
        if want_stream and not mutate and not drop:
            return StreamingResponse(self._pipe(resp, t0, entry), resp.status_code, media_type=ctype)
        body = await resp.aread()
        await resp.aclose()
        self._latency(t0)
        obj = _loads(body)
        if resp.status_code == 200 and isinstance(obj, dict):
            if usage := extract_usage(obj):
                led.record(self.prices, usage, entry)
            if mutate:
                obj = mutate_response(obj, regression, fault)
                body = json.dumps(obj).encode()
            if want_stream:
                return self._emit(synthesize_stream(obj), "text/event-stream", drop)
        if drop:
            return self._emit([body], ctype, True)
        return Response(body, resp.status_code, media_type=ctype)

    async def _pipe(self, resp: httpx.Response, t0: float, entry: dict[str, Any]) -> AsyncIterator[bytes]:
        """Byte-exact stream pass-through that records usage from the SSE events."""
        led, buf = self.ledger, b""
        latest_usage = None
        try:
            async for chunk in resp.aiter_raw():
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.startswith(b"data:") and (usage := extract_usage(_loads(line[5:].strip()))):
                        latest_usage = usage
                yield chunk
        finally:
            if latest_usage is not None:
                led.record(self.prices, latest_usage, entry)
            await resp.aclose()
            self._latency(t0)
            led.in_flight -= 1

    def _emit(self, parts: list[bytes], media_type: str, drop: bool) -> StreamingResponse:
        led = self.ledger

        async def gen() -> AsyncIterator[bytes]:
            try:
                if drop:
                    head = b"".join(parts)
                    yield head[: max(1, len(head) // 2)]
                    raise Dropped()
                for part in parts:
                    yield part
            finally:
                led.in_flight -= 1

        return StreamingResponse(gen(), media_type=media_type)


def create_app(gateway: Gateway) -> FastAPI:
    app = FastAPI(title="OP-01 gateway")

    @app.get("/_stats")
    async def stats(request: Request) -> Response:
        if request.headers.get("authorization") != "Bearer " + gateway.control_key:
            return _err(401, "reviewer control key required", "authentication_error")
        return JSONResponse(gateway.stats())

    @app.get("/_ledger")
    async def ledger_export(request: Request) -> Response:
        if request.headers.get("authorization") != "Bearer " + gateway.control_key:
            return _err(401, "reviewer control key required", "authentication_error")
        body = "".join(json.dumps(e, allow_nan=False) + "\n" for e in gateway.ledger.entries)
        return Response(body, media_type="application/x-ndjson")

    @app.post("/_control")
    async def control(request: Request) -> Response:
        if request.headers.get("authorization") != "Bearer " + gateway.control_key:
            return _err(401, "reviewer control key required", "authentication_error")
        try:
            return JSONResponse(gateway.control(await request.json()))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, 400)

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def relay(path: str, request: Request) -> Response:
        return await gateway.relay(request, "/" + path)

    return app


def gateway_from_env() -> Gateway:
    prices = load_prices(os.environ.get("PRICES") or Path(__file__).with_name("prices.yaml"))
    return Gateway(os.environ.get("UPSTREAM_BASE_URL", "https://api.openai.com/v1"),
                   os.environ.get("UPSTREAM_API_KEY") or os.environ.get("OPENAI_API_KEY", ""),
                   os.environ.get("GATEWAY_API_KEY", ""), prices,
                   os.environ.get("FAULT_MODE", "none"), os.environ.get("REGRESSION", "none"),
                   control_key=os.environ.get("GATEWAY_CONTROL_KEY"))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="OP-01 fault-injecting OpenAI-compatible gateway")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8601)
    args = ap.parse_args(argv)
    uvicorn.run(create_app(gateway_from_env()), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
