"""Editable M1 mounts -> paid attitude -> real data custody, short nominal model.

All hardware, forcing, static Earth and prescribed Sun coefficients below are
ASSUMED test inputs. Two assembly documents differ only in battery placements.
Point sampling does not certify continuous target/RF visibility.
"""
from dataclasses import replace, asdict
from fractions import Fraction as Q
from math import radians, pi
from pathlib import Path
import argparse
import json
from examples.v5_ms_mission_demo import build_demo_state, parameter as legacy_parameter
from examples.v5_operational_protection_demo import policy
from examples.v5_coupled_downlink_demo import physical_inputs
from examples.m2_environment_forcing_demo import parameter as legacy_scalar
from examples.m2_sun_table_demo import synthetic_table
from ops_sim.v5.environment_mission_3d_continuation import scientific_bytes
from ops_sim.v5.assembly import UniformCuboid, MountPose, MassCoverage
from ops_sim.v5.assembly_choices import (AssemblyDesign, PhysicalInstance, PlacementChoice,
    InstallationBox, InstallationRegion, Selection)
from ops_sim.v5.assembly_document import save_assembly_document, load_assembly_document
from ops_sim.v5.assembly_attitude import ComponentAxisBinding
from ops_sim.v5.assembly_attitude_3d import NetTorqueActuatorPolicy as ActuatorPolicy, compile_assembly_hardware_3d as compile_assembly_hardware
from ops_sim.v5.environment_mission_3d import (EnvironmentMissionInputs3D, MissionAction,
    start_environment_mission, advance_environment_mission, scientific_projection)
from ops_sim.v5.environment_mission_3d_document import save_mission_inputs, load_mission_inputs
from ops_sim.v5.mission_environment import CatalogPoint, SamplingPolicy
from ops_sim.v5.environment_forcing import NodeForcing, ForcingProfileEntry, EnvironmentForcingRequest
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.orbit_config import (TTEpoch, ReferenceEllipsoid, UniformRotationDefinition,
                                    FrameDefinition, FrameKind, GeometryInstant)
from ops_sim.v5.frames import CartesianState, CartesianPosition, CartesianVelocity
from ops_sim.v5.orbit_j2 import J2CartesianTrajectory, J2GravityModel
from ops_sim.v5.orbit_j2_enclosure import J2EnclosurePolicy
from ops_sim.v5.orbit_j2_zonotope import J2ZonotopePolicyV3
from ops_sim.v5.orbit_j2_zonotope_segments import J2ZonotopeSegmentRequest
from ops_sim.v5.orbit_sun_zonotope_local_v2 import ZonotopeLocalIlluminationPolicyV2, ZonotopeLocalIlluminationRequestV2
from ops_sim.v5.sun_table import SunPositionSample
from ops_sim.v5.orbit_geometry import GroundPointDefinition
from ops_sim.v5.orbit_visibility import GroundVisibilityPolicy
from ops_sim.v5.ids import GroundTargetId, GroundStationId, ThermalNodeId
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.thermal_routing import ComponentHeatRoute, ComponentHeatRoutingConfig, ElectricalLoadComponent

ASSUMPTION='B42 synthetic bounded nominal test input; no spacecraft calibration or flight performance claim.'
def parameter(p,value):
    return replace(legacy_parameter(p,value),provenance=replace(p.provenance,rationale=ASSUMPTION))


def scalar(name,units,value):
    p=legacy_scalar(name,units,value)
    return replace(p,provenance=replace(p.provenance,rationale=ASSUMPTION))


IDENTITY=((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))
PLUS_Y=((0.,0.,1.),(0.,1.,0.),(-1.,0.,0.))
MINUS_Y=((0.,0.,-1.),(0.,1.,0.),(1.,0.,0.))


def assembly_variant(name):
    if name not in ('compact','outboard'):raise ValueError('unknown variant')
    distance=.25 if name=='compact' else .7
    definitions=(UniformCuboid('core','C-core',4.,(.2,.2,.2),(0.,0.,0.),'ASSUMED_UNIFORM_CUBOID'),
        UniformCuboid('camera','C-camera',.2,(.1,.1,.1),(0.,0.,0.),'ASSUMED_UNIFORM_CUBOID'),
        UniformCuboid('panel','C-panel',.4,(.1,.6,.05),(0.,0.,0.),'ASSUMED_UNIFORM_CUBOID'),
        UniformCuboid('battery','C-battery',1.,(.1,.1,.1),(0.,0.,0.),'ASSUMED_UNIFORM_CUBOID'))
    records=(('core','core',(0.,0.,0.),IDENTITY,(.11,.11,.11)),
        ('camera','camera',(0.,.25,0.),PLUS_Y,(.06,.06,.06)),
        ('panel','panel',(0.,-.5,0.),MINUS_Y,(.04,.31,.06)),
        ('battery-left','battery',(-distance,-.15,.1),IDENTITY,(.06,.06,.06)),
        ('battery-right','battery',(distance,.15,-.1),IDENTITY,(.06,.06,.06)))
    choices=[];instances=[];selections=[]
    for identifier,definition,origin,rotation,extent in records:
        choice='mount-'+identifier
        pose=MountPose(choice,choice,'BODY_B40','C-'+definition,origin,rotation,(identifier,))
        box=InstallationBox(tuple(x-d for x,d in zip(origin,extent)),tuple(x+d for x,d in zip(origin,extent)))
        instances.append(PhysicalInstance(identifier,definition,MassCoverage(((identifier,),))))
        choices.append(PlacementChoice(choice,definition,(identifier,),pose,box,'space',True))
        selections.append(Selection(identifier,choice))
    return AssemblyDesign('BODY_B40',definitions,tuple(instances),tuple(choices),tuple(selections),
        (InstallationRegion('space',InstallationBox((-2.,-2.,-2.),(2.,2.,2.))),),(),.001)


def environment_request():
    epoch=TTEpoch(2451545,.125)
    earth=ReferenceEllipsoid('B40-synthetic-sphere',scalar('orbit.earth.equatorial-radius','m',6400000.),
                             scalar('orbit.earth.flattening','1',0.))
    rotation=UniformRotationDefinition(epoch,scalar('orbit.rotation.initial-phase','rad',0.),
        scalar('orbit.rotation.angular-rate','rad/s',1e-5))
    frame=FrameDefinition(FrameKind.MODEL_INERTIAL,earth,rotation);instant=GeometryInstant(epoch,128.)
    state=CartesianState(CartesianPosition(frame,instant,(7000000.,0.,0.)),
        CartesianVelocity(frame,instant,(0.,0.,7500.)))
    gravity=J2GravityModel(scalar('orbit.gravity.gravitational-parameter','m^3/s^2',4e14),
        scalar('orbit.gravity.j2','1',1/1024),scalar('orbit.gravity.reference-radius','m',6400000.))
    trajectory=J2CartesianTrajectory(state,gravity)
    segment=J2ZonotopeSegmentRequest(trajectory,GeometryInstant(epoch,192.),
        J2ZonotopePolicyV3(J2EnclosurePolicy(5.,32,6000000.,50,12),(6,6,6,3,3,3),2**31))
    table=replace(synthetic_table(frame),domain_seconds=(128.,192.),samples=(
        SunPositionSample(128.,(1e11,0.,0.)),SunPositionSample(192.,(1e11,0.,0.))))
    local=ZonotopeLocalIlluminationRequestV2(segment,table,1.,ZonotopeLocalIlluminationPolicyV2(
        32,0,0,0,384,64,65536,2**34,2**24,2**32))
    def entry(a,b,albedo):
        return ForcingProfileEntry(a,b,0.,PowerLoadBreakdown(5.,1.,0.,0.,0.,0.,0.),
            tuple(NodeForcing(ThermalNodeId(n),300.,0.,2.,albedo,.5) for n in ('bus','battery','payload')),
            'Explicit radiation excludes routed electrical heat and conversion losses; sink excludes these explicit sources.')
    return EnvironmentForcingRequest(local,Q(128),Q(192),tuple(ThermalNodeId(n) for n in ('bus','battery','payload')),
        (entry(Q(128),Q(128)+Q(1,3),.2),entry(Q(128)+Q(1,3),Q(192),.3)))


def make_inputs(name='compact',*,design=None):
    ctx=build_demo_state(width_m=100.,length_m=100.,spacing_m=6.5).context
    cfg=ctx.inputs.spacecraft_configuration
    cfg=replace(cfg,communications=replace(cfg.communications,nominal_downlink_data_rate_bps=
        parameter(cfg.communications.nominal_downlink_data_rate_bps,1000.)),
        adcs=replace(cfg.adcs,agile_pointing=replace(cfg.adcs.agile_pointing,
            post_slew_settling_time_seconds=parameter(cfg.adcs.agile_pointing.post_slew_settling_time_seconds,1.))))
    ctx.inputs=replace(ctx.inputs,spacecraft_configuration=cfg,
        common_world=replace(ctx.inputs.common_world,horizon_seconds=192,event_ids=()))
    ctx.simulation_time_seconds=128
    old=physical_inputs(ctx)
    routes=ComponentHeatRoutingConfig(tuple(ComponentHeatRoute(component,
        ThermalNodeId('payload' if component is ElectricalLoadComponent.PAYLOAD else 'bus'),
        scalar('thermal.routing.'+component.value+'.retained-heat-fraction','1',1.)) for component in ElectricalLoadComponent))
    tx=replace(old.transmitter,electrical_power_w=parameter(old.transmitter.electrical_power_w,10.))
    from ops_sim.v5.ms_product import MSProductSpec, MSFootprint, REQUIRED_MS_CHANNELS
    from ops_sim.v5.observation import ImagingRequest
    from ops_sim.v5.ids import ImagingRequestId
    product=MSProductSpec(1,ImagingRequest(ImagingRequestId('b40-ms'),GroundTargetId('target'),1.),
        'b40-capture',REQUIRED_MS_CHANNELS,MSFootprint('b40-rectangle',100.,100.),128,148,6.5,6.5,188)
    environment=environment_request();earth=environment.source_request.segment.trajectory.initial_state.position.frame.ellipsoid
    gate=GroundVisibilityPolicy(scalar('orbit.visibility.minimum-elevation','rad',0.))
    def ground(identifier,lon):
        return GroundPointDefinition(identifier,earth,scalar('orbit.ground-point.geodetic-latitude','rad',0.),
            scalar('orbit.ground-point.east-longitude','rad',lon),scalar('orbit.ground-point.ellipsoidal-height','m',0.))
    catalog=(CatalogPoint(ground(GroundTargetId('target'),0.),gate,False,False,0,'Geometry only; no station service.'),
        CatalogPoint(ground(GroundTargetId('blocked-target'),-pi),gate,False,False,0,'Geometry only.'),
        CatalogPoint(ground(GroundStationId('station'),0.),gate,True,True,1000,
            'ASSUMED availability and 1000 bit/s nominal service; no antenna/RF link budget; geometry remains sampled.'))
    capabilities=(ComponentAxisBinding('camera','camera','C-camera',(0.,.6,.8),ASSUMPTION),
                  ComponentAxisBinding('panel','panel','C-panel',(0.,-.6,.8),ASSUMPTION))
    actuator=ActuatorPolicy((.1,.1,.1),(.6,.6,.6),2.,.8,1,(10.,10.,10.),ASSUMPTION)
    actions=(MissionAction('point','POINT','target'),MissionAction('capture','CAPTURE','target',4),
        MissionAction('wait','HOLD_UNTIL',until_seconds=168),MissionAction('contact','CONTACT','station',20),
        MissionAction('finish','HOLD_UNTIL',until_seconds=192))
    return EnvironmentMissionInputs3D(ctx.inputs,CheckpointState.from_context(ctx),environment,
        assembly_variant(name) if design is None else design,capabilities,actuator,catalog,SamplingPolicy(),
        actions,product,policy(ctx),routes,tx,(1.,0.,0.,0.),radians(15.),1e-7)


def run(inputs,stop=None):
    state=start_environment_mission(inputs)
    while state.cursor<(len(inputs.actions) if stop is None else stop):state=advance_environment_mission(state)
    return state


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',choices=('spatial','electrical-negative'),default='spatial')
    p.add_argument('--input',type=Path);p.add_argument('--assembly',type=Path)
    p.add_argument('--variant',choices=('compact','outboard'),default='compact')
    p.add_argument('--write-input',type=Path);p.add_argument('--write-assembly',type=Path)
    p.add_argument('--output',type=Path);p.add_argument('--stop-after',type=int)
    p.add_argument('--checkpoint-output',type=Path);p.add_argument('--resume',type=Path)
    p.add_argument('--packet-sha256');p.add_argument('--input-digest');p.add_argument('--work-output',type=Path)
    a=p.parse_args()
    if a.resume:
        from ops_sim.v5.environment_mission_3d_continuation import restore_continuation,scientific_bytes as encode
        state,reconstruction=restore_continuation(a.resume,expected_packet_sha256=a.packet_sha256,expected_input_digest=a.input_digest)
        inputs=state.inputs
    else:
        state=None;reconstruction=None
        inputs=load_mission_inputs(a.input) if a.input else make_inputs(a.variant,
        design=None if a.assembly is None else load_assembly_document(a.assembly))
    if not a.input and not a.resume and a.case=='electrical-negative':
        cfg=inputs.simulation_inputs.spacecraft_configuration
        battery=replace(cfg.eps.battery,max_discharge_output_power_w=parameter(cfg.eps.battery.max_discharge_output_power_w,1.))
        inputs=replace(inputs,simulation_inputs=replace(inputs.simulation_inputs,spacecraft_configuration=replace(cfg,eps=replace(cfg.eps,battery=battery))))
    if a.write_input:save_mission_inputs(a.write_input,inputs)
    if a.write_assembly:save_assembly_document(inputs.assembly,a.write_assembly)
    if a.output:
        if state is None:state=start_environment_mission(inputs)
        stop=len(inputs.actions) if a.stop_after is None else a.stop_after
        if type(stop) is not int or not state.cursor<=stop<=len(inputs.actions):raise ValueError('invalid action boundary')
        while state.cursor<stop:state=advance_environment_mission(state)
        if a.checkpoint_output:
            from ops_sim.v5.environment_mission_3d_continuation import save_continuation
            digest=save_continuation(a.checkpoint_output,state);print('PACKET_SHA256='+digest)
        if a.work_output:a.work_output.write_bytes((json.dumps(dict(work=asdict(state.runtime_work),reconstruction=reconstruction),default=str,indent=2)+'\n').encode())
        a.output.write_bytes(scientific_bytes(state))
        print(json.dumps(dict(cursor=state.cursor,status=state.assessment().status,
            credit=state.assessment().credited_products,clock=state.context.simulation_time_seconds,
            actions=[(o.kind,o.status,o.reason) for o in state.outcomes],work=asdict(state.runtime_work))))


if __name__=='__main__':main()
