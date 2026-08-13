#!/usr/bin/env bash
# EVIDENCE-ONLY diagnostic for the 006 landlord-audit trigger. Changes nothing.
# Run AFTER a harness run (corwado_harness persists; it's dropped at the START of
# the harness, so it still has 006 applied). Bisects the three candidate causes:
#   1. trigger missing        -> step 1 shows no trg_landlord_audit
#   2. INSERT fails RLS        -> step 4 prints "violates row-level security policy"
#   3. trigger fires, no log   -> step 4 INSERT succeeds but audit_diag = 0
set -uo pipefail
# Force UTF-8 client encoding: this PG build lacks the utf8_and_win conversion lib,
# so a WIN1252 client (PowerShell default) fails at connect. DB is UTF-8; match it.
export PGCLIENTENCODING=UTF8
PGBIN="/c/Users/USER/Desktop/corwado-platform/postgres/pg17/pgsql/bin"; P="$PGBIN/psql.exe"
CA="-h localhost -p 5433 -U corwado_app -d corwado_harness"
SU="-h localhost -p 5433 -U postgres -d corwado_harness"

echo "=== 1. is trg_landlord_audit present on cooperative? ==="
$P $CA -c "SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid='cooperative'::regclass AND NOT tgisinternal;"

echo "=== 2. log_landlord_write: security-definer + owner? ==="
$P $CA -c "SELECT proname, prosecdef AS sec_definer, (SELECT rolname FROM pg_roles WHERE oid=proowner) AS owner FROM pg_proc WHERE proname='log_landlord_write';"

echo "=== 3. can corwado_app set + read app.platform_admin at all? (expect on) ==="
$P $CA -tAc "SELECT set_config('app.platform_admin','on',false); SELECT current_setting('app.platform_admin', true);"

echo "=== 4. landlord INSERT with app.platform_admin='on', ERRORS VISIBLE ==="
echo "    (if this prints an RLS violation, the GUC isn't reaching the WITH CHECK;"
echo "     if it prints INSERT 0 1, RLS passed and the question is the trigger body)"
$P $CA -v ON_ERROR_STOP=0 -c "SELECT set_config('app.platform_admin','on',false); SELECT set_config('app.platform_admin_id','11111111-1111-1111-1111-111111111111',false); INSERT INTO cooperative (organization_id,name,type) VALUES ((SELECT id FROM organization WHERE short_code='corwado'),'DiagCoop','cooperative');"

echo "=== 5. did the coop row land, and did the trigger log? ==="
$P $CA -c "SELECT set_config('app.platform_admin','on',false); SELECT (SELECT count(*) FROM cooperative WHERE name='DiagCoop') AS coop_diag, (SELECT count(*) FROM landlord_audit_log WHERE row_data->>'name'='DiagCoop') AS audit_diag;"

echo "=== 6. total audit rows (as superuser, no RLS ambiguity) ==="
$P $SU -c "SELECT count(*) AS total_audit FROM landlord_audit_log;"

echo "=== 7. owner of landlord_audit_log + can render_owner read it? (harness reads via render_owner) ==="
$P $SU -c "SELECT tableowner FROM pg_tables WHERE tablename='landlord_audit_log';"
echo "--- render_owner SELECT (errors visible; if permission denied, the HARNESS assertion role is the bug) ---"
$P -h localhost -p 5433 -U render_owner -d corwado_harness -c "SELECT count(*) FROM landlord_audit_log;" 2>&1

echo "=== 8. LOCAL-GUC insert exactly like the APP + harness (BEGIN; set_config true; COMMIT) ==="
echo "    (the app uses is_local=true; if this does NOT log, it's a REAL prod bug, not just the harness)"
$P $CA -c "BEGIN; SELECT set_config('app.platform_admin','on',true); SELECT set_config('app.platform_admin_id','22222222-2222-2222-2222-222222222222',true); INSERT INTO cooperative (organization_id,name,type) VALUES ((SELECT id FROM organization WHERE short_code='corwado'),'LocalCoop','cooperative'); COMMIT;"
echo "--- did LocalCoop log? (superuser read) ---"
$P $SU -c "SELECT count(*) AS localcoop_audit FROM landlord_audit_log WHERE row_data->>'name'='LocalCoop';"
