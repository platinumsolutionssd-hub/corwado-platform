"""Small, dependency-free helpers for walking GeoJSON features/coordinates.
Shared by the check modules so each stays about *rules*, not traversal."""
from __future__ import annotations

from decimal import Decimal
from typing import Iterator, Optional

_NUMS = (int, float, Decimal)

POINT_TYPES = ("Point", "MultiPoint")
POLYGON_TYPES = ("Polygon", "MultiPolygon")


def geom_type(feature: dict) -> Optional[str]:
    g = feature.get("geometry")
    return g.get("type") if isinstance(g, dict) else None


def is_point(gtype: Optional[str]) -> bool:
    return gtype in POINT_TYPES


def is_polygon(gtype: Optional[str]) -> bool:
    return gtype in POLYGON_TYPES


def iter_positions(coords) -> Iterator[list]:
    """Yield every [lon, lat, ...] position from an arbitrarily-nested
    coordinates array."""
    if not isinstance(coords, (list, tuple)) or not coords:
        return
    if isinstance(coords[0], _NUMS):
        yield coords
    else:
        for c in coords:
            yield from iter_positions(c)


def geometry_positions(geometry: dict) -> Iterator[list]:
    """All positions in a geometry, including a GeometryCollection's members."""
    if not isinstance(geometry, dict):
        return
    if geometry.get("type") == "GeometryCollection":
        for g in geometry.get("geometries", []) or []:
            yield from geometry_positions(g)
    else:
        yield from iter_positions(geometry.get("coordinates"))


def polygon_rings(geometry: dict):
    """List of (exterior_ring, [interior_rings]) for a Polygon/MultiPolygon."""
    t = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if t == "Polygon":
        return [(coords[0], list(coords[1:]))] if coords else []
    if t == "MultiPolygon":
        return [(poly[0], list(poly[1:])) for poly in coords if poly]
    return []


def feature_identifier(feature: dict, name_property: str) -> dict:
    """Best-effort identifier for a finding — the producer name if present."""
    props = feature.get("properties") or {}
    if name_property in props:
        return {name_property: props[name_property]}
    # fall back to any case-variant of the name property
    for k, v in props.items():
        if k.lower() == name_property.lower():
            return {k: v}
    return {}
