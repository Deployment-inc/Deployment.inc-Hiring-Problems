# References

What Deployment.inc publishes so candidates don't pay for it, and its honest status today.

**[`HARBOUR.md`](HARBOUR.md)** describes the shared environment behind problems 01–04: a synthetic loan-servicing agent, its backend and 14 tools, a servicing policy, 240 authored cases with exact expected end states, a deliberately thin starter eval suite, and a partial trace export. It is built and its tests pass. Its synthetic data is inspectable by every participant and by coding tools; authorship does not establish resistance to automated solutions.

| Folder | Problem | Here now | Still to publish | Never published |
|---|---|---|---|---|
| [`OP-01/`](OP-01/) | Ship the Thing You Inherited | **Harbour itself (offline tests included), 180 cases, the starter eval suite, the production contract and its checker** | the `[CALIBRATE]` thresholds from our own measured run | 60 held-out cases, the gateway regression pack, our defect detectors |
| [`OP-02/`](OP-02/) | The Deprecation Notice | **Harbour, in `../OP-01/harbour/`** | the retiring configuration, 180 published equivalence cases, our measured reference | 60 held-out cases, the deliberately degraded third configuration |
| [`OP-03/`](OP-03/) | Ten Times Cheaper | **Harbour, in `../OP-01/harbour/`** | the shipped agent's measured cost, quality, policy violations and p95 | 60 held-out cases |
| [`OP-04/`](OP-04/) | Judge Without Ground Truth | `trajectory.schema.json`, `score.py` (the exact scorer we run, with tests) | labelled development trajectories, unlabelled held-out trajectories | the hidden set |
| [`OP-05/`](OP-05/) | Ask the Policy Book | `grader.py`, `rubric.md` (judge prompts verbatim), both schemas, the corpus builder, example questions | the IndiaFinBench-derived question sets and the source URL manifest | hidden questions, role probes, the update pack |
| [`OP-06/`](OP-06/) | Triage the Inbox | the response schema, `grader.py`, the published baseline | the ABCD-derived splits and the authored noisy slice | the paraphrased test split and the hostile pack |

Every completed reference run carries a `manifest.json` validating against [`reference.schema.json`](reference.schema.json), next to `raw/` with unmodified harness outputs. You may reuse these instead of re-running them; if you re-run one, include your raw outputs in the private submission.
