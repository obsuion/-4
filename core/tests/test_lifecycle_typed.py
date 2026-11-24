"""B64 genuine typed storage, exact coupled results and retained work."""
from copy import deepcopy
from dataclasses import asdict,replace
from fractions import Fraction as Q
from importlib.machinery import ExtensionFileLoader
import json
import pytest

from ops_sim.v5 import _lifecycle_typed as typed
from ops_sim.v5.battery_port import BatteryPortPolicy,BatteryPortDomainError
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.construction_service import service_physical_substep,ConstructionServiceDomainRefusal
from ops_sim.v5.integration_time import RationalSeconds
from ops_sim.v5.lifecycle_typed_state import prepare_typed_static,service_port_substep
from ops_sim.v5.long_mission_continuation import _scientific
from test_battery_port_coupling import leaf


def encoded(value):
    return json.dumps(_scientific(value),sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def prepared(s,kw):
    return prepare_typed_static(s.context.inputs.spacecraft_configuration,kw['compilation'],kw['service_policy'],
        kw['battery_port_policy'],s.inputs.protection,s.inputs.routing,kw['limits'],module=typed)


def test_real_binary64_owner_and_explicit_closed_quiet_capability():
    assert isinstance(typed.__loader__,ExtensionFileLoader)
    cap=typed.typed_capability()
    assert cap['typed_contiguous_numeric_state'] is True and cap['full_coupled']is True
    assert cap['quiet_interval_callback_free']is True
    assert cap['python_model_callbacks']is False and cap['python_model_callbacks_scope']=='COUPLED_CUT_AND_CLOSED_WORLD_QUIET_ONLY'
    assert cap['changes_scientific_work']is False and cap['speedup']=='UNPROVEN'
    assert cap['limits']==dict(nodes=64,links=256,branches=8,loads=7)
    assert all(cap['capability_screen'].values())
    before=typed.native_entry_counts();after=typed.native_entry_counts()
    assert before==after and before['reset_available']is False
    assert sum(before['counts'].values())==before['total']
    before['counts']['allocation_trial']+=999
    assert typed.native_entry_counts()==after


@pytest.mark.parametrize('mode',['NORMAL','SAFE','POWER_OFF','RECOVERY'])
@pytest.mark.parametrize('sunlit',[False,True])
def test_complete_coupled_science_state_and_distinct_exact_work(mode,sunlit):
    expected=[]
    for function in (service_physical_substep,service_port_substep):
        s,f,e,origin,port,allocation,kw=leaf(sunlit=sunlit,mode=mode)
        if function is service_port_substep:kw['compiled_static']=prepared(s,kw)
        result=function(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,**kw)
        expected.append(encoded((result,CheckpointState.from_context(s.context),asdict(port),asdict(allocation),asdict(s.construction.work))))
    assert expected[0]==expected[1]


@pytest.mark.parametrize('energy,current',[(80.,.001),(0.,8.),(.000001,8.),(80.,.12)])
def test_allocation_rejections_and_priority_bisection_remain_paid(energy,current):
    policy=replace(BatteryPortPolicy(),maximum_discharge_current_a=current)
    outputs=[]
    before=typed.native_entry_counts()
    for function in (service_physical_substep,service_port_substep):
        s,f,e,origin,port,allocation,kw=leaf(policy,energy=energy)
        if function is service_port_substep:kw['compiled_static']=prepared(s,kw)
        result=function(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,**kw)
        outputs.append(encoded((result,CheckpointState.from_context(s.context),asdict(port),asdict(allocation),asdict(s.construction.work))))
    after=typed.native_entry_counts()
    assert outputs[0]==outputs[1]
    assert after['counts']['allocation_trial']>before['counts']['allocation_trial']
    assert after['counts']['electrical_line']>before['counts']['electrical_line']
    assert after['counts']['thermal_transition']==before['counts']['thermal_transition']+1


def test_fraction_duration_and_port_measurement_support_not_binary64_clock():
    values=[]
    for function in (service_physical_substep,service_port_substep):
        s,f,e,origin,port,allocation,kw=leaf()
        kw['end_seconds']=Q(130)+Q(1,3)
        if function is service_port_substep:kw['compiled_static']=prepared(s,kw)
        result=function(s.context,RationalSeconds(1,3),f,e,s.inputs.protection,None,**kw)
        assert result[0].port_state_after.clock_seconds==Q(391,3)
        values.append(encoded((result,asdict(port),asdict(allocation),asdict(s.construction.work))))
    assert values[0]==values[1]


@pytest.mark.parametrize('kind',['port_ageing','moving_power'])
def test_late_failure_is_atomic_and_attempt_ledgers_match(kind):
    policy=(replace(BatteryPortPolicy(),initial_resistance_damage=64.,calendar_damage_per_second=1.)
            if kind=='port_ageing' else replace(BatteryPortPolicy(),maximum_discharge_current_a=.001))
    outputs=[]
    for function in (service_physical_substep,service_port_substep):
        s,f,e,origin,port,allocation,kw=leaf(policy)
        if kind=='moving_power':kw['internal_heat_adjustments_w']=((s.context.inputs.spacecraft_configuration.thermal.network.bus_node_id,-.001),)
        if function is service_port_substep:kw['compiled_static']=prepared(s,kw)
        before=encoded(CheckpointState.from_context(s.context))
        with pytest.raises((BatteryPortDomainError,ConstructionServiceDomainRefusal)) as caught:
            function(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,**kw)
        assert encoded(CheckpointState.from_context(s.context))==before
        outputs.append((type(caught.value),str(caught.value),encoded(getattr(caught.value,'diagnostic',None)),
                        asdict(port),asdict(allocation),asdict(s.construction.work)))
    assert outputs[0]==outputs[1]


@pytest.mark.parametrize('boundary',('selected_steps','weighted_seconds'))
def test_port_history_boundary_refusal_retains_original_ageing_accounting(boundary):
    outputs=[]
    for function in (service_physical_substep,service_port_substep):
        s,f,e,origin,port,allocation,kw=leaf()
        history=replace(origin,selected_steps=2**40 if boundary=='selected_steps' else 1,
            temperature_weighted_seconds=1.e12 if boundary=='weighted_seconds' else 0.,
            last_voltage_v=8.,last_current_a=0.,last_resistance_ohm=.1,last_ocv_v=8.,last_support_start_seconds=Q(129))
        kw['battery_port_state']=history
        if function is service_port_substep:kw['compiled_static']=prepared(s,kw)
        before=encoded(CheckpointState.from_context(s.context))
        with pytest.raises(BatteryPortDomainError)as caught:
            function(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,**kw)
        assert encoded(CheckpointState.from_context(s.context))==before
        outputs.append((str(caught.value),asdict(port),asdict(allocation),asdict(s.construction.work)))
    assert outputs[0]==outputs[1]


def test_independent_dynamic_arrays_and_no_exposed_buffer_alias():
    s,f,e,origin,port,allocation,kw=leaf()
    static=prepared(s,kw)
    from ops_sim.v5.lifecycle_typed_state import _dynamic
    a=_dynamic(static,s.context,origin);b=_dynamic(static,s.context,origin)
    first=a.snapshot();second=b.snapshot()
    assert first==second and first is not second
    first['energy']=-999
    s.context.spacecraft_state.battery.energy_wh-=1
    assert a.snapshot()==b.snapshot()==second
    assert not hasattr(a,'energy') and not hasattr(a,'t') and not hasattr(static.compiled,'capacity')


def test_integer_temperature_refuses_declared_typed_domain_before_work():
    s,f,e,origin,port,allocation,kw=leaf()
    static=prepared(s,kw)
    s.context.spacecraft_state.thermal.node_states[0].temperature_k=300
    before=(asdict(port),asdict(allocation),asdict(s.construction.work),typed.native_entry_counts())
    with pytest.raises(ValueError,match='binary64 temperature state'):
        service_port_substep(s.context,RationalSeconds(1,1),f,e,s.inputs.protection,None,compiled_static=static,**kw)
    assert (asdict(port),asdict(allocation),asdict(s.construction.work),typed.native_entry_counts())==before
