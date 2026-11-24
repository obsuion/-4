"""New physical-owner failures and accounting on explicitly synthetic bytes.

No numerical model, worker, or scientific initialization is called here.
"""
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import os
import pytest

from ops_sim.v5 import lifetime_physical_storage as storage
from ops_sim.v5.lifetime_policy import (LifetimeCampaignPolicyV2, METHOD_NO_LAUNCH,
    METHOD_PHYSICAL, QUALIFICATION, STORE_PHYSICAL, STORE_V2)


def policy():
    return LifetimeCampaignPolicyV2(method=METHOD_PHYSICAL, mode=QUALIFICATION,
        maximum_primary_segments=2, reserved_diagnostic_slots=1,
        hard_seconds=60, soft_seconds=8, finalization_seconds=52)


def binding(p):
    return dict(root_identity='a'*64, source_identity='b'*64,
        input_sha256='c'*64, policy_identity=p.identity, store_name='study')


@pytest.fixture
def owner(tmp_path):
    with storage.PhysicalStorage(tmp_path, policy(), binding(policy()), create=True) as value:
        yield value


def reserve(owner, token='d', scope='study/jobs/one', maximum_files=8, producer=None):
    producer = dict(kind='SYNTHETIC_CORPUS') if producer is None else producer
    operation = token*64
    owner.reserve(operation, 'RETAINED', 2**20, producer,
        scope=scope, maximum_files=maximum_files)
    return operation, producer


def write(owner, name, data=b'canonical saved bytes'):
    owner.register_path(name)
    path = owner.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def seal(owner, operation, producer, tip=None):
    scope = owner.db.execute('SELECT scope FROM grants WHERE operation=?', (operation,)).fetchone()[0]
    proof = dict(format='YEAR_V4_OWNED_CLOSED_PRODUCER_V1', binding=owner.binding,
        producer=producer, scope=scope, closed=True, ownership_valid=True, uncertain_suffix=False)
    return owner.seal(operation, owner.producer_inventory(operation),
        producer=producer, settlement=proof, tip=tip)


class _AllocationCall:
    """Prototype-bearing fake DLL entry; never calls a native API."""
    def __init__(self, function):self.function=function
    def __call__(self,*args):return self.function(*args)


class _AllocationAPI:
    def __init__(self, *, allocation=4096, eof=17, links=1, directory=0,
                 delete=0, attributes=0, handle=101, query_failure=None,
                 query_result=1, close_result=1, query_exception=False):
        self.allocation=allocation;self.eof=eof;self.links=links
        self.directory=directory;self.delete=delete;self.attributes=attributes
        self.handle=handle;self.query_failure=query_failure
        self.query_result=query_result;self.close_result=close_result
        self.query_exception=query_exception;self.calls=[]
        self.CreateFileW=_AllocationCall(self.create)
        self.GetFileInformationByHandleEx=_AllocationCall(self.query)
        self.CloseHandle=_AllocationCall(self.close)
    def create(self,*args):
        self.calls.append(('open',args));return self.handle
    def query(self,handle,kind,data,size):
        self.calls.append(('query',handle,kind,size))
        if self.query_exception:
            if isinstance(self.query_exception,BaseException):raise self.query_exception
            raise RuntimeError('injected native query exception')
        if kind==self.query_failure:return 0
        value=data._obj
        if kind==1:
            assert size==24
            value.AllocationSize=self.allocation;value.EndOfFile=self.eof
            value.NumberOfLinks=self.links;value.Directory=self.directory
            value.DeletePending=self.delete
        else:
            assert kind==9 and size==8
            value.FileAttributes=self.attributes;value.ReparseTag=0
        return self.query_result
    def close(self,handle):
        self.calls.append(('close',handle));return self.close_result


@pytest.mark.parametrize('eof,allocated',((17,4096),(1,0),(0,0),(17,24)))
def test_windows_allocation_reads_native_size_and_closes_readonly_handle(eof,allocated):
    api=_AllocationAPI(allocation=allocated,eof=eof)
    assert storage._windows_allocation(Path('owned.bin'),SimpleNamespace(st_size=eof),4096,library=api)==allocated
    assert api.calls==[
        ('open',('owned.bin',0x80,7,None,3,0x00200000,None)),
        ('query',101,1,24),('query',101,9,8),('close',101)]
    # Resident/sparse/compressed allocations can be smaller than EOF. The
    # logical rounded charge remains conservative; no EOF<=allocation rule.


@pytest.mark.parametrize('values,match',(
    ({'allocation':8192},'foreign preallocation'),
    ({'allocation':-1},'native allocation'),
    ({'eof':-1},'native EOF'),
    ({'eof':18},'EOF drift'),
    ({'links':2},'single-link'),
    ({'links':0},'single-link'),
    ({'directory':1},'single-link'),
    ({'delete':1},'single-link'),
    ({'attributes':0x400},'nonreparse'),
    ({'attributes':0x10},'nonreparse'),
))
def test_windows_allocation_refuses_oversize_or_invalid_native_metadata_and_closes(values,match):
    api=_AllocationAPI(**values)
    with pytest.raises(ValueError,match=match):
        storage._windows_allocation(Path('owned.bin'),SimpleNamespace(st_size=17),4096,library=api)
    assert api.calls[-1]==('close',101)
    assert sum(row[0]=='close'for row in api.calls)==1


@pytest.mark.parametrize('expected,unit',((True,4096),(17.0,4096),(-1,4096),(17,True),(17,0),(17,3072)))
def test_windows_allocation_refuses_invalid_expected_types_before_open(expected,unit):
    api=_AllocationAPI()
    with pytest.raises(ValueError):
        storage._windows_allocation(Path('owned.bin'),SimpleNamespace(st_size=expected),unit,library=api)
    assert api.calls==[]


@pytest.mark.parametrize('stage',('open','standard','attributes','query_type','close','close_type','exception'))
def test_windows_allocation_api_failures_are_closed_and_never_admitted(monkeypatch,stage):
    import ctypes
    monkeypatch.setattr(ctypes,'get_last_error',lambda:5,raising=False)
    values={
        'open':dict(handle=ctypes.c_void_p(-1).value),
        'standard':dict(query_failure=1),'attributes':dict(query_failure=9),
        'query_type':dict(query_result=True),'close':dict(close_result=0),
        'close_type':dict(close_result=True),'exception':dict(query_exception=True)}
    api=_AllocationAPI(**values[stage])
    with pytest.raises(RuntimeError if stage=='exception'else OSError):
        storage._windows_allocation(Path('owned.bin'),SimpleNamespace(st_size=17),4096,library=api)
    closes=[row for row in api.calls if row[0]=='close']
    assert closes==([]if stage=='open'else[('close',101)])


def test_windows_allocation_close_failure_preserves_primary_query_failure(monkeypatch):
    import ctypes
    monkeypatch.setattr(ctypes,'get_last_error',lambda:5,raising=False)
    primary=RuntimeError('injected primary query exception')
    api=_AllocationAPI(query_exception=primary,close_result=0)
    with pytest.raises(RuntimeError,match='primary query exception')as failure:
        storage._windows_allocation(Path('owned.bin'),SimpleNamespace(st_size=17),4096,library=api)
    assert failure.value is primary
    assert any('handle close failure'in note for note in failure.value.__notes__)
    assert api.calls[-1]==('close',101)
    assert sum(row[0]=='close'for row in api.calls)==1


def test_windows_oversized_allocation_cannot_seal_or_advance_tip(owner,monkeypatch):
    operation,producer=reserve(owner)
    write(owner,'study/jobs/one/preallocated.bin',b'x'*17)
    before=owner.snapshot();api=_AllocationAPI(allocation=8192)
    def allocation(path,info,unit):
        return storage._windows_allocation(path,info,unit,library=api)
    monkeypatch.setattr(storage,'_allocation',allocation)
    with pytest.raises(ValueError,match='foreign preallocation'):
        seal(owner,operation,producer,tip={'clock':99})
    after=owner.snapshot()
    assert after['tip']==before['tip']
    assert after['still_reserved_active_writes']==before['still_reserved_active_writes']
    assert after['charged_by_role']==before['charged_by_role']
    assert owner.inventory()==[]
    assert api.calls[-1]==('close',101)


@pytest.mark.skipif(os.name!='nt',reason='actual Windows FileAllocationInfo own-temp case')
def test_actual_windows_own_temp_preallocation_is_refused_without_privilege_changes(owner):
    import ctypes
    operation,producer=reserve(owner)
    path=write(owner,'study/jobs/one/native-preallocation.bin',b'x')
    before=owner.snapshot();api=ctypes.WinDLL('kernel32',use_last_error=True)
    class Allocation(ctypes.Structure):
        _fields_=(('AllocationSize',ctypes.c_int64),)
    class Standard(ctypes.Structure):
        _fields_=(('AllocationSize',ctypes.c_int64),('EndOfFile',ctypes.c_int64),
            ('NumberOfLinks',ctypes.c_uint32),('DeletePending',ctypes.c_ubyte),('Directory',ctypes.c_ubyte))
    create=api.CreateFileW
    create.argtypes=(ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,
        ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p);create.restype=ctypes.c_void_p
    change=api.SetFileInformationByHandle
    change.argtypes=(ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32);change.restype=ctypes.c_int
    query=api.GetFileInformationByHandleEx
    query.argtypes=(ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32);query.restype=ctypes.c_int
    close=api.CloseHandle;close.argtypes=(ctypes.c_void_p,);close.restype=ctypes.c_int
    # Normal write permission on our own temporary file, not SetFileValidData,
    # token privileges, volume control, or a filesystem/global change.
    handle=create(str(path),0x40000000|0x80,7,None,3,0x00200000,None)
    if handle in(None,ctypes.c_void_p(-1).value):raise ctypes.WinError(ctypes.get_last_error())
    try:
        allocation=Allocation(65536)
        if not change(handle,5,ctypes.byref(allocation),ctypes.sizeof(allocation)):
            error=ctypes.get_last_error()
            if error in(1,50):pytest.skip('FileAllocationInfo unsupported by own-temp filesystem: '+str(error))
            raise ctypes.WinError(error)
        native=Standard()
        if not query(handle,1,ctypes.byref(native),ctypes.sizeof(native)):
            raise ctypes.WinError(ctypes.get_last_error())
        assert native.EndOfFile==1 and path.stat().st_size==1
        if native.AllocationSize<=owner.volume['allocation_unit_bytes']:
            pytest.skip('filesystem did not retain requested native preallocation')
        with pytest.raises(ValueError,match='foreign preallocation'):
            seal(owner,operation,producer,tip={'clock':99})
        after=owner.snapshot()
        assert after['tip']==before['tip']
        assert after['still_reserved_active_writes']==before['still_reserved_active_writes']
        assert after['charged_by_role']==before['charged_by_role']
        assert owner.inventory()==[]
    finally:
        if not close(handle):raise ctypes.WinError(ctypes.get_last_error())


def test_new_contract_preserves_old_reservation_and_identity_wire():
    p = policy(); legacy = replace(p, method=METHOD_NO_LAUNCH)
    expected = (legacy.maximum_jobs*legacy.maximum_output_bytes +
        legacy.maximum_metadata_bytes + legacy.initial_package_reserve_bytes)*(1+legacy.backup_copies)
    assert legacy.pool_commitment_bytes == expected
    assert set(asdict(p)) == set(asdict(legacy))
    assert p.maximum_reserved_job_output_bytes == legacy.maximum_reserved_job_output_bytes
    assert p.pool_commitment_bytes == sum(storage.contract(p)[key] for key in (
        'global_retained_cap_bytes', 'maximum_concurrent_write_reserve_bytes',
        'terminal_checkpoint_headroom_bytes', 'maximum_temporary_overlap_bytes',
        'export_allowance_bytes', 'full_defined_backup_cap_bytes', 'bounded_index_metadata_bytes'))
    assert p.pool_commitment_bytes == 8522825728 < 8*2**30
    limits=storage.contract(p)
    assert limits['maximum_concurrent_write_reserve_bytes']==512*2**20
    assert limits['bounded_index_metadata_bytes']==576*2**20
    assert limits['maximum_allocation_unit_bytes']==4096
    assert limits['maximum_rollback_journal_bytes']==553877504
    assert limits['maximum_rollback_journal_headers']==4098
    # At every admitted allocation unit, static+initial-package+one full
    # RAW-sized segment fits the independent active-grant ceiling.
    u=limits['maximum_allocation_unit_bytes'];f=limits['maximum_files_per_operation']
    static=128*2**20+(3*f+16)*u
    package=128*2**20+(3+16)*u
    segment=(128+16)*2**20+(3*f+16)*u
    assert static+package+segment<=limits['maximum_concurrent_write_reserve_bytes']
    assert p.identity != legacy.identity
    with pytest.raises(ValueError, match='backup'):
        replace(p, backup_copies=2)


def test_explicit_store_format_cannot_acquire_or_drop_physical_method():
    from ops_sim.v5.lifecycle_runner_policy import admit_runner_store_metadata, STORE_FIELDS
    p=policy()
    base={name:None for name in STORE_FIELDS}
    base.update(format=STORE_PHYSICAL,maximum_jobs=p.maximum_jobs,runner_policy=asdict(p),
        runner_policy_identity=p.identity,execution_authority_sha256='e'*64)
    assert admit_runner_store_metadata(base)[0] == p
    with pytest.raises(ValueError, match='no migration'):
        admit_runner_store_metadata(dict(base,format=STORE_V2))
    old=replace(p,method=METHOD_NO_LAUNCH)
    with pytest.raises(ValueError, match='no migration'):
        admit_runner_store_metadata(dict(base,runner_policy=asdict(old),runner_policy_identity=old.identity))


def test_reservation_is_durable_idempotent_and_unknown_never_refunded(owner):
    operation, producer = reserve(owner)
    before = owner.snapshot()
    again = owner.reserve(operation,'RETAINED',2**20,producer,
        scope='study/jobs/one',maximum_files=8)
    assert again['existing'] is True
    assert owner.snapshot()['charged_by_role'] == before['charged_by_role']
    owner.mark_unknown(operation)
    assert owner.snapshot()['unknown_reserved_bytes'] == again['reserved_bytes']
    with pytest.raises(ValueError, match='UNKNOWN'):
        owner.register_path('study/jobs/one/new.bin')
    assert owner.snapshot()['charged_by_role'] == before['charged_by_role']


def test_file_count_guard_refuses_before_second_creation(owner):
    operation, producer = reserve(owner, maximum_files=1)
    write(owner,'study/jobs/one/first.bin')
    with pytest.raises(ValueError, match='population'):
        owner.register_path('study/jobs/one/second.bin')
    assert not (owner.root/'study/jobs/one/second.bin').exists()
    assert owner.snapshot()['still_reserved_active_writes'] > 0


def test_seal_requires_positive_claims_and_charges_allocation_overhead(owner):
    operation, producer = reserve(owner)
    write(owner,'study/jobs/one/data.bin',b'x'*17)
    before=owner.snapshot()['charged_by_role']['RETAINED']
    result=seal(owner,operation,producer,tip={'clock':7})
    after=owner.snapshot()
    assert result['logical_bytes']==17
    assert result['charged_bytes'] >=17+owner.volume['allocation_unit_bytes']
    assert after['retained_owned_bytes']==result['charged_bytes']<before
    assert after['whole_study_commitment_bytes']==owner.contract['whole_study_commitment_bytes']
    assert after['tip']=={'clock':7}
    assert owner.inventory()[0]['sha256']==sha256(b'x'*17).hexdigest()


def test_orphan_failure_preserves_grant_and_prior_tip(owner):
    operation, producer = reserve(owner)
    write(owner,'study/jobs/one/data.bin')
    (owner.root/'study/jobs/one/foreign.bin').write_bytes(b'not a producer claim')
    before=owner.snapshot()
    with pytest.raises(ValueError,match='orphan'):
        seal(owner,operation,producer,tip={'clock':99})
    assert owner.snapshot()['still_reserved_active_writes']==before['still_reserved_active_writes']
    assert owner.snapshot()['tip']==before['tip']


def synthetic_status_job():
    """Status DATA only; no scientific initialization or execution."""
    return dict(format='B59_FINITE_OWNED_LIFECYCLE_JOB_V1', job_id='1'*32,
        intent=dict(root_identity='a'*64, idempotency_key='2'*32,
            parent_job_id=None, mode='NORMAL', maximum_output_bytes=128*2**20),
        root_identity='a'*64, source_identity='b'*64,
        runtime=dict(implementation='CPython', version=[3,14,7]),
        input_sha256='c'*64, resume=None, publication_sequence=0,
        status='QUEUED', reason=None, progress=dict(payload='saved DATA '*128),
        checkpoints=[], result=None, launch=None, ownership_valid=None,
        created_utc='2026-10-24T00:00:00Z', worker_artifact_bytes=None)


@pytest.mark.parametrize('object_store',(False,True))
def test_real_status_publisher_claims_details_objects_and_error_files_before_seal(owner,object_store):
    """Regression for SHORT4-NEW: status63 sidecars used a separate writer."""
    from ops_sim.v5 import lifetime_status as status
    from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
    operation,producer=reserve(owner,maximum_files=32)
    value=synthetic_status_job()
    bound=status.make_binding(value,'d'*64,None,policy().identity)
    directory=owner.root/'study/jobs/one/status63'
    publisher=status.Publisher(directory,bound,LifecycleStreamPolicy(),object_store=object_store)
    plan=status.preflight(value,bound,object_store=object_store)
    assert publisher.publish(plan)==1
    publisher.errors.record('SYNTHETIC_TEST',ValueError('saved DATA failure evidence'))
    publisher.close()
    inventory=owner.producer_inventory(operation)
    names={entry['path'] for entry in inventory}
    base='study/jobs/one/status63/'
    assert base+plan.envelope['details']['path'] in names
    assert base+'parent-errors/reservation.json' in names
    assert base+'parent-errors/error-01.json' in names
    assert {base+name for name,_ in plan.objects}<=names
    assert bool(plan.objects)==object_store
    for leaf in ('details','parent-errors',*(('objects',) if object_store else ())):
        assert owner.db.execute('SELECT kind,retired FROM claims WHERE path=?',
            (base+leaf,)).fetchone()==('DIRECTORY',0)
    result=seal(owner,operation,producer,tip={'clock':7})
    assert result['files']==len(inventory)
    assert owner.snapshot()['tip']=={'clock':7}


def test_status_unknown_owner_refuses_before_sidecar_directory_creation(owner):
    from ops_sim.v5 import lifetime_status as status
    from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
    operation,producer=reserve(owner,maximum_files=32)
    owner.mark_unknown(operation)
    value=synthetic_status_job()
    bound=status.make_binding(value,'d'*64,None,policy().identity)
    directory=owner.root/'study/jobs/one/status63'
    publisher=status.Publisher(directory,bound,LifecycleStreamPolicy(),object_store=True)
    before=owner.snapshot()
    with pytest.raises(ValueError,match='UNKNOWN'):
        publisher.publish(status.preflight(value,bound,object_store=True))
    assert publisher.failed and not directory.exists()
    assert owner.producer_inventory(operation)==[]
    assert owner.snapshot()['still_reserved_active_writes']==before['still_reserved_active_writes']
    assert owner.snapshot()['tip']==before['tip']


@pytest.mark.parametrize('stage',('directory_fsync','sqlite_commit'))
def test_commit_failure_preserves_previous_tip_and_charge(owner,monkeypatch,stage):
    operation, producer = reserve(owner)
    write(owner,'study/jobs/one/data.bin')
    before=owner.snapshot()
    calls=[]
    def refuse(*args):
        calls.append(stage)
        raise OSError('injected '+stage+' failure')
    monkeypatch.setattr(owner,'_sync_directories'if stage=='directory_fsync'else'_commit',refuse)
    with pytest.raises(OSError,match='injected'):
        seal(owner,operation,producer,tip={'clock':99})
    assert calls and owner.snapshot()['tip']==before['tip']
    assert owner.snapshot()['still_reserved_active_writes']==before['still_reserved_active_writes']
    assert owner.inventory()==[]


def test_static_control_slot_reuses_generations_but_scientific_name_does_not(owner):
    operation,producer=reserve(owner,scope='study',producer={'kind':'STATIC_AND_BOUNDED_ROOT_CONTROL'})
    path=write(owner,'study/dispatch-owner.json')
    path.unlink();owner.retire_path('study/dispatch-owner.json')
    write(owner,'study/dispatch-owner.json',b'new owned generation')
    assert owner.db.execute('SELECT generation FROM claims WHERE path=?',('study/dispatch-owner.json',)).fetchone()[0]==2
    assert owner.db.execute('SELECT COUNT(*) FROM claim_retirements').fetchone()[0]==1
    op2,p2=reserve(owner,token='e',scope='study/jobs/two')
    cp=write(owner,'study/jobs/two/checkpoint.json')
    cp.unlink();owner.retire_path('study/jobs/two/checkpoint.json')
    with pytest.raises(ValueError,match='scientific'):
        owner.register_path('study/jobs/two/checkpoint.json')


def test_mutable_parent_bytes_stay_charged_after_seal_and_future_append(owner):
    operation,producer=reserve(owner)
    write(owner,'study/jobs/one/data.bin')
    leaf='study/jobs/one/parent-validation-work.bin';data=b'0'*16
    owner.reserve_mutable(leaf,len(data),{'kind':'APPEND'})
    with (owner.root/leaf).open('wb') as stream:stream.write(data)
    seal(owner,operation,producer)
    before=owner.snapshot()['mutable_reserved_bytes']
    owner.reserve_mutable(leaf,len(data),{'kind':'APPEND'})
    with (owner.root/leaf).open('ab') as stream:stream.write(data)
    assert owner.snapshot()['mutable_reserved_bytes']>=before
    assert all(entry['path']!=leaf for entry in owner.inventory())


def test_closed_synthetic_second_export_does_not_reclaim_first(owner):
    scope='study.exports'
    for token,name in (('a','one.zip'),('b','two.zip'),('c','three.zip')):
        producer={'kind':'SYNTHETIC_EXPORT','name':name};operation=token*64
        owner.reserve(operation,'EXPORT',2**20,producer,scope=scope,maximum_files=2)
        write(owner,scope+'/'+name,b'opaque saved synthetic export bytes')
        seal(owner,operation,producer)
    assert len(owner.inventory())==3
    assert owner.snapshot()['charged_by_role']['EXPORT']>0


def test_volume_change_refuses_before_write(owner,monkeypatch):
    changed=dict(owner.volume,device=owner.volume['device']+1)
    monkeypatch.setattr(storage,'_volume',lambda root:changed)
    with pytest.raises(ValueError,match='volume'):
        reserve(owner)
    assert not (owner.root/'study').exists()


def test_unsupported_sqlite_version_refuses_before_disk_owner(tmp_path,monkeypatch):
    p=policy()
    monkeypatch.setattr(storage.sqlite3,'sqlite_version','0.0.unsupported')
    with pytest.raises(ValueError,match='unsupported SQLite runtime'):
        storage.PhysicalStorage(tmp_path,p,binding(p),create=True)
    assert list(tmp_path.iterdir())==[]


def test_unsupported_sqlite_source_refuses_before_disk_owner(tmp_path,monkeypatch):
    p=policy()
    monkeypatch.setattr(storage.sqlite3,'sqlite_version',storage.SQLITE_VERSION)
    monkeypatch.setattr(storage,'SQLITE_SOURCE_ID','not the admitted pager source')
    monkeypatch.setattr(storage,'_SQLITE_RUNTIME',None)
    with pytest.raises(ValueError,match='unsupported SQLite source identity'):
        storage.PhysicalStorage(tmp_path,p,binding(p),create=True)
    assert list(tmp_path.iterdir())==[]


def test_static_bytes_precharged_before_io_and_never_refunded_on_retirement(owner):
    operation,producer=reserve(owner,scope='study',producer={'kind':'STATIC_AND_BOUNDED_ROOT_CONTROL'})
    name='study/control.json'
    owner.precharge_static_bytes(name,4)
    path=write(owner,name,b'data')
    path.unlink();owner.retire_path(name)
    owner.precharge_static_bytes(name,4)
    write(owner,name,b'next')
    assert owner.snapshot()['static_bytes_precharged']==8
    with pytest.raises(ValueError,match='STATIC'):
        owner.precharge_static_bytes('study/oversized.json',2**20)
    assert not (owner.root/'study/oversized.json').exists()


def test_pool_reserves_future_cap_and_foreign_bytes_never_earn_credit(tmp_path,monkeypatch):
    p=policy();cap=p.pool_commitment_bytes
    free=[cap+2**20]
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda path:SimpleNamespace(free=free[0]))
    owners=storage.pool_owners(tmp_path/'study','a'*64)
    result=storage.reserve_pool(tmp_path,'a'*64,p,owners=owners,pool_bytes=cap,windows=True)
    assert result['total_reserved_bytes']==cap
    assert result['outstanding_reserved_bytes']==cap
    assert result['credited_physical_bytes']==0
    before=(tmp_path/storage.POOL_FILE).read_bytes()
    (tmp_path/'foreign.bin').write_bytes(b'unattributed')
    free[0]-=1
    with pytest.raises(ValueError,match='unattributed'):
        storage.reserve_pool(tmp_path,'a'*64,p,owners=owners,windows=True)
    assert (tmp_path/storage.POOL_FILE).read_bytes()==before


def test_bounded_zip_sink_refuses_before_growth(tmp_path):
    target=tmp_path/'bounded.zip'
    with storage.BoundedExportFile(target,64) as sink:
        sink.write(b'x'*63)
        with pytest.raises(ValueError,match='prospective'):
            sink.write(b'zz')
    assert target.stat().st_size==63


def test_export_write_failure_keeps_full_export_reservation_and_no_final(owner):
    study=owner.root/'study';study.mkdir()
    fake=SimpleNamespace(directory=study,runner_policy=owner.policy,
        meta={key:value for key,value in owner.binding.items()if key!='store_name'})
    target=owner.root/'study.exports'/'result.zip'
    def fail_export(store,plan,path,*,sink_factory,maximum_bytes):
        with sink_factory(path) as sink:sink.write(b'paid incomplete ZIP')
        raise OSError('injected export staging failure')
    with pytest.raises(OSError,match='injected'):
        storage.publish_data_export(fake,{'plan_identity':'a'*64},target,fail_export)
    assert not target.exists()
    state=owner.snapshot()
    assert state['charged_by_role']['EXPORT']>=128*2**20
    assert state['tip'] is None
    assert list((owner.root/'study.exports').glob('*.pending.zip'))


def test_public_export_commit_failure_preserves_valid_final_as_charged_orphan(owner,monkeypatch):
    """Real supervisor/physical publication, with only saved synthetic DATA.

    A final ZIP can exist before the ownership COMMIT. That failure must not
    return a receipt, credit the ZIP, change the prior tip or permit a retry.
    """
    import json,zipfile
    from ops_sim.v5 import lifetime_result as result
    from ops_sim.v5 import lifetime_supervisor as supervisor
    operation,producer=reserve(owner)
    write(owner,'study/jobs/one/data.bin',b'synthetic prior sealed prefix')
    seal(owner,operation,producer,tip={'clock':7})
    fake=SimpleNamespace(directory=owner.root/'study',runner_policy=owner.policy,
        meta={key:value for key,value in owner.binding.items()if key!='store_name'},
        close_publications=lambda:None)
    plan={'plan_identity':'a'*64}
    monkeypatch.setattr(supervisor,'_store',lambda directory:(fake,plan))
    # This fixture already owns its explicitly reserved local namespace; the
    # public entry still selects the production physical export branch.
    monkeypatch.setattr(supervisor,'_reserve_pool',lambda store,plan:None)
    fixture=json.loads((Path(__file__).parent/'fixtures/lifetime_readonly_actual.json').read_bytes())
    payload={name:data.encode('utf8')for name,data in fixture['payload'].items()}
    view=json.loads(payload['view.json'])
    manifest={name:dict(bytes=len(data),sha256=sha256(data).hexdigest())for name,data in payload.items()}
    def saved_data_export(store,plan,path,*,sink_factory,maximum_bytes):
        with sink_factory(path) as stream:
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('MANIFEST.json',storage.encoded(dict(format=view['format'],files=manifest)))
                for name,data in sorted(payload.items()):archive.writestr(name,data)
    monkeypatch.setattr(result,'export_result',saved_data_export)
    target=owner.root/'study.exports'/'result.zip'
    original_commit=storage.PhysicalStorage._commit
    failed_commits=[]
    def fail_only_export_seal(value):
        row=value.db.execute('SELECT operation FROM grants WHERE role=? AND state=?',('EXPORT','SEALED')).fetchone()
        if row is not None and target.exists():
            # This runs after exclusive final publication and all checks,
            # before the authoritative SQLite transaction can commit.
            assert result.inspect_result(target)==view
            failed_commits.append(row[0])
            raise OSError('injected EXPORT ownership COMMIT failure')
        return original_commit(value)
    monkeypatch.setattr(storage.PhysicalStorage,'_commit',fail_only_export_seal)
    before=owner.snapshot();receipts=[]
    with pytest.raises(OSError,match='EXPORT ownership COMMIT failure'):
        receipts.append(supervisor.export_result(fake.directory,target))
    assert receipts==[] and len(failed_commits)==1
    assert target.is_file() and result.inspect_result(target)==view
    assert not list(target.parent.glob('*.pending.zip'))
    after=owner.snapshot()
    assert after['tip']==before['tip']=={'clock':7}
    assert after['retained_owned_bytes']==before['retained_owned_bytes']
    assert owner.db.execute('SELECT state,reserved_bytes,charged_bytes FROM grants WHERE operation=?',
        (failed_commits[0],)).fetchone()==('RESERVED',owner.reservation_bytes(128*2**20,2),0)
    assert after['charged_by_role']['EXPORT']==owner.reservation_bytes(128*2**20,2)
    relative=target.relative_to(owner.root).as_posix()
    assert owner.db.execute('SELECT 1 FROM files WHERE path=?',(relative,)).fetchone() is None
    assert all(entry['path']!=relative for entry in owner.inventory())
    with pytest.raises(ValueError,match='only one active external-role'):
        supervisor.export_result(fake.directory,target.with_name('retry.zip'))
    assert not target.with_name('retry.zip').exists()
    assert owner.snapshot()['charged_by_role']==after['charged_by_role']
    assert owner.snapshot()['tip']==before['tip']


def test_workspace_reopen_allows_only_bound_physical_namespace(tmp_path,monkeypatch):
    from ops_sim.v5 import lifecycle_application as app
    p=policy();name='a'*64;b=dict(binding(p),store_name=name)
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda path:SimpleNamespace(free=20*2**30))
    storage.prepare_owner(tmp_path/name,p,b)
    (tmp_path/name).mkdir()
    fake=SimpleNamespace(directory=tmp_path/name,runner_policy=p,
        meta={key:value for key,value in b.items()if key!='store_name'},jobs=lambda:[])
    monkeypatch.setattr(app,'LifecycleStore',lambda path:fake)
    workspace=app.LifecycleWorkspace(tmp_path)
    assert list(workspace.stores)==[name]
    (tmp_path/'foreign.physical.sqlite3').write_bytes(b'foreign')
    with pytest.raises(ValueError,match='unknown lifecycle workspace artifact'):
        app.LifecycleWorkspace(tmp_path)


def test_workspace_refuses_unfinished_external_publication(tmp_path,monkeypatch):
    p=policy();name='a'*64;b=dict(binding(p),store_name=name)
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda path:SimpleNamespace(free=20*2**30))
    storage.prepare_owner(tmp_path/name,p,b)
    (tmp_path/name).mkdir()
    with storage.PhysicalStorage(tmp_path,p,b) as own:
        own.reserve('f'*64,'EXPORT',128*2**20,{'kind':'FAILED_EXPORT'},
            scope=name+'.exports',maximum_files=2)
        write(own,name+'.exports/incomplete.pending.zip',b'not a complete archive')
        charged=own.snapshot()['charged_by_role']['EXPORT']
    with pytest.raises(ValueError,match='unfinished external producer'):
        storage.workspace_physical_entries(tmp_path)
    with storage.PhysicalStorage(tmp_path,p,b) as own:
        assert own.snapshot()['charged_by_role']['EXPORT']==charged


@pytest.mark.parametrize('compact',(False,True))
def test_missing_declared_physical_owner_refuses_before_file_creation(tmp_path,compact):
    from ops_sim.v5.lifecycle_runner_policy import STORE_FIELDS
    p=policy();study=tmp_path/'study';study.mkdir()
    meta={name:None for name in STORE_FIELDS}
    meta.update(format=STORE_PHYSICAL,maximum_jobs=p.maximum_jobs,runner_policy=asdict(p),
        runner_policy_identity=p.identity,execution_authority_sha256='e'*64)
    if compact:
        from ops_sim.v5.lifecycle_compact import PublicationProfile,STORE
        profile=PublicationProfile()
        meta.update(format=STORE,base_store_format=STORE_PHYSICAL,
            publication_profile=asdict(profile),publication_profile_identity=profile.identity)
    (study/'store.json').write_bytes(storage.encoded(meta))
    target=study/'jobs'/'one'/'unpaid.bin'
    with pytest.raises(ValueError,match='physical SQLite owner missing'):
        storage.register_producer_path(target)
    assert not target.exists() and not (tmp_path/'study.physical.sqlite3').exists()


def test_missing_new_owner_with_pool_marker_cannot_fall_back_to_legacy(tmp_path,monkeypatch):
    p=policy();study=tmp_path/'study'
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda path:SimpleNamespace(free=20*2**30))
    storage.prepare_owner(study,p,binding(p))
    (tmp_path/'study.physical.sqlite3').unlink()
    with pytest.raises(ValueError,match='physical SQLite owner missing'):
        storage.register_producer_path(study/'input.json')
    assert not study.exists() and not (tmp_path/'study.physical.sqlite3').exists()


def test_legacy_store_marker_keeps_no_owner_noop(tmp_path):
    from ops_sim.v5.lifecycle_runner_policy import STORE_FIELDS
    p=replace(policy(),method=METHOD_NO_LAUNCH);study=tmp_path/'legacy';study.mkdir()
    meta={name:None for name in STORE_FIELDS}
    meta.update(format=STORE_V2,maximum_jobs=p.maximum_jobs,runner_policy=asdict(p),
        runner_policy_identity=p.identity,execution_authority_sha256='e'*64)
    (study/'store.json').write_bytes(storage.encoded(meta))
    assert storage.register_producer_path(study/'jobs'/'one'/'legacy.bin') is False


def test_optional_posix_declaration_claim_retires_only_after_closed_scope(owner):
    from ops_sim.v5.lifecycle_process import OwnedPosixGroup
    operation,producer=reserve(owner)
    write(owner,'study/jobs/one/tmp/linux-owned-token.json',b'synthetic closed handshake')
    leaf='study/jobs/one/tmp/linux-descendants-token.json'
    owner.register_path(leaf)
    adapter=OwnedPosixGroup.__new__(OwnedPosixGroup)
    adapter.token='a'*32;adapter.declarations=owner.root/leaf
    adapter.process=SimpleNamespace(poll=lambda:0,wait=lambda **kwargs:0,
        stdin=None,stdout=None,stderr=None)
    adapter.state=lambda:{'job_active_PIDs':[],'job_active_count':0}
    receipt=adapter.reap(max_seconds=2,cleanup_deadline=__import__('time').perf_counter()+2)
    assert receipt['owned_job_empty'] and receipt['root_reaped'] and not receipt['errors']
    assert owner.db.execute('SELECT retired FROM claims WHERE path=?',(leaf,)).fetchone()==(1,)
    assert seal(owner,operation,producer)['files']==1


def test_actual_supervisor_global_refusal_never_dispatches_empty_continuations(tmp_path,monkeypatch):
    """A synthetic small owner exercises the real serial supervisor seam."""
    from ops_sim.v5 import lifecycle_application as app
    from ops_sim.v5 import lifetime_supervisor as supervisor
    from ops_sim.v5 import lifetime_execution_authority as authority
    from ops_sim.v5 import lifetime_no_launch as no_launch
    from ops_sim.v5.lifetime_journal import Journal
    original=storage.contract
    def small(p):
        value=original(p)
        value['global_retained_cap_bytes']=8*2**20
        value['whole_study_commitment_bytes']=sum(value[name] for name in (
            'global_retained_cap_bytes','maximum_concurrent_write_reserve_bytes',
            'terminal_checkpoint_headroom_bytes','maximum_temporary_overlap_bytes',
            'export_allowance_bytes','full_defined_backup_cap_bytes','bounded_index_metadata_bytes'))
        value['identity']=storage.digest({key:item for key,item in value.items() if key!='identity'})
        return value
    monkeypatch.setattr(storage,'contract',small)
    p=policy();study=tmp_path/'study'
    with storage.PhysicalStorage(tmp_path,p,binding(p),create=True) as own:
        own.reserve('f'*64,'RETAINED',128*1024,
            {'kind':'STATIC_AND_BOUNDED_ROOT_CONTROL'},scope='study',maximum_files=8)
        operation='d'*64;producer={'kind':'SYNTHETIC_PREFIX'}
        own.reserve(operation,'RETAINED',32,producer,
            scope='study/jobs/prefix',maximum_files=1)
        prefix=write(own,'study/jobs/prefix/prefix.bin',b'saved-prefix')
        seal(own,operation,producer,tip={'clock':17})
    launched=[]
    class Runner:
        active=None
        thread=None
        def __init__(self,*args,**kwargs):pass
        def submit(self,intent):
            launched.append(intent)
            raise AssertionError('full global quota must refuse before dispatch')
    fake=SimpleNamespace(directory=study,runner_policy=p,
        meta={key:value for key,value in binding(p).items() if key!='store_name'},
        root_input=SimpleNamespace(start_seconds=0,end_seconds=86400,identity='a'*64),
        jobs=lambda:[],path=lambda *parts:study.joinpath(*parts))
    summary=dict(parent_job_id=None,primary_jobs=0,observed_seconds=0,
        reserved_unknown_seconds=0,clock=17)
    monkeypatch.setattr(app,'LifecycleRunner',Runner)
    monkeypatch.setattr(authority,'admit_store_execution',lambda store:None)
    monkeypatch.setattr(no_launch,'enabled',lambda policy:False)
    monkeypatch.setattr(supervisor,'_reserve_pool',lambda store,plan:None)
    monkeypatch.setattr(supervisor,'_summary',lambda store,plan:dict(summary))
    monkeypatch.setattr(supervisor,'_close_session',lambda store,runner=None:None)
    plan={'plan_identity':'e'*64}
    for _ in range(2):
        assert supervisor._run_locked(fake,plan,explicit_continue=True,
            on_launch=None,on_finish=None,stop_when=None,job_factory=None)['clock']==17
    records=list(Journal(fake,plan).records())
    halts=[record for record in records if record['action']=='HALT']
    assert len(halts)==2 and all(record['data']['reason']==storage.GLOBAL_EXHAUSTED for record in halts)
    assert not any(record['action']=='DISPATCH' for record in records)
    assert launched==[] and prefix.read_bytes()==b'saved-prefix'
    with storage.open_for_store(fake) as own:
        assert own.snapshot()['tip']=={'clock':17}
