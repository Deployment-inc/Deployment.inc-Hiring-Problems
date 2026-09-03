# Open Problem 03 — Ten Times Cheaper

**Category:** Core · **Track:** Cost Engineering · **Reports to:** CFO · **Harness:** Harbour, the gateway ledger, held-out cases, and a Pareto submission schema

> **Available now:** the Harbour service and backend, `policy.md`, 180 published cases, the gateway ledger format and its reader, the deferral classification rules, and the Pareto point schema.
> **Not yet published:** the 60 held-out cases and their per-case raw evidence. The current aggregate starter measurements are in CALIBRATION.md.

> "I'm told this saves us headcount. I can see what it costs to the rupee and I cannot see what it saves. Make the number ten times smaller or make the case for keeping it."

## The Situation

Harbour resolves loan-servicing cases. Its model bill is now a line item the CFO reads out loud in the monthly review, and it grew faster than case volume did, which is the part that bothers her.

Harbour repeats context and retries requests, and its costs vary across case families. Measure which stages actually dominate before choosing an optimisation.

Your mandate is an order of magnitude on cost per *resolved case*. Not per token, not per call — a cheap run that fails and lands on a human costs more than the expensive one it replaced.

The engineering is unglamorous and it is the job: caching what is stable, routing easy cases to small models and hard ones to the model that can actually do them, compacting prompts without amputating the instructions that keep money safe, exiting early, and deciding which cases are not worth spending on at all. That last lever is legitimate and bounded. Deferral only counts as a saving if you own its price.

## Environment

- **Harbour** in `references/OP-01/harbour/`, unmodified — one shared copy, so it cannot drift between the problems that use it. `references/HARBOUR.md` is the tour.
- **180 published cases** with `goal_state` end states across 12 families and three difficulty tiers; 60 held out.
- **The gateway ledger.** Every call through `LLM_BASE_URL` is recorded with model, token counts, list price and wall time. `references/OP-03/ledger_reader.py` is the reader we use. This is the only cost measurement that counts.
- **Deferral classification:** a successful `escalate` audit entry marks a case handed to a person; its reason must be nonempty. Required escalations come from the trusted case goal; other handoffs are elective deferrals. A resolved case must match its goal and not be deferred. Every other case is failed. The ledger reader applies this denominator to independently observed run records.
- **The Pareto point schema** in `references/OP-03/pareto_schema.json`. Every point you measured goes into `results/pareto.jsonl`, including the rejected ones.
- Budget-class models only for every role: generator, router, verifier, summariser, fallback. Embeddings and rerankers are allowed and their cost still counts. Caches you host yourself are free, and must be described.

## Deliverable

A modified Harbour that resolves cases at an order of magnitude lower cost, the measurement that proves it from the ledger, and the Pareto curve behind the point you chose — with the points you rejected and why.

> **Season 1 evaluation targets:** The bars below apply to this season. [CALIBRATION.md](../CALIBRATION.md) records current reference attempts and their limits; [RELEASE_MANIFEST.json](../RELEASE_MANIFEST.json) pins the released files. Failed reference attempts do not lower the qualification targets.

## Qualification Bar

1. **Cost per resolved case ≤ 0.1× the shipped agent's** on the 60 held-out cases, from the ledger at pinned list prices. Deferred and failed cases count as unresolved in the denominator; their spend still counts in the numerator.
2. **Quality:** exact `goal_state` success on the 60 held-out cases is **at least 85.3%**, and no more than three percentage points below the frozen starter reference, whichever requirement is higher. With the current 37/60 reference the 85.3% floor governs (at least 52/60 successes). This preserves the original quality target even though the freshly measured starter is weaker than the old historical report. A correct policy-required escalation counts toward quality; all handoffs remain excluded from cost resolution.
3. **Policy violations do not increase** over the shipped agent, on the same scorer. Savings bought by skipping identity verification fail this bar and end the review.
4. **p95 end-to-end latency is not worse** than the shipped agent's on the same hardware and cases.
5. **Elective deferral rate ≤ 10% of automatable cases**, with a machine-readable reason on every handoff. A policy-required escalation is determined by the trusted case goal (`audit_must_include` contains `escalate`) and is reported separately; it is not an elective abandonment of automation. The published cases require escalation in 74/180 cases, so an overall 10% handoff limit would contradict the task. All handoff spend stays in the cost numerator, and neither kind of handoff counts as a resolved case in the cost denominator.
6. **`results/pareto.jsonl` holds ≥ 8 distinct operating points**, each with ledger-derived cost, measured quality, measured p95 latency, overall handoff rate and elective deferral rate, and one line on what it changes. Measured, not projected.

## How this is assessed

| What we run | On what | Produces |
|---|---|---|
| the 60 held-out cases, then a backend diff | a fresh database per case | `results/held_out_runs.jsonl` and the resolution rate |
| the gateway ledger reader | every model call across all runs | `results/ledger.jsonl` — cost per case, per model, per stage |
| `python references/OP-02/policy_scorer.py --db results/audit_log.sqlite` | `results/audit_log.sqlite` | `results/policy_report.json` |
| the deferral scorer | `results/audit_log.sqlite` | `results/deferrals.json` — rate and reason codes |
| a consistency check on your curve | `results/pareto.jsonl` against `results/ledger.jsonl` | whether each claimed point is backed by a real run |

Cost is read from the ledger. A figure your service computes about itself is not evidence and is not graded; where the curve disagrees with the ledger, the ledger wins and the discrepancy is a reporting failure.

## You Decide

Where the money goes before you touch anything, and whether your first week is measurement or optimisation. What a cache key is when the input is a customer message and backend state moves underneath it, and how a stale hit is stopped from moving money. How a router judges difficulty without spending as much deciding as it saves. What you compact out of the prompt, and how you prove you did not compact out a guardrail. Which cases are genuinely not worth automating.

## Required Analysis

A cost decomposition before and after, by stage and by case family, from the ledger. Each lever measured independently — an ablation per lever, not one before/after — because a stack of changes that together hit 10× says nothing about which to keep. The Pareto curve with the rejected points and the reason for each. And the quality you did lose, named by case family, with your argument for why it is acceptable.

## MEMO.md

One page to the CFO. What a resolved case costs now against what it cost before, in currency rather than multiples; what quality was traded for it and where that shows up in customer experience; what happens to the number when volume doubles or the case mix shifts; and the one decision you need from her, stated as a decision and not a briefing.

## Decision review

Follow [JUDGMENT_REVIEW.md](../JUDGMENT_REVIEW.md). We use your evidence and one new constraint in the existing technical conversation. No additional take-home round is required. Coding-agent use is allowed and disclosed; you own the decisions and their explanation.
