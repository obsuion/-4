from dataclasses import replace
import json
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.spacecraft_project import SpacecraftProject,ProjectLimits,project_source_identity,preview_project,edit_project,materialize_project
from ops_sim.v5.spacecraft_project_document import dumps_project,loads_project
from ops_sim.v5.design_repair import ConstructorLedger
from ops_sim.v5.long_mission_document import canonical_json
from hashlib import sha256

@pytest.fixture(scope='module')
def project():return SpacecraftProject(make_inputs(wire='weakness'),project_source_identity())

def test_canonical_input_exact_roundtrip_and_revision(project):
    text=dumps_project(project);loaded=loads_project(text,expected_identity=project.identity,expected_source_identity=project.source_identity)
    assert dumps_project(loaded)==text and loaded==project
    edited=edit_project(project,placement='outboard');assert edited.identity!=project.identity and project.placement=='compact'
    assert edited.comparison_identity==project.comparison_identity

@pytest.mark.parametrize('field',['cached_tensor','receipts','score','advanced_checkpoint','callback','directory'])
def test_unknown_authority_rejects_even_with_correct_document_digest(project,field):
    d=json.loads(dumps_project(project));d['inputs'][field]=None
    d['digest']=sha256(canonical_json({n:d[n] for n in ('format','version','inputs')}).encode()).hexdigest()
    with pytest.raises(ValueError):loads_project(canonical_json(d))

@pytest.mark.parametrize('area',[True,1,1e-9,float('nan')])
def test_unsupported_area_rejects_before_constructor(project,area):
    with pytest.raises((ValueError,TypeError)):replace(project,payload_area_m2=area)

def test_source_and_foreign_template_binding(project):
    with pytest.raises(ValueError,match='source'):loads_project(dumps_project(project),expected_source_identity='0'*64)
    with pytest.raises(ValueError,match='template'):loads_project(dumps_project(project),expected_reference_identity='0'*64)
    ledger=ConstructorLedger(maximum_compiles=32)
    with pytest.raises(ValueError,match='SOURCE'):materialize_project(replace(project,source_identity='0'*64),ledger)
    assert ledger.compiles==0

def test_preview_uses_real_full_tensor_routes_and_mounted_centers(project):
    a=preview_project(project,ConstructorLedger(maximum_compiles=32))
    b=preview_project(replace(project,placement='outboard'),ConstructorLedger(maximum_compiles=32))
    assert a['mass_properties']['inertia_com_body_kg_m2']!=b['mass_properties']['inertia_com_body_kg_m2']
    assert any(a['mass_properties']['inertia_com_body_kg_m2'][i][j]!=b['mass_properties']['inertia_com_body_kg_m2'][i][j] for i in range(3) for j in range(3) if i!=j)
    assert a['routes']!=b['routes'] and b['mass_properties']['total_mass_kg']>a['mass_properties']['total_mass_kg']
    for p in (a,b):
        assert p['constructor_work']['compiles']==1 and p['grant']=='CONSTRUCTOR_PREVIEW_ONLY_NO_MISSION_OR_VISIBILITY_CREDIT'
        for c in p['components']:
            assert len(c['vertices_body_m'])==8
            average=tuple(sum(v[i] for v in c['vertices_body_m'])/8 for i in range(3))
            assert all(abs(average[i]-c['center_body_m'][i])<=8*2**-53*max(1.,abs(average[i])) for i in range(3))
        for mount in p['mount_vectors']:
            c=next(c for c in p['components'] if c['id']==mount['component_id'])
            assert mount['origin_body_m']==c['mount']['origin_body_m']
    assert project.reference==replace(project,placement='outboard').reference

def test_exhausted_constructor_refuses_with_no_new_derived_result(project):
    ledger=ConstructorLedger(maximum_compiles=1);preview_project(project,ledger)
    with pytest.raises(ValueError,match='ADMISSION'):preview_project(project,ledger)
    assert ledger.compiles==1

def test_requirements_and_output_limits_are_explicit(project):
    with pytest.raises(ValueError):replace(project,requirements=replace(project.requirements,minimum_credited_products=4))
    with pytest.raises(ValueError):ProjectLimits(maximum_progress_bytes=1)
    assert replace(project,requirements=replace(project.requirements,minimum_priority_score=.7)).comparison_identity!=project.comparison_identity
