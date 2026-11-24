"""Normalization and scoring for comparable simulator runs.

Data is normalized by the maximum data volume available through all nominal
synthetic contact opportunities in the requested duration.  This denominator is
independent of policy and scenario; outage runs therefore retain their penalty.
All normalized components are clamped to [0, 1].

V2.1 preserves every original score term and subtracts two transparent penalties:
``data_loss_penalty_weight * data_loss_fraction`` and
``emergency_penalty_weight * emergency_mode_fraction``.
"""

from dataclasses import asdict, dataclass
from math import ceil

from .config import DEFAULT_CONFIG, SimulationConfig
from .models import Mode, SatelliteState


def clamp_fraction(value: float) -> float:
    return max(DEFAULT_CONFIG.minimum_health, min(DEFAULT_CONFIG.maximum_health, value))


@dataclass(frozen=True)
class Metrics:
    normalized_data_downlinked: float
    final_total_health: float
    survival_fraction: float
    final_soc_fraction: float
    safe_mode_fraction: float
    data_lost_gb: float
    data_loss_fraction: float
    overflow_hours: int
    backup_mode_fraction: float
    emergency_mode_fraction: float
    payload_unavailable_hours: int
    minimum_soc: float
    minimum_health: float
    final_buffer_fraction: float
    effective_storage_capacity_gb: float
    score: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def calculate_metrics(
    state: SatelliteState,
    total_hours: int,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> Metrics:
    nominal_contacts = ceil(total_hours / config.contact_interval_hours)
    nominal_capacity_gb = (
        nominal_contacts
        * config.data_contact_minutes
        * config.x_band_downlink_rate_gb_per_min
    )
    normalized_data = (
        clamp_fraction(state.total_data_downlinked_gb / nominal_capacity_gb)
        if nominal_capacity_gb > config.minimum_percent
        else config.minimum_health
    )
    survival = (
        clamp_fraction(state.hours_completed / total_hours)
        if total_hours > config.minimum_percent
        else config.maximum_health
    )
    safe_fraction = (
        clamp_fraction(state.safe_mode_hours / state.hours_completed)
        if state.hours_completed > config.minimum_percent
        else config.minimum_health
    )
    backup_fraction = (
        clamp_fraction(state.mode_hours.get(Mode.BACKUP, 0) / state.hours_completed)
        if state.hours_completed > config.minimum_percent
        else config.minimum_health
    )
    emergency_fraction = (
        clamp_fraction(
            state.mode_hours.get(Mode.EMERGENCY_BEACON, 0) / state.hours_completed
        )
        if state.hours_completed > config.minimum_percent
        else config.minimum_health
    )
    data_loss_fraction = (
        clamp_fraction(state.data_lost_gb / state.total_data_generated_gb)
        if state.total_data_generated_gb > config.minimum_percent
        else config.minimum_health
    )
    effective_storage_capacity = config.storage_capacity_gb * clamp_fraction(
        state.storage_health
    )
    final_buffer_fraction = (
        clamp_fraction(state.data_buffer_gb / effective_storage_capacity)
        if effective_storage_capacity > config.minimum_percent
        else config.minimum_health
    )
    health = clamp_fraction(state.total_health(config))
    soc_fraction = clamp_fraction(state.soc / config.maximum_percent)
    score = (
        config.score_data_weight * normalized_data
        + config.score_health_weight * health
        + config.score_survival_weight * survival
        + config.score_soc_weight * soc_fraction
        - config.score_safe_penalty_weight * safe_fraction
        - config.score_data_loss_penalty_weight * data_loss_fraction
        - config.score_emergency_penalty_weight * emergency_fraction
    )
    return Metrics(
        normalized_data_downlinked=normalized_data,
        final_total_health=health,
        survival_fraction=survival,
        final_soc_fraction=soc_fraction,
        safe_mode_fraction=safe_fraction,
        data_lost_gb=state.data_lost_gb,
        data_loss_fraction=data_loss_fraction,
        overflow_hours=state.overflow_hours,
        backup_mode_fraction=backup_fraction,
        emergency_mode_fraction=emergency_fraction,
        payload_unavailable_hours=state.payload_unavailable_hours,
        minimum_soc=state.minimum_soc,
        minimum_health=state.minimum_health,
        final_buffer_fraction=final_buffer_fraction,
        effective_storage_capacity_gb=effective_storage_capacity,
        score=score,
    )
