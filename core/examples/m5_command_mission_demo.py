"""B48 command-informed synthetic NOMINAL_LONG mission and causal restart CLI."""
from dataclasses import replace,asdict
from pathlib import Path
import argparse,json
from examples.m5_rolling_mission_demo import make_inputs as received_inputs,summary
from ops_sim.v5.command_estimation import CommandRollingRoot
from ops_sim.v5.command_document import inputs_to_json,inputs_from_json
from ops_sim.v5.rolling_execution import start_rolling,step_rolling,paid_scientific_bytes
from ops_sim.v5.rolling_document import save_continuation,restore_continuation
from ops_sim.v5.construction_coupling import compile_construction
from ops_sim.v5.harness_mass import geometry_digest
from ops_sim.v5.long_mission_continuation import _scientific
from ops_sim.v5.long_mission_document import canonical_json


def make_inputs(variant='compact',scenario='C',wire='nominal'):
    if wire not in ('nominal','weakness','repair'):raise ValueError('declared single-area intervention')
    root=received_inputs(variant,scenario,600)
    if wire!='nominal':
        area=1e-10 if wire=='weakness' else 1e-6
        cfg=root.model.configuration
        lines=tuple(replace(l,wire=replace(l.wire,cross_section_m2=area)) if l.line_id=='payload-line' else l for l in cfg.lines)
        cfg=replace(cfg,lines=lines)
        compilation=compile_construction(root.model.assembly,cfg)
        branches={b.line_id:b for b in compilation.branches};index={l.line_id:l for l in cfg.lines}
        routes=tuple(replace(r,geometry_digest=geometry_digest(branches[r.line_id],index[r.line_id])) for r in root.model.augmentation.routes)
        augmentation=replace(root.model.augmentation,construction_digest=compilation.configuration_digest,routes=routes)
        root=replace(root,model=replace(root.model,configuration=cfg,augmentation=augmentation))
    return CommandRollingRoot(root)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--variant',choices=('compact','outboard'),default='compact')
    p.add_argument('--scenario',choices=('A','B','C'),default='C')
    p.add_argument('--wire',choices=('nominal','weakness','repair'),default='nominal')
    p.add_argument('--input',type=Path);p.add_argument('--output-directory',type=Path,required=True)
    p.add_argument('--resume',type=Path);p.add_argument('--packet-sha256');p.add_argument('--root-identity')
    p.add_argument('--checkpoint-on-pending',action='store_true');p.add_argument('--stop-after',type=int)
    a=p.parse_args();proof=None
    if a.resume:
        state,proof=restore_continuation(a.resume,expected_packet_sha256=a.packet_sha256,expected_root_identity=a.root_identity)
        root=state.root
    else:
        root=inputs_from_json(a.input.read_text(encoding='utf-8')) if a.input else make_inputs(a.variant,a.scenario,a.wire)
        state=start_rolling(root)
    out=a.output_directory;out.mkdir()
    (out/'inputs.json').write_text(inputs_to_json(root)+'\n',encoding='utf-8')
    saved=False
    while state.status=='ACTIVE' and (a.stop_after is None or len(state.decisions)<a.stop_after):
        try:state=step_rolling(state)
        except Exception as error:
            import traceback
            original=traceback.format_exc()
            (out/'original-exception.txt').write_text(original,encoding='utf-8')
            from ops_sim.v5.mission_diagnosis import capture_model_exception
            try:
                evidence,finding=capture_model_exception(state,error)
                (out/'termination.json').write_text(canonical_json(_scientific((evidence,finding)))+'\n',encoding='utf-8')
            except Exception:
                (out/'termination-capture-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
            raise
        if a.checkpoint_on_pending and not saved and any(c.kind in ('CAPTURE','CONTACT') for c in state.knowledge.pending()):
            sha=save_continuation(out/'pending.packet.json',state);saved=True
            (out/'pending.binding.json').write_text(json.dumps(dict(packet_sha256=sha,root_identity=state.root_identity,
                clock=state.physical.context.simulation_time_seconds,decisions=len(state.decisions),
                actual_records=len(state.physical.context.spacecraft_state.data_storage.stored_records),
                received_records=len(state.knowledge.observation.onboard_records),
                partial_bits=[p.transmitted_equivalent_bits for p in state.physical.context.ground_data_delivery_state.partial_transfers],
                pending=[asdict(c) for c in state.knowledge.pending()]),indent=2)+'\n')
    (out/'science.json').write_bytes(paid_scientific_bytes(state))
    (out/'diagnosis.json').write_text(canonical_json(_scientific(state.diagnosis))+'\n',encoding='utf-8')
    result=summary(state);result['reconstruction']=proof
    result.update(estimation_method=root.estimation.method,controller_method=root.controller_method,
        reconciliation=[asdict(r) for r in state.reconciliations],diagnosis_findings=len(state.diagnosis.findings),
        commanded_intents=[dict(command_id=i.command_id,kind=i.action.kind,issued=i.issued_at_seconds,expected_end=i.expected_end_seconds,
            assumption=i.prediction_status,profile_identity=i.profile_identity) for i in state.intents])
    (out/'summary.json').write_text(json.dumps(result,default=str,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({n:result[n] for n in ('status','clock','acquired','receipts','credited_products','decisions','forecasts','diagnosis_findings')},default=str))


if __name__=='__main__':main()
