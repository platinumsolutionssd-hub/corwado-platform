# Prod-apply runbook — migration 006 (consultant + landlord audit)

> **STATUS: PREPARED, NOT EXECUTED. Do not run tonight.** Third prod-facing change
> of a long session — run next session with fresh eyes (same reasoning that caught
> the 004 inherit-leak). Nothing here executes until John says go.

**Credential discipline (unchanged):** every prod step runs from John's machine as
the DB **owner**, John's hands on the credential. Claude supplies exact commands;
Claude never holds or runs prod credentials.

**Env vars:** NONE new. 006 is pure SQL; the app-layer uses only the existing
`JWT_SECRET` + `DATABASE_URL`. No Render dashboard env change needed.

**Risk shape:** 006 is **additive + non-breaking** — it only creates objects and
flips `staff_account.role` DEFAULT (which no running code relies on; the founding
path sets `role` explicitly). Unlike 001, there is no context-less-old-code hazard,
so **apply-then-deploy, no maintenance window**. Rollout order is not load-bearing,
but we still apply 006 first, verify, then deploy.

Conventions below:
- `PSQL` = full path to John's psql, e.g. `C:\Users\USER\Desktop\corwado-platform\postgres\pg17\pgsql\bin\psql.exe`
- `$OWNER` = the **external** prod connection string as the DB owner
  (`corwadodb_pb0f_user`), the same one used for the 001/004/005 cutovers. John
  supplies it; it is never written into this file.
- Run each block, paste output back, wait for confirmation before the next step.

---

## Step 0 — Pre-flight: verified backup still exists + hash-matches

Standing precondition for every prod session. Confirm the most recent verified
`pg_dump` backup is present and its hash matches the recorded value (the backup that
was restore-verified into a throwaway cluster). Do NOT proceed if the hash differs
or the file is missing — take and verify a fresh backup first, same as the 001/004
cutovers.

```
# (John's backup location + hash-check command, as established in prior cutovers)
# Expected: hash matches the recorded value; restore-verified.
```

## Step 1 — 9-table row-count baseline BEFORE

Counts run with the landlord bypass GUC set, so RLS doesn't hide rows from the owner
(the owner is RLS-subject under FORCE). Read-only; sets nothing durable.

```
& "$PSQL" "$OWNER" -v ON_ERROR_STOP=1 -c "SELECT set_config('app.platform_admin','on',true);
SELECT 'organization' t, count(*) n FROM organization
UNION ALL SELECT 'staff_account', count(*) FROM staff_account
UNION ALL SELECT 'cooperative', count(*) FROM cooperative
UNION ALL SELECT 'land_steward', count(*) FROM land_steward
UNION ALL SELECT 'parcel', count(*) FROM parcel
UNION ALL SELECT 'season_planting', count(*) FROM season_planting
UNION ALL SELECT 'input_requirement', count(*) FROM input_requirement
UNION ALL SELECT 'input_financing_record', count(*) FROM input_financing_record
UNION ALL SELECT 'authorized_operator', count(*) FROM authorized_operator
ORDER BY t;"
```

Record these 9 numbers. (Align the table set with the established cutover baseline if
it differs.)

## Step 2 — Apply 006 as owner

```
& "$PSQL" "$OWNER" -v ON_ERROR_STOP=1 -f db/migrations/006_consultant_and_audit.sql
```

Expected: ends `COMMIT`, no error. 006 is idempotent (IF NOT EXISTS / DROP-then-
create) and contains no superuser-only object, so it applies as the non-superuser
owner (same class proven by the Render-equivalent harness).

## Step 3 — Confirm objects (mirror the harness contract)

**3a. Consultant tables + audit table exist:**
```
& "$PSQL" "$OWNER" -c "SELECT tablename FROM pg_tables WHERE tablename IN ('consultant_account','consultant_grant','landlord_audit_log') ORDER BY tablename;"
```
Expect all three.

**3b. corwado_consultant role — granted the ALLOWED tables, DENIED BoQ/PII.** This is
the structural contract; it must match the harness exactly.
```
& "$PSQL" "$OWNER" -c "SELECT table_name, privilege_type FROM information_schema.role_table_grants WHERE grantee='corwado_consultant' ORDER BY table_name;"
```
Expect SELECT (only) on: parcel, parcel_diagnostic, parcel_crop_baseline,
season_planting, advisory_snapshot, cooperative, buyer, buyer_posting, agro_dealer,
radio_station, radio_broadcast_slot, price_board_entry, crop_dictionary_entry.
**Expect NO row** for input_requirement, input_financing_record, land_steward,
authorized_operator, staff_account, inbound_message (BoQ/PII — structural deny), and
**no INSERT/UPDATE/DELETE anywhere** (read-only).

**3c. Landlord-audit trigger present on the 19 tenant tables:**
```
& "$PSQL" "$OWNER" -c "SELECT count(*) AS audit_triggers FROM pg_trigger WHERE tgname='trg_landlord_audit' AND NOT tgisinternal;"
```
Expect 19.

**3d. Role default flipped:**
```
& "$PSQL" "$OWNER" -c "SELECT column_default FROM information_schema.columns WHERE table_name='staff_account' AND column_name='role';"
```
Expect `'staff'::text`.

## Step 4 — 9-table baseline AFTER (must be identical to Step 1)

Re-run the Step 1 block verbatim. **Every count must equal Step 1.** 006 creates
objects and touches no rows (same as 004/005). Any difference = stop and investigate.

## Step 5 — Prod smoke test (READ-ONLY, against REAL prod data)

Mirrors the harness assertions but on live rows. **No writes** — the audit-trigger
firing was already proven on the harness; firing it here would write a test row to
prod. We confirm the trigger *exists* (Step 3c), not fire it.

Let `CORG` = the real CORWADO org id:
```
& "$PSQL" "$OWNER" -c "SELECT id FROM organization WHERE short_code='corwado';"
```

**5a. corwado_app can assume the consultant role:** (run as corwado_app, not owner —
use the corwado_app connection string `$APP`)
```
& "$PSQL" "$APP" -c "SET ROLE corwado_consultant;"    # expect no error
```

**5b. Consultant is org-scoped + read-only + BoQ/PII denied, on real data:**
```
& "$PSQL" "$APP" -v ON_ERROR_STOP=0 -c "SET ROLE corwado_consultant; SELECT set_config('app.current_org','<CORG>',false);
SELECT count(*) AS coops_visible FROM cooperative;               -- expect: CORWADO's real coop count
SELECT count(*) FROM input_financing_record;                     -- expect: ERROR permission denied for ...
SELECT count(*) FROM land_steward;                               -- expect: ERROR permission denied for ...
INSERT INTO cooperative (organization_id,name,type) VALUES ('<CORG>','x','cooperative');  -- expect: ERROR permission denied (read-only)"
```
Expect: `coops_visible` = CORWADO's real count; the three denials fire as
`permission denied for ...`. **Org-scoping caveat:** prod currently has ONE tenant
(CORWADO), so "sees only org X" is trivially satisfied — the *denial + read-only +
role* mechanics are the meaningful prod proof here; cross-tenant scoping is fully
proven on the harness (two orgs) and re-provable on prod once a second org exists.

## Step 6 — App-layer deploy

No new env vars. Sequence (mirrors the frontend/validator deploys):
1. Merge `feature/phase1-consultant` → `master` (`--no-ff`, preserve the two commits),
   push `origin master`.
2. Render: if Auto-Deploy is OFF (its state after the last cutover — confirm on the
   dashboard), trigger **Manual Deploy** of the new master; if ON, the push fires it.
3. Watch the build log to completion (installs unchanged — no new deps; `pyproj`/
   `shapely`/`ee` are not touched by this change).
4. Endpoint checks after build:
   - existing tenant routes still 200 with a staff token (no regression);
   - operator add/revoke now require an org-admin token (a non-admin staff token →
     403 `org_admin_required`); GET list still works for any staff.
   (The consultant *endpoints* don't exist yet — that's the next stage — so there's
   nothing consultant-facing to hit here; the plumbing is dormant until the router
   lands.)

## Step 7 — Post-deploy

The **consultant-facing router** (consultant login + grant request/approve/revoke +
consultant read routes) is the next gated stage, after 006 + this app-layer are live
and confirmed. Do not start it until this lands.

## Rollback

006 is additive; if a smoke check fails, the app-layer code can be left undeployed
and 006's objects dropped (consultant_account/consultant_grant/landlord_audit_log,
the corwado_consultant role, the trigger + function, and reset the role DEFAULT) — no
tenant data is touched at any point, and the verified backup from Step 0 remains the
ultimate fallback. Prefer diagnosing forward over rollback unless data integrity is
in question (it isn't — 006 writes no rows).
