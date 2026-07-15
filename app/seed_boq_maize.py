"""
Standalone demo runner for seeding a Bill of Quantities from
agri-venture-v2's real maize economics.json. The actual cost figures/FX
rate logic lives in app/services/boq_seed.py (shared with
POST /api/inputs/seed-baseline, so a script and a route never carry two
copies of the same real data).

Run after the season_planting/input_requirement/input_financing_record
migration is applied and at least one parcel+maize crop_dictionary_entry
exist:
    python -m app.seed_boq_maize --parcel-id <uuid>
(defaults to the first parcel found if --parcel-id is omitted)
"""
import argparse
from datetime import date

from app.database import SessionLocal
from app import models
from app.services.boq_seed import seed_maize_baseline, ACRES_TO_HECTARES


def run(parcel_id: str | None):
    db = SessionLocal()
    try:
        parcel = (
            db.query(models.Parcel).filter_by(id=parcel_id).first()
            if parcel_id else db.query(models.Parcel).first()
        )
        if not parcel:
            print("No parcel found -- register one first.")
            return

        maize = db.query(models.CropDictionaryEntry).filter_by(crop_name="maize").first()
        if not maize:
            print("No 'maize' crop_dictionary_entry found -- run app.seed first.")
            return

        area_ha = round(float(parcel.area_acres or 1) * ACRES_TO_HECTARES, 3)

        season = models.SeasonPlanting(
            parcel_id=parcel.id,
            crop_id=maize.id,
            sowing_date=date.today(),
            season_label="2026 Wet Season",
        )
        db.add(season)
        db.flush()
        print(f"Seeded season_planting {season.id} for parcel {parcel.id} ({area_ha} ha)")

        rows = seed_maize_baseline(db, season, area_ha)
        db.commit()
        print(f"Seeded {len(rows)} input_requirement rows.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--parcel-id", default=None)
    args = parser.parse_args()
    run(args.parcel_id)
