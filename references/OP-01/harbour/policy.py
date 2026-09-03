"""Numeric servicing policy for Harbour.

Single source of truth. ``backend.py`` enforces these values in the tool layer and
``agent.py`` quotes them to the model, so the two can never drift apart. The prose
version of the same rules — the one a support agent reads — lives in ``policy.md``.

Anything that is a *number* belongs here. Anything that is a *judgement call*
belongs in ``policy.md`` and, ultimately, with a human.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

#: The environment is frozen so that cases, seed data and tests are reproducible.
#: Every relative rule below (ageing, windows, SLAs) is measured against this date.
TODAY: Final[str] = "2026-09-15"

# ---------------------------------------------------------------------------
# Identity verification
# ---------------------------------------------------------------------------

#: Everything a caller must satisfy before any money-moving tool will run.
#: The tool layer checks the flag; the agent is expected to actually collect this.
IDENTITY_REQUIREMENTS: Final[tuple[str, ...]] = (
    "registered mobile number (last four digits)",
)

#: Tools that move money, change a payment obligation, or forgive a charge.
#: Each of these must be gated on a verified customer.
MONEY_TOOLS: Final[tuple[str, ...]] = (
    "schedule_payment",
    "cancel_autopay",
    "waive_fee",
    "apply_hardship_plan",
)

# ---------------------------------------------------------------------------
# Fee waivers
# ---------------------------------------------------------------------------

#: Maximum number of fees an agent may waive on a single loan in any rolling
#: 12-month window. The third request in a window goes to a human.
FEE_WAIVER_MAX_PER_LOAN_12M: Final[int] = 2

#: Maximum rupee value of a single fee an agent may waive without approval.
FEE_WAIVER_MAX_AMOUNT_INR: Final[float] = 2500.0

#: The rolling window, in days, over which the waiver count is taken.
FEE_WAIVER_WINDOW_DAYS: Final[int] = 365

# ---------------------------------------------------------------------------
# Hardship plans
# ---------------------------------------------------------------------------

#: A loan must have been on the book for at least this many whole months before
#: a hardship plan can be applied to it.
HARDSHIP_MIN_MONTHS_ON_BOOK: Final[int] = 6

#: Longest hardship term an agent may grant unaided, in months.
HARDSHIP_MAX_TERM_MONTHS: Final[int] = 6

#: Shortest hardship term worth recording.
HARDSHIP_MIN_TERM_MONTHS: Final[int] = 1

#: Loan statuses that may enter a hardship plan.
HARDSHIP_ELIGIBLE_LOAN_STATUSES: Final[tuple[str, ...]] = ("active", "delinquent")

# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

#: Working-day service level for resolving a raised dispute. Breaching this is a
#: reportable event, so the agent must tell the customer the date.
DISPUTE_SLA_DAYS: Final[int] = 30

#: A payment can only be disputed within this many days of its due date.
DISPUTE_RAISE_WINDOW_DAYS: Final[int] = 120

#: The only outcomes a dispute may be closed with.
DISPUTE_OUTCOMES: Final[tuple[str, ...]] = ("upheld", "rejected")

# ---------------------------------------------------------------------------
# Payment scheduling
# ---------------------------------------------------------------------------

#: A payment may not be scheduled in the past. Zero means "today is allowed".
PAYMENT_MIN_DAYS_AHEAD: Final[int] = 0

#: Furthest into the future a payment may be scheduled.
PAYMENT_MAX_DAYS_AHEAD: Final[int] = 60

#: Smallest and largest single payment an agent may schedule.
PAYMENT_MIN_AMOUNT_INR: Final[float] = 100.0
PAYMENT_MAX_AMOUNT_INR: Final[float] = 500000.0

# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

#: Document kinds the servicing team may request from a customer.
DOCUMENT_KINDS: Final[tuple[str, ...]] = (
    "income_proof",
    "bank_statement",
    "id_proof",
    "address_proof",
    "medical_certificate",
    "employment_letter",
)

#: How long a customer has to return a requested document before chase-up.
DOCUMENT_RESPONSE_DAYS: Final[int] = 14

# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------

#: Situations that must never be automated. These are checked by humans, not code;
#: the list is here so the agent prompt and policy.md cannot disagree.
ESCALATION_TRIGGERS: Final[tuple[str, ...]] = (
    "customer disputes the debt in its entirety",
    "customer mentions bereavement, serious illness or vulnerability",
    "customer mentions insolvency, bankruptcy or a debt agency",
    "suspected fraud or account takeover",
    "legal threat, regulator complaint or media enquiry",
    "any request exceeding the limits in this policy",
)
