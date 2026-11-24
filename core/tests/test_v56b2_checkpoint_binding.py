"""Real schema-5 restart, four engine paths, and rejection before mutation."""

from copy import deepcopy
from dataclasses import fields, replace
import json

import pytest

import ops_sim.v5.context as context_module
import ops_sim.v5.engine as engine_module
from ops_sim.v5.checkpoint import CheckpointState, CURRENT_CHECKPOINT_SCHEMA_VERSION, SpacecraftStateSnapshot
from ops_sim.v5.context import SimulationContext, evaluate_context_coast, with_coast_orbit
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import AcquisitionDataRecordId, ModelManifestId
from ops_sim.v5.orbit import TwoBodySolverConfig, evaluate_two_body_state
from ops_sim.v5.orbit_binding import CoastOrbitInputs
from ops_sim.v5.orbit_config import GeometryInstant
from test_v56b1_two_body_contracts import _forge, _trajectory
from test_v50d1_time_engine import _context as generic_context
import test_v53f3b_imaging_engine_integration as imaging
import test_v54d2_imaging_storage_engine_integration as storage
import test_v55d_downlink_engine_integration as downlink


def _coast(t0=7.25, tolerance=1e-8):
    return CoastOrbitInputs(_trajectory(r=(7000000., 0., 0.), v=(3., 7546., 20.),
                                       mu=398600441800000., earth=6378137., t0=t0),
                            TwoBodySolverConfig(tolerance, 100))


def _bound(context=None, coast=None):
    context = generic_context() if context is None else context
    return replace(context, inputs=with_coast_orbit(context.inputs, _coast() if coast is None else coast))


def _refs(context):
    return (context.inputs, context.inputs.coast_orbit, *downlink._authoritative_references(context))


def _assert_unchanged(context, before, refs):
    assert context == before
    assert all(a is b for a, b in zip(_refs(context), refs))


def _portable_restart(context, legacy_inputs):
    checkpoint = CheckpointState.from_context(context)
    portable = json.loads(json.dumps(checkpoint.to_dict(), allow_nan=False))
    recovered = CheckpointState.from_dict(portable)
    coast = CoastOrbitInputs.from_dict(json.loads(json.dumps(context.inputs.coast_orbit.to_dict(), allow_nan=False)))
    inputs = with_coast_orbit(legacy_inputs, coast)
    restored = recovered.restore(inputs)
    assert restored.inputs is inputs
    assert restored.inputs.coast_orbit is coast
    return restored


def test_portable_checkpoint_keeps_schema_fields_and_all_keys_unchanged():
    legacy = generic_context()
    bound = _bound(legacy)
    original = CheckpointState.from_context(legacy).to_dict()
    payload = CheckpointState.from_context(bound).to_dict()
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == payload["schema_version"] == 5
    assert tuple(payload) == ("schema_version", "simulation_time_seconds", "input_ids", "spacecraft",
                              "ground_knowledge", "ground_data_delivery", "mission", "controller", "diagnostics")
    original["input_ids"]["model_manifest_id"] = bound.inputs.model_manifest.manifest_id.canonical
    assert payload == original  # Every other nested key/value retains legacy representation.
    assert not any("orbit" in f.name or "coast" in f.name for f in fields(CheckpointState))
    restored = _portable_restart(bound, legacy.inputs)
    assert restored == bound
    assert evaluate_context_coast(restored) == evaluate_context_coast(bound)
    for name in ("spacecraft_state", "ground_knowledge_state", "ground_data_delivery_state", "mission_state",
                 "controller_state", "diagnostics"):
        assert getattr(restored, name) is not getattr(bound, name)
    for name in ("battery", "propulsion", "thermal", "degradation", "onboard", "data_storage"):
        assert getattr(restored.spacecraft_state, name) is not getattr(bound.spacecraft_state, name)
    assert CheckpointState.from_dict(json.loads(json.dumps(CheckpointState.from_context(legacy).to_dict(),
                                                        allow_nan=False))).restore(legacy.inputs) == legacy


def test_query_uses_actual_time_not_initial_sample_and_calls_b1_once(monkeypatch):
    context = _bound(coast=_coast(t0=7.25))
    before, refs = deepcopy(context), _refs(context)
    calls = []
    def evaluate(trajectory, instant, solver_config):
        calls.append((trajectory, instant, solver_config))
        return evaluate_two_body_state(trajectory, instant, solver_config)
    monkeypatch.setattr(context_module, "evaluate_two_body_state", evaluate)
    result = evaluate_context_coast(context)
    coast = context.inputs.coast_orbit
    assert len(calls) == 1 and calls[0][0] is coast.trajectory and calls[0][2] is coast.solver_config
    assert result.position.instant == GeometryInstant(coast.trajectory.initial_state.position.instant.epoch, 0)
    assert result.position.instant.elapsed_seconds != coast.trajectory.initial_state.position.instant.elapsed_seconds
    assert result == evaluate_two_body_state(coast.trajectory, result.position.instant, coast.solver_config)
    _assert_unchanged(context, before, refs)


def test_binding_capture_restore_and_normal_step_do_not_propagate(monkeypatch):
    monkeypatch.setattr(context_module, "evaluate_two_body_state", lambda *a: pytest.fail("hidden coast propagation"))
    context = _bound()
    restored = _portable_restart(context, generic_context().inputs)
    SimulationEngine().step(restored)
    assert restored.simulation_time_seconds == 60


@pytest.mark.parametrize("path,value", [
    ("coast_orbit.solver_config.max_iterations", 101),
    ("coast_orbit.trajectory.gravitational_parameter_m3_s2.provenance.rationale", "Changed valid rationale"),
    ("numerical_config.geometry_sample_seconds", 2),
    ("common_world.horizon_seconds", 601),
    ("coast_orbit", None),
])
@pytest.mark.parametrize("boundary", ["context", "capture", "restore", "engine", "query"])
def test_stale_or_stripped_binding_rejected_at_every_runtime_boundary(path, value, boundary, monkeypatch):
    context = _bound()
    checkpoint = CheckpointState.from_context(context)
    original, refs = deepcopy(context), _refs(context)
    bad_inputs = _forge(context.inputs, path, value)
    forged = _forge(context, "inputs", bad_inputs)
    if boundary == "restore":
        monkeypatch.setattr(SpacecraftStateSnapshot, "restore", lambda *a: pytest.fail("allocated state before binding validation"))
    with pytest.raises(ValueError, match="coast binding identity mismatch|reserved coast manifest namespace"):
        if boundary == "context":
            SimulationContext(**{f.name: getattr(forged, f.name) for f in fields(SimulationContext)})
        elif boundary == "capture":
            CheckpointState.from_context(forged)
        elif boundary == "restore":
            checkpoint.restore(bad_inputs)
        elif boundary == "engine":
            SimulationEngine().step(forged)
        else:
            evaluate_context_coast(forged)
    _assert_unchanged(context, original, refs)


@pytest.mark.parametrize("direction", ["bound-to-legacy", "legacy-to-bound", "different-coast", "copied-bound-id"])
def test_restore_substitution_fails_before_allocating_state(direction, monkeypatch):
    legacy = generic_context()
    bound = _bound(legacy)
    cp = CheckpointState.from_context(legacy if direction == "legacy-to-bound" else bound)
    if direction == "bound-to-legacy":
        supplied = legacy.inputs
    elif direction == "legacy-to-bound":
        supplied = bound.inputs
    elif direction == "different-coast":
        supplied = with_coast_orbit(legacy.inputs, _coast(t0=8.))
    else:
        supplied = _forge(legacy.inputs, "model_manifest.manifest_id", bound.inputs.model_manifest.manifest_id)
    before, refs = deepcopy(bound), _refs(bound)
    monkeypatch.setattr(SpacecraftStateSnapshot, "restore", lambda *a: pytest.fail("allocated mismatched state"))
    with pytest.raises(ValueError, match="model manifest identity mismatch|reserved coast manifest namespace"):
        cp.restore(supplied)
    _assert_unchanged(bound, before, refs)


@pytest.mark.parametrize("path,value", [("mission_state.command_ids", []),
                                       ("spacecraft_state.propulsion.delta_v_remaining_m_per_s", -1.),
                                       ("diagnostics.completed_steps", True),
                                       ("simulation_time_seconds", True), ("simulation_time_seconds", -1)])
def test_query_revalidates_complete_actual_runtime_context(path, value):
    bad = _forge(_bound(), path, value)
    with pytest.raises((ValueError, TypeError)):
        evaluate_context_coast(bad)


def test_orbit_free_query_is_explicitly_rejected():
    with pytest.raises(ValueError, match="no coast_orbit binding"):
        evaluate_context_coast(generic_context())


@pytest.mark.parametrize("time", [2**40+1, 2**53+1])
def test_fingerprinted_horizon_does_not_round_or_validate_query_time(time):
    legacy = generic_context(horizon_seconds=time)
    context = _bound(legacy)
    context.simulation_time_seconds = time
    before, refs = deepcopy(context), _refs(context)
    with pytest.raises(ValueError, match="arithmetic envelope|integer precision"):
        evaluate_context_coast(context)
    _assert_unchanged(context, before, refs)


def test_b1_accuracy_failure_remains_visible_without_fabricated_evidence():
    context = _bound(generic_context(simulation_time_seconds=60), _coast(tolerance=1e-30))
    before, refs = deepcopy(context), _refs(context)
    with pytest.raises(ValueError, match="requested residual accuracy cannot be resolved"):
        evaluate_context_coast(context)
    _assert_unchanged(context, before, refs)


def _case(kind):
    return {"generic": generic_context, "imaging": imaging._context,
            "storage": storage._context, "downlink": downlink._context}[kind]()


def _step(kind, context):
    engine = SimulationEngine()
    if kind == "generic":
        return engine.step(context)
    if kind == "imaging":
        return engine.step_imaging(**imaging._arguments(context=context))
    if kind == "storage":
        return engine.step_imaging_to_storage(**storage._arguments(context=context))
    return engine.step_downlink(context, downlink._contact(start=context.simulation_time_seconds,
                                end=context.simulation_time_seconds+23), record_id=AcquisitionDataRecordId("target"))


@pytest.mark.parametrize("kind", ["generic", "imaging", "storage", "downlink"])
def test_all_four_paths_direct_and_portable_restart_continuations(kind, monkeypatch):
    legacy = _case(kind)
    direct = _bound(deepcopy(legacy))
    restarted = _portable_restart(direct, deepcopy(legacy.inputs))
    initial = deepcopy(direct.inputs.coast_orbit.trajectory.initial_state)
    inputs_ref = direct.inputs
    before_query = evaluate_context_coast(direct)
    assert evaluate_context_coast(restarted) == before_query
    # A successful engine step must never evaluate the trajectory internally.
    with monkeypatch.context() as guarded:
        guarded.setattr(context_module, "evaluate_two_body_state", lambda *a: pytest.fail("hidden propagation in engine path"))
        result = _step(kind, direct)
        restarted_result = _step(kind, restarted)
        legacy_result = _step(kind, legacy)
    step = result if kind == "generic" else result.step_result
    assert step is not None and direct.simulation_time_seconds == step.end_time_seconds
    assert result == restarted_result == legacy_result
    assert direct == restarted
    assert direct.inputs is inputs_ref
    after = evaluate_context_coast(direct)
    assert after == evaluate_context_coast(restarted)
    assert after.position.instant.elapsed_seconds == direct.simulation_time_seconds
    assert after.velocity.instant == after.position.instant
    assert after.position.instant != before_query.position.instant
    assert direct.inputs.coast_orbit.trajectory.initial_state == initial
    # Restart after a real completed step, then continue both branches again.
    continued = _portable_restart(direct, legacy.inputs)
    assert continued == direct and evaluate_context_coast(continued) == after
    SimulationEngine().step(direct)
    SimulationEngine().step(continued)
    assert direct == continued and evaluate_context_coast(direct) == evaluate_context_coast(continued)
    print(f"B2 {kind}: completed {step.start_time_seconds}->{step.end_time_seconds}s; "
          "portable restart, coast evidence and continuation exactly equal")


def test_downlink_partial_completion_and_unmodeled_physics_remain_separate():
    context = _bound(downlink._context())
    before = deepcopy(context.spacecraft_state)
    trajectory = context.inputs.coast_orbit.trajectory
    for expected_time, progress in [(123, 5000.), (146, 10000.), (169, 12000.)]:
        result = _step("downlink", context)
        assert context.simulation_time_seconds == expected_time
        assert all(value is None for value in downlink._physical_fields(result.step_result))
        assert result.transmission_result.progress_after_equivalent_bits == progress
        assert evaluate_context_coast(context).position.instant.elapsed_seconds == expected_time
        for name in ("battery", "propulsion", "thermal", "degradation"):
            assert getattr(context.spacecraft_state, name) == getattr(before, name)
        assert context.inputs.coast_orbit.trajectory is trajectory
        if progress < 12000.:
            assert len(context.spacecraft_state.data_storage.stored_records) == 1
            assert len(context.ground_data_delivery_state.partial_transfers) == 1
        else:
            assert not context.spacecraft_state.data_storage.stored_records
            assert not context.ground_data_delivery_state.partial_transfers
            assert len(context.ground_data_delivery_state.completed_deliveries) == 1


def test_failed_precommit_result_preserves_all_authoritative_values_and_references(monkeypatch):
    context = _bound(downlink._context())
    before, refs = deepcopy(context), _refs(context)
    before_coast = evaluate_context_coast(context)
    observed = []
    def fail_result(self):
        observed.append(self.transmission_result.progress_after_equivalent_bits)
        raise RuntimeError("B2 injected precommit result failure")
    monkeypatch.setattr(engine_module.DownlinkEngineStepResult, "__post_init__", fail_result)
    with pytest.raises(RuntimeError, match="injected precommit result failure"):
        _step("downlink", context)
    assert observed == [5000.]
    _assert_unchanged(context, before, refs)
    assert evaluate_context_coast(context) == before_coast


class PrefixHidingText(str):
    def startswith(self, *args, **kwargs):
        return False


def test_review_prefix_hiding_id_cannot_restore_without_orbit():
    bound, legacy = _bound(), generic_context()
    checkpoint = CheckpointState.from_context(bound)
    copied_id = ModelManifestId(PrefixHidingText(bound.inputs.model_manifest.manifest_id.value))
    assert copied_id.canonical == checkpoint.model_manifest_id.canonical
    assert copied_id == checkpoint.model_manifest_id
    with pytest.raises(TypeError, match="exact str"):
        without_orbit = replace(legacy.inputs,
            model_manifest=replace(legacy.inputs.model_manifest, manifest_id=copied_id))
        checkpoint.restore(without_orbit)


@pytest.mark.parametrize("boundary", ["capture", "restore", "engine"])
def test_forged_reserved_subclass_rejected_before_state_or_execution(boundary, monkeypatch):
    bound, legacy = _bound(), generic_context()
    checkpoint = CheckpointState.from_context(bound)
    copied = ModelManifestId(PrefixHidingText(bound.inputs.model_manifest.manifest_id.value))
    supplied = _forge(legacy.inputs, "model_manifest.manifest_id", copied)
    forged_context = _forge(legacy, "inputs", supplied)
    before, refs = deepcopy(bound), _refs(bound)
    monkeypatch.setattr(SpacecraftStateSnapshot, "restore", lambda *a: pytest.fail("mutable snapshot reached"))
    monkeypatch.setattr(SimulationEngine, "_execute_phase", lambda *a: pytest.fail("execution reached"))
    with pytest.raises(TypeError, match="exact str"):
        if boundary == "capture":
            CheckpointState.from_context(forged_context)
        elif boundary == "restore":
            checkpoint.restore(supplied)
        else:
            SimulationEngine().step(forged_context)
    _assert_unchanged(bound, before, refs)


@pytest.mark.parametrize("orbit_enabled", [False, True])
@pytest.mark.parametrize("text_kind", ["plain", "comparison", "prefix"])
@pytest.mark.parametrize("path", [
    "model_manifest.manifest_id", "model_manifest.spacecraft_configuration_id",
    "model_manifest.numerical_config_id", "model_manifest.environment_id", "model_manifest.flight_rules_id",
    "model_manifest.scenario_id", "model_manifest.world_id", "model_manifest.controller_id",
    "numerical_config.configuration_id", "common_world.world_id", "common_world.scenario_id",
])
def test_known_binding_id_text_is_exact_on_bound_and_legacy_paths(orbit_enabled, text_kind, path):
    from test_v56b2_orbit_binding import PlainText, ComparisonText
    context = _bound() if orbit_enabled else generic_context()
    text_type = {"plain": PlainText, "comparison": ComparisonText, "prefix": PrefixHidingText}[text_kind]
    identity = context.inputs
    for name in path.split("."):
        identity = getattr(identity, name)
    forged = _forge(context.inputs, path+".value", text_type(identity.value))
    with pytest.raises(TypeError, match="exact str"):
        replace(forged)


@pytest.mark.parametrize("orbit_enabled", [False, True])
def test_world_event_id_text_is_exact_on_both_paths(orbit_enabled):
    from ops_sim.v5.ids import WorldEventId
    from test_v56b2_orbit_binding import PlainText
    context = _bound() if orbit_enabled else generic_context()
    bad_event = WorldEventId(PlainText("ordinary-event"))
    supplied = _forge(context.inputs, "common_world.event_ids", (bad_event,))
    with pytest.raises(TypeError, match="exact str"):
        replace(supplied)
