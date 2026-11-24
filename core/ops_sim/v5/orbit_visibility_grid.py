"""Exact projection of C2b-certified visibility onto complete engine intervals.

One C2b search owns all physical/numerical visibility decisions. This adapter
uses only its certified windows and the active integer-second main timestep.
Blocks are compact arithmetic progressions, not serviceability, scheduling,
capacity, acquisition authorization or engine execution. D040/D309 define the
half-open containment. No search/grid evidence is persisted or added to B2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .context import SimulationInputs, _validate_inputs
from .orbit_config import _exact
from .orbit_geometry import GroundPointDefinition
from .orbit_visibility import GroundVisibilityPolicy
from .orbit_visibility_windows import (
    GroundVisibilitySearchConfig, GroundVisibilitySearchResult,
    GroundVisibilityWindow, TemporalVisibilityStatus,
    find_ground_visibility_windows,
)


def _window(value: object) -> GroundVisibilityWindow:
    _exact(value, GroundVisibilityWindow, "source_window")
    # Reuse C2b admission/normalization, then perform all containment on exact
    # rational representations of the admitted binary boundaries.
    return GroundVisibilityWindow(value.start_seconds, value.end_seconds)


def _grid(first: int, timestep: int) -> None:
    _exact(first, int, "first_start_time_seconds")
    _exact(timestep, int, "timestep_seconds")
    if first < 0 or timestep <= 0:
        raise ValueError("grid requires a nonnegative first boundary and positive timestep")


@dataclass(frozen=True, slots=True)
class EngineGridVisibilityBlock:
    """Exactly count intervals [first+k*dt,first+(k+1)*dt), 0<=k<count.

    Both containment boundaries allow equality. The first start need not be
    divisible by dt: the caller's explicit future boundary defines the phase.
    This standalone value records containment, not independent visibility proof.
    """

    first_start_time_seconds: int
    timestep_seconds: int
    step_count: int
    source_window: GroundVisibilityWindow

    def __post_init__(self) -> None:
        _grid(self.first_start_time_seconds, self.timestep_seconds)
        _exact(self.step_count, int, "step_count")
        if self.step_count <= 0:
            raise ValueError("step_count must be positive")
        window = _window(self.source_window)
        if (self.first_start_time_seconds < Fraction(window.start_seconds)
                or self.last_end_time_seconds > Fraction(window.end_seconds)):
            raise ValueError("complete block must lie inside its source window")
        object.__setattr__(self, "source_window", window)

    @property
    def last_end_time_seconds(self) -> int:
        return self.first_start_time_seconds+self.represented_duration_seconds

    @property
    def represented_duration_seconds(self) -> int:
        return self.timestep_seconds*self.step_count


def _project_window(window, first, timestep):
    """At most one block per window; work/storage independent of step count."""
    _grid(first, timestep)
    window = _window(window)
    left, right = Fraction(window.start_seconds), Fraction(window.end_seconds)
    lower = max(left, first)
    # ceil(x)=-floor(-x); Fraction // int returns an exact Python integer.
    k_first = max(0, -((first-lower)//timestep))
    k_last = (right-first-timestep)//timestep
    if k_last < k_first:
        return None
    return EngineGridVisibilityBlock(first+k_first*timestep, timestep,
                                     k_last-k_first+1, window)


@dataclass(frozen=True, slots=True)
class GroundVisibilityGridProjection:
    """Original search inputs composed once; all derived evidence recomputes.

    all_search_cells_resolved states only that no C2b cell is UNRESOLVED.
    complete_to_tolerance can be true while this flag is false. Certified
    blocks remain valid when the remainder of the search retains uncertainty.
    Point/policy/config/confinement/origin remain external to B2 content.
    """

    inputs: SimulationInputs
    point: GroundPointDefinition
    policy: GroundVisibilityPolicy
    search_start_seconds: float
    search_end_seconds: float
    search_config: GroundVisibilitySearchConfig
    first_step_start_seconds: int
    search_result: GroundVisibilitySearchResult = field(init=False)
    timestep_seconds: int = field(init=False)
    blocks: tuple[EngineGridVisibilityBlock, ...] = field(init=False)
    total_step_count: int = field(init=False)
    all_search_cells_resolved: bool = field(init=False)

    def __post_init__(self) -> None:
        _validate_inputs(self.inputs)
        _exact(self.first_step_start_seconds, int, "first_step_start_seconds")
        if not 0 <= self.first_step_start_seconds <= self.inputs.common_world.horizon_seconds:
            raise ValueError("first future boundary must lie within the common-world horizon")
        # Even an origin after search_end must validate and compose the search.
        # C2b owns the point/policy/config/confinement and B2 coast admission.
        search = find_ground_visibility_windows(self.inputs, self.point, self.policy,
            self.search_start_seconds, self.search_end_seconds, self.search_config)
        timestep = search.inputs.numerical_config.timestep_seconds
        _grid(self.first_step_start_seconds, timestep)
        blocks = tuple(block for window in search.visible_windows
                       if (block := _project_window(window, self.first_step_start_seconds, timestep)) is not None)
        values = {
            "inputs": search.inputs, "point": search.point, "policy": search.policy,
            "search_start_seconds": search.start_seconds, "search_end_seconds": search.end_seconds,
            "search_config": search.config, "search_result": search, "timestep_seconds": timestep,
            "blocks": blocks, "total_step_count": sum(block.step_count for block in blocks),
            "all_search_cells_resolved": all(cell.status is not TemporalVisibilityStatus.UNRESOLVED
                                              for cell in search.cells),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)


def project_ground_visibility_to_engine_grid(
    inputs: SimulationInputs, point: GroundPointDefinition, policy: GroundVisibilityPolicy,
    search_start_seconds: float, search_end_seconds: float,
    search_config: GroundVisibilitySearchConfig, first_step_start_seconds: int,
) -> GroundVisibilityGridProjection:
    return GroundVisibilityGridProjection(inputs, point, policy, search_start_seconds,
        search_end_seconds, search_config, first_step_start_seconds)


__all__ = ["EngineGridVisibilityBlock", "GroundVisibilityGridProjection",
           "project_ground_visibility_to_engine_grid"]
