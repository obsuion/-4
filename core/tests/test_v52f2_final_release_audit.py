"""Final integrated numerical and release audit for V5.2F2."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import dataclass, replace
from io import StringIO
import json
from math import exp, isfinite
from pathlib import Path

import numpy as np
import pytest

from examples.v52_integrated_eps_thermal_demo import (
    build_demo_context,
    build_step_inputs,
    run_demo,
)
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.degradation import (
    BatteryDegradationIntervalInput,
    BatteryThroughputIncrement,
    SolarDegradationForcingInput,
    compute_battery_degradation_transition,
)
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.eps import compute_battery_transition
from ops_sim.v5.eps_capability import (
    EPSCapabilityResult,
    compute_battery_capacity_reconciliation,
    compute_eps_capability,
)
from ops_sim.v5.eps_system import (
    EPSIntervalInputs,
    compute_eps_interval_transition,
)
from ops_sim.v5.eps_validation import compute_eps_conservation_report
from ops_sim.v5.ids import NumericalConfigId, ThermalLinkId, ThermalNodeId
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.state import (
    BatteryDegradationState,
    BatteryState,
    DegradationState,
    SolarDegradationState,
    ThermalNodeState,
    ThermalState,
)
from ops_sim.v5.thermal import (
    ThermalIntervalInputs,
    ThermalNodeBoundaryInput,
    compute_thermal_interval_transition,
)
from ops_sim.v5.thermal_config import (
    ThermalLinkConfig,
    ThermalNetworkConfig,
)
from ops_sim.v5.thermal_coupling import (
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
)


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"
EPS_SYSTEM_PATH = ROOT / "ops_sim" / "v5" / "eps_system.py"
DEGRADATION_PATH = ROOT / "ops_sim" / "v5" / "degradation.py"
THERMAL_PATH = ROOT / "ops_sim" / "v5" / "thermal.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
README_PATH = ROOT / "README.md"
RELEASE_AUDIT_PATH = ROOT / "V5_2_RELEASE_AUDIT.md"

PHASE_DURATION_SECONDS = 960
CONVERGENCE_HORIZON_SECONDS = 4 * PHASE_DURATION_SECONDS
CONVERGENCE_TIMESTEPS_SECONDS = (120, 60, 30, 15)
LONG_RUN_SECONDS = 6 * 3600
LONG_RUN_TIMESTEP_SECONDS = 60
EPS_ENERGY_TOLERANCE_WH = 1.0e-12
EPS_POWER_TOLERANCE_W = 1.0e-12
REPRESENTATION_TOLERANCE = 1.0e-12
NODE_NAMES = ("bus", "battery", "payload")


@dataclass(frozen=True, slots=True)
class _ForcingPhase:
    sunlit: bool
    base_bus_w: float
    payload_w: float
    bus_internal_w: float
    battery_internal_w: float
    payload_internal_w: float


@dataclass(frozen=True, slots=True)
class _RunAudit:
    context: object
    results: tuple[object, ...]
    phase_seconds: tuple[int, int, int, int]
    max_eps_energy_residual_wh: float
    max_eps_power_residual_w: float
    max_thermal_ledger_residual: float
    max_conductive_balance_w: float
    max_reconciliation_unavailable_wh: float
    min_usable_capacity_margin_wh: float
    min_battery_energy_wh: float
    max_battery_energy_wh: float
    min_temperature_k: float
    max_temperature_k: float


FORCING_PHASES = (
    _ForcingPhase(True, 50.0, 20.0, 18.0, 1.5, 4.0),
    _ForcingPhase(True, 50.0, 100.0, 25.0, 2.0, 35.0),
    _ForcingPhase(False, 50.0, 10.0, 16.0, 1.5, 3.0),
    _ForcingPhase(False, 50.0, 70.0, 23.0, 2.0, 28.0),
)


def _parameter_with_value(parameter, value):
    return replace(parameter, value=value)


def _audit_context(
    *,
    dt_seconds: int,
    horizon_seconds: int,
    battery_retention: float = 0.92,
    solar_retention: float = 0.88,
    battery_energy_wh: float = 300.0,
    throughput_wh: float = 25.0,
    calendar_rate: float = 2.0e-9,
    calendar_activation_energy: float = 12_000.0,
    cycling_coefficient: float = 5.0e-4,
    cycling_activation_energy: float = 8_000.0,
):
    context = build_demo_context()
    spacecraft = context.inputs.spacecraft_configuration
    degradation_config = spacecraft.degradation
    model = degradation_config.battery_ageing_model
    model = replace(
        model,
        calendar_damage_rate_per_second_at_reference=_parameter_with_value(
            model.calendar_damage_rate_per_second_at_reference,
            calendar_rate,
        ),
        calendar_activation_energy_j_per_mol=_parameter_with_value(
            model.calendar_activation_energy_j_per_mol,
            calendar_activation_energy,
        ),
        cycling_damage_per_normalized_energy_throughput_at_reference=(
            _parameter_with_value(
                model.cycling_damage_per_normalized_energy_throughput_at_reference,
                cycling_coefficient,
            )
        ),
        cycling_activation_energy_j_per_mol=_parameter_with_value(
            model.cycling_activation_energy_j_per_mol,
            cycling_activation_energy,
        ),
    )
    spacecraft = replace(
        spacecraft,
        degradation=replace(degradation_config, battery_ageing_model=model),
    )
    numerical = replace(
        context.inputs.numerical_config,
        configuration_id=NumericalConfigId(f"v52-f2-step-{dt_seconds}"),
        timestep_seconds=dt_seconds,
        geometry_sample_seconds=min(10, dt_seconds),
        checkpoint_interval_seconds=960,
    )
    world = replace(
        context.inputs.common_world,
        horizon_seconds=horizon_seconds,
    )
    manifest = replace(
        context.inputs.model_manifest,
        numerical_config_id=numerical.configuration_id,
    )
    context.inputs = replace(
        context.inputs,
        spacecraft_configuration=spacecraft,
        numerical_config=numerical,
        common_world=world,
        model_manifest=manifest,
    )
    context.spacecraft_state.battery.energy_wh = battery_energy_wh
    battery_degradation = context.spacecraft_state.degradation.battery
    battery_degradation.usable_capacity_retention = battery_retention
    battery_degradation.cumulative_energy_throughput_wh = throughput_wh
    context.spacecraft_state.degradation.solar.generation_retention = (
        solar_retention
    )
    return context


def _forcing_phase_at(time_seconds: int) -> tuple[int, _ForcingPhase]:
    phase_index = (
        time_seconds // PHASE_DURATION_SECONDS
    ) % len(FORCING_PHASES)
    return phase_index, FORCING_PHASES[phase_index]


def _inputs_at(time_seconds: int):
    _, forcing = _forcing_phase_at(time_seconds)
    eps_inputs = EPSIntervalInputs(
        forcing.sunlit,
        0.0,
        PowerLoadBreakdown(
            forcing.base_bus_w,
            0.0,
            0.0,
            forcing.payload_w,
            0.0,
            0.0,
            0.0,
        ),
    )
    thermal_inputs = ThermalIntervalInputs(
        (
            ThermalNodeBoundaryInput(ThermalNodeId("bus"), 270.0),
            ThermalNodeBoundaryInput(ThermalNodeId("battery"), 268.0),
            ThermalNodeBoundaryInput(ThermalNodeId("payload"), 265.0),
        )
    )
    heat_sources = ThermalHeatSourceInputs(
        (
            ThermalNodeHeatSourceInput(
                ThermalNodeId("bus"),
                forcing.bus_internal_w,
                3.0 if forcing.sunlit else 0.0,
                0.5 if forcing.sunlit else 0.0,
                1.0,
            ),
            ThermalNodeHeatSourceInput(
                ThermalNodeId("battery"),
                forcing.battery_internal_w,
                0.0,
                0.0,
                0.2,
            ),
            ThermalNodeHeatSourceInput(
                ThermalNodeId("payload"),
                forcing.payload_internal_w,
                2.0 if forcing.sunlit else 0.0,
                0.3 if forcing.sunlit else 0.0,
                0.8,
            ),
        )
    )
    return eps_inputs, thermal_inputs, heat_sources


def _mutable_references(context) -> tuple[object, ...]:
    spacecraft = context.spacecraft_state
    return (
        spacecraft,
        spacecraft.battery,
        spacecraft.propulsion,
        spacecraft.thermal,
        *spacecraft.thermal.node_states,
        spacecraft.degradation,
        spacecraft.degradation.battery,
        spacecraft.degradation.solar,
        spacecraft.onboard,
        spacecraft.data_storage,
        context.ground_knowledge_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def _thermal_residuals(result) -> tuple[float, float]:
    coupling = result.thermal_coupling_result
    assert coupling is not None
    ledger_residual = 0.0
    conductive_sum = 0.0
    for transition in coupling.thermal_result.node_transitions:
        expected_net = (
            transition.conductive_heat_into_w
            + transition.radiative_heat_into_w
            + transition.applied_heat_into_w
        )
        ledger_residual = max(
            ledger_residual,
            abs(transition.net_heat_into_w - expected_net),
            abs(
                transition.thermal_energy_change_j
                - transition.net_heat_into_w * result.dt_seconds
            ),
        )
        conductive_sum += transition.conductive_heat_into_w
    return ledger_residual, abs(conductive_sum)


def _run_integrated(context) -> _RunAudit:
    engine = SimulationEngine()
    results = []
    phase_seconds = [0, 0, 0, 0]
    max_eps_energy_residual_wh = 0.0
    max_eps_power_residual_w = 0.0
    max_thermal_ledger_residual = 0.0
    max_conductive_balance_w = 0.0
    max_unavailable_wh = 0.0
    min_margin_wh = float("inf")
    battery_values = [context.spacecraft_state.battery.energy_wh]
    temperature_values = [
        node.temperature_k
        for node in context.spacecraft_state.thermal.node_states
    ]
    previous_throughput = (
        context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
    )
    previous_retention = (
        context.spacecraft_state.degradation.battery
        .usable_capacity_retention
    )
    telemetry = context.ground_knowledge_state.latest_telemetry
    starting_completed_steps = context.diagnostics.completed_steps

    while (
        context.simulation_time_seconds
        < context.inputs.common_world.horizon_seconds
    ):
        start_time = context.simulation_time_seconds
        phase_index, _ = _forcing_phase_at(start_time)
        arguments = _inputs_at(start_time)
        result = engine.step(
            context,
            eps_inputs=arguments[0],
            thermal_inputs=arguments[1],
            heat_source_inputs=arguments[2],
        )
        results.append(result)
        phase_seconds[phase_index] += result.dt_seconds

        eps_result = result.eps_result
        reconciliation = result.battery_capacity_reconciliation_result
        assert eps_result is not None
        assert reconciliation is not None
        report = compute_eps_conservation_report(eps_result)
        assert report.is_within_tolerance(
            EPS_ENERGY_TOLERANCE_WH,
            absolute_power_tolerance_w=EPS_POWER_TOLERANCE_W,
        )
        max_eps_energy_residual_wh = max(
            max_eps_energy_residual_wh,
            report.max_abs_energy_residual_wh,
        )
        max_eps_power_residual_w = max(
            max_eps_power_residual_w,
            report.max_abs_power_link_residual_w,
        )
        thermal_residual, conductive_balance = _thermal_residuals(result)
        assert thermal_residual <= REPRESENTATION_TOLERANCE
        assert conductive_balance <= REPRESENTATION_TOLERANCE
        max_thermal_ledger_residual = max(
            max_thermal_ledger_residual,
            thermal_residual,
        )
        max_conductive_balance_w = max(
            max_conductive_balance_w,
            conductive_balance,
        )

        authoritative_energy = context.spacecraft_state.battery.energy_wh
        assert authoritative_energy >= 0
        assert authoritative_energy <= reconciliation.end_usable_capacity_wh
        if reconciliation.unavailable_energy_wh > 0:
            assert eps_result.battery.end_energy_wh - authoritative_energy == (
                pytest.approx(reconciliation.unavailable_energy_wh)
            )
        max_unavailable_wh = max(
            max_unavailable_wh,
            reconciliation.unavailable_energy_wh,
        )
        min_margin_wh = min(
            min_margin_wh,
            reconciliation.end_usable_capacity_wh - authoritative_energy,
        )
        battery_values.append(authoritative_energy)

        current_throughput = (
            context.spacecraft_state.degradation.battery
            .cumulative_energy_throughput_wh
        )
        current_retention = (
            context.spacecraft_state.degradation.battery
            .usable_capacity_retention
        )
        assert isfinite(current_throughput)
        assert current_throughput >= previous_throughput
        assert 0 < current_retention <= previous_retention <= 1
        assert (
            0
            < context.spacecraft_state.degradation.solar.generation_retention
            <= 1
        )
        previous_throughput = current_throughput
        previous_retention = current_retention
        assert context.ground_knowledge_state.latest_telemetry is telemetry
        assert context.simulation_time_seconds == start_time + result.dt_seconds
        assert context.diagnostics.completed_steps == (
            starting_completed_steps + len(results)
        )
        for node in context.spacecraft_state.thermal.node_states:
            assert isfinite(node.temperature_k)
            assert node.temperature_k > 0
            temperature_values.append(node.temperature_k)

    return _RunAudit(
        context,
        tuple(results),
        tuple(phase_seconds),
        max_eps_energy_residual_wh,
        max_eps_power_residual_w,
        max_thermal_ledger_residual,
        max_conductive_balance_w,
        max_unavailable_wh,
        min_margin_wh,
        min(battery_values),
        max(battery_values),
        min(temperature_values),
        max(temperature_values),
    )


def _endpoint(run: _RunAudit) -> dict[str, float]:
    context = run.context
    temperatures = {
        node.node_id.value: node.temperature_k
        for node in context.spacecraft_state.thermal.node_states
    }
    battery_degradation = context.spacecraft_state.degradation.battery
    return {
        "battery_energy_wh": context.spacecraft_state.battery.energy_wh,
        "bus_temperature_k": temperatures["bus"],
        "battery_temperature_k": temperatures["battery"],
        "payload_temperature_k": temperatures["payload"],
        "battery_retention": battery_degradation.usable_capacity_retention,
        "battery_throughput_wh": (
            battery_degradation.cumulative_energy_throughput_wh
        ),
        "solar_retention": (
            context.spacecraft_state.degradation.solar.generation_retention
        ),
        "completed_time_seconds": context.simulation_time_seconds,
    }


@pytest.fixture(scope="module")
def convergence_runs() -> dict[int, _RunAudit]:
    return {
        dt_seconds: _run_integrated(
            _audit_context(
                dt_seconds=dt_seconds,
                horizon_seconds=CONVERGENCE_HORIZON_SECONDS,
            )
        )
        for dt_seconds in CONVERGENCE_TIMESTEPS_SECONDS
    }


@pytest.fixture(scope="module")
def long_run() -> _RunAudit:
    return _run_integrated(
        _audit_context(
            dt_seconds=LONG_RUN_TIMESTEP_SECONDS,
            horizon_seconds=LONG_RUN_SECONDS,
        )
    )


def _refinement_differences(values: dict[int, float]) -> tuple[float, ...]:
    return tuple(
        abs(values[coarse] - values[fine])
        for coarse, fine in zip(
            CONVERGENCE_TIMESTEPS_SECONDS,
            CONVERGENCE_TIMESTEPS_SECONDS[1:],
        )
    )


def _assert_refinement_consistent(differences: tuple[float, ...]) -> None:
    if all(difference == 0.0 for difference in differences):
        return
    if max(differences) <= REPRESENTATION_TOLERANCE:
        return
    coarse, middle, fine = differences
    assert fine <= middle + REPRESENTATION_TOLERANCE
    assert middle <= coarse + REPRESENTATION_TOLERANCE
    assert fine < coarse


def test_fixed_time_convergence_runs_share_one_physical_chronology(
    convergence_runs,
) -> None:
    for dt_seconds, run in convergence_runs.items():
        assert run.phase_seconds == (960, 960, 960, 960)
        assert len(run.results) == CONVERGENCE_HORIZON_SECONDS // dt_seconds
        assert run.context.simulation_time_seconds == CONVERGENCE_HORIZON_SECONDS
        assert run.context.diagnostics.completed_steps == len(run.results)
        assert run.max_eps_energy_residual_wh <= EPS_ENERGY_TOLERANCE_WH
        assert run.max_eps_power_residual_w <= EPS_POWER_TOLERANCE_W
        assert run.max_thermal_ledger_residual <= REPRESENTATION_TOLERANCE
        assert run.max_conductive_balance_w <= REPRESENTATION_TOLERANCE


def test_integrated_endpoint_refinement_is_consistent(convergence_runs) -> None:
    endpoints = {
        dt_seconds: _endpoint(run)
        for dt_seconds, run in convergence_runs.items()
    }
    for field_name in tuple(endpoints[120]):
        values = {
            dt_seconds: endpoint[field_name]
            for dt_seconds, endpoint in endpoints.items()
        }
        _assert_refinement_consistent(_refinement_differences(values))
    assert all(
        run.max_reconciliation_unavailable_wh == 0.0
        for run in convergence_runs.values()
    )
    assert all(
        run.min_usable_capacity_margin_wh > 0
        for run in convergence_runs.values()
    )


def _analytical_network(
    *,
    heat_capacity_j_per_k: float = 1000.0,
    conductance_w_per_k: float = 0.5,
) -> ThermalNetworkConfig:
    base = build_demo_context().inputs.spacecraft_configuration.thermal.network
    nodes = tuple(
        replace(
            node,
            heat_capacity_j_per_k=_parameter_with_value(
                node.heat_capacity_j_per_k,
                heat_capacity_j_per_k,
            ),
            emissivity=_parameter_with_value(node.emissivity, 0.0),
        )
        for node in base.nodes
    )
    link = ThermalLinkConfig(
        ThermalLinkId("bus-battery"),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        _parameter_with_value(
            base.links[0].conductance_w_per_k,
            conductance_w_per_k,
        ),
    )
    return ThermalNetworkConfig(
        nodes,
        (link,),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("payload"),
    )


def _analytical_run(dt_seconds: int) -> tuple[float, float, float]:
    horizon_seconds = 1000
    state = ThermalState(
        (
            ThermalNodeState(ThermalNodeId("bus"), 310.0),
            ThermalNodeState(ThermalNodeId("battery"), 290.0),
            ThermalNodeState(ThermalNodeId("payload"), 300.0),
        )
    )
    inputs = ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(ThermalNodeId(name), 300.0)
            for name in NODE_NAMES
        )
    )
    network = _analytical_network()
    for _ in range(horizon_seconds // dt_seconds):
        result = compute_thermal_interval_transition(
            state,
            network,
            inputs,
            dt_seconds=dt_seconds,
        )
        endpoints = {
            transition.node_id: transition.end_temperature_k
            for transition in result.node_transitions
        }
        assert 300.0 <= endpoints[ThermalNodeId("bus")] <= 310.0
        assert 290.0 <= endpoints[ThermalNodeId("battery")] <= 300.0
        for node in state.node_states:
            node.temperature_k = endpoints[node.node_id]
    by_name = {node.node_id.value: node.temperature_k for node in state.node_states}
    return by_name["bus"], by_name["battery"], by_name["payload"]


def test_explicit_euler_refines_toward_two_node_analytical_solution() -> None:
    exact_difference_k = 20.0 * exp(-2 * 0.5 * 1000 / 1000.0)
    exact_hot_k = 300.0 + exact_difference_k / 2
    exact_cold_k = 300.0 - exact_difference_k / 2
    errors = []
    for dt_seconds in (200, 100, 50, 25):
        hot_k, cold_k, isolated_k = _analytical_run(dt_seconds)
        assert (hot_k + cold_k) / 2 == pytest.approx(300.0, abs=1.0e-12)
        assert hot_k < 310.0
        assert cold_k > 290.0
        assert hot_k > cold_k
        assert isolated_k == 300.0
        errors.append(max(abs(hot_k - exact_hot_k), abs(cold_k - exact_cold_k)))
    assert all(fine < coarse for coarse, fine in zip(errors, errors[1:]))
    assert exact_hot_k == pytest.approx(303.6787944117144)
    assert exact_cold_k == pytest.approx(296.3212055882856)


def _simple_eps_inputs(
    *, sunlit: bool, incidence_angle_deg: float = 0.0, load_w: float = 0.0
) -> EPSIntervalInputs:
    return EPSIntervalInputs(
        sunlit,
        incidence_angle_deg,
        PowerLoadBreakdown(load_w, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


def _demo_eps_and_capability(
    battery_retention: float = 0.8,
    solar_retention: float = 0.6,
):
    config = build_demo_context().inputs.spacecraft_configuration.eps
    capability = compute_eps_capability(
        config,
        DegradationState(
            BatteryDegradationState(battery_retention, 0.0),
            SolarDegradationState(solar_retention),
        ),
    )
    return config, capability


def test_battery_limiting_cases_hold_through_e2_capability() -> None:
    config, capability = _demo_eps_and_capability(0.8, 1.0)
    empty = compute_eps_interval_transition(
        BatteryState(0.0),
        config,
        _simple_eps_inputs(sunlit=False, load_w=40.0),
        dt_seconds=60,
        capability=capability,
    )
    assert empty.battery.end_energy_wh == 0.0
    assert empty.battery.unmet_load_w == 40.0

    at_cap = compute_eps_interval_transition(
        BatteryState(capability.battery_usable_capacity_wh),
        config,
        _simple_eps_inputs(sunlit=True),
        dt_seconds=3600,
        capability=capability,
    )
    assert at_cap.battery.end_energy_wh == capability.battery_usable_capacity_wh
    assert at_cap.battery.charge_input_w == 0.0
    assert at_cap.battery.curtailed_generation_w == 180.0

    below_cap = compute_eps_interval_transition(
        BatteryState(capability.battery_usable_capacity_wh - 1.0),
        config,
        _simple_eps_inputs(sunlit=True),
        dt_seconds=3600,
        capability=capability,
    )
    assert below_cap.battery.end_energy_wh == capability.battery_usable_capacity_wh
    assert below_cap.battery.end_energy_wh <= capability.battery_usable_capacity_wh

    discharge = compute_eps_interval_transition(
        BatteryState(capability.battery_usable_capacity_wh),
        config,
        _simple_eps_inputs(sunlit=False, load_w=200.0),
        dt_seconds=60,
        capability=capability,
    )
    assert discharge.battery.discharge_output_w == (
        config.battery.max_discharge_output_power_w.value
    )

    nominal = compute_eps_interval_transition(
        BatteryState(250.0),
        config,
        _simple_eps_inputs(sunlit=True, load_w=70.0),
        dt_seconds=60,
    )
    retention_one = compute_eps_interval_transition(
        BatteryState(250.0),
        config,
        _simple_eps_inputs(sunlit=True, load_w=70.0),
        dt_seconds=60,
        capability=compute_eps_capability(
            config,
            DegradationState(
                BatteryDegradationState(1.0, 0.0),
                SolarDegradationState(1.0),
            ),
        ),
    )
    assert retention_one == nominal


def test_solar_limiting_cases_apply_retention_once_before_geometry() -> None:
    config, capability = _demo_eps_and_capability(1.0, 0.6)
    cases = {
        "eclipse": _simple_eps_inputs(sunlit=False),
        "edge": _simple_eps_inputs(sunlit=True, incidence_angle_deg=90.0),
        "back": _simple_eps_inputs(sunlit=True, incidence_angle_deg=120.0),
        "direct": _simple_eps_inputs(sunlit=True, incidence_angle_deg=0.0),
        "sixty": _simple_eps_inputs(sunlit=True, incidence_angle_deg=60.0),
    }
    results = {
        name: compute_eps_interval_transition(
            BatteryState(250.0),
            config,
            inputs,
            dt_seconds=1,
            capability=capability,
        )
        for name, inputs in cases.items()
    }
    retained_nominal_w = 180.0 * 0.6
    assert results["eclipse"].solar.generation_w == 0.0
    assert results["edge"].solar.generation_w == 0.0
    assert results["back"].solar.generation_w == 0.0
    assert results["direct"].solar.nominal_generation_w == retained_nominal_w
    assert results["direct"].solar.generation_w == retained_nominal_w
    assert results["sixty"].solar.generation_w == pytest.approx(
        retained_nominal_w * 0.5
    )
    nominal = compute_eps_interval_transition(
        BatteryState(250.0),
        config,
        cases["sixty"],
        dt_seconds=1,
    )
    retention_one = compute_eps_interval_transition(
        BatteryState(250.0),
        config,
        cases["sixty"],
        dt_seconds=1,
        capability=compute_eps_capability(
            config,
            DegradationState(
                BatteryDegradationState(1.0, 0.0),
                SolarDegradationState(1.0),
            ),
        ),
    )
    assert retention_one == nominal


def _ageing_model(
    *,
    calendar_rate: float,
    cycling_coefficient: float,
    calendar_activation: float = 0.0,
    cycling_activation: float = 0.0,
):
    context = _audit_context(dt_seconds=60, horizon_seconds=60)
    model = context.inputs.spacecraft_configuration.degradation.battery_ageing_model
    return replace(
        model,
        calendar_damage_rate_per_second_at_reference=_parameter_with_value(
            model.calendar_damage_rate_per_second_at_reference,
            calendar_rate,
        ),
        calendar_activation_energy_j_per_mol=_parameter_with_value(
            model.calendar_activation_energy_j_per_mol,
            calendar_activation,
        ),
        cycling_damage_per_normalized_energy_throughput_at_reference=(
            _parameter_with_value(
                model.cycling_damage_per_normalized_energy_throughput_at_reference,
                cycling_coefficient,
            )
        ),
        cycling_activation_energy_j_per_mol=_parameter_with_value(
            model.cycling_activation_energy_j_per_mol,
            cycling_activation,
        ),
    )


def _degradation_transition(
    *,
    calendar_rate: float,
    cycling_coefficient: float,
    temperature_k: float = 300.0,
    throughput_wh: float = 10.0,
):
    context = build_demo_context()
    return compute_battery_degradation_transition(
        BatteryDegradationState(0.9, 100.0),
        context.inputs.spacecraft_configuration.eps.battery,
        _ageing_model(
            calendar_rate=calendar_rate,
            cycling_coefficient=cycling_coefficient,
            calendar_activation=20_000.0,
            cycling_activation=20_000.0,
        ),
        BatteryDegradationIntervalInput(
            temperature_k,
            BatteryThroughputIncrement(0.0, throughput_wh, throughput_wh),
            100,
        ),
    )


def test_degradation_limiting_cases_remain_separate_and_monotonic() -> None:
    zero = _degradation_transition(
        calendar_rate=0.0,
        cycling_coefficient=0.0,
    )
    calendar = _degradation_transition(
        calendar_rate=1.0e-8,
        cycling_coefficient=0.0,
    )
    cycling = _degradation_transition(
        calendar_rate=0.0,
        cycling_coefficient=1.0e-3,
    )
    combined = _degradation_transition(
        calendar_rate=1.0e-8,
        cycling_coefficient=1.0e-3,
    )
    hot = _degradation_transition(
        calendar_rate=1.0e-8,
        cycling_coefficient=1.0e-3,
        temperature_k=310.0,
    )
    cold = _degradation_transition(
        calendar_rate=1.0e-8,
        cycling_coefficient=1.0e-3,
        temperature_k=290.0,
    )
    assert zero.end_usable_capacity_retention == 0.9
    assert zero.end_cumulative_energy_throughput_wh == 110.0
    assert calendar.calendar_damage > 0 and calendar.cycling_damage == 0
    assert cycling.calendar_damage == 0 and cycling.cycling_damage > 0
    assert combined.total_damage == pytest.approx(
        combined.calendar_damage + combined.cycling_damage
    )
    assert hot.calendar_temperature_acceleration > 1
    assert hot.cycling_temperature_acceleration > 1
    assert 0 < cold.calendar_temperature_acceleration < 1
    assert 0 < cold.cycling_temperature_acceleration < 1
    assert all(
        transition.end_usable_capacity_retention > 0
        for transition in (zero, calendar, cycling, combined, hot, cold)
    )

    with pytest.raises(ValueError, match="candidate retention"):
        compute_battery_degradation_transition(
            BatteryDegradationState(1.0e-6, 100.0),
            build_demo_context().inputs.spacecraft_configuration.eps.battery,
            _ageing_model(calendar_rate=1.0e-3, cycling_coefficient=0.0),
            BatteryDegradationIntervalInput(
                300.0,
                BatteryThroughputIncrement(0.0, 0.0, 0.0),
                1,
            ),
        )


def test_capacity_reconciliation_release_branches_are_explicit() -> None:
    battery = build_demo_context().inputs.spacecraft_configuration.eps.battery
    below = compute_battery_capacity_reconciliation(390.0, battery, 0.8)
    equal = compute_battery_capacity_reconciliation(400.0, battery, 0.8)
    above = compute_battery_capacity_reconciliation(410.0, battery, 0.8)
    assert below.unavailable_energy_wh == 0.0
    assert below.authoritative_end_energy_wh == 390.0
    assert equal.unavailable_energy_wh == 0.0
    assert equal.authoritative_end_energy_wh == 400.0
    assert above.unavailable_energy_wh == 10.0
    assert above.authoritative_end_energy_wh == 400.0


def test_integrated_reconciliation_is_distinct_from_eps_and_thermal_ledgers() -> None:
    baseline = _audit_context(
        dt_seconds=60,
        horizon_seconds=60,
        battery_retention=0.8,
        solar_retention=0.88,
        battery_energy_wh=390.0,
        calendar_rate=0.0,
        calendar_activation_energy=0.0,
        cycling_coefficient=0.0,
        cycling_activation_energy=0.0,
    )
    reconciled = _audit_context(
        dt_seconds=60,
        horizon_seconds=60,
        battery_retention=0.8,
        solar_retention=0.88,
        battery_energy_wh=390.0,
        calendar_rate=4.0e-4,
        calendar_activation_energy=0.0,
        cycling_coefficient=0.0,
        cycling_activation_energy=0.0,
    )
    arguments = _inputs_at(0)
    baseline_result = SimulationEngine().step(
        baseline,
        eps_inputs=arguments[0],
        thermal_inputs=arguments[1],
        heat_source_inputs=arguments[2],
    )
    reconciled_result = SimulationEngine().step(
        reconciled,
        eps_inputs=arguments[0],
        thermal_inputs=arguments[1],
        heat_source_inputs=arguments[2],
    )
    baseline_reconciliation = (
        baseline_result.battery_capacity_reconciliation_result
    )
    reconciliation = reconciled_result.battery_capacity_reconciliation_result
    assert baseline_reconciliation is not None
    assert reconciliation is not None
    assert baseline_reconciliation.unavailable_energy_wh == 0.0
    assert reconciliation.unavailable_energy_wh > 0
    assert reconciled_result.eps_result == baseline_result.eps_result
    assert reconciled_result.thermal_coupling_result == (
        baseline_result.thermal_coupling_result
    )
    assert reconciled_result.eps_result is not None
    assert reconciled_result.eps_result.battery.end_energy_wh - (
        reconciled.spacecraft_state.battery.energy_wh
    ) == pytest.approx(reconciliation.unavailable_energy_wh)
    assert compute_eps_conservation_report(
        reconciled_result.eps_result
    ).is_within_tolerance(
        EPS_ENERGY_TOLERANCE_WH,
        absolute_power_tolerance_w=EPS_POWER_TOLERANCE_W,
    )


def test_six_hour_integrated_run_is_finite_bounded_and_monotonic(long_run) -> None:
    assert len(long_run.results) == 360
    assert long_run.context.simulation_time_seconds == LONG_RUN_SECONDS
    assert long_run.context.diagnostics.completed_steps == 360
    assert 0 <= long_run.min_battery_energy_wh <= long_run.max_battery_energy_wh
    assert 0 < long_run.min_temperature_k <= long_run.max_temperature_k
    assert long_run.min_usable_capacity_margin_wh > 0
    assert long_run.max_eps_energy_residual_wh <= EPS_ENERGY_TOLERANCE_WH
    assert long_run.max_thermal_ledger_residual <= REPRESENTATION_TOLERANCE


def test_deterministic_replay_matches_every_step_and_final_context() -> None:
    first = _run_integrated(
        _audit_context(dt_seconds=60, horizon_seconds=CONVERGENCE_HORIZON_SECONDS)
    )
    second = _run_integrated(
        _audit_context(dt_seconds=60, horizon_seconds=CONVERGENCE_HORIZON_SECONDS)
    )
    assert first.results == second.results
    assert first.context == second.context


def test_schema_four_json_restart_matches_uninterrupted_long_run() -> None:
    direct_context = _audit_context(
        dt_seconds=60,
        horizon_seconds=LONG_RUN_SECONDS,
    )
    split_context = _audit_context(
        dt_seconds=60,
        horizon_seconds=LONG_RUN_SECONDS,
    )
    direct = _run_integrated(direct_context)
    engine = SimulationEngine()
    split_steps = 137
    for _ in range(split_steps):
        inputs = _inputs_at(split_context.simulation_time_seconds)
        engine.step(
            split_context,
            eps_inputs=inputs[0],
            thermal_inputs=inputs[1],
            heat_source_inputs=inputs[2],
        )
    checkpoint = CheckpointState.from_context(split_context)
    payload = checkpoint.to_dict()
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    restored = CheckpointState.from_dict(json.loads(encoded)).restore(
        split_context.inputs
    )
    restarted = _run_integrated(restored)
    assert checkpoint.schema_version == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    serialized = encoded.lower()
    for transient_name in (
        "eps_result",
        "eps_capability_result",
        "battery_capacity_reconciliation_result",
        "thermal_coupling_result",
    ):
        assert transient_name not in serialized
    assert restarted.context.spacecraft_state.battery == (
        direct.context.spacecraft_state.battery
    )
    assert restarted.context.spacecraft_state.thermal == (
        direct.context.spacecraft_state.thermal
    )
    assert restarted.context.spacecraft_state.degradation == (
        direct.context.spacecraft_state.degradation
    )
    assert restarted.context.spacecraft_state.propulsion == (
        direct.context.spacecraft_state.propulsion
    )
    assert restarted.context.spacecraft_state.onboard == (
        direct.context.spacecraft_state.onboard
    )
    assert restarted.context.mission_state == direct.context.mission_state
    assert restarted.context.controller_state == direct.context.controller_state
    assert restarted.context.diagnostics == direct.context.diagnostics
    assert restarted.context.simulation_time_seconds == (
        direct.context.simulation_time_seconds
    )


def _dangerous_thermal_context():
    context = _audit_context(dt_seconds=60, horizon_seconds=60)
    spacecraft = context.inputs.spacecraft_configuration
    network = spacecraft.thermal.network
    nodes = []
    for node in network.nodes:
        if node.node_id == ThermalNodeId("battery"):
            node = replace(
                node,
                heat_capacity_j_per_k=_parameter_with_value(
                    node.heat_capacity_j_per_k, 1.0
                ),
                emissivity=_parameter_with_value(node.emissivity, 1.0),
                radiating_area_m2=_parameter_with_value(
                    node.radiating_area_m2, 1000.0
                ),
            )
        nodes.append(node)
    network = replace(network, nodes=tuple(nodes))
    spacecraft = replace(
        spacecraft,
        thermal=replace(spacecraft.thermal, network=network),
    )
    context.inputs = replace(
        context.inputs,
        spacecraft_configuration=spacecraft,
    )
    eps_inputs, _, sources = _inputs_at(0)
    thermal_inputs = ThermalIntervalInputs(
        (
            ThermalNodeBoundaryInput(ThermalNodeId("bus"), 300.0),
            ThermalNodeBoundaryInput(ThermalNodeId("battery"), 1.0),
            ThermalNodeBoundaryInput(ThermalNodeId("payload"), 300.0),
        )
    )
    return context, {
        "eps_inputs": eps_inputs,
        "thermal_inputs": thermal_inputs,
        "heat_source_inputs": sources,
    }


def _failure_case(case: str):
    if case == "horizon-crossing":
        return _audit_context(dt_seconds=60, horizon_seconds=30), {}
    if case == "partial-coupling":
        context = _audit_context(dt_seconds=60, horizon_seconds=60)
        eps_inputs, thermal_inputs, _ = _inputs_at(0)
        return context, {
            "eps_inputs": eps_inputs,
            "thermal_inputs": thermal_inputs,
        }
    if case == "energy-above-capacity":
        context = _audit_context(
            dt_seconds=60,
            horizon_seconds=60,
            battery_retention=0.5,
            battery_energy_wh=260.0,
        )
        return context, {"eps_inputs": _inputs_at(0)[0]}
    if case == "thermal-endpoint":
        return _dangerous_thermal_context()
    if case == "battery-degradation-endpoint":
        context = _audit_context(
            dt_seconds=60,
            horizon_seconds=60,
            battery_retention=0.2,
            battery_energy_wh=50.0,
            calendar_rate=0.01,
            calendar_activation_energy=0.0,
            cycling_coefficient=0.0,
            cycling_activation_energy=0.0,
        )
        eps_inputs, thermal_inputs, sources = _inputs_at(0)
        return context, {
            "eps_inputs": eps_inputs,
            "thermal_inputs": thermal_inputs,
            "heat_source_inputs": sources,
        }
    if case == "solar-degradation-endpoint":
        context = _audit_context(dt_seconds=60, horizon_seconds=60)
        eps_inputs, thermal_inputs, sources = _inputs_at(0)
        return context, {
            "eps_inputs": eps_inputs,
            "thermal_inputs": thermal_inputs,
            "heat_source_inputs": sources,
            "solar_degradation_forcing": SolarDegradationForcingInput(0.88),
        }
    raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    (
        "horizon-crossing",
        "partial-coupling",
        "energy-above-capacity",
        "thermal-endpoint",
        "battery-degradation-endpoint",
        "solar-degradation-endpoint",
    ),
)
def test_transactional_failure_matrix_preserves_state_and_identity(case) -> None:
    context, arguments = _failure_case(case)
    before = CheckpointState.from_context(context)
    references = _mutable_references(context)
    time_before = context.simulation_time_seconds
    completed_before = context.diagnostics.completed_steps
    with pytest.raises(ValueError):
        SimulationEngine().step(context, **arguments)
    assert CheckpointState.from_context(context) == before
    assert context.simulation_time_seconds == time_before
    assert context.diagnostics.completed_steps == completed_before
    assert all(
        current is original
        for current, original in zip(_mutable_references(context), references)
    )


def test_battery_degradation_endpoint_changes_capability_next_interval_only() -> None:
    context = _audit_context(
        dt_seconds=60,
        horizon_seconds=120,
        calendar_rate=1.0e-5,
        calendar_activation_energy=0.0,
        cycling_coefficient=0.0,
        cycling_activation_energy=0.0,
    )
    zero_damage = _audit_context(
        dt_seconds=60,
        horizon_seconds=60,
        calendar_rate=0.0,
        calendar_activation_energy=0.0,
        cycling_coefficient=0.0,
        cycling_activation_energy=0.0,
    )
    inputs = _inputs_at(0)
    first = SimulationEngine().step(
        context,
        eps_inputs=inputs[0],
        thermal_inputs=inputs[1],
        heat_source_inputs=inputs[2],
    )
    control = SimulationEngine().step(
        zero_damage,
        eps_inputs=inputs[0],
        thermal_inputs=inputs[1],
        heat_source_inputs=inputs[2],
    )
    assert first.eps_capability_result is not None
    assert first.battery_degradation_result is not None
    assert first.eps_capability_result.battery_capacity_retention == 0.92
    assert first.eps_result == control.eps_result
    assert first.thermal_coupling_result == control.thermal_coupling_result
    endpoint_retention = (
        first.battery_degradation_result.end_usable_capacity_retention
    )
    second_inputs = _inputs_at(context.simulation_time_seconds)
    second = SimulationEngine().step(
        context,
        eps_inputs=second_inputs[0],
        thermal_inputs=second_inputs[1],
        heat_source_inputs=second_inputs[2],
    )
    assert second.eps_capability_result is not None
    assert second.eps_capability_result.battery_capacity_retention == (
        endpoint_retention
    )


def test_solar_degradation_endpoint_changes_capability_next_interval_only() -> None:
    context = _audit_context(
        dt_seconds=60,
        horizon_seconds=120,
        calendar_rate=0.0,
        calendar_activation_energy=0.0,
        cycling_coefficient=0.0,
        cycling_activation_energy=0.0,
    )
    inputs = _inputs_at(0)
    first = SimulationEngine().step(
        context,
        eps_inputs=inputs[0],
        thermal_inputs=inputs[1],
        heat_source_inputs=inputs[2],
        solar_degradation_forcing=SolarDegradationForcingInput(0.08),
    )
    assert first.eps_capability_result is not None
    assert first.solar_degradation_result is not None
    assert first.eps_capability_result.solar_generation_retention == 0.88
    assert first.eps_result is not None
    assert first.eps_result.solar.nominal_generation_w == 180.0 * 0.88
    endpoint_retention = first.solar_degradation_result.end_generation_retention
    next_inputs = _inputs_at(context.simulation_time_seconds)
    second = SimulationEngine().step(
        context,
        eps_inputs=next_inputs[0],
        thermal_inputs=next_inputs[1],
        heat_source_inputs=next_inputs[2],
    )
    assert second.eps_capability_result is not None
    assert second.eps_capability_result.solar_generation_retention == (
        endpoint_retention
    )
    assert second.eps_result is not None
    assert second.eps_result.solar.nominal_generation_w == (
        180.0 * endpoint_retention
    )


def test_public_composition_integrity_and_single_ownership_are_preserved() -> None:
    config, capability = _demo_eps_and_capability(0.8, 0.6)
    mismatched = replace(capability, battery_usable_capacity_wh=399.0)
    with pytest.raises(ValueError, match="battery_usable_capacity_wh"):
        compute_eps_interval_transition(
            BatteryState(250.0),
            config,
            _simple_eps_inputs(sunlit=True),
            dt_seconds=60,
            capability=mismatched,
        )
    other_config = replace(
        config,
        battery=replace(
            config.battery,
            nominal_energy_wh=_parameter_with_value(
                config.battery.nominal_energy_wh,
                600.0,
            ),
        ),
    )
    other_capability = compute_eps_capability(
        other_config,
        DegradationState(
            BatteryDegradationState(0.8, 0.0),
            SolarDegradationState(0.6),
        ),
    )
    with pytest.raises(ValueError, match="battery_usable_capacity_wh"):
        compute_eps_interval_transition(
            BatteryState(250.0),
            config,
            _simple_eps_inputs(sunlit=True),
            dt_seconds=60,
            capability=other_capability,
        )

    engine_source = ENGINE_PATH.read_text(encoding="utf-8")
    engine_tree = ast.parse(engine_source, filename=str(ENGINE_PATH))
    eps_system_source = EPS_SYSTEM_PATH.read_text(encoding="utf-8")
    eps_system_tree = ast.parse(eps_system_source, filename=str(EPS_SYSTEM_PATH))
    engine_calls = [
        node.func.id
        for node in ast.walk(engine_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    eps_system_calls = [
        node.func.id
        for node in ast.walk(eps_system_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert engine_calls.count("compute_eps_capability") == 1
    assert engine_calls.count("compute_battery_degradation_transition") == 1
    assert eps_system_calls.count("validate_eps_capability_for_config") == 1
    assert "nominal_energy_wh.value *" not in engine_source
    assert "nominal_generation_w.value *" not in engine_source
    assert "8.31446261815324" not in engine_source
    assert "5.670374419" not in engine_source
    assert "exp(" not in engine_source


def test_numeric_adversarial_supported_reals_remain_finite_and_numpy_free() -> None:
    config = build_demo_context().inputs.spacecraft_configuration.eps
    numpy_capability = compute_eps_capability(
        config,
        DegradationState(
            BatteryDegradationState(np.float64(0.8), np.int64(0)),
            SolarDegradationState(np.float64(0.6)),
        ),
    )
    assert numpy_capability.battery_usable_capacity_wh == 400.0
    assert numpy_capability.solar_nominal_generation_capability_w == 108.0
    assert all(
        type(value) in {int, float} and isfinite(value)
        for value in (
            numpy_capability.battery_usable_capacity_wh,
            numpy_capability.solar_nominal_generation_capability_w,
        )
    )

    tiny = compute_eps_capability(
        config,
        DegradationState(
            BatteryDegradationState(1.0e-200, 0.0),
            SolarDegradationState(1.0e-200),
        ),
    )
    assert 0 < tiny.battery_usable_capacity_wh < 1.0e-190
    assert 0 < tiny.solar_nominal_generation_capability_w < 1.0e-190

    large_config = replace(
        config,
        battery=replace(
            config.battery,
            nominal_energy_wh=_parameter_with_value(
                config.battery.nominal_energy_wh, 1.0e200
            ),
        ),
        solar_array=replace(
            config.solar_array,
            nominal_generation_w=_parameter_with_value(
                config.solar_array.nominal_generation_w, 1.0e200
            ),
        ),
    )
    large = compute_eps_capability(
        large_config,
        DegradationState(
            BatteryDegradationState(0.5, 0.0),
            SolarDegradationState(0.5),
        ),
    )
    assert large.battery_usable_capacity_wh == 5.0e199
    assert large.solar_nominal_generation_capability_w == 5.0e199
    for path in ROOT.joinpath("ops_sim", "v5").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            alias.name.partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert "numpy" not in imports


@pytest.mark.parametrize(
    ("invalid", "error_type"),
    (
        (True, TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (float("-inf"), ValueError),
    ),
)
def test_numeric_adversarial_invalid_reals_fail_intentionally(
    invalid, error_type
) -> None:
    with pytest.raises(error_type):
        EPSCapabilityResult(invalid, 1.0, 1.0, 1.0)


def test_numeric_adversarial_underflow_and_overflow_fail_intentionally() -> None:
    context = build_demo_context()
    config = context.inputs.spacecraft_configuration.eps
    smallest = float.fromhex("0x0.0000000000001p-1022")
    underflow_config = replace(
        config,
        battery=replace(
            config.battery,
            nominal_energy_wh=_parameter_with_value(
                config.battery.nominal_energy_wh, smallest
            ),
        ),
    )
    with pytest.raises(ValueError, match="nonzero product"):
        compute_eps_capability(
            underflow_config,
            DegradationState(
                BatteryDegradationState(0.5, 0.0),
                SolarDegradationState(1.0),
            ),
        )
    with pytest.raises(ValueError, match="nonzero product"):
        compute_battery_degradation_transition(
            BatteryDegradationState(0.9, 0.0),
            config.battery,
            _ageing_model(
                calendar_rate=0.0,
                cycling_coefficient=smallest,
            ),
            BatteryDegradationIntervalInput(
                300.0,
                BatteryThroughputIncrement(0.0, 250.0, 250.0),
                1,
            ),
        )
    overflow_state = ThermalState(
        (
            ThermalNodeState(ThermalNodeId("bus"), 1.0e100),
            ThermalNodeState(ThermalNodeId("battery"), 300.0),
            ThermalNodeState(ThermalNodeId("payload"), 300.0),
        )
    )
    radiating_network = build_demo_context().inputs.spacecraft_configuration.thermal.network
    inputs = ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(ThermalNodeId(name), 300.0)
            for name in NODE_NAMES
        )
    )
    with pytest.raises(ValueError, match="fourth power|finite"):
        compute_thermal_interval_transition(
            overflow_state,
            radiating_network,
            inputs,
            dt_seconds=1,
        )


def test_public_numeric_integer_and_float_battery_inputs_remain_supported() -> None:
    config = build_demo_context().inputs.spacecraft_configuration.eps.battery
    integer = compute_battery_transition(
        BatteryState(100),
        config,
        generation_w=100,
        load_w=50,
        dt_seconds=60,
    )
    floating = compute_battery_transition(
        BatteryState(100.0),
        config,
        generation_w=100.0,
        load_w=50.0,
        dt_seconds=60,
    )
    assert integer == floating


def test_scientific_claims_preserve_level_one_limitations() -> None:
    readme = README_PATH.read_text(encoding="utf-8").lower()
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8").lower()
    audit = RELEASE_AUDIT_PATH.read_text(encoding="utf-8").lower()
    combined = " ".join("\n".join((readme, sources, audit)).split())
    normalized_audit = " ".join(audit.split())
    for phrase in (
        "not flight software",
        "not telemetry replay",
        "not a kazeosat-1 digital twin",
        "chemistry-specific",
        "no automatic",
        "power fade",
        "reversible entropic heat",
    ):
        assert phrase in combined
    assert "does not provide" in normalized_audit
    assert "orbit-derived thermal environment" in normalized_audit
    assert "externally validated" not in normalized_audit
    assert "universal accepted timestep" not in normalized_audit
    assert "v5.8" in normalized_audit


def test_source_register_preserves_public_value_conflicts() -> None:
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s001 = sources.partition("### S001 ")[2].partition("### S002 ")[0]
    for pair in (
        ("830 kg", "820 kg"),
        ("7.25", "7 years"),
        ("228,000 km", "220,000 km"),
        ("1200 W", "does not provide"),
    ):
        assert pair[0] in s001 and pair[1] in s001
    assert "productivity" in s001.lower()
    assert "conflict" in s001.lower()


def test_committed_e2_demo_remains_deterministic_and_explicit() -> None:
    first_output = StringIO()
    second_output = StringIO()
    first = run_demo(stream=first_output)
    second = run_demo(stream=second_output)
    assert first == second
    assert first_output.getvalue() == second_output.getvalue()
    assert len(first) == 16
    assert first[0].battery_energy_wh == pytest.approx(251.68666666666667)
    assert first[-1].time_s == 960
    assert all(row.unmet_load_w == 0.0 for row in first)
    output = first_output.getvalue().lower()
    for phrase in (
        "synthetic",
        "reduced-order model",
        "not flight software",
        "not telemetry replay",
        "not a kazeosat-1 digital twin",
        "explicitly supplied, not orbit-derived",
        "zero-damage coefficients",
        "throughput history still accumulates",
    ):
        assert phrase in output

    context = build_demo_context()
    retention = (
        context.spacecraft_state.degradation.battery
        .usable_capacity_retention
    )
    throughput = (
        context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
    )
    for step_index in range(16):
        inputs = build_step_inputs(step_index)
        SimulationEngine().step(
            context,
            eps_inputs=inputs[0],
            thermal_inputs=inputs[1],
            heat_source_inputs=inputs[2],
        )
    assert (
        context.spacecraft_state.degradation.battery
        .usable_capacity_retention
        == retention
    )
    assert (
        context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
        > throughput
    )


def test_f2_decisions_source_notes_and_release_audit_are_complete() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    audit = RELEASE_AUDIT_PATH.read_text(encoding="utf-8")
    normalized_sources = " ".join(sources.lower().split())
    for number in range(149, 157):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D148 ") < decisions.index("## D149 ")
    for phrase in (
        "timestep refinement",
        "numerical verification",
        "explicit Euler",
        "adds no new source",
        "V5.8",
    ):
        assert phrase.lower() in normalized_sources
    for phrase in (
        "6b7aae05afe5a852c41496fca5cf27010808bf0f",
        "3840",
        "120 s",
        "60 s",
        "30 s",
        "15 s",
        "two-node",
        "6 h",
        "schema 3",
        "rollback",
        "V5.8",
    ):
        assert phrase.lower() in audit.lower()
