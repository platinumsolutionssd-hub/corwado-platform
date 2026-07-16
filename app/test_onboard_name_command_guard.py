"""
Standalone regression check for the onboard_name command-word bug
(2026-07-16): a returning user replying REGISTER (or any other reserved
command word) to the self-onboarding "what's your name?" prompt was
being stored as their literal full_name instead of being recognized as
a command -- confirmed live in the database as junk land_steward rows
named "Register" and "Newfarmer". Fixed in
app/services/telegram_inbound.py's _handle_onboard_name.

Runs directly against the real database (no mocks -- this project's own
established pattern, see app/seed_boq_maize.py), through the real
handle_update() entrypoint, exactly as app/telegram_poller.py would
call it for a live Telegram message. Self-contained and self-cleaning:
uses a chat_id no real user could ever have, and deletes every row it
touches at the end, verifying via a fresh query that cleanup was
complete.

Run:
    python -m app.test_onboard_name_command_guard
"""
from app.database import SessionLocal
from app import models
from app.services.telegram_inbound import handle_update

TEST_CHAT_ID = "TEST_ONBOARD_GUARD_9f3e7c1a"
TEST_PHONE_DIGITS = "0999000111"  # unregistered on purpose -- see run()'s guard below


def _send(db, text: str) -> str:
    return handle_update(db, {"message": {"chat": {"id": TEST_CHAT_ID}, "text": text}})


def _cleanup(db):
    db.query(models.InboundMessage).filter_by(external_chat_id=TEST_CHAT_ID).delete()
    db.query(models.TelegramConversationState).filter_by(chat_id=TEST_CHAT_ID).delete()
    # Defensive: if the bug were still present, this is where the junk
    # record would have landed. Deleted by telegram_chat_id, not by
    # full_name, so this can never touch a real farmer's row.
    db.query(models.LandSteward).filter_by(telegram_chat_id=TEST_CHAT_ID).delete()
    db.commit()


def _assert_no_junk_steward(db, label: str):
    junk = db.query(models.LandSteward).filter_by(telegram_chat_id=TEST_CHAT_ID).first()
    assert junk is None, (
        f"[{label}] BUG STILL PRESENT: a land_steward row was created "
        f"from a command word (full_name={junk.full_name if junk else None!r})"
    )


def run():
    db = SessionLocal()
    try:
        # Start clean in case a previous failed run left rows behind.
        _cleanup(db)

        # Self-verifying guard, not just a comment: step 3 below sends
        # REGISTER <phone> through the real lookup, which would mutate
        # a REAL farmer's telegram_chat_id if this number ever matched
        # one (confirmed live 2026-07-16 -- an earlier draft of this
        # test used 0912345678, which turned out to already belong to
        # "Achol Deng Malual"). Refuse to run rather than risk it again.
        collision = db.query(models.LandSteward).filter(
            models.LandSteward.phone_number.like(f"%{TEST_PHONE_DIGITS[-9:]}%")
        ).first()
        assert collision is None, (
            f"TEST_PHONE_DIGITS {TEST_PHONE_DIGITS!r} collides with a real steward "
            f"({collision.full_name!r}) -- pick a different unregistered number."
        )

        # 1. First contact -- arbitrary text starts self-onboarding and
        #    asks for a name (state.awaiting becomes "onboard_name").
        reply = _send(db, "hello")
        state = db.query(models.TelegramConversationState).filter_by(chat_id=TEST_CHAT_ID).first()
        assert state is not None and state.awaiting == "onboard_name", (
            f"Setup failed: expected onboard_name, got {state.awaiting if state else None!r} "
            f"(reply was: {reply!r})"
        )
        print("1. First contact -> onboard_name:", "OK")

        # 2. The original bug: reply with the bare command word REGISTER
        #    -- the welcome message itself tells a returning user to do
        #    exactly this. Must NOT be stored as a name.
        reply = _send(db, "Register")
        _assert_no_junk_steward(db, "bare REGISTER")
        state = db.query(models.TelegramConversationState).filter_by(chat_id=TEST_CHAT_ID).first()
        assert state.awaiting != "onboard_phone", "BUG STILL PRESENT: advanced to onboard_phone after REGISTER"
        assert "REGISTER" in reply.upper(), f"Expected the REGISTER usage/lookup reply, got: {reply!r}"
        print("2. Bare 'Register' as name reply -> not stored, not advanced:", "OK")
        print("   reply:", reply)

        # 3. Re-enter onboarding and try REGISTER with a trailing phone
        #    number -- must route into the real lookup, not be stored
        #    as a name either.
        _send(db, "hello again")
        reply = _send(db, f"Register {TEST_PHONE_DIGITS}")
        _assert_no_junk_steward(db, "REGISTER <phone>")
        print(f"3. 'Register {TEST_PHONE_DIGITS}' as name reply -> not stored:", "OK")
        print("   reply:", reply)

        # 4. Newfarmer -- the second command word confirmed live in the
        #    database as a junk record. Any reserved command word must
        #    be rejected as a name, not just REGISTER.
        _send(db, "hello once more")
        reply = _send(db, "Newfarmer")
        _assert_no_junk_steward(db, "NEWFARMER")
        state = db.query(models.TelegramConversationState).filter_by(chat_id=TEST_CHAT_ID).first()
        assert state.awaiting != "onboard_phone", "BUG STILL PRESENT: advanced to onboard_phone after Newfarmer"
        print("4. 'Newfarmer' as name reply -> not stored, not advanced:", "OK")
        print("   reply:", reply)

        # 5. Sanity check the fix doesn't break the legitimate case: a
        #    real name that merely CONTAINS a command word as a
        #    substring, not as the command itself, must still work.
        _send(db, "hello finally")
        reply = _send(db, "Regina Register-Achol")
        state = db.query(models.TelegramConversationState).filter_by(chat_id=TEST_CHAT_ID).first()
        assert state.awaiting == "onboard_phone", (
            f"REGRESSION: a real name was rejected -- expected onboard_phone, got {state.awaiting!r}"
        )
        print("5. Real name 'Regina Register-Achol' still accepted -> onboard_phone:", "OK")

        print("\nALL CHECKS PASSED.")
    finally:
        # Count what this run actually left behind BEFORE cleaning it
        # up -- counting after would trivially always read zero.
        before = (
            db.query(models.LandSteward).filter_by(telegram_chat_id=TEST_CHAT_ID).count()
            + db.query(models.TelegramConversationState).filter_by(chat_id=TEST_CHAT_ID).count()
            + db.query(models.InboundMessage).filter_by(external_chat_id=TEST_CHAT_ID).count()
        )
        _cleanup(db)
        db.close()
        # Fresh session for the final confirmation query -- proves
        # cleanup actually committed, not just that the same in-memory
        # session thinks it did.
        confirm_db = SessionLocal()
        try:
            remaining_confirmed = (
                confirm_db.query(models.LandSteward).filter_by(telegram_chat_id=TEST_CHAT_ID).count()
                + confirm_db.query(models.TelegramConversationState).filter_by(chat_id=TEST_CHAT_ID).count()
                + confirm_db.query(models.InboundMessage).filter_by(external_chat_id=TEST_CHAT_ID).count()
            )
        finally:
            confirm_db.close()
        print(f"Cleanup: {before} row(s) found and removed for {TEST_CHAT_ID}; {remaining_confirmed} remain (fresh-session check).")
        assert remaining_confirmed == 0, "Cleanup incomplete -- test data still present."


if __name__ == "__main__":
    run()
