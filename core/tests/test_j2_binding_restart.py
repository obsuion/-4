"""Schema-5/bundle reconstruction, actual engine clocks and fresh-process F3."""

from copy import deepcopy
from dataclasses import replace
import json
import os
import subprocess
import sys

import pytest

from examples.v5_experiment_bundle_demo import ROOT, build_demo_state
from examples.v5_j2_bundle_demo import build_j2_demo_state, summary
import ops_sim.v5.context as contexts
from ops_sim.v5.checkpoint import CheckpointState, CURRENT_CHECKPOINT_SCHEMA_VERSION, SpacecraftStateSnapshot
from ops_sim.v5.context import evaluate_context_j2_enclosure, with_j2_coast_orbit
from ops_sim.v5.continuation import advance_continuation
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle
from ops_sim.v5.experiment_codec import canonical_content, decode_content, json_text
from ops_sim.v5.ids import ModelManifestId
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.orbit_j2_binding import J2_MANIFEST_PREFIX
from ops_sim.v5.orbit_j2_enclosure import evaluate_j2_enclosure
from test_v56b1_two_body_contracts import _forge
from test_v56b2_checkpoint_binding import _case, _coast, _step


def test_clock_mapping_nonmutation_and_explicit_unresolved(monkeypatch):
    context = build_j2_demo_state().context
    for unresolved in (False, True):
        if unresolved:
            coast = context.inputs.coast_orbit
            context = replace(context, inputs=with_j2_coast_orbit(context.inputs, replace(
                coast, enclosure_policy=replace(coast.enclosure_policy, max_steps=1))))
        before = deepcopy(context)
        refs = (context.inputs, context.spacecraft_state, context.diagnostics, context.ground_data_delivery_state)
        coast = context.inputs.coast_orbit
        calls = []
        def query(trajectory, instant, solver, policy):
            calls.append(instant)
            return evaluate_j2_enclosure(trajectory, instant, solver, policy)
        monkeypatch.setattr(contexts, 'evaluate_j2_enclosure', query)
        actual = evaluate_context_j2_enclosure(context)
        assert calls == [GeometryInstant(coast.trajectory.initial_state.position.instant.epoch, 100)]
        assert coast.trajectory.initial_state.position.instant.elapsed_seconds == 128
        assert actual == evaluate_j2_enclosure(coast.trajectory, calls[0], coast.solver_config, coast.enclosure_policy)
        assert actual.status == ('unresolved' if unresolved else 'enclosed')
        if unresolved:
            assert actual.nominal_state is actual.endpoint_intervals is actual.position_error_bound_m is actual.velocity_error_bound_m_per_s is None
        assert context == before
        assert all(a is b for a, b in zip(refs, (
            context.inputs, context.spacecraft_state, context.diagnostics, context.ground_data_delivery_state)))


@pytest.mark.parametrize('kind', ['generic', 'imaging', 'storage', 'downlink'])
def test_every_engine_path_retains_original_j2_authority_and_restarts(kind, monkeypatch):
    legacy = _case(kind)
    coast = build_j2_demo_state().context.inputs.coast_orbit
    direct = replace(deepcopy(legacy), inputs=with_j2_coast_orbit(legacy.inputs, coast))
    original_inputs = direct.inputs
    restored_inputs = decode_content(canonical_content(direct.inputs))
    checkpoint = CheckpointState.from_dict(json.loads(json.dumps(CheckpointState.from_context(direct).to_dict())))
    assert checkpoint.schema_version == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    restored = checkpoint.restore(restored_inputs)
    # Engine execution and capture/restore revalidate definitions but do not coast.
    with monkeypatch.context() as guard:
        guard.setattr(contexts, 'evaluate_j2_enclosure', lambda *a: pytest.fail('hidden propagation'))
        assert _step(kind, direct) == _step(kind, restored) == _step(kind, legacy)
        again = CheckpointState.from_context(direct).restore(restored_inputs)
    assert direct == restored == again
    assert direct.inputs is original_inputs and direct.inputs.coast_orbit is coast
    actual = evaluate_context_j2_enclosure(direct)
    assert actual == evaluate_context_j2_enclosure(restored)
    assert actual.instant.elapsed_seconds == direct.simulation_time_seconds
    assert coast.trajectory.initial_state.position.instant.elapsed_seconds == 128


@pytest.mark.parametrize('boundary', ['context', 'capture', 'restore', 'engine', 'query', 'codec'])
@pytest.mark.parametrize('damage', ['stale-policy', 'no-owner', 'old-owner', 'old-id', 'plain-id', 'unknown-owner'])
def test_bad_bindings_rejected_before_mutable_restore_or_propagation(boundary, damage, monkeypatch):
    context = build_j2_demo_state().context
    checkpoint = CheckpointState.from_context(context)
    inputs = context.inputs
    if damage == 'stale-policy':
        bad = _forge(inputs, 'coast_orbit.enclosure_policy.precision_digits', 51)
    elif damage in ('no-owner', 'old-owner', 'unknown-owner'):
        bad = _forge(inputs, 'coast_orbit', {'no-owner': None, 'old-owner': _coast(), 'unknown-owner': object()}[damage])
    else:
        label = 'v56b2-coast-sha256-' + '0'*64 if damage == 'old-id' else 'ordinary'
        bad = _forge(inputs, 'model_manifest.manifest_id', ModelManifestId(label))
    forged = _forge(context, 'inputs', bad)
    before = deepcopy(context)
    monkeypatch.setattr(SpacecraftStateSnapshot, 'restore', lambda *a: pytest.fail('mutable restore before binding check'))
    monkeypatch.setattr(contexts, 'evaluate_j2_enclosure', lambda *a: pytest.fail('propagation before binding check'))
    monkeypatch.setattr(SimulationEngine, '_execute_phase', lambda *a: pytest.fail('execution before binding check'))
    with pytest.raises((ValueError, TypeError)):
        if boundary == 'context':
            replace(forged)
        elif boundary == 'capture':
            CheckpointState.from_context(forged)
        elif boundary == 'restore':
            checkpoint.restore(bad)
        elif boundary == 'engine':
            SimulationEngine().step(forged)
        elif boundary == 'codec':
            canonical_content(bad)
        else:
            evaluate_context_j2_enclosure(forged)
    assert context == before


def test_reserved_namespace_and_unsupported_two_body_geometry(monkeypatch):
    from ops_sim.v5.orbit_visibility_windows import find_ground_visibility_windows, GroundVisibilitySearchConfig
    from test_v56c1_ground_point_contracts import _point
    from test_v56c2a_visibility_contracts import _policy

    legacy = build_demo_state().context.inputs
    with pytest.raises(ValueError, match='reserved J2'):
        replace(legacy, model_manifest=replace(legacy.model_manifest, manifest_id=ModelManifestId(J2_MANIFEST_PREFIX+'0'*64)))
    context = build_j2_demo_state().context
    with pytest.raises(TypeError, match='two-body'):
        contexts.evaluate_context_coast(context)
    with pytest.raises(TypeError, match='CoastOrbitInputs'):
        find_ground_visibility_windows(context.inputs, _point(), _policy(0.), 0., 10., GroundVisibilitySearchConfig(1., 100))
    with pytest.raises(TypeError, match='J2CoastOrbitInputs'):
        evaluate_context_j2_enclosure(build_demo_state().context)


def test_binding_hashing_and_bundle_restore_never_propagate(monkeypatch):
    import ops_sim.v5.orbit_j2 as j2
    import ops_sim.v5.orbit_j2_enclosure as f3

    def forbidden(*args, **kwargs):
        pytest.fail('propagation reached by persistence')
    monkeypatch.setattr(contexts, 'evaluate_j2_enclosure', forbidden)
    monkeypatch.setattr(f3, 'evaluate_j2_enclosure', forbidden)
    monkeypatch.setattr(j2, 'evaluate_j2_cartesian_state', forbidden)
    state = build_j2_demo_state()
    bundle = create_bundle(state, repository_root=ROOT)
    restored = ExperimentBundle.from_json(bundle.to_json()).restore(repository_root=ROOT)
    assert restored == state and restored.context.inputs is not state.context.inputs
    payload = json.loads(bundle.to_json())
    assert payload['canonical_version'] == payload['bundle_version'] == 1
    assert restored.program.version == 1


@pytest.fixture(scope='module')
def states():
    sequence = [build_j2_demo_state()]
    for _ in sequence[0].program.actions:
        sequence.append(advance_continuation(sequence[-1]))
    return sequence


@pytest.mark.parametrize('mode', ['bundle', 'schema'])
def test_fresh_process_nonzero_boundary_real_continuation_and_f3(tmp_path, states, mode):
    partial, final = states[2], states[-1]
    assert partial.context.simulation_time_seconds == 146
    assert partial.context.ground_data_delivery_state.partial_transfers
    bundle_path, schema_path, inputs_path, output_path = [tmp_path / n for n in
        ('bundle.json', 'schema.json', 'inputs.json', 'result.json')]
    if mode == 'bundle':
        bundle_path.write_text(create_bundle(partial, repository_root=ROOT).to_json(), encoding='utf-8')
        args = ['--resume', str(bundle_path)]
    else:
        schema_path.write_text(json_text({'checkpoint': CheckpointState.from_context(partial.context).to_dict(),
            'program': canonical_content(partial.program), 'memory': canonical_content(partial.memory)}), encoding='utf-8')
        inputs_path.write_text(json_text(canonical_content(partial.context.inputs)), encoding='utf-8')
        args = ['--resume-schema', str(schema_path), '--inputs', str(inputs_path)]
    code = '\n'.join([
        'import sys', 'from examples import v5_j2_bundle_demo as demo',
        "def forbidden(*a): raise AssertionError('origin fixture called during restart')",
        'demo.build_j2_demo_state = forbidden', 'demo.build_demo_state = forbidden',
        'demo.pilot_trajectory = forbidden', 'demo.main(sys.argv[1:])',
    ])
    command = [sys.executable, '-B', '-c', code, *args, '--output', str(output_path)]
    result = subprocess.run(command, cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONHASHSEED': '731'}, text=True, encoding='utf-8', capture_output=True, timeout=120)
    (tmp_path / 'child.log').write_text(result.stdout+result.stderr, encoding='utf-8')
    assert result.returncode == 0, result.stdout+result.stderr
    output = json.loads(output_path.read_text(encoding='utf-8'))
    assert output['initial'] == summary(partial)
    assert output['final'] == summary(final)
    assert output['final']['metrics']['clock_seconds'] == 238
    assert output['final']['metrics']['delivered_equivalent_bits'] == 24000
    assert output['final']['j2']['anchor_seconds'] == 128
    assert output['final']['j2']['status'] == 'enclosed'


def test_bundle_code_environment_check_remains_effective(monkeypatch):
    import ops_sim.v5.experiment_bundle as bundles

    bundle = create_bundle(build_j2_demo_state(), repository_root=ROOT)
    original = bundles.capture_provenance
    def incompatible(root):
        result = original(root)
        result['compatibility_digest'] = '0'*64
        return result
    monkeypatch.setattr(bundles, 'capture_provenance', incompatible)
    with pytest.raises(ValueError, match='implementation/environment compatibility mismatch'):
        bundle.restore(repository_root=ROOT)
