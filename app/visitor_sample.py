"""
Static sample-report payload for visitor mode 2A. Pure data — imports
nothing from app.database or app.models (enforced by test_visitor_no_db.py).
"""
SAMPLE_REPORT = {
    "mode": "sample",
    "parcel_label": "Demo parcel — Kibiko, Kajiado (illustrative)",
    "crop": "maize",
    "overall_score": 0.923,
    "overall_classification": "S1",
    "note": "Static illustrative report shown to visitors. Not computed live, "
            "not tied to any organization, never stored.",
}
