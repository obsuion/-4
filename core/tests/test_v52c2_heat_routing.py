"""Behavioral and structural validation for V5.2C2 heat routing."""

import ast
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from pathlib import Path

import numpy as np
import pytest

from ops_sim.v5.configuration import (
    BatteryConfig,
    EPSConfig,
    SolarArrayConfig,
)
from ops_sim.v5.eps_system import (
    EPSIntervalInputs,
    compute_eps_interval_transition,
)
from ops_sim.v5.ids import (
    ParameterId,
    SubsystemConfigurationId,
    ThermalNodeId,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import BatteryState, ThermalNodeState, ThermalState
from ops_sim.v5.thermal import (
    ThermalIntervalInputs,
    ThermalNodeAppliedHeatInput,
    ThermalNodeBoundaryInput,
)
from ops_sim.v5.thermal_config import (
    ThermalNetworkConfig,
    ThermalNodeConfig,
)
from ops_sim.v5.thermal_coupling import (
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
    compute_eps_thermal_interval_transition,
)
from ops_sim.v5.thermal_routing import (
    ComponentHeatLedger,
    ComponentHeatRoute,
    ComponentHeatRoutingConfig,
    ElectricalLoadComponent,
    RoutedInternalHeatResult,
    ServedComponentPower,
    ServedPowerLedger,
    compose_routed_internal_heat_sources,
    compute_routed_internal_heat,
    validate_served_power_matches_loads,
)


ROOT = Path(__file__).resolve().parents[1]
ROUTING_PATH = ROOT / "ops_sim" / "v5" / "thermal_routing.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
COMPONENTS = tuple(ElectricalLoadComponent)
LOAD_FIELD_BY_COMPONENT = {
    ElectricalLoadComponent.BASE_BUS: "base_bus_w",
    ElectricalLoadComponent.OBC: "obc_w",
    ElectricalLoadComponent.ADCS: "adcs_w",
    ElectricalLoadComponent.PAYLOAD: "payload_w",
    ElectricalLoadComponent.COMMUNICATIONS: "communications_w",
    ElectricalLoadComponent.THERMAL_CONTROL: "thermal_control_w",
    ElectricalLoadComponent.PROPULSION: "propulsion_w",
}
DEFAULT_FRACTIONS = {
    ElectricalLoadComponent.BASE_BUS: 1.0,
    ElectricalLoadComponent.OBC: 1.0,
    ElectricalLoadComponent.ADCS: 0.8,
    ElectricalLoadComponent.PAYLOAD: 0.7,
    ElectricalLoadComponent.COMMUNICATIONS: 0.4,
    ElectricalLoadComponent.THERMAL_CONTROL: 1.0,
    ElectricalLoadComponent.PROPULSION: 0.2,
}


def _parameter(parameter_id: str, units: str, value: object) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by a focused unit test.",
        ),
    )


def _node(name: str, *, heat_capacity: object = 1_000_000.0):
    prefix = f"thermal.node.{name}"
    return ThermalNodeConfig(
        ThermalNodeId(name),
        _parameter(f"{prefix}.heat-capacity", "J/K", heat_capacity),
        _parameter(f"{prefix}.emissivity", "1", 0.0),
        _parameter(f"{prefix}.radiating-area", "m^2", 1.0),
        _parameter(f"{prefix}.operating-min-temperature", "K", 270.0),
        _parameter(f"{prefix}.operating-max-temperature", "K", 320.0),
        _parameter(f"{prefix}.survival-min-temperature", "K", 250.0),
        _parameter(f"{prefix}.survival-max-temperature", "K", 340.0),
    )


def _network(
    names: tuple[str, ...] = ("bus", "battery", "payload"),
    *,
    battery_role: str = "battery",
) -> ThermalNetworkConfig:
    return ThermalNetworkConfig(
        tuple(_node(name) for name in names),
        (),
        ThermalNodeId("bus"),
        ThermalNodeId(battery_role),
        ThermalNodeId("payload"),
    )


def _loads(**changes: object) -> PowerLoadBreakdown:
    values = {field_name: 0.0 for field_name in LOAD_FIELD_BY_COMPONENT.values()}
    values.update(changes)
    return PowerLoadBreakdown(**values)


def _served(
    loads: PowerLoadBreakdown,
    served_by_component: dict[ElectricalLoadComponent, object] | None = None,
    *,
    order: tuple[ElectricalLoadComponent, ...] = COMPONENTS,
) -> ServedPowerLedger:
    served_values = {} if served_by_component is None else served_by_component
    return ServedPowerLedger(
        tuple(
            ServedComponentPower(
                component,
                getattr(loads, LOAD_FIELD_BY_COMPONENT[component]),
                served_values.get(
                    component,
                    getattr(loads, LOAD_FIELD_BY_COMPONENT[component]),
                ),
            )
            for component in order
        )
    )


def _fraction(component: ElectricalLoadComponent, value: object):
    return _parameter(
        f"thermal.routing.{component.value}.retained-heat-fraction",
        "1",
        value,
    )


def _routing(
    *,
    fractions: dict[ElectricalLoadComponent, object] | None = None,
    nodes: dict[ElectricalLoadComponent, str] | None = None,
    order: tuple[ElectricalLoadComponent, ...] = COMPONENTS,
) -> ComponentHeatRoutingConfig:
    fraction_values = DEFAULT_FRACTIONS if fractions is None else fractions
    node_values = {} if nodes is None else nodes
    return ComponentHeatRoutingConfig(
        tuple(
            ComponentHeatRoute(
                component,
                ThermalNodeId(node_values.get(component, "bus")),
                _fraction(component, fraction_values.get(component, 0.0)),
            )
            for component in order
        )
    )


def _battery_config(
    *,
    discharge_efficiency: object = 0.8,
    max_discharge_w: object = 50.0,
) -> BatteryConfig:
    return BatteryConfig(
        SubsystemConfigurationId("battery-c2"),
        _parameter("eps.battery.nominal-energy", "Wh", 1000.0),
        _parameter("eps.battery.charge-efficiency", "1", 1.0),
        _parameter(
            "eps.battery.discharge-efficiency", "1", discharge_efficiency
        ),
        _parameter("eps.battery.max-charge-input-power", "W", 1000.0),
        _parameter(
            "eps.battery.max-discharge-output-power", "W", max_discharge_w
        ),
    )


def _eps_result(loads: PowerLoadBreakdown, *, dt_seconds: int = 3600):
    config = EPSConfig(
        SubsystemConfigurationId("eps-c2"),
        _battery_config(),
        SolarArrayConfig(
            SubsystemConfigurationId("solar-c2"),
            _parameter("eps.solar-array.nominal-generation", "W", 200.0),
        ),
    )
    return compute_eps_interval_transition(
        BatteryState(500.0),
        config,
        EPSIntervalInputs(False, 0.0, loads),
        dt_seconds=dt_seconds,
    )


def _state(names=("bus", "battery", "payload")) -> ThermalState:
    return ThermalState(
        tuple(ThermalNodeState(ThermalNodeId(name), 300.0) for name in names)
    )


def _thermal_inputs(names=("bus", "battery", "payload")):
    return ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(ThermalNodeId(name), 300.0)
            for name in names
        )
    )


def _sources(names=("bus", "battery", "payload")):
    return ThermalHeatSourceInputs(
        tuple(
            ThermalNodeHeatSourceInput(
                ThermalNodeId(name), 999.0, 0.0, 0.0, 0.0
            )
            for name in names
        )
    )


def _component_ledgers(result: RoutedInternalHeatResult):
    return {ledger.component: ledger for ledger in result.component_ledgers}


def _node_heat(result: RoutedInternalHeatResult):
    return {
        item.node_id.value: item.applied_heat_into_w
        for item in result.node_internal_heat_w
    }


def test_component_enum_is_exact_and_stable() -> None:
    assert tuple(ElectricalLoadComponent.__members__) == (
        "BASE_BUS",
        "OBC",
        "ADCS",
        "PAYLOAD",
        "COMMUNICATIONS",
        "THERMAL_CONTROL",
        "PROPULSION",
    )
    assert tuple(component.value for component in COMPONENTS) == (
        "base-bus",
        "obc",
        "adcs",
        "payload",
        "communications",
        "thermal-control",
        "propulsion",
    )


def test_public_dataclasses_have_exact_frozen_slotted_required_fields() -> None:
    expected = {
        ServedComponentPower: (
            "component",
            "requested_power_w",
            "served_power_w",
        ),
        ServedPowerLedger: ("components",),
        ComponentHeatRoute: (
            "component",
            "thermal_node_id",
            "retained_heat_fraction",
        ),
        ComponentHeatRoutingConfig: ("routes",),
        ComponentHeatLedger: (
            "component",
            "requested_power_w",
            "served_power_w",
            "retained_heat_fraction",
            "thermal_node_id",
            "retained_heat_w",
        ),
        RoutedInternalHeatResult: (
            "component_ledgers",
            "node_internal_heat_w",
        ),
    }
    for class_type, field_names in expected.items():
        assert tuple(field.name for field in fields(class_type)) == field_names
        assert class_type.__dataclass_params__.frozen
        for field in fields(class_type):
            assert field.default is MISSING
            assert field.default_factory is MISSING

    item = ServedComponentPower(ElectricalLoadComponent.OBC, 2.0, 1.0)
    assert not hasattr(item, "__dict__")
    assert isinstance(hash(item), int)
    with pytest.raises(FrozenInstanceError):
        item.served_power_w = 2.0


@pytest.mark.parametrize("field_name", ("requested_power_w", "served_power_w"))
@pytest.mark.parametrize(
    ("value", "error_type"),
    (
        (True, TypeError),
        ("1", TypeError),
        (-1.0, ValueError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (float("-inf"), ValueError),
    ),
)
def test_served_component_power_rejects_invalid_powers(
    field_name, value, error_type
) -> None:
    values = {"requested_power_w": 2.0, "served_power_w": 1.0}
    values[field_name] = value
    with pytest.raises(error_type):
        ServedComponentPower(ElectricalLoadComponent.OBC, **values)


def test_served_power_cannot_exceed_requested_power() -> None:
    with pytest.raises(ValueError, match="less than or equal"):
        ServedComponentPower(ElectricalLoadComponent.OBC, 1.0, 1.01)


def test_served_ledger_requires_exact_tuple_complete_unique_revalidated() -> None:
    loads = _loads()
    valid = _served(loads)
    with pytest.raises(TypeError, match="tuple"):
        ServedPowerLedger(list(valid.components))
    with pytest.raises(ValueError, match="every"):
        ServedPowerLedger(valid.components[:-1])
    with pytest.raises(ValueError, match="duplicate"):
        ServedPowerLedger((*valid.components[:-1], valid.components[0]))
    damaged = valid.components[0]
    object.__setattr__(damaged, "served_power_w", float("nan"))
    with pytest.raises(ValueError, match="finite"):
        ServedPowerLedger(valid.components)


def test_requested_power_must_match_power_load_breakdown_exactly() -> None:
    loads = _loads(base_bus_w=10.0, payload_w=20.0)
    valid = _served(loads)
    validate_served_power_matches_loads(loads, valid)
    changed = replace(valid.components[0], requested_power_w=11.0)
    with pytest.raises(ValueError, match="must match loads"):
        validate_served_power_matches_loads(
            loads, ServedPowerLedger((changed, *valid.components[1:]))
        )


def test_routing_parameter_identity_units_range_and_types_are_strict() -> None:
    route = ComponentHeatRoute(
        ElectricalLoadComponent.OBC,
        ThermalNodeId("bus"),
        _fraction(ElectricalLoadComponent.OBC, 0.5),
    )
    with pytest.raises(ValueError, match="ParameterId"):
        replace(
            route,
            retained_heat_fraction=_parameter("wrong.parameter", "1", 0.5),
        )
    with pytest.raises(ValueError, match="units"):
        replace(
            route,
            retained_heat_fraction=_parameter(
                "thermal.routing.obc.retained-heat-fraction", "W", 0.5
            ),
        )
    for value in (-0.01, 1.01, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            replace(route, retained_heat_fraction=_fraction(route.component, value))
    with pytest.raises(TypeError, match="ScalarParameter"):
        replace(route, retained_heat_fraction=0.5)


def test_routing_config_requires_complete_unique_routes_but_reuses_nodes() -> None:
    valid = _routing()
    assert len({route.thermal_node_id for route in valid.routes}) == 1
    with pytest.raises(TypeError, match="tuple"):
        ComponentHeatRoutingConfig(list(valid.routes))
    with pytest.raises(ValueError, match="every"):
        ComponentHeatRoutingConfig(valid.routes[:-1])
    with pytest.raises(ValueError, match="duplicate"):
        ComponentHeatRoutingConfig((*valid.routes[:-1], valid.routes[0]))
    damaged = valid.routes[0]
    object.__setattr__(damaged, "retained_heat_fraction", 1.0)
    with pytest.raises(TypeError, match="ScalarParameter"):
        ComponentHeatRoutingConfig(valid.routes)


def test_two_components_same_node_match_independent_hand_calculation() -> None:
    loads = _loads(base_bus_w=100.0, communications_w=50.0)
    fractions = {component: 0.0 for component in COMPONENTS}
    fractions[ElectricalLoadComponent.BASE_BUS] = 0.8
    fractions[ElectricalLoadComponent.COMMUNICATIONS] = 0.4
    result = compute_routed_internal_heat(
        loads,
        _served(loads),
        _routing(fractions=fractions),
        _network(),
    )
    ledgers = _component_ledgers(result)
    assert ledgers[ElectricalLoadComponent.BASE_BUS].retained_heat_w == 80.0
    assert (
        ledgers[ElectricalLoadComponent.COMMUNICATIONS].retained_heat_w
        == 20.0
    )
    assert _node_heat(result) == {
        "bus": 100.0,
        "battery": 0.0,
        "payload": 0.0,
    }


def test_zero_unity_unserved_and_partial_service_use_served_power_only() -> None:
    loads = _loads(
        base_bus_w=20.0,
        obc_w=30.0,
        payload_w=100.0,
        communications_w=100.0,
    )
    served = _served(
        loads,
        {
            ElectricalLoadComponent.PAYLOAD: 0.0,
            ElectricalLoadComponent.COMMUNICATIONS: 40.0,
        },
    )
    fractions = {component: 0.0 for component in COMPONENTS}
    fractions.update(
        {
            ElectricalLoadComponent.BASE_BUS: 0.0,
            ElectricalLoadComponent.OBC: 1.0,
            ElectricalLoadComponent.PAYLOAD: 0.9,
            ElectricalLoadComponent.COMMUNICATIONS: 0.5,
        }
    )
    ledgers = _component_ledgers(
        compute_routed_internal_heat(
            loads, served, _routing(fractions=fractions), _network()
        )
    )
    assert ledgers[ElectricalLoadComponent.BASE_BUS].retained_heat_w == 0.0
    assert ledgers[ElectricalLoadComponent.OBC].retained_heat_w == 30.0
    assert ledgers[ElectricalLoadComponent.PAYLOAD].retained_heat_w == 0.0
    assert ledgers[ElectricalLoadComponent.COMMUNICATIONS].retained_heat_w == 20.0


def test_eps_shortfall_accepts_explicit_matching_service_and_rejects_changed_sum() -> None:
    loads = _loads(base_bus_w=70.0, payload_w=30.0)
    eps_result = _eps_result(loads)
    served = _served(
        loads,
        {
            ElectricalLoadComponent.BASE_BUS: 40.0,
            ElectricalLoadComponent.PAYLOAD: 10.0,
        },
    )
    assert loads.total_load_w == 100.0
    assert eps_result.battery.served_load_w == 50.0
    compute_routed_internal_heat(
        loads, served, _routing(), _network(), eps_result=eps_result
    )

    changed = tuple(
        replace(item, served_power_w=11.0)
        if item.component is ElectricalLoadComponent.PAYLOAD
        else item
        for item in served.components
    )
    with pytest.raises(ValueError, match="must equal EPS served load"):
        compute_routed_internal_heat(
            loads,
            ServedPowerLedger(changed),
            _routing(),
            _network(),
            eps_result=eps_result,
        )


def test_eps_requested_component_composition_must_match_routing_loads() -> None:
    routing_loads = _loads(base_bus_w=70.0, payload_w=30.0)
    different_eps_loads = _loads(obc_w=100.0)
    eps_result = _eps_result(different_eps_loads)
    served = _served(
        routing_loads,
        {
            ElectricalLoadComponent.BASE_BUS: 40.0,
            ElectricalLoadComponent.PAYLOAD: 10.0,
        },
    )
    assert routing_loads.total_load_w == different_eps_loads.total_load_w
    assert eps_result.battery.served_load_w == 50.0
    assert sum(item.served_power_w for item in served.components) == 50.0

    with pytest.raises(ValueError, match="EPS requested load breakdown"):
        compute_routed_internal_heat(
            routing_loads,
            served,
            _routing(),
            _network(),
            eps_result=eps_result,
        )


def test_matching_eps_requested_component_composition_is_accepted() -> None:
    loads = _loads(base_bus_w=70.0, payload_w=30.0)
    served = _served(
        loads,
        {
            ElectricalLoadComponent.BASE_BUS: 40.0,
            ElectricalLoadComponent.PAYLOAD: 10.0,
        },
    )

    result = compute_routed_internal_heat(
        loads,
        served,
        _routing(),
        _network(),
        eps_result=_eps_result(loads),
    )

    assert sum(
        item.served_power_w for item in result.component_ledgers
    ) == 50.0


def test_tuple_order_is_nonsemantic_and_outputs_are_configuration_ordered() -> None:
    loads = _loads(base_bus_w=5.0, payload_w=7.0)
    reverse = tuple(reversed(COMPONENTS))
    canonical = compute_routed_internal_heat(
        loads, _served(loads), _routing(), _network()
    )
    reordered = compute_routed_internal_heat(
        loads,
        _served(loads, order=reverse),
        _routing(order=reverse),
        _network(),
    )
    assert canonical == reordered
    assert tuple(item.component for item in canonical.component_ledgers) == COMPONENTS
    assert tuple(item.node_id.value for item in canonical.node_internal_heat_w) == (
        "bus",
        "battery",
        "payload",
    )


def test_unknown_route_node_is_rejected() -> None:
    loads = _loads(base_bus_w=1.0)
    with pytest.raises(ValueError, match="must exist"):
        compute_routed_internal_heat(
            loads,
            _served(loads),
            _routing(nodes={ElectricalLoadComponent.BASE_BUS: "unknown"}),
            _network(),
        )


def test_source_composition_replaces_internal_and_preserves_external_heat() -> None:
    loads = _loads(base_bus_w=20.0)
    routed = compute_routed_internal_heat(
        loads,
        _served(loads),
        _routing(),
        _network(),
    )
    sources = ThermalHeatSourceInputs(
        (
            ThermalNodeHeatSourceInput(
                ThermalNodeId("payload"), 999.0, 3.0, 4.0, 5.0
            ),
            ThermalNodeHeatSourceInput(
                ThermalNodeId("bus"), 999.0, 6.0, 7.0, 8.0
            ),
            ThermalNodeHeatSourceInput(
                ThermalNodeId("battery"), 999.0, 9.0, 10.0, 11.0
            ),
        )
    )
    composed = compose_routed_internal_heat_sources(routed, sources)
    by_name = {source.node_id.value: source for source in composed.node_sources}
    assert tuple(source.node_id.value for source in composed.node_sources) == (
        "bus",
        "battery",
        "payload",
    )
    assert by_name["bus"].internal_dissipation_w == 20.0
    assert by_name["battery"].internal_dissipation_w == 0.0
    assert (
        by_name["payload"].absorbed_solar_w,
        by_name["payload"].absorbed_albedo_w,
        by_name["payload"].absorbed_earth_ir_w,
    ) == (3.0, 4.0, 5.0)


def test_c1_end_to_end_keeps_component_external_and_battery_loss_once() -> None:
    loads = _loads(base_bus_w=70.0, payload_w=30.0)
    eps_result = _eps_result(loads)
    served = _served(
        loads,
        {
            ElectricalLoadComponent.BASE_BUS: 40.0,
            ElectricalLoadComponent.PAYLOAD: 10.0,
        },
    )
    fractions = {component: 0.0 for component in COMPONENTS}
    fractions[ElectricalLoadComponent.BASE_BUS] = 1.0
    fractions[ElectricalLoadComponent.PAYLOAD] = 0.5
    routes = _routing(
        fractions=fractions,
        nodes={ElectricalLoadComponent.PAYLOAD: "battery"},
    )
    network = _network()
    routed = compute_routed_internal_heat(
        loads, served, routes, network, eps_result=eps_result
    )
    external = ThermalHeatSourceInputs(
        (
            ThermalNodeHeatSourceInput(
                ThermalNodeId("bus"), 0.0, 0.0, 0.0, 0.0
            ),
            ThermalNodeHeatSourceInput(
                ThermalNodeId("battery"), 0.0, 3.0, 2.0, 1.0
            ),
            ThermalNodeHeatSourceInput(
                ThermalNodeId("payload"), 0.0, 0.0, 0.0, 0.0
            ),
        )
    )
    sources = compose_routed_internal_heat_sources(routed, external)
    result = compute_eps_thermal_interval_transition(
        _state(),
        network,
        _thermal_inputs(),
        sources,
        eps_result,
        dt_seconds=3600,
    )
    heat_ledgers = {
        item.node_id.value: item for item in result.node_heat_ledgers
    }
    transitions = {
        item.node_id.value: item for item in result.thermal_result.node_transitions
    }
    assert eps_result.battery.conversion_loss_wh == pytest.approx(12.5)
    assert heat_ledgers["bus"].internal_dissipation_w == 40.0
    assert heat_ledgers["battery"].internal_dissipation_w == 5.0
    assert heat_ledgers["battery"].absorbed_solar_w == 3.0
    assert heat_ledgers["battery"].absorbed_albedo_w == 2.0
    assert heat_ledgers["battery"].absorbed_earth_ir_w == 1.0
    assert heat_ledgers["battery"].battery_conversion_heat_w == pytest.approx(
        12.5
    )
    assert transitions["bus"].applied_heat_into_w == 40.0
    assert transitions["battery"].applied_heat_into_w == pytest.approx(23.5)


def test_four_node_generic_routing_and_c1_battery_role_are_independent() -> None:
    names = ("bus", "storage", "payload", "radiator")
    network = _network(names, battery_role="storage")
    loads = _loads(communications_w=50.0)
    eps_result = _eps_result(loads)
    fractions = {component: 0.0 for component in COMPONENTS}
    fractions[ElectricalLoadComponent.COMMUNICATIONS] = 0.4
    routed = compute_routed_internal_heat(
        loads,
        _served(loads),
        _routing(
            fractions=fractions,
            nodes={ElectricalLoadComponent.COMMUNICATIONS: "radiator"},
        ),
        network,
        eps_result=eps_result,
    )
    assert _node_heat(routed) == {
        "bus": 0.0,
        "storage": 0.0,
        "payload": 0.0,
        "radiator": 20.0,
    }
    result = compute_eps_thermal_interval_transition(
        _state(names),
        network,
        _thermal_inputs(names),
        compose_routed_internal_heat_sources(routed, _sources(names)),
        eps_result,
        dt_seconds=3600,
    )
    ledgers = {item.node_id.value: item for item in result.node_heat_ledgers}
    assert ledgers["radiator"].internal_dissipation_w == 20.0
    assert ledgers["radiator"].battery_conversion_heat_w == 0.0
    assert ledgers["storage"].battery_conversion_heat_w == pytest.approx(12.5)


def test_numpy_reals_execute_without_production_numpy_dependency() -> None:
    loads = _loads(base_bus_w=np.int64(10), obc_w=np.float64(5.0))
    served = _served(
        loads,
        {
            ElectricalLoadComponent.BASE_BUS: np.float64(8.0),
            ElectricalLoadComponent.OBC: np.int64(4),
        },
    )
    fractions = {component: np.float64(0.0) for component in COMPONENTS}
    fractions[ElectricalLoadComponent.BASE_BUS] = np.float64(0.5)
    fractions[ElectricalLoadComponent.OBC] = np.float64(0.25)
    result = compute_routed_internal_heat(
        loads, served, _routing(fractions=fractions), _network()
    )
    assert _node_heat(result)["bus"] == 5.0
    assert "numpy" not in ROUTING_PATH.read_text(encoding="utf-8")


def test_nonfinite_aggregate_fails_and_significance_loss_is_allowed() -> None:
    loads = _loads()
    object.__setattr__(loads, "base_bus_w", 1.0e308)
    object.__setattr__(loads, "obc_w", 1.0e308)
    with pytest.raises(ValueError, match="finite"):
        compute_routed_internal_heat(
            loads, _served(loads), _routing(), _network()
        )

    loads = _loads(base_bus_w=1.0e16, obc_w=1.0)
    result = compute_routed_internal_heat(
        loads, _served(loads), _routing(), _network()
    )
    assert _node_heat(result)["bus"] == 1.0e16
    assert _component_ledgers(result)[ElectricalLoadComponent.OBC].retained_heat_w == 1.0


def test_nonzero_retained_heat_product_underflow_fails_intentionally() -> None:
    loads = _loads(base_bus_w=1.0e-300)
    fractions = {component: 0.0 for component in COMPONENTS}
    fractions[ElectricalLoadComponent.BASE_BUS] = 1.0e-100
    assert loads.base_bus_w != 0.0
    assert fractions[ElectricalLoadComponent.BASE_BUS] != 0.0
    assert loads.base_bus_w * fractions[ElectricalLoadComponent.BASE_BUS] == 0.0

    with pytest.raises(ValueError, match="nonzero product"):
        compute_routed_internal_heat(
            loads,
            _served(loads),
            _routing(fractions=fractions),
            _network(),
        )


def test_result_validates_component_identity_node_sums_and_nonnegative_heat() -> None:
    valid = compute_routed_internal_heat(
        _loads(), _served(_loads()), _routing(), _network()
    )
    with pytest.raises(ValueError, match="duplicate"):
        replace(
            valid,
            component_ledgers=(
                valid.component_ledgers[0],
                *valid.component_ledgers[:-1],
            ),
        )
    with pytest.raises(ValueError, match="must equal"):
        replace(
            valid,
            node_internal_heat_w=(
                ThermalNodeAppliedHeatInput(ThermalNodeId("bus"), 1.0),
                *valid.node_internal_heat_w[1:],
            ),
        )
    with pytest.raises(ValueError, match="greater than or equal"):
        replace(
            valid,
            node_internal_heat_w=(
                ThermalNodeAppliedHeatInput(ThermalNodeId("bus"), -1.0),
                *valid.node_internal_heat_w[1:],
            ),
        )


def test_composition_requires_exact_matching_node_sets() -> None:
    routed = compute_routed_internal_heat(
        _loads(), _served(_loads()), _routing(), _network()
    )
    with pytest.raises(ValueError, match="exactly match"):
        compose_routed_internal_heat_sources(
            routed,
            ThermalHeatSourceInputs(
                (
                    ThermalNodeHeatSourceInput(
                        ThermalNodeId("bus"), 0.0, 0.0, 0.0, 0.0
                    ),
                    ThermalNodeHeatSourceInput(
                        ThermalNodeId("battery"), 0.0, 0.0, 0.0, 0.0
                    ),
                )
            ),
        )


def test_compute_mutates_no_inputs() -> None:
    loads = _loads(base_bus_w=10.0)
    served = _served(loads)
    routing = _routing()
    network = _network()
    eps_result = _eps_result(loads)
    originals = tuple(
        deepcopy(item) for item in (loads, served, routing, network, eps_result)
    )
    compute_routed_internal_heat(
        loads, served, routing, network, eps_result=eps_result
    )
    assert (loads, served, routing, network, eps_result) == originals


@pytest.mark.parametrize(
    ("argument", "value", "error_type"),
    (
        ("loads", object(), TypeError),
        ("served_power", object(), TypeError),
        ("routing_config", object(), TypeError),
        ("thermal_config", object(), TypeError),
        ("eps_result", object(), TypeError),
    ),
)
def test_compute_requires_exact_public_types(argument, value, error_type) -> None:
    loads = _loads()
    arguments = {
        "loads": loads,
        "served_power": _served(loads),
        "routing_config": _routing(),
        "thermal_config": _network(),
        "eps_result": None,
    }
    arguments[argument] = value
    with pytest.raises(error_type):
        compute_routed_internal_heat(**arguments)


def test_no_allocation_inference_battery_component_or_detailed_physics() -> None:
    source = ROUTING_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ROUTING_PATH))
    import_roots = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    prohibited = {
        "unmet_load_w",
        "OperationalMode",
        "FDIRState",
        "priority",
        "isclose",
        "round",
        "clamp",
        "degradation",
        "temperature_k",
    }
    assert import_roots.isdisjoint({"numpy", "pandas", "engine", "context"})
    assert identifiers.isdisjoint(prohibited)
    assert "BATTERY_CONVERSION" not in ElectricalLoadComponent.__members__
    assert set(ElectricalLoadComponent) == set(LOAD_FIELD_BY_COMPONENT)


def test_c2_decisions_source_contract_and_exports_are_exact() -> None:
    decision_log = DECISION_LOG_PATH.read_text(encoding="utf-8")
    source_register = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s003 = source_register.partition("### S003 ")[2].partition("### S004 ")[0]
    s004 = source_register.partition("### S004 ")[2].partition("### S005 ")[0]
    for decision_number in range(103, 108):
        assert decision_log.count(f"## D{decision_number:03d} ") == 1
    assert decision_log.index("## D102 ") < decision_log.index("## D103 ")
    assert "P_heat,k = P_served,k * f_heat,k" in s004
    assert "0 <= f_heat,k <= 1" in s004
    assert "explicitly" in s003
    assert "aggregate `unmet_load_w`" in s003.lower()
    assert "Battery conversion heat remains separate" in s004
    assert "freezes no real spacecraft fraction" in s004

    from ops_sim.v5 import thermal_routing

    assert thermal_routing.__all__ == [
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
