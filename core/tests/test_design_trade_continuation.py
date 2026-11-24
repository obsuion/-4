"""Paid maneuver/acquisition causality and fresh-process coupled continuation."""

from dataclasses import replace
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ops_sim.v5.design_trade_campaign import TradeSpec
from ops_sim.v5.design_trade_continuation import (advance_trade, restore_trade, run_trade,
    save_trade, start_trade, summarize_trade)
from ops_sim.v5.design_trade_design import DesignAssumptions, enumerate_designs, select_designs
from ops_sim.v5.design_trade_execution import ProfileOutcome
from ops_sim.v5.experiment_codec import canonical_content, content_digest
from ops_sim.v5.continuation import checked_checkpoint


def spec(**changes):
    initial = TradeSpec(select_designs(enumerate_designs())[0].design_id,
        "relaxed", "FULL", 1, DesignAssumptions())
    return replace(initial, **changes)


@pytest.fixture(scope="module")
def completed():
    return run_trade(spec())


def test_all_real_execution_intervals_are_paid_contiguous_and_attitude_consistent(completed):
    result = summarize_trade(completed)
    assert result["status"] == "completed-horizon"
    assert sum(result["phase_seconds"].values()) == completed.spec.horizon
    assert result["phase_seconds"]["motion"] > 0
    assert result["phase_seconds"]["settle"] > 0
    assert len(result["requests"]) == 6
    assert completed.context.simulation_time_seconds == completed.spec.horizon
    last_time, angle = 0, 0.
    for event in completed.events:
        assert event.start_seconds == last_time and event.start_angle_rad == angle
        assert event.outcome.accounting.requested_load_wh > 0
        if event.phase == "motion":
            assert type(event.outcome) is ProfileOutcome
            assert event.outcome.approved
            assert event.end_angle_rad != event.start_angle_rad
            assert any(i.omega_rad_s != 0 for i in event.outcome.intervals)
        elif event.phase in ("hold", "settle", "imaging", "contact"):
            assert event.end_angle_rad == event.start_angle_rad
        last_time, angle = event.end_seconds, event.end_angle_rad
    assert last_time == completed.spec.horizon and angle == completed.angle_rad


def test_acquisition_starts_only_after_explicit_ready_state_and_inside_window(completed):
    windows = {o.acquisition.request.request_id.value: o for o in completed.program.opportunities}
    seen = []
    for i, event in enumerate(completed.events):
        if event.acquisition is None:
            continue
        item = windows[event.request_id]
        o = item.opportunity
        assert o.window_start_seconds <= event.start_seconds
        assert event.end_seconds <= o.window_end_seconds
        assert event.end_seconds-event.start_seconds == 60
        assert event.acquisition.plan.sizing.stored_bits == 426241440
        assert event.acquisition.record.scheduled_start_seconds == event.start_seconds
        assert any(e.phase == "motion" for e in completed.events[:i])
        assert completed.events[i-1].phase in ("settle", "hold")
        seen.append(event.request_id)
    assert seen and len(seen) == len(set(seen))


def test_product_credit_uses_actual_receipt_and_inclusive_deadline(completed):
    summary = summarize_trade(completed)
    credits = sum(Fraction(row["priority"])*row["credited_products"] for row in summary["requests"])
    denominator = sum(Fraction(row["priority"]) for row in summary["requests"])
    assert Fraction(*summary["weighted_credit"]) == credits/denominator
    for row in summary["requests"]:
        if row["credited_products"]:
            assert row["acquired"] and Fraction(*row["exact_completion_seconds"]) <= 1550
    assert sum(row["credited_products"] for row in summary["requests"]) <= len(
        completed.context.ground_data_delivery_state.completed_deliveries)


def test_impossible_turn_window_is_rejected_without_free_actual_maneuver():
    state = run_trade(spec(torque_nm=.00001))
    result = summarize_trade(state)
    assert result["weighted_credit"] == [0, 1]
    assert len(state.rejections) == 6
    assert all(reason == "motion-and-exposure-do-not-fit-window" for _,reason in state.rejections)
    assert "motion" not in result["phase_seconds"]
    assert result["accounting"]["requested_load_wh"] > 0
    assert state.context.simulation_time_seconds == state.spec.horizon


def test_full_and_resource_variants_share_requests_but_use_explicit_counterfactual():
    a, b = start_trade(spec()), start_trade(spec(variant="RESOURCE_ONLY"))
    assert canonical_content(a.program.requests) == canonical_content(b.program.requests)
    assert canonical_content(a.program.opportunities) == canonical_content(b.program.opportunities)
    assert a.design == b.design
    assert a.spec.inertia(a.design) != b.spec.inertia(b.design)
    assert json.loads(save_trade(a))["input_digest"] != json.loads(save_trade(b))["input_digest"]


def changed_input_label(state):
    inputs = replace(state.context.inputs, spacecraft_configuration=replace(
        state.context.inputs.spacecraft_configuration, label="unbound replacement"))
    return replace(state, context=replace(state.context, inputs=inputs))


@pytest.mark.parametrize("change", [
    lambda s: replace(s, spec=replace(s.spec, variant="RESOURCE_ONLY")),
    lambda s: replace(s, design=replace(s.design, spare_mass_kg=s.design.spare_mass_kg+1.)),
    lambda s: replace(s, program=replace(s.program, assumptions=s.program.assumptions+("unbound replacement",))),
    changed_input_label,
])
def test_mixed_immutable_owners_reject_before_execution_or_save(change):
    state = change(start_trade(spec()))
    before = canonical_content(checked_checkpoint(state.context))
    with pytest.raises(ValueError, match="immutable.*binding mismatch"):
        advance_trade(state)
    with pytest.raises(ValueError, match="immutable.*binding mismatch"):
        save_trade(state)
    assert canonical_content(checked_checkpoint(state.context)) == before


def test_restore_replays_completed_boundary_without_trusting_attitude_or_checkpoint():
    state = advance_trade(start_trade(spec()))
    restored = restore_trade(save_trade(state))
    assert save_trade(restored) == save_trade(state)
    for field, value in (("angle_hex", float(1.25).hex()), ("attempted_request_ids", [])):
        payload = json.loads(save_trade(state))
        payload["state"][field] = value
        del payload["digest"]
        payload["digest"] = content_digest("task05e-completed-bundle-v1", payload)
        with pytest.raises(ValueError, match="causal replay"):
            restore_trade(json.dumps(payload))


@pytest.mark.parametrize("field,value", [("version", True), ("version", 2), ("extra", None)])
def test_unknown_or_downgraded_bundle_fields_reject(field, value):
    payload = json.loads(save_trade(start_trade(spec())))
    payload[field] = value
    with pytest.raises(ValueError):
        restore_trade(json.dumps(payload))


def test_bundle_rejects_duplicate_keys_and_immutable_parameter_changes():
    original = save_trade(start_trade(spec()))
    with pytest.raises(ValueError, match="duplicate"):
        restore_trade(original[:-1]+',"version":1}')
    payload = json.loads(original)
    payload["spec"]["torque_nm"] *= 2
    del payload["digest"]
    payload["digest"] = content_digest("task05e-completed-bundle-v1", payload)
    with pytest.raises(ValueError, match="binding"):
        restore_trade(json.dumps(payload))


def test_fresh_process_restart_matches_uninterrupted_after_completed_action(tmp_path):
    prefix = advance_trade(start_trade(spec()))
    before, after = tmp_path/"boundary.json", tmp_path/"fresh-final.json"
    before.write_text(save_trade(prefix), encoding="utf-8")
    command = [sys.executable, "-B", "-c", (
        "from pathlib import Path; import sys; "
        "from ops_sim.v5.design_trade_continuation import restore_trade,advance_trade,save_trade; "
        "s=restore_trade(Path(sys.argv[1]).read_text(encoding='utf-8')); "
        "exec('while s.context.simulation_time_seconds < s.spec.horizon:\\n s=advance_trade(s)'); "
        "Path(sys.argv[2]).write_text(save_trade(s),encoding='utf-8')"), str(before), str(after)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=180)
    (tmp_path/"fresh-process.log").write_text(result.stdout+result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    state = prefix
    while state.context.simulation_time_seconds < state.spec.horizon:
        state = advance_trade(state)
    assert after.read_text(encoding="utf-8") == save_trade(state)


def test_physical_endpoint_refinement_preserves_product_result(completed):
    fine = run_trade(spec(level=2))
    coarse, refined = summarize_trade(completed), summarize_trade(fine)
    assert coarse["weighted_credit"] == refined["weighted_credit"]
    assert [r["credited_products"] for r in coarse["requests"]] == [r["credited_products"] for r in refined["requests"]]
    assert coarse["phase_seconds"] == refined["phase_seconds"]
    by_time = {tuple(s["time"]): s for s in refined["physical_samples"]}
    assert all(tuple(s["time"]) in by_time for s in coarse["physical_samples"])
    for low in coarse["physical_samples"]:
        high = by_time[tuple(low["time"]) ]
        assert abs(low["energy_wh"]-high["energy_wh"]) <= .001*completed.design.capacity_wh
        assert max(abs(low["temperatures_k"][n]-high["temperatures_k"][n]) for n in low["temperatures_k"]) <= .1
