"""OP-01 contract conformance runner.

    python -m contract_check.check --target http://127.0.0.1:8000 \
        --upstream https://api.openai.com/v1 --repo . --start-cmd "make run" --report report.json

Starts the gateway and the OTLP collector in-process, drives the candidate service through
the ten contract items, the fault scenarios and the prompt regressions, and writes a JSON
report. README.md documents the arguments; contract.md defines what each check means.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import math
import os
import re
import secrets
import signal
import socket
import statistics
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
import uvicorn

from . import otel_collector, proxy

FAULTS = ("http500", "http429", "slow10x", "malformed", "tool_timeout", "drop_stream")
REGRESSIONS = ("strip_system_prompt", "truncate_output", "scramble_tool_args", "model_identity_drift")
ITEM_NAMES = {1: "route every model call through LLM_BASE_URL", 2: "/healthz and /readyz",
              3: "OpenTelemetry traces", 4: "hard spend cap", 5: "fault injection", 6: "idempotency key",
              7: "secrets only from the environment", 8: "two versions side by side",
              9: "make eval and prompt regressions", 10: "RUNBOOK, THREAT_MODEL, SLO"}
ORDER = (1, 2, 3, 6, 5, 9, 7, 8, 10, 4)  # the spend cap goes last: afterwards the service refuses work
RUN_BUDGET_S = 30.0
MODEL_SPAN_ATTRS = ("gen_ai.request.model", "gen_ai.response.model", "gen_ai.usage.input_tokens",
                    "gen_ai.usage.output_tokens", "gen_ai.usage.cost_usd")
SECRET_PATTERNS = [re.compile(p) for p in (r"sk-[A-Za-z0-9_-]{20,}", r"AKIA[0-9A-Z]{16}", r"ghp_[A-Za-z0-9]{36}",
                                           r"xox[bp]-[A-Za-z0-9-]{10,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]
DOCKER_SECRET = re.compile(r"^\s*(ENV|ARG)\s+\w*(KEY|SECRET|TOKEN|PASSWORD)\w*[= ]+['\"]?[^\s'\"$]", re.I)
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build"}
DOC_RULES: dict[str, tuple[list[re.Pattern[str]], str]] = {
    "RUNBOOK.md": ([re.compile(r"^#+.*rollback", re.I | re.M)], "no heading containing 'rollback'"),
    "THREAT_MODEL.md": ([re.compile(r"prompt[ -]injection", re.I)], "does not mention prompt injection"),
    "SLO.md": ([re.compile(r"\bp9[59]\b", re.I), re.compile(r"\d+(\.\d+)?\s*%")], "needs a p95/p99 target and a percentage"),
}


class Failure(Exception):
    """A contract check failed; the message becomes the reason in the report."""


class ServerThread(threading.Thread):
    """Runs an ASGI app on uvicorn in a background thread."""

    def __init__(self, app: Any, port: int) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                                    timeout_graceful_shutdown=2))

    def run(self) -> None:
        self.server.run()

    def start(self) -> None:
        super().start()
        for _ in range(100):
            if self.server.started:
                return
            time.sleep(0.05)
        raise RuntimeError(f"server on port {self.port} did not start (port in use?)")

    def stop(self) -> None:
        self.server.should_exit = True
        self.join(5)


class Service:
    """A candidate process the harness owns (--start-cmd)."""

    def __init__(self, cmd: str, cwd: str, name: str) -> None:
        self.cmd, self.cwd = cmd, cwd
        self.log = Path(tempfile.gettempdir()) / f"op01-{name}.log"
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self, env: dict[str, str]) -> None:
        with self.log.open("ab") as log:
            self.proc = subprocess.Popen(self.cmd, shell=True, cwd=self.cwd, env=env, stdout=log,
                                         stderr=subprocess.STDOUT, start_new_session=True)

    def exited(self) -> int | None:
        return self.proc.poll() if self.proc else None

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(self.proc.pid), sig)
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=5)
                return


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def p95(values: list[float]) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return v[max(0, math.ceil(0.95 * len(v)) - 1)]


def _json(r: httpx.Response) -> dict[str, Any]:
    try:
        data = r.json()
    except ValueError:
        return {"raw": r.text[:300]}
    return data if isinstance(data, dict) else {"raw": data}


def _code(body: dict[str, Any]) -> str | None:
    err = body.get("error")
    return err.get("code") if isinstance(err, dict) else None


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.1 * abs(b), 1e-5)


def _brief(run: dict[str, Any]) -> dict[str, Any]:
    body = dict(run["body"])
    if isinstance(body.get("output"), str):
        body["output"] = body["output"][:120]
    return {**run, "body": body}


def _select(value: str | None) -> set[str]:
    return {v.strip() for v in value.split(",") if v.strip()} if value else set()


def validate_eval_report(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["report is not a JSON object"]
    cases, passed, thr, ok = data.get("cases"), data.get("passed"), data.get("threshold"), data.get("pass")
    errs = []
    if not isinstance(cases, int) or isinstance(cases, bool) or cases < 1:
        errs.append("cases must be a positive integer")
    if not isinstance(passed, int) or isinstance(passed, bool) or passed < 0 or (not errs and passed > cases):
        errs.append("passed must be an integer in [0, cases]")
    if not isinstance(thr, (int, float)) or isinstance(thr, bool) or not 0 < thr <= 1:
        errs.append("threshold must be a number in (0, 1]")
    if not isinstance(ok, bool):
        errs.append("pass must be a boolean")
    if not errs and ok != (passed / cases >= thr - 1e-9):
        errs.append("pass does not equal passed / cases >= threshold")
    return errs


def tracked_files(repo: Path) -> list[Path]:
    with contextlib.suppress(OSError):
        git = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
        if git.returncode == 0:
            return [repo / p.decode() for p in git.stdout.split(b"\0") if p]
    out: list[Path] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        out += [Path(root) / f for f in files]
    return out


@dataclass
class Item:
    id: int
    name: str
    status: str = "skip"
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


class Harness:
    def __init__(self, args: argparse.Namespace) -> None:
        self.a = args
        self.items = {i: Item(i, n) for i, n in ITEM_NAMES.items()}
        self.faults: list[dict[str, Any]] = []
        self.regressions: list[dict[str, Any]] = []
        self.latency: dict[str, Any] = {"status": "skip"}
        self.eval_cases: int | None = None
        self.eval_threshold: float | None = None
        self.max_single_calls = 1  # gateway calls in the largest single successful /run seen so far
        self.control_key = secrets.token_hex(32)
        self.gateway_key = args.llm_api_key or os.environ.get("LLM_API_KEY") or secrets.token_hex(16)
        self.upstream_key = os.environ.get("UPSTREAM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        self.http = httpx.Client(timeout=httpx.Timeout(RUN_BUDGET_S + 5, connect=5))
        port = urlparse(args.target).port or 80
        self.service = Service(args.start_cmd, args.repo, f"service-{port}") if args.start_cmd else None
        self.only, self.skip = _select(args.only), _select(args.skip)
        self.proxy_url = f"http://127.0.0.1:{args.proxy_port}"
        self.collector_url = f"http://127.0.0.1:{args.collector_port}"
        self.started_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

    # --- plumbing ---------------------------------------------------------------------
    def selected(self, key: str) -> bool:
        return key in self.only if self.only else key not in self.skip

    def env(self, **override: str) -> dict[str, str]:
        allowed = {"PATH", "LANG", "LC_ALL", "PYTHONPATH", "VIRTUAL_ENV", "LLM_MODEL", "PRICES",
                   "EXAMPLE_CALL_TIMEOUT_S", "EXAMPLE_RUN_BUDGET_S"}
        env = {key: value for key, value in os.environ.items() if key in allowed}
        env.update(LLM_BASE_URL=self.proxy_url + "/v1", LLM_API_KEY=self.gateway_key,
                   MAX_SPEND_USD=str(self.a.max_spend_usd), OTEL_EXPORTER_OTLP_ENDPOINT=self.collector_url,
                   APP_VERSION=self.a.app_version, PORT=str(urlparse(self.a.target).port or 80),
                   TARGET_URL=self.a.target)
        env.update(override)
        return env

    def wait_ready(self, base: str, svc: Service | None) -> None:
        deadline = time.monotonic() + self.a.startup_timeout
        while time.monotonic() < deadline:
            if svc and svc.exited() is not None:
                raise Failure(f"service exited with code {svc.exited()} during startup (log: {svc.log})")
            with contextlib.suppress(httpx.HTTPError):
                if (self.http.get(base + "/healthz", timeout=2).status_code == 200
                        and self.http.get(base + "/readyz", timeout=2).status_code == 200):
                    return
            time.sleep(0.25)
        raise Failure(f"{base} not healthy and ready within {self.a.startup_timeout}s")

    def restart_service(self, **override: str) -> None:
        assert self.service is not None
        self.service.stop()
        self.service.start(self.env(**override))
        self.wait_ready(self.a.target, self.service)

    def stats(self) -> dict[str, Any]:
        return self.http.get(self.proxy_url + "/_stats", headers={"Authorization": "Bearer " + self.control_key}).json()

    def control(self, fault: str = "none", regression: str = "none") -> None:
        self.http.post(self.proxy_url + "/_control", headers={"Authorization": "Bearer " + self.control_key}, json={"fault_mode": fault, "regression": regression}).raise_for_status()

    def run(self, text: str, key: str | None = None, base: str | None = None) -> dict[str, Any]:
        """POST /run once (awaiting a 202 job if needed); returns status, body, timings and gateway deltas."""
        before, base = self.stats(), base or self.a.target
        payload: dict[str, Any] = {"input": text, **({"idempotency_key": key} if key else {})}
        t0 = time.monotonic()
        try:
            r = self.http.post(base + "/run", json=payload)
            status, body = r.status_code, _json(r)
        except httpx.HTTPError as exc:
            status, body = 0, {"error": {"code": "transport", "message": repr(exc)}}
        elapsed = time.monotonic() - t0
        if status == 202:
            status, body = self.await_job(body, base)
        completed = time.monotonic() - t0
        after = self.stats()
        if before["spend_usd"] is None or after["spend_usd"] is None:
            raise Failure("gateway usage or exact model price is unavailable; spend cannot be verified")
        d = {k: after[k] - before[k] for k in ("requests", "spend_usd", "input_tokens", "output_tokens")}
        return {"status": status, "body": body, "elapsed_s": round(elapsed, 3), "completed_s": round(completed, 3),
                "calls": d["requests"], "spend": d["spend_usd"], "input_tokens": d["input_tokens"],
                "output_tokens": d["output_tokens"]}

    def await_job(self, accepted: dict[str, Any], base: str) -> tuple[int, dict[str, Any]]:
        """Poll GET /jobs/{job_id} until it stops answering 202 or --job-slo-s elapses."""
        job = accepted.get("job_id")
        if not isinstance(job, str) or not job:
            return 202, {"error": {"code": "harness", "message": "202 response without a job_id"}}
        deadline = time.monotonic() + self.a.job_slo_s
        while time.monotonic() < deadline:
            try:
                r = self.http.get(f"{base}/jobs/{job}")
            except httpx.HTTPError as exc:
                return 0, {"error": {"code": "transport", "message": repr(exc)}}
            if r.status_code != 202:
                return r.status_code, _json(r)
            time.sleep(0.5)
        return 202, {"error": {"code": "harness", "message": f"job {job} still pending after {self.a.job_slo_s}s"}}

    def wait_trace(self, trace_id: str) -> dict[str, Any] | None:
        deadline, found = time.monotonic() + self.a.trace_wait, None
        while time.monotonic() < deadline:
            r = self.http.get(f"{self.collector_url}/_traces/{trace_id}")
            if r.status_code == 200:
                found = r.json()
                if found["roots"]:
                    break
            time.sleep(0.25)
        return found

    # --- contract items ---------------------------------------------------------------
    def check_1(self, ev: dict[str, Any]) -> None:
        r = self.run("contract item 1: routing probe")
        ev["run"], ev["unauthorized"] = _brief(r), self.stats()["unauthorized"]
        if r["status"] != 200:
            raise Failure(f"/run returned {r['status']} {_code(r['body'])}")
        if r["calls"] < 1:
            raise Failure("no model call reached the gateway during /run")
        if ev["unauthorized"]:
            raise Failure(f"{ev['unauthorized']} gateway call(s) carried a key other than LLM_API_KEY")

    def check_2(self, ev: dict[str, Any]) -> None:
        t = self.a.target
        h = self.http.get(t + "/healthz")
        hb = _json(h)
        ev["healthz"] = {"status": h.status_code, "body": hb}
        if h.status_code != 200 or hb.get("status") != "ok" or hb.get("version") != self.a.app_version:
            raise Failure(f"/healthz must be 200 with status 'ok' and version {self.a.app_version!r}")
        r = self.http.get(t + "/readyz")
        rb = _json(r)
        ev["readyz"] = {"status": r.status_code, "body": rb}
        if r.status_code != 200 or rb.get("ready") is not True or not rb.get("checks"):
            raise Failure("/readyz must be 200 with ready: true and a non-empty checks map")
        if not self.service:
            ev["invalid_config"] = "skipped (needs --start-cmd)"
            return
        self.service.stop()
        self.service.start(self.env(MAX_SPEND_USD="not-a-number"))
        verdict, deadline = "", time.monotonic() + 15

        def readiness() -> str:
            rz = self.http.get(t + "/readyz", timeout=2)
            ok = rz.status_code == 503 and _json(rz).get("ready") is False
            return "ready=false" if ok else f"readyz returned {rz.status_code} with invalid config"

        while not verdict and time.monotonic() < deadline:
            if (code := self.service.exited()) is not None:
                verdict = "exited non-zero" if code else "exited with code 0 (expected non-zero)"
                continue
            with contextlib.suppress(httpx.HTTPError):
                if self.http.get(t + "/healthz", timeout=2).status_code == 200:
                    verdict = readiness()
            time.sleep(0.25)
        if verdict == "ready=false":  # not merely slow to start: it must stay not-ready
            time.sleep(2)
            with contextlib.suppress(httpx.HTTPError):
                verdict = readiness()
        ev["invalid_config"] = verdict or "no exit and no readiness verdict within 15 s"
        self.restart_service()
        if verdict not in ("ready=false", "exited non-zero"):
            raise Failure(f"invalid MAX_SPEND_USD: {ev['invalid_config']}")

    def check_3(self, ev: dict[str, Any]) -> None:
        r = self.run("contract item 3: trace probe")
        ev["run"] = _brief(r)
        if r["status"] != 200:
            raise Failure(f"/run returned {r['status']} {_code(r['body'])}")
        tid = str(r["body"].get("trace_id", ""))
        if not re.fullmatch(r"[0-9a-f]{32}", tid):
            raise Failure("trace_id must be 32 lower-case hex characters")
        trace = self.wait_trace(tid)
        if trace is None:
            raise Failure(f"trace {tid} not received by the collector within {self.a.trace_wait}s")
        ev["trace"] = {k: trace[k] for k in ("span_count", "roots", "model_calls", "tool_calls", "totals")}
        if len(trace["roots"]) != 1:
            raise Failure(f"expected exactly one root span, found {len(trace['roots'])}")
        ids = {s["span_id"] for s in trace["spans"]}
        orphans = [s["name"] for s in trace["spans"] if s["parent_span_id"] and s["parent_span_id"] not in ids]
        if orphans:
            raise Failure(f"spans whose parent is not in the trace: {orphans}")
        parents = {span["span_id"]: span["parent_span_id"] for span in trace["spans"]}
        for sid in parents:
            seen = set()
            cursor = sid
            while cursor:
                if cursor in seen:
                    raise Failure("trace contains a parent cycle")
                seen.add(cursor)
                cursor = parents.get(cursor, "")
        model = [s for s in trace["spans"] if otel_collector.MODEL_ATTR in s["attributes"]]
        if len(model) != r["calls"]:
            raise Failure(f"{len(model)} model-call span(s) but the gateway saw {r['calls']} call(s)")
        for s in model:
            if missing := [k for k in MODEL_SPAN_ATTRS if s["attributes"].get(k) is None]:
                raise Failure(f"model span {s['name']!r} lacks {missing}")
        tot = trace["totals"]
        if (tot["input_tokens"], tot["output_tokens"]) != (r["input_tokens"], r["output_tokens"]):
            raise Failure(f"trace tokens {tot['input_tokens']}/{tot['output_tokens']} differ from gateway "
                          f"{r['input_tokens']}/{r['output_tokens']}")
        if not _close(tot["cost_usd"], r["spend"]):
            raise Failure(f"trace cost {tot['cost_usd']:.6f} differs from gateway {r['spend']:.6f}")
        cost = r["body"].get("cost_usd")
        if not isinstance(cost, (int, float)) or not _close(float(cost), r["spend"]):
            raise Failure(f"response cost_usd {cost!r} differs from gateway {r['spend']:.6f}")
        bad = [t["name"] for t in trace["tool_calls"] if t["operation"] != "execute_tool"]
        if bad:
            raise Failure(f"tool spans without gen_ai.operation.name = 'execute_tool': {bad}")

    def check_4(self, ev: dict[str, Any]) -> None:
        spend0 = 0.0
        if self.service:
            cap = self.a.cap_usd
            spend0 = self.stats()["spend_usd"]
            self.restart_service(MAX_SPEND_USD=str(cap))
        else:
            cap = self.a.max_spend_usd
        costs: list[float] = []
        hit = None
        for i in range(self.a.cap_max_runs):
            r = self.run(f"contract item 4: spend probe {i}")
            if r["status"] == 200:
                costs.append(r["spend"])
                continue
            if r["status"] == 503 and _code(r["body"]) == "spend_cap_reached":
                hit = r
                break
            raise Failure(f"unexpected {r['status']} {_code(r['body'])} while spending toward the cap")
        spend = self.stats()["spend_usd"] - spend0
        ev.update(cap_usd=cap, runs_before_cap=len(costs), spend_usd=spend, max_request_cost_usd=max(costs, default=0.0))
        if hit is None:
            raise Failure(f"cap {cap} not reached after {len(costs)} runs (spend {spend:.6f}); "
                          "start with a smaller MAX_SPEND_USD or use --start-cmd")
        if spend - cap > max(costs, default=0.0) + 1e-9:
            raise Failure(f"spend {spend:.6f} exceeds cap {cap} by more than one request ({max(costs):.6f})")
        before = self.stats()["requests"]
        again = [self.run(f"contract item 4: post-cap probe {i}") for i in range(2)]
        ev["after_cap"] = [(x["status"], _code(x["body"])) for x in again]
        if any(x["status"] != 503 or _code(x["body"]) != "spend_cap_reached" for x in again):
            raise Failure("service kept taking work after the cap")
        if self.stats()["requests"] != before:
            raise Failure("model calls were made after the cap")
        rz = self.http.get(self.a.target + "/readyz")
        ev["readyz_at_cap"] = rz.status_code
        if rz.status_code != 503 or _json(rz).get("ready") is not False:
            raise Failure("/readyz must be 503 with ready: false at the cap")

    def judge_fault(self, mode: str, r: dict[str, Any]) -> str:
        st, code, calls = r["status"], _code(r["body"]), r["calls"]
        if st == 0:
            return f"transport failure: {r['body']['error']['message']}"
        if st == 202:
            return f"accepted with 202 but no final status within the job SLO: {r['body']['error']['message']}"
        if r["elapsed_s"] > RUN_BUDGET_S:
            return f"took {r['elapsed_s']}s (> {RUN_BUDGET_S:.0f} s)"
        if st == 500:
            return "returned 500"
        accepted = {
            "http500": st == 502 and code == "upstream_error" and calls <= 4,
            "http429": st == 200 and calls >= 3 and r.get("completed_s", r["elapsed_s"]) >= 2.0,
            "slow10x": st == 200 or (st == 504 and code == "upstream_timeout"),
            "tool_timeout": st == 200 or (st == 504 and code == "upstream_timeout"),
            "malformed": (st == 200 or (st == 502 and code == "malformed_model_output")) and calls <= 4 * self.max_single_calls,
            "drop_stream": st == 200 or (st == 502 and code == "upstream_error"),
        }[mode]
        return "" if accepted else f"status {st} code {code!r} after {calls} gateway call(s) is not an accepted outcome"

    def wait_in_flight(self, seconds: float) -> int:
        """Wait up to `seconds` for the gateway's in-flight count to reach zero; returns the final count."""
        deadline = time.monotonic() + seconds
        while (n := self.stats()["in_flight"]) and time.monotonic() < deadline:
            time.sleep(0.2)
        return n

    def check_5(self, ev: dict[str, Any]) -> None:
        for mode in FAULTS:
            for i in range(self.a.fault_repeats):
                self.wait_in_flight(65)  # a previous scenario's zombie calls must not be blamed on this one
                self.control(fault=mode)
                r = self.run(f"contract item 5: {mode} probe {i}")
                reason = self.judge_fault(mode, r)
                if open_calls := self.wait_in_flight(3):
                    reason = reason or f"{open_calls} gateway call(s) still open 3 s after /run returned (zombie work)"
                self.control()
                try:
                    if self.http.get(self.a.target + "/healthz", timeout=5).status_code != 200:
                        reason = reason or "/healthz not 200 after the scenario"
                    elif self.http.get(self.a.target + "/readyz", timeout=5).status_code != 200:
                        reason = reason or "/readyz not 200 after the scenario"
                except httpx.HTTPError:
                    reason = reason or "service unreachable after the scenario"
                self.faults.append({"mode": mode, "repeat": i, "status": "fail" if reason else "pass", "reason": reason,
                                    "http_status": r["status"], "code": _code(r["body"]), "elapsed_s": r["elapsed_s"],
                                    "completed_s": r["completed_s"], "attempts": r["calls"]})
        failed = [f for f in self.faults if f["status"] == "fail"]
        ev.update(runs=len(self.faults), failed=len(failed))
        if failed:
            raise Failure(f"{len(failed)}/{len(self.faults)} scenario runs failed: "
                          + "; ".join(f"{f['mode']}#{f['repeat']}: {f['reason']}" for f in failed[:6]))

    def check_6(self, ev: dict[str, Any]) -> None:
        text, key = "contract item 6: idempotency probe", "k-" + secrets.token_hex(4)
        first, replay = self.run(text, key), self.run(text, key)
        ev["first"], ev["replay"] = _brief(first), _brief(replay)
        if first["status"] != 200 or replay["status"] != 200:
            raise Failure(f"keyed runs returned {first['status']} then {replay['status']}")
        if replay["calls"]:
            raise Failure(f"replay with the same key made {replay['calls']} model call(s)")
        if any(first["body"].get(k) != replay["body"].get(k) for k in ("output", "trace_id")):
            raise Failure("replay returned a different output or trace_id")
        conflict = self.run(text + " (different input)", key)
        ev["conflict"] = (conflict["status"], _code(conflict["body"]))
        if conflict["status"] != 409 or _code(conflict["body"]) != "idempotency_conflict":
            raise Failure(f"same key with a different input returned {ev['conflict']}, expected 409 idempotency_conflict")
        key2, before = "k-" + secrets.token_hex(4), self.stats()["requests"]
        with ThreadPoolExecutor(3) as pool:
            burst = list(pool.map(lambda _: self.run(text, key2), range(3)))
        calls = self.stats()["requests"] - before
        ev["concurrent"] = {"statuses": [b["status"] for b in burst], "calls": calls, "allowed": self.max_single_calls}
        if any(b["status"] != 200 for b in burst) or len({json.dumps(b["body"], sort_keys=True) for b in burst}) != 1:
            raise Failure("concurrent duplicates did not all return 200 with identical bodies")
        if calls > self.max_single_calls:
            raise Failure(f"concurrent duplicates made {calls} model calls; one execution is at most {self.max_single_calls}")

    def check_7(self, ev: dict[str, Any]) -> None:
        repo, findings = Path(self.a.repo), []
        literals = [k for k in (self.gateway_key, self.upstream_key) if k]
        files = tracked_files(repo)
        for f in files:
            rel, name = f.relative_to(repo), f.name
            if name == ".env" or (name.startswith(".env.") and not name.endswith((".example", ".sample", ".template"))):
                findings.append(f"{rel}: environment file committed")
                continue
            try:
                if f.stat().st_size > 1_000_000:
                    continue
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            findings += [f"{rel}: matches {p.pattern}" for p in SECRET_PATTERNS if p.search(text)]
            findings += [f"{rel}: contains a live API key" for lit in literals if lit in text]
            if name.startswith("Dockerfile"):
                findings += [f"{rel}: {line.strip()[:60]}" for line in text.splitlines() if DOCKER_SECRET.match(line)]
        unauthorized = self.stats()["unauthorized"]
        ev.update(scanned_files=len(files), findings=findings[:50], gateway_unauthorized=unauthorized)
        if findings:
            raise Failure(f"{len(findings)} finding(s), first: {findings[0]}")
        if unauthorized:
            raise Failure(f"{unauthorized} gateway call(s) carried a key other than LLM_API_KEY")

    def check_8(self, ev: dict[str, Any]) -> None:
        runbook = Path(self.a.repo) / "RUNBOOK.md"
        ev["rollback_heading"] = bool(runbook.exists() and DOC_RULES["RUNBOOK.md"][0][0].search(runbook.read_text(errors="ignore")))
        svc_b: Service | None = None
        if self.service:
            port_b = free_port()
            target_b = f"http://127.0.0.1:{port_b}"
            svc_b = Service(self.a.start_cmd, self.a.repo, f"service-{port_b}")
            svc_b.start(self.env(PORT=str(port_b), APP_VERSION=self.a.app_version + "-b"))
        elif self.a.target_b:
            target_b = self.a.target_b
        else:
            ev["side_by_side"] = "skipped (needs --start-cmd or --target-b)"
            raise Failure("side-by-side not exercised: pass --start-cmd or --target-b")
        try:
            self.wait_ready(target_b, svc_b)
            versions = {n: _json(self.http.get(t + "/healthz")).get("version") for n, t in (("a", self.a.target), ("b", target_b))}
            ev["versions"] = versions
            if versions["a"] == versions["b"] or not all(versions.values()):
                raise Failure(f"instances must report distinct versions, got {versions}")
            runs = {n: self.run(f"contract item 8: version {n} probe", base=t) for n, t in (("a", self.a.target), ("b", target_b))}
            ev["runs"] = {n: (r["status"], _code(r["body"])) for n, r in runs.items()}
            if any(r["status"] != 200 for r in runs.values()):
                raise Failure(f"both instances must answer /run while running together: {ev['runs']}")
        finally:
            if svc_b:
                svc_b.stop()
        after = self.run("contract item 8: after rollback probe")
        ev["after_rollback"] = (after["status"], _code(after["body"]))
        if after["status"] != 200:
            raise Failure("instance A stopped answering after B was removed")
        if not ev["rollback_heading"]:
            raise Failure("RUNBOOK.md has no heading containing 'rollback'")

    def run_eval(self, regression: str) -> dict[str, Any]:
        report = Path(self.a.repo) / "eval_report.json"
        report.unlink(missing_ok=True)
        self.control(regression=regression)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(["make", "eval"], cwd=self.a.repo, env=self.env(), capture_output=True,
                                  text=True, timeout=self.a.eval_timeout)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {"regression": regression, "error": f"make eval did not complete: {exc!r}"}
        finally:
            self.control()
        out: dict[str, Any] = {"regression": regression, "exit_code": proc.returncode,
                               "elapsed_s": round(time.monotonic() - t0, 1), "stderr_tail": proc.stderr[-800:]}
        if not report.exists():
            return {**out, "error": "eval_report.json was not written at the repository root"}
        try:
            data = json.loads(report.read_text())
        except ValueError:
            return {**out, "error": "eval_report.json is not valid JSON"}
        if errs := validate_eval_report(data):
            return {**out, "error": "; ".join(errs)}
        return {**out, "report": {k: data[k] for k in ("cases", "passed", "threshold", "pass")}}

    def check_9(self, ev: dict[str, Any]) -> None:
        base = self.run_eval("none")
        ev["baseline"] = base
        if base.get("error"):
            raise Failure(f"baseline eval: {base['error']}")
        rep = base["report"]
        self.eval_cases, self.eval_threshold = rep["cases"], rep["threshold"]
        if rep["cases"] < 50:
            raise Failure(f"eval has {rep['cases']} cases; at least 50 required")
        if not rep["pass"] or base["exit_code"] != 0:
            raise Failure(f"baseline eval must pass with exit code 0 (pass={rep['pass']}, exit={base['exit_code']})")
        for reg in REGRESSIONS:
            res = self.run_eval(reg)
            reg_report = res.get("report") or {}
            ok = (not res.get("error") and reg_report.get("pass") is False
                  and res.get("exit_code") != 0
                  and reg_report.get("cases") == rep["cases"]
                  and reg_report.get("threshold") == rep["threshold"])
            self.regressions.append({"name": reg, "status": "pass" if ok else "fail", **res})
            print(f"  regression {reg}: {'detected' if ok else 'NOT detected'}", flush=True)
        ev["regressions"] = {r["name"]: r["status"] for r in self.regressions}
        if bad := [r["name"] for r in self.regressions if r["status"] == "fail"]:
            raise Failure(f"eval still passes (or wrote no valid report) under: {', '.join(bad)}")

    def check_10(self, ev: dict[str, Any]) -> None:
        problems = []
        for name, (patterns, hint) in DOC_RULES.items():
            path = Path(self.a.repo) / name
            if not path.exists():
                problems.append(f"{name} missing")
                continue
            text = path.read_text(errors="ignore")
            lines = sum(1 for line in text.splitlines() if line.strip())
            ok = all(p.search(text) for p in patterns)
            ev[name] = {"non_blank_lines": lines, "heuristic": ok}
            problems += [f"{name}: {lines} non-blank lines (< 20)"] if lines < 20 else []
            problems += [f"{name}: {hint}"] if not ok else []
        if problems:
            raise Failure("; ".join(problems))

    # --- driver -----------------------------------------------------------------------
    def measure_latency(self) -> None:
        if self.a.latency_inputs:
            inputs = [x for x in Path(self.a.latency_inputs).read_text().splitlines() if x.strip()]
        else:
            inputs = [f"latency sample {i}" for i in range(self.a.latency_samples)]
        samples = []
        for text in inputs:
            r = self.run(text)
            if r["status"] == 200:
                samples.append(r["completed_s"] * 1000)
                self.max_single_calls = max(self.max_single_calls, r["calls"])
        value, base = p95(samples), self.a.baseline_p95_ms
        self.latency = {"samples": len(samples), "p95_ms": value, "p50_ms": statistics.median(samples) if samples else None,
                        "baseline_p95_ms": base, "ratio": None, "status": "info"}
        if len(samples) != len(inputs):
            self.latency["status"] = "fail"
            self.latency["reason"] = "not every latency request completed successfully"
        elif value is not None and base:
            self.latency["ratio"] = round(value / base, 3)
            self.latency["status"] = "pass" if value / base <= 1.5 else "fail"
        print(f"latency p95 {value} ms, ratio {self.latency['ratio']} [{self.latency['status']}]", flush=True)

    def item(self, n: int, fn: Callable[[dict[str, Any]], None]) -> None:
        it = self.items[n]
        if not self.selected(str(n)):
            it.reason = "not selected"
            return
        try:
            fn(it.evidence)
            it.status = "pass"
        except Failure as exc:
            it.status, it.reason = "fail", str(exc)
        except Exception as exc:  # a harness/transport error is still a failed check; the cause is recorded
            it.status, it.reason = "fail", f"harness error: {exc!r}"
        print(f"item {n:>2} {it.status:<4} {it.name}" + (f" -- {it.reason}" if it.reason else ""), flush=True)

    def execute(self) -> dict[str, Any]:
        gw = proxy.Gateway(self.a.upstream, self.upstream_key, self.gateway_key, proxy.load_prices(self.a.prices), control_key=self.control_key)
        servers = [ServerThread(proxy.create_app(gw), self.a.proxy_port),
                   ServerThread(otel_collector.create_app(otel_collector.Collector()), self.a.collector_port)]
        checks = {1: self.check_1, 2: self.check_2, 3: self.check_3, 4: self.check_4, 5: self.check_5,
                  6: self.check_6, 7: self.check_7, 8: self.check_8, 9: self.check_9, 10: self.check_10}
        for s in servers:
            s.start()
        try:
            if self.service:
                self.service.start(self.env())
            self.wait_ready(self.a.target, self.service)
            warm = self.run("warmup")
            if warm["status"] == 200:
                self.max_single_calls = max(1, warm["calls"])
            if self.selected("latency"):
                self.measure_latency()
            for n in ORDER:
                self.item(n, checks[n])
        except Failure as exc:
            for it in self.items.values():
                if it.status == "skip" and not it.reason:
                    it.status, it.reason = "fail", f"not run: {exc}"
        finally:
            if self.service:
                self.service.stop()
            for s in servers:
                s.stop()
        return self.report()

    def report(self) -> dict[str, Any]:
        items = [asdict(self.items[i]) for i in sorted(self.items)]
        passed = sum(i["status"] == "pass" for i in items)
        ran = sum(i["status"] != "skip" for i in items)
        fault_ok = sum(f["status"] == "pass" for f in self.faults)
        summary = {"contract_items_passed": passed, "contract_items_run": ran,
                   "fault_scenarios_passed_pct": round(100 * fault_ok / len(self.faults), 1) if self.faults else None,
                   "latency_overhead_ratio": self.latency.get("ratio"), "eval_cases": self.eval_cases,
                   "eval_regression_threshold": self.eval_threshold,
                   "all_run_items_passed": ran > 0 and passed == ran and self.latency.get("status") != "fail"}
        return {"harness_version": "1.0", "target": self.a.target, "upstream": self.a.upstream, "repo": self.a.repo,
                "started_at": self.started_at, "finished_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "service_log": str(self.service.log) if self.service else None, "items": items,
                "fault_scenarios": self.faults, "regressions": [next((r for r in self.regressions if r["name"] == name), {"name": name, "status": "skip", "reason": "regression was not reached; see item 9 or startup failure"}) for name in REGRESSIONS], "latency": self.latency,
                "summary": summary}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m contract_check.check", description="OP-01 Production Contract checker")
    ap.add_argument("--target", required=True, help="base URL of the candidate service, e.g. http://127.0.0.1:8000")
    ap.add_argument("--upstream", default="https://api.openai.com/v1", help="real OpenAI-compatible base URL")
    ap.add_argument("--repo", default=".", help="candidate repository root (make eval, docs, secret scan)")
    ap.add_argument("--report", default="report.json", help="where to write the JSON report")
    ap.add_argument("--start-cmd", help="shell command that starts the service (run in --repo with the contract env)")
    ap.add_argument("--target-b", help="second, already-running instance with a different APP_VERSION (item 8)")
    ap.add_argument("--baseline-p95-ms", type=float, help="unpackaged agent p95 for the overhead ratio")
    ap.add_argument("--proxy-port", type=int, default=8601)
    ap.add_argument("--collector-port", type=int, default=8602)
    ap.add_argument("--prices", default=str(Path(__file__).with_name("prices.yaml")))
    ap.add_argument("--app-version", default="1.0.0", help="APP_VERSION the service was (or will be) started with")
    ap.add_argument("--max-spend-usd", type=float, default=5.0, help="MAX_SPEND_USD for the main run")
    ap.add_argument("--cap-usd", type=float, default=0.002, help="small cap used for item 4 with --start-cmd")
    ap.add_argument("--cap-max-runs", type=int, default=100)
    ap.add_argument("--fault-repeats", type=int, default=2)
    ap.add_argument("--latency-samples", type=int, default=20)
    ap.add_argument("--latency-inputs", help="file with one /run input per line (your 50 eval cases); overrides --latency-samples")
    ap.add_argument("--job-slo-s", type=float, default=120.0, help="seconds a 202-accepted job may take to reach its final status")
    ap.add_argument("--trace-wait", type=float, default=10.0)
    ap.add_argument("--startup-timeout", type=float, default=60.0)
    ap.add_argument("--eval-timeout", type=float, default=1800.0)
    ap.add_argument("--llm-api-key", help="gateway key the pre-started service uses (default: $LLM_API_KEY or random)")
    ap.add_argument("--only", help="comma-separated item ids (1-10, latency) to run")
    ap.add_argument("--skip", help="comma-separated item ids (1-10, latency) to skip")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = Harness(args).execute()
    Path(args.report).write_text(json.dumps(report, indent=2))
    s = report["summary"]
    print(f"{s['contract_items_passed']}/{s['contract_items_run']} items passed, fault scenarios "
          f"{s['fault_scenarios_passed_pct']}%, report: {args.report}")
    return 0 if s["all_run_items_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
