"""B64 admission/ownership/boundary tests; no long numerical campaign."""
from copy import copy, deepcopy
from dataclasses import replace
from fractions import Fraction as Q
import sys

import pytest

from lifetime_support import root_for
from ops_sim.v5.environment_ageing import initial_state, retention, state_metrics
from ops_sim.v5.environment_thermal import effective_network
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.lifecycle_execution import build_model
from ops_sim.v5.lifecycle_job_prepared import (
    MAX_CACHE_ENTRIES, MAX_CONTROL_UNITS, JobInputAdmission, PreparedRoleState,
    admit_job_root, prepare_job_runtime,
)
from ops_sim.v5.lifecycle_prepared import _exact_tree

SOURCE = 'b' * 64
BUILD = {'format': 'SYNTHETIC_METADATA_BINDING_ONLY', 'version': 1}


@pytest.fixture
def raw(): return dumps_root(deepcopy(root_for(600)))


@pytest.fixture
def job(raw):
    root, admission = admit_job_root(raw, SOURCE, build_binding=BUILD)
    return prepare_job_runtime(admission, root)


def history(role, n=0):
    h = initial_state(role.environment_policy, role.root.start_seconds, role.baseline, 1.)
    return replace(h, clock_seconds=Q(role.root.start_seconds)+n,
                   calendar_seconds=Q(role.environment_policy.initial_calendar_seconds)+n,
                   pv_exposure_seconds=float(n)/2, thermal_exposure_seconds=float(n), selected_cuts=n)


def env(role, state):
    return role.effective_environment(role._external_policy, state, role._external_baseline)


def test_original_decoder_and_model_factory_called_once_for_both_roles(raw):
    import ops_sim.v5.lifecycle_job_prepared as owner
    codes = {owner._LOAD_ROOT.__code__: 'decode', owner._BUILD_MODEL.__code__: 'build'}
    counts = {'decode': 0, 'build': 0}
    previous = sys.getprofile()
    def profile(frame, event, arg):
        if event == 'call' and frame.f_code in codes: counts[codes[frame.f_code]] += 1
    sys.setprofile(profile)
    try:
        root, admission = admit_job_root(raw, SOURCE, build_binding=BUILD)
        prepared = prepare_job_runtime(admission, root)
        assert prepared.actual is not prepared.forecast
    finally: sys.setprofile(previous)
    assert counts == {'decode': 1, 'build': 1}
    receipt = prepared.receipt()['preparation']
    assert receipt['raw_admissions'] == receipt['model_build_attempts'] == receipt['model_build_completed'] == 1
    assert receipt['static_copy_attempts'] == receipt['static_copy_completed'] == 1


def test_combined_static_copy_has_no_external_alias_and_preserves_internal_aliases(job):
    assert job.static.root is not job.external_root
    assert job.static.model is not job.external_model
    assert job.static.model.base is job.static.root.base.model
    assert job.external_model.base is job.external_root.base.model
    assert _exact_tree((job.static.root, job.static.model)) == _exact_tree((job.external_root, job.external_model))
    assert job.static.baseline is not job.external_model.simulation_inputs.spacecraft_configuration.thermal.network
    assert job.actual.static is job.forecast.static is job.static
    assert job.actual._cache is not job.forecast._cache
    assert job.actual._work is not job.forecast._work


def test_authorities_are_not_copy_or_pickle_data(raw, job):
    import pickle
    root, admission = admit_job_root(raw, SOURCE)
    for authority in (admission, job, job.actual, job.transaction()):
        with pytest.raises(TypeError): copy(authority)
        with pytest.raises(TypeError): deepcopy(authority)
        with pytest.raises(TypeError): pickle.dumps(authority)
    with pytest.raises(TypeError): PreparedRoleState(job, 'ACTUAL', object())
    assert type(admission) is JobInputAdmission


def test_input_token_is_exact_foreign_root_refused_and_single_use(raw):
    root, admission = admit_job_root(raw, SOURCE)
    with pytest.raises(ValueError, match='admission'):
        prepare_job_runtime(admission, deepcopy(root))
    job = prepare_job_runtime(admission, root)
    with pytest.raises(ValueError, match='admission'):
        prepare_job_runtime(admission, root)
    assert job.receipt()['preparation']['model_build_completed'] == 1


@pytest.mark.parametrize('field,value', [('source_binding', 'c'*64), ('_build_raw', b'null'), ('_raw', b'{}')])
def test_input_token_full_binding_drift_refused(raw, field, value):
    root, admission = admit_job_root(raw, SOURCE, build_binding=BUILD)
    object.__setattr__(admission, field, value)
    with pytest.raises(ValueError, match='admission'):
        prepare_job_runtime(admission, root)


def test_saved_model_admitted_against_one_original_static_factory(raw):
    root, admission = admit_job_root(raw, SOURCE)
    saved_model = deepcopy(build_model(root))
    job = prepare_job_runtime(admission, root, restored_model=saved_model)
    assert job.external_model is saved_model
    assert _exact_tree(job.static.model) == _exact_tree(saved_model)
    assert job.receipt()['preparation']['model_build_completed'] == 1


def test_wrong_saved_model_refuses_before_private_role_creation(raw):
    root, admission = admit_job_root(raw, SOURCE)
    saved = deepcopy(build_model(root))
    object.__setattr__(saved.limits, 'max_interval_seconds', saved.limits.max_interval_seconds+1)
    with pytest.raises(ValueError, match='saved model'):
        prepare_job_runtime(admission, root, restored_model=saved)
    assert admission.receipt()['phase'] == 'FAILED_PREPARATION'


def test_role_realization_requires_active_transaction_and_exact_role(job):
    with pytest.raises(ValueError, match='requires external transaction'): env(job.actual, history(job.actual))
    with pytest.raises(ValueError): job.role('actual')
    with pytest.raises(ValueError): job.transaction(deepcopy(job.external_root), job.external_model)
    with job.transaction():
        with pytest.raises(ValueError): job.forecast.check_boundary(job.external_root, job.external_model, role='ACTUAL')


def test_exact_environment_equivalence_and_separate_roles(job):
    actual, forecast = job.actual, job.forecast
    h = history(actual, 120)
    expected = effective_network(actual._external_policy, h, actual._external_baseline)
    with job.transaction():
        a = env(actual, h); f = env(forecast, deepcopy(h))
        assert a is not f
        assert _exact_tree(a) == _exact_tree(f) == _exact_tree(expected)
        assert actual.environment_retention(actual._external_policy, h, actual._external_baseline).hex() == retention(actual._external_policy, h).hex()
        assert _exact_tree(actual.environment_metrics(actual._external_policy, h, actual._external_baseline)) == _exact_tree(state_metrics(actual._external_policy, h, actual._external_baseline))
        assert actual.validate_environment_binding((a, actual._external_policy, h), actual._external_baseline) is a.network
    assert actual.snapshot()['coefficient_realizations'] == forecast.snapshot()['coefficient_realizations'] == 1
    assert actual.snapshot()['cache_hits'] == 3
    assert forecast.snapshot()['cache_hits'] == 0


def test_nested_public_transactions_keep_outer_active_and_single_use(job):
    outer = job.transaction()
    with outer:
        env(job.actual, history(job.actual, 1))
        with job.transaction() as inner:
            assert job.require_transaction() is inner
            env(job.forecast, history(job.forecast, 2))
        assert job.require_transaction() is outer
        with pytest.raises(ValueError): inner.require_active()
        env(job.actual, history(job.actual, 3))
    with pytest.raises(ValueError): outer.require_active()
    with pytest.raises(ValueError):
        with outer: pass
    receipt = job.receipt()['control']
    assert receipt['transaction_attempts'] == receipt['transaction_completed'] == 2


def test_full_graph_seals_are_not_repeated_for_each_private_environment_leaf(job):
    # Count actual schema/owner scan receipts, not implementation-mirroring mocks.
    with job.transaction():
        before = job._schema.codec.receipt()['counters']['full_schema_scans']
        for _ in range(7): env(job.actual, history(job.actual, 1))
        after = job._schema.codec.receipt()['counters']['full_schema_scans']
        assert after == before
    assert job.actual.snapshot()['coefficient_realizations'] == 1


def test_external_and_owned_mutations_refuse_at_entry_and_exit(job):
    original = job.external_root.policy.max_transitions
    object.__setattr__(job.external_root.policy, 'max_transitions', original+1)
    with pytest.raises(ValueError, match='drift'):
        with job.transaction(): pass
    object.__setattr__(job.external_root.policy, 'max_transitions', original)
    with pytest.raises(ValueError, match='drift'):
        with job.transaction():
            env(job.actual, history(job.actual, 1))
            object.__setattr__(job.static.model.limits, 'max_interval_seconds', job.static.model.limits.max_interval_seconds+1)
    assert job.actual.snapshot()['coefficient_attempts'] == 1
    assert job.receipt()['control']['transaction_failed'] == 2


def test_callback_preserves_primary_error_and_records_seal_failure(job):
    class PrimaryFailure(LookupError): pass
    def callback():
        object.__setattr__(job.external_root.policy, 'max_transitions', job.external_root.policy.max_transitions+1)
        raise PrimaryFailure('original callback')
    with pytest.raises(PrimaryFailure, match='original callback') as caught:
        with job.transaction() as tx:
            env(job.actual, history(job.actual, 1))
            tx.callback(callback)
    assert any('exit also failed' in item for item in caught.value.__notes__)
    assert job.receipt()['secondary_errors']
    assert job.actual.snapshot()['coefficient_realizations'] == 1


def test_evicted_realization_is_retained_through_transaction_exit(job):
    with pytest.raises(ValueError, match='drift'):
        with job.transaction():
            first = env(job.actual, history(job.actual))
            for n in range(1, MAX_CACHE_ENTRIES+2): env(job.actual, history(job.actual, n))
            object.__setattr__(first.network.nodes[0].emissivity, 'value', .123456)
    assert job.actual.snapshot()['cache_evictions'] >= 2


def test_finite_control_exhaustion_retains_reservation_and_primary_error(job):
    with pytest.raises(ValueError, match='CONTROL_LIMIT'):
        with job.transaction():
            job._work['control_units_reserved'] = MAX_CONTROL_UNITS
            env(job.actual, history(job.actual))
    assert job.receipt()['control']['control_units_reserved'] == MAX_CONTROL_UNITS


def test_process_change_and_closed_job_cannot_reuse_authority(job, monkeypatch):
    import ops_sim.v5.lifecycle_job_prepared as owner
    original = owner.os.getpid
    monkeypatch.setattr(owner.os, 'getpid', lambda: original()+1)
    with pytest.raises(ValueError, match='stale job'): job.check_boundary(job.external_root, job.external_model)
    monkeypatch.setattr(owner.os, 'getpid', original)
    job.close()
    with pytest.raises(ValueError, match='stale job'): job.role('ACTUAL')


def test_typed_construction_thermal_alias_is_explicit_paid_and_identity_bound():
    from test_lifecycle_b65 import started_pair
    from ops_sim.v5.lifecycle_job_prepared import MAX_GRAPH_NODES
    state, _ = started_pair(); context = state.backend_context; job = context.job
    role = context.actual
    network = job.static.model.configuration.thermal_network
    assert network is not role.baseline
    with context.transaction():
        with pytest.raises(ValueError, match='foreign baseline'):
            role.validate_environment_binding(None, network)
        before = dict(job.receipt()['control'])
        typed = context._static_for(state.physical)  # root's one explicit registration
        after = job.receipt()['control']
        assert typed.configuration is job.static.model.configuration
        assert after['public_boundaries'] == before['public_boundaries']+1
        assert after['control_units_reserved']-before['control_units_reserved'] == 64+4*MAX_GRAPH_NODES
        assert job.admit_thermal_alias(typed) is network
        assert job.receipt()['control'] == after  # same owner is idempotent
        assert role.validate_environment_binding(None, network) is role.baseline
        h = history(role, 1)
        realized = role.effective_environment(role.environment_policy, h, network)
        assert _exact_tree(realized) == _exact_tree(effective_network(role.environment_policy, h, role.baseline))
        assert job.forecast.validate_environment_binding(None, network) is job.forecast.baseline
        assert job.actual._cache is not job.forecast._cache
        with pytest.raises(ValueError, match='foreign baseline'):
            role.validate_environment_binding(None, deepcopy(network))
        with pytest.raises(TypeError, match='exact typed thermal owner'):
            job.admit_thermal_alias(network)


def test_registered_thermal_alias_leaf_checks_do_not_rewalk_static_graph():
    from test_lifecycle_b65 import started_pair
    state, _ = started_pair(); context = state.backend_context; job = context.job
    calls=[]; old=sys.getprofile()
    def watch(frame,event,unused):
        if event=='call'and frame.f_code is _exact_tree.__code__:calls.append(frame.f_locals)
    with context.transaction():
        typed=context._static_for(state.physical)
        network=typed.configuration.thermal_network
        try:
            sys.setprofile(watch)
            for _ in range(4):assert context.actual.validate_environment_binding(None,network)is context.actual.baseline
        finally:sys.setprofile(old)
    assert calls==[]


def test_registered_thermal_alias_static_mutation_is_refused_at_public_exit():
    from test_lifecycle_b65 import started_pair
    state, _ = started_pair(); context=state.backend_context
    with pytest.raises(ValueError,match='drift'):
        with context.transaction():
            typed=context._static_for(state.physical)
            parameter=typed.configuration.thermal_network.nodes[0].heat_capacity_j_per_k
            object.__setattr__(parameter,'value',parameter.value+1.)
