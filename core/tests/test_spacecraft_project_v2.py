"""Strict input-only V2 constructor project identity and legacy separation."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from test_spacecraft_design import common, specification, add_structural_part, moved_camera
from ops_sim.v5.spacecraft_project_v2 import (SpacecraftProjectV2, project_from_root,
    materialize_lifecycle_project, preview_project, edit_project)
from ops_sim.v5.spacecraft_project_v2_document import dumps_project, loads_project, FORMAT
from ops_sim.v5.spacecraft_project import project_source_identity
from ops_sim.v5.lifecycle_document import canonical
from ops_sim.v5.design_repair import ConstructorLedger
from ops_sim.v5.rolling_physics import digest


@pytest.fixture(scope='module')
def project(common, specification):
    return SpacecraftProjectV2(common, specification, project_source_identity(), 'Мой спутник: editable composition')


def redigest(data):
    body = {n: data[n] for n in ('format', 'version', 'inputs')}
    data['digest'] = sha256(canonical(body).encode()).hexdigest()
    return canonical(data)


def test_exact_project_roundtrip_and_arbitrary_user_revision(project):
    text = dumps_project(project)
    loaded = loads_project(text, expected_identity=project.identity,
        expected_source_identity=project.source_identity, expected_reference_identity=digest(project.reference))
    assert loaded == project and dumps_project(loaded) == text
    assert json.loads(text)['format'] == FORMAT
    edited = edit_project(project, specification=add_structural_part(project.specification, 'not-a-preset-17'))
    assert edited.identity != project.identity
    assert edited.comparison_identity == project.comparison_identity
    assert loaded.specification.assembly != edited.specification.assembly


def test_title_changes_revision_but_not_common_comparison_identity(project):
    renamed = edit_project(project, title='Independent user design № 1007')
    assert renamed.identity != project.identity
    assert renamed.comparison_identity == project.comparison_identity
    changed = replace(project, requirements=replace(project.requirements, minimum_priority_score=.7))
    assert changed.comparison_identity != project.comparison_identity


def test_materialization_source_binding_refuses_before_constructor_work(project):
    changed = replace(project, source_identity='0'*64)
    ledger = ConstructorLedger(maximum_compiles=32)
    with pytest.raises(ValueError, match='PROJECT_SOURCE_MISMATCH'):
        materialize_lifecycle_project(changed, ledger)
    assert ledger.compiles == 0
    with pytest.raises(ValueError, match='foreign source'):
        loads_project(dumps_project(project), expected_source_identity='0'*64)


def test_project_and_common_lineage_require_exact_expected_identity(project):
    text = dumps_project(project)
    with pytest.raises(ValueError, match='foreign project revision'):
        loads_project(text, expected_identity='0'*64)
    with pytest.raises(ValueError, match='foreign common mission template'):
        loads_project(text, expected_reference_identity='0'*64)


def test_preview_and_materialization_consume_real_general_poses_mass_tensor_routes(project):
    changed = edit_project(project, specification=moved_camera(project.specification))
    a = preview_project(project, ConstructorLedger(maximum_compiles=32))
    b = preview_project(changed, ConstructorLedger(maximum_compiles=32))
    assert a['format'] == b['format'] == 'B66_PAID_GENERAL_DESIGN_PREVIEW_V2'
    assert a['mass_properties'] != b['mass_properties']
    assert a['routes'] != b['routes']
    assert a['root_identity'] != b['root_identity']
    assert a['comparison_identity'] == b['comparison_identity']
    assert a['source_identity'] == b['source_identity'] == project.source_identity
    assert a['grant'] == 'CONSTRUCTOR_PREVIEW_ONLY_NO_MISSION_OR_VISIBILITY_CREDIT'
    assert a['functional_composition']['battery_instances'] == [b.instance_id for b in project.specification.batteries]
    assert all(c['editable_placement'] for c in b['components'])
    root, _, hardware = materialize_lifecycle_project(changed, ConstructorLedger(maximum_compiles=32))
    assert root.base.model.assembly == changed.specification.assembly
    assert hardware.mass_properties.inertia_com_body_kg_m2 == tuple(tuple(row) for row in b['mass_properties']['inertia_com_body_kg_m2'])


def test_legacy_v1_is_read_as_its_own_family_without_silent_conversion(project):
    from examples.m5_command_mission_demo import make_inputs
    from ops_sim.v5.spacecraft_project import SpacecraftProject
    from ops_sim.v5.spacecraft_project_document import dumps_project as dumps_any, loads_project as loads_any
    legacy = SpacecraftProject(make_inputs(wire='weakness'), project_source_identity())
    text = dumps_any(legacy)
    assert type(loads_any(text)) is SpacecraftProject
    assert dumps_any(loads_any(text)) == text
    with pytest.raises(ValueError, match='format/version'):
        loads_project(text)
    assert type(loads_any(dumps_project(project))) is SpacecraftProjectV2


@pytest.mark.parametrize('field', ('cached_tensor', 'score', 'checkpoint', 'receipts', 'callback', 'directory', 'hardware_result'))
def test_output_or_executable_authority_cannot_be_smuggled_as_input(project, field):
    data = json.loads(dumps_project(project))
    data['inputs']['specification']['fields'][field] = None
    with pytest.raises(ValueError):
        loads_project(redigest(data))


@pytest.mark.parametrize('change', ({'placement': 'compact'}, {'payload_area_m2': 1e-8}))
def test_v1_preset_fields_are_not_v2_edits(project, change):
    with pytest.raises(ValueError, match='general specification'):
        edit_project(project, **change)


def test_changed_bytes_need_valid_digest_and_canonical_float_spelling(project):
    data = json.loads(dumps_project(project))
    data['inputs']['title'] = 'Changed without rebind'
    with pytest.raises(ValueError, match='content digest'):
        loads_project(canonical(data))
    data = json.loads(dumps_project(project))
    battery = data['inputs']['specification']['fields']['batteries']['design_tuple'][0]
    battery['fields']['nominal_energy_wh'] = {'design_float': '1.0'}
    with pytest.raises(ValueError, match='canonical finite SI'):
        loads_project(redigest(data))


def test_integer_downgrade_and_33_module_preallocation_refuse(project):
    data = json.loads(dumps_project(project))
    battery = data['inputs']['specification']['fields']['batteries']['design_tuple'][0]
    battery['fields']['nominal_energy_wh'] = 50
    with pytest.raises(ValueError, match='finite binary64'):
        loads_project(redigest(data))
    data = json.loads(dumps_project(project))
    field = data['inputs']['specification']['fields']['batteries']['design_tuple']
    field.extend([field[0]]*(33-len(field)))
    with pytest.raises(ValueError, match='preallocation design cardinality'):
        loads_project(redigest(data))


def test_unknown_existing_owner_and_boolean_version_refuse(project):
    data = json.loads(dumps_project(project))
    data['inputs']['specification']['fields']['assembly'] = {'existing_input': {'rolling_type': 'RuntimeWork', 'fields': {}}}
    with pytest.raises(ValueError):
        loads_project(redigest(data))
    data = json.loads(dumps_project(project))
    data['version'] = True
    with pytest.raises(ValueError, match='format/version'):
        loads_project(redigest(data))


def test_original_common_is_retained_and_no_preset_axes_are_required(common):
    project = project_from_root(common, source_identity=project_source_identity(), title='Not limited to twelve IDs')
    assert project.common is common and project.placement == 'CUSTOM'
    assert project.payload_area_m2 is None
    assert project.specification.initial_usable_energy_fraction >= 0.


def test_requirements_use_actual_recurring_population_not_seed_template_count(project):
    from ops_sim.v5.design_repair import MissionRequirements
    assert project.common.offered_population == 1
    assert project.requirements.minimum_credited_products == 1
    with pytest.raises(ValueError, match='actual recurring'):
        replace(project, requirements=MissionRequirements(minimum_credited_products=2))
    longer = replace(project.common, duration_seconds=3600)
    changed = replace(project, common=longer, requirements=MissionRequirements(minimum_credited_products=4))
    assert changed.common.offered_population == 4
    assert changed.requirements.minimum_credited_products == 4
