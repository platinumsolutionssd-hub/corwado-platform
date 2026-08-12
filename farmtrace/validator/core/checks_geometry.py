"""Geometry checks (5-13) per feature. Scheme-agnostic — allowed types, precision
bounds and country bboxes all come from the ruleset."""
from __future__ import annotations

from decimal import Decimal

from . import codes, geometry as geo
from .emit import finding
from .geojson_util import (POLYGON_TYPES, feature_identifier, geom_type,
                           geometry_positions, is_point, is_polygon, polygon_rings)
from .models import FeatureRef, Severity
from .ruleset import GeometryDisposition


def _decimals(v) -> int:
    """Number of decimal places. Reliable for Decimal (file input preserves
    trailing zeros); best-effort for float (object input already lost them)."""
    if isinstance(v, Decimal):
        exp = v.as_tuple().exponent
        return -exp if isinstance(exp, int) and exp < 0 else 0
    s = repr(float(v))
    if "e" in s or "E" in s:
        return 17  # scientific notation implies very small/large — treat as high precision
    return len(s.split(".")[1]) if "." in s else 0


def run(features, ruleset, mode) -> list:
    out = []
    src = f"{ruleset.name} ruleset"
    name_prop = ruleset.required_properties[0].name

    for i, feat in enumerate(features):
        ref = FeatureRef(i, feature_identifier(feat, name_prop))
        geometry = feat.get("geometry")
        gtype = geom_type(feat)

        # GEOM_NULL — no geometry at all
        if geometry is None or gtype is None:
            out.append(finding(codes.GEOM_NULL, "This plot has no geometry — nothing to check or export.",
                               feature_ref=ref, checked="geometry is present", found="null",
                               expected="a Point/MultiPoint/Polygon/MultiPolygon", rule="every plot needs geometry", source=src))
            continue

        # check 5 — geometry type disposition
        disp = ruleset.disposition(gtype)
        if disp is GeometryDisposition.REJECTED:
            out.append(finding(codes.GEOM_TYPE_REJECTED,
                               f"Geometry type '{gtype}' is not accepted — a plot must be a point or a polygon.",
                               feature_ref=ref, offending_value=gtype, checked="geometry type is permitted",
                               found=gtype, expected="Point/MultiPoint/Polygon/MultiPolygon",
                               rule="permitted geometry types", source=src))
            continue  # the type is the fault; skip further geometry checks
        if disp is GeometryDisposition.DISCOURAGED:
            out.append(finding(codes.GEOM_TYPE_DISCOURAGED,
                               f"Geometry type '{gtype}' is discouraged — prefer a plain Point or Polygon.",
                               feature_ref=ref, offending_value=gtype, checked="geometry type is preferred",
                               found=gtype, expected="Point/MultiPoint/Polygon/MultiPolygon",
                               rule="discouraged geometry types", source=src))
            # still worth range-checking, but skip polygon-structure checks

        positions = list(geometry_positions(geometry))

        # check 7 — coordinate range (hard). Emit once for the first offender.
        out_of_range = False
        for pos in positions:
            lon, lat = float(pos[0]), float(pos[1])
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                out.append(finding(codes.GEOM_COORD_OUT_OF_RANGE,
                                   f"A coordinate is outside the valid range (lon {lon}, lat {lat}).",
                                   feature_ref=ref, offending_value=[lon, lat],
                                   checked="lon in [-180,180], lat in [-90,90]", found=[lon, lat],
                                   expected="lon in [-180,180], lat in [-90,90]", rule="valid coordinate range", source=src))
                out_of_range = True
                break

        # check 6 — coordinate-order (swap) heuristic; skip if out of range
        if not out_of_range and positions:
            _swap_check(out, ref, feat, positions[0], ruleset, src)

        # check 13 — precision
        _precision_check(out, ref, positions, ruleset, src)

        # polygon structure checks (8-12) + antimeridian
        if is_polygon(gtype):
            _polygon_checks(out, ref, geometry, ruleset, src)

    return out


def _swap_check(out, ref, feat, first_pos, ruleset, src):
    props = feat.get("properties") or {}
    iso2 = props.get(ruleset.country_property)
    if not isinstance(iso2, str):
        return
    bbox = ruleset.bbox_for(iso2)
    if not bbox:  # no bbox for this country -> can't run the heuristic (documented skip)
        return
    lon, lat = float(first_pos[0]), float(first_pos[1])
    if geo.point_in_bbox(lon, lat, bbox):
        return
    if geo.point_in_bbox(lat, lon, bbox):  # un-swapping lands inside the declared country
        out.append(finding(codes.GEOM_COORDS_LIKELY_SWAPPED,
                           f"Coordinates appear reversed: as written this plot is outside {iso2}, but swapping "
                           f"longitude and latitude places it inside {iso2} — almost certainly a lon/lat swap.",
                           feature_ref=ref, offending_value=[lon, lat], severity=Severity.ERROR,
                           checked=f"coordinates fall within the {iso2} bounding box", found=[lon, lat],
                           expected=f"a point inside {iso2}", rule="coordinate order [lon, lat] vs declared country", source=src))
    else:
        out.append(finding(codes.GEOM_COORDS_LIKELY_SWAPPED,
                           f"Coordinates fall outside {iso2} and swapping longitude/latitude does not fix it — "
                           f"the plot may be mislocated or the coordinates possibly swapped.",
                           feature_ref=ref, offending_value=[lon, lat],
                           checked=f"coordinates fall within the {iso2} bounding box", found=[lon, lat],
                           expected=f"a point inside {iso2}", rule="coordinate order [lon, lat] vs declared country", source=src))


def _precision_check(out, ref, positions, ruleset, src):
    min_d = max((_decimals(v) for pos in positions for v in pos[:2]), default=0)
    max_d = max((_decimals(v) for pos in positions for v in pos[:2]), default=0)
    if min_d < ruleset.min_precision_decimals:
        out.append(finding(codes.GEOM_PRECISION_INSUFFICIENT,
                           f"Coordinates carry only ~{min_d} decimal places; at least "
                           f"{ruleset.min_precision_decimals} are expected (this can be a false alarm for "
                           f"legitimately round coordinates — review).",
                           feature_ref=ref, offending_value=min_d,
                           checked=f"coordinate precision >= {ruleset.min_precision_decimals} decimals",
                           found=min_d, expected=f">= {ruleset.min_precision_decimals}",
                           rule="minimum coordinate precision", source=src))
    if max_d > ruleset.excess_precision_decimals:
        out.append(finding(codes.GEOM_PRECISION_EXCESS,
                           f"Coordinates carry {max_d} decimal places — more than is meaningful; excess digits imply "
                           f"false precision.",
                           feature_ref=ref, offending_value=max_d,
                           checked=f"coordinate precision <= {ruleset.excess_precision_decimals} decimals",
                           found=max_d, expected=f"<= {ruleset.excess_precision_decimals}",
                           rule="excess coordinate precision (labelled assumption)", source=src))


def _polygon_checks(out, ref, geometry, ruleset, src):
    for exterior, interiors in polygon_rings(geometry):
        # check 9 — too few points
        if len(exterior) < 4:
            out.append(finding(codes.GEOM_RING_TOO_FEW_POINTS,
                               f"A polygon ring has only {len(exterior)} points; a valid ring needs at least 4.",
                               feature_ref=ref, offending_value=len(exterior),
                               checked="ring has >= 4 coordinate pairs", found=len(exterior),
                               expected=">= 4", rule="polygon ring minimum points", source=src))
        # check 8 — closure
        elif not geo.ring_is_closed(exterior):
            out.append(finding(codes.GEOM_RING_NOT_CLOSED,
                               "A polygon ring is not closed — its first and last points differ.",
                               feature_ref=ref, checked="ring first point == last point",
                               found="open", expected="closed", rule="polygon rings must close", source=src))

        # check 11 — interior rings (holes)
        if interiors:
            out.append(finding(codes.GEOM_INTERIOR_RING,
                               f"A polygon has {len(interiors)} interior ring(s) (holes), which are not allowed.",
                               feature_ref=ref, offending_value=len(interiors),
                               checked="polygon has no interior rings", found=len(interiors),
                               expected="0 interior rings", rule="no holes in plot polygons", source=src))

        # check 12 — duplicate consecutive coordinates (after rounding to min precision)
        nd = ruleset.min_precision_decimals
        rounded = [(round(float(c[0]), nd), round(float(c[1]), nd)) for c in exterior]
        if any(rounded[k] == rounded[k - 1] for k in range(1, len(rounded))):
            out.append(finding(codes.GEOM_DUPLICATE_CONSECUTIVE,
                               "A polygon ring has duplicate consecutive coordinates.",
                               feature_ref=ref, checked="no duplicate consecutive coordinates",
                               found="duplicate present", expected="no duplicates", rule="no duplicate vertices", source=src))

        # antimeridian (edge behaviour — documented, never crash)
        if geo.crosses_antimeridian(exterior):
            out.append(finding(codes.GEOM_ANTIMERIDIAN,
                               "This polygon crosses the antimeridian (+/-180 longitude); area and overlap results "
                               "for it are approximate.",
                               feature_ref=ref, checked="geometry does not cross the antimeridian",
                               found="crosses +/-180", expected="does not cross", rule="antimeridian handling", source=src))

        # check 10 — self-intersection (only meaningful on a closed, >=4-point ring)
        if len(exterior) >= 4 and geo.ring_is_closed(exterior):
            try:
                shp = geo.to_shape({"type": "Polygon", "coordinates": [exterior]})
                bad, point = geo.self_intersection(shp)
            except Exception:
                bad, point = False, None
            if bad:
                where = f" near {point}" if point else ""
                out.append(finding(codes.GEOM_SELF_INTERSECTION,
                                   f"This polygon crosses itself{where} (a bow-tie or figure-eight shape).",
                                   feature_ref=ref, offending_value=point,
                                   checked="polygon does not self-intersect", found=f"self-intersects{where}",
                                   expected="a simple, non-self-intersecting ring", rule="no self-intersection", source=src))
