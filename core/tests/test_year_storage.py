"""YEAR-V2 strict lossless object publication; synthetic DATA, no physics."""
from copy import deepcopy
from dataclasses import replace,asdict
from hashlib import sha256
import json
import pytest
from ops_sim.v5 import lifetime_status as o,lifetime_status_objects as obj
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,METHOD_OBJECTS,admit_policy,object_storage
from test_lifetime_status import job,binding,FakeWriter

def writer(tmp_path,**kw):
    return o.Publisher(tmp_path/'status',binding(),LifecycleStreamPolicy(),object_store=True,writer_factory=FakeWriter,**kw)

def sample():
    j=job();j['intent']['description']='immutable '+'abc'*700
    j['progress']={'padding':'dynamic '+'xyz'*1000}
    return j

def test_explicit_policy_identity_and_legacy_preservation():
    old=LifetimeCampaignPolicyV2();new=replace(old,method=METHOD_OBJECTS)
    assert not object_storage(old)and object_storage(new)and old.identity!=new.identity
    assert admit_policy(asdict(new))==new
    assert o.preflight(job(),binding()).envelope['format']==o.STORAGE

def test_pure_plan_complete_job_and_reader_roundtrip(tmp_path):
    j=sample();before=deepcopy(j);p=o.preflight(j,binding(),object_store=True)
    assert j==before and p.envelope['format']==o.STORAGE_OBJECTS
    assert p.job==dict(j,publication_sequence=1)and p.objects
    w=writer(tmp_path);w.publish(p)
    assert o.hydrate(w.directory,p.envelope,binding())==p.job
    assert sum(q.stat().st_size for q in (w.directory/'objects').iterdir())<len(o.raw(j))
    w.close()

def test_identical_large_fields_written_once_and_changed_progress_separate(tmp_path):
    w=writer(tmp_path);j=sample();p=o.preflight(j,binding(),object_store=True);w.publish(p)
    files={q.name:q.read_bytes()for q in (w.directory/'objects').iterdir()}
    j['publication_sequence']=1;j['progress']['padding']+='changed'
    q=o.preflight(j,binding(),object_store=True);w.publish(q)
    assert len(list((w.directory/'objects').iterdir()))==len(files)+1
    assert all((w.directory/'objects'/n).read_bytes()==b for n,b in files.items())
    assert o.hydrate(w.directory,p.envelope,binding())==p.job
    assert o.hydrate(w.directory,q.envelope,binding())==q.job
    w.close()

@pytest.mark.parametrize('fault',('encoded_hash','decoded_hash','tail','oversize','path','shape'))
def test_object_strict_binding_rejects(fault):
    fields,objects=obj.prepare({'field':'z'*1000});ref=deepcopy(fields['field']['object']);data=objects[0][1]
    if fault=='encoded_hash':ref['sha256']='0'*64
    elif fault=='decoded_hash':ref['decoded_sha256']='0'*64;ref['path']='objects/'+'0'*64+'.zjson'
    elif fault=='tail':data+=b'x';ref['bytes']=len(data);ref['sha256']=sha256(data).hexdigest()
    elif fault=='oversize':ref['decoded_bytes']=obj.LIMIT+1
    elif fault=='path':ref['path']='../escape.zjson'
    else:ref['extra']=1
    with pytest.raises(ValueError):obj.decode(ref,data)

@pytest.mark.parametrize('value',(True,1,None,'yes'))
def test_explicit_policy_flag(value):
    if value is True:return
    with pytest.raises(ValueError):o.preflight(job(),binding(),object_store=value)

def test_missing_and_corrupt_saved_object_refuse_without_rewrite(tmp_path):
    w=writer(tmp_path);p=o.preflight(sample(),binding(),object_store=True);w.publish(p)
    q=next((w.directory/'objects').iterdir());old=q.read_bytes();q.write_bytes(b'!'+old[1:])
    with pytest.raises(ValueError):o.hydrate(w.directory,p.envelope,binding())
    assert q.read_bytes()==b'!'+old[1:]
    j=sample();j['publication_sequence']=1
    with pytest.raises(ValueError):w.publish(o.preflight(j,binding(),object_store=True))
    assert w.sequence==1
    w.close()

def test_late_publication_failure_no_visible_head_attempt_cost_retained(tmp_path):
    class Bad(FakeWriter):
        def publish(self,*a,**k):raise OSError('injected durable head failure')
    charges=[];w=o.Publisher(tmp_path/'status',binding(),LifecycleStreamPolicy(),object_store=True,writer_factory=Bad,charge=charges.append)
    p=o.preflight(sample(),binding(),object_store=True)
    with pytest.raises(OSError,match='injected'):w.publish(p)
    assert w.failed and w.sequence==0 and sum(charges)>0
    assert (w.directory/p.envelope['details']['path']).exists()
    assert len(list((w.directory/'objects').iterdir()))==len(p.objects)
    with pytest.raises(ValueError):w.publish(p)
    w.close()

def test_field_objects_cannot_exceed_total_decoded_job():
    with pytest.raises(ValueError):obj.prepare({'a':'x'*(obj.LIMIT//2),'b':'y'*(obj.LIMIT//2)})
    with pytest.raises(ValueError):obj.restore({'a':{'inline':'x'*512}},lambda _:b'')
