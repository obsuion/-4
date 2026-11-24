"""Differential YEAR-V2 canonical loops; full wire, constructors and guards."""
from pathlib import Path
from fractions import Fraction
from dataclasses import fields,is_dataclass
from enum import Enum
import importlib.util,json,math
import pytest
from ops_sim.v5 import experiment_codec as c
from ops_sim.v5.lifecycle_typed_platform import admit_typed_build
from ops_sim.v5.metadata_codec import metadata_scope

@pytest.fixture(scope='module')
def native():return admit_typed_build(json.loads((Path(__file__).parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes()))

@pytest.fixture(scope='module')
def oracle():
    # Portable frozen source, the original canonical algorithm, no dynamic run.
    p=Path(__file__).parent/'fixtures/year_v1_experiment_codec.py.txt'
    spec=importlib.util.spec_from_loader('ops_sim.v5._year_v1_oracle',loader=None)
    module=importlib.util.module_from_spec(spec);exec(compile(p.read_text(encoding='utf8'),str(p),'exec'),module.__dict__)
    return module

@pytest.mark.parametrize('value',[None,True,False,0,2**256,-2**256,0.,-0.,1.25,'Русский',(1,'a'),[1,'a'],{'z':(-0.,Fraction(17,29)),'a':None},Fraction(1,7)])
def test_full_encode_decode_exact(native,oracle,value):
    before=native.native_entry_counts();encoded=oracle.canonical_content(value)
    with metadata_scope(native):
        assert c.canonical_content(value)==encoded
        assert c.json_text(c.canonical_content(c.decode_content(encoded)))==c.json_text(encoded)
        assert c.json_text(c.canonical_content(c.canonical_copy(value)))==c.json_text(encoded)
    assert native.native_entry_counts()==before

@pytest.mark.parametrize('payload',[{'kind':'float','value':'nan'},{'kind':'int','value':'01'},{'kind':'none','extra':0},{'kind':'fraction','numerator':'2','denominator':'4'},{'kind':'map','items':[['x',{'kind':'none'}],['x',{'kind':'none'}]]},{'kind':'record','type':'not.allowed','fields':{}},{'kind':'tuple','items':()}, {'kind':'str','value':1}])
def test_invalid_wire_rejection_type_matches(native,oracle,payload):
    with pytest.raises(Exception)as expected:oracle.decode_content(payload)
    with metadata_scope(native):
        with pytest.raises(type(expected.value)):c.decode_content(payload)

@pytest.mark.parametrize('value',[float('inf'),float('nan'),object(),{1:'nontext'},complex(1,2)])
def test_unsupported_input_same_rejection(native,oracle,value):
    with pytest.raises(Exception)as expected:oracle.canonical_content(value)
    with metadata_scope(native):
        with pytest.raises(type(expected.value)):c.canonical_content(value)

@pytest.mark.parametrize('field_name',['name','init'])
def test_schema_is_rechecked_and_changes_are_not_cached(native,oracle,field_name):
    owner=next(iter(c.RECORD_FIELDS));f=fields(owner)[0];old=getattr(f,field_name)
    with metadata_scope(native):
        c.check_schema_coverage()
        setattr(f,field_name,'foreign'if field_name=='name'else False)
        try:
            with pytest.raises(ValueError):c.check_schema_coverage()
            with pytest.raises(ValueError):oracle.check_schema_coverage()
        finally:setattr(f,field_name,old)
        c.check_schema_coverage()

def test_real_authored_legacy_record_population(native,oracle):
    from ops_sim.v5.spacecraft_project_document import loads_project
    p=loads_project((Path(__file__).parent/'fixtures/year_authored_A.project.json').read_text('utf8'))
    seen=set();supported=[]
    def walk(v):
        if id(v)in seen:return
        seen.add(id(v))
        if type(v)in c.RECORD_FIELDS or type(v)in c.ENUM_TYPES:supported.append(v)
        if is_dataclass(v):
            for f in fields(v):walk(getattr(v,f.name))
        elif type(v)in(tuple,list):
            for x in v:walk(x)
        elif type(v)is dict:
            for x in v.values():walk(x)
    walk(p);assert len(supported)>100
    for v in supported:
        encoded=oracle.canonical_content(v)
        with metadata_scope(native):
            assert c.canonical_content(v)==encoded
            assert c.canonical_content(c.decode_content(encoded))==encoded
    assert native.canonical_codec_counts_v2()['encodings']>0

def test_export_drift_rejected_before_unsafe_codec(native):
    original=native.canonical_encode_v2
    with metadata_scope(native):
        native.canonical_encode_v2=lambda *a: {'unsafe':True}
        try:
            with pytest.raises(ValueError,match='drift'):c.canonical_content([1])
        finally:native.canonical_encode_v2=original


@pytest.mark.parametrize('attribute',['pid','thread','calls','native','closed','gate_code'])
def test_complete_native_scope_live_fields_still_checked(native,attribute):
    with metadata_scope(native)as scope:
        old=getattr(scope,attribute)
        bad={'pid':-1,'thread':-1,'calls':(),'native':object(),'closed':True,'gate_code':object()}[attribute]
        setattr(scope,attribute,bad)
        try:
            with pytest.raises((ValueError,AttributeError,IndexError,TypeError)):scope.check()
        finally:setattr(scope,attribute,old)
        scope.check()

def test_scope_guard_export_cannot_be_replaced_by_python(native):
    old=native.metadata_scope_check_v2
    with metadata_scope(native)as scope:
        native.metadata_scope_check_v2=lambda *a:None
        try:
            with pytest.raises(ValueError):scope.check()
        finally:native.metadata_scope_check_v2=old

def test_codec_package_attribute_substitution_cannot_redirect_native_namespace(native,oracle,monkeypatch):
    import ops_sim.v5 as package
    from types import SimpleNamespace
    with metadata_scope(native):
        monkeypatch.setattr(package,'experiment_codec',SimpleNamespace(_encode=lambda _: {'unsafe':True}))
        assert c.canonical_content((1,-0.,Fraction(2,7)))==oracle.canonical_content((1,-0.,Fraction(2,7)))
    monkeypatch.undo()

@pytest.mark.parametrize('name',['_encode_reference','_decode_reference','_check_schema_coverage_reference'])
def test_reference_alias_function_remains_in_full_input_seal(native,name):
    from ops_sim.v5.prepared_input_codec import PreparedInputCodec
    old=getattr(c,name)
    with metadata_scope(native):
        try:
            with pytest.raises(ValueError,match='drift|binding'):
                with PreparedInputCodec():setattr(c,name,lambda *a:None)
        finally:setattr(c,name,old)


@pytest.mark.parametrize('name',['_encode_reference','_decode_reference','_check_schema_coverage_reference'])
def test_reference_alias_substitution_before_input_entry_is_rejected(native,name):
    from ops_sim.v5.prepared_input_codec import PreparedInputCodec
    old=getattr(c,name)
    with metadata_scope(native):
        setattr(c,name,lambda *a:None)
        try:
            with pytest.raises(ValueError,match='binding'):
                with PreparedInputCodec():pass
        finally:setattr(c,name,old)


@pytest.mark.parametrize('name',['canonical_encode','canonical_decode','canonical_schema'])
def test_metadata_helper_code_substitution_before_entry_refuses(native,name):
    from ops_sim.v5 import metadata_codec as m
    from ops_sim.v5.prepared_input_codec import PreparedInputCodec
    fn=getattr(m,name);old=fn.__code__
    def foreign(*a,**kw):return None
    with metadata_scope(native):
        fn.__code__=foreign.__code__
        try:
            with pytest.raises(ValueError,match='binding'):
                with PreparedInputCodec():pass
        finally:fn.__code__=old

def test_foreign_contextvar_scope_is_not_a_metadata_grant(native):
    from ops_sim.v5 import metadata_codec as m
    from types import SimpleNamespace
    fake=SimpleNamespace(check=lambda:None,native=native,calls=((None,lambda *a: {'unsafe':True}),)*8)
    token=m._ACTIVE.set(fake)
    try:
        with pytest.raises(TypeError,match='exact'):
            with metadata_scope(native):pass
        with pytest.raises(TypeError,match='exact'):c.canonical_content((1,2))
    finally:m._ACTIVE.reset(token)
