# Open Problem 04 — Judge Without Ground Truth

**Category:** Core · **Track:** Evaluation & Observability · **Reports to:** Product owner · **Harness:** Harbour trajectories + the published scorer

> **Available now:** the labelled development set (480 trajectories), the unlabelled held-out set (240), `trajectory.schema.json`, and `score.py` — the exact scorer we run. Qualification targets and historical reference scores are shown below; the current attempt is recorded in CALIBRATION.md.
> **Not yet published:** a separate private set of Harbour trajectories on hidden cases; it uses the same tools and model families. We run your judge on it ourselves.

> "I have ten thousand transcripts and a board meeting on Thursday. Is the thing working or not?"

## The Situation

A lender has a loan-servicing agent in production, handling fee disputes, hardship requests, payment reschedules and document chases. There are logs. There are no labels, no simulator, no gold final state, and no appetite for paying a frontier model to reread every transcript nightly.

The product owner wants a daily quality number she can defend, and a breakdown of *why* things fail that somebody can be staffed against. Every deployment reaches this in month two, and most teams answer it with a dashboard of token counts and a vibe.

## Environment

Trajectories come from **Harbour**, our synthetic loan-servicing environment: an agent service over a SQLite backend of customers, loans, payments, disputes and documents, fourteen tools, a written servicing policy, and 240 authored cases across twelve families. Harbour is ours end to end — no public benchmark, no scraped data — so nothing here sits in anybody's training set.

What matters is how it grades. Every case carries a `goal_state`: the exact backend rows that must exist once the request is handled properly. Success is a **database diff**, not an opinion. So every trajectory carries a deterministic pass/fail label that no model produced and no annotator argued about. That is the point. You are measured against a fact your judge never sees.

- **Development set:** 480 trajectories from two budget-class agent models (`gpt-4.1-mini` and `gpt-5-mini`, 240 each) over 120 published cases, **with** labels. Train or tune on it freely. Pass rate 0.679.
- **Held-out set:** 240 trajectories over a further 60 published cases, disjoint from the development split, same two models, **labels withheld**. Measured pass rate 0.633 — 4.6 points from the development set's, so the distribution holds.

  The cases here are published; only the labels are withheld. That is the right thing to hold back: your judge is handed the trajectory either way, and the only thing it must not see is whether the run succeeded.
- **Hidden set:** Harbour runs on hidden cases, using the same tools and model families. Any additional transfer-test scope must be published before submissions open. We run your judge on it ourselves.

Each trajectory ships with the case text the agent saw and the full transcript — every tool call **and what each tool returned**, refusals included. That last part matters more than it sounds: our first reference judge saw only the calls, concluded from an unbroken run of them that everything had worked, and scored 0.54 balanced accuracy with an AUROC below chance. The tool results are where the failures actually are.

## Deliverable

A judge that takes a **trajectory only** — messages and tool calls, plus tool schemas and case text — and returns a verdict, a confidence, and an operational failure category from a taxonomy you define and publish. No backend state, no gold actions, no `goal_state`. Expose it as `judge(trajectory, tool_schemas, case) -> {verdict, confidence, category}` with a CLI wrapper we can run unattended. Tool schemas are supplied as [JSON data](../references/OP-04/tool_schemas.json); input projection follows [EVALUATION_PROTOCOL.md](../EVALUATION_PROTOCOL.md). Run it, on budget-class models only.

**Your judge may not import, vendor or execute Harbour**, and may not reconstruct backend state by replaying tool calls against a simulator or an inferred schema. Replaying the environment is not judging: the difficulty of the real job is that production has no environment to replay. Our checks fail submissions whose judge references the harness.

> **Season 1 evaluation targets:** The bars below apply to this season. [CALIBRATION.md](../CALIBRATION.md) records current reference attempts and their limits; [RELEASE_MANIFEST.json](../RELEASE_MANIFEST.json) pins the released files. Failed reference attempts do not lower the qualification targets.

## Qualification Bar

On the held-out set **and** our hidden set, as computed by the published `score.py`:

1. **Balanced accuracy ≥ 0.79.** This is a qualification target informed by the earlier reference run, not a claim that the current reference clears it.
2. **Matthews correlation ≥ 0.65** (reference: 0.6487). MCC rather than Cohen's κ, because κ punishes the imbalanced pass rates real deployments have and rewards a judge that has learned the base rate instead of the task.
3. **Calibration:** expected calibration error **≤ 0.10** *and* AUROC of confidence against correctness **≥ 0.65**. Both together — a constant confidence can pass the first and fails the second when the set contains both correct and incorrect predictions. If every prediction is correct, AUROC is undefined and is not a failing bar; accuracy and ECE still apply.

   **Be warned: our reference judge does not clear this bar.** It gets ECE 0.0213, comfortably inside, and AUROC **0.5563**, which is barely better than ordering the trajectories at random. It knows *whether* it is right far better than it knows *when* it is right. We are publishing that rather than quietly lowering the bar to what we happened to score, because a verdict a compliance team cannot triage by confidence is a verdict they have to read in full — which is the thing they hired the judge to avoid. This is the part of the problem we consider unsolved, and the part most worth your time.
4. **Cost per trajectory** at or below the reference, measured from the gateway ledger. Ours averages **774 input and 500 output tokens** per trajectory. Stated in tokens rather than dollars so the bar does not move when a price list does; we convert at the pinned list price on the day we score.
5. **A human audit of 50 of your judge's own decisions** on the held-out set: read those trajectories, record your verdict, say where you disagree with your judge and why. We compare all three — you, your judge, the database.

## How this is assessed

| What we run | On what | Produces |
|---|---|---|
| the published `score.py` | `results/heldout_predictions.jsonl` — one line per trajectory, `{id, verdict, confidence, category}` | balanced accuracy, MCC, confidence AUROC, ECE |
| your judge's CLI, on our machines | our hidden set | the same four numbers on data you have never seen |
| our gateway ledger reader | `results/manifest.json` | measured cost per trajectory |
| a reviewer, alongside the database labels | `results/audit_50.md` | whether your disagreements with your judge are the interesting ones |

Nothing is graded from a number your process reported about itself. Your judge must run as a CLI on a plain Linux box with no GPU and no service to stand up; otherwise we cannot score the hidden set and the submission cannot qualify.

## You Decide

- Whether the judge is a small model, a fine-tuned classifier, a rubric-driven call, deterministic checks over tool-call sequences, or a stack with an escalation path.
- What the taxonomy is, and how you make it *operational*. "Reasoning error" is decoration; "moved money before verifying identity" is a ticket.
- What you do about trajectories the database marks failed that a servicing manager would accept — and the ones that pass the diff by luck. There are more of both than you expect, and that is most of the signal.

## Required Analysis

Where the judge fails and why. The false positives that would have hidden a real production problem for a week. Which categories transfer to unseen cases and which quietly do not. What you would change if the client's agent worked in a domain you had never seen.

## MEMO.md

To the product owner. The daily number, how far to trust it, what it costs, when to ignore it, and the three failure categories to staff a person against first.

## Decision review

Follow [JUDGMENT_REVIEW.md](../JUDGMENT_REVIEW.md). We use your evidence and one new constraint in the existing technical conversation. No additional take-home round is required. Coding-agent use is allowed and disclosed; you own the decisions and their explanation.
