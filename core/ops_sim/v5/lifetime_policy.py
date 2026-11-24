"""Explicit B62 finite lifetime store policy; old B59/B61 stores are not migrated."""
from dataclasses import dataclass,asdict
from hashlib import sha256
import json

STORE='B62_FINITE_B61_LIFETIME_STORE_V1'
METHOD='B62_SERIAL_LIFETIME_STORE_POLICY_V1'
PRODUCTION='LINUX_PRODUCTION'
QUALIFICATION='WINDOWS_ONLY_LOCAL_QUALIFICATION'
# Explicit local experimental execution, never Linux/physical qualification.
WINDOWS_USER='YEAR_V1_WINDOWS_AUTHORED_SERIAL_EXPERIMENT'
METHOD_OBJECTS='YEAR_V2_LOSSLESS_OBJECT_STORE_POLICY_V3'
METHOD_NO_LAUNCH='YEAR_V3_NO_LAUNCH_OBJECT_STORE_POLICY_V4'
METHOD_PHYSICAL='YEAR_V4_BOUNDED_PHYSICAL_STORE_POLICY_V5'
STORE_PHYSICAL='YEAR_V4_BOUNDED_PHYSICAL_LIFETIME_STORE_V1'
METHOD_PACKED='YEAR_V5_PACKED_TERMINAL_STORAGE_POLICY_V6'
STORE_PACKED='YEAR_V5_PACKED_PHYSICAL_LIFETIME_STORE_V2'

def packed_storage(policy):return type(policy)is LifetimeCampaignPolicyV2 and policy.method==METHOD_PACKED

def physical_storage(policy):return type(policy)is LifetimeCampaignPolicyV2 and policy.method in(METHOD_PHYSICAL,METHOD_PACKED)

def no_launch(policy):return type(policy)is LifetimeCampaignPolicyV2 and policy.method in(METHOD_NO_LAUNCH,METHOD_PHYSICAL,METHOD_PACKED)

def object_storage(policy):
    return type(policy)is LifetimeCampaignPolicyV2 and policy.method in(METHOD_OBJECTS,METHOD_NO_LAUNCH,METHOD_PHYSICAL,METHOD_PACKED)

def windows_policy(policy):
    return policy.mode in (QUALIFICATION,WINDOWS_USER)

@dataclass(frozen=True,slots=True)
class LifetimeCampaignPolicy:
    method:str=METHOD
    mode:str=PRODUCTION
    maximum_primary_segments:int=4096
    reserved_diagnostic_slots:int=4
    maximum_output_bytes:int=128*2**20
    hard_seconds:int=900
    soft_seconds:int=840
    finalization_seconds:int=60
    cleanup_seconds:int=2
    maximum_observed_primary_seconds:int=4096*902
    maximum_diagnostic_seconds:int=4*902
    maximum_rss_bytes:int=768*2**20
    maximum_native_bytes:int=64*2**20
    maximum_metadata_bytes:int=64*2**20
    initial_package_reserve_bytes:int=128*2**20
    backup_copies:int=1
    maximum_journal_records:int=16384
    maximum_journal_record_bytes:int=4096
    def __post_init__(self):
        if type(self.method)is not str or self.method!=METHOD or type(self.mode)is not str or self.mode not in (PRODUCTION,QUALIFICATION):raise ValueError('B62 named lifetime mode/policy')
        limits=dict(maximum_primary_segments=(2,8192),reserved_diagnostic_slots=(1,8),maximum_output_bytes=(16*2**20,128*2**20),hard_seconds=(35,1200),soft_seconds=(1,1170),finalization_seconds=(30,300),cleanup_seconds=(2,2),maximum_observed_primary_seconds=(1,8192*1202),maximum_diagnostic_seconds=(1,8*1202),maximum_rss_bytes=(768*2**20,768*2**20),maximum_native_bytes=(64*2**20,64*2**20),maximum_metadata_bytes=(2**20,64*2**20),initial_package_reserve_bytes=(64*2**20,128*2**20),backup_copies=(1,2),maximum_journal_records=(64,65536),maximum_journal_record_bytes=(4096,16384))
        for n,(lo,hi)in limits.items():
            v=getattr(self,n)
            if type(v)is not int or not lo<=v<=hi:raise ValueError('B62 exact finite policy integer: '+n)
        if self.maximum_journal_records<2*self.maximum_jobs+16:raise ValueError('B62 full dispatch/settlement journal population reserve')
        if self.maximum_journal_records*self.maximum_journal_record_bytes>self.maximum_metadata_bytes:raise ValueError('B62 journal reservation exceeds metadata')
        if self.soft_seconds+self.finalization_seconds!=self.hard_seconds:raise ValueError('B62 execution partition')
        if self.maximum_observed_primary_seconds<self.hard_seconds+2 or self.maximum_diagnostic_seconds<self.hard_seconds+2:raise ValueError('B62 full next-job wall reserve')
        if self.mode==QUALIFICATION and (self.maximum_primary_segments>8 or self.reserved_diagnostic_slots>2 or self.hard_seconds>240):raise ValueError('B62 local qualification is bounded and not production acceptance')
    @property
    def maximum_jobs(self):return self.maximum_primary_segments+self.reserved_diagnostic_slots
    @property
    def maximum_lineage_jobs(self):return self.maximum_jobs
    @property
    def maximum_reserved_job_output_bytes(self):return self.maximum_jobs*self.maximum_output_bytes+self.maximum_metadata_bytes+self.initial_package_reserve_bytes
    @property
    def pool_commitment_bytes(self):return self.maximum_reserved_job_output_bytes*(1+self.backup_copies)
    @property
    def disk_limit_bytes(self):return self.maximum_reserved_job_output_bytes
    @property
    def identity(self):
        self.__post_init__();return sha256(json.dumps(asdict(self),sort_keys=True,separators=(',',':')).encode()).hexdigest()

def admit_policy(data):
    if type(data)is not dict or set(data)!=set(LifetimeCampaignPolicy.__dataclass_fields__):raise ValueError('B62 exact lifetime policy fields')
    return (LifetimeCampaignPolicyV2 if data.get('method')in(METHOD_V2,METHOD_OBJECTS,METHOD_NO_LAUNCH,METHOD_PHYSICAL,METHOD_PACKED) else LifetimeCampaignPolicy)(**data)

def is_finite(policy):
    # Deliberate typed branch for the new owner. Legacy policy admission is
    # unchanged; this helper never coerces an arbitrary duck-typed object.
    from .finite_campaign import FiniteCampaignPolicy
    return type(policy)in(FiniteCampaignPolicy,LifetimeCampaignPolicy,LifetimeCampaignPolicyV2)

def admit_roles(policy,intent,parent,checkpoint,jobs,target,*,administrative_job_ids=()):
    from .finite_campaign import intent_role
    role=intent_role(intent,parent,checkpoint,target)
    if role=='DIAGNOSTIC' and intent['mode'] not in ('DIAGNOSTIC_NORMAL','DIAGNOSTIC_VERBOSE'):raise ValueError('B62 diagnostic mode must be explicit; MAIN cannot rewind')
    index={j['job_id']:j for j in jobs};counts={'PRIMARY':0,'DIAGNOSTIC':0}
    for j in jobs:counts[intent_role(j['intent'],index.get(j['intent']['parent_job_id']),None if j['resume']is None else j['resume']['checkpoint'],target)]+=1
    cap=policy.maximum_primary_segments if role=='PRIMARY'else policy.reserved_diagnostic_slots
    if counts[role]>=cap:raise ValueError('B62 role reservation exhausted: '+role)
    if role=='PRIMARY':
        prim=[j for j in jobs if j['job_id']not in administrative_job_ids and intent_role(j['intent'],index.get(j['intent']['parent_job_id']),None if j['resume']is None else j['resume']['checkpoint'],target)=='PRIMARY']
        if not prim:
            if parent is not None:raise ValueError('B62 first primary must be initial')
        else:
            parents={x['intent']['parent_job_id']for x in prim}
            leaves=[j for j in prim if j['job_id']not in parents]
            if len(leaves)!=1 or parent is None or parent['job_id']!=leaves[0]['job_id']:raise ValueError('B62 latest forward primary only; no reinitialization/rewind')
            if checkpoint!=parent['result']['checkpoint']:raise ValueError('B62 MAIN must use exact settled FINAL native/publication authority')
    return role


def compact_index(store,names):
    """Read/validate one complete job at a time, retaining only admission data.

    Full results remain in their immutable streams. This new store's jobs()
    returns an admission index; job(id) remains the complete typed job API.
    """
    rows=[]
    for jid in sorted(names):
        j=store.job(jid)
        if j['result']is not None:
            j['result']={k:j['result'][k]for k in ('typed_terminal','checkpoint','clock',
                'actual_end_seconds','target_seconds','application_status','status','reason')}
        if j['launch']is not None:
            j['launch']={k:j['launch'].get(k)for k in ('observed_envelope_seconds','forced_interruption','timeout','unexpected')}
        j['progress']=None;j['checkpoints']=[]
        rows.append(j)
        if j['status']in ('COMPLETED','INCOMPLETE','CANCELLED','REFUSED','PROCESS_FAILED','UNKNOWN'):
            store._cache.pop(jid,None)
            writer=store._status_writers.pop(jid,None)
            if writer is not None and not writer.head.closed:writer.close()
            catalog=store._catalogs.pop(jid,None)
            if catalog is not None:catalog.close()
    return rows


METHOD_V2='B63_SERIAL_LIFETIME_STORE_POLICY_V2'
STORE_V2='B63_FINITE_PREPARED_LIFETIME_STORE_V2'

@dataclass(frozen=True,slots=True)
class LifetimeCampaignPolicyV2(LifetimeCampaignPolicy):
    """New storage/dispatch identity. Same finite bounds, no B62 migration."""
    method:str=METHOD_V2
    def __post_init__(self):
        if type(self.method)is not str or self.method not in(METHOD_V2,METHOD_OBJECTS,METHOD_NO_LAUNCH,METHOD_PHYSICAL,METHOD_PACKED):raise ValueError('B63 exact lifetime method')
        if type(self.mode)is not str or self.mode not in(PRODUCTION,QUALIFICATION,WINDOWS_USER):raise ValueError('YEAR-V1 exact finite V2 mode')
        if self.mode==WINDOWS_USER and (self.maximum_primary_segments>1024 or self.reserved_diagnostic_slots>2 or self.hard_seconds>900):raise ValueError('YEAR-V1 finite experimental serial policy')
        values=asdict(self);values['method']=METHOD
        if self.mode==WINDOWS_USER:values['mode']=PRODUCTION # validate same finite fields; no Linux execution claim
        LifetimeCampaignPolicy(**values)
        if self.method in(METHOD_PHYSICAL,METHOD_PACKED) and self.backup_copies!=1:raise ValueError('YEAR-V4/V5 exactly one independently reserved full backup')

    @property
    def pool_commitment_bytes(self):
        if physical_storage(self):
            from .lifetime_physical_storage import contract
            return contract(self)['whole_study_commitment_bytes']
        return self.maximum_reserved_job_output_bytes*(1+self.backup_copies)

    @property
    def disk_limit_bytes(self):
        if physical_storage(self):
            from .lifetime_physical_storage import contract
            value=contract(self)
            return value['global_retained_cap_bytes']+value['maximum_concurrent_write_reserve_bytes']+value['terminal_checkpoint_headroom_bytes']+value['maximum_temporary_overlap_bytes']+value['bounded_index_metadata_bytes']
        return self.maximum_reserved_job_output_bytes

def is_v2(policy):return type(policy)is LifetimeCampaignPolicyV2

def is_lifetime(policy):return type(policy)in(LifetimeCampaignPolicy,LifetimeCampaignPolicyV2)
