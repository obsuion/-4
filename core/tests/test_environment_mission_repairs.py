from dataclasses import replace
from fractions import Fraction as Q
from math import pi
import pytest
from examples.m3_constructor_mission_demo import make_inputs
from ops_sim.v5.environment_mission import start_environment_mission,advance_environment_mission,RuntimeWork,MissionAction
from ops_sim.v5.environment_mission_document import mission_input_digest
from ops_sim.v5.environment_mission_continuation import save_continuation
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.state import OperationalMode,FDIRState


@pytest.fixture(scope='module')
def original():return start_environment_mission(make_inputs())


def fresh(s,inputs=None):
    d=s.inputs if inputs is None else inputs
    return replace(s,inputs=d,context=d.initial_checkpoint.restore(d.simulation_inputs),cursor=0,outcomes=(),acquisitions=(),
        attitude=replace(s.attitude),runtime_work=RuntimeWork(upstream_entries=1),input_digest=mission_input_digest(d))


def test_unsafe_idle_contact_atomic_and_spent(original):
    d=original.inputs;c=d.initial_checkpoint.restore(d.simulation_inputs)
    c.spacecraft_state.thermal.node_states[0].temperature_k=319.9999
    env=replace(d.environment,profile=(replace(d.environment.profile[1],start_seconds=Q(128)),))
    d=replace(d,initial_checkpoint=CheckpointState.from_context(c),environment=env,actions=(MissionAction('unsafe','CONTACT','station',2),))
    s=fresh(original,d);before=CheckpointState.from_context(s.context).to_dict()
    out=advance_environment_mission(s)
    assert out.outcomes[-1].reason=='CONTACT_EXISTING_PROTECTION_REFUSED'
    assert CheckpointState.from_context(out.context).to_dict()==before and out.attitude==s.attitude
    assert out.runtime_work.physical_completed_calls==4 and out.runtime_work.physical_reserved_calls==4
    assert not out.outcomes[-1].contact_outcomes and not out.context.ground_data_delivery_state.completed_deliveries


def test_ordinary_contact_preserves_idle_terminal_mode(original):
    s=fresh(original)
    for _ in range(4):s=advance_environment_mission(s)
    assert s.outcomes[-1].status=='completed'
    assert s.outcomes[-1].contact_outcomes[-1].operational_mode is OperationalMode.STANDBY
    assert s.context.spacecraft_state.onboard.operational_mode is OperationalMode.STANDBY
    assert s.context.spacecraft_state.onboard.fdir_state is FDIRState.NORMAL
    assert s.context.spacecraft_state.onboard.critical_energy_since_seconds is None


def test_denied_tx_counts_exact_returned_work_before_refusal(original):
    d=replace(original.inputs,transmitter=replace(original.inputs.transmitter,electrical_power_w=replace(original.inputs.transmitter.electrical_power_w,value=1e6)))
    s=fresh(original,d)
    for _ in range(3):s=advance_environment_mission(s)
    before=CheckpointState.from_context(s.context).to_dict();actual=s.runtime_work.physical_completed_calls;reserve=s.runtime_work.physical_reserved_calls
    out=advance_environment_mission(s)
    assert out.outcomes[-1].reason=='CONTACT_EXISTING_PROTECTION_REFUSED'
    assert out.runtime_work.physical_completed_calls-actual==9
    assert out.runtime_work.physical_reserved_calls-reserve==12
    assert CheckpointState.from_context(out.context).to_dict()==before
    assert not out.outcomes[-1].contact_outcomes


@pytest.mark.parametrize('mode,fdir,marker',[(OperationalMode.SAFE,FDIRState.NORMAL,None),
    (OperationalMode.STANDBY,FDIRState.BACKUP,None),(OperationalMode.SAFE,FDIRState.EMERGENCY_BEACON,None),
    (OperationalMode.EMERGENCY_BEACON,FDIRState.NORMAL,None),(OperationalMode.STANDBY,FDIRState.NORMAL,128)])
def test_initial_and_current_unsupported_regime_before_paid_work(original,mode,fdir,marker,tmp_path,monkeypatch):
    import ops_sim.v5.environment_mission as owner
    c=original.inputs.initial_checkpoint.restore(original.inputs.simulation_inputs)
    c.spacecraft_state.onboard.operational_mode=mode;c.spacecraft_state.onboard.fdir_state=fdir;c.spacecraft_state.onboard.critical_energy_since_seconds=marker
    monkeypatch.setattr(owner.light,'evaluate_zonotope_local_illumination_v2',lambda *a:pytest.fail('no upstream work for unsupported regime'))
    with pytest.raises(ValueError,match='REGIME'):
        replace(original.inputs,initial_checkpoint=CheckpointState.from_context(c))
    s=fresh(original);s.context=c
    with pytest.raises(ValueError,match='REGIME'):advance_environment_mission(s)
    with pytest.raises(ValueError,match='REGIME'):save_continuation(tmp_path/'packet.json',s)
    assert s.runtime_work.physical_completed_calls==0 and s.cursor==0

def test_unreturned_contact_work_unknown_not_zero_or_refunded(original,monkeypatch):
    import ops_sim.v5.environment_mission as m
    d=replace(original.inputs,environment=replace(original.inputs.environment,profile=(replace(original.inputs.environment.profile[1],start_seconds=Q(128)),)),actions=(MissionAction('exception','CONTACT','station',2),))
    s=fresh(original,d);before=CheckpointState.from_context(s.context).to_dict()
    def fail(*a,**k):raise RuntimeError('injected no returned work count')
    monkeypatch.setattr(m,'execute_contact_plan',fail)
    with pytest.raises(RuntimeError,match='injected'):advance_environment_mission(s)
    assert s.runtime_work.contact_work_unknown_events==1 and s.runtime_work.physical_reserved_calls==4
    assert s.runtime_work.physical_completed_calls==0 and CheckpointState.from_context(s.context).to_dict()==before