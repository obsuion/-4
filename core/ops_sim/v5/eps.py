"""Pure source-aware Level-1 battery energy-balance physics for V5."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real

from .configuration import BatteryConfig
from .integration_time import DyadicDuration, checked_duration, validate_substep_seconds
from .state import BatteryState


_SECONDS_PER_HOUR = 3600.0


def _validate_nonnegative_real(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


def _validate_positive_seconds(value: object) -> None:
    if type(value) is not int:
        raise TypeError("dt_seconds must be an integer")
    if value <= 0:
        raise ValueError("dt_seconds must be greater than zero")


def _validated_dt_hours(value: object) -> float:
    """Return a finite positive hour duration for an exact integer dt."""
    _validate_positive_seconds(value)
    try:
        dt_hours = value / _SECONDS_PER_HOUR
    except OverflowError as error:
        raise ValueError(
            "dt_seconds cannot be represented as finite hours"
        ) from error
    if not isfinite(dt_hours) or dt_hours <= 0:
        raise ValueError(
            "dt_seconds cannot be represented as finite positive hours"
        )
    return dt_hours


def _real_as_integer_ratio(value: Real) -> tuple[int, int]:
    """Return a validated exact ratio for one admitted finite real value."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("value must be a real finite number")

    try:
        index_method = getattr(value, "__index__", None)
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise ValueError(
            "value cannot provide an exact integer ratio"
        ) from error
    if callable(index_method):
        try:
            integer_value = index_method()
        except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
            raise ValueError(
                "value cannot be represented as an exact integer ratio"
            ) from error
        if type(integer_value) is not int:
            raise ValueError("value exact integer must be a Python int")
        try:
            is_exact_integer = bool(value == integer_value)
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                "value cannot validate its exact integer representation"
            ) from error
        if is_exact_integer:
            return integer_value, 1

    try:
        finite = isfinite(value)
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise ValueError("value must be finite") from error
    if not finite:
        raise ValueError("value must be finite")

    try:
        ratio_method = getattr(value, "as_integer_ratio", None)
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise ValueError(
            "value cannot provide an exact integer ratio"
        ) from error

    if callable(ratio_method):
        try:
            numerator, denominator = ratio_method()
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                "value cannot provide an exact integer ratio"
            ) from error
        if type(numerator) is not int or type(denominator) is not int:
            raise ValueError(
                "value exact ratio must contain integer numerator and "
                "denominator"
            )
        if denominator <= 0:
            raise ValueError(
                "value exact ratio denominator must be positive"
            )
        return numerator, denominator

    try:
        float_value = float(value)
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise ValueError(
            "value cannot be represented as a finite number"
        ) from error
    if not isfinite(float_value):
        raise ValueError("value cannot be represented as a finite number")
    numerator, denominator = float_value.as_integer_ratio()
    return int(numerator), int(denominator)


def _product_ratio(*values: Real) -> tuple[int, int]:
    """Return the exact rational product of finite binary values."""
    numerator = 1
    denominator = 1
    for value in values:
        value_numerator, value_denominator = _real_as_integer_ratio(value)
        numerator *= value_numerator
        denominator *= value_denominator
    return numerator, denominator


def _quotient_ratio(
    numerator_values: tuple[Real, ...],
    denominator_values: tuple[Real, ...],
) -> tuple[int, int]:
    """Return an exact rational product divided by positive products."""
    numerator, denominator = _product_ratio(*numerator_values)
    divisor_numerator, divisor_denominator = _product_ratio(
        *denominator_values
    )
    return (
        numerator * divisor_denominator,
        denominator * divisor_numerator,
    )


def _ratio_sum(
    left: tuple[int, int],
    right: tuple[int, int],
) -> tuple[int, int]:
    """Return the exact sum of two rational values."""
    left_numerator, left_denominator = left
    right_numerator, right_denominator = right
    return (
        left_numerator * right_denominator
        + right_numerator * left_denominator,
        left_denominator * right_denominator,
    )


def _ratio_difference(
    left: tuple[int, int],
    right: tuple[int, int],
) -> tuple[int, int]:
    """Return the exact nonnegative difference of two rational values."""
    left_numerator, left_denominator = left
    right_numerator, right_denominator = right
    return (
        left_numerator * right_denominator
        - right_numerator * left_denominator,
        left_denominator * right_denominator,
    )


def _ratio_at_least(
    left: tuple[int, int],
    right: tuple[int, int],
) -> bool:
    """Compare nonnegative rational values without floating overflow."""
    left_numerator, left_denominator = left
    right_numerator, right_denominator = right
    return (
        left_numerator * right_denominator
        >= right_numerator * left_denominator
    )


def _finite_ratio_value(
    name: str,
    ratio: tuple[int, int],
    *,
    require_positive: bool = False,
) -> float:
    """Convert an exact ratio or reject an unrepresentable public value."""
    numerator, denominator = ratio
    try:
        value = numerator / denominator
    except (OverflowError, ZeroDivisionError) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if not isfinite(value):
        raise ValueError(f"{name} cannot be represented as a finite number")
    if value < 0:
        raise ValueError(f"{name} cannot be represented as nonnegative")
    if require_positive and value <= 0:
        raise ValueError(f"{name} cannot be represented as positive")
    return value


def _nonnegative_power_difference(
    name: str,
    minuend: Real,
    subtrahend: Real,
) -> int | float:
    """Return an exact integral or finite binary64 power difference."""
    difference_numerator, difference_denominator = _ratio_difference(
        _product_ratio(minuend),
        _product_ratio(subtrahend),
    )
    if difference_numerator < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    quotient, remainder = divmod(
        difference_numerator,
        difference_denominator,
    )
    if remainder == 0:
        return quotient
    return _finite_ratio_value(
        name,
        (difference_numerator, difference_denominator),
        require_positive=difference_numerator > 0,
    )


def _validated_energy_and_capacity(
    state: object,
    config: object,
    usable_capacity_wh: object = None,
) -> tuple[float, float]:
    if type(state) is not BatteryState:
        raise TypeError("state must be a BatteryState")
    if type(config) is not BatteryConfig:
        raise TypeError("config must be a BatteryConfig")

    # BatteryState is mutable, so re-run its domain validation on every use.
    BatteryState(state.energy_wh)
    start_energy_wh = state.energy_wh
    nominal_capacity_wh = config.nominal_energy_wh.value
    if usable_capacity_wh is None:
        capacity_wh = nominal_capacity_wh
        capacity_name = "nominal battery energy"
    else:
        _validate_nonnegative_real("usable_capacity_wh", usable_capacity_wh)
        if usable_capacity_wh <= 0:
            raise ValueError("usable_capacity_wh must be greater than zero")
        if usable_capacity_wh > nominal_capacity_wh:
            raise ValueError(
                "usable_capacity_wh must not exceed nominal battery energy"
            )
        capacity_wh = usable_capacity_wh
        capacity_name = "usable battery energy"
    if start_energy_wh > capacity_wh:
        raise ValueError(f"state energy must not exceed {capacity_name}")
    return start_energy_wh, capacity_wh


@dataclass(frozen=True, slots=True)
class BatteryTransition:
    """Immutable accounting for one proposed constant-power interval.

    Charging input is bus-side power before charge-efficiency loss. Discharge
    output is bus-side power delivered after discharge-efficiency loss.
    """

    start_energy_wh: float
    end_energy_wh: float
    generation_w: float
    load_w: float
    charge_input_w: float
    discharge_output_w: float
    curtailed_generation_w: float
    unmet_load_w: float
    conversion_loss_wh: float
    dt_seconds: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("start_energy_wh", self.start_energy_wh),
            ("end_energy_wh", self.end_energy_wh),
            ("generation_w", self.generation_w),
            ("load_w", self.load_w),
            ("charge_input_w", self.charge_input_w),
            ("discharge_output_w", self.discharge_output_w),
            ("curtailed_generation_w", self.curtailed_generation_w),
            ("unmet_load_w", self.unmet_load_w),
            ("conversion_loss_wh", self.conversion_loss_wh),
        ):
            _validate_nonnegative_real(field_name, value)
        self._validate_duration()
        if self.charge_input_w > 0 and self.discharge_output_w > 0:
            raise ValueError(
                "charge_input_w and discharge_output_w must not both be "
                "positive"
            )

    def _validate_duration(self):
        _validate_positive_seconds(self.dt_seconds)

    @property
    def energy_change_wh(self) -> float:
        """Return the proposed change in authoritative stored energy."""
        return self.end_energy_wh - self.start_energy_wh

    @property
    def net_bus_power_w(self) -> float:
        """Return available generation minus requested load."""
        return self.generation_w - self.load_w

    @property
    def served_load_w(self) -> float:
        """Return requested load that the bus can actually supply."""
        return self.load_w - self.unmet_load_w


@dataclass(frozen=True, slots=True)
class BatterySubstepTransition(BatteryTransition):
    """Same accounting, explicitly admitted fractional internal duration."""
    dt_seconds: float
    duration: DyadicDuration

    def _validate_duration(self):
        validate_substep_seconds(self.dt_seconds, self.duration)


def battery_soc_fraction(
    state: BatteryState,
    config: BatteryConfig,
) -> float:
    """Derive battery SOC from stored energy and nominal usable capacity."""
    energy_wh, capacity_wh = _validated_energy_and_capacity(state, config)
    return energy_wh / capacity_wh


def compute_battery_transition(
    state: BatteryState,
    config: BatteryConfig,
    *,
    generation_w: float,
    load_w: float,
    dt_seconds: int,
    usable_capacity_wh: float | None = None,
) -> BatteryTransition:
    """Compute a pure Level-1 battery energy proposal without mutation.

    ``usable_capacity_wh`` selects an explicit runtime energy ceiling when
    supplied; otherwise the nominal configured capacity is used for backward
    compatibility. ``max_charge_input_power_w`` limits bus power accepted
    before charging loss. ``max_discharge_output_power_w`` limits bus power
    delivered after discharging loss. Available generation and requested load
    are constant or interval-average powers supplied by external models.
    """
    return _compute_battery_transition(state, config, generation_w=generation_w,
        load_w=load_w, dt_seconds=dt_seconds, usable_capacity_wh=usable_capacity_wh)


def compute_battery_substep_transition(state, config, *, generation_w, load_w,
                                       duration, usable_capacity_wh=None):
    """Use the shared battery equations with an explicit dyadic duration."""
    return _compute_battery_transition(state, config, generation_w=generation_w,
        load_w=load_w, dt_seconds=checked_duration(duration),
        usable_capacity_wh=usable_capacity_wh, _duration=duration)


def _compute_battery_transition(state, config, *, generation_w, load_w,
                                dt_seconds, usable_capacity_wh, _duration=None):
    start_energy_wh, capacity_wh = _validated_energy_and_capacity(
        state, config, usable_capacity_wh)

    _validate_nonnegative_real("generation_w", generation_w)
    _validate_nonnegative_real("load_w", load_w)
    dt_hours = (_validated_dt_hours(dt_seconds) if _duration is None
                else checked_duration(_duration) / _SECONDS_PER_HOUR)
    charge_input_w = 0.0
    discharge_output_w = 0.0
    curtailed_generation_w = 0.0
    unmet_load_w = 0.0
    conversion_loss_wh = 0.0
    end_energy_wh = start_energy_wh

    if generation_w > load_w:
        surplus_w = _nonnegative_power_difference(
            "surplus_w",
            generation_w,
            load_w,
        )
        efficiency = config.charge_efficiency.value
        room_wh = capacity_wh - start_energy_wh
        available_charge_input_w = min(
            surplus_w,
            config.max_charge_input_power_w.value,
        )
        potential_stored_energy_ratio = _product_ratio(
            available_charge_input_w,
            efficiency,
            dt_hours,
        )
        available_room_ratio = _ratio_difference(
            _product_ratio(capacity_wh),
            _product_ratio(start_energy_wh),
        )
        if _ratio_at_least(
            potential_stored_energy_ratio,
            available_room_ratio,
        ):
            stored_energy_increase_wh = room_wh
            end_energy_wh = capacity_wh
            if room_wh == 0:
                charge_input_w = 0.0
                conversion_loss_wh = 0.0
            else:
                charge_input_w = _finite_ratio_value(
                    "capacity-limited charge_input_w",
                    _quotient_ratio(
                        (room_wh,),
                        (efficiency, dt_hours),
                    ),
                    require_positive=True,
                )
                charge_input_w = min(
                    available_charge_input_w,
                    charge_input_w,
                )
                conversion_loss_wh = _finite_ratio_value(
                    "capacity-limited conversion_loss_wh",
                    _product_ratio(
                        charge_input_w,
                        dt_hours,
                        1.0 - efficiency,
                    ),
                )
        else:
            charge_input_w = available_charge_input_w
            stored_energy_increase_wh = _finite_ratio_value(
                "stored_energy_increase_wh",
                potential_stored_energy_ratio,
            )
            end_energy_wh = _finite_ratio_value(
                "end_energy_wh",
                _ratio_sum(
                    _product_ratio(start_energy_wh),
                    potential_stored_energy_ratio,
                ),
            )
            conversion_loss_wh = _finite_ratio_value(
                "conversion_loss_wh",
                _product_ratio(
                    charge_input_w,
                    dt_hours,
                    1.0 - efficiency,
                ),
            )
        curtailed_generation_w = _nonnegative_power_difference(
            "curtailed_generation_w",
            surplus_w,
            charge_input_w,
        )
    elif load_w > generation_w:
        deficit_w = _nonnegative_power_difference(
            "deficit_w",
            load_w,
            generation_w,
        )
        efficiency = config.discharge_efficiency.value
        requested_discharge_output_w = min(
            deficit_w,
            config.max_discharge_output_power_w.value,
        )
        requested_bus_energy_ratio = _product_ratio(
            requested_discharge_output_w,
            dt_hours,
        )
        available_bus_energy_ratio = _product_ratio(
            start_energy_wh,
            efficiency,
        )
        if _ratio_at_least(
            requested_bus_energy_ratio,
            available_bus_energy_ratio,
        ):
            removed_energy_wh = start_energy_wh
            end_energy_wh = 0.0
            if start_energy_wh == 0:
                discharge_output_w = 0.0
                conversion_loss_wh = 0.0
            else:
                discharge_output_w = _finite_ratio_value(
                    "energy-limited discharge_output_w",
                    _quotient_ratio(
                        (start_energy_wh, efficiency),
                        (dt_hours,),
                    ),
                    require_positive=True,
                )
                conversion_loss_wh = _finite_ratio_value(
                    "energy-limited conversion_loss_wh",
                    _product_ratio(
                        start_energy_wh,
                        1.0 - efficiency,
                    ),
                )
        else:
            discharge_output_w = requested_discharge_output_w
            removed_energy_ratio = _quotient_ratio(
                (discharge_output_w, dt_hours),
                (efficiency,),
            )
            removed_energy_wh = _finite_ratio_value(
                "removed_energy_wh",
                removed_energy_ratio,
            )
            end_energy_wh = _finite_ratio_value(
                "end_energy_wh",
                _ratio_difference(
                    _product_ratio(start_energy_wh),
                    removed_energy_ratio,
                ),
            )
            conversion_loss_wh = _finite_ratio_value(
                "conversion_loss_wh",
                _quotient_ratio(
                    (
                        discharge_output_w,
                        dt_hours,
                        1.0 - efficiency,
                    ),
                    (efficiency,),
                ),
            )
        unmet_load_w = _nonnegative_power_difference(
            "unmet_load_w",
            deficit_w,
            discharge_output_w,
        )

    result_type = BatteryTransition if _duration is None else BatterySubstepTransition
    extra = {} if _duration is None else {"duration": _duration}
    return result_type(
        start_energy_wh,
        end_energy_wh,
        generation_w,
        load_w,
        charge_input_w,
        discharge_output_w,
        curtailed_generation_w,
        unmet_load_w,
        conversion_loss_wh,
        dt_seconds,
        **extra,
    )


__all__ = [
    "BatteryTransition",
    "battery_soc_fraction",
    "compute_battery_transition",
]
