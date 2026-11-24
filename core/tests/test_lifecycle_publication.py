"""Real worker publication/reader components with one explicit injected error.

No owned-child/Windows acceptance is claimed here. The numerical transition
is deliberately not entered; actual startup, native checkpoints, journals,
strict readers, settlement and export are exercised in the focused test gate.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json,zipfile

import pytest

from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
import ops_sim.v5.lifecycle_application as app


@pytest.fixture(scope='module')
def publication_root():
    return LifecycleRoot(make_inputs(wire='nominal'),120,output_policy=LifecycleStreamPolicy())


def test_actual_failure_prefix_publication_exact_settlement_and_resume_admission(tmp_path,monkeypatch,publication_root):
    import ops_sim.v5.lifecycle_execution as execution
    import ops_sim.v5.project_offline_guard as offline
    root=publication_root
    store=app.LifecycleStore(tmp_path/'store',root,create=True)
    parent,_=store.prepare_job(app.make_intent(root.identity,key='a'*32,maximum_output_bytes=256*2**20))
    directory=store.path('jobs',parent['job_id']);request=directory/'request.json'
    def expected_failure(state):
        state.work.reserve_transition(root.policy);state.work.failed_transitions+=1
        raise ArithmeticError('B54 deterministic publication regression injection')
    monkeypatch.setattr(execution,'step_lifecycle',expected_failure)
    # The focused gate retains its own offline guard. Do not globally mutate
    # socket implementations for unrelated tests in the same pytest process.
    monkeypatch.setattr(offline,'block_network',lambda:None)
    with pytest.raises(ArithmeticError,match='regression injection'):
        app.execute_worker(store.directory,parent['job_id'],sha256(request.read_bytes()).hexdigest())
    failure=json.loads((directory/'failure.json').read_bytes())
    receipt=json.loads((directory/'application-work-final.json').read_bytes())
    reader=app.ProgressReader(directory/'progress53',parent,root.output_policy.progress_total_bytes,
        output_policy=root.output_policy,method=root.method)
    records=reader.read();assert not reader.tail
    checkpoints=[r['data']for r in records if r['kind']=='checkpoint']
    assert records[-1]['kind']=='failure' and len(checkpoints)==2
    cp=checkpoints[-1]
    assert failure['last_checkpoint']==cp and cp['kind']=='FAILURE_PAID_PREFIX'
    assert failure['updated_paid_prefix_checkpoint'] is True and failure['failure_prefix_publication_error'] is None
    assert failure['paid_model_work']['transitions_reserved']==failure['paid_model_work']['failed_transitions']==1
    assert failure['execution_timing']['calls']['start']['returned']==1
    assert failure['execution_timing']['calls']['step']['raised']==1
    assert failure['execution_timing']['restart_authority'] is False
    prefix=app._publication_document(directory,cp,root)
    assert prefix['format']==app.PUBLICATION54
    assert prefix['scope']=='BEFORE_CHECKPOINT_PROGRESS_PUBLICATION'
    assert prefix['application_work']!=failure['application_work']
    expected_failure_work=app._advance_publication_work(prefix['application_work'],prefix['stream_charges'],failure['stream_charges'],True)
    assert expected_failure_work==failure['application_work']
    settled=app._admit_failure_publication(directory,cp,root,failure,parent)
    assert settled==receipt['application_work']
    assert settled['stream_encoded_bytes_reserved']>failure['application_work']['stream_encoded_bytes_reserved']
    assert settled['stream_publication_attempts']>failure['application_work']['stream_publication_attempts']
    assert app._admit_publication(directory,cp,root,settled=True)==settled

    # Replay actual checkpoint records into the real parent catalog. This is
    # component readback; ownership status below is explicitly synthetic.
    for checkpoint in checkpoints:store.checkpoint_catalog(parent['job_id']).append(checkpoint)
    parent.update(status='PROCESS_FAILED',reason='EXPECTED_TEST_INJECTION',ownership_valid=True,
        launch={'forced_interruption':False},checkpoints=checkpoints)
    store.update_job(parent)
    resumed,new=store.prepare_job(app.make_intent(root.identity,key='b'*32,parent_job_id=parent['job_id'],
        snapshot_sha256=cp['sha256'],maximum_output_bytes=256*2**20))
    assert new and resumed['resume']['checkpoint']==cp and resumed['status']=='QUEUED'
    assert not (store.path('jobs',resumed['job_id'])/'application-work-final.json').exists()
    exported=store.export(parent['job_id'])
    with zipfile.ZipFile(exported['path'])as archive:
        manifest=json.loads(archive.read('MANIFEST.json'))
        for name in ('application-work-final.json','failure.json',cp['publication']['file']):
            member='jobs/'+parent['job_id']+'/'+name
            assert sha256(archive.read(member)).hexdigest()==manifest[member]['sha256']

    receipt_path=directory/'application-work-final.json';original=receipt_path.read_bytes()
    for corruption in ('extra','source','record','ledger','reservation','native_work','unclosed'):
        value=deepcopy(receipt)
        if corruption=='extra':value['invented']=True
        elif corruption=='source':value['source_identity']='0'*64
        elif corruption=='record':value['record']['sha256']='0'*64
        elif corruption=='ledger':value['application_work']['stream_encoded_bytes_reserved']+=1
        elif corruption=='reservation':value['stream_charges']['progress']['reservation_attempts']+=1
        elif corruption=='native_work':value['stream_work']['progress']['encoded_bytes_reserved']+=1
        else:value['publication_closed']=False
        receipt_path.write_bytes(app._bytes(value))
        with pytest.raises((ValueError,TypeError)):
            app._admit_failure_publication(directory,cp,root,failure,parent)
        receipt_path.write_bytes(original)
    # An incomplete atomic receipt is never replaced by an inferred ledger.
    receipt_path.rename(directory/'incomplete-test-receipt.saved')
    with pytest.raises(FileNotFoundError):app._admit_publication(directory,cp,root,settled=True)
    (directory/'incomplete-test-receipt.saved').rename(receipt_path)
    store.close_publications()


def test_exact_publication_delta_rejects_even_monotone_unrelated_counter_changes():
    before={name:dict(encoded_bytes_reserved=0,reservation_attempts=0)for name in app.STREAM_NAMES54}
    after=deepcopy(before);after['progress']=dict(encoded_bytes_reserved=1274,reservation_attempts=1)
    base={name:0 for name in app.PUBLICATION_FIELDS53}
    expected=app._advance_publication_work(base,before,after,True)
    assert expected['stream_encoded_bytes_reserved']==1274 and expected['stream_publication_attempts']==1
    assert expected['checkpoint_storage_reserved_bytes']==0
    bad=deepcopy(before);bad['progress']=dict(encoded_bytes_reserved=1300,reservation_attempts=1)
    with pytest.raises(ValueError,match='refund'):app._advance_publication_work(base,bad,after,True)


def test_disjoint_public_timers_forward_once_and_retain_original_exception():
    wall=iter((0,10,30,40,60,80));cpu=iter((0,2,5,6,9,12))
    timing=app._InvocationTiming(lambda:next(wall),lambda:next(cpu));calls=[]
    def returned(*args,**kwargs):calls.append((args,kwargs));return 'unchanged'
    assert timing.call('start',returned,1,flag='kept')=='unchanged'
    original=ArithmeticError('expected timing test injection')
    def raised():calls.append('raised');raise original
    with pytest.raises(ArithmeticError)as error:timing.call('step',raised)
    assert error.value is original and calls==[((1,),{'flag':'kept'}),'raised']
    saved=timing.snapshot()
    assert saved['calls']['start']==dict(attempted=1,returned=1,raised=0,wall_ns=20,worker_cpu_ns=3)
    assert saved['calls']['step']==dict(attempted=1,returned=0,raised=1,wall_ns=20,worker_cpu_ns=3)
    assert saved['observed_wall_ns']==80 and saved['unclassified_wall_ns']==40
    assert saved['observed_worker_cpu_ns']==12 and saved['restart_authority'] is False


def test_early_native_restore_merges_later_settled_static_work_without_science_changes(publication_root):
    from ops_sim.v5.lifecycle_admission import COMPILED,MAX_WRAPPER_UNITS
    from ops_sim.v5.lifecycle_execution import start_lifecycle,step_lifecycle,scientific_projection
    from ops_sim.v5.lifecycle_checkpoint import checkpoint_bytes,make_bindings,restore_checkpoint
    root=publication_root;parent=start_lifecycle(root,execution_mode=COMPILED)
    bindings=make_bindings(root,parent.clock);encoded=checkpoint_bytes(parent,bindings)
    selected=json.loads(encoded)['wrapper']
    parent,_,_=step_lifecycle(parent)
    whole=parent.compiled_context.to_data()
    assert whole['actual']['guards_reserved']>selected['actual']['guards_reserved']
    restored,proof=restore_checkpoint(encoded,root,sha256(encoded).hexdigest(),bindings)
    assert proof['retained_prior_static_admission_wrapper']==selected
    before=restored.compiled_context.to_data();science=deepcopy(scientific_projection(restored))
    runtime=deepcopy(asdict(restored.physical.runtime_work));forecast_runtime=deepcopy(asdict(restored.forecast_runtime))
    merge=app._merge_static_admission_work(restored,selected,whole)
    merged=restored.compiled_context.to_data()
    for role in ('actual','forecast'):
        for name in merged[role]:
            assert merged[role][name]==whole[role][name]+before[role][name]-selected[role][name]
    assert merge['merged']==merged and scientific_projection(restored)==science
    assert asdict(restored.physical.runtime_work)==runtime and asdict(restored.forecast_runtime)==forecast_runtime
    later=checkpoint_bytes(restored,make_bindings(root,restored.clock))
    persisted=json.loads(later)['wrapper']
    assert persisted==restored.compiled_context.to_data()
    for role in ('actual','forecast'):
        for name in merged[role]:assert persisted[role][name]>=merged[role][name]
    # Both ledgers are admitted together: invalid forecast authority/quota
    # cannot partially update ACTUAL. These are rejected synthetic mutations.
    for corruption in ('source','refund','forecast_quota'):
        bad=deepcopy(whole)
        if corruption=='source':bad['source_identity']='0'*64
        elif corruption=='refund':bad['actual']['control_units_reserved']=0
        else:bad['forecast']['control_units_reserved']=MAX_WRAPPER_UNITS
        unchanged=deepcopy(restored.compiled_context.to_data())
        with pytest.raises((ValueError,TypeError)):app._merge_static_admission_work(restored,selected,bad)
        assert restored.compiled_context.to_data()==unchanged


def test_secondary_failure_observation_preserves_original_error_and_denies_prefix_trust(tmp_path,monkeypatch,publication_root):
    import ops_sim.v5.lifecycle_execution as execution
    import ops_sim.v5.project_offline_guard as offline
    root=publication_root;store=app.LifecycleStore(tmp_path/'observer-error-store',root,create=True)
    job,_=store.prepare_job(app.make_intent(root.identity,key='c'*32,maximum_output_bytes=256*2**20))
    directory=store.path('jobs',job['job_id']);request=directory/'request.json'
    original=ArithmeticError('B54 primary test exception')
    def primary(state):raise original
    def secondary(state):raise RuntimeError('B54 secondary observation injection')
    monkeypatch.setattr(execution,'step_lifecycle',primary)
    monkeypatch.setattr(offline,'block_network',lambda:None)
    monkeypatch.setattr(app,'_static_admission_snapshot',secondary)
    with pytest.raises(ArithmeticError)as caught:
        app.execute_worker(store.directory,job['job_id'],sha256(request.read_bytes()).hexdigest())
    assert caught.value is original
    failure=json.loads((directory/'failure.json').read_bytes())
    assert failure['reason']==str(original) and 'primary test exception'in failure['traceback']
    assert failure['static_admission_wrapper']is None
    assert 'secondary observation injection'in failure['observation_errors']['static_admission_wrapper']
    with pytest.raises(ValueError,match='incomplete'):
        app._admit_failure_publication(directory,failure['last_checkpoint'],root,failure,job)
    store.close_publications()
