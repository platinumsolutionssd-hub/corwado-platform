"""
Auth dependencies — physically separate branches that decide the tenant context.
Staff, landlord (platform admin), and consultant resolve through different
functions writing mutually exclusive keys into session.info.
"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, _apply_tenant_context
from app.security import parse_bearer, decode_jwt
from app import models


def _stamp_current_txn(db: Session):
    # Apply the GUC (and, for a consultant, SET LOCAL ROLE) to the already-open
    # transaction too (the after_begin listener only covers transactions that
    # begin AFTER this point).
    _apply_tenant_context(db, db.connection())


# ---------- Branch A: tenant staff. Sets ONLY app.current_org. ----------
def get_current_staff(authorization: str = Header(None), db: Session = Depends(get_db)):
    claims = decode_jwt(parse_bearer(authorization))
    if claims.get("typ") != "staff":                       # a landlord/consultant token cannot be used here
        raise HTTPException(status_code=401, detail="invalid credentials")
    staff = db.query(models.StaffAccount).filter_by(       # identity table: no tenant RLS on it
        id=claims["sub"], is_active=True).first()
    if not staff:
        raise HTTPException(status_code=401, detail="invalid credentials")
    org = db.query(models.Organization).filter_by(id=staff.organization_id).first()
    if not org or org.status != "active":                  # pending/suspended -> blocked from tenant routes
        raise HTTPException(
            status_code=403,
            detail="org_pending" if org and org.status == "pending" else "org_inactive",
        )
    db.info["tenant"] = {"org_id": staff.organization_id}  # NEVER writes platform_admin
    _stamp_current_txn(db)
    return staff


# ---------- Org-admin gate: an org-admin (role='admin') staff. ----------
# Wraps get_current_staff (so tenant context is already set) and additionally
# requires role='admin'. Used for consultant-grant approval + operator management.
def require_org_admin(staff: models.StaffAccount = Depends(get_current_staff)):
    if staff.role != "admin":
        raise HTTPException(status_code=403, detail="org_admin_required")
    return staff


# ---------- Branch B: landlord. Sets app.platform_admin (+ id for the audit). ----------
def get_current_platform_admin(authorization: str = Header(None), db: Session = Depends(get_db)):
    claims = decode_jwt(parse_bearer(authorization))
    if claims.get("typ") != "platform_admin":
        raise HTTPException(status_code=403, detail="not a platform admin")
    admin = db.query(models.PlatformAdmin).filter_by(id=claims["sub"], is_active=True).first()
    if not admin:
        raise HTTPException(status_code=403, detail="not a platform admin")
    # platform_admin_id flows into app.platform_admin_id so the landlord-audit
    # trigger records WHO performed each landlord-context write.
    db.info["tenant"] = {"platform_admin": True, "platform_admin_id": str(admin.id)}  # NEVER writes org_id
    _stamp_current_txn(db)
    return admin


# ---------- Branch C: consultant. Per-request org + revocable grant. ----------
def get_current_consultant(
    organization_id: str = Header(None, alias="X-Org-Id"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Cross-org by per-org grant, NOT a landlord bypass. The org is chosen per
    request (X-Org-Id header) and an ACTIVE grant is verified on EVERY request, so
    a revoked grant stops access on the next request — no org is baked into the
    token, no grant check is cached.

    FAIL-CLOSED ORDERING (all-or-nothing): verify token -> load consultant ->
    require an org -> load grant -> require status='active' -> require org active
    -> ONLY THEN set app.current_org + SET LOCAL ROLE corwado_consultant. If the
    grant lookup itself errors, the request fails closed and never proceeds with a
    stale or assumed grant.
    """
    claims = decode_jwt(parse_bearer(authorization))
    if claims.get("typ") != "consultant":                  # a staff/landlord token cannot be used here
        raise HTTPException(status_code=401, detail="invalid credentials")
    consultant = db.query(models.ConsultantAccount).filter_by(
        id=claims["sub"], is_active=True).first()
    if not consultant:
        raise HTTPException(status_code=401, detail="invalid credentials")
    if not organization_id:
        raise HTTPException(status_code=400, detail="missing X-Org-Id")

    # Grant lookup wrapped so a DB error fails CLOSED, never open.
    try:
        grant = db.query(models.ConsultantGrant).filter_by(
            consultant_id=consultant.id, organization_id=organization_id).first()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=503, detail="grant_check_unavailable")
    if not grant or grant.status != "active":
        raise HTTPException(status_code=403, detail="no_active_grant")

    org = db.query(models.Organization).filter_by(id=organization_id).first()
    if not org or org.status != "active":
        raise HTTPException(status_code=403, detail="org_inactive")

    # All checks passed -> set the tenant context. The 'consultant' marker makes
    # _apply_tenant_context also SET LOCAL ROLE corwado_consultant (read-only,
    # BoQ/PII-denied), scoped to THIS org only.
    db.info["tenant"] = {"org_id": organization_id, "consultant": True}
    _stamp_current_txn(db)
    return consultant
