from copy import deepcopy
import pytest
from ops_sim.v5.project_intents import make_intent,validate_intent,intent_identity,DIRECT

def test_exact_durable_content_and_method():
    a=make_intent('1'*32,'2'*64,'3'*32,parent='4'*32,snapshot_sha='5'*64,method=DIRECT,window_end=728)
    assert validate_intent(deepcopy(a))==a and intent_identity(deepcopy(a))==intent_identity(a)
    for key,value in [('revision','6'*64),('parent_job_id','7'*32),('snapshot_sha256','8'*64),('mode','DIAGNOSTIC_VERBOSE')]:
        b=dict(a,**{key:value});assert intent_identity(b)!=intent_identity(a)

@pytest.mark.parametrize('field,value',[('action_id',True),('window_end_seconds',True),('window_end_seconds',729),('method','free-form'),('snapshot_sha256','../state')])
def test_intent_strict_inputs(field,value):
    a=make_intent('1'*32,'2'*64,'3'*32,parent='4'*32,snapshot_sha='5'*64,method=DIRECT,window_end=728)
    a[field]=value
    with pytest.raises((ValueError,TypeError)):validate_intent(a)
