"""Harbour backend: SQLite schema, the 14 servicing tools, and the audit log.

The tool layer is the only thing that writes to ``audit_log``. The agent cannot
suppress an entry, cannot edit one, and cannot append one of its own — every call
lands there with its arguments and its result, whether it succeeded or not. That
is deliberate: the audit log is the record we replay when something goes wrong.

Policy limits are imported from :mod:`policy`; nothing in this module hard-codes a
number that a compliance officer might want to change.
"""

from __future__ import annotations

import functools
import inspect
import json
import sqlite3
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional, TypeVar

from . import policy

__all__ = ["Backend", "PolicyError", "NotFound", "SCHEMA"]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PolicyError(Exception):
    """Raised when a request is well-formed but the servicing policy forbids it."""


class NotFound(Exception):
    """Raised when a referenced row does not exist."""


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT PRIMARY KEY,
    name          TEXT,
    phone         TEXT,
    email         TEXT,
    verified      INTEGER DEFAULT 0,
    hardship_flag INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS loans (
    loan_id      TEXT PRIMARY KEY,
    customer_id  TEXT,
    principal    REAL,
    balance      REAL,
    apr          REAL,
    status       TEXT,
    opened_on    TEXT,
    next_due_on  TEXT,
    autopay      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    loan_id    TEXT,
    amount     REAL,
    due_on     TEXT,
    paid_on    TEXT,
    status     TEXT
);

CREATE TABLE IF NOT EXISTS disputes (
    dispute_id TEXT PRIMARY KEY,
    loan_id    TEXT,
    payment_id TEXT,
    reason     TEXT,
    status     TEXT,
    opened_on  TEXT,
    closed_on  TEXT,
    outcome    TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    document_id  TEXT PRIMARY KEY,
    customer_id  TEXT,
    kind         TEXT,
    status       TEXT,
    requested_on TEXT,
    received_on  TEXT
);

CREATE TABLE IF NOT EXISTS fees (
    fee_id     TEXT PRIMARY KEY,
    loan_id    TEXT,
    kind       TEXT,
    amount     REAL,
    status     TEXT,
    applied_on TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT,
    ts_ms       INTEGER,
    actor       TEXT,
    tool        TEXT,
    args_json   TEXT,
    result_json TEXT,
    ok          INTEGER,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS ix_loans_customer   ON loans(customer_id);
CREATE INDEX IF NOT EXISTS ix_payments_loan    ON payments(loan_id);
CREATE INDEX IF NOT EXISTS ix_fees_loan        ON fees(loan_id);
CREATE INDEX IF NOT EXISTS ix_disputes_loan    ON disputes(loan_id);
CREATE INDEX IF NOT EXISTS ix_documents_cust   ON documents(customer_id);
CREATE INDEX IF NOT EXISTS ix_audit_case       ON audit_log(case_id, seq);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

F = TypeVar("F", bound=Callable[..., Any])


def _parse_date(value: str, field: str = "date") -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc


def _months_between(earlier: date, later: date) -> int:
    """Whole months from ``earlier`` to ``later``. Negative if the order is reversed."""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return months


def _looks_like_email(value: str) -> bool:
    if not isinstance(value, str) or value.count("@") != 1:
        return False
    local, _, domain = value.partition("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


def _looks_like_phone(value: str) -> bool:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return 10 <= len(digits) <= 13


def _jsonable(value: Any) -> Any:
    """Best-effort conversion so the audit log never fails on an odd argument."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def audited(fn: F) -> F:
    """Wrap a tool so that every call is recorded in ``audit_log``.

    The record is written after the call returns or raises, and the write is
    committed independently of the tool's own transaction, so a failed tool still
    leaves a trace. Tools must not call one another through this wrapper.
    """
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(self: "Backend", *args: Any, **kwargs: Any) -> Any:
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        call_args = {k: _jsonable(v) for k, v in bound.arguments.items() if k not in ("self", "case_id")}
        case_id = bound.arguments.get("case_id")
        started = time.time()
        try:
            result = fn(*bound.args, **bound.kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised below
            self._write_audit(
                case_id=case_id,
                tool=fn.__name__,
                args=call_args,
                result=None,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                ts_ms=int(started * 1000),
            )
            raise
        self._write_audit(
            case_id=case_id,
            tool=fn.__name__,
            args=call_args,
            result=result,
            ok=True,
            error=None,
            ts_ms=int(started * 1000),
        )
        return result

    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class Backend:
    """The servicing system of record.

    Parameters
    ----------
    db_path:
        SQLite path. Defaults to an in-memory database, which is what the tests
        and the case runner use.
    today:
        ISO date the environment treats as "now". Defaults to ``policy.TODAY``.
    actor:
        Recorded against every audit row. The service sets this to the agent's id.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        today: str = policy.TODAY,
        actor: str = "agent",
    ) -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.today: date = _parse_date(today, "today")
        self.actor = actor
        self._committed_cases: set[str] = set()

    # -- infrastructure ----------------------------------------------------

    def close(self) -> None:
        self.conn.close()

    def _write_audit(
        self,
        *,
        case_id: Optional[str],
        tool: str,
        args: dict[str, Any],
        result: Any,
        ok: bool,
        error: Optional[str],
        ts_ms: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO audit_log (case_id, ts_ms, actor, tool, args_json, result_json, ok, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id,
                ts_ms,
                self.actor,
                tool,
                json.dumps(args, sort_keys=True, default=str),
                json.dumps(_jsonable(result), default=str),
                1 if ok else 0,
                error,
            ),
        )
        self.conn.commit()

    def audit_trail(self, case_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Read the audit log, oldest first. Diagnostics only — never a tool."""
        if case_id is None:
            rows = self.conn.execute("SELECT * FROM audit_log ORDER BY seq").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM audit_log WHERE case_id = ? ORDER BY seq", (case_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def _next_id(self, prefix: str, table: str, column: str) -> str:
        n = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        while True:
            candidate = f"{prefix}_{n + 1:04d}"
            hit = self.conn.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (candidate,)).fetchone()
            if hit is None:
                return candidate
            n += 1

    # -- row access --------------------------------------------------------

    def _customer(self, customer_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"no such customer: {customer_id}")
        return row

    def _loan(self, loan_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM loans WHERE loan_id = ?", (loan_id,)).fetchone()
        if row is None:
            raise NotFound(f"no such loan: {loan_id}")
        return row

    def _fee(self, fee_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM fees WHERE fee_id = ?", (fee_id,)).fetchone()
        if row is None:
            raise NotFound(f"no such fee: {fee_id}")
        return row

    def _payment(self, payment_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"no such payment: {payment_id}")
        return row

    def _dispute(self, dispute_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM disputes WHERE dispute_id = ?", (dispute_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"no such dispute: {dispute_id}")
        return row

    # -- policy gate -------------------------------------------------------

    def _require_verified(self, customer_id: str) -> None:
        """Refuse the call unless the customer has passed identity verification.

        Every tool that moves money, alters a payment obligation or forgives a
        charge must call this before it touches a row. See ``policy.md``, section
        "Identity before money".
        """
        customer = self._customer(customer_id)
        if not customer["verified"]:
            raise PolicyError(
                f"identity not verified for {customer_id}; "
                f"verify_identity must succeed before any money movement"
            )

    # ------------------------------------------------------------------
    # Read tools
    # ------------------------------------------------------------------

    @audited
    def lookup_loan(self, case_id: str, loan_id: str) -> dict:
        """Return the loan row plus the owning customer's name, contact and verification state.

        The email is here because ``send_statement`` will only send to the address already on
        the record, so an agent that cannot read that address cannot use the tool. The phone
        number is deliberately NOT returned: ``verify_identity`` checks its last four digits,
        and an agent that could read them would be able to verify the customer to itself.
        """
        loan = self._loan(loan_id)
        customer = self._customer(loan["customer_id"])
        out = dict(loan)
        out["customer_name"] = customer["name"]
        out["customer_email"] = customer["email"]
        out["customer_verified"] = bool(customer["verified"])
        return out

    @audited
    def payment_history(self, case_id: str, loan_id: str, limit: int = 12) -> list[dict]:
        """Return the most recent payments on a loan, newest first."""
        self._loan(loan_id)
        if limit <= 0:
            raise PolicyError("limit must be positive")
        rows = self.conn.execute(
            "SELECT * FROM payments WHERE loan_id = ? ORDER BY due_on DESC, payment_id DESC LIMIT ?",
            (loan_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @audited
    def verify_identity(self, case_id: str, customer_id: str, last4_phone: str) -> bool:
        """Check the last four digits of the registered mobile and set the verified flag.

        Returns ``False`` on a mismatch without changing anything; the caller must
        not retry indefinitely (see ``policy.md``, "Failed verification").
        """
        customer = self._customer(customer_id)
        supplied = "".join(ch for ch in str(last4_phone) if ch.isdigit())
        if len(supplied) != 4:
            raise PolicyError("last4_phone must be exactly four digits")
        on_file = "".join(ch for ch in str(customer["phone"] or "") if ch.isdigit())
        if not on_file.endswith(supplied):
            return False
        self.conn.execute(
            "UPDATE customers SET verified = 1 WHERE customer_id = ?", (customer_id,)
        )
        self.conn.commit()
        return True

    # ------------------------------------------------------------------
    # Money movement
    # ------------------------------------------------------------------

    @audited
    def schedule_payment(self, case_id: str, loan_id: str, amount: float, due_on: str) -> str:
        """Schedule a one-off payment against a loan. Returns the new payment id."""
        loan = self._loan(loan_id)
        self._require_verified(loan["customer_id"])

        if loan["status"] == "closed":
            raise PolicyError(f"loan {loan_id} is closed; no further payments may be scheduled")

        try:
            amount = float(amount)
        except (TypeError, ValueError) as exc:
            raise PolicyError(f"amount must be numeric, got {amount!r}") from exc
        if amount < policy.PAYMENT_MIN_AMOUNT_INR:
            raise PolicyError(
                f"amount {amount:.2f} is below the minimum of "
                f"{policy.PAYMENT_MIN_AMOUNT_INR:.2f}"
            )
        if amount > policy.PAYMENT_MAX_AMOUNT_INR:
            raise PolicyError(
                f"amount {amount:.2f} exceeds the single-payment ceiling of "
                f"{policy.PAYMENT_MAX_AMOUNT_INR:.2f}; escalate for approval"
            )

        when = _parse_date(due_on, "due_on")
        earliest = self.today + timedelta(days=policy.PAYMENT_MIN_DAYS_AHEAD)
        latest = self.today + timedelta(days=policy.PAYMENT_MAX_DAYS_AHEAD)
        if when < earliest:
            raise PolicyError(f"cannot schedule a payment in the past (due_on={due_on})")
        if when > latest:
            raise PolicyError(
                f"due_on={due_on} is more than {policy.PAYMENT_MAX_DAYS_AHEAD} days ahead"
            )

        payment_id = self._next_id("pm", "payments", "payment_id")
        self.conn.execute(
            "INSERT INTO payments (payment_id, loan_id, amount, due_on, paid_on, status)"
            " VALUES (?, ?, ?, ?, NULL, 'scheduled')",
            (payment_id, loan_id, amount, when.isoformat()),
        )
        self.conn.commit()
        return payment_id

    @audited
    def waive_fee(self, case_id: str, fee_id: str) -> bool:
        """Waive a fee that has been applied to a loan, within the waiver cap."""
        fee = self._fee(fee_id)
        loan = self._loan(fee["loan_id"])
        self._require_verified(loan["customer_id"])

        if fee["status"] == "waived":
            raise PolicyError(f"fee {fee_id} has already been waived")
        if fee["status"] != "applied":
            raise PolicyError(f"fee {fee_id} is in status {fee['status']!r} and cannot be waived")
        if float(fee["amount"]) > policy.FEE_WAIVER_MAX_AMOUNT_INR:
            raise PolicyError(
                f"fee {fee_id} is {float(fee['amount']):.2f}, above the "
                f"{policy.FEE_WAIVER_MAX_AMOUNT_INR:.2f} single-waiver limit; escalate for approval"
            )

        window_start = (self.today - timedelta(days=policy.FEE_WAIVER_WINDOW_DAYS)).isoformat()
        waived_recently = self.conn.execute(
            "SELECT COUNT(*) FROM fees WHERE loan_id = ? AND status = 'waived' AND applied_on >= ?",
            (fee["loan_id"], window_start),
        ).fetchone()[0]
        if waived_recently >= policy.FEE_WAIVER_MAX_PER_LOAN_12M:
            raise PolicyError(
                f"loan {fee['loan_id']} has already had {waived_recently} fees waived in the last "
                f"{policy.FEE_WAIVER_WINDOW_DAYS} days (cap is "
                f"{policy.FEE_WAIVER_MAX_PER_LOAN_12M}); escalate for approval"
            )

        self.conn.execute("UPDATE fees SET status = 'waived' WHERE fee_id = ?", (fee_id,))
        self.conn.commit()
        return True

    @audited
    def apply_hardship_plan(self, case_id: str, loan_id: str, months: int) -> bool:
        """Place a loan on a hardship plan for a number of months."""
        loan = self._loan(loan_id)
        self._require_verified(loan["customer_id"])
        customer = self._customer(loan["customer_id"])

        try:
            months = int(months)
        except (TypeError, ValueError) as exc:
            raise PolicyError(f"months must be an integer, got {months!r}") from exc
        if months < policy.HARDSHIP_MIN_TERM_MONTHS:
            raise PolicyError(f"hardship term must be at least {policy.HARDSHIP_MIN_TERM_MONTHS} month")
        if months > policy.HARDSHIP_MAX_TERM_MONTHS:
            raise PolicyError(
                f"hardship term of {months} months exceeds the "
                f"{policy.HARDSHIP_MAX_TERM_MONTHS}-month limit; escalate for approval"
            )

        if loan["status"] not in policy.HARDSHIP_ELIGIBLE_LOAN_STATUSES:
            raise PolicyError(
                f"loan {loan_id} is {loan['status']!r}; only "
                f"{', '.join(policy.HARDSHIP_ELIGIBLE_LOAN_STATUSES)} loans are eligible"
            )
        if customer["hardship_flag"]:
            raise PolicyError(
                f"customer {customer['customer_id']} is already on a hardship plan; "
                f"a second concurrent plan must be approved by a human"
            )

        on_book = _months_between(_parse_date(loan["opened_on"], "opened_on"), self.today)
        if on_book < policy.HARDSHIP_MIN_MONTHS_ON_BOOK:
            raise PolicyError(
                f"loan {loan_id} has been on the book {on_book} months; "
                f"{policy.HARDSHIP_MIN_MONTHS_ON_BOOK} are required for hardship"
            )

        self.conn.execute("UPDATE loans SET status = 'hardship' WHERE loan_id = ?", (loan_id,))
        self.conn.execute(
            "UPDATE customers SET hardship_flag = 1 WHERE customer_id = ?", (loan["customer_id"],)
        )
        self.conn.commit()
        return True

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------

    @audited
    def raise_dispute(self, case_id: str, loan_id: str, payment_id: str, reason: str) -> str:
        """Open a dispute against a payment. Returns the new dispute id."""
        self._loan(loan_id)
        payment = self._payment(payment_id)
        if payment["loan_id"] != loan_id:
            raise PolicyError(f"payment {payment_id} does not belong to loan {loan_id}")
        if not isinstance(reason, str) or not reason.strip():
            raise PolicyError("a dispute reason is required")

        due = _parse_date(payment["due_on"], "due_on")
        age_days = (self.today - due).days
        if age_days > policy.DISPUTE_RAISE_WINDOW_DAYS:
            raise PolicyError(
                f"payment {payment_id} fell due {age_days} days ago, beyond the "
                f"{policy.DISPUTE_RAISE_WINDOW_DAYS}-day dispute window"
            )

        existing = self.conn.execute(
            "SELECT dispute_id FROM disputes WHERE payment_id = ? AND status = 'open'",
            (payment_id,),
        ).fetchone()
        if existing is not None:
            raise PolicyError(
                f"payment {payment_id} already has an open dispute ({existing['dispute_id']})"
            )

        dispute_id = self._next_id("dp", "disputes", "dispute_id")
        self.conn.execute(
            "INSERT INTO disputes (dispute_id, loan_id, payment_id, reason, status, opened_on,"
            " closed_on, outcome) VALUES (?, ?, ?, ?, 'open', ?, NULL, NULL)",
            (dispute_id, loan_id, payment_id, reason.strip(), self.today.isoformat()),
        )
        self.conn.commit()
        return dispute_id

    @audited
    def close_dispute(self, case_id: str, dispute_id: str, outcome: str) -> bool:
        """Close an open dispute with an outcome of ``upheld`` or ``rejected``."""
        dispute = self._dispute(dispute_id)
        if outcome not in policy.DISPUTE_OUTCOMES:
            raise PolicyError(
                f"outcome must be one of {', '.join(policy.DISPUTE_OUTCOMES)}, got {outcome!r}"
            )
        if dispute["status"] != "open":
            raise PolicyError(
                f"dispute {dispute_id} is {dispute['status']!r}, not open; it cannot be closed again"
            )
        self.conn.execute(
            "UPDATE disputes SET status = 'closed', closed_on = ?, outcome = ? WHERE dispute_id = ?",
            (self.today.isoformat(), outcome, dispute_id),
        )
        self.conn.commit()
        return True

    # ------------------------------------------------------------------
    # Correspondence and records
    # ------------------------------------------------------------------

    @audited
    def request_document(self, case_id: str, customer_id: str, kind: str) -> str:
        """Ask a customer for a supporting document. Returns the new document id."""
        self._customer(customer_id)
        if kind not in policy.DOCUMENT_KINDS:
            raise PolicyError(
                f"{kind!r} is not a document kind we may request; "
                f"allowed: {', '.join(policy.DOCUMENT_KINDS)}"
            )
        document_id = self._next_id("dc", "documents", "document_id")
        self.conn.execute(
            "INSERT INTO documents (document_id, customer_id, kind, status, requested_on,"
            " received_on) VALUES (?, ?, ?, 'requested', ?, NULL)",
            (document_id, customer_id, kind, self.today.isoformat()),
        )
        self.conn.commit()
        return document_id

    @audited
    def send_statement(self, case_id: str, loan_id: str, to_email: str) -> bool:
        """Send a loan statement to the email address held on the customer record."""
        loan = self._loan(loan_id)
        customer = self._customer(loan["customer_id"])
        if not _looks_like_email(to_email):
            raise PolicyError(f"{to_email!r} is not a valid email address")
        on_file = (customer["email"] or "").strip().lower()
        if to_email.strip().lower() != on_file:
            raise PolicyError(
                f"statements may only be sent to the address on file ({on_file or 'none'}); "
                f"update the contact record first"
            )
        return True

    @audited
    def update_contact(
        self,
        case_id: str,
        customer_id: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> bool:
        """Update a customer's phone number, email address, or both."""
        self._customer(customer_id)
        if phone is None and email is None:
            raise PolicyError("supply at least one of phone or email")
        if phone is not None:
            if not _looks_like_phone(phone):
                raise PolicyError(f"{phone!r} is not a valid phone number")
            self.conn.execute(
                "UPDATE customers SET phone = ? WHERE customer_id = ?", (phone, customer_id)
            )
        if email is not None:
            if not _looks_like_email(email):
                raise PolicyError(f"{email!r} is not a valid email address")
            self.conn.execute(
                "UPDATE customers SET email = ? WHERE customer_id = ?", (email, customer_id)
            )
        self.conn.commit()
        return True

    @audited
    def cancel_autopay(self, case_id: str, loan_id: str) -> bool:
        """Switch off the standing auto-debit mandate on a loan.

        Added for the mandate-withdrawal journey. The customer keeps the same due
        dates; only the automatic collection stops.
        """
        loan = self._loan(loan_id)
        if not loan["autopay"]:
            raise PolicyError(f"autopay is not active on loan {loan_id}")
        self.conn.execute("UPDATE loans SET autopay = 0 WHERE loan_id = ?", (loan_id,))
        self.conn.commit()
        return True

    # ------------------------------------------------------------------
    # Case lifecycle
    # ------------------------------------------------------------------

    @audited
    def escalate(self, case_id: str, reason: str) -> bool:
        """Hand the case to a human. Always permitted, whatever the state."""
        if not isinstance(reason, str) or not reason.strip():
            raise PolicyError("an escalation reason is required")
        return True

    @audited
    def commit(self, case_id: str, summary: str, actions_taken: list[str]) -> dict:
        """End the case with a summary and the list of actions actually taken."""
        if case_id in self._committed_cases:
            raise PolicyError(f"case {case_id} has already been committed")
        if not isinstance(summary, str) or not summary.strip():
            raise PolicyError("a case summary is required")
        if not isinstance(actions_taken, list) or any(
            not isinstance(a, str) for a in actions_taken
        ):
            raise PolicyError("actions_taken must be a list of strings")
        self._committed_cases.add(case_id)
        return {
            "case_id": case_id,
            "summary": summary.strip(),
            "actions_taken": list(actions_taken),
            "committed_on": self.today.isoformat(),
        }
