"""Offline, immutable TT geocentric Sun tables; no network or propagation cache."""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from math import isfinite

from .experiment_codec import canonical_copy
from .frames import CartesianDirection, CartesianPosition, CartesianState
from .ids import SourceRecordId
from .orbit_binding import CoastOrbitInputs
from .orbit_config import FrameDefinition, FrameKind, GeometryInstant, TTEpoch, _exact, _real
from .orbit_j2_binding import J2CoastOrbitInputs
from .orbit_j2_enclosure import J2EnclosureResult
from .orbit_sun import OrbitSunQuery, OrbitSunResult, SuppliedSunDirection, _evaluate_coast_at, _result, _text


def _number(value, name):
    if type(value) not in (int, float):
        raise TypeError(name+" requires a built-in real number")
    return _real(name, value)


def _triple(value):
    _exact(value, tuple, "position")
    if len(value) != 3:
        raise ValueError("position requires three components in metres")
    result = tuple(_number(x, "position_m") for x in value)
    if not any(result):
        raise ValueError("geocentric Sun position must be nonzero")
    return result


def _hash(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("source hash requires lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class SunTableProvenance:
    source_kind: str
    target: str
    center: str
    axes: str
    reference_plane: str
    correction: str
    source_timescale: str
    source_units: str
    conversion: str
    alignment: str
    source_ids: tuple[SourceRecordId, ...]
    source_uri: str
    retrieved_utc: str | None
    request_sha256: str | None
    response_sha256: str | None
    ephemeris_id: str | None
    accuracy_policy: str
    accuracy_statement: str
    alignment_rationale: str

    def __post_init__(self):
        for name in ("source_kind", "target", "center", "axes", "reference_plane",
                     "correction", "source_timescale", "source_units", "conversion",
                     "alignment", "source_uri", "accuracy_policy", "accuracy_statement",
                     "alignment_rationale"):
            _text(getattr(self, name), name)
        if (self.target, self.center, self.correction, self.source_timescale,
                self.accuracy_policy) != ("10", "500@399", "GEOMETRIC", "TT", "UNQUANTIFIED"):
            raise ValueError("unsupported Sun target/center/correction/time/accuracy metadata")
        if (self.source_units, self.conversion) not in (
                ("M", "IDENTITY_METRES"), ("KM", "EXACT_KM_TIMES_1000")):
            raise ValueError("unsupported source units/conversion")
        _exact(self.source_ids, tuple, "source_ids")
        sources = canonical_copy(self.source_ids)
        for source in sources:
            _exact(source, SourceRecordId, "source ID")
        if len(set(sources)) != len(sources):
            raise ValueError("duplicate source ID")
        if self.source_kind == "SYNTHETIC":
            if (self.axes, self.reference_plane, self.alignment) != (
                    "MODEL_INERTIAL", "MODEL_EQUATOR", "IDENTITY_MODEL"):
                raise ValueError("incompatible synthetic coordinate binding")
            if any(v is not None for v in (self.retrieved_utc, self.request_sha256,
                                          self.response_sha256, self.ephemeris_id)):
                raise ValueError("synthetic source must not fabricate retrieval evidence")
        elif self.source_kind == "HORIZONS":
            if (self.axes, self.reference_plane, self.alignment) != (
                    "ICRF", "FRAME", "ASSUMED_ICRF_MODEL_IDENTITY"):
                raise ValueError("incompatible Horizons coordinate binding")
            if not sources:
                raise ValueError("external source requires source IDs")
            _text(self.retrieved_utc, "retrieved_utc")
            when = datetime.fromisoformat(self.retrieved_utc)
            if when.tzinfo is None or when.utcoffset() != timezone.utc.utcoffset(when):
                raise ValueError("retrieval timestamp must declare UTC")
            _hash(self.request_sha256)
            _hash(self.response_sha256)
            _text(self.ephemeris_id, "ephemeris_id")
        else:
            raise ValueError("unsupported Sun source kind")
        object.__setattr__(self, "source_ids", sources)


def _provenance(p):
    _exact(p, SunTableProvenance, "provenance")
    # Fixed schema in sun_table_document; this only rebuilds this exact owner.
    return SunTableProvenance(**{name: getattr(p, name) for name in p.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class SunPositionSample:
    elapsed_seconds: float
    position_m: tuple[float, float, float]

    def __post_init__(self):
        object.__setattr__(self, "elapsed_seconds", _number(self.elapsed_seconds, "elapsed_seconds"))
        object.__setattr__(self, "position_m", _triple(self.position_m))


@dataclass(frozen=True, slots=True)
class SunPositionTable:
    epoch: TTEpoch
    frame: FrameDefinition
    domain_seconds: tuple[float, float]
    interpolation: str
    samples: tuple[SunPositionSample, ...]
    provenance: SunTableProvenance

    def __post_init__(self):
        _exact(self.epoch, TTEpoch, "epoch")
        _exact(self.frame, FrameDefinition, "frame")
        epoch, frame = canonical_copy((self.epoch, self.frame))
        if frame.kind is not FrameKind.MODEL_INERTIAL or frame.rotation.epoch != epoch:
            raise ValueError("table requires MODEL_INERTIAL bound to original TT epoch")
        _text(self.interpolation, "interpolation")
        if self.interpolation != "LINEAR_POSITION_V1":
            raise ValueError("unsupported interpolation policy")
        _exact(self.samples, tuple, "samples")
        if not 2 <= len(self.samples) <= 1024:
            raise ValueError("table requires 2..1024 samples")
        samples = []
        for sample in self.samples:
            _exact(sample, SunPositionSample, "sample")
            sample = SunPositionSample(sample.elapsed_seconds, sample.position_m)
            GeometryInstant(epoch, sample.elapsed_seconds)
            if samples and sample.elapsed_seconds <= samples[-1].elapsed_seconds:
                raise ValueError("sample times must be strictly increasing")
            samples.append(sample)
        _exact(self.domain_seconds, tuple, "domain_seconds")
        if len(self.domain_seconds) != 2:
            raise ValueError("closed domain requires two endpoints")
        domain = tuple(_number(x, "domain_seconds") for x in self.domain_seconds)
        if domain != (samples[0].elapsed_seconds, samples[-1].elapsed_seconds):
            raise ValueError("closed domain must match first/last samples")
        for name, value in (("epoch", epoch), ("frame", frame), ("domain_seconds", domain),
                            ("samples", tuple(samples)), ("provenance", _provenance(self.provenance))):
            object.__setattr__(self, name, value)


def _table(table):
    _exact(table, SunPositionTable, "table")
    return SunPositionTable(table.epoch, table.frame, table.domain_seconds,
                            table.interpolation, table.samples, table.provenance)


def evaluate_sun_position(table: SunPositionTable, instant: GeometryInstant) -> CartesianPosition:
    table = _table(table)
    _exact(instant, GeometryInstant, "instant")
    instant = canonical_copy(instant)
    if instant.epoch != table.epoch:
        raise ValueError("query must use original table TT epoch")
    t = instant.elapsed_seconds
    if not table.domain_seconds[0] <= t <= table.domain_seconds[1]:
        raise ValueError("Sun query outside closed table domain")
    times = tuple(s.elapsed_seconds for s in table.samples)
    i = bisect_right(times, t)-1
    left = table.samples[i]
    if t == left.elapsed_seconds:
        xyz = left.position_m
    else:
        right = table.samples[i+1]
        w = (Fraction(t)-Fraction(left.elapsed_seconds))/(Fraction(right.elapsed_seconds)-Fraction(left.elapsed_seconds))
        xyz = tuple(float((1-w)*Fraction(a)+w*Fraction(b))
                    for a,b in zip(left.position_m, right.position_m))
    return CartesianPosition(table.frame, instant, _triple(xyz))


@dataclass(frozen=True, slots=True)
class TableOrbitSunQuery:
    coast: CoastOrbitInputs | J2CoastOrbitInputs
    table: SunPositionTable
    instant: GeometryInstant

    def __post_init__(self):
        if type(self.coast) not in (CoastOrbitInputs, J2CoastOrbitInputs):
            raise TypeError("query requires accepted coast inputs")
        coast = canonical_copy(self.coast)
        table = _table(self.table)
        _exact(self.instant, GeometryInstant, "instant")
        instant = canonical_copy(self.instant)
        anchor = coast.trajectory.initial_state.position
        if anchor.frame != table.frame or anchor.instant.epoch != table.epoch:
            raise ValueError("orbit/table full frame or epoch mismatch")
        if instant.epoch != table.epoch:
            raise ValueError("query must use original TT epoch")
        if not table.domain_seconds[0] <= instant.elapsed_seconds <= table.domain_seconds[1]:
            raise ValueError("query outside closed table domain")
        object.__setattr__(self, "coast", coast)
        object.__setattr__(self, "table", table)
        object.__setattr__(self, "instant", instant)


@dataclass(frozen=True, slots=True)
class TableOrbitSunResult:
    query: TableOrbitSunQuery
    sun_position: CartesianPosition
    orbit_state: CartesianState | None
    spacecraft_to_sun_m: tuple[float, float, float] | None
    fixed_ray_assessment: OrbitSunResult | None
    j2_evidence: J2EnclosureResult | None
    combined_qualification: str
    combined_reasons: tuple[str, ...]


def evaluate_table_orbit_sun(query: TableOrbitSunQuery) -> TableOrbitSunResult:
    _exact(query, TableOrbitSunQuery, "query")
    query = TableOrbitSunQuery(query.coast, query.table, query.instant)
    sun = evaluate_sun_position(query.table, query.instant)
    state, evidence = _evaluate_coast_at(query.coast, query.instant)
    reasons = ("PROVIDER_EPHEMERIS_ERROR_UNQUANTIFIED", "INTERPOLATION_UNIFORM_ERROR_UNQUANTIFIED",
               "SOURCE_TIME_ERROR_UNQUANTIFIED", "FRAME_MAPPING_ERROR_UNQUANTIFIED",
               "SPACECRAFT_DEPENDENT_RAY_NOT_JOINTLY_ENCLOSED")
    displacement = conditional = None
    if state is None:
        reasons = ("J2_F3_UNRESOLVED: "+str(evidence.reason),)+reasons
    else:
        try:
            displacement = _triple(tuple(float(Fraction(s)-Fraction(r))
                                         for s,r in zip(sun.components_m, state.position.components_m)))
        except OverflowError as error:
            raise ValueError("spacecraft-to-Sun displacement exceeds finite binary64") from error
        p = query.table.provenance
        ray = SuppliedSunDirection(CartesianDirection(query.table.frame, query.instant, displacement),
             "SYNTHETIC" if p.source_kind=="SYNTHETIC" else "EXTERNALLY_SUPPLIED", p.source_ids,
             "Table-interpolated s(t)-r(t); fixed represented ray only; combined error UNRESOLVED")
        fixed = OrbitSunQuery(query.coast, query.instant, ray)
        conditional = _result(fixed, state, evidence)
    return TableOrbitSunResult(query, sun, state, displacement, conditional, evidence, "UNRESOLVED", reasons)


def evaluate_context_table_sun(context, table: SunPositionTable) -> TableOrbitSunResult:
    from .context import SimulationContext
    from .engine import _validate_completed_context

    _exact(context, SimulationContext, "context")
    _validate_completed_context(context)
    coast = context.inputs.coast_orbit
    if type(coast) not in (CoastOrbitInputs, J2CoastOrbitInputs):
        raise TypeError("context requires accepted coast inputs")
    epoch = coast.trajectory.initial_state.position.instant.epoch
    return evaluate_table_orbit_sun(TableOrbitSunQuery(
        coast, table, GeometryInstant(epoch, context.simulation_time_seconds)))
