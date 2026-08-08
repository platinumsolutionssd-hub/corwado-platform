-- ============================================================
-- 003_operator_phone_per_org — make authorized_operator.phone_number
-- unique PER ORGANIZATION, not globally.
--
-- Under multi-tenancy, two different organizations can legitimately have
-- an operator with the same phone number (a Digital Champion who works
-- for two co-ops; a shared field phone). The original global UNIQUE
-- (authorized_operator_phone_number_key) made the second org's insert
-- raise an IntegrityError -> unhandled 500, even though the app-level
-- duplicate check is already RLS-scoped and never saw the other org's row.
--
-- telegram_chat_id stays GLOBAL-unique on purpose: a Telegram chat maps to
-- exactly one real person, and resolve_chat_org() relies on that single-
-- match property. Only phone_number becomes org-scoped.
-- ============================================================
BEGIN;

ALTER TABLE authorized_operator
    DROP CONSTRAINT authorized_operator_phone_number_key;

ALTER TABLE authorized_operator
    ADD CONSTRAINT authorized_operator_org_phone_key
        UNIQUE (organization_id, phone_number);

COMMIT;
