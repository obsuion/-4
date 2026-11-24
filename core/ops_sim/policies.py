"""Daily-plan policy choices from the supplied specification."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .config import DEFAULT_CONFIG, SimulationConfig
from .models import ContactInfo, Mode, SatelliteState


@dataclass(frozen=True)
class OperatorProfile:
    """Transparent proxy parameters for reactive and risk-aware planning."""

    energy_floor: float
    imaging_energy_floor: float
    buffer_high_fraction: float
    buffer_critical_fraction: float
    downlink_bias: float
    imaging_bias: float
    standby_bias: float
    outage_reserve_bias: float
    battery_protection_bias: float


OPERATOR_PROFILES = {
    "aggressive": OperatorProfile(15, 35, 0.75, 0.95, 0.40, 0.95, 0.10, 0.05, 0.05),
    "conservative": OperatorProfile(30, 65, 0.55, 0.70, 0.70, 0.30, 0.80, 0.75, 0.70),
    "adaptive": OperatorProfile(25, 55, 0.60, 0.80, 0.65, 0.60, 0.45, 0.50, 0.50),
    "balanced": OperatorProfile(25, 50, 0.55, 0.80, 0.65, 0.65, 0.50, 0.45, 0.45),
    "survival_first": OperatorProfile(40, 75, 0.40, 0.65, 0.75, 0.15, 0.95, 1.00, 1.00),
    "data_maximizer": OperatorProfile(18, 32, 0.80, 0.95, 0.35, 1.00, 0.10, 0.10, 0.10),
    "power_saver": OperatorProfile(35, 68, 0.50, 0.75, 0.65, 0.20, 0.90, 0.70, 0.90),
    "downlink_priority": OperatorProfile(25, 50, 0.35, 0.70, 1.00, 0.45, 0.45, 0.45, 0.45),
    "storage_guardian": OperatorProfile(25, 52, 0.35, 0.60, 0.95, 0.45, 0.65, 0.55, 0.45),
    "outage_resilient": OperatorProfile(35, 62, 0.45, 0.70, 0.80, 0.30, 0.80, 1.00, 0.70),
    "battery_protective": OperatorProfile(32, 65, 0.50, 0.75, 0.70, 0.30, 0.80, 0.65, 1.00),
    "contact_opportunist": OperatorProfile(22, 42, 0.65, 0.85, 1.00, 0.80, 0.25, 0.25, 0.30),
}


class Policy(ABC):
    name = "base"

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    @property
    @abstractmethod
    def safe_threshold(self) -> float: ...

    @abstractmethod
    def select_mode(self, state: SatelliteState, contact: ContactInfo) -> Mode: ...

    def buffer_fraction(self, state: SatelliteState) -> float:
        return state.data_buffer_gb / self.config.storage_capacity_gb

    @property
    def operator_profile(self) -> OperatorProfile:
        return OPERATOR_PROFILES.get(self.name, OPERATOR_PROFILES["adaptive"])


class AggressivePolicy(Policy):
    name = "aggressive"

    @property
    def safe_threshold(self) -> float:
        return self.config.aggressive_safe_threshold

    def select_mode(self, state: SatelliteState, contact: ContactInfo) -> Mode:
        buffer_fraction = self.buffer_fraction(state)
        if contact.data_contact_min > 0 and buffer_fraction > self.config.aggressive_downlink_buffer_fraction:
            return Mode.DOWNLINK
        if state.soc > self.config.aggressive_imaging_soc and buffer_fraction < self.config.imaging_block_fraction:
            return Mode.IMAGING
        return Mode.STANDBY


class ConservativePolicy(Policy):
    name = "conservative"

    @property
    def safe_threshold(self) -> float:
        return self.config.conservative_safe_threshold

    def select_mode(self, state: SatelliteState, contact: ContactInfo) -> Mode:
        buffer_fraction = self.buffer_fraction(state)
        if contact.data_contact_min > 0 and buffer_fraction > self.config.conservative_downlink_buffer_fraction:
            return Mode.DOWNLINK
        if state.soc > self.config.conservative_imaging_soc and buffer_fraction < self.config.conservative_imaging_buffer_fraction:
            return Mode.IMAGING
        return Mode.STANDBY


class AdaptivePolicy(Policy):
    name = "adaptive"

    @property
    def safe_threshold(self) -> float:
        return self.config.adaptive_safe_threshold

    def select_mode(self, state: SatelliteState, contact: ContactInfo) -> Mode:
        buffer_fraction = self.buffer_fraction(state)
        if contact.data_contact_min > 0 and buffer_fraction > self.config.adaptive_downlink_buffer_fraction:
            return Mode.DOWNLINK
        if state.soc > self.config.adaptive_imaging_soc and buffer_fraction < self.config.adaptive_imaging_buffer_fraction:
            return Mode.IMAGING
        if state.soc < self.config.adaptive_safe_soc:
            return Mode.SAFE
        return Mode.STANDBY


class ProfilePolicy(Policy):
    """Shared reactive rule for the additional V2.6 operator profiles."""

    @property
    def safe_threshold(self) -> float:
        return self.operator_profile.energy_floor

    def select_mode(self, state: SatelliteState, contact: ContactInfo) -> Mode:
        profile = self.operator_profile
        buffer_fraction = self.buffer_fraction(state)
        energy_margin = state.soc * state.battery_health
        battery_reserve = (
            (1.0 - state.battery_health)
            * 20.0
            * profile.battery_protection_bias
        )
        outage_reserve = (
            min(1.0, state.hours_since_contact / self.config.hours_per_day)
            * 10.0
            * profile.outage_reserve_bias
        )
        energy_floor = profile.energy_floor + battery_reserve + outage_reserve

        if energy_margin < energy_floor:
            return Mode.SAFE

        has_data_contact = contact.data_contact_min > self.config.minimum_percent
        if has_data_contact and state.data_buffer_gb > self.config.minimum_percent:
            downlink_trigger = max(
                0.02,
                profile.buffer_high_fraction
                * (1.0 - 0.75 * profile.downlink_bias),
            )
            if buffer_fraction >= downlink_trigger or profile.downlink_bias >= 0.90:
                return Mode.DOWNLINK

        if buffer_fraction >= profile.buffer_critical_fraction:
            return Mode.STANDBY

        imaging_floor = profile.imaging_energy_floor + battery_reserve
        energy_confidence = max(
            0.0, min(1.0, (energy_margin - imaging_floor) / 40.0)
        )
        imaging_score = profile.imaging_bias + 0.25 * energy_confidence
        standby_score = profile.standby_bias + 0.25 * (
            outage_reserve / 10.0
        )
        if (
            energy_margin >= imaging_floor
            and buffer_fraction < profile.buffer_high_fraction
            and imaging_score > standby_score
        ):
            return Mode.IMAGING
        if (
            has_data_contact
            and state.data_buffer_gb > self.config.minimum_percent
            and profile.downlink_bias >= profile.standby_bias
        ):
            return Mode.DOWNLINK
        return Mode.STANDBY


class BalancedPolicy(ProfilePolicy):
    name = "balanced"


class SurvivalFirstPolicy(ProfilePolicy):
    name = "survival_first"


class DataMaximizerPolicy(ProfilePolicy):
    name = "data_maximizer"


class PowerSaverPolicy(ProfilePolicy):
    name = "power_saver"


class DownlinkPriorityPolicy(ProfilePolicy):
    name = "downlink_priority"


class StorageGuardianPolicy(ProfilePolicy):
    name = "storage_guardian"


class OutageResilientPolicy(ProfilePolicy):
    name = "outage_resilient"


class BatteryProtectivePolicy(ProfilePolicy):
    name = "battery_protective"


class ContactOpportunistPolicy(ProfilePolicy):
    name = "contact_opportunist"


POLICIES = {
    AggressivePolicy.name: AggressivePolicy,
    ConservativePolicy.name: ConservativePolicy,
    AdaptivePolicy.name: AdaptivePolicy,
    BalancedPolicy.name: BalancedPolicy,
    SurvivalFirstPolicy.name: SurvivalFirstPolicy,
    DataMaximizerPolicy.name: DataMaximizerPolicy,
    PowerSaverPolicy.name: PowerSaverPolicy,
    DownlinkPriorityPolicy.name: DownlinkPriorityPolicy,
    StorageGuardianPolicy.name: StorageGuardianPolicy,
    OutageResilientPolicy.name: OutageResilientPolicy,
    BatteryProtectivePolicy.name: BatteryProtectivePolicy,
    ContactOpportunistPolicy.name: ContactOpportunistPolicy,
}


def make_policy(name: str, config: SimulationConfig = DEFAULT_CONFIG) -> Policy:
    try:
        return POLICIES[name.lower()](config)
    except KeyError as exc:
        choices = ", ".join(sorted(POLICIES))
        raise ValueError(f"Unknown policy {name!r}; choose one of: {choices}") from exc
