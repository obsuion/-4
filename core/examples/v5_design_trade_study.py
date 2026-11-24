"""Task05E pilots, protocol freeze and bounded source-bound comparison.

Run with python -B -m examples.v5_design_trade_study --help. Every output must
be outside the repository; successful matching runs are reused, never replaced.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time
import traceback

from ops_sim.v5.design_trade_campaign import TradeSpec, input_digest
from ops_sim.v5.design_trade_continuation import run_trade, summarize_trade
from ops_sim.v5.design_trade_design import enumerate_designs, select_designs, design_record

ROOT=Path(__file__).resolve().parents[1]
PILOTS=(('B8-A2','close','FULL',2),('B2-A4','relaxed','FULL',2))
SENSITIVITIES=(('core_low','core_inertia_scale',.75),('core_high','core_inertia_scale',1.25),
    ('torque_low','torque_nm',.015),('torque_high','torque_nm',.025),
    ('harness_low','harness_resistivity_factor',.5),('harness_high','harness_resistivity_factor',2.),
    ('mode_low','mode_factor',.5),('mode_high','mode_factor',1.5))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2)+'\n'


def digest(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def source_snapshot():
    paths=sorted((ROOT/'ops_sim').rglob('*.py'))+[Path(__file__).resolve()]
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return {'files':hashes,'sha256':digest(hashes),
        'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}


def output_directory(value):
    directory=Path(value).resolve()
    if directory==ROOT or ROOT in directory.parents:
        raise ValueError('study evidence must remain outside the repository')
    directory.mkdir(parents=True,exist_ok=True)
    return directory


def case_id(spec,label='nominal'):
    return f'{label}__{spec.design_id}__{spec.workload}__{spec.variant}__L{spec.level}'


def row(spec,label='nominal'):
    return {'case_id':case_id(spec,label),'group':label,'spec':spec.to_dict(),'input_digest':input_digest(spec)}


def cases(selected):
    result=[row(TradeSpec(d,w,v,n)) for d in selected for w in ('relaxed','close')
        for v in ('FULL','RESOURCE_ONLY') for n in (1,2)]
    for label,key,value in SENSITIVITIES:
        for d in ('B8-A2','B2-A4'):
            for variant in ('FULL','RESOURCE_ONLY'):
                spec=TradeSpec(d,'close',variant,2)
                spec=(replace(spec,assumptions=replace(spec.assumptions,**{key:value}))
                    if key in ('core_inertia_scale','harness_resistivity_factor') else replace(spec,**{key:value}))
                result.append(row(spec,label))
    return result


def read_matching(directory,case,source):
    path=directory/'runs'/(case['case_id']+'.json')
    if not path.exists(): return None
    existing=json.loads(path.read_text(encoding='utf-8'))
    hashed={k:v for k,v in existing.items() if k!='result_sha256'}
    if (existing.get('status')!='success' or existing.get('source')!=source
            or existing.get('case')!=json.loads(encode(case))
            or existing.get('result_sha256')!=digest(hashed)
            or existing.get('python')!=platform.python_version() or existing.get('platform')!=platform.platform()
            or existing['summary']['input_digest']!=case['input_digest']
            or existing['summary']['status']!='completed-horizon'
            or existing['summary']['checkpoint']['simulation_time_seconds']!=case['spec']['horizon']):
        raise ValueError('existing output differs from frozen source/input: '+str(path))
    return existing


def execute_case(directory_string,case,source):
    directory=Path(directory_string);(directory/'runs').mkdir(exist_ok=True)
    existing=read_matching(directory,case,source)
    if existing is not None:
        return {'case_id':case['case_id'],'status':'success','reused':True,'elapsed_seconds':existing['elapsed_seconds']}
    if source_snapshot()!=source:
        raise ValueError('production source changed before case execution')
    started=stamp();timer=time.perf_counter()
    try:
        spec=TradeSpec.from_dict(case['spec'])
        if input_digest(spec)!=case['input_digest']: raise ValueError('frozen input mismatch')
        state=run_trade(spec)
        summary=summarize_trade(state)
        if summary['status']!='completed-horizon': raise ValueError('incomplete physical campaign')
        if source_snapshot()!=source: raise ValueError('production source changed during execution')
        result={'status':'success','case':case,'source':source,'started_utc':started,
            'finished_utc':stamp(),'elapsed_seconds':time.perf_counter()-timer,
            'python':platform.python_version(),'platform':platform.platform(),
            'design':design_record(state.design),'summary':summary}
        result['result_sha256']=digest(result)
        path=directory/'runs'/(case['case_id']+'.json')
        with path.open('x',encoding='utf-8',newline='\n') as stream: stream.write(encode(result))
        return {'case_id':case['case_id'],'status':'success','reused':False,'elapsed_seconds':result['elapsed_seconds']}
    except Exception:
        result={'status':'failed','case':case,'source':source,'started_utc':started,
            'elapsed_seconds':time.perf_counter()-timer,'traceback':traceback.format_exc()}
        path=directory/(case['case_id']+'.failed.'+str(time.time_ns())+'.json')
        path.write_text(encode(result),encoding='utf-8')
        return {'case_id':case['case_id'],'status':'failed','failure_log':str(path),
            'elapsed_seconds':result['elapsed_seconds']}


def pilot(directory):
    source=source_snapshot()
    manifest={'declared_utc':stamp(),'source':source,'pilots':[row(TradeSpec(*p)) for p in PILOTS],
        'nominal_rule':'min/max packs per feasible array count; two workloads/two variants/two levels',
        'planned_cases':cases([d.design_id for d in select_designs(enumerate_designs())]),
        'timing_projection':'1.5 * max(two pilot elapsed seconds) * (64 - 2 matching pilots) / 2 workers',
        'fallback_threshold_seconds':3600,'fallback_designs':['B2-A2','B8-A2','B2-A4'],
        'fallback_policy':'before main scores only; same32 sensitivities; if projection still over3600, stop incomplete',
        'qualification':{'exact':['request_credit','phase_durations','common-time grid inclusion'],
            'energy_abs_bound_fraction_of_capacity':.001,'temperature_abs_bound_k':.1},
        'selection':'retain all maximum priority-credit ties; FULL selection-loss range over all ablation maximizers',
        'prohibition':'no outcome-based parameter tuning or case omission'}
    declaration=directory/'pilot-declaration.json'
    if declaration.exists():
        old=json.loads(declaration.read_text(encoding='utf-8'))
        if old['source']!=source: raise ValueError('pilot source drift; use a new external evidence directory')
    else: declaration.write_text(encode(manifest),encoding='utf-8')
    inventory=[execute_case(str(directory),r,source) for r in manifest['pilots']]
    (directory/'pilot-runtime.json').write_text(encode(inventory),encoding='utf-8')
    print(encode(inventory)) # Runtime and completion only; no scores before freeze.
    return 0 if all(r['status']=='success' for r in inventory) else 1


def freeze(directory):
    source=source_snapshot();declaration=json.loads((directory/'pilot-declaration.json').read_text(encoding='utf-8'))
    if declaration['source']!=source: raise ValueError('pilot source is not current candidate')
    pilots=[read_matching(directory,r,source) for r in declaration['pilots']]
    if any(p is None for p in pilots): raise ValueError('both timing pilots must complete')
    slowest=max(p['elapsed_seconds'] for p in pilots)
    selected=[d.design_id for d in select_designs(enumerate_designs())]
    projected=1.5*slowest*(64-2)/2
    fallback=projected>3600
    if fallback: selected=declaration['fallback_designs']
    planned=cases(selected);projected_selected=1.5*slowest*(len(planned)-2)/2
    if projected_selected>3600: raise ValueError('measured runtime exceeds predeclared fallback; report INCOMPLETE')
    protocol=dict(declaration,frozen_utc=stamp(),cases=planned,selected_designs=selected,
        designs=[design_record(d) for d in enumerate_designs()],fallback_used=fallback,
        projected_full_seconds=projected,projected_selected_seconds=projected_selected,
        workers=2,slowest_pilot_seconds=slowest,
        reused_pilot_result_sha256={p['case']['case_id']:p['result_sha256'] for p in pilots},
        omitted_nominal_designs=[d.design_id for d in
            select_designs(enumerate_designs()) if d.design_id not in selected])
    del protocol['planned_cases']
    path=directory/'protocol.json'
    with path.open('x',encoding='utf-8',newline='\n') as stream: stream.write(encode(protocol))
    (directory/'protocol.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest()+'\n',encoding='ascii')
    print(encode({'selected':selected,'cases':len(planned),'projection_seconds':projected_selected,
        'protocol_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))
    return 0


def run(directory):
    path=directory/'protocol.json'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=(directory/'protocol.sha256').read_text().strip():
        raise ValueError('frozen protocol changed')
    protocol=json.loads(path.read_text(encoding='utf-8'))
    if source_snapshot()!=protocol['source']: raise ValueError('frozen production changed')
    inventory=[]
    with ProcessPoolExecutor(max_workers=protocol['workers']) as pool:
        tasks=[pool.submit(execute_case,str(directory),case,protocol['source']) for case in protocol['cases']]
        for task in as_completed(tasks):
            record=task.result();inventory.append(record)
            (directory/'run-inventory.json').write_text(encode(sorted(inventory,key=lambda r:r['case_id'])),encoding='utf-8')
            print(encode(record).strip(),flush=True)
    inventory.sort(key=lambda r:r['case_id'])
    (directory/'run-inventory.json').write_text(encode(inventory),encoding='utf-8')
    return 0 if all(r['status']=='success' for r in inventory) else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('pilot','freeze','run'))
    parser.add_argument('--output',required=True)
    args=parser.parse_args();directory=output_directory(args.output)
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    return {'pilot':pilot,'freeze':freeze,'run':run}[args.command](directory)


if __name__=='__main__':
    raise SystemExit(main())
