# references/OP-02 — The Deprecation Notice

**Status: reference attempts measured.** Harbour and the independent current measurements are available. See [CALIBRATION.md](../../CALIBRATION.md) and [MODELS.md](../../MODELS.md).

| Item | Status |
|---|---|
| Harbour: service, backend, 14 tools, `policy.md`, seed data, 180 published cases | **published in `../OP-01/`, offline tests included** |
| the retiring model configuration and the 180 published equivalence cases | in CALIBRATION.md and MODELS.md |
| our measured reference on the retiring configuration: task success, policy violations, cost, p95 | in CALIBRATION.md and MODELS.md |
| 60 held-out cases | never published |
| the deliberately degraded third configuration that tests whether your eval suite discriminates | never published |

Reference-relative bars use the named frozen configuration. Rerun timing comparisons on the same evaluation hardware and load.

See [`../HARBOUR.md`](../HARBOUR.md) for what the environment is and why it is ours rather than a public benchmark.

`retiring-decisions.jsonl` contains the actual fixed decisions for all 180 public cases. Compare its `decision` object to the successor using the complete decision contract in SUBMISSION_SCHEMA.md; formatting differences such as 100 vs 100.0 are equivalent numeric arguments.
