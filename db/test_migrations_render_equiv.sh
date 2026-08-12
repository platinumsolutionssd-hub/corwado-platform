#!/usr/bin/env bash
# Render-equivalent migration test harness.
#
# Applies the resolver migrations as a NON-SUPERUSER owner role (mirroring
# Render's corwado_platform_user: CREATEROLE CREATEDB NOSUPERUSER NOBYPASSRLS)
# against a scratch DB it owns, and asserts the tenant boundary — INCLUDING the
# standing check whose absence let the 004 inherit-leak reach prod:
#   the OWNER role must read 0 rows without a tenant context on BOTH
#   land_steward and authorized_operator.
#
# Standing rule: local migration testing runs as this role, never as superuser.
# Usage: bash db/test_migrations_render_equiv.sh   (from repo root)
set -uo pipefail
PGBIN="/c/Users/USER/Desktop/corwado-platform/postgres/pg17/pgsql/bin"; P="$PGBIN/psql.exe"
SU="-h localhost -p 5433 -U postgres"; DB="corwado_harness"
RO="-h localhost -p 5433 -U render_owner -d $DB"; CA="-h localhost -p 5433 -U corwado_app -d $DB"
cd "$(dirname "$0")/.." || exit 2
FAIL=0
assert() { if [ "$2" = "$3" ]; then echo "  PASS: $1 ($3)"; else echo "  FAIL: $1 — expected [$2] got [$3]"; FAIL=1; fi; }
q()  { $P $RO -tAc "$1" 2>/dev/null; }
qa() { $P $CA -tAc "$1" 2>/dev/null; }
ctx() { echo "SELECT set_config('app.current_org',(SELECT id::text FROM organization WHERE short_code='$1'),false)>'';"; }

echo "== clean slate =="
# These roles are cluster-global and may own objects / hold grants in any of
# the throwaway test DBs. Terminate connections and drop every such DB before
# the roles, so DROP ROLE has no remaining dependencies.
for d in "$DB" corwado_rev corwado_test; do
  $P $SU -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$d' AND pid<>pg_backend_pid();" >/dev/null 2>&1
  $P $SU -d postgres -c "DROP DATABASE IF EXISTS $d;" 2>&1 | grep -iE "error|cannot" || true
done
$P $SU -d postgres -c "DROP ROLE IF EXISTS corwado_resolver; DROP ROLE IF EXISTS corwado_app; DROP ROLE IF EXISTS render_owner;" 2>&1 | grep -iE "error|cannot" || true
$P $SU -d postgres -c "CREATE ROLE render_owner LOGIN CREATEROLE CREATEDB NOSUPERUSER NOBYPASSRLS; CREATE ROLE corwado_app LOGIN NOSUPERUSER NOBYPASSRLS;" 2>&1 | grep -iE "error" || true
$P $SU -d postgres -c "CREATE DATABASE $DB OWNER render_owner;" 2>&1 | grep -iE "error" || true
$P $SU -d $DB -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"; ALTER SCHEMA public OWNER TO render_owner;" 2>&1 | grep -iE "error" || true

echo "== apply migrations AS render_owner (fixed 004 + 003 + 005) =="
for f in db/schema.sql db/migrations/001_multitenancy.sql db/migrations/004_telegram_resolver_rev.sql \
         db/migrations/003_operator_phone_per_org.sql db/migrations/005_resolver_membership_no_inherit.sql; do
  if out=$($P $RO -v ON_ERROR_STOP=1 -f "$f" 2>&1); then echo "  applied $f"; else echo "  FAIL applying $f:"; echo "$out" | grep -iE "error|fatal" | head -2; FAIL=1; fi
done

echo "== seed: corwado_app grants + two orgs + operator/stewards =="
$P $RO -v ON_ERROR_STOP=1 2>&1 <<'SQL' | grep -iE "error|fatal" && FAIL=1 || true
GRANT USAGE ON SCHEMA public TO corwado_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO corwado_app;
INSERT INTO organization (name,short_code,country,status) VALUES ('Org B','orgb','Kenya','active');
SELECT set_config('app.current_org',(SELECT id::text FROM organization WHERE short_code='corwado'),false);
INSERT INTO authorized_operator (organization_id,full_name,phone_number,telegram_chat_id,added_by,is_active)
  VALUES ((SELECT id FROM organization WHERE short_code='corwado'),'Op A','+211900000001','CHAT_A','test',true);
INSERT INTO land_steward (organization_id,role,full_name)
  VALUES ((SELECT id FROM organization WHERE short_code='corwado'),'smallholder_farmer','Steward A');
SELECT set_config('app.current_org',(SELECT id::text FROM organization WHERE short_code='orgb'),false);
INSERT INTO land_steward (organization_id,role,full_name)
  VALUES ((SELECT id FROM organization WHERE short_code='orgb'),'smallholder_farmer','Steward B');
SQL

echo "== fresh-apply assertions (fixed 004 must NOT leak) =="
# THE STANDING CHECK — owner must be RLS-subject with no context:
assert "OWNER no-context land_steward = 0"        "0" "$(q 'SELECT count(*) FROM land_steward;')"
assert "OWNER no-context authorized_operator = 0" "0" "$(q 'SELECT count(*) FROM authorized_operator;')"
# corwado_app boundary:
assert "corwado_app no-context land_steward = 0"  "0" "$(qa 'SELECT count(*) FROM land_steward;')"
assert "corwado_app orgA sees only Steward A" "Steward A" "$($P $CA -tAc "$(ctx corwado) SELECT string_agg(full_name,',') FROM land_steward;" 2>/dev/null | tail -1)"
assert "corwado_app orgB sees only Steward B" "Steward B" "$($P $CA -tAc "$(ctx orgb) SELECT string_agg(full_name,',') FROM land_steward;" 2>/dev/null | tail -1)"
assert "resolve_chat_org(CHAT_A) = corwado/active" "corwado/active" "$(qa "SELECT o.short_code||'/'||r.org_status FROM resolve_chat_org('CHAT_A') r JOIN organization o ON o.id=r.organization_id;")"
assert "corwado_app SET ROLE corwado_resolver denied" "1" "$($P $CA -c 'SET ROLE corwado_resolver;' 2>&1 | grep -c 'permission denied')"

echo "== corrective proof: reintroduce the leak, then 005 closes it =="
echo -n "  reintroduce-leak grant: "; $P $RO -c "GRANT corwado_resolver TO render_owner WITH SET TRUE, INHERIT TRUE;" 2>&1 | tr -d '\n'; echo ""
echo -n "  membership inh after re-grant: "; q "SELECT inherit_option FROM pg_auth_members m JOIN pg_roles g ON g.oid=m.roleid JOIN pg_roles u ON u.oid=m.member WHERE g.rolname='corwado_resolver' AND u.rolname='render_owner' AND m.grantor=(SELECT oid FROM pg_roles WHERE rolname='render_owner');"
assert "leak reproduced: OWNER no-context land_steward > 0" "2" "$(q 'SELECT count(*) FROM land_steward;')"
echo -n "  apply 005: "; $P $RO -v ON_ERROR_STOP=1 -f db/migrations/005_resolver_membership_no_inherit.sql 2>&1 | tail -1
echo -n "  membership inh after 005 (self-grant row): "; q "SELECT inherit_option FROM pg_auth_members m JOIN pg_roles g ON g.oid=m.roleid JOIN pg_roles u ON u.oid=m.member WHERE g.rolname='corwado_resolver' AND u.rolname='render_owner' AND m.grantor=(SELECT oid FROM pg_roles WHERE rolname='render_owner');"
assert "005 closes leak: OWNER no-context land_steward = 0"        "0" "$(q 'SELECT count(*) FROM land_steward;')"
assert "005 closes leak: OWNER no-context authorized_operator = 0" "0" "$(q 'SELECT count(*) FROM authorized_operator;')"

echo ""
[ "$FAIL" = "0" ] && echo "ALL ASSERTIONS PASS" || echo ">>> SOME ASSERTIONS FAILED"
exit $FAIL
