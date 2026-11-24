"""Immutable V5 mission targets and explicit observation opportunities."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real

from .ids import (
    GroundTargetId,
    ImagingRequestId,
    ObservationOpportunityId,
)


def _normalized_real(name: str, value: object) -> int | float:
    """Return an admitted finite Real as a safe built-in scalar."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = bool(isfinite(value))
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} must be finite") from error
    if not finite:
        raise ValueError(f"{name} must be finite")

    try:
        normalized = int(value) if isinstance(value, Integral) else float(value)
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if type(normalized) not in {int, float}:
        raise ValueError(f"{name} must normalize to a built-in number")
    try:
        normalized_finite = bool(isfinite(normalized))
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if not normalized_finite:
        raise ValueError(f"{name} cannot be represented as a finite number")
    return normalized


def _validate_item_tuple(
    name: str,
    value: object,
    expected_type: type,
    id_attribute: str,
) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    if not all(type(item) is expected_type for item in value):
        raise TypeError(
            f"{name} must contain only {expected_type.__name__} values"
        )
    identifiers = tuple(getattr(item, id_attribute) for item in value)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{name} IDs must be unique")


@dataclass(frozen=True, slots=True)
class GroundTarget:
    """A geographic mission target without visibility or feasibility state."""

    target_id: GroundTargetId
    latitude_deg: float
    longitude_deg: float

    def __post_init__(self) -> None:
        if type(self.target_id) is not GroundTargetId:
            raise TypeError("target_id must be a GroundTargetId")
        latitude = _normalized_real("latitude_deg", self.latitude_deg)
        longitude = _normalized_real("longitude_deg", self.longitude_deg)
        if not -90 <= latitude <= 90:
            raise ValueError("latitude_deg must be between -90 and 90 degrees")
        if not -180 <= longitude < 180:
            raise ValueError(
                "longitude_deg must be at least -180 and less than 180 degrees"
            )


@dataclass(frozen=True, slots=True)
class ImagingRequest:
    """A weighted mission request to observe one geographic target."""

    request_id: ImagingRequestId
    target_id: GroundTargetId
    priority_weight: float

    def __post_init__(self) -> None:
        if type(self.request_id) is not ImagingRequestId:
            raise TypeError("request_id must be an ImagingRequestId")
        if type(self.target_id) is not GroundTargetId:
            raise TypeError("target_id must be a GroundTargetId")
        priority = _normalized_real("priority_weight", self.priority_weight)
        if priority <= 0:
            raise ValueError("priority_weight must be greater than zero")


@dataclass(frozen=True, slots=True)
class ObservationPointing:
    """An abstract local-orbital viewing direction for one candidate.

    Azimuth has no north, east, or velocity-frame realization in V5.3A. The
    view angle is spacecraft-local and is not a surface incidence angle.
    """

    view_angle_from_nadir_deg: float
    view_azimuth_deg: float

    def __post_init__(self) -> None:
        view_angle = _normalized_real(
            "view_angle_from_nadir_deg",
            self.view_angle_from_nadir_deg,
        )
        azimuth = _normalized_real("view_azimuth_deg", self.view_azimuth_deg)
        if not 0 <= view_angle < 90:
            raise ValueError(
                "view_angle_from_nadir_deg must be at least zero and less "
                "than 90 degrees"
            )
        if not 0 <= azimuth < 360:
            raise ValueError(
                "view_azimuth_deg must be at least zero and less than 360 "
                "degrees"
            )


@dataclass(frozen=True, slots=True)
class ObservationOpportunity:
    """An explicit geometric/tasking window, not a feasibility decision."""

    opportunity_id: ObservationOpportunityId
    request_id: ImagingRequestId
    window_start_seconds: int
    window_end_seconds: int
    imaging_duration_seconds: int
    pointing: ObservationPointing

    def __post_init__(self) -> None:
        if type(self.opportunity_id) is not ObservationOpportunityId:
            raise TypeError(
                "opportunity_id must be an ObservationOpportunityId"
            )
        if type(self.request_id) is not ImagingRequestId:
            raise TypeError("request_id must be an ImagingRequestId")
        for name, value in (
            ("window_start_seconds", self.window_start_seconds),
            ("window_end_seconds", self.window_end_seconds),
            ("imaging_duration_seconds", self.imaging_duration_seconds),
        ):
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
        if self.window_start_seconds < 0:
            raise ValueError(
                "window_start_seconds must be greater than or equal to zero"
            )
        if self.window_end_seconds < 0:
            raise ValueError(
                "window_end_seconds must be greater than or equal to zero"
            )
        if self.window_end_seconds <= self.window_start_seconds:
            raise ValueError(
                "window_end_seconds must be greater than window_start_seconds"
            )
        if self.imaging_duration_seconds <= 0:
            raise ValueError("imaging_duration_seconds must be greater than zero")
        if self.imaging_duration_seconds > (
            self.window_end_seconds - self.window_start_seconds
        ):
            raise ValueError(
                "imaging_duration_seconds must fit inside the opportunity window"
            )
        if type(self.pointing) is not ObservationPointing:
            raise TypeError("pointing must be an ObservationPointing")
        ObservationPointing(
            self.pointing.view_angle_from_nadir_deg,
            self.pointing.view_azimuth_deg,
        )


@dataclass(frozen=True, slots=True)
class TargetCatalog:
    """An unordered immutable collection of uniquely identified targets."""

    targets: tuple[GroundTarget, ...]

    def __post_init__(self) -> None:
        _validate_item_tuple("targets", self.targets, GroundTarget, "target_id")
        for target in self.targets:
            GroundTarget(target.target_id, target.latitude_deg, target.longitude_deg)


@dataclass(frozen=True, slots=True)
class ImagingRequestCatalog:
    """An unordered immutable collection of uniquely identified requests."""

    requests: tuple[ImagingRequest, ...]

    def __post_init__(self) -> None:
        _validate_item_tuple(
            "requests",
            self.requests,
            ImagingRequest,
            "request_id",
        )
        for request in self.requests:
            ImagingRequest(
                request.request_id,
                request.target_id,
                request.priority_weight,
            )


@dataclass(frozen=True, slots=True)
class ObservationOpportunityCatalog:
    """An unordered immutable collection of unique candidate opportunities."""

    opportunities: tuple[ObservationOpportunity, ...]

    def __post_init__(self) -> None:
        _validate_item_tuple(
            "opportunities",
            self.opportunities,
            ObservationOpportunity,
            "opportunity_id",
        )
        for opportunity in self.opportunities:
            ObservationOpportunity(
                opportunity.opportunity_id,
                opportunity.request_id,
                opportunity.window_start_seconds,
                opportunity.window_end_seconds,
                opportunity.imaging_duration_seconds,
                opportunity.pointing,
            )


@dataclass(frozen=True, slots=True)
class ObservationCampaign:
    """A coherent target, request, and explicit-opportunity input bundle."""

    targets: TargetCatalog
    requests: ImagingRequestCatalog
    opportunities: ObservationOpportunityCatalog

    def __post_init__(self) -> None:
        if type(self.targets) is not TargetCatalog:
            raise TypeError("targets must be a TargetCatalog")
        if type(self.requests) is not ImagingRequestCatalog:
            raise TypeError("requests must be an ImagingRequestCatalog")
        if type(self.opportunities) is not ObservationOpportunityCatalog:
            raise TypeError(
                "opportunities must be an ObservationOpportunityCatalog"
            )
        TargetCatalog(self.targets.targets)
        ImagingRequestCatalog(self.requests.requests)
        ObservationOpportunityCatalog(self.opportunities.opportunities)

        target_ids = {target.target_id for target in self.targets.targets}
        if any(
            request.target_id not in target_ids
            for request in self.requests.requests
        ):
            raise ValueError("every request target_id must exist in targets")
        request_ids = {
            request.request_id for request in self.requests.requests
        }
        if any(
            opportunity.request_id not in request_ids
            for opportunity in self.opportunities.opportunities
        ):
            raise ValueError(
                "every opportunity request_id must exist in requests"
            )


__all__ = [
    "GroundTarget",
    "ImagingRequest",
    "ImagingRequestCatalog",
    "ObservationCampaign",
    "ObservationOpportunity",
    "ObservationOpportunityCatalog",
    "ObservationPointing",
    "TargetCatalog",
]
