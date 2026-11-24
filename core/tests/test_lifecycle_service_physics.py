"""Linked service/physics transactions, using the existing real short source.

These initial-clock test plants are not advanced checkpoints or manufactured
visibility. Public actions call the real physical adapter and accepted leaves.
"""
from dataclasses import replace
from fractions import Fraction as Q
import pytest

from types import SimpleNamespace
from examples.m4_construction_mission_demo import make_inputs
from ops_sim.v5.assembly_attitude_3d import compile_assembly_hardware_3d
from ops_sim.v5.construction_mission import start_construction_mission
from ops_sim.v5.integration_time import RationalSeconds
from ops_sim.v5.lifecycle_quiet import QuietIntegrationPolicy
from ops_sim.v5.long_mission import _forcing
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.construction_service import (ConstructionServicePolicy, ConstructionServiceWork,
    ConstructionServiceElectricalRefusal, ConstructionServiceDomainRefusal,
    service_physical_substep)
from ops_sim.v5.lifecycle_physics import execute_lifecycle_action, guard_lifecycle_physical
from ops_sim.v5.lifecycle_service import PowerServicePolicy, PowerServiceWork, initial_service_state
from ops_sim.v5.long_mission import LongMissionAction
from ops_sim.v5.state import OperationalMode, FDIRState


# Portable local copies of the original initial-state fixture builders only.
# No bare test-module imports: pytest importlib mode intentionally omits tests/
# from sys.path. Physical calls remain the same public source owners.
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


def leaf(*, energy=None, sunlit=False, seconds=1, mode='SAFE'):
    state = start_construction_mission(make_inputs())
    if energy is not None:
        state.context.spacecraft_state.battery.energy_wh = energy
    hardware = compile_assembly_hardware_3d(state.inputs.assembly,
        state.inputs.capabilities, state.inputs.actuator)
    forcing, eps, *_ = _forcing(state, hardware, Q(130), Q(131), state.attitude.quaternion)
    eps = replace(eps, sunlit=sunlit, incidence_angle_deg=0.)
    paid = ConstructionServiceWork()
    kwargs = dict(compilation=state.construction.compilation,
        service_policy=ConstructionServicePolicy(), service_mode=mode,
        service_work=paid, work=state.construction.work,
        limits=state.construction.inputs.limits,
        start_seconds=Q(130), end_seconds=Q(130+seconds))
    return state, forcing, eps, RationalSeconds.from_fraction(Q(seconds)), paid, kwargs



def start(*, energy=None, quiet=True, detailed=2):
    value = _physical_start(quiet=quiet, detailed=detailed)
    assert value.context.simulation_time_seconds == 128
    if energy is not None:
        value.context.spacecraft_state.battery.energy_wh = energy
    model = replace(value.inputs.model, service_policy=PowerServicePolicy())
    value = replace(value, inputs=replace(value.inputs, model=model),
        service_state=initial_service_state(Q(128)), service_work=PowerServiceWork(),
        service_allocation_work=ConstructionServiceWork())
    guard_lifecycle_physical(value)
    return value


def test_normal_detailed_hold_keeps_physical_projection_exact():
    legacy = _physical_start(quiet=False)
    current = start(quiet=False)
    action = LongMissionAction('normal-physical-compatibility', 'HOLD_UNTIL', until_seconds=130)
    legacy, old = execute_lifecycle_action(legacy, action)
    current, new = execute_lifecycle_action(current, action)
    assert new.status == old.status == 'completed'
    assert CheckpointState.from_context(current.context).to_dict() == CheckpointState.from_context(legacy.context).to_dict()
    assert tuple(cut.part.physical for cut in new.cuts) == tuple(cut.part.physical for cut in old.cuts)
    assert current.service_work.normal_seconds == 2
    assert current.service_work.covered_seconds == 2
    assert new.service_work_before.covered_seconds == 0
    assert new.service_work_after == current.service_work


def test_low_energy_hold_selects_real_passive_support_and_onboard_mode():
    original = start(energy=0.)
    current, outcome = execute_lifecycle_action(original,
        LongMissionAction('low-original-state', 'HOLD_UNTIL', until_seconds=188))
    assert outcome.status == 'completed' and current.context.simulation_time_seconds == 188
    assert current.service_work.covered_seconds == 60
    assert current.service_work.safe_seconds+current.service_work.power_off_seconds == 60
    assert not current.service_state.communications_serviceable
    assert current.context.spacecraft_state.onboard.operational_mode is OperationalMode.SAFE
    assert current.context.spacecraft_state.onboard.fdir_state is FDIRState.BACKUP
    assert sum((cut.end_seconds-cut.start_seconds for cut in outcome.cuts), Q()) == 60
    assert all(cut.part.service.commanded_load_w > 0 for cut in outcome.cuts)
    assert current.quiet_work.accepted_macros > 0
    assert current.service_work.selected_steps == len(outcome.cuts)
    assert current.service_allocation_work.selected_coupled_calls > len(outcome.cuts)
    guard_lifecycle_physical(current)


def test_low_original_state_quiet_against_detailed_finer_reference():
    states = [start(energy=0.), start(energy=0., quiet=False),
              start(energy=0., quiet=False, detailed=1)]
    results = [execute_lifecycle_action(state,
        LongMissionAction('low-refinement', 'HOLD_UNTIL', until_seconds=188)) for state in states]
    assert all(outcome.status == 'completed' for _, outcome in results)
    reference = results[-1][0]
    # Existing predeclared short B53 physical screen, in Wh and K. This is a
    # nominal sampled comparison, not exact cross-method replay or safety.
    for current, _ in results[:2]:
        assert abs(current.context.spacecraft_state.battery.energy_wh-reference.context.spacecraft_state.battery.energy_wh) <= .005
        assert max(abs(a.temperature_k-b.temperature_k) for a, b in zip(
            current.context.spacecraft_state.thermal.node_states,
            reference.context.spacecraft_state.thermal.node_states)) <= .05
        assert current.service_work.covered_seconds == reference.service_work.covered_seconds == 60


def test_charged_dwell_release_is_guarded_against_actual_detailed_finer(monkeypatch):
    """Declared standalone prior SAFE state; not a migrated experiment input.

    Constant face-on PV is an explicit unit forcing input to the REAL coupled
    service owner, not a geometric visibility or original-root recovery claim.
    Forty seconds remain of the fixed sixty-second dwell. Without its guard,
    full and half proposals can both stay SAFE past that release boundary.
    """
    import ops_sim.v5.lifecycle_physics as owner
    from ops_sim.v5.lifecycle_service import fresh_service_work
    original = owner._forcing
    def face_on(*args, **kwargs):
        forcing, eps, *tail = original(*args, **kwargs)
        return forcing, replace(eps, sunlit=True, incidence_angle_deg=0.), *tail
    monkeypatch.setattr(owner, '_forcing', face_on)
    states = [start(energy=31.), start(energy=31., quiet=False),
              start(energy=31., quiet=False, detailed=1)]
    prepared = []
    for state in states:
        service = replace(state.service_state, mode='SAFE', entered_at_seconds=Q(108),
            last_reason='NORMAL_LOW_ENERGY', transition_count=1,
            communications_serviceable=False)
        state.context.spacecraft_state.onboard.operational_mode = OperationalMode.SAFE
        state.context.spacecraft_state.onboard.fdir_state = FDIRState.BACKUP
        state = replace(state, service_state=service, service_work=fresh_service_work(service))
        guard_lifecycle_physical(state); prepared.append(state)
    results = [execute_lifecycle_action(state,
        LongMissionAction('charged-dwell-boundary', 'HOLD_UNTIL', until_seconds=248)) for state in prepared]
    assert all(outcome.status == 'completed' for _, outcome in results)
    for current, outcome in results:
        assert current.service_state.mode == 'RECOVERY'
        assert current.service_state.entered_at_seconds == 168
        assert current.service_work.safe_seconds == 40
        assert current.service_work.recovery_seconds == current.service_work.boot_work_seconds == 80
        assert current.service_work.covered_seconds == 120
        assert any(cut.part.eps_result.battery.charge_input_w > 0 for cut in outcome.cuts)
        assert all(cut.end_seconds-cut.start_seconds <= 2 for cut in outcome.cuts
                   if cut.part.service.service_mode == 'SAFE')
    reference = results[-1][0]
    for current, _ in results[:2]:
        assert abs(current.context.spacecraft_state.battery.energy_wh-reference.context.spacecraft_state.battery.energy_wh) <= .005
        assert max(abs(a.temperature_k-b.temperature_k) for a, b in zip(
            current.context.spacecraft_state.thermal.node_states,
            reference.context.spacecraft_state.thermal.node_states)) <= .05


def test_high_draw_low_threshold_jump_uses_actual_detailed_finer_boundary(monkeypatch):
    """An explicit dark12W unit load can jump over the near-energy margin.

    This calls the real allocation/EPS/heat/ageing owners under declared unit
    forcing, without claiming geometric darkness or an original-root campaign.
    No threshold, margin or tolerance is changed to manufacture agreement.
    """
    import ops_sim.v5.lifecycle_physics as owner
    from ops_sim.v5.eps_capability import compute_eps_capability
    original = owner._forcing
    def high_draw(*args, **kwargs):
        forcing, eps, *tail = original(*args, **kwargs)
        loads = replace(eps.load_breakdown, base_bus_w=12., obc_w=0.)
        return forcing, replace(eps, load_breakdown=loads, sunlit=False, incidence_angle_deg=0.), *tail
    monkeypatch.setattr(owner, '_forcing', high_draw)
    states = [start(), start(quiet=False), start(quiet=False, detailed=1)]
    for state in states:
        capacity = compute_eps_capability(state.context.inputs.spacecraft_configuration.eps,
            state.context.spacecraft_state.degradation).battery_usable_capacity_wh
        state.context.spacecraft_state.battery.energy_wh = capacity*state.inputs.service_policy.low_usable_capacity_fraction+.065
    results = [execute_lifecycle_action(state,
        LongMissionAction('high-draw-low-crossing', 'HOLD_UNTIL', until_seconds=188)) for state in states]
    assert all(outcome.status == 'completed' for _, outcome in results)
    reference = results[-1][0]
    assert reference.service_state.mode == 'SAFE'
    for current, outcome in results:
        assert current.service_state.mode == 'SAFE'
        assert current.service_work.covered_seconds == 60
        assert abs(current.service_state.entered_at_seconds-reference.service_state.entered_at_seconds) <= 2
        assert all(cut.part.service.essential_fully_served for cut in outcome.cuts)
        assert any(cut.part.service.service_mode == 'NORMAL' for cut in outcome.cuts)
        assert any(cut.part.service.service_mode == 'SAFE' for cut in outcome.cuts)
        assert abs(current.context.spacecraft_state.battery.energy_wh-reference.context.spacecraft_state.battery.energy_wh) <= .005
        assert max(abs(a.temperature_k-b.temperature_k) for a, b in zip(
            current.context.spacecraft_state.thermal.node_states,
            reference.context.spacecraft_state.thermal.node_states)) <= .05


def test_late_survival_failure_is_paid_private_without_public_commit(monkeypatch):
    import ops_sim.v5.lifecycle_physics as owner
    state = start(quiet=False)
    before = CheckpointState.from_context(state.context).to_dict()
    original = owner._violations; survival_calls = []
    def later(context, required, *, survival=False):
        if survival:
            survival_calls.append(context)
            if len(survival_calls) == 2:
                return (context.inputs.spacecraft_configuration.thermal.network.bus_node_id,)
        return original(context, required, survival=survival)
    monkeypatch.setattr(owner, '_violations', later)
    result, outcome = execute_lifecycle_action(state,
        LongMissionAction('late-survival', 'HOLD_UNTIL', until_seconds=130))
    assert outcome.status == 'refused' and outcome.reason == 'B55_SURVIVAL_TEMPERATURE_AT_ENDPOINT'
    assert outcome.failure_diagnostic[0] == 'PAID_PRIVATE_ENDPOINT_NOT_PUBLISHED'
    assert CheckpointState.from_context(result.context).to_dict() == before
    assert result.service_work.covered_seconds == 0
    assert result.service_allocation_work.allocation_trials > 0
    assert result.runtime_work.physical_completed_calls > 0


def test_point_policy_denies_low_energy_without_free_pose_change():
    state = start(energy=0., quiet=False)
    pose = state.attitude
    result, outcome = execute_lifecycle_action(state, LongMissionAction('no-free-point', 'POINT', point_id='target'))
    assert outcome.status == 'refused' and outcome.reason.startswith('B55_POWER_SERVICE_INTERRUPTED')
    assert result.attitude == pose and result.context.simulation_time_seconds == 128
    assert result.service_work.covered_seconds == 0


def test_unpowered_mechanical_adjustment_retains_failed_eps_carrier():
    state, forcing, eps, duration, paid, kwargs = leaf(energy=0., mode='NORMAL')
    before = CheckpointState.from_context(state.context).to_dict()
    node = state.context.inputs.spacecraft_configuration.thermal.network.bus_node_id
    with pytest.raises(ConstructionServiceDomainRefusal) as caught:
        service_physical_substep(state.context, duration, forcing, eps,
            state.inputs.protection, None, internal_heat_adjustments_w=((node, -1.),), **kwargs)
    diagnostic = caught.value.diagnostic
    assert diagnostic.full_demand_trial.battery.unmet_load_w > 0
    assert not diagnostic.full_commanded_service
    assert paid.allocation_trials > 0 and paid.selected_coupled_calls == 0
    assert CheckpointState.from_context(state.context).to_dict() == before


def test_pv_line_refusal_preserves_exact_private_attempt_without_eps_repeat():
    state, forcing, eps, duration, paid, kwargs = leaf(sunlit=True)
    before = CheckpointState.from_context(state.context).to_dict()
    compilation = kwargs['compilation']; pv_id = compilation.configuration.pv_line_id
    kwargs['compilation'] = replace(compilation, branches=tuple(replace(branch,
        wire=replace(branch.wire, current_limit_a=1.e-12)) if branch.line_id == pv_id else branch
        for branch in compilation.branches))
    with pytest.raises(ConstructionServiceElectricalRefusal) as caught:
        service_physical_substep(state.context, duration, forcing, eps,
            state.inputs.protection, None, **kwargs)
    diagnostic = caught.value.diagnostic
    assert diagnostic.returned_full_demand_trial is None
    assert diagnostic.start_seconds == 130 and diagnostic.end_seconds == 131
    assert diagnostic.trial_count == paid.allocation_trials == 2
    assert paid.eps_calls_refused == 2 and paid.eps_calls_returned == 0
    assert CheckpointState.from_context(state.context).to_dict() == before


def test_tiny_unspent_energy_is_preserved_below_allocation_grid():
    state, forcing, eps, duration, paid, kwargs = leaf(energy=1.e-20, mode='POWER_OFF')
    part, _ = service_physical_substep(state.context, duration, forcing, eps,
        state.inputs.protection, None, **kwargs)
    assert state.context.spacecraft_state.battery.energy_wh == 1.e-20
    assert part.service.served_load_w == 0 and not part.service.essential_fully_served
    assert part.service.commanded_load_w > 0
    assert paid.allocation_trials == 2 and paid.bisection_trials == 0


def _contact_case(*, powered):
    """Leaf negative fixture, not an original-root campaign or restart claim."""
    from ops_sim.v5.construction_mission import advance_construction_mission
    # Identical portable original-fixture builders from construction repairs.
    def partial_inputs():
        value = make_inputs(); actions = value.mission.actions
        actions = (*actions[:3], replace(actions[3], action_id='partial-first', duration_seconds=1),
            replace(actions[3], action_id='partial-second'), actions[4])
        return replace(value, mission=replace(value.mission, actions=actions))
    def prefix(inputs, count):
        state = start_construction_mission(inputs)
        for _ in range(count): state = advance_construction_mission(state)
        return state
    from ops_sim.v5.assembly_attitude_3d import compile_assembly_hardware_3d
    from ops_sim.v5.long_mission import _forcing
    from ops_sim.v5.coupled_downlink import CoupledDownlinkInputs
    from ops_sim.v5.operational_protection import StandbyInputs
    from ops_sim.v5.communications import ServiceableGroundContact
    from ops_sim.v5.ids import GroundContactId, GroundStationId
    from ops_sim.v5.contact_execution import ContactPlan, ConsumedContacts
    from ops_sim.v5.integration_time import IntegrationPolicy
    from ops_sim.v5.lifecycle_service_contact import execute_service_contact_plan
    state = prefix(partial_inputs(), 4)
    assert state.context.simulation_time_seconds == 169
    before_bits = state.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits
    hardware = compile_assembly_hardware_3d(state.inputs.assembly, state.inputs.capabilities, state.inputs.actuator)
    forcing, *_ = _forcing(state, hardware, Q(169), Q(170), state.attitude.quaternion)
    # Explicit dark constant-forcing electrical leaf input in BOTH TX and idle.
    # The injected energy is a targeted guard test, not a migrated experiment.
    if not powered: state.context.spacecraft_state.battery.energy_wh = 0.
    tx = CoupledDownlinkInputs(state.inputs.transmitter, forcing.loads, False, 0.,
        forcing.routing_config, forcing.thermal_inputs, forcing.external_heat_sources, None)
    idle = StandbyInputs(forcing.loads, False, 0., forcing.routing_config,
        forcing.thermal_inputs, forcing.external_heat_sources, None,
        'Explicit synthetic dark leaf regression; no visibility certification.')
    contact = ServiceableGroundContact(GroundContactId('b55-unit-dark'), GroundStationId('station'), 169, 170)
    ids = tuple(record.record_id for record in state.context.spacecraft_state.data_storage.stored_records)
    result = execute_service_contact_plan(state.context, ContactPlan(contact, ids, tx, idle),
        consumed_contacts=ConsumedContacts(()), policy=state.inputs.protection,
        integration=IntegrationPolicy(2), compilation=state.construction.compilation,
        work=state.construction.work, limits=state.construction.inputs.limits,
        service_policy=PowerServicePolicy(), service_state=initial_service_state(Q(169)),
        service_work=PowerServiceWork(), allocation_work=ConstructionServiceWork())
    return state, result, before_bits


def test_contact_partial_bits_require_each_selected_tx_cut_fully_powered():
    state, result, before = _contact_case(powered=True)
    assert result.outcome.transmitted_bits == 1000
    assert result.outcome.denied_record_id is None and not state.context.ground_data_delivery_state.completed_deliveries
    assert state.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits == before+1000
    assert all(diagnostic.full_commanded_service for diagnostic in result.outcome.service_diagnostics)
    assert result.service_state.tx_fully_served
    assert result.service_work.covered_seconds == 1


def test_contact_power_loss_keeps_old_partial_custody_without_new_receipt():
    state, result, before = _contact_case(powered=False)
    assert result.outcome.transmitted_bits == 0 and result.outcome.denied_record_id is not None
    assert state.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits == before
    assert not state.context.ground_data_delivery_state.completed_deliveries
    assert not result.service_state.tx_fully_served and not result.service_state.communications_serviceable
    assert result.outcome.operational_mode is OperationalMode.SAFE
    assert result.outcome.fdir_state is FDIRState.BACKUP
    assert result.outcome.critical_energy_since_seconds == 169
    assert any(diagnostic.essential_unserved_w > 0 for diagnostic in result.outcome.service_diagnostics)
    assert result.service_work.covered_seconds == 1 and state.context.simulation_time_seconds == 170


@pytest.fixture(scope='module')
def valid_service_diagnostic():
    state, forcing, eps, duration, _, kwargs = leaf()
    part, _ = service_physical_substep(state.context, duration, forcing, eps,
        state.inputs.protection, None, **kwargs)
    return part.service


@pytest.mark.parametrize('change', [
    dict(desired_load_w=-1.), dict(service_mode='UNKNOWN'), dict(scope='ACTUAL_COMMITTED'),
    dict(trial_count=True), dict(essential_fully_served=False), dict(start_seconds=130),
    dict(end_seconds=Q(132)), dict(reason='FULL_MISSION_SUCCESS')])
def test_diagnostic_rejects_inconsistent_fields(valid_service_diagnostic, change):
    with pytest.raises((TypeError, ValueError)):
        replace(valid_service_diagnostic, **change)


def test_diagnostic_rejects_changed_source_wire_and_allocated_carrier(valid_service_diagnostic):
    value = valid_service_diagnostic
    for name in ('source_load_w', 'source_generation_w', 'pv_wire_loss_w', 'receiving_wire_loss_w'):
        changed = replace(value.selected_electrical, **{name: getattr(value.selected_electrical, name)+1.})
        with pytest.raises(ValueError): replace(value, selected_electrical=changed)
    first, *remaining = value.selected_electrical.branches
    changed = replace(first, electrical=replace(first.electrical, loss_w=first.electrical.loss_w+1.))
    carrier = replace(value.selected_electrical, branches=(changed, *remaining))
    with pytest.raises(ValueError): replace(value, selected_electrical=carrier)


def test_guard_revalidates_frozen_diagnostic_after_untrusted_record_tamper():
    state, outcome = execute_lifecycle_action(start(quiet=False),
        LongMissionAction('record-integrity', 'HOLD_UNTIL', until_seconds=130))
    assert outcome.status == 'completed'
    object.__setattr__(state.last_service_diagnostic, 'served_load_w', -1.)
    with pytest.raises(ValueError): guard_lifecycle_physical(state)


def test_failure_diagnostic_rejects_changed_interval_scope_and_demand():
    from ops_sim.v5.construction_service import ConstructionServiceFailureDiagnostic
    state, forcing, eps, duration, paid, kwargs = leaf()
    value = ConstructionServiceFailureDiagnostic('SAFE', Q(130), Q(131),
        eps.load_breakdown, eps.load_breakdown, None, 'known wire refusal', 2)
    for change in (dict(trial_count=True), dict(start_seconds=130), dict(scope='ACTUAL'),
                   dict(reason=''), dict(end_seconds=Q(130)),
                   dict(commanded_loads=replace(eps.load_breakdown, payload_w=1.))):
        with pytest.raises((TypeError, ValueError)):
            replace(value, **change)
