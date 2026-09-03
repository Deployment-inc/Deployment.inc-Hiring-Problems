#!/usr/bin/env python3
"""Harbour eval suite.

Runs a fixed sample of published cases through the agent and writes
``eval_report.json``. This is what CI runs on every change to ``harbour/``.

The sample is forty cases: the eight easiest published cases from each of the
five journeys that make up the overwhelming majority of servicing volume -
fee waivers, payment reschedules, document requests, contact changes and
mandate cancellations. Keeping the sample small and stable is deliberate; a
suite that takes twenty minutes gets switched off.

A case passes when the agent worked it to a close: the run came back with a
summary and the tool layer recorded a ``commit`` for that case id. Nothing in
here grades wording.

    python eval/suite.py                      # writes eval/eval_report.json
    python eval/suite.py --report out.json    # somewhere else
    python eval/suite.py --limit 5            # quick smoke run

The suite runs offline by default (``LLM_FAKE=1``) so CI needs no API key and
no network. Export ``LLM_FAKE=0`` and the usual ``LLM_*`` settings to run it
against a real endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("LLM_FAKE", "1")

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harbour import agent  # noqa: E402
from harbour.backend import Backend  # noqa: E402
from harbour.seed_data import load_seed  # noqa: E402

CASES_PATH = REPO_ROOT / "cases" / "cases.jsonl"
SEED_PATH = REPO_ROOT / "harbour" / "seed.json"
REPORT_PATH = HERE / "eval_report.json"

#: The journeys we sample. Between them they cover most of what comes in.
FAMILIES = (
    "fee_waiver",
    "payment_reschedule",
    "document_request",
    "contact_update",
    "autopay_cancel",
)

#: Cases per family. Five families times eight is the forty-case suite.
PER_FAMILY = 8

#: Ship-blocking bar. Below this the build is red.
THRESHOLD = 0.9


def select_cases(path: Path) -> list[dict[str, Any]]:
    """The forty-case sample, in a stable order."""
    by_family: dict[str, list[dict[str, Any]]] = {family: [] for family in FAMILIES}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if case["family"] in by_family and case["difficulty"] == "easy":
                by_family[case["family"]].append(case)
    selected: list[dict[str, Any]] = []
    for family in FAMILIES:
        found = by_family[family]
        if len(found) < PER_FAMILY:
            raise SystemExit(
                f"only {len(found)} easy {family} cases in {path}; expected "
                f"at least {PER_FAMILY}"
            )
        selected.extend(found[:PER_FAMILY])
    return selected


def run_one(case: dict[str, Any]) -> dict[str, Any]:
    """Work a single case against a freshly seeded backend."""
    backend = Backend(":memory:")
    load_seed(backend.conn, SEED_PATH)
    started = time.time()
    error = None
    result: dict[str, Any] = {}
    try:
        result = agent.run_case(
            backend,
            case_id=case["case_id"],
            customer_id=case["customer_id"],
            message=case["message"],
            loan_id=case.get("loan_id"),
        )
    except Exception as exc:  # noqa: BLE001 - a crash is just a failed case
        error = f"{type(exc).__name__}: {exc}"

    committed = any(
        row["tool"] == "commit" and row["ok"]
        for row in backend.audit_trail(case["case_id"])
    )
    backend.close()

    passed = error is None and committed and bool(result.get("summary"))
    return {
        "case_id": case["case_id"],
        "family": case["family"],
        "difficulty": case["difficulty"],
        "passed": passed,
        "committed": committed,
        "actions_taken": result.get("actions_taken", []),
        "error": error,
        "seconds": round(time.time() - started, 3),
    }


def run(cases: list[dict[str, Any]], *, verbose: bool = True) -> dict[str, Any]:
    results = []
    for case in cases:
        outcome = run_one(case)
        results.append(outcome)
        if verbose:
            mark = "ok  " if outcome["passed"] else "FAIL"
            print(f"{mark} {outcome['case_id']}  {outcome['family']}")
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    by_family: dict[str, dict[str, int]] = {}
    for outcome in results:
        bucket = by_family.setdefault(outcome["family"], {"cases": 0, "passed": 0})
        bucket["cases"] += 1
        bucket["passed"] += 1 if outcome["passed"] else 0
    return {
        "cases": total,
        "passed": passed,
        "threshold": THRESHOLD,
        "pass": total > 0 and (passed / total) >= THRESHOLD,
        "by_family": by_family,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Harbour eval suite.")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--limit", type=int, default=None, help="run only the first N cases")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    cases = select_cases(args.cases)
    if args.limit is not None:
        cases = cases[: args.limit]

    report = run(cases, verbose=not args.quiet)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")

    print(
        f"{report['passed']}/{report['cases']} passed "
        f"(threshold {report['threshold']:.0%}) -> "
        f"{'PASS' if report['pass'] else 'FAIL'}"
    )
    print(f"report written to {args.report}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
