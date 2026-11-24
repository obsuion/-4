"""Content binding, causal completeness, semantic rejection and atomicity."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
import hashlib
import subprocess

import pytest

from examples.v5_experiment_bundle_demo import ROOT, build_demo_state, summarize
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.checkpoint import CURRENT_CHECKPOINT_SCHEMA_VERSION, CheckpointState
import ops_sim.v5.continuation as continuation
from ops_sim.v5.continuation import (
    ContinuationMemory, ContinuationState, advance_continuation, checked_checkpoint,
)
from ops_sim.v5.context import with_coast_orbit, evaluate_context_coast
from ops_sim.v5.engine import SimulationEngine
import ops_sim.v5.experiment_bundle as bundles
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content, content_digest, json_text
from ops_sim.v5.experiment_provenance import capture_provenance, compatibility_digest
from ops_sim.v5.ids import WorldEventId
from test_v56b2_checkpoint_binding import _coast


def rehash(payload):
    """Recompute published integrity domains independently of bundle reader."""
    payload["runtime_digest"] = content_digest("v5-continuation-state-v1", {
        "input_digest": payload["input_digest"], "checkpoint": payload["checkpoint"], "memory": payload["memory"],
    })
    payload["bundle_digest"] = content_digest("v5-experiment-bundle-v1", {
        k: v for k, v in payload.items() if k != "bundle_digest"
    })
    return payload


@pytest.fixture(scope="module")
def partial_state():
    return advance_continuation(advance_continuation(build_demo_state()))


@pytest.fixture(scope="module")
def bundle(partial_state):
    return create_bundle(partial_state, repository_root=ROOT)


def test_time_advances_without_changing_immutable_identity():
    state = build_demo_state()
    first = create_bundle(state, repository_root=ROOT)
    state = advance_continuation(state)
    later = create_bundle(state, repository_root=ROOT)
    assert first.input_digest == later.input_digest
    assert first.runtime_digest != later.runtime_digest
    assert experiment_input_digest(build_demo_state().context.inputs, state.program) == first.input_digest


@pytest.mark.parametrize("change", ["efficiency", "electrical_power", "capacity", "numerics"])
def test_same_ids_different_valid_input_content_rejected_before_legacy_restore(bundle, partial_state, change, monkeypatch):
    inputs = partial_state.context.inputs
    config = inputs.spacecraft_configuration
    if change == "efficiency":
        battery = config.eps.battery
        assert battery.discharge_efficiency.value == 0.9
        config = replace(config, eps=replace(config.eps, battery=replace(
            battery, discharge_efficiency=replace(battery.discharge_efficiency, value=0.45),
        )))
    elif change == "electrical_power":
        optical = config.payload.optical_acquisition
        config = replace(config, payload=replace(config.payload, optical_acquisition=replace(
            optical, acquisition_power_w=replace(optical.acquisition_power_w, value=optical.acquisition_power_w.value + 1),
        )))
    elif change == "capacity":
        battery = config.eps.battery
        config = replace(config, eps=replace(config.eps, battery=replace(
            battery, nominal_energy_wh=replace(battery.nominal_energy_wh, value=battery.nominal_energy_wh.value * 2),
        )))
    changed = replace(inputs, spacecraft_configuration=config)
    if change == "numerics":
        changed = replace(changed, numerical_config=replace(changed.numerical_config, geometry_sample_seconds=2))
    assert changed.model_manifest == inputs.model_manifest
    assert experiment_input_digest(changed, partial_state.program) != bundle.input_digest
    # Legacy semantics deliberately remain ID-based, including the audit case.
    old = CheckpointState.from_context(partial_state.context).restore(changed)
    assert old.inputs is changed
    before = deepcopy(partial_state)
    monkeypatch.setattr(CheckpointState, "restore", lambda *args: pytest.fail("legacy restore ran before content check"))
    with pytest.raises(ValueError, match="supplied input content"):
        bundle.restore(repository_root=ROOT, expected_inputs=changed)
    assert partial_state == before


def test_forcing_and_explicit_assumptions_are_bound_with_unchanged_input_ids(bundle, partial_state):
    program = partial_state.program
    image = program.actions[0]
    forcing = replace(image.environment, non_acquisition_loads=replace(image.environment.non_acquisition_loads, base_bus_w=2.0))
    programs = (
        replace(program, actions=(replace(image, environment=forcing), *program.actions[1:])),
        replace(program, assumptions=program.assumptions + ("Additional explicit assumption.",)),
    )
    for changed in programs:
        assert experiment_input_digest(partial_state.context.inputs, changed) != bundle.input_digest
        with pytest.raises(ValueError, match="program/forcing"):
            bundle.restore(repository_root=ROOT, expected_program=changed)


def test_supported_coast_content_survives_bundle_and_changes_identity():
    state = build_demo_state()
    inputs = with_coast_orbit(state.context.inputs, _coast())
    state = replace(state, context=replace(state.context, inputs=inputs))
    bundle = create_bundle(state, repository_root=ROOT)
    restored = ExperimentBundle.from_json(bundle.to_json()).restore(repository_root=ROOT)
    assert evaluate_context_coast(restored.context) == evaluate_context_coast(state.context)
    changed_coast = replace(inputs.coast_orbit, solver_config=replace(inputs.coast_orbit.solver_config, time_tolerance_seconds=2e-8))
    changed = with_coast_orbit(inputs, changed_coast)
    assert experiment_input_digest(changed, state.program) != bundle.input_digest
    with pytest.raises(ValueError, match="supplied input content"):
        bundle.restore(repository_root=ROOT, expected_inputs=changed)


@pytest.mark.parametrize("field", ["bundle_version", "canonical_version", "inputs", "program", "randomness", "input_digest", "checkpoint", "memory", "runtime_digest", "provenance", "bundle_digest"])
def test_every_required_section_rejects_omission(bundle, field):
    payload = json.loads(bundle.to_json())
    del payload[field]
    with pytest.raises(ValueError, match="fields"):
        ExperimentBundle.from_json(json.dumps(payload))


@pytest.mark.parametrize("field,value", [("bundle_version", 2), ("canonical_version", True), ("randomness", "seed-only"), ("runtime_digest", "0"*64), ("input_digest", "0"*64), ("bundle_digest", "0"*64)])
def test_versions_randomness_and_corrupted_digests(bundle, field, value):
    payload = json.loads(bundle.to_json()); payload[field] = value
    with pytest.raises((TypeError, ValueError)):
        ExperimentBundle.from_json(json.dumps(payload))


@pytest.mark.parametrize("change", ["binding", "clock", "progress", "previous", "missing_previous", "empty_prefix", "over_capacity", "extra_section"])
def test_semantic_inconsistency_rejected_even_with_recomputed_checksums(bundle, partial_state, change):
    payload = json.loads(bundle.to_json())
    if change == "binding":
        payload["checkpoint"]["input_digest"] = "0" * 64
    elif change == "clock":
        payload["checkpoint"]["schema5"]["simulation_time_seconds"] += 23
    elif change == "progress":
        payload["checkpoint"]["schema5"]["ground_data_delivery"]["partial_transfers"][0]["transmitted_equivalent_bits"] = 1.0
    elif change == "over_capacity":
        payload["checkpoint"]["schema5"]["spacecraft"]["battery_energy_wh"] = 1e10
    elif change == "extra_section":
        payload["unknown_runner_queue"] = []
    else:
        memory = payload["memory"]["fields"]
        if change == "previous":
            memory["previous_execution"] = canonical_content(partial_state.program.initial_previous_execution)
        elif change == "missing_previous":
            memory["previous_execution"] = {"kind": "none"}
        else:
            memory["executed_action_ids"] = canonical_content(())
    rehash(payload)
    before = deepcopy(partial_state)
    with pytest.raises((TypeError, ValueError)):
        ExperimentBundle.from_json(json.dumps(payload))
    assert partial_state == before


def test_lost_attitude_memory_changes_the_next_legal_imaging_result(partial_state):
    current = partial_state.memory.previous_execution
    direction = current.candidate.common_frame_boresight
    wrong = replace(current, candidate=replace(current.candidate, common_frame_boresight=CommonFrameBoresightDirection(direction.frame_id, 1.0, 0.0, 0.0)))
    action = partial_state.program.actions[2]
    working = CheckpointState.from_context(partial_state.context).restore(partial_state.context.inputs)
    with pytest.raises(ValueError):
        replace(partial_state, memory=replace(partial_state.memory, previous_execution=wrong))
    # Exercise the actual public engine to establish why this memory is causal.
    attempt = SimulationEngine().step_imaging_to_storage(
        working, wrong, action.execution, record_id=action.record_id,
        environment=action.environment, routing_config=action.routing_config,
        thermal_inputs=action.thermal_inputs, external_heat_sources=action.external_heat_sources,
        solar_degradation_forcing=action.solar_degradation_forcing,
    )
    assert attempt.step_result is None
    assert working == partial_state.context
    assert advance_continuation(partial_state).memory.executed_action_ids[-1] == "image-b"


def test_valid_empty_prefix_is_distinct_from_missing_or_inconsistent_memory():
    state = build_demo_state()
    assert state.memory.executed_action_ids == ()
    with pytest.raises(TypeError):
        ContinuationMemory(previous_execution=state.memory.previous_execution)
    with pytest.raises(ValueError, match="cursor"):
        replace(state, context=replace(state.context, simulation_time_seconds=123))


def test_capture_rejects_lossy_legacy_numeric_normalization():
    state = build_demo_state()
    state.context.spacecraft_state.battery.energy_wh = Fraction(1, 3)
    with pytest.raises(ValueError, match="losslessly representable"):
        checked_checkpoint(state.context)


def test_unsupported_world_event_processing_is_not_silently_filled_in():
    state = build_demo_state()
    inputs = replace(state.context.inputs, common_world=replace(state.context.inputs.common_world, event_ids=(WorldEventId("unresolved-event"),)))
    with pytest.raises(ValueError, match="world-event"):
        replace(state, context=replace(state.context, inputs=inputs))


@pytest.mark.parametrize("change", ["code", "dependency"])
def test_matching_head_does_not_hide_changed_code_or_environment(bundle, change):
    payload = json.loads(bundle.to_json())
    provenance = payload["provenance"]
    if change == "code":
        path = "ops_sim/v5/engine.py"
        provenance["source_sha256"][path] = "0" * 64
        provenance["source_status"][path] = "modified"
        provenance["git_dirty"] = True
    else:
        provenance["environment"]["dependencies"]["pytest"] = "different-version"
    provenance["compatibility_digest"] = compatibility_digest(provenance)
    forged = ExperimentBundle.from_json(json.dumps(rehash(payload)))
    with pytest.raises(ValueError, match="implementation/environment"):
        forged.restore(repository_root=ROOT)


def test_actual_provenance_hashes_dirty_or_new_code_instead_of_only_head():
    provenance = capture_provenance(ROOT)
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args])
    path = "ops_sim/v5/experiment_bundle.py"
    tracked = {p.decode("utf-8") for p in git("ls-files", "-z").split(b"\0") if p}
    modified = {p.decode("utf-8") for p in git("diff", "HEAD", "--name-only", "-z").split(b"\0") if p}
    expected_status = "untracked" if path not in tracked else "modified" if path in modified else "clean"
    assert provenance["source_status"][path] == expected_status
    assert provenance["git_dirty"] == bool(git("status", "--porcelain=v1", "--untracked-files=all").strip())
    assert provenance["source_sha256"][path] == hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def test_schema5_wire_preserves_supported_integer_runtime_values(bundle):
    payload = json.loads(bundle.to_json())
    payload["checkpoint"]["schema5"]["spacecraft"]["battery_energy_wh"] = 1
    restored = ExperimentBundle.from_json(json.dumps(rehash(payload))).restore(repository_root=ROOT)
    assert type(restored.context.spacecraft_state.battery.energy_wh) is int
    assert restored.context.spacecraft_state.battery.energy_wh == 1


def test_schema5_wire_rejects_unknown_nested_state_even_if_rehashed(bundle):
    payload = json.loads(bundle.to_json())
    payload["checkpoint"]["schema5"]["spacecraft"]["unpersisted_queue"] = []
    with pytest.raises(ValueError, match="invalid keys"):
        ExperimentBundle.from_json(json.dumps(rehash(payload)))


def test_late_restore_failure_does_not_mutate_existing_context_or_memory(bundle, partial_state, monkeypatch):
    before = deepcopy(partial_state)
    references = (partial_state.context.spacecraft_state, partial_state.context.ground_data_delivery_state, partial_state.memory)
    def fail(*args):
        raise RuntimeError("late bundle validation probe")
    monkeypatch.setattr(bundles, "ContinuationState", fail)
    with pytest.raises(RuntimeError, match="late bundle"):
        bundle.restore(repository_root=ROOT, expected_inputs=partial_state.context.inputs)
    assert partial_state == before
    assert references == (partial_state.context.spacecraft_state, partial_state.context.ground_data_delivery_state, partial_state.memory)
    assert references[0] is partial_state.context.spacecraft_state
    assert references[1] is partial_state.context.ground_data_delivery_state
    assert references[2] is partial_state.memory


def test_late_advance_validation_failure_is_atomic(partial_state, monkeypatch):
    before = deepcopy(partial_state)
    original = continuation.validate_continuation
    def validate(context, program, memory):
        original(context, program, memory)
        if context is not partial_state.context:
            raise RuntimeError("late script completion probe")
    monkeypatch.setattr(continuation, "validate_continuation", validate)
    with pytest.raises(RuntimeError, match="late script"):
        advance_continuation(partial_state)
    assert partial_state == before


def test_bundle_returns_fresh_state_without_aliasing(bundle, partial_state):
    one = bundle.restore(repository_root=ROOT)
    two = bundle.restore(repository_root=ROOT)
    assert summarize(one) == summarize(two) == summarize(partial_state)
    assert one.context is not two.context
    one.context.spacecraft_state.battery.energy_wh = 0.0
    assert two.context.spacecraft_state.battery.energy_wh != 0.0
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
