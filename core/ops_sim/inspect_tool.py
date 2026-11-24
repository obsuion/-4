"""Read and display saved hourly simulator state in several focused views."""

import argparse
import csv
from pathlib import Path

from .reporting import print_table


DEFAULT_STATE_LOG = Path("results/state_log.csv")
IDENTIFIER_FIELDS = ("policy", "scenario", "hour", "year")
SYSTEM_FIELDS = (
    "health", "eps_health", "solar_health", "battery_health", "comms_health",
    "payload_health", "storage_health", "adcs_health", "obc_health",
    "thermal_health", "propulsion_health", "effective_energy_margin",
    "effective_storage_capacity_gb", "pointing_efficiency",
    "effective_downlink_rate_gb_per_min", "effective_imaging_rate_gb_per_hour",
    "data_lost_gb", "overflow_hours", "minimum_soc", "minimum_health",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect saved hourly simulator state",
        epilog=(
            "View precedence when combined: --around, --fields, --systems, --full, "
            "then the default compact report. --list-fields works by itself."
        ),
    )
    parser.add_argument("--policy")
    parser.add_argument("--scenario")
    parser.add_argument("--hour", type=int)
    parser.add_argument("--nearest", action="store_true")
    parser.add_argument("--full", action="store_true", help="print every field in the selected row")
    parser.add_argument(
        "--systems", action="store_true",
        help="print subsystem health and operational capability fields",
    )
    parser.add_argument(
        "--fields", help="comma-separated fields to print with run identifiers"
    )
    parser.add_argument(
        "--around", type=int, metavar="HOURS",
        help="print a compact window before and after the selected hour",
    )
    parser.add_argument(
        "--list-fields", action="store_true",
        help="list state-log columns; no run selection is required",
    )
    parser.add_argument("--state-log", type=Path, default=DEFAULT_STATE_LOG)
    return parser


def _missing_log_message(path: Path) -> str:
    return f"{path.as_posix()} not found. Run an experiment first with python run.py ..."


def _read_fieldnames(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or [])


def _read_matching_rows(
    path: Path, policy: str, scenario: str
) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            row for row in csv.DictReader(handle)
            if row.get("policy") == policy and row.get("scenario") == scenario
        ]


def _print_key_values(row: dict[str, str], fields: list[str]) -> None:
    available = [field for field in fields if field in row]
    width = max((len(field) for field in available), default=0)
    for field in available:
        print(f"{field.ljust(width)} : {row[field]}")


def _interpret(row: dict[str, str]) -> str:
    mode = row["mode"]
    if mode == "EMERGENCY_BEACON":
        return "The satellite is prioritizing survival and contact recovery."
    if mode == "BACKUP":
        return "The daily plan has expired and onboard backup behavior is active."
    if mode == "SAFE":
        return "Safe mode is protecting the spacecraft while power is constrained."
    if mode == "IMAGING":
        return "The payload is acquiring imagery and adding it to onboard storage."
    if mode == "DOWNLINK":
        return "Stored payload data is being transmitted during a data contact."
    if mode == "MANEUVER":
        return "A coarse maneuver proxy is consuming SOC and delta-v."
    return "The satellite is in standby between operational activities."


def _print_default(row: dict[str, str]) -> None:
    print(f"Policy: {row['policy']}")
    print(f"Scenario: {row['scenario']}")
    print(f"Hour / year: {row['hour']} / {float(row['year']):.6f}")
    print(f"Current mode: {row['mode']}")
    print(f"SOC / health: {float(row['soc']):.2f}% / {float(row['health']):.4f}")
    print(f"Buffer: {float(row['buffer_gb']):.2f} GB")
    if "effective_storage_capacity_gb" in row:
        print(
            "Effective storage capacity: "
            f"{float(row['effective_storage_capacity_gb']):.2f} GB"
        )
    if "data_lost_gb" in row:
        print(
            f"Data lost / overflow hours: {float(row['data_lost_gb']):.2f} GB / "
            f"{row['overflow_hours']}"
        )
    if "pointing_efficiency" in row:
        print(f"Pointing efficiency: {float(row['pointing_efficiency']):.4f}")
    if "effective_energy_margin" in row:
        print(f"Effective energy margin: {float(row['effective_energy_margin']):.2f}")
    if "effective_downlink_rate_gb_per_min" in row:
        print(
            "Effective downlink rate: "
            f"{float(row['effective_downlink_rate_gb_per_min']):.4f} GB/min"
        )
    print(f"Contacts: command {row['cmd_contact_min']} min, data {row['data_contact_min']} min")
    print(f"Daily plan valid: {row['valid_daily_plan']} (age {row['daily_plan_age_hours']} h)")
    print(f"Hours since contact: {row['hours_since_contact']}")
    print(
        "Approximate position: "
        f"{float(row['sat_lat_deg']):.3f} deg lat, "
        f"{float(row['sat_lon_deg']):.3f} deg lon, "
        f"{float(row['sat_alt_km']):.1f} km altitude"
    )
    print(f"Interpretation: {_interpret(row)}")


def _format_window_value(field: str, value: str) -> str:
    decimals = {
        "year": 6, "soc": 2, "health": 4, "buffer_gb": 2,
        "data_lost_gb": 2, "effective_energy_margin": 2,
    }
    if field not in decimals:
        return value
    return f"{float(value):.{decimals[field]}f}"


def _print_window(
    matches: list[dict[str, str]], center_hour: int, radius: int
) -> None:
    candidates = [
        "hour", "year", "mode", "soc", "health", "buffer_gb",
        "data_lost_gb", "effective_energy_margin",
    ]
    fields = [field for field in candidates if field in matches[0]]
    window = [
        row for row in matches
        if center_hour - radius <= int(row["hour"]) <= center_hour + radius
    ]
    print_table(
        fields,
        [[_format_window_value(field, row[field]) for field in fields] for row in window],
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.around is not None and args.around < 0:
        parser.error("--around must be non-negative")

    if not args.state_log.exists():
        print(_missing_log_message(args.state_log))
        return 1

    if args.list_fields:
        fieldnames = _read_fieldnames(args.state_log)
        print("Available state_log fields:")
        for field in fieldnames:
            print(field)
        return 0

    if args.policy is None or args.scenario is None or args.hour is None:
        parser.error("--policy, --scenario, and --hour are required unless --list-fields is used")

    fieldnames = _read_fieldnames(args.state_log)
    matches = _read_matching_rows(args.state_log, args.policy, args.scenario)
    if not matches:
        print("No saved run matches that policy and scenario")
        return 1

    row = next((item for item in matches if int(item["hour"]) == args.hour), None)
    if row is None and args.nearest:
        row = min(matches, key=lambda item: abs(int(item["hour"]) - args.hour))
    if row is None:
        print("Exact hour not found; use --nearest to select the closest hour")
        return 1

    # Deliberate view precedence: around > fields > systems > full > default.
    if args.around is not None:
        _print_window(matches, int(row["hour"]), args.around)
    elif args.fields is not None:
        requested = [field.strip() for field in args.fields.split(",") if field.strip()]
        selected = list(IDENTIFIER_FIELDS)
        selected.extend(
            field for field in requested if field not in selected and field in row
        )
        _print_key_values(row, selected)
        missing = [field for field in requested if field not in row]
        if missing:
            print(f"Warning: unavailable fields: {', '.join(missing)}")
    elif args.systems:
        _print_key_values(row, [*IDENTIFIER_FIELDS, *SYSTEM_FIELDS])
    elif args.full:
        _print_key_values(row, fieldnames)
    else:
        _print_default(row)
    return 0
