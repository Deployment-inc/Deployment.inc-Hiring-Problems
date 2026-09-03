#!/usr/bin/env python3
"""OP-04 scorer: balanced accuracy, Matthews correlation, AUROC of confidence and expected calibration error.

Usage:
    python score.py --pred predictions.jsonl --gold heldout_labels.jsonl [--bins 10] [--report report.json]

predictions.jsonl, one object per line:
    {"id": "...", "verdict": 0|1, "confidence": 0.0-1.0, "category": "..."}
gold.jsonl, one object per line:
    {"id": "...", "label": 0|1}

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter


def load_jsonl(path: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                sys.exit(f"{path}:{n}: invalid JSON ({e})")
            if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or not obj["id"]:
                sys.exit(f"{path}:{n}: missing id")
            if obj["id"] in rows:
                sys.exit(f"{path}:{n}: duplicate id {obj['id']}")
            rows[obj["id"]] = obj
    return rows


def balanced_accuracy(y: list[int], p: list[int]) -> float:
    tp = sum(1 for a, b in zip(y, p) if a == 1 and b == 1)
    tn = sum(1 for a, b in zip(y, p) if a == 0 and b == 0)
    pos = sum(y)
    neg = len(y) - pos
    tpr = tp / pos if pos else 0.0
    tnr = tn / neg if neg else 0.0
    return (tpr + tnr) / 2


def cohens_kappa(y: list[int], p: list[int]) -> float:
    n = len(y)
    if n == 0:
        return 0.0
    po = sum(1 for a, b in zip(y, p) if a == b) / n
    cy, cp = Counter(y), Counter(p)
    pe = sum((cy[k] / n) * (cp[k] / n) for k in (0, 1))
    return (po - pe) / (1 - pe) if pe != 1 else 1.0


def mcc(y: list[int], p: list[int]) -> float:
    tp = sum(1 for a, b in zip(y, p) if a == 1 and b == 1)
    tn = sum(1 for a, b in zip(y, p) if a == 0 and b == 0)
    fp = sum(1 for a, b in zip(y, p) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(y, p) if a == 1 and b == 0)
    denom = ((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) ** 0.5
    return (tp * tn - fp * fn) / denom if denom else 0.0


def auroc(correct: list[int], conf: list[float]) -> float | None:
    """Probability that a correct verdict carries higher confidence than an incorrect one (ties count half).
    A constant confidence scores exactly 0.5."""
    pos = [c for c, k in zip(conf, correct) if k == 1]
    neg = [c for c, k in zip(conf, correct) if k == 0]
    if not pos or not neg:
        return None
    wins = 0.0
    for a in pos:
        for b in neg:
            wins += 1.0 if a > b else 0.5 if a == b else 0.0
    return wins / (len(pos) * len(neg))


def ece(y: list[int], p: list[int], conf: list[float], bins: int) -> float:
    """ECE on the confidence of the *predicted* verdict (correctness vs confidence)."""
    total = 0.0
    n = len(y)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(conf) if (lo <= c < hi) or (b == bins - 1 and c == 1.0)]
        if not idx:
            continue
        acc = sum(1 for i in idx if y[i] == p[i]) / len(idx)
        avg_conf = sum(conf[i] for i in idx) / len(idx)
        total += (len(idx) / n) * abs(acc - avg_conf)
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--report")
    a = ap.parse_args()
    if a.bins < 1:
        ap.error("--bins must be positive")

    pred, gold = load_jsonl(a.pred), load_jsonl(a.gold)
    if not gold or any(type(g.get("label")) is not int or g["label"] not in (0, 1) for g in gold.values()):
        sys.exit("gold must contain nonempty records with integer labels 0 or 1")
    if set(pred) - set(gold):
        sys.exit("predictions contain unknown ids")
    missing = [k for k in gold if k not in pred]
    if missing:
        print(f"warning: {len(missing)} gold ids missing from predictions; they count as wrong", file=sys.stderr)

    y, p, conf, bad = [], [], [], 0
    for k, g in gold.items():
        label = int(g["label"])
        r = pred.get(k)
        if r is None or type(r.get("verdict")) is not int or r.get("verdict") not in (0, 1) or not isinstance(r.get("confidence"), (int, float)) or isinstance(r.get("confidence"), bool) or not math.isfinite(r["confidence"]) or not 0 <= r["confidence"] <= 1:
            bad += 1
            y.append(label)
            p.append(1 - label)
            conf.append(0.5)
            continue
        c = r.get("confidence", 0.5)
        try:
            c = float(c)
        except (TypeError, ValueError):
            c = 0.5
        c = min(max(c, 0.0), 1.0)
        y.append(label)
        p.append(int(r["verdict"]))
        conf.append(c)

    cats = Counter(str(pred[k].get("category", "")) for k in gold if k in pred)
    correct = [1 if a == b else 0 for a, b in zip(y, p)]
    auc = auroc(correct, conf)
    out = {
        "n": len(y),
        "invalid_or_missing": bad,
        "balanced_accuracy": round(balanced_accuracy(y, p), 4),
        "mcc": round(mcc(y, p), 4),
        "confidence_auroc_applicability": "defined" if auc is not None else "only_one_correctness_class",
        "confidence_auroc": round(auc, 4) if auc is not None else None,
        "ece": round(ece(y, p, conf, a.bins), 4),
        "cohens_kappa_reported_only": round(cohens_kappa(y, p), 4),
        "predicted_pass_rate": round(sum(p) / len(p), 4) if p else None,
        "gold_pass_rate": round(sum(y) / len(y), 4) if y else None,
        "categories": dict(cats.most_common()),
    }
    print(json.dumps(out, indent=2))
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
