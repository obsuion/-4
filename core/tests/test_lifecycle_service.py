"""Pure synthetic B55 contract checks; no simulation, replay or integration."""
from dataclasses import asdict, replace
from fractions import Fraction as Q
import pytest

from ops_sim.v5.lifecycle_service import (
    LEGACY, POWER_SERVICE_METHOD, PowerServicePolicy, PowerServiceState,
    PowerServiceWork, PowerServiceDecision, initial_service_state, requested_service_policy,
    select_service_mode, commit_service_step, service_projection)


def choose(p, s, energy, *, stationary=True):
    return select_service_mode(p, s, clock_seconds=s.clock_seconds,
        energy_wh=energy, usable_capacity_wh=100., stationary=stationary)


def advance(p, decision, work, dt, *, desired=6., commanded=2., served=2., unmet=0.):
    return commit_service_step(p, decision, work, duration_seconds=Q(dt),
        desired_normal_load_w=desired, commanded_load_w=commanded,
        served_receiving_load_w=served, essential_unserved_w=unmet,
        essential_fully_served=(unmet == 0))


def test_explicit_selector_legacy_and_policy_identity():
    assert requested_service_policy(LEGACY) is None
    p = requested_service_policy(POWER_SERVICE_METHOD)
    assert p == PowerServicePolicy()
    assert len(p.identity) == 64
    assert p.identity != replace(p, boot_duration_seconds=121).identity
    assert p.source_role.startswith('ASSUMED_')
    with pytest.raises(ValueError): requested_service_policy('unknown')
    with pytest.raises(TypeError): requested_service_policy(True)


@pytest.mark.parametrize('change', [
    dict(low_usable_capacity_fraction=0), dict(high_usable_capacity_fraction=1.),
    dict(low_usable_capacity_fraction=.4), dict(point_reserve_fraction=.2),
    dict(minimum_dwell_seconds=True), dict(boot_duration_seconds=0),
    dict(low_usable_capacity_fraction=float('nan')), dict(storage_rule='VOLATILE'),
    dict(functional_rule='FREE_COMPUTER')])
def test_policy_negative_domains(change):
    with pytest.raises((ValueError, TypeError)):
        PowerServicePolicy(**change)


def test_well_powered_normal_no_gratuitous_transition():
    p = PowerServicePolicy(); s = initial_service_state(Q(128)); work = PowerServiceWork()
    decision = choose(p, s, 80.)
    assert decision.state is s and not decision.transitioned and decision.supported
    after, ledger = advance(p, decision, work, 60, commanded=6., served=6.)
    assert after.mode == 'NORMAL' and after.communications_serviceable
    assert ledger.normal_seconds == 60 and ledger.commanded_shed_demand_wh == 0
    assert work.covered_seconds == 0 and s.clock_seconds == 128


def test_sampled_hysteresis_dwell_paid_boot_full_cycle():
    p = PowerServicePolicy(); s = initial_service_state(Q(128)); w = PowerServiceWork()
    decision = choose(p, s, 9.)
    assert decision.state.mode == 'SAFE' and decision.state.entered_at_seconds == 128
    s, w = advance(p, decision, w, 30)
    assert not choose(p, s, 35.).transitioned
    s, w = advance(p, choose(p, s, 25.), w, 30)
    assert choose(p, s, 25.).state.mode == 'SAFE'
    s, w = advance(p, choose(p, s, 35.), w, 120)
    assert s.mode == 'RECOVERY' and s.boot_progress_seconds == 120
    assert not s.communications_serviceable
    s, w = advance(p, choose(p, s, 35.), w, 60, commanded=6., served=6.)
    assert s.mode == 'NORMAL' and s.boot_progress_seconds == 0
    assert s.communications_serviceable and w.transitions == 3
    assert (w.safe_seconds, w.recovery_seconds, w.normal_seconds) == (60, 120, 60)
    assert w.covered_seconds == 240 and w.boot_work_seconds == 120
    projection = service_projection(p, s, w, original_start_seconds=Q(128))
    assert projection['mode_durations_seconds']['SAFE'] == ['60', '1']
    assert projection['receiving_energy_wh']['commanded_shed_demand_wh'] == ['1', '5']
    assert sum(n for _, n in w.transition_reasons) == 3


def test_essential_deficit_is_not_working_computer_or_radio():
    p = PowerServicePolicy(); s = initial_service_state(Q(128)); w = PowerServiceWork()
    s, w = advance(p, choose(p, s, 0.), w, 60, served=0., unmet=2.)
    assert not s.essential_serviceable and not s.communications_serviceable
    decision = choose(p, s, 0.)
    assert decision.state.mode == 'POWER_OFF'
    s, w = advance(p, decision, w, 60, served=0., unmet=2.)
    assert w.covered_seconds == 120 and w.essential_unserved_wh == Q(1, 15)
    assert w.service_interruptions == 1 and w.boot_work_seconds == 0


def test_boot_service_loss_and_reserve_loss_do_not_complete_recovery():
    p = PowerServicePolicy()
    s = PowerServiceState(Q(200), Q(128), 'RECOVERY', 'RECOVERY_RESERVE_READY', Q(72), 2, True, False)
    decision = choose(p, s, 9.)
    assert decision.state.mode == 'SAFE' and decision.state.boot_progress_seconds == 0
    failed = replace(s, essential_serviceable=False)
    assert choose(p, failed, 35.).state.mode == 'POWER_OFF'


def test_moving_point_domain_preserves_original_state_exactly():
    p = PowerServicePolicy(); original = initial_service_state(Q(128))
    snapshot = asdict(original)
    decision = choose(p, original, 0., stationary=False)
    assert not decision.supported and not decision.transitioned
    assert decision.state is original and asdict(original) == snapshot
    assert decision.reason == 'UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY'
    with pytest.raises(ValueError): advance(p, decision, PowerServiceWork(), 1)


def test_exact_selected_accounting_no_private_trial_or_zero_duration():
    p = PowerServicePolicy(); s = initial_service_state(Q(128)); w = PowerServiceWork()
    decision = choose(p, s, 9.)
    for bad in (Q(0), -Q(1), 1):
        with pytest.raises(ValueError):
            commit_service_step(p, decision, w, duration_seconds=bad,
                desired_normal_load_w=6., commanded_load_w=2., served_receiving_load_w=2.,
                essential_unserved_w=0., essential_fully_served=True)
    assert s.clock_seconds == 128 and w == PowerServiceWork()
    with pytest.raises(ValueError):
        advance(p, decision, w, 1, desired=1., commanded=2.)
    with pytest.raises(ValueError):
        advance(p, decision, w, 1, commanded=2., served=2., unmet=1.)


def test_current_capacity_not_nominal_capacity_and_strict_clock():
    p = PowerServicePolicy(); s = initial_service_state(Q(128))
    decision = select_service_mode(p, s, clock_seconds=Q(128), energy_wh=9.,
        usable_capacity_wh=50., stationary=True)
    assert decision.state.mode == 'NORMAL'
    with pytest.raises(ValueError):
        select_service_mode(p, s, clock_seconds=Q(129), energy_wh=9.,
            usable_capacity_wh=50., stationary=True)
    with pytest.raises(TypeError): choose(p, s, 9., stationary=1)


def test_projection_rejects_unaccounted_duration_and_transition():
    p = PowerServicePolicy(); s = initial_service_state(Q(128))
    with pytest.raises(ValueError):
        service_projection(p, s, PowerServiceWork(), original_start_seconds=Q(127))
    invalid = replace(s, transition_count=1)
    with pytest.raises(ValueError):
        service_projection(p, invalid, PowerServiceWork(), original_start_seconds=Q(128))
class HostileReason:
    def __eq__(self, other):
        raise AssertionError('hostile equality must not run during admission')


class TextReason(str):
    def __eq__(self, other):
        raise AssertionError('text subclass equality must not run during admission')


@pytest.mark.parametrize('reason', [HostileReason(), TextReason('INITIAL_NOMINAL')])
def test_reason_admission_rejects_nonexact_text_without_equality(reason):
    state = initial_service_state(Q(128))
    with pytest.raises(ValueError):
        PowerServiceDecision(state, 'NORMAL', False, True, reason)
    with pytest.raises(ValueError):
        PowerServiceWork(transitions=1, transition_reasons=((reason, 1),))


def test_stale_decision_cannot_account_already_advanced_work():
    policy = PowerServicePolicy(); original = initial_service_state(Q(128))
    decision = choose(policy, original, 80.)
    state, work = advance(policy, decision, PowerServiceWork(), 60,
        commanded=6., served=6.)
    saved_state, saved_work = asdict(state), asdict(work)
    assert work.initial_clock_seconds == 128 and work.through_seconds == 188
    with pytest.raises(ValueError, match='stale service decision/work frontier'):
        advance(policy, decision, work, 60, commanded=6., served=6.)
    assert asdict(state) == saved_state and asdict(work) == saved_work
    state, work = advance(policy, choose(policy, state, 80.), work, 60,
        commanded=6., served=6.)
    assert work.through_seconds == state.clock_seconds == 248
    assert work.covered_seconds == 120


@pytest.mark.parametrize('mode', ['SAFE', 'POWER_OFF', 'RECOVERY'])
def test_degraded_nochange_still_requires_stationary_domain(mode):
    policy = PowerServicePolicy()
    state = PowerServiceState(Q(200), Q(128), mode,
        'RECOVERY_RESERVE_READY' if mode == 'RECOVERY' else 'NORMAL_LOW_ENERGY',
        Q(), 1, True, False)
    decision = choose(policy, state, 20., stationary=False)
    assert decision.state is state and not decision.transitioned and not decision.supported
    with pytest.raises(ValueError, match='unsupported moving recovery'):
        advance(policy, decision, PowerServiceWork(), 1)