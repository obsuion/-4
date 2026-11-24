from dataclasses import asdict,replace
import pytest
from ops_sim.v5.finite_campaign import *
from ops_sim.v5.lifecycle_runner_policy import requested_runner_policy,LifecycleRunnerStorePolicy,STORE_V1,STORE_V2,STORE_FIELDS,admit_runner_store_metadata

def test_named_strict_policy_and_prospective_not_average_reservation():
 p=FiniteCampaignPolicy();assert p.maximum_jobs==10 and p.maximum_primary_segments==8 and p.reserved_diagnostic_slots==2
 assert 10*128*2**20+33*2**20==1313*2**20<1536*2**20
 assert requested_runner_policy(METHOD)==p and LifecycleRunnerStorePolicy().maximum_jobs==8
 assert admit_policy(asdict(p))==p
 assert p.soft_seconds+p.finalization_seconds==p.hard_seconds

@pytest.mark.parametrize('name',list(FiniteCampaignPolicy.__dataclass_fields__))
def test_every_policy_field_is_immutable_named_value(name):
 p=FiniteCampaignPolicy();v=getattr(p,name)
 with pytest.raises((TypeError,ValueError)):replace(p,**{name:v+'x' if type(v)is str else v+1})
 if type(v)is int:
  with pytest.raises((TypeError,ValueError)):replace(p,**{name:float(v)})

def test_store_format_cannot_substitute_old_caps():
 p=FiniteCampaignPolicy();m={k:None for k in STORE_FIELDS};m.update(format=STORE,maximum_jobs=10,runner_policy=asdict(p),runner_policy_identity=p.identity)
 assert admit_runner_store_metadata(m)==(p,10,10,1536*2**20)
 for fmt in (STORE_V1,STORE_V2):
  bad=dict(m,format=fmt)
  with pytest.raises(ValueError):admit_runner_store_metadata(bad)


def test_reserved_roles_cannot_be_repurposed_even_when_slots_remain():
 from ops_sim.v5.battery_terminal import make_terminal,bind_terminal
 from ops_sim.v5.lifecycle_application import make_intent
 root='a'*64;cp={'sha256':'c'*64,'clock':190}
 parent={'job_id':'b'*32,'root_identity':root,'source_identity':'d'*64,'runtime':{'v':1},'intent':make_intent(root,key='1'*32),'resume':None}
 result=dict(checkpoint={'sha256':'e'*64},clock=200,actual_end_seconds=200,target_seconds=200,application_status='COMPLETED_WINDOW',status='COMPLETE',reason='BOUND_TARGET_REACHED')
 result['typed_terminal']=bind_terminal(make_terminal('TARGET',result['reason'],'END','OWNER',200),parent,result['checkpoint']);parent['result']=result
 diagnostic=make_intent(root,key='2'*32,parent_job_id=parent['job_id'],snapshot_sha256=cp['sha256'],mode='DIAGNOSTIC_VERBOSE',window_end_seconds=200)
 assert admit_role_population(diagnostic,parent,cp,[parent],200)=='DIAGNOSTIC'
 jobs=[parent]
 for i in (3,4):jobs.append(dict(job_id=f'{i:032x}',intent=dict(diagnostic,idempotency_key=f'{i:032x}'),resume=dict(checkpoint=cp),result=None))
 with pytest.raises(ValueError,match='two reserved'):admit_role_population(diagnostic,parent,cp,jobs,200)
 bad=dict(diagnostic,parent_job_id=None,snapshot_sha256=None)
 with pytest.raises(ValueError,match='predecessor'):intent_role(bad,None,None,200)
