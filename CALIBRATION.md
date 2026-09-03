# Measured attempts — 6 September 2026

These are independently rerun attempts against the revised scorers, not six qualifying solutions.
The thresholds remain demanding when an attempt fails. A failed coding-agent attempt is evidence
about that attempt; it is not proof that another Codex or Claude setup cannot solve the challenge.

[Machine-readable measurements and evidence hashes](references/calibration-2026-09-06.json) bind
this summary to private raw traces, audits and the separately retained token ledger. No previous
private evaluator was invoked or imported. Per-case held-out answers and labels stay private.

## Method

Harbour uses the shipped agent/backend with a fresh seeded SQLite database per case. A reviewer
adapter replaces only the provider boundary with Responses API calls to the exact snapshots below,
retaining the starter's 800 output-token limit. Goal truth comes from the new canonical database
and successful-audit scorer. Spend is computed independently from observed upstream input/output
tokens at the verified uncached list prices. No failed attempt was dropped.

OP-04 is a fresh single-prompt judge with the public policy and full trajectory, using GPT-5 mini
and at most 1,800 output tokens. It does not replay the backend or receive gold. OP-05 is freshly
implemented TF-IDF top-six retrieval with role filtering, using GPT-5 mini and the same output cap;
GPT-4.1 mini applies the published semantic rubrics. OP-06 is the shipped lexical baseline.

The API runs used concurrency eight on a macOS reviewer host. Timing below describes this setup;
qualification latency comparisons rerun the reference and candidate at the same load on the same
Linux evaluation machine. The offline Linux container rehearsals test runtime/scorer plumbing.
Do not mistake a macOS API timing for a universal Linux performance guarantee.

## Observed results

| Attempt | Scope | Result |
|---|---|---|
| Harbour, `gpt-4.1-mini-2025-04-14` | 180 public + 60 private | Goal success 117/180 and 37/60; one private policy finding; no unhandled agent exceptions |
| Harbour, `gpt-5-mini-2025-08-07` | 180 public + 60 private | Goal success 116/180 and 38/60; one private policy finding; no unhandled agent exceptions |
| OP-01 starter contract | Actual starter HTTP service | Fails readiness; 0/10 items passed, four regressions explicitly unreached. This is a starter deficiency, not a passing production package. |
| OP-02 unchanged model swap | 180 paired public cases | Decision agreement 0.5611; private cost ratio about 0.815 and latency ratio about 1.425. A degraded-configuration eval and a defensible migration report are still required. |
| OP-03 model swap | 60 private cases | Cost per resolved case falls from $0.012540 to $0.010223, about 1.23× cheaper. It does not achieve 10× or supply eight operating points. |
| OP-04 fresh judge | Dev 480 / held-out 240 / private 360 | Balanced accuracy 0.7728 / 0.7658 / 0.7865; confidence AUROC 0.6004 / 0.5565 / 0.5725. Does not clear the bars. |
| OP-05 fresh retrieval | Dev 146 / held-out 272 | Answer accuracy 0.8067 / 0.7619; citation support 0.5837 / 0.6963; out-of-corpus refusal 0 in both. Does not clear the bars. |
| OP-06 lexical baseline | Dev 2,000 + noisy 300 + hostile 9 | Intent 0.3748, action 0.3913, macro-F1 0.4508. Does not clear the accuracy/calibration bars. |

OP-04 MCC is 0.6022 / 0.5885 / 0.6469; ECE is 0.0621 / 0.0810 / 0.0424. One development
prediction was invalid and counted wrong. OP-05 contradiction accuracy is 0.8750 / 0.8667 and
temporal accuracy 0.7895 / 0.7111. Role-refusal rates are 0.9048 / 0.9808; a zero detected citation/
text-overlap violation count does not establish full semantic role isolation. Its semantic review
remains incomplete. Missing or invalid responses remain visible rather than disappearing.

Total API accounting for generation and semantic grading is **$4.647676 across 3,794 calls**, with
no missing-usage calls, under an $8 run cap. This is list-price accounting, not a reconciled provider
invoice. Small availability probes are separately recorded; they cost less than $0.001. Indexing
and local compute use no model API calls and are reported separately.

## Required escalation and quality

The trusted goals require escalation in 74/180 public cases and 26/60 private cases. An overall
handoff ceiling of 10% would contradict successful handling of those cases. OP-03 therefore limits
**elective handoffs among automatable cases** to 10%. Required escalations still contribute spend;
all handoffs are excluded from the resolved-case cost denominator. Correct required escalation
counts toward goal success. `success_rate` and `resolved_rate` are separate metrics.

The frozen starter reference for OP-01–03 is GPT-4.1 mini: 37/60 private goal successes, one private
policy finding, cost $0.012540 per resolved case and 11.889 s private p95 in this run. OP-03 retains
its demanding 85.3% quality floor as well as the three-percentage-point non-regression condition;
the floor is not lowered to accommodate this starter result. Timing must be paired on evaluator
hardware. The exact model roles and price treatment are in [MODELS.md](MODELS.md).

## Reproduction evidence and limits

All six submission formats were exercised with explicit synthetic/oracle fixtures, including
inflated claims and unsafe artifacts. All six baseline runtime rehearsals also ran in non-root,
network-disabled Linux containers. Oracle files are plumbing tests, not performance evidence.

A private six-question OP-05 synthetic version pack was tested through the CORPUS_DIR restart
interface: six correct before and after refresh; a stale index fails the three changed rules.
This proves the interface and negative check, not that the live TF-IDF attempt handles every update.
The private OP-06 run includes 2,000 clean, 300 independently generated noisy and nine hostile inputs.
Candidate code must receive only the allowlisted fields in EVALUATION_PROTOCOL.md.

Passing these infrastructure checks is not a promise that no defect remains. Submissions are open
through the [private form](https://deployment.inc/hiring-challenges/#submit). RELEASE_MANIFEST.json
pins the Season 1 files. Failed attempts alone are not a reason to weaken a qualification target.
