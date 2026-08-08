"""
The single organization-creation path shared by self-signup and
landlord-created onboarding, so both produce a structurally identical
result: one organization + one org-scoped admin staff account.
"""
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app import models
from app.security import hash_password

# Product policy, NOT schema. Flip to "active" to make self-signup immediate;
# changing this constant needs NO migration (the DB column default is
# 'pending', and both callers pass status explicitly).
SELF_SIGNUP_INITIAL_STATUS = "pending"


def create_organization_with_admin(
    db: Session, *, org_name: str, short_code: str, admin_full_name: str,
    admin_email: str, admin_password: str, country: Optional[str] = None,
    status: str = "pending",
) -> Tuple[models.Organization, models.StaffAccount]:
    """
    role is HARDCODED to 'admin' below. This function has no parameter and no
    branch that can produce a platform_admin row — landlord accounts are
    created only by the separate bootstrap script, never through here. The
    ONLY difference between the self-signup and landlord callers is `status`.
    """
    org = models.Organization(
        name=org_name, short_code=short_code, country=country, status=status,
    )
    db.add(org)
    db.flush()  # obtain org.id without committing

    staff = models.StaffAccount(
        organization_id=org.id,
        email=admin_email,
        password_hash=hash_password(admin_password),
        full_name=admin_full_name,
        role="admin",  # <-- hardcoded server-side; never taken from client input
    )
    db.add(staff)
    db.commit()
    db.refresh(org)
    db.refresh(staff)
    return org, staff
