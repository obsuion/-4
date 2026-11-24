"""Explicit offline prepare/admit/run/status/stop/resume/export/inspect.

Run stays in the foreground and owns its child. Another invocation may publish
a cooperative stop marker, but cannot control/reacquire old PIDs. All execution
uses fixed source-owned entrypoints and current runtime/source admission.
"""
from pathlib import Path
import argparse,json,sys,time
from .portable_job import prepare,admit_job,create_store,export_result,inspect_result,parse,admit_contract,worker_contract

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('--input',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--key',required=True);a.add_argument('--seconds',type=int,default=240);a.add_argument('--strategy',choices=('REFERENCE_B59','B60_SEALED_STATIC_V1'),default='B60_SEALED_STATIC_V1')
    a=sub.add_parser('admit');a.add_argument('package',type=Path)
    a=sub.add_parser('run');a.add_argument('package',type=Path);a.add_argument('--store',type=Path,required=True)
    for name in ('status','stop','resume','export-result'):
        a=sub.add_parser(name);a.add_argument('--store',type=Path,required=True)
        if name in ('stop','resume'):a.add_argument('--job',required=True)
        if name=='resume':a.add_argument('--key',required=True);a.add_argument('--seconds',type=int,default=240)
        if name=='export-result':a.add_argument('--output',type=Path,required=True)
    a=sub.add_parser('inspect-result');a.add_argument('package',type=Path)
    args=p.parse_args(argv);source=Path(__file__).resolve().parents[2]
    if args.command=='prepare':
        from .lifecycle_document import loads_root
        result=prepare(args.output,loads_root(args.input.read_bytes()),source,strategy=args.strategy,key=args.key,execution_seconds=args.seconds)
    elif args.command=='admit':
        j,root,raw=admit_job(args.package,source);result=dict(admitted=True,root_identity=root.identity,strategy=j['contract']['strategy'],dispatch=False)
    elif args.command=='inspect-result':result=inspect_result(args.package)
    else:
        from .lifecycle_application import LifecycleStore,LifecycleRunner,make_intent,_write_stop_request
        if args.command=='run':store,intent=create_store(args.package,args.store,source)
        else:
            store=LifecycleStore(args.store)
            worker_contract(store.directory,source)
        if args.command in ('run','resume'):
            if args.command=='resume':
                from .lifecycle_execution_budget import ExecutionBudget
                parent=store.job(args.job)
                if parent['ownership_valid']is not True or parent['result']is None:raise ValueError('B60_SETTLED_NATIVE_REQUIRED')
                cp=parent['result']['checkpoint']
                intent=make_intent(store.root_input.identity,key=args.key,parent_job_id=args.job,snapshot_sha256=cp['sha256'],execution_seconds=args.seconds,maximum_output_bytes=128*2**20,execution_budget=ExecutionBudget(args.seconds,args.seconds-30,30),publication_profile=store.publication_profile)
            runner=LifecycleRunner(store)
            try:
                job=runner.submit(intent)
                while runner.thread is not None and runner.thread.is_alive():runner.thread.join(.25)
                result=store.job(job['job_id'])
            finally:runner.close()
        elif args.command=='stop':
            job=store.job(args.job)
            if job['status']not in ('RUNNING','ADMITTED','STOP_REQUESTED'):raise ValueError('B60_NO_ACTIVE_COOPERATIVE_WORKER')
            marker=store.path('jobs',args.job,'stop-request.json')
            if not marker.exists():_write_stop_request(marker,job)
            result=dict(requested=True,PID_control=False,job=args.job)
        elif args.command=='status':result=store.snapshot()
        else:result=export_result(store,args.output)
        store.close_publications()
    print(json.dumps(result,ensure_ascii=False,allow_nan=False));return result

if __name__=='__main__':main()
