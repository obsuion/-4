"""Exact scalar/grouped accounting on real, owned temporary SQLite stores.

No numerical model is called. The 192-operation corpus is storage metadata
qualification, not 192 scientific segments or a mission-capacity proof.
"""
from hashlib import sha256
import json
import sqlite3
from time import perf_counter_ns

import pytest

from ops_sim.v5 import lifetime_physical_storage as s
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,METHOD_PACKED,METHOD_PHYSICAL,QUALIFICATION


def policy(packed=True):
    return LifetimeCampaignPolicyV2(method=METHOD_PACKED if packed else METHOD_PHYSICAL,
        mode=QUALIFICATION,maximum_primary_segments=2,reserved_diagnostic_slots=1,
        hard_seconds=60,soft_seconds=8,finalization_seconds=52)


def binding(p):
    return dict(root_identity='a'*64,source_identity='b'*64,input_sha256='c'*64,
                policy_identity=p.identity,store_name='study')


def old_namespace(owner):
    """Independent direct transcription of SOURCE08's per-grant equations."""
    db=owner.db
    files=db.execute("SELECT COUNT(*) FROM claims WHERE kind='FILE'").fetchone()[0]
    dirs=db.execute("SELECT COUNT(*) FROM claims WHERE kind='DIRECTORY'").fetchone()[0]
    mutable=db.execute('SELECT COUNT(*) FROM mutable').fetchone()[0]
    rf=rd=pages=rows=unknown=mf=protected=0
    for op,maximum,dirmax,ir,meta,slots,state,phase,scope in db.execute(
            'SELECT n.operation,n.file_slots,n.directory_slots,n.index_rows,n.metadata_pages,n.mutable_slots,n.state,n.phase,g.scope FROM packed_namespace n JOIN grants g ON n.operation=g.operation'):
        uf=db.execute("SELECT COUNT(*) FROM claims WHERE operation=? AND kind='FILE'",(op,)).fetchone()[0]
        ud=db.execute("SELECT COUNT(*) FROM claims WHERE operation=? AND kind='DIRECTORY'",(op,)).fetchone()[0]
        names=tuple(scope+'/'+leaf for leaf in s.PACKED_MUTABLE_LEAVES)if scope is not None else ('','','')
        um=db.execute('SELECT COUNT(*) FROM mutable WHERE path IN (?,?,?)',names).fetchone()[0]
        future=max(0,slots-um);mf+=future;rf+=future
        if state!='SEALED':rf+=max(0,maximum-uf);rd+=max(0,dirmax-ud);pages+=meta;rows+=ir;unknown+=state=='UNKNOWN'
        elif future:pages+=meta;rows+=min(ir,future)
        if state=='UNKNOWN'or state!='SEALED'and phase!='TERMINAL'or state=='SEALED'and future:protected+=meta
    return dict(format='YEAR_V5_PROSPECTIVE_TERMINAL_NAMESPACE_V2',cumulative_file_names=files,
        cumulative_directory_names=dirs,mutable_names=mutable,unused_unsettled_file_slots=rf,
        unused_unsettled_directory_slots=rd,unsettled_metadata_pages=pages,unsettled_terminal_index_rows=rows,
        unknown_escrows=unknown,unused_persistent_mutable_file_slots=mf,protected_metadata_pages_for_mutations=protected,
        file_slot_scope='UNSETTLED_SCIENTIFIC_NAMES_PLUS_PERSISTENT_UNUSED_MUTABLE_NAMES_INCLUDING_SEALED_JOBS',
        current_database_pages=db.execute('PRAGMA page_count').fetchone()[0],maximum_database_pages=s.MAX_DATABASE_PAGES,
        maximum_file_names=s.MAX_FILES,terminal_file_slots_per_segment=s.PACKED_TERMINAL_FILES,
        terminal_directory_slots_per_segment=s.PACKED_TERMINAL_DIRECTORIES,
        retired_names='CUMULATIVE_NEVER_REUSED_SCIENTIFIC_NAMES')


def old_snapshot(owner):
    """Old scalar accounting, deliberately reading its old unused BLOBs."""
    db=owner.db
    rows=db.execute('SELECT operation,role,maximum_bytes,maximum_files,reserved_bytes,producer,scope,state,manifest,charged_bytes,logical_bytes,allocated_bytes FROM grants ORDER BY operation').fetchall()
    if len(rows)>s.MAX_OPERATIONS:raise ValueError('old operation population')
    used={r:0 for r in s.ROLES};active=unknown=logical=allocated=sealed=0
    for row in rows:
        if row[1]not in s.ROLES or row[7]not in('RESERVED','UNKNOWN','SEALED'):raise ValueError('old role/state')
        amount=row[9]if row[7]=='SEALED'else row[4]
        if type(amount)is not int or not 0<=amount<=2**40:raise ValueError('old amount')
        used[row[1]]+=amount
        if row[7]!='SEALED':
            active+=row[4]if row[1]=='RETAINED'else 0
            if row[7]=='UNKNOWN':unknown+=row[4]
        else:
            sealed+=row[9]if row[1]=='RETAINED'else 0;logical+=row[10];allocated+=row[11]
    mutable,count=db.execute('SELECT COALESCE(SUM(charged_bytes),0),COUNT(*) FROM mutable').fetchone()
    if type(mutable)is not int or not 0<=mutable<=2**40 or count>s.MAX_FILES:raise ValueError('old mutable')
    used['RETAINED']+=mutable
    if any(used[r]>owner.contract[s.CAP_KEYS[r]]for r in s.ROLES):raise ValueError('old role cap')
    if active>owner.contract['maximum_concurrent_write_reserve_bytes']:raise ValueError('old active cap')
    files=db.execute('SELECT COUNT(*) FROM files').fetchone()[0]
    if files>s.MAX_FILES:raise ValueError('old files cap')
    head=db.execute('SELECT value FROM metadata WHERE key=?',('tip',)).fetchone()
    c=owner.contract
    result=dict(format=owner.owner_format,binding=dict(owner.binding),contract=dict(c),
        retained_owned_bytes=sealed,still_reserved_active_writes=active,mutable_reserved_bytes=mutable,
        static_bytes_precharged=db.execute('SELECT COALESCE(SUM(write_reserved_bytes),0) FROM grants').fetchone()[0],
        charged_by_role=used,unknown_reserved_bytes=unknown,logical_sealed_bytes=logical,
        allocated_sealed_file_data_bytes=allocated,owned_files=files,operations=len(rows),
        global_retained_headroom_bytes=c['global_retained_cap_bytes']-used['RETAINED'],
        current_peak_bound_bytes=sealed+active+mutable+sum(c[k]for k in('terminal_checkpoint_headroom_bytes',
            'maximum_temporary_overlap_bytes','export_allowance_bytes','full_defined_backup_cap_bytes','bounded_index_metadata_bytes')),
        whole_study_commitment_bytes=c['whole_study_commitment_bytes'],
        tip=None if head is None else json.loads(head[0]),capacity_status='NOT_ESTABLISHED_BY_RESOURCE_CAP')
    if owner.packed:result['namespace']=old_namespace(owner)
    return result


def reserve(owner,index,*,kind='SEGMENT',role='RETAINED'):
    jid=f'{index:032x}';op=sha256(('owned-accounting-'+str(index)).encode()).hexdigest()
    producer=dict(kind=kind,job_id=jid,intent_sha256='2'*64,request_sha256='3'*64)
    scope='study/jobs/'+jid if role=='RETAINED'else 'study.'+role.lower()+'/'+jid
    owner.reserve(op,role,2**20,producer,scope=scope,
                  maximum_files=s.PACKED_SEGMENT_FILES if kind=='SEGMENT'else 8)
    return op,producer,scope


def write(owner,path,data=b'owned metadata-only payload'):
    owner.register_path(path);target=owner.root/path;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(data);return target


def append(owner,scope,producer,leaf):
    path=scope+'/'+leaf;data=b'paid'
    owner.reserve_mutable(path,len(data),dict(kind='PARENT_APPEND_LEDGER',job_id=producer['job_id'],leaf=leaf))
    with(owner.root/path).open('ab')as stream:stream.write(data);stream.flush()


def seal(owner,op,producer,scope,tip=None):
    proof=dict(format=s.SETTLEMENT_PACKED if owner.packed else 'YEAR_V4_OWNED_CLOSED_PRODUCER_V1',
        binding=owner.binding,producer=producer,scope=scope,closed=True,ownership_valid=True,uncertain_suffix=False)
    return owner.seal(op,owner.producer_inventory(op),producer=producer,settlement=proof,tip=tip)


def completed(owner,index,*,mutable=3):
    op,p,scope=reserve(owner,index);write(owner,scope+'/payload.bin',b'owned '+str(index).encode())
    for leaf in s.PACKED_MUTABLE_LEAVES[:mutable]:append(owner,scope,p,leaf)
    seal(owner,op,p,scope,tip=dict(clock=index+1))
    return op,p,scope


@pytest.mark.parametrize('count',(0,1,7))
def test_exact_snapshot_and_namespace_match_old_equations_on_real_owned_rows(tmp_path,count):
    p=policy()
    with s.PhysicalStorage(tmp_path,p,binding(p),create=True)as owner:
        for index in range(count):completed(owner,index)
        assert owner.snapshot()==old_snapshot(owner)
        assert owner.namespace_snapshot()==old_namespace(owner)


def test_mixed_roles_reserved_unknown_sealed_and_legacy_values_remain_exact(tmp_path):
    for packed in(False,True):
        root=tmp_path/str(packed);root.mkdir();p=policy(packed)
        with s.PhysicalStorage(root,p,binding(p),create=True)as owner:
            if packed:completed(owner,0)
            else:
                op,pr,scope=reserve(owner,0,kind='SYNTHETIC');write(owner,scope+'/data.bin');seal(owner,op,pr,scope)
            op,pr,scope=reserve(owner,1,kind='SYNTHETIC',role='EXPORT')
            write(owner,scope+'/data.zip');seal(owner,op,pr,scope)
            reserve(owner,2,kind='SYNTHETIC',role='BACKUP')
            op,_,_=reserve(owner,3,kind='SYNTHETIC');owner.mark_unknown(op)
            assert owner.snapshot()==old_snapshot(owner)
            assert owner.snapshot()['unknown_reserved_bytes']>0


def test_late_closed_mutable_slot_and_charge_conservation_match_old_snapshot(tmp_path):
    p=policy()
    with s.PhysicalStorage(tmp_path,p,binding(p),create=True)as owner:
        op,pr,scope=completed(owner,0,mutable=2)
        before=owner.namespace_snapshot();assert before['unused_persistent_mutable_file_slots']==1
        append(owner,scope,pr,s.PACKED_MUTABLE_LEAVES[0]);append(owner,scope,pr,s.PACKED_MUTABLE_LEAVES[2])
        after=owner.namespace_snapshot()
        assert before['cumulative_file_names']+before['mutable_names']+before['unused_unsettled_file_slots']==after['cumulative_file_names']+after['mutable_names']+after['unused_unsettled_file_slots']
        assert owner.snapshot()==old_snapshot(owner)and after==old_namespace(owner)
        assert after['protected_metadata_pages_for_mutations']==0


def test_near_active_reservation_cap_and_next_refusal_are_exact(tmp_path):
    p=policy()
    with s.PhysicalStorage(tmp_path,p,binding(p),create=True)as owner:
        overhead=owner.reservation_bytes(1,8)-1
        amount=owner.contract['maximum_concurrent_write_reserve_bytes']-overhead
        owner.reserve('d'*64,'RETAINED',amount,dict(kind='SYNTHETIC_NEAR_CAP'),scope='study/near',maximum_files=8)
        assert owner.snapshot()==old_snapshot(owner)
        assert owner.snapshot()['still_reserved_active_writes']==owner.contract['maximum_concurrent_write_reserve_bytes']
        before=owner.snapshot()
        with pytest.raises(ValueError,match='active write'):owner.reserve('e'*64,'RETAINED',1,dict(kind='SYNTHETIC'),scope='study/refused',maximum_files=1)
        assert owner.snapshot()==before


@pytest.mark.parametrize('column,value',(
    ('role','BAD'),('state','BAD'),('reserved_bytes',-1),('charged_bytes',-1),
    ('logical_bytes',-1),('allocated_bytes',-1),('write_reserved_bytes',-1),
    ('reserved_bytes',1.5),('write_reserved_bytes',1.5),('write_reserved_bytes',2**62),
    ('logical_bytes',1),('allocated_bytes',1),('charged_bytes',1)))
def test_corrupt_scalar_rows_never_skip_unused_values_or_use_float_sum(tmp_path,column,value):
    p=policy()
    with s.PhysicalStorage(tmp_path,p,binding(p),create=True)as owner:
        op,_,_=reserve(owner,0)
        owner.db.execute('UPDATE grants SET '+column+'=? WHERE operation=?',(value,op))
        statements=[];owner.db.set_trace_callback(statements.append)
        try:
            with pytest.raises(ValueError):owner.snapshot()
        finally:owner.db.set_trace_callback(None)
        assert not owner.db.in_transaction
        assert not any('SUM('in q.upper()for q in statements)


@pytest.mark.parametrize('damage',('kind','negative_slots','real_pages','state_mismatch','missing_namespace','mutable_real'))
def test_corrupt_grouped_namespace_is_not_silently_omitted(tmp_path,damage):
    p=policy()
    with s.PhysicalStorage(tmp_path,p,binding(p),create=True)as owner:
        op,pr,scope=reserve(owner,0);write(owner,scope+'/data.bin')
        if damage=='kind':owner.db.execute("UPDATE claims SET kind='BOGUS' WHERE kind='FILE'")
        elif damage=='negative_slots':owner.db.execute('UPDATE packed_namespace SET file_slots=-1')
        elif damage=='real_pages':owner.db.execute('UPDATE packed_namespace SET metadata_pages=1.5')
        elif damage=='state_mismatch':owner.db.execute("UPDATE packed_namespace SET state='SEALED'")
        elif damage=='missing_namespace':owner.db.execute('DELETE FROM packed_namespace')
        else:
            append(owner,scope,pr,s.PACKED_MUTABLE_LEAVES[0]);owner.db.execute('UPDATE mutable SET charged_bytes=1.5')
        with pytest.raises(ValueError):owner.snapshot()
        with pytest.raises(ValueError):owner.namespace_snapshot()


def test_accounting_projection_does_not_remove_full_seal_manifest_guard(tmp_path):
    p=policy()
    with s.PhysicalStorage(tmp_path,p,binding(p),create=True)as owner:
        op,pr,scope=completed(owner,0);before=owner.snapshot()
        owner.db.execute('UPDATE grants SET manifest=? WHERE operation=?',(b'corrupt saved manifest',op))
        assert owner.snapshot()==before
        with pytest.raises(ValueError,match='sealed ownership drift'):seal(owner,op,pr,scope,tip=dict(clock=1))


def test_read_view_is_consistent_and_existing_mutation_transaction_is_reused(tmp_path):
    p=policy()
    with s.PhysicalStorage(tmp_path,p,binding(p),create=True)as owner:
        completed(owner,0);other=sqlite3.connect(owner.path,isolation_level=None,timeout=0)
        try:
            with owner._accounting_read():
                before=owner.snapshot()
                other.execute('BEGIN IMMEDIATE');other.execute('UPDATE grants SET write_reserved_bytes=1')
                with pytest.raises(sqlite3.OperationalError,match='locked'):other.execute('COMMIT')
                other.execute('ROLLBACK')
                assert owner.snapshot()==before
            statements=[];owner.db.set_trace_callback(statements.append)
            try:
                with pytest.raises(RuntimeError,match='rollback test'):
                    with owner._transaction():
                        owner.db.execute('UPDATE grants SET write_reserved_bytes=7')
                        assert owner.snapshot()['static_bytes_precharged']==7
                        raise RuntimeError('rollback test')
            finally:owner.db.set_trace_callback(None)
            assert sum(q.startswith('BEGIN')for q in statements)==1
            assert owner.snapshot()['static_bytes_precharged']==0
        finally:other.close()


def test_192_segment_equivalent_real_owner_corpus_has_constant_grouped_queries(tmp_path):
    p=policy();counts={};started=perf_counter_ns()
    with s.PhysicalStorage(tmp_path,p,binding(p),create=True)as owner:
        owner.reserve('f'*64,'RETAINED',128*2**20,dict(kind='STATIC_AND_BOUNDED_ROOT_CONTROL'),scope='study')
        owner.register_path('study/jobs',kind='DIRECTORY');(tmp_path/'study/jobs').mkdir(parents=True)
        for index in range(192):
            completed(owner,index)
            if index+1 in(1,64,96,192):
                traced=[];owner.db.set_trace_callback(traced.append)
                try:current=owner.snapshot()
                finally:owner.db.set_trace_callback(None)
                assert current==old_snapshot(owner)
                assert not any('MANIFEST'in q.upper()or 'PRODUCER'in q.upper()or 'SUM('in q.upper()for q in traced)
                assert sum('FROM CLAIMS'in q.upper()for q in traced)==1
                counts[index+1]=len(traced)
        assert len(set(counts.values()))==1
        state=owner.snapshot();assert state['owned_files']==192 and state['namespace']['mutable_names']==576
        assert state['namespace']['unused_persistent_mutable_file_slots']==0
        assert state['namespace']['protected_metadata_pages_for_mutations']==128 # ROOT control, not192 forever-held grants.
        assert owner.namespace_snapshot()==old_namespace(owner)
        inventory=owner.inventory();assert len(inventory)==192
        report=dict(format='V6_REAL_PHYSICAL_OWNER_METADATA_CORPUS_V1',
            segment_equivalent_producers=192,operations=193,actual_sealed_immutable_files=192,actual_mutable_files=576,
            actual_seal_calls=192,native_allocation='REAL_PRODUCTION_SEAL_PATH; NO_DISABLED_CLAIM_OR_FAKE_ALLOCATION',
            snapshot_query_counts=counts,snapshot_matches_old_equations=True,owner_database_bytes=owner.path.stat().st_size,
            namespace=state['namespace'],elapsed_ns=perf_counter_ns()-started,
            scope='STORAGE_METADATA_ONLY; NOT192_SCIENTIFIC_JOBS_OR90D_CAPACITY_OR_PERFORMANCE_PROOF')
        (tmp_path/'V6-ACCOUNTING-CORPUS.json').write_bytes(s.encoded(report))
