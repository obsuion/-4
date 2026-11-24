"""Strict legacy/new quiet progress DATA, with no physical/numerical calls."""
from copy import deepcopy
from dataclasses import fields, replace
from fractions import Fraction as Q
from hashlib import sha256
from pathlib import Path

import pytest

from ops_sim.v5 import lifecycle_application as app
from ops_sim.v5.lifecycle_quiet import (
    QuietIntegrationPolicy,BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy,
    QuietWork,ShortCircuitQuietWork,quiet_work_for,short_circuit_policy,
)

OWNERS=(QuietIntegrationPolicy,BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy)
EXTRA=tuple(f.name for f in fields(ShortCircuitQuietWork)if f.name not in QuietWork.__dataclass_fields__)


def display(work):
    value={f.name:getattr(work,f.name)for f in fields(work)}
    for key in('selected_seconds','committed_seconds'):
        q=value[key];value[key]=[str(q.numerator),str(q.denominator)]
    return value


def empty(policy,clock=4):
    return dict(method=policy.method,
        controller=dict(clock_seconds=[str(clock),'1'],next_step_seconds=policy.minimum_macro_seconds,
            last_step_seconds=['0','1'],last_error_norm=0.,phase='INITIAL'),
        actual=display(quiet_work_for(policy)),forecast=display(quiet_work_for(policy)))


def paid(policy,*,early=False):
    """Use actual work owner operations, never a simulated spacecraft leaf."""
    work=quiet_work_for(policy);work.proposed_macros=1
    work.reserve('full_trial',policy);work.returned_leaf_calls+=1
    if early:
        assert type(work)is ShortCircuitQuietWork
        work.full_near_guard=1;work.early('full_near');work.rejected_macros=1
        for _ in range(2):
            work.reserve('detailed_fallback',policy);work.returned_leaf_calls+=1;work.select(Q(2))
        work.minimum_macro_proposals=work.minimum_macro_fallbacks=1
        work.below_minimum_fallbacks=work.shortened_boundary_proposals=1
    else:
        for stage in('first','second'):
            work.reserve('half_trial',policy)
            if type(work)is ShortCircuitQuietWork:work.performed(stage)
            work.returned_leaf_calls+=1
        work.accepted_macros=1;work.maximum_accepted_error_norm=.25
        if type(work)is ShortCircuitQuietWork:work.norm_evaluations=1
        work.select(Q(2));work.select(Q(2))
    work.committed_parts=work.selected_parts;work.committed_seconds=work.selected_seconds
    work.validate(policy)
    data=empty(policy);data['actual']=display(work)
    data['controller'].update(last_step_seconds=['2'if early else'4','1'],
        last_error_norm=0. if early else .25,phase='DETAILED_FALLBACK'if early else'ACCEPTED')
    return data


@pytest.mark.parametrize('owner',OWNERS)
def test_existing_legacy_exact_22_fields_keep_private_call_compatibility(owner):
    policy=owner();value=paid(policy)
    assert len(value['actual'])==22
    app._quiet_accounting(value,clock=4,elapsed=4,expected_method=policy.method)
    app._quiet_accounting(value,clock=4,elapsed=4,expected_method=policy.method,expected_policy=policy)


@pytest.mark.parametrize('owner',OWNERS)
@pytest.mark.parametrize('early',[False,True])
def test_new_exact_41_fields_are_bound_to_actual_policy_and_truthful_cost(owner,early):
    policy=short_circuit_policy(owner());value=paid(policy,early=early)
    assert len(value['actual'])==41 and len(EXTRA)==19
    app._quiet_accounting(value,clock=4,elapsed=4,expected_method=policy.method,expected_policy=policy)
    assert value['actual']['reserved_leaf_calls']==3
    assert value['actual']['skipped_half_trial_calls']==(2 if early else 0)
    assert value['actual']['half_trial_calls']==(0 if early else 2)


def test_new_work_cannot_be_omitted_or_declared_without_policy():
    policy=short_circuit_policy(QuietIntegrationPolicy())
    with pytest.raises(ValueError,match='cannot be omitted'):
        app._quiet_accounting(None,expected_method=policy.method,expected_policy=policy)
    with pytest.raises(ValueError,match='exact declared policy'):
        app._quiet_accounting(paid(policy),expected_method=policy.method)
    assert app._quiet_accounting(None)is None # historical detailed/absent shape


@pytest.mark.parametrize('field',EXTRA)
def test_new_counter_is_required_and_never_silently_recomputed(field):
    policy=short_circuit_policy(QuietIntegrationPolicy());value=paid(policy,early=True)
    del value['actual'][field]
    with pytest.raises((ValueError,TypeError)):
        app._quiet_accounting(value,expected_method=policy.method,expected_policy=policy)


@pytest.mark.parametrize('field',EXTRA)
def test_new_counter_rejects_boolean_instead_of_integer(field):
    policy=short_circuit_policy(QuietIntegrationPolicy());value=paid(policy,early=True)
    value['forecast'][field]=True
    with pytest.raises((ValueError,TypeError)):
        app._quiet_accounting(value,expected_method=policy.method,expected_policy=policy)


@pytest.mark.parametrize('change',[
    'extra','fake_reserve','half_stage_sum','second_without_first','skipped_sum','early_norm_sum','norm_rejections',
])
def test_recomputed_or_extra_declared_work_must_preserve_source_conservation(change):
    policy=short_circuit_policy(QuietIntegrationPolicy());value=paid(policy,early=True);work=value['actual']
    if change=='extra':work['computed_extra']=0
    elif change=='fake_reserve':work['reserved_leaf_calls']+=work['skipped_half_trial_calls']
    elif change=='half_stage_sum':work['first_half_calls']=1
    elif change=='second_without_first':
        work.update(second_half_calls=1,half_trial_calls=1,reserved_leaf_calls=4,returned_leaf_calls=4)
    elif change=='skipped_sum':work['skipped_half_trial_calls']+=1
    elif change=='early_norm_sum':work['norm_not_evaluated_early']=0
    else:work['norm_rejections']=1
    with pytest.raises((ValueError,TypeError)):
        app._quiet_accounting(value,expected_method=policy.method,expected_policy=policy)


@pytest.mark.parametrize('change',['legacy_data_as_new','new_data_as_legacy','wrong_policy','quota'])
def test_method_and_work_shape_cannot_substitute_for_authority(change):
    old=QuietIntegrationPolicy();policy=short_circuit_policy(old);value=paid(policy,early=True)
    if change=='legacy_data_as_new':value['actual']=paid(old)['actual']
    elif change=='new_data_as_legacy':
        value['method']=old.method
    elif change=='wrong_policy':policy=short_circuit_policy(BatteryQuietIntegrationPolicy())
    else:policy=replace(policy,max_total_leaf_calls=2)
    with pytest.raises((ValueError,TypeError)):
        app._quiet_accounting(value,expected_method=policy.method,expected_policy=policy)


@pytest.mark.parametrize('change',['next_below_policy','stale_clock','noncanonical_rational','future_commit'])
def test_new_controller_and_rational_display_stay_within_actual_policy(change):
    policy=short_circuit_policy(QuietIntegrationPolicy());value=paid(policy,early=True)
    if change=='next_below_policy':value['controller']['next_step_seconds']=2
    elif change=='stale_clock':value['controller']['clock_seconds']=['5','1']
    elif change=='noncanonical_rational':value['actual']['selected_seconds']=['04','1']
    else:value['actual']['committed_seconds']=['5','1']
    with pytest.raises((ValueError,TypeError)):
        app._quiet_accounting(value,clock=4,elapsed=4,expected_method=policy.method,expected_policy=policy)


def test_hostile_method_phase_and_policy_types_never_supply_equality_or_callbacks():
    class Hostile(str):
        def __eq__(self,other):raise AssertionError('hostile equality must not run')
        __hash__=str.__hash__
    class PolicyProxy:
        def __post_init__(self):raise AssertionError('foreign policy callback must not run')
    policy=short_circuit_policy(QuietIntegrationPolicy());original=paid(policy,early=True)
    for where in('method','expected_method','phase','policy'):
        value=deepcopy(original);expected=policy.method;authority=policy
        if where=='method':value['method']=Hostile(policy.method)
        elif where=='expected_method':expected=Hostile(policy.method)
        elif where=='phase':value['controller']['phase']=Hostile('DETAILED_FALLBACK')
        else:authority=PolicyProxy()
        with pytest.raises((ValueError,TypeError)):
            app._quiet_accounting(value,expected_method=expected,expected_policy=authority)


@pytest.mark.parametrize('short',[False,True])
def test_environment_progress_route_uses_the_actual_root_method(monkeypatch,short):
    """Routing unit: unrelated subsystem display validation is isolated.

    The real immutable root checks and real quiet validator are retained. This
    does not manufacture a full physical progress record or replace the actual
    production-runner acceptance. A hardcoded legacy ENV method fails here.
    """
    from ops_sim.v5.spacecraft_project_document import loads_project
    from ops_sim.v5 import environment_lifecycle,solar_lifecycle,battery_port_reporting
    raw=(Path(__file__).parent/'fixtures/year_authored_A.project.json').read_bytes()
    assert sha256(raw).hexdigest()=='02d5b13ae67758901664353ddd09a2bd93d3f425e1b1868939b7513231cf216d'
    root=loads_project(raw.decode('utf8')).common
    if short:root=replace(root,policy=replace(root.policy,quiet_solver=short_circuit_policy(root.policy.quiet_solver)))
    for name in('_cache_accounting','_world_accounting','_last_action','_lighting_accounting','_power_service_accounting'):
        monkeypatch.setattr(app,name,lambda *args,**kwargs:None)
    monkeypatch.setattr(environment_lifecycle,'validate_progress',lambda *args:None)
    monkeypatch.setattr(solar_lifecycle,'validate_solar_progress',lambda *args:None)
    monkeypatch.setattr(battery_port_reporting,'validate_port_progress',lambda *args:None)
    start=root.start_seconds;light={'end_seconds':[hex(start),'0x1']}
    data=dict(method=root.method,status='INITIAL',clock=start,start_seconds=start,end_seconds=root.end_seconds,
        simulated_seconds=0,transitions=0,actions=0,decisions=0,offered=0,active_requests=0,
        queued_packets=0,pending_intents=0,pending_action=None,partial_bits=[],credits=0,sealed_month_rows=0,
        actual_cache={},forecast_cache={},actual_world=dict(api='ISOLATED_ROUTING',lighting_consumption=light),
        forecast_world=dict(api='ISOLATED_ROUTING',lighting_consumption=deepcopy(light)),
        quiet=empty(root.policy.quiet_solver,clock=start),illumination=light,last_action=None,
        power_service={},solar_attitude={},battery_port={},environment_ageing={},
        publication=dict(minimum_wall_interval_seconds=1,policy_omitted_snapshots=0,last_checkpoint_bytes=1,
            memory=dict(status='UNAVAILABLE',method='WINDOWS_OWN_PROCESS_WORKING_SET',
                current_rss_bytes=None,peak_rss_bytes=None,error='synthetic routing; no OS query')))
    job=dict(job_id='1'*32,root_identity=root.identity,runtime={'routing_test':True})
    record=dict(format=app.JOURNAL,sequence=1,job_id=job['job_id'],root_identity=root.identity,kind='boundary',data=data)
    assert app._validate_progress(record,job,1,method=root.method,
        service_policy_identity=root.service_policy.identity,solar_root=root,battery_root=root,environment_root=root)is record
