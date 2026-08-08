"""
Staff authentication. Issues a 'staff'-typed JWT. Reads identity tables
(staff_account/organization), which are not tenant-RLS'd, so login works
before any org context exists.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.security import verify_password, issue_token, parse_bearer, decode_jwt
from fastapi import Header

router = APIRouter()


class StaffLoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    organization_status: str


@router.post("/login", response_model=TokenOut)
def staff_login(payload: StaffLoginIn, db: Session = Depends(get_db)):
    staff = db.query(models.StaffAccount).filter_by(
        email=str(payload.email).lower(), is_active=True).first()
    if not staff or not verify_password(payload.password, staff.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    org = db.query(models.Organization).filter_by(id=staff.organization_id).first()
    # NOTE: we issue a token even for a pending org, so the account can reach
    # the "waiting for approval" status endpoint below — but get_current_staff
    # blocks every tenant route until the org is active.
    return TokenOut(access_token=issue_token(staff.id, "staff"),
                    organization_status=org.status if org else "unknown")


@router.get("/me")
def whoami(authorization: str = Header(None), db: Session = Depends(get_db)):
    """Lightweight status endpoint a pending-org staff can reach (does not
    require an active org, unlike get_current_staff)."""
    claims = decode_jwt(parse_bearer(authorization))
    if claims.get("typ") != "staff":
        raise HTTPException(status_code=401, detail="invalid credentials")
    staff = db.query(models.StaffAccount).filter_by(id=claims["sub"], is_active=True).first()
    if not staff:
        raise HTTPException(status_code=401, detail="invalid credentials")
    org = db.query(models.Organization).filter_by(id=staff.organization_id).first()
    return {"staff_account_id": staff.id, "role": staff.role,
            "organization_id": staff.organization_id,
            "organization_status": org.status if org else None}
