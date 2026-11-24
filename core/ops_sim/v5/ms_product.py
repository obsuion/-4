"""Task 05A version-1 MS product, exact grid sizing and delivery credit.

Declared rectangular coverage/sample cells, not detector pixels or image quality.
Schema-5 custody records retain their historical float representation; the new
manifest owns exact integer sizing and its provenance, bounded to 2**40 bits.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import ceil, isfinite

from .continuation import _exact, _label
from .ids import AcquisitionDataRecordId
from .observation import ImagingRequest
from .onboard_data import OnboardAcquisitionDataRecord
from .payload import OpticalAcquisitionChannelSelection


REQUIRED_MS_CHANNELS = ("B", "G", "R", "NIR")


def _version(value, expected=1):
    _exact(value, int, "version")
    if value != expected:
        raise ValueError("unsupported MS contract version")


def _positive(value):
    if type(value) not in (int, float) or value <= 0 or (type(value) is float and not isfinite(value)):
        raise ValueError("expected finite positive built-in quantity")
    return Fraction(value)


def _time(value):
    _exact(value, int, "time")
    if not 0 <= value <= 2**40:
        raise ValueError("time outside bounded domain")


def _channels(values):
    _exact(values, tuple, "channels")
    if not 1 <= len(values) <= 32:
        raise ValueError("channels must be nonempty and bounded")
    for value in values:
        _label(value, "spectral channel identity")
        if value.upper() == "PAN":
            raise ValueError("PAN is outside the MS product contract")
    if len(set(values)) != len(values):
        raise ValueError("duplicate spectral channel")


@dataclass(frozen=True, slots=True)
class MSFootprint:
    region_id: str
    width_m: float
    length_m: float

    def __post_init__(self):
        _label(self.region_id, "declared footprint identity")
        _positive(self.width_m)
        _positive(self.length_m)


@dataclass(frozen=True, slots=True)
class MSGridSizing:
    version: int
    footprint: MSFootprint
    spacing_x_m: float
    spacing_y_m: float
    captured_channels: tuple[str, ...]
    bits_per_sample: int
    nx: int
    ny: int
    stored_bits: int

    def __post_init__(self):
        _version(self.version)
        _exact(self.footprint, MSFootprint, "footprint")
        self.footprint.__post_init__()
        _channels(self.captured_channels)
        for n in ("bits_per_sample", "nx", "ny", "stored_bits"):
            _exact(getattr(self, n), int, n)
            if not 1 <= getattr(self, n) <= 2**40:
                raise ValueError("integer sizing exceeds contact/storage domain")
        nx = ceil(_positive(self.footprint.width_m) / _positive(self.spacing_x_m))
        ny = ceil(_positive(self.footprint.length_m) / _positive(self.spacing_y_m))
        if (self.nx, self.ny, self.stored_bits) != (
                nx, ny, nx * ny * len(self.captured_channels) * self.bits_per_sample):
            raise ValueError("grid counts/bits disagree with exact ceiling convention")


def size_ms_grid(footprint, spacing_x_m, spacing_y_m, channels, bits_per_sample):
    _exact(footprint, MSFootprint, "footprint")
    footprint.__post_init__()
    _channels(channels)
    _exact(bits_per_sample, int, "bits per sample")
    nx = ceil(_positive(footprint.width_m) / _positive(spacing_x_m))
    ny = ceil(_positive(footprint.length_m) / _positive(spacing_y_m))
    return MSGridSizing(1, footprint, spacing_x_m, spacing_y_m, channels,
                        bits_per_sample, nx, ny, nx * ny * len(channels) * bits_per_sample)


@dataclass(frozen=True, slots=True)
class MSProductSpec:
    version: int
    request: ImagingRequest
    capture_group: str
    required_channels: tuple[str, ...]
    footprint: MSFootprint
    acquisition_start_seconds: int
    acquisition_end_seconds: int
    maximum_spacing_x_m: float
    maximum_spacing_y_m: float
    delivery_deadline_seconds: int

    def __post_init__(self):
        _version(self.version)
        _exact(self.request, ImagingRequest, "request")
        self.request.__post_init__()
        _label(self.capture_group, "capture group")
        _channels(self.required_channels)
        if self.required_channels != REQUIRED_MS_CHANNELS:
            raise ValueError("version 1 requires the common B/G/R/NIR product")
        _exact(self.footprint, MSFootprint, "footprint")
        self.footprint.__post_init__()
        for t in (self.acquisition_start_seconds, self.acquisition_end_seconds, self.delivery_deadline_seconds):
            _time(t)
        if not self.acquisition_start_seconds < self.acquisition_end_seconds <= self.delivery_deadline_seconds:
            raise ValueError("invalid acquisition window/deadline")
        _positive(self.maximum_spacing_x_m)
        _positive(self.maximum_spacing_y_m)


@dataclass(frozen=True, slots=True)
class MSAcquisitionPlan:
    version: int
    request: ImagingRequest
    capture_group: str
    sizing: MSGridSizing
    capability_rationale: str

    def __post_init__(self):
        _version(self.version)
        _exact(self.request, ImagingRequest, "request")
        self.request.__post_init__()
        _label(self.capture_group, "capture group")
        _exact(self.sizing, MSGridSizing, "sizing")
        self.sizing.__post_init__()
        _label(self.capability_rationale, "explicit MS-only capability and spectral provenance")


@dataclass(frozen=True, slots=True)
class MSAcquisitionEvidence:
    record: OnboardAcquisitionDataRecord
    plan: MSAcquisitionPlan

    def __post_init__(self):
        _exact(self.record, OnboardAcquisitionDataRecord, "record")
        _exact(self.plan, MSAcquisitionPlan, "acquisition plan")
        self.record.__post_init__()
        self.plan.__post_init__()
        if (self.record.imaging_request_id != self.plan.request.request_id
                or self.record.channel_selection is not OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY
                or self.record.stored_equivalent_bits != self.plan.sizing.stored_bits):
            raise ValueError("record and integer MS acquisition association disagree")


@dataclass(frozen=True, slots=True)
class MSProductAssessment:
    status: str
    reasons: tuple[str, ...]
    credited_record_ids: tuple[AcquisitionDataRecordId, ...]
    completion_time_seconds: Fraction | None

    def __post_init__(self):
        _exact(self.status, str, "status")
        if self.status not in ("pending", "expired", "credited"):
            raise ValueError("unknown product status")
        _exact(self.reasons, tuple, "reasons")
        for r in self.reasons:
            _label(r, "reason")
        _exact(self.credited_record_ids, tuple, "credited records")
        for r in self.credited_record_ids:
            _exact(r, AcquisitionDataRecordId, "record identity")
        if len(set(self.credited_record_ids)) != len(self.credited_record_ids):
            raise ValueError("duplicate credit record")
        if self.status == "credited":
            _exact(self.completion_time_seconds, Fraction, "exact completion")
            if self.completion_time_seconds < 0 or not self.credited_record_ids or self.reasons:
                raise ValueError("invalid credit evidence")
        elif self.completion_time_seconds is not None or self.credited_record_ids or not self.reasons:
            raise ValueError("unearned product cannot carry credit")

    @property
    def credited_products(self):
        return int(self.status == "credited")


def assess_ms_product(product, acquisitions, delivery, contact_outcomes, now_seconds):
    """Idempotent projection of actual custody + completing RecordService evidence.

    Trusted execution provenance is established by the version-6 replay owner;
    this pure assessment also rejects mismatched/missing completion associations.
    Multiple records can combine only at the SAME acquisition time and footprint.
    """
    from .experiment_codec import canonical_copy, canonical_content
    from .contact_execution import ContactOutcome
    from .data_delivery import GroundDataDeliveryState
    _exact(product, MSProductSpec, "product")
    _exact(acquisitions, tuple, "acquisitions")
    _exact(contact_outcomes, tuple, "contact outcomes")
    _exact(delivery, GroundDataDeliveryState, "custody")
    _time(now_seconds)
    product, acquisitions, contact_outcomes = canonical_copy((product, acquisitions, contact_outcomes))
    delivery.__post_init__()
    acquired = {}
    for e in acquisitions:
        _exact(e, MSAcquisitionEvidence, "acquisition evidence")
        if e.record.record_id in acquired:
            raise ValueError("duplicate acquisition identity")
        acquired[e.record.record_id] = e
    completed = {d.record.record_id: d for d in delivery.completed_deliveries}
    times = {}
    for out in contact_outcomes:
        _exact(out, ContactOutcome, "contact outcome")
        if out.contact.end_time_seconds > now_seconds:
            raise ValueError("future service cannot credit a product")
        for service in out.services:
            if not service.completed:
                continue
            rid = service.record.record_id
            if rid in times:
                raise ValueError("duplicate completing service")
            d = completed.get(rid)
            if d is None or canonical_content((d.record, d.completing_contact)) != canonical_content((service.record, out.contact)):
                raise ValueError("completing service does not match delivered custody")
            times[rid] = Fraction(out.contact.start_time_seconds) + service.end_offset.fraction
    groups = {}
    reasons = []
    for rid, e in acquired.items():
        p, record = e.plan, e.record
        failed = []
        if p.request.request_id != product.request.request_id: failed.append("wrong-request")
        if p.request.target_id != product.request.target_id: failed.append("wrong-target")
        if p.capture_group != product.capture_group: failed.append("incompatible-capture-group")
        if p.sizing.footprint != product.footprint: failed.append("incompatible-footprint")
        if not (product.acquisition_start_seconds <= record.scheduled_start_seconds
                and record.scheduled_start_seconds + record.acquisition_duration_seconds <= product.acquisition_end_seconds):
            failed.append("outside-acquisition-window")
        if p.sizing.spacing_x_m > product.maximum_spacing_x_m or p.sizing.spacing_y_m > product.maximum_spacing_y_m:
            failed.append("sampling-criterion-failed")
        if rid not in completed: failed.append("not-delivered")
        elif canonical_content(completed[rid].record) != canonical_content(record):
            raise ValueError("delivered record differs from acquisition evidence")
        elif rid not in times: failed.append("missing-completion-service")
        elif times[rid] > product.delivery_deadline_seconds: failed.append("late-delivery")
        if failed:
            reasons.extend(failed)
            continue
        key = (record.scheduled_start_seconds, record.acquisition_duration_seconds)
        groups.setdefault(key, []).append((times[rid], rid, p.sizing.captured_channels))
    candidates = []
    for values in groups.values():
        channels, records = set(), []
        for instant, rid, captured in sorted(values, key=lambda x: (x[0], x[1].value)):
            channels.update(captured)
            records.append(rid)
            if set(product.required_channels) <= channels:
                candidates.append((instant, tuple(records)))
                break
    if candidates:
        instant, records = min(candidates, key=lambda x: (x[0], tuple(r.value for r in x[1])))
        return MSProductAssessment("credited", (), records, instant)
    if len(groups) > 1: reasons.append("incompatible-capture-time")
    reasons.append("missing-required-channels" if groups else "no-eligible-delivered-capture")
    if now_seconds >= product.delivery_deadline_seconds: reasons.append("delivery-deadline-expired")
    return MSProductAssessment("expired" if now_seconds >= product.delivery_deadline_seconds else "pending",
                               tuple(dict.fromkeys(reasons)), (), None)
