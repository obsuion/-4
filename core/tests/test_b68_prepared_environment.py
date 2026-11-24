"""Static identity reuse keeps exact dynamic guards and the public law."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
import pytest
from test_lifecycle_job_prepared import raw,job,history
from ops_sim.v5 import environment_ageing as ageing
from ops_sim.v5.lifecycle_job_prepared import PreparedRoleState

def test_prepared_history_guard_requires_owned_live_aliases(job):
    role=job.actual;h=history(role)
    with pytest.raises(ValueError):role.guard_environment_history(role._external_policy,h,role._external_baseline)
    with job.transaction():
        role.guard_environment_history(role._external_policy,h,role._external_baseline,h.clock_seconds)
        for policy,baseline,state,clock in ((deepcopy(role._external_policy),role._external_baseline,h,h.clock_seconds),
                (role._external_policy,deepcopy(role._external_baseline),h,h.clock_seconds),
                (role._external_policy,role._external_baseline,h,h.clock_seconds+1),
                (role._external_policy,role._external_baseline,replace(h,policy_identity='f'*64),h.clock_seconds)):
            with pytest.raises(ValueError):role.guard_environment_history(policy,state,baseline,clock)

def test_one_policy_identity_and_exact_reference_proposal_work(job):
    role=job.actual;h=history(role);p=role._external_policy;b=role._external_baseline
    assert job.static.environment_policy_identity==p.identity
    refwork=ageing.EnvironmentAgeingWork();work=ageing.EnvironmentAgeingWork()
    expected=ageing.propose(p,h,b,h.clock_seconds,h.clock_seconds+Q(1,4),True,30.,refwork)
    with job.transaction():
        actual=ageing.propose(p,h,b,h.clock_seconds,h.clock_seconds+Q(1,4),True,30.,work,prepared_runtime=role)
        assert actual==expected
        assert work==refwork
        assert role.effective_environment(p,actual,b).policy_identity==job.static.environment_policy_identity
        assert job.forecast._cache is not role._cache

@pytest.mark.parametrize('target',['property','digest','guard','propose','leaf','role-helper','cut-helper'])
def test_changed_helpers_and_property_refuse_atomic_publication(job,target):
    from ops_sim.v5 import environment_lifecycle as life
    role=job.actual;h=history(role);published=[]
    table={'property':(ageing.EnvironmentAgeingPolicy,'identity',property(lambda self:'f'*64)),
        'digest':(ageing,'digest',lambda x:'f'*64),'guard':(ageing,'guard',lambda *a,**k:None),
        'propose':(ageing,'propose',lambda *a,**k:None),'leaf':(ageing,'_propose_validated',lambda *a,**k:None),
        'role-helper':(PreparedRoleState,'guard_environment_history',lambda *a,**k:None),
        'cut-helper':(life,'_guard_history',lambda *a,**k:None)}
    owner,key,replacement=table[target];original=getattr(owner,key)
    try:
        with pytest.raises(ValueError):
            with job.transaction():
                setattr(owner,key,replacement)
                role.effective_environment(role._external_policy,h,role._external_baseline)
            published.append(True)
        assert not published and job._active is None
    finally:setattr(owner,key,original)

def test_cached_scalar_mutation_refuses_before_realization(job):
    role=job.actual;h=history(role);before=job.static.environment_policy_identity
    try:
        with pytest.raises(ValueError):
            with job.transaction():
                object.__setattr__(job.static,'environment_policy_identity','f'*64)
                role.guard_environment_history(role._external_policy,h,role._external_baseline)
    finally:object.__setattr__(job.static,'environment_policy_identity',before)
