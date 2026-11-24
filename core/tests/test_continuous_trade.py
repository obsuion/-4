"""Focused continuous-contract, physical boundary and integer-custody checks.

These short tests are not the 24/72-hour pilots or month qualification. The
cycle energy reference comes from the separate pre-score engineering budget.
"""

from dataclasses import replace
from fractions import Fraction
from math import ceil, cos, fsum, radians

import pytest

from ops_sim.v5.continuation import checked_checkpoint
from ops_sim.v5.continuous_trade import (
    CONTACT_END, HORIZON, LIGHT, PERIOD, ContinuousSpec, _force, _macro,
    _profile, _turn, _turn_duration, advance_continuous, cycle_requests,
    forcing_breakpoints, forecast_context, observe_continuous,
    published_requests, start_continuous, summary, validate_state,
)
from ops_sim.v5.experiment_codec import canonical_content


BITS = 426_241_440


def checkpoint(state):
    return canonical_content(checked_checkpoint(state.context))


@pytest.mark.parametrize("field,value", [
    ("design_id", "B8-A4"), ("design_id", True),
    ("workload", "close"), ("numerical", 2), ("variant", "ENERGY_ONLY"),
    ("version", True), ("version", 2), ("horizon", 86400),
    ("horizon", float(HORIZON)), ("initial_fraction", 1),
    ("initial_fraction", 0.), ("initial_fraction", float("nan")),
    ("initial_fraction", float("inf")), ("contact_chunk_seconds", True),
    ("contact_chunk_seconds", 0), ("contact_chunk_seconds", 21),
])
def test_contract_rejects_ambiguous_or_reinterpreted_inputs(field, value):
    with pytest.raises((ValueError, TypeError)):
        replace(ContinuousSpec("B8-A2"), **{field: value})


def test_exact_versioned_round_trip_and_real_month_world():
    spec = ContinuousSpec("B8-A2")
    assert ContinuousSpec.from_dict(spec.to_dict()) == spec
    for change in ({"extra": 0}, {"horizon": 3600}):
        with pytest.raises(ValueError):
            ContinuousSpec.from_dict({**spec.to_dict(), **change})
    missing = spec.to_dict()
    del missing["version"]
    with pytest.raises(ValueError):
        ContinuousSpec.from_dict(missing)
    state = start_continuous(spec)
    assert HORIZON == 30 * 24 * 3600 == state.context.inputs.common_world.horizon_seconds
    assert state.context.simulation_time_seconds == 0
    assert state.context.spacecraft_state.battery.energy_wh == 344.
    assert {n.temperature_k for n in state.context.spacecraft_state.thermal.node_states} == {293.15}
    assert summary(state)["status"] == "pilot-boundary"
    # Summary scores completed exposure [0,now); knowledge at the right-hand
    # endpoint can already publish the next cycle without counting its demand.
    assert summary(state)["offered_products"] == 0
    assert len(published_requests(state, 0)) == 6


def test_cycle_occurrences_are_deterministic_unique_and_inside_light():
    state = start_continuous(ContinuousSpec("B8-A2"))
    requests, opportunities, captures = set(), set(), set()
    for cycle in range(480):
        pairs = cycle_requests(state, cycle)
        assert pairs == cycle_requests(state, cycle)
        assert len(pairs) == 6
        for index, (released, item) in enumerate(pairs):
            product, opportunity = released.product, item.opportunity
            origin = cycle * PERIOD
            assert released.release_seconds == origin
            assert product.delivery_deadline_seconds == origin + CONTACT_END
            assert opportunity.window_start_seconds == origin + 120 + 600 * index
            assert opportunity.window_end_seconds - opportunity.window_start_seconds == 70
            assert opportunity.imaging_duration_seconds == 60
            assert origin <= opportunity.window_start_seconds < opportunity.window_end_seconds <= origin + LIGHT
            requests.add(product.request.request_id)
            opportunities.add(opportunity.opportunity_id)
            captures.add(product.capture_group)
    assert len(requests) == len(opportunities) == len(captures) == 2880
    for bad in (-1, 480, True, 1.0):
        with pytest.raises(ValueError):
            cycle_requests(state, bad)


def test_regular_and_burst_preserve_offered_product_requirements():
    regular = start_continuous(ContinuousSpec("B8-A2", workload="regular"))
    burst = start_continuous(ContinuousSpec("B8-A2", workload="burst"))
    total_priority = 0.
    for index, (left, right) in enumerate(zip(cycle_requests(regular, 3), cycle_requests(burst, 3))):
        lr, lo = left
        rr, ro = right
        total_priority += lr.product.request.priority_weight
        assert lr.product.request.priority_weight == rr.product.request.priority_weight == 3 - index % 3
        assert lr.release_seconds == rr.release_seconds == 3 * PERIOD
        assert lr.product.delivery_deadline_seconds == rr.product.delivery_deadline_seconds
        assert lo.acquisition.sizing.stored_bits == ro.acquisition.sizing.stored_bits == BITS
        assert lo.acquisition.sizing.captured_channels == ro.acquisition.sizing.captured_channels
        assert lo.acquisition.sizing.bits_per_sample == ro.acquisition.sizing.bits_per_sample == 12
        assert lo.acquisition.sizing.nx == ro.acquisition.sizing.nx == 1539
        assert lo.acquisition.sizing.ny == ro.acquisition.sizing.ny == 4616
        assert lo.candidate.maneuver_candidate.common_frame_boresight == ro.candidate.maneuver_candidate.common_frame_boresight
        assert lo.opportunity.window_start_seconds == 3 * PERIOD + 120 + 600 * index
        assert ro.opportunity.window_start_seconds == 3 * PERIOD + 120 + 130 * index
    assert total_priority == 12


def test_only_current_cycle_is_published_and_future_request_cannot_enter_macro():
    state = start_continuous(ContinuousSpec("B8-A2"))
    for now, cycle in ((0, 0), (PERIOD - 1, 0), (PERIOD, 1), (HORIZON - 1, 479)):
        visible = published_requests(state, now)
        assert visible == cycle_requests(state, cycle)
        assert all(r.release_seconds <= now for r, _ in visible)
    before = checkpoint(state)
    with pytest.raises(ValueError, match="unpublished"):
        _macro(state, state.context, state.angle_rad, cycle_requests(state, 1)[0])
    assert checkpoint(state) == before


@pytest.mark.parametrize("design,expected_30,expected_60", [("B8-A2", 44, 72), ("B4-A4", 47, 78)])
def test_paid_turn_duration_and_burst_window_feasibility_are_independent(design, expected_30, expected_60):
    state = start_continuous(ContinuousSpec(design))
    inertia = state.design.inertia_y_kg_m2
    # Both angles lie in the momentum-limited trapezoidal regime: ta=H/tau=10s.
    independent = lambda degrees: ceil(radians(degrees) * inertia / .2 + .2 / .02) + 5
    assert independent(30) == expected_30
    assert independent(60) == expected_60
    assert _turn_duration(state, 0., radians(30))[1] == expected_30
    assert _turn_duration(state, radians(-30), radians(30))[1] == expected_60
    regular_actual = [120]
    burst_actual = [120]
    for index in range(1, 6):
        regular_actual.append(max(120 + 600 * index, regular_actual[-1] + 60 + independent(60)))
        burst_actual.append(max(120 + 130 * index, burst_actual[-1] + 60 + independent(60)))
    assert regular_actual == [120 + 600 * i for i in range(6)]
    if design == "B8-A2":
        assert burst_actual[-1] + 60 == 120 + 5 * 130 + 70
    else:
        assert burst_actual[2] + 60 > 120 + 2 * 130 + 70


def test_periodic_forcing_is_exact_at_right_continuous_endpoints():
    state = start_continuous(ContinuousSpec("B8-A2"))
    for time, sunlit in ((0, True), (Fraction(7199, 2), True), (3600, False),
                         (Fraction(10799, 2), False), (5400, True), (9000, False)):
        wait, diagnostics = _force(state, time, 0.)
        assert wait.sunlit is sunlit
        assert diagnostics["geometric_incidence"] == pytest.approx(cos(radians(70)) if sunlit else 0.)
        assert (diagnostics["solar_bus_w"] > 0) is sunlit
    assert forcing_breakpoints(3590, 5410) == (3600, 5400)
    assert forcing_breakpoints(3600, 5400) == ()


def test_motion_splits_forcing_discontinuity_and_keeps_its_physical_duration():
    state = start_continuous(ContinuousSpec("B8-A2"))
    # A deliberately located physical-owner probe, not a reconstructed mission.
    state.context.simulation_time_seconds = 3580
    final_angle, events, approved = _turn(state, state.context, 0., radians(30))
    assert approved and final_angle == radians(30)
    motion = events[0]
    assert (motion["start"], motion["end"]) == (3580, 3619)
    times = {Fraction(*s["time"]) for s in motion["samples"]}
    assert 3600 in times
    for interval in motion["diagnostics"]:
        start, end = Fraction(*interval["start"]), Fraction(*interval["end"])
        assert end - start <= 5
        assert not start < 3600 < end
        assert (interval["values"]["solar_bus_w"] > 0) is (start < 3600)
    assert state.context.simulation_time_seconds == 3624  # includes paid settling


def test_forecast_uses_received_snapshots_and_cannot_mutate_actual_state():
    state = start_continuous(ContinuousSpec("B8-A2"))
    before = checkpoint(state)
    feedback = observe_continuous(state)
    predicted = forecast_context(state, feedback)
    assert predicted.inputs is state.context.inputs
    assert predicted.spacecraft_state is not state.context.spacecraft_state
    assert predicted.ground_data_delivery_state is not state.context.ground_data_delivery_state
    _, events, approved, _ = _macro(state, predicted, state.angle_rad, cycle_requests(state, 0)[0])
    assert approved and predicted.simulation_time_seconds == 180
    assert len(predicted.spacecraft_state.data_storage.stored_records) == 1
    assert events[-1]["acquired_bits"] == BITS
    assert checkpoint(state) == before
    assert state.accounting["acquired"] == 0
    with pytest.raises(ValueError, match="zero-latency"):
        forecast_context(state, replace(feedback, received_seconds=1))


@pytest.fixture(scope="module")
def first_cycle():
    state = start_continuous(ContinuousSpec("B8-A2"))
    origin = checkpoint(state)
    events = []
    while state.context.simulation_time_seconds < PERIOD:
        state = advance_continuous(state, stop_seconds=PERIOD)
        events.extend(state.last_events)
    return state, tuple(events), origin


def test_continuous_cycle_has_paid_contiguous_physics_and_phase_dt_limits(first_cycle):
    state, events, _ = first_cycle
    now, angle = 0, 0.
    limits = {"hold": 60, "motion": 5, "settle": 5, "imaging": 15, "contact": 20}
    for event in events:
        if "accounting" not in event:
            continue
        assert event["start"] == now
        assert event["start_angle"] == angle
        assert event["accounting"]["requested_load_wh"] > 0
        times = sorted({Fraction(*s["time"]) for s in event["samples"]})
        assert times[0] == event["start"] and times[-1] == event["end"]
        assert all(0 < end - start <= limits[event["kind"]] for start, end in zip(times, times[1:]))
        now, angle = event["end"], event["end_angle"]
    assert now == PERIOD and angle == state.angle_rad == 0.
    assert state.accounting["phase_seconds"]["motion"] == 413
    assert state.accounting["phase_seconds"]["settle"] == 35
    assert sum(state.accounting["phase_seconds"].values()) == PERIOD
    assert state.cycle_index == 1 and state.next_request_index == 0
    assert state.context.controller_state.replan_count == state.advances
    assert summary(state)["offered_products"] == 6


def test_independent_bus_storage_and_integer_custody_balances(first_cycle):
    state, events, _ = first_cycle
    energies = state.accounting["energies"]
    assert energies["generation_wh"] + energies["discharge_output_wh"] == pytest.approx(
        energies["served_load_wh"] + energies["charge_input_wh"] + energies["curtailed_generation_wh"], abs=1e-9)
    assert energies["requested_load_wh"] == pytest.approx(energies["served_load_wh"] + energies["unmet_load_wh"], abs=1e-9)
    assert state.context.spacecraft_state.battery.energy_wh == pytest.approx(
        344 + .9 * energies["charge_input_wh"] - energies["discharge_output_wh"] / .9, abs=1e-9)
    assert energies["calendar_damage"] == energies["cycling_damage"] == energies["solar_retention_loss"] == 0.
    # Independently derived prospective schedule: actual TX is 15.984054s;
    # the reference budget conservatively used 16s and a finer slew quadrature.
    assert energies["generation_wh"] == pytest.approx(28.4052465, abs=.01)
    assert energies["served_load_wh"] == pytest.approx(31.5732594, abs=.01)
    assert state.context.spacecraft_state.battery.energy_wh == pytest.approx(344 - 7.2052961, abs=.02)
    custody = state.context.ground_data_delivery_state
    assert len(custody.completed_deliveries) == 6
    assert not custody.partial_transfers and not state.context.spacecraft_state.data_storage.stored_records
    acquired = [e for e in events if e["kind"] == "imaging" and e["approved"]]
    services = [s for e in events for s in e.get("services", ())]
    assert len(acquired) == 6 and sum(e["acquired_bits"] for e in acquired) == 6 * BITS
    assert sum(s["transmitted_bits"] for s in services) == 6 * BITS
    assert state.accounting["acquired_bits"] == state.accounting["transmitted_bits"] == 6 * BITS
    assert state.accounting["acquired"] == state.accounting["completed"] == state.accounting["credited"] == 6
    assert state.accounting["weighted_credit"] == 12
    assert all(s["completed"] and s["credited"] and Fraction(*s["completion"]) <= 3500 for s in services)
    assert {s["request_id"] for s in services} == {e["request_id"] for e in acquired}
    tx_seconds = fsum(float(Fraction(*s["end_offset"]) - Fraction(*s["start_offset"])) for s in services)
    assert tx_seconds == pytest.approx(6 * BITS / 160_000_000, abs=1e-12)


def test_next_cycle_continues_energy_temperature_and_custody_without_reset(first_cycle):
    state, _, _ = first_cycle
    previous = checkpoint(state)
    old_energy = state.context.spacecraft_state.battery.energy_wh
    old_temperatures = {n.node_id.value: n.temperature_k for n in state.context.spacecraft_state.thermal.node_states}
    advanced = advance_continuous(state, stop_seconds=2 * PERIOD)
    assert checkpoint(state) == previous
    first_physical = next(e for e in advanced.last_events if "samples" in e)
    assert first_physical["samples"][0]["energy_wh"] == old_energy
    assert first_physical["samples"][0]["temperatures_k"] == old_temperatures
    assert advanced.context.simulation_time_seconds == PERIOD + 180
    assert advanced.accounting["acquired"] == 7 and advanced.accounting["completed"] == 6
    assert len(advanced.context.ground_data_delivery_state.completed_deliveries) == 6
    assert len(advanced.context.spacecraft_state.data_storage.stored_records) == 1
    assert advanced.last_events[-1]["request_id"] == "task05fa-regular-c0001-r0"
    validate_state(advanced, full_binding=True)


def test_low_reserve_forecast_rejects_and_replans_without_fictitious_credit():
    state = advance_continuous(start_continuous(ContinuousSpec("B8-A2", initial_fraction=.001)))
    before = checkpoint(state)
    advanced = advance_continuous(state)
    assert checkpoint(state) == before
    rejected = [e for e in advanced.last_events if e["kind"] == "forecast-rejection"]
    assert len(rejected) == 1 and rejected[0]["request_id"].endswith("-r1")
    assert rejected[0]["reason"] == "acquisition-protection-denied"
    assert advanced.last_events[-1]["request_id"].endswith("-r2")
    assert advanced.context.simulation_time_seconds == 1380
    assert advanced.accounting["forecast_rejections"] == 1
    assert advanced.accounting["acquired"] == 2 and advanced.accounting["credited"] == 0
    ids = {r.imaging_request_id.value for r in advanced.context.spacecraft_state.data_storage.stored_records}
    assert not any(value.endswith("-r1") for value in ids)
    assert sum(advanced.accounting["phase_seconds"].values()) == 1380
    assert advanced.context.controller_state.replan_count == 2


def test_denied_actual_dark_turn_becomes_same_duration_paid_hold():
    state = start_continuous(ContinuousSpec("B8-A2", initial_fraction=.001))
    state.context.simulation_time_seconds = LIGHT
    initial_energy = state.context.spacecraft_state.battery.energy_wh
    start_angle, target = radians(-30), radians(30)
    final_angle, events, approved = _turn(state, state.context, start_angle, target)
    assert not approved and final_angle == start_angle
    assert len(events) == 1 and events[0]["end"] - events[0]["start"] == 67
    assert events[0]["reasons"] == ["motion-full-electrical-service-unavailable"]
    assert all(d["values"]["actuator_electrical_w"] == .5 for d in events[0]["diagnostics"])
    assert state.context.simulation_time_seconds == LIGHT + 67
    assert 0 < state.context.spacecraft_state.battery.energy_wh < initial_energy
    assert not state.context.spacecraft_state.data_storage.stored_records


def test_atomic_macro_stop_rejects_without_mutating_reality():
    state = start_continuous(ContinuousSpec("B8-A2"))
    before = checkpoint(state)
    with pytest.raises(ValueError, match="stop lies inside"):
        advance_continuous(state, stop_seconds=150)
    assert checkpoint(state) == before


def test_refinement_halves_physical_dt_without_changing_action_duration():
    partitions = []
    for numerical in ("coarse", "fine"):
        state = start_continuous(ContinuousSpec("B8-A2", numerical=numerical))
        result, _ = _profile(state, state.context, 0., 120, "hold", lambda t: (0., 0., 0.))
        partitions.append(tuple(i.end_seconds - i.start_seconds for i in result.intervals))
        assert state.context.simulation_time_seconds == 120
    assert partitions == [(Fraction(60),) * 2, (Fraction(30),) * 4]


def test_completed_cycle_cannot_restore_with_previous_cycle_cursor(first_cycle):
    state, _, _ = first_cycle
    stale = replace(state, cycle_index=0, next_request_index=6, phase="recovery")
    before = checkpoint(stale)
    with pytest.raises(ValueError, match="cycle cursor must advance"):
        validate_state(stale, full_binding=True)
    with pytest.raises(ValueError, match="cycle cursor must advance"):
        advance_continuous(stale)
    assert checkpoint(stale) == before


@pytest.mark.parametrize("clock", [3420, 3499, 3600])
def test_request_phase_cannot_resume_after_contact_preparation(clock):
    state = start_continuous(ContinuousSpec("B8-A2"))
    state.context.simulation_time_seconds = clock
    before = checkpoint(state)
    with pytest.raises(ValueError, match="request phase cannot resume"):
        advance_continuous(state)
    assert checkpoint(state) == before


@pytest.mark.parametrize("offset", [-1, 1])
def test_received_feedback_rejects_stale_and_future_timestamps(first_cycle, offset):
    state, _, _ = first_cycle
    observed = observe_continuous(state)
    unreceived = replace(observed, sampled_seconds=PERIOD + offset, received_seconds=PERIOD + offset)
    before = checkpoint(state)
    with pytest.raises(ValueError, match="zero-latency"):
        forecast_context(state, unreceived)
    assert checkpoint(state) == before


def test_received_feedback_rejects_boolean_clock_and_unbound_derived_design():
    state = start_continuous(ContinuousSpec("B8-A2"))
    observed = observe_continuous(state)
    with pytest.raises(ValueError, match="zero-latency"):
        forecast_context(state, replace(observed, sampled_seconds=False, received_seconds=False))
    changed = replace(state, design=replace(state.design, inertia_y_kg_m2=state.design.inertia_y_kg_m2 + 1))
    with pytest.raises(ValueError, match="derived design mismatch"):
        validate_state(changed, full_binding=True)
