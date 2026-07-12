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
