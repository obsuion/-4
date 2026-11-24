"""Run the first request with the core Python model. Usage: python examples/first_delivery.py D1"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent / "core"
sys.path.insert(0, str(CORE))

from ops_sim.v5.lifecycle_document import loads_root
from ops_sim.v5.lifecycle_execution import start_lifecycle, step_lifecycle


# Digest of the unmodified 90-day input bytes carried by the original constructor.
INPUTS = {
    "D1": ("D1_BALANCED.json", "8351dc53f2286fe926101878aa7df961bcc7395083dcd6f17ec895ed225469df"),
    "D2": ("D2_LIGHT.json", "96fae2916b2f7ccab61009bd890b2bf0276653cdb2a9f76111ae594998ed3f0e"),
}


def main():
    parser = argparse.ArgumentParser(description="Simulate one delivered observation and compare it to the recorded mission prefix.")
    parser.add_argument("design", choices=INPUTS, nargs="?", default="D1")
    args = parser.parse_args()
    name, expected_sha = INPUTS[args.design]
    raw = (HERE / "inputs" / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError(f"Unexpected mission input bytes: {name}")
    ref = json.loads((HERE / "first-delivery.reference.json").read_text(encoding="utf8"))["events"]

    # This public in-memory lifecycle evolves the orbit, attitude, energy, thermal
    # state, operator, payload and contact. No event replay or preloaded checkpoint.
    root = loads_root(raw)
    state = start_lifecycle(root)
    print(f"{args.design}: clock starts at {state.clock} s. Simulating the first delivery.", flush=True)
    credit = None
    for expected in ref:
        state, event, _ = step_lifecycle(state)
        for key, recorded in expected.items():
            if event[key] != recorded:
                raise ValueError(f"Transition {expected['index']}, {key}: simulated {event[key]!r}, recorded {recorded!r}")
        if event["kind"] in {"POINT", "CAPTURE"}:
            print(f"{event['kind']:7s}  {event['start_seconds']} to {event['end_seconds']} s: {event['status']}")
        if event["kind"] == "CONTACT" and event["index"] == 9:
            print(f"CONTACT  from {event['start_seconds']} s")
        if event["credits"]:
            credit = event["credits"][0]

    if credit is None:
        raise ValueError("No credited product within the recorded prefix")
    time = Fraction(*map(int, credit["completion_time"]))
    since_release = time - credit["released_at_seconds"]
    print(f"DELIVER  {credit['request_id']}: {credit['useful_bits']} bits at clock {float(time):.3f} s "
          f"(+{float(since_release):.3f} s since release)")
    print(f"Matched all {len(ref)} recorded transitions on the selected event fields; stopped at clock {state.clock} s.")


if __name__ == "__main__":
    main()
