"""Orchestrator: load -> ordered checks -> ValidationReport. Knows nothing about
any specific scheme; it runs whatever RuleSet it's handed."""
from __future__ import annotations

from typing import Any, Union

from . import checks_crossfeature, checks_file, checks_geometry, checks_property, loader
from .models import FileType, ValidationReport
from .ruleset import RuleSet


def validate(source: Any, ruleset: RuleSet,
             file_type: Union[FileType, str] = FileType.TYPE_I) -> ValidationReport:
    """Validate a GeoJSON file path or parsed object against `ruleset`.

    file_type selects Type I (producer-level) or Type II (multi-producer).
    """
    ruleset.validate()
    mode = file_type if isinstance(file_type, FileType) else FileType(file_type)

    lr = loader.load(source)
    findings = list(lr.findings)
    if lr.fatal:  # invalid JSON / not a FeatureCollection — nothing else is meaningful
        return ValidationReport(ruleset.name, mode, 0, findings)

    features = lr.features
    findings += checks_file.run(features, ruleset, mode, lr.payload_mb)
    findings += checks_geometry.run(features, ruleset, mode)
    findings += checks_property.run(features, ruleset, mode)
    findings += checks_crossfeature.run(features, ruleset, mode)

    return ValidationReport(ruleset.name, mode, len(features), findings)
