#!/usr/bin/env python3
"""The published lexical baseline. No model, no API key, no GPU — and the bar you have to beat.

    python baseline.py --train train.jsonl.gz --pred-out baseline_predictions.jsonl \
        --eval dev.jsonl [--eval-noisy dev_noisy.jsonl] [--eval-hostile hostile.jsonl]

It is deliberately dull: a bag-of-words nearest-centroid over the last few turns for the intent,
and, for the action, the most frequent action seen in training for the predicted intent at a
similar point in the dialogue. Confidence is the margin between the top two intent scores.

Publishing it does two things. It stops anyone wondering whether the task is trivial — you can
see exactly how far dull gets you — and it makes the bars honest, because they are set from a
measurement rather than from a guess about what ought to be hard.

Stdlib only.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9']+")
#: Only the tail of the dialogue is used. The opening pleasantries are the same in every flow.
TAIL_TURNS = 4


def tokens(row: dict) -> list[str]:
    text = " ".join(t.get("text", "") for t in (row.get("context") or [])[-TAIL_TURNS:])
    return TOKEN.findall(text.lower())


def turn_bucket(row: dict) -> str:
    """Early, middle or late in the dialogue. Which action is next depends heavily on this."""
    idx = row.get("turn_index") or 0
    return "early" if idx <= 6 else ("mid" if idx <= 14 else "late")


class Baseline:
    def __init__(self) -> None:
        self.centroids: dict[str, dict[str, float]] = {}
        self.action_by_intent_bucket: dict[tuple[str, str], str] = {}
        self.action_by_intent: dict[str, str] = {}
        self.fallback_action = "pull-up-account"
        self.fallback_intent = "manage"

    def fit(self, rows: list[dict]) -> "Baseline":
        # Term frequencies per intent, then IDF-weighted and L2-normalised into a centroid.
        per_intent: dict[str, Counter] = defaultdict(Counter)
        doc_freq: Counter = Counter()
        for row in rows:
            toks = tokens(row)
            per_intent[row["intent"]].update(toks)
            doc_freq.update(set(toks))
        n_docs = max(1, len(rows))
        for intent, counts in per_intent.items():
            vec = {t: c * math.log(n_docs / (1 + doc_freq[t])) for t, c in counts.items()}
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            self.centroids[intent] = {t: v / norm for t, v in vec.items()}

        pair: dict[tuple[str, str], Counter] = defaultdict(Counter)
        solo: dict[str, Counter] = defaultdict(Counter)
        for row in rows:
            pair[(row["intent"], turn_bucket(row))][row["action"]] += 1
            solo[row["intent"]][row["action"]] += 1
        self.action_by_intent_bucket = {k: c.most_common(1)[0][0] for k, c in pair.items()}
        self.action_by_intent = {k: c.most_common(1)[0][0] for k, c in solo.items()}
        self.fallback_action = Counter(r["action"] for r in rows).most_common(1)[0][0]
        self.fallback_intent = Counter(r["intent"] for r in rows).most_common(1)[0][0]
        return self

    def predict(self, row: dict) -> dict:
        toks = Counter(tokens(row))
        norm = math.sqrt(sum(v * v for v in toks.values())) or 1.0
        scored = []
        for intent, centroid in self.centroids.items():
            scored.append((sum(centroid.get(t, 0.0) * c for t, c in toks.items()) / norm, intent))
        scored.sort(reverse=True)

        if not scored or scored[0][0] <= 0:
            intent, confidence = self.fallback_intent, 0.05
        else:
            intent = scored[0][1]
            runner_up = scored[1][0] if len(scored) > 1 else 0.0
            # The margin, squashed. A wide gap to the runner-up is the only evidence of
            # confidence a model this simple has.
            confidence = round(min(0.99, max(0.05, (scored[0][0] - runner_up) * 4)), 4)

        action = (self.action_by_intent_bucket.get((intent, turn_bucket(row)))
                  or self.action_by_intent.get(intent)
                  or self.fallback_action)
        return {"id": str(row["id"]), "intent": intent, "action": action,
                "confidence": confidence,
                # Hand over anything the margin says is a coin toss. That is the whole of its
                # judgement, and it is worth exactly what it costs.
                "needs_human": confidence < 0.20}


def load(path: str | None) -> list[dict]:
    """Read a .jsonl or .jsonl.gz. The training split ships gzipped; nothing else needs to be."""
    if not path:
        return []
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", required=True)
    ap.add_argument("--eval", required=True)
    ap.add_argument("--eval-noisy")
    ap.add_argument("--eval-hostile")
    ap.add_argument("--pred-out", required=True)
    args = ap.parse_args(argv)

    model = Baseline().fit(load(args.train))
    rows = load(args.eval) + load(args.eval_noisy) + load(args.eval_hostile)

    out = []
    for row in rows:
        started = time.perf_counter()
        pred = model.predict(row)
        pred["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        pred["cost_usd"] = 0.0          # it runs on a laptop; that is the point
        out.append(pred)

    Path(args.pred_out).write_text("\n".join(json.dumps(p) for p in out) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} predictions to {args.pred_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
