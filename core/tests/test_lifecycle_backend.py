"""B63 explicit build/ABI and invocation authority checks."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import os,platform,socket,sys
import pytest
from ops_sim.v5 import lifecycle_backend as backend
from lifetime_support import SOURCE, root_for

def receipt():return json.loads((SOURCE/'ops_sim/v5/lifecycle_native_build_receipt.json').read_bytes())

def test_real_build_import_and_canonical_capability():
    value=receipt();module=backend.admit_native_build(value)
    assert module.native_capability()['canary'] is True
    assert sha256(backend.canonical(module.native_capability())).hexdigest()==value['capability_sha256']


@pytest.mark.parametrize('number,name',[(0,'x86'),(5,'ARM'),(6,'IA64'),(9,'AMD64'),(12,'ARM64')])
def test_local_windows_native_architecture_mapping(number,name):
    assert backend._windows_architecture_name(number)==name


@pytest.mark.parametrize('number',[True,False,None,'9',9.0,-1,1,7,11,65535,2**32])
def test_unknown_or_nonexact_windows_architecture_is_refused(number):
    with pytest.raises(ValueError,match='processor architecture'):
        backend._windows_architecture_name(number)


def test_runtime_binding_does_not_read_hostname_or_platform_machine(monkeypatch):
    expected=receipt()['runtime']['machine']if sys.platform=='win32'else os.uname().machine
    def forbidden(*args,**kwargs):raise AssertionError('hostname/platform.machine is not local ABI authority')
    monkeypatch.setattr(platform,'machine',forbidden)
    monkeypatch.setattr(socket,'gethostname',forbidden)
    value=backend.runtime_binding()
    assert value['machine']==expected
    assert set(value)=={'implementation','python','cache_tag','ext_suffix','platform','machine'}


def test_native_receipt_admission_survives_denied_hostname(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('hostname/platform.machine must not be called')
    monkeypatch.setattr(platform,'machine',forbidden)
    monkeypatch.setattr(socket,'gethostname',forbidden)
    value=receipt()
    module=backend.admit_native_build(value)
    assert backend.runtime_binding()==value['runtime']
    assert module.native_capability()['canary']is True


def test_windows_system_info_abi_layout_and_native_api_not_environment(monkeypatch):
    import ctypes
    from types import SimpleNamespace
    captured={}
    class NativeInfo:
        def __call__(self,pointer):
            value=pointer._obj;owner=type(value)
            captured['size']=ctypes.sizeof(owner)
            captured['offsets']={name:getattr(owner,name).offset for name,*_ in owner._fields_}
            captured['argtypes']=self.argtypes;captured['restype']=self.restype
            value.u.processor.wProcessorArchitecture=9
    function=NativeInfo()
    def library(name,*,use_last_error):
        assert name=='kernel32'and use_last_error is True
        return SimpleNamespace(GetNativeSystemInfo=function)
    monkeypatch.setattr(backend.sys,'platform','win32')
    monkeypatch.setattr(ctypes,'WinDLL',library,raising=False)
    monkeypatch.setenv('PROCESSOR_ARCHITECTURE','ARM64')
    monkeypatch.setenv('PROCESSOR_ARCHITEW6432','ARM64')
    assert backend._machine_identity()=='AMD64'
    pointer=ctypes.sizeof(ctypes.c_void_p)
    assert captured['size']==(48 if pointer==8 else 36)
    assert captured['offsets']==dict(u=0,dwPageSize=4,lpMinimumApplicationAddress=8,
        lpMaximumApplicationAddress=8+pointer,dwActiveProcessorMask=8+2*pointer,
        dwNumberOfProcessors=8+3*pointer,dwProcessorType=12+3*pointer,
        dwAllocationGranularity=16+3*pointer,wProcessorLevel=20+3*pointer,wProcessorRevision=22+3*pointer)
    assert len(captured['argtypes'])==1 and captured['restype']is None


def test_native_api_missing_architecture_fails_closed(monkeypatch):
    import ctypes
    from types import SimpleNamespace
    class NoWrite:
        def __call__(self,pointer):pass
    monkeypatch.setattr(backend.sys,'platform','win32')
    monkeypatch.setattr(ctypes,'WinDLL',lambda *a,**k:SimpleNamespace(GetNativeSystemInfo=NoWrite()),raising=False)
    with pytest.raises(ValueError,match='unsupported native Windows'):
        backend._machine_identity()


@pytest.mark.parametrize('machine',['','bad machine',None,True,'x'*129])
def test_unix_machine_is_local_and_strict(monkeypatch,machine):
    from types import SimpleNamespace
    monkeypatch.setattr(backend.sys,'platform','linux')
    monkeypatch.setattr(backend.os,'uname',lambda:SimpleNamespace(machine=machine),raising=False)
    with pytest.raises(ValueError,match='local uname machine'):
        backend._machine_identity()

@pytest.mark.parametrize('path', ['runtime','artifact','capability','engine','format','extra'])
def test_changed_build_refused(path):
    value=receipt()
    if path=='runtime':value['runtime']['python']='foreign'
    if path=='artifact':value['artifact']['sha256']='f'*64
    if path=='capability':value['capability_sha256']='f'*64
    if path=='engine':value['engine_source_sha256']='f'*64
    if path=='format':value['format']='B60_SEALED_STATIC_V1'
    if path=='extra':value['validated']=True
    with pytest.raises(ValueError):backend.admit_native_build(value)

@pytest.mark.parametrize('selection',[None,True,'B60_SEALED_STATIC_V1','NATIVE','prepared_native'])
def test_no_implicit_or_alias_selection(selection):
    with pytest.raises(ValueError):backend.BackendContext(None,None,selection,'a'*64)

def test_reference_rejects_foreign_native_receipt():
    with pytest.raises(ValueError):backend.BackendContext(None,None,'REFERENCE','a'*64,receipt())

def test_invalid_build_fails_before_preparation(monkeypatch):
    import ops_sim.v5.lifecycle_prepared as owner
    def forbidden(*a,**k):raise AssertionError('preparation was reached')
    monkeypatch.setattr(owner,'prepare_runtime',forbidden)
    value=receipt();value['runtime']['cache_tag']='foreign'
    with pytest.raises(ValueError,match='ABI'):backend.BackendContext(None,None,'PREPARED_NATIVE','a'*64,value)

def test_full_source_binding_not_object_identity():
    value=backend.current_source_binding()
    assert type(value)is str and len(value)==64 and value==backend.current_source_binding()


@pytest.mark.parametrize('selection',backend.SELECTIONS)
def test_selected_input_codec_retains_exact_root_without_native_activation(monkeypatch,selection):
    from ops_sim.v5.lifecycle_document import dumps_root
    raw=dumps_root(root_for(60));receipts=[]
    def forbidden(*a,**k):raise AssertionError('pure input reader cannot activate native execution')
    monkeypatch.setattr(backend,'admit_native_build',forbidden)
    result=backend.load_root_for_backend(raw,selection,receipts=receipts)
    assert dumps_root(result)==raw
    if selection==backend.REFERENCE:assert receipts==[]
    else:
        assert len(receipts)==1
        assert receipts[0]['counters']['full_schema_scans']==2


@pytest.mark.parametrize('selection',[True,None,'NATIVE','prepared_native'])
def test_input_codec_selector_refuses_unbound_mode_before_parsing(selection):
    with pytest.raises(ValueError,match='explicit input-admission'):
        backend.load_root_for_backend(b'not a document',selection)

@pytest.fixture(scope='module')
def native_context():
    from ops_sim.v5.lifecycle_execution import build_model
    root=root_for(60);model=build_model(root)
    return backend.BackendContext(root,model,'PREPARED_NATIVE',backend.current_source_binding(),receipt())

@pytest.mark.parametrize('field,new_value',[('selection','REFERENCE'),('native',None),
    ('source_binding','f'*64),('actual',None),('forecast',None),('build',None)])
def test_mutated_activation_rejected_before_dispatch(native_context,field,new_value):
    from types import SimpleNamespace
    old=getattr(native_context,field);setattr(native_context,field,new_value)
    def forbidden(*a,**k):raise AssertionError('silent reference fallback')
    try:
        with pytest.raises(ValueError,match='activation drift'):
            backend.service_call(SimpleNamespace(backend_context=native_context),forbidden)
        with pytest.raises(ValueError,match='activation drift'):
            native_context.guard(native_context.root,native_context.model)
    finally:setattr(native_context,field,old)
