from dataclasses import replace
from decimal import Decimal, localcontext
from math import ulp
import pytest
from examples.m4_construction_mission_demo import make_inputs
from ops_sim.v5.construction_coupling import compile_construction
from ops_sim.v5.design_trade_physics import WireSpec,constant_power_load,generated_power_line,ElectricalLimitError


def wire(length=.5,**kwargs):
    return replace(WireSpec(length,1.,1.,1.,0.,0,0.,10.,10.),**kwargs)


def test_zero_resistance_and_hand_low_root():
    zero=constant_power_load(wire(0.),10.,20.)
    assert (zero.current_a,zero.loss_w,zero.delivered_power_w)==(2.,0.,20.)
    value=constant_power_load(wire(),10.,16.)
    assert (value.current_a,value.voltage_drop_v,value.loss_w,value.source_power_w)==(2.,2.,4.,20.)


def test_independent_decimal_root():
    result=constant_power_load(wire(),10.,3.)
    with localcontext() as c:
        c.prec=80
        expected=(Decimal(10)-(Decimal(100)-Decimal(12)).sqrt())/2
        assert abs(Decimal.from_float(result.current_a)-expected)<=Decimal.from_float(2*ulp(result.current_a))


@pytest.mark.parametrize('power',[25.,26.])
def test_collapsed_or_no_root(power):
    with pytest.raises(ElectricalLimitError):constant_power_load(wire(),10.,power)


def test_current_and_drop_are_independent_guards():
    with pytest.raises(ElectricalLimitError,match='current'):constant_power_load(wire(current_limit_a=1.),10.,16.)
    with pytest.raises(ElectricalLimitError,match='drop'):constant_power_load(wire(max_drop_v=1.),10.,16.)


def test_generated_line_hand_balance():
    r=generated_power_line(wire(),12.,24.)
    assert (r.current_a,r.loss_w,r.delivered_power_w)==(2.,4.,20.)
    assert r.source_power_w==r.delivered_power_w+r.loss_w


@pytest.mark.parametrize('bad',[float('inf'),float('nan'),True])
def test_finite_strict_values(bad):
    with pytest.raises((ValueError,TypeError)):constant_power_load(wire(),bad,1.)


def test_compiler_recomputes_endpoints_and_harness_scope():
    inputs=make_inputs();c=compile_construction(inputs.mission.assembly,inputs.configuration)
    assert len(c.branches)==8 and c.conductor_mass_kg>0 and c.connector_mass_kg==.032
    assert c.mass_scope=='NOT_MASS_CLOSED_EXCLUDED_HARNESS'
    pv=next(b for b in c.branches if b.line_id=='pv-line')
    assert pv.source_body_m==(0.,-.5,0.) and pv.load_body_m==(0.,0.,0.)
    assert pv.polyline_length_m==.5 and pv.wire.one_way_length_m==.7


@pytest.mark.parametrize('fault',['digest','heat','topology','frame','mass'])
def test_static_rejection_before_execution(fault):
    inputs=make_inputs();c=inputs.configuration
    with pytest.raises((ValueError,TypeError)):
        if fault=='digest':c=replace(c,assembly_digest='0'*64)
        elif fault=='heat':c=replace(c,lines=(replace(c.lines[0],wire_loss_node_id=None),*c.lines[1:]))
        elif fault=='topology':c=replace(c,topology='PARALLEL_BATTERIES')
        elif fault=='frame':c=replace(c,ports=(replace(c.ports[0],local_frame_id='foreign'),*c.ports[1:]))
        else:c=replace(c,lines=(replace(c.lines[0],mass=replace(c.lines[0].mass,coverage=c.lines[1].mass.coverage)),*c.lines[1:]))
        compile_construction(inputs.mission.assembly,c)


def test_old_static_owner_still_rejects_shared_instances():
    from ops_sim.v5.assembly_interfaces import AssemblyInterfaces,compile_interfaces
    i=make_inputs();c=i.configuration
    lines=tuple(l for l in c.lines if l.line_id in ('pv-line','payload-line'))
    endpoints={p for l in lines for p in (l.source_port_id,l.load_port_id)}
    old=AssemblyInterfaces(c.assembly_digest,c.body_frame_id,tuple(p for p in c.ports if p.port_id in endpoints),lines,c.thermal_bindings,c.thermal_network,c.thermal_boundaries,'IDEAL_INDEPENDENT_SOURCES',c.rationale)
    assessment=compile_interfaces(i.mission.assembly,old)
    assert assessment.compilation is None and any(x.code=='SHARED_INSTANCE_TOPOLOGY' for x in assessment.issues)


@pytest.mark.parametrize('field',['topology','generation_model','regulator_loss_model'])
def test_hostile_text_equality_cannot_authorize_model(field):
    class EqualText(str):
        def __eq__(self,other):return True
        def __ne__(self,other):return False
    inputs=make_inputs()
    with pytest.raises((TypeError,ValueError)):replace(inputs.configuration,**{field:EqualText('wrong')})


def test_hostile_api_equality_rejects():
    class EqualText(str):
        def __eq__(self,other):return True
        def __ne__(self,other):return False
    with pytest.raises((TypeError,ValueError)):replace(make_inputs(),api=EqualText('wrong'))
