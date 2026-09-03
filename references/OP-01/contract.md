# OP-01 — Production Contract

This is the contract referenced by the OP-01 problem statement in `problems/`.
The harness in `contract_check/` checks it; we run the same harness on your submission.
Everything in this document is normative. Where a check is only partly machine-checkable, the part a
reviewer reads by hand is marked **reviewed**.

## 1. The surface the harness talks to

Keep Harbour’s `POST /case` interface and add the generic `/run` adapter below. For real case evaluation, `input` contains a JSON-encoded `/case` request and `output` contains its JSON-encoded result. The conformance probes also send ordinary text: handle those as synthetic requests against disposable fixtures, without changing customer records. The contract checker uses these routes; case scoring separately uses `/case`.

| Route | Request | Response |
|---|---|---|
| `GET /healthz` | — | `200 {"status": "ok", "version": "<APP_VERSION>"}` while the process is alive. Liveness only: it stays `200` when the service is not ready. |
| `GET /readyz` | — | `200 {"ready": true, "checks": {...}}` when the service will accept work; `503 {"ready": false, "checks": {...}}` otherwise. `checks` is a non-empty map of named booleans (index loaded, config valid, spend cap not reached, …). Status and `ready` must agree. |
| `POST /run` | `{"input": string, "idempotency_key"?: string}` | `200 {"output": string, "trace_id": string, "cost_usd": number}`. `trace_id` is the 32-character lower-case hex W3C trace id of the OpenTelemetry trace for this request. `cost_usd` is the model spend this request incurred, at the prices in `contract_check/prices.yaml`. |
| `POST /run` (asynchronous form) | as above | `202 {"job_id": string, "trace_id": string}` when the work will take longer than 30 s. Optional; a synchronous service never uses it. |
| `GET /jobs/{job_id}` | — | `202` (any body) while the job runs; once finished, exactly the status and body `/run` would have returned synchronously — `200 {output, trace_id, cost_usd}` or an error envelope. |

`POST /run` is the one endpoint with side effects (it spends money and runs tools). Map
your agent's job onto `input` → `output` however you like; the harness treats both as
opaque strings.

### Error envelope

Every non-2xx response from `/run` is JSON:

```json
{"error": {"code": "<code>", "message": "<human text>", "trace_id": "<hex or omitted>"}}
```

| Status | `code` | When |
|---|---|---|
| 400 / 422 | `invalid_request` | Body is not `{"input": string, ...}`. |
| 409 | `idempotency_conflict` | Same `idempotency_key`, different `input`. |
| 502 | `upstream_error` | Model provider returned 5xx (after bounded retries) or dropped the connection. |
| 502 | `malformed_model_output` | Model output could not be parsed/validated after bounded retries. |
| 503 | `upstream_rate_limited` | Provider kept returning 429 after bounded retries. |
| 503 | `spend_cap_reached` | `MAX_SPEND_USD` reached. |
| 503 | `not_ready` | Any other not-ready condition (index loading, invalid config). |
| 504 | `upstream_timeout` | Model call exceeded your per-call timeout (after bounded retries) and no degraded answer was possible. |

A `500` from `/run` is always a failure. A `200` with a degraded-but-useful `output` is
always acceptable where the tables below list it.

### Environment

The service is configured **only** through these variables. It must start with nothing else.

| Variable | Meaning |
|---|---|
| `LLM_BASE_URL` | OpenAI-compatible base URL including the `/v1` segment (e.g. `http://127.0.0.1:8601/v1`). **Every** model call goes to this base. The harness puts a fault-injecting gateway here. |
| `LLM_API_KEY` | Bearer token sent to `LLM_BASE_URL` as `Authorization: Bearer <key>`. The gateway validates it; the real provider key never reaches your service. |
| `MAX_SPEND_USD` | Decimal hard cap on cumulative model spend for the life of the process. An unparseable value is an invalid configuration. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/HTTP base URL; traces are POSTed to `<endpoint>/v1/traces` as protobuf or JSON. |
| `APP_VERSION` | Free-form version string echoed by `/healthz`. The side-by-side check runs two processes that differ only in this and `PORT`. |
| `PORT` | TCP port to listen on (default `8000`). Required when the harness starts your service with `--start-cmd`. |

Your `make eval` receives the same variables plus `TARGET_URL` (the running service),
so an eval suite may either drive the service or call the agent in-process — either way
the model traffic must go through `LLM_BASE_URL`.

### Cost accounting

`contract_check/prices.yaml` lists input/output USD per million tokens keyed by model
name (exact match, then longest prefix, then `default`). It mirrors `MODELS.md` at the
season freeze. The gateway computes spend from the `usage` object of every upstream
response. Your own accounting (the `cost_usd` you return, the cap you enforce, the cost
span attribute) must use the same table; the harness allows 10 % (or $0.00001, whichever
is larger) of disagreement per request.

## 2. The ten contract items

For each item: **what** is required, **how** the harness checks it, and the **pass**
criterion. Item ids match the numbering in the problem statement.

### Item 1 — Route every model call through `LLM_BASE_URL`

**What.** Every request to a model provider (chat completions and responses) is sent to `LLM_BASE_URL` with `Authorization: Bearer $LLM_API_KEY`.

**How.** The harness generates a random `LLM_API_KEY` that only its gateway accepts; the
gateway substitutes the real provider key on the way out. It then calls `POST /run` and
reads the gateway ledger (`GET /_stats`).

**Pass.** `/run` returns `200`; the gateway saw at least one model call during the
request; every call carried the harness-issued key (`unauthorized == 0`). For official runs, network egress is restricted to the gateway. A successful response alone cannot prove that no other provider was used.

### Item 2 — `/healthz` and `/readyz` with honest semantics

**What.** As in the surface table. Ready is `false` while an index loads, while
configuration is invalid, and when the spend cap is hit.

**How.** (a) At steady state: `/healthz` → `200` with `version == APP_VERSION`; `/readyz`
→ `200`, `ready: true`, non-empty `checks`. (b) Invalid configuration: when the harness
owns the process (`--start-cmd`) it restarts the service with `MAX_SPEND_USD=not-a-number`
and expects, within 15 s, either a non-zero exit or `/healthz 200` + `/readyz 503`. Without
`--start-cmd` this sub-check is skipped and marked so. (c) Spend cap: checked in item 4.
(d) Index loading: **reviewed** (show it in `RUNBOOK.md`).

**Pass.** (a) and, when run, (b) hold; status codes and `ready` agree.

### Item 3 — OpenTelemetry traces

**What.** One trace per `/run` request. A span for every model call and every tool call.
Model-call spans carry:

| Attribute | Type | Meaning |
|---|---|---|
| `gen_ai.request.model` | string | Model name requested |
| `gen_ai.response.model` | string | Model snapshot the provider reported (`response.model`) |
| `gen_ai.usage.input_tokens` | int | From upstream `usage` |
| `gen_ai.usage.output_tokens` | int | From upstream `usage` |
| `gen_ai.usage.cost_usd` | double | Cost of this call at `prices.yaml` |

Tool-call spans carry `gen_ai.operation.name = "execute_tool"` and `gen_ai.tool.name`.
Any span with a non-empty parent is a child of the request's root span, directly or
transitively; exactly one span has no parent.

**How.** The harness calls `/run`, then polls its collector for the returned `trace_id`
for up to `--trace-wait` seconds (default 10). It compares the trace against the gateway
ledger for that request, which is exact because the harness sends requests one at a time.

**Pass.** Trace found; exactly one root span; number of model-call spans equals the number
of model calls the gateway saw for that request; summed input and output tokens equal the
gateway's; summed `gen_ai.usage.cost_usd`, the gateway's measured cost and the response's
`cost_usd` agree within tolerance; every tool span present is well-formed (tool spans are
required whenever the agent executed a tool; the harness cannot force a tool call, so their
presence is **reviewed** against your trace samples).

### Item 4 — Hard spend cap from `MAX_SPEND_USD`

**What.** Cumulative spend never exceeds `MAX_SPEND_USD` by more than one request's worth.
Once reached, `/run` returns `503 spend_cap_reached` without making any model call, and
`/readyz` returns `503` with `ready: false`. The cap is for the life of the process; it
does not reset.

**How.** With `--start-cmd` the harness restarts the service with `MAX_SPEND_USD=<--cap-usd>`
(default `0.002`); otherwise it uses the running service and the value you pass as
`--max-spend-usd`. It then sends distinct `/run` requests one at a time, reading gateway
spend before and after each (so it knows each request's cost), until the service refuses.
Without `--start-cmd` the gateway ledger since the harness started stands in for the
service's lifetime spend: start the service fresh immediately before the harness, and run
`--only 4` if your `make eval` calls the agent in-process (that traffic is billed by the
gateway but never passed through the service).

**Pass.** The refusal is `503 spend_cap_reached`; final gateway spend ≤ cap + the largest
single-request cost observed; two further `/run` calls are refused with the same status
and the gateway request count does not change; `/readyz` is `503`. If the cap is not hit
within `--cap-max-runs` requests (default 100) the item fails — use a small cap.

### Item 5 — Behaviour under fault injection

**What.** Defined error statuses, bounded retries (at most 3 retries per model call, with
backoff; honour `Retry-After`), no crash, no zombie work (once the final status has been
returned, no upstream call of that request is still open). Every `/run` answers within 30 s
wall-clock including error paths — with its final status, or with `202` and a job id; an
accepted job reaches its final status within the SLO you publish in `SLO.md`, which the
harness takes as `--job-slo-s` (default 120 s).

**How.** The gateway is switched into each mode below, `/run` is called (`--fault-repeats`
times, default 2), then the gateway is checked for open connections and the service for
liveness and readiness. "Attempts" is the number of gateway requests during the call.

| Mode | Gateway behaviour | Accepted `/run` outcome |
|---|---|---|
| `http500` | Every model call → `500`. | `502 upstream_error`; attempts ≤ 4. |
| `http429` | First two model calls of the scenario → `429` with `Retry-After: 1`; then pass-through. | `200`; attempts ≥ 3; Retry-After timing is checked separately. |
| `slow10x` | Every model call stalls for 10 × the median upstream latency measured so far, and at least 35 s. | `504 upstream_timeout`, or `200` with a degraded answer. |
| `malformed` | Every completion is corrupted: text becomes unterminated JSON, tool-call `arguments` are cut in half; streams are collapsed to a single corrupted chunk. | `502 malformed_model_output`, or `200` after repair/fallback; attempts ≤ 4 × the number of model calls a normal run makes. |
| `tool_timeout` | Every model call stalls 60 s. (The harness cannot reach your tools; a stalled dependency is simulated at the gateway.) | as `slow10x`. |
| `drop_stream` | The first model call of the scenario is cut mid-body (TCP close, no terminator); later calls pass through. | `200` (after retry) or `502 upstream_error`. |

**Pass** (per run, all of): final outcome in the accepted set; first response ≤ 30 s and,
for a `202`, the final status within `--job-slo-s`; never `500`; gateway `in_flight == 0`
within 3 s of the final status; afterwards `/healthz 200` and `/readyz 200`. The qualification bar counts runs: ≥ 95 % of scenario runs must pass, which
with six scenarios means all of them.

### Item 6 — Idempotency key

**What.** `POST /run` accepts `idempotency_key`. Repeating a request with the same key and
the same `input` returns the same `output` and the same `trace_id`, without running the
agent again. Same key with a different `input` → `409 idempotency_conflict`. Concurrent
duplicates execute once.

**How.** (a) Two sequential calls with a fresh key; the gateway request count must not
change on the second. (b) Same key, different input. (c) Three concurrent calls with a
fresh key; gateway requests during the burst ≤ the largest single-run count seen so far.

**Pass.** (a) identical `output` and `trace_id`, zero new gateway requests; (b) `409`;
(c) all three `200`, identical bodies, one execution's worth of gateway requests.

### Item 7 — Secrets only from the environment

**What.** No credential in the repository or the image. The service reads `LLM_API_KEY`
from the environment and sends exactly that.

**How.** (a) Static scan of the tracked files in `--repo` (or all files if not a git
checkout): committed `.env`-style files (`.env`, `.env.*` other than `*.example`,
`*.sample`, `*.template`), key-shaped strings (`sk-…`, `AKIA…`, `ghp_…`, `xox[bp]-…`,
`-----BEGIN … PRIVATE KEY-----`), `ENV`/`ARG` lines in any `Dockerfile*` that assign a
literal to a `*KEY*`, `*SECRET*`, `*TOKEN*` or `*PASSWORD*` name, and the literal value of
the harness's `LLM_API_KEY` and upstream key. (b) Gateway evidence: `unauthorized == 0`
over the whole run. (c) Image layers: **reviewed**.

**Pass.** No findings in (a); (b) holds.

### Item 8 — Two versions side by side, documented rollback

**What.** Two instances with different `APP_VERSION` (and `PORT`) run at the same time from
the same package; switching traffic is configuration, not a rebuild. `RUNBOOK.md` documents
a rollback that takes under five minutes.

**How.** With `--start-cmd`, the harness starts a second instance with
`APP_VERSION=<APP_VERSION>-b` on a free port while the first keeps running; without it, pass
`--target-b` for a second instance you started yourself. It checks both `/healthz` report
their own version, both answer `/run`, then stops B and checks A still answers.
`RUNBOOK.md` must contain a heading with "rollback" in it. The five-minute claim is
**reviewed**.

**Pass.** All of the above; the sub-check is skipped (not failed) only when neither
`--start-cmd` nor `--target-b` is given, and the item then cannot pass.

### Item 9 — `make eval`

**What.** `make eval`, run from the repository root, evaluates your agent on ≥ 50 cases
against a stated regression threshold and writes `eval_report.json` at the repository root:

```json
{"cases": 50, "passed": 47, "threshold": 0.9, "pass": true}
```

`cases` (int ≥ 50), `passed` (int ≤ cases), `threshold` (float in (0, 1]), `pass`
(`passed / cases ≥ threshold`). Extra keys are ignored. `make eval` exits non-zero when
`pass` is false. All model traffic goes through `LLM_BASE_URL`.

**How.** The harness deletes any stale `eval_report.json`, runs `make eval` with the
contract environment, and validates the report. It then applies each prompt regression at
the gateway (section 3) and runs `make eval` again.

**Pass.** Unmodified: schema valid, `cases ≥ 50`, `pass == true`, exit code 0. Under each
of R1, R2, R3 and R4: `pass == false` (the report must still be written; a non-zero exit alone
is not enough). Your suite therefore needs cases whose expected output depends on the
system prompt, cases with expected outputs longer than 40 characters, and cases that
exercise at least one tool call.

### Item 10 — `RUNBOOK.md`, `THREAT_MODEL.md`, SLO document

**What.** At the repository root: `RUNBOOK.md`, `THREAT_MODEL.md` and `SLO.md`.

**How.** Each file exists with ≥ 20 non-blank lines. `RUNBOOK.md` has a heading containing
"rollback". `THREAT_MODEL.md` mentions prompt injection. `SLO.md` states at least one
percentile target (`p95` or `p99`) and at least one percentage. Content quality is
**reviewed**.

**Pass.** All heuristics hold.

### Packaging overhead (qualification bar, not a contract item)

The harness measures the p95 of sequential `/run` calls in pass-through mode — over the
inputs in `--latency-inputs` (one per line; give it your 50 eval cases) or, failing that,
`--latency-samples` synthetic inputs (default 20) — and reports it. The baseline is the same
agent invoked in-process on the same 50 eval cases on the same machine, through the same
gateway; pass its p95 as `--baseline-p95-ms` and the harness reports the ratio and passes
when it is ≤ 1.5. Publish how you measured the baseline in `EXPERIMENT_LOG.md`.

## 3. Prompt regressions

These are applied by the gateway, so they work against any agent, and they simulate the
four representative ways a prompt change silently breaks a deployed agent. Your eval must
fail under each and pass without.

| Id | Gateway mutation | What it simulates |
|---|---|---|
| R1 `strip_system_prompt` | Removes every `system`/`developer` message (chat completions) and `instructions` plus system/developer input items (responses API) before forwarding. | A deploy that lost the system prompt. |
| R2 `truncate_output` | Cuts every completion text to its first 40 characters (`message.content` / `output_text`). | A max-tokens or template change that truncates answers. |
| R3 `scramble_tool_args` | For every tool call in the completion, parses `arguments`; with two or more keys the values are rotated one position (`{a: 1, b: 2, c: 3}` → `{a: 2, b: 3, c: 1}`); with one key the value is replaced by the key's name. Harbour’s JSON `{tool,args}` inside completion text is also mutated. Non-object arguments are left alone. | A schema drift between prompt and tool definitions. |

| R4 `model_identity_drift` | Changes the returned model identity to `<model>-unapproved`, preserving content and usage. | Detects an unapproved provider identity. This is a deterministic identity check, not a claim to reproduce a real model migration; OP-02 tests an actual configuration change. |

The case count and threshold must remain unchanged across all four regression runs, and each must exit nonzero as well as write `pass: false`.

Streams are collapsed to a single chunk while a regression is active.

## 4. Running it

See `contract_check/README.md`. In short: `pip install -r contract_check/requirements.txt`,
export `UPSTREAM_API_KEY`, then

```
python -m contract_check.check --target http://127.0.0.1:8000 \
  --upstream https://api.openai.com/v1 --repo /path/to/your/repo \
  --start-cmd "make run" --report report.json
```

The report's `summary` block carries the `claimed` keys for OP-01 in
`SUBMISSION_SCHEMA.md`.

The local checker is a development tool. Its control endpoints must be inaccessible to candidate code during official reproduction; use separate network/control boundaries. Unknown provider endpoints are rejected so they cannot escape metering. Embeddings/rerankers require a separately metered reviewer gateway before use.
