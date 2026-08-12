"""
Human-readable findings report — the client-facing dry-run deliverable. The
reader is a cooperative manager or an exporter's clerk with NO GIS knowledge, so
this reads as plain guidance: a summary block, findings grouped by severity then
fault class (each class with a one-paragraph explanation of what the fault is and
why the EU system rejects it, plus a concrete fix), then a "what to do next"
checklist.

The machine-readable output is ValidationReport.to_dict(); this module is the
markdown view of the same findings.
"""
from __future__ import annotations

from . import codes
from .models import Severity, ValidationReport

# Per fault-class guidance: (title, why the EU system rejects it, concrete fix).
# The per-finding message carries the specific value; this is the class-level
# explanation the reader needs to understand and fix the whole class.
GUIDANCE = {
    codes.FILE_INVALID_JSON: (
        "The file could not be read",
        "The submission has to be a valid GeoJSON file. This one could not be opened as one, so nothing inside it could be checked.",
        "Re-export the file from the tool that produced it, and make sure it is saved as GeoJSON (.geojson), not as a spreadsheet or a copied-and-pasted fragment."),
    codes.FILE_NOT_FEATURECOLLECTION: (
        "The file is not a plot collection",
        "The EU system expects the file's top level to be a GeoJSON \"FeatureCollection\" — a list of plots. This file's top level is something else, so it has no plots to submit.",
        "Re-export the plots as a FeatureCollection from your mapping/registration tool."),
    codes.FILE_EMPTY_COLLECTION: (
        "The file has no plots",
        "The file is a valid plot collection but contains no plots, so there is nothing to submit.",
        "Add the plots (or check you exported the right file) and re-validate."),
    codes.FILE_PAYLOAD_EXCEEDED: (
        "The file is too large",
        "The EU information system rejects a single upload above its size limit.",
        "Split the plots into several smaller files, each under the limit, and submit them separately."),
    codes.FILE_PAYLOAD_WARN: (
        "The file is close to the size limit",
        "The file is under the EU size limit but near it; a slightly larger batch would be rejected.",
        "Consider splitting into smaller batches now so future exports don't cross the limit."),
    codes.FILE_PLOT_COUNT_EXCEEDED: (
        "Too many plots in one file",
        "The EU information system rejects a single upload with more than its maximum number of plots.",
        "Split the plots across several files, each under the plot limit."),
    codes.FILE_PLOT_COUNT_WARN: (
        "Approaching the plot limit",
        "The file is under the EU plot-count limit but close to it.",
        "Consider splitting into smaller batches to stay clear of the limit."),
    codes.FILE_TYPEII_COUNTRY_MISSING: (
        "A plot is missing its country (multi-producer file)",
        "This is a multi-producer (Type II) file, so the EU system requires each individual plot to state its own production country.",
        "Add the ProducerCountry (2-letter ISO code) to every plot listed below."),

    codes.GEOM_TYPE_REJECTED: (
        "The plot shape is not an allowed type",
        "A plot must be either a point (a single GPS location) or a polygon (a drawn boundary). Lines and other shapes are not accepted by the EU system — they cannot represent a plot's area.",
        "Re-capture the plot as a point (for a small plot) or a closed polygon boundary (for a larger one)."),
    codes.GEOM_TYPE_DISCOURAGED: (
        "The plot shape uses a discouraged type",
        "The shape is technically readable but uses a compound type the EU system prefers you avoid; it can cause ambiguity.",
        "Re-save the plot as a plain point or polygon."),
    codes.GEOM_NULL: (
        "The plot has no location",
        "The plot record exists but carries no coordinates at all, so it cannot be placed on the map or checked for deforestation.",
        "Add the plot's GPS point or drawn boundary."),
    codes.GEOM_COORD_OUT_OF_RANGE: (
        "A coordinate is impossible",
        "A longitude must be between -180 and 180, and a latitude between -90 and 90. A value outside that range is not a real place on Earth, so the EU system rejects it.",
        "Check the coordinate for a typo (an extra digit, a misplaced decimal point) and correct it to the real location."),
    codes.GEOM_COORDS_LIKELY_SWAPPED: (
        "Longitude and latitude look swapped",
        "GeoJSON stores each point as [longitude, latitude], in that order. When they are entered the other way round, the plot lands in the wrong part of the world — often in the sea — which the EU system will flag as inconsistent with the stated country.",
        "Swap the two numbers for each plot below so the point falls inside the declared country."),
    codes.GEOM_RING_NOT_CLOSED: (
        "A boundary does not close",
        "A polygon boundary has to end where it started — the first and last points must be identical — so the area is fully enclosed. An open boundary has no well-defined area.",
        "Close the boundary by repeating its first point as the last point (most drawing tools do this automatically; re-save from one that does)."),
    codes.GEOM_RING_TOO_FEW_POINTS: (
        "A boundary has too few points",
        "A polygon needs at least three distinct corners (four points including the repeated closing point) to enclose any area.",
        "Re-draw the boundary with enough points to outline the real plot."),
    codes.GEOM_SELF_INTERSECTION: (
        "A boundary crosses itself",
        "The drawn boundary loops back over itself (a bow-tie or figure-eight shape), so the enclosed area is ambiguous and the EU system cannot compute it reliably.",
        "Re-draw the boundary so its edges never cross — walk the plot's outline in one direction without backtracking."),
    codes.GEOM_INTERIOR_RING: (
        "A boundary contains a hole",
        "The plot polygon has a hole cut out of it (an interior ring). Plot boundaries are expected to be solid outlines, not shapes with holes.",
        "Re-draw the plot as a single solid outline without interior holes."),
    codes.GEOM_DUPLICATE_CONSECUTIVE: (
        "A boundary repeats a point",
        "The boundary lists the same point twice in a row, which usually means a stray double-tap while drawing.",
        "Remove the duplicated point (re-saving from the drawing tool usually clears it)."),
    codes.GEOM_PRECISION_INSUFFICIENT: (
        "Coordinates may be too rounded",
        "The EU system expects coordinates recorded to about six decimal places (roughly 0.1 m). These look more rounded than that — though a genuinely round coordinate can trigger this too, so treat it as a prompt to check, not a certainty.",
        "Confirm the coordinates were captured at full GPS precision; if they were rounded, re-export them un-rounded."),
    codes.GEOM_PRECISION_EXCESS: (
        "Coordinates have false precision",
        "The coordinates carry far more decimal places than a GPS can actually measure, which overstates how exact the location is.",
        "Round the coordinates to six decimal places on export."),
    codes.GEOM_ANTIMERIDIAN: (
        "A boundary crosses the 180° line",
        "The plot boundary crosses the +/-180° longitude line. Area and overlap results for it are approximate. This is unusual for the operating region and often signals a coordinate error.",
        "Confirm the plot really sits near the 180° meridian; if not, check the coordinates for an error."),

    codes.PROP_MISSING: (
        "A required detail is missing",
        "The EU system requires certain details on every plot; one of them is absent here.",
        "Add the missing property (see each plot below) and re-validate."),
    codes.PROP_CASING_MISMATCH: (
        "A detail is spelled with the wrong capitalisation",
        "The EU system matches property names exactly, including capital letters. A name like \"producername\" is not recognised as \"ProducerName\", so the detail is treated as missing.",
        "Rename the property to the exact spelling shown for each plot below (capitalisation matters)."),
    codes.PROP_RECOMMENDED_MISSING: (
        "A recommended detail is missing",
        "This detail is recommended but not strictly required. Including it makes the submission clearer and less likely to be queried.",
        "Add the recommended property where you can."),
    codes.PROP_COUNTRY_NOT_ISO2: (
        "The country code is not valid",
        "The production country must be given as its official 2-letter code (ISO 3166-1 alpha-2), e.g. KE for Kenya. The value here is not a recognised 2-letter code.",
        "Replace it with the correct 2-letter country code."),
    codes.PROP_COUNTRY_IS_ISO3: (
        "The country code uses 3 letters instead of 2",
        "The country was given as a 3-letter code (e.g. KEN). The EU system requires the 2-letter code (e.g. KE).",
        "Replace the 3-letter code with the 2-letter code shown for each plot below."),
    codes.PROP_AREA_NOT_NUMBER: (
        "The area is written as text, not a number",
        "The Area must be a number (e.g. 1.1). Here it is stored as text — wrapped in quotation marks — which is the most common fault from spreadsheet exports. A text value cannot be used in calculations, so the EU system rejects it.",
        "Remove the quotation marks so the value is a plain number."),
    codes.PROP_POINT_AREA_MISSING: (
        "A point plot has no area",
        "A plot recorded as a single point must state its area, because a point has no size of its own. Without it the EU system assumes a default that is likely wrong.",
        "Add the plot's real area (in hectares) as a number."),
    codes.PROP_POLYGON_AREA_INCONSISTENT: (
        "The stated area doesn't match the drawn boundary",
        "The area written on the plot differs substantially from the area of the drawn boundary. One of them is wrong.",
        "Check which is correct — the drawn boundary or the written area — and fix the other."),
    codes.THRESH_POINT_AREA_TOO_LARGE: (
        "A large plot is recorded as a point",
        "Plots at or above the EU size threshold must be submitted as a drawn boundary (polygon), not a single point, because a point cannot show where a large plot's edges are.",
        "Re-capture the plot as a polygon boundary instead of a point."),

    codes.XFEAT_OVERLAP: (
        "Two plots overlap",
        "Two plots cover part of the same ground. Overlapping plots can mean a double-counted area or a mapping error, which the EU system will question.",
        "Check the two plots below; correct whichever boundary is wrong so they no longer overlap."),
    codes.XFEAT_DUPLICATE_PRODUCER: (
        "The same plot appears twice",
        "The same producer has two plots with near-identical boundaries — usually the same plot entered twice when rosters were merged.",
        "Remove the duplicate so each real plot appears once."),
}

_FALLBACK = ("Issue", "This item needs review before submission.", "Review and correct the item below.")


def _verdict_sentence(r: ValidationReport) -> str:
    if r.errors:
        return (f"**This file cannot be submitted as it is.** {r.errors} "
                f"{'error' if r.errors == 1 else 'errors'} below would be rejected by the EU information "
                f"system. Fix every error, then run the check again.")
    if r.warnings:
        return (f"**This file has no blocking errors and can be submitted** — but {r.warnings} "
                f"{'warning' if r.warnings == 1 else 'warnings'} below should be reviewed first.")
    return "**This file passed every check and is ready to submit.**"


def _feature_label(f) -> str:
    if not f.feature_ref:
        return "File"
    ref = f.feature_ref
    name = next(iter(ref.identifier.values()), None) if ref.identifier else None
    return f"Plot #{ref.index}" + (f" ({name})" if name else "")


def render_markdown(report: ValidationReport, filename: str = "(submission)") -> str:
    out = []
    out.append(f"# Geolocation check — {filename}")
    out.append("")
    out.append(f"**Plots checked:** {report.total_features}  ·  "
               f"**Verdict:** {report.verdict}  ·  "
               f"**Errors:** {report.errors}  ·  **Warnings:** {report.warnings}")
    out.append("")
    out.append(_verdict_sentence(report))
    out.append("")

    sections = [
        (Severity.ERROR, "Errors — must be fixed before submission"),
        (Severity.WARNING, "Warnings — review before submission"),
    ]
    for severity, heading in sections:
        group = [f for f in report.findings if f.severity is severity]
        if not group:
            continue
        out.append(f"## {heading}")
        out.append("")
        # group by fault class (code), preserving first-seen order
        seen = []
        for f in group:
            if f.code not in seen:
                seen.append(f.code)
        for code in seen:
            title, why, fix = GUIDANCE.get(code, _FALLBACK)
            items = [f for f in group if f.code == code]
            out.append(f"### {title}  ({len(items)})")
            out.append("")
            out.append(why)
            out.append("")
            out.append(f"**How to fix:** {fix}")
            out.append("")
            for f in items:
                line = f"- **{_feature_label(f)}:** {f.message}"
                out.append(line)
            out.append("")

    out.append("## What to do next")
    out.append("")
    if report.errors:
        out.append("1. **Fix every error above.** The file must reach **zero errors** before it can be submitted to the EU system.")
        out.append("2. **Review each warning** — either correct it, or record a short note of why it is acceptable (reviewed and justified).")
        out.append("3. **Run this check again** and keep the passing report with your submission records.")
    elif report.warnings:
        out.append("1. **Review each warning above** — correct it, or record why it is acceptable (reviewed and justified).")
        out.append("2. Keep this report with your submission records; the file has no blocking errors.")
    else:
        out.append("1. No action needed — keep this passing report with your submission records.")
    out.append("")
    return "\n".join(out)
