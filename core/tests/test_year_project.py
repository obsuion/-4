"""Original-anchor long input contract; no mission execution in these tests."""
from dataclasses import replace
from pathlib import Path
from hashlib import sha256
import json
import pytest
from ops_sim.v5.year_project import (derive_project,compile_job,admit_job,canonical,_world,DAY,YEAR)
from ops_sim.v5.spacecraft_project_document import loads_project,dumps_project
from ops_sim.v5.spacecraft_project import project_source_identity
from ops_sim.v5.design_repair import ConstructorLedger
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,QUALIFICATION,WINDOWS_USER,windows_policy
from ops_sim.v5.general_project_job import GeneralProjectExecution,dumps_named_project,loads_named_project
from ops_sim.v5.lifetime_execution_authority import USER_LONG

@pytest.fixture(scope='module')
def project():
    raw=(Path(__file__).parent/'fixtures/year_authored_A.project.json').read_bytes()
    assert sha256(raw).hexdigest()=='02d5b13ae67758901664353ddd09a2bd93d3f425e1b1868939b7513231cf216d'
    # Explicit source upgrade of imported initial DATA, never checkpoint retagging.
    return replace(loads_project(raw.decode('utf8')),source_identity=project_source_identity())

@pytest.fixture(scope='module')
def build():
    return (Path(__file__).parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes()

def policy(long=False):
    return LifetimeCampaignPolicyV2(mode=WINDOWS_USER if long else QUALIFICATION,
        maximum_primary_segments=128 if long else 8,reserved_diagnostic_slots=2,
        hard_seconds=900 if long else 240,soft_seconds=840 if long else 210,
        finalization_seconds=60 if long else 30,maximum_journal_records=1024)

@pytest.mark.parametrize('duration',[600,DAY,YEAR])
def test_original_anchor_full_world_not_table_extension(project,duration):
    p=derive_project(project,duration)
    assert p.common.start_seconds==project.common.start_seconds==128
    assert p.common.end_seconds==128+duration
    assert p.specification is project.specification
    assert p.common.base is project.common.base
    assert p.common.policy is project.common.policy
    assert p.common.environment_ageing_policy is project.common.environment_ageing_policy
    world=_world(p.common)
    assert world['sun_table_used']is False
    assert world['sun']['period_seconds']==31557600.0
    assert world['end_seconds']==128+duration
    assert p.common.base.initial_checkpoint is project.common.base.initial_checkpoint

@pytest.mark.parametrize('duration',[True,0,-1,1,YEAR+1,1.0,'86400'])
def test_duration_strict_admission(project,duration):
    with pytest.raises((TypeError,ValueError)):derive_project(project,duration)

def test_short_table_not_promoted(project):
    table=replace(project,common=replace(project.common,sun_mode='BOUND_SHORT_TABLE_V1'))
    with pytest.raises(ValueError):derive_project(table,DAY)

def test_source_upgrade_is_explicit(project):
    with pytest.raises(ValueError,match='source mismatch'):
        derive_project(replace(project,source_identity='0'*64),DAY)

def test_year_job_paid_codec_reconstruction(project,build):
    ledger=ConstructorLedger();raw=compile_job(project,YEAR,ledger,policy(True),build)
    assert ledger.compiles==2
    second=ConstructorLedger();p,root,execution=admit_job(raw,second)
    assert second.compiles==2 and root.duration_seconds==YEAR and root.start_seconds==128
    assert p.common.duration_seconds==YEAR and execution.execution_mode==USER_LONG
    assert execution.policy.mode==WINDOWS_USER
    d=json.loads(raw);assert not d['resource_plan']['quota_completion_proof']
    assert root.base.initial_checkpoint.simulation_time_seconds==128
    envelope=dumps_named_project(p,execution)
    q,e=loads_named_project(envelope)
    assert dumps_project(q)==dumps_project(p) and e==execution

@pytest.mark.parametrize('long',[False,True])
def test_finite_mode_is_not_linux_acceptance(long):
    p=policy(long);assert windows_policy(p)
    assert p.mode!='LINUX_PRODUCTION'
    if long:assert p.maximum_jobs==130

def test_old_qualification_limits_preserved():
    with pytest.raises(ValueError):replace(policy(False),maximum_primary_segments=9)
    with pytest.raises(ValueError):replace(policy(False),hard_seconds=900,soft_seconds=870)

def test_long_requires_distinct_permission(build):
    with pytest.raises(ValueError):GeneralProjectExecution(policy(True),build)
    with pytest.raises(ValueError):GeneralProjectExecution(policy(False),build,execution_mode=USER_LONG)

@pytest.mark.parametrize('count',[True,0,-1,1025,1.0])
def test_bounded_supervisor_invocation_before_side_effects(count):
    from ops_sim.v5.lifetime_supervisor import run
    with pytest.raises(ValueError,match='segment count'):run('DOES_NOT_EXIST',maximum_segments=count)


def test_world_binding_is_valid_inside_existing_fast_strategy(project):
    from ops_sim.v5.lifecycle_fast import execution_strategy,FAST
    with execution_strategy(FAST,'1'*64):
        p=derive_project(project,DAY)
        assert _world(p.common)['end_seconds']==86528

def test_legacy_policy_cannot_acquire_new_user_permission():
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicy
    with pytest.raises(ValueError):LifetimeCampaignPolicy(mode=WINDOWS_USER)
