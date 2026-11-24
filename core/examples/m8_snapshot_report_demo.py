"""B51 real production-runner demo; short nominal domain, never a month campaign.

Use a new external directory. Execution is explicit; reopening only displays
stored metadata and does not dispatch a diagnostic automatically.
"""
from pathlib import Path
from dataclasses import asdict
import argparse,json,uuid
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.project_store import ProjectStore
from ops_sim.v5.project_runner import ProjectRunner
from ops_sim.v5.spacecraft_project import SpacecraftProject,project_source_identity
from ops_sim.v5.project_intents import make_intent,DIRECT
from ops_sim.v5.design_repair import ConstructorLedger

def create_store(directory):
    startup=ConstructorLedger();startup.reserve()
    store=ProjectStore(directory,make_inputs(wire='weakness'),create=True)
    store.meta['constructor']=asdict(startup);store._write(('store.json',),store.meta,mutable=True)
    project=store.create(SpacecraftProject(store.reference,project_source_identity(),title='B51 direct snapshot demo'))
    store.preview(project['project_id'],project['revision'])
    return store,project

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--run-primary',action='store_true');p.add_argument('--direct-job');a=p.parse_args()
    if (a.directory/'store.json').exists():
        store=ProjectStore(a.directory,make_inputs(wire='weakness'));pid=store.meta['projects'][-1]
        project=dict(project_id=pid,revision=store.load(pid).identity)
    else:store,project=create_store(a.directory)
    runner=ProjectRunner(store)
    try:
        if a.run_primary:
            runner.submit(project['project_id'],project['revision'],uuid.uuid4().hex)
        elif a.direct_job:
            old=store.job(a.direct_job);cp=next(s for s in old['snapshots'] if s['clock']==200)
            intent=make_intent(project['project_id'],project['revision'],uuid.uuid4().hex,parent=old['job_id'],snapshot_sha=cp['sha256'],
                method=DIRECT,mode='DIAGNOSTIC_VERBOSE',window_end=728)
            runner.submit(project['project_id'],project['revision'],intent['idempotency_key'],resume_job=old['job_id'],intent=intent)
        if runner.thread is not None:runner.thread.join(422)
        print(json.dumps(store.snapshot(),ensure_ascii=False,indent=2))
    finally:runner.close()
if __name__=='__main__':main()
