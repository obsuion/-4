"""Task 04A synthetic references and version-4 fresh-process restart demo.

All coefficients are explicit verification assumptions, not spacecraft values.
Run as a module; write output/bundles outside the repository.
"""

import argparse
from dataclasses import replace
from decimal import Decimal, localcontext
import json
from pathlib import Path

from examples import v5_operational_protection_demo as old
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.continuation import ImagingAction, CoupledDownlinkAction
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content, content_digest
from ops_sim.v5.ids import AcquisitionDataRecordId, ThermalLinkId
from ops_sim.v5.integration_time import IntegrationPolicy
from ops_sim.v5.operational_protection import ProtectedRequest, StandbyAction
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.substepped_continuation import (
    SubsteppedProgram, SubsteppedMemory, SubsteppedState, advance_substepped_continuation)
from ops_sim.v5.substepped_execution import TimedRequest, execute_substepped_request
from ops_sim.v5.thermal_config import ThermalLinkConfig


ROOT = Path(__file__).resolve().parents[1]


def build_demo_state(level=2):
    seed = old.physical.build_demo_state()
    c = seed.context
    cfg = c.inputs.spacecraft_configuration
    c.inputs = replace(c.inputs, spacecraft_configuration=replace(cfg,
        communications=replace(cfg.communications, nominal_downlink_data_rate_bps=
            old.physical.parameter_value(cfg.communications.nominal_downlink_data_rate_bps, 400.0))))
    wait = old.standby(c, sunlit=False)
    first = seed.program.actions[0]
    first = replace(first, action_id="image", record_id=AcquisitionDataRecordId("task04a-product"),
                    execution=old.physical.storage._scheduled_execution(100, 1, "task04a"))
    hot = replace(first, action_id="hot-denied", record_id=AcquisitionDataRecordId("task04a-denied"),
        execution=old.physical.storage._scheduled_execution(169, 4, "task04a"),
        external_heat_sources=replace(first.external_heat_sources, node_sources=tuple(
            replace(s, absorbed_solar_w=8000.0) if s.node_id.value == "payload" else s
            for s in first.external_heat_sources.node_sources)))

    def downlink(start, name):
        contact = replace(old.physical.contact(c, name), start_time_seconds=start, end_time_seconds=start+23)
        return CoupledDownlinkAction(name, contact, first.record_id, old.physical.physical_inputs(c))

    actions = (first, downlink(123, "partial"), StandbyAction("standby"), hot, downlink(192, "complete"))
    requests = tuple(TimedRequest(100+23*i, 123+23*i, ProtectedRequest(action, wait))
                     for i, action in enumerate(actions))
    program = SubsteppedProgram(4, CheckpointState.from_context(c), seed.memory.previous_execution,
        old.policy(c), IntegrationPolicy(level), requests, (
        "Synthetic fixed timeline and interval-constant forcing; no geometry/controller decisions inside actions.",
        "23 second exposure/contact/standby independent of the dyadic integration policy.",
        "One selected record; transmitter remains on through the whole contact, including spare capacity.",
        "Explicit external solar loss distributed uniformly in time; Euler heat, midpoint-temperature ageing.",
        "Sampled prediction only; no continuous safety, general numerical qualification, damage or calibration.",
    ))
    return SubsteppedState(c, program, SubsteppedMemory((), seed.memory.previous_execution))


def physical_scenario_digest(state):
    """Comparison diagnostic only. Experiment identity ALWAYS includes integration."""
    p = state.program
    return content_digest("task04a-physical-scenario-comparison-v1", (state.context.inputs,
        p.initial_checkpoint, p.initial_previous_execution, p.policy, p.requests, p.assumptions))


def thermal_case(cooling=False):
    """Two active nodes; isolated third battery node cannot influence the reference."""
    c = old.physical.reference_context()
    cfg = c.inputs.spacecraft_configuration
    n = cfg.thermal.network
    values = {"bus": 3600.0 if cooling else 10.0, "payload": 23.0 if cooling else 10.0}
    nodes = tuple(replace(node, heat_capacity_j_per_k=old.physical.parameter_value(
        node.heat_capacity_j_per_k, values.get(node.node_id.value, 3600.0))) for node in n.nodes)
    link = ThermalLinkConfig(ThermalLinkId("task04a-reference-link"), n.bus_node_id, n.payload_node_id,
        old.physical.storage._parameter("thermal.link.task04a-reference-link.conductance", "W/K", 1.0))
    optical = cfg.payload.optical_acquisition
    c.inputs = replace(c.inputs, spacecraft_configuration=replace(cfg,
        thermal=replace(cfg.thermal, network=replace(n, nodes=nodes, links=(link,))),
        payload=replace(cfg.payload, optical_acquisition=replace(optical,
            acquisition_power_w=old.physical.parameter_value(optical.acquisition_power_w, 20.0)))))
    for node in c.spacecraft_state.thermal.node_states:
        node.temperature_k = {"bus": 300.0 if cooling else 310.0,
                              "payload": 400.0 if cooling else 290.0, "battery": 300.0}[node.node_id.value]
    wait = old.standby(c, sunlit=False, loads=PowerLoadBreakdown(12.0 if cooling else 1.0, 0., 0., 0., 0., 0., 0.))
    wait = replace(wait, solar_degradation_forcing=None,
        routing_config=replace(wait.routing_config, routes=tuple(replace(route,
            retained_heat_fraction=replace(route.retained_heat_fraction, value=1.0 if cooling else 0.0))
            for route in wait.routing_config.routes)),
        external_heat_sources=replace(wait.external_heat_sources, node_sources=tuple(replace(source,
            absorbed_solar_w=0., absorbed_albedo_w=0., absorbed_earth_ir_w=0.)
            for source in wait.external_heat_sources.node_sources)))
    return c, wait


def analytic_two_node(cb, cp, tb, tp, qb, qp, duration):
    """Independent 60-digit closed solution from weighted energy and T difference."""
    with localcontext() as ctx:
        ctx.prec = 60
        cb, cp, tb, tp, qb, qp, duration = map(lambda x: Decimal(str(x)), (cb,cp,tb,tp,qb,qp,duration))
        rate = 1/cb + 1/cp  # declared G = 1 W/K
        steady_difference = (qp/cp - qb/cb)/rate
        difference = steady_difference + (tp-tb-steady_difference)*(-rate*duration).exp()
        mean = (cb*tb + cp*tp + (qb+qp)*duration)/(cb+cp)
        return float(mean-cp/(cb+cp)*difference), float(mean+cb/(cb+cp)*difference)


def numerical_references():
    output = {}
    for cooling, name in ((False, "original_two_node"), (True, "cooling_recovery")):
        duration = 23 if cooling else 12
        reference = analytic_two_node(3600 if cooling else 10, 23 if cooling else 10,
            300 if cooling else 310, 400 if cooling else 290, 12 if cooling else 0, 0, duration)
        rows = []
        for level in (0, 1, 2, 4, 6, 8, 10, 12):
            c, wait = thermal_case(cooling)
            before_inputs = canonical_content(c.inputs)
            result = execute_substepped_request(c, old.physical.storage._previous_execution(),
                TimedRequest(100, 100+duration, ProtectedRequest(StandbyAction("thermal-reference"), wait)),
                policy=old.policy(c), integration=IntegrationPolicy(level))
            temperatures = {n.node_id.value: n.temperature_k for n in c.spacecraft_state.thermal.node_states}
            actual = temperatures["bus"], temperatures["payload"]
            assert canonical_content(c.inputs) == before_inputs
            assert c.simulation_time_seconds == 100+duration and c.diagnostics.completed_steps == 1
            rows.append(dict(level=level, substep_seconds=duration/(2**level), bus_k=actual[0], payload_k=actual[1],
                max_error_k=max(abs(x-y) for x,y in zip(actual,reference)),
                subsequent_payload_start_within_320k=actual[1] <= 320,
                physical_duration_seconds=duration, completed_steps=c.diagnostics.completed_steps,
                numerical_substeps=result.outcome.accounting.numerical_substeps))
        output[name] = {"reference_k":reference, "method":"independent closed linear ODE, Decimal 60 digits", "rows":rows}
    return output


def summarize(state):
    return {"input_digest":experiment_input_digest(state.context.inputs, state.program),
        "physical_scenario_digest":physical_scenario_digest(state),
        "checkpoint":CheckpointState.from_context(state.context).to_dict(),
        "memory":canonical_content(state.memory),
        "metrics":{"requests":len(state.memory.outcomes), "numerical_substeps":state.memory.numerical_substeps,
            "evaluated_eps_substeps":state.memory.evaluated_eps_substeps,
            "evaluated_thermal_substeps":state.memory.evaluated_thermal_substeps,
            "denials":sum(not o.availability.available for o in state.memory.outcomes),
            "delivered_bits":sum(d.record.stored_equivalent_bits for d in state.context.ground_data_delivery_state.completed_deliveries)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", type=int, default=2)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--bundle-output", type=Path)
    parser.add_argument("--numerical", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.numerical:
        result = numerical_references()
    else:
        state = build_demo_state(args.level) if args.resume is None else ExperimentBundle.from_json(
            args.resume.read_text(encoding="utf-8")).restore(repository_root=ROOT)
        stop = len(state.program.requests) if args.stop_after is None else args.stop_after
        if not len(state.memory.outcomes) <= stop <= len(state.program.requests):
            parser.error("stop-after outside remaining action boundaries")
        while len(state.memory.outcomes) < stop:
            state = advance_substepped_continuation(state)
        if args.bundle_output:
            args.bundle_output.write_text(create_bundle(state, repository_root=ROOT).to_json(), encoding="utf-8")
        result = summarize(state)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
