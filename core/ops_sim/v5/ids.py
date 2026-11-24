"""Stable, typed identifiers for persistent V5 domain identity."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import ClassVar, TypeVar


_MAX_VALUE_LENGTH = 128
_VALUE_PATTERN = re.compile(
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*",
    flags=re.ASCII,
)
_StableIdT = TypeVar("_StableIdT", bound="StableId")


@dataclass(frozen=True, slots=True)
class StableId:
    """One deterministic identifier value with a type-specific prefix."""

    value: str

    prefix: ClassVar[str] = "id"

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("StableId value must be a string")
        if not self.value:
            raise ValueError("StableId value must not be empty")
        if self.value != self.value.strip():
            raise ValueError(
                "StableId value must not have leading or trailing whitespace"
            )
        if len(self.value) > _MAX_VALUE_LENGTH:
            raise ValueError(
                f"StableId value must be at most {_MAX_VALUE_LENGTH} characters"
            )
        if _VALUE_PATTERN.fullmatch(self.value) is None:
            raise ValueError(
                "StableId value must contain lowercase ASCII alphanumeric "
                "segments separated only by '.', '_', or '-'"
            )

    @property
    def canonical(self) -> str:
        """Return the stable type-prefixed representation."""
        return f"{self.prefix}:{self.value}"

    def __str__(self) -> str:
        return self.canonical

    @classmethod
    def from_canonical(
        cls: type[_StableIdT], text: str
    ) -> _StableIdT:
        """Parse a canonical value belonging to this exact ID type."""
        if not isinstance(text, str):
            raise TypeError("canonical identifier must be a string")
        expected_prefix = f"{cls.prefix}:"
        if not text.startswith(expected_prefix):
            raise ValueError(
                f"canonical identifier must use prefix {cls.prefix!r}"
            )
        return cls(text[len(expected_prefix):])


@dataclass(frozen=True, slots=True)
class ParameterId(StableId):
    prefix: ClassVar[str] = "parameter"


@dataclass(frozen=True, slots=True)
class SourceRecordId(StableId):
    prefix: ClassVar[str] = "source"


@dataclass(frozen=True, slots=True)
class SpacecraftConfigurationId(StableId):
    prefix: ClassVar[str] = "spacecraft-config"


@dataclass(frozen=True, slots=True)
class SubsystemConfigurationId(StableId):
    prefix: ClassVar[str] = "subsystem-config"


@dataclass(frozen=True, slots=True)
class ADCSBoresightFrameId(StableId):
    prefix: ClassVar[str] = "adcs-boresight-frame"


@dataclass(frozen=True, slots=True)
class ADCSSlewAnchorId(StableId):
    prefix: ClassVar[str] = "adcs-slew-anchor"


@dataclass(frozen=True, slots=True)
class AcquisitionDataRecordId(StableId):
    """Identity of one persistent onboard acquisition-data record."""

    prefix: ClassVar[str] = "acquisition-data-record"


@dataclass(frozen=True, slots=True)
class AuthorityId(StableId):
    prefix: ClassVar[str] = "authority"


@dataclass(frozen=True, slots=True)
class TelemetrySnapshotId(StableId):
    prefix: ClassVar[str] = "telemetry-snapshot"


@dataclass(frozen=True, slots=True)
class NumericalConfigId(StableId):
    prefix: ClassVar[str] = "numerical-config"


@dataclass(frozen=True, slots=True)
class EnvironmentId(StableId):
    prefix: ClassVar[str] = "environment"


@dataclass(frozen=True, slots=True)
class FlightRulesId(StableId):
    prefix: ClassVar[str] = "flight-rules"


@dataclass(frozen=True, slots=True)
class ScenarioId(StableId):
    prefix: ClassVar[str] = "scenario"


@dataclass(frozen=True, slots=True)
class WorldId(StableId):
    prefix: ClassVar[str] = "world"


@dataclass(frozen=True, slots=True)
class ModelManifestId(StableId):
    prefix: ClassVar[str] = "model-manifest"


@dataclass(frozen=True, slots=True)
class ControllerId(StableId):
    prefix: ClassVar[str] = "controller"


@dataclass(frozen=True, slots=True)
class MissionRequestId(StableId):
    prefix: ClassVar[str] = "mission-request"


@dataclass(frozen=True, slots=True)
class GroundContactId(StableId):
    prefix: ClassVar[str] = "ground-contact"


@dataclass(frozen=True, slots=True)
class GroundStationId(StableId):
    prefix: ClassVar[str] = "ground-station"


@dataclass(frozen=True, slots=True)
class GroundTargetId(StableId):
    prefix: ClassVar[str] = "ground-target"


@dataclass(frozen=True, slots=True)
class ImagingRequestId(StableId):
    prefix: ClassVar[str] = "imaging-request"


@dataclass(frozen=True, slots=True)
class ObservationOpportunityId(StableId):
    prefix: ClassVar[str] = "observation-opportunity"


@dataclass(frozen=True, slots=True)
class DataProductId(StableId):
    prefix: ClassVar[str] = "data-product"


@dataclass(frozen=True, slots=True)
class PlanId(StableId):
    prefix: ClassVar[str] = "plan"


@dataclass(frozen=True, slots=True)
class WorldEventId(StableId):
    prefix: ClassVar[str] = "event"


@dataclass(frozen=True, slots=True)
class CommandId(StableId):
    prefix: ClassVar[str] = "command"


@dataclass(frozen=True, slots=True)
class ManeuverId(StableId):
    prefix: ClassVar[str] = "maneuver"


@dataclass(frozen=True, slots=True)
class ThermalNodeId(StableId):
    prefix: ClassVar[str] = "thermal-node"


@dataclass(frozen=True, slots=True)
class ThermalLinkId(StableId):
    prefix: ClassVar[str] = "thermal-link"


__all__ = [
    "ADCSBoresightFrameId",
    "ADCSSlewAnchorId",
    "AcquisitionDataRecordId",
    "AuthorityId",
    "CommandId",
    "ControllerId",
    "DataProductId",
    "EnvironmentId",
    "FlightRulesId",
    "GroundContactId",
    "GroundStationId",
    "GroundTargetId",
    "ImagingRequestId",
    "ManeuverId",
    "MissionRequestId",
    "ModelManifestId",
    "NumericalConfigId",
    "ObservationOpportunityId",
    "ParameterId",
    "PlanId",
    "ScenarioId",
    "SourceRecordId",
    "SpacecraftConfigurationId",
    "StableId",
    "SubsystemConfigurationId",
    "TelemetrySnapshotId",
    "ThermalLinkId",
    "ThermalNodeId",
    "WorldEventId",
    "WorldId",
]
