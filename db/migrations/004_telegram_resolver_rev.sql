-- ============================================================
-- 004_telegram_resolver_rev — SUPERSEDES 002_telegram_resolver.sql.
--
-- 002 creates `corwado_resolver` as a BYPASSRLS role. Only a SUPERUSER can
-- create a BYPASSRLS role; Render's owner role (corwado_platform_user) is
-- NOSUPERUSER, so 002 aborts at its first statement on Render and rolls back
-- atomically. 002 must NOT be applied to prod. This migration delivers the
-- same outcome — a narrow, context-free chat_id/phone -> org resolver for
-- session-less inbound — with NO superuser-only object.
--
-- Mechanism (role-scoped permissive policy, NOT a session GUC):
--   * `corwado_resolver` is a plain NOLOGIN, NON-BYPASSRLS role (a CREATEROLE
--     owner can create it).
--   * The SECURITY DEFINER resolver functions are OWNED BY corwado_resolver,
--     so they execute as that role.
--   * A permissive policy `resolver_read FOR SELECT TO corwado_resolver
--     USING (true)` on authorized_operator + land_steward gives ONLY that
--     role (i.e. only code inside these functions) the context-free read.
--   * FORCE ROW LEVEL SECURITY stays on every table. corwado_app may EXECUTE
--     the functions but, being a different role, never receives the
--     permissive policy — it cannot read those tables cross-tenant directly.
--   * No session variable is used, so there is no pooled-connection leakage
--     surface. Full analysis in db/SECURITY_resolver.md.
--
-- Idempotent: safe to re-run. Creates corwado_resolver only if absent (never
-- attempts the superuser-only ALTER ... BYPASSRLS).
-- ============================================================
BEGIN;

-- Plain, login-less, NON-BYPASSRLS role that owns the resolver functions.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'corwado_resolver') THEN
    CREATE ROLE corwado_resolver NOLOGIN NOBYPASSRLS;
  END IF;
END $$;

-- The migration runner (Render's owner role) must be able to SET ROLE to
-- corwado_resolver, otherwise `ALTER FUNCTION ... OWNER TO corwado_resolver`
-- below fails with "must be able to SET ROLE". In PG16+, creating a role
-- grants the creator ADMIN OPTION but NOT the SET option, so grant ourselves
-- membership explicitly (we hold ADMIN from having created it).
-- INHERIT FALSE is LOAD-BEARING: without it the option defaults to the
-- grantee's rolinherit (TRUE for the owner), and the owner would then INHERIT
-- corwado_resolver's resolver_read policy + function EXECUTE and be able to
-- read the identity tables with no tenant context. SET alone is all ALTER
-- OWNER needs. (The first apply of 004 shipped WITHOUT `INHERIT FALSE` and
-- leaked; migration 005 corrects environments where that version already ran,
-- incl. prod. A superuser would never hit any of this — the Render-equivalent
-- non-superuser harness is what surfaced it.)
DO $$
BEGIN
  EXECUTE format('GRANT corwado_resolver TO %I WITH SET TRUE, INHERIT FALSE', current_user);
END $$;

-- USAGE + CREATE on public: CREATE is required because a role can only OWN an
-- object in a schema where it holds CREATE (the ALTER FUNCTION ... OWNER TO
-- corwado_resolver below fails "permission denied for schema public" without
-- it). corwado_resolver is NOLOGIN and reachable only via the SECURITY DEFINER
-- functions, so this CREATE is not a usable attack surface. (Superuser-masked;
-- surfaced by the Render-equivalent test.)
GRANT USAGE, CREATE ON SCHEMA public TO corwado_resolver;
GRANT SELECT ON authorized_operator, land_steward, organization TO corwado_resolver;

-- Role-scoped permissive read window: applies ONLY when the current role is
-- corwado_resolver (only inside the SECURITY DEFINER functions below).
-- Permissive policies OR-combine with tenant_isolation; because this one is
-- TO corwado_resolver it never widens any other role's access.
DROP POLICY IF EXISTS resolver_read ON authorized_operator;
CREATE POLICY resolver_read ON authorized_operator
  FOR SELECT TO corwado_resolver USING (true);
DROP POLICY IF EXISTS resolver_read ON land_steward;
CREATE POLICY resolver_read ON land_steward
  FOR SELECT TO corwado_resolver USING (true);

-- Resolution logic is IDENTICAL to 002; only the owning role differs.
CREATE OR REPLACE FUNCTION resolve_chat_org(p_chat_id text, p_channel text DEFAULT 'telegram')
RETURNS TABLE(organization_id uuid, org_status text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT organization_id, org_status FROM (
    SELECT o.id AS organization_id, o.status AS org_status, 1 AS pri
    FROM authorized_operator ao JOIN organization o ON o.id = ao.organization_id
    WHERE ao.telegram_chat_id = p_chat_id AND ao.is_active
    UNION ALL
    SELECT o.id, o.status, 2
    FROM land_steward ls JOIN organization o ON o.id = ls.organization_id
    WHERE (p_channel = 'telegram' AND ls.telegram_chat_id = p_chat_id)
       OR (p_channel = 'whatsapp' AND ls.whatsapp_number = p_chat_id)
  ) t
  ORDER BY pri
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION resolve_phone_org(p_phone text, p_channel text DEFAULT 'telegram')
RETURNS TABLE(organization_id uuid, org_status text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT organization_id, org_status FROM (
    SELECT o.id AS organization_id, o.status AS org_status, 1 AS pri
    FROM authorized_operator ao JOIN organization o ON o.id = ao.organization_id
    WHERE ao.phone_number = p_phone AND ao.is_active
    UNION ALL
    SELECT o.id, o.status, 2
    FROM land_steward ls JOIN organization o ON o.id = ls.organization_id
    WHERE ls.phone_number = p_phone
  ) t
  ORDER BY pri
  LIMIT 1;
$$;

ALTER FUNCTION resolve_chat_org(text, text) OWNER TO corwado_resolver;
ALTER FUNCTION resolve_phone_org(text, text) OWNER TO corwado_resolver;

-- Lock EXECUTE down to corwado_app only. Functions default to EXECUTE for
-- PUBLIC; a SECURITY DEFINER function readable by anyone is a footgun, so
-- revoke PUBLIC and grant only the app role. (Tightening beyond 002, which
-- relied on the implicit PUBLIC grant.)
REVOKE EXECUTE ON FUNCTION resolve_chat_org(text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION resolve_phone_org(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION resolve_chat_org(text, text) TO corwado_app;
GRANT EXECUTE ON FUNCTION resolve_phone_org(text, text) TO corwado_app;

-- Fork A (verbatim from 002): inbound_message + parcel_draw_token are
-- pre-identity tables — rows arrive before any org is known. 001 made them
-- NOT NULL + FORCE RLS, which breaks the inbound write path. Relax to
-- RLS-exempt + nullable org, stamped when known, NULL when not. Idempotent.
ALTER TABLE inbound_message   NO FORCE ROW LEVEL SECURITY;
ALTER TABLE inbound_message   DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON inbound_message;
ALTER TABLE inbound_message   ALTER COLUMN organization_id DROP NOT NULL;

ALTER TABLE parcel_draw_token NO FORCE ROW LEVEL SECURITY;
ALTER TABLE parcel_draw_token DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON parcel_draw_token;
ALTER TABLE parcel_draw_token ALTER COLUMN organization_id DROP NOT NULL;

COMMIT;
