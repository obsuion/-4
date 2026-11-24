"""Command-line interface for running and comparing simulations."""

import argparse
import json

from .config import DEFAULT_CONFIG
from .policies import POLICIES, make_policy
from .scenarios import SCENARIOS, make_scenario
from .simulator import Simulator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Version 1 simplified proxy satellite operations simulator."
    )
    parser.add_argument(
        "--years", type=float, default=DEFAULT_CONFIG.default_simulation_years
    )
    parser.add_argument("--policy", choices=sorted(POLICIES), default="adaptive")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="nominal")
    parser.add_argument(
        "--json", action="store_true", help="print the complete result as JSON"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    simulator = Simulator(make_policy(args.policy), make_scenario(args.scenario))
    result = simulator.run(args.years)
    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        state = result.state
        print(f"Policy: {result.policy_name}")
        print(f"Scenario: {result.scenario_name}")
        print(f"Survived: {state.alive} ({state.hours_completed}/{result.total_hours} h)")
        print(f"Final SOC: {state.soc:.2f}%")
        print(f"Final health: {result.metrics.final_total_health:.4f}")
        print(f"Downlinked: {state.total_data_downlinked_gb:.2f} GB")
        print(f"Score: {result.metrics.score:.4f}")
        if state.loss_reason:
            print(f"Loss reason: {state.loss_reason.value}")
    return 0
