"""Versioned finite lifetime CLI; explicit B63 backend/permission opt-in."""
from pathlib import Path
import argparse,json
from ops_sim.v5 import lifetime_supervisor as supervisor
from ops_sim.v5.lifetime_policy import admit_policy
from ops_sim.v5.lifetime_journal import publish

def main(argv=None):
    a=argparse.ArgumentParser(description=__doc__);sub=a.add_subparsers(dest='command',required=True)
    p=sub.add_parser('derive-input');p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--duration-seconds',type=int,required=True)
    p=sub.add_parser('derive-accounting');p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('prepare');p.add_argument('--input',type=Path,required=True);p.add_argument('--store',type=Path,required=True);p.add_argument('--policy',type=Path,required=True);p.add_argument('--strategy',choices=('B60_SEALED_STATIC_V1','REFERENCE_B59'),default='B60_SEALED_STATIC_V1')
    p.add_argument('--backend',choices=('REFERENCE','PREPARED_PYTHON','PREPARED_NATIVE','B64_TYPED_EXECUTION_V1','B64_TYPED_COUPLED_LEGACY_QUIET_CONTROL_V1','B65_TYPED_EXECUTION_V2'),default='REFERENCE');p.add_argument('--build',type=Path)
    p.add_argument('--execution-mode',choices=('PILOT','LONG'),default='PILOT');p.add_argument('--acceptance',type=Path)
    for name in ('admit','chain-run','status','stop','resume','export-result','diagnostic'):
        p=sub.add_parser(name);p.add_argument('--store',type=Path,required=True)
        if name=='export-result':p.add_argument('--output',type=Path,required=True)
        if name=='diagnostic':
            p.add_argument('--parent-job-id',required=True);p.add_argument('--checkpoint-sha256',required=True);p.add_argument('--verbose',action='store_true')
    p=sub.add_parser('inspect-result');p.add_argument('--input',type=Path,required=True)
    p=sub.add_parser('local-capability');p.add_argument('--build',type=Path)
    p.add_argument('--backend',choices=('REFERENCE','B65_TYPED_EXECUTION_V2'),default='B65_TYPED_EXECUTION_V2')
    v=a.parse_args(argv)
    if v.command=='local-capability':
        from ops_sim.v5.lifetime_local_capability import local_capability
        result=local_capability(None if v.build is None else supervisor._read(v.build,65536),backend=v.backend)
    elif v.command=='derive-input':result=supervisor.derive_input(v.input,v.output,v.duration_seconds)
    elif v.command=='derive-accounting':
        from ops_sim.v5.lifetime_admission import derive_accounting
        _,raw,result=derive_accounting(v.input.read_bytes())
        with v.output.open('xb')as f:f.write(raw)
    elif v.command=='prepare':
        from ops_sim.v5.lifetime_execution_authority import reference
        result=supervisor.prepare(v.input,v.store,admit_policy(json.loads(v.policy.read_text(encoding='utf-8-sig'))),strategy=v.strategy,
            backend=v.backend,build=None if v.build is None else supervisor._read(v.build,65536),execution_mode=v.execution_mode,
            acceptance=None if v.acceptance is None else reference(v.acceptance))
    elif v.command in ('chain-run','resume'):result=supervisor.run(v.store,explicit_continue=v.command=='resume')
    elif v.command=='diagnostic':result=supervisor.diagnostic(v.store,v.parent_job_id,v.checkpoint_sha256,verbose=v.verbose)
    elif v.command=='export-result':result=supervisor.export_result(v.store,v.output)
    elif v.command=='inspect-result':
        from ops_sim.v5.lifetime_result import inspect_result
        result=inspect_result(v.input)
    else:
        store,plan=supervisor._store(v.store)
        try:
            if v.command=='stop':
                marker=store.path('operator-pause.json')
                if not marker.exists():publish(marker,dict(plan_identity=plan['plan_identity']),16384)
                elif supervisor._read(marker).get('plan_identity')!=plan['plan_identity']:raise ValueError('B62 foreign pause')
            result=supervisor._summary(store,plan)
            if v.command=='admit':
                from ops_sim.v5.lifetime_execution_authority import admit_store_execution
                authority=admit_store_execution(store)
                result.update(admitted=True,dispatch=False,execution_authority_mode=authority['mode'])
        finally:store.close_publications()
    print(json.dumps(result,ensure_ascii=False,allow_nan=False));return result

if __name__=='__main__':main()
