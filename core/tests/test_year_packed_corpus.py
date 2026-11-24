"""Long administrative corpus; no physical/scientific constructor is used.

Run separately from the focused storage gate so the paid test ledger records
its real wall/RAM cost. The corpus is synthetic, not an annual mission result.
"""
from hashlib import sha256
from pathlib import Path
import json
import zlib
from time import perf_counter_ns

from ops_sim.v5 import lifetime_packed_status as packed


def test_more_than_old_global_files_and_four_mib_pool_equivalent(tmp_path,monkeypatch):
    binding=dict(job_id='1'*32,root_identity='2'*64,source_identity='4'*64,
        request_sha256='6'*64,profile_identity=None,runner_policy_identity='7'*64,
        runtime=dict(implementation='CPython',version=[3,14,7]))
    from ops_sim.v5.lifecycle_application import _memory_sample
    memory_before=_memory_sample();memory_samples=[dict(logical_objects=0,**memory_before)]
    monkeypatch.setattr(packed,'_claim',lambda path:None)
    old_open=Path.open;sealed=set();old_reads=[]
    def guarded_open(path,mode='r',*args,**kwargs):
        if str(path)in sealed and 'r'in mode:
            old_reads.append(str(path));raise AssertionError('ordinary put reread a previously sealed block')
        return old_open(path,mode,*args,**kwargs)
    equivalent=0;first=last=None;started=perf_counter_ns()
    with packed.PackedStatus(tmp_path,binding,create=True)as store:
        original_seal=store._seal_block
        def seal(number,size):
            result=original_seal(number,size);sealed.add(str(store._block_path(number)));return result
        monkeypatch.setattr(store,'_seal_block',seal)
        monkeypatch.setattr(Path,'open',guarded_open)
        for number in range(33001):
            decoded=packed.raw(dict(number=number,text='x'*96))
            key='objects/'+sha256(decoded).hexdigest()+'.zjson';data=zlib.compress(decoded,6)
            store.put(key,data,role='FIELD')
            equivalent+=len(packed.raw(dict(path=key,sha256=sha256(data).hexdigest(),bytes=len(data))))+1
            if first is None:first=(key,data)
            last=(key,data)
            if (number+1)%4096==0:memory_samples.append(dict(logical_objects=number+1,**_memory_sample()))
        snapshot=store.snapshot()
        assert snapshot['logical_objects']==33001>32768
        assert equivalent>4*2**20
        assert snapshot['index_bytes']<=16*2**20
        assert snapshot['blocks']<=128 and old_reads==[]
    monkeypatch.setattr(Path,'open',old_open)
    append_elapsed_ns=perf_counter_ns()-started;import_started=perf_counter_ns()
    with packed.PackedStatus(tmp_path,binding)as reader:
        assert reader.read(first[0])==first[1] and reader.read(last[0])==last[1]
        checked=reader.verify_import()
        assert checked['objects']==33001
        checked['reader_bytes']=reader.snapshot()['bytes_read']
    import_elapsed_ns=perf_counter_ns()-import_started
    memory_after=_memory_sample();memory_samples.append(dict(logical_objects=33001,**memory_after))
    available=[x['current_rss_bytes']for x in memory_samples if x['status']=='AVAILABLE']
    if len(available)==len(memory_samples):
        assert max(available)-min(available)<64*2**20
    physical_files=sum(path.is_file()for path in(tmp_path/'packed-v1').iterdir())
    assert physical_files<128+3
    report=dict(format='YEAR_V5_SYNTHETIC_PACKED_CORPUS_V1',logical_objects=33001,
        old_pool_equivalent_bytes=equivalent,physical_files=physical_files,
        index_bytes=snapshot['index_bytes'],blocks=snapshot['blocks'],
        old_prefix_reads=len(old_reads),explicit_import=checked,
        append_elapsed_ns=append_elapsed_ns,explicit_import_elapsed_ns=import_elapsed_ns,
        memory_samples=memory_samples,
        bounded_rss_growth_limit_bytes=64*2**20,
        scope='SYNTHETIC_ADMINISTRATIVE_DATA_NOT_YEAR_CAPACITY_OR_MISSION_QUALIFICATION')
    (tmp_path/'CORPUS-RESULT.json').write_text(json.dumps(report,sort_keys=True,indent=2),encoding='utf8')
