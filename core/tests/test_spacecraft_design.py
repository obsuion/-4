"""Supported arbitrary assembly -> actual static plant; no mission evaluations.

The portable common V7 input is archived authority, not a numerical checkpoint.
All hardware additions below are explicitly ASSUMED test declarations.
"""
from dataclasses import replace
from math import fsum
from pathlib import Path

import pytest

from ops_sim.v5.assembly import MassCoverage, MountPose, UniformCuboid, UNIFORM_CUBOID
from ops_sim.v5.assembly_choices import PhysicalInstance, PlacementChoice, Selection, InstallationBox, assess_design
from ops_sim.v5.lifecycle_document import loads_root, dumps_root
from ops_sim.v5.design_repair import ConstructorLedger
from ops_sim.v5.spacecraft_design import (DesignSpecification, DesignProvenance, ThermalPart,
    admit_design, admit_compiled_design, specification_from_root)


@pytest.fixture(scope='module')
def common():
    return loads_root((Path(__file__).parent/'fixtures/b66_common_initial.json').read_bytes())


@pytest.fixture(scope='module')
def specification(common):
    return specification_from_root(common)


def add_structural_part(specification, instance_id, ordinal=0):
    """An authored additional cuboid with disjoint declared installation/mass."""
    assembly = specification.assembly
    definition = UniformCuboid('user-bracket-' + instance_id, 'LOCAL-' + instance_id,
        .01, (.02, .03, .04), (0., 0., 0.), UNIFORM_CUBOID)
    position = (.6 + .16*(ordinal % 8), .6 + .16*(ordinal // 8), .4)
    rotation = ((.6, -.8, 0.), (.8, .6, 0.), (0., 0., 1.))
    choice_id = 'user-mount-' + instance_id
    pose = MountPose(choice_id, choice_id, assembly.body_frame_id,
        definition.local_frame_id, position, rotation, (instance_id,))
    region = assembly.allowed_regions[0].region_id
    choice = PlacementChoice(choice_id, definition.definition_id, (instance_id,), pose,
        InstallationBox(tuple(x-.03 for x in position), tuple(x+.03 for x in position)), region, True)
    instance = PhysicalInstance(instance_id, definition.definition_id,
        MassCoverage((('user-declared-parts', instance_id),)))
    assembly = replace(assembly, definitions=assembly.definitions + (definition,),
        instances=assembly.instances + (instance,), choices=assembly.choices + (choice,),
        selections=assembly.selections + (Selection(instance_id, choice_id),))
    node = next(p.node_id for p in specification.thermal_parts if p.instance_id == 'core')
    part = ThermalPart(instance_id, node, 500., .001, .75,
        DesignProvenance('ASSUMED', (), 'Synthetic user bracket: declared material and exposed area.'))
    return replace(specification, assembly=assembly,
        thermal_parts=specification.thermal_parts + (part,))


def clone_functional_part(specification, template_id, instance_id, shift, role):
    """Identical electrical/PV module, separately owned physical instance."""
    assembly = specification.assembly
    original = next(i for i in assembly.instances if i.instance_id == template_id)
    selected = next(s.choice_id for s in assembly.selections if s.instance_id == template_id)
    choice = next(c for c in assembly.choices if c.choice_id == selected)
    choice_id = 'mount-' + instance_id
    envelope = replace(choice.envelope,
        lower_m=tuple(x+d for x, d in zip(choice.envelope.lower_m, shift)),
        upper_m=tuple(x+d for x, d in zip(choice.envelope.upper_m, shift)))
    pose = replace(choice.pose, mount_id=choice_id, choice_id=choice_id,
        origin_body_m=tuple(x+d for x, d in zip(choice.pose.origin_body_m, shift)),
        occupied_slots=(instance_id,))
    choice = replace(choice, choice_id=choice_id, allowed_instance_ids=(instance_id,),
        pose=pose, envelope=envelope)
    instance = replace(original, instance_id=instance_id,
        mass_coverage=MassCoverage((('user-declared-parts', instance_id),)))
    assembly = replace(assembly, instances=assembly.instances + (instance,),
        choices=assembly.choices + (choice,), selections=assembly.selections + (Selection(instance_id, choice_id),))
    part = next(p for p in specification.thermal_parts if p.instance_id == template_id)
    updates = dict(assembly=assembly, thermal_parts=specification.thermal_parts + (replace(part, instance_id=instance_id),))
    if role == 'battery':
        module = next(b for b in specification.batteries if b.instance_id == template_id)
        updates['batteries'] = specification.batteries + (replace(module, instance_id=instance_id),)
    elif role == 'pv':
        module = next(p for p in specification.pv_modules if p.instance_id == template_id)
        updates['pv_modules'] = specification.pv_modules + (replace(module, instance_id=instance_id),)
    else:
        raise AssertionError('test helper requires explicit physical role')
    return replace(specification, **updates)


def moved_camera(specification):
    assembly = specification.assembly
    camera = next(i for i in assembly.instances if i.instance_id == 'camera')
    definitions = tuple(replace(d, mass_kg=d.mass_kg*2., center_local_m=(.01, -.02, .03),
        size_m=(.12, .08, .1)) if d.definition_id == camera.definition_id else d for d in assembly.definitions)
    selected = next(s.choice_id for s in assembly.selections if s.instance_id == camera.instance_id)
    origin = (.12, .44, .07)
    rotation = ((.6, -.8, 0.), (.8, .6, 0.), (0., 0., 1.))
    choices = tuple(replace(c, pose=replace(c.pose, origin_body_m=origin,
        rotation_body_from_local=rotation),
        envelope=InstallationBox(tuple(x-.07 for x in origin), tuple(x+.07 for x in origin)))
        if c.choice_id == selected else c for c in assembly.choices)
    return replace(specification, assembly=replace(assembly, definitions=definitions, choices=choices))


def thermal_node(root, role):
    network = root.base.model.simulation_inputs.spacecraft_configuration.thermal.network
    selected = getattr(network, role + '_node_id')
    return next(n for n in network.nodes if n.node_id == selected)


def test_seed_derives_full_effective_hardware_and_preserves_common_authority(common, specification):
    before = dumps_root(common)
    ledger = ConstructorLedger(maximum_compiles=32)
    admitted = admit_design(specification, common, ledger)
    assert ledger.compiles == 1 and ledger.control_reserved == 16*2**20
    assert admitted.specification_identity == specification.identity
    assert admitted.common_identity == common.identity
    assert admitted.root.base.model.assembly == specification.assembly
    assert len(admitted.hardware.mass_properties.inertia_com_body_kg_m2) == 3
    assert admitted.root.scenario == common.scenario and admitted.root.policy == common.policy
    assert admitted.root.base.requests == common.base.requests
    assert admitted.root.base.model.environment == common.base.model.environment
    assert dumps_root(common) == before


def test_thirteen_unique_user_specs_are_admitted_without_preset_ids(common, specification):
    ledger = ConstructorLedger(maximum_compiles=32)
    roots = []
    for ordinal in range(13):
        spec = add_structural_part(specification, 'user-arbitrary-' + str(ordinal))
        roots.append(admit_design(spec, common, ledger).root.identity)
    assert len(set(roots)) == 13 and ledger.compiles == 13


@pytest.mark.parametrize('count', (13, 32))
def test_more_than_twelve_components_up_to_explicit_32_cap(common, specification, count):
    spec = specification
    for index in range(count-len(specification.assembly.instances)):
        spec = add_structural_part(spec, 'independent-' + str(index), index)
    result = admit_design(spec, common, ConstructorLedger(maximum_compiles=32))
    assert len(result.root.base.model.assembly.instances) == count
    assert result.hardware.mass_properties.total_mass_kg > result.hardware.base_hardware.mass_properties.total_mass_kg


def test_33rd_component_refused_at_declared_engine_domain(specification):
    spec = specification
    for index in range(32-len(specification.assembly.instances)):
        spec = add_structural_part(spec, 'independent-' + str(index), index)
    with pytest.raises(ValueError, match='32-entry'):
        add_structural_part(spec, 'over-cap', 27)


def test_noncardinal_pose_com_offset_mass_full_tensor_and_route_are_consumed(common, specification):
    original = admit_design(specification, common, ConstructorLedger(maximum_compiles=32))
    changed = admit_design(moved_camera(specification), common, ConstructorLedger(maximum_compiles=32))
    a, b = original.hardware, changed.hardware
    assert a.mass_properties.total_mass_kg != b.mass_properties.total_mass_kg
    assert a.mass_properties.center_body_m != b.mass_properties.center_body_m
    assert a.mass_properties.inertia_com_body_kg_m2 != b.mass_properties.inertia_com_body_kg_m2
    assert any(a.mass_properties.inertia_com_body_kg_m2[i][j] != b.mass_properties.inertia_com_body_kg_m2[i][j]
        for i in range(3) for j in range(3) if i != j)
    assert a.camera_body_axis != b.camera_body_axis
    assert original.construction.branches != changed.construction.branches
    camera = next(c for c in assess_design(b.base_hardware.design).assembly.components if c.component_id == 'camera')
    assert camera.center_body_m == tuple(fsum((camera.mount_pose.origin_body_m[i],
        fsum(camera.rotation_body_from_local[i][j]*camera.definition.center_local_m[j] for j in range(3)))) for i in range(3))


def test_identical_parallel_battery_multiplicity_changes_all_declared_owners(common, specification):
    spec = clone_functional_part(specification, 'battery-left', 'third-bank-module', (.8, 0., 0.), 'battery')
    spec = clone_functional_part(spec, 'battery-right', 'fourth-bank-module', (-.8, 0., 0.), 'battery')
    a = admit_design(specification, common, ConstructorLedger(maximum_compiles=32)).root
    b = admit_design(spec, common, ConstructorLedger(maximum_compiles=32)).root
    old = a.base.model.simulation_inputs.spacecraft_configuration.eps.battery
    new = b.base.model.simulation_inputs.spacecraft_configuration.eps.battery
    for name in ('nominal_energy_wh', 'max_charge_input_power_w', 'max_discharge_output_power_w'):
        assert getattr(new, name).value == 2.*getattr(old, name).value
    assert b.battery_port_policy.resistance_reference_ohm == a.battery_port_policy.resistance_reference_ohm/2.
    assert b.battery_port_policy.cycling_damage_per_chemical_wh == a.battery_port_policy.cycling_damage_per_chemical_wh/2.
    for name in ('maximum_charge_current_a', 'maximum_discharge_current_a', 'maximum_charge_bus_w', 'maximum_discharge_bus_w'):
        assert getattr(b.battery_port_policy, name) == 2.*getattr(a.battery_port_policy, name)
    assert thermal_node(b, 'battery').heat_capacity_j_per_k.value == 2.*thermal_node(a, 'battery').heat_capacity_j_per_k.value
    assert b.base.initial_checkpoint.spacecraft.battery_energy_wh == 2.*a.base.initial_checkpoint.spacecraft.battery_energy_wh
    assert b.base.initial_estimate.resources.battery_energy_wh == b.base.initial_checkpoint.spacecraft.battery_energy_wh


def test_coplanar_pv_multiplicity_changes_generation_mass_and_thermal(common, specification):
    panel = specification.pv_modules[0].instance_id
    spec = clone_functional_part(specification, panel, 'user-second-array', (1., 0., 0.), 'pv')
    a = admit_design(specification, common, ConstructorLedger(maximum_compiles=32))
    b = admit_design(spec, common, ConstructorLedger(maximum_compiles=32))
    old = a.root.base.model.simulation_inputs.spacecraft_configuration.eps.solar_array.nominal_generation_w.value
    new = b.root.base.model.simulation_inputs.spacecraft_configuration.eps.solar_array.nominal_generation_w.value
    assert new == 2.*old and b.hardware.mass_properties.total_mass_kg > a.hardware.mass_properties.total_mass_kg
    assert b.hardware.panel_body_normal == a.hardware.panel_body_normal
    panel_node_id = next(p.node_id for p in specification.thermal_parts if p.instance_id == panel)
    def node(result):
        return next(n for n in result.root.base.model.configuration.thermal_network.nodes if n.node_id.value == panel_node_id)
    assert node(b).heat_capacity_j_per_k.value > node(a).heat_capacity_j_per_k.value
    assert node(b).radiating_area_m2.value > node(a).radiating_area_m2.value


def test_heterogeneous_parallel_battery_and_opposing_pv_normals_refuse(common, specification):
    mixed = replace(specification, batteries=tuple(replace(b, nominal_energy_wh=b.nominal_energy_wh+1.)
        if index else b for index, b in enumerate(specification.batteries)))
    with pytest.raises(ValueError, match='HETEROGENEOUS'):
        admit_design(mixed, common, ConstructorLedger(maximum_compiles=32))
    panel = specification.pv_modules[0].instance_id
    opposing = clone_functional_part(specification, panel, 'opposing-array', (1., 0., 0.), 'pv')
    opposing = replace(opposing, pv_modules=tuple(replace(p, normal_local=tuple(-x for x in p.normal_local))
        if p.instance_id == 'opposing-array' else p for p in opposing.pv_modules))
    with pytest.raises(ValueError, match='NONCOORIENTED'):
        admit_design(opposing, common, ConstructorLedger(maximum_compiles=32))


def test_missing_thermal_and_double_functional_ownership_refuse(specification):
    with pytest.raises(ValueError, match='each physical instance'):
        replace(specification, thermal_parts=specification.thermal_parts[:-1])
    with pytest.raises(ValueError, match='disjoint'):
        replace(specification, pv_modules=(replace(specification.pv_modules[0], instance_id=specification.batteries[0].instance_id),))


def test_aggregate_child_mass_overlap_is_not_silently_accepted(common, specification):
    spec = add_structural_part(specification, 'overlapping-owner')
    owner = next(i for i in spec.assembly.instances if i.instance_id == 'core')
    assembly = replace(spec.assembly, instances=tuple(replace(i, mass_coverage=owner.mass_coverage)
        if i.instance_id == 'overlapping-owner' else i for i in spec.assembly.instances))
    with pytest.raises(ValueError, match='INSTALLATION_OR_MASS'):
        admit_design(replace(spec, assembly=assembly), common, ConstructorLedger(maximum_compiles=32))


@pytest.mark.parametrize('change', ({'battery_connection': 'SERIES'}, {'pv_connection': 'ARBITRARY_CIRCUIT'}))
def test_unsupported_circuits_are_explicit_refusals(specification, change):
    with pytest.raises(ValueError, match='unsupported bank/circuit'):
        replace(specification, **change)


def test_declared_pv_area_cannot_exceed_the_actual_cuboid_face(common, specification):
    spec = replace(specification, pv_modules=(replace(specification.pv_modules[0], active_area_m2=10000.),))
    with pytest.raises(ValueError, match='PV_ACTIVE_AREA'):
        admit_design(spec, common, ConstructorLedger(maximum_compiles=32))


def test_advanced_initial_diagnostics_refuse_before_compile(common, specification):
    cp = common.base.initial_checkpoint
    advanced_cp = replace(cp, diagnostics=replace(cp.diagnostics, completed_steps=1))
    command = replace(common.base, reference=replace(common.base.reference, initial_checkpoint=advanced_cp))
    advanced = replace(common, base=command)
    ledger = ConstructorLedger(maximum_compiles=32)
    with pytest.raises(ValueError, match='INITIAL_EMPTY_CUSTODY'):
        admit_design(specification, advanced, ledger)
    assert ledger.compiles == 0


def test_compiler_and_common_authority_are_checked_independently(common, specification):
    compiled = admit_design(specification, common, ConstructorLedger(maximum_compiles=32)).root
    accepted = admit_compiled_design(specification, common, compiled, ConstructorLedger(maximum_compiles=32))
    assert accepted.root.identity == compiled.identity
    foreign = replace(common, scenario=replace(common.scenario, namespace=common.scenario.namespace+'-foreign'))
    with pytest.raises(ValueError, match='COMPILED_DESIGN'):
        admit_compiled_design(specification, foreign, compiled, ConstructorLedger(maximum_compiles=32))
    with pytest.raises(ValueError, match='COMPILED_DESIGN'):
        admit_compiled_design(add_structural_part(specification, 'compiler-drift'), common, compiled, ConstructorLedger(maximum_compiles=32))


def test_compiler_cached_identity_is_not_a_substitute_for_current_input_validation(common, specification):
    compiled = admit_design(specification, common, ConstructorLedger(maximum_compiles=32)).root
    stale = loads_root(dumps_root(compiled))
    object.__setattr__(stale, 'duration_seconds', stale.duration_seconds+1)
    with pytest.raises(ValueError, match='COMPILED_DESIGN|authority|identity|canonical'):
        admit_compiled_design(specification, common, stale, ConstructorLedger(maximum_compiles=32))


def test_declared_payload_rf_and_baseline_functions_feed_existing_plant_owners(common, specification):
    old = specification.functional
    optical = old.payload_configuration.optical_acquisition
    power = optical.acquisition_power_w
    payload = replace(old.payload_configuration, optical_acquisition=replace(optical,
        acquisition_power_w=replace(power, value=power.value*2.)))
    transmitter = replace(old.transmitter, electrical_power_w=replace(old.transmitter.electrical_power_w,
        value=old.transmitter.electrical_power_w.value*1.5))
    functional = replace(old, payload_configuration=payload, transmitter=transmitter,
        baseline_loads=replace(old.baseline_loads, base_bus_w=old.baseline_loads.base_bus_w*2.),
        camera_half_fov_rad=old.camera_half_fov_rad*.75)
    result = admit_design(replace(specification, functional=functional), common, ConstructorLedger())
    model = result.root.base.model
    assert model.simulation_inputs.spacecraft_configuration.payload == payload
    assert model.transmitter == transmitter and model.camera_half_fov_rad == functional.camera_half_fov_rad
    assert all(p.loads == functional.baseline_loads for p in model.environment.profile)
    assert result.root.study.housekeeping_w == functional.baseline_loads.base_bus_w
    assert result.root.scenario == common.scenario


def test_dynamic_loads_cannot_be_declared_twice_and_functional_axis_owns_real_branch(specification):
    with pytest.raises(ValueError, match='double-counted'):
        replace(specification.functional, baseline_loads=replace(specification.functional.baseline_loads, payload_w=1.))
    core = next(c for c in specification.assembly.definitions if c.definition_id == 'core')
    axes = tuple(replace(c, component_id='core', local_frame_id=core.local_frame_id)
        if c.role == 'camera' else c for c in specification.capabilities)
    with pytest.raises(ValueError, match='payload branch'):
        replace(specification, capabilities=axes)


def test_declared_sources_follow_derived_plant_without_becoming_verified(common, specification):
    from ops_sim.v5.ids import SourceRecordId
    from ops_sim.v5.provenance import ProvenanceClass, ProvenanceStatus
    declaration = DesignProvenance('SOURCE', ('user-cell-data',), 'Declared example source, not independently verified here.')
    spec = replace(specification, batteries=tuple(replace(b, provenance=declaration) for b in specification.batteries))
    root = admit_design(spec, common, ConstructorLedger()).root
    parameter = root.base.model.simulation_inputs.spacecraft_configuration.eps.battery.nominal_energy_wh
    assert parameter.provenance.source_ids == (SourceRecordId('user-cell-data'),)
    assert parameter.provenance.classification is ProvenanceClass.DERIVED_VALUE
    assert parameter.provenance.status is ProvenanceStatus.TO_VERIFY
    with pytest.raises(ValueError, match='lowercase ASCII'):
        DesignProvenance('SOURCE', ('Not a typed source ID',), 'invalid authored reference')


def test_thermal_routes_are_admitted_before_a_mission_starts(specification):
    from ops_sim.v5.ids import ThermalNodeId
    from ops_sim.v5.thermal_routing import ElectricalLoadComponent
    routes = specification.functional.routing.routes
    with pytest.raises(ValueError, match='existing declared thermal node'):
        replace(specification, functional=replace(specification.functional,
            routing=replace(specification.functional.routing, routes=tuple(replace(r,
                thermal_node_id=ThermalNodeId('undeclared-node')) if i == 0 else r for i, r in enumerate(routes)))))
    with pytest.raises(ValueError, match='ADCS storage'):
        replace(specification, functional=replace(specification.functional,
            routing=replace(specification.functional.routing, routes=tuple(replace(r,
                retained_heat_fraction=replace(r.retained_heat_fraction, value=.5))
                if r.component is ElectricalLoadComponent.ADCS else r for r in routes))))


def test_pan_only_declaration_does_not_silently_receive_ms_capability(specification):
    from ops_sim.v5.configuration import PayloadMode
    with pytest.raises(ValueError, match='multispectral'):
        replace(specification.functional, payload_configuration=replace(
            specification.functional.payload_configuration, supported_modes=(PayloadMode.PANCHROMATIC,)))


def test_editable_demo_declares_ms_assumption_without_rewriting_legacy_common(common, specification):
    from ops_sim.v5.configuration import PayloadMode
    original = common.base.model.simulation_inputs.spacecraft_configuration.payload
    assert original.supported_modes == (PayloadMode.PANCHROMATIC,)
    assert specification.functional.payload_configuration.supported_modes == (PayloadMode.MULTISPECTRAL,)
    assert specification.provenance.classification == 'ASSUMED'
    assert 'legacy supported_modes PAN' in specification.provenance.rationale
