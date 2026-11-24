"""B63 explicit process-local numerical backend, separate from B54/B60.

No mutable simulator state is cached and no module globals are patched.
Preparation/dispatch accounting is operational DATA, not scientific credit.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import importlib, json, os, sys, sysconfig

METHOD = 'B63_PREPARED_NATIVE_V1'
REFERENCE = 'REFERENCE'
PREPARED_PYTHON = 'PREPARED_PYTHON'
PREPARED_NATIVE = 'PREPARED_NATIVE'
SELECTIONS = (REFERENCE, PREPARED_PYTHON, PREPARED_NATIVE)
# Distinct B64 domains; legacy SELECTIONS retains its exact B63 meaning.
TYPED_SELECTIONS = ('B64_TYPED_EXECUTION_V1', 'B64_TYPED_COUPLED_LEGACY_QUIET_CONTROL_V1', 'B65_TYPED_EXECUTION_V2')
ALL_SELECTIONS = SELECTIONS + TYPED_SELECTIONS

def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')

def identity(v):
    if type(v)is not str or len(v)!=64 or any(c not in '0123456789abcdef' for c in v):
        raise ValueError('B63 backend SHA256')
    return v


def load_root_for_backend(raw,selection,*,receipts=None):
    """Explicit pure DATA admission, never native activation or dispatch rights.

    A fresh closed codec scope retains all typed constructors and canonical
    roundtrips. It cannot survive this root transaction or cache dynamic state.
    Existing execution/authority/read reservations remain paid on any failure.
    """
    if type(selection)is not str or selection not in ALL_SELECTIONS:
        raise ValueError('explicit input-admission backend')
    if receipts is not None and (type(receipts)is not list or len(receipts)>=64):
        raise ValueError('B63 bounded exact input-admission receipt sink')
    from .lifecycle_document import loads_root
    if selection==REFERENCE:return loads_root(raw)
    from .prepared_input_codec import PreparedInputCodec
    codec=PreparedInputCodec()
    try:return loads_root(raw,input_codec=codec)
    finally:
        receipt=codec.receipt()
        if receipts is not None:receipts.append(receipt)

def _windows_architecture_name(value):
    """Declared native SYSTEM_INFO architectures, never environment authority."""
    if type(value)is not int:
        raise ValueError('B63 exact native Windows processor architecture')
    names={0:'x86',5:'ARM',6:'IA64',9:'AMD64',12:'ARM64'}
    if value not in names:
        raise ValueError('B63 unsupported native Windows processor architecture: '+str(value))
    return names[value]


def _machine_identity():
    """Read only local processor metadata, including under strict offline guard.

    platform.machine() on Windows lazily reads hostname through uname(); that
    is unrelated to this ABI pin and violates the unchanged offline guard.
    GetNativeSystemInfo avoids hostname, WMI, shell and environment variables.
    Fixed WORD/DWORD widths and pointer-sized addresses/mask match SYSTEM_INFO.
    """
    if sys.platform=='win32':
        import ctypes
        class Processor(ctypes.Structure):
            _fields_=[('wProcessorArchitecture',ctypes.c_uint16),('wReserved',ctypes.c_uint16)]
        class Oem(ctypes.Union):
            _fields_=[('dwOemId',ctypes.c_uint32),('processor',Processor)]
        class SystemInfo(ctypes.Structure):
            _fields_=[('u',Oem),('dwPageSize',ctypes.c_uint32),
                ('lpMinimumApplicationAddress',ctypes.c_void_p),('lpMaximumApplicationAddress',ctypes.c_void_p),
                ('dwActiveProcessorMask',ctypes.c_size_t),('dwNumberOfProcessors',ctypes.c_uint32),
                ('dwProcessorType',ctypes.c_uint32),('dwAllocationGranularity',ctypes.c_uint32),
                ('wProcessorLevel',ctypes.c_uint16),('wProcessorRevision',ctypes.c_uint16)]
        info=SystemInfo();info.u.processor.wProcessorArchitecture=0xffff
        library=ctypes.WinDLL('kernel32',use_last_error=True)
        get_info=library.GetNativeSystemInfo
        get_info.argtypes=[ctypes.POINTER(SystemInfo)];get_info.restype=None
        get_info(ctypes.byref(info))
        return _windows_architecture_name(int(info.u.processor.wProcessorArchitecture))
    machine=os.uname().machine
    if type(machine)is not str or not 1<=len(machine)<=128 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-'for c in machine):
        raise ValueError('B63 strict local uname machine identity')
    return machine


def runtime_binding():
    return dict(implementation=sys.implementation.name,python=sys.version,
                cache_tag=sys.implementation.cache_tag,ext_suffix=sysconfig.get_config_var('EXT_SUFFIX'),
                platform=sys.platform,machine=_machine_identity())

def admit_native_build(build):
    expected={'format','artifact','runtime','engine_source_sha256','compiler','capabilities','capability_sha256'}
    if type(build)is not dict or set(build)!=expected or build['format']!='B63_NATIVE_BUILD_RECEIPT_V1':
        raise ValueError('B63 exact native build receipt')
    if build['runtime']!=runtime_binding():raise ValueError('B63 native runtime/ABI mismatch')
    identity(build['engine_source_sha256']);identity(build['capability_sha256'])
    if type(build['capabilities'])is not dict or sha256(canonical(build['capabilities'])).hexdigest()!=build['capability_sha256']:
        raise ValueError('B63 native capability digest')
    c=build['compiler']
    if type(c)is not dict or set(c)!= {'name','version','flags'} or type(c['flags'])is not list or not c['flags'] or any(type(s)is not str for s in c['flags']):
        raise ValueError('B63 compiler binding')
    a=build['artifact'];name='ops_sim/v5/_lifecycle_native'+sysconfig.get_config_var('EXT_SUFFIX')
    if type(a)is not dict or set(a)!= {'path','sha256','bytes'} or a['path']!=name or type(a['bytes'])is not int or not 0<a['bytes']<=64*2**20:
        raise ValueError('B63 native artifact binding')
    identity(a['sha256']);root=Path(__file__).resolve().parents[2];p=root/a['path']
    if p.is_symlink() or not p.is_file() or p.stat().st_size!=a['bytes'] or sha256(p.read_bytes()).hexdigest()!=a['sha256']:
        raise ValueError('B63 native binary bytes')
    pyx=Path(__file__).with_name('lifecycle_native.pyx')
    if sha256(pyx.read_bytes()).hexdigest()!=build['engine_source_sha256']:raise ValueError('B63 native engine source')
    module=importlib.import_module('ops_sim.v5._lifecycle_native')
    from importlib.machinery import ExtensionFileLoader
    from types import ModuleType,FunctionType
    if type(module)is not ModuleType or not isinstance(module.__loader__,ExtensionFileLoader):raise ValueError('B63 actual extension loader required')
    for name in ('service_port_substep','integrate_quiet_hold','complete_port_cut','battery_port_transition','compute_thermal_substep_transition','compute_battery_degradation_substep','native_entry_counts'):
        function=getattr(module,name,None)
        if not callable(function) or isinstance(function,FunctionType) or getattr(function,'__module__',None)!='ops_sim.v5._lifecycle_native':raise ValueError('B63 compiled numerical owner required')
    if Path(module.__file__).resolve()!=p.resolve():raise ValueError('B63 foreign native import')
    actual=module.native_capability()
    if canonical(actual)!=canonical(build['capabilities']):raise ValueError('B63 actual capability screen mismatch')
    if actual.get('method')!=METHOD or actual.get('ordered_python_object_arithmetic')is not True or actual.get('canary')is not True or type(actual.get('capability_screen'))is not dict or not actual['capability_screen'] or any(v is not True for v in actual['capability_screen'].values()):
        raise ValueError('B63 unadmitted numerical capability')
    admit_native_counts(module.native_entry_counts(),build)
    return module


def admit_native_counts(value,build):
    """Strict detached DATA from the build-bound private monotone monitor."""
    fields={'format','method','limit','total','counts','exhausted','gil_held','reset_available',
            'python_implementation','python_cache_tag','python_version','platform','module_basename',
            'source_binding','scope'}
    declaration=build['capabilities'].get('entry_monitor')
    if type(declaration)is not dict or declaration.get('method')!='B63_COMPILED_NUMERICAL_ENTRY_MONITOR_V1':
        raise ValueError('B63 native monitor capability required')
    if type(value)is not dict or set(value)!=fields or value['format']!='B63_MONOTONE_NATIVE_ENTRY_COUNTS_V1':
        raise ValueError('B63 native monitor schema')
    if (value['method']!=declaration['method'] or type(value['limit'])is not int or value['limit']!=2**56 or
            value['limit']!=declaration['limit'] or value['exhausted']is not False or value['gil_held']is not True or
            value['reset_available']is not False or value['module_basename']!=Path(build['artifact']['path']).name or
            value['python_implementation']!=sys.implementation.name or value['python_cache_tag']!=sys.implementation.cache_tag or
            value['python_version']!=sys.version or value['platform']!=sys.platform or
            value['source_binding']!='ACTUAL_EXTENSION_AND_SOURCE_BUILD_RECEIPT_REQUIRED' or
            value['scope']!='OPERATIONAL_ENTRY_ATTEMPTS_NOT_SCIENTIFIC_WORK_OR_DYNAMIC_STATE'):
        raise ValueError('B63 native monitor authority or saturation')
    names=declaration['names']
    if (type(names)is not list or len(names)!=17 or len(set(names))!=17 or
            type(value['counts'])is not dict or set(value['counts'])!=set(names) or
            any(type(v)is not int or not 0<=v<=value['limit'] for v in value['counts'].values()) or
            type(value['total'])is not int or not 0<=value['total']<=value['limit'] or
            sum(value['counts'].values())!=value['total']):
        raise ValueError('B63 native monitor counters')
    return json.loads(canonical(value))


def native_restore_proof(before,after,build,source_binding):
    before=admit_native_counts(before,build);after=admit_native_counts(after,build)
    delta={n:after['counts'][n]-v for n,v in before['counts'].items()}
    total=after['total']-before['total']
    if any(v!=0 for v in delta.values()) or total!=0:
        raise ValueError('B63 native numerical entries during direct restore')
    return dict(format='B63_NATIVE_RESTORE_ZERO_V1',before=before,after=after,delta=delta,
                total_delta=total,build_sha256=sha256(canonical(build)).hexdigest(),
                source_binding=identity(source_binding))

class BackendContext:
    """One invocation with independent actual and received-forecast preparation."""
    def __init__(self,root,model,selection,source_binding,build=None):
        if type(selection)is not str or selection not in SELECTIONS:raise ValueError('B63 explicit backend selection')
        identity(source_binding)
        if selection!=PREPARED_NATIVE and build is not None:raise ValueError('B63 foreign build on Python backend')
        self.selection=selection;self.source_binding=source_binding;self.build=None if build is None else json.loads(canonical(build))
        self.root=root;self.model=model;self.actual=self.forecast=None;self.native=None
        self.attempted=1;self.completed=0;self.boundaries=0;self.leaf_entries=0;self.quiet_entries=0
        if selection==PREPARED_NATIVE:self.native=admit_native_build(self.build)
        if selection==PREPARED_NATIVE and root is not None and (root.environment_ageing_policy is None or root.service_policy is None or root.battery_port_policy is None):raise ValueError('B63 native domain requires declared service/port/exposure owners')
        if selection!=REFERENCE:
            from .lifecycle_prepared import prepare_runtime
            self.actual=prepare_runtime(root,model,'ACTUAL',source_binding)
            self.forecast=prepare_runtime(root,model,'FORECAST',source_binding)
            if self.actual is self.forecast:raise ValueError('B63 aliased roles')
        self._calls={} if self.native is None else {n:getattr(self.native,n) for n in
            ('service_port_substep','integrate_quiet_hold','native_capability','native_entry_counts')}
        self.completed=1
        self._adapters={}
        self._activation=(selection,source_binding,None if self.build is None else sha256(canonical(self.build)).hexdigest(),self.native,self.actual,self.forecast,tuple(self._calls.items()),root,model)

    def _guard_activation(self):
        selection,source,build,native,actual,forecast,calls,root,model=self._activation
        if (type(self.selection)is not str or self.selection!=selection or type(self.source_binding)is not str or self.source_binding!=source or self.root is not root or self.model is not model or self.native is not native or self.actual is not actual or self.forecast is not forecast or (None if self.build is None else sha256(canonical(self.build)).hexdigest())!=build or type(self._calls)is not dict or set(self._calls)!={n for n,f in calls} or any(self._calls[n] is not f or getattr(native,n) is not f for n,f in calls)):
            raise ValueError('B63 backend activation drift')
        for value in (self.attempted,self.completed,self.boundaries,self.leaf_entries,self.quiet_entries):
            if type(value)is not int or not 0<=value<=2**40:raise ValueError('B63 backend operational counter')
        if self.attempted!=1 or self.completed!=1:raise ValueError('B63 backend admission accounting')

    def guard(self,root,model):
        self._guard_activation()
        self.boundaries+=1
        if self.boundaries>2**40:raise ValueError('B63 backend finite boundary allowance')
        if root is not self.root or model is not self.model:raise ValueError('B63 foreign backend authority')
        if self.actual is not None:
            self.actual.check_boundary(root,model,source_binding=self.source_binding,role='ACTUAL')
            self.forecast.check_boundary(root,model,source_binding=self.source_binding,role='FORECAST')
        if self.native is not None and any(getattr(self.native,n) is not f for n,f in self._calls.items()):
            raise ValueError('B63 native callable drift')

    def receipt(self):
        self._guard_activation()
        return dict(format='B63_BACKEND_EXECUTION_RECEIPT_V1',method=METHOD,selection=self.selection,
                    source_binding=self.source_binding,runtime=runtime_binding(),
                    build_sha256=None if self.build is None else sha256(canonical(self.build)).hexdigest(),
                    capability_sha256=None if self.build is None else self.build['capability_sha256'],
                    attempted=self.attempted,completed=self.completed,boundaries=self.boundaries,
                    leaf_entries=self.leaf_entries,quiet_entries=self.quiet_entries,
                    static_views={role:adapter.snapshot() for role,adapter in self._adapters.items()},
                    actual=None if self.actual is None else self.actual.snapshot(),
                    forecast=None if self.forecast is None else self.forecast.snapshot(),
                    scope='OPERATIONAL_EXECUTION_NOT_PHYSICAL_MODEL_WORK')

    def checkpoint_binding(self):
        self._guard_activation()
        return dict(format='B63_BACKEND_CHECKPOINT_BINDING_V1',method=METHOD,selection=self.selection,
                    source_binding=self.source_binding,runtime=runtime_binding(),build=self.build)

def attach_backend(state,selection,source_binding,build=None,*,prepared=None):
    context=BackendContext(state.root,state.model,selection,source_binding,build) if prepared is None else prepared
    from .lifecycle_typed_context import TypedBackendContext
    if type(context) not in (BackendContext,TypedBackendContext) or context.selection!=selection or context.source_binding!=source_binding:raise ValueError('exact process-local prepared scope')
    context.guard(state.root,state.model)
    state.backend_context=context;state.physical.prepared_runtime=context.actual;state.physical.backend_context=context
    return state

def prepared_for(physical):
    return physical.prepared_runtime

def service_call(physical,reference,*args,**kwargs):
    context=physical.backend_context
    if context is None:return reference(*args,**kwargs)
    from .lifecycle_typed_context import TypedBackendContext
    if type(context)is TypedBackendContext:return context.service_call(physical,reference,*args,**kwargs)
    context._guard_activation()
    if context.selection==REFERENCE:return reference(*args,**kwargs)
    context.leaf_entries+=1
    if context.leaf_entries>2**40:raise ValueError('B63 finite leaf-entry allowance')
    from .lifecycle_native_state import PreparedServiceAdapter
    role=physical.prepared_runtime.role
    adapter=context._adapters.get(role)
    if adapter is None:
        adapter=PreparedServiceAdapter(physical.prepared_runtime,physical);context._adapters[role]=adapter
    return adapter.service_call(physical,reference if context.native is None else context._calls['service_port_substep'],*args,**kwargs)

def quiet_call(physical,reference,*args,**kwargs):
    context=physical.backend_context
    if context is None:return reference(*args,**kwargs)
    from .lifecycle_typed_context import TypedBackendContext
    if type(context)is TypedBackendContext:return context.quiet_call(physical,reference,*args,**kwargs)
    context._guard_activation()
    if context.native is None:return reference(*args,**kwargs)
    context.quiet_entries+=1
    if context.quiet_entries>2**40:raise ValueError('B63 finite quiet-entry allowance')
    return context.native.integrate_quiet_hold(*args,**kwargs)


def current_source_binding():
    from .portable_job import source_manifest
    return sha256(canonical(source_manifest(Path(__file__).resolve().parents[2]))).hexdigest()

def validate_checkpoint_backend(value):
    from .lifecycle_typed_context import CHECKPOINT_FORMAT,validate_checkpoint_backend as admit_typed
    if type(value)is dict and value.get('format')in(CHECKPOINT_FORMAT,'B65_TYPED_BACKEND_CHECKPOINT_BINDING_V2'):return admit_typed(value)
    fields={'format','method','selection','source_binding','runtime','build'}
    if type(value)is not dict or set(value)!=fields or value['format']!='B63_BACKEND_CHECKPOINT_BINDING_V1' or value['method']!=METHOD or value['selection'] not in SELECTIONS:
        raise ValueError('B63 checkpoint backend schema')
    if value['runtime']!=runtime_binding() or identity(value['source_binding'])!=current_source_binding():
        raise ValueError('B63 checkpoint backend source/runtime mismatch')
    if value['selection']==PREPARED_NATIVE:admit_native_build(value['build'])
    elif value['build'] is not None:raise ValueError('B63 foreign checkpoint native receipt')
    return value

def admit_backend_receipt(value,contract):
    """Saved returned DATA admission. This grants no import/dispatch rights."""
    from .lifecycle_typed_receipt import FORMAT as TYPED_RECEIPT,admit_backend_receipt as admit_typed_receipt
    if type(value)is dict and value.get('format')in(TYPED_RECEIPT,'B65_TYPED_BACKEND_EXECUTION_RECEIPT_V2'):
        return admit_typed_receipt(value,contract)
    fields={'format','method','selection','source_binding','runtime','build_sha256','capability_sha256',
            'attempted','completed','boundaries','leaf_entries','quiet_entries','actual','forecast','static_views','scope'}
    if type(value)is not dict or set(value)!=fields or value['format']!='B63_BACKEND_EXECUTION_RECEIPT_V1' or value['method']!=METHOD:
        raise ValueError('B63 exact backend execution receipt')
    b=contract['backend_binding'];build=contract['native_build']
    if (value['selection']!=b['selection'] or value['source_binding']!=sha256(canonical(contract['source_manifest'])).hexdigest() or
            value['runtime']!=runtime_binding() or value['build_sha256']!=b['build_sha256'] or value['capability_sha256']!=b['capability_sha256'] or
            value['scope']!='OPERATIONAL_EXECUTION_NOT_PHYSICAL_MODEL_WORK'):
        raise ValueError('B63 backend execution contract binding')
    for n in ('attempted','completed','boundaries','leaf_entries','quiet_entries'):
        if type(value[n])is not int or not 0<=value[n]<=2**40:raise ValueError('B63 returned operational counter')
    if value['attempted']!=1 or value['completed']!=1:raise ValueError('B63 incomplete backend preparation')
    if type(value['static_views'])is not dict or not set(value['static_views'])<={'ACTUAL','FORECAST'}:
        raise ValueError('B63 static view role map')
    if value['selection']==REFERENCE:
        if value['actual'] is not None or value['forecast'] is not None or value['leaf_entries'] or value['quiet_entries'] or value['static_views']:
            raise ValueError('B63 reference acquired native/prepared work')
    else:
        from .lifecycle_prepared import METHOD as PREPARED_METHOD,WORK_FIELDS,MAX_CACHE_ENTRIES
        for role,key in (('ACTUAL','actual'),('FORECAST','forecast')):
            v=value[key]
            expected={'method','source_binding','root_identity','model_identity','role','cache_entries','cache_limit','scope',*WORK_FIELDS}
            if type(v)is not dict or set(v)!=expected or v['method']!=PREPARED_METHOD or v['role']!=role or v['source_binding']!=value['source_binding'] or v['root_identity']!=contract['root_identity'] or v['scope']!='CURRENT_PROCESS_PREPARATION_NOT_SCIENTIFIC_PROPOSAL_OR_ARITHMETIC_WORK':
                raise ValueError('B63 prepared receipt authority/role')
            identity(v['model_identity'])
            if type(v['cache_entries'])is not int or not 0<=v['cache_entries']<=MAX_CACHE_ENTRIES or type(v['cache_limit'])is not int or v['cache_limit']!=MAX_CACHE_ENTRIES:
                raise ValueError('B63 prepared cache bounds')
            if any(type(v[n])is not int or not 0<=v[n]<=2**48 for n in WORK_FIELDS):raise ValueError('B63 prepared work types')
            if v['boundary_completed']+v['boundary_failed']!=v['boundary_attempts'] or v['coefficient_realizations']>v['coefficient_attempts']:
                raise ValueError('B63 prepared work balance')
        for role,v in value['static_views'].items():
            from .lifecycle_native_state import METHOD as VIEW_METHOD
            names={'method','source_binding','root_identity','model_identity','role','configuration_digest','initializations',
                   'control_units_reserved','guards','rebindings','service_attempts','service_returned','service_failed',
                   'static_views','dynamic_states_cached','numerical_recompilations','scope'}
            if type(v)is not dict or set(v)!=names or v['method']!=VIEW_METHOD or v['role']!=role or v['source_binding']!=value['source_binding'] or v['root_identity']!=contract['root_identity']:
                raise ValueError('B63 owned view receipt binding')
            for name in ('model_identity','configuration_digest'):identity(v[name])
            counters=names-{'method','source_binding','root_identity','model_identity','role','configuration_digest','scope'}
            if any(type(v[n])is not int or not 0<=v[n]<=2**48 for n in counters) or v['initializations']!=1 or v['dynamic_states_cached'] or v['numerical_recompilations'] or v['service_returned']+v['service_failed']!=v['service_attempts']:
                raise ValueError('B63 owned view accounting')
    return value
