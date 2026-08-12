"""
Layer-1 load: a GeoJSON file path or an already-parsed object -> a normalized
structure the checks consume. Performs only file check 1 here (valid JSON +
top-level FeatureCollection); everything else is a check module.

For a file/string source we parse with parse_float=Decimal so coordinate
precision (trailing zeros) survives — the precision checks need "37.150000" to
stay six decimals, not collapse to 37.15. For an already-parsed object that
precision is already gone (Python floats), so precision checks on object input
are best-effort only; this is documented and the checks degrade gracefully.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from . import codes
from .emit import finding
from .models import Finding


@dataclass
class LoadResult:
    data: Optional[dict]           # the FeatureCollection dict, or None if fatal
    features: list                 # feature dicts (empty if fatal)
    payload_bytes: int
    findings: list                 # file-level load findings
    fatal: bool                    # if True the engine returns just these

    @property
    def payload_mb(self) -> float:
        return self.payload_bytes / (1024 * 1024)


def load(source: Any) -> LoadResult:
    findings: list[Finding] = []

    if isinstance(source, (dict, list)):
        data = source
        payload_bytes = len(json.dumps(source, default=str).encode("utf-8"))
    else:
        path = os.fspath(source)
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError as e:
            findings.append(finding(codes.FILE_INVALID_JSON,
                                    f"Could not read the file: {e}",
                                    checked="file is readable", found=str(e),
                                    expected="a readable GeoJSON file", rule="file must exist and be readable"))
            return LoadResult(None, [], 0, findings, fatal=True)
        payload_bytes = len(raw)
        try:
            data = json.loads(raw.decode("utf-8"), parse_float=Decimal)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            findings.append(finding(codes.FILE_INVALID_JSON,
                                    f"The file is not valid JSON: {e}",
                                    checked="file parses as JSON", found=str(e),
                                    expected="valid JSON", rule="input must be valid JSON"))
            return LoadResult(None, [], payload_bytes, findings, fatal=True)

    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        got = data.get("type") if isinstance(data, dict) else type(data).__name__
        findings.append(finding(codes.FILE_NOT_FEATURECOLLECTION,
                                "The top-level object is not a GeoJSON FeatureCollection.",
                                checked="top-level type == FeatureCollection",
                                found=got, expected="FeatureCollection",
                                rule="a GeoJSON submission's root must be a FeatureCollection"))
        return LoadResult(None, [], payload_bytes, findings, fatal=True)

    features = data.get("features")
    if not isinstance(features, list):
        features = []
    return LoadResult(data, features, payload_bytes, findings, fatal=False)
