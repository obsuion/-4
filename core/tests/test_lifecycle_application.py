"""Synthetic application admission/ownership tests; no model transition calls."""
from copy import deepcopy
from hashlib import sha256
import json,threading,zipfile
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot
from ops_sim.v5.lifecycle_application import (LifecycleStore,LifecycleRunner,ProgressReader,make_intent,validate_intent,
    JOURNAL,_write_new,PUBLICATION,PUBLICATION_FIELDS)
import ops_sim.v5.lifecycle_application as owner


def setup_streamed(tmp_path):
    from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
    root=LifecycleRoot(make_inputs(wire='weakness'),600,output_policy=LifecycleStreamPolicy())
    return LifecycleStore(tmp_path/'chunked-store',root,create=True)


def test_versioned_status_has_no_legacy_4096_guard_and_reopens_read_only(tmp_path):
    store=setup_streamed(tmp_path);job,_=store.prepare_job(make_intent(store.root_input.identity,key='f'*32,maximum_output_bytes=256*2**20))
    directory=store.path('jobs',job['job_id'],'status53');first=(directory/'heads.bin').read_bytes()
    with (directory/'heads.bin').open('rb') as held:
        job.update(status='REFUSED',ownership_valid=True);store.update_job(job)
        assert held.read(len(first))==first
    store.close_publications();before={p.relative_to(store.directory).as_posix():p.read_bytes() for p in store.directory.rglob('*') if p.is_file()}
    reopened=LifecycleStore(store.directory);assert reopened.job(job['job_id'])['publication_sequence']==2
    assert before=={p.relative_to(store.directory).as_posix():p.read_bytes() for p in store.directory.rglob('*') if p.is_file()}
    assert not store.path('jobs',job['job_id'],'status').exists()


def test_b53_ui_input_compiler_keeps_named_assumptions_and_rejects_unknowns():
    policy,scenario,study,output=owner._requested_inputs({'quiet_solver':{},'latency_seconds':1},{},'COMMON_ASSUMED_V1',1,{'publication_minimum_wall_seconds':1})
    assert study.ageing_multiplier==1. and study.latency_seconds==policy.latency_seconds==1
    assert policy.quiet_solver is not None and output.publication_minimum_wall_seconds==1.
    for data in ({'quiet_solver':{'invented':True}},{'invented':True}):
        with pytest.raises((ValueError,TypeError)):owner._requested_inputs(data,{},'COMMON_ASSUMED_V1',1,{})
    with pytest.raises(ValueError):owner._requested_inputs({}, {}, 'COMMON_ASSUMED_V1',True,{})


def test_actual_refusal_schema_preserves_zero_numeric_margins():
    value=dict(action_id='a',kind='CAPTURE',status='refused',reason='VIEW_REJECTED',refusal_detail=dict(stage='VIEW',code='OFF_NADIR',owner='actual_view_owner',
        evaluated_calls=[['view',1]],quantities=[['margin_rad',0.]],method='B53_ACTUAL_ACQUISITION_REFUSAL_V1'))
    owner._last_action(value)
    for update in (dict(quantities=[['margin_rad',float('nan')]]),dict(evaluated_calls=[['view',0]]),dict(stage='FORECAST')):
        bad=deepcopy(value);bad['refusal_detail'].update(update)
        with pytest.raises(ValueError):owner._last_action(bad)


def test_chunked_progress_preserves_terminal_reserve_without_poisoning_writer(tmp_path):
    from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy,iter_stream_records
    p=LifecycleStreamPolicy(chunk_bytes=4096,max_record_bytes=1024,progress_total_bytes=327680)
    j=owner._ChunkJournal(tmp_path/'journal',dict(job_id='1'*32,root_identity='2'*64),p,lambda n:None)
    while j.regular_capacity>2000:j.emit('boundary',{'padding':'x'*500})
    with pytest.raises(ValueError,match='terminal reserve'):j.emit('boundary',{'padding':'x'*2000})
    assert not j.writer.failed
    j.emit('failure',{'reason':'expected injected ordinary quota refusal'},terminal=True);j.close()
    rows=list(iter_stream_records(tmp_path/'journal'));assert rows[-1]['kind']=='failure'


def test_plain_progress_reader_retains_new_root_method_without_chunked_output(tmp_path,monkeypatch):
    observed=[];raw={'kind':'boundary'};path=tmp_path/'plain.jsonl';path.write_text(json.dumps(raw)+'\n',encoding='utf-8')
    def validate(record,job,sequence,*,method,publication_minimum=1):
        observed.append((method,sequence));return record
    monkeypatch.setattr(owner,'_validate_progress',validate)
    reader=ProgressReader(path,{},1024,method='B53_ADAPTIVE_QUIET_CHRONOLOGICAL_NOMINAL_V1')
    assert reader.read()==[raw] and observed==[('B53_ADAPTIVE_QUIET_CHRONOLOGICAL_NOMINAL_V1',1)]


def test_chunked_checkpoint_catalog_page_and_paid_lookup_are_not_recent_list(tmp_path):
    store=setup_streamed(tmp_path);job,_=store.prepare_job(make_intent(store.root_input.identity,key='e'*32,maximum_output_bytes=256*2**20))
    catalog=store.checkpoint_catalog(job['job_id']);items=[]
    for n in range(1,21):
        cp=dict(file=f'checkpoint-{n:08}.json',sha256=f'{n:064x}',bytes=2,clock=128+n,bindings={},kind='WORKING',publication={})
        catalog.append(cp);items.append(cp)
    assert store.find_checkpoint(job['job_id'],items[0]['sha256'])==items[0]
    assert len(store.checkpoint_history(job['job_id'],limit=4)['entries'])==4
    catalog.retire(1,'DECLARED_LAST_TWO_WORKING_RETENTION')
    with pytest.raises(ValueError,match='retired'):store.find_checkpoint(job['job_id'],items[0]['sha256'])
    raw=store.path('jobs',job['job_id'],'parent-publication-work.bin').read_bytes()
    assert raw and len(raw)%owner.PARENT_COST.size==0
    store.close_publications()


def setup(tmp_path):
    root=LifecycleRoot(make_inputs(wire='weakness'),600)
    return LifecycleStore(tmp_path/'long-store',root,create=True)


class FakeOwnedJob:
    calls=[];hold=False;bad_cleanup=False;started=threading.Event()
    def __init__(self,command,cwd,env,out,err):
        assert command[1:5]==['-B','-m','ops_sim.v5.lifecycle_application','worker']
        assert env['PYTHONDONTWRITEBYTECODE']=='1' and env['TEMP']==env['TMP']
        self.pid=123;self.closed=False;self.assigned_before_resume=True
        type(self).calls.append(self);type(self).started.set()
    def state(self):return dict(job_active_PIDs=[123] if self.hold else [],job_active_count=int(self.hold))
    def poll(self):return None if self.hold else 0
    def reap(self,kill=False,**kwargs):
        self.kill=kill;self.closed=True
        return dict(owned_job_empty=not self.bad_cleanup,root_signaled=True,root_status_captured=True,
            handles_closed=True,errors=[],cleanup_within_two_seconds=True,root_exit_code=0)


def fake_runner(store):
    FakeOwnedJob.calls=[];FakeOwnedJob.hold=False;FakeOwnedJob.bad_cleanup=False;FakeOwnedJob.started.clear()
    return LifecycleRunner(store,job_factory=FakeOwnedJob)


@pytest.mark.parametrize('mutation',[
    lambda b:b.update(execution_seconds=True),lambda b:b.update(execution_seconds=1801),
    lambda b:b.update(maximum_output_bytes=0),lambda b:b.update(mode='UNKNOWN'),
    lambda b:b.update(parent_job_id='1'*32),lambda b:b.update(window_end_seconds=100),
    lambda b:b.update(unreviewed=True),lambda b:b.update(root_identity='x'*64)])
def test_exact_durable_intent_admission(mutation):
    body=make_intent('0'*64,key='1'*32);mutation(body)
    with pytest.raises((ValueError,TypeError)):validate_intent(body)


def test_reopen_is_read_only_and_exact_input_is_bound(tmp_path):
    store=setup(tmp_path);raw=(store.directory/'store.json').read_bytes();inp=(store.directory/'input.json').read_bytes()
    reopened=LifecycleStore(store.directory)
    assert reopened.root_input.identity==store.root_input.identity
    assert (store.directory/'store.json').read_bytes()==raw and (store.directory/'input.json').read_bytes()==inp
    assert not (store.directory/'jobs').exists()


def test_status_publications_append_without_replacing_reader_held_files(tmp_path):
    store=setup(tmp_path);intent=make_intent(store.root_input.identity,key='1'*32)
    job,new=store.prepare_job(intent);assert new
    first=store.path('jobs',job['job_id'],'status','00000001.json');before=first.read_bytes()
    with first.open('rb') as held:
        job['status']='REFUSED';job['ownership_valid']=True;store.update_job(job)
        assert held.read()==before
    assert first.read_bytes()==before and store.job(job['job_id'])['publication_sequence']==2
    assert len(list(first.parent.glob('*.json')))==2


def test_zero_exit_without_terminal_is_incomplete_and_duplicate_never_relaunches(tmp_path):
    store=setup(tmp_path);runner=fake_runner(store);intent=make_intent(store.root_input.identity,key='2'*32)
    job=runner.submit(intent);runner.thread.join(3)
    settled=store.job(job['job_id'])
    assert settled['status']=='INCOMPLETE' and settled['result'] is None and settled['ownership_valid'] is True
    assert runner.submit(intent)['job_id']==job['job_id'] and len(FakeOwnedJob.calls)==1
    changed=dict(intent,execution_seconds=419)
    with pytest.raises(ValueError,match='drift'):runner.submit(changed)
    runner.close()


def test_stop_reaps_only_owned_fake_handle_and_blocks_later_dispatch(tmp_path):
    store=setup(tmp_path);runner=fake_runner(store);FakeOwnedJob.hold=True
    job=runner.submit(make_intent(store.root_input.identity,key='3'*32));assert FakeOwnedJob.started.wait(3)
    runner.stop(job['job_id']);marker=store.path('jobs',job['job_id'],'stop-request.json');raw=marker.read_bytes()
    runner.stop(job['job_id']);assert marker.read_bytes()==raw
    runner.close()
    assert FakeOwnedJob.calls[0].kill and store.job(job['job_id'])['status']=='CANCELLED'
    assert store.job(job['job_id'])['launch']['forced_interruption'] is True
    with pytest.raises(ValueError,match='closed'):runner.submit(make_intent(store.root_input.identity,key='4'*32))
    FakeOwnedJob.hold=False


def test_main_resume_refuses_unknown_paid_suffix_after_forced_stop(tmp_path):
    store=setup(tmp_path);parent,_=store.prepare_job(make_intent(store.root_input.identity,key='a'*32))
    parent.update(status='CANCELLED',ownership_valid=True,launch=dict(forced_interruption=True));store.update_job(parent)
    runner=fake_runner(store)
    body=make_intent(store.root_input.identity,key='b'*32,parent_job_id=parent['job_id'],snapshot_sha256='0'*64)
    with pytest.raises(ValueError,match='UNKNOWN paid work'):runner.submit(body)
    assert not FakeOwnedJob.calls and len(store.jobs())==1
    runner.close()


@pytest.mark.parametrize('boundary',['source_admission','owned_factory'])
def test_stop_during_launch_does_not_stale_status_or_erase_stop_intent(tmp_path,monkeypatch,boundary):
    store=setup(tmp_path);runner=fake_runner(store)
    if boundary=='source_admission':
        original=store._pinned
        def pinned():
            original()
            if runner.active is not None:runner.stop(runner.active)
        monkeypatch.setattr(store,'_pinned',pinned)
    else:
        def factory(*args):
            child=FakeOwnedJob(*args);runner.stop(runner.active);return child
        runner.factory=factory
    job=runner.submit(make_intent(store.root_input.identity,key='7'*32));runner.thread.join(3)
    settled=store.job(job['job_id'])
    assert settled['status']=='CANCELLED' and settled['ownership_valid'] is True
    assert settled['launch']['stopped'] is True and 'parent_failure' not in settled
    assert store.path('jobs',job['job_id'],'stop-request.json').exists()
    if boundary=='source_admission':assert not FakeOwnedJob.calls
    else:assert len(FakeOwnedJob.calls)==1
    runner.close()


def test_unknown_cleanup_blocks_duplicate_new_dispatch(tmp_path):
    store=setup(tmp_path);runner=fake_runner(store);FakeOwnedJob.bad_cleanup=True
    job=runner.submit(make_intent(store.root_input.identity,key='5'*32));runner.thread.join(3)
    assert store.job(job['job_id'])['status']=='UNKNOWN'
    with pytest.raises(ValueError):runner.submit(make_intent(store.root_input.identity,key='6'*32))
    with pytest.raises(RuntimeError):runner.close()
    FakeOwnedJob.bad_cleanup=False


def test_source_mismatch_rejects_before_job_or_child(tmp_path,monkeypatch):
    store=setup(tmp_path);runner=fake_runner(store)
    monkeypatch.setattr(owner,'project_source_identity',lambda:'f'*64)
    with pytest.raises(ValueError,match='before work'):runner.submit(make_intent(store.root_input.identity,key='7'*32))
    assert not FakeOwnedJob.calls and not (store.directory/'jobs').exists()
    runner.close()


def test_corrupt_checkpoint_rejects_before_new_job_or_child(tmp_path):
    from ops_sim.v5.lifecycle_checkpoint import make_bindings
    store=setup(tmp_path);parent,_=store.prepare_job(make_intent(store.root_input.identity,key='8'*32))
    raw=b'{}';name='checkpoint-00000001.json';_write_new(store.path('jobs',parent['job_id'],name),raw)
    publication=dict(format=PUBLICATION,root_identity=store.root_input.identity,native_checkpoint_sha256=sha256(raw).hexdigest(),
        application_work={name:0 for name in PUBLICATION_FIELDS})
    sidecar=_write_new(store.path('jobs',parent['job_id'],'checkpoint-00000001-publication.json'),publication)
    cp=dict(file=name,sha256=sha256(raw).hexdigest(),bytes=len(raw),clock=200,bindings=make_bindings(store.root_input,200),kind='PENDING_PARTIAL_CONTACT',publication=sidecar)
    parent.update(status='COMPLETED',ownership_valid=True,checkpoints=[cp]);store.update_job(parent)
    runner=fake_runner(store);body=make_intent(store.root_input.identity,key='9'*32,parent_job_id=parent['job_id'],snapshot_sha256=cp['sha256'])
    with pytest.raises((ValueError,TypeError,KeyError)):runner.submit(body)
    assert len(store.jobs())==1 and not FakeOwnedJob.calls
    runner.close()


def test_separate_cli_runner_cannot_dispatch_while_owned_token_exists(tmp_path):
    store=setup(tmp_path);first=fake_runner(store);FakeOwnedJob.hold=True
    job=first.submit(make_intent(store.root_input.identity,key='d'*32));assert FakeOwnedJob.started.wait(3)
    second=LifecycleRunner(LifecycleStore(store.directory),job_factory=FakeOwnedJob)
    with pytest.raises(ValueError,match='existing lifecycle dispatch owner'):second.submit(make_intent(store.root_input.identity,key='e'*32))
    assert len(FakeOwnedJob.calls)==1
    first.stop(job['job_id']);first.close();second.close();FakeOwnedJob.hold=False
    assert not store.path('dispatch-owner.json').exists()


def test_foreign_unknown_dispatch_token_is_preserved_and_never_controls_pid(tmp_path):
    store=setup(tmp_path);runner=fake_runner(store);path=store.path('dispatch-owner.json')
    original=b'{"PID":999999,"format":"foreign-data-not-authority"}';path.write_bytes(original)
    with pytest.raises(ValueError,match='requires reconciliation'):runner.submit(make_intent(store.root_input.identity,key='f'*32))
    runner.close()
    assert path.read_bytes()==original and not FakeOwnedJob.calls and not (store.directory/'jobs').exists()


def test_incremental_complete_records_and_explicit_partial_tail(tmp_path):
    job=dict(job_id='a'*32,root_identity='b'*64,runtime=dict(test='synthetic'))
    def row(n):return dict(format=JOURNAL,sequence=n,job_id=job['job_id'],root_identity=job['root_identity'],kind='identity',
        data=dict(worker_PID=12,worker_PPID=11,runtime=job['runtime']))
    one=json.dumps(row(1)).encode()+b'\n';two=json.dumps(row(2)).encode()+b'\n';path=tmp_path/'journal'
    path.write_bytes(one+two[:10]);reader=ProgressReader(path,job,2**20)
    assert len(reader.read())==1 and reader.tail
    with path.open('ab') as f:f.write(two[10:])
    assert len(reader.read())==1 and not reader.tail and reader.read()==[]
    with path.open('ab') as f:f.write(two)
    with pytest.raises(ValueError,match='sequence'):reader.read()


def test_export_contains_input_manifest_and_settled_records_without_execution(tmp_path):
    store=setup(tmp_path);runner=fake_runner(store)
    job=runner.submit(make_intent(store.root_input.identity,key='c'*32));runner.thread.join(3);runner.close()
    export=store.export(job['job_id'])
    with zipfile.ZipFile(export['path']) as archive:
        assert archive.testzip() is None
        manifest=json.loads(archive.read('MANIFEST.json'))
        assert set(manifest)==set(archive.namelist())-{'MANIFEST.json'}
        for name,record in manifest.items():
            raw=archive.read(name);assert record==dict(bytes=len(raw),sha256=sha256(raw).hexdigest())
    assert len(FakeOwnedJob.calls)==1
