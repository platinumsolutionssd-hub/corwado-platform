"""
Unit tests for the Phase-1 consultant/landlord auth plumbing — dep, token, and
context logic, exercised with fakes (no DB, no network). The DB-side enforcement
(consultant role read-only, BoQ/PII denied, org-scope, audit trigger) is proven
separately by db/test_migrations_render_equiv.sh.

Run (cwd = repo root, JWT_SECRET is set by this file before importing app):
    python app/test_consultant_auth.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-prod")

from fastapi import HTTPException

from app import models
from app.security import issue_token, decode_jwt
from app.database import _apply_tenant_context
from app.deps import get_current_consultant, require_org_admin

FAIL = 0


def check(label, cond, detail=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAIL = 1


def expect_http(label, status, fn):
    try:
        fn()
        check(label, False, "no HTTPException raised")
    except HTTPException as e:
        check(label, e.status_code == status, f"got {e.status_code}, want {status}")


# ---- fakes -------------------------------------------------------------
class FakeQuery:
    def __init__(self, result, raises=False):
        self._result, self._raises = result, raises

    def filter_by(self, **kw):
        return self

    def first(self):
        if self._raises:
            raise RuntimeError("simulated DB hiccup")
        return self._result


class FakeConn:
    def __init__(self):
        self.executed = []

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params or {}))


class FakeDB:
    """results: {Model: obj | 'RAISE'}"""
    def __init__(self, results):
        self.results, self.info, self._conn, self.rolled_back = results, {}, FakeConn(), False

    def query(self, model):
        r = self.results.get(model, None)
        return FakeQuery(None, raises=True) if r == "RAISE" else FakeQuery(r)

    def connection(self):
        return self._conn

    def rollback(self):
        self.rolled_back = True


def con_obj():
    return types.SimpleNamespace(id="con-1", is_active=True)


def grant(status):
    return types.SimpleNamespace(status=status)


def org(status="active"):
    return types.SimpleNamespace(status=status)


TOKEN = f"Bearer {issue_token('con-1', 'consultant')}"

print("=" * 72)
print("Part 1 — token shape: consultant token carries identity, NO org")
claims = decode_jwt(issue_token("con-1", "consultant"))
check("typ == consultant", claims.get("typ") == "consultant")
check("sub == consultant id", claims.get("sub") == "con-1")
check("NO org baked into token", "org" not in claims and "organization_id" not in claims)

print("Part 2 — require_org_admin gate")
expect_http("role='staff' -> 403", 403,
            lambda: require_org_admin(types.SimpleNamespace(role="staff")))
check("role='admin' -> passes",
      require_org_admin(types.SimpleNamespace(role="admin")).role == "admin")

print("Part 3 — get_current_consultant fail-closed ordering")
# wrong token type
expect_http("staff token -> 401", 401,
            lambda: get_current_consultant("org1", f"Bearer {issue_token('s','staff')}", FakeDB({})))
# consultant not found
expect_http("unknown consultant -> 401", 401,
            lambda: get_current_consultant("org1", TOKEN, FakeDB({models.ConsultantAccount: None})))
# missing org header (consultant valid) -> 400, and NO context set
db = FakeDB({models.ConsultantAccount: con_obj()})
expect_http("missing X-Org-Id -> 400", 400, lambda: get_current_consultant(None, TOKEN, db))
check("  ...no tenant context set on 400", "tenant" not in db.info)
# grant lookup ERRORS -> fail closed (503), never proceed
db = FakeDB({models.ConsultantAccount: con_obj(), models.ConsultantGrant: "RAISE"})
expect_http("grant lookup error -> fail closed 503", 503,
            lambda: get_current_consultant("org1", TOKEN, db))
check("  ...rolled back on grant error", db.rolled_back is True)
check("  ...no tenant context set on error", "tenant" not in db.info)
# no grant / revoked grant -> 403
expect_http("no grant -> 403", 403, lambda: get_current_consultant(
    "org1", TOKEN, FakeDB({models.ConsultantAccount: con_obj(), models.ConsultantGrant: None})))
expect_http("revoked grant -> 403", 403, lambda: get_current_consultant(
    "org1", TOKEN, FakeDB({models.ConsultantAccount: con_obj(), models.ConsultantGrant: grant("revoked")})))
# active grant but org inactive -> 403
expect_http("active grant, org suspended -> 403", 403, lambda: get_current_consultant(
    "org1", TOKEN, FakeDB({models.ConsultantAccount: con_obj(),
                           models.ConsultantGrant: grant("active"), models.Organization: org("suspended")})))

print("Part 4 — happy path sets consultant context (org + SET LOCAL ROLE)")
db = FakeDB({models.ConsultantAccount: con_obj(), models.ConsultantGrant: grant("active"),
             models.Organization: org("active")})
result = get_current_consultant("org1", TOKEN, db)
check("returns the consultant", getattr(result, "id", None) == "con-1")
check("tenant ctx = {org_id, consultant}",
      db.info.get("tenant") == {"org_id": "org1", "consultant": True})
sql = " | ".join(s for s, _ in db._conn.executed)
check("context set app.current_org", "app.current_org" in sql)
check("context did SET LOCAL ROLE corwado_consultant", "SET LOCAL ROLE corwado_consultant" in sql)

print("Part 5 — _apply_tenant_context branches")
# consultant: current_org + role switch
c = FakeConn(); _apply_tenant_context(types.SimpleNamespace(info={"tenant": {"org_id": "o1", "consultant": True}}), c)
s = " | ".join(x for x, _ in c.executed)
check("consultant branch: current_org + SET LOCAL ROLE",
      "app.current_org" in s and "SET LOCAL ROLE corwado_consultant" in s)
# plain staff: current_org, NO role switch
c = FakeConn(); _apply_tenant_context(types.SimpleNamespace(info={"tenant": {"org_id": "o1"}}), c)
s = " | ".join(x for x, _ in c.executed)
check("staff branch: current_org, NO role switch",
      "app.current_org" in s and "SET LOCAL ROLE" not in s)
# landlord: platform_admin + platform_admin_id (who-flow for the audit trigger)
c = FakeConn(); _apply_tenant_context(
    types.SimpleNamespace(info={"tenant": {"platform_admin": True, "platform_admin_id": "adm-1"}}), c)
s = " | ".join(x for x, _ in c.executed)
check("landlord branch: platform_admin + platform_admin_id",
      "app.platform_admin'" in s and "app.platform_admin_id" in s)
# no context: sets nothing (deny-closed)
c = FakeConn(); _apply_tenant_context(types.SimpleNamespace(info={}), c)
check("no context -> nothing executed (deny-closed)", c.executed == [])

print("=" * 72)
print("ALL CONSULTANT-AUTH UNIT TESTS PASS" if not FAIL else ">>> SOME TESTS FAILED")
raise SystemExit(FAIL)
