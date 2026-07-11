"""
Parcel router — registers a farm boundary as a GeoJSON polygon.

The offline-first field app walks or draws the farm boundary, sends it
here as GeoJSON. PostGIS stores it as a real polygon (SRID 4326), which
is what lets later queries like "which farms are in this flood zone" or
"how many acres is this" work directly in the database rather than in
application code.
"""
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import shape
from pydantic import BaseModel

from app.database import get_db
from app import models

router = APIRouter()


class ParcelIn(BaseModel):
    id: Optional[str] = None
    steward_id: str
    geojson: dict  # {"type": "Polygon", "coordinates": [[[lon,lat], ...]]}


class ParcelOut(BaseModel):
    id: str
    steward_id: str
    area_acres: Optional[float] = None
    elevation_m: Optional[float] = None
    soil_type: Optional[str] = None
    geojson: Optional[dict] = None

    class Config:
        from_attributes = True


def _parcel_to_out(parcel: models.Parcel) -> ParcelOut:
    # baseline_suitability/baseline_computed_at dropped from this response
    # (see db/schema.sql migration, post-Day 14): baseline is now per
    # parcel+crop, in parcel_crop_baseline, not a single value per parcel
    # -- fetch it via GET /advisory/parcel/{parcel_id}/baseline?crop=...
    # instead.
    geojson = None
    if parcel.geom is not None:
        try:
            shp = to_shape(parcel.geom)
            geojson = json.loads(json.dumps(shp.__geo_interface__))
        except Exception:
            geojson = None
    return ParcelOut(
        id=parcel.id,
        steward_id=parcel.steward_id,
        area_acres=float(parcel.area_acres) if parcel.area_acres is not None else None,
        elevation_m=float(parcel.elevation_m) if parcel.elevation_m is not None else None,
        soil_type=parcel.soil_type,
        geojson=geojson,
    )


@router.post("", response_model=ParcelOut)
def register_parcel(parcel: ParcelIn, db: Session = Depends(get_db)):
    if not db.query(models.LandSteward).filter_by(id=parcel.steward_id).first():
        raise HTTPException(status_code=404, detail="steward_id does not exist — register the steward first")

    try:
        shp = shape(parcel.geojson)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid GeoJSON: {e}")

    if shp.geom_type != "Polygon":
        raise HTTPException(status_code=422, detail="geojson must be a Polygon")

    db_parcel = models.Parcel(
        steward_id=parcel.steward_id,
        geom=from_shape(shp, srid=4326),
    )
    if parcel.id:
        db_parcel.id = parcel.id
    db.add(db_parcel)
    db.commit()
    db.refresh(db_parcel)
    return _parcel_to_out(db_parcel)


@router.get("", response_model=List[ParcelOut])
def list_parcels(steward_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.Parcel)
    if steward_id:
        q = q.filter(models.Parcel.steward_id == steward_id)
    return [_parcel_to_out(p) for p in q.all()]


@router.get("/{parcel_id}", response_model=ParcelOut)
def get_parcel(parcel_id: str, db: Session = Depends(get_db)):
    parcel = db.query(models.Parcel).filter_by(id=parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    return _parcel_to_out(parcel)
