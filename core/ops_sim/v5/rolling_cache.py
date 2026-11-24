"""Two isolated public-model cache banks; original anchor/grid is authoritative."""
from dataclasses import dataclass, field, asdict
from .long_nominal_provider import LongNominalProvider
from .long_environment import AcquiredLongEnvironment
from .rolling_contract import RollingQuotas, typed, integer


@dataclass(slots=True)
class CumulativeWork:
    forecast_invocations: int = 0
    forecast_physical_reserved: int = 0
    actual_physical_reserved: int = 0
    harness_compiles: int = 0
    construction_line_reserved: int = 0
    nominal_force_reserved: int = 0
    control_reserved: int = 0
    output_bytes: int = 0
    output_capacity_peak_bytes: int = 0
    output_admission_events: int = 0
    publication_reencoded_bytes: int = 0
    publication_reuse_hits: int = 0
    publication_digests: dict = field(default_factory=dict)
    publication_reuse_mode: bool = False
    publication_reuse_seen: tuple = ()
    reconstructions: int = 0
    decisions: int = 0
    invocation_records: list = field(default_factory=list)

    def admit_output_capacity(self, count, quotas):
        integer(count,'publication allowance',0,quotas.max_output_bytes)
        used=self.publication_reencoded_bytes if self.publication_reuse_mode else max(self.output_bytes,self.publication_reencoded_bytes)
        if used+count>quotas.max_output_bytes:
            raise ValueError('B47_OUTPUT_CAPACITY_BEFORE_ALLOCATION')
        self.output_capacity_peak_bytes=max(self.output_capacity_peak_bytes,count)
        self.output_admission_events+=1
        if self.output_admission_events>1024: raise ValueError('output admission event bound')

    def charge(self, name, count, quotas):
        typed(quotas, RollingQuotas); integer(count, 'prospective charge', 0, 2**48)
        value = getattr(self, name)+count
        cap = getattr(quotas, 'max_'+name)
        if value > cap:
            raise ValueError('B47_CUMULATIVE_QUOTA:'+name)
        setattr(self, name, value)

    def reserve_forecast(self, model, quotas):
        # A complete old invocation ceiling is admitted before branch allocations.
        self.charge('forecast_invocations', 1, quotas)
        self.charge('forecast_physical_reserved', model.limits.max_physical_substeps, quotas)
        self.charge('construction_line_reserved', 8*model.limits.max_physical_substeps, quotas)
        # Initialization + catch-up + at most four suffix guards/planners.
        self.charge('harness_compiles', 10, quotas)
        self.charge('control_reserved', model.limits.max_output_control_units+10*2**20, quotas)
        self.admit_output_capacity(32*2**20,quotas)

    def record(self, kind, state):
        self.invocation_records.append(dict(kind=kind, runtime=asdict(state.runtime_work),
            construction=asdict(state.construction.work), harness=asdict(state.harness.work)))
        if len(self.invocation_records) > 520:
            raise ValueError('bounded invocation history')

    def validate(self, quotas):
        for name in ('forecast_invocations', 'forecast_physical_reserved', 'actual_physical_reserved',
                     'harness_compiles', 'construction_line_reserved', 'nominal_force_reserved',
                     'control_reserved', 'output_bytes', 'reconstructions'):
            integer(getattr(self, name), name, 0, getattr(quotas, 'max_'+name))
        integer(self.decisions, 'decisions', 0, 192)
        integer(self.output_capacity_peak_bytes,'peak output allowance',0,quotas.max_output_bytes)
        integer(self.output_admission_events,'output admissions',0,1024)
        integer(self.publication_reencoded_bytes,'cumulative encoded work',0,quotas.max_output_bytes)
        integer(self.publication_reuse_hits,'exact output reuse hits',0,2048)
        if type(self.publication_digests) is not dict or len(self.publication_digests)>1024:
            raise ValueError('bounded publication binding map')
        for key,size in self.publication_digests.items():
            if type(key) is not str or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):
                raise ValueError('exact publication hash')
            integer(size,'bound publication length',1,quotas.max_output_bytes)
        if sum(self.publication_digests.values())>self.output_bytes or type(self.publication_reuse_mode) is not bool or type(self.publication_reuse_seen) is not tuple:
            raise ValueError('inconsistent encoded-publication ledger')


def canonical_size(tree,limit):
    """Exact UTF-8 size for the pinned JSON spelling, before blob allocation.

    String spelling uses the standard-library encoder; repeated immutable key
    spellings are locally cached. This does not touch scientific arithmetic.
    """
    import json
    strings={};total=0;visits=0;todo=[(tree,0)]
    def string_size(s):
        if s in strings: return strings[s]
        size=len(json.dumps(s,ensure_ascii=False,allow_nan=False).encode('utf-8'))
        if len(strings)<4096: strings[s]=size
        return size
    while todo:
        v,depth=todo.pop();visits+=1
        if visits>8*2**20 or depth>64: raise ValueError('bounded publication tree')
        if type(v) is dict:
            if len(v)>65536 or any(type(k) is not str for k in v): raise ValueError('exact publication object')
            total+=2+max(0,len(v)-1)+len(v)+sum(string_size(k) for k in v)
            todo.extend((x,depth+1) for x in v.values())
        elif type(v) in (list,tuple):
            if len(v)>65536: raise ValueError('bounded publication list')
            total+=2+max(0,len(v)-1);todo.extend((x,depth+1) for x in v)
        elif type(v) is str: total+=string_size(v)
        elif v is None: total+=4
        elif type(v) is bool: total+=4 if v else 5
        elif type(v) is int: total+=len(str(v))
        elif type(v) is float:
            total+=len(json.dumps(v,allow_nan=False))
        else: raise TypeError('JSON publication scalar')
        if total>limit: raise ValueError('B47_PUBLICATION_TREE_LIMIT')
    return total


def paid_publication(value,work,quotas,limit):
    """Exact streaming byte admission before allocation of a complete JSON blob.

    A capacity allowance is unallocated room, not spent work/refunded quota.
    Actual encoded publications and prospective encoder control work remain
    cumulative, including refused forecasts and fresh reconstruction.
    """
    from .long_mission_continuation import _scientific
    import json
    work.charge('control_reserved',16*2**20+2*((limit+63)//64),quotas)
    tree=_scientific(value)
    total=canonical_size(tree,limit)
    work.admit_output_capacity(total,quotas)
    raw=json.dumps(tree,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(raw)!=total: raise ValueError('unstable scientific encoding')
    work.publication_reencoded_bytes+=total
    from hashlib import sha256
    key=sha256(raw).hexdigest()
    if work.publication_reuse_mode:
        if key not in work.publication_digests or work.publication_digests[key]!=total or key in work.publication_reuse_seen:
            raise ValueError('REPLAY_PUBLICATION_NOT_EXACT_PRIOR_CONTENT')
        work.publication_reuse_seen=(*work.publication_reuse_seen,key)
        work.publication_reuse_hits+=1
    elif key not in work.publication_digests:
        work.charge('output_bytes',total,quotas);work.publication_digests[key]=total
    else:
        if work.publication_digests[key]!=total: raise ValueError('publication length/hash mismatch')
        work.publication_reuse_hits+=1
    work.validate(quotas)
    return raw


class PublicCacheBank:
    def __init__(self, model, work, quotas, ownership):
        if ownership not in ('ACTUAL_PUBLIC_MODEL', 'FORECAST_PUBLIC_MODEL'):
            raise ValueError('cache ownership required')
        self.model = model; self.ownership = ownership; self.work = work; self.quotas = quotas
        def charge(name, count):
            if name == 'nominal_force_reserved': work.charge('nominal_force_reserved', count, quotas)
            else: work.charge('control_reserved', count, quotas)
        self.provider = LongNominalProvider(model.environment.trajectory, model.nominal_policy, charge=charge)
        self.environment = AcquiredLongEnvironment(model.environment, self.provider, charge=charge)

    def bind(self, runtime):
        return MeteredProvider(self, runtime), MeteredEnvironment(self, runtime)

    def accounting(self):
        return dict(ownership=self.ownership, provider=self.provider.accounting(), environment=self.environment.accounting())


class MeteredProvider:
    def __init__(self, bank, runtime):
        self.bank = bank; self.runtime = runtime; self.identity = bank.provider.identity
    def at_seconds(self, value):
        before = asdict(self.bank.provider.work)
        try:
            return self.bank.provider.at_seconds(value)
        finally:
            after = asdict(self.bank.provider.work)
            for name, key in (('nominal_force_reserved', 'force_reserved'), ('nominal_control_units', 'control_reserved'), ('nominal_orbit_queries', 'queries')):
                self.runtime.charge(name, after[key]-before[key], self.bank.model.limits)
            self.runtime.nominal_force_completed += after['force_completed']-before['force_completed']
            self.runtime.nominal_unknown_events += after['unknown_primitive_events']-before['unknown_primitive_events']
    def validate(self, *args):
        return self.bank.provider.validate(*args)


class MeteredEnvironment:
    def __init__(self, bank, runtime):
        self.bank = bank; self.runtime = runtime
        self.identity = bank.environment.identity
        self.signature = None; self.supports = (); self.steps = {}
    def _call(self, name, *args):
        before = self.bank.environment.controls
        try:
            return getattr(self.bank.environment, name)(*args)
        finally:
            self.runtime.charge('index_control_units', self.bank.environment.controls-before, self.bank.model.limits)
    def guard(self): return self._call('guard')
    def schedule(self, a, b): return self._call('schedule', a, b)
