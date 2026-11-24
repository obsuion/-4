"""Concrete-frame admission for one ordered pairwise V5.3 C2 transition.

D1b owns reconstruction of instantaneous ray evidence; C2 owns all transition
arithmetic. Equal complete MODEL_INERTIAL bindings are required before the
legacy label-only comparison. No time ordering, view/window/sequence feasibility,
catalog, execution or persistent state is introduced. See D314/S006.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from .adcs import (
    BoresightTransitionResult,
    CommonFrameBoresightDirection,
    compute_boresight_transition,
)
from .adcs_config import AgilePointingConfig
from .orbit_observation_boresight import OrbitBoundObservationManeuverCandidate


@dataclass(frozen=True, slots=True, eq=False)
class OrbitBoundObservationTransition:
    """Recomputed, unhashable evidence for an ordered pair, not a schedule."""

    config: AgilePointingConfig
    previous: OrbitBoundObservationManeuverCandidate
    next: OrbitBoundObservationManeuverCandidate
    transition_result: BoresightTransitionResult = field(init=False)

    __hash__ = None

    def __post_init__(self) -> None:
        if type(self.config) is not AgilePointingConfig:
            raise TypeError("config must be an exact AgilePointingConfig")
        config = AgilePointingConfig(
            self.config.maximum_view_angle_from_nadir_deg,
            self.config.post_slew_settling_time_seconds,
            self.config.slew_time_anchors,
        )
        for name in ("previous", "next"):
            if type(getattr(self, name)) is not OrbitBoundObservationManeuverCandidate:
                raise TypeError(
                    f"{name} must be an exact OrbitBoundObservationManeuverCandidate"
                )
        # Only the eleven init inputs cross back into D1b's public owner.
        # Its three derived fields are deliberately neither read nor trusted.
        previous, next = (
            OrbitBoundObservationManeuverCandidate(**{
                item.name: getattr(candidate, item.name)
                for item in fields(OrbitBoundObservationManeuverCandidate) if item.init
            })
            for candidate in (self.previous, self.next)
        )
        if not previous.boresight_frame == next.boresight_frame:
            raise ValueError(
                "pairwise observation transition requires equal concrete boresight-frame bindings"
            )

        # Compatibility shim ONLY after the stronger concrete-binding gate.
        # Reuse one original caller-owned ID object: no new identity, frame
        # transform or rewrite of either retained D1b direction is involved.
        shared_frame_id = previous.boresight_frame.frame_id
        start = previous.common_frame_boresight
        end = next.common_frame_boresight
        legacy_start = CommonFrameBoresightDirection(
            shared_frame_id, start.x, start.y, start.z
        )
        legacy_end = CommonFrameBoresightDirection(
            shared_frame_id, end.x, end.y, end.z
        )
        transition = compute_boresight_transition(config, legacy_start, legacy_end)
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "previous", previous)
        object.__setattr__(self, "next", next)
        object.__setattr__(self, "transition_result", transition)

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return (self.config == other.config
                and self.previous == other.previous
                and self.next == other.next
                and self.transition_result == other.transition_result)


def evaluate_orbit_bound_observation_transition(
    config: AgilePointingConfig,
    previous: OrbitBoundObservationManeuverCandidate,
    next: OrbitBoundObservationManeuverCandidate,
) -> OrbitBoundObservationTransition:
    return OrbitBoundObservationTransition(config, previous, next)


__all__ = ["OrbitBoundObservationTransition", "evaluate_orbit_bound_observation_transition"]
