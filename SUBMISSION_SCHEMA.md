# Submission format — revision 4

Upload `submission.yaml` (UTF-8, at most 64 KB) through the [private submission form](https://deployment.inc/hiring-challenges/#submit), never by public PR. The problem and repository URL must match the form fields; the commit SHA lives only here, in `commit`.
It points to an exact, clean commit in your separate private solution repository. Keep the YAML
outside that commit if necessary to avoid a self-referencing SHA. Updating your repository alone
does not change the evaluated SHA. For an update, send a new form entry and email hiring@deployment.inc with your old and new submission IDs. See [CONTACT.md](CONTACT.md).

`repo_visibility` must be `private` and `leaderboard` must be `false`. The reviewer independently
checks repository and artifact access; a declaration alone does not verify privacy. No candidate
submission, individual result or review note is published by this workflow.

```yaml
problem: OP-06
handle: your-github-handle
repo: https://github.com/you/your-solution
commit: 3f9c2e1a7b5d4c6e8f0a1b2c3d4e5f6a7b8c9d0e
repo_visibility: private
leaderboard: false
season: 1
pins_ack: true
models_ack: true
claimed:
  intent_accuracy: 0.55
  macro_f1: 0.50
  action_accuracy: 0.55
  noisy_accuracy: 0.48
  schema_valid_pct: 100.0
  top70_error_ratio: 0.85
  cost_per_message_usd: null
  latency_p95_s: null
spend:
  results_usd: 27.40   # API spend at pinned list prices; includes failed submitted runs
  compute_usd: 0      # reported separately, outside the US$50 API ceiling
  development_usd: 18 # optional
hardware: "CPU laptop; no GPU"
```

`claimed` reports development measurements only. Use JSON/YAML `null` for an unavailable metric;
never invent a hidden-set score, reference value or a successful unrun check. A pending metric must
be measured during reproduction before the corresponding bar can pass. Values must be finite
numbers, never NaN/Infinity. Duplicate IDs/keys, ambiguous records and unsafe file paths are errors.

## Common files at the submitted commit

`README.md`, `EXPERIMENT_LOG.md`, `DECISIONS.md`, `LANDSCAPE.md`, `MEMO.md`, `LICENSE`,
`scripts/reproduce.sh`, `results/manifest.json`, and nonempty `results/raw/`.

The script documents how to start the service or CLI and how to run evaluation; document subcommands
instead of starting a server that prevents the evaluation step from running. The reviewer uses the
script only in an isolated reproduction environment. For OP-01 also include `RUNBOOK.md`,
`THREAT_MODEL.md` and `SLO.md`.

The manifest is an object with `claimed` exactly matching the submission, and nonempty `runs`:

```json
{"claimed":{"action_accuracy":0.55},"runs":[{"run_id":"dev-001","seed":42,"model":"exact-snapshot","status":"completed","input_sha256":"...","raw_path":"results/raw/dev-001.jsonl"}]}
```

Use unique run IDs. Record timestamps, configuration, model snapshots, token counts, costs and
failed runs. Artifact paths are relative to the solution root and may not escape it or be symlinks.
Large external artifacts must be access-controlled and shared only with reviewers, with a URL and
SHA-256. Do not embed credentials in URLs or manifests. They must be staged and verified by the reviewer
before evaluation; the evaluator never downloads or executes URLs from a candidate manifest.

## Per-problem development artifacts

| Problem | Files in `results/` | Preliminary claim keys |
|---|---|---|
| OP-01 | `contract_check.json`; raw cases, database snapshots, traces and regression outputs | `contract_items_passed`, `regressions_caught` |
| OP-02 | `equivalence.jsonl`; raw old/new/degraded cases, audit databases and eval outputs | `decision_agreement` |
| OP-03 | `runs.jsonl`, `ledger.jsonl`, `pareto.jsonl`; raw evidence for every operating point | `cost_per_resolved_case`, `success_rate`, `deferral_rate`, `elective_deferral_rate`, `latency_p95_s`, `pareto_points` |
| OP-04 | `dev_predictions.jsonl`, `heldout_predictions.jsonl`, `audit_50.md`; judge CLI | `dev_balanced_accuracy`, `dev_mcc`, `dev_ece`, `dev_confidence_auroc` |
| OP-05 | `answers_dev.jsonl`; `/ask` service; no crawl or fetch log is required | `coverage`, `citation_verbatim_rate`, `ooc_refusal_rate`, `detected_role_violations` |
| OP-06 | `dev_predictions.jsonl`, `noisy_predictions.jsonl`, `hostile_results.jsonl`, `latency_bench.json`; service | `intent_accuracy`, `macro_f1`, `action_accuracy`, `noisy_accuracy`, `schema_valid_pct`, `top70_error_ratio` |

Additional problem-bar measurements belong in the manifest with their evidence and provenance.
The preliminary table is not the qualification rubric. Every problem still requires its full
published bars, independent runtime evidence and [decision review](JUDGMENT_REVIEW.md).
`detected_role_violations: 0` means the deterministic checks detected none; it does not certify
absence of semantic leakage. Candidate `latency_bench.json` documents sample count, concurrency,
request IDs and externally measured durations; it is rerun by us.

OP-02 equivalence rows use `{id, old, new}`, where each decision is
`{tools: [{name, args}], escalated: bool, committed: bool}`. `tools` is the ordered list of
**successful state-changing** calls, including arguments. Failed calls remain in raw audit data,
not in the decision list. Empty or missing decisions cannot be interpreted as agreement.

Candidate OP-03 artifacts use the published development cases; reviewers generate private runs themselves. OP-03 runs and ledger follow `references/OP-03/ledger_reader.py`. Supply trusted case definitions with `--cases` to derive required escalations and the elective-deferral rate. A candidate-supplied classification of a case as requiring escalation is not authoritative. Each Pareto point names a real
manifest run with its own matching ledger and observed outcomes. A run ID alone does not verify a
point. A no-call case needs a zero-cost ledger row so omitted spend cannot look like a free run.

OP-04 predictions use `{id, verdict: 0|1, confidence: 0..1, category}`. OP-05 uses
`{id, status: "answered"|"not_in_corpus"|"not_permitted", answer, citations: [{doc_id, section, quote}]}`.
The requester role comes from the input question, not from a prediction. OP-06 uses
`{id, intent, action, confidence, needs_human}`, as defined by its output schema.

An official scorer can establish file consistency without establishing who produced those files.
See [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md) for the trust boundary and pending states.
