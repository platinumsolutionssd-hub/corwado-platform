"""
Provider seam for the deforestation fact layer.

The core computes FACTS from raw raster reductions but does not know HOW those
reductions are produced. `GeeProvider` (provider_gee.py) does the live Earth Engine
reduction; `FakeProvider` returns a constructed reduction so the fact-assembly
logic unit-tests offline with zero EECU and no earthengine-api import. This module
imports no `ee`.

`RawReduction` is REGULATION-AGNOSTIC: it carries the FULL loss-year histogram and
applies no cutoff. The cutoff/verdict live in the Stage-3 ruleset, so a scheme with
a different cutoff reuses the same facts unchanged (the config-only seam).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RawReduction:
    """Raw per-plot raster reductions over a footprint.

    forest_2020_fraction : mean of GFC2020 'Map'.unmask(0) over the footprint, 0..1.
    loss_area_by_year    : {calendar_year: hectares}, nonzero years only, from
                           Hansen 'lossyear' (full history — no cutoff applied).
    treecover2000_mean   : mean Hansen 'treecover2000' over the footprint, 0..100.
    """
    forest_2020_fraction: float
    loss_area_by_year: Mapping[int, float]
    treecover2000_mean: float


class Provider(ABC):
    @abstractmethod
    def reduce(self, footprint_geojson: dict, footprint_area_ha: float) -> RawReduction:
        """Reduce the forest / loss layers over a footprint (a GeoJSON Polygon dict)."""
        raise NotImplementedError


class FakeProvider(Provider):
    """Test double: returns a pre-set RawReduction, ignoring the geometry. Build one
    per scenario to drive a fact-assembly / determination branch offline."""

    def __init__(self, reduction: RawReduction):
        self._reduction = reduction

    def reduce(self, footprint_geojson, footprint_area_ha):  # noqa: ARG002 - fake ignores geom
        return self._reduction
