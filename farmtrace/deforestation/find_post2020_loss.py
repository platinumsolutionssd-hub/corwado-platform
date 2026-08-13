"""
Stage 1a — ground-truth finder for the FarmTrace deforestation baseline (2.4).

The probe (probe_datasets.py) gave us verified real-world truth for four fixture
classes (intact forest, never-forested, non-forest built-up, pre-2020 clearing).
It did NOT give us the case that matters most for EUDR: a parcel that was forest
at the 2020 baseline AND lost forest AFTER the 2020-12-31 cutoff. We will not
invent such a coordinate (Anti-Hallucination Rule) — this finds a real one.

Definition (matches the verified encodings from Stage 0):
    forest_2020   = GFC2020 'Map'.unmask(0) == 1          (forest at baseline)
    loss_post2020 = Hansen 'lossyear'.unmask(0) >= 21     (loss in 2021+)
    deforestation = forest_2020 AND loss_post2020

Reports, over a search region: qualifying pixel count, total hectares, and up to
N sample pixel coordinates with their loss year — so we can drop a fixture polygon
on a confirmed, dated, post-cutoff clearing.

REQUIRES: earthengine-api, EE API enabled on the project, `earthengine authenticate`.

RUN (cwd = repo root):
    $env:GEE_PROJECT="your-project-id"; python farmtrace/deforestation/find_post2020_loss.py
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

# Verified asset ids (Stage 0, probe_datasets.py, 2026-08-12).
HANSEN = "UMD/hansen/global_forest_change_2025_v1_13"
GFC2020 = "JRC/GFC2020/V3"

# EUDR: loss is post-cutoff if lossyear >= 21 (year 2021+), cutoff 2020-12-31.
CUTOFF_LOSSYEAR = 21

# Search region: a Mau Forest complex frontier box (min_lon, min_lat, max_lon, max_lat).
# Mau has documented post-2020 logging; widen or move this if the count comes back 0.
REGION = [35.30, -0.60, 35.60, -0.30]

N_SAMPLES = 8
SAMPLE_SCALE_M = 30.0   # Hansen native; the limiting layer for the loss signal


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

    region = ee.Geometry.Rectangle(REGION)
    hansen = ee.Image(HANSEN)
    gfc = ee.Image(GFC2020)

    forest_2020 = gfc.select("Map").unmask(0).eq(1)
    lossyear = hansen.select("lossyear").unmask(0)
    loss_post = lossyear.gte(CUTOFF_LOSSYEAR)
    deforestation = forest_2020.And(loss_post).rename("defor")

    print(f"\nSearch region (lon/lat box): {REGION}")
    print(f"Definition: GFC2020 forest==1  AND  Hansen lossyear >= {CUTOFF_LOSSYEAR} (2021+)\n")

    # count + area of qualifying pixels
    count = deforestation.selfMask().reduceRegion(
        ee.Reducer.count(), region, SAMPLE_SCALE_M, maxPixels=int(1e9)).get("defor")
    area_ha = deforestation.multiply(ee.Image.pixelArea()).reduceRegion(
        ee.Reducer.sum(), region, SAMPLE_SCALE_M, maxPixels=int(1e9)).get("defor")
    count = count.getInfo() if count is not None else 0
    area_ha = (area_ha.getInfo() or 0.0) / 1e4
    print(f"Qualifying pixels: {count}")
    print(f"Total post-2020 forest-loss area in box: {area_ha:.2f} ha")

    if not count:
        print("\n>>> Zero qualifying pixels in this box. Widen REGION or move it to another")
        print("    frontier (e.g. Mt Elgon, Cherangani, Aberdare edge) and re-run.")
        return 1

    # sample coordinates of qualifying pixels, tagged with their loss year
    samp = (deforestation.selfMask()
            .addBands(lossyear.rename("lossyear"))
            .addBands(ee.Image.pixelLonLat())
            .sample(region=region, scale=SAMPLE_SCALE_M, numPixels=int(5e4),
                    seed=1, geometries=True, dropNulls=True)
            .limit(N_SAMPLES))
    feats = samp.getInfo().get("features", [])
    print(f"\nSample qualifying pixels (up to {N_SAMPLES}) — lon, lat, loss year:")
    for f in feats:
        lon, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        yr = 2000 + int(p.get("lossyear", 0))
        print(f"    ({lon:.5f}, {lat:.5f})   lossyear={int(p.get('lossyear',0))} -> {yr}")

    print("\nPick one coordinate above for the 'post-2020 deforestation' fixture; the")
    print("others corroborate it. Paste this whole output back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
