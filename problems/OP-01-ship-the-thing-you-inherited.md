# Open Problem 01 — Ship the Thing You Inherited

**Category:** Core · **Track:** Production Engineering · **Reports to:** Head of platform engineering · **Harness:** Harbour service, published case set, and defect detectors we hold privately

> **Available now:** Harbour itself — the service, backend, 14 tools, `policy.md` and seed data, with an offline test suite — plus the 180 published cases, the starter eval suite you inherit, and the production contract with its checker.
> **Not yet published:** the 60 held-out cases and private policy/trace assertions. All four gateway regression mechanisms are published; current reference measurements are in CALIBRATION.md.

> "It demos beautifully. My team won't put it behind our load balancer and they won't tell me why in one sentence."

## The Situation

Harbour is a loan-servicing support agent. It reads a customer message, looks up the loan, checks policy, calls tools, and moves money or raises a dispute. It works. On the published cases it usually lands on the expected backend end state, and the team that built it has left.

The platform team spent three weeks with it and produced complaints rather than bugs. The eval suite is green and they don't trust it; it stayed green through an incident that took two days to unwind by hand. Answers changed on a Tuesday when the provider rolled a snapshot, and nothing in the repository had changed. The bill spikes without traffic spiking, and nobody can say which cases cause it. Asked what one case costs to resolve, the team spent a day grepping logs and still guessed. Someone in risk found an audit entry where money moved and could not find the step that established who the customer was. And in one case the agent did something nobody had asked for, shortly after reading a free-text field that came from outside the company.

Six symptoms, no diagnoses. Finding the causes is the work. We will not say how many distinct root causes there are, and some complaints may share one.

## Environment

- **Harbour** in `references/OP-01/harbour/`, with the backend, the tool layer, `policy.md`, and a `scripts/reproduce.sh` that runs on a plain Linux box with no GPU.
- **180 published cases**, each with a `goal_state`: the exact backend rows expected after correct handling. 60 more are held back.
- **The starter eval suite** in `eval/` — 40 cases and a runner, thin on purpose. Read it as evidence about the team that wrote it.
- **The production contract** and its checker in `references/OP-01/`. Run it yourself; we run the same binary.
- Budget-class models only. Every model call keeps routing through `LLM_BASE_URL`.

## Deliverable

A hardened Harbour the platform team would accept, plus the four things they asked for and never got: an eval suite that fails when behaviour regresses, tracing that attributes token cost to a case and a tool call, a runbook for the failure modes you actually found, and an account of what was wrong. `POST /case` keeps its contract. Everything behind it is yours.

> **Season 1 evaluation targets:** The bars below apply to this season. [CALIBRATION.md](../CALIBRATION.md) records current reference attempts and their limits; [RELEASE_MANIFEST.json](../RELEASE_MANIFEST.json) pins the released files. Failed reference attempts do not lower the qualification targets.

## Qualification Bar

1. **Every item in the published production contract passes** in our checker, from your `scripts/reproduce.sh`.
2. **Your eval suite fails on each regression in our gateway regression pack and passes on clean code.** The pack is applied at the proxy: stripped system prompt, truncated completions, scrambled tool arguments, unapproved returned model identity. All four must be caught.
3. **Our defect detectors report zero findings** against your service over the published cases. They are deterministic assertions over `audit_log` rows and the trace export. We do not publish their count.
4. **Task success on the 60 held-out cases is ≥ the shipped agent's**, as exact end-state match against `goal_state`.
5. **No held-out case exceeds 3× the median case's token spend**, from the gateway ledger. The current starter's worst private case is about 2.07× its median, so 3× is slack, not a squeeze — the bar exists to catch a retry loop that fans out on the cases it cannot do.
6. **Packaging overhead:** p95 latency ≤ 1.5× the shipped agent's on the same hardware and cases. The current 60-case private reference is p95 11.889s at concurrency eight; see CALIBRATION.md for timing scope. We rerun both systems on the same Linux machine.

## How this is assessed

| What we run | On what | Produces |
|---|---|---|
| `python -m contract_check.check --target <your service>` | your running service | `results/contract_check.json` — pass/fail per contract item |
| the 60 held-out cases, then a backend diff | a fresh database per case | `results/held_out_runs.jsonl` and the end-state match rate |
| our defect detectors | `results/audit_log.sqlite`, `results/traces/otlp.jsonl` | a findings list, expected empty |
| `make eval`, once clean and once per gateway regression | your eval suite | `results/eval_report.json` per run |
| the gateway ledger | every model call your service made | `results/ledger.jsonl` — tokens and cost per case |

Every number is computed by us from artefacts your process emitted as data. Nothing your process reports about its own correctness, cost or coverage is graded.

## You Decide

Which complaints share a root cause and which don't. What your eval suite is for — deploy gate, regression net, or both — and what it blocks on. Whether hardening means fixing Harbour in place or replacing a subsystem, and how you justify the larger diff. Where refusing and escalating beats trying harder. How much of this is a Harbour fix and how much is a library you would carry to the next engagement.

## Required Analysis

For each reported symptom: the root cause, the evidence that convinced you, the code path you changed, and the assertion that now fails if it returns. Say plainly if you could not reproduce one. Then the failure modes nobody complained about, and what you did about each.

## MEMO.md

One page to the head of platform engineering. What was actually wrong with the thing they inherited, in language they can repeat to their own director; what the service now guarantees and what it still does not; how they would know within an hour that it is misbehaving, and how they turn it off; and what one resolved case costs.

## Decision review

Follow [JUDGMENT_REVIEW.md](../JUDGMENT_REVIEW.md). We use your evidence and one new constraint in the existing technical conversation. No additional take-home round is required. Coding-agent use is allowed and disclosed; you own the decisions and their explanation.
