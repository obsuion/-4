"""Short offline conditional model examples; no ephemeris or mission validation."""
import argparse
from dataclasses import asdict, replace
from fractions import Fraction
import json
from pathlib import Path
from time import perf_counter

from examples.v5_j2_enclosure_pilot import inputs
from examples.m2_sun_table_demo import synthetic_table
from examples.m2_j2_segments_demo import block_network, summary as j2_summary
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.orbit_j2 import J2RK4SolverConfig
from ops_sim.v5.orbit_j2_binding import J2CoastOrbitInputs
from ops_sim.v5.orbit_j2_enclosure import J2EnclosurePolicy
from ops_sim.v5.sun_table import SunPositionSample
from ops_sim.v5.sun_table_document import load_table
from ops_sim.v5.orbit_sun_intervals import (
    IntervalIlluminationPolicy, IntervalIlluminationRequest, evaluate_interval_illumination,
)
from ops_sim.v5.orbit_sun_intervals_document import (
    interval_request_digest, load_interval_request, save_interval_request,
)


KINDS = ("illuminated", "occulted", "ambiguous", "work-failure", "upstream-failure", "external")


def example_request(kind):
    if kind not in KINDS:
        raise ValueError("unknown example kind")
    trajectory = inputs(kind != "external")
    step = 10. if kind == "external" else 1/32
    start, end = 128., 128.+step
    if kind == "external":
        table = load_table(Path(__file__).resolve().parents[1]/"tests/fixtures/sun_horizons_20261001.json")
        state = trajectory.initial_state
        instant = GeometryInstant(table.epoch, start)
        state = replace(state, position=replace(state.position, frame=table.frame, instant=instant),
                        velocity=replace(state.velocity, frame=table.frame, instant=instant))
        trajectory = replace(trajectory, initial_state=state)
    else:
        if kind == "upstream-failure":
            end = start+2*step
        if kind == "ambiguous":
            a, b = (-1., 16., 0.), (-1., -16., 0.)
        else:
            x = -100. if kind == "occulted" else 100.
            a, b = (x, -1., 0.), (x, 1., 0.)
        samples = (SunPositionSample(start, a), SunPositionSample(end, b))
        if kind == "work-failure":
            samples = (samples[0], SunPositionSample((start+end)/2, (100.,0.,0.)), samples[1])
        table = replace(synthetic_table(trajectory.initial_state.position.frame),
                        domain_seconds=(start,end), samples=samples)
    policy = J2EnclosurePolicy(step, 1 if kind == "upstream-failure" else 32,
                               6000000 if kind == "external" else .5, 50, 12)
    coast = J2CoastOrbitInputs(trajectory, J2RK4SolverConfig(step,32), policy)
    return IntervalIlluminationRequest(coast, table, GeometryInstant(table.epoch,start),
        GeometryInstant(table.epoch,end), IntervalIlluminationPolicy(1 if kind == "work-failure" else 32))


def _wire(value):
    if type(value) is Fraction:
        # Hex integers avoid Python's decimal-int string length ceiling even
        # at the documented rational bit cap; signs and exact values survive.
        return {"numerator_hex": hex(value.numerator), "denominator_hex": hex(value.denominator)}
    if type(value) in (tuple, list):
        return [_wire(v) for v in value]
    if type(value) is dict:
        return {k:_wire(v) for k,v in value.items()}
    return value


def summary(result):
    return {"request_digest": interval_request_digest(result.request),
        "status":result.status, "reason":result.reason,
        "planned_geometry_cells":result.planned_geometry_cells,
        "geometry_cells_evaluated":result.geometry_cells_evaluated,
        "arithmetic_operations":result.arithmetic_operations,
        "propagation_calls":result.propagation_calls,
        "all_cells_classified":result.all_cells_classified,
        "combined_qualification":result.combined_qualification,
        "combined_reasons":result.combined_reasons,
        "source_kind":result.request.table.provenance.source_kind,
        "cells":None if result.cells is None else [_wire(asdict(c)) for c in result.cells],
        "j2_evidence":None if result.j2_evidence is None else j2_summary(result.j2_evidence)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=KINDS, default="illuminated")
    parser.add_argument("--inputs",type=Path)
    parser.add_argument("--write-inputs",type=Path)
    parser.add_argument("--expected-digest")
    parser.add_argument("--offline",action="store_true")
    args=parser.parse_args()
    if args.inputs and args.write_inputs:parser.error("choose reconstruction or exclusive creation")
    if args.expected_digest and not args.inputs:parser.error("expected-digest requires inputs")
    if args.offline:block_network()
    request=load_interval_request(args.inputs,expected_digest=args.expected_digest) if args.inputs else example_request(args.kind)
    if args.write_inputs:save_interval_request(args.write_inputs,request)
    start=perf_counter(); result=evaluate_interval_illumination(request); elapsed=perf_counter()-start
    print(json.dumps({"evidence":summary(result),"evaluation_seconds":elapsed,
                      "python_network_disabled":args.offline},indent=2))


if __name__=="__main__":main()
