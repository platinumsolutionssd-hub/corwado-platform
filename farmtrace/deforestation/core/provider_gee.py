"""
Live Earth Engine implementation of the deforestation Provider — the ONLY module
in this package that imports earthengine-api. Uses the Stage-0-verified assets and
band encodings (see probe_datasets.py's grounding record).

Verified (2026-08-12, probe_datasets.py):
  GFC2020 JRC/GFC2020/V3 'Map' (~10 m): 1=forest, non-forest MASKED -> unmask(0).
  Hansen  UMD/hansen/global_forest_change_2025_v1_13 (~30 m):
    lossyear 0=none / N=year 2000+N, masked at no-loss -> unmask(0);
    treecover2000 = canopy % in 2000.
"""
from __future__ import annotations

import ee

from .provider import Provider, RawReduction

HANSEN = "UMD/hansen/global_forest_change_2025_v1_13"
GFC2020 = "JRC/GFC2020/V3"
# Explicit catalog resolutions (Stage 0 lesson: never trust nominalScale() after a
# projection-losing op; sample at the documented native scale).
GFC2020_SCALE_M = 10.0
HANSEN_SCALE_M = 30.0
_MAXPIXELS = int(1e9)


class GeeProvider(Provider):
    def __init__(self, project: str | None = None, initialize: bool = True):
        if initialize and project:
            ee.Initialize(project=project)
        self._forest = ee.Image(GFC2020).select("Map").unmask(0)          # 1=forest, 0=non-forest
        self._hansen = ee.Image(HANSEN)
        self._lossyear = self._hansen.select("lossyear").unmask(0)        # 0=no loss, N=2000+N

    def reduce(self, footprint_geojson: dict, footprint_area_ha: float) -> RawReduction:
        geom = ee.Geometry(footprint_geojson)

        forest_frac = self._forest.reduceRegion(
            ee.Reducer.mean(), geom, GFC2020_SCALE_M, maxPixels=_MAXPIXELS).get("Map")
        tc_mean = self._hansen.select("treecover2000").reduceRegion(
            ee.Reducer.mean(), geom, HANSEN_SCALE_M, maxPixels=_MAXPIXELS).get("treecover2000")

        # loss area per year: sum pixelArea grouped by lossyear, over loss pixels only.
        # image bands: [area (0), lossyear (1)] -> group by band 1, sum band 0.
        loss_img = (ee.Image.pixelArea()
                    .addBands(self._lossyear)
                    .updateMask(self._lossyear.gt(0)))
        grouped = loss_img.reduceRegion(
            ee.Reducer.sum().group(groupField=1, groupName="year"),
            geom, HANSEN_SCALE_M, maxPixels=_MAXPIXELS)

        info = ee.Dictionary({
            "forest": forest_frac, "tc": tc_mean, "groups": grouped.get("groups"),
        }).getInfo()

        by_year = {}
        for g in (info.get("groups") or []):
            year = 2000 + int(g["year"])
            by_year[year] = float(g["sum"]) / 1e4  # m^2 -> ha

        return RawReduction(
            forest_2020_fraction=float(info.get("forest") or 0.0),
            loss_area_by_year=by_year,
            treecover2000_mean=float(info.get("tc") or 0.0),
        )
