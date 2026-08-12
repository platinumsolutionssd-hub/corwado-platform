"""
Geometry helpers for the deforestation fact layer: geodesic plot area and the
Point -> circular-footprint buffer. Pure shapely + pyproj — no Earth Engine, no
scheme/crop knowledge — so this is unit-testable offline.

Units: area in hectares, radius in metres, coordinates lon/lat degrees (WGS84).
"""
from __future__ import annotations

import math

from pyproj import Geod
from shapely.geometry import Polygon, shape

_GEOD = Geod(ellps="WGS84")


def geodesic_area_ha(geom) -> float:
    """Geodesic area of a shapely (Multi)Polygon, in hectares (WGS84 ellipsoid)."""
    area_m2, _ = _GEOD.geometry_area_perimeter(geom)
    return abs(area_m2) / 1e4


def circle_footprint(lon: float, lat: float, area_ha: float, n: int = 72) -> Polygon:
    """A geodesic regular n-gon whose area equals `area_ha`, centred on lon/lat.

    EUDR gives a Point plot a declared Area but mandates no footprint shape; a
    circle is the neutral choice (labelled EXPERT ASSUMPTION). The radius is solved
    so the n-gon's own area equals the declared Area exactly (not the circumscribed
    circle's), so geodesic_area_ha(result) ~= area_ha to rounding.
    """
    if area_ha <= 0:
        raise ValueError(f"point plot needs a positive Area (got {area_ha})")
    # area of a regular n-gon = 0.5 * n * r^2 * sin(2pi/n)  ->  solve for r
    r = math.sqrt(2.0 * area_ha * 1e4 / (n * math.sin(2.0 * math.pi / n)))  # metres
    coords = []
    for i in range(n):
        az = 360.0 * i / n
        f_lon, f_lat, _ = _GEOD.fwd(lon, lat, az, r)
        coords.append((f_lon, f_lat))
    coords.append(coords[0])
    return Polygon(coords)


def footprint_for(geometry: dict, area_ha):
    """Return (shapely_polygon, kind) for a GeoJSON geometry dict.

    Polygon / MultiPolygon -> used as-is (kind 'polygon').
    Point -> circular buffer of `area_ha`        (kind 'point-buffer').
    """
    gtype = geometry.get("type")
    if gtype in ("Polygon", "MultiPolygon"):
        return shape(geometry), "polygon"
    if gtype == "Point":
        if area_ha is None:
            raise ValueError("a Point plot requires an Area to build a footprint")
        lon, lat = geometry["coordinates"][:2]
        return circle_footprint(float(lon), float(lat), float(area_ha)), "point-buffer"
    raise ValueError(f"unsupported geometry type for a plot footprint: {gtype!r}")
