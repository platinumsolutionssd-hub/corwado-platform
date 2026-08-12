"""Finding factory — one place that stamps a finding's default severity (from the
code registry) and its explainability block. `severity` may be overridden by the
caller for the few checks that escalate (e.g. the two-tier coordinate swap)."""
from __future__ import annotations

from typing import Any, Optional

from . import codes
from .models import Finding, FeatureRef, Severity


def finding(code: str, message: str, *,
            feature_ref: Optional[FeatureRef] = None,
            offending_value: Any = None,
            checked: str = "", found: Any = None, expected: Any = None,
            rule: str = "", source: str = "",
            severity: Optional[Severity] = None) -> Finding:
    return Finding(
        severity=severity or codes.default_severity(code),
        code=code, message=message, feature_ref=feature_ref,
        offending_value=offending_value,
        checked=checked, found=found, expected=expected, rule=rule, source=source,
    )
