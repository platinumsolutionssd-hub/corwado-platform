"""
Season Planting router.

A season_planting row is "this crop, on this parcel, starting this
date, for this season" -- the scope a Bill of Quantities (input
requirements + financing, see app/routers/inputs.py) actually belongs
to. Deliberately not folded into parcels.py: a parcel can carry many
seasons over its lifetime (this table has no uniqueness constraint
tying it to "one active season per parcel" -- multiple rows, current
and historical, are expected, same pattern as advisory_snapshot's
history), and this router's only job is creating/listing them.
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models
from app.deps import get_current_staff

router = APIRouter(dependencies=[Depends(get_current_staff)])


class SeasonPlantingIn(BaseModel):
    parcel_id: str
    crop: str  # crop name, e.g. "maize" -- same vocabulary as /baseline's `crop` param
    sowing_date: Optional[date] = None
    season_label: Optional[str] = None  # e.g. "2026 Wet Season"


class SeasonPlantingOut(BaseModel):
    id: str
    parcel_id: str
    crop_id: str
    crop_name: str
    sowing_date: Optional[date] = None
    season_label: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


def _season_to_out(season: models.SeasonPlanting, crop_name: str) -> SeasonPlantingOut:
    return SeasonPlantingOut(
        id=season.id,
        parcel_id=season.parcel_id,
        crop_id=season.crop_id,
        crop_name=crop_name,
        sowing_date=season.sowing_date,
        season_label=season.season_label,
        created_at=season.created_at.isoformat() if season.created_at else None,
    )


@router.post("", response_model=SeasonPlantingOut)
def start_season(season: SeasonPlantingIn,
                 staff: models.StaffAccount = Depends(get_current_staff),
                 db: Session = Depends(get_db)):
    """
    Starts a season_planting cycle -- the "Start a season" action a
    parcel card offers before its Bill of Quantities can exist. Crop is
    resolved by name (same vocabulary/lookup as get_baseline() in
    advisory.py) so the caller never has to know crop_dictionary_entry's
    UUID.
    """
    parcel = db.query(models.Parcel).filter_by(id=season.parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")

    crop_entry = db.query(models.CropDictionaryEntry).filter_by(crop_name=season.crop).first()
    if not crop_entry:
        raise HTTPException(
            status_code=404,
            detail=f"Crop '{season.crop}' not found in crop_dictionary_entry. Add it before starting a season.",
        )

    row = models.SeasonPlanting(
        parcel_id=season.parcel_id,
        organization_id=staff.organization_id,   # stamped from authed staff (== current_org)
        crop_id=crop_entry.id,
        sowing_date=season.sowing_date,
        season_label=season.season_label,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _season_to_out(row, crop_entry.crop_name)


@router.get("", response_model=List[SeasonPlantingOut])
def list_seasons(parcel_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.SeasonPlanting)
    if parcel_id:
        q = q.filter(models.SeasonPlanting.parcel_id == parcel_id)
    seasons = q.order_by(models.SeasonPlanting.created_at.desc()).all()

    crop_ids = {s.crop_id for s in seasons}
    crops = {
        c.id: c.crop_name
        for c in db.query(models.CropDictionaryEntry).filter(models.CropDictionaryEntry.id.in_(crop_ids)).all()
    } if crop_ids else {}

    return [_season_to_out(s, crops.get(s.crop_id, "unknown")) for s in seasons]
