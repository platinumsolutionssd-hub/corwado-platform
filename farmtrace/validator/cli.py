"""
Thin CLI wrapper for the geolocation validator.

    python -m farmtrace.validator.cli PATH [--ruleset eudr] [--type I|II] [--format human|json]

Exit code: 0 if the file PASSES, 1 if it FAILS validation, 2 on a usage error
(argparse). No API endpoint, no extra behaviour — just load, validate, print.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .core.engine import validate
from .core.models import FileType
from .core.report import render_markdown
from .rulesets.eudr import eudr_ruleset

RULESETS = {
    "eudr": eudr_ruleset,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="farmtrace-validate",
        description="Validate a plot GeoJSON file against a certification ruleset.")
    parser.add_argument("path", help="GeoJSON file to validate")
    parser.add_argument("--ruleset", default="eudr", choices=sorted(RULESETS),
                        help="certification ruleset (default: eudr)")
    parser.add_argument("--type", dest="file_type", default="I", choices=["I", "II"],
                        help="file type: I = producer-level, II = multi-producer (default: I)")
    parser.add_argument("--format", dest="fmt", default="human", choices=["human", "json"],
                        help="output format (default: human)")
    args = parser.parse_args(argv)  # argparse exits 2 on a usage error

    # The report uses em-dashes / middots; force UTF-8 so a Windows console
    # (cp1252 by default) renders them instead of mojibake. No-op elsewhere.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    ruleset = RULESETS[args.ruleset]()
    report = validate(args.path, ruleset, FileType(args.file_type))

    if args.fmt == "json":
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_markdown(report, filename=os.path.basename(args.path)))

    return 0 if report.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
