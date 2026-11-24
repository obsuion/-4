"""Tables and publication figures from completed, source-bound Task05C runs."""

import argparse
import csv
import json
import os
from pathlib import Path

from examples.v5_ms_comparison import external, write_json
from examples.v5_ms_comparison_study import case_id
from ops_sim.v5.comparison_manifest import manifest, derive_hardware, digest
from ops_sim.v5.comparison_evidence import qualify_pair


def report(root):
    protocol=json.loads((root/"protocol.json").read_text(encoding="utf-8"))
    if digest(protocol)!=(root/"protocol.sha256").read_text().strip(): raise ValueError("protocol was changed")
    inventory=[]
    for name in ("rolling-inventory.json","fixed-inventory.json"):
        inventory.extend(json.loads((root/name).read_text(encoding="utf-8")))
    records={}
    failures=[]
    for item in inventory:
        path=root/item["output"]/"result.json"
        if item["exit_code"] or not path.exists():
            failures.append(item); continue
        r=json.loads(path.read_text(encoding="utf-8"))
        if r["status"]!="completed-horizon" or r["run_key"]["compatibility_digest"]!=protocol["compatibility_digest"]:
            raise ValueError("incomplete or stale result cannot support comparison")
        if item.get("reused_pilot"):
            if digest(r)!=item["result_digest"]: raise ValueError("reused pilot result changed")
        elif r["run_key"]["protocol_digest"]!=digest(protocol): raise ValueError("case not bound to protocol")
        if item["case"] in records: raise ValueError("duplicate case identity")
        records[item["case"]]=r
    expected=[case_id(h,s,l,f,k) for h in protocol["hardware"] for s in protocol["scenarios"]
        for f,k in ((1.,"rolling"),(.5,"rolling"),(1.,"fixed")) for l in protocol["levels"]]
    missing=sorted(set(expected)-set(records))
    write_json(root/"completed-failed-missing.json",dict(expected=len(expected),completed=len(records),failed=failures,missing=missing,
        omitted_hardware=sorted(set(protocol["all_hardware"])-set(protocol["hardware"]))))
    if missing or failures: raise ValueError("study incomplete; see explicit run inventory")
    rows=[]; screens=[]
    for h in protocol["hardware"]:
        for s in protocol["scenarios"]:
            for f,k in ((1.,"rolling"),(.5,"rolling"),(1.,"fixed")):
                series=[records[case_id(h,s,l,f,k)] for l in protocol["levels"]]
                for lo,hi in ((0,1),(1,2)):
                    screens.append(dict(hardware=h,scenario=s,mode_factor=f,kind=k,levels=[lo,hi],
                        **qualify_pair(series[lo],series[hi],derive_hardware(manifest(),h)["working_energy_wh"])))
                r=series[-1]
                rows.append(dict(hardware=h,scenario=s,mode_factor=f,kind=k,level=2,score=r["score"],exact_score=r["exact_score"],
                    earned_priority=r["earned_priority"],total_priority=r["total_priority"],
                    on_time_count=sum(x["credited_products"] for x in r["requests"]),acquired_bits=r["acquired_bits"],
                    queued_bits=r["final_custody"]["queued_bits"],partial_bits=r["final_custody"]["partial_bits"],
                    completed_delivery_bits=r["final_custody"]["delivered_bits"],
                    actual_denials=sum(bool(d["feedback_reasons"]) for d in r.get("decisions",[])),
                    forecast_rejection_count=sum(len(d["rejections"]) for d in r.get("decisions",[])),
                    final_energy_wh=r["final_custody"]["energy_wh"],min_energy_wh=min(b["energy_wh"] for b in r["boundaries"]),
                    runtime_seconds=r["runtime_seconds"]))
    write_json(root/"comparison.json",rows)
    write_json(root/"numerical.json",screens)
    with (root/"comparison.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    fine=[q for q in screens if q["levels"]==[1,2]]
    write_json(root/"qualification-summary.json",dict(qualified=sum(q["qualified"] for q in fine),total=len(fine),
        max_energy_difference_wh=max(q["max_energy_difference_wh"] for q in fine),
        max_temperature_difference_k=max(q["max_temperature_difference_k"] for q in fine),
        action_changes=sum(not q["actions_equal"] for q in fine),completion_time_changes=sum(not q["completion_times_equal"] for q in fine)))
    # Matplotlib cache/fonts stay external, including on first import.
    os.environ["MPLCONFIGDIR"]=str(root/"plot-cache")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size":9,"figure.dpi":150,"savefig.dpi":300,"pdf.fonttype":42})
    out=root/"figures";out.mkdir(exist_ok=True)
    def save(fig,name):
        fig.savefig(out/(name+".pdf"),bbox_inches="tight")
        fig.savefig(out/(name+".png"),bbox_inches="tight")
        plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,3.6),sharey=True)
    for ax,s in zip(axes,protocol["scenarios"]):
        values=[next(r for r in rows if r["hardware"]==h and r["scenario"]==s and r["mode_factor"]==1 and r["kind"]=="rolling")["score"] for h in protocol["hardware"]]
        ax.bar(protocol["hardware"],values,color=[{"D":"#0072B2","H":"#E69F00","J":"#009E73"}[h[0]] for h in protocol["hardware"]])
        ax.set_title(s+": prescribed contacts");ax.set_ylim(0,1.05);ax.tick_params(axis="x",rotation=60)
    axes[0].set_ylabel("Complete on-time priority / 12")
    save(fig,"comparison")
    fig,axes=plt.subplots(3,1,figsize=(9,7),sharex=True)
    for contrast in protocol["contrasts"]:
        h,s=contrast.rsplit("-",1)
        if h not in protocol["hardware"]: continue
        r=records[case_id(h,s,2,1.)]; b=r["boundaries"];times=[v["seconds"]/60 for v in b]
        axes[0].plot(times,[v["energy_wh"] for v in b],label=contrast)
        axes[1].plot(times,[v["temperatures_k"]["payload"] for v in b],label=contrast)
        axes[2].step(times,[v["queued_bits"]/1e9 for v in b],where="post",label=contrast)
    for ax,label in zip(axes,("Battery energy (Wh)","Payload temperature (K)","Onboard raw bits (Gbit)")): ax.set_ylabel(label);ax.grid(alpha=.2)
    axes[0].legend(ncol=3,fontsize=8);axes[-1].set_xlabel("Physical time (min)")
    save(fig,"predeclared-resource-contrasts")
    fig,axes=plt.subplots(1,2,figsize=(11,3.6))
    for s,marker in (("S1","o"),("S2","s")):
        delta=[]
        for h in protocol["hardware"]:
            a=records[case_id(h,s,2,1.)];b=records[case_id(h,s,2,.5)]
            delta.append(b["score"]-a["score"])
        axes[0].plot(protocol["hardware"],delta,marker=marker,label=s)
    axes[0].axhline(0,color="gray",linewidth=.5);axes[0].set_ylabel("Score(0.5 proxy) - score(1.0 proxy)")
    axes[0].tick_params(axis="x",rotation=60);axes[0].legend()
    for lo,hi in ((0,1),(1,2)):
        values=[q["max_temperature_difference_k"] for q in screens if q["levels"]==[lo,hi] and q["kind"]=="rolling"]
        axes[1].plot(range(len(values)),values,label=f"levels {lo} / {hi}")
    axes[1].axhline(.1,color="red",linestyle="--",label="declared 0.1 K screen")
    axes[1].set_ylabel("Maximum common-boundary difference (K)");axes[1].set_xlabel("Hardware / scenario / mode-factor case index");axes[1].legend()
    save(fig,"sensitivity-and-refinement")
    return dict(cases=len(records),fine_screens=len(fine),passed=sum(q["qualified"] for q in fine))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(report(external(args.archive))))
