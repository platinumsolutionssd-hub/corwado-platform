"""
Stage 2 LIVE verification — run the deforestation fact layer over the real
fixtures against live Earth Engine, and print the facts per plot so they can be
checked against tests/fixtures/README.md's expected determinations.

This is the data-integration counterpart to the offline unit test
(tests/test_facts.py): the unit test proves the LOGIC, this proves the GEE wiring.

RUN (cwd = repo root):
    $env:GEE_PROJECT="your-project-id"; python farmtrace/deforestation/run_facts_live.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from farmtrace.deforestation.core.facts import build_facts

FIX = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "parcels.geojson")

# Expected determination per plot (from the fixtures README) — for eyeball checking.
EXPECT = {
    "intact-forest-kakamega": "forest baseline, NO post-2020 loss",
    "deforestation-post2020-mau": "forest baseline, POST-2020 loss present (the case)",
    "savanna-cropland-wau": "NOT forest baseline, no loss",
    "arid-nonforest-turkana": "NOT forest baseline, no loss",
    "deforestation-post2020-mau-point": "point plot, POST-2020 loss present",
}


def main() -> int:
    project = os.environ.get("GEE_PROJECT", "")
    if not project:
        print('ERROR: set GEE_PROJECT, e.g.  $env:GEE_PROJECT="your-project-id"')
        return 2
    from farmtrace.deforestation.core.provider_gee import GeeProvider  # imports ee
    provider = GeeProvider(project=project)
    print(f"Earth Engine initialised on project: {project}\n")

    fc = json.load(open(FIX))
    for feat in fc["features"]:
        p = feat["properties"]
        pid = p["plot_id"]
        facts = build_facts(feat["geometry"], p.get("Area"), provider, identifier=pid)
        loss = {y: round(a, 4) for y, a in sorted(facts.loss_area_by_year.items())}
        post2020 = {y: a for y, a in loss.items() if y >= 2021}
        print(f"● {pid}   [{facts.footprint_kind}]  {p.get('ProducerName')} / {p.get('ProducerCountry')}")
        print(f"    plot_area_ha         : {facts.plot_area_ha:.4f}")
        print(f"    forest_2020_fraction : {facts.forest_2020_fraction:.4f}  "
              f"(forest_2020_area_ha {facts.forest_2020_area_ha:.4f})")
        print(f"    treecover2000_mean   : {facts.treecover2000_mean:.2f}")
        print(f"    loss_area_by_year    : {loss if loss else '{}'}")
        print(f"    post-2020 loss (>=21): {post2020 if post2020 else 'none'}")
        print(f"    EXPECT               : {EXPECT.get(pid, '?')}")
        print()

    print("Check each plot's facts against tests/fixtures/README.md. Two things to")
    print("confirm: (1) forest_2020_fraction is high for Kakamega/Mau, ~0 for")
    print("Wau/Turkana; (2) post-2020 loss is present ONLY for the two Mau plots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
