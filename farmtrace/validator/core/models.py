"""
Core data contracts for the geolocation validator — scheme-agnostic.

A Finding is the single unit every check emits. It carries the machine fields
(severity, code, feature ref, message, offending value) AND an explainability
block (what was checked, what was found, what was expected, which rule required
it, and that rule's source) so nothing is a black box. ValidationReport
aggregates findings and computes the summary/verdict (FAIL iff any ERROR).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    ERROR = "ERROR"      # blocks export
    WARNING = "WARNING"  # flagged for review, does not block


class FileType(str, Enum):
    TYPE_I = "I"    # producer-level
    TYPE_II = "II"  # multi-producer (ProducerCountry mandatory per feature)


@dataclass(frozen=True)
class FeatureRef:
    """Points a finding at a feature: its index plus a best-effort identifier
    (an identifying property, e.g. {"ProducerName": "Alice"}). None for
    file-level findings."""
    index: int
    identifier: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"index": self.index, "identifier": self.identifier}


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str
    feature_ref: Optional[FeatureRef] = None
    offending_value: Any = None
    # Explainability block — every finding exposes these.
    checked: str = ""
    found: Any = None
    expected: Any = None
    rule: str = ""
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "feature_ref": self.feature_ref.to_dict() if self.feature_ref else None,
            "message": self.message,
            "offending_value": _jsonable(self.offending_value),
            "explain": {
                "checked": self.checked,
                "found": _jsonable(self.found),
                "expected": _jsonable(self.expected),
                "rule": self.rule,
                "source": self.source,
            },
        }


@dataclass
class ValidationReport:
    ruleset_name: str
    file_type: FileType
    total_features: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.WARNING)

    @property
    def verdict(self) -> str:
        return "FAIL" if self.errors else "PASS"

    def summary(self) -> dict:
        return {
            "ruleset": self.ruleset_name,
            "file_type": self.file_type.value,
            "total_features": self.total_features,
            "errors": self.errors,
            "warnings": self.warnings,
            "verdict": self.verdict,
        }

    def to_dict(self) -> dict:
        """Machine-readable output: summary block + the full findings list."""
        return {"summary": self.summary(), "findings": [f.to_dict() for f in self.findings]}


def _jsonable(v: Any) -> Any:
    """Coerce values (e.g. Decimal from precision-preserving parse) to something
    JSON-serialisable, without losing the human-visible representation."""
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v
