"""Detached build/monitor DATA and pre-import refusal; no model or build runs."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import importlib.machinery

import pytest

from ops_sim.v5 import lifecycle_typed_backend as owner


def receipt(*,quiet=True):
    runtime=dict(implementation='cpython',python='3.14.7 METADATA_ONLY',cache_tag='cpython-314',
        ext_suffix='.cp314-win_amd64.pyd',platform='win32',machine='AMD64')
    def binding(path):return dict(path=path,sha256='a'*64,bytes=1)
    artifact=binding('ops_sim/v5/_lifecycle_typed'+runtime['ext_suffix'])
    capability=dict(method=owner.METHOD,arithmetic='ORDERED_TYPED_BINARY64_WITH_EXACT_INTEGER_BARRIERS_V1',
        typed_contiguous_numeric_state=True,full_coupled=True,python_model_callbacks=False,
        python_model_callbacks_scope=owner.CALLBACK_SCOPE,exact_integer_and_fraction=True,
        actual_math_fsum=True,direct_c_libm=False,changes_scientific_work=False,canary=True,
        limits=dict(nodes=64,links=256,branches=8,loads=7),
        capability_screen={name:True for name in owner.SCREEN_NAMES},
        entry_monitor=dict(method=owner.MONITOR_METHOD,limit=2**56,names=list(owner.ENTRY_NAMES)),
        module_basename=Path(artifact['path']).name,python_implementation=runtime['implementation'],
        python_cache_tag=runtime['cache_tag'],python_version=runtime['python'],platform=runtime['platform'],
        quiet_interval_callback_free=quiet,scope='REQUIRES_BOUND_BUILD_RUNTIME_SOURCE_AND_FULL_SCIENTIFIC_EQUALITY',speedup='UNPROVEN')
    return dict(format=owner.BUILD_FORMAT,execution_domain=owner.FULL_DOMAIN if quiet else owner.SUPPORT_DOMAIN,
        artifact=artifact,runtime=runtime,engine_source=binding(owner.ENGINE_PATH),generated_c=binding(owner.GENERATED_PATH),
        support_sources={path:binding(path)for path in owner.SUPPORT_PATHS},
        compiler=dict(name='Zig cc',version=owner.ZIG_VERSION,flags=list(owner.FLAGS),
            executable_sha256=owner.ZIG_EXECUTABLE_SHA256,archive_sha256=owner.ZIG_ARCHIVE_SHA256),
        cython=dict(version=owner.CYTHON_VERSION,wheel_sha256=owner.CYTHON_WHEEL_SHA256,directives=dict(owner.DIRECTIVES)),
        capabilities=capability,capability_sha256=sha256(owner.canonical(capability)).hexdigest())


def rehash(value):
    value['capability_sha256']=sha256(owner.canonical(value['capabilities'])).hexdigest()
    return value


def monitor(build):
    runtime=build['runtime']
    return dict(format=owner.MONITOR_FORMAT,method=owner.MONITOR_METHOD,limit=2**56,total=0,
        counts={name:0 for name in owner.ENTRY_NAMES},exhausted=False,gil_held=True,reset_available=False,
        python_implementation=runtime['implementation'],python_cache_tag=runtime['cache_tag'],
        python_version=runtime['python'],platform=runtime['platform'],module_basename=Path(build['artifact']['path']).name,
        source_binding=owner.SOURCE_SCOPE,scope=owner.MONITOR_SCOPE)


def test_detached_data_requires_no_file_runtime_or_extension_access(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('detached DATA performed activation or I/O')
    monkeypatch.setattr(Path,'read_bytes',forbidden)
    monkeypatch.setattr(owner.importlib,'import_module',forbidden)
    for quiet in (False,True):
        value=receipt(quiet=quiet);admitted=owner.admit_build_data(value)
        assert admitted==value and admitted is not value
        admitted['capabilities']['limits']['nodes']=0
        assert value['capabilities']['limits']['nodes']==64
        assert owner.admit_native_counts(monitor(value),value)['total']==0


@pytest.mark.parametrize('path,changed',[
    (('format',),'B63_NATIVE_BUILD_RECEIPT_V1'),
    (('runtime','cache_tag'),'cpython-313'),
    (('runtime','machine'),'ARM64'),
    (('runtime','ext_suffix'),'../malicious.pyd'),
    (('artifact','path'),'ops_sim/v5/_lifecycle_native.cp314-win_amd64.pyd'),
    (('artifact','bytes'),True),
    (('generated_c','sha256'),'g'*64),
    (('engine_source','path'),'ops_sim/v5/lifecycle_native.pyx'),
    (('compiler','flags'),list(owner.FLAGS)+['-ffast-math']),
    (('compiler','flags'),list(owner.FLAGS[:-2])+['-ffp-contract=fast','-DPy_NO_LINK_LIB']),
    (('compiler','version'),'0.16.0'),
    (('compiler','executable_sha256'),'b'*64),
    (('cython','version'),'3.2.5'),
    (('cython','directives','overflowcheck'),False),
    (('cython','directives','binding'),1),
    (('capabilities','typed_contiguous_numeric_state'),False),
    (('capabilities','python_model_callbacks'),True),
    (('capabilities','python_model_callbacks_scope'),'COUPLED_CUT_ONLY'),
    (('capabilities','direct_c_libm'),True),
    (('capabilities','actual_math_fsum'),False),
    (('capabilities','limits','nodes'),True),
    (('capabilities','limits','branches'),9),
    (('capabilities','capability_screen','independent_scratch'),False),
    (('capabilities','entry_monitor','limit'),2**56+1),
    (('capabilities','quiet_interval_callback_free'),1),
])
def test_exact_receipt_rejects_changed_recipe_abi_and_capability(path,changed):
    value=receipt();target=value
    for name in path[:-1]:target=target[name]
    target[path[-1]]=changed;rehash(value)
    with pytest.raises(ValueError):owner.admit_build_data(value)


@pytest.mark.parametrize('field',('format','execution_domain','generated_c','support_sources','compiler','cython','capabilities','capability_sha256'))
def test_missing_receipt_field_fails(field):
    value=receipt();del value[field]
    with pytest.raises(ValueError):owner.admit_build_data(value)


def test_old_build_and_extra_fields_are_not_silently_upgraded():
    value=receipt();value['engine_source_sha256']='a'*64
    with pytest.raises(ValueError,match='exact'):owner.admit_build_data(value)
    value=receipt();value['capabilities']['entry_monitor']['names']=list(reversed(owner.ENTRY_NAMES));rehash(value)
    with pytest.raises(ValueError,match='monitor declaration'):owner.admit_build_data(value)
    value=receipt();value['capability_sha256']='0'*64
    with pytest.raises(ValueError,match='digest'):owner.admit_build_data(value)


def test_world_quiet_sources_and_eleventh_monitor_are_explicitly_bound():
    value=receipt()
    assert owner.ENTRY_NAMES[-1]=='world_forcing' and len(owner.ENTRY_NAMES)==11
    assert set(owner.INCLUDE_PATHS)<=set(value['support_sources'])
    assert 'ops_sim/v5/lifecycle_typed_world.py'in value['support_sources']
    for missing in (*owner.INCLUDE_PATHS,'ops_sim/v5/lifecycle_typed_world.py'):
        changed=deepcopy(value);del changed['support_sources'][missing]
        with pytest.raises(ValueError,match='support source'):owner.admit_build_data(changed)
    changed=deepcopy(value);changed['capabilities']['entry_monitor']['names'].pop();rehash(changed)
    with pytest.raises(ValueError,match='monitor declaration'):owner.admit_build_data(changed)


def test_python_callable_impostors_cannot_replace_a_compiled_export():
    class CallableObject:
        __module__=owner.MODULE
        __name__='prepare_static'
        def __call__(self,*args,**kwargs):raise AssertionError('impostor invoked')
    ordinary=CallableObject()
    disguised=type(owner.CALLABLE_TYPE_NAME,(),{'__module__':owner.CALLABLE_TYPE_MODULE,
        '__name__':'prepare_static','__call__':lambda self,*a,**k:None})()
    for changed in (ordinary,disguised,lambda:None,None):
        with pytest.raises(ValueError,match='compiled typed callable'):
            owner._compiled_callable(changed,'prepare_static')
    assert not type(disguised).__flags__&owner.CALLABLE_REQUIRED_FLAGS


def test_partial_quiet_is_explicit_truthful_data_and_never_full_activation(monkeypatch):
    value=receipt(quiet=False)
    assert owner.admit_build_data(value)['execution_domain']==owner.SUPPORT_DOMAIN
    wrong=deepcopy(value);wrong['execution_domain']=owner.FULL_DOMAIN
    with pytest.raises(ValueError,match='callback-free quiet'):owner.admit_build_data(wrong)
    def forbidden(*a,**k):raise AssertionError('partial domain reached file/import side effect')
    monkeypatch.setattr(owner,'_live_file',forbidden)
    with pytest.raises(ValueError,match='full typed activation'):owner.admit_typed_build(value)
    with pytest.raises(ValueError,match='separately bound support'):owner.admit_typed_build(value,require_quiet=False)
    with pytest.raises(ValueError,match='separately bound support'):
        owner.admit_typed_build(value,require_quiet=False,execution_domain=owner.FULL_DOMAIN)
    with pytest.raises(ValueError,match='exact typed quiet'):owner.admit_typed_build(value,require_quiet=1)


def test_live_admission_checks_runtime_and_actual_loader_before_import(tmp_path,monkeypatch):
    from ops_sim.v5 import lifecycle_backend
    value=receipt();monkeypatch.setattr(lifecycle_backend,'runtime_binding',lambda:value['runtime'])
    def materialize(binding):
        path=tmp_path/binding['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x')
        binding['sha256']=sha256(b'x').hexdigest()
    for item in (value['artifact'],value['engine_source'],value['generated_c'],*value['support_sources'].values()):materialize(item)
    def forbidden(*a,**k):raise AssertionError('source-loader impostor was imported')
    monkeypatch.setattr(owner.importlib,'import_module',forbidden)
    monkeypatch.setattr(owner.importlib.util,'find_spec',lambda name:SimpleNamespace(
        loader=importlib.machinery.SourceFileLoader(name,str(tmp_path/'fake.py')),
        origin=str(tmp_path/value['artifact']['path'])))
    with pytest.raises(ValueError,match='ExtensionFileLoader'):owner.admit_typed_build(value,source=tmp_path)
    value['generated_c']['sha256']='f'*64
    with pytest.raises(ValueError,match='artifact hash'):owner.admit_typed_build(value,source=tmp_path)


@pytest.mark.parametrize('field,changed',[
    ('total',True),('total',1),('limit',2**55),('exhausted',True),('gil_held',False),('reset_available',True),
    ('format','B63_MONOTONE_NATIVE_ENTRY_COUNTS_V1'),('source_binding','SUMMARY_ONLY'),('module_basename','_lifecycle_native.pyd')])
def test_monitor_refuses_wrong_types_scope_saturation_or_balance(field,changed):
    value=receipt();counts=monitor(value);counts[field]=changed
    with pytest.raises(ValueError):owner.admit_native_counts(counts,value)


def test_restore_zero_proof_is_exact_and_any_numerical_delta_is_refused():
    value=receipt();before=monitor(value);after=deepcopy(before)
    proof=owner.native_restore_proof(before,after,value,'a'*64)
    assert proof['format']=='B64_TYPED_RESTORE_ZERO_V1' and proof['total_delta']==0
    assert proof['delta']=={name:0 for name in owner.ENTRY_NAMES}
    assert proof['execution_domain']==owner.FULL_DOMAIN
    after['counts']['allocation_trial']=1;after['total']=1
    with pytest.raises(ValueError,match='numerical entries'):owner.native_restore_proof(before,after,value,'a'*64)
    with pytest.raises(ValueError,match='numerical entries'):owner.native_restore_proof(after,before,value,'a'*64)
