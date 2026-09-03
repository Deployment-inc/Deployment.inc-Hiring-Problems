# OP-04 references — Judge Without Ground Truth

| File | What it is |
|---|---|
| `dev.jsonl` | 480 labelled trajectories over 120 published cases. Tune on this. |
| `heldout.jsonl` | 240 trajectories over a further 60 published cases, **labels removed**. |
| `tool_schemas.json` | Tool descriptions and argument schemas as data; no Harbour import needed. |
| `score.py` | The official scorer. Stdlib only, and the exact program we run. |
| `trajectory.schema.json` | The shape of a trajectory row. |
| `manifest.json` | Counts, pass rates and the label provenance. |

Both splits are drawn from the 180 cases published with Harbour, and are **disjoint by
case** — so a held-out trajectory cannot be matched against a labelled one of the same case
and have its answer read off. What is withheld here is the label, not the case: your judge
sees the trajectory either way, and the only thing it must not see is whether the run
succeeded.

The current 60 cases held back from OP-01, OP-02 and OP-03 do not appear in these current files. This statement does not establish secrecy of earlier Git revisions. A separate private set contains Harbour trajectories on hidden cases. It uses the same tool vocabulary and model families. We run your judge on that ourselves; any additional transfer test must have its scope published before it is used to evaluate submissions, with the change process in EVALUATION_PROTOCOL.md.

## Where the labels come from

Not from a model, and not from an annotator. Every Harbour case carries a `goal_state`: the exact
backend rows that must exist once the request is handled properly. The label is whether those rows
were there when the run finished — an exact database diff. Nobody argued about it and no
frontier model produced it.

That is the whole premise: **you are measured against a fact your judge never sees.**

## What a trajectory contains

```json
{"id": "gpt-4.1-mini::c_0001#r0",
 "agent_model": "gpt-4.1-mini",
 "split": "public", "family": "fee_waiver", "difficulty": "easy",
 "trajectory": {
   "case": {"case_id": "c_0001", "customer_id": "cu_027", "loan_id": "ln_028",
            "message": "...the customer's message...", "family": "...", "difficulty": "..."},
   "turns": [{"role": "user", "content": "Case c_0001..."},
             {"role": "assistant", "content": "{\"tool\":\"verify_identity\",...}"},
             {"role": "user", "content": "Result of verify_identity: true"}],
   "audited_tool_calls": ["verify_identity", "waive_fee", "commit"]},
 "label": 1}
```

`turns` is the whole conversation: what the agent said, and **what each tool returned**, including
the policy refusals. `audited_tool_calls` is the tool layer's own record of the calls it saw, in
order.

**Read the turns, not just the call list.** Our first reference judge was shown the tool calls
without the results. Seeing a run of calls and no visible failures, it concluded everything had
worked and scored 0.54 balanced accuracy with an AUROC below chance — against 0.79 and 0.65 once
the results were included. Whether a call was refused, and why, is in the tool result that follows
it.

What a trajectory never contains: `goal_state`, backend rows, or the held-out labels.

## The splits

|  | dev | held-out |
|---|---|---|
| trajectories | 480 | 240 |
| distinct cases | 120 | 60 |
| agent models | `gpt-4.1-mini` 240, `gpt-5-mini` 240 | 120 each |
| pass rate | 0.679 | 0.633 |

Two agent models on purpose. They fail differently, and a judge tuned to one model's tells does
not transfer — which is the situation you would actually be in.

## The reference judge, and what it could not do

One budget-class model, one prompt, no retrieval, no fine-tuning. **Historical run on the earlier split; not revalidated on the current 480-row development split:**

| | |
|---|---|
| balanced accuracy | 0.7892 |
| MCC | 0.6487 |
| ECE | 0.0213 |
| **confidence AUROC** | **0.5563** |
| cost | ~774 input / ~500 output tokens per trajectory |

The targets were informed by these historical numbers; this reference is slightly below the 0.65 MCC target and substantially below the confidence target: **the AUROC bar is
0.65 and our reference judge scores 0.5563.** It does not clear its own confidence bar. It knows
whether it is right much better than it knows when it is right, and we would rather publish that
than quietly move the bar down to whatever we happened to score. A verdict a compliance team
cannot triage by confidence is a verdict they have to read in full, which is the thing they wanted
the judge for.

If you clear that one, you have beaten us at the part of this problem we consider unsolved.

## Running the scorer

```bash
python score.py --pred your_predictions.jsonl --gold labels.jsonl [--bins 10] [--report r.json]
```

Predictions: one object per line, `{"id", "verdict": 0|1, "confidence": 0.0-1.0, "category"}`.
Missing IDs or structurally invalid prediction values are counted as wrong; malformed JSON, duplicate IDs, and unknown IDs reject the file — a judge that declines to answer has
answered.
