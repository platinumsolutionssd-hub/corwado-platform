"""
Market Linkage router — real DB persistence.
Covers price board, buyer demand postings, aggregation-event coordination,
and the agro-dealer directory, per ToR Scope of Work component #6.
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models
from app.services import dispatch as dispatch_service

router = APIRouter()


# --- Schemas -----------------------------------------------------------
class PriceIn(BaseModel):
    crop_id: str
    market_location: str
    price_ssp: float
    unit: str = "kg"
    recorded_by: Optional[str] = None


class BuyerIn(BaseModel):
    name: str
    contact_phone: Optional[str] = None
    buyer_type: Optional[str] = None


class PostingIn(BaseModel):
    buyer_id: str
    crop_id: str
    quantity_kg: float
    offer_price_ssp: float
    needed_by: Optional[date] = None
    location: Optional[str] = None


class AggregationEventIn(BaseModel):
    cooperative_id: str
    crop_id: str
    collection_point: Optional[str] = None
    scheduled_date: Optional[date] = None


class ContributionIn(BaseModel):
    steward_id: str
    quantity_kg: Optional[float] = None
    attended: bool = False


class DealerIn(BaseModel):
    name: str
    location: Optional[str] = None
    products: Optional[list] = None
    contact_phone: Optional[str] = None


# --- Price board ---------------------------------------------------------
@router.post("/prices")
def record_price(entry: PriceIn, db: Session = Depends(get_db)):
    row = models.PriceBoardEntry(**entry.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/prices")
def list_prices(crop_id: Optional[str] = None, market_location: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.PriceBoardEntry)
    if crop_id:
        q = q.filter(models.PriceBoardEntry.crop_id == crop_id)
    if market_location:
        q = q.filter(models.PriceBoardEntry.market_location == market_location)
    return q.order_by(models.PriceBoardEntry.recorded_at.desc()).all()


# --- Buyers & postings -----------------------------------------------
@router.post("/buyers")
def register_buyer(buyer: BuyerIn, db: Session = Depends(get_db)):
    row = models.Buyer(**buyer.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/postings")
def create_posting(posting: PostingIn, db: Session = Depends(get_db)):
    if not db.query(models.Buyer).filter_by(id=posting.buyer_id).first():
        raise HTTPException(status_code=404, detail="Buyer not found")
    row = models.BuyerPosting(**posting.model_dump(), status="open")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/postings")
def list_postings(status: str = "open", db: Session = Depends(get_db)):
    return db.query(models.BuyerPosting).filter_by(status=status).all()


@router.get("/postings/{posting_id}/matches")
def find_matches(posting_id: str, db: Session = Depends(get_db)):
    """
    Suggests candidate aggregation events that could fulfil this posting:
    same crop, still scheduled (not completed/cancelled), and — where the
    posting has a needed_by date — scheduled on or before it. This is a
    suggestion list for CORWADO staff to review and confirm, not an
    automatic commitment — matching farmers to a buyer without a human
    checking first isn't something to automate at this stage.
    """
    posting = db.query(models.BuyerPosting).filter_by(id=posting_id).first()
    if not posting:
        raise HTTPException(status_code=404, detail="Posting not found")

    q = (
        db.query(models.AggregationEvent)
        .filter(models.AggregationEvent.crop_id == posting.crop_id)
        .filter(models.AggregationEvent.status == "scheduled")
    )
    if posting.needed_by:
        q = q.filter(models.AggregationEvent.scheduled_date <= posting.needed_by)

    candidates = []
    for event in q.all():
        contributed = (
            db.query(models.AggregationContribution)
            .filter_by(aggregation_event_id=event.id)
            .all()
        )
        total_kg = sum(float(c.quantity_kg or 0) for c in contributed)
        candidates.append({
            "aggregation_event_id": event.id,
            "collection_point": event.collection_point,
            "scheduled_date": event.scheduled_date,
            "contributed_kg_so_far": total_kg,
            "posting_quantity_needed_kg": float(posting.quantity_kg or 0),
            "likely_sufficient": total_kg >= float(posting.quantity_kg or 0),
        })
    return {"posting_id": posting_id, "candidates": candidates}


@router.post("/postings/{posting_id}/confirm-match")
def confirm_match(posting_id: str, aggregation_event_id: str, db: Session = Depends(get_db)):
    """
    CORWADO staff confirm a match. This: (1) records the link on the
    posting, (2) marks the posting 'matched', and (3) notifies every
    farmer who has a logged contribution to that aggregation event —
    real dispatch, not a log entry pretending to be one.
    """
    posting = db.query(models.BuyerPosting).filter_by(id=posting_id).first()
    if not posting:
        raise HTTPException(status_code=404, detail="Posting not found")
    event = db.query(models.AggregationEvent).filter_by(id=aggregation_event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Aggregation event not found")

    posting.matched_aggregation_event_id = aggregation_event_id
    posting.status = "matched"

    contributors = (
        db.query(models.AggregationContribution)
        .filter_by(aggregation_event_id=aggregation_event_id)
        .all()
    )
    stewards = db.query(models.LandSteward).filter(
        models.LandSteward.id.in_([c.steward_id for c in contributors])
    ).all()
    for steward in stewards:
        dispatch_service.dispatch_to_steward(db, steward, "buyer_posting", posting.id)

    db.commit()
    db.refresh(posting)
    return posting


# --- Aggregation events ------------------------------------------------
@router.post("/aggregation-events")
def create_aggregation_event(event: AggregationEventIn, db: Session = Depends(get_db)):
    row = models.AggregationEvent(**event.model_dump())
    db.add(row)
    db.flush()  # get row.id before dispatching, without committing yet

    # Notify every steward in this cooperative — they need to know when
    # and where to bring their harvest. This is real dispatch logic, not
    # a TODO: uses the same service built Day 4.
    cooperative_members = (
        db.query(models.LandSteward)
        .filter(models.LandSteward.cooperative_id == event.cooperative_id)
        .all()
    )
    for steward in cooperative_members:
        dispatch_service.dispatch_to_steward(db, steward, "aggregation_alert", row.id)

    db.commit()
    db.refresh(row)
    return row


@router.post("/aggregation-events/{event_id}/contribute")
def log_contribution(event_id: str, contribution: ContributionIn, db: Session = Depends(get_db)):
    event = db.query(models.AggregationEvent).filter_by(id=event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Aggregation event not found")
    row = models.AggregationContribution(aggregation_event_id=event_id, **contribution.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- Agro-dealer directory ----------------------------------------------
@router.post("/dealers")
def register_dealer(dealer: DealerIn, db: Session = Depends(get_db)):
    row = models.AgroDealer(**dealer.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/dealers")
def list_dealers(db: Session = Depends(get_db)):
    return db.query(models.AgroDealer).all()
