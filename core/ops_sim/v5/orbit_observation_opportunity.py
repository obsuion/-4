"""One certified engine step and one instantaneous local observation direction.

C2c owns whole-step visibility. One additional B1/C1 snapshot at the selected
start supplies local pointing only, not tracking, configured view feasibility,
common-frame boresight, scheduling or execution. All evidence is transient and
external to B2 content; see D312/S008.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from math import degrees, nextafter, pi, tau

from .context import SimulationInputs
from .frames import CartesianState
from .ids import GroundTargetId, ImagingRequestId, ObservationOpportunityId
from .observation import ImagingRequest, ObservationOpportunity, ObservationPointing
from .orbit import evaluate_two_body_state
from .orbit_config import GeometryInstant, _exact
from .orbit_geometry import GroundPointDefinition, GroundPointGeometry, evaluate_ground_point_geometry
from .orbit_visibility import GroundVisibilityPolicy
from .orbit_visibility_grid import (
    EngineGridVisibilityBlock, GroundVisibilityGridProjection,
    project_ground_visibility_to_engine_grid,
)
from .orbit_visibility_windows import GroundVisibilitySearchConfig


def _same_id(left, right):
    # Exact owner types are admitted before construction. Legacy ID text may
    # overload equality/hash; base str comparison preserves its actual content.
    return type(left) is type(right) and str.__eq__(left.value, right.value) is True


def _degrees_in_domain(angle, upper_rad, upper_deg, name):
    if not 0 <= angle < upper_rad:
        raise ValueError(name + " is outside the V5.3 pointing domain")
    converted = degrees(angle)
    # Only a strictly interior source may receive this <=1-ulp coordinate
    # representation correction. No physical angle is clipped or quantized.
    if converted == upper_deg:
        converted = nextafter(upper_deg, 0.0)
    return converted


def _pointing(geometry):
    view = _degrees_in_domain(geometry.off_nadir_rad, pi/2, 90., "off-nadir angle")
    status = geometry.orbital_azimuth_status
    if status == "resolved":
        if geometry.orbital_azimuth_rad is None:
            raise ValueError("resolved orbital azimuth must be present")
        azimuth = _degrees_in_domain(geometry.orbital_azimuth_rad, tau, 360., "orbital azimuth")
    elif status == "zero_projection" and geometry.off_nadir_rad == 0:
        # At exact modeled nadir azimuth has no directional effect. Zero is a
        # coordinate convention, not measured azimuth evidence.
        azimuth = 0.0
    else:
        raise ValueError("orbital azimuth is unresolved or has non-nadir zero projection")
    return ObservationPointing(view, azimuth)


@dataclass(frozen=True, slots=True, eq=False)
class OrbitDerivedObservationOpportunity:
    """Required external inputs, recomputed evidence, no precomputed authority.

    Equality includes actual external ID content without invoking caller text
    overloads. The transient wrapper is explicitly unhashable. The nested
    opportunity is the unchanged V5.3 value and retains its own owner semantics.
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
    visibility_projection: GroundVisibilityGridProjection = field(init=False)
    supporting_visibility_block: EngineGridVisibilityBlock = field(init=False)
    spacecraft_state: CartesianState = field(init=False)
    geometry: GroundPointGeometry = field(init=False)
    opportunity: ObservationOpportunity = field(init=False)

    __hash__ = None

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        a, b = self.request, other.request
        left, right = self.opportunity, other.opportunity
        return (_same_id(a.request_id, b.request_id)
            and _same_id(a.target_id, b.target_id)
            and a.priority_weight == b.priority_weight
            and _same_id(self.opportunity_id, other.opportunity_id)
            and _same_id(left.opportunity_id, right.opportunity_id)
            and _same_id(left.request_id, right.request_id)
            and all(getattr(left, f.name) == getattr(right, f.name)
                    for f in fields(left) if f.name not in ("opportunity_id", "request_id"))
            and all(getattr(self, f.name) == getattr(other, f.name)
                    for f in fields(self) if f.name not in ("request", "opportunity_id", "opportunity")))

    def __post_init__(self) -> None:
        _exact(self.target, GroundPointDefinition, "target")
        _exact(self.target.point_id, GroundTargetId, "target.point_id")
        _exact(self.request, ImagingRequest, "request")
        _exact(self.request.request_id, ImagingRequestId, "request.request_id")
        _exact(self.request.target_id, GroundTargetId, "request.target_id")
        _exact(self.opportunity_id, ObservationOpportunityId, "opportunity_id")
        _exact(self.step_start_seconds, int, "step_start_seconds")
        # Existing V5.3 values check ID types but do not revalidate ID text.
        # Reconstruct only for validation; retain the original caller ID objects.
        ImagingRequestId(self.request.request_id.value)
        GroundTargetId(self.request.target_id.value)
        ObservationOpportunityId(self.opportunity_id.value)
        request = ImagingRequest(self.request.request_id, self.request.target_id,
                                 self.request.priority_weight)
        projection = project_ground_visibility_to_engine_grid(self.inputs, self.target,
            self.policy, self.search_start_seconds, self.search_end_seconds,
            self.search_config, self.first_step_start_seconds)
        if not _same_id(request.target_id, projection.point.point_id):
            raise ValueError("request target does not match visibility target")
        start, timestep = self.step_start_seconds, projection.timestep_seconds
        if not 0 <= start < projection.inputs.common_world.horizon_seconds:
            raise ValueError("selected engine-step start must lie within the common-world horizon")
        end = start + timestep
        supporting = None
        for block in projection.blocks:
            first = block.first_start_time_seconds
            if start >= first and end <= block.last_end_time_seconds and (start-first) % timestep == 0:
                if supporting is not None:
                    raise ValueError("inconsistent visibility support: more than one block contains the engine step")
                supporting = block
        if supporting is None:
            raise ValueError("selected engine step lacks visibility support in a single C2c block")
        coast = projection.inputs.coast_orbit
        instant = GeometryInstant(coast.trajectory.initial_state.position.instant.epoch, start)
        state = evaluate_two_body_state(coast.trajectory, instant, coast.solver_config)
        geometry = evaluate_ground_point_geometry(projection.point, state)
        opportunity = ObservationOpportunity(self.opportunity_id, request.request_id,
            start, end, timestep, _pointing(geometry))
        values = {
            "inputs": projection.inputs, "target": projection.point, "policy": projection.policy,
            "search_start_seconds": projection.search_start_seconds,
            "search_end_seconds": projection.search_end_seconds,
            "search_config": projection.search_config,
            "first_step_start_seconds": projection.first_step_start_seconds,
            "request": request, "visibility_projection": projection,
            "supporting_visibility_block": supporting, "spacecraft_state": state,
            "geometry": geometry, "opportunity": opportunity,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)


def derive_observation_opportunity_for_engine_step(
    inputs: SimulationInputs, target: GroundPointDefinition, policy: GroundVisibilityPolicy,
    search_start_seconds: float, search_end_seconds: float,
    search_config: GroundVisibilitySearchConfig, first_step_start_seconds: int,
    step_start_seconds: int, request: ImagingRequest, opportunity_id: ObservationOpportunityId,
) -> OrbitDerivedObservationOpportunity:
    return OrbitDerivedObservationOpportunity(inputs, target, policy, search_start_seconds,
        search_end_seconds, search_config, first_step_start_seconds, step_start_seconds,
        request, opportunity_id)


__all__ = ["OrbitDerivedObservationOpportunity", "derive_observation_opportunity_for_engine_step"]
