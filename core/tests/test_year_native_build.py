"""Nonnumerical generation-process protocol, with a fake subprocess boundary.

No compiler, Cython import or real subprocess is invoked by these tests.
"""
import ast
import builtins
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace, ModuleType

import pytest

from ops_sim.v5 import lifecycle_typed_platform_build as build


@pytest.fixture
def files(tmp_path,monkeypatch):
    # Ensure the exact rejection of a preloaded compiler can be tested without
    # depending on a pytest plugin's optional imports; restoration is automatic.
    for key in list(build.sys.modules):
        if key=='Cython'or key.startswith('Cython.'):
            monkeypatch.delitem(build.sys.modules,key)
    tree=tmp_path/'cython';tree.mkdir()
    source=tmp_path/'lifecycle_typed.pyx';source.write_bytes(b'# fake bound source\n')
    out=tmp_path/'raw-generated';out.mkdir()
    return tree,source,out/'lifecycle_typed65.c',tmp_path


def fake_result(config,raw):
    return dict(format='YEAR_V5_ISOLATED_CYTHON_RESULT_V1',status='PASS_GENERATION_ONLY',
        working_directory=config['working_directory'],
        offline_guard='SOCKET_AND_URLLIB_AUDIT_DENY_V1',interpreter=config['interpreter'],
        source_sha256=config['source_sha256'],module=config['module'],directives=config['directives'],
        cython_version=config['version'],cython_origin=str(Path(config['cython'])/'Cython/__init__.py'),
        num_errors=0,generated_bytes=len(raw),generated_sha256=sha256(raw).hexdigest(),
        wall_ns=1000,process_cpu_ns=0)


def fake_process(monkeypatch,*,change=None,exit_code=0,error=None):
    calls=[]
    def run(command,**kwargs):
        calls.append((command,kwargs))
        if error is not None:raise error
        config=json.loads(command[-1]);raw=b'/* same fake raw generated C */\n'
        Path(config['output']).write_bytes(raw)
        result=fake_result(config,raw)
        if change is not None:change(config,result)
        Path(config['report']).write_bytes(build.canonical(result))
        return SimpleNamespace(returncode=exit_code)
    monkeypatch.setattr(build.subprocess,'run',run)
    return calls


def test_isolated_generation_binds_exact_command_and_completed_child(files,monkeypatch):
    calls=fake_process(monkeypatch)
    result=build.isolated_cython_generation(*files,17)
    assert len(calls)==1
    command,kwargs=calls[0];config=json.loads(command[-1])
    assert command[:3]==[build.sys.executable,'-B','-c']
    assert command[3]==build.CYTHON_GENERATOR_V1
    assert config['module']==build.backend.MODULE
    assert config['directives']==dict(build.backend.DIRECTIVES)
    assert config['version']==build.backend.legacy.CYTHON_VERSION
    assert config['source']==str(files[1].resolve())
    assert config['output']==str(files[2])
    assert kwargs['timeout']==17 and kwargs['cwd']==str(Path.cwd().resolve())
    assert kwargs['env']['PYTHONDONTWRITEBYTECODE']=='1'
    assert kwargs['env']['PYTHONUTF8']=='1'
    assert result['process_cpu_ns']==0
    launch=json.loads((files[3]/'CYTHON-GENERATION-LAUNCH.json').read_bytes())
    done=json.loads((files[3]/'CYTHON-GENERATION-ENVELOPE.json').read_bytes())
    assert launch['status']=='FAIL' # prospective, immutable declaration
    assert done['status']=='PASS_GENERATION_CHILD_EXITED' and done['exit_code']==0
    assert done['generated_sha256']==sha256(files[2].read_bytes()).hexdigest()
    assert done['generator_sha256']==sha256(build.CYTHON_GENERATOR_V1.encode('utf8')).hexdigest()
    assert not any(n=='Cython'or n.startswith('Cython.')for n in build.sys.modules)


@pytest.mark.parametrize('seconds',[True,0,-1,241,1.,'17'])
def test_invalid_generation_allowance_has_no_launch_or_artifacts(files,monkeypatch,seconds):
    calls=fake_process(monkeypatch)
    with pytest.raises(ValueError,match='allowance'):
        build.isolated_cython_generation(*files,seconds)
    assert calls==[] and not(files[3]/'CYTHON-GENERATION-LAUNCH.json').exists()


def test_preloaded_cython_refused_before_any_child(files,monkeypatch):
    calls=fake_process(monkeypatch)
    monkeypatch.setitem(build.sys.modules,'Cython',SimpleNamespace())
    with pytest.raises(ValueError,match='already imported'):
        build.isolated_cython_generation(*files,17)
    assert calls==[]


def test_generation_refuses_overwriting_any_original_output(files,monkeypatch):
    calls=fake_process(monkeypatch);files[2].write_bytes(b'KEEP')
    with pytest.raises(ValueError,match='overwrite'):
        build.isolated_cython_generation(*files,17)
    assert calls==[] and files[2].read_bytes()==b'KEEP'


@pytest.mark.parametrize('change',[
    'runtime','module','directives','source_binding','version','foreign_origin',
    'generated_hash','generated_bytes','source_drift','boolean_counter','offline_guard','extra_field',
])
def test_generation_result_drift_is_retained_and_refused(files,monkeypatch,change):
    def alter(config,result):
        if change=='runtime':result['interpreter']={}
        elif change=='module':result['module']='foreign'
        elif change=='directives':result['directives']={}
        elif change=='source_binding':result['source_sha256']='0'*64
        elif change=='version':result['cython_version']='foreign'
        elif change=='foreign_origin':result['cython_origin']=str(files[3]/'foreign/__init__.py')
        elif change=='generated_hash':result['generated_sha256']='0'*64
        elif change=='generated_bytes':result['generated_bytes']+=1
        elif change=='source_drift':files[1].write_bytes(b'altered source')
        elif change=='boolean_counter':result['process_cpu_ns']=True
        elif change=='offline_guard':result['offline_guard']='NONE'
        else:result['unexpected']=0
    calls=fake_process(monkeypatch,change=alter)
    with pytest.raises((TypeError,ValueError)):
        build.isolated_cython_generation(*files,17)
    assert len(calls)==1
    assert(files[3]/'CYTHON-GENERATION-CHILD.json').is_file()
    envelope=json.loads((files[3]/'CYTHON-GENERATION-ENVELOPE.json').read_bytes())
    assert envelope['status']=='FAIL' and 'traceback'in envelope


@pytest.mark.parametrize('error',[None,TimeoutError('injected OS failure')])
def test_failed_child_keeps_envelope_and_no_retry(files,monkeypatch,error):
    calls=fake_process(monkeypatch,exit_code=5,error=error)
    with pytest.raises((ValueError,TimeoutError)):
        build.isolated_cython_generation(*files,17)
    assert len(calls)==1
    envelope=json.loads((files[3]/'CYTHON-GENERATION-ENVELOPE.json').read_bytes())
    assert envelope['status']=='FAIL' and 'traceback'in envelope
    assert(files[3]/'cython-generation.stderr.txt').is_file()
    if error is None:assert envelope['exit_code']==5


def test_generation_deadline_error_is_original_and_recorded(files,monkeypatch):
    original=build.subprocess.TimeoutExpired(['fake'],17)
    calls=fake_process(monkeypatch,error=original)
    with pytest.raises(build.subprocess.TimeoutExpired)as caught:
        build.isolated_cython_generation(*files,17)
    assert caught.value is original and len(calls)==1
    assert 'TimeoutExpired'in json.loads((files[3]/'CYTHON-GENERATION-ENVELOPE.json').read_bytes())['traceback']


def test_literal_generator_is_parseable_and_network_guard_precedes_compiler_import():
    tree=ast.parse(build.CYTHON_GENERATOR_V1)
    imports=[n for n in ast.walk(tree)if isinstance(n,ast.Import)and any(a.name=='Cython'for a in n.names)]
    hooks=[n for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr=='addaudithook']
    assert len(imports)==len(hooks)==1 and hooks[0].lineno<imports[0].lineno
    assert "event.startswith('socket.')"in build.CYTHON_GENERATOR_V1
    assert "event=='urllib.Request'"in build.CYTHON_GENERATOR_V1
    assert 'import Cython'not in build.isolated_cython_generation.__code__.co_names


def test_explicit_isolated_dispatch_never_imports_parent_compiler(files,monkeypatch):
    calls=[];result={'cython_version':'TEST_VERSION'}
    def isolated(*args):calls.append(args);return result
    monkeypatch.setattr(build,'isolated_cython_generation',isolated)
    version,owned=build.cython_generation_phase(*files,17,isolated=True)
    assert version=='TEST_VERSION' and owned is result
    assert calls==[(*files,17)]
    assert not any(n=='Cython'or n.startswith('Cython.')for n in build.sys.modules)


def test_default_dispatch_retains_exact_legacy_arguments_and_result(files,monkeypatch):
    tree,source,output,evidence=files;calls=[];owned=SimpleNamespace(num_errors=0)
    cython=ModuleType('Cython');cython.__file__=str(tree/'Cython/__init__.py')
    cython.__path__=[str(tree/'Cython')];cython.__version__=build.backend.legacy.CYTHON_VERSION
    compiler=ModuleType('Cython.Compiler');compiler.__path__=[str(tree/'Cython/Compiler')]
    main=ModuleType('Cython.Compiler.Main');default=object();main.default_options=default
    def options(base,**kw):
        assert base is default;return kw
    def compile(source,**kw):calls.append((source,kw));return owned
    main.CompilationOptions=options;main.compile=compile
    compiler.Main=main;cython.Compiler=compiler
    for name,value in [('Cython',cython),('Cython.Compiler',compiler),('Cython.Compiler.Main',main)]:
        monkeypatch.setitem(build.sys.modules,name,value)
    monkeypatch.setattr(build.sys,'path',list(build.sys.path))
    def unexpected(*args):raise AssertionError('legacy path must not launch generation child')
    monkeypatch.setattr(build,'isolated_cython_generation',unexpected)
    version,result=build.cython_generation_phase(*files,17)
    assert version==cython.__version__ and result is owned
    assert calls==[(str(source),dict(options=dict(output_file=str(output),language_level=3,
        compiler_directives=dict(build.backend.DIRECTIVES)),full_module_name=build.backend.MODULE))]
    assert build.sys.path[0]==str(tree)
    assert not(evidence/'CYTHON-GENERATION-LAUNCH.json').exists()


@pytest.mark.parametrize('selection',[1,'true',None])
def test_generation_selection_is_explicit_bool(files,selection):
    with pytest.raises(TypeError,match='selection'):
        build.cython_generation_phase(*files,17,isolated=selection)


def test_local_platform_cache_is_primed_before_unchanged_offline_guard():
    """Execute only the literal pre-Cython prefix with synthetic OS metadata.

    No real hook is installed in pytest, no child or Cython is run, and no
    network or local hostname API is invoked. The fake uname cache models
    the actual cached versus uncached path which failed in build three.
    """
    hooks=[];events=[];cache=[];imports=[]
    def hostname():
        events.append('hostname')
        for hook in hooks:hook('socket.gethostname',())
        return 'SYNTHETIC_LOCAL_NODE'
    def uname():
        events.append('uname')
        if not cache:cache.append(SimpleNamespace(node=hostname()))
        return cache[0]
    def add_hook(hook):
        events.append('install_offline_hook');hooks.append(hook)
    fake_sys=SimpleNamespace(addaudithook=add_hook)
    fake_platform=SimpleNamespace(uname=uname)
    original_import=builtins.__import__
    def local_import(name,*args,**kwargs):
        imports.append(name)
        if name=='sys':return fake_sys
        if name=='platform':return fake_platform
        assert name!='Cython'
        return original_import(name,*args,**kwargs)
    tree=ast.parse(build.CYTHON_GENERATOR_V1)
    cutoff=next(i for i,node in enumerate(tree.body)if isinstance(node,ast.Assign)
        and any(isinstance(t,ast.Name)and t.id=='c'for t in node.targets))
    prefix=ast.fix_missing_locations(ast.Module(body=tree.body[:cutoff],type_ignores=[]))
    namespace={'__builtins__':dict(vars(builtins),__import__=local_import)}
    exec(compile(prefix,'<synthetic isolated generation prefix>','exec'),namespace)
    assert events==['uname','hostname','install_offline_hook']
    assert len(hooks)==1 and 'Cython'not in imports
    first=uname();assert first is uname() and first.node=='SYNTHETIC_LOCAL_NODE'
    assert events.count('hostname')==1
    for event in('socket.gethostname','socket.connect','socket.getaddrinfo','urllib.Request'):
        with pytest.raises(RuntimeError,match='network disabled'):
            hooks[0](event,())
    assert hooks[0]('ordinary.nonnetwork.event',())is None
