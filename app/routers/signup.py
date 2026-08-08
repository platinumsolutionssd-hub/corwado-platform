"""
Public organization self-onboarding. Creates a PENDING organization + its
first org-scoped admin. No landlord can be created here (see organizations.py).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, constr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.organizations import (
    create_organization_with_admin, SELF_SIGNUP_INITIAL_STATUS,
)

router = APIRouter()


class OrganizationSignupIn(BaseModel):
    # There is deliberately NO 'role', 'status', 'is_landlord', or
    # 'platform_admin' field. The client cannot submit privilege or activation
    # state. role is hardcoded in the service; status comes from
    # SELF_SIGNUP_INITIAL_STATUS. An unexpected extra key is ignored.
    org_name: constr(strip_whitespace=True, min_length=2, max_length=200)
    short_code: constr(strip_whitespace=True, min_length=2, max_length=40)
    country: Optional[str] = None
    admin_full_name: constr(strip_whitespace=True, min_length=1, max_length=200)
    admin_email: EmailStr
    admin_password: constr(min_length=10, max_length=200)


class OrganizationSignupOut(BaseModel):
    organization_id: str
    status: str
    staff_account_id: str
    message: str


@router.post("/signup", response_model=OrganizationSignupOut, status_code=201)
def self_onboard_organization(payload: OrganizationSignupIn, db: Session = Depends(get_db)):
    try:
        org, staff = create_organization_with_admin(
            db,
            org_name=payload.org_name,
            short_code=payload.short_code.lower(),
            country=payload.country,
            admin_full_name=payload.admin_full_name,
            admin_email=str(payload.admin_email).lower(),
            admin_password=payload.admin_password,
            status=SELF_SIGNUP_INITIAL_STATUS,   # 'pending' — NOT from the request
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An organization with that short code, or that admin email, already exists.",
        )
    return OrganizationSignupOut(
        organization_id=org.id,
        status=org.status,
        staff_account_id=staff.id,
        message=("Organization submitted for approval. You can sign in to check status, "
                 "but data entry unlocks once an administrator approves your organization."),
    )
