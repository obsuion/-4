from copy import deepcopy
from types import SimpleNamespace
import pytest
from ops_sim.v5.battery_terminal import *

@pytest.mark.parametrize('code,kind',[
 ('BATTERY_PORT_DOMAIN_REFUSED:BATTERY_PORT_RETURNED_BALANCE','MODEL'),
 ('BATTERY_PORT_DOMAIN_REFUSED:BATTERY_PORT_DOMAIN:temperature','UNSUPPORTED'),
 ('UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY','UNSUPPORTED'),
 ('B55_POWER_SERVICE_INTERRUPTED:PARTIAL_RECEIVING_SERVICE','PHYSICAL'),
 ('OPERATING_TEMPERATURE_AT_ENDPOINT','PHYSICAL'),('unknown-code','MODEL')])
def test_actual_code_families_never_claim_validator_is_power_shortage(code,kind):
 t=physical_terminal(SimpleNamespace(status='refused',reason=code,kind='POINT'),132)
 assert t['kind']==kind and t['clock']==132 and not t['automatic_resume']

@pytest.mark.parametrize('kind',KINDS)
def test_strict_typed_wire_roundtrip_and_policy(kind):
 t=make_terminal(kind,'CODE','STAGE','OWNER',None if kind in ('UNKNOWN','PROCESS_FAILURE') else 128)
 assert admit_terminal(t)==t
 bad=deepcopy(t);bad['automatic_resume']=not bad['automatic_resume']
 with pytest.raises(ValueError):admit_terminal(bad)
 bad=deepcopy(t);bad['extra']=1
 with pytest.raises(ValueError):admit_terminal(bad)

@pytest.mark.parametrize('clock',[True,1.,-1,float('nan')])
def test_clock_is_exact_selected_integer(clock):
 with pytest.raises((ValueError,TypeError)):make_terminal('PHYSICAL','CODE','STAGE','OWNER',clock)

def test_bound_target_and_resource_cannot_be_forged():
 j=dict(job_id='a'*32,root_identity='b'*64,source_identity='c'*64,runtime={'v':1})
 cp=dict(sha256='d'*64)
 r=dict(checkpoint=cp,clock=138,actual_end_seconds=138,target_seconds=138,application_status='COMPLETED_WINDOW',status='COMPLETE',reason='BOUND_TARGET_REACHED')
 t=bind_terminal(make_terminal('TARGET',r['reason'],'END','OWNER',138),j,cp)
 assert admit_bound_terminal(t,j,r)['kind']=='TARGET'
 for path,value in [('clock',137),('target_seconds',139),('reason',None)]:
  bad=deepcopy(r);bad[path]=value
  with pytest.raises(ValueError):admit_bound_terminal(t,j,bad)
 r.update(status='ACTIVE',application_status='INCOMPLETE_BUDGET_STOP',target_seconds=200,reason='TIME')
 t=bind_terminal(make_terminal('RESOURCE_TIME','TIME','BOUNDARY','OWNER',138),j,cp)
 assert admit_bound_terminal(t,j,r)['automatic_resume']
 r['status']='INCOMPLETE_PENDING_PHYSICAL_REFUSAL'
 with pytest.raises(ValueError):admit_bound_terminal(t,j,r)


def test_native_boundary_binding_not_last_event_text():
 t=make_terminal('PHYSICAL','FULL_ELECTRICAL_SERVICE_UNAVAILABLE','ACTUAL_HOLD_UNTIL','lifecycle_physics',128)
 def tok(v):
  if v is None:return ['none']
  if type(v)is bool:return ['bool',v]
  if type(v)is int:return ['int',str(v)]
  return ['str',v]
 graph={'value':['ref',0],'nodes':[
  ['map',[[['str','state'],['ref',1]]]],
  ['map',[[['str','status'],['str','INCOMPLETE_NO_PROGRESS_HOLD_REFUSAL']],[['str','terminal'],['ref',2]]]],
  ['map',[[['str',k],tok(v)]for k,v in t.items()]]]}
 d=dict(graph=graph,bindings=dict(clock=128));r=dict(status='INCOMPLETE_NO_PROGRESS_HOLD_REFUSAL')
 assert admit_native_terminal(d,t,r)==t
 bad=deepcopy(t);bad['code']='FORGED_REASON'
 with pytest.raises(ValueError,match='disagreement'):admit_native_terminal(d,bad,r)


def test_model_boundary_at_target_is_not_successful_completion():
 j=dict(job_id='a'*32,root_identity='b'*64,source_identity='c'*64,runtime={'v':1})
 cp={'sha256':'d'*64};t=make_terminal('UNSUPPORTED','UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY','ACTUAL_POINT','lifecycle_physics',200)
 bound=bind_terminal(t,j,cp)
 r=dict(clock=200,actual_end_seconds=200,target_seconds=200,status='INCOMPLETE_TYPED_MODEL_BOUNDARY',reason=t['code'],checkpoint=cp,application_status='COMPLETED_WINDOW')
 with pytest.raises(ValueError,match='completed'):admit_bound_terminal(bound,j,r)
 r['application_status']='INCOMPLETE_MODEL_STATUS';assert admit_bound_terminal(bound,j,r)==t
