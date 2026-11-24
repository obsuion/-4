"""B63 owned preparation and independent legacy environment equivalence."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, dataclass, replace
from fractions import Fraction as Q

import pytest

from lifetime_support import root_for
from ops_sim.v5.assembly_attitude import ComponentAxisBinding
from ops_sim.v5.environment_ageing import (
    ACCOUNTING_LAW, EnvironmentAgeingState, EnvironmentAgeingWork, initial_state,
    propose, retention, state_metrics,
)
from ops_sim.v5.environment_thermal import effective_network, thermal_network
from ops_sim.v5.lifecycle_execution import build_model
from ops_sim.v5.lifecycle_prepared import (
    MAX_CACHE_ENTRIES, MAX_OPERATIONAL_UNITS, METHOD, PreparedRuntime,
    _Seal, _exact_tree, prepare_runtime,
)

SOURCE = '6' * 64


@pytest.fixture
def authorities():
    # root_for is shared by older tests. Never mutate its lru-cached authority.
    root = deepcopy(root_for(600))
    model = build_model(root)
    return root, model


@pytest.fixture
def prepared(authorities):
    root, model = authorities
    return prepare_runtime(root, model, 'ACTUAL', SOURCE)


def sample(runtime, *, elapsed=0, pv=0., thermal=0., selected=0):
    state = initial_state(runtime.environment_policy, runtime.root.start_seconds,
                          runtime.baseline, 1.)
    return replace(state, clock_seconds=Q(runtime.root.start_seconds) + Q(elapsed),
                   calendar_seconds=Q(runtime.environment_policy.initial_calendar_seconds) + Q(elapsed),
                   pv_exposure_seconds=pv, thermal_exposure_seconds=thermal,
                   selected_cuts=selected)


def arguments(runtime):
    return runtime._external_policy, runtime._external_baseline


def test_owned_topology_and_policies_are_real_independent_input_copies(prepared, authorities):
    root, model = authorities
    assert type(prepared) is PreparedRuntime
    assert prepared.root is not root and prepared.model is not model
    assert _exact_tree(prepared.root) == _exact_tree(root)
    assert _exact_tree(prepared.model) == _exact_tree(model)
    assert prepared.baseline is not model.simulation_inputs.spacecraft_configuration.thermal.network
    for owned, external in zip(prepared.baseline.nodes,
                               model.simulation_inputs.spacecraft_configuration.thermal.network.nodes):
        assert owned is not external
        assert owned.heat_capacity_j_per_k is not external.heat_capacity_j_per_k
        assert owned.heat_capacity_j_per_k.provenance is not external.heat_capacity_j_per_k.provenance
    assert prepared.environment_policy is not root.environment_ageing_policy
    assert tuple(row[0] for row in prepared.thermal_nodes) == tuple(n.node_id.value for n in prepared.baseline.nodes)
    assert len(prepared.heat_routes) == 7 and len(prepared.construction_lines) == 8
    assert prepared.construction_lines[0] is not model.configuration.lines[0]
    assert prepared.frame_authorities[2] is not model.assembly
    assert prepared.provenance
    assert prepared.environment_policy.method == root.environment_ageing_policy.method == ACCOUNTING_LAW
    prepared.check_boundary(root, model)


@pytest.mark.parametrize('elapsed,pv,thermal', [(0, 0., 0.), (Q(1, 3), .125, .25),
                                              (120, 67.25, 120.), (300, 124.5, 280.)])
def test_full_exact_environment_output_matches_independent_existing_owners(prepared, elapsed, pv, thermal):
    policy, baseline = arguments(prepared)
    state = sample(prepared, elapsed=elapsed, pv=pv, thermal=thermal, selected=3)
    expected = effective_network(policy, state, baseline)
    actual = prepared.effective_environment(policy, state, baseline)
    assert _exact_tree(actual) == _exact_tree(expected)
    assert _exact_tree(prepared.environment_metrics(policy, state, baseline)) == _exact_tree(state_metrics(policy, state, baseline))
    assert prepared.environment_retention(policy, state, baseline).hex() == retention(policy, state).hex()
    assert prepared.validate_environment_binding((actual, policy, state), baseline) == thermal_network((expected, policy, state), baseline)
    work = prepared.snapshot()
    assert work['coefficient_attempts'] == work['coefficient_realizations'] == work['state_digests'] == 1
    assert work['cache_hits'] == 3


def test_one_realization_shared_by_metrics_retention_and_binding(prepared, monkeypatch):
    import ops_sim.v5.lifecycle_prepared as owner
    old = owner._derive
    calls = []

    def recorded(policy, state, baseline):
        calls.append((policy, state, baseline))
        return old(policy, state, baseline)

    monkeypatch.setattr(owner, '_derive', recorded)
    policy, baseline = arguments(prepared)
    state = sample(prepared, elapsed=60, pv=30., thermal=60.)
    actual = prepared.effective_environment(policy, state, baseline)
    prepared.environment_metrics(policy, deepcopy(state), baseline)
    prepared.environment_retention(policy, state, baseline)
    prepared.validate_environment_binding((actual, policy, state), baseline)
    assert len(calls) == 1
    assert calls[0][0] is prepared.environment_policy
    assert calls[0][1] is not state
    assert calls[0][2] is prepared.baseline


def test_dynamic_state_is_not_frozen_at_initial_age_and_cache_is_bounded(prepared):
    policy, baseline = arguments(prepared)
    initial = prepared.effective_environment(policy, sample(prepared), baseline)
    results = []
    for i in range(1, MAX_CACHE_ENTRIES + 4):
        results.append(prepared.effective_environment(policy,
                       sample(prepared, elapsed=i * 30, pv=float(i * 15), thermal=float(i * 30), selected=i), baseline))
    assert any(_exact_tree(x.network) != _exact_tree(initial.network) for x in results)
    work = prepared.snapshot()
    assert work['cache_entries'] == MAX_CACHE_ENTRIES
    assert work['cache_evictions'] == 4
    assert work['coefficient_realizations'] == MAX_CACHE_ENTRIES + 4


def test_signed_zero_and_every_exact_history_field_participate_in_cache_key(prepared):
    policy, baseline = arguments(prepared)
    a = sample(prepared, pv=0.)
    b = replace(a, pv_exposure_seconds=-0.)
    c = replace(a, selected_cuts=1)
    d = replace(a, clock_seconds=a.clock_seconds + Q(1, 7))
    for state in (a, b, c, d):
        prepared.effective_environment(policy, state, baseline)
    assert prepared.snapshot()['coefficient_realizations'] == 4
    assert prepared.effective_environment(policy, deepcopy(a), baseline) is prepared.effective_environment(policy, a, baseline)


def test_history_alias_mutation_cannot_modify_retained_result(prepared):
    policy, baseline = arguments(prepared)
    state = sample(prepared)
    first = prepared.effective_environment(policy, state, baseline)
    first_tree = _exact_tree(first)
    object.__setattr__(state, 'pv_exposure_seconds', 15.)
    second = prepared.effective_environment(policy, state, baseline)
    assert second is not first
    assert _exact_tree(first) == first_tree
    assert first.state_identity != second.state_identity


def test_caller_policy_mutation_refused_and_owned_values_unchanged(prepared):
    policy, baseline = arguments(prepared)
    old = policy.pv_floor_fraction
    try:
        object.__setattr__(policy, 'pv_floor_fraction', old * .9)
        with pytest.raises(ValueError, match='drift'):
            prepared.effective_environment(policy, sample(prepared), baseline)
        assert prepared.environment_policy.pv_floor_fraction == old
    finally:
        object.__setattr__(policy, 'pv_floor_fraction', old)
    assert prepared.snapshot()['environment_failed'] == 1


def test_caller_nested_provenance_mutation_refused_without_alias(prepared):
    policy, baseline = arguments(prepared)
    p = baseline.nodes[0].emissivity.provenance
    old = p.rationale
    owned = prepared.baseline.nodes[0].emissivity.provenance.rationale
    try:
        object.__setattr__(p, 'rationale', 'changed caller provenance')
        with pytest.raises(ValueError, match='drift'):
            prepared.environment_metrics(policy, sample(prepared), baseline)
        assert prepared.baseline.nodes[0].emissivity.provenance.rationale == owned
    finally:
        object.__setattr__(p, 'rationale', old)


@pytest.mark.parametrize('which', ['root', 'model'])
def test_public_boundary_detects_deep_mutation(prepared, authorities, which):
    root, model = authorities
    target, field = (root.scenario, 'namespace') if which == 'root' else (model.limits, 'max_interval_seconds')
    old = getattr(target, field)
    try:
        object.__setattr__(target, field, old + '-changed' if type(old) is str else old + 1)
        with pytest.raises(ValueError, match='drift'):
            prepared.check_boundary(root, model)
    finally:
        object.__setattr__(target, field, old)
    work = prepared.snapshot()
    assert work['boundary_attempts'] == work['boundary_failed'] == 1
    assert work['boundary_completed'] == 0


@pytest.mark.parametrize('kwargs', [dict(source_binding='7' * 64), dict(role='FORECAST'), dict(role=True)])
def test_foreign_source_or_role_refused_at_boundary(prepared, authorities, kwargs):
    with pytest.raises(ValueError, match='foreign'):
        prepared.check_boundary(*authorities, **kwargs)


def test_equal_foreign_root_or_model_is_not_the_admitted_boundary(prepared, authorities):
    root, model = authorities
    with pytest.raises(ValueError, match='foreign'):
        prepared.check_boundary(deepcopy(root), model)
    with pytest.raises(ValueError, match='foreign'):
        prepared.check_boundary(root, deepcopy(model))


def test_established_checkpoint_root_codec_may_refresh_same_derived_hash(prepared, authorities):
    from ops_sim.v5.lifecycle_document import dumps_root
    root, model = authorities
    identity = root.identity
    dumps_root(root)
    assert type(root.identity) is str and root.identity == identity
    prepared.check_boundary(root, model)
    assert prepared.snapshot()['boundary_completed'] == 1


def test_hardware_readmission_and_checkpoint_codec_preserve_canonical_axis_bits(prepared, authorities):
    from ops_sim.v5.lifecycle_document import dumps_root
    root, model = authorities
    previous = tuple(b.local_axis for b in model.capabilities)
    for binding in model.capabilities:
        binding.__post_init__()
    assert all(b.local_axis is not old for b, old in zip(model.capabilities, previous))
    assert tuple(tuple(x.hex() for x in b.local_axis) for b in model.capabilities) == tuple(
        tuple(x.hex() for x in old) for old in previous)
    dumps_root(root)
    prepared.check_boundary(root, model)


@pytest.mark.parametrize('changed', [
    (1., -0., 0.), (1., 0., -0.), (1., 0, 0.), (True, 0., 0.),
    (1., 0., 0., 0.), (1., 0.), [1., 0., 0.], (1., 2**-52, 0.),
])
def test_axis_refresh_rejects_signed_zero_type_shape_or_value_drift(changed):
    binding = ComponentAxisBinding('panel', 'panel', 'panel-frame', (1., 0., 0.),
                                   'Synthetic declared unit axis for strict seal checking')
    seal = _Seal(binding)
    object.__setattr__(binding, 'local_axis', changed)
    with pytest.raises(ValueError, match='canonical local axis drift'):
        seal.guard()


def test_axis_refresh_rejects_foreign_tuple_and_float_subclasses():
    class ForeignTuple(tuple):
        pass

    class ForeignFloat(float):
        pass

    for changed in (ForeignTuple((1., 0., 0.)), (ForeignFloat(1.), 0., 0.)):
        binding = ComponentAxisBinding('panel', 'panel', 'panel-frame', (1., 0., 0.),
                                       'Synthetic declared unit axis for strict seal checking')
        seal = _Seal(binding)
        object.__setattr__(binding, 'local_axis', changed)
        with pytest.raises(ValueError, match='canonical local axis drift'):
            seal.guard()


def test_equal_foreign_capability_cannot_replace_admitted_authority(prepared, authorities):
    root, model = authorities
    # LifecyclePhysicalModel forwards capabilities to PublicPhysicalModel.
    # Replace the real frozen authority edge, not the forwarding attribute.
    previous = model.base.capabilities
    try:
        object.__setattr__(model.base, 'capabilities', tuple(deepcopy(b) for b in previous))
        with pytest.raises(ValueError, match='immutable field drift: capabilities'):
            prepared.check_boundary(root, model)
    finally:
        object.__setattr__(model.base, 'capabilities', previous)


def test_unrelated_local_axis_field_has_no_canonical_refresh_permission():
    @dataclass(frozen=True, slots=True)
    class OtherOwner:
        local_axis: tuple

    record = OtherOwner((1., 0., 0.))
    seal = _Seal(record)
    object.__setattr__(record, 'local_axis', tuple(x for x in record.local_axis))
    with pytest.raises(ValueError, match='immutable field drift: local_axis'):
        seal.guard()


def test_roles_have_distinct_owned_realizations_and_ledgers(authorities):
    actual = prepare_runtime(*authorities, 'ACTUAL', SOURCE)
    forecast = prepare_runtime(*authorities, 'FORECAST', SOURCE)
    p, baseline = arguments(actual)
    state = sample(actual, elapsed=60, pv=20., thermal=60.)
    a = actual.effective_environment(p, state, baseline)
    f = forecast.effective_environment(p, state, baseline)
    assert a is not f and a.network is not f.network
    assert _exact_tree(a) == _exact_tree(f)
    assert actual.snapshot()['role'] == 'ACTUAL' and forecast.snapshot()['role'] == 'FORECAST'
    actual.effective_environment(p, state, baseline)
    assert actual.snapshot()['cache_hits'] == 1 and forecast.snapshot()['cache_hits'] == 0


@pytest.mark.parametrize('part', ['policy', 'baseline'])
def test_equal_foreign_static_authority_not_admitted(prepared, part):
    p, baseline = arguments(prepared)
    if part == 'policy':
        p = deepcopy(p)
    else:
        baseline = deepcopy(baseline)
    with pytest.raises(ValueError, match='foreign'):
        prepared.effective_environment(p, sample(prepared), baseline)


@pytest.mark.parametrize('field', ['policy_identity', 'baseline_network_identity'])
def test_stale_history_provenance_refused(prepared, field):
    p, baseline = arguments(prepared)
    with pytest.raises(ValueError, match='stale/foreign'):
        prepared.effective_environment(p, replace(sample(prepared), **{field: 'f' * 64}), baseline)


def test_state_subclass_and_hostile_numeric_type_refused(prepared):
    class StateSubclass(EnvironmentAgeingState):
        pass

    p, baseline = arguments(prepared)
    state = sample(prepared)
    with pytest.raises(TypeError, match='exact environment state'):
        prepared.effective_environment(p, StateSubclass(**asdict(state)), baseline)
    object.__setattr__(state, 'selected_cuts', True)
    with pytest.raises((TypeError, ValueError)):
        prepared.effective_environment(p, state, baseline)


@pytest.mark.parametrize('bad', ['state_identity', 'policy_identity', 'baseline_identity', 'network'])
def test_effective_binding_matches_complete_exact_network_and_provenance(prepared, bad):
    p, baseline = arguments(prepared)
    state = sample(prepared, elapsed=60, pv=30., thermal=60.)
    e = prepared.effective_environment(p, state, baseline)
    changed = replace(e, **{bad: baseline if bad == 'network' else 'a' * 64})
    with pytest.raises(ValueError, match='provenance'):
        prepared.validate_environment_binding((changed, p, state), baseline)
    assert prepared.snapshot()['binding_refusals'] == 1


def test_mutating_a_returned_frozen_result_is_detected_before_cache_reuse(prepared):
    p, baseline = arguments(prepared)
    state = sample(prepared)
    e = prepared.effective_environment(p, state, baseline)
    parameter = e.network.nodes[0].emissivity
    old = parameter.value
    try:
        object.__setattr__(parameter, 'value', old * .9)
        with pytest.raises(ValueError, match='drift'):
            prepared.effective_environment(p, state, baseline)
    finally:
        object.__setattr__(parameter, 'value', old)


def test_legacy_none_binding_retains_identity_and_does_not_derive(prepared):
    p, baseline = arguments(prepared)
    assert prepared.validate_environment_binding(None, baseline) is baseline
    assert prepared.snapshot()['coefficient_realizations'] == 0


@pytest.mark.parametrize('binding', [(), [], (None,), (None, None, None), 'validated'])
def test_binding_exact_shape_and_owner_required(prepared, binding):
    with pytest.raises(TypeError):
        prepared.validate_environment_binding(binding, prepared.baseline)


def test_original_scientific_failed_trial_and_accounting_law_are_unchanged(prepared):
    p, baseline = arguments(prepared)
    work = EnvironmentAgeingWork()
    state = sample(prepared)
    after = propose(p, state, baseline, state.clock_seconds, state.clock_seconds + 1,
                    True, 0., work)
    with pytest.raises(ValueError):
        propose(p, state, baseline, state.clock_seconds + 1, state.clock_seconds + 2,
                True, 0., work)
    before = asdict(work)
    prepared.effective_environment(p, after, baseline)
    prepared.environment_metrics(p, after, baseline)
    prepared.validate_environment_binding((prepared.effective_environment(p, after, baseline), p, after), baseline)
    assert asdict(work) == before
    assert work.proposed == 2 and work.returned == work.failed == 1
    assert work.control_units == 2 * (256 + 64 * (len(p.emissivity) + len(p.conductance)))
    assert state.selected_cuts == 0 and after.selected_cuts == 1
    assert prepared.snapshot()['method'] == METHOD


def test_operational_cap_refuses_before_derivation_and_does_not_refund(prepared):
    p, baseline = arguments(prepared)
    prepared._work['control_units_reserved'] = MAX_OPERATIONAL_UNITS
    with pytest.raises(ValueError, match='PREPARATION_WORK_LIMIT'):
        prepared.effective_environment(p, sample(prepared), baseline)
    assert prepared._work['control_units_reserved'] == MAX_OPERATIONAL_UNITS
    assert prepared._work['coefficient_attempts'] == 0


def test_public_runtime_is_frozen_and_snapshot_is_only_detached_data(prepared):
    with pytest.raises(FrozenInstanceError):
        prepared.role = 'FORECAST'
    snapshot = prepared.snapshot()
    snapshot['coefficient_realizations'] = 999
    assert prepared.snapshot()['coefficient_realizations'] == 0


@pytest.mark.parametrize('role,source', [('actual', SOURCE), (True, SOURCE), ('ACTUAL', 'bad'), ('ACTUAL', False)])
def test_exact_role_and_source_admission(authorities, role, source):
    with pytest.raises((TypeError, ValueError)):
        prepare_runtime(*authorities, role, source)


def test_stale_root_identity_refused_without_rewriting_caller(authorities):
    root, model = authorities
    object.__setattr__(root, '_identity', 'f' * 64)
    with pytest.raises(ValueError, match='stale/noncanonical'):
        prepare_runtime(root, model, 'ACTUAL', SOURCE)
    assert root.identity == 'f' * 64


def test_foreign_model_value_refused_before_prepared_state(authorities):
    root, model = authorities
    changed = replace(model, limits=replace(model.limits, max_interval_seconds=1))
    with pytest.raises(ValueError, match='foreign physical model'):
        prepare_runtime(root, changed, 'ACTUAL', SOURCE)


def test_no_trusted_validated_flag_or_global_activation(authorities):
    with pytest.raises(TypeError):
        prepare_runtime(*authorities, 'ACTUAL', SOURCE, validated=True)
