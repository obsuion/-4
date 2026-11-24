"""B43 synthetic general-Earth mission; WGS84 shape is sourced, flight inputs are assumed."""
from dataclasses import replace,asdict
from fractions import Fraction as Q
from math import radians,pi,cos,sin
from pathlib import Path
import argparse,json
from examples.m3_spatial_constructor_mission_demo import (make_inputs as sphere_inputs,
    assembly_variant,parameter,scalar,run)
from ops_sim.v5.orbit_config import (wgs84_reference_ellipsoid,nominal_earth_angular_velocity,
    UniformRotationDefinition,FrameDefinition,FrameKind)
from ops_sim.v5.frames import CartesianPosition,CartesianVelocity,CartesianState,geodetic_position,geodetic_normal
from ops_sim.v5.orbit_geometry import GroundPointDefinition
from ops_sim.v5.sun_table import SunPositionSample
from ops_sim.v5.environment_mission_3d import MissionAction,start_environment_mission,advance_environment_mission
from ops_sim.v5.environment_mission_3d_document import save_mission_inputs,load_mission_inputs
from ops_sim.v5.environment_mission_3d_continuation import scientific_bytes
from ops_sim.v5.assembly_document import save_assembly_document,load_assembly_document
from ops_sim.v5.mission_general_geometry import MODE,GeneralGeometryPolicy
from ops_sim.v5.ids import GroundTargetId,GroundStationId


def make_inputs(name='compact',*,design=None,case='wgs84'):
    if case not in ('wgs84','south','pole','trap','buried','sphere'):raise ValueError('unknown general world')
    old=sphere_inputs(name,design=design)
    q=old.environment.source_request; old_frame=q.segment.trajectory.initial_state.position.frame
    earth=old_frame.ellipsoid if case=='sphere' else wgs84_reference_ellipsoid()
    lat=0. if case=='sphere' else -25. if case=='south' else 89.9 if case=='pole' else 87. if case=='trap' else 25.
    h=0. if case in ('sphere','trap') else -100. if case=='buried' else 1000.
    rate=2*pi/40 if case=='trap' else nominal_earth_angular_velocity().value
    phase=-pi if case=='trap' else 0.
    rotation=UniformRotationDefinition(old_frame.rotation.epoch,
        scalar('orbit.rotation.initial-phase','rad',phase),
        scalar('orbit.rotation.angular-rate','rad/s',rate))
    frame=FrameDefinition(FrameKind.MODEL_INERTIAL,earth,rotation)
    instant=q.segment.trajectory.initial_state.position.instant
    def ground(identifier,degrees,height,lon=0.):
        return GroundPointDefinition(identifier,earth,scalar('orbit.ground-point.geodetic-latitude','rad',radians(degrees)),
            scalar('orbit.ground-point.east-longitude','rad',lon),scalar('orbit.ground-point.ellipsoidal-height','m',height))
    # Input synthesis uses nominal C1 to DEFINE a Cartesian anchor, never a proof.
    start_lon=.02-phase-rate*128
    while start_lon < -pi:start_lon+=2*pi
    while start_lon >= pi:start_lon-=2*pi
    overhead=ground(GroundTargetId('anchor-input-only'),lat,0.,start_lon)
    earth_fixed=FrameDefinition(FrameKind.EARTH_FIXED,earth,rotation)
    from ops_sim.v5.frames import transform_position,transform_direction
    pos=transform_position(geodetic_position(overhead.geodetic_location,earth_fixed,instant),frame)
    normal=transform_direction(geodetic_normal(overhead.geodetic_location,earth_fixed,instant),frame)
    altitude=600000.
    components=tuple(x+altitude*n for x,n in zip(pos.components_m,normal.components))
    # East tangent to the initial meridian. Same center/velocity for both mounts.
    velocity=(0.,7500.,0.)
    state=CartesianState(CartesianPosition(frame,instant,components),CartesianVelocity(frame,instant,velocity))
    trajectory=replace(q.segment.trajectory,initial_state=state)
    segment=replace(q.segment,trajectory=trajectory)
    sun=tuple(x*1e11 for x in normal.components)
    table=replace(q.table,frame=frame,samples=(SunPositionSample(128.,sun),SunPositionSample(192.,sun)))
    environment=replace(old.environment,source_request=replace(q,segment=segment,table=table))
    target_lat=89.9 if case=='trap' else lat
    target=ground(GroundTargetId('target'),target_lat,h)
    lon=(-phase-rate*148) if case=='trap' else 0.
    while lon < -pi:lon+=2*pi
    while lon >= pi:lon-=2*pi
    station=ground(GroundStationId('station'),66. if case=='trap' else lat,0. if case in ('trap','sphere') else 120.,lon)
    blocked=ground(GroundTargetId('blocked-target'),-lat if lat else 0.,0.,-pi)
    catalog=(replace(old.catalog[0],point=target),replace(old.catalog[1],point=blocked),
             replace(old.catalog[2],point=station,service_assumption='ASSUMED station availability/RF/1000bit/s; continuous geometry separate.'))
    actions=old.actions if case!='trap' else (old.actions[0],old.actions[1],MissionAction('wait','HOLD_UNTIL',until_seconds=148),
        MissionAction('contact','CONTACT','station',40),old.actions[-1])
    return replace(old,environment=environment,catalog=catalog,actions=actions,geometry_mode=MODE,geometry_policy=GeneralGeometryPolicy())

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case',choices=('wgs84','south','pole','trap','buried','sphere','electrical-negative'),default='wgs84')
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
        inputs=load_mission_inputs(a.input) if a.input else make_inputs(a.variant,case='wgs84' if a.case=='electrical-negative' else a.case,
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
