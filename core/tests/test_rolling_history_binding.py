"""Real first-command history mutations reject before physics or publication."""
from dataclasses import replace
from copy import deepcopy
import pytest
from examples.m5_rolling_mission_demo import make_inputs
from ops_sim.v5.rolling_execution import start_rolling, step_rolling, guard_rolling
from ops_sim.v5.rolling_document import save_continuation


@pytest.fixture(scope='module')
def point_state():
    state=step_rolling(start_rolling(make_inputs()))
    assert state.physical.context.simulation_time_seconds==136
    assert state.physical.commands[0].kind=='POINT'
    return state


@pytest.mark.parametrize('field',['explanation','suffix','rejection','age','prediction','trial-outcome','work','context','root','command'])
def test_real_first_command_mutation_rejects_before_save_and_next_work(point_state,field,tmp_path,monkeypatch):
    s=deepcopy(point_state);d=s.decisions[0]
    if field=='explanation':d=replace(d,explanation='unrelated caller text')
    if field=='suffix':d=replace(d,selected_suffix=(replace(d.selected_suffix[0],point_id='station'),*d.selected_suffix[1:]))
    if field=='rejection':d=replace(d,rejected=(*d.rejected,('caller','forged')))
    if field=='age':d=replace(d,knowledge_age_seconds=d.knowledge_age_seconds+1)
    if field=='prediction':
        tag,f=d.forecasts[0];f=replace(f,predicted_energy_wh=f.predicted_energy_wh+1)
        d=replace(d,forecasts=((tag,f),*d.forecasts[1:]))
    if field=='work':d.forecasts[0][1].runtime_work['physical_completed_calls']+=1
    if field=='trial-outcome':
        tag,f=d.forecasts[0];o=f.predicted_outcomes[0]
        f=replace(f,predicted_outcomes=(replace(o,reason='forged trial reason'),*f.predicted_outcomes[1:]))
        d=replace(d,forecasts=((tag,f),*d.forecasts[1:]))
    if field=='context':s.physical.context.spacecraft_state.battery.energy_wh-=1
    if field=='root':s.root=replace(s.root,contacts=s.root.contacts[:-1])
    if field=='command':s.physical.commands=(replace(s.physical.commands[0],point_id='station'),)
    s.decisions=(d,)
    import ops_sim.v5.rolling_execution as execution
    def forbidden(*a,**k):raise AssertionError('model execution after changed history')
    monkeypatch.setattr(execution,'advance_physical',forbidden)
    before=s.work.output_bytes
    for call in (lambda:guard_rolling(s),lambda:save_continuation(tmp_path/'bad.json',s),lambda:step_rolling(s)):
        with pytest.raises(ValueError,match='MUTATED|MISMATCH|broken'):call()
    assert s.work.output_bytes==before and not (tmp_path/'bad.json').exists()


def test_legitimate_paid_output_does_not_invalidate_history(point_state):
    from ops_sim.v5.rolling_execution import paid_scientific_bytes
    s=deepcopy(point_state);before=s.work.control_reserved
    paid_scientific_bytes(s);guard_rolling(s)
    assert s.work.control_reserved>before


def test_first_action_semantics_survives_action_id_replacement(point_state):
    s=deepcopy(point_state);d=s.decisions[0];a=s.physical.commands[0]
    assert d.selected_suffix[0].action_id!=a.action_id
    assert replace(d.selected_suffix[0],action_id=a.action_id)==a
    assert s.command_lineage[0].decision_payload_identity
    guard_rolling(s)
