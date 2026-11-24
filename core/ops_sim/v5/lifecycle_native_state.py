"""B63 explicit owned-static views over an existing private physical proposal.

Already paid construction/hardware outputs are copied once per role. They are
not recompiled, recomputed checkpoints or new scientific authority. Every leaf
gets a shallow same-type context shell: current dynamic records are forwarded
by reference, never cached; all numerical configuration/routing/wire reads use
the admitted private static copies. Original caller inputs are never swapped.
"""
from __future__ import annotations

from dataclasses import fields, replace

from .context import SimulationContext
from .construction_coupling import ConstructionCompilation, digest as construction_digest
from .construction_service import ConstructionServicePolicy
from .harness_hardware import EffectiveAssemblyHardware
from .lifecycle_prepared import PreparedRuntime, _Seal, _copy_frozen, _exact_tree


METHOD = 'B63_OWNED_STATIC_SERVICE_VIEW_V1'
MAX_CONTROL_UNITS = 2**48


def _physical_scope(runtime, physical):
    from .lifecycle_physics import LifecyclePhysicalState
    from .lifecycle_backend import BackendContext, REFERENCE
    if type(runtime) is not PreparedRuntime or type(physical) is not LifecyclePhysicalState:
        raise TypeError('B63 exact private runtime/physical owner')
    context = physical.backend_context
    if (type(context) is not BackendContext or context.selection == REFERENCE or
            physical.prepared_runtime is not runtime or
            physical.inputs.model is not runtime._external_model or
            type(physical.nominal_provider.role) is not str or
            physical.nominal_provider.role != runtime.role or
            context.source_binding != runtime.source_binding or
            (context.actual if runtime.role == 'ACTUAL' else context.forecast) is not runtime):
        raise ValueError('B63 foreign physical/source/role adapter scope')
    runtime._guard_identity()
    return context


class PreparedServiceAdapter:
    """Bounded static transfer; contains no dynamic physical-result cache."""
    __slots__ = ('runtime', 'compilation', 'hardware', 'limits', 'service_policy',
                 '_configuration_digest', '_compiled_tree', '_hardware_tree',
                 '_static_sources', '_static_trees',
                 '_external_compilation', '_external_hardware',
                 '_external_seals', '_owned_seal', '_binding', '_work')

    def __init__(self, runtime, physical):
        _physical_scope(runtime, physical)
        runtime.check_boundary(runtime._external_root, physical.inputs.model, role=runtime.role,
                               source_binding=runtime.source_binding)
        compilation, hardware = physical.construction.compilation, physical.harness.hardware
        if type(compilation) is not ConstructionCompilation or type(hardware) is not EffectiveAssemblyHardware:
            raise TypeError('B63 exact paid construction/hardware outputs')
        configuration_digest = construction_digest(runtime.model.configuration)
        self.runtime = runtime
        self._configuration_digest = configuration_digest
        self.limits = runtime.model.construction_limits
        self.service_policy = ConstructionServicePolicy()
        # Only independently owned immutable comparands are retained. One
        # shared exact-tree budget bounds all twelve entries together. Incoming
        # policies/forcing and current dynamic records are still checked anew.
        self._static_sources = self._owned_static_values()
        tree_budget = [0, 0]
        self._static_trees = tuple(_exact_tree(value, tree_budget)
                                   for value in self._static_sources)
        self._validate_derived_binding(compilation, hardware)
        # These are copies of the real paid owner outputs, not another call to
        # compile_construction or compile_effective_hardware. Their numerical
        # results/counters stay attached to the original physical owner.
        owned_compilation = _copy_frozen(compilation)
        owned_compilation = replace(owned_compilation, configuration=runtime.model.configuration)
        owned_hardware = _copy_frozen(hardware)
        owned_base = replace(owned_hardware.base_hardware, design=runtime.model.assembly,
                             capabilities=runtime.model.capabilities, actuator=runtime.model.actuator)
        owned_hardware = replace(owned_hardware, base_hardware=owned_base,
                                 configuration=runtime.model.configuration,
                                 augmentation_inputs=runtime.model.augmentation)
        self.compilation, self.hardware = owned_compilation, owned_hardware
        self._compiled_tree, self._hardware_tree = _exact_tree(compilation), _exact_tree(hardware)
        if _exact_tree(owned_compilation) != self._compiled_tree or _exact_tree(owned_hardware) != self._hardware_tree:
            raise ValueError('B63 owned derived output copy mismatch')
        self._external_compilation, self._external_hardware = compilation, hardware
        self._external_seals = (_Seal(compilation), _Seal(hardware))
        # Preserve every previous seal and additionally seal all retained
        # comparands. Replacing their owning model edges is checked separately
        # by identity below; mutating a retained record is caught by this seal.
        self._owned_seal = _Seal((self.compilation, self.hardware, self.limits,
                                  self.service_policy, self._static_sources))
        self._binding = (runtime, runtime.source_binding, runtime.role, runtime.root_identity,
                         runtime.model_identity, self.compilation, self.hardware, self.limits,
                         self.service_policy, self._configuration_digest,
                         self._static_sources, self._static_trees)
        self._work = dict(initializations=1, control_units_reserved=self._owned_seal.nodes +
                          sum(s.nodes for s in self._external_seals) + tree_budget[0], guards=0, rebindings=0,
                          service_attempts=0, service_returned=0, service_failed=0,
                          static_views=0, dynamic_states_cached=0, numerical_recompilations=0)

    def _owned_static_values(self):
        """Fixed twelve-entry private domain; never accepts caller cache data."""
        model = self.runtime.model
        return (model.configuration, model.assembly, model.capabilities,
                model.actuator, model.augmentation, model.protection,
                self.limits, self.service_policy, model.battery_port_policy,
                model.routing, model.configuration.thermal_boundaries,
                model.transmitter)

    def _validate_derived_binding(self, compilation, hardware):
        r = self.runtime
        configuration, assembly, capabilities, actuator, augmentation, *_ = self._static_trees
        if (type(compilation) is not ConstructionCompilation or type(hardware) is not EffectiveAssemblyHardware or
                type(compilation.configuration_digest) is not str or
                compilation.configuration_digest != self._configuration_digest or
                _exact_tree(compilation.configuration) != configuration or
                _exact_tree(hardware.configuration) != configuration or
                _exact_tree(hardware.design) != assembly or
                _exact_tree(hardware.capabilities) != capabilities or
                _exact_tree(hardware.actuator) != actuator or
                _exact_tree(hardware.augmentation_inputs) != augmentation):
            raise ValueError('B63 foreign paid construction/hardware binding')
        if (type(compilation.branches) is not tuple or len(compilation.branches) != 8 or
                tuple(b.line_id for b in compilation.branches) != tuple(l.line_id for l in r.model.configuration.lines) or
                hardware.base_hardware.assembly_digest != r.model.configuration.assembly_digest or
                hardware.augmentation.construction_digest != self._configuration_digest):
            raise ValueError('B63 paid branch/assembly/tensor authority')
        _exact_tree((compilation, hardware))

    def _charge(self, amount, field):
        (r, source, role, root, model, compilation, hardware, limits, service,
         digest, static_sources, static_trees) = self._binding
        if (self.runtime is not r or r.source_binding != source or r.role != role or
                r.root_identity != root or r.model_identity != model or
                self.compilation is not compilation or self.hardware is not hardware or
                self.limits is not limits or self.service_policy is not service or
                self._configuration_digest != digest or
                self._static_sources is not static_sources or self._static_trees is not static_trees):
            raise ValueError('B63 static adapter binding drift')
        if (type(self._work) is not dict or any(type(v) is not int or v < 0 or v > MAX_CONTROL_UNITS for v in self._work.values()) or
                type(amount) is not int or amount < 1 or self._work['control_units_reserved'] + amount > MAX_CONTROL_UNITS):
            raise ValueError('B63_STATIC_VIEW_WORK_LIMIT')
        self._work['control_units_reserved'] += amount
        self._work[field] += 1

    def guard(self, physical, *, public_boundary=False):
        if type(public_boundary) is not bool:
            raise TypeError('B63 exact public boundary flag')
        self._charge(self._owned_seal.nodes + 8, 'guards')
        _physical_scope(self.runtime, physical)
        if any(current is not admitted for current, admitted in
               zip(self._owned_static_values(), self._static_sources)):
            raise ValueError('B63 owned static comparand authority drift')
        if public_boundary:
            self.runtime.check_boundary(self.runtime._external_root, physical.inputs.model,
                                        source_binding=self.runtime.source_binding, role=self.runtime.role)
        compilation, hardware = physical.construction.compilation, physical.harness.hardware
        if compilation is not self._external_compilation or hardware is not self._external_hardware:
            # Fresh paid forecast compilation may have equal immutable DATA.
            # Retain only the latest external static seals, never all forecasts.
            self._validate_derived_binding(compilation, hardware)
            if _exact_tree(compilation) != self._compiled_tree or _exact_tree(hardware) != self._hardware_tree:
                raise ValueError('B63 changed compiled geometry/hardware requires new preparation')
            seals = (_Seal(compilation), _Seal(hardware))
            self._charge(sum(s.nodes for s in seals), 'rebindings')
            self._external_compilation, self._external_hardware = compilation, hardware
            self._external_seals = seals
        for seal in self._external_seals:
            seal.guard()
        self._owned_seal.guard()
        # Existing paid counters are checked, never replaced by preparation.
        physical.construction.work.validate(physical.inputs.construction_limits)
        physical.harness.work.validate(physical.inputs.augmentation.policy)

    def _arguments(self, physical, args, kwargs):
        self.guard(physical)
        if type(args) is not tuple or len(args) != 6 or type(kwargs) is not dict:
            raise TypeError('B63 fixed coupled service call signature')
        candidate, duration, forcing, eps, policy, solar = args
        if type(candidate) is not SimulationContext or candidate.inputs is not physical.inputs.simulation_inputs:
            raise ValueError('B63 foreign private service context/input authority')
        (_, _, _, _, _, protection, limits, service, port,
         routing, thermal, transmitter) = self._static_trees
        if (kwargs.get('compilation') is not physical.construction.compilation or
                kwargs.get('work') is not physical.construction.work or
                _exact_tree(policy) != protection or
                _exact_tree(kwargs.get('limits')) != limits or
                _exact_tree(kwargs.get('service_policy')) != service or
                _exact_tree(kwargs.get('battery_port_policy')) != port):
            raise ValueError('B63 foreign private service configuration/work/policy')
        if (not hasattr(forcing, '__dataclass_fields__') or not type(forcing).__dataclass_params__.frozen or
                _exact_tree(forcing.routing_config) != routing or
                _exact_tree(forcing.thermal_inputs) != thermal):
            raise ValueError('B63 unsupported changed routing/thermal support')
        self._charge(len(fields(SimulationContext)) + 16, 'static_views')
        view = object.__new__(SimulationContext)
        for field in fields(SimulationContext):
            object.__setattr__(view, field.name, self.runtime.model.simulation_inputs if field.name == 'inputs' else getattr(candidate, field.name))
        changes = dict(routing_config=self.runtime.model.routing,
                       thermal_inputs=self.runtime.model.configuration.thermal_boundaries)
        if 'transmitter' in forcing.__dataclass_fields__:
            if _exact_tree(forcing.transmitter) != transmitter:
                raise ValueError('B63 foreign static transmitter')
            changes['transmitter'] = self.runtime.model.transmitter
        owned_forcing = replace(forcing, **changes)
        options = dict(kwargs, compilation=self.compilation, limits=self.limits,
                       service_policy=self.service_policy, battery_port_policy=self.runtime.model.battery_port_policy,
                       prepared_runtime=self.runtime)
        return (view, duration, owned_forcing, eps, self.runtime.model.protection, solar), options

    def service_call(self, physical, function, *args, **kwargs):
        from .construction_service import service_physical_substep
        context = _physical_scope(self.runtime, physical)
        expected = service_physical_substep if context.native is None else context._calls['service_port_substep']
        if function is not expected:
            raise ValueError('B63 unbound coupled numerical callable')
        self._charge(8, 'service_attempts')
        try:
            owned_args, owned_kwargs = self._arguments(physical, args, kwargs)
            result = function(*owned_args, **owned_kwargs)
            # The current leaf publishes only fields inside spacecraft_state.
            # It cannot silently advance a wrapper clock or replace authority.
            shell, original = owned_args[0], args[0]
            if shell.inputs is not self.runtime.model.simulation_inputs:
                raise ValueError('B63 private context authority replaced')
            for field in fields(SimulationContext):
                if field.name not in ('inputs', 'spacecraft_state') and getattr(shell, field.name) is not getattr(original, field.name):
                    raise ValueError('B63 unexpected nonphysical context replacement')
        except BaseException:
            self._work['service_failed'] += 1
            raise
        self._work['service_returned'] += 1
        return result

    def hardware_for(self, physical):
        self.guard(physical)
        return self.hardware

    def snapshot(self):
        self._charge(1, 'guards')
        return dict(method=METHOD, source_binding=self.runtime.source_binding,
                    root_identity=self.runtime.root_identity, model_identity=self.runtime.model_identity,
                    role=self.runtime.role, configuration_digest=self._configuration_digest,
                    **self._work, scope='OPERATIONAL_STATIC_COPY_NOT_SCIENTIFIC_COMPILATION_OR_DYNAMIC_CACHE')


class BackendServiceBinding:
    """Short-lived exact contact dispatch token; never input/checkpoint DATA."""
    __slots__ = ('physical', 'context', 'runtime', '_binding')

    def __init__(self, physical):
        from .lifecycle_prepared import PreparedRuntime
        runtime = physical.prepared_runtime
        if type(runtime) is not PreparedRuntime:
            raise TypeError('B63 contact requires private prepared physical role')
        context = _physical_scope(runtime, physical)
        self.physical, self.context, self.runtime = physical, context, runtime
        self._binding = (physical, context, runtime, runtime.source_binding, runtime.role)

    def check_context(self, candidate):
        physical, context, runtime, source, role = self._binding
        if (self.physical is not physical or self.context is not context or self.runtime is not runtime or
                runtime.source_binding != source or runtime.role != role or
                _physical_scope(runtime, physical) is not context or type(candidate) is not SimulationContext or
                candidate.inputs is not physical.inputs.simulation_inputs):
            raise ValueError('B63 foreign contact dispatch/context authority')

    def call(self, *args, **kwargs):
        from .construction_service import service_physical_substep
        from .lifecycle_backend import service_call
        if not args:
            raise TypeError('B63 contact private context required')
        self.check_context(args[0])
        return service_call(self.physical, service_physical_substep, *args, **kwargs)

    def effective_environment(self, policy, history, baseline):
        _physical_scope(self.runtime, self.physical)
        return self.runtime.effective_environment(policy, history, baseline)


def contact_service_binding(physical):
    from .lifecycle_backend import BackendContext, REFERENCE
    context = physical.backend_context
    if context is None or type(context) is BackendContext and context.selection == REFERENCE:
        return None
    from .lifecycle_typed_context import TypedBackendContext,TypedContactBinding
    if type(context)is TypedBackendContext:return TypedContactBinding(physical)
    if type(context) is not BackendContext:
        raise TypeError('exact contact backend context')
    return BackendServiceBinding(physical)
