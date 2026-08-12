"""
EUDR ruleset test + the mock-second-ruleset SEAM test (a hard acceptance
criterion): a different rule set, exercised purely through configuration, changes
validation behaviour with ZERO core-code changes.

Run (cwd = repo root):
    python farmtrace/validator/tests/test_eudr.py
"""
import os
import sys
from dataclasses import replace
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from farmtrace.validator.core.engine import validate
from farmtrace.validator.core.models import FileType, Severity
from farmtrace.validator.rulesets.eudr import eudr_ruleset

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
EUDR = eudr_ruleset()
FAIL = 0


def rep(name, mode=FileType.TYPE_I):
    return validate(os.path.join(FIX, name), EUDR, mode)


def check(label, cond, detail=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAIL = 1


print("=" * 72)
print("Part 1 — the fixtures validate correctly under the real EUDR ruleset")
r = rep("valid_type1.geojson")
check("valid_type1 -> 0 findings", len(r.findings) == 0, str([f.code for f in r.findings]))
r = rep("valid_type2.geojson", FileType.TYPE_II)
check("valid_type2 (Type II) -> 0 findings", len(r.findings) == 0, str([f.code for f in r.findings]))
r = rep("kenyan_smallholder_roster.geojson")
check("roster -> 0 findings", len(r.findings) == 0, str([f.code for f in r.findings]))

r = rep("broken_seeded.geojson")
expected = {0: "PROP_CASING_MISMATCH", 1: "PROP_COUNTRY_IS_ISO3", 2: "PROP_AREA_NOT_NUMBER",
            3: "GEOM_RING_NOT_CLOSED", 4: "GEOM_SELF_INTERSECTION", 5: "GEOM_TYPE_REJECTED",
            6: "GEOM_COORD_OUT_OF_RANGE", 7: "GEOM_COORDS_LIKELY_SWAPPED"}
by_idx = {}
for f in r.findings:
    by_idx.setdefault(f.feature_ref.index, []).append((f.code, f.severity))
check("broken_seeded -> exactly 8", len(r.findings) == 8, str(len(r.findings)))
for idx, code in expected.items():
    got = by_idx.get(idx, [])
    check(f"  idx {idx} -> {code}", [c for c, s in got] == [code], str(got))
check("  idx 7 swap = ERROR", by_idx.get(7, [(None, None)])[0][1] is Severity.ERROR)

r = rep("swap_tiers.geojson")
sev = {f.feature_ref.index: f.severity for f in r.findings}
check("swap_tiers -> feature0 ERROR, feature1 WARNING",
      len(r.findings) == 2 and sev.get(0) is Severity.ERROR and sev.get(1) is Severity.WARNING,
      str([(f.feature_ref.index, f.severity.value) for f in r.findings]))
for name, want in [("edge_empty.geojson", "FILE_EMPTY_COLLECTION"),
                   ("edge_null_geometry.geojson", "GEOM_NULL")]:
    r = rep(name)
    check(f"{name} -> {want}", [f.code for f in r.findings] == [want], str([f.code for f in r.findings]))
r = rep("edge_precision_exact.geojson")
check("edge_precision_exact -> 0 findings (6dp ok under EUDR min 6)", len(r.findings) == 0, str([f.code for f in r.findings]))

print("Part 2 — SEAM: a second ruleset via config alone changes the verdict, no core change")
# scheme-b: same core, same fixtures, only PARAMETERS differ (frozen-dataclass replace).
scheme_b = replace(EUDR, name="scheme-b", polygon_threshold_ha=2.0,
                   min_precision_decimals=4, cutoff_date=date(2021, 1, 1))
scheme_b.validate()

# One point, Area 3.0 ha, valid 6-decimal KE coords, all properties present.
point_3ha = {"type": "FeatureCollection", "features": [{
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [37.123456, -0.654321]},
    "properties": {"ProducerName": "Test", "ProducerCountry": "KE",
                   "ProductionPlace": "Nyeri", "Area": 3.0},
}]}
codes_eudr = [f.code for f in validate(point_3ha, EUDR).findings]
codes_b = [f.code for f in validate(point_3ha, scheme_b).findings]
check("EUDR (threshold 4.0 ha): point Area 3.0 -> no threshold finding",
      "THRESH_POINT_AREA_TOO_LARGE" not in codes_eudr, str(codes_eudr))
check("scheme-b (threshold 2.0 ha): SAME point -> THRESH_POINT_AREA_TOO_LARGE",
      "THRESH_POINT_AREA_TOO_LARGE" in codes_b, str(codes_b))
check("=> the seam is real: same core + same input, different ruleset -> different result",
      codes_eudr != codes_b)
check("scheme-b differs from EUDR only in config (name/threshold/precision/cutoff)",
      scheme_b.polygon_threshold_ha == 2.0 and EUDR.polygon_threshold_ha == 4.0
      and scheme_b.min_precision_decimals == 4 and EUDR.min_precision_decimals == 6)

print("=" * 72)
print("ALL EUDR TESTS PASS" if not FAIL else ">>> SOME EUDR TESTS FAILED")
sys.exit(FAIL)
