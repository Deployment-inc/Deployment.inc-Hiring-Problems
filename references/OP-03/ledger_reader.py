#!/usr/bin/env python3
"""OP-03 gateway ledger reader. The only cost measurement that counts.

    python ledger_reader.py --ledger results/ledger.jsonl --runs results/held_out_runs.jsonl

Cost comes from the ledger, never from what a system reports about itself. A number the thing
under measurement produces about its own spend is not a measurement, and the whole problem is
about spending less — so the one number that decides it has to come from outside.

**The denominator is the part people get wrong.** Cost per resolved case divides ledger spend by
cases *resolved*, not cases *attempted*. Deferred and failed cases keep their spend in the
numerator and contribute nothing to the denominator, so an agent that defers everything hard
looks expensive rather than cheap. Dividing by attempts would make refusing to work the winning
strategy.

Ledger lines, one per case (or per call, summed by case):

    {"case_id": "...", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model": "..."}

Run lines, one per case:

    {"case_id": "...", "goal_state_match": true, "deferred": false, "latency_s": 0.0}

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def load_jsonl(path: Path, what: str) -> list[dict]:
    if not path.is_file():
        sys.exit(f"no such {what}: {path}")
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError("record must be an object")
            rows.append(obj)
        except ValueError as exc:
            sys.exit(f"{path}:{n}: {what} is not valid JSON ({exc})")
    return rows


def by_case(ledger: list[dict]) -> dict[str, dict]:
    """Sum the ledger per case. A case may appear once or once per model call."""
    out: dict[str, dict] = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    for row in ledger:
        cid = str(row.get("case_id") or row.get("case") or "")
        if not cid:
            raise ValueError("every ledger row requires case_id")
        for key in ("input_tokens", "output_tokens", "cost_usd"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{cid}: missing, negative or nonfinite {key}")
            if key.endswith("tokens") and type(value) is not int:
                raise ValueError(f"{cid}: token counts must be integers")
        acc = out[cid]
        acc["input_tokens"] += int(row.get("input_tokens") or 0)
        acc["output_tokens"] += int(row.get("output_tokens") or 0)
        acc["cost_usd"] += float(row.get("cost_usd") or 0.0)
    return dict(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--cases", type=Path, help="trusted case definitions; required for elective deferral scoring")
    args = ap.parse_args(argv)

    spend = by_case(load_jsonl(args.ledger, "ledger"))
    runs = load_jsonl(args.runs, "runs")

    ids = [r.get("case_id") for r in runs]
    if not runs or any(not isinstance(k, str) or not k for k in ids) or len(ids) != len(set(ids)):
        raise ValueError("run records require unique nonempty case_id values")
    for run in runs:
        if type(run.get("goal_state_match")) is not bool or type(run.get("deferred")) is not bool:
            raise ValueError("goal_state_match and deferred must be booleans")
        latency = run.get("latency_s")
        if isinstance(latency, bool) or not isinstance(latency, (int, float)) or not math.isfinite(latency) or latency < 0:
            raise ValueError("latency_s must be a finite nonnegative measurement")
    if set(spend) != set(ids):
        raise ValueError("ledger and run case IDs must match exactly; include a zero-cost row for cases making no model calls")
    resolved = [r for r in runs if r["goal_state_match"] and not r["deferred"]]
    deferred = [r for r in runs if r["deferred"]]
    total_cost = sum(v["cost_usd"] for v in spend.values())
    total_tokens = sum(v["input_tokens"] + v["output_tokens"] for v in spend.values())
    lat = sorted(float(r["latency_s"]) for r in runs)
    unledgered = []
    mandatory = eligible = elective = None
    if args.cases:
        case_rows = load_jsonl(args.cases, "case definitions")
        definitions = {row["case_id"]: row for row in case_rows}
        if len(definitions) != len(case_rows) or not set(ids) <= set(definitions):
            raise ValueError("case definitions have duplicate IDs or do not cover every run")
        required = {cid for cid in ids if "escalate" in definitions[cid]["goal_state"].get("audit_must_include", [])}
        mandatory = len(required)
        eligible = len(ids) - mandatory
        elective = sum(run["deferred"] and run["case_id"] not in required for run in runs)

    report = {
        "evidence_status": "artifact_consistency_only",
        "note_on_trust": "Only a reviewer-controlled gateway and backend can attest these input files; candidate files alone do not prove performance.",
        "cases": len(runs),
        "resolved": len(resolved),
        "deferred": len(deferred),
        "policy_escalation_required_cases": mandatory,
        "automatable_cases": eligible,
        "elective_deferrals": elective,
        "elective_deferral_rate": round(elective / eligible, 4) if eligible else None,
        "success_rate": round(sum(r["goal_state_match"] for r in runs) / len(runs), 4),
        "resolved_rate": round(len(resolved) / len(runs), 4),
        "deferral_rate": round(len(deferred) / len(runs), 4) if runs else None,
        "total_cost_usd": round(total_cost, 6),
        "total_tokens": total_tokens,
        # Undefined rather than zero: spending money and resolving nothing is the worst
        # outcome available, and reporting 0.0 would make it look like the best.
        # None, not 0.0, when the ledger carries no prices: an unpriced ledger and a free run
        # look identical as a number, and only one of them is true.
        "cost_per_resolved_case": (round(total_cost / len(resolved), 6)
                                   if resolved else None),
        "tokens_per_resolved_case": round(total_tokens / len(resolved), 1) if resolved else None,
        "latency_p50_s": round(statistics.median(lat), 3) if lat else None,
        "latency_p95_s": round(lat[max(0, int(0.95 * (len(lat) - 1)))], 3) if lat else None,
        "cases_missing_from_ledger": len(unledgered),
    }
    if unledgered:
        report["missing_sample"] = unledgered[:10]
        report["warning"] = ("Some cases have no ledger entry. Their spend is invisible, so the "
                             "cost per resolved case below is an underestimate.")
    if not resolved:
        report["note"] = "Nothing was resolved, so cost per resolved case is undefined, not zero."
    elif total_cost < 0:
        report["note"] = ("The ledger carries token counts but no cost_usd, so cost per resolved "
                          "case is undefined rather than zero. Compare tokens_per_resolved_case, "
                          "or price the ledger first.")

    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
