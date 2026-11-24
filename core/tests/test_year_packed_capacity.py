"""Prospective FILE/index/terminal grants on synthetic producer bytes only."""
from dataclasses import replace
from hashlib import sha256
import json
import os

import pytest

from ops_sim.v5 import lifetime_physical_storage as storage
from ops_sim.v5 import lifetime_incremental_pool as pool
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,METHOD_PACKED,METHOD_PHYSICAL,QUALIFICATION


def policy():
    return LifetimeCampaignPolicyV2(method=METHOD_PACKED,mode=QUALIFICATION,
        maximum_primary_segments=2,reserved_diagnostic_slots=1,
        hard_seconds=60,soft_seconds=8,finalization_seconds=52)


def binding(p=None,name='study'):
    p=policy()if p is None else p
    return dict(root_identity='a'*64,source_identity='b'*64,input_sha256='c'*64,
                policy_identity=p.identity,store_name=name)


@pytest.fixture
def owner(tmp_path):
    with storage.PhysicalStorage(tmp_path,policy(),binding(),create=True)as value:yield value


def reserve(owner,token='d',scope='study/jobs/one',kind='SEGMENT'):
    operation=token*64;producer=dict(kind=kind)
    owner.reserve(operation,'RETAINED',2**20,producer,scope=scope,
                  maximum_files=storage.PACKED_SEGMENT_FILES)
    return operation,producer


def write(owner,name,data=b'synthetic durable producer bytes'):
    owner.register_path(name);path=owner.root/name
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path


def seal(owner,operation,producer,tip=None):
    scope=owner.db.execute('SELECT scope FROM grants WHERE operation=?',(operation,)).fetchone()[0]
    proof=dict(format=storage.SETTLEMENT_PACKED,binding=owner.binding,producer=producer,
               scope=scope,closed=True,ownership_valid=True,uncertain_suffix=False)
    return owner.seal(operation,owner.producer_inventory(operation),producer=producer,settlement=proof,tip=tip)


def test_new_contract_is_explicit_and_does_not_raise_legacy_file_caps():
    new=storage.contract(policy());old=storage.contract(replace(policy(),method=METHOD_PHYSICAL))
    assert new['format']==storage.CONTRACT_PACKED
    assert new['whole_study_commitment_bytes']==7680*2**20<8*2**30
    assert old['global_retained_cap_bytes']==3072*2**20
    assert new['global_retained_cap_bytes']==2560*2**20
    assert new['full_defined_backup_cap_bytes']==2560*2**20
    assert new['maximum_temporary_overlap_bytes']==704*2**20
    assert storage.MAX_FILES==32768 and storage.MAX_OPERATION_FILES==4096


def test_segment_namespace_escrow_exists_before_producer_body(owner):
    before=owner.namespace_snapshot();operation,_=reserve(owner)
    after=owner.namespace_snapshot()
    assert after['unused_unsettled_file_slots']-before['unused_unsettled_file_slots']==515
    assert after['unsettled_terminal_index_rows']>=storage.PACKED_TERMINAL_INDEX_ROWS
    assert after['unsettled_metadata_pages']>=storage.PACKED_SEGMENT_METADATA_PAGES
    assert not(owner.root/'study/jobs/one').exists()
    assert owner.db.execute('SELECT state,phase FROM packed_namespace WHERE operation=?',(operation,)).fetchone()==('RESERVED','ORDINARY')


def test_ordinary_names_cannot_consume_terminal_file_escrow(owner):
    operation,_=reserve(owner)
    # Exercise the actual declared boundary. Changing a contract constant
    # during this test would correctly make a second owner reopen refuse.
    ordinary=storage.PACKED_SEGMENT_FILES-storage.PACKED_TERMINAL_FILES
    for number in range(ordinary):write(owner,'study/jobs/one/'+str(number)+'.bin')
    refused=owner.root/'study/jobs/one/refused.bin'
    with pytest.raises(ValueError,match='terminal namespace'):write(owner,'study/jobs/one/refused.bin')
    assert not refused.exists()
    storage.activate_terminal_for_job_directory(owner.root/'study/jobs/one')
    write(owner,'study/jobs/one/terminal-checkpoint.json',b'{"paid":true}')
    assert owner.db.execute('SELECT phase FROM packed_namespace WHERE operation=?',(operation,)).fetchone()==('TERMINAL',)


def test_unknown_holds_unused_namespace_and_does_not_admit_new_writes(owner):
    operation,_=reserve(owner);before=owner.namespace_snapshot();owner.mark_unknown(operation)
    after=owner.namespace_snapshot()
    assert after['unused_unsettled_file_slots']==before['unused_unsettled_file_slots']
    assert after['unsettled_metadata_pages']==before['unsettled_metadata_pages']
    assert after['unknown_escrows']==1
    assert owner.admission_status(1)['reason']==storage.UNKNOWN_UNSETTLED_PRODUCER
    with pytest.raises(ValueError,match=storage.UNKNOWN_UNSETTLED_PRODUCER):
        reserve(owner,token='e',scope='study/jobs/two')
    assert not(owner.root/'study/jobs/two').exists()
    with pytest.raises(ValueError,match='UNKNOWN'):write(owner,'study/jobs/one/after-unknown.bin')


def test_metadata_exhaustion_refuses_before_next_segment_and_is_not_byte_exhaustion(owner):
    operation,_=reserve(owner)
    owner.db.execute('UPDATE packed_namespace SET metadata_pages=? WHERE operation=?',
                     (storage.MAX_DATABASE_PAGES,operation))
    result=owner.admission_status(1)
    assert result['admitted']is False and result['reason']==storage.GLOBAL_NAMESPACE_EXHAUSTED
    assert owner.can_admit_segment(1)is False
    assert not(owner.root/'study/jobs/two').exists()


def test_file_exhaustion_refuses_before_numerical_body(owner,monkeypatch):
    reserve(owner)
    monkeypatch.setattr(storage,'MAX_FILES',600)
    result=owner.admission_status(1)
    assert result['admitted']is False and result['reason']==storage.GLOBAL_NAMESPACE_EXHAUSTED


def test_proved_seal_releases_unused_escrow_but_preserves_cumulative_names(owner):
    operation,producer=reserve(owner)
    write(owner,'study/jobs/one/value.bin')
    before=owner.namespace_snapshot();seal(owner,operation,producer,tip=dict(clock=12))
    after=owner.namespace_snapshot()
    assert after['unused_unsettled_file_slots']==storage.PACKED_MUTABLE_FILES
    assert after['unused_persistent_mutable_file_slots']==storage.PACKED_MUTABLE_FILES
    assert after['cumulative_file_names']==before['cumulative_file_names']==1
    assert after['cumulative_directory_names']==before['cumulative_directory_names']
    assert after['unsettled_metadata_pages']==storage.PACKED_SEGMENT_METADATA_PAGES
    assert owner.db.execute('SELECT sequence FROM packed_pool_seals').fetchall()==[(1,)]
    assert owner.snapshot()['tip']==dict(clock=12)


def test_unlisted_orphan_prevents_seal_and_preserves_tip_and_reservations(owner):
    operation,producer=reserve(owner)
    write(owner,'study/jobs/one/value.bin')
    (owner.root/'study/jobs/one/orphan.bin').write_bytes(b'unregistered')
    before=owner.snapshot()
    with pytest.raises(ValueError):seal(owner,operation,producer,tip=dict(clock=999))
    after=owner.snapshot()
    assert after['tip']==before['tip'] and after['still_reserved_active_writes']==before['still_reserved_active_writes']
    assert owner.db.execute('SELECT COUNT(*) FROM packed_pool_seals').fetchone()==(0,)


def pool_owner(tmp_path):
    p=policy();b=binding(p,name='a'*64);key=storage.digest(b)
    owners=storage.pool_owners(tmp_path/b['store_name'],key)
    pool.reserve_pool(tmp_path,key,p,owners=owners,pool_bytes=8*2**30,windows=os.name=='nt')
    return p,b,key,owners


def test_pool_fixed_slot_credit_requires_positive_owner_and_native_allocation(tmp_path):
    p,b,key,owners=pool_owner(tmp_path)
    with storage.PhysicalStorage(tmp_path,p,b,create=True)as value:
        pool.mark_owner_initialized(tmp_path,key,windows=os.name=='nt')
        op,producer=reserve(value,scope=b['store_name']+'/jobs/one')
        write(value,b['store_name']+'/jobs/one/value.bin')
        seal(value,op,producer)
        first=pool.reserve_pool(tmp_path,key,p,owners=owners,pool_bytes=8*2**30,windows=os.name=='nt')
        assert first['new_sealed_files_verified']==1 and first['credited_physical_bytes']>0
        second=pool.reserve_pool(tmp_path,key,p,owners=owners,pool_bytes=8*2**30,windows=os.name=='nt')
        assert second['new_sealed_files_verified']==0 and second['historical_file_bytes_read']==0
        assert second['credited_physical_bytes']==first['credited_physical_bytes']
        slot=tmp_path/pool.FOLDER/(key+'.json');raw=json.loads(slot.read_bytes())
        raw['credit_bytes']+=4096;slot.write_bytes(storage.encoded(raw))
        with pytest.raises(ValueError,match='positive committed'):pool.reserve_pool(tmp_path,key,p,owners=owners,pool_bytes=8*2**30,windows=os.name=='nt')


def test_pool_unknown_pending_or_orphan_is_not_silently_repaired(tmp_path):
    p,b,key,owners=pool_owner(tmp_path)
    slot=tmp_path/pool.FOLDER/(key+'.json');before=slot.read_bytes()
    slot.with_name(slot.name+'.pending').write_bytes(b'partial')
    with pytest.raises(ValueError,match='pending|unfinished|unindexed'):pool.reserve_pool(tmp_path,key,p,owners=owners,pool_bytes=8*2**30,windows=os.name=='nt')
    assert slot.read_bytes()==before


def test_pool_owner_loss_after_positive_initialized_marker_never_falls_back(tmp_path):
    p,b,key,owners=pool_owner(tmp_path)
    with storage.PhysicalStorage(tmp_path,p,b,create=True):pool.mark_owner_initialized(tmp_path,key,windows=os.name=='nt')
    database=tmp_path/(b['store_name']+'.physical.sqlite3');database.unlink()
    with pytest.raises(ValueError,match='disappeared'):pool.reserve_pool(tmp_path,key,p,owners=owners,pool_bytes=8*2**30,windows=os.name=='nt')


def test_copied_pool_namespace_needs_explicit_verified_import(tmp_path):
    import shutil
    original=tmp_path/'original';original.mkdir();pool_owner(original)
    copy=tmp_path/'copy';shutil.copytree(original,copy)
    with pytest.raises(ValueError,match='namespace/volume'):pool.workspace_entries(copy)


@pytest.mark.parametrize('stage',('BEFORE_COMMIT','AFTER_DURABLE_COMMIT_BEFORE_ACK'))
def test_commit_failure_evidence_matches_actual_durable_tip(owner,tmp_path,monkeypatch,stage):
    operation,producer=reserve(owner);write(owner,'study/jobs/one/value.bin')
    before=owner.snapshot();commit=owner._commit
    def fail():
        if stage=='AFTER_DURABLE_COMMIT_BEFORE_ACK':commit()
        raise OSError('injected '+stage)
    monkeypatch.setattr(owner,'_commit',fail)
    with pytest.raises(OSError,match='injected')as failure:
        seal(owner,operation,producer,tip=dict(clock=25))
    monkeypatch.setattr(owner,'_commit',commit)
    if stage=='BEFORE_COMMIT':owner.mark_unknown(operation)
    with storage.PhysicalStorage(owner.root,policy(),binding())as reopened:
        after=reopened.snapshot()
        state=reopened.db.execute('SELECT state FROM grants WHERE operation=?',(operation,)).fetchone()[0]
        if stage=='BEFORE_COMMIT':
            assert after['tip']==before['tip'] and state=='UNKNOWN'
            assert after['still_reserved_active_writes']==before['still_reserved_active_writes']
            assert reopened.namespace_snapshot()['unknown_escrows']==1
        else:
            assert after['tip']==dict(clock=25) and state=='SEALED'
            assert reopened.db.execute('SELECT COUNT(*) FROM packed_pool_seals').fetchone()==(1,)
    evidence=dict(format='YEAR_V5_SYNTHETIC_COMMIT_FAILURE_V1',stage=stage,
        actual_error=type(failure.value).__name__+': '+str(failure.value),
        before=before,reopened=after,reopened_grant_state=state,
        semantics='FAILURE_PRESERVED; DURABLE_COMMIT_IS_NOT_REPORTED_AS_ROLLBACK_OR_SUCCESSFUL_CALL')
    (tmp_path/('FAULT-'+stage+'.json')).write_bytes(storage.encoded(evidence))


def test_actual_serial_supervisor_unknown_halt_never_dispatches_or_retries(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from ops_sim.v5 import lifecycle_application as app
    from ops_sim.v5 import lifetime_supervisor as supervisor
    from ops_sim.v5 import lifetime_execution_authority as authority
    from ops_sim.v5 import lifetime_no_launch as no_launch
    from ops_sim.v5.lifetime_journal import Journal
    p=policy();study=tmp_path/'study'
    with storage.PhysicalStorage(tmp_path,p,binding(p),create=True)as own:
        own.reserve('f'*64,'RETAINED',128*1024,
            dict(kind='STATIC_AND_BOUNDED_ROOT_CONTROL'),scope='study',maximum_files=128)
        operation,producer=reserve(own,scope='study/jobs/prefix',kind='SYNTHETIC_PREFIX')
        prefix=write(own,'study/jobs/prefix/prefix.bin',b'last-proved-prefix')
        seal(own,operation,producer,tip=dict(clock=17))
        pending,_=reserve(own,token='e',scope='study/jobs/unknown')
        own.mark_unknown(pending)
    launched=[]
    class Runner:
        active=None;thread=None
        def __init__(self,*args,**kwargs):pass
        def submit(self,intent):
            launched.append(intent);raise AssertionError('UNKNOWN must halt before dispatch')
    fake=SimpleNamespace(directory=study,runner_policy=p,
        meta={key:value for key,value in binding(p).items()if key!='store_name'},
        root_input=SimpleNamespace(start_seconds=0,end_seconds=86400,identity='a'*64),
        jobs=lambda:[],path=lambda*parts:study.joinpath(*parts))
    summary=dict(parent_job_id=None,primary_jobs=0,observed_seconds=0,
                 reserved_unknown_seconds=0,clock=17)
    monkeypatch.setattr(app,'LifecycleRunner',Runner)
    monkeypatch.setattr(authority,'admit_store_execution',lambda store:None)
    monkeypatch.setattr(no_launch,'enabled',lambda policy:False)
    monkeypatch.setattr(supervisor,'_reserve_pool',lambda store,plan:None)
    monkeypatch.setattr(supervisor,'_summary',lambda store,plan:dict(summary))
    monkeypatch.setattr(supervisor,'_close_session',lambda store,runner=None:None)
    plan=dict(plan_identity='e'*64)
    for _ in range(2):
        assert supervisor._run_locked(fake,plan,explicit_continue=True,on_launch=None,
            on_finish=None,stop_when=None,job_factory=None)['clock']==17
    records=list(Journal(fake,plan).records())
    halts=[record for record in records if record['action']=='HALT']
    assert len(halts)==2
    assert all(record['data']['reason']==storage.UNKNOWN_UNSETTLED_PRODUCER and
               record['data']['automatic_retry']is False for record in halts)
    assert not any(record['action']=='DISPATCH'for record in records)and launched==[]
    assert prefix.read_bytes()==b'last-proved-prefix'
    with storage.open_for_store(fake)as own:
        assert own.snapshot()['tip']==dict(clock=17)
        assert own.namespace_snapshot()['unknown_escrows']==1
    (tmp_path/'UNKNOWN-SUPERVISOR-NO-LAUNCH.json').write_bytes(storage.encoded(dict(
        format='YEAR_V5_SYNTHETIC_UNKNOWN_NO_LAUNCH_V1',dispatches=launched,
        halt_records=halts,tip=dict(clock=17),unknown_escrows=1)))


@pytest.mark.parametrize('critical_status',('PROCESS_FAILED','STOP_REQUESTED'))
def test_parent_critical_publication_spends_real_reserved_names_without_worker_checkpoint(owner,critical_status):
    from types import SimpleNamespace
    from ops_sim.v5 import lifetime_status as status
    from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
    operation,_=reserve(owner)
    ordinary=storage.PACKED_SEGMENT_FILES-storage.PACKED_TERMINAL_FILES
    for number in range(ordinary):write(owner,'study/jobs/one/'+str(number)+'.bin')
    assert owner.db.execute('SELECT phase FROM packed_namespace WHERE operation=?',(operation,)).fetchone()==('ORDINARY',)
    class Writer:
        def __init__(self,*args,**kwargs):self.sequence=0;self.head=SimpleNamespace(closed=False)
        def publish(self,value,*,terminal=False):self.sequence+=1;return self.sequence
        def close(self):self.head.closed=True
    value=dict(format='B59_FINITE_OWNED_LIFECYCLE_JOB_V1',job_id='1'*32,
        intent=dict(root_identity='a'*64,idempotency_key='3'*32,parent_job_id=None,
                    mode='NORMAL',maximum_output_bytes=128*2**20),
        root_identity='a'*64,source_identity='b'*64,runtime=dict(implementation='CPython',version=[3,14,7]),
        input_sha256='c'*64,resume=None,publication_sequence=0,status=critical_status,
        reason='synthetic parent terminal before worker checkpoint',progress=dict(padding='x'*7000),
        checkpoints=[],result=None,launch=None,ownership_valid=None,
        created_utc='2026-10-24T00:00:00Z',worker_artifact_bytes=None)
    b=status.make_binding(value,'6'*64,None,'7'*64)
    plan=status.preflight(value,b,packed_store=True)
    publisher=status.Publisher(owner.root/'study/jobs/one/status63',b,LifecycleStreamPolicy(),
                               packed_store=True,writer_factory=Writer)
    try:
        assert publisher.publish(plan)==1
        assert status.hydrate(publisher.directory,plan.envelope,b)==dict(value,publication_sequence=1)
        assert owner.db.execute('SELECT phase FROM packed_namespace WHERE operation=?',(operation,)).fetchone()==('TERMINAL',)
        count=owner.db.execute("SELECT COUNT(*) FROM claims WHERE operation=? AND kind='FILE'",(operation,)).fetchone()[0]
        assert ordinary<count<=storage.PACKED_SEGMENT_FILES
    finally:publisher.close()
