"""Synthetic anonymous-pipe capture; no worker or scientific model is run."""
import os
import time
import pytest
from ops_sim.v5 import lifetime_bounded_logs as logs


def test_aggregate_log_prefix_has_prospective_disk_bound(tmp_path):
    capture = logs.BoundedLogPipes(tmp_path, maximum_bytes=64)
    os.write(capture.stdout.fileno(), b'out prefix')
    os.write(capture.stderr.fileno(), b'err prefix')
    capture.close_parent_writers()
    receipt = capture.finish(time.perf_counter() + 2)
    assert receipt['readers_joined'] and not receipt['truncated']
    assert (tmp_path/'stdout.log').read_bytes() == b'out prefix'
    assert (tmp_path/'stderr.log').read_bytes() == b'err prefix'
    assert receipt['bytes_written'] == 20


def test_cap_keeps_draining_pipe_and_never_writes_suffix(tmp_path):
    capture = logs.BoundedLogPipes(tmp_path, maximum_bytes=64)
    payload = b'x' * (3 * capture.BLOCK_BYTES)
    offset = 0
    while offset < len(payload):
        offset += os.write(capture.stdout.fileno(), payload[offset:])
    capture.close_parent_writers()
    with pytest.raises(ValueError, match='log cap'):
        capture.finish(time.perf_counter() + 2)
    receipt = capture.snapshot()
    assert receipt['readers_joined'] and receipt['truncated']
    assert receipt['bytes_received'] == len(payload)
    assert receipt['bytes_discarded'] == len(payload) - 64
    assert sum((tmp_path/leaf).stat().st_size for leaf in ('stdout.log','stderr.log')) == 64


def test_log_sync_failure_is_explicit_and_disk_remains_bounded(tmp_path, monkeypatch):
    def fail(fd, **kwargs):raise OSError('injected sync failure')
    monkeypatch.setattr(logs, 'fsync', fail)
    capture = logs.BoundedLogPipes(tmp_path, maximum_bytes=64)
    os.write(capture.stderr.fileno(), b'diagnostic')
    capture.close_parent_writers()
    with pytest.raises(OSError, match='reader failure'):
        capture.finish(time.perf_counter() + 2)
    assert capture.snapshot()['readers_joined']
    assert sum((tmp_path/leaf).stat().st_size for leaf in ('stdout.log','stderr.log')) <= 64


def test_retained_writer_refuses_same_cleanup_deadline(tmp_path):
    capture = logs.BoundedLogPipes(tmp_path, maximum_bytes=64)
    retained = os.dup(capture.stdout.fileno())
    try:
        capture.close_parent_writers()
        with pytest.raises(TimeoutError, match='same owned cleanup deadline'):
            capture.finish(time.perf_counter() + .03)
        assert not capture.snapshot()['readers_joined']
        assert any(error['operation']=='JOIN_DEADLINE' for error in capture.snapshot()['errors'])
    finally:
        os.close(retained)
        for thread in capture._threads:thread.join(.5)


def test_already_finished_reader_cannot_hide_completion_after_deadline(tmp_path):
    capture = logs.BoundedLogPipes(tmp_path, maximum_bytes=64)
    capture.close_parent_writers()
    receipt = capture.finish(time.perf_counter() + 2)
    assert receipt['readers_joined']
    deadline = max(receipt['reader_completion_monotonic']) - 1
    with pytest.raises(TimeoutError, match='same owned cleanup deadline'):
        capture.finish(deadline)
    assert not capture.snapshot()['readers_joined']
