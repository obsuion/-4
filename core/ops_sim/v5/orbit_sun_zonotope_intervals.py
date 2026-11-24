"""Opt-in conditional illumination from original-anchor continuous v3 tubes.

No dispatch change. Exact rational geometry reuses the frozen B3 half-ray kernel.
The orbital ledger belongs exclusively to B33; geometry is accounted separately.
"""
from bisect import bisect_right
from dataclasses import dataclass, field, fields, is_dataclass
from decimal import Decimal
from fractions import Fraction as Q
from math import isfinite

from . import orbit_j2 as _coast
from . import orbit_j2_zonotope_segments as _segments
from . import orbit_j2_zonotope_segments_document as _segment_document
from . import orbit_sun_intervals as _geometry_owner
from .experiment_codec import canonical_content
from .orbit_config import _exact, _instant
from .sun_table import SunPositionTable, _table

API_ID = "m2-zonotope-interval-illumination-v1"
API_VERSION = 1
GEOMETRY_RESOURCE_POLICY_VERSION = 1
MAX_GEOMETRY_CELLS = 5118
MAX_RATIONAL_BITS = 16384
MAX_CELL_OPERATIONS = 512
MAX_GEOMETRY_OPERATIONS = (MAX_GEOMETRY_CELLS + 1) * MAX_CELL_OPERATIONS
MAX_INPUT_NODES = 131072
MAX_INPUT_TEXT = 16384
_SOURCE_IDENTITIES = dict(api_id="m2-j2-zonotope-segments-v1", api_version=1,
                          publication_version=1, transport_resource_policy_version=3,
                          kernel_id="incremental-j2-jet-v1",
                          method_id="m2-centered-zonotope-pb6-v1", method_version=1)


def _bounded_input(value):
    """Data-only scan, before canonical constructors; independent of v3 work."""
    remaining = MAX_INPUT_NODES
    def visit(v, depth):
        nonlocal remaining
        if depth > 64 or remaining <= 0:
            raise ValueError("bounded input tree admission exceeded")
        remaining -= 1
        if type(v) is str:
            if len(v) > MAX_INPUT_TEXT:
                raise ValueError("bounded input text admission exceeded")
        elif type(v) in (tuple, list, dict):
            if len(v) > 4096:
                raise ValueError("bounded input container admission exceeded")
            for item in (v.values() if type(v) is dict else v):
                visit(item, depth + 1)
        elif is_dataclass(v):
            for f in fields(v):
                visit(getattr(v, f.name), depth + 1)
        elif type(v) is int:
            if v.bit_length() > MAX_RATIONAL_BITS:
                raise ValueError("bounded input integer admission exceeded")
        # Enum/float exactness and full nested normalization are subsequently
        # checked by the accepted input-only canonical owners.
    visit(value, 0)


@dataclass(frozen=True, slots=True)
class ZonotopeIntervalIlluminationPolicy:
    max_cells: int
    max_arithmetic_operations: int = MAX_GEOMETRY_OPERATIONS
    resource_policy_version: int = field(init=False, default=1)

    def __post_init__(self):
        for n in ("max_cells", "max_arithmetic_operations", "resource_policy_version"):
            _exact(getattr(self, n), int, n)
        if not 1 <= self.max_cells <= MAX_GEOMETRY_CELLS:
            raise ValueError("max_cells must be in [1,5118]")
        if not 1 <= self.max_arithmetic_operations <= MAX_GEOMETRY_OPERATIONS:
            raise ValueError("unsupported geometry arithmetic ceiling")
        if self.resource_policy_version != GEOMETRY_RESOURCE_POLICY_VERSION:
            raise ValueError("unsupported geometry resource policy")


def _policy(value):
    _exact(value, ZonotopeIntervalIlluminationPolicy, "geometry policy")
    value.__post_init__()
    return ZonotopeIntervalIlluminationPolicy(value.max_cells, value.max_arithmetic_operations)


def _segment(value):
    _segments._request(value)
    _bounded_input((value.trajectory.initial_state, value.trajectory.gravity_model,
                    value.end, value.policy.base_policy))
    # Safe decomposed authority, never canonical_copy(full trajectory).
    data = _segment_document._input_data(value)
    state, model = _coast._authorities(data["initial_state"], data["gravity_model"])
    trajectory = object.__new__(_coast.J2CartesianTrajectory)
    object.__setattr__(trajectory, "initial_state", state)
    object.__setattr__(trajectory, "gravity_model", model)
    return _segments.J2ZonotopeSegmentRequest(trajectory, _instant(value.end), value.policy)


@dataclass(frozen=True, slots=True)
class ZonotopeIntervalIlluminationRequest:
    segment: _segments.J2ZonotopeSegmentRequest
    table: SunPositionTable
    policy: ZonotopeIntervalIlluminationPolicy
    api_id: str = field(init=False, default=API_ID)
    api_version: int = field(init=False, default=API_VERSION)
    geometry_resource_policy_version: int = field(init=False, default=1)

    __hash__ = None

    def __post_init__(self):
        _exact(self.table, SunPositionTable, "Sun table")
        _bounded_input(self.table)
        segment, table, policy = _segment(self.segment), _table(self.table), _policy(self.policy)
        origin = segment.trajectory.initial_state.position
        if origin.frame != table.frame or origin.instant.epoch != table.epoch:
            raise ValueError("complete model frame/ellipsoid/TT binding mismatch")
        if not table.domain_seconds[0] <= origin.instant.elapsed_seconds < segment.end.elapsed_seconds <= table.domain_seconds[1]:
            raise ValueError("entire original-anchor span outside closed Sun-table domain")
        for n, v in (("segment", segment), ("table", table), ("policy", policy)):
            object.__setattr__(self, n, v)


def _request(value):
    _exact(value, ZonotopeIntervalIlluminationRequest, "request")
    for n, v in (("api_id", API_ID), ("api_version", 1), ("geometry_resource_policy_version", 1)):
        _exact(getattr(value, n), type(v), n)
        if getattr(value, n) != v:
            raise ValueError("unsupported illumination input identity")
    return ZonotopeIntervalIlluminationRequest(value.segment, value.table, value.policy)


class _Failure(_geometry_owner._WorkFailure):
    pass


class _Rational(_geometry_owner._Rational):
    def __init__(self, maximum):
        super().__init__()
        self.maximum = maximum
        self.limit = min(MAX_CELL_OPERATIONS, maximum)

    def begin_cell(self):
        self.limit = min(self.operations + MAX_CELL_OPERATIONS, self.maximum)


def _plan(segment, table):
    anchor = Q(segment.trajectory.initial_state.position.instant.elapsed_seconds)
    end, step = Q(segment.end.elapsed_seconds), Q(segment.policy.base_policy.step_seconds)
    full, tail = divmod(end-anchor, step)
    count = full + bool(tail)
    if end-anchor > 86400 or count > segment.policy.base_policy.max_steps or count > 4096:
        raise _Failure("source horizon/step budget exceeded before propagation")
    source = tuple(anchor+k*step for k in range(int(full)+1))
    if tail:
        source += (end,)
    # At most 4097 source boundaries and 1022 interior Sun knots.
    boundaries = tuple(sorted(set(source) | {Q(s.elapsed_seconds) for s in table.samples
                                          if anchor < Q(s.elapsed_seconds) < end}))
    return source, boundaries


def _fraction_endpoint(v):
    _exact(v, Decimal, "upstream SI endpoint")
    if not v.is_finite():
        raise _Failure("nonfinite upstream endpoint")
    t = v.as_tuple()
    # Bound conversion work BEFORE constructing 10**large_exponent. These
    # conservative representation guards cover all accepted plain B33 outputs.
    if 4 * (len(t.digits) + abs(t.exponent) + 1) > MAX_RATIONAL_BITS:
        raise _Failure("Decimal representation exceeds bounded conversion domain")
    return _Rational.checked(Q(v))


def _validate_source(evidence, request, grid):
    _exact(evidence, _segments.J2ZonotopeSegmentResult, "upstream evidence")
    for n, v in _SOURCE_IDENTITIES.items():
        _exact(getattr(evidence, n), type(v), n)
        if getattr(evidence, n) != v:
            raise _Failure("stale/substituted upstream identity: " + n)
    if canonical_content(_segment_document._input_data(evidence.request)) != canonical_content(_segment_document._input_data(request)):
        raise _Failure("substituted upstream physical request")
    _exact(evidence.status, str, "upstream status")
    if evidence.status != "enclosed":
        raise _Failure("J2_ZONOTOPE_SEGMENTS_UNRESOLVED: " + str(evidence.reason))
    _exact(evidence.cells, tuple, "source cells")
    if len(evidence.cells) != len(grid)-1:
        raise _Failure("incomplete upstream source partition")
    count = len(grid)-1
    for n in ("planned_steps", "attempted_steps", "completed_steps"):
        _exact(getattr(evidence, n), int, n)
        if getattr(evidence, n) != count:
            raise _Failure("upstream successful work/partition mismatch")
    for n in ("charged_leaf_operations", "reserved_control_operations", "scalar_operations", "picard_attempts", "reductions"):
        _exact(getattr(evidence, n), int, n)
        if getattr(evidence, n) < 0:
            raise _Failure("negative upstream work")
    if evidence.scalar_operations != evidence.charged_leaf_operations + evidence.reserved_control_operations or evidence.scalar_operations > request.policy.max_scalar_operations:
        raise _Failure("upstream arithmetic ledger mismatch")
    _exact(evidence.budget_rejected, bool, "upstream budget flag")
    if evidence.budget_rejected:
        raise _Failure("successful upstream marked rejected")
    for i, c in enumerate(evidence.cells):
        _exact(c, _segments.J2ZonotopeSegmentCell, "source cell")
        c.__post_init__()
        if (c.source_step_index != i or c.start_seconds != grid[i] or
                c.end_seconds != grid[i+1]):
            raise _Failure("upstream partition/grid/source-index mismatch")
        for vector in (c.position_bounds_m, c.velocity_bounds_m_per_s):
            for lo, hi in vector:
                _fraction_endpoint(lo); _fraction_endpoint(hi)


@dataclass(frozen=True, slots=True)
class _PositionTube:
    position_bounds_m: tuple


# Test seams only in the new opt-in owner. Frozen upstream/helpers stay intact.
_propagate = _segments.evaluate_j2_zonotope_segments
_geometry_cell = _geometry_owner._geometry_cell


def _publish(cells, plan):
    if len(cells) != len(plan)-1:
        raise _Failure("incomplete final geometry publication")
    for i, c in enumerate(cells):
        if (type(c) is not _geometry_owner.IntervalIlluminationCell or
                c.start_seconds != plan[i] or c.end_seconds != plan[i+1]):
            raise _Failure("final geometry partition mismatch")
    return tuple(cells)


@dataclass(frozen=True, slots=True)
class ZonotopeIntervalIlluminationResult:
    request: ZonotopeIntervalIlluminationRequest
    status: str = field(init=False, default="unresolved")
    reason: str | None = field(init=False, default=None)
    cells: tuple | None = field(init=False, default=None)
    upstream_evidence: _segments.J2ZonotopeSegmentResult | None = field(init=False, default=None)
    planned_geometry_cells: int | None = field(init=False, default=None)
    geometry_cells_evaluated: int = field(init=False, default=0)
    arithmetic_operations: int = field(init=False, default=0)
    propagation_calls: int = field(init=False, default=0)
    all_cells_classified: bool = field(init=False, default=False)
    api_id: str = field(init=False, default=API_ID)
    api_version: int = field(init=False, default=1)
    geometry_resource_policy_version: int = field(init=False, default=1)
    upstream_api_id: str = field(init=False, default=_segments.SEGMENT_API_ID)
    upstream_publication_version: int = field(init=False, default=1)
    upstream_transport_resource_policy_version: int = field(init=False, default=3)
    upstream_kernel_id: str = field(init=False, default="incremental-j2-jet-v1")
    combined_qualification: str = field(init=False, default="UNRESOLVED")
    combined_reasons: tuple = field(init=False, default=_geometry_owner.COMBINED_REASONS)

    __hash__ = None

    def __post_init__(self):
        object.__setattr__(self, "request", _request(self.request))
        ar = _Rational(self.request.policy.max_arithmetic_operations)
        try:
            self._evaluate(ar)
        except Exception as error:
            # Atomic publication: even late conversion/publication errors keep
            # orbital diagnostics separate from a combined coverage claim.
            object.__setattr__(self, "reason", type(error).__name__ + ": " + str(error))
        finally:
            object.__setattr__(self, "arithmetic_operations", ar.operations)

    def _evaluate(self, ar):
        req = self.request
        grid, plan = _plan(req.segment, req.table)
        count = len(plan)-1
        object.__setattr__(self, "planned_geometry_cells", count)
        if count > req.policy.max_cells or count > MAX_GEOMETRY_CELLS:
            raise _Failure("geometry-cell budget exceeded before propagation")
        object.__setattr__(self, "propagation_calls", 1)
        upstream = _propagate(req.segment)
        object.__setattr__(self, "upstream_evidence", upstream)
        _validate_source(upstream, req.segment, grid)
        weights = _geometry_owner._shape_weights(req.table.frame.ellipsoid, ar)
        knots = tuple(Q(s.elapsed_seconds) for s in req.table.samples)
        j, k = 0, bisect_right(knots, plan[0])-1
        pending = []
        for start, end in zip(plan, plan[1:]):
            while j+1 < len(grid)-1 and grid[j+1] <= start:
                j += 1
            while k+1 < len(knots)-1 and knots[k+1] <= start:
                k += 1
            source = upstream.cells[j]
            if not source.start_seconds <= start < end <= source.end_seconds or not knots[k] <= start < end <= knots[k+1]:
                raise _Failure("geometry/source/Sun closed-support mismatch")
            # Identical WHOLE source tube on every Sun subdivision.
            tube = _PositionTube(tuple(tuple(_fraction_endpoint(v) for v in pair)
                                       for pair in source.position_bounds_m))
            cell = _geometry_cell(req.table, tube, j, k, start, end, weights, ar)
            if (type(cell) is not _geometry_owner.IntervalIlluminationCell or cell.j2_cell_index != j or
                    cell.sun_segment_index != k or cell.position_bounds_m != tube.position_bounds_m or
                    cell.scope != _geometry_owner.ASSESSMENT_SCOPE or
                    cell.assessment not in ("ILLUMINATED", "OCCULTED", "UNRESOLVED")):
                raise _Failure("derived geometry identity/source mismatch")
            pending.append(cell)
            object.__setattr__(self, "geometry_cells_evaluated", len(pending))
        complete = _publish(pending, plan)
        classified = all(c.assessment != "UNRESOLVED" for c in complete)
        # No failure-prone work occurs after the atomic publication gate.
        object.__setattr__(self, "cells", complete)
        object.__setattr__(self, "all_cells_classified", classified)
        object.__setattr__(self, "status", "complete")


def evaluate_zonotope_interval_illumination(request):
    return ZonotopeIntervalIlluminationResult(request)


__all__ = ["ZonotopeIntervalIlluminationPolicy", "ZonotopeIntervalIlluminationRequest",
           "ZonotopeIntervalIlluminationResult", "evaluate_zonotope_interval_illumination"]
