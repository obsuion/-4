"""Pure Level-1 lumped thermal conduction and radiation physics for V5."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real

from .integration_time import DyadicDuration, checked_duration, validate_substep_seconds
from .ids import ThermalLinkId, ThermalNodeId
from .state import ThermalState
from .thermal_config import ThermalNetworkConfig


_STEFAN_BOLTZMANN_W_PER_M2_K4 = 5.670374419e-8


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


def _validate_positive_real(name: str, value: object) -> None:
    normalized = _normalized_real(name, value)
    if normalized <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _validate_finite_real(name: str, value: object) -> None:
    _normalized_real(name, value)


def _checked_sum(name: str, left: object, right: object) -> int | float:
    left_value = _normalized_real(f"{name} left operand", left)
    right_value = _normalized_real(f"{name} right operand", right)
    try:
        value = left_value + right_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    return _normalized_real(name, value)


def _checked_difference(
    name: str,
    minuend: object,
    subtrahend: object,
) -> int | float:
    minuend_value = _normalized_real(f"{name} minuend", minuend)
    subtrahend_value = _normalized_real(f"{name} subtrahend", subtrahend)
    try:
        value = minuend_value - subtrahend_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    return _normalized_real(name, value)


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
        value = numerator_value / denominator_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    normalized = _normalized_real(name, value)
    if numerator_value != 0 and normalized == 0:
        raise ValueError(f"{name} cannot represent a nonzero quotient")
    return normalized


def _checked_fourth_power(name: str, value: object) -> int | float:
    base = _normalized_real(name, value)
    try:
        fourth_power = base**4
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{name} fourth power cannot be represented as finite"
        ) from error
    normalized = _normalized_real(f"{name} fourth power", fourth_power)
    if base != 0 and normalized == 0:
        raise ValueError(
            f"{name} fourth power cannot represent a positive value"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class ThermalNodeBoundaryInput:
    """Transient effective radiative sink boundary for one thermal node."""

    node_id: ThermalNodeId
    radiative_sink_temperature_k: float

    def __post_init__(self) -> None:
        if type(self.node_id) is not ThermalNodeId:
            raise TypeError("node_id must be a ThermalNodeId")
        _validate_positive_real(
            "radiative_sink_temperature_k",
            self.radiative_sink_temperature_k,
        )


@dataclass(frozen=True, slots=True)
class ThermalIntervalInputs:
    """Transient radiative boundaries for one thermal interval."""

    node_boundaries: tuple[ThermalNodeBoundaryInput, ...]

    def __post_init__(self) -> None:
        if type(self.node_boundaries) is not tuple:
            raise TypeError("node_boundaries must be a tuple")
        if not self.node_boundaries:
            raise ValueError("node_boundaries must not be empty")
        if not all(
            type(boundary) is ThermalNodeBoundaryInput
            for boundary in self.node_boundaries
        ):
            raise TypeError(
                "node_boundaries must contain only "
                "ThermalNodeBoundaryInput values"
            )
        for boundary in self.node_boundaries:
            ThermalNodeBoundaryInput(
                boundary.node_id,
                boundary.radiative_sink_temperature_k,
            )
        node_ids = tuple(boundary.node_id for boundary in self.node_boundaries)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("thermal boundary node IDs must be unique")


@dataclass(frozen=True, slots=True)
class ThermalNodeAppliedHeatInput:
    """Transient signed applied heat for one thermal node."""

    node_id: ThermalNodeId
    applied_heat_into_w: float

    def __post_init__(self) -> None:
        if type(self.node_id) is not ThermalNodeId:
            raise TypeError("node_id must be a ThermalNodeId")
        _validate_finite_real(
            "applied_heat_into_w",
            self.applied_heat_into_w,
        )


@dataclass(frozen=True, slots=True)
class ThermalAppliedHeatInputs:
    """Transient signed applied heat for every configured thermal node."""

    node_heat_inputs: tuple[ThermalNodeAppliedHeatInput, ...]

    def __post_init__(self) -> None:
        if type(self.node_heat_inputs) is not tuple:
            raise TypeError("node_heat_inputs must be a tuple")
        if not self.node_heat_inputs:
            raise ValueError("node_heat_inputs must not be empty")
        if not all(
            type(heat_input) is ThermalNodeAppliedHeatInput
            for heat_input in self.node_heat_inputs
        ):
            raise TypeError(
                "node_heat_inputs must contain only "
                "ThermalNodeAppliedHeatInput values"
            )
        for heat_input in self.node_heat_inputs:
            ThermalNodeAppliedHeatInput(
                heat_input.node_id,
                heat_input.applied_heat_into_w,
            )
        node_ids = tuple(
            heat_input.node_id for heat_input in self.node_heat_inputs
        )
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("applied-heat node IDs must be unique")


@dataclass(frozen=True, slots=True)
class ThermalLinkHeatFlow:
    """Signed heat flow for one configured conductive link."""

    link_id: ThermalLinkId
    node_a_id: ThermalNodeId
    node_b_id: ThermalNodeId
    heat_flow_a_to_b_w: float

    def __post_init__(self) -> None:
        if type(self.link_id) is not ThermalLinkId:
            raise TypeError("link_id must be a ThermalLinkId")
        if type(self.node_a_id) is not ThermalNodeId:
            raise TypeError("node_a_id must be a ThermalNodeId")
        if type(self.node_b_id) is not ThermalNodeId:
            raise TypeError("node_b_id must be a ThermalNodeId")
        if self.node_a_id == self.node_b_id:
            raise ValueError("thermal link endpoints must be distinct")
        _validate_finite_real(
            "heat_flow_a_to_b_w",
            self.heat_flow_a_to_b_w,
        )


@dataclass(frozen=True, slots=True)
class ThermalNodeTransition:
    """Signed energy and temperature proposal for one thermal node."""

    node_id: ThermalNodeId
    start_temperature_k: float
    end_temperature_k: float
    conductive_heat_into_w: float
    radiative_heat_into_w: float
    applied_heat_into_w: float
    net_heat_into_w: float
    thermal_energy_change_j: float

    def __post_init__(self) -> None:
        if type(self.node_id) is not ThermalNodeId:
            raise TypeError("node_id must be a ThermalNodeId")
        _validate_positive_real(
            "start_temperature_k",
            self.start_temperature_k,
        )
        _validate_positive_real("end_temperature_k", self.end_temperature_k)
        for name, value in (
            ("conductive_heat_into_w", self.conductive_heat_into_w),
            ("radiative_heat_into_w", self.radiative_heat_into_w),
            ("applied_heat_into_w", self.applied_heat_into_w),
            ("net_heat_into_w", self.net_heat_into_w),
            ("thermal_energy_change_j", self.thermal_energy_change_j),
        ):
            _validate_finite_real(name, value)
        exchange_heat_into_w = _checked_sum(
            "net_heat_into_w",
            self.conductive_heat_into_w,
            self.radiative_heat_into_w,
        )
        expected_net_heat_into_w = _checked_sum(
            "net_heat_into_w",
            exchange_heat_into_w,
            self.applied_heat_into_w,
        )
        if _normalized_real("net_heat_into_w", self.net_heat_into_w) != (
            expected_net_heat_into_w
        ):
            raise ValueError(
                "net_heat_into_w must equal conductive_heat_into_w plus "
                "radiative_heat_into_w plus applied_heat_into_w"
            )


@dataclass(frozen=True, slots=True)
class ThermalIntervalResult:
    """Transient observable ledger for one pure thermal transition."""

    node_transitions: tuple[ThermalNodeTransition, ...]
    link_heat_flows: tuple[ThermalLinkHeatFlow, ...]
    dt_seconds: int

    def __post_init__(self) -> None:
        if type(self.node_transitions) is not tuple:
            raise TypeError("node_transitions must be a tuple")
        if not all(
            type(transition) is ThermalNodeTransition
            for transition in self.node_transitions
        ):
            raise TypeError(
                "node_transitions must contain only ThermalNodeTransition "
                "values"
            )
        for transition in self.node_transitions:
            ThermalNodeTransition(
                transition.node_id,
                transition.start_temperature_k,
                transition.end_temperature_k,
                transition.conductive_heat_into_w,
                transition.radiative_heat_into_w,
                transition.applied_heat_into_w,
                transition.net_heat_into_w,
                transition.thermal_energy_change_j,
            )
        node_ids = tuple(
            transition.node_id for transition in self.node_transitions
        )
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("thermal transition node IDs must be unique")

        if type(self.link_heat_flows) is not tuple:
            raise TypeError("link_heat_flows must be a tuple")
        if not all(
            type(flow) is ThermalLinkHeatFlow
            for flow in self.link_heat_flows
        ):
            raise TypeError(
                "link_heat_flows must contain only ThermalLinkHeatFlow values"
            )
        for flow in self.link_heat_flows:
            ThermalLinkHeatFlow(
                flow.link_id,
                flow.node_a_id,
                flow.node_b_id,
                flow.heat_flow_a_to_b_w,
            )
        link_ids = tuple(flow.link_id for flow in self.link_heat_flows)
        if len(set(link_ids)) != len(link_ids):
            raise ValueError("thermal result link IDs must be unique")

        self._validate_duration()

    def _validate_duration(self):
        if type(self.dt_seconds) is not int:
            raise TypeError("dt_seconds must be an integer")
        if self.dt_seconds <= 0:
            raise ValueError("dt_seconds must be greater than zero")


@dataclass(frozen=True, slots=True)
class ThermalSubstepResult(ThermalIntervalResult):
    dt_seconds: float
    duration: DyadicDuration

    def _validate_duration(self):
        validate_substep_seconds(self.dt_seconds, self.duration)


def compute_thermal_substep_transition(state, config, inputs, applied_heat_inputs=None, *, duration):
    """Same simultaneous Euler equations over an explicit internal duration."""
    if applied_heat_inputs is not None and type(applied_heat_inputs) is not ThermalAppliedHeatInputs:
        raise TypeError("applied_heat_inputs must be ThermalAppliedHeatInputs or None")
    return _compute_thermal_interval_transition(state, config, inputs, applied_heat_inputs,
        dt_seconds=checked_duration(duration), _duration=duration)


def compute_thermal_interval_transition(
    state: ThermalState,
    config: ThermalNetworkConfig,
    inputs: ThermalIntervalInputs,
    *,
    dt_seconds: int,
) -> ThermalIntervalResult:
    """Compute one pure proposal with zero applied heat at every node."""
    return _compute_thermal_interval_transition(
        state,
        config,
        inputs,
        None,
        dt_seconds=dt_seconds,
    )


def compute_thermal_interval_transition_with_applied_heat(
    state: ThermalState,
    config: ThermalNetworkConfig,
    inputs: ThermalIntervalInputs,
    applied_heat_inputs: ThermalAppliedHeatInputs,
    *,
    dt_seconds: int,
) -> ThermalIntervalResult:
    """Compute one pure proposal with explicit signed applied node heat."""
    if type(applied_heat_inputs) is not ThermalAppliedHeatInputs:
        raise TypeError(
            "applied_heat_inputs must be a ThermalAppliedHeatInputs"
        )
    return _compute_thermal_interval_transition(
        state,
        config,
        inputs,
        applied_heat_inputs,
        dt_seconds=dt_seconds,
    )


def _compute_thermal_interval_transition(
    state: ThermalState,
    config: ThermalNetworkConfig,
    inputs: ThermalIntervalInputs,
    applied_heat_inputs: ThermalAppliedHeatInputs | None,
    *,
    dt_seconds: int | float,
    _duration: DyadicDuration | None = None,
) -> ThermalIntervalResult:
    """Evaluate the shared simultaneous conduction/radiation/Euler core."""
    if type(state) is not ThermalState:
        raise TypeError("state must be a ThermalState")
    if type(config) is not ThermalNetworkConfig:
        raise TypeError("config must be a ThermalNetworkConfig")
    if type(inputs) is not ThermalIntervalInputs:
        raise TypeError("inputs must be a ThermalIntervalInputs")
    if _duration is None:
        if type(dt_seconds) is not int:
            raise TypeError("dt_seconds must be an integer")
        if dt_seconds <= 0:
            raise ValueError("dt_seconds must be greater than zero")
    else:
        validate_substep_seconds(dt_seconds, _duration)

    try:
        ThermalState(state.node_states)
        ThermalNetworkConfig(
            config.nodes,
            config.links,
            config.bus_node_id,
            config.battery_node_id,
            config.payload_node_id,
        )
        ThermalIntervalInputs(inputs.node_boundaries)
        if applied_heat_inputs is not None:
            ThermalAppliedHeatInputs(applied_heat_inputs.node_heat_inputs)
    except (TypeError, ValueError):
        raise
    except (AttributeError, ArithmeticError) as error:
        raise ValueError("thermal inputs cannot be evaluated safely") from error

    configured_node_ids = {node.node_id for node in config.nodes}
    runtime_node_ids = {
        node_state.node_id for node_state in state.node_states
    }
    boundary_node_ids = {
        boundary.node_id for boundary in inputs.node_boundaries
    }
    if runtime_node_ids != configured_node_ids:
        raise ValueError(
            "runtime thermal node IDs must exactly match configured node IDs"
        )
    if boundary_node_ids != configured_node_ids:
        raise ValueError(
            "thermal boundary node IDs must exactly match configured node IDs"
        )

    if applied_heat_inputs is None:
        applied_heat_into_by_id: dict[ThermalNodeId, int | float] = {
            node.node_id: 0 for node in config.nodes
        }
    else:
        applied_heat_node_ids = {
            heat_input.node_id
            for heat_input in applied_heat_inputs.node_heat_inputs
        }
        if applied_heat_node_ids != configured_node_ids:
            raise ValueError(
                "applied-heat node IDs must exactly match configured node IDs"
            )
        applied_heat_into_by_id = {
            heat_input.node_id: _normalized_real(
                f"applied heat for {heat_input.node_id.canonical}",
                heat_input.applied_heat_into_w,
            )
            for heat_input in applied_heat_inputs.node_heat_inputs
        }

    start_temperature_by_id = {
        node_state.node_id: _normalized_real(
            f"start temperature for {node_state.node_id.canonical}",
            node_state.temperature_k,
        )
        for node_state in state.node_states
    }
    sink_temperature_by_id = {
        boundary.node_id: _normalized_real(
            f"radiative sink temperature for {boundary.node_id.canonical}",
            boundary.radiative_sink_temperature_k,
        )
        for boundary in inputs.node_boundaries
    }
    conductive_heat_into_by_id: dict[ThermalNodeId, int | float] = {
        node.node_id: 0 for node in config.nodes
    }

    link_heat_flows = []
    for link in config.links:
        temperature_difference_k = _checked_difference(
            f"temperature difference for {link.link_id.canonical}",
            start_temperature_by_id[link.node_a_id],
            start_temperature_by_id[link.node_b_id],
        )
        heat_flow_a_to_b_w = _checked_product(
            f"conductive heat flow for {link.link_id.canonical}",
            link.conductance_w_per_k.value,
            temperature_difference_k,
        )
        conductive_heat_into_by_id[link.node_a_id] = _checked_difference(
            f"conductive heat into {link.node_a_id.canonical}",
            conductive_heat_into_by_id[link.node_a_id],
            heat_flow_a_to_b_w,
        )
        conductive_heat_into_by_id[link.node_b_id] = _checked_sum(
            f"conductive heat into {link.node_b_id.canonical}",
            conductive_heat_into_by_id[link.node_b_id],
            heat_flow_a_to_b_w,
        )
        link_heat_flows.append(
            ThermalLinkHeatFlow(
                link.link_id,
                link.node_a_id,
                link.node_b_id,
                heat_flow_a_to_b_w,
            )
        )

    node_transitions = []
    for node in config.nodes:
        node_id = node.node_id
        start_temperature_k = start_temperature_by_id[node_id]
        sink_temperature_k = sink_temperature_by_id[node_id]
        sink_fourth_power = _checked_fourth_power(
            f"radiative sink temperature for {node_id.canonical}",
            sink_temperature_k,
        )
        node_fourth_power = _checked_fourth_power(
            f"node temperature for {node_id.canonical}",
            start_temperature_k,
        )
        fourth_power_difference = _checked_difference(
            f"radiative fourth-power difference for {node_id.canonical}",
            sink_fourth_power,
            node_fourth_power,
        )
        radiative_heat_into_w = _checked_product(
            f"radiative heat into {node_id.canonical}",
            node.emissivity.value,
            _STEFAN_BOLTZMANN_W_PER_M2_K4,
            node.radiating_area_m2.value,
            fourth_power_difference,
        )
        conductive_heat_into_w = conductive_heat_into_by_id[node_id]
        applied_heat_into_w = applied_heat_into_by_id[node_id]
        exchange_heat_into_w = _checked_sum(
            f"net heat into {node_id.canonical}",
            conductive_heat_into_w,
            radiative_heat_into_w,
        )
        net_heat_into_w = _checked_sum(
            f"net heat into {node_id.canonical}",
            exchange_heat_into_w,
            applied_heat_into_w,
        )
        thermal_energy_change_j = _checked_product(
            f"thermal energy change for {node_id.canonical}",
            net_heat_into_w,
            dt_seconds,
        )
        temperature_change_k = _checked_quotient(
            f"temperature change for {node_id.canonical}",
            thermal_energy_change_j,
            node.heat_capacity_j_per_k.value,
        )
        end_temperature_k = _checked_sum(
            f"end temperature for {node_id.canonical}",
            start_temperature_k,
            temperature_change_k,
        )
        if end_temperature_k <= 0:
            raise ValueError(
                f"end temperature for {node_id.canonical} must be greater "
                "than zero"
            )
        node_transitions.append(
            ThermalNodeTransition(
                node_id,
                start_temperature_k,
                end_temperature_k,
                conductive_heat_into_w,
                radiative_heat_into_w,
                applied_heat_into_w,
                net_heat_into_w,
                thermal_energy_change_j,
            )
        )

    result_type = ThermalIntervalResult if _duration is None else ThermalSubstepResult
    extra = {} if _duration is None else {"duration": _duration}
    return result_type(
        tuple(node_transitions),
        tuple(link_heat_flows),
        dt_seconds,
        **extra,
    )


__all__ = [
    "ThermalAppliedHeatInputs",
    "ThermalIntervalInputs",
    "ThermalIntervalResult",
    "ThermalLinkHeatFlow",
    "ThermalNodeAppliedHeatInput",
    "ThermalNodeBoundaryInput",
    "ThermalNodeTransition",
    "compute_thermal_interval_transition",
    "compute_thermal_interval_transition_with_applied_heat",
]
