"""
Stage 2 OFFLINE unit test — fact assembly + geometry, via the FakeProvider seam.
No Earth Engine, no network. Tests the LOGIC; the live GEE data integration is
verified separately by run_facts_live.py against the real fixtures.

Run (cwd = repo root):
    python farmtrace/deforestation/tests/test_facts.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from farmtrace.deforestation.core.facts import build_facts
from farmtrace.deforestation.core.geometry import circle_footprint, footprint_for, geodesic_area_ha
from farmtrace.deforestation.core.provider import FakeProvider, RawReduction

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
FAIL = 0


def check(label, cond, detail=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAIL = 1


def feature(fc, plot_id):
    for f in fc["features"]:
        if f["properties"]["plot_id"] == plot_id:
            return f
    raise KeyError(plot_id)


print("=" * 72)
print("Part 1 — geometry: geodesic area + point circular buffer")

fc = json.load(open(os.path.join(FIX, "parcels.geojson")))

# each ~133 m square fixture should be ~1.77 ha geodesic
poly, kind = footprint_for(feature(fc, "intact-forest-kakamega")["geometry"], 1.77)
a = geodesic_area_ha(poly)
check("kakamega polygon ~1.77 ha", 1.70 <= a <= 1.84, f"{a:.4f} ha, kind={kind}")

# a circular footprint's OWN area equals the declared Area (n-gon solved, not circumscribed)
circ = circle_footprint(35.48149, -0.56383, 1.0)
ca = geodesic_area_ha(circ)
check("circle_footprint(Area=1.0) ~= 1.0 ha", 0.99 <= ca <= 1.01, f"{ca:.5f} ha")

# point plot dispatches to a point-buffer of the declared Area
pt_feat = feature(fc, "deforestation-post2020-mau-point")
pt_poly, pt_kind = footprint_for(pt_feat["geometry"], pt_feat["properties"]["Area"])
check("point geometry -> point-buffer kind", pt_kind == "point-buffer", pt_kind)
check("point footprint area ~= declared Area 1.0",
      0.99 <= geodesic_area_ha(pt_poly) <= 1.01, f"{geodesic_area_ha(pt_poly):.5f} ha")

# a Point with no Area is an explicit error, not a silent single-pixel guess
try:
    footprint_for({"type": "Point", "coordinates": [35.0, -0.5]}, None)
    check("point without Area raises", False)
except ValueError:
    check("point without Area raises", True)

print("Part 2 — fact assembly via FakeProvider (constructed reductions, no GEE)")

# intact forest: high forest fraction, empty loss history
r_forest = RawReduction(forest_2020_fraction=0.98, loss_area_by_year={}, treecover2000_mean=88.0)
f = build_facts(feature(fc, "intact-forest-kakamega")["geometry"], 1.77,
                FakeProvider(r_forest), identifier="intact-forest-kakamega")
check("intact: forest_2020_fraction carried", f.forest_2020_fraction == 0.98)
check("intact: forest_2020_area = frac*plot_area",
      abs(f.forest_2020_area_ha - 0.98 * f.plot_area_ha) < 1e-9, f"{f.forest_2020_area_ha:.4f}")
check("intact: no loss in any year", f.total_loss_area_ha == 0.0)
check("intact: footprint_kind polygon", f.footprint_kind == "polygon")

# post-2020 clearing: loss in 2024
r_loss = RawReduction(forest_2020_fraction=0.9, loss_area_by_year={2024: 1.2}, treecover2000_mean=90.0)
f2 = build_facts(feature(fc, "deforestation-post2020-mau")["geometry"], 1.77,
                 FakeProvider(r_loss), identifier="deforestation-post2020-mau")
check("clearing: 2024 loss present", f2.loss_area_by_year.get(2024) == 1.2)
check("clearing: total loss = 1.2 ha", f2.total_loss_area_ha == 1.2)

# non-forest: zero forest, zero loss
r_bare = RawReduction(forest_2020_fraction=0.0, loss_area_by_year={}, treecover2000_mean=1.0)
f3 = build_facts(feature(fc, "savanna-cropland-wau")["geometry"], 1.77,
                 FakeProvider(r_bare), identifier="savanna-cropland-wau")
check("savanna: forest fraction 0", f3.forest_2020_fraction == 0.0)
check("savanna: forest area 0", f3.forest_2020_area_ha == 0.0)

# point plot: build_facts computes a point-buffer footprint and tags it
r_pt = RawReduction(forest_2020_fraction=0.95, loss_area_by_year={2023: 0.6}, treecover2000_mean=85.0)
f4 = build_facts(pt_feat["geometry"], pt_feat["properties"]["Area"],
                 FakeProvider(r_pt), identifier="mau-point")
check("point-facts: kind point-buffer", f4.footprint_kind == "point-buffer")
check("point-facts: plot_area ~= 1.0 ha", 0.99 <= f4.plot_area_ha <= 1.01, f"{f4.plot_area_ha:.5f}")
check("point-facts: 2023 loss carried", f4.loss_area_by_year.get(2023) == 0.6)

print("Part 3 — explainability + serialisation contract")
d = f2.to_dict()
check("to_dict is JSON-serialisable", json.dumps(d) is not None)
for key in ("inputs", "equations", "assumptions", "uncertainty", "provenance"):
    check(f"explainability has '{key}'", key in f2.explainability)
check("point footprint radius equation only on point plots",
      "point_footprint_radius_m" in f4.explainability["equations"]
      and "point_footprint_radius_m" not in f2.explainability["equations"])
check("loss years serialise as string keys", all(isinstance(k, str) for k in d["loss_area_by_year"]))

print("=" * 72)
print("ALL FACT-LAYER UNIT TESTS PASS" if not FAIL else ">>> SOME TESTS FAILED")
sys.exit(FAIL)
