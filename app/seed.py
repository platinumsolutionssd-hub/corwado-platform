"""
Seed script — populates a freshly-created database with realistic
Western Bahr el Ghazal demo data, matching the front-end demo's content
so a local run and the Claude-hosted demo tell the same story.

Run after loading db/schema.sql:
    python -m app.seed
"""
from app.database import SessionLocal
from app import models

# Lowercase, matching agri-venture-v2's crops/<name>/ folder convention
# exactly (its own folder names are the source of truth for crop_data,
# since that's the system that owns it -- e.g. crops/moringa/, not
# crops/Moringa/). Found live 2026-07-11: CORWADO's own
# crop_dictionary_entry lookup in get_baseline() is a case-sensitive
# exact match, so a Title Case seed value here silently 404s a request
# for the (correct, agri-venture-v2-normalized) lowercase crop name.
#
# "maize" added here 2026-07-11 -- it already existed live in
# crop_dictionary_entry (added ad hoc while verifying the BiophysicalEngine
# path against the real DB) but was missing from this list, so a fresh
# `python -m app.seed` run would never have created it.
CROPS = ["maize", "sorghum", "groundnut", "sesame", "cassava", "moringa"]

# agri-venture-v2 only has a biology.json for maize and moringa today --
# the rest satisfy "CORWADO tracks this crop" but not "agri-venture-v2 can
# score it". NULL (the default, left unset for crops not in this dict)
# means the latter isn't true yet. See db/schema.sql migration (Day 15)
# and get_baseline()'s gate in app/routers/advisory.py.
AGRIVENTURE_CROP_KEYS = {"maize": "maize", "moringa": "moringa"}

PAYAMS = ["Wau Payam", "Bagari Payam", "Bazia Payam", "Farajallah Payam"]


def run():
    db = SessionLocal()
    try:
        crop_rows = {}
        for name in CROPS:
            agriventure_key = AGRIVENTURE_CROP_KEYS.get(name)
            existing = db.query(models.CropDictionaryEntry).filter_by(crop_name=name).first()
            if existing:
                # Backfill in place: a row created before agriventure_crop_key
                # existed (or seeded by an earlier version of this script)
                # would otherwise sit at NULL forever, since this branch
                # otherwise leaves existing rows untouched.
                if existing.agriventure_crop_key != agriventure_key:
                    existing.agriventure_crop_key = agriventure_key
                crop_rows[name] = existing
                continue
            row = models.CropDictionaryEntry(
                crop_name=name,
                scoring_params={"note": "placeholder MCE weights — replace with Kibiko model params"},
                typical_season="2026 wet season",
                agriventure_crop_key=agriventure_key,
            )
            db.add(row)
            db.flush()
            crop_rows[name] = row

        coop = db.query(models.Cooperative).filter_by(
            name="Wau Women's Agribusiness Cooperative"
        ).first()
        if coop:
            coop.type = "cooperative"
            coop.payam = "Wau Payam"
            coop.county = "Western Bahr el Ghazal"
        else:
            coop = models.Cooperative(
                name="Wau Women's Agribusiness Cooperative",
                type="cooperative",
                payam="Wau Payam",
                county="Western Bahr el Ghazal",
            )
            db.add(coop)
            db.flush()

        # Radio: seed a real station + slot so broadcast_to_payam has
        # something to find, rather than a payam that always 404s.
        station = db.query(models.RadioStation).filter_by(name="Wau FM").first()
        if station:
            station.frequency = "97.5 FM"
            station.payam_coverage = ["Wau Payam", "Bagari Payam"]
            station.language = "juba_arabic"
            print(f"Radio station already seeded, updated: {station.name} covering {station.payam_coverage}")
        else:
            station = models.RadioStation(
                name="Wau FM",
                frequency="97.5 FM",
                payam_coverage=["Wau Payam", "Bagari Payam"],
                language="juba_arabic",
            )
            db.add(station)
            db.flush()
            print(f"Seeded radio station: {station.name} covering {station.payam_coverage}")

        slot = db.query(models.RadioBroadcastSlot).filter_by(
            radio_station_id=station.id, day_of_week="wed", time_slot="18:00-18:15"
        ).first()
        if slot:
            slot.program_name = "CORWADO Farmers' Hour"
        else:
            db.add(models.RadioBroadcastSlot(
                radio_station_id=station.id,
                day_of_week="wed",
                time_slot="18:00-18:15",
                program_name="CORWADO Farmers' Hour",
            ))

        demo_stewards = [
            ("Achol Deng Malual", "smallholder_farmer", "female", False, False, "Wau Payam", "radio"),
            ("Santino Garang", "cooperative_member", "male", True, False, "Bagari Payam", "ussd"),
            ("Nyibol Ater Kuol", "smallholder_farmer", "female", True, True, "Bazia Payam", "ivr"),
            ("Mayen Akec Chol", "cooperative_member", "male", False, False, "Farajallah Payam", "sms"),
            ("Adut Malith", "smallholder_farmer", "female", False, False, "Wau Payam", "whatsapp"),
        ]

        for name, role, gender, youth, disability, payam, channel in demo_stewards:
            existing = db.query(models.LandSteward).filter_by(full_name=name).first()
            if existing:
                existing.role = role
                existing.gender = gender
                existing.is_youth = youth
                existing.has_disability = disability
                existing.preferred_channel = channel
                existing.cooperative_id = coop.id if role == "cooperative_member" else None
                print(f"Steward already seeded, updated: {name} ({payam})")
                continue
            steward = models.LandSteward(
                full_name=name, role=role, gender=gender, is_youth=youth,
                has_disability=disability, preferred_channel=channel,
                cooperative_id=coop.id if role == "cooperative_member" else None,
                registered_by="Demo Seed Script",
                registered_offline=False,
            )
            db.add(steward)
            db.flush()
            print(f"Seeded steward: {name} ({payam})")

        db.commit()
        print("\nSeed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
