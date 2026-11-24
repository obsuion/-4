"""Small causal perturbations through accepted protected physical executors."""

import argparse
from dataclasses import replace
from pathlib import Path

from examples.v5_ms_comparison import external, write_json, boundary
from ops_sim.v5.comparison_campaign import build_inputs_program, parameter
from ops_sim.v5.campaign_contract import PlannedAction
from ops_sim.v5.campaign_continuation import start_campaign, planning_boundary
from ops_sim.v5.campaign_controller import execute_selected
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.communications import ServiceableGroundContact
from ops_sim.v5.contact_execution import ConsumedContacts
from ops_sim.v5.ids import GroundContactId, GroundStationId
from ops_sim.v5.ms_product import size_ms_grid


def prepare(kind,value):
    inputs,p=build_inputs_program("D-E1")
    cfg=inputs.spacecraft_configuration
    origin=p.initial_checkpoint.restore(inputs)
    if kind=="storage":
        cfg=replace(cfg,storage=replace(cfg.storage,usable_capacity_gb=parameter("storage.usable-capacity","GB",value)))
    elif kind=="rate":
        cfg=replace(cfg,communications=replace(cfg.communications,nominal_downlink_data_rate_bps=parameter("communications.nominal-downlink-data-rate","bit/s",value)))
    elif kind=="power-limit":
        cfg=replace(cfg,eps=replace(cfg.eps,battery=replace(cfg.eps.battery,max_discharge_output_power_w=parameter("eps.battery.max-discharge-output-power","W",value))))
    elif kind in ("generation","capacity"):
        cfg=replace(cfg,eps=replace(cfg.eps,solar_array=replace(cfg.eps.solar_array,
            nominal_generation_w=parameter("eps.solar-array.nominal-generation","W",value if kind=="generation" else 90.))))
        p=replace(p,forcing=tuple(replace(f,standby=replace(f.standby,sunlit=True)) for f in p.forcing))
        if kind=="capacity":
            cfg=replace(cfg,eps=replace(cfg.eps,battery=replace(cfg.eps.battery,
                nominal_energy_wh=parameter("eps.battery.nominal-energy","Wh",value))))
            origin.spacecraft_state.battery.energy_wh=9.
    elif kind=="sizing":
        optical=replace(cfg.payload.optical_acquisition,acquisition_bits_per_sample=parameter("payload.optical.acquisition-bits-per-sample","bit/sample",value))
        cfg=replace(cfg,payload=replace(cfg.payload,optical_acquisition=optical))
        p=replace(p,opportunities=tuple(replace(o,acquisition=replace(o.acquisition,sizing=size_ms_grid(
            o.acquisition.sizing.footprint,o.acquisition.sizing.spacing_x_m,o.acquisition.sizing.spacing_y_m,
            o.acquisition.sizing.captured_channels,value))) for o in p.opportunities))
    else: raise ValueError("unsupported probe")
    inputs=replace(inputs,spacecraft_configuration=cfg)
    origin.inputs=inputs
    p=replace(p,initial_checkpoint=CheckpointState.from_context(origin))
    state=start_campaign(inputs,p)
    view,_=planning_boundary(inputs,p,state.memory)
    action=PlannedAction("standby" if kind in ("generation","capacity") else "imaging",
        "causal-wait" if kind in ("generation","capacity") else "task05c-op0",0,60,(),"isolated declared parameter perturbation")
    outcome,acq,previous,consumed=execute_selected(state.context,view,action,p.initial_attitude,ConsumedContacts(()))
    transmitted=0
    if kind=="rate":
        contact=ServiceableGroundContact(GroundContactId("causal-contact"),GroundStationId("causal-station"),60,70)
        view=replace(view,contacts=(contact,))
        selected=PlannedAction("contact",contact.contact_id.value,60,70,(acq.record.record_id,),"isolated rate perturbation")
        outcome,_,_,_=execute_selected(state.context,view,selected,previous,consumed)
        transmitted=sum(s.transmitted_bits for s in outcome.services)
    return dict(parameter=kind,value=value,acquired=acq is not None,
        acquired_bits=0 if acq is None else acq.plan.sizing.stored_bits,transmitted_bits=transmitted,
        final=boundary(state.context))


def checks():
    perturbations={"sizing":(8,4),"storage":(4.,.001),"rate":(30000000.,15000000.),
        "generation":(90.,45.),"capacity":(10.,20.),"power-limit":(100.,20.)}
    rows={key:[prepare(key,v) for v in values] for key,values in perturbations.items()}
    assert rows["sizing"][0]["acquired_bits"]==2*rows["sizing"][1]["acquired_bits"]
    assert [r["acquired"] for r in rows["storage"]]==[True,False]
    assert [r["transmitted_bits"] for r in rows["rate"]]==[300000000,150000000]
    assert rows["generation"][0]["final"]["energy_wh"]>rows["generation"][1]["final"]["energy_wh"]
    assert rows["capacity"][0]["final"]["energy_wh"]==10.
    assert rows["capacity"][1]["final"]["energy_wh"]>10.
    assert [r["acquired"] for r in rows["power-limit"]]==[True,False]
    return dict(status="passed",scope="Isolated synthetic causal wiring probes; binding in main campaign assessed separately",rows=rows)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    write_json(external(args.output),checks())
