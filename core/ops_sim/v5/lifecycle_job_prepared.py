"""B64 paid, process-local job preparation and closed private transactions.

Only genuinely immutable static data is shared by ACTUAL and FORECAST.  A
saved receipt is DATA, never an admission or continuation capability.  Static
graph/schema checks occur at external transaction boundaries; dynamic state
and arithmetic checks remain the numerical owners' responsibility.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from hashlib import sha256
import json
import os
import sys
from types import FunctionType

from .environment_ageing import EnvironmentAgeingPolicy, EnvironmentAgeingState, admit_network, digest, retention
from .environment_thermal import EffectiveEnvironmentNetwork, _derive
from .lifecycle_document import loads_root as _LOAD_ROOT
from .lifecycle_execution import build_model as _BUILD_MODEL
from .lifecycle_prepared import MAX_GRAPH_BYTES, MAX_GRAPH_NODES, _Seal, _exact_tree, _hash
from .prepared_input_codec import PreparedInputCodec, _function_signature
from .thermal_config import ThermalNetworkConfig
from . import lifecycle_generation as _generation_owner

METHOD = 'B69_OWNED_PREPARED_JOB_V2'
CONTROL_METHOD = 'B69_JOB_PREPARATION_CONTROL_V2'
MAX_CONTROL_UNITS = 2**48
MAX_CACHE_ENTRIES = 8
MAX_TRANSACTION_REALIZATIONS = 4096
MAX_TRANSACTION_DEPTH = 64
_ROLE_WORK_FIELDS = ('requests', 'failures', 'coefficient_attempts', 'coefficient_realizations',
                     'cache_hits', 'cache_misses', 'cache_evictions', 'binding_refusals')
_JOB_WORK_FIELDS = ('method', 'control_units_reserved', 'static_preparations',
                    'transaction_attempts', 'transaction_completed', 'transaction_failed',
                    'transaction_exits', 'callback_checks', 'environment_requests',
                    'coefficient_realizations', 'projections', 'report_parts', 'public_boundaries','progress_frontiers')
_FACTORY = object()


def _generation_function_state(function, retained=None, depth=0):
    """Seal the small generation owner independently of its own predicates.

    Strong references prevent identity reuse. Closure cells and their current
    contents are pinned as well as code/defaults, including wrapped functions.
    This is fixed-size control validation, never an input-graph traversal.
    """
    if type(function) is not FunctionType or depth > 16:
        raise ValueError('B66 bounded generation callable seal')
    signature = _function_signature(function, retained)
    closure = function.__closure__
    if retained is not None:
        retained.extend((closure, *(closure or ())))
    cells = []
    for cell in closure or ():
        try: value = cell.cell_contents
        except ValueError:
            cells.append((id(cell), 'EMPTY'))
            continue
        if retained is not None: retained.append(value)
        cells.append((id(cell), id(value),
            _generation_function_state(value, retained, depth + 1)
            if type(value) is FunctionType else None))
    return signature, id(closure), tuple(cells)


def _generation_owner_binding():
    owner = _generation_owner._Generation
    retained = [owner, _generation_owner, owner.__bases__, owner.__mro__]
    attributes = tuple(vars(owner).items())
    retained.extend(value for _, value in attributes)
    functions = tuple((name, fn, _generation_function_state(fn, retained))
                      for name, fn in attributes if type(fn) is FunctionType)
    factory = _generation_owner.enable
    factory_state = _generation_function_state(factory, retained)
    globals_ = tuple((name, getattr(_generation_owner, name))
                     for name in ('_KEY', 'METHOD', 'os', 'threading'))
    return (owner, owner.__bases__, owner.__mro__, attributes, functions,
            factory, factory_state, globals_, tuple(retained))


_GENERATION_OWNER_BINDING = _generation_owner_binding()


def _guard_generation_owner(pin=_GENERATION_OWNER_BINDING, *, compiled=None):
    """Check BEFORE calling generation cheap/closed/factory/cleanup methods.

    In particular this seal does not invoke a method on the object being
    checked. A foreign callback cannot make its own mutated predicate decide
    whether validation of that predicate is needed.
    """
    if compiled is not None:
        from .lifecycle_exact_guards import ExactGuardSession
        if type(compiled)is not ExactGuardSession:raise TypeError("B69 exact generation guard session")
        job=compiled._job;gate=job._guard_gate;t=type(gate)
        if (gate is not job._guard_gate_pin or t.__module__!='_cython_3_2_4' or
                t.__name__!='cython_function_or_method' or t.__flags__&384!=384 or
                getattr(gate,'__module__',None)!='ops_sim.v5._lifecycle_typed65' or
                getattr(gate,'__name__',None)!='dispatch_exact_guard'):
            raise ValueError('B70 independent generation dispatch origin')
        gate(job._guard_arena,job._guard_binding,compiled,job,'generation',pin);return
    owner = pin[0]
    if (_GENERATION_OWNER_BINDING is not pin or
            sys.modules.get(_generation_owner.__name__) is not _generation_owner or
            _generation_owner._Generation is not owner or
            owner.__bases__ is not pin[1] or owner.__mro__ is not pin[2] or
            tuple(vars(owner)) != tuple(name for name, _ in pin[3]) or
            any(vars(owner)[name] is not value for name, value in pin[3]) or
            _generation_owner.enable is not pin[5] or
            _generation_function_state(pin[5]) != pin[6] or
            any(getattr(_generation_owner, name) is not value for name, value in pin[7])):
        raise ValueError('B66 generation class/factory/callable drift')
    for name, function, state in pin[4]:
        if _generation_function_state(function) != state:
            raise ValueError('B66 generation callable drift: ' + name)


def _runtime():
    return (os.getpid(), sys.implementation.name, sys.version, sys.executable,
            sys.implementation.cache_tag, sys.platform)


def _data(value):
    """Detach complete finite JSON DATA; never round-trip a physical model."""
    def check(v, depth=0):
        if depth > 64:
            raise ValueError('B64 bounded metadata depth')
        if v is None or type(v) in (str, bool, int):
            return
        if type(v) is float:
            from math import isfinite
            if not isfinite(v):
                raise ValueError('B64 finite metadata')
            return
        if type(v) is list:
            for x in v: check(x, depth + 1)
            return
        if type(v) is dict and all(type(k) is str for k in v):
            for x in v.values(): check(x, depth + 1)
            return
        raise TypeError('B64 exact JSON metadata')
    check(value)
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False).encode('utf8')
    if len(raw) > MAX_GRAPH_BYTES:
        raise ValueError('B64 metadata byte capacity')
    return raw


def _copy_owned(value, memo=None):
    """Deep-copy the combined admitted graph, retaining its internal aliases.

    This is the exact frozen-record domain of _exact_tree, not arbitrary
    __deepcopy__/reduce hooks.  Memo IDs only deduplicate strongly retained
    original objects during this one copy; they grant no admission.
    """
    if memo is None: memo = {}
    owner = type(value)
    if value is None or owner in (str, int, bool, bytes, float): return value
    if isinstance(value, Enum): return value
    old = memo.get(id(value))
    if old is not None:
        if old[0] is not value: raise ValueError('B64 copy memo identity')
        return old[1]
    if owner is Fraction: result = Fraction(value.numerator, value.denominator)
    elif owner is Decimal: result = Decimal(value.as_tuple())
    elif owner is tuple: result = tuple(_copy_owned(x, memo) for x in value)
    elif is_dataclass(value) and owner.__dataclass_params__.frozen:
        result = object.__new__(owner)
        memo[id(value)] = (value, result)
        for f in fields(owner): object.__setattr__(result, f.name, _copy_owned(getattr(value, f.name), memo))
        return result
    else: raise TypeError('B64 admitted frozen copy domain')
    memo[id(value)] = (value, result)
    return result


class _SchemaSeal:
    """Strongly retained complete registry/constructor/function seal."""
    __slots__ = ('codec', 'functions', 'properties', 'retained', '_pins', '__weakref__')
    def __init__(self):
        from . import lifecycle_document, lifecycle_execution, lifecycle_prepared, environment_thermal, environment_ageing, environment_lifecycle
        self.codec = PreparedInputCodec()
        self.codec.__enter__()  # Private schema capability, never returned.
        self.retained = []
        declarations = ((lifecycle_document, 'loads_root', _LOAD_ROOT),
                        (lifecycle_execution, 'build_model', _BUILD_MODEL),
                        (lifecycle_prepared, '_exact_tree', _exact_tree),
                        (environment_thermal, '_derive', _derive),
                        (environment_ageing, 'retention', retention),
                        (environment_ageing, 'digest', digest))
        declarations += tuple((environment_ageing,name,getattr(environment_ageing,name))for name in ('guard','admit_network','propose','_propose_validated'))
        declarations += tuple((environment_lifecycle,name,getattr(environment_lifecycle,name))for name in ('prepare_cut','_guard_history','guard','propose','retention'))
        declarations += tuple((lifecycle_execution, name, getattr(lifecycle_execution, name))
                              for name in ('LifecyclePhysicalModel', 'LifecyclePhysicsLimits',
                                           'LifecycleWorld', 'horizon_inputs'))
        declarations += tuple((lifecycle_execution,name,getattr(lifecycle_execution,name))for name in ('progress_projection','progress_frontier_projection','_progress_projection'))
        declarations += tuple((sys.modules[__name__], name, globals()[name]) for name in
                              ('_LOAD_ROOT', '_BUILD_MODEL', '_copy_owned', '_runtime',
                               'admit_job_root', 'prepare_job_runtime', '_data', '_Seal', '_exact_tree',
                               '_generation_function_state', '_generation_owner_binding',
                               '_guard_generation_owner'))
        from . import lifecycle_prepared_report as selected_report
        declarations += tuple((selected_report,name,getattr(selected_report,name)) for name in
            ('consume_prepared_part','consume_prepared_result','consume_selected_result',
             '_consume_selected_part','_consume_selected_result','_duration','_port','_service'))
        extra, properties = [], []
        own_classes = (_SchemaSeal, JobInputAdmission, PreparedRoleState, PreparedTransaction, _ThermalStaticAlias,
                       PreparedJobRuntime, PreparedStaticModel, _Realization, _Seal, EnvironmentAgeingPolicy,
                       lifecycle_execution.LifecyclePhysicalModel,
                       lifecycle_execution.LifecyclePhysicsLimits, lifecycle_execution.LifecycleWorld)
        for owner in own_classes:
            for name, function in vars(owner).items():
                if type(function) is FunctionType:
                    extra.append((owner, name, function))
                elif type(function) is property:
                    self.retained.append(function)
                    for accessor in (function.fget, function.fset, function.fdel):
                        if accessor is not None: self.retained.append(accessor)
                    properties.append((owner, name, function,
                        tuple(None if fn is None else (fn, _function_signature(fn, self.retained))
                              for fn in (function.fget, function.fset, function.fdel))))
        from . import lifecycle_exact_guards as exact_guards
        from . import lifecycle_state, lifecycle_report, environment_reporting, lifetime_reporting, lifecycle_quiet
        for module in (exact_guards,lifecycle_state,environment_reporting,lifetime_reporting,lifecycle_quiet):
            extra.extend((module,name,fn) for name,fn in vars(module).items() if type(fn)is FunctionType)
        for owner in (lifecycle_report.LifecycleReport,exact_guards.ExactGuardSession,exact_guards._Rows,
                      lifecycle_quiet.QuietWork,lifecycle_quiet.ShortCircuitQuietWork):
            extra.extend((owner,name,fn) for name,fn in vars(owner).items() if type(fn)is FunctionType)
        for name in ('projection','validate_projection','_projection_data'):
            extra.append((environment_lifecycle,name,getattr(environment_lifecycle,name)))
        # Version selectors and diagnostic bounds are source authority, not a live flag.
        declarations += tuple((lifecycle_quiet,name,getattr(lifecycle_quiet,name)) for name in
            ('QUIET_METHOD','BATTERY_QUIET_METHOD','ENVIRONMENT_QUIET_METHOD',
             'SHORT_QUIET_METHOD','SHORT_BATTERY_QUIET_METHOD','SHORT_ENVIRONMENT_QUIET_METHOD',
             'SHORT_QUIET_METHODS','_REASON_LIMIT_V5','_REASON_ROLES_V5','_REASONS_V5'))
        declarations += tuple(extra)
        self.functions = tuple((module, name, function,
                                _function_signature(function, self.retained))
                               for module, name, function in declarations)
        self.properties = tuple(properties)
        self._pins = (self.codec, self.functions, self.properties, self.retained)
        self.guard()

    def guard(self):
        if (self.codec is not self._pins[0] or self.functions is not self._pins[1] or
                self.properties is not self._pins[2] or self.retained is not self._pins[3]):
            raise ValueError('B64 replaced schema seal')
        seal, owners, functions = self.codec._full_snapshot()
        if (seal != self.codec._seal or functions != self.codec._functions or
                set(owners) != set(self.codec._owners) or
                any(owners[o] != self.codec._owners[o] for o in owners)):
            raise ValueError('B64 schema/registry/constructor drift')
        for module, name, function, signature in self.functions:
            if getattr(module, name) is not function or _function_signature(function) != signature:
                raise ValueError('B64 prepared function drift: ' + name)
        for owner, name, descriptor, accessors in self.properties:
            if getattr(owner, name) is not descriptor:
                raise ValueError('B64 prepared property drift: ' + name)
            for actual, expected in zip((descriptor.fget, descriptor.fset, descriptor.fdel), accessors):
                if expected is None:
                    if actual is not None: raise ValueError('B64 prepared property accessor')
                elif actual is not expected[0] or _function_signature(actual) != expected[1]:
                    raise ValueError('B64 prepared property accessor drift')


class _Authority:
    __slots__ = ()
    def __copy__(self): raise TypeError('B64 private authority cannot be copied')
    def __deepcopy__(self, memo): raise TypeError('B64 private authority cannot be copied')
    def __reduce_ex__(self, protocol): raise TypeError('B64 private authority is not persistent DATA')


class _ThermalStaticAlias(_Authority):
    """One strongly retained, already owned typed-construction baseline alias."""
    __slots__ = ('job', 'owner', 'network', 'seal', '_pins')
    def __init__(self, job, owner, key):
        if key is not _FACTORY: raise TypeError('B64 thermal alias factory')
        self.job = job; self.owner = owner
        self.network = owner.configuration.thermal_network
        self.seal = _Seal(self.network)
        self._pins = (self, job, owner, self.network, self.seal, owner._pins)

    def check(self, job, network):
        from .lifecycle_typed_state import TypedStatic
        p = self._pins
        if (type(self) is not _ThermalStaticAlias or type(p) is not tuple or len(p) != 6 or
                p[0] is not self or p[1] is not self.job or self.job is not job or
                p[2] is not self.owner or p[3] is not self.network or p[4] is not self.seal or
                type(self.owner) is not TypedStatic or self.owner._pins is not p[5] or
                self.owner.configuration is not job.static.model.configuration or
                self.owner.configuration.thermal_network is not self.network or network is not self.network):
            raise ValueError('B64 foreign/replaced typed thermal alias')
        self.owner._check_identity()

    def guard(self, job):
        self.check(job, self.network)
        self.owner.guard(); self.seal.guard()


class JobInputAdmission(_Authority):
    """One exact freshly decoded root, usable once by the job factory."""
    __slots__ = ('root', 'source_binding', '_raw', '_raw_sha', '_build_raw',
                 '_runtime', '_schema', '_root_seal', '_phase', '_self',
                 '_factory', '_codec_receipt', '_work', '_binding')
    def __init__(self, raw, root, source, build, schema, receipt, key):
        if key is not _FACTORY: raise TypeError('B64 admission factory required')
        self.root = root; self.source_binding = _hash(source)
        self._raw = raw; self._raw_sha = sha256(raw).hexdigest(); self._build_raw = build
        self._runtime = _runtime(); self._schema = schema; self._root_seal = _Seal(root)
        self._phase = 'ADMITTED'; self._self = self; self._factory = key
        self._codec_receipt = _data(receipt)
        self._work = dict(raw_admissions=1, model_build_attempts=0, model_build_completed=0,
                          static_copy_attempts=0, static_copy_completed=0,
                          control_units_reserved=len(raw) + self._root_seal.nodes)
        self._binding = (self, root, source, raw, self._raw_sha, build, self._runtime,
                         schema, self._root_seal, self._codec_receipt, self._work)

    def _guard(self, root, *, phase='ADMITTED'):
        if (type(self) is not JobInputAdmission or self._self is not self or
                self._factory is not _FACTORY or self._runtime != _runtime() or
                self._phase != phase or root is not self.root or
                type(self._raw) is not bytes or sha256(self._raw).hexdigest() != self._raw_sha or
                type(self._binding) is not tuple or len(self._binding) != 11 or
                self._binding[0] is not self or self._binding[1] is not self.root or
                self._binding[2] != self.source_binding or self._binding[3] is not self._raw or
                self._binding[4] != self._raw_sha or self._binding[5] is not self._build_raw or
                self._binding[6] is not self._runtime or self._binding[7] is not self._schema or
                self._binding[8] is not self._root_seal or self._binding[9] is not self._codec_receipt or
                self._binding[10] is not self._work):
            raise ValueError('B64 foreign/copied/stale/consumed input admission')
        _hash(self.source_binding); self._root_seal.guard(); self._schema.guard()
        if any(type(v) is not int or not 0 <= v <= MAX_CONTROL_UNITS for v in self._work.values()):
            raise ValueError('B64 admission operational work')

    def receipt(self):
        return dict(method=METHOD, phase=self._phase, raw_sha256=self._raw_sha,
                    raw_bytes=len(self._raw), source_binding=self.source_binding,
                    build_sha256=sha256(self._build_raw).hexdigest(),
                    input_codec=json.loads(self._codec_receipt), **self._work,
                    scope='PROCESS_LOCAL_ADMISSION_DATA_NOT_AUTHORITY')

    @property
    def raw_sha256(self): return self._raw_sha
    @property
    def build_sha256(self): return sha256(self._build_raw).hexdigest()


def admit_job_root(raw, source_binding, *, build_binding=None):
    """Strict raw admission exactly once; return (public root, one-shot token)."""
    _hash(source_binding)
    if type(raw) is not bytes: raise TypeError('B64 exact lifecycle raw bytes')
    build = _data(build_binding)
    schema = _SchemaSeal()
    codec = PreparedInputCodec()
    root = _LOAD_ROOT(raw, input_codec=codec)
    schema.guard()
    token = JobInputAdmission(raw, root, source_binding, build, schema, codec.receipt(), _FACTORY)
    token._guard(root)
    return root, token


@dataclass(frozen=True, slots=True)
class PreparedStaticModel:
    root: object
    model: object
    source_binding: str
    root_identity: str
    model_identity: str
    baseline: ThermalNetworkConfig
    environment_policy: object
    environment_policy_identity: str | None
    thermal_node_indices: tuple
    thermal_nodes: tuple
    thermal_links: tuple
    heat_routes: tuple
    construction_lines: tuple
    static_policies: tuple
    frame_authorities: tuple
    provenance: tuple


@dataclass(frozen=True, slots=True)
class _Realization:
    key: tuple
    history: EnvironmentAgeingState
    effective: EffectiveEnvironmentNetwork
    solar_retention: float
    network_identity: str
    seal: object


class PreparedRoleState(_Authority):
    """Independent realization/work scope; never an actual-state cache."""
    __slots__ = ('_job', 'role', '_cache', '_work', '_self', '_binding')
    def __init__(self, job, role, key):
        if key is not _FACTORY or role not in ('ACTUAL', 'FORECAST'):
            raise TypeError('B64 private role factory')
        self._job = job; self.role = role; self._self = self
        self._cache = OrderedDict()
        self._work = dict(requests=0, failures=0, coefficient_attempts=0,
                          coefficient_realizations=0, cache_hits=0, cache_misses=0,
                          cache_evictions=0, binding_refusals=0)
        self._binding = (job, role, job.static, self._cache, self._work)

    @property
    def root(self): return self._job.static.root
    @property
    def static(self): return self._job.static
    @property
    def model(self): return self._job.static.model
    @property
    def baseline(self): return self._job.static.baseline
    @property
    def environment_policy(self): return self._job.static.environment_policy
    @property
    def source_binding(self): return self._job.source_binding
    @property
    def root_identity(self): return self._job.static.root_identity
    @property
    def model_identity(self): return self._job.static.model_identity
    @property
    def _external_root(self): return self._job.external_root
    @property
    def _external_model(self): return self._job.external_model
    @property
    def _external_policy(self): return self._job.external_root.environment_ageing_policy
    @property
    def _external_baseline(self): return self._job.external_model.simulation_inputs.spacecraft_configuration.thermal.network

    def _guard_identity(self):
        self._job._guard_identity()
        if (type(self) is not PreparedRoleState or self._self is not self or
                type(self._binding) is not tuple or len(self._binding) != 5 or
                self._binding[0] is not self._job or self._binding[1] != self.role or
                self._binding[2] is not self._job.static or self._binding[3] is not self._cache or
                self._binding[4] is not self._work or
                type(self.role) is not str or self._job._roles.get(self.role) is not self or
                type(self._cache) is not OrderedDict or len(self._cache) > MAX_CACHE_ENTRIES or
                type(self._work) is not dict or set(self._work) != set(_ROLE_WORK_FIELDS) or
                any(type(v) is not int or not 0 <= v <= MAX_CONTROL_UNITS for v in self._work.values()) or
                self._work['coefficient_realizations'] > self._work['coefficient_attempts']):
            raise ValueError('B64 foreign role or operational state')

    def require_transaction(self):
        self._guard_identity()
        return self._job.require_transaction()

    def check_boundary(self, root, model, *, source_binding=None, role=None):
        self._guard_identity()
        if (root is not self._external_root or model is not self._external_model or
                source_binding is not None and source_binding != self.source_binding or
                role is not None and role != self.role):
            raise ValueError('B64 foreign prepared role boundary')
        if self._job._active is None: self._job.check_boundary(root, model)
        else: self.require_transaction()

    def _statics(self, policy, baseline):
        tx = self.require_transaction()
        if (type(policy) is not EnvironmentAgeingPolicy or self.environment_policy is None or
                policy is not self._external_policy and policy is not self.environment_policy or
                type(baseline) is not ThermalNetworkConfig or
                not self._accept_baseline(baseline)):
            raise ValueError('B64 foreign environment static authority')
        return tx

    def _accept_baseline(self, baseline):
        if baseline is self._external_baseline or baseline is self.baseline: return True
        alias = self._job._thermal_aliases.get('TYPED_CONSTRUCTION_V1')
        if alias is None or baseline is not alias.network: return False
        alias.check(self._job, baseline)
        return True

    def _history(self,history,clock=None):
        if type(history)is not EnvironmentAgeingState:raise TypeError('B68 exact dynamic environment history')
        history.__post_init__()
        if (history.policy_identity!=self.static.environment_policy_identity or
                history.baseline_network_identity!=self._job._baseline_identity or
                clock is not None and history.clock_seconds!=Fraction(clock)):
            raise ValueError('B68 stale/foreign environment history or clock')

    def guard_environment_history(self,policy,history,baseline,clock=None):
        self._statics(policy,baseline) # exact live role/current owned transaction
        self._history(history,clock)

    def _realization(self, policy, history, baseline):
        tx = self._statics(policy, baseline)
        self._job._charge(32, 'environment_requests'); self._work['requests'] += 1
        try:
            self._history(history)
            key = (EnvironmentAgeingState, _exact_tree(history))
            entry = self._cache.get(key)
            if entry is not None:
                self._work['cache_hits'] += 1; self._cache.move_to_end(key)
                tx._retain(entry)
                return entry
            self._work['cache_misses'] += 1
            owned = _copy_owned(history); owned.__post_init__()
            self._work['coefficient_attempts'] += 1
            network = _derive(self.environment_policy, owned, self.baseline)
            state_identity = digest(owned)
            effective = EffectiveEnvironmentNetwork(self._job._baseline_identity,
                self.static.environment_policy_identity, state_identity, network)
            entry = _Realization(key, owned, effective, retention(self.environment_policy, owned),
                                 digest(network), _Seal((owned, effective)))
            self._job._charge(32 + entry.seal.nodes, 'coefficient_realizations')
            self._work['coefficient_realizations'] += 1
            tx._retain(entry)
            if len(self._cache) >= MAX_CACHE_ENTRIES:
                self._cache.popitem(last=False); self._work['cache_evictions'] += 1
            self._cache[key] = entry
            return entry
        except BaseException:
            self._work['failures'] += 1
            raise

    def effective_environment(self, policy, history, baseline):
        return self._realization(policy, history, baseline).effective

    def environment_retention(self, policy, history, baseline):
        return self._realization(policy, history, baseline).solar_retention

    def environment_metrics(self, policy, history, baseline):
        entry = self._realization(policy, history, baseline)
        state, network = entry.history, entry.effective.network
        return (('environment_calendar_seconds', float(state.calendar_seconds)),
                ('environment_pv_exposure_seconds', state.pv_exposure_seconds),
                ('environment_thermal_exposure_seconds', state.thermal_exposure_seconds),
                ('environment_pv_retention', entry.solar_retention),
                *(("environment_epsilon:" + n.node_id.value, n.emissivity.value) for n in network.nodes),
                *(("environment_conductance:" + l.link_id.value, l.conductance_w_per_k.value) for l in network.links))

    def environment_state_identity(self, policy, history, baseline):
        return self._realization(policy, history, baseline).effective.state_identity

    def environment_projection(self, policy, history, baseline):
        entry = self._realization(policy, history, baseline)
        self._job._charge(32 + 4 * (len(entry.effective.network.nodes) + len(entry.effective.network.links)), 'projections')
        from .environment_lifecycle import _projection_data
        return _projection_data(self.environment_policy, entry.history, entry.effective.network,
            entry.solar_retention, entry.effective.policy_identity,
            entry.effective.state_identity, entry.network_identity)

    def validate_environment_binding(self, binding, baseline):
        self.require_transaction()
        if binding is None:
            if not self._accept_baseline(baseline):
                raise ValueError('B64 foreign baseline')
            return self.baseline
        if type(binding) is not tuple or len(binding) != 3:
            raise TypeError('B64 exact effective environment binding')
        effective, policy, history = binding
        if type(effective) is not EffectiveEnvironmentNetwork:
            raise TypeError('B64 exact effective environment record')
        entry = self._realization(policy, history, baseline)
        if effective is not entry.effective and _exact_tree(effective) != _exact_tree(entry.effective):
            self._work['binding_refusals'] += 1
            raise ValueError('B64 effective environment provenance')
        return entry.effective.network

    def snapshot(self):
        self._guard_identity()
        return dict(method=METHOD, role=self.role, source_binding=self.source_binding,
                    root_identity=self.root_identity, model_identity=self.model_identity,
                    cache_entries=len(self._cache), cache_limit=MAX_CACHE_ENTRIES,
                    **self._work, scope='ROLE_LOCAL_OPERATIONAL_DATA_NOT_SCIENTIFIC_WORK')


class PreparedTransaction(_Authority):
    __slots__ = ('_job', '_self', '_phase', '_generation', '_entries', '_nodes', '_parent')
    def __init__(self, job, key):
        if key is not _FACTORY: raise TypeError('B64 transaction factory')
        self._job = job; self._self = self; self._phase = 'NEW'
        self._generation = job._generation; self._entries = {}; self._nodes = 0; self._parent = None

    def require_active(self):
        self._job._guard_identity()
        if (type(self) is not PreparedTransaction or self._self is not self or
                self._phase != 'ACTIVE' or self._job._active is not self or
                not 0 < self._generation <= self._job._generation):
            raise ValueError('B64 inactive/foreign/stale private transaction')
        return self

    def _retain(self, entry):
        self.require_active()
        previous = self._entries.get(id(entry))
        if previous is entry: return
        if (previous is not None or len(self._entries) >= MAX_TRANSACTION_REALIZATIONS or
                self._nodes + entry.seal.nodes > MAX_GRAPH_NODES):
            raise ValueError('B64 finite private realization retention')
        self._entries[id(entry)] = entry; self._nodes += entry.seal.nodes

    def __enter__(self):
        job = self._job
        job._guard_identity()
        if self._self is not self or self._phase != 'NEW':
            raise ValueError('B64 transaction is single-use')
        parent = job._active
        if job._validation is not None and job._validation._phase == 'CALLBACK':
            raise ValueError('B65 foreign callback reentrancy refused before work')
        if parent is not None: parent.require_active()
        depth, cursor = 1, parent
        while cursor is not None:
            depth += 1
            if depth > MAX_TRANSACTION_DEPTH: raise ValueError('B64 finite transaction nesting')
            cursor = cursor._parent
        job._charge(job._boundary_units, 'transaction_attempts')
        try: job._full_guard(parent)
        except BaseException:
            job._work['transaction_failed'] += 1; self._phase = 'FAILED_ENTRY'
            raise
        job._generation += 1; self._generation = job._generation
        self._parent = parent
        self._phase = 'ACTIVE'; job._active = self
        if parent is None and job._validation is not None:job._validation.activate(self)
        return self

    def after_callback(self):
        self.require_active()
        self._job._charge(self._job._boundary_units, 'callback_checks')
        validation = self._job._validation
        if validation is not None:validation.boundary()
        try:
            self._job._full_guard(self)
            if validation is not None:validation.callback_end()
        except BaseException:
            self._phase = 'INVALID_CALLBACK'
            if validation is not None:validation._phase = 'BOUNDARY'
            raise

    def callback(self, function, *args, **kwargs):
        """Exactly one external call; preserve its primary exception on exit."""
        self.require_active()
        validation = self._job._validation
        if validation is not None:
            validation.callback_begin()
            self._job._full_guard(self)
            # Existing opaque native plans also require phase ACTIVE. Merely
            # rejecting a new nested transaction would leave a reentry hole.
            self._phase = 'EXTERNAL_CALLBACK'
        try: result = function(*args, **kwargs)
        except BaseException as primary:
            if validation is not None:
                if self._phase != 'EXTERNAL_CALLBACK':
                    self._phase = 'INVALID_CALLBACK'
                    try:
                        self._job._secondary(primary,ValueError('B65 callback transaction phase drift'))
                    except BaseException:
                        try:BaseException.add_note(primary,"B69 secondary annotator failed; original exception preserved")
                        except BaseException:pass
                else:self._phase = 'ACTIVE'
            try: self.after_callback()
            except BaseException as secondary:
                try:
                    self._job._secondary(primary, secondary)
                except BaseException:
                    try:BaseException.add_note(primary,"B69 secondary annotator failed; original exception preserved")
                    except BaseException:pass
            raise
        if validation is not None:
            if self._phase != 'EXTERNAL_CALLBACK':
                self._phase = 'INVALID_CALLBACK'
                raise ValueError('B65 callback transaction phase drift')
            self._phase = 'ACTIVE'
        self.after_callback()
        return result

    def __exit__(self, exc_type, primary, traceback):
        job = self._job
        if job._active is not self or self._phase not in ('ACTIVE', 'INVALID_CALLBACK'):
            raise ValueError('B64 exact transaction exit')
        secondary = None
        try:
            job._guard_identity()
            if self._parent is None and job._validation is not None:job._validation.boundary()
            job._charge(job._boundary_units, 'transaction_exits')
            if self._parent is None and job._validation is not None:
                job._validation.verify_boundary()
            job._full_guard(self)
        except BaseException as error:
            secondary = error
        finally:
            job._active = self._parent
            if self._parent is not None:
                try:
                    for entry in self._entries.values(): self._parent._retain(entry)
                except BaseException as error:
                    if secondary is None: secondary = error
                    else:
                        try:
                            job._secondary(secondary, error)
                        except BaseException:
                            try:BaseException.add_note(secondary,"B69 secondary annotator failed; original exception preserved")
                            except BaseException:pass
            self._entries.clear()
            if self._parent is None and job._validation is not None:
                try:
                    # Never dispatch cleanup through a callback-mutated class.
                    job._guard_identity()
                    job._validation.finish(primary is not None or secondary is not None)
                except BaseException as error:
                    if secondary is None: secondary = error
                    else:
                        try:
                            job._secondary(secondary, error)
                        except BaseException:
                            try:BaseException.add_note(secondary,"B69 secondary annotator failed; original exception preserved")
                            except BaseException:pass
            self._phase = 'CLOSED' if primary is None and secondary is None else 'FAILED'
            job._work['transaction_completed' if self._phase == 'CLOSED' else 'transaction_failed'] += 1
        if secondary is not None:
            if primary is None: raise secondary
            try:
                job._secondary(primary, secondary)
            except BaseException:
                try:BaseException.add_note(primary,"B69 secondary annotator failed; original exception preserved")
                except BaseException:pass
        return False


class PreparedJobRuntime(_Authority):
    __slots__ = ('static', 'external_root', 'external_model', 'source_binding',
                 '_admission', '_schema', '_external_seal', '_owned_seal',
                 '_baseline_identity', '_roles', '_active', '_generation',
                 '_runtime', '_self', '_binding', '_boundary_units', '_work',
                 '_secondary_errors', '_closed', '_admission_pins', '_thermal_aliases', '_validation', '_validation_pin', '_guard_plan', '_guard_plan_pin', '_guard_gate', '_guard_gate_pin', '_guard_arena', '_guard_binding', '_guard_records_enabled')
    def __init__(self, admission, root, model, owned_root, owned_model, key):
        if key is not _FACTORY: raise TypeError('B64 job factory')
        baseline = owned_model.simulation_inputs.spacecraft_configuration.thermal.network
        policy = owned_root.environment_ageing_policy
        baseline_identity = digest(baseline)
        if policy is not None and admit_network(baseline, policy) != baseline_identity:
            raise ValueError('B64 static environment admission')
        indices = tuple((n.node_id.value, i) for i, n in enumerate(baseline.nodes)); index = dict(indices)
        nodes = tuple((n.node_id.value, n.heat_capacity_j_per_k.value, n.emissivity.value,
                       n.radiating_area_m2.value, n.operating_min_temperature_k.value,
                       n.operating_max_temperature_k.value, n.survival_min_temperature_k.value,
                       n.survival_max_temperature_k.value) for n in baseline.nodes)
        links = tuple((l.link_id.value, index[l.node_a_id.value], index[l.node_b_id.value],
                       l.conductance_w_per_k.value) for l in baseline.links)
        routes = tuple((r.component.value, index[r.thermal_node_id.value], r.retained_heat_fraction.value)
                       for r in owned_model.routing.routes)
        policies = tuple((name, getattr(owned_model, name)) for name in
                         ('limits', 'quiet_policy', 'service_policy', 'energy_attitude_policy',
                          'battery_port_policy', 'environment_ageing_policy'))
        frames = (owned_model.environment.trajectory, owned_model.environment.sun,
                  owned_model.assembly, owned_model.capabilities, owned_model.actuator)
        provenance = tuple((n.node_id.value, f.name, getattr(n, f.name).provenance)
                           for n in baseline.nodes for f in fields(type(n)) if f.name != 'node_id')
        provenance += tuple((l.link_id.value, 'conductance_w_per_k', l.conductance_w_per_k.provenance)
                            for l in baseline.links)
        self.static = PreparedStaticModel(owned_root, owned_model, admission.source_binding,
            owned_root.identity, digest(owned_model), baseline, policy, None if policy is None else policy.identity, indices, nodes, links, routes,
            tuple(owned_model.configuration.lines), policies, frames, provenance)
        self.external_root = root; self.external_model = model; self.source_binding = admission.source_binding
        self._admission = admission; self._schema = admission._schema
        self._external_seal = _Seal((root, model)); self._owned_seal = _Seal((self.static, owned_root, owned_model))
        self._baseline_identity = baseline_identity; self._active = None; self._generation = 0
        self._runtime = _runtime(); self._self = self; self._closed = False
        self._validation = None; self._validation_pin = None
        self._guard_plan = None; self._guard_plan_pin = None
        self._guard_gate = self._guard_gate_pin = self._guard_arena = self._guard_binding = None
        self._guard_records_enabled = False
        self._roles = {role: PreparedRoleState(self, role, _FACTORY) for role in ('ACTUAL', 'FORECAST')}
        self._boundary_units = self._external_seal.nodes + self._owned_seal.nodes + len(self._schema.codec._owners) + 32
        self._work = dict(method=CONTROL_METHOD, control_units_reserved=admission._work['control_units_reserved'],
                          static_preparations=1, transaction_attempts=0, transaction_completed=0,
                          transaction_failed=0, transaction_exits=0, callback_checks=0,
                          environment_requests=0, coefficient_realizations=0, projections=0,
                          report_parts=0, public_boundaries=0,progress_frontiers=0)
        self._secondary_errors = []; self._thermal_aliases = {}
        self._admission_pins = (admission.root, admission.source_binding, admission._raw,
            admission._raw_sha, admission._build_raw, admission._schema, admission._root_seal,
            admission._codec_receipt, admission._work, tuple(admission._work.items()))
        self._binding = (self, self.static, root, model, admission, self.source_binding, self._runtime,
                         self._roles['ACTUAL'], self._roles['FORECAST'], self._schema,
                         self._external_seal, self._owned_seal, self._work, self._roles, self._thermal_aliases,
                         (baseline_identity,self.static.environment_policy_identity))
        self._full_guard()

    def _dispatch_guard(self,operation,argument):
        # This is an independently admitted immutable Cython export. Neither
        # session._pins nor a session method decides whether its gate runs.
        gate=self._guard_gate;t=type(gate)
        if (gate is not self._guard_gate_pin or t.__module__!='_cython_3_2_4' or
                t.__name__!='cython_function_or_method' or t.__flags__&384!=384 or
                getattr(gate,'__module__',None)!='ops_sim.v5._lifecycle_typed65' or
                getattr(gate,'__name__',None)!='dispatch_exact_guard'):
            raise ValueError('B70 independent native dispatch origin')
        return gate(self._guard_arena,self._guard_binding,self._guard_plan,self,operation,argument)

    def _guard_identity(self):
        if type(self._guard_records_enabled)is not bool:raise ValueError('YEAR-V4 exact guard record activation')
        if self._guard_plan is not self._guard_plan_pin:raise ValueError('B69 replaced exact guard owner')
        if self._guard_plan is not None or self._guard_gate is not None or self._guard_arena is not None:
            # Inline immutable-C entry, independent of the new Python dispatch
            # wrapper AND of every session method being validated.
            gate=self._guard_gate;t=type(gate)
            if (gate is not self._guard_gate_pin or t.__module__!='_cython_3_2_4' or
                    t.__name__!='cython_function_or_method' or t.__flags__&384!=384 or
                    getattr(gate,'__module__',None)!='ops_sim.v5._lifecycle_typed65' or
                    getattr(gate,'__name__',None)!='dispatch_exact_guard'):
                raise ValueError('B70 independent native entry origin')
            gate(self._guard_arena,self._guard_binding,self._guard_plan,self,
                'identity'if self._guard_records_enabled else 'check',self)
            if self._guard_records_enabled:return
        if self._validation is not self._validation_pin:
            raise ValueError('B65 changed validation owner')
        if self._validation is not None:
            _guard_generation_owner(compiled=self._guard_plan)
            if type(self._validation) is not _GENERATION_OWNER_BINDING[0]:
                raise ValueError('B66 foreign generation owner before dispatch')
            self._validation.cheap(self)
        if (type(self) is not PreparedJobRuntime or self._self is not self or self._closed or
                self._runtime != _runtime() or type(self._binding) is not tuple or
                len(self._binding) != 16 or self._binding[0] is not self or
                self._binding[1] is not self.static or self._binding[2] is not self.external_root or
                self._binding[3] is not self.external_model or self._binding[4] is not self._admission or
                type(self.source_binding) is not str or self._binding[5] != self.source_binding or
                self._binding[6] != self._runtime or type(self._roles) is not dict or
                set(self._roles) != {'ACTUAL', 'FORECAST'} or
                self._roles['ACTUAL'] is not self._binding[7] or self._roles['FORECAST'] is not self._binding[8]):
            raise ValueError('B64 foreign/copied/stale job authority')
        if (self._binding[9] is not self._schema or self._binding[10] is not self._external_seal or
                self._binding[11] is not self._owned_seal or self._binding[12] is not self._work or
                self._binding[13] is not self._roles or self._binding[14] is not self._thermal_aliases or
                type(self._thermal_aliases) is not dict or
                any(type(name) is not str for name in self._thermal_aliases) or
                not set(self._thermal_aliases) <= {'TYPED_CONSTRUCTION_V1'} or
                any(type(a) is not _ThermalStaticAlias for a in self._thermal_aliases.values())):
            raise ValueError('B64 replaced job seal or ledger')
        if (type(self._binding[15])is not tuple or len(self._binding[15])!=2 or
                self._baseline_identity!=self._binding[15][0] or
                self.static.environment_policy_identity!=self._binding[15][1]):
            raise ValueError('B68 prepared static digest drift')
        a = self._admission; p = self._admission_pins
        if (a._phase != 'CONSUMED' or a.root is not p[0] or a.source_binding != p[1] or
                a._raw is not p[2] or a._raw_sha != p[3] or a._build_raw is not p[4] or
                a._schema is not p[5] or a._root_seal is not p[6] or a._codec_receipt is not p[7] or
                a._work is not p[8] or tuple(a._work.items()) != p[9]):
            raise ValueError('B64 consumed input admission drift')
        if (type(self._generation) is not int or not 0 <= self._generation < MAX_CONTROL_UNITS or
                set(self._work) != set(_JOB_WORK_FIELDS) or self._work['method'] != CONTROL_METHOD or
                self._work['transaction_completed'] + self._work['transaction_failed'] > self._work['transaction_attempts'] or
                any(type(v) is not int or not 0 <= v <= MAX_CONTROL_UNITS
                for n, v in self._work.items() if n != 'method')):
            raise ValueError('B64 finite versioned operational ledger')

    def _charge(self, amount, field):
        self._guard_identity()
        if (type(amount) is not int or amount < 1 or field not in self._work or field == 'method' or
                self._work['control_units_reserved'] + amount > MAX_CONTROL_UNITS):
            raise ValueError('B64_PREPARATION_CONTROL_LIMIT')
        self._work['control_units_reserved'] += amount; self._work[field] += 1

    def _full_guard(self, transaction=None):
        self._guard_identity()
        # Independent of mutable job._guard_identity and _dispatch_guard code.
        if self._guard_plan is not None or self._guard_gate is not None or self._guard_arena is not None:
            gate=self._guard_gate;t=type(gate)
            if (gate is not self._guard_gate_pin or t.__module__!='_cython_3_2_4' or
                    t.__name__!='cython_function_or_method' or t.__flags__&384!=384 or
                    getattr(gate,'__module__',None)!='ops_sim.v5._lifecycle_typed65' or
                    getattr(gate,'__name__',None)!='dispatch_exact_guard'):
                raise ValueError('B70 independent native entry origin')
            gate(self._guard_arena,self._guard_binding,self._guard_plan,self,'check',self)
        if self._validation is not None:
            if self._validation.closed(transaction):
                self._validation._counts['closed_requests'] += 1
                return
            self._validation._counts['full_requests'] += 1
        if self._guard_plan is not None:
            self._dispatch_guard('full',transaction);return
        self._schema.guard(); self._external_seal.guard(); self._owned_seal.guard()
        for alias in self._thermal_aliases.values(): alias.guard(self)
        for role in self._roles.values():
            role._guard_identity()
            for entry in role._cache.values(): entry.seal.guard()
        if transaction is not None:
            for entry in transaction._entries.values(): entry.seal.guard()

    def admit_thermal_alias(self, owner):
        """Register the exact owned construction thermal network once.

        No equal caller-supplied network is admitted. The TypedStatic must
        retain this job's already owned configuration by identity. Equality is
        checked once under a conservative finite operational reservation; every
        leaf thereafter uses only the strongly retained alias identity.
        """
        from .lifecycle_typed_state import TypedStatic
        self.require_transaction()
        if type(owner) is not TypedStatic: raise TypeError('B64 exact typed thermal owner')
        owner._check_identity()
        if owner.configuration is not self.static.model.configuration:
            raise ValueError('B64 foreign typed thermal owner configuration')
        network = owner.configuration.thermal_network
        previous = self._thermal_aliases.get('TYPED_CONSTRUCTION_V1')
        if previous is not None:
            previous.check(self, network)
            if previous.owner is not owner: raise ValueError('B64 foreign replacement typed thermal owner')
            return network
        # One owner guard, two exact trees and one new immutable seal are
        # bounded by the admitted whole-graph domain. This is an additional public
        # admission boundary, never an extra static-copy or scientific fee.
        self._charge(64 + 4 * MAX_GRAPH_NODES, 'public_boundaries')
        owner.guard()
        if type(network) is not ThermalNetworkConfig or _exact_tree(network) != _exact_tree(self.static.baseline):
            raise ValueError('B64 typed thermal alias changes exact baseline')
        alias = _ThermalStaticAlias(self, owner, _FACTORY)
        alias.check(self, network)
        self._thermal_aliases['TYPED_CONSTRUCTION_V1'] = alias
        return network

    def _secondary(self, primary, secondary):
        detail = type(secondary).__name__
        try: detail += ': ' + str(secondary)[:1024]
        except BaseException: detail += ': <unavailable>'
        if len(self._secondary_errors) < 32: self._secondary_errors.append(detail)
        try: primary.add_note('B64 prepared exit also failed: ' + detail)
        except BaseException: pass

    def role(self, role):
        self._guard_identity()
        if type(role) is not str or role not in self._roles: raise ValueError('B64 exact physical role')
        return self._roles[role]

    @property
    def actual(self): return self.role('ACTUAL')
    @property
    def forecast(self): return self.role('FORECAST')

    @property
    def raw_sha256(self): return self._admission._raw_sha
    @property
    def build_sha256(self): return sha256(self._admission._build_raw).hexdigest()

    def require_transaction(self):
        self._guard_identity()
        if self._active is None: raise ValueError('B64 private operation requires external transaction')
        return self._active.require_active()

    def transaction(self, root=None, model=None):
        self._guard_identity()
        if root is not None and root is not self.external_root or model is not None and model is not self.external_model:
            raise ValueError('B64 foreign external transaction')
        return PreparedTransaction(self, _FACTORY)

    def check_boundary(self, root, model):
        if root is not self.external_root or model is not self.external_model:
            raise ValueError('B64 foreign root/model boundary')
        if self._active is not None: return self.require_transaction()
        self._charge(self._boundary_units, 'public_boundaries'); self._full_guard()

    def receipt(self):
        self._guard_identity()
        return dict(method=METHOD, source_binding=self.source_binding, root_identity=self.static.root_identity,
                    model_identity=self.static.model_identity, raw_sha256=self._admission._raw_sha,
                    build_sha256=sha256(self._admission._build_raw).hexdigest(),
                    preparation=self._admission.receipt(), control=dict(self._work),
                    roles={n: r.snapshot() for n, r in self._roles.items()},
                    secondary_errors=list(self._secondary_errors),
                    exact_guard=dict(method='PYTHON_EXACT_REFERENCE_FALLBACK'if self._guard_plan is None else 'B69_COMPILED_EXACT_GUARD_PLAN_V1',
                        counters='SEPARATE_OPERATIONAL_STATISTICS_NOT_BINDING_RECEIPT'),
                    scope='PAID_CURRENT_JOB_PREPARATION_NOT_SCIENTIFIC_WORK_OR_RESTART_AUTHORITY')

    def exact_guard_statistics(self):
        self._guard_identity()
        return (dict(method='PYTHON_EXACT_REFERENCE_FALLBACK')if self._guard_plan is None else self._dispatch_guard('receipt',None))

    def close(self):
        self._guard_identity()
        if self._active is not None: raise ValueError('B64 cannot close active transaction')
        self._full_guard()
        if self._guard_plan is not None:self._dispatch_guard('close',None)
        self._closed = True


def prepare_job_runtime(admission, root, *, restored_model=None):
    """Consume admission once; one original factory build and one owned copy."""
    if type(admission) is not JobInputAdmission: raise TypeError('B64 exact input admission')
    admission._guard(root)
    admission._phase = 'CONSUMING'
    # Reserve the original bounded graph domain before factory/copy work.
    # This is an explicit operational reservation, not a science invocation fee.
    if admission._work['control_units_reserved'] + 2 * MAX_GRAPH_NODES > MAX_CONTROL_UNITS:
        admission._phase = 'FAILED_PREPARATION'
        raise ValueError('B64 preparation admission control capacity')
    admission._work['control_units_reserved'] += 2 * MAX_GRAPH_NODES
    admission._work['model_build_attempts'] += 1
    try:
        built_model = _BUILD_MODEL(root)
        admission._work['model_build_completed'] += 1
        admission._root_seal.guard(); admission._schema.guard()
        if restored_model is not None:
            from .lifecycle_physics import LifecyclePhysicalModel
            if type(restored_model) is not LifecyclePhysicalModel or _exact_tree(restored_model) != _exact_tree(built_model):
                raise ValueError('B64 saved model differs from original static factory')
            model = restored_model
        else: model = built_model
        tree = _exact_tree((root, model))
        admission._work['static_copy_attempts'] += 1
        owned_root, owned_model = _copy_owned((root, model))
        if _exact_tree((owned_root, owned_model)) != tree:
            raise ValueError('B64 independently owned static copy mismatch')
        admission._work['static_copy_completed'] += 1
        admission._phase = 'CONSUMED'
        return PreparedJobRuntime(admission, root, model, owned_root, owned_model, _FACTORY)
    except BaseException:
        admission._phase = 'FAILED_PREPARATION'
        raise
