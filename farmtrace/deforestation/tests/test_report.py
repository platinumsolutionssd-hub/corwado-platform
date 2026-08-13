"""
Stage 4 OFFLINE unit test — the report renderer's disclosure branches. No Earth
Engine. Asserts the three things that must always hold in the human report:
flagged plots are detailed, and a "deforestation-free" plot is NEVER shown as clean
when a signal was filtered (MMU sub-floor OR non-forest tree loss).

Run (cwd = repo root):
    python farmtrace/deforestation/tests/test_report.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from farmtrace.deforestation.core.facts import build_facts
from farmtrace.deforestation.core.provider import FakeProvider, RawReduction
from farmtrace.deforestation.core.report import render_markdown
from farmtrace.deforestation.core.ruleset import determine
from farmtrace.deforestation.rulesets.eudr import eudr_deforestation_ruleset

EUDR = eudr_deforestation_ruleset()
POLY = {"type": "Polygon", "coordinates": [[
    [37.0, -0.5], [37.0018, -0.5], [37.0018, -0.4982], [37.0, -0.4982], [37.0, -0.5]]]}
FAIL = 0


def check(label, cond, detail=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAIL = 1


def result(ident, forest_frac, all_loss, forest_loss):
    raw = RawReduction(forest_frac, dict(all_loss), dict(forest_loss), 50.0)
    return determine(build_facts(POLY, None, FakeProvider(raw), identifier=ident), EUDR)


# one of each class
flagged = result("flag-mau", 0.83, {2024: 1.0}, {2024: 1.0})            # non-compliant
subfloor = result("subfloor", 0.9, {2024: 0.05}, {2024: 0.05})          # compliant, < MMU
nonforest = result("wau-div", 0.10, {2023: 0.84}, {})                   # compliant, non-forest loss
clean = result("kakamega", 1.0, {}, {})                                 # compliant, truly clean

md = render_markdown([flagged, subfloor, nonforest, clean], EUDR, "test.geojson")

print("=" * 72)
check("header counts: 1 flagged, 3 free", "**Deforestation-free:** 3" in md and "**Flagged:** 1" in md)
check("flagged plot detailed under its section",
      "## Plots that cannot be submitted as deforestation-free" in md and "flag-mau" in md)
check("flagged plot states area + years", "1.00 ha" in md and "in 2024" in md)
check("forest-baseline sentence carries fraction + threshold + consequence",
      "83% of this plot was forest at the 2020 baseline (the EUDR check applies where this is at least 10%)" in md)

# disclosure: sub-floor MMU note
check("sub-floor plot disclosed (not shown as clean)",
      "subfloor" in md and "below the 0.09 ha noise floor" in md and "imagery review recommended" in md)
# disclosure: non-forest tree loss excluded
check("non-forest tree loss disclosed",
      "0.84 ha of post-2020 tree loss on land that was NOT forest" in md and "excluded as not EUDR deforestation" in md)
# truly clean plot
check("clean plot says no loss detected",
      "**kakamega:** no post-2020 tree loss detected." in md)

# audit footer names every verdict-shaping parameter
for token in ["JRC Global Forest Cover 2020", "Hansen", "Regulation (EU) 2023/1115",
              "Minimum-mapping-unit noise floor:** 0.09 ha", "Forest-baseline threshold:** 10%",
              "circular buffer of the declared Area"]:
    check(f"audit footer names: {token[:40]}", token in md)

print("=" * 72)
print("ALL REPORT UNIT TESTS PASS" if not FAIL else ">>> SOME TESTS FAILED")
sys.exit(FAIL)
