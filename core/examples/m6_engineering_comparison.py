"""Run an explicitly bounded two-root synthetic engineering comparison."""
from pathlib import Path
import argparse,json
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.engineering_experiment import ExperimentContract,execute_experiment
from ops_sim.v5.rolling_execution import paid_scientific_bytes
from ops_sim.v5.command_document import inputs_to_json
from ops_sim.v5.long_mission_continuation import _scientific
from ops_sim.v5.long_mission_document import canonical_json
from examples.m5_rolling_mission_demo import summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hypothesis',choices=('wire','placement'),default='wire')
    p.add_argument('--output-directory',type=Path,required=True);a=p.parse_args()
    if a.hypothesis=='wire':
        roots=(make_inputs(wire='weakness'),make_inputs(wire='repair'));hypothesis='PAYLOAD_WIRE_CROSS_SECTION'
    else:roots=(make_inputs('compact'),make_inputs('outboard'));hypothesis='ASSEMBLY_PLACEMENT'
    contract=ExperimentContract('b48-'+a.hypothesis,*roots,hypothesis)
    out=a.output_directory;out.mkdir()
    (out/'contract.json').write_text(canonical_json(_scientific(contract))+'\n',encoding='utf-8')
    for label,root in zip(('baseline','intervention'),roots):
        (out/(label+'.inputs.json')).write_text(inputs_to_json(root)+'\n',encoding='utf-8')
    states,result=execute_experiment(contract)
    for label,state in zip(('baseline','intervention'),states):
        (out/(label+'.science.json')).write_bytes(paid_scientific_bytes(state))
        (out/(label+'.summary.json')).write_text(json.dumps(summary(state),default=str,indent=2)+'\n',encoding='utf-8')
        (out/(label+'.diagnosis.json')).write_text(canonical_json(_scientific(state.diagnosis))+'\n',encoding='utf-8')
    (out/'comparison.json').write_text(canonical_json(_scientific(result))+'\n',encoding='utf-8')
    print(json.dumps(dict(hypothesis=hypothesis,results=[{n:summary(s)[n] for n in ('status','credited_products','acquired','final_energy_wh')} for s in states])))


if __name__=='__main__':main()
