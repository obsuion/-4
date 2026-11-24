"""Ordered admission of supplied orbit-bound candidates, not bulk generation.

D1b reconstructs every item's existing D1a/C2c/B1/C1 evidence. This owner adds
only collection shape, actual-text opportunity-ID uniqueness and retained order.
It neither evaluates a sequence nor adds a legacy catalog or persistent state.
See D316/S006. Existing nested owner admission is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from .ids import ObservationOpportunityId
from .orbit_observation_boresight import OrbitBoundObservationManeuverCandidate


def _opportunity_key(identifier: ObservationOpportunityId) -> tuple[type, str]:
    """Copy actual text through the base descriptor, without caller hooks."""
    if type(identifier) is not ObservationOpportunityId:
        raise TypeError("opportunity_id must be an exact ObservationOpportunityId")
    text = str.__str__(identifier.value)
    if type(text) is not str:
        raise TypeError("opportunity identity key must contain exact built-in text")
    return type(identifier), text


@dataclass(frozen=True, slots=True, eq=False)
class OrbitBoundObservationCandidateCatalog:
    """Transient reconstructed evidence in caller order, with unique opportunity IDs.

    No other identity, frame, world or time is required to be shared or unique.
    Order is evidence, not an execution chronology. Equality uses the existing
    D1b semantics; the catalog is explicitly unhashable.
    """

    candidates: tuple[OrbitBoundObservationManeuverCandidate, ...]

    __hash__ = None

    def __post_init__(self) -> None:
        if type(self.candidates) is not tuple:
            raise TypeError("candidates must be an exact tuple")
        if not all(type(item) is OrbitBoundObservationManeuverCandidate
                   for item in self.candidates):
            raise TypeError("candidates must contain only exact OrbitBoundObservationManeuverCandidate values")
        candidates = tuple(
            OrbitBoundObservationManeuverCandidate(**{
                item.name: getattr(candidate, item.name)
                for item in fields(OrbitBoundObservationManeuverCandidate) if item.init
            })
            for candidate in self.candidates
        )
        # All owner reconstructions precede this new identity boundary. Only
        # exact owner types and built-in text enter the temporary set. Expected
        # cost is O(n + total actual text length), apart from reconstruction.
        seen = set()
        for candidate in candidates:
            key = _opportunity_key(candidate.opportunity_id)
            if key in seen:
                raise ValueError("candidate opportunity IDs must be unique by actual text")
            seen.add(key)
        object.__setattr__(self, "candidates", candidates)

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return (len(self.candidates) == len(other.candidates)
                and all(a == b for a, b in zip(self.candidates, other.candidates)))


__all__ = ["OrbitBoundObservationCandidateCatalog"]
