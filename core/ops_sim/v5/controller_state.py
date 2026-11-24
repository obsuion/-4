"""Authoritative planner memory without controller implementation."""

from __future__ import annotations

from dataclasses import dataclass

from .ids import ControllerId, PlanId


@dataclass(slots=True)
class ControllerState:
    """Track minimal mutable memory for a future mission controller."""

    controller_id: ControllerId
    latest_plan_id: PlanId | None
    replan_count: int

    def __post_init__(self) -> None:
        if type(self.controller_id) is not ControllerId:
            raise TypeError("controller_id must be a ControllerId")
        if (
            self.latest_plan_id is not None
            and type(self.latest_plan_id) is not PlanId
        ):
            raise TypeError("latest_plan_id must be a PlanId or None")
        if type(self.replan_count) is not int:
            raise TypeError("replan_count must be an integer")
        if self.replan_count < 0:
            raise ValueError("replan_count must be greater than or equal to zero")


__all__ = ["ControllerState"]
