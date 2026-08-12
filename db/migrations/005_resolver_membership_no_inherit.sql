-- ============================================================
-- 005_resolver_membership_no_inherit — CORRECTIVE, for already-applied 004.
--
-- 004's self-membership grant was `GRANT corwado_resolver TO current_user
-- WITH SET TRUE`. The INHERIT option was left unspecified, so it defaulted to
-- the grantee's rolinherit (TRUE for the owner). Effect: the owner role
-- INHERITED corwado_resolver and therefore its `resolver_read` permissive
-- policy AND the resolver functions' ownership/EXECUTE — so the owner could
-- read authorized_operator / land_steward with NO tenant context, bypassing
-- FORCE RLS on the two identity tables and contradicting
-- db/SECURITY_resolver.md ("the owner is subject to FORCE RLS"). Caught by the
-- Stage-4 prod smoke test running the no-context read as the owner; it was
-- missed locally because the Stage-3 suite only checked the app roles, never
-- asserted the OWNER reads 0 without context (that assertion has since been
-- added to the harness).
--
-- Fix: re-issue the membership WITH INHERIT FALSE. SET stays TRUE — SET is all
-- that `ALTER FUNCTION ... OWNER TO corwado_resolver` needs; INHERIT is the
-- part that leaked. Re-granting UPDATES the existing self-grant row in place
-- (inherit t -> f); it does NOT add a third row. The only other membership row
-- is the auto-grant created when the role was created (grantor = postgres),
-- which is already inherit=f. So after this migration NO membership path from
-- the owner to corwado_resolver carries INHERIT, and the effective state is
-- provably non-inheriting — verified by the owner's no-context reads on
-- land_steward and authorized_operator returning 0 rows.
--
-- 004's grant line has ALSO been corrected in place (SET TRUE, INHERIT FALSE)
-- so fresh applies never leak. This migration exists solely to correct
-- environments where the buggy 004 already ran (prod: 004 applied 2026-08-12).
-- Idempotent: safe to re-run; on an environment that never had the leak it is
-- a no-op re-affirmation of SET TRUE, INHERIT FALSE.
-- ============================================================
BEGIN;

DO $$
BEGIN
  EXECUTE format('GRANT corwado_resolver TO %I WITH SET TRUE, INHERIT FALSE', current_user);
END $$;

COMMIT;
