"""Pure LINEARIZED LEVEL-1 DAMAGE ACCUMULATION physics for V5.

Battery cycling uses battery-side energy throughput in Wh. This Level-1
history is not the charge throughput in Ah used by many cell-ageing studies.
Solar degradation remains an explicit external forcing because V5 does not
yet own a radiation-environment or solar-cell response model.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite
from numbers import Integral, Real

from .configuration import BatteryConfig
from .degradation_config import BatteryAgeingModelConfig
from .eps_system import EPSIntervalResult, EPSSubstepResult
from .integration_time import DyadicDuration, checked_duration, validate_substep_seconds
from .state import BatteryDegradationState, SolarDegradationState


_SECONDS_PER_HOUR = 3600.0
_MOLAR_GAS_CONSTANT_J_PER_MOL_K = 8.31446261815324


def _normalized_real(name: str, value: object) -> int | float:
    """Return an admitted finite Real as a safe built-in scalar."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = bool(isfinite(value))
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} must be finite") from error
    if not finite:
        raise ValueError(f"{name} must be finite")

    try:
        normalized = int(value) if isinstance(value, Integral) else float(value)
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if type(normalized) not in {int, float}:
        raise ValueError(f"{name} must normalize to a built-in number")
    try:
        normalized_finite = bool(isfinite(normalized))
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if not normalized_finite:
        raise ValueError(f"{name} cannot be represented as a finite number")
    return normalized


def _normalized_nonnegative_real(name: str, value: object) -> int | float:
    normalized = _normalized_real(name, value)
    if normalized < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return normalized


def _normalized_positive_real(name: str, value: object) -> int | float:
    normalized = _normalized_real(name, value)
    if normalized <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return normalized


def _validated_positive_seconds(value: object) -> int:
    if type(value) is not int:
        raise TypeError("dt_seconds must be an integer")
    if value <= 0:
        raise ValueError("dt_seconds must be greater than zero")
    return value


def _checked_sum(name: str, *values: object) -> int | float:
    """Add finite values using ordinary built-in arithmetic."""
    total: int | float = 0
    for index, value in enumerate(values):
        addend = _normalized_real(f"{name} addend {index}", value)
        try:
            total = total + addend
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"{name} cannot be represented as finite"
            ) from error
        total = _normalized_real(name, total)
    return total


def _checked_difference(
    name: str,
    minuend: object,
    subtrahend: object,
) -> int | float:
    minuend_value = _normalized_real(f"{name} minuend", minuend)
    subtrahend_value = _normalized_real(f"{name} subtrahend", subtrahend)
    try:
        difference = minuend_value - subtrahend_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    return _normalized_real(name, difference)


def _checked_product(name: str, *values: object) -> int | float:
    product: int | float = 1
    for index, value in enumerate(values):
        factor = _normalized_real(f"{name} factor {index}", value)
        prior_product = product
        try:
            product = product * factor
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"{name} cannot be represented as finite"
            ) from error
        product = _normalized_real(name, product)
        if prior_product != 0 and factor != 0 and product == 0:
            raise ValueError(f"{name} cannot represent a nonzero product")
    return product


def _checked_quotient(
    name: str,
    numerator: object,
    denominator: object,
) -> int | float:
    numerator_value = _normalized_real(f"{name} numerator", numerator)
    denominator_value = _normalized_real(f"{name} denominator", denominator)
    if denominator_value == 0:
        raise ValueError(f"{name} denominator must not be zero")
    try:
        quotient = numerator_value / denominator_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    normalized = _normalized_real(name, quotient)
    if numerator_value != 0 and normalized == 0:
        raise ValueError(f"{name} cannot represent a nonzero quotient")
    return normalized


def _temperature_acceleration(
    temperature_k: object,
    reference_temperature_k: object,
    activation_energy_j_per_mol: object,
) -> int | float:
    """Return a normalized Arrhenius temperature-acceleration factor."""
    temperature = _normalized_positive_real("temperature_k", temperature_k)
    reference = _normalized_positive_real(
        "reference_temperature_k",
        reference_temperature_k,
    )
    activation_energy = _normalized_nonnegative_real(
        "activation_energy_j_per_mol",
        activation_energy_j_per_mol,
    )
    if activation_energy == 0 or temperature == reference:
        return 1.0

    inverse_temperature = _checked_quotient(
        "inverse temperature",
        1.0,
        temperature,
    )
    inverse_reference = _checked_quotient(
        "inverse reference temperature",
        1.0,
        reference,
    )
    inverse_difference = _checked_difference(
        "inverse-temperature difference",
        inverse_temperature,
        inverse_reference,
    )
    activation_ratio = _checked_quotient(
        "activation-energy ratio",
        activation_energy,
        _MOLAR_GAS_CONSTANT_J_PER_MOL_K,
    )
    exponent_magnitude = _checked_product(
        "Arrhenius exponent",
        activation_ratio,
        inverse_difference,
    )
    exponent = _checked_product(
        "Arrhenius exponent",
        -1.0,
        exponent_magnitude,
    )
    try:
        acceleration = exp(exponent)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(
            "temperature acceleration cannot be represented as finite"
        ) from error
    acceleration = _normalized_real(
        "temperature acceleration",
        acceleration,
    )
    if acceleration <= 0:
        raise ValueError(
            "temperature acceleration cannot be represented as positive"
        )
    return acceleration


@dataclass(frozen=True, slots=True)
class BatteryThroughputIncrement:
    """Battery-side absolute stored and extracted energy movement."""

    charge_energy_throughput_wh: float
    discharge_energy_throughput_wh: float
    total_energy_throughput_wh: float

    def __post_init__(self) -> None:
        charge = _normalized_nonnegative_real(
            "charge_energy_throughput_wh",
            self.charge_energy_throughput_wh,
        )
        discharge = _normalized_nonnegative_real(
            "discharge_energy_throughput_wh",
            self.discharge_energy_throughput_wh,
        )
        total = _normalized_nonnegative_real(
            "total_energy_throughput_wh",
            self.total_energy_throughput_wh,
        )
        expected_total = _checked_sum(
            "total_energy_throughput_wh",
            charge,
            discharge,
        )
        if total != expected_total:
            raise ValueError(
                "total_energy_throughput_wh must equal charge plus discharge "
                "energy throughput"
            )


@dataclass(frozen=True, slots=True)
class BatteryDegradationIntervalInput:
    """Explicit representative temperature, usage, and interval duration."""

    battery_temperature_k: float
    throughput_increment: BatteryThroughputIncrement
    dt_seconds: int

    def __post_init__(self) -> None:
        _normalized_positive_real(
            "battery_temperature_k",
            self.battery_temperature_k,
        )
        if type(self.throughput_increment) is not BatteryThroughputIncrement:
            raise TypeError(
                "throughput_increment must be a BatteryThroughputIncrement"
            )
        BatteryThroughputIncrement(
            self.throughput_increment.charge_energy_throughput_wh,
            self.throughput_increment.discharge_energy_throughput_wh,
            self.throughput_increment.total_energy_throughput_wh,
        )
        self._validate_duration()

    def _validate_duration(self):
        _validated_positive_seconds(self.dt_seconds)


@dataclass(frozen=True, slots=True)
class BatteryDegradationTransition:
    """Observable proposal for one Level-1 battery degradation interval."""

    start_usable_capacity_retention: float
    end_usable_capacity_retention: float
    start_cumulative_energy_throughput_wh: float
    throughput_increment_wh: float
    end_cumulative_energy_throughput_wh: float
    representative_temperature_k: float
    calendar_temperature_acceleration: float
    cycling_temperature_acceleration: float
    calendar_damage: float
    cycling_damage: float
    total_damage: float
    dt_seconds: int

    def __post_init__(self) -> None:
        start_retention = _normalized_positive_real(
            "start_usable_capacity_retention",
            self.start_usable_capacity_retention,
        )
        end_retention = _normalized_positive_real(
            "end_usable_capacity_retention",
            self.end_usable_capacity_retention,
        )
        if start_retention > 1 or end_retention > 1:
            raise ValueError(
                "usable capacity retention must be less than or equal to one"
            )
        start_throughput = _normalized_nonnegative_real(
            "start_cumulative_energy_throughput_wh",
            self.start_cumulative_energy_throughput_wh,
        )
        increment = _normalized_nonnegative_real(
            "throughput_increment_wh",
            self.throughput_increment_wh,
        )
        end_throughput = _normalized_nonnegative_real(
            "end_cumulative_energy_throughput_wh",
            self.end_cumulative_energy_throughput_wh,
        )
        _normalized_positive_real(
            "representative_temperature_k",
            self.representative_temperature_k,
        )
        _normalized_positive_real(
            "calendar_temperature_acceleration",
            self.calendar_temperature_acceleration,
        )
        _normalized_positive_real(
            "cycling_temperature_acceleration",
            self.cycling_temperature_acceleration,
        )
        calendar_damage = _normalized_nonnegative_real(
            "calendar_damage",
            self.calendar_damage,
        )
        cycling_damage = _normalized_nonnegative_real(
            "cycling_damage",
            self.cycling_damage,
        )
        total_damage = _normalized_nonnegative_real(
            "total_damage",
            self.total_damage,
        )
        self._validate_duration()

        expected_end_throughput = _checked_sum(
            "end_cumulative_energy_throughput_wh",
            start_throughput,
            increment,
        )
        if end_throughput != expected_end_throughput:
            raise ValueError(
                "end cumulative throughput must equal start throughput plus "
                "increment"
            )
        expected_total_damage = _checked_sum(
            "total_damage",
            calendar_damage,
            cycling_damage,
        )
        if total_damage != expected_total_damage:
            raise ValueError(
                "total_damage must equal calendar_damage plus cycling_damage"
            )
        expected_end_retention = _checked_difference(
            "end_usable_capacity_retention",
            start_retention,
            total_damage,
        )
        if end_retention != expected_end_retention:
            raise ValueError(
                "end retention must equal start retention minus total damage"
            )

    def _validate_duration(self):
        _validated_positive_seconds(self.dt_seconds)


@dataclass(frozen=True, slots=True)
class SolarDegradationForcingInput:
    """Explicit external solar-capability retention loss."""

    retention_loss: float

    def __post_init__(self) -> None:
        _normalized_nonnegative_real("retention_loss", self.retention_loss)


@dataclass(frozen=True, slots=True)
class SolarDegradationTransition:
    """Pure proposal from one explicit solar degradation forcing."""

    start_generation_retention: float
    retention_loss: float
    end_generation_retention: float

    def __post_init__(self) -> None:
        start = _normalized_positive_real(
            "start_generation_retention",
            self.start_generation_retention,
        )
        loss = _normalized_nonnegative_real(
            "retention_loss",
            self.retention_loss,
        )
        end = _normalized_positive_real(
            "end_generation_retention",
            self.end_generation_retention,
        )
        if start > 1 or end > 1:
            raise ValueError(
                "generation retention must be less than or equal to one"
            )
        expected_end = _checked_difference(
            "end_generation_retention",
            start,
            loss,
        )
        if end != expected_end:
            raise ValueError(
                "end generation retention must equal start retention minus "
                "loss"
            )


@dataclass(frozen=True, slots=True)
class BatteryDegradationSubstepInput(BatteryDegradationIntervalInput):
    dt_seconds: float
    duration: DyadicDuration
    def _validate_duration(self):
        validate_substep_seconds(self.dt_seconds, self.duration)


@dataclass(frozen=True, slots=True)
class BatteryDegradationSubstepTransition(BatteryDegradationTransition):
    dt_seconds: float
    duration: DyadicDuration
    def _validate_duration(self):
        validate_substep_seconds(self.dt_seconds, self.duration)


def compute_battery_throughput_increment(
    eps_result: EPSIntervalResult,
    battery_config: BatteryConfig,
) -> BatteryThroughputIncrement:
    """Derive battery-side absolute energy movement from one EPS result."""
    return _compute_battery_throughput(eps_result, battery_config, EPSIntervalResult)


def compute_battery_substep_throughput(eps_result, battery_config):
    return _compute_battery_throughput(eps_result, battery_config, EPSSubstepResult)


def _compute_battery_throughput(eps_result, battery_config, expected_type):
    if type(eps_result) is not expected_type:
        raise TypeError("eps_result must be an EPSIntervalResult")
    if type(battery_config) is not BatteryConfig:
        raise TypeError("battery_config must be a BatteryConfig")

    transition = eps_result.battery
    if expected_type is EPSIntervalResult:
        dt_seconds = _validated_positive_seconds(transition.dt_seconds)
    else:
        transition.__post_init__()
        dt_seconds = checked_duration(transition.duration)
    dt_hours = _checked_quotient(
        "EPS interval duration in hours",
        dt_seconds,
        _SECONDS_PER_HOUR,
    )
    charge_input_w = _normalized_nonnegative_real(
        "charge_input_w",
        transition.charge_input_w,
    )
    discharge_output_w = _normalized_nonnegative_real(
        "discharge_output_w",
        transition.discharge_output_w,
    )
    charge_efficiency = _normalized_positive_real(
        "charge_efficiency",
        battery_config.charge_efficiency.value,
    )
    discharge_efficiency = _normalized_positive_real(
        "discharge_efficiency",
        battery_config.discharge_efficiency.value,
    )
    charge_energy = _checked_product(
        "charge_energy_throughput_wh",
        charge_input_w,
        charge_efficiency,
        dt_hours,
    )
    discharge_bus_energy = _checked_product(
        "discharge bus energy in Wh",
        discharge_output_w,
        dt_hours,
    )
    discharge_energy = _checked_quotient(
        "discharge_energy_throughput_wh",
        discharge_bus_energy,
        discharge_efficiency,
    )
    total_energy = _checked_sum(
        "total_energy_throughput_wh",
        charge_energy,
        discharge_energy,
    )
    return BatteryThroughputIncrement(
        charge_energy,
        discharge_energy,
        total_energy,
    )


def compute_battery_degradation_transition(
    state: BatteryDegradationState,
    battery_config: BatteryConfig,
    ageing_config: BatteryAgeingModelConfig,
    interval_input: BatteryDegradationIntervalInput,
) -> BatteryDegradationTransition:
    """Compute a pure linearized Level-1 battery damage proposal."""
    return _compute_battery_degradation(state, battery_config, ageing_config, interval_input)


def compute_battery_degradation_substep(state, battery_config, ageing_config, interval_input):
    if type(interval_input) is not BatteryDegradationSubstepInput:
        raise TypeError("interval_input must be BatteryDegradationSubstepInput")
    interval_input.__post_init__()
    return _compute_battery_degradation(state, battery_config, ageing_config,
        interval_input, _duration=interval_input.duration)


def _compute_battery_degradation(state, battery_config, ageing_config, interval_input, _duration=None):
    if type(state) is not BatteryDegradationState:
        raise TypeError("state must be a BatteryDegradationState")
    if type(battery_config) is not BatteryConfig:
        raise TypeError("battery_config must be a BatteryConfig")
    if type(ageing_config) is not BatteryAgeingModelConfig:
        raise TypeError("ageing_config must be a BatteryAgeingModelConfig")
    input_type = BatteryDegradationIntervalInput if _duration is None else BatteryDegradationSubstepInput
    if type(interval_input) is not input_type:
        raise TypeError(
            "interval_input must be a BatteryDegradationIntervalInput"
        )

    BatteryDegradationState(
        state.usable_capacity_retention,
        state.cumulative_energy_throughput_wh,
    )
    interval_input.__post_init__()
    start_retention = _normalized_positive_real(
        "start_usable_capacity_retention",
        state.usable_capacity_retention,
    )
    start_throughput = _normalized_nonnegative_real(
        "start_cumulative_energy_throughput_wh",
        state.cumulative_energy_throughput_wh,
    )
    temperature = _normalized_positive_real(
        "representative_temperature_k",
        interval_input.battery_temperature_k,
    )
    increment = _normalized_nonnegative_real(
        "throughput_increment_wh",
        interval_input.throughput_increment.total_energy_throughput_wh,
    )
    dt_seconds = (_validated_positive_seconds(interval_input.dt_seconds) if _duration is None
                  else checked_duration(_duration))
    reference_temperature = _normalized_positive_real(
        "reference_temperature_k",
        ageing_config.reference_temperature_k.value,
    )
    calendar_acceleration = _temperature_acceleration(
        temperature,
        reference_temperature,
        ageing_config.calendar_activation_energy_j_per_mol.value,
    )
    cycling_acceleration = _temperature_acceleration(
        temperature,
        reference_temperature,
        ageing_config.cycling_activation_energy_j_per_mol.value,
    )
    calendar_damage = _checked_product(
        "calendar_damage",
        ageing_config.calendar_damage_rate_per_second_at_reference.value,
        calendar_acceleration,
        dt_seconds,
    )
    nominal_energy_wh = _normalized_positive_real(
        "nominal_energy_wh",
        battery_config.nominal_energy_wh.value,
    )
    normalized_throughput = _checked_quotient(
        "normalized_energy_throughput",
        increment,
        nominal_energy_wh,
    )
    cycling_damage = _checked_product(
        "cycling_damage",
        ageing_config
        .cycling_damage_per_normalized_energy_throughput_at_reference.value,
        cycling_acceleration,
        normalized_throughput,
    )
    total_damage = _checked_sum(
        "total_damage",
        calendar_damage,
        cycling_damage,
    )
    end_retention = _checked_difference(
        "end_usable_capacity_retention",
        start_retention,
        total_damage,
    )
    if end_retention <= 0:
        raise ValueError(
            "battery degradation candidate retention must be greater than zero"
        )
    end_throughput = _checked_sum(
        "end_cumulative_energy_throughput_wh",
        start_throughput,
        increment,
    )
    result_type = BatteryDegradationTransition if _duration is None else BatteryDegradationSubstepTransition
    extra = {} if _duration is None else {"duration": _duration}
    return result_type(
        start_retention,
        end_retention,
        start_throughput,
        increment,
        end_throughput,
        temperature,
        calendar_acceleration,
        cycling_acceleration,
        calendar_damage,
        cycling_damage,
        total_damage,
        dt_seconds,
        **extra,
    )


def compute_explicit_solar_degradation_transition(
    state: SolarDegradationState,
    forcing: SolarDegradationForcingInput,
) -> SolarDegradationTransition:
    """Apply one explicit solar retention loss without a hidden time law."""
    if type(state) is not SolarDegradationState:
        raise TypeError("state must be a SolarDegradationState")
    if type(forcing) is not SolarDegradationForcingInput:
        raise TypeError(
            "forcing must be a SolarDegradationForcingInput"
        )
    SolarDegradationState(state.generation_retention)
    SolarDegradationForcingInput(forcing.retention_loss)
    start = _normalized_positive_real(
        "start_generation_retention",
        state.generation_retention,
    )
    loss = _normalized_nonnegative_real(
        "retention_loss",
        forcing.retention_loss,
    )
    end = _checked_difference("end_generation_retention", start, loss)
    if end <= 0:
        raise ValueError(
            "solar degradation candidate retention must be greater than zero"
        )
    return SolarDegradationTransition(start, loss, end)


__all__ = [
    "BatteryAgeingModelConfig",
    "BatteryDegradationIntervalInput",
    "BatteryDegradationTransition",
    "BatteryThroughputIncrement",
    "SolarDegradationForcingInput",
    "SolarDegradationTransition",
    "compute_battery_degradation_transition",
    "compute_battery_throughput_increment",
    "compute_explicit_solar_degradation_transition",
]
