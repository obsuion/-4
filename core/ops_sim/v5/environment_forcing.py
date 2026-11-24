"""Opt-in exact-time forcing from trusted, completed B38 owner evidence.

This adapter validates structure/binding; it neither authenticates arbitrary
fabricated Python objects nor re-proves the upstream numerical certificates.
"""
from dataclasses import dataclass, fields
from fractions import Fraction
from hashlib import sha256
from math import isfinite
import json

from . import orbit_sun_zonotope_local_v2 as light
from . import orbit_sun_zonotope_local_v2_document as light_doc
from . import orbit_sun_intervals as geometry
from . import experiment_codec
from .ids import ThermalNodeId
from .integration_time import RationalSeconds, checked_duration
from .power_loads import PowerLoadBreakdown
from .eps_system import EPSIntervalInputs
from .thermal import ThermalIntervalInputs, ThermalNodeBoundaryInput
from .thermal_coupling import ThermalHeatSourceInputs, ThermalNodeHeatSourceInput

ENDPOINTS = "LEFT_CLOSED_RIGHT_OPEN_FINAL_END_INCLUDED"
ASSESSMENTS = ("ILLUMINATED", "OCCULTED", "UNRESOLVED")
LOAD_FIELDS = tuple(f.name for f in fields(PowerLoadBreakdown))
RADIATION = ("solar", "albedo", "earth_ir")


def _type(v, t, name):
    if type(v) is not t:
        raise TypeError(name + " requires exact " + t.__name__)
    return v


def _time(v):
    _type(v, Fraction, "time")
    RationalSeconds.from_fraction(v)
    return v


def _number(v, name, *, positive=False):
    if type(v) not in (int, float):
        raise TypeError(name + " requires a built-in number")
    try:
        good = isfinite(v) and (v > 0 if positive else v >= 0)
    except OverflowError:
        good = False
    if not good:
        raise ValueError(name + " outside finite physical domain")
    return v


def _text(v, name, limit=1024):
    _type(v, str, name)
    if not v or len(v) > limit:
        raise ValueError(name + " outside bounded text domain")
    return v


def _integer(v, name):
    _type(v, int, name)
    if v < 0:
        raise ValueError(name + " must be nonnegative")
    return v


@dataclass(frozen=True, slots=True)
class ForcingPolicy:
    max_profile_entries: int = 128
    max_cells: int = 8192
    max_source_records: int = 16384

    def __post_init__(self):
        for n, upper in (("max_profile_entries", 128), ("max_cells", 8192),
                         ("max_source_records", 16384)):
            _integer(getattr(self, n), n)
            if not 1 <= getattr(self, n) <= upper:
                raise ValueError(n + " exceeds forcing admission")


@dataclass(frozen=True, slots=True)
class NodeForcing:
    node_id: ThermalNodeId
    sink_temperature_k: float
    internal_dissipation_w: float
    illuminated_solar_w: float
    absorbed_albedo_w: float
    absorbed_earth_ir_w: float
    sink_includes: tuple[str, ...] = ()

    def __post_init__(self):
        _type(self.node_id, ThermalNodeId, "node_id")
        _text(self.node_id.value, "node ID", 256)
        ThermalNodeId(self.node_id.value)
        _number(self.sink_temperature_k, "sink K", positive=True)
        for n in ("internal_dissipation_w", "illuminated_solar_w",
                  "absorbed_albedo_w", "absorbed_earth_ir_w"):
            _number(getattr(self, n), n)
        _type(self.sink_includes, tuple, "sink_includes")
        if len(self.sink_includes) > 3 or any(type(n) is not str or n not in RADIATION
                                            for n in self.sink_includes):
            raise ValueError("unknown sink convention")
        if len(set(self.sink_includes)) != len(self.sink_includes):
            raise ValueError("duplicate sink convention")
        for n, p in zip(RADIATION, (self.illuminated_solar_w,
                                    self.absorbed_albedo_w, self.absorbed_earth_ir_w)):
            if n in self.sink_includes and p != 0:
                raise ValueError("declared radiative double counting: " + n)


@dataclass(frozen=True, slots=True)
class ForcingProfileEntry:
    start_seconds: Fraction
    end_seconds: Fraction
    incidence_angle_deg: float
    loads: PowerLoadBreakdown
    nodes: tuple[NodeForcing, ...]
    non_overlap_assumption: str
    internal_includes_eps_losses: bool = False

    def __post_init__(self):
        if _time(self.start_seconds) >= _time(self.end_seconds):
            raise ValueError("profile requires positive duration")
        _number(self.incidence_angle_deg, "incidence deg")
        if self.incidence_angle_deg > 180:
            raise ValueError("incidence must be in [0,180] degrees")
        _type(self.loads, PowerLoadBreakdown, "loads")
        PowerLoadBreakdown(**{n: _number(getattr(self.loads, n), n) for n in LOAD_FIELDS})
        _type(self.nodes, tuple, "nodes")
        if not 1 <= len(self.nodes) <= 64:
            raise ValueError("1..64 thermal nodes required")
        for node in self.nodes:
            _type(node, NodeForcing, "node forcing")
            node.__post_init__()
        if len({n.node_id for n in self.nodes}) != len(self.nodes):
            raise ValueError("duplicate thermal nodes")
        _text(self.non_overlap_assumption, "explicit non-overlap assumption")
        _type(self.internal_includes_eps_losses, bool, "EPS loss convention")
        if self.internal_includes_eps_losses:
            raise ValueError("EPS conversion loss is owned by existing thermal coupling")


@dataclass(frozen=True, slots=True)
class EnvironmentForcingRequest:
    source_request: light.ZonotopeLocalIlluminationRequestV2
    start_seconds: Fraction
    end_seconds: Fraction
    node_ids: tuple[ThermalNodeId, ...]
    profile: tuple[ForcingProfileEntry, ...]
    policy: ForcingPolicy = ForcingPolicy()

    def __post_init__(self):
        _type(self.policy, ForcingPolicy, "policy").__post_init__()
        _type(self.profile, tuple, "profile")
        if not 1 <= len(self.profile) <= self.policy.max_profile_entries:
            raise ValueError("profile admission exceeded")
        _type(self.node_ids, tuple, "node_ids")
        if not 1 <= len(self.node_ids) <= 64:
            raise ValueError("1..64 configured node IDs required")
        for n in self.node_ids:
            _type(n, ThermalNodeId, "configured node ID")
            _text(n.value, "configured node ID", 256)
            ThermalNodeId(n.value)
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("duplicate configured node IDs")
        a, b = _time(self.start_seconds), _time(self.end_seconds)
        if a > b:
            raise ValueError("backward requested interval")
        # Safe input-only clone; no result constructor or propagator invocation.
        q = light._request(self.source_request)
        origin = Fraction(q.segment.trajectory.initial_state.position.instant.elapsed_seconds)
        end = Fraction(q.segment.end.elapsed_seconds)
        if not origin <= a <= b <= end:
            raise ValueError("requested interval outside original source domain")
        for e in self.profile:
            _type(e, ForcingProfileEntry, "profile entry").__post_init__()
            if {n.node_id for n in e.nodes} != set(self.node_ids):
                raise ValueError("profile nodes must exactly match declared node set")
        if any(x.end_seconds != y.start_seconds for x, y in zip(self.profile, self.profile[1:])):
            raise ValueError("profile must be ordered with no gap or overlap")
        if not self.profile[0].start_seconds <= a <= b <= self.profile[-1].end_seconds:
            raise ValueError("profile does not cover request")
        object.__setattr__(self, "source_request", q)


@dataclass(frozen=True, slots=True)
class SourceEdge:
    step_id: int
    parent_boundary_id: int
    endpoint_boundary_id: int
    trial_index: int
    pass_index: int
    bridge: bool
    start_seconds: Fraction
    end_seconds: Fraction


@dataclass(frozen=True, slots=True)
class SourceSupport:
    piece: light.LocalPiece
    geometry: light.LocalGeometry
    step_id: int
    parent_boundary_id: int
    endpoint_boundary_id: int
    geometry_support_convention: str = "CLOSED"


@dataclass(frozen=True, slots=True)
class ForcingInputCase:
    sunlit: bool
    eps_inputs: EPSIntervalInputs
    thermal_inputs: ThermalIntervalInputs
    heat_source_inputs: ThermalHeatSourceInputs


@dataclass(frozen=True, slots=True)
class EnvironmentForcingCell:
    start_seconds: Fraction
    end_seconds: Fraction
    assessment: str
    support_index: int
    profile_index: int
    alternatives: tuple[ForcingInputCase, ...]
    endpoint_convention: str = ENDPOINTS


@dataclass(frozen=True, slots=True)
class EnvironmentForcingSchedule:
    request: EnvironmentForcingRequest
    source_request_digest: str
    authority_digest: str
    original_anchor_seconds: Fraction
    source_end_seconds: Fraction
    ancestry: tuple[SourceEdge, ...]
    supports: tuple[SourceSupport, ...]
    cells: tuple[EnvironmentForcingCell, ...]
    coverage_id: str


def _source(source, request):
    _type(source, light.ZonotopeLocalIlluminationResultV2, "completed B38 result")
    if type(source.coverage_complete) is not bool or not source.coverage_complete:
        raise ValueError("incomplete source cannot become forcing")
    if type(source.status) is not str or source.status not in ("classified", "resolution_reached", "budget_exhausted"):
        raise ValueError("failed source cannot become forcing")
    for n, v in (("api_id", light.API_ID), ("api_version", 2),
                 ("resource_policy_version", 2), ("geometry_resource_policy_version", 2),
                 ("transport_resource_policy_version", 3)):
        if type(getattr(source, n)) is not type(v) or getattr(source, n) != v:
            raise ValueError("unsupported upstream identity")
    for n in ("proof_scalar_budget_rejected", "local_control_budget_rejected",
              "local_control_ledger_failed", "geometry_control_budget_rejected",
              "geometry_control_ledger_failed", "geometry_leaf_budget_rejected",
              "geometry_leaf_ledger_failed"):
        if type(getattr(source, n)) is not bool or getattr(source, n):
            raise ValueError("failed upstream ledger")
    digest = light_doc.zonotope_local_request_digest_v2(request.source_request)
    if digest != light_doc.zonotope_local_request_digest_v2(source.request):
        raise ValueError("foreign source request")
    authority = sha256(experiment_codec.json_text(experiment_codec.canonical_content(
        light_doc._input_map(request.source_request))).encode()).hexdigest()
    if type(source.authority_digest) is not str or source.authority_digest != authority:
        raise ValueError("foreign source authority")
    names = ("pieces", "windows", "boundaries", "steps", "geometry_records", "trials")
    for n in names:
        _type(getattr(source, n), tuple, n)
    if sum(len(getattr(source, n)) for n in names) > request.policy.max_source_records:
        raise ValueError("source-record admission exceeded")
    origin = Fraction(request.source_request.segment.trajectory.initial_state.position.instant.elapsed_seconds)
    end = Fraction(request.source_request.segment.end.elapsed_seconds)
    if not source.pieces or not source.boundaries:
        raise ValueError("empty source coverage or ancestry")
    maps = {}
    for name, cls in (("boundaries", light.ZonotopeBoundary), ("steps", light.LocalStep),
                      ("geometry_records", light.LocalGeometry), ("trials", light.LocalTrial)):
        m = {}
        for x in getattr(source, name):
            _type(x, cls, name)
            i = _integer(x.index if name == "trials" else x.id, name + " ID")
            if i in m:
                raise ValueError("duplicate source ID")
            m[i] = x
        maps[name] = m
    bs, ss, gs, ts = (maps[n] for n in ("boundaries", "steps", "geometry_records", "trials"))
    if set(bs) != set(range(len(bs))) or bs[0].parent_step_id is not None or bs[0].set.time != origin:
        raise ValueError("missing original-anchor root")
    for b in bs.values():
        _type(b.set, light._s.J2ZonotopeSegmentDiagnostic, "boundary set")
        if type(b.authority_digest) is not str or b.authority_digest != authority:
            raise ValueError("foreign boundary authority")
        _time(b.set.time)
        if b.id and (type(b.parent_step_id) is not int or b.parent_step_id not in ss):
            raise ValueError("broken boundary ancestry")
    edges = []
    for s in ss.values():
        for n in ("parent_boundary_id", "endpoint_boundary_id", "trial_index", "pass_index"):
            _integer(getattr(s, n), n)
        _type(s.bridge, bool, "bridge")
        if not s.parent_boundary_id < s.endpoint_boundary_id or s.parent_boundary_id not in bs or s.endpoint_boundary_id not in bs:
            raise ValueError("non-rooted source step")
        if bs[s.endpoint_boundary_id].parent_step_id != s.id or s.trial_index not in ts or ts[s.trial_index].pass_index != s.pass_index:
            raise ValueError("inconsistent step/trial ancestry")
        _type(s.tube, light._s.J2ZonotopeSegmentCell, "whole tube")
        a, b = _time(s.tube.start_seconds), _time(s.tube.end_seconds)
        if not origin <= a < b <= end or bs[s.parent_boundary_id].set.time != a or bs[s.endpoint_boundary_id].set.time != b:
            raise ValueError("inconsistent step time domain")
        edges.append(SourceEdge(s.id, s.parent_boundary_id, s.endpoint_boundary_id,
                                s.trial_index, s.pass_index, s.bridge, a, b))
    if {s.endpoint_boundary_id for s in ss.values()} != set(bs)-{0}:
        raise ValueError("unconnected boundary")
    for g in gs.values():
        _type(g.cell, geometry.IntervalIlluminationCell, "geometry cell")
        if type(g.authority_digest) is not str or g.authority_digest != authority or type(g.step_id) is not int or g.step_id not in ss:
            raise ValueError("foreign geometry support")
        s = ss[g.step_id]
        _integer(g.trial_index, "geometry trial")
        _integer(g.pass_index, "geometry pass")
        if (g.trial_index, g.pass_index) != (s.trial_index, s.pass_index):
            raise ValueError("foreign geometry trial")
        if not s.tube.start_seconds <= _time(g.cell.start_seconds) <= _time(g.cell.end_seconds) <= s.tube.end_seconds:
            raise ValueError("geometry outside whole source tube")
    supports = []
    previous = origin
    for p in source.pieces:
        _type(p, light.LocalPiece, "piece")
        if p.endpoint_convention != ENDPOINTS or type(p.assessment) is not str or p.assessment not in ASSESSMENTS:
            raise ValueError("unsupported partition convention/classification")
        _text(p.reason, "source reason")
        if _time(p.start_seconds) != previous or _time(p.end_seconds) <= p.start_seconds:
            raise ValueError("source partition has gap/overlap/order error")
        _integer(p.geometry_record_id, "geometry reference")
        if p.geometry_record_id not in gs:
            raise ValueError("missing geometry support")
        g = gs[p.geometry_record_id]
        if not g.cell.start_seconds <= p.start_seconds < p.end_seconds <= g.cell.end_seconds or (p.assessment, p.reason) != (g.cell.assessment, g.cell.reason):
            raise ValueError("partition contradicts whole support")
        s = ss[g.step_id]
        _integer(g.trial_index, "geometry trial")
        _integer(g.pass_index, "geometry pass")
        supports.append(SourceSupport(p, g, s.id, s.parent_boundary_id, s.endpoint_boundary_id))
        previous = p.end_seconds
    if previous != end:
        raise ValueError("source does not cover original requested domain")
    flat = []
    for w in source.windows:
        _type(w, light.LocalWindow, "window")
        if type(w.assessment) is not str or w.assessment not in ASSESSMENTS or type(w.reasons) is not tuple or any(type(x) is not str for x in w.reasons):
            raise ValueError("invalid window classification/reasons")
        if len(w.supports) > len(source.pieces) or len(flat)+len(w.supports) > len(source.pieces):
            raise ValueError("window support count exceeded")
        if w.endpoint_convention != ENDPOINTS or type(w.supports) is not tuple or not w.supports:
            raise ValueError("invalid window supports")
        if w.start_seconds != w.supports[0].start_seconds or w.end_seconds != w.supports[-1].end_seconds or any(p.assessment != w.assessment for p in w.supports):
            raise ValueError("inconsistent windows")
        flat.extend(w.supports)
    if tuple(flat) != source.pieces:
        raise ValueError("windows do not preserve partition supports")
    return digest, authority, origin, end, tuple(edges), tuple(supports)


def _case(entry, sunlit):
    nodes = sorted(entry.nodes, key=lambda n: n.node_id.canonical)
    loads = PowerLoadBreakdown(**{n: getattr(entry.loads, n) for n in LOAD_FIELDS})
    return ForcingInputCase(sunlit, EPSIntervalInputs(sunlit, entry.incidence_angle_deg, loads),
        ThermalIntervalInputs(tuple(ThermalNodeBoundaryInput(n.node_id, n.sink_temperature_k) for n in nodes)),
        ThermalHeatSourceInputs(tuple(ThermalNodeHeatSourceInput(n.node_id, n.internal_dissipation_w,
            n.illuminated_solar_w if sunlit else 0, n.absorbed_albedo_w, n.absorbed_earth_ir_w) for n in nodes)))


def adapt_environment_forcing(source, request):
    """Validate the whole trusted source before publishing any derived schedule."""
    _type(request, EnvironmentForcingRequest, "forcing request")
    request = EnvironmentForcingRequest(request.source_request, request.start_seconds,
        request.end_seconds, request.node_ids, request.profile, request.policy)
    digest, authority, origin, end, edges, supports = _source(source, request)
    a, b = request.start_seconds, request.end_seconds
    points = sorted({a, b} | {x for s in supports for x in (s.piece.start_seconds, s.piece.end_seconds) if a < x < b}
                    | {x for e in request.profile for x in (e.start_seconds, e.end_seconds) if a < x < b})
    if max(1, len(points)-1) > request.policy.max_cells:
        raise ValueError("forcing cell admission exceeded")
    intervals = [(a, b)] if a == b else list(zip(points, points[1:]))
    cells = []
    si = pi = 0
    for left, right in intervals:
        while si+1 < len(supports) and supports[si].piece.end_seconds <= left:
            si += 1
        while pi+1 < len(request.profile) and request.profile[pi].end_seconds <= left:
            pi += 1
        p = supports[si].piece
        if not p.start_seconds <= left <= right <= p.end_seconds:
            raise ValueError("forcing interval not supported")
        e = request.profile[pi]
        cases = (_case(e, True), _case(e, False)) if p.assessment == "UNRESOLVED" else (_case(e, p.assessment == "ILLUMINATED"),)
        if right > left:
            checked_duration(RationalSeconds.from_fraction(right-left))
        cells.append(EnvironmentForcingCell(left, right, p.assessment, si, pi, cases))
    # Identity of the exact partition and caller parameters; not a new certificate.
    from .environment_forcing_document import environment_forcing_digest
    identity = dict(request=environment_forcing_digest(request), authority=authority,
                    source=[(str(s.piece.start_seconds), str(s.piece.end_seconds), s.piece.assessment,
                             s.piece.reason, s.geometry.id, s.step_id) for s in supports],
                    ancestry=[(e.step_id, e.parent_boundary_id, e.endpoint_boundary_id,
                               e.trial_index, e.pass_index, e.bridge, str(e.start_seconds), str(e.end_seconds)) for e in edges],
                    cells=[(str(c.start_seconds), str(c.end_seconds), c.support_index, c.profile_index) for c in cells])
    cid = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return EnvironmentForcingSchedule(request, digest, authority, origin, end, edges, supports, tuple(cells), cid)
