"""Simulation-based Remaining Useful Life estimates for the operations proxy.

The calculations in this module are horizon-censored continuations of this
simulator, not physical reliability predictions or KazEOSat-1 flight estimates.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
from math import floor, isclose, isfinite, pi
from statistics import fmean, median
from typing import Callable, Sequence

from .autonomy import AUTONOMY_MODELS
from .config import DEFAULT_CONFIG, SimulationConfig
from .contacts import (
    ContactModel,
    GeometryContactModel,
    SyntheticContactModel,
    default_astana_ground_station,
)
from .event_catalog import EventCatalog, generate_stochastic_event_catalog
from .debris_risk import DEBRIS_RISK_MODELS
from .models import LossReason, SatelliteState
from .packets import PACKET_DELIVERY_MODELS, PACKET_MODELS
from .policies import make_policy
from .pointing import POINTING_MODELS
from .power import POWER_MODELS
from .scenarios import make_scenario
from .simulator import (
    EVENT_LIFECYCLE_MODELS,
    MANEUVER_MODELS,
    OPERATOR_VIEWS,
    ORBIT_EVOLUTION_MODELS,
    PLANNING_MODELS,
    Simulator,
)
from .stationkeeping import STATIONKEEPING_PLANNING_MODELS
from .targets import TARGET_MODELS
from .thermal import THERMAL_MODELS


STOCHASTIC_SCENARIO = "stochastic_post_life_events"

RUL_PROVENANCE_FIELDS = (
    "policy",
    "scenario",
    "operator_view",
    "planning_model",
    "maneuver_model",
    "orbit_evolution_model",
    "contact_model",
    "stationkeeping_planning_model",
    "event_lifecycle_model",
    "debris_risk_model",
    "autonomy_model",
    "power_model",
    "thermal_model",
    "target_model",
    "pointing_model",
    "packet_model",
    "packet_delivery_model",
    "packet_drop_fraction_proxy",
    "start_year",
    "horizon_years",
)

ContactModelFactory = Callable[[SimulationConfig], ContactModel]
EventCatalogFactory = Callable[
    [int | None, str, int, SimulationConfig], EventCatalog
]
SimulatorFactory = Callable[[int, EventCatalog | None], Simulator]


@dataclass(frozen=True)
class RULSample:
    """One warm-up plus continuation outcome, with continuation-only deltas."""

    policy: str
    scenario: str
    operator_view: str
    planning_model: str
    maneuver_model: str
    orbit_evolution_model: str
    contact_model: str
    sample_seed: int
    start_year: float
    horizon_years: float
    warmup_failed: bool
    alive_at_start: bool
    survived_to_horizon: bool
    additional_hours_survived: int
    additional_years_survived: float
    loss_reason: str | None
    risk_driver: str
    risk_margin: float
    start_soc: float
    start_health: float
    start_delta_v_remaining_m_per_s: float
    start_fuel_remaining_percent: float
    start_orbit_drift_proxy_km: float
    final_soc: float
    final_health: float
    final_delta_v_remaining_m_per_s: float
    final_fuel_remaining_percent: float
    final_orbit_drift_proxy_km: float
    data_downlinked_during_rul_gb: float
    data_generated_during_rul_gb: float
    debris_avoidance_executed_during_rul: int
    debris_avoidance_skipped_during_rul: int
    maneuver_count_during_rul: int
    orbit_correction_count_during_rul: int
    stationkeeping_planning_model: str = "legacy"
    event_lifecycle_model: str = "none"
    debris_risk_model: str = "legacy"
    autonomy_model: str = "none"
    power_model: str = "legacy"
    thermal_model: str = "legacy"
    target_model: str = "legacy"
    pointing_model: str = "legacy"
    packet_model: str = "legacy"
    packet_delivery_model: str = "ideal"
    packet_drop_fraction_proxy: float = (
        DEFAULT_CONFIG.packet_drop_fraction_proxy
    )
    contingency_plan_uploads_during_rul: int = 0
    autonomous_actions_during_rul: int = 0
    lifecycle_uploads_during_rul: int = 0
    lifecycle_resolved_success_during_rul: int = 0
    lifecycle_resolved_failed_during_rul: int = 0
    telemetry_delivery_failures_during_rul: int = 0
    command_packet_failures_during_rul: int = 0
    daily_plan_packet_failures_during_rul: int = 0
    thermal_stress_hours_during_rul: int = 0
    target_area_imaged_during_rul_km2: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RULSummary:
    """Aggregate horizon-censored RUL and survival statistics."""

    policy: str
    scenario: str
    operator_view: str
    planning_model: str
    maneuver_model: str
    orbit_evolution_model: str
    contact_model: str
    start_year: float
    horizon_years: float
    samples: int
    alive_at_start_fraction: float
    survived_to_horizon_fraction: float
    expected_rul_years_censored: float
    median_rul_years_censored: float
    p05_rul_years_censored: float
    p95_rul_years_censored: float
    probability_survive_plus_1y: float | None
    probability_survive_plus_2y: float | None
    probability_survive_plus_3y: float | None
    probability_survive_to_horizon: float
    most_common_loss_reason: str | None
    most_common_risk_driver: str | None
    mean_start_soc: float
    mean_start_health: float
    mean_start_fuel_remaining_percent: float
    mean_final_soc: float
    mean_final_health: float
    mean_final_fuel_remaining_percent: float
    mean_data_downlinked_during_rul_gb: float
    mean_data_generated_during_rul_gb: float
    mean_maneuver_count_during_rul: float
    mean_debris_avoidance_executed_during_rul: float
    mean_debris_avoidance_skipped_during_rul: float
    stationkeeping_planning_model: str = "legacy"
    event_lifecycle_model: str = "none"
    debris_risk_model: str = "legacy"
    autonomy_model: str = "none"
    power_model: str = "legacy"
    thermal_model: str = "legacy"
    target_model: str = "legacy"
    pointing_model: str = "legacy"
    packet_model: str = "legacy"
    packet_delivery_model: str = "ideal"
    packet_drop_fraction_proxy: float = (
        DEFAULT_CONFIG.packet_drop_fraction_proxy
    )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SurvivalCurvePoint:
    """Empirical probability of remaining alive at one RUL grid point."""

    policy: str
    scenario: str
    operator_view: str
    planning_model: str
    maneuver_model: str
    orbit_evolution_model: str
    contact_model: str
    start_year: float
    years_after_start: float
    survival_probability: float
    samples: int
    stationkeeping_planning_model: str = "legacy"
    event_lifecycle_model: str = "none"
    debris_risk_model: str = "legacy"
    autonomy_model: str = "none"
    power_model: str = "legacy"
    thermal_model: str = "legacy"
    target_model: str = "legacy"
    pointing_model: str = "legacy"
    packet_model: str = "legacy"
    packet_delivery_model: str = "ideal"
    packet_drop_fraction_proxy: float = (
        DEFAULT_CONFIG.packet_drop_fraction_proxy
    )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


_LOSS_REASON_DRIVERS = {
    LossReason.CRITICAL_POWER: "power",
    LossReason.EPS_FAILURE: "eps",
    LossReason.COMMUNICATION_FAILURE: "comms",
    LossReason.STORAGE_FAILURE: "storage",
    LossReason.OBC_FAILURE: "obc",
    LossReason.ADCS_FAILURE: "adcs",
    LossReason.THERMAL_FAILURE: "thermal",
}


def _normalized_upper_margin(
    value: float, failure_threshold: float, healthy_value: float
) -> float:
    """Return dimensionless headroom, with zero at the failure threshold."""
    span = healthy_value - failure_threshold
    if span <= 0.0:
        return value - failure_threshold
    return (value - failure_threshold) / span


def _normalized_lower_margin(value: float, critical_value: float) -> float:
    """Return dimensionless headroom for quantities where lower is safer."""
    if critical_value <= 0.0:
        return -abs(value)
    return (critical_value - abs(value)) / critical_value


def _orbit_geometry_error_km(
    state: SatelliteState, config: SimulationConfig
) -> float:
    phase_arc_km = (
        abs(state.orbit_phase_error_deg)
        / config.degrees_per_circle
        * 2.0
        * pi
        * (config.earth_radius_km + config.orbit_altitude_km)
    )
    return max(
        abs(state.orbit_groundtrack_error_km),
        abs(state.orbit_altitude_offset_km),
        phase_arc_km,
    )


def risk_margins(
    state: SatelliteState,
    config: SimulationConfig = DEFAULT_CONFIG,
    *,
    maneuver_model: str = "none",
    orbit_evolution_model: str = "fixed",
) -> dict[str, float]:
    """Return auditable dimensionless margins used by the RUL classifier.

    Health and SOC margins are normalized between their configured failure and
    healthy values. Maneuver fuel is normalized above the minimum executable
    stationkeeping cost. Drift and geometry margins are normalized below their
    configured critical thresholds. Values below zero are beyond a threshold.
    """
    margins = {
        "power": _normalized_upper_margin(
            state.soc, config.critical_soc, config.maximum_percent
        ),
        "eps": _normalized_upper_margin(
            state.eps_health(config),
            config.eps_failure_health,
            config.maximum_health,
        ),
        "comms": _normalized_upper_margin(
            state.comms_health,
            config.comms_failure_health,
            config.maximum_health,
        ),
        "storage": _normalized_upper_margin(
            state.storage_health,
            config.storage_failure_health,
            config.maximum_health,
        ),
        "obc": _normalized_upper_margin(
            state.obc_health,
            config.obc_failure_health,
            config.maximum_health,
        ),
        "adcs": _normalized_upper_margin(
            state.adcs_health,
            config.adcs_failure_health,
            config.maximum_health,
        ),
        "thermal": _normalized_upper_margin(
            state.thermal_health,
            config.thermal_failure_health,
            config.maximum_health,
        ),
        "payload": _normalized_upper_margin(
            state.payload_health,
            config.payload_failure_health,
            config.maximum_health,
        ),
    }
    if maneuver_model == "stationkeeping_proxy":
        required_delta_v = max(
            config.minimum_delta_v_for_maneuver_m_per_s,
            config.stationkeeping_delta_v_cost_m_per_s,
        )
        margins["fuel"] = _normalized_upper_margin(
            state.delta_v_remaining_m_per_s,
            required_delta_v,
            config.initial_delta_v_budget_m_per_s,
        )
        margins["orbit_drift"] = _normalized_lower_margin(
            state.orbit_drift_proxy_km,
            config.orbit_drift_critical_threshold_km,
        )
    if orbit_evolution_model == "drift_proxy":
        margins["orbit_geometry"] = _normalized_lower_margin(
            _orbit_geometry_error_km(state, config),
            config.orbit_geometry_critical_threshold_km,
        )
    return margins


def classify_risk_driver(
    state: SatelliteState,
    config: SimulationConfig = DEFAULT_CONFIG,
    *,
    maneuver_model: str = "none",
    orbit_evolution_model: str = "fixed",
) -> tuple[str, float]:
    """Classify failure or the smallest remaining normalized proxy margin."""
    margins = risk_margins(
        state,
        config,
        maneuver_model=maneuver_model,
        orbit_evolution_model=orbit_evolution_model,
    )
    if state.loss_reason is not None:
        driver = _LOSS_REASON_DRIVERS.get(state.loss_reason, "unknown")
        return driver, margins.get(driver, 0.0)
    return min(margins.items(), key=lambda item: item[1])


def _fuel_remaining_percent(
    state: SatelliteState, config: SimulationConfig
) -> float:
    budget = config.initial_delta_v_budget_m_per_s
    if budget <= config.minimum_percent:
        return config.minimum_percent
    value = config.maximum_percent * state.delta_v_remaining_m_per_s / budget
    return max(config.minimum_percent, min(config.maximum_percent, value))


def _years_to_hours(
    value: float, name: str, config: SimulationConfig
) -> int:
    if not isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    if config.hours_per_year <= 0:
        raise ValueError("config.hours_per_year must be positive")
    return int(round(value * config.hours_per_year))


def _default_contact_model(
    name: str, config: SimulationConfig
) -> ContactModel:
    if name == "synthetic":
        return SyntheticContactModel(config)
    if name == "geometry":
        return GeometryContactModel(
            default_astana_ground_station(config), config
        )
    raise ValueError(
        f"Unknown contact model {name!r}; choose one of: geometry, synthetic"
    )


def _percentile(values: Sequence[float], probability: float) -> float:
    """Linear-interpolated percentile, including the one-sample case."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    position = (len(ordered) - 1) * probability
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _most_common(values: Sequence[str | None]) -> str | None:
    counts = Counter(value for value in values if value)
    if not counts:
        return None
    return sorted(counts, key=lambda value: (-counts[value], value))[0]


def _survives_offset(sample: RULSample, years_after_start: float) -> bool:
    if not sample.alive_at_start:
        return False
    if years_after_start <= 0.0:
        return True
    if isclose(years_after_start, sample.horizon_years):
        return sample.survived_to_horizon
    return sample.additional_years_survived >= years_after_start


def validate_homogeneous_rul_samples(
    samples: Sequence[RULSample],
) -> RULSample:
    """Return the first sample after validating shared run provenance."""
    if not samples:
        raise ValueError("at least one RUL sample is required")
    first = samples[0]
    expected = tuple(getattr(first, field) for field in RUL_PROVENANCE_FIELDS)
    if any(
        tuple(getattr(sample, field) for field in RUL_PROVENANCE_FIELDS)
        != expected
        for sample in samples[1:]
    ):
        raise ValueError("RUL samples must share one run configuration")
    return first


# Retain the established private name for any internal or downstream callers.
_validate_homogeneous_samples = validate_homogeneous_rul_samples


def summarize_rul_samples(samples: Sequence[RULSample]) -> RULSummary:
    """Summarize a homogeneous sample set using horizon-censored durations."""
    first = validate_homogeneous_rul_samples(samples)
    count = len(samples)
    censored = [
        min(
            first.horizon_years,
            max(0.0, sample.additional_years_survived),
        )
        for sample in samples
    ]

    def mean_of(field: str) -> float:
        return fmean(float(getattr(sample, field)) for sample in samples)

    def survival_probability(years: float) -> float | None:
        if first.horizon_years < years:
            return None
        return fmean(_survives_offset(sample, years) for sample in samples)

    survived_fraction = fmean(
        sample.survived_to_horizon for sample in samples
    )
    return RULSummary(
        policy=first.policy,
        scenario=first.scenario,
        operator_view=first.operator_view,
        planning_model=first.planning_model,
        maneuver_model=first.maneuver_model,
        orbit_evolution_model=first.orbit_evolution_model,
        contact_model=first.contact_model,
        stationkeeping_planning_model=(
            first.stationkeeping_planning_model
        ),
        event_lifecycle_model=first.event_lifecycle_model,
        debris_risk_model=first.debris_risk_model,
        autonomy_model=first.autonomy_model,
        power_model=first.power_model,
        thermal_model=first.thermal_model,
        target_model=first.target_model,
        pointing_model=first.pointing_model,
        packet_model=first.packet_model,
        packet_delivery_model=first.packet_delivery_model,
        packet_drop_fraction_proxy=first.packet_drop_fraction_proxy,
        start_year=first.start_year,
        horizon_years=first.horizon_years,
        samples=count,
        alive_at_start_fraction=fmean(
            sample.alive_at_start for sample in samples
        ),
        survived_to_horizon_fraction=survived_fraction,
        expected_rul_years_censored=fmean(censored),
        median_rul_years_censored=median(censored),
        p05_rul_years_censored=_percentile(censored, 0.05),
        p95_rul_years_censored=_percentile(censored, 0.95),
        probability_survive_plus_1y=survival_probability(1.0),
        probability_survive_plus_2y=survival_probability(2.0),
        probability_survive_plus_3y=survival_probability(3.0),
        probability_survive_to_horizon=survived_fraction,
        most_common_loss_reason=_most_common(
            [sample.loss_reason for sample in samples]
        ),
        most_common_risk_driver=_most_common(
            [sample.risk_driver for sample in samples]
        ),
        mean_start_soc=mean_of("start_soc"),
        mean_start_health=mean_of("start_health"),
        mean_start_fuel_remaining_percent=mean_of(
            "start_fuel_remaining_percent"
        ),
        mean_final_soc=mean_of("final_soc"),
        mean_final_health=mean_of("final_health"),
        mean_final_fuel_remaining_percent=mean_of(
            "final_fuel_remaining_percent"
        ),
        mean_data_downlinked_during_rul_gb=mean_of(
            "data_downlinked_during_rul_gb"
        ),
        mean_data_generated_during_rul_gb=mean_of(
            "data_generated_during_rul_gb"
        ),
        mean_maneuver_count_during_rul=mean_of(
            "maneuver_count_during_rul"
        ),
        mean_debris_avoidance_executed_during_rul=mean_of(
            "debris_avoidance_executed_during_rul"
        ),
        mean_debris_avoidance_skipped_during_rul=mean_of(
            "debris_avoidance_skipped_during_rul"
        ),
    )


def build_survival_curve(
    samples: Sequence[RULSample],
) -> list[SurvivalCurvePoint]:
    """Build the requested annual empirical survival grid without plotting."""
    first = validate_homogeneous_rul_samples(samples)
    grid = sorted({
        point
        for point in (0.0, 1.0, 2.0, 3.0, first.horizon_years)
        if point <= first.horizon_years
    })
    return [
        SurvivalCurvePoint(
            policy=first.policy,
            scenario=first.scenario,
            operator_view=first.operator_view,
            planning_model=first.planning_model,
            maneuver_model=first.maneuver_model,
            orbit_evolution_model=first.orbit_evolution_model,
            contact_model=first.contact_model,
            stationkeeping_planning_model=(
                first.stationkeeping_planning_model
            ),
            event_lifecycle_model=first.event_lifecycle_model,
            debris_risk_model=first.debris_risk_model,
            autonomy_model=first.autonomy_model,
            power_model=first.power_model,
            thermal_model=first.thermal_model,
            target_model=first.target_model,
            pointing_model=first.pointing_model,
            packet_model=first.packet_model,
            packet_delivery_model=first.packet_delivery_model,
            packet_drop_fraction_proxy=first.packet_drop_fraction_proxy,
            start_year=first.start_year,
            years_after_start=point,
            survival_probability=fmean(
                _survives_offset(sample, point) for sample in samples
            ),
            samples=len(samples),
        )
        for point in grid
    ]


def _validate_selector(
    value: str,
    name: str,
    choices: Sequence[str],
) -> None:
    if value not in choices:
        allowed = ", ".join(choices)
        raise ValueError(f"{name} must be one of: {allowed}")


def _lifecycle_counter_snapshot(simulator: object) -> tuple[int, int, int]:
    manager = getattr(simulator, "lifecycle_manager", None)
    if manager is None:
        return 0, 0, 0
    diagnostics = manager.diagnostics()
    return (
        diagnostics.lifecycle_uploaded_count,
        diagnostics.lifecycle_resolved_success_count,
        diagnostics.lifecycle_resolved_failed_count,
    )


def estimate_remaining_useful_life(
    *,
    policy_name: str,
    scenario_name: str,
    start_year: float = 8.0,
    horizon_years: float = 5.0,
    samples: int = 50,
    seed: int = 0,
    config: SimulationConfig = DEFAULT_CONFIG,
    contact_model_name: str = "synthetic",
    contact_model_factory: ContactModelFactory | None = None,
    operator_view: str = "omniscient",
    planning_model: str = "reactive",
    maneuver_model: str = "none",
    orbit_evolution_model: str = "fixed",
    stationkeeping_planning_model: str = "legacy",
    event_lifecycle_model: str = "none",
    debris_risk_model: str = "legacy",
    autonomy_model: str = "none",
    power_model: str = "legacy",
    thermal_model: str = "legacy",
    target_model: str = "legacy",
    pointing_model: str = "legacy",
    packet_model: str = "legacy",
    packet_delivery_model: str = "ideal",
    packet_drop_fraction_proxy: float | None = None,
    event_catalog_factory: EventCatalogFactory | None = None,
    simulator_factory: SimulatorFactory | None = None,
) -> tuple[list[RULSample], RULSummary, list[SurvivalCurvePoint]]:
    """Estimate horizon-censored RUL by warm-up and defensive continuation.

    Each stochastic sample receives one catalog covering warm-up plus
    continuation. The warmed Simulator instance is reused so delayed telemetry
    and already-resolved event state continue naturally; only the start
    SatelliteState is defensively copied for the continuation call.
    """
    if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
        raise ValueError("samples must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    start_hour = _years_to_hours(start_year, "start_year", config)
    horizon_hours = _years_to_hours(
        horizon_years, "horizon_years", config
    )
    total_hours = start_hour + horizon_hours
    scenario_key = scenario_name.lower()
    contact_key = contact_model_name.lower()
    resolved_drop_fraction = (
        config.packet_drop_fraction_proxy
        if packet_drop_fraction_proxy is None
        else packet_drop_fraction_proxy
    )
    if contact_key not in {"synthetic", "geometry"}:
        raise ValueError(
            f"Unknown contact model {contact_model_name!r}; "
            "choose one of: geometry, synthetic"
        )
    _validate_selector(operator_view, "operator_view", OPERATOR_VIEWS)
    _validate_selector(planning_model, "planning_model", PLANNING_MODELS)
    _validate_selector(maneuver_model, "maneuver_model", MANEUVER_MODELS)
    _validate_selector(
        orbit_evolution_model,
        "orbit_evolution_model",
        ORBIT_EVOLUTION_MODELS,
    )
    _validate_selector(
        stationkeeping_planning_model,
        "stationkeeping_planning_model",
        STATIONKEEPING_PLANNING_MODELS,
    )
    _validate_selector(
        event_lifecycle_model,
        "event_lifecycle_model",
        EVENT_LIFECYCLE_MODELS,
    )
    _validate_selector(
        debris_risk_model, "debris_risk_model", DEBRIS_RISK_MODELS
    )
    _validate_selector(autonomy_model, "autonomy_model", AUTONOMY_MODELS)
    _validate_selector(power_model, "power_model", POWER_MODELS)
    _validate_selector(thermal_model, "thermal_model", THERMAL_MODELS)
    _validate_selector(target_model, "target_model", TARGET_MODELS)
    _validate_selector(pointing_model, "pointing_model", POINTING_MODELS)
    _validate_selector(packet_model, "packet_model", PACKET_MODELS)
    _validate_selector(
        packet_delivery_model,
        "packet_delivery_model",
        PACKET_DELIVERY_MODELS,
    )
    if packet_model == "legacy" and packet_delivery_model != "ideal":
        raise ValueError(
            "non-ideal packet delivery requires packet_model='packet_proxy'"
        )
    if (
        not isinstance(resolved_drop_fraction, (int, float))
        or isinstance(resolved_drop_fraction, bool)
        or not isfinite(resolved_drop_fraction)
        or not 0.0 <= resolved_drop_fraction <= 1.0
    ):
        raise ValueError("packet_drop_fraction_proxy must be in [0, 1]")
    catalog_builder = (
        event_catalog_factory
        if event_catalog_factory is not None
        else generate_stochastic_event_catalog
    )

    if simulator_factory is None:
        def build_simulator(
            sample_seed: int, catalog: EventCatalog | None
        ) -> Simulator:
            contact_model = (
                contact_model_factory(config)
                if contact_model_factory is not None
                else _default_contact_model(contact_key, config)
            )
            scenario = make_scenario(
                scenario_key,
                config,
                seed=sample_seed,
                total_hours=total_hours,
                event_catalog=catalog,
            )
            return Simulator(
                make_policy(policy_name, config),
                scenario,
                config,
                contact_model=contact_model,
                operator_view=operator_view,
                planning_model=planning_model,
                maneuver_model=maneuver_model,
                orbit_evolution_model=orbit_evolution_model,
                stationkeeping_planning_model=(
                    stationkeeping_planning_model
                ),
                event_lifecycle_model=event_lifecycle_model,
                debris_risk_model=debris_risk_model,
                autonomy_model=autonomy_model,
                power_model=power_model,
                thermal_model=thermal_model,
                target_model=target_model,
                pointing_model=pointing_model,
                packet_model=packet_model,
                packet_delivery_model=packet_delivery_model,
                packet_delivery_seed=sample_seed,
                packet_drop_fraction_proxy=resolved_drop_fraction,
            )
    else:
        build_simulator = simulator_factory

    sample_rows: list[RULSample] = []
    for sample_index in range(samples):
        sample_seed = seed + sample_index
        catalog = None
        if scenario_key == STOCHASTIC_SCENARIO:
            catalog = catalog_builder(
                sample_seed, scenario_key, total_hours, config
            )
        simulator = build_simulator(sample_seed, catalog)
        if packet_model == "packet_proxy" and hasattr(
            simulator, "packet_delivery_seed"
        ):
            simulator.packet_delivery_seed = sample_seed
        warmup_result = simulator.run(start_year)
        start_state = deepcopy(warmup_result.state)
        warmup_contingency_uploads = getattr(
            warmup_result, "contingency_plan_upload_count", 0
        )
        warmup_autonomous_actions = getattr(
            warmup_result, "autonomous_action_count", 0
        )
        warmup_lifecycle_counts = _lifecycle_counter_snapshot(simulator)
        warmup_failed = (
            not start_state.alive
            or start_state.hours_completed < start_hour
        )
        alive_at_start = not warmup_failed

        if alive_at_start and start_state.hours_completed != start_hour:
            raise RuntimeError(
                "warm-up completed at an unexpected mission hour: "
                f"expected {start_hour}, got {start_state.hours_completed}"
            )

        contingency_plan_uploads_during_rul = 0
        autonomous_actions_during_rul = 0
        lifecycle_uploads_during_rul = 0
        lifecycle_resolved_success_during_rul = 0
        lifecycle_resolved_failed_during_rul = 0
        telemetry_delivery_failures_during_rul = 0
        command_packet_failures_during_rul = 0
        daily_plan_packet_failures_during_rul = 0
        thermal_stress_hours_during_rul = 0
        target_area_imaged_during_rul_km2 = 0.0
        if warmup_failed:
            final_state = start_state
            additional_hours = 0
            survived_to_horizon = False
        else:
            continuation_result = simulator.run(
                horizon_years,
                state=deepcopy(start_state),
                start_hour=start_hour,
            )
            final_state = continuation_result.state
            additional_hours = max(
                0,
                min(
                    horizon_hours,
                    final_state.hours_completed - start_state.hours_completed,
                ),
            )
            survived_to_horizon = (
                final_state.alive and additional_hours == horizon_hours
            )
            contingency_plan_uploads_during_rul = max(
                0,
                getattr(
                    continuation_result,
                    "contingency_plan_upload_count",
                    0,
                )
                - warmup_contingency_uploads,
            )
            autonomous_actions_during_rul = max(
                0,
                getattr(
                    continuation_result, "autonomous_action_count", 0
                )
                - warmup_autonomous_actions,
            )
            lifecycle_after = _lifecycle_counter_snapshot(simulator)
            lifecycle_uploads_during_rul = max(
                0,
                lifecycle_after[0] - warmup_lifecycle_counts[0],
            )
            lifecycle_resolved_success_during_rul = max(
                0,
                lifecycle_after[1] - warmup_lifecycle_counts[1],
            )
            lifecycle_resolved_failed_during_rul = max(
                0,
                lifecycle_after[2] - warmup_lifecycle_counts[2],
            )
            telemetry_delivery_failures_during_rul = getattr(
                continuation_result, "telemetry_delivery_failures", 0
            )
            command_packet_failures_during_rul = getattr(
                continuation_result, "command_packet_failures", 0
            )
            daily_plan_packet_failures_during_rul = getattr(
                continuation_result, "daily_plan_packet_failures", 0
            )
            thermal_stress_hours_during_rul = getattr(
                continuation_result, "thermal_stress_hours", 0
            )
            target_area_imaged_during_rul_km2 = getattr(
                continuation_result, "target_area_imaged_km2", 0.0
            )

        risk_driver, risk_margin = classify_risk_driver(
            final_state,
            config,
            maneuver_model=maneuver_model,
            orbit_evolution_model=orbit_evolution_model,
        )
        loss_reason = (
            final_state.loss_reason.value
            if final_state.loss_reason is not None
            else None
        )
        sample_rows.append(RULSample(
            policy=policy_name,
            scenario=scenario_key,
            operator_view=operator_view,
            planning_model=planning_model,
            maneuver_model=maneuver_model,
            orbit_evolution_model=orbit_evolution_model,
            contact_model=contact_key,
            sample_seed=sample_seed,
            start_year=start_year,
            horizon_years=horizon_years,
            warmup_failed=warmup_failed,
            alive_at_start=alive_at_start,
            survived_to_horizon=survived_to_horizon,
            additional_hours_survived=additional_hours,
            additional_years_survived=(
                additional_hours / config.hours_per_year
            ),
            loss_reason=loss_reason,
            risk_driver=risk_driver,
            risk_margin=risk_margin,
            start_soc=start_state.soc,
            start_health=start_state.total_health(config),
            start_delta_v_remaining_m_per_s=(
                start_state.delta_v_remaining_m_per_s
            ),
            start_fuel_remaining_percent=_fuel_remaining_percent(
                start_state, config
            ),
            start_orbit_drift_proxy_km=start_state.orbit_drift_proxy_km,
            final_soc=final_state.soc,
            final_health=final_state.total_health(config),
            final_delta_v_remaining_m_per_s=(
                final_state.delta_v_remaining_m_per_s
            ),
            final_fuel_remaining_percent=_fuel_remaining_percent(
                final_state, config
            ),
            final_orbit_drift_proxy_km=final_state.orbit_drift_proxy_km,
            data_downlinked_during_rul_gb=max(
                0.0,
                final_state.total_data_downlinked_gb
                - start_state.total_data_downlinked_gb,
            ),
            data_generated_during_rul_gb=max(
                0.0,
                final_state.total_data_generated_gb
                - start_state.total_data_generated_gb,
            ),
            debris_avoidance_executed_during_rul=max(
                0,
                final_state.debris_avoidance_executed_count
                - start_state.debris_avoidance_executed_count,
            ),
            debris_avoidance_skipped_during_rul=max(
                0,
                final_state.debris_avoidance_skipped_count
                - start_state.debris_avoidance_skipped_count,
            ),
            maneuver_count_during_rul=max(
                0,
                final_state.maneuver_count - start_state.maneuver_count,
            ),
            orbit_correction_count_during_rul=max(
                0,
                final_state.orbit_correction_count
                - start_state.orbit_correction_count,
            ),
            stationkeeping_planning_model=(
                stationkeeping_planning_model
            ),
            event_lifecycle_model=event_lifecycle_model,
            debris_risk_model=debris_risk_model,
            autonomy_model=autonomy_model,
            power_model=power_model,
            thermal_model=thermal_model,
            target_model=target_model,
            pointing_model=pointing_model,
            packet_model=packet_model,
            packet_delivery_model=packet_delivery_model,
            packet_drop_fraction_proxy=resolved_drop_fraction,
            contingency_plan_uploads_during_rul=(
                contingency_plan_uploads_during_rul
            ),
            autonomous_actions_during_rul=(
                autonomous_actions_during_rul
            ),
            lifecycle_uploads_during_rul=lifecycle_uploads_during_rul,
            lifecycle_resolved_success_during_rul=(
                lifecycle_resolved_success_during_rul
            ),
            lifecycle_resolved_failed_during_rul=(
                lifecycle_resolved_failed_during_rul
            ),
            telemetry_delivery_failures_during_rul=(
                telemetry_delivery_failures_during_rul
            ),
            command_packet_failures_during_rul=(
                command_packet_failures_during_rul
            ),
            daily_plan_packet_failures_during_rul=(
                daily_plan_packet_failures_during_rul
            ),
            thermal_stress_hours_during_rul=(
                thermal_stress_hours_during_rul
            ),
            target_area_imaged_during_rul_km2=(
                target_area_imaged_during_rul_km2
            ),
        ))

    summary = summarize_rul_samples(sample_rows)
    curve = build_survival_curve(sample_rows)
    return sample_rows, summary, curve


__all__ = [
    "RULSample",
    "RULSummary",
    "SurvivalCurvePoint",
    "build_survival_curve",
    "classify_risk_driver",
    "estimate_remaining_useful_life",
    "risk_margins",
    "summarize_rul_samples",
]
