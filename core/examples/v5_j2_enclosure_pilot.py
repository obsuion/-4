"""Small F3 usefulness pilot; JSON to stdout, no repository artifact writes.

All numerical physical values below are synthetic EXPLICIT_MODEL_ASSUMPTIONs.
LEO-scale names describe a scale only, not sourced Earth/spacecraft truth.
Run: python -B -m examples.v5_j2_enclosure_pilot > <external-path>/pilot.json
"""

from dataclasses import asdict
import json
from time import perf_counter

from ops_sim.v5.frames import CartesianPosition, CartesianState, CartesianVelocity
from ops_sim.v5.ids import ParameterId
from ops_sim.v5.orbit_config import (
    FrameDefinition, FrameKind, GeometryInstant, ReferenceEllipsoid, TTEpoch,
    UniformRotationDefinition,
)
from ops_sim.v5.orbit_j2 import J2CartesianTrajectory, J2RK4SolverConfig
from ops_sim.v5.orbit_j2_enclosure import J2EnclosurePolicy, evaluate_j2_enclosure
from ops_sim.v5.orbit_j2_gravity import J2GravityModel
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import ParameterProvenance, ProvenanceClass, ProvenanceStatus


def parameter(name, value, units):
    return ScalarParameter(value, ParameterProvenance(
        ParameterId(name), ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION, units, (),
        ProvenanceStatus.VERIFIED, rationale='Synthetic Task 06A enclosure pilot input'))


def inputs(circle):
    epoch = TTEpoch(2451545, .125)
    frame = FrameDefinition(FrameKind.MODEL_INERTIAL,
        ReferenceEllipsoid('Synthetic independent shape',
            parameter('orbit.earth.equatorial-radius', 1, 'm'),
            parameter('orbit.earth.flattening', .125, '1')),
        UniformRotationDefinition(epoch,
            parameter('orbit.rotation.initial-phase', .25, 'rad'),
            parameter('orbit.rotation.angular-rate', -.0625, 'rad/s')))
    instant = GeometryInstant(epoch, 128)
    r, v, mu, j2, rg = ((2,0,0),(0,17/8,0),8,11/32,1) if circle else (
        (7000000,100000,200000),(-100,6000,4500),4e14,1/1024,6400000)
    state = CartesianState(CartesianPosition(frame,instant,r),CartesianVelocity(frame,instant,v))
    model = J2GravityModel(parameter('orbit.gravity.gravitational-parameter',mu,'m^3/s^2'),
                           parameter('orbit.gravity.j2',j2,'1'),
                           parameter('orbit.gravity.reference-radius',rg,'m'))
    return J2CartesianTrajectory(state,model)


def main():
    rows=[]
    for circle, span, h in ((True,.5,1/32),(False,-60,10),(False,60,10),
                             (False,300,10),(False,600,10),(False,600,5)):
        trajectory=inputs(circle)
        policy=J2EnclosurePolicy(h,256,.5 if circle else 6000000,50,12)
        solver=J2RK4SolverConfig(h,256)
        instant=GeometryInstant(trajectory.initial_state.position.instant.epoch,128+span)
        start=perf_counter()
        result=evaluate_j2_enclosure(trajectory,instant,solver,policy)
        elapsed=perf_counter()-start
        rows.append(dict(case='exact-J2-circle' if circle else 'inclined-LEO-scale-assumption',
            span_s=span,policy=asdict(policy),solver=asdict(solver),status=result.status,
            reason=result.reason,position_infinity_bound_m=result.position_error_bound_m,
            velocity_infinity_bound_m_per_s=result.velocity_error_bound_m_per_s,
            completed_enclosure_steps=result.enclosure_steps,completed_nominal_steps=result.nominal_steps,
            picard_attempts=result.picard_attempts,wall_s=elapsed,
            endpoint_intervals=result.endpoint_intervals))
    print(json.dumps(rows,indent=2,default=str))


if __name__=='__main__':
    main()
