"""Prepare canonical authored day/year DATA; execution uses year_project CLI."""
from pathlib import Path
from dataclasses import replace
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops_sim.v5.spacecraft_project_document import loads_project
from ops_sim.v5.spacecraft_project import project_source_identity
from ops_sim.v5.year_project import compile_job,DAY,YEAR
from ops_sim.v5.design_repair import ConstructorLedger
from ops_sim.v5.lifetime_policy import LifetimeCampaignPolicyV2,WINDOWS_USER,QUALIFICATION

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True)
    p.add_argument('--duration',type=int,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-upgrade-from');p.add_argument('--segments',type=int,default=512)
    a=p.parse_args(argv)
    if a.output.exists():raise ValueError('new immutable output required')
    project=loads_project(a.project.read_text('utf-8-sig'))
    current=project_source_identity()
    if project.source_identity!=current:
        if a.source_upgrade_from!=project.source_identity:raise ValueError('explicit exact source-upgrade-from required for imported initial DATA')
        project=replace(project,source_identity=current)
    long=a.duration>DAY
    segments=a.segments if long else 8;hard=900 if long else 240;soft=840 if long else 210
    policy=LifetimeCampaignPolicyV2(mode=WINDOWS_USER if long else QUALIFICATION,
        maximum_primary_segments=segments,reserved_diagnostic_slots=2,hard_seconds=hard,soft_seconds=soft,
        finalization_seconds=hard-soft,maximum_journal_records=max(128,4*(segments+2)+32),
        maximum_observed_primary_seconds=segments*(hard+2),maximum_diagnostic_seconds=2*(hard+2))
    ledger=ConstructorLedger();build=(Path(__file__).parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes()
    raw=compile_job(project,a.duration,ledger,policy,build)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('xb')as f:f.write(raw)
    print(json.dumps(dict(prepared=True,dispatch=False,path=str(a.output.absolute()),constructor_work=ledger.__dict__ if hasattr(ledger,'__dict__')else {'compiles':ledger.compiles},year_seconds=YEAR)))
    return 0
if __name__=='__main__':raise SystemExit(main())
