-- 001_multitenancy — organizations + RLS tenant isolation.
-- Ordering is load-bearing: backfill BEFORE SET NOT NULL, so SET NOT NULL
-- fails loudly if any row was missed (self-verifying zero-orphan).
BEGIN;

CREATE TABLE organization (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    short_code TEXT UNIQUE,
    country TEXT,
    contact_name TEXT,
    contact_phone TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','suspended')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE staff_account (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organization(id),
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin','staff')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, email)
);

CREATE TABLE platform_admin (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO organization (name, short_code, country, status)
VALUES ('Consortium of Rural Women for Agribusiness Development Organization',
        'corwado', 'South Sudan', 'active');

-- 1. cooperative
ALTER TABLE cooperative ADD COLUMN organization_id UUID;
UPDATE cooperative SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE cooperative ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE cooperative ADD CONSTRAINT cooperative_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE cooperative ENABLE ROW LEVEL SECURITY;
ALTER TABLE cooperative FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON cooperative
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 2. land_steward
ALTER TABLE land_steward ADD COLUMN organization_id UUID;
UPDATE land_steward SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE land_steward ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE land_steward ADD CONSTRAINT land_steward_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE land_steward ENABLE ROW LEVEL SECURITY;
ALTER TABLE land_steward FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON land_steward
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 3. parcel
ALTER TABLE parcel ADD COLUMN organization_id UUID;
UPDATE parcel SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE parcel ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE parcel ADD CONSTRAINT parcel_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE parcel ENABLE ROW LEVEL SECURITY;
ALTER TABLE parcel FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON parcel
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 4. season_planting
ALTER TABLE season_planting ADD COLUMN organization_id UUID;
UPDATE season_planting SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE season_planting ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE season_planting ADD CONSTRAINT season_planting_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE season_planting ENABLE ROW LEVEL SECURITY;
ALTER TABLE season_planting FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON season_planting
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 5. advisory_snapshot
ALTER TABLE advisory_snapshot ADD COLUMN organization_id UUID;
UPDATE advisory_snapshot SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE advisory_snapshot ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE advisory_snapshot ADD CONSTRAINT advisory_snapshot_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE advisory_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE advisory_snapshot FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON advisory_snapshot
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 6. price_board_entry
ALTER TABLE price_board_entry ADD COLUMN organization_id UUID;
UPDATE price_board_entry SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE price_board_entry ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE price_board_entry ADD CONSTRAINT price_board_entry_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE price_board_entry ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_board_entry FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON price_board_entry
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 7. buyer
ALTER TABLE buyer ADD COLUMN organization_id UUID;
UPDATE buyer SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE buyer ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE buyer ADD CONSTRAINT buyer_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE buyer ENABLE ROW LEVEL SECURITY;
ALTER TABLE buyer FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON buyer
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 8. buyer_posting
ALTER TABLE buyer_posting ADD COLUMN organization_id UUID;
UPDATE buyer_posting SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE buyer_posting ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE buyer_posting ADD CONSTRAINT buyer_posting_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE buyer_posting ENABLE ROW LEVEL SECURITY;
ALTER TABLE buyer_posting FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON buyer_posting
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 9. aggregation_event
ALTER TABLE aggregation_event ADD COLUMN organization_id UUID;
UPDATE aggregation_event SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE aggregation_event ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE aggregation_event ADD CONSTRAINT aggregation_event_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE aggregation_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE aggregation_event FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON aggregation_event
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 10. aggregation_contribution
ALTER TABLE aggregation_contribution ADD COLUMN organization_id UUID;
UPDATE aggregation_contribution SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE aggregation_contribution ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE aggregation_contribution ADD CONSTRAINT aggregation_contribution_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE aggregation_contribution ENABLE ROW LEVEL SECURITY;
ALTER TABLE aggregation_contribution FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON aggregation_contribution
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 11. radio_station
ALTER TABLE radio_station ADD COLUMN organization_id UUID;
UPDATE radio_station SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE radio_station ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE radio_station ADD CONSTRAINT radio_station_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE radio_station ENABLE ROW LEVEL SECURITY;
ALTER TABLE radio_station FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON radio_station
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 12. radio_broadcast_slot
ALTER TABLE radio_broadcast_slot ADD COLUMN organization_id UUID;
UPDATE radio_broadcast_slot SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE radio_broadcast_slot ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE radio_broadcast_slot ADD CONSTRAINT radio_broadcast_slot_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE radio_broadcast_slot ENABLE ROW LEVEL SECURITY;
ALTER TABLE radio_broadcast_slot FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON radio_broadcast_slot
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 13. agro_dealer
ALTER TABLE agro_dealer ADD COLUMN organization_id UUID;
UPDATE agro_dealer SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE agro_dealer ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE agro_dealer ADD CONSTRAINT agro_dealer_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE agro_dealer ENABLE ROW LEVEL SECURITY;
ALTER TABLE agro_dealer FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON agro_dealer
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 14. message_dispatch
ALTER TABLE message_dispatch ADD COLUMN organization_id UUID;
UPDATE message_dispatch SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE message_dispatch ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE message_dispatch ADD CONSTRAINT message_dispatch_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE message_dispatch ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_dispatch FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON message_dispatch
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 15. parcel_crop_baseline
ALTER TABLE parcel_crop_baseline ADD COLUMN organization_id UUID;
UPDATE parcel_crop_baseline SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE parcel_crop_baseline ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE parcel_crop_baseline ADD CONSTRAINT parcel_crop_baseline_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE parcel_crop_baseline ENABLE ROW LEVEL SECURITY;
ALTER TABLE parcel_crop_baseline FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON parcel_crop_baseline
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 16. parcel_diagnostic
ALTER TABLE parcel_diagnostic ADD COLUMN organization_id UUID;
UPDATE parcel_diagnostic SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE parcel_diagnostic ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE parcel_diagnostic ADD CONSTRAINT parcel_diagnostic_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE parcel_diagnostic ENABLE ROW LEVEL SECURITY;
ALTER TABLE parcel_diagnostic FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON parcel_diagnostic
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 17. input_requirement
ALTER TABLE input_requirement ADD COLUMN organization_id UUID;
UPDATE input_requirement SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE input_requirement ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE input_requirement ADD CONSTRAINT input_requirement_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE input_requirement ENABLE ROW LEVEL SECURITY;
ALTER TABLE input_requirement FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON input_requirement
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 18. input_financing_record
ALTER TABLE input_financing_record ADD COLUMN organization_id UUID;
UPDATE input_financing_record SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE input_financing_record ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE input_financing_record ADD CONSTRAINT input_financing_record_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE input_financing_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE input_financing_record FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON input_financing_record
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 19. inbound_message
ALTER TABLE inbound_message ADD COLUMN organization_id UUID;
UPDATE inbound_message SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE inbound_message ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE inbound_message ADD CONSTRAINT inbound_message_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE inbound_message ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_message FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON inbound_message
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 20. authorized_operator
ALTER TABLE authorized_operator ADD COLUMN organization_id UUID;
UPDATE authorized_operator SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE authorized_operator ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE authorized_operator ADD CONSTRAINT authorized_operator_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE authorized_operator ENABLE ROW LEVEL SECURITY;
ALTER TABLE authorized_operator FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON authorized_operator
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- 21. parcel_draw_token
ALTER TABLE parcel_draw_token ADD COLUMN organization_id UUID;
UPDATE parcel_draw_token SET organization_id = (SELECT id FROM organization WHERE short_code='corwado');
ALTER TABLE parcel_draw_token ALTER COLUMN organization_id SET NOT NULL;
ALTER TABLE parcel_draw_token ADD CONSTRAINT parcel_draw_token_org_fk FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE parcel_draw_token ENABLE ROW LEVEL SECURITY;
ALTER TABLE parcel_draw_token FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON parcel_draw_token
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on')
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
         OR current_setting('app.platform_admin', true) = 'on');

-- Deliberate exclusions:
--   crop_dictionary_entry       -> global reference data, shared across orgs.
--   telegram_conversation_state -> pre-identity chat scratch keyed by chat_id.

COMMIT;
