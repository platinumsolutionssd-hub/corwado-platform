"""
Authorized operator router — the admin side of chat-based registration
authorization (see db/schema.sql's authorized_operator migration note).

This is the ONLY way an authorized_operator row can be created: there is
no self-registration path, by design. A staffer/Digital Champion still
has to separately link their Telegram chat_id by sending "STAFF <phone>"
to the bot (app/services/telegram_inbound.py) — this endpoint just puts
their phone number on the allow-list an admin controls.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models
from app.deps import get_current_staff, require_org_admin
from app.services.steward_registration import normalize_phone

# Router-level get_current_staff => any authenticated staff for reads; the two
# management endpoints (add / revoke) additionally require an org-admin.
router = APIRouter(dependencies=[Depends(get_current_staff)])


class AuthorizedOperatorIn(BaseModel):
    full_name: str
    phone_number: str
    role: Optional[str] = None  # 'corwado_staff' | 'digital_champion' — reporting only
    added_by: str


class AuthorizedOperatorOut(BaseModel):
    id: str
    full_name: str
    phone_number: str
    role: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    added_by: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("", response_model=AuthorizedOperatorOut)
def add_authorized_operator(operator: AuthorizedOperatorIn,
                            staff: models.StaffAccount = Depends(require_org_admin),
                            db: Session = Depends(get_db)):
    phone = normalize_phone(operator.phone_number)
    existing = db.query(models.AuthorizedOperator).filter_by(phone_number=phone).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"{existing.full_name} is already authorized under this phone number.",
        )
    row = models.AuthorizedOperator(
        full_name=operator.full_name,
        organization_id=staff.organization_id,   # stamped from authed staff (== current_org)
        phone_number=phone,
        role=operator.role,
        added_by=operator.added_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=List[AuthorizedOperatorOut])
def list_authorized_operators(active_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(models.AuthorizedOperator)
    if active_only:
        q = q.filter(models.AuthorizedOperator.is_active.is_(True))
    return q.all()


@router.patch("/{operator_id}/revoke", response_model=AuthorizedOperatorOut)
def revoke_authorized_operator(operator_id: str,
                               admin: models.StaffAccount = Depends(require_org_admin),
                               db: Session = Depends(get_db)):
    """
    Turns off is_active without deleting the row — access removal stays
    an auditable fact ("X was authorized, then revoked"), same reasoning
    as land_steward.registered_offline never being erased.
    """
    row = db.query(models.AuthorizedOperator).filter_by(id=operator_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Authorized operator not found")
    row.is_active = False
    db.commit()
    db.refresh(row)
    return row
