"""Conditional statistical interpretation of existing RUL sample rows.

This module never runs the simulator. Its intervals quantify finite Monte Carlo
sample uncertainty in the bounded proxy outputs, not physical spacecraft or
KazEOSat-1 reliability uncertainty.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from math import sqrt
from random import Random
from statistics import fmean, median
from typing import Sequence

from .rul import (
    RUL_PROVENANCE_FIELDS,
    RULSample,
    _percentile,
    _survives_offset,
    validate_homogeneous_rul_samples,
)


DEFAULT_BOOTSTRAP_REPLICATES = 1000
DEFAULT_BOOTSTRAP_SEED = 390
WILSON_95_Z = 1.959963984540054


@dataclass(frozen=True)
class ReliabilityProvenance:
    """Shared simulation-population and statistical-analysis provenance."""

    policy: str
    scenario: str
    operator_view: str
    planning_model: str
    maneuver_model: str
    orbit_evolution_model: str
    contact_model: str
    stationkeeping_planning_model: str
    event_lifecycle_model: str
    debris_risk_model: str
    autonomy_model: str
    power_model: str
    thermal_model: str
    target_model: str
    pointing_model: str
    packet_model: str
    packet_delivery_model: str
    packet_drop_fraction_proxy: float
    start_year: float
    horizon_years: float
    bootstrap_seed: int
    bootstrap_replicates: int


@dataclass(frozen=True)
class ConditionalRULSummary(ReliabilityProvenance):
    """RUL statistics conditioned on being alive at the start year.

    ``conditional_expected_rul_years_censored`` is the restricted mean over
    bounded durations under the shared administrative horizon.
    """

    total_samples: int
    alive_at_start_samples: int
    warmup_failed_samples: int
    alive_at_start_fraction: float
    conditional_survived_to_horizon_fraction: float | None
    conditional_expected_rul_years_censored: float | None
    conditional_expected_rul_years_censored_ci95_lower: float | None
    conditional_expected_rul_years_censored_ci95_upper: float | None
    conditional_median_rul_years_censored: float | None
    conditional_p05_rul_years_censored: float | None
    conditional_p95_rul_years_censored: float | None
    conditional_probability_survive_plus_1y: float | None
    conditional_probability_survive_plus_2y: float | None
    conditional_probability_survive_plus_3y: float | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ConditionalSurvivalCurvePoint(ReliabilityProvenance):
    """Conditional empirical survival with a 95% Wilson interval."""

    years_after_start: float
    conditional_survival_probability: float
    conditional_survival_ci95_lower: float
    conditional_survival_ci95_upper: float
    alive_at_start_samples: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FailureModeDistributionRow(ReliabilityProvenance):
    """Loss reasons for conditional samples not surviving through horizon."""

    loss_reason: str | None
    failure_count: int
    fraction_of_conditional_failures: float
    fraction_of_alive_at_start_samples: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CensoredSurvivorRiskDistributionRow(ReliabilityProvenance):
    """Nearest proxy risk drivers among horizon-censored survivors."""

    risk_driver: str
    survivor_count: int
    fraction_of_horizon_survivors: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _validate_bootstrap(
    bootstrap_replicates: int, bootstrap_seed: int
) -> None:
    if (
        not isinstance(bootstrap_replicates, int)
        or isinstance(bootstrap_replicates, bool)
        or bootstrap_replicates <= 0
    ):
        raise ValueError("bootstrap_replicates must be a positive integer")
    if not isinstance(bootstrap_seed, int) or isinstance(bootstrap_seed, bool):
        raise ValueError("bootstrap_seed must be an integer")


def _provenance(
    first: RULSample,
    bootstrap_replicates: int,
    bootstrap_seed: int,
) -> dict[str, object]:
    values = {field: getattr(first, field) for field in RUL_PROVENANCE_FIELDS}
    values.update({
        "bootstrap_seed": bootstrap_seed,
        "bootstrap_replicates": bootstrap_replicates,
    })
    return values


def _conditional_samples(samples: Sequence[RULSample]) -> list[RULSample]:
    return [sample for sample in samples if sample.alive_at_start is True]


def _bounded_duration(sample: RULSample, horizon_years: float) -> float:
    return min(horizon_years, max(0.0, sample.additional_years_survived))


def wilson_interval(
    successes: int,
    trials: int,
    *,
    z: float = WILSON_95_Z,
) -> tuple[float, float]:
    """Return the two-sided Wilson score interval for a binomial proportion."""
    if (
        not isinstance(successes, int)
        or isinstance(successes, bool)
        or not isinstance(trials, int)
        or isinstance(trials, bool)
        or trials <= 0
        or not 0 <= successes <= trials
    ):
        raise ValueError(
            "successes and trials must satisfy 0 <= successes <= trials"
        )
    proportion = successes / trials
    z_squared = z * z
    denominator = 1.0 + z_squared / trials
    center = (proportion + z_squared / (2.0 * trials)) / denominator
    half_width = (
        z
        * sqrt(
            proportion * (1.0 - proportion) / trials
            + z_squared / (4.0 * trials * trials)
        )
        / denominator
    )
    return max(0.0, center - half_width), min(1.0, center + half_width)


def _bootstrap_mean_interval(
    samples: Sequence[RULSample],
    *,
    horizon_years: float,
    bootstrap_replicates: int,
    bootstrap_seed: int,
) -> tuple[float, float]:
    rng = Random(bootstrap_seed)
    sample_count = len(samples)
    replicate_means = [
        fmean(
            _bounded_duration(rng.choice(samples), horizon_years)
            for _ in range(sample_count)
        )
        for _ in range(bootstrap_replicates)
    ]
    return (
        _percentile(replicate_means, 0.025),
        _percentile(replicate_means, 0.975),
    )


def summarize_conditional_rul(
    samples: Sequence[RULSample],
    *,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> ConditionalRULSummary:
    """Summarize bounded RUL only among samples alive at ``start_year``."""
    first = validate_homogeneous_rul_samples(samples)
    _validate_bootstrap(bootstrap_replicates, bootstrap_seed)
    eligible = _conditional_samples(samples)
    total = len(samples)
    count = len(eligible)
    provenance = _provenance(first, bootstrap_replicates, bootstrap_seed)
    common = {
        **provenance,
        "total_samples": total,
        "alive_at_start_samples": count,
        "warmup_failed_samples": sum(sample.warmup_failed for sample in samples),
        "alive_at_start_fraction": count / total,
    }
    if not eligible:
        return ConditionalRULSummary(
            **common,
            conditional_survived_to_horizon_fraction=None,
            conditional_expected_rul_years_censored=None,
            conditional_expected_rul_years_censored_ci95_lower=None,
            conditional_expected_rul_years_censored_ci95_upper=None,
            conditional_median_rul_years_censored=None,
            conditional_p05_rul_years_censored=None,
            conditional_p95_rul_years_censored=None,
            conditional_probability_survive_plus_1y=None,
            conditional_probability_survive_plus_2y=None,
            conditional_probability_survive_plus_3y=None,
        )

    durations = [
        _bounded_duration(sample, first.horizon_years)
        for sample in eligible
    ]
    mean_lower, mean_upper = _bootstrap_mean_interval(
        eligible,
        horizon_years=first.horizon_years,
        bootstrap_replicates=bootstrap_replicates,
        bootstrap_seed=bootstrap_seed,
    )

    def survival_probability(years: float) -> float | None:
        if first.horizon_years < years:
            return None
        return fmean(_survives_offset(sample, years) for sample in eligible)

    return ConditionalRULSummary(
        **common,
        conditional_survived_to_horizon_fraction=fmean(
            sample.survived_to_horizon for sample in eligible
        ),
        conditional_expected_rul_years_censored=fmean(durations),
        conditional_expected_rul_years_censored_ci95_lower=mean_lower,
        conditional_expected_rul_years_censored_ci95_upper=mean_upper,
        conditional_median_rul_years_censored=median(durations),
        conditional_p05_rul_years_censored=_percentile(durations, 0.05),
        conditional_p95_rul_years_censored=_percentile(durations, 0.95),
        conditional_probability_survive_plus_1y=survival_probability(1.0),
        conditional_probability_survive_plus_2y=survival_probability(2.0),
        conditional_probability_survive_plus_3y=survival_probability(3.0),
    )


def build_conditional_survival_curve(
    samples: Sequence[RULSample],
    *,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> list[ConditionalSurvivalCurvePoint]:
    """Build conditional empirical survival proportions and Wilson intervals."""
    first = validate_homogeneous_rul_samples(samples)
    _validate_bootstrap(bootstrap_replicates, bootstrap_seed)
    eligible = _conditional_samples(samples)
    if not eligible:
        return []
    provenance = _provenance(first, bootstrap_replicates, bootstrap_seed)
    grid = sorted({
        point
        for point in (0.0, 1.0, 2.0, 3.0, first.horizon_years)
        if point <= first.horizon_years
    })
    rows = []
    for point in grid:
        if point == 0.0:
            probability = lower = upper = 1.0
        else:
            successes = sum(
                _survives_offset(sample, point) for sample in eligible
            )
            probability = successes / len(eligible)
            lower, upper = wilson_interval(successes, len(eligible))
        rows.append(
            ConditionalSurvivalCurvePoint(
                **provenance,
                years_after_start=point,
                conditional_survival_probability=probability,
                conditional_survival_ci95_lower=lower,
                conditional_survival_ci95_upper=upper,
                alive_at_start_samples=len(eligible),
            )
        )
    return rows


def build_failure_mode_distribution(
    samples: Sequence[RULSample],
    *,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> list[FailureModeDistributionRow]:
    """Count loss reasons for conditional samples failing by the horizon."""
    first = validate_homogeneous_rul_samples(samples)
    _validate_bootstrap(bootstrap_replicates, bootstrap_seed)
    eligible = _conditional_samples(samples)
    failures = [sample for sample in eligible if not sample.survived_to_horizon]
    if not failures:
        return []
    counts = Counter(sample.loss_reason for sample in failures)
    provenance = _provenance(first, bootstrap_replicates, bootstrap_seed)
    return [
        FailureModeDistributionRow(
            **provenance,
            loss_reason=reason,
            failure_count=count,
            fraction_of_conditional_failures=count / len(failures),
            fraction_of_alive_at_start_samples=count / len(eligible),
        )
        for reason, count in sorted(counts.items(), key=lambda item: str(item[0]))
    ]


def build_censored_survivor_risk_distribution(
    samples: Sequence[RULSample],
    *,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> list[CensoredSurvivorRiskDistributionRow]:
    """Describe nearest proxy risk drivers among horizon-censored survivors."""
    first = validate_homogeneous_rul_samples(samples)
    _validate_bootstrap(bootstrap_replicates, bootstrap_seed)
    survivors = [
        sample
        for sample in _conditional_samples(samples)
        if sample.survived_to_horizon
    ]
    if not survivors:
        return []
    counts = Counter(sample.risk_driver for sample in survivors)
    provenance = _provenance(first, bootstrap_replicates, bootstrap_seed)
    return [
        CensoredSurvivorRiskDistributionRow(
            **provenance,
            risk_driver=driver,
            survivor_count=count,
            fraction_of_horizon_survivors=count / len(survivors),
        )
        for driver, count in sorted(counts.items())
    ]


__all__ = [
    "DEFAULT_BOOTSTRAP_REPLICATES",
    "DEFAULT_BOOTSTRAP_SEED",
    "CensoredSurvivorRiskDistributionRow",
    "ConditionalRULSummary",
    "ConditionalSurvivalCurvePoint",
    "FailureModeDistributionRow",
    "build_censored_survivor_risk_distribution",
    "build_conditional_survival_curve",
    "build_failure_mode_distribution",
    "summarize_conditional_rul",
    "wilson_interval",
]
