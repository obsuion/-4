"""Dependency-free analysis helpers for the V3.0 paper suite.

The helpers in this module operate on CSV-shaped mappings and deliberately do
not know how an experiment was executed.  They provide a small, deterministic
analysis layer that can be reused by :mod:`paper_suite` and by downstream
notebooks without requiring pandas.

The paper score is a presentation aid, not an additional simulator metric.  It
uses the explicit weights and normalization modes below.  Missing optional
components are omitted and the remaining weights are renormalized, so a run is
not penalized merely because (for example) RUL was skipped.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from math import fsum, isfinite
from pathlib import Path
from statistics import fmean
from typing import Iterable, Mapping, Sequence


AnalysisValue = str | int | float | bool | None
AnalysisRow = dict[str, AnalysisValue]


# These weights intentionally sum to one.  They are public so generated paper
# methods can report the score definition verbatim.
PAPER_SCORE_WEIGHTS: dict[str, float] = {
    "simulator_score": 0.25,
    "survival_fraction": 0.20,
    "data_downlinked_gb": 0.20,
    "final_health": 0.15,
    "expected_rul_years_censored": 0.15,
    "fuel_remaining_percent": 0.05,
}

# Fractions and percentages have physically meaningful fixed bounds.  Metrics
# without a fixed useful bound are min-max normalized across candidate policies.
PAPER_SCORE_NORMALIZATION: dict[str, str] = {
    "simulator_score": "minmax",
    "survival_fraction": "fraction",
    "data_downlinked_gb": "minmax",
    "final_health": "fraction",
    "expected_rul_years_censored": "minmax",
    "fuel_remaining_percent": "percent",
}

DEFAULT_ABLATION_METRICS: tuple[str, ...] = (
    "simulator_score",
    "survival_fraction",
    "data_downlinked_gb",
    "final_health",
    "fuel_remaining_percent",
    "expected_rul_years_censored",
)

DEFAULT_SENSITIVITY_METRICS = DEFAULT_ABLATION_METRICS


_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "simulator_score": ("simulator_score", "score", "mean_score"),
    "survival_fraction": (
        "survival_fraction",
        "survived_fraction",
        "alive_fraction",
        "survived_to_horizon_fraction",
        "probability_survive_to_horizon",
        "survived",
        "alive",
    ),
    "data_downlinked_gb": (
        "data_downlinked_gb",
        "total_data_downlinked_gb",
        "mean_data_downlinked_gb",
        "mean_data_downlinked_during_rul_gb",
    ),
    "final_health": (
        "final_health",
        "final_total_health",
        "mean_final_health",
    ),
    "fuel_remaining_percent": (
        "fuel_remaining_percent",
        "final_fuel_remaining_percent",
        "mean_final_fuel_remaining_percent",
    ),
    "expected_rul_years_censored": (
        "expected_rul_years_censored",
        "expected_rul_years",
        "mean_rul_years_censored",
    ),
    "median_rul_years_censored": (
        "median_rul_years_censored",
        "median_rul_years",
    ),
}

_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(
    r"^[+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[eE][+-]?\d+)?$"
)


@dataclass(frozen=True)
class AnalysisCSVData:
    """Rows loaded from the standard simulator and RUL CSV filenames."""

    summary: list[AnalysisRow]
    monte_carlo_summary: list[AnalysisRow]
    rul_samples: list[AnalysisRow]
    rul_summary: list[AnalysisRow]
    rul_survival_curve: list[AnalysisRow]


def parse_csv_value(value: str | None) -> AnalysisValue:
    """Parse one CSV cell without guessing schemas.

    Blank cells become ``None``.  Finite integer, floating-point, and boolean
    spellings become their Python equivalents; all other text is preserved.
    Non-finite spellings such as ``nan`` remain text because they are not valid
    analysis numbers and will consequently be ignored by numeric aggregation.
    """

    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if _INTEGER_RE.fullmatch(stripped):
        try:
            return int(stripped)
        except ValueError:
            return stripped
    if _FLOAT_RE.fullmatch(stripped):
        try:
            number = float(stripped)
        except ValueError:
            return stripped
        return number if isfinite(number) else stripped
    return stripped


def load_csv_rows(
    path: str | Path, *, optional: bool = False
) -> list[AnalysisRow]:
    """Load a CSV as parsed mappings, optionally accepting a missing file."""

    csv_path = Path(path)
    if not csv_path.exists():
        if optional:
            return []
        raise FileNotFoundError(f"Required analysis CSV not found: {csv_path}")
    if not csv_path.is_file():
        raise ValueError(f"Analysis CSV path is not a file: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"Analysis CSV has no header: {csv_path}")
        rows: list[AnalysisRow] = []
        for raw_row in reader:
            # DictReader uses a None key for surplus cells.  Ignoring that key
            # keeps the returned shape restricted to the declared CSV schema.
            rows.append({
                key: parse_csv_value(value)
                for key, value in raw_row.items()
                if key is not None
            })
        return rows


def load_analysis_csvs(
    results_dir: str | Path, *, skip_rul: bool = False
) -> AnalysisCSVData:
    """Load the standard run/RUL CSV package from ``results_dir``.

    ``summary.csv`` is always required.  Monte Carlo output is optional.  The
    three RUL files are required unless ``skip_rul`` is true; in that mode they
    are not opened and the corresponding collections are empty.
    """

    directory = Path(results_dir)
    if skip_rul:
        rul_samples: list[AnalysisRow] = []
        rul_summary: list[AnalysisRow] = []
        rul_survival_curve: list[AnalysisRow] = []
    else:
        rul_samples = load_csv_rows(directory / "rul_samples.csv")
        rul_summary = load_csv_rows(directory / "rul_summary.csv")
        rul_survival_curve = load_csv_rows(
            directory / "rul_survival_curve.csv"
        )
    return AnalysisCSVData(
        summary=load_csv_rows(directory / "summary.csv"),
        monte_carlo_summary=load_csv_rows(
            directory / "monte_carlo_summary.csv", optional=True
        ),
        rul_samples=rul_samples,
        rul_summary=rul_summary,
        rul_survival_curve=rul_survival_curve,
    )


def _as_number(value: object) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return number if isfinite(number) else None
    if isinstance(value, str):
        parsed = parse_csv_value(value)
        if isinstance(parsed, bool):
            return float(parsed)
        if isinstance(parsed, (int, float)):
            number = float(parsed)
            return number if isfinite(number) else None
    return None


def metric_value(row: Mapping[str, object], metric: str) -> float | None:
    """Return the first numeric value for a canonical metric or direct field.

    For simulator summary rows, survival can also be derived from
    ``survived_hours / total_hours`` when no explicit fraction is present.
    """

    if metric == "survival_fraction":
        explicit_fraction_fields = _METRIC_ALIASES[metric][:-2]
        for field in explicit_fraction_fields:
            value = _as_number(row.get(field))
            if value is not None:
                return value
        survived_hours = _as_number(row.get("survived_hours"))
        total_hours = _as_number(row.get("total_hours"))
        if (
            survived_hours is not None
            and total_hours is not None
            and total_hours > 0.0
        ):
            return survived_hours / total_hours
        for field in ("survived", "alive"):
            value = _as_number(row.get(field))
            if value is not None:
                return value
        return None

    aliases = _METRIC_ALIASES.get(metric, (metric,))
    for field in aliases:
        value = _as_number(row.get(field))
        if value is not None:
            return value
    return None


def _mean_metric(
    rows: Iterable[Mapping[str, object]], metric: str
) -> float | None:
    values = [
        value
        for row in rows
        if (value := metric_value(row, metric)) is not None
    ]
    return fmean(values) if values else None


def normalize_metric_values(
    values: Sequence[float | None], mode: str
) -> list[float | None]:
    """Normalize values using one of the public paper-score modes.

    ``fraction`` clips to ``[0, 1]``; ``percent`` divides by 100 and clips;
    ``minmax`` scales finite candidates to ``[0, 1]``.  If all finite min-max
    values are equal, each receives 1.0 because they are tied at the maximum.
    Missing values remain ``None``.
    """

    if mode == "fraction":
        return [
            None if value is None else max(0.0, min(1.0, value))
            for value in values
        ]
    if mode == "percent":
        return [
            None
            if value is None
            else max(0.0, min(1.0, value / 100.0))
            for value in values
        ]
    if mode != "minmax":
        raise ValueError(
            f"Unknown normalization mode {mode!r}; choose fraction, "
            "minmax, or percent"
        )
    present = [value for value in values if value is not None]
    if not present:
        return [None for _ in values]
    lower = min(present)
    upper = max(present)
    if upper == lower:
        return [None if value is None else 1.0 for value in values]
    span = upper - lower
    return [
        None if value is None else (value - lower) / span
        for value in values
    ]


def _policy_name(row: Mapping[str, object]) -> str:
    policy = row.get("policy")
    if policy is None or not str(policy).strip():
        raise ValueError("Every row used for policy ranking must name a policy")
    return str(policy)


def _competition_ranks(
    records: Sequence[Mapping[str, object]], metric: str
) -> list[int | None]:
    """Return descending competition ranks, leaving missing values unranked.

    Equal values share a rank (``1, 1, 3``).  Policy name is used only to make
    the processing order deterministic and never breaks a numeric tie.
    """

    ranked_values = [
        (index, value, str(record["policy"]))
        for index, record in enumerate(records)
        if (value := _as_number(record.get(metric))) is not None
    ]
    ranked_values.sort(key=lambda item: (-item[1], item[2]))
    ranks: list[int | None] = [None] * len(records)
    previous_value: float | None = None
    previous_rank = 0
    for position, (index, value, _policy) in enumerate(
        ranked_values, start=1
    ):
        if previous_value is None or value != previous_value:
            previous_rank = position
            previous_value = value
        ranks[index] = previous_rank
    return ranks


def rank_policies(
    simulator_rows: Sequence[Mapping[str, object]],
    rul_summary_rows: Sequence[Mapping[str, object]] = (),
) -> list[AnalysisRow]:
    """Aggregate and rank policies with the transparent paper score.

    Simulator and RUL rows are averaged independently per policy.  The paper
    score combines the normalized components in ``PAPER_SCORE_WEIGHTS``.  When
    an optional component is unavailable for a policy, available component
    weights are renormalized to sum to one.  Each raw ranking metric also gets
    a descending competition-rank column (equal values use ``1, 1, 3`` and
    missing values use ``None``).  Results sort by paper score, then simulator
    score, then policy name for deterministic ties.
    """

    simulator_by_policy: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    rul_by_policy: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in simulator_rows:
        simulator_by_policy[_policy_name(row)].append(row)
    for row in rul_summary_rows:
        rul_by_policy[_policy_name(row)].append(row)

    policies = sorted(set(simulator_by_policy) | set(rul_by_policy))
    if not policies:
        return []

    records: list[AnalysisRow] = []
    for policy in policies:
        simulator_group = simulator_by_policy.get(policy, [])
        rul_group = rul_by_policy.get(policy, [])
        survival = _mean_metric(simulator_group, "survival_fraction")
        if survival is None:
            survival = _mean_metric(rul_group, "survival_fraction")
        record: AnalysisRow = {
            "policy": policy,
            "runs": len(simulator_group),
            "simulator_score": _mean_metric(
                simulator_group, "simulator_score"
            ),
            "survival_fraction": survival,
            "data_downlinked_gb": _mean_metric(
                simulator_group, "data_downlinked_gb"
            ),
            "final_health": _mean_metric(simulator_group, "final_health"),
            "fuel_remaining_percent": _mean_metric(
                simulator_group, "fuel_remaining_percent"
            ),
            "expected_rul_years_censored": _mean_metric(
                rul_group, "expected_rul_years_censored"
            ),
            "median_rul_years_censored": _mean_metric(
                rul_group, "median_rul_years_censored"
            ),
        }
        records.append(record)

    rank_metrics = (
        "simulator_score",
        "survival_fraction",
        "data_downlinked_gb",
        "final_health",
        "fuel_remaining_percent",
        "expected_rul_years_censored",
        "median_rul_years_censored",
    )
    for metric in rank_metrics:
        ranks = _competition_ranks(records, metric)
        for record, metric_rank in zip(records, ranks):
            record[f"{metric}_rank"] = metric_rank

    for metric in PAPER_SCORE_WEIGHTS:
        normalized = normalize_metric_values(
            [_as_number(record.get(metric)) for record in records],
            PAPER_SCORE_NORMALIZATION[metric],
        )
        for record, value in zip(records, normalized):
            record[f"normalized_{metric}"] = value

    for record in records:
        weighted_components = [
            (weight, _as_number(record.get(f"normalized_{metric}")))
            for metric, weight in PAPER_SCORE_WEIGHTS.items()
        ]
        available = [
            (weight, value)
            for weight, value in weighted_components
            if value is not None
        ]
        available_weight = fsum(weight for weight, _ in available)
        record["paper_score"] = (
            fsum(weight * value for weight, value in available)
            / available_weight
            if available_weight > 0.0
            else None
        )

    def descending_number(record: Mapping[str, object], field: str) -> float:
        value = _as_number(record.get(field))
        return float("inf") if value is None else -value

    records.sort(key=lambda record: (
        descending_number(record, "paper_score"),
        descending_number(record, "simulator_score"),
        str(record["policy"]),
    ))
    for rank, record in enumerate(records, start=1):
        # Rebuild the mapping so rank is the first CSV/Markdown column.
        record_copy = {"rank": rank, **record}
        record.clear()
        record.update(record_copy)
    return records


def _validate_named_rows(
    rows: Sequence[Mapping[str, object]], field: str, purpose: str
) -> None:
    if any(row.get(field) is None or not str(row.get(field)).strip() for row in rows):
        raise ValueError(f"Every row used for {purpose} must define {field!r}")


def compute_ablation_deltas(
    rows: Sequence[Mapping[str, object]],
    comparisons: Sequence[tuple[str, str]],
    *,
    label_field: str = "configuration",
    group_fields: Sequence[str] = ("policy", "scenario"),
    metrics: Sequence[str] = DEFAULT_ABLATION_METRICS,
) -> list[AnalysisRow]:
    """Compute wide pairwise ablation rows as ``comparison - baseline``.

    Duplicate runs for one group/configuration are averaged before subtraction.
    Groups without both requested configurations are omitted.  Missing optional
    metrics produce ``None`` baseline/comparison/delta cells rather than errors.
    """

    _validate_named_rows(rows, label_field, "ablation analysis")
    grouped: dict[
        tuple[object, ...], dict[str, list[Mapping[str, object]]]
    ] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        group_key = tuple(row.get(field) for field in group_fields)
        grouped[group_key][str(row[label_field])].append(row)

    result: list[AnalysisRow] = []
    for group_key in sorted(grouped, key=lambda key: tuple(map(str, key))):
        configurations = grouped[group_key]
        for baseline, comparison in comparisons:
            if baseline not in configurations or comparison not in configurations:
                continue
            output: AnalysisRow = {
                field: value
                for field, value in zip(group_fields, group_key)
            }
            output.update({
                "baseline": baseline,
                "comparison": comparison,
            })
            for metric in metrics:
                baseline_value = _mean_metric(
                    configurations[baseline], metric
                )
                comparison_value = _mean_metric(
                    configurations[comparison], metric
                )
                output[f"{metric}_baseline"] = baseline_value
                output[f"{metric}_comparison"] = comparison_value
                output[f"{metric}_delta"] = (
                    comparison_value - baseline_value
                    if baseline_value is not None
                    and comparison_value is not None
                    else None
                )
            result.append(output)
    return result


def summarize_sensitivity(
    rows: Sequence[Mapping[str, object]],
    *,
    label_field: str = "sensitivity_label",
    group_fields: Sequence[str] = (),
    metrics: Sequence[str] = DEFAULT_SENSITIVITY_METRICS,
) -> list[AnalysisRow]:
    """Return mean/min/max metrics for each sensitivity label and group."""

    _validate_named_rows(rows, label_field, "sensitivity analysis")
    grouped: dict[tuple[object, ...], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field) for field in group_fields) + (
            row[label_field],
        )
        grouped[key].append(row)

    result: list[AnalysisRow] = []
    for key in sorted(grouped, key=lambda item: tuple(map(str, item))):
        group_values = key[:-1]
        label = key[-1]
        group_rows = grouped[key]
        output: AnalysisRow = {
            field: value
            for field, value in zip(group_fields, group_values)
        }
        output[label_field] = label  # type: ignore[assignment]
        output["rows"] = len(group_rows)
        for metric in metrics:
            values = [
                value
                for row in group_rows
                if (value := metric_value(row, metric)) is not None
            ]
            output[f"{metric}_mean"] = fmean(values) if values else None
            output[f"{metric}_min"] = min(values) if values else None
            output[f"{metric}_max"] = max(values) if values else None
        result.append(output)
    return result


def _markdown_cell(value: object, float_digits: int, none_value: str) -> str:
    if value is None:
        text = none_value
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float):
        if not isfinite(value):
            text = none_value
        else:
            text = f"{value:.{float_digits}f}".rstrip("0").rstrip(".")
            if text == "-0":
                text = "0"
    else:
        text = str(value)
    return text.replace("\r\n", "<br>").replace("\n", "<br>").replace("|", "\\|")


def render_markdown_table(
    rows: Sequence[Mapping[str, object]],
    columns: Sequence[str] | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    float_digits: int = 3,
    none_value: str = "",
) -> str:
    """Render compact GitHub-flavored Markdown from mapping rows.

    Column order defaults to first appearance across the input mappings.
    Supplying ``columns`` allows a header-only table when ``rows`` is empty.
    """

    if float_digits < 0:
        raise ValueError("float_digits must be non-negative")
    if columns is None:
        ordered: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for column in row:
                if column not in seen:
                    seen.add(column)
                    ordered.append(column)
        columns = ordered
    else:
        columns = list(columns)
    if not columns:
        return ""

    labels = [
        (headers or {}).get(column, column.replace("_", " ").title())
        for column in columns
    ]
    lines = [
        "| " + " | ".join(
            _markdown_cell(label, float_digits, none_value)
            for label in labels
        ) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(row.get(column), float_digits, none_value)
                for column in columns
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "AnalysisCSVData",
    "AnalysisRow",
    "AnalysisValue",
    "DEFAULT_ABLATION_METRICS",
    "DEFAULT_SENSITIVITY_METRICS",
    "PAPER_SCORE_NORMALIZATION",
    "PAPER_SCORE_WEIGHTS",
    "compute_ablation_deltas",
    "load_analysis_csvs",
    "load_csv_rows",
    "metric_value",
    "normalize_metric_values",
    "parse_csv_value",
    "rank_policies",
    "render_markdown_table",
    "summarize_sensitivity",
]
