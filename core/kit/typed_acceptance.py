"""Produce B65 LONG evidence from real target-owned day/continuation stores.

Example (on the actual Linux runtime, after the day and process protocol):
 python -B -m kit.typed_acceptance --native-store NATIVE_DAY_STORE
   --python-reference-store PYTHON_DAY_STORE --legacy-day-evidence EVIDENCE.json
   --output NEW_EXTERNAL_DIRECTORY
Missing day, cleanup, restore-watch or equality evidence is a refusal.
"""
from pathlib import Path
import argparse,json
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--native-store',required=True,type=Path)
    p.add_argument('--python-reference-store',required=True,type=Path);p.add_argument('--legacy-day-evidence',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args(argv)
    from ops_sim.v5.lifetime_supervisor import _store
    from ops_sim.v5.lifetime_execution_authority import _binding,_qualification_binding
    from ops_sim.v5.portable_job import parse
    from ops_sim.v5.lifetime_typed_acceptance import produce
    store,plan=_store(a.native_store)
    try:
        contract=parse(store.path('portable-execution.json').read_bytes());raw=store.path('input.json').read_bytes()
        binding=_binding(store.root_input,raw,contract,store.runner_policy,contract['backend_binding']['selection'],contract['native_build'])
        result=produce(a.output,legacy_day_evidence=a.legacy_day_evidence,python_reference_store=a.python_reference_store,
            qualification_binding=_qualification_binding(binding),binding=binding)
    finally:store.close_publications()
    print(json.dumps(result,indent=2,ensure_ascii=False));return result
if __name__=='__main__':main()
