"""
Regression check for the Juba Arabic bilingual command-matching added
2026-07-16 alongside Philip Pitia's verified jba translations (see
app/services/telegram_strings.py's STRINGS and this module's
COMMAND_ALIASES / YES_WORDS / NO_WORDS): REGISTER/SEJILU, STAFF/UMAL,
PRICE/SER, BOUNDARY/HUDUD/UDUD, YES/NAM, NO/LA must all route
identically regardless of which half of the pair a farmer types.

Runs directly against the real database (no mocks -- this project's own
established pattern, see app/test_onboard_name_command_guard.py), through
the real handle_update() entrypoint, exactly as app/telegram_poller.py
would call it for a live Telegram message. Self-contained and
self-cleaning: uses chat_ids and phone numbers no real user could ever
have, and deletes every row it touches at the end, verifying via a fresh
session query that cleanup was complete.

Run:
    python -m app.test_bilingual_command_matching
"""
from shapely.geometry import Polygon
from geoalchemy2.shape import from_shape

from app.database import SessionLocal
from app import models
from app.services.telegram_inbound import handle_update

CHAT_BOUNDARY_CONFIRM = "TEST_JBA_BOUNDARY_CONFIRM_2a1c"
CHAT_BOUNDARY_ALIAS = "TEST_JBA_BOUNDARY_ALIAS_7e4b"
CHAT_ONBOARD_SEJILU = "TEST_JBA_ONBOARD_SEJILU_5d9f"
CHAT_ONBOARD_REGISTER = "TEST_JBA_ONBOARD_REGISTER_5d9f"  # control: same flow, English keyword
ALL_TEST_CHAT_IDS = [CHAT_BOUNDARY_CONFIRM, CHAT_BOUNDARY_ALIAS, CHAT_ONBOARD_SEJILU, CHAT_ONBOARD_REGISTER]

TEST_PHONE_A = "0999000221"  # steward for the boundary-confirm (NAM/YES) scenario
TEST_PHONE_B = "0999000222"  # steward for the boundary-alias (UDUD/HUDUD) scenario
TEST_PHONE_ONBOARD = "0999000223"  # bare SEJILU during onboarding must never look this up


def _send(db, chat_id: str, text: str) -> str:
    return handle_update(db, {"message": {"chat": {"id": chat_id}, "text": text}})


def _make_steward(db, chat_id: str, phone: str, name: str):
    steward = models.LandSteward(
        role=models.StewardRole.smallholder_farmer,
        full_name=name,
        phone_number=phone,
        preferred_language="juba_arabic",
        telegram_chat_id=chat_id,
    )
    db.add(steward)
    db.flush()
    return steward


def _make_parcel(db, steward):
    # A small, plausible square well within South Sudan (near Juba) --
    # only its presence matters to _handle_boundary_self, not its shape.
    square = Polygon([(31.60, 4.85), (31.601, 4.85), (31.601, 4.851), (31.60, 4.851), (31.60, 4.85)])
    parcel = models.Parcel(steward_id=steward.id, geom=from_shape(square, srid=4326))
    db.add(parcel)
    db.flush()
    return parcel


def _cleanup(db):
    for chat_id in ALL_TEST_CHAT_IDS:
        db.query(models.InboundMessage).filter_by(external_chat_id=chat_id).delete()
        db.query(models.TelegramConversationState).filter_by(chat_id=chat_id).delete()
        db.query(models.ParcelDrawToken).filter_by(originating_chat_id=chat_id).delete()
    stewards = db.query(models.LandSteward).filter(
        models.LandSteward.telegram_chat_id.in_(ALL_TEST_CHAT_IDS)
    ).all()
    for steward in stewards:
        db.query(models.Parcel).filter_by(steward_id=steward.id).delete()
        db.delete(steward)
    db.commit()


def _assert_no_real_collision(db):
    for phone in (TEST_PHONE_A, TEST_PHONE_B, TEST_PHONE_ONBOARD):
        collision = db.query(models.LandSteward).filter(
            models.LandSteward.phone_number.like(f"%{phone[-9:]}%"),
            ~models.LandSteward.telegram_chat_id.in_(ALL_TEST_CHAT_IDS),
        ).first()
        assert collision is None, (
            f"Test phone {phone!r} collides with a real steward ({collision.full_name!r}) "
            "-- pick a different unregistered number."
        )


def run():
    db = SessionLocal()
    try:
        _cleanup(db)  # start clean in case a previous failed run left rows behind
        _assert_no_real_collision(db)

        # --- Scenario 1: NAM accepted identically to YES -------------- #
        # Set up a linked farmer with an existing parcel so BOUNDARY hits
        # the boundary_self_existing_confirm YES/NO gate
        # (_handle_boundary_self_confirm).
        steward_a = _make_steward(db, CHAT_BOUNDARY_CONFIRM, TEST_PHONE_A, "Test Farmer A")
        _make_parcel(db, steward_a)
        db.commit()

        reply = _send(db, CHAT_BOUNDARY_CONFIRM, "BOUNDARY")
        state = db.query(models.TelegramConversationState).filter_by(chat_id=CHAT_BOUNDARY_CONFIRM).first()
        assert state.awaiting == "boundary_self_confirm", (
            f"Setup failed: expected boundary_self_confirm, got {state.awaiting!r} (reply: {reply!r})"
        )
        assert "udud" in reply.lower(), f"Expected jba boundary_self_existing_confirm text, got: {reply!r}"
        print("1a. BOUNDARY with an existing parcel -> boundary_self_confirm (jba reply):", "OK")

        reply_nam = _send(db, CHAT_BOUNDARY_CONFIRM, "NAM")
        state = db.query(models.TelegramConversationState).filter_by(chat_id=CHAT_BOUNDARY_CONFIRM).first()
        assert state.awaiting is None, f"NAM should resolve the gate (awaiting=None), got {state.awaiting!r}"
        assert "draw-boundary?token=" in reply_nam, f"Expected a fresh draw link after NAM, got: {reply_nam!r}"
        print("1b. 'NAM' accepted -> minted link, awaiting cleared:", "OK")
        print("    reply:", reply_nam)

        # Re-trigger the same gate and confirm English YES produces the
        # identical reply template (only the one-time token differs).
        _send(db, CHAT_BOUNDARY_CONFIRM, "BOUNDARY")
        reply_yes = _send(db, CHAT_BOUNDARY_CONFIRM, "YES")
        template_nam = reply_nam.split("token=")[0]
        template_yes = reply_yes.split("token=")[0]
        assert template_nam == template_yes, (
            f"NAM and YES produced different reply templates:\n  NAM: {template_nam!r}\n  YES: {template_yes!r}"
        )
        print("1c. 'NAM' reply template identical to 'YES' reply template:", "OK")

        # And LA behaves identically to NO (both clear awaiting -- the
        # gate's next_awaiting is None on a cancel, "boundary_self_start"
        # there is the logged *intent* string, not the next state).
        _send(db, CHAT_BOUNDARY_CONFIRM, "BOUNDARY")
        reply_la = _send(db, CHAT_BOUNDARY_CONFIRM, "LA")
        state = db.query(models.TelegramConversationState).filter_by(chat_id=CHAT_BOUNDARY_CONFIRM).first()
        assert state.awaiting is None, f"LA should cancel like NO (awaiting=None), got awaiting={state.awaiting!r}"
        assert "gofulu" in reply_la.lower(), f"Expected jba boundary_self_cancelled text, got: {reply_la!r}"
        reply_no = _send(db, CHAT_BOUNDARY_CONFIRM, "BOUNDARY")  # re-trigger the gate once more
        reply_no = _send(db, CHAT_BOUNDARY_CONFIRM, "NO")
        assert reply_la == reply_no, f"LA and NO produced different replies:\n  LA: {reply_la!r}\n  NO: {reply_no!r}"
        print("1d. 'LA' accepted -> cancelled identically to 'NO':", "OK")

        # --- Scenario 2: UDUD and HUDUD both match BOUNDARY ------------ #
        steward_b = _make_steward(db, CHAT_BOUNDARY_ALIAS, TEST_PHONE_B, "Test Farmer B")
        db.commit()  # no parcel -- bare command mints a link immediately, no confirm gate

        reply_udud = _send(db, CHAT_BOUNDARY_ALIAS, "UDUD")
        assert "draw-boundary?token=" in reply_udud, f"Expected 'UDUD' to route to BOUNDARY, got: {reply_udud!r}"
        print("2a. 'UDUD' routes to BOUNDARY -> draw link:", "OK")

        reply_hudud = _send(db, CHAT_BOUNDARY_ALIAS, "HUDUD")
        assert "draw-boundary?token=" in reply_hudud, f"Expected 'HUDUD' to route to BOUNDARY, got: {reply_hudud!r}"
        print("2b. 'HUDUD' routes to BOUNDARY -> draw link:", "OK")

        assert reply_udud.split("token=")[0] == reply_hudud.split("token=")[0], (
            "UDUD and HUDUD produced different reply templates"
        )
        print("2c. 'UDUD' and 'HUDUD' reply templates identical:", "OK")

        # --- Scenario 3: bare SEJILU in onboard_name routes like REGISTER #
        reply = _send(db, CHAT_ONBOARD_SEJILU, "hello")
        state = db.query(models.TelegramConversationState).filter_by(chat_id=CHAT_ONBOARD_SEJILU).first()
        assert state is not None and state.awaiting == "onboard_name", (
            f"Setup failed: expected onboard_name, got {state.awaiting if state else None!r} (reply: {reply!r})"
        )
        print("3a. First contact -> onboard_name:", "OK")

        reply_sejilu = _send(db, CHAT_ONBOARD_SEJILU, "Sejilu")
        junk = db.query(models.LandSteward).filter_by(telegram_chat_id=CHAT_ONBOARD_SEJILU).first()
        assert junk is None, f"BUG: 'Sejilu' was stored as a name -- full_name={junk.full_name if junk else None!r}"
        state = db.query(models.TelegramConversationState).filter_by(chat_id=CHAT_ONBOARD_SEJILU).first()
        assert state.awaiting != "onboard_phone", "BUG: advanced to onboard_phone after bare 'Sejilu'"

        # Control: an identical fresh onboarding chat sent the English
        # 'Register' instead. An unlinked chat has no preferred_language
        # to read yet, so lang defaults to English either way (see
        # handle_update's `lang = ... if steward else DEFAULT_LANGUAGE`)
        # -- the invariant under test isn't the reply's language, it's
        # that SEJILU is recognized as the SAME command as REGISTER.
        _send(db, CHAT_ONBOARD_REGISTER, "hello")
        reply_register = _send(db, CHAT_ONBOARD_REGISTER, "Register")
        assert reply_sejilu == reply_register, (
            f"'Sejilu' and 'Register' produced different replies:\n  Sejilu: {reply_sejilu!r}\n  Register: {reply_register!r}"
        )
        print("3b. Bare 'Sejilu' as name reply -> not stored, reply identical to bare 'Register':", "OK")
        print("    reply:", reply_sejilu)

        # And with a trailing phone number, same as REGISTER <phone>.
        _send(db, CHAT_ONBOARD_SEJILU, "hello again")
        reply_sejilu_phone = _send(db, CHAT_ONBOARD_SEJILU, f"Sejilu {TEST_PHONE_ONBOARD}")
        junk = db.query(models.LandSteward).filter_by(telegram_chat_id=CHAT_ONBOARD_SEJILU).first()
        assert junk is None, f"BUG: 'Sejilu {TEST_PHONE_ONBOARD}' was stored as a name"

        _send(db, CHAT_ONBOARD_REGISTER, "hello once more")
        reply_register_phone = _send(db, CHAT_ONBOARD_REGISTER, f"Register {TEST_PHONE_ONBOARD}")
        assert reply_sejilu_phone == reply_register_phone, (
            f"'Sejilu <phone>' and 'Register <phone>' produced different replies:\n"
            f"  Sejilu: {reply_sejilu_phone!r}\n  Register: {reply_register_phone!r}"
        )
        print(f"3c. 'Sejilu {TEST_PHONE_ONBOARD}' as name reply -> not stored, reply identical to 'Register <phone>':", "OK")
        print("    reply:", reply_sejilu_phone)

        print("\nALL CHECKS PASSED.")
    finally:
        before = (
            db.query(models.LandSteward).filter(
                models.LandSteward.telegram_chat_id.in_(ALL_TEST_CHAT_IDS)
            ).count()
            + db.query(models.TelegramConversationState).filter(
                models.TelegramConversationState.chat_id.in_(ALL_TEST_CHAT_IDS)
            ).count()
            + db.query(models.InboundMessage).filter(
                models.InboundMessage.external_chat_id.in_(ALL_TEST_CHAT_IDS)
            ).count()
            + db.query(models.ParcelDrawToken).filter(
                models.ParcelDrawToken.originating_chat_id.in_(ALL_TEST_CHAT_IDS)
            ).count()
        )
        _cleanup(db)
        db.close()
        # Fresh session for the final confirmation query -- proves
        # cleanup actually committed, not just that the same in-memory
        # session thinks it did.
        confirm_db = SessionLocal()
        try:
            remaining_confirmed = (
                confirm_db.query(models.LandSteward).filter(
                    models.LandSteward.telegram_chat_id.in_(ALL_TEST_CHAT_IDS)
                ).count()
                + confirm_db.query(models.TelegramConversationState).filter(
                    models.TelegramConversationState.chat_id.in_(ALL_TEST_CHAT_IDS)
                ).count()
                + confirm_db.query(models.InboundMessage).filter(
                    models.InboundMessage.external_chat_id.in_(ALL_TEST_CHAT_IDS)
                ).count()
                + confirm_db.query(models.ParcelDrawToken).filter(
                    models.ParcelDrawToken.originating_chat_id.in_(ALL_TEST_CHAT_IDS)
                ).count()
            )
        finally:
            confirm_db.close()
        print(f"Cleanup: {before} row(s) found and removed across test chat_ids; {remaining_confirmed} remain (fresh-session check).")
        assert remaining_confirmed == 0, "Cleanup incomplete -- test data still present."


if __name__ == "__main__":
    run()
