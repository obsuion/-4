"""B47 synthetic common-policy A/B/C compact/outboard NOMINAL_LONG missions.

No flight performance or physical qualification. The battery-bracket detour is
an authored common routing rule; it changes wire losses and rigid harness mass.
"""
from dataclasses import replace, asdict
from fractions import Fraction as Q
from pathlib import Path
import argparse, json
from examples.m3_long_mission_demo import make_inputs as long_inputs
from examples.m4_construction_mission_demo import make_inputs as construction_inputs, actual_parts
from examples.m4_mass_closed_mission_demo import distribution_inputs
from ops_sim.v5.assembly_document import assembly_document_digest
from ops_sim.v5.thermal_routing import ElectricalLoadComponent
from ops_sim.v5.checkpoint import CheckpointState, ThermalNodeStateSnapshot
from ops_sim.v5.assembly_attitude_3d import BodyAttitude3D
from ops_sim.v5.campaign_contract import ResourceObservation
from ops_sim.v5.ms_product import MSFootprint
from ops_sim.v5.ids import ImagingRequestId
from ops_sim.v5.state import OperationalMode, FDIRState
from ops_sim.v5.rolling_contract import (RollingRoot, ReleasedRequest, DeclaredContact,
    public_model_from_harness)
from ops_sim.v5.rolling_knowledge import KnowledgeMode, ReceivedObservation
from ops_sim.v5.harness_mission import HarnessMissionInputs
from ops_sim.v5.rolling_execution import start_rolling, run_rolling, step_rolling, scientific_bytes, paid_scientific_bytes, work_projection
from ops_sim.v5.rolling_document import inputs_to_json, inputs_from_json, save_continuation, restore_continuation
from ops_sim.v5.construction_physics import cut_balance

ASSUMPTIONS=('ASSUMED ideal net torque full rigid tensor; lumped thermal; ideal star regulators;',
             'ASSUMED observed all node temperatures and homogeneous Hamilton body-to-model-inertial pose;',
             'ASSUMED deterministic boundary packet latency, no sensor/RF/noise calibration;',
             'ASSUMED base-bus wire detours via left battery bracket; same rule both placements;',
             'Original WGS84/TT model and synthetic distant fixed Sun; sampled visibility/lighting, no interval certificate.')


def make_inputs(variant='compact',scenario='A',duration=600):
    if variant not in ('compact','outboard') or scenario not in ('A','B','C') or duration not in (600,3600):
        raise ValueError('declared bounded demonstration')
    template=construction_inputs();mission=long_inputs(variant,duration=duration)
    network=template.configuration.thermal_network
    if scenario=='B':
        nodes=tuple(replace(n,emissivity=replace(n.emissivity,value=.8,
            provenance=replace(n.emissivity.provenance,rationale='ASSUMED B47 common radiative recovery scenario emissivity0.8; no calibration.'))) for n in network.nodes)
        network=replace(network,nodes=nodes)
    cfg=replace(mission.simulation_inputs.spacecraft_configuration,thermal=replace(mission.simulation_inputs.spacecraft_configuration.thermal,network=network))
    simulation=replace(mission.simulation_inputs,spacecraft_configuration=cfg)
    context=mission.initial_checkpoint.restore(simulation)
    if scenario=='B':
        maximum=next(n.operating_max_temperature_k.value for n in network.nodes if n.node_id==network.payload_node_id)
        for n in context.spacecraft_state.thermal.node_states:
            if n.node_id==network.payload_node_id: n.temperature_k=maximum+.05
    mission=replace(mission,simulation_inputs=simulation,initial_checkpoint=CheckpointState.from_context(context))
    selected=next(s for s in mission.assembly.selections if s.instance_id=='battery-left')
    battery_mount=next(c.pose.origin_body_m for c in mission.assembly.choices if c.choice_id==selected.choice_id)
    lines=tuple(replace(l,waypoints_body_m=(battery_mount,)) if l.line_id==ElectricalLoadComponent.BASE_BUS.value+'-line' else l for l in template.configuration.lines)
    configuration=replace(template.configuration,assembly_digest=assembly_document_digest(mission.assembly),
        lines=lines,thermal_network=network,rationale=template.configuration.rationale+' B47 base-bus detour via declared left battery bracket; common rule, no route optimization.')
    coupled=replace(template,mission=mission,configuration=configuration)
    harness=HarnessMissionInputs(coupled,distribution_inputs(coupled))
    model=public_model_from_harness(harness)
    p=mission.products[0]
    requests=[]
    for name,priority,window,deadline in (('urgent',3.,138,320),('medium',2.,250,350),('low',1.,290,360)):
        product=replace(p,request=replace(p.request,request_id=ImagingRequestId('b47-'+name),priority_weight=priority),
            capture_group='b47-capture-'+name,footprint=MSFootprint('b47-region-'+name,100.,100.),
            acquisition_start_seconds=128,acquisition_end_seconds=window,delivery_deadline_seconds=deadline,
            maximum_spacing_x_m=cfg.payload.optical_acquisition.multispectral_reference_sample_spacing_m.value,
            maximum_spacing_y_m=cfg.payload.optical_acquisition.multispectral_reference_sample_spacing_m.value)
        requests.append(ReleasedRequest(128,product,4))
    contacts=tuple(DeclaredContact('service-'+str(a),'station',a,b) for a,b in ((160,161),(180,200),(230,231),(300,320)))
    mode=KnowledgeMode() if scenario!='C' else KnowledgeMode('DELAYED_BOUNDARY_OBSERVATION',40)
    # Authored estimates are explicit constants, not read from actual checkpoint.
    resource=ResourceObservation(80.,1.,1.,0.,tuple(ThermalNodeStateSnapshot(n.node_id,300.) for n in network.nodes),
        OperationalMode.STANDBY,FDIRState.NORMAL,None)
    pose=BodyAttitude3D(mission.assembly.body_frame_id,mission.environment.trajectory.initial_state.position.frame,Q(128),mission.initial_quaternion,Q(128))
    estimate=ReceivedObservation('author-declared-initial-estimate',128,128,resource,pose,origin='DECLARED_ESTIMATE')
    return RollingRoot(model,mission.initial_checkpoint,mission.initial_quaternion,tuple(requests),contacts,mode,estimate)


def summary(state):
    physical=state.physical;parts=list(actual_parts(physical))
    initial=state.root.initial_checkpoint.restore(state.root.model.simulation_inputs)
    energy=[initial.spacecraft_state.battery.energy_wh]+[p.eps_result.battery.end_energy_wh for _,p in parts]
    temperatures={n.node_id.value:max([n.temperature_k]+[t.end_temperature_k for _,p in parts
        for t in p.thermal_coupling_result.thermal_result.node_transitions if t.node_id==n.node_id])
        for n in initial.spacecraft_state.thermal.node_states}
    hardware=physical.harness.hardware
    from ops_sim.v5.ms_product import assess_ms_product
    assessments=[asdict(assess_ms_product(r.product,physical.acquisitions,physical.context.ground_data_delivery_state,
        tuple(c for o in physical.outcomes for c in o.contact_outcomes),physical.context.simulation_time_seconds)) for r in state.root.requests]
    credited=sum(a['status']=='credited' for a in assessments)
    weighted=sum(r.product.request.priority_weight for r,a in zip(state.root.requests,assessments) if a['status']=='credited')
    return dict(api=state.root.api,status=state.status,clock=physical.context.simulation_time_seconds,
        elapsed=physical.context.simulation_time_seconds-128,root_identity=state.root_identity,
        decisions=len(state.decisions),forecasts=state.work.forecast_invocations,
        acquired=len(physical.acquisitions),receipts=len(physical.context.ground_data_delivery_state.completed_deliveries),
        partial_bits=[p.transmitted_equivalent_bits for p in physical.context.ground_data_delivery_state.partial_transfers],
        assessments=assessments,credited_products=credited,priority_weighted_credit=weighted,
        priority_weighted_delivery_score=weighted/sum(r.product.request.priority_weight for r in state.root.requests),
        minimum_energy_wh=min(energy),final_energy_wh=physical.context.spacecraft_state.battery.energy_wh,
        maximum_temperature_k=temperatures,final_temperature_k={n.node_id.value:n.temperature_k for n in physical.context.spacecraft_state.thermal.node_states},
        wire_loss_wh=sum((p.electrical.pv_wire_loss_w+p.electrical.receiving_wire_loss_w)*p.eps_result.battery.dt_seconds/3600 for _,p in parts),
        mass_properties=asdict(hardware.mass_properties),added_harness_mass_kg=str(hardware.augmentation.added_mass_exact_kg),
        physical_parts=len(parts),unmet_load_wh=sum(p.eps_result.battery.unmet_load_w*p.eps_result.battery.dt_seconds/3600 for _,p in parts),
        actions=[dict(id=o.action_id,kind=o.kind,status=o.status,reason=o.reason,start=o.start_seconds,end=o.end_seconds,
            slew_seconds=None if o.slew is None else o.slew.duration_seconds) for o in physical.outcomes],
        planning=[dict(id=d.decision_id,age=d.knowledge_age_seconds,explanation=d.explanation,
            first=d.selected_suffix[0].kind if d.selected_suffix else None,suffix=len(d.selected_suffix),
            rejected=d.rejected,forecasts=len(d.forecasts)) for d in state.decisions],
        work=work_projection(state),assumptions=ASSUMPTIONS)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--variant',choices=('compact','outboard'),default='compact');p.add_argument('--scenario',choices=('A','B','C'),default='A')
    p.add_argument('--duration',type=int,default=600);p.add_argument('--input',type=Path);p.add_argument('--write-input',type=Path)
    p.add_argument('--output-directory',type=Path);p.add_argument('--resume',type=Path);p.add_argument('--packet-sha256');p.add_argument('--root-identity')
    p.add_argument('--stop-after',type=int);p.add_argument('--checkpoint-on-partial',action='store_true')
    a=p.parse_args();reconstruction=None
    if a.resume:
        state,reconstruction=restore_continuation(a.resume,expected_packet_sha256=a.packet_sha256,expected_root_identity=a.root_identity);root=state.root
    else:
        root=inputs_from_json(a.input.read_text(encoding='utf-8')) if a.input else make_inputs(a.variant,a.scenario,a.duration);state=None
    if a.write_input: a.write_input.write_text(inputs_to_json(root)+'\n',encoding='utf-8')
    if a.output_directory is None: return
    out=a.output_directory;out.mkdir()
    (out/'inputs.json').write_text(inputs_to_json(root)+'\n',encoding='utf-8')
    if state is None: state=start_rolling(root)
    saved=False
    while state.status=='ACTIVE' and (a.stop_after is None or len(state.decisions)<a.stop_after):
        state=step_rolling(state)
        if a.checkpoint_on_partial and not saved and (state.physical.context.ground_data_delivery_state.partial_transfers or
                any(c.kind in ('CAPTURE','CONTACT') for c in state.knowledge.pending())):
            h=save_continuation(out/'substantive.packet.json',state);saved=True
            (out/'substantive.binding.json').write_text(json.dumps(dict(packet_sha256=h,root_identity=state.root_identity,
                clock=state.physical.context.simulation_time_seconds,decisions=len(state.decisions),
                partial_bits=[p.transmitted_equivalent_bits for p in state.physical.context.ground_data_delivery_state.partial_transfers],
                pending=[asdict(c) for c in state.knowledge.pending()]),indent=2)+'\n',encoding='utf-8')
    (out/'science.json').write_bytes(paid_scientific_bytes(state))
    report=summary(state);report['reconstruction']=reconstruction
    (out/'summary.json').write_text(json.dumps(report,default=str,indent=2)+'\n',encoding='utf-8')
    (out/'balances.json').write_text(json.dumps([dict(**identity,**cut_balance(part)) for identity,part in actual_parts(state.physical)],indent=2)+'\n',encoding='utf-8')
    print(json.dumps({n:report[n] for n in ('status','clock','elapsed','decisions','forecasts','acquired','receipts','planning')},default=str))


if __name__=='__main__': main()
