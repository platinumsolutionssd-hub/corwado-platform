"""
AdvisoryEngine interface.

Formalized per the Platinum Precision Agriculture Platform Architecture
addendum (v0.2, "Response to External Architecture Review"): with two
real implementations now sharing one output shape — the in-house
Biophysical Intelligence Engine and Satyukt's Sat2Farm — this interface
is earned, not speculative. It uses structural typing (Protocol), not a
heavier plugin framework, because that's the amount of abstraction two
real cases justifies. Do not add a registry, factory, or dynamic-loading
mechanism here until a third engine actually needs one.
"""
from typing import Protocol

from app.schemas import AdvisoryOutput


class AdvisoryEngine(Protocol):
    """
    Any advisory source — in-house or external — should be shaped to
    satisfy this. A class doesn't need to inherit from this Protocol
    explicitly; Python's structural typing means anything with matching
    method signatures satisfies it. This exists for type-checking and
    documentation clarity, not runtime enforcement.
    """

    def supports(self, crop: str) -> bool:
        """Whether this engine can produce a score for the given crop."""
        ...

    def analyse(self, parcel, crop: str) -> AdvisoryOutput:
        """
        Returns advisory data in the shared AdvisoryOutput shape.

        `crop` was added because agri-venture-v2's real /analyze pipeline
        scores land/production suitability against one specific crop's
        biology.json -- parcel geometry alone isn't enough to call it.
        Every engine behind this Protocol must accept the parameter even
        if a given implementation doesn't use it (see SatyuktSat2FarmEngine).
        """
        ...
