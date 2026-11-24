"""Predeclare, admit, pilot, freeze and run the bounded 40-case Task05D study."""

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from examples.v5_ms_comparison import ROOT,external,write_json
from examples.v5_eps_stress import HARDWARE,SCENARIOS,POLICY,ASSUMPTIONS,build_inputs_program,independent_budgets
from examples.v5_eps_stress_report import case_id,matrix,validate_result
from ops_sim.v5.campaign_continuation import start_campaign,planning_boundary
from ops_sim.v5.comparison_manifest import manifest,derive_hardware,digest
from ops_sim.v5.experiment_bundle import experiment_input_digest
from ops_sim.v5.experiment_provenance import capture_provenance
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.solar import compute_solar_generation


PILOTS=(('J-E4','A',2,.5,'rolling'),('J-E1','B',2,1.,'rolling'))
WORKERS=2
UNCERTAINTY_MULTIPLIER=2.
TEST_ALLOWANCE_SECONDS=600


def now(): return datetime.now(timezone.utc)
def stamp(text): return datetime.fromisoformat(text.replace('Z','+00:00'))


def predeclare(root,budget_anchor):
    if (root/'predeclared.json').exists(): raise ValueError('predeclaration already exists')
    start=stamp(budget_anchor)
    from datetime import timedelta
    end=start+timedelta(hours=4);execution_end=end-timedelta(minutes=45)
    data=dict(task='Task05D',version=1,budget_anchor_utc=start.isoformat(),hard_stop_utc=end.isoformat(),
        execution_stop_utc=execution_end.isoformat(),declared_at_utc=now().isoformat(),workers=WORKERS,
        matrix=[dict(case=case_id(*j),hardware=j[0],scenario=j[1],level=j[2],mode_factor=j[3],kind=j[4]) for j in matrix()],
        pilots=[case_id(*j) for j in PILOTS],scenarios=SCENARIOS,policy=canonical_content(POLICY),assumptions=ASSUMPTIONS,
        exact_independent_budgets=independent_budgets(),uncertainty_multiplier=UNCERTAINTY_MULTIPLIER,
        remaining_validation_test_allowance_seconds=TEST_ALLOWANCE_SECONDS,
        runtime_rule='slower pilot wall * 40 cases / 2 workers * 2 uncertainty + 600 s tests; must fit before final 45 minute reserve',
        fixed_controls='finest nominal rolling requested sequence for E1/E4 in each scenario, at levels 1 and 2; protection enabled',
        stop_rule='any admission/pilot error or incomplete/nonfinite output stops extension; retain evidence and use accepted 05C',
        numerical_screen=dict(per_request_credit='identical',energy_fraction_of_working_capacity=.001,temperature_k=.1,
            alignment='exact rational physical sample times; no interpolation/index matching; action/completion differences separate'),
        source_provenance=capture_provenance(ROOT),accepted_05c_reference_manifest_unchanged=manifest(),
        active_initial_conditions={s:dict(fraction=v['initial_fraction'],retention=1,temperatures_k=293.15,
            initial_wh={h:derive_hardware(manifest(),h)['working_energy_wh']*v['initial_fraction'] for h in HARDWARE})
            for s,v in SCENARIOS.items()})
    write_json(root/'predeclared.json',data)
    (root/'predeclared.sha256').write_text(digest(data)+'\n',encoding='ascii')
    print('PREDECLARED',digest(data),flush=True)


def declaration(root):
    d=json.loads((root/'predeclared.json').read_text(encoding='utf-8'))
    if digest(d)!=(root/'predeclared.sha256').read_text().strip(): raise ValueError('predeclaration changed')
    if capture_provenance(ROOT)['compatibility_digest']!=d['source_provenance']['compatibility_digest']:
        raise ValueError('source changed since predeclaration')
    return d


def admission(root):
    declaration(root)
    rows=[]
    for h,s,l,f,k in matrix():
        if k!='rolling': continue
        inputs,p=build_inputs_program(h,s,level=l,mode_factor=f)
        state=start_campaign(inputs,p)  # Accepted constructor, origin and acquisition admission.
        view,_=planning_boundary(inputs,p,state.memory)
        solar=compute_solar_generation(inputs.spacecraft_configuration.eps.solar_array,
            sunlit=p.forcing[0].standby.sunlit,incidence_angle_deg=p.forcing[0].standby.incidence_angle_deg)
        if len(view.requests)!=6 or len(view.opportunities)!=6: raise ValueError('future requests were not legitimately published')
        rows.append(dict(case=case_id(h,s,l,f,k),input_digest=experiment_input_digest(inputs,p),
            requests_visible_at_origin=len(view.requests),horizon=inputs.common_world.horizon_seconds,
            initial_energy_wh=state.context.spacecraft_state.battery.energy_wh,
            cosine_binary64=solar.incidence_factor,cosine_hex=solar.incidence_factor.hex(),generation_w=solar.generation_w,
            contact_work_bound=(len(p.requests)+1)*p.integration.substeps,
            execution_work_bound=p.policy.max_decisions*(2*len(p.requests)+1)*p.integration.substeps,
            replay_forecast_work_bound=p.policy.max_decisions*p.policy.max_forecast_eps))
    write_json(root/'admission.json',dict(status='passed',cases=rows))
    print('ADMITTED',len(rows),flush=True)


def run_case(root,job,*,pilot=False,reference=None):
    d=json.loads((root/'predeclared.json').read_text(encoding='utf-8'))
    name=case_id(*job);output=root/('pilots' if pilot else 'cases')/name
    output.mkdir(parents=True,exist_ok=False)
    h,s,l,f,k=job
    command=[sys.executable,'-B','-m','examples.v5_eps_stress','--hardware',h,'--scenario',s,'--level',str(l),
        '--mode-factor',str(f),'--output',str(output)]
    if not pilot: command.extend(('--protocol',str(root/'protocol.json')))
    if reference is not None: command.extend(('--fixed-reference',str(reference)))
    start=perf_counter();remaining=(stamp(d['execution_stop_utc'])-now()).total_seconds()
    timed_out=False
    if remaining<=0: code=124
    else:
        with (output/'process.log').open('w',encoding='utf-8') as stream:
            try: code=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=remaining).returncode
            except subprocess.TimeoutExpired: code=124;timed_out=True
    item=dict(case=name,output=output.relative_to(root).as_posix(),command=command,exit_code=code,
        timed_out=timed_out,subprocess_wall_seconds=perf_counter()-start)
    write_json(output/'process-status.json',item)
    print(json.dumps(item),flush=True)
    return item


def pilots(root):
    declaration(root)
    if json.loads((root/'admission.json').read_text())['status']!='passed': raise ValueError('admission required')
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results=list(pool.map(lambda job:run_case(root,job,pilot=True),PILOTS))
    write_json(root/'pilot-inventory.json',results)
    if any(r['exit_code'] for r in results):
        write_json(root/'extension-stopped.json',dict(reason='pilot error/incomplete; no redesign authorized',inventory=results))
        raise ValueError('pilot failure: stop supplemental extension')
    for item in results:
        validate_result(json.loads((root/item['output']/'result.json').read_text(encoding='utf-8')))


def freeze(root):
    d=declaration(root)
    if (root/'protocol.json').exists(): raise ValueError('protocol already frozen')
    items=json.loads((root/'pilot-inventory.json').read_text())
    if {r['case'] for r in items}!={case_id(*j) for j in PILOTS}: raise ValueError('wrong pilots')
    provenance=capture_provenance(ROOT)
    for item in items:
        if item['exit_code']: raise ValueError('failed pilot')
        r=json.loads((root/item['output']/'result.json').read_text(encoding='utf-8'));validate_result(r)
        x,p=build_inputs_program(r['hardware'],r['scenario'],level=r['level'],mode_factor=r['mode_factor'])
        if r['run_key']['compatibility_digest']!=provenance['compatibility_digest'] or r['input_digest']!=experiment_input_digest(x,p):
            raise ValueError('pilot source/input mismatch')
        item['result_digest']=digest(r)
    slower=max(i['subprocess_wall_seconds'] for i in items)
    estimate=slower*40/WORKERS*UNCERTAINTY_MULTIPLIER+TEST_ALLOWANCE_SECONDS
    available=(stamp(d['execution_stop_utc'])-now()).total_seconds()
    budget=dict(slower_pilot_seconds=slower,workers=WORKERS,planned_cases=40,uncertainty_multiplier=UNCERTAINTY_MULTIPLIER,
        projected_seconds_including_tests=estimate,available_before_reserve_seconds=available,admitted=estimate<=available)
    write_json(root/'runtime-budget.json',budget)
    if not budget['admitted']:
        write_json(root/'extension-stopped.json',dict(reason='measured conservative projection exceeds execution budget',budget=budget))
        raise ValueError('budget stop: accepted 05C remains manuscript baseline')
    protocol=dict(declaration_digest=digest(d),compatibility_digest=provenance['compatibility_digest'],
        source_environment=provenance,frozen_at_utc=now().isoformat(),matrix=d['matrix'],pilot_inventory=items,budget=budget,
        physical_intervals='unchanged across levels',policy=d['policy'],scenarios=d['scenarios'],assumptions=d['assumptions'])
    write_json(root/'protocol.json',protocol);(root/'protocol.sha256').write_text(digest(protocol)+'\n',encoding='ascii')
    print('FROZEN',digest(protocol),json.dumps(budget),flush=True)


def execute(root):
    declaration(root)
    protocol=json.loads((root/'protocol.json').read_text())
    if digest(protocol)!=(root/'protocol.sha256').read_text().strip(): raise ValueError('protocol changed')
    items=[dict(i,reused_pilot=True) for i in protocol['pilot_inventory']]
    completed={i['case'] for i in items}
    jobs=[j for j in matrix() if j[4]=='rolling' and case_id(*j) not in completed]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures=[pool.submit(run_case,root,j) for j in jobs]
        for future in as_completed(futures):
            items.append(future.result());write_json(root/'rolling-inventory.json',sorted(items,key=lambda i:i['case']))
    if any(i['exit_code'] for i in items): raise ValueError('rolling matrix incomplete; preserve evidence')
    fixed=[]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures=[]
        for job in matrix():
            if job[4]!='fixed': continue
            ref=next(root/i['output']/'result.json' for i in items if i['case']==case_id(job[0],job[1],2,1.))
            futures.append(pool.submit(run_case,root,job,reference=ref))
        for future in as_completed(futures):
            fixed.append(future.result());write_json(root/'fixed-inventory.json',sorted(fixed,key=lambda i:i['case']))
    if any(i['exit_code'] for i in fixed): raise ValueError('fixed controls incomplete; preserve evidence')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('predeclare','admission','pilots','freeze','execute'))
    p.add_argument('--archive',required=True,type=Path);p.add_argument('--budget-anchor')
    a=p.parse_args();root=external(a.archive);root.mkdir(parents=True,exist_ok=True)
    if a.phase=='predeclare':
        if a.budget_anchor is None: p.error('explicit task-start budget anchor required')
        predeclare(root,a.budget_anchor)
    else: globals()[a.phase](root)


if __name__=='__main__': main()
