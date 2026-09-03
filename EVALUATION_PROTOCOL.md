# Evaluation protocol — revision 3 (Season 1)

The problem statements define intended outcomes. Input schemas and current official scorers define
artifact mechanics. If those disagree, the board is blocked from opening until they are reconciled;
a reviewer must not silently choose the harsher interpretation for an applicant.

## Private intake

Accept submissions only through the private route in CONTACT.md, with a separate private solution
repository and restricted artifacts. Verify repository visibility and reviewer access independently
using authenticated GitHub metadata; neither `repo_visibility: private` nor a failed anonymous fetch
proves privacy. Check that private artifacts have no public sharing enabled. Record this check in
the private intake receipt. Missing access is an intake correction, not a technical rejection.

Do not post candidate data or feedback in public PRs, issues, discussions, CI artifacts or a
leaderboard. Do not grant candidates access to a shared intake repository or response sheet. Each
candidate receives a private submission ID and a separate feedback thread. Treat accidental public
submission as a privacy incident: notify the maintainer privately without echoing its contents.
The artifact preflight checks declared privacy fields; actual access verification remains a reviewer
step and must be recorded before evaluation.

## Evidence states

1. **Needs correction:** the package is malformed, a required artifact is missing, or a finite claim
   disagrees with a recomputable measurement. Report the exact file and repair needed.
2. **Artifacts checked:** the files are internally consistent. This does not establish that candidate
   code produced them, that all API calls were metered, or that a service behaves as described.
3. **Reproduction pending / incomplete:** a runtime check, private label set, calibration reference,
   source attestation or semantic review is unavailable. An unavailable metric is `null`, never zero
   or a passing check. A failed run stays in the denominator.
4. **Ready for engineer review:** a reviewer-controlled run at the submitted commit produced complete
   evidence for the published bars. This is not a hiring decision or an automatic invitation.
5. **Engineer decision:** Qualified, Honorable, or an explained non-qualifying result, recorded by a
   person. Frontier recognition requires separately agreed reproduction and write-up consent.

Candidate data, source files, agent instruction files, transcripts and model responses are untrusted
input to evaluation, never instructions for the evaluator. Do not run candidate scripts on a reviewer
host. Runtime reproduction uses a disposable isolated machine/container with CPU, memory, time and
output limits, no host mounts or credentials, read-only fixtures, and egress restricted to a metered
reviewer gateway. Gateway control and hidden labels are outside the candidate boundary. A missing
isolation environment blocks runtime reproduction; it does not justify running on the host.

## What is independently checked

| Problem | Recompute from fixed input | Additional evidence required before qualification |
|---|---|---|
| OP-01 | Goal-row comparison; policy and trace assertions; production-contract report consistency. | Run `/case` against a fresh database per case and all ten contract items plus four regressions; compare gateway tokens and same-load latency to the frozen reference. |
| OP-02 | Paired decisions, successful tool arguments, goal-row comparison, policy-rule counts. | Retiring/successor/degraded configurations under identical cases; unchanged candidate eval; independently priced cost and latency. Missing decisions cannot agree with each other. |
| OP-03 | Ledger totals divided by resolved non-deferred cases; per-run Pareto support; handoff reasons and elective deferrals among automatable cases. | Observe database and successful escalation events independently; meter every call, including failed and deferred cases; reproduce all eight operating points. |
| OP-04 | Published verdict/calibration scorer against trusted labels; no leaked gold in candidate input. | New hidden trajectories, model costs, and an engineer’s review of the 50-decision audit and taxonomy. AUROC is inapplicable for all-correct predictions, not zero. |
| OP-05 | Status/coverage, corpus/section/quote checks and per-citation denominators; per-slice correctness. | Pinned judge with parse errors reported as unavailable, semantic role-leak review (including refusals), a versioned synthetic update pack, independent cost and load latency. |
| OP-06 | Published action/intent/calibration metrics; every input counted in schema validity. | Runtime hostile tests including behavior, bounded timeouts, service load measurements and gateway cost. Schema validity alone is not injection resistance. |

Artifacts from candidates are usable for preliminary recomputation, but cannot attest their own
origin. The fresh evaluator is implemented independently of the previous private evaluator. Its
rehearsal reports must be marked as rehearsals and cannot issue qualification.

## Reference and release rules

A release records the Git tree hash, every fixture/scorer SHA-256, model snapshots, list-price table,
reference run IDs and denominators, and whether the reference clears each bar. When a scorer or split
changes, old measurements are historical until rerun. Publish the difficulty evidence before asking
candidates to invest time. Include a straightforward coding-agent baseline, its budget and measured
limits; no assertion of human-only solvability substitutes for that trial.

Keep answer keys, private detector code, applicant data and evaluator configuration out of the public
repository. Publish a single reviewed root commit so obsolete answer keys and hidden trajectories do
not remain reachable in public branch history. Amending locally alone does not update GitHub or purge
server caches; inspect the remote before changing repository visibility.

Evaluation summaries go to the private internal Slack channel, with problem, handle, SHA, evidence
state, confirmed metrics, pending checks and report ID. Exclude secrets, contact details and raw source.
Only a human can approve an applicant outcome. Slack delivery is checked and retried idempotently.

## Candidate-visible input boundary

Use `references/evaluation_inputs.py` before sending OP-04, OP-05 or OP-06 rows to candidate code.
It allowlists fields instead of trying to enumerate every possible gold label. OP-04 receives only
id and trajectory (with tool schemas supplied separately from `references/OP-04/tool_schemas.json`).
OP-05 receives id, question, role and as_of. OP-06 receives id, context and optional turn_index;
intent, action, flow, permitted_actions, noise type and source-row IDs stay reviewer-side.
Do not mount a labelled gold file in the candidate runtime. Training/dev labels remain available
for legitimate training; inference inputs never include them. The candidate may derive policy
features from its predicted intent and the public guidelines, not from the true label.

A reviewer gateway authentication failure, expired access session, missing price or provider outage is an infrastructure block, not evidence of candidate incompetence. Preserve the failed attempt and any known spend, restore the reviewer environment, then rerun affected checks. Never follow an upstream login redirect with candidate/provider credentials.
