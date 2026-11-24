"""Internal consistency, public-reference, and sensitivity helpers.

These checks validate research-output structure inside this proxy project. They
do not validate spacecraft truth, operational performance, or KazEOSat-1 data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, fields
from math import isclose, isfinite
from typing import Mapping, Sequence

from .analysis import compute_ablation_deltas
from .config import DEFAULT_CONFIG, SimulationConfig
from .research_design import (
    FINAL_V40_CONFIGURATION,
    MODEL_SELECTOR_FIELDS,
    ExperimentConfiguration,
)


PASS = "pass"
FAIL = "fail"
WARNING = "warning"
NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ValidationCheck:
    """One internal research-output consistency check."""

    check_id: str
    category: str
    status: str
    observed: str
    expected_or_rule: str
    details: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationSummaryRow:
    """Count of internal checks by category and status."""

    category: str
    status: str
    check_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PublicSpecSanityRow:
    """One public-reference relationship; never a calibration claim."""

    check_id: str
    reference_quantity: str
    public_reference: str
    implemented_proxy: str
    relationship: str
    status: str
    interpretation: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


VALIDATION_CHECK_FIELDS = tuple(field.name for field in fields(ValidationCheck))
VALIDATION_SUMMARY_FIELDS = tuple(
    field.name for field in fields(ValidationSummaryRow)
)
PUBLIC_SPEC_SANITY_FIELDS = tuple(
    field.name for field in fields(PublicSpecSanityRow)
)

LAYER_SENSITIVITY_METRICS = (
    "simulator_score",
    "survival_fraction",
    "data_downlinked_gb",
    "final_health",
    "fuel_remaining_percent",
    "stationkeeping_selected_count",
    "stationkeeping_deferred_count",
    "telemetry_delivery_failures",
    "command_packet_failures",
    "packet_delivery_failure_events",
    "thermal_stress_hours",
    "target_area_imaged_km2",
)
LAYER_SENSITIVITY_FIELDS = (
    "suite_profile",
    "reference_configuration",
    "comparison_configuration",
    "policy",
    "scenario",
    *(
        field
        for metric in LAYER_SENSITIVITY_METRICS
        for field in (
            f"{metric}_baseline",
            f"{metric}_comparison",
            f"{metric}_delta",
        )
    ),
)


def _as_float(value: object) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _equivalent(left: object, right: object) -> bool:
    left_number = _as_float(left)
    right_number = _as_float(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return left == right or str(left) == str(right)


def _status(condition: bool) -> str:
    return PASS if condition else FAIL


def _check(
    check_id: str,
    category: str,
    condition: bool,
    observed: object,
    expected_or_rule: str,
    details: str,
) -> ValidationCheck:
    return ValidationCheck(
        check_id=check_id,
        category=category,
        status=_status(condition),
        observed=str(observed),
        expected_or_rule=expected_or_rule,
        details=details,
    )


def _not_applicable(
    check_id: str,
    category: str,
    details: str,
) -> ValidationCheck:
    return ValidationCheck(
        check_id=check_id,
        category=category,
        status=NOT_APPLICABLE,
        observed="no applicable rows",
        expected_or_rule="check applies only when the relevant rows exist",
        details=details,
    )


def _configuration_mismatches(
    rows: Sequence[Mapping[str, object]],
    configuration: ExperimentConfiguration,
) -> list[str]:
    expected = configuration.selector_provenance()
    mismatches: list[str] = []
    for index, row in enumerate(rows):
        for field, value in expected.items():
            if field not in row or not _equivalent(row.get(field), value):
                mismatches.append(f"row {index} {field}")
    return mismatches


def _has_missing_selectors(
    rows: Sequence[Mapping[str, object]],
) -> list[str]:
    missing: list[str] = []
    for index, row in enumerate(rows):
        for field in MODEL_SELECTOR_FIELDS:
            if field not in row or row.get(field) is None or row.get(field) == "":
                missing.append(f"row {index} {field}")
    return missing


def _numeric_sanity_failures(
    named_rows: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[str]:
    failures: list[str] = []
    for table_name, rows in named_rows.items():
        for index, row in enumerate(rows):
            for field, value in row.items():
                if isinstance(value, bool) or value is None or value == "":
                    continue
                if isinstance(value, (int, float)) and not isfinite(float(value)):
                    failures.append(f"{table_name}[{index}].{field}")
                elif isinstance(value, str) and value.strip().lower() in {
                    "nan", "+nan", "-nan", "inf", "+inf", "-inf",
                    "infinity", "+infinity", "-infinity",
                }:
                    failures.append(f"{table_name}[{index}].{field}")
    return failures


def _is_bounded_field(field: str) -> bool:
    return (
        field.endswith("_fraction")
        or "probability" in field
        or field.startswith("fraction_of_")
        or field in {
            "survival_probability",
            "conditional_survival_ci95_lower",
            "conditional_survival_ci95_upper",
            "packet_drop_fraction_proxy",
        }
    )


def _bounded_fraction_failures(
    named_rows: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[str]:
    failures: list[str] = []
    for table_name, rows in named_rows.items():
        for index, row in enumerate(rows):
            for field, value in row.items():
                if not _is_bounded_field(field):
                    continue
                number = _as_float(value)
                if number is not None and not 0.0 <= number <= 1.0:
                    failures.append(f"{table_name}[{index}].{field}")
    return failures


def _by_policy(
    rows: Sequence[Mapping[str, object]],
) -> dict[object, list[Mapping[str, object]]]:
    grouped: dict[object, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("policy")].append(row)
    return grouped


def _sample_population(
    rows: Sequence[Mapping[str, object]],
) -> tuple[int, int, int, int, int]:
    """Return total, eligible, warm-up-failed, survivor, and failure counts."""
    alive = [row for row in rows if row.get("alive_at_start") is True]
    return (
        len(rows),
        len(alive),
        sum(row.get("warmup_failed") is True for row in rows),
        sum(row.get("survived_to_horizon") is True for row in alive),
        sum(row.get("survived_to_horizon") is False for row in alive),
    )


def _matches_fraction(value: object, expected: float) -> bool:
    number = _as_float(value)
    return number is not None and isclose(
        number, expected, rel_tol=1e-12, abs_tol=1e-12
    )


def build_internal_validation_checks(
    *,
    core_rows: Sequence[Mapping[str, object]],
    rul_sample_rows: Sequence[Mapping[str, object]] = (),
    conditional_summary_rows: Sequence[Mapping[str, object]] = (),
    conditional_survival_rows: Sequence[Mapping[str, object]] = (),
    failure_mode_rows: Sequence[Mapping[str, object]] = (),
    survivor_risk_rows: Sequence[Mapping[str, object]] = (),
    additional_numeric_tables: Mapping[
        str, Sequence[Mapping[str, object]]
    ] | None = None,
    configuration: ExperimentConfiguration = FINAL_V40_CONFIGURATION,
) -> list[ValidationCheck]:
    """Build hard structural checks for final research outputs."""
    checks: list[ValidationCheck] = []

    core_mismatches = _configuration_mismatches(core_rows, configuration)
    checks.append(_check(
        "core_provenance_matches_final_configuration",
        "provenance",
        bool(core_rows) and not core_mismatches,
        f"{len(core_mismatches)} mismatches across {len(core_rows)} rows",
        "every final core selector equals the canonical configuration",
        "; ".join(core_mismatches[:5]) or "all core selectors agree",
    ))
    missing = _has_missing_selectors(core_rows)
    checks.append(_check(
        "core_selectors_complete",
        "provenance",
        bool(core_rows) and not missing,
        f"{len(missing)} missing values",
        "all authoritative selector values are present",
        "; ".join(missing[:5]) or "no missing selector values",
    ))
    seed_mismatches = [
        index for index, row in enumerate(core_rows)
        if not _equivalent(row.get("packet_delivery_seed"), row.get("seed"))
    ]
    checks.append(_check(
        "core_packet_seed_matches_experiment_seed",
        "provenance",
        bool(core_rows) and not seed_mismatches,
        f"{len(seed_mismatches)} mismatches",
        "packet_delivery_seed equals experiment seed",
        (
            f"mismatched rows: {seed_mismatches[:5]}"
            if seed_mismatches else "all packet seeds agree"
        ),
    ))

    if rul_sample_rows:
        rul_mismatches = _configuration_mismatches(
            rul_sample_rows, configuration
        )
        label_mismatches = [
            index for index, row in enumerate(rul_sample_rows)
            if row.get("rul_configuration") != configuration.label
        ]
        checks.append(_check(
            "rul_provenance_matches_core_configuration",
            "configuration_identity",
            not rul_mismatches and not label_mismatches,
            (
                f"{len(rul_mismatches)} selector mismatches; "
                f"{len(label_mismatches)} label mismatches"
            ),
            "final RUL uses the same canonical configuration as final core",
            "; ".join(rul_mismatches[:5]) or "all RUL selectors agree",
        ))
    else:
        checks.append(_not_applicable(
            "rul_provenance_matches_core_configuration",
            "configuration_identity",
            "RUL generation was skipped",
        ))

    numeric_tables: dict[str, Sequence[Mapping[str, object]]] = {
        "core": core_rows,
        "rul_samples": rul_sample_rows,
        "conditional_summary": conditional_summary_rows,
        "conditional_survival": conditional_survival_rows,
        "failure_modes": failure_mode_rows,
        "survivor_risks": survivor_risk_rows,
        **(additional_numeric_tables or {}),
    }
    numeric_failures = _numeric_sanity_failures(numeric_tables)
    checks.append(_check(
        "defined_numeric_outputs_are_finite",
        "numeric_sanity",
        not numeric_failures,
        f"{len(numeric_failures)} non-finite values",
        "every defined numeric output is finite",
        "; ".join(numeric_failures[:5]) or "all defined numbers are finite",
    ))
    bounded_failures = _bounded_fraction_failures(numeric_tables)
    checks.append(_check(
        "fractions_and_probabilities_are_bounded",
        "bounded_fractions",
        not bounded_failures,
        f"{len(bounded_failures)} out-of-range values",
        "mathematical fractions and probabilities are within [0, 1]",
        "; ".join(bounded_failures[:5]) or "all bounded values are valid",
    ))

    sample_groups = _by_policy(rul_sample_rows)
    summary_groups = _by_policy(conditional_summary_rows)
    conditional_scalar_fields = (
        "conditional_survived_to_horizon_fraction",
        "conditional_expected_rul_years_censored",
        "conditional_expected_rul_years_censored_ci95_lower",
        "conditional_expected_rul_years_censored_ci95_upper",
        "conditional_median_rul_years_censored",
        "conditional_p05_rul_years_censored",
        "conditional_p95_rul_years_censored",
        "conditional_probability_survive_plus_1y",
        "conditional_probability_survive_plus_2y",
        "conditional_probability_survive_plus_3y",
    )
    if conditional_summary_rows or rul_sample_rows:
        accounting_failures: list[str] = []
        zero_semantic_failures: list[str] = []
        for policy, summary_rows in summary_groups.items():
            label = repr(policy)
            samples_for_policy = sample_groups.get(policy, [])
            if len(summary_rows) != 1:
                accounting_failures.append(
                    f"{label}: {len(summary_rows)} summary rows"
                )
            summary = summary_rows[0]
            if not samples_for_policy:
                accounting_failures.append(f"{label}: no RUL sample rows")
                actual_alive = int(summary["alive_at_start_samples"])
            else:
                (
                    actual_total,
                    actual_alive,
                    actual_warmup,
                    actual_survivors,
                    _,
                ) = _sample_population(samples_for_policy)
                summary_total = int(summary["total_samples"])
                summary_alive = int(summary["alive_at_start_samples"])
                summary_warmup = int(summary["warmup_failed_samples"])
                consistent = (
                    summary_total == actual_total
                    and summary_alive == actual_alive
                    and summary_warmup == actual_warmup
                    and _matches_fraction(
                        summary.get("alive_at_start_fraction"),
                        actual_alive / actual_total,
                    )
                )
                conditional_fraction = summary.get(
                    "conditional_survived_to_horizon_fraction"
                )
                if actual_alive:
                    consistent = consistent and _matches_fraction(
                        conditional_fraction,
                        actual_survivors / actual_alive,
                    )
                else:
                    consistent = consistent and conditional_fraction in (
                        None,
                        "",
                    )
                if not consistent:
                    accounting_failures.append(
                        f"{label}: summary does not match sample rows"
                    )
            if actual_alive == 0 and any(
                summary.get(field) not in (None, "")
                for field in conditional_scalar_fields
            ):
                zero_semantic_failures.append(label)
        for policy in sample_groups.keys() - summary_groups.keys():
            accounting_failures.append(
                f"{policy!r}: no conditional summary row"
            )
        checks.append(_check(
            "rul_population_accounting",
            "rul_population",
            not accounting_failures,
            f"{len(accounting_failures)} inconsistencies",
            (
                "conditional summary counts and fractions equal the actual "
                "per-policy RUL sample population"
            ),
            "; ".join(accounting_failures) or "all populations reconcile",
        ))
        checks.append(_check(
            "zero_eligible_population_semantics",
            "rul_population",
            not zero_semantic_failures,
            f"{len(zero_semantic_failures)} inconsistent policies",
            "all conditional scalars are unavailable with zero eligible samples",
            "; ".join(zero_semantic_failures) or "zero-population semantics hold",
        ))
    else:
        checks.extend((
            _not_applicable(
                "rul_population_accounting",
                "rul_population",
                "conditional RUL analysis was not generated",
            ),
            _not_applicable(
                "zero_eligible_population_semantics",
                "rul_population",
                "conditional RUL analysis was not generated",
            ),
        ))

    if conditional_survival_rows or rul_sample_rows:
        interval_failures: list[str] = []
        t0_failures: list[str] = []
        for index, row in enumerate(conditional_survival_rows):
            estimate = float(row["conditional_survival_probability"])
            lower = float(row["conditional_survival_ci95_lower"])
            upper = float(row["conditional_survival_ci95_upper"])
            if not 0.0 <= lower <= estimate <= upper <= 1.0:
                interval_failures.append(str(index))
        curve_groups = _by_policy(conditional_survival_rows)
        for policy, samples_for_policy in sample_groups.items():
            _, actual_alive, _, _, _ = _sample_population(
                samples_for_policy
            )
            policy_curve = curve_groups.get(policy, [])
            t0_rows = [
                row for row in policy_curve
                if float(row["years_after_start"]) == 0.0
            ]
            if actual_alive:
                if len(t0_rows) != 1:
                    t0_failures.append(
                        f"{policy!r}: expected one t=0 row"
                    )
                elif tuple(float(t0_rows[0][field]) for field in (
                    "conditional_survival_probability",
                    "conditional_survival_ci95_lower",
                    "conditional_survival_ci95_upper",
                )) != (1.0, 1.0, 1.0):
                    t0_failures.append(f"{policy!r}: invalid t=0 values")
            elif policy_curve:
                t0_failures.append(
                    f"{policy!r}: curve exists with zero eligible samples"
                )
        for policy in curve_groups.keys() - sample_groups.keys():
            t0_failures.append(f"{policy!r}: curve has no RUL sample rows")
        checks.append(_check(
            "conditional_wilson_interval_consistency",
            "conditional_survival",
            not interval_failures,
            f"{len(interval_failures)} invalid rows",
            "0 <= Wilson low <= estimate <= Wilson high <= 1",
            "; ".join(interval_failures[:5]) or "all intervals contain estimates",
        ))
        checks.append(_check(
            "conditional_survival_time_zero_definition",
            "conditional_survival",
            not t0_failures,
            f"{len(t0_failures)} invalid rows",
            "eligible t=0 rows are exactly 1.0 / 1.0 / 1.0",
            "; ".join(t0_failures[:5]) or "curve presence and t=0 rows agree",
        ))
    else:
        checks.extend((
            _not_applicable(
                "conditional_wilson_interval_consistency",
                "conditional_survival",
                "no eligible conditional survival rows exist",
            ),
            _not_applicable(
                "conditional_survival_time_zero_definition",
                "conditional_survival",
                "no eligible conditional survival rows exist",
            ),
        ))

    failure_groups = _by_policy(failure_mode_rows)
    risk_groups = _by_policy(survivor_risk_rows)
    failure_failures: list[str] = []
    risk_failures: list[str] = []
    for policy, samples_for_policy in sample_groups.items():
        (
            _,
            actual_alive,
            _,
            expected_survivors,
            expected_failures,
        ) = _sample_population(samples_for_policy)
        failures = failure_groups.get(policy, [])
        failure_count = sum(int(row["failure_count"]) for row in failures)
        failure_fraction_sum = sum(
            float(row["fraction_of_conditional_failures"])
            for row in failures
        )
        failure_rows_valid = all(
            _matches_fraction(
                row.get("fraction_of_alive_at_start_samples"),
                int(row["failure_count"]) / actual_alive,
            )
            and _matches_fraction(
                row.get("fraction_of_conditional_failures"),
                int(row["failure_count"]) / expected_failures,
            )
            for row in failures
        ) if expected_failures and actual_alive else not failures
        if (
            failure_count != expected_failures
            or (expected_failures and not _matches_fraction(
                failure_fraction_sum, 1.0
            ))
            or not failure_rows_valid
        ):
            failure_failures.append(repr(policy))

        risks = risk_groups.get(policy, [])
        survivor_count = sum(int(row["survivor_count"]) for row in risks)
        survivor_fraction_sum = sum(
            float(row["fraction_of_horizon_survivors"])
            for row in risks
        )
        risk_rows_valid = all(
            _matches_fraction(
                row.get("fraction_of_horizon_survivors"),
                int(row["survivor_count"]) / expected_survivors,
            )
            for row in risks
        ) if expected_survivors else not risks
        if (
            survivor_count != expected_survivors
            or (expected_survivors and not _matches_fraction(
                survivor_fraction_sum, 1.0
            ))
            or not risk_rows_valid
        ):
            risk_failures.append(repr(policy))

    for policy in failure_groups.keys() - sample_groups.keys():
        failure_failures.append(f"{policy!r}: no RUL sample rows")
    for policy in risk_groups.keys() - sample_groups.keys():
        risk_failures.append(f"{policy!r}: no RUL sample rows")

    if rul_sample_rows or failure_mode_rows or survivor_risk_rows:
        checks.append(_check(
            "conditional_failure_decomposition",
            "failure_decomposition",
            not failure_failures,
            f"{len(failure_failures)} inconsistent policies",
            "failure counts reconcile and failure fractions sum to one",
            "; ".join(failure_failures) or "failure distributions reconcile",
        ))
        checks.append(_check(
            "censored_survivor_risk_decomposition",
            "survivor_risk_decomposition",
            not risk_failures,
            f"{len(risk_failures)} inconsistent policies",
            "survivor counts reconcile and survivor fractions sum to one",
            "; ".join(risk_failures) or "survivor-risk distributions reconcile",
        ))
    else:
        checks.extend((
            _not_applicable(
                "conditional_failure_decomposition",
                "failure_decomposition",
                "conditional RUL analysis was not generated",
            ),
            _not_applicable(
                "censored_survivor_risk_decomposition",
                "survivor_risk_decomposition",
                "conditional RUL analysis was not generated",
            ),
        ))
    return checks


def summarize_validation_checks(
    checks: Sequence[ValidationCheck],
) -> list[ValidationSummaryRow]:
    counts = Counter((check.category, check.status) for check in checks)
    return [
        ValidationSummaryRow(category, status, count)
        for (category, status), count in sorted(counts.items())
    ]


def raise_for_validation_failures(
    checks: Sequence[ValidationCheck],
) -> None:
    failures = [check for check in checks if check.status == FAIL]
    if failures:
        identifiers = ", ".join(check.check_id for check in failures)
        raise ValueError(
            "Internal research-output validation failed: " + identifiers
        )


def build_public_spec_sanity_rows(
    config: SimulationConfig = DEFAULT_CONFIG,
) -> list[PublicSpecSanityRow]:
    """Describe public-reference relationships without claiming calibration."""
    public_scene_area = (
        config.public_scene_width_reference_km
        * config.public_scene_height_reference_km
    )
    implemented_scene_area = (
        config.target_scene_width_km * config.target_scene_height_km
    )
    public_rate_gb_per_min = (
        config.public_x_band_rate_mbit_per_s / 8.0 * 60.0 / 1000.0
    )
    rate_relative_difference = (
        config.x_band_downlink_rate_gb_per_min / public_rate_gb_per_min - 1.0
    )
    return [
        PublicSpecSanityRow(
            "orbit_altitude_reference",
            "orbit altitude",
            f"{config.public_orbit_altitude_reference_km:g} km",
            f"{config.orbit_altitude_km:g} km circular-orbit proxy",
            "exact_reference_match",
            _status(
                config.orbit_altitude_km
                == config.public_orbit_altitude_reference_km
            ),
            "Reference consistency only; this is not an operational ephemeris.",
        ),
        PublicSpecSanityRow(
            "orbit_inclination_reference",
            "orbit inclination",
            f"{config.public_orbit_inclination_reference_deg:g} deg",
            f"{config.orbit_inclination_deg:g} deg analytical reference",
            "exact_reference_match",
            _status(
                config.orbit_inclination_deg
                == config.public_orbit_inclination_reference_deg
            ),
            "Reference consistency only; this is not orbit determination.",
        ),
        PublicSpecSanityRow(
            "scene_area_reference",
            "scene area",
            (
                f"{config.public_scene_width_reference_km:g} km x "
                f"{config.public_scene_height_reference_km:g} km = "
                f"{public_scene_area:g} km^2"
            ),
            f"{implemented_scene_area:g} km^2 synthetic scene proxy",
            "exact_reference_match",
            _status(implemented_scene_area == public_scene_area),
            "The area labels synthetic opportunities; it is not observation geometry.",
        ),
        PublicSpecSanityRow(
            "x_band_rate_rounded_proxy",
            "X-band payload rate",
            (
                f"{config.public_x_band_rate_mbit_per_s:g} Mbit/s = "
                f"{public_rate_gb_per_min:g} GB/min"
            ),
            (
                f"{config.x_band_downlink_rate_gb_per_min:g} GB/min; "
                f"relative difference {rate_relative_difference:.6%}"
            ),
            "rounded_proxy_approximation",
            _status(abs(rate_relative_difference) <= 0.02),
            "Intentional rounded payload proxy; not RF or link-budget calibration.",
        ),
        PublicSpecSanityRow(
            "power_reference_only",
            "power",
            f"{config.public_power_reference_w:g} W",
            (
                f"{config.solar_generation_proxy_w:g} W generation proxy "
                "with separate mode-load assumptions"
            ),
            "not_directly_comparable",
            NOT_APPLICABLE,
            "The public value is sanity metadata and does not calibrate EPS proxies.",
        ),
        PublicSpecSanityRow(
            "spatial_resolution_reference_only",
            "spatial resolution",
            f"{config.public_spatial_resolution_reference_m:g} m",
            "not used in payload volume or pointing-quality calculations",
            "reference_only",
            NOT_APPLICABLE,
            "Metadata only; no numerical proxy comparison is appropriate.",
        ),
        PublicSpecSanityRow(
            "imagery_modes_reference",
            "imagery modes",
            ", ".join(config.public_imagery_mode_references),
            "deterministic synthetic scene labels use the same two names",
            "exact_reference_match",
            PASS,
            "Label consistency only; this is not an instrument-mode model.",
        ),
        PublicSpecSanityRow(
            "revisit_reference_only",
            "revisit",
            (
                f"{config.public_revisit_min_days:g} to "
                f"{config.public_revisit_max_days:g} days"
            ),
            "not used to set the synthetic opportunity period",
            "reference_only",
            NOT_APPLICABLE,
            "Metadata only; no coverage or revisit prediction is made.",
        ),
        PublicSpecSanityRow(
            "productivity_reference_only",
            "productivity",
            f"{config.public_productivity_reference_km2_per_day:g} km^2/day",
            "not used to force simulated daily imaged area",
            "reference_only",
            NOT_APPLICABLE,
            "Metadata only; no productivity calibration is performed.",
        ),
    ]


def build_layer_sensitivity_rows(
    rows: Sequence[Mapping[str, object]],
    comparisons: Sequence[tuple[str, str]],
    *,
    suite_profile: str = "final_v40",
) -> list[dict[str, object]]:
    """Build paired layer deltas from already-generated ablation rows."""
    deltas = compute_ablation_deltas(
        rows,
        comparisons,
        label_field="configuration_label",
        metrics=LAYER_SENSITIVITY_METRICS,
    )
    output: list[dict[str, object]] = []
    for row in deltas:
        result: dict[str, object] = {
            "suite_profile": suite_profile,
            "reference_configuration": row["baseline"],
            "comparison_configuration": row["comparison"],
            "policy": row["policy"],
            "scenario": row["scenario"],
        }
        for metric in LAYER_SENSITIVITY_METRICS:
            for suffix in ("baseline", "comparison", "delta"):
                field = f"{metric}_{suffix}"
                result[field] = row.get(field)
        output.append(result)
    return output


__all__ = [
    "FAIL",
    "LAYER_SENSITIVITY_FIELDS",
    "LAYER_SENSITIVITY_METRICS",
    "NOT_APPLICABLE",
    "PASS",
    "PUBLIC_SPEC_SANITY_FIELDS",
    "VALIDATION_CHECK_FIELDS",
    "VALIDATION_SUMMARY_FIELDS",
    "PublicSpecSanityRow",
    "ValidationCheck",
    "ValidationSummaryRow",
    "build_internal_validation_checks",
    "build_layer_sensitivity_rows",
    "build_public_spec_sanity_rows",
    "raise_for_validation_failures",
    "summarize_validation_checks",
]
