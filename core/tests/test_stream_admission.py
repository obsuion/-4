"""Tiny hostile manifests must refuse before count-driven enumeration."""
from copy import deepcopy
import builtins,json
from pathlib import Path
import pytest
from ops_sim.v5 import lifecycle_stream as stream
from ops_sim.v5.lifecycle_compact import CompactStreamWriter,PublicationProfile


def artifact(tmp_path,compact):
    p=tmp_path/('compact'if compact else'raw');policy=stream.LifecycleStreamPolicy()
    writer=CompactStreamWriter(p,policy,2**20)if compact else stream.ChunkedStreamWriter(p,policy,2**20)
    writer.append({'record':1});frontier=writer.finish()
    return p,frontier


@pytest.mark.parametrize('compact',[False,True])
@pytest.mark.parametrize('key,bad',[('sealed_chunks',2**40),('sealed_chunks',True),('sealed_chunks',-1),('records',False),('index_bytes',-1),('index_bytes',True),('maximum_bytes',2**41),('sealed_bytes',-1)])
def test_hostile_count_admission_precedes_inventory(tmp_path,monkeypatch,compact,key,bad):
    p,f=artifact(tmp_path,compact);f=deepcopy(f);f[key]=bad
    (p/'manifest.json').write_text(json.dumps(f))
    def forbidden(*args,**kwargs):raise AssertionError('inventory reached before admission')
    monkeypatch.setattr(stream,'_whole_inventory',forbidden)
    def bounded_range(*args):
        if any(abs(x)>1000 for x in args):raise AssertionError('untrusted huge range')
        return builtins.range(*args)
    monkeypatch.setattr(stream,'range',bounded_range,raising=False)
    with pytest.raises((ValueError,TypeError)):list(stream.iter_stream_records(p))


@pytest.mark.parametrize('compact',[False,True])
def test_population_bound_and_strict_final_inventory(tmp_path,compact):
    p,f=artifact(tmp_path,compact)
    assert list(stream.iter_stream_records(p))==[{'record':1}]
    (p/'surplus.tmp').write_text('data')
    with pytest.raises(ValueError,match='unexpected'):list(stream.iter_stream_records(p))
    assert list(stream.iter_stream_records(p,f))==[{'record':1}]


@pytest.mark.parametrize('compact',[False,True])
def test_count_inconsistent_with_tiny_index_rejected_without_population(tmp_path,monkeypatch,compact):
    p,f=artifact(tmp_path,compact);f['sealed_chunks']=10**6
    f['work']['index_records']=10**6;f['records']=10**6;f['end_record']=f['start_record']+10**6
    f['work']['records_completed']=f['work']['record_attempts']=10**6
    def forbidden(*a,**kw):raise AssertionError('population must be admitted first')
    monkeypatch.setattr(stream,'_whole_inventory',forbidden)
    (p/'manifest.json').write_text(json.dumps(f))
    with pytest.raises(ValueError):list(stream.iter_stream_records(p))
