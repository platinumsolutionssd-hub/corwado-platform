"""Cross-feature checks (19-20). Compares polygon plots pairwise for overlap and
same-producer near-duplicates. O(n^2) — fine at fixture/roster scale; a spatial
index is a later optimisation (logged, not silently assumed) for very large files.

The overlap sliver tolerance and the near-duplicate threshold are ruleset
parameters / labelled expert assumptions — no magic numbers here.
"""
from __future__ import annotations

from . import codes, geometry as geo
from .emit import finding
from .geojson_util import feature_identifier, geom_type, is_polygon
from .models import FeatureRef

_NEAR_DUPLICATE_OVERLAP = 0.90  # >=90% mutual overlap => "near-identical" (labelled assumption)


def run(features, ruleset, mode) -> list:
    out = []
    src = f"{ruleset.name} ruleset"
    name_prop = ruleset.required_properties[0].name
    sliver = ruleset.overlap_sliver_pct / 100.0

    polys = []  # (index, feature, shapely_shape, producer_name)
    for i, feat in enumerate(features):
        if not is_polygon(geom_type(feat)):
            continue
        try:
            shp = geo.to_shape(feat["geometry"])
            if not shp.is_valid:
                shp = shp.buffer(0)  # best-effort repair for overlap math
        except Exception:
            continue
        pname = (feat.get("properties") or {}).get(name_prop)
        polys.append((i, feat, shp, pname))

    for a in range(len(polys)):
        ia, fa, sa, na = polys[a]
        for b in range(a + 1, len(polys)):
            ib, fb, sb, nb = polys[b]
            overlap_ha, frac = geo.overlap_fraction_of_smaller(sa, sb)
            if frac <= sliver:
                continue
            # check 20 — same producer + near-identical geometry (likely double-entry)
            if na is not None and na == nb and frac >= _NEAR_DUPLICATE_OVERLAP:
                out.append(finding(codes.XFEAT_DUPLICATE_PRODUCER,
                                   f"Plots #{ia} and #{ib} share the producer '{na}' and near-identical geometry "
                                   f"({frac * 100:.0f}% overlap) — likely a double entry.",
                                   feature_ref=FeatureRef(ib, feature_identifier(fb, name_prop)),
                                   offending_value={"other_feature": ia, "overlap_pct": round(frac * 100, 1)},
                                   checked="no duplicate producer with near-identical geometry",
                                   found=f"{frac * 100:.0f}% overlap, same producer", expected="distinct plots",
                                   rule="duplicate producer + geometry (labelled assumption)", source=src))
            else:
                # check 19 — overlapping plots
                out.append(finding(codes.XFEAT_OVERLAP,
                                   f"Plots #{ia} and #{ib} overlap by {overlap_ha:.2f} ha "
                                   f"({frac * 100:.0f}% of the smaller plot).",
                                   feature_ref=FeatureRef(ib, feature_identifier(fb, name_prop)),
                                   offending_value={"other_feature": ia, "overlap_ha": round(overlap_ha, 3),
                                                    "overlap_pct": round(frac * 100, 1)},
                                   checked=f"plots overlap <= {ruleset.overlap_sliver_pct}% sliver tolerance",
                                   found=f"{frac * 100:.0f}% overlap", expected="no meaningful overlap",
                                   rule="overlapping plots (sliver tolerance is a labelled assumption)", source=src))
    return out
