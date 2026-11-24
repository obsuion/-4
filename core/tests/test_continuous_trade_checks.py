"""Independent evidence auditing must reject semantic damage after rehashing."""

from copy import deepcopy
from fractions import Fraction
import json

import pytest

from examples.v5_continuous_trade_checks import audit_evidence, compare_refinement
from ops_sim.v5.continuous_trade import ContinuousSpec, PERIOD, advance_continuous, start_continuous
from ops_sim.v5.continuous_trade_io import EvidenceStream, verify_evidence


def write_events(path, events):
    with EvidenceStream(path) as stream:
        for event in events:
            stream.append(event)
    verify_evidence(path)
    return path


@pytest.fixture(scope="module")
def streamed_cycle(tmp_path_factory):
    directory = tmp_path_factory.mktemp("continuous-independent-audit")
    state = start_continuous(ContinuousSpec("B8-A2", contact_chunk_seconds=5))
    events = []
    while state.context.simulation_time_seconds < PERIOD:
        state = advance_continuous(state, stop_seconds=PERIOD)
        events.extend(state.last_events)
    path = write_events(directory / "cycle.jsonl", events)
    return path, events, state


def audit(path):
    return audit_evidence(path, initial_energy_wh=344., capacity_wh=688.)


def test_streamed_cycle_audit_recomputes_energy_custody_and_credit(streamed_cycle):
    path, _, state = streamed_cycle
    result = audit(path)
    assert result["status"] == "passed" and result["seconds"] == PERIOD
    assert result["offered_products"] == result["acquired"] == result["completed"] == result["credited"] == 6
    assert result["weighted_credit"] == [12, 1]
    assert result["transmitted_bits"] == result["acquired_bits"] == 6 * 426_241_440
    assert result["partial_records"] == result["onboard_records"] == 0
    assert result["numerical_substeps"] == state.accounting["numerical_substeps"]
    assert max(result["maximum_action_residual_wh"].values()) < 1e-9
    assert abs(result["global_battery_residual_wh"]) <= result["global_roundoff_allowance_wh"]


def test_audit_accepts_real_partial_receipt_without_complete_product_credit(streamed_cycle, tmp_path):
    _, original, _ = streamed_cycle
    index = next(i for i, event in enumerate(original) if event["kind"] == "contact")
    prefix = original[:index + 1]
    contact = prefix[-1]
    assert any(not service["completed"] for service in contact["services"])
    result = audit(write_events(tmp_path / "partial.jsonl", prefix))
    assert result["seconds"] == 3425
    assert result["acquired"] == 6
    assert result["completed"] == result["credited"] == 1
    assert result["partial_records"] == 1 and result["onboard_records"] == 5
    assert result["transmitted_bits"] == 5 * 160_000_000


@pytest.mark.parametrize("tamper,match", [
    ("energy", "energy conservation"),
    ("reset", "reset|continuity"),
    ("before-bits", "prior partial bits"),
    ("bitrate", "bits/rate/time"),
    ("credit", "eligibility.*credit"),
    ("completion", "completion time"),
    ("unpublished", "unpublished request"),
])
def test_rehashed_semantic_damage_fails_independent_audit(streamed_cycle, tmp_path, tamper, match):
    _, original, _ = streamed_cycle
    changed = deepcopy(original)
    physical = next(event for event in changed if "accounting" in event)
    contact = next(event for event in changed if event["kind"] == "contact")
    service = contact["services"][0]
    if tamper == "energy":
        physical["accounting"]["generation_wh"] += .01
    elif tamper == "reset":
        physical["samples"][0]["energy_wh"] += .01
    elif tamper == "before-bits":
        service["before_bits"] = 1
    elif tamper == "bitrate":
        contact["bitrate_bps"] += 1
    elif tamper == "credit":
        service["credited"] = False
    elif tamper == "completion":
        service["completion"][0] += service["completion"][1]
    else:
        changed = [event for event in changed if event["kind"] != "release"]
    path = write_events(tmp_path / (tamper + ".jsonl"), changed)
    # A new valid hash chain does not make a physically inconsistent ledger true.
    assert verify_evidence(path)[0] == len(changed)
    with pytest.raises(ValueError, match=match):
        audit(path)


def test_refinement_identical_files_have_exact_discrete_and_physical_agreement(streamed_cycle):
    path, _, _ = streamed_cycle
    result = compare_refinement(path, path, capacity_wh=688.)
    assert result["status"] == "pilot-screen-passed"
    assert result["exact_discrete_actions_reasons_completions"]
    assert result["first_difference"] is None
    assert result["max_common_sample_energy_difference_wh"] == 0.
    assert all(value == 0. for value in result["max_common_sample_temperature_difference_k"].values())
    assert "no month" in result["scope"]


@pytest.mark.parametrize("quantity,offset", [("energy", 1.), ("temperature", .2)])
def test_refinement_reports_scalar_screen_failure(streamed_cycle, tmp_path, quantity, offset):
    original_path, original, _ = streamed_cycle
    changed = deepcopy(original)
    for event in changed:
        for sample in event.get("samples", ()):
            if quantity == "energy":
                sample["energy_wh"] += offset
            else:
                sample["temperatures_k"]["payload"] += offset
    path = write_events(tmp_path / (quantity + ".jsonl"), changed)
    result = compare_refinement(original_path, path, capacity_wh=688.)
    assert result["status"] == "unresolved-numerical-sensitivity"
    assert not result["scalar_screens_pass"]
    assert result["exact_discrete_actions_reasons_completions"]


def test_refinement_reports_changed_completion_even_when_scalar_screens_pass(streamed_cycle, tmp_path):
    original_path, original, _ = streamed_cycle
    changed = deepcopy(original)
    service = next(event for event in changed if event["kind"] == "contact")["services"][0]
    service["completion"] = [int(Fraction(*service["completion"])) + 1, 1]
    path = write_events(tmp_path / "completion-difference.jsonl", changed)
    result = compare_refinement(original_path, path, capacity_wh=688.)
    assert result["status"] == "unresolved-numerical-sensitivity"
    assert result["scalar_screens_pass"]
    assert not result["exact_discrete_actions_reasons_completions"]
    assert result["first_difference"] is not None


def test_refinement_rejects_truncated_physical_horizon(streamed_cycle, tmp_path):
    original_path, original, _ = streamed_cycle
    path = write_events(tmp_path / "short.jsonl", original[:-1])
    with pytest.raises(ValueError, match="identical complete physical duration"):
        compare_refinement(original_path, path, capacity_wh=688.)


def test_refinement_rejects_invalid_hash_chain(streamed_cycle, tmp_path):
    original_path, _, _ = streamed_cycle
    lines = original_path.read_text(encoding="utf-8").splitlines()
    body = json.loads(lines[0])
    body["digest"] = "f" * 64
    lines[0] = json.dumps(body)
    path = tmp_path / "corrupted.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        compare_refinement(original_path, path, capacity_wh=688.)
