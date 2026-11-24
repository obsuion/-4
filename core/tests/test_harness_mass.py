from dataclasses import replace
from decimal import Decimal,localcontext
from fractions import Fraction as Q
from math import ulp
import pytest
from examples.m4_mass_closed_mission_demo import make_inputs,distribution_inputs
from ops_sim.v5.harness_mass import compile_harness_mass,combine_mass_properties,MassContribution,SpatialMassPoint,resolve_point
from ops_sim.v5.assembly import AssemblyMassProperties
from ops_sim.v5.assembly_choices import assess_design
from ops_sim.v5.assembly_document import assembly_document_digest


def test_independent_point_parallel_axis_all_nine_entries():
    base=AssemblyMassProperties('B',2.,(0.,0.,0.),((1.,0.,0.),(0.,2.,0.),(0.,0.,3.)))
    zero=((Q(0),)*3,)*3
    point=MassContribution('p','l','POINT',('p',),Q(1),(Q(1),Q(2),Q(3)),zero,())
    mass,center,tensor=combine_mass_properties(base,(point,))
    assert mass==3 and center==(Q(1,3),Q(2,3),Q(1))
    expected=((Q(29,3),Q(-4,3),Q(-2)),(Q(-4,3),Q(26,3),Q(-4)),(Q(-2),Q(-4),Q(19,3)))
    assert tensor==expected


def test_closed_mass_matches_all_eight_wires_and_off_diagonals():
    inputs=make_inputs();m=inputs.coupled.mission
    c=compile_harness_mass(m.assembly,inputs.coupled.configuration,inputs.augmentation)
    assert c.mass_scope=='MASS_CLOSED_WITHIN_RIGID_LUMPED_B46_MODEL'
    assert len(c.route_closure)==8 and all(row[1]+row[2]==row[3] and row[4]==row[5] for row in c.route_closure)
    assert c.added_mass_exact_kg==sum(r.mass_kg for r in c.contributions)
    assert c.effective_mass_exact_kg==Q(c.base_mass_properties.total_mass_kg)+c.added_mass_exact_kg
    assert c.effective_mass_properties.center_body_m!=c.base_mass_properties.center_body_m
    assert any(c.effective_tensor_exact_kg_m2[i][j]!=0 for i in range(3) for j in range(3) if i!=j)


def test_rod_intrinsic_tensor_against_independent_decimal_formula():
    inputs=make_inputs();m=inputs.coupled.mission;c=compile_harness_mass(m.assembly,inputs.coupled.configuration,inputs.augmentation)
    rods=[r for r in c.contributions if r.kind=='UNIFORM_SLENDER_ROD'];assert rods
    with localcontext() as ctx:
        ctx.prec=80
        for rod in rods:
            def decimal(q):return Decimal(q.numerator)/Decimal(q.denominator)
            p,q=rod.endpoints_body_m;d=[decimal(b-a) for a,b in zip(p,q)]
            mass=decimal(rod.mass_kg);length2=sum(x*x for x in d)
            length=length2.sqrt();unit=[x/length for x in d]
            for i in range(3):
                for j in range(3):
                    expected=mass*length*length/12*((Decimal(1) if i==j else Decimal(0))-unit[i]*unit[j])
                    actual=decimal(rod.intrinsic_tensor_body_kg_m2[i][j])
                    #80-digit independent unit-rod formula: <=64 rounded
                    #operations;128*10^-79 of the participating mL² scale.
                    assert abs(actual-expected)<=Decimal(128)*Decimal('1e-79')*max(Decimal(1),abs(mass*length2))


@pytest.mark.parametrize('fault',['assembly','route','missing_slack','connectors','duplicate_line','point_frame','contribution_cap'])
def test_mass_authority_and_shape_rejection(fault):
    i=make_inputs();a=i.augmentation
    with pytest.raises((ValueError,TypeError)):
        if fault=='assembly':a=replace(a,assembly_digest='0'*64)
        elif fault=='route':a=replace(a,routes=(replace(a.routes[0],geometry_digest='0'*64),*a.routes[1:]))
        elif fault=='missing_slack':a=replace(a,routes=(replace(a.routes[0],slack_point=None),*a.routes[1:]))
        elif fault=='connectors':a=replace(a,routes=(replace(a.routes[0],connector_points=()),*a.routes[1:]))
        elif fault=='duplicate_line':a=replace(a,routes=(a.routes[1],*a.routes[1:]))
        elif fault=='point_frame':a=replace(a,routes=(replace(a.routes[0],slack_point=replace(a.routes[0].slack_point,frame_id='foreign')),*a.routes[1:]))
        else:a=replace(a,policy=replace(a.policy,max_contributions=1))
        compile_harness_mass(i.coupled.mission.assembly,i.coupled.configuration,a)


def test_local_frame_point_applies_nonzero_local_com_once():
    i=make_inputs();design=i.coupled.mission.assembly
    defs=tuple(replace(d,center_local_m=(.02,.03,-.01)) if d.definition_id=='camera' else d for d in design.definitions)
    design=replace(design,definitions=defs)
    components={c.component_id:c for c in assess_design(design).assembly.components}
    point=SpatialMassPoint('C-camera',(.01,-.02,.03),'camera','COMPONENT_LOCAL')
    body=resolve_point(point,design,components)
    expected=(.03,.23,-.01)
    assert all(abs(float(a)-b)<=4*ulp(max(abs(b),1.)) for a,b in zip(body,expected))


def test_distribution_control_keeps_exact_mass_and_electrical_authority():
    base=make_inputs('augmented');other=make_inputs('redistributed')
    assert base.coupled==other.coupled
    a=compile_harness_mass(base.coupled.mission.assembly,base.coupled.configuration,base.augmentation)
    b=compile_harness_mass(other.coupled.mission.assembly,other.coupled.configuration,other.augmentation)
    assert a.added_mass_exact_kg==b.added_mass_exact_kg
    assert a.effective_center_exact_m!=b.effective_center_exact_m and a.effective_tensor_exact_kg_m2!=b.effective_tensor_exact_kg_m2


@pytest.mark.parametrize('fault',['base_overlap','route_overlap','included_aggregate'])
def test_declared_mass_coverage_rejects_double_addition(fault):
    from ops_sim.v5.assembly import MassCoverage
    from ops_sim.v5.assembly_interfaces import HarnessMassDeclaration
    i=make_inputs();design=i.coupled.mission.assembly;lines=i.coupled.configuration.lines
    instance=next(x for x in design.instances if x.mass_coverage is not None)
    if fault=='route_overlap':
        claim=lines[1].mass
    else:
        claim=HarnessMassDeclaration('INCLUDED' if fault=='included_aggregate' else 'EXCLUDED',
            MassCoverage((instance.mass_coverage.paths[0]+('declared-harness',),)),instance.instance_id if fault=='included_aggregate' else None)
    configuration=replace(i.coupled.configuration,lines=(replace(lines[0],mass=claim),*lines[1:]))
    from ops_sim.v5.construction_coupling import digest
    augmentation=replace(i.augmentation,construction_digest=digest(configuration))
    with pytest.raises(ValueError,match='already assembled|overlapping harness|INCLUDED_AGGREGATE'):
        compile_harness_mass(design,configuration,augmentation)
