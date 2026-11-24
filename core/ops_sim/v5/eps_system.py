"""Pure interval-level composition of V5 solar, load, and battery physics."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real

from .configuration import EPSConfig
from .eps import (BatteryTransition, BatterySubstepTransition,
                  compute_battery_transition, compute_battery_substep_transition)
from .integration_time import checked_duration
from .eps_capability import (
    EPSCapabilityResult,
    validate_eps_capability_for_config,
)
from .power_loads import PowerLoadBreakdown
from .solar import SolarGenerationResult, compute_solar_generation
from .state import BatteryState


def _validate_incidence_angle(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("incidence_angle_deg must be a real finite number")
    try:
        finite = isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError("incidence_angle_deg must be finite")
    if not 0 <= value <= 180:
        raise ValueError(
            "incidence_angle_deg must be between zero and 180 degrees"
        )


def _validate_positive_seconds(value: object) -> None:
    if type(value) is not int:
        raise TypeError("dt_seconds must be an integer")
    if value <= 0:
        raise ValueError("dt_seconds must be greater than zero")


@dataclass(frozen=True, slots=True)
class EPSIntervalInputs:
    """Explicit EPS forcing representative of one engine step interval."""

    sunlit: bool
    incidence_angle_deg: float
    load_breakdown: PowerLoadBreakdown

    def __post_init__(self) -> None:
        if type(self.sunlit) is not bool:
            raise TypeError("sunlit must be a boolean")
        _validate_incidence_angle(self.incidence_angle_deg)
        if type(self.load_breakdown) is not PowerLoadBreakdown:
            raise TypeError(
                "load_breakdown must be a PowerLoadBreakdown"
            )


@dataclass(frozen=True, slots=True)
class EPSIntervalResult:
    """Transient inspectable result of one composite EPS calculation."""

    solar: SolarGenerationResult
    loads: PowerLoadBreakdown
    battery: BatteryTransition

    def __post_init__(self) -> None:
        contracts = (
            ("solar", self.solar, SolarGenerationResult),
            ("loads", self.loads, PowerLoadBreakdown),
            ("battery", self.battery, self._battery_type()),
        )
        for field_name, value, expected_type in contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )

    def _battery_type(self):
        return BatteryTransition


@dataclass(frozen=True, slots=True)
class EPSSubstepResult(EPSIntervalResult):
    battery: BatterySubstepTransition
    def _battery_type(self):
        return BatterySubstepTransition


def compute_eps_interval_transition(
    state: BatteryState,
    config: EPSConfig,
    inputs: EPSIntervalInputs,
    *,
    dt_seconds: int,
    capability: EPSCapabilityResult | None = None,
) -> EPSIntervalResult:
    """Compose solar, load, and battery models without mutation.

    Omitting ``capability`` preserves the nominal V5.1 compatibility path.
    """
    return _compute_eps_transition(state, config, inputs, dt_seconds=dt_seconds, capability=capability)


def compute_eps_substep_transition(state, config, inputs, *, duration, capability=None):
    """Fractional internal EPS; legacy interval admission remains integer-only."""
    return _compute_eps_transition(state, config, inputs,
        dt_seconds=checked_duration(duration), capability=capability, _duration=duration)


def _compute_eps_transition(state, config, inputs, *, dt_seconds, capability, _duration=None):
    if type(state) is not BatteryState:
        raise TypeError("state must be a BatteryState")
    if type(config) is not EPSConfig:
        raise TypeError("config must be an EPSConfig")
    if type(inputs) is not EPSIntervalInputs:
        raise TypeError("inputs must be EPSIntervalInputs")
    if capability is not None:
        validate_eps_capability_for_config(capability, config)
    if _duration is None:
        _validate_positive_seconds(dt_seconds)

    if capability is None:
        solar_capability_w = None
        battery_capacity_wh = None
    else:
        solar_capability_w = (
            capability.solar_nominal_generation_capability_w
        )
        battery_capacity_wh = capability.battery_usable_capacity_wh

    solar = compute_solar_generation(
        config.solar_array,
        sunlit=inputs.sunlit,
        incidence_angle_deg=inputs.incidence_angle_deg,
        nominal_generation_capability_w=solar_capability_w,
    )
    if _duration is None:
        battery = compute_battery_transition(state, config.battery,
            generation_w=solar.generation_w, load_w=inputs.load_breakdown.total_load_w,
            dt_seconds=dt_seconds, usable_capacity_wh=battery_capacity_wh)
    else:
        battery = compute_battery_substep_transition(state, config.battery,
            generation_w=solar.generation_w, load_w=inputs.load_breakdown.total_load_w,
            duration=_duration, usable_capacity_wh=battery_capacity_wh)
    result_type = EPSIntervalResult if _duration is None else EPSSubstepResult
    return result_type(
        solar=solar,
        loads=inputs.load_breakdown,
        battery=battery,
    )


__all__ = [
    "EPSIntervalInputs",
    "EPSIntervalResult",
    "compute_eps_interval_transition",
]
