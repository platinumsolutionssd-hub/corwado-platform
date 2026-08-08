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
from sqlalchemy import text
from sqlalchemy.orm import Session
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import shape
from pydantic import BaseModel, model_validator

from app.database import get_db
from app import models
from app.deps import get_current_staff
from app.services import telegram_sender
from app.services.boq_seed import ACRES_TO_HECTARES
from app.services.telegram_strings import get_string, language_code_for, DEFAULT_LANGUAGE

router = APIRouter()

# --------------------------------------------------------------------- #
# Large-parcel plausibility guardrail. No authoritative smallholder
# plot-size figure exists for this to be sourced from: the ToR
# (ToR-001-06-2026) is referenced by this project but the document
# itself isn't in this repo (see docs/ACCESSIBILITY.md's own note that
# it hasn't been obtained yet), there is no LAST project baseline survey
# document here either, and a search for FAO / South Sudan Ministry of
# Agriculture smallholder statistics for Western Bahr el Ghazal turned
# up nothing in this codebase (checked 2026-07-16). Per the Scientific
# Evidence rule this project already applies elsewhere (see
# boq_seed.py's FX_RATE_SOURCE, telegram_strings.py's translation
# discipline note), a number without a real source gets labeled as an
# assumption, not presented as if it were sourced.
#
# 10 ha is therefore an EXPERT ASSUMPTION, not a sourced figure -- chosen
# deliberately generous (several times a typical FAO-reported South
# Sudan smallholder cultivated area of roughly 0.5-2 ha) so it only
# catches gross drawing errors (tracing on a zoomed-out map) rather than
# a legitimate large or aggregated/cooperative plot. Replace with a real
# figure once CORWADO's LAST project baseline survey is available.
LARGE_PARCEL_THRESHOLD_HA = 10.0
LARGE_PARCEL_THRESHOLD_ACRES = LARGE_PARCEL_THRESHOLD_HA / ACRES_TO_HECTARES


class ParcelConfirmationRequired(BaseModel):
    """
    Returned instead of ParcelOut when a submission crosses
    LARGE_PARCEL_THRESHOLD_HA and hasn't been confirmed yet -- nothing
    is written to the database when this is returned (see
    register_parcel below). confirmation_required is a fixed True so a
    caller can tell the two response shapes apart with one field check.
    """
    confirmation_required: bool = True
    area_ha: float
    area_acres: float
    threshold_ha: float
    message: str


def _preview_area_acres(db: Session, shp) -> Optional[float]:
    """
    Computes area using the exact same expression as parcel.area_acres's
    generated column (db/schema.sql: ST_Area(geom::geography)/4046.86),
    run here before any row exists purely so the guardrail can compare
    against the threshold. Never written anywhere -- parcel.area_acres
    remains the single source of truth once a row is actually inserted,
    this is not a second implementation of it.
    """
    return db.execute(
        text("SELECT ST_Area(ST_GeogFromText(:wkt)) / 4046.86"),
        {"wkt": f"SRID=4326;{shp.wkt}"},
    ).scalar()


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
    # Only meaningful on the steward_id (dashboard) path: set True to
    # re-submit the same geojson after the caller already saw a
    # confirmation_required response and the user chose "save anyway".
    # The token (Telegram hand-off) path ignores this entirely -- that
    # path's confirmation happens via a YES/NO reply in the originating
    # chat instead, see register_parcel below.
    confirm_large_area: bool = False

    @model_validator(mode="after")
    def _one_of_steward_or_token(self):
        if bool(self.steward_id) == bool(self.token):
            raise ValueError("Provide exactly one of steward_id or token")
        return self


class ParcelOut(BaseModel):
    id: str
    steward_id: str
    area_acres: Optional[float] = None
    area_flagged_large: bool = False
    area_confirmed_at: Optional[datetime] = None
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
        area_flagged_large=bool(parcel.area_flagged_large),
        area_confirmed_at=parcel.area_confirmed_at,
        elevation_m=float(parcel.elevation_m) if parcel.elevation_m is not None else None,
        soil_type=parcel.soil_type,
        geojson=geojson,
    )


def _peek_draw_token(db: Session, token: str) -> models.ParcelDrawToken:
    """
    Validates a parcel_draw_token (exists / not used / not expired)
    WITHOUT consuming it -- shared by get_draw_token's page-load check
    and register_parcel's pre-insert large-area preview below, both of
    which need to resolve the steward before deciding whether this
    submission can actually be saved yet. Consumption stays the sole
    job of _consume_draw_token's atomic UPDATE, called only once a
    submission is actually about to be persisted.
    """
    row = db.query(models.ParcelDrawToken).filter_by(token=token).first()
    if not row:
        raise HTTPException(status_code=404, detail="Invalid boundary link — ask CORWADO staff to send a new one.")
    if row.used_at is not None:
        raise HTTPException(status_code=409, detail="This boundary link has already been used — ask CORWADO staff to send a new one.")
    if row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This boundary link has expired — ask CORWADO staff to send a new one.")
    return row


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
    row = _peek_draw_token(db, token)
    steward = db.query(models.LandSteward).filter_by(id=row.steward_id).first()
    if not steward:
        raise HTTPException(status_code=404, detail="The farmer this link was created for no longer exists.")
    return {"steward_id": steward.id, "full_name": steward.full_name, "expires_at": row.expires_at}


@router.post("", response_model=None)
def register_parcel(parcel: ParcelIn, db: Session = Depends(get_db)):
    try:
        shp = shape(parcel.geojson)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid GeoJSON: {e}")

    if shp.geom_type != "Polygon":
        raise HTTPException(status_code=422, detail="geojson must be a Polygon")

    # Resolve who this is for WITHOUT consuming the token yet -- a
    # large-area submission on the token path defers the actual save to
    # a Telegram YES/NO reply (below), so the token can't be spent here;
    # it's spent only once we know this submission is actually going to
    # be persisted (either under threshold, or over it and about to be
    # staged for confirmation).
    if parcel.token:
        token_row = _peek_draw_token(db, parcel.token)
        steward_id = token_row.steward_id
    else:
        token_row = None
        if not db.query(models.LandSteward).filter_by(id=parcel.steward_id).first():
            raise HTTPException(status_code=404, detail="steward_id does not exist — register the steward first")
        steward_id = parcel.steward_id

    preview_acres = _preview_area_acres(db, shp)
    flagged = preview_acres is not None and preview_acres > LARGE_PARCEL_THRESHOLD_ACRES

    if flagged and not parcel.confirm_large_area:
        area_ha = preview_acres * ACRES_TO_HECTARES
        if token_row is not None:
            # Telegram-originated (self-service farmer or staff
            # hand-off): the person who drew this may not still be
            # looking at the browser by the time they'd see an in-page
            # dialog (same reasoning DrawBoundaryPage's existing "check
            # Telegram for a confirmation" copy already assumes for a
            # normal save) -- so the confirmation itself happens as a
            # YES/NO reply in whichever chat generated the link, not a
            # second POST from this page. Spend the token now (this
            # specific drawing attempt is used up either way) and stash
            # the geometry on it until that reply comes in.
            token_row = _consume_draw_token(db, parcel.token)
            token_row.pending_geojson = parcel.geojson
            steward = db.query(models.LandSteward).filter_by(id=steward_id).first()
            self_service = steward.telegram_chat_id == token_row.originating_chat_id
            lang = language_code_for(steward.preferred_language) if self_service else DEFAULT_LANGUAGE
            state = db.query(models.TelegramConversationState).filter_by(chat_id=token_row.originating_chat_id).first()
            if not state:
                state = models.TelegramConversationState(chat_id=token_row.originating_chat_id, context={})
                db.add(state)
            state.awaiting = "boundary_large_area_confirm"
            state.context = {"draw_token": parcel.token}
            db.commit()
            telegram_sender.send(
                token_row.originating_chat_id,
                get_string("boundary_large_area_confirm", lang, name=steward.full_name, ha=f"{area_ha:.1f}"),
            )
            return ParcelConfirmationRequired(
                area_ha=area_ha, area_acres=preview_acres, threshold_ha=LARGE_PARCEL_THRESHOLD_HA,
                message="This boundary is unusually large — check Telegram to confirm or redraw.",
            )
        # Dashboard path: staff is at the browser right now, so the
        # confirmation is an in-page prompt instead -- no DB write at
        # all yet. The caller re-submits with confirm_large_area=true
        # (same geojson) to proceed, or just draws again.
        return ParcelConfirmationRequired(
            area_ha=area_ha, area_acres=preview_acres, threshold_ha=LARGE_PARCEL_THRESHOLD_HA,
            message=(
                f"This boundary covers about {area_ha:.1f} ha — much larger than a typical "
                f"smallholder plot (guideline: {LARGE_PARCEL_THRESHOLD_HA:.0f} ha). Save anyway, or redraw?"
            ),
        )

    if token_row is not None:
        # Claims the token inside this same db session/transaction — the
        # parcel INSERT below and this UPDATE commit together in one
        # db.commit() call, so a failure after claiming but before the
        # insert rolls back both and leaves the token reusable, and a
        # successful save can never leave the token unmarked.
        token_row = _consume_draw_token(db, parcel.token)

    db_parcel = models.Parcel(
        steward_id=steward_id,
        geom=from_shape(shp, srid=4326),
        area_flagged_large=flagged,
        area_confirmed_at=datetime.now(timezone.utc) if flagged else None,
    )
    if parcel.id:
        db_parcel.id = parcel.id
    db.add(db_parcel)
    db.commit()
    db.refresh(db_parcel)

    if token_row is not None:
        steward = db.query(models.LandSteward).filter_by(id=steward_id).first()
        area = f"{db_parcel.area_acres:.2f} acres" if db_parcel.area_acres is not None else "area pending"
        note = " (confirmed as unusually large)" if flagged else ""
        # Best-effort: the parcel is already saved regardless of whether
        # this send succeeds, same "never block the real write on a
        # notification" posture as dispatch_to_steward()'s delivery_note
        # handling — nothing here rolls back the save on a failed send.
        telegram_sender.send(
            token_row.originating_chat_id,
            f"Boundary saved for {steward.full_name}: {area}{note}.",
        )

    return _parcel_to_out(db_parcel)


@router.get("", response_model=List[ParcelOut])
def list_parcels(steward_id: Optional[str] = None,
                 staff: models.StaffAccount = Depends(get_current_staff),
                 db: Session = Depends(get_db)):
    q = db.query(models.Parcel)
    if steward_id:
        q = q.filter(models.Parcel.steward_id == steward_id)
    return [_parcel_to_out(p) for p in q.all()]


@router.get("/{parcel_id}", response_model=ParcelOut)
def get_parcel(parcel_id: str,
               staff: models.StaffAccount = Depends(get_current_staff),
               db: Session = Depends(get_db)):
    parcel = db.query(models.Parcel).filter_by(id=parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    return _parcel_to_out(parcel)
