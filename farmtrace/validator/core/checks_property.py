"""Property checks (14-18) per feature. Scheme-agnostic — required properties,
casing, country standard, Area property and threshold all come from the ruleset."""
from __future__ import annotations

from decimal import Decimal

from . import codes, geometry as geo
from .emit import finding
from .geojson_util import (feature_identifier, geom_type, is_point, is_polygon,
                           polygon_rings)
from .models import FeatureRef
from .ruleset import Applies


def _is_number(v) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _applicable(spec, is_pt, is_poly) -> bool:
    if spec.applies is Applies.ALL:
        return True
    if spec.applies is Applies.POINT:
        return is_pt
    if spec.applies is Applies.POLYGON:
        return is_poly
    return False


def run(features, ruleset, mode) -> list:
    out = []
    src = f"{ruleset.name} ruleset"
    name_prop = ruleset.required_properties[0].name
    area_prop = ruleset.area_property
    country_prop = ruleset.country_property

    for i, feat in enumerate(features):
        ref = FeatureRef(i, feature_identifier(feat, name_prop))
        props = feat.get("properties") or {}
        gtype = geom_type(feat)
        is_pt, is_poly = is_point(gtype), is_polygon(gtype)

        # check 14 — required/recommended properties, EXACT casing
        for spec in ruleset.required_properties:
            if not _applicable(spec, is_pt, is_poly):
                continue
            if spec.name in props:
                value = props[spec.name]
                # check 16 — Area present but non-numeric (classic Excel string)
                if spec.name == area_prop and not _is_number(value):
                    out.append(finding(codes.PROP_AREA_NOT_NUMBER,
                                       f"'{spec.name}' is written as text (\"{value}\"), not a number — export it as a "
                                       f"numeric value.",
                                       feature_ref=ref, offending_value=value,
                                       checked=f"{spec.name} is a JSON number", found=f"string \"{value}\"",
                                       expected="a number", rule="Area must be numeric", source=src))
                continue
            # not present under the exact name — is it a casing variant?
            variant = next((k for k in props if k.lower() == spec.name.lower()), None)
            if variant is not None:
                out.append(finding(codes.PROP_CASING_MISMATCH,
                                   f"The property is spelled '{variant}' but must be exactly '{spec.name}' "
                                   f"(capitalisation matters).",
                                   feature_ref=ref, offending_value=variant,
                                   checked=f"property named exactly '{spec.name}'", found=variant,
                                   expected=spec.name, rule="required property exact casing", source=src))
            elif spec.name == area_prop and is_pt:
                out.append(finding(codes.PROP_POINT_AREA_MISSING,
                                   f"This point plot has no '{spec.name}'. Without it the target system assumes "
                                   f"{ruleset.default_point_area_ha} ha, which may be wrong — provide the real area.",
                                   feature_ref=ref, checked=f"point features carry '{spec.name}'", found="absent",
                                   expected="a numeric Area", rule="point features must declare Area", source=src))
            elif spec.required:
                out.append(finding(codes.PROP_MISSING,
                                   f"Required property '{spec.name}' is missing.",
                                   feature_ref=ref, checked=f"'{spec.name}' present", found="absent",
                                   expected="present", rule="required property", source=src))
            else:
                out.append(finding(codes.PROP_RECOMMENDED_MISSING,
                                   f"Recommended property '{spec.name}' is missing.",
                                   feature_ref=ref, checked=f"'{spec.name}' present (recommended)", found="absent",
                                   expected="present", rule="recommended property", source=src))

        # check 15 — country code standard (ISO2), only when present as a string
        cval = props.get(country_prop)
        if isinstance(cval, str):
            if cval in ruleset.iso2_codes:
                pass
            elif cval in ruleset.iso3_to_iso2:
                iso2 = ruleset.iso3_to_iso2[cval]
                out.append(finding(codes.PROP_COUNTRY_IS_ISO3,
                                   f"'{country_prop}' is '{cval}', a 3-letter (ISO3) code; use the 2-letter (ISO2) "
                                   f"code '{iso2}' instead.",
                                   feature_ref=ref, offending_value=cval,
                                   checked=f"{country_prop} is {ruleset.country_code_standard}", found=cval,
                                   expected=iso2, rule="country code must be ISO 3166-1 alpha-2", source=src))
            else:
                out.append(finding(codes.PROP_COUNTRY_NOT_ISO2,
                                   f"'{country_prop}' is '{cval}', which is not a valid ISO 3166-1 alpha-2 code.",
                                   feature_ref=ref, offending_value=cval,
                                   checked=f"{country_prop} is a valid {ruleset.country_code_standard}", found=cval,
                                   expected="a valid ISO2 code", rule="country code must be ISO 3166-1 alpha-2", source=src))

        # checks 17 & 18 — Area/threshold semantics
        aval = props.get(area_prop)
        if is_pt and _is_number(aval):
            if float(aval) >= ruleset.polygon_threshold_ha:
                out.append(finding(codes.THRESH_POINT_AREA_TOO_LARGE,
                                   f"This is a point with Area {float(aval)} ha, at or above the "
                                   f"{ruleset.polygon_threshold_ha} ha threshold — a plot that large must be drawn as a "
                                   f"polygon, not a point.",
                                   feature_ref=ref, offending_value=float(aval),
                                   checked=f"point Area < {ruleset.polygon_threshold_ha} ha", found=float(aval),
                                   expected=f"< {ruleset.polygon_threshold_ha} ha (or use a polygon)",
                                   rule="plots at/above the area threshold must be polygons", source=src))
        elif is_poly and _is_number(aval):
            computed = _polygon_area_ha(feat.get("geometry"))
            if computed > 0:
                divergence = abs(float(aval) - computed) / computed * 100
                if divergence > ruleset.area_divergence_pct:
                    out.append(finding(codes.PROP_POLYGON_AREA_INCONSISTENT,
                                       f"Declared Area {float(aval)} ha differs from the polygon's computed area "
                                       f"{computed:.2f} ha by {divergence:.0f}% (over the {ruleset.area_divergence_pct:.0f}% "
                                       f"tolerance) — check which is correct.",
                                       feature_ref=ref, offending_value=float(aval),
                                       checked=f"declared Area within {ruleset.area_divergence_pct}% of computed",
                                       found=f"{float(aval)} ha declared vs {computed:.2f} ha computed",
                                       expected=f"within {ruleset.area_divergence_pct}%",
                                       rule="declared vs computed polygon area (labelled assumption)", source=src))

    return out


def _polygon_area_ha(geometry: dict) -> float:
    try:
        return sum(geo.geodesic_area_ha(ext) for ext, _ in polygon_rings(geometry))
    except Exception:
        return 0.0
