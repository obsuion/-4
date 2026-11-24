"""Actual finite weak-wire diagnosis -> declared repairs -> mission -> selection.

Run one catalogue case per bounded process; full cases are durable immediately.
The study input is input-only. External evidence bindings are explicit CLI args.
"""
from pathlib import Path
from dataclasses import asdict
from hashlib import sha256
import argparse, json, traceback
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.design_repair import DesignRepairSpec, source_identity
from ops_sim.v5.design_repair_document import inputs_from_json, inputs_to_json
from ops_sim.v5.design_repair_study import (start_study, begin_case, step_case, finish_case,
    record_case_failure, export_study, publish_metadata, scientific_study, _observe, metrics_from_science)
from ops_sim.v5.design_repair_continuation import save_study, restore_study, reuse_completed_case
from ops_sim.v5.rolling_execution import start_rolling, paid_scientific_bytes
from ops_sim.v5.long_mission_document import canonical_json


def make_spec():
    return DesignRepairSpec(make_inputs(wire='weakness'), source_identity())


def bindings_from_packet(packet, directory):
    # Convenience for a locally trusted prior packet. Remote/shared reuse must
    # supply independently retained external hashes; the CLI's explicit packet
    # hash binds this local extraction, not a newly self-certified cache.
    data=json.loads(Path(packet).read_bytes())
    return {b['index']:dict(directory=str(Path(directory)/'cases'/f"{b['index']:02d}"),
        case_sha256=b['case_sha256'],scientific_sha256=b['scientific_sha256']) for b in data['completed']}


def run_one_case(state, directory, *, checkpoint_partial=False):
    index=len(state.cases) if state.active is None else state.active_index
    out=Path(directory)
    if state.active is None:begin_case(state,index)
    saved=False
    try:
        while state.active.status=='ACTIVE':
            step_case(state)
            publish_metadata(state,out/'boundaries'/f'{index:02d}-{len(state.active.decisions):02d}.json',
                dict(index=index,clock=state.active.physical.context.simulation_time_seconds,
                    status=state.active.status,case_paid_work=asdict(state.active.work),study_paid_work=asdict(state.work)))
            if checkpoint_partial and not saved and len(state.cases)>=1 and state.active.physical.context.ground_data_delivery_state.partial_transfers and any(c.kind=='CONTACT' for c in state.active.knowledge.pending()):
                active=out/'cases'/f'{index:02d}'/'partial.rolling.json';active.parent.mkdir(parents=True,exist_ok=True)
                packet=out/'packets'/f'partial-{index:02d}.study.json'
                h=save_study(packet,state,rolling_packet_path=active)
                publish_metadata(state,out/'packets'/f'partial-{index:02d}.binding.json',dict(study_packet_sha256=h,
                    active_packet_sha256=sha256(active.read_bytes()).hexdigest(),spec_identity=state.spec.identity,
                    source_identity=state.spec.source_identity,clock=state.active.physical.context.simulation_time_seconds,
                    completed_cases=len(state.cases),pending=[c.kind for c in state.active.knowledge.pending()],
                    partial_bits=[p.transmitted_equivalent_bits for p in state.active.physical.context.ground_data_delivery_state.partial_transfers]))
                saved=True
        record=finish_case(state,out)
    except Exception as error:
        # Do not conceal the original failure if the diagnostic itself fails.
        error_text=traceback.format_exc();p=out/'failures';p.mkdir(exist_ok=True,parents=True)
        (p/f'{index:02d}-original.txt').write_text(error_text,encoding='utf-8')
        try:record_case_failure(state,out,error)
        except Exception:(p/f'{index:02d}-capture.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    packet=out/'packets'/f'after-{index:02d}.study.json'
    h=save_study(packet,state)
    publish_metadata(state,out/'packets'/f'after-{index:02d}.binding.json',dict(packet_sha256=h,
        specification_identity=state.spec.identity,source_identity=state.spec.source_identity))
    export_study(state,out,f'after-{index:02d}')
    print(canonical_json(dict(index=index,terminal=record['terminal'],credited=record['metrics']['credited_products'],
        status=state.status,completed=len(state.cases),selected=state.selected_variant)))
    return state


def confirm_selected(state,directory):
    if len(state.cases)!=len(state.catalogue) or state.selected_variant is None or state.active is not None:
        raise ValueError('complete selected catalogue required for fresh confirmation')
    v=next(v for v in state.catalogue if v.manifest.variant_identity==state.selected_variant)
    selected=next(r for r in state.cases if r['variant_identity']==state.selected_variant)
    state.work.reserve_case(state.spec)
    state.active_index=v.index;state.active=start_rolling(v.root);_observe(state)
    while state.active.status=='ACTIVE':step_case(state)
    raw=paid_scientific_bytes(state.active);_observe(state)
    state.work.retained_case_bytes+=len(raw)
    out=Path(directory);out.mkdir(parents=True)
    (out/'science.json').write_bytes(raw)
    h=sha256(raw).hexdigest();metrics=metrics_from_science(raw,v.root,expected_scientific_sha256=h)
    if h!=selected['scientific_sha256'] or canonical_json(metrics)!=canonical_json(selected['metrics']):
        raise ValueError('FRESH_ORIGINAL_ROOT_CONFIRMATION_MISMATCH')
    from ops_sim.v5.command_document import inputs_to_json as root_to_json
    publish_metadata(state,out/'root.json',json.loads(root_to_json(v.root)))
    publish_metadata(state,out/'confirmation.json',dict(status='PASS',method='FRESH_ORIGINAL_ROOT_ACTUAL_EXECUTION',
        root_identity=v.manifest.candidate_root_identity,scientific_sha256=h,selected_scientific_sha256=selected['scientific_sha256'],
        exact_same_runtime_science=True,metrics=metrics,case_work=asdict(state.active.work),study_work=asdict(state.work)))
    print(canonical_json(dict(confirmation='PASS',credited=metrics['credited_products'],scientific_sha256=h)))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path);p.add_argument('--write-input',type=Path)
    p.add_argument('--output-directory',type=Path)
    p.add_argument('--resume',type=Path);p.add_argument('--packet-sha256');p.add_argument('--spec-identity');p.add_argument('--source-identity')
    p.add_argument('--completed-bindings',type=Path);p.add_argument('--previous-directory',type=Path)
    p.add_argument('--active-packet',type=Path);p.add_argument('--active-sha256')
    p.add_argument('--future-cache-bindings',type=Path);p.add_argument('--confirm',action='store_true')
    p.add_argument('--checkpoint-partial',action='store_true');p.add_argument('--all-cases',action='store_true')
    a=p.parse_args()
    if a.write_input:
        if a.resume or a.output_directory:raise ValueError('input-only operation is separate')
        spec=make_spec()
        with a.write_input.open('x',encoding='utf-8') as f:f.write(inputs_to_json(spec))
        print(spec.identity);return
    if a.output_directory is None:raise ValueError('output directory required')
    out=a.output_directory;out.mkdir(parents=True,exist_ok=True)
    if a.resume:
        completed={int(k):v for k,v in json.loads(a.completed_bindings.read_bytes()).items()} if a.completed_bindings else bindings_from_packet(a.resume,a.previous_directory or out)
        state,proof=restore_study(a.resume,expected_packet_sha256=a.packet_sha256,
            expected_spec_identity=a.spec_identity,expected_source_identity=a.source_identity,
            completed_outputs=completed,active_packet=a.active_packet,expected_active_packet_sha256=a.active_sha256)
        publish_metadata(state,out/('confirmation-restore.json' if a.confirm else 'restore-'+str(len(state.cases))+'.json'),proof)
    else:
        spec=inputs_from_json(a.input.read_text(encoding='utf-8')) if a.input else make_spec()
        state=start_study(spec)
    if a.confirm:
        confirm_selected(state,out/'confirmation');return
    run_one_case(state,out,checkpoint_partial=a.checkpoint_partial)
    if a.future_cache_bindings:
        binds={int(k):v for k,v in json.loads(a.future_cache_bindings.read_bytes()).items()}
        if set(binds)!=set(range(len(state.cases),len(state.catalogue))):raise ValueError('exact future complete cache set')
        for index in sorted(binds):
            b=binds[index];reuse_completed_case(state,index,b['directory'],expected_case_sha256=b['case_sha256'],expected_scientific_sha256=b['scientific_sha256'])
        export_study(state,out,'resumed-final')
        save_study(out/'packets/resumed-final.study.json',state)
    elif a.all_cases:
        while len(state.cases)<len(state.catalogue):run_one_case(state,out)


if __name__=='__main__':main()
