"""B53 declared study compilation, not a month or flight qualification."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import pytest

from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_study import (LifecycleStudyInput, StudyThermalNode,
    common_study_input, study_to_data, study_from_data, compile_study_base,
    validate_study_base, study_provenance)
from ops_sim.v5.construction_coupling import digest
from ops_sim.v5.environment_forcing import _case
from ops_sim.v5.provenance import ProvenanceClass


@lru_cache(maxsize=1)
def original():
    return make_inputs(wire='nominal')


@lru_cache(maxsize=1)
def compiled():
    return compile_study_base(original(),common_study_input())


def test_strict_study_wire_roundtrip_units_and_identity():
    study=common_study_input();document=study_to_data(study)
    assert study_from_data(document)==study
    assert study_from_data(document).content_digest==study.content_digest
    assert document['scalars']['calendar_damage_per_second']['units']=='1/s'
    assert document['scalars']['cycling_damage_per_normalized_throughput']['units']=='1'
    assert document['nodes'][0]['parameters']['heat_capacity_j_per_k']['units']=='J/K'


@pytest.mark.parametrize('mutation',('units','extra','nan','number','subtype','node','scope','domain'))
def test_study_wire_rejects_ambiguous_or_unbounded_values(mutation):
    data=deepcopy(study_to_data(common_study_input()))
    if mutation=='units':data['scalars']['calendar_damage_per_second']['units']='1/day'
    elif mutation=='extra':data['ignored']=True
    elif mutation=='nan':data['scalars']['calendar_damage_per_second']['value_hex']='nan'
    elif mutation=='number':data['scalars']['housekeeping_w']['value_hex']=4.
    elif mutation=='subtype':data['latency_seconds']=True
    elif mutation=='node':data['nodes'][1]['role']='BUS'
    elif mutation=='scope':data['provenance']='FLIGHT_CALIBRATED'
    else:data['maximum_duration_seconds']=15*31557600+1
    with pytest.raises((TypeError,ValueError)):study_from_data(data)


@pytest.mark.parametrize('change',({'housekeeping_w':0.},{'calendar_damage_per_second':0.},
    {'cycling_damage_per_normalized_throughput':0.},{'solar_retention_loss_per_second':0.},
    {'ageing_multiplier':0.},{'initial_energy_fraction':True},{'initial_temperature_k':float('inf')}))
def test_common_study_keeps_nonzero_plant_and_ageing(change):
    with pytest.raises((TypeError,ValueError)):replace(common_study_input(),**change)


def test_one_time_compiler_updates_every_thermal_binding_without_hardware_change():
    old=original();new=compiled();study=common_study_input()
    assert new.initial_checkpoint.spacecraft.battery_energy_wh==new.model.simulation_inputs.spacecraft_configuration.eps.battery.nominal_energy_wh.value*.8
    assert new.model.assembly is old.model.assembly
    assert new.model.catalog is old.model.catalog
    assert new.model.protection is old.model.protection
    assert new.model.routing is old.model.routing
    assert new.model.transmitter is old.model.transmitter
    assert new.model.actuator is old.model.actuator
    assert new.model.configuration.lines==old.model.configuration.lines
    assert new.model.configuration.thermal_network==new.model.simulation_inputs.spacecraft_configuration.thermal.network
    assert new.model.configuration.thermal_boundaries==_case(new.model.environment.profile[0],False).thermal_inputs
    assert new.model.augmentation.construction_digest==digest(new.model.configuration)
    assert new.model.augmentation.routes==old.model.augmentation.routes
    assert validate_study_base(new,study)==study.content_digest
    assert all(n.emissivity.provenance.classification is ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
        for n in new.model.configuration.thermal_network.nodes)
    assert all(n.emissivity.provenance.source_ids==() for n in new.model.configuration.thermal_network.nodes)


def test_declared_initial_estimate_matches_new_original_initial_state():
    new=compiled();cp=new.initial_checkpoint;resources=new.initial_estimate.resources
    assert cp.simulation_time_seconds==128 and cp.diagnostics.completed_steps==0
    assert resources.battery_energy_wh==cp.spacecraft.battery_energy_wh
    assert resources.observed_temperatures==cp.spacecraft.thermal.node_states
    assert resources.battery_retention==cp.spacecraft.degradation.battery.usable_capacity_retention==1.
    assert resources.solar_retention==cp.spacecraft.degradation.solar.generation_retention==1.
    assert resources.throughput_wh==cp.spacecraft.degradation.battery.cumulative_energy_throughput_wh==0.
    assert all(n.temperature_k==300. for n in cp.spacecraft.thermal.node_states)
    # Strict original native restore validates units/state without numerical evolution.
    assert cp.restore(new.model.simulation_inputs).simulation_time_seconds==128


def test_predeclared_ageing_sensitivity_changes_authority_not_hardware_or_heat():
    study=common_study_input();sensitive=replace(study,ageing_multiplier=2.)
    new=compile_study_base(original(),sensitive);nominal=compiled()
    age=new.model.simulation_inputs.spacecraft_configuration.degradation.battery_ageing_model
    old=nominal.model.simulation_inputs.spacecraft_configuration.degradation.battery_ageing_model
    assert age.calendar_damage_rate_per_second_at_reference.value==2*old.calendar_damage_rate_per_second_at_reference.value
    assert age.cycling_damage_per_normalized_energy_throughput_at_reference.value==2*old.cycling_damage_per_normalized_energy_throughput_at_reference.value
    assert new.model.solar_retention_loss_per_second==2*nominal.model.solar_retention_loss_per_second
    assert tuple((n.heat_capacity_j_per_k.value,n.radiating_area_m2.value,n.emissivity.value)
        for n in new.model.configuration.thermal_network.nodes)==tuple(
        (n.heat_capacity_j_per_k.value,n.radiating_area_m2.value,n.emissivity.value)
        for n in nominal.model.configuration.thermal_network.nodes)
    assert sensitive.content_digest!=study.content_digest
    assert study_provenance(study)['limiting_cases']['calendar_reference_30days']==.0002592


def test_rate_provenance_keeps_exact_domain_without_expanding_legacy_input_codec():
    study=common_study_input()
    age=compiled().model.simulation_inputs.spacecraft_configuration.degradation.battery_ageing_model
    parameter=age.calendar_damage_rate_per_second_at_reference
    assert parameter.provenance.sensitivity_range is None
    assert (study.calendar_damage_per_second*.125).hex() in parameter.provenance.rationale
    assert (study.calendar_damage_per_second*8.).hex() in parameter.provenance.rationale
    assert parameter.units in parameter.provenance.rationale
    assert 'multiplier domain [0.125,8]' in parameter.provenance.rationale


def test_compiler_refuses_advanced_or_nonempty_initial_authority():
    old=original();cp=replace(old.initial_checkpoint,diagnostics=replace(old.initial_checkpoint.diagnostics,completed_steps=1))
    # Deliberately bypass only the high-level wrapper constructor to exercise
    # compiler admission of a hostile already-typed object. No dynamics run.
    reference=object.__new__(type(old.reference))
    for name in old.reference.__dataclass_fields__:
        object.__setattr__(reference,name,cp if name=='initial_checkpoint' else getattr(old.reference,name))
    base=object.__new__(type(old))
    for name in old.__dataclass_fields__:
        object.__setattr__(base,name,reference if name=='reference' else getattr(old,name))
    with pytest.raises(ValueError,match='ORIGINAL_EMPTY_INITIAL_BOUNDARY_ONLY'):
        compile_study_base(base,common_study_input())


def test_original_b52_demo_is_not_silently_rewritten():
    old=original();new=compiled()
    assert old.model.environment!=new.model.environment
    assert old.model.simulation_inputs.spacecraft_configuration!=new.model.simulation_inputs.spacecraft_configuration
    assert old.initial_checkpoint!=new.initial_checkpoint
    assert old.model.environment.profile[0].loads.base_bus_w==2.
    assert all(n.emissivity.value==0. for n in old.model.configuration.thermal_network.nodes)


def test_base_binding_rejects_uncompiled_or_stale_coefficients():
    with pytest.raises(ValueError,match='binding'):validate_study_base(original(),common_study_input())
    with pytest.raises(ValueError,match='binding'):validate_study_base(compiled(),replace(common_study_input(),housekeeping_w=5.))
