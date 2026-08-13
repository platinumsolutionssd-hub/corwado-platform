"""
Stage 3 OFFLINE unit test — cutoff filter + determination + the config-only seam.
No Earth Engine. Facts are built via FakeProvider, so verdicts are exercised on
controlled forest-loss histograms (including the pre-cutoff boundary case that we
deliberately did NOT make a whole-parcel fixture).

Run (cwd = repo root):
    python farmtrace/deforestation/tests/test_ruleset.py
"""
import os
import sys
from dataclasses import replace
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from farmtrace.deforestation.core.facts import build_facts
from farmtrace.deforestation.core.provider import FakeProvider, RawReduction
from farmtrace.deforestation.core.ruleset import Determination, determine
from farmtrace.deforestation.rulesets.eudr import eudr_deforestation_ruleset

EUDR = eudr_deforestation_ruleset()
FAIL = 0

# A generic ~1 ha polygon; geometry is irrelevant here (FakeProvider ignores it).
POLY = {"type": "Polygon", "coordinates": [[
    [37.0000, -0.5000], [37.0010, -0.5000], [37.0010, -0.4990], [37.0000, -0.4990], [37.0000, -0.5000]]]}


def check(label, cond, detail=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAIL = 1


def result_for(forest_loss, ruleset=EUDR, forest_frac=0.9):
    raw = RawReduction(forest_2020_fraction=forest_frac, loss_area_by_year=dict(forest_loss),
                       forest_loss_area_by_year=dict(forest_loss), treecover2000_mean=80.0)
    facts = build_facts(POLY, None, FakeProvider(raw), identifier="t")
    return determine(facts, ruleset)


print("=" * 72)
print("Part 1 — cutoff filter (EUDR cutoff 2020-12-31 -> first post-cutoff year 2021)")

check("cutoff_lossyear == 21", EUDR.cutoff_lossyear == 21, str(EUDR.cutoff_lossyear))

# pre-cutoff clearing only (2007) -> compliant. This is the boundary case we did NOT
# build as a fixture; here it is, precisely.
r = result_for({2007: 2.0})
check("pre-cutoff loss (2007) only -> NO_DEFORESTATION", r.determination is Determination.NO_DEFORESTATION_DETECTED)
check("pre-cutoff loss -> compliant", r.compliant is True)
check("pre-cutoff loss -> post-cutoff area 0", r.post_cutoff_forest_loss_ha == 0.0)

# boundary: 2020 loss (lossyear 20) is PRE-cutoff -> excluded; 2021 is post -> included
check("2020 loss excluded (compliant)", result_for({2020: 1.0}).compliant is True)
r21 = result_for({2021: 1.0})
check("2021 loss included -> DEFORESTATION", r21.determination is Determination.DEFORESTATION_DETECTED)
check("2021 loss -> non-compliant", r21.compliant is False)

# mixed history: only the post-cutoff part counts
r = result_for({2007: 5.0, 2018: 0.5, 2024: 1.0})
check("mixed history -> only 2024 counts", r.post_cutoff_loss_years == {2024: 1.0}, str(r.post_cutoff_loss_years))
check("mixed history -> DEFORESTATION", r.determination is Determination.DEFORESTATION_DETECTED)

print("Part 2 — minimum-mapping-unit noise floor (EUDR 0.09 ha)")

# below the floor -> treated as sensor noise -> compliant, but surfaced in rationale
r = result_for({2024: 0.05})
check("0.05 ha post-cutoff (< 0.09) -> compliant (noise)", r.compliant is True)
check("  ...but exceeds_mmu False and area reported", r.exceeds_mmu is False and r.post_cutoff_forest_loss_ha == 0.05)
check("  ...rationale flags it as noise", "noise" in r.rationale.lower())
# above the floor -> deforestation
check("0.15 ha post-cutoff (> 0.09) -> non-compliant", result_for({2024: 0.15}).compliant is False)
# exactly at the floor is NOT exceeded (strict >)
check("exactly 0.09 ha -> compliant (strict >)", result_for({2024: 0.09}).compliant is True)

print("Part 3 — was_forest_2020 flag is informational, does NOT gate the verdict")
# non-forest plot (fraction 0.0) with post-cutoff forest-loss still gets a verdict on the loss
r = result_for({2024: 1.0}, forest_frac=0.0)
check("low forest fraction -> was_forest_2020 False", r.was_forest_2020 is False)
check("  ...verdict still driven by loss (DEFORESTATION)", r.determination is Determination.DEFORESTATION_DETECTED)
r = result_for({}, forest_frac=0.95)
check("high forest fraction, no loss -> was_forest_2020 True + compliant",
      r.was_forest_2020 is True and r.compliant is True)

print("Part 4 — SEAM: a second scheme via config alone changes the verdict, no core change")
# scheme with an EARLIER cutoff (2019-12-31 -> first post year 2020): now 2020 loss counts.
scheme_2019 = replace(EUDR, name="scheme-2019", cutoff_date=date(2019, 12, 31)).validate()
r_eudr = result_for({2020: 1.0}, ruleset=EUDR)
r_2019 = result_for({2020: 1.0}, ruleset=scheme_2019)
check("EUDR (cutoff 2020): 2020 loss -> compliant", r_eudr.compliant is True)
check("scheme-2019 (cutoff 2019): SAME 2020 loss -> non-compliant", r_2019.compliant is False)
check("=> seam real: same facts, different ruleset, different verdict",
      r_eudr.compliant != r_2019.compliant)
# a stricter MMU also flips a small clearing purely by config
scheme_strict = replace(EUDR, name="scheme-strict", min_mapping_unit_ha=0.0).validate()
check("scheme-strict (MMU 0): 0.05 ha loss -> non-compliant",
      result_for({2024: 0.05}, ruleset=scheme_strict).compliant is False)

print("Part 5 — result serialises")
import json
d = result_for({2024: 1.0}).to_dict()
check("to_dict JSON-serialisable + carries facts", json.dumps(d) is not None and "facts" in d)

print("=" * 72)
print("ALL RULESET/DETERMINATION UNIT TESTS PASS" if not FAIL else ">>> SOME TESTS FAILED")
sys.exit(FAIL)
