"""Short offline Sun examples. Source fixture is not an ephemeris accuracy claim."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter

from examples.m2_orbit_sun_demo import demo_query
from examples.v5_j2_enclosure_pilot import parameter
from ops_sim.v5.frames import CartesianPosition, CartesianVelocity, CartesianState
from ops_sim.v5.orbit import TwoBodyTrajectory, TwoBodySolverConfig
from ops_sim.v5.orbit_binding import CoastOrbitInputs
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.sun_table import (
    SunPositionSample, SunPositionTable, SunTableProvenance, TableOrbitSunQuery,
    evaluate_sun_position, evaluate_table_orbit_sun,
)
from ops_sim.v5.sun_table_document import load_table, load_table_query, save_table_query, table_query_digest


def synthetic_table(frame):
    provenance = SunTableProvenance(
        "SYNTHETIC", "10", "500@399", "MODEL_INERTIAL", "MODEL_EQUATOR",
        "GEOMETRIC", "TT", "M", "IDENTITY_METRES", "IDENTITY_MODEL", (),
        "synthetic:affine-example", None, None, None, None, "UNQUANTIFIED",
        "Synthetic prescribed table, not a physical solar ephemeris.",
        "Already expressed in the declared model axes.")
    return SunPositionTable(frame.rotation.epoch, frame, (0.,256.), "LINEAR_POSITION_V1",
        (SunPositionSample(0.,(100.,0.,0.)), SunPositionSample(128.,(-100.,50.,0.)),
         SunPositionSample(256.,(-100.,100.,0.))), provenance)


def example_query(kind):
    if kind=="external":
        table=load_table(Path(__file__).resolve().parents[1]/"tests/fixtures/sun_horizons_20261001.json")
        at=GeometryInstant(table.epoch,128.)
        state=CartesianState(CartesianPosition(table.frame,at,(7000000.,0.,0.)),
                             CartesianVelocity(table.frame,at,(0.,7500.,0.)))
        coast=CoastOrbitInputs(TwoBodyTrajectory(state,
             parameter("orbit.gravity.gravitational-parameter",4e14,"m^3/s^2")),TwoBodySolverConfig(1e-12,100))
        return TableOrbitSunQuery(coast,table,GeometryInstant(table.epoch,128.125))
    old=demo_query(kind)
    return TableOrbitSunQuery(old.coast,synthetic_table(old.sun.direction.frame),old.instant)


def summary(result):
    q=result.query;e=result.j2_evidence;c=result.fixed_ray_assessment
    return {"query_digest":table_query_digest(q),"instant_seconds":q.instant.elapsed_seconds,
        "anchor_seconds":q.coast.trajectory.initial_state.position.instant.elapsed_seconds,
        "sun_position_m":result.sun_position.components_m,
        "orbit_position_m":None if result.orbit_state is None else result.orbit_state.position.components_m,
        "spacecraft_to_sun_m":result.spacecraft_to_sun_m,
        "nominal":None if c is None else c.shadow.nominal,
        "fixed_ray_conditional":None if c is None else c.shadow.qualified,
        "fixed_ray_scope":None if c is None else c.shadow.scope,
        "combined_qualification":result.combined_qualification,"combined_reasons":result.combined_reasons,
        "source_kind":q.table.provenance.source_kind,"accuracy_policy":q.table.provenance.accuracy_policy,
        "j2":None if e is None else {"status":e.status,"reason":e.reason,
            "anchor_seconds":e.trajectory.initial_state.position.instant.elapsed_seconds,
            "position_error_bound_m":e.position_error_bound_m,
            "velocity_error_bound_m_per_s":e.velocity_error_bound_m_per_s,
            "endpoint_intervals":None if e.endpoint_intervals is None else [[str(a),str(b)] for a,b in e.endpoint_intervals],
            "nominal_steps":e.nominal_steps,"enclosure_steps":e.enclosure_steps}}


def block_network():
    """Deny Python socket/urllib audit events in this fresh process."""
    def deny(event,args):
        if event.startswith("socket.") or event=="urllib.Request":
            raise RuntimeError("network disabled for offline reconstruction")
    sys.addaudithook(deny)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kind",choices=("two-body","j2","unresolved","external"),default="j2")
    p.add_argument("--inputs",type=Path);p.add_argument("--expected-digest")
    p.add_argument("--write-inputs",type=Path);p.add_argument("--offline",action="store_true")
    args=p.parse_args()
    if args.inputs and args.write_inputs:p.error("choose load or exclusive creation")
    if args.expected_digest and not args.inputs:p.error("expected-digest requires inputs")
    if args.offline:block_network()
    q=load_table_query(args.inputs,expected_digest=args.expected_digest) if args.inputs else example_query(args.kind)
    if args.write_inputs:save_table_query(args.write_inputs,q)
    start=perf_counter();sun=evaluate_sun_position(q.table,q.instant);provider_s=perf_counter()-start
    start=perf_counter();result=evaluate_table_orbit_sun(q);query_s=perf_counter()-start
    assert sun==result.sun_position
    print(json.dumps({"evidence":summary(result),"provider_seconds":provider_s,
                      "integrated_seconds":query_s,"python_network_disabled":args.offline},indent=2))


if __name__=="__main__":main()
