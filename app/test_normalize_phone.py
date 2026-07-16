"""
Regression check for normalize_phone() (2026-07-16): it previously only
stripped whitespace/hyphens and never reconciled local (leading-0) vs.
E.164 format, so STAFF 0928004009 reported "No staff authorization
found" for an operator whose row was seeded as +211928004009 -- a
literal string mismatch, not a real "not authorized" rejection. The
same gap silently missed a real phone-number duplicate in
land_steward too (see part B below).

Part A is pure unit coverage of normalize_phone() itself (no DB). Part
B runs the real reported bug and the real duplicate-detection miss
against the actual database, through the real handle_update()/
find_possible_duplicate() entrypoints -- no mocks, this project's
established pattern (see app/seed_boq_maize.py,
app/test_onboard_name_command_guard.py). The one real mutation this
performs (linking John Kariuki Ngugi's operator row to a test chat_id)
is reverted at the end and independently re-confirmed via a fresh
session query.

Run:
    python -m app.test_normalize_phone
"""
from app.database import SessionLocal
from app import models
from app.services.steward_registration import (
    normalize_phone,
    find_possible_duplicate,
    SOUTH_SUDAN_COUNTRY_CODE,
)
from app.services.telegram_inbound import handle_update

TEST_CHAT_ID = "TEST_NORMALIZE_PHONE_4d8b1a"


# --------------------------------------------------------------------- #
# Part A: normalize_phone() unit coverage
# --------------------------------------------------------------------- #

def run_unit_checks():
    cases = [
        # (input, expected, label)
        ("0928004009", "+211928004009", "local South Sudan -> E.164 (the STAFF bug case)"),
        (" 0928-004-009 ", "+211928004009", "local with whitespace/hyphens -> same E.164"),
        ("+211928004009", "+211928004009", "already E.164 (South Sudan) -> unchanged, not double-prefixed"),
        ("+254722225162", "+254722225162", "already E.164 (Kenya) -> unchanged -- never assumed South Sudan"),
        ("", "", "empty input -> empty"),
        ("abc", "", "letters -> invalid, empty (not passed through as a fake number)"),
        ("New", "", "junk word (real value found in the DB) -> invalid, empty"),
        ("012", "", "too short after leading 0 -> invalid, empty"),
        ("+123", "", "too short after + -> invalid, empty"),
    ]
    print("=== Part A: normalize_phone() unit checks ===")
    for raw, expected, label in cases:
        actual = normalize_phone(raw)
        assert actual == expected, f"[{label}] normalize_phone({raw!r}) = {actual!r}, expected {expected!r}"
        print(f"  OK  {label}: {raw!r} -> {actual!r}")
    assert SOUTH_SUDAN_COUNTRY_CODE == "+211"
    print("Part A: ALL PASSED\n")


# --------------------------------------------------------------------- #
# Part B: real database checks
# --------------------------------------------------------------------- #

def _cleanup_chat_rows(db):
    db.query(models.InboundMessage).filter_by(external_chat_id=TEST_CHAT_ID).delete()
    db.query(models.TelegramConversationState).filter_by(chat_id=TEST_CHAT_ID).delete()
    db.commit()


def run_db_checks():
    print("=== Part B: real database checks ===")
    db = SessionLocal()
    original_chat_id = None
    operator_id = None
    try:
        _cleanup_chat_rows(db)

        # --- B1: the real reported bug -- STAFF <local-format number> ---
        operator = db.query(models.AuthorizedOperator).filter_by(full_name="John Kariuki Ngugi").first()
        assert operator is not None, "Setup failed: John Kariuki Ngugi's authorized_operator row not found"
        assert operator.phone_number == "+211928004009", (
            f"Setup assumption changed: expected +211928004009, found {operator.phone_number!r}"
        )
        operator_id = operator.id
        original_chat_id = operator.telegram_chat_id
        assert original_chat_id in (None, ""), (
            f"Refusing to run: operator is already linked to a chat ({original_chat_id!r}) -- "
            f"would not be safe to overwrite and revert."
        )

        reply = handle_update(db, {"message": {"chat": {"id": TEST_CHAT_ID}, "text": "STAFF 0928004009"}})
        print(f"  STAFF 0928004009 reply: {reply!r}")
        assert "no staff authorization" not in reply.lower(), (
            f"BUG STILL PRESENT: local-format STAFF lookup failed. Reply: {reply!r}"
        )
        assert "john kariuki ngugi" in reply.lower() or "linked" in reply.lower(), (
            f"Expected a successful staff-link confirmation, got: {reply!r}"
        )

        db.refresh(operator)
        assert operator.telegram_chat_id == TEST_CHAT_ID, (
            f"Reply looked successful but operator.telegram_chat_id is {operator.telegram_chat_id!r}, "
            f"expected {TEST_CHAT_ID!r}"
        )
        print("  B1 OK: STAFF 0928004009 (local format) now correctly authorizes John Kariuki Ngugi")

        # --- B2: duplicate-phone detection, local-format input ---
        # James Otim's second land_steward row was registered with the
        # local-format number "0922090804" -- the exact same subscriber
        # number (922090804) as "TEST 1 END TO END SELF SERVICE"'s
        # already-stored "+211922090804". Under the pre-fix
        # normalize_phone, find_possible_duplicate would never have
        # matched these (literal string mismatch), silently missing a
        # real duplicate. Read-only check -- no mutation.
        duplicate = find_possible_duplicate(db, "0922090804")
        assert duplicate is not None, (
            "BUG STILL PRESENT (or data changed): local-format duplicate lookup found nothing -- "
            "expected it to match TEST 1 END TO END SELF SERVICE's +211922090804"
        )
        assert duplicate.phone_number == "+211922090804", (
            f"Matched the wrong record: {duplicate.full_name!r} / {duplicate.phone_number!r}"
        )
        print(
            f"  B2 OK: local-format duplicate lookup for '0922090804' now correctly matches "
            f"{duplicate.full_name!r} ({duplicate.phone_number!r})"
        )

        print("\nPart B: ALL PASSED")
    finally:
        # Revert the one real mutation this test makes, regardless of
        # pass/fail above.
        if operator_id is not None:
            operator = db.query(models.AuthorizedOperator).filter_by(id=operator_id).first()
            if operator is not None and operator.telegram_chat_id == TEST_CHAT_ID:
                operator.telegram_chat_id = original_chat_id
                db.commit()
        _cleanup_chat_rows(db)
        db.close()

        # Fresh session, independent of the one used above, to prove
        # the revert + cleanup actually committed.
        confirm_db = SessionLocal()
        try:
            confirmed_operator = confirm_db.query(models.AuthorizedOperator).filter_by(id=operator_id).first() if operator_id else None
            leftover_state = confirm_db.query(models.TelegramConversationState).filter_by(chat_id=TEST_CHAT_ID).count()
            leftover_messages = confirm_db.query(models.InboundMessage).filter_by(external_chat_id=TEST_CHAT_ID).count()
        finally:
            confirm_db.close()

        reverted_ok = confirmed_operator is not None and confirmed_operator.telegram_chat_id == original_chat_id
        print(
            f"Cleanup (fresh-session check): operator.telegram_chat_id back to {original_chat_id!r}: "
            f"{reverted_ok}; leftover conversation_state rows: {leftover_state}; leftover inbound_message rows: {leftover_messages}"
        )
        assert reverted_ok, "Cleanup incomplete -- operator.telegram_chat_id was not reverted."
        assert leftover_state == 0 and leftover_messages == 0, "Cleanup incomplete -- test chat rows still present."


if __name__ == "__main__":
    run_unit_checks()
    run_db_checks()
    print("\nALL CHECKS PASSED.")
