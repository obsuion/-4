"""Task 03A synthetic numerical and fresh-process restart demonstration.

All coefficients are explicit test assumptions, not calibrated KazEOSat values.
Run as a module. Output files must be outside the repository.
"""

import argparse
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from math import ulp
from pathlib import Path

from examples import v5_experiment_bundle_demo as legacy
from examples import v54_integrated_storage_demo as storage
from ops_sim.v5.communications import ServiceableGroundContact
from ops_sim.v5.continuation import (
    ContinuationState, CoupledDownlinkAction, DownlinkAction, advance_continuation,
)
from ops_sim.v5.coupled_downlink import CoupledDownlinkInputs, DownlinkTransmitterConfig
from ops_sim.v5.degradation import SolarDegradationForcingInput
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.eps_system import EPSIntervalInputs
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle
from ops_sim.v5.ids import AcquisitionDataRecordId, GroundContactId, GroundStationId, ImagingRequestId, ObservationOpportunityId
from ops_sim.v5.onboard_data import OnboardAcquisitionDataRecord
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload import OpticalAcquisitionChannelSelection
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.state import DataStorageState
from ops_sim.v5.thermal_routing import (
    ElectricalLoadComponent, ServedComponentPower, ServedPowerLedger,
    compose_routed_internal_heat_sources, compute_routed_internal_heat,
)


ROOT = Path(__file__).resolve().parents[1]


def parameter_value(parameter, value):
    return ScalarParameter(value, replace(
        parameter.provenance,
        rationale="Synthetic Task 03A verification coefficient; not spacecraft calibration.",
    ))


def configure_physics(context):
    """100 Wh battery, nonzero ageing, isolated nonradiating C=3600 J/K nodes."""
    cfg = context.inputs.spacecraft_configuration
    battery = replace(cfg.eps.battery, **{
        key: parameter_value(getattr(cfg.eps.battery, key), value)
        for key, value in {"nominal_energy_wh": 100.0, "charge_efficiency": 0.9,
                           "discharge_efficiency": 0.8, "max_charge_input_power_w": 100.0,
                           "max_discharge_output_power_w": 200.0}.items()
    })
    solar = replace(cfg.eps.solar_array, nominal_generation_w=parameter_value(cfg.eps.solar_array.nominal_generation_w, 25.0))
    model = cfg.degradation.battery_ageing_model
    model = replace(model, **{
        key: parameter_value(getattr(model, key), value) for key, value in {
            "reference_temperature_k": 300.0,
            "calendar_damage_rate_per_second_at_reference": 1e-6,
            "calendar_activation_energy_j_per_mol": 12000.0,
            "cycling_damage_per_normalized_energy_throughput_at_reference": 0.002,
            "cycling_activation_energy_j_per_mol": 6000.0,
        }.items()
    })
    network = replace(cfg.thermal.network, links=(), nodes=tuple(
        replace(node, heat_capacity_j_per_k=parameter_value(node.heat_capacity_j_per_k, 3600.0),
                emissivity=parameter_value(node.emissivity, 0.0))
        for node in cfg.thermal.network.nodes
    ))
    context.inputs = replace(context.inputs, spacecraft_configuration=replace(
        cfg, eps=replace(cfg.eps, battery=battery, solar_array=solar),
        thermal=replace(cfg.thermal, network=network),
        degradation=replace(cfg.degradation, battery_ageing_model=model),
    ))
    context.spacecraft_state.battery.energy_wh = 80.0
    context.spacecraft_state.degradation.battery.usable_capacity_retention = 0.9
    context.spacecraft_state.degradation.solar.generation_retention = 0.8
    for node in context.spacecraft_state.thermal.node_states:
        node.temperature_k = 300.0
    return context


def physical_inputs(context, *, sunlit=True):
    external = storage._external_heat_sources(context)
    external = replace(external, node_sources=tuple(
        replace(source, absorbed_solar_w=2.0 if source.node_id.value == "bus" else 0.0,
                absorbed_earth_ir_w=1.0 if source.node_id.value == "battery" else 0.0,
                absorbed_albedo_w=3.0 if source.node_id.value == "payload" else 0.0)
        for source in external.node_sources
    ))
    power = storage._parameter("communications.transmitter-electrical-power", "W", 36.0)
    power = parameter_value(power, 36.0)
    return CoupledDownlinkInputs(
        DownlinkTransmitterConfig(power), PowerLoadBreakdown(12.0, 3.0, 5.0, 4.0, 0.0, 0.0, 0.0),
        sunlit, 0.0, storage._routing_config(), storage._thermal_inputs(context),
        external, SolarDegradationForcingInput(0.00001),
    )


def contact(context, name="task03a-contact"):
    start = context.simulation_time_seconds
    return ServiceableGroundContact(GroundContactId(name), GroundStationId("synthetic-station"),
                                    start, start + context.inputs.numerical_config.timestep_seconds)


def record(name="reference-record", bits=12000.0):
    return OnboardAcquisitionDataRecord(
        AcquisitionDataRecordId(name), ImagingRequestId(name + "-request"),
        ObservationOpportunityId(name + "-opportunity"), 1, 10,
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL, bits, bits,
    )


def reference_context():
    context = configure_physics(legacy.build_demo_state().context)
    cfg = context.inputs.spacecraft_configuration
    context.inputs = replace(context.inputs,
        numerical_config=replace(context.inputs.numerical_config, timestep_seconds=36, checkpoint_interval_seconds=36),
        spacecraft_configuration=replace(cfg, communications=replace(cfg.communications,
            nominal_downlink_data_rate_bps=parameter_value(cfg.communications.nominal_downlink_data_rate_bps, 250.0))),
    )
    context.spacecraft_state.data_storage = DataStorageState((record(),))
    return context


def build_demo_state():
    original = legacy.build_demo_state()
    context = configure_physics(original.context)
    actions = []
    for index, action in enumerate(original.program.actions):
        forcing = physical_inputs(context, sunlit=index % 2 == 1)
        if type(action) is DownlinkAction:
            action = CoupledDownlinkAction(action.action_id, action.contact, action.record_id, forcing)
        else:
            action = replace(action, routing_config=forcing.routing_config,
                             thermal_inputs=forcing.thermal_inputs,
                             external_heat_sources=forcing.external_heat_sources,
                             solar_degradation_forcing=forcing.solar_degradation_forcing)
        actions.append(action)
    program = replace(original.program, version=2, actions=tuple(actions), assumptions=(
        "Synthetic Task 03A coefficients; no calibrated KazEOSat claim.",
        "Transmitter energized for every full coupled contact, including unused capacity.",
        "Explicit solar/external heat forcing and nonzero Arrhenius/calendar/cycling ageing.",
        "Nonradiating isolated thermal nodes for the analytic example; not a stability proof for general networks.",
        "Declared serviceable contacts; fixed script, no mission controller or autonomous retries.",
    ))
    return ContinuationState(context, program, original.memory)


def numerical_reference():
    """Independent rational balances and Decimal Arrhenius reference."""
    context = reference_context()
    attempt = SimulationEngine().step_coupled_downlink(context, contact(context),
        record_id=record().record_id, physical_inputs=physical_inputs(context))
    eps, step = attempt.eps_result.battery, attempt.step_result
    ageing = step.battery_degradation_result
    # Reference quantities are literal rationals, not outputs of production helpers.
    hours, demand, generation, eta = Fraction(1, 100), Fraction(60), Fraction(20), Fraction(4, 5)
    throughput = (demand - generation) * hours / eta
    loss = throughput - (demand - generation) * hours
    t_mid = Decimal("300.055")  # (10 W loss heat + 1 W external) * 36 s / 3600 J/K / 2
    with localcontext() as ctx:
        ctx.prec = 50
        inv = Decimal(1) / Decimal(300) - Decimal(1) / t_mid
        ac = (Decimal(12000) / Decimal("8.31446261815324") * inv).exp()
        ay = (Decimal(6000) / Decimal("8.31446261815324") * inv).exp()
        calendar = Decimal("0.000001") * 36 * ac
        cycling = Decimal("0.002") * Decimal("0.5") / 100 * ay
        retention = Decimal("0.9") - calendar - cycling
    rows = []

    def check(name, unit, expected, actual):
        expected = float(expected)
        # <=64 ulp of the reference (unit scale for exact zero): short arithmetic chain,
        # Decimal exp reference and cancellation in 1/T; never an authorization slack.
        tolerance = 64 * ulp(abs(expected) if expected else 1.0)
        if abs(actual - expected) > tolerance:
            raise AssertionError(f"{name}: {actual} != {expected} within {tolerance} {unit}")
        rows.append(dict(quantity=name, units=unit, expected=expected, actual=actual, absolute_tolerance=tolerance))

    check("required_and_served_power", "W", demand, eps.served_load_w)
    check("generation", "W", generation, eps.generation_w)
    check("end_energy", "Wh", 80 - throughput, context.spacecraft_state.battery.energy_wh)
    check("conversion_loss", "Wh", loss, eps.conversion_loss_wh)
    check("throughput", "Wh", throughput, ageing.throughput_increment_wh)
    heat = {x.node_id.value: x for x in step.thermal_coupling_result.node_heat_ledgers}
    check("bus_internal_heat", "W", 28, heat["bus"].internal_dissipation_w)
    check("payload_internal_heat", "W", 2, heat["payload"].internal_dissipation_w)
    check("battery_conversion_heat", "W", 10, heat["battery"].battery_conversion_heat_w)
    temps = {x.node_id.value: x.temperature_k for x in context.spacecraft_state.thermal.node_states}
    for name, temp in (("bus", Fraction(3003, 10)), ("battery", Fraction(30011, 100)), ("payload", Fraction(6001, 20))):
        check(name + "_temperature", "K", temp, temps[name])
    check("calendar_damage", "1", calendar, ageing.calendar_damage)
    check("cycling_damage", "1", cycling, ageing.cycling_damage)
    check("end_capacity_retention", "1", retention, ageing.end_usable_capacity_retention)
    check("reconciliation_unavailable", "Wh", 0, step.battery_capacity_reconciliation_result.unavailable_energy_wh)
    if attempt.transmission_result.transmitted_equivalent_bits_this_service != 9000.0:
        raise AssertionError("partial data transfer must be exactly 9000 equivalent bits")
    return {"assumptions": "Synthetic rational electrical/isolated-node reference; existing ageing law, no calibration.",
            "rows": rows, "clock_seconds": context.simulation_time_seconds, "completed_steps": context.diagnostics.completed_steps,
            "transmitted_equivalent_bits": 9000.0, "stored_equivalent_bits": 12000.0}


def denied_then_wait():
    context = reference_context()
    context.spacecraft_state.battery.energy_wh = 0.0
    forcing = physical_inputs(context, sunlit=False)
    denied = SimulationEngine().step_coupled_downlink(context, contact(context),
        record_id=record().record_id, physical_inputs=forcing)
    if denied.time_advanced or denied.transmission_result is not None:
        raise AssertionError("denial must not advance or deliver")
    # Explicit caller choice: transmitter off, 12 W bus-only waiting demand,
    # 20 W generation. Routing is fully served; no second EPS evaluation here.
    loads = PowerLoadBreakdown(12.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    served = ServedPowerLedger(tuple(ServedComponentPower(c, 12.0 if c is ElectricalLoadComponent.BASE_BUS else 0.0,
        12.0 if c is ElectricalLoadComponent.BASE_BUS else 0.0) for c in ElectricalLoadComponent))
    routed = compute_routed_internal_heat(loads, served, forcing.routing_config,
        context.inputs.spacecraft_configuration.thermal.network)
    step = SimulationEngine().step(context, eps_inputs=EPSIntervalInputs(True, 0.0, loads),
        thermal_inputs=forcing.thermal_inputs,
        heat_source_inputs=compose_routed_internal_heat_sources(routed, forcing.external_heat_sources),
        solar_degradation_forcing=forcing.solar_degradation_forcing)
    if context.simulation_time_seconds != 136 or context.diagnostics.completed_steps != 1:
        raise AssertionError("exactly one explicit waiting interval required")
    if context.ground_data_delivery_state.partial_transfers or context.ground_data_delivery_state.completed_deliveries:
        raise AssertionError("waiting must not deliver data")
    return {"denial_reason": denied.denial_reason.value, "denial_time_advanced": denied.time_advanced,
            "waiting_clock_seconds": context.simulation_time_seconds, "waiting_completed_steps": 1,
            "waiting_energy_wh": context.spacecraft_state.battery.energy_wh,
            "waiting_ageing_damage": step.battery_degradation_result.total_damage,
            "waiting_battery_temperature_k": step.battery_degradation_result.representative_temperature_k,
            "waiting_transmitted_bits": 0, "waiting_unmet_load_w": step.eps_result.battery.unmet_load_w}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--bundle-output", type=Path)
    parser.add_argument("--numerical", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.numerical:
        result = {"reference": numerical_reference(), "denial_then_wait": denied_then_wait()}
    else:
        state = build_demo_state() if args.resume is None else ExperimentBundle.from_json(
            args.resume.read_text(encoding="utf-8")).restore(repository_root=ROOT)
        stop = len(state.program.actions) if args.stop_after is None else args.stop_after
        if not len(state.memory.executed_action_ids) <= stop <= len(state.program.actions):
            parser.error("stop-after must lie between current cursor and program end")
        while len(state.memory.executed_action_ids) < stop:
            state = advance_continuation(state)
        if args.bundle_output:
            args.bundle_output.write_text(create_bundle(state, repository_root=ROOT).to_json(), encoding="utf-8")
        result = legacy.summarize(state)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
