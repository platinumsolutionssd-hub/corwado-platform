"""
Advisory router — backed by real PostgreSQL persistence now.

Implements the change-speed caching decision we agreed on earlier:
- Slow-changing baseline (per parcel+crop suitability) lives in the
  parcel_crop_baseline join table and is only recomputed when stale
  (refresh_due) — see db/schema.sql migration note (post-Day 14) for
  why this moved off parcel.baseline_* columns.
- Fast-changing data (weather, NDVI, pest alerts) is always fetched fresh
  and stored as a new advisory_snapshot row — never overwritten, so
  CORWADO's dashboard can show history ("was there a pest warning three
  weeks ago this farmer never saw?").

`BiophysicalEngine` now makes a real HTTP call to agri-venture-v2's
/analyze endpoint (a live external dependency, same category as
Satyukt) — deliberately HTTP, not a direct Python import, so
agri-venture-v2 stays an independently-deployed service and CORWADO's
process never couples to its GEE credentials/dependency tree ("one core
engine, everything else is a deployment"). `SatyuktSat2FarmEngine`
remains a stub — still honest: real Satyukt integration needs their API
credentials under the signed agreement, and shouldn't be faked even at
prototype stage. What changed since Day 1: the results these engines
return now get persisted as real rows, and the baseline caching logic
is real (checks and updates parcel_crop_baseline), not simulated.

Renamed from `digital_twin_score()` per the architecture doc addendum
(v0.2) — "Digital Twin" implies continuous sensor sync to a live
physical asset, which this isn't; it's a batch/on-demand suitability
score. Both engines now also conform to the AdvisoryEngine Protocol
(app/services/advisory_engine.py) since there are two real
implementations sharing one shape — the threshold where that
abstraction is earned, not speculative. No registry or factory added
yet; a third engine (agri-venture-v2) would be the point to reconsider
that, not before.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from geoalchemy2.shape import to_shape
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models

router = APIRouter()

BASELINE_REFRESH_INTERVAL_DAYS = 365  # slow-changing data: recheck yearly

# Base URL for agri-venture-v2's independently-deployed FastAPI service.
# Same env-var-with-localhost-default pattern as DATABASE_URL in
# app/database.py and VITE_API_URL in frontend/.env.example.
AGRIVENTURE_API_URL = os.getenv("AGRIVENTURE_API_URL", "http://localhost:8000")
# /analyze runs live GEE calls (SRTM elevation, CHIRPS rainfall, ERA5-Land
# temp/frost, ISDASOIL pH/clay/depth, plus iSDA nutrient facts and 12
# yearly CHIRPS reduceRegions for rainfall variability). A real GEE
# cold-start hit 120s in testing (steady-state calls run ~8s) -- 150s
# gives headroom above that observed worst case. No background-job/async
# infrastructure added for this: /baseline only runs when stale (yearly)
# or admin-forced, never on a farmer-facing hot path, so an occasional
# slow blocking call is an acceptable tradeoff at this scale (same
# reasoning as declining the event bus earlier).
AGRIVENTURE_TIMEOUT_S = 150


# ---------------------------------------------------------------------
# ENGINES — clearly marked as stubs, each conforms to AdvisoryEngine
# (supports/analyse), returning data in the shared shape
# ---------------------------------------------------------------------
class BiophysicalEngine:
    """
    Calls agri-venture-v2's real /analyze endpoint over HTTP -- a live
    external dependency now, same category as Satyukt below. Deliberately
    HTTP, not a direct Python import: agri-venture-v2 stays an
    independently-deployed service, so CORWADO's process never couples to
    its GEE credentials or dependency tree, and both stay free to be
    hosted separately ("one core engine, everything else is a
    deployment"). See advisory.py docstring re: renaming from
    "Digital Twin".
    """
    def supports(self, crop: str) -> bool:
        # CORWADO's own crop_dictionary_entry check (see get_baseline()
        # below) already gates this before analyse() is ever called;
        # agri-venture-v2 itself 404s/errors on a crop whose biology.json
        # is missing (beans/coffee are empty placeholders there today) --
        # that error surfaces honestly through analyse()'s 502 path
        # rather than being pre-checked here too.
        return True

    def analyse(self, parcel, crop: str) -> dict:
        """
        POSTs {geojson, crop} to agri-venture-v2's /analyze and maps the
        real AnalysisResult response into the two-part shape
        parcel_crop_baseline stores:
          - "suitability": flattened summary (overall_score,
            overall_classification, is_fatal, binding_domain, confidence)
            for cheap dashboard/dispatch reads.
          - "suitability_raw": the full response, unmodified -- every
            DomainResult/FactorScore/Evidence, never discarded, per
            agri-venture-v2's own Explainability Requirement.

        Fails loudly on purpose -- no fallback to fake data, no retry
        loop. A 503 means agri-venture-v2 wasn't reachable at all; a 502
        means it was reachable but returned an error. Either way the
        caller gets a real error, never a silently wrong suitability
        number.
        """
        # agri-venture-v2's own load_crop_biology() (server.py) already
        # lowercases before its crops/<name>/ folder lookup, so this
        # isn't required for agri-venture-v2 to work -- it's cheap
        # insurance on CORWADO's side against the crop_dictionary_entry
        # casing bug found live 2026-07-11 (seed data had "Moringa",
        # folder is crops/moringa/) recurring from a future typo or a
        # different naming convention creeping into crop_dictionary_entry.
        # The real fix is the seed data (see app/seed.py); this is a
        # backstop, not a substitute for it.
        crop = crop.strip().lower()
        geojson = json.loads(json.dumps(to_shape(parcel.geom).__geo_interface__))
        try:
            resp = requests.post(
                f"{AGRIVENTURE_API_URL}/analyze",
                json={"geojson": geojson, "crop": crop},
                timeout=AGRIVENTURE_TIMEOUT_S,
            )
        except requests.RequestException as e:
            raise HTTPException(
                status_code=503,
                detail=f"agri-venture-v2 unreachable at {AGRIVENTURE_API_URL}/analyze: {e}",
            )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"agri-venture-v2 /analyze returned {resp.status_code} "
                    f"for crop='{crop}': {resp.text[:500]}"
                ),
            )

        raw = resp.json()
        summary = {
            "overall_score": raw.get("overall_score"),
            "overall_classification": raw.get("overall_classification"),
            "is_fatal": raw.get("is_fatal"),
            "binding_domain": raw.get("binding_domain"),
            "confidence": raw.get("confidence"),
        }
        return {"suitability": summary, "suitability_raw": raw}


class SatyuktSat2FarmEngine:
    """
    STUB: would call Satyukt's Sat2Farm API — needs real credentials
    under agreement SYA10231/210/2026-03-23 before this can be live.
    """
    def supports(self, crop: str) -> bool:
        return True  # Sat2Farm covers soil/weather regardless of crop

    def analyse(self, parcel, crop: str) -> dict:
        # `crop` is accepted for Protocol conformance but ignored here.
        # OPEN QUESTION (not guessed): does Sat2Farm's real API take a
        # crop parameter at all? It returns soil/weather/NDVI facts that
        # read as crop-independent, but it may use crop internally to
        # scope pest/disease alerts. Resolve this once we have real
        # Sat2Farm API docs/credentials under the signed agreement --
        # don't infer behaviour from a stub.
        return {
            "soil_n": 305, "soil_p": 29, "soil_k": 201, "soil_soc": 1.8, "soil_ph": 6.4,
            "ndvi": 0.62,
            "soil_moisture": 34.2,
            "weather_forecast_json": {"7day_rain_mm": 42, "temp_range_c": [22, 31]},
            "pest_disease_alerts": [],
        }


biophysical_engine = BiophysicalEngine()
satyukt_engine = SatyuktSat2FarmEngine()


class AdvisoryOut(BaseModel):
    id: str
    parcel_id: str
    source: str
    soil_n: Optional[float] = None
    soil_p: Optional[float] = None
    soil_k: Optional[float] = None
    soil_soc: Optional[float] = None
    soil_ph: Optional[float] = None
    ndvi: Optional[float] = None
    soil_moisture: Optional[float] = None
    weather_forecast_json: Optional[dict] = None
    pest_disease_alerts: Optional[list] = None
    generated_at: datetime

    class Config:
        from_attributes = True


@router.get("/parcel/{parcel_id}/baseline")
def get_baseline(parcel_id: str, crop: str, force_refresh: bool = False, db: Session = Depends(get_db)):
    """
    Returns the cached parcel+crop baseline unless it's stale or
    force_refresh is set. Reads/writes parcel_crop_baseline, keyed by
    (parcel_id, crop_id) — replaced the old single baseline_suitability
    JSONB-on-parcel approach (see db/schema.sql migration, post-Day 14):
    that couldn't give more than one crop its own staleness clock, and
    had no FK integrity to crop_dictionary_entry.

    `crop` is the crop's name (e.g. "maize") — the same vocabulary
    agri-venture-v2's biology.json files use. It's resolved against
    crop_dictionary_entry.crop_name to get the real crop_id the join
    table's foreign key needs; the caller never has to know that UUID.
    Required, not defaulted, so a caller can never silently get a
    baseline for the wrong crop.
    """
    parcel = db.query(models.Parcel).filter_by(id=parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")

    crop_entry = db.query(models.CropDictionaryEntry).filter_by(crop_name=crop).first()
    if not crop_entry:
        raise HTTPException(
            status_code=404,
            detail=f"Crop '{crop}' not found in crop_dictionary_entry. Add it before requesting a baseline.",
        )

    baseline = (
        db.query(models.ParcelCropBaseline)
        .filter_by(parcel_id=parcel_id, crop_id=crop_entry.id)
        .first()
    )

    # datetime.utcnow() is naive; computed_at/refresh_due are
    # DateTime(timezone=True) columns, so Postgres/psycopg2 hands back
    # timezone-aware datetimes. Comparing naive vs aware raises TypeError
    # -- only ever surfaced once this ran against a real Postgres row on
    # the cached-baseline path (no mock reproduces real tzinfo). Use an
    # aware "now" throughout so this stays comparable.
    now = datetime.now(timezone.utc)
    is_stale = (
        baseline is None
        or baseline.computed_at is None
        or baseline.refresh_due is None
        or baseline.refresh_due < now
    )

    if is_stale or force_refresh:
        mapped = biophysical_engine.analyse(parcel, crop)
        if baseline is None:
            baseline = models.ParcelCropBaseline(parcel_id=parcel_id, crop_id=crop_entry.id)
            db.add(baseline)
        baseline.suitability = mapped["suitability"]
        baseline.suitability_raw = mapped["suitability_raw"]
        baseline.computed_at = now
        baseline.refresh_due = now + timedelta(days=BASELINE_REFRESH_INTERVAL_DAYS)
        db.commit()
        db.refresh(baseline)
        was_cached = False
    else:
        was_cached = True

    return {
        "parcel_id": parcel_id,
        "crop": crop,
        "cached": was_cached,
        "elevation_m": float(parcel.elevation_m) if parcel.elevation_m else None,
        "soil_type": parcel.soil_type,
        "baseline_suitability": baseline.suitability,
        "baseline_suitability_raw": baseline.suitability_raw,
        "baseline_computed_at": baseline.computed_at,
        "next_refresh_due": baseline.refresh_due,
    }


_LIVE_ALLOWED_SOURCES = {"satyukt_sat2farm", "satyukt_sat4risk", "satyukt_sat4agri"}


@router.get("/parcel/{parcel_id}/live", response_model=AdvisoryOut)
def get_live_advisory(
    parcel_id: str, crop: str, source: str = "satyukt_sat2farm", db: Session = Depends(get_db)
):
    """
    Fast-changing advisory — always fetched fresh, always persisted as a
    new snapshot row (never overwrites the previous one).

    Restricted to satyukt_* sources. BiophysicalEngine is the slow/cached
    engine and belongs only in /baseline (see get_baseline() above) — it
    used to also be reachable here under source='digital_twin', but that
    branch built an AdvisorySnapshot row that never actually stored the
    engine's payload (soil_n/ndvi/etc. stayed null), since BiophysicalEngine
    doesn't return those fields at all. Removed rather than patched: the
    mismatch was structural (a slow suitability engine bolted onto a
    fast-changing-facts snapshot shape), not a bug in how the fields were
    assigned.

    `crop` is required — every AdvisoryEngine.analyse() call needs it
    post-Protocol-change, even though today's SatyuktSat2FarmEngine stub
    ignores it (see the open question in its analyse() docstring).
    """
    if source == "digital_twin":
        raise HTTPException(
            status_code=400,
            detail=(
                "source='digital_twin' is not valid for /live -- BiophysicalEngine "
                "is the slow/cached engine. Use /parcel/{parcel_id}/baseline instead."
            ),
        )
    if source not in _LIVE_ALLOWED_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Must be one of: {sorted(_LIVE_ALLOWED_SOURCES)}.",
        )

    parcel = db.query(models.Parcel).filter_by(id=parcel_id).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")

    payload = satyukt_engine.analyse(parcel, crop)
    snapshot = models.AdvisorySnapshot(
        parcel_id=parcel_id, source=source,
        soil_n=payload["soil_n"], soil_p=payload["soil_p"], soil_k=payload["soil_k"],
        soil_soc=payload["soil_soc"], soil_ph=payload["soil_ph"], ndvi=payload["ndvi"],
        soil_moisture=payload["soil_moisture"],
        weather_forecast_json=payload["weather_forecast_json"],
        pest_disease_alerts=payload["pest_disease_alerts"],
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.get("/parcel/{parcel_id}/history", response_model=List[AdvisoryOut])
def get_advisory_history(parcel_id: str, db: Session = Depends(get_db)):
    return (
        db.query(models.AdvisorySnapshot)
        .filter_by(parcel_id=parcel_id)
        .order_by(models.AdvisorySnapshot.generated_at.desc())
        .all()
    )
