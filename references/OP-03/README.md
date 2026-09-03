# references/OP-03 — Ten Times Cheaper

**Status: reference attempts measured.** Harbour and the independent current measurements are available. See [CALIBRATION.md](../../CALIBRATION.md) and [MODELS.md](../../MODELS.md).

| Item | Status |
|---|---|
| Harbour: service, backend, 14 tools, `policy.md`, seed data, 180 published cases | **published in `../OP-01/`, offline tests included** |
| the shipped agent's measured cost per resolved case, quality, policy violations and p95 | in CALIBRATION.md and MODELS.md |
| the gateway ledger your cost is read from | in CALIBRATION.md and MODELS.md |
| 60 held-out cases | never published |

Reference-relative bars use the named frozen configuration. Rerun timing comparisons on the same evaluation hardware and load.

See [`../HARBOUR.md`](../HARBOUR.md) for what the environment is and why it is ours rather than a public benchmark.

The 10% bar applies to **elective** deferrals among automatable cases. Required policy escalations are determined from the trusted case goals and reported separately. Use `ledger_reader.py --cases ../OP-01/cases/cases.jsonl ...` to compute this rate on public cases. Overall handoff rate remains descriptive; it cannot have a 10% ceiling when the dataset itself requires more handoffs.

`success_rate` is exact goal success, including a correct required escalation. `resolved_rate` excludes all handoffs and is the cost denominator divided by all cases. These are different quantities.
