"""Finite, immutable wrapper-store admission; never a numerical root policy.

The legacy wire and four-job population are unchanged. The new named policy is
selected only when a new store is created; saved stores are never migrated.
"""
from dataclasses import asdict,dataclass
from hashlib import sha256
import json

STORE_V1='B52_PINNED_LIFECYCLE_STORE_V1'
STORE_V2='B54_FINITE_SEGMENTED_LIFECYCLE_STORE_V2'
SEGMENTED='B54_FINITE_SEGMENTED_MAIN_LINEAGE_V1'
STORE_FIELDS=('format','root_identity','source_identity','runtime','input_sha256','input_bytes','created_utc','project','admission','maximum_jobs')
POLICY_FIELDS=('method','maximum_jobs','maximum_lineage_jobs','maximum_reserved_job_output_bytes')


@dataclass(frozen=True,slots=True)
class LifecycleRunnerStorePolicy:
    method:str=SEGMENTED
    maximum_jobs:int=8
    maximum_lineage_jobs:int=8
    maximum_reserved_job_output_bytes:int=1536*2**20

    def __post_init__(self):
        values=(SEGMENTED,8,8,1536*2**20)
        for name,expected in zip(POLICY_FIELDS,values):
            value=getattr(self,name)
            if type(value) is not type(expected) or value!=expected:
                raise ValueError('exact named finite runner-store policy required: '+name)

    @property
    def identity(self):
        self.__post_init__()
        raw=json.dumps(asdict(self),sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')
        return sha256(raw).hexdigest()


def requested_runner_policy(name):
    if type(name) is not str:raise TypeError('exact named runner-store selection required')
    from .finite_campaign import METHOD as FINITE,FiniteCampaignPolicy
    from .lifetime_campaign import METHOD as LIFETIME,LifetimeCampaignPolicy
    from .lifetime_policy import METHOD_V2,METHOD_PHYSICAL,METHOD_PACKED,LifetimeCampaignPolicyV2
    if name==METHOD_PACKED:return LifetimeCampaignPolicyV2(method=METHOD_PACKED)
    if name==METHOD_PHYSICAL:return LifetimeCampaignPolicyV2(method=METHOD_PHYSICAL)
    if name==METHOD_V2:return LifetimeCampaignPolicyV2()
    if name==LIFETIME:return LifetimeCampaignPolicy()
    if name==FINITE:return FiniteCampaignPolicy()
    if name=='LEGACY':return None
    if name==SEGMENTED:return LifecycleRunnerStorePolicy()
    raise ValueError('unknown runner-store policy')


def admit_runner_store_metadata(meta):
    """Pure strict wire admission, also usable by portable saved-data consumers.

    Returns policy/limits, not source/runtime trust; the caller must bind the
    remaining store metadata and immutable input before using the returned caps.
    """
    from .finite_campaign import STORE as FINITE_STORE,admit_policy
    from .lifetime_campaign import STORE as LIFETIME_STORE,admit_policy as admit_lifetime
    from .lifetime_policy import STORE_V2 as LIFETIME_V2,STORE_PHYSICAL,STORE_PACKED,is_v2,physical_storage,packed_storage
    if type(meta) is not dict:raise TypeError('exact store metadata object required')
    if type(meta.get('format')) is not str:raise TypeError('exact store format required')
    from .lifecycle_compact import STORE as COMPACT_STORE,admit_profile
    if meta['format']==COMPACT_STORE:
        admit_profile(meta['publication_profile'],meta['publication_profile_identity'])
        base={k:v for k,v in meta.items() if k not in ('base_store_format','publication_profile','publication_profile_identity')}
        base['format']=meta['base_store_format']
        if base['format'] not in (STORE_V1,STORE_V2,FINITE_STORE,LIFETIME_STORE,LIFETIME_V2,STORE_PHYSICAL,STORE_PACKED):raise ValueError('compact base store format')
        return admit_runner_store_metadata(base)
    if meta['format']==STORE_V1:
        if set(meta)!=set(STORE_FIELDS):raise ValueError('legacy store field set')
        if type(meta['maximum_jobs']) is not int or meta['maximum_jobs']!=4:raise ValueError('legacy store cap remains four')
        return None,4,4,2**31
    if meta['format']in(LIFETIME_V2,STORE_PHYSICAL,STORE_PACKED):
        if set(meta)!=set((*STORE_FIELDS,'runner_policy','runner_policy_identity','execution_authority_sha256')):raise ValueError('B63 lifetime store fields')
        p=admit_lifetime(meta['runner_policy'])
        h=meta['execution_authority_sha256']
        if not is_v2(p)or type(h)is not str or len(h)!=64 or any(c not in '0123456789abcdef'for c in h):raise ValueError('B63 policy/authority pin')
        expected_format=STORE_PACKED if packed_storage(p) else STORE_PHYSICAL if physical_storage(p) else LIFETIME_V2
        if meta['format']!=expected_format:raise ValueError('YEAR-V4/V5 explicit physical method/store format binding; no migration')
        if type(meta['maximum_jobs'])is not int or meta['maximum_jobs']!=p.maximum_jobs or meta['runner_policy_identity']!=p.identity:raise ValueError('B63 lifetime store policy binding')
        return p,p.maximum_jobs,p.maximum_lineage_jobs,p.maximum_reserved_job_output_bytes
    if meta['format']==LIFETIME_STORE:
        if set(meta)!=set((*STORE_FIELDS,'runner_policy','runner_policy_identity')):raise ValueError('lifetime store fields')
        p=admit_lifetime(meta['runner_policy'])
        from .lifetime_policy import LifetimeCampaignPolicy
        if type(p)is not LifetimeCampaignPolicy:raise ValueError('legacy lifetime metadata cannot acquire B63 policy')
        if type(meta['maximum_jobs'])is not int or meta['maximum_jobs']!=p.maximum_jobs or meta['runner_policy_identity']!=p.identity:raise ValueError('lifetime store policy binding')
        return p,p.maximum_jobs,p.maximum_lineage_jobs,p.maximum_reserved_job_output_bytes
    if meta['format']==FINITE_STORE:
        if set(meta)!=set((*STORE_FIELDS,'runner_policy','runner_policy_identity')):raise ValueError('finite store fields')
        p=admit_policy(meta['runner_policy'])
        if type(meta['maximum_jobs'])is not int or meta['maximum_jobs']!=10 or meta['runner_policy_identity']!=p.identity:raise ValueError('finite store policy binding')
        return p,p.maximum_jobs,p.maximum_lineage_jobs,p.maximum_reserved_job_output_bytes
    if meta['format']!=STORE_V2:raise ValueError('unknown runner-store format')
    if set(meta)!=set((*STORE_FIELDS,'runner_policy','runner_policy_identity')):raise ValueError('segmented store field set')
    data=meta['runner_policy']
    if type(data) is not dict or set(data)!=set(POLICY_FIELDS):raise ValueError('segmented runner policy field set')
    policy=LifecycleRunnerStorePolicy(**data)
    if type(meta['maximum_jobs']) is not int or meta['maximum_jobs']!=policy.maximum_jobs:raise ValueError('segmented population binding')
    if type(meta['runner_policy_identity']) is not str or meta['runner_policy_identity']!=policy.identity:raise ValueError('segmented runner policy identity')
    return policy,policy.maximum_jobs,policy.maximum_lineage_jobs,policy.maximum_reserved_job_output_bytes
