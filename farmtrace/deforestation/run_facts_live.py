"""
LIVE end-to-end verification — run the deforestation pipeline (fact layer + EUDR
determination) over the real fixtures against live Earth Engine, and print facts +
verdict per plot for checking against tests/fixtures/README.md.

Counterpart to the offline unit tests (test_facts.py proves fact assembly,
test_ruleset.py proves the determination logic); this proves the GEE wiring.

RUN (cwd = repo root):
    $env:GEE_PROJECT="your-project-id"; python farmtrace/deforestation/run_facts_live.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from farmtrace.deforestation.core.facts import build_facts
from farmtrace.deforestation.core.ruleset import determine
from farmtrace.deforestation.rulesets.eudr import eudr_deforestation_ruleset

FIX = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "parcels.geojson")

EXPECT = {
    "intact-forest-kakamega": "compliant (forest, no post-2020 loss)",
    "deforestation-post2020-mau": "NON-compliant (post-2020 forest loss) — the case",
    "savanna-cropland-wau": "compliant (not forest, no loss)",
    "arid-nonforest-turkana": "compliant (not forest, no loss)",
    "deforestation-post2020-mau-point": "NON-compliant (point plot, post-2020 loss)",
}


def main() -> int:
    project = os.environ.get("GEE_PROJECT", "")
    if not project:
        print('ERROR: set GEE_PROJECT, e.g.  $env:GEE_PROJECT="your-project-id"')
        return 2
    from farmtrace.deforestation.core.provider_gee import GeeProvider  # imports ee
    provider = GeeProvider(project=project)
    ruleset = eudr_deforestation_ruleset()
    print(f"Earth Engine initialised on project: {project}   |   ruleset: {ruleset.name}\n")

    fc = json.load(open(FIX))
    for feat in fc["features"]:
        p = feat["properties"]
        pid = p["plot_id"]
        facts = build_facts(feat["geometry"], p.get("Area"), provider, identifier=pid)
        res = determine(facts, ruleset)

        all_loss = {y: round(a, 4) for y, a in sorted(facts.loss_area_by_year.items()) if y >= 2021}
        forest_loss = {y: round(a, 4) for y, a in sorted(facts.forest_loss_area_by_year.items()) if y >= 2021}
        flag = "NON-COMPLIANT" if not res.compliant else "compliant"
        print(f"● {pid}   [{facts.footprint_kind}]  {p.get('ProducerName')} / {p.get('ProducerCountry')}")
        print(f"    forest_2020_fraction     : {facts.forest_2020_fraction:.4f}   was_forest_2020={res.was_forest_2020}")
        print(f"    post-2020 ALL tree loss  : {all_loss if all_loss else 'none'}")
        print(f"    post-2020 FOREST loss    : {forest_loss if forest_loss else 'none'}   (verdict runs on this)")
        print(f"    -> {res.determination.value}  [{flag}]")
        print(f"       {res.rationale}")
        print(f"       EXPECT: {EXPECT.get(pid, '?')}")
        print()

    print("Confirm: Kakamega/Wau/Turkana compliant; both Mau plots NON-compliant.")
    print("Watch the ALL-tree-loss vs FOREST-loss columns — where they differ, the")
    print("verdict correctly uses forest-loss (non-forest tree loss excluded).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
