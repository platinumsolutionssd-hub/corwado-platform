"""
Parcel router — registers a farm boundary as a GeoJSON polygon.

The offline-first field app walks or draws the farm boundary, sends it
here as GeoJSON. PostGIS stores it as a real polygon (SRID 4326), which
is what lets later queries like "which farms are in this flood zone" or
"how many acres is this" work directly in the database rather than in
application code.
"""
import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import shape
from pydantic import BaseModel, model_validator

from app.database import get_db
from app import models
from app.services import telegram_sender

router = APIRouter()


class ParcelIn(BaseModel):
    id: Optional[str] = None
    # Exactly one of steward_id / token must be set. steward_id is the
    # normal dashboard path (staff is already looking at that steward's
    # record). token is the Telegram BOUNDARY hand-off path: the public
    # draw-boundary page has no other way to know who it's authorized
    # for, so the steward is resolved server-side from the token instead
    # of trusted from the client body -- see register_parcel() below.
    steward_id: Optional[str] = None
    token: Optional[str] = None
    geojson: dict  # {"type": "Polygon", "coordinates": [[[lon,lat], ...]]}

    @model_validator(mode="after")
    def _one_of_steward_or_token(self):
        if bool(self.steward_id) == bool(self.token):
            raise ValueError("Provide exactly one of steward_id or token")
        return self


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


def _consume_draw_token(db: Session, token: str) -> models.ParcelDrawToken:
    """
    Atomically claims a parcel_draw_token: a single UPDATE ... WHERE
    used_at IS NULL AND expires_at > now(), same idiom as the
    baseline-race fix in app/routers/advisory.py (INSERT ... ON CONFLICT
    there, an atomic UPDATE here) -- Postgres row-locks the token row for
    the life of this statement, so two concurrent submissions of the
    same token can't both pass the check. The loser's UPDATE affects 0
    rows once the winner commits, which is what raises the 409 below --
    not a separate SELECT-then-act race window.

    Raises a distinct HTTPException per failure reason (not found /
    already used / expired) so a staffer retrying gets a message that
    tells them what actually happened, not a dead end.
    """
    now = datetime.now(timezone.utc)
    updated = (
        db.query(models.ParcelDrawToken)
        .filter(
            models.ParcelDrawToken.token == token,
            models.ParcelDrawToken.used_at.is_(None),
            models.ParcelDrawToken.expires_at > now,
        )
        .update({"used_at": now}, synchronize_session=False)
    )
    if updated == 0:
        row = db.query(models.ParcelDrawToken).filter_by(token=token).first()
        if not row:
            raise HTTPException(status_code=404, detail="Invalid boundary link — ask CORWADO staff to send a new one.")
        if row.used_at is not None:
            raise HTTPException(status_code=409, detail="This boundary link has already been used — ask CORWADO staff to send a new one.")
        raise HTTPException(status_code=410, detail="This boundary link has expired — ask CORWADO staff to send a new one.")

    row = db.query(models.ParcelDrawToken).filter_by(token=token).first()
    return row


@router.get("/draw-token/{token}")
def get_draw_token(token: str, db: Session = Depends(get_db)):
    """
    Read-only validity check the draw-boundary page calls on load, before
    the farmer/staffer has drawn anything -- lets the page show "trace
    {full_name}'s farm" and fail fast with a clear message if the link
    is already dead, rather than only discovering that at submit time.
    Does NOT consume the token (see _consume_draw_token, used only by
    the actual POST /api/parcels save below).
    """
    row = db.query(models.ParcelDrawToken).filter_by(token=token).first()
    if not row:
        raise HTTPException(status_code=404, detail="Invalid boundary link — ask CORWADO staff to send a new one.")
    if row.used_at is not None:
        raise HTTPException(status_code=409, detail="This boundary link has already been used — ask CORWADO staff to send a new one.")
    now = datetime.now(timezone.utc)
    if row.expires_at <= now:
        raise HTTPException(status_code=410, detail="This boundary link has expired — ask CORWADO staff to send a new one.")

    steward = db.query(models.LandSteward).filter_by(id=row.steward_id).first()
    if not steward:
        raise HTTPException(status_code=404, detail="The farmer this link was created for no longer exists.")
    return {"steward_id": steward.id, "full_name": steward.full_name, "expires_at": row.expires_at}


@router.post("", response_model=ParcelOut)
def register_parcel(parcel: ParcelIn, db: Session = Depends(get_db)):
    try:
        shp = shape(parcel.geojson)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid GeoJSON: {e}")

    if shp.geom_type != "Polygon":
        raise HTTPException(status_code=422, detail="geojson must be a Polygon")

    token_row = None
    if parcel.token:
        # Claims the token inside this same db session/transaction — the
        # parcel INSERT below and this UPDATE commit together in one
        # db.commit() call, so a failure after claiming but before the
        # insert rolls back both and leaves the token reusable, and a
        # successful save can never leave the token unmarked.
        token_row = _consume_draw_token(db, parcel.token)
        steward_id = token_row.steward_id
    else:
        if not db.query(models.LandSteward).filter_by(id=parcel.steward_id).first():
            raise HTTPException(status_code=404, detail="steward_id does not exist — register the steward first")
        steward_id = parcel.steward_id

    db_parcel = models.Parcel(
        steward_id=steward_id,
        geom=from_shape(shp, srid=4326),
    )
    if parcel.id:
        db_parcel.id = parcel.id
    db.add(db_parcel)
    db.commit()
    db.refresh(db_parcel)

    if token_row is not None:
        steward = db.query(models.LandSteward).filter_by(id=steward_id).first()
        area = f"{db_parcel.area_acres:.2f} acres" if db_parcel.area_acres is not None else "area pending"
        # Best-effort: the parcel is already saved regardless of whether
        # this send succeeds, same "never block the real write on a
        # notification" posture as dispatch_to_steward()'s delivery_note
        # handling — nothing here rolls back the save on a failed send.
        telegram_sender.send(
            token_row.originating_chat_id,
            f"Boundary saved for {steward.full_name}: {area}.",
        )

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
