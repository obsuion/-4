"""Versioned physical action identity, no-prefix denial and JSON-only restart."""

from copy import deepcopy
from dataclasses import replace
import json
import os
import subprocess
import sys

import pytest

from examples import v5_coupled_downlink_demo as demo
from examples import v5_experiment_bundle_demo as legacy
import ops_sim.v5.continuation as continuation
from ops_sim.v5.continuation import (
    ContinuationElectricalDenial, ContinuationState, CoupledDownlinkAction,
    DownlinkAction, advance_continuation,
)
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content, canonical_copy, check_schema_coverage


@pytest.fixture(scope="module")
def trajectory():
    states = [demo.build_demo_state()]
    for _ in states[0].program.actions:
        states.append(advance_continuation(states[-1]))
    return states


@pytest.mark.parametrize("boundary", [0, 1, 2, 3, 4, 5, 6])
def test_fresh_process_restore_uses_only_json_and_replays_all_domains(tmp_path, trajectory, boundary):
    state = trajectory[boundary]
    if boundary in (2, 3, 5):
        assert state.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits == 9000.0
    saved, output = tmp_path / "saved.json", tmp_path / "resumed.json"
    saved.write_text(create_bundle(state, repository_root=demo.ROOT).to_json(), encoding="utf-8")
    code = "\n".join([
        "import sys",
        "from examples import v5_coupled_downlink_demo as demo",
        "def forbidden(): raise AssertionError('origin fixture called on restart')",
        "demo.build_demo_state = forbidden",
        "demo.legacy.build_demo_state = forbidden",
        "demo.main(['--resume', sys.argv[1], '--output', sys.argv[2]])",
    ])
    run = subprocess.run([sys.executable, "-B", "-c", code, str(saved), str(output)],
        cwd=demo.ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"},
        text=True, encoding="utf-8", capture_output=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == legacy.summarize(trajectory[-1])
    final = trajectory[-1].context
    assert final.simulation_time_seconds == 238 and final.diagnostics.completed_steps == 6
    assert len(final.ground_data_delivery_state.completed_deliveries) == 2
    assert final.spacecraft_state.degradation.battery.usable_capacity_retention < 0.9
    assert final.spacecraft_state.degradation.battery.cumulative_energy_throughput_wh > 0
    assert final.spacecraft_state.degradation.solar.generation_retention < 0.8
    assert final.ground_knowledge_state == trajectory[0].context.ground_knowledge_state


def test_coupled_steps_evolve_physics_without_changing_immutable_identity(trajectory):
    digests = {experiment_input_digest(s.context.inputs, s.program) for s in trajectory}
    assert len(digests) == 1
    for end in (2, 4, 5, 6):
        before, after = trajectory[end-1].context, trajectory[end].context
        assert before.spacecraft_state.battery != after.spacecraft_state.battery
        assert before.spacecraft_state.thermal != after.spacecraft_state.thermal
        assert before.spacecraft_state.degradation != after.spacecraft_state.degradation
        assert after.simulation_time_seconds == before.simulation_time_seconds + 23
        assert after.diagnostics.completed_steps == before.diagnostics.completed_steps + 1


@pytest.mark.parametrize("change", ["power", "provenance", "baseline", "sunlit", "incidence", "routing", "boundary", "external", "solar-ageing", "battery-ageing"])
def test_every_causal_forcing_and_parameter_is_content_bound(trajectory, change):
    state = trajectory[2]
    bundle = create_bundle(state, repository_root=demo.ROOT)
    program, inputs = state.program, state.context.inputs
    action = program.actions[1]
    physical = action.physical_inputs
    if change == "power":
        physical = replace(physical, transmitter=replace(physical.transmitter,
            electrical_power_w=replace(physical.transmitter.electrical_power_w, value=37.0)))
    elif change == "provenance":
        power = physical.transmitter.electrical_power_w
        physical = replace(physical, transmitter=replace(physical.transmitter,
            electrical_power_w=replace(power, provenance=replace(power.provenance, rationale="Different explicit test assumption."))))
    elif change == "baseline": physical = replace(physical, baseline_loads=replace(physical.baseline_loads, obc_w=4.0))
    elif change == "sunlit": physical = replace(physical, sunlit=False)
    elif change == "incidence": physical = replace(physical, incidence_angle_deg=30.0)
    elif change == "routing":
        first, *rest = physical.routing_config.routes
        physical = replace(physical, routing_config=replace(physical.routing_config, routes=(
            replace(first, retained_heat_fraction=replace(first.retained_heat_fraction, value=0.25)), *rest)))
    elif change == "boundary":
        first, *rest = physical.thermal_inputs.node_boundaries
        physical = replace(physical, thermal_inputs=replace(physical.thermal_inputs,
            node_boundaries=(replace(first, radiative_sink_temperature_k=299.0), *rest)))
    elif change == "external":
        first, *rest = physical.external_heat_sources.node_sources
        physical = replace(physical, external_heat_sources=replace(physical.external_heat_sources,
            node_sources=(replace(first, absorbed_solar_w=3.0), *rest)))
    elif change == "solar-ageing": physical = replace(physical, solar_degradation_forcing=None)
    else:
        cfg = inputs.spacecraft_configuration
        model = cfg.degradation.battery_ageing_model
        model = replace(model, calendar_damage_rate_per_second_at_reference=replace(model.calendar_damage_rate_per_second_at_reference, value=2e-6))
        inputs = replace(inputs, spacecraft_configuration=replace(cfg, degradation=replace(cfg.degradation, battery_ageing_model=model)))
    program = replace(program, actions=(program.actions[0], replace(action, physical_inputs=physical), *program.actions[2:]))
    assert experiment_input_digest(inputs, program) != bundle.input_digest
    with pytest.raises(ValueError, match="supplied input content|program/forcing"):
        bundle.restore(repository_root=demo.ROOT, expected_inputs=inputs, expected_program=program)


def test_version1_keeps_legacy_semantics_and_cannot_admit_coupled_content():
    old = legacy.build_demo_state()
    check_schema_coverage()
    assert canonical_content(canonical_copy(old.program)) == canonical_content(old.program)
    assert old.program.version == 1
    before = advance_continuation(old)
    after = advance_continuation(before)
    assert before.context.spacecraft_state == after.context.spacecraft_state
    new = demo.build_demo_state()
    assert type(new.program.actions[1]) is CoupledDownlinkAction
    with pytest.raises(ValueError, match="version 2"):
        replace(new.program, version=1)
    with pytest.raises(ValueError, match="unsupported script version"):
        replace(new.program, version=3)
    # A v2 legacy action is still explicitly data-only; version alone never
    # promotes an old DownlinkAction into a physically coupled operation.
    old_v2 = replace(old, program=replace(old.program, version=2))
    old_v2 = advance_continuation(old_v2)
    next_v2 = advance_continuation(old_v2)
    assert next_v2.context.spacecraft_state == old_v2.context.spacecraft_state
    action = new.program.actions[1]
    changed = replace(new.program, actions=(new.program.actions[0],
        DownlinkAction(action.action_id, action.contact, action.record_id), *new.program.actions[2:]))
    assert experiment_input_digest(new.context.inputs, changed) != experiment_input_digest(new.context.inputs, new.program)


def test_denial_preserves_caller_memory_clock_data_and_all_physical_state(trajectory):
    state = deepcopy(trajectory[1])
    state.context.spacecraft_state.battery.energy_wh = 0.0
    action = state.program.actions[1]
    action = replace(action, physical_inputs=replace(action.physical_inputs, sunlit=False))
    state = replace(state, program=replace(state.program, actions=(state.program.actions[0], action, *state.program.actions[2:])))
    before = deepcopy(state)
    memory, context, spacecraft = state.memory, state.context, state.context.spacecraft_state
    with pytest.raises(ContinuationElectricalDenial) as error:
        advance_continuation(state)
    assert error.value.action_id == "partial-a"
    assert error.value.attempt.time_advanced is False
    assert error.value.attempt.transmission_result is None
    assert state == before and state.memory is memory and state.context is context
    assert state.context.spacecraft_state is spacecraft
    assert state.memory.executed_action_ids == ("image-a",)


def test_continuation_late_postengine_validation_failure_is_atomic(monkeypatch, trajectory):
    state = trajectory[1]
    before = deepcopy(state)
    original = continuation.validate_continuation
    def validate(context, program, memory):
        if context is not state.context:
            assert context.simulation_time_seconds == state.context.simulation_time_seconds + 23
            assert context.ground_data_delivery_state.partial_transfers
            raise RuntimeError("late continuation validation")
        return original(context, program, memory)
    monkeypatch.setattr(continuation, "validate_continuation", validate)
    with pytest.raises(RuntimeError, match="late continuation"):
        advance_continuation(state)
    assert state == before


def test_same_schema_does_not_bypass_implementation_provenance(monkeypatch, trajectory):
    import ops_sim.v5.experiment_bundle as bundles
    bundle = create_bundle(trajectory[2], repository_root=demo.ROOT)
    capture = bundles.capture_provenance
    def changed(root):
        from ops_sim.v5.experiment_provenance import compatibility_digest
        provenance = capture(root)
        provenance["source_sha256"]["ops_sim/v5/coupled_downlink.py"] = "f" * 64
        provenance["compatibility_digest"] = compatibility_digest(provenance)
        return provenance
    monkeypatch.setattr(bundles, "capture_provenance", changed)
    with pytest.raises(ValueError, match="implementation|environment|compatibility"):
        bundle.restore(repository_root=demo.ROOT)
