-- ============================================================
-- 006_consultant_and_audit — implements the signed db/ACCESS_MATRIX.md:
-- the consultant role, org-admin activation, and landlord write auditing.
--
-- Depends on 001 (tenant tables + RLS) and 004 (role-scoped pattern; note 004
-- made inbound_message + parcel_draw_token RLS-EXEMPT — the consultant role must
-- never receive a grant on those, or reads would cross tenants).
--
-- Same discipline as 004/005: NO superuser-only object. Every role is NON-BYPASSRLS
-- and creatable by Render's CREATEROLE owner; prove on the Render-equivalent
-- non-superuser harness (db/test_migrations_render_equiv.sh) before prod.
-- Idempotent where practical (IF NOT EXISTS / DROP-then-create).
--
--   A. consultant_account + consultant_grant  (control-plane tables, NOT tenant-
--      RLS'd — like staff_account/platform_admin; the app + the read-only role
--      enforce access, never a blanket grant).
--   B. corwado_consultant  — NOLOGIN NON-BYPASSRLS read-only role. SELECT on the
--      allowed classes ONLY (parcels + business registry + global crops); NO grant
--      on BoQ / operator+farmer PII / control-plane / RLS-exempt tables. The app
--      activates it with SET LOCAL ROLE after verifying an active grant; RLS still
--      scopes every read to app.current_org. "No BoQ/PII" is a Postgres privilege,
--      not an app convention.
--   C. landlord_audit_log + a SECURITY DEFINER trigger on the 19 FORCE-RLS tenant
--      tables that logs any write performed under app.platform_admin='on'. Makes
--      the landlord's procedural write-restraint verifiable, not merely asserted.
--
-- org-admin: NO schema change — the existing staff_account.role='admin' (dormant
-- since 001) becomes the org-admin. Enforcement (who may approve consultant grants
-- / manage operators) is app-layer; this migration only relies on the column.
-- ============================================================
BEGIN;

-- ---------- A. consultant identity + grants (control plane, no tenant RLS) ----------
CREATE TABLE IF NOT EXISTS consultant_account (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS consultant_grant (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    consultant_id UUID NOT NULL REFERENCES consultant_account(id),
    organization_id UUID NOT NULL REFERENCES organization(id),
    -- requested -> active (org-admin approves) -> revoked (org-admin revokes).
    status TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','active','revoked')),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at  TIMESTAMPTZ,
    approved_by  UUID REFERENCES staff_account(id),   -- must be role='admin' (app-enforced)
    revoked_at   TIMESTAMPTZ,
    review_due   DATE,                                -- persist-until-revoked + logged review date
    UNIQUE (consultant_id, organization_id)
);
-- Deliberately NO ENABLE ROW LEVEL SECURITY: these mirror staff_account /
-- platform_admin (identity/control-plane). corwado_consultant gets NO grant on
-- them; the app scopes access (org-admins see their org's grants; a consultant
-- sees their own). The GATING check in get_current_consultant runs as corwado_app.

-- ---------- B. read-only consultant role ----------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'corwado_consultant') THEN
    CREATE ROLE corwado_consultant NOLOGIN NOBYPASSRLS;
  END IF;
END $$;

-- The app may SET ROLE to it, but must NOT ambiently inherit it (005 hygiene:
-- INHERIT FALSE, so activation is explicit per transaction, never ambient).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'corwado_app') THEN
    EXECUTE 'GRANT corwado_consultant TO corwado_app WITH SET TRUE, INHERIT FALSE';
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO corwado_consultant;

-- ALLOWED (SELECT only; RLS scopes each to app.current_org):
--   parcels / geometry / agronomy (land_steward EXCLUDED — farmer PII):
GRANT SELECT ON parcel, parcel_diagnostic, parcel_crop_baseline,
                season_planting, advisory_snapshot TO corwado_consultant;
--   business registry / market (no farmer PII):
GRANT SELECT ON cooperative, buyer, buyer_posting, agro_dealer,
                radio_station, radio_broadcast_slot, price_board_entry TO corwado_consultant;
--   global reference:
GRANT SELECT ON crop_dictionary_entry TO corwado_consultant;
-- STRUCTURALLY DENIED (no grant -> unreadable, and no write grant anywhere):
--   input_requirement, input_financing_record            (BoQ / financial — never)
--   authorized_operator, staff_account, land_steward,
--   inbound_message                                       (operator/farmer identity — never)
--   aggregation_event, aggregation_contribution,
--   message_dispatch                                      (farmer-linked / messaging — v1 defer)
--   organization                                          (would expose all org names; not RLS'd)
--   parcel_draw_token, inbound_message                    (RLS-exempt -> would cross tenants)
--   consultant_account, consultant_grant, platform_admin,
--   landlord_audit_log                                    (control plane)
-- FarmTrace compliance-output tables do not exist yet (registry 2.3); their
-- SELECT grant to corwado_consultant is added when 2.3 creates them.

-- ---------- C. landlord write audit ----------
CREATE TABLE IF NOT EXISTS landlord_audit_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    platform_admin_id UUID,          -- from app.platform_admin_id (nullable if unset)
    action     TEXT NOT NULL,        -- INSERT / UPDATE / DELETE
    table_name TEXT NOT NULL,
    row_id     TEXT,                 -- affected row's id (best-effort)
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_data   JSONB                 -- NEW (ins/upd) or OLD (del) snapshot
);
GRANT SELECT ON landlord_audit_log TO corwado_app;  -- landlord reads its own trail

-- SECURITY DEFINER (owned by the migration runner = the DB owner) so the audit
-- insert always succeeds and corwado_app can neither forge nor suppress a row.
CREATE OR REPLACE FUNCTION log_landlord_write() RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_on   text := current_setting('app.platform_admin', true);
  v_who  text := current_setting('app.platform_admin_id', true);
  v_row  jsonb;
BEGIN
  IF v_on IS DISTINCT FROM 'on' THEN
    RETURN NULL;                     -- only landlord-context writes are audited
  END IF;
  IF TG_OP = 'DELETE' THEN v_row := to_jsonb(OLD); ELSE v_row := to_jsonb(NEW); END IF;
  INSERT INTO landlord_audit_log (platform_admin_id, action, table_name, row_id, row_data)
  VALUES (NULLIF(v_who, '')::uuid, TG_OP, TG_TABLE_NAME, v_row->>'id', v_row);
  RETURN NULL;                       -- AFTER trigger
END $$;
REVOKE EXECUTE ON FUNCTION log_landlord_write() FROM PUBLIC;

-- Attach to the 19 FORCE-RLS tenant tables (001's set minus the two RLS-exempt
-- pre-identity tables inbound_message + parcel_draw_token).
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT unnest(ARRAY[
    'cooperative','land_steward','parcel','season_planting','advisory_snapshot',
    'price_board_entry','buyer','buyer_posting','aggregation_event',
    'aggregation_contribution','radio_station','radio_broadcast_slot','agro_dealer',
    'message_dispatch','parcel_crop_baseline','parcel_diagnostic','input_requirement',
    'input_financing_record','authorized_operator'])
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_landlord_audit ON %I', t);
    EXECUTE format(
      'CREATE TRIGGER trg_landlord_audit AFTER INSERT OR UPDATE OR DELETE ON %I '
      'FOR EACH ROW EXECUTE FUNCTION log_landlord_write()', t);
  END LOOP;
END $$;

COMMIT;
