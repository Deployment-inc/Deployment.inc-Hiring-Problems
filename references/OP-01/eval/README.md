# Harbour eval suite

This is the suite CI runs on every change to `harbour/`. One command, one JSON
report, no fixtures to maintain.

```
python eval/suite.py
```

Nothing else is needed: no API key, no network, no running service. The suite
sets `LLM_FAKE=1` for itself so the model path replays the canned servicing
replies, which is what makes the run fast enough to sit in the pre-merge check.
If you want to run it against a real endpoint, export `LLM_FAKE=0` along with
the usual `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` and run it again.

## What it runs

Forty cases drawn from `cases/cases.jsonl`: the first eight easy published cases
in each of five families.

| Family | Cases |
|---|---|
| `fee_waiver` | 8 |
| `payment_reschedule` | 8 |
| `document_request` | 8 |
| `contact_update` | 8 |
| `autopay_cancel` | 8 |

Those five journeys are the bulk of live volume, so a regression that matters to
customers shows up here first. Each case runs against its own in-memory backend
seeded from `harbour/seed.json`, so cases cannot contaminate each other and the
order they run in does not matter.

A case passes when the agent worked it through to a close — the run returned a
summary and the tool layer recorded a `commit` against that case id. The
audit log is the thing we check, not what the agent says it did, because the
agent cannot write to the audit log itself.

## What it reports

`eval/eval_report.json`, overwritten on every run:

```json
{
  "cases": 40,
  "passed": 40,
  "threshold": 0.9,
  "pass": true,
  "by_family": {"fee_waiver": {"cases": 8, "passed": 8}, "...": {}},
  "results": [
    {"case_id": "c_0001", "family": "fee_waiver", "difficulty": "easy",
     "passed": true, "committed": true, "actions_taken": ["verify_identity",
     "lookup_loan", "waive_fee"], "error": null, "seconds": 0.02}
  ]
}
```

`pass` is `true` when at least 90% of the sampled cases pass. The process exit
code follows it, so CI needs no extra glue. `results` carries a row per case;
when something goes red, start with the rows where `committed` is `false` and
read the `error` field.

## Options

| Flag | Effect |
|---|---|
| `--cases PATH` | run against a different case file |
| `--report PATH` | write the report somewhere other than `eval/eval_report.json` |
| `--limit N` | run only the first N cases (smoke check while developing) |
| `--quiet` | suppress the per-case lines |

## Adding cases

Don't hand-edit `cases/cases.jsonl` — it is generated. Add a spec to
the private maintainer case generator (not distributed) and rebuild:

```
python cases/build_cases.py
```

The builder validates every case by executing its tool sequence against a
scratch backend before it writes anything, so a case with an unreachable goal
state fails the build rather than the suite. The suite picks up new cases in the
sampled families automatically.
