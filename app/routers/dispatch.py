"""
Dispatch router.

Three kinds of endpoint:
1. Trigger endpoints — fire a dispatch for a specific piece of content
   (an advisory snapshot, a price update, a radio broadcast).
2. Log endpoint — the audit trail CORWADO's Section 6 (Financial
   Inclusion / advisory-adherence) and Section 9 (M&E dashboard) both
   depend on: every dispatch is traceable back to its source content
   and its recipient.
3. Stats endpoint — channel-mix breakdown, useful for the dashboard's
   donor-reporting view (e.g. "60% of farmers reached via radio this
   month" is exactly the kind of number a Norad report would want).
"""
from collections import Counter
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models
from app.deps import get_current_staff
from app.services import dispatch as dispatch_service

# Router-level auth+scope. The trigger endpoints insert MessageDispatch via
# dispatch_service, which stamps org from the steward/slot (== current_org).
router = APIRouter(dependencies=[Depends(get_current_staff)])


class DispatchOut(BaseModel):
    id: str
    steward_id: Optional[str] = None
    channel: str
    radio_slot_id: Optional[str] = None
    content_type: str
    content_ref_id: Optional[str] = None
    content_format: str = "text"
    delivery_status: str
    # Was missing from this schema even though message_dispatch.sent_at
    # (app/models.py) has always existed -- response_model=DispatchOut
    # silently dropped it from every /log response. Found while verifying
    # /log's real shape against the running backend for the farmer detail
    # view, which needs sent_at for the chronological history list.
    sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RadioStationIn(BaseModel):
    name: str
    frequency: Optional[str] = None
    payam_coverage: List[str]
    language: str = "juba_arabic"
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None


class RadioSlotIn(BaseModel):
    radio_station_id: str
    day_of_week: str  # mon|tue|wed|thu|fri|sat|sun
    time_slot: str    # e.g. "18:00-18:15"
    program_name: Optional[str] = None


@router.post("/radio-stations")
def register_radio_station(station: RadioStationIn, staff: models.StaffAccount = Depends(get_current_staff), db: Session = Depends(get_db)):
    row = models.RadioStation(**station.model_dump(), organization_id=staff.organization_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/radio-stations")
def list_radio_stations(payam: Optional[str] = None, db: Session = Depends(get_db)):
    stations = db.query(models.RadioStation).all()
    if payam:
        stations = [s for s in stations if s.payam_coverage and payam in s.payam_coverage]
    return stations


@router.post("/radio-slots")
def register_radio_slot(slot: RadioSlotIn, staff: models.StaffAccount = Depends(get_current_staff), db: Session = Depends(get_db)):
    if not db.query(models.RadioStation).filter_by(id=slot.radio_station_id).first():
        raise HTTPException(status_code=404, detail="Radio station not found")
    row = models.RadioBroadcastSlot(**slot.model_dump(), organization_id=staff.organization_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/advisory/{parcel_id}", response_model=DispatchOut)
def trigger_advisory_dispatch(parcel_id: str, db: Session = Depends(get_db)):
    """Dispatches the most recent advisory snapshot for this parcel to its steward."""
    parcel = db.query(models.Parcel).filter_by(id=parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    snapshot = (
        db.query(models.AdvisorySnapshot)
        .filter_by(parcel_id=parcel_id)
        .order_by(models.AdvisorySnapshot.generated_at.desc())
        .first()
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail="No advisory snapshot exists for this parcel yet")
    steward = db.query(models.LandSteward).filter_by(id=parcel.steward_id).first()
    row = dispatch_service.dispatch_to_steward(db, steward, "advisory", snapshot.id)
    db.commit()
    db.refresh(row)
    return row


@router.post("/price-alert/{crop_id}", response_model=List[DispatchOut])
def trigger_price_broadcast(crop_id: str, price_entry_id: str, db: Session = Depends(get_db)):
    """Broadcasts a price update to every steward currently growing this crop."""
    rows = dispatch_service.broadcast_to_crop_growers(db, crop_id, "price_update", price_entry_id)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


@router.post("/radio/{payam}", response_model=DispatchOut)
def trigger_radio_broadcast(payam: str, content_type: str, content_ref_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Dispatches to a real, registered radio slot covering this payam — closes the radio-channel gap flagged in the ToR review."""
    try:
        row = dispatch_service.broadcast_to_payam(db, payam, content_type, content_ref_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    db.commit()
    db.refresh(row)
    return row


@router.get("/log", response_model=List[DispatchOut])
def dispatch_log(
    steward_id: Optional[str] = None,
    channel: Optional[str] = None,
    content_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.MessageDispatch)
    if steward_id:
        q = q.filter(models.MessageDispatch.steward_id == steward_id)
    if channel:
        q = q.filter(models.MessageDispatch.channel == channel)
    if content_type:
        q = q.filter(models.MessageDispatch.content_type == content_type)
    return q.order_by(models.MessageDispatch.sent_at.desc()).all()


@router.get("/stats")
def dispatch_stats(db: Session = Depends(get_db)):
    """
    Channel-mix breakdown — the kind of figure a donor M&E report would
    want ("X% of farmers reached via radio vs SMS this period").
    """
    rows = db.query(models.MessageDispatch).all()
    by_channel = Counter(r.channel for r in rows)
    by_content_type = Counter(r.content_type for r in rows)
    return {
        "total_dispatches": len(rows),
        "by_channel": dict(by_channel),
        "by_content_type": dict(by_content_type),
    }
