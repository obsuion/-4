"""Explicit B66 treated-C native builder; invoke in an owned finite process.

No install, download or overwrite. Linux is a separate ELF/GCC/CPython3.14.7
profile, not a relabelled Windows receipt. Tool/header hashes are observed.
"""
from pathlib import Path
from hashlib import sha256
import argparse, importlib, json, os, subprocess, sys, sysconfig, time, traceback
from . import lifecycle_typed_platform as backend
from .lifecycle_backend import canonical,runtime_binding
from .generated_c_treatment import normalize_generated_c

CYTHON_GENERATOR_V1 = r'''from pathlib import Path
from hashlib import sha256
import json,os,sys,time,traceback,platform
# CPython's local uname cache avoids a later socket.gethostname audit event
# inside pinned Cython. This performs no lookup or connection. All Cython
# imports still occur only after the unchanged offline audit hook is active.
platform.uname()
def deny_network(event,args):
 if event.startswith('socket.') or event=='urllib.Request':
  raise RuntimeError('Python network disabled for offline reconstruction')
sys.addaudithook(deny_network)
c=json.loads(sys.argv[1]);start=time.perf_counter_ns();cpu=time.process_time_ns()
report=dict(format='YEAR_V5_ISOLATED_CYTHON_RESULT_V1',status='FAIL',
 offline_guard='SOCKET_AND_URLLIB_AUDIT_DENY_V1',
 working_directory=str(Path.cwd().resolve()),
 interpreter=dict(executable=sys.executable,version=sys.version,implementation=sys.implementation.name,cache_tag=sys.implementation.cache_tag),
 source_sha256=sha256(Path(c['source']).read_bytes()).hexdigest(),module=c['module'],directives=c['directives'])
try:
 if report['interpreter']!=c['interpreter'] or report['source_sha256']!=c['source_sha256'] or report['working_directory']!=c['working_directory']:
  raise ValueError('YEAR-V5 generation runtime/source binding')
 tree=Path(c['cython']).resolve(strict=True);sys.path.insert(0,str(tree));import Cython
 if Cython.__version__!=c['version'] or not Path(Cython.__file__).resolve().is_relative_to(tree):
  raise ValueError('YEAR-V5 pinned generation package')
 from Cython.Compiler.Main import compile as compile_cython,CompilationOptions,default_options
 result=compile_cython(c['source'],options=CompilationOptions(default_options,
  output_file=c['output'],language_level=3,compiler_directives=c['directives']),full_module_name=c['module'])
 report.update(cython_version=Cython.__version__,cython_origin=str(Path(Cython.__file__).resolve()),num_errors=result.num_errors)
 if result.num_errors:raise ValueError('B65 Cython compile errors')
 raw=Path(c['output']).read_bytes();report.update(status='PASS_GENERATION_ONLY',generated_bytes=len(raw),generated_sha256=sha256(raw).hexdigest())
except BaseException:
 report['traceback']=traceback.format_exc()
finally:
 report.update(wall_ns=time.perf_counter_ns()-start,process_cpu_ns=time.process_time_ns()-cpu)
 with Path(c['report']).open('xb')as f:
  f.write(json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8'));f.flush();os.fsync(f.fileno())
raise SystemExit(0 if report['status']=='PASS_GENERATION_ONLY' else 1)
'''


def isolated_cython_generation(cython,source,output,evidence,seconds):
    """Finite build phase: release the Cython process before starting Zig.

    This changes build-process overlap only. The same wheel/tree/version,
    module, directives, input and raw output filename remain authoritative.
    Its child inherits the existing private Job; this grants no numerical entry.
    """
    if type(seconds)is not int or not 1<=seconds<=240:
        raise ValueError('YEAR-V5 finite Cython generation allowance')
    if any(n=='Cython'or n.startswith('Cython.')for n in sys.modules):
        raise ValueError('YEAR-V5 isolated builder parent already imported Cython')
    cython=Path(cython).resolve(strict=True);source=Path(source).resolve(strict=True)
    output=Path(output);evidence=Path(evidence)
    result_path=evidence/'CYTHON-GENERATION-CHILD.json'
    launch=evidence/'CYTHON-GENERATION-LAUNCH.json'
    envelope=evidence/'CYTHON-GENERATION-ENVELOPE.json'
    stdout=evidence/'cython-generation.stdout.txt';stderr=evidence/'cython-generation.stderr.txt'
    if any(p.exists()for p in(output,result_path,launch,envelope,stdout,stderr)):
        raise ValueError('YEAR-V5 generation refuses overwrite')
    interpreter=dict(executable=sys.executable,version=sys.version,
        implementation=sys.implementation.name,cache_tag=sys.implementation.cache_tag)
    config=dict(cython=str(cython),source=str(source),output=str(output),report=str(result_path),
        version=backend.legacy.CYTHON_VERSION,module=backend.MODULE,
        directives=dict(backend.DIRECTIVES),source_sha256=sha256(source.read_bytes()).hexdigest(),interpreter=interpreter,
        working_directory=str(Path.cwd().resolve()))
    encoded=canonical(config)
    if len(encoded)>65536:raise ValueError('YEAR-V5 finite generation control bytes')
    command=[sys.executable,'-B','-c',CYTHON_GENERATOR_V1,encoded.decode('utf8')]
    data=dict(format='YEAR_V5_ISOLATED_CYTHON_ENVELOPE_V1',status='FAIL',
        generator_sha256=sha256(CYTHON_GENERATOR_V1.encode('utf8')).hexdigest(),
        config=config,command=command,deadline_seconds=seconds,
        scope='BUILD_GENERATION_ONLY_SAME_PRIVATE_JOB_NO_MODEL_EVALUATION')
    with launch.open('xb')as f:f.write(canonical(data))
    started=time.perf_counter_ns()
    try:
        env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
        with stdout.open('xb')as out,stderr.open('xb')as err:
            process=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                timeout=seconds,env=env,cwd=config['working_directory'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        data['exit_code']=process.returncode
        if stdout.stat().st_size>2**20 or stderr.stat().st_size>2**20:
            raise ValueError('YEAR-V5 generation diagnostics exceeded declared one-MiB stream cap')
        if process.returncode:raise ValueError('YEAR-V5 isolated Cython generation failed')
        if not result_path.is_file()or result_path.stat().st_size>65536:
            raise ValueError('YEAR-V5 bounded generation result missing')
        raw=result_path.read_bytes();result=json.loads(raw)
        if canonical(result)!=raw:raise ValueError('YEAR-V5 canonical generation result')
        expected={'format','status','offline_guard','working_directory','interpreter','source_sha256','module','directives','cython_version',
            'cython_origin','num_errors','generated_bytes','generated_sha256','wall_ns','process_cpu_ns'}
        if type(result)is not dict or set(result)!=expected or result['format']!='YEAR_V5_ISOLATED_CYTHON_RESULT_V1' or result['status']!='PASS_GENERATION_ONLY':
            raise ValueError('YEAR-V5 exact generation result schema')
        if (result['offline_guard']!='SOCKET_AND_URLLIB_AUDIT_DENY_V1' or
                result['working_directory']!=config['working_directory'] or
                result['interpreter']!=interpreter or result['source_sha256']!=config['source_sha256'] or
                result['module']!=config['module'] or result['directives']!=config['directives'] or
                result['cython_version']!=config['version'] or
                not Path(result['cython_origin']).resolve().is_relative_to(cython) or
                type(result['num_errors'])is not int or result['num_errors']!=0):
            raise ValueError('YEAR-V5 generation authority mismatch')
        for name in('generated_bytes','wall_ns','process_cpu_ns'):
            if type(result[name])is not int or result[name]<0:raise ValueError('YEAR-V5 exact generation counter')
        generated=output.read_bytes()
        if (not generated or result['generated_bytes']!=len(generated)or
                result['generated_sha256']!=sha256(generated).hexdigest()or
                sha256(source.read_bytes()).hexdigest()!=config['source_sha256']):
            raise ValueError('YEAR-V5 generation raw/source bytes mismatch')
        data.update(status='PASS_GENERATION_CHILD_EXITED',result_sha256=sha256(raw).hexdigest(),
            generated_sha256=result['generated_sha256'])
        return result
    except BaseException:
        data['traceback']=traceback.format_exc();raise
    finally:
        data['observed_wall_ns']=time.perf_counter_ns()-started
        with envelope.open('xb')as f:f.write(canonical(data))


def cython_generation_phase(cython,source,output,evidence,seconds,*,isolated=False):
    """Explicit process selection; retain the legacy result/context in caller."""
    if type(isolated)is not bool:raise TypeError('YEAR-V5 exact isolated generation selection')
    if isolated:
        result=isolated_cython_generation(cython,source,output,evidence,seconds)
        return result['cython_version'],result
    sys.path.insert(0,str(cython));import Cython
    if Cython.__version__!=backend.legacy.CYTHON_VERSION or not Path(Cython.__file__).resolve().is_relative_to(cython):raise ValueError('B65 explicit pinned Cython package')
    from Cython.Compiler.Main import compile as compile_cython,CompilationOptions,default_options
    result=compile_cython(str(source),options=CompilationOptions(default_options,output_file=str(output),language_level=3,compiler_directives=dict(backend.DIRECTIVES)),full_module_name=backend.MODULE)
    if result.num_errors:raise ValueError('B65 Cython compile errors')
    return Cython.__version__,result


def binding(root,path):
    return dict(path=path.relative_to(root).as_posix(),bytes=path.stat().st_size,sha256=sha256(path.read_bytes()).hexdigest())

def headers():
    rows={}
    for name,key in(('Python.h','include'),('pyconfig.h','platinclude')):
        path=Path(sysconfig.get_path(key))/name
        if not path.is_file():path=Path(sysconfig.get_path('include'))/name
        if not path.is_file()or path.is_symlink():raise ValueError('B65 Python development headers unavailable: '+name)
        rows[name]=dict(path=str(path.resolve()),bytes=path.stat().st_size,sha256=sha256(path.read_bytes()).hexdigest())
    return rows

def compiler_command(compiler,generated,artifact,profile):
    include=Path(sysconfig.get_path('include'));plat=Path(sysconfig.get_path('platinclude'))
    if profile==backend.WINDOWS:
        return [str(compiler),*backend.WINDOWS_FLAGS,'-I',str(include),str(generated),str(Path(sys.base_prefix)/'libs/python314.lib'),'-o',str(artifact)]
    if profile==backend.WINDOWS_SERIAL:
        return [str(compiler),*backend.SERIAL_FLAGS,'-I',str(include),str(generated),
            str(Path(sys.base_prefix)/'libs/python314.lib'),'-femit-bin='+str(artifact)]
    if profile!=backend.LINUX:raise ValueError('B65 unsupported compiler profile')
    return [str(compiler),*backend.LINUX_FLAGS,'-I',str(include),'-I',str(plat),str(generated),'-o',str(artifact)]

def _version(command):
    p=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,timeout=10)
    if p.returncode or len(p.stdout)>65536 or len(p.stderr)>65536:raise ValueError('B65 bounded tool version refusal')
    return p.stdout.decode('utf8','strict').strip()

def admit_cython_tree(wheel,tree):
    """The explicit compiler package must match the frozen wheel, not its name."""
    import zipfile
    total=0
    with zipfile.ZipFile(wheel)as archive:
        if len(archive.infolist())>20000 or archive.testzip()is not None:raise ValueError('B65 Cython wheel CRC/member cap')
        for info in archive.infolist():
            if info.is_dir():continue
            parts=Path(info.filename).parts
            if Path(info.filename).is_absolute()or '..'in parts or '\\'in info.filename or ':'in info.filename:raise ValueError('B65 compiler wheel path')
            total+=info.file_size
            if info.file_size>64*2**20 or total>256*2**20:raise ValueError('B65 finite compiler package')
            path=tree/info.filename
            if path.is_symlink()or not path.is_file()or path.stat().st_size!=info.file_size or sha256(path.read_bytes()).digest()!=sha256(archive.read(info)).digest():raise ValueError('B65 explicit compiler package differs from wheel: '+info.filename)
    return dict(files=len(archive.infolist()),expanded_bytes=total,wheel_sha256=sha256(wheel.read_bytes()).hexdigest())

def serial_dependencies(compiler,evidence,label):
    """Hash actual build support, without bundling a compiler or trusting names."""
    metadata=[]
    def row(path):
        a=path.stat();raw=path.read_bytes();b=path.stat()
        metadata.append(dict(path=str(path),atime_before=a.st_atime_ns,atime_after=b.st_atime_ns,
            mtime_ns=b.st_mtime_ns,birthtime_ns=b.st_birthtime_ns))
        return dict(bytes=len(raw),sha256=sha256(raw).hexdigest())
    roots=dict(python_headers=Path(sysconfig.get_path('include')),compiler_support=compiler.parent/'lib')
    result=dict(format='B67_SERIAL_BUILD_DEPENDENCIES_V1',trees={})
    for name,directory in roots.items():
        files={}
        for path in sorted(directory.rglob('*')):
            if path.is_symlink():raise ValueError('B67 build support symlink refused')
            if path.is_file():files[path.relative_to(directory).as_posix()]=row(path)
        if not 1<=len(files)<=32768:raise ValueError('B67 finite actual build support closure')
        result['trees'][name]=dict(root=str(directory),files=files)
    result['import_library']=dict(path=str(Path(sys.base_prefix)/'libs/python314.lib'),
        **row(Path(sys.base_prefix)/'libs/python314.lib'))
    result['runtime_dll']=dict(path=str(Path(sys.base_prefix)/'python314.dll'),
        **row(Path(sys.base_prefix)/'python314.dll'))
    raw=canonical(result)
    if len(raw)>8*2**20:raise ValueError('B67 build support manifest byte cap')
    with (evidence/(label+'-support-access.json')).open('xb')as f:f.write(canonical(metadata))
    return raw

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',required=True,type=Path);parser.add_argument('--cython',required=True,type=Path)
    parser.add_argument('--cython-wheel',required=True,type=Path);parser.add_argument('--evidence',required=True,type=Path)
    parser.add_argument('--compiler-seconds',type=int,default=180)
    parser.add_argument('--serial-zig',action='store_true')
    parser.add_argument('--global-cache-seed',type=Path)
    parser.add_argument('--isolate-cython',action='store_true')
    parser.add_argument('--generation-seconds',type=int,default=180)
    args=parser.parse_args(argv);root=Path(__file__).resolve().parents[2];here=Path(__file__).resolve().parent
    runtime=runtime_binding();profile=backend.profile_for(runtime)
    if args.serial_zig:
        if profile!=backend.WINDOWS:raise ValueError('B67 serial Zig recipe is Windows-only')
        profile=backend.WINDOWS_SERIAL
    elif args.global_cache_seed is not None:raise ValueError('B67 cache seed requires explicit serial recipe')
    if sysconfig.get_config_var('Py_GIL_DISABLED'):raise ValueError('B65 normal GIL build only')
    if not 1<=args.compiler_seconds<=240:raise ValueError('B65 finite compiler allowance')
    if not 1<=args.generation_seconds<=240:raise ValueError('YEAR-V5 finite generation allowance')
    generated=here/'lifecycle_typed65.c';artifact=here/('_lifecycle_typed65'+runtime['ext_suffix']);receipt=here/'lifecycle_typed65_build_receipt.json'
    if any(p.exists()for p in(generated,artifact,receipt,args.evidence)):raise ValueError('B65 build refuses overwrite; use fresh copy')
    compiler=args.compiler.resolve(strict=True);cython=args.cython.resolve(strict=True);wheel=args.cython_wheel.resolve(strict=True)
    wheel_pin=backend.legacy.CYTHON_WHEEL_SHA256 if profile in(backend.WINDOWS,backend.WINDOWS_SERIAL) else backend.LINUX_CYTHON_WHEEL_SHA256
    if sha256(wheel.read_bytes()).hexdigest()!=wheel_pin:raise ValueError('B65 pinned target Cython wheel bytes')
    compiler_package=admit_cython_tree(wheel,cython)
    executable_sha=sha256(compiler.read_bytes()).hexdigest()
    if profile in(backend.WINDOWS,backend.WINDOWS_SERIAL):
        if executable_sha!=backend.legacy.ZIG_EXECUTABLE_SHA256:raise ValueError('B65 pinned Zig executable')
        version=_version([str(compiler),'version'])
        if version!=backend.legacy.ZIG_VERSION:raise ValueError('B65 actual Zig version')
        tool=dict(name='Zig build-lib serial'if args.serial_zig else'Zig cc',version=version,executable_sha256=executable_sha,
            flags=list(backend.SERIAL_FLAGS if args.serial_zig else backend.WINDOWS_FLAGS),linker='Zig bundled linker')
    else:
        version=_version([str(compiler),'-dumpfullversion']);linker=_version([str(compiler),'-print-prog-name=ld'])
        ld=Path(linker)
        if not ld.is_absolute():
            import shutil
            found=shutil.which(linker)
            if found is None:raise ValueError('B65 actual Linux linker unavailable')
            ld=Path(found)
        ld=ld.resolve(strict=True)
        tool=dict(name='GCC',version=version,executable_sha256=executable_sha,flags=list(backend.LINUX_FLAGS),
            linker=str(ld)+' SHA256='+sha256(ld.read_bytes()).hexdigest()+' VERSION='+_version([str(ld),'--version']).splitlines()[0])
    args.evidence.mkdir(parents=True)
    dependencies=None
    if args.serial_zig:
        dependencies=serial_dependencies(compiler,args.evidence,'before')
        with (root/backend.DEPENDENCIES_PATH).open('xb')as f:f.write(dependencies)
    source=binding(root,here/'lifecycle_typed.pyx')
    support_names=backend.SERIAL_SUPPORT_PATHS if args.serial_zig else backend.SUPPORT_PATHS
    support={n:binding(root,root/n)for n in support_names};header=headers()
    # Literal include closure, no unbound transitive includes or executable source wrappers.
    expected={'lifecycle_typed.pyx':['lifecycle_typed_world.pxi','lifecycle_typed_quiet.pxi','lifecycle_exact_guards.pxi'],
              'lifecycle_typed_world.pxi':['lifecycle_typed_world65.pxi'],'lifecycle_typed_quiet.pxi':[], 'lifecycle_typed_world65.pxi':[],'lifecycle_exact_guards.pxi':[]}
    import re
    for name,wanted in expected.items():
        actual=re.findall(r'^include "([^"\n]+)"\s*$',(here/name).read_text('utf8'),re.M)
        if actual!=wanted:raise ValueError('B65 bound literal include closure: '+name)
    report=dict(format='B67_SERIAL_NATIVE_BUILD_ATTEMPT_V1'if args.serial_zig else'B66_NATIVE_BUILD_ATTEMPT_V2',status='FAIL',runtime=runtime,profile=profile,
        source=source,support=support,headers=header,toolchain=tool,compiler_package=compiler_package,model_evaluations=0,started_ns=time.perf_counter_ns())
    try:
        raw_dir=args.evidence/'raw-generated';raw_dir.mkdir()
        raw_generated=raw_dir/'lifecycle_typed65.c'
        cython_version,result=cython_generation_phase(cython,here/'lifecycle_typed.pyx',raw_generated,
            args.evidence,args.generation_seconds,isolated=args.isolate_cython)
        if args.isolate_cython:
            report['cython_generation']=dict(method='YEAR_V5_ISOLATED_CYTHON_BUILD_PHASE_V1',
                generator_sha256=sha256(CYTHON_GENERATOR_V1.encode('utf8')).hexdigest(),
                result=binding(args.evidence,args.evidence/'CYTHON-GENERATION-CHILD.json'),
                envelope=binding(args.evidence,args.evidence/'CYTHON-GENERATION-ENVELOPE.json'))
        normalized,treatment=normalize_generated_c(raw_generated.read_bytes())
        treatment.update(transform_source=support[backend.TREATMENT_PATH],raw_artifact='raw-generated/lifecycle_typed65.c')
        # Raw C remains immutable outside source; only the proved result enters
        # the compiler and source membership. No old receipt/binary is reused.
        with (args.evidence/'GENERATED-C-TREATMENT.json').open('xb')as f:f.write(canonical(treatment))
        with generated.open('xb')as f:f.write(normalized)
        report['generated_c_treatment']=treatment
        command=compiler_command(compiler,generated,artifact,profile);report['command']=command
        env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
        for key in('ZIG_GLOBAL_CACHE_DIR','ZIG_LOCAL_CACHE_DIR','TEMP','TMP'):
            d=args.evidence/key;d.mkdir();env[key]=str(d)
            if key=='ZIG_GLOBAL_CACHE_DIR' and args.global_cache_seed is not None:
                import shutil
                before_cache={p.relative_to(args.global_cache_seed).as_posix():sha256(p.read_bytes()).hexdigest()
                    for p in args.global_cache_seed.rglob('*')if p.is_file()}
                shutil.copytree(args.global_cache_seed,d,dirs_exist_ok=True)
                copied={p.relative_to(d).as_posix():sha256(p.read_bytes()).hexdigest()for p in d.rglob('*')if p.is_file()}
                if copied!=before_cache:raise ValueError('B67 owned cache copy drift')
                report['cache_seed']=dict(path=str(args.global_cache_seed),files=before_cache,
                    scope='COPIED_TASK_OWNED_COMPILER_CACHE_NOT_SCIENTIFIC_AUTHORITY')
        with (args.evidence/'PRECOMPILE.json').open('xb')as f:f.write(canonical(report))
        with (args.evidence/'compiler.stdout.txt').open('xb')as out,(args.evidence/'compiler.stderr.txt').open('xb')as err:
            process=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=out,stderr=err,timeout=args.compiler_seconds,env=env,cwd=args.evidence,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        report['compiler_exit']=process.returncode
        if process.returncode:raise ValueError('B65 compiler failed')
        if args.serial_zig and serial_dependencies(compiler,args.evidence,'after')!=dependencies:
            raise ValueError('B67 actual compiler/header/library support drift')
        if (sha256(raw_generated.read_bytes()).hexdigest()!=treatment['raw_sha256']or
                sha256(generated.read_bytes()).hexdigest()!=treatment['normalized_sha256']):
            raise ValueError('B66 raw/treated generated-C drift during compilation')
        for name in ('lifecycle_typed65.lib','_lifecycle_typed65.cp314-win_amd64.pdb'):
            temporary=here/name
            if temporary.exists():temporary.rename(args.evidence/name)
        if source!=binding(root,here/'lifecycle_typed.pyx')or support!={n:binding(root,root/n)for n in support}or header!=headers():raise ValueError('B65 build input drift')
        importlib.invalidate_caches();module=importlib.import_module(backend.MODULE)
        capability=json.loads(canonical(module.typed_capability()))
        data=dict(format=backend.SERIAL_BUILD_FORMAT if args.serial_zig else backend.TREATED_BUILD_FORMAT,execution_domain=backend.METHOD,profile=profile,artifact=binding(root,artifact),runtime=runtime,
            engine_source=source,generated_c=binding(root,generated),support_sources=support,compiler=tool,headers=header,command=command,
            cython=dict(version=cython_version,wheel_sha256=sha256(wheel.read_bytes()).hexdigest(),directives=dict(backend.DIRECTIVES)),
            capabilities=capability,capability_sha256=sha256(canonical(capability)).hexdigest(),generated_c_treatment=treatment)
        data=backend.admit_build_data(data);backend.admit_typed_build(data,source=root)
        counts=backend.admit_native_counts(module.native_entry_counts(),data)
        if counts['total']!=0:raise ValueError('B65 build/import entered numerical owners')
        with receipt.open('xb')as f:f.write(canonical(data));f.flush();os.fsync(f.fileno())
        report.update(status='PASS_BUILD_LOAD_ONLY',receipt=data,initial_counts=counts,qualification='NOT_RUN')
        return 0
    except BaseException:
        report['traceback']=traceback.format_exc();return 1
    finally:
        report['ended_ns']=time.perf_counter_ns()
        with (args.evidence/'BUILD-RESULT.json').open('xb')as f:f.write(canonical(report))
        print(json.dumps(dict(status=report['status'],evidence=str(args.evidence))))
if __name__=='__main__':raise SystemExit(main())
