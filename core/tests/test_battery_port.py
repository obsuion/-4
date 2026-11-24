"""Independent equation/Decimal references for the declared reduced pack."""
from dataclasses import asdict, replace
from decimal import Decimal, localcontext
from fractions import Fraction as Q
from math import isclose, ulp
import pytest
from ops_sim.v5.battery_port import (BatteryPortPolicy, BatteryPortState,
    BatteryPortWork, BatteryPortDomainError, solve_port, battery_port_transition,
    advance_port_state, ocv_resistance)
from ops_sim.v5.integration_time import RationalSeconds


def reference_policy(**kwargs):
    return replace(BatteryPortPolicy(), ocv_curve=((0.,20.),(1.,20.)),
        minimum_terminal_voltage_v=10.,maximum_terminal_voltage_v=40.,
        ocv_temperature_v_per_k=0.,resistance_reference_ohm=1.,
        resistance_temperature_per_k=0.,resistance_low_soc_factor=0.,**kwargs)


def transition(policy=None, **kwargs):
    data=dict(energy_wh=100.,usable_wh=200.,temperature_k=298.15,
        generation_w=0.,load_w=20.,duration=RationalSeconds.from_fraction(Q(60)),
        charge_bus_limit_w=1000.,discharge_bus_limit_w=1000.,work=BatteryPortWork())
    data.update(kwargs)
    return battery_port_transition(reference_policy()if policy is None else policy,
        BatteryPortState(Q(0)),**data)


@pytest.mark.parametrize('charging',[False,True])
@pytest.mark.parametrize('r,p',[(0.,0.),(0.,80.),(.001,.000001),(1.,64.),(2.,30.),(.1,400.)])
def test_independent_decimal_and_kirchhoff(charging,r,p):
    result=solve_port(20.,r,p,charging=charging,current_limit=100.,voltage_min=.01,voltage_max=100.)
    assert result.available
    with localcontext()as ctx:
        ctx.prec=80;v=Decimal(20);rd=Decimal.from_float(r);pd=Decimal.from_float(p)
        # Use the other quadratic form at nonzero R, independently of the
        # production cancellation-free root. Decimal80 resolves cancellation.
        if rd==0:current=pd/v
        elif charging:current=((v*v+4*rd*pd).sqrt()-v)/(2*rd)
        else:current=(v-(v*v-4*rd*pd).sqrt())/(2*rd)
        expected=float(current)
    magnitude=abs(result.current_a)
    assert abs(magnitude-expected)<=64*ulp(max(abs(expected),1.e-300))
    vt=20.+magnitude*r if charging else 20.-magnitude*r
    assert result.terminal_voltage_v==vt
    assert abs(vt*magnitude-p)<=64*ulp(max(p,1.))
    assert result.current_a<=0 if charging else result.current_a>=0


def test_hand_solvable_discriminant_boundary_and_unavailable():
    r=solve_port(20.,1.,100.,charging=False,current_limit=10.,voltage_min=10.,voltage_max=40.)
    assert r.available and r.boundary and r.discriminant_v2==0.
    assert r.current_a==10. and r.terminal_voltage_v==10.
    bad=solve_port(20.,1.,100.001,charging=False,current_limit=20.,voltage_min=1.,voltage_max=40.)
    assert not bad.available and bad.reason=='NEGATIVE_DISCRIMINANT'


@pytest.mark.parametrize('charging',[False,True])
def test_zero_current_zero_heat_and_no_simultaneous_flow(charging):
    r=transition(generation_w=8.,load_w=8.)
    assert r.current_a==r.ohmic_heat_wh==r.converter_loss_wh==0.
    assert r.end_energy_wh==r.start_energy_wh
    assert r.charge_input_w==r.discharge_output_w==0.


@pytest.mark.parametrize('charging',[False,True])
@pytest.mark.parametrize('r',[0.,.1,1.,5.])
def test_selected_energy_power_and_heat_references(charging,r):
    p=replace(reference_policy(),resistance_reference_ohm=r)
    x=transition(p,generation_w=30. if charging else 0.,load_w=5. if charging else 30.)
    dt=x.dt_seconds/3600
    expected_delta=(x.chemical_charge_w-x.chemical_discharge_w)*dt
    assert x.end_energy_wh==x.start_energy_wh+expected_delta
    with localcontext()as ctx:
        ctx.prec=80
        heat=Decimal.from_float(x.current_a)**2*Decimal.from_float(r)*Decimal(60)/Decimal(3600)
    # Squaring, R multiplication, dt multiplication and division are four
    # binary64 operations; eight ULP allows their independent association.
    assert abs(x.ohmic_heat_wh-float(heat))<=8*ulp(max(float(heat),1.e-300))
    assert x.conversion_loss_wh==x.ohmic_heat_wh+x.converter_loss_wh
    residual=x.generation_w-x.served_load_w-x.curtailed_generation_w-expected_delta/dt-x.conversion_loss_wh/dt
    assert abs(residual)<=128*ulp(max(x.generation_w,x.load_w,1.))


@pytest.mark.parametrize('charging',[False,True])
def test_r_zero_matches_fixed_efficiency_law_with_inactive_new_guards(charging):
    p=replace(reference_policy(),resistance_reference_ohm=0.,converter_charge_efficiency=.8,converter_discharge_efficiency=.8)
    x=transition(p,generation_w=30. if charging else 0.,load_w=5. if charging else 30.)
    delta=(25*.8 if charging else -30/.8)*60/3600
    assert x.end_energy_wh==100.+delta


def test_remaining_wh_does_not_guarantee_full_service():
    x=transition(replace(reference_policy(),resistance_reference_ohm=8.),load_w=80.)
    assert x.end_energy_wh>0 and x.unmet_load_w>0
    assert x.terminal_voltage_v>=10 and abs(x.current_a)<=8
    assert x.near_boundary


@pytest.mark.parametrize('energy,generation,load',[(0.,0.,80.),(200.,100.,0.),(.00001,0.,80.),(199.99999,100.,0.)])
def test_chemical_capacity_limits(energy,generation,load):
    x=transition(energy_wh=energy,generation_w=generation,load_w=load)
    assert 0<=x.end_energy_wh<=200.
    if energy==0:assert x.served_load_w==0.
    if energy==200:assert x.charge_input_w==0. and x.curtailed_generation_w==100.


@pytest.mark.parametrize('bad',[True,float('nan'),float('inf'),-1.,1<<4096])
def test_strict_domain_bad_inputs_pay_and_leave_state_unchanged(bad):
    state=BatteryPortState(Q(0));before=asdict(state);work=BatteryPortWork()
    with pytest.raises(BatteryPortDomainError):
        battery_port_transition(reference_policy(),state,energy_wh=100.,usable_wh=200.,
            temperature_k=298.15,generation_w=bad,load_w=5.,duration=RationalSeconds.from_fraction(Q(1)),
            charge_bus_limit_w=100.,discharge_bus_limit_w=100.,work=work)
    assert asdict(state)==before and work.reserved==1 and work.refused==1


def test_causal_resistance_history_and_temperature_response():
    p=reference_policy();initial=BatteryPortState(Q(0));work=BatteryPortWork()
    x=transition(p);end=advance_port_state(p,initial,x,start=Q(0),end=Q(60),representative_temperature_k=308.15,work=work)
    assert initial.resistance_damage==0. and initial.selected_steps==0
    assert end.resistance_damage>0 and end.chemical_throughput_wh==x.chemical_throughput_wh
    old=ocv_resistance(p,initial,100.,200.,298.15)[1]
    new=ocv_resistance(p,end,100.,200.,298.15)[1]
    assert new>old and end.last_support_start_seconds==0 and end.clock_seconds==60
    assert isclose(end.temperature_weighted_seconds,120.,rel_tol=1.e-14)


def test_ocv_energy_fraction_and_temperature_domains_are_explicit():
    p=BatteryPortPolicy();state=BatteryPortState(Q(0))
    low=ocv_resistance(p,state,0.,100.,298.15);high=ocv_resistance(p,state,100.,100.,298.15)
    assert low[0]==26. and high[0]==33. and (low[2],high[2])==(0.,1.)
    with pytest.raises(BatteryPortDomainError):ocv_resistance(p,state,101.,100.,298.15)
    with pytest.raises(BatteryPortDomainError):ocv_resistance(p,state,50.,100.,100.)


def test_discharge_residual_does_not_fabricate_negative_unmet_from_round_trip():
    load=float.fromhex('0x1.0000000000003p0')
    generation=float.fromhex('0x1.8000000000000p-52')
    # Exact stored floats: the round trip overshoots load by one ULP.
    assert generation+(load-generation)>load
    result=transition(load_w=load,generation_w=generation)
    assert result.unmet_load_w==0. and result.served_load_w==load
    assert result.discharge_output_w==load-generation


# B59: operation-ordered identities, never reassociation of rounded W values.
def test_partial_service_rounding_regression_b59():
    from dataclasses import replace
    from fractions import Fraction
    from ops_sim.v5.integration_time import RationalSeconds
    p=BatteryPortPolicy();w=BatteryPortWork()
    result=battery_port_transition(p,BatteryPortState(Fraction(0)),energy_wh=50.,usable_wh=100.,
        temperature_k=298.15,generation_w=float.fromhex('0x1.7e527b785274dp+3'),
        load_w=float.fromhex('0x1.d09b113fb737bp+5'),duration=RationalSeconds.from_fraction(Fraction(1)),
        charge_bus_limit_w=100.,discharge_bus_limit_w=float.fromhex('0x1.d9ce4418f6559p+4'),work=w)
    assert result.served_load_w+result.unmet_load_w!=result.load_w
    assert result.unmet_load_w>0 and result.served_load_w>result.generation_w
    assert (w.reserved,w.returned,w.refused,w.unknown)==(1,1,0,0)
    for fields in ({'end_energy_wh':result.end_energy_wh+1.},
                   {'chemical_throughput_wh':result.chemical_throughput_wh+1.},
                   {'chemical_charge_w':1.}, {'chemical_discharge_w':0.},
                   {'current_a':-result.current_a}, {'terminal_voltage_v':result.terminal_voltage_v+1.},
                   {'ohmic_heat_wh':0.},
                   {'unmet_load_w':-1.}, {'served_load_w':result.load_w},
                   {'unmet_load_w':0.}, {'curtailed_generation_w':1.},
                   {'charge_input_w':1.}, {'conversion_loss_wh':0.},
                   {'served_load_w':result.served_load_w+1.,'unmet_load_w':result.unmet_load_w-1.}):
        with pytest.raises(BatteryPortDomainError):replace(result,**fields)
