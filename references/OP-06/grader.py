#!/usr/bin/env python3
"""OP-06 official scorer. This is the exact program we run; nothing about the metric is a surprise.

    python grader.py --pred predictions.jsonl --gold dev.jsonl \
        [--noisy dev_noisy.jsonl] [--hostile hostile.jsonl] [--schema schema.json] \
        [--report report.json] [--quiet]

One prediction per line, keyed by `id`:

    {"id": "...", "intent": "...", "action": "...", "confidence": 0.0-1.0, "needs_human": bool}

Extra keys are tolerated and two are used if present: `cost_usd` and `latency_ms`.

What is scored, and why each one is here:

- **Intent accuracy and macro-F1.** Macro-F1 as well as accuracy because the intent distribution
  has a long tail; a system that nails the common intents and drops the rest looks fine on
  accuracy alone.
- **Action accuracy**, scored separately. Knowing the intent does not tell you the action —
  in this data the intent predicts the majority action only 27% of the time — so a single
  combined number would hide which half is broken.
- **The noisy slice, scored on its own.** A system excellent on clean text and helpless on a typo
  is not deployable, and a blended average lets that hide.
- **Policy violations:** predicted actions outside what the flow's written procedure authorises.
  Note the gold labels themselves violate the written policy about 9% of the time, because real
  agents deviate. So this is scored against the gold's own rate, not against zero.
- **Schema validity over every input, including the hostile pack.** A response that does not
  parse is not a wrong answer, it is an outage.
- **Confidence usefulness.** The error rate on the most-confident 70% against the overall error
  rate. A constant confidence scores 1.0 here and tells the manager nothing about when to look.

Stdlib only. Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from collections import Counter, defaultdict
from typing import Any

GRADER_VERSION = "2.1"

#: Every bar is set from a measurement, never from a guess about what ought to be hard.
#: `baseline.py`, trained on train.jsonl and scored on dev.jsonl + dev_noisy.jsonl, gets:
#:
#:     intent accuracy 0.3748   action accuracy 0.3913   intent macro-F1 0.4508
#:     clean-to-noisy action gap 0.0743   schema valid 100%
#:     policy violation rate 0.1404 (the gold labels' own rate is 0.0883)
#:     confidence error ratio 1.0 — its confidence orders nothing at all
#:
#: The bars sit a clear margin above that, so passing means beating bag-of-words by something
#: that matters rather than by noise.
BASELINE = {
    "intent_accuracy": 0.3748, "action_accuracy": 0.3913, "macro_f1": 0.4508,
    "noisy_gap": 0.0743, "schema_valid_pct": 100.0,
    "policy_violation_rate": 0.1404, "gold_policy_violation_rate": 0.0883,
    "top70_error_ratio": 1.0,
}
BARS = {
    "intent_accuracy": 0.55,        # baseline 0.3748
    "action_accuracy": 0.55,        # baseline 0.3913
    "macro_f1": 0.50,               # baseline 0.4508
    "schema_valid_pct": 100.0,      # baseline already clears this; an outage is not a wrong answer
    "noisy_gap": 0.10,              # baseline 0.0743 — do not regress on noisy text to buy clean
    "top70_error_ratio": 0.85,      # baseline 1.0: confidence must actually order the errors
}


# --------------------------------------------------------------------------- io

def load_jsonl(path: str, what: str) -> list[dict]:
    rows = []
    seen = set()
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or not obj["id"] or obj["id"] in seen:
                    raise ValueError("missing, invalid or duplicate id")
                seen.add(obj["id"])
                rows.append(obj)
            except ValueError as exc:
                sys.exit(f"{path}:{n}: {what} is not valid JSON ({exc})")
    return rows


def by_id(rows: list[dict]) -> dict[str, dict]:
    return {str(r["id"]): r for r in rows if "id" in r}


# --------------------------------------------------------------------------- metrics

def accuracy(pairs: list[tuple[Any, Any]]) -> float:
    return round(sum(1 for g, p in pairs if g == p) / len(pairs), 4) if pairs else 0.0


def macro_f1(pairs: list[tuple[Any, Any]]) -> float:
    """Unweighted mean F1 over every class present in the gold labels."""
    if not pairs:
        return 0.0
    tp, fp, fn = Counter(), Counter(), Counter()
    for gold, pred in pairs:
        if gold == pred:
            tp[gold] += 1
        else:
            fn[gold] += 1
            fp[pred] += 1
    scores = []
    for cls in {g for g, _ in pairs}:
        precision = tp[cls] / (tp[cls] + fp[cls]) if tp[cls] + fp[cls] else 0.0
        recall = tp[cls] / (tp[cls] + fn[cls]) if tp[cls] + fn[cls] else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return round(sum(scores) / len(scores), 4)


def confidence_report(rows: list[tuple[float, bool]]) -> dict[str, Any]:
    """Overall accuracy against accuracy on the most-confident 70%.

    Ties at the cut are kept, so a system that returns one confidence value for everything gets
    the same two numbers and a ratio of 1.0 — which is the honest answer: its confidence orders
    nothing.
    """
    if not rows:
        return {"n": 0, "overall_accuracy": None, "top70_accuracy": None}
    ordered = sorted(rows, key=lambda x: -x[0])
    cut = max(1, int(round(0.70 * len(ordered))))
    threshold = ordered[cut - 1][0]
    top = [r for r in ordered if r[0] >= threshold]
    overall = sum(1 for _, ok in ordered if ok) / len(ordered)
    top_acc = sum(1 for _, ok in top if ok) / len(top)
    return {"n": len(ordered), "kept_in_top70": len(top),
            "threshold": round(threshold, 6),
            "overall_accuracy": round(overall, 4),
            "top70_accuracy": round(top_acc, 4),
            "distinct_confidences": len({round(c, 6) for c, _ in ordered})}


def error_ratio(top70_accuracy: float | None, overall_accuracy: float | None) -> float | None:
    """(1 - top70) / (1 - overall). Below 1.0 means confidence is informative."""
    if top70_accuracy is None or overall_accuracy is None:
        return None
    top_err, all_err = 1.0 - top70_accuracy, 1.0 - overall_accuracy
    if all_err <= 0:
        return 0.0 if top_err <= 0 else None
    return round(top_err / all_err, 4)


# --------------------------------------------------------------------------- schema

def schema_valid(pred: dict, schema: dict | None) -> bool:
    """Structural validation without a dependency: required keys, types and ranges."""
    if not isinstance(pred, dict):
        return False
    if schema is None:
        schema = json.loads(Path(__file__).with_name("schema.json").read_text())
    for key in schema.get("required", []):
        if key not in pred:
            return False
    for key, spec in (schema.get("properties") or {}).items():
        if key not in pred:
            continue
        value, kind = pred[key], spec.get("type")
        if kind == "string" and not isinstance(value, str):
            return False
        if kind == "boolean" and not isinstance(value, bool):
            return False
        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return False
            if "minimum" in spec and value < spec["minimum"]:
                return False
            if "maximum" in spec and value > spec["maximum"]:
                return False
        if "enum" in spec and value not in spec["enum"]:
            return False
    return True


# --------------------------------------------------------------------------- grading

def grade(gold: list[dict], noisy: list[dict], hostile: list[dict],
          preds: dict[str, dict], schema: dict | None) -> dict[str, Any]:
    expected = [str(r["id"]) for r in gold + noisy + hostile]
    if len(expected) != len(set(expected)) or set(preds) - set(expected):
        raise ValueError("overlapping input splits or unknown prediction ids")
    clean_ids = [str(r["id"]) for r in gold]
    noisy_ids = [str(r["id"]) for r in noisy]
    labelled = {str(r["id"]): r for r in gold + noisy}

    intent_pairs: dict[str, list[tuple[Any, Any]]] = defaultdict(list)
    action_pairs: dict[str, list[tuple[Any, Any]]] = defaultdict(list)
    conf_rows: list[tuple[float, bool]] = []
    violations = 0
    scored_actions = 0
    missing = 0

    for group, ids in (("clean", clean_ids), ("noisy", noisy_ids)):
        for rid in ids:
            row = labelled[rid]
            pred = preds.get(rid)
            if pred is None:
                missing += 1
                conf_rows.append((0.0, False))
                intent_pairs[group].append((row["intent"], None))
                action_pairs[group].append((row["action"], None))
                continue
            p_intent, p_action = pred.get("intent"), pred.get("action")
            intent_pairs[group].append((row["intent"], p_intent))
            action_pairs[group].append((row["action"], p_action))
            permitted = row.get("permitted_actions") or []
            if permitted:
                scored_actions += 1
                if p_action is not None and p_action not in permitted:
                    violations += 1
            conf = pred.get("confidence")
            if schema_valid(pred, schema):
                conf_rows.append((float(conf), row["action"] == p_action))
            else:
                conf_rows.append((0.0, False))

    all_intent = intent_pairs["clean"] + intent_pairs["noisy"]
    all_action = action_pairs["clean"] + action_pairs["noisy"]

    # Schema validity is measured over EVERY input we sent, hostile pack included: a service that
    # returns nothing for binary junk has failed, whatever it scores on the clean rows.
    every_id = clean_ids + noisy_ids + [str(r["id"]) for r in hostile]
    valid = sum(1 for rid in every_id if rid in preds and schema_valid(preds[rid], schema))

    gold_violations = sum(
        1 for r in gold + noisy
        if (r.get("permitted_actions") and r["action"] not in r["permitted_actions"]))
    gold_scored = sum(1 for r in gold + noisy if r.get("permitted_actions"))

    conf = confidence_report(conf_rows)
    acc_clean = accuracy(action_pairs["clean"])
    acc_noisy = accuracy(action_pairs["noisy"]) if action_pairs["noisy"] else None

    clean_map = {str(r["id"]): r for r in gold}
    paired_ids = [str(r["id"]).removesuffix("-noisy") for r in noisy]
    matched_clean = accuracy([(clean_map[k]["action"], preds.get(k, {}).get("action")) for k in paired_ids if k in clean_map]) if paired_ids and all(k in clean_map for k in paired_ids) else None
    report: dict[str, Any] = {
        "grader_version": GRADER_VERSION,
        "counts": {"clean": len(clean_ids), "noisy": len(noisy_ids), "hostile": len(hostile),
                   "predictions": len(preds), "missing_predictions": sum(rid not in preds for rid in every_id)},
        "intent": {
            "accuracy_all": accuracy(all_intent),
            "accuracy_clean": accuracy(intent_pairs["clean"]),
            "accuracy_noisy": accuracy(intent_pairs["noisy"]) if intent_pairs["noisy"] else None,
            "macro_f1_all": macro_f1(all_intent),
            "macro_f1_clean": macro_f1(intent_pairs["clean"]),
        },
        "action": {
            "accuracy_all": accuracy(all_action),
            "accuracy_clean": acc_clean,
            "accuracy_noisy": acc_noisy,
            "macro_f1_all": macro_f1(all_action),
            "matched_clean_accuracy": matched_clean,
            "matched_noisy_gap": round(matched_clean - acc_noisy, 4) if matched_clean is not None and acc_noisy is not None else None,
            "noisy_gap": round(acc_clean - acc_noisy, 4) if acc_noisy is not None else None,
        },
        "policy": {
            "predicted_actions_scored": scored_actions,
            "violations": violations,
            "violation_rate": round(violations / scored_actions, 4) if scored_actions else None,
            # Published so the bar is honest: real agents deviate from the written procedure, so
            # a perfect predictor of the gold label does not score zero here.
            "gold_violation_rate": round(gold_violations / gold_scored, 4) if gold_scored else None,
        },
        "hostile": {
            "structural_only": True,
            "runtime_and_behavior_verified": False,
            "note": "Prediction files cannot prove absence of crashes, hangs or instruction following; run the service checks.",
        },
        "schema": {
            "inputs_including_hostile": len(every_id),
            "valid": valid,
            "valid_rate_all_inputs": valid / len(every_id) if every_id else 0.0,
        },
        "confidence": {"all": conf, "top70_error_ratio": error_ratio(conf["top70_accuracy"],
                                                                    conf["overall_accuracy"])},
    }

    schema_pct = report["schema"]["valid_rate_all_inputs"] * 100
    report["bars"] = {
        "intent_accuracy_all": _bar(report["intent"]["accuracy_all"], BARS["intent_accuracy"]),
        "action_accuracy_all": _bar(report["action"]["accuracy_all"], BARS["action_accuracy"]),
        "macro_f1_all": _bar(report["intent"]["macro_f1_all"], BARS["macro_f1"]),
        "schema_valid_pct": _bar(schema_pct, BARS["schema_valid_pct"]),
        "noisy_gap": _bar(report["action"]["noisy_gap"], BARS["noisy_gap"], lower_is_better=True),
        "top70_error_ratio": _bar(report["confidence"]["top70_error_ratio"],
                                  BARS["top70_error_ratio"], lower_is_better=True),
    }
    report["baseline"] = BASELINE
    return report


def _bar(value: float | None, bar: float, lower_is_better: bool = False) -> dict[str, Any]:
    if value is None:
        return {"value": None, "bar": bar, "pass": None}
    ok = value <= bar if lower_is_better else value >= bar
    return {"value": value, "bar": bar, "pass": bool(ok)}


# --------------------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--noisy")
    ap.add_argument("--hostile")
    ap.add_argument("--schema")
    ap.add_argument("--report")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    gold = load_jsonl(args.gold, "gold")
    noisy = load_jsonl(args.noisy, "noisy gold") if args.noisy else []
    hostile = load_jsonl(args.hostile, "hostile pack") if args.hostile else []
    preds = by_id(load_jsonl(args.pred, "predictions"))
    schema = json.loads(open(args.schema, encoding="utf-8").read()) if args.schema else None

    report = grade(gold, noisy, hostile, preds, schema)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")
    if not args.quiet:
        b = report["bars"]
        yn = lambda x: "PASS" if x else ("—" if x is None else "FAIL")  # noqa: E731
        print(f"OP-06 grader {GRADER_VERSION}")
        print(f"  {'Intent accuracy (clean+noisy)':<38}{report['intent']['accuracy_all']:>9.4f}"
              f"   >= {BARS['intent_accuracy']:<6}{yn(b['intent_accuracy_all']['pass'])}")
        print(f"  {'Action accuracy (clean+noisy)':<38}{report['action']['accuracy_all']:>9.4f}"
              f"   >= {BARS['action_accuracy']:<6}{yn(b['action_accuracy_all']['pass'])}")
        print(f"  {'Intent macro-F1':<38}{report['intent']['macro_f1_all']:>9.4f}"
              f"   >= {BARS['macro_f1']:<6}{yn(b['macro_f1_all']['pass'])}")
        gap = report["action"]["noisy_gap"]
        print(f"  {'Clean-to-noisy action gap':<38}{gap if gap is None else f'{gap:>9.4f}'}"
              f"   <= {BARS['noisy_gap']:<6}{yn(b['noisy_gap']['pass'])}")
        print(f"  {'Schema valid (incl. hostile)':<38}"
              f"{report['schema']['valid_rate_all_inputs'] * 100:>8.2f}%"
              f"   == {BARS['schema_valid_pct']:<6}{yn(b['schema_valid_pct']['pass'])}")
        pol = report["policy"]
        print(f"  {'Policy violations':<38}{str(pol['violation_rate']):>9}"
              f"   (gold itself: {pol['gold_violation_rate']})")
        print(f"  {'Confidence error ratio (top 70%)':<38}"
              f"{str(report['confidence']['top70_error_ratio']):>9}   (< 1.0 is informative)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
