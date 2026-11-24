"""Short B38 -> forcing -> real nominal EPS/thermal example.

CLI reads two supplied B38 input-only documents; exactly two public entries.
Synthetic fixtures below test adapters only and never prove orbit accuracy.
"""
from dataclasses import fields, MISSING, replace
from decimal import Decimal
from fractions import Fraction as Q
from hashlib import sha256
from pathlib import Path
import argparse
import json

from ops_sim.v5 import orbit_sun_zonotope_local_v2 as light
from ops_sim.v5 import orbit_sun_zonotope_local_v2_document as ld
from ops_sim.v5 import orbit_j2_zonotope_segments as segments
from ops_sim.v5 import orbit_sun_intervals as geometry
from ops_sim.v5 import experiment_codec
from ops_sim.v5.environment_forcing import (NodeForcing, ForcingProfileEntry,
    EnvironmentForcingRequest, adapt_environment_forcing)
from ops_sim.v5.environment_physics import compute_environment_transition
from ops_sim.v5.configuration import BatteryConfig, SolarArrayConfig, EPSConfig
from ops_sim.v5.thermal_config import ThermalNodeConfig, ThermalNetworkConfig
from ops_sim.v5.ids import ParameterId, SubsystemConfigurationId, ThermalNodeId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import ParameterProvenance, ProvenanceClass, ProvenanceStatus
from ops_sim.v5.state import BatteryState, ThermalState, ThermalNodeState
from ops_sim.v5.power_loads import PowerLoadBreakdown
from examples.m2_zonotope_local_v2_illumination_demo import scientific_bytes


def parameter(name, units, value):
    return ScalarParameter(value, ParameterProvenance(ParameterId(name),
        ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION, units, (), ProvenanceStatus.TO_RESEARCH,
        rationale="Synthetic B39 demonstration; not spacecraft calibration."))


def physical_case(*, efficiency=1.0):
    eps = EPSConfig(SubsystemConfigurationId("b39-eps"),
        BatteryConfig(SubsystemConfigurationId("b39-battery"),
            parameter("eps.battery.nominal-energy", "Wh", 1000.0),
            parameter("eps.battery.charge-efficiency", "1", efficiency),
            parameter("eps.battery.discharge-efficiency", "1", efficiency),
            parameter("eps.battery.max-charge-input-power", "W", 1000.0),
            parameter("eps.battery.max-discharge-output-power", "W", 1000.0)),
        SolarArrayConfig(SubsystemConfigurationId("b39-array"),
                         parameter("eps.solar-array.nominal-generation", "W", 100.0)))
    nodes = []
    for name in ("bus", "battery", "payload"):
        p = "thermal.node."+name+"."
        nodes.append(ThermalNodeConfig(ThermalNodeId(name),
            parameter(p+"heat-capacity", "J/K", 1000.0), parameter(p+"emissivity", "1", 0.0),
            parameter(p+"radiating-area", "m^2", 1.0),
            parameter(p+"operating-min-temperature", "K", 270.0),
            parameter(p+"operating-max-temperature", "K", 320.0),
            parameter(p+"survival-min-temperature", "K", 250.0),
            parameter(p+"survival-max-temperature", "K", 340.0)))
    network = ThermalNetworkConfig(tuple(nodes), (), ThermalNodeId("bus"),
                                   ThermalNodeId("battery"), ThermalNodeId("payload"))
    state = ThermalState(tuple(ThermalNodeState(n.node_id, 300.0) for n in nodes))
    return BatteryState(100.0), eps, state, network


def profile_entry(a, b, *, load=20.0, heat=2.0, solar=10.0, incidence=0.0):
    return ForcingProfileEntry(a, b, incidence, PowerLoadBreakdown(load, 0., 0., 0., 0., 0., 0.),
        tuple(NodeForcing(ThermalNodeId(n), 300.0, heat, solar, 1.0, 3.0)
              for n in ("bus", "battery", "payload")),
        "Effective sinks exclude the explicit absorbed sources; internal heat excludes EPS losses.")


def forcing_request(q, *, profile=None, start=None, end=None):
    a = Q(q.segment.trajectory.initial_state.position.instant.elapsed_seconds)
    b = Q(q.segment.end.elapsed_seconds)
    return EnvironmentForcingRequest(q, a if start is None else start, b if end is None else end,
        tuple(ThermalNodeId(n) for n in ("bus", "battery", "payload")),
        (profile_entry(a, b),) if profile is None else profile)


def trusted_synthetic_result(q, assessments=("ILLUMINATED",)):
    """Deliberately fabricated typed test partition, NOT an orbital certificate.

    No B38 result constructor/propagation is called. These fixtures exercise
    trust-boundary structure and nominal physics, not correctness of geometry.
    """
    r = object.__new__(light.ZonotopeLocalIlluminationResultV2)
    for f in fields(r):
        object.__setattr__(r, f.name, q if f.name == "request" else f.default)
    a = Q(q.segment.trajectory.initial_state.position.instant.elapsed_seconds)
    b = Q(q.segment.end.elapsed_seconds)
    authority = sha256(experiment_codec.json_text(experiment_codec.canonical_content(ld._input_map(q))).encode()).hexdigest()
    boundaries, steps, records, pieces = [], [], [], []
    points = [a+(b-a)*Q(i, len(assessments)) for i in range(len(assessments)+1)]
    zero = Decimal(0)
    for i, t in enumerate(points):
        diagnostic = segments.J2ZonotopeSegmentDiagnostic((zero,)*6, (), (), t)
        boundaries.append(light.ZonotopeBoundary(i, None if i == 0 else i-1,
            diagnostic, q.segment.policy.scale_exponents, authority))
    for i, (left, right, assessment) in enumerate(zip(points, points[1:], assessments)):
        tube = segments.J2ZonotopeSegmentCell(left, right, i, left, right,
            ((zero, zero),)*3, ((zero, zero),)*3)
        steps.append(light.LocalStep(i, i, i+1, 0, 0, False, tube))
        reason = "TRUSTED_SYNTHETIC_FIXTURE_NOT_ORBIT_PROOF"
        cell = geometry.IntervalIlluminationCell(left, right, i, 0, (Q(0), Q(1)),
            ((Q(0), Q(0)),)*3, ((Q(0), Q(0)),)*3, ((Q(0), Q(0)),)*3,
            ((Q(0), Q(0)),)*3, *((Q(0), Q(0)),)*5, assessment, reason)
        records.append(light.LocalGeometry(i, i, 0, 0, authority, cell))
        pieces.append(light.LocalPiece(left, right, i, assessment, reason))
    trial = light.LocalTrial(0, 0, 0, a, b, (b-a)/len(assessments), len(steps), len(records),
                             "classified", tuple(range(len(steps))), tuple(range(len(records))))
    updates = dict(status="classified", reason="TRUSTED_SYNTHETIC_FIXTURE", coverage_complete=True,
        pieces=tuple(pieces), windows=light._merge(tuple(pieces)), initial_pieces=tuple(pieces),
        boundaries=tuple(boundaries), steps=tuple(steps), geometry_records=tuple(records),
        trials=(trial,), authority_digest=authority)
    for n, v in updates.items():
        object.__setattr__(r, n, v)
    return r


def demonstrate(real_light, real_dark):
    case = physical_case(efficiency=0.8)
    outputs = {}
    for name, result in (("real_light", real_light), ("real_eclipse", real_dark)):
        outputs[name] = compute_environment_transition(result, forcing_request(result.request), *case)
        assert outputs[name].status == "complete", outputs[name].reason
    q = real_light.request
    a = Q(q.segment.trajectory.initial_state.position.instant.elapsed_seconds)
    b = Q(q.segment.end.elapsed_seconds)
    mid = a+(b-a)/3
    mixed = trusted_synthetic_result(q, ("ILLUMINATED", "OCCULTED"))
    f = forcing_request(q, profile=(profile_entry(a, mid), profile_entry(mid, b, load=30.0)))
    outputs["synthetic_mixed_inner_breakpoint"] = compute_environment_transition(mixed, f, *case)
    unresolved = trusted_synthetic_result(q, ("UNRESOLVED",))
    outputs["synthetic_unresolved"] = compute_environment_transition(unresolved, forcing_request(q), *case)
    assert outputs["synthetic_unresolved"].final_proposal is None
    bad = forcing_request(q, profile=(profile_entry(a, mid),
        profile_entry(mid, b, heat=1.7e308, solar=1.7e308)))
    outputs["late_physical_failure"] = compute_environment_transition(real_light, bad, *case)
    assert outputs["late_physical_failure"].status == "physical_failure"
    assert outputs["late_physical_failure"].final_proposal is None and outputs["late_physical_failure"].trajectory is None
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--light-input", type=Path, required=True)
    parser.add_argument("--dark-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results, entries = [], []
    args.output.mkdir(exist_ok=False)
    for name, path in (("light", args.light_input), ("dark", args.dark_input)):
        q = ld.load_zonotope_local_request_v2(path)
        span = q.segment.end.elapsed_seconds-q.segment.trajectory.initial_state.position.instant.elapsed_seconds
        if not 0 < span <= 30 or q.policy.max_initial_steps+q.policy.max_refinement_steps > 128 or q.policy.max_passes > 3:
            raise ValueError("short B38 scope exceeded")
        entries.append(dict(name=name, api_entries=1, completed=False, span_seconds=span))
        (args.output/"entry-inventory.json").write_bytes((json.dumps(entries)+"\n").encode())
        r = light.evaluate_zonotope_local_illumination_v2(q)
        (args.output/(name+".b38.scientific.json")).write_bytes(scientific_bytes(r))
        if not r.coverage_complete:
            raise ValueError("real short upstream failed: "+str(r.reason))
        assert all(p.assessment == ("ILLUMINATED" if name == "light" else "OCCULTED") for p in r.pieces)
        entries[-1]["completed"] = True
        (args.output/"entry-inventory.json").write_bytes((json.dumps(entries)+"\n").encode())
        results.append(r)
    outputs = demonstrate(*results)
    for name, value in outputs.items():
        (args.output/(name+".physical.scientific.json")).write_bytes(scientific_bytes(value))
    (args.output/"PASS.json").write_bytes((json.dumps(dict(overall="PASS", public_entries=2,
        result_hashes={n:sha256(scientific_bytes(v)).hexdigest() for n, v in outputs.items()}))+"\n").encode())


if __name__ == "__main__":
    main()
