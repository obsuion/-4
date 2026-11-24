"""B53 local-error, paid-work, exact-boundary and real-leaf compatibility gates."""
from copy import deepcopy
from dataclasses import dataclass, replace, asdict
from fractions import Fraction as Q
from math import exp
from types import SimpleNamespace
import pytest

from ops_sim.v5.lifecycle_quiet import (QuietIntegrationPolicy, QuietControllerState,
    QuietWork, QuietSample, QuietTrial, QuietTrialRefusal, integrate_quiet_hold,
    quiet_error_norm)


@dataclass
class ScalarState:
    temperature: float = 300.
    energy: float = 80.


def values(state):
    return (('temperature:bus', state.temperature), ('energy_wh', state.energy))


def scalar_step(*, rate=.001, regime=lambda a, b: ('steady',), near=False,
                fail=None, calls=None):
    def step(state, a, b):
        if calls is not None: calls.append((a, b))
        if fail is not None: fail(state, a, b)
        dt = float(b-a)
        state.temperature += -rate*(state.temperature-280.)*dt
        state.energy += .01*dt
        sample = QuietSample(values(state), (('served_load_wh', .01*dt),),
                             regime(a, b), near)
        return QuietTrial(state, (a, b, state.temperature), sample)
    return step


def solve(state=None, *, start=0, end=60, policy=None, controller=None, work=None, step=None):
    p = QuietIntegrationPolicy() if policy is None else policy
    w = QuietWork() if work is None else work
    c = QuietControllerState(Q(start), p.maximum_macro_seconds) if controller is None else controller
    s = ScalarState() if state is None else state
    return integrate_quiet_hold(s, Q(start), Q(end), policy=p, controller=c, work=w,
        clone_context=deepcopy, state_values=values, step=scalar_step() if step is None else step), w


@pytest.mark.parametrize('change', [dict(maximum_macro_seconds=121), dict(detailed_seconds=3),
    dict(minimum_macro_seconds=3), dict(relative_tolerance=True),
    dict(absolute_temperature_k=float('nan')), dict(absolute_retention=0.),
    dict(max_total_leaf_calls=False), dict(method='unversioned')])
def test_strict_explicit_policy_rejects_invalid_values(change):
    with pytest.raises(ValueError): replace(QuietIntegrationPolicy(), **change)


class HostileText(str):
    def __eq__(self, other):
        raise AssertionError('hostile text equality must not be invoked')


class HostileEquality:
    def __eq__(self, other):
        raise AssertionError('hostile object equality must not be invoked')


@pytest.mark.parametrize('tag', [HostileText('B53_PAID_QUIET_STEP_DOUBLING_V1'), HostileEquality()])
def test_direct_policy_method_requires_builtin_text_before_equality(tag):
    with pytest.raises(ValueError): replace(QuietIntegrationPolicy(), method=tag)


@pytest.mark.parametrize('name,value', [
    ('phase', HostileText('INITIAL')), ('phase', HostileEquality()),
    ('method', HostileText('B53_PAID_QUIET_STEP_DOUBLING_V1')), ('method', HostileEquality())])
def test_direct_controller_tags_require_builtin_text_before_equality(name, value):
    controller = replace(QuietControllerState(Q(0), 60), **{name:value})
    with pytest.raises(ValueError): controller.validate(QuietIntegrationPolicy(), clock=0)


@pytest.mark.parametrize('kind', ['unknown', False, HostileText('full_trial'), HostileEquality()])
def test_invalid_reservation_kind_is_atomic_and_never_invokes_hostile_equality(kind):
    work = QuietWork(); before = asdict(work)
    with pytest.raises(ValueError): work.reserve(kind, QuietIntegrationPolicy())
    assert asdict(work) == before


def test_linear_rates_accept_two_half_path_and_pay_three_calls():
    original = ScalarState()
    result, work = solve(original, step=scalar_step(rate=0.))
    assert original == ScalarState()
    assert result.context.energy == pytest.approx(80.6, abs=1.e-13)
    assert [(a, b) for a, b, _ in result.cuts] == [(Q(0), Q(30)), (Q(30), Q(60))]
    assert work.reserved_leaf_calls == work.returned_leaf_calls == 3
    assert work.full_trial_calls == 1 and work.half_trial_calls == 2
    assert work.accepted_macros == 1 and work.rejected_macros == 0
    assert work.selected_seconds == 60 and work.selected_parts == 2
    # Local selection is not an actual outer transaction publication.
    assert work.committed_seconds == work.committed_parts == 0
    assert result.controller.clock_seconds == 60 and result.maximum_accepted_error_norm <= 1.


def test_decay_analytic_reference_and_rejected_work_are_not_refunded():
    result, work = solve()
    analytic = 280.+20.*exp(-.001*60)
    # Explicit-Euler cooling has the known lower-sided bias for this convex
    # exponential. This independent analytic bound is declared before a run.
    assert analytic-.02 <= result.context.temperature <= analytic
    assert work.rejected_macros > 0 and work.reserved_leaf_calls > work.selected_parts
    assert work.reserved_leaf_calls == work.returned_leaf_calls
    assert result.maximum_accepted_error_norm <= 1.


def test_regime_transition_forces_detailed_fallback_without_outward_time_rounding():
    calls = []
    regime = lambda a, b: ('before' if b <= 3 else 'cross' if a < 3 < b else 'after',)
    result, work = solve(end=7, step=scalar_step(rate=0., regime=regime, calls=calls))
    assert result.cuts[0][:2] == (Q(0), Q(2))
    assert work.detailed_fallback_calls > 0 and work.rejected_macros > 0
    assert result.cuts[-1][1] == 7
    assert sum(b-a for a, b, _ in result.cuts) == 7
    assert all(0 <= a < b <= 7 for a, b in calls)


def test_near_guard_uses_detailed_samples_not_wide_selection():
    result, work = solve(end=9, step=scalar_step(rate=0., near=True))
    assert all(b-a <= 2 for a, b, _ in result.cuts)
    assert work.accepted_macros == 0 and work.detailed_fallback_calls == 5
    assert result.controller.phase == 'DETAILED_FALLBACK'


def test_known_trial_refusal_halves_and_final_refusal_preserves_original():
    original = ScalarState()
    work = QuietWork()
    def fail(state, a, b):
        state.energy = 0.
        raise QuietTrialRefusal(ValueError('known physical refusal'))
    with pytest.raises(QuietTrialRefusal, match='known physical refusal'):
        solve(original, work=work, step=scalar_step(fail=fail))
    assert original == ScalarState()
    assert work.refused_leaf_calls == work.reserved_leaf_calls > 1
    assert work.returned_leaf_calls == 0
    work.validate(QuietIntegrationPolicy())


def test_unknown_error_is_not_a_retry_or_a_refusal():
    work = QuietWork(); calls = []
    def fail(state, a, b): raise RuntimeError('unexpected kernel error')
    with pytest.raises(RuntimeError, match='unexpected kernel error'):
        solve(work=work, step=scalar_step(fail=fail, calls=calls))
    assert len(calls) == 1 and work.unknown_leaf_calls == 1
    assert work.reserved_leaf_calls == 1 and work.rejected_macros == 0


def test_cumulative_quota_refuses_without_reset_or_input_publication():
    p = replace(QuietIntegrationPolicy(), max_total_leaf_calls=2)
    original = ScalarState(); work = QuietWork()
    with pytest.raises(ValueError, match='CUMULATIVE_LEAF_QUOTA'):
        solve(original, policy=p, work=work, step=scalar_step(rate=0.))
    assert original == ScalarState()
    assert work.reserved_leaf_calls == work.returned_leaf_calls == 2


def test_resume_same_explicit_boundary_retains_controller_work_and_exact_results():
    first, work = solve(end=20)
    saved_state, saved_controller, saved_work = deepcopy(first.context), first.controller, deepcopy(work)
    direct, work = solve(first.context, start=20, end=60, controller=first.controller, work=work)
    resumed, resumed_work = solve(saved_state, start=20, end=60,
                                  controller=saved_controller, work=saved_work)
    assert asdict(direct) == asdict(resumed)
    assert asdict(work) == asdict(resumed_work)


def test_exact_odd_boundary_half_seconds_and_short_tail_are_supported():
    result, work = solve(end=5, step=scalar_step(rate=0.))
    assert [(a, b) for a, b, _ in result.cuts] == [(Q(0), Q(5, 2)), (Q(5, 2), Q(5))]
    assert work.selected_seconds == 5


def test_integral_error_participates_even_when_endpoint_state_matches():
    p = QuietIntegrationPolicy()
    full = QuietSample((('energy_wh', 80.),), (('served_load_wh', 1.),), ('same',))
    half = QuietSample((('energy_wh', 80.),), (('served_load_wh', .6),), ('same',))
    assert quiet_error_norm((('energy_wh', 80.),), full, half, half, p) > 1


def _physical_start(*, quiet=True, detailed=2):
    from examples.m5_rolling_mission_demo import make_inputs
    from ops_sim.v5 import long_mission as leaf
    from ops_sim.v5.assembly_attitude_3d import BodyAttitude3D
    from ops_sim.v5.lifecycle_physics import (LifecyclePhysicsLimits, LifecyclePhysicalModel,
        start_lifecycle_physical)
    from ops_sim.v5.rolling_cache import PublicCacheBank, CumulativeWork
    root = make_inputs(); model = root.model; rt = leaf.RuntimeWork()
    bank = PublicCacheBank(model, CumulativeWork(), root.quotas, 'ACTUAL_PUBLIC_MODEL')
    provider, old_source = bank.bind(rt)
    class Source:
        def __init__(self): self.stub = SimpleNamespace(inputs=model, nominal_provider=provider, runtime_work=rt)
        def guard(self): return old_source.guard()
        def schedule(self, a, b): return old_source.schedule(a, b)
        def observations(self, entry, a, b, sampling): return leaf._observations(self.stub, entry, a, b)
        def orientation_inputs(self, hardware, time, quaternion): return leaf._orientation_inputs(self.stub, hardware, time, quaternion)
    context = root.initial_checkpoint.restore(model.simulation_inputs)
    attitude = BodyAttitude3D(model.assembly.body_frame_id, model.environment.trajectory.initial_state.position.frame,
        Q(128), root.initial_quaternion, Q(128))
    wrapper = LifecyclePhysicalModel(model, model.environment,
        replace(LifecyclePhysicsLimits(), detailed_interval_seconds=detailed),
        quiet_policy=QuietIntegrationPolicy() if quiet else None)
    return start_lifecycle_physical(wrapper, context, attitude, tuple(r.product for r in root.requests),
                                    provider, Source(), runtime_work=rt)


def test_real_quiet_leaf_has_paid_fewer_calls_and_bounded_detailed_finer_difference():
    from ops_sim.v5.lifecycle_physics import execute_lifecycle_action
    from ops_sim.v5.long_mission import LongMissionAction
    states = [_physical_start(), _physical_start(quiet=False), _physical_start(quiet=False, detailed=1)]
    results = [execute_lifecycle_action(s, LongMissionAction('quiet-check', 'HOLD_UNTIL', until_seconds=188))
               for s in states]
    assert all(o.status == 'completed' for _, o in results)
    quiet, detailed, finer = (s for s, _ in results)
    assert quiet.context.simulation_time_seconds == detailed.context.simulation_time_seconds == finer.context.simulation_time_seconds == 188
    assert quiet.quiet_work.reserved_leaf_calls < detailed.runtime_work.physical_completed_calls
    assert quiet.quiet_work.committed_seconds == 60
    for state in (quiet, detailed):
        assert abs(state.context.spacecraft_state.battery.energy_wh-finer.context.spacecraft_state.battery.energy_wh) <= .005
        assert max(abs(a.temperature_k-b.temperature_k) for a, b in zip(
            state.context.spacecraft_state.thermal.node_states, finer.context.spacecraft_state.thermal.node_states)) <= .05
    assert quiet.quiet_controller.clock_seconds == 188


def test_real_moving_point_stays_detailed_and_updates_quiet_clock():
    from ops_sim.v5.lifecycle_physics import execute_lifecycle_action
    from ops_sim.v5.long_mission import LongMissionAction
    state = _physical_start()
    state, outcome = execute_lifecycle_action(state, LongMissionAction('paid-point', 'POINT', point_id='target'))
    assert outcome.status == 'completed' and all(c.end_seconds-c.start_seconds <= 2 for c in outcome.cuts)
    assert state.quiet_work.reserved_leaf_calls == 0
    assert state.quiet_controller.clock_seconds == state.context.simulation_time_seconds
    assert state.quiet_controller.phase == 'DETAILED_ACTION'


def _acquisition_case(state, *, stage=None):
    """Explicit supplied-owner input, no invented visibility or capture grant."""
    from ops_sim.v5.lifecycle_physics import _forcing
    from ops_sim.v5.adcs import CommonFrameBoresightDirection
    from ops_sim.v5.ids import ADCSBoresightFrameId, ObservationOpportunityId, AcquisitionDataRecordId
    from ops_sim.v5.observation import ObservationOpportunity, ObservationPointing
    from ops_sim.v5.observation_feasibility import ObservationManeuverCandidate
    from ops_sim.v5.imaging_feasibility import ObservationAcquisitionCandidate
    from ops_sim.v5.imaging_execution import ScheduledObservationAcquisitionExecution
    from ops_sim.v5.imaging_resources import AcquisitionEPSIntervalEnvironment
    from ops_sim.v5.payload import OpticalAcquisitionInput, OpticalAcquisitionChannelSelection
    from ops_sim.v5.ms_product import MSAcquisitionPlan, REQUIRED_MS_CHANNELS, size_ms_grid
    from ops_sim.v5.ms_acquisition import InitialAttitudeEvidence
    from ops_sim.v5.continuation import ImagingAction
    context = deepcopy(state.context); cfg = context.inputs.spacecraft_configuration
    product = next(p for p in state.inputs.products if p.request.request_id.value == 'b47-medium')
    limit = cfg.adcs.agile_pointing.maximum_view_angle_from_nadir_deg.value
    angle = (limit+90.)/2 if stage == 'VIEW' else 0.
    point = ObservationOpportunity(ObservationOpportunityId('diagnostic-opportunity'), product.request.request_id,
        128, 132, 4, ObservationPointing(angle, 0.))
    frame = ADCSBoresightFrameId('supplied-typed-test-common-frame')
    direction = CommonFrameBoresightDirection(frame, 1., 0., 0.)
    previous = InitialAttitudeEvidence(128,
        CommonFrameBoresightDirection(frame, 0., 1., 0.) if stage == 'SETTLING' else direction,
        'Explicit test initial rest and same common frame, no inferred geometry.')
    optical = cfg.payload.optical_acquisition
    acquisition = OpticalAcquisitionInput(product.footprint.width_m, product.footprint.length_m, 4,
        OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY)
    execution = ScheduledObservationAcquisitionExecution(ObservationAcquisitionCandidate(
        ObservationManeuverCandidate(point, direction), acquisition), 128)
    forcing, _, _, _, _ = _forcing(state, state.harness.hardware, Q(128), Q(128), state.attitude.quaternion)
    image = ImagingAction('diagnostic-image', execution, AcquisitionDataRecordId('diagnostic-record'),
        AcquisitionEPSIntervalEnvironment(forcing.sunlit, forcing.incidence_angle_deg, forcing.loads),
        state.inputs.routing, forcing.thermal_inputs, forcing.external_heat_sources, None)
    plan = MSAcquisitionPlan(1, product.request, product.capture_group,
        size_ms_grid(product.footprint, optical.multispectral_reference_sample_spacing_m.value,
            optical.multispectral_reference_sample_spacing_m.value, REQUIRED_MS_CHANNELS,
            int(optical.acquisition_bits_per_sample.value)), 'Supplied exact typed diagnostic fixture.')
    if stage == 'STORAGE':
        storage = replace(cfg.storage, usable_capacity_gb=replace(cfg.storage.usable_capacity_gb, value=1.e-12))
        context.inputs = replace(context.inputs, spacecraft_configuration=replace(cfg, storage=storage))
    return context, previous, image, plan


@pytest.mark.parametrize('stage,code,owner', [
    ('VIEW', 'ACQUISITION_VIEW_ENVELOPE_REFUSED', 'evaluate_observation_view_feasibility'),
    ('SETTLING', 'ACQUISITION_SETTLING_NOT_READY', 'compute_boresight_transition'),
    ('STORAGE', 'ACQUISITION_STORAGE_INSUFFICIENT_CAPACITY', 'evaluate_storage_admission')])
def test_actual_lower_owner_refusal_has_precise_typed_evidence_and_no_physical_grant(stage, code, owner):
    from ops_sim.v5.lifecycle_physics import _diagnosed_imaging_request, LifecycleRefusalDetail
    from ops_sim.v5.long_mission import _Refusal
    state = _physical_start(); args = _acquisition_case(state, stage=stage)
    before = deepcopy(args[0]); paid = state.runtime_work.spatial_reserved_units
    with pytest.raises(_Refusal, match=code) as caught:
        _diagnosed_imaging_request(state, *args)
    detail = caught.value.diagnostic[1]
    assert type(detail) is LifecycleRefusalDetail and detail.stage == stage and detail.code == code
    assert detail.owner.endswith(owner)
    assert dict(detail.evaluated_calls)[owner] == 1
    assert args[0] == before
    assert state.runtime_work.spatial_reserved_units == paid+1024
    assert state.runtime_work.physical_reserved_calls == 0


def test_single_pass_diagnostic_success_matches_original_initial_attitude_adapter_exactly():
    from ops_sim.v5.lifecycle_physics import _diagnosed_imaging_request
    from ops_sim.v5.substepped_execution import _imaging_request
    state = _physical_start(); context, previous, image, plan = _acquisition_case(state)
    assert _diagnosed_imaging_request(state, context, previous, image, plan) == _imaging_request(
        context, previous, image, plan)
