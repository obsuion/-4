"""Display the saved experiment summary ordered by score."""

import argparse
import csv
from pathlib import Path

from ops_sim.reporting import print_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare saved experiment results")
    parser.add_argument("--summary", type=Path, default=Path("results/summary.csv"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.summary.exists():
        raise SystemExit(f"Summary not found: {args.summary}")
    with args.summary.open(newline="", encoding="utf-8") as handle:
        rows = sorted(csv.DictReader(handle), key=lambda row: float(row["score"]), reverse=True)
    print_table(
        ["Policy", "Scenario", "Survival", "Health", "SOC", "Downlinked GB",
         "Lost GB", "Overflow h", "Emergency", "Score"],
        [[row["policy"], row["scenario"], row["survived"],
          f'{float(row["final_health"]):.4f}', f'{float(row["final_soc"]):.2f}',
          f'{float(row["data_downlinked_gb"]):.2f}',
          f'{float(row.get("data_lost_gb", 0)):.2f}', row.get("overflow_hours", "0"),
          f'{float(row.get("emergency_mode_fraction", 0)):.4f}',
          f'{float(row["score"]):.4f}']
         for row in rows],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
