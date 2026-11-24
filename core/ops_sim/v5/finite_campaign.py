"""B59 forward-only wrapper policy. No physical root or old-store migration."""
from dataclasses import dataclass,asdict
from hashlib import sha256
import json
STORE='B59_FINITE_BATTERY_STORE_V3'
METHOD='B59_TEN_JOB_EIGHT_PRIMARY_BATTERY_V1'
@dataclass(frozen=True,slots=True)
class FiniteCampaignPolicy:
    method:str=METHOD
    maximum_jobs:int=10
    maximum_lineage_jobs:int=10
    maximum_reserved_job_output_bytes:int=1536*2**20
    maximum_output_bytes:int=128*2**20
    maximum_primary_segments:int=8
    reserved_diagnostic_slots:int=2
    maximum_observed_primary_seconds:int=10800
    hard_seconds:int=1550
    soft_seconds:int=1250
    finalization_seconds:int=300
    cleanup_seconds:int=2
    maximum_rss_bytes:int=768*2**20
    maximum_native_bytes:int=64*2**20
    def __post_init__(self):
        for n,f in self.__dataclass_fields__.items():
            if type(getattr(self,n))is not type(f.default) or getattr(self,n)!=f.default:raise ValueError('exact B59 named policy: '+n)
        # Prospective maximum, not observed average files. Existing chain
        # metadata cap (128 * 256 KiB + 1 MiB) is separate from job output.
        if self.maximum_jobs*self.maximum_output_bytes+33*2**20>self.maximum_reserved_job_output_bytes:raise ValueError('prospective store reservation')
    @property
    def identity(self):
        self.__post_init__();return sha256(json.dumps(asdict(self),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def admit_policy(data):
    if type(data)is not dict or set(data)!=set(FiniteCampaignPolicy.__dataclass_fields__):raise ValueError('finite policy schema')
    return FiniteCampaignPolicy(**data)


def intent_role(intent,parent,checkpoint,target):
    """Declared mode/window plus admitted native lineage; no event inference."""
    diagnostic=(intent['mode']in ('DIAGNOSTIC_NORMAL','DIAGNOSTIC_VERBOSE') or intent['window_end_seconds']is not None or
                parent is not None and parent['result']is not None and checkpoint['clock']<parent['result']['clock'])
    if diagnostic:
        from .battery_terminal import admit_bound_terminal
        if parent is None or checkpoint is None or parent['result']is None:raise ValueError('diagnostic requires retained completed-target predecessor')
        t=admit_bound_terminal(parent['result']['typed_terminal'],parent,parent['result'])
        if t['kind']!='TARGET' or t['clock']!=target or checkpoint['clock']>=target:raise ValueError('diagnostic requires completed immutable target')
        return 'DIAGNOSTIC'
    return 'PRIMARY'

def admit_role_population(intent,parent,checkpoint,jobs,target):
    role=intent_role(intent,parent,checkpoint,target)
    index={j['job_id']:j for j in jobs};counts={'PRIMARY':0,'DIAGNOSTIC':0}
    for j in jobs:
        p=index.get(j['intent']['parent_job_id']);cp=None if j['resume']is None else j['resume']['checkpoint']
        counts[intent_role(j['intent'],p,cp,target)]+=1
    if role=='PRIMARY'and counts[role]>=8:raise ValueError('diagnostic slots cannot launch a ninth primary')
    if role=='DIAGNOSTIC'and counts[role]>=2:raise ValueError('only two reserved diagnostic slots')
    return role
