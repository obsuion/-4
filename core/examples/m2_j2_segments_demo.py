"""Bounded synthetic J2 continuous tubes; no mission or full-day claim."""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

from examples.v5_j2_enclosure_pilot import inputs
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.orbit_j2 import J2RK4SolverConfig
from ops_sim.v5.orbit_j2_binding import J2CoastOrbitInputs
from ops_sim.v5.orbit_j2_enclosure import J2EnclosurePolicy
from ops_sim.v5.orbit_j2_segments import J2SegmentRequest, evaluate_j2_segments
from ops_sim.v5.orbit_j2_segments_document import (
    load_segment_request, save_segment_request, segment_request_digest,
)


def example_request(kind):
    """Reuse the explicitly assumed F3 inclined synthetic input, anchor=128 s."""
    trajectory = inputs(False)
    policy = J2EnclosurePolicy(10, 32 if kind != "unresolved" else 1, 6000000, 50, 12)
    coast = J2CoastOrbitInputs(trajectory, J2RK4SolverConfig(10, 32), policy)
    offsets = {"forward": (15., 65.), "backward": (-65., -15.),
               "crossing": (-25., 35.), "unresolved": (-25., 35.)}
    a, b = offsets[kind]
    epoch = trajectory.initial_state.position.instant.epoch
    return J2SegmentRequest(coast, GeometryInstant(epoch, 128+a), GeometryInstant(epoch, 128+b))


def summary(result):
    def time(value):
        return {"numerator": value.numerator, "denominator": value.denominator}
    return {
        "request_digest": segment_request_digest(result.request),
        "status": result.status, "reason": result.reason,
        "planned_steps": result.planned_steps, "enclosure_steps": result.enclosure_steps,
        "picard_attempts": result.picard_attempts, "nominal_steps": result.nominal_steps,
        "time_units": "elapsed SI seconds in original TT reference epoch",
        "cells": None if result.cells is None else [{
            "start_seconds": time(cell.start_seconds), "end_seconds": time(cell.end_seconds),
            "source_initial_seconds": time(cell.source_initial_seconds),
            "source_final_seconds": time(cell.source_final_seconds),
            "position_bounds_m": [[str(a), str(b)] for a, b in cell.position_bounds_m],
            "velocity_bounds_m_per_s": [[str(a), str(b)] for a, b in cell.velocity_bounds_m_per_s],
        } for cell in result.cells],
    }


def block_network():
    def deny(event, args):
        if event.startswith("socket.") or event == "urllib.Request":
            raise RuntimeError("Python network disabled for offline reconstruction")
    sys.addaudithook(deny)
    # Verify the guard without attempting a connection.
    import socket
    try:
        socket.getaddrinfo("example.invalid", 443)
    except RuntimeError:
        return
    raise AssertionError("network audit guard did not reject name resolution")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("forward", "backward", "crossing", "unresolved"), default="forward")
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--expected-digest")
    parser.add_argument("--write-inputs", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.inputs and args.write_inputs:
        parser.error("choose reconstruction or exclusive creation")
    if args.expected_digest and not args.inputs:
        parser.error("expected-digest requires inputs")
    if args.offline:
        block_network()
    request = (load_segment_request(args.inputs, expected_digest=args.expected_digest)
               if args.inputs else example_request(args.kind))
    if args.write_inputs:
        save_segment_request(args.write_inputs, request)
    started = perf_counter()
    result = evaluate_j2_segments(request)
    wall = perf_counter()-started
    print(json.dumps({"evidence": summary(result), "evaluation_seconds": wall,
                      "python_network_disabled": args.offline}, indent=2))


if __name__ == "__main__":
    main()
