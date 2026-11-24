"""Task05D separate synthetic study builder/runner; accepted V5 owners unchanged."""

import argparse
from dataclasses import asdict, replace
from fractions import Fraction
import json
from math import fsum
from pathlib import Path
from time import perf_counter
import traceback

from examples.v5_ms_comparison import ROOT, external, write_json, boundary, finish, physical_samples
from ops_sim.v5 import ids
from ops_sim.v5.campaign_contract import ReleasedMSRequest, RollingPolicy
from ops_sim.v5.campaign_continuation import start_campaign, advance_campaign, campaign_summary, planning_boundary
from ops_sim.v5.campaign_controller import execute_selected
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.communications import ServiceableGroundContact
from ops_sim.v5.comparison_campaign import build_inputs_program as accepted_inputs
from ops_sim.v5.comparison_manifest import manifest, derive_hardware, digest
from ops_sim.v5.contact_execution import ContactOutcome, ConsumedContacts
from ops_sim.v5.experiment_bundle import experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content, decode_content
from ops_sim.v5.experiment_provenance import capture_provenance
from ops_sim.v5.ms_product import assess_ms_product


HARDWARE = ('J-E1', 'J-E2', 'J-E3', 'J-E4')
SCENARIOS = {
    'A': dict(horizon=14400, initial_fraction=.5, sunlit=False, incidence_deg=0.,
              starts=(10800,11100,11400,11700,12000,12300), window=300, contact=(13000,13030), deadline=13200),
    'B': dict(horizon=600, initial_fraction=.01, sunlit=True, incidence_deg=60.,
              starts=(0,60,120,180,240,300), window=60, contact=(360,390), deadline=500),
}
POLICY = RollingPolicy(1,14400,1800,3,32,64,4096)
ASSUMPTIONS = (
    'Task05D supplemental synthetic EPS stress study; not a realistic eclipse, orbit reconstruction or full V5.',
    'Accepted JSS56 five-channel sizing, 6.5 m samples, 77 km swath, 12 bit/sample, 6 GB storage, 160 Mbit/s useful ceiling unchanged.',
    'All six 10 km x 30 km B/G/R/NIR requests published at t=0, priorities 3,2,1,3,2,1, denominator 12; physical acquisitions 60 s.',
    'J-E1..E4 retain accepted sourced BP8/TSP allocations, efficiencies, limits and thermal normalization. Hardware IDs retain their source namespace.',
    'Common 12 W baseline plus separate mutually exclusive imaging/transmitter increments 93 W times 1 or .5; assumptions, not flight values or bounds.',
    'Initial fraction applies to recommended working-energy window once; retention 1, empty custody and zero throughput. One percent is a synthetic stress, not a flight recommendation.',
    'Held nadir attitude and idealized zero-latency boundary knowledge unchanged; all future opportunities are legitimately known from published requests.',
    'Each thermal node retains 50000 J/K, emissivity .8, area .2 m2, sink 250 K; 293.15 K initially, no conductive links or external absorbed heat.',
    'Operating 270..320 K and survival 250..340 K unchanged; electrical heat routes unchanged. Zero ageing coefficients, no lifetime inference.',
    'One declared synthetic serviceable 30 s contact; no RF, availability or orbit proof. Unused contact time has baseline load through the accepted executor.',
    'No forcing or controller tuning by hardware. Protection, causal replay and work bounds stay enabled; incomplete output is never a zero-score result.',
    'Levels 1 and 2 change only internal subdivisions (2 and 4); physical intervals and common policy remain unchanged.',
)


def build_inputs_program(hardware, scenario, *, level=2, mode_factor=1.):
    if type(hardware) is not str or hardware not in HARDWARE:
        raise ValueError('Task05D requires one of all four J allocations')
    if type(scenario) is not str or scenario not in SCENARIOS:
        raise ValueError('unknown Task05D scenario')
    if type(level) is not int or level not in (1,2):
        raise ValueError('Task05D admits levels 1 and 2 only')
    if type(mode_factor) not in (int,float) or mode_factor not in (1.,.5):
        raise ValueError('Task05D admits mode factors 1 and .5 only')
    s = SCENARIOS[scenario]
    old, base = accepted_inputs(hardware, level=level, mode_factor=mode_factor)
    context = base.initial_checkpoint.restore(old)
    world = replace(old.common_world, world_id=ids.WorldId('task05d-world-'+scenario.lower()),
                    scenario_id=ids.ScenarioId('task05d-'+scenario.lower()), horizon_seconds=s['horizon'])
    env = replace(old.environment_config, environment_id=ids.EnvironmentId('task05d-forcing-'+scenario.lower()))
    model = replace(old.model_manifest, manifest_id=ids.ModelManifestId('task05d-'+hardware.lower()+'-'+scenario.lower()),
                    environment_id=env.environment_id, scenario_id=world.scenario_id, world_id=world.world_id)
    inputs = replace(old, common_world=world, scenario_config=replace(old.scenario_config, scenario_id=world.scenario_id),
                     environment_config=env, model_manifest=model)
    context = replace(context, inputs=inputs)
    capacity = inputs.spacecraft_configuration.eps.battery.nominal_energy_wh.value
    context.spacecraft_state.battery.energy_wh = capacity*s['initial_fraction']
    requests, opportunities = [], []
    for i,(released,item,start) in enumerate(zip(base.requests,base.opportunities,s['starts'])):
        product = released.product
        request = replace(product.request, request_id=ids.ImagingRequestId(f'task05d-r{i}'),
                          target_id=ids.GroundTargetId(f'task05d-target{i}'))
        footprint = replace(product.footprint, region_id=f'task05d-region{i}')
        product = replace(product, request=request, capture_group=f'task05d-capture{i}', footprint=footprint,
                          acquisition_start_seconds=start, acquisition_end_seconds=start+s['window'],
                          delivery_deadline_seconds=s['deadline'])
        opportunity = replace(item.opportunity, opportunity_id=ids.ObservationOpportunityId(f'task05d-op{i}'),
                              request_id=request.request_id, window_start_seconds=start, window_end_seconds=start+s['window'])
        acquisition = replace(item.acquisition, request=request, capture_group=product.capture_group,
                              sizing=replace(item.acquisition.sizing, footprint=footprint))
        candidate = replace(item.candidate, maneuver_candidate=replace(item.candidate.maneuver_candidate, opportunity=opportunity))
        requests.append(ReleasedMSRequest(product,0))
        opportunities.append(replace(item, candidate=candidate, acquisition=acquisition))
    contact = ServiceableGroundContact(ids.GroundContactId('task05d-contact-'+scenario.lower()),
        ids.GroundStationId('task05d-declared-station'), *s['contact'])
    forcing = replace(base.forcing[0], end_seconds=s['horizon'], standby=replace(base.forcing[0].standby,
        sunlit=s['sunlit'], incidence_angle_deg=s['incidence_deg'],
        rationale=f'Task05D {scenario}: prescribed constant illumination/incidence, 12 W baseline; no external heat'))
    description = (f'Scenario {scenario}: horizon {s["horizon"]} s, initial working-energy fraction {s["initial_fraction"]}; '
        f'sunlit={s["sunlit"]}, incidence={s["incidence_deg"]} deg; acquisition windows {s["starts"]} plus {s["window"]} s; '
        f'contact {s["contact"]}, inclusive deadline {s["deadline"]} s.')
    program = replace(base, initial_checkpoint=CheckpointState.from_context(context), requests=tuple(requests),
        opportunities=tuple(opportunities), contacts=(contact,), forcing=(forcing,), policy=POLICY,
        assumptions=(*ASSUMPTIONS,description))
    return inputs,program


def independent_budgets():
    """Exact dimensional arithmetic predeclared before running the controller."""
    eta = Fraction(9,10)
    capacities = [344,258,172,86]
    pv = [Fraction(v,2) for v in (90,135,180,225)]
    return dict(units='W * s / 3600 / discharge_efficiency = Wh removed from battery',
        A_baseline_before_workload_wh=str(Fraction(12*10800,3600)/eta),
        A_initial_wh=[str(Fraction(c,2)) for c in capacities],
        B_initial_wh=[str(Fraction(c,100)) for c in capacities],
        B_half_reference_generation_w=list(map(str,pv)),
        B_six_nominal_image_discharge_wh=[str(max(Fraction(),105-p)*Fraction(360,3600)/eta) for p in pv],
        product_bits=1539*4616*5*12, all_product_bits=6*1539*4616*5*12,
        contact_capacity_bits=160000000*30, priority_denominator=12,
        caveat='Explanatory budgets, not product predictions. E4 nominal darkness also exceeds the independent 84.96 W bus discharge ceiling.')


def mechanism(report, outcomes, actions, initial):
    outcomes,actions = tuple(outcomes),tuple(actions)
    samples = physical_samples(outcomes)
    report['physical_samples'] = samples
    totals = {name:fsum(getattr(o.accounting,name) for o in outcomes) for name in asdict(outcomes[0].accounting)
              if name != 'numerical_substeps'}
    rows = []
    for action,outcome in zip(actions,outcomes):
        contact = type(outcome) is ContactOutcome
        reasons = ([dict(record_id=a.record_id.value,reasons=[r.value for r in a.availability.reasons],
                         action_unmet_w=a.availability.action_unmet_w,essential_unmet_wh=a.availability.essential_unmet_wh)
                    for a in outcome.attempts if not a.availability.available] if contact else
                   [r.value for r in outcome.availability.reasons])
        rows.append(dict(start_seconds=action.start_seconds,end_seconds=action.end_seconds,requested_kind=action.kind,
            actual_kind='contact' if contact else outcome.actual_kind.value,reasons=reasons,
            critical_energy_since_seconds=outcome.critical_energy_since_seconds,accounting=asdict(outcome.accounting),
            segments=[] if not contact else [dict(record_id=None if s.record_id is None else s.record_id.value,
                transmitter_on=s.transmitter_on,start_offset=str(s.trace.start_offset.fraction),
                end_offset=str(s.trace.end_offset.fraction),accounting=asdict(s.accounting)) for s in outcome.segments]))
    energies = [initial['energy_wh'],*(x['energy_wh'] for x in samples)]
    temperatures = {n:[initial['temperatures_k'][n],*(x['temperatures_k'][n] for x in samples)]
                    for n in initial['temperatures_k']}
    report['mechanism'] = dict(energy_ledger_wh=totals,initial_energy_wh=energies[0],min_energy_wh=min(energies),
        final_energy_wh=energies[-1],first_sampled_zero_energy_seconds=next((x['seconds'] for x in samples if x['energy_wh']==0),None),
        sampled_thermal_extrema_k={n:dict(min=min(v),max=max(v)) for n,v in temperatures.items()},
        actual_intervals=rows,forecast_rejections=[dict(at_seconds=d['received_at_seconds'],identity=i,reason=r)
            for d in report.get('decisions',[]) for i,r in d['rejections']],
        received_bits=sum(o.transmitted_bits for o in outcomes if type(o) is ContactOutcome))
    return report


def run(inputs,program,output,reference=None):
    state = start_campaign(inputs,program)
    initial = boundary(state.context)
    boundaries,outcomes,actions = [initial],[],[]
    horizon = inputs.common_world.horizon_seconds
    if reference is None:
        while state.context.simulation_time_seconds < horizon:
            state = advance_campaign(state)  # Accepted full causal replay stays enabled.
            d = state.memory.decisions[-1]
            outcomes.append(d.outcome); actions.append(d.plan.actions[0]); boundaries.append(boundary(state.context))
            write_json(output/'progress.json',dict(status='incomplete',boundary=boundaries[-1],decisions=len(actions)))
        report = campaign_summary(state)
    else:
        view,_ = planning_boundary(inputs,program,state.memory)
        view = replace(view,requests=program.requests,opportunities=program.opportunities,contacts=program.contacts,
                       forcing=program.forcing,until_seconds=horizon)
        previous,consumed,acquisitions = program.initial_attitude,ConsumedContacts(()),[]
        for wire in reference['selected_actions']:
            action = decode_content(wire)
            if state.context.simulation_time_seconds != action.start_seconds:
                raise ValueError('fixed requested sequence must partition the same physical horizon')
            outcome,acq,previous,consumed = execute_selected(state.context,view,action,previous,consumed)
            outcomes.append(outcome);actions.append(action);boundaries.append(boundary(state.context))
            if acq is not None: acquisitions.append(acq)
        contacts = tuple(o for o in outcomes if type(o) is ContactOutcome)
        requests = []
        for request in program.requests:
            product = request.product
            acq = tuple(a for a in acquisitions if a.plan.request.request_id==product.request.request_id)
            assessment = assess_ms_product(product,acq,state.context.ground_data_delivery_state,contacts,state.context.simulation_time_seconds)
            completion = next((Fraction(o.contact.start_time_seconds)+s.end_offset.fraction for o in contacts for s in o.services
                if s.completed and any(a.record.record_id==s.record.record_id for a in acq)),None)
            requests.append(dict(request_id=product.request.request_id.value,credited_products=assessment.credited_products,
                release_seconds=0,deadline_seconds=product.delivery_deadline_seconds,status=assessment.status,
                acquired=bool(acq),delivered=completion is not None,deadline_met=None if completion is None else completion<=product.delivery_deadline_seconds,
                exact_completion_seconds=None if completion is None else dict(numerator=completion.numerator,denominator=completion.denominator),
                acquisitions=[dict(bits=a.plan.sizing.stored_bits,record_id=a.record.record_id.value) for a in acq]))
        report = dict(status='completed-horizon' if state.context.simulation_time_seconds==horizon else 'incomplete',
                      requests=requests,checkpoint=CheckpointState.from_context(state.context).to_dict(),outcomes=canonical_content(tuple(outcomes)))
    report = finish(report,inputs,program,boundaries,[canonical_content(a) for a in actions])
    return mechanism(report,outcomes,actions,initial)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hardware',required=True,choices=HARDWARE);p.add_argument('--scenario',required=True,choices=SCENARIOS)
    p.add_argument('--level',required=True,type=int,choices=(1,2));p.add_argument('--mode-factor',required=True,type=float,choices=(1.,.5))
    p.add_argument('--output',required=True,type=Path);p.add_argument('--protocol',type=Path);p.add_argument('--fixed-reference',type=Path)
    args = p.parse_args(argv);output=external(args.output);output.mkdir(parents=True,exist_ok=True)
    if any((output/n).exists() for n in ('result.json','failed-status.json','invocation.json')):
        raise ValueError('preserve existing execution evidence; use explicit validated pilot reuse')
    started=perf_counter()
    try:
        inputs,program=build_inputs_program(args.hardware,args.scenario,level=args.level,mode_factor=args.mode_factor)
        provenance=capture_provenance(ROOT)
        protocol=None if args.protocol is None else json.loads(args.protocol.read_text(encoding='utf-8'))
        if protocol is not None:
            if protocol['compatibility_digest']!=provenance['compatibility_digest']:
                raise ValueError('frozen source/environment changed')
            if digest(protocol)!=(args.protocol.with_suffix('.sha256')).read_text().strip():
                raise ValueError('frozen protocol changed')
            kind='rolling' if args.fixed_reference is None else 'fixed'
            if not any((r['hardware'],r['scenario'],r['level'],r['mode_factor'],r['kind'])==
                (args.hardware,args.scenario,args.level,args.mode_factor,kind) for r in protocol['matrix']):
                raise ValueError('case is not admitted by the complete frozen matrix')
        reference=None if args.fixed_reference is None else json.loads(args.fixed_reference.read_text(encoding='utf-8'))
        if reference is not None and (reference['hardware']!=args.hardware or reference['scenario']!=args.scenario
            or reference['mode_factor']!=1 or args.mode_factor!=1 or reference['level']!=2 or reference['status']!='completed-horizon'
            or reference['run_key']['compatibility_digest']!=provenance['compatibility_digest']):
            raise ValueError('fixed reference must be matching completed finest nominal run')
        key=dict(input_digest=experiment_input_digest(inputs,program),compatibility_digest=provenance['compatibility_digest'],
            protocol_digest=None if protocol is None else digest(protocol),reference_digest=None if reference is None else digest(reference))
        write_json(output/'inputs.json',dict(inputs=canonical_content(inputs),program=canonical_content(program)))
        write_json(output/'invocation.json',dict(run_key=key,provenance=provenance,hardware=args.hardware,scenario=args.scenario,
            level=args.level,mode_factor=args.mode_factor,initial_energy_wh=program.initial_checkpoint.spacecraft.battery_energy_wh))
        report=run(inputs,program,output,reference)
        if capture_provenance(ROOT)['compatibility_digest']!=provenance['compatibility_digest']:
            raise ValueError('source/environment changed during execution')
        report.update(run_key=key,input_digest=key['input_digest'],hardware=args.hardware,scenario=args.scenario,level=args.level,
                      mode_factor=args.mode_factor,kind='rolling' if reference is None else 'fixed',runtime_seconds=perf_counter()-started)
        write_json(output/'result.json',report)
        print(json.dumps(dict(status=report['status'],runtime_seconds=report['runtime_seconds'])),flush=True)
        return 0 if report['status']=='completed-horizon' else 2
    except Exception:
        (output/'failure.log').write_text(traceback.format_exc(),encoding='utf-8')
        write_json(output/'failed-status.json',dict(status='failed-or-incomplete',runtime_seconds=perf_counter()-started))
        raise


if __name__=='__main__':
    raise SystemExit(main())
