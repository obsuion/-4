"""Integrated repeated-run and demonstration hardening for V5.2F1."""

import ast
from io import StringIO
import json
from math import isfinite
from pathlib import Path

import pytest

from examples.v52_integrated_eps_thermal_demo import (
    DEFAULT_DEMO_STEPS,
    TIMESTEP_SECONDS,
    build_demo_context,
    build_step_inputs,
    run_demo,
)
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.eps_validation import compute_eps_conservation_report
from ops_sim.v5.state import BatteryDegradationState, SolarDegradationState
from ops_sim.v5.thermal import ThermalIntervalInputs


ROOT = Path(__file__).resolve().parents[1]
DEMO_PATH = ROOT / "examples" / "v52_integrated_eps_thermal_demo.py"
README_PATH = ROOT / "README.md"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
REPEATED_STEPS = 24
ENERGY_TOLERANCE_WH = 1.0e-12
POWER_TOLERANCE_W = 1.0e-12


def _run_steps(context, start_step: int, step_count: int):
    engine = SimulationEngine()
    results = []
    for step_index in range(start_step, start_step + step_count):
        eps_inputs, thermal_inputs, heat_source_inputs = build_step_inputs(
            step_index
        )
        results.append(
            engine.step(
                context,
                eps_inputs=eps_inputs,
                thermal_inputs=thermal_inputs,
                heat_source_inputs=heat_source_inputs,
            )
        )
    return tuple(results)


def _assert_integrated_result_is_sane(context, result) -> None:
    eps_result = result.eps_result
    coupling_result = result.thermal_coupling_result
    assert eps_result is not None
    assert coupling_result is not None

    capacity_wh = (
        context.inputs.spacecraft_configuration.eps.battery
        .nominal_energy_wh.value
    )
    battery_energy_wh = context.spacecraft_state.battery.energy_wh
    assert isfinite(battery_energy_wh)
    assert 0 <= battery_energy_wh <= capacity_wh
    assert isfinite(eps_result.battery.conversion_loss_wh)
    assert eps_result.battery.conversion_loss_wh >= 0

    report = compute_eps_conservation_report(eps_result)
    assert report.is_within_tolerance(
        ENERGY_TOLERANCE_WH,
        absolute_power_tolerance_w=POWER_TOLERANCE_W,
    )

    for node_state in context.spacecraft_state.thermal.node_states:
        assert isfinite(node_state.temperature_k)
        assert node_state.temperature_k > 0

    dt_seconds = coupling_result.thermal_result.dt_seconds
    assert dt_seconds == result.dt_seconds == TIMESTEP_SECONDS
    for transition in coupling_result.thermal_result.node_transitions:
        assert transition.net_heat_into_w == pytest.approx(
            transition.conductive_heat_into_w
            + transition.radiative_heat_into_w
            + transition.applied_heat_into_w
        )
        assert transition.thermal_energy_change_j == pytest.approx(
            transition.net_heat_into_w * dt_seconds
        )


def test_demo_fixture_is_synthetic_public_and_physically_explicit() -> None:
    context = build_demo_context()
    config = context.inputs.spacecraft_configuration
    network = config.thermal.network
    source = DEMO_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DEMO_PATH))

    assert len(network.nodes) == 3
    assert len(network.links) == 2
    assert all(node.emissivity.value > 0 for node in network.nodes)
    assert all(node.radiating_area_m2.value > 0 for node in network.nodes)
    assert context.spacecraft_state.degradation.battery == (
        BatteryDegradationState(1.0, 0.0)
    )
    assert context.spacecraft_state.degradation.solar == (
        SolarDegradationState(1.0)
    )
    assert "random" not in source
    assert "pandas" not in source
    assert "thermal_routing" not in source
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "ops_sim.v5"
        ):
            assert all(not alias.name.startswith("_") for alias in node.names)


def test_twenty_four_coupled_steps_remain_valid_conserved_and_stale() -> None:
    context = build_demo_context()
    engine = SimulationEngine()
    retention_before = (
        context.spacecraft_state.degradation.battery
        .usable_capacity_retention
    )
    throughput_before = (
        context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
    )
    solar_before = context.spacecraft_state.degradation.solar.generation_retention
    telemetry_before = context.ground_knowledge_state.latest_telemetry
    assert telemetry_before is not None

    for step_index in range(REPEATED_STEPS):
        eps_inputs, thermal_inputs, heat_source_inputs = build_step_inputs(
            step_index
        )
        result = engine.step(
            context,
            eps_inputs=eps_inputs,
            thermal_inputs=thermal_inputs,
            heat_source_inputs=heat_source_inputs,
        )
        _assert_integrated_result_is_sane(context, result)
        assert result.battery_degradation_result is not None
        assert result.solar_degradation_result is None
        assert (
            context.spacecraft_state.degradation.battery
            .usable_capacity_retention
            == retention_before
        )
        current_throughput = (
            context.spacecraft_state.degradation.battery
            .cumulative_energy_throughput_wh
        )
        assert current_throughput > throughput_before
        throughput_before = current_throughput
        assert (
            context.spacecraft_state.degradation.solar.generation_retention
            == solar_before
        )
        assert context.ground_knowledge_state.latest_telemetry is (
            telemetry_before
        )
        assert telemetry_before.battery_energy_wh == 250.0

    assert context.simulation_time_seconds == (
        REPEATED_STEPS * TIMESTEP_SECONDS
    )
    assert context.diagnostics.completed_steps == REPEATED_STEPS


def test_deterministic_replay_matches_every_result_and_final_context() -> None:
    first = build_demo_context()
    second = build_demo_context()

    first_results = _run_steps(first, 0, REPEATED_STEPS)
    second_results = _run_steps(second, 0, REPEATED_STEPS)

    assert first_results == second_results
    assert first == second


def test_checkpoint_continuation_matches_uninterrupted_execution() -> None:
    direct = build_demo_context()
    split = build_demo_context()
    split_step = 9

    _run_steps(direct, 0, REPEATED_STEPS)
    _run_steps(split, 0, split_step)
    checkpoint = CheckpointState.from_context(split)
    restored = checkpoint.restore(split.inputs)
    _run_steps(restored, split_step, REPEATED_STEPS - split_step)

    assert restored == direct


def test_schema_four_json_restart_matches_uninterrupted_execution() -> None:
    direct = build_demo_context()
    split = build_demo_context()
    split_step = 11

    _run_steps(direct, 0, REPEATED_STEPS)
    _run_steps(split, 0, split_step)
    checkpoint = CheckpointState.from_context(split)
    assert checkpoint.schema_version == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    encoded = json.dumps(checkpoint.to_dict(), allow_nan=False, sort_keys=True)
    parsed = CheckpointState.from_dict(json.loads(encoded))
    restored = parsed.restore(split.inputs)
    _run_steps(restored, split_step, REPEATED_STEPS - split_step)

    assert restored == direct


def test_checkpoint_continuation_has_no_mutable_physical_aliases() -> None:
    context = build_demo_context()
    _run_steps(context, 0, 5)

    restored = CheckpointState.from_context(context).restore(context.inputs)
    _run_steps(restored, 5, 1)

    assert restored.spacecraft_state is not context.spacecraft_state
    assert restored.spacecraft_state.battery is not (
        context.spacecraft_state.battery
    )
    assert restored.spacecraft_state.thermal is not (
        context.spacecraft_state.thermal
    )
    assert restored.spacecraft_state.data_storage is not (
        context.spacecraft_state.data_storage
    )
    assert all(
        restored_node is not original_node
        for restored_node, original_node in zip(
            restored.spacecraft_state.thermal.node_states,
            context.spacecraft_state.thermal.node_states,
        )
    )
    assert restored.spacecraft_state.degradation is not (
        context.spacecraft_state.degradation
    )
    assert restored.spacecraft_state.degradation.battery is not (
        context.spacecraft_state.degradation.battery
    )
    assert restored.spacecraft_state.degradation.solar is not (
        context.spacecraft_state.degradation.solar
    )


def test_invalid_later_thermal_interval_rolls_back_last_valid_context() -> None:
    context = build_demo_context()
    successful_steps = 7
    _run_steps(context, 0, successful_steps)
    checkpoint = CheckpointState.from_context(context)
    references = (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.thermal,
        *context.spacecraft_state.thermal.node_states,
        context.spacecraft_state.degradation,
        context.spacecraft_state.degradation.battery,
        context.spacecraft_state.degradation.solar,
        context.spacecraft_state.data_storage,
        context.diagnostics,
    )
    eps_inputs, thermal_inputs, heat_source_inputs = build_step_inputs(
        successful_steps
    )
    invalid_thermal_inputs = ThermalIntervalInputs(
        thermal_inputs.node_boundaries[:-1]
    )

    with pytest.raises(ValueError, match="exactly match"):
        SimulationEngine().step(
            context,
            eps_inputs=eps_inputs,
            thermal_inputs=invalid_thermal_inputs,
            heat_source_inputs=heat_source_inputs,
        )

    assert CheckpointState.from_context(context) == checkpoint
    assert (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.thermal,
        *context.spacecraft_state.thermal.node_states,
        context.spacecraft_state.degradation,
        context.spacecraft_state.degradation.battery,
        context.spacecraft_state.degradation.solar,
        context.spacecraft_state.data_storage,
        context.diagnostics,
    ) == references


def test_demo_callable_prints_deterministic_rows_and_disclaimers() -> None:
    first_output = StringIO()
    second_output = StringIO()

    first_rows = run_demo(steps=DEFAULT_DEMO_STEPS, stream=first_output)
    second_rows = run_demo(steps=DEFAULT_DEMO_STEPS, stream=second_output)

    assert len(first_rows) == DEFAULT_DEMO_STEPS == 16
    assert first_rows == second_rows
    assert first_output.getvalue() == second_output.getvalue()
    output = first_output.getvalue()
    for heading in (
        "step",
        "time_s",
        "sunlit",
        "load_W",
        "solar_generation_W",
        "battery_energy_Wh",
        "battery_conversion_loss_Wh",
        "bus_temperature_K",
        "battery_temperature_K",
        "payload_temperature_K",
    ):
        assert heading in output
    disclaimer = output.lower()
    assert "synthetic" in disclaimer
    assert "reduced-order model" in disclaimer
    assert "not flight software" in disclaimer
    assert "not telemetry replay" in disclaimer
    assert "not a kazeosat-1 digital twin" in disclaimer
    assert "explicitly supplied, not orbit-derived" in disclaimer
    assert "zero-damage coefficients" in disclaimer
    assert "throughput history still accumulates" in disclaimer


def test_f1_readme_and_decisions_are_concise_and_exact() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")

    assert readme.count("## V5 integrated demonstration") == 1
    assert "python examples/v52_integrated_eps_thermal_demo.py" in readme
    for number in range(119, 123):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D118 ") < decisions.index("## D119 ")
