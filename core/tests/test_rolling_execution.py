"""Transactional actual actions, adaptive lineage and old defaults unchanged."""
from dataclasses import replace
import pytest
from examples.m5_rolling_mission_demo import make_inputs
from ops_sim.v5.rolling_execution import start_rolling,step_rolling,guard_rolling
from ops_sim.v5.rolling_physics import advance_physical
from ops_sim.v5.long_mission import LongMissionAction as Action


def test_refusal_preserves_actual_context_and_retains_work():
    state=start_rolling(make_inputs());p=state.physical
    initial=p.context.simulation_time_seconds;energy=p.context.spacecraft_state.battery.energy_wh
    refused=advance_physical(p,Action('bad-held-image','CAPTURE','target',4,product_id='b47-medium'))
    assert refused.outcomes[-1].status=='refused'
    assert refused.context.simulation_time_seconds==initial and refused.context.spacecraft_state.battery.energy_wh==energy
    assert not refused.context.spacecraft_state.data_storage.stored_records
    assert refused.cursor==1 and refused.harness.work.compilation_calls>1


def test_mutated_boundary_rejects():
    state=start_rolling(make_inputs());state.physical.context.spacecraft_state.battery.energy_wh-=1
    with pytest.raises(ValueError,match='MUTATED'): guard_rolling(state)


def test_fair_assemblies_rebind_routes_and_effective_tensor():
    a,b=make_inputs('compact'),make_inputs('outboard')
    assert a.policy==b.policy and a.requests==b.requests and a.contacts==b.contacts and a.knowledge_mode==b.knowledge_mode
    assert a.model.environment==b.model.environment and a.model.actuator==b.model.actuator
    assert a.model.configuration.assembly_digest!=b.model.configuration.assembly_digest
    x,y=start_rolling(a),start_rolling(b)
    assert x.physical.harness.hardware.tensor_exact!=y.physical.harness.hardware.tensor_exact
    assert x.physical.construction.compilation.configuration_digest!=y.physical.construction.compilation.configuration_digest
