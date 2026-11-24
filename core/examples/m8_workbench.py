"""Launch the bounded Russian local constructor and actual mission workbench."""
from pathlib import Path
from dataclasses import asdict
import argparse
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.project_store import ProjectStore
from ops_sim.v5.project_workbench import Workbench
from ops_sim.v5.design_repair import ConstructorLedger

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-directory',type=Path,required=True,help='New external directory, or existing M8 store to reopen')
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--without-lifecycle',action='store_true',help='Open only the historical bounded short consumer')
    p.add_argument('--design-common',type=Path,help='Strict canonical LifecycleRoot input for V2 designs; never an advanced checkpoint')
    a=p.parse_args()
    # The fixed authored immutable template is paid construction, not mission work.
    startup=ConstructorLedger(maximum_compiles=32);startup.reserve()
    common=None
    if a.design_common is not None:
        from ops_sim.v5.lifecycle_document import loads_root
        if a.design_common.stat().st_size>16*2**20:raise ValueError('bounded common mission input')
        common=loads_root(a.design_common.read_bytes());reference=common.base
    else:reference=make_inputs(wire='weakness')
    exists=(a.project_directory/'store.json').is_file()
    store=ProjectStore(a.project_directory,reference,create=not exists)
    if not exists:
        store.meta['constructor']=asdict(startup);store._write(('store.json',),store.meta,mutable=True)
    lifecycle=None
    if not a.without_lifecycle:
        from ops_sim.v5.lifecycle_application import LifecycleWorkspace
        lifecycle=LifecycleWorkspace(store.path('lifecycle'),project_store=store)
    Workbench(store,lifecycle_workspace=lifecycle,design_common=common).serve(a.port)
if __name__=='__main__':main()
