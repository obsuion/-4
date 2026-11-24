"""Pure Level-1 solar generation from explicit illumination geometry."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, radians
from numbers import Real

from .configuration import SolarArrayConfig


def _validate_finite_real(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class SolarGenerationResult:
    """Transient Level-1 solar-source geometry and current nominal capability.

    ``nominal_generation_w`` is the bus-side electrical capability under full
    direct illumination and zero-degree incidence before geometry is applied.
    """

    nominal_generation_w: float
    sunlit: bool
    incidence_angle_deg: float

    def __post_init__(self) -> None:
        _validate_finite_real(
            "nominal_generation_w",
            self.nominal_generation_w,
        )
        if self.nominal_generation_w <= 0:
            raise ValueError(
                "nominal_generation_w must be strictly greater than zero"
            )
        if type(self.sunlit) is not bool:
            raise TypeError("sunlit must be a boolean")
        _validate_finite_real(
            "incidence_angle_deg",
            self.incidence_angle_deg,
        )
        if not 0 <= self.incidence_angle_deg <= 180:
            raise ValueError(
                "incidence_angle_deg must be between zero and 180 degrees"
            )

    @property
    def illumination_factor(self) -> float:
        """Return one for direct illumination and zero for eclipse."""
        return 1.0 if self.sunlit else 0.0

    @property
    def incidence_factor(self) -> float:
        """Return the one-sided cosine response of the solar-array face."""
        if self.incidence_angle_deg >= 90:
            return 0.0
        return cos(radians(self.incidence_angle_deg))

    @property
    def generation_w(self) -> float:
        """Return derived bus-side generation for the supplied geometry."""
        return (
            self.nominal_generation_w
            * self.illumination_factor
            * self.incidence_factor
        )


def compute_solar_generation(
    config: SolarArrayConfig,
    *,
    sunlit: bool,
    incidence_angle_deg: float,
    nominal_generation_capability_w: float | None = None,
) -> SolarGenerationResult:
    """Compute solar bus power from explicit illumination and incidence.

    The optional runtime capability is interpreted as bus-side output under
    full direct illumination and zero-degree incidence. Omitting it preserves
    the nominal configured behavior for compatibility. Orbit and attitude
    remain external to this function.
    """
    if type(config) is not SolarArrayConfig:
        raise TypeError("config must be a SolarArrayConfig")
    configured_nominal_w = config.nominal_generation_w.value
    if nominal_generation_capability_w is None:
        active_nominal_w = configured_nominal_w
    else:
        _validate_finite_real(
            "nominal_generation_capability_w",
            nominal_generation_capability_w,
        )
        if nominal_generation_capability_w <= 0:
            raise ValueError(
                "nominal_generation_capability_w must be greater than zero"
            )
        if nominal_generation_capability_w > configured_nominal_w:
            raise ValueError(
                "nominal_generation_capability_w must not exceed configured "
                "nominal generation"
            )
        active_nominal_w = nominal_generation_capability_w
    return SolarGenerationResult(
        active_nominal_w,
        sunlit,
        incidence_angle_deg,
    )


__all__ = [
    "SolarGenerationResult",
    "compute_solar_generation",
]
