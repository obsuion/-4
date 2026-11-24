"""Strict, separately versioned Windows/Linux native profiles.

Receipts are DATA, not qualification. Loading additionally checks every live
source byte, extension loader, ABI, callable and capability. B64 stays strict.
"""
from pathlib import Path
from hashlib import sha256
import importlib, importlib.machinery, importlib.util, json, sys, sysconfig
from types import ModuleType, FunctionType
from .lifecycle_backend import canonical, identity, runtime_binding
from . import lifecycle_typed_backend as legacy

METHOD='B65_TYPED_EXECUTION_V2'
BUILD_FORMAT='B65_NATIVE_BUILD_RECEIPT_V2'
TREATED_BUILD_FORMAT='B66_NATIVE_BUILD_RECEIPT_V3'
SERIAL_BUILD_FORMAT='B67_SERIAL_NATIVE_BUILD_RECEIPT_V4'
MODULE='ops_sim.v5._lifecycle_typed65'
WINDOWS='B65_WINDOWS_AMD64_CPYTHON314_ZIG_V1'
WINDOWS_SERIAL='B67_WINDOWS_AMD64_CPYTHON314_ZIG_SERIAL_V1'
LINUX='B65_LINUX_X86_64_CPYTHON314_GCC_V1'
# Source: existing cached official PyPI Cython3.2.4 JSON, exact cp314 Linux
# x86_64 manylinux wheel entry. This task has not downloaded/executed that wheel.
LINUX_CYTHON_WHEEL_SHA256='90f43be4eaa6afd58ce20d970bb1657a3627c44e1760630b82aa256ba74b4acb'
MONITOR_FORMAT='B65_MONOTONE_TYPED_ENTRY_COUNTS_V2'
MONITOR_METHOD='B65_TYPED_NUMERICAL_ENTRY_MONITOR_V2'
WINDOWS_FLAGS=legacy.FLAGS
SERIAL_FLAGS=('build-lib','-dynamic','-lc','-target','x86_64-windows-gnu',
    '-O','ReleaseSafe','-j1','-cflags','-O2','-fno-fast-math','-ffp-contract=off',
    '-fno-associative-math','-DPy_NO_LINK_LIB','--')
LINUX_FLAGS=('-shared','-fPIC','-O2','-fno-fast-math','-ffp-contract=off',
             '-fno-associative-math','-fno-unsafe-math-optimizations','-fexcess-precision=standard')
ENGINE_PATH='ops_sim/v5/lifecycle_typed.pyx'
GENERATED_PATH='ops_sim/v5/lifecycle_typed65.c'
LEGACY_SUPPORT_PATHS=(*legacy.SUPPORT_PATHS,'ops_sim/v5/lifecycle_typed_platform.py',
    'ops_sim/v5/lifecycle_typed_platform_build.py','ops_sim/v5/lifecycle_generation.py',
    'ops_sim/v5/lifecycle_job_prepared.py','ops_sim/v5/lifecycle_typed_context.py',
    'ops_sim/v5/lifecycle_typed_world65.pxi')
TREATMENT_PATH='ops_sim/v5/generated_c_treatment.py'
SUPPORT_PATHS=(*LEGACY_SUPPORT_PATHS,TREATMENT_PATH,'ops_sim/v5/lifecycle_exact_guards.py',
    'ops_sim/v5/lifecycle_exact_guards.pxi','ops_sim/v5/lifecycle_prepared.py','ops_sim/v5/prepared_input_codec.py',
    'ops_sim/v5/lifecycle_state.py','ops_sim/v5/lifecycle_report.py','ops_sim/v5/environment_reporting.py',
    'ops_sim/v5/lifetime_reporting.py','ops_sim/v5/environment_ageing.py','ops_sim/v5/environment_lifecycle.py',
    'ops_sim/v5/metadata_codec.py','ops_sim/v5/long_mission_continuation.py')
DEPENDENCIES_PATH='ops_sim/v5/lifecycle_typed65_build_dependencies.json'
SERIAL_SUPPORT_PATHS=(*SUPPORT_PATHS,DEPENDENCIES_PATH)
SERIAL_SUPPORT_PATHS=tuple(dict.fromkeys((*SERIAL_SUPPORT_PATHS,'ops_sim/v5/experiment_codec.py')))
DIRECTIVES=legacy.DIRECTIVES

def fields(value,names):
    if type(value)is not dict or any(type(k)is not str for k in value)or set(value)!=set(names):
        raise ValueError('B65 exact native fields')

def _text(value):
    if type(value)is not str or not value or len(value)>32768:raise ValueError('B65 bounded native text')
    return value

def profile_for(runtime):
    fields(runtime,('implementation','python','cache_tag','ext_suffix','platform','machine'))
    if any(type(v)is not str for v in runtime.values()):raise ValueError('B65 exact runtime text')
    if runtime['implementation']!='cpython' or not runtime['python'].startswith('3.14.7 ')or runtime['cache_tag']!='cpython-314':
        raise ValueError('B65 requires declared normal-GIL CPython3.14.7')
    if (runtime['platform'],runtime['machine'],runtime['ext_suffix'])==('win32','AMD64','.cp314-win_amd64.pyd'):return WINDOWS
    if (runtime['platform'],runtime['machine'],runtime['ext_suffix'])==('linux','x86_64','.cpython-314-x86_64-linux-gnu.so'):return LINUX
    raise ValueError('B65 unsupported strict native OS/ABI; no Python substitute')

def _binding(v,path):
    fields(v,('path','bytes','sha256'))
    if type(v['path'])is not str or v['path']!=path or type(v['bytes'])is not int or not 0<v['bytes']<=64*2**20:
        raise ValueError('B65 exact native artifact/source binding')
    identity(v['sha256'])

def admit_build_data(value):
    if type(value)is not dict or type(value.get('format'))is not str:
        raise ValueError('B65 exact native receipt version')
    serial=value['format']==SERIAL_BUILD_FORMAT
    treated=value['format']in(TREATED_BUILD_FORMAT,SERIAL_BUILD_FORMAT)
    base=('format','execution_domain','profile','artifact','runtime','engine_source','generated_c',
        'support_sources','compiler','cython','headers','command','capabilities','capability_sha256')
    fields(value,(*base,'generated_c_treatment')if treated else base)
    if value['format']not in(BUILD_FORMAT,TREATED_BUILD_FORMAT,SERIAL_BUILD_FORMAT)or value['execution_domain']!=METHOD:
        raise ValueError('B65 named native receipt/domain')
    runtime=value['runtime'];profile=profile_for(runtime)
    if serial:
        if profile!=WINDOWS:raise ValueError('B67 serial Zig profile is Windows-only')
        profile=WINDOWS_SERIAL
    if type(value['profile'])is not str or value['profile']!=profile:raise ValueError('B65 explicit build profile')
    _binding(value['artifact'],'ops_sim/v5/_lifecycle_typed65'+runtime['ext_suffix'])
    _binding(value['engine_source'],ENGINE_PATH);_binding(value['generated_c'],GENERATED_PATH)
    fields(value['support_sources'],SERIAL_SUPPORT_PATHS if serial else SUPPORT_PATHS if treated else LEGACY_SUPPORT_PATHS)
    for n,v in value['support_sources'].items():_binding(v,n)
    if treated:_admit_treatment(value['generated_c_treatment'],value)
    fields(value['cython'],('version','wheel_sha256','directives'))
    wheel_sha=legacy.CYTHON_WHEEL_SHA256 if profile in(WINDOWS,WINDOWS_SERIAL) else LINUX_CYTHON_WHEEL_SHA256
    if (value['cython']['version']!=legacy.CYTHON_VERSION or value['cython']['wheel_sha256']!=wheel_sha or
            canonical(value['cython']['directives'])!=canonical(DIRECTIVES)):raise ValueError('B65 pinned Cython generation')
    compiler=value['compiler'];fields(compiler,('name','version','executable_sha256','flags','linker'))
    for k in ('name','version','linker'):_text(compiler[k])
    identity(compiler['executable_sha256'])
    expected=SERIAL_FLAGS if serial else WINDOWS_FLAGS if profile==WINDOWS else LINUX_FLAGS
    if type(compiler['flags'])is not list or compiler['flags']!=list(expected):raise ValueError('B65 ordered non-fast compiler flags')
    if profile in(WINDOWS,WINDOWS_SERIAL):
        if (compiler['name']!=('Zig build-lib serial' if serial else 'Zig cc') or compiler['version']!=legacy.ZIG_VERSION or compiler['executable_sha256']!=legacy.ZIG_EXECUTABLE_SHA256 or compiler['linker']!='Zig bundled linker'):
            raise ValueError('B65 Windows toolchain pin')
    else:
        if compiler['name']!='GCC' or not compiler['version'].split('.')[0].isdigit()or not 12<=int(compiler['version'].split('.')[0])<=16:
            raise ValueError('B65 admitted GCC12..16 Linux toolchain; exact observed version/hash retained')
    fields(value['headers'],('Python.h','pyconfig.h'))
    for row in value['headers'].values():
        fields(row,('path','bytes','sha256'));_text(row['path']);identity(row['sha256'])
        if type(row['bytes'])is not int or not 1<=row['bytes']<=2**20:raise ValueError('B65 header binding')
    command=value['command']
    if type(command)is not list or not 6<=len(command)<=32 or any(type(x)is not str or not x or len(x)>32768 for x in command):raise ValueError('B65 exact compiler command')
    if command[1:1+len(expected)]!=list(expected):raise ValueError('B65 command/flag disagreement')
    capability=value['capabilities'];fields(capability,legacy._capability_fields if hasattr(legacy,'_capability_fields')else (
        'method','arithmetic','typed_contiguous_numeric_state','full_coupled','python_model_callbacks','python_model_callbacks_scope',
        'exact_integer_and_fraction','actual_math_fsum','direct_c_libm','changes_scientific_work','canary','limits','capability_screen',
        'entry_monitor','module_basename','python_implementation','python_cache_tag','python_version','platform','quiet_interval_callback_free','scope','speedup'))
    if (capability['method']!=METHOD or capability['arithmetic']!='ORDERED_TYPED_BINARY64_WITH_EXACT_INTEGER_BARRIERS_V1' or
            capability['module_basename']!=Path(value['artifact']['path']).name or capability['python_implementation']!=runtime['implementation']or
            capability['python_cache_tag']!=runtime['cache_tag']or capability['python_version']!=runtime['python']or capability['platform']!=runtime['platform']):raise ValueError('B65 capability/runtime')
    for n in ('typed_contiguous_numeric_state','full_coupled','exact_integer_and_fraction','actual_math_fsum','canary','quiet_interval_callback_free'):
        if capability[n]is not True:raise ValueError('B65 required compiled capability')
    for n in ('python_model_callbacks','direct_c_libm','changes_scientific_work'):
        if capability[n]is not False:raise ValueError('B65 forbidden capability claim')
    if (capability['python_model_callbacks_scope']!='COUPLED_CUT_AND_CLOSED_WORLD_QUIET_ONLY'or
            capability['scope']!='REQUIRES_BOUND_BUILD_RUNTIME_SOURCE_AND_FULL_SCIENTIFIC_EQUALITY'or capability['speedup']!='UNPROVEN'or
            canonical(capability['limits'])!=canonical(dict(nodes=64,links=256,branches=8,loads=7))):raise ValueError('B65 capability scope/caps')
    screen=dict(binary64_storage=True,indexed_arrays=True,ordered_arithmetic=True,exact_time_barrier=True,
        guarded_nonzero_underflow=True,independent_scratch=True,no_model_callbacks=True)
    if canonical(capability['capability_screen'])!=canonical(screen)or canonical(capability['entry_monitor'])!=canonical(dict(method=MONITOR_METHOD,limit=2**56,names=legacy.ENTRY_NAMES)):
        raise ValueError('B65 exact native screen/monitor')
    identity(value['capability_sha256'])
    if sha256(canonical(capability)).hexdigest()!=value['capability_sha256']:raise ValueError('B65 native capability hash')
    return json.loads(canonical(value))

def _admit_treatment(value,build):
    # Shared with the separately versioned legacy-module build family.
    if value is not build['generated_c_treatment']:raise ValueError('B66 exact treatment record owner')
    legacy._admit_c_treatment(build)

def admit_typed_build(value,*,require_quiet=True,execution_domain=None,source=None):
    build=admit_build_data(value)
    if require_quiet is not True or execution_domain not in(None,METHOD):raise ValueError('B65 full native domain only')
    if build['runtime']!=runtime_binding()or sysconfig.get_config_var('Py_GIL_DISABLED'):raise ValueError('B65 native ABI/runtime mismatch')
    root=Path(__file__).resolve().parents[2]if source is None else Path(source).absolute()
    artifact=legacy._live_file(root,build['artifact'])
    for item in(build['engine_source'],build['generated_c'],*build['support_sources'].values()):legacy._live_file(root,item)
    head=artifact.read_bytes()[:64]
    if build['profile']==LINUX and not(head[:6]==b'\x7fELF\x02\x01'and int.from_bytes(head[18:20],'little')==62):raise ValueError('B65 Linux ELF64 x86_64 required')
    if build['profile']in(WINDOWS,WINDOWS_SERIAL) and head[:2]!=b'MZ':raise ValueError('B65 Windows PE extension required')
    spec=importlib.util.find_spec(MODULE)
    if spec is None or type(spec.loader)is not importlib.machinery.ExtensionFileLoader or Path(spec.origin).resolve()!=artifact.resolve():raise ValueError('B65 actual extension loader/origin required')
    module=importlib.import_module(MODULE)
    if type(module)is not ModuleType or type(module.__loader__)is not importlib.machinery.ExtensionFileLoader or Path(module.__file__).resolve()!=artifact.resolve():raise ValueError('B65 imported extension drift')
    for name in('prepare_static','service_port_substep','typed_capability','native_entry_counts',*legacy.FULL_QUIET_EXPORTS,
            'guard_plan_capability','make_guard_arena','compile_guard_plan','guard_exact_plans','guard_arena_receipt','close_guard_arena','guard_process_counts','bind_guard_dispatch','dispatch_exact_guard',
            'input_owner_signature_v1','scientific_output_v1','metadata_codec_counts_v1'):
        f=getattr(module,name,None);t=type(f)
        if (not callable(f)or isinstance(f,FunctionType)or t.__module__!=legacy.CALLABLE_TYPE_MODULE or t.__name__!=legacy.CALLABLE_TYPE_NAME or
                t.__flags__&legacy.CALLABLE_REQUIRED_FLAGS!=legacy.CALLABLE_REQUIRED_FLAGS or getattr(f,'__module__',None)!=MODULE or getattr(f,'__name__',None)!=name):raise ValueError('B65 actual immutable compiled callable: '+name)
    if hasattr(module,'guard_record_capability'):
        for name in ('guard_record_capability','guard_record_counts','bind_guard_identity','bind_guard_generation'):
            f=getattr(module,name,None);t=type(f)
            if (not callable(f)or isinstance(f,FunctionType)or t.__module__!=legacy.CALLABLE_TYPE_MODULE or t.__name__!=legacy.CALLABLE_TYPE_NAME or
                    t.__flags__&legacy.CALLABLE_REQUIRED_FLAGS!=legacy.CALLABLE_REQUIRED_FLAGS or getattr(f,'__module__',None)!=MODULE or getattr(f,'__name__',None)!=name):raise ValueError('YEAR_V4 actual immutable compiled record callable: '+name)
    if canonical(module.typed_capability())!=canonical(build['capabilities']):raise ValueError('B65 actual native capability mismatch')
    admit_native_counts(module.native_entry_counts(),build)
    return module

def admit_native_counts(value,build):
    build=admit_build_data(build);fields(value,('format','method','limit','total','counts','exhausted','gil_held','reset_available',
        'python_implementation','python_cache_tag','python_version','platform','module_basename','source_binding','scope'))
    if (value['format']!=MONITOR_FORMAT or value['method']!=MONITOR_METHOD or type(value['limit'])is not int or value['limit']!=2**56 or
            value['exhausted']is not False or value['gil_held']is not True or value['reset_available']is not False or value['source_binding']!=legacy.SOURCE_SCOPE or value['scope']!=legacy.MONITOR_SCOPE):raise ValueError('B65 monitor identity/scope')
    r=build['runtime']
    for key,v in dict(python_implementation=r['implementation'],python_cache_tag=r['cache_tag'],python_version=r['python'],platform=r['platform'],module_basename=Path(build['artifact']['path']).name).items():
        if type(value[key])is not str or value[key]!=v:raise ValueError('B65 monitor runtime')
    fields(value['counts'],legacy.ENTRY_NAMES)
    if any(type(v)is not int or not 0<=v<=2**56 for v in value['counts'].values())or type(value['total'])is not int or value['total']!=sum(value['counts'].values()):raise ValueError('B65 monitor exact balance')
    return json.loads(canonical(value))

def native_restore_proof(before,after,build,source_binding):
    before=admit_native_counts(before,build);after=admit_native_counts(after,build)
    delta={n:after['counts'][n]-before['counts'][n]for n in legacy.ENTRY_NAMES}
    if any(delta.values())or after['total']!=before['total']:raise ValueError('B65 numerical entries during RESTORE')
    return dict(format='B65_TYPED_RESTORE_ZERO_V2',before=before,after=after,delta=delta,total_delta=0,
        build_sha256=sha256(canonical(build)).hexdigest(),source_binding=identity(source_binding),execution_domain=METHOD)
