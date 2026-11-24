"""One D1a target ray bound to concrete MODEL_INERTIAL common-frame axes.

The nested V5.3 candidate carries only a frame label, not complete V5.6 frame
evidence. A later pairwise bridge must compare the enclosing hardened bindings
before invoking historical C2/C3 logic. No transition or sequence is evaluated
here. MODEL_INERTIAL is the adopted model frame, not GCRS/J2000/ITRS.

The ray is instantaneous at the selected step start, not continuous tracking or
full attitude. Binding and candidate evidence are transient and external to B2.
No catalog is built: legacy caller ID text needs a separate hardened actual-text
uniqueness boundary before future bulk catalog generation. See D313/S006.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from .adcs import CommonFrameBoresightDirection
from .context import SimulationInputs
from .ids import ADCSBoresightFrameId, ObservationOpportunityId
from .observation import ImagingRequest
from .observation_feasibility import ObservationManeuverCandidate
from .orbit_config import FrameDefinition, FrameKind, _exact, _frame, _instant
from .orbit_geometry import GroundPointDefinition, _frame_text
from .orbit_observation_opportunity import (
    OrbitDerivedObservationOpportunity, derive_observation_opportunity_for_engine_step,
)
from .orbit_visibility import GroundVisibilityPolicy
from .orbit_visibility_windows import GroundVisibilitySearchConfig


@dataclass(frozen=True, slots=True, eq=False)
class ModelInertialBoresightFrameBinding:
    """Caller label plus complete concrete axes; no global label uniqueness."""

    frame_id: ADCSBoresightFrameId
    frame: FrameDefinition

    __hash__ = None

    def __post_init__(self) -> None:
        _exact(self.frame_id, ADCSBoresightFrameId, "frame_id")
        ADCSBoresightFrameId(self.frame_id.value)
        frame = _frame(self.frame)
        # Concrete metadata follows C1/B2's exact scalar-Unicode contract;
        # only the independent legacy ADCS label admits text subclasses.
        _frame_text(frame)
        if frame.kind is not FrameKind.MODEL_INERTIAL:
            raise ValueError("boresight binding requires MODEL_INERTIAL frame")
        object.__setattr__(self, "frame", frame)

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return (str.__eq__(self.frame_id.value, other.frame_id.value) is True
                and self.frame == other.frame)


@dataclass(frozen=True, slots=True, eq=False)
class OrbitBoundObservationManeuverCandidate:
    """One recomputed D1a observation and its explicitly bound V5.3 candidate.

    The concrete binding is essential evidence omitted by the nested legacy
    candidate. No slew feasibility, roll, rate, actuator or ADCS energy follows
    from this boresight alone. The wrapper is deliberately unhashable.
    """

    inputs: SimulationInputs
    target: GroundPointDefinition
    policy: GroundVisibilityPolicy
    search_start_seconds: float
    search_end_seconds: float
    search_config: GroundVisibilitySearchConfig
    first_step_start_seconds: int
    step_start_seconds: int
    request: ImagingRequest
    opportunity_id: ObservationOpportunityId
    boresight_frame: ModelInertialBoresightFrameBinding
    orbit_observation: OrbitDerivedObservationOpportunity = field(init=False)
    common_frame_boresight: CommonFrameBoresightDirection = field(init=False)
    maneuver_candidate: ObservationManeuverCandidate = field(init=False)

    __hash__ = None

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        # Avoid legacy boresight/candidate ID equality and caller text hashes.
        return (self.orbit_observation == other.orbit_observation
                and self.boresight_frame == other.boresight_frame
                and all(getattr(self.common_frame_boresight, axis)
                        == getattr(other.common_frame_boresight, axis)
                        for axis in ("x", "y", "z")))

    def __post_init__(self) -> None:
        _exact(self.boresight_frame, ModelInertialBoresightFrameBinding, "boresight_frame")
        binding = ModelInertialBoresightFrameBinding(
            self.boresight_frame.frame_id, self.boresight_frame.frame)
        observation = derive_observation_opportunity_for_engine_step(
            self.inputs, self.target, self.policy, self.search_start_seconds,
            self.search_end_seconds, self.search_config, self.first_step_start_seconds,
            self.step_start_seconds, self.request, self.opportunity_id)
        state = observation.spacecraft_state
        ray = observation.geometry.spacecraft_to_ground
        for source in (state.position, state.velocity, ray):
            frame = _frame(source.frame)
            _frame_text(frame)
            if frame.kind is not FrameKind.MODEL_INERTIAL or frame != binding.frame:
                raise ValueError("concrete/common-frame mismatch with D1a MODEL_INERTIAL evidence")
        when = _instant(state.position.instant)
        if (_instant(state.velocity.instant) != when or _instant(ray.instant) != when
                or when.elapsed_seconds != observation.step_start_seconds):
            raise ValueError("D1a direction/state instant must match the selected step start")
        boresight = CommonFrameBoresightDirection(binding.frame_id, *ray.components)
        candidate = ObservationManeuverCandidate(observation.opportunity, boresight)
        # Preserve D1a's normalized semantic inputs and original caller ID objects.
        for item in fields(self):
            if item.init and item.name != "boresight_frame":
                object.__setattr__(self, item.name, getattr(observation, item.name))
        object.__setattr__(self, "boresight_frame", binding)
        object.__setattr__(self, "orbit_observation", observation)
        object.__setattr__(self, "common_frame_boresight", boresight)
        object.__setattr__(self, "maneuver_candidate", candidate)


def derive_observation_maneuver_candidate_for_engine_step(
    inputs: SimulationInputs, target: GroundPointDefinition, policy: GroundVisibilityPolicy,
    search_start_seconds: float, search_end_seconds: float,
    search_config: GroundVisibilitySearchConfig, first_step_start_seconds: int,
    step_start_seconds: int, request: ImagingRequest, opportunity_id: ObservationOpportunityId,
    boresight_frame: ModelInertialBoresightFrameBinding,
) -> OrbitBoundObservationManeuverCandidate:
    return OrbitBoundObservationManeuverCandidate(inputs, target, policy,
        search_start_seconds, search_end_seconds, search_config, first_step_start_seconds,
        step_start_seconds, request, opportunity_id, boresight_frame)


__all__ = ["ModelInertialBoresightFrameBinding", "OrbitBoundObservationManeuverCandidate",
           "derive_observation_maneuver_candidate_for_engine_step"]
