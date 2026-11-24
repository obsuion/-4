from dataclasses import replace,asdict
from fractions import Fraction as Q
from math import fsum
import pytest
from examples.m3_constructor_mission_demo import make_inputs
from ops_sim.v5.environment_mission import (start_environment_mission,advance_environment_mission,
    RuntimeWork,MissionLimits,MissionAction,scientific_projection)
from ops_sim.v5.environment_mission_document import mission_input_digest,mission_inputs_to_json,mission_inputs_from_json
from ops_sim.v5.checkpoint import CheckpointState


@pytest.fixture(scope='module')
def initial():return start_environment_mission(make_inputs())


def copy_state(initial,inputs=None):
    inputs=initial.inputs if inputs is None else inputs
    ctx=inputs.initial_checkpoint.restore(inputs.simulation_inputs)
    return replace(initial,inputs=inputs,context=ctx,attitude=replace(initial.attitude),cursor=0,
        outcomes=(),acquisitions=(),runtime_work=RuntimeWork(upstream_entries=1),input_digest=mission_input_digest(inputs))


def test_actual_paid_slew_capture_custody_and_credit(initial):
    s=copy_state(initial);old=s
    s=advance_environment_mission(s)
    assert s.context.simulation_time_seconds>128 and s.outcomes[0].slew.hardware.mass_properties.total_mass_kg==6.6
    assert s.outcomes[0].cuts and sum((c.end_seconds-c.start_seconds for c in s.outcomes[0].cuts),Q(0))==s.context.simulation_time_seconds-128
    assert any(c.end_seconds==Q(128)+Q(1,3) for c in s.outcomes[0].cuts)
    assert all(c.part.eps_result.loads.adcs_w>0 for c in s.outcomes[0].cuts)
    assert any(c.incidence_angle_deg>90 for c in s.outcomes[0].cuts)
    assert any(c.incidence_angle_deg<90 for c in s.outcomes[0].cuts)
    assert fsum(c.heat_adjustment_w*float(c.end_seconds-c.start_seconds) for c in s.outcomes[0].cuts)==pytest.approx(0.,abs=2**-40)
    with pytest.raises(ValueError,match='STALE'):advance_environment_mission(old)
    s=advance_environment_mission(s)
    assert len(s.context.spacecraft_state.data_storage.stored_records)==1
    assert s.outcomes[-1].acquired_record.stored_equivalent_bits==12288.
    s=advance_environment_mission(s);s=advance_environment_mission(s)
    assert not s.context.spacecraft_state.data_storage.stored_records
    assert len(s.context.ground_data_delivery_state.completed_deliveries)==1
    assert s.assessment().credited_products==1 and s.assessment().completion_time_seconds==Q(168)+Q(12288,1000)
    assert s.outcomes[-1].contact_forcing and len(s.consumed_contacts.contacts)==4
    assert s.context.spacecraft_state.degradation.solar.generation_retention<.8
    assert s.context.spacecraft_state.degradation.battery.usable_capacity_retention<.9
    s=advance_environment_mission(s)
    with pytest.raises(ValueError,match='cursor'):advance_environment_mission(s)
    with pytest.raises(ValueError):advance_environment_mission(copy_state(initial),expected_action_id='contact')


def test_unmet_power_refuses_without_context_mutation(initial):
    d=initial.inputs;cfg=d.simulation_inputs.spacecraft_configuration
    battery=replace(cfg.eps.battery,max_discharge_output_power_w=replace(cfg.eps.battery.max_discharge_output_power_w,value=1.))
    inputs=replace(d,simulation_inputs=replace(d.simulation_inputs,spacecraft_configuration=replace(cfg,eps=replace(cfg.eps,battery=battery))))
    s=copy_state(initial,inputs);before=CheckpointState.from_context(s.context).to_dict()
    denied=advance_environment_mission(s)
    assert denied.outcomes[-1].status=='refused' and denied.outcomes[-1].reason=='FULL_ELECTRICAL_SERVICE_UNAVAILABLE'
    assert denied.context is s.context and CheckpointState.from_context(s.context).to_dict()==before
    assert denied.attitude==s.attitude and denied.runtime_work.physical_completed_calls==1


def test_late_physical_failure_keeps_original_context_and_cursor(initial,monkeypatch):
    import ops_sim.v5.environment_mission as m
    s=copy_state(initial);before=CheckpointState.from_context(s.context).to_dict();real=m._physical_substep;calls=[]
    def fail(*a,**k):
        calls.append(1)
        if len(calls)==2:raise RuntimeError('injected late primitive failure')
        return real(*a,**k)
    monkeypatch.setattr(m,'_physical_substep',fail)
    with pytest.raises(RuntimeError,match='late primitive'):advance_environment_mission(s)
    assert len(calls)==2 and s.cursor==0 and s.outcomes==()
    assert CheckpointState.from_context(s.context).to_dict()==before
    assert s.runtime_work.physical_reserved_calls>0


def test_exhausted_work_and_foreign_input_refused(initial):
    s=copy_state(initial);s.runtime_work.nominal_orbit_queries=s.inputs.limits.max_nominal_orbit_queries
    before=CheckpointState.from_context(s.context).to_dict()
    with pytest.raises(ValueError,match='QUOTA'):advance_environment_mission(s)
    assert CheckpointState.from_context(s.context).to_dict()==before
    s=copy_state(initial);s.inputs=replace(s.inputs,camera_half_fov_rad=.1)
    with pytest.raises(ValueError,match='foreign/modified'):advance_environment_mission(s)


def test_input_only_strict_roundtrip_and_unsafe_nested_type():
    import json
    d=make_inputs();text=mission_inputs_to_json(d)
    assert mission_inputs_to_json(mission_inputs_from_json(text))==text
    bad=json.loads(text);bad['inputs']['simulation_inputs']['typed']['type']='os.system'
    with pytest.raises(ValueError,match='unsafe'):mission_inputs_from_json(json.dumps(bad))
    with pytest.raises((TypeError,ValueError)):MissionLimits(max_actions=True)


def test_heat_ownership_and_original_anchor_are_admitted():
    d=make_inputs()
    node=d.environment.profile[0].nodes[0]
    with pytest.raises(ValueError,match='internal heat'):
        replace(d,environment=replace(d.environment,profile=(replace(d.environment.profile[0],nodes=(replace(node,internal_dissipation_w=1.),*d.environment.profile[0].nodes[1:])),d.environment.profile[1])))
    cp=d.initial_checkpoint.restore(d.simulation_inputs);cp.simulation_time_seconds=129
    with pytest.raises(ValueError,match='anchor'):replace(d,initial_checkpoint=CheckpointState.from_context(cp))


def test_independent_constant_power_and_node_heat_reference(initial):
    from math import pi,ulp
    d=replace(initial.inputs,initial_angle_y_rad=pi,solar_retention_loss_per_second=0.,
        actions=(MissionAction('one-second','HOLD_UNTIL',until_seconds=129),))
    s=copy_state(initial,d);s.attitude=replace(s.attitude,angle_y_rad=pi)
    out=advance_environment_mission(s);cuts=out.outcomes[-1].cuts
    # Prescribed far +x Sun and held +x panel: angular correction <=8e-8 rad,
    # generation correction <=6.4e-14 W; 4 binary64 endpoint ULP cover the
    # two charge additions. Ageing does not trim energy below available capacity.
    assert out.context.spacecraft_state.battery.energy_wh==pytest.approx(80.+.9*14/3600,abs=4*ulp(80.))
    temperatures={n.node_id.value:n.temperature_k for n in out.context.spacecraft_state.thermal.node_states}
    radiation=Q(27,10)/3+Q(28,10)*Q(2,3)
    for node,internal in [('bus',6.),('battery',1.4),('payload',0.)]:
        expected=300.+(float(radiation)+internal)/3600
        assert temperatures[node]==pytest.approx(expected,abs=4*ulp(300.))
    assert out.outcomes[-1].accounting.routed_internal_heat_wh==pytest.approx(6./3600,rel=2**-45)
    assert out.outcomes[-1].accounting.conversion_loss_wh==pytest.approx(1.4/3600,rel=2**-45)


def test_temperature_protection_and_late_commit_atomicity(initial,monkeypatch):
    import ops_sim.v5.engine as engine
    s=copy_state(initial)
    s.context.spacecraft_state.thermal.node_states[0].temperature_k=1000.
    before=CheckpointState.from_context(s.context).to_dict()
    denied=advance_environment_mission(s)
    assert denied.outcomes[-1].reason=='OPERATING_TEMPERATURE_AT_START'
    assert CheckpointState.from_context(s.context).to_dict()==before
    s=copy_state(initial);before=CheckpointState.from_context(s.context).to_dict()
    def late(original,candidate):
        original.simulation_time_seconds=999
        raise RuntimeError('injected commit failure')
    monkeypatch.setattr(engine.SimulationEngine,'_commit',late)
    with pytest.raises(RuntimeError,match='commit failure'):advance_environment_mission(s)
    assert CheckpointState.from_context(s.context).to_dict()==before


def test_completed_contact_identity_cannot_be_consumed_twice(initial):
    from ops_sim.v5.communications import ServiceableGroundContact
    from ops_sim.v5.contact_execution import ConsumedContacts
    from ops_sim.v5.ids import GroundContactId,GroundStationId
    s=copy_state(initial)
    for _ in range(3):s=advance_environment_mission(s)
    s.consumed_contacts=ConsumedContacts((ServiceableGroundContact(GroundContactId('b40.contact.0'),GroundStationId('station'),168,173),))
    before=CheckpointState.from_context(s.context).to_dict()
    with pytest.raises(ValueError):advance_environment_mission(s)
    assert CheckpointState.from_context(s.context).to_dict()==before and s.cursor==3


def test_uncertain_environment_preflight_has_no_physical_publication(initial,monkeypatch):
    import ops_sim.v5.environment_mission as m
    from examples.m2_environment_forcing_demo import trusted_synthetic_result
    s=copy_state(initial);s.source_result=trusted_synthetic_result(s.inputs.environment.source_request,('UNRESOLVED',))
    before=CheckpointState.from_context(s.context).to_dict()
    monkeypatch.setattr(m,'_physical_substep',lambda *a,**k:pytest.fail('uncertain physical kernel must not launch'))
    denied=advance_environment_mission(s)
    assert denied.outcomes[-1].reason=='UNRESOLVED_ILLUMINATION'
    assert CheckpointState.from_context(s.context).to_dict()==before


def test_fractional_contact_cut_refuses_without_rounding_service_outward(initial):
    d=replace(initial.inputs,actions=(MissionAction('fractional-contact','CONTACT','station',2),))
    s=copy_state(initial,d);before=CheckpointState.from_context(s.context).to_dict()
    denied=advance_environment_mission(s)
    assert denied.outcomes[-1].reason=='UNSUPPORTED_FRACTIONAL_CONTACT_FORCING_CUT'
    assert not denied.outcomes[-1].contact_outcomes and CheckpointState.from_context(s.context).to_dict()==before


def test_unavailable_station_is_not_downlink_receipt(initial):
    d=replace(initial.inputs,catalog=(*initial.inputs.catalog[:-1],replace(initial.inputs.catalog[-1],station_available=False)),
        actions=(MissionAction('no-service','CONTACT','station',2),))
    s=copy_state(initial,d);before=CheckpointState.from_context(s.context).to_dict();denied=advance_environment_mission(s)
    assert denied.outcomes[-1].reason=='STATION_GEOMETRY_OR_DECLARED_SERVICE_UNAVAILABLE'
    assert CheckpointState.from_context(s.context).to_dict()==before


def test_short_requested_interval_does_not_admit_long_upstream_source():
    from ops_sim.v5.orbit_config import GeometryInstant
    from ops_sim.v5.sun_table import SunPositionSample
    d=make_inputs();q=d.environment.source_request
    end=GeometryInstant(q.segment.end.epoch,512.)
    table=replace(q.table,domain_seconds=(128.,512.),samples=(q.table.samples[0],SunPositionSample(512.,q.table.samples[-1].position_m)))
    q=replace(q,segment=replace(q.segment,end=end),table=table)
    with pytest.raises(ValueError,match='full upstream source span'):
        replace(d,environment=replace(d.environment,source_request=q))


@pytest.mark.parametrize('action',[MissionAction('bad-target','CAPTURE','blocked-target',4),MissionAction('bad-role','POINT','station'),MissionAction('bad-station','CONTACT','target',4)])
def test_action_role_and_product_target_are_bound_before_owner(action):
    with pytest.raises(ValueError):replace(make_inputs(),actions=(action,))


@pytest.mark.parametrize('kind',['inertial','body'])
def test_foreign_attitude_frame_refused_before_geometry_or_physics(initial,kind):
    s=copy_state(initial);before=CheckpointState.from_context(s.context).to_dict()
    if kind=='body':s.attitude=replace(s.attitude,body_frame_id='FOREIGN_BODY')
    else:
        f=s.attitude.inertial_frame
        phase=replace(f.rotation.initial_phase_rad,value=.1)
        s.attitude=replace(s.attitude,inertial_frame=replace(f,rotation=replace(f.rotation,initial_phase_rad=phase)))
    with pytest.raises(ValueError,match='frame'):advance_environment_mission(s)
    assert s.runtime_work.nominal_orbit_queries==0 and CheckpointState.from_context(s.context).to_dict()==before


def test_undefined_nonnadir_azimuth_not_fabricated(initial):
    from types import SimpleNamespace
    from math import pi
    from ops_sim.v5.assembly_attitude import compile_assembly_hardware
    from ops_sim.v5.environment_mission import _capture_definition
    s=copy_state(initial);s.attitude=replace(s.attitude,angle_y_rad=pi)
    h=compile_assembly_hardware(s.inputs.assembly,s.inputs.capabilities,s.inputs.actuator)
    # Deliberate missing-azimuth boundary double, not orbital evidence.
    observation=SimpleNamespace(visible=True,direction=SimpleNamespace(components=(-1.,0.,0.)),
        geometry=SimpleNamespace(orbital_azimuth_rad=None),off_nadir_rad=.1)
    with pytest.raises(ValueError,match='UNDEFINED_LOCAL_VIEW_AZIMUTH'):
        _capture_definition(s,s.context,s.inputs.actions[1],h,(observation,))
