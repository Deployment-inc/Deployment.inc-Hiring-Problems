"""Reference-compliant example service for the OP-05 Production Contract.

A deliberately small agent (one tool, one model) wrapped the way the contract requires:
gateway routing, honest health/readiness, OTLP traces, a hard spend cap, bounded retries,
idempotency keys, configuration from the environment only. `python example_service.py`
serves it; `python example_service.py eval` runs its 50-case eval against TARGET_URL and
writes eval_report.json in the current directory.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contract_check.proxy import cost_of, load_prices  # noqa: E402

SYSTEM_PROMPT = 'Call the lookup tool for the user text, then answer as JSON {"answer": ...} in UPPERCASE.'
TOOLS = [{"type": "function", "function": {"name": "lookup", "parameters": {
    "type": "object", "properties": {"key": {"type": "string"}, "field": {"type": "string"}}}}}]
RETRIES = 3
CALL_TIMEOUT_S = float(os.environ.get("EXAMPLE_CALL_TIMEOUT_S", "10"))
RUN_BUDGET_S = float(os.environ.get("EXAMPLE_RUN_BUDGET_S", "25"))


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code = status, code


class Config:
    def __init__(self) -> None:
        env = os.environ
        self.base_url = env.get("LLM_BASE_URL", "").rstrip("/")
        self.api_key = env.get("LLM_API_KEY", "")
        self.otel = env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
        self.version = env.get("APP_VERSION", "dev")
        self.model = env.get("LLM_MODEL", "stub-1")
        self.error = ""
        try:
            self.max_spend = float(env["MAX_SPEND_USD"])
        except (KeyError, ValueError):
            self.max_spend, self.error = 0.0, "MAX_SPEND_USD must be a decimal number"
        if not self.base_url or not self.api_key:
            self.error = self.error or "LLM_BASE_URL and LLM_API_KEY are required"
        self.prices = load_prices(env["PRICES"]) if env.get("PRICES") else {"default": (1.0, 4.0)}


def kv(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        v: dict[str, Any] = {"boolValue": value}
    elif isinstance(value, int):
        v = {"intValue": str(value)}
    elif isinstance(value, float):
        v = {"doubleValue": value}
    else:
        v = {"stringValue": str(value)}
    return {"key": key, "value": v}


class Trace:
    """A hand-rolled trace, exported as OTLP/JSON when the request ends."""

    def __init__(self) -> None:
        self.id = secrets.token_hex(16)
        self.spans: list[dict[str, Any]] = []

    def span(self, name: str, parent: str = "") -> dict[str, Any]:
        s = {"traceId": self.id, "spanId": secrets.token_hex(8), "parentSpanId": parent, "name": name, "kind": 1,
             "startTimeUnixNano": str(time.time_ns()), "endTimeUnixNano": "0", "attributes": [], "status": {"code": 1}}
        self.spans.append(s)
        return s

    @staticmethod
    def end(s: dict[str, Any], **attrs: Any) -> None:
        s["endTimeUnixNano"] = str(time.time_ns())
        s["attributes"] += [kv(k, v) for k, v in attrs.items()]

    def payload(self) -> dict[str, Any]:
        return {"resourceSpans": [{"resource": {"attributes": [kv("service.name", "op09-example")]},
                                   "scopeSpans": [{"scope": {"name": "example"}, "spans": self.spans}]}]}


def assemble(sse: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Fold a chat-completions SSE body into (message, usage, model). ValueError if malformed."""
    content, calls, usage, model = "", {}, None, ""
    for line in sse.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        model = chunk.get("model") or model
        usage = chunk.get("usage") or usage
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            content += delta.get("content") or ""
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                fn = tc.get("function") or {}
                slot["id"], slot["name"] = tc.get("id") or slot["id"], fn.get("name") or slot["name"]
                slot["arguments"] += fn.get("arguments") or ""
    if not isinstance(usage, dict):
        raise ValueError("stream ended without a usage object")
    return {"content": content, "tool_calls": [calls[i] for i in sorted(calls)]}, usage, model


class Agent:
    def __init__(self, cfg: Config) -> None:
        self.cfg, self.spent = cfg, 0.0
        self.cache: dict[str, tuple[str, dict[str, Any]]] = {}  # idempotency key -> (input, body)
        self.locks: dict[str, asyncio.Lock] = {}
        self.llm = httpx.AsyncClient(base_url=cfg.base_url, headers={"Authorization": f"Bearer {cfg.api_key}"})
        self.otel = httpx.AsyncClient(timeout=3)

    def checks(self) -> dict[str, bool]:
        return {"config_valid": not self.cfg.error, "spend_cap_ok": self.spent < self.cfg.max_spend, "index_loaded": True}

    async def chat(self, messages: list[dict[str, Any]], trace: Trace, root: str, deadline: float) -> tuple[dict[str, Any], float]:
        last = ServiceError(504, "upstream_timeout", "run budget exhausted")
        for attempt in range(RETRIES + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            span = trace.span(f"chat {self.cfg.model}", root)
            try:
                r = await self.llm.post("/chat/completions", timeout=min(CALL_TIMEOUT_S, remaining), json={
                    "model": self.cfg.model, "messages": messages, "tools": TOOLS, "stream": True,
                    "stream_options": {"include_usage": True}})
                if r.status_code == 429:
                    last = ServiceError(503, "upstream_rate_limited", "provider rate limited")
                    await asyncio.sleep(min(float(r.headers.get("retry-after", "1")), max(remaining, 0.0)))
                    continue
                if r.status_code >= 500:
                    last = ServiceError(502, "upstream_error", f"provider returned {r.status_code}")
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                r.raise_for_status()
                msg, usage, model = assemble(r.text)
                if model != self.cfg.model:
                    raise ValueError("upstream returned an unapproved model identity")
            except httpx.TimeoutException:
                last = ServiceError(504, "upstream_timeout", "model call timed out")
            except httpx.HTTPError as exc:
                last = ServiceError(502, "upstream_error", f"transport failure: {exc}")
                await asyncio.sleep(0.2)
            except ValueError as exc:
                last = ServiceError(502, "malformed_model_output", str(exc))
            else:
                tokens = (model, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))
                cost = cost_of(self.cfg.prices, tokens)
                self.spent += cost
                Trace.end(span, **{"gen_ai.operation.name": "chat", "gen_ai.request.model": self.cfg.model,
                                   "gen_ai.response.model": model, "gen_ai.usage.input_tokens": tokens[1],
                                   "gen_ai.usage.output_tokens": tokens[2], "gen_ai.usage.cost_usd": cost})
                return msg, cost
            Trace.end(span, **{"error.type": last.code})
        raise last

    async def run(self, text: str, trace: Trace) -> tuple[str, float]:
        deadline, root, cost = time.monotonic() + RUN_BUDGET_S, trace.span("run"), 0.0
        try:
            messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}]
            msg, c = await self.chat(messages, trace, root["spanId"], deadline)
            cost += c
            if msg["tool_calls"]:
                call = msg["tool_calls"][0]
                try:
                    args = json.loads(call["arguments"])
                except ValueError:
                    raise ServiceError(502, "malformed_model_output", "tool arguments are not valid JSON") from None
                if not isinstance(args, dict):
                    raise ServiceError(502, "malformed_model_output", "tool arguments are not an object")
                tool = trace.span("execute_tool lookup", root["spanId"])
                result = f"{args.get('key')}:{args.get('field')}"
                Trace.end(tool, **{"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "lookup"})
                messages += [{"role": "assistant", "content": None, "tool_calls": [{"id": call["id"], "type": "function",
                              "function": {"name": call["name"], "arguments": call["arguments"]}}]},
                             {"role": "tool", "tool_call_id": call["id"], "content": result}]
                msg, c = await self.chat(messages, trace, root["spanId"], deadline)
                cost += c
            try:
                answer = json.loads(msg["content"] or "")["answer"]
            except (ValueError, KeyError, TypeError):
                raise ServiceError(502, "malformed_model_output", 'final answer is not {"answer": ...}') from None
            return str(answer), cost
        finally:
            Trace.end(root, **{"app.cost_usd": cost})

    async def export(self, trace: Trace) -> None:
        if self.cfg.otel:
            try:
                await self.otel.post(self.cfg.otel + "/v1/traces", json=trace.payload())
            except httpx.HTTPError:
                pass  # telemetry never fails a request


def create_app(cfg: Config) -> FastAPI:
    app, agent = FastAPI(title="OP-05 example service"), Agent(cfg)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": cfg.version}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        checks = agent.checks()
        return JSONResponse({"ready": all(checks.values()), "checks": checks}, 200 if all(checks.values()) else 503)

    async def execute(text: str) -> JSONResponse:
        trace = Trace()
        try:
            if cfg.error:
                raise ServiceError(503, "not_ready", cfg.error)
            if agent.spent >= cfg.max_spend:
                raise ServiceError(503, "spend_cap_reached", f"spent {agent.spent:.6f} of {cfg.max_spend}")
            output, cost = await agent.run(text, trace)
            body, status = {"output": output, "trace_id": trace.id, "cost_usd": cost}, 200
        except ServiceError as exc:
            body, status = {"error": {"code": exc.code, "message": str(exc), "trace_id": trace.id}}, exc.status
        await agent.export(trace)
        return JSONResponse(body, status)

    @app.post("/run")
    async def run(request: Request) -> JSONResponse:
        try:
            data = await request.json()
        except ValueError:
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("input"), str):
            return JSONResponse({"error": {"code": "invalid_request", "message": "body must be {input: string, idempotency_key?: string}"}}, 422)
        key = data.get("idempotency_key")
        if not isinstance(key, str) or not key:
            return await execute(data["input"])
        async with agent.locks.setdefault(key, asyncio.Lock()):
            if key in agent.cache:
                text, body = agent.cache[key]
                if text != data["input"]:
                    return JSONResponse({"error": {"code": "idempotency_conflict", "message": "key already used with a different input"}}, 409)
                return JSONResponse(body, 200)
            resp = await execute(data["input"])
            if resp.status_code == 200:
                agent.cache[key] = (data["input"], json.loads(bytes(resp.body)))
            return resp

    return app


def run_eval() -> int:
    target = os.environ.get("TARGET_URL", "http://127.0.0.1:8000")
    cases = [f"case {i:02d}: the quick brown fox jumps over the lazy dog {i}" for i in range(50)]
    passed = 0
    with httpx.Client(timeout=35) as http:
        for text in cases:
            r = http.post(target + "/run", json={"input": text})
            passed += int(r.status_code == 200 and r.json().get("output") == f"{text}:value".upper())
    report = {"cases": len(cases), "passed": passed, "threshold": 0.9, "pass": passed / len(cases) >= 0.9}
    Path("eval_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["eval"]:
        sys.exit(run_eval())
    uvicorn.run(create_app(Config()), host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), log_level="warning")
