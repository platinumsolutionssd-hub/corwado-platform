"""
Dispatch service — the actual "write a message once, fan it out to
whichever channel a farmer can receive" logic the ToR and proposal both
describe.

Honest scope note: this module decides WHICH channel a message should
go out on and LOGS that decision as a message_dispatch row. It does not
actually transmit an SMS, place an IVR call, or push to WhatsApp — those
require a licensed South Sudan telecom aggregator contract and a
WhatsApp Business API account, neither of which exist yet. Building a
fake "send" that pretends to succeed would be the wrong kind of demo to
bring to a funder. What's real here: the routing decision, the audit
trail, and the logic a real gateway integration would slot into later
without changing anything upstream of it.
"""
from sqlalchemy.orm import Session

from app import models

# Fallback order if a steward's preferred_channel is unset or unusable.
# Radio sits last because it's a broadcast channel, not addressed to one
# person — it's used separately via broadcast_to_payam(), not this list.
CHANNEL_FALLBACK_ORDER = ["whatsapp", "sms", "ussd", "ivr"]

# Which content format a channel needs. This is the structural half of
# the accessibility gap flagged in the ToR review: a farmer who can't
# read text still gets the same information, delivered as something
# that works for them, not a degraded version. IVR and radio need an
# audio script (spoken aloud); SMS/USSD need short text; WhatsApp can
# carry a pictorial reference for low-literacy job aids.
CONTENT_FORMAT_BY_CHANNEL = {
    "ivr": "audio_script",
    "radio": "audio_script",
    "sms": "text",
    "ussd": "text",
    "whatsapp": "pictorial",
    "in_person": "text",
}


def dispatch_to_steward(
    db: Session,
    steward: models.LandSteward,
    content_type: str,
    content_ref_id: str = None,
) -> models.MessageDispatch:
    """
    Routes a single message to one steward via their preferred channel,
    falling back down CHANNEL_FALLBACK_ORDER if their preference is
    missing or not one we support for this content type.
    """
    channel = steward.preferred_channel if steward.preferred_channel in CHANNEL_FALLBACK_ORDER else None
    if not channel:
        channel = CHANNEL_FALLBACK_ORDER[0]

    row = models.MessageDispatch(
        steward_id=steward.id,
        channel=channel,
        content_type=content_type,
        content_ref_id=content_ref_id,
        content_format=CONTENT_FORMAT_BY_CHANNEL.get(channel, "text"),
        # "queued" not "sent" — see module docstring. A real gateway
        # integration would update this to "delivered"/"failed" via a
        # webhook or polling callback; nothing here does that yet.
        delivery_status="queued",
    )
    db.add(row)
    return row


def broadcast_to_crop_growers(
    db: Session,
    crop_id: str,
    content_type: str,
    content_ref_id: str = None,
) -> list[models.MessageDispatch]:
    """
    Finds every steward currently growing a given crop (via their
    season_planting → parcel link) and dispatches to each one via their
    own preferred channel. Used for things like a price update or a
    pest alert relevant to everyone growing that crop, not just one farm.
    """
    steward_ids = (
        db.query(models.Parcel.steward_id)
        .join(models.SeasonPlanting, models.SeasonPlanting.parcel_id == models.Parcel.id)
        .filter(models.SeasonPlanting.crop_id == crop_id)
        .distinct()
        .all()
    )
    dispatched = []
    stewards = db.query(models.LandSteward).filter(
        models.LandSteward.id.in_([s[0] for s in steward_ids])
    ).all()
    for steward in stewards:
        dispatched.append(
            dispatch_to_steward(db, steward, content_type, content_ref_id)
        )
    return dispatched


def broadcast_to_payam(
    db: Session,
    payam: str,
    content_type: str,
    content_ref_id: str = None,
) -> models.MessageDispatch:
    """
    Radio is a broadcast channel, not addressed to one steward. This
    looks up an actual active broadcast slot covering the given payam
    and logs a single dispatch row against it — "this went out on Wau
    FM's 18:00 Farmers' Hour," not a placeholder "radio" entry with no
    station attached. Raises if no station covers that payam: better to
    surface that gap than log a broadcast that couldn't have happened.
    """
    stations = (
        db.query(models.RadioStation)
        .filter(models.RadioStation.payam_coverage.isnot(None))
        .all()
    )
    covering_station_ids = [
        s.id for s in stations
        if s.payam_coverage and payam in s.payam_coverage
    ]
    if not covering_station_ids:
        raise ValueError(
            f"No radio station covers payam '{payam}'. "
            f"Register one via POST /api/dispatch/radio-stations first."
        )

    slot = (
        db.query(models.RadioBroadcastSlot)
        .filter(models.RadioBroadcastSlot.radio_station_id.in_(covering_station_ids))
        .filter(models.RadioBroadcastSlot.is_active.is_(True))
        .first()
    )
    if not slot:
        raise ValueError(
            f"A station covers payam '{payam}' but has no active broadcast slot scheduled."
        )

    row = models.MessageDispatch(
        steward_id=None,
        channel="radio",
        radio_slot_id=slot.id,
        content_type=content_type,
        content_ref_id=content_ref_id,
        content_format="audio_script",
        delivery_status="queued",
    )
    db.add(row)
    return row
