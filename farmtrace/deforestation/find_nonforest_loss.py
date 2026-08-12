"""
Stage 3b — divergence ground-truth finder: a plot that is NON-forest at the 2020
baseline (GFC2020 Map==0) yet has post-2020 Hansen tree loss (lossyear>=21). This
is the case the Stage-2 forest-intersection amendment protects — a cropland /
savanna plot losing a scattered tree post-cutoff must come back COMPLIANT
(all-tree-loss > 0 but forest-loss ~0), NOT flagged as deforestation.

The existing fixtures never exercise this (their post-2020 loss fell on forest, so
all-loss == forest-loss). We find a real divergence plot to prove it live.

Definition:
    non_forest_2020 = GFC2020 'Map'.unmask(0) == 0
    loss_post2020   = Hansen 'lossyear'.unmask(0) >= 21   (2021+)
    divergence      = non_forest_2020 AND loss_post2020

Scans several regions (CORWADO's Wau theatre first) and samples from the first that
yields qualifying pixels, tagging each with loss year + treecover2000.

RUN (cwd = repo root):
    $env:GEE_PROJECT="your-project-id"; python farmtrace/deforestation/find_nonforest_loss.py
"""
from __future__ import annotations

import os
import sys

try:
    import ee
except ImportError:
    print("ERROR: earthengine-api is not installed in this interpreter.")
    sys.exit(2)

PROJECT = os.environ.get("GEE_PROJECT", "")

HANSEN = "UMD/hansen/global_forest_change_2025_v1_13"
GFC2020 = "JRC/GFC2020/V3"
CUTOFF_LOSSYEAR = 21
N_SAMPLES = 8
SCALE_M = 30.0

# (label, [min_lon, min_lat, max_lon, max_lat]) — CORWADO theatre first, then
# frontier mosaics likely to hold non-forest-with-loss pixels.
REGIONS = [
    ("Wau savanna, W. Bahr el Ghazal SS (CORWADO theatre)", [27.80, 7.40, 28.20, 7.80]),
    ("Mau frontier mosaic, KE",                             [35.30, -0.60, 35.55, -0.35]),
    ("Western Kenya agricultural mosaic, KE",               [34.65, 0.15, 34.95, 0.45]),
]


def main() -> int:
    if not PROJECT:
        print('ERROR: set GEE_PROJECT, e.g.  $env:GEE_PROJECT="your-project-id"')
        return 2
    try:
        ee.Initialize(project=PROJECT)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: ee.Initialize failed: {e}")
        return 2
    print(f"Earth Engine initialised on project: {PROJECT}")
    print(f"Divergence: GFC2020 forest==0  AND  Hansen lossyear >= {CUTOFF_LOSSYEAR} (2021+)\n")

    forest = ee.Image(GFC2020).select("Map").unmask(0)
    hansen = ee.Image(HANSEN)
    lossyear = hansen.select("lossyear").unmask(0)
    treecover = hansen.select("treecover2000")
    divergence = forest.eq(0).And(lossyear.gte(CUTOFF_LOSSYEAR)).rename("div")

    chosen = None
    for label, box in REGIONS:
        region = ee.Geometry.Rectangle(box)
        count = divergence.selfMask().reduceRegion(
            ee.Reducer.count(), region, SCALE_M, maxPixels=int(1e9)).get("div")
        count = count.getInfo() if count is not None else 0
        print(f"  {label}: {count} qualifying pixels  (box {box})")
        if count and chosen is None:
            chosen = (label, region)

    if chosen is None:
        print("\n>>> No divergence pixels in any region. Widen a box or add a region.")
        return 1

    label, region = chosen
    print(f"\nSampling from: {label}")
    samp = (divergence.selfMask()
            .addBands(lossyear.rename("lossyear"))
            .addBands(treecover.rename("treecover2000"))
            .addBands(forest.rename("forest2020"))
            .addBands(ee.Image.pixelLonLat())
            .sample(region=region, scale=SCALE_M, numPixels=int(5e4),
                    seed=1, geometries=True, dropNulls=True)
            .limit(N_SAMPLES))
    feats = samp.getInfo().get("features", [])
    print("lon, lat  |  lossyear  |  treecover2000  |  forest2020(should be 0):")
    for f in feats:
        lon, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        yr = 2000 + int(p.get("lossyear", 0))
        print(f"    ({lon:.5f}, {lat:.5f})   {int(p.get('lossyear',0))} -> {yr}   "
              f"tc={int(p.get('treecover2000',0))}   forest2020={int(p.get('forest2020',0))}")

    print("\nPick a coordinate whose NEIGHBOURHOOD is mostly non-forest (a 1.7 ha plot")
    print("there should read forest_2020_fraction low). Paste the whole output back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
