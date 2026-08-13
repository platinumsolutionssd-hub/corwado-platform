"""
CLI for the deforestation baseline check.

    $env:GEE_PROJECT="..."; python -m farmtrace.deforestation.cli PLOTS.geojson [--ruleset eudr] [--format human|json]

Unlike the validator CLI, this runs LIVE Earth Engine reductions (the verdict needs
GFC2020 + Hansen), so it requires an EE project (--project or GEE_PROJECT) with auth
already set up. Exit code: 0 if every plot is deforestation-free, 1 if any plot is
flagged, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .core.facts import build_facts
from .core.report import render_markdown
from .core.ruleset import determine
from .rulesets.eudr import eudr_deforestation_ruleset

RULESETS = {
    "eudr": eudr_deforestation_ruleset,
}


def _identifier(props: dict, index: int) -> str:
    pid = props.get("plot_id")
    name = props.get("ProducerName")
    country = props.get("ProducerCountry")
    who = (f"{name} ({country})" if country else name) if name else None
    parts = [str(p) for p in (pid, who) if p]
    return " — ".join(parts) if parts else f"feature-{index}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="farmtrace-deforestation",
        description="Check plot geometries for post-cutoff deforestation (live Earth Engine).")
    parser.add_argument("path", help="GeoJSON FeatureCollection of plots")
    parser.add_argument("--ruleset", default="eudr", choices=sorted(RULESETS),
                        help="certification ruleset (default: eudr)")
    parser.add_argument("--format", dest="fmt", default="human", choices=["human", "json"],
                        help="output format (default: human)")
    parser.add_argument("--project", default=os.environ.get("GEE_PROJECT", ""),
                        help="Earth Engine project id (or set GEE_PROJECT). Required — this tool "
                             "runs live GEE reductions.")
    args = parser.parse_args(argv)  # argparse exits 2 on a usage error

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if not args.project:
        parser.error("no Earth Engine project: pass --project or set GEE_PROJECT "
                     "(this tool needs live GEE).")  # exits 2

    ruleset = RULESETS[args.ruleset]()
    from .core.provider_gee import GeeProvider  # imports ee — only when actually running
    provider = GeeProvider(project=args.project)

    with open(args.path, encoding="utf-8") as fh:
        fc = json.load(fh)

    results = []
    for i, feat in enumerate(fc.get("features", [])):
        props = feat.get("properties", {}) or {}
        facts = build_facts(feat["geometry"], props.get("Area"), provider,
                            identifier=_identifier(props, i))
        results.append(determine(facts, ruleset))

    if args.fmt == "json":
        print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
    else:
        print(render_markdown(results, ruleset, os.path.basename(args.path)))

    return 0 if all(r.compliant for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
