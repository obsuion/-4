"""Explicit treated-C legacy-module build; run only in an owned build Job.

No download/install/automatic retry. The parent freezes the verified historical
Zig/Cython package bytes before this command. Every attempt uses a fresh source
copy and evidence directory; generated outputs are never overwritten.
"""
from hashlib import sha256
from pathlib import Path
import argparse
import importlib
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import traceback

from . import lifecycle_typed_backend as backend
from .generated_c_treatment import normalize_generated_c
BUILD_SUPPORT_PATHS=backend.TREATED_SUPPORT_PATHS


def canonical(value):return backend.canonical(value)
def digest(path):return sha256(Path(path).read_bytes()).hexdigest()


def file_binding(root,path):
    return dict(path=path.relative_to(root).as_posix(),sha256=digest(path),bytes=path.stat().st_size)


def output_paths(here,runtime):
    return (here/'lifecycle_typed.c',here/('_lifecycle_typed'+runtime['ext_suffix']),
        here/'lifecycle_typed_build_receipt.json')


def compiler_command(zig,generated,artifact,python_root):
    return [str(zig),*backend.FLAGS,'-I',str(python_root/'include'),str(generated),
        str(python_root/'libs/python314.lib'),'-o',str(artifact)]


def admit_cython_tree(wheel,tree):
    """Verify the actual explicit compiler tree against the pinned wheel."""
    import zipfile
    if digest(wheel)!=backend.CYTHON_WHEEL_SHA256:raise ValueError('B66 pinned legacy-module Cython wheel bytes')
    total=0
    with zipfile.ZipFile(wheel)as archive:
        if len(archive.infolist())>20000 or archive.testzip()is not None:raise ValueError('B66 bounded Cython wheel CRC')
        for info in archive.infolist():
            if info.is_dir():continue
            if Path(info.filename).is_absolute()or '..'in Path(info.filename).parts or '\\'in info.filename or ':'in info.filename:
                raise ValueError('B66 Cython wheel member path')
            total+=info.file_size
            if info.file_size>64*2**20 or total>256*2**20:raise ValueError('B66 bounded Cython wheel expansion')
            path=tree/info.filename
            if path.is_symlink()or not path.is_file()or path.stat().st_size!=info.file_size or digest(path)!=sha256(archive.read(info)).hexdigest():
                raise ValueError('B66 explicit compiler package differs from pinned wheel: '+info.filename)
    return dict(files=len(archive.infolist()),expanded_bytes=total,wheel_sha256=digest(wheel))


def admit_include_sources(here):
    """Bind the literal, ordered Cython include closure before any output.

    The two admitted includes have no transitive includes. All three raw
    inputs are separately included in the immutable build receipt bindings.
    """
    expected=tuple(Path(name).name for name in backend.INCLUDE_PATHS)
    def includes(path):
        result=[]
        for line in path.read_text(encoding='utf8').splitlines():
            stripped=line.strip()
            if re.match(r'include\b',stripped):
                match=re.fullmatch(r'''include\s+['"]([^'"\r\n]+)['"]''',stripped)
                if match is None:raise ValueError('B64 exact literal Cython include declaration')
                result.append(match.group(1))
        return tuple(result)
    if includes(here/'lifecycle_typed.pyx')!=expected:
        raise ValueError('B64 exact ordered world/quiet Cython includes')
    for name in expected:
        wanted=('lifecycle_typed_world65.pxi',)if name=='lifecycle_typed_world.pxi'else()
        if includes(here/name)!=wanted:raise ValueError('B64 unbound transitive Cython include')
    if includes(here/'lifecycle_typed_world65.pxi'):raise ValueError('B64 unbound secondary include')
    return expected


def admit_attempt(here,evidence,runtime,execution_domain,compiler_seconds):
    """Pure admission except read-only local metadata; creates no output."""
    backend._runtime(runtime)
    if type(compiler_seconds)is not int or not 1<=compiler_seconds<=160:
        raise ValueError('B64 bounded compiler deadline 1..160 seconds')
    if type(execution_domain)is not str or execution_domain not in (backend.FULL_DOMAIN,backend.SUPPORT_DOMAIN):
        raise ValueError('B64 declared typed build domain')
    paths=output_paths(here,runtime)
    if evidence.exists() or any(path.exists()for path in paths):
        raise ValueError('B64 typed build refuses overwrite; preserve previous attempt')
    if not (here/'lifecycle_typed.pyx').is_file():raise ValueError('B64 typed engine source missing')
    for path in BUILD_SUPPORT_PATHS:
        if not (here.parents[1]/path).is_file():raise ValueError('B64 typed support source missing: '+path)
    admit_include_sources(here)
    return paths


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True)
    parser.add_argument('--cython',type=Path,required=True)
    parser.add_argument('--cython-wheel',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--compiler-seconds',type=int,default=160)
    parser.add_argument('--execution-domain',choices=(backend.FULL_DOMAIN,backend.SUPPORT_DOMAIN),default=backend.FULL_DOMAIN)
    args=parser.parse_args(argv)
    from .lifecycle_backend import runtime_binding
    runtime=runtime_binding();here=Path(__file__).resolve().parent;root=here.parents[1]
    evidence=args.evidence.absolute()
    generated,artifact,receipt_path=admit_attempt(here,evidence,runtime,args.execution_domain,args.compiler_seconds)
    zig=args.zig.resolve(strict=True);cython_path=args.cython.resolve(strict=True)
    wheel=args.cython_wheel.resolve(strict=True)
    if digest(zig)!=backend.ZIG_EXECUTABLE_SHA256:raise ValueError('B64 pinned historical Zig executable bytes')
    compiler_package=admit_cython_tree(wheel,cython_path)
    # Pre-admit all immutable source bindings before Cython or a compiler starts.
    source=here/'lifecycle_typed.pyx';engine=file_binding(root,source)
    support={name:file_binding(root,root/name)for name in BUILD_SUPPORT_PATHS}
    evidence.mkdir(exist_ok=False,parents=True)
    report=dict(format='B66_LOCAL_LEGACY_TYPED_BUILD_V2',status='FAIL',started_ns=time.perf_counter_ns(),
        execution_domain=args.execution_domain,engine_source=engine,support_sources=support,
        engine_includes={name:support[name]for name in backend.INCLUDE_PATHS},
        compiler_deadline_seconds=args.compiler_seconds,compiler_flags=list(backend.FLAGS),
        model_evaluations=0,automatic_retry=False,compiler_package=compiler_package)
    try:
        sys.path.insert(0,str(cython_path))
        import Cython
        if Cython.__version__!=backend.CYTHON_VERSION or not Path(Cython.__file__).resolve().is_relative_to(cython_path):
            raise ValueError('B64 pinned explicit Cython package/version')
        from Cython.Compiler.Main import compile as cycompile,CompilationOptions,default_options
        raw_dir=evidence/'raw-generated';raw_dir.mkdir()
        raw_generated=raw_dir/'lifecycle_typed.c'
        options=CompilationOptions(default_options,output_file=str(raw_generated),language_level=3,
            compiler_directives=dict(backend.DIRECTIVES))
        result=cycompile(str(source),options=options,full_module_name=backend.MODULE)
        if result.num_errors:raise ValueError('B64 Cython generation errors: '+str(result.num_errors))
        normalized,treatment=normalize_generated_c(raw_generated.read_bytes())
        treatment.update(transform_source=support[backend.TREATMENT_PATH],raw_artifact='raw-generated/lifecycle_typed.c')
        with (evidence/'GENERATED-C-TREATMENT.json').open('xb')as stream:stream.write(canonical(treatment))
        with generated.open('xb')as stream:stream.write(normalized)
        report['generated_c_treatment']=treatment
        report['generated_c']=file_binding(root,generated)
        pyroot=Path(sys.base_prefix)
        command=compiler_command(zig,generated,artifact,pyroot)
        report['command']=command
        env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
        for name in ('ZIG_GLOBAL_CACHE_DIR','ZIG_LOCAL_CACHE_DIR','TEMP','TMP'):
            directory=evidence/name;directory.mkdir();env[name]=str(directory)
        with (evidence/'PRECOMPILE.json').open('xb')as stream:stream.write(canonical(report))
        start=time.perf_counter_ns()
        try:
            with (evidence/'compiler.stdout.txt').open('xb')as out,(evidence/'compiler.stderr.txt').open('xb')as err:
                process=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=out,stderr=err,env=env,cwd=evidence,
                    timeout=args.compiler_seconds,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        finally:report['compiler_seconds']=(time.perf_counter_ns()-start)/1e9
        report['exit_code']=process.returncode
        auxiliary=here/'lifecycle_typed.lib'
        if auxiliary.exists():
            report['import_library_sha256']=digest(auxiliary);auxiliary.rename(evidence/auxiliary.name)
        symbols=artifact.with_suffix('.pdb')
        if symbols.exists():
            report['debug_symbols_sha256']=digest(symbols);symbols.rename(evidence/symbols.name)
        if process.returncode:raise ValueError('B64 typed compiler exit '+str(process.returncode))
        if file_binding(root,source)!=engine or any(file_binding(root,root/name)!=value for name,value in support.items()):
            raise ValueError('B64 immutable typed build source drift')
        if file_binding(root,generated)!=report['generated_c']:raise ValueError('B64 generated C drift during compilation')
        if digest(raw_generated)!=treatment['raw_sha256']:raise ValueError('B66 raw generated-C drift during compilation')
        sys.path.insert(0,str(root))
        spec=importlib.util.find_spec(backend.MODULE)
        if spec is None or type(spec.loader)is not importlib.machinery.ExtensionFileLoader or Path(spec.origin).resolve()!=artifact.resolve():
            raise ValueError('B64 actual compiled typed import before capability')
        module=importlib.import_module(backend.MODULE)
        required=('prepare_static','service_port_substep','typed_capability','native_entry_counts')
        if args.execution_domain==backend.FULL_DOMAIN:required=(*required,*backend.FULL_QUIET_EXPORTS)
        report['actual_callable_types']={name:dict(type_module=type(getattr(module,name,None)).__module__,
            type_name=type(getattr(module,name,None)).__name__,
            type_flags=type(getattr(module,name,None)).__flags__,
            callable_module=getattr(getattr(module,name,None),'__module__',None),
            callable_name=getattr(getattr(module,name,None),'__name__',None))for name in required}
        capability=json.loads(canonical(module.typed_capability()))
        receipt=dict(format=backend.TREATED_BUILD_FORMAT,execution_domain=args.execution_domain,
            artifact=file_binding(root,artifact),runtime=runtime,engine_source=engine,
            generated_c=report['generated_c'],support_sources=support,
            compiler=dict(name='Zig cc',version=backend.ZIG_VERSION,flags=list(backend.FLAGS),
                executable_sha256=backend.ZIG_EXECUTABLE_SHA256,archive_sha256=backend.ZIG_ARCHIVE_SHA256),
            cython=dict(version=backend.CYTHON_VERSION,wheel_sha256=backend.CYTHON_WHEEL_SHA256,directives=dict(backend.DIRECTIVES)),
            capabilities=capability,capability_sha256=sha256(canonical(capability)).hexdigest(),
            generated_c_treatment=treatment)
        receipt=backend.admit_build_data(receipt)
        require_quiet=args.execution_domain==backend.FULL_DOMAIN
        backend.admit_typed_build(receipt,require_quiet=require_quiet,execution_domain=args.execution_domain,source=root)
        monitor=backend.admit_native_counts(module.native_entry_counts(),receipt)
        if monitor['total']!=0 or any(n!=0 for n in monitor['counts'].values()):
            raise ValueError('B64 fresh build import performed a numerical owner entry')
        report['native_entry_monitor_initial']=monitor
        with receipt_path.open('xb')as stream:stream.write(canonical(receipt))
        report.update(status='PASS_BUILD_IMPORT_CAPABILITY_ONLY',receipt=receipt,
            qualification='NO_MODEL_RUN_OR_H05_ACCEPTANCE')
        return 0
    except BaseException as error:
        report.update(error=repr(error),traceback=traceback.format_exc());return 1
    finally:
        report['ended_ns']=time.perf_counter_ns()
        with (evidence/'BUILD-RESULT.json').open('xb')as stream:stream.write(canonical(report))
        print(json.dumps(dict(status=report['status'],evidence=str(evidence)),ensure_ascii=False),flush=True)


if __name__=='__main__':raise SystemExit(main())
