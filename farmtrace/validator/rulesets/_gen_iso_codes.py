"""
Generates iso_codes.py — the static ISO 3166-1 alpha-2 set and alpha-3 -> alpha-2
map used by the EUDR ruleset's country-code checks. Sourced from `pycountry` (the
authoritative ISO 3166 dataset) at build time and frozen into a plain-Python
module, so the shipped ruleset has NO runtime dependency on pycountry and no
hand-typed (error-prone) country list.

Run (cwd = repo root, pycountry installed):
    python farmtrace/validator/rulesets/_gen_iso_codes.py
"""
import os

import pycountry

HERE = os.path.dirname(os.path.abspath(__file__))

iso2 = sorted(c.alpha_2 for c in pycountry.countries)
iso3_to_iso2 = {c.alpha_3: c.alpha_2 for c in pycountry.countries}

lines = [
    '"""ISO 3166-1 country codes. GENERATED from pycountry by _gen_iso_codes.py —',
    'do not hand-edit; regenerate to update. No runtime dependency on pycountry."""',
    "",
    f"# {len(iso2)} alpha-2 codes",
    "ISO2_CODES = frozenset({",
]
# 12 codes per line for readability
for i in range(0, len(iso2), 12):
    chunk = ", ".join(f'"{c}"' for c in iso2[i:i + 12])
    lines.append(f"    {chunk},")
lines.append("})")
lines.append("")
lines.append(f"# {len(iso3_to_iso2)} alpha-3 -> alpha-2 (to flag 'you wrote ISO3' and name the ISO2 fix)")
lines.append("ISO3_TO_ISO2 = {")
for k in sorted(iso3_to_iso2):
    lines.append(f'    "{k}": "{iso3_to_iso2[k]}",')
lines.append("}")
lines.append("")

with open(os.path.join(HERE, "iso_codes.py"), "w", encoding="utf-8", newline="\n") as fh:
    fh.write("\n".join(lines))

print(f"wrote iso_codes.py: {len(iso2)} ISO2 codes, {len(iso3_to_iso2)} ISO3->ISO2 mappings")
