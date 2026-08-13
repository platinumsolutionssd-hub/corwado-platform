"""
EUDR deforestation rule set — the first concrete scheme for the deforestation
baseline core. Pure configuration; it adds no logic. A different scheme is another
module like this one, with zero changes to core/.

SOURCES (see core/ruleset.py for the per-field rationale):
  * cutoff_date 2020-12-31            : Regulation (EU) 2023/1115 (EUDR), Art. 2.
  * min_mapping_unit_ha 0.09          : EXPERT ASSUMPTION — ~one 30 m Hansen pixel
                                        (900 m^2). EUDR has no de-minimis; this is a
                                        sensor-noise floor only.
  * forest_baseline_fraction 0.10     : EXPERT ASSUMPTION — informational "was forest
                                        in 2020" flag; does NOT gate the verdict.
"""
from __future__ import annotations

from datetime import date

from ..core.ruleset import DeforestationRuleSet


def eudr_deforestation_ruleset() -> DeforestationRuleSet:
    return DeforestationRuleSet(
        name="EUDR",
        cutoff_date=date(2020, 12, 31),
        min_mapping_unit_ha=0.09,
        forest_baseline_fraction=0.10,
    ).validate()
