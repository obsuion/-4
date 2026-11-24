"""Coordinator integration, not a direct artificial report.seal test.

The tiny calendar periods are SYNTHETIC_UNIT; their actual physical intervals
are never labelled a month calculation. Endpoint expiry is an actual event.
"""
from dataclasses import replace
from hashlib import sha256

from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot, LifecyclePolicy, canonical
from ops_sim.v5.lifecycle_execution import start_lifecycle, step_lifecycle, scientific_projection
from ops_sim.v5.lifecycle_checkpoint import checkpoint_bytes, make_bindings, restore_checkpoint


def run(root, state=None):
    state = start_lifecycle(root) if state is None else state
    rows = []; events = []
    while state.status == 'ACTIVE':
        previous = state.event_chain
        state, event, row = step_lifecycle(state)
        body = {k: v for k, v in event.items() if k != 'chain'}
        assert event['chain'] == sha256((previous+canonical(body)).encode()).hexdigest()
        events.append(event)
        if row is not None: rows.append(row)
        if 'additional_terminal_row' in event: rows.append(event['additional_terminal_row'])
    return state, events, rows


def test_exact_terminal_calendar_boundary_without_handoff_has_one_covered_row():
    root = LifecycleRoot(make_inputs(wire='weakness'), 1,
                         policy=LifecyclePolicy(month_period_seconds=1),
                         sun_mode='BOUND_SHORT_TABLE_V1')
    state, events, rows = run(root)
    assert state.status == 'COMPLETE' and state.clock == 129
    assert root.month_rows == state.report.state['sealed_count'] == len(rows) == 1
    assert rows[0]['start_seconds'] == 128 and rows[0]['end_seconds'] == 129
    assert rows[0]['seal'] == 'MONTH_BOUNDARY'
    assert 'additional_terminal_row' not in events[-1]
    assert state.report.state['current'] is None


def test_actual_endpoint_expiry_handoff_is_a_named_nonphantom_tail():
    root = LifecycleRoot(make_inputs(wire='weakness'), 600,
                         policy=LifecyclePolicy(month_period_seconds=600),
                         sun_mode='BOUND_SHORT_TABLE_V1')
    state, events, rows = run(root)
    assert state.clock == 728 and state.status == 'COMPLETE'
    assert len(rows) == 2 and state.report.state['sealed_count'] == 2
    assert rows[0]['seal'] == 'MONTH_BOUNDARY'
    tail = rows[1]
    assert tail['seal'] == 'ENDPOINT_EVENT_TAIL'
    assert tail['start_seconds'] == tail['end_seconds'] == 728
    assert tail['expired'] == 1 and tail['credits'] == tail['transitions'] == 0
    assert events[-1]['expired_count'] == 1
    assert state.report.summary()['totals']['expired'] == 1


def test_partial_terminal_is_one_positive_duration_row():
    root = LifecycleRoot(make_inputs(wire='weakness'), 2,
                         policy=LifecyclePolicy(month_period_seconds=3),
                         sun_mode='BOUND_SHORT_TABLE_V1')
    state, _, rows = run(root)
    assert state.status == 'COMPLETE' and state.clock == 130
    assert len(rows) == state.report.state['sealed_count'] == 1
    assert rows[0]['seal'] == 'PARTIAL_TERMINAL'
    assert rows[0]['end_seconds']-rows[0]['start_seconds'] == 2


def test_exact_terminal_calendar_seal_survives_direct_checkpoint_resume():
    root = LifecycleRoot(make_inputs(wire='weakness'), 3,
                         policy=LifecyclePolicy(quiet_step_seconds=1,
                             detailed_step_seconds=1, month_period_seconds=3),
                         sun_mode='BOUND_SHORT_TABLE_V1')
    state = start_lifecycle(root)
    state, _, row = step_lifecycle(state)
    assert row is None and state.clock == 129
    bindings = make_bindings(root, state.clock)
    raw = checkpoint_bytes(state, bindings)
    restored, proof = restore_checkpoint(raw, root, sha256(raw).hexdigest(), bindings)
    uninterrupted, _, rows = run(root, state)
    resumed, _, resumed_rows = run(root, restored)
    assert scientific_projection(uninterrupted) == scientific_projection(resumed)
    assert rows == resumed_rows and len(rows) == 1
    assert rows[0]['seal'] == 'MONTH_BOUNDARY'
    assert proof['restored_clock'] == 129
