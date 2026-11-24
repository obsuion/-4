from dataclasses import replace,asdict
from fractions import Fraction
from math import ulp
import pytest
from examples.m7_design_repair_demo import make_spec
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.design_repair import (ConstructorLedger,compile_catalogue,payload_area,
    DesignRepairSpec,propose_repairs,source_identity)
from ops_sim.v5.rolling_physics import digest
from ops_sim.v5.mission_diagnosis import MissionDiagnosis,DiagnosisFinding


def test_all_eight_input_roots_are_independent_and_common_mission():
    spec=make_spec();work=ConstructorLedger();cat=compile_catalogue(spec,work)
    assert len(cat)==8 and len({v.manifest.candidate_root_identity for v in cat})==8
    assert work.compiles==8 and work.control_reserved==8*16*2**20
    assert cat[0].manifest.kind=='BASELINE_IDENTITY' and digest(cat[0].root)==digest(spec.reference)
    assert cat[1].manifest.kind=='PAYLOAD_WIRE_CROSS_SECTION'
    assert cat[4].manifest.kind=='ASSEMBLY_PLACEMENT'
    assert cat[5].manifest.kind=='COMBINED_PLACEMENT_AND_PAYLOAD_AREA'
    for v in cat:
        r=v.root
        for n in ('initial_checkpoint','initial_quaternion','requests','contacts','knowledge_mode','initial_estimate','policy','quotas'):
            assert getattr(r,n)==getattr(spec.reference,n)
        assert r.estimation==spec.reference.estimation and r.controller_method==spec.reference.controller_method
        assert r.model.environment==spec.reference.model.environment
        assert r.model.protection==spec.reference.model.protection
        assert r.model.assembly.definitions==spec.reference.model.assembly.definitions
        assert r.model.assembly.instances==spec.reference.model.assembly.instances
        assert payload_area(r.model)==v.manifest.payload_area_m2
        mass=v.hardware.augmentation
        assert mass.effective_mass_exact_kg==Fraction(mass.base_mass_properties.total_mass_kg)+sum(c.mass_kg for c in mass.contributions)
        assert len({c.coverage for c in mass.contributions})==len(mass.contributions)
        I=v.hardware.mass_properties.inertia_com_body_kg_m2
        assert all(I[i][j]==I[j][i] for i in range(3) for j in range(3))


@pytest.mark.parametrize('index,name,wire',[(0,'compact','weakness'),(1,'compact','repair'),(4,'outboard','weakness'),(5,'outboard','repair')])
def test_existing_numeric_constructor_compatibility(index,name,wire):
    cat=compile_catalogue(make_spec(),ConstructorLedger())
    assert digest(cat[index].root)==digest(make_inputs(name,wire=wire))


def test_area_mass_delta_has_independent_two_conductor_reference():
    cat=compile_catalogue(make_spec(),ConstructorLedger());a,b=cat[:2]
    branch=next(x for x in a.construction.branches if x.line_id=='payload-line')
    line=next(x for x in a.root.model.configuration.lines if x.line_id=='payload-line')
    expected=2*line.wire.density_kg_m3*(1e-6-1e-10)*(branch.polyline_length_m+line.slack_m)
    actual=b.hardware.mass_properties.total_mass_kg-a.hardware.mass_properties.total_mass_kg
    # Both total masses are rounded binary64; subtracting them contributes at
    # most two total-mass ULPs, plus the independently formed conductor sum.
    assert abs(actual-expected)<=4*ulp(b.hardware.mass_properties.total_mass_kg)
    assert b.hardware.mass_properties.center_body_m!=a.hardware.mass_properties.center_body_m
    assert cat[5].hardware.tensor_exact!=b.hardware.tensor_exact


def test_constructor_admission_precedes_compilation(monkeypatch):
    import ops_sim.v5.design_repair as owner
    w=ConstructorLedger(maximum_compiles=1,compiles=1,control_reserved=16*2**20)
    monkeypatch.setattr(owner,'compile_construction',lambda *a:pytest.fail('entered compile after exhausted constructor'))
    with pytest.raises(ValueError,match='CONSTRUCTOR_ADMISSION'):owner.rebuild_model(make_inputs(wire='weakness'),'outboard',1e-6,w)


@pytest.mark.parametrize('areas',[(1e-10,1e-10),(1e-10,True),(1e-10,float('nan')),(1e-10,1.),(1e-6,)])
def test_bad_or_nonbaseline_catalogue_rejects(areas):
    with pytest.raises((ValueError,TypeError)):replace(make_spec(),payload_areas_m2=areas)


def test_planner_preserves_forecast_scope_and_unknown_timeout():
    spec=make_spec();cat=compile_catalogue(spec,ConstructorLedger())
    f=DiagnosisFinding('f','FORECAST','FULL_ELECTRICAL_SERVICE','d','a','r',128,
        'FULL_ELECTRICAL_SERVICE_UNAVAILABLE','predicted screening only',())
    diag=MissionDiagnosis('M6_TYPED_RETURNED_EVIDENCE_DIAGNOSIS_V1',digest(spec.reference),digest(spec.reference.model),
        digest(spec.reference.model.assembly),'c',spec.reference.controller_method,spec.reference.estimation.method,1,(f,))
    p=propose_repairs(spec,cat,diag)
    assert p and p[0].evidence_scope=='FORECAST' and p[0].status=='PROPOSAL_ONLY_NO_EXECUTION_GRANT'
    manifests={v.manifest.variant_identity:v.manifest for v in cat}
    for proposal in p:
        for identity in proposal.candidate_variant_ids:
            assert proposal.edited_fields==manifests[identity].edited_fields
            assert proposal.intervention_kind==manifests[identity].kind
    assert propose_repairs(spec,cat,replace(diag,findings=(replace(f,scope='OWNED_PROCESS_TIMEOUT',category='UNKNOWN_OWNER_SUBCAUSE'),)))==()
    with pytest.raises(ValueError):propose_repairs(spec,cat,replace(diag,root_identity='0'*64))
