# contract_check — the OP-01 conformance harness

Runs the Production Contract in `../contract.md` against a packaged service. Three parts:

| Module | Role |
|---|---|
| `proxy.py` | OpenAI-compatible gateway placed at `LLM_BASE_URL`. Forwards `/v1/chat/completions` and `/v1/responses` (streaming or not) to the real provider, injects one fault mode and one prompt regression, keeps a token/cost ledger from upstream `usage`. |
| `otel_collector.py` | In-memory OTLP/HTTP receiver (`POST /v1/traces`, protobuf or JSON) with `GET /_traces/{trace_id}`. |
| `check.py` | The runner. Starts both in-process, drives the service through the ten items, six fault scenarios and four regressions, writes `report.json`. |

Requires Python 3.11+. Only `httpx`, `fastapi`, `uvicorn`, `pyyaml` at runtime (`pytest` for the tests).

## Run it against your service

```
cd references/OP-01
python -m venv .venv && . .venv/bin/activate
pip install -r contract_check/requirements.txt
export UPSTREAM_API_KEY=...          # the real provider key; only the gateway ever sees it

python -m contract_check.check \
  --target http://127.0.0.1:8000 \
  --upstream https://api.openai.com/v1 \
  --repo /path/to/your/repo \
  --start-cmd "make run" \
  --baseline-p95-ms 1800 \
  --report report.json
```

With `--start-cmd` the harness owns the process: it runs the command in `--repo` with the
contract environment (`LLM_BASE_URL`, `LLM_API_KEY`, `MAX_SPEND_USD`, `OTEL_EXPORTER_OTLP_ENDPOINT`,
`APP_VERSION`, `PORT`), and restarts it where an item needs different configuration (invalid
config for item 2, a small `MAX_SPEND_USD` for item 4, a second instance on another port
for item 8). Your command must honour `PORT`. Its output goes to `$TMPDIR/op01-service-<port>.log`.

Without `--start-cmd`, start the service yourself first, pointed at the harness ports:

```
LLM_BASE_URL=http://127.0.0.1:8601/v1 LLM_API_KEY=<any token> MAX_SPEND_USD=0.002 \
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:8602 APP_VERSION=1.0.0 PORT=8000 make run
LLM_API_KEY=<same token> python -m contract_check.check --target http://127.0.0.1:8000 \
  --repo . --max-spend-usd 0.002 --target-b http://127.0.0.1:8001
```

In that mode the invalid-configuration sub-check of item 2 is skipped, item 8 needs
`--target-b`, and item 4 needs the cap you started with to be small enough to hit within
`--cap-max-runs` requests. Item 4 also measures spend from the moment the harness started,
so the service must be started fresh just before it, and eval traffic that calls the agent
in-process (not through the service) would inflate the measurement. Use `--only`/`--skip`
(`--only 4`, `--skip 9,latency`) to run a subset, for example the cap check on a separately
started low-cap instance.

`make eval` is invoked in `--repo` with the same environment plus `TARGET_URL`, so the eval
can either call the running service or run the agent in-process through `LLM_BASE_URL`.

### Arguments

| Flag | Default | Meaning |
|---|---|---|
| `--target` | required | Base URL of the service |
| `--upstream` | `https://api.openai.com/v1` | Real provider base URL the gateway forwards to |
| `--repo` | `.` | Repository root: `make eval`, docs, secret scan |
| `--report` | `report.json` | Output path |
| `--start-cmd` | — | Command to start the service (see above) |
| `--target-b` | — | Second pre-started instance for item 8 |
| `--baseline-p95-ms` | — | Unpackaged agent p95; enables the overhead ratio |
| `--proxy-port` / `--collector-port` | 8601 / 8602 | Where the gateway and collector listen |
| `--prices` | `contract_check/prices.yaml` | Price table |
| `--app-version` | `1.0.0` | Expected `/healthz` version |
| `--max-spend-usd` | 5.0 | Cap for the main run (or the cap you started with) |
| `--cap-usd` | 0.002 | Cap used for item 4 when the harness restarts the service |
| `--cap-max-runs` | 100 | Give up on item 4 after this many requests |
| `--fault-repeats` | 2 | Runs per fault scenario |
| `--latency-samples` | 20 | Sequential `/run` calls for the p95 (synthetic inputs) |
| `--latency-inputs` | — | File with one `/run` input per line (your 50 eval cases); overrides `--latency-samples` |
| `--job-slo-s` | 120 | Seconds a `202`-accepted job may take to reach its final status via `GET /jobs/{job_id}` |
| `--trace-wait` | 10 | Seconds to wait for a trace to reach the collector |
| `--startup-timeout` | 60 | Seconds to wait for `/healthz` + `/readyz` |
| `--eval-timeout` | 1800 | Seconds allowed per `make eval` |
| `--llm-api-key` | `$LLM_API_KEY` or random | Gateway key a pre-started service uses |
| `--only` / `--skip` | — | Comma-separated item ids, plus `latency` |

Environment read by the harness: `UPSTREAM_API_KEY` (or `OPENAI_API_KEY`) for the real
provider; `LLM_API_KEY` as the gateway key when the service was started by hand.

### Order of checks

Warm-up and latency samples first (pass-through), then items 1, 2, 3, 6, 5, 9 (with the four
regressions), 7, 8, 10, and item 4 last, because a hard cap leaves the service refusing work.
Exit code 0 means every item that ran passed and the latency ratio (if measured) is ≤ 1.5.

## The report

```json
{
  "items": [{"id": 5, "name": "fault injection", "status": "pass|fail|skip", "reason": "", "evidence": {...}}],
  "fault_scenarios": [{"mode": "http429", "repeat": 0, "status": "pass", "http_status": 200, "code": null,
                       "elapsed_s": 2.3, "attempts": 4, "reason": ""}],
  "regressions": [{"name": "strip_system_prompt", "status": "pass", "exit_code": 2,
                   "report": {"cases": 50, "passed": 3, "threshold": 0.9, "pass": false}}],
  "latency": {"samples": 20, "p95_ms": 1450.2, "p50_ms": 990.1, "baseline_p95_ms": 1300.0, "ratio": 1.116, "status": "pass"},
  "summary": {"contract_items_passed": 10, "contract_items_run": 10, "fault_scenarios_passed_pct": 100.0,
              "latency_overhead_ratio": 1.116, "eval_cases": 50, "eval_regression_threshold": 0.9,
              "all_run_items_passed": true}
}
```

`reason` is the first thing that failed for an item; `evidence` holds what was observed
(status codes, gateway deltas, trace summaries, scan findings). A regression entry's
`status` is `pass` when your eval correctly reported `pass: false` under it. `summary`
carries the `claimed` keys for OP-01 in `SUBMISSION_SCHEMA.md`.

## `eval_report.json`

`make eval` must write this at the repository root and exit non-zero when `pass` is false:

```json
{"cases": 50, "passed": 47, "threshold": 0.9, "pass": true}
```

| Key | Type | Rule |
|---|---|---|
| `cases` | int | ≥ 50 |
| `passed` | int | 0 ≤ passed ≤ cases |
| `threshold` | number | 0 < threshold ≤ 1 |
| `pass` | bool | equals `passed / cases >= threshold` |

Extra keys are ignored.

## Using the gateway and collector on their own

```
UPSTREAM_BASE_URL=https://api.openai.com/v1 UPSTREAM_API_KEY=... GATEWAY_API_KEY=devkey \
FAULT_MODE=none REGRESSION=none python -m contract_check.proxy --port 8601
python -m contract_check.otel_collector --port 8602
```

`GET /_stats` on the gateway returns the ledger (`requests`, `spend_usd`, tokens,
`in_flight`, current modes). `POST /_control {"fault_mode": "...", "regression": "..."}`
switches modes and resets the per-scenario counters (`http429` fails the first two calls
of a scenario; `drop_stream` cuts the first). `GET /_traces/<id>` on the collector returns
the spans with attributes, the model-call and tool-call summaries and the token/cost totals.
Only the two model endpoints are accounted and fault-injected; other `/v1/*` paths are
forwarded untouched.

## Tests

```
python -m pytest references/OP-01/contract_check/tests
```

`tests/example_service.py` is a small contract-compliant service (one tool, one model,
hand-rolled OTLP export) with its own 50-case eval; `tests/test_check.py` runs the whole
harness against it with a stub OpenAI-compatible upstream, so no real API calls are made.

Gateway `/_stats` and `/_control` require the reviewer control token, separate from the candidate model token. The checker creates it automatically. For a separately started gateway, set `GATEWAY_CONTROL_KEY` and send it only to control requests as a bearer token; never give it to the candidate process.

`GET /_ledger` (reviewer bearer token required) exports one JSONL record per authorised model attempt. Set `case_id` and `run_id` through the reviewer-only control API before a case run; these values are captured for each call. Without a case context, records use generated request IDs and are not a case-cost benchmark. Failed calls remain present. Missing provider usage is `null`/`usage_unavailable`, not a fabricated zero cost; any such record blocks a complete cost claim. Export and retain the ledger outside candidate storage before stopping the gateway.

Pricing matches returned model IDs exactly. Unknown model prices or incomplete upstream usage produce a null total spend and a failed accounting check, never an invented default or zero. Use `--prices` to supply verified prices for other budget models; pass the same table to your service where it enforces spend.

For a protected upstream gateway, reviewers may set `UPSTREAM_HEADERS_JSON` to a JSON object of additional access headers (for example a Cloudflare Access header). These headers stay in the proxy, are not passed to the service, and are not recorded in the ledger. Authorization remains the separate upstream API key.
