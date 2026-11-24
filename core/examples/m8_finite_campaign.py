"""New finite wrapper contract; actual runs require explicit store and command."""
from dataclasses import asdict
from ops_sim.v5.finite_campaign import FiniteCampaignPolicy
from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget

def wrapper_contract():
 p=FiniteCampaignPolicy()
 return dict(policy=asdict(p),identity=p.identity,execution_budget=asdict(ExecutionBudget(1550,1250,300)),
             prospective_bytes=10*128*2**20+33*2**20,reserved_bytes=1536*2**20)
if __name__=='__main__':
 import json
 print(json.dumps(wrapper_contract(),indent=2))
