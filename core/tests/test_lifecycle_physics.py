"""Bounded actual assembly/pose/EPS/thermal/acquisition/contact adapter checks.

The reference source below is TEST ONLY and short-domain: accepted old forcing
and numerical owners are reused explicitly.  Production long execution uses
AcquiredLifecycleWorld and its separately bounded sliding orbit provider.
"""
from dataclasses import asdict, fields, replace
from fractions import Fraction as Q
from types import SimpleNamespace
import pytest

from examples.m5_rolling_mission_demo import make_inputs
from ops_sim.v5 import long_mission as leaf
from ops_sim.v5.assembly_attitude_3d import BodyAttitude3D
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.lifecycle_physics import (
    LifecyclePhysicsLimits, LifecyclePhysicalModel, LifecyclePhysicalState,
    LifecycleConstructionLimits, LifecycleConstructionWork, LifecycleHarnessWork,
    start_lifecycle_physical, execute_lifecycle_action, resume_pending_lifecycle_action,
    retire_lifecycle_products, assess_lifecycle_product)
from ops_sim.v5.rolling_cache import PublicCacheBank, CumulativeWork
from ops_sim.v5.rolling_physics import start_physical, advance_physical
from ops_sim.v5.harness_hardware import compile_effective_hardware


class ShortReferenceSource:
    """No fake physics: only call accepted short geometry and orientation."""
    def __init__(self, model, provider, source, work):
        self.source = source
        self.stub = SimpleNamespace(inputs=model, nominal_provider=provider, runtime_work=work)
    def guard(self): return self.source.guard()
    def schedule(self, a, b): return self.source.schedule(a, b)
    def observations(self, entry, a, b, sampling):
        assert sampling == self.stub.inputs.sampling
        return leaf._observations(self.stub, entry, a, b)
    def orientation_inputs(self, hardware, time, quaternion):
        return leaf._orientation_inputs(self.stub, hardware, time, quaternion)


@pytest.fixture(scope='module')
def root():
    return make_inputs()


def _start(root, *, limits=None):
    model = root.model
    work = leaf.RuntimeWork()
    bank = PublicCacheBank(model, CumulativeWork(), root.quotas, 'ACTUAL_PUBLIC_MODEL')
    provider, source = bank.bind(work)
    context = root.initial_checkpoint.restore(model.simulation_inputs)
    attitude = BodyAttitude3D(model.assembly.body_frame_id,
        model.environment.trajectory.initial_state.position.frame, Q(128), root.initial_quaternion, Q(128))
    physical = LifecyclePhysicalModel(model, model.environment,
                                      LifecyclePhysicsLimits() if limits is None else limits)
    return start_lifecycle_physical(physical, context, attitude,
        tuple(r.product for r in root.requests), provider,
        ShortReferenceSource(model, provider, source, work), runtime_work=work)


@pytest.mark.parametrize('change', [dict(max_interval_seconds=True), dict(max_active_products=33),
    dict(max_action_cells=513), dict(contact_integration_level=5), dict(max_document_bytes=65*2**20),
    dict(max_physical_substeps=0), dict(method='old-limits')])
def test_new_finite_physical_admission(change):
    with pytest.raises(ValueError): replace(LifecyclePhysicsLimits(), **change)


def test_cumulative_line_reservation_refusal_never_refunds():
    limits = LifecycleConstructionLimits(16, 2, 65536)
    work = LifecycleConstructionWork()
    work.reserve_lines(8, limits)
    work.line_calls_returned = 8
    work.reserve_lines(8, limits)
    work.line_calls_refused = 1
    with pytest.raises(ValueError, match='LINE_QUOTA'): work.reserve_lines(8, limits)
    assert work.line_calls_reserved == 16 and work.line_calls_returned == 8 and work.line_calls_refused == 1
    work.reserve_compile(limits); work.reserve_compile(limits)
    with pytest.raises(ValueError, match='COMPILATION_QUOTA'): work.reserve_compile(limits)
    assert work.compilation_calls == 2 and work.control_units == 65536


def test_harness_accounting_cumulative_not_legacy_window(root):
    policy = root.model.augmentation.policy
    work = LifecycleHarnessWork(2, 2*policy.control_units_per_compile)
    work.reserve_compile(policy); work.reserve_compile(policy)
    with pytest.raises(ValueError, match='HARNESS_COMPILATION_QUOTA'): work.reserve_compile(policy)
    assert work.compilation_calls == 2 and work.control_reserved_units == 2*policy.control_units_per_compile


def test_new_state_has_only_future_data_and_full_effective_tensor(root):
    state = _start(root)
    assert not {'commands', 'outcomes', 'decisions', 'forecasts'} & {f.name for f in fields(LifecyclePhysicalState)}
    model = root.model
    expected = compile_effective_hardware(model.assembly, model.capabilities, model.actuator,
                                           model.configuration, model.augmentation)
    assert state.harness.hardware == expected
    assert len(state.harness.hardware.tensor_exact) == 3
    assert all(len(row) == 3 for row in state.harness.hardware.tensor_exact)
    assert state.harness.hardware.camera_body_axis == expected.camera_body_axis
    assert state.harness.hardware.panel_body_normal == expected.panel_body_normal


def test_same_detailed_policy_explicit_point_matches_accepted_leaf_reference(root):
    state = _start(root)
    # B52 deliberately uses a <=2-second detailed physical maximum. The
    # historical default used 30 seconds between source/slew cuts. Compare
    # both unchanged leaf implementations under the SAME numerical policy;
    # do not disguise different partition/ageing roundoff as exact replay.
    old_model = replace(root.model, limits=replace(root.model.limits,
        max_interval_seconds=state.inputs.limits.detailed_interval_seconds))
    old_context = root.initial_checkpoint.restore(old_model.simulation_inputs)
    old_bank = PublicCacheBank(old_model, CumulativeWork(), root.quotas, 'ACTUAL_PUBLIC_MODEL')
    old = start_physical(old_model, old_context, state.attitude, state.inputs.products, old_bank, 'short-detailed-reference')
    action = leaf.LongMissionAction('point-reference', 'POINT', 'target')
    actual, outcome = execute_lifecycle_action(state, action)
    old = advance_physical(old, action)
    reference = old.outcomes[-1]
    assert outcome.status == reference.status == 'completed'
    assert actual.attitude == old.attitude
    assert tuple((c.start_seconds, c.end_seconds) for c in outcome.cuts) == tuple((c.start_seconds, c.end_seconds) for c in reference.cuts)
    assert CheckpointState.from_context(actual.context).to_dict() == CheckpointState.from_context(old.context).to_dict()
    assert outcome.cuts == reference.cuts and outcome.accounting == reference.accounting
    assert actual.harness.hardware.tensor_exact == old.harness.hardware.tensor_exact


def test_pending_point_carries_original_slew_and_does_not_replan(root):
    state = _start(root)
    state, first = execute_lifecycle_action(state, leaf.LongMissionAction('point-cut', 'POINT', 'target'), stop_at_seconds=130)
    assert first.status == 'partial' and state.pending.kind == 'POINT'
    pending = state.pending
    assert state.context.simulation_time_seconds == 130 and state.completed_actions == 0
    compiles = state.harness.work.compilation_calls
    energy = state.context.spacecraft_state.battery.energy_wh
    state, final = resume_pending_lifecycle_action(state)
    assert final.status == 'completed' and state.pending is None and state.completed_actions == 1
    assert state.context.simulation_time_seconds == pending.end_seconds
    assert final.slew is pending.slew and state.harness.work.compilation_calls == compiles
    assert state.attitude.quaternion == pending.slew.quaternion_at(Q(pending.end_seconds-pending.origin_seconds))
    assert state.context.spacecraft_state.battery.energy_wh != 80. or energy != 80.
    assert first.cuts[0].kinetic_start_exact_j == 0 and final.cuts[-1].kinetic_end_exact_j == 0
    with pytest.raises(ValueError, match='no pending'): resume_pending_lifecycle_action(state)


def test_refused_capture_keeps_context_and_spent_work(root):
    state = _start(root)
    checkpoint = CheckpointState.from_context(state.context).to_dict()
    state, outcome = execute_lifecycle_action(state, leaf.LongMissionAction('unpointed', 'CAPTURE', 'target', 4, product_id='b47-medium'))
    assert outcome.status == 'refused' and not state.acquisitions
    assert CheckpointState.from_context(state.context).to_dict() == checkpoint
    assert state.runtime_work.spatial_reserved_units >= 65536 and state.completed_actions == 1


def test_prospective_substep_quota_retains_paid_work_and_last_context(root):
    state = _start(root, limits=replace(LifecyclePhysicsLimits(), max_physical_substeps=1))
    before = CheckpointState.from_context(state.context).to_dict()
    with pytest.raises(ValueError, match='CUMULATIVE_RUNTIME_QUOTA_EXHAUSTED:physical_reserved_calls'):
        execute_lifecycle_action(state, leaf.LongMissionAction('over-budget-point', 'POINT', 'target'))
    assert CheckpointState.from_context(state.context).to_dict() == before
    assert state.runtime_work.spatial_reserved_units > 65536
    assert state.runtime_work.physical_reserved_calls == 0
    assert state.harness.work.compilation_calls == 2
    assert state.completed_actions == 0 and state.pending is None


def _capture_one(root):
    state = _start(root)
    state, point = execute_lifecycle_action(state, leaf.LongMissionAction('paid-point', 'POINT', 'target'))
    assert point.status == 'completed'
    state, capture = execute_lifecycle_action(state, leaf.LongMissionAction('paid-capture', 'CAPTURE', 'target', 4, product_id='b47-medium'))
    assert capture.status == 'completed'
    return state


def test_actual_partial_contact_and_compact_receipt_then_accounted_retirement(root):
    state = _capture_one(root)
    state, _ = execute_lifecycle_action(state, leaf.LongMissionAction('wait-contact', 'HOLD_UNTIL', until_seconds=160))
    state, short = execute_lifecycle_action(state, leaf.LongMissionAction('one-second', 'CONTACT', 'station', 1))
    assert short.status == 'completed'
    assert state.context.ground_data_delivery_state.partial_transfers
    partial = state.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits
    rate = int(state.inputs.simulation_inputs.spacecraft_configuration.communications.nominal_downlink_data_rate_bps.value)
    assert partial == rate
    assert not state.receipts
    state, _ = execute_lifecycle_action(state, leaf.LongMissionAction('wait-second', 'HOLD_UNTIL', until_seconds=180))
    state, first = execute_lifecycle_action(state, leaf.LongMissionAction('split-contact', 'CONTACT', 'station', 20), stop_at_seconds=181)
    assert first.status == 'partial' and state.pending.kind == 'CONTACT'
    assert state.consumed_through_seconds == 181
    state, last = resume_pending_lifecycle_action(state)
    assert last.status == 'completed' and state.consumed_through_seconds == 200
    assert len(state.receipts) == 1 and not state.context.ground_data_delivery_state.partial_transfers
    medium = next(p for p in state.inputs.products if p.request.request_id.value == 'b47-medium')
    assessed = assess_lifecycle_product(state, medium)
    assert assessed.status == 'credited' and Q(181) < assessed.completion_time_seconds <= 200
    work_before = asdict(state.runtime_work)
    with pytest.raises(ValueError, match='unreported'): retire_lifecycle_products(state, ('b47-medium',), reported_through_seconds=181)
    state, retired = retire_lifecycle_products(state, ('b47-medium',), reported_through_seconds=200)
    assert retired and not state.receipts and not state.acquisitions
    assert not state.context.ground_data_delivery_state.completed_deliveries
    assert asdict(state.runtime_work) == work_before
    assert state.consumed_through_seconds == 200 and state.reported_through_seconds == 200


def test_retirement_does_not_drop_pending_or_change_frontier_on_error(root):
    state = _start(root)
    with pytest.raises(ValueError, match='pending product'): retire_lifecycle_products(state, ('b47-medium',), reported_through_seconds=128)
    assert len(state.inputs.products) == 3 and state.reported_through_seconds == 128
    with pytest.raises(ValueError, match='unknown'): retire_lifecycle_products(state, ('never-offered',), reported_through_seconds=128)
