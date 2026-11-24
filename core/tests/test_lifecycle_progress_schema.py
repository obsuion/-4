"""B54 real progress producer/publication/reader compatibility.

The three small, actual HOLD transitions are shared by the module. Mutations
below operate only on their saved JSON data; they do not repeat a mission.
Windows-owned production-runner smoke evidence is a separate task gate.
"""
from copy import deepcopy
import json

import pytest

from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot, LifecyclePolicy, METHOD
from ops_sim.v5.lifecycle_execution import start_lifecycle, step_lifecycle, progress_projection
from ops_sim.v5.lifecycle_quiet import QuietIntegrationPolicy
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
from ops_sim.v5.lifecycle_world import API, ACCOUNTING_API, LIGHT_TRACKING
import ops_sim.v5.lifecycle_application as app


def publication(data):
    """Add the worker's observational envelope, leaving its model data intact."""
    value=json.loads(json.dumps(data,allow_nan=False))
    value['publication']=dict(minimum_wall_interval_seconds=1,
        policy_omitted_snapshots=0,last_checkpoint_bytes=1,
        memory=dict(status='UNAVAILABLE',method='WINDOWS_OWN_PROCESS_WORKING_SET',
            current_rss_bytes=None,peak_rss_bytes=None,error='portable schema test; no OS memory query'))
    return value


@pytest.fixture(scope='module')
def produced():
    base=make_inputs(wire='nominal')
    result={}
    for name in ('legacy_detailed','detailed','quiet'):
        policy=LifecyclePolicy(quiet_solver=QuietIntegrationPolicy() if name=='quiet' else None)
        root=LifecycleRoot(base,120,policy=policy,
            output_policy=None if name=='legacy_detailed' else LifecycleStreamPolicy())
        state=start_lifecycle(root)
        initial=publication(progress_projection(state))
        state,event,_=step_lifecycle(state)
        assert state.clock>root.start_seconds and event['kind']=='HOLD_UNTIL'
        advanced=publication(progress_projection(state))
        result[name]=(root,initial,advanced)
    return result


def job(root):
    return dict(job_id='1'*32,root_identity=root.identity,runtime={'schema_test':'not a worker identity'})


def record(root,data):
    return dict(format=app.JOURNAL,sequence=1,job_id=job(root)['job_id'],
        root_identity=root.identity,kind='boundary',data=data)


def validate(root,data):
    return app._validate_progress(record(root,data),job(root),1,method=root.method)


@pytest.mark.parametrize('name',('legacy_detailed','detailed','quiet'))
@pytest.mark.parametrize('channel',('plain','chunked'))
def test_real_progress_publisher_to_strict_incremental_reader(produced,tmp_path,name,channel):
    root,initial,advanced=produced[name]
    if channel=='plain':
        path=tmp_path/'progress.jsonl'
        publisher=app._Journal(path,job(root),2**20,lambda:2**20)
        reader=app.ProgressReader(path,job(root),2**20,method=root.method)
    else:
        path=tmp_path/'progress53';policy=LifecycleStreamPolicy()
        publisher=app._ChunkJournal(path,job(root),policy,lambda n:None)
        reader=app.ProgressReader(path,job(root),policy.progress_total_bytes,
            output_policy=policy,method=root.method)
    try:
        publisher.emit('boundary',initial)
        assert reader.read()[0]['data']==initial
        publisher.emit('boundary',advanced)
        assert reader.read()[0]['data']==advanced
        assert not reader.read() and reader.sequence==2 and reader.tail==b''
    finally:publisher.close()
    for data in (initial,advanced):
        for role in ('actual','forecast'):
            world=data[role+'_world']
            assert world['api']==ACCOUNTING_API and world['lighting_tracking']==LIGHT_TRACKING
        if name=='legacy_detailed':
            assert data['actual_world']['lighting_consumption']['covered_seconds']==['0x0','0x1']
            assert 'illumination' not in data and 'quiet' not in data
        else:
            assert data['illumination']==data['actual_world']['lighting_consumption']
    if name=='quiet':
        assert advanced['quiet']['actual']['reserved_leaf_calls']>0
        for scope in ('actual','forecast'):
            assert 'maximum_accepted_error_norm' in advanced['quiet'][scope]
    elif name=='detailed':assert advanced['quiet'] is None


def at(data,path):
    for key in path:data=data[key]
    return data


# Each corruption begins with the same real advanced producer record.
@pytest.mark.parametrize('path,key,value',[
    ((),'invented',0),
    (('actual_world',),'api','UNAPPROVED'),
    (('actual_world',),'lighting_tracking','FULL_HORIZON_TRUTH'),
    (('actual_world',),'role','FORECAST'),
    (('actual_world',),'mode','CERTIFIED'),
    (('actual_world',),'sun_authority','UNKNOWN_SOURCE'),
    (('actual_world',),'original_anchor',['0x0','0x1']),
    (('actual_world',),'lighting_grid_seconds',0),
    (('actual_world',),'lighting_evaluations',-1),
    (('actual_world',),'retained_lighting',2**55),
    (('actual_world',),'invented',1),
    (('actual_world','lighting_consumption'),'units','h'),
    (('actual_world','lighting_consumption'),'scope','INHERITED_ACTUAL_PREFIX_ONLY_NO_FORECAST_CONSUMPTION'),
    (('actual_world','lighting_consumption'),'method','CONTINUOUS_ECLIPSE'),
    (('actual_world','lighting_consumption'),'qualification','VALIDATED_EVENT_TIME'),
    (('actual_world','lighting_consumption'),'selected_commits',True),
    (('actual_world','lighting_consumption'),'selected_commits',0),
    (('actual_world','lighting_consumption'),'covered_seconds',['0x0','0x1']),
    (('actual_world','lighting_consumption'),'occulted_seconds',['-0x1','0x1']),
    (('actual_world','lighting_consumption'),'end_seconds',['0x1','0x1']),
    (('actual_world','lighting_consumption'),'start_seconds',['0x0','0x1']),
    (('actual_world','lighting_consumption'),'illuminated_seconds',['0x0','0x0']),
    (('actual_world','lighting_consumption'),'invented',0),
    (('forecast_world','lighting_consumption'),'scope','SELECTED_ACTUAL_CONSUMED_SUPPORT'),
    (('quiet','actual'),'maximum_accepted_error_norm',float('nan')),
    (('quiet','actual'),'maximum_accepted_error_norm',float('inf')),
    (('quiet','actual'),'maximum_accepted_error_norm',-1e-12),
    (('quiet','actual'),'maximum_accepted_error_norm',1.0000000000000002),
    (('quiet','actual'),'maximum_accepted_error_norm',True),
    (('quiet','forecast'),'maximum_accepted_error_norm',float('nan')),
    (('quiet','actual'),'returned_leaf_calls',2**55),
    (('quiet','actual'),'committed_seconds',['999999','1']),
    (('quiet','actual'),'selected_step_le_1',2**55),
    (('quiet','actual'),'invented',0),
    (('quiet','controller'),'clock_seconds',['0','1']),
    (('quiet','controller'),'last_error_norm',float('nan')),
    (('quiet','controller'),'last_error_norm',-1.),
    (('quiet','controller'),'phase','INVENTED'),
    (('quiet','controller'),'invented',0),
])
def test_real_quiet_progress_rejects_strict_and_semantic_corruption(produced,path,key,value):
    root,_,source=produced['quiet'];data=deepcopy(source)
    at(data,path)[key]=value
    with pytest.raises((ValueError,TypeError)):validate(root,data)


@pytest.mark.parametrize('path,key',[
    ((),'actual_world'),(('actual_world',),'lighting_consumption'),
    (('actual_world',),'lighting_tracking'),
    (('actual_world','lighting_consumption'),'units'),
    (('actual_world','lighting_consumption'),'unresolved_seconds'),
    (('quiet','actual'),'maximum_accepted_error_norm'),
    (('quiet','forecast'),'maximum_accepted_error_norm'),
    (('quiet','controller'),'clock_seconds'),
])
def test_real_progress_rejects_missing_required_fields(produced,path,key):
    root,_,source=produced['quiet'];data=deepcopy(source);del at(data,path)[key]
    with pytest.raises((ValueError,TypeError)):validate(root,data)


def test_current_detailed_consumer_preserves_strict_historical_world_shape(produced):
    root,_,source=produced['legacy_detailed'];data=deepcopy(source)
    # Explicit old observational shape: the current actual producer is the
    # authority; only the historically absent fields/API are projected out.
    for name in ('actual_world','forecast_world'):
        data[name]['api']=API
        del data[name]['lighting_consumption'];del data[name]['lighting_tracking']
    assert root.method==METHOD and validate(root,data)['data']==data
    for name in ('actual_world','forecast_world'):
        bad=deepcopy(data);bad[name]['lighting_consumption']=source[name]['lighting_consumption']
        with pytest.raises(ValueError):validate(root,bad)


def test_new_progress_cannot_downgrade_world_schema(produced):
    root,_,source=produced['detailed'];data=deepcopy(source)
    for name in ('actual_world','forecast_world'):
        data[name]['api']=API
        del data[name]['lighting_consumption'];del data[name]['lighting_tracking']
    with pytest.raises(ValueError):validate(root,data)


def test_legacy_empty_ledger_does_not_claim_selected_coverage(produced):
    root,_,source=produced['legacy_detailed'];data=deepcopy(source)
    data['actual_world']['lighting_consumption']=deepcopy(produced['detailed'][2]['illumination'])
    with pytest.raises(ValueError,match='legacy'):validate(root,data)


def test_new_actual_ledger_requires_full_committed_prefix_and_matching_projection(produced):
    root,initial,source=produced['detailed'];data=deepcopy(source)
    data['actual_world']['lighting_consumption']=deepcopy(initial['illumination'])
    with pytest.raises(ValueError,match='committed prefix'):validate(root,data)
    data=deepcopy(source)
    # Both tallies remain exact nonnegative full-prefix partitions, but their
    # classifications differ. They cannot represent two ACTUAL authorities.
    light=data['illumination'];covered=light['covered_seconds']
    light['illuminated_seconds']=['0x0','0x1'];light['occulted_seconds']=['0x0','0x1']
    light['unresolved_seconds']=covered
    if light==data['actual_world']['lighting_consumption']:
        light['unresolved_seconds']=['0x0','0x1'];light['illuminated_seconds']=covered
    with pytest.raises(ValueError,match='disagreement'):validate(root,data)


def test_forecast_cannot_inherit_future_consumed_support(produced):
    root,_,source=produced['detailed'];data=deepcopy(source)
    light=data['forecast_world']['lighting_consumption'];future=data['clock']+1
    light.update(end_seconds=[hex(future),'0x1'],covered_seconds=[hex(future-data['start_seconds']),'0x1'],
        illuminated_seconds=[hex(future-data['start_seconds']),'0x1'],occulted_seconds=['0x0','0x1'],
        unresolved_seconds=['0x0','0x1'],selected_commits=1)
    with pytest.raises(ValueError,match='future'):validate(root,data)


def test_accepted_controller_cannot_publish_rejected_error_norm(produced):
    root,_,source=produced['quiet'];data=deepcopy(source)
    data['quiet']['controller'].update(phase='ACCEPTED',last_error_norm=1.0000000000000002)
    with pytest.raises(ValueError,match='accepted'):validate(root,data)


@pytest.mark.parametrize('corruption',('unknown','missing','units','maximum'))
@pytest.mark.parametrize('channel',('plain','chunked'))
def test_strict_reader_rejects_mutated_real_publications_without_accepting_sequence(produced,tmp_path,corruption,channel):
    root,_,source=produced['quiet'];data=deepcopy(source)
    if corruption=='unknown':data['actual_world']['invented']=True
    elif corruption=='missing':del data['quiet']['actual']['maximum_accepted_error_norm']
    elif corruption=='units':data['illumination']['units']='K'
    else:data['quiet']['actual']['maximum_accepted_error_norm']=1.01
    if channel=='plain':
        path=tmp_path/'invalid.jsonl'
        publisher=app._Journal(path,job(root),2**20,lambda:2**20)
        reader=app.ProgressReader(path,job(root),2**20,method=root.method)
    else:
        path=tmp_path/'invalid53';policy=LifecycleStreamPolicy()
        publisher=app._ChunkJournal(path,job(root),policy,lambda n:None)
        reader=app.ProgressReader(path,job(root),policy.progress_total_bytes,
            output_policy=policy,method=root.method)
    try:
        publisher.emit('boundary',data)
        with pytest.raises(ValueError):reader.read()
        assert reader.sequence==0
    finally:publisher.close()


@pytest.fixture(scope='module')
def wrapper(produced):
    from ops_sim.v5.lifecycle_admission import COMPILED
    state=start_lifecycle(produced['quiet'][0],execution_mode=COMPILED)
    bound=dict(root_identity=state.root.identity,source_identity=state.compiled_context.source_identity)
    return state,bound


def test_real_compiled_terminal_wrapper_snapshot_is_pure_and_separate_from_science(wrapper):
    from ops_sim.v5.lifecycle_execution import scientific_projection
    state,bound=wrapper;before=deepcopy(state.compiled_context.to_data())
    payload=app._static_admission_snapshot(state)
    assert app._static_admission_accounting(payload,bound,required=True)==before
    assert state.compiled_context.to_data()==before
    assert payload['actual'] is not payload['forecast']
    assert 'static_admission_wrapper' not in scientific_projection(state)
    assert state.compiled_context.to_data()==before
    payload['actual']['control_units_reserved']+=1
    assert state.compiled_context.to_data()==before


@pytest.mark.parametrize('corruption',('unknown','method','root','source','missing_actual',
    'unknown_counter','negative','noninteger','unbalanced'))
def test_real_compiled_terminal_wrapper_rejects_schema_and_binding_corruption(wrapper,corruption):
    state,bound=wrapper;data=app._static_admission_snapshot(state)
    if corruption=='unknown':data['invented']=1
    elif corruption=='method':data['method']='UNAPPROVED'
    elif corruption=='root':data['root_identity']='0'*64
    elif corruption=='source':data['source_identity']='0'*64
    elif corruption=='missing_actual':del data['actual']
    elif corruption=='unknown_counter':data['actual']['invented']=0
    elif corruption=='negative':data['forecast']['control_units_reserved']=-1
    elif corruption=='noninteger':data['actual']['guards_reserved']=True
    else:data['actual']['guards_completed']+=1
    with pytest.raises((ValueError,TypeError)):
        app._static_admission_accounting(data,bound,required=True)


def test_terminal_wrapper_absence_requires_explicit_baseline_mode(wrapper,produced):
    _,bound=wrapper
    assert app._static_admission_accounting(None,bound,required=False) is None
    with pytest.raises(ValueError,match='required'):
        app._static_admission_accounting(None,bound,required=True)
    assert app._static_admission_snapshot(None) is None
    assert app._production_execution_mode(produced['legacy_detailed'][0])=='BASELINE'


def test_production_activates_compiled_only_for_explicit_new_roots(produced):
    from ops_sim.v5.lifecycle_admission import BASELINE,COMPILED
    assert app.PRODUCTION_EXECUTION_MODE==COMPILED
    assert app._production_execution_mode(produced['legacy_detailed'][0])==BASELINE
    for name in ('detailed','quiet'):
        assert app._production_execution_mode(produced[name][0])==COMPILED
