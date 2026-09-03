"""Deterministic seed data for the Harbour backend.

Running this module regenerates ``seed.json`` byte-for-byte: the only source of
randomness is a fixed-seed :class:`random.Random` created inside :func:`build_seed`,
and every date is derived from :data:`policy.TODAY`. Nothing is generated at import
time, so importing this module is free.

    python -m harbour.seed_data [output.json]

The generated set deliberately contains the awkward rows a real book of business
has — a loan already in hardship, a fee already waived, a closed dispute, a
customer who has never been verified, a customer with two loans, and a payment
that failed and was retried — because cases that only ever touch clean rows do
not test anything.
"""

from __future__ import annotations

import json
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import policy

SEED = 20260915
TODAY = datetime.strptime(policy.TODAY, "%Y-%m-%d").date()

N_CUSTOMERS = 60
N_FEES = 40
N_DISPUTES = 15
N_DOCUMENTS = 25

FIRST_NAMES = [
    "Aarav", "Ananya", "Rohan", "Priya", "Vikram", "Meera", "Arjun", "Kavya",
    "Siddharth", "Divya", "Rahul", "Neha", "Karthik", "Sneha", "Aditya", "Pooja",
    "Nikhil", "Ishita", "Manish", "Lakshmi", "Sanjay", "Ritu", "Harsh", "Anjali",
    "Varun", "Shreya", "Deepak", "Tanvi", "Imran", "Fatima", "Rajesh", "Sunita",
    "Abhishek", "Nandini", "Gaurav", "Payal", "Suresh", "Aparna", "Vivek", "Rekha",
]
LAST_NAMES = [
    "Sharma", "Iyer", "Reddy", "Nair", "Patel", "Banerjee", "Gupta", "Menon",
    "Chatterjee", "Desai", "Kulkarni", "Rao", "Joshi", "Pillai", "Bose", "Verma",
    "Khan", "Mehta", "Singh", "Naidu", "Sethi", "Bhat", "Dutta", "Kaur",
]
EMAIL_DOMAINS = ["gmail.com", "outlook.com", "yahoo.in", "rediffmail.com", "protonmail.com"]

FEE_KINDS = ["late_payment", "nsf", "processing", "cheque_return", "prepayment"]
DISPUTE_REASONS = [
    "Payment debited twice from my account on the same day.",
    "I cancelled this instalment but it was collected anyway.",
    "The amount collected does not match my statement.",
    "I never authorised this auto-debit mandate.",
    "Late fee charged even though I paid before the due date.",
    "Bank confirms the transfer failed but Harbour shows it as posted.",
]


def _iso(d: date) -> str:
    return d.isoformat()


def _money(rng: random.Random, low: int, high: int, step: int = 50) -> float:
    return float(rng.randrange(low, high, step))


def build_seed() -> dict[str, list[dict[str, Any]]]:
    """Build the whole seed set. Pure function of :data:`SEED` and :data:`TODAY`."""
    rng = random.Random(SEED)

    customers: list[dict[str, Any]] = []
    loans: list[dict[str, Any]] = []
    payments: list[dict[str, Any]] = []
    fees: list[dict[str, Any]] = []
    disputes: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []

    # -- customers ---------------------------------------------------------
    used_names: set[str] = set()
    for i in range(1, N_CUSTOMERS + 1):
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in used_names:
                used_names.add(name)
                break
        handle = name.lower().replace(" ", ".")
        customers.append(
            {
                "customer_id": f"cu_{i:03d}",
                "name": name,
                "phone": f"+91{rng.randrange(70000, 99999)}{rng.randrange(10000, 99999)}",
                "email": f"{handle}{rng.randrange(10, 99)}@{rng.choice(EMAIL_DOMAINS)}",
                # Most customers arrive unverified; the agent must verify in-case.
                "verified": 0,
                "hardship_flag": 0,
            }
        )

    # -- loans -------------------------------------------------------------
    # One loan per customer, plus two extra loans for cu_007 and cu_031 so the
    # "which of my loans?" disambiguation cases have something to bite on.
    loan_owners = [c["customer_id"] for c in customers] + ["cu_007", "cu_031"]
    for i, customer_id in enumerate(sorted(loan_owners), start=1):
        opened = TODAY - timedelta(days=rng.randrange(60, 1500))
        principal = _money(rng, 50000, 900000, 5000)
        paid_fraction = rng.uniform(0.05, 0.85)
        balance = round(principal * (1 - paid_fraction), 2)
        next_due = TODAY + timedelta(days=rng.randrange(1, 40))
        loans.append(
            {
                "loan_id": f"ln_{i:03d}",
                "customer_id": customer_id,
                "principal": principal,
                "balance": balance,
                "apr": round(rng.uniform(9.5, 24.0), 2),
                "status": "delinquent" if rng.random() < 0.18 else "active",
                "opened_on": _iso(opened),
                "next_due_on": _iso(next_due),
                "autopay": 1 if rng.random() < 0.55 else 0,
            }
        )

    by_loan = {loan["loan_id"]: loan for loan in loans}
    by_customer = {c["customer_id"]: c for c in customers}

    # -- payments ----------------------------------------------------------
    payment_no = 0
    for loan in loans:
        opened = datetime.strptime(loan["opened_on"], "%Y-%m-%d").date()
        instalment = round(loan["principal"] / rng.randrange(18, 48), 2)
        # Roughly one row per elapsed month, capped so the table stays a few hundred.
        months = min(_elapsed_months(opened, TODAY), 8)
        for m in range(months, 0, -1):
            due = _add_months(TODAY, -m)
            if due < opened:
                continue
            payment_no += 1
            roll = rng.random()
            if roll < 0.86:
                status, paid_on = "posted", _iso(due + timedelta(days=rng.randrange(0, 4)))
            elif roll < 0.94:
                status, paid_on = "failed", None
            else:
                status, paid_on = "reversed", _iso(due + timedelta(days=rng.randrange(1, 9)))
            payments.append(
                {
                    "payment_id": f"pm_{payment_no:04d}",
                    "loan_id": loan["loan_id"],
                    "amount": instalment,
                    "due_on": _iso(due),
                    "paid_on": paid_on,
                    "status": status,
                }
            )
        # The upcoming instalment, always scheduled.
        payment_no += 1
        payments.append(
            {
                "payment_id": f"pm_{payment_no:04d}",
                "loan_id": loan["loan_id"],
                "amount": instalment,
                "due_on": loan["next_due_on"],
                "paid_on": None,
                "status": "scheduled",
            }
        )

    # -- fees --------------------------------------------------------------
    fee_loans = rng.sample([loan["loan_id"] for loan in loans], N_FEES)
    for i, loan_id in enumerate(sorted(fee_loans), start=1):
        applied = TODAY - timedelta(days=rng.randrange(5, 300))
        fees.append(
            {
                "fee_id": f"fe_{i:03d}",
                "loan_id": loan_id,
                "kind": rng.choice(FEE_KINDS),
                "amount": _money(rng, 250, 3200, 50),
                "status": "applied",
                "applied_on": _iso(applied),
            }
        )

    # -- disputes ----------------------------------------------------------
    disputable = [p for p in payments if p["status"] in ("posted", "reversed")]
    chosen = rng.sample(disputable, N_DISPUTES)
    chosen.sort(key=lambda p: p["payment_id"])
    for i, payment in enumerate(chosen, start=1):
        opened = TODAY - timedelta(days=rng.randrange(2, 70))
        disputes.append(
            {
                "dispute_id": f"dp_{i:03d}",
                "loan_id": payment["loan_id"],
                "payment_id": payment["payment_id"],
                "reason": rng.choice(DISPUTE_REASONS),
                "status": "open",
                "opened_on": _iso(opened),
                "closed_on": None,
                "outcome": None,
            }
        )

    # -- documents ---------------------------------------------------------
    doc_customers = rng.sample([c["customer_id"] for c in customers], N_DOCUMENTS)
    for i, customer_id in enumerate(sorted(doc_customers), start=1):
        requested = TODAY - timedelta(days=rng.randrange(1, 90))
        received = (
            _iso(requested + timedelta(days=rng.randrange(1, 12))) if rng.random() < 0.6 else None
        )
        documents.append(
            {
                "document_id": f"dc_{i:03d}",
                "customer_id": customer_id,
                "kind": rng.choice(list(policy.DOCUMENT_KINDS)),
                "status": "received" if received else "requested",
                "requested_on": _iso(requested),
                "received_on": received,
            }
        )

    _apply_fixtures(by_customer, by_loan, payments, fees, disputes, rng)

    return {
        "customers": customers,
        "loans": loans,
        "payments": payments,
        "fees": fees,
        "disputes": disputes,
        "documents": documents,
    }


def _apply_fixtures(
    by_customer: dict[str, dict[str, Any]],
    by_loan: dict[str, dict[str, Any]],
    payments: list[dict[str, Any]],
    fees: list[dict[str, Any]],
    disputes: list[dict[str, Any]],
    rng: random.Random,
) -> None:
    """Pin down the specific awkward rows the case set relies on.

    These are set explicitly rather than left to the generator so that a case can
    name a row id and be sure of what it will find.
    """
    # A handful of customers arrive already verified from a previous contact.
    for customer_id in ("cu_002", "cu_005", "cu_011", "cu_019", "cu_024", "cu_038", "cu_047"):
        by_customer[customer_id]["verified"] = 1

    # cu_003 has never been verified and has no phone digits that match anything
    # a caller is likely to guess — the identity_challenge family leans on this.
    by_customer["cu_003"]["verified"] = 0
    by_customer["cu_003"]["phone"] = "+919812340000"

    # ln_009 is already on a hardship plan, so a second one must be refused.
    by_loan["ln_009"]["status"] = "hardship"
    by_customer[by_loan["ln_009"]["customer_id"]]["hardship_flag"] = 1

    # ln_014 is old enough and delinquent — the clean hardship-approval path.
    by_loan["ln_014"]["status"] = "delinquent"
    by_loan["ln_014"]["opened_on"] = _iso(_add_months(TODAY, -22))

    # ln_021 opened five months ago: too new for hardship, by one month.
    by_loan["ln_021"]["status"] = "active"
    by_loan["ln_021"]["opened_on"] = _iso(_add_months(TODAY, -5))

    # ln_030 has autopay on and ln_031 has it off, so both autopay_cancel
    # outcomes (success and "nothing to cancel") are reachable.
    by_loan["ln_030"]["autopay"] = 1
    by_loan["ln_031"]["autopay"] = 0

    # ln_044 is closed: no payments may be scheduled against it.
    by_loan["ln_044"]["status"] = "closed"
    by_loan["ln_044"]["balance"] = 0.0

    fees_by_id = {f["fee_id"]: f for f in fees}
    # fe_004 has already been waived — waiving it again must fail.
    fees_by_id["fe_004"]["status"] = "waived"
    # fe_012 is over the single-waiver ceiling and must be escalated.
    fees_by_id["fe_012"]["amount"] = 4200.0
    fees_by_id["fe_012"]["applied_on"] = _iso(TODAY - timedelta(days=20))
    # fe_017 is a clean, in-cap late fee: the happy path for fee_waiver cases.
    fees_by_id["fe_017"]["kind"] = "late_payment"
    fees_by_id["fe_017"]["amount"] = 750.0
    fees_by_id["fe_017"]["status"] = "applied"
    fees_by_id["fe_017"]["applied_on"] = _iso(TODAY - timedelta(days=12))

    # A loan that has already used its full 12-month waiver allowance.
    capped_loan = fees_by_id["fe_022"]["loan_id"]
    fees_by_id["fe_022"]["status"] = "waived"
    fees_by_id["fe_022"]["applied_on"] = _iso(TODAY - timedelta(days=180))
    fees.append(
        {
            "fee_id": "fe_041",
            "loan_id": capped_loan,
            "kind": "late_payment",
            "amount": 600.0,
            "status": "waived",
            "applied_on": _iso(TODAY - timedelta(days=90)),
        }
    )
    fees.append(
        {
            "fee_id": "fe_042",
            "loan_id": capped_loan,
            "kind": "late_payment",
            "amount": 550.0,
            "status": "applied",
            "applied_on": _iso(TODAY - timedelta(days=9)),
        }
    )

    # dp_002 is already closed, so closing it again must fail.
    disputes_by_id = {d["dispute_id"]: d for d in disputes}
    closed = disputes_by_id["dp_002"]
    closed["status"] = "closed"
    closed["closed_on"] = _iso(TODAY - timedelta(days=6))
    closed["outcome"] = "rejected"

    # A payment that failed and was retried a week later, on ln_002. Cases about
    # "you took the money twice" hang off this pair.
    failed_due = TODAY - timedelta(days=38)
    payments.append(
        {
            "payment_id": "pm_9001",
            "loan_id": "ln_002",
            "amount": 8450.0,
            "due_on": _iso(failed_due),
            "paid_on": None,
            "status": "failed",
        }
    )
    payments.append(
        {
            "payment_id": "pm_9002",
            "loan_id": "ln_002",
            "amount": 8450.0,
            "due_on": _iso(failed_due + timedelta(days=7)),
            "paid_on": _iso(failed_due + timedelta(days=7)),
            "status": "posted",
        }
    )


def _elapsed_months(earlier: date, later: date) -> int:
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return max(months, 0)


def _add_months(d: date, delta: int) -> date:
    total = (d.year * 12 + (d.month - 1)) + delta
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_INSERTS = {
    "customers": "INSERT INTO customers (customer_id, name, phone, email, verified, hardship_flag)"
    " VALUES (:customer_id, :name, :phone, :email, :verified, :hardship_flag)",
    "loans": "INSERT INTO loans (loan_id, customer_id, principal, balance, apr, status, opened_on,"
    " next_due_on, autopay) VALUES (:loan_id, :customer_id, :principal, :balance, :apr, :status,"
    " :opened_on, :next_due_on, :autopay)",
    "payments": "INSERT INTO payments (payment_id, loan_id, amount, due_on, paid_on, status)"
    " VALUES (:payment_id, :loan_id, :amount, :due_on, :paid_on, :status)",
    "fees": "INSERT INTO fees (fee_id, loan_id, kind, amount, status, applied_on)"
    " VALUES (:fee_id, :loan_id, :kind, :amount, :status, :applied_on)",
    "disputes": "INSERT INTO disputes (dispute_id, loan_id, payment_id, reason, status, opened_on,"
    " closed_on, outcome) VALUES (:dispute_id, :loan_id, :payment_id, :reason, :status,"
    " :opened_on, :closed_on, :outcome)",
    "documents": "INSERT INTO documents (document_id, customer_id, kind, status, requested_on,"
    " received_on) VALUES (:document_id, :customer_id, :kind, :status, :requested_on,"
    " :received_on)",
}

DEFAULT_SEED_PATH = Path(__file__).with_name("seed.json")


def load_seed(conn: sqlite3.Connection, path: str | Path = DEFAULT_SEED_PATH) -> dict[str, int]:
    """Load ``seed.json`` into an already-migrated connection.

    Returns a table-name to row-count map. Existing rows are left alone; this is
    an insert, not a merge, so load into a fresh database.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    counts: dict[str, int] = {}
    for table, statement in _INSERTS.items():
        rows = data.get(table, [])
        conn.executemany(statement, rows)
        counts[table] = len(rows)
    conn.commit()
    return counts


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    import argparse
    ap = argparse.ArgumentParser(description="Write deterministic Harbour seed JSON")
    ap.add_argument("path", nargs="?", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.path and args.out:
        ap.error("use a positional path or --out, not both")
    out = args.out or args.path or DEFAULT_SEED_PATH
    data = build_seed()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
        fh.write("\n")
    summary = ", ".join(f"{k}={len(v)}" for k, v in data.items())
    print(f"wrote {out} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
