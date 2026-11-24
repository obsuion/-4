"""Bounded declared-accounting/rounding/consumer checks, not flight validation."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from math import fsum
import json
import pytest
from b68_cases import authored
from ops_sim.v5.spacecraft_route_thermal import (RouteThermalDeclaration,DesignSpecificationV2,
    RouteThermalCompilation,admit_design_v2,admit_compiled_design_v2,constructor_compile_bound)
from ops_sim.v5.design_repair import ConstructorLedger
from ops_sim.v5.rolling_physics import digest
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.spacecraft_project_document import dumps_project,loads_project

@pytest.fixture(scope='module')
def project():return authored()[0]

@pytest.fixture(scope='module')
def admitted(project):
    ledger=ConstructorLedger(maximum_compiles=2)
    a=admit_design_v2(project.specification,project.common,ledger)
    assert ledger.compiles==2 and ledger.control_reserved==2*16*2**20
    return a

def paid(spec,common):return admit_design_v2(spec,common,ConstructorLedger(maximum_compiles=2))

def test_original_user_v1_exact_capacity_and_final_bindings(project,admitted):
    p,user,mapping=authored()
    audit=admitted.route_thermal;net=admitted.root.base.model.configuration.thermal_network
    roles={'BUS':net.bus_node_id.value,'BATTERY':net.battery_node_id.value,'PAYLOAD':net.payload_node_id.value}
    assert dict(audit.final_capacities)=={roles[k]:v for k,v in mapping['thermal_ownership']['required_node_capacities_j_k'].items()}
    assert dict(audit.final_capacities)[net.bus_node_id.value]==dict(audit.base_capacities)[net.bus_node_id.value]+float(admitted.hardware.augmentation.added_mass_exact_kg)*user['thermal']['harness_specific_heat_j_kg_k']
    assert sum((row[1]for row in audit.per_line),Fraction(0))==admitted.hardware.augmentation.added_mass_exact_kg
    assert {c.kind for c in admitted.hardware.augmentation.contributions}>={'UNIFORM_SLENDER_ROD','DECLARED_POINT_SLACK','DECLARED_POINT_CONNECTOR'}
    assert admitted.hardware.configuration is admitted.root.base.model.configuration
    assert admitted.hardware.augmentation_inputs==admitted.root.base.model.augmentation
    assert admitted.construction.configuration_digest==admitted.hardware.augmentation.construction_digest
    assert digest(admitted.root.base.model.simulation_inputs.spacecraft_configuration.thermal.network)==digest(net)
    assert constructor_compile_bound(p.specification)==2 and constructor_compile_bound(p.specification.base)==1

def test_second_genuine_assembly_same_common_different_mechanics(project,admitted):
    other,_,_=authored('own');a=paid(other.specification,other.common)
    assert other.common.identity==project.common.identity
    assert digest(other.specification.base.assembly)!=digest(project.specification.base.assembly)
    assert digest(a.hardware.mass_properties)!=digest(admitted.hardware.mass_properties)

def test_independent_full_root_admission_not_audit_authority(project,admitted):
    ledger=ConstructorLedger(maximum_compiles=2)
    a=admit_compiled_design_v2(project.specification,project.common,admitted.root,ledger)
    assert dumps_root(a.root)==dumps_root(admitted.root)and ledger.compiles==2
    forged=deepcopy(admitted.root)
    object.__setattr__(forged,'study',replace(forged.study,nodes=tuple(replace(n,heat_capacity_j_per_k=n.heat_capacity_j_per_k+1.)for n in forged.study.nodes)))
    ledger=ConstructorLedger(maximum_compiles=2)
    with pytest.raises((ValueError,TypeError)):
        admit_compiled_design_v2(project.specification,project.common,forged,ledger)
    assert ledger.compiles==2

def test_swapped_common_refuses_stale_proposed_root(project,admitted):
    common=replace(project.common,policy=replace(project.common.policy,max_task_output_bytes=project.common.policy.max_task_output_bytes-1))
    ledger=ConstructorLedger(maximum_compiles=2);before=dumps_root(common)
    with pytest.raises(ValueError):admit_compiled_design_v2(project.specification,common,admitted.root,ledger)
    assert ledger.compiles==2 and dumps_root(common)==before

def test_cp_only_changes_actual_heat_transition_not_mechanics(project,admitted):
    spec=replace(project.specification,route_thermal=tuple(replace(d,specific_heat_j_per_kg_k=d.specific_heat_j_per_kg_k*2)for d in project.specification.route_thermal))
    a=paid(spec,project.common)
    assert digest(a.hardware.mass_properties)==digest(admitted.hardware.mass_properties)
    assert digest(a.hardware.augmentation.contributions)==digest(admitted.hardware.augmentation.contributions)
    assert digest(a.construction.branches)==digest(admitted.construction.branches)
    from ops_sim.v5.thermal import (ThermalIntervalInputs,ThermalNodeBoundaryInput,ThermalAppliedHeatInputs,
        ThermalNodeAppliedHeatInput,compute_thermal_interval_transition_with_applied_heat)
    temperatures=[]
    for item in (admitted,a):
        net=item.root.base.model.configuration.thermal_network
        state=item.root.base.initial_checkpoint.spacecraft.thermal
        from ops_sim.v5.state import ThermalState,ThermalNodeState
        state=ThermalState(tuple(ThermalNodeState(n.node_id,300.)for n in state.node_states))
        inputs=ThermalIntervalInputs(tuple(ThermalNodeBoundaryInput(n.node_id,300.)for n in net.nodes))
        heat=ThermalAppliedHeatInputs(tuple(ThermalNodeAppliedHeatInput(n.node_id,10. if n.node_id==net.bus_node_id else 0.)for n in net.nodes))
        result=compute_thermal_interval_transition_with_applied_heat(state,net,inputs,heat,dt_seconds=1)
        bus=next(n for n in result.node_transitions if n.node_id==net.bus_node_id)
        C=next(n.heat_capacity_j_per_k.value for n in net.nodes if n.node_id==net.bus_node_id)
        assert bus.end_temperature_k==300.+10./C # analytic zero-conduction/equal-sink case, K
        temperatures.append(bus.end_temperature_k)
    assert temperatures[1]<temperatures[0]

def test_section_changes_mass_tensor_and_route_capacity_once(project,admitted):
    base=project.specification.base
    cfg=replace(base.configuration,lines=tuple(replace(l,wire=replace(l.wire,cross_section_m2=l.wire.cross_section_m2/2))if l.line_id=='payload-line'else l for l in base.configuration.lines))
    a=paid(replace(project.specification,base=replace(base,configuration=cfg)),project.common)
    assert a.hardware.augmentation.base_mass_properties==admitted.hardware.augmentation.base_mass_properties
    assert a.hardware.augmentation.added_mass_exact_kg<admitted.hardware.augmentation.added_mass_exact_kg
    assert a.hardware.mass_properties.inertia_com_body_kg_m2!=admitted.hardware.mass_properties.inertia_com_body_kg_m2
    assert a.route_thermal.final_capacities!=admitted.route_thermal.final_capacities
    assert a.hardware.augmentation.effective_mass_exact_kg==a.hardware.augmentation.added_mass_exact_kg+Fraction(a.hardware.augmentation.base_mass_properties.total_mass_kg)

def test_mixed_groups_use_exact_mass_and_explicit_capacity_destination(project,admitted):
    net=project.specification.base.configuration.thermal_network
    declarations=tuple(replace(d,thermal_node_id=net.payload_node_id.value,specific_heat_j_per_kg_k=700.)if i%2 else d for i,d in enumerate(project.specification.route_thermal))
    a=paid(replace(project.specification,route_thermal=declarations),project.common)
    for node,final in a.route_thermal.final_capacities:
        groups=[v for n,c,m,v in a.route_thermal.groups if n==node]
        assert final==dict(a.route_thermal.base_capacities)[node]+fsum(groups)
    assert digest(a.hardware.mass_properties)==digest(admitted.hardware.mass_properties)
    assert digest(a.construction.branches)==digest(admitted.construction.branches) # loss destinations unchanged

def test_zero_resolved_route_mass_still_requires_positive_cp_and_full_coverage(project,admitted):
    line_id=next(b.line_id for b in admitted.construction.branches if b.polyline_length_m==0.)
    base=project.specification.base
    cfg=replace(base.configuration,lines=tuple(replace(l,slack_m=0.,wire=replace(l.wire,connector_mass_kg=0.))if l.line_id==line_id else l for l in base.configuration.lines))
    aug=replace(base.augmentation,routes=tuple(replace(x,slack_point=None)if x.line_id==line_id else x for x in base.augmentation.routes))
    a=paid(replace(project.specification,base=replace(base,configuration=cfg,augmentation=aug)),project.common)
    assert next(m for line,m,n,cp in a.route_thermal.per_line if line==line_id)==0
    assert len(a.route_thermal.per_line)==8

@pytest.mark.parametrize('cp',[0.,-1.,float('inf'),float('nan'),1e9,1e-13,385,True,'385'])
def test_exact_finite_positive_builtin_cp(project,cp):
    with pytest.raises((ValueError,TypeError)):replace(project.specification.route_thermal[0],specific_heat_j_per_kg_k=cp)

@pytest.mark.parametrize('kind',['missing','duplicate','foreign-line','foreign-node','foreign-provenance'])
def test_declaration_coverage_refusals_precede_compilation(project,kind):
    ds=project.specification.route_thermal
    with pytest.raises((ValueError,TypeError)):
        if kind=='missing':ds=ds[:-1]
        elif kind=='duplicate':ds=ds[:-1]+(ds[0],)
        elif kind=='foreign-line':ds=(replace(ds[0],line_id='foreign'),)+ds[1:]
        elif kind=='foreign-node':ds=(replace(ds[0],thermal_node_id='foreign'),)+ds[1:]
        else:ds=(replace(ds[0],provenance='ASSUMED'),)+ds[1:]
        replace(project.specification,route_thermal=ds)

def test_constructor_refusal_does_not_refund_and_no_unpaid_first_pass(project):
    ledger=ConstructorLedger(maximum_compiles=1)
    with pytest.raises(ValueError,match='CONSTRUCTOR_ADMISSION'):admit_design_v2(project.specification,project.common,ledger)
    assert ledger.compiles==1 and ledger.control_reserved==16*2**20

def test_v3_closed_codec_and_legacy_strict_controls(project):
    from ops_sim.v5.spacecraft_project_v2_document import loads_project as old
    text=dumps_project(project);assert dumps_project(loads_project(text))==text
    with pytest.raises(ValueError):old(text)
    doc=json.loads(text);row=doc['inputs']['specification']['fields']['route_thermal']['design_tuple'][0]
    for key in ('mass_kg','capacity','compiled_result'):
        changed=deepcopy(doc);changed['inputs']['specification']['fields']['route_thermal']['design_tuple'][0]['fields'][key]=1.
        from ops_sim.v5.project_workbench import edited_design_document
        raw=edited_design_document(json.dumps(changed),rebuild_outer_digest=True)
        with pytest.raises(ValueError):loads_project(raw)
    from b68_cases import FIXTURES
    original=(FIXTURES/'b68-r3-user-composition.core-project-v2.json').read_text('utf8')
    from ops_sim.v5.spacecraft_project_v2_document import dumps_project as old_dump
    assert old_dump(old(original))==original

def test_v3_owner_mutation_refused_by_codec_exit(project):
    from ops_sim.v5.prepared_input_codec import PreparedInputCodec
    original=RouteThermalDeclaration.__post_init__
    try:
        with pytest.raises(ValueError,match='drift'):
            with PreparedInputCodec():RouteThermalDeclaration.__post_init__=lambda self:None
    finally:RouteThermalDeclaration.__post_init__=original

def test_public_store_preview_create_reopen_edit_and_short_guard(project,tmp_path):
    from ops_sim.v5.project_store import ProjectStore
    from ops_sim.v5.project_runner import ProjectRunner
    from ops_sim.v5.lifecycle_application import LifecycleWorkspace
    store=ProjectStore(tmp_path/'projects',project.reference,create=True);rec=store.create(project)
    assert store.load_document(dumps_project(project))['revision']==rec['revision']
    assert store.snapshot()['projects'][0]['project_format']=='KAZEOSAT_SPACECRAFT_PROJECT_V3'
    before={p.relative_to(store.root).as_posix():p.read_bytes()for p in store.root.rglob('*')if p.is_file()}
    runner=ProjectRunner(store)
    with pytest.raises(ValueError,match='GENERAL_PROJECT_REQUIRES_FULL_LIFECYCLE_DISPATCH'):runner.submit(rec['project_id'],rec['revision'],'1'*32)
    assert before=={p.relative_to(store.root).as_posix():p.read_bytes()for p in store.root.rglob('*')if p.is_file()}
    preview=store.preview(rec['project_id'],rec['revision']);assert preview['constructor_work']['compiles']==2
    assert preview['route_thermal']['method']==project.specification.method
    workspace=LifecycleWorkspace(tmp_path/'life',project_store=store)
    snap=workspace.create_design_project(dict(project_id=rec['project_id'],revision=rec['revision']))
    assert store.meta['constructor']['compiles']==4
    owned=workspace.store(snap['root_identity']);assert owned._design_lineage_constructor_work['compiles']==2
    assert owned.meta['project']['format']=='B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1'
    assert workspace.create_design_project(dict(project_id=rec['project_id'],revision=rec['revision']))['root_identity']==snap['root_identity']
    assert store.meta['constructor']['compiles']==4
    owned.close_publications()
    fresh=LifecycleWorkspace(tmp_path/'life');opened=fresh.store(snap['root_identity'])
    assert opened._design_lineage_constructor_work['compiles']==2 and opened.jobs()==[]
    opened.close_publications()
    changed=replace(project,title='Edited route project');edit=store.edit_document(rec['project_id'],rec['revision'],dumps_project(changed))
    assert store.current_preview(rec['project_id'],edit['revision'])is None

def test_v3_named_initial_envelope_is_distinct_and_strict(project):
    from pathlib import Path
    from ops_sim.v5.general_project_job import GeneralProjectExecution,dumps_named_project,loads_named_project,ENVELOPE
    from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,QUALIFICATION
    policy=LifetimeCampaignPolicyV2(mode=QUALIFICATION,maximum_primary_segments=2,reserved_diagnostic_slots=2,
        hard_seconds=60,soft_seconds=30,finalization_seconds=30,maximum_observed_primary_seconds=124,
        maximum_diagnostic_seconds=124,maximum_journal_records=128)
    receipt=(Path(__file__).resolve().parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes()
    option=GeneralProjectExecution(policy,receipt)
    raw=dumps_named_project(project,option);p,e=loads_named_project(raw)
    assert dumps_named_project(p,e)==raw and dumps_project(p)==dumps_project(project)
    value=json.loads(raw);assert value['format']=='B68_NAMED_ROUTE_THERMAL_PROJECT_ENVELOPE_V1'
    value['format']=ENVELOPE
    from ops_sim.v5.portable_job import canonical
    with pytest.raises(ValueError,match='family mismatch'):loads_named_project(canonical(value))

# Reuse the established side-effect/HTTP/worker checks with a genuinely V3
# project fixture. These are separate family cases, not implementation mirrors.
from test_project_b67_dispatch import (test_refusal_precedes_any_intent_job_quota_or_launch,
    test_http_routes_cannot_bypass_guard,test_worker_defense_before_journal_or_materialization)

@pytest.fixture
def general(project,tmp_path):
    from ops_sim.v5.project_store import ProjectStore
    store=ProjectStore(tmp_path/'v3-dispatch',project.reference,create=True)
    return store,store.create(project),project
