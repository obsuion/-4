"""Pure optical-acquisition EPS evaluation and service bounds."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from enum import Enum
from math import isfinite
from numbers import Integral, Real

from .adcs_config import AgilePointingConfig
from .configuration import EPSConfig
from .eps_capability import EPSCapabilityResult, compute_eps_capability
from .eps_system import (
    EPSIntervalInputs,
    EPSIntervalResult,
    compute_eps_interval_transition,
)
from .imaging_feasibility import (
    ObservationAcquisitionCandidate,
    ObservationAcquisitionEvaluationResult,
    evaluate_observation_acquisition,
)
from .observation_feasibility import ScheduledObservationExecution
from .payload_config import OpticalAcquisitionConfig
from .power_loads import PowerLoadBreakdown
from .state import BatteryState, DegradationState


_SECONDS_PER_HOUR = 3600


class AcquisitionServiceStatus(str, Enum):
    """Allocation-free classification of full acquisition-load service."""

    FULLY_SERVED = "fully-served"
    FULL_SERVICE_IMPOSSIBLE = "full-service-impossible"
    SERVICE_ALLOCATION_REQUIRED = "service-allocation-required"


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


def _builtin_nonnegative_real(name: str, value: object) -> int | float:
    """Validate one externally exposed built-in service-bound number."""
    if type(value) not in {int, float}:
        raise TypeError(f"{name} must be a built-in int or float")
    try:
        finite = bool(isfinite(value))
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{name} must be finite") from error
    if not finite:
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
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
    """Subtract finite values using ordinary built-in arithmetic."""
    left = _normalized_real(f"{name} minuend", minuend)
    right = _normalized_real(f"{name} subtrahend", subtrahend)
    try:
        difference = left - right
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    return _normalized_real(name, difference)


def _checked_product(name: str, *values: object) -> int | float:
    """Multiply finite values and reject nonzero representational underflow."""
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
    """Divide finite values and reject nonzero representational underflow."""
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


def _revalidate_loads(loads: PowerLoadBreakdown) -> None:
    replace(loads)


def _revalidate_eps_config(config: EPSConfig) -> None:
    replace(config)
    replace(config.configuration_id)
    replace(config.battery.configuration_id)
    for field in fields(config.battery)[1:]:
        replace(getattr(config.battery, field.name))
    replace(config.battery)
    replace(config.solar_array.configuration_id)
    for field in fields(config.solar_array)[1:]:
        replace(getattr(config.solar_array, field.name))
    replace(config.solar_array)


def _revalidate_eps_inputs(inputs: EPSIntervalInputs) -> None:
    replace(inputs)
    _revalidate_loads(inputs.load_breakdown)


def _revalidate_eps_result(result: EPSIntervalResult) -> None:
    replace(result)
    replace(result.solar)
    _revalidate_loads(result.loads)
    replace(result.battery)


@dataclass(frozen=True, slots=True)
class AcquisitionEPSIntervalEnvironment:
    """Solar forcing and all loads except the candidate acquisition load."""

    sunlit: bool
    incidence_angle_deg: float
    non_acquisition_loads: PowerLoadBreakdown

    def __post_init__(self) -> None:
        if type(self.sunlit) is not bool:
            raise TypeError("sunlit must be a boolean")
        if type(self.non_acquisition_loads) is not PowerLoadBreakdown:
            raise TypeError(
                "non_acquisition_loads must be a PowerLoadBreakdown"
            )
        _revalidate_loads(self.non_acquisition_loads)
        EPSIntervalInputs(
            self.sunlit,
            self.incidence_angle_deg,
            self.non_acquisition_loads,
        )


@dataclass(frozen=True, slots=True)
class AcquisitionServiceBounds:
    """Allocation-free lower and upper bounds on acquisition service."""

    minimum_served_acquisition_power_w: float
    maximum_served_acquisition_power_w: float
    minimum_served_acquisition_energy_wh: float
    maximum_served_acquisition_energy_wh: float
    status: AcquisitionServiceStatus

    def __post_init__(self) -> None:
        minimum_power = _builtin_nonnegative_real(
            "minimum_served_acquisition_power_w",
            self.minimum_served_acquisition_power_w,
        )
        maximum_power = _builtin_nonnegative_real(
            "maximum_served_acquisition_power_w",
            self.maximum_served_acquisition_power_w,
        )
        minimum_energy = _builtin_nonnegative_real(
            "minimum_served_acquisition_energy_wh",
            self.minimum_served_acquisition_energy_wh,
        )
        maximum_energy = _builtin_nonnegative_real(
            "maximum_served_acquisition_energy_wh",
            self.maximum_served_acquisition_energy_wh,
        )
        if type(self.status) is not AcquisitionServiceStatus:
            raise TypeError("status must be an AcquisitionServiceStatus")
        if minimum_power > maximum_power:
            raise ValueError(
                "minimum served acquisition power must not exceed maximum"
            )
        if minimum_energy > maximum_energy:
            raise ValueError(
                "minimum served acquisition energy must not exceed maximum"
            )


def _service_bounds(
    acquisition_evaluation: ObservationAcquisitionEvaluationResult,
    eps_result: EPSIntervalResult,
) -> AcquisitionServiceBounds:
    acquisition = acquisition_evaluation.acquisition_result
    if acquisition is None:
        raise ValueError("service bounds require a feasible acquisition")

    requested_power = _normalized_positive_real(
        "requested_acquisition_power_w",
        acquisition.requested_acquisition_power_w,
    )
    total_requested = _normalized_nonnegative_real(
        "total_requested_combined_bus_load_w",
        eps_result.battery.load_w,
    )
    aggregate_served = _normalized_nonnegative_real(
        "aggregate_served_bus_load_w",
        eps_result.battery.served_load_w,
    )
    aggregate_unmet = _normalized_nonnegative_real(
        "aggregate_unmet_bus_load_w",
        eps_result.battery.unmet_load_w,
    )
    if requested_power > total_requested:
        raise ValueError(
            "requested acquisition power must not exceed total requested load"
        )
    if aggregate_served > total_requested:
        raise ValueError(
            "aggregate served bus load must not exceed total requested load"
        )

    guaranteed_remainder = _checked_difference(
        "guaranteed acquisition service remainder",
        requested_power,
        aggregate_unmet,
    )
    minimum_power = max(0, guaranteed_remainder)
    maximum_power = min(requested_power, aggregate_served)

    dt_seconds = eps_result.battery.dt_seconds
    minimum_energy = _checked_quotient(
        "minimum_served_acquisition_energy_wh",
        _checked_product(
            "minimum served acquisition energy in watt-seconds",
            minimum_power,
            dt_seconds,
        ),
        _SECONDS_PER_HOUR,
    )
    maximum_energy = _checked_quotient(
        "maximum_served_acquisition_energy_wh",
        _checked_product(
            "maximum served acquisition energy in watt-seconds",
            maximum_power,
            dt_seconds,
        ),
        _SECONDS_PER_HOUR,
    )

    if minimum_power == requested_power:
        status = AcquisitionServiceStatus.FULLY_SERVED
    elif maximum_power < requested_power:
        status = AcquisitionServiceStatus.FULL_SERVICE_IMPOSSIBLE
    else:
        status = AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED
    return AcquisitionServiceBounds(
        minimum_power,
        maximum_power,
        minimum_energy,
        maximum_energy,
        status,
    )


@dataclass(frozen=True, slots=True)
class ObservationAcquisitionEPSResult:
    """D evaluation with conditional EPS proposal and service bounds."""

    acquisition_evaluation: ObservationAcquisitionEvaluationResult
    eps_inputs: EPSIntervalInputs | None
    eps_capability_result: EPSCapabilityResult | None
    eps_result: EPSIntervalResult | None
    service_bounds: AcquisitionServiceBounds | None

    def __post_init__(self) -> None:
        if type(self.acquisition_evaluation) is not (
            ObservationAcquisitionEvaluationResult
        ):
            raise TypeError(
                "acquisition_evaluation must be an "
                "ObservationAcquisitionEvaluationResult"
            )
        replace(self.acquisition_evaluation)

        conditional_values = (
            self.eps_inputs,
            self.eps_capability_result,
            self.eps_result,
            self.service_bounds,
        )
        if not self.acquisition_evaluation.feasible:
            if any(value is not None for value in conditional_values):
                raise ValueError(
                    "an infeasible acquisition evaluation requires all EPS "
                    "and service fields to be None"
                )
            return

        contracts = (
            ("eps_inputs", self.eps_inputs, EPSIntervalInputs),
            (
                "eps_capability_result",
                self.eps_capability_result,
                EPSCapabilityResult,
            ),
            ("eps_result", self.eps_result, EPSIntervalResult),
            ("service_bounds", self.service_bounds, AcquisitionServiceBounds),
        )
        for field_name, value, expected_type in contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )

        _revalidate_eps_inputs(self.eps_inputs)
        replace(self.eps_capability_result)
        _revalidate_eps_result(self.eps_result)
        AcquisitionServiceBounds(
            self.service_bounds.minimum_served_acquisition_power_w,
            self.service_bounds.maximum_served_acquisition_power_w,
            self.service_bounds.minimum_served_acquisition_energy_wh,
            self.service_bounds.maximum_served_acquisition_energy_wh,
            self.service_bounds.status,
        )

        if self.eps_result.loads != self.eps_inputs.load_breakdown:
            raise ValueError(
                "eps_result loads must equal eps_inputs load_breakdown"
            )
        requested_bus_load = self.eps_inputs.load_breakdown.total_load_w
        if self.eps_result.battery.load_w != requested_bus_load:
            raise ValueError(
                "EPS battery requested load must equal the input total load"
            )
        if self.eps_result.battery.generation_w != self.eps_result.solar.generation_w:
            raise ValueError(
                "EPS battery generation must equal the solar result generation"
            )
        if (
            self.eps_result.solar.nominal_generation_w
            != self.eps_capability_result.solar_nominal_generation_capability_w
        ):
            raise ValueError(
                "EPS solar nominal generation must equal the capability result"
            )

        acquisition = self.acquisition_evaluation.acquisition_result
        if acquisition is None:
            raise ValueError(
                "a feasible acquisition evaluation requires acquisition data"
            )
        expected_requested_energy = _checked_quotient(
            "acquisition_energy_wh",
            _checked_product(
                "requested acquisition energy in watt-seconds",
                acquisition.requested_acquisition_power_w,
                self.eps_result.battery.dt_seconds,
            ),
            _SECONDS_PER_HOUR,
        )
        if acquisition.acquisition_energy_wh != expected_requested_energy:
            raise ValueError(
                "EPS interval duration must equal the acquisition duration"
            )

        expected_bounds = _service_bounds(
            self.acquisition_evaluation,
            self.eps_result,
        )
        for field_name in (
            "minimum_served_acquisition_power_w",
            "maximum_served_acquisition_power_w",
            "minimum_served_acquisition_energy_wh",
            "maximum_served_acquisition_energy_wh",
            "status",
        ):
            if getattr(self.service_bounds, field_name) != getattr(
                expected_bounds,
                field_name,
            ):
                raise ValueError(
                    f"service_bounds {field_name} is inconsistent with EPS "
                    "aggregate service"
                )


def evaluate_observation_acquisition_eps(
    agile_pointing_config: AgilePointingConfig,
    optical_acquisition_config: OpticalAcquisitionConfig,
    eps_config: EPSConfig,
    battery_state: BatteryState,
    degradation_state: DegradationState,
    previous_execution: ScheduledObservationExecution,
    next_candidate: ObservationAcquisitionCandidate,
    environment: AcquisitionEPSIntervalEnvironment,
) -> ObservationAcquisitionEPSResult:
    """Evaluate one acquisition through D and existing EPS physics."""
    contracts = (
        (
            "agile_pointing_config",
            agile_pointing_config,
            AgilePointingConfig,
        ),
        (
            "optical_acquisition_config",
            optical_acquisition_config,
            OpticalAcquisitionConfig,
        ),
        ("eps_config", eps_config, EPSConfig),
        ("battery_state", battery_state, BatteryState),
        ("degradation_state", degradation_state, DegradationState),
        (
            "previous_execution",
            previous_execution,
            ScheduledObservationExecution,
        ),
        (
            "next_candidate",
            next_candidate,
            ObservationAcquisitionCandidate,
        ),
        (
            "environment",
            environment,
            AcquisitionEPSIntervalEnvironment,
        ),
    )
    for field_name, value, expected_type in contracts:
        if type(value) is not expected_type:
            raise TypeError(
                f"{field_name} must be a {expected_type.__name__}"
            )

    replace(agile_pointing_config)
    replace(optical_acquisition_config)
    _revalidate_eps_config(eps_config)
    replace(battery_state)
    replace(degradation_state)
    replace(previous_execution)
    replace(next_candidate)
    replace(environment)

    acquisition_evaluation = evaluate_observation_acquisition(
        agile_pointing_config,
        optical_acquisition_config,
        previous_execution,
        next_candidate,
    )
    if type(acquisition_evaluation) is not (
        ObservationAcquisitionEvaluationResult
    ):
        raise TypeError(
            "D evaluation must be an ObservationAcquisitionEvaluationResult"
        )
    replace(acquisition_evaluation)
    if not acquisition_evaluation.feasible:
        return ObservationAcquisitionEPSResult(
            acquisition_evaluation,
            None,
            None,
            None,
            None,
        )

    acquisition = acquisition_evaluation.acquisition_result
    if acquisition is None:
        raise ValueError("a feasible D result must contain acquisition data")
    combined_payload_w = _checked_sum(
        "combined payload request",
        environment.non_acquisition_loads.payload_w,
        acquisition.requested_acquisition_power_w,
    )
    combined_loads = replace(
        environment.non_acquisition_loads,
        payload_w=combined_payload_w,
    )
    eps_inputs = EPSIntervalInputs(
        environment.sunlit,
        environment.incidence_angle_deg,
        combined_loads,
    )
    capability = compute_eps_capability(eps_config, degradation_state)
    eps_result = compute_eps_interval_transition(
        battery_state,
        eps_config,
        eps_inputs,
        dt_seconds=next_candidate.acquisition_input.imaging_duration_seconds,
        capability=capability,
    )
    bounds = _service_bounds(acquisition_evaluation, eps_result)
    return ObservationAcquisitionEPSResult(
        acquisition_evaluation,
        eps_inputs,
        capability,
        eps_result,
        bounds,
    )


__all__ = [
    "AcquisitionEPSIntervalEnvironment",
    "AcquisitionServiceBounds",
    "AcquisitionServiceStatus",
    "ObservationAcquisitionEPSResult",
    "evaluate_observation_acquisition_eps",
]
