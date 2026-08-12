"""
EUDR rule set — the first (and currently only) concrete scheme for the validator
core. Pure configuration: it constructs a core RuleSet; it adds no logic. Swapping
schemes means writing another module like this one, with zero changes to core/.

SOURCES (Scientific Evidence Rule — no magic numbers):
  * cut-off date: Regulation (EU) 2023/1115 (EUDR) — cut-off date 31 December 2020.
  * geolocation format values (>=6-decimal precision; 4 ha polygon threshold and
    the 4 ha default point area; permitted geometry types; ProducerName /
    ProducerCountry / ProductionPlace / Area properties with exact casing;
    ProducerCountry = ISO 3166-1 alpha-2; 25 MB payload limit; 10,000-plot limit;
    Type I producer-level vs Type II multi-producer): EUDR GeoJSON File
    Description v1.5 (the EU Information System / TRACES geolocation submission
    format).
  * ISO 3166-1 code set + alpha-3->alpha-2 map: iso_codes.py (generated from the
    ISO 3166 dataset via pycountry).
  * country bounding boxes: approximate admin-0 extents (Natural-Earth-scale),
    coarse — used ONLY by the lon/lat-swap heuristic; see _COUNTRY_BBOXES.

Values marked "EXPERT ASSUMPTION" have no official EUDR figure and are labelled as
such (Anti-Hallucination Rule); each is a single, configurable parameter.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..core.ruleset import Applies, GeometryDisposition, PropertySpec, RuleSet
from .iso_codes import ISO2_CODES, ISO3_TO_ISO2

# Approximate country bounding boxes (min_lon, min_lat, max_lon, max_lat).
# Coarse extents for the coordinate-swap heuristic only — NOT precise borders.
# v1 covers the East-Africa operating theatre + two West-African cocoa origins;
# a country absent here simply skips the swap check (documented behaviour).
# Replace with exact dataset extents (e.g. Natural Earth admin-0) if tighter
# bounds are ever needed.
_COUNTRY_BBOXES = {
    "KE": (33.9, -4.7, 41.9, 5.5),    # Kenya
    "UG": (29.5, -1.5, 35.0, 4.3),    # Uganda
    "TZ": (29.3, -11.8, 40.5, -0.9),  # Tanzania
    "ET": (32.9, 3.4, 48.0, 14.9),    # Ethiopia
    "RW": (28.8, -2.9, 30.9, -1.0),   # Rwanda
    "SS": (23.4, 3.5, 35.9, 12.3),    # South Sudan
    "CI": (-8.6, 4.3, -2.5, 10.8),    # Côte d'Ivoire
    "GH": (-3.3, 4.7, 1.2, 11.2),     # Ghana
}


def eudr_ruleset() -> RuleSet:
    rs = RuleSet(
        name="EUDR",
        cutoff_date=date(2020, 12, 31),          # Reg. (EU) 2023/1115 cut-off date
        min_precision_decimals=6,                # GeoJSON File Description v1.5
        excess_precision_decimals=7,             # EXPERT ASSUMPTION: spec basis is 6; allow 1 extra digit
        polygon_threshold_ha=4.0,                # GeoJSON File Description v1.5
        default_point_area_ha=4.0,               # GeoJSON File Description v1.5 (assumed when Area absent)
        allowed_geometries={
            "Point": GeometryDisposition.ALLOWED,
            "MultiPoint": GeometryDisposition.ALLOWED,
            "Polygon": GeometryDisposition.ALLOWED,
            "MultiPolygon": GeometryDisposition.ALLOWED,
            "LineString": GeometryDisposition.REJECTED,
            "MultiLineString": GeometryDisposition.REJECTED,
            "GeometryCollection": GeometryDisposition.DISCOURAGED,
        },
        required_properties=(
            PropertySpec("ProducerName", (str,), True, Applies.ALL),
            PropertySpec("ProducerCountry", (str,), True, Applies.ALL),      # ISO2
            PropertySpec("ProductionPlace", (str,), False, Applies.ALL),     # recommended -> WARNING
            PropertySpec("Area", (int, float, Decimal), True, Applies.POINT),
        ),
        country_property="ProducerCountry",
        area_property="Area",
        country_code_standard="ISO 3166-1 alpha-2",
        iso2_codes=ISO2_CODES,
        iso3_to_iso2=ISO3_TO_ISO2,
        country_bboxes=_COUNTRY_BBOXES,
        max_payload_mb=25.0,                     # GeoJSON File Description v1.5
        payload_warn_mb=20.0,                    # EXPERT ASSUMPTION: 80% of the hard limit
        max_plots=10000,                         # GeoJSON File Description v1.5
        plots_warn=8000,                         # EXPERT ASSUMPTION: 80% of the hard limit
        file_types=("I", "II"),                  # Type I producer-level, Type II multi-producer
        overlap_sliver_pct=0.5,                  # EXPERT ASSUMPTION: no official EUDR sliver tolerance
        area_divergence_pct=25.0,                # EXPERT ASSUMPTION: no official figure; GPS-drift tolerant
    )
    rs.validate()
    return rs
