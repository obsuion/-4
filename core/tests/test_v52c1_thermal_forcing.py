"""Scientific and structural validation for V5.2C1 thermal forcing."""

import ast
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from math import isfinite
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
    EPSIntervalResult,
    compute_eps_interval_transition,
)
from ops_sim.v5.ids import (
    ParameterId,
    SubsystemConfigurationId,
    ThermalLinkId,
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
    ThermalAppliedHeatInputs,
    ThermalIntervalInputs,
    ThermalNodeAppliedHeatInput,
    ThermalNodeBoundaryInput,
    compute_thermal_interval_transition,
    compute_thermal_interval_transition_with_applied_heat,
)
from ops_sim.v5.thermal_config import (
    ThermalLinkConfig,
    ThermalNetworkConfig,
    ThermalNodeConfig,
)
from ops_sim.v5.thermal_coupling import (
    EPSThermalCouplingResult,
    ThermalHeatSourceInputs,
    ThermalNodeHeatLedger,
    ThermalNodeHeatSourceInput,
    compute_eps_thermal_interval_transition,
)


ROOT = Path(__file__).resolve().parents[1]
THERMAL_PATH = ROOT / "ops_sim" / "v5" / "thermal.py"
COUPLING_PATH = ROOT / "ops_sim" / "v5" / "thermal_coupling.py"
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
        _parameter(f"thermal.link.{name}.conductance", "W/K", conductance),
    )


def _network(
    *,
    names: tuple[str, ...] = BASELINE_NAMES,
    nodes: tuple[ThermalNodeConfig, ...] | None = None,
    links: tuple[ThermalLinkConfig, ...] = (),
    bus_role: str = "bus",
    battery_role: str = "battery",
    payload_role: str = "payload",
) -> ThermalNetworkConfig:
    return ThermalNetworkConfig(
        tuple(_node(name) for name in names) if nodes is None else nodes,
        links,
        ThermalNodeId(bus_role),
        ThermalNodeId(battery_role),
        ThermalNodeId(payload_role),
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


def _thermal_inputs(
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


def _source(
    name: str,
    *,
    internal: object = 0.0,
    solar: object = 0.0,
    albedo: object = 0.0,
    earth_ir: object = 0.0,
) -> ThermalNodeHeatSourceInput:
    return ThermalNodeHeatSourceInput(
        ThermalNodeId(name),
        internal,
        solar,
        albedo,
        earth_ir,
    )


def _sources(
    names: tuple[str, ...] = BASELINE_NAMES,
    *,
    replacements: dict[str, ThermalNodeHeatSourceInput] | None = None,
    order: tuple[str, ...] | None = None,
) -> ThermalHeatSourceInputs:
    replacement_values = {} if replacements is None else replacements
    source_order = names if order is None else order
    return ThermalHeatSourceInputs(
        tuple(
            replacement_values.get(name, _source(name))
            for name in source_order
        )
    )


def _battery_config(
    *,
    charge_efficiency: object = 1.0,
    discharge_efficiency: object = 1.0,
) -> BatteryConfig:
    return BatteryConfig(
        SubsystemConfigurationId("battery-c1"),
        _parameter("eps.battery.nominal-energy", "Wh", 1000.0),
        _parameter(
            "eps.battery.charge-efficiency",
            "1",
            charge_efficiency,
        ),
        _parameter(
            "eps.battery.discharge-efficiency",
            "1",
            discharge_efficiency,
        ),
        _parameter("eps.battery.max-charge-input-power", "W", 1000.0),
        _parameter("eps.battery.max-discharge-output-power", "W", 1000.0),
    )


def _eps_config(
    *,
    nominal_generation_w: object = 200.0,
    charge_efficiency: object = 1.0,
    discharge_efficiency: object = 1.0,
) -> EPSConfig:
    return EPSConfig(
        SubsystemConfigurationId("eps-c1"),
        _battery_config(
            charge_efficiency=charge_efficiency,
            discharge_efficiency=discharge_efficiency,
        ),
        SolarArrayConfig(
            SubsystemConfigurationId("solar-c1"),
            _parameter(
                "eps.solar-array.nominal-generation",
                "W",
                nominal_generation_w,
            ),
        ),
    )


def _loads(base_bus_w: object = 0.0) -> PowerLoadBreakdown:
    return PowerLoadBreakdown(base_bus_w, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _eps_result(mode: str, *, dt_seconds: int) -> EPSIntervalResult:
    if mode == "lossy-charge":
        return compute_eps_interval_transition(
            BatteryState(100.0),
            _eps_config(charge_efficiency=0.8),
            EPSIntervalInputs(True, 0.0, _loads(100.0)),
            dt_seconds=dt_seconds,
        )
    if mode == "lossy-discharge":
        return compute_eps_interval_transition(
            BatteryState(500.0),
            _eps_config(discharge_efficiency=0.8),
            EPSIntervalInputs(False, 0.0, _loads(80.0)),
            dt_seconds=dt_seconds,
        )
    if mode == "zero-loss":
        return compute_eps_interval_transition(
            BatteryState(500.0),
            _eps_config(),
            EPSIntervalInputs(False, 0.0, _loads()),
            dt_seconds=dt_seconds,
        )
    raise AssertionError(f"unknown EPS test mode: {mode}")


def _neutral_state(names: tuple[str, ...] = BASELINE_NAMES) -> ThermalState:
    return _state({name: 300.0 for name in names})


def _neutral_inputs(
    names: tuple[str, ...] = BASELINE_NAMES,
) -> ThermalIntervalInputs:
    return _thermal_inputs({name: 300.0 for name in names})


def _couple(
    *,
    state: ThermalState | None = None,
    config: ThermalNetworkConfig | None = None,
    thermal_inputs: ThermalIntervalInputs | None = None,
    heat_source_inputs: ThermalHeatSourceInputs | None = None,
    eps_result: EPSIntervalResult | None = None,
    dt_seconds: int = 10,
) -> EPSThermalCouplingResult:
    return compute_eps_thermal_interval_transition(
        _neutral_state() if state is None else state,
        _network() if config is None else config,
        _neutral_inputs() if thermal_inputs is None else thermal_inputs,
        _sources() if heat_source_inputs is None else heat_source_inputs,
        _eps_result("zero-loss", dt_seconds=dt_seconds)
        if eps_result is None
        else eps_result,
        dt_seconds=dt_seconds,
    )


def _ledgers_by_name(
    result: EPSThermalCouplingResult,
) -> dict[str, ThermalNodeHeatLedger]:
    return {ledger.node_id.value: ledger for ledger in result.node_heat_ledgers}


def _transitions_by_name(result: EPSThermalCouplingResult):
    return {
        transition.node_id.value: transition
        for transition in result.thermal_result.node_transitions
    }


def test_c1_dataclasses_have_exact_frozen_slotted_required_fields() -> None:
    expected_fields = {
        ThermalNodeAppliedHeatInput: ("node_id", "applied_heat_into_w"),
        ThermalAppliedHeatInputs: ("node_heat_inputs",),
        ThermalNodeHeatSourceInput: (
            "node_id",
            "internal_dissipation_w",
            "absorbed_solar_w",
            "absorbed_albedo_w",
            "absorbed_earth_ir_w",
        ),
        ThermalHeatSourceInputs: ("node_sources",),
        ThermalNodeHeatLedger: (
            "node_id",
            "internal_dissipation_w",
            "absorbed_solar_w",
            "absorbed_albedo_w",
            "absorbed_earth_ir_w",
            "battery_conversion_heat_w",
            "total_applied_heat_w",
        ),
        EPSThermalCouplingResult: ("node_heat_ledgers", "thermal_result"),
    }
    for class_type, field_names in expected_fields.items():
        assert tuple(field.name for field in fields(class_type)) == field_names
        assert class_type.__dataclass_params__.frozen
        for field in fields(class_type):
            assert field.default is MISSING
            assert field.default_factory is MISSING

    source = _source("bus")
    assert not hasattr(source, "__dict__")
    assert isinstance(hash(source), int)
    with pytest.raises(FrozenInstanceError):
        source.internal_dissipation_w = 1.0


@pytest.mark.parametrize(
    "field_name",
    (
        "internal_dissipation_w",
        "absorbed_solar_w",
        "absorbed_albedo_w",
        "absorbed_earth_ir_w",
    ),
)
@pytest.mark.parametrize(
    ("invalid", "error_type"),
    (
        (True, TypeError),
        ("1", TypeError),
        (-1.0, ValueError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (float("-inf"), ValueError),
    ),
)
def test_source_power_fields_require_nonnegative_finite_reals(
    field_name,
    invalid,
    error_type,
) -> None:
    with pytest.raises(error_type):
        replace(_source("bus"), **{field_name: invalid})


def test_source_collections_require_tuple_exact_members_unique_ids_and_revalidate() -> None:
    source = _source("bus")
    with pytest.raises(TypeError, match="tuple"):
        ThermalHeatSourceInputs([source])
    with pytest.raises(ValueError, match="empty"):
        ThermalHeatSourceInputs(())
    with pytest.raises(TypeError, match="ThermalNodeHeatSourceInput"):
        ThermalHeatSourceInputs((object(),))
    with pytest.raises(ValueError, match="unique"):
        ThermalHeatSourceInputs((source, source))
    object.__setattr__(source, "absorbed_solar_w", float("nan"))
    with pytest.raises(ValueError, match="finite"):
        ThermalHeatSourceInputs((source,))


def test_generic_applied_heat_accepts_signed_values_and_validates_collection() -> None:
    heating = ThermalNodeAppliedHeatInput(ThermalNodeId("bus"), 5.0)
    cooling = ThermalNodeAppliedHeatInput(ThermalNodeId("battery"), -5.0)
    inputs = ThermalAppliedHeatInputs((heating, cooling))
    assert inputs.node_heat_inputs == (heating, cooling)

    with pytest.raises(TypeError, match="ThermalNodeId"):
        ThermalNodeAppliedHeatInput(ParameterId("bus"), 1.0)
    for invalid, error_type in (
        (True, TypeError),
        ("1", TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ):
        with pytest.raises(error_type):
            ThermalNodeAppliedHeatInput(ThermalNodeId("bus"), invalid)
    with pytest.raises(TypeError, match="tuple"):
        ThermalAppliedHeatInputs([heating])
    with pytest.raises(ValueError, match="empty"):
        ThermalAppliedHeatInputs(())
    with pytest.raises(TypeError, match="ThermalNodeAppliedHeatInput"):
        ThermalAppliedHeatInputs((object(),))
    with pytest.raises(ValueError, match="unique"):
        ThermalAppliedHeatInputs((heating, heating))


@pytest.mark.parametrize(
    ("source_names", "state_names", "boundary_names"),
    (
        (("bus", "battery"), BASELINE_NAMES, BASELINE_NAMES),
        ((*BASELINE_NAMES, "radiator"), BASELINE_NAMES, BASELINE_NAMES),
        (("bus", "battery", "renamed"), BASELINE_NAMES, BASELINE_NAMES),
        (BASELINE_NAMES, ("bus", "battery"), BASELINE_NAMES),
        (BASELINE_NAMES, BASELINE_NAMES, ("bus", "battery")),
    ),
)
def test_coupling_requires_exact_config_state_boundary_and_source_id_sets(
    source_names,
    state_names,
    boundary_names,
) -> None:
    with pytest.raises(ValueError, match="node IDs"):
        compute_eps_thermal_interval_transition(
            _state({name: 300.0 for name in state_names}),
            _network(),
            _thermal_inputs({name: 300.0 for name in boundary_names}),
            _sources(source_names),
            _eps_result("zero-loss", dt_seconds=10),
            dt_seconds=10,
        )


def test_zero_applied_heat_is_physically_identical_to_v52b_api() -> None:
    state = _state({"bus": 310.0, "battery": 295.0, "payload": 285.0})
    config = _network(
        nodes=(
            _node("bus", emissivity=0.7),
            _node("battery", emissivity=0.4),
            _node("payload", emissivity=0.6),
        ),
        links=(
            _link("bus-battery", "bus", "battery", 2.0),
            _link("battery-payload", "battery", "payload", 1.5),
        ),
    )
    inputs = _thermal_inputs(
        {"bus": 280.0, "battery": 290.0, "payload": 300.0}
    )
    zero_heat = ThermalAppliedHeatInputs(
        tuple(
            ThermalNodeAppliedHeatInput(node.node_id, 0.0)
            for node in config.nodes
        )
    )
    baseline = compute_thermal_interval_transition(
        state, config, inputs, dt_seconds=12
    )
    source_aware = compute_thermal_interval_transition_with_applied_heat(
        state,
        config,
        inputs,
        zero_heat,
        dt_seconds=12,
    )

    assert baseline == source_aware
    assert all(
        transition.applied_heat_into_w == 0.0
        for transition in baseline.node_transitions
    )


def test_signed_applied_heat_drives_independent_internal_heat_hand_case() -> None:
    heat_inputs = ThermalAppliedHeatInputs(
        (
            ThermalNodeAppliedHeatInput(ThermalNodeId("bus"), 0.0),
            ThermalNodeAppliedHeatInput(ThermalNodeId("battery"), 100.0),
            ThermalNodeAppliedHeatInput(ThermalNodeId("payload"), 0.0),
        )
    )
    result = compute_thermal_interval_transition_with_applied_heat(
        _neutral_state(),
        _network(),
        _neutral_inputs(),
        heat_inputs,
        dt_seconds=10,
    )
    battery = next(
        item
        for item in result.node_transitions
        if item.node_id == ThermalNodeId("battery")
    )
    assert battery.applied_heat_into_w == 100.0
    assert battery.net_heat_into_w == 100.0
    assert battery.thermal_energy_change_j == 1000.0
    assert battery.end_temperature_k == 301.0


def test_explicit_internal_dissipation_coupling_hand_calculation() -> None:
    result = _couple(
        heat_source_inputs=_sources(
            replacements={"battery": _source("battery", internal=100.0)}
        ),
        dt_seconds=10,
    )
    ledger = _ledgers_by_name(result)["battery"]
    battery = _transitions_by_name(result)["battery"]
    assert ledger.internal_dissipation_w == 100.0
    assert ledger.total_applied_heat_w == 100.0
    assert battery.applied_heat_into_w == 100.0
    assert battery.thermal_energy_change_j == 1000.0
    assert battery.end_temperature_k == 301.0


def test_external_absorbed_sources_are_additive_without_extra_transforms() -> None:
    result = _couple(
        heat_source_inputs=_sources(
            replacements={
                "battery": _source(
                    "battery",
                    internal=5.0,
                    solar=10.0,
                    albedo=20.0,
                    earth_ir=30.0,
                )
            }
        ),
        dt_seconds=10,
    )
    ledger = _ledgers_by_name(result)["battery"]
    battery = _transitions_by_name(result)["battery"]
    assert ledger.total_applied_heat_w == 65.0
    assert battery.net_heat_into_w == 65.0
    assert battery.thermal_energy_change_j == 650.0
    assert battery.end_temperature_k == pytest.approx(300.65)


@pytest.mark.parametrize(
    ("mode", "expected_loss_wh", "expected_heat_w"),
    (
        ("lossy-charge", 20.0, 20.0),
        ("lossy-discharge", 20.0, 20.0),
    ),
)
def test_actual_lossy_eps_conversion_heats_battery_once(
    mode,
    expected_loss_wh,
    expected_heat_w,
) -> None:
    eps_result = _eps_result(mode, dt_seconds=3600)
    result = _couple(eps_result=eps_result, dt_seconds=3600)
    ledgers = _ledgers_by_name(result)
    battery = _transitions_by_name(result)["battery"]

    assert eps_result.battery.conversion_loss_wh == pytest.approx(
        expected_loss_wh
    )
    assert ledgers["battery"].battery_conversion_heat_w == pytest.approx(
        expected_heat_w
    )
    assert all(
        ledger.battery_conversion_heat_w == 0.0
        for name, ledger in ledgers.items()
        if name != "battery"
    )
    assert battery.applied_heat_into_w == pytest.approx(expected_heat_w)
    assert battery.net_heat_into_w == pytest.approx(expected_heat_w)


def test_efficiency_one_produces_no_battery_conversion_heat() -> None:
    eps_result = compute_eps_interval_transition(
        BatteryState(100.0),
        _eps_config(),
        EPSIntervalInputs(True, 0.0, _loads(100.0)),
        dt_seconds=3600,
    )
    result = _couple(eps_result=eps_result, dt_seconds=3600)
    assert eps_result.battery.conversion_loss_wh == 0.0
    assert all(
        ledger.battery_conversion_heat_w == 0.0
        for ledger in result.node_heat_ledgers
    )


def test_battery_conversion_heat_routes_by_configured_role_not_name_or_position() -> None:
    names = ("radiator", "payload", "bus", "storage")
    config = _network(
        names=names,
        bus_role="bus",
        battery_role="storage",
        payload_role="payload",
    )
    result = compute_eps_thermal_interval_transition(
        _neutral_state(names),
        config,
        _neutral_inputs(names),
        _sources(names),
        _eps_result("lossy-charge", dt_seconds=3600),
        dt_seconds=3600,
    )
    ledgers = _ledgers_by_name(result)
    assert tuple(item.node_id.value for item in result.node_heat_ledgers) == names
    assert ledgers["storage"].battery_conversion_heat_w == pytest.approx(20.0)
    assert ledgers["radiator"].battery_conversion_heat_w == 0.0
    assert ledgers["bus"].battery_conversion_heat_w == 0.0


def test_combined_conduction_radiation_sources_and_eps_match_hand_balance() -> None:
    nodes = (
        _node("bus", heat_capacity=100_000.0, emissivity=0.7, area=1.2),
        _node("battery", heat_capacity=100_000.0, emissivity=0.4, area=0.5),
        _node("payload", heat_capacity=100_000.0, emissivity=0.6, area=0.8),
    )
    config = _network(
        nodes=nodes,
        links=(
            _link("bus-battery", "bus", "battery", 2.0),
            _link("battery-payload", "battery", "payload", 1.5),
        ),
    )
    state = _state({"bus": 310.0, "battery": 295.0, "payload": 285.0})
    thermal_inputs = _thermal_inputs(
        {"bus": 280.0, "battery": 290.0, "payload": 300.0}
    )
    sources = _sources(
        replacements={
            "battery": _source(
                "battery",
                internal=10.0,
                solar=3.0,
                albedo=2.0,
                earth_ir=5.0,
            )
        }
    )
    result = compute_eps_thermal_interval_transition(
        state,
        config,
        thermal_inputs,
        sources,
        _eps_result("lossy-charge", dt_seconds=3600),
        dt_seconds=3600,
    )
    ledger = _ledgers_by_name(result)["battery"]
    battery = _transitions_by_name(result)["battery"]

    expected_conduction = 2.0 * (310.0 - 295.0) - 1.5 * (295.0 - 285.0)
    expected_radiation = 0.4 * SIGMA * 0.5 * (290.0**4 - 295.0**4)
    expected_external = 3.0 + 2.0 + 5.0
    expected_battery_loss = 20.0
    expected_applied = 10.0 + expected_external + expected_battery_loss
    expected_net = expected_conduction + expected_radiation + expected_applied
    expected_energy = expected_net * 3600
    expected_end = 295.0 + expected_energy / 100_000.0

    assert battery.conductive_heat_into_w == pytest.approx(expected_conduction)
    assert battery.radiative_heat_into_w == pytest.approx(expected_radiation)
    assert ledger.internal_dissipation_w == 10.0
    assert (
        ledger.absorbed_solar_w
        + ledger.absorbed_albedo_w
        + ledger.absorbed_earth_ir_w
    ) == expected_external
    assert ledger.battery_conversion_heat_w == pytest.approx(
        expected_battery_loss
    )
    assert ledger.total_applied_heat_w == pytest.approx(expected_applied)
    assert battery.net_heat_into_w == pytest.approx(expected_net)
    assert battery.thermal_energy_change_j == pytest.approx(expected_energy)
    assert battery.end_temperature_k == pytest.approx(expected_end)


def test_runtime_boundary_and_source_tuple_order_are_nonsemantic() -> None:
    temperatures = {"bus": 310.0, "battery": 295.0, "payload": 285.0}
    sinks = {"bus": 280.0, "battery": 290.0, "payload": 300.0}
    replacements = {
        "bus": _source("bus", internal=1.0),
        "battery": _source("battery", solar=2.0),
        "payload": _source("payload", earth_ir=3.0),
    }
    config = _network(
        links=(_link("bus-battery", "bus", "battery", 2.0),)
    )
    eps_result = _eps_result("lossy-charge", dt_seconds=3600)
    canonical = compute_eps_thermal_interval_transition(
        _state(temperatures),
        config,
        _thermal_inputs(sinks),
        _sources(replacements=replacements),
        eps_result,
        dt_seconds=3600,
    )
    reordered = compute_eps_thermal_interval_transition(
        _state(temperatures, order=("payload", "bus", "battery")),
        config,
        _thermal_inputs(sinks, order=("battery", "payload", "bus")),
        _sources(
            replacements=replacements,
            order=("payload", "battery", "bus"),
        ),
        eps_result,
        dt_seconds=3600,
    )
    assert canonical == reordered
    assert tuple(item.node_id.value for item in canonical.node_heat_ledgers) == (
        BASELINE_NAMES
    )


def test_four_node_radiator_uses_same_generic_source_path() -> None:
    names = ("bus", "storage", "payload", "radiator")
    config = _network(
        names=names,
        battery_role="storage",
        links=(_link("bus-radiator", "bus", "radiator", 1.0),),
    )
    result = compute_eps_thermal_interval_transition(
        _neutral_state(names),
        config,
        _neutral_inputs(names),
        _sources(
            names,
            replacements={"radiator": _source("radiator", internal=50.0)},
        ),
        _eps_result("zero-loss", dt_seconds=10),
        dt_seconds=10,
    )
    radiator = _transitions_by_name(result)["radiator"]
    assert tuple(item.node_id.value for item in result.node_heat_ledgers) == names
    assert radiator.applied_heat_into_w == 50.0
    assert radiator.end_temperature_k == 300.5


def test_coupling_mutates_no_input_or_eps_result() -> None:
    state = _neutral_state()
    config = _network(
        links=(_link("bus-battery", "bus", "battery", 2.0),)
    )
    thermal_inputs = _neutral_inputs()
    source_inputs = _sources(
        replacements={"battery": _source("battery", internal=10.0)}
    )
    eps_result = _eps_result("lossy-charge", dt_seconds=3600)
    originals = tuple(
        deepcopy(item)
        for item in (
            state,
            config,
            thermal_inputs,
            source_inputs,
            eps_result,
        )
    )
    state_nodes = tuple(state.node_states)

    compute_eps_thermal_interval_transition(
        state,
        config,
        thermal_inputs,
        source_inputs,
        eps_result,
        dt_seconds=3600,
    )

    assert (state, config, thermal_inputs, source_inputs, eps_result) == originals
    assert all(
        current is original
        for current, original in zip(state.node_states, state_nodes)
    )


def test_eps_and_thermal_timestep_must_match_exactly() -> None:
    with pytest.raises(ValueError, match="must equal"):
        _couple(
            eps_result=_eps_result("zero-loss", dt_seconds=9),
            dt_seconds=10,
        )


@pytest.mark.parametrize(
    ("argument", "value", "error_type"),
    (
        ("state", object(), TypeError),
        ("config", object(), TypeError),
        ("thermal_inputs", object(), TypeError),
        ("heat_source_inputs", object(), TypeError),
        ("eps_result", object(), TypeError),
        ("dt_seconds", True, TypeError),
        ("dt_seconds", 1.0, TypeError),
        ("dt_seconds", 0, ValueError),
        ("dt_seconds", -1, ValueError),
    ),
)
def test_coupling_requires_exact_types_and_positive_integer_dt(
    argument,
    value,
    error_type,
) -> None:
    arguments = {
        "state": _neutral_state(),
        "config": _network(),
        "thermal_inputs": _neutral_inputs(),
        "heat_source_inputs": _sources(),
        "eps_result": _eps_result("zero-loss", dt_seconds=10),
        "dt_seconds": 10,
    }
    arguments[argument] = value
    with pytest.raises(error_type):
        compute_eps_thermal_interval_transition(**arguments)


def test_invalid_battery_loss_conversion_fails_intentionally() -> None:
    eps_result = _eps_result("zero-loss", dt_seconds=1)
    object.__setattr__(eps_result.battery, "conversion_loss_wh", 1.0e308)
    with pytest.raises(ValueError) as captured:
        _couple(eps_result=eps_result, dt_seconds=1)
    assert type(captured.value) is ValueError


def test_nonfinite_source_aggregate_fails_intentionally() -> None:
    sources = _sources(
        replacements={
            "battery": _source(
                "battery",
                internal=1.0e308,
                solar=1.0e308,
            )
        }
    )
    with pytest.raises(ValueError, match="finite") as captured:
        _couple(heat_source_inputs=sources, dt_seconds=10)
    assert type(captured.value) is ValueError


def test_negative_applied_heat_rejects_nonpositive_euler_endpoint() -> None:
    applied = ThermalAppliedHeatInputs(
        (
            ThermalNodeAppliedHeatInput(ThermalNodeId("bus"), -40_000.0),
            ThermalNodeAppliedHeatInput(ThermalNodeId("battery"), 0.0),
            ThermalNodeAppliedHeatInput(ThermalNodeId("payload"), 0.0),
        )
    )
    with pytest.raises(ValueError, match="greater than zero"):
        compute_thermal_interval_transition_with_applied_heat(
            _neutral_state(),
            _network(),
            _neutral_inputs(),
            applied,
            dt_seconds=10,
        )


def test_ordinary_finite_source_significance_loss_is_allowed() -> None:
    ledger = ThermalNodeHeatLedger(
        ThermalNodeId("bus"),
        1.0e16,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0e16,
    )
    assert ledger.total_applied_heat_w == ledger.internal_dissipation_w

    applied = ThermalAppliedHeatInputs(
        (
            ThermalNodeAppliedHeatInput(ThermalNodeId("bus"), 1.0e-20),
            ThermalNodeAppliedHeatInput(ThermalNodeId("battery"), 0.0),
            ThermalNodeAppliedHeatInput(ThermalNodeId("payload"), 0.0),
        )
    )
    config = _network(
        links=(_link("bus-battery", "bus", "battery", 2.0),)
    )
    result = compute_thermal_interval_transition_with_applied_heat(
        _state({"bus": 310.0, "battery": 290.0, "payload": 300.0}),
        config,
        _thermal_inputs(
            {"bus": 310.0, "battery": 290.0, "payload": 300.0}
        ),
        applied,
        dt_seconds=1,
    )
    bus = next(
        item
        for item in result.node_transitions
        if item.node_id == ThermalNodeId("bus")
    )
    assert bus.applied_heat_into_w != 0.0
    assert bus.net_heat_into_w == bus.conductive_heat_into_w == -40.0


def test_numpy_real_sources_execute_without_production_numpy_dependency() -> None:
    result = _couple(
        heat_source_inputs=_sources(
            replacements={
                "battery": _source(
                    "battery",
                    internal=np.int64(10),
                    solar=np.float64(2.5),
                )
            }
        ),
        dt_seconds=10,
    )
    ledger = _ledgers_by_name(result)["battery"]
    assert ledger.total_applied_heat_w == pytest.approx(12.5)
    assert _transitions_by_name(result)["battery"].end_temperature_k == (
        pytest.approx(300.125)
    )


def test_coupling_result_validates_ledger_total_identity_and_node_sets() -> None:
    valid = _couple(dt_seconds=10)
    ledger = valid.node_heat_ledgers[0]
    with pytest.raises(ValueError, match="sum"):
        replace(ledger, total_applied_heat_w=1.0)
    with pytest.raises(ValueError, match="unique"):
        replace(valid, node_heat_ledgers=(ledger, ledger))
    with pytest.raises(ValueError, match="exactly match"):
        replace(valid, node_heat_ledgers=valid.node_heat_ledgers[:-1])


def test_c1_production_has_no_load_inference_engine_degradation_or_numpy() -> None:
    coupling_source = COUPLING_PATH.read_text(encoding="utf-8")
    thermal_source = THERMAL_PATH.read_text(encoding="utf-8")
    coupling_tree = ast.parse(coupling_source, filename=str(COUPLING_PATH))
    import_roots = {
        alias.name.partition(".")[0]
        for node in ast.walk(coupling_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").partition(".")[0]
        for node in ast.walk(coupling_tree)
        if isinstance(node, ast.ImportFrom)
    }
    identifiers = {
        node.id for node in ast.walk(coupling_tree) if isinstance(node, ast.Name)
    } | {
        node.attr
        for node in ast.walk(coupling_tree)
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
        "total_load_w",
        "payload_w",
        "communications_w",
        "propulsion_w",
        "PowerLoadBreakdown",
        "unmet_load_w",
        "served_load_w",
        "OperationalMode",
        "FDIRState",
        "degradation",
        "capacity_fade",
        "cycle_count",
        "health",
        "isclose",
        "round",
        "clamp",
    }
    coupling_calls = [
        node
        for node in ast.walk(coupling_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id
        == "compute_thermal_interval_transition_with_applied_heat"
    ]
    assert import_roots.isdisjoint(prohibited_imports)
    assert identifiers.isdisjoint(prohibited_identifiers)
    assert "numpy" not in thermal_source
    assert "pandas" not in thermal_source
    assert len(coupling_calls) == 1


def test_c1_decisions_source_contract_and_exports_are_exact() -> None:
    decision_log = DECISION_LOG_PATH.read_text(encoding="utf-8")
    source_register = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s004 = source_register.partition("### S004 ")[2].partition("### S005 ")[0]
    for decision_number in range(97, 103):
        assert decision_log.count(f"## D{decision_number:03d} ") == 1
    assert decision_log.index("## D096 ") < decision_log.index("## D097 ")
    assert "Q_applied,i" in s004
    assert "Q_internal" in s004
    assert "Q_absorbed_solar" in s004
    assert "Q_absorbed_albedo" in s004
    assert "Q_absorbed_earth_ir" in s004
    assert "Q_battery_conversion_loss" in s004
    assert "E_conversion_loss_Wh * 3600 / dt_s" in s004
    assert "electrical load with waste heat" in s004
    assert "must not encode the same incoming radiation" in s004

    from ops_sim.v5 import thermal, thermal_coupling

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
    assert thermal_coupling.__all__ == [
        "EPSThermalCouplingResult",
        "ThermalHeatSourceInputs",
        "ThermalNodeHeatLedger",
        "ThermalNodeHeatSourceInput",
        "compute_eps_thermal_interval_transition",
    ]
