"""Fresh-process, exact restart comparisons for the bounded V5 script."""

import json
import os
import subprocess
import sys

import pytest

from examples.v5_experiment_bundle_demo import ROOT, build_demo_state, summarize
from ops_sim.v5.continuation import advance_continuation
from ops_sim.v5.experiment_bundle import create_bundle, experiment_input_digest


def process(*args):
    result = subprocess.run(
        [sys.executable, "-B", *args], cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True, encoding="utf-8", capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def trajectory():
    states = [build_demo_state()]
    for _ in states[0].program.actions:
        states.append(advance_continuation(states[-1]))
    return states


@pytest.mark.parametrize("boundary", [1, 2, 3, 5])
def test_json_only_restart_in_fresh_process_has_exact_complete_outcome(tmp_path, trajectory, boundary):
    state = trajectory[boundary]
    assert state.memory.executed_action_ids
    assert state.memory.previous_execution != state.program.initial_previous_execution
    if boundary in (2, 3, 5):
        progress = state.context.ground_data_delivery_state.partial_transfers
        assert len(progress) == 1
        assert progress[0].transmitted_equivalent_bits == 9000.0
    saved = tmp_path / "saved.json"
    output = tmp_path / "resumed.json"
    saved.write_text(create_bundle(state, repository_root=ROOT).to_json(), encoding="utf-8")
    # Only serialized data crosses the process boundary. Fail if the reader tries
    # to regenerate origin state/memory from the demo fixture rather than the file.
    process("-c", "\n".join([
        "import sys",
        "from examples import v5_experiment_bundle_demo as demo",
        "def forbidden(): raise AssertionError('origin fixture called during restart')",
        "demo.build_demo_state = forbidden",
        "demo.main(['--resume', sys.argv[1], '--output', sys.argv[2]])",
    ]), str(saved), str(output))
    resumed = json.loads(output.read_text(encoding="utf-8"))
    # Full checkpoint includes physical state, knowledge, mission/controller,
    # diagnostics, custody and delivery progress; memory and choices are explicit.
    assert resumed == summarize(trajectory[-1])
    assert resumed["decisions"] == [
        "image-a", "partial-a", "image-b", "complete-a", "partial-b", "complete-b",
    ]
    assert resumed["metrics"] == {
        "clock_seconds": 238, "completed_steps": 6,
        "delivered_equivalent_bits": 24000.0,
        "onboard_equivalent_bits": 0, "partial_transfers": 0,
    }


def test_public_cli_saves_and_resumes_from_partial_transfer(tmp_path, trajectory):
    saved, partial, complete = (tmp_path / name for name in ("bundle.json", "partial.json", "complete.json"))
    process("-m", "examples.v5_experiment_bundle_demo", "--stop-after", "2",
            "--bundle-output", str(saved), "--output", str(partial))
    process("-m", "examples.v5_experiment_bundle_demo", "--resume", str(saved), "--output", str(complete))
    assert json.loads(partial.read_text(encoding="utf-8")) == summarize(trajectory[2])
    assert json.loads(complete.read_text(encoding="utf-8")) == summarize(trajectory[-1])


def test_content_identity_is_process_independent_with_a_different_hash_seed():
    state = build_demo_state()
    code = "\n".join([
        "from examples.v5_experiment_bundle_demo import build_demo_state",
        "from ops_sim.v5.experiment_bundle import experiment_input_digest",
        "s = build_demo_state()",
        "print(experiment_input_digest(s.context.inputs, s.program))",
    ])
    result = subprocess.run(
        [sys.executable, "-B", "-c", code], cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "412"},
        text=True, encoding="utf-8", capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == experiment_input_digest(state.context.inputs, state.program)


def test_existing_uncoupled_downlink_and_nontrivial_knowledge_are_reported_honestly(trajectory):
    before = trajectory[1].context
    after = trajectory[2].context
    assert after.simulation_time_seconds == before.simulation_time_seconds + 23
    assert after.spacecraft_state == before.spacecraft_state
    assert after.ground_knowledge_state == before.ground_knowledge_state
    assert after.ground_knowledge_state.latest_telemetry.sampled_at_seconds == 90
    assert after.ground_data_delivery_state != before.ground_data_delivery_state
    assert trajectory[0].context.spacecraft_state.battery != before.spacecraft_state.battery


def test_mapping_construction_order_does_not_change_bundle_json(trajectory):
    original = create_bundle(trajectory[2], repository_root=ROOT)
    from ops_sim.v5.experiment_bundle import ExperimentBundle
    def reversed_maps(value):
        if isinstance(value, dict):
            return {key: reversed_maps(value[key]) for key in reversed(value)}
        if isinstance(value, list):
            return [reversed_maps(item) for item in value]
        return value
    reordered = ExperimentBundle.from_json(json.dumps(reversed_maps(json.loads(original.to_json()))))
    assert reordered.to_json() == original.to_json()
