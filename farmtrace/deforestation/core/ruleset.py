"""
Stage 3 — the certification ruleset + determination for the deforestation baseline.

Pure configuration + a small determination function that consumes DeforestationFacts
(Stage 2) and produces a bounded, sourced verdict. Same seam as the validator: the
scheme's numbers live here; the fact layer and geometry know nothing about EUDR. A
different scheme = another RuleSet instance, zero core change.

FIREWALL: the verdict describes the LAND / production ("post-2020 forest loss on
this parcel"), never the borrower. It is a regulatory determination about the plot,
not a creditworthiness statement.

SOURCES (Scientific Evidence Rule):
  * cutoff_date 2020-12-31           : Regulation (EU) 2023/1115 (EUDR), Art. 2.
  * forest baseline = GFC2020 'Map'  : JRC Global Forest Cover 2020 (FAO forest def).
  * min_mapping_unit_ha              : EXPERT ASSUMPTION — EUDR has NO de-minimis for
                                       deforestation; this is purely a sensor-noise
                                       floor (~one 30 m Hansen pixel = 0.09 ha) to
                                       stop single boundary pixels condemning a plot.
  * forest_baseline_fraction         : EXPERT ASSUMPTION — plot-level threshold for
                                       the informational "was forest in 2020" flag;
                                       does NOT gate the verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

from .facts import DeforestationFacts


class Determination(str, Enum):
    DEFORESTATION_DETECTED = "DEFORESTATION_DETECTED"          # non-compliant
    NO_DEFORESTATION_DETECTED = "NO_DEFORESTATION_DETECTED"    # compliant on this criterion


@dataclass(frozen=True)
class DeforestationRuleSet:
    name: str
    cutoff_date: date
    min_mapping_unit_ha: float          # expert assumption: sensor-noise floor
    forest_baseline_fraction: float     # expert assumption: informational flag only

    @property
    def cutoff_lossyear(self) -> int:
        """Hansen lossyear code that is the FIRST post-cutoff year. 2020-12-31 -> 21
        (2021), since Hansen loss is annual and any 2021+ loss is after the cutoff."""
        return (self.cutoff_date.year - 2000) + 1

    def validate(self) -> "DeforestationRuleSet":
        if not (0.0 <= self.forest_baseline_fraction <= 1.0):
            raise ValueError("forest_baseline_fraction must be in [0,1]")
        if self.min_mapping_unit_ha < 0:
            raise ValueError("min_mapping_unit_ha must be >= 0")
        return self


@dataclass(frozen=True)
class DeforestationResult:
    identifier: Optional[str]
    determination: Determination
    compliant: bool
    was_forest_2020: bool
    post_cutoff_forest_loss_ha: float          # the deforestation signal, cutoff-filtered
    post_cutoff_loss_years: dict               # {year: ha}, forest loss, year >= cutoff
    exceeds_mmu: bool
    facts: DeforestationFacts
    ruleset_name: str
    rationale: str

    def to_dict(self) -> dict:
        return {
            "identifier": self.identifier,
            "ruleset": self.ruleset_name,
            "determination": self.determination.value,
            "compliant": self.compliant,
            "was_forest_2020": self.was_forest_2020,
            "post_cutoff_forest_loss_ha": round(self.post_cutoff_forest_loss_ha, 4),
            "post_cutoff_loss_years": {str(y): round(a, 4) for y, a in sorted(self.post_cutoff_loss_years.items())},
            "exceeds_min_mapping_unit": self.exceeds_mmu,
            "rationale": self.rationale,
            "facts": self.facts.to_dict(),
        }


def determine(facts: DeforestationFacts, ruleset: DeforestationRuleSet) -> DeforestationResult:
    """Apply the cutoff to the forest-loss histogram and decide. The verdict runs on
    forest_loss_area_by_year (loss of 2020-baseline forest), NOT all tree loss."""
    cutoff_year = 2000 + ruleset.cutoff_lossyear  # first post-cutoff calendar year
    post = {y: a for y, a in facts.forest_loss_area_by_year.items() if y >= cutoff_year}
    post_area = sum(post.values())
    exceeds = post_area > ruleset.min_mapping_unit_ha
    was_forest = facts.forest_2020_fraction >= ruleset.forest_baseline_fraction

    if exceeds:
        det = Determination.DEFORESTATION_DETECTED
        years = ", ".join(f"{y} ({a:.3f} ha)" for y, a in sorted(post.items()))
        rationale = (
            f"{post_area:.3f} ha of 2020-baseline forest was lost after "
            f"{ruleset.cutoff_date.isoformat()} [{years}], above the "
            f"{ruleset.min_mapping_unit_ha:.2f} ha minimum-mapping-unit noise floor. "
            f"Under {ruleset.name} this parcel is NOT deforestation-free.")
    else:
        det = Determination.NO_DEFORESTATION_DETECTED
        if post_area > 0:
            rationale = (
                f"{post_area:.3f} ha of post-cutoff forest loss detected, but at or "
                f"below the {ruleset.min_mapping_unit_ha:.2f} ha noise floor — treated "
                f"as sensor noise, not deforestation. No deforestation signal on this "
                f"parcel under {ruleset.name}.")
        else:
            rationale = (
                f"No loss of 2020-baseline forest after {ruleset.cutoff_date.isoformat()} "
                f"on this parcel under {ruleset.name}.")

    return DeforestationResult(
        identifier=facts.identifier,
        determination=det,
        compliant=not exceeds,
        was_forest_2020=was_forest,
        post_cutoff_forest_loss_ha=post_area,
        post_cutoff_loss_years=post,
        exceeds_mmu=exceeds,
        facts=facts,
        ruleset_name=ruleset.name,
        rationale=rationale,
    )
