"""
Human "deforestation check" report — plain-language markdown for a cooperative
manager / exporter's clerk with NO GIS knowledge. Renders a batch of
DeforestationResults (one file of plots) into: a header summary, the flagged
plots detailed, the deforestation-free plots (WITH full disclosure of any signal
that was filtered — see below), and an audit footer naming every parameter that
shaped a verdict.

DISCLOSURE PRINCIPLE (EUDR has no de-minimis — the report must state what was
filtered and why, or it misstates the reader's legal exposure). A "deforestation-
free" plot is never shown as simply clean if a signal was filtered. Two filters
can suppress a signal, and BOTH are disclosed:
  * MMU noise floor    — post-cutoff FOREST loss > 0 but <= the floor.
  * forest-intersection — post-cutoff tree loss on land that was NOT 2020 forest
                          (excluded as not-deforestation; often the larger signal).
"""
from __future__ import annotations

from typing import List

from .ruleset import DeforestationResult, DeforestationRuleSet

_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _human_date(d) -> str:
    return f"{d.day} {_MONTHS[d.month]} {d.year}"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _years_phrase(loss_years: dict) -> str:
    return ", ".join(f"{y} ({a:.2f} ha)" for y, a in sorted(loss_years.items(), reverse=True))


def _years_simple(loss_years: dict) -> str:
    """Just the years, ascending, in prose: '2023 and 2024' / '2021, 2023 and 2024'."""
    years = [str(y) for y in sorted(loss_years)]
    if len(years) == 1:
        return years[0]
    return ", ".join(years[:-1]) + " and " + years[-1]


def _forest_baseline_sentence(r: DeforestationResult, rs: DeforestationRuleSet) -> str:
    return (f"{_pct(r.facts.forest_2020_fraction)} of this plot was forest at the 2020 "
            f"baseline (the EUDR check applies where this is at least "
            f"{_pct(rs.forest_baseline_fraction)}).")


def _post_cutoff_all_loss(r: DeforestationResult, rs: DeforestationRuleSet) -> dict:
    cutoff_year = 2000 + rs.cutoff_lossyear
    return {y: a for y, a in r.facts.loss_area_by_year.items() if y >= cutoff_year}


def _compliant_disclosure(r: DeforestationResult, rs: DeforestationRuleSet) -> str:
    forest_post = dict(r.post_cutoff_loss_years)          # post-cutoff FOREST loss
    forest_sum = sum(forest_post.values())
    all_post = _post_cutoff_all_loss(r, rs)               # post-cutoff ALL tree loss
    all_sum = sum(all_post.values())
    nonforest_excluded = all_sum - forest_sum

    notes = []
    if forest_sum > 0:  # sub-floor forest loss (below the MMU)
        notes.append(
            f"a small signal ({forest_sum:.2f} ha of 2020-forest loss) below the "
            f"{rs.min_mapping_unit_ha:.2f} ha noise floor — consistent with boundary / "
            f"GPS noise; imagery review recommended")
    if nonforest_excluded > 0.005:  # tree loss excluded because the land was not 2020 forest
        notes.append(
            f"{nonforest_excluded:.2f} ha of post-2020 tree loss on land that was NOT forest "
            f"at the 2020 baseline ({_pct(r.facts.forest_2020_fraction)} forest), excluded as "
            f"not EUDR deforestation")
    if notes:
        return "no deforestation, but disclosed for transparency: " + "; ".join(notes) + "."
    return "no post-2020 tree loss detected."


def render_markdown(results: List[DeforestationResult], ruleset: DeforestationRuleSet,
                    filename: str) -> str:
    total = len(results)
    flagged = [r for r in results if not r.compliant]
    clear = [r for r in results if r.compliant]
    cutoff = _human_date(ruleset.cutoff_date)
    cutoff_year = 2000 + ruleset.cutoff_lossyear

    L: List[str] = []
    L.append(f"# Deforestation check — {filename}")
    L.append("")
    L.append(f"**Plots checked:** {total}  ·  **Deforestation-free:** {len(clear)}  ·  "
             f"**Flagged:** {len(flagged)}  ·  **Ruleset:** {ruleset.name}")
    L.append("")
    if flagged:
        L.append(f"**{len(flagged)} of {total} plots show forest loss after {cutoff} and cannot "
                 f"be submitted as deforestation-free.** Each is detailed below with the year and "
                 f"the area. Exclude or correct them, then run the check again.")
    else:
        L.append(f"**All {total} plots are clear of post-{cutoff_year - 1} forest loss under "
                 f"{ruleset.name}.** Keep this report with your submission records.")
    L.append("")

    if flagged:
        L.append("## Plots that cannot be submitted as deforestation-free")
        L.append("")
        for r in flagged:
            L.append(f"### {r.identifier}")
            L.append("")
            L.append(f"Forest on this plot was cleared after the cut-off: "
                     f"{r.post_cutoff_forest_loss_ha:.2f} ha of land that was forest at the 2020 "
                     f"baseline was lost, in {_years_simple(r.post_cutoff_loss_years)}.")
            L.append("")
            L.append(f"- **Post-2020 forest loss:** {r.post_cutoff_forest_loss_ha:.2f} ha "
                     f"— {_years_phrase(r.post_cutoff_loss_years)}")
            L.append(f"- {_forest_baseline_sentence(r, ruleset)}")
            L.append(f"- **What this means:** land cleared of forest after {cutoff} cannot enter "
                     f"the EU as deforestation-free under {ruleset.name}.")
            L.append(f"- **What to do:** exclude this plot from the deforestation-free batch. If "
                     f"you believe the detection is wrong (for example the plot boundary is off), "
                     f"commission a ground or imagery review and re-check with a corrected boundary.")
            L.append("")

    if clear:
        L.append("## Plots that are deforestation-free")
        L.append("")
        for r in clear:
            L.append(f"- **{r.identifier}:** {_compliant_disclosure(r, ruleset)}")
        L.append("")

    L.append("## How this was checked")
    L.append("")
    L.append("- **Forest baseline (2020):** JRC Global Forest Cover 2020 (GFC2020) V3, ~10 m — "
             "defines what was forest at the cut-off.")
    L.append("- **Forest loss:** Hansen / UMD Global Forest Change v1.13 (2025), ~30 m — annual "
             "tree-cover loss.")
    L.append(f"- **Cut-off date:** {cutoff} (Regulation (EU) 2023/1115). Loss from {cutoff_year} "
             f"onward counts.")
    L.append("- **Deforestation = loss of 2020-baseline forest.** Tree loss on land that was not "
             "forest in 2020 is excluded and disclosed, never counted as deforestation.")
    L.append(f"- **Minimum-mapping-unit noise floor:** {ruleset.min_mapping_unit_ha:.2f} ha "
             f"(~one 30 m pixel). Expert assumption — EUDR has no de-minimis; this filters sensor "
             f"noise only, and anything filtered is disclosed above.")
    L.append(f"- **Forest-baseline threshold:** {_pct(ruleset.forest_baseline_fraction)} — a plot "
             f"is treated as having 2020 forest where at least this share is forest. Expert "
             f"assumption; informational, does not by itself decide the verdict.")
    L.append("- **Point plots:** the footprint is a circular buffer of the declared Area. Expert "
             "assumption — EUDR supplies a point + Area but no footprint shape.")
    L.append("")

    return "\n".join(L)
