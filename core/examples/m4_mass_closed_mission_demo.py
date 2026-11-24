"""B46 explicit synthetic rigid/lumped600s construction, no installation proof."""
from dataclasses import replace,asdict
from fractions import Fraction as Q
from pathlib import Path
import argparse,json
from examples.m4_construction_mission_demo import make_inputs as coupled_inputs,report as coupled_report,actual_parts
from ops_sim.v5.long_mission import LongMissionAction
from ops_sim.v5.construction_coupling import compile_construction
from ops_sim.v5.harness_mass import (SpatialMassPoint,RouteMassDistribution,HarnessAugmentationInputs,geometry_digest)
from ops_sim.v5.harness_mission import HarnessMissionInputs,start_harness_mission,advance_harness_mission
from ops_sim.v5.harness_document import (inputs_to_json,inputs_from_json,save_harness_continuation,restore_harness_continuation)
from ops_sim.v5.long_mission_continuation import scientific_bytes
from ops_sim.v5.construction_physics import cut_balance

RATIONALE='ASSUMED B46 rigid co-routed rods; slack is an explicitly hypothesized point centroid; contacts are distinct series point masses at authored polyline vertices. No routing/installation/flex/flight proof or thermal-capacity inference.'


def distribution_inputs(coupled,*,redistributed=False):
    m=coupled.mission;c=compile_construction(m.assembly,coupled.configuration);lines={l.line_id:l for l in coupled.configuration.lines};routes=[]
    for b in c.branches:
        line=lines[b.line_id];vertices=(b.source_body_m,*line.waypoints_body_m,b.load_body_m)
        midpoint=tuple((b.source_body_m[i]+b.load_body_m[i])/2 for i in range(3))
        offset=-.025 if redistributed else .025
        slack=SpatialMassPoint(m.assembly.body_frame_id,(midpoint[0]+offset,midpoint[1],midpoint[2]+offset)) if line.slack_m else None
        connectors=(vertices[1],vertices[1]) if redistributed and line.waypoints_body_m else (vertices[0],vertices[-1])
        if b.wire.connector_count!=2:raise ValueError('this explicit example declares exactly two series connector points')
        routes.append(RouteMassDistribution(line.line_id,geometry_digest(b,line),slack,
            tuple(SpatialMassPoint(m.assembly.body_frame_id,p) for p in connectors),RATIONALE))
    return HarnessAugmentationInputs(c.configuration.assembly_digest,c.configuration_digest,m.assembly.body_frame_id,tuple(routes))


def make_inputs(variant='augmented'):
    if variant not in ('unassembled','augmented','redistributed','weakness','repair'):raise ValueError('known B46 example required')
    coupled=coupled_inputs('weakness' if variant=='weakness' else 'repair' if variant=='repair' else 'baseline')
    # Same authored detours for every case: electrical lengths remain identical
    # between the unassembled/augmented/redistributed mechanical comparison.
    lines=tuple(replace(l,waypoints_body_m=((.6,-.25,.3),)) if l.line_id=='pv-line' else
        replace(l,waypoints_body_m=((.6,.125,.3),)) if l.line_id=='payload-line' else l for l in coupled.configuration.lines)
    configuration=replace(coupled.configuration,lines=lines)
    a=coupled.mission.actions
    actions=(*a[:3],replace(a[3],action_id='partial-first',duration_seconds=1),replace(a[3],action_id='partial-second'),a[4])
    coupled=replace(coupled,configuration=configuration,mission=replace(coupled.mission,actions=actions))
    augmentation=distribution_inputs(coupled,redistributed=variant=='redistributed')
    return HarnessMissionInputs(coupled,augmentation,'UNASSEMBLED_HARNESS_CONTROL_V1' if variant=='unassembled' else 'MASS_AUGMENTED_CLOSED_V1')


def report(state):
    result=coupled_report(state);h=state.harness;hardware=h.hardware
    point=state.outcomes[0];slew=point.slew
    result['harness']=dict(mode=h.inputs.mass_mode,input_digest=h.input_digest,mass_scope=h.mass_scope,work=asdict(h.work),
        base_mass_properties=asdict(slew.hardware.base_hardware.mass_properties if hardware is not None else slew.hardware.mass_properties),
        effective_mass_properties=asdict(slew.hardware.mass_properties),
        added_mass_exact_kg=None if hardware is None else str(hardware.augmentation.added_mass_exact_kg),
        contributions=0 if hardware is None else len(hardware.augmentation.contributions),
        point_duration_seconds=slew.duration_seconds,acceleration_seconds=str(slew.acceleration_seconds),
        effective_axis_inertia=str(slew.effective_inertia_kg_m2),peak_kinetic_j=float(slew.kinetic_j(slew.acceleration_seconds)),
        actuator_electrical_wh=sum(c.actuator_draw_w*float(c.end_seconds-c.start_seconds)/3600 for c in point.cuts),
        mechanical_heat_adjustment_j=sum(c.heat_adjustment_w*float(c.end_seconds-c.start_seconds) for c in point.cuts),
        method=slew.method,source_translation_and_camera_origin='UNCHANGED_DECLARED_SPACECRAFT_POINT_NO_LEVER_ARM_GRADIENT_AERO_OR_FLEX')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--variant',default='augmented');p.add_argument('--input',type=Path)
    p.add_argument('--output-directory',type=Path,required=True);p.add_argument('--resume',type=Path);p.add_argument('--packet-sha256');p.add_argument('--input-digest')
    a=p.parse_args();out=a.output_directory;out.mkdir();paid=None
    if a.resume:state,paid=restore_harness_continuation(a.resume,expected_packet_sha256=a.packet_sha256,expected_input_digest=a.input_digest)
    else:
        inputs=inputs_from_json(a.input.read_text(encoding='utf-8')) if a.input else make_inputs(a.variant)
        (out/'inputs.json').write_text(inputs_to_json(inputs)+'\n',encoding='utf-8');state=start_harness_mission(inputs)
    while state.cursor<len(state.inputs.actions):
        state=advance_harness_mission(state)
        if not a.resume and state.cursor==4:
            h=save_harness_continuation(out/'partial.packet.json',state)
            (out/'partial.binding.json').write_text(json.dumps(dict(packet_sha256=h,input_digest=state.harness.input_digest,
                clock=state.context.simulation_time_seconds,partial_bits=[p.transmitted_equivalent_bits for p in state.context.ground_data_delivery_state.partial_transfers],
                receipts=len(state.context.ground_data_delivery_state.completed_deliveries)),indent=2)+'\n')
    (out/'science.json').write_bytes(scientific_bytes(state))
    summary=dict(**report(state),reconstruction=paid)
    (out/'summary.json').write_text(json.dumps(summary,default=str,indent=2)+'\n',encoding='utf-8')
    (out/'balances.json').write_text(json.dumps([dict(**identity,**cut_balance(part)) for identity,part in actual_parts(state)],indent=2)+'\n')
    print(json.dumps(dict(clock=summary['clock'],receipts=summary['receipts'],harness=summary['harness']),default=str))

if __name__=='__main__':main()
