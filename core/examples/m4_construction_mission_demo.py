"""B45 actual600s NOMINAL_LONG synthetic construction comparisons, not flight data."""
from dataclasses import replace, asdict
from pathlib import Path
import argparse,json
from examples.m3_long_mission_demo import make_inputs as base_inputs,summary as base_summary
from ops_sim.v5.long_environment import NOMINAL
from ops_sim.v5.assembly import MassCoverage
from ops_sim.v5.assembly_document import assembly_document_digest
from ops_sim.v5.assembly_interfaces import (ElectricalPort,WireProperties,OperatingPoint,
    HarnessMassDeclaration,LineConnection,ThermalBinding,_network)
from ops_sim.v5.thermal_routing import ElectricalLoadComponent
from ops_sim.v5.construction_coupling import ConstructionConfiguration,ReceivingBranch
from ops_sim.v5.construction_mission import ConstructionMissionInputs,start_construction_mission,advance_construction_mission
from ops_sim.v5.construction_document import (inputs_to_json,inputs_from_json,save_construction_continuation,
    restore_construction_continuation)
from ops_sim.v5.long_mission_continuation import scientific_bytes
from ops_sim.v5.construction_physics import cut_balance
from ops_sim.v5.environment_forcing import _case
from ops_sim.v5.thermal_config import ThermalLinkConfig
from ops_sim.v5.ids import ThermalLinkId
from examples.m3_spatial_constructor_mission_demo import scalar

ASSUMPTION='ASSUMED B45 ideal28V star; copper-like rho1.7e-8/density8960; imposed10A/drop6V; explicit lumped heat; synthetic uncalibrated geometry/material/thermal values.'


def make_inputs(variant='baseline'):
    if variant not in ('baseline','route','thermal','weakness','repair'):raise ValueError('known construction case required')
    mission=base_inputs(mode=NOMINAL,duration=600)
    cfg=mission.simulation_inputs.spacecraft_configuration
    network=cfg.thermal.network
    link=ThermalLinkConfig(ThermalLinkId('b45-bus-payload'),network.bus_node_id,network.payload_node_id,
        scalar('thermal.link.b45-bus-payload.conductance','W/K',.1))
    cfg=replace(cfg,thermal=replace(cfg.thermal,network=_network(replace(network,links=(link,)))))
    mission=replace(mission,simulation_inputs=replace(mission.simulation_inputs,spacecraft_configuration=cfg))
    if variant=='thermal':
        cfg=mission.simulation_inputs.spacecraft_configuration;network=cfg.thermal.network
        link=network.links[0]
        changed=replace(link,conductance_w_per_k=replace(link.conductance_w_per_k,value=link.conductance_w_per_k.value*.1,
            provenance=replace(link.conductance_w_per_k.provenance,rationale='ASSUMED B45 thermal-only sensitivity: first declared link conductance reduced10x; no geometry-derived conductance.')))
        cfg=replace(cfg,thermal=replace(cfg.thermal,network=replace(network,links=(changed,*network.links[1:]))))
        simulation=replace(mission.simulation_inputs,spacecraft_configuration=cfg)
        mission=replace(mission,simulation_inputs=simulation)
    definitions={d.definition_id:d for d in mission.assembly.definitions};instances={i.instance_id:i for i in mission.assembly.instances}
    ports=[];lines=[];receiving=[]
    def port(name,instance,role):
        definition=definitions[instances[instance].definition_id]
        ports.append(ElectricalPort(name,instance,definition.local_frame_id,definition.center_local_m,role));return name
    def line(identifier,source,load,node,component=None):
        section=1e-7
        if component is ElectricalLoadComponent.PAYLOAD:
            if variant=='weakness':section=1e-10
            if variant=='repair':section=1e-6
        wire=WireProperties(section,1.7e-8,8960.,.001,2,.002,10.,6.)
        slack=2. if variant=='route' else .2
        lines.append(LineConnection(identifier,source,load,(),slack,wire,OperatingPoint('GENERATED' if component is None else 'CONSTANT_LOAD',28.,0.),
            HarnessMassDeclaration('EXCLUDED',MassCoverage((('B45-external-harness',identifier),)),None),node))
    pvsource=port('pv-source','panel','SOURCE');pvload=port('pv-bus','core','LOAD')
    line('pv-line',pvsource,pvload,'bus')
    for component in ElectricalLoadComponent:
        name=component.value
        source=port(name+'-source','core','SOURCE')
        target='camera' if component is ElectricalLoadComponent.PAYLOAD else 'core'
        load=port(name+'-receiver',target,'LOAD')
        line(name+'-line',source,load,'payload' if target=='camera' else 'bus',component)
        receiving.append(ReceivingBranch(component,name+'-line'))
    network=mission.simulation_inputs.spacecraft_configuration.thermal.network
    bindings=(ThermalBinding('core','bus','core-panel-lump'),ThermalBinding('panel','bus','core-panel-lump'),
        ThermalBinding('camera','payload',None))
    configuration=ConstructionConfiguration(assembly_document_digest(mission.assembly),mission.assembly.body_frame_id,'core',28.,20.,28.,'pv-line',
        tuple(ports),tuple(lines),tuple(receiving),bindings,network,_case(mission.environment.profile[0],False).thermal_inputs,ASSUMPTION)
    return ConstructionMissionInputs(mission,configuration)


def actual_parts(state):
    for o in state.outcomes:
        for c in o.cuts:yield dict(action=o.action_id,kind=o.kind,start=str(c.start_seconds),end=str(c.end_seconds)),c.part
        for forcing in o.contact_forcing:
            for evaluation in forcing.evaluations:
                if evaluation.selected:
                    for i,part in enumerate(evaluation.parts):
                        yield dict(action=o.action_id,kind='CONTACT_IDLE' if evaluation.standby else 'CONTACT_TX',
                            start_bits=evaluation.start_bits,index=i,rate=evaluation.rate),part


def report(state):
    summary=base_summary(state);parts=list(actual_parts(state))
    energy=[state.inputs.initial_checkpoint.spacecraft.battery_energy_wh]+[p.eps_result.battery.end_energy_wh for _,p in parts]
    nodes=state.inputs.simulation_inputs.spacecraft_configuration.thermal.network.nodes
    summary['construction']=dict(input_digest=state.construction.input_digest,configuration_digest=state.construction.compilation.configuration_digest,
        work=asdict(state.construction.work),conductor_mass_kg=state.construction.compilation.conductor_mass_kg,
        connector_mass_kg=state.construction.compilation.connector_mass_kg,mass_scope=state.construction.compilation.mass_scope,
        actual_cuts=len(parts),minimum_energy_wh=min(energy),final_energy_wh=state.context.spacecraft_state.battery.energy_wh,
        max_temperature_k={n.node_id.value:max([s.temperature_k for s in state.inputs.initial_checkpoint.spacecraft.thermal.node_states if s.node_id==n.node_id]+
            [t.end_temperature_k for _,p in parts for t in p.thermal_coupling_result.thermal_result.node_transitions if t.node_id==n.node_id]) for n in nodes},
        wire_loss_wh=sum((p.electrical.pv_wire_loss_w+p.electrical.receiving_wire_loss_w)*p.eps_result.battery.dt_seconds/3600 for _,p in parts))
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--variant',default='baseline');p.add_argument('--input',type=Path);p.add_argument('--output-directory',type=Path,required=True)
    p.add_argument('--resume',type=Path);p.add_argument('--packet-sha256');p.add_argument('--input-digest')
    a=p.parse_args();out=a.output_directory;out.mkdir(exist_ok=False);reconstruction=None
    if a.resume:state,reconstruction=restore_construction_continuation(a.resume,expected_packet_sha256=a.packet_sha256,expected_input_digest=a.input_digest)
    else:
        inputs=inputs_from_json(a.input.read_text(encoding='utf-8')) if a.input else make_inputs(a.variant)
        (out/'inputs.json').write_text(inputs_to_json(inputs)+'\n',encoding='utf-8',newline='\n')
        state=start_construction_mission(inputs)
    while state.cursor<len(state.inputs.actions):
        state=advance_construction_mission(state)
        if not a.resume and state.cursor==3:
            h=save_construction_continuation(out/'prefix.packet.json',state)
            (out/'prefix.binding.json').write_text(json.dumps(dict(packet_sha256=h,input_digest=state.construction.input_digest),indent=2)+'\n')
    (out/'science.json').write_bytes(scientific_bytes(state))
    (out/'summary.json').write_text(json.dumps(dict(**report(state),reconstruction=reconstruction),default=str,indent=2)+'\n',encoding='utf-8')
    (out/'balances.json').write_text(json.dumps([dict(**identity,**cut_balance(part)) for identity,part in actual_parts(state)],indent=2)+'\n')
    print(json.dumps(dict(clock=state.context.simulation_time_seconds,receipts=len(state.context.ground_data_delivery_state.completed_deliveries),construction=report(state)['construction']),default=str))

if __name__=='__main__':main()
