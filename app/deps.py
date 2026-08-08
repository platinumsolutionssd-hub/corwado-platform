"""
Auth dependencies — the two physically separate branches that decide the
tenant context. A staff account and a platform admin resolve through
different functions writing mutually exclusive keys into session.info.
"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, _apply_tenant_context
from app.security import parse_bearer, decode_jwt
from app import models


def _stamp_current_txn(db: Session):
    # Apply the GUC to the already-open transaction too (the after_begin
    # listener only covers transactions that begin AFTER this point).
    _apply_tenant_context(db, db.connection())


# ---------- Branch A: tenant staff. Sets ONLY app.current_org. ----------
def get_current_staff(authorization: str = Header(None), db: Session = Depends(get_db)):
    claims = decode_jwt(parse_bearer(authorization))
    if claims.get("typ") != "staff":                       # a landlord token cannot be used here
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


# ---------- Branch B: landlord. Sets ONLY app.platform_admin. ----------
# Separate function, used only by /api/admin/*. A staff account has no code
# path here: it requires a platform_admin token type AND a matching row.
def get_current_platform_admin(authorization: str = Header(None), db: Session = Depends(get_db)):
    claims = decode_jwt(parse_bearer(authorization))
    if claims.get("typ") != "platform_admin":
        raise HTTPException(status_code=403, detail="not a platform admin")
    admin = db.query(models.PlatformAdmin).filter_by(id=claims["sub"], is_active=True).first()
    if not admin:
        raise HTTPException(status_code=403, detail="not a platform admin")
    db.info["tenant"] = {"platform_admin": True}           # NEVER writes org_id
    _stamp_current_txn(db)
    return admin
