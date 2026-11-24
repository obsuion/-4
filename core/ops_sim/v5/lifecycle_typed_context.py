"""B64 explicit current-job typed consumer, separate from the B63 backend.

Static preparation is paid once; ACTUAL/FORECAST never share dynamic state.
The support domain deliberately retains the legacy quiet controller and must
not be described as callback-free quiet execution or H05 completion.
"""
from dataclasses import fields, replace
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from types import FunctionType

from .lifecycle_backend import canonical, runtime_binding, identity
from .lifecycle_typed_backend import (METHOD, FULL_DOMAIN, FULL_DOMAINS, NEW_DOMAIN, SUPPORT_DOMAIN,
    admit_typed_build, admit_build_data)

SELECTIONS = (FULL_DOMAIN, SUPPORT_DOMAIN, NEW_DOMAIN)
CHECKPOINT_FORMAT = 'B64_TYPED_BACKEND_CHECKPOINT_BINDING_V1'
RECEIPT_FORMAT = 'B64_TYPED_BACKEND_EXECUTION_RECEIPT_V1'


def _function_state(function, retained=None, depth=0):
    """Bind wrapped closure functions as well as the public Python wrapper."""
    from .prepared_input_codec import _function_signature
    if depth>16:raise ValueError('B64 bounded consumer function closure')
    result=[_function_signature(function,retained)]
    closure=function.__closure__ or ()
    if retained is not None:retained.extend((closure,*closure))
    for cell in closure:
        value=cell.cell_contents
        if retained is not None:retained.append(value)
        result.append((id(cell),id(value),_function_state(value,retained,depth+1)
            if type(value)is FunctionType else None))
    return tuple(result)


class TypedBackendContext:
    """Private job plus one immutable indexed package, no result cache."""
    def __init__(self, job, selection, source_binding, build):
        from .lifecycle_job_prepared import PreparedJobRuntime
        if type(job) is not PreparedJobRuntime or type(selection) is not str or selection not in SELECTIONS:
            raise TypeError('B64 explicit owned job/typed selection')
        if job.source_binding != identity(source_binding):
            raise ValueError('B64 typed job/source binding')
        build = admit_build_data(build)
        if build['execution_domain'] != selection:
            raise ValueError('B64 typed build/domain mismatch')
        if job.build_sha256 != sha256(canonical(build)).hexdigest():
            raise ValueError('B64 one-shot admission/build binding')
        self.native = admit_typed_build(build, require_quiet=selection in FULL_DOMAINS,
            execution_domain=selection)
        self.job = job; self.root = job.external_root; self.model = job.external_model
        self.selection = selection; self.source_binding = source_binding; self.build = build
        self.actual = job.actual; self.forecast = job.forecast
        self._pid = os.getpid(); self._typed = None; self._derived = {}
        self._calls = {n: getattr(self.native, n) for n in
            ('prepare_static', 'service_port_substep', 'typed_capability', 'native_entry_counts')}
        if selection in FULL_DOMAINS: self._calls['integrate_quiet_hold'] = self.native.integrate_quiet_hold
        if selection == NEW_DOMAIN:
            # These are real global lookups in generated C, including the
            # retained Python math barriers. Strong pins prevent a foreign
            # callback from silently changing the native numerical closure.
            for name in ('prepare_world','world_forcing','world_support_points',
                    'materialize_world_forcing','materialize_world_forcings',
                    'Fraction','fsum','sqrt','exp','nextafter','cos','radians',
                    '_w_right','_w_left','_w_frexp','_w_ldexp','_w_hypot','_w_finite','_w_ulp',
                    '_w_sin','_w_cos','_w_tau','_w_degrees','_w_acos','_w_ceil','_w65_pow',
                    '_B65','_NAMES','METHOD','ARITHMETIC','__file__','__name__','__loader__','__spec__',
                    'ElectricalLimitError','BatteryPortDomainError',
                    'guard_plan_capability','make_guard_arena','compile_guard_plan','guard_exact_plans','guard_arena_receipt','close_guard_arena','guard_process_counts','bind_guard_dispatch','dispatch_exact_guard',
                    'input_owner_signature_v1','scientific_output_v1','metadata_codec_counts_v1'):
                self._calls[name] = getattr(self.native,name)
        if selection == NEW_DOMAIN and hasattr(self.native,'guard_record_capability'):
            for name in ('guard_record_capability','guard_record_counts','bind_guard_identity','bind_guard_generation'):
                self._calls[name]=getattr(self.native,name)
        self._work = dict(attempted=1, completed=1, boundaries=0, leaf_entries=0,
            quiet_entries=0, static_preparations=0, derived_admissions=0,
            typed_static_control_units=0,world_preparation_control_units=0,
            world_preparations=0,progress_summary_calls=0,progress_secondary_validations=0,progress_frontiers_completed=0)
        self._binding = (self, job, self.root, self.model, selection, source_binding,
            sha256(canonical(build)).hexdigest(), self.native, self.actual, self.forecast,
            tuple(self._calls.items()), self._work, self._derived, self.build)
        from . import lifecycle_typed_state
        from . import lifecycle_typed_world
        from .prepared_input_codec import _function_signature
        from . import contact_execution
        self._function_retained=[]
        self._function_pins=tuple((owner,name,fn,_function_state(fn,self._function_retained))
            for owner in (lifecycle_typed_state,lifecycle_typed_world,TypedBackendContext,TypedContactBinding,
                contact_execution,contact_execution._ContactPreparation)
            for name,fn in vars(owner).items() if type(fn).__name__=='function')
        self._function_retained=tuple(self._function_retained)
        self._binding=self._binding+(self._function_pins,self._function_retained)
        if (self.root.service_policy is None or self.root.battery_port_policy is None or
                self.root.environment_ageing_policy is None):
            raise ValueError('B64 typed domain requires service, battery port and exposure')
        network = self.model.simulation_inputs.spacecraft_configuration.thermal.network
        if not 1 <= len(network.nodes) <= 64 or len(network.links) > 256:
            raise ValueError('B64 typed topology admission before numerical work')
        if selection == NEW_DOMAIN:
            from .lifecycle_exact_guards import enable_exact_guards
            enable_exact_guards(job,self.native)
            self._binding=self._binding+(job._guard_plan,)
            from .lifecycle_job_prepared import _guard_generation_owner
            _guard_generation_owner()
            from .lifecycle_generation import enable
            enable(job,self._static_guard)
            if hasattr(self.native,'guard_record_capability'):
                plan=job._guard_plan
                self.native.bind_guard_generation(plan._arena,plan._binding,plan,job,job._validation)
                job._guard_identity()
        self.guard(self.root, self.model)

    def _guard_activation(self):
        old = self._binding
        if (self._pid != os.getpid() or old[0] is not self or old[1] is not self.job or
                old[2] is not self.root or old[3] is not self.model or
                old[4] != self.selection or old[5] != self.source_binding or
                old[13] is not self.build or
                old[14] is not self._function_pins or old[15] is not self._function_retained or
                old[7] is not self.native or old[8] is not self.actual or old[9] is not self.forecast or
                old[11] is not self._work or old[12] is not self._derived or
                type(self._calls) is not dict or set(self._calls) != {n for n, _ in old[10]} or
                any(self._calls[n] is not f or getattr(self.native, n) is not f for n, f in old[10])):
            raise ValueError('B64 typed activation/role/callable drift')
        if self.selection==NEW_DOMAIN and (len(old)!=17 or old[16]is not self.job._guard_plan or old[16]is not self.job._guard_plan_pin):raise ValueError('B69 removed/replaced native guard session')
        self.job._guard_identity()
        if any(type(v) is not int or not 0 <= v <= 2**40 for v in self._work.values()):
            raise ValueError('B64 finite operational entries')
        if self._work['attempted'] != 1 or self._work['completed'] != 1:
            raise ValueError('B64 typed preparation accounting')

    def guard(self, root, model):
        self._guard_activation()
        if root is not self.root or model is not self.model:
            raise ValueError('B64 typed foreign root/model')
        self._work['boundaries'] += 1
        self.job.check_boundary(root, model)
        # This call is a real selected-state boundary, never an arithmetic leaf.
        self._static_guard()
        if self.job._active is not None:self.job._full_guard(self.job._active)

    def _static_guard(self):
        self._guard_activation()
        if self.selection == NEW_DOMAIN:
            validation=self.job._validation
            if validation is None:raise ValueError('B65 missing generation owner')
            if validation.closed():return
        if sha256(canonical(self.build)).hexdigest()!=self._binding[6]:
            raise ValueError('B64 changed typed build receipt')
        for owner,name,fn,signature in self._function_pins:
            if getattr(owner,name)is not fn or _function_state(fn)!=signature:
                raise ValueError('B64 typed consumer function drift: '+name)
        if self._typed is not None:self._typed.guard(compiled=self.job._guard_plan)
        for _,_,seal in self._derived.values():seal.guard(compiled=self.job._guard_plan)

    @contextmanager
    def transaction(self):
        self._guard_activation()
        self._static_guard()
        with self.job.transaction(self.root, self.model):
            from .metadata_codec import metadata_scope
            try:
                if self.selection==NEW_DOMAIN:
                    with metadata_scope(self.native):yield self
                else:yield self # unchanged legacy B64/support dispatch; no B65-only metadata scope
            except BaseException as primary:
                try:self._static_guard()
                except BaseException as secondary:
                    try:
                        self.job._secondary(primary,secondary)
                    except BaseException:
                        try:BaseException.add_note(primary,"B69 secondary annotator failed; original exception preserved")
                        except BaseException:pass
                raise
            else:self._static_guard()

    def _role(self, physical):
        from .lifecycle_physics import LifecyclePhysicalState
        if type(physical) is not LifecyclePhysicalState or physical.backend_context is not self:
            raise ValueError('B64 exact typed physical scope')
        role = physical.prepared_runtime
        if (role is not self.actual and role is not self.forecast or
                role.role != physical.nominal_provider.role or
                physical.inputs.model is not self.model):
            raise ValueError('B64 typed role/truth isolation')
        role.require_transaction()
        return role

    def _static_for(self, physical):
        """Admit fresh paid derived construction once per role frontier."""
        from .lifecycle_job_prepared import _copy_owned
        from .lifecycle_prepared import _exact_tree
        from .lifecycle_prepared import _Seal
        from .construction_service import ConstructionServicePolicy
        from .lifecycle_typed_state import prepare_typed_static
        role = self._role(physical)
        compilation = physical.construction.compilation
        previous = self._derived.get(role.role)
        if previous is None or previous[0] is not compilation:
            tree = _exact_tree(compilation)
            if self._typed is None:
                # Explicit operational prepayment for topology conversion and
                # C-array copies, separate from unchanged scientific fees.
                network=self.job.static.baseline
                reserve=4096+16*(8*len(network.nodes)+3*len(network.links)+10*8+8*7)
                if self._work['typed_static_control_units']+reserve>2**40:
                    raise ValueError('B64_TYPED_STATIC_CONTROL_LIMIT')
                self._work['typed_static_control_units']+=reserve
                owned = _copy_owned(compilation)
                owned = replace(owned, configuration=self.job.static.model.configuration)
                m = self.job.static.model
                self._typed = prepare_typed_static(m.simulation_inputs.spacecraft_configuration,
                    owned, ConstructionServicePolicy(), m.battery_port_policy, m.protection,
                    m.routing, m.construction_limits, module=self.native)
                self.job.admit_thermal_alias(self._typed)
                self._work['static_preparations'] += 1
            elif tree != _exact_tree(self._typed.compilation):
                raise ValueError('B64 changed construction requires new job admission')
            self._derived[role.role] = (compilation, tree, _Seal(compilation))
            self._work['derived_admissions'] += 1
        return self._typed

    def service_call(self, physical, reference, *args, **kwargs):
        from .construction_service import service_physical_substep
        from .context import SimulationContext
        from .lifecycle_physics import LifecycleConstructionLimits
        from .operational_protection import ProtectionPolicy
        from .construction_service import ConstructionServicePolicy
        from .lifecycle_prepared import _exact_tree
        if reference is not service_physical_substep or len(args) != 6:
            raise ValueError('B64 exact coupled public call signature')
        self._guard_activation(); role = self._role(physical)
        static = self._static_for(physical)
        candidate, duration, forcing, eps, policy, solar = args
        if type(candidate) is not SimulationContext or candidate.inputs is not physical.inputs.simulation_inputs:
            raise ValueError('B64 foreign candidate context authority')
        if kwargs.get('compilation') is not physical.construction.compilation:
            raise ValueError('B64 changed coupled compilation authority')
        if (kwargs.get('work') is not physical.construction.work or
                kwargs.get('service_work') is not physical.service_allocation_work or
                kwargs.get('battery_port_work') is not physical.battery_port_work):
            raise ValueError('B64 changed coupled work/role authority')
        if (type(kwargs.get('limits'))is not LifecycleConstructionLimits or
                _exact_tree(kwargs['limits'])!=_exact_tree(self.model.construction_limits)):
            raise ValueError('B64 changed coupled limits authority')
        # The genuine public CONTACT validator returns a canonical policy copy.
        # Its small exact schema/value contract is preserved; pointer identity
        # was never promised by that caller. No model graph is rebuilt here.
        if (type(policy)is not ProtectionPolicy or
                policy is not self.model.protection and
                _exact_tree(policy)!=_exact_tree(self.model.protection)):
            raise ValueError('B64 changed coupled protection policy authority')
        if (type(kwargs.get('service_policy'))is not ConstructionServicePolicy or
                _exact_tree(kwargs['service_policy'])!=_exact_tree(static.service_policy) or
                kwargs.get('battery_port_policy') is not self.model.battery_port_policy):
            raise ValueError('B64 changed coupled service/port policy authority')
        if (_exact_tree(forcing.routing_config)!=_exact_tree(self.model.routing) or
                _exact_tree(forcing.thermal_inputs)!=_exact_tree(self.model.configuration.thermal_boundaries) or
                hasattr(forcing,'transmitter')and _exact_tree(forcing.transmitter)!=_exact_tree(self.model.transmitter)):
            raise ValueError('B64 changed coupled forcing static authority')
        # Only immutable static edges change in this shell. Current spacecraft
        # state and paid work remain the caller's private candidate/ledgers.
        shell = object.__new__(SimulationContext)
        for field in fields(SimulationContext):
            object.__setattr__(shell, field.name,
                self.job.static.model.simulation_inputs if field.name == 'inputs' else getattr(candidate, field.name))
        owned_forcing = replace(forcing, routing_config=static.routing,
            thermal_inputs=static.configuration.thermal_boundaries)
        options = dict(kwargs, compilation=static.compilation, service_policy=static.service_policy,
            limits=static.limits, battery_port_policy=static.port_policy, prepared_runtime=role,
            compiled_static=static)
        self._work['leaf_entries'] += 1
        from .lifecycle_typed_state import service_port_substep
        result = service_port_substep(shell, duration, owned_forcing, eps, static.protection, solar, **options)
        for field in fields(SimulationContext):
            if field.name not in ('inputs', 'spacecraft_state') and getattr(shell, field.name) is not getattr(candidate, field.name):
                raise ValueError('B64 coupled cut replaced nonphysical context authority')
        return result

    def quiet_call(self, physical, reference, *args, **kwargs):
        self._guard_activation(); self._role(physical)
        self._work['quiet_entries'] += 1
        if self.selection == SUPPORT_DOMAIN:
            # Explicit domain selected before work. Never an implicit fallback.
            return reference(*args, **kwargs)
        raise ValueError('B64 full quiet requires the explicit closed whole-piece interface')

    def quiet_piece(self, physical, candidate, hardware, left, right, pending):
        """Whole bounded piece, before schedule; no callback arguments exist."""
        self._guard_activation();self._role(physical)
        if self.selection not in FULL_DOMAINS:raise ValueError('B64 closed quiet is an explicit full-domain selection')
        self._work['quiet_entries']+=1
        static=self._static_for(physical)
        return self._calls['integrate_quiet_hold'](physical,candidate,hardware,left,right,pending,
            compiled_static=static)

    def reserve_world_plan(self, *, profile_count, node_count, profile_cuts, table_cuts):
        """Finite prepayment for indexed world inputs; no physics fee refund."""
        self._guard_activation();self.job.require_transaction()
        for value,maximum in ((profile_count,4096),(node_count,64),(profile_cuts,8192),(table_cuts,65536)):
            if type(value)is not int or not 0<=value<=maximum:raise ValueError('B64 world plan shape domain')
        if profile_count<1 or node_count<1:raise ValueError('B64 nonempty world plan')
        reserve=64+16*profile_count+16*node_count+profile_cuts+table_cuts
        if self._work['world_preparation_control_units']+reserve>2**40:
            raise ValueError('B64_WORLD_PREPARATION_CONTROL_LIMIT')
        self._work['world_preparation_control_units']+=reserve
        self._work['world_preparations']+=1
        return dict(method='B64_WORLD_PLAN_CONTROL_V1',reserved_units=reserve,
            profile_count=profile_count,node_count=node_count,profile_cuts=profile_cuts,table_cuts=table_cuts)

    def checkpoint_binding(self):
        self._guard_activation()
        return dict(format='B65_TYPED_BACKEND_CHECKPOINT_BINDING_V2' if self.selection==NEW_DOMAIN else CHECKPOINT_FORMAT, method=NEW_DOMAIN if self.selection==NEW_DOMAIN else METHOD, selection=self.selection,
            source_binding=self.source_binding, runtime=runtime_binding(), build=json.loads(canonical(self.build)))

    def receipt(self):
        self._guard_activation()
        return dict(format='B65_TYPED_BACKEND_EXECUTION_RECEIPT_V2' if self.selection==NEW_DOMAIN else RECEIPT_FORMAT, method=NEW_DOMAIN if self.selection==NEW_DOMAIN else METHOD, selection=self.selection,
            **(dict(validation_control=self.job._validation.snapshot())if self.selection==NEW_DOMAIN else {}),
            source_binding=self.source_binding, runtime=runtime_binding(),
            build_sha256=sha256(canonical(self.build)).hexdigest(),
            capability_sha256=self.build['capability_sha256'], **self._work,
            owned_job=self.job.receipt(),
            quiet_scope='CALLBACK_FREE' if self.selection in FULL_DOMAINS else 'EXPLICIT_LEGACY_QUIET_CONTROL_H05_INCOMPLETE',
            scope='OPERATIONAL_EXECUTION_NOT_PHYSICAL_MODEL_WORK')


class TypedContactBinding:
    """One exact private contact context; no persisted authority flag."""
    __slots__ = ('physical', 'context', 'runtime', '_pins')
    def __init__(self, physical):
        context = physical.backend_context
        if type(context) is not TypedBackendContext:
            raise TypeError('B64 exact typed contact backend')
        runtime = context._role(physical)
        self.physical = physical; self.context = context; self.runtime = runtime
        self._pins = (physical, context, runtime, os.getpid())

    def check_context(self, candidate):
        from .context import SimulationContext
        if (any(a is not b for a,b in zip(self._pins[:3],(self.physical,self.context,self.runtime))) or self._pins[3]!=os.getpid() or
                self.context._role(self.physical) is not self.runtime or
                type(candidate) is not SimulationContext or candidate.inputs is not self.physical.inputs.simulation_inputs):
            raise ValueError('B64 foreign contact context/role')

    def call(self, *args, **kwargs):
        from .construction_service import service_physical_substep
        if not args: raise TypeError('B64 contact candidate required')
        self.check_context(args[0])
        return self.context.service_call(self.physical, service_physical_substep, *args, **kwargs)

    def effective_environment(self, policy, history, baseline):
        self.context._role(self.physical)
        return self.runtime.effective_environment(policy, history, baseline)


def validate_checkpoint_backend(value):
    from .lifecycle_backend import current_source_binding
    if (type(value) is not dict or set(value) != {'format','method','selection','source_binding','runtime','build'} or
            value['format'] != ('B65_TYPED_BACKEND_CHECKPOINT_BINDING_V2'if value.get('selection')==NEW_DOMAIN else CHECKPOINT_FORMAT) or value['method'] != (NEW_DOMAIN if value.get('selection')==NEW_DOMAIN else METHOD) or
            type(value['selection']) is not str or value['selection'] not in SELECTIONS or
            value['runtime'] != runtime_binding() or identity(value['source_binding']) != current_source_binding()):
        raise ValueError('B64 strict typed checkpoint source/runtime/backend binding')
    admit_typed_build(value['build'], require_quiet=value['selection'] in FULL_DOMAINS,
        execution_domain=value['selection'])
    return value
