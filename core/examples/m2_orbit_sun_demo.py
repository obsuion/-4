"""Synthetic short point queries, not an ephemeris or mission simulation."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

from examples.v5_j2_enclosure_pilot import inputs as synthetic_trajectory
from ops_sim.v5.frames import CartesianDirection, CartesianState, CartesianVelocity
from ops_sim.v5.orbit import TwoBodySolverConfig, TwoBodyTrajectory
from ops_sim.v5.orbit_binding import CoastOrbitInputs
from ops_sim.v5.orbit_config import FrameKind, GeometryInstant
from ops_sim.v5.orbit_j2 import J2RK4SolverConfig
from ops_sim.v5.orbit_j2_binding import J2CoastOrbitInputs
from ops_sim.v5.orbit_j2_enclosure import J2EnclosurePolicy
from ops_sim.v5.orbit_sun import OrbitSunQuery, SuppliedSunDirection, evaluate_orbit_sun
from ops_sim.v5.orbit_sun_document import load_query, query_digest, save_query


def demo_query(kind="j2"):
    trajectory = synthetic_trajectory(True)
    coast = J2CoastOrbitInputs(trajectory, J2RK4SolverConfig(1/32, 32),
                               J2EnclosurePolicy(1/32, 32, .5, 50, 12))
    instant = GeometryInstant(trajectory.initial_state.position.instant.epoch, 128.125)
    frame = trajectory.initial_state.position.frame
    if kind == "two-body":
        p = trajectory.initial_state.position
        state = CartesianState(p, CartesianVelocity(p.frame, p.instant, (0., 2., 0.)))
        coast = CoastOrbitInputs(TwoBodyTrajectory(state, trajectory.gravity_model.gravitational_parameter_m3_s2),
                                 TwoBodySolverConfig(1e-12, 100))
    elif kind == "unresolved":
        coast = replace(coast, enclosure_policy=replace(coast.enclosure_policy, max_steps=1))
    elif kind == "rotated":
        frame = replace(frame, kind=FrameKind.EARTH_FIXED)
    elif kind != "j2":
        raise ValueError("unknown demo kind")
    sun = SuppliedSunDirection(CartesianDirection(frame, instant, (-1., 0., 0.)),
                               "SYNTHETIC", (), "Explicit single-instant synthetic ray; no seasonal accuracy")
    return OrbitSunQuery(coast, instant, sun)


def summary(result):
    e = result.j2_evidence
    state = result.orbit_state
    return {
        "query_digest": query_digest(result.query),
        "instant_seconds": result.query.instant.elapsed_seconds,
        "anchor_seconds": result.query.coast.trajectory.initial_state.position.instant.elapsed_seconds,
        "sun_origin": result.query.sun.origin,
        "position_m": None if state is None else state.position.components_m,
        "velocity_m_per_s": None if state is None else state.velocity.components_m_per_s,
        "sun_components": result.sun_direction.components,
        "unit_sun_components": result.unit_sun_direction.components,
        "nominal": result.shadow.nominal, "qualified": result.shadow.qualified,
        "reason": result.shadow.reason, "scope": result.shadow.scope,
        "j2": None if e is None else {
            "status": e.status, "reason": e.reason,
            "position_error_bound_m": e.position_error_bound_m,
            "velocity_error_bound_m_per_s": e.velocity_error_bound_m_per_s,
            "endpoint_intervals": None if e.endpoint_intervals is None else
                [[str(lo), str(hi)] for lo, hi in e.endpoint_intervals],
            "enclosure_steps": e.enclosure_steps, "nominal_steps": e.nominal_steps,
            "picard_attempts": e.picard_attempts}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--expected-digest")
    parser.add_argument("--write-inputs", type=Path)
    parser.add_argument("--kind", choices=("two-body", "j2", "unresolved", "rotated"), default="j2")
    args = parser.parse_args()
    if args.inputs and args.write_inputs:
        parser.error("choose loading or exclusive creation")
    if args.expected_digest and not args.inputs:
        parser.error("expected-digest requires inputs")
    q = load_query(args.inputs, expected_digest=args.expected_digest) if args.inputs else demo_query(args.kind)
    if args.write_inputs:
        save_query(args.write_inputs, q)
    start = perf_counter()
    result = evaluate_orbit_sun(q)
    elapsed = perf_counter()-start
    print(json.dumps({"evidence": summary(result), "wall_seconds": elapsed}, indent=2))


if __name__ == "__main__":
    main()
