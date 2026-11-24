"""Pure explicit-source and EPS-loss coupling for V5 thermal physics.

Callers must keep the effective radiative sink boundary and explicit absorbed
solar, albedo, and Earth-IR powers physically non-overlapping. The same
incoming radiative flux must not be represented by both mechanisms.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real

from .eps_system import EPSIntervalResult, EPSSubstepResult
from .integration_time import checked_duration, validate_substep_seconds
from .ids import ThermalNodeId
from .state import ThermalState
from .thermal import (
    ThermalAppliedHeatInputs,
    ThermalIntervalInputs,
    ThermalIntervalResult, ThermalSubstepResult, compute_thermal_substep_transition,
    ThermalNodeAppliedHeatInput,
    compute_thermal_interval_transition_with_applied_heat,
)
from .thermal_config import ThermalNetworkConfig


_JOULES_PER_WATT_HOUR = 3600


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


def _checked_sum(name: str, *values: object) -> int | float:
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


def _checked_product(name: str, left: object, right: object) -> int | float:
    left_value = _normalized_real(f"{name} left factor", left)
    right_value = _normalized_real(f"{name} right factor", right)
    try:
        product = left_value * right_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    normalized = _normalized_real(name, product)
    if left_value != 0 and right_value != 0 and normalized == 0:
        raise ValueError(f"{name} cannot represent a nonzero product")
    return normalized


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


@dataclass(frozen=True, slots=True)
class ThermalNodeHeatSourceInput:
    """Explicit nonnegative heat sources already assigned to one node."""

    node_id: ThermalNodeId
    internal_dissipation_w: float
    absorbed_solar_w: float
    absorbed_albedo_w: float
    absorbed_earth_ir_w: float

    def __post_init__(self) -> None:
        if type(self.node_id) is not ThermalNodeId:
            raise TypeError("node_id must be a ThermalNodeId")
        for field_name, value in (
            ("internal_dissipation_w", self.internal_dissipation_w),
            ("absorbed_solar_w", self.absorbed_solar_w),
            ("absorbed_albedo_w", self.absorbed_albedo_w),
            ("absorbed_earth_ir_w", self.absorbed_earth_ir_w),
        ):
            _normalized_nonnegative_real(field_name, value)


@dataclass(frozen=True, slots=True)
class ThermalHeatSourceInputs:
    """Explicit nonnegative heat sources for every configured node."""

    node_sources: tuple[ThermalNodeHeatSourceInput, ...]

    def __post_init__(self) -> None:
        if type(self.node_sources) is not tuple:
            raise TypeError("node_sources must be a tuple")
        if not self.node_sources:
            raise ValueError("node_sources must not be empty")
        if not all(
            type(source) is ThermalNodeHeatSourceInput
            for source in self.node_sources
        ):
            raise TypeError(
                "node_sources must contain only ThermalNodeHeatSourceInput "
                "values"
            )
        for source in self.node_sources:
            ThermalNodeHeatSourceInput(
                source.node_id,
                source.internal_dissipation_w,
                source.absorbed_solar_w,
                source.absorbed_albedo_w,
                source.absorbed_earth_ir_w,
            )
        node_ids = tuple(source.node_id for source in self.node_sources)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("thermal heat-source node IDs must be unique")


@dataclass(frozen=True, slots=True)
class ThermalNodeHeatLedger:
    """Source-resolved nonnegative applied heat for one thermal node."""

    node_id: ThermalNodeId
    internal_dissipation_w: float
    absorbed_solar_w: float
    absorbed_albedo_w: float
    absorbed_earth_ir_w: float
    battery_conversion_heat_w: float
    total_applied_heat_w: float

    def __post_init__(self) -> None:
        if type(self.node_id) is not ThermalNodeId:
            raise TypeError("node_id must be a ThermalNodeId")
        components = (
            ("internal_dissipation_w", self.internal_dissipation_w),
            ("absorbed_solar_w", self.absorbed_solar_w),
            ("absorbed_albedo_w", self.absorbed_albedo_w),
            ("absorbed_earth_ir_w", self.absorbed_earth_ir_w),
            ("battery_conversion_heat_w", self.battery_conversion_heat_w),
        )
        normalized_components = tuple(
            _normalized_nonnegative_real(name, value)
            for name, value in components
        )
        normalized_total = _normalized_nonnegative_real(
            "total_applied_heat_w",
            self.total_applied_heat_w,
        )
        expected_total = _checked_sum(
            "total_applied_heat_w",
            *normalized_components,
        )
        if normalized_total != expected_total:
            raise ValueError(
                "total_applied_heat_w must equal the sum of all source "
                "components"
            )


@dataclass(frozen=True, slots=True)
class EPSThermalCouplingResult:
    """Transient source ledgers and their pure thermal proposal."""

    node_heat_ledgers: tuple[ThermalNodeHeatLedger, ...]
    thermal_result: ThermalIntervalResult

    def __post_init__(self) -> None:
        if type(self.node_heat_ledgers) is not tuple:
            raise TypeError("node_heat_ledgers must be a tuple")
        if not self.node_heat_ledgers:
            raise ValueError("node_heat_ledgers must not be empty")
        if not all(
            type(ledger) is ThermalNodeHeatLedger
            for ledger in self.node_heat_ledgers
        ):
            raise TypeError(
                "node_heat_ledgers must contain only ThermalNodeHeatLedger "
                "values"
            )
        for ledger in self.node_heat_ledgers:
            ThermalNodeHeatLedger(
                ledger.node_id,
                ledger.internal_dissipation_w,
                ledger.absorbed_solar_w,
                ledger.absorbed_albedo_w,
                ledger.absorbed_earth_ir_w,
                ledger.battery_conversion_heat_w,
                ledger.total_applied_heat_w,
            )
        ledger_node_ids = tuple(
            ledger.node_id for ledger in self.node_heat_ledgers
        )
        if len(set(ledger_node_ids)) != len(ledger_node_ids):
            raise ValueError("thermal heat-ledger node IDs must be unique")

        if type(self.thermal_result) is not self._thermal_type():
            raise TypeError("thermal_result must be a ThermalIntervalResult")
        self.thermal_result.__post_init__()
        transition_node_ids = {
            transition.node_id
            for transition in self.thermal_result.node_transitions
        }
        if set(ledger_node_ids) != transition_node_ids:
            raise ValueError(
                "heat-ledger node IDs must exactly match thermal-result node "
                "IDs"
            )

    def _thermal_type(self):
        return ThermalIntervalResult


@dataclass(frozen=True, slots=True)
class EPSThermalSubstepResult(EPSThermalCouplingResult):
    thermal_result: ThermalSubstepResult
    def _thermal_type(self):
        return ThermalSubstepResult


def compute_eps_thermal_substep_transition(state, config, thermal_inputs, heat_source_inputs,
                                         eps_result, *, duration):
    return _compute_eps_thermal_transition(state, config, thermal_inputs, heat_source_inputs,
        eps_result, dt_seconds=checked_duration(duration), _duration=duration)


def compute_eps_thermal_interval_transition(
    state: ThermalState,
    config: ThermalNetworkConfig,
    thermal_inputs: ThermalIntervalInputs,
    heat_source_inputs: ThermalHeatSourceInputs,
    eps_result: EPSIntervalResult,
    *,
    dt_seconds: int,
) -> EPSThermalCouplingResult:
    """Couple explicit sources and battery loss into one pure transition.

    ``internal_dissipation_w`` is caller-supplied heat known to remain inside
    the thermal network; it is not inferred from electrical demand. Absorbed
    radiative sources must not duplicate incoming flux represented by the
    effective radiative sink boundary.
    """
    return _compute_eps_thermal_transition(state, config, thermal_inputs, heat_source_inputs,
                                         eps_result, dt_seconds=dt_seconds)


def _compute_eps_thermal_transition(state, config, thermal_inputs, heat_source_inputs,
                                   eps_result, *, dt_seconds, _duration=None):
    if type(state) is not ThermalState:
        raise TypeError("state must be a ThermalState")
    if type(config) is not ThermalNetworkConfig:
        raise TypeError("config must be a ThermalNetworkConfig")
    if type(thermal_inputs) is not ThermalIntervalInputs:
        raise TypeError("thermal_inputs must be a ThermalIntervalInputs")
    if type(heat_source_inputs) is not ThermalHeatSourceInputs:
        raise TypeError(
            "heat_source_inputs must be a ThermalHeatSourceInputs"
        )
    eps_type = EPSIntervalResult if _duration is None else EPSSubstepResult
    if type(eps_result) is not eps_type:
        raise TypeError("eps_result must be an EPSIntervalResult")
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
        ThermalIntervalInputs(thermal_inputs.node_boundaries)
        ThermalHeatSourceInputs(heat_source_inputs.node_sources)
        eps_type(eps_result.solar, eps_result.loads, eps_result.battery)
    except (TypeError, ValueError):
        raise
    except (AttributeError, ArithmeticError) as error:
        raise ValueError("coupling inputs cannot be evaluated safely") from error

    configured_node_ids = {node.node_id for node in config.nodes}
    runtime_node_ids = {
        node_state.node_id for node_state in state.node_states
    }
    boundary_node_ids = {
        boundary.node_id for boundary in thermal_inputs.node_boundaries
    }
    source_node_ids = {
        source.node_id for source in heat_source_inputs.node_sources
    }
    if runtime_node_ids != configured_node_ids:
        raise ValueError(
            "runtime thermal node IDs must exactly match configured node IDs"
        )
    if boundary_node_ids != configured_node_ids:
        raise ValueError(
            "thermal boundary node IDs must exactly match configured node IDs"
        )
    if source_node_ids != configured_node_ids:
        raise ValueError(
            "thermal heat-source node IDs must exactly match configured node "
            "IDs"
        )

    eps_dt_seconds = eps_result.battery.dt_seconds
    if _duration is None:
        if type(eps_dt_seconds) is not int:
            raise TypeError("eps_result battery dt_seconds must be an integer")
    else:
        eps_result.battery.__post_init__()
        if eps_result.battery.duration != _duration:
            raise ValueError("EPS and thermal dyadic durations must match")
    if eps_dt_seconds <= 0:
        raise ValueError(
            "eps_result battery dt_seconds must be greater than zero"
        )
    if eps_dt_seconds != dt_seconds:
        raise ValueError(
            "EPS battery dt_seconds must equal thermal dt_seconds"
        )
    conversion_loss_wh = _normalized_nonnegative_real(
        "battery conversion_loss_wh",
        eps_result.battery.conversion_loss_wh,
    )
    conversion_loss_j = _checked_product(
        "battery conversion loss energy in J",
        conversion_loss_wh,
        _JOULES_PER_WATT_HOUR,
    )
    battery_conversion_heat_w = _checked_quotient(
        "battery conversion heat in W",
        conversion_loss_j,
        dt_seconds,
    )
    battery_conversion_heat_w = _normalized_nonnegative_real(
        "battery conversion heat in W",
        battery_conversion_heat_w,
    )

    source_by_id = {
        source.node_id: source for source in heat_source_inputs.node_sources
    }
    ledgers = []
    for node in config.nodes:
        source = source_by_id[node.node_id]
        internal_dissipation_w = _normalized_nonnegative_real(
            f"internal dissipation for {node.node_id.canonical}",
            source.internal_dissipation_w,
        )
        absorbed_solar_w = _normalized_nonnegative_real(
            f"absorbed solar heat for {node.node_id.canonical}",
            source.absorbed_solar_w,
        )
        absorbed_albedo_w = _normalized_nonnegative_real(
            f"absorbed albedo heat for {node.node_id.canonical}",
            source.absorbed_albedo_w,
        )
        absorbed_earth_ir_w = _normalized_nonnegative_real(
            f"absorbed Earth-IR heat for {node.node_id.canonical}",
            source.absorbed_earth_ir_w,
        )
        node_battery_conversion_heat_w = (
            battery_conversion_heat_w
            if node.node_id == config.battery_node_id
            else 0
        )
        total_applied_heat_w = _checked_sum(
            f"total applied heat for {node.node_id.canonical}",
            internal_dissipation_w,
            absorbed_solar_w,
            absorbed_albedo_w,
            absorbed_earth_ir_w,
            node_battery_conversion_heat_w,
        )
        ledgers.append(
            ThermalNodeHeatLedger(
                node.node_id,
                internal_dissipation_w,
                absorbed_solar_w,
                absorbed_albedo_w,
                absorbed_earth_ir_w,
                node_battery_conversion_heat_w,
                total_applied_heat_w,
            )
        )

    node_heat_ledgers = tuple(ledgers)
    applied_heat_inputs = ThermalAppliedHeatInputs(
        tuple(
            ThermalNodeAppliedHeatInput(
                ledger.node_id,
                ledger.total_applied_heat_w,
            )
            for ledger in node_heat_ledgers
        )
    )
    if _duration is None:
        thermal_result = compute_thermal_interval_transition_with_applied_heat(
            state, config, thermal_inputs, applied_heat_inputs, dt_seconds=dt_seconds)
    else:
        thermal_result = compute_thermal_substep_transition(
            state, config, thermal_inputs, applied_heat_inputs, duration=_duration)
    result_type = EPSThermalCouplingResult if _duration is None else EPSThermalSubstepResult
    return result_type(node_heat_ledgers, thermal_result)


__all__ = [
    "EPSThermalCouplingResult",
    "ThermalHeatSourceInputs",
    "ThermalNodeHeatLedger",
    "ThermalNodeHeatSourceInput",
    "compute_eps_thermal_interval_transition",
]
