"""Deterministic synthetic debris-severity and impact-zone assessment.

The values produced here are transparent experiment proxies.  They are not
collision probabilities, conjunction screening, orbit determination, or
physical debris-impact predictions.  Stable SHA-256 bytes provide repeatable
variation without relying on Python's process-randomized ``hash()``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256

from .event_catalog import ExternalEvent


class DebrisRiskClass(str, Enum):
    NEGLIGIBLE = "negligible"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SEVERE = "severe"


class DebrisImpactZone(str, Enum):
    SOLAR_ARRAY = "solar_array"
    COMMS_ANTENNA = "comms_antenna"
    ADCS = "adcs"
    THERMAL_CONTROL = "thermal_control"
    PAYLOAD_APERTURE = "payload_aperture"
    OBC = "obc"
    PROPULSION = "propulsion"
    BUS_STRUCTURE = "bus_structure"


class DebrisRecommendedResponse(str, Enum):
    MONITOR = "monitor"
    PREPARE_COMMAND = "prepare_command"
    AVOIDANCE_RECOMMENDED = "avoidance_recommended"
    AVOIDANCE_REQUIRED = "avoidance_required"


DEBRIS_RISK_MODELS = ("legacy", "severity_proxy")

IMPACT_ZONE_DAMAGE_TARGETS: dict[DebrisImpactZone, tuple[str, ...]] = {
    DebrisImpactZone.SOLAR_ARRAY: ("solar_health",),
    DebrisImpactZone.COMMS_ANTENNA: ("comms_health",),
    DebrisImpactZone.ADCS: ("adcs_health",),
    DebrisImpactZone.THERMAL_CONTROL: ("thermal_health",),
    DebrisImpactZone.PAYLOAD_APERTURE: ("payload_health",),
    DebrisImpactZone.OBC: ("obc_health",),
    DebrisImpactZone.PROPULSION: ("propulsion_health",),
    DebrisImpactZone.BUS_STRUCTURE: (
        "adcs_health",
        "thermal_health",
        "obc_health",
    ),
}

MAXIMUM_PROXY_DAMAGE_EFFECT = 0.25


@dataclass(frozen=True)
class DebrisRiskAssessment:
    """One repeatable, synthetic characterization of a debris catalog event."""

    event_id: str | None
    source_event_hour: int
    object_size_cm: float
    relative_velocity_km_s: float
    miss_distance_proxy_m: float
    warning_confidence: float
    risk_score: float
    risk_class: str
    impact_zone: str
    damage_targets: tuple[str, ...]
    damage_effect: float
    recommended_response: str
    notes: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _canonical_event(event: ExternalEvent, event_id: str | None) -> str:
    return "|".join((
        event_id or "",
        str(event.hour),
        event.event_type,
        format(event.severity, ".17g"),
        str(event.duration_hours),
        event.target,
        format(event.effect, ".17g"),
        event.description,
    ))


def _unit_interval(chunk: bytes) -> float:
    integer = int.from_bytes(chunk, "big", signed=False)
    maximum = (1 << (8 * len(chunk))) - 1
    return integer / maximum


def _risk_class(score: float) -> DebrisRiskClass:
    if score < 0.15:
        return DebrisRiskClass.NEGLIGIBLE
    if score < 0.35:
        return DebrisRiskClass.LOW
    if score < 0.60:
        return DebrisRiskClass.MODERATE
    if score < 0.80:
        return DebrisRiskClass.HIGH
    return DebrisRiskClass.SEVERE


def _recommended_response(score: float) -> DebrisRecommendedResponse:
    if score < 0.25:
        return DebrisRecommendedResponse.MONITOR
    if score < 0.50:
        return DebrisRecommendedResponse.PREPARE_COMMAND
    if score < 0.75:
        return DebrisRecommendedResponse.AVOIDANCE_RECOMMENDED
    return DebrisRecommendedResponse.AVOIDANCE_REQUIRED


def assess_debris_risk(
    event: ExternalEvent,
    event_id: str | None = None,
) -> DebrisRiskAssessment:
    """Build a stable proxy assessment from an external debris event.

    The catalog's severity and effect are retained as explicit inputs.  Hash
    bytes add deterministic variation for otherwise absent size, velocity,
    distance, and impact-zone fields.  No returned value is calibrated to a
    real object, collision probability, or KazEOSat-1 conjunction.
    """

    if event.event_type.lower() != "debris_conjunction":
        raise ValueError(
            "Debris risk assessment requires event_type "
            "'debris_conjunction'"
        )
    digest = sha256(
        _canonical_event(event, event_id).encode("utf-8")
    ).digest()
    size_unit = _unit_interval(digest[0:8])
    velocity_unit = _unit_interval(digest[8:16])
    distance_unit = _unit_interval(digest[16:24])
    confidence_unit = _unit_interval(digest[24:28])
    zone_index = int.from_bytes(digest[28:32], "big") % len(DebrisImpactZone)

    severity = _clamp(float(event.severity))
    effect_fraction = _clamp(
        max(0.0, float(event.effect)) / MAXIMUM_PROXY_DAMAGE_EFFECT
    )
    object_size_cm = 0.1 + 19.9 * size_unit
    relative_velocity_km_s = 5.0 + 10.0 * velocity_unit
    miss_distance_proxy_m = 10.0 + 4990.0 * distance_unit
    proximity = 1.0 - (miss_distance_proxy_m - 10.0) / 4990.0
    size_fraction = (object_size_cm - 0.1) / 19.9
    velocity_fraction = (relative_velocity_km_s - 5.0) / 10.0
    warning_confidence = _clamp(
        0.30 + 0.50 * severity + 0.20 * confidence_unit
    )
    risk_score = _clamp(
        0.35 * severity
        + 0.20 * effect_fraction
        + 0.15 * size_fraction
        + 0.15 * velocity_fraction
        + 0.15 * proximity
    )

    impact_zone = tuple(DebrisImpactZone)[zone_index]
    damage_targets = IMPACT_ZONE_DAMAGE_TARGETS[impact_zone]
    # The event effect remains the base magnitude; assessed risk scales it by
    # 0.5..1.5 and a hard cap keeps this stress proxy explicitly bounded.
    damage_effect = _clamp(
        max(0.0, float(event.effect)) * (0.5 + risk_score),
        upper=MAXIMUM_PROXY_DAMAGE_EFFECT,
    )
    risk_class = _risk_class(risk_score)
    response = _recommended_response(risk_score)
    return DebrisRiskAssessment(
        event_id=event_id,
        source_event_hour=event.hour,
        object_size_cm=object_size_cm,
        relative_velocity_km_s=relative_velocity_km_s,
        miss_distance_proxy_m=miss_distance_proxy_m,
        warning_confidence=warning_confidence,
        risk_score=risk_score,
        risk_class=risk_class.value,
        impact_zone=impact_zone.value,
        damage_targets=damage_targets,
        damage_effect=damage_effect,
        recommended_response=response.value,
        notes=(
            "Synthetic deterministic proxy; risk_score is not collision "
            "probability and geometry fields are not measured values."
        ),
    )


__all__ = [
    "DEBRIS_RISK_MODELS",
    "IMPACT_ZONE_DAMAGE_TARGETS",
    "MAXIMUM_PROXY_DAMAGE_EFFECT",
    "DebrisImpactZone",
    "DebrisRecommendedResponse",
    "DebrisRiskAssessment",
    "DebrisRiskClass",
    "assess_debris_risk",
]
