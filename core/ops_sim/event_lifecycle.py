"""Deterministic debris-warning lifecycle and awareness bookkeeping.

This module separates external information available to the ground from a
response that has actually been uploaded to the spacecraft.  It deliberately
does not import or mutate :class:`~ops_sim.models.SatelliteState`; callers keep
spacecraft telemetry and lifecycle awareness as independent information
channels.

The lifecycle is an operational proxy, not conjunction assessment, collision
probability, or flight software.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
from math import isfinite
from typing import Iterable

from .config import DEFAULT_CONFIG
from .event_catalog import EventCatalog, ExternalEvent
from .models import ContactInfo


MINIMUM_CONJUNCTION_WARNING_LEAD_HOURS = 6
NOMINAL_CONJUNCTION_WARNING_LEAD_HOURS = 24
MAXIMUM_CONJUNCTION_WARNING_LEAD_HOURS = 72

# Lower-case aliases mirror the configuration-style names in the V3.2A model
# description while retaining conventional constant names for Python callers.
minimum_conjunction_warning_lead_hours = (
    MINIMUM_CONJUNCTION_WARNING_LEAD_HOURS
)
nominal_conjunction_warning_lead_hours = (
    NOMINAL_CONJUNCTION_WARNING_LEAD_HOURS
)
maximum_conjunction_warning_lead_hours = (
    MAXIMUM_CONJUNCTION_WARNING_LEAD_HOURS
)


class LifecycleStatus(str, Enum):
    """Possible states of one external-warning/response lifecycle."""

    SCHEDULED = "scheduled"
    WARNED = "warned"
    KNOWN_TO_GROUND = "known_to_ground"
    UPLINK_PENDING = "uplink_pending"
    UPLOADED_TO_SPACECRAFT = "uploaded_to_spacecraft"
    ACTIVE = "active"
    RESOLVED_SUCCESS = "resolved_success"
    RESOLVED_FAILED = "resolved_failed"
    EXPIRED = "expired"


LIFECYCLE_STATUSES = tuple(status.value for status in LifecycleStatus)


@dataclass
class LifecycleEvent:
    """Mutable lifecycle state linked to one external debris catalog event."""

    event_id: str
    event_type: str
    source_event_hour: int
    warning_hour: int
    ground_awareness_hour: int
    spacecraft_awareness_hour: int | None
    decision_deadline_hour: int
    execution_hour: int
    status: str
    severity: float
    confidence: float
    requires_command_upload: bool
    requires_maneuver: bool
    response_uploaded: bool
    response_upload_hour: int | None
    response_executed: bool
    response_skipped: bool
    failure_reason: str | None
    linked_external_event_hour: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LifecycleTransition:
    """One auditable change in a lifecycle event's status."""

    hour: int
    year: float
    event_id: str
    event_type: str
    previous_status: str
    new_status: str
    transition_reason: str
    ground_knows: bool
    spacecraft_knows: bool
    command_contact_min: float
    data_contact_min: float
    response_uploaded: bool
    response_executed: bool
    response_skipped: bool
    failure_reason: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LifecycleHourContext:
    """Policy-safe lifecycle facts exposed after one final-contact update.

    Only warned events appear in the awareness collections.  In particular,
    scheduled future events are absent, so passing this context onward cannot
    reveal a future conjunction before its warning hour.
    """

    hour: int
    ground_known_event_ids: tuple[str, ...]
    spacecraft_known_event_ids: tuple[str, ...]
    uploaded_event_ids: tuple[str, ...]
    upload_attempted_event_ids: tuple[str, ...]
    upload_delivery_failed_event_ids: tuple[str, ...]
    avoidance_eligible_event_ids: tuple[str, ...]
    upload_failed_event_ids: tuple[str, ...]
    transitions: tuple[LifecycleTransition, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LifecycleDiagnostics:
    """Compact read-only lifecycle awareness for one simulator hour.

    Upcoming fields are restricted to events already known to the ground.
    They therefore never reveal a scheduled conjunction before its warning.
    """

    lifecycle_ground_known_count: int = 0
    lifecycle_spacecraft_known_count: int = 0
    lifecycle_uploaded_count: int = 0
    lifecycle_pending_count: int = 0
    lifecycle_active_count: int = 0
    lifecycle_resolved_success_count: int = 0
    lifecycle_resolved_failed_count: int = 0
    lifecycle_missed_upload_count: int = 0
    lifecycle_next_warning_hour: int | None = None
    lifecycle_next_execution_hour: int | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def deterministic_warning_lead_hours(
    event_id: str,
    source_event_hour: int,
) -> int:
    """Return a stable warning lead in the inclusive 6..72 hour range."""
    if not event_id:
        raise ValueError("event_id must be non-empty")
    if (
        isinstance(source_event_hour, bool)
        or not isinstance(source_event_hour, int)
        or source_event_hour < 0
    ):
        raise ValueError("source_event_hour must be a non-negative integer")
    digest = sha256(
        f"{event_id}|{source_event_hour}".encode("utf-8")
    ).digest()
    stable_value = int.from_bytes(digest[:8], "big", signed=False)
    span = (
        MAXIMUM_CONJUNCTION_WARNING_LEAD_HOURS
        - MINIMUM_CONJUNCTION_WARNING_LEAD_HOURS
        + 1
    )
    return MINIMUM_CONJUNCTION_WARNING_LEAD_HOURS + stable_value % span


def _stable_event_id(event: ExternalEvent, debris_ordinal: int) -> str:
    canonical = "|".join((
        str(event.hour),
        event.event_type,
        format(event.severity, ".17g"),
        str(event.duration_hours),
        event.target,
        format(event.effect, ".17g"),
        event.description,
        str(debris_ordinal),
    ))
    digest = sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"debris_conjunction_{event.hour}_{debris_ordinal}_{digest}"


class EventLifecycleManager:
    """Manage deterministic debris warning, upload, and TCA state.

    ``advance`` must receive the final, scenario-modified contact for an hour.
    It changes lifecycle awareness only: it never changes telemetry snapshots
    or satellite state.  Uploaded events become avoidance-eligible at TCA;
    callers then use ``resolve_avoidance`` to record the outcome of their
    existing maneuver/damage path.
    """

    def __init__(
        self,
        catalog: EventCatalog | Iterable[ExternalEvent],
        *,
        hours_per_year: int = DEFAULT_CONFIG.hours_per_year,
    ) -> None:
        if (
            isinstance(hours_per_year, bool)
            or not isinstance(hours_per_year, int)
            or hours_per_year <= 0
        ):
            raise ValueError("hours_per_year must be a positive integer")
        source_events = (
            catalog.events if isinstance(catalog, EventCatalog) else list(catalog)
        )
        self.hours_per_year = hours_per_year
        self.events: list[LifecycleEvent] = []
        self.transitions: list[LifecycleTransition] = []
        self.events_by_id: dict[str, LifecycleEvent] = {}
        self._source_events_by_id: dict[str, ExternalEvent] = {}
        self._source_identity_to_id: dict[int, str] = {}
        self._ground_known_ids: set[str] = set()
        self._spacecraft_known_ids: set[str] = set()
        self._last_advanced_hour: int | None = None
        self._last_contact = ContactInfo()

        debris_ordinal = 0
        for source_event in source_events:
            if source_event.event_type.lower() != "debris_conjunction":
                continue
            if (
                isinstance(source_event.hour, bool)
                or not isinstance(source_event.hour, int)
                or source_event.hour < 0
            ):
                raise ValueError(
                    "debris lifecycle source event hour must be a "
                    "non-negative integer"
                )
            event_id = _stable_event_id(source_event, debris_ordinal)
            lead_hours = deterministic_warning_lead_hours(
                event_id, source_event.hour
            )
            warning_hour = max(0, source_event.hour - lead_hours)
            deadline = (
                source_event.hour - 1
                if source_event.hour > 0
                else source_event.hour
            )
            # The external catalog has no separate warning-confidence input.
            # Reusing its clamped severity is an explicit, deterministic proxy.
            confidence = max(0.0, min(1.0, source_event.severity))
            lifecycle_event = LifecycleEvent(
                event_id=event_id,
                event_type=source_event.event_type,
                source_event_hour=source_event.hour,
                warning_hour=warning_hour,
                ground_awareness_hour=warning_hour,
                spacecraft_awareness_hour=None,
                decision_deadline_hour=deadline,
                execution_hour=source_event.hour,
                status=LifecycleStatus.SCHEDULED.value,
                severity=source_event.severity,
                confidence=confidence,
                requires_command_upload=True,
                requires_maneuver=True,
                response_uploaded=False,
                response_upload_hour=None,
                response_executed=False,
                response_skipped=False,
                failure_reason=None,
                linked_external_event_hour=source_event.hour,
            )
            self.events.append(lifecycle_event)
            self.events_by_id[event_id] = lifecycle_event
            self._source_events_by_id[event_id] = source_event
            self._source_identity_to_id[id(source_event)] = event_id
            debris_ordinal += 1

    @classmethod
    def from_catalog(
        cls,
        catalog: EventCatalog,
        *,
        hours_per_year: int = DEFAULT_CONFIG.hours_per_year,
    ) -> "EventLifecycleManager":
        return cls(catalog, hours_per_year=hours_per_year)

    @property
    def lifecycle_events(self) -> tuple[LifecycleEvent, ...]:
        return tuple(self.events)

    @property
    def ground_external_awareness(self) -> frozenset[str]:
        return frozenset(self._ground_known_ids)

    @property
    def spacecraft_awareness(self) -> frozenset[str]:
        return frozenset(self._spacecraft_known_ids)

    def get_event(self, event_id: str) -> LifecycleEvent:
        try:
            return self.events_by_id[event_id]
        except KeyError as exc:
            raise KeyError(f"Unknown lifecycle event_id {event_id!r}") from exc

    def source_event(self, event_id: str) -> ExternalEvent:
        self.get_event(event_id)
        return self._source_events_by_id[event_id]

    def event_id_for_source(self, source_event: ExternalEvent) -> str:
        identity_match = self._source_identity_to_id.get(id(source_event))
        if identity_match is not None:
            return identity_match
        matches = [
            event_id
            for event_id, candidate in self._source_events_by_id.items()
            if candidate == source_event
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise KeyError("External event is not managed by this lifecycle")
        raise ValueError(
            "External event matches multiple lifecycle entries; use event_id"
        )

    def lifecycle_event_for_source(
        self, source_event: ExternalEvent
    ) -> LifecycleEvent:
        return self.get_event(self.event_id_for_source(source_event))

    def events_at_execution_hour(
        self, hour: int
    ) -> tuple[LifecycleEvent, ...]:
        return tuple(event for event in self.events if event.execution_hour == hour)

    def is_avoidance_eligible(self, event_id: str, hour: int) -> bool:
        event = self.get_event(event_id)
        return (
            event.execution_hour == hour
            and event.response_uploaded
            and event.status == LifecycleStatus.ACTIVE.value
        )

    def diagnostics(
        self, current_hour: int | None = None
    ) -> LifecycleDiagnostics:
        """Summarize current awareness without mutating lifecycle state."""
        if current_hour is None:
            current_hour = self._last_advanced_hour
        elif (
            isinstance(current_hour, bool)
            or not isinstance(current_hour, int)
            or current_hour < 0
        ):
            raise ValueError("current_hour must be a non-negative integer")

        terminal_statuses = {
            LifecycleStatus.RESOLVED_SUCCESS.value,
            LifecycleStatus.RESOLVED_FAILED.value,
            LifecycleStatus.EXPIRED.value,
        }
        ground_known = self._ground_known_ids
        spacecraft_known = self._spacecraft_known_ids
        known_unresolved = [
            event
            for event in self.events
            if event.event_id in ground_known
            and event.status not in terminal_statuses
        ]
        warning_hours = (
            [
                event.warning_hour
                for event in known_unresolved
                if event.warning_hour >= current_hour
            ]
            if current_hour is not None
            else []
        )
        execution_hours = (
            [
                event.execution_hour
                for event in known_unresolved
                if event.execution_hour >= current_hour
            ]
            if current_hour is not None
            else []
        )
        active_count = (
            sum(
                event.event_id in ground_known
                and event.execution_hour == current_hour
                for event in self.events
            )
            if current_hour is not None
            else sum(
                event.status == LifecycleStatus.ACTIVE.value
                for event in self.events
            )
        )
        return LifecycleDiagnostics(
            lifecycle_ground_known_count=len(ground_known),
            lifecycle_spacecraft_known_count=len(spacecraft_known),
            lifecycle_uploaded_count=sum(
                event.response_uploaded for event in self.events
            ),
            lifecycle_pending_count=sum(
                event.event_id in ground_known
                and event.event_id not in spacecraft_known
                and event.status not in terminal_statuses
                for event in self.events
            ),
            lifecycle_active_count=active_count,
            lifecycle_resolved_success_count=sum(
                event.status == LifecycleStatus.RESOLVED_SUCCESS.value
                for event in self.events
            ),
            lifecycle_resolved_failed_count=sum(
                event.status == LifecycleStatus.RESOLVED_FAILED.value
                for event in self.events
            ),
            lifecycle_missed_upload_count=sum(
                event.failure_reason == "no_command_upload_before_tca"
                for event in self.events
            ),
            lifecycle_next_warning_hour=(
                min(warning_hours) if warning_hours else None
            ),
            lifecycle_next_execution_hour=(
                min(execution_hours) if execution_hours else None
            ),
        )

    def advance(
        self,
        hour: int,
        contact: ContactInfo | None = None,
        *,
        command_upload_allowed: bool = True,
    ) -> LifecycleHourContext:
        """Advance lifecycle awareness using one final contact opportunity."""
        self._validate_hour(hour)
        if self._last_advanced_hour is not None and hour <= self._last_advanced_hour:
            raise ValueError(
                "lifecycle hour must increase strictly; "
                f"last={self._last_advanced_hour}, requested={hour}"
            )
        final_contact = contact or ContactInfo()
        self._validate_contact(final_contact)
        if not isinstance(command_upload_allowed, bool):
            raise ValueError("command_upload_allowed must be a boolean")
        self._last_advanced_hour = hour
        self._last_contact = ContactInfo(
            final_contact.cmd_contact_min,
            final_contact.data_contact_min,
        )
        hour_transitions: list[LifecycleTransition] = []
        eligible_ids: list[str] = []
        upload_failed_ids: list[str] = []
        upload_attempted_ids: list[str] = []
        upload_delivery_failed_ids: list[str] = []

        # An uploaded event should be resolved at its execution hour by the
        # caller. If it was not, preserve that integration error explicitly.
        for event in self.events:
            if (
                event.status == LifecycleStatus.ACTIVE.value
                and event.execution_hour < hour
            ):
                event.response_skipped = True
                event.failure_reason = "response_not_resolved_at_tca"
                hour_transitions.append(
                    self._transition(
                        event,
                        hour,
                        LifecycleStatus.EXPIRED,
                        "execution_hour_passed_without_resolution",
                        final_contact,
                    )
                )

        for event in self.events:
            if (
                event.status == LifecycleStatus.SCHEDULED.value
                and hour >= event.warning_hour
            ):
                hour_transitions.append(
                    self._transition(
                        event,
                        hour,
                        LifecycleStatus.WARNED,
                        "external_warning_issued",
                        final_contact,
                    )
                )
                self._ground_known_ids.add(event.event_id)
                hour_transitions.append(
                    self._transition(
                        event,
                        hour,
                        LifecycleStatus.KNOWN_TO_GROUND,
                        "warning_available_to_ground",
                        final_contact,
                    )
                )
                hour_transitions.append(
                    self._transition(
                        event,
                        hour,
                        LifecycleStatus.UPLINK_PENDING,
                        "command_response_requires_upload",
                        final_contact,
                    )
                )

        if final_contact.cmd_contact_min > 0.0:
            for event in self.events:
                if (
                    event.status == LifecycleStatus.UPLINK_PENDING.value
                    and hour <= event.decision_deadline_hour
                    and hour < event.execution_hour
                ):
                    upload_attempted_ids.append(event.event_id)
                    if not command_upload_allowed:
                        upload_delivery_failed_ids.append(event.event_id)
                        continue
                    event.response_uploaded = True
                    event.response_upload_hour = hour
                    event.spacecraft_awareness_hour = hour
                    self._spacecraft_known_ids.add(event.event_id)
                    hour_transitions.append(
                        self._transition(
                            event,
                            hour,
                            LifecycleStatus.UPLOADED_TO_SPACECRAFT,
                            "response_uploaded_during_command_contact",
                            final_contact,
                        )
                    )

        for event in self.events:
            if event.execution_hour != hour:
                continue
            if event.status == LifecycleStatus.UPLOADED_TO_SPACECRAFT.value:
                hour_transitions.append(
                    self._transition(
                        event,
                        hour,
                        LifecycleStatus.ACTIVE,
                        "execution_hour_reached",
                        final_contact,
                    )
                )
                eligible_ids.append(event.event_id)
            elif event.status not in {
                LifecycleStatus.RESOLVED_SUCCESS.value,
                LifecycleStatus.RESOLVED_FAILED.value,
                LifecycleStatus.EXPIRED.value,
            }:
                event.response_skipped = True
                event.failure_reason = "no_command_upload_before_tca"
                hour_transitions.append(
                    self._transition(
                        event,
                        hour,
                        LifecycleStatus.RESOLVED_FAILED,
                        "no_command_upload_before_tca",
                        final_contact,
                    )
                )
                upload_failed_ids.append(event.event_id)

        return LifecycleHourContext(
            hour=hour,
            ground_known_event_ids=self._ordered_ids(self._ground_known_ids),
            spacecraft_known_event_ids=self._ordered_ids(
                self._spacecraft_known_ids
            ),
            uploaded_event_ids=tuple(
                event.event_id for event in self.events if event.response_uploaded
            ),
            upload_attempted_event_ids=tuple(upload_attempted_ids),
            upload_delivery_failed_event_ids=tuple(
                upload_delivery_failed_ids
            ),
            avoidance_eligible_event_ids=tuple(eligible_ids),
            upload_failed_event_ids=tuple(upload_failed_ids),
            transitions=tuple(hour_transitions),
        )

    def upload_candidate_event_ids(self, hour: int) -> tuple[str, ...]:
        """Return response IDs eligible for a command attempt this hour.

        Events whose warning is issued in ``hour`` are included, but scheduled
        events before their warning hour remain hidden.
        """
        self._validate_hour(hour)
        return tuple(
            event.event_id
            for event in self.events
            if (
                event.status == LifecycleStatus.UPLINK_PENDING.value
                or (
                    event.status == LifecycleStatus.SCHEDULED.value
                    and hour >= event.warning_hour
                )
            )
            and hour <= event.decision_deadline_hour
            and hour < event.execution_hour
        )

    def resolve_avoidance(
        self,
        event_id: str,
        hour: int,
        *,
        success: bool,
        failure_reason: str | None = None,
        contact: ContactInfo | None = None,
    ) -> LifecycleTransition:
        """Record the caller's existing avoidance/maneuver resolution result."""
        self._validate_hour(hour)
        event = self.get_event(event_id)
        if event.execution_hour != hour:
            raise ValueError(
                "avoidance may be resolved only at its execution hour: "
                f"expected {event.execution_hour}, got {hour}"
            )
        if event.status != LifecycleStatus.ACTIVE.value:
            raise ValueError(
                f"lifecycle event {event_id!r} is not active/eligible at TCA"
            )
        if not isinstance(success, bool):
            raise ValueError("success must be a boolean")
        resolved_contact = contact or (
            self._last_contact
            if self._last_advanced_hour == hour
            else ContactInfo()
        )
        self._validate_contact(resolved_contact)
        event.response_executed = success
        event.response_skipped = not success
        event.failure_reason = None if success else (
            failure_reason or "avoidance_response_failed"
        )
        return self._transition(
            event,
            hour,
            (
                LifecycleStatus.RESOLVED_SUCCESS
                if success
                else LifecycleStatus.RESOLVED_FAILED
            ),
            (
                "avoidance_response_executed"
                if success
                else "avoidance_response_failed"
            ),
            resolved_contact,
        )

    def resolve_event(
        self,
        event_id: str,
        hour: int,
        *,
        success: bool,
        failure_reason: str | None = None,
        contact: ContactInfo | None = None,
    ) -> LifecycleTransition:
        """Alias for ``resolve_avoidance`` for generic lifecycle callers."""
        return self.resolve_avoidance(
            event_id,
            hour,
            success=success,
            failure_reason=failure_reason,
            contact=contact,
        )

    def _transition(
        self,
        event: LifecycleEvent,
        hour: int,
        new_status: LifecycleStatus,
        reason: str,
        contact: ContactInfo,
    ) -> LifecycleTransition:
        previous_status = event.status
        event.status = new_status.value
        transition = LifecycleTransition(
            hour=hour,
            year=hour / self.hours_per_year,
            event_id=event.event_id,
            event_type=event.event_type,
            previous_status=previous_status,
            new_status=event.status,
            transition_reason=reason,
            ground_knows=event.event_id in self._ground_known_ids,
            spacecraft_knows=event.event_id in self._spacecraft_known_ids,
            command_contact_min=contact.cmd_contact_min,
            data_contact_min=contact.data_contact_min,
            response_uploaded=event.response_uploaded,
            response_executed=event.response_executed,
            response_skipped=event.response_skipped,
            failure_reason=event.failure_reason,
        )
        self.transitions.append(transition)
        return transition

    def _ordered_ids(self, selected: set[str]) -> tuple[str, ...]:
        return tuple(
            event.event_id for event in self.events if event.event_id in selected
        )

    @staticmethod
    def _validate_hour(hour: int) -> None:
        if isinstance(hour, bool) or not isinstance(hour, int) or hour < 0:
            raise ValueError("hour must be a non-negative integer")

    @staticmethod
    def _validate_contact(contact: ContactInfo) -> None:
        for field_name in ("cmd_contact_min", "data_contact_min"):
            value = getattr(contact, field_name)
            if not isfinite(value) or value < 0.0:
                raise ValueError(
                    f"{field_name} must be a finite non-negative number"
                )


__all__ = [
    "EventLifecycleManager",
    "LIFECYCLE_STATUSES",
    "LifecycleEvent",
    "LifecycleDiagnostics",
    "LifecycleHourContext",
    "LifecycleStatus",
    "LifecycleTransition",
    "MAXIMUM_CONJUNCTION_WARNING_LEAD_HOURS",
    "MINIMUM_CONJUNCTION_WARNING_LEAD_HOURS",
    "NOMINAL_CONJUNCTION_WARNING_LEAD_HOURS",
    "deterministic_warning_lead_hours",
    "maximum_conjunction_warning_lead_hours",
    "minimum_conjunction_warning_lead_hours",
    "nominal_conjunction_warning_lead_hours",
]
