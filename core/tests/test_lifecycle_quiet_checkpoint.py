"""B53 input and substantive adaptive-state continuation integration.

Small genuine numerical missions in the targeted owned test gate; this is not
a month qualification or the later fresh-process scientific restart evidence.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import pytest

from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot, LifecyclePolicy, METHOD53
from ops_sim.v5.lifecycle_study import common_study_input, compile_study_base
from ops_sim.v5.lifecycle_quiet import QuietIntegrationPolicy
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
from ops_sim.v5.lifecycle_document import dumps_root, loads_root, canonical
from ops_sim.v5.lifecycle_execution import start_lifecycle, step_lifecycle, scientific_projection
from ops_sim.v5.lifecycle_checkpoint import checkpoint_bytes, make_bindings, restore_checkpoint


@pytest.fixture(scope='module')
def root():
    study = common_study_input()
    base = compile_study_base(make_inputs(wire='nominal'), study)
    return LifecycleRoot(base, 600, policy=LifecyclePolicy(latency_seconds=study.latency_seconds,
        quiet_solver=QuietIntegrationPolicy()), study=study, output_policy=LifecycleStreamPolicy())


def pending(root):
    state = start_lifecycle(root)
    for _ in range(128):
        state, _, _ = step_lifecycle(state)
        if (state.physical.pending is not None and state.physical.pending.kind == 'CONTACT'
                and any(p.transmitted_equivalent_bits > 0
                        for p in state.physical.context.ground_data_delivery_state.partial_transfers)):
            assert state.intents and state.queued
            return state
        if state.status != 'ACTIVE': break
    raise AssertionError('declared short study fixture did not reach actual partial CONTACT')


def test_b53_input_roundtrip_preserves_exact_numerical_study_and_output_authority(root):
    raw = dumps_root(root); restored = loads_root(raw)
    assert json.loads(raw)['version'] == 2
    assert root.method == restored.method == METHOD53
    assert restored.identity == root.identity and dumps_root(restored) == raw
    assert type(restored.policy.quiet_solver) is QuietIntegrationPolicy
    assert restored.policy.quiet_solver == root.policy.quiet_solver
    assert restored.study.content_digest == root.study.content_digest
    assert restored.output_policy == root.output_policy


@pytest.mark.parametrize('field', ('quiet', 'output', 'study_units', 'method'))
def test_b53_input_policy_corruption_rejects_even_with_recomputed_document_hash(root, field):
    document = json.loads(dumps_root(root)); data = document['inputs']
    if field == 'quiet': data['policy']['quiet_solver']['absolute_energy_wh'] = -1.
    elif field == 'output': data['output_policy']['max_record_bytes'] = 0
    elif field == 'study_units': data['study']['scalars']['housekeeping_w']['units'] = 'Wh'
    else: data['method'] = 'UNAPPROVED_ALGORITHM'
    body = {k:v for k,v in document.items() if k != 'digest'}
    document['digest'] = sha256(canonical(body).encode()).hexdigest()
    with pytest.raises((ValueError,TypeError)): loads_root(canonical(document).encode())


def test_substantive_adaptive_materialization_has_zero_numerical_prefix(root, monkeypatch):
    import ops_sim.v5.lifecycle_physics as physical
    import ops_sim.v5.lifecycle_execution as execution
    import ops_sim.v5.lifecycle_quiet as quiet
    from ops_sim.v5.lifecycle_orbit import LifecycleOrbitProvider
    state = pending(root); bindings = make_bindings(root,state.clock)
    raw = checkpoint_bytes(state,bindings); before = deepcopy(scientific_projection(state))
    calls = []
    def forbidden(*args,**kwargs):
        calls.append(True); raise AssertionError('numerical owner entered during advanced restore')
    for owner,name in ((physical,'construction_physical_substep'),(physical,'start_lifecycle_physical'),
        (physical,'integrate_quiet_hold'),(execution,'start_lifecycle'),(quiet,'integrate_quiet_hold'),
        (LifecycleOrbitProvider,'query'),(LifecycleOrbitProvider,'at_seconds')):
        monkeypatch.setattr(owner,name,forbidden)
    restored, proof = restore_checkpoint(raw,root,sha256(raw).hexdigest(),bindings)
    assert not calls and scientific_projection(restored) == before
    assert proof['partial_bits'] and restored.physical.pending.kind == 'CONTACT'
    assert restored.physical.quiet_controller == state.physical.quiet_controller
    assert asdict(restored.physical.quiet_work) == asdict(state.physical.quiet_work)
    assert asdict(restored.forecast_quiet_work) == asdict(state.forecast_quiet_work)
    assert restored.forecast_quiet_work is not restored.physical.quiet_work
    assert restored.actual_world.lighting_accounting() == state.actual_world.lighting_accounting()


def test_adaptive_checkpoint_resume_preserves_future_scientific_state_exactly(root):
    state = pending(root); bindings = make_bindings(root,state.clock)
    raw = checkpoint_bytes(state,bindings)
    assert json.loads(raw)['format'] == 'B53_TRUSTED_QUIET_COMPACT_CHECKPOINT_V2'
    restored, _ = restore_checkpoint(raw,root,sha256(raw).hexdigest(),bindings)
    while state.status == 'ACTIVE': state,_,_ = step_lifecycle(state)
    while restored.status == 'ACTIVE': restored,_,_ = step_lifecycle(restored)
    assert scientific_projection(restored) == scientific_projection(state)
    assert restored.actual_world.lighting_accounting() == state.actual_world.lighting_accounting()
