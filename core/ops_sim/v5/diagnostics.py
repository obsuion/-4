"""Non-causal observations of V5 simulation execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Diagnostics:
    """Observe execution without becoming input to physics or mission control."""

    completed_steps: int

    def __post_init__(self) -> None:
        if type(self.completed_steps) is not int:
            raise TypeError("completed_steps must be an integer")
        if self.completed_steps < 0:
            raise ValueError(
                "completed_steps must be greater than or equal to zero"
            )


__all__ = ["Diagnostics"]
