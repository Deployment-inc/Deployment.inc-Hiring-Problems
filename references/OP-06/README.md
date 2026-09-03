# OP-06 references — Triage the Inbox

Everything here is what we run. The scorer in this folder is the scorer that grades you; there is
no second, stricter one held back.

## Files

| File | What it is |
|---|---|
| `train.jsonl.gz` | 20,000 labelled rows from ABCD's own train split. Fit on this. |
| `dev.jsonl` | 2,000 labelled rows from ABCD's dev split. Tune and report on this. |
| `dev_noisy.jsonl` | 300 rows from `dev.jsonl` with the last customer turn rewritten badly. Same labels. |
| `hostile.jsonl` | 9 inputs that are not requests at all. No labels — the only thing scored is that you stayed up and were not talked into anything. |
| `input.schema.json` | Candidate-visible request shape: id, context, optional turn_index. Gold and permitted_actions are excluded. |
| `guidelines.json` | Published written procedures; may be indexed by the submission. |
| `schema.json` | The response shape. `id, intent, action, confidence, needs_human` are required. |
| `grader.py` | The official scorer. Stdlib only. |
| `baseline.py` | The published lexical baseline. Stdlib only, no API key, no GPU. |
| `manifest.json` | Provenance: source URLs, SHA-256 of both upstream files, seed, counts. |

The held-out split is built the same way from ABCD's test conversations and is not published.
ABCD's own split boundaries are respected throughout, so no conversation appears in two splits.

## The unit

One row is **one action-taking turn**: the dialogue up to that point, and the action the human
agent took next.

```json
{"id": "3129-8",
 "context": [{"speaker": "customer", "text": "i want to return an item"},
             {"speaker": "agent", "text": "sure, may i have your name?"}],
 "intent": "return_size", "flow": "product_defect",
 "action": "pull-up-account",
 "permitted_actions": ["ask-the-oracle", "enter-details", "..."],
 "turn_index": 8}
```

Context is capped at the last 8 turns so a prompt cannot grow without bound.

**Why a conversation prefix and not a single message.** The problem is about the *permitted
action*, and in ABCD an action is only defined part-way through a dialogue. The first action of a
conversation is `pull-up-account` 67% of the time — a one-message action label would be a coin
toss dressed up as a task. Predicting the next action from the dialogue so far is ABCD's own
Action State Tracking framing and is grounded in labels a human agent actually produced.

## `permitted_actions`, and the 9% you should know about

`permitted_actions` is what that flow's written procedure in ABCD's `guidelines.json` authorises,
resolved into the action names the data actually uses. (The guidelines and the turn labels name
some things differently, and the guidelines fold every knowledge-base lookup into one step; that
is resolved once, at build time, so you can test membership directly.)

**About 9% of the gold actions are outside the permitted set**, because real agents deviate from
the written procedure. This is not a bug and we have not cleaned it. It means a perfect predictor
of the gold label still scores about 9% policy violations, so `grader.py` reports your rate
alongside the gold's own rate rather than against zero. What you do about that gap — follow the
label, follow the policy, or flag the conflict — is part of the problem, and we would rather read
your reasoning than see the number quietly optimised.

## The baseline, measured

`baseline.py` is bag-of-words nearest-centroid for the intent, and the most frequent action for
that intent at that stage of the dialogue. Trained on `train.jsonl.gz`, scored on
`dev.jsonl` + `dev_noisy.jsonl`:

| | |
|---|---|
| Intent accuracy | 0.3748 |
| Action accuracy | 0.3913 |
| Intent macro-F1 | 0.4508 |
| Clean-to-noisy action gap | 0.0743 |
| Schema valid, incl. hostile | 100% |
| Policy violation rate | 0.1404 (gold's own: 0.0883) |
| Confidence error ratio | **1.0** |

That last number is the interesting one. Its confidence orders nothing — the most-confident 70%
of its predictions are exactly as wrong as the rest. Beating it on accuracy is not hard; producing
a confidence a manager could actually route on is the part worth your time.

## Running both

```bash
python baseline.py --train train.jsonl.gz --eval dev.jsonl \
    --eval-noisy dev_noisy.jsonl --eval-hostile hostile.jsonl \
    --pred-out baseline_predictions.jsonl

python grader.py --pred baseline_predictions.jsonl --gold dev.jsonl \
    --noisy dev_noisy.jsonl --hostile hostile.jsonl --schema schema.json \
    --report report.json
```

Predict for every row you are given, hostile ones included. A missing prediction is scored as
wrong, and a hostile input with no response counts against schema validity — which is the one bar
that must be perfect, because a response that does not parse is not a wrong answer, it is an
outage.

## Licence

ABCD is MIT, © ASAPP Inc. `manifest.json` records the exact upstream URLs and their SHA-256 so
you can verify you have the same bytes we do.

## Service contract

`scripts/reproduce.sh` starts the service on `PORT`. `GET /healthz` returns 200 after loading.
`POST /triage` accepts `input.schema.json` and returns `schema.json`, echoing the input id.
The reviewer projects labelled rows with `../evaluation_inputs.py`; never rely on gold-only fields
being present at inference. Inputs may contain empty strings, unusual Unicode and long text.

For a valid envelope whose text cannot be handled, return the normal response shape with
`intent: "unknown"`, `action: "none"`, `confidence: 0`, `needs_human: true`; an extra
`error: {"code": "invalid_input", "message": "..."}` may explain the abstention. This is a defined
error response that still passes structural validation. It earns no intent/action credit on a
labelled example. Malformed HTTP/JSON envelopes may return HTTP 400 with an error object; those
transport probes are separate from the published valid-JSON hostile rows. Document bounded request
timeouts and body limits that accommodate the published pack.

Context speakers may be `customer`, `agent` or `action`; action turns describe prior observed actions, never the withheld next-action label. Preserve them when constructing model input.
