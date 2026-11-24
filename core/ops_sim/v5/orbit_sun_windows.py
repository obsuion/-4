"""Bounded whole-interval searches of the declared J2/affine-Sun model.

Every refinement re-runs B3 from the original authority. Certification is
conditional; unresolved coverage never asserts an eclipse event or action grant.
"""
from dataclasses import dataclass, field, fields, replace
from fractions import Fraction as Q
from math import isfinite

from .orbit_config import GeometryInstant, _exact
from .orbit_j2_binding import J2CoastOrbitInputs
from .sun_table import SunPositionTable
from .sun_table_document import _table_map
from .experiment_codec import content_digest
from . import orbit_sun_intervals as _b3
from . import orbit_j2_segments as _b2
from .orbit_sun_intervals_document import interval_request_digest


MAX_TIME_BITS = 2048
LIMITS = {"max_trials": 16, "max_integration_steps": 65536,
          "max_geometry_cells": 65536, "max_retained_evidence_units": 393216,
          "max_arithmetic_operations": 33562624}
PHYSICAL_DOMAIN = "m2-illumination-window-common-authority-v1"


@dataclass(frozen=True, slots=True)
class IlluminationSearchPolicy:
    max_trials: int
    max_integration_steps: int
    max_geometry_cells: int
    max_retained_evidence_units: int
    max_arithmetic_operations: int

    def __post_init__(self):
        for name, limit in LIMITS.items():
            value = getattr(self, name)
            _exact(value, int, name)
            if not 1 <= value <= limit:
                raise ValueError(f"{name} must be in [1, {limit}]")


def _time(value):
    _exact(value, Q, "exact time")
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_TIME_BITS:
        raise _SearchFailure("exact time representation ceiling exceeded")
    return value


@dataclass(frozen=True, slots=True)
class IlluminationWindowRequest:
    coast: J2CoastOrbitInputs
    table: SunPositionTable
    start: GeometryInstant
    end: GeometryInstant
    requested_resolution_seconds: float
    policy: IlluminationSearchPolicy

    __hash__ = None

    def __post_init__(self):
        # Accepted B3 validation rebuilds every physical/provenance authority,
        # but does not integrate. Existing codec registrations remain unchanged.
        q = _b3.IntervalIlluminationRequest(self.coast, self.table, self.start,
                                           self.end, _b3.IntervalIlluminationPolicy(5118))
        _exact(self.policy, IlluminationSearchPolicy, "policy")
        policy = IlluminationSearchPolicy(**{f.name: getattr(self.policy, f.name)
                                             for f in fields(IlluminationSearchPolicy)})
        resolution = self.requested_resolution_seconds
        if type(resolution) not in (int, float):
            raise TypeError("requested_resolution_seconds requires built-in int or float")
        try:
            normalized = float(resolution)
        except OverflowError as error:
            raise ValueError("resolution exceeds binary64") from error
        if (not isfinite(normalized) or not 0 < normalized <= 2**41
                or (type(resolution) is int and int(normalized) != resolution)):
            raise ValueError("resolution must be positive, exactly admitted and <=2**41 seconds")
        for name in ("coast", "table", "start", "end"):
            object.__setattr__(self, name, getattr(q, name))
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "requested_resolution_seconds", normalized)


def _request(value):
    _exact(value, IlluminationWindowRequest, "request")
    return IlluminationWindowRequest(value.coast, value.table, value.start, value.end,
                                     value.requested_resolution_seconds, value.policy)


def _physical_digest(q):
    # The sole changing authority is enclosure step_seconds. Everything else,
    # including nominal solver and all provenance, is common to every proof.
    c = q.coast
    return content_digest(PHYSICAL_DOMAIN, {
        "trajectory": c.trajectory, "solver_config": c.solver_config,
        "coast_versions": (c.model, c.representation_version, c.binding_version, c.policy_version),
        "enclosure_fixed_policy": {f.name: getattr(c.enclosure_policy, f.name)
                                    for f in fields(c.enclosure_policy) if f.name != "step_seconds"},
        "table": _table_map(q.table), "start": q.start, "end": q.end})


class _SearchFailure(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CellSupport:
    start_seconds: Q
    end_seconds: Q
    trial_index: int
    cell_index: int
    trial_digest: str


@dataclass(frozen=True, slots=True)
class IlluminationWindow:
    start_seconds: Q
    end_seconds: Q
    assessment: str
    reasons: tuple[str, ...]
    supports: tuple[CellSupport, ...]
    endpoint_convention: str = field(init=False, default="LEFT_CLOSED_RIGHT_OPEN_FINAL_END_INCLUDED")


@dataclass(frozen=True, slots=True)
class IlluminationTrial:
    index: int
    request: _b3.IntervalIlluminationRequest
    input_digest: str
    planned_integration_steps: int
    planned_geometry_cells: int | None
    reserved_integration_steps: int
    reserved_geometry_cells: int
    reserved_arithmetic_operations: int
    reserved_evidence_units: int
    evidence: _b3.IntervalIlluminationResult | None
    status: str
    reason: str | None


def _certified(label):
    return label in ("ILLUMINATED", "OCCULTED")


def _check_common_boxes(a, b):
    # On the temporal overlap both boxes contain the SAME original-authority
    # solution and affine/RN Sun components. Subset nesting is not assumed.
    for name in ("position_bounds_m", "provider_sun_bounds_m"):
        if any(max(x[0], y[0]) > min(x[1], y[1])
               for x, y in zip(getattr(a, name), getattr(b, name))):
            raise _SearchFailure("INCONSISTENT_COMMON_AUTHORITY_ENCLOSURES")


def _pieces(evidence, index, digest, old, trials):
    """Linear nested-grid overlay, one supporting certificate per new cell."""
    new = []
    j = 0
    for k, cell in enumerate(evidence.cells):
        start, end = _time(cell.start_seconds), _time(cell.end_seconds)
        label, reasons = cell.assessment, (cell.reason,)
        if label not in ("ILLUMINATED", "OCCULTED", "UNRESOLVED"):
            raise _SearchFailure("invalid upstream assessment")
        support = CellSupport(start, end, index, k, digest)
        if old:
            while j+1 < len(old) and old[j].end_seconds <= start:
                j += 1
            prior = old[j]
            if not prior.start_seconds <= start < end <= prior.end_seconds:
                raise _SearchFailure("refined partition is not nested in preceding coverage")
            # Check closed overlaps, including either neighboring old cell at
            # a shared endpoint; interval facts cannot contradict there either.
            for p in old[max(0, j-1):min(len(old), j+2)]:
                if max(p.start_seconds, start) > min(p.end_seconds, end):
                    continue
                ref = p.supports[0]
                source = trials[ref.trial_index].evidence.cells[ref.cell_index]
                _check_common_boxes(source, cell)
                if _certified(p.assessment) and _certified(label) and p.assessment != label:
                    raise _SearchFailure("CONTRADICTORY_CLOSED_CELL_CERTIFICATES")
            if _certified(prior.assessment) and not _certified(label):
                ref = prior.supports[0]
                label, reasons = prior.assessment, prior.reasons
                support = CellSupport(start, end, ref.trial_index, ref.cell_index, ref.trial_digest)
        new.append(IlluminationWindow(start, end, label, reasons, (support,)))
    if (not new or new[0].start_seconds != Q(evidence.request.start.elapsed_seconds)
            or new[-1].end_seconds != Q(evidence.request.end.elapsed_seconds)
            or any(a.end_seconds != b.start_seconds for a, b in zip(new, new[1:]))):
        raise _SearchFailure("incomplete whole-interval partition")
    # Opposing closed certificates in the new partition would disagree at
    # their common endpoint. B3 should never supply such evidence.
    if any(_certified(a.assessment) and _certified(b.assessment) and a.assessment != b.assessment
           for a, b in zip(new, new[1:])):
        raise _SearchFailure("CONTRADICTORY_ADJACENT_CLOSED_CERTIFICATES")
    return tuple(new)


def _merge(pieces):
    windows = []
    group = []
    for p in pieces:
        if group and (group[0].assessment, group[0].reasons) != (p.assessment, p.reasons):
            windows.append(IlluminationWindow(group[0].start_seconds, group[-1].end_seconds,
                                               group[0].assessment, group[0].reasons,
                                               tuple(ref for x in group for ref in x.supports)))
            group = []
        group.append(p)
    if group:
        windows.append(IlluminationWindow(group[0].start_seconds, group[-1].end_seconds,
                                           group[0].assessment, group[0].reasons,
                                           tuple(ref for x in group for ref in x.supports)))
    return tuple(windows)


def _uncertainty_width(pieces):
    # Consecutive uncertainty with DIFFERENT domain reasons is still one
    # connected uncertainty component. Cell splitting alone never meets a
    # smaller requested width.
    largest = Q(0)
    begin = None
    for p in pieces:
        if p.assessment == "UNRESOLVED":
            if begin is None:
                begin = p.start_seconds
            largest = max(largest, _time(p.end_seconds-begin))
        else:
            begin = None
    return largest


@dataclass(frozen=True, slots=True)
class IlluminationWindowResult:
    request: IlluminationWindowRequest
    status: str = field(init=False, default="computational_failure")
    reason: str | None = field(init=False, default=None)
    coverage_complete: bool = field(init=False, default=False)
    windows: tuple[IlluminationWindow, ...] | None = field(init=False, default=None)
    trials: tuple[IlluminationTrial, ...] = field(init=False, default=())
    common_authority_digest: str = field(init=False, default="")
    all_spans_classified: bool = field(init=False, default=False)
    temporal_resolution_achieved: bool = field(init=False, default=False)
    max_unresolved_width_seconds: Q | None = field(init=False, default=None)
    planned_integration_steps_considered: int = field(init=False, default=0)
    reserved_integration_steps: int = field(init=False, default=0)
    completed_integration_steps: int = field(init=False, default=0)
    reserved_picard_attempts: int = field(init=False, default=0)
    picard_attempts: int = field(init=False, default=0)
    planned_geometry_cells_considered: int = field(init=False, default=0)
    reserved_geometry_cells: int = field(init=False, default=0)
    geometry_cells_evaluated: int = field(init=False, default=0)
    reserved_arithmetic_operations: int = field(init=False, default=0)
    arithmetic_operations: int = field(init=False, default=0)
    reserved_evidence_units: int = field(init=False, default=0)
    propagation_calls: int = field(init=False, default=0)
    b3_evaluation_calls: int = field(init=False, default=0)
    actual_work_accounting_complete: bool = field(init=False, default=True)
    retained_evidence_units: int = field(init=False, default=0)
    combined_qualification: str = field(init=False, default="UNRESOLVED")
    combined_reasons: tuple[str, ...] = field(init=False, default=_b3.COMBINED_REASONS)

    __hash__ = None

    def __post_init__(self):
        object.__setattr__(self, "request", _request(self.request))
        object.__setattr__(self, "common_authority_digest", _physical_digest(self.request))
        try:
            self._evaluate()
        except (_SearchFailure, OverflowError, ZeroDivisionError) as error:
            # Never publish part of a failed trial, or a newly computed prefix.
            for name, value in (("status", "computational_failure"), ("reason", str(error)),
                                ("windows", None), ("coverage_complete", False),
                                ("all_spans_classified", False), ("temporal_resolution_achieved", False),
                                ("max_unresolved_width_seconds", None)):
                object.__setattr__(self, name, value)
            object.__setattr__(self, "retained_evidence_units", self._history_units())

    def _history_units(self):
        total = 0
        for t in self.trials:
            if t.evidence is not None:
                total += len(t.evidence.cells or ())
                if t.evidence.j2_evidence is not None:
                    total += len(t.evidence.j2_evidence.cells or ())
        return total

    def _add(self, name, amount):
        object.__setattr__(self, name, getattr(self, name)+amount)

    def _stop(self, status, reason, pieces):
        if pieces:
            width = _uncertainty_width(pieces)
            windows = _merge(pieces)
            history = self._history_units()
            # All retained cell objects, piece/support objects, window objects,
            # and support tuple references are counted conservatively.
            units = history+3*len(pieces)+len(windows)
            if units > self.reserved_evidence_units:
                raise _SearchFailure("retained evidence exceeded reservation")
            for name, value in (("windows", windows), ("coverage_complete", True),
                                ("max_unresolved_width_seconds", width),
                                ("all_spans_classified", width == 0),
                                ("temporal_resolution_achieved", width <= Q(self.request.requested_resolution_seconds)),
                                ("retained_evidence_units", units)):
                object.__setattr__(self, name, value)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason", reason)

    def _evaluate(self):
        q, policy = self.request, self.request.policy
        pieces = ()
        coast = q.coast
        for index in range(policy.max_trials):
            trial_request = _b3.IntervalIlluminationRequest(coast, q.table, q.start, q.end,
                                                           _b3.IntervalIlluminationPolicy(5118))
            if _physical_digest(trial_request) != self.common_authority_digest:
                raise _SearchFailure("refinement changed common physical authority")
            segment = _b2.J2SegmentRequest(coast, q.start, q.end)
            plan = _b2._plan(segment)
            for t in plan[:4]:
                _time(t)
            count = plan[-1]
            boundaries = _b3._refinement_plan(segment, q.table)
            geometry = None if boundaries is None else len(boundaries)-1
            if boundaries:
                for t in boundaries:
                    _time(t)
            g = geometry or 0
            operations = _b3.MAX_CELL_OPERATIONS*(1+g)
            retained = count+5*g
            self._add("planned_integration_steps_considered", count)
            self._add("planned_geometry_cells_considered", g)
            digest = interval_request_digest(trial_request)
            reservations = (("reserved_integration_steps", count, policy.max_integration_steps),
                            ("reserved_geometry_cells", g, policy.max_geometry_cells),
                            ("reserved_evidence_units", retained, policy.max_retained_evidence_units),
                            ("reserved_arithmetic_operations", operations, policy.max_arithmetic_operations))
            blocked = next((name for name, amount, ceiling in reservations
                            if getattr(self, name)+amount > ceiling), None)
            if blocked:
                attempt = IlluminationTrial(index, trial_request, digest, count, geometry,
                                             0, 0, 0, 0, None, "rejected_plan", blocked)
                object.__setattr__(self, "trials", self.trials+(attempt,))
                self._stop("budget_exhausted", "GLOBAL_BUDGET_EXHAUSTED: "+blocked, pieces)
                return
            for name, amount, _ in reservations:
                self._add(name, amount)
            self._add("reserved_picard_attempts", count*coast.enclosure_policy.max_picard_iterations)
            self._add("b3_evaluation_calls", 1)
            # B3 is the sole evaluation path and owns exactly one B2 call.
            try:
                evidence = _b3.evaluate_interval_illumination(trial_request)
            except (ArithmeticError, ValueError, RuntimeError) as error:
                attempt = IlluminationTrial(index, trial_request, digest, count, geometry,
                                             count, g, operations, retained, None,
                                             "exception_failed", str(error) or type(error).__name__)
                object.__setattr__(self, "trials", self.trials+(attempt,))
                object.__setattr__(self, "actual_work_accounting_complete", False)
                # With no returned upstream diagnostics actual work in this
                # failed call is UNKNOWN. Counters contain only known work;
                # reservations remain charged, and no zero-work claim is made.
                raise _SearchFailure("B3_EXCEPTION_ACTUAL_WORK_UNKNOWN: "+attempt.reason) from error
            _exact(evidence, _b3.IntervalIlluminationResult, "B3 result")
            self._add("propagation_calls", evidence.propagation_calls)
            attempt = IlluminationTrial(index, trial_request, digest, count, geometry,
                                         count, g, operations, retained, evidence,
                                         evidence.status, evidence.reason)
            object.__setattr__(self, "trials", self.trials+(attempt,))
            self._add("geometry_cells_evaluated", evidence.geometry_cells_evaluated)
            self._add("arithmetic_operations", evidence.arithmetic_operations)
            if evidence.j2_evidence is not None:
                self._add("completed_integration_steps", evidence.j2_evidence.enclosure_steps)
                self._add("picard_attempts", evidence.j2_evidence.picard_attempts)
            if (evidence.request != trial_request or evidence.geometry_cells_evaluated > g
                    or evidence.arithmetic_operations > operations
                    or (evidence.j2_evidence is not None and
                        (evidence.j2_evidence.enclosure_steps > count or
                         evidence.j2_evidence.picard_attempts > count*coast.enclosure_policy.max_picard_iterations))):
                raise _SearchFailure("upstream evidence/counters do not match reservation")
            if evidence.status != "complete":
                raise _SearchFailure("B3_UNRESOLVED: "+str(evidence.reason))
            if geometry is None or evidence.cells is None or len(evidence.cells) != geometry:
                raise _SearchFailure("complete B3 partition does not match preflight")
            pieces = _pieces(evidence, index, digest, pieces, self.trials)
            width = _uncertainty_width(pieces)
            if width == 0:
                self._stop("classified", "ALL_SPANS_CLASSIFIED", pieces)
                return
            if width <= Q(q.requested_resolution_seconds):
                self._stop("resolution_reached", "CONNECTED_UNCERTAINTY_WIDTH_CRITERION_REACHED_NO_EVENT_CLAIM", pieces)
                return
            if index+1 == policy.max_trials:
                break
            target = _time(Q(coast.enclosure_policy.step_seconds)/2)
            h = float(target)
            if h <= 0 or Q(h) != target or h < 2**-20:
                self._stop("numerical_limit", "EXACT_HALVING_NOT_REPRESENTABLE_OR_BELOW_F3_STEP_FLOOR", pieces)
                return
            coast = replace(coast, enclosure_policy=replace(coast.enclosure_policy, step_seconds=h))
        self._stop("budget_exhausted", "GLOBAL_TRIAL_COUNT_EXHAUSTED", pieces)


def evaluate_illumination_windows(request):
    return IlluminationWindowResult(request)


__all__ = ["IlluminationSearchPolicy", "IlluminationWindowRequest", "CellSupport",
           "IlluminationWindow", "IlluminationTrial", "IlluminationWindowResult",
           "evaluate_illumination_windows"]
