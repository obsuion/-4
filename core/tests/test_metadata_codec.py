"""Differential metadata tests: full exact signatures/wire, no physical calls."""
from pathlib import Path
from dataclasses import dataclass,fields,replace
from fractions import Fraction
from decimal import Decimal
from enum import Enum
import json,pytest
from ops_sim.v5.prepared_input_codec import PreparedInputCodec,_owner_signature
from ops_sim.v5.long_mission_continuation import _scientific_reference,_scientific
from ops_sim.v5.metadata_codec import metadata_scope
from ops_sim.v5.lifecycle_typed_platform import admit_typed_build

@pytest.fixture(scope='module')
def native():
    b=json.loads((Path(__file__).parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes())
    return admit_typed_build(b)

class Color(Enum):RED='red'
@dataclass(frozen=True)
class Record:
    position:tuple
    scalar:object

@pytest.mark.parametrize('value',[None,True,False,0,2**250,-2**250,'Привет',0.0,-0.0,1.25,
    float('inf'),float('nan'),Decimal('1.2300'),Decimal('-0'),Decimal('NaN'),Fraction(3,7),
    Color.RED,(1,2),[1,2],{'a':[1,Record((0.,-0.,3.),Fraction(-5,9))]}])
def test_complete_wire_exact(value,native):
    before=native.native_entry_counts()
    assert native.scientific_output_v1(value)==_scientific_reference(value)
    with metadata_scope(native):assert _scientific(value)==_scientific_reference(value)
    assert native.native_entry_counts()==before

def test_all_registered_owner_signatures_exact(native):
    with PreparedInputCodec()as codec:
        owners=tuple(codec._owners)
        for owner in owners:
            assert native.input_owner_signature_v1(owner)==_owner_signature(owner,retained=[])
        with metadata_scope(native):
            for owner in owners:codec.owner(owner)
    assert len(owners)>200

@pytest.mark.parametrize('name',['name','type','default','default_factory','init','repr','hash','compare','kw_only','metadata','_field_type'])
def test_changed_owner_metadata_still_refuses(name,native):
    from ops_sim.v5.power_loads import PowerLoadBreakdown
    with PreparedInputCodec()as codec:
        f=fields(PowerLoadBreakdown)[0];old=getattr(f,name)
        with metadata_scope(native):
            setattr(f,name,'foreign'if name=='name'else object())
            try:
                # Native signature is a full read, not an immutable-id memo.
                with pytest.raises((ValueError,TypeError,AttributeError)):codec.owner(PowerLoadBreakdown)
            finally:setattr(f,name,old)

def test_mutable_export_is_refused_and_original_exception_preserved(native):
    old=native.scientific_output_v1
    with metadata_scope(native):
        native.scientific_output_v1=lambda x:old(x)
        try:
            with pytest.raises(ValueError,match='drift'):_scientific([1])
        finally:native.scientific_output_v1=old
    error=RuntimeError('original')
    with pytest.raises(RuntimeError)as captured:
        with metadata_scope(native):raise error
    assert captured.value is error

def test_actual_authored_root_wire_and_counters(native):
    from ops_sim.v5.spacecraft_project_document import loads_project
    raw=(Path(__file__).parent/'fixtures/year_authored_A.project.json').read_text('utf8')
    before=native.native_entry_counts();p=loads_project(raw)
    expected=_scientific_reference(p.common)
    with metadata_scope(native):
        assert _scientific(p.common)==expected
    counts=native.metadata_codec_counts_v1()
    assert counts['owner_signatures']>0 and counts['scientific_encodings']>0
    assert native.native_entry_counts()==before

@pytest.mark.parametrize('value',[object(),complex(1,2),{1,2}])
def test_unsupported_domain_is_not_coerced(value,native):
    with pytest.raises(TypeError):_scientific_reference(value)
    with pytest.raises(TypeError):native.scientific_output_v1(value)


def test_legacy_context_keeps_reference_metadata_dispatch():
    from contextlib import nullcontext
    from types import SimpleNamespace
    from ops_sim.v5.lifecycle_typed_context import TypedBackendContext,SUPPORT_DOMAIN
    calls=[]
    fake=SimpleNamespace(selection=SUPPORT_DOMAIN,native=object(),root=object(),model=object(),
        _guard_activation=lambda:calls.append('activation'),_static_guard=lambda:calls.append('static'))
    fake.job=SimpleNamespace(transaction=lambda *args:nullcontext())
    with TypedBackendContext.transaction(fake)as current:assert current is fake
    assert calls==['activation','static','static']
