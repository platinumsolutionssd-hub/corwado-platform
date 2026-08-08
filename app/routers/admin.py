"""
Landlord (platform_admin) surface — cross-org. Every route here uses
get_current_platform_admin, which sets app.platform_admin='on' (the RLS
bypass). Deliberately a separate router from the tenant routes, so the
staff/landlord separation stays physical, not a flag on a shared route.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.deps import get_current_platform_admin
from app.security import verify_password, issue_token

router = APIRouter()


class AdminLoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenOut)
def admin_login(payload: AdminLoginIn, db: Session = Depends(get_db)):
    admin = db.query(models.PlatformAdmin).filter_by(
        email=str(payload.email).lower(), is_active=True).first()
    if not admin or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    return TokenOut(access_token=issue_token(admin.id, "platform_admin"))


@router.get("/organizations")
def list_organizations(admin=Depends(get_current_platform_admin), db: Session = Depends(get_db)):
    rows = db.query(models.Organization).all()
    return [{"id": o.id, "name": o.name, "short_code": o.short_code, "status": o.status}
            for o in rows]


@router.post("/organizations/{org_id}/approve")
def approve_organization(org_id: str, admin=Depends(get_current_platform_admin),
                         db: Session = Depends(get_db)):
    org = db.query(models.Organization).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="organization not found")
    org.status = "active"
    db.commit()
    return {"id": org.id, "status": org.status}


@router.get("/stewards")
def all_stewards(admin=Depends(get_current_platform_admin), db: Session = Depends(get_db)):
    """Cross-org read: under the platform_admin GUC, RLS returns every org's
    stewards. This is the concrete proof of landlord bypass."""
    rows = db.query(models.LandSteward).all()
    return [{"id": s.id, "full_name": s.full_name, "organization_id": s.organization_id}
            for s in rows]
