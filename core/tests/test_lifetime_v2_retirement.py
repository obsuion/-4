"""Real bounded metadata storage and caller paths; no physical executions."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from ops_sim.v5 import lifecycle_application as owner,lifetime_status
from test_lifetime_v2_caller import metadata_store,intent_for,settle_metadata


def immutable_bytes(store):
    return {p.relative_to(store.directory).as_posix():p.read_bytes()
        for p in store.directory.rglob('*') if p.is_file()}


def test_many_actual_metadata_caller_segments_keep_constant_active_resources(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch);parent=None;first=None
    for n in range(1,19):
        job,new=store.prepare_job(intent_for(store,n,parent=parent));assert new
        assert len(store._cache)<=owner.LIFETIME_HYDRATED_CACHE_LIMIT
        assert len(store._status_writers)==1 and len(store._catalogs)==0
        parent=settle_metadata(store,job,128+n)
        if first is None:first=deepcopy(parent)
        assert store._cache=={} and store._status_writers=={} and store._catalogs=={} and store._parent_work=={}
    before=immutable_bytes(store)
    for _ in range(3):
        rows=store.jobs()
        old=store.job(first['job_id']);latest=store.job(parent['job_id'])
        assert old==first and latest==parent and len(rows)==18
        old['result']['reason']='caller mutation'
        assert store.job(first['job_id'])==first
        assert store._cache=={} and store._status_writers=={} and store._catalogs=={}
    assert immutable_bytes(store)==before
    assert next(row for row in rows if row['job_id']==parent['job_id'])['result']['checkpoint']==parent['result']['checkpoint']
    store.close_publications()


def test_old_primary_and_diagnostic_readers_remain_strict_after_retirement(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch)
    primary,_=store.prepare_job(intent_for(store,1))
    primary=settle_metadata(store,primary,10000,extra_checkpoint=True,terminal_kind='TARGET',working_clock=200)
    selected=primary['checkpoints'][0]
    diagnostic,_=store.prepare_job(intent_for(store,2,parent=primary,checkpoint=selected,
        mode='DIAGNOSTIC_NORMAL',window=500))
    diagnostic=settle_metadata(store,diagnostic,300)
    before=immutable_bytes(store)
    assert store.job(primary['job_id'])==primary and store.job(diagnostic['job_id'])==diagnostic
    assert store.find_checkpoint(primary['job_id'],selected['sha256'])==selected
    assert store.checkpoint_history(primary['job_id'])['entries']
    assert immutable_bytes(store)==before and store._cache=={}
    # An old details payload is still hash-admitted on demand, never trusted
    # merely because its compact head was seen by a previous listing.
    binding=store._status_binding(primary['job_id'])
    envelope,_=lifetime_status.read_envelope(store.path('jobs',primary['job_id'],'status63'),binding,store.root_input.output_policy)
    path=store.path('jobs',primary['job_id'],'status63').joinpath(envelope['details']['path'])
    raw=path.read_bytes();path.write_bytes(raw[:-1]+b' ')
    with pytest.raises(ValueError,match='details exact hash'):store.job(primary['job_id'])
    assert store._cache=={}
    store.close_publications()


def test_terminal_writer_and_catalog_never_reopen_after_full_read(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch)
    job,_=store.prepare_job(intent_for(store,1));terminal=settle_metadata(store,job,129)
    before=immutable_bytes(store)
    def forbidden(*a,**k):raise AssertionError('terminal writer factory was reopened')
    monkeypatch.setattr(lifetime_status,'Publisher',forbidden)
    monkeypatch.setattr(owner,'CheckpointCatalog',forbidden)
    full=store.job(job['job_id'])
    with pytest.raises(ValueError,match='immutable terminal'):store.update_job(full)
    with pytest.raises(ValueError,match='immutable terminal'):store.checkpoint_catalog(job['job_id'])
    runner=owner.LifecycleRunner(store)
    assert runner.stop(job['job_id'])==terminal
    assert immutable_bytes(store)==before
    assert store._cache=={} and store._status_writers=={} and store._catalogs=={}
    store.close_publications()


def test_compact_listing_retires_terminal_handles_without_hydration(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch)
    job,_=store.prepare_job(intent_for(store,1))
    # Delay the explicit handoff once, to exercise the independently used
    # supervisor/status-list route against a real durable terminal head.
    original=store.retire_lifetime_job;store.retire_lifetime_job=lambda jid:None
    terminal=settle_metadata(store,job,129);store.retire_lifetime_job=original
    assert len(store._status_writers)==1 and len(store._catalogs)==1
    def forbidden(*a,**k):raise AssertionError('listing hydrated a historical full job')
    monkeypatch.setattr(lifetime_status,'hydrate',forbidden)
    rows=store.jobs()
    assert rows[0]['job_id']==terminal['job_id']
    assert store._cache=={} and store._status_writers=={} and store._catalogs=={}
    store.close_publications()


def test_retirement_close_failures_preserve_terminal_and_every_error(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch)
    job,_=store.prepare_job(intent_for(store,1))
    original=store.retire_lifetime_job;store.retire_lifetime_job=lambda jid:None
    terminal=settle_metadata(store,job,129);store.retire_lifetime_job=original
    jid=job['job_id'];closed=[]
    class FailingClose:
        def __init__(self,name,resource):self.name=name;self.resource=resource
        def close(self):
            closed.append(self.name);self.resource.close()
            raise OSError('injected close '+self.name)
    store._status_writers[jid]=FailingClose('status',store._status_writers[jid])
    store._catalogs[jid]=FailingClose('catalog',store._catalogs[jid])
    head=store.path('jobs',jid,'status63','head','heads.bin').read_bytes()
    ledger=store.path('jobs',jid,'parent-publication-work.bin').read_bytes()
    charges=[];original_charge=store._parent_charge
    def charge(job_id,n):
        assert job_id==jid
        original_charge(job_id,n);charges.append(n)
    monkeypatch.setattr(store,'_parent_charge',charge)
    with pytest.raises(RuntimeError,match='retirement failed') as failure:store.retire_lifetime_job(jid)
    assert closed==['status','catalog']
    assert [name.split(':')[0] for name,error in failure.value.close_failures]==['status','catalog']
    assert store._cache=={} and store._status_writers=={} and store._catalogs=={}
    assert store._lifetime_retirement_failed and store.path('dispatch-quarantine.json').is_file()
    error_files=list(store.path('jobs',jid,'status63','parent-errors').glob('error-*.json'))
    assert len(error_files)==1
    error=json.loads(error_files[0].read_bytes())
    assert error['stage']=='TERMINAL_PUBLICATION_RETIREMENT'
    assert error['primary_message']=='injected close status'
    assert error['secondary'][0]['message']=='injected close catalog'
    assert store.job(jid)==terminal
    assert store.path('jobs',jid,'status63','head','heads.bin').read_bytes()==head
    after=store.path('jobs',jid,'parent-publication-work.bin').read_bytes()
    assert after.startswith(ledger)
    suffix=after[len(ledger):];record=owner.PARENT_COST
    assert len(suffix)==record.size*len(charges) and charges
    sequence,total=record.unpack(ledger[-record.size:])
    for offset,n in enumerate(charges):
        sequence+=1;total+=n+record.size
        assert record.unpack(suffix[offset*record.size:(offset+1)*record.size])==(sequence,total)
    assert store._parent_work=={}
    with pytest.raises(ValueError,match='quarantined'):store.prepare_job(intent_for(store,2,parent=terminal))
    with pytest.raises(ValueError,match='quarantined'):owner.LifecycleRunner(store)._claim_dispatch()
    assert not store.path('dispatch-owner.json').exists()
    store.close_publications()


def test_retirement_latches_even_if_independent_error_publication_fails(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch)
    job,_=store.prepare_job(intent_for(store,1));terminal=settle_metadata(store,job,129)
    class Failed:
        def close(self):raise OSError('injected original close')
    store._status_writers[job['job_id']]=Failed()
    def failure(*a,**k):raise OSError('injected independent channel')
    monkeypatch.setattr(store,'parent_error',failure)
    with pytest.raises(RuntimeError) as raised:store.retire_lifetime_job(job['job_id'])
    assert str(raised.value.__cause__)=='injected original close'
    assert [str(e)for e in raised.value.reporting_failures]==['injected independent channel']
    assert store.job(job['job_id'])==terminal and store._status_writers=={}
    with pytest.raises(ValueError,match='quarantined'):store.prepare_job(intent_for(store,2,parent=terminal))
    store.close_publications()


def test_explicit_hydration_cap_and_final_close_cannot_reactivate_writer(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch)
    store._cache={f'{n:032x}':{} for n in range(owner.LIFETIME_HYDRATED_CACHE_LIMIT)}
    with pytest.raises(ValueError,match='bounded lifetime hydrated'):store._admit_lifetime_cache_slot('f'*32)
    store._cache.clear()
    job,_=store.prepare_job(intent_for(store,1));terminal=settle_metadata(store,job,129)
    store.close_publications();before=immutable_bytes(store)
    assert store.job(job['job_id'])==terminal
    with pytest.raises(ValueError,match='publications closed'):store.update_job(deepcopy(terminal))
    with pytest.raises(ValueError,match='publications closed'):store.checkpoint_catalog(job['job_id'])
    with pytest.raises(ValueError,match='publications closed'):store.prepare_job(intent_for(store,2,parent=terminal))
    assert immutable_bytes(store)==before
    assert store._cache=={} and store._status_writers=={} and store._catalogs=={}


def test_final_close_saves_all_errors_and_drops_active_registries(tmp_path,monkeypatch):
    store,_=metadata_store(tmp_path,monkeypatch)
    job,_=store.prepare_job(intent_for(store,1));calls=[]
    original=store._status_writers[job['job_id']]
    class Fail:
        def __init__(self,name,resource=None):self.name=name;self.resource=resource
        def close(self):
            calls.append(self.name)
            if self.resource is not None:self.resource.close()
            raise OSError('final close '+self.name)
    store._status_writers[job['job_id']]=Fail('status',original)
    store._catalogs[job['job_id']]=Fail('catalog')
    with pytest.raises(RuntimeError,match='publication close failures') as raised:store.close_publications()
    assert calls==['status','catalog'] and len(raised.value.close_failures)==2
    assert len(raised.value.retirement_failures)==1
    assert store._lifetime_publications_closed and store._lifetime_retirement_failed
    assert store._cache=={} and store._status_writers=={} and store._catalogs=={}
    errors=list(store.path('jobs',job['job_id'],'status63','parent-errors').glob('error-*.json'))
    assert len(errors)==1
    saved=json.loads(errors[0].read_bytes())
    assert saved['primary_message']=='final close status'
    assert saved['secondary'][0]['message']=='final close catalog'
    with pytest.raises(ValueError,match='closed'):store.update_job(job)
    with pytest.raises(ValueError,match='quarantined'):owner.LifecycleRunner(store)._claim_dispatch()
