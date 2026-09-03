# Open Problem 02 — The Deprecation Notice

**Category:** Core · **Track:** Applied AI · **Reports to:** VP of engineering · **Harness:** Harbour, a published equivalence set, held-out cases, and your own eval suite run by us on both configurations

> **Available now:** the Harbour service and backend, `policy.md`, 180 published cases, the 180-case behavioural equivalence set, the policy-violation scorer, and the current pinned snapshot.
> **Not yet published:** the 60 held-out cases and private per-case traces. The retiring decisions for all 180 public cases are in `references/OP-02/retiring-decisions.jsonl`; current aggregate measurements are in CALIBRATION.md.

> "I have thirty days, a model that is going away, and no way to tell the risk committee the new one behaves the same. Convince me, don't reassure me."

## The Situation

Harbour runs on a hosted model snapshot the provider is retiring in 30 days. The migration itself is a configuration line. The problem is everything that line does not tell you.

Your VP has watched a team migrate a prompt in an afternoon, declare success on a few examples, and spend the next quarter finding the customer segments where behaviour changed. She needs a comparison that makes those changes visible before rollout.

Harbour's prompt was tuned against the retiring snapshot, and there is reason to think parts of it lean on that snapshot's habits rather than on anything robust. You find out how much when you move.

This is a sequencing test as much as an engineering one. A competent engineer builds the measurement before touching the thing being measured, and your commit history and experiment log will show which order you worked in.

## Environment

- **Harbour** in `references/OP-01/harbour/` — one copy shared by every problem that runs on it, so it cannot drift between them. `references/HARBOUR.md` is the tour.
- **180 published cases** with `goal_state` end states; 60 held out for grading.
- **The behavioural equivalence set**: 180 published cases across the 12 case families, including the awkward ones — refusals, hardship requests, ambiguous identity, third-party text arriving in tool output. Published together with the retiring snapshot's outputs, so you can diff against a fixed reference.
- **The policy-violation scorer** in `references/OP-02/policy_scorer.py`, deterministic, over the `audit_log` and the transcript. The same scorer we run.
- Budget-class models only for every role you control: generator, planner, critic, verifier, router, fallback. The retiring snapshot is itself budget class, so this is a lateral move, not a downgrade you can blame.

## Deliverable

A migrated Harbour on a budget-class successor, and the evidence that it behaves the same. The evidence is the deliverable; the migration is the easy half. You submit your eval suite and we run it, unchanged, against both configurations. A suite that passes everything on both is not evidence of equivalence, it is evidence of a bad suite.

> **Season 1 evaluation targets:** The bars below apply to this season. [CALIBRATION.md](../CALIBRATION.md) records current reference attempts and their limits; [RELEASE_MANIFEST.json](../RELEASE_MANIFEST.json) pins the released files. Failed reference attempts do not lower the qualification targets.

## Qualification Bar

1. **Task success on the 60 held-out cases is no worse than the retiring configuration's**, as exact end-state match against `goal_state`, within one standard error of our published reference.
2. **Behavioural equivalence on the 180 published cases** — agreement on decisions taken (which state-changing tools were called, whether it escalated, whether it committed) at **≥ 0.55**. Wording is not graded; decisions are.

   Read the reference numbers before you plan against this bar, because they are not what most people expect. An earlier historical control migration got **0.5722** — swapping the model changes the decision on more than four cases in ten. Worse, neither configuration is deterministic: the retiring one agrees with **itself** across repeats only **91.1%** of the time, and the successor **88.9%**. These repeat measurements describe variability in those runs; they are not a mathematical ceiling on what a different system can achieve.

   The bar is set just below our own control migration on purpose: matching a naive model swap is the floor, and the interesting work is beating it. The worst family in our control was `injected_instruction` at **0.20** agreement — the two models respond to text injected into tool output almost completely differently. If your migration report does not mention that, you have not looked.
3. **Policy violations do not increase.** The published scorer's count on the held-out cases is ≤ the retiring configuration's. One new identity-check violation fails this bar outright.
4. **Your eval suite discriminates.** Run by us on the retiring configuration, on yours, and on a third we degrade deliberately, it must pass the first, agree with your claim on the second, and fail the third.
5. **Cost per resolved case ≤ 1.0× the retiring configuration's**, from the gateway ledger. The earlier control migration measured **0.709×** (15,954 → 11,309 tokens per resolved case), so this is comfortable if you do not spend the saving on retries.
6. **p95 latency ≤ 2.2× the retiring configuration's** on the same hardware and cases. This bar is loose because the earlier control migration measured **2.02×** (p95 7.8s → 15.7s): the successor is genuinely slower per call, and we are not going to demand you beat a number we did not beat ourselves. Choosing a faster successor, or cutting a round trip, is one of the few ways to clear this comfortably.

## How this is assessed

| What we run | On what | Produces |
|---|---|---|
| the 60 held-out cases against both configurations | a fresh database per case | `results/held_out_runs.jsonl` and both end-state match rates |
| the 180-case equivalence set | both configurations | `results/equivalence_runs.jsonl` and a per-decision agreement matrix |
| `python policy_scorer.py` | `results/audit_log.sqlite` | `results/policy_report.json` — violations by rule |
| `make eval` from your repository | the retiring configuration, yours, and our degraded one | `results/eval_report_{old,new,degraded}.json` |
| the gateway ledger | every model call in every run above | `results/ledger.jsonl` — tokens, cost and wall time per case |

We recompute every headline number from these files. Nothing your migration reports about its own equivalence is graded.

## You Decide

What "the same behaviour" means when the wording changes but the decision does not, and where you encode that line in a scorer rather than in prose. Which parts of the prompt were load-bearing and which were superstition inherited from the old snapshot. Whether to port the prompt or rewrite it against the new model's real failure modes, and how you defend the larger change. What you do if the new model is simply worse on one case family: hold a fallback, restructure the task, or tell the VP. And how you run this migration again in six months without redoing the work.

## Required Analysis

The disagreement inventory: every equivalence prompt where the two configurations decided differently, grouped by cause, with your judgement on which decision was correct. The prompt changes you made and the behavioural difference each addresses. An ablation showing which changes mattered. And the honest section: what your suite still cannot detect, and what you would need to detect it.

## MEMO.md

One page to the VP of engineering. Whether the migration is safe to ship and on what evidence; the specific ways behaviour did change and who is affected; what it now costs and how long a case takes; and what you want her to fund before the next deprecation notice arrives, because one will.

## Decision review

Follow [JUDGMENT_REVIEW.md](../JUDGMENT_REVIEW.md). We use your evidence and one new constraint in the existing technical conversation. No additional take-home round is required. Coding-agent use is allowed and disclosed; you own the decisions and their explanation.
