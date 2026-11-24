"""B63 invocation-owned immutable topology and exact environment realization.

This is a private execution optimization, not a source of dynamic state. Full
root admission occurs once at preparation. Caller graphs are retained only as
drift guards; arithmetic consumes independently reconstructed immutable input.
The small cache owns complete exact history samples, including their types and
provenance. It never owns or changes scientific work, proposal or trial ledgers.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from hashlib import sha256
from math import isfinite
import sys

from .assembly_attitude import ComponentAxisBinding
from .environment_ageing import (
    EnvironmentAgeingPolicy, EnvironmentAgeingState, admit_network, digest,
    retention,
)
from .environment_thermal import EffectiveEnvironmentNetwork, _derive
from .thermal_config import ThermalNetworkConfig


METHOD = 'B63_OWNED_PREPARED_RUNTIME_V1'
MAX_GRAPH_NODES = 2**19
MAX_GRAPH_BYTES = 64 * 2**20
MAX_CACHE_ENTRIES = 8
MAX_OPERATIONAL_UNITS = 2**48
WORK_FIELDS = ('full_admissions', 'control_units_reserved', 'boundary_attempts',
               'boundary_completed', 'boundary_failed', 'effective_requests',
               'metric_requests', 'retention_requests', 'binding_requests',
               'environment_failed', 'coefficient_attempts',
               'coefficient_realizations', 'state_digests', 'cache_hits',
               'cache_misses', 'cache_evictions', 'binding_refusals')


def _hash(value):
    if (type(value) is not str or len(value) != 64 or
            any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('B63 exact source binding required')
    return value


def _runtime():
    return (sys.implementation.name, sys.version, sys.executable, sys.platform)


def _exact_tree(value, budget=None, depth=0):
    """Compare exact immutable data without user equality or float coercion."""
    if budget is None:
        budget = [0, 0]
    budget[0] += 1
    if budget[0] > MAX_GRAPH_NODES or depth > 64:
        raise ValueError('B63 bounded immutable graph')
    owner = type(value)
    if value is None:
        return ('none',)
    if owner in (str, int, bool, bytes):
        budget[1] += (len(value) if owner in (str, bytes) else
                      (value.bit_length() // 8 + 1 if owner is int else 1))
        result = (owner, value)
    elif owner is float:
        if not isfinite(value):
            raise ValueError('B63 finite immutable scalar required')
        result = (float, value.hex())
    elif owner is Fraction:
        if type(value.numerator) is not int or type(value.denominator) is not int:
            raise TypeError('B63 exact Fraction internals')
        result = (Fraction, value.numerator, value.denominator)
    elif owner is Decimal:
        if not value.is_finite():
            raise ValueError('B63 finite Decimal authority required')
        result = (Decimal, value.as_tuple())
    elif isinstance(value, Enum):
        if owner.__members__.get(value.name) is not value:
            raise ValueError('B63 canonical immutable enum required')
        result = ('enum', owner, value.name,
                  _exact_tree(value.value, budget, depth + 1))
    elif owner is tuple:
        result = (tuple, tuple(_exact_tree(x, budget, depth + 1) for x in value))
    elif is_dataclass(value) and owner.__dataclass_params__.frozen:
        result = ('record', owner, tuple(
            (f.name, _exact_tree(getattr(value, f.name), budget, depth + 1))
            for f in fields(owner)))
    else:
        raise TypeError('B63 frozen exact input records required')
    if budget[1] > MAX_GRAPH_BYTES:
        raise ValueError('B63 immutable byte reservation exceeded')
    return result


def _copy_frozen(value):
    """Copy frozen data without invoking an unadmitted caller's constructors.

    The caller first passes _exact_tree. Complete trusted constructor/codec
    admission follows on this private copy. Canonical Enum members and built-in
    scalar values are immutable leaves; enum fields are separately sealed.
    """
    owner = type(value)
    if value is None or owner in (str, int, bool, bytes, float):
        return value
    if owner is Fraction:
        return Fraction(value.numerator, value.denominator)
    if owner is Decimal:
        return Decimal(value.as_tuple())
    if isinstance(value, Enum):
        return value
    if owner is tuple:
        return tuple(_copy_frozen(x) for x in value)
    if is_dataclass(value) and owner.__dataclass_params__.frozen:
        copy = object.__new__(owner)
        for field in fields(owner):
            object.__setattr__(copy, field.name, _copy_frozen(getattr(value, field.name)))
        return copy
    raise TypeError('B63 frozen copy domain')


class _Seal:
    """Field-edge authority plus exact Fraction/Enum/schema guards.

    ids below only avoid revisiting an already retained graph node. An id is
    never an admission key, cache key or authority; the graph objects and every
    field edge remain strongly retained and checked.
    """
    __slots__ = ('edges', 'scalars', 'nodes', '__weakref__')

    def __init__(self, value):
        _exact_tree(value)
        edges, scalars, seen = [], [], set()
        count = 0

        def capture(item, depth=0):
            nonlocal count
            count += 1
            if count > MAX_GRAPH_NODES or depth > 64:
                raise ValueError('B63 bounded immutable seal')
            owner = type(item)
            if item is None or owner in (str, int, bool, float, bytes, Decimal):
                return
            if owner is Fraction:
                scalars.append(('fraction', item, item.numerator, item.denominator))
                return
            if isinstance(item, Enum):
                scalars.append(('enum', item, owner, item.name, item.value))
                return
            if owner is tuple:
                for child in item:
                    capture(child, depth + 1)
                return
            if id(item) in seen:
                return
            seen.add(id(item))
            mapping = owner.__dataclass_fields__
            schema = tuple((name, f, f.name, f.init) for name, f in mapping.items())
            values = tuple((f.name, getattr(item, f.name), f.init) for f in fields(owner))
            edges.append((item, owner, mapping, schema, values))
            for _, child, _ in values:
                capture(child, depth + 1)

        capture(value)
        self.edges, self.scalars, self.nodes = tuple(edges), tuple(scalars), count

    def guard(self, *, compiled=None):
        if compiled is not None:
            from .lifecycle_exact_guards import ExactGuardSession
            if type(compiled)is not ExactGuardSession:raise TypeError("B69 exact guard session")
            compiled._job._guard_identity()
            compiled._job._dispatch_guard('graph',self);return
        for item, owner, mapping, schema, values in self.edges:
            if type(item) is not owner or owner.__dataclass_fields__ is not mapping or len(mapping) != len(schema):
                raise ValueError('B63 prepared owner/schema drift')
            for name, field, declared_name, init in schema:
                if mapping.get(name) is not field or field.name != declared_name or field.init is not init:
                    raise ValueError('B63 prepared schema drift')
            for name, previous, init in values:
                current = getattr(item, name)
                # The established checkpoint/header codec refreshes this
                # derived cached hash through LifecycleRoot.__post_init__.
                # Its exact built-in string value is sealed; replacing any
                # authoritative input edge still requires new admission.
                if name == '_identity' and init is False:
                    if type(previous) is not str or type(current) is not str or current != previous:
                        raise ValueError('B63 prepared derived identity drift')
                elif owner is ComponentAxisBinding and name == 'local_axis':
                    # The established hardware compiler re-admits this exact
                    # owner through __post_init__, refreshing only its unit
                    # direction tuple. Preserve every binary64 bit (including
                    # signed zero), not generic tuple/dataclass equality. The
                    # containing capability and all its other edges remain
                    # identity-sealed; equal foreign capabilities are refused.
                    if (type(previous) is not tuple or type(current) is not tuple or
                            len(previous) != 3 or len(current) != 3 or
                            any(type(a) is not float or type(b) is not float or
                                a.hex() != b.hex() for a, b in zip(previous, current))):
                        raise ValueError('B63 prepared canonical local axis drift')
                elif current is not previous:
                    raise ValueError('B63 prepared immutable field drift: ' + name)
        for kind, item, *previous in self.scalars:
            if kind == 'fraction':
                if (type(item) is not Fraction or type(item.numerator) is not int or
                        type(item.denominator) is not int or
                        item.numerator != previous[0] or item.denominator != previous[1]):
                    raise ValueError('B63 prepared Fraction drift')
            else:
                owner, name, value = previous
                if (type(item) is not owner or item.name is not name or item.value is not value or
                        owner.__members__.get(name) is not item):
                    raise ValueError('B63 prepared enum drift')


@dataclass(frozen=True, slots=True)
class _Realization:
    key: tuple
    history: EnvironmentAgeingState
    effective: EffectiveEnvironmentNetwork
    solar_retention: float
    network_identity: str
    seal: _Seal


@dataclass(frozen=True, slots=True, init=False)
class PreparedRuntime:
    """One job/role's owned inputs, immutable numeric layouts and bounded cache."""
    source_binding: str
    role: str
    root_identity: str
    model_identity: str
    root: object
    model: object
    baseline: ThermalNetworkConfig
    environment_policy: object
    thermal_node_indices: tuple
    thermal_nodes: tuple
    thermal_links: tuple
    heat_routes: tuple
    construction_lines: tuple
    static_policies: tuple
    frame_authorities: tuple
    provenance: tuple
    _external_root: object
    _external_model: object
    _external_policy: object
    _external_baseline: object
    _external_seal: _Seal
    _owned_seal: _Seal
    _policy_seals: tuple
    _baseline_seals: tuple
    _identity_binding: tuple
    _cache: object
    _work: dict

    def __init__(self, root, model, role, source_binding):
        from .lifecycle_contract import LifecycleRoot
        from .lifecycle_physics import LifecyclePhysicalModel
        from .lifecycle_document import dumps_root, loads_root
        from .lifecycle_execution import build_model
        if type(root) is not LifecycleRoot or type(model) is not LifecyclePhysicalModel:
            raise TypeError('B63 exact lifecycle root/model required')
        if type(role) is not str or role not in ('ACTUAL', 'FORECAST'):
            raise ValueError('B63 exact private physical role required')
        _hash(source_binding)
        external_seal = _Seal((root, model))
        original_tree = _exact_tree(root)
        # dumps_root performs full versioned constructor/codec admission, but
        # may refresh a cached identity. Never perform that on caller objects.
        private = _copy_frozen(root)
        raw = dumps_root(private)
        from .prepared_input_codec import PreparedInputCodec
        input_codec=PreparedInputCodec()
        try:owned_root = loads_root(raw,input_codec=input_codec)
        finally:input_codec.receipt()
        if _exact_tree(owned_root) != original_tree:
            raise ValueError('B63 stale/noncanonical root authority')
        owned_model = build_model(owned_root)
        if _exact_tree(model) != _exact_tree(owned_model):
            raise ValueError('B63 foreign physical model/root authority')
        external_seal.guard()
        baseline = owned_model.simulation_inputs.spacecraft_configuration.thermal.network
        external_baseline = model.simulation_inputs.spacecraft_configuration.thermal.network
        policy = owned_root.environment_ageing_policy
        external_policy = root.environment_ageing_policy
        policy_identity = None if policy is None else policy.identity
        baseline_identity = digest(baseline)
        if policy is not None and admit_network(baseline, policy) != baseline_identity:
            raise ValueError('B63 environment baseline admission')
        indices = tuple((node.node_id.value, i) for i, node in enumerate(baseline.nodes))
        index = dict(indices)
        node_values = tuple((n.node_id.value, n.heat_capacity_j_per_k.value, n.emissivity.value,
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
        # Declared wire/port/mount records are owned. Existing separately paid
        # construction compilation still owns lengths/mass/electrical geometry.
        lines = tuple(owned_model.configuration.lines)
        frames = (owned_model.environment.trajectory, owned_model.environment.sun,
                  owned_model.assembly, owned_model.capabilities, owned_model.actuator)
        provenance = tuple((n.node_id.value, f.name, getattr(n, f.name).provenance)
                           for n in baseline.nodes for f in fields(type(n)) if f.name != 'node_id')
        provenance += tuple((l.link_id.value, 'conductance_w_per_k', l.conductance_w_per_k.provenance)
                            for l in baseline.links)
        model_identity = digest(owned_model)
        binding = (source_binding, role, owned_root.identity, model_identity, _runtime(),
                   policy_identity, baseline_identity)
        values = dict(source_binding=source_binding, role=role, root_identity=owned_root.identity,
                      model_identity=model_identity, root=owned_root, model=owned_model,
                      baseline=baseline, environment_policy=policy,
                      thermal_node_indices=indices, thermal_nodes=node_values,
                      thermal_links=links, heat_routes=routes, construction_lines=lines,
                      static_policies=policies, frame_authorities=frames, provenance=provenance,
                      _external_root=root, _external_model=model, _external_policy=external_policy,
                      _external_baseline=external_baseline, _external_seal=external_seal,
                      _owned_seal=_Seal((owned_root, owned_model)),
                      _policy_seals=() if policy is None else (_Seal(external_policy), _Seal(policy)),
                      _baseline_seals=(_Seal(external_baseline), _Seal(baseline)),
                      _identity_binding=binding, _cache=OrderedDict(),
                      _work=dict(full_admissions=1, control_units_reserved=external_seal.nodes + len(raw),
                                 boundary_attempts=0, boundary_completed=0, boundary_failed=0,
                                 effective_requests=0, metric_requests=0, retention_requests=0,
                                 binding_requests=0, environment_failed=0, coefficient_realizations=0,
                                 coefficient_attempts=0, state_digests=0, cache_hits=0,
                                 cache_misses=0, cache_evictions=0, binding_refusals=0))
        for name, value in values.items():
            object.__setattr__(self, name, value)
        self._guard_identity()

    def _guard_identity(self):
        source, role, root, model, runtime, _, _ = self._identity_binding
        if (type(self.source_binding) is not str or self.source_binding != source or
                type(self.role) is not str or self.role != role or
                type(self.root_identity) is not str or self.root_identity != root or
                type(self.model_identity) is not str or self.model_identity != model or runtime != _runtime()):
            raise ValueError('B63 prepared source/root/model/role/runtime drift')
        if (type(self._work) is not dict or set(self._work) != set(WORK_FIELDS) or
                any(type(v) is not int or not 0 <= v <= MAX_OPERATIONAL_UNITS for v in self._work.values()) or
                self._work['boundary_completed'] + self._work['boundary_failed'] != self._work['boundary_attempts'] or
                self._work['coefficient_realizations'] > self._work['coefficient_attempts']):
            raise ValueError('B63 operational preparation ledger')

    def _charge(self, amount, field):
        self._reserve_control(amount)
        self._work[field] += 1

    def _reserve_control(self, amount):
        """Prepay operational data work; no scientific counter is changed."""
        self._guard_identity()
        if type(amount) is not int or amount < 1 or self._work['control_units_reserved'] + amount > MAX_OPERATIONAL_UNITS:
            raise ValueError('B63_PREPARATION_WORK_LIMIT')
        self._work['control_units_reserved'] += amount

    def check_boundary(self, root, model, *, source_binding=None, role=None):
        """Recheck caller and private immutable graphs at real public boundaries."""
        self._charge(self._external_seal.nodes + self._owned_seal.nodes + 1, 'boundary_attempts')
        try:
            if (root is not self._external_root or model is not self._external_model or
                    source_binding is not None and (type(source_binding) is not str or source_binding != self.source_binding) or
                    role is not None and (type(role) is not str or role != self.role)):
                raise ValueError('B63 foreign prepared transaction authority')
            self._external_seal.guard()
            self._owned_seal.guard()
        except BaseException:
            self._work['boundary_failed'] += 1
            raise
        self._work['boundary_completed'] += 1

    def _check_environment_statics(self, policy, baseline):
        self._guard_identity()
        if type(policy) is not EnvironmentAgeingPolicy or self.environment_policy is None:
            raise TypeError('B63 exact configured environment policy required')
        if policy is not self._external_policy and policy is not self.environment_policy:
            raise ValueError('B63 foreign environment policy authority')
        if type(baseline) is not ThermalNetworkConfig or (baseline is not self._external_baseline and baseline is not self.baseline):
            raise ValueError('B63 foreign environment baseline authority')
        for seal in (*self._policy_seals, *self._baseline_seals):
            seal.guard()

    def _realization(self, policy, history, baseline, request_field):
        self._charge(32 + sum(s.nodes for s in (*self._policy_seals, *self._baseline_seals)), request_field)
        try:
            self._check_environment_statics(policy, baseline)
            if type(history) is not EnvironmentAgeingState:
                raise TypeError('B63 exact environment state required')
            history.__post_init__()
            policy_identity, baseline_identity = self._identity_binding[-2:]
            if history.policy_identity != policy_identity or history.baseline_network_identity != baseline_identity:
                raise ValueError('B63 stale/foreign environment history')
            key = (EnvironmentAgeingState, _exact_tree(history))
            entry = self._cache.get(key)
            if entry is not None:
                entry.seal.guard()
                self._work['cache_hits'] += 1
                self._cache.move_to_end(key)
                return entry
            self._work['cache_misses'] += 1
            # History is not made static. Copy this exact sample; no caller
            # alias can mutate a retained coefficient realization afterwards.
            private_history = _copy_frozen(history)
            private_history.__post_init__()
            state_identity = digest(private_history)
            self._work['state_digests'] += 1
            self._work['coefficient_attempts'] += 1
            network = _derive(self.environment_policy, private_history, self.baseline)
            self._work['coefficient_realizations'] += 1
            effective = EffectiveEnvironmentNetwork(baseline_identity, policy_identity, state_identity, network)
            solar = retention(self.environment_policy, private_history)
            seal = _Seal((private_history, effective))
            # The full effective network includes inherited parameter provenance.
            # Its reporting identity is computed once for this exact history;
            # all later hits retain the complete graph/seal, never just a hash.
            self._reserve_control(32 + seal.nodes)
            network_identity = digest(network)
            entry = _Realization(key, private_history, effective, solar, network_identity, seal)
            if len(self._cache) >= MAX_CACHE_ENTRIES:
                self._cache.popitem(last=False)
                self._work['cache_evictions'] += 1
            self._cache[key] = entry
            return entry
        except BaseException:
            self._work['environment_failed'] += 1
            raise

    def effective_environment(self, policy, history, baseline):
        return self._realization(policy, history, baseline, 'effective_requests').effective

    def environment_retention(self, policy, history, baseline):
        return self._realization(policy, history, baseline, 'retention_requests').solar_retention

    def environment_metrics(self, policy, history, baseline):
        entry = self._realization(policy, history, baseline, 'metric_requests')
        state, network = entry.history, entry.effective.network
        return (('environment_calendar_seconds', float(state.calendar_seconds)),
                ('environment_pv_exposure_seconds', state.pv_exposure_seconds),
                ('environment_thermal_exposure_seconds', state.thermal_exposure_seconds),
                ('environment_pv_retention', entry.solar_retention),
                *(("environment_epsilon:" + n.node_id.value, n.emissivity.value) for n in network.nodes),
                *(("environment_conductance:" + l.link_id.value, l.conductance_w_per_k.value) for l in network.links))

    def environment_projection(self, policy, history, baseline):
        """Fresh complete old-schema DATA from one exact owned history sample.

        Projection requests are derived metric requests in the existing separate
        operational ledger. No report, trial, physical state or output mapping
        is cached, and the eight-entry realization cap is unchanged.
        """
        entry = self._realization(policy, history, baseline, 'metric_requests')
        network = entry.effective.network
        self._reserve_control(32 + 4 * (len(network.nodes) + len(network.links)))
        from .environment_lifecycle import _projection_data
        return _projection_data(self.environment_policy, entry.history, network,
            entry.solar_retention, entry.effective.policy_identity,
            entry.effective.state_identity, entry.network_identity)

    def validate_environment_binding(self, binding, baseline):
        if binding is None:
            self._guard_identity()
            if baseline is not self._external_baseline and baseline is not self.baseline:
                raise ValueError('B63 foreign environment baseline authority')
            for seal in self._baseline_seals:
                seal.guard()
            return baseline
        if type(binding) is not tuple or len(binding) != 3:
            raise TypeError('B63 explicit effective environment binding')
        effective, policy, history = binding
        if type(effective) is not EffectiveEnvironmentNetwork:
            raise TypeError('B63 exact effective environment owner')
        entry = self._realization(policy, history, baseline, 'binding_requests')
        if effective is not entry.effective and _exact_tree(effective) != _exact_tree(entry.effective):
            self._work['binding_refusals'] += 1
            raise ValueError('B63 effective environment provenance')
        return entry.effective.network

    def snapshot(self):
        """Separate operational DATA; no authority to resume or refund work."""
        self._guard_identity()
        return dict(method=METHOD, source_binding=self.source_binding,
                    root_identity=self.root_identity, model_identity=self.model_identity,
                    role=self.role, cache_entries=len(self._cache), cache_limit=MAX_CACHE_ENTRIES,
                    **self._work,
                    scope='CURRENT_PROCESS_PREPARATION_NOT_SCIENTIFIC_PROPOSAL_OR_ARITHMETIC_WORK')


def prepare_runtime(root, model, role, source_binding):
    return PreparedRuntime(root, model, role, source_binding)
