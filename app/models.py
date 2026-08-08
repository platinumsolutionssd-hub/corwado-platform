"""
SQLAlchemy models — mirror db/schema.sql exactly. If you change one,
change the other; this file doesn't auto-generate the SQL.
"""
import uuid
import enum
from datetime import datetime

from sqlalchemy import (
    Column, String, Boolean, Numeric, DateTime, ForeignKey, Text, Date,
    Enum as SAEnum, UniqueConstraint, FetchedValue,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class StewardRole(str, enum.Enum):
    smallholder_farmer = "smallholder_farmer"
    cooperative_member = "cooperative_member"
    investor_partner = "investor_partner"
    land_owner = "land_owner"


class GenderType(str, enum.Enum):
    female = "female"
    male = "male"
    other = "other"
    prefer_not_to_say = "prefer_not_to_say"


class AdvisorySource(str, enum.Enum):
    digital_twin = "digital_twin"
    satyukt_sat2farm = "satyukt_sat2farm"
    satyukt_sat4risk = "satyukt_sat4risk"
    satyukt_sat4agri = "satyukt_sat4agri"


class DispatchChannel(str, enum.Enum):
    sms = "sms"
    ussd = "ussd"
    ivr = "ivr"
    whatsapp = "whatsapp"
    radio = "radio"
    in_person = "in_person"
    telegram = "telegram"


class InputCategory(str, enum.Enum):
    seed = "seed"
    fertilizer = "fertilizer"
    pesticide = "pesticide"
    labour = "labour"
    other = "other"


class FinancierType(str, enum.Enum):
    farmer = "farmer"
    corwado = "corwado"
    financial_institution = "financial_institution"
    government = "government"
    ngo = "ngo"


class Cooperative(Base):
    __tablename__ = "cooperative"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    name = Column(Text, nullable=False)
    type = Column(Text)  # cooperative | vsla | farmer_group
    payam = Column(Text)
    county = Column(Text, default="Western Bahr el Ghazal")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    stewards = relationship("LandSteward", back_populates="cooperative")


class LandSteward(Base):
    __tablename__ = "land_steward"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    role = Column(SAEnum(StewardRole), nullable=False)
    full_name = Column(Text, nullable=False)
    phone_number = Column(Text)
    whatsapp_number = Column(Text)
    preferred_language = Column(Text, default="juba_arabic")
    preferred_channel = Column(Text)  # sms|ussd|ivr|whatsapp|radio|in_person
    telegram_chat_id = Column(Text, unique=True)
    gender = Column(SAEnum(GenderType))
    is_youth = Column(Boolean, default=False)
    has_disability = Column(Boolean, default=False)
    disability_notes = Column(Text)
    cooperative_id = Column(UUID(as_uuid=False), ForeignKey("cooperative.id"))
    registered_by = Column(Text)
    registered_offline = Column(Boolean, default=False)
    synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    cooperative = relationship("Cooperative", back_populates="stewards")
    parcels = relationship("Parcel", back_populates="steward")

    @property
    def cooperative_name(self):
        return self.cooperative.name if self.cooperative else None


class Parcel(Base):
    __tablename__ = "parcel"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    steward_id = Column(UUID(as_uuid=False), ForeignKey("land_steward.id"), nullable=False)
    geom = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    # area_acres is a DB-generated column (see db/schema.sql —
    # ST_Area(geom::geography)/4046.86, STORED). Found while running this
    # against a real database for the first time: `nullable=True` alone
    # does NOT make SQLAlchemy treat it as read-only -- it still put
    # `area_acres = NULL` in every INSERT, which Postgres rejects outright
    # for a GENERATED ALWAYS column ("cannot insert a non-DEFAULT value").
    # server_default=FetchedValue() is what actually tells SQLAlchemy to
    # omit the column from INSERT/UPDATE and fetch the server-computed
    # value back instead.
    area_acres = Column(Numeric, server_default=FetchedValue())

    # Large-parcel confirmation guardrail (see db/schema.sql migration
    # note and app/routers/parcels.py's LARGE_PARCEL_THRESHOLD_HA) --
    # area_flagged_large records whether THIS submission crossed the
    # plausibility threshold; area_confirmed_at, when a human explicitly
    # confirmed it was correct. Neither touches area_acres itself.
    area_flagged_large = Column(Boolean, nullable=False, default=False)
    area_confirmed_at = Column(DateTime(timezone=True), nullable=True)

    elevation_m = Column(Numeric)

    soil_type = Column(Text)
    terrain_slope_pct = Column(Numeric)
    # baseline_suitability/baseline_computed_at/baseline_refresh_due were
    # dropped (see db/schema.sql migration, post-Day 14) in favor of the
    # parcel_crop_baseline join table below -- one shared baseline/
    # staleness pair on parcel couldn't represent more than one crop.

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    steward = relationship("LandSteward", back_populates="parcels")


class CropDictionaryEntry(Base):
    __tablename__ = "crop_dictionary_entry"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    crop_name = Column(Text, nullable=False, unique=True)
    scoring_params = Column(JSONB, nullable=False)
    typical_season = Column(Text)
    notes = Column(Text)
    # Nullable: NULL means CORWADO tracks this crop for registration/
    # market-linkage purposes but agri-venture-v2 has no biology.json for
    # it yet, so no biophysical score can be produced (see db/schema.sql
    # migration, Day 15). get_baseline() in app/routers/advisory.py
    # checks this before ever calling BiophysicalEngine.
    agriventure_crop_key = Column(Text)


class ParcelCropBaseline(Base):
    """
    One row per (parcel, crop): the cached baseline suitability result
    from BiophysicalEngine (agri-venture-v2's /analyze, once wired up).
    Replaces the old parcel.baseline_suitability JSONB column -- see
    db/schema.sql migration note (post-Day 14) for why.
    """
    __tablename__ = "parcel_crop_baseline"
    __table_args__ = (UniqueConstraint("parcel_id", "crop_id"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    parcel_id = Column(UUID(as_uuid=False), ForeignKey("parcel.id"), nullable=False)
    crop_id = Column(UUID(as_uuid=False), ForeignKey("crop_dictionary_entry.id"), nullable=False)
    # Flattened summary for dashboard/dispatch use: overall_score,
    # overall_classification, is_fatal, binding_domain, confidence.
    suitability = Column(JSONB)
    # Full, unmodified AnalysisResult tree (DomainResult -> FactorScore ->
    # Evidence) -- never discarded, per agri-venture-v2's Explainability
    # Requirement. Separate column so `suitability` stays cheap to read.
    suitability_raw = Column(JSONB)
    computed_at = Column(DateTime(timezone=True), nullable=True)
    refresh_due = Column(DateTime(timezone=True), nullable=True)


class ParcelDiagnostic(Base):
    """
    One row per parcel: the cached Stage 1 Land Diagnostic ("FarmLab
    report") from agri-venture-v2's /diagnostic. Crop-independent, unlike
    ParcelCropBaseline above -- UNIQUE on parcel_id alone, not
    parcel_id+crop_id, since there is exactly one Land Diagnostic per
    parcel regardless of which crop is being considered (see db/schema.sql
    migration note).
    """
    __tablename__ = "parcel_diagnostic"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    parcel_id = Column(UUID(as_uuid=False), ForeignKey("parcel.id"), nullable=False, unique=True)
    # Full, unmodified LandDiagnostic response (climate/soil/water/
    # vegetation/topography/land_use/carbon fact lists, external reference
    # models, warnings) -- never reshaped server-side.
    diagnostic = Column(JSONB)
    depth = Column(Text)  # 'quick' or 'full' -- whichever was actually run
    computed_at = Column(DateTime(timezone=True), nullable=True)
    refresh_due = Column(DateTime(timezone=True), nullable=True)


class SeasonPlanting(Base):
    __tablename__ = "season_planting"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    parcel_id = Column(UUID(as_uuid=False), ForeignKey("parcel.id"), nullable=False)
    crop_id = Column(UUID(as_uuid=False), ForeignKey("crop_dictionary_entry.id"), nullable=False)
    sowing_date = Column(Date)
    season_label = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class InputRequirement(Base):
    """
    One Bill of Quantities line item for a season_planting cycle --
    transparent record-keeping only, never a creditworthiness or
    eligibility signal (same firewall as everywhere else in this
    project). Costs always in USD; source-currency/fx fields exist so a
    KES-sourced figure (e.g. agri-venture-v2's economics.json) is
    auditable and correctable, never silently baked in. See db/schema.sql
    migration note for the full reasoning.
    """
    __tablename__ = "input_requirement"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    season_planting_id = Column(UUID(as_uuid=False), ForeignKey("season_planting.id"), nullable=False)
    item_name = Column(Text, nullable=False)
    category = Column(SAEnum(InputCategory), nullable=False)
    quantity = Column(Numeric, nullable=False)
    unit = Column(Text, nullable=False)
    unit_cost_usd = Column(Numeric, nullable=False)
    # GENERATED column in Postgres (quantity * unit_cost_usd) -- read-only
    # from SQLAlchemy's side, same pattern as Parcel.area_acres above.
    total_cost_usd = Column(Numeric, server_default=FetchedValue())
    currency = Column(Text, nullable=False, default="USD")

    cost_source = Column(Text, nullable=False)
    baseline_unit_cost_usd = Column(Numeric)
    source_currency_original = Column(Text)
    source_amount_original = Column(Numeric)
    fx_rate_used = Column(Numeric)
    fx_rate_date = Column(Date)
    fx_rate_source = Column(Text)

    override_reason = Column(Text)
    override_by = Column(Text)
    override_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class InputFinancingRecord(Base):
    """
    One financing/payment record against a single input_requirement line
    item -- deliberately line-item-scoped, not BoQ-wide, so "who funded
    what" stays comparable at the resolution that actually matters (see
    db/schema.sql migration note). No uniqueness constraint on
    input_requirement_id: multiple records may reference the same line
    item, which is how split/partial funding falls out of this schema
    without special-case modeling.
    """
    __tablename__ = "input_financing_record"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    input_requirement_id = Column(UUID(as_uuid=False), ForeignKey("input_requirement.id"), nullable=False)
    financier_type = Column(SAEnum(FinancierType), nullable=False)
    financier_name = Column(Text)
    amount_usd = Column(Numeric, nullable=False)
    currency = Column(Text, nullable=False, default="USD")
    financed_at = Column(Date, nullable=False)
    notes = Column(Text)
    recorded_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class AdvisorySnapshot(Base):
    __tablename__ = "advisory_snapshot"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    parcel_id = Column(UUID(as_uuid=False), ForeignKey("parcel.id"), nullable=False)
    source = Column(SAEnum(AdvisorySource), nullable=False)
    soil_n = Column(Numeric)
    soil_p = Column(Numeric)
    soil_k = Column(Numeric)
    soil_soc = Column(Numeric)
    soil_ph = Column(Numeric)
    ndvi = Column(Numeric)
    evi = Column(Numeric)
    soil_moisture = Column(Numeric)
    weather_forecast_json = Column(JSONB)
    pest_disease_alerts = Column(JSONB)
    generated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class PriceBoardEntry(Base):
    __tablename__ = "price_board_entry"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    crop_id = Column(UUID(as_uuid=False), ForeignKey("crop_dictionary_entry.id"), nullable=False)
    market_location = Column(Text, nullable=False)
    price_ssp = Column(Numeric)
    unit = Column(Text, default="kg")
    recorded_by = Column(Text)
    recorded_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Buyer(Base):
    __tablename__ = "buyer"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    name = Column(Text, nullable=False)
    contact_phone = Column(Text)
    buyer_type = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class BuyerPosting(Base):
    __tablename__ = "buyer_posting"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    buyer_id = Column(UUID(as_uuid=False), ForeignKey("buyer.id"), nullable=False)
    crop_id = Column(UUID(as_uuid=False), ForeignKey("crop_dictionary_entry.id"), nullable=False)
    quantity_kg = Column(Numeric)
    offer_price_ssp = Column(Numeric)
    needed_by = Column(Date)
    location = Column(Text)
    status = Column(Text, default="open")  # open | matched | fulfilled | expired
    # Added Day 7-9 (see db/schema.sql migration note) — links a posting
    # to the aggregation event confirmed to fulfil it.
    matched_aggregation_event_id = Column(UUID(as_uuid=False), ForeignKey("aggregation_event.id"), nullable=True)
    posted_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class AggregationEvent(Base):
    __tablename__ = "aggregation_event"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    cooperative_id = Column(UUID(as_uuid=False), ForeignKey("cooperative.id"), nullable=False)
    crop_id = Column(UUID(as_uuid=False), ForeignKey("crop_dictionary_entry.id"), nullable=False)
    collection_point = Column(Text)
    scheduled_date = Column(Date)
    status = Column(Text, default="scheduled")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class AggregationContribution(Base):
    __tablename__ = "aggregation_contribution"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    aggregation_event_id = Column(UUID(as_uuid=False), ForeignKey("aggregation_event.id"), nullable=False)
    steward_id = Column(UUID(as_uuid=False), ForeignKey("land_steward.id"), nullable=False)
    quantity_kg = Column(Numeric)
    attended = Column(Boolean, default=False)


class AgroDealer(Base):
    __tablename__ = "agro_dealer"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    name = Column(Text, nullable=False)
    location = Column(Text)
    geom = Column(Geometry(geometry_type="POINT", srid=4326))
    products = Column(JSONB)
    contact_phone = Column(Text)


class RadioStation(Base):
    __tablename__ = "radio_station"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    name = Column(Text, nullable=False)
    frequency = Column(Text)
    # Was Column(JSON) ("keeps SQLite-testable") -- but db/schema.sql
    # declares this TEXT[], and running app/seed.py against a real
    # Postgres instance for the first time (2026-07-11) confirmed Postgres
    # rejects a JSON value into a text[] column outright (DatatypeMismatch),
    # blocking seeding entirely. ARRAY(Text) matches the real schema.
    payam_coverage = Column(ARRAY(Text))
    language = Column(Text, default="juba_arabic")
    contact_name = Column(Text)
    contact_phone = Column(Text)


class RadioBroadcastSlot(Base):
    __tablename__ = "radio_broadcast_slot"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    radio_station_id = Column(UUID(as_uuid=False), ForeignKey("radio_station.id"), nullable=False)
    day_of_week = Column(Text)
    time_slot = Column(Text)
    program_name = Column(Text)
    is_active = Column(Boolean, default=True)


class InboundMessage(Base):
    """
    Inbound side of the dispatch story -- kept separate from
    MessageDispatch (outbound-only, see below) since a farmer's reply is
    a different job, not the same table pointed the other way. See
    db/schema.sql migration note for the full reasoning.
    """
    __tablename__ = "inbound_message"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    steward_id = Column(UUID(as_uuid=False), ForeignKey("land_steward.id"), nullable=True)
    channel = Column(Text, nullable=False, default="telegram")
    external_chat_id = Column(Text, nullable=False)
    raw_text = Column(Text, nullable=False)
    parsed_intent = Column(Text)
    parsed_params = Column(JSONB)
    response_text = Column(Text)
    received_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    processed_at = Column(DateTime(timezone=True), nullable=True)


class TelegramConversationState(Base):
    """
    One row per Telegram chat, tracking the single pending follow-up
    question the numbered menu is waiting on (e.g. "send your phone
    number" after choosing REGISTER). Not a column on LandSteward --
    REGISTER has to work before a steward row is linked to this chat_id,
    so this has to be keyed on the chat_id alone. See db/schema.sql
    migration note for the full reasoning.
    """
    __tablename__ = "telegram_conversation_state"
    chat_id = Column(Text, primary_key=True)
    awaiting = Column(Text, nullable=True)  # 'phone_for_register' | 'crop_for_price' | 'new_farmer_name' | ... | None
    # Scratch space for multi-step forms (NEWFARMER: name -> phone ->
    # gender) that need to remember earlier answers across several
    # inbound messages -- `awaiting` alone only tracks the next pending
    # question. See db/schema.sql migration note.
    context = Column(JSONB, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class AuthorizedOperator(Base):
    """
    CORWADO staff / Digital Champions authorized to create a new
    land_steward or register a boundary on someone else's behalf via
    Telegram -- deliberately a separate table from LandSteward, not a
    role flag on it, since a person can plausibly be both. Populated
    only by an admin action (POST /api/authorized-operators); chat
    linking (telegram_chat_id) works the same way REGISTER does for
    farmers -- the phone_number must already be on this table. See
    db/schema.sql migration note for the full reasoning.
    """
    __tablename__ = "authorized_operator"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    full_name = Column(Text, nullable=False)
    phone_number = Column(Text, nullable=False, unique=True)
    role = Column(Text)  # 'corwado_staff' | 'digital_champion' -- reporting only, does not gate anything
    telegram_chat_id = Column(Text, unique=True)
    added_by = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class ParcelDrawToken(Base):
    """
    Single-use, time-limited credential authorizing one boundary
    submission for one steward on the public draw-boundary web page --
    the only "auth" that page has, since no dashboard login exists
    anywhere in this project. Minted by the Telegram BOUNDARY command
    with secrets.token_urlsafe(). used_at is set atomically with the
    parcel insert it authorizes (same transaction -- see
    app/routers/parcels.py) so it can never be replayed. See
    db/schema.sql migration note.
    """
    __tablename__ = "parcel_draw_token"
    token = Column(Text, primary_key=True)
    steward_id = Column(UUID(as_uuid=False), ForeignKey("land_steward.id"), nullable=False)
    originating_chat_id = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    # Holds a drawn boundary that crossed the large-parcel plausibility
    # threshold while it awaits a YES/NO reply in the originating
    # Telegram chat -- see db/schema.sql migration note and
    # app/services/telegram_inbound.py's boundary_large_area_confirm
    # state. NULL for every token that never triggered the guardrail.
    # none_as_null=True: SQLAlchemy's JSONB default treats an assigned
    # Python None as the JSON value 'null', not SQL NULL -- confirmed
    # live 2026-07-16 testing the confirm/redraw handlers, where
    # `token_row.pending_geojson = None` (clearing it after YES/NO) left
    # a real 'null'::jsonb in the column instead of SQL NULL. Invisible
    # to the ORM (both deserialize back to Python None) but wrong for
    # any direct SQL query checking "was this ever flagged" -- this
    # column exists specifically to be auditable.
    pending_geojson = Column(JSONB(none_as_null=True), nullable=True)


class Organization(Base):
    __tablename__ = "organization"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(Text, nullable=False)
    short_code = Column(Text, unique=True)
    country = Column(Text)
    contact_name = Column(Text)
    contact_phone = Column(Text)
    # DB default is 'pending' (fail-closed). Product policy for self-signup
    # lives in code (SELF_SIGNUP_INITIAL_STATUS), not this default.
    status = Column(Text, nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class StaffAccount(Base):
    __tablename__ = "staff_account"
    __table_args__ = (UniqueConstraint("organization_id", "email"),)
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    email = Column(Text, nullable=False)
    password_hash = Column(Text, nullable=False)
    full_name = Column(Text)
    role = Column(Text, nullable=False, default="admin")  # 'admin' | 'staff' — org-scoped, never landlord
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class PlatformAdmin(Base):
    """Landlord / cross-org superadmin. Deliberately its own table, never a
    flag on StaffAccount — the self-signup path has no way to create one."""
    __tablename__ = "platform_admin"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(Text, nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    full_name = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class MessageDispatch(Base):
    __tablename__ = "message_dispatch"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organization.id"), nullable=False)
    steward_id = Column(UUID(as_uuid=False), ForeignKey("land_steward.id"), nullable=True)
    channel = Column(SAEnum(DispatchChannel), nullable=False)
    # Added Day 10-11 — see db/schema.sql migration note.
    radio_slot_id = Column(UUID(as_uuid=False), ForeignKey("radio_broadcast_slot.id"), nullable=True)
    content_type = Column(Text)
    content_ref_id = Column(UUID(as_uuid=False), nullable=True)
    content_format = Column(Text, default="text")  # text | audio_script | pictorial
    sent_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    delivery_status = Column(Text, default="pending")
    delivery_note = Column(Text, nullable=True)
