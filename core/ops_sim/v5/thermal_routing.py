"""Pure served-power validation and reduced-order thermal heat routing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Integral, Real

from .eps_system import EPSIntervalResult, EPSSubstepResult
from .ids import ParameterId, ThermalNodeId
from .parameters import ScalarParameter
from .power_loads import PowerLoadBreakdown
from .thermal import ThermalNodeAppliedHeatInput
from .thermal_config import ThermalNetworkConfig
from .thermal_coupling import (
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
)


class ElectricalLoadComponent(str, Enum):
    """The seven component families in ``PowerLoadBreakdown``."""

    BASE_BUS = "base-bus"
    OBC = "obc"
    ADCS = "adcs"
    PAYLOAD = "payload"
    COMMUNICATIONS = "communications"
    THERMAL_CONTROL = "thermal-control"
    PROPULSION = "propulsion"


_LOAD_FIELD_BY_COMPONENT = {
    ElectricalLoadComponent.BASE_BUS: "base_bus_w",
    ElectricalLoadComponent.OBC: "obc_w",
    ElectricalLoadComponent.ADCS: "adcs_w",
    ElectricalLoadComponent.PAYLOAD: "payload_w",
    ElectricalLoadComponent.COMMUNICATIONS: "communications_w",
    ElectricalLoadComponent.THERMAL_CONTROL: "thermal_control_w",
    ElectricalLoadComponent.PROPULSION: "propulsion_w",
}


def _normalized_real(name: str, value: object) -> int | float:
    """Return one admitted finite Real as a built-in numeric scalar."""
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


def _normalized_fraction(name: str, value: object) -> int | float:
    normalized = _normalized_nonnegative_real(name, value)
    if normalized > 1:
        raise ValueError(f"{name} must be less than or equal to one")
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


def _validate_complete_components(
    name: str,
    components: tuple[ElectricalLoadComponent, ...],
) -> None:
    if len(set(components)) != len(components):
        raise ValueError(f"{name} must not contain duplicate components")
    if set(components) != set(ElectricalLoadComponent):
        raise ValueError(
            f"{name} must contain exactly one entry for every "
            "ElectricalLoadComponent"
        )


@dataclass(frozen=True, slots=True)
class ServedComponentPower:
    """Explicit requested and actually served power for one component."""

    component: ElectricalLoadComponent
    requested_power_w: float
    served_power_w: float

    def __post_init__(self) -> None:
        if type(self.component) is not ElectricalLoadComponent:
            raise TypeError("component must be an ElectricalLoadComponent")
        requested = _normalized_nonnegative_real(
            "requested_power_w", self.requested_power_w
        )
        served = _normalized_nonnegative_real(
            "served_power_w", self.served_power_w
        )
        if served > requested:
            raise ValueError(
                "served_power_w must be less than or equal to "
                "requested_power_w"
            )


@dataclass(frozen=True, slots=True)
class ServedPowerLedger:
    """Explicit service allocation for every electrical load component."""

    components: tuple[ServedComponentPower, ...]

    def __post_init__(self) -> None:
        if type(self.components) is not tuple:
            raise TypeError("components must be a tuple")
        if not all(
            type(component) is ServedComponentPower
            for component in self.components
        ):
            raise TypeError(
                "components must contain only ServedComponentPower values"
            )
        for component in self.components:
            ServedComponentPower(
                component.component,
                component.requested_power_w,
                component.served_power_w,
            )
        _validate_complete_components(
            "components",
            tuple(component.component for component in self.components),
        )


@dataclass(frozen=True, slots=True)
class ComponentHeatRoute:
    """Configuration-owned retained-heat fraction and destination node."""

    component: ElectricalLoadComponent
    thermal_node_id: ThermalNodeId
    retained_heat_fraction: ScalarParameter

    def __post_init__(self) -> None:
        if type(self.component) is not ElectricalLoadComponent:
            raise TypeError("component must be an ElectricalLoadComponent")
        if type(self.thermal_node_id) is not ThermalNodeId:
            raise TypeError("thermal_node_id must be a ThermalNodeId")
        parameter = self.retained_heat_fraction
        if type(parameter) is not ScalarParameter:
            raise TypeError(
                "retained_heat_fraction must be a ScalarParameter"
            )
        expected_parameter_id = (
            f"thermal.routing.{self.component.value}.retained-heat-fraction"
        )
        if (
            type(parameter.parameter_id) is not ParameterId
            or parameter.parameter_id.value != expected_parameter_id
        ):
            raise ValueError(
                "retained_heat_fraction must use ParameterId "
                f"{expected_parameter_id!r}"
            )
        if parameter.units != "1":
            raise ValueError("retained_heat_fraction must use units '1'")
        _normalized_fraction(
            "retained_heat_fraction", parameter.value
        )


@dataclass(frozen=True, slots=True)
class ComponentHeatRoutingConfig:
    """One configuration-owned heat route for every load component."""

    routes: tuple[ComponentHeatRoute, ...]

    def __post_init__(self) -> None:
        if type(self.routes) is not tuple:
            raise TypeError("routes must be a tuple")
        if not all(type(route) is ComponentHeatRoute for route in self.routes):
            raise TypeError(
                "routes must contain only ComponentHeatRoute values"
            )
        for route in self.routes:
            ComponentHeatRoute(
                route.component,
                route.thermal_node_id,
                route.retained_heat_fraction,
            )
        _validate_complete_components(
            "routes", tuple(route.component for route in self.routes)
        )


@dataclass(frozen=True, slots=True)
class ComponentHeatLedger:
    """Served electrical power and retained heat for one component."""

    component: ElectricalLoadComponent
    requested_power_w: float
    served_power_w: float
    retained_heat_fraction: float
    thermal_node_id: ThermalNodeId
    retained_heat_w: float

    def __post_init__(self) -> None:
        if type(self.component) is not ElectricalLoadComponent:
            raise TypeError("component must be an ElectricalLoadComponent")
        requested = _normalized_nonnegative_real(
            "requested_power_w", self.requested_power_w
        )
        served = _normalized_nonnegative_real(
            "served_power_w", self.served_power_w
        )
        if served > requested:
            raise ValueError(
                "served_power_w must be less than or equal to "
                "requested_power_w"
            )
        fraction = _normalized_fraction(
            "retained_heat_fraction", self.retained_heat_fraction
        )
        if type(self.thermal_node_id) is not ThermalNodeId:
            raise TypeError("thermal_node_id must be a ThermalNodeId")
        retained = _normalized_nonnegative_real(
            "retained_heat_w", self.retained_heat_w
        )
        expected = _checked_product(
            "retained_heat_w", served, fraction
        )
        if retained != expected:
            raise ValueError(
                "retained_heat_w must equal served_power_w times "
                "retained_heat_fraction"
            )


@dataclass(frozen=True, slots=True)
class RoutedInternalHeatResult:
    """Component heat ledgers and their configured node aggregates."""

    component_ledgers: tuple[ComponentHeatLedger, ...]
    node_internal_heat_w: tuple[ThermalNodeAppliedHeatInput, ...]

    def __post_init__(self) -> None:
        if type(self.component_ledgers) is not tuple:
            raise TypeError("component_ledgers must be a tuple")
        if not all(
            type(ledger) is ComponentHeatLedger
            for ledger in self.component_ledgers
        ):
            raise TypeError(
                "component_ledgers must contain only ComponentHeatLedger "
                "values"
            )
        for ledger in self.component_ledgers:
            ComponentHeatLedger(
                ledger.component,
                ledger.requested_power_w,
                ledger.served_power_w,
                ledger.retained_heat_fraction,
                ledger.thermal_node_id,
                ledger.retained_heat_w,
            )
        _validate_complete_components(
            "component_ledgers",
            tuple(ledger.component for ledger in self.component_ledgers),
        )

        if type(self.node_internal_heat_w) is not tuple:
            raise TypeError("node_internal_heat_w must be a tuple")
        if not self.node_internal_heat_w:
            raise ValueError("node_internal_heat_w must not be empty")
        if not all(
            type(node_heat) is ThermalNodeAppliedHeatInput
            for node_heat in self.node_internal_heat_w
        ):
            raise TypeError(
                "node_internal_heat_w must contain only "
                "ThermalNodeAppliedHeatInput values"
            )
        for node_heat in self.node_internal_heat_w:
            ThermalNodeAppliedHeatInput(
                node_heat.node_id, node_heat.applied_heat_into_w
            )
            _normalized_nonnegative_real(
                "node internal heat", node_heat.applied_heat_into_w
            )
        node_ids = tuple(
            node_heat.node_id for node_heat in self.node_internal_heat_w
        )
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("node_internal_heat_w node IDs must be unique")
        node_id_set = set(node_ids)
        if any(
            ledger.thermal_node_id not in node_id_set
            for ledger in self.component_ledgers
        ):
            raise ValueError(
                "every component heat ledger must target a result node"
            )
        for node_heat in self.node_internal_heat_w:
            expected = _checked_sum(
                f"internal heat for {node_heat.node_id.canonical}",
                *(
                    ledger.retained_heat_w
                    for ledger in self.component_ledgers
                    if ledger.thermal_node_id == node_heat.node_id
                ),
            )
            if _normalized_real(
                "node internal heat", node_heat.applied_heat_into_w
            ) != expected:
                raise ValueError(
                    "node internal heat must equal routed component heat sum"
                )


def _validated_served_by_component(
    loads: PowerLoadBreakdown,
    served_power: ServedPowerLedger,
) -> dict[ElectricalLoadComponent, ServedComponentPower]:
    if type(loads) is not PowerLoadBreakdown:
        raise TypeError("loads must be a PowerLoadBreakdown")
    if type(served_power) is not ServedPowerLedger:
        raise TypeError("served_power must be a ServedPowerLedger")
    PowerLoadBreakdown(
        loads.base_bus_w,
        loads.obc_w,
        loads.adcs_w,
        loads.payload_w,
        loads.communications_w,
        loads.thermal_control_w,
        loads.propulsion_w,
    )
    ServedPowerLedger(served_power.components)
    served_by_component = {
        item.component: item for item in served_power.components
    }
    for component in ElectricalLoadComponent:
        item = served_by_component[component]
        requested = _normalized_real(
            f"requested power for {component.value}", item.requested_power_w
        )
        load = _normalized_real(
            f"load power for {component.value}",
            getattr(loads, _LOAD_FIELD_BY_COMPONENT[component]),
        )
        if requested != load:
            raise ValueError(
                f"requested power for {component.value} must match loads"
            )
    return served_by_component


def validate_served_power_matches_loads(
    loads: PowerLoadBreakdown,
    served_power: ServedPowerLedger,
) -> None:
    """Prove that an explicit service ledger belongs to a load breakdown."""
    _validated_served_by_component(loads, served_power)


def compute_routed_internal_heat(
    loads: PowerLoadBreakdown,
    served_power: ServedPowerLedger,
    routing_config: ComponentHeatRoutingConfig,
    thermal_config: ThermalNetworkConfig,
    *,
    eps_result: EPSIntervalResult | None = None,
) -> RoutedInternalHeatResult:
    """Compute component-retained heat and configured node aggregates."""
    return _compute_routed_internal_heat(loads, served_power, routing_config, thermal_config,
                                        eps_result=eps_result, eps_type=EPSIntervalResult)


def compute_substep_routed_internal_heat(loads, served_power, routing_config, thermal_config, *, eps_result):
    """The same exact service/heat owner with an explicit internal EPS result."""
    if type(eps_result) is not EPSSubstepResult:
        raise TypeError("eps_result must be EPSSubstepResult")
    eps_result.battery.__post_init__()
    return _compute_routed_internal_heat(loads, served_power, routing_config, thermal_config,
                                        eps_result=eps_result, eps_type=EPSSubstepResult)


def _compute_routed_internal_heat(loads, served_power, routing_config, thermal_config, *, eps_result, eps_type):
    served_by_component = _validated_served_by_component(
        loads, served_power
    )
    if type(routing_config) is not ComponentHeatRoutingConfig:
        raise TypeError(
            "routing_config must be a ComponentHeatRoutingConfig"
        )
    if type(thermal_config) is not ThermalNetworkConfig:
        raise TypeError("thermal_config must be a ThermalNetworkConfig")
    ComponentHeatRoutingConfig(routing_config.routes)
    ThermalNetworkConfig(
        thermal_config.nodes,
        thermal_config.links,
        thermal_config.bus_node_id,
        thermal_config.battery_node_id,
        thermal_config.payload_node_id,
    )

    if eps_result is not None:
        if type(eps_result) is not eps_type:
            raise TypeError("eps_result must be an EPSIntervalResult or None")
        eps_type(eps_result.solar, eps_result.loads, eps_result.battery)
        for component in ElectricalLoadComponent:
            field_name = _LOAD_FIELD_BY_COMPONENT[component]
            routing_load = _normalized_real(
                f"routing load power for {component.value}",
                getattr(loads, field_name),
            )
            eps_load = _normalized_real(
                f"EPS requested load power for {component.value}",
                getattr(eps_result.loads, field_name),
            )
            if routing_load != eps_load:
                raise ValueError(
                    "EPS requested load breakdown must match the routing "
                    "load breakdown"
                )
        total_served = _checked_sum(
            "total served component power",
            *(
                served_by_component[component].served_power_w
                for component in ElectricalLoadComponent
            ),
        )
        eps_served = _normalized_real(
            "EPS served load", eps_result.battery.served_load_w
        )
        if total_served != eps_served:
            raise ValueError(
                "total served component power must equal EPS served load"
            )

    configured_node_ids = {
        node.node_id for node in thermal_config.nodes
    }
    route_by_component = {
        route.component: route for route in routing_config.routes
    }
    unknown_route_nodes = {
        route.thermal_node_id
        for route in routing_config.routes
        if route.thermal_node_id not in configured_node_ids
    }
    if unknown_route_nodes:
        raise ValueError(
            "every heat route thermal node ID must exist in thermal_config"
        )

    component_ledgers = []
    node_heat_by_id: dict[ThermalNodeId, int | float] = {
        node.node_id: 0 for node in thermal_config.nodes
    }
    for component in ElectricalLoadComponent:
        served_item = served_by_component[component]
        route = route_by_component[component]
        fraction = _normalized_fraction(
            f"retained heat fraction for {component.value}",
            route.retained_heat_fraction.value,
        )
        retained_heat = _checked_product(
            f"retained heat for {component.value}",
            served_item.served_power_w,
            fraction,
        )
        ledger = ComponentHeatLedger(
            component,
            _normalized_real(
                f"requested power for {component.value}",
                served_item.requested_power_w,
            ),
            _normalized_real(
                f"served power for {component.value}",
                served_item.served_power_w,
            ),
            fraction,
            route.thermal_node_id,
            retained_heat,
        )
        component_ledgers.append(ledger)
        node_heat_by_id[route.thermal_node_id] = _checked_sum(
            f"node internal heat for {route.thermal_node_id.canonical}",
            node_heat_by_id[route.thermal_node_id],
            retained_heat,
        )

    return RoutedInternalHeatResult(
        tuple(component_ledgers),
        tuple(
            ThermalNodeAppliedHeatInput(
                node.node_id, node_heat_by_id[node.node_id]
            )
            for node in thermal_config.nodes
        ),
    )


def compose_routed_internal_heat_sources(
    routed_heat: RoutedInternalHeatResult,
    heat_source_inputs: ThermalHeatSourceInputs,
) -> ThermalHeatSourceInputs:
    """Set C1 internal heat while preserving its external absorbed sources."""
    if type(routed_heat) is not RoutedInternalHeatResult:
        raise TypeError("routed_heat must be a RoutedInternalHeatResult")
    if type(heat_source_inputs) is not ThermalHeatSourceInputs:
        raise TypeError(
            "heat_source_inputs must be a ThermalHeatSourceInputs"
        )
    RoutedInternalHeatResult(
        routed_heat.component_ledgers, routed_heat.node_internal_heat_w
    )
    ThermalHeatSourceInputs(heat_source_inputs.node_sources)

    routed_node_ids = {
        node_heat.node_id for node_heat in routed_heat.node_internal_heat_w
    }
    source_node_ids = {
        source.node_id for source in heat_source_inputs.node_sources
    }
    if routed_node_ids != source_node_ids:
        raise ValueError(
            "routed-heat node IDs must exactly match heat-source node IDs"
        )
    source_by_id = {
        source.node_id: source for source in heat_source_inputs.node_sources
    }
    return ThermalHeatSourceInputs(
        tuple(
            ThermalNodeHeatSourceInput(
                node_heat.node_id,
                _normalized_nonnegative_real(
                    "routed internal heat", node_heat.applied_heat_into_w
                ),
                source_by_id[node_heat.node_id].absorbed_solar_w,
                source_by_id[node_heat.node_id].absorbed_albedo_w,
                source_by_id[node_heat.node_id].absorbed_earth_ir_w,
            )
            for node_heat in routed_heat.node_internal_heat_w
        )
    )


__all__ = [
    "ComponentHeatLedger",
    "ComponentHeatRoute",
    "ComponentHeatRoutingConfig",
    "ElectricalLoadComponent",
    "RoutedInternalHeatResult",
    "ServedComponentPower",
    "ServedPowerLedger",
    "compose_routed_internal_heat_sources",
    "compute_routed_internal_heat",
    "validate_served_power_matches_loads",
]
