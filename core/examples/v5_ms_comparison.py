"""Task05C external-artifact runner using accepted causal version-7 APIs.

Run individual cases in separate processes. Completed identical cases may be
reused only after both immutable input and implementation/environment checks.
"""

import argparse
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import sys
from time import perf_counter
import traceback

from ops_sim.v5.campaign_continuation import start_campaign, advance_campaign, campaign_summary, planning_boundary
from ops_sim.v5.campaign_controller import execute_selected
from ops_sim.v5.comparison_campaign import build_inputs_program, HORIZON
from ops_sim.v5.comparison_manifest import manifest, derive_hardware, digest
from ops_sim.v5.comparison_evidence import weighted_score
from ops_sim.v5.contact_execution import ContactOutcome, ConsumedContacts
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content, decode_content
from ops_sim.v5.experiment_provenance import capture_provenance
from ops_sim.v5.ms_product import assess_ms_product


ROOT = Path(__file__).resolve().parents[1]


def write_json(path, content):
    path.write_text(json.dumps(content,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")


def external(path):
    path = Path(path).resolve()
    if path == ROOT or ROOT in path.parents:
        raise ValueError("experiment artifacts must remain outside the repository")
    return path


def boundary(context):
    s = context.spacecraft_state
    return dict(seconds=context.simulation_time_seconds,energy_wh=s.battery.energy_wh,
        temperatures_k={n.node_id.value:n.temperature_k for n in s.thermal.node_states},
        queued_bits=sum(int(r.stored_equivalent_bits) for r in s.data_storage.stored_records),
        partial_bits=sum(int(r.transmitted_equivalent_bits) for r in context.ground_data_delivery_state.partial_transfers),
        delivered_bits=sum(int(d.record.stored_equivalent_bits) for d in context.ground_data_delivery_state.completed_deliveries))


def finish(report, inputs, program, boundaries, actions):
    priorities = {r.product.request.request_id.value:r.product.request.priority_weight for r in program.requests}
    report.update(weighted_score(report["requests"],priorities))
    report["boundaries"] = boundaries
    report["selected_actions"] = actions
    report["acquired_bits"] = sum(a["bits"] for r in report["requests"] for a in r.get("acquisitions",[]))
    report["final_custody"] = boundaries[-1]
    for r in report["requests"]:
        c = r.get("exact_completion_seconds")
        r["exact_latency_seconds"] = None if c is None else str(Fraction(c["numerator"],c["denominator"])-r["release_seconds"])
    return report


def physical_samples(outcomes):
    """Actual accepted samples at exact rational physical times, no interpolation."""
    points={}
    for outcome in outcomes:
        if type(outcome) is ContactOutcome:
            traces=[(outcome.contact.start_time_seconds,s.trace.denominator,s.trace.samples) for s in outcome.segments]
        else:
            t=outcome.actual_trace
            traces=[(t.start_time_seconds,1<<t.subdivision_level,t.samples)]
        for origin,denominator,samples in traces:
            for sample in samples:
                seconds=Fraction(origin)+Fraction(sample.offset_numerator_seconds,denominator)
                row=dict(seconds=str(seconds),energy_wh=sample.battery_energy_wh,
                    temperatures_k={n.value:t for n,t in sample.temperatures_k})
                if seconds in points and points[seconds]!=row:
                    raise ValueError("physical sample disagrees at an action/segment boundary")
                points[seconds]=row
    return [points[t] for t in sorted(points)]


def rolling(inputs, program, output, *, restart_boundary=False, restored=None):
    state = start_campaign(inputs,program) if restored is None else restored
    boundaries = [boundary(state.context)]
    saved = False
    while state.context.simulation_time_seconds < HORIZON:
        state = advance_campaign(state)  # Includes the accepted full causal replay validation.
        boundaries.append(boundary(state.context))
        if restart_boundary and not saved and state.context.ground_data_delivery_state.partial_transfers:
            (output/"partial-boundary.bundle.json").write_text(create_bundle(state,repository_root=ROOT).to_json(),encoding="utf-8")
            saved = True
    if restart_boundary and not saved:
        raise ValueError("requested actual partial boundary was absent; select another case explicitly")
    report = campaign_summary(state)
    report["physical_samples"] = physical_samples(d.outcome for d in state.memory.decisions)
    actions = [canonical_content(d.plan.actions[0]) for d in state.memory.decisions]
    return finish(report,inputs,program,boundaries,actions)


def fixed(inputs, program, reference):
    """Replay a declared requested sequence through protected physical executors.

    This is deliberately not a new rolling controller/history. The reference
    request intervals and IDs are held fixed; protection remains enabled.
    """
    state = start_campaign(inputs,program)
    view,_ = planning_boundary(inputs,program,state.memory)
    view = replace(view,requests=program.requests,opportunities=program.opportunities,contacts=program.contacts,
        forcing=program.forcing,until_seconds=HORIZON)
    context = state.context
    previous,consumed = program.initial_attitude,ConsumedContacts(())
    boundaries,outcomes,acquisitions = [boundary(context)],[],[]
    for wire in reference["selected_actions"]:
        action = decode_content(wire)
        if context.simulation_time_seconds != action.start_seconds:
            raise ValueError("fixed sequence does not partition physical time")
        outcome,acq,previous,consumed = execute_selected(context,view,action,previous,consumed)
        outcomes.append(outcome)
        if acq is not None: acquisitions.append(acq)
        boundaries.append(boundary(context))
    contacts = tuple(o for o in outcomes if type(o) is ContactOutcome)
    requests = []
    for request in program.requests:
        product = request.product
        acq = tuple(a for a in acquisitions if a.plan.request.request_id == product.request.request_id)
        assessment = assess_ms_product(product,acq,context.ground_data_delivery_state,contacts,context.simulation_time_seconds)
        completion = next((Fraction(o.contact.start_time_seconds)+s.end_offset.fraction for o in contacts
            for s in o.services if s.completed and any(a.record.record_id == s.record.record_id for a in acq)),None)
        requests.append(dict(request_id=product.request.request_id.value,credited_products=assessment.credited_products,
            release_seconds=request.release_seconds,status=assessment.status,
            exact_completion_seconds=None if completion is None else dict(numerator=completion.numerator,denominator=completion.denominator),
            acquisitions=[dict(bits=a.plan.sizing.stored_bits) for a in acq]))
    report = dict(status="completed-horizon" if context.simulation_time_seconds == HORIZON else "incomplete",
        requests=requests,outcomes=canonical_content(tuple(outcomes)),input_digest=experiment_input_digest(inputs,program),
        physical_samples=physical_samples(outcomes))
    return finish(report,inputs,program,boundaries,reference["selected_actions"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hardware",required=True)
    parser.add_argument("--scenario",choices=("S1","S2"),required=True)
    parser.add_argument("--level",type=int,required=True)
    parser.add_argument("--mode-factor",type=float,default=1.)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--protocol",type=Path)
    parser.add_argument("--fixed-reference",type=Path)
    parser.add_argument("--partial-boundary",action="store_true")
    parser.add_argument("--resume",type=Path)
    args = parser.parse_args(argv)
    output = external(args.output)
    output.mkdir(parents=True,exist_ok=True)
    inputs,program = build_inputs_program(args.hardware,args.scenario,level=args.level,mode_factor=args.mode_factor)
    provenance = capture_provenance(ROOT)
    identity = experiment_input_digest(inputs,program)
    reference = None if args.fixed_reference is None else json.loads(args.fixed_reference.read_text(encoding="utf-8"))
    if reference is not None and (reference.get("hardware")!=args.hardware or reference.get("scenario")!=args.scenario
            or reference.get("mode_factor")!=args.mode_factor or reference.get("status")!="completed-horizon"
            or reference.get("run_key",{}).get("compatibility_digest")!=provenance["compatibility_digest"]):
        raise ValueError("fixed reference must be a completed matching hardware/scenario/mode/source run")
    reference_digest = None if reference is None else digest(reference)
    protocol = None if args.protocol is None else json.loads(args.protocol.read_text(encoding="utf-8"))
    protocol_digest = None if protocol is None else digest(protocol)
    if protocol is not None:
        if protocol["compatibility_digest"] != provenance["compatibility_digest"]:
            raise ValueError("frozen protocol code/environment mismatch")
        if args.hardware not in protocol["hardware"] or args.level not in protocol["levels"] or args.mode_factor not in protocol["mode_factors"]:
            raise ValueError("case is not admitted by frozen protocol")
    key = dict(input_digest=identity,compatibility_digest=provenance["compatibility_digest"],
        protocol_digest=protocol_digest,fixed_reference_digest=reference_digest,
        resume_digest=None if args.resume is None else digest(args.resume.read_text(encoding="utf-8")))
    if (output/"result.json").exists():
        old = json.loads((output/"result.json").read_text(encoding="utf-8"))
        if old.get("run_key") != key or old.get("status") != "completed-horizon":
            raise ValueError("existing output is different or incomplete; preserve it and use a distinct run directory")
        if args.partial_boundary and not (output/"partial-boundary.bundle.json").is_file():
            raise ValueError("matching run has no saved restart evidence")
        print("REUSED",output,flush=True)
        return 0
    write_json(output/"inputs.json",dict(inputs=canonical_content(inputs),program=canonical_content(program)))
    write_json(output/"invocation.json",dict(argv=sys.argv,python=sys.version,executable=sys.executable,
        provenance=provenance,run_key=key,hardware=derive_hardware(manifest(),args.hardware,args.mode_factor)))
    start = perf_counter()
    try:
        restored = None if args.resume is None else ExperimentBundle.from_json(args.resume.read_text(encoding="utf-8")).restore(
            repository_root=ROOT,expected_inputs=inputs,expected_program=program)
        report = (fixed(inputs,program,reference) if reference is not None else
            rolling(inputs,program,output,restart_boundary=args.partial_boundary,restored=restored))
        if capture_provenance(ROOT)["compatibility_digest"] != provenance["compatibility_digest"]:
            raise ValueError("source/environment changed during execution")
        report.update(run_key=key,hardware=args.hardware,scenario=args.scenario,level=args.level,mode_factor=args.mode_factor,
            kind="fixed-requested-sequence" if reference is not None else "rolling",runtime_seconds=perf_counter()-start)
        write_json(output/"result.json",report)
        print(json.dumps(dict(status=report["status"],runtime_seconds=report["runtime_seconds"],output=str(output))),flush=True)
        return 0 if report["status"] == "completed-horizon" else 2
    except Exception:
        (output/"failure.log").write_text(traceback.format_exc(),encoding="utf-8")
        write_json(output/"failed-status.json",dict(status="failed-or-incomplete",run_key=key,runtime_seconds=perf_counter()-start))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
