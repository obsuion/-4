"""Authoritative mission-identity state for the V5 runtime."""

from __future__ import annotations

from dataclasses import dataclass

from .ids import (
    CommandId,
    DataProductId,
    MissionRequestId,
    PlanId,
    WorldEventId,
)


def _validate_id_tuple(
    name: str,
    value: object,
    expected_type: type,
) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    if not all(type(item) is expected_type for item in value):
        raise TypeError(
            f"{name} must contain only {expected_type.__name__} values"
        )
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not contain duplicates")


@dataclass(slots=True)
class MissionState:
    """Track authoritative mission object identities without derived totals."""

    pending_request_ids: tuple[MissionRequestId, ...]
    completed_request_ids: tuple[MissionRequestId, ...]
    data_product_ids: tuple[DataProductId, ...]
    active_plan_id: PlanId | None
    command_ids: tuple[CommandId, ...]
    resolved_world_event_ids: tuple[WorldEventId, ...]

    def __post_init__(self) -> None:
        contracts = (
            (
                "pending_request_ids",
                self.pending_request_ids,
                MissionRequestId,
            ),
            (
                "completed_request_ids",
                self.completed_request_ids,
                MissionRequestId,
            ),
            ("data_product_ids", self.data_product_ids, DataProductId),
            ("command_ids", self.command_ids, CommandId),
            (
                "resolved_world_event_ids",
                self.resolved_world_event_ids,
                WorldEventId,
            ),
        )
        for name, value, expected_type in contracts:
            _validate_id_tuple(name, value, expected_type)
        if (
            self.active_plan_id is not None
            and type(self.active_plan_id) is not PlanId
        ):
            raise TypeError("active_plan_id must be a PlanId or None")
        if set(self.pending_request_ids) & set(self.completed_request_ids):
            raise ValueError(
                "pending and completed request IDs must be disjoint"
            )


__all__ = ["MissionState"]
