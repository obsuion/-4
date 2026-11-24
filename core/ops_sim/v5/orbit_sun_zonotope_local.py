"""Fresh-session full-zonotope refinement; public diagnostics are never seeds."""
from bisect import bisect_right
from dataclasses import dataclass, field, fields
from decimal import Decimal
from fractions import Fraction as Q
from hashlib import sha256
from math import isfinite

from . import orbit_j2_zonotope as _z
from . import orbit_j2_zonotope_segments as _s
from . import orbit_sun_zonotope_intervals as _b34
from . import orbit_sun_intervals as _g
from . import orbit_sun_windows as _w
from .orbit_config import _exact
from .experiment_codec import canonical_content, json_text

API_ID = "m2-zonotope-local-illumination-v1"
RESOURCE_VERSION = 1
# Global step IDs also own generator births: 32*32767+21 < 2**20.
MAX_TOTAL_STEPS = 32768
LIMITS = dict(max_initial_steps=4096, max_refinement_steps=28672,
              max_trials=64, max_passes=16, max_picard_attempts=393216,
              max_geometry_cells=65536, max_retained_evidence_units=1048576,
              max_geometry_operations=2**26)
_ZERO_ALLOWED = {"max_refinement_steps", "max_trials", "max_passes"}
# Separate finite orchestration schedules; numerical leaves remain unchanged.
_SET_SCAN = 1024 + 90*(64+4096)
_STEP_CONTROL = 4*_SET_SCAN + _s._CELL_CONTROL + 4096
_GEOMETRY_CONTROL = 4096
_PIECE_CONTROL = 2048
_TERMINAL_CONTROL = 8192


@dataclass(frozen=True, slots=True)
class ZonotopeLocalIlluminationPolicy:
    max_initial_steps: int
    max_refinement_steps: int
    max_trials: int
    max_passes: int
    max_picard_attempts: int
    max_geometry_cells: int
    max_retained_evidence_units: int
    max_geometry_operations: int
    resource_policy_version: int = field(init=False, default=RESOURCE_VERSION)

    def __post_init__(self):
        for name, upper in LIMITS.items():
            value = getattr(self, name)
            _exact(value, int, name)
            if not (0 if name in _ZERO_ALLOWED else 1) <= value <= upper:
                raise ValueError(name+" outside local domain")
        _exact(self.resource_policy_version, int, "resource_policy_version")
        if self.resource_policy_version != RESOURCE_VERSION:
            raise ValueError("unsupported local resource policy")
        if self.max_initial_steps+self.max_refinement_steps > MAX_TOTAL_STEPS:
            raise ValueError("global generator-birth domain exceeded")


@dataclass(frozen=True, slots=True)
class ZonotopeLocalIlluminationRequest:
    segment: _s.J2ZonotopeSegmentRequest
    table: _b34.SunPositionTable
    requested_resolution_seconds: float
    policy: ZonotopeLocalIlluminationPolicy
    api_id: str = field(init=False, default=API_ID)
    api_version: int = field(init=False, default=1)
    resource_policy_version: int = field(init=False, default=RESOURCE_VERSION)

    __hash__ = None

    def __post_init__(self):
        _exact(self.policy, ZonotopeLocalIlluminationPolicy, "local policy")
        self.policy.__post_init__()
        _exact(self.requested_resolution_seconds, float, "requested resolution")
        if not isfinite(self.requested_resolution_seconds) or not 0 < self.requested_resolution_seconds <= 86400:
            raise ValueError("positive finite resolution <=86400 seconds required")
        base = _b34.ZonotopeIntervalIlluminationRequest(self.segment, self.table,
                    _b34.ZonotopeIntervalIlluminationPolicy(5118))
        object.__setattr__(self, "segment", base.segment)
        object.__setattr__(self, "table", base.table)
        object.__setattr__(self, "policy", ZonotopeLocalIlluminationPolicy(
            **{n:getattr(self.policy,n) for n in LIMITS}))


def _request(value):
    _exact(value, ZonotopeLocalIlluminationRequest, "request")
    for n, v in (("api_id",API_ID),("api_version",1),("resource_policy_version",1)):
        _exact(getattr(value,n),type(v),n)
        if getattr(value,n) != v:
            raise ValueError("unsupported local input identity")
    return ZonotopeLocalIlluminationRequest(value.segment,value.table,
        value.requested_resolution_seconds,value.policy)


class _Failure(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ZonotopeBoundary:
    id: int
    parent_step_id: int | None
    set: _s.J2ZonotopeSegmentDiagnostic
    scale_exponents: tuple
    authority_digest: str


@dataclass(frozen=True, slots=True)
class LocalStep:
    id: int
    parent_boundary_id: int
    endpoint_boundary_id: int
    trial_index: int
    pass_index: int
    bridge: bool
    tube: _s.J2ZonotopeSegmentCell


@dataclass(frozen=True, slots=True)
class LocalGeometry:
    id: int
    step_id: int
    trial_index: int
    pass_index: int
    authority_digest: str
    cell: _g.IntervalIlluminationCell


@dataclass(frozen=True, slots=True)
class LocalPiece:
    start_seconds: Q
    end_seconds: Q
    geometry_record_id: int
    assessment: str
    reason: str
    endpoint_convention: str = field(init=False,default="LEFT_CLOSED_RIGHT_OPEN_FINAL_END_INCLUDED")


@dataclass(frozen=True, slots=True)
class LocalWindow:
    start_seconds: Q
    end_seconds: Q
    assessment: str
    reasons: tuple
    supports: tuple[LocalPiece,...]
    endpoint_convention: str = field(init=False,default="LEFT_CLOSED_RIGHT_OPEN_FINAL_END_INCLUDED")


@dataclass(frozen=True, slots=True)
class LocalTrial:
    index: int
    pass_index: int
    seed_boundary_id: int
    start_seconds: Q
    end_seconds: Q
    step_seconds: Q
    planned_steps: int
    planned_geometry_cells: int
    status: str
    step_ids: tuple
    geometry_record_ids: tuple


@dataclass(frozen=True, slots=True)
class _OwnedBoundary:
    record: ZonotopeBoundary
    z: _z._Zonotope
    signature: tuple


def _proof_signature(v):
    if type(v) is Q:return ("Q",v.numerator,v.denominator)
    if type(v) is Decimal:return ("D",v.as_tuple())
    if type(v) is tuple:return tuple(_proof_signature(x) for x in v)
    if type(v) in (str,int,bool,type(None)):return (type(v).__name__,v)
    raise _Failure("UNSUPPORTED_SIGNATURE_VALUE")


def _set_signature(z):
    # Called only under a precharged bounded set scan. Exact tuples, not a hash.
    if type(z) is not _z._Zonotope:
        raise _Failure("INVALID_FULL_SET_TYPE")
    return (tuple(x.as_tuple() for x in z.center),
            tuple(tuple(x.as_tuple() for x in c) for c in z.generators),z.births,(z.time.numerator,z.time.denominator))


def _record_signature(r):
    d = r.set
    return (r.id,r.parent_step_id,_set_signature(_z._Zonotope(
        d.center,d.generators,d.births,d.time)),r.scale_exponents,r.authority_digest)


def _merge(pieces):
    result=[]; group=[]
    for p in pieces:
        if group and (group[0].assessment,group[0].reason)!=(p.assessment,p.reason):
            result.append(LocalWindow(group[0].start_seconds,group[-1].end_seconds,
                group[0].assessment,(group[0].reason,),tuple(group)));group=[]
        group.append(p)
    if group:
        result.append(LocalWindow(group[0].start_seconds,group[-1].end_seconds,
            group[0].assessment,(group[0].reason,),tuple(group)))
    return tuple(result)


def _width(pieces):
    width=Q(0);first=None
    for p in pieces:
        if p.assessment=="UNRESOLVED":
            if first is None:first=p.start_seconds
            width=max(width,p.end_seconds-first)
        else:first=None
    return width


class _GeometryLedger(_b34._Rational):
    def __init__(self, maximum):
        super().__init__(maximum);self.control_units=0
    @property
    def total_operations(self):
        return self.operations+self.control_units
    def reserve(self, count):
        if type(count) is not int or count<0 or count>self.maximum-self.total_operations:
            raise _Failure("GEOMETRY_CONTROL_BUDGET_EXHAUSTED")
        self.control_units+=count
        self.limit=min(self.limit,self.maximum-self.control_units)
    def begin_cell(self):
        self.limit=min(self.operations+512,self.maximum-self.control_units)


# New-owner seams only; all existing owners remain frozen.
_transport = _z._transport_step_v3
_geometry_cell = _g._geometry_cell


class _Session:
    def __init__(self, q):
        self.q=q;self.p=q.segment.policy
        self.ar=_z._CoefficientArithmeticV3(self.p.base_policy.precision_digits,
                                           self.p.max_scalar_operations)
        self.ga=_GeometryLedger(q.policy.max_geometry_operations)
        self.anchor=Q(q.segment.trajectory.initial_state.position.instant.elapsed_seconds)
        self.end=Q(q.segment.end.elapsed_seconds)
        self.knots=tuple(Q(s.elapsed_seconds) for s in q.table.samples)
        self.boundaries=[];self.owned=[];self.steps=[];self.geometry=[];self.trials=[]
        self.step_signatures=[];self.geometry_signatures=[];self.boundary_signatures=[];self.actual_sets=[]
        self.pieces=();self.initial_pieces=();self.initial_steps=0;self.refinement_steps=0
        self.planned_picard=0;self.planned_geometry=0;self.evidence_reserved=0
        self.reused_boundaries=0;self.reused_certificates=0;self.passes_completed=0
        self.initial_entries=0;self.refinement_entries=0;self.geometry_attempts=0
        self.authority="";self.weights=None

    def _signature_step(self,s):
        return _proof_signature((s.id,s.parent_boundary_id,s.endpoint_boundary_id,s.trial_index,
                s.pass_index,s.bridge,tuple((getattr(s.tube,f.name).numerator,getattr(s.tube,f.name).denominator) if type(getattr(s.tube,f.name)) is Q else getattr(s.tube,f.name) for f in fields(s.tube))))

    def _signature_geometry(self,g):
        # Frozen record itself is not a history: snapshot every nested field.
        return _proof_signature((g.id,g.step_id,g.trial_index,g.pass_index,g.authority_digest,
                tuple(getattr(g.cell,f.name) for f in fields(g.cell))))

    def _validate_owned(self,b):
        if type(b) is not _OwnedBoundary:raise _Failure("FOREIGN_FULL_BOUNDARY")
        r=b.record
        if (type(b) is not _OwnedBoundary or type(r) is not ZonotopeBoundary
                or type(r.id) is not int or not 0<=r.id<len(self.owned)
                or self.owned[r.id] is not b or self.boundaries[r.id] is not r
                or self.actual_sets[r.id] is not b.z or self.boundary_signatures[r.id]!=b.signature
                or r.authority_digest!=self.authority or r.scale_exponents!=self.p.scale_exponents
                or _record_signature(r)!=b.signature[0]
                or _set_signature(b.z)!=b.signature[1]
                or b.z.time!=r.set.time or b.z.births!=r.set.births
                or tuple(x.as_tuple() for x in b.z.center)!=tuple(x.as_tuple() for x in r.set.center)
                or tuple(tuple(x.as_tuple() for x in c) for c in b.z.generators)!=tuple(tuple(x.as_tuple() for x in c) for c in r.set.generators)):
            raise _Failure("FOREIGN_DUPLICATE_OR_MUTATED_FULL_BOUNDARY")
        for x in (*b.z.center,*(v for c in b.z.generators for v in c)):
            if type(x) is not _z._D or x._ar is not self.ar:
                raise _Failure("FOREIGN_ARITHMETIC_OWNERSHIP")
        if r.parent_step_id is None:
            if r.id!=0 or b.z.time!=self.anchor or b.z.generators:
                raise _Failure("INVALID_ORIGINAL_ROOT")
        else:
            sid=r.parent_step_id
            if type(sid) is not int or not 0<=sid<len(self.steps):
                raise _Failure("INVALID_PARENT_STEP")
            s=self.steps[sid]
            if (self._signature_step(s)!=self.step_signatures[sid] or s.id!=sid
                    or s.endpoint_boundary_id!=r.id or not 0<=s.parent_boundary_id<r.id
                    or s.tube.source_end_seconds!=b.z.time
                    or self.owned[s.parent_boundary_id].z.time!=s.tube.source_start_seconds):
                raise _Failure("INVALID_FULL_BOUNDARY_ANCESTRY")
        return b

    def _seed(self,b):
        # Debit before examining supplied private test seams, even foreign ones.
        self.ar.reserve(_SET_SCAN,"local seed identity admission")
        if type(b) is not _OwnedBoundary or type(b.record.id) is not int or not 0<=b.record.id<len(self.owned):
            raise _Failure("FOREIGN_FULL_BOUNDARY")
        self.ar.reserve(_SET_SCAN*(b.record.id+1),"bounded anchor ancestry scan")
        current=b
        for _ in range(b.record.id+1):
            self._validate_owned(current)
            if current.record.parent_step_id is None:return b
            current=self.owned[self.steps[current.record.parent_step_id].parent_boundary_id]
        raise _Failure("ANCESTRY_DID_NOT_REACH_ORIGINAL_ANCHOR")

    def _boundary(self,z,parent):
        # Allocation/signatures/final scan prepaid by the pass reservation.
        plain=_z._plain_set(z,self.ar)
        d=_s.J2ZonotopeSegmentDiagnostic(plain.center,plain.generators,plain.births,plain.time)
        r=ZonotopeBoundary(len(self.boundaries),parent,d,self.p.scale_exponents,self.authority)
        owned=_OwnedBoundary(r,z,(_record_signature(r),_set_signature(z)))
        self.boundaries.append(r);self.owned.append(owned)
        self.boundary_signatures.append(owned.signature);self.actual_sets.append(z)
        return owned

    def _ledger(self):
        # Each pass prepays one complete audit and final publication audit.
        if len(self.boundaries)!=len(self.owned) or len(self.owned)!=len(self.boundary_signatures) or len(self.owned)!=len(self.actual_sets) or len(self.steps)!=len(self.step_signatures) or len(self.geometry)!=len(self.geometry_signatures):
            raise _Failure("LEDGER_LENGTH_MISMATCH")
        for i,b in enumerate(self.owned):
            if b.record.id!=i:self._invalid("BOUNDARY_ID_MISMATCH")
            self._validate_owned(b)
        for i,g in enumerate(self.geometry):
            if (g.id!=i or g.authority_digest!=self.authority
                    or self._signature_geometry(g)!=self.geometry_signatures[i]
                    or not 0<=g.step_id<len(self.steps)):
                raise _Failure("MUTATED_GEOMETRY_LINEAGE")
            s=self.steps[g.step_id]
            if not s.tube.start_seconds<=g.cell.start_seconds<g.cell.end_seconds<=s.tube.end_seconds:
                raise _Failure("GEOMETRY_OUTSIDE_WHOLE_TUBE")

    def _invalid(self,reason):
        raise _Failure(reason)

    def _common(self,a,b):
        ga,gb=self.geometry[a.geometry_record_id],self.geometry[b.geometry_record_id]
        if ga.authority_digest!=self.authority or gb.authority_digest!=self.authority:
            raise _Failure("INCOMPATIBLE_COMMON_AUTHORITY")
        _w._check_common_boxes(ga.cell,gb.cell)
        va=self.steps[ga.step_id].tube.velocity_bounds_m_per_s
        vb=self.steps[gb.step_id].tube.velocity_bounds_m_per_s
        if any(max(Q(x[0]),Q(y[0]))>min(Q(x[1]),Q(y[1])) for x,y in zip(va,vb)):
            raise _Failure("INCONSISTENT_COMMON_VELOCITY_BOUNDS")
        if a.assessment!="UNRESOLVED" and b.assessment!="UNRESOLVED" and a.assessment!=b.assessment:
            raise _Failure("CONTRADICTORY_CLOSED_CERTIFICATES")

    def _piece(self,p):
        if (type(p) is not LocalPiece or type(p.geometry_record_id) is not int
                or not 0<=p.geometry_record_id<len(self.geometry)):
            raise _Failure("INVALID_PIECE_REFERENCE")
        for t in (p.start_seconds,p.end_seconds):_s._time(t)
        if p.endpoint_convention!="LEFT_CLOSED_RIGHT_OPEN_FINAL_END_INCLUDED":raise _Failure("INVALID_ENDPOINT_CONVENTION")
        g=self.geometry[p.geometry_record_id]
        if (p.assessment!=g.cell.assessment or p.reason!=g.cell.reason
                or not g.cell.start_seconds<=p.start_seconds<p.end_seconds<=g.cell.end_seconds):
            raise _Failure("PIECE_CERTIFICATE_MISMATCH")
        return p

    def _partition(self,pieces):
        if (not pieces or pieces[0].start_seconds!=self.anchor or pieces[-1].end_seconds!=self.end
                or any(a.end_seconds!=b.start_seconds for a,b in zip(pieces,pieces[1:]))):
            raise _Failure("INCOMPLETE_CLOSED_SUPPORTED_PARTITION")
        for p in pieces:self._piece(p)
        for a,b in zip(pieces,pieces[1:]):self._common(a,b)
        return tuple(pieces)

    def _overlay(self,new,tasks):
        if not self.pieces:return self._partition(new)
        # Validate finite disjoint selected coverage BEFORE the overlap sweep.
        j=0
        for _,a,b in tasks:
            cursor=a
            while j<len(new) and new[j].start_seconds<b:
                p=self._piece(new[j])
                if p.start_seconds!=cursor or p.end_seconds>b:
                    raise _Failure("MALFORMED_SELECTED_CLOSED_PARTITION")
                cursor=p.end_seconds;j+=1
            if cursor!=b:raise _Failure("INCOMPLETE_SELECTED_CLOSED_PARTITION")
        if j!=len(new):raise _Failure("EXTRA_SELECTED_CERTIFICATE")
        j=0
        for p in new:
            while j<len(self.pieces) and self.pieces[j].end_seconds<p.start_seconds:j+=1
            k=j
            while k<len(self.pieces) and self.pieces[k].start_seconds<=p.end_seconds:
                self._common(self.pieces[k],p);k+=1
        kept=[];j=0
        for p in self.pieces:
            while j<len(tasks) and tasks[j][2]<=p.start_seconds:j+=1
            replaced=j<len(tasks) and tasks[j][1]<p.end_seconds
            if replaced:
                if p.assessment!="UNRESOLVED":raise _Failure("REFINEMENT_SELECTED_CERTIFIED_SUPPORT")
            else:kept.append(p)
        self.reused_certificates+=sum(p.assessment!="UNRESOLVED" for p in kept)
        return self._partition(sorted(kept+new,key=lambda p:p.start_seconds))

    def _tasks(self):
        tasks=[];i=0
        while i<len(self.pieces):
            p=self.pieces[i]
            if p.assessment!="UNRESOLVED":i+=1;continue
            a=p.start_seconds;g=self.geometry[p.geometry_record_id]
            seed=self.owned[self.steps[g.step_id].parent_boundary_id]
            b=p.end_seconds;i+=1
            while i<len(self.pieces) and self.pieces[i].assessment=="UNRESOLVED":
                b=self.pieces[i].end_seconds;i+=1
            tasks.append((seed,a,b))
        return tuple(tasks)

    def _ends(self,a,b,h):
        full,tail=divmod(b-a,h)
        if full+bool(tail)>4096:raise _Failure("PER_TRIAL_STEP_CEILING")
        return tuple(a+k*h for k in range(1,int(full)+1))+((b,) if tail else ())

    def _plans(self,tasks,h):
        plans=[]
        for seed,a,b in tasks:
            ends=self._ends(seed.z.time,a,h)+self._ends(a,b,h)
            if len(ends)>self.p.base_policy.max_steps:raise _Failure("PER_TRIAL_STEP_CEILING")
            times=(seed.z.time,)+ends;geometry=[]
            for j,(lo,hi) in enumerate(zip(times,times[1:])):
                lo,hi=max(lo,a),min(hi,b)
                if lo>=hi:continue
                cuts=(lo,)+tuple(k for k in self.knots if lo<k<hi)+(hi,)
                geometry.extend((x,y,j,bisect_right(self.knots,x)-1) for x,y in zip(cuts,cuts[1:]))
            plans.append((seed,a,b,ends,tuple(geometry)))
        return tuple(plans)

    def _pass(self,index,h,tasks):
        # Finite planning control admitted before list/grid/subdivision work.
        control=8192+4096*(self.q.policy.max_initial_steps if index==0 else min(4096*self.q.policy.max_trials,self.q.policy.max_refinement_steps))+4096*len(self.knots)
        if control>self.ar.limit-self.ar.operations:return "SCALAR_PLANNING_RESERVATION"
        self.ar.reserve(control,"local bounded prospective exact-grid planning")
        if index and len(self.trials)-1+len(tasks)>self.q.policy.max_trials:return "TRIAL_BUDGET"
        # Exact counts before allocating a prospective grid. A rejected local
        # plan cannot allocate an oversized step/evidence graph.
        counts=[]
        for seed,a,b in tasks:
            self._seed(seed)
            if not self.anchor<=seed.z.time<=a<b<=self.end:
                raise _Failure("INVALID_ANCHORWARD_SELECTED_SUPPORT")
            count=0
            for lo,hi in ((seed.z.time,a),(a,b)):
                full,tail=divmod(hi-lo,h);count+=full+bool(tail)
            if count>self.p.base_policy.max_steps:return "PER_TRIAL_STEP_CEILING"
            counts.append(count)
        prospective=sum(counts)
        if index and self.refinement_steps+prospective>self.q.policy.max_refinement_steps:return "REFINEMENT_STEP_BUDGET"
        if self.initial_steps+self.refinement_steps+prospective>MAX_TOTAL_STEPS:return "GENERATOR_BIRTH_BUDGET"
        if self.planned_picard+prospective*self.p.base_policy.max_picard_iterations>self.q.policy.max_picard_attempts:return "PICARD_BUDGET"
        try:plans=self._plans(tasks,h)
        except _Failure as e:
            if str(e)=="PER_TRIAL_STEP_CEILING":return str(e)
            raise
        n=sum(len(p[3]) for p in plans);g=sum(len(p[4]) for p in plans)
        steps=self.initial_steps+self.refinement_steps
        units=96*n+64*g+8*len(plans)+16
        checks=((index==0 and n>self.q.policy.max_initial_steps,"INITIAL_STEP_BUDGET"),
                (index>0 and self.refinement_steps+n>self.q.policy.max_refinement_steps,"REFINEMENT_STEP_BUDGET"),
                (index>0 and len(self.trials)-1+len(plans)>self.q.policy.max_trials,"TRIAL_BUDGET"),
                (steps+n>MAX_TOTAL_STEPS,"GENERATOR_BIRTH_BUDGET"),
                (self.planned_picard+n*self.p.base_policy.max_picard_iterations>self.q.policy.max_picard_attempts,"PICARD_BUDGET"),
                (self.planned_geometry+g>self.q.policy.max_geometry_cells,"GEOMETRY_CELL_BUDGET"),
                (self.evidence_reserved+units>self.q.policy.max_retained_evidence_units,"EVIDENCE_BUDGET"))
        for rejected,reason in checks:
            if rejected:return reason
        # Covers bounded lineage snapshots, final audit, closed overlay pair scans,
        # input-to-rational conversion and publication. Ray leaves are separate.
        pair_bound=(len(self.pieces)+g)*4+2
        reserve=(_STEP_CONTROL*n+2*_SET_SCAN*(len(self.owned)+1)+
                 _PIECE_CONTROL*(len(self.pieces)+g)+_TERMINAL_CONTROL)
        geometry_control=_GEOMETRY_CONTROL*(g+pair_bound+1)
        if reserve>self.ar.limit-self.ar.operations:return "SCALAR_CONTROL_RESERVATION"
        if geometry_control+512*(g+1)>self.ga.maximum-self.ga.total_operations:return "GEOMETRY_OPERATION_BUDGET"
        self.ar.reserve(reserve,"local evidence/lineage/terminal control schedule")
        self.ga.reserve(geometry_control)
        self.evidence_reserved+=units;self.planned_picard+=n*self.p.base_policy.max_picard_iterations;self.planned_geometry+=g
        if self.weights is None:self.weights=_g._shape_weights(self.q.table.frame.ellipsoid,self.ga)
        pending=[]
        for seed,a,b,ends,geom in plans:
            trial_index=len(self.trials);step_ids=[];geometry_ids=[]
            trial=LocalTrial(trial_index,index,seed.record.id,a,b,h,len(ends),len(geom),"failed",(),())
            self.trials.append(trial)
            parent=self._seed(seed)
            if index:self.reused_boundaries+=1
            for j,end in enumerate(ends):
                dt=_z._radd(end,_z._rmul(Q(-1),parent.z.time,self.ar),self.ar)
                if not 0<dt<=h:raise _Failure("INVALID_EXACT_LOCAL_DURATION")
                hid=self.ar.div(self.ar.point(dt.numerator),self.ar.point(dt.denominator))
                sid=len(self.steps)
                if index:self.refinement_entries+=1
                else:self.initial_entries+=1
                z,tube=_transport(parent.z,hid,self.q.segment.trajectory.gravity_model,self.p,self.ar,sid,end)
                whole=_s._publish_cell(tube,parent.z.time,end,j,self.ar)
                child=self._boundary(z,sid)
                s=LocalStep(sid,parent.record.id,child.record.id,trial_index,index,end<=a,whole)
                self.steps.append(s);self.step_signatures.append(self._signature_step(s));step_ids.append(sid)
                parent=child
                if index:self.refinement_steps+=1
                else:self.initial_steps+=1
            for start,end,j,k in geom:
                s=self.steps[step_ids[j]]
                tube=_b34._PositionTube(tuple(tuple(_b34._fraction_endpoint(v) for v in pair) for pair in s.tube.position_bounds_m))
                self.geometry_attempts+=1
                cell=_geometry_cell(self.q.table,tube,s.tube.source_step_index,k,start,end,self.weights,self.ga)
                if (type(cell) is not _g.IntervalIlluminationCell or cell.start_seconds!=start or cell.end_seconds!=end
                        or cell.j2_cell_index!=s.tube.source_step_index or cell.sun_segment_index!=k
                        or cell.position_bounds_m!=tube.position_bounds_m or cell.scope!=_g.ASSESSMENT_SCOPE
                        or cell.assessment not in ("ILLUMINATED","OCCULTED","UNRESOLVED")):
                    raise _Failure("INVALID_DERIVED_GEOMETRY")
                gid=len(self.geometry);r=LocalGeometry(gid,s.id,trial_index,index,self.authority,cell)
                self.geometry.append(r);self.geometry_signatures.append(self._signature_geometry(r));geometry_ids.append(gid)
                pending.append(LocalPiece(start,end,gid,cell.assessment,cell.reason))
            self.trials[trial_index]=LocalTrial(trial_index,index,seed.record.id,a,b,h,len(ends),len(geom),"complete",tuple(step_ids),tuple(geometry_ids))
        if self.ar.picard_attempts>self.planned_picard or self.ar.completed_steps>steps+n or self.ar.attempted_steps>steps+n:
            raise _Failure("ACTUAL_WORK_EXCEEDED_RESERVATION")
        self._ledger()
        pieces=self._overlay(sorted(pending,key=lambda p:p.start_seconds),tasks)
        self.pieces=pieces;self.passes_completed=index
        if index==0:self.initial_pieces=pieces
        return None

    def run(self):
        self.ar.reserve(_TERMINAL_CONTROL+2*_SET_SCAN,"local session/root/failure retention")
        _z._reserve_authority_metadata(self.q.segment.trajectory,self.ar)
        # Strict normalized input identity; structural admission is separate from
        # proof work, just as B34. Prepay bounded canonical metadata scans.
        def cost(v):
            if type(v) is str:return 32+16*len(v)
            if type(v) in (tuple,list):return 64+sum(cost(x) for x in v)
            if type(v) is dict:return 64+sum(cost(k)+cost(x) for k,x in v.items())
            if hasattr(type(v),'__dataclass_fields__'):return 64+sum(cost(getattr(v,f.name)) for f in fields(v))
            return 512
        self.ar.reserve(cost(self.q)*4,"local input identity/canonical ownership scan")
        from .orbit_sun_zonotope_local_document import _input_map
        self.authority=sha256(json_text(canonical_content(_input_map(self.q))).encode('utf-8')).hexdigest()
        self.ar.reserve(512,"initial exact count/horizon admission")
        count,tail=divmod(self.end-self.anchor,Q(self.p.base_policy.step_seconds))
        count+=bool(tail)
        if self.end-self.anchor>86400 or count>self.p.base_policy.max_steps:return "budget_exhausted","SOURCE_HORIZON_OR_STEP_BUDGET"
        if count>self.q.policy.max_initial_steps:return "budget_exhausted","INITIAL_STEP_BUDGET"
        if self.q.policy.max_retained_evidence_units<96:return "budget_exhausted","ROOT_EVIDENCE_BUDGET"
        self.evidence_reserved=96
        values=(*self.q.segment.trajectory.initial_state.position.components_m,
                *self.q.segment.trajectory.initial_state.velocity.components_m_per_s,
                self.q.segment.trajectory.gravity_model.gravitational_parameter_m3_s2.value,
                self.q.segment.trajectory.gravity_model.j2.value,
                self.q.segment.trajectory.gravity_model.reference_radius_m.value,
                self.p.base_policy.step_seconds)
        self.ar.charge(40)
        if any(v!=0 and not 1e-100<=abs(v)<=1e100 for v in values):raise _Failure("DYNAMICAL_ARITHMETIC_ENVELOPE")
        z=_z._initial_set(values[:6],self.p.scale_exponents,self.ar,self.anchor)
        self.ar.reserve(128,"initial domain legacy control")
        _z._old._domain(_z._project_box(z,self.p.scale_exponents,self.ar),self.p.base_policy,self.ar)
        root=self._boundary(z,None)
        h=Q(self.p.base_policy.step_seconds)
        for index in range(self.q.policy.max_passes+1):
            tasks=((root,self.anchor,self.end),) if index==0 else self._tasks()
            reason=self._pass(index,h,tasks)
            if reason:return "budget_exhausted",reason
            width=_width(self.pieces)
            if width==0:return "classified","ALL_SPANS_CLASSIFIED"
            if width<=Q(self.q.requested_resolution_seconds):return "resolution_reached","CONNECTED_WIDTH_CRITERION_NO_EVENT_ACCURACY_CLAIM"
            if index==self.q.policy.max_passes:return "budget_exhausted","GLOBAL_PASS_COUNT_EXHAUSTED"
            if len(self.trials)-1>=self.q.policy.max_trials:return "budget_exhausted","TRIAL_BUDGET"
            self.ar.reserve(_PIECE_CONTROL*len(self.pieces)+64,"local connected-support scan and exact halving")
            h=_z._rmul(h,Q(1,2),self.ar)
        raise _Failure("UNREACHABLE_PASS_CONTROL")


@dataclass(frozen=True, slots=True)
class ZonotopeLocalIlluminationResult:
    request: ZonotopeLocalIlluminationRequest
    status: str = field(init=False,default="computational_failure")
    reason: str | None = field(init=False,default=None)
    coverage_complete: bool = field(init=False,default=False)
    pieces: tuple | None = field(init=False,default=None)
    windows: tuple | None = field(init=False,default=None)
    initial_pieces: tuple | None = field(init=False,default=None)
    boundaries: tuple = field(init=False,default=())
    steps: tuple = field(init=False,default=())
    geometry_records: tuple = field(init=False,default=())
    trials: tuple = field(init=False,default=())
    authority_digest: str = field(init=False,default="")
    max_unresolved_width_seconds: Q | None = field(init=False,default=None)
    attempted_steps: int = field(init=False,default=0)
    completed_steps: int = field(init=False,default=0)
    initial_attempted_steps: int = field(init=False,default=0)
    refinement_attempted_steps: int = field(init=False,default=0)
    initial_completed_steps: int = field(init=False,default=0)
    refinement_completed_steps: int = field(init=False,default=0)
    picard_attempts: int = field(init=False,default=0)
    reductions: int = field(init=False,default=0)
    charged_leaf_operations: int = field(init=False,default=0)
    reserved_control_operations: int = field(init=False,default=0)
    scalar_operations: int = field(init=False,default=0)
    scalar_budget_rejected: bool = field(init=False,default=False)
    geometry_cells_attempted: int = field(init=False,default=0)
    geometry_cells_evaluated: int = field(init=False,default=0)
    geometry_leaf_operations: int = field(init=False,default=0)
    geometry_control_operations: int = field(init=False,default=0)
    geometry_operations: int = field(init=False,default=0)
    reserved_picard_attempts: int = field(init=False,default=0)
    reserved_geometry_cells: int = field(init=False,default=0)
    reserved_evidence_units: int = field(init=False,default=0)
    retained_evidence_units: int = field(init=False,default=0)
    reused_boundaries: int = field(init=False,default=0)
    reused_certificates: int = field(init=False,default=0)
    api_id: str = field(init=False,default=API_ID)
    api_version: int = field(init=False,default=1)
    resource_policy_version: int = field(init=False,default=RESOURCE_VERSION)
    transport_resource_policy_version: int = field(init=False,default=3)
    combined_qualification: str = field(init=False,default="UNRESOLVED")
    combined_reasons: tuple = field(init=False,default=_g.COMBINED_REASONS)

    __hash__ = None

    def __post_init__(self):
        q=_request(self.request);object.__setattr__(self,"request",q);s=_Session(q)
        try:
            status,reason=s.run()
            if s.pieces:
                s._ledger();s._partition(s.pieces)
                windows=_merge(s.pieces)
                units=(96*len(s.steps)+96+64*len(s.geometry)+8*len(s.trials)+16)
                if units>s.evidence_reserved:raise _Failure("FINAL_EVIDENCE_RESERVATION_MISMATCH")
                values=dict(pieces=s.pieces,windows=windows,initial_pieces=s.initial_pieces,
                    coverage_complete=True,max_unresolved_width_seconds=_width(s.pieces),retained_evidence_units=units)
                for n,v in values.items():object.__setattr__(self,n,v)
            object.__setattr__(self,"status",status);object.__setattr__(self,"reason",reason)
        except Exception as e:
            # Diagnostic ledger retention cannot become coverage after any failure.
            object.__setattr__(self,"reason",type(e).__name__+": "+str(e))
        finally:
            for n,v in dict(boundaries=tuple(s.boundaries),steps=tuple(s.steps),
                    geometry_records=tuple(s.geometry),trials=tuple(s.trials),authority_digest=s.authority,
                    attempted_steps=s.ar.attempted_steps,completed_steps=s.ar.completed_steps,
                    initial_attempted_steps=s.initial_entries,refinement_attempted_steps=s.refinement_entries,
                    initial_completed_steps=s.initial_steps,refinement_completed_steps=s.refinement_steps,
                    picard_attempts=s.ar.picard_attempts,reductions=s.ar.reductions,
                    charged_leaf_operations=s.ar.leaf_operations,reserved_control_operations=s.ar.reserved_units,
                    scalar_operations=s.ar.operations,scalar_budget_rejected=s.ar.rejected,
                    geometry_cells_attempted=s.geometry_attempts,geometry_cells_evaluated=len(s.geometry),geometry_leaf_operations=s.ga.operations,
                    geometry_control_operations=s.ga.control_units,geometry_operations=s.ga.total_operations,
                    reserved_picard_attempts=s.planned_picard,reserved_geometry_cells=s.planned_geometry,
                    reserved_evidence_units=s.evidence_reserved,
                    retained_evidence_units=(96*bool(s.boundaries)+96*len(s.steps)+64*len(s.geometry)+8*len(s.trials)+16*bool(s.trials)),
                    reused_boundaries=s.reused_boundaries,
                    reused_certificates=s.reused_certificates).items():object.__setattr__(self,n,v)


def evaluate_zonotope_local_illumination(request):
    return ZonotopeLocalIlluminationResult(request)


__all__=["ZonotopeLocalIlluminationPolicy","ZonotopeLocalIlluminationRequest",
         "ZonotopeLocalIlluminationResult","ZonotopeBoundary","LocalStep","LocalGeometry",
         "LocalPiece","LocalWindow","LocalTrial","evaluate_zonotope_local_illumination"]
