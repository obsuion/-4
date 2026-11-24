"""Run bounded final-V4 or legacy-V3 experiment suites.

The suite packages results from the existing operational proxy.  It does not
add spacecraft physics and its outputs are not operational forecasts.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, fields
from math import isfinite
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from decision_report import run_decision_report
from ops_sim.analysis import (
    PAPER_SCORE_WEIGHTS,
    compute_ablation_deltas,
    rank_policies,
    render_markdown_table,
    summarize_sensitivity,
)
from ops_sim.config import DEFAULT_CONFIG, SimulationConfig
from ops_sim.contacts import (
    ContactModel,
    GeometryContactModel,
    SyntheticContactModel,
    default_astana_ground_station,
)
from ops_sim.event_catalog import EventCatalog, generate_stochastic_event_catalog
from ops_sim.policies import POLICIES, make_policy
from ops_sim.reliability import (
    DEFAULT_BOOTSTRAP_REPLICATES,
    DEFAULT_BOOTSTRAP_SEED,
    CensoredSurvivorRiskDistributionRow,
    ConditionalRULSummary,
    ConditionalSurvivalCurvePoint,
    FailureModeDistributionRow,
    build_censored_survivor_risk_distribution,
    build_conditional_survival_curve,
    build_failure_mode_distribution,
    summarize_conditional_rul,
)
from ops_sim.rul import estimate_remaining_useful_life
from ops_sim.research_design import (
    FINAL_V40_ABLATION_COMPARISONS,
    FINAL_V40_ABLATION_CONFIGURATIONS,
    FINAL_V40_CONFIGURATION,
    FINAL_V40_PROFILE,
    LEGACY_V30_ABLATION_COMPARISONS,
    LEGACY_V30_ABLATION_CONFIGURATIONS,
    LEGACY_V30_CORE_CONFIGURATION,
    LEGACY_V30_GEOMETRY_ABLATION_COMPARISON,
    LEGACY_V30_GEOMETRY_ABLATION_CONFIGURATION,
    MODEL_SELECTOR_FIELDS,
    SUITE_PROFILES,
    ExperimentConfiguration,
    ExperimentDesign,
)
from ops_sim.research_validation import (
    LAYER_SENSITIVITY_FIELDS,
    PUBLIC_SPEC_SANITY_FIELDS,
    VALIDATION_CHECK_FIELDS,
    VALIDATION_SUMMARY_FIELDS,
    build_internal_validation_checks,
    build_layer_sensitivity_rows,
    build_public_spec_sanity_rows,
    raise_for_validation_failures,
    summarize_validation_checks,
)
from ops_sim.scenarios import make_scenario
from ops_sim.simulator import Simulator
from run import _summary_row


STOCHASTIC_SCENARIO = "stochastic_post_life_events"
DEFAULT_RESULTS_DIR = Path("results/paper_suite")

DEFAULT_YEARS = 15.0
DEFAULT_SEED = 42
DEFAULT_RUL_SAMPLES = 20
DEFAULT_RUL_START_YEAR = 8.0
DEFAULT_RUL_HORIZON_YEARS = 5.0

QUICK_YEARS = 0.02
QUICK_RUL_SAMPLES = 1
QUICK_RUL_START_YEAR = 0.02
QUICK_RUL_HORIZON_YEARS = 0.02

CORE_SCENARIOS = (
    "nominal",
    "contact_outage",
    "extreme_compound_post_life_stress",
    STOCHASTIC_SCENARIO,
)
QUICK_POLICIES = ("adaptive", "survival_first")
ABLATION_POLICIES = ("adaptive", "survival_first", "data_maximizer")

# Backward-compatible module aliases for callers that imported the historical
# paper-suite definitions directly.
CORE_CONFIGURATION = LEGACY_V30_CORE_CONFIGURATION
BASE_ABLATION_CONFIGURATIONS = LEGACY_V30_ABLATION_CONFIGURATIONS
GEOMETRY_ABLATION_CONFIGURATION = (
    LEGACY_V30_GEOMETRY_ABLATION_CONFIGURATION
)
BASE_ABLATION_COMPARISONS = LEGACY_V30_ABLATION_COMPARISONS
GEOMETRY_ABLATION_COMPARISON = LEGACY_V30_GEOMETRY_ABLATION_COMPARISON

UNCONDITIONAL_RAW_RUL_FILES = (
    "rul_samples.csv",
    "rul_summary.csv",
    "rul_survival_curve.csv",
)
CONDITIONAL_RAW_RUL_FILES = (
    "rul_conditional_summary.csv",
    "rul_conditional_survival_curve.csv",
    "rul_failure_modes.csv",
    "rul_censored_survivor_risk_drivers.csv",
)
RAW_RUL_FILES = UNCONDITIONAL_RAW_RUL_FILES + CONDITIONAL_RAW_RUL_FILES
TABLE_RUL_FILES = (
    "rul_summary.csv",
    "rul_summary.md",
    "rul_conditional_summary.csv",
    "rul_conditional_summary.md",
)
FINAL_V40_RAW_FILES = (*CONDITIONAL_RAW_RUL_FILES, "internal_validation_checks.csv")
FINAL_V40_TABLE_FILES = (
    "rul_conditional_summary.csv",
    "rul_conditional_summary.md",
    "layer_sensitivity_summary.csv",
    "layer_sensitivity_summary.md",
    "internal_validation_summary.csv",
    "internal_validation_summary.md",
    "public_spec_sanity.csv",
    "public_spec_sanity.md",
)
RUL_ANALYSIS_PROVENANCE_FIELDS = (
    "suite_profile",
    "experiment_group",
    "rul_configuration",
    "rul_stack_status",
)
CONDITIONAL_SUMMARY_FIELDS = RUL_ANALYSIS_PROVENANCE_FIELDS + tuple(
    field.name for field in fields(ConditionalRULSummary)
)
CONDITIONAL_SURVIVAL_FIELDS = RUL_ANALYSIS_PROVENANCE_FIELDS + tuple(
    field.name for field in fields(ConditionalSurvivalCurvePoint)
)
FAILURE_MODE_FIELDS = RUL_ANALYSIS_PROVENANCE_FIELDS + tuple(
    field.name for field in fields(FailureModeDistributionRow)
)
SURVIVOR_RISK_FIELDS = RUL_ANALYSIS_PROVENANCE_FIELDS + tuple(
    field.name for field in fields(CensoredSurvivorRiskDistributionRow)
)
PLOT_FILES = (
    "policy_score_comparison.png",
    "survival_fraction_by_policy.png",
    "data_downlinked_by_policy.png",
    "final_health_by_policy.png",
    "fuel_remaining_by_policy.png",
    "rul_by_policy.png",
    "survival_curve_rul.png",
)
RUL_PLOT_FILES = ("rul_by_policy.png", "survival_curve_rul.png")
DECISION_FILES = (
    "decision_trace.csv",
    "risk_trace.csv",
    "option_assessments.csv",
    "failure_attribution.csv",
    "decision_summary.md",
)


@dataclass(frozen=True)
class RULMatrixResults:
    """Combined unconditional and conditional per-policy RUL products."""

    samples: list[dict[str, object]]
    summaries: list[dict[str, object]]
    survival_curve: list[dict[str, object]]
    conditional_summaries: list[dict[str, object]]
    conditional_survival_curve: list[dict[str, object]]
    failure_modes: list[dict[str, object]]
    censored_survivor_risks: list[dict[str, object]]


class _ExplicitValueAction(argparse.Action):
    """Store an option and remember that quick mode must not override it."""

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        supplied = set(getattr(namespace, "_explicit_value_options", ()))
        supplied.add(self.dest)
        setattr(namespace, "_explicit_value_options", supplied)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a bounded final-V4 or legacy-V3 research suite and generate "
            "paper-ready tables, figures, and Markdown"
        )
    )
    parser.add_argument(
        "--suite-profile",
        choices=SUITE_PROFILES,
        default=FINAL_V40_PROFILE,
    )
    parser.add_argument(
        "--years",
        type=float,
        default=DEFAULT_YEARS,
        action=_ExplicitValueAction,
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--rul-samples",
        type=int,
        default=DEFAULT_RUL_SAMPLES,
        action=_ExplicitValueAction,
    )
    parser.add_argument(
        "--rul-start-year",
        type=float,
        default=DEFAULT_RUL_START_YEAR,
        action=_ExplicitValueAction,
    )
    parser.add_argument(
        "--rul-horizon-years",
        type=float,
        default=DEFAULT_RUL_HORIZON_YEARS,
        action=_ExplicitValueAction,
    )
    parser.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=DEFAULT_BOOTSTRAP_REPLICATES,
    )
    parser.add_argument(
        "--bootstrap-seed",
        type=int,
        default=DEFAULT_BOOTSTRAP_SEED,
    )
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--include-geometry", action="store_true")
    parser.add_argument("--skip-rul", action="store_true")
    parser.add_argument("--skip-plots", action="store_true")
    parser.add_argument("--include-decision-report", action="store_true")
    parser.add_argument("--quick", action="store_true")
    return parser


def build_experiment_design(args: argparse.Namespace) -> ExperimentDesign:
    """Resolve quick-mode overrides without replacing explicit CLI values."""
    supplied = set(getattr(args, "_explicit_value_options", ()))

    def effective(name: str, quick_value):
        value = getattr(args, name)
        if args.quick and name not in supplied:
            return quick_value
        return value

    years = effective("years", QUICK_YEARS)
    rul_samples = effective("rul_samples", QUICK_RUL_SAMPLES)
    rul_start_year = effective("rul_start_year", QUICK_RUL_START_YEAR)
    rul_horizon_years = effective(
        "rul_horizon_years", QUICK_RUL_HORIZON_YEARS
    )
    if not isfinite(years) or years < 0:
        raise ValueError("--years must be a finite non-negative number")
    if isinstance(rul_samples, bool) or rul_samples <= 0:
        raise ValueError("--rul-samples must be a positive integer")
    if not isfinite(rul_start_year) or rul_start_year < 0:
        raise ValueError(
            "--rul-start-year must be a finite non-negative number"
        )
    if not isfinite(rul_horizon_years) or rul_horizon_years < 0:
        raise ValueError(
            "--rul-horizon-years must be a finite non-negative number"
        )
    if (
        isinstance(args.bootstrap_replicates, bool)
        or not isinstance(args.bootstrap_replicates, int)
        or args.bootstrap_replicates <= 0
    ):
        raise ValueError("--bootstrap-replicates must be a positive integer")
    if isinstance(args.bootstrap_seed, bool) or not isinstance(
        args.bootstrap_seed, int
    ):
        raise ValueError("--bootstrap-seed must be an integer")
    if args.suite_profile == FINAL_V40_PROFILE and args.include_geometry:
        raise ValueError(
            "--include-geometry is unnecessary for --suite-profile "
            "final_v40 because geometry is already the primary contact model"
        )

    all_policies = tuple(POLICIES)
    selected_policies = QUICK_POLICIES if args.quick else all_policies
    ablation_policies = ("adaptive",) if args.quick else ABLATION_POLICIES
    if args.suite_profile == FINAL_V40_PROFILE:
        core_configuration = FINAL_V40_CONFIGURATION
        rul_configuration = FINAL_V40_CONFIGURATION
        rul_is_final_stack = True
        configurations = list(FINAL_V40_ABLATION_CONFIGURATIONS)
        comparisons = FINAL_V40_ABLATION_COMPARISONS
    else:
        core_configuration = LEGACY_V30_CORE_CONFIGURATION
        rul_configuration = LEGACY_V30_CORE_CONFIGURATION
        rul_is_final_stack = False
        configurations = list(LEGACY_V30_ABLATION_CONFIGURATIONS)
        comparisons = list(LEGACY_V30_ABLATION_COMPARISONS)
        if args.include_geometry:
            configurations.append(
                LEGACY_V30_GEOMETRY_ABLATION_CONFIGURATION
            )
            comparisons.append(LEGACY_V30_GEOMETRY_ABLATION_COMPARISON)

    return ExperimentDesign(
        suite_profile=args.suite_profile,
        years=years,
        seed=args.seed,
        core_policies=selected_policies,
        core_scenarios=("nominal",) if args.quick else CORE_SCENARIOS,
        core_configuration=core_configuration,
        ablation_policies=ablation_policies,
        ablation_scenario=STOCHASTIC_SCENARIO,
        ablation_configurations=tuple(configurations),
        ablation_comparisons=tuple(comparisons),
        run_rul=not args.skip_rul,
        rul_policies=selected_policies,
        rul_samples=rul_samples,
        rul_start_year=rul_start_year,
        rul_horizon_years=rul_horizon_years,
        rul_configuration=rul_configuration,
        bootstrap_replicates=args.bootstrap_replicates,
        bootstrap_seed=args.bootstrap_seed,
        rul_is_final_stack=rul_is_final_stack,
        include_decision_report=getattr(
            args, "include_decision_report", False
        ),
    )


def _contact_model(
    name: str, config: SimulationConfig = DEFAULT_CONFIG
) -> ContactModel:
    if name == "synthetic":
        return SyntheticContactModel(config)
    if name == "geometry":
        return GeometryContactModel(default_astana_ground_station(config), config)
    raise ValueError(f"Unknown contact model {name!r}")


def run_simulator_case(
    *,
    suite_profile: str,
    policy_name: str,
    scenario_name: str,
    years: float,
    seed: int,
    configuration: ExperimentConfiguration,
    event_catalog: EventCatalog | None,
    experiment_group: str,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> dict[str, object]:
    """Run one fresh simulator/contact/scenario instance and return its summary."""
    total_hours = int(round(years * config.hours_per_year))
    scenario = make_scenario(
        scenario_name,
        config,
        seed=seed if event_catalog is not None else None,
        total_hours=total_hours,
        event_catalog=event_catalog,
    )
    simulator = Simulator(
        make_policy(policy_name, config),
        scenario,
        config,
        contact_model=_contact_model(configuration.contact_model, config),
        **configuration.simulator_kwargs(seed=seed),
    )
    result = simulator.run(years)
    summary = _summary_row(result, years)
    provenance = configuration.selector_provenance()
    for field in MODEL_SELECTOR_FIELDS:
        if field == "contact_model":
            continue
        if field not in summary:
            raise ValueError(
                f"Simulation summary omitted configuration field {field!r}"
            )
        if summary[field] != provenance[field]:
            raise ValueError(
                f"Configuration/result provenance mismatch for {field}: "
                f"{provenance[field]!r} != {summary[field]!r}"
            )
    if summary.get("packet_delivery_seed") != seed:
        raise ValueError(
            "Configuration/result provenance mismatch for "
            "packet_delivery_seed"
        )
    return {
        "suite_profile": suite_profile,
        "experiment_group": experiment_group,
        "configuration": configuration.label,
        "configuration_label": configuration.label,
        "sensitivity_label": configuration.label,
        "seed": seed,
        **provenance,
        **summary,
    }


def _shared_stochastic_catalog(
    design: ExperimentDesign,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> EventCatalog:
    total_hours = int(round(design.years * config.hours_per_year))
    return generate_stochastic_event_catalog(
        design.seed,
        STOCHASTIC_SCENARIO,
        total_hours,
        config,
    )


def run_core_matrix(
    design: ExperimentDesign,
    stochastic_catalog: EventCatalog,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for policy_name in design.core_policies:
        for scenario_name in design.core_scenarios:
            row = run_simulator_case(
                suite_profile=design.suite_profile,
                policy_name=policy_name,
                scenario_name=scenario_name,
                years=design.years,
                seed=design.seed,
                configuration=design.core_configuration,
                event_catalog=(
                    stochastic_catalog
                    if scenario_name == STOCHASTIC_SCENARIO
                    else None
                ),
                experiment_group="core",
                config=config,
            )
            row["sensitivity_label"] = scenario_name
            rows.append(row)
    return rows


def run_ablation_matrix(
    design: ExperimentDesign,
    stochastic_catalog: EventCatalog,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for configuration in design.ablation_configurations:
        policy_names = (
            configuration.applicable_policies
            if configuration.applicable_policies is not None
            else design.ablation_policies
        )
        for policy_name in policy_names:
            rows.append(
                run_simulator_case(
                    suite_profile=design.suite_profile,
                    policy_name=policy_name,
                    scenario_name=design.ablation_scenario,
                    years=design.years,
                    seed=design.seed,
                    configuration=configuration,
                    event_catalog=stochastic_catalog,
                    experiment_group="ablation",
                    config=config,
                )
            )
    return rows


def run_rul_matrix(
    design: ExperimentDesign,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> RULMatrixResults:
    """Run bounded RUL estimates with catalogs cached across policies by seed."""
    sample_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    curve_rows: list[dict[str, object]] = []
    conditional_summary_rows: list[dict[str, object]] = []
    conditional_curve_rows: list[dict[str, object]] = []
    failure_mode_rows: list[dict[str, object]] = []
    survivor_risk_rows: list[dict[str, object]] = []
    catalog_cache: dict[tuple[int | None, str, int], EventCatalog] = {}

    def shared_catalog_factory(
        seed: int | None,
        scenario_name: str,
        total_hours: int,
        requested_config: SimulationConfig,
    ) -> EventCatalog:
        key = (seed, scenario_name, total_hours)
        if key not in catalog_cache:
            catalog_cache[key] = generate_stochastic_event_catalog(
                seed, scenario_name, total_hours, requested_config
            )
        return catalog_cache[key]

    for policy_name in design.rul_policies:
        samples, summary, curve = estimate_remaining_useful_life(
            policy_name=policy_name,
            scenario_name=STOCHASTIC_SCENARIO,
            start_year=design.rul_start_year,
            horizon_years=design.rul_horizon_years,
            samples=design.rul_samples,
            seed=design.seed,
            config=config,
            event_catalog_factory=shared_catalog_factory,
            **design.rul_configuration.rul_kwargs(),
        )
        rul_provenance = {
            "suite_profile": design.suite_profile,
            "experiment_group": "rul",
            "rul_configuration": design.rul_configuration.label,
            "rul_stack_status": (
                "final_stack_v40b"
                if design.rul_is_final_stack
                else "legacy_compatibility"
            ),
        }
        sample_rows.extend(
            {**rul_provenance, **sample.as_dict()}
            for sample in samples
        )
        summary_rows.append(
            {**rul_provenance, **summary.as_dict()}
        )
        curve_rows.extend(
            {**rul_provenance, **point.as_dict()}
            for point in curve
        )
        if design.is_final_v40:
            analysis_options = {
                "bootstrap_replicates": design.bootstrap_replicates,
                "bootstrap_seed": design.bootstrap_seed,
            }
            conditional_summary_rows.append({
                **rul_provenance,
                **summarize_conditional_rul(
                    samples, **analysis_options
                ).as_dict(),
            })
            conditional_curve_rows.extend(
                {
                    **rul_provenance,
                    **point.as_dict(),
                }
                for point in build_conditional_survival_curve(
                    samples, **analysis_options
                )
            )
            failure_mode_rows.extend(
                {
                    **rul_provenance,
                    **row.as_dict(),
                }
                for row in build_failure_mode_distribution(
                    samples, **analysis_options
                )
            )
            survivor_risk_rows.extend(
                {
                    **rul_provenance,
                    **row.as_dict(),
                }
                for row in build_censored_survivor_risk_distribution(
                    samples, **analysis_options
                )
            )
    return RULMatrixResults(
        samples=sample_rows,
        summaries=summary_rows,
        survival_curve=curve_rows,
        conditional_summaries=conditional_summary_rows,
        conditional_survival_curve=conditional_curve_rows,
        failure_modes=failure_mode_rows,
        censored_survivor_risks=survivor_risk_rows,
    )


def _all_fieldnames(rows: Sequence[Mapping[str, object]]) -> list[str]:
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                seen.add(field)
                fieldnames.append(field)
    return fieldnames


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fieldnames: Sequence[str] | None = None,
) -> None:
    fields = list(fieldnames or _all_fieldnames(rows))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown_table(
    path: Path,
    title: str,
    rows: Sequence[Mapping[str, object]],
    preferred_columns: Sequence[str] = (),
) -> None:
    available = set().union(*(row.keys() for row in rows)) if rows else set()
    columns = [field for field in preferred_columns if field in available]
    if not columns:
        columns = _all_fieldnames(rows)
    rendered = render_markdown_table(rows, columns=columns or None)
    path.write_text(f"# {title}\n\n{rendered}\n", encoding="utf-8")


def _write_markdown_table_with_note(
    path: Path,
    title: str,
    note: str,
    rows: Sequence[Mapping[str, object]],
    columns: Sequence[str],
) -> None:
    rendered = render_markdown_table(rows, columns=columns)
    path.write_text(
        f"# {title}\n\n{note}\n\n{rendered}\n",
        encoding="utf-8",
    )


def _ablation_comparisons(design: ExperimentDesign):
    return design.ablation_comparisons


def build_tables(
    *,
    design: ExperimentDesign,
    core_rows: Sequence[Mapping[str, object]],
    ablation_rows: Sequence[Mapping[str, object]],
    rul_summary_rows: Sequence[Mapping[str, object]],
    tables_dir: Path,
    conditional_rul_summary_rows: Sequence[Mapping[str, object]] = (),
    public_spec_rows: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, list[dict[str, object]]]:
    ranking_rul_rows = (
        rul_summary_rows
        if not design.is_final_v40 or design.rul_is_final_stack
        else ()
    )
    rankings = rank_policies(core_rows, ranking_rul_rows)
    scenario_rows = summarize_sensitivity(
        core_rows,
        label_field="scenario",
    )
    ablation_summary = list(
        compute_ablation_deltas(
            ablation_rows,
            _ablation_comparisons(design),
            label_field="configuration_label",
        )
    )
    if design.is_final_v40:
        ablation_summary = [
            {
                "reference_configuration": row["baseline"],
                "comparison_configuration": row["comparison"],
                **row,
            }
            for row in ablation_summary
        ]
    sensitivity_rows = summarize_sensitivity(
        ablation_rows,
        label_field="sensitivity_label",
    )
    layer_sensitivity_rows = (
        build_layer_sensitivity_rows(
            ablation_rows,
            design.ablation_comparisons,
            suite_profile=design.suite_profile,
        )
        if design.is_final_v40
        else []
    )
    resolved_public_spec_rows = (
        list(public_spec_rows)
        if public_spec_rows is not None
        else [
            row.as_dict() for row in build_public_spec_sanity_rows()
        ]
        if design.is_final_v40
        else []
    )

    output_rows = {
        "policy_ranking": list(rankings),
        "scenario_summary": list(scenario_rows),
        "ablation_summary": list(ablation_summary),
        "sensitivity_summary": list(sensitivity_rows),
    }
    preferred = {
        "policy_ranking": (
            "rank",
            "policy",
            "paper_score",
            "simulator_score",
            "simulator_score_rank",
            "survival_fraction",
            "survival_fraction_rank",
            "data_downlinked_gb",
            "data_downlinked_gb_rank",
            "final_health",
            "final_health_rank",
            "fuel_remaining_percent",
            "fuel_remaining_percent_rank",
            "expected_rul_years_censored",
            "expected_rul_years_censored_rank",
            "median_rul_years_censored",
            "median_rul_years_censored_rank",
        ),
        "scenario_summary": (
            "scenario",
            "rows",
            "simulator_score_mean",
            "survival_fraction_mean",
            "data_downlinked_gb_mean",
            "final_health_mean",
            "fuel_remaining_percent_mean",
        ),
        "ablation_summary": (
            "reference_configuration",
            "comparison_configuration",
            "comparison",
            "policy",
            "scenario",
            "baseline",
            "simulator_score_delta",
            "survival_fraction_delta",
            "data_downlinked_gb_delta",
            "final_health_delta",
            "fuel_remaining_percent_delta",
        ),
        "sensitivity_summary": (
            "sensitivity_label",
            "rows",
            "simulator_score_mean",
            "simulator_score_min",
            "simulator_score_max",
            "data_downlinked_gb_mean",
            "final_health_mean",
        ),
    }
    titles = {
        "policy_ranking": "Policy ranking",
        "scenario_summary": "Scenario summary",
        "ablation_summary": (
            "Final-stack layer ablation summary"
            if design.is_final_v40
            else "Legacy V3.0 ablation summary"
        ),
        "sensitivity_summary": "Sensitivity summary",
    }
    for name, rows in output_rows.items():
        _write_csv(tables_dir / f"{name}.csv", rows)
        _write_markdown_table(
            tables_dir / f"{name}.md",
            titles[name],
            rows,
            preferred[name],
        )

    if design.run_rul:
        ordered_rul = sorted(
            (dict(row) for row in rul_summary_rows),
            key=lambda row: _number(
                row, "expected_rul_years_censored", default=-1.0
            ),
            reverse=True,
        )
        _write_csv(tables_dir / "rul_summary.csv", ordered_rul)
        _write_markdown_table(
            tables_dir / "rul_summary.md",
            "Remaining useful life summary",
            ordered_rul,
            (
                "policy",
                "samples",
                "alive_at_start_fraction",
                "survived_to_horizon_fraction",
                "expected_rul_years_censored",
                "median_rul_years_censored",
                "p05_rul_years_censored",
                "p95_rul_years_censored",
                "mean_final_health",
                "mean_final_fuel_remaining_percent",
            ),
        )
        if design.is_final_v40:
            conditional_rows = [
                dict(row) for row in conditional_rul_summary_rows
            ]
            _write_csv(
                tables_dir / "rul_conditional_summary.csv",
                conditional_rows,
                CONDITIONAL_SUMMARY_FIELDS,
            )
            _write_markdown_table_with_note(
                tables_dir / "rul_conditional_summary.md",
                "Conditional remaining useful life summary",
                (
                    "These results condition on simulated samples alive at "
                    "the RUL start and remain bounded by the common requested "
                    "horizon. They do not replace unconditional RUL."
                ),
                conditional_rows,
                (
                    "policy",
                    "total_samples",
                    "alive_at_start_samples",
                    "warmup_failed_samples",
                    "alive_at_start_fraction",
                    "conditional_expected_rul_years_censored",
                    "conditional_expected_rul_years_censored_ci95_lower",
                    "conditional_expected_rul_years_censored_ci95_upper",
                    "conditional_median_rul_years_censored",
                    "conditional_p05_rul_years_censored",
                    "conditional_p95_rul_years_censored",
                    "conditional_survived_to_horizon_fraction",
                    "conditional_probability_survive_plus_1y",
                    "conditional_probability_survive_plus_2y",
                    "conditional_probability_survive_plus_3y",
                ),
            )
    if design.is_final_v40:
        _write_csv(
            tables_dir / "layer_sensitivity_summary.csv",
            layer_sensitivity_rows,
            LAYER_SENSITIVITY_FIELDS,
        )
        _write_markdown_table_with_note(
            tables_dir / "layer_sensitivity_summary.md",
            "Final-stack layer sensitivity summary",
            (
                "Comparisons are within this proxy model and paired runs "
                "share the experiment seed/catalog where applicable. Some "
                "ablations alter coupled layers; deltas are not physical "
                "causal-effect estimates. `synthetic_contact_control` is a "
                "model comparison, and `limited_maneuver_autonomy` is a "
                "sensitivity case rather than primary autonomy."
            ),
            layer_sensitivity_rows,
            LAYER_SENSITIVITY_FIELDS,
        )
        _write_csv(
            tables_dir / "public_spec_sanity.csv",
            resolved_public_spec_rows,
            PUBLIC_SPEC_SANITY_FIELDS,
        )
        _write_markdown_table_with_note(
            tables_dir / "public_spec_sanity.md",
            "Public-spec sanity and reference checks",
            (
                "Public-spec sanity checks are consistency/reference checks, "
                "not calibration or validation against operational data."
            ),
            resolved_public_spec_rows,
            PUBLIC_SPEC_SANITY_FIELDS,
        )
        output_rows["layer_sensitivity_summary"] = list(
            layer_sensitivity_rows
        )
        output_rows["public_spec_sanity"] = list(
            resolved_public_spec_rows
        )
    return output_rows


def _number(
    row: Mapping[str, object],
    *names: str,
    default: float | None = None,
) -> float | None:
    for name in names:
        value = row.get(name)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _load_pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit(
            "matplotlib is required to generate paper-suite figures; "
            "install matplotlib or rerun with --skip-plots"
        ) from exc
    return plt


def _bar_plot(
    plt,
    rows: Sequence[Mapping[str, object]],
    metric_names: Sequence[str],
    ylabel: str,
    title: str,
    path: Path,
) -> None:
    policies = [str(row.get("policy", "")) for row in rows]
    values = [
        _number(row, *metric_names, default=0.0) or 0.0 for row in rows
    ]
    figure, axis = plt.subplots(figsize=(max(6.0, len(rows) * 0.65), 4.2))
    try:
        axis.bar(policies, values)
        axis.set_ylabel(ylabel)
        axis.set_title(title)
        axis.tick_params(axis="x", labelrotation=45)
        figure.tight_layout()
        figure.savefig(path, dpi=150)
    finally:
        plt.close(figure)


def generate_plots(
    *,
    ranking_rows: Sequence[Mapping[str, object]],
    rul_summary_rows: Sequence[Mapping[str, object]],
    survival_curve_rows: Sequence[Mapping[str, object]],
    figures_dir: Path,
    plt=None,
) -> None:
    plt = plt or _load_pyplot()
    specifications = (
        (
            ("simulator_score", "mean_score", "score"),
            "Mean simulator score",
            "Simulator score by policy",
            "policy_score_comparison.png",
        ),
        (
            ("survival_fraction", "alive_fraction", "survived_fraction"),
            "Survival fraction",
            "Survival fraction by policy",
            "survival_fraction_by_policy.png",
        ),
        (
            ("data_downlinked_gb", "mean_data_downlinked_gb"),
            "Mean data downlinked (GB)",
            "Data downlinked by policy",
            "data_downlinked_by_policy.png",
        ),
        (
            ("final_health", "mean_final_health"),
            "Mean final health",
            "Final health by policy",
            "final_health_by_policy.png",
        ),
        (
            ("fuel_remaining_percent", "mean_fuel_remaining_percent"),
            "Mean fuel remaining (%)",
            "Fuel remaining by policy",
            "fuel_remaining_by_policy.png",
        ),
    )
    for names, ylabel, title, filename in specifications:
        _bar_plot(
            plt,
            ranking_rows,
            names,
            ylabel,
            title,
            figures_dir / filename,
        )

    if rul_summary_rows:
        ordered_rul = sorted(
            rul_summary_rows,
            key=lambda row: str(row.get("policy", "")),
        )
        _bar_plot(
            plt,
            ordered_rul,
            ("expected_rul_years_censored",),
            "Expected censored RUL (years)",
            "Remaining useful life by policy",
            figures_dir / "rul_by_policy.png",
        )

        figure, axis = plt.subplots(figsize=(7.0, 4.2))
        try:
            policies = sorted({str(row["policy"]) for row in survival_curve_rows})
            for policy in policies:
                points = sorted(
                    (
                        row
                        for row in survival_curve_rows
                        if str(row.get("policy")) == policy
                    ),
                    key=lambda row: _number(
                        row, "years_after_start", default=0.0
                    ),
                )
                axis.plot(
                    [
                        _number(point, "years_after_start", default=0.0)
                        for point in points
                    ],
                    [
                        _number(point, "survival_probability", default=0.0)
                        for point in points
                    ],
                    marker="o",
                    label=policy,
                )
            axis.set_xlabel("Years after RUL start")
            axis.set_ylabel("Survival probability")
            axis.set_ylim(0.0, 1.05)
            axis.set_title("Empirical RUL survival curves")
            if policies:
                axis.legend(fontsize="small")
            figure.tight_layout()
            figure.savefig(figures_dir / "survival_curve_rul.png", dpi=150)
        finally:
            plt.close(figure)


def _best_row(
    rows: Sequence[Mapping[str, object]], *metric_names: str
) -> Mapping[str, object] | None:
    candidates = [
        (value, row)
        for row in rows
        if (value := _number(row, *metric_names)) is not None
    ]
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _policy_label(row: Mapping[str, object] | None) -> str:
    return str(row.get("policy", "unavailable")) if row else "unavailable"


def _format_weights() -> str:
    labels = {
        "simulator_score": "normalized simulator score",
        "survival_fraction": "survival/alive fraction",
        "data_downlinked_gb": "normalized data downlinked",
        "final_health": "normalized final health",
        "expected_rul_years_censored": "normalized expected RUL",
        "fuel_remaining_percent": "normalized fuel remaining",
    }
    return "\n".join(
        f"- {labels.get(name, name.replace('_', ' '))}: `{weight:.3f}`"
        for name, weight in PAPER_SCORE_WEIGHTS.items()
    )


def write_paper_markdown(
    *,
    design: ExperimentDesign,
    ranking_rows: Sequence[Mapping[str, object]],
    ablation_summary_rows: Sequence[Mapping[str, object]],
    rul_summary_rows: Sequence[Mapping[str, object]],
    paper_dir: Path,
    conditional_rul_summary_rows: Sequence[Mapping[str, object]] = (),
    decision_report_included: bool = False,
) -> None:
    scenario_word = "scenario" if len(design.core_scenarios) == 1 else "scenarios"
    configuration_lines = "\n".join(
        f"- `{field}={value}`"
        for field, value in (
            design.core_configuration.selector_provenance().items()
        )
    )
    if design.is_final_v40:
        profile_methods = f"""The selected suite profile is `final_v40`. Its
primary scientific matrix uses geometry contacts and the complete canonical
stack listed below:

{configuration_lines}

This combines drift-proxy orbit evolution, delayed telemetry, risk-aware
planning, stationkeeping-proxy maneuvers with drift-aware planning, warning
lifecycle and severity debris proxies, conservative contingency-plan autonomy,
eclipse and load-stress proxies, target and bounded-pointing proxies, and packet
accounting with the deterministic loss/retry proxy. The packet drop fraction
`{design.core_configuration.packet_drop_fraction_proxy:.2f}` is an explicit synthetic stress assumption,
not measured or calibrated link reliability.

The layer-ablation matrix contains {design.ablation_run_count} runs. Each
comparison is an intentionally bounded layer change against `final_full_stack`;
the synthetic-contact row is a labeled control, not the primary scientific
model. The compact layer-sensitivity product uses these already-generated
paired rows; some comparisons intentionally alter coupled layers, and their
deltas are not physical causal-effect estimates. `synthetic_contact_control` is
a model comparison, while `limited_maneuver_autonomy` remains a sensitivity
case rather than primary autonomy."""
    else:
        profile_methods = f"""The selected suite profile is `legacy_v30`. It
preserves the historical synthetic-contact core and five-selector V3.0
experiment architecture, with later selector layers kept at their neutral
compatibility settings:

{configuration_lines}

The legacy ablation matrix contains {design.ablation_run_count} runs and retains
the bounded A/B/C/D/E synthetic sequence. A geometry comparison is included
only when explicitly requested with `--include-geometry`. This profile is a
regression and control architecture, not the primary V4 scientific suite."""

    if design.run_rul:
        if design.is_final_v40:
            rul_methods = (
                "The `final_v40` RUL matrix uses the same canonical "
                "complete-stack configuration as the primary core. For sample "
                "i, the sample seed is the base seed plus i; matched policies "
                "reuse the corresponding event catalog, and that sample seed "
                "also drives packet delivery. One warmed Simulator remains "
                "authoritative across warm-up and continuation. The established "
                "unconditional population retains zero additional RUL for "
                "warm-up failures. The parallel conditional population includes "
                "only samples alive at the start year. Both remain censored at "
                "the common administrative horizon. Conditional survival uses "
                "95% Wilson intervals, and the conditional censored mean uses "
                f"a {design.bootstrap_replicates}-replicate row-resampling "
                f"bootstrap with analysis seed {design.bootstrap_seed}. These "
                "intervals quantify finite Monte Carlo sample uncertainty only. "
                "Reliability analysis consumes the generated sample rows and "
                "does not rerun the simulator. RUL/reliability analysis is a "
                "common-horizon simulation interpretation, not a real lifetime "
                "model."
            )
        else:
            rul_methods = (
                "The `legacy_v30` profile retains the historical synthetic "
                "V3.0/V3.9 RUL matrix and its established ranking behavior."
            )
        rul_methods += (
            f" It warms each sample to year `{design.rul_start_year:g}` and "
            f"continues it for up to `{design.rul_horizon_years:g}` years, "
            f"with {design.rul_samples} sample(s) per policy. These are "
            "horizon-censored proxy results, not physical reliability "
            "predictions."
        )
    else:
        rul_methods = "RUL generation was disabled for this suite run."

    integration_methods = (
        "Final-profile outputs also receive internal structural consistency "
        "checks, public-spec sanity/reference checks, and bounded layer-"
        "sensitivity summaries. Internal checks validate output invariants "
        "rather than spacecraft truth. Public-spec sanity checks are not "
        "calibration or validation against operational data."
        if design.is_final_v40
        else (
            "The legacy profile does not automatically enable the V3.9B "
            "conditional package or final-profile validation/sensitivity "
            "products."
        )
    )

    methods = f"""# Autogenerated methods

This study uses an open, simplified operational proxy inspired by KazEOSat-1.
It is neither official spacecraft software nor a real physical digital twin.
The simulator advances in hourly steps and represents transparent subsystem
degradation, contact opportunities, delayed ground telemetry, uploaded daily
plans, operator-policy decisions, and coarse maneuver/fuel and orbit-drift
proxies.

The bounded core matrix contains {design.core_run_count} runs at
`{design.years:g}` years each. It compares {len(design.core_policies)} operator
profiles across {len(design.core_scenarios)} selected {scenario_word}.

{profile_methods}

Stochastic simulator comparisons use common random numbers: a catalog generated
for seed `{design.seed}` is reused across the applicable policies and ablation
configurations, and packet delivery uses that same experiment seed without
policy-specific reseeding.

{rul_methods}

{integration_methods}

The transparent weighted paper score uses these components:

{_format_weights()}

Fraction and percentage components use their fixed bounds; the other components
use cross-policy min-max normalization. Weights are renormalized when optional
RUL or fuel inputs are unavailable.
"""
    paper_dir.joinpath("methods_autogenerated.md").write_text(
        methods, encoding="utf-8"
    )

    best_paper = _best_row(ranking_rows, "paper_score")
    best_simulator = _best_row(
        ranking_rows, "simulator_score", "mean_score", "score"
    )
    best_rul = _best_row(rul_summary_rows, "expected_rul_years_censored")
    best_conditional_rul = _best_row(
        conditional_rul_summary_rows,
        "conditional_expected_rul_years_censored",
    )

    tradeoff_lines: list[str] = []
    for row in ablation_summary_rows[:5]:
        baseline = str(row.get("baseline") or "baseline")
        comparison = str(row.get("comparison") or "comparison")
        comparison_label = f"{comparison}_minus_{baseline}"
        delta = _number(row, "simulator_score_delta", "score_delta", "delta_score")
        suffix = f" (score delta {delta:+.4f})" if delta is not None else ""
        policy = row.get("policy")
        policy_text = f" for `{policy}`" if policy else ""
        tradeoff_lines.append(
            f"- `{comparison_label}`{policy_text}{suffix}."
        )
    if not tradeoff_lines:
        tradeoff_lines.append("- No matched ablation comparison was available.")

    if design.run_rul and design.is_final_v40:
        total_samples = sum(
            int(row.get("total_samples", 0) or 0)
            for row in conditional_rul_summary_rows
        )
        alive_samples = sum(
            int(row.get("alive_at_start_samples", 0) or 0)
            for row in conditional_rul_summary_rows
        )
        available_policies = sum(
            int(row.get("alive_at_start_samples", 0) or 0) > 0
            for row in conditional_rul_summary_rows
        )
        rul_result = (
            "- Best unconditional expected censored RUL within the configured "
            f"final-stack proxy: `{_policy_label(best_rul)}`.\n"
            "- Conditional given-alive-at-start RUL is available for "
            f"{available_policies} policy row(s), with {alive_samples} of "
            f"{total_samples} simulated samples alive at the start; the "
            "largest conditional censored mean is associated with "
            f"`{_policy_label(best_conditional_rul)}`."
        )
    elif design.run_rul:
        rul_result = (
            "- Best historical synthetic compatibility expected censored "
            f"RUL: `{_policy_label(best_rul)}`."
        )
    else:
        rul_result = "- RUL analysis was skipped for this suite run."
    tradeoff_heading = (
        "Main layer-ablation tradeoffs"
        if design.is_final_v40
        else "Main legacy ablation tradeoffs"
    )
    results = f"""# Autogenerated results

These are comparisons within the configured proxy model and should not be read
as operational performance claims.

- Best weighted paper score: `{_policy_label(best_paper)}`.
- Best mean simulator score: `{_policy_label(best_simulator)}`.
{rul_result}

## {tradeoff_heading}

{chr(10).join(tradeoff_lines)}

Detailed values are available in
[the policy ranking](../tables/policy_ranking.md),
[the scenario summary](../tables/scenario_summary.md),
[the ablation summary](../tables/ablation_summary.md), and
[the sensitivity summary](../tables/sensitivity_summary.md).
"""
    if design.run_rul:
        results += "\nRUL details are in [the RUL summary](../tables/rul_summary.md).\n"
        if design.is_final_v40:
            results += (
                "Conditional given-alive-at-start details are in "
                "[the conditional RUL summary]"
                "(../tables/rul_conditional_summary.md).\n"
            )
    if design.is_final_v40:
        results += (
            "\nFurther structural outputs are in "
            "[the layer sensitivity summary]"
            "(../tables/layer_sensitivity_summary.md), "
            "[the internal validation summary]"
            "(../tables/internal_validation_summary.md), and "
            "[the public-spec sanity table]"
            "(../tables/public_spec_sanity.md). These are within-model "
            "comparisons and consistency/reference checks, not operational "
            "validation or grand scientific conclusions.\n"
        )
    if decision_report_included:
        results += (
            "\nDecision diagnostics are in "
            "[the decision summary](../decision/decision_summary.md).\n"
        )
    paper_dir.joinpath("results_autogenerated.md").write_text(
        results, encoding="utf-8"
    )

    limitations = """# Autogenerated limitations

The simulator implements bounded lifecycle/debris information-flow and severity
proxies, but no real conjunction screening, collision probability, covariance
propagation, or impact prediction. Its geometry-contact proxy has no TLE/SGP4,
J2, drag, high-precision orbit propagation, or operational station schedule.

Bounded eclipse/power and load-stress/thermal proxies exist, but they are not a
real EPS, battery, or thermal-balance model. Bounded packet accounting and
deterministic delivery/retry proxies exist, but there is no real RF propagation,
BER/FER, protocol stack, or link budget. Public KazEOSat-1 values are reference
and sanity-check metadata only; no model is calibrated from real telemetry.

The RUL and reliability statistical layer is simulation-based and
horizon-censored. It is not a calibrated physics-of-failure model, real lifetime
prediction, or operational reliability estimate, and it does not extrapolate a
lifetime beyond the requested horizon. Wilson and bootstrap intervals quantify
finite Monte Carlo sample uncertainty, not parameter, model-form, or model
uncertainty.

Public-spec sanity checks are consistency/reference checks, not calibration or validation against operational data.
Internal structural consistency checks are
not external validation. Layer-ablation deltas are within-model sensitivities,
not physical causal effects; some ablations intentionally change coupled layers.
All outputs are model-dependent proxy results, not real KazEOSat-1 forecasts or
operational recommendations.
"""
    paper_dir.joinpath("limitations_autogenerated.md").write_text(
        limitations, encoding="utf-8"
    )


def _remove_named_files(directory: Path, filenames: Iterable[str]) -> None:
    for filename in filenames:
        path = directory / filename
        if path.is_file():
            path.unlink()


def _prepare_directories(results_dir: Path) -> dict[str, Path]:
    directories = {
        name: results_dir / name for name in ("raw", "tables", "figures", "paper")
    }
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True)
    return directories


def run_suite_decision_report(
    design: ExperimentDesign,
    results_dir: Path,
    *,
    quick: bool,
):
    """Run the optional report with the profile's primary configuration."""
    decision_years = design.years if quick else min(design.years, 1.0)
    return run_decision_report(
        years=decision_years,
        policy="adaptive",
        scenario="nominal",
        seed=design.seed,
        results_dir=results_dir,
        **design.core_configuration.decision_report_kwargs(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        design = build_experiment_design(args)
    except ValueError as exc:
        parser.error(str(exc))

    directories = _prepare_directories(args.results_dir)
    decision_dir = args.results_dir / "decision"
    if not design.include_decision_report and decision_dir.is_dir():
        _remove_named_files(decision_dir, DECISION_FILES)
        if not any(decision_dir.iterdir()):
            decision_dir.rmdir()
    if args.skip_plots:
        _remove_named_files(directories["figures"], PLOT_FILES)
    if not design.run_rul:
        _remove_named_files(directories["raw"], RAW_RUL_FILES)
        _remove_named_files(directories["tables"], TABLE_RUL_FILES)
        _remove_named_files(directories["figures"], RUL_PLOT_FILES)
    if not design.is_final_v40:
        _remove_named_files(directories["raw"], FINAL_V40_RAW_FILES)
        _remove_named_files(directories["tables"], FINAL_V40_TABLE_FILES)

    # Import plotting support before expensive simulations so an unavailable
    # optional dependency fails promptly and clearly. Directories and explicit
    # stale-output cleanup above still reflect the requested suite flags.
    pyplot = None if args.skip_plots else _load_pyplot()

    stochastic_catalog = _shared_stochastic_catalog(design)
    core_rows = run_core_matrix(design, stochastic_catalog)
    ablation_rows = run_ablation_matrix(design, stochastic_catalog)
    _write_csv(directories["raw"] / "core_summary.csv", core_rows)
    _write_csv(directories["raw"] / "ablation_raw.csv", ablation_rows)

    rul_results = RULMatrixResults([], [], [], [], [], [], [])
    if design.run_rul:
        rul_results = run_rul_matrix(design)
        _write_csv(
            directories["raw"] / "rul_samples.csv",
            rul_results.samples,
        )
        _write_csv(
            directories["raw"] / "rul_summary.csv",
            rul_results.summaries,
        )
        _write_csv(
            directories["raw"] / "rul_survival_curve.csv",
            rul_results.survival_curve,
        )
        if design.is_final_v40:
            _write_csv(
                directories["raw"] / "rul_conditional_summary.csv",
                rul_results.conditional_summaries,
                CONDITIONAL_SUMMARY_FIELDS,
            )
            _write_csv(
                directories["raw"]
                / "rul_conditional_survival_curve.csv",
                rul_results.conditional_survival_curve,
                CONDITIONAL_SURVIVAL_FIELDS,
            )
            _write_csv(
                directories["raw"] / "rul_failure_modes.csv",
                rul_results.failure_modes,
                FAILURE_MODE_FIELDS,
            )
            _write_csv(
                directories["raw"]
                / "rul_censored_survivor_risk_drivers.csv",
                rul_results.censored_survivor_risks,
                SURVIVOR_RISK_FIELDS,
            )

    public_spec_rows = (
        [row.as_dict() for row in build_public_spec_sanity_rows()]
        if design.is_final_v40
        else []
    )

    tables = build_tables(
        design=design,
        core_rows=core_rows,
        ablation_rows=ablation_rows,
        rul_summary_rows=rul_results.summaries,
        tables_dir=directories["tables"],
        conditional_rul_summary_rows=(
            rul_results.conditional_summaries
        ),
        public_spec_rows=public_spec_rows,
    )
    if design.is_final_v40:
        validation_checks = build_internal_validation_checks(
            core_rows=core_rows,
            rul_sample_rows=rul_results.samples,
            conditional_summary_rows=rul_results.conditional_summaries,
            conditional_survival_rows=(
                rul_results.conditional_survival_curve
            ),
            failure_mode_rows=rul_results.failure_modes,
            survivor_risk_rows=rul_results.censored_survivor_risks,
            additional_numeric_tables={
                "ablation": ablation_rows,
                "rul_summary": rul_results.summaries,
                "rul_survival": rul_results.survival_curve,
                "layer_sensitivity": tables[
                    "layer_sensitivity_summary"
                ],
            },
            configuration=design.core_configuration,
        )
        validation_rows = [
            check.as_dict() for check in validation_checks
        ]
        validation_summary_rows = [
            row.as_dict()
            for row in summarize_validation_checks(validation_checks)
        ]
        _write_csv(
            directories["raw"] / "internal_validation_checks.csv",
            validation_rows,
            VALIDATION_CHECK_FIELDS,
        )
        _write_csv(
            directories["tables"] / "internal_validation_summary.csv",
            validation_summary_rows,
            VALIDATION_SUMMARY_FIELDS,
        )
        _write_markdown_table_with_note(
            directories["tables"] / "internal_validation_summary.md",
            "Internal research-output validation summary",
            (
                "These are structural consistency checks inside the proxy "
                "research package, not external or operational validation."
            ),
            validation_summary_rows,
            VALIDATION_SUMMARY_FIELDS,
        )
        raise_for_validation_failures(validation_checks)
    if not args.skip_plots:
        generate_plots(
            ranking_rows=tables["policy_ranking"],
            rul_summary_rows=rul_results.summaries,
            survival_curve_rows=rul_results.survival_curve,
            figures_dir=directories["figures"],
            plt=pyplot,
        )
    if design.include_decision_report:
        run_suite_decision_report(
            design,
            decision_dir,
            quick=args.quick,
        )
    write_paper_markdown(
        design=design,
        ranking_rows=tables["policy_ranking"],
        ablation_summary_rows=tables["ablation_summary"],
        rul_summary_rows=rul_results.summaries,
        paper_dir=directories["paper"],
        conditional_rul_summary_rows=rul_results.conditional_summaries,
        decision_report_included=design.include_decision_report,
    )

    print(
        "Paper suite complete: "
        f"{design.core_run_count} core runs, "
        f"{design.ablation_run_count} ablation runs, "
        f"{design.rul_simulation_count} RUL sample continuations, "
        f"{design.decision_run_count} decision report runs."
    )
    print(f"Outputs: {args.results_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
