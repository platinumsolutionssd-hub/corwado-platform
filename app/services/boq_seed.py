"""
Shared Bill of Quantities seeding logic for maize, from agri-venture-v2's
real economics.json -- used by BOTH app/seed_boq_maize.py (standalone
demo script) and POST /api/inputs/seed-baseline (the real endpoint), so
the real cost figures/FX rate live in exactly one place, never
duplicated between a script and a route.

See app/seed_boq_maize.py's original docstring for why this reads real
published figures once here rather than calling agri-venture-v2 live:
no endpoint there exposes the itemized costs block, only the aggregate
total via /analyze's financial.total_cost_kes_per_ha.
"""
from datetime import date

from sqlalchemy.orm import Session

from app import models

# Real values from agri-venture-v2/backend/crops/maize/economics.json,
# read directly 2026-07-12. unit is genuinely "KES_per_ha_per_cycle" per
# that file's own costs.unit field.
ECONOMICS_JSON_COSTS_KES_PER_HA = {
    "seed": 8000, "fertilizer": 22000, "land_prep": 9000,
    "planting_labour": 5000, "weeding": 8000, "pest_control": 4000,
    "harvest_labour": 7000, "transport": 5000,
}
ITEM_CATEGORY = {
    "seed": "seed", "fertilizer": "fertilizer", "pest_control": "pesticide",
    "land_prep": "labour", "planting_labour": "labour", "weeding": "labour",
    "harvest_labour": "labour", "transport": "other",
}
ITEM_LABEL = {
    "seed": "Seed", "fertilizer": "Fertilizer", "land_prep": "Land preparation",
    "planting_labour": "Planting labour", "weeding": "Weeding",
    "pest_control": "Pest control", "harvest_labour": "Harvest labour",
    "transport": "Transport",
}

# Real, dated, cited rate -- NOT invented. Wise mid-market USD/KES,
# retrieved 2026-07-12: https://wise.com/us/currency-converter/usd-to-kes-rate
# Mid-market rates move daily; re-confirm before relying on this for a
# real financial decision. Every row this produces carries this exact
# rate/date/source so the conversion is auditable and correctable later,
# never silently baked in (see db/schema.sql migration note).
FX_RATE_KES_PER_USD = 129.19
FX_RATE_DATE = date(2026, 7, 12)
FX_RATE_SOURCE = "Wise mid-market rate, https://wise.com/us/currency-converter/usd-to-kes-rate, retrieved 2026-07-12"

ACRES_TO_HECTARES = 0.404686


def seed_maize_baseline(db: Session, season: models.SeasonPlanting, area_ha: float) -> list[models.InputRequirement]:
    """
    Creates the 8 real economics.json-derived input_requirement rows for
    one season_planting. Quantity is honestly the parcel's real area in
    hectares (these are per-hectare bundles in the source data, not
    itemized physical quantities -- no "kg of DAP" exists upstream to
    quote), not a fabricated physical unit count.
    """
    rows = []
    for key, kes_per_ha in ECONOMICS_JSON_COSTS_KES_PER_HA.items():
        unit_cost_usd = round(kes_per_ha / FX_RATE_KES_PER_USD, 2)
        row = models.InputRequirement(
            season_planting_id=season.id,
            organization_id=season.organization_id,  # child inherits parent season's org (== caller's current_org)
            item_name=f"{ITEM_LABEL[key]} (KALRO/Farmers Trend baseline)",
            category=models.InputCategory(ITEM_CATEGORY[key]),
            quantity=area_ha,
            unit="ha",
            unit_cost_usd=unit_cost_usd,
            cost_source="agriventure_kalro_baseline",
            baseline_unit_cost_usd=unit_cost_usd,
            source_currency_original="KES",
            source_amount_original=kes_per_ha,
            fx_rate_used=FX_RATE_KES_PER_USD,
            fx_rate_date=FX_RATE_DATE,
            fx_rate_source=FX_RATE_SOURCE,
        )
        db.add(row)
        rows.append(row)
    return rows
