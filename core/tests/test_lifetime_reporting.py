from dataclasses import replace
from fractions import Fraction as Q
import pytest
from lifetime_support import root_for
from ops_sim.v5.environment_ageing import initial_state,propose,EnvironmentAgeingWork
from ops_sim.v5.lifetime_reporting import initial,advance,validate,rows

def test_selected_environment_bucket_handoff_and_constant_retention():
    root=root_for(600);root=replace(root,policy=replace(root.policy,month_period_seconds=120))
    net=root.base.model.simulation_inputs.spacecraft_configuration.thermal.network
    p=root.environment_ageing_policy;s=initial_state(p,128,net,1.);data=initial(root,s);work=EnvironmentAgeingWork()
    for n in range(4):
        after=propose(p,s,net,Q(128+120*n),Q(128+120*(n+1)),True,0.,work)
        data=advance(data,root,s,after);s=after
        assert len(data['rows'])==1 and data['sealed_count']==n+1
    assert data['rows'][0]['start_seconds']==488 and data['end_seconds']==608
    assert data['current']['end']['calendar_seconds']=='480'
    assert data['sealed_chain']!='0'*64
    with pytest.raises(ValueError,match='gap'):advance(data,root,initial_state(p,128,net,1.),s)
