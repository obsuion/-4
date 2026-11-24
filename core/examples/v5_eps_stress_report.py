"""Strict inventory, exact-time qualification and factual Task05D exports."""

import argparse
import csv
from fractions import Fraction
import json
from math import isfinite
from pathlib import Path

from examples.v5_ms_comparison import external,write_json
from examples.v5_eps_stress import HARDWARE,SCENARIOS,build_inputs_program
from ops_sim.v5.comparison_manifest import manifest,derive_hardware,digest
from ops_sim.v5.comparison_evidence import qualify_pair
from ops_sim.v5.experiment_bundle import experiment_input_digest
from ops_sim.v5.experiment_provenance import capture_provenance
from examples.v5_ms_comparison import ROOT


def case_id(hardware,scenario,level,factor,kind='rolling'):
    return f'{hardware}-{scenario}-L{level}-P{factor:g}-{kind}'


def matrix():
    rolling=[(h,s,l,f,'rolling') for h in HARDWARE for s in SCENARIOS for f in (1.,.5) for l in (1,2)]
    fixed=[(h,s,l,1.,'fixed') for h in ('J-E1','J-E4') for s in SCENARIOS for l in (1,2)]
    return rolling+fixed


def validate_result(r):
    if r['status']!='completed-horizon': raise ValueError('incomplete result is not a scored zero')
    horizon=SCENARIOS[r['scenario']]['horizon']
    if r['boundaries'][-1]['seconds']!=horizon: raise ValueError('missing completed horizon')
    requests=r['requests']
    if len(requests)!=6 or {x['request_id'] for x in requests}!={f'task05d-r{i}' for i in range(6)}:
        raise ValueError('six distinct common products required')
    if r['total_priority']!='12': raise ValueError('wrong common denominator')
    samples=r['physical_samples']
    times=[Fraction(x['seconds']) for x in samples]
    if not times or times[0]!=0 or times[-1]!=horizon or times!=sorted(set(times)):
        raise ValueError('physical samples must uniquely cover origin and horizon')
    for x in samples:
        if set(x['temperatures_k'])!={'bus','battery','payload'}: raise ValueError('missing thermal node')
        values=[x['energy_wh'],*x['temperatures_k'].values()]
        if any(type(v) not in (float,int) or not isfinite(v) for v in values): raise ValueError('nonfinite result')
    acquired=r['acquired_bits'];custody=r['final_custody'];received=r['mechanism']['received_bits']
    if acquired!=custody['queued_bits']+custody['delivered_bits']:
        raise ValueError('onboard/completed record custody does not conserve acquired bits')
    if received!=custody['partial_bits']+custody['delivered_bits']:
        raise ValueError('received bits do not match partial/completed delivery')
    if acquired>2557448640 or received>4800000000: raise ValueError('unexpected sizing/contact accounting')
    intervals=r['mechanism']['actual_intervals']
    if intervals[0]['start_seconds']!=0 or intervals[-1]['end_seconds']!=horizon:
        raise ValueError('actual execution omitted physical time')
    if any(a['end_seconds']!=b['start_seconds'] for a,b in zip(intervals,intervals[1:])):
        raise ValueError('actual execution has gaps')


def qualify(coarse,fine,capacity):
    validate_result(coarse);validate_result(fine)
    q=qualify_pair(coarse,fine,capacity)
    a={Fraction(x['seconds']) for x in coarse['physical_samples']}
    b={Fraction(x['seconds']) for x in fine['physical_samples']}
    q.update(coarse_unmatched_times=list(map(str,sorted(a-b))),fine_unmatched_times=list(map(str,sorted(b-a))),
        actual_kinds_and_intervals_equal=[(x['start_seconds'],x['end_seconds'],x['requested_kind'],x['actual_kind']) for x in coarse['mechanism']['actual_intervals']]
            ==[(x['start_seconds'],x['end_seconds'],x['requested_kind'],x['actual_kind']) for x in fine['mechanism']['actual_intervals']],
        protection_causes_equal=[x['reasons'] for x in coarse['mechanism']['actual_intervals']]==[x['reasons'] for x in fine['mechanism']['actual_intervals']])
    if q['actions_equal'] and a-b:
        q['qualified']=False;q['reasons'].append('same-actions-missing-coarse-sample-times')
    return q


def report(root):
    protocol=json.loads((root/'protocol.json').read_text(encoding='utf-8'))
    if digest(protocol)!=(root/'protocol.sha256').read_text().strip(): raise ValueError('protocol changed')
    if protocol['compatibility_digest']!=capture_provenance(ROOT)['compatibility_digest']: raise ValueError('source changed after freeze')
    inventories=[]
    for name in ('rolling-inventory.json','fixed-inventory.json'):
        if (root/name).exists(): inventories.extend(json.loads((root/name).read_text()))
    records={};failed=[]
    for item in inventories:
        p=root/item['output']/'result.json'
        if item['exit_code'] or not p.exists(): failed.append(item);continue
        r=json.loads(p.read_text(encoding='utf-8'));validate_result(r)
        x,program=build_inputs_program(r['hardware'],r['scenario'],level=r['level'],mode_factor=r['mode_factor'])
        if r['input_digest']!=experiment_input_digest(x,program) or r['run_key']['compatibility_digest']!=protocol['compatibility_digest']:
            raise ValueError('stale result inputs/source')
        if item.get('reused_pilot'):
            if digest(r)!=item['result_digest']: raise ValueError('pilot bytes changed')
        elif r['run_key']['protocol_digest']!=digest(protocol): raise ValueError('case not bound to frozen protocol')
        if item['case'] in records: raise ValueError('duplicate case')
        records[item['case']]=r
    expected={case_id(*job) for job in matrix()}
    if set(records)-expected: raise ValueError('unexpected case')
    inventory=dict(expected=40,completed=len(records),failed=failed,missing=sorted(expected-set(records)),omitted_configurations=[])
    write_json(root/'completed-failed-missing.json',inventory)
    if len(records)!=40 or failed: raise ValueError('incomplete matrix; retained 05C remains baseline')
    for h,s,l,f,k in matrix():
        if k!='fixed': continue
        r=records[case_id(h,s,l,f,k)];reference=records[case_id(h,s,2,1.)]
        if r['run_key']['reference_digest']!=digest(reference) or r['selected_actions']!=reference['selected_actions']:
            raise ValueError('fixed control differs from finest nominal requested sequence')
    screens=[];rows=[]
    for h,s,l,f,k in matrix():
        r=records[case_id(h,s,l,f,k)];m=r['mechanism'];ledger=m['energy_ledger_wh']
        rows.append(dict(case=case_id(h,s,l,f,k),hardware=h,scenario=s,level=l,mode_factor=f,kind=k,
            exact_score=r['exact_score'],score=r['score'],acquired_products=sum(bool(x['acquired']) for x in r['requests']),
            delivered_products=sum(bool(x['delivered']) for x in r['requests']),on_time_products=sum(x['credited_products'] for x in r['requests']),
            initial_energy_wh=m['initial_energy_wh'],min_energy_wh=m['min_energy_wh'],final_energy_wh=m['final_energy_wh'],
            generation_wh=ledger['generation_wh'],served_load_wh=ledger['served_load_wh'],unmet_load_wh=ledger['unmet_load_wh'],
            curtailed_generation_wh=ledger['curtailed_generation_wh'],received_bits=m['received_bits'],
            queued_bits=r['final_custody']['queued_bits'],partial_bits=r['final_custody']['partial_bits'],
            first_sampled_zero_energy_seconds=m['first_sampled_zero_energy_seconds'],runtime_seconds=r['runtime_seconds']))
        if l==2:
            q=qualify(records[case_id(h,s,1,f,k)],r,derive_hardware(manifest(),h)['working_energy_wh'])
            screens.append(dict(hardware=h,scenario=s,mode_factor=f,kind=k,**q))
    write_json(root/'comparison.json',rows);write_json(root/'numerical-qualification.json',screens)
    with (root/'comparison.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary=dict(qualified=sum(x['qualified'] for x in screens),required_pairs=20,rolling_pairs=16,fixed_pairs=4,
        max_energy_difference_wh=max(x['max_energy_difference_wh'] for x in screens),
        max_temperature_difference_k=max(x['max_temperature_difference_k'] for x in screens),
        requested_action_difference_pairs=sum(not x['actions_equal'] for x in screens),
        actual_action_difference_pairs=sum(not x['actual_kinds_and_intervals_equal'] for x in screens),
        exact_completion_difference_pairs=sum(not x['completion_times_equal'] for x in screens),
        fit_for_bounded_supplement=all(x['qualified'] for x in screens),
        accepted_05c_is_manuscript_baseline=True)
    write_json(root/'qualification-summary.json',summary)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True)
    args=p.parse_args();print(json.dumps(report(external(args.archive))))
