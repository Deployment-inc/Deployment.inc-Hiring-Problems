# references/OP-01 — Ship the Thing You Inherited

**Status: Harbour is here.** The service, its backend, the fourteen tools, the servicing policy and the production contract are published and tested. The case set is published. What stays private is what decides your grade.

| Item | Status |
|---|---|
| `harbour/` — the service, backend, 14 tools, `policy.md`, seed data | **published, offline tests included** |
| `contract.md` and `contract_check/` — the ten machine-checked items, a fault-injecting gateway, an OTLP collector and a conformance runner | **published, tested** |
| `cases/cases.jsonl` — 180 cases with exact expected end states | **published** |
| `eval/` — the starter eval suite you inherit | **published** |
| 60 held-out cases | never published |
| the four deterministic gateway regression modes | published in contract_check |
| our defect detectors | never published |
| the current starter reference measurements | CALIBRATION.md |

## Running it

```bash
cd references/OP-01
python -m harbour.seed_data --out harbour/seed.json      # regenerate seed data (deterministic)
LLM_FAKE=1 python -m harbour.service                     # start on :8080 with no API key
curl -s localhost:8080/healthz
python -m pytest harbour/tests -q                        # offline runtime tests
```

`LLM_FAKE=1` runs the agent against canned deterministic responses, so you can drive a full case with no
model access at all. Point `LLM_BASE_URL` at a real gateway when you want the genuine thing; `llm.py` is
the only outbound path, so whatever sits in front of that URL sees every call.

## What we grade, and what we do not

We read artefacts your run **emits as data**: the append-only `audit_log`, the trace export, the gateway
ledger, and your own eval reports. We never grade a number your process reports about its own
correctness, cost or coverage. That is why the audit log is written by the tool layer rather than by the
agent — the agent cannot tell us what it did, only do it.

## A note on the shipped agent

It works on the happy path. The team that wrote it left. The starter eval suite is green. Read all three
of those facts as evidence rather than reassurance.
