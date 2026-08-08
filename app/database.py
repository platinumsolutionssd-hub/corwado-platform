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
    The single place that decides which RLS GUC a transaction carries.
    Three mutually exclusive outcomes:
      - platform_admin -> sets ONLY app.platform_admin='on'  (landlord bypass)
      - org_id         -> sets ONLY app.current_org=<uuid>   (tenant scope)
      - neither        -> sets NOTHING -> RLS denies every tenant row (fail-closed)
    A staff context can never reach the platform_admin branch: the two are set
    by two different dependencies (deps.py) writing different keys.
    Settings are LOCAL (txn-scoped), so nothing leaks onto the pooled connection.
    """
    ctx = session.info.get("tenant")
    if not ctx:
        return  # deny-closed: an unauthenticated / stray session sees zero rows
    if ctx.get("platform_admin"):
        connection.execute(text("SELECT set_config('app.platform_admin', 'on', true)"))
    elif ctx.get("org_id"):
        connection.execute(
            text("SELECT set_config('app.current_org', :o, true)"),
            {"o": str(ctx["org_id"])},
        )


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
