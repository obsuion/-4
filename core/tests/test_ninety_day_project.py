"""Finite 90D DATA/policy contracts; no scientific execution in these tests.

Delegation cases use explicit fake owner outputs, not trusted compiled roots.
The actual five-design compilation/store controls are separate paid gates.
"""
from dataclasses import asdict
from hashlib import sha256
import json

import pytest

from ops_sim.v5 import ninety_day_project as ninety
from ops_sim.v5 import year_project as year
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2, admit_policy, METHOD_PACKED, WINDOWS_USER


@pytest.mark.parametrize('name,primary', [('P64',64),('P96',96)])
def test_existing_policy_admission_and_exact_finite_identity(name,primary):
    p=ninety.policy_for(name)
    assert type(p)is LifetimeCampaignPolicyV2
    assert p.method==METHOD_PACKED and p.mode==WINDOWS_USER
    assert p.maximum_primary_segments==primary and p.reserved_diagnostic_slots==2
    assert (p.soft_seconds,p.hard_seconds,p.finalization_seconds,p.cleanup_seconds)==(840,900,60,2)
    assert p.maximum_observed_primary_seconds==primary*902
    assert p.maximum_diagnostic_seconds==1804
    assert (p.maximum_journal_records,p.maximum_journal_record_bytes)==(512,4096)
    assert asdict(admit_policy(asdict(p)))==asdict(p)
    assert p.identity==admit_policy(asdict(p)).identity
    assert p.identity!=ninety.policy_for('P96'if name=='P64'else'P64').identity


@pytest.mark.parametrize('bad',[None,True,64,96,64.0,'64','P63','p64','P64 ',[],{}])
def test_no_implicit_or_mutable_profile_selection(bad):
    with pytest.raises(ValueError):ninety.policy_for(bad)


@pytest.mark.parametrize('profile,jobs',[('P64',66),('P96',98)])
def test_capacity_keeps_distinct_real_owner_dimensions(profile,jobs):
    p=ninety.capacity_proposal(profile)
    assert p['scientific_jobs']==jobs
    assert p['physical_contract']['whole_study_commitment_bytes']==8053063680
    assert p['journal']['reserved_payload_bytes']==2**21
    assert p['journal']['minimum_policy_admission_records']==2*jobs+16
    assert p['namespace']['maximum_cumulative_file_names']==32768
    assert p['namespace']['maximum_owner_pages']==4096
    assert p['namespace']['all_jobs_at_full_file_grant']==jobs*512
    assert p['namespace']['all_full_file_grants_fit']is False
    assert p['per_job_packed']['maximum_objects']==65536
    assert p['per_job_packed']['maximum_blocks']==128
    assert p['per_job_packed']['maximum_index_bytes']==16*2**20
    assert p['readonly_export']['physical_public_operation_cap_bytes']==128*2**20
    assert p['readonly_export']['result_reader_hard_cap_bytes']==512*2**20
    assert p['unknown_producer_requires_halt']is True
    assert p['completion_proved']is False
    assert 'all three mutable names'in p['namespace']['normal_settlement']


def test_group_adds_five_full_commitments_and_explicit_shared_metadata():
    p=ninety.group_capacity_proposal(('P64','P96','P64','P64','P96'))
    assert p['whole_study_commitments_bytes']==5*8053063680
    assert p['shared_metadata_added_bytes']==2*128*16384+2*16384
    assert p['conservative_group_commitment_bytes']==40269545472
    assert p['completion_proved']is False


@pytest.mark.parametrize('bad',[None,'P64',[],['P64']*4,['P64']*6,['P64']*4+['BAD']])
def test_group_has_exact_five_explicit_profiles(bad):
    with pytest.raises(ValueError):ninety.group_capacity_proposal(bad)


def observation():
    # Synthetic DATA for arithmetic; not a measured model run.
    return dict(format=ninety.DAY_OBSERVATION,source_identity='1'*64,
        specification_identity='2'*64,root_identity='3'*64,evidence_sha256='4'*64,
        duration_seconds=86400,original_anchor_seconds=128,target_seconds=86528,
        parent_E2E_ns=300*10**9,worker_wall_ns=260*10**9,worker_CPU_ns=250*10**9,
        retained_file_data_bytes=6*2**20,cumulative_file_names=180,
        owner_database_pages=70,public_export_bytes=120000)


def test_day_estimate_is_rounded_up_and_explicitly_not_capacity_proof():
    old=observation();p=ninety.estimate_from_day('P64',old)
    assert p['stationary_primary_segments_at_soft840']==33
    assert p['twofold_wall_margin_primary_segments']==66
    assert p['estimate_with_twofold_margin_fits']is False
    assert ninety.estimate_from_day('P96',old)['estimate_with_twofold_margin_fits']is True
    assert p['stationary_owner_pages']==6300  # Exceeding a projected cap is visible.
    assert p['status']=='ESTIMATED_FROM_DAY_WITH_ENFORCED_HALT'
    assert p['completion_proved']is False and old==observation()


@pytest.mark.parametrize('key,value',[
    ('duration_seconds',86400.0),('original_anchor_seconds',128.0),
    ('worker_CPU_ns',False),('owner_database_pages',4097),
    ('cumulative_file_names',32769),('public_export_bytes',129*2**20),
    ('retained_file_data_bytes',2561*2**20),('evidence_sha256','X'*64),
    ('parent_E2E_ns',0),('worker_wall_ns',-1),
])
def test_invalid_day_data_cannot_become_a_capacity_estimate(key,value):
    d=observation();d[key]=value
    with pytest.raises(ValueError):ninety.estimate_from_day('P64',d)


def fake_inner(profile):
    # Intentionally incomplete lower-owner DATA. Only delegation is tested.
    return year.canonical(dict(format=year.FORMAT_V5,duration_seconds=ninety.DURATION,
        world=dict(start_seconds=128,end_seconds=ninety.TARGET),
        execution=dict(policy=asdict(ninety.policy_for(profile)))))


@pytest.fixture
def wrapped(monkeypatch):
    calls=[]
    def compile_(project,duration,ledger,policy,build):
        calls.append((project,duration,ledger,policy,build))
        return fake_inner('P64')
    monkeypatch.setattr(year,'compile_job_v5',compile_)
    project=object();ledger=object();build=b'FAKE_TEST_METADATA'
    raw=ninety.compile_job(project,'P64',ledger,build)
    assert calls==[(project,ninety.DURATION,ledger,ninety.policy_for('P64'),build)]
    return raw


def test_independent_admission_delegates_exact_embedded_owner_bytes(wrapped,monkeypatch):
    calls=[];ledger=object();answer=(object(),object(),object())
    monkeypatch.setattr(year,'admit_job',lambda raw,paid:(calls.append((raw,paid))or answer))
    assert ninety.admit_job(wrapped,ledger)is answer
    assert calls==[(fake_inner('P64'),ledger)]


def test_create_preserves_actual_returned_path_and_uses_one_existing_creation(wrapped,monkeypatch):
    calls=[];ledger=object()
    actual=dict(store='ACTUAL_OWNER_RETURNED_PATH',root_identity='1'*64,
        project_identity='2'*64,job_sha256='3'*64,plan_identity='4'*64,dispatch=False)
    def create(raw,projects,workspace,paid):
        calls.append((raw,projects,workspace,paid));return actual
    monkeypatch.setattr(year,'create_store',create)
    result=ninety.create_store(wrapped,'PROJECTS','WORKSPACE',ledger)
    assert calls==[(fake_inner('P64'),'PROJECTS','WORKSPACE',ledger)]
    assert result['store']==actual['store'] and result['dispatch']is False
    assert result['ninety_day_job_sha256']==sha256(wrapped).hexdigest()
    assert result['year_job_sha256']==sha256(fake_inner('P64')).hexdigest()


@pytest.mark.parametrize('change',[
    lambda d:d.update(profile='P96'),
    lambda d:d.update(duration_seconds=86400),
    lambda d:d['capacity']['namespace'].update(maximum_cumulative_file_names=999999),
    lambda d:d.update(year_job_sha256='0'*64),
])
def test_rehashed_envelope_tampering_fails_before_owner_admission(wrapped,monkeypatch,change):
    d=json.loads(wrapped);change(d);d.pop('digest');d['digest']=sha256(ninety.canonical(d)).hexdigest()
    monkeypatch.setattr(year,'admit_job',lambda *a:pytest.fail('must reject before owner'))
    with pytest.raises(ValueError):ninety.admit_job(ninety.canonical(d),object())


@pytest.mark.parametrize('resume',[False,True])
def test_execution_reuses_serial_supervisor_with_explicit_finite_argument(monkeypatch,resume):
    from ops_sim.v5 import lifetime_supervisor
    calls=[]
    monkeypatch.setattr(lifetime_supervisor,'run',lambda directory,**kw:(calls.append((directory,kw))or'ANSWER'))
    call=ninety.resume if resume else ninety.run
    assert call('EXISTING_STORE',maximum_segments=2)=='ANSWER'
    assert calls==[('EXISTING_STORE',dict(explicit_continue=resume,maximum_segments=2))]
    for bad in (None,True,0,97,2.0):
        with pytest.raises(ValueError):call('EXISTING_STORE',maximum_segments=bad)
    assert len(calls)==1
