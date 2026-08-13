"""
Database connection setup — SQLAlchemy + PostGIS, with RLS tenant context.

The tenant scope is enforced by Postgres Row-Level Security, driven by a
per-transaction GUC that this module sets from session.info['tenant'].
Nothing here trusts individual queries to remember an org filter.
"""
import os

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://corwado_user:changeme@localhost:5432/corwado_platform",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _apply_tenant_context(session, connection):
    """
    The single place that decides which RLS context a transaction carries.
    Mutually exclusive outcomes:
      - platform_admin -> app.platform_admin='on' (+ app.platform_admin_id for the
                          landlord-audit trigger's who-field)      (landlord bypass)
      - consultant     -> app.current_org=<uuid> AND SET LOCAL ROLE corwado_consultant
                          (read-only, BoQ/PII-denied), scoped to that one org
      - org_id (staff) -> ONLY app.current_org=<uuid>              (tenant scope)
      - neither        -> sets NOTHING -> RLS denies every tenant row (fail-closed)
    The four are set by four different dependencies writing different keys; a staff
    context can never reach the platform_admin branch, etc.

    Every setting is TRANSACTION-LOCAL: `set_config(..., true)` and `SET LOCAL ROLE`
    both reset at transaction end. So a pooled connection can NEVER carry the
    consultant role (or any GUC) into the next request — the next request's
    after_begin re-derives the context from scratch, or sets nothing (deny-closed).
    """
    ctx = session.info.get("tenant")
    if not ctx:
        return  # deny-closed: an unauthenticated / stray session sees zero rows
    if ctx.get("platform_admin"):
        connection.execute(text("SELECT set_config('app.platform_admin', 'on', true)"))
        admin_id = ctx.get("platform_admin_id")
        if admin_id:
            connection.execute(
                text("SELECT set_config('app.platform_admin_id', :a, true)"),
                {"a": str(admin_id)},
            )
    elif ctx.get("org_id"):
        connection.execute(
            text("SELECT set_config('app.current_org', :o, true)"),
            {"o": str(ctx["org_id"])},
        )
        if ctx.get("consultant"):
            # SET LOCAL ROLE is transaction-scoped: it reverts to corwado_app at
            # txn end, so the read-only consultant role cannot outlive this request
            # on the pooled connection. RLS (app.current_org above) still confines
            # every read to the granted org; the role additionally strips write and
            # BoQ/PII access. Role name is a fixed literal (no injection surface).
            connection.execute(text("SET LOCAL ROLE corwado_consultant"))


@event.listens_for(SessionLocal, "after_begin")
def _reapply_on_each_txn(session, transaction, connection):
    # Re-applies at the start of EVERY transaction, so a mid-request db.commit()
    # (which ends the txn and drops LOCAL settings) cannot silently un-scope the
    # queries that run after it.
    _apply_tenant_context(session, connection)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
