"""
Stage 0 — dataset grounding probe for the FarmTrace deforestation baseline (2.4).

WHY THIS EXISTS (not shipped in the core):
Per the project's "verify the data before you trust it" discipline — the same
reason agri-venture keeps its root fetch_*/diagnose_* scripts — this confirms the
exact Earth Engine asset IDs resolve, prints their band names / type / native
scale, and samples them at points of KNOWN forest status. Every threshold the
core will later use must be grounded in the band semantics THIS RUN reports, not
in an assumed asset ID or an assumed encoding (Anti-Hallucination Rule).

EUDR anchor (Regulation (EU) 2023/1115, Art. 2): "deforestation-free" = produced
on land not subject to deforestation after 31 December 2020. That needs two
layers, and this probe verifies BOTH before any scoring is written:
  (1) "was this land forest at the 2020 baseline?"  -> JRC Global Forest Cover 2020
  (2) "was there forest loss after the cutoff?"      -> Hansen GFC lossyear >= 2021

------------------------------------------------------------------------------
VERIFIED FINDINGS (run 2026-08-12, EE project project-1-493810) — the grounding
record the core scoring must cite. Do NOT re-derive these; re-run this probe if
the assets version-bump.

  HANSEN  = UMD/hansen/global_forest_change_2025_v1_13   (Image, native ~27.8 m)
    treecover2000 : canopy cover % in 2000, 0-100.
    loss          : 0 / 1.
    lossyear      : 0 = no loss; N = year 2000+N. MASKED (returns None) at no-loss
                    pixels -> .unmask(0) before use. EUDR-relevant loss = lossyear
                    >= 21 (i.e. 2021+), the cutoff being 2020-12-31.
    datamask      : 1 = mapped land.

  GFC2020 = JRC/GFC2020/V3   (Image, single band 'Map', native ~9.3 m ~= 10 m)
    Map : a forest MASK. 1 = forest (2020 baseline). Non-forest is MASKED (returns
          None), NOT 0 -> the core MUST .unmask(0) before any area/mean reduction,
          or masked non-forest pixels are dropped and every plot reads ~100% forest.

  Cross-check (forest vs non-forest contrast, all coherent):
    Kakamega rainforest  tc=89  lossyear=0   Map=1     -> intact forest
    Mau Forest           tc=90  lossyear=7   Map=None  -> forest in 2000, cleared
                                                          2007 (PRE-cutoff, EUDR-
                                                          irrelevant), non-forest 2020
    Nairobi CBD          tc=5   lossyear=0   Map=None  -> non-forest
    Turkana desert       tc=0   lossyear=0   Map=None  -> non-forest
    Wau savanna (SS)     tc=1   lossyear=0   Map=None  -> non-forest

  => Two-layer design confirmed: GFC2020 anchors the 2020 forest baseline; Hansen
     lossyear catches post-cutoff loss. Hansen loss history ALONE would misfire on
     pre-2020 clearings (see Mau), which is exactly why both layers are required.
------------------------------------------------------------------------------

REQUIRES: earthengine-api installed, a GEE project with the Earth Engine API
enabled, and `earthengine authenticate` already run locally.

RUN (cwd = repo root):
    $env:GEE_PROJECT="your-project-id"; python farmtrace/deforestation/probe_datasets.py
  (or hardcode PROJECT below). Paste the full output back.
"""
from __future__ import annotations

import os
import sys

try:
    import ee
except ImportError:
    print("ERROR: earthengine-api is not installed in this interpreter.")
    print("       pip install earthengine-api")
    sys.exit(2)

# Set your Earth Engine project id here or via the GEE_PROJECT env var.
PROJECT = os.environ.get("GEE_PROJECT", "")

# --- Candidate asset IDs. This run CONFIRMS which one resolves. Newest first.
#     (Run 1 found 2024_v1_12 and GFC2020/V2, but BOTH were flagged deprecated by
#     the EE catalog -> using the current successors 2025_v1_13 and V3.) ---
HANSEN_CANDIDATES = [
    "UMD/hansen/global_forest_change_2025_v1_13",   # current (Run 1: v1_12 was deprecated)
    "UMD/hansen/global_forest_change_2024_v1_12",
    "UMD/hansen/global_forest_change_2023_v1_11",
]
# JRC Global Forest Cover 2020 — EU/JRC benchmark map, an ImageCollection with a
# single 'Map' band (Run 1 confirmed: V2 is an ImageCollection, band 'Map').
GFC2020_CANDIDATES = [
    "JRC/GFC2020/V3",   # current (Run 1: V2 was deprecated)
    "JRC/GFC2020/V2",
]

# Documented native resolutions from the GEE Data Catalog (metres). We sample at
# THESE explicit scales, NOT projection().nominalScale(): .mosaic() on an
# ImageCollection drops the fixed projection, so nominalScale() falls back to
# ~111 km (1 degree) and silently samples at the wrong scale. That fallback is the
# bug that made Run 1's GFC2020 samples meaningless (Nairobi CBD read as forest).
CATALOG_SCALE_M = {"hansen": 30.0, "gfc2020": 10.0}

# Points of known forest status (lon, lat), chosen for genuine forest-vs-non-forest
# CONTRAST so the real band encodings are legible. The probe reports raw values; it
# asserts nothing. (Run 1's Mt Kenya/Aberdare points landed on moorland ABOVE the
# treeline -> treecover ~5-6%, not usable as "forest" ground truth. Replaced.)
PROBE_POINTS = [
    ("Kakamega tropical rainforest, KE (expect: FOREST, high cover)", 34.865,  0.350),
    ("Mau Forest complex, KE           (expect: FOREST)",             35.550, -0.550),
    ("Nairobi CBD, KE                  (expect: NON-forest, built)",  36.8172, -1.2864),
    ("Turkana arid NW Kenya            (expect: NON-forest, desert)", 35.900,  3.500),
    ("Wau savanna, W. Bahr el Ghazal SS(expect: low / non-forest)",   27.990,  7.700),
]


def resolve_asset(candidates):
    """Return the first candidate that loads, as {id, kind, img, bands, native_scale}.

    native_scale is read from the UN-mosaicked source (ic.first() for collections)
    so the reported figure is the true asset resolution, not the mosaic fallback.
    """
    for cid in candidates:
        for kind in ("image", "collection"):
            try:
                if kind == "image":
                    img = ee.Image(cid)
                    base = img
                else:
                    ic = ee.ImageCollection(cid)
                    img = ic.mosaic()
                    base = ic.first()
                bands = img.bandNames().getInfo()
                native = base.select(0).projection().nominalScale().getInfo()
                print(f"    [OK] {cid}  ({kind}) -> bands={bands}  native_scale~{native:.2f} m")
                return {"id": cid, "kind": kind, "img": ee.Image(img), "bands": bands, "native_scale": native}
            except Exception as e:  # noqa: BLE001 - probe reports every failure verbatim
                msg = str(e).splitlines()[0][:140] if str(e) else ""
                print(f"    [no] {cid}  ({kind}): {type(e).__name__}: {msg}")
    return None


def sample(img, lon, lat, scale_m):
    pt = ee.Geometry.Point([lon, lat])
    try:
        return img.reduceRegion(ee.Reducer.first(), pt, scale_m).getInfo()
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {str(e).splitlines()[0][:140]}"}


def main() -> int:
    if not PROJECT:
        print("ERROR: no Earth Engine project set.")
        print('       Run as:  $env:GEE_PROJECT="your-project-id"; python farmtrace/deforestation/probe_datasets.py')
        return 2
    try:
        ee.Initialize(project=PROJECT)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: ee.Initialize failed: {e}")
        print("       Have you run `earthengine authenticate` and enabled the EE API on this project?")
        return 2
    print(f"Earth Engine initialised on project: {PROJECT}\n")

    print("=" * 72)
    print("(1) Hansen Global Forest Change — post-cutoff LOSS layer")
    print("    lossyear encoding: 0 = no loss; N = year 2000+N (so >= 21 means 2021+).")
    print("    treecover2000: percent canopy cover in 2000 (0-100).")
    hansen = resolve_asset(HANSEN_CANDIDATES)
    if not hansen:
        print("    >>> No Hansen candidate resolved. Search the GEE Data Catalog for")
        print("        'Hansen Global Forest Change' and paste the latest id back to me.")

    print()
    print("=" * 72)
    print("(2) JRC Global Forest Cover 2020 — the 2020 forest BASELINE layer")
    print("    'Map' band: JRC GFC2020 forest/non-forest (read the encoding below).")
    gfc = resolve_asset(GFC2020_CANDIDATES)
    if not gfc:
        print("    >>> No GFC2020 candidate resolved. Search the GEE Data Catalog for")
        print("        'JRC Global Forest Cover 2020' and paste me the exact asset id.")

    # sampling scales: explicit catalog resolution, NOT the mosaic fallback
    h_scale = CATALOG_SCALE_M["hansen"]
    g_scale = CATALOG_SCALE_M["gfc2020"]

    # lossyear reads as None where Hansen masks it (no-loss pixels); unmask to 0 so
    # "no loss" is legible as 0 rather than null.
    if hansen:
        hansen_img = hansen["img"].addBands(
            hansen["img"].select("lossyear").unmask(0).rename("lossyear_unmasked"))

    print()
    print("=" * 72)
    print(f"Point samples (Hansen @ {h_scale:.0f} m, GFC2020 @ {g_scale:.0f} m — explicit scales):")
    print("=" * 72)
    for label, lon, lat in PROBE_POINTS:
        print(f"\n  {label}\n    ({lon}, {lat})")
        if hansen:
            hs = sample(hansen_img, lon, lat, h_scale)
            keep = {k: hs.get(k) for k in
                    ("treecover2000", "loss", "lossyear", "lossyear_unmasked", "gain", "datamask")
                    if k in hs}
            print(f"    Hansen : {keep if keep else hs}")
        if gfc:
            gs = sample(gfc["img"], lon, lat, g_scale)
            print(f"    GFC2020: {gs}")

    print("\n" + "=" * 72)
    print("Resolved ids (paste this line back):")
    print(f"    HANSEN  = {hansen['id'] if hansen else 'UNRESOLVED'}"
          + (f"  (native ~{hansen['native_scale']:.1f} m)" if hansen else ""))
    print(f"    GFC2020 = {gfc['id'] if gfc else 'UNRESOLVED'}"
          + (f"  ({gfc['kind']}, band(s)={gfc['bands']}, native ~{gfc['native_scale']:.1f} m)" if gfc else ""))
    return 0 if (hansen and gfc) else 1


if __name__ == "__main__":
    sys.exit(main())
