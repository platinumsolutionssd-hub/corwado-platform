"""
The RuleSet contract — the single seam between the scheme-agnostic core and a
certification scheme. A RuleSet is pure configuration: every threshold the checks
use comes from here, so `core/` contains no scheme constants. Concrete schemes
(e.g. rulesets/eudr.py) build a RuleSet instance; the core never names one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class GeometryDisposition(str, Enum):
    ALLOWED = "allowed"          # accepted silently
    DISCOURAGED = "discouraged"  # accepted, WARNING
    REJECTED = "rejected"        # ERROR


class Applies(str, Enum):
    ALL = "all"
    POINT = "point"      # Point + MultiPoint
    POLYGON = "polygon"  # Polygon + MultiPolygon


@dataclass(frozen=True)
class PropertySpec:
    """One required/recommended property, matched by EXACT casing."""
    name: str
    py_types: tuple            # acceptable python types, e.g. (str,) or (int, float, Decimal)
    required: bool             # True -> ERROR if absent; False -> WARNING (recommended)
    applies: Applies = Applies.ALL


@dataclass(frozen=True)
class RuleSet:
    name: str
    cutoff_date: date                       # carried for the deforestation module; unused by these checks
    min_precision_decimals: int
    excess_precision_decimals: int          # labelled expert assumption
    polygon_threshold_ha: float
    default_point_area_ha: float
    allowed_geometries: dict                # geom_type -> GeometryDisposition
    required_properties: tuple              # tuple[PropertySpec, ...]
    country_property: str                   # which property holds the country code
    area_property: str                      # which property holds Area
    country_code_standard: str
    iso2_codes: frozenset                   # valid ISO 3166-1 alpha-2 set
    iso3_to_iso2: dict                      # ISO3 -> ISO2, to identify the "you wrote ISO3" case
    country_bboxes: dict                    # ISO2 -> (min_lon, min_lat, max_lon, max_lat)
    max_payload_mb: float
    payload_warn_mb: float
    max_plots: int
    plots_warn: int                         # labelled expert assumption
    file_types: tuple                       # ("I", "II")
    overlap_sliver_pct: float               # labelled expert assumption
    area_divergence_pct: float              # labelled expert assumption

    def disposition(self, geom_type: str) -> GeometryDisposition:
        """Unknown/unlisted types are rejected by default (deny-closed)."""
        return self.allowed_geometries.get(geom_type, GeometryDisposition.REJECTED)

    def bbox_for(self, iso2: Optional[str]):
        return self.country_bboxes.get(iso2) if iso2 else None

    def validate(self) -> None:
        """Sanity-check a ruleset on load — fail loudly on an incoherent config
        rather than silently misvalidate."""
        errs = []
        if self.min_precision_decimals < 0:
            errs.append("min_precision_decimals must be >= 0")
        if self.excess_precision_decimals < self.min_precision_decimals:
            errs.append("excess_precision_decimals must be >= min_precision_decimals")
        if self.polygon_threshold_ha <= 0:
            errs.append("polygon_threshold_ha must be > 0")
        if self.payload_warn_mb > self.max_payload_mb:
            errs.append("payload_warn_mb must be <= max_payload_mb")
        if self.plots_warn > self.max_plots:
            errs.append("plots_warn must be <= max_plots")
        if not (0 < self.overlap_sliver_pct < 100):
            errs.append("overlap_sliver_pct must be in (0, 100)")
        if not (0 < self.area_divergence_pct < 100):
            errs.append("area_divergence_pct must be in (0, 100)")
        if not self.required_properties:
            errs.append("required_properties must be non-empty")
        for p in self.required_properties:
            if not p.py_types:
                errs.append(f"property {p.name} has no acceptable types")
        if errs:
            raise ValueError(f"invalid RuleSet '{self.name}': " + "; ".join(errs))
