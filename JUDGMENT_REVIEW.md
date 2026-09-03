# Decision evidence and the technical conversation

Coding agents are allowed. We do not use AI-text detectors, typing speed, a distinctive writing style,
or an assertion that a task is “AI-proof” as evidence of ability. You are responsible for understanding,
checking and explaining the work you submit. A solution generated with assistance can be excellent;
a polished artifact alone does not establish that its author can operate it.

## What to include in the existing documents

In `DECISIONS.md`, record three consequential decisions (two for OP-06). For each, include the
initial hypothesis, at least two plausible options, the constraint that mattered, the experiment or
observation that changed your view, the option chosen, and what evidence would make you reverse it.
Link to dated entries and raw runs in `EXPERIMENT_LOG.md`. Reconstructed notes are allowed: label them
as reconstructed instead of presenting them as contemporaneous. Report significant coding-agent
assistance and which outputs you independently checked. No private thought process or full private
chat history is required.

At least one decision must concern a failure or inconclusive experiment. “Nothing failed” needs
supporting evidence, not an invented story. In `MEMO.md`, name the residual risk, who would bear its
cost, and the operational condition under which you would pause rollout or send work to a person.
These requirements fit inside the existing documents and time budget.

## The one technical conversation

An engineer selects a raw run from your submission and asks you to explain what happened, why the
measurement supports your conclusion, and what it leaves uncertain. You then work through one new
constraint from the published families below. The exact instance is unseen; the skill being tested
and assessment criteria are public. We supply any required facts. You may consult documentation and
use your usual tools, including coding agents. We assess the checks and decisions you make with them.
No additional take-home implementation or unpaid round is required.

| Problem | New constraint family | Evidence of understanding |
|---|---|---|
| OP-01 | An upstream times out after a tool may have committed, or a model reports a different identity. | Distinguishes an unknown outcome from a safe retry; proposes an observable check and rollback boundary. |
| OP-02 | Aggregate migration quality holds but one customer family deteriorates; the retirement date moves forward. | Uses paired case evidence, quantifies uncertainty and chooses a rollout/fallback decision with an explicit cost. |
| OP-03 | Traffic mix changes or a cache becomes stale while backend state changes. | Recalculates cost per resolved case including failures/deferrals, identifies unsafe savings and changes the operating point. |
| OP-04 | The judge encounters a different failure family, or the database label conflicts with defensible servicing behavior. | Separates benchmark truth from task adequacy, inspects tool results and revises confidence or escalation criteria. |
| OP-05 | A fictional policy amendment changes precedence or access, including an as-of-date question. | Identifies authoritative evidence, handles version and role boundaries, and distinguishes a supported answer from a plausible one. |
| OP-06 | A written procedure changes or a two-intent request conflicts with the next permitted action. | Notices the conflict, explains uncertainty, and chooses a safe action or human route with a testable check. |

We do not ask you to know an unpublished regulation or guess a reviewer’s preferred architecture.
Policy changes in review exercises are synthetic task rules, not real-world legal guidance.

## Reviewer rubric

For each of the seven dimensions in the README, an engineer records evidence, an uncertainty and a
0–3 rating: 0 = absent or contradicted; 1 = assertion with limited evidence; 2 = reproducible evidence
and a defensible decision; 3 = tests alternatives and explains when the decision stops being valid.
An automated assistant may organise evidence and draft questions. It cannot determine a hiring
outcome. Reviewers evaluate job-related work only, not personal background or protected traits.

A metric failure can still support an Honorable result. A missing file is a request to repair the
package, not a claim of dishonesty. Apparent inconsistencies are put to the candidate before an
integrity finding. Invite/decline and any public result require a named engineer’s decision.
