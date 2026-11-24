"""Streaming-chain integrity and no-replay continuous checkpoint boundaries."""

from dataclasses import replace
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ops_sim.v5 import continuous_trade_io as io


def _event(index):
    return {"phase": "hold", "start_seconds": index * 10, "end_seconds": (index + 1) * 10,
            "accounting": {"generation_wh": .125 * index, "requested_load_wh": .5},
            "temperatures_k": {"payload": 293.15 + index}, "record": None}


def _stream(path, count=3):
    with io.EvidenceStream(path) as stream:
        for index in range(count):
            stream.append(_event(index))
        cursor = stream.event_count, stream.event_digest
    return cursor


def test_stream_hashes_can_be_recomputed_independently_and_resumed(tmp_path):
    path = tmp_path / "events.jsonl"
    count, head = _stream(path)
    previous = "0" * 64
    energy = 0.
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        event = json.loads(line)
        digest = event.pop("digest")
        assert event["event_count"] == index
        assert event["previous_digest"] == previous
        body = json.dumps(event, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        assert hashlib.sha256(("task05fa-event-v1\n" + body).encode("utf-8")).hexdigest() == digest
        energy += event["event"]["accounting"]["generation_wh"]
        previous = digest
    assert (count, head) == (3, previous)
    assert energy == .375
    with io.EvidenceStream(path, event_count=count, event_digest=head, resume=True) as stream:
        final = stream.append(_event(3))
        stream.flush(durable=True)
    assert io.verify_evidence(path, event_count=final[0], event_digest=final[1]) == final


@pytest.mark.parametrize("change", ["content", "reorder", "duplicate", "missing", "truncated", "extra", "duplicate-key"])
def test_corrupt_missing_or_extra_evidence_cannot_resume(tmp_path, change):
    path = tmp_path / "events.jsonl"
    count, head = _stream(path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if change == "content":
        lines[1] = lines[1].replace('"requested_load_wh":0.5', '"requested_load_wh":5.0')
    elif change == "reorder":
        lines[0], lines[1] = lines[1], lines[0]
    elif change == "duplicate":
        lines.insert(1, lines[0])
    elif change == "missing":
        lines.pop()
    elif change == "truncated":
        lines[-1] = lines[-1][:-1]
    elif change == "extra":
        with io.EvidenceStream(path, event_count=count, event_digest=head, resume=True) as stream:
            stream.append(_event(3))
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines[0] = lines[0].rstrip()[:-1] + ',"version":1}\n'
    path.write_text("".join(lines), encoding="utf-8", newline="")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        io.EvidenceStream(path, event_count=count, event_digest=head, resume=True)
    assert path.read_bytes() == before


def test_existing_evidence_is_never_silently_overwritten(tmp_path):
    path = tmp_path / "events.jsonl"
    _stream(path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        io.EvidenceStream(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("count,digest", [(True, "0" * 64), (-1, "0" * 64), (1, "0" * 64), (0, "a" * 64)])
def test_invalid_event_cursor_rejects_before_file_creation(tmp_path, count, digest):
    path = tmp_path / "events.jsonl"
    with pytest.raises(ValueError):
        io.EvidenceStream(path, event_count=count, event_digest=digest)
    assert not path.exists()


def test_nonfinite_event_rejects_without_advancing_cursor(tmp_path):
    path = tmp_path / "events.jsonl"
    with io.EvidenceStream(path) as stream:
        with pytest.raises(ValueError):
            stream.append({"energy_wh": float("nan")})
        assert (stream.event_count, stream.event_digest) == (0, "0" * 64)
    assert path.read_bytes() == b""


def _origin():
    from ops_sim.v5.continuous_trade import ContinuousSpec, start_continuous
    return start_continuous(ContinuousSpec("B8-A2"))


def _rehash(payload):
    payload.pop("digest")
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    payload["digest"] = hashlib.sha256(("task05fa-continuation-v1\n" + body).encode("utf-8")).hexdigest()
    return json.dumps(payload)


def test_origin_roundtrip_has_bounded_input_validation_and_does_not_replay(monkeypatch):
    import ops_sim.v5.continuous_trade as coordinator
    state = _origin()
    text = io.save_continuous(state)
    calls = []
    original = coordinator.start_continuous
    def build(spec):
        calls.append(spec)
        return original(spec)
    monkeypatch.setattr(coordinator, "start_continuous", build)
    monkeypatch.setattr(coordinator, "advance_continuous", lambda *a, **k: pytest.fail("restore replayed history"))
    restored = io.restore_continuous(text)
    # One reconstruction plus the separate full-boundary binding check.
    assert len(calls) == 2
    assert restored.context is not state.context
    assert restored.last_events == ()
    assert io.save_continuous(restored) == text


@pytest.mark.parametrize("field", ["runtime", "source_fingerprint", "input_digest"])
def test_valid_rehashed_envelope_still_rejects_wrong_runtime_source_or_inputs(field):
    payload = json.loads(io.save_continuous(_origin()))
    if field == "input_digest":
        payload[field] = "a" * 64
    else:
        payload[field] = {"foreign": "replacement"}
    with pytest.raises(ValueError, match="binding mismatch"):
        io.restore_continuous(_rehash(payload))


def test_continuation_rejects_duplicate_keys_and_unbound_checkpoint_mutation():
    text = io.save_continuous(_origin())
    with pytest.raises(ValueError, match="duplicate"):
        io.restore_continuous(text[:-1] + ',"version":1}')
    payload = json.loads(text)
    payload["state"]["checkpoint"]["simulation_time_seconds"] = 1
    with pytest.raises(ValueError, match="digest mismatch"):
        io.restore_continuous(json.dumps(payload))


def test_atomic_checkpoint_matches_flushed_evidence_and_excludes_transient_history(tmp_path):
    state = _origin()
    path = tmp_path / "events.jsonl"
    with io.EvidenceStream(path) as stream:
        io.write_checkpoint(tmp_path / "state.json", state, evidence=stream)
        saved = (tmp_path / "state.json").read_bytes()
        stream.append(_event(0))
        with pytest.raises(ValueError, match="cursor differs"):
            io.write_checkpoint(tmp_path / "state.json", state, evidence=stream)
        assert (tmp_path / "state.json").read_bytes() == saved
    payload = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "last_events" not in payload["state"]
    assert "events" not in payload["state"]
    assert not tuple(tmp_path.glob("*.tmp"))


def test_fresh_process_origin_restore_is_exact(tmp_path):
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    before.write_text(io.save_continuous(_origin()), encoding="utf-8")
    code = ("from pathlib import Path; import sys; "
            "from ops_sim.v5.continuous_trade_io import restore_continuous,save_continuous; "
            "s=restore_continuous(Path(sys.argv[1]).read_text(encoding='utf-8')); "
            "Path(sys.argv[2]).write_text(save_continuous(s),encoding='utf-8')")
    result = subprocess.run([sys.executable, "-B", "-c", code, str(before), str(after)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"), timeout=90)
    (tmp_path / "fresh-process.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert before.read_bytes() == after.read_bytes()


@pytest.mark.parametrize("key,value", [
    ("credited", True), ("completed", -1), ("numerical_substeps", 1.),
    ("weighted_credit", float("inf")), ("minimum_energy_wh", -1.),
    ("acquired_bits", 1), ("transmitted_bits", 1),
    ("phase_seconds", {"hold": 1}), ("energies", {"unknown": 0.}),
    ("diagnostic_energy_wh", {"solar_source_wh": -1.}),
    ("minimum_temperatures_k", {"invented": 293.15}),
])
def test_persistence_rejects_invalid_accounting_and_custody_totals(key, value):
    state = _origin()
    accounting = deepcopy(state.accounting)
    accounting[key] = value
    with pytest.raises(ValueError):
        io.save_continuous(replace(state, accounting=accounting))


def test_signed_actuator_heat_transfer_is_admitted_as_a_diagnostic():
    state = _origin()
    accounting = deepcopy(state.accounting)
    accounting["diagnostic_energy_wh"]["actuator_heat_adjustment_wh"] = -1e-15
    io.validate_accounting(replace(state, accounting=accounting))


@pytest.fixture(scope="module")
def physical_partial(tmp_path_factory):
    from ops_sim.v5.continuous_trade import ContinuousSpec, start_continuous, advance_continuous
    directory = tmp_path_factory.mktemp("physical-partial")
    evidence = directory / "prefix.jsonl"
    state = start_continuous(ContinuousSpec("B8-A2", contact_chunk_seconds=1))
    with io.EvidenceStream(evidence) as stream:
        for _ in range(8):
            state = advance_continuous(state)
            count, digest = stream.append_events(state.last_events)
            state = replace(state, event_count=count, event_digest=digest)
            if state.context.ground_data_delivery_state.partial_transfers:
                break
    assert state.context.ground_data_delivery_state.partial_transfers
    assert state.context.spacecraft_state.data_storage.stored_records
    assert state.accounting["transmitted_bits"] > 0
    io.validate_accounting(state)
    return state, evidence


def test_real_partial_downlink_roundtrip_preserves_all_live_truth_without_replay(physical_partial, monkeypatch):
    import ops_sim.v5.continuous_trade as coordinator
    state, evidence = physical_partial
    text = io.save_continuous(state)
    monkeypatch.setattr(coordinator, "advance_continuous", lambda *a, **k: pytest.fail("physical replay"))
    restored = io.restore_continuous(text)
    assert restored.context == state.context
    assert restored.accounting == state.accounting
    assert restored.last_events == ()
    assert io.verify_evidence(evidence, event_count=restored.event_count, event_digest=restored.event_digest)
    assert io.save_continuous(restored) == text


def test_unstreamed_physical_batch_cannot_be_checkpointed(physical_partial):
    from ops_sim.v5.continuous_trade import advance_continuous
    state, _ = physical_partial
    next_state = advance_continuous(state)
    assert next_state.events_emitted > next_state.event_count
    with pytest.raises(ValueError, match="must be streamed"):
        io.save_continuous(next_state)


def test_fresh_process_partial_downlink_resume_matches_uninterrupted_exactly(physical_partial, tmp_path):
    from ops_sim.v5.continuous_trade import advance_continuous
    state, prefix_evidence = physical_partial
    before, after = tmp_path / "partial.json", tmp_path / "fresh-final.json"
    fresh_events, direct_events = tmp_path / "fresh.jsonl", tmp_path / "direct.jsonl"
    before.write_text(io.save_continuous(state), encoding="utf-8")
    fresh_events.write_bytes(prefix_evidence.read_bytes())
    direct_events.write_bytes(prefix_evidence.read_bytes())
    code = """
from dataclasses import replace
from pathlib import Path
import sys
from ops_sim.v5.continuous_trade import advance_continuous
from ops_sim.v5.continuous_trade_io import restore_continuous, EvidenceStream, write_checkpoint
s = restore_continuous(Path(sys.argv[1]).read_text(encoding='utf-8'))
with EvidenceStream(sys.argv[3], event_count=s.event_count, event_digest=s.event_digest, resume=True) as stream:
    s = advance_continuous(s)
    count, digest = stream.append_events(s.last_events)
    s = replace(s, event_count=count, event_digest=digest)
    write_checkpoint(sys.argv[2], s, evidence=stream)
"""
    result = subprocess.run([sys.executable, "-B", "-c", code, str(before), str(after), str(fresh_events)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"), timeout=90)
    (tmp_path / "fresh-partial-process.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    with io.EvidenceStream(direct_events, event_count=state.event_count, event_digest=state.event_digest, resume=True) as stream:
        direct = advance_continuous(state)
        count, digest = stream.append_events(direct.last_events)
        direct = replace(direct, event_count=count, event_digest=digest)
    assert fresh_events.read_bytes() == direct_events.read_bytes()
    assert after.read_text(encoding="utf-8") == io.save_continuous(direct)
