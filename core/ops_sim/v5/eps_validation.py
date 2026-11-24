"""Pure observable conservation accounting for completed V5 EPS intervals."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real

from .eps_system import EPSIntervalResult


_SECONDS_PER_HOUR = 3600.0


def _validate_finite_real(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError(f"{name} must be finite")


def _validate_nonnegative_real(name: str, value: object) -> None:
    _validate_finite_real(name, value)
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


def _validated_dt_hours(dt_seconds: object) -> float:
    if type(dt_seconds) is not int:
        raise TypeError("dt_seconds must be an integer")
    if dt_seconds <= 0:
        raise ValueError("dt_seconds must be greater than zero")
    try:
        dt_hours = dt_seconds / _SECONDS_PER_HOUR
    except OverflowError as error:
        raise ValueError(
            "dt_seconds cannot be represented as finite hours"
        ) from error
    if not isfinite(dt_hours) or dt_hours <= 0:
        raise ValueError(
            "dt_seconds cannot be represented as finite positive hours"
        )
    return dt_hours


@dataclass(frozen=True, slots=True)
class EPSConservationReport:
    """Explicit energy and power-link residuals for one EPS interval."""

    dt_seconds: int
    generation_energy_wh: float
    requested_load_energy_wh: float
    served_load_energy_wh: float
    unmet_load_energy_wh: float
    charge_input_energy_wh: float
    discharge_output_energy_wh: float
    curtailed_generation_energy_wh: float
    conversion_loss_wh: float
    battery_energy_change_wh: float
    generation_link_residual_w: float
    load_link_residual_w: float
    bus_energy_residual_wh: float
    load_service_residual_wh: float
    battery_energy_residual_wh: float

    def __post_init__(self) -> None:
        if type(self.dt_seconds) is not int:
            raise TypeError("dt_seconds must be an integer")
        if self.dt_seconds <= 0:
            raise ValueError("dt_seconds must be greater than zero")

        for field_name, value in (
            ("generation_energy_wh", self.generation_energy_wh),
            ("requested_load_energy_wh", self.requested_load_energy_wh),
            ("served_load_energy_wh", self.served_load_energy_wh),
            ("unmet_load_energy_wh", self.unmet_load_energy_wh),
            ("charge_input_energy_wh", self.charge_input_energy_wh),
            ("discharge_output_energy_wh", self.discharge_output_energy_wh),
            (
                "curtailed_generation_energy_wh",
                self.curtailed_generation_energy_wh,
            ),
            ("conversion_loss_wh", self.conversion_loss_wh),
        ):
            _validate_nonnegative_real(field_name, value)

        for field_name, value in (
            ("battery_energy_change_wh", self.battery_energy_change_wh),
            ("generation_link_residual_w", self.generation_link_residual_w),
            ("load_link_residual_w", self.load_link_residual_w),
            ("bus_energy_residual_wh", self.bus_energy_residual_wh),
            ("load_service_residual_wh", self.load_service_residual_wh),
            ("battery_energy_residual_wh", self.battery_energy_residual_wh),
        ):
            _validate_finite_real(field_name, value)

    @property
    def max_abs_energy_residual_wh(self) -> float:
        """Return the largest absolute conservation residual in Wh."""
        return max(
            abs(self.bus_energy_residual_wh),
            abs(self.load_service_residual_wh),
            abs(self.battery_energy_residual_wh),
        )

    @property
    def max_abs_power_link_residual_w(self) -> float:
        """Return the largest absolute inter-model power-link residual in W."""
        return max(
            abs(self.generation_link_residual_w),
            abs(self.load_link_residual_w),
        )

    def is_within_tolerance(
        self,
        absolute_energy_tolerance_wh: float,
        *,
        absolute_power_tolerance_w: float,
    ) -> bool:
        """Return whether every explicit residual meets caller tolerances."""
        _validate_nonnegative_real(
            "absolute_energy_tolerance_wh",
            absolute_energy_tolerance_wh,
        )
        _validate_nonnegative_real(
            "absolute_power_tolerance_w",
            absolute_power_tolerance_w,
        )
        return (
            self.max_abs_energy_residual_wh <= absolute_energy_tolerance_wh
            and self.max_abs_power_link_residual_w
            <= absolute_power_tolerance_w
        )


def compute_eps_conservation_report(
    result: EPSIntervalResult,
) -> EPSConservationReport:
    """Derive an uncorrected conservation report from one EPS result."""
    if type(result) is not EPSIntervalResult:
        raise TypeError("result must be an EPSIntervalResult")

    battery = result.battery
    dt_hours = _validated_dt_hours(battery.dt_seconds)
    generation_energy_wh = result.solar.generation_w * dt_hours
    requested_load_energy_wh = result.loads.total_load_w * dt_hours
    served_load_energy_wh = battery.served_load_w * dt_hours
    unmet_load_energy_wh = battery.unmet_load_w * dt_hours
    charge_input_energy_wh = battery.charge_input_w * dt_hours
    discharge_output_energy_wh = battery.discharge_output_w * dt_hours
    curtailed_generation_energy_wh = (
        battery.curtailed_generation_w * dt_hours
    )
    conversion_loss_wh = battery.conversion_loss_wh
    battery_energy_change_wh = battery.end_energy_wh - battery.start_energy_wh

    generation_link_residual_w = (
        battery.generation_w - result.solar.generation_w
    )
    load_link_residual_w = battery.load_w - result.loads.total_load_w
    bus_energy_residual_wh = (
        generation_energy_wh
        + discharge_output_energy_wh
        - served_load_energy_wh
        - charge_input_energy_wh
        - curtailed_generation_energy_wh
    )
    load_service_residual_wh = (
        requested_load_energy_wh
        - served_load_energy_wh
        - unmet_load_energy_wh
    )
    battery_energy_residual_wh = battery_energy_change_wh - (
        charge_input_energy_wh
        - discharge_output_energy_wh
        - conversion_loss_wh
    )

    return EPSConservationReport(
        dt_seconds=battery.dt_seconds,
        generation_energy_wh=generation_energy_wh,
        requested_load_energy_wh=requested_load_energy_wh,
        served_load_energy_wh=served_load_energy_wh,
        unmet_load_energy_wh=unmet_load_energy_wh,
        charge_input_energy_wh=charge_input_energy_wh,
        discharge_output_energy_wh=discharge_output_energy_wh,
        curtailed_generation_energy_wh=curtailed_generation_energy_wh,
        conversion_loss_wh=conversion_loss_wh,
        battery_energy_change_wh=battery_energy_change_wh,
        generation_link_residual_w=generation_link_residual_w,
        load_link_residual_w=load_link_residual_w,
        bus_energy_residual_wh=bus_energy_residual_wh,
        load_service_residual_wh=load_service_residual_wh,
        battery_energy_residual_wh=battery_energy_residual_wh,
    )


__all__ = [
    "EPSConservationReport",
    "compute_eps_conservation_report",
]
