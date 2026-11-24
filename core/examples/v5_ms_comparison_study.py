"""Pilot, freeze, execute and inventory Task05C; all evidence stays external.

The study never branches policy on hardware identity. Parallelism is only across
independent experiments, not inside a physical execution or its causal replay.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from examples.v5_ms_comparison import external, write_json, ROOT
from ops_sim.v5.comparison_campaign import build_inputs_program, COMMON_ASSUMPTIONS, CONTACTS_S1, CONTACTS_S2
from ops_sim.v5.comparison_manifest import manifest, derive_hardware, hardware_ledger, digest
from ops_sim.v5.comparison_evidence import qualify_pair
from ops_sim.v5.experiment_bundle import experiment_input_digest
from ops_sim.v5.experiment_provenance import capture_provenance


LEVELS=(0,1,2)
WORKERS=4
RUNTIME_BUDGET_SECONDS=10800  # Declared study execution budget, NOT the organizers' unspecified cutoff.


def case_id(hardware,scenario,level,factor,kind="rolling"):
    return f"{hardware}-{scenario}-L{level}-P{factor:g}-{kind}"


def run_case(root,hardware,scenario,level,factor,*,pilot=False,fixed_reference=None,partial=False):
    name=case_id(hardware,scenario,level,factor,"fixed" if fixed_reference else "rolling")
    output=root/("adjusted-pilots" if pilot else "cases")/name
    output.mkdir(parents=True,exist_ok=True)
    cmd=[sys.executable,"-B","-m","examples.v5_ms_comparison","--hardware",hardware,"--scenario",scenario,
         "--level",str(level),"--mode-factor",str(factor),"--output",str(output)]
    if not pilot: cmd.extend(("--protocol",str(root/"protocol.json")))
    if fixed_reference: cmd.extend(("--fixed-reference",str(fixed_reference)))
    if partial: cmd.append("--partial-boundary")
    log=output/("process.log" if not (output/"process.log").exists() else "reuse-process.log")
    if log.exists(): raise ValueError("do not overwrite existing rerun evidence")
    start=perf_counter()
    with log.open("w",encoding="utf-8") as stream:
        result=subprocess.run(cmd,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=False)
    item=dict(case=name,output=str(output.relative_to(root)),command=cmd,exit_code=result.returncode,
              subprocess_wall_seconds=perf_counter()-start)
    write_json(output/("process-status.json" if not (output/"process-status.json").exists() else "reuse-status.json"),item)
    print(json.dumps(item),flush=True)
    return item


def pilots(root):
    jobs=[(h,"S1",l,1.) for h in ("H-E4","J-E1") for l in LEVELS]
    # Two pilot processes avoid overloading measurements with main-study work.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda job:run_case(root,*job,pilot=True),jobs))
    write_json(root/"pilot-inventory.json",results)
    if any(r["exit_code"] for r in results): raise ValueError("pilot execution did not complete")


def freeze(root):
    if (root/"protocol.json").exists(): raise ValueError("protocol already frozen; do not overwrite")
    provenance=capture_provenance(ROOT)
    inventory=json.loads((root/"pilot-inventory.json").read_text(encoding="utf-8"))
    results={}
    for item in inventory:
        r=json.loads((root/item["output"]/"result.json").read_text(encoding="utf-8"))
        x,p=build_inputs_program(r["hardware"],r["scenario"],level=r["level"])
        if (item["exit_code"] or r["status"]!="completed-horizon" or r["run_key"]["compatibility_digest"]!=provenance["compatibility_digest"]
            or r["input_digest"]!=experiment_input_digest(x,p)):
            raise ValueError("pilot not complete and bound to current candidate")
        results[(r["hardware"],r["level"])]=r
    screens={h:qualify_pair(results[h,1],results[h,2],derive_hardware(manifest(),h)["working_energy_wh"]) for h in ("H-E4","J-E1")}
    if not all(q["qualified"] for q in screens.values()):
        write_json(root/"pilot-unqualified.json",screens)
        raise ValueError("planned levels failed pilot screen; no main-study freeze")
    # Conservative extrapolation uses the slowest measured L2 pilot for ALL
    # rolling levels; 144 rolling + 72 faster fixed cases for the full matrix.
    worst=max(r["runtime_seconds"] for r in results.values())
    estimate=216*worst/WORKERS
    hardware=[f"{f}-E{i}" for f in "DHJ" for i in (range(1,5) if estimate<=RUNTIME_BUDGET_SECONDS else (1,4))]
    m=manifest()
    protocol=dict(version=1,compatibility_digest=provenance["compatibility_digest"],manifest_digest=digest(m),
        hardware=hardware,all_hardware=[f"{f}-E{i}" for f in "DHJ" for i in range(1,5)],scenarios=["S1","S2"],
        levels=list(LEVELS),mode_factors=[1.,.5],workers=WORKERS,runtime_budget_seconds=RUNTIME_BUDGET_SECONDS,
        estimated_full_matrix_wall_seconds=estimate,slowest_measured_pilot_seconds=worst,
        fallback_used=len(hardware)==6,fallback_rule="D/H/J x E1/E4 if conservative pilot extrapolation exceeds 10800 s execution budget; before main rankings",
        engineering_screen=dict(per_request_credit="exact identical",energy_fraction_of_working_capacity=.001,temperature_k=.1,
            time_alignment="common actual physical boundaries, no index matching/interpolation",comparison="levels 1 and 2; level 0 retained as third successive level"),
        fixed_sequence="For every nominal hardware/scenario, hold finest rolling requested actions/record IDs/physical intervals fixed at levels 0,1,2; protection enabled",
        sensitivity="Both exclusive mode proxies * .5, all hardware/scenarios/all three levels; no truth bracket claim",
        contrasts=["D-E1-S1","H-E1-S1","H-E4-S1","J-E1-S1","J-E4-S1"],
        restart="D-E1 S1 level2 nominal: first actual partial transfer, save full accepted bundle and restore in a fresh process",
        pilot_adjustment="One common adjustment: acquisition windows 120 -> 300 s to cover the unchanged 300 s unknown-release poll; physical duration 60 s unchanged; original pilots retained",
        assumptions=list(COMMON_ASSUMPTIONS),contacts=dict(S1=CONTACTS_S1,S2=CONTACTS_S2),
        budgets="Six 10x30 km products; raw per-family integer bits; 50 versus 30 s aggregate contact time; 12 Wh baseline over one hour; at most 6*60 s imaging; final 900 s drain",
        source_notes="Primary sources inspected 23 September 2026; snapshot retrieval statuses preserved separately",
        pilot_screen=screens,pilot_inventory=inventory,
        result_scope="Counterfactual prescribed workload, accepted v7 policy; not flight/cross-simulator/radiometric/optimality/full-V5 validation")
    write_json(root/"manifest.json",m)
    write_json(root/"hardware.json",{h:dict(vector=derive_hardware(m,h),ledger=hardware_ledger(m,h)) for h in protocol["all_hardware"]})
    write_json(root/"protocol.json",protocol)
    (root/"protocol.sha256").write_text(digest(protocol)+"\n",encoding="ascii")
    print(json.dumps(dict(protocol_digest=digest(protocol),hardware=hardware,estimated_wall_seconds=estimate)),flush=True)


def execute(root):
    protocol=json.loads((root/"protocol.json").read_text(encoding="utf-8"))
    if digest(protocol)!=(root/"protocol.sha256").read_text().strip(): raise ValueError("protocol digest changed")
    if protocol["compatibility_digest"]!=capture_provenance(ROOT)["compatibility_digest"]: raise ValueError("source changed after freeze")
    items=[]
    jobs=[]
    # Reuse the six final matching pilot runs with explicit evidence and hashes.
    pilot_rows={item["case"]:item for item in protocol["pilot_inventory"]}
    for h in protocol["hardware"]:
        for s in protocol["scenarios"]:
            for factor in protocol["mode_factors"]:
                for level in protocol["levels"]:
                    name=case_id(h,s,level,factor)
                    if name in pilot_rows:
                        item=dict(pilot_rows[name],reused_pilot=True,protocol_digest=digest(protocol))
                        item["result_digest"]=digest(json.loads((root/item["output"]/"result.json").read_text(encoding="utf-8")))
                        items.append(item)
                    else: jobs.append((h,s,level,factor))
    with ThreadPoolExecutor(max_workers=protocol["workers"]) as pool:
        futures=[pool.submit(run_case,root,*job,partial=job==("D-E1","S1",2,1.)) for job in jobs]
        for future in as_completed(futures):
            items.append(future.result())
            write_json(root/"rolling-inventory.json",sorted(items,key=lambda r:r["case"]))
    if any(i["exit_code"] for i in items): raise ValueError("rolling cases failed; preserve inventory, do not score as zero")
    fixed_jobs=[]
    for h in protocol["hardware"]:
        for s in protocol["scenarios"]:
            ref=next(root/i["output"]/"result.json" for i in items if i["case"]==case_id(h,s,2,1.))
            fixed_jobs.extend((h,s,l,1.,ref) for l in protocol["levels"])
    fixed_items=[]
    with ThreadPoolExecutor(max_workers=protocol["workers"]) as pool:
        futures=[pool.submit(run_case,root,h,s,l,f,fixed_reference=ref) for h,s,l,f,ref in fixed_jobs]
        for future in as_completed(futures):
            fixed_items.append(future.result())
            write_json(root/"fixed-inventory.json",sorted(fixed_items,key=lambda r:r["case"]))
    if any(i["exit_code"] for i in fixed_items): raise ValueError("fixed cases failed")


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("pilots","freeze","execute"))
    parser.add_argument("--archive",type=Path,required=True)
    args=parser.parse_args(argv)
    root=external(args.archive); root.mkdir(parents=True,exist_ok=True)
    {"pilots":pilots,"freeze":freeze,"execute":execute}[args.phase](root)


if __name__=="__main__": main()
