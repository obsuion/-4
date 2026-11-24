"""Task 03B synthetic protection/standby/restart trace; no calibration claim."""

import argparse
from dataclasses import replace
from decimal import Decimal, localcontext
import json
from math import ulp
from pathlib import Path

from examples import v5_coupled_downlink_demo as physical
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.continuation import ImagingAction, CoupledDownlinkAction
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.ids import AcquisitionDataRecordId, ThermalLinkId
from ops_sim.v5.imaging_resources import AcquisitionEPSIntervalEnvironment
from ops_sim.v5.operational_continuation import (
    OperationalProgram, OperationalMemory, OperationalState, advance_operational_continuation)
from ops_sim.v5.operational_protection import (
    ProtectionPolicy, StandbyInputs, StandbyAction, ProtectedRequest, execute_protected_request)
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.thermal_config import ThermalLinkConfig
from ops_sim.v5.thermal_routing import ElectricalLoadComponent


ROOT = Path(__file__).resolve().parents[1]


def policy(context):
    n = context.inputs.spacecraft_configuration.thermal.network
    return ProtectionPolicy((n.bus_node_id, n.battery_node_id, n.payload_node_id),
        (n.bus_node_id, n.battery_node_id), (n.bus_node_id, n.battery_node_id), n.bus_node_id,
        tuple(ElectricalLoadComponent), "all-declared-standby-loads", "next-admissible-sampled-boundary",
        "Synthetic reversible start/end admission; perfect sampled onboard observation; all standby loads essential; no reserve rule.",
        "Synthetic shared bus temperature represents the transmitter; explicit assumption, not inferred from waste-heat routing.")


def standby(context, *, sunlit=True, loads=None):
    forcing = physical.physical_inputs(context, sunlit=sunlit)
    return StandbyInputs(loads if loads is not None else PowerLoadBreakdown(12.0, 3.0, 5.0, 0.0, 0.0, 0.0, 0.0),
        forcing.sunlit, forcing.incidence_angle_deg, forcing.routing_config, forcing.thermal_inputs,
        forcing.external_heat_sources, forcing.solar_degradation_forcing,
        "Synthetic explicitly declared essential standby watts and interval forcing; payload/transmitter/propulsion off.")


def build_demo_state():
    old = physical.build_demo_state()
    context = old.context
    cfg = context.inputs.spacecraft_configuration
    n = cfg.thermal.network
    # Analytically simple conductive cooling: payload C=23 J/K, link G=1 W/K,
    # dt=23 s; Euler endpoint moves to bus temperature plus payload heat/G.
    nodes = tuple(replace(node, heat_capacity_j_per_k=physical.parameter_value(node.heat_capacity_j_per_k, 23.0))
        if node.node_id == n.payload_node_id else node for node in n.nodes)
    link = ThermalLinkConfig(ThermalLinkId("task03b-synthetic-cooling"), n.bus_node_id, n.payload_node_id,
        physical.storage._parameter("thermal.link.task03b-synthetic-cooling.conductance", "W/K", 1.0))
    payload = cfg.payload.optical_acquisition
    context.inputs = replace(context.inputs, spacecraft_configuration=replace(cfg,
        thermal=replace(cfg.thermal, network=replace(n, nodes=nodes, links=(link,))),
        payload=replace(cfg.payload, optical_acquisition=replace(payload,
            acquisition_power_w=physical.parameter_value(payload.acquisition_power_w, 20.0)))))
    for node in context.spacecraft_state.thermal.node_states:
        if node.node_id == n.payload_node_id:
            node.temperature_k = 400.0
    wait = standby(context)
    # Zero payload external heat for the exact 400 -> 300 K cooling example.
    wait = replace(wait, external_heat_sources=replace(wait.external_heat_sources, node_sources=tuple(
        replace(s, absorbed_albedo_w=0.0) for s in wait.external_heat_sources.node_sources)))
    requests = []

    def image(name, i, *, predicted_hot=False):
        action = old.program.actions[0]
        execution = physical.storage._scheduled_execution(100 + 23*i, i+1, "task03b")
        heat = wait.external_heat_sources
        if predicted_hot:
            heat = replace(heat, node_sources=tuple(replace(s, absorbed_solar_w=200.0)
                if s.node_id == n.payload_node_id else s for s in heat.node_sources))
        action = replace(action, action_id="image-" + name, execution=execution,
            record_id=AcquisitionDataRecordId(name),
            environment=AcquisitionEPSIntervalEnvironment(True, 0.0, PowerLoadBreakdown(12.0, 3.0, 5.0, 0.0, 0.0, 0.0, 0.0)),
            external_heat_sources=heat)
        return ProtectedRequest(action, wait)

    def downlink(name, i, label):
        c = physical.contact(context, label)
        c = replace(c, start_time_seconds=100+23*i, end_time_seconds=123+23*i)
        forcing = replace(physical.physical_inputs(context), baseline_loads=PowerLoadBreakdown(12.0, 3.0, 5.0, 0.0, 0.0, 0.0, 0.0),
                          external_heat_sources=wait.external_heat_sources)
        return ProtectedRequest(CoupledDownlinkAction(label, c, AcquisitionDataRecordId(name), forcing), wait)

    requests.extend((image("hot-denied", 0), downlink("hot-denied", 1, "missing-hot"),
        image("acquired", 2), downlink("acquired", 3, "partial"), image("predicted-denied", 4, predicted_hot=True),
        downlink("predicted-denied", 5, "missing-predicted"), ProtectedRequest(StandbyAction("explicit-standby"), wait),
        downlink("acquired", 7, "complete")))
    program = OperationalProgram(3, CheckpointState.from_context(context), old.memory.previous_execution,
        policy(context), tuple(requests), (
        "All Task 03B coefficients and perfect onboard sampling are synthetic assumptions, not calibrated FDIR.",
        "Existing 270..320 K operating and 250..340 K survival limits; equality admitted.",
        "Shared bus/transmitter node; explicit standby demand and priority; recovery next admissible boundary.",
        "Simple Euler conductive cooling reference; start/end prediction does not certify the interior trajectory.",
        "Different mission/standby thermal forcing is explicitly declared; no inferred attitude-dependent environment.",
        "Fixed requests with physical fallback; no ground scheduling, reserve, damage, beacon or reliability model.",
    ))
    return OperationalState(context, program, OperationalMemory((), old.memory.previous_execution))


def numerical_reference():
    context = physical.reference_context()
    inputs = standby(context, sunlit=False)
    result = execute_protected_request(context, physical.storage._previous_execution(),
        ProtectedRequest(StandbyAction("reference-standby"), inputs), policy=policy(context))
    step = result.step_result
    with localcontext() as c:
        c.prec = 50
        inv = Decimal(1)/300 - Decimal(1)/Decimal("300.03")
        calendar = Decimal("0.000001")*36*(Decimal(12000)/Decimal("8.31446261815324")*inv).exp()
        cycling = Decimal("0.002")*Decimal("0.25")/100*(Decimal(6000)/Decimal("8.31446261815324")*inv).exp()
        retention = Decimal("0.9") - calendar - cycling
    rows = []
    def check(name, units, expected, actual):
        expected = float(expected)
        bound = 64*ulp(abs(expected) if expected else 1.0)
        assert abs(actual-expected) <= bound, (name, actual, expected, bound)
        rows.append(dict(quantity=name, units=units, expected=expected, actual=actual, absolute_tolerance=bound))
    # Literal independent balances: 20 W * .01 h / .8 = .25 Wh;
    # conversion loss .05 Wh -> 5 W; C=3600 J/K, dt=36 s.
    check("served_essential", "W", 20, step.eps_result.battery.served_load_w)
    check("essential_unmet", "W", 0, result.outcome.availability.essential_unmet_w)
    check("end_energy", "Wh", "79.75", context.spacecraft_state.battery.energy_wh)
    check("conversion_loss", "Wh", ".05", step.eps_result.battery.conversion_loss_wh)
    check("throughput", "Wh", ".25", step.battery_degradation_result.throughput_increment_wh)
    heat = {x.node_id.value:x for x in step.thermal_coupling_result.node_heat_ledgers}
    check("bus_internal_heat", "W", 10, heat["bus"].internal_dissipation_w)
    check("battery_conversion_heat", "W", 5, heat["battery"].battery_conversion_heat_w)
    for node in context.spacecraft_state.thermal.node_states:
        check(node.node_id.value+"_temperature", "K", {"bus":"300.12", "battery":"300.06", "payload":"300.03"}[node.node_id.value], node.temperature_k)
    check("calendar_damage", "1", calendar, step.battery_degradation_result.calendar_damage)
    check("cycling_damage", "1", cycling, step.battery_degradation_result.cycling_damage)
    check("retention", "1", retention, context.spacecraft_state.degradation.battery.usable_capacity_retention)
    return {"assumptions":"Synthetic rational balances and 50-digit Decimal exponential reference; 64 ULP arithmetic bound, no admission slack.",
            "rows":rows, "clock_seconds":context.simulation_time_seconds, "completed_steps":context.diagnostics.completed_steps}


def trace_row(before, after):
    outcome = after.memory.outcomes[-1]
    # Reproduce transient evidence on an isolated copy for the external trace;
    # neither continuation state nor its clock is advanced a second time.
    isolated = CheckpointState.from_context(before.context).restore(before.context.inputs)
    selected = execute_protected_request(isolated, before.memory.previous_execution,
        before.program.requests[len(before.memory.outcomes)], policy=before.program.policy)
    assert CheckpointState.from_context(isolated) == CheckpointState.from_context(after.context)
    eps = selected.step_result.eps_result.battery
    return {"time_seconds":outcome.start_time_seconds, "end_seconds":outcome.end_time_seconds,
        "request":outcome.request_id, "requested":outcome.availability.requested_kind.value,
        "available":outcome.availability.available, "reasons":[r.value for r in outcome.availability.reasons],
        "actual":outcome.actual_kind.value, "mode":outcome.operational_mode.value, "fdir":outcome.fdir_state.value,
        "start_temperatures_k":{n.node_id.value:n.temperature_k for n in before.context.spacecraft_state.thermal.node_states},
        "end_temperatures_k":{n.node_id.value:n.temperature_k for n in after.context.spacecraft_state.thermal.node_states},
        "essential_unmet_w":outcome.availability.essential_unmet_w,
        "actual_generation_w":eps.generation_w, "actual_demand_w":eps.load_w,
        "actual_served_w":eps.served_load_w, "actual_unmet_w":eps.unmet_load_w,
        "start_energy_wh":before.context.spacecraft_state.battery.energy_wh,
        "end_energy_wh":after.context.spacecraft_state.battery.energy_wh,
        "survival_start":[n.value for n in outcome.survival_start_node_ids],
        "survival_end":[n.value for n in outcome.survival_end_node_ids],
        "critical_since_seconds":outcome.critical_energy_since_seconds, "recovered":outcome.recovered,
        "onboard_records":[r.record_id.value for r in after.context.spacecraft_state.data_storage.stored_records],
        "partial_bits":sum(p.transmitted_equivalent_bits for p in after.context.ground_data_delivery_state.partial_transfers),
        "delivered_bits":sum(d.record.stored_equivalent_bits for d in after.context.ground_data_delivery_state.completed_deliveries)}


def summarize(state):
    return {"input_digest":experiment_input_digest(state.context.inputs, state.program),
        "checkpoint":CheckpointState.from_context(state.context).to_dict(), "memory":canonical_content(state.memory),
        "actual_actions":[o.actual_kind.value for o in state.memory.outcomes],
        "metrics":{"requests":len(state.memory.outcomes), "denials":sum(not o.availability.available for o in state.memory.outcomes),
                   "delivered_bits":sum(d.record.stored_equivalent_bits for d in state.context.ground_data_delivery_state.completed_deliveries)}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--bundle-output", type=Path)
    parser.add_argument("--trace-output", type=Path)
    parser.add_argument("--numerical", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args=parser.parse_args(argv)
    if args.numerical:
        result=numerical_reference()
    else:
        state=build_demo_state() if args.resume is None else ExperimentBundle.from_json(args.resume.read_text(encoding="utf-8")).restore(repository_root=ROOT)
        stop=len(state.program.requests) if args.stop_after is None else args.stop_after
        if not len(state.memory.outcomes) <= stop <= len(state.program.requests):
            parser.error("stop-after outside remaining request prefix")
        trace=[]
        while len(state.memory.outcomes)<stop:
            before=state
            state=advance_operational_continuation(state)
            trace.append(trace_row(before,state))
        if args.bundle_output:
            args.bundle_output.write_text(create_bundle(state,repository_root=ROOT).to_json(),encoding="utf-8")
        if args.trace_output:
            args.trace_output.write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding="utf-8")
        result=summarize(state)
    args.output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False,indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
