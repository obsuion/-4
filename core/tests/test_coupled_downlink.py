"""Independent balances, electrical boundaries and atomic Task 03A execution."""

from copy import deepcopy
from dataclasses import replace
from math import nextafter, ulp

import pytest

from examples import v5_coupled_downlink_demo as demo
import ops_sim.v5.engine as engine_module
import ops_sim.v5.coupled_downlink as resources_module
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.coupled_downlink import (
    CoupledDownlinkAttempt, CoupledDownlinkDenialReason, DownlinkTransmitterConfig,
)
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import AcquisitionDataRecordId, ThermalNodeId
from ops_sim.v5.state import DataStorageState


def call(context, forcing=None, *, engine=None, selected=None, contact=None):
    return (engine or SimulationEngine()).step_coupled_downlink(
        context, contact or demo.contact(context),
        record_id=selected or demo.record().record_id,
        physical_inputs=forcing if forcing is not None else demo.physical_inputs(context),
    )


def references(context):
    s, d = context.spacecraft_state, context.ground_data_delivery_state
    return (context.inputs, s, s.battery, s.propulsion, s.thermal, *s.thermal.node_states,
            s.degradation, s.degradation.battery, s.degradation.solar, s.onboard,
            s.data_storage, s.data_storage.stored_records, *s.data_storage.stored_records,
            d, d.partial_transfers, d.completed_deliveries, context.ground_knowledge_state,
            context.mission_state, context.controller_state, context.diagnostics)


def unchanged(context, before, refs):
    assert context == before
    assert len(refs) == len(references(context))
    assert all(a is b for a, b in zip(refs, references(context)))


def configure_battery(context, **values):
    cfg = context.inputs.spacecraft_configuration
    battery = replace(cfg.eps.battery, **{
        name: demo.parameter_value(getattr(cfg.eps.battery, name), value)
        for name, value in values.items()
    })
    context.inputs = replace(context.inputs, spacecraft_configuration=replace(cfg, eps=replace(cfg.eps, battery=battery)))


def solar_generation(context, nominal):
    cfg = context.inputs.spacecraft_configuration
    solar = replace(cfg.eps.solar_array, nominal_generation_w=demo.parameter_value(cfg.eps.solar_array.nominal_generation_w, nominal))
    context.inputs = replace(context.inputs, spacecraft_configuration=replace(cfg, eps=replace(cfg.eps, solar_array=solar)))


def test_independent_rational_electrical_thermal_and_decimal_ageing_reference():
    report = demo.numerical_reference()
    assert len(report["rows"]) == 15
    assert report["clock_seconds"] == 136
    assert report["completed_steps"] == 1
    assert report["transmitted_equivalent_bits"] == 9000.0
    assert report["stored_equivalent_bits"] == 12000.0


@pytest.mark.parametrize("case,authorized", [
    ("no-supply", False), ("empty-solar", True), ("too-little-energy", False),
    ("power-limit", False), ("degraded-solar", False), ("full-power-boundary", True),
])
def test_supply_and_power_boundaries(case, authorized):
    context = demo.reference_context()
    sunlit = True
    if case == "no-supply":
        context.spacecraft_state.battery.energy_wh = 0.0
        sunlit = False
    elif case == "empty-solar":
        context.spacecraft_state.battery.energy_wh = 0.0
        solar_generation(context, 125.0)  # 100 W after retention; empty is not no supply.
    elif case == "too-little-energy":
        context.spacecraft_state.battery.energy_wh = 0.1
    elif case == "power-limit":
        configure_battery(context, max_discharge_output_power_w=30.0)
    else:
        configure_battery(context, max_discharge_output_power_w=40.0)
        if case == "degraded-solar":
            context.spacecraft_state.degradation.solar.generation_retention = 0.1
    before, refs = deepcopy(context), references(context)
    result = call(context, demo.physical_inputs(context, sunlit=sunlit))
    assert result.authorized is authorized
    assert result.time_advanced is authorized
    if authorized:
        assert result.eps_result.battery.unmet_load_w == 0
        assert result.eps_result.battery.served_load_w == 60.0
        assert context.simulation_time_seconds == 136
        assert context.diagnostics.completed_steps == 1
        if case == "empty-solar":
            assert context.spacecraft_state.battery.energy_wh == pytest.approx(0.36, rel=0, abs=4*ulp(0.36))
    else:
        assert result.denial_reason is CoupledDownlinkDenialReason.INSUFFICIENT_ELECTRICAL_SERVICE
        assert result.transmission_result is result.step_result is result.routed_heat_result is None
        assert result.eps_result.battery.unmet_load_w > 0
        unchanged(context, before, refs)


@pytest.mark.parametrize("energy,authorized", [(128.0, True), (nextafter(128.0, 0.0), False)])
def test_exact_binary_energy_boundary_has_no_authorization_tolerance(energy, authorized):
    context = demo.reference_context()
    configure_battery(context, nominal_energy_wh=256.0, discharge_efficiency=0.5,
                      max_discharge_output_power_w=64.0)
    context.spacecraft_state.battery.energy_wh = energy
    context.inputs = replace(context.inputs, numerical_config=replace(context.inputs.numerical_config,
        timestep_seconds=3600, checkpoint_interval_seconds=3600))
    forcing = demo.physical_inputs(context, sunlit=False)
    forcing = replace(forcing, transmitter=DownlinkTransmitterConfig(demo.parameter_value(
        forcing.transmitter.electrical_power_w, 40.0)))
    before, refs = deepcopy(context), references(context)
    result = call(context, forcing)
    assert result.authorized is authorized
    if authorized:
        assert result.eps_result.battery.end_energy_wh == 0.0
        assert result.eps_result.battery.discharge_output_w == 64.0
        assert result.eps_result.battery.conversion_loss_wh == 64.0
        assert result.step_result.battery_degradation_result.throughput_increment_wh == 128.0
    else:
        unchanged(context, before, refs)


def test_degraded_capacity_reconciliation_is_not_heat():
    context = demo.reference_context()
    context.spacecraft_state.battery.energy_wh = 90.0  # usable 100 Wh * 0.9, exactly full
    solar_generation(context, 125.0)
    result = call(context)
    step = result.step_result
    assert result.eps_capability_result.battery_usable_capacity_wh == 90.0
    assert result.eps_result.battery.end_energy_wh == 90.0
    assert result.eps_result.battery.charge_input_w == 0.0
    assert step.battery_degradation_result.calendar_damage > 0
    assert step.battery_degradation_result.throughput_increment_wh == 0
    reconciliation = step.battery_capacity_reconciliation_result
    assert reconciliation.unavailable_energy_wh > 0
    assert reconciliation.unavailable_energy_wh == pytest.approx(
        100 * step.battery_degradation_result.total_damage, rel=0, abs=8*ulp(90.0))
    assert context.spacecraft_state.battery.energy_wh == reconciliation.end_usable_capacity_wh
    heat = next(h for h in step.thermal_coupling_result.node_heat_ledgers if h.node_id.value == "battery")
    assert heat.battery_conversion_heat_w == 0.0
    assert heat.total_applied_heat_w == 1.0  # external IR only, no reconciliation energy
    battery = next(n for n in context.spacecraft_state.thermal.node_states if n.node_id.value == "battery")
    assert battery.temperature_k == 300.01


def test_state_above_degraded_capacity_is_invalid_not_electrical_denial():
    context = demo.reference_context()
    context.spacecraft_state.battery.energy_wh = nextafter(90.0, 100.0)
    before, refs = deepcopy(context), references(context)
    with pytest.raises(ValueError):
        call(context)
    unchanged(context, before, refs)


def test_nonzero_arrhenius_damage_responds_to_battery_temperature():
    cold, warm = demo.reference_context(), demo.reference_context()
    next(n for n in warm.spacecraft_state.thermal.node_states if n.node_id.value == "battery").temperature_k = 310.0
    a, b = call(cold).step_result.battery_degradation_result, call(warm).step_result.battery_degradation_result
    assert a.throughput_increment_wh == b.throughput_increment_wh
    assert 0 < a.calendar_damage < b.calendar_damage
    assert 0 < a.cycling_damage < b.cycling_damage


def test_isolated_constant_heat_temperature_matches_analytic_solution_at_two_steps():
    # For this deliberately isolated, nonradiating network dT/dt=Q/C is
    # constant. Euler is exact for this ODE. This is not a general stability claim.
    for dt in (18, 36):
        context = demo.reference_context()
        context.inputs = replace(context.inputs, numerical_config=replace(context.inputs.numerical_config,
            timestep_seconds=dt, checkpoint_interval_seconds=dt))
        result = call(context)
        for transition, power in zip(result.step_result.thermal_coupling_result.thermal_result.node_transitions, (30, 11, 5)):
            assert transition.end_temperature_k == pytest.approx(300 + power * dt / 3600, rel=0, abs=4*ulp(300.0))


def test_partial_completion_and_unused_capacity_leave_other_record_untouched():
    context = demo.reference_context()
    selected, other = demo.record(), demo.record("other")
    context.spacecraft_state.data_storage = DataStorageState((selected, other))
    partial = call(context)
    assert partial.transmission_result.transmitted_equivalent_bits_this_service == 9000.0
    assert partial.transmission_result.storage_freed_equivalent_bits == 0
    assert context.spacecraft_state.data_storage.stored_records == (selected, other)
    energy_after_partial = context.spacecraft_state.battery.energy_wh
    complete = call(context)
    assert complete.transmission_result.transmitted_equivalent_bits_this_service == 3000.0
    assert complete.transmission_result.storage_freed_equivalent_bits == 12000.0
    assert complete.transmission_result.unused_contact_capacity_bits == 6000.0
    assert context.spacecraft_state.data_storage.stored_records == (other,)
    assert context.spacecraft_state.data_storage.stored_records[0] is other
    assert len(context.ground_data_delivery_state.completed_deliveries) == 1
    assert context.ground_data_delivery_state.completed_deliveries[0].completing_contact.end_time_seconds == 172
    assert not context.ground_data_delivery_state.partial_transfers
    assert complete.eps_result.battery.load_w == 60
    assert complete.eps_result.battery.dt_seconds == 36
    assert context.spacecraft_state.battery.energy_wh < energy_after_partial
    assert context.simulation_time_seconds == 172 and context.diagnostics.completed_steps == 2
    before, refs = deepcopy(context), references(context)
    with pytest.raises(ValueError, match="already delivered"):
        call(context)
    unchanged(context, before, refs)


@pytest.mark.parametrize("case", ["missing-record", "record-type", "contact-type", "start", "duration", "horizon", "future-record"])
def test_invalid_data_timeline_and_selection_remain_atomic_even_without_supply(case):
    context = demo.reference_context()
    context.spacecraft_state.battery.energy_wh = 0.0
    forcing = demo.physical_inputs(context, sunlit=False)
    kwargs = {}
    if case == "missing-record": kwargs["selected"] = AcquisitionDataRecordId("absent")
    if case == "record-type": kwargs["selected"] = "bad"
    if case == "contact-type": kwargs["contact"] = "bad"
    if case == "start": kwargs["contact"] = replace(demo.contact(context), start_time_seconds=99)
    if case == "duration": kwargs["contact"] = replace(demo.contact(context), end_time_seconds=137)
    if case == "horizon": context.inputs = replace(context.inputs, common_world=replace(context.inputs.common_world, horizon_seconds=135))
    if case == "future-record": context.spacecraft_state.data_storage = DataStorageState((replace(demo.record(), scheduled_start_seconds=99),))
    before, refs = deepcopy(context), references(context)
    with pytest.raises((TypeError, ValueError)):
        call(context, forcing, **kwargs)
    unchanged(context, before, refs)


@pytest.mark.parametrize("case", ["missing", "bad-power", "units", "double-communications", "heat-duplicate", "unknown-node", "bad-routing-fraction", "bad-solar", "bad-external"])
def test_forged_nested_forcing_rejected_atomically_before_eps(monkeypatch, case):
    context = demo.reference_context()
    forcing = demo.physical_inputs(context, sunlit=False)
    if case == "missing": forcing = "no physical inputs"
    if case == "bad-power": object.__setattr__(forcing.transmitter.electrical_power_w, "value", -1.0)
    if case == "units": object.__setattr__(forcing.transmitter.electrical_power_w.provenance, "units", "bit/s")
    if case == "double-communications": object.__setattr__(forcing.baseline_loads, "communications_w", 36.0)
    if case == "heat-duplicate": object.__setattr__(forcing.external_heat_sources.node_sources[0], "internal_dissipation_w", 36.0)
    if case == "unknown-node": object.__setattr__(forcing.thermal_inputs.node_boundaries[0], "node_id", ThermalNodeId("absent"))
    if case == "bad-routing-fraction": object.__setattr__(forcing.routing_config.routes[0].retained_heat_fraction, "value", 2.0)
    if case == "bad-solar": object.__setattr__(forcing, "sunlit", 1)
    if case == "bad-external": object.__setattr__(forcing.external_heat_sources.node_sources[0], "absorbed_solar_w", float("nan"))
    before, refs = deepcopy(context), references(context)
    def forbidden(*args, **kwargs): raise AssertionError("invalid input reached EPS")
    monkeypatch.setattr(resources_module, "compute_eps_interval_transition", forbidden)
    with pytest.raises((TypeError, ValueError)):
        call(context, forcing)
    unchanged(context, before, refs)


@pytest.mark.parametrize("power", [0.0, -1.0, True, float("inf")])
def test_transmitter_requires_explicit_positive_watts(power):
    with pytest.raises((TypeError, ValueError)):
        DownlinkTransmitterConfig(demo.storage._parameter("communications.transmitter-electrical-power", "W", power))


@pytest.mark.parametrize("stage", ["thermal", "degradation", "after-physical", "precommit"])
def test_late_failure_preserves_every_authoritative_value_and_identity(monkeypatch, stage):
    context = demo.reference_context()
    before, refs = deepcopy(context), references(context)
    def fail(*args, **kwargs): raise RuntimeError("injected late failure")
    engine = SimulationEngine()
    if stage == "thermal": monkeypatch.setattr(resources_module, "compute_eps_thermal_interval_transition", fail)
    elif stage == "degradation": monkeypatch.setattr(engine_module, "compute_battery_degradation_transition", fail)
    elif stage == "after-physical":
        def fail_after(working, interval):
            assert working.spacecraft_state.battery.energy_wh != before.spacecraft_state.battery.energy_wh
            assert working.ground_data_delivery_state.partial_transfers
            fail()
        monkeypatch.setattr(SimulationEngine, "_failure_capability_resolution", staticmethod(fail_after))
    else:
        monkeypatch.setattr(CoupledDownlinkAttempt, "__post_init__", fail)
    with pytest.raises(RuntimeError, match="injected late"):
        call(context, engine=engine)
    unchanged(context, before, refs)


def test_authoritative_eps_is_used_once_and_commit_occurs_after_valid_result(monkeypatch):
    seen, context = {}, demo.reference_context()
    for name in ("compute_eps_interval_transition", "compute_eps_thermal_interval_transition",
                 "compute_battery_throughput_increment", "evaluate_downlink_transmission"):
        owner = resources_module if name in ("compute_eps_interval_transition", "compute_eps_thermal_interval_transition") else engine_module
        original = getattr(owner, name)
        def spy(*args, _name=name, _original=original, **kwargs):
            assert _name not in seen
            result = _original(*args, **kwargs)
            seen[_name] = (args, result)
            return result
        monkeypatch.setattr(owner, name, spy)
    engine = SimulationEngine()
    original_commit = engine._commit
    original_validate = CoupledDownlinkAttempt.__post_init__
    def validate(self):
        original_validate(self)
        seen["valid_attempt"] = self
    def commit(original, working):
        assert "valid_attempt" in seen and "committed" not in seen
        seen["committed"] = True
        original_commit(original, working)
    monkeypatch.setattr(CoupledDownlinkAttempt, "__post_init__", validate)
    monkeypatch.setattr(SimulationEngine, "_commit", staticmethod(commit))
    result = call(context, engine=engine)
    eps = seen["compute_eps_interval_transition"][1]
    assert result.eps_result is result.step_result.eps_result is eps
    assert seen["compute_eps_thermal_interval_transition"][0][4] is eps
    assert seen["compute_battery_throughput_increment"][0][0] is eps
    assert context.simulation_time_seconds == 136 and context.diagnostics.completed_steps == 1
    assert seen["committed"]


@pytest.mark.parametrize("case", ["eps-identity", "thermal-duration", "ageing-duration", "reconciliation", "solar-forcing", "missing-data"])
def test_inconsistent_precommit_evidence_is_rejected_before_any_commit(monkeypatch, case):
    context = demo.reference_context()
    before, refs = deepcopy(context), references(context)
    validate = CoupledDownlinkAttempt.__post_init__
    def corrupt_and_validate(self):
        step = self.step_result
        if case == "eps-identity": object.__setattr__(step, "eps_result", replace(self.eps_result))
        elif case == "thermal-duration": object.__setattr__(step.thermal_coupling_result.thermal_result, "dt_seconds", 35)
        elif case == "ageing-duration": object.__setattr__(step.battery_degradation_result, "dt_seconds", 35)
        elif case == "reconciliation": object.__setattr__(step.battery_capacity_reconciliation_result, "proposed_end_energy_wh", 80.0)
        elif case == "solar-forcing": object.__setattr__(step.solar_degradation_result, "retention_loss", 0.01)
        else: object.__setattr__(self, "transmission_result", None)
        validate(self)
    monkeypatch.setattr(CoupledDownlinkAttempt, "__post_init__", corrupt_and_validate)
    with pytest.raises((ValueError, TypeError)):
        call(context)
    unchanged(context, before, refs)


def test_coupled_api_requires_physical_inputs_without_legacy_fallback():
    context = demo.reference_context()
    before, refs = deepcopy(context), references(context)
    with pytest.raises(TypeError, match="physical_inputs"):
        SimulationEngine().step_coupled_downlink(context, demo.contact(context), record_id=demo.record().record_id)
    unchanged(context, before, refs)


def test_resource_composition_is_pure_and_returns_the_same_eps_for_thermal(monkeypatch):
    context = demo.reference_context()
    before, refs = deepcopy(context), references(context)
    cfg, spacecraft = context.inputs.spacecraft_configuration, context.spacecraft_state
    captured = []
    original = resources_module.compute_eps_thermal_interval_transition
    def thermal(*args, **kwargs):
        captured.append(args[4])
        return original(*args, **kwargs)
    monkeypatch.setattr(resources_module, "compute_eps_thermal_interval_transition", thermal)
    proposal = resources_module.evaluate_coupled_downlink_resources(
        spacecraft.battery, spacecraft.degradation, spacecraft.thermal, cfg.eps, cfg.thermal.network,
        demo.physical_inputs(context), dt_seconds=36)
    assert proposal.authorized and captured == [proposal.eps_result]
    assert captured[0] is proposal.eps_result
    unchanged(context, before, refs)


def test_denial_followed_by_explicit_transmitter_off_wait():
    result = demo.denied_then_wait()
    assert result["denial_time_advanced"] is False
    assert result["waiting_completed_steps"] == 1 and result["waiting_clock_seconds"] == 136
    assert result["waiting_energy_wh"] == pytest.approx(0.072, rel=0, abs=4*ulp(0.072))
    assert result["waiting_ageing_damage"] > 0
    assert result["waiting_battery_temperature_k"] > 300
    assert result["waiting_transmitted_bits"] == result["waiting_unmet_load_w"] == 0


def test_schema5_restart_after_coupled_partial_replays_exactly():
    direct = demo.reference_context()
    call(direct)
    restored = CheckpointState.from_dict(CheckpointState.from_context(direct).to_dict()).restore(direct.inputs)
    a, b = call(direct), call(restored)
    assert a == b and direct == restored
    assert CheckpointState.from_context(direct).schema_version == 5


def test_legacy_path_remains_data_only_and_physically_distinct():
    legacy, coupled = demo.reference_context(), demo.reference_context()
    before = deepcopy(legacy.spacecraft_state)
    result = SimulationEngine().step_downlink(legacy, demo.contact(legacy), record_id=demo.record().record_id)
    physical = call(coupled)
    assert result.transmission_result == physical.transmission_result
    assert result.step_result.eps_result is None
    assert legacy.spacecraft_state == before
    assert legacy.simulation_time_seconds == coupled.simulation_time_seconds == 136
    assert legacy.spacecraft_state != coupled.spacecraft_state
