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
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models

router = APIRouter()


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


class StewardOut(StewardIn):
    created_at: datetime
    synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.post("", response_model=StewardOut)
def register_steward(steward: StewardIn, db: Session = Depends(get_db)):
    """Single, online registration — sets synced_at immediately."""
    data = steward.model_dump()
    row_id = data.pop("id", None)
    db_steward = models.LandSteward(**data)
    if row_id:
        db_steward.id = row_id
    if not steward.registered_offline:
        db_steward.synced_at = datetime.utcnow()
    db.add(db_steward)
    db.commit()
    db.refresh(db_steward)
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
