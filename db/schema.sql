-- =====================================================================
-- CORWADO Agricultural Extension & Market Linkage Platform
-- Core PostGIS Schema — v0.1
-- Design principle: tiered by change-speed (see architecture doc Section 2
-- and the platform's cached-vs-live data decision)
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------------------------------------------------------------------
-- 1. LAND STEWARD (generalized farmer / cooperative member / investor)
-- ---------------------------------------------------------------------
CREATE TYPE steward_role AS ENUM (
    'smallholder_farmer',
    'cooperative_member',
    'investor_partner',   -- Ngong Gold front-end only
    'land_owner'
);

CREATE TYPE gender_type AS ENUM ('female', 'male', 'other', 'prefer_not_to_say');

CREATE TABLE cooperative (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    type            TEXT CHECK (type IN ('cooperative', 'vsla', 'farmer_group')),
    payam           TEXT,               -- Western Bahr el Ghazal is county/payam administered
    county          TEXT DEFAULT 'Western Bahr el Ghazal',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE land_steward (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role                steward_role NOT NULL,
    full_name           TEXT NOT NULL,
    phone_number        TEXT,               -- primary channel identifier for SMS/USSD/IVR
    whatsapp_number     TEXT,
    preferred_language  TEXT DEFAULT 'juba_arabic',
    preferred_channel   TEXT CHECK (preferred_channel IN ('sms','ussd','ivr','whatsapp','radio','in_person')),
    gender              gender_type,
    is_youth            BOOLEAN DEFAULT FALSE,   -- CORWADO M&E disaggregation requirement
    has_disability       BOOLEAN DEFAULT FALSE,   -- accessibility gap we flagged — now designed in
    disability_notes     TEXT,                    -- e.g. "visual impairment - prefers IVR"
    cooperative_id      UUID REFERENCES cooperative(id),
    registered_by       TEXT,               -- Digital Champion / extension worker name/id
    registered_offline  BOOLEAN DEFAULT FALSE,   -- true if captured with no live connectivity
    synced_at           TIMESTAMPTZ,             -- null until offline record syncs
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_land_steward_cooperative ON land_steward(cooperative_id);
CREATE INDEX idx_land_steward_phone ON land_steward(phone_number);

-- ---------------------------------------------------------------------
-- 2. PARCEL — the geolocated shape, with cached SLOW-changing attributes
-- ---------------------------------------------------------------------
CREATE TABLE parcel (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    steward_id              UUID NOT NULL REFERENCES land_steward(id),
    geom                    GEOMETRY(Polygon, 4326) NOT NULL,   -- farm boundary
    area_acres              NUMERIC GENERATED ALWAYS AS (ST_Area(geom::geography) / 4046.86) STORED,

    -- SLOW-CHANGING (cached at registration, refreshed periodically — not queried live)
    elevation_m             NUMERIC,
    soil_type               TEXT,
    terrain_slope_pct       NUMERIC,
    baseline_suitability    JSONB,        -- per-crop suitability scores from Digital Twin, computed once
    baseline_computed_at    TIMESTAMPTZ,
    baseline_refresh_due    TIMESTAMPTZ,  -- next scheduled recheck (e.g. +1 year)

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_parcel_geom ON parcel USING GIST(geom);
CREATE INDEX idx_parcel_steward ON parcel(steward_id);

-- ---------------------------------------------------------------------
-- 3. CROP DICTIONARY — one entry per crop, reused across all parcels
-- ---------------------------------------------------------------------
CREATE TABLE crop_dictionary_entry (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    crop_name           TEXT NOT NULL UNIQUE,
    scoring_params       JSONB NOT NULL,   -- MCE weights, trapezoid function params (from Kibiko model)
    typical_season       TEXT,
    notes                TEXT
);

CREATE TABLE season_planting (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parcel_id       UUID NOT NULL REFERENCES parcel(id),
    crop_id         UUID NOT NULL REFERENCES crop_dictionary_entry(id),
    sowing_date     DATE,
    season_label    TEXT,   -- e.g. "2026 Wet Season"
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 4. ADVISORY OUTPUT — shared schema regardless of source engine
--    FAST-CHANGING data lives here as time-stamped snapshots, not cached
-- ---------------------------------------------------------------------
CREATE TYPE advisory_source AS ENUM ('digital_twin', 'satyukt_sat2farm', 'satyukt_sat4risk', 'satyukt_sat4agri');

CREATE TABLE advisory_snapshot (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parcel_id           UUID NOT NULL REFERENCES parcel(id),
    source               advisory_source NOT NULL,
    soil_n               NUMERIC, soil_p NUMERIC, soil_k NUMERIC, soil_soc NUMERIC, soil_ph NUMERIC,
    ndvi                 NUMERIC,
    evi                  NUMERIC,
    soil_moisture         NUMERIC,
    weather_forecast_json JSONB,     -- 14-day forecast payload
    pest_disease_alerts   JSONB,     -- array of {crop, threat, severity, date}
    generated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_advisory_parcel_time ON advisory_snapshot(parcel_id, generated_at DESC);

-- ---------------------------------------------------------------------
-- 5. MARKET LINKAGE — genuinely new build, not covered by Satyukt
-- ---------------------------------------------------------------------
CREATE TABLE price_board_entry (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    crop_id         UUID NOT NULL REFERENCES crop_dictionary_entry(id),
    market_location TEXT NOT NULL,      -- e.g. "Wau Central Market"
    price_ssp       NUMERIC,
    unit            TEXT DEFAULT 'kg',
    recorded_by     TEXT,               -- CORWADO staff / partner
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE buyer (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    contact_phone   TEXT,
    buyer_type      TEXT CHECK (buyer_type IN ('trader','processor','institution','exporter')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE buyer_posting (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    buyer_id        UUID NOT NULL REFERENCES buyer(id),
    crop_id         UUID NOT NULL REFERENCES crop_dictionary_entry(id),
    quantity_kg     NUMERIC,
    offer_price_ssp NUMERIC,
    needed_by       DATE,
    location        TEXT,
    status          TEXT DEFAULT 'open' CHECK (status IN ('open','matched','fulfilled','expired')),
    posted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE aggregation_event (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cooperative_id      UUID NOT NULL REFERENCES cooperative(id),
    crop_id             UUID NOT NULL REFERENCES crop_dictionary_entry(id),
    collection_point    TEXT,
    scheduled_date       DATE,
    status               TEXT DEFAULT 'scheduled' CHECK (status IN ('scheduled','completed','cancelled')),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Migration, added Day 7-9: link a buyer posting to the aggregation
-- event that will fulfil it, once CORWADO staff confirm a match.
-- Added as an explicit ALTER rather than rewritten into buyer_posting's
-- original CREATE TABLE, since aggregation_event didn't exist yet at
-- that point in the table order — this is how the change would actually
-- land as a real migration against a live database.
-- ---------------------------------------------------------------------
ALTER TABLE buyer_posting
    ADD COLUMN matched_aggregation_event_id UUID REFERENCES aggregation_event(id);

CREATE TABLE aggregation_contribution (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aggregation_event_id    UUID NOT NULL REFERENCES aggregation_event(id),
    steward_id              UUID NOT NULL REFERENCES land_steward(id),
    quantity_kg              NUMERIC,
    attended                 BOOLEAN DEFAULT FALSE
);

-- ---------------------------------------------------------------------
-- Migration, added Day 10-11: real radio-channel design, not just a
-- channel label. South Sudan rural extension relies heavily on
-- community/local radio — this table set exists so "radio" dispatch
-- means something concrete (which station, which slot, which language)
-- rather than a generic broadcast log entry.
-- ---------------------------------------------------------------------
CREATE TABLE radio_station (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,          -- e.g. "Wau FM"
    frequency       TEXT,                    -- e.g. "97.5 FM"
    payam_coverage  TEXT[],                  -- payams this station's signal actually reaches
    language        TEXT DEFAULT 'juba_arabic',
    contact_name    TEXT,
    contact_phone   TEXT
);

CREATE TABLE radio_broadcast_slot (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    radio_station_id UUID NOT NULL REFERENCES radio_station(id),
    day_of_week     TEXT CHECK (day_of_week IN ('mon','tue','wed','thu','fri','sat','sun')),
    time_slot       TEXT,                    -- e.g. "18:00-18:15"
    program_name    TEXT,                    -- e.g. "CORWADO Farmers' Hour"
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE TABLE agro_dealer (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    location        TEXT,
    geom            GEOMETRY(Point, 4326),
    products        JSONB,      -- e.g. ["seed", "fertilizer", "pesticide"]
    contact_phone   TEXT
);

CREATE INDEX idx_agro_dealer_geom ON agro_dealer USING GIST(geom);

-- ---------------------------------------------------------------------
-- 6. MESSAGE DISPATCH LOG — the multi-channel gateway's audit trail
--    (radio added explicitly — a gap flagged in ToR review)
-- ---------------------------------------------------------------------
CREATE TYPE dispatch_channel AS ENUM ('sms','ussd','ivr','whatsapp','radio','in_person');

CREATE TABLE message_dispatch (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    steward_id      UUID REFERENCES land_steward(id),   -- nullable: radio broadcasts aren't steward-specific
    channel         dispatch_channel NOT NULL,
    content_type    TEXT CHECK (content_type IN ('advisory','price_update','buyer_posting','aggregation_alert','training')),
    content_ref_id  UUID,       -- points back to advisory_snapshot / price_board_entry / etc.
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivery_status TEXT DEFAULT 'pending'
);

-- ---------------------------------------------------------------------
-- Migration, added Day 10-11: attach dispatches to a specific radio
-- slot (only set when channel='radio'), and record which content
-- format was actually used — text, an audio script for IVR/radio
-- reading, or a pictorial reference for low-literacy job aids. Added
-- as ALTER TABLE rather than rewritten into the Day-1 CREATE TABLE,
-- consistent with how the buyer_posting match column was migrated.
-- ---------------------------------------------------------------------
ALTER TABLE message_dispatch
    ADD COLUMN radio_slot_id UUID REFERENCES radio_broadcast_slot(id),
    ADD COLUMN content_format TEXT DEFAULT 'text' CHECK (content_format IN ('text','audio_script','pictorial'));

CREATE INDEX idx_dispatch_steward ON message_dispatch(steward_id);

-- ---------------------------------------------------------------------
-- Migration, added post-Day 14 (agri-venture-v2 integration prep):
-- replace parcel.baseline_suitability/baseline_computed_at/baseline_
-- refresh_due (a single per-parcel JSONB dict keyed by bare crop-name
-- strings, with one shared pair of staleness timestamps) with a proper
-- join table.
--
-- Two problems this fixes:
--   1. Bare crop-name string keys in a JSONB dict have no referential
--      integrity to crop_dictionary_entry, which already exists in this
--      schema for exactly this purpose. A real foreign key does.
--   2. One shared baseline_computed_at/baseline_refresh_due pair on
--      parcel cannot correctly represent staleness for more than one
--      crop at a time -- refreshing crop A's baseline would look like
--      it also refreshed crop B's.
--
-- suitability (flattened summary: overall_score, overall_classification,
-- is_fatal, binding_domain, confidence) and suitability_raw (the full,
-- unmodified agri-venture-v2 AnalysisResult tree -- DomainResult ->
-- FactorScore -> Evidence) are split into two columns so the small
-- summary a dashboard reads on every load stays cheap, while the full
-- explainability trail is never discarded (agri-venture-v2's own
-- Explainability Requirement: nothing is a black box).
--
-- No live deployment with real data exists yet, so the old columns are
-- dropped cleanly rather than carried forward as unused legacy columns.
-- ---------------------------------------------------------------------
CREATE TABLE parcel_crop_baseline (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parcel_id       UUID NOT NULL REFERENCES parcel(id),
    crop_id         UUID NOT NULL REFERENCES crop_dictionary_entry(id),
    suitability     JSONB,       -- flattened summary (overall_score, overall_classification, is_fatal, binding_domain, confidence)
    suitability_raw JSONB,       -- full AnalysisResult tree, unmodified (DomainResult -> FactorScore -> Evidence)
    computed_at     TIMESTAMPTZ,
    refresh_due     TIMESTAMPTZ,
    UNIQUE(parcel_id, crop_id)
);

ALTER TABLE parcel
    DROP COLUMN baseline_suitability,
    DROP COLUMN baseline_computed_at,
    DROP COLUMN baseline_refresh_due;

-- ---------------------------------------------------------------------
-- Migration, added Day 15 (post real-DB verification): crop_dictionary_
-- entry was serving two distinct jobs without distinguishing them --
-- (1) CORWADO tracking that a crop exists at all, for registration and
-- market-linkage purposes (true for all 6 seeded crops), and (2)
-- agri-venture-v2 actually being able to produce a biophysical
-- suitability score for it (true only for maize and moringa today --
-- the other 4 crops don't have a biology.json in agri-venture-v2 yet).
-- Querying /baseline for a crop that satisfies (1) but not (2) reached
-- agri-venture-v2 and failed with an opaque 502 instead of a clean,
-- specific error.
--
-- agriventure_crop_key is nullable: NULL means "CORWADO tracks this
-- crop, but no biophysical scoring source exists yet" -- get_baseline()
-- in app/routers/advisory.py checks this before ever calling
-- BiophysicalEngine. Added as an explicit ALTER rather than rewritten
-- into crop_dictionary_entry's original CREATE TABLE, consistent with
-- every other migration in this file.
-- ---------------------------------------------------------------------
ALTER TABLE crop_dictionary_entry
    ADD COLUMN agriventure_crop_key TEXT;

-- ---------------------------------------------------------------------
-- Migration: parcel_diagnostic — caches agri-venture-v2's Stage 1
-- LandDiagnostic ("FarmLab report") per parcel.
--
-- Deliberately a SEPARATE table from parcel_crop_baseline above, not a
-- reuse of it: parcel_crop_baseline is a per-(parcel, crop) suitability
-- verdict (UNIQUE on parcel_id+crop_id, one row per crop a farmer might
-- grow on that land). The Land Diagnostic is a different shape entirely
-- — a crop-independent "lab report" of the parcel itself (climate, soil,
-- water, vegetation, topography, land use, carbon), computed once per
-- parcel regardless of which crop is being considered. UNIQUE on
-- parcel_id alone (not parcel_id+crop_id) reflects that: there is
-- exactly one Land Diagnostic per parcel, never one per crop.
--
-- Same tiered slow-data caching pattern as parcel_crop_baseline
-- (computed_at/refresh_due, checked before recomputing) — see
-- get_diagnostic() in app/routers/advisory.py.
-- ---------------------------------------------------------------------
CREATE TABLE parcel_diagnostic (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parcel_id    UUID NOT NULL REFERENCES parcel(id) UNIQUE,
    diagnostic   JSONB,       -- full LandDiagnostic response, unmodified
    depth        TEXT,        -- 'quick' or 'full' — whichever was actually run
    computed_at  TIMESTAMPTZ,
    refresh_due  TIMESTAMPTZ
);

-- ---------------------------------------------------------------------
-- Migration: Bill of Quantities (input_requirement) + financing ledger
-- (input_financing_record), scoped per planting cycle via
-- season_planting (already existed in this file but had no writer yet
-- — nothing created a row until this migration's season CRUD).
--
-- Explicitly a transparent record-keeping tool, NOT a creditworthiness
-- or eligibility signal — same firewall this project enforces
-- everywhere else (CORWADO never assesses the person, only records
-- facts). Nothing here computes a score, a recommendation, or an
-- approve/decline verdict.
--
-- All costs stored in USD (CORWADO's own currency, per the existing
-- financial proposal). agri-venture-v2's economics.json (the one real
-- cost dataset that exists, for maize) is priced in KES -- confirmed by
-- reading the file directly, not assumed. Converting KES-sourced figures
-- to USD without a real, dated, cited rate would be inventing a number
-- wearing a real-data costume, so every conversion carries its own
-- fx_rate_used/fx_rate_date/fx_rate_source alongside the original
-- currency and amount -- the conversion is auditable and correctable
-- later, never silently baked in.
-- ---------------------------------------------------------------------
CREATE TYPE input_category AS ENUM ('seed', 'fertilizer', 'pesticide', 'labour', 'other');
CREATE TYPE financier_type AS ENUM ('farmer', 'corwado', 'financial_institution', 'government', 'ngo');

CREATE TABLE input_requirement (
    id                        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    season_planting_id        UUID NOT NULL REFERENCES season_planting(id),
    item_name                 TEXT NOT NULL,
    category                  input_category NOT NULL,
    quantity                  NUMERIC NOT NULL,
    unit                      TEXT NOT NULL,
    unit_cost_usd             NUMERIC NOT NULL,
    -- GENERATED, same pattern as parcel.area_acres above -- can never
    -- drift out of sync with quantity/unit_cost_usd.
    total_cost_usd            NUMERIC GENERATED ALWAYS AS (quantity * unit_cost_usd) STORED,
    currency                  TEXT NOT NULL DEFAULT 'USD',

    -- Where THIS line item's cost actually came from -- the Scientific
    -- Evidence Rule applied to a cost figure instead of a suitability
    -- factor.
    cost_source               TEXT NOT NULL,   -- e.g. 'agriventure_kalro_baseline' | 'corwado_override' | 'farmer_reported'
    baseline_unit_cost_usd    NUMERIC,          -- the original agri-venture-v2 (or first-recorded) figure, preserved even after an override
    source_currency_original  TEXT,             -- e.g. 'KES'; NULL if the source was already USD
    source_amount_original    NUMERIC,          -- the pre-conversion figure in source_currency_original
    fx_rate_used              NUMERIC,          -- e.g. 129.19 (units of source_currency_original per 1 USD)
    fx_rate_date              DATE,             -- the date that rate was published/valid for
    fx_rate_source            TEXT,             -- citation, e.g. "Wise mid-market rate, https://wise.com/..., retrieved 2026-07-12"

    -- Override provenance -- never a silent replacement (see
    -- baseline_unit_cost_usd above, which this never overwrites).
    override_reason           TEXT,
    override_by               TEXT,
    override_at               TIMESTAMPTZ,

    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Linked to individual input_requirement rows, NOT the BoQ as a whole:
-- the point of this ledger is comparing external support to what the
-- farmer actually buys, and that comparison only means something at
-- line-item resolution ("CORWADO funded fertilizer, farmer paid for
-- seed") -- an aggregate "someone funded $340 of $500" loses exactly the
-- distinction this feature exists to make. Plain FK with no uniqueness
-- constraint -- multiple rows may reference the same input_requirement,
-- which is how partial/split funding (e.g. 60% CORWADO + 40% farmer on
-- one line item) falls out of this schema for free, with no special-case
-- modeling.
CREATE TABLE input_financing_record (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    input_requirement_id   UUID NOT NULL REFERENCES input_requirement(id),
    financier_type         financier_type NOT NULL,
    financier_name         TEXT,             -- optional, e.g. "Equity Bank"; NULL if not tracked
    amount_usd             NUMERIC NOT NULL,
    currency               TEXT NOT NULL DEFAULT 'USD',
    financed_at            DATE NOT NULL,    -- when the financing/payment actually happened
    notes                  TEXT,
    recorded_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Migration: Telegram inbound handling -- the first two-way channel in
-- this platform. Everything up to this point (message_dispatch) is
-- outbound-tracking only; a farmer's reply needs a different table and
-- a different identity link, not a repurposed one -- same discipline as
-- the crop_dictionary_entry split (Day 15 migration above): two
-- distinct jobs get two distinct homes.
--
-- telegram_chat_id lives directly on land_steward, not a separate
-- linking table -- it's the same shape as phone_number/whatsapp_number
-- above (one identifier, one steward, 1:1). A join table would only
-- earn its keep if a steward could plausibly hold multiple Telegram
-- accounts, which isn't a real scenario here. UNIQUE (not just
-- indexed): two stewards must never resolve to the same chat_id, since
-- that chat_id is the only way an inbound message gets attributed back
-- to a real person.
-- ---------------------------------------------------------------------
ALTER TABLE land_steward
    ADD COLUMN telegram_chat_id TEXT UNIQUE;

CREATE INDEX idx_land_steward_telegram_chat ON land_steward(telegram_chat_id);

-- inbound_message: deliberately separate from message_dispatch (outbound
-- only, see Section 6 above). steward_id is nullable until a REGISTER
-- command links the chat_id to a real land_steward row; external_chat_id
-- is kept regardless, so an unlinked sender's message isn't lost.
-- channel is plain TEXT, not an ENUM like dispatch_channel -- Telegram is
-- the only real inbound channel today, and an ENUM would need its own
-- migration the moment a second one (e.g. inbound WhatsApp) shows up.
CREATE TABLE inbound_message (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    steward_id        UUID REFERENCES land_steward(id),
    channel           TEXT NOT NULL DEFAULT 'telegram',
    external_chat_id  TEXT NOT NULL,
    raw_text          TEXT NOT NULL,
    parsed_intent     TEXT,       -- 'register' | 'price_lookup' | 'status_check' | 'unrecognized'
    parsed_params     JSONB,      -- e.g. {"crop": "maize"} for price_lookup
    response_text     TEXT,       -- what the bot actually replied -- audit trail
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at      TIMESTAMPTZ
);

CREATE INDEX idx_inbound_message_steward ON inbound_message(steward_id);
CREATE INDEX idx_inbound_message_chat ON inbound_message(external_chat_id);

-- ---------------------------------------------------------------------
-- Migration: 'telegram' as a real outbound channel -- the first channel
-- to move dispatch_to_steward() past "queued" (logged only) to an
-- actual send. Two places name the allowed channel set, both need it:
-- dispatch_channel (message_dispatch.channel) and land_steward's
-- preferred_channel CHECK constraint. The latter was assumed to be
-- unconstrained free text going into this migration -- it isn't; it's
-- CHECK-restricted to the original six values, so 'telegram' would have
-- been silently rejected by Postgres without this.
-- ---------------------------------------------------------------------
ALTER TYPE dispatch_channel ADD VALUE 'telegram';

ALTER TABLE land_steward
    DROP CONSTRAINT land_steward_preferred_channel_check,
    ADD CONSTRAINT land_steward_preferred_channel_check
        CHECK (preferred_channel IN ('sms','ussd','ivr','whatsapp','radio','in_person','telegram'));

-- delivery_note: nowhere to record *why* a dispatch fell back or
-- failed until now -- every prior channel only ever logged the routing
-- decision (see message_dispatch's original comment), so a bare
-- delivery_status was enough. Telegram's real send needs somewhere to
-- put "no linked telegram_chat_id, fell back to queued" or the actual
-- Telegram API failure reason. NULL for every dispatch that doesn't
-- need one -- every non-Telegram channel, and every successful send.
ALTER TABLE message_dispatch
    ADD COLUMN delivery_note TEXT;

-- ---------------------------------------------------------------------
-- Migration: numbered-menu state for the Telegram bot (USSD-style
-- REGISTER/PRICE/STATUS menu, replacing free-text-only commands).
-- REGISTER and PRICE both need a follow-up message (a phone number, a
-- crop choice) before they can resolve -- a single 'awaiting' field per
-- chat is enough to track that one pending question; this is not a
-- session or conversation-tree table.
--
-- Deliberately its own table, NOT a column on land_steward: REGISTER has
-- to work before any land_steward row is linked to this chat_id (that
-- link is the whole point of REGISTER), so the pending-question state
-- can't live on a table row that doesn't exist yet for an unlinked chat.
-- Same reasoning already used for inbound_message/telegram_chat_id above
-- -- external_chat_id is the identity that's always available; steward
-- linkage is a fact that may or may not exist yet.
--
-- One row per chat, upserted in place (not inserted per-question) --
-- awaiting is nulled out once the follow-up is answered or cancelled,
-- the row itself persists.
-- ---------------------------------------------------------------------
CREATE TABLE telegram_conversation_state (
    chat_id     TEXT PRIMARY KEY,
    awaiting    TEXT,       -- 'phone_for_register' | 'crop_for_price' | NULL
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Migration: chat-based registration for CORWADO staff / Digital
-- Champions -- lets an authorized operator create a new land_steward
-- and register a farm boundary on someone's behalf via Telegram, not
-- just link their own existing record (the REGISTER flow above).
--
-- authorized_operator is a SEPARATE table from land_steward, not a role
-- flag on it -- the two ideas are genuinely different facts (a person
-- CORWADO trusts to act on others' records vs. a farmer's own profile)
-- and a person can plausibly be both (a Digital Champion who is also a
-- registered farmer), so collapsing them into one row with a role flag
-- would make that dual case awkward to represent.
--
-- Populated ONLY by an admin action (POST /api/authorized-operators) --
-- never by a chat message. telegram_chat_id starts NULL and is filled
-- in by the operator sending "STAFF <phone>" to the bot, same linking
-- pattern as land_steward.telegram_chat_id/REGISTER above (see that
-- migration's note) -- the phone number has to already be on this table
-- for the link to succeed, so self-registration still isn't possible.
--
-- is_active, not a DELETE: revoking access needs to stay an auditable
-- fact ("X was authorized, then revoked on date Y"), same reasoning as
-- registered_offline being permanent on land_steward -- never silently
-- erased by turning access off.
--
-- role is descriptive/reporting metadata only (M&E: how many Digital
-- Champions vs. CORWADO staff are using this) -- it does NOT gate
-- either capability differently. Both NEWFARMER (creating a new
-- land_steward) and BOUNDARY (registering/editing a boundary on
-- someone's behalf) check the exact same thing: an active row here
-- linked to the sending chat_id. One gate, two capabilities -- not two
-- separate authorization systems.
-- ---------------------------------------------------------------------
CREATE TABLE authorized_operator (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name         TEXT NOT NULL,
    phone_number      TEXT NOT NULL UNIQUE,
    role              TEXT CHECK (role IN ('corwado_staff', 'digital_champion')),
    telegram_chat_id  TEXT UNIQUE,
    added_by          TEXT NOT NULL,   -- admin who authorized this person -- audit trail
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_authorized_operator_chat ON authorized_operator(telegram_chat_id);

-- context: NEWFARMER is a multi-step form (name -> phone -> gender)
-- collected across several inbound messages, unlike REGISTER/PRICE
-- which each resolve from a single follow-up reply. The existing
-- `awaiting` column only tracks WHAT question is pending, not the
-- answers already collected -- this holds those, same JSONB-scratch-
-- space idiom already used by inbound_message.parsed_params. Cleared
-- alongside `awaiting` on cancel or once the form completes.
ALTER TABLE telegram_conversation_state
    ADD COLUMN context JSONB NOT NULL DEFAULT '{}';

-- parcel_draw_token: the single-use, time-limited credential that lets
-- the public draw-boundary web page (no dashboard login exists anywhere
-- in this project) accept one boundary submission for one specific
-- steward. Minted by the BOUNDARY chat command (secrets.token_urlsafe --
-- unguessable, not just unique, since it carries the entire
-- authorization for that page). used_at is set atomically with the
-- parcel insert it authorizes (same transaction, see
-- app/routers/parcels.py) so a token can never be replayed even under a
-- race between two concurrent submissions.
CREATE TABLE parcel_draw_token (
    token                 TEXT PRIMARY KEY,
    steward_id            UUID NOT NULL REFERENCES land_steward(id),
    originating_chat_id   TEXT NOT NULL,   -- where the real save confirmation gets pushed back to
    expires_at            TIMESTAMPTZ NOT NULL,
    used_at               TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_parcel_draw_token_steward ON parcel_draw_token(steward_id);
