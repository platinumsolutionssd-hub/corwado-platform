"""
The finding-code taxonomy. Stable uppercase `<LEVEL>_<SLUG>` strings, decoupled
from any check numbering, and scheme-agnostic (the ruleset supplies the
parameter that defines each boundary; the code names the fault class). Each code
has a default severity and a short human title; the per-finding `source` is set
by the check from the ruleset that drove it.

A few checks override the default severity at emit time (documented inline) —
notably the two-tier coordinate-swap heuristic.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Severity


@dataclass(frozen=True)
class CodeSpec:
    code: str
    default_severity: Severity
    title: str


# ---- File level ----
FILE_INVALID_JSON = "FILE_INVALID_JSON"
FILE_NOT_FEATURECOLLECTION = "FILE_NOT_FEATURECOLLECTION"
FILE_EMPTY_COLLECTION = "FILE_EMPTY_COLLECTION"
FILE_PAYLOAD_WARN = "FILE_PAYLOAD_WARN"
FILE_PAYLOAD_EXCEEDED = "FILE_PAYLOAD_EXCEEDED"
FILE_PLOT_COUNT_WARN = "FILE_PLOT_COUNT_WARN"
FILE_PLOT_COUNT_EXCEEDED = "FILE_PLOT_COUNT_EXCEEDED"
FILE_TYPEII_COUNTRY_MISSING = "FILE_TYPEII_COUNTRY_MISSING"

# ---- Geometry level ----
GEOM_TYPE_REJECTED = "GEOM_TYPE_REJECTED"
GEOM_TYPE_DISCOURAGED = "GEOM_TYPE_DISCOURAGED"
GEOM_NULL = "GEOM_NULL"
GEOM_COORD_OUT_OF_RANGE = "GEOM_COORD_OUT_OF_RANGE"
GEOM_COORDS_LIKELY_SWAPPED = "GEOM_COORDS_LIKELY_SWAPPED"
GEOM_RING_NOT_CLOSED = "GEOM_RING_NOT_CLOSED"
GEOM_RING_TOO_FEW_POINTS = "GEOM_RING_TOO_FEW_POINTS"
GEOM_SELF_INTERSECTION = "GEOM_SELF_INTERSECTION"
GEOM_INTERIOR_RING = "GEOM_INTERIOR_RING"
GEOM_DUPLICATE_CONSECUTIVE = "GEOM_DUPLICATE_CONSECUTIVE"
GEOM_PRECISION_INSUFFICIENT = "GEOM_PRECISION_INSUFFICIENT"
GEOM_PRECISION_EXCESS = "GEOM_PRECISION_EXCESS"
GEOM_ANTIMERIDIAN = "GEOM_ANTIMERIDIAN"

# ---- Property level ----
PROP_MISSING = "PROP_MISSING"
PROP_CASING_MISMATCH = "PROP_CASING_MISMATCH"
PROP_RECOMMENDED_MISSING = "PROP_RECOMMENDED_MISSING"
PROP_COUNTRY_NOT_ISO2 = "PROP_COUNTRY_NOT_ISO2"
PROP_COUNTRY_IS_ISO3 = "PROP_COUNTRY_IS_ISO3"
PROP_AREA_NOT_NUMBER = "PROP_AREA_NOT_NUMBER"
PROP_POINT_AREA_MISSING = "PROP_POINT_AREA_MISSING"
PROP_POLYGON_AREA_INCONSISTENT = "PROP_POLYGON_AREA_INCONSISTENT"
THRESH_POINT_AREA_TOO_LARGE = "THRESH_POINT_AREA_TOO_LARGE"

# ---- Cross-feature level ----
XFEAT_OVERLAP = "XFEAT_OVERLAP"
XFEAT_DUPLICATE_PRODUCER = "XFEAT_DUPLICATE_PRODUCER"


REGISTRY: dict[str, CodeSpec] = {c.code: c for c in [
    CodeSpec(FILE_INVALID_JSON, Severity.ERROR, "File is not valid JSON"),
    CodeSpec(FILE_NOT_FEATURECOLLECTION, Severity.ERROR, "Top level is not a FeatureCollection"),
    CodeSpec(FILE_EMPTY_COLLECTION, Severity.WARNING, "FeatureCollection has no features"),
    CodeSpec(FILE_PAYLOAD_WARN, Severity.WARNING, "Payload approaching the size limit"),
    CodeSpec(FILE_PAYLOAD_EXCEEDED, Severity.ERROR, "Payload exceeds the size limit"),
    CodeSpec(FILE_PLOT_COUNT_WARN, Severity.WARNING, "Plot count approaching the limit"),
    CodeSpec(FILE_PLOT_COUNT_EXCEEDED, Severity.ERROR, "Plot count exceeds the limit"),
    CodeSpec(FILE_TYPEII_COUNTRY_MISSING, Severity.ERROR, "Type II: ProducerCountry missing on a feature"),

    CodeSpec(GEOM_TYPE_REJECTED, Severity.ERROR, "Geometry type not permitted"),
    CodeSpec(GEOM_TYPE_DISCOURAGED, Severity.WARNING, "Geometry type discouraged"),
    CodeSpec(GEOM_NULL, Severity.ERROR, "Feature has no geometry"),
    CodeSpec(GEOM_COORD_OUT_OF_RANGE, Severity.ERROR, "Coordinate out of valid lon/lat range"),
    CodeSpec(GEOM_COORDS_LIKELY_SWAPPED, Severity.WARNING, "Coordinates appear swapped"),
    CodeSpec(GEOM_RING_NOT_CLOSED, Severity.ERROR, "Polygon ring is not closed"),
    CodeSpec(GEOM_RING_TOO_FEW_POINTS, Severity.ERROR, "Polygon ring has too few points"),
    CodeSpec(GEOM_SELF_INTERSECTION, Severity.ERROR, "Polygon self-intersects"),
    CodeSpec(GEOM_INTERIOR_RING, Severity.ERROR, "Polygon has interior rings (holes)"),
    CodeSpec(GEOM_DUPLICATE_CONSECUTIVE, Severity.WARNING, "Duplicate consecutive coordinates"),
    CodeSpec(GEOM_PRECISION_INSUFFICIENT, Severity.WARNING, "Coordinate precision below minimum"),
    CodeSpec(GEOM_PRECISION_EXCESS, Severity.WARNING, "Coordinate precision beyond useful"),
    CodeSpec(GEOM_ANTIMERIDIAN, Severity.WARNING, "Geometry crosses the antimeridian"),

    CodeSpec(PROP_MISSING, Severity.ERROR, "Required property missing"),
    CodeSpec(PROP_CASING_MISMATCH, Severity.ERROR, "Property present with wrong casing"),
    CodeSpec(PROP_RECOMMENDED_MISSING, Severity.WARNING, "Recommended property missing"),
    CodeSpec(PROP_COUNTRY_NOT_ISO2, Severity.ERROR, "Country code is not valid ISO 3166-1 alpha-2"),
    CodeSpec(PROP_COUNTRY_IS_ISO3, Severity.ERROR, "Country code is ISO3, expected ISO2"),
    CodeSpec(PROP_AREA_NOT_NUMBER, Severity.ERROR, "Area is not a numeric value"),
    CodeSpec(PROP_POINT_AREA_MISSING, Severity.ERROR, "Point feature has no Area"),
    CodeSpec(PROP_POLYGON_AREA_INCONSISTENT, Severity.WARNING, "Declared Area diverges from computed area"),
    CodeSpec(THRESH_POINT_AREA_TOO_LARGE, Severity.ERROR, "Point Area at/above threshold — must be a polygon"),

    CodeSpec(XFEAT_OVERLAP, Severity.WARNING, "Plots overlap"),
    CodeSpec(XFEAT_DUPLICATE_PRODUCER, Severity.WARNING, "Duplicate producer with near-identical geometry"),
]}


def default_severity(code: str) -> Severity:
    return REGISTRY[code].default_severity


def title(code: str) -> str:
    return REGISTRY[code].title
