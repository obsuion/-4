"""B55 strict immutable input, sparse-data schema and store admission.

These tests perform original-input admission/data encoding only. Actual coupled
transitions, owned production workers and fresh restore instrumentation belong
to separately bound execution gates; this module does not substitute for them.
"""
from copy import deepcopy
from dataclasses import asdict,replace
from fractions import Fraction as Q
from hashlib import sha256
import json

import pytest

from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot,LifecyclePolicy,METHOD,METHOD53,METHOD55,horizon_inputs
from ops_sim.v5.lifecycle_document import dumps_root,loads_root,canonical,FORMAT,FORMAT53,FORMAT55
from ops_sim.v5.lifecycle_service import (PowerServicePolicy,PowerServiceWork,
    POWER_SERVICE_METHOD,initial_service_state,service_projection)
from ops_sim.v5.lifecycle_quiet import QuietIntegrationPolicy
from ops_sim.v5.lifecycle_application import (LifecycleStore,LifecycleWorkspace,
    requested_lifecycle_root,_power_service_accounting,ProgressReader)
from ops_sim.v5.lifecycle_checkpoint import GraphCodec,RECORD_FIELDS
from ops_sim.v5.lifecycle_world import ReducedSunPolicy
from ops_sim.v5.lifecycle_document import FORMAT55_SUN


@pytest.fixture(scope='module')
def base():return make_inputs(wire='weakness')


@pytest.fixture(scope='module')
def service_root(base):return LifecycleRoot(base,600,service_policy=PowerServicePolicy())


@pytest.mark.parametrize('extended',[False,True])
def test_none_service_preserves_legacy_input_wire_and_identity(base,extended):
    root=LifecycleRoot(base,600,policy=LifecyclePolicy(quiet_solver=QuietIntegrationPolicy() if extended else None))
    explicit=replace(root,service_policy=None)
    raw=dumps_root(root);document=json.loads(raw)
    assert root.method==(METHOD53 if extended else METHOD)
    assert document['format']==(FORMAT53 if extended else FORMAT)
    assert 'service_policy' not in document['inputs']
    assert explicit.identity==root.identity and dumps_root(explicit)==raw
    assert dumps_root(loads_root(raw))==raw


def test_new_policy_is_explicit_identity_and_exact_versioned_input(base,service_root):
    root=service_root;raw=dumps_root(root);document=json.loads(raw)
    assert root.method==METHOD55 and root.identity!=LifecycleRoot(base,600).identity
    assert document['format']==FORMAT55 and document['version']==3
    assert document['inputs']['service_policy']==asdict(PowerServicePolicy())
    restored=loads_root(raw)
    assert restored.identity==root.identity and dumps_root(restored)==raw
    assert 'b55-world-' in str(horizon_inputs(root).common_world.world_id)


def reseal(document):
    body={name:document[name] for name in ('format','version','inputs')}
    document['digest']=sha256(canonical(body).encode()).hexdigest()
    return canonical(document).encode()


@pytest.mark.parametrize('mutation',[
    lambda d:d['inputs']['service_policy'].update(unknown=True),
    lambda d:d['inputs']['service_policy'].update(low_usable_capacity_fraction=True),
    lambda d:d['inputs']['service_policy'].update(high_usable_capacity_fraction=.01),
    lambda d:d['inputs']['service_policy'].update(method='LEGACY'),
    lambda d:d['inputs'].update(service_policy=None),
    lambda d:d['inputs'].update(method=METHOD53),
    lambda d:d.update(version=True),lambda d:d.update(version=2),
    lambda d:d.update(format=FORMAT53),lambda d:d['inputs'].update(actual_mode='SAFE')])
def test_changed_unknown_or_mixed_service_inputs_rejected(service_root,mutation):
    document=json.loads(dumps_root(service_root));mutation(document)
    with pytest.raises((TypeError,ValueError)):loads_root(reseal(document))


def test_shared_create_compiler_never_changes_legacy_by_default(base):
    arguments=dict(duration_seconds=600,policy_data={},scenario_data={},sun_mode='REDUCED_ASSUMED_ANNUAL_V1')
    assert requested_lifecycle_root(base,**arguments).service_policy is None
    root=requested_lifecycle_root(base,service_policy=POWER_SERVICE_METHOD,**arguments)
    assert root.service_policy==PowerServicePolicy() and root.method==METHOD55
    for value in (True,{},'SAFE','B55'):
        with pytest.raises((TypeError,ValueError)):requested_lifecycle_root(base,service_policy=value,**arguments)


@pytest.mark.parametrize('extended',[False,True])
def test_http_named_service_selection_strict_before_constructor_lookup(tmp_path,extended):
    workspace=LifecycleWorkspace(tmp_path/'workspace')
    body=dict(project_id='p',revision='r',duration_seconds=600,policy={},scenario={},sun_mode='REDUCED_ASSUMED_ANNUAL_V1',service_policy=POWER_SERVICE_METHOD)
    if extended:body.update(study_preset='LEGACY',ageing_multiplier=1.,output_policy=None)
    with pytest.raises(ValueError,match='no constructor project authority'):workspace.create_project(body)
    body['service_policy']='SAFE'
    with pytest.raises(ValueError,match='unknown power service policy'):workspace.create_project(body)
    body['service_policy']=POWER_SERVICE_METHOD;body['hidden']=True
    with pytest.raises(ValueError):workspace.create_project(body)


def test_service_store_reopen_has_no_migration_or_implicit_dispatch(tmp_path,service_root):
    store=LifecycleStore(tmp_path/'store',service_root,create=True)
    before={p.relative_to(store.directory).as_posix():p.read_bytes() for p in store.directory.rglob('*') if p.is_file()}
    reopened=LifecycleStore(store.directory)
    assert reopened.root_input.identity==service_root.identity
    assert reopened.snapshot()['service_policy_identity']==service_root.service_policy.identity
    assert not reopened.jobs()
    assert before=={p.relative_to(store.directory).as_posix():p.read_bytes() for p in store.directory.rglob('*') if p.is_file()}


def initial_projection(root):
    value=service_projection(root.service_policy,initial_service_state(Q(root.start_seconds)),PowerServiceWork(),original_start_seconds=Q(root.start_seconds))
    value.update(pinned_requests=0,deferred_feedback=0)
    return value


def test_initial_service_projection_has_exact_zero_support_and_bound_policy(service_root):
    value=initial_projection(service_root)
    _power_service_accounting(value,clock=service_root.start_seconds,start=service_root.start_seconds,policy_identity=service_root.service_policy.identity)


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(extra=True),lambda d:d.update(policy_identity='0'*64),
    lambda d:d.update(mode='GROUND_ASSUMED_SAFE'),lambda d:d.update(clock_seconds=['129','1']),
    lambda d:d.update(essential_serviceable=1),lambda d:d.update(transitions=True),
    lambda d:d.update(communications_serviceable=False,low_rate_telemetry_serviceable=True),
    lambda d:d.update(mode='SAFE',tx_fully_served=True),
    lambda d:d['mode_durations_seconds'].update(SAFE=['1','1']),
    lambda d:d['receiving_energy_wh'].update(commanded_shed_demand_wh=['1','1']),
    lambda d:d.update(boot_work_seconds=['1','1']),
    lambda d:d.update(pinned_requests=17),lambda d:d.update(deferred_feedback=True),
    lambda d:d.update(transition_reasons=[['NORMAL_LOW_ENERGY',1]])])
def test_selected_service_projection_rejects_semantic_corruption(service_root,mutation):
    value=initial_projection(service_root);mutation(value)
    with pytest.raises((TypeError,ValueError)):
        _power_service_accounting(value,clock=service_root.start_seconds,start=service_root.start_seconds,policy_identity=service_root.service_policy.identity)


def test_service_reader_requires_explicit_policy_binding(tmp_path,service_root):
    with pytest.raises(ValueError):ProgressReader(tmp_path/'journal',{},1024,method=METHOD55)
    with pytest.raises(ValueError):ProgressReader(tmp_path/'journal',{},1024,method=METHOD53,service_policy_identity=service_root.service_policy.identity)


def test_service_records_use_only_fixed_native_registry(service_root):
    policy=service_root.service_policy;state=initial_service_state(Q(service_root.start_seconds));work=PowerServiceWork()
    assert all(type(value) in RECORD_FIELDS for value in (policy,state,work))
    codec=GraphCodec(service_root);encoded=codec.encode((policy,state,work,state))
    restored=codec.decode(encoded)
    assert restored[:3]==(policy,state,work) and restored[1] is restored[3]
    bad=deepcopy(encoded)
    for node in bad['nodes']:
        if node[0]=='record':node[1]='untrusted.module.PowerServiceState';break
    with pytest.raises(ValueError):codec.decode(bad)


@pytest.mark.parametrize('kind',('B52','B53','B55'))
def test_none_reduced_sun_preserves_existing_root_input_and_identity(base,kind):
    from ops_sim.v5.rolling_physics import digest
    root=LifecycleRoot(base,600,
        policy=LifecyclePolicy(quiet_solver=QuietIntegrationPolicy()if kind=='B53'else None),
        service_policy=PowerServicePolicy()if kind=='B55'else None)
    raw=dumps_root(root);explicit=replace(root,reduced_sun_policy=None)
    assert root.reduced_sun_policy is None and explicit.identity==root.identity and dumps_root(explicit)==raw
    assert 'reduced_sun_policy'not in json.loads(raw)['inputs']
    assert dumps_root(loads_root(raw))==raw
    if kind in('B53','B55'):
        original_authorities=(root.method,root.base,root.duration_seconds,root.policy,root.scenario,root.sun_mode,root.study,root.output_policy)
        if kind=='B55':original_authorities+= (root.service_policy,)
        assert root.identity==digest(original_authorities)


def test_explicit_reduced_sun_is_versioned_and_identity_bound(service_root):
    from ops_sim.v5.lifecycle_execution import build_model
    policy=ReducedSunPolicy(phase_at_anchor_rad=.625)
    root=replace(service_root,reduced_sun_policy=policy);encoded=dumps_root(root);document=json.loads(encoded)
    assert document['format']==FORMAT55_SUN and document['version']==4
    assert document['inputs']['reduced_sun_policy']==asdict(policy)
    assert root.identity!=service_root.identity
    assert replace(root,reduced_sun_policy=ReducedSunPolicy(phase_at_anchor_rad=.75)).identity!=root.identity
    restored=loads_root(encoded)
    assert restored.reduced_sun_policy==policy and dumps_root(restored)==encoded and restored.identity==root.identity
    assert build_model(root).environment.sun is policy
    assert build_model(service_root).environment.sun==ReducedSunPolicy()
    # Declared default coefficients remain an explicit different authority;
    # no old root is silently migrated to a new wire or digest.
    assert replace(service_root,reduced_sun_policy=ReducedSunPolicy()).identity!=service_root.identity


@pytest.mark.parametrize('value',(True,{},'phase',1.0))
def test_reduced_sun_requires_exact_immutable_existing_type(service_root,value):
    with pytest.raises((TypeError,ValueError)):replace(service_root,reduced_sun_policy=value)


def test_reduced_sun_override_is_only_supported_in_b55_reduced_mode(base,service_root):
    policy=ReducedSunPolicy(phase_at_anchor_rad=.625)
    with pytest.raises(ValueError):LifecycleRoot(base,600,reduced_sun_policy=policy)
    with pytest.raises(ValueError):replace(service_root,sun_mode='BOUND_SHORT_TABLE_V1',reduced_sun_policy=policy)


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(format=FORMAT55,version=3),
    lambda d:d.update(format=FORMAT55_SUN,version=3),
    lambda d:d['inputs'].pop('reduced_sun_policy'),
    lambda d:d['inputs'].update(reduced_sun_policy=None),
    lambda d:d['inputs'].update(sun_mode='BOUND_SHORT_TABLE_V1'),
    lambda d:d['inputs'].update(method=METHOD53),
    lambda d:d['inputs']['reduced_sun_policy'].update(unknown=True),
    lambda d:d['inputs']['reduced_sun_policy'].update(phase_at_anchor_rad=True),
    lambda d:d['inputs']['reduced_sun_policy'].update(phase_at_anchor_rad=9.),
    lambda d:d['inputs']['reduced_sun_policy'].update(provenance='FLIGHT_CALIBRATED'),
    lambda d:d['inputs']['reduced_sun_policy'].pop('distance_m')])
def test_reduced_sun_rejects_mixed_unknown_or_invalid_input(service_root,mutation):
    root=replace(service_root,reduced_sun_policy=ReducedSunPolicy(phase_at_anchor_rad=.625))
    document=json.loads(dumps_root(root));mutation(document)
    with pytest.raises((TypeError,ValueError)):loads_root(reseal(document))


def test_old_service_input_cannot_smuggle_reduced_sun_field(service_root):
    document=json.loads(dumps_root(service_root));document['inputs']['reduced_sun_policy']=asdict(ReducedSunPolicy())
    with pytest.raises(ValueError):loads_root(reseal(document))


def test_explicit_sun_store_snapshot_discloses_immutable_authority(tmp_path,service_root):
    root=replace(service_root,reduced_sun_policy=ReducedSunPolicy(phase_at_anchor_rad=.625))
    store=LifecycleStore(tmp_path/'sun-store',root,create=True)
    assert store.snapshot()['reduced_sun_policy']==asdict(root.reduced_sun_policy)
    assert LifecycleStore(store.directory).root_input.reduced_sun_policy==root.reduced_sun_policy


def test_explicit_sun_native_checkpoint_preserves_domain_and_zero_owner_restore(service_root,monkeypatch):
    from ops_sim.v5.lifecycle_execution import start_lifecycle,scientific_projection
    from ops_sim.v5.lifecycle_checkpoint import make_bindings,checkpoint_bytes,restore_checkpoint,admit_checkpoint
    from ops_sim.v5 import lifecycle_orbit as orbit,lifecycle_world as world,lifecycle_physics as physical,lifecycle_execution as execution
    root=replace(service_root,reduced_sun_policy=ReducedSunPolicy(phase_at_anchor_rad=.625))
    state=start_lifecycle(root);bindings=make_bindings(root,state.clock);raw=checkpoint_bytes(state,bindings)
    before=deepcopy(scientific_projection(state));calls=[]
    def forbidden(*args,**kwargs):
        calls.append(True);raise AssertionError('native explicit Sun restore entered a numerical owner')
    for owner,name in((orbit,'_gravity'),(orbit,'_rk4_step'),(world,'nominal_parallel_ray'),
        (world,'evaluate_ground_point_geometry'),(world,'evaluate_ground_visibility'),
        (physical,'start_lifecycle_physical'),(physical,'construction_physical_substep'),(execution,'start_lifecycle')):
        monkeypatch.setattr(owner,name,forbidden)
    restored,proof=restore_checkpoint(raw,root,sha256(raw).hexdigest(),bindings)
    assert proof['restored_clock']==state.clock
    assert calls==[] and scientific_projection(restored)==before
    assert restored.model.environment.sun==root.reduced_sun_policy
    assert restored.actual_world.environment.sun==restored.forecast_world.environment.sun==root.reduced_sun_policy
    assert restored.actual_world is not restored.forecast_world
    other=replace(root,reduced_sun_policy=ReducedSunPolicy(phase_at_anchor_rad=.75))
    with pytest.raises(ValueError):admit_checkpoint(raw,other,sha256(raw).hexdigest(),bindings)
    with pytest.raises(ValueError):admit_checkpoint(raw,service_root,sha256(raw).hexdigest(),bindings)
