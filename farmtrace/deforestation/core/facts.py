"""
Deforestation fact layer: a plot geometry -> DeforestationFacts.

REGULATION-AGNOSTIC and VERDICT-FREE (the fact-vs-verdict firewall). It emits the
FULL loss-year histogram and the 2020 forest state; it applies NO cutoff and
returns NO 'compliant/non-compliant' judgement — those belong to the Stage-3
ruleset. Every fact carries an explainability block (inputs, equation, assumptions,
uncertainty, provenance) per the platform's Explainability Requirement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from shapely.geometry import mapping

from .geometry import footprint_for, geodesic_area_ha
from .provider import Provider

PROVENANCE = {
    "forest_baseline": ("JRC Global Forest Cover 2020 (GFC2020) V3, band 'Map', ~10 m; "
                        "forest per the FAO forest definition. Asset + encoding verified "
                        "2026-08-12 (probe_datasets.py)."),
    "forest_loss": ("Hansen/UMD Global Forest Change v1.13 (2025), bands 'lossyear' & "
                    "'treecover2000', ~30 m. Asset + encoding verified 2026-08-12."),
    "point_footprint": ("EXPERT ASSUMPTION: a Point plot's footprint is a geodesic circle "
                        "of the declared Area; EUDR supplies point + Area but mandates no "
                        "footprint shape."),
}


@dataclass(frozen=True)
class DeforestationFacts:
    identifier: Optional[str]
    footprint_kind: str                       # 'polygon' | 'point-buffer'
    plot_area_ha: float
    forest_2020_fraction: float               # 0..1
    forest_2020_area_ha: float
    treecover2000_mean: float                 # 0..100
    loss_area_by_year: Mapping[int, float]    # full histogram, ha (NO cutoff applied)
    explainability: dict

    @property
    def total_loss_area_ha(self) -> float:
        return sum(self.loss_area_by_year.values())

    def to_dict(self) -> dict:
        return {
            "identifier": self.identifier,
            "footprint_kind": self.footprint_kind,
            "plot_area_ha": round(self.plot_area_ha, 4),
            "forest_2020_fraction": round(self.forest_2020_fraction, 4),
            "forest_2020_area_ha": round(self.forest_2020_area_ha, 4),
            "treecover2000_mean": round(self.treecover2000_mean, 2),
            "loss_area_by_year": {str(y): round(a, 4) for y, a in sorted(self.loss_area_by_year.items())},
            "total_loss_area_ha": round(self.total_loss_area_ha, 4),
            "explainability": self.explainability,
        }


def build_facts(geometry: dict, area_ha, provider: Provider,
                identifier: Optional[str] = None) -> DeforestationFacts:
    footprint, kind = footprint_for(geometry, area_ha)
    plot_area = geodesic_area_ha(footprint)
    raw = provider.reduce(mapping(footprint), plot_area)
    forest_area = raw.forest_2020_fraction * plot_area

    explain = {
        "inputs": {
            "forest_baseline": {"asset": "JRC/GFC2020/V3", "band": "Map", "scale_m": 10.0},
            "forest_loss": {"asset": "UMD/hansen/global_forest_change_2025_v1_13",
                            "bands": ["lossyear", "treecover2000"], "scale_m": 30.0},
            "footprint_kind": kind,
        },
        "equations": {
            "plot_area_ha": "geodesic area of the footprint (WGS84 ellipsoid)",
            "forest_2020_fraction": "mean(GFC2020.Map.unmask(0)) over footprint @10 m",
            "forest_2020_area_ha": "forest_2020_fraction * plot_area_ha",
            "loss_area_by_year": "sum(pixelArea where lossyear==Y) over footprint @30 m, per year",
            **({"point_footprint_radius_m": "sqrt(Area_ha * 1e4 / pi)"} if kind == "point-buffer" else {}),
        },
        "assumptions": [
            "GFC2020 non-forest is masked and read as 0 via unmask(0).",
            "Hansen lossyear no-loss is masked and read as 0 via unmask(0).",
            *(["Point footprint is a geodesic circle of the declared Area (see provenance)."]
              if kind == "point-buffer" else []),
        ],
        "uncertainty": ("GFC2020 ~10 m, Hansen ~30 m native resolution; sub-pixel plot edges "
                        "and GPS error are not modelled; loss-area uses GEE pixelArea while "
                        "plot_area_ha is geodesic (<1% divergence on small plots)."),
        "provenance": PROVENANCE,
    }

    return DeforestationFacts(
        identifier=identifier,
        footprint_kind=kind,
        plot_area_ha=plot_area,
        forest_2020_fraction=raw.forest_2020_fraction,
        forest_2020_area_ha=forest_area,
        treecover2000_mean=raw.treecover2000_mean,
        loss_area_by_year=dict(raw.loss_area_by_year),
        explainability=explain,
    )
