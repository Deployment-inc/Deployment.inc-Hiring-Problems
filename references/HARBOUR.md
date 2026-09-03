# HARBOUR — the shared environment

A synthetic loan-servicing support agent. Its customers and servicing requests are synthetic. The implementation and case set are authored by Deployment.inc.

## What ships

- `harbour/` — a working Python service. FastAPI-free (stdlib `http.server`) so it starts anywhere.
  - `POST /case` `{case_id, message, customer_id}` → the agent handles a servicing request.
  - Routes every model call through `LLM_BASE_URL` so a gateway can sit in front of it.
- `harbour/backend.py` — SQLite: `customers`, `loans`, `payments`, `disputes`, `documents`, `audit_log`.
  14 tools: `lookup_loan`, `payment_history`, `schedule_payment`, `waive_fee`, `raise_dispute`,
  `close_dispute`, `request_document`, `verify_identity`, `update_contact`, `escalate`,
  `send_statement`, `apply_hardship_plan`, `cancel_autopay`, `commit`.
- `policy.md` — the servicing policy the agent must follow (identity before any money movement,
  fee-waiver caps, hardship eligibility, dispute SLAs, what requires a human).
- `cases/` — 240 authored cases across 12 families, each with a `goal_state` (exact expected
  backend rows after handling) and a difficulty tier. 180 published, 60 held back.
- `eval/` — a starter eval suite of 40 cases with a runner. Deliberately thin: it passes on the
  shipped agent and misses every planted defect.
- `traces/` — written at runtime, not shipped: OpenTelemetry GenAI-convention spans in
  `HARBOUR_TRACE_FILE` (default `traces/otlp.jsonl`). Review instrumentation coverage against the production contract.

## What the evidence can establish

Task success comes from comparing observed backend state with each case's expected rows.
Audit and trace checks establish specific safety and observability properties. Cost comes from
an independently operated gateway. Passing the starter tests is evidence only about those tests.
The shipped implementation intentionally has weaknesses: finding, demonstrating and prioritising
them is candidate work. Private tests check the published policy and contract, with no secret product requirements.

The published source and cases are available to coding agents as well as people. Original authorship
does not make a benchmark immune to training contamination or automated solutions. The decision review
in [JUDGMENT_REVIEW.md](../JUDGMENT_REVIEW.md) tests candidates' understanding of their work.

## Status, 5 September 2026

Built and tested: the backend and its fourteen tools with real policy enforcement, the agent and its
tool-calling loop, the HTTP service, the model boundary with an offline fake mode, trace emission, and
deterministic seed data. The test suite runs offline.

Policy as implemented: fee waivers capped at two per loan per rolling 365 days and ₹2,500 each; hardship
requires six whole months on book and runs one to six months; disputes carry a 30-day SLA and a 120-day
raise window; payments schedule up to 60 days ahead. The clock is frozen at 2026-09-15 so cases are
reproducible.

Private assertions live outside this repository. A public release must also exclude historical solution notes; deleting this page alone does not remove Git history.
