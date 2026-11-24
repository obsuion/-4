"""The new design contract binds the physical inputs actually consumed."""
from dataclasses import replace
from fractions import Fraction
import json
from math import cos, radians

import pytest

from ops_sim.v5.design_trade_campaign import TradeSpec, build_program, forcing_at, input_digest
from ops_sim.v5.design_trade_design import enumerate_designs, select_designs
from ops_sim.v5.experiment_codec import canonical_content


def spec(**changes):
    return replace(TradeSpec('B2-A2', 'close', 'FULL', 1), **changes)


def test_exact_json_roundtrip_and_identity_changes_with_physical_assumption():
    a=spec()
    assert TradeSpec.from_dict(json.loads(json.dumps(a.to_dict()))) == a
    assert input_digest(a) != input_digest(replace(a,torque_nm=.015))
    assert input_digest(a) != input_digest(replace(a,assumptions=replace(a.assumptions,core_inertia_scale=.75)))


@pytest.mark.parametrize('field,value', [('level',True),('version',True),('mode_factor',2.),
    ('initial_fraction',0.),('torque_nm',float('nan')),('variant','full'),('horizon',1500)])
def test_invalid_contracts_reject(field,value):
    with pytest.raises((ValueError,TypeError)):
        spec(**{field:value})


def test_same_request_and_forcing_world_for_all_designs_and_both_variants():
    reference=None
    for d in select_designs(enumerate_designs()):
        for v in ('FULL','RESOURCE_ONLY'):
            inputs,p,_=build_program(spec(design_id=d.design_id,variant=v))
            common=canonical_content((p.requests,p.opportunities,p.contacts,p.knowledge,p.policy,inputs.common_world))
            if reference is None: reference=common
            assert common==reference


def test_actual_body_rotation_changes_solar_generation_without_free_tracking():
    s=spec();_,p,d=build_program(s)
    _,positive=forcing_at(s,p,d,Fraction(100),radians(30))
    _,negative=forcing_at(s,p,d,Fraction(100),radians(-30))
    assert positive['geometric_incidence']==pytest.approx(cos(radians(10)),abs=2e-16)
    assert negative['geometric_incidence']==pytest.approx(cos(radians(50)),abs=2e-16)
    assert positive['solar_bus_w']>negative['solar_bus_w']
    _,dark=forcing_at(s,p,d,Fraction(29),radians(30))
    assert dark['solar_bus_w']==0.


def test_external_losses_are_counted_once_and_ablation_keeps_regulator():
    for v in ('FULL','RESOURCE_ONLY'):
        s=spec(variant=v);_,p,d=build_program(s)
        wait,x=forcing_at(s,p,d,Fraction(100),radians(30),'hold','imaging')
        assert x['solar_source_w']==pytest.approx(x['solar_bus_w']+x['solar_wire_loss_w']+x['solar_converter_loss_w'],abs=3e-14)
        assert wait.loads.base_bus_w==12.+x['load_wire_loss_w']
        assert wait.loads.adcs_w==.5
        assert wait.loads.payload_w==0. # Accepted acquisition owner adds it.
        assert x['terminal_load_w']==105.5
        assert x['solar_converter_loss_w']>0.
        assert (x['load_wire_loss_w']==0.) == (v=='RESOURCE_ONLY')


def test_derived_thermal_mass_excludes_only_the_deployed_wing():
    s=spec();x,_,d=build_program(s)
    nodes={n.node_id.value:n for n in x.spacecraft_configuration.thermal.network.nodes}
    assert nodes['battery'].heat_capacity_j_per_k.value==d.packs*.486*900.
    assert nodes['payload'].heat_capacity_j_per_k.value==46.*700.
    assert nodes['bus'].heat_capacity_j_per_k.value==(d.total_mass_kg-d.arrays*.650-d.packs*.486-46.)*900.


def test_declared_duration_and_mode_power_are_consumed_without_altering_reference():
    s=spec(exposure_seconds=55,mode_factor=1.5);x,p,d=build_program(s)
    assert all(o.opportunity.imaging_duration_seconds==55 for o in p.opportunities)
    assert all(o.candidate.acquisition_input.imaging_duration_seconds==55 for o in p.opportunities)
    assert x.spacecraft_configuration.payload.optical_acquisition.acquisition_power_w.value==139.5
    assert p.forcing[0].transmitter.electrical_power_w.value==139.5
    assert build_program(spec())[0].spacecraft_configuration.payload.optical_acquisition.acquisition_power_w.value==93.
