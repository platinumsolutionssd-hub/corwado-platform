"""File-level checks (2-4; check 1 is in the loader). Scheme-agnostic: every
threshold comes from the ruleset."""
from __future__ import annotations

from . import codes
from .emit import finding
from .geojson_util import feature_identifier
from .models import FeatureRef, FileType


def run(features, ruleset, mode, payload_mb) -> list:
    out = []
    src = f"{ruleset.name} ruleset"

    if len(features) == 0:
        out.append(finding(codes.FILE_EMPTY_COLLECTION,
                           "The file contains no plots (empty FeatureCollection).",
                           checked="feature count > 0", found=0, expected=">= 1",
                           rule="a submission must contain at least one plot", source=src))

    # check 2 — payload size
    if payload_mb > ruleset.max_payload_mb:
        out.append(finding(codes.FILE_PAYLOAD_EXCEEDED,
                           f"The file is {payload_mb:.1f} MB, over the {ruleset.max_payload_mb:.0f} MB limit — "
                           f"split it into smaller batches before submitting.",
                           offending_value=round(payload_mb, 2),
                           checked="payload <= max_payload_mb", found=round(payload_mb, 2),
                           expected=f"<= {ruleset.max_payload_mb} MB", rule="payload size limit", source=src))
    elif payload_mb >= ruleset.payload_warn_mb:
        out.append(finding(codes.FILE_PAYLOAD_WARN,
                           f"The file is {payload_mb:.1f} MB, approaching the {ruleset.max_payload_mb:.0f} MB limit — "
                           f"consider splitting into smaller batches.",
                           offending_value=round(payload_mb, 2),
                           checked="payload < payload_warn_mb", found=round(payload_mb, 2),
                           expected=f"< {ruleset.payload_warn_mb} MB", rule="payload size soft limit", source=src))

    # check 3 — plot count
    n = len(features)
    if n > ruleset.max_plots:
        out.append(finding(codes.FILE_PLOT_COUNT_EXCEEDED,
                           f"The file has {n} plots, over the {ruleset.max_plots} limit — split into smaller batches.",
                           offending_value=n, checked="plot count <= max_plots", found=n,
                           expected=f"<= {ruleset.max_plots}", rule="plot count limit", source=src))
    elif n >= ruleset.plots_warn:
        out.append(finding(codes.FILE_PLOT_COUNT_WARN,
                           f"The file has {n} plots, approaching the {ruleset.max_plots} limit.",
                           offending_value=n, checked="plot count < plots_warn", found=n,
                           expected=f"< {ruleset.plots_warn}", rule="plot count soft limit", source=src))

    # check 4 — Type II requires ProducerCountry on every feature
    if mode == FileType.TYPE_II:
        cprop = ruleset.country_property
        name_prop = ruleset.required_properties[0].name
        for i, feat in enumerate(features):
            props = feat.get("properties") or {}
            if cprop not in props:
                out.append(finding(codes.FILE_TYPEII_COUNTRY_MISSING,
                                   f"This is a Type II (multi-producer) file, so every plot must name its "
                                   f"{cprop}, and this one does not.",
                                   feature_ref=FeatureRef(i, feature_identifier(feat, name_prop)),
                                   checked=f"{cprop} present (Type II)", found="absent", expected="present",
                                   rule="Type II files require ProducerCountry per feature", source=src))
    return out
