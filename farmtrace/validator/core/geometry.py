"""
The single place the validator touches shapely / pyproj. Every geometry
computation the checks need lives behind these functions, so the dependency
boundary is one file and the checks stay readable.

Areas are geodesic (WGS84 ellipsoid via pyproj), never planar — a planar
"area" in degrees is meaningless for a hectare threshold.
"""
from __future__ import annotations

from typing import Optional

from shapely.geometry import shape as _shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity
from pyproj import Geod

_GEOD = Geod(ellps="WGS84")


def to_shape(geometry: dict) -> BaseGeometry:
    return _shape(geometry)


def _ring_area_ha(coords) -> float:
    lons = [float(c[0]) for c in coords]
    lats = [float(c[1]) for c in coords]
    area_m2, _ = _GEOD.polygon_area_perimeter(lons, lats)
    return abs(area_m2) / 10_000.0


def geodesic_area_ha(exterior_coords) -> float:
    """Absolute geodesic area (hectares) of a single polygon exterior ring."""
    return _ring_area_ha(exterior_coords)


def shape_area_ha(shp: BaseGeometry) -> float:
    """Geodesic area of a shapely Polygon or MultiPolygon (exteriors only)."""
    if shp.is_empty:
        return 0.0
    if shp.geom_type == "Polygon":
        return _ring_area_ha(list(shp.exterior.coords))
    if shp.geom_type == "MultiPolygon":
        return sum(_ring_area_ha(list(g.exterior.coords)) for g in shp.geoms)
    return 0.0


def ring_is_closed(ring) -> bool:
    if len(ring) < 2:
        return False
    a, b = ring[0], ring[-1]
    return float(a[0]) == float(b[0]) and float(a[1]) == float(b[1])


def self_intersection(polygon_shape: BaseGeometry):
    """Return (is_self_intersecting, approx_crossing_point_or_None). Uses
    shapely's validity explanation, which reports the offending location for a
    self-intersection."""
    if polygon_shape.is_valid:
        return False, None
    reason = explain_validity(polygon_shape)  # e.g. "Self-intersection[37.1 -0.7]"
    if "self-intersection" not in reason.lower():
        return False, None
    point = None
    if "[" in reason and "]" in reason:
        inside = reason[reason.index("[") + 1: reason.index("]")].replace(",", " ")
        parts = inside.split()
        try:
            point = (round(float(parts[0]), 6), round(float(parts[1]), 6))
        except (ValueError, IndexError):
            point = None
    return True, point


def point_in_bbox(lon: float, lat: float, bbox) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def overlap_fraction_of_smaller(shp_a: BaseGeometry, shp_b: BaseGeometry):
    """(overlap_ha, fraction_of_smaller_area). fraction is 0..1; 0 if disjoint or
    either area is 0. Uses geodesic areas so the fraction is honest."""
    if not shp_a.intersects(shp_b):
        return 0.0, 0.0
    inter = shp_a.intersection(shp_b)
    overlap_ha = shape_area_ha(inter)
    if overlap_ha <= 0:
        return 0.0, 0.0
    a, b = shape_area_ha(shp_a), shape_area_ha(shp_b)
    smaller = min(a, b)
    if smaller <= 0:
        return overlap_ha, 0.0
    return overlap_ha, overlap_ha / smaller


def crosses_antimeridian(exterior_coords) -> bool:
    """True if consecutive longitudes jump by more than 180 degrees — the
    signature of a ring that wraps across +/-180."""
    lons = [float(c[0]) for c in exterior_coords]
    return any(abs(lons[i] - lons[i - 1]) > 180 for i in range(1, len(lons)))
