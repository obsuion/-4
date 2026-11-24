from pathlib import Path
from dataclasses import replace
import json,zipfile
import pytest
from ops_sim.v5.portable_job import safe,write_bundle,read_bundle,JOB,RESULT,horizon_preflight,prepare,admit_job,inspect_result,canonical

@pytest.mark.parametrize('name',['../x','/x','x/../y','x\\y','C:/x','a//b','a/./b','con.txt','x ','a:b','a\x00'])
def test_path_rejection(name):
    with pytest.raises(ValueError):safe(name)

def test_bundle_roundtrip_and_no_dispatch(tmp_path):
    p=tmp_path/'a.zip';write_bundle(p,JOB,{'input.json':b'{}'})
    assert read_bundle(p,JOB)=={'input.json':b'{}'}
    with pytest.raises(ValueError):read_bundle(p,RESULT)

@pytest.mark.parametrize('case',['duplicate','symlink','traversal','unknown','size','bad_hash','casefold'])
def test_malformed_archive(tmp_path,case):
    p=tmp_path/'bad.zip';m={'format':JOB,'files':{'input.json':{'bytes':2,'sha256':'0'*64}}}
    with zipfile.ZipFile(p,'w')as z:
        z.writestr('MANIFEST.json',canonical(m));z.writestr('input.json',b'{}')
        if case=='duplicate':z.writestr('input.json',b'{}')
        elif case=='traversal':z.writestr('../bad',b'x')
        elif case=='symlink':
            i=zipfile.ZipInfo('link');i.create_system=3;i.external_attr=0o120777<<16;z.writestr(i,b'input.json')
        elif case=='unknown':z.writestr('unknown',b'x')
        elif case=='casefold':z.writestr('INPUT.JSON',b'{}')
    with pytest.raises(ValueError):read_bundle(p,JOB)

def test_horizon_refuses_year_without_monthly_reset():
    from examples.m8_battery_port import make_inputs
    from ops_sim.v5.lifecycle_contract import YEAR
    root=make_inputs(duration=7200,energy=80.)
    for d,ok in [(2592000,True),(YEAR,False),(15*YEAR,False)]:
        h=horizon_preflight(replace(root,duration_seconds=d))
        assert h['admitted']is ok and h['causal_end_seconds']==128+d
        assert h['full_buckets']*2592000+h['partial_bucket_seconds']==d

def test_prepare_consumes_installed_source_and_strict_job(tmp_path):
    from examples.m8_battery_port import make_inputs
    root=make_inputs(duration=600,energy=80.);source=Path(__file__).resolve().parents[1]
    p=tmp_path/'job.zip';prepare(p,root,source,key='a'*32)
    j,r,raw=admit_job(p,source);assert r.identity==root.identity and j['native_import']is False
    data=read_bundle(p,JOB);j['command']='arbitrary';data['job.json']=canonical(j)
    bad=tmp_path/'bad.zip';write_bundle(bad,JOB,data)
    with pytest.raises(ValueError,match='EXACT_FIELDS'):admit_job(bad,source)

def test_read_only_result_has_no_execution_rights(tmp_path):
    p=tmp_path/'result.zip';v=dict(format=RESULT,root_identity='a'*64,jobs=[],read_only=True,native_execution_rights=False,credits_scope='DISPLAY',runtime={})
    write_bundle(p,RESULT,{'view.json':canonical(v)})
    assert inspect_result(p)['native_execution_rights']is False


def test_cancelled_settled_result_is_exportable_readonly(tmp_path):
    from types import SimpleNamespace
    from ops_sim.v5.portable_job import export_result
    directory=tmp_path/'store';directory.mkdir()
    j=dict(job_id='1'*32,root_identity='a'*64,status='CANCELLED',result=None)
    store=SimpleNamespace(directory=directory,_pinned=lambda:None,jobs=lambda:[j],root_input=SimpleNamespace(identity='a'*64),runtime={})
    target=tmp_path/'cancelled.zip';export_result(store,target)
    v=inspect_result(target)
    assert v['jobs']==[j]and not v['native_execution_rights']


def test_current_versioned_producer_retains_exact_membership():
    from m8_fast_campaign_cli import trusted_worker_binding as old_binding
    with pytest.raises(ValueError,match='membership drift'):old_binding()
    from m8_environment_campaign_cli import trusted_worker_binding,EXPECTED_WORKER_MEMBERS
    # B61 producer remains exact and refuses the successor membership.
    with pytest.raises(ValueError,match='membership drift'):trusted_worker_binding()
    assert len(EXPECTED_WORKER_MEMBERS)==720
    from ops_sim.v5.lifetime_source import SOURCE_PATHS
    assert set(EXPECTED_WORKER_MEMBERS)<set(SOURCE_PATHS)
    assert 'ops_sim/v5/lifecycle_fast.py'in SOURCE_PATHS
    assert 'ops_sim/v5/lifecycle_process.py'in SOURCE_PATHS


def test_raw_parent_status_has_prospective_separate_unchanged_total_cap(tmp_path):
    from examples.m8_battery_port import make_inputs
    from ops_sim.v5.portable_job import create_store
    from ops_sim.v5.lifecycle_application import PARENT_COST
    source=Path(__file__).resolve().parents[1];package=tmp_path/'raw.zip'
    prepare(package,make_inputs(duration=600,energy=80.),source,key='b'*32)
    store,intent=create_store(package,tmp_path/'raw-store',source)
    j,new=store.prepare_job(intent)
    ledger=store.path('jobs',j['job_id'],'parent-publication-work.bin')
    assert new and ledger.stat().st_size==PARENT_COST.size
    assert store._parent_work[j['job_id']][1]>0
    with pytest.raises(ValueError,match='allowance'):store._parent_charge(j['job_id'],9*2**20)
    assert ledger.stat().st_size==PARENT_COST.size
    store.close_publications()


def test_every_job_pins_strategy_and_rejects_metadata_stripping(tmp_path):
    from examples.m8_battery_port import make_inputs
    from ops_sim.v5.portable_job import create_store,worker_contract,admit_job_pin,parse
    source=Path(__file__).resolve().parents[1];package=tmp_path/'pin.zip'
    prepare(package,make_inputs(duration=600,energy=80.),source,key='c'*32)
    store,intent=create_store(package,tmp_path/'pin-store',source);j,new=store.prepare_job(intent)
    c=worker_contract(store.directory,source);pin=admit_job_pin(store.directory,j['job_id'],c)
    assert pin['strategy']=='B60_SEALED_STATIC_V1'
    changed=dict(c,strategy='REFERENCE_B59')
    with pytest.raises(ValueError,match='STRATEGY_CONTRACT_DRIFT'):admit_job_pin(store.directory,j['job_id'],changed)
    # No dispatch or native migration: stripping both store files still leaves
    # the immutable job pin, so a new prepare cannot downgrade to reference.
    store.path('portable-execution.json').unlink();store.path('portable-job.json').unlink()
    with pytest.raises((ValueError,FileNotFoundError)):store.prepare_job(dict(intent,idempotency_key='d'*32))
    assert len(store.jobs())==1
    store.close_publications()


def test_dependencies_checked_without_install_or_model_launch(monkeypatch):
    import importlib.metadata
    from ops_sim.v5.portable_job import dependency_requirements
    source=Path(__file__).resolve().parents[1]
    def missing(name):raise importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(importlib.metadata,'version',missing)
    with pytest.raises(ValueError,match='DEPENDENCY_MISSING'):dependency_requirements(source)
    monkeypatch.setattr(importlib.metadata,'version',lambda name:'0.invalid')
    with pytest.raises(ValueError,match='DEPENDENCY_VERSION'):dependency_requirements(source)


@pytest.mark.parametrize('case',['limits_float','horizon_bool','requirements_minor_float'])
@pytest.mark.parametrize('entry',['package','stored_worker'])
def test_metadata_types_are_exact_at_both_admission_boundaries(tmp_path,case,entry):
    from examples.m8_battery_port import make_inputs
    from ops_sim.v5.portable_job import create_store,worker_contract
    source=Path(__file__).resolve().parents[1];package=tmp_path/'valid.zip'
    prepare(package,make_inputs(duration=600,energy=80.),source,key='e'*32)
    def alter(j):
        if case=='limits_float':j['limits']['rss_bytes']=float(j['limits']['rss_bytes'])
        elif case=='horizon_bool':j['horizon']['full_buckets']=False
        else:j['requirements']['python_major_minor'][0]=3.0
    if entry=='package':
        payload=read_bundle(package,JOB);j=json.loads(payload['job.json']);alter(j);payload['job.json']=canonical(j)
        bad=tmp_path/'malformed.zip';write_bundle(bad,JOB,payload)
        with pytest.raises(ValueError,match='B60_'):admit_job(bad,source)
    else:
        store,_=create_store(package,tmp_path/'store',source)
        try:
            p=store.path('portable-job.json');j=json.loads(p.read_bytes());alter(j);p.write_bytes(canonical(j))
            with pytest.raises(ValueError,match='B60_'):worker_contract(store.directory,source)
        finally:store.close_publications()


@pytest.mark.parametrize('case',['declared_count','directory_count_disagrees'])
def test_directory_admission_precedes_zipinfo_allocation(tmp_path,monkeypatch,case):
    import struct
    from ops_sim.v5.portable_job import MAX_MEMBERS
    p=tmp_path/'bad-directory.zip'
    if case=='declared_count':
        p.write_bytes(struct.pack('<4s4H2LH',b'PK\x05\x06',0,0,MAX_MEMBERS+2,MAX_MEMBERS+2,0,0,0))
    else:
        header=bytearray(46);header[:4]=b'PK\x01\x02';struct.pack_into('<H',header,28,1)
        directory=(bytes(header)+b'a')*3
        p.write_bytes(directory+struct.pack('<4s4H2LH',b'PK\x05\x06',0,0,2,2,len(directory),0,0))
    def forbidden(*a,**kw):raise AssertionError('ZipFile constructor must not be reached')
    monkeypatch.setattr(zipfile,'ZipFile',forbidden)
    with pytest.raises(ValueError,match='B60_'):read_bundle(p,JOB)


def test_metadata_payload_bound_precedes_any_member_read(tmp_path,monkeypatch):
    from hashlib import sha256
    from ops_sim.v5.portable_job import MAX_MANIFEST
    p=tmp_path/'oversized-metadata.zip';data=b' '*(MAX_MANIFEST+1)
    manifest=dict(format=JOB,files={'job.json':dict(bytes=len(data),sha256=sha256(data).hexdigest())})
    with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED)as z:
        z.writestr('MANIFEST.json',canonical(manifest));z.writestr('job.json',data)
    def forbidden(*a,**kw):raise AssertionError('No member may be read before header byte admission')
    monkeypatch.setattr(zipfile.ZipFile,'read',forbidden)
    with pytest.raises(ValueError,match='B60_'):read_bundle(p,JOB)
