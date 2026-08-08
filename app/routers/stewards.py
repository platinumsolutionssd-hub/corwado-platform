"""
Land Steward router — registration and profiling, backed by PostgreSQL.

Offline-first design (ToR requirement): the field registration app writes
records locally on the device with a client-generated UUID. When
connectivity returns, it POSTs a batch to /sync. Each record's
`registered_offline` flag stays True permanently (it's a fact about how
the record was captured), but `synced_at` moves from null to the sync
timestamp — that's the signal the dashboard uses to show "pending sync"
counts to CORWADO staff.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models
from app.deps import get_current_staff
from app.services.steward_registration import create_steward

# Router-level dependency: EVERY route here is authenticated + org-scoped.
# No individual route can forget it. Reads need no further change — RLS scopes
# them, so a cross-org GET by id returns None -> the existing 404.
router = APIRouter(dependencies=[Depends(get_current_staff)])


class StewardIn(BaseModel):
    id: Optional[str] = None  # client-generated if created offline
    role: str
    full_name: str
    phone_number: Optional[str] = None
    whatsapp_number: Optional[str] = None
    preferred_language: str = "juba_arabic"
    preferred_channel: Optional[str] = None
    gender: Optional[str] = None
    is_youth: bool = False
    has_disability: bool = False
    disability_notes: Optional[str] = None
    cooperative_id: Optional[str] = None
    registered_by: Optional[str] = None
    registered_offline: bool = False


class StewardUpdate(BaseModel):
    """
    Partial update for the "edit farmer" dashboard action -- every field
    optional, and only the ones the caller actually sets are touched
    (model_dump(exclude_unset=True) below), so a PATCH that only sends
    `gender` can't accidentally null out phone_number etc.
    """
    role: Optional[str] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    whatsapp_number: Optional[str] = None
    preferred_language: Optional[str] = None
    preferred_channel: Optional[str] = None
    gender: Optional[str] = None
    is_youth: Optional[bool] = None
    has_disability: Optional[bool] = None
    disability_notes: Optional[str] = None
    cooperative_id: Optional[str] = None


class StewardOut(StewardIn):
    created_at: datetime
    synced_at: Optional[datetime] = None
    # Resolved from the cooperative_id FK via LandSteward.cooperative_name
    # (app/models.py) -- the farmer detail view needs a human-readable
    # name, not the raw UUID cooperative_id already exposed above.
    cooperative_name: Optional[str] = None

    class Config:
        from_attributes = True


@router.post("", response_model=StewardOut)
def register_steward(steward: StewardIn, force_create: bool = False,
                     staff: models.StaffAccount = Depends(get_current_staff),
                     db: Session = Depends(get_db)):
    """
    Single, online registration — sets synced_at immediately.

    Flags (not silently ignores, not silently duplicates) an existing
    steward with the same phone_number: without force_create=true, a
    match returns 409 with the existing record so the caller can show
    "already registered as X — continue anyway?" rather than either
    refusing outright (a household can legitimately share one phone
    across stewards) or silently creating a duplicate. See
    app/services/steward_registration.py.
    """
    db_steward, duplicate = create_steward(
        db, steward.model_dump(), force_create=force_create,
        organization_id=staff.organization_id,   # stamped from the authed staff, never client input
    )
    if db_steward is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"A farmer with this phone number is already registered: {duplicate.full_name}.",
                "existing_steward_id": duplicate.id,
                "existing_full_name": duplicate.full_name,
                "existing_created_at": duplicate.created_at.isoformat(),
            },
        )
    return db_steward


@router.post("/sync", response_model=List[StewardOut])
def sync_offline_batch(stewards: List[StewardIn], db: Session = Depends(get_db)):
    """
    Bulk endpoint the mobile app calls once it regains connectivity.
    Upserts by client-generated id so a re-sent batch (e.g. after a
    dropped connection mid-sync) doesn't create duplicates.
    """
    results = []
    for steward in stewards:
        data = steward.model_dump()
        row_id = data.pop("id", None)
        existing = db.query(models.LandSteward).filter_by(id=row_id).first() if row_id else None
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            existing.synced_at = datetime.utcnow()
            db_steward = existing
        else:
            db_steward = models.LandSteward(**data, synced_at=datetime.utcnow())
            if row_id:
                db_steward.id = row_id
            db.add(db_steward)
        results.append(db_steward)
    db.commit()
    for r in results:
        db.refresh(r)
    return results


@router.get("", response_model=List[StewardOut])
def list_stewards(
    cooperative_id: Optional[str] = None,
    has_disability: Optional[bool] = None,
    pending_sync_only: bool = False,
    db: Session = Depends(get_db),
):
    q = db.query(models.LandSteward)
    if cooperative_id:
        q = q.filter(models.LandSteward.cooperative_id == cooperative_id)
    if has_disability is not None:
        q = q.filter(models.LandSteward.has_disability == has_disability)
    if pending_sync_only:
        q = q.filter(models.LandSteward.synced_at.is_(None))
    return q.all()


@router.get("/{steward_id}", response_model=StewardOut)
def get_steward(steward_id: str, db: Session = Depends(get_db)):
    steward = db.query(models.LandSteward).filter_by(id=steward_id).first()
    if not steward:
        raise HTTPException(status_code=404, detail="Steward not found")
    return steward


@router.patch("/{steward_id}", response_model=StewardOut)
def update_steward(steward_id: str, update: StewardUpdate, db: Session = Depends(get_db)):
    """Edits an existing farmer's profile fields -- the dashboard's "Edit" action."""
    steward = db.query(models.LandSteward).filter_by(id=steward_id).first()
    if not steward:
        raise HTTPException(status_code=404, detail="Steward not found")
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(steward, field, value)
    db.commit()
    db.refresh(steward)
    return steward


@router.delete("/{steward_id}", status_code=204)
def delete_steward(steward_id: str, db: Session = Depends(get_db)):
    """
    Removes a farmer -- the dashboard's "Delete" action. No table in
    db/schema.sql declares ON DELETE CASCADE from parcel, message_dispatch,
    etc. back to land_steward, so deleting a steward who already has real
    data attached (a mapped parcel, dispatch history, ...) is correctly
    rejected by Postgres's own foreign-key constraint rather than silently
    orphaning or cascading through records this endpoint was never asked
    to touch -- that's surfaced here as a 409 telling the caller what's
    still attached, not a 500.
    """
    steward = db.query(models.LandSteward).filter_by(id=steward_id).first()
    if not steward:
        raise HTTPException(status_code=404, detail="Steward not found")
    try:
        db.delete(steward)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot delete this farmer: they still have parcels, seasons, "
                "or dispatch history linked to their record. Remove those first."
            ),
        )
