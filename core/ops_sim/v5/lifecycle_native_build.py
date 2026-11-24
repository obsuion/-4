"""Explicit local B63 build; no automatic download, install or dispatch.

Run in an already bounded private Job. Tool paths are supplied by the caller.
Generated C is portable source; the ABI-specific artifact is not portable.
"""
from pathlib import Path
from hashlib import sha256
import argparse, importlib.util, json, os, platform, subprocess, sys, sysconfig, time, traceback

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')
def digest(p):return sha256(Path(p).read_bytes()).hexdigest()
def main(argv=None):
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--zig',type=Path,required=True);a.add_argument('--cython',type=Path,required=True)
    a.add_argument('--evidence',type=Path,required=True)
    a.add_argument('--compiler-seconds',type=int,default=160)
    args=a.parse_args(argv)
    if not 1<=args.compiler_seconds<=160:raise ValueError('B63 bounded compiler deadline 1..160 seconds')
    evidence=args.evidence.absolute();evidence.mkdir(exist_ok=False,parents=True)
    here=Path(__file__).resolve().parent;source=here/'lifecycle_native.pyx';generated=here/'lifecycle_native.c'
    artifact=here/('_lifecycle_native'+sysconfig.get_config_var('EXT_SUFFIX'))
    if artifact.exists() or generated.exists():raise ValueError('B63 build refuses overwrite; preserve previous attempt')
    report=dict(format='B63_LOCAL_NATIVE_BUILD_V1',status='FAIL',started_ns=time.perf_counter_ns(),source_sha256=digest(source),compiler_deadline_seconds=args.compiler_seconds)
    try:
        sys.path.insert(0,str(args.cython.resolve(strict=True)))
        from Cython.Compiler.Main import compile as cycompile, CompilationOptions, default_options
        import Cython
        options=CompilationOptions(default_options,output_file=str(generated),language_level=3,
            compiler_directives=dict(infer_types=False,annotation_typing=False,binding=True,
                                     cdivision=False,overflowcheck=True))
        result=cycompile(str(source),options=options,full_module_name='ops_sim.v5._lifecycle_native')
        if result.num_errors:raise ValueError('B63 Cython generation errors: '+str(result.num_errors))
        report['cython_version']=Cython.__version__;report['generated_c_sha256']=digest(generated)
        pyroot=Path(sys.base_prefix);flags=['cc','-shared','-target','x86_64-windows-gnu','-O2',
                '-fno-fast-math','-ffp-contract=off','-fno-associative-math','-DPy_NO_LINK_LIB']
        command=[str(args.zig.resolve(strict=True)),*flags,'-I',str(pyroot/'include'),str(generated),
                 str(pyroot/'libs/python314.lib'),'-o',str(artifact)]
        report['command']=command
        env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
        for name in ('ZIG_GLOBAL_CACHE_DIR','ZIG_LOCAL_CACHE_DIR','TEMP','TMP'):
            d=evidence/name;d.mkdir();env[name]=str(d)
        (evidence/'PRECOMPILE.json').write_bytes(canonical(report))
        start=time.perf_counter_ns()
        with (evidence/'compiler.stdout.txt').open('xb') as out,(evidence/'compiler.stderr.txt').open('xb') as err:
            proc=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=out,stderr=err,env=env,
                                cwd=evidence,timeout=args.compiler_seconds,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        report['compiler_seconds']=(time.perf_counter_ns()-start)/1e9;report['exit_code']=proc.returncode
        auxiliary=here/'lifecycle_native.lib'
        if auxiliary.exists():
            report['import_library_sha256']=digest(auxiliary);auxiliary.rename(evidence/'lifecycle_native.lib')
        symbols=artifact.with_suffix('.pdb')
        if symbols.exists():
            report['debug_symbols_sha256']=digest(symbols);symbols.rename(evidence/symbols.name)
        if proc.returncode:raise ValueError('B63 compiler exit '+str(proc.returncode))
        if source.exists() and digest(source)!=report['source_sha256']:raise ValueError('B63 source drift during build')
        sys.path.insert(0,str(here.parents[1]))
        module=__import__('ops_sim.v5._lifecycle_native',fromlist=['native_capability'])
        capability=module.native_capability()
        if (capability.get('method')!='B63_PREPARED_NATIVE_V1' or capability.get('ordered_python_object_arithmetic')is not True or
                capability.get('canary')is not True or not all(x is True for x in capability.get('capability_screen',{}).values())):
            raise ValueError('B63 native capability refusal')
        monitor=module.native_entry_counts()
        if (monitor.get('method')!='B63_COMPILED_NUMERICAL_ENTRY_MONITOR_V1' or
                monitor.get('total')!=0 or monitor.get('exhausted')is not False or
                any(type(n)is not int or n!=0 for n in monitor.get('counts',{}).values()) or
                set(monitor.get('counts',{}))!=set(capability.get('entry_monitor',{}).get('names',()))):
            raise ValueError('B63 fresh build import performed a numerical owner entry')
        report['native_entry_monitor_initial']=monitor
        receipt=dict(format='B63_NATIVE_BUILD_RECEIPT_V1',
            artifact=dict(path=artifact.relative_to(here.parents[1]).as_posix(),sha256=digest(artifact),bytes=artifact.stat().st_size),
            runtime=dict(implementation=sys.implementation.name,python=sys.version,cache_tag=sys.implementation.cache_tag,
                         ext_suffix=sysconfig.get_config_var('EXT_SUFFIX'),platform=sys.platform,machine=platform.machine()),
            engine_source_sha256=digest(source),compiler=dict(name='Zig cc',version='0.15.2',flags=flags),
            capabilities=capability,capability_sha256=sha256(canonical(capability)).hexdigest())
        with (here/'lifecycle_native_build_receipt.json').open('xb') as f:f.write(canonical(receipt))
        report.update(status='PASS_BUILD_IMPORT_CAPABILITY_ONLY',receipt=receipt,model_evaluations=0)
        return 0
    except BaseException as e:
        report.update(error=repr(e),traceback=traceback.format_exc());return 1
    finally:
        report['ended_ns']=time.perf_counter_ns();(evidence/'BUILD-RESULT.json').write_bytes(canonical(report))
        print(json.dumps(dict(status=report['status'],evidence=str(evidence)),ensure_ascii=False),flush=True)

if __name__=='__main__':raise SystemExit(main())
