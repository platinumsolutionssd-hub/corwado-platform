"""
Bill of Quantities (input_requirement) + financing ledger
(input_financing_record) router.

Explicitly a transparent record-keeping tool, NOT a creditworthiness or
eligibility signal -- same firewall enforced everywhere else in this
project (CORWADO never assesses the person, only records facts).
Nothing here computes a score, a recommendation, or an approve/decline
verdict; it only stores and returns what was entered.

All costs are USD. See db/schema.sql migration note (Bill of Quantities)
for the full reasoning on source-currency/fx-rate provenance and why
this is a separate table from parcel_crop_baseline/parcel_diagnostic.
"""
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models
from app.services.boq_seed import seed_maize_baseline, ACRES_TO_HECTARES

router = APIRouter()


# --------------------------------------------------------------------- #
# input_requirement -- one Bill of Quantities line item
# --------------------------------------------------------------------- #

class InputRequirementIn(BaseModel):
    season_planting_id: str
    item_name: str
    category: str  # seed | fertilizer | pesticide | labour | other
    quantity: float
    unit: str
    unit_cost_usd: float
    cost_source: str  # e.g. 'agriventure_kalro_baseline' | 'corwado_override' | 'farmer_reported'
    # Present when unit_cost_usd was converted from a non-USD source
    # (e.g. agri-venture-v2's KES-priced economics.json) -- never
    # required, since a farmer-reported USD price has no conversion at
    # all.
    source_currency_original: Optional[str] = None
    source_amount_original: Optional[float] = None
    fx_rate_used: Optional[float] = None
    fx_rate_date: Optional[date] = None
    fx_rate_source: Optional[str] = None


class InputRequirementOverride(BaseModel):
    """
    Overriding an existing line item's cost -- never a silent
    replacement. baseline_unit_cost_usd (the pre-override figure) is
    preserved automatically by the endpoint below, not something the
    caller sets.
    """
    unit_cost_usd: float
    override_reason: str
    override_by: str


class InputRequirementOut(BaseModel):
    id: str
    season_planting_id: str
    item_name: str
    category: str
    quantity: float
    unit: str
    unit_cost_usd: float
    total_cost_usd: Optional[float] = None
    currency: str
    cost_source: str
    baseline_unit_cost_usd: Optional[float] = None
    source_currency_original: Optional[str] = None
    source_amount_original: Optional[float] = None
    fx_rate_used: Optional[float] = None
    fx_rate_date: Optional[date] = None
    fx_rate_source: Optional[str] = None
    override_reason: Optional[str] = None
    override_by: Optional[str] = None
    override_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.post("/requirements", response_model=InputRequirementOut)
def create_input_requirement(item: InputRequirementIn, db: Session = Depends(get_db)):
    season = db.query(models.SeasonPlanting).filter_by(id=item.season_planting_id).first()
    if not season:
        raise HTTPException(status_code=404, detail="season_planting not found")

    try:
        category = models.InputCategory(item.category)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"category must be one of {[c.value for c in models.InputCategory]}, got '{item.category}'",
        )

    row = models.InputRequirement(
        season_planting_id=item.season_planting_id,
        item_name=item.item_name,
        category=category,
        quantity=item.quantity,
        unit=item.unit,
        unit_cost_usd=item.unit_cost_usd,
        cost_source=item.cost_source,
        baseline_unit_cost_usd=item.unit_cost_usd,  # first-recorded figure, preserved even if later overridden
        source_currency_original=item.source_currency_original,
        source_amount_original=item.source_amount_original,
        fx_rate_used=item.fx_rate_used,
        fx_rate_date=item.fx_rate_date,
        fx_rate_source=item.fx_rate_source,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/requirements", response_model=List[InputRequirementOut])
def list_input_requirements(season_planting_id: str, db: Session = Depends(get_db)):
    return (
        db.query(models.InputRequirement)
        .filter_by(season_planting_id=season_planting_id)
        .order_by(models.InputRequirement.created_at.asc())
        .all()
    )


@router.post("/seed-baseline", response_model=List[InputRequirementOut])
def seed_baseline(season_planting_id: str, db: Session = Depends(get_db)):
    """
    Populates a season's Bill of Quantities from agri-venture-v2's real
    maize economics.json (the one real cost dataset that exists) -- the
    same seed_maize_baseline() app/seed_boq_maize.py's standalone script
    calls, so there is exactly one copy of these real figures, not one
    in a script and a second drifting copy in this route.

    maize-only for now, same honesty as get_baseline()'s
    agriventure_crop_key gate in advisory.py: no other crop has a real
    economics.json in agri-venture-v2 yet, so seeding one would mean
    fabricating costs rather than reading real published figures.
    """
    season = db.query(models.SeasonPlanting).filter_by(id=season_planting_id).first()
    if not season:
        raise HTTPException(status_code=404, detail="season_planting not found")

    existing = db.query(models.InputRequirement).filter_by(season_planting_id=season_planting_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="This season already has input_requirement rows -- seed-baseline only applies to an empty BoQ.")

    crop = db.query(models.CropDictionaryEntry).filter_by(id=season.crop_id).first()
    if not crop or crop.crop_name != "maize":
        raise HTTPException(
            status_code=400,
            detail=f"seed-baseline only supports maize today (this season is '{crop.crop_name if crop else 'unknown'}') -- "
                   "no other crop has a real economics.json in agri-venture-v2 yet.",
        )

    parcel = db.query(models.Parcel).filter_by(id=season.parcel_id).first()
    area_ha = round(float(parcel.area_acres or 1) * ACRES_TO_HECTARES, 3)

    rows = seed_maize_baseline(db, season, area_ha)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


@router.patch("/requirements/{requirement_id}", response_model=InputRequirementOut)
def override_input_requirement(requirement_id: str, override: InputRequirementOverride, db: Session = Depends(get_db)):
    """
    Replaces unit_cost_usd on an existing line item -- e.g. swapping
    agri-venture-v2's KALRO baseline for a locally-observed price.
    baseline_unit_cost_usd is never touched here, so the original figure
    this replaced stays visible regardless of how many times a line item
    is later re-overridden.
    """
    row = db.query(models.InputRequirement).filter_by(id=requirement_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="input_requirement not found")

    row.unit_cost_usd = override.unit_cost_usd
    row.cost_source = "corwado_override"
    row.override_reason = override.override_reason
    row.override_by = override.override_by
    row.override_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


# --------------------------------------------------------------------- #
# input_financing_record -- who paid for one line item
# --------------------------------------------------------------------- #

class InputFinancingIn(BaseModel):
    input_requirement_id: str
    financier_type: str  # farmer | corwado | financial_institution | government | ngo
    financier_name: Optional[str] = None
    amount_usd: float
    financed_at: date
    notes: Optional[str] = None


class InputFinancingOut(BaseModel):
    id: str
    input_requirement_id: str
    financier_type: str
    financier_name: Optional[str] = None
    amount_usd: float
    currency: str
    financed_at: date
    notes: Optional[str] = None
    recorded_at: datetime

    class Config:
        from_attributes = True


@router.post("/financing", response_model=InputFinancingOut)
def create_financing_record(record: InputFinancingIn, db: Session = Depends(get_db)):
    requirement = db.query(models.InputRequirement).filter_by(id=record.input_requirement_id).first()
    if not requirement:
        raise HTTPException(status_code=404, detail="input_requirement not found")

    try:
        financier_type = models.FinancierType(record.financier_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"financier_type must be one of {[f.value for f in models.FinancierType]}, got '{record.financier_type}'",
        )

    row = models.InputFinancingRecord(
        input_requirement_id=record.input_requirement_id,
        financier_type=financier_type,
        financier_name=record.financier_name,
        amount_usd=record.amount_usd,
        financed_at=record.financed_at,
        notes=record.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/financing", response_model=List[InputFinancingOut])
def list_financing_records(
    input_requirement_id: Optional[str] = None,
    season_planting_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Filter by a single line item (input_requirement_id) or every line
    item in a season at once (season_planting_id, joined through
    input_requirement) -- the latter is what a "how was this season's
    BoQ actually funded" view needs.
    """
    if not input_requirement_id and not season_planting_id:
        raise HTTPException(status_code=400, detail="Provide input_requirement_id or season_planting_id")

    q = db.query(models.InputFinancingRecord)
    if input_requirement_id:
        q = q.filter(models.InputFinancingRecord.input_requirement_id == input_requirement_id)
    if season_planting_id:
        q = q.join(
            models.InputRequirement,
            models.InputFinancingRecord.input_requirement_id == models.InputRequirement.id,
        ).filter(models.InputRequirement.season_planting_id == season_planting_id)

    return q.order_by(models.InputFinancingRecord.financed_at.asc()).all()
