"""
Shared land_steward creation path.

Both POST /api/stewards (web dashboard) and the Telegram NEWFARMER flow
create a new farmer record -- this is the one place that happens, so
duplicate detection and field handling exist exactly once rather than
being reimplemented per caller. See db/schema.sql's authorized_operator
migration note for the chat-registration design this supports.
"""
import re
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app import models


# South Sudan's country code, used as the assumed target when a user
# types a LOCAL-format number (leading 0) rather than E.164 -- e.g.
# "0928004009" -> "+211928004009". This is a documented ASSUMPTION, not
# a detected fact: confirmed live in land_steward (2026-07-16) that
# CORWADO's data is NOT strictly South-Sudan-only -- a real farmer
# ("James otim") has a Kenyan +254 number on file. A bare local-format
# number is structurally ambiguous between countries (both are '0' + 9
# digits, no reliable way to tell them apart from the digits alone), so
# this can't be "detected" correctly in general. +211 was chosen
# because it matches CORWADO's primary operating geography (ToR:
# Western Bahr el Ghazal) and is what the reported STAFF-authorization
# lookup bug needed fixed. A non-South-Sudan number typed in LOCAL
# format (rather than already stored/typed as E.164) will still
# normalize wrong -- a pre-existing limitation, not one this
# introduces: James Otim's own number is already stored as E.164 and
# is untouched by this function either way (see the E.164 branch
# below).
SOUTH_SUDAN_COUNTRY_CODE = "+211"

# Plausible total-digit-count bounds (E.164's own max is 15 digits
# after the '+', ITU-T E.164 sec. 6; 7 is a generous floor -- shorter
# than any real mobile number in the countries CORWADO's data actually
# contains). Used to reject obvious junk ("New", "abc", a truncated
# number) as invalid rather than silently passing it through to a
# lookup that would fail identically to "not registered" -- see
# normalize_phone's docstring.
_MIN_PHONE_DIGITS = 7
_MAX_PHONE_DIGITS = 15
# South Sudan/Kenya local numbers are '0' + 9 digits (confirmed against
# every local-format number currently in land_steward/
# authorized_operator) -- narrower than the general E.164 bound above
# since this branch is specifically converting to a 3-digit country
# code + 9-digit subscriber number, not passing an arbitrary length
# through unchanged.
_LOCAL_SUBSCRIBER_DIGITS = 9


def normalize_phone(raw: str) -> str:
    """
    Normalizes user-typed phone input into a single canonical form so a
    lookup (find_possible_duplicate, _handle_staff_link, etc.) and the
    value actually stored at registration always compare equal --
    fixing a real bug confirmed live 2026-07-16: STAFF 0928004009
    reported "No staff authorization found" for an operator whose row
    was seeded as +211928004009, because this function previously only
    stripped whitespace/hyphens and never reconciled local vs. E.164
    format at all.

    - Already E.164 (leading '+'): passed through unchanged (after
      whitespace/hyphen stripping) provided what follows '+' is
      all-digit and a plausible length -- never re-prefixed, so a
      Kenyan +254 number (see SOUTH_SUDAN_COUNTRY_CODE's note above)
      typed correctly is never touched.
    - Local South Sudan format (leading '0' + 9 digits): the '0' is
      replaced with SOUTH_SUDAN_COUNTRY_CODE.
    - Anything else that isn't a plausible phone number (too short,
      contains letters, wrong digit count) returns "" rather than a
      best-effort guess. Every existing caller already treats a falsy
      return as "not a phone number" (shows a usage/format message)
      -- returning "" here, instead of passing junk through to a
      lookup, is what turns that into a real distinction from "a
      validly-formatted number that just isn't registered", rather
      than both looking like an identical "not found".
    """
    cleaned = re.sub(r"[\s\-]", "", raw)
    if not cleaned:
        return ""

    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if digits.isdigit() and _MIN_PHONE_DIGITS <= len(digits) <= _MAX_PHONE_DIGITS:
            return cleaned
        return ""

    if cleaned.startswith("0"):
        digits = cleaned[1:]
        if digits.isdigit() and len(digits) == _LOCAL_SUBSCRIBER_DIGITS:
            return f"{SOUTH_SUDAN_COUNTRY_CODE}{digits}"
        return ""

    if cleaned.isdigit() and _MIN_PHONE_DIGITS <= len(cleaned) <= _MAX_PHONE_DIGITS:
        return cleaned
    return ""


def find_possible_duplicate(db: Session, phone_number: Optional[str]) -> Optional[models.LandSteward]:
    """
    Phone-number match against existing stewards. land_steward.phone_number
    deliberately has no UNIQUE constraint (a household can legitimately
    share one phone across multiple stewards), so this flags a possible
    duplicate for the caller to confirm rather than refusing outright.
    """
    if not phone_number:
        return None
    normalized = normalize_phone(phone_number)
    if not normalized:
        return None
    return db.query(models.LandSteward).filter_by(phone_number=normalized).first()


def create_steward(
    db: Session, data: dict, force_create: bool = False
) -> Tuple[Optional[models.LandSteward], Optional[models.LandSteward]]:
    """
    Creates a land_steward row from an already-validated field dict (a
    StewardIn.model_dump() from the router, or the equivalent dict the
    Telegram NEWFARMER flow builds up across its conversation).

    Returns (steward, duplicate):
    - No duplicate found: (new steward, None).
    - Duplicate found, force_create=False: (None, existing steward) --
      nothing is written; the caller shows the existing record and asks
      for confirmation.
    - Duplicate found, force_create=True: (new steward, existing steward)
      -- both are created/returned so the caller can still mention the
      match in its confirmation message.
    """
    data = dict(data)
    phone_number = data.get("phone_number")
    if phone_number:
        data["phone_number"] = normalize_phone(phone_number)

    duplicate = find_possible_duplicate(db, data.get("phone_number"))
    if duplicate and not force_create:
        return None, duplicate

    row_id = data.pop("id", None)
    registered_offline = data.get("registered_offline", False)
    db_steward = models.LandSteward(**data)
    if row_id:
        db_steward.id = row_id
    if not registered_offline:
        db_steward.synced_at = datetime.utcnow()
    db.add(db_steward)
    db.commit()
    db.refresh(db_steward)
    return db_steward, duplicate
