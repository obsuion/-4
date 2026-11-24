"""V5 project derivation/front-door admission, without a numerical launch.

Only the lower paid compilation/reconstruction gate is replaced in wrapper
tests and its exact delegated bytes are checked. The real admitted native
metadata scope is retained. These cases do not claim actual materialization
or restart coverage; those require the connected pilots.
"""
from dataclasses import asdict, fields, replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from ops_sim.v5 import year_project as year
from ops_sim.v5.spacecraft_project import project_source_identity
from ops_sim.v5.spacecraft_project_document import loads_project, dumps_project
from ops_sim.v5.lifecycle_document import loads_root, dumps_root
from ops_sim.v5.lifecycle_quiet import is_short_circuit_policy
from ops_sim.v5.lifetime_policy import (
    LifetimeCampaignPolicyV2, METHOD_PACKED, QUALIFICATION,
)


@pytest.fixture(scope='module')
def authored():
    raw=(Path(__file__).parent/'fixtures/year_authored_A.project.json').read_bytes()
    assert sha256(raw).hexdigest()=='02d5b13ae67758901664353ddd09a2bd93d3f425e1b1868939b7513231cf216d'
    # Explicit initial DATA source rebinding, never an advanced checkpoint.
    return replace(loads_project(raw.decode('utf8')),source_identity=project_source_identity())


@pytest.fixture(scope='module')
def admitted_build():
    """The real source-matching receipt; these cases run after final build."""
    return (Path(__file__).parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes()


def packed():
    return LifetimeCampaignPolicyV2(method=METHOD_PACKED,mode=QUALIFICATION,
        maximum_primary_segments=8,reserved_diagnostic_slots=2,
        hard_seconds=240,soft_seconds=210,finalization_seconds=30,
        maximum_journal_records=1024)


@pytest.fixture
def world_gate(monkeypatch):
    seen=[]
    def check(root):
        seen.append(root)
        return {'static_test_only':True}
    monkeypatch.setattr(year,'_world',check)
    return seen


@pytest.mark.parametrize('duration',[600,year.DAY,year.YEAR])
def test_v5_changes_only_declared_duration_and_quiet_method(authored,world_gate,duration):
    old=dumps_project(authored)
    result=year.derive_project_v5(authored,duration)
    assert dumps_project(authored)==old
    assert result.specification is authored.specification
    assert result.common.start_seconds==authored.common.start_seconds==128
    assert result.common.duration_seconds==duration
    assert result.common.base is authored.common.base
    assert result.common.base.initial_checkpoint is authored.common.base.initial_checkpoint
    assert world_gate==[result.common]
    for f in fields(authored):
        if f.name!='common':assert getattr(result,f.name)==getattr(authored,f.name)
    for f in fields(authored.common):
        if f.name not in ('duration_seconds','policy','_identity'):
            assert getattr(result.common,f.name)==getattr(authored.common,f.name)
    assert result.common.identity!=authored.common.identity
    assert loads_root(dumps_root(result.common)).identity==result.common.identity
    assert result.identity!=authored.identity
    assert loads_project(dumps_project(result)).identity==result.identity
    for f in fields(authored.common.policy):
        if f.name!='quiet_solver':
            assert getattr(result.common.policy,f.name)==getattr(authored.common.policy,f.name)
    before=asdict(authored.common.policy.quiet_solver)
    after=asdict(result.common.policy.quiet_solver)
    assert before.pop('method')!=after.pop('method')
    assert before==after and is_short_circuit_policy(result.common.policy.quiet_solver)


def test_legacy_derivation_does_not_implicitly_upgrade_quiet_owner(authored,world_gate):
    result=year.derive_project(authored,year.DAY)
    assert result.common.policy is authored.common.policy
    assert not is_short_circuit_policy(result.common.policy.quiet_solver)


@pytest.mark.parametrize('duration',[True,0,-1,year.YEAR+1,600.0,'600'])
def test_v5_duration_rejection_precedes_world_gate(authored,world_gate,duration):
    with pytest.raises((TypeError,ValueError)):
        year.derive_project_v5(authored,duration)
    assert world_gate==[]


def test_v5_stale_authored_source_is_not_silently_rebound(authored,world_gate):
    stale=replace(authored,source_identity='0'*64)
    with pytest.raises(ValueError,match='source mismatch'):
        year.derive_project_v5(stale,600)
    assert world_gate==[]


@pytest.fixture
def frontdoor(monkeypatch,authored,world_gate,admitted_build):
    """Actual strict typed DATA frontend; fake paid lower gate is explicit."""
    compiled=[]
    def lower(project,duration,ledger,policy,build_bytes):
        compiled.append((project,duration,ledger,policy,build_bytes))
        doc=dumps_project(project)
        body=dict(format=year.FORMAT,version=1,project_document=doc,
            root_document='LOWER_COMPILED_ROOT_STUB_NO_PHYSICS',
            original_project_document=doc,
            original_project_sha256=sha256(doc.encode('utf8')).hexdigest(),
            project_identity=project.identity,root_identity='1'*64,
            source_identity=project.source_identity,duration_seconds=duration,
            world={'static_test_only':True},resource_plan={},horizon={},
            execution=dict(policy=asdict(policy),mode='STUB',backend='STUB',build=json.loads(build_bytes)),
            evidence={},qualification='PREPARED_ONLY_NO_YEAR_EXECUTION_OR_PHYSICAL_QUALIFICATION')
        return signed(body)
    monkeypatch.setattr(year,'_compile_job',lower)
    delegated=[];sentinel=object()
    def admit(raw,ledger):
        delegated.append((json.loads(raw),ledger))
        return sentinel
    monkeypatch.setattr(year,'_admit_job_legacy',admit)
    ledger=object()
    raw=year.compile_job_v5(authored,600,ledger,packed(),admitted_build)
    return raw,compiled,delegated,ledger,sentinel


def signed(body):
    body={k:v for k,v in body.items()if k!='digest'}
    return year.canonical(dict(body,digest=sha256(year.canonical(body)).hexdigest()))


def test_v5_compile_binds_authored_and_derived_data_separately(authored,frontdoor):
    raw,compiled,_,ledger,_=frontdoor
    data=json.loads(raw)
    assert data['format']==year.FORMAT_V5 and data['version']==2
    assert data['original_project_document']==dumps_project(authored)
    assert data['original_project_sha256']==sha256(dumps_project(authored).encode('utf8')).hexdigest()
    assert len(compiled)==1 and compiled[0][2]is ledger
    derived=compiled[0][0]
    assert is_short_circuit_policy(derived.common.policy.quiet_solver)
    assert data['project_document']==dumps_project(derived)
    numeric=asdict(authored.common.policy.quiet_solver);numeric.pop('method')
    assert data['derivation']==dict(method=year.DERIVATION_V5,
        original_quiet_method=authored.common.policy.quiet_solver.method,
        selected_quiet_method=derived.common.policy.quiet_solver.method,
        physical_parameter_sha256=sha256(year.canonical(numeric)).hexdigest())


def test_v5_admission_delegates_complete_independent_gate_without_state_upgrade(frontdoor):
    raw,_,delegated,ledger,sentinel=frontdoor
    assert year.admit_job(raw,ledger)is sentinel
    data=json.loads(raw);assert len(delegated)==1
    lower,owned=delegated[0]
    assert owned is ledger
    assert lower['format']==year.FORMAT and lower['version']==1
    assert 'derivation'not in lower
    assert lower['original_project_document']==data['project_document']
    assert lower['project_document']==data['project_document']
    assert lower['root_document']==data['root_document']
    assert lower['execution']==data['execution']
    assert lower['original_project_sha256']==sha256(data['project_document'].encode('utf8')).hexdigest()


@pytest.mark.parametrize('change',[
    'extra_field','wrong_version','duration_without_derivation',
    'declared_method','declared_old_method','numeric_parameter_digest',
    'derived_tolerance','legacy_storage_policy','original_digest',
])
def test_rehashed_v5_edits_rejected_before_paid_reconstruction(frontdoor,change):
    raw,compiled,delegated,ledger,_=frontdoor
    data=json.loads(raw)
    if change=='extra_field':data['not_declared']=0
    elif change=='wrong_version':data['version']=True
    elif change=='duration_without_derivation':data['duration_seconds']=601
    elif change=='declared_method':data['derivation']['selected_quiet_method']='UNKNOWN'
    elif change=='declared_old_method':data['derivation']['original_quiet_method']='UNKNOWN'
    elif change=='numeric_parameter_digest':data['derivation']['physical_parameter_sha256']='0'*64
    elif change=='derived_tolerance':
        p=compiled[0][0];q=replace(p.common.policy.quiet_solver,absolute_energy_wh=0.012345)
        data['project_document']=dumps_project(replace(p,common=replace(p.common,
            policy=replace(p.common.policy,quiet_solver=q))))
    elif change=='legacy_storage_policy':
        data['execution']['policy']=asdict(replace(packed(),method='B63_SERIAL_LIFETIME_STORE_POLICY_V2'))
    else:data['original_project_sha256']='0'*64
    with pytest.raises((TypeError,ValueError)):
        year.admit_job(signed(data),ledger)
    assert delegated==[]


def test_v5_noncannonical_bytes_rejected_before_paid_reconstruction(frontdoor):
    raw,_,delegated,ledger,_=frontdoor
    with pytest.raises(ValueError,match='canonical'):
        year.admit_job(json.dumps(json.loads(raw),indent=2).encode('utf8'),ledger)
    assert delegated==[]


def test_legacy_data_dispatch_does_not_opt_into_v5(frontdoor):
    _,_,delegated,ledger,sentinel=frontdoor
    raw=year.canonical({'format':year.FORMAT,'strict_lower_gate_fixture':True})
    assert year.admit_job(raw,ledger)is sentinel
    assert delegated==[(json.loads(raw),ledger)]


def test_old_storage_policy_refused_before_scope_or_compilation(monkeypatch,authored):
    def unexpected(*args,**kwargs):
        raise AssertionError('metadata/constructor gate must remain untouched')
    monkeypatch.setattr(year,'_compile_job',unexpected)
    with pytest.raises(ValueError,match='packed'):
        year.compile_job_v5(authored,600,object(),replace(packed(),method='B63_SERIAL_LIFETIME_STORE_POLICY_V2'),b'{}')
