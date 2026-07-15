"""
Telegram inbound handling — the platform's first two-way channel.
Everything in dispatch.py is outbound-tracking only; this module is the
other direction: parsing what a farmer actually sent back, matched to a
real land_steward via telegram_chat_id, and answering with real data —
not placeholder replies. See db/schema.sql migration note for the
inbound_message / telegram_chat_id design.

Intent set is deliberately small (REGISTER, PRICE, STATUS) to prove the
pattern, not attempt natural-language understanding. A numbered menu
(USSD-style, matching this platform's accessibility principles) sits on
top of those same three intents for users who don't type commands --
REGISTER <phone>/PRICE <crop>/STATUS keep working unchanged for anyone
who still types them directly.

Chat-based registration (STAFF/NEWFARMER, added alongside the
authorized_operator table -- see db/schema.sql migration note): a
staff-only intent set that can create a brand-new land_steward, gated by
_get_authorized_operator() -- one authorization mechanism, not a
role-based system. Self-service farmers linked via REGISTER never reach
these; that table is populated only by an admin action
(POST /api/authorized-operators), never by a chat message.

BOUNDARY is the one intent both sides can reach, on two structurally
distinct paths: an authorized operator's BOUNDARY <phone> hands off a
drawing for whichever farmer they name (_handle_boundary), while an
already-linked farmer's bare BOUNDARY resolves their own record purely
from telegram_chat_id (_handle_boundary_self) -- that function takes no
args parameter at all, so there is no code path where it could ever act
on someone else's identity, even if a phone number was typed after it.
A dual-role chat (both authorized operator and linked farmer) always
takes the staff path on bare BOUNDARY, same precedent NEWFARMER already
set by checking _get_authorized_operator() first; the self-service path
only activates for chats that are farmer-only.

Language: every user-facing string is sourced from
app/services/telegram_strings.py, not hardcoded here. Farmer-facing
replies (REGISTER, PRICE, STATUS, the numbered menu) are shown in the
chat's land_steward.preferred_language once linked (English before
that -- there's nothing to read a preference from yet). Staff-only
flows (STAFF/NEWFARMER/BOUNDARY, including their refusal messages) stay
English-only, deliberately: authorized_operator is admin-populated and
that population already works in English elsewhere (the dashboard) --
extending translation there is scope without a demonstrated need. See
telegram_strings.py's own docstring for why Latin script (translated
string tables), not Arabic/RTL rendering, and why 'jba' entries are
still None placeholders rather than invented translations.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import models
from app.services.steward_registration import create_steward, find_possible_duplicate, normalize_phone
from app.services.telegram_strings import get_string, language_code_for, DEFAULT_LANGUAGE

CANCEL_WORDS = {"MENU", "0"}

# How long a BOUNDARY hand-off link stays valid. Short enough that a
# leaked/forgotten link is a small window, long enough that a staffer
# can walk to the farmer's plot with a phone before it expires.
DRAW_TOKEN_EXPIRY_MINUTES = 30

FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://localhost:5173")

# Keys are matched against raw_text.strip().lower(), so this covers both
# the numbered menu and someone just typing the word -- "female"/"Female"/
# "FEMALE" all normalize to the same lookup. Matching logic, not display
# text -- unlike the gender MENU prompt itself, this never goes through
# telegram_strings (a farmer's typed answer isn't translated, it's parsed).
GENDER_CHOICES = {
    "1": "female", "female": "female",
    "2": "male", "male": "male",
    "3": "other", "other": "other",
    "4": "prefer_not_to_say", "prefer not to say": "prefer_not_to_say", "prefer_not_to_say": "prefer_not_to_say",
}


def _find_steward_by_chat(db: Session, chat_id: str):
    return db.query(models.LandSteward).filter_by(telegram_chat_id=chat_id).first()


def _get_authorized_operator(db: Session, chat_id: str):
    """
    The single gate both staff-only capabilities (NEWFARMER, BOUNDARY)
    check. Returns the active, linked AuthorizedOperator for this chat,
    or None -- callers refuse clearly with the staff_auth_required
    string when this is None, never silently falling back to the
    farmer menu.
    """
    operator = db.query(models.AuthorizedOperator).filter_by(telegram_chat_id=chat_id).first()
    if operator and operator.is_active:
        return operator
    return None


def _get_conversation_state(db: Session, chat_id: str) -> models.TelegramConversationState:
    state = db.query(models.TelegramConversationState).filter_by(chat_id=chat_id).first()
    if not state:
        state = models.TelegramConversationState(chat_id=chat_id, awaiting=None, context={})
        db.add(state)
        db.flush()
    return state


def _crop_menu_text(db: Session, lang: str = DEFAULT_LANGUAGE) -> str:
    crops = db.query(models.CropDictionaryEntry).order_by(models.CropDictionaryEntry.crop_name).all()
    # Crop names are data (crop_dictionary_entry.crop_name, a real lookup
    # key elsewhere in the system), never translated -- only the "Which
    # crop?" header comes from the string table.
    lines = [f"{i}. {crop.crop_name}" for i, crop in enumerate(crops, start=1)]
    return get_string("crop_menu_header", lang) + "\n" + "\n".join(lines)


def _resolve_crop_reply(db: Session, raw_text: str):
    """
    Matches raw_text against the live crop list, by menu position or by
    typed name -- returns the crop_name string _handle_price() expects,
    or None if it matches neither.
    """
    crops = db.query(models.CropDictionaryEntry).order_by(models.CropDictionaryEntry.crop_name).all()
    text = raw_text.strip()
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(crops):
            return crops[index].crop_name
        return None
    name = text.lower()
    if any(crop.crop_name == name for crop in crops):
        return name
    return None


def _handle_register(db: Session, chat_id: str, args: str, lang: str = DEFAULT_LANGUAGE):
    phone = normalize_phone(args)
    if not phone:
        return "register", {}, get_string("register_usage", lang)

    steward = db.query(models.LandSteward).filter_by(phone_number=phone).first()
    if not steward:
        return (
            "register", {"phone": phone},
            get_string("register_not_found", lang),
        )

    if steward.telegram_chat_id and steward.telegram_chat_id != chat_id:
        return (
            "register", {"phone": phone},
            get_string("register_phone_linked_elsewhere", lang),
        )

    # The symmetric check: land_steward.telegram_chat_id is UNIQUE, so a
    # chat already linked to a DIFFERENT steward (found here by chat_id
    # rather than by phone) would hit that constraint at commit time if
    # not caught first -- surfaced live in testing 2026-07-14 as an
    # uncaught psycopg2.errors.UniqueViolation that crashed the poller
    # process outright. The check above only ever validated from the
    # phone/steward side; this is the other direction.
    existing_link = db.query(models.LandSteward).filter_by(telegram_chat_id=chat_id).first()
    if existing_link and existing_link.id != steward.id:
        return (
            "register", {"phone": phone},
            get_string("register_chat_linked_elsewhere", lang, name=existing_link.full_name),
        )

    steward.telegram_chat_id = chat_id
    # steward here is freshly resolved by phone, not necessarily the same
    # record `lang` (passed by the caller) was derived from -- use its
    # own preferred_language for this specific confirmation rather than
    # the ambient `lang`, since we now know exactly who we're talking to.
    return (
        "register", {"phone": phone},
        get_string("register_linked", language_code_for(steward.preferred_language), name=steward.full_name),
    )


def _handle_staff_link(db: Session, chat_id: str, args: str):
    """
    Links a Telegram chat to an authorized_operator row -- same pattern
    as _handle_register above, against authorized_operator instead of
    land_steward. Only succeeds if an admin already put this phone
    number on the table (POST /api/authorized-operators); this command
    can never create that row itself. English-only throughout, no lang
    param -- see module docstring's staff-flow scope note.
    """
    phone = normalize_phone(args)
    if not phone:
        return "staff_link", {}, get_string("staff_usage")

    operator = db.query(models.AuthorizedOperator).filter_by(phone_number=phone).first()
    if not operator:
        return (
            "staff_link", {"phone": phone},
            get_string("staff_not_found"),
        )
    if not operator.is_active:
        return (
            "staff_link", {"phone": phone},
            get_string("staff_suspended"),
        )
    if operator.telegram_chat_id and operator.telegram_chat_id != chat_id:
        return (
            "staff_link", {"phone": phone},
            get_string("staff_phone_linked_elsewhere"),
        )

    operator.telegram_chat_id = chat_id
    return (
        "staff_link", {"phone": phone},
        get_string("staff_linked", name=operator.full_name),
    )


def _handle_price(db: Session, crop_arg: str, lang: str = DEFAULT_LANGUAGE):
    crop_name = crop_arg.strip().lower()
    if not crop_name:
        return "price_lookup", {}, get_string("price_usage", lang)

    crop = db.query(models.CropDictionaryEntry).filter_by(crop_name=crop_name).first()
    if not crop:
        return "price_lookup", {"crop": crop_name}, get_string("price_crop_not_tracked", lang, crop=crop_name)

    entry = (
        db.query(models.PriceBoardEntry)
        .filter_by(crop_id=crop.id)
        .order_by(models.PriceBoardEntry.recorded_at.desc())
        .first()
    )
    if not entry:
        return "price_lookup", {"crop": crop_name}, get_string("price_no_price_yet", lang, crop=crop_name)

    reply = get_string(
        "price_result", lang,
        crop=crop_name.capitalize(), price=entry.price_ssp, unit=entry.unit,
        location=entry.market_location, date=entry.recorded_at.strftime('%Y-%m-%d'),
    )
    return "price_lookup", {"crop": crop_name}, reply


def _handle_status(steward, lang: str = DEFAULT_LANGUAGE):
    if not steward:
        return (
            "status_check", {},
            get_string("status_unregistered", lang),
        )
    coop = steward.cooperative_name or "no cooperative on file"
    # `steward` here is the exact object `lang` was already derived from
    # by the caller -- no need to re-derive from steward.preferred_language.
    reply = get_string("status_registered", lang, name=steward.full_name, coop=coop)
    return "status_check", {}, reply


def _mint_draw_token(db: Session, chat_id: str, steward) -> str:
    """
    Mints a single-use, time-limited parcel_draw_token for `steward`,
    originating from `chat_id`. Shared by both the staff hand-off path
    (_handle_boundary) and the self-service path (_handle_boundary_self)
    -- extracted so the token/draw-page/confirmation-push-back machinery
    genuinely has one implementation, not two copies that could drift.
    Nothing about the token or the draw page it authorizes assumes a
    staff initiator: it carries steward_id + originating_chat_id only,
    and app/routers/parcels.py's confirmation send just replies to
    whichever chat_id minted it.
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=DRAW_TOKEN_EXPIRY_MINUTES)
    db.add(models.ParcelDrawToken(
        token=token,
        steward_id=steward.id,
        originating_chat_id=chat_id,
        expires_at=expires_at,
    ))
    return token


def _handle_boundary(db: Session, chat_id: str, args: str, context: dict):
    """
    Staff hand-off: mints a draw token and replies with the web link for
    the given steward -- resolved either by phone number, or (bare
    "BOUNDARY", no args) by whichever farmer NEWFARMER most recently
    created in this same chat. English-only throughout -- staff flow,
    see module docstring.

    Mutates `context` in place, popping "last_created_steward_id" the
    moment it's read (whether or not the lookup succeeds) -- caller
    (handle_update) writes the mutated dict back to state.context. This
    is a single-use hand-off, not a standing pointer: confirmed live
    2026-07-15 that without this, a bare BOUNDARY sent long after the
    fact (with unrelated messages -- even a bare "MENU", which doesn't
    reset state.context, only "DONE" does) silently re-resolved to
    whichever farmer NEWFARMER had created *last*, not the one the
    sender actually meant.
    """
    phone = normalize_phone(args)
    if phone:
        steward = db.query(models.LandSteward).filter_by(phone_number=phone).first()
        if not steward:
            return "boundary_start", {"phone": phone}, get_string("boundary_no_farmer_found", phone=phone)
    else:
        last_id = context.pop("last_created_steward_id", None)
        steward = db.query(models.LandSteward).filter_by(id=last_id).first() if last_id else None
        if not steward:
            return "boundary_start", {}, get_string("boundary_usage")

    token = _mint_draw_token(db, chat_id, steward)
    link = f"{FRONTEND_BASE_URL}/draw-boundary?token={token}"
    reply = get_string(
        "boundary_link",
        name=steward.full_name, minutes=DRAW_TOKEN_EXPIRY_MINUTES, link=link,
    )
    return "boundary_start", {"steward_id": steward.id}, reply


def _handle_boundary_self(db: Session, chat_id: str, steward, lang: str = DEFAULT_LANGUAGE):
    """
    Self-service BOUNDARY for an already-linked farmer. Deliberately has
    no `args` parameter -- `steward` is resolved by the caller purely
    from chat_id (the same _find_steward_by_chat lookup STATUS already
    uses), so there is no line of code in this function that could ever
    parse or act on a phone number, even if one was typed after
    "BOUNDARY". This is the non-negotiable constraint enforced
    structurally, not behaviorally.

    Returns (next_awaiting, intent, params, reply) -- next_awaiting is
    "boundary_self_confirm" when an existing parcel needs a YES/NO gate
    first, None otherwise (link sent immediately, or nothing left
    pending).
    """
    existing = (
        db.query(models.Parcel)
        .filter_by(steward_id=steward.id)
        .order_by(models.Parcel.created_at.desc())
        .first()
    )
    if existing is not None:
        acres = f"{existing.area_acres:.2f}" if existing.area_acres is not None else "area pending"
        return (
            "boundary_self_confirm", "boundary_self_start", {"steward_id": steward.id},
            get_string("boundary_self_existing_confirm", lang, acres=acres),
        )

    token = _mint_draw_token(db, chat_id, steward)
    link = f"{FRONTEND_BASE_URL}/draw-boundary?token={token}"
    reply = get_string("boundary_self_link", lang, minutes=DRAW_TOKEN_EXPIRY_MINUTES, link=link)
    return None, "boundary_start", {"steward_id": steward.id}, reply


def _handle_boundary_self_confirm(db: Session, chat_id: str, raw_text: str, lang: str):
    """
    YES/NO gate after _handle_boundary_self found an existing parcel --
    same shape as _handle_new_farmer_dup_confirm. No context to carry:
    steward is re-resolved fresh from chat_id on YES, same as everywhere
    else in this module.
    """
    choice = raw_text.strip().upper()
    if choice == "YES":
        steward = _find_steward_by_chat(db, chat_id)
        token = _mint_draw_token(db, chat_id, steward)
        link = f"{FRONTEND_BASE_URL}/draw-boundary?token={token}"
        reply = get_string("boundary_self_link", lang, minutes=DRAW_TOKEN_EXPIRY_MINUTES, link=link)
        return None, "boundary_start", {"steward_id": steward.id}, reply
    if choice == "NO":
        return None, "boundary_self_start", {}, get_string("boundary_self_cancelled", lang)
    return (
        "boundary_self_confirm", "boundary_self_start", {},
        get_string("boundary_self_existing_confirm_retry", lang),
    )


def _handle_new_farmer_name(raw_text: str, context: dict):
    name = raw_text.strip()
    if not name:
        return None, "new_farmer_name", get_string("new_farmer_name_prompt")
    context["full_name"] = name
    return context, "new_farmer_phone", get_string("new_farmer_phone_prompt")


def _handle_new_farmer_phone(db: Session, raw_text: str, context: dict):
    phone = normalize_phone(raw_text)
    if not phone:
        return None, "new_farmer_phone", get_string("new_farmer_phone_usage")
    context["phone_number"] = phone
    duplicate = find_possible_duplicate(db, phone)
    if duplicate:
        return (
            context, "new_farmer_dup_confirm",
            get_string("new_farmer_dup_confirm", name=duplicate.full_name),
        )
    return context, "new_farmer_gender", get_string("gender_menu")


def _handle_new_farmer_dup_confirm(raw_text: str, context: dict):
    choice = raw_text.strip().upper()
    if choice == "YES":
        return context, "new_farmer_gender", get_string("gender_menu")
    if choice == "NO":
        return None, None, get_string("new_farmer_cancelled")
    return context, "new_farmer_dup_confirm", get_string("new_farmer_dup_confirm_retry")


def _handle_new_farmer_gender(db: Session, raw_text: str, context: dict, operator):
    choice = raw_text.strip().lower()
    if choice == "skip":
        gender = None
    elif choice in GENDER_CHOICES:
        gender = GENDER_CHOICES[choice]
    else:
        return context, "new_farmer_gender", get_string("gender_not_recognized", menu=get_string("gender_menu"))

    data = {
        "role": "smallholder_farmer",
        "full_name": context["full_name"],
        "phone_number": context["phone_number"],
        "gender": gender,
        "registered_by": operator.full_name,
        "registered_offline": False,
    }
    steward, _ = create_steward(db, data, force_create=True)
    reply = get_string("new_farmer_created", name=steward.full_name)
    return {"last_created_steward_id": steward.id}, None, reply


# ----------------------------------------------------------------------- #
# Self-service onboarding (unregistered, unlinked chat's first contact --
# see handle_update's catch-all/digit-shortcut branches). Mirrors the
# NEWFARMER step machinery above ((context, next_awaiting, reply) shape)
# but as separate functions, not reused ones: these take no `operator`
# (there isn't one), collect two extra fields NEWFARMER never asks about
# (is_youth, has_disability/disability_notes -- real land_steward columns
# that were previously only ever written as their silent defaults), and
# resolve a duplicate-phone hit more conservatively than NEWFARMER's
# staff-supervised YES/NO -- there's no human vouching for "two people
# share a phone" here, so self-service either links to the existing
# unlinked record or refuses and defers to staff; it never force-creates
# a second record the way create_steward(..., force_create=True) would
# let NEWFARMER do.
# ----------------------------------------------------------------------- #

def _handle_onboard_name(raw_text: str, context: dict):
    name = raw_text.strip()
    if not name:
        return None, "onboard_name", get_string("onboard_name_prompt")
    context["full_name"] = name
    return context, "onboard_phone", get_string("onboard_phone_prompt")


def _handle_onboard_phone(db: Session, chat_id: str, raw_text: str, context: dict):
    phone = normalize_phone(raw_text)
    if not phone:
        return None, "onboard_phone", get_string("new_farmer_phone_usage")
    context["phone_number"] = phone
    duplicate = find_possible_duplicate(db, phone)
    if duplicate:
        if duplicate.telegram_chat_id and duplicate.telegram_chat_id != chat_id:
            # Already claimed by a different chat -- refuse immediately,
            # don't offer a YES/NO "link" prompt for something that can
            # never succeed. Same shape as _handle_register's own
            # phone-linked-elsewhere refusal.
            return None, None, get_string("register_phone_linked_elsewhere")
        context["duplicate_steward_id"] = duplicate.id
        return (
            context, "onboard_link_existing_confirm",
            get_string("onboard_link_existing_confirm", name=duplicate.full_name),
        )
    return context, "onboard_gender", get_string("gender_menu")


def _handle_onboard_link_existing_confirm(db: Session, chat_id: str, raw_text: str, context: dict):
    """
    The conservative duplicate-resolution gate: YES links THIS chat to
    the already-existing (but not yet Telegram-linked) record -- reusing
    _handle_register's own phone/chat collision checks rather than new
    matching logic -- never creates a second record. NO refuses outright
    and defers to staff; there is no "create anyway" option here, unlike
    NEWFARMER's confirm gate, because nobody is vouching that this is
    genuinely a different person.

    Returns (context_or_None, next_awaiting, reply). On YES, next_awaiting
    is _handle_boundary_self's own return value (None or
    "boundary_self_confirm"), not an onboarding state -- the onboarding
    flow itself is finished the moment linking succeeds.
    """
    choice = raw_text.strip().upper()
    duplicate_id = context.get("duplicate_steward_id")
    if choice == "YES":
        existing = db.query(models.LandSteward).filter_by(id=duplicate_id).first()
        if not existing:
            return None, None, get_string("register_not_found")
        if existing.telegram_chat_id and existing.telegram_chat_id != chat_id:
            # Someone else linked this exact record to a different chat
            # in the gap between the phone step and this confirmation --
            # same collision _handle_register already guards against.
            return None, None, get_string("register_phone_linked_elsewhere")
        existing.telegram_chat_id = chat_id
        existing_lang = language_code_for(existing.preferred_language)
        next_awaiting, _, _, boundary_reply = _handle_boundary_self(db, chat_id, existing, existing_lang)
        reply = get_string("register_linked", existing_lang, name=existing.full_name) + "\n\n" + boundary_reply
        return None, next_awaiting, reply
    if choice == "NO":
        existing = db.query(models.LandSteward).filter_by(id=duplicate_id).first()
        name = existing.full_name if existing else "an existing record"
        return None, None, get_string("onboard_link_existing_needs_staff", name=name)
    return context, "onboard_link_existing_confirm", get_string("onboard_link_existing_confirm_retry")


def _handle_onboard_gender(raw_text: str, context: dict):
    choice = raw_text.strip().lower()
    if choice == "skip":
        gender = None
    elif choice in GENDER_CHOICES:
        gender = GENDER_CHOICES[choice]
    else:
        return context, "onboard_gender", get_string("gender_not_recognized", menu=get_string("gender_menu"))
    context["gender"] = gender
    return context, "onboard_youth", get_string("onboard_youth_prompt")


def _handle_onboard_youth(raw_text: str, context: dict):
    choice = raw_text.strip().upper()
    if choice == "SKIP":
        context["is_youth"] = None  # unknown/not-asserted, same semantics as gender's SKIP
    elif choice == "YES":
        context["is_youth"] = True
    elif choice == "NO":
        context["is_youth"] = False
    else:
        return (
            context, "onboard_youth",
            get_string("onboard_choice_not_recognized", menu=get_string("onboard_youth_prompt")),
        )
    return context, "onboard_disability", get_string("onboard_disability_prompt")


def _handle_onboard_disability(db: Session, chat_id: str, raw_text: str, context: dict):
    choice = raw_text.strip().upper()
    if choice == "YES":
        context["has_disability"] = True
        return context, "onboard_disability_notes", get_string("onboard_disability_notes_prompt")
    if choice in ("NO", "SKIP"):
        context["has_disability"] = False if choice == "NO" else None
        context["disability_notes"] = None
        next_awaiting, reply = _create_self_onboarded_steward(db, chat_id, context)
        return None, next_awaiting, reply
    return (
        context, "onboard_disability",
        get_string("onboard_choice_not_recognized", menu=get_string("onboard_disability_prompt")),
    )


def _handle_onboard_disability_notes(db: Session, chat_id: str, raw_text: str, context: dict):
    """
    Free text, never validated/re-prompted -- SKIP or an empty reply
    both leave disability_notes unset. Never a forced field.
    """
    notes = raw_text.strip()
    context["disability_notes"] = None if (not notes or notes.upper() == "SKIP") else notes
    next_awaiting, reply = _create_self_onboarded_steward(db, chat_id, context)
    return None, next_awaiting, reply


def _create_self_onboarded_steward(db: Session, chat_id: str, context: dict):
    """
    Shared completion step reached from both disability-question exits
    (NO/SKIP finishes immediately; YES finishes one step later, after
    notes). Two deltas from _handle_new_farmer_gender's create_steward()
    call this is modeled on:

    1. telegram_chat_id is set explicitly here. NEWFARMER never sets it
       because staff create a record for someone ELSE who links later
       via REGISTER; self-onboarding is the chatting person creating
       their OWN record, so without this, _find_steward_by_chat would
       still return None right after creation and nothing downstream
       (including the very next message) could resolve them.
    2. force_create=False, never True. The phone-step duplicate check
       already resolved (link-existing or refuse) before this could ever
       be reached in the normal case; force_create=False here is a
       defensive re-check for the rare race where a second chat
       completes its own onboarding with the same phone in the gap
       between this chat's phone step and this final step (the poller
       is single-threaded but processes other chats' messages in
       between this chat's own multi-turn replies) -- if that happens,
       this refuses and defers to staff, same as every other duplicate
       outcome in this flow, rather than silently force-creating.
    """
    data = {
        "role": "smallholder_farmer",
        "full_name": context["full_name"],
        "phone_number": context["phone_number"],
        "gender": context.get("gender"),
        "is_youth": context.get("is_youth"),
        "has_disability": context.get("has_disability"),
        "disability_notes": context.get("disability_notes"),
        "registered_by": "self-service (Telegram)",
        "registered_offline": False,
        "telegram_chat_id": chat_id,
    }
    steward, duplicate = create_steward(db, data, force_create=False)
    if steward is None:
        return None, get_string("onboard_link_existing_needs_staff", name=duplicate.full_name)
    steward_lang = language_code_for(steward.preferred_language)
    next_awaiting, _, _, boundary_reply = _handle_boundary_self(db, chat_id, steward, steward_lang)
    reply = get_string("onboard_created", steward_lang, name=steward.full_name) + "\n\n" + boundary_reply
    return next_awaiting, reply


# ----------------------------------------------------------------------- #
# Services menu (already-registered/linked farmer's fallback, replacing
# menu_text for this audience) -- see handle_update's catch-all/digit
# branches. Honest split: price/status/boundary reuse existing, already-
# shipped handlers; FarmLab and BoQ are real data read directly (never
# through the POST/PATCH routes that mutate them -- editing stays
# staff-only regardless of how the farmer's record was created, per the
# security boundary this whole redesign leaves untouched); extension
# advice has nothing real behind it anywhere in this codebase, so it's
# labeled "(coming soon)" in the menu itself rather than presented as
# a dead or silently-ignored option.
# ----------------------------------------------------------------------- #

# Real, verified top-level keys of ParcelDiagnostic.diagnostic (matches
# frontend/src/App.jsx's DIAGNOSTIC_CATEGORIES + the land_use block it
# renders separately) -- each maps to a list of fact dicts shaped like
# {code, title, value, unit, status, nature, description}.
FARMLAB_CATEGORIES = [
    ("land_use", "Land use"), ("climate", "Climate"), ("soil", "Soil"),
    ("water", "Water"), ("vegetation", "Vegetation"),
    ("topography", "Topography"), ("carbon", "Carbon"),
]

# Telegram's real cap is 4096 chars; sendMessage fails outright past it,
# and telegram_poller.py's per-update try/except would swallow that
# failure silently (no reply sent at all) -- a FarmLab diagnostic across
# 7 categories can genuinely run long, so this is a real guard, not
# defensive theater.
TELEGRAM_REPLY_CHAR_LIMIT = 3500


def _cap_reply(text: str) -> str:
    if len(text) <= TELEGRAM_REPLY_CHAR_LIMIT:
        return text
    return text[:TELEGRAM_REPLY_CHAR_LIMIT].rstrip() + "\n…(truncated — see the CORWADO dashboard for the full report)"


def _handle_services_menu(steward, lang: str = DEFAULT_LANGUAGE):
    return "services_menu_shown", {}, get_string("services_menu_text", lang)


def _handle_farmlab(db: Session, steward, lang: str = DEFAULT_LANGUAGE):
    """
    Cached-only -- never triggers a live agri-venture-v2 call from the
    chat path. get_diagnostic()/get_baseline() in app/routers/advisory.py
    can legitimately take up to 150s on a cold fetch (AGRIVENTURE_TIMEOUT_S),
    and telegram_poller.py is a single-threaded loop with no timeout
    around handle_update() -- a live call here would freeze every other
    farmer's messages for that whole window. If nothing is cached yet,
    this tells the farmer to ask staff or use the web dashboard instead
    of triggering one itself.
    """
    parcel = (
        db.query(models.Parcel)
        .filter_by(steward_id=steward.id)
        .order_by(models.Parcel.created_at.desc())
        .first()
    )
    if not parcel:
        return "farmlab_check", {}, get_string("no_boundary_yet", lang)

    diagnostic = db.query(models.ParcelDiagnostic).filter_by(parcel_id=parcel.id).first()
    if not diagnostic or not diagnostic.computed_at:
        return "farmlab_check", {}, get_string("farmlab_not_ready", lang)

    data = diagnostic.diagnostic or {}
    lines = [f"FarmLab report (as of {diagnostic.computed_at.strftime('%Y-%m-%d')}):"]
    for w in (data.get("warnings") or []):
        lines.append(f"⚠ {w}")
    for category_key, category_label in FARMLAB_CATEGORIES:
        for fact in (data.get(category_key) or []):
            value = fact.get("value")
            if value is None:
                continue
            unit = fact.get("unit") or ""
            title = fact.get("title") or category_label
            lines.append(f"{category_label} — {title}: {value}{(' ' + unit) if unit else ''}")

    season = (
        db.query(models.SeasonPlanting)
        .filter_by(parcel_id=parcel.id)
        .order_by(models.SeasonPlanting.created_at.desc())
        .first()
    )
    if season:
        crop = db.query(models.CropDictionaryEntry).filter_by(id=season.crop_id).first()
        # agriventure_crop_key gate matches get_baseline()'s own check --
        # only maize/moringa have a real biophysical score to show.
        if crop and crop.agriventure_crop_key:
            baseline = (
                db.query(models.ParcelCropBaseline)
                .filter_by(parcel_id=parcel.id, crop_id=crop.id)
                .first()
            )
            if baseline and baseline.suitability:
                s = baseline.suitability
                lines.append(
                    f"\n{crop.crop_name.capitalize()} suitability: "
                    f"{s.get('overall_classification', 'unknown')} (score {s.get('overall_score', '—')})"
                )

    return "farmlab_check", {"parcel_id": parcel.id}, _cap_reply("\n".join(lines))


def _handle_boq_summary(db: Session, steward, lang: str = DEFAULT_LANGUAGE):
    """
    Read-only: only ever queries input_requirement/input_financing_record
    directly (same direct-db.query() pattern this file already uses
    elsewhere), never calls the POST /requirements, PATCH /requirements,
    or POST /financing routes that mutate them -- editing BoQ costs and
    recording financing stay staff-only regardless of how the farmer's
    record was created, unrelated to and untouched by this change.
    """
    parcel = (
        db.query(models.Parcel)
        .filter_by(steward_id=steward.id)
        .order_by(models.Parcel.created_at.desc())
        .first()
    )
    if not parcel:
        return "boq_check", {}, get_string("no_boundary_yet", lang)

    season = (
        db.query(models.SeasonPlanting)
        .filter_by(parcel_id=parcel.id)
        .order_by(models.SeasonPlanting.created_at.desc())
        .first()
    )
    if not season:
        return "boq_check", {}, get_string("boq_no_season", lang)

    requirements = (
        db.query(models.InputRequirement)
        .filter_by(season_planting_id=season.id)
        .order_by(models.InputRequirement.created_at.asc())
        .all()
    )
    if not requirements:
        return "boq_check", {"season_planting_id": season.id}, get_string("boq_empty", lang)

    crop = db.query(models.CropDictionaryEntry).filter_by(id=season.crop_id).first()
    crop_name = crop.crop_name.capitalize() if crop else "your"
    season_label = season.season_label or (str(season.sowing_date) if season.sowing_date else "current")
    lines = [get_string("boq_header", lang, crop=crop_name, season_label=season_label)]
    total = 0.0
    for item in requirements:
        cost = float(item.total_cost_usd or 0)
        total += cost
        lines.append(f"- {item.item_name}: {item.quantity} {item.unit} @ ${item.unit_cost_usd}/unit = ${cost:.2f}")
    lines.append(f"Total: ${total:.2f}")

    # Same join _handle GET /api/inputs/financing?season_planting_id=
    # uses (app/routers/inputs.py) -- direct query, matching this file's
    # own established pattern, not an HTTP round-trip to its own API.
    financing = (
        db.query(models.InputFinancingRecord)
        .join(models.InputRequirement, models.InputFinancingRecord.input_requirement_id == models.InputRequirement.id)
        .filter(models.InputRequirement.season_planting_id == season.id)
        .order_by(models.InputFinancingRecord.financed_at.asc())
        .all()
    )
    lines.append("")
    if not financing:
        lines.append(get_string("boq_no_financing", lang))
    else:
        lines.append("Financing recorded:")
        for record in financing:
            financier = getattr(record.financier_type, "value", record.financier_type)
            lines.append(f"- {financier}: ${float(record.amount_usd):.2f} on {record.financed_at.strftime('%Y-%m-%d')}")

    return "boq_check", {"season_planting_id": season.id}, _cap_reply("\n".join(lines))


# Command keyword -> recognized token sequences (each a tuple of
# already-lowercased tokens). Single-token commands (REGISTER, PRICE,
# STATUS, STAFF, BOUNDARY, DONE) were already case-insensitive before
# this existed -- parts[0].upper() handles a single token fine regardless
# of case. NEWFARMER is the one that was actually broken: typed
# naturally as two words ("new farmer"), the old parts[0]-only check
# only ever saw "new", which matched nothing and silently fell through
# to the menu. Structured as a dict of alias lists (not just a NEWFARMER
# special case) so the same fix applies uniformly and any future
# multi-word alias is a one-line addition, not a new code path.
COMMAND_ALIASES = {
    "REGISTER": [("register",)],
    "PRICE": [("price",)],
    "STATUS": [("status",)],
    "STAFF": [("staff",)],
    "NEWFARMER": [("newfarmer",), ("new", "farmer")],
    "BOUNDARY": [("boundary",)],
    "DONE": [("done",)],
}


def _split_command(raw_text: str):
    """
    Case-insensitive, natural-phrasing-tolerant command matching against
    COMMAND_ALIASES above. Only the command KEYWORD is lowercased for
    comparison -- the returned args are sliced from the original,
    un-lowercased tokens, so a phone number, crop name, or farmer's name
    typed after the keyword keeps its original case. (A handler that
    needs case-insensitive argument matching already does its own
    lowering -- e.g. _handle_price already does crop_arg.strip().lower()
    -- this only fixes the keyword lookup itself, per the same
    "arguments aren't the keyword" boundary REGISTER/PRICE already
    relied on.)

    Returns (command, args); command is None if raw_text doesn't start
    with any recognized keyword (falls through to the numbered-menu /
    unrecognized-text handling in handle_update below, same as before).
    """
    tokens = raw_text.split()
    if not tokens:
        return None, ""
    lowered = [t.lower() for t in tokens]

    for command, aliases in COMMAND_ALIASES.items():
        for alias in aliases:
            n = len(alias)
            if tuple(lowered[:n]) == alias:
                return command, " ".join(tokens[n:])
    return None, ""


def handle_update(db: Session, update: dict) -> str:
    """
    Processes one Telegram getUpdates() message dict, logs it as an
    inbound_message row, and returns the reply text for the poller to
    send back via sendMessage. Returns "" if the update has no text
    message to act on (e.g. an edited_message or non-text update).
    """
    message = update.get("message")
    if not message or "text" not in message:
        return ""

    chat_id = str(message["chat"]["id"])
    raw_text = message["text"].strip()

    steward = _find_steward_by_chat(db, chat_id)
    state = _get_conversation_state(db, chat_id)
    context = dict(state.context or {})
    # Farmer-facing language for this exchange: the linked steward's own
    # preference if one exists, English otherwise (an unlinked chat has
    # no preference on file to read yet). Computed once per message --
    # see _handle_register's own note for the one place a handler
    # deliberately re-derives from a freshly-resolved steward instead.
    lang = language_code_for(steward.preferred_language) if steward else DEFAULT_LANGUAGE

    if state.awaiting and raw_text.upper() in CANCEL_WORDS:
        state.awaiting = None
        state.context = {}
        intent, params, reply = "menu_cancel", {}, get_string("menu_text", lang)
    elif state.awaiting == "phone_for_register":
        state.awaiting = None
        intent, params, reply = _handle_register(db, chat_id, raw_text, lang)
        steward = _find_steward_by_chat(db, chat_id)  # re-resolve: REGISTER may have just linked it
    elif state.awaiting == "crop_for_price":
        state.awaiting = None
        crop_name = _resolve_crop_reply(db, raw_text)
        if crop_name is None:
            intent, params, reply = (
                "price_lookup", {"raw": raw_text},
                get_string("crop_not_recognized", lang, menu=_crop_menu_text(db, lang)),
            )
            state.awaiting = "crop_for_price"  # still waiting -- re-prompt, don't drop the flow
        else:
            intent, params, reply = _handle_price(db, crop_name, lang)
    elif state.awaiting == "new_farmer_name":
        new_context, next_awaiting, reply = _handle_new_farmer_name(raw_text, context)
        state.context = new_context if new_context is not None else {}
        state.awaiting = next_awaiting
        intent, params = "new_farmer_step", {"step": "name"}
    elif state.awaiting == "new_farmer_phone":
        new_context, next_awaiting, reply = _handle_new_farmer_phone(db, raw_text, context)
        state.context = new_context if new_context is not None else {}
        state.awaiting = next_awaiting
        intent, params = "new_farmer_step", {"step": "phone"}
    elif state.awaiting == "new_farmer_dup_confirm":
        new_context, next_awaiting, reply = _handle_new_farmer_dup_confirm(raw_text, context)
        state.context = new_context if new_context is not None else {}
        state.awaiting = next_awaiting
        intent, params = "new_farmer_step", {"step": "dup_confirm"}
    elif state.awaiting == "onboard_name":
        new_context, next_awaiting, reply = _handle_onboard_name(raw_text, context)
        state.context = new_context if new_context is not None else {}
        state.awaiting = next_awaiting
        intent, params = "onboard_step", {"step": "name"}
    elif state.awaiting == "onboard_phone":
        new_context, next_awaiting, reply = _handle_onboard_phone(db, chat_id, raw_text, context)
        state.context = new_context if new_context is not None else {}
        state.awaiting = next_awaiting
        intent, params = "onboard_step", {"step": "phone"}
    elif state.awaiting == "onboard_link_existing_confirm":
        new_context, next_awaiting, reply = _handle_onboard_link_existing_confirm(db, chat_id, raw_text, context)
        state.context = new_context if new_context is not None else {}
        state.awaiting = next_awaiting
        steward = _find_steward_by_chat(db, chat_id)  # re-resolve: may have just linked
        intent, params = "onboard_step", {"step": "link_existing_confirm"}
    elif state.awaiting == "onboard_gender":
        new_context, next_awaiting, reply = _handle_onboard_gender(raw_text, context)
        state.context = new_context if new_context is not None else {}
        state.awaiting = next_awaiting
        intent, params = "onboard_step", {"step": "gender"}
    elif state.awaiting == "onboard_youth":
        new_context, next_awaiting, reply = _handle_onboard_youth(raw_text, context)
        state.context = new_context if new_context is not None else {}
        state.awaiting = next_awaiting
        intent, params = "onboard_step", {"step": "youth"}
    elif state.awaiting == "onboard_disability":
        new_context, next_awaiting, reply = _handle_onboard_disability(db, chat_id, raw_text, context)
        state.context = new_context if new_context is not None else {}
        state.awaiting = next_awaiting
        steward = _find_steward_by_chat(db, chat_id)  # re-resolve: creation may have just happened
        intent, params = "onboard_step", {"step": "disability"}
    elif state.awaiting == "onboard_disability_notes":
        new_context, next_awaiting, reply = _handle_onboard_disability_notes(db, chat_id, raw_text, context)
        state.context = new_context if new_context is not None else {}
        state.awaiting = next_awaiting
        steward = _find_steward_by_chat(db, chat_id)  # re-resolve: creation may have just happened
        intent, params = "onboard_step", {"step": "disability_notes"}
    elif state.awaiting == "boundary_self_confirm":
        next_awaiting, intent, params, reply = _handle_boundary_self_confirm(db, chat_id, raw_text, lang)
        state.awaiting = next_awaiting
    elif state.awaiting == "new_farmer_gender":
        operator = _get_authorized_operator(db, chat_id)
        if not operator:
            # Shouldn't happen (only NEWFARMER sets this awaiting state,
            # and that's gated) -- but if access was revoked mid-flow,
            # refuse rather than let a stale awaiting state finish the
            # create with no authorization behind it.
            state.awaiting = None
            state.context = {}
            intent, params, reply = "new_farmer_step", {"step": "gender"}, get_string("staff_auth_required")
        else:
            new_context, next_awaiting, reply = _handle_new_farmer_gender(db, raw_text, context, operator)
            state.context = new_context if new_context is not None else {}
            state.awaiting = next_awaiting
            intent, params = "new_farmer_step", {"step": "gender"}
    else:
        command, args = _split_command(raw_text)

        if command == "REGISTER":
            intent, params, reply = _handle_register(db, chat_id, args, lang)
            steward = _find_steward_by_chat(db, chat_id)  # re-resolve: REGISTER may have just linked it
        elif command == "PRICE":
            intent, params, reply = _handle_price(db, args, lang)
        elif command == "STATUS":
            intent, params, reply = _handle_status(steward, lang)
        elif command == "STAFF":
            intent, params, reply = _handle_staff_link(db, chat_id, args)
        elif command == "NEWFARMER":
            operator = _get_authorized_operator(db, chat_id)
            if not operator:
                intent, params, reply = "new_farmer_start", {}, get_string("staff_auth_required")
            else:
                state.awaiting = "new_farmer_name"
                state.context = {}
                intent, params, reply = "new_farmer_start", {}, get_string("new_farmer_name_prompt")
        elif command == "BOUNDARY":
            operator = _get_authorized_operator(db, chat_id)
            if operator:
                intent, params, reply = _handle_boundary(db, chat_id, args, context)
                state.context = context  # persists _handle_boundary's last_created_steward_id pop, if any
            elif steward:
                next_awaiting, intent, params, reply = _handle_boundary_self(db, chat_id, steward, lang)
                state.awaiting = next_awaiting
            else:
                intent, params, reply = "boundary_start", {}, get_string("status_unregistered", lang)
        elif command == "DONE":
            state.context = {}
            intent, params, reply = "menu_shown", {}, get_string("menu_text", lang)
        else:
            # Digit shortcuts and the catch-all are both registration-
            # status-aware, gated on this single operator lookup so a
            # dual-role chat (both authorized operator AND linked farmer
            # -- a real case in this database, not hypothetical) is
            # resolved once, consistently, rather than by two separately-
            # ordered checks. Operator wins first, matching the precedent
            # BOUNDARY already established ("a dual-role chat always
            # takes the staff path") -- a linked steward's "1"-"6" only
            # ever map to the new services menu when the chat is NOT
            # also staff.
            operator = _get_authorized_operator(db, chat_id)
            if operator and raw_text == "1":
                state.awaiting = "phone_for_register"
                intent, params, reply = "menu_select_register", {}, get_string("register_phone_prompt", lang)
            elif operator and raw_text == "2":
                state.awaiting = "crop_for_price"
                intent, params, reply = "menu_select_price", {}, _crop_menu_text(db, lang)
            elif operator and raw_text == "3":
                intent, params, reply = _handle_status(steward, lang)
            elif (not operator) and steward and raw_text == "1":
                state.awaiting = "crop_for_price"
                intent, params, reply = "menu_select_price", {}, _crop_menu_text(db, lang)
            elif (not operator) and steward and raw_text == "2":
                intent, params, reply = _handle_status(steward, lang)
            elif (not operator) and steward and raw_text == "3":
                intent, params, reply = _handle_farmlab(db, steward, lang)
            elif (not operator) and steward and raw_text == "4":
                intent, params, reply = _handle_boq_summary(db, steward, lang)
            elif (not operator) and steward and raw_text == "5":
                intent, params, reply = "extension_check", {}, get_string("extension_coming_soon", lang)
            elif (not operator) and steward and raw_text == "6":
                next_awaiting, intent, params, reply = _handle_boundary_self(db, chat_id, steward, lang)
                state.awaiting = next_awaiting
            elif (not operator) and (not steward) and raw_text == "1":
                state.awaiting = "phone_for_register"
                intent, params, reply = "menu_select_register", {}, get_string("register_phone_prompt", lang)
            elif (not operator) and (not steward) and raw_text == "2":
                state.awaiting = "crop_for_price"
                intent, params, reply = "menu_select_price", {}, _crop_menu_text(db, lang)
            elif (not operator) and (not steward) and raw_text == "3":
                intent, params, reply = _handle_status(steward, lang)
            else:
                # First-contact auto-detection (Change 1): reached only
                # once every command and digit shortcut above has
                # already failed to match -- REGISTER/STAFF/etc. are
                # never intercepted, so an authorized operator's
                # first-ever "STAFF <phone>" still links normally rather
                # than being swallowed into onboarding (both `steward`
                # and `operator` resolve identically -- None -- for a
                # staffer's very first message, before their chat is
                # linked; only the command content distinguishes them,
                # which is why this branch has to sit after command
                # parsing, not before it). Same operator-first precedence
                # as the digit shortcuts above.
                if operator:
                    intent, params, reply = "menu_shown", {"raw": raw_text}, get_string("menu_text", lang)
                elif steward:
                    intent, params, reply = _handle_services_menu(steward, lang)
                else:
                    state.awaiting = "onboard_name"
                    state.context = {}
                    intent, params, reply = "onboard_start", {}, get_string("onboard_welcome")

    db.add(models.InboundMessage(
        steward_id=steward.id if steward else None,
        channel="telegram",
        external_chat_id=chat_id,
        raw_text=raw_text,
        parsed_intent=intent,
        parsed_params=params,
        response_text=reply,
        processed_at=datetime.utcnow(),
    ))
    db.commit()

    return reply
