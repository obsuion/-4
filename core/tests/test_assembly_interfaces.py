"""Independent M1-C reference cases and failure-boundary checks."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
import math

import pytest

from examples.m1_assembly_interfaces_demo import IDENTITY, synthetic_inputs
from ops_sim.v5.assembly import MassCoverage, calculate_mass_properties
from ops_sim.v5.assembly_choices import InstallationBox, PhysicalInstance, Selection, assess_design
from ops_sim.v5.assembly_document import assembly_document_digest
from ops_sim.v5.assembly_interfaces import (
    ElectricalPort, HarnessMassDeclaration, ThermalBinding, compile_interfaces,
)


def near(value):
    return pytest.approx(value, rel=2e-14, abs=2e-14)


def line_change(inputs, **kwargs):
    return replace(inputs, lines=(replace(inputs.lines[0], **kwargs),))


def rebind(design, inputs):
    return replace(inputs, assembly_digest=assembly_document_digest(design))


def codes(report):
    return {i.code for i in report.issues}


def two_lines():
    design, inputs = synthetic_inputs()
    choices = list(design.choices)
    instances = list(design.instances)
    selections = list(design.selections)
    for iid, selected in (('source2', 'source-fixed'), ('load2', 'load-near')):
        original = next(c for c in choices if c.choice_id == selected)
        x = original.pose.origin_body_m[0]
        cid = selected + '2'
        pose = replace(original.pose, mount_id=cid, choice_id=cid,
                       origin_body_m=(x, .5, 0), occupied_slots=(cid,))
        choices.append(replace(original, choice_id=cid, allowed_instance_ids=(iid,), pose=pose,
            envelope=InstallationBox((x-.125, .375, -.125), (x+.125, .625, .125))))
        instances.append(PhysicalInstance(iid, original.definition_id, MassCoverage((('devices', iid),))))
        selections.append(Selection(iid, cid))
    design = replace(design, choices=tuple(choices), instances=tuple(instances), selections=tuple(selections))
    ports = inputs.ports + tuple(replace(p, port_id=p.port_id+'2', instance_id=p.instance_id+'2') for p in inputs.ports)
    extra = replace(inputs.lines[0], line_id='power-line2', source_port_id='supply2', load_port_id='receiver2',
                    mass=HarnessMassDeclaration('EXCLUDED', MassCoverage((('external-harness', 'power-line2'),)), None))
    bindings = tuple(ThermalBinding(iid, node, node+'-lump')
        for iid, node in (('source', 'battery'), ('source2', 'battery'), ('load', 'payload'), ('load2', 'payload')))
    inputs = replace(rebind(design, inputs), ports=ports, lines=inputs.lines+(extra,), thermal_bindings=bindings)
    return design, inputs


@pytest.mark.parametrize('case,length,resistance,mass', [('near', 1, .5, 20), ('far', 2, 1, 40)])
def test_same_inventory_changes_route_through_existing_electrical_owner(case, length, resistance, mass):
    design, inputs = synthetic_inputs(case)
    report = compile_interfaces(design, inputs)
    assert report.compilation is not None and report.issues == ()
    line = report.line_diagnostics[0]
    assert line.source_body_m == (0, 0, 0)
    assert line.load_body_m == (length, 0, 0)
    assert line.polyline_length_m == line.wire.one_way_length_m == length
    assert line.wire.resistance_ohm == resistance
    assert line.wire.harness_mass_kg == mass
    assert line.harness_mass_status == 'EXCLUDED'
    assert calculate_mass_properties(report.assembly_assessment.assembly).total_mass_kg == 2
    with localcontext() as ctx:
        ctx.prec = 80
        r = Decimal(str(resistance))
        # Independent high precision low root; deliberately not rationalized like owner.
        current = (Decimal(10) - (Decimal(100) - 4*r*Decimal(18)).sqrt())/(2*r)
        loss = current*current*r
    assert line.electrical.current_a == near(float(current))
    assert line.electrical.loss_w == near(float(loss))
    assert line.electrical.source_power_w == near(18+float(loss))
    heat = {h.node_id.value: h.applied_heat_into_w for h in report.compilation.wire_loss_heat.node_heat_inputs}
    assert heat == {'battery': 0, 'bus': line.electrical.loss_w, 'payload': 0}
    assert report.compilation.heat_accounting_boundary == 'WIRE_LOSS_ONLY_STATIC_OPERATING_POINT'
    assert sum(heat.values()) == line.electrical.loss_w  # no delivered-load heat or EPS heat


def test_exact_hand_solution_and_power_balance():
    d, i = synthetic_inputs()
    line = compile_interfaces(d, i).line_diagnostics[0].electrical
    assert (line.current_a, line.voltage_drop_v, line.loss_w, line.source_power_w,
            line.delivered_power_w, line.load_voltage_v) == (2, 1, 2, 20, 18, 9)
    assert line.source_power_w == line.delivered_power_w + line.loss_w
    assert line.current_a * line.load_voltage_v == line.delivered_power_w


@pytest.mark.parametrize('case,loss,delivered', [('near', 2, 18), ('far', 4, 16)])
def test_generated_power_reference(case, loss, delivered):
    d, i = synthetic_inputs(case, generated=True)
    line = compile_interfaces(d, i).line_diagnostics[0].electrical
    assert line.current_a == 2
    assert line.loss_w == loss and line.delivered_power_w == delivered
    assert line.source_power_w == 20 == line.delivered_power_w + line.loss_w


def test_nonzero_local_com_rotated_mount_port_is_not_double_offset():
    d, i = synthetic_inputs()
    definition = replace(d.definitions[0], center_local_m=(.25, .5, .75))
    rotation = ((0., -1., 0.), (1., 0., 0.), (0., 0., 1.))
    choices = tuple(replace(c, pose=replace(c.pose, rotation_body_from_local=rotation)) for c in d.choices)
    d = replace(d, definitions=(definition,), choices=choices)
    # p_C=(.5,.25,0). At mount origin (1,0,0), R*p_C=(-.25,.5,0).
    # Component COM=(.5,.25,.75), and center + R*(p_C-c_C)=(.75,.5,0).
    ports = tuple(replace(p, position_local_m=(.5,.25,0)) if p.role == 'LOAD'
                  else replace(p, position_local_m=(0,0,0)) for p in i.ports)
    report = compile_interfaces(d, replace(rebind(d, i), ports=ports))
    assert report.compilation is not None
    assert report.line_diagnostics[0].source_body_m == (0,0,0)
    assert report.line_diagnostics[0].load_body_m == (.75,.5,0)
    assert report.line_diagnostics[0].polyline_length_m == near(math.sqrt(.8125))


def test_polyline_and_slack_once_connectors_owned_by_wire_spec():
    d, i = synthetic_inputs()
    w = replace(i.lines[0].wire, connector_count=2, connector_mass_kg=.5, connector_resistance_ohm=.1)
    i = line_change(i, waypoints_body_m=((0,1,0),(1,1,0)), slack_m=.25, wire=w,
                    operating_point=replace(i.lines[0].operating_point, power_w=1))
    line = compile_interfaces(d, i).line_diagnostics[0]
    assert line.polyline_length_m == 3
    assert line.wire.one_way_length_m == 3.25 and line.wire.loop_length_m == 6.5
    assert line.wire.resistance_ohm == near(1.825)
    assert line.wire.conductor_mass_kg == 65
    assert line.wire.connector_total_mass_kg == 1 and line.wire.harness_mass_kg == 66


def test_reposition_requires_new_binding_and_recomputes_endpoint():
    near_design, i = synthetic_inputs()
    far_design, _ = synthetic_inputs('far')
    with pytest.raises(ValueError, match='digest mismatch'):
        compile_interfaces(far_design, i)
    result = compile_interfaces(far_design, rebind(far_design, i))
    assert result.line_diagnostics[0].wire.one_way_length_m == 2


@pytest.mark.parametrize('kind', ['outside', 'coverage', 'missing-envelope'])
def test_authorized_pose_is_not_enough_for_subsystem_compilation(kind):
    d, i = synthetic_inputs()
    if kind == 'outside':
        d = replace(d, choices=tuple(replace(c, envelope=InstallationBox((5,5,5),(6,6,6)))
            if c.choice_id == 'load-near' else c for c in d.choices))
    elif kind == 'coverage':
        d = replace(d, instances=tuple(replace(x, mass_coverage=MassCoverage((('duplicate',),))) for x in d.instances))
    else:
        d = replace(d, choices=tuple(replace(c, envelope=None, allowed_region_id=None)
            if c.choice_id == 'load-near' else c for c in d.choices))
    report = compile_interfaces(d, rebind(d, i))
    assert not report.assembly_assessment.qualified
    assert report.compilation is None and report.line_diagnostics == ()
    assert any(x.category == ('INCOMPLETE' if kind == 'missing-envelope' else 'CONSTRAINT') for x in report.issues)


def test_disjoint_lines_explicit_lumping_and_heat_sum():
    d, i = two_lines()
    report = compile_interfaces(d, i)
    assert report.compilation is not None
    assert len(report.line_diagnostics) == 2
    assert sum(x.applied_heat_into_w for x in report.compilation.wire_loss_heat.node_heat_inputs) == 4


def test_branching_different_ports_same_instance_is_unsupported_no_circuit_eval():
    d, i = two_lines()
    i = replace(i, ports=tuple(replace(p, instance_id='source') if p.port_id == 'supply2' else p for p in i.ports))
    report = compile_interfaces(d, i)
    assert 'SHARED_INSTANCE_TOPOLOGY' in codes(report)
    assert report.compilation is None and not report.line_diagnostics
    assert {x.category for x in report.issues} == {'UNSUPPORTED'}


def test_shared_source_port_is_unsupported_not_independent_supply():
    d, i = two_lines()
    i = replace(i, lines=(i.lines[0], replace(i.lines[1], source_port_id='supply')))
    report = compile_interfaces(d, i)
    assert {'SHARED_INSTANCE_TOPOLOGY','UNCONNECTED_PORT'} <= codes(report)
    assert report.compilation is None and not report.line_diagnostics


def test_duplicate_connection_rejects_even_with_different_line_id():
    _, i = synthetic_inputs()
    with pytest.raises(ValueError, match='duplicate connection'):
        replace(i, lines=i.lines+(replace(i.lines[0], line_id='alias'),))


@pytest.mark.parametrize('change', ['port', 'instance', 'local-frame', 'body-frame', 'heat-node', 'thermal-instance'])
def test_dangling_or_wrong_frame_input_raises(change):
    d, i = synthetic_inputs()
    with pytest.raises(ValueError):
        if change == 'port':
            i = line_change(i, load_port_id='absent')
        elif change in ('instance','local-frame'):
            changes = {'instance_id':'absent'} if change == 'instance' else {'local_frame_id':'wrong'}
            i = replace(i, ports=(replace(i.ports[0], **changes), i.ports[1]))
        elif change == 'body-frame':
            i = replace(i, body_frame_id='wrong')
        elif change == 'heat-node':
            i = line_change(i, wire_loss_node_id='unknown')
        else:
            i = replace(i, thermal_bindings=(ThermalBinding('unknown','bus',None),))
        compile_interfaces(d, i)


def test_incompatible_roles_fail_before_calculation():
    _, i = synthetic_inputs()
    with pytest.raises(ValueError, match='incompatible'):
        replace(i, ports=tuple(replace(p, role='SOURCE') for p in i.ports))


@pytest.mark.parametrize('missing,expected', [
    ('heat','MISSING_WIRE_HEAT_DESTINATION'), ('network','MISSING_THERMAL_NETWORK'),
    ('boundaries','MISSING_THERMAL_BOUNDARIES'), ('one-boundary','MISSING_NODE_BOUNDARY'),
    ('binding','MISSING_INSTANCE_THERMAL_BINDING'), ('mass','UNSPECIFIED_HARNESS_MASS')])
def test_incomplete_mapping_is_not_usable(missing, expected):
    d, i = synthetic_inputs()
    if missing == 'heat': i = line_change(i, wire_loss_node_id=None)
    elif missing == 'network': i = replace(i, thermal_network=None)
    elif missing == 'boundaries': i = replace(i, thermal_boundaries=None)
    elif missing == 'one-boundary': i = replace(i, thermal_boundaries=replace(i.thermal_boundaries, node_boundaries=i.thermal_boundaries.node_boundaries[:1]))
    elif missing == 'binding': i = replace(i, thermal_bindings=())
    else: i = line_change(i, mass=HarnessMassDeclaration('UNSPECIFIED',None,None))
    report = compile_interfaces(d, i)
    assert report.compilation is None and expected in codes(report)
    assert {x.category for x in report.issues} == {'INCOMPLETE'}
    assert len(report.line_diagnostics) == 1  # clearly marked diagnostic only


def test_lumping_must_be_explicit():
    d, i = two_lines()
    i = replace(i, thermal_bindings=tuple(replace(b, lumping_group=None) for b in i.thermal_bindings))
    report = compile_interfaces(d, i)
    assert 'UNDECLARED_THERMAL_LUMPING' in codes(report) and report.compilation is None


def test_lumping_group_cannot_change_node():
    _, i = synthetic_inputs()
    with pytest.raises(ValueError, match='different nodes'):
        replace(i, thermal_bindings=tuple(replace(b, lumping_group='shared') for b in i.thermal_bindings))


def test_included_harness_is_not_added_or_claimed_numerically_closed():
    d, i = synthetic_inputs()
    mass = HarnessMassDeclaration('INCLUDED', MassCoverage((('devices','source','internal-wire'),)), 'source')
    report = compile_interfaces(d, line_change(i, mass=mass))
    assert report.compilation is not None
    assert calculate_mass_properties(report.assembly_assessment.assembly).total_mass_kg == 2
    # Synthetic computed 20 kg is separate even though owning aggregate is 1 kg.
    assert report.line_diagnostics[0].wire.harness_mass_kg == 20
    assert report.line_diagnostics[0].harness_mass_status == 'INCLUDED'


@pytest.mark.parametrize('status,owner,code', [
    ('EXCLUDED',None,'EXCLUDED_HARNESS_ALREADY_ASSEMBLED'),
    ('INCLUDED','load','HARNESS_NOT_COVERED_BY_OWNER')])
def test_bad_declared_mass_accounting_is_constraint(status, owner, code):
    d, i = synthetic_inputs()
    i = line_change(i, mass=HarnessMassDeclaration(status, MassCoverage((('devices','source'),)), owner))
    report = compile_interfaces(d, i)
    assert code in codes(report) and report.compilation is None
    assert {x.category for x in report.issues} == {'CONSTRAINT'}


def test_mass_aggregate_child_overlap_across_line_ids_collects_all_issues():
    d, i = two_lines()
    first = replace(i.lines[0], mass=HarnessMassDeclaration('EXCLUDED', MassCoverage((('wire',),)),None),wire_loss_node_id=None)
    second = replace(i.lines[1], mass=HarnessMassDeclaration('EXCLUDED', MassCoverage((('wire','child'),)),None),
                     wire=replace(i.lines[1].wire,current_limit_a=1))
    report = compile_interfaces(d, replace(i, lines=(first,second)))
    assert codes(report) == {'HARNESS_MASS_OVERLAP','MISSING_WIRE_HEAT_DESTINATION','ELECTRICAL_LIMIT'}
    assert report.compilation is None
    again = compile_interfaces(d, replace(i, lines=(second,first)))
    assert again == report


@pytest.mark.parametrize('change', ['current','drop','fold','collapsed'])
def test_electrical_limits_reject_without_clamping(change):
    d, i = synthetic_inputs()
    line = i.lines[0]
    if change == 'current': line = replace(line, wire=replace(line.wire, current_limit_a=math.nextafter(2,0)))
    elif change == 'drop': line = replace(line, wire=replace(line.wire, max_drop_v=math.nextafter(1,0)))
    elif change == 'fold': line = replace(line, operating_point=replace(line.operating_point,power_w=50))
    else: line = replace(line, operating_point=replace(line.operating_point,mode='GENERATED',power_w=200))
    report = compile_interfaces(d, replace(i, lines=(line,)))
    assert codes(report) == {'ELECTRICAL_LIMIT'} and report.compilation is None
    assert report.line_diagnostics == ()


def test_exact_electrical_limit_equality_passes():
    d, i = synthetic_inputs()
    assert compile_interfaces(d, line_change(i, wire=replace(i.lines[0].wire,current_limit_a=2,max_drop_v=1))).compilation is not None


def test_mechanical_only_instance_needs_no_invented_ports():
    d, i = synthetic_inputs()
    i = replace(i, ports=(), lines=(), thermal_bindings=())
    report = compile_interfaces(d, i)
    assert report.compilation is not None and report.line_diagnostics == ()
    assert all(h.applied_heat_into_w == 0 for h in report.compilation.wire_loss_heat.node_heat_inputs)


class HostileFloat(float):
    def __eq__(self, other): return True


@pytest.mark.parametrize('bad', [True, HostileFloat(1), float('nan'), float('inf'), -1])
def test_invalid_numerics_rejected(bad):
    _, i = synthetic_inputs()
    with pytest.raises((ValueError,TypeError)):
        line_change(i, slack_m=bad)
    with pytest.raises((ValueError,TypeError)):
        replace(i.lines[0].wire, cross_section_m2=bad)


def test_deep_immutability_and_revalidation():
    d, i = synthetic_inputs()
    with pytest.raises(FrozenInstanceError): i.lines[0].slack_m = 2
    with pytest.raises(TypeError): replace(i,ports=list(i.ports))
    with pytest.raises(TypeError): line_change(i,waypoints_body_m=([0,0,0],))
    object.__setattr__(i.lines[0].wire, 'connector_count', True)
    with pytest.raises(ValueError): compile_interfaces(d,i)


def test_no_invented_thermal_provenance_or_mandatory_roles():
    _, i = synthetic_inputs()
    n = i.thermal_network
    with pytest.raises(ValueError): replace(n,battery_node_id=n.bus_node_id)
    with pytest.raises(ValueError):
        replace(n.nodes[0].heat_capacity_j_per_k.provenance, rationale=None)
