"""
Dispatch service — the actual "write a message once, fan it out to
whichever channel a farmer can receive" logic the ToR and proposal both
describe.

Honest scope note, updated: this module decides WHICH channel a message
should go out on and LOGS that decision as a message_dispatch row. For
sms/ussd/ivr/whatsapp/radio, it still does not actually transmit —
those require a licensed South Sudan telecom aggregator contract and a
WhatsApp Business API account, neither of which exist yet. Building a
fake "send" that pretends to succeed would be the wrong kind of demo to
bring to a funder. Telegram is the one exception: it's a real API call
with a real bot token, so 'telegram' dispatches actually send via
telegram_sender.send() and delivery_status reflects the real outcome
('sent'/'failed'), not just 'queued'. What's real for every other
channel: the routing decision, the audit trail, and the logic a real
gateway integration would slot into later without changing anything
upstream of it.
"""
from sqlalchemy.orm import Session

from app import models
from app.services import telegram_sender

# Fallback order if a steward's preferred_channel is unset or unusable.
# Radio is deliberately absent: it's a broadcast channel, not addressed
# to one person, and is dispatched separately via broadcast_to_payam().
# A steward whose preferred_channel is 'radio' is rejected explicitly
# below rather than silently falling through to whatsapp.
CHANNEL_FALLBACK_ORDER = ["whatsapp", "sms", "ussd", "ivr"]

# Valid preferred_channel values that are never a fallback target — each
# is only ever used when explicitly chosen, handled outside the fallback
# chain above instead of being silently substituted with whatsapp.
# Telegram belongs here, not in CHANNEL_FALLBACK_ORDER: most stewards
# won't have a linked telegram_chat_id, so it must never become the
# silent default for someone else's unset/invalid preference — only for
# a steward who explicitly chose it (and even then, see the no-link
# fallback in dispatch_to_steward() below).
DIRECT_ONLY_CHANNELS = {"in_person", "telegram"}

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
    "telegram": "text",
}


def _render_message_text(db: Session, content_type: str, content_ref_id: str) -> str:
    """
    Turns a (content_type, content_ref_id) dispatch pointer into actual
    message text. Nothing needed this before Telegram: every other
    channel only ever logged the pointer (see module docstring), so no
    renderer existed. Minimal, real data only — no invented copy for
    fields a record doesn't have.
    """
    if content_ref_id is None:
        return f"CORWADO update: {content_type}"

    if content_type == "price_update":
        entry = db.query(models.PriceBoardEntry).filter_by(id=content_ref_id).first()
        if entry:
            crop = db.query(models.CropDictionaryEntry).filter_by(id=entry.crop_id).first()
            crop_name = crop.crop_name.capitalize() if crop else "Crop"
            return (
                f"Price update: {crop_name} — {entry.price_ssp} SSP/{entry.unit} "
                f"at {entry.market_location}."
            )
    elif content_type == "advisory":
        snapshot = db.query(models.AdvisorySnapshot).filter_by(id=content_ref_id).first()
        if snapshot:
            return (
                f"New advisory available for your farm, generated "
                f"{snapshot.generated_at.strftime('%Y-%m-%d')}. Contact "
                f"your Digital Champion for details."
            )
    elif content_type == "buyer_posting":
        posting = db.query(models.BuyerPosting).filter_by(id=content_ref_id).first()
        if posting:
            crop = db.query(models.CropDictionaryEntry).filter_by(id=posting.crop_id).first()
            crop_name = crop.crop_name.capitalize() if crop else "Crop"
            return (
                f"Buyer interested in {crop_name}: {posting.quantity_kg} kg at "
                f"{posting.offer_price_ssp} SSP/kg, {posting.location or 'location TBC'}."
            )
    elif content_type == "aggregation_alert":
        event = db.query(models.AggregationEvent).filter_by(id=content_ref_id).first()
        if event:
            when = event.scheduled_date.strftime("%Y-%m-%d") if event.scheduled_date else "date TBC"
            return f"Collection event scheduled {when} at {event.collection_point or 'location TBC'}."

    return f"CORWADO update: {content_type}"


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
    if steward.preferred_channel == "radio":
        raise ValueError(
            f"Steward {steward.id} has preferred_channel='radio', which "
            "is a broadcast channel with no single addressee — "
            "dispatch_to_steward() can't route to it. Use "
            "broadcast_to_payam() for radio delivery instead."
        )

    if steward.preferred_channel in DIRECT_ONLY_CHANNELS:
        channel = steward.preferred_channel
    else:
        channel = steward.preferred_channel if steward.preferred_channel in CHANNEL_FALLBACK_ORDER else None
        if not channel:
            channel = CHANNEL_FALLBACK_ORDER[0]

    # "queued" not "sent" — see module docstring. A real gateway
    # integration would update this to "delivered"/"failed" via a
    # webhook or polling callback; nothing here does that yet, except
    # Telegram below, which really sends.
    delivery_status = "queued"
    delivery_note = None

    if channel == "telegram":
        if steward.telegram_chat_id:
            text = _render_message_text(db, content_type, content_ref_id)
            sent, detail = telegram_sender.send(steward.telegram_chat_id, text)
            delivery_status = "sent" if sent else "failed"
            delivery_note = detail or None
        else:
            delivery_note = (
                "preferred_channel is 'telegram' but no telegram_chat_id "
                "is linked — steward must send REGISTER <phone> to the "
                "bot first"
            )

    row = models.MessageDispatch(
        steward_id=steward.id,
        organization_id=steward.organization_id,  # scopes to the steward's org (== caller's current_org)
        channel=channel,
        content_type=content_type,
        content_ref_id=content_ref_id,
        content_format=CONTENT_FORMAT_BY_CHANNEL.get(channel, "text"),
        delivery_status=delivery_status,
        delivery_note=delivery_note,
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
        organization_id=slot.organization_id,  # radio broadcast: no steward, scope to the slot's org
        channel="radio",
        radio_slot_id=slot.id,
        content_type=content_type,
        content_ref_id=content_ref_id,
        content_format="audio_script",
        delivery_status="queued",
    )
    db.add(row)
    return row
