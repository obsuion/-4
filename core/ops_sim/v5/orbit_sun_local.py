"""Evaluation-local, proof-preserving refinement of conditional illumination.

Only original inputs are authority. All boundary boxes are computed here by the
unchanged F3 kernel, with their full accumulated uncertainty and ancestry.
"""
from bisect import bisect_right
from dataclasses import dataclass, field, fields, is_dataclass, replace
from decimal import Decimal, DecimalException
from fractions import Fraction as Q

from .orbit_config import _exact
from .orbit_j2_binding import J2CoastOrbitInputs
from .sun_table import SunPositionTable
from . import orbit_j2_enclosure as _f3
from . import orbit_j2_segments as _b2
from . import orbit_sun_intervals as _b3
from . import orbit_sun_windows as _b4


LIMITS = {
    "max_passes": 16, "max_integration_steps": 65536,
    "max_picard_attempts": 1048576, "max_geometry_cells": 65536,
    "max_retained_evidence_units": 393216, "max_arithmetic_operations": 33562624,
}


@dataclass(frozen=True, slots=True)
class LocalIlluminationPolicy:
    max_passes: int
    max_integration_steps: int
    max_picard_attempts: int
    max_geometry_cells: int
    max_retained_evidence_units: int
    max_arithmetic_operations: int

    def __post_init__(self):
        for name, upper in LIMITS.items():
            value = getattr(self, name)
            _exact(value, int, name)
            if not 1 <= value <= upper:
                raise ValueError(name+" outside local policy domain")


@dataclass(frozen=True, slots=True)
class LocalIlluminationRequest:
    coast: J2CoastOrbitInputs
    table: SunPositionTable
    start: _b3.GeometryInstant
    end: _b3.GeometryInstant
    requested_resolution_seconds: float
    policy: LocalIlluminationPolicy

    __hash__ = None

    def __post_init__(self):
        _exact(self.policy, LocalIlluminationPolicy, "policy")
        policy = LocalIlluminationPolicy(**{name: getattr(self.policy, name) for name in LIMITS})
        # Reuse accepted complete input and strict resolution admission only.
        base = _b4.IlluminationWindowRequest(self.coast, self.table, self.start, self.end,
            self.requested_resolution_seconds, _b4.IlluminationSearchPolicy(
                policy.max_passes, policy.max_integration_steps, policy.max_geometry_cells,
                policy.max_retained_evidence_units, policy.max_arithmetic_operations))
        for name in ("coast", "table", "start", "end", "requested_resolution_seconds"):
            object.__setattr__(self, name, getattr(base, name))
        object.__setattr__(self, "policy", policy)


def _request(value):
    _exact(value, LocalIlluminationRequest, "request")
    return LocalIlluminationRequest(value.coast, value.table, value.start, value.end,
                                    value.requested_resolution_seconds, value.policy)


class _LocalFailure(Exception):
    pass


@dataclass(frozen=True, slots=True)
class BoundaryRecord:
    id: int
    elapsed_seconds: Q
    state_bounds: tuple
    parent_step_id: int | None
    direction: int
    common_authority_digest: str


@dataclass(frozen=True, slots=True)
class StepRecord:
    id: int
    parent_boundary_id: int
    endpoint_boundary_id: int
    pass_index: int
    enclosure_policy: _f3.J2EnclosurePolicy
    tube: _b2.J2SegmentCell


@dataclass(frozen=True, slots=True)
class GeometryRecord:
    id: int
    pass_index: int
    step_id: int
    cell: _b3.IntervalIlluminationCell
    common_authority_digest: str


@dataclass(frozen=True, slots=True)
class LocalSupport:
    start_seconds: Q
    end_seconds: Q
    geometry_record_id: int


@dataclass(frozen=True, slots=True)
class LocalWindow:
    start_seconds: Q
    end_seconds: Q
    assessment: str
    reasons: tuple[str, ...]
    supports: tuple[LocalSupport, ...]
    endpoint_convention: str = field(init=False, default="LEFT_CLOSED_RIGHT_OPEN_FINAL_END_INCLUDED")


@dataclass(frozen=True, slots=True)
class LocalPass:
    index: int
    step_seconds: Q
    status: str
    reason: str | None
    planned_integration_steps: int
    planned_geometry_cells: int | None
    reserved_integration_steps: int
    reserved_picard_attempts: int
    reserved_geometry_cells: int
    reserved_arithmetic_operations: int
    reserved_evidence_units: int
    attempted_integration_steps: int
    completed_integration_steps: int
    picard_attempts: int
    geometry_cells_attempted: int
    geometry_cells_evaluated: int
    arithmetic_operations: int
    geometry_record_ids: tuple[int, ...]
    reused_boundary_records: int
    reused_certificate_pieces: int


@dataclass(frozen=True, slots=True)
class _Task:
    seed_id: int
    seed_time: Q
    start: Q
    end: Q
    direction: int
    initial: bool


def _signature(record):
    # Snapshot values; a nested frozen dataclass is not its own history.
    def freeze(value):
        if type(value) in (str, int, bool, type(None)):
            return (type(value),value)
        if type(value) is float:
            return (float,value.hex())
        if type(value) is Q:
            return (Q,value.numerator,value.denominator)
        if type(value) is Decimal:
            return (Decimal,value.as_tuple())
        if is_dataclass(value):
            return (type(value),tuple((f.name,freeze(getattr(value,f.name))) for f in fields(value)))
        if type(value) is tuple:
            return (tuple,tuple(freeze(v) for v in value))
        raise _LocalFailure("UNSUPPORTED_PROOF_LEDGER_VALUE_TYPE")
    return freeze(record)


def _time(x):
    return _b4._time(x)


def _ceil_steps(span, h):
    n, tail = divmod(abs(_time(span)), h)
    return n+bool(tail)


def _ends(start, end, h):
    span = _time(end-start)
    full, tail = divmod(abs(span), h)
    sign = 1 if span > 0 else -1
    return tuple(_time(start+sign*k*h) for k in range(1, full+1)) + ((end,) if tail else ())


def _merge(pieces):
    result = []
    group = []
    for p in pieces:
        if group and (group[0].assessment,group[0].reasons) != (p.assessment,p.reasons):
            result.append(LocalWindow(group[0].start_seconds,group[-1].end_seconds,
                group[0].assessment,group[0].reasons,tuple(s for x in group for s in x.supports)))
            group = []
        group.append(p)
    if group:
        result.append(LocalWindow(group[0].start_seconds,group[-1].end_seconds,
            group[0].assessment,group[0].reasons,tuple(s for x in group for s in x.supports)))
    return tuple(result)


class _Session:
    """Private fresh proof ledger. No supplied/cache/result graph is accepted."""
    def __init__(self, request):
        self.q = request
        base = _b3.IntervalIlluminationRequest(request.coast, request.table, request.start,
                                              request.end, _b3.IntervalIlluminationPolicy(5118))
        self.authority = _b4._physical_digest(base)
        self.anchor = _time(Q(request.coast.trajectory.initial_state.position.instant.elapsed_seconds))
        self.boundaries, self.steps, self.geometry_records, self.passes = [], [], [], []
        self._boundary_signatures, self._step_signatures, self._geometry_signatures = [], [], []
        self.pieces = ()
        self.counts = {name: 0 for name in (
            "planned_integration_steps_considered", "reserved_integration_steps", "attempted_integration_steps",
            "completed_integration_steps", "reserved_picard_attempts", "picard_attempts",
            "planned_geometry_cells_considered", "reserved_geometry_cells", "geometry_cells_attempted",
            "geometry_cells_evaluated", "reserved_arithmetic_operations", "arithmetic_operations",
            "reserved_evidence_units", "reused_boundary_records", "reused_certificate_pieces")}
        self.actual_work_accounting_complete = True
        self.ar = _f3._Arithmetic(request.coast.enclosure_policy.precision_digits)
        self._knots = tuple(Q(s.elapsed_seconds) for s in request.table.samples)

    def _seed(self, boundary):
        # Identity and full ledger signatures, not matching content digest.
        if (type(boundary) is not BoundaryRecord or type(boundary.id) is not int
                or not 0 <= boundary.id < len(self.boundaries)
                or self.boundaries[boundary.id] is not boundary
                or _signature(boundary) != self._boundary_signatures[boundary.id]
                or boundary.common_authority_digest != self.authority):
            raise _LocalFailure("FOREIGN_STALE_OR_FORGED_BOUNDARY_SEED")
        if boundary.parent_step_id is not None:
            parent = self.steps[boundary.parent_step_id]
            if (_signature(parent) != self._step_signatures[parent.id]
                    or parent.endpoint_boundary_id != boundary.id
                    or parent.tube.source_final_seconds != boundary.elapsed_seconds):
                raise _LocalFailure("INVALID_BOUNDARY_ANCESTRY")
        return boundary

    def _ledger(self):
        for records, signatures in ((self.boundaries,self._boundary_signatures),
                (self.steps,self._step_signatures),(self.geometry_records,self._geometry_signatures)):
            if len(records) != len(signatures) or any(r.id != i for i,r in enumerate(records)):
                raise _LocalFailure("INVALID_LEDGER_LENGTH_OR_RECORD_IDS")
        for r, signature in zip(self.boundaries, self._boundary_signatures):
            if _signature(r) != signature:
                raise _LocalFailure("MUTATED_BOUNDARY_LEDGER")
        for r, signature in zip(self.steps, self._step_signatures):
            if _signature(r) != signature:
                raise _LocalFailure("MUTATED_STEP_LEDGER")
        for r, signature in zip(self.geometry_records, self._geometry_signatures):
            if _signature(r) != signature or r.common_authority_digest != self.authority:
                raise _LocalFailure("MUTATED_OR_FOREIGN_GEOMETRY_LEDGER")

    def _units(self, pieces=(), windows=()):
        # Fixed-schema records, registry/signature references and coverage/support
        # records. Not bytes, physical uncertainty or wall-time measurement.
        return (4*len(self.boundaries)+4*len(self.steps)+2*len(self.geometry_records)
                +4*len(pieces)+len(windows)+sum(len(w.supports) for w in windows))

    def _storage(self):
        if self._units(self.pieces) > self.counts["reserved_evidence_units"]:
            raise _LocalFailure("RETAINED_LEDGER_EXCEEDED_RESERVATION")

    def _root(self):
        initial = _b2._initial_box(self.q.coast, self.ar)
        r = BoundaryRecord(0, self.anchor, tuple((x.lo, x.hi) for x in initial), None, 0, self.authority)
        self.boundaries.append(r); self._boundary_signatures.append(_signature(r))
        self._storage()

    def _choose_seed(self, piece, direction):
        geometry = self.geometry_records[piece.supports[0].geometry_record_id]
        step = self.steps[geometry.step_id]
        if (step.tube.source_final_seconds > step.tube.source_initial_seconds) != (direction > 0):
            raise _LocalFailure("SEED_DIRECTION_DOES_NOT_MATCH_ORIGINAL_BRANCH")
        return self.boundaries[step.parent_boundary_id]

    def _initial_tasks(self):
        segment = _b2.J2SegmentRequest(self.q.coast, self.q.start, self.q.end)
        anchor, start, end, h, legs, count = _b2._plan(segment)
        if any(abs(d) > 86400 for d, _, _ in legs):
            raise _LocalFailure("ORIGINAL_ANCHOR_HORIZON_EXCEEDED")
        tasks = []
        for d, _, _ in legs:
            sign = 1 if d > 0 else -1
            a, b = (max(anchor, start), end) if sign > 0 else (start, min(anchor, end))
            tasks.append(_Task(0, anchor, _time(a), _time(b), sign, True))
        return tuple(tasks)

    def _local_tasks(self):
        components = []
        first = None
        for p in self.pieces:
            if p.assessment == "UNRESOLVED":
                if first is None: first = p.start_seconds
                last = p.end_seconds
            elif first is not None:
                components.append((first, last)); first = None
        if first is not None: components.append((first, last))
        tasks = []
        j = 0
        for a, b in components:
            spans = ((a, self.anchor), (self.anchor, b)) if a < self.anchor < b else ((a, b),)
            for lo, hi in spans:
                direction = -1 if hi <= self.anchor else 1
                edge = lo if direction > 0 else hi
                while j+1 < len(self.pieces) and self.pieces[j].end_seconds <= lo:
                    j += 1
                k = j
                if direction < 0:
                    while k+1 < len(self.pieces) and self.pieces[k].end_seconds < hi:
                        k += 1
                seed = self._seed(self._choose_seed(self.pieces[k], direction))
                if (seed.direction not in (0, direction)
                        or direction*(edge-seed.elapsed_seconds) < 0):
                    raise _LocalFailure("SEED_IS_NOT_ANCHORWARD_OF_LOCAL_EDGE")
                tasks.append(_Task(seed.id, seed.elapsed_seconds, lo, hi, direction, False))
        return tuple(tasks)

    def _task_count(self, task, h):
        near, far = (task.start, task.end) if task.direction > 0 else (task.end, task.start)
        if task.initial:
            return _ceil_steps(far-task.seed_time, h)
        return _ceil_steps(near-task.seed_time, h)+_ceil_steps(far-near, h)

    def _plan(self, tasks, h):
        count = sum(self._task_count(t, h) for t in tasks)
        self.counts["planned_integration_steps_considered"] += count
        if count > self.q.coast.enclosure_policy.max_steps:
            return count, None, None, "PER_PASS_ENCLOSURE_STEP_BUDGET"
        if self.counts["reserved_integration_steps"]+count > self.q.policy.max_integration_steps:
            return count, None, None, "reserved_integration_steps"
        plans = []
        total_geometry = 0
        for task in tasks:
            near, far = (task.start, task.end) if task.direction > 0 else (task.end, task.start)
            ends = _ends(task.seed_time, far, h) if task.initial else (
                _ends(task.seed_time, near, h)+_ends(near, far, h))
            times = (task.seed_time,)+ends
            source = []
            for i, (a, b) in enumerate(zip(times, times[1:])):
                lo, hi = sorted((a, b)); lo, hi = max(lo, task.start), min(hi, task.end)
                if lo < hi:
                    source.append((lo, hi, i))
            source.sort()
            geometry = []
            for lo, hi, i in source:
                cuts = (lo,)+tuple(k for k in self._knots if lo < k < hi)+(hi,)
                for a, b in zip(cuts, cuts[1:]):
                    geometry.append((a, b, i, bisect_right(self._knots, a)-1))
            total_geometry += len(geometry)
            plans.append((task, ends, tuple(geometry)))
        self.counts["planned_geometry_cells_considered"] += total_geometry
        if total_geometry > _b3.MAX_GEOMETRY_CELLS:
            return count, total_geometry, None, "PER_PASS_GEOMETRY_CELL_BUDGET"
        return count, total_geometry, tuple(plans), None

    def _edge(self, parent, end, policy, index):
        parent = self._seed(parent)
        dt = _time(end-parent.elapsed_seconds)
        if not dt or abs(dt) > Q(policy.step_seconds):
            raise _LocalFailure("INVALID_LOCAL_SIGNED_STEP")
        direction = 1 if dt > 0 else -1
        if parent.direction not in (0, direction):
            raise _LocalFailure("LOCAL_STEP_REVERSED_ORIGINAL_BRANCH")
        box = [_f3._I(lo, hi) for lo, hi in parent.state_bounds]
        self.counts["attempted_integration_steps"] += 1
        endpoint, tube, _ = _b2._validated_step(box, dt, self.q.coast.trajectory.gravity_model, policy, self.ar)
        step_id, boundary_id = len(self.steps), len(self.boundaries)
        cell = _b2.J2SegmentCell(min(parent.elapsed_seconds, end), max(parent.elapsed_seconds, end),
            parent.elapsed_seconds, end, tuple((x.lo, x.hi) for x in tube[:3]),
            tuple((x.lo, x.hi) for x in tube[3:]))
        boundary = BoundaryRecord(boundary_id, end, tuple((x.lo, x.hi) for x in endpoint), step_id, direction, self.authority)
        step = StepRecord(step_id, parent.id, boundary_id, index, policy, cell)
        self.boundaries.append(boundary); self._boundary_signatures.append(_signature(boundary))
        self.steps.append(step); self._step_signatures.append(_signature(step))
        self.counts["completed_integration_steps"] += 1
        self._storage()
        return boundary, step_id

    def _common(self, prior, new):
        a = self.geometry_records[prior.supports[0].geometry_record_id]
        b = self.geometry_records[new.supports[0].geometry_record_id]
        if a.common_authority_digest != self.authority or b.common_authority_digest != self.authority:
            raise _LocalFailure("INCOMPATIBLE_COMMON_AUTHORITY")
        _b4._check_common_boxes(a.cell, b.cell)
        va, vb = self.steps[a.step_id].tube.velocity_bounds_m_per_s, self.steps[b.step_id].tube.velocity_bounds_m_per_s
        if any(max(Q(x[0]), Q(y[0])) > min(Q(x[1]), Q(y[1])) for x, y in zip(va, vb)):
            raise _LocalFailure("INCONSISTENT_COMMON_VELOCITY_ENCLOSURES")
        if _b4._certified(prior.assessment) and _b4._certified(new.assessment) and prior.assessment != new.assessment:
            raise _LocalFailure("CONTRADICTORY_CLOSED_CELL_CERTIFICATES")

    def _partition(self, pieces):
        if (not pieces or pieces[0].start_seconds != Q(self.q.start.elapsed_seconds)
                or pieces[-1].end_seconds != Q(self.q.end.elapsed_seconds)
                or any(a.end_seconds != b.start_seconds for a, b in zip(pieces, pieces[1:]))):
            raise _LocalFailure("INCOMPLETE_SUPPORTED_PARTITION")
        for a, b in zip(pieces, pieces[1:]):
            self._common(a, b)  # shared CLOSED endpoint counts as overlap
        return tuple(pieces)

    def _overlay(self, new, tasks):
        if not self.pieces:
            return self._partition(new)
        j = 0
        for p in new:
            while j < len(self.pieces) and self.pieces[j].end_seconds < p.start_seconds:
                j += 1
            k = j
            while k < len(self.pieces) and self.pieces[k].start_seconds <= p.end_seconds:
                self._common(self.pieces[k], p); k += 1
        kept = []
        task_index = 0
        for p in self.pieces:
            while task_index < len(tasks) and tasks[task_index].end <= p.start_seconds:
                task_index += 1
            replaced = task_index < len(tasks) and tasks[task_index].start < p.end_seconds
            if replaced:
                if p.assessment != "UNRESOLVED":
                    raise _LocalFailure("REFINEMENT_SELECTED_CERTIFIED_COVERAGE")
            else:
                kept.append(p)
        self.counts["reused_certificate_pieces"] += sum(_b4._certified(p.assessment) for p in kept)
        return self._partition(sorted(kept+new, key=lambda p: p.start_seconds))

    def _pass(self, index, h, tasks):
        self._ledger()
        n, g, plans, blocked = self._plan(tasks, h)
        reserved = {"reserved_integration_steps": n, "reserved_picard_attempts": n*self.q.coast.enclosure_policy.max_picard_iterations,
            "reserved_geometry_cells": g or 0, "reserved_arithmetic_operations": 512*(1+(g or 0)),
            "reserved_evidence_units": 12*n+24*(g or 0)+16}
        ceilings = {"reserved_integration_steps": self.q.policy.max_integration_steps,
            "reserved_picard_attempts": self.q.policy.max_picard_attempts,
            "reserved_geometry_cells": self.q.policy.max_geometry_cells,
            "reserved_arithmetic_operations": self.q.policy.max_arithmetic_operations,
            "reserved_evidence_units": self.q.policy.max_retained_evidence_units}
        if blocked is None:
            blocked = next((name for name, amount in reserved.items() if self.counts[name]+amount > ceilings[name]), None)
        before = self.counts.copy(); picard_before = self.ar.picard_attempts
        first_geometry = len(self.geometry_records)
        if blocked:
            self.passes.append(LocalPass(index,h,"rejected_plan",blocked,n,g,0,0,0,0,0,0,0,0,0,0,0,(),0,0))
            return "GLOBAL_BUDGET_EXHAUSTED: "+blocked
        for name, amount in reserved.items(): self.counts[name] += amount
        status, reason, geometry_ar = "failed", None, None
        try:
            if not self.boundaries: self._root()
            pending = []
            policy = replace(self.q.coast.enclosure_policy, step_seconds=float(h))
            for task, ends, geometry in plans:
                parent = self._seed(self.boundaries[task.seed_id])
                if parent.elapsed_seconds != task.seed_time:
                    raise _LocalFailure("PLANNED_SEED_TIME_MISMATCH")
                if index: self.counts["reused_boundary_records"] += 1
                ids = []
                for end in ends:
                    parent, step_id = self._edge(parent, end, policy, index); ids.append(step_id)
                pending.extend((a,b,ids[i],k) for a,b,i,k in geometry)
            geometry_ar = _b3._Rational()
            weights = _b3._shape_weights(self.q.table.frame.ellipsoid, geometry_ar)
            new = []
            for start,end,step_id,sun_index in sorted(pending):
                self.counts["geometry_cells_attempted"] += 1
                cell = _b3._geometry_cell(self.q.table, self.steps[step_id].tube,
                                         step_id,sun_index,start,end,weights,geometry_ar)
                if cell.assessment not in ("ILLUMINATED","OCCULTED","UNRESOLVED"):
                    raise _LocalFailure("INVALID_GEOMETRY_ASSESSMENT")
                gid = len(self.geometry_records)
                record = GeometryRecord(gid,index,step_id,cell,self.authority)
                self.geometry_records.append(record); self._geometry_signatures.append(_signature(record))
                self.counts["geometry_cells_evaluated"] += 1
                new.append(LocalWindow(start,end,cell.assessment,(cell.reason,), (LocalSupport(start,end,gid),)))
                self._storage()
            if (self.counts["attempted_integration_steps"]-before["attempted_integration_steps"] > n
                    or self.counts["completed_integration_steps"]-before["completed_integration_steps"] > n
                    or self.ar.picard_attempts-picard_before > reserved["reserved_picard_attempts"]
                    or self.counts["geometry_cells_attempted"]-before["geometry_cells_attempted"] > g
                    or self.counts["geometry_cells_evaluated"]-before["geometry_cells_evaluated"] > g
                    or geometry_ar.operations > reserved["reserved_arithmetic_operations"]):
                raise _LocalFailure("ACTUAL_WORK_EXCEEDED_CHARGED_RESERVATION")
            self._ledger()
            pieces = self._overlay(new,tasks)
            if self._units(pieces,_merge(pieces)) > self.counts["reserved_evidence_units"]:
                raise _LocalFailure("COVERAGE_EVIDENCE_EXCEEDED_RESERVATION")
            self.pieces = pieces
            status = "complete"
        except Exception as error:
            reason = str(error) or type(error).__name__
            if not isinstance(error, (_LocalFailure,_f3._Unresolved,DecimalException,_b3._WorkFailure,_b4._SearchFailure,OverflowError,ZeroDivisionError)):
                self.actual_work_accounting_complete = False
            raise
        finally:
            self.counts["picard_attempts"] = self.ar.picard_attempts
            operations = 0 if geometry_ar is None else geometry_ar.operations
            self.counts["arithmetic_operations"] += operations
            delta = lambda name: self.counts[name]-before[name]
            self.passes.append(LocalPass(index,h,status,reason,n,g,*[reserved[name] for name in (
                "reserved_integration_steps","reserved_picard_attempts","reserved_geometry_cells",
                "reserved_arithmetic_operations","reserved_evidence_units")],
                delta("attempted_integration_steps"),delta("completed_integration_steps"),self.ar.picard_attempts-picard_before,
                delta("geometry_cells_attempted"),delta("geometry_cells_evaluated"),operations,
                tuple(range(first_geometry,len(self.geometry_records))),delta("reused_boundary_records"),delta("reused_certificate_pieces")))
        return None

    def run(self):
        h = _time(Q(self.q.coast.enclosure_policy.step_seconds))
        for index in range(self.q.policy.max_passes):
            tasks = self._initial_tasks() if index == 0 else self._local_tasks()
            reason = self._pass(index,h,tasks)
            if reason: return "budget_exhausted",reason
            width = _b4._uncertainty_width(self.pieces)
            if width == 0: return "classified","ALL_SPANS_CLASSIFIED"
            if width <= Q(self.q.requested_resolution_seconds):
                return "resolution_reached","CONNECTED_UNCERTAINTY_WIDTH_CRITERION_REACHED_NO_EVENT_CLAIM"
            if index+1 == self.q.policy.max_passes: break
            target = _time(h/2); step = float(target)
            if Q(step) != target or step < 2**-20:
                return "numerical_limit","EXACT_HALVING_NOT_REPRESENTABLE_OR_BELOW_F3_STEP_FLOOR"
            h = target
        return "budget_exhausted","GLOBAL_PASS_COUNT_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class LocalIlluminationResult:
    request: LocalIlluminationRequest
    status: str = field(init=False, default="computational_failure")
    reason: str | None = field(init=False, default=None)
    coverage_complete: bool = field(init=False, default=False)
    windows: tuple[LocalWindow, ...] | None = field(init=False, default=None)
    boundaries: tuple[BoundaryRecord, ...] = field(init=False, default=())
    steps: tuple[StepRecord, ...] = field(init=False, default=())
    geometry_records: tuple[GeometryRecord, ...] = field(init=False, default=())
    passes: tuple[LocalPass, ...] = field(init=False, default=())
    common_authority_digest: str = field(init=False, default="")
    all_spans_classified: bool = field(init=False, default=False)
    temporal_resolution_achieved: bool = field(init=False, default=False)
    max_unresolved_width_seconds: Q | None = field(init=False, default=None)
    planned_integration_steps_considered: int = field(init=False, default=0)
    reserved_integration_steps: int = field(init=False, default=0)
    attempted_integration_steps: int = field(init=False, default=0)
    completed_integration_steps: int = field(init=False, default=0)
    reserved_picard_attempts: int = field(init=False, default=0)
    picard_attempts: int = field(init=False, default=0)
    planned_geometry_cells_considered: int = field(init=False, default=0)
    reserved_geometry_cells: int = field(init=False, default=0)
    geometry_cells_attempted: int = field(init=False, default=0)
    geometry_cells_evaluated: int = field(init=False, default=0)
    reserved_arithmetic_operations: int = field(init=False, default=0)
    arithmetic_operations: int = field(init=False, default=0)
    reserved_evidence_units: int = field(init=False, default=0)
    retained_evidence_units: int = field(init=False, default=0)
    reused_boundary_records: int = field(init=False, default=0)
    reused_certificate_pieces: int = field(init=False, default=0)
    actual_work_accounting_complete: bool = field(init=False, default=True)
    combined_qualification: str = field(init=False, default="UNRESOLVED")
    combined_reasons: tuple[str, ...] = field(init=False, default=_b3.COMBINED_REASONS)

    __hash__ = None

    def __post_init__(self):
        request = _request(self.request)
        object.__setattr__(self,"request",request)
        session = _Session(request)
        object.__setattr__(self,"common_authority_digest",session.authority)
        try:
            status,reason = session.run()
            object.__setattr__(self,"status",status); object.__setattr__(self,"reason",reason)
            if session.pieces:
                windows = _merge(session.pieces)
                width = _b4._uncertainty_width(session.pieces)
                for name,value in (("windows",windows),("coverage_complete",True),
                        ("max_unresolved_width_seconds",width),("all_spans_classified",width==0),
                        ("temporal_resolution_achieved",width<=Q(request.requested_resolution_seconds))):
                    object.__setattr__(self,name,value)
        except (_LocalFailure,_f3._Unresolved,DecimalException,_b3._WorkFailure,_b4._SearchFailure,
                ArithmeticError,ValueError,RuntimeError) as error:
            object.__setattr__(self,"reason",str(error) or type(error).__name__)
        finally:
            for name in ("boundaries","steps","geometry_records","passes"):
                object.__setattr__(self,name,tuple(getattr(session,name)))
            for name,value in session.counts.items(): object.__setattr__(self,name,value)
            object.__setattr__(self,"actual_work_accounting_complete",session.actual_work_accounting_complete)
            object.__setattr__(self,"retained_evidence_units",session._units(
                session.pieces if self.coverage_complete else (), self.windows or ()))


def evaluate_local_illumination(request):
    return LocalIlluminationResult(request)


__all__ = ["LocalIlluminationPolicy","LocalIlluminationRequest","LocalIlluminationResult",
           "BoundaryRecord","StepRecord","GeometryRecord","LocalSupport","LocalWindow","LocalPass",
           "evaluate_local_illumination"]
