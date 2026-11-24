"""Genuine paid static construction checks; no mission/forecast evaluations."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
from math import fsum

import pytest

from ops_sim.v5.design_repair import ConstructorLedger
from ops_sim.v5.lifecycle_document import loads_root, dumps_root
from ops_sim.v5.spacecraft_project_document import dumps_project, loads_project
from ops_sim.v5.ninety_day_designs import (loads_intent, author_project,
    compile_project, confirm_compiled, design_report, ResearchIntent)

FIXTURES = Path(__file__).with_name('fixtures')


@pytest.fixture(scope='module')
def common():
    return loads_root((FIXTURES/'b66_common_initial.json').read_bytes())


@pytest.fixture(scope='module')
def intent():
    return loads_intent((FIXTURES/'ninety_day_intent_v1.json').read_bytes())


@pytest.fixture(scope='module')
def compiled(common, intent):
    rows={}
    for row in intent.data['designs']:
        ledger=ConstructorLedger(maximum_compiles=3)
        authored=author_project(common,intent,row['id'],ledger)
        admission=compile_project(authored,ledger)
        assert ledger.compiles==3
        rows[row['id']]=(authored,admission)
    return rows


def test_original_intent_is_immutable_and_roundtrips_exactly(intent):
    raw=(FIXTURES/'ninety_day_intent_v1.json').read_bytes()
    assert intent.raw_json.encode('utf8')==raw
    changed=intent.data;changed['designs'][0]['core']['mass_kg']=999
    assert intent.data['designs'][0]['core']['mass_kg']==4


@pytest.mark.parametrize('index',range(5))
def test_five_real_projects_compile_and_independently_admit(compiled,intent,index):
    row=intent.data['designs'][index];authored,a=compiled[row['id']]
    ledger=ConstructorLedger(maximum_compiles=2)
    b=confirm_compiled(authored,a.root,ledger)
    assert ledger.compiles==2 and dumps_root(a.root)==dumps_root(b.root)
    public=design_report(authored,a)
    assert public['mass']['part_mass_kg']==float(row['expected_part_mass_before_harness_kg'])
    assert public['nominal_battery_wh']==float(row['nominal_battery_wh'])
    assert public['nominal_pv_w']==float(row['nominal_pv_w'])
    assert len(public['mass']['inertia_COM_body_kg_m2'])==3
    assert all(len(x)==3 for x in public['mass']['inertia_COM_body_kg_m2'])
    assert len(public['routes'])==8 and a.hardware.augmentation.added_mass_exact_kg>0
    assert dumps_project(loads_project(dumps_project(authored.project)))==dumps_project(authored.project)
    assert authored.audit['geometry_repairs']==authored.audit['intent_coordinate_diff']==[]


def test_common_state_and_physical_laws_preserved(compiled,common):
    for authored,a in compiled.values():
        assert authored.project.common is common
        spec=authored.project.specification.base
        assert a.root.scenario==common.scenario and a.root.policy==common.policy
        assert a.root.base.requests==common.base.requests
        assert a.root.base.model.environment==common.base.model.environment
        assert a.root.base.model.actuator==common.base.model.actuator
        assert a.root.environment_ageing_policy==common.environment_ageing_policy
        assert a.root.study.calendar_damage_per_second==common.study.calendar_damage_per_second
        assert a.root.study.cycling_damage_per_normalized_throughput==common.study.cycling_damage_per_normalized_throughput
        assert a.root.study.ageing_multiplier==common.study.ageing_multiplier
        assert a.root.study.solar_retention_loss_per_second==common.study.solar_retention_loss_per_second
        assert a.root.base.initial_checkpoint.spacecraft.degradation==common.base.initial_checkpoint.spacecraft.degradation
        cfg=a.root.base.model.simulation_inputs.spacecraft_configuration
        assert a.root.base.initial_checkpoint.spacecraft.battery_energy_wh==(cfg.eps.battery.nominal_energy_wh.value*
            common.base.initial_checkpoint.spacecraft.degradation.battery.usable_capacity_retention*spec.initial_usable_energy_fraction)
        assert tuple((n.node_id.value,n.temperature_k)for n in a.root.base.initial_checkpoint.spacecraft.thermal.node_states)==spec.initial_temperatures_k
        assert cfg.thermal.network.links==common.base.model.configuration.thermal_network.links


def test_d1_d4_control_has_only_battery_pose_and_derived_route_changes(compiled):
    left,a=compiled['D1_BALANCED'];right,b=compiled['D4_OUTBOARD']
    sa,sb=left.project.specification.base,right.project.specification.base
    assert sa.batteries==sb.batteries and sa.pv_modules==sb.pv_modules
    assert sa.thermal_parts==sb.thermal_parts
    assert sa.functional==sb.functional and sa.actuator==sb.actuator
    assert sa.capabilities==sb.capabilities
    assert sa.initial_temperatures_k==sb.initial_temperatures_k
    assert sa.initial_usable_energy_fraction==sb.initial_usable_energy_fraction
    assert sa.assembly.definitions==sb.assembly.definitions
    from ops_sim.v5.assembly_choices import assess_design
    ca={c.component_id:c for c in assess_design(a.hardware.design).assembly.components}
    cb={c.component_id:c for c in assess_design(b.hardware.design).assembly.components}
    for name in ca:
        if not name.startswith('battery-'):assert ca[name]==cb[name]
    assert a.hardware.augmentation.base_mass_properties.total_mass_kg==b.hardware.augmentation.base_mass_properties.total_mass_kg
    assert a.hardware.mass_properties.inertia_com_body_kg_m2!=b.hardware.mass_properties.inertia_com_body_kg_m2
    assert a.hardware.augmentation.added_mass_exact_kg!=b.hardware.augmentation.added_mass_exact_kg
    assert a.construction.branches!=b.construction.branches
    assert any(x.wire.resistance_ohm!=y.wire.resistance_ohm for x,y in zip(a.construction.branches,b.construction.branches))
    assert a.route_thermal.route_capacities!=b.route_thermal.route_capacities
    assert left.audit['routing']['internal_battery_and_PV_bank_leads']=='IDEAL_UNRESOLVED_NO_SEPARATE_LOSS_CLAIM'


def test_actual_local_ports_rotations_and_declared_occupied_extents(compiled):
    from ops_sim.v5.assembly_interfaces import _port_body
    from ops_sim.v5.assembly_choices import assess_design
    for authored,a in compiled.values():
        spec=authored.project.specification.base
        assessment=assess_design(spec.assembly);assert assessment.qualified
        cs={c.component_id:c for c in assessment.assembly.components}
        ps={p.port_id:p for p in spec.configuration.ports}
        ls={l.line_id:l for l in spec.configuration.lines}
        for branch in a.construction.branches:
            line=ls[branch.line_id];p=ps[line.source_port_id];q=ps[line.load_port_id]
            assert branch.source_body_m==_port_body(p,cs[p.instance_id])
            assert branch.load_body_m==_port_body(q,cs[q.instance_id])
        assert a.hardware.panel_body_normal==(-.8,-.6,0.)
        assert a.hardware.camera_body_axis==(.8,.6,0.)
        assert len(a.hardware.mass_properties.inertia_com_body_kg_m2)==3


def test_uniform_area_rule_and_genuine_mass_cp_once(compiled):
    fractions=set()
    for authored,a in compiled.values():
        spec=authored.project.specification
        core=next(d for d in spec.base.assembly.definitions if d.definition_id=='core')
        part=next(p for p in spec.base.thermal_parts if p.instance_id=='core')
        x,y,z=core.size_m;surface=2.*fsum((x*y,x*z,y*z))
        fractions.add(authored.audit['thermal']['core_exposed_fraction'])
        assert part.radiating_area_m2==surface*authored.audit['thermal']['core_exposed_fraction']
        for node,capacity in a.route_thermal.final_capacities:
            assert capacity==dict(a.route_thermal.base_capacities)[node]+dict(a.route_thermal.route_capacities)[node]
        assert sum((row[1]for row in a.route_thermal.per_line),start=__import__('fractions').Fraction(0))==a.hardware.augmentation.added_mass_exact_kg
    assert len(fractions)==1


def test_forged_compiled_root_rejected_with_paid_independent_units(compiled):
    authored,a=compiled['D1_BALANCED'];root=deepcopy(a.root)
    object.__setattr__(root,'study',replace(root.study,initial_energy_fraction=root.study.initial_energy_fraction/2))
    ledger=ConstructorLedger(maximum_compiles=2)
    with pytest.raises((ValueError,TypeError)):confirm_compiled(authored,root,ledger)
    assert ledger.compiles==2


def test_stale_authored_project_audit_rejected(compiled):
    authored,a=compiled['D1_BALANCED']
    with pytest.raises(ValueError,match='binding mismatch'):
        replace(authored,project=replace(authored.project,title='stale alternate title'))


def test_overlapping_occupied_core_refused_before_science(common,intent):
    data=intent.data;data['designs'][0]['camera_position_m']=[0,0,0]
    data['designs'][3]['camera_position_m']=[0,0,0]  # Retain the declared placement-control relation.
    candidate=loads_intent(json.dumps(data));ledger=ConstructorLedger(maximum_compiles=1)
    before=dumps_root(common)
    with pytest.raises(ValueError,match='GEOMETRY_REFUSED_BEFORE_SCIENCE'):
        author_project(common,candidate,'D1_BALANCED',ledger)
    assert ledger.compiles==1 and dumps_root(common)==before


def test_arbitrary_declared_ids_are_not_a_saved_root_whitelist(common,intent):
    data=intent.data
    for row in data['designs']:
        row['id']='USER-'+row['id']
        if 'control_pair'in row:row['control_pair']='USER-'+row['control_pair']
    new=loads_intent(json.dumps(data));ledger=ConstructorLedger(maximum_compiles=1)
    authored=author_project(common,new,'USER-D2_LIGHT',ledger)
    assert authored.project.title=='90D USER-D2_LIGHT'and ledger.compiles==1
    assert len(authored.project.specification.base.batteries)==1


@pytest.mark.parametrize('change', ['boolean','nonfinite','extra-root','mass-total','control-core','module-law'])
def test_bad_intent_cannot_smuggle_authority_or_conflicting_counts(intent,change):
    data=intent.data
    if change=='boolean':data['designs'][0]['core']['mass_kg']=True
    elif change=='nonfinite':data['designs'][0]['battery_positions_m'][0][0]=float('nan')
    elif change=='extra-root':data['designs'][0]['compiled_root']={}
    elif change=='mass-total':data['designs'][0]['expected_part_mass_before_harness_kg']=100
    elif change=='control-core':data['designs'][3]['core']['size_m']=[.21,.2,.2]
    elif change=='module-law':data['common_modules']['battery']['capacity_wh']=51
    with pytest.raises((ValueError,TypeError)):loads_intent(json.dumps(data))


def test_duplicate_json_key_and_foreign_source_are_refused(common,intent):
    with pytest.raises(ValueError,match='duplicate JSON key'):
        loads_intent(intent.raw_json.replace('"mass_kg": 4,','"mass_kg": 4, "mass_kg": 4,',1))
    ledger=ConstructorLedger(maximum_compiles=1)
    with pytest.raises(ValueError,match='PROJECT_SOURCE_MISMATCH'):
        author_project(common,intent,'D1_BALANCED',ledger,source_identity='0'*64)
    assert ledger.compiles==0
