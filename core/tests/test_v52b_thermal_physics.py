"""Scientific and numerical validation for V5.2B pure thermal physics."""

import ast
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from math import isfinite
from pathlib import Path

import numpy as np
import pytest

from ops_sim.v5.ids import (
    ParameterId,
    ThermalLinkId,
    ThermalNodeId,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import ThermalNodeState, ThermalState
from ops_sim.v5.thermal import (
    ThermalIntervalInputs,
    ThermalIntervalResult,
    ThermalLinkHeatFlow,
    ThermalNodeBoundaryInput,
    ThermalNodeTransition,
    compute_thermal_interval_transition,
)
from ops_sim.v5.thermal_config import (
    ThermalLinkConfig,
    ThermalNetworkConfig,
    ThermalNodeConfig,
)


ROOT = Path(__file__).resolve().parents[1]
THERMAL_PATH = ROOT / "ops_sim" / "v5" / "thermal.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
SIGMA = 5.670374419e-8
BASELINE_NAMES = ("bus", "battery", "payload")


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


def _node(
    name: str,
    *,
    heat_capacity: object = 1000.0,
    emissivity: object = 0.0,
    area: object = 1.0,
) -> ThermalNodeConfig:
    prefix = f"thermal.node.{name}"
    return ThermalNodeConfig(
        ThermalNodeId(name),
        _parameter(f"{prefix}.heat-capacity", "J/K", heat_capacity),
        _parameter(f"{prefix}.emissivity", "1", emissivity),
        _parameter(f"{prefix}.radiating-area", "m^2", area),
        _parameter(f"{prefix}.operating-min-temperature", "K", 270.0),
        _parameter(f"{prefix}.operating-max-temperature", "K", 320.0),
        _parameter(f"{prefix}.survival-min-temperature", "K", 250.0),
        _parameter(f"{prefix}.survival-max-temperature", "K", 340.0),
    )


def _link(
    name: str,
    node_a: str,
    node_b: str,
    conductance: object,
) -> ThermalLinkConfig:
    return ThermalLinkConfig(
        ThermalLinkId(name),
        ThermalNodeId(node_a),
        ThermalNodeId(node_b),
        _parameter(
            f"thermal.link.{name}.conductance",
            "W/K",
            conductance,
        ),
    )


def _network(
    *,
    nodes: tuple[ThermalNodeConfig, ...] | None = None,
    links: tuple[ThermalLinkConfig, ...] = (),
) -> ThermalNetworkConfig:
    configured_nodes = (
        tuple(_node(name) for name in BASELINE_NAMES)
        if nodes is None
        else nodes
    )
    return ThermalNetworkConfig(
        configured_nodes,
        links,
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("payload"),
    )


def _state(
    temperatures: dict[str, object],
    *,
    order: tuple[str, ...] | None = None,
) -> ThermalState:
    names = tuple(temperatures) if order is None else order
    return ThermalState(
        tuple(
            ThermalNodeState(ThermalNodeId(name), temperatures[name])
            for name in names
        )
    )


def _inputs(
    sinks: dict[str, object],
    *,
    order: tuple[str, ...] | None = None,
) -> ThermalIntervalInputs:
    names = tuple(sinks) if order is None else order
    return ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(ThermalNodeId(name), sinks[name])
            for name in names
        )
    )


def _transition_by_name(
    result: ThermalIntervalResult,
) -> dict[str, ThermalNodeTransition]:
    return {
        transition.node_id.value: transition
        for transition in result.node_transitions
    }


def _baseline_state() -> ThermalState:
    return _state({"bus": 310.0, "battery": 290.0, "payload": 300.0})


def _baseline_inputs() -> ThermalIntervalInputs:
    return _inputs({"bus": 300.0, "battery": 300.0, "payload": 300.0})


def test_public_dataclasses_have_exact_required_frozen_slotted_fields() -> None:
    expected_fields = {
        ThermalNodeBoundaryInput: (
            "node_id",
            "radiative_sink_temperature_k",
        ),
        ThermalIntervalInputs: ("node_boundaries",),
        ThermalLinkHeatFlow: (
            "link_id",
            "node_a_id",
            "node_b_id",
            "heat_flow_a_to_b_w",
        ),
        ThermalNodeTransition: (
            "node_id",
            "start_temperature_k",
            "end_temperature_k",
            "conductive_heat_into_w",
            "radiative_heat_into_w",
            "applied_heat_into_w",
            "net_heat_into_w",
            "thermal_energy_change_j",
        ),
        ThermalIntervalResult: (
            "node_transitions",
            "link_heat_flows",
            "dt_seconds",
        ),
    }

    for class_type, names in expected_fields.items():
        assert tuple(field.name for field in fields(class_type)) == names
        assert class_type.__dataclass_params__.frozen
        assert not hasattr(class_type, "__dict__") or "__slots__" in vars(
            class_type
        )
        for field in fields(class_type):
            assert field.default is MISSING
            assert field.default_factory is MISSING

    boundary = ThermalNodeBoundaryInput(ThermalNodeId("bus"), 300.0)
    assert not hasattr(boundary, "__dict__")
    assert isinstance(hash(boundary), int)
    with pytest.raises(FrozenInstanceError):
        boundary.radiative_sink_temperature_k = 301.0


@pytest.mark.parametrize(
    ("temperature", "error_type"),
    (
        (0.0, ValueError),
        (-1.0, ValueError),
        (True, TypeError),
        ("300", TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (float("-inf"), ValueError),
    ),
)
def test_boundary_rejects_invalid_temperature(temperature, error_type) -> None:
    with pytest.raises(error_type):
        ThermalNodeBoundaryInput(ThermalNodeId("bus"), temperature)


def test_boundary_and_interval_input_identity_contracts_are_strict() -> None:
    boundary = ThermalNodeBoundaryInput(ThermalNodeId("bus"), 300.0)
    with pytest.raises(TypeError, match="ThermalNodeId"):
        ThermalNodeBoundaryInput(ParameterId("bus"), 300.0)
    with pytest.raises(TypeError, match="tuple"):
        ThermalIntervalInputs([boundary])
    with pytest.raises(ValueError, match="empty"):
        ThermalIntervalInputs(())
    with pytest.raises(TypeError, match="ThermalNodeBoundaryInput"):
        ThermalIntervalInputs((object(),))
    with pytest.raises(ValueError, match="unique"):
        ThermalIntervalInputs((boundary, boundary))

    object.__setattr__(boundary, "radiative_sink_temperature_k", float("nan"))
    with pytest.raises(ValueError, match="finite"):
        ThermalIntervalInputs((boundary,))


def test_result_types_accept_signed_flows_and_reject_inconsistent_net() -> None:
    flow = ThermalLinkHeatFlow(
        ThermalLinkId("bus-battery"),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        -2.5,
    )
    transition = ThermalNodeTransition(
        ThermalNodeId("bus"),
        300.0,
        299.9,
        -3.0,
        1.0,
        0.0,
        -2.0,
        -20.0,
    )
    result = ThermalIntervalResult((transition,), (flow,), 10)

    assert result.node_transitions[0].net_heat_into_w == -2.0
    assert result.link_heat_flows[0].heat_flow_a_to_b_w == -2.5
    with pytest.raises(ValueError, match="must equal"):
        replace(transition, net_heat_into_w=-1.0)
    with pytest.raises(ValueError, match="distinct"):
        replace(flow, node_b_id=ThermalNodeId("bus"))


def test_interval_result_validates_collections_identity_and_dt() -> None:
    transition = ThermalNodeTransition(
        ThermalNodeId("bus"),
        300.0,
        300.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )
    flow = ThermalLinkHeatFlow(
        ThermalLinkId("bus-battery"),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        0.0,
    )
    with pytest.raises(TypeError, match="node_transitions"):
        ThermalIntervalResult([transition], (), 1)
    with pytest.raises(TypeError, match="link_heat_flows"):
        ThermalIntervalResult((transition,), [flow], 1)
    with pytest.raises(ValueError, match="node IDs"):
        ThermalIntervalResult((transition, transition), (), 1)
    with pytest.raises(ValueError, match="link IDs"):
        ThermalIntervalResult((transition,), (flow, flow), 1)
    with pytest.raises(TypeError, match="dt_seconds"):
        ThermalIntervalResult((transition,), (), True)
    with pytest.raises(ValueError, match="greater than zero"):
        ThermalIntervalResult((transition,), (), 0)


@pytest.mark.parametrize(
    ("argument", "replacement", "error_type"),
    (
        ("state", object(), TypeError),
        ("config", object(), TypeError),
        ("inputs", object(), TypeError),
        ("dt_seconds", True, TypeError),
        ("dt_seconds", 1.0, TypeError),
        ("dt_seconds", 0, ValueError),
        ("dt_seconds", -1, ValueError),
    ),
)
def test_compute_requires_exact_public_types_and_positive_int_dt(
    argument,
    replacement,
    error_type,
) -> None:
    arguments = {
        "state": _baseline_state(),
        "config": _network(),
        "inputs": _baseline_inputs(),
        "dt_seconds": 10,
    }
    arguments[argument] = replacement

    with pytest.raises(error_type):
        compute_thermal_interval_transition(**arguments)


@pytest.mark.parametrize(
    ("state_names", "boundary_names"),
    (
        (("bus", "battery"), BASELINE_NAMES),
        ((*BASELINE_NAMES, "radiator"), BASELINE_NAMES),
        (("bus", "battery", "renamed"), BASELINE_NAMES),
        (BASELINE_NAMES, ("bus", "battery")),
        (BASELINE_NAMES, (*BASELINE_NAMES, "radiator")),
        (BASELINE_NAMES, ("bus", "battery", "renamed")),
    ),
    ids=(
        "missing-state",
        "extra-state",
        "renamed-state",
        "missing-boundary",
        "extra-boundary",
        "renamed-boundary",
    ),
)
def test_compute_requires_exact_config_state_boundary_id_sets(
    state_names,
    boundary_names,
) -> None:
    temperatures = {name: 300.0 for name in state_names}
    sinks = {name: 300.0 for name in boundary_names}

    with pytest.raises(ValueError, match="node IDs"):
        compute_thermal_interval_transition(
            _state(temperatures),
            _network(),
            _inputs(sinks),
            dt_seconds=1,
        )


def test_conduction_hand_calculation_matches_signed_ledger() -> None:
    config = _network(
        links=(_link("bus-battery", "bus", "battery", 2.0),)
    )
    result = compute_thermal_interval_transition(
        _baseline_state(),
        config,
        _baseline_inputs(),
        dt_seconds=10,
    )
    nodes = _transition_by_name(result)

    assert len(result.link_heat_flows) == 1
    assert result.link_heat_flows[0].heat_flow_a_to_b_w == 40.0
    assert nodes["bus"].conductive_heat_into_w == -40.0
    assert nodes["battery"].conductive_heat_into_w == 40.0
    assert nodes["bus"].thermal_energy_change_j == -400.0
    assert nodes["battery"].thermal_energy_change_j == 400.0
    assert nodes["bus"].end_temperature_k == pytest.approx(309.6)
    assert nodes["battery"].end_temperature_k == pytest.approx(290.4)
    assert nodes["payload"].end_temperature_k == 300.0
    assert all(
        transition.applied_heat_into_w == 0.0
        for transition in result.node_transitions
    )


def test_tiny_finite_radiation_may_round_out_of_net_heat() -> None:
    emissivity = 1.0e-17
    config = _network(
        nodes=(
            _node("bus", emissivity=emissivity),
            _node("battery"),
            _node("payload"),
        ),
        links=(_link("bus-battery", "bus", "battery", 2.0),),
    )
    result = compute_thermal_interval_transition(
        _baseline_state(),
        config,
        _baseline_inputs(),
        dt_seconds=10,
    )
    bus = _transition_by_name(result)["bus"]
    expected_radiation_w = (
        emissivity * SIGMA * (300.0**4 - 310.0**4)
    )

    assert isfinite(bus.radiative_heat_into_w)
    assert bus.radiative_heat_into_w == pytest.approx(expected_radiation_w)
    assert bus.radiative_heat_into_w != 0.0
    assert isfinite(bus.conductive_heat_into_w)
    assert bus.conductive_heat_into_w == -40.0
    assert bus.net_heat_into_w == bus.conductive_heat_into_w
    assert isfinite(bus.end_temperature_k)
    assert bus.end_temperature_k > 0.0


def test_finite_fourth_power_difference_may_round_to_dominant_operand() -> None:
    emissivity = 1.0e-18
    sink_temperature_k = 10_000.0
    start_temperature_k = 1.0
    sink_fourth_power = sink_temperature_k**4
    node_fourth_power = start_temperature_k**4
    rounded_difference = sink_fourth_power - node_fourth_power
    assert rounded_difference == sink_fourth_power

    config = _network(
        nodes=(
            _node("bus", emissivity=emissivity),
            _node("battery"),
            _node("payload"),
        )
    )
    result = compute_thermal_interval_transition(
        _state(
            {
                "bus": start_temperature_k,
                "battery": 300.0,
                "payload": 300.0,
            }
        ),
        config,
        _inputs(
            {
                "bus": sink_temperature_k,
                "battery": 300.0,
                "payload": 300.0,
            }
        ),
        dt_seconds=1,
    )
    bus = _transition_by_name(result)["bus"]
    expected_radiation_w = emissivity * SIGMA * rounded_difference

    assert isfinite(bus.radiative_heat_into_w)
    assert bus.radiative_heat_into_w == pytest.approx(expected_radiation_w)
    assert bus.end_temperature_k > start_temperature_k
    assert isfinite(bus.end_temperature_k)


def test_multiple_link_conduction_is_conservative() -> None:
    config = _network(
        links=(
            _link("bus-battery", "bus", "battery", 2.0),
            _link("battery-payload", "battery", "payload", 3.0),
            _link("bus-payload", "bus", "payload", 1.0),
        )
    )
    state = _state({"bus": 310.0, "battery": 300.0, "payload": 290.0})
    result = compute_thermal_interval_transition(
        state,
        config,
        _baseline_inputs(),
        dt_seconds=37,
    )

    assert sum(
        item.conductive_heat_into_w for item in result.node_transitions
    ) == pytest.approx(0.0, abs=1.0e-12)
    assert sum(
        item.thermal_energy_change_j for item in result.node_transitions
    ) == pytest.approx(0.0, abs=1.0e-10)


def test_link_sign_reverses_without_reversing_configured_endpoints() -> None:
    config = _network(
        links=(_link("bus-battery", "bus", "battery", 2.0),)
    )
    hot_a = compute_thermal_interval_transition(
        _state({"bus": 310.0, "battery": 290.0, "payload": 300.0}),
        config,
        _baseline_inputs(),
        dt_seconds=1,
    )
    hot_b = compute_thermal_interval_transition(
        _state({"bus": 290.0, "battery": 310.0, "payload": 300.0}),
        config,
        _baseline_inputs(),
        dt_seconds=1,
    )

    assert hot_a.link_heat_flows[0].node_a_id == ThermalNodeId("bus")
    assert hot_a.link_heat_flows[0].heat_flow_a_to_b_w == 40.0
    assert hot_b.link_heat_flows[0].heat_flow_a_to_b_w == -40.0


def test_equal_temperature_conduction_is_exactly_zero() -> None:
    config = _network(
        links=(_link("bus-battery", "bus", "battery", 2.0),)
    )
    result = compute_thermal_interval_transition(
        _state({"bus": 300.0, "battery": 300.0, "payload": 300.0}),
        config,
        _baseline_inputs(),
        dt_seconds=10,
    )

    assert result.link_heat_flows[0].heat_flow_a_to_b_w == 0.0
    assert all(
        transition.conductive_heat_into_w == 0.0
        for transition in result.node_transitions
    )


def test_radiation_cooling_matches_independent_hand_calculation() -> None:
    config = _network(
        nodes=(
            _node("bus", emissivity=0.8, area=2.0),
            _node("battery"),
            _node("payload"),
        )
    )
    state = _state({"bus": 310.0, "battery": 300.0, "payload": 300.0})
    result = compute_thermal_interval_transition(
        state,
        config,
        _inputs({"bus": 290.0, "battery": 300.0, "payload": 300.0}),
        dt_seconds=10,
    )
    bus = _transition_by_name(result)["bus"]
    expected_q = 0.8 * SIGMA * 2.0 * (290.0**4 - 310.0**4)
    expected_end = 310.0 + expected_q * 10.0 / 1000.0

    assert bus.conductive_heat_into_w == 0.0
    assert bus.radiative_heat_into_w == pytest.approx(expected_q)
    assert bus.radiative_heat_into_w < 0
    assert bus.end_temperature_k == pytest.approx(expected_end)
    assert bus.end_temperature_k < bus.start_temperature_k


def test_radiative_heating_uses_positive_heat_into_convention() -> None:
    config = _network(
        nodes=(
            _node("bus", emissivity=0.7, area=1.5),
            _node("battery"),
            _node("payload"),
        )
    )
    result = compute_thermal_interval_transition(
        _state({"bus": 280.0, "battery": 300.0, "payload": 300.0}),
        config,
        _inputs({"bus": 320.0, "battery": 300.0, "payload": 300.0}),
        dt_seconds=10,
    )
    bus = _transition_by_name(result)["bus"]

    assert bus.radiative_heat_into_w > 0
    assert bus.end_temperature_k > bus.start_temperature_k


@pytest.mark.parametrize("mode", ("zero-emissivity", "equilibrium"))
def test_zero_emissivity_and_radiative_equilibrium_are_exactly_static(
    mode,
) -> None:
    emissivity = 0.0 if mode == "zero-emissivity" else 0.8
    sink = 100.0 if mode == "zero-emissivity" else 300.0
    config = _network(
        nodes=(
            _node("bus", emissivity=emissivity),
            _node("battery"),
            _node("payload"),
        )
    )
    result = compute_thermal_interval_transition(
        _state({"bus": 300.0, "battery": 300.0, "payload": 300.0}),
        config,
        _inputs({"bus": sink, "battery": 300.0, "payload": 300.0}),
        dt_seconds=10,
    )
    bus = _transition_by_name(result)["bus"]

    assert bus.radiative_heat_into_w == 0.0
    assert bus.net_heat_into_w == 0.0
    assert bus.end_temperature_k == bus.start_temperature_k


def test_combined_conduction_and_radiation_ledger_matches_equations() -> None:
    config = _network(
        nodes=(
            _node("bus", emissivity=0.7, area=1.2),
            _node("battery", emissivity=0.4, area=0.5),
            _node("payload", emissivity=0.6, area=0.8),
        ),
        links=(
            _link("bus-battery", "bus", "battery", 2.0),
            _link("battery-payload", "battery", "payload", 1.5),
        ),
    )
    result = compute_thermal_interval_transition(
        _state({"bus": 310.0, "battery": 295.0, "payload": 285.0}),
        config,
        _inputs({"bus": 280.0, "battery": 290.0, "payload": 300.0}),
        dt_seconds=12,
    )
    bus = _transition_by_name(result)["bus"]
    expected_cond = -2.0 * (310.0 - 295.0)
    expected_rad = 0.7 * SIGMA * 1.2 * (280.0**4 - 310.0**4)
    expected_net = expected_cond + expected_rad
    expected_energy = expected_net * 12
    expected_end = 310.0 + expected_energy / 1000.0

    assert bus.conductive_heat_into_w == pytest.approx(expected_cond)
    assert bus.radiative_heat_into_w == pytest.approx(expected_rad)
    assert bus.net_heat_into_w == pytest.approx(expected_net)
    assert bus.thermal_energy_change_j == pytest.approx(expected_energy)
    assert bus.end_temperature_k == pytest.approx(expected_end)


def test_runtime_and_boundary_tuple_order_do_not_change_physics() -> None:
    config = _network(
        nodes=(
            _node("bus", emissivity=0.7),
            _node("battery", emissivity=0.5),
            _node("payload", emissivity=0.6),
        ),
        links=(
            _link("bus-battery", "bus", "battery", 2.0),
            _link("battery-payload", "battery", "payload", 1.5),
        ),
    )
    temperatures = {"bus": 310.0, "battery": 295.0, "payload": 285.0}
    sinks = {"bus": 280.0, "battery": 290.0, "payload": 300.0}
    canonical = compute_thermal_interval_transition(
        _state(temperatures),
        config,
        _inputs(sinks),
        dt_seconds=12,
    )
    reordered = compute_thermal_interval_transition(
        _state(temperatures, order=("payload", "bus", "battery")),
        config,
        _inputs(sinks, order=("battery", "payload", "bus")),
        dt_seconds=12,
    )

    assert canonical == reordered
    assert tuple(item.node_id.value for item in canonical.node_transitions) == (
        BASELINE_NAMES
    )
    assert tuple(item.link_id.value for item in canonical.link_heat_flows) == (
        "bus-battery",
        "battery-payload",
    )


def test_four_node_radiator_network_uses_same_generic_api() -> None:
    nodes = (
        _node("bus", emissivity=0.2),
        _node("battery", emissivity=0.1),
        _node("payload", emissivity=0.3),
        _node("radiator", emissivity=0.9, area=3.0),
    )
    config = _network(
        nodes=nodes,
        links=(
            _link("bus-battery", "bus", "battery", 2.0),
            _link("bus-radiator", "bus", "radiator", 4.0),
        ),
    )
    result = compute_thermal_interval_transition(
        _state(
            {
                "bus": 310.0,
                "battery": 295.0,
                "payload": 290.0,
                "radiator": 270.0,
            }
        ),
        config,
        _inputs(
            {
                "bus": 280.0,
                "battery": 280.0,
                "payload": 280.0,
                "radiator": 250.0,
            }
        ),
        dt_seconds=5,
    )

    assert tuple(item.node_id.value for item in result.node_transitions) == (
        "bus",
        "battery",
        "payload",
        "radiator",
    )
    assert len(result.link_heat_flows) == 2
    assert all(isfinite(item.end_temperature_k) for item in result.node_transitions)


def test_compute_mutates_no_state_configuration_or_boundary_input() -> None:
    config = _network(
        links=(_link("bus-battery", "bus", "battery", 2.0),)
    )
    state = _baseline_state()
    inputs = _baseline_inputs()
    config_before = deepcopy(config)
    state_before = deepcopy(state)
    inputs_before = deepcopy(inputs)
    state_node_references = tuple(state.node_states)
    input_boundary_references = tuple(inputs.node_boundaries)

    compute_thermal_interval_transition(
        state,
        config,
        inputs,
        dt_seconds=10,
    )

    assert config == config_before
    assert state == state_before
    assert inputs == inputs_before
    assert all(
        current is original
        for current, original in zip(state.node_states, state_node_references)
    )
    assert all(
        current is original
        for current, original in zip(
            inputs.node_boundaries,
            input_boundary_references,
        )
    )


def test_extreme_temperature_fourth_power_fails_intentionally() -> None:
    config = _network(
        nodes=(
            _node("bus", emissivity=1.0),
            _node("battery"),
            _node("payload"),
        )
    )
    state = _state({"bus": 1.0e100, "battery": 300.0, "payload": 300.0})

    with pytest.raises(ValueError, match="fourth power|finite") as captured:
        compute_thermal_interval_transition(
            state,
            config,
            _baseline_inputs(),
            dt_seconds=1,
        )

    assert type(captured.value) is ValueError


@pytest.mark.parametrize("dt_seconds", (10**400, 1_000_000_000))
def test_huge_dt_or_nonpositive_euler_endpoint_fails_intentionally(
    dt_seconds,
) -> None:
    config = _network(
        nodes=(
            _node("bus", emissivity=1.0, area=100.0),
            _node("battery"),
            _node("payload"),
        )
    )
    state = _state({"bus": 300.0, "battery": 300.0, "payload": 300.0})
    inputs = _inputs({"bus": 1.0, "battery": 300.0, "payload": 300.0})

    with pytest.raises(ValueError) as captured:
        compute_thermal_interval_transition(
            state,
            config,
            inputs,
            dt_seconds=dt_seconds,
        )

    assert type(captured.value) is ValueError


def test_numpy_real_temperatures_and_sink_execute_without_adapter_errors() -> None:
    state = _state(
        {
            "bus": np.int64(310),
            "battery": np.float64(290.0),
            "payload": np.int64(300),
        }
    )
    inputs = _inputs(
        {
            "bus": np.float64(300.0),
            "battery": np.float64(300.0),
            "payload": np.float64(300.0),
        }
    )
    result = compute_thermal_interval_transition(
        state,
        _network(links=(_link("bus-battery", "bus", "battery", 2.0),)),
        inputs,
        dt_seconds=10,
    )

    assert result.link_heat_flows[0].heat_flow_a_to_b_w == 40.0
    assert _transition_by_name(result)["bus"].end_temperature_k == (
        pytest.approx(309.6)
    )


def test_positive_temperature_outside_survival_limits_still_evolves() -> None:
    result = compute_thermal_interval_transition(
        _state({"bus": 500.0, "battery": 300.0, "payload": 300.0}),
        _network(
            nodes=(
                _node("bus", emissivity=0.2),
                _node("battery"),
                _node("payload"),
            )
        ),
        _inputs({"bus": 490.0, "battery": 300.0, "payload": 300.0}),
        dt_seconds=1,
    )

    bus = _transition_by_name(result)["bus"]
    assert bus.start_temperature_k == 500.0
    assert 0 < bus.end_temperature_k < 500.0


def test_thermal_module_has_one_link_evaluation_and_no_forbidden_coupling() -> None:
    source = THERMAL_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(THERMAL_PATH))
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
    prohibited_imports = {
        "numpy",
        "pandas",
        "engine",
        "context",
        "checkpoint",
        "controller",
    }
    prohibited_identifiers = {
        "EPSIntervalResult",
        "BatteryState",
        "OperationalMode",
        "FDIRState",
        "internal_heat_w",
        "component_heat_w",
        "absorbed_solar_w",
        "earth_ir_w",
        "albedo_w",
        "battery_loss_heat_w",
        "heater_w",
        "degradation",
        "isclose",
        "round",
        "clamp",
        "epsilon",
        "min",
        "max",
    }

    assert import_roots.isdisjoint(prohibited_imports)
    assert identifiers.isdisjoint(prohibited_identifiers)
    assert source.count("for link in config.links") == 1
    assert "operating_min_temperature_k" not in source
    assert "operating_max_temperature_k" not in source
    assert "survival_min_temperature_k" not in source
    assert "survival_max_temperature_k" not in source


def test_v52b_decisions_source_record_and_exports_are_exact() -> None:
    decision_log = DECISION_LOG_PATH.read_text(encoding="utf-8")
    source_register = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s004 = source_register.partition("### S004 ")[2].partition("### S005 ")[0]
    for decision_number in range(91, 97):
        assert decision_log.count(f"## D{decision_number:03d} ") == 1
    assert decision_log.index("## D090 ") < decision_log.index("## D091 ")
    assert "C_i dT_i/dt" in s004
    assert "G_ab (T_a - T_b)" in s004
    assert "epsilon sigma A" in s004
    assert "5.670374419e-8" in s004
    assert "NIST 2018 CODATA" in s004
    assert "transient boundary input" in s004
    assert "convergence" in s004

    from ops_sim.v5 import thermal

    assert thermal.__all__ == [
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
