"""Metadata-only acceptance regressions; no child, native load or day evaluation.

The real per-root DATA domain and durable provenance readers are exercised.
Scientific checkpoint validation and Linux execution qualification are explicit
test doubles: passing these tests is not genuine Linux qualification evidence.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from shutil import copytree
from types import SimpleNamespace

import pytest

from lifetime_support import root_for
from ops_sim.v5 import lifetime_typed_acceptance as acceptance
from ops_sim.v5 import lifetime_execution_authority as authority
from ops_sim.v5.portable_job import canonical, digest, parse


SOURCE_SHA='a'*64
SCIENCE=b'{"identical_scientific_history":"metadata fixture only"}'


def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(canonical(value))


class MetadataStore:
    def __init__(self,path,root,backend):
        self.directory=path;self.root_input=root;self.rows={};self.tip=None;self.closed=0
        self.runner_policy=SimpleNamespace(mode='LINUX_PRODUCTION',maximum_jobs=8)
        self.contract=dict(source_manifest_sha256=SOURCE_SHA,
            backend_binding=dict(selection=backend),native_build=dict(profile=acceptance.LINUX))
        _write(self.path('portable-execution.json'),self.contract)

    def path(self,*parts):return self.directory.joinpath(*parts)
    def job(self,jid):return deepcopy(self.rows[jid])
    def close_publications(self):self.closed+=1


def _job(store,number,*,parent=None,clock=None):
    jid=f'{number:032x}';worker=1000+number;creator=900
    cp=dict(sha256=f'{number:064x}',clock=store.root_input.end_seconds if clock is None else clock,
        kind='FINAL',file='checkpoint.json')
    resume=None if parent is None else dict(parent_job_id=parent['job_id'],checkpoint=deepcopy(parent['checkpoints'][-1]))
    intent=dict(mode='MAIN',parent_job_id=None if parent is None else parent['job_id'],
        snapshot_sha256=None if parent is None else resume['checkpoint']['sha256'])
    request=dict(format='METADATA_TEST_JOB',job_id=jid,intent=intent,root_identity=store.root_input.identity,
        source_identity='b'*64,runtime=dict(metadata='NOT_AN_ACTUAL_LINUX_RUN'),input_sha256='c'*64,resume=resume)
    request_raw=canonical(request);directory=store.path('jobs',jid);directory.mkdir(parents=True)
    (directory/'request.json').write_bytes(request_raw)
    dispatch=dict(format='B52_EXCLUSIVE_DISPATCH_OWNER_V1',owner=f'{number+100:032x}',
        PID=creator,source_identity=request['source_identity'])
    command=['metadata-test','--job',jid]
    launch_authority=dict(format='B63_IMMUTABLE_PARENT_LAUNCH_AUTHORITY_V1',job_id=jid,
        root_identity=request['root_identity'],source_identity=request['source_identity'],runtime=request['runtime'],
        request_sha256=digest(request_raw),dispatch_token=dispatch,command=command,started_utc='2026-10-19T00:00:00Z')
    _write(directory/'parent-launch-authority.json',launch_authority)
    cleanup=dict(owned_job_empty=True,root_signaled=True,root_status_captured=True,handles_closed=True,
        cleanup_within_two_seconds=True,root_exit_code=0,root_reaped=True,errors=[],cleanup_started_monotonic=1.,
        cleanup_wall_seconds=.1,cleanup_deadline_monotonic=3.,cleanup_within_deadline=True,
        backend='B60_COOPERATIVE_LINUX_SESSION_V1',owner_token=f'{number+200:032x}')
    identity=dict(worker_PID=worker,worker_PPID=creator,runtime=request['runtime'])
    launch=dict(cleanup=cleanup,worker_identity=identity,root_PID=worker,owned_seen_PIDs=[worker],
        command=command,forced_interruption=False,timeout=False,unexpected=None)
    settlement=dict(format='B60_DURABLE_BACKEND_SETTLEMENT_V1',job_id=jid,root_identity=request['root_identity'],
        source_identity=request['source_identity'],launch_command=command,root_launch_PID=worker,
        worker_identity=identity,owned_seen_PIDs=[worker],execution_start_monotonic=0.,
        envelope_to_completed_cleanup_seconds=1.1,scope='LAUNCH_TO_COMPLETED_OWNED_CLEANUP_NOT_LATER_PARENT_REPORTING',
        cleanup=cleanup)
    _write(directory/'backend-settlement.json',settlement)
    (directory/'endpoint.json').write_bytes(SCIENCE)
    result=dict(clock=cp['clock'],endpoint=dict(file='endpoint.json',sha256=digest(SCIENCE)),backend_execution={})
    row=dict(**request,status='COMPLETED',ownership_valid=True,launch=launch,checkpoints=[cp],result=result)
    store.rows[jid]=row;store.tip=jid
    if parent is not None:
        _write(directory/'direct-restore.json',dict(restored_clock=resume['checkpoint']['clock'],
            native_entry_monitor=dict(total_delta=0,delta=dict(start=0,step=0))))
    return row


@pytest.fixture
def stores(tmp_path,monkeypatch):
    from ops_sim.v5 import lifetime_supervisor,lifetime_campaign,lifecycle_backend,lifetime_server_acceptance
    root=root_for(86400)
    reference=MetadataStore(tmp_path/'reference',root,'REFERENCE');_job(reference,1)
    baseline=MetadataStore(tmp_path/'baseline',root,acceptance.METHOD);_job(baseline,2)
    continued=MetadataStore(tmp_path/'continuation',root,acceptance.METHOD)
    prefix=_job(continued,3,clock=root.start_seconds+10);_job(continued,4,parent=prefix)
    mapping={str(s.directory):s for s in (reference,baseline,continued)}
    monkeypatch.setattr(lifetime_supervisor,'_store',lambda path:(mapping[str(path)],{}))
    monkeypatch.setattr(lifetime_supervisor,'_summary',lambda store,plan:dict(parent_job_id=store.tip))
    monkeypatch.setattr(lifetime_campaign,'validate_settled_parent',lambda store,job:(
        dict(kind='TARGET' if job['result']['clock']==root.end_seconds else 'RESOURCE_TIME'),job['checkpoints'][-1],1.))
    monkeypatch.setattr(lifecycle_backend,'admit_backend_receipt',lambda receipt,contract:None)
    monkeypatch.setattr(lifetime_server_acceptance,'admit_acceptance',lambda *args:dict(metadata_double=True))
    monkeypatch.setattr(acceptance,'admit_build_data',lambda value:value)
    monkeypatch.setattr(acceptance,'admit_typed_build',lambda value:None)
    monkeypatch.setattr(acceptance.sys,'platform','linux')
    legacy=tmp_path/'legacy.json';_write(legacy,dict(reference_store=str(baseline.directory),continuation_store=str(continued.directory)))
    binding=dict(source_manifest_sha256=SOURCE_SHA,runtime=dict(metadata='fixture'),
        backend_binding=dict(selection=acceptance.METHOD),domain_identity=authority.domain_identity(root),
        original_anchor_seconds=root.start_seconds)
    value=dict(format=acceptance.FORMAT,qualification_binding=authority._qualification_binding(binding),
        legacy_day_evidence=authority.reference(legacy),python_reference_store=str(reference.directory),
        native_uninterrupted_store=str(baseline.directory),native_continuation_store=str(continued.directory))
    evidence=tmp_path/'genuine.json';_write(evidence,value)
    return SimpleNamespace(root=root,reference=reference,baseline=baseline,continued=continued,mapping=mapping,
        legacy=legacy,binding=binding,value=value,evidence=evidence)


def test_duration_only_domain_is_preserved():
    assert authority.domain_identity(root_for(86400))==authority.domain_identity(root_for(7200))
    root=root_for(86400)
    changed=replace(root,policy=replace(root.policy,max_control_units=root.policy.max_control_units-1))
    assert authority.domain_identity(root)!=authority.domain_identity(changed)
    battery=replace(root,battery_port_policy=replace(root.battery_port_policy,
        resistance_reference_ohm=root.battery_port_policy.resistance_reference_ohm*1.1))
    assert authority.domain_identity(root)!=authority.domain_identity(battery)


@pytest.mark.parametrize('key',['python_reference_store','native_uninterrupted_store','native_continuation_store'])
def test_each_actual_tested_root_is_rechecked_before_acceptance(stores,key):
    selected=stores.mapping[stores.value[key]]
    selected.root_input=replace(stores.root,policy=replace(stores.root.policy,max_control_units=stores.root.policy.max_control_units-1))
    with pytest.raises(ValueError,match='actual tested root domain'):
        acceptance.admit(stores.evidence,stores.binding)
    assert selected.closed==1


def test_mutually_equal_design_a_science_cannot_publish_design_b_acceptance(stores,tmp_path):
    binding=deepcopy(stores.binding)
    other=replace(stores.root,battery_port_policy=replace(stores.root.battery_port_policy,
        resistance_reference_ohm=stores.root.battery_port_policy.resistance_reference_ohm*1.1))
    binding['domain_identity']=authority.domain_identity(other)
    output=tmp_path/'refused-output'
    with pytest.raises(ValueError,match='actual tested root domain'):
        acceptance.produce(output,legacy_day_evidence=stores.legacy,
            python_reference_store=stores.reference.directory,
            qualification_binding=authority._qualification_binding(binding),binding=binding)
    assert not (output/'acceptance.json').exists()
    assert (output/'FAILURE.txt').exists()


def test_copied_complete_causal_history_is_not_an_independent_continuation(stores,tmp_path):
    copied=tmp_path/'copied-full-history';copytree(stores.continued.directory,copied)
    clone=deepcopy(stores.continued);clone.directory=copied
    stores.mapping[str(copied)]=clone
    # Both native roles now refer to the same actual completed history through
    # different directories; every endpoint remains byte-identical.
    value=deepcopy(stores.value);value['native_uninterrupted_store']=str(copied)
    _write(stores.legacy,dict(reference_store=str(copied),continuation_store=str(stores.continued.directory)))
    value['legacy_day_evidence']=authority.reference(stores.legacy);_write(stores.evidence,value)
    with pytest.raises(ValueError,match='independent causal histories'):
        acceptance.admit(stores.evidence,stores.binding)


def test_independent_serial_baseline_may_have_resource_bounded_resumes(stores):
    baseline=stores.baseline
    baseline.rows.clear()
    prefix=_job(baseline,5,clock=stores.root.start_seconds+20);_job(baseline,6,parent=prefix)
    result=acceptance.admit(stores.evidence,stores.binding)
    proof=result['causal_provenance']
    assert proof['format']=='B66_INDEPENDENT_SERIAL_BASELINE_AND_FRESH_CONTINUATION_V1'
    assert len(proof['histories'][1])==2
    assert proof['histories'][1][0]['process_owner']!=proof['histories'][2][0]['process_owner']


def test_shared_authentic_prefix_is_allowed_but_new_tip_owner_is_required(stores):
    prefix=deepcopy(stores.continued.rows[f'{3:032x}'])
    stores.baseline.rows.clear()
    stores.baseline.rows[prefix['job_id']]=prefix
    # Shared saved prefix is data authority, not a second execution. Preserve
    # its bound receipts while constructing a new independent terminal launch.
    copytree(stores.continued.path('jobs',prefix['job_id']),stores.baseline.path('jobs',prefix['job_id']))
    _job(stores.baseline,7,parent=prefix)
    assert acceptance.admit(stores.evidence,stores.binding)['computed_acceptance']=='PASS'


@pytest.mark.parametrize('name',['parent-launch-authority.json','backend-settlement.json','request.json'])
def test_authoritative_receipts_are_reread_not_caller_approved_flags(stores,name):
    acceptance.admit(stores.evidence,stores.binding)
    path=stores.baseline.path('jobs',stores.baseline.tip,name)
    value=parse(path.read_bytes())
    if name=='parent-launch-authority.json':value['request_sha256']='d'*64
    elif name=='backend-settlement.json':value['cleanup']['owner_token']='e'*32
    else:value['intent']['mode']='DIAGNOSTIC_VERBOSE'
    _write(path,value)
    with pytest.raises(ValueError,match='binding'):
        acceptance.admit(stores.evidence,stores.binding)


def test_continuation_owner_must_differ_from_every_baseline_segment(stores):
    first=acceptance._execution_history(stores.continued,stores.continued.job(stores.continued.tip))
    baseline=acceptance._execution_history(stores.baseline,stores.baseline.job(stores.baseline.tip))
    reference=acceptance._execution_history(stores.reference,stores.reference.job(stores.reference.tip))
    # Different job IDs/path cannot turn reused private process ownership into
    # an independent experiment.
    baseline[0]['process_owner']=first[0]['process_owner']
    with pytest.raises(ValueError,match='independent causal histories'):
        acceptance._independent_histories([reference,baseline,first])
