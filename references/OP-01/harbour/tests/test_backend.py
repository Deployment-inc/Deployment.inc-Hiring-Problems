"""Tests for the Harbour tool layer.

Covers the happy path of all fourteen tools, every policy refusal the tools
implement, and the guarantee that the audit log records failures as well as
successes. The fixture below uses hand-written rows rather than ``seed.json`` so
that a change to the seed generator cannot silently change what these assert;
one test does load the real seed, to check it fits the schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harbour import policy
from harbour.backend import Backend, NotFound, PolicyError
from harbour.seed_data import DEFAULT_SEED_PATH, load_seed

CASE = "c_test"

CUSTOMERS = [
    # verified, hardship
    ("cu_100", "Rhea Kapoor", "+919876543210", "rhea.kapoor@example.com", 0, 0),
    ("cu_200", "Devan Iyer", "+919812345678", "devan.iyer@example.com", 1, 0),
    ("cu_300", "Meera Sethi", "+919800011122", "meera.sethi@example.com", 1, 1),
]

LOANS = [
    # loan_id, customer, principal, balance, apr, status, opened_on, next_due_on, autopay
    ("ln_100", "cu_100", 200000.0, 120000.0, 14.5, "active", "2024-01-10", "2026-10-01", 1),
    ("ln_200", "cu_200", 350000.0, 190000.0, 12.0, "active", "2024-01-10", "2026-10-05", 1),
    ("ln_201", "cu_200", 90000.0, 0.0, 15.0, "closed", "2022-03-01", "2026-10-05", 0),
    ("ln_202", "cu_200", 60000.0, 55000.0, 18.0, "active", "2026-06-01", "2026-10-09", 0),
    ("ln_300", "cu_300", 400000.0, 250000.0, 11.0, "active", "2023-02-01", "2026-10-11", 0),
]

PAYMENTS = [
    ("pm_100", "ln_200", 8000.0, "2026-08-01", "2026-08-02", "posted"),
    ("pm_101", "ln_200", 8000.0, "2025-01-01", "2025-01-02", "posted"),
    ("pm_103", "ln_200", 8000.0, "2026-08-20", "2026-08-21", "posted"),
    ("pm_104", "ln_100", 6000.0, "2026-08-20", None, "failed"),
]

FEES = [
    # in-cap, waivable
    ("fe_100", "ln_200", "late_payment", 500.0, "applied", "2026-09-01"),
    # already waived
    ("fe_101", "ln_200", "nsf", 900.0, "waived", "2026-07-01"),
    # above the single-waiver ceiling
    ("fe_102", "ln_200", "processing", 3000.0, "applied", "2026-08-15"),
    # ln_300 has already used its full 12-month allowance
    ("fe_110", "ln_300", "late_payment", 400.0, "waived", "2026-03-01"),
    ("fe_111", "ln_300", "late_payment", 450.0, "waived", "2026-06-01"),
    ("fe_112", "ln_300", "late_payment", 500.0, "applied", "2026-09-02"),
    ("fe_120", "ln_100", "late_payment", 300.0, "applied", "2026-09-05"),
]

DISPUTES = [
    ("dp_100", "ln_200", "pm_100", "Debited twice.", "open", "2026-09-01", None, None),
    ("dp_101", "ln_200", "pm_101", "Old query.", "closed", "2025-02-01", "2025-02-20", "rejected"),
]


@pytest.fixture()
def bk() -> Backend:
    backend = Backend(":memory:", today=policy.TODAY)
    conn = backend.conn
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", CUSTOMERS)
    conn.executemany("INSERT INTO loans VALUES (?,?,?,?,?,?,?,?,?)", LOANS)
    conn.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?)", PAYMENTS)
    conn.executemany("INSERT INTO fees VALUES (?,?,?,?,?,?)", FEES)
    conn.executemany("INSERT INTO disputes VALUES (?,?,?,?,?,?,?,?)", DISPUTES)
    conn.commit()
    yield backend
    backend.close()


def last_audit(bk: Backend) -> dict:
    return bk.audit_trail(CASE)[-1]


def verified_before(trail: list[dict], tool: str, customer_id: str) -> bool:
    """Check an ordered audit trail.

    True when the first call to ``tool`` in this trail was preceded by a
    successful ``verify_identity`` for ``customer_id`` in the same case.
    """
    seen_verify = False
    for row in trail:
        if row["tool"] == tool:
            return seen_verify
        if row["tool"] == "verify_identity" and row["ok"] and json.loads(row["result_json"]) is True:
            if json.loads(row["args_json"]).get("customer_id") == customer_id:
                seen_verify = True
    return False


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


def test_lookup_loan_happy(bk: Backend) -> None:
    loan = bk.lookup_loan(CASE, "ln_200")
    assert loan["loan_id"] == "ln_200"
    assert loan["customer_name"] == "Devan Iyer"
    assert loan["customer_verified"] is True


def test_lookup_loan_missing(bk: Backend) -> None:
    with pytest.raises(NotFound):
        bk.lookup_loan(CASE, "ln_999")


def test_payment_history_happy(bk: Backend) -> None:
    rows = bk.payment_history(CASE, "ln_200")
    assert [r["payment_id"] for r in rows] == ["pm_103", "pm_100", "pm_101"]


def test_payment_history_respects_limit(bk: Backend) -> None:
    assert len(bk.payment_history(CASE, "ln_200", limit=1)) == 1


def test_payment_history_rejects_bad_limit(bk: Backend) -> None:
    with pytest.raises(PolicyError):
        bk.payment_history(CASE, "ln_200", limit=0)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_verify_identity_happy(bk: Backend) -> None:
    assert bk.verify_identity(CASE, "cu_100", "3210") is True
    row = bk.conn.execute(
        "SELECT verified FROM customers WHERE customer_id = 'cu_100'"
    ).fetchone()
    assert row["verified"] == 1


def test_verify_identity_mismatch_does_not_set_flag(bk: Backend) -> None:
    assert bk.verify_identity(CASE, "cu_100", "0000") is False
    row = bk.conn.execute(
        "SELECT verified FROM customers WHERE customer_id = 'cu_100'"
    ).fetchone()
    assert row["verified"] == 0


def test_verify_identity_requires_four_digits(bk: Backend) -> None:
    with pytest.raises(PolicyError):
        bk.verify_identity(CASE, "cu_100", "321")


def test_verify_identity_unknown_customer(bk: Backend) -> None:
    with pytest.raises(NotFound):
        bk.verify_identity(CASE, "cu_999", "3210")


# ---------------------------------------------------------------------------
# schedule_payment
# ---------------------------------------------------------------------------


def test_schedule_payment_happy(bk: Backend) -> None:
    payment_id = bk.schedule_payment(CASE, "ln_200", 5000.0, "2026-09-25")
    row = bk.conn.execute(
        "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
    ).fetchone()
    assert row["status"] == "scheduled"
    assert row["loan_id"] == "ln_200"
    assert row["amount"] == 5000.0


def test_schedule_payment_requires_verified_customer(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="identity not verified"):
        bk.schedule_payment(CASE, "ln_100", 5000.0, "2026-09-25")


def test_schedule_payment_in_the_past_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="in the past"):
        bk.schedule_payment(CASE, "ln_200", 5000.0, "2026-09-01")


def test_schedule_payment_beyond_window_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="days ahead"):
        bk.schedule_payment(CASE, "ln_200", 5000.0, "2026-12-31")


def test_schedule_payment_on_closed_loan_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="closed"):
        bk.schedule_payment(CASE, "ln_201", 5000.0, "2026-09-25")


def test_schedule_payment_below_minimum_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="below the minimum"):
        bk.schedule_payment(CASE, "ln_200", 10.0, "2026-09-25")


def test_schedule_payment_above_ceiling_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="ceiling"):
        bk.schedule_payment(CASE, "ln_200", policy.PAYMENT_MAX_AMOUNT_INR + 1, "2026-09-25")


def test_schedule_payment_bad_date_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="ISO date"):
        bk.schedule_payment(CASE, "ln_200", 5000.0, "25/09/2026")


# ---------------------------------------------------------------------------
# waive_fee
# ---------------------------------------------------------------------------


def test_waive_fee_happy(bk: Backend) -> None:
    assert bk.waive_fee(CASE, "fe_100") is True
    row = bk.conn.execute("SELECT status FROM fees WHERE fee_id = 'fe_100'").fetchone()
    assert row["status"] == "waived"


def test_waive_fee_requires_verified_customer(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="identity not verified"):
        bk.waive_fee(CASE, "fe_120")


def test_waive_fee_already_waived_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="already been waived"):
        bk.waive_fee(CASE, "fe_101")


def test_waive_fee_above_amount_ceiling_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="single-waiver limit"):
        bk.waive_fee(CASE, "fe_102")


def test_waive_fee_over_12_month_cap_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="cap is"):
        bk.waive_fee(CASE, "fe_112")


def test_waive_fee_missing(bk: Backend) -> None:
    with pytest.raises(NotFound):
        bk.waive_fee(CASE, "fe_999")


# ---------------------------------------------------------------------------
# apply_hardship_plan
# ---------------------------------------------------------------------------


def test_apply_hardship_plan_happy(bk: Backend) -> None:
    assert bk.apply_hardship_plan(CASE, "ln_200", 3) is True
    loan = bk.conn.execute("SELECT status FROM loans WHERE loan_id = 'ln_200'").fetchone()
    customer = bk.conn.execute(
        "SELECT hardship_flag FROM customers WHERE customer_id = 'cu_200'"
    ).fetchone()
    assert loan["status"] == "hardship"
    assert customer["hardship_flag"] == 1


def test_apply_hardship_plan_requires_verified_customer(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="identity not verified"):
        bk.apply_hardship_plan(CASE, "ln_100", 3)


def test_apply_hardship_plan_term_too_long_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="exceeds"):
        bk.apply_hardship_plan(CASE, "ln_200", policy.HARDSHIP_MAX_TERM_MONTHS + 1)


def test_apply_hardship_plan_term_too_short_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="at least"):
        bk.apply_hardship_plan(CASE, "ln_200", 0)


def test_apply_hardship_plan_loan_too_new_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="on the book"):
        bk.apply_hardship_plan(CASE, "ln_202", 3)


def test_apply_hardship_plan_ineligible_status_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="eligible"):
        bk.apply_hardship_plan(CASE, "ln_201", 3)


def test_apply_hardship_plan_second_concurrent_plan_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="already on a hardship plan"):
        bk.apply_hardship_plan(CASE, "ln_300", 3)


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------


def test_raise_dispute_happy(bk: Backend) -> None:
    dispute_id = bk.raise_dispute(CASE, "ln_200", "pm_103", "Charged twice in August.")
    row = bk.conn.execute(
        "SELECT * FROM disputes WHERE dispute_id = ?", (dispute_id,)
    ).fetchone()
    assert row["status"] == "open"
    assert row["opened_on"] == policy.TODAY
    assert row["outcome"] is None


def test_raise_dispute_wrong_loan_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="does not belong"):
        bk.raise_dispute(CASE, "ln_100", "pm_103", "Charged twice.")


def test_raise_dispute_outside_window_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="dispute window"):
        bk.raise_dispute(CASE, "ln_200", "pm_101", "Very old charge.")


def test_raise_dispute_duplicate_open_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="already has an open dispute"):
        bk.raise_dispute(CASE, "ln_200", "pm_100", "Same complaint again.")


def test_raise_dispute_empty_reason_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="reason is required"):
        bk.raise_dispute(CASE, "ln_200", "pm_103", "   ")


def test_close_dispute_happy(bk: Backend) -> None:
    assert bk.close_dispute(CASE, "dp_100", "upheld") is True
    row = bk.conn.execute("SELECT * FROM disputes WHERE dispute_id = 'dp_100'").fetchone()
    assert row["status"] == "closed"
    assert row["outcome"] == "upheld"
    assert row["closed_on"] == policy.TODAY


def test_close_dispute_already_closed_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="not open"):
        bk.close_dispute(CASE, "dp_101", "upheld")


def test_close_dispute_bad_outcome_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="outcome must be"):
        bk.close_dispute(CASE, "dp_100", "partially_upheld")


def test_close_dispute_missing(bk: Backend) -> None:
    with pytest.raises(NotFound):
        bk.close_dispute(CASE, "dp_999", "upheld")


# ---------------------------------------------------------------------------
# Documents, statements, contact
# ---------------------------------------------------------------------------


def test_request_document_happy(bk: Backend) -> None:
    document_id = bk.request_document(CASE, "cu_100", "income_proof")
    row = bk.conn.execute(
        "SELECT * FROM documents WHERE document_id = ?", (document_id,)
    ).fetchone()
    assert row["status"] == "requested"
    assert row["kind"] == "income_proof"
    assert row["received_on"] is None


def test_request_document_unknown_kind_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="not a document kind"):
        bk.request_document(CASE, "cu_100", "selfie_with_passport")


def test_request_document_unknown_customer(bk: Backend) -> None:
    with pytest.raises(NotFound):
        bk.request_document(CASE, "cu_999", "income_proof")


def test_send_statement_happy(bk: Backend) -> None:
    assert bk.send_statement(CASE, "ln_200", "devan.iyer@example.com") is True


def test_send_statement_to_other_address_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="only be sent to the address on file"):
        bk.send_statement(CASE, "ln_200", "someone.else@example.com")


def test_send_statement_invalid_address_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="not a valid email"):
        bk.send_statement(CASE, "ln_200", "not-an-email")


def test_update_contact_happy(bk: Backend) -> None:
    assert bk.update_contact(CASE, "cu_100", phone="+919000011111") is True
    assert bk.update_contact(CASE, "cu_100", email="rhea.k@example.org") is True
    row = bk.conn.execute(
        "SELECT phone, email FROM customers WHERE customer_id = 'cu_100'"
    ).fetchone()
    assert row["phone"] == "+919000011111"
    assert row["email"] == "rhea.k@example.org"


def test_update_contact_requires_a_field(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="at least one"):
        bk.update_contact(CASE, "cu_100")


def test_update_contact_rejects_bad_phone(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="not a valid phone"):
        bk.update_contact(CASE, "cu_100", phone="12")


def test_update_contact_rejects_bad_email(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="not a valid email"):
        bk.update_contact(CASE, "cu_100", email="rhea@@example")


# ---------------------------------------------------------------------------
# autopay
# ---------------------------------------------------------------------------


def test_cancel_autopay_happy(bk: Backend) -> None:
    bk.verify_identity(CASE, "cu_200", "5678")
    assert bk.cancel_autopay(CASE, "ln_200") is True
    row = bk.conn.execute("SELECT autopay FROM loans WHERE loan_id = 'ln_200'").fetchone()
    assert row["autopay"] == 0


def test_cancel_autopay_when_not_active_is_refused(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="not active"):
        bk.cancel_autopay(CASE, "ln_202")


def test_cancel_autopay_missing_loan(bk: Backend) -> None:
    with pytest.raises(NotFound):
        bk.cancel_autopay(CASE, "ln_999")


# ---------------------------------------------------------------------------
# Case lifecycle
# ---------------------------------------------------------------------------


def test_escalate_happy(bk: Backend) -> None:
    assert bk.escalate(CASE, "Customer alleges the account is not theirs.") is True
    assert last_audit(bk)["tool"] == "escalate"


def test_escalate_is_allowed_without_verification(bk: Backend) -> None:
    assert bk.escalate(CASE, "Unverified caller, possible account takeover.") is True


def test_escalate_requires_a_reason(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="reason is required"):
        bk.escalate(CASE, "")


def test_commit_happy(bk: Backend) -> None:
    out = bk.commit(CASE, "Waived one late fee.", ["verify_identity", "waive_fee"])
    assert out["case_id"] == CASE
    assert out["actions_taken"] == ["verify_identity", "waive_fee"]
    assert out["committed_on"] == policy.TODAY


def test_commit_twice_is_refused(bk: Backend) -> None:
    bk.commit(CASE, "Done.", [])
    with pytest.raises(PolicyError, match="already been committed"):
        bk.commit(CASE, "Done again.", [])


def test_commit_requires_a_summary(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="summary is required"):
        bk.commit(CASE, "  ", [])


def test_commit_rejects_bad_actions_list(bk: Backend) -> None:
    with pytest.raises(PolicyError, match="list of strings"):
        bk.commit(CASE, "Done.", "waive_fee")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The audit log
# ---------------------------------------------------------------------------


def test_audit_log_records_successes_with_args_and_result(bk: Backend) -> None:
    bk.lookup_loan(CASE, "ln_200")
    entry = last_audit(bk)
    assert entry["tool"] == "lookup_loan"
    assert entry["ok"] == 1
    assert entry["error"] is None
    assert json.loads(entry["args_json"]) == {"loan_id": "ln_200"}
    assert json.loads(entry["result_json"])["loan_id"] == "ln_200"


def test_audit_log_records_policy_failures(bk: Backend) -> None:
    with pytest.raises(PolicyError):
        bk.schedule_payment(CASE, "ln_200", 5000.0, "2026-09-01")
    entry = last_audit(bk)
    assert entry["tool"] == "schedule_payment"
    assert entry["ok"] == 0
    assert "PolicyError" in entry["error"]
    assert json.loads(entry["args_json"])["due_on"] == "2026-09-01"


def test_audit_log_records_not_found_failures(bk: Backend) -> None:
    with pytest.raises(NotFound):
        bk.lookup_loan(CASE, "ln_999")
    entry = last_audit(bk)
    assert entry["ok"] == 0
    assert "NotFound" in entry["error"]


def test_audit_log_is_append_only_and_ordered(bk: Backend) -> None:
    bk.lookup_loan(CASE, "ln_200")
    with pytest.raises(NotFound):
        bk.lookup_loan(CASE, "ln_999")
    bk.escalate(CASE, "Referred to collections.")
    trail = bk.audit_trail(CASE)
    assert [r["tool"] for r in trail] == ["lookup_loan", "lookup_loan", "escalate"]
    assert [r["seq"] for r in trail] == sorted(r["seq"] for r in trail)


def test_audit_log_scopes_by_case(bk: Backend) -> None:
    bk.lookup_loan("c_one", "ln_200")
    bk.lookup_loan("c_two", "ln_200")
    assert len(bk.audit_trail("c_one")) == 1
    assert len(bk.audit_trail()) == 2


# ---------------------------------------------------------------------------
# Verification gate across the money tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda b: b.schedule_payment(CASE, "ln_100", 5000.0, "2026-09-25"), id="schedule_payment"),
        pytest.param(lambda b: b.waive_fee(CASE, "fe_120"), id="waive_fee"),
        pytest.param(lambda b: b.apply_hardship_plan(CASE, "ln_100", 3), id="apply_hardship_plan"),
    ],
)
def test_money_tools_refuse_an_unverified_customer(bk: Backend, call) -> None:
    with pytest.raises(PolicyError, match="identity not verified"):
        call(bk)


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda b: b.schedule_payment(CASE, "ln_100", 5000.0, "2026-09-25"), id="schedule_payment"),
        pytest.param(lambda b: b.waive_fee(CASE, "fe_120"), id="waive_fee"),
        pytest.param(lambda b: b.apply_hardship_plan(CASE, "ln_100", 3), id="apply_hardship_plan"),
    ],
)
def test_money_tools_succeed_once_verified(bk: Backend, call) -> None:
    assert bk.verify_identity(CASE, "cu_100", "3210") is True
    call(bk)
    assert last_audit(bk)["ok"] == 1




def test_verified_before_detector_is_not_vacuous(bk: Backend) -> None:
    # Guards the detector used above: it must return True when the verification
    # really did happen first.
    bk.verify_identity(CASE, "cu_100", "3210")
    bk.schedule_payment(CASE, "ln_100", 5000.0, "2026-09-25")
    trail = bk.audit_trail(CASE)
    assert verified_before(trail, "schedule_payment", "cu_100") is True

    # A failed verification does not count.
    other = Backend(":memory:", today=policy.TODAY)
    other.conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", CUSTOMERS)
    other.conn.executemany("INSERT INTO loans VALUES (?,?,?,?,?,?,?,?,?)", LOANS)
    other.conn.commit()
    assert other.verify_identity(CASE, "cu_100", "0000") is False
    other.cancel_autopay(CASE, "ln_100")
    assert verified_before(other.audit_trail(CASE), "cancel_autopay", "cu_100") is False
    other.close()


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


def test_seed_json_loads_into_the_schema() -> None:
    assert Path(DEFAULT_SEED_PATH).exists(), "run `python -m harbour.seed_data` first"
    backend = Backend(":memory:", today=policy.TODAY)
    counts = load_seed(backend.conn, DEFAULT_SEED_PATH)
    assert counts["customers"] == 60
    assert counts["loans"] >= 60
    assert 200 <= counts["payments"] <= 800
    assert counts["fees"] >= 40
    assert counts["disputes"] == 15
    assert counts["documents"] == 25
    backend.close()


def test_seed_contains_the_awkward_rows() -> None:
    backend = Backend(":memory:", today=policy.TODAY)
    load_seed(backend.conn, DEFAULT_SEED_PATH)
    conn = backend.conn

    def scalar(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    assert scalar("SELECT COUNT(*) FROM loans WHERE status = 'hardship'") >= 1
    assert scalar("SELECT COUNT(*) FROM customers WHERE hardship_flag = 1") >= 1
    assert scalar("SELECT COUNT(*) FROM fees WHERE status = 'waived'") >= 1
    assert scalar("SELECT COUNT(*) FROM disputes WHERE status = 'closed'") >= 1
    assert scalar("SELECT COUNT(*) FROM customers WHERE verified = 0") >= 1
    assert scalar("SELECT COUNT(*) FROM payments WHERE status = 'failed'") >= 1
    assert scalar("SELECT COUNT(*) FROM loans WHERE status = 'closed'") >= 1
    # a customer holding two loans
    assert scalar(
        "SELECT COUNT(*) FROM (SELECT customer_id FROM loans GROUP BY customer_id"
        " HAVING COUNT(*) > 1)"
    ) >= 1
    backend.close()


def test_seed_generation_is_deterministic() -> None:
    from harbour.seed_data import build_seed

    assert json.dumps(build_seed(), sort_keys=True) == json.dumps(build_seed(), sort_keys=True)
