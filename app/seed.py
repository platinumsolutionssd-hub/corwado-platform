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
CROPS = ["sorghum", "groundnut", "sesame", "cassava", "moringa"]
PAYAMS = ["Wau Payam", "Bagari Payam", "Bazia Payam", "Farajallah Payam"]


def run():
    db = SessionLocal()
    try:
        crop_rows = {}
        for name in CROPS:
            existing = db.query(models.CropDictionaryEntry).filter_by(crop_name=name).first()
            if existing:
                crop_rows[name] = existing
                continue
            row = models.CropDictionaryEntry(
                crop_name=name,
                scoring_params={"note": "placeholder MCE weights — replace with Kibiko model params"},
                typical_season="2026 wet season",
            )
            db.add(row)
            db.flush()
            crop_rows[name] = row

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
        station = models.RadioStation(
            name="Wau FM",
            frequency="97.5 FM",
            payam_coverage=["Wau Payam", "Bagari Payam"],
            language="juba_arabic",
        )
        db.add(station)
        db.flush()
        db.add(models.RadioBroadcastSlot(
            radio_station_id=station.id,
            day_of_week="wed",
            time_slot="18:00-18:15",
            program_name="CORWADO Farmers' Hour",
        ))
        print(f"Seeded radio station: {station.name} covering {station.payam_coverage}")

        demo_stewards = [
            ("Achol Deng Malual", "smallholder_farmer", "female", False, False, "Wau Payam", "radio"),
            ("Santino Garang", "cooperative_member", "male", True, False, "Bagari Payam", "ussd"),
            ("Nyibol Ater Kuol", "smallholder_farmer", "female", True, True, "Bazia Payam", "ivr"),
            ("Mayen Akec Chol", "cooperative_member", "male", False, False, "Farajallah Payam", "sms"),
            ("Adut Malith", "smallholder_farmer", "female", False, False, "Wau Payam", "whatsapp"),
        ]

        for name, role, gender, youth, disability, payam, channel in demo_stewards:
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
