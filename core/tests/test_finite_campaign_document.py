from dataclasses import asdict,replace
from types import SimpleNamespace
from copy import deepcopy
import pytest
from ops_sim.v5.finite_campaign import FiniteCampaignPolicy
from ops_sim.v5.finite_campaign_document import make_plan,admit_plan,digest
from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget

def store():
 return SimpleNamespace(runner_policy=FiniteCampaignPolicy(),maximum_jobs=10,maximum_reserved_job_output_bytes=1536*2**20,
  meta=dict(root_identity='a'*64,input_sha256='b'*64,source_identity='c'*64,runtime={'version':1}),
  root_input=SimpleNamespace(output_policy=None,policy=SimpleNamespace(max_task_output_bytes=128*2**20)))
def test_eight_primary_two_late_plan_and_no_legacy_substitution():
 s=store();p=make_plan(s,chain_id='d'*32,execution_budget=ExecutionBudget(1550,1250,300),maximum_observed_seconds=10800)
 assert p['maximum_primary_segments']==8 and p['reserved_diagnostic_slots']==2 and admit_plan(p,s)==p
 s.runner_policy=None
 with pytest.raises(ValueError):admit_plan(p,s)
@pytest.mark.parametrize('key,value',[('maximum_primary_segments',9),('maximum_observed_seconds',10801),('reserved_diagnostic_slots',1),('maximum_output_bytes',129*2**20)])
def test_cannot_raise_caps_even_with_rehashed_wire(key,value):
 s=store();p=make_plan(s,chain_id='d'*32,execution_budget=ExecutionBudget(1550,1250,300))
 p[key]=value;p['plan_identity']=digest({k:v for k,v in p.items() if k!='plan_identity'})
 with pytest.raises(ValueError):admit_plan(p,s)
