# Geolocation Validator — test fixtures

Sample GeoJSON files that are the correctness oracle for the validator. Built
by `_build_fixtures.py` (deterministic; no randomness, no clock — re-running
reproduces byte-identical files). The builder uses shapely/pyproj to *verify*
each fixture encodes what its name claims before writing it; run it to confirm:

```
python farmtrace/validator/tests/fixtures/_build_fixtures.py
```

All coordinates are `[lon, lat]`, 6-decimal, WGS84. "In KE" means within an
approximate mainland-Kenya bounding box used only to place fixture points; the
real source-cited country bboxes live in the ruleset.

| Fixture | Expected outcome |
|---------|------------------|
| `valid_type1.geojson` | **Zero findings** (Type I). Point 0.8 ha + all four properties; polygon 5.428 ha, closed, valid, no Area; MultiPoint with Area. |
| `valid_type2.geojson` | **Zero findings** (Type II). Three producers, `ProducerCountry` on every feature. |
| `broken_seeded.geojson` | Exactly **8 findings, one per feature** — see `broken_seeded.README.md`. No false positives. |
| `kenyan_smallholder_roster.geojson` | **Zero findings.** 31 features (28 points 0.08–0.43 ha + 3 small polygons), all in Murang'a/Nyeri, `ProducerCountry` "KE". Also the future demo file; must run clean in seconds. |
| `edge_empty.geojson` | Empty `FeatureCollection` → `FILE_EMPTY_COLLECTION` (WARNING). No crash. |
| `edge_null_geometry.geojson` | One feature with `geometry: null` → `GEOM_NULL` (ERROR). No crash. |
| `edge_antimeridian.geojson` | Polygon crossing ±180 (Fiji vicinity, `ProducerCountry` "FJ"). **Behavior documented, must not crash.** "FJ" is intentionally absent from the v1 bbox table, so the swap heuristic is skipped for it (documents the "no bbox data → skip check 6" path). |
| `edge_precision_exact.geojson` | 6-decimal-exact coordinate → **must pass, must NOT raise `GEOM_PRECISION_*`.** Guards against a min-precision check that mistakes exactly-6-decimals for too few. |
| `swap_tiers.geojson` | Two features exercising both swap tiers: feature 0 → `GEOM_COORDS_LIKELY_SWAPPED` **ERROR** (un-swap lands in KE, "almost certainly swapped"); feature 1 → `GEOM_COORDS_LIKELY_SWAPPED` **WARNING** (un-swap still outside KE, "possibly swapped"). |

## Fault-class coverage (the floor, not the ceiling)

The eight `broken_seeded` faults + the edge/swap fixtures cover: property casing,
ISO3 country, string Area, unclosed ring, self-intersection, rejected geometry
type, coordinate out of range, both swap tiers, null geometry, empty collection,
antimeridian, and precision-exactness. Additional per-check unit fixtures will be
added under the core test modules as those checks are built.
