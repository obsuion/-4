"""B64 typed extension DATA/ABI admission; no automatic build or fallback.

Detached receipts can be inspected without importing an extension. Live
activation additionally admits the actual loader, local bytes and monitor.
The explicitly named coupled/legacy-quiet development domain is not H05.
"""
from hashlib import sha256
from pathlib import Path
from types import FunctionType,ModuleType
import importlib
import importlib.machinery
import importlib.util
import json
import sys

METHOD='B64_TYPED_EXECUTION_V1'
SELECTION=METHOD
FULL_DOMAIN=METHOD
NEW_DOMAIN='B65_TYPED_EXECUTION_V2'
FULL_DOMAINS=(FULL_DOMAIN,NEW_DOMAIN)
SUPPORT_DOMAIN='B64_TYPED_COUPLED_LEGACY_QUIET_CONTROL_V1'
BUILD_FORMAT='B64_NATIVE_BUILD_RECEIPT_V1'
TREATED_BUILD_FORMAT='B66_LEGACY_NATIVE_BUILD_RECEIPT_V2'
MODULE='ops_sim.v5._lifecycle_typed'
MONITOR_METHOD='B64_TYPED_NUMERICAL_ENTRY_MONITOR_V1'
MONITOR_FORMAT='B64_MONOTONE_TYPED_ENTRY_COUNTS_V1'
MONITOR_SCOPE='OPERATIONAL_ENTRY_ATTEMPTS_NOT_SCIENTIFIC_WORK_OR_DYNAMIC_STATE'
SOURCE_SCOPE='ACTUAL_EXTENSION_AND_SOURCE_BUILD_RECEIPT_REQUIRED'
ENTRY_NAMES=('service_port_substep','allocation_trial','electrical_line','battery_port_transition',
    'thermal_transition','battery_degradation','solar_degradation','port_ageing','quiet_interval','quiet_error_norm',
    'world_forcing')
CALLBACK_SCOPE='COUPLED_CUT_AND_CLOSED_WORLD_QUIET_ONLY'
FULL_QUIET_EXPORTS=('prepare_world','world_forcing','world_support_points','materialize_world_forcing',
    'materialize_world_forcings','integrate_quiet_hold')
# The pinned 3.2.4 generated C declares this exact type via
# __PYX_ABI_MODULE_NAME + '.cython_function_or_method', with both flags below.
# These are loader/ABI screens, not permission to substitute another callable.
CALLABLE_TYPE_MODULE='_cython_3_2_4'
CALLABLE_TYPE_NAME='cython_function_or_method'
CALLABLE_REQUIRED_FLAGS=(1<<8)|(1<<7) # IMMUTABLETYPE | DISALLOW_INSTANTIATION
SCREEN_NAMES=('binary64_storage','indexed_arrays','ordered_arithmetic','exact_time_barrier',
    'guarded_nonzero_underflow','independent_scratch','no_model_callbacks')
FLAGS=('cc','-shared','-target','x86_64-windows-gnu','-O2','-fno-fast-math',
    '-ffp-contract=off','-fno-associative-math','-DPy_NO_LINK_LIB')
CYTHON_VERSION='3.2.4'
ZIG_VERSION='0.15.2'
ZIG_EXECUTABLE_SHA256='d408dd38eed3e5204af841bcebf70502a4dbbb8399a3a3262be55059370bc018'
ZIG_ARCHIVE_SHA256='3a0ed1e8799a2f8ce2a6e6290a9ff22e6906f8227865911fb7ddedc3cc14cb0c'
CYTHON_WHEEL_SHA256='983f9d2bb8a896e16fa68f2b37866ded35fa980195eefe62f764ddc5f9f5ef8e'
DIRECTIVES=dict(infer_types=False,annotation_typing=False,binding=True,cdivision=False,overflowcheck=True)
ENGINE_PATH='ops_sim/v5/lifecycle_typed.pyx'
GENERATED_PATH='ops_sim/v5/lifecycle_typed.c'
INCLUDE_PATHS=('ops_sim/v5/lifecycle_typed_world.pxi','ops_sim/v5/lifecycle_typed_quiet.pxi')
SUPPORT_PATHS=('ops_sim/v5/lifecycle_typed_state.py','ops_sim/v5/lifecycle_typed_backend.py',
    'ops_sim/v5/lifecycle_typed_build.py','ops_sim/v5/lifecycle_typed_world.py',*INCLUDE_PATHS)
TREATMENT_PATH='ops_sim/v5/generated_c_treatment.py'
TREATED_SUPPORT_PATHS=(*SUPPORT_PATHS,'ops_sim/v5/lifecycle_typed_world65.pxi',TREATMENT_PATH)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')


def identity(value):
    if type(value)is not str or len(value)!=64 or any(c not in '0123456789abcdef'for c in value):
        raise ValueError('B64 typed SHA256')
    return value


def _fields(value,names,label):
    if type(value)is not dict or any(type(k)is not str for k in value) or set(value)!=set(names):raise ValueError('B64 exact '+label+' fields')


def _runtime(value):
    _fields(value,('implementation','python','cache_tag','ext_suffix','platform','machine'),'typed runtime')
    if any(type(v)is not str or not 1<=len(v)<=4096 for v in value.values()):raise ValueError('B64 typed runtime text')
    if (value['implementation']!='cpython' or value['cache_tag']!='cpython-314' or
            value['platform']!='win32' or value['machine']!='AMD64' or value['ext_suffix']!='.cp314-win_amd64.pyd'):
        raise ValueError('B64 declared pinned compiler target/ABI')


def _file_data(value,path,maximum):
    _fields(value,('path','sha256','bytes'),'typed file binding')
    if type(value['path'])is not str or value['path']!=path:raise ValueError('B64 typed exact source/artifact path')
    identity(value['sha256'])
    if type(value['bytes'])is not int or not 0<value['bytes']<=maximum:raise ValueError('B64 typed file byte bound')


def _capability(value,runtime,artifact):
    names=('method','arithmetic','typed_contiguous_numeric_state','full_coupled','python_model_callbacks',
        'python_model_callbacks_scope','exact_integer_and_fraction','actual_math_fsum','direct_c_libm',
        'changes_scientific_work','canary','limits','capability_screen','entry_monitor','module_basename',
        'python_implementation','python_cache_tag','python_version','platform','quiet_interval_callback_free','scope','speedup')
    _fields(value,names,'typed capability')
    text=('method','arithmetic','python_model_callbacks_scope','module_basename','python_implementation',
        'python_cache_tag','python_version','platform','scope','speedup')
    if any(type(value[n])is not str for n in text):raise ValueError('B64 exact typed capability text')
    if (value['method']!=METHOD or value['arithmetic']!='ORDERED_TYPED_BINARY64_WITH_EXACT_INTEGER_BARRIERS_V1' or
            value['python_model_callbacks_scope']!=CALLBACK_SCOPE or
            value['scope']!='REQUIRES_BOUND_BUILD_RUNTIME_SOURCE_AND_FULL_SCIENTIFIC_EQUALITY' or value['speedup']!='UNPROVEN'):
        raise ValueError('B64 typed capability identity/scope')
    for name in ('typed_contiguous_numeric_state','full_coupled','exact_integer_and_fraction','actual_math_fsum','canary'):
        if value[name]is not True:raise ValueError('B64 missing typed capability: '+name)
    for name in ('python_model_callbacks','direct_c_libm','changes_scientific_work'):
        if value[name]is not False:raise ValueError('B64 forbidden typed capability: '+name)
    if type(value['quiet_interval_callback_free'])is not bool:raise ValueError('B64 exact quiet capability flag')
    _fields(value['limits'],('nodes','links','branches','loads'),'typed capacity')
    if any(type(value['limits'][n])is not int or value['limits'][n]!=v for n,v in
            (('nodes',64),('links',256),('branches',8),('loads',7))):raise ValueError('B64 fixed typed capacities')
    _fields(value['capability_screen'],SCREEN_NAMES,'typed screen')
    if any(v is not True for v in value['capability_screen'].values()):raise ValueError('B64 typed screen refusal')
    monitor=value['entry_monitor'];_fields(monitor,('method','limit','names'),'typed monitor declaration')
    if (type(monitor['method'])is not str or monitor['method']!=MONITOR_METHOD or type(monitor['limit'])is not int or monitor['limit']!=2**56 or
            type(monitor['names'])is not list or any(type(n)is not str for n in monitor['names']) or monitor['names']!=list(ENTRY_NAMES)):
        raise ValueError('B64 typed monitor declaration')
    if (value['module_basename']!=Path(artifact['path']).name or value['python_implementation']!=runtime['implementation'] or
            value['python_cache_tag']!=runtime['cache_tag'] or value['python_version']!=runtime['python'] or value['platform']!=runtime['platform']):
        raise ValueError('B64 typed capability runtime binding')


def admit_build_data(build):
    """Strict detached receipt DATA only: no paths opened or code activated."""
    if type(build)is dict and build.get('format')in('B65_NATIVE_BUILD_RECEIPT_V2','B66_NATIVE_BUILD_RECEIPT_V3','B67_SERIAL_NATIVE_BUILD_RECEIPT_V4'):
        from .lifecycle_typed_platform import admit_build_data as admit_new
        return admit_new(build)
    treated=type(build)is dict and build.get('format')==TREATED_BUILD_FORMAT
    names=('format','execution_domain','artifact','runtime','engine_source','generated_c','support_sources',
        'compiler','cython','capabilities','capability_sha256')
    _fields(build,(*names,'generated_c_treatment')if treated else names,'typed build receipt')
    if type(build['format'])is not str or build['format']not in(BUILD_FORMAT,TREATED_BUILD_FORMAT):raise ValueError('B64 typed build version')
    _runtime(build['runtime']);runtime=build['runtime']
    _file_data(build['artifact'],'ops_sim/v5/_lifecycle_typed'+runtime['ext_suffix'],64*2**20)
    _file_data(build['engine_source'],ENGINE_PATH,16*2**20)
    _file_data(build['generated_c'],GENERATED_PATH,64*2**20)
    if treated:admitted_support=TREATED_SUPPORT_PATHS
    else:admitted_support=SUPPORT_PATHS if set(build['support_sources'])==set(SUPPORT_PATHS)else(*SUPPORT_PATHS,'ops_sim/v5/lifecycle_typed_world65.pxi')
    _fields(build['support_sources'],admitted_support,'typed support source')
    for path,value in build['support_sources'].items():_file_data(value,path,16*2**20)
    if treated:_admit_c_treatment(build)
    compiler=build['compiler'];_fields(compiler,('name','version','flags','executable_sha256','archive_sha256'),'typed compiler')
    if any(type(compiler[n])is not str for n in ('name','version','executable_sha256','archive_sha256')):
        raise ValueError('B64 exact typed compiler text')
    if (compiler['name']!='Zig cc' or compiler['version']!=ZIG_VERSION or type(compiler['flags'])is not list or any(type(s)is not str for s in compiler['flags']) or
            compiler['flags']!=list(FLAGS) or compiler['executable_sha256']!=ZIG_EXECUTABLE_SHA256 or compiler['archive_sha256']!=ZIG_ARCHIVE_SHA256):
        raise ValueError('B64 fixed typed compiler/flags')
    cython=build['cython'];_fields(cython,('version','wheel_sha256','directives'),'typed Cython recipe')
    if type(cython['version'])is not str or type(cython['wheel_sha256'])is not str or cython['version']!=CYTHON_VERSION or cython['wheel_sha256']!=CYTHON_WHEEL_SHA256 or type(cython['directives'])is not dict or set(cython['directives'])!=set(DIRECTIVES) or any(type(cython['directives'][n])is not bool or cython['directives'][n]is not v for n,v in DIRECTIVES.items()):
        raise ValueError('B64 fixed typed Cython recipe')
    identity(build['capability_sha256'])
    _capability(build['capabilities'],runtime,build['artifact'])
    if sha256(canonical(build['capabilities'])).hexdigest()!=build['capability_sha256']:raise ValueError('B64 typed capability digest')
    domain=build['execution_domain']
    if type(domain)is not str or domain not in (FULL_DOMAIN,SUPPORT_DOMAIN):raise ValueError('B64 explicit typed execution domain')
    if domain==FULL_DOMAIN and build['capabilities']['quiet_interval_callback_free']is not True:
        raise ValueError('B64 full typed domain requires callback-free quiet')
    return json.loads(canonical(build))


def _admit_c_treatment(build):
    """One strict proof-record schema for both newly built module families."""
    from .generated_c_treatment import METHOD as treatment_method,EQUIVALENCE
    value=build['generated_c_treatment']
    _fields(value,('format','equivalence','transform_source','raw_artifact','raw_sha256','raw_bytes',
        'normalized_sha256','normalized_bytes','changed_lines','removed_bytes','physical_lines',
        'preprocessing_tokens','preprocessing_sha256'),'generated-C treatment')
    if type(value['format'])is not str or value['format']!=treatment_method or value['equivalence']!=EQUIVALENCE:
        raise ValueError('B66 explicit generated-C treatment version/equivalence')
    _file_data(value['transform_source'],TREATMENT_PATH,16*2**20)
    if canonical(value['transform_source'])!=canonical(build['support_sources'][TREATMENT_PATH]):
        raise ValueError('B66 generated-C transform source binding')
    raw_name='raw-generated/'+Path(build['generated_c']['path']).name
    if type(value['raw_artifact'])is not str or value['raw_artifact']!=raw_name:
        raise ValueError('B66 raw generated-C evidence artifact name')
    for key in('raw_sha256','normalized_sha256','preprocessing_sha256'):identity(value[key])
    for key in('raw_bytes','normalized_bytes','physical_lines','preprocessing_tokens'):
        if type(value[key])is not int or not 1<=value[key]<=64*2**20:
            raise ValueError('B66 bounded generated-C treatment size/count')
    for key in('changed_lines','removed_bytes'):
        if type(value[key])is not int or not 0<=value[key]<=64*2**20:
            raise ValueError('B66 exact generated-C treatment count')
    if (value['raw_bytes']-value['normalized_bytes']!=value['removed_bytes']or
            value['changed_lines']>value['physical_lines']or
            (value['removed_bytes']==0)!=(value['changed_lines']==0)or
            value['normalized_bytes']!=build['generated_c']['bytes']or
            value['normalized_sha256']!=build['generated_c']['sha256']):
        raise ValueError('B66 generated-C treatment conservation/binding')


def _live_file(root,binding):
    path=root/binding['path']
    for entry in (path,*path.parents):
        if entry.is_symlink() or entry.exists() and getattr(entry,'is_junction',lambda:False)():
            raise ValueError('B64 typed source/artifact link refusal')
        if entry==root:break
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or path.stat().st_size!=binding['bytes']:
        raise ValueError('B64 typed source/artifact bytes')
    if sha256(path.read_bytes()).hexdigest()!=binding['sha256']:raise ValueError('B64 typed source/artifact hash')
    return path


def _compiled_callable(function,name):
    owner=type(function)
    if (not callable(function) or isinstance(function,FunctionType) or
            owner.__module__!=CALLABLE_TYPE_MODULE or owner.__name__!=CALLABLE_TYPE_NAME or
            owner.__flags__&CALLABLE_REQUIRED_FLAGS!=CALLABLE_REQUIRED_FLAGS or
            getattr(function,'__module__',None)!=MODULE or getattr(function,'__name__',None)!=name):
        raise ValueError('B64 compiled typed callable required: '+name)
    return function


def admit_typed_build(build,*,require_quiet=True,execution_domain=None,source=None):
    """Admit the real extension. Partial controls require two explicit pins."""
    if type(build)is dict and build.get('format')in('B65_NATIVE_BUILD_RECEIPT_V2','B66_NATIVE_BUILD_RECEIPT_V3','B67_SERIAL_NATIVE_BUILD_RECEIPT_V4'):
        from .lifecycle_typed_platform import admit_typed_build as admit_new
        return admit_new(build,require_quiet=require_quiet,execution_domain=execution_domain,source=source)
    build=admit_build_data(build)
    if type(require_quiet)is not bool:raise ValueError('B64 exact typed quiet requirement')
    if execution_domain is not None and type(execution_domain)is not str:raise ValueError('B64 exact typed execution-domain argument')
    if require_quiet:
        if execution_domain not in (None,FULL_DOMAIN) or build['execution_domain']!=FULL_DOMAIN or build['capabilities']['quiet_interval_callback_free']is not True:
            raise ValueError('B64 full typed activation requires full quiet domain')
    elif execution_domain!=SUPPORT_DOMAIN or build['execution_domain']!=SUPPORT_DOMAIN:
        raise ValueError('B64 partial typed control requires separately bound support domain')
    from .lifecycle_backend import runtime_binding
    if build['runtime']!=runtime_binding():raise ValueError('B64 typed runtime/ABI mismatch')
    root=Path(__file__).resolve().parents[2] if source is None else Path(source).absolute()
    artifact=_live_file(root,build['artifact'])
    for item in (build['engine_source'],build['generated_c'],*build['support_sources'].values()):_live_file(root,item)
    spec=importlib.util.find_spec(MODULE)
    if spec is None or type(spec.loader)is not importlib.machinery.ExtensionFileLoader or Path(spec.origin).resolve()!=artifact.resolve():
        raise ValueError('B64 actual typed ExtensionFileLoader required before import')
    module=importlib.import_module(MODULE)
    if type(module)is not ModuleType or type(module.__loader__)is not importlib.machinery.ExtensionFileLoader or Path(module.__file__).resolve()!=artifact.resolve():
        raise ValueError('B64 foreign typed extension import')
    required=('prepare_static','service_port_substep','typed_capability','native_entry_counts')
    if require_quiet:required=(*required,*FULL_QUIET_EXPORTS)
    for name in required:
        function=getattr(module,name,None)
        _compiled_callable(function,name)
    capability=json.loads(canonical(module.typed_capability()))
    if capability!=build['capabilities']:raise ValueError('B64 actual typed capability mismatch')
    admit_native_counts(module.native_entry_counts(),build)
    return module


def admit_native_counts(value,build):
    """Detached, monotone numeric entry-attempt DATA; no execution rights."""
    if type(build)is dict and build.get('format')in('B65_NATIVE_BUILD_RECEIPT_V2','B66_NATIVE_BUILD_RECEIPT_V3'):
        from .lifecycle_typed_platform import admit_native_counts as admit_new
        return admit_new(value,build)
    build=admit_build_data(build)
    fields=('format','method','limit','total','counts','exhausted','gil_held','reset_available','python_implementation',
        'python_cache_tag','python_version','platform','module_basename','source_binding','scope')
    _fields(value,fields,'typed monitor snapshot')
    if any(type(value[n])is not str for n in ('format','method','python_implementation','python_cache_tag','python_version','platform','module_basename','source_binding','scope')):
        raise ValueError('B64 exact typed monitor text')
    runtime=build['runtime']
    if (value['format']!=MONITOR_FORMAT or value['method']!=MONITOR_METHOD or type(value['limit'])is not int or value['limit']!=2**56 or
            value['exhausted']is not False or value['gil_held']is not True or value['reset_available']is not False or
            value['module_basename']!=Path(build['artifact']['path']).name or value['python_implementation']!=runtime['implementation'] or
            value['python_cache_tag']!=runtime['cache_tag'] or value['python_version']!=runtime['python'] or value['platform']!=runtime['platform'] or
            value['source_binding']!=SOURCE_SCOPE or value['scope']!=MONITOR_SCOPE):
        raise ValueError('B64 typed monitor runtime/scope/saturation')
    _fields(value['counts'],ENTRY_NAMES,'typed monitor counts')
    if any(type(n)is not int or not 0<=n<=value['limit']for n in value['counts'].values()) or type(value['total'])is not int or not 0<=value['total']<=value['limit'] or sum(value['counts'].values())!=value['total']:
        raise ValueError('B64 typed monitor exact counters/balance')
    return json.loads(canonical(value))


def native_restore_proof(before,after,build,source_binding):
    if type(build)is dict and build.get('format')in('B65_NATIVE_BUILD_RECEIPT_V2','B66_NATIVE_BUILD_RECEIPT_V3'):
        from .lifecycle_typed_platform import native_restore_proof as prove_new
        return prove_new(before,after,build,source_binding)
    before=admit_native_counts(before,build);after=admit_native_counts(after,build)
    delta={name:after['counts'][name]-before['counts'][name]for name in ENTRY_NAMES}
    total=after['total']-before['total']
    if total!=0 or any(n!=0 for n in delta.values()):raise ValueError('B64 typed numerical entries during direct restore')
    return dict(format='B64_TYPED_RESTORE_ZERO_V1',before=before,after=after,delta=delta,total_delta=total,
        build_sha256=sha256(canonical(build)).hexdigest(),source_binding=identity(source_binding),execution_domain=build['execution_domain'])
