"""Immutable realised comparison-world identity for V5 experiments."""

from __future__ import annotations

from dataclasses import dataclass

from .ids import ScenarioId, WorldEventId, WorldId


@dataclass(frozen=True, slots=True)
class CommonWorld:
    """Describe one horizon-specific realised world shared by comparisons."""

    world_id: WorldId
    scenario_id: ScenarioId
    horizon_seconds: int
    event_ids: tuple[WorldEventId, ...]

    def __post_init__(self) -> None:
        if type(self.world_id) is not WorldId:
            raise TypeError("world_id must be a WorldId")
        if type(self.scenario_id) is not ScenarioId:
            raise TypeError("scenario_id must be a ScenarioId")
        if type(self.horizon_seconds) is not int:
            raise TypeError("horizon_seconds must be an integer")
        if self.horizon_seconds < 0:
            raise ValueError("horizon_seconds must be greater than or equal to zero")
        if type(self.event_ids) is not tuple:
            raise TypeError("event_ids must be a tuple")
        if not all(type(event_id) is WorldEventId for event_id in self.event_ids):
            raise TypeError("event_ids must contain only WorldEventId values")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("event_ids must not contain duplicates")


__all__ = ["CommonWorld"]
