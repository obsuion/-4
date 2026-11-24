"""Station-owned geometric candidates, with no serviceability or contact IDs.

C2c owns the complete engine-grid visibility proof. This adapter retains that
evidence and labels each compact source block with an explicit station ID.
RF, availability, allocation, electrical feasibility and delivery remain
outside this contract. Station/search evidence remains external to B2 and is
recomputed after restart, never persisted. See D310 and S007/S008.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .context import SimulationInputs
from .ids import GroundStationId
from .orbit_binding import _id
from .orbit_config import _exact
from .orbit_geometry import GroundPointDefinition
from .orbit_visibility import GroundVisibilityPolicy
from .orbit_visibility_grid import (
    EngineGridVisibilityBlock, GroundVisibilityGridProjection,
    project_ground_visibility_to_engine_grid,
)
from .orbit_visibility_windows import GroundVisibilitySearchConfig


@dataclass(frozen=True, slots=True)
class GeometricGroundContactBlock:
    """One station label and one compact geometry-only visibility block.

    Standalone construction revalidates the supplied evidence; it does not
    establish visibility independently. Complete geographic/search evidence
    belongs to GroundStationContactProjection. Nested reconstruction preserves
    source value equality, without promising Python object identity.
    """

    station_id: GroundStationId
    source_visibility_block: EngineGridVisibilityBlock

    def __post_init__(self) -> None:
        station_id = _id(self.station_id, GroundStationId)
        source = self.source_visibility_block
        _exact(source, EngineGridVisibilityBlock, "source_visibility_block")
        source = EngineGridVisibilityBlock(source.first_start_time_seconds,
            source.timestep_seconds, source.step_count, source.source_window)
        object.__setattr__(self, "station_id", station_id)
        object.__setattr__(self, "source_visibility_block", source)

    @property
    def first_start_time_seconds(self) -> int:
        return self.source_visibility_block.first_start_time_seconds

    @property
    def timestep_seconds(self) -> int:
        return self.source_visibility_block.timestep_seconds

    @property
    def step_count(self) -> int:
        return self.source_visibility_block.step_count

    @property
    def last_end_time_seconds(self) -> int:
        return self.source_visibility_block.last_end_time_seconds

    @property
    def represented_duration_seconds(self) -> int:
        return self.source_visibility_block.represented_duration_seconds


@dataclass(frozen=True, slots=True)
class GroundStationContactProjection:
    """One C2c composition retaining the complete normalized station evidence.

    Each source block maps to one candidate, in source order, without timing
    changes. The C2c resolution flag is copied without a stronger completeness
    claim. Derived fields cannot be constructor inputs; replace recomputes.
    """

    inputs: SimulationInputs
    station: GroundPointDefinition
    policy: GroundVisibilityPolicy
    search_start_seconds: float
    search_end_seconds: float
    search_config: GroundVisibilitySearchConfig
    first_step_start_seconds: int
    visibility_projection: GroundVisibilityGridProjection = field(init=False)
    contact_blocks: tuple[GeometricGroundContactBlock, ...] = field(init=False)
    total_step_count: int = field(init=False)
    all_search_cells_resolved: bool = field(init=False)

    def __post_init__(self) -> None:
        # Reject targets even when the search/grid would produce no blocks.
        # C2c's C1/C2a/C2b owners revalidate the complete ORIGINAL input graph.
        _exact(self.station, GroundPointDefinition, "station")
        _exact(self.station.point_id, GroundStationId, "station.point_id")
        projection = project_ground_visibility_to_engine_grid(self.inputs,
            self.station, self.policy, self.search_start_seconds,
            self.search_end_seconds, self.search_config, self.first_step_start_seconds)
        blocks = tuple(GeometricGroundContactBlock(projection.point.point_id, block)
                       for block in projection.blocks)
        values = {
            "inputs": projection.inputs, "station": projection.point,
            "policy": projection.policy,
            "search_start_seconds": projection.search_start_seconds,
            "search_end_seconds": projection.search_end_seconds,
            "search_config": projection.search_config,
            "first_step_start_seconds": projection.first_step_start_seconds,
            "visibility_projection": projection, "contact_blocks": blocks,
            "total_step_count": projection.total_step_count,
            "all_search_cells_resolved": projection.all_search_cells_resolved,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)


def generate_geometric_ground_contacts(
    inputs: SimulationInputs, station: GroundPointDefinition, policy: GroundVisibilityPolicy,
    search_start_seconds: float, search_end_seconds: float,
    search_config: GroundVisibilitySearchConfig, first_step_start_seconds: int,
) -> GroundStationContactProjection:
    return GroundStationContactProjection(inputs, station, policy, search_start_seconds,
        search_end_seconds, search_config, first_step_start_seconds)


__all__ = ["GeometricGroundContactBlock", "GroundStationContactProjection",
           "generate_geometric_ground_contacts"]
