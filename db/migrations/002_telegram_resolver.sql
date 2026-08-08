-- ============================================================
-- 002_telegram_resolver — establish a tenant context for public,
-- session-less inbound (Telegram/WhatsApp).
--
-- The problem: an inbound chat message has no logged-in staff, so there is
-- no app.current_org to scope RLS by; but the identity tables that would
-- tell us which org the chat belongs to (authorized_operator, land_steward)
-- are themselves RLS-protected, so a session with no context can't read
-- them. Chicken-and-egg.
--
-- The seam: a narrow SECURITY DEFINER function owned by a dedicated
-- BYPASSRLS role that does exactly ONE thing — resolve an identity key
-- (chat_id or phone) to its organization_id + status. It reads nothing
-- else and returns nothing else. The application then EXPLICITLY re-applies
-- that org as the normal app.current_org GUC, and every subsequent read/
-- write runs under ordinary RLS. RLS is never bypassed for the request
-- itself — only this one lookup.
-- ============================================================
BEGIN;

-- Dedicated, login-less, BYPASSRLS role that owns the resolvers.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'corwado_resolver') THEN
    CREATE ROLE corwado_resolver NOLOGIN BYPASSRLS;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO corwado_resolver;
GRANT SELECT ON authorized_operator, land_steward, organization TO corwado_resolver;

-- Resolve a chat identity (already-linked operator or steward) to its org.
-- Operator-first precedence (pri=1) matches the handler's own dual-role rule.
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

-- Resolve a phone number to its org — used only by the linking commands
-- (REGISTER <phone> / STAFF <phone>), which by definition arrive on a chat
-- that is not yet linked, so resolve_chat_org above returns nothing for them.
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
GRANT EXECUTE ON FUNCTION resolve_chat_org(text, text) TO corwado_app;
GRANT EXECUTE ON FUNCTION resolve_phone_org(text, text) TO corwado_app;

-- Fork A: inbound_message and parcel_draw_token are PRE-IDENTITY tables —
-- they legitimately receive rows from unlinked/unknown senders (an inbound
-- message logged before any org is known; a draw token minted mid-flow).
-- 001 made them NOT NULL + RLS like every other tenant table, which is wrong
-- for their purpose: an unknown sender has no org, so that insert can't
-- satisfy the policy. Relax both to RLS-exempt with a nullable
-- organization_id, stamped when the org IS known, NULL when it isn't —
-- mirroring the telegram_conversation_state exemption already in place.
ALTER TABLE inbound_message   NO FORCE ROW LEVEL SECURITY;
ALTER TABLE inbound_message   DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON inbound_message;
ALTER TABLE inbound_message   ALTER COLUMN organization_id DROP NOT NULL;

ALTER TABLE parcel_draw_token NO FORCE ROW LEVEL SECURITY;
ALTER TABLE parcel_draw_token DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON parcel_draw_token;
ALTER TABLE parcel_draw_token ALTER COLUMN organization_id DROP NOT NULL;

COMMIT;
