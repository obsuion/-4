from dataclasses import asdict
import json,pytest
from lifetime_support import SOURCE,RAW
from kit import serverctl as ctl
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicy

@pytest.mark.parametrize('value',['NaN','Infinity','-1','0'])
def test_nonfinite_cost_or_time_is_refused(value):
    with pytest.raises(ValueError):ctl.decimal(value,'budget')

def test_actual_plan_owner_roundtrip_source_binding_and_foreign_store(tmp_path):
    original=tmp_path/'v7.json';original.write_bytes(b'\xef\xbb\xbf'+RAW)
    path=tmp_path/'server-plan.json';p=ctl.make_plan(SOURCE,original,path,seconds=473364000,policy=asdict(LifetimeCampaignPolicy()),rate='.0625',currency='USD',max_cost='1000',mode='long')
    assert ctl.load_plan(path,SOURCE)==p
    assert p['duration_derivation']['full_30day_buckets']==182
    assert p['accounting_derivation']['physical_fields']=='UNCHANGED'
    with pytest.raises((OSError,ValueError)):ctl.bound_store(path,p,SOURCE)
    d=json.loads((tmp_path/p['input_file']).read_bytes());d['inputs']['duration_seconds']=900
    (tmp_path/p['input_file']).write_bytes(ctl.canonical(d))
    with pytest.raises(ValueError,match='raw drift'):ctl.load_plan(path,SOURCE)

def test_doctor_never_invents_linux_or_launches():
    import sys
    d=ctl.doctor(SOURCE)
    assert d['science_executed']is False
    if sys.platform=='win32':assert not d['checks']['linux']and not d['ready_for_engine_attempt']


def test_legacy_long_refused_before_doctor_or_lease_or_preparation(monkeypatch,tmp_path):
    from types import SimpleNamespace
    calls=[]
    supervisor=SimpleNamespace(prepare=lambda *a,**k:calls.append('prepare'))
    monkeypatch.setattr(ctl,'owners',lambda engine:supervisor)
    monkeypatch.setattr(ctl,'load_plan',lambda *a:dict(format=ctl.FORMAT,policy=asdict(LifetimeCampaignPolicy()),duration_seconds=473364000))
    def forbidden(*args,**kwargs):raise AssertionError('doctor reached before common long refusal')
    monkeypatch.setattr(ctl,'doctor',forbidden)
    with pytest.raises(ValueError,match='no qualified long'):ctl.run_plan(tmp_path/'old-plan.json',SOURCE)
    assert calls==[]


def test_v2_plan_authority_refusal_leaves_no_derived_files(monkeypatch,tmp_path):
    from dataclasses import replace
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,QUALIFICATION
    from ops_sim.v5 import lifetime_execution_authority as authority,lifetime_portable
    original=tmp_path/'input.json';original.write_bytes(RAW)
    p=replace(LifetimeCampaignPolicyV2(),mode=QUALIFICATION,maximum_primary_segments=8,reserved_diagnostic_slots=2,hard_seconds=240,soft_seconds=210,finalization_seconds=30)
    monkeypatch.setattr(lifetime_portable,'execution_contract_v2',lambda *a,**k:{'not':'a permission'})
    def refuse(*args,**kwargs):raise ValueError('expected genuine authority refusal')
    monkeypatch.setattr(authority,'make_authority',refuse)
    path=tmp_path/'prepared-plan.json'
    with pytest.raises(ValueError,match='genuine authority refusal'):
        ctl.make_plan(SOURCE,original,path,seconds=7200,policy=asdict(p),rate='.0625',currency='USD',max_cost='1000',backend='PREPARED_PYTHON')
    assert sorted(x.name for x in tmp_path.iterdir())==['input.json']


def test_v2_bounded_plan_roundtrip_uses_strict_backend_authority(tmp_path):
    from dataclasses import replace
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,QUALIFICATION
    original=tmp_path/'input.json';original.write_bytes(RAW)
    p=replace(LifetimeCampaignPolicyV2(),mode=QUALIFICATION,maximum_primary_segments=8,reserved_diagnostic_slots=2,hard_seconds=240,soft_seconds=210,finalization_seconds=30)
    path=tmp_path/'prepared-plan.json'
    value=ctl.make_plan(SOURCE,original,path,seconds=7200,policy=asdict(p),rate='.0625',currency='USD',max_cost='1000',backend='PREPARED_PYTHON')
    assert value['format']==ctl.FORMAT_V2 and value['backend']=='PREPARED_PYTHON'
    assert value['execution_authority']['mode']=='PILOT' and value['native_build']is None
    assert ctl.load_plan(path,SOURCE)==value
