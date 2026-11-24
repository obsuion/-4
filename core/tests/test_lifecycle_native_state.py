"""Owned-static adapter unit contracts; no altered scientific work ledgers."""
from copy import deepcopy
from dataclasses import asdict, fields, replace
from fractions import Fraction as Q
import json

import pytest

from lifetime_support import root_for
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.context import SimulationContext
from ops_sim.v5.construction_service import ConstructionServicePolicy, service_physical_substep
from ops_sim.v5.environment_forcing import _case
from ops_sim.v5.integration_time import RationalSeconds
from ops_sim.v5.lifecycle_backend import PREPARED_PYTHON
from ops_sim.v5.lifecycle_execution import start_lifecycle
from ops_sim.v5.lifecycle_native_state import (
    MAX_CONTROL_UNITS, BackendServiceBinding, PreparedServiceAdapter,
    contact_service_binding,
)
from ops_sim.v5.lifecycle_prepared import _copy_frozen, _exact_tree
from ops_sim.v5.long_mission import LongMissionActionForcing
from ops_sim.v5.long_mission_continuation import _scientific

from ops_sim.v5.lifecycle_backend import current_source_binding
SOURCE = current_source_binding()


def encoded(value):
    return json.dumps(_scientific(value), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf8')


@pytest.fixture(scope='module')
def template():
    root = deepcopy(root_for(600))
    # Static admission/initial owner construction only. No lifecycle advance,
    # orbit query, request acquisition or campaign is requested by this helper.
    return start_lifecycle(root, backend=PREPARED_PYTHON, source_binding=SOURCE).physical


@pytest.fixture
def physical(template):
    return replace(template,
        context=deepcopy(template.context, {id(template.context.inputs): template.context.inputs}),
        runtime_work=deepcopy(template.runtime_work),
        construction=replace(template.construction, work=deepcopy(template.construction.work)),
        harness=replace(template.harness, work=deepcopy(template.harness.work)),
        service_allocation_work=deepcopy(template.service_allocation_work),
        battery_port_work=deepcopy(template.battery_port_work),
        environment_ageing_work=deepcopy(template.environment_ageing_work))


def arguments(physical):
    model = physical.inputs.model
    case = _case(model.environment.profile[0], False)
    forcing = LongMissionActionForcing(case.eps_inputs.load_breakdown, False,
        case.eps_inputs.incidence_angle_deg, model.routing, case.thermal_inputs,
        case.heat_source_inputs)
    runtime = physical.prepared_runtime
    policy = model.environment_ageing_policy
    history = physical.environment_ageing_state
    baseline = physical.context.inputs.spacecraft_configuration.thermal.network
    binding = (runtime.effective_environment(policy, history, baseline), policy, history)
    args = (physical.context, RationalSeconds(1, 1), forcing, case.eps_inputs,
            model.protection, None)
    kwargs = dict(compilation=physical.construction.compilation,
                  service_policy=ConstructionServicePolicy(), service_mode='NORMAL',
                  service_work=physical.service_allocation_work,
                  work=physical.construction.work, limits=model.construction_limits,
                  start_seconds=Q(physical.context.simulation_time_seconds),
                  end_seconds=Q(physical.context.simulation_time_seconds + 1),
                  battery_port_policy=model.battery_port_policy,
                  battery_port_state=physical.battery_port_state,
                  battery_port_work=physical.battery_port_work,
                  environment_binding=binding)
    return args, kwargs


def counters(physical):
    return (asdict(physical.construction.work), asdict(physical.harness.work),
            asdict(physical.service_allocation_work), asdict(physical.battery_port_work),
            asdict(physical.environment_ageing_work))


def test_compilation_and_hardware_copied_once_without_numerical_recompilation(physical):
    before = encoded(counters(physical))
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    assert adapter.compilation is not physical.construction.compilation
    assert adapter.hardware is not physical.harness.hardware
    assert adapter.compilation.configuration is physical.prepared_runtime.model.configuration
    assert adapter.hardware.configuration is physical.prepared_runtime.model.configuration
    assert adapter.hardware.design is physical.prepared_runtime.model.assembly
    assert adapter.hardware.augmentation_inputs is physical.prepared_runtime.model.augmentation
    assert _exact_tree(adapter.compilation) == _exact_tree(physical.construction.compilation)
    assert _exact_tree(adapter.hardware) == _exact_tree(physical.harness.hardware)
    assert encoded(counters(physical)) == before
    receipt = adapter.snapshot()
    assert receipt['numerical_recompilations'] == receipt['dynamic_states_cached'] == 0
    assert receipt['initializations'] == 1


def test_service_view_uses_owned_static_and_current_dynamic_objects(physical):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    args, kwargs = arguments(physical)
    original_inputs = physical.context.inputs
    view_args, view_kwargs = adapter._arguments(physical, args, kwargs)
    view, _, forcing, eps, policy, _ = view_args
    assert type(view) is type(physical.context) and view is not physical.context
    assert view.inputs is physical.prepared_runtime.model.simulation_inputs
    assert view.spacecraft_state is physical.context.spacecraft_state
    assert view.ground_data_delivery_state is physical.context.ground_data_delivery_state
    assert view_kwargs['compilation'] is adapter.compilation
    assert view_kwargs['work'] is physical.construction.work
    assert view_kwargs['battery_port_work'] is physical.battery_port_work
    assert view_kwargs['service_work'] is physical.service_allocation_work
    assert forcing.routing_config is physical.prepared_runtime.model.routing
    assert forcing.thermal_inputs is physical.prepared_runtime.model.configuration.thermal_boundaries
    assert eps is args[3] and policy is physical.prepared_runtime.model.protection
    assert physical.context.inputs is original_inputs


def test_repeat_leaf_views_do_not_deepcopy_or_recompile_and_do_not_cache_state(physical, monkeypatch):
    import ops_sim.v5.lifecycle_native_state as owner
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    args, kwargs = arguments(physical)

    def forbidden(*args, **kwargs):
        raise AssertionError('per-leaf frozen copy was attempted')

    monkeypatch.setattr(owner, '_copy_frozen', forbidden)
    first, _ = adapter._arguments(physical, args, kwargs)
    physical.context.spacecraft_state.battery.energy_wh -= .125
    second, _ = adapter._arguments(physical, args, kwargs)
    assert first[0] is not second[0]
    assert second[0].spacecraft_state is physical.context.spacecraft_state
    assert second[0].spacecraft_state.battery.energy_wh == physical.context.spacecraft_state.battery.energy_wh
    assert adapter.snapshot()['dynamic_states_cached'] == 0


def test_real_python_service_with_owned_inputs_has_complete_exact_science_and_work(physical, template):
    other = replace(template,
        context=deepcopy(template.context, {id(template.context.inputs): template.context.inputs}),
        construction=replace(template.construction, work=deepcopy(template.construction.work)),
        harness=replace(template.harness, work=deepcopy(template.harness.work)),
        service_allocation_work=deepcopy(template.service_allocation_work),
        battery_port_work=deepcopy(template.battery_port_work),
        environment_ageing_work=deepcopy(template.environment_ageing_work))
    pure_args, pure_kwargs = arguments(other)
    expected = service_physical_substep(*pure_args, **pure_kwargs)
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    args, kwargs = arguments(physical)
    actual = adapter.service_call(physical, service_physical_substep, *args, **kwargs)
    assert encoded(actual) == encoded(expected)
    assert encoded(CheckpointState.from_context(physical.context)) == encoded(CheckpointState.from_context(other.context))
    assert encoded(counters(physical)) == encoded(counters(other))
    assert physical.context.inputs is args[0].inputs
    assert adapter.snapshot()['service_returned'] == 1


def test_foreign_callable_is_not_dispatch_authority(physical):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    args, kwargs = arguments(physical)
    with pytest.raises(ValueError, match='unbound coupled numerical callable'):
        adapter.service_call(physical, lambda *a, **k: None, *args, **kwargs)


@pytest.mark.parametrize('target', ['external_wire', 'owned_wire', 'external_hardware'])
def test_static_copy_or_source_mutation_refused_before_service(physical, target):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    if target == 'external_wire':
        obj, field = physical.construction.compilation.branches[0].wire, 'one_way_length_m'
    elif target == 'owned_wire':
        obj, field = adapter.compilation.branches[0].wire, 'one_way_length_m'
    else:
        obj, field = physical.harness.hardware, 'method'
    old = getattr(obj, field)
    try:
        object.__setattr__(obj, field, old + 1. if type(old) is float else old + '-changed')
        with pytest.raises(ValueError, match='drift'):
            adapter.guard(physical)
    finally:
        object.__setattr__(obj, field, old)


def test_equal_new_paid_static_records_rebind_without_retaining_forecast_history(physical):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    before = encoded(counters(physical))
    physical.construction = replace(physical.construction, compilation=_copy_frozen(physical.construction.compilation))
    physical.harness = replace(physical.harness, hardware=_copy_frozen(physical.harness.hardware))
    adapter.guard(physical)
    assert adapter.snapshot()['rebindings'] == 1
    assert encoded(counters(physical)) == before
    assert adapter._external_compilation is physical.construction.compilation
    assert adapter._external_hardware is physical.harness.hardware


def test_changed_compiled_branch_cannot_reuse_owned_static_copy(physical):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    c = physical.construction.compilation
    branch = replace(c.branches[0], polyline_length_m=c.branches[0].polyline_length_m + 1.)
    physical.construction = replace(physical.construction, compilation=replace(c, branches=(branch, *c.branches[1:])))
    with pytest.raises(ValueError, match='changed compiled geometry'):
        adapter.guard(physical)


def test_source_role_and_context_authority_are_bound(physical):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    args, kwargs = arguments(physical)
    foreign = deepcopy(args[0].inputs)
    changed = replace(args[0], inputs=foreign)
    with pytest.raises(ValueError, match='foreign private service context'):
        adapter._arguments(physical, (changed, *args[1:]), kwargs)
    original = physical.prepared_runtime
    physical.prepared_runtime = physical.backend_context.forecast
    with pytest.raises(ValueError, match='foreign physical/source/role'):
        adapter.guard(physical)
    physical.prepared_runtime = original


def test_explicit_contact_binding_and_no_arbitrary_public_callable(physical):
    from ops_sim.v5.lifecycle_service_contact import execute_service_contact_plan
    binding = contact_service_binding(physical)
    assert type(binding) is BackendServiceBinding
    binding.check_context(physical.context)
    with pytest.raises(TypeError, match='exact private contact backend binding'):
        execute_service_contact_plan(None, None, consumed_contacts=None, policy=None,
            integration=None, compilation=None, work=None, limits=None, service_policy=None,
            service_state=None, service_work=None, allocation_work=None,
            backend_service=lambda *a, **k: None)


def test_contact_token_calls_only_the_current_bound_service_route(physical, monkeypatch):
    import ops_sim.v5.lifecycle_backend as owner
    binding = contact_service_binding(physical)
    args, kwargs = arguments(physical)
    calls = []

    def captured(p, reference, *a, **kw):
        calls.append((p, reference, a, kw))
        return 'synthetic dispatch marker'

    monkeypatch.setattr(owner, 'service_call', captured)
    assert binding.call(*args, **kwargs) == 'synthetic dispatch marker'
    assert len(calls) == 1 and calls[0][0] is physical
    assert calls[0][1] is service_physical_substep
    assert calls[0][2][0] is physical.context


def test_adapter_operational_exhaustion_preserves_all_scientific_counters(physical):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    before = encoded(counters(physical))
    adapter._work['control_units_reserved'] = MAX_CONTROL_UNITS
    with pytest.raises(ValueError, match='STATIC_VIEW_WORK_LIMIT'):
        adapter.guard(physical)
    assert encoded(counters(physical)) == before


def test_public_boundary_guard_checks_original_root_not_just_derived_copy(physical):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    root = physical.prepared_runtime._external_root
    previous = root.scenario.namespace
    try:
        object.__setattr__(root.scenario, 'namespace', previous + '-changed')
        with pytest.raises(ValueError, match='drift'):
            adapter.guard(physical, public_boundary=True)
    finally:
        object.__setattr__(root.scenario, 'namespace', previous)


def test_owned_static_comparand_trees_are_bounded_and_never_rebuilt_per_leaf(physical, monkeypatch):
    import ops_sim.v5.lifecycle_native_state as owner
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    assert type(adapter._static_sources) is tuple and len(adapter._static_sources) == 12
    assert type(adapter._static_trees) is tuple and len(adapter._static_trees) == 12
    assert adapter._static_trees == tuple(_exact_tree(x) for x in adapter._static_sources)
    args, kwargs = arguments(physical)
    original = owner._exact_tree
    incoming = []

    def checked(value, *a, **kw):
        # Caller data remains freshly checked. Merely retaining a cache must
        # never turn a legitimate incoming comparison into an omitted check.
        assert not any(value is x for x in adapter._static_sources if x is not None)
        incoming.append(value)
        return original(value, *a, **kw)

    monkeypatch.setattr(owner, '_exact_tree', checked)
    before = dict(adapter._work)
    first, _ = adapter._arguments(physical, args, kwargs)
    physical.context.spacecraft_state.battery.energy_wh -= .125
    second, _ = adapter._arguments(physical, args, kwargs)
    assert first[0] is not second[0]
    assert second[0].spacecraft_state is physical.context.spacecraft_state
    assert second[0].spacecraft_state.battery.energy_wh == physical.context.spacecraft_state.battery.energy_wh
    assert len(incoming) == 12  # six incoming static comparisons per action view
    assert all(any(value is expected for value in incoming) for expected in
               (args[4], kwargs['limits'], kwargs['service_policy'],
                kwargs['battery_port_policy'], args[2].routing_config, args[2].thermal_inputs))
    # Every previous guard/view reservation remains paid. The enlarged owned
    # seal also charges all newly retained static records; no fee is skipped.
    per_view = adapter._owned_seal.nodes + 8 + len(fields(SimulationContext)) + 16
    assert adapter._work['control_units_reserved'] == before['control_units_reserved'] + 2 * per_view
    assert adapter._work['guards'] == before['guards'] + 2
    assert adapter._work['static_views'] == before['static_views'] + 2
    assert adapter._work['dynamic_states_cached'] == 0


@pytest.mark.parametrize('field', ['_static_sources', '_static_trees'])
def test_equal_replacement_of_private_static_cache_refused(physical, field):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    original = getattr(adapter, field)
    replacement = tuple(list(original))
    assert replacement is not original and replacement == original
    setattr(adapter, field, replacement)
    with pytest.raises(ValueError, match='static adapter binding drift'):
        adapter.guard(physical)


@pytest.mark.parametrize('target', ['protection', 'routing', 'transmitter', 'thermal', 'port'])
def test_mutated_owned_comparand_refused_without_scientific_commit(physical, target):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    args, kwargs = arguments(physical)
    model = physical.prepared_runtime.model
    if target == 'protection':
        obj, field, changed = model.protection, 'rationale', model.protection.rationale + '-changed'
    elif target == 'routing':
        obj, field, changed = model.routing, 'routes', tuple(reversed(model.routing.routes))
        assert changed != obj.routes
    elif target == 'transmitter':
        obj, field = model.transmitter.electrical_power_w, 'value'
        changed = obj.value + 1.
    elif target == 'thermal':
        obj, field = model.configuration.thermal_boundaries, 'node_boundaries'
        changed = tuple(reversed(obj.node_boundaries))
        assert changed != obj.node_boundaries
    else:
        obj, field = model.battery_port_policy, 'resistance_reference_ohm'
        assert obj is not None
        changed = obj.resistance_reference_ohm + .01
    original = getattr(obj, field)
    science = encoded((CheckpointState.from_context(physical.context), counters(physical)))
    try:
        object.__setattr__(obj, field, changed)
        with pytest.raises(ValueError, match='drift'):
            adapter.service_call(physical, service_physical_substep, *args, **kwargs)
        assert encoded((CheckpointState.from_context(physical.context), counters(physical))) == science
        assert adapter._work['service_attempts'] == adapter._work['service_failed'] == 1
        assert adapter._work['service_returned'] == adapter._work['static_views'] == 0
    finally:
        object.__setattr__(obj, field, original)


def test_equal_foreign_owned_policy_cannot_replace_the_cached_authority(physical):
    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    model = physical.prepared_runtime.model
    original = model.base.protection
    replacement = _copy_frozen(original)
    assert replacement is not original and _exact_tree(replacement) == _exact_tree(original)
    try:
        object.__setattr__(model.base, 'protection', replacement)
        with pytest.raises(ValueError, match='owned static comparand authority drift'):
            adapter.guard(physical)
    finally:
        object.__setattr__(model.base, 'protection', original)


def test_cached_comparands_keep_incoming_exact_type_and_value_checks(physical):
    class HostileText(str):
        def __eq__(self, other):
            raise AssertionError('caller equality must not run')

    adapter = PreparedServiceAdapter(physical.prepared_runtime, physical)
    args, kwargs = arguments(physical)
    policy = _copy_frozen(args[4])
    object.__setattr__(policy, 'rationale', HostileText(policy.rationale))
    science = encoded((CheckpointState.from_context(physical.context), counters(physical)))
    with pytest.raises(TypeError, match='frozen exact input records'):
        adapter.service_call(physical, service_physical_substep,
                             *(*args[:4], policy, args[5]), **kwargs)
    assert encoded((CheckpointState.from_context(physical.context), counters(physical))) == science
    assert adapter._work['service_failed'] == 1
    changed = dict(kwargs, limits=replace(kwargs['limits'],
                                         max_line_calls=kwargs['limits'].max_line_calls - 1))
    with pytest.raises(ValueError, match='foreign private service configuration'):
        adapter.service_call(physical, service_physical_substep, *args, **changed)
    assert encoded((CheckpointState.from_context(physical.context), counters(physical))) == science
    assert adapter._work['service_attempts'] == adapter._work['service_failed'] == 2
    assert adapter._work['service_returned'] == adapter._work['static_views'] == 0
