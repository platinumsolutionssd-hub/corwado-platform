"""
Deterministic builder for the Geolocation Validator test fixtures.

This is NOT the validator. It is a fixture-authoring tool: it constructs each
sample GeoJSON as a Python structure, uses shapely/pyproj to VERIFY the fixture
actually encodes the intended property (a "valid" polygon really is >= 4 ha; a
"bow-tie" really self-intersects; a "swapped" point really falls outside Kenya
and back inside when un-swapped), then writes the .geojson files committed
alongside it.

Deterministic by construction: no randomness, no clock. Re-running reproduces
byte-identical fixtures.

Run (cwd = repo root, shapely + pyproj installed):
    python farmtrace/validator/tests/fixtures/_build_fixtures.py
"""
import json
import os

from shapely.geometry import shape
from pyproj import Geod

HERE = os.path.dirname(os.path.abspath(__file__))
GEOD = Geod(ellps="WGS84")

# Approximate Kenya bounding box, used ONLY to verify fixture coordinates fall
# where intended. The real, source-cited bbox table lives in the ruleset (built
# in a later stage). Bounds ~ mainland Kenya. lon[E], lat[N].
KE_BBOX = (33.9, -4.7, 41.9, 5.5)  # (min_lon, min_lat, max_lon, max_lat)


def in_bbox(lon, lat, bbox=KE_BBOX):
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def geodesic_area_ha(polygon_coords):
    """Absolute geodesic area (hectares) of a polygon exterior ring."""
    lons = [c[0] for c in polygon_coords]
    lats = [c[1] for c in polygon_coords]
    area_m2, _ = GEOD.polygon_area_perimeter(lons, lats)
    return abs(area_m2) / 10_000.0


def feat(geometry, **props):
    return {"type": "Feature", "geometry": geometry, "properties": props}


def point(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


def fc(features):
    return {"type": "FeatureCollection", "features": features}


def d6(v, axis):
    # Give coordinates genuine 6-decimal precision with a non-zero 6th digit.
    # Round literals like 37.150000 collapse to "37.15" in JSON (under-precise);
    # real GPS fixes carry ~6 decimals. Deterministic; the sub-metre shift
    # preserves every area / self-intersection / in-country property asserted below.
    bump = 0.000041 if axis == 0 else 0.000073
    return round(v + bump, 6)


def _precise(node):
    """Recursively apply d6 to every [lon, lat] position in a GeoJSON structure."""
    if isinstance(node, list):
        if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
            return [d6(node[0], 0), d6(node[1], 1)] + list(node[2:])
        return [_precise(x) for x in node]
    if isinstance(node, dict):
        return {k: _precise(v) for k, v in node.items()}
    return node


def write(name, obj):
    obj = _precise(obj)
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


checks = []  # (label, ok, detail)


def verify(label, ok, detail=""):
    checks.append((label, bool(ok), detail))


# --------------------------------------------------------------------------- #
# 1. valid_type1.geojson — a clean Type I file; MUST pass with zero findings.
# --------------------------------------------------------------------------- #
vt1_poly_ring = [
    [37.100000, -0.700000],
    [37.102100, -0.700000],
    [37.102100, -0.702100],
    [37.100000, -0.702100],
    [37.100000, -0.700000],
]
valid_type1 = fc([
    # point, 0.8 ha, all four properties, Murang'a
    feat(point(37.150000, -0.720000),
         ProducerName="Alice Wanjiku", ProducerCountry="KE",
         ProductionPlace="Murang'a", Area=0.8),
    # polygon, >= 4 ha, closed, valid, NO Area
    feat({"type": "Polygon", "coordinates": [vt1_poly_ring]},
         ProducerName="Boniface Kamau", ProducerCountry="KE",
         ProductionPlace="Nyeri"),
    # multipoint carrying Area
    feat({"type": "MultiPoint", "coordinates": [[37.155000, -0.725000],
                                                [37.156000, -0.726000]]},
         ProducerName="Catherine Njeri", ProducerCountry="KE",
         ProductionPlace="Murang'a", Area=0.3),
])
_vt1_area = geodesic_area_ha(vt1_poly_ring)
verify("valid_type1 polygon >= 4 ha", _vt1_area >= 4.0, f"{_vt1_area:.3f} ha")
verify("valid_type1 polygon geometrically valid", shape(valid_type1["features"][1]["geometry"]).is_valid)
verify("valid_type1 point in KE", in_bbox(37.150000, -0.720000))
write("valid_type1.geojson", valid_type1)

# --------------------------------------------------------------------------- #
# 2. valid_type2.geojson — multi-producer; ProducerCountry on EVERY feature.
# --------------------------------------------------------------------------- #
valid_type2 = fc([
    feat(point(36.950000, -0.420000),
         ProducerName="Daniel Mwangi", ProducerCountry="KE",
         ProductionPlace="Nyeri", Area=0.25),
    feat(point(37.010000, -0.560000),
         ProducerName="Esther Achieng", ProducerCountry="KE",
         ProductionPlace="Karatina", Area=0.4),
    feat(point(37.080000, -0.640000),
         ProducerName="Francis Otieno", ProducerCountry="KE",
         ProductionPlace="Murang'a", Area=0.15),
])
verify("valid_type2 all features carry ProducerCountry",
       all("ProducerCountry" in f["properties"] for f in valid_type2["features"]))
write("valid_type2.geojson", valid_type2)

# --------------------------------------------------------------------------- #
# 3. broken_seeded.geojson — EXACTLY eight features, one seeded fault each,
#    everything else about each feature clean (so no false positives).
#    Index -> fault mapping is asserted below and documented in the README.
# --------------------------------------------------------------------------- #
# idx3 unclosed ring: 4 distinct points, first != last (passes >=4, fails closed)
unclosed_ring = [
    [37.100000, -0.700000],
    [37.101500, -0.700000],
    [37.101500, -0.701500],
    [37.100000, -0.701500],
]
# idx4 bow-tie self-intersection (closed, >=4 points, single ring, no holes)
# placed well away from idx3's polygon so the two broken plots don't overlap
bowtie_ring = [
    [37.300000, -0.900000],
    [37.301000, -0.901000],
    [37.301000, -0.900000],
    [37.300000, -0.901000],
    [37.300000, -0.900000],
]
broken_seeded = fc([
    # idx0 — property casing: "producername" instead of "ProducerName"
    feat(point(37.150000, -0.720000),
         **{"producername": "Grace Wambui", "ProducerCountry": "KE",
            "ProductionPlace": "Murang'a", "Area": 0.5}),
    # idx1 — ISO3 country code "KEN" (valid ISO3, should be ISO2 "KE")
    feat(point(37.010000, -0.560000),
         ProducerName="Henry Kiprop", ProducerCountry="KEN",
         ProductionPlace="Karatina", Area=0.3),
    # idx2 — string-typed Area "1.1"
    feat(point(36.950000, -0.420000),
         ProducerName="Irene Chebet", ProducerCountry="KE",
         ProductionPlace="Nyeri", Area="1.1"),
    # idx3 — unclosed polygon ring
    feat({"type": "Polygon", "coordinates": [unclosed_ring]},
         ProducerName="James Mutua", ProducerCountry="KE",
         ProductionPlace="Nyeri"),
    # idx4 — self-intersecting bow-tie polygon
    feat({"type": "Polygon", "coordinates": [bowtie_ring]},
         ProducerName="Kevin Omondi", ProducerCountry="KE",
         ProductionPlace="Murang'a"),
    # idx5 — LineString geometry (rejected type)
    feat({"type": "LineString", "coordinates": [[37.100000, -0.700000],
                                                [37.101000, -0.701000]]},
         ProducerName="Lucy Njoki", ProducerCountry="KE",
         ProductionPlace="Murang'a"),
    # idx6 — longitude out of range (> 180)
    feat(point(210.500000, -0.700000),
         ProducerName="Moses Barasa", ProducerCountry="KE",
         ProductionPlace="Nyeri", Area=0.2),
    # idx7 — swapped lon/lat: KE producer, coords outside KE, un-swap lands in KE
    feat(point(-0.420000, 36.950000),
         ProducerName="Nancy Auma", ProducerCountry="KE",
         ProductionPlace="Nyeri", Area=0.2),
])
# verify the seeded faults are really what we claim
verify("broken_seeded has exactly 8 features", len(broken_seeded["features"]) == 8)
verify("idx0 has lowercase producername, no ProducerName",
       "producername" in broken_seeded["features"][0]["properties"]
       and "ProducerName" not in broken_seeded["features"][0]["properties"])
verify("idx1 ProducerCountry is ISO3 'KEN'", broken_seeded["features"][1]["properties"]["ProducerCountry"] == "KEN")
verify("idx2 Area is a string", isinstance(broken_seeded["features"][2]["properties"]["Area"], str))
verify("idx3 ring is NOT closed", unclosed_ring[0] != unclosed_ring[-1] and len(unclosed_ring) >= 4)
verify("idx4 bow-tie really self-intersects (shapely invalid)",
       not shape({"type": "Polygon", "coordinates": [bowtie_ring]}).is_valid)
verify("idx5 is a LineString", broken_seeded["features"][5]["geometry"]["type"] == "LineString")
verify("idx6 longitude 210.5 is out of range", abs(210.5) > 180)
verify("idx7 stored coord outside KE", not in_bbox(-0.420000, 36.950000))
verify("idx7 un-swapped coord inside KE (=> ERROR tier)", in_bbox(36.950000, -0.420000))
write("broken_seeded.geojson", broken_seeded)

# --------------------------------------------------------------------------- #
# 4. kenyan_smallholder_roster.geojson — ~30 features, all valid. Deterministic.
#    Predominantly points 0.08-0.5 ha + a few small polygons. Murang'a/Nyeri.
# --------------------------------------------------------------------------- #
NAMES = ["Wanjiku", "Kamau", "Njeri", "Mwangi", "Achieng", "Otieno", "Wambui",
         "Kiprop", "Chebet", "Mutua", "Omondi", "Njoki", "Barasa", "Auma",
         "Kariuki", "Nyambura", "Gitau", "Waithera", "Macharia", "Wangari",
         "Kimani", "Muthoni", "Ndung'u", "Wairimu", "Githinji", "Nyokabi",
         "Maina", "Wanjiru"]
PLACES = ["Murang'a", "Nyeri", "Karatina", "Kangema", "Mathira"]
roster = []
base_lon, base_lat = 36.900000, -0.450000
for i in range(28):  # 28 points
    lon = round(base_lon + (i % 7) * 0.012000 + (i // 7) * 0.003000, 6)
    lat = round(base_lat - (i % 5) * 0.011000 - (i // 5) * 0.002000, 6)
    area = round(0.08 + (i % 6) * 0.070000, 2)  # 0.08 .. 0.43 ha
    roster.append(feat(point(lon, lat),
                       ProducerName=f"{NAMES[i % len(NAMES)]} {NAMES[(i * 3 + 1) % len(NAMES)]}",
                       ProducerCountry="KE", ProductionPlace=PLACES[i % len(PLACES)], Area=area))
for j in range(3):  # 3 small polygons (no Area)
    lon = round(37.050000 + j * 0.010000, 6)
    lat = round(-0.500000 - j * 0.010000, 6)
    d = 0.001200
    ring = [[lon, lat], [lon + d, lat], [lon + d, lat - d], [lon, lat - d], [lon, lat]]
    roster.append(feat({"type": "Polygon", "coordinates": [ring]},
                       ProducerName=f"{NAMES[(j * 5) % len(NAMES)]} Cooperative Plot {j + 1}",
                       ProducerCountry="KE", ProductionPlace=PLACES[j % len(PLACES)]))
roster_fc = fc(roster)
# verify every roster coordinate is inside KE and every geometry valid
_all_in = True
for f in roster:
    g = f["geometry"]
    coords = [g["coordinates"]] if g["type"] == "Point" else g["coordinates"][0]
    for lon, lat in coords:
        if not in_bbox(lon, lat):
            _all_in = False
verify("roster has ~30 features", 28 <= len(roster) <= 34, f"{len(roster)} features")
verify("roster all coordinates inside KE", _all_in)
verify("roster all geometries valid", all(shape(f["geometry"]).is_valid for f in roster))
write("kenyan_smallholder_roster.geojson", roster_fc)

# --------------------------------------------------------------------------- #
# 5. Edge fixtures.
# --------------------------------------------------------------------------- #
write("edge_empty.geojson", fc([]))

write("edge_null_geometry.geojson", fc([
    feat(None, ProducerName="Oscar Kiptoo", ProducerCountry="KE",
         ProductionPlace="Nyeri", Area=0.2),
]))

# antimeridian-crossing polygon (Fiji vicinity). Behavior documented, must not crash.
# Fiji ("FJ") is intentionally NOT in the v1 bbox table -> swap heuristic skipped.
antimeridian_ring = [
    [179.900000, -16.700000],
    [-179.900000, -16.700000],
    [-179.900000, -16.900000],
    [179.900000, -16.900000],
    [179.900000, -16.700000],
]
write("edge_antimeridian.geojson", fc([
    feat({"type": "Polygon", "coordinates": [antimeridian_ring]},
         ProducerName="Pacific Grower", ProducerCountry="FJ",
         ProductionPlace="Vanua Levu"),
]))

# 6-decimal-exact coordinates: MUST pass, MUST NOT raise a precision warning.
write("edge_precision_exact.geojson", fc([
    feat(point(37.123456, -0.654321),
         ProducerName="Quentin Mbeki", ProducerCountry="KE",
         ProductionPlace="Murang'a", Area=0.3),
]))

# --------------------------------------------------------------------------- #
# 6. swap_tiers.geojson — exercises BOTH tiers of the swap heuristic (decision 3).
#    A: out-of-KE, un-swap lands IN KE          -> ERROR   ("almost certainly swapped")
#    B: out-of-KE, un-swap still OUT of KE       -> WARNING ("possibly swapped")
# --------------------------------------------------------------------------- #
swap_tiers = fc([
    feat(point(-0.420000, 36.950000),      # un-swap -> (36.95, -0.42) in KE
         ProducerName="Rita Nasimiyu", ProducerCountry="KE",
         ProductionPlace="Nyeri", Area=0.2),
    feat(point(10.000000, 50.000000),      # un-swap -> (50.0, 10.0) still out of KE
         ProducerName="Samuel Rotich", ProducerCountry="KE",
         ProductionPlace="Nyeri", Area=0.2),
])
verify("swap A stored outside KE", not in_bbox(-0.420000, 36.950000))
verify("swap A un-swapped inside KE (ERROR tier)", in_bbox(36.950000, -0.420000))
verify("swap B stored outside KE", not in_bbox(10.000000, 50.000000))
verify("swap B un-swapped STILL outside KE (WARNING tier)", not in_bbox(50.000000, 10.000000))
write("swap_tiers.geojson", swap_tiers)

# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
print("=" * 70)
allok = True
for label, ok, detail in checks:
    allok = allok and ok
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))
print("=" * 70)
print("ALL FIXTURE INVARIANTS HOLD" if allok else ">>> SOME INVARIANTS FAILED <<<")
