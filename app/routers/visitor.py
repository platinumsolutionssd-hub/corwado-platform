"""
Visitor (unauthenticated) routes — modes 2A and 2B.

HARD INVARIANT (enforced by app/test_visitor_no_db.py): this module must never
import app.database or app.models and must never touch Postgres. 2A returns a
static canned report; 2B is a stateless pass-through to agri-venture-v2.
"""
import os

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.visitor_sample import SAMPLE_REPORT  # pure-data module; imports nothing from app.*

router = APIRouter()

AGRIVENTURE_API_URL = os.getenv("AGRIVENTURE_API_URL", "http://localhost:8000")
AGRIVENTURE_TIMEOUT_S = 150


# ---- Mode 2A: static sample report (zero compute, zero DB) ----
@router.get("/sample-report")
def visitor_sample_report():
    return SAMPLE_REPORT


# ---- Mode 2B: live-computation-only, DB-free pass-through ----
class VisitorAnalyzeIn(BaseModel):
    # Only geojson + crop are accepted. No parcel_id, no steward_id — there is
    # nothing here that could key a database lookup.
    geojson: dict
    crop: str


@router.post("/analyze")
def visitor_live_analyze(payload: VisitorAnalyzeIn):
    # No `db` parameter, no Session, no models import in this function's reach:
    # there is structurally no path from here to a database write. The result
    # is returned to the caller and discarded.
    try:
        resp = requests.post(
            f"{AGRIVENTURE_API_URL}/analyze",
            json={"geojson": payload.geojson, "crop": payload.crop.strip().lower()},
            timeout=AGRIVENTURE_TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=503, detail=f"agri-venture-v2 unreachable: {e}")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"agri-venture-v2 /analyze returned {resp.status_code}")
    return resp.json()
