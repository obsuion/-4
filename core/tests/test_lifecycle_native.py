"""Required compiled B63 object-kernel equality; no silent import fallback."""
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction as Q
import importlib.machinery
import json
import math
from types import FunctionType

import pytest

from ops_sim.v5 import _lifecycle_native as native
from ops_sim.v5 import battery_port as port_reference
from ops_sim.v5 import battery_port_construction as coupled_reference
from ops_sim.v5 import thermal as thermal_reference
from ops_sim.v5 import degradation as damage_reference
from ops_sim.v5 import lifecycle_quiet as quiet_reference
from ops_sim.v5.battery_port import BatteryPortPolicy, BatteryPortState, BatteryPortWork
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.integration_time import RationalSeconds
from ops_sim.v5.long_mission_continuation import _scientific
from test_battery_port import reference_policy
from test_battery_port_coupling import leaf
from test_lifecycle_quiet import ScalarState, scalar_step, values


def scientific_bytes(value):
    return json.dumps(_scientific(value), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def test_binary_extension_and_explicit_object_arithmetic_capability():
    assert any(native.__file__.endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES)
    assert isinstance(native.__loader__, importlib.machinery.ExtensionFileLoader)
    for name in ('service_port_substep', 'evaluate_port_eps', 'battery_port_transition',
                 'complete_port_cut', 'compute_thermal_substep_transition',
                 'compute_battery_degradation_substep', 'integrate_quiet_hold', 'quiet_error_norm'):
        assert not isinstance(getattr(native, name), FunctionType)
    capability = native.native_capability()
    assert capability['method'] == 'B63_PREPARED_NATIVE_V1'
    assert capability['ordered_python_object_arithmetic'] is True
    assert capability['canary'] is True and all(capability['capability_screen'].values())
    assert capability['direct_c_libm'] is False
    assert capability['actual_math_fsum'] is True
    assert capability['speedup'] == 'UNPROVEN'
    assert capability['changes_scientific_work'] is False
    assert len(capability['reference_sources']) == 6


def test_monotone_entry_monitor_is_detached_strict_data_with_no_reset_api():
    before = native.native_entry_counts()
    capability = native.native_capability()
    assert set(before) == {'format', 'method', 'limit', 'total', 'counts', 'exhausted',
        'gil_held', 'reset_available', 'python_implementation', 'python_cache_tag',
        'python_version', 'platform', 'module_basename', 'source_binding', 'scope'}
    assert before['format'] == 'B63_MONOTONE_NATIVE_ENTRY_COUNTS_V1'
    assert before['method'] == 'B63_COMPILED_NUMERICAL_ENTRY_MONITOR_V1'
    assert before['limit'] == 2**56 and type(before['limit']) is int
    assert type(before['total']) is int and sum(before['counts'].values()) == before['total']
    assert all(type(n) is int and 0 <= n <= before['limit'] for n in before['counts'].values())
    assert before['gil_held'] is True and before['reset_available'] is False
    assert before['exhausted'] is False
    assert before['scope'] == 'OPERATIONAL_ENTRY_ATTEMPTS_NOT_SCIENTIFIC_WORK_OR_DYNAMIC_STATE'
    assert before['source_binding'] == 'ACTUAL_EXTENSION_AND_SOURCE_BUILD_RECEIPT_REQUIRED'
    declaration = capability['entry_monitor']
    assert declaration['method'] == before['method'] and declaration['limit'] == before['limit']
    assert set(declaration['names']) == set(before['counts']) and len(declaration['names']) == 17
    for key in ('python_implementation', 'python_cache_tag', 'python_version', 'platform', 'module_basename'):
        assert before[key] == capability[key]
    # Canaries and repeated readers are not numerical owner entries.
    assert native.native_entry_counts() == before
    expected = deepcopy(before)
    before['counts']['service_port_substep'] += 11
    before['total'] += 11
    assert native.native_entry_counts() == expected
    for name in ('_native_enter', '_native_entry_counters', '_native_entry_total',
                 '_native_entry_limit', '_native_entry_exhausted'):
        assert name not in vars(native)
    assert not hasattr(native, 'reset_native_entry_counts')


_ENTRY_REFUSALS = (
    ('constant_power_load', (None, None, None), {}),
    ('generated_power_line', (None, None, None), {}),
    ('solve_port', (None, None, None), dict(charging=False, current_limit=None,
        voltage_min=None, voltage_max=None)),
    ('ocv_resistance', (None, None, None, None, None), {}),
    ('battery_port_transition', (None, None), dict(energy_wh=None, usable_wh=None,
        temperature_k=None, generation_w=None, load_w=None, duration=None,
        charge_bus_limit_w=None, discharge_bus_limit_w=None, work=None)),
    ('_transition', (None,) * 10, {}),
    ('advance_port_state', (None, None, None), dict(start=None, end=None,
        representative_temperature_k=None, work=None)),
    ('compute_thermal_substep_transition', (None, None, None), dict(duration=None)),
    ('_thermal_compute_thermal_interval_transition', (None, None, None, None), dict(dt_seconds=None)),
    ('compute_battery_degradation_substep', (None, None, None, None), {}),
    ('_damage_compute_battery_degradation', (None, None, None, None), {}),
    ('compute_explicit_solar_degradation_transition', (None, None), {}),
    ('evaluate_port_eps', (None,) * 6, dict(port_policy=None, port_state=None, port_work=None)),
    ('service_port_substep', (None,) * 6, dict(compilation=None, service_policy=None,
        service_mode=None, service_work=None)),
    ('complete_port_cut', (None,) * 12, {}),
    ('quiet_error_norm', (None,) * 5, {}),
    ('integrate_quiet_hold', (None, None, None), dict(policy=None, controller=None,
        work=None, clone_context=None, state_values=None, step=None)),
)


@pytest.mark.parametrize('name,args,kwargs', _ENTRY_REFUSALS)
def test_every_native_owner_attempt_is_retained_before_its_original_guard(name, args, kwargs):
    before = native.native_entry_counts()
    with pytest.raises((TypeError, ValueError, AttributeError)):
        getattr(native, name)(*args, **kwargs)
    after = native.native_entry_counts()
    assert after['total'] == before['total'] + 1
    assert after['counts'] == {key: value + (key == name) for key, value in before['counts'].items()}
    assert after['exhausted'] is False
    assert native.native_entry_counts() == after


def test_python_attributes_cannot_replace_private_compiled_counter_ownership(monkeypatch):
    before = native.native_entry_counts()
    monkeypatch.setattr(native, '_native_entry_counters', {'service_port_substep': 0}, raising=False)
    monkeypatch.setattr(native, '_native_entry_total', -1, raising=False)
    monkeypatch.setattr(native, '_native_entry_limit', 1, raising=False)
    assert native.native_entry_counts() == before
    with pytest.raises(TypeError):
        native.ocv_resistance(None, None, None, None, None)
    after = native.native_entry_counts()
    assert after['total'] == before['total'] + 1
    assert after['counts']['ocv_resistance'] == before['counts']['ocv_resistance'] + 1
    assert after['limit'] == 2**56


@pytest.mark.parametrize('charging', [False, True])
@pytest.mark.parametrize('resistance,power', [(0., 0.), (0., 80.), (.001, .000001),
                                            (1., 64.), (2., 30.), (.1, 400.)])
def test_full_port_solution_and_boundaries_match(charging, resistance, power):
    kwargs = dict(charging=charging, current_limit=1000., voltage_min=1., voltage_max=1000.)
    expected = port_reference.solve_port(20., resistance, power, **kwargs)
    actual = native.solve_port(20., resistance, power, **kwargs)
    assert type(actual) is port_reference.BatteryPortSolution
    assert scientific_bytes(actual) == scientific_bytes(expected)


@pytest.mark.parametrize('energy,generation,load,seconds', [
    (100., 0., 20., Q(60)), (100., 60., 0., Q(60)),
    (0., 0., 20., Q(1, 8)), (200., 60., 0., Q(1, 8)),
    (.000001, 0., 1000., Q(1)), (199.999999, 1000., 0., Q(1)),
])
def test_full_port_transition_exact_result_and_distinct_paid_ledgers(energy, generation, load, seconds):
    policy, state = reference_policy(), BatteryPortState(Q(0))
    original = scientific_bytes((policy, state))
    results = []
    for function in (port_reference.battery_port_transition, native.battery_port_transition):
        work = BatteryPortWork()
        result = function(policy, state, energy_wh=energy, usable_wh=200., temperature_k=298.15,
                          generation_w=generation, load_w=load,
                          duration=RationalSeconds.from_fraction(seconds),
                          charge_bus_limit_w=1000., discharge_bus_limit_w=1000., work=work)
        results.append((result, asdict(work)))
    assert type(results[1][0]) is port_reference.BatteryPortTransition
    assert scientific_bytes(results[1]) == scientific_bytes(results[0])
    assert scientific_bytes((policy, state)) == original
    assert results[1][1]['reserved'] == results[1][1]['returned'] == 1


@pytest.mark.parametrize('bad', [dict(energy_wh=-1.), dict(energy_wh=True),
                                dict(temperature_k=float('nan')), dict(generation_w=2**2000)])
def test_port_refusals_preserve_exact_exception_and_nonrefundable_work(bad):
    outputs = []
    for function in (port_reference.battery_port_transition, native.battery_port_transition):
        work = BatteryPortWork()
        kwargs = dict(energy_wh=100., usable_wh=200., temperature_k=298.15,
                      generation_w=0., load_w=20., duration=RationalSeconds(1, 1),
                      charge_bus_limit_w=1000., discharge_bus_limit_w=1000., work=work)
        kwargs.update(bad)
        try:
            function(reference_policy(), BatteryPortState(Q(0)), **kwargs)
        except BaseException as error:
            outputs.append((type(error), str(error), asdict(work)))
        else:
            pytest.fail('invalid input unexpectedly returned')
    assert outputs[0] == outputs[1]
    assert outputs[1][2]['reserved'] == 1


def run_coupled(function, origin, *, adjustments=None):
    s, forcing, eps, history, work, allocation, kwargs = deepcopy(origin)
    extra = {} if adjustments is None else dict(internal_heat_adjustments_w=adjustments(s))
    result = function(s.context, RationalSeconds(1, 1), forcing, eps,
                      s.inputs.protection, None, **kwargs, **extra)
    return result, CheckpointState.from_context(s.context), asdict(work), asdict(allocation), asdict(s.construction.work), history


@pytest.mark.parametrize('mode', ['NORMAL', 'SAFE', 'POWER_OFF', 'RECOVERY'])
@pytest.mark.parametrize('sunlit,limited', [(False, False), (True, False), (False, True)])
def test_wide_coupled_allocation_heat_thermal_damage_and_commit_equal(mode, sunlit, limited):
    policy = replace(BatteryPortPolicy(), maximum_discharge_current_a=.001) if limited else BatteryPortPolicy()
    origin = leaf(policy, sunlit=sunlit, mode=mode)
    expected = run_coupled(coupled_reference.service_port_substep, origin)
    actual = run_coupled(native.service_port_substep, origin)
    assert scientific_bytes(actual) == scientific_bytes(expected)
    part, carrier = actual[0]
    assert type(part) is coupled_reference.PortConstructionPhysicalResult
    assert type(carrier) is coupled_reference.PortEPSResult
    assert actual[-1].selected_steps == 0
    assert part.port_state_after.selected_steps == 1
    assert actual[2]['ageing_reserved'] == actual[2]['ageing_returned'] == 1
    if limited:
        assert not part.service.obc_serviceable
        assert actual[3]['bisection_trials'] > 0


def test_compiled_wide_owner_does_not_delegate_whole_core_to_reference_functions(monkeypatch):
    origin = leaf()
    expected = run_coupled(coupled_reference.service_port_substep, origin)

    def forbidden(*args, **kwargs):
        raise AssertionError('copied compiled owner delegated to old full numerical function')

    for module, names in ((coupled_reference, ('service_port_substep', 'evaluate_port_eps', 'complete_port_cut')),
                          (port_reference, ('battery_port_transition', 'solve_port', 'ocv_resistance', 'advance_port_state')),
                          (thermal_reference, ('compute_thermal_substep_transition',)),
                          (damage_reference, ('compute_battery_degradation_substep',))):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    actual = run_coupled(native.service_port_substep, origin)
    assert scientific_bytes(actual) == scientific_bytes(expected)


@pytest.mark.parametrize('failure', ['moving_unpowered', 'late_ageing'])
def test_late_refusal_atomicity_exact_error_and_paid_trial_counters(failure):
    policy = (replace(BatteryPortPolicy(), maximum_discharge_current_a=.001)
              if failure == 'moving_unpowered' else
              replace(BatteryPortPolicy(), initial_resistance_damage=64., calendar_damage_per_second=1.))
    origin = leaf(policy)
    outcomes = []
    for function in (coupled_reference.service_port_substep, native.service_port_substep):
        s, forcing, eps, history, work, allocation, kwargs = deepcopy(origin)
        before = scientific_bytes(CheckpointState.from_context(s.context))
        extra = (dict(internal_heat_adjustments_w=((s.context.inputs.spacecraft_configuration.thermal.network.bus_node_id, -.001),))
                 if failure == 'moving_unpowered' else {})
        try:
            function(s.context, RationalSeconds(1, 1), forcing, eps, s.inputs.protection,
                     None, **kwargs, **extra)
        except BaseException as error:
            outcomes.append((type(error), str(error), asdict(work), asdict(allocation),
                             asdict(s.construction.work), scientific_bytes(CheckpointState.from_context(s.context))))
        else:
            pytest.fail('expected paid physical refusal')
        assert scientific_bytes(CheckpointState.from_context(s.context)) == before
        assert history.selected_steps == 0
    assert outcomes[0] == outcomes[1]
    assert outcomes[1][2]['reserved'] > 0
    if failure == 'late_ageing':
        assert outcomes[1][2]['ageing_reserved'] == outcomes[1][2]['ageing_refused'] == 1


@pytest.mark.parametrize('near,regime_cross,rate', [(False, False, 0.), (False, False, .001),
                                                (True, False, 0.), (False, True, 0.)])
def test_compiled_full_two_half_selection_schedule_and_work_exact(near, regime_cross, rate):
    policy = quiet_reference.QuietIntegrationPolicy()
    outputs = []
    for function in (quiet_reference.integrate_quiet_hold, native.integrate_quiet_hold):
        original = ScalarState()
        work = quiet_reference.QuietWork()
        calls = []
        regime = (lambda a, b: ('before' if b <= 3 else 'cross' if a < 3 < b else 'after',)) if regime_cross else (lambda a, b: ('steady',))
        result = function(original, Q(0), Q(9 if near or regime_cross else 60),
                          policy=policy, controller=quiet_reference.QuietControllerState(Q(0), 60), work=work,
                          clone_context=deepcopy, state_values=values,
                          step=scalar_step(rate=rate, regime=regime, near=near, calls=calls))
        assert original == ScalarState()
        outputs.append((asdict(result), asdict(work), calls))
    assert scientific_bytes(outputs[0]) == scientific_bytes(outputs[1])


@pytest.mark.parametrize('known', [False, True])
def test_quiet_original_exceptions_exactly_once_and_no_work_refund(known):
    outputs = []
    for function in (quiet_reference.integrate_quiet_hold, native.integrate_quiet_hold):
        work, calls = quiet_reference.QuietWork(), []
        original = ScalarState()

        def fail(state, a, b):
            state.energy = 0.
            if known:
                raise quiet_reference.QuietTrialRefusal(ValueError('declared native test refusal'))
            raise RuntimeError('declared native test unknown failure')

        try:
            function(original, Q(0), Q(60), policy=quiet_reference.QuietIntegrationPolicy(),
                     controller=quiet_reference.QuietControllerState(Q(0), 60), work=work,
                     clone_context=deepcopy, state_values=values, step=scalar_step(fail=fail, calls=calls))
        except BaseException as error:
            outputs.append((type(error), str(error), asdict(work), calls))
        else:
            pytest.fail('expected original callback exception')
        assert original == ScalarState()
    assert scientific_bytes((outputs[0][1], outputs[0][2:])) == scientific_bytes((outputs[1][1], outputs[1][2:]))
    assert outputs[0][0] is outputs[1][0]
    if not known:
        assert len(outputs[1][3]) == 1 and outputs[1][2]['unknown_leaf_calls'] == 1


def test_quiet_quota_failure_preserves_paid_prefix_and_original_context():
    policy = replace(quiet_reference.QuietIntegrationPolicy(), max_total_leaf_calls=2)
    outputs = []
    for function in (quiet_reference.integrate_quiet_hold, native.integrate_quiet_hold):
        work, original = quiet_reference.QuietWork(), ScalarState()
        with pytest.raises(ValueError, match='CUMULATIVE_LEAF_QUOTA') as captured:
            function(original, Q(0), Q(60), policy=policy,
                     controller=quiet_reference.QuietControllerState(Q(0), 60), work=work,
                     clone_context=deepcopy, state_values=values, step=scalar_step(rate=0.))
        assert original == ScalarState()
        outputs.append((str(captured.value), asdict(work)))
    assert outputs[0] == outputs[1]
    assert outputs[1][1]['reserved_leaf_calls'] == outputs[1][1]['returned_leaf_calls'] == 2


def test_quiet_boundary_reopen_uses_explicit_state_controller_and_work_exactly():
    def execute(function):
        p, work = quiet_reference.QuietIntegrationPolicy(), quiet_reference.QuietWork()
        first = function(ScalarState(), Q(0), Q(20), policy=p,
                         controller=quiet_reference.QuietControllerState(Q(0), 60), work=work,
                         clone_context=deepcopy, state_values=values, step=scalar_step())
        second = function(deepcopy(first.context), Q(20), Q(60), policy=p,
                          controller=deepcopy(first.controller), work=deepcopy(work),
                          clone_context=deepcopy, state_values=values, step=scalar_step())
        return asdict(first), asdict(second), asdict(work)
    assert scientific_bytes(execute(native.integrate_quiet_hold)) == scientific_bytes(execute(quiet_reference.integrate_quiet_hold))


def test_complete_quiet_error_norm_uses_integrals_and_unit_scales():
    p = quiet_reference.EnvironmentQuietIntegrationPolicy()
    initial = (('energy_wh', 80.), ('port_current_a', 1.), ('environment_pv_exposure_seconds', 0.))
    full = quiet_reference.QuietSample(initial, (('served_load_wh', 1.),), ('steady',))
    half = quiet_reference.QuietSample(initial, (('served_load_wh', .6),), ('steady',))
    expected = quiet_reference.quiet_error_norm(initial, full, half, half, p)
    actual = native.quiet_error_norm(initial, full, half, half, p)
    assert actual.hex() == expected.hex() and actual > 1.


def test_ordered_wire_products_and_math_fsum_not_reassociated():
    # These exact source-vs-loss products are intentionally different public
    # identities; compare every returned field, never a width or tolerance.
    from ops_sim.v5.design_trade_physics import WireSpec, constant_power_load, generated_power_line
    from test_design_trade_physics import wire
    spec = wire()
    for pure, compiled in ((constant_power_load, native.constant_power_load),
                           (generated_power_line, native.generated_power_line)):
        for power in (0., .125, 3.7, 12.):
            assert scientific_bytes(compiled(spec, 28., power)) == scientific_bytes(pure(spec, 28., power))
