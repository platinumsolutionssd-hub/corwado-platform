"""
Core engine test — runs every fixture through the engine with a MINIMAL INLINE
ruleset (not the EUDR ruleset, which comes at the next stage; not the
mock-second-ruleset seam test either). Asserts the exact findings each fixture
should produce. Print-based, exits non-zero on any failure.

Run (cwd = repo root, shapely + pyproj installed):
    python farmtrace/validator/tests/test_core.py
"""
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from farmtrace.validator.core.engine import validate
from farmtrace.validator.core.models import FileType, Severity
from farmtrace.validator.core.ruleset import Applies, GeometryDisposition, PropertySpec, RuleSet

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def inline_ruleset() -> RuleSet:
    """EUDR-shaped parameters, inlined for the core test only."""
    return RuleSet(
        name="test-inline",
        cutoff_date=date(2020, 12, 31),
        min_precision_decimals=6,
        excess_precision_decimals=7,
        polygon_threshold_ha=4.0,
        default_point_area_ha=4.0,
        allowed_geometries={
            "Point": GeometryDisposition.ALLOWED, "MultiPoint": GeometryDisposition.ALLOWED,
            "Polygon": GeometryDisposition.ALLOWED, "MultiPolygon": GeometryDisposition.ALLOWED,
            "LineString": GeometryDisposition.REJECTED, "MultiLineString": GeometryDisposition.REJECTED,
            "GeometryCollection": GeometryDisposition.DISCOURAGED,
        },
        required_properties=(
            PropertySpec("ProducerName", (str,), True, Applies.ALL),
            PropertySpec("ProducerCountry", (str,), True, Applies.ALL),
            PropertySpec("ProductionPlace", (str,), False, Applies.ALL),
            PropertySpec("Area", (int, float, Decimal), True, Applies.POINT),
        ),
        country_property="ProducerCountry",
        area_property="Area",
        country_code_standard="ISO 3166-1 alpha-2",
        iso2_codes=frozenset({"KE", "UG", "TZ", "ET", "RW", "SS", "FJ", "GH", "CI"}),
        iso3_to_iso2={"KEN": "KE", "UGA": "UG", "TZA": "TZ", "ETH": "ET", "RWA": "RW", "SSD": "SS"},
        country_bboxes={"KE": (33.9, -4.7, 41.9, 5.5)},
        max_payload_mb=25.0, payload_warn_mb=20.0,
        max_plots=10000, plots_warn=8000,
        file_types=("I", "II"),
        overlap_sliver_pct=0.5,
        area_divergence_pct=25.0,
    )


RS = inline_ruleset()
FAIL = 0


def report(name, mode=FileType.TYPE_I):
    return validate(os.path.join(FIX, name), RS, mode)


def check(label, cond, detail=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAIL = 1


print("=" * 72)
# 1. clean files -> zero findings
r = report("valid_type1.geojson")
check("valid_type1 -> 0 findings", len(r.findings) == 0 and r.verdict == "PASS",
      f"{len(r.findings)} findings: {[f.code for f in r.findings]}")

r = report("valid_type2.geojson", FileType.TYPE_II)
check("valid_type2 (Type II) -> 0 findings", len(r.findings) == 0,
      f"{len(r.findings)} findings: {[f.code for f in r.findings]}")

r = report("kenyan_smallholder_roster.geojson")
check("roster -> 0 findings", len(r.findings) == 0,
      f"{len(r.findings)} findings: {[f.code for f in r.findings]}")

# 2. broken_seeded -> exactly 8, one per feature, correct codes
r = report("broken_seeded.geojson")
expected = {
    0: "PROP_CASING_MISMATCH", 1: "PROP_COUNTRY_IS_ISO3", 2: "PROP_AREA_NOT_NUMBER",
    3: "GEOM_RING_NOT_CLOSED", 4: "GEOM_SELF_INTERSECTION", 5: "GEOM_TYPE_REJECTED",
    6: "GEOM_COORD_OUT_OF_RANGE", 7: "GEOM_COORDS_LIKELY_SWAPPED",
}
by_idx = {}
for f in r.findings:
    by_idx.setdefault(f.feature_ref.index, []).append(f.code)
check("broken_seeded -> exactly 8 findings", len(r.findings) == 8, f"{len(r.findings)}")
for idx, code in expected.items():
    got = by_idx.get(idx, [])
    check(f"  idx {idx} -> {code} (only)", got == [code], f"{got}")
# idx7 swap must be ERROR tier
sev7 = next((f.severity for f in r.findings if f.feature_ref.index == 7), None)
check("  idx 7 swap severity = ERROR (un-swap lands in KE)", sev7 is Severity.ERROR, str(sev7))

# 3. edges
r = report("edge_empty.geojson")
check("edge_empty -> FILE_EMPTY_COLLECTION", [f.code for f in r.findings] == ["FILE_EMPTY_COLLECTION"],
      f"{[f.code for f in r.findings]}")

r = report("edge_null_geometry.geojson")
check("edge_null_geometry -> GEOM_NULL", [f.code for f in r.findings] == ["GEOM_NULL"],
      f"{[f.code for f in r.findings]}")

r = report("edge_antimeridian.geojson")
codes_am = [f.code for f in r.findings]
check("edge_antimeridian -> GEOM_ANTIMERIDIAN, no ERROR, no crash",
      "GEOM_ANTIMERIDIAN" in codes_am and r.errors == 0, f"{codes_am}")

r = report("edge_precision_exact.geojson")
check("edge_precision_exact -> 0 findings (6dp must not warn)", len(r.findings) == 0,
      f"{[f.code for f in r.findings]}")

# 4. two-tier swap
r = report("swap_tiers.geojson")
sevs = {f.feature_ref.index: f.severity for f in r.findings if f.code == "GEOM_COORDS_LIKELY_SWAPPED"}
check("swap_tiers -> 2 swap findings", len(r.findings) == 2 and len(sevs) == 2, f"{[f.code for f in r.findings]}")
check("  feature 0 = ERROR (un-swap in KE)", sevs.get(0) is Severity.ERROR, str(sevs.get(0)))
check("  feature 1 = WARNING (un-swap still outside KE)", sevs.get(1) is Severity.WARNING, str(sevs.get(1)))

# 5. machine output shape sanity
r = report("broken_seeded.geojson")
d = r.to_dict()
check("machine output has summary + findings + verdict FAIL",
      d["summary"]["verdict"] == "FAIL" and d["summary"]["errors"] >= 1 and len(d["findings"]) == 8)

print("=" * 72)
print("ALL CORE TESTS PASS" if not FAIL else ">>> SOME CORE TESTS FAILED")
sys.exit(FAIL)
