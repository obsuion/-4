"""B44 synthetic long mission. Explicit nominal day / conditional 600s model.

Shared loads, synthetic fixed distant Sun table, world/program and actuator.
Only battery placements differ. This is no flight/hardware qualification.
"""
from dataclasses import replace, asdict
from fractions import Fraction as Q
from pathlib import Path
import argparse, json
from examples.m3_general_earth_mission_demo import make_inputs as short_inputs
from ops_sim.v5.long_environment import LongEnvironment, NOMINAL, CONTINUOUS
from ops_sim.v5.long_mission import (LongMissionInputs, LongMissionAction,
    LongSamplingPolicy, LongMissionLimits, start_long_mission, advance_long_mission)
from ops_sim.v5.long_nominal_provider import LongNominalPolicy
from ops_sim.v5.long_general_geometry import LongGeometryPolicy
from ops_sim.v5.long_mission_document import save_mission_inputs,load_mission_inputs,mission_input_digest
from ops_sim.v5.long_mission_continuation import scientific_bytes,save_continuation,restore_continuation
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.sun_table import SunPositionSample
from ops_sim.v5.ids import ImagingRequestId
from ops_sim.v5.checkpoint import CheckpointState

def make_inputs(variant='compact',*,mode=NOMINAL,duration=86400):
    if type(duration) is not int or not 600<=duration<=86400:raise ValueError('declared long example horizon')
    old=short_inputs(variant);q=old.environment.source_request;end=128+duration
    # Cartesian authority, WGS84, latitude+25 and nonzero heights/rotation
    # remain exactly those of accepted B43. Full original epoch/frame retained.
    table=replace(q.table,domain_seconds=(128.,float(end)),samples=(
        SunPositionSample(128.,q.table.samples[0].position_m),
        SunPositionSample(float(end),q.table.samples[-1].position_m)))
    request=None
    if mode==CONTINUOUS:
        base=replace(q.segment.policy.base_policy,max_steps=256)
        segment=replace(q.segment,end=GeometryInstant(table.epoch,float(end)),policy=replace(q.segment.policy,base_policy=base))
        local=replace(q.policy,max_initial_steps=256,max_picard_attempts=3072,max_geometry_cells=512,max_retained_evidence_units=131072)
        request=replace(q,segment=segment,table=table,policy=local)
    profile=tuple(replace(e,end_seconds=Q(end) if i==len(old.environment.profile)-1 else e.end_seconds,
        # Two-watt aggregate synthetic housekeeping; OBC separately zero.
        # This declared case avoids nonassociative multi-component binary64
        # sums rejected by the unchanged exact routing/EPS consistency guard.
        loads=replace(e.loads,base_bus_w=2.,obc_w=0.)) for i,e in enumerate(old.environment.profile))
    environment=LongEnvironment(q.segment.trajectory,table,Q(128),Q(end),old.environment.node_ids,profile,mode,request)
    simulation=replace(old.simulation_inputs,common_world=replace(old.simulation_inputs.common_world,horizon_seconds=end))
    if duration>=6000:
        # Revised DAY-RADIATIVE-03 case: the inherited short arithmetic demo
        # used emissivity=0 (no radiative cooling). Declare 0.8 for every node,
        # retaining areas/capacities/links/sink and all protection thresholds.
        # This common synthetic plant is shared by both battery placements.
        cfg=simulation.spacecraft_configuration
        nodes=tuple(replace(n,emissivity=replace(n.emissivity,value=.8,provenance=replace(n.emissivity.provenance,
            rationale='ASSUMED B44 DAY-RADIATIVE-03 emissivity0.8 for stable synthetic day forcing; no spacecraft calibration or hardware performance claim.'))) for n in cfg.thermal.network.nodes)
        simulation=replace(simulation,spacecraft_configuration=replace(cfg,thermal=replace(cfg.thermal,network=replace(cfg.thermal.network,nodes=nodes))))
    context=old.initial_checkpoint.restore(simulation)
    p0=replace(old.product,request=replace(old.product.request,request_id=ImagingRequestId('b44-ms-0')),
        capture_group='b44-capture-0')
    actions=[LongMissionAction('point-0','POINT','target'),LongMissionAction('capture-0','CAPTURE','target',4,product_id='b44-ms-0'),
        LongMissionAction('wait-0','HOLD_UNTIL',until_seconds=168),LongMissionAction('contact-0','CONTACT','station',20)]
    products=[p0]
    if duration>=6000:
        p1=replace(p0,request=replace(p0.request,request_id=ImagingRequestId('b44-ms-1')),capture_group='b44-capture-1',
            acquisition_start_seconds=6128,acquisition_end_seconds=6148,delivery_deadline_seconds=6188)
        products.append(p1)
        actions.extend((LongMissionAction('later','HOLD_UNTIL',until_seconds=6128),
            LongMissionAction('blocked-point','POINT','blocked-target'),
            LongMissionAction('point-1','POINT','target'),LongMissionAction('capture-1','CAPTURE','target',4,product_id='b44-ms-1'),
            LongMissionAction('wait-1','HOLD_UNTIL',until_seconds=6168),LongMissionAction('contact-1','CONTACT','station',20)))
    actions.append(LongMissionAction('finish','HOLD_UNTIL',until_seconds=end))
    return LongMissionInputs(simulation,CheckpointState.from_context(context),environment,old.assembly,old.capabilities,old.actuator,
        old.catalog,LongSamplingPolicy(),tuple(actions),tuple(products),old.protection,old.routing,old.transmitter,
        old.initial_quaternion,old.camera_half_fov_rad,old.solar_retention_loss_per_second,
        LongNominalPolicy(),LongMissionLimits(),LongGeometryPolicy())

def run(inputs,stop=None):
    state=start_long_mission(inputs)
    while state.cursor<(len(inputs.actions) if stop is None else stop):state=advance_long_mission(state)
    return state

def summary(state):
    cp=CheckpointState.from_context(state.context).to_dict()
    return dict(mode=state.inputs.environment.mode,clock=state.context.simulation_time_seconds,
        elapsed=state.context.simulation_time_seconds-state.inputs.environment.start_seconds.numerator,
        products=len(state.inputs.products),acquisitions=len(state.acquisitions),
        receipts=len(state.context.ground_data_delivery_state.completed_deliveries),credits=[asdict(a) for a in state.assessment()],
        actions=[dict(id=o.action_id,kind=o.kind,status=o.status,reason=o.reason,start=o.start_seconds,end=o.end_seconds,
                      cuts=len(o.cuts),slew_seconds=None if o.slew is None else o.slew.duration_seconds) for o in state.outcomes],
        work=asdict(state.runtime_work),nominal=state.nominal_provider.accounting(),index=state.source_authority.accounting(),
        final_checkpoint=cp,input_digest=state.input_digest)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--variant',choices=('compact','outboard'),default='compact')
    p.add_argument('--mode',choices=(NOMINAL,CONTINUOUS),default=NOMINAL)
    p.add_argument('--duration',type=int,default=86400)
    p.add_argument('--input',type=Path);p.add_argument('--write-input',type=Path)
    p.add_argument('--output',type=Path);p.add_argument('--summary',type=Path);p.add_argument('--stop-after',type=int)
    p.add_argument('--checkpoint-output',type=Path);p.add_argument('--resume',type=Path)
    p.add_argument('--packet-sha256');p.add_argument('--input-digest');p.add_argument('--work-output',type=Path)
    a=p.parse_args();reconstruction=None
    if a.resume:
        state,reconstruction=restore_continuation(a.resume,expected_packet_sha256=a.packet_sha256,expected_input_digest=a.input_digest)
        inputs=state.inputs
    else:
        inputs=load_mission_inputs(a.input) if a.input else make_inputs(a.variant,mode=a.mode,duration=a.duration);state=None
    if a.write_input:save_mission_inputs(a.write_input,inputs)
    if a.output:
        if state is None:state=start_long_mission(inputs)
        stop=len(inputs.actions) if a.stop_after is None else a.stop_after
        if not state.cursor<=stop<=len(inputs.actions):raise ValueError('invalid boundary')
        while state.cursor<stop:state=advance_long_mission(state)
        if a.checkpoint_output:print('PACKET_SHA256='+save_continuation(a.checkpoint_output,state))
        a.output.write_bytes(scientific_bytes(state))
        report=summary(state)
        if a.summary:a.summary.write_text(json.dumps(report,default=str,indent=2)+'\n',encoding='utf-8')
        if a.work_output:a.work_output.write_text(json.dumps(dict(work=asdict(state.runtime_work),reconstruction=reconstruction),indent=2)+'\n',encoding='utf-8')
        print(json.dumps({n:report[n] for n in ('mode','clock','elapsed','products','acquisitions','receipts','actions')},default=str))

if __name__=='__main__':main()
