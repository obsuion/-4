"""Synthetic B53 stream/retention checks; no spacecraft model execution."""
from dataclasses import replace
from hashlib import sha256
import json,struct
import pytest
from ops_sim.v5.lifecycle_stream import (LifecycleStreamPolicy,ChunkedStreamWriter,
    iter_stream_records,verify_stream,IncrementalStreamReader,StatusStream,read_latest_status,
    CheckpointCatalog,checkpoint_page,lookup_checkpoint,iter_checkpoint_catalog)


def policy():return LifecycleStreamPolicy(chunk_bytes=4096,max_record_bytes=1024)


def test_status_quota_reserves_terminal_publications(tmp_path):
    p=LifecycleStreamPolicy(chunk_bytes=4096,max_record_bytes=1024,status_total_bytes=65536)
    writer=StatusStream(tmp_path/'status-reserve',p);completed=0
    while True:
        try:writer.publish({'status':'RUNNING','padding':'x'*800});completed+=1
        except ValueError as error:
            assert 'terminal reserve' in str(error);break
    assert completed>0 and not writer.writer.failed
    writer.publish({'status':'PROCESS_FAILED','reason':'expected injected ordinary status quota'},terminal=True)
    writer.close();value,proof=read_latest_status(tmp_path/'status-reserve',p)
    assert value['status']=='PROCESS_FAILED' and proof['sequence']==completed+1


@pytest.mark.parametrize('changes',[dict(chunk_bytes=True),dict(chunk_bytes=0),dict(max_record_bytes=8192),
    dict(publication_minimum_wall_seconds=True),dict(publication_minimum_wall_seconds=float('nan')),
    dict(events_total_bytes=0),dict(working_checkpoint_every_events=0),dict(method='old')])
def test_exact_finite_policy(changes):
    with pytest.raises((ValueError,TypeError)):replace(policy(),**changes)


def test_raw_records_all_retained_across_chunks_and_saved_reader(tmp_path):
    p=policy();writer=ChunkedStreamWriter(tmp_path/'events',p,2**20,start_record=100)
    rows=[dict(index=i,data='x'*300) for i in range(80)]
    for row in rows:writer.append(row)
    manifest=writer.finish()
    assert manifest['records']==80 and manifest['end_record']==180 and manifest['sealed_chunks']>1
    assert list(iter_stream_records(tmp_path/'events'))==rows
    assert verify_stream(tmp_path/'events',manifest,p)['records']==80
    assert writer.records==80 and writer.work['record_attempts']==80
    assert not hasattr(writer,'history') and not hasattr(writer,'chunks')


def test_checkpoint_prefix_survives_later_append_rotation_and_final_seal(tmp_path):
    p=policy();writer=ChunkedStreamWriter(tmp_path/'events',p,2**20)
    writer.append(dict(n=1));prefix=writer.snapshot()
    for n in range(2,41):writer.append(dict(n=n,data='y'*300))
    final=writer.finish()
    assert list(iter_stream_records(tmp_path/'events',prefix,p))==[dict(n=1)]
    assert len(list(iter_stream_records(tmp_path/'events',final,p)))==40
    assert prefix['index_bytes']==0 and final['index_bytes']>0


def test_quota_refusal_never_refunds_attempted_publication_and_keeps_prior_prefix(tmp_path):
    p=policy();charged=[]
    def charge(n):
        charged.append(n)
        if len(charged)==2:raise ValueError('injected output reservation refusal')
    writer=ChunkedStreamWriter(tmp_path/'events',p,2**20,charge=charge)
    writer.append(dict(n=1));prefix=writer.snapshot()
    with pytest.raises(ValueError,match='injected'):writer.append(dict(n=2))
    assert writer.failed and writer.work['record_attempts']==2 and writer.work['records_completed']==1
    assert writer.work['encoded_bytes_reserved']==sum(charged)>writer.work['bytes_published']
    assert list(iter_stream_records(tmp_path/'events',prefix,p))==[dict(n=1)]
    writer.close()


def test_oversize_record_fails_before_any_raw_publication(tmp_path):
    writer=ChunkedStreamWriter(tmp_path/'events',policy(),2**20)
    with pytest.raises(ValueError,match='record'):writer.append(dict(data='x'*2000))
    assert writer.work['record_attempts']==1 and writer.records==0
    assert not list((tmp_path/'events').glob('chunk-*'))
    writer.close()


def test_raw_tamper_and_index_tamper_rejected(tmp_path):
    p=policy();writer=ChunkedStreamWriter(tmp_path/'events',p,2**20)
    writer.append(dict(n=1));manifest=writer.finish();chunk=tmp_path/'events/chunk-00000001.jsonl'
    original=chunk.read_bytes();chunk.write_bytes(original.replace(b'1',b'2'))
    with pytest.raises(ValueError):verify_stream(tmp_path/'events',manifest,p)
    chunk.write_bytes(original);index=tmp_path/'events/index.jsonl';raw=index.read_bytes();index.write_bytes(raw.replace(b'"records":1',b'"records":2'))
    with pytest.raises(ValueError):verify_stream(tmp_path/'events',manifest,p)


def test_live_incremental_reader_has_no_rescan_and_explicit_incomplete_tail(tmp_path):
    p=policy();folder=tmp_path/'events';folder.mkdir();path=folder/'chunk-00000001.jsonl'
    path.write_bytes(b'{"n":1}\n{"n":')
    reader=IncrementalStreamReader(folder,p,2**20)
    assert reader.read()==[dict(n=1)] and reader.tail
    offset=reader.offset
    with path.open('ab') as stream:stream.write(b'2}\n')
    assert reader.read()==[dict(n=2)] and not reader.tail and reader.offset>offset
    assert reader.read()==[] and reader.records==2
    second=folder/'chunk-00000002.jsonl';second.write_bytes(b'{"n":3}\n')
    assert reader.read()==[dict(n=3)] and reader.chunk==2


def test_live_partial_tail_before_next_chunk_is_error(tmp_path):
    folder=tmp_path/'events';folder.mkdir();(folder/'chunk-00000001.jsonl').write_bytes(b'{"n":')
    (folder/'chunk-00000002.jsonl').write_bytes(b'{"n":2}\n')
    with pytest.raises(ValueError,match='tail'):IncrementalStreamReader(folder,policy(),2**20).read()


def test_append_only_status_while_reader_holds_head_no_replace_or_unlink(tmp_path):
    p=policy();store=StatusStream(tmp_path/'status',p)
    first=dict(sequence=1,status='RUNNING');second=dict(sequence=2,status='COMPLETE')
    store.publish(first);head=tmp_path/'status/heads.bin';prefix=head.read_bytes()
    with head.open('rb') as held:
        store.publish(second)
        assert held.read(len(prefix))==prefix and head.read_bytes().startswith(prefix)
    value,proof=read_latest_status(tmp_path/'status',p)
    assert value==second and proof['sequence']==2 and proof['incomplete_head_tail_bytes']==0
    store.close()
    assert len(list(iter_stream_records(tmp_path/'status/records')))==2


def test_incomplete_status_head_retains_last_complete_and_does_not_repair(tmp_path):
    p=policy();store=StatusStream(tmp_path/'status',p);store.publish(dict(n=1));store.close()
    head=tmp_path/'status/heads.bin'
    with head.open('ab') as stream:stream.write(b'bad')
    before=head.read_bytes();value,proof=read_latest_status(tmp_path/'status',p)
    assert value==dict(n=1) and proof['incomplete_head_tail_bytes']==3 and head.read_bytes()==before


def test_checkpoint_catalog_direct_lookup_bounded_page_and_retirement(tmp_path):
    catalog=CheckpointCatalog(tmp_path/'checkpoints',2**20);rows=[]
    for i in range(1,41):
        cp=dict(file='checkpoint-'+str(i).zfill(8)+'.json',sha256=sha256(str(i).encode()).hexdigest(),kind='MONTH_BOUNDARY',clock=i)
        catalog.append(cp);rows.append(cp)
    page=checkpoint_page(tmp_path/'checkpoints',limit=3)
    assert [x['sequence'] for x in page['entries']]==[40,39,38] and page['next_before']==38
    selected,proof=lookup_checkpoint(tmp_path/'checkpoints',rows[10]['sha256'])
    assert selected==rows[10] and proof['raw_available'] is True
    record=catalog.retire(11,'DECLARED_LAST_TWO_WORKING_RETENTION')
    assert record['raw_revalidation'].startswith('NOT_AVAILABLE')
    assert lookup_checkpoint(tmp_path/'checkpoints',rows[10]['sha256'])[1]['raw_available'] is False
    assert len(list(iter_checkpoint_catalog(tmp_path/'checkpoints')))==40
    assert not hasattr(catalog,'history')
    catalog.close()


def test_checkpoint_catalog_same_sha_uses_latest_publication_and_keeps_old(tmp_path):
    catalog=CheckpointCatalog(tmp_path/'checkpoints',2**20);digest=sha256(b'unchanged-native').hexdigest()
    one=dict(file='checkpoint-00000001.json',sha256=digest,kind='COOPERATIVE_STOP_PAID_PREFIX',clock=100)
    two=dict(file='checkpoint-00000002.json',sha256=digest,kind='FINAL',clock=100)
    catalog.append(one);catalog.append(two)
    cp,proof=lookup_checkpoint(tmp_path/'checkpoints',digest)
    assert cp==two and proof['sequence']==2
    assert [x['checkpoint'] for x in iter_checkpoint_catalog(tmp_path/'checkpoints')]==[one,two]
    catalog.close()


def test_b55_mixed_named_retention_keeps_kind_and_catalog_authority(tmp_path):
    from ops_sim.v5.lifecycle_contract import METHOD55
    folder=tmp_path/'b55-mixed-named';charges=[]
    catalog=CheckpointCatalog(folder,2**20,charge=charges.append)
    kinds=('AUDIT_NAMED','SERVICE_SAFE','SERVICE_POWER_OFF','SERVICE_RECOVERY','AUDIT_NAMED','SERVICE_SAFE')
    kept=[];retired=[];reason='DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS'
    try:
        for number,kind in enumerate(kinds,1):
            cp=dict(file='checkpoint-'+str(number).zfill(8)+'.json',
                sha256=sha256(('native-'+str(number)).encode()).hexdigest(),
                kind=kind,clock=128+number,bindings=dict(method=METHOD55))
            catalog.append(cp);kept.append((number,cp))
            if len(kept)>2:
                sequence,old=kept.pop(0);tombstone=catalog.retire(sequence,reason)
                assert tombstone['reason']==reason and tombstone['checkpoint_sha256']==old['sha256']
                assert tombstone['raw_revalidation']=='NOT_AVAILABLE_AFTER_DECLARED_RETIREMENT'
                retired.append(sequence)
        assert retired==[1,2,3,4] and [n for n,_ in kept]==[5,6]
        rows=list(iter_checkpoint_catalog(folder))
        assert [r['checkpoint']['kind']for r in rows]==list(kinds)
        assert all(r['checkpoint']['bindings']['method']==METHOD55 for r in rows)
        for row in rows:
            original=row['checkpoint'];indexed,proof=lookup_checkpoint(folder,original['sha256'])
            assert indexed==original and proof['raw_available']==(row['sequence']not in retired)
        page=checkpoint_page(folder,limit=6)
        assert page['total_publications']==6 and [r['raw_available']for r in page['entries']]==[True,True,False,False,False,False]
        assert catalog.sequence==6 and catalog.published==catalog.reserved==sum(charges)
    finally:catalog.close()


@pytest.mark.parametrize('method,kind,reason',[
    ('B52_CHRONOLOGICAL_NOMINAL_ACK_GATED_V1','AUDIT_NAMED','DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS'),
    ('B53_ADAPTIVE_QUIET_CHRONOLOGICAL_NOMINAL_V1','SERVICE_SAFE','DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS'),
    ('MISSING','SERVICE_RECOVERY','DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS'),
    (None,'SERVICE_POWER_OFF','DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS'),
    (True,'AUDIT_NAMED','DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS'),
    ('B55_CONSTRUCTION_RECOVERY_CHRONOLOGICAL_NOMINAL_V1','WORKING','DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS'),
    ('B55_CONSTRUCTION_RECOVERY_CHRONOLOGICAL_NOMINAL_V1','MONTH_BOUNDARY','DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS'),
    ('B55_CONSTRUCTION_RECOVERY_CHRONOLOGICAL_NOMINAL_V1','SERVICE_NORMAL','DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS'),
    ('B55_CONSTRUCTION_RECOVERY_CHRONOLOGICAL_NOMINAL_V1','SERVICE_SAFE','DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS_EXTRA'),
])
def test_b55_named_retirement_rejects_wrong_authority_before_publication(tmp_path,method,kind,reason):
    folder=tmp_path/'reject-b55-retirement';charges=[]
    catalog=CheckpointCatalog(folder,2**20,charge=charges.append)
    cp=dict(file='checkpoint-00000001.json',sha256=sha256(b'native').hexdigest(),kind=kind,clock=128)
    if method!='MISSING':cp['bindings']=dict(method=method)
    try:
        catalog.append(cp)
        files={p.relative_to(folder).as_posix():p.read_bytes()for p in folder.rglob('*')if p.is_file()}
        before=(catalog.published,catalog.reserved,catalog.sequence,catalog.chain,tuple(charges))
        with pytest.raises(ValueError,match='checkpoint retirement scope'):catalog.retire(1,reason)
        assert (catalog.published,catalog.reserved,catalog.sequence,catalog.chain,tuple(charges))==before
        assert {p.relative_to(folder).as_posix():p.read_bytes()for p in folder.rglob('*')if p.is_file()}==files
        assert not(folder/'retired').exists()
        selected,proof=lookup_checkpoint(folder,cp['sha256'])
        assert selected==cp and proof['raw_available']is True
    finally:catalog.close()
