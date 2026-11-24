"""Bounded C/Python differential controls; no endpoint or horizon study."""
from copy import copy,deepcopy
from dataclasses import dataclass,fields
from enum import Enum
from fractions import Fraction
import json,pickle,sys,threading
from pathlib import Path
import pytest
from ops_sim.v5.lifecycle_prepared import _Seal
from ops_sim.v5.lifecycle_exact_guards import _Rows,_graph_rows,enable_exact_guards
from ops_sim.v5.lifecycle_typed_platform import admit_typed_build
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.lifecycle_job_prepared import admit_job_root,prepare_job_runtime
from lifetime_support import root_for

@pytest.fixture
def native():
    p=Path(__file__).resolve().parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json'
    return admit_typed_build(json.loads(p.read_bytes()))

@dataclass(frozen=True,slots=True)
class Record:
    text:str
    quantity:Fraction

class Choice(Enum):
    A='a'
    B='b'

def plan(native,owner,rows):
    binding=object();arena=native.make_guard_arena(binding)
    compiled=native.compile_guard_plan(arena,binding,owner,rows)
    return lambda:native.guard_exact_plans(arena,binding,((owner,compiled),)),arena,binding,compiled

@pytest.mark.parametrize('which',('edge','fraction','enum','schema-name','schema-init','seal-replacement'))
def test_graph_mutations_refused_by_native_and_python_oracle(native,which):
    rec=Record('original',Fraction(3,7));seal=_Seal((rec,Choice.A))
    check,arena,binding,compiled=plan(native,seal,_graph_rows(seal));check()
    if which=='edge':target,name,new=rec,'text','foreign'
    elif which=='fraction':target,name,new=rec.quantity,'_numerator',4
    elif which=='enum':target,name,new=Choice.A,'_value_','foreign'
    elif which=='schema-name':target,name,new=fields(Record)[0],'name','foreign'
    elif which=='schema-init':target,name,new=fields(Record)[0],'init',False
    else:target,name,new=seal,'edges',()
    old=getattr(target,name)
    try:
        object.__setattr__(target,name,new)
        with pytest.raises(ValueError):check()
        # Original _Seal allows replacement of its bookkeeping tuples; the new
        # private compiled owner additionally seals the validation gate itself.
        if which!='seal-replacement':
            with pytest.raises(ValueError):seal.guard()
    finally:object.__setattr__(target,name,old)
    seal.guard();check()

def test_exact_canonical_identity_and_local_axis_exceptions_are_retained(native):
    from ops_sim.v5.assembly_attitude import ComponentAxisBinding
    @dataclass(frozen=True)
    class Identity:
        _identity:str=__import__('dataclasses').field(default='a'*64,init=False)
    item=Identity();axis=ComponentAxisBinding('panel','panel1','local',(0.,0.,1.),'assumed')
    seal=_Seal((item,axis));check,*_=plan(native,seal,_graph_rows(seal))
    object.__setattr__(item,'_identity',(' '+item._identity)[1:])
    object.__setattr__(axis,'local_axis',tuple([0.,0.,1.]))
    seal.guard();check()
    object.__setattr__(axis,'local_axis',(-0.,0.,1.))
    with pytest.raises(ValueError):seal.guard()
    with pytest.raises(ValueError):check()

@pytest.mark.parametrize('which',('code','defaults','kwdefaults','closure'))
def test_callable_code_default_and_closure_rows(native,which):
    def factory():
        retained=object()
        def fn(x=object(),*,setting=object()):return retained
        return fn
    fn=factory();out=_Rows();out.function(fn)
    class Owner:pass
    owner=Owner();check,*_=plan(native,owner,out.result())
    code,defaults,kw,cell=fn.__code__,fn.__defaults__,dict(fn.__kwdefaults__),fn.__closure__[0].cell_contents
    try:
        if which=='code':
            def other_factory():
                value=None
                def other(x=None,*,setting=None):return value
                return other
            fn.__code__=other_factory().__code__
        elif which=='defaults':fn.__defaults__=(object(),)
        elif which=='kwdefaults':fn.__kwdefaults__['setting']=object()
        else:fn.__closure__[0].cell_contents=object()
        with pytest.raises(ValueError):check()
    finally:
        fn.__code__=code;fn.__defaults__=defaults;fn.__kwdefaults__.clear();fn.__kwdefaults__.update(kw);fn.__closure__[0].cell_contents=cell
    check()

@pytest.mark.parametrize('which',('replace','order','membership','value'))
def test_registry_order_membership_and_identity(native,which):
    class Owner:pass
    o=Owner();o.registry={'a':object(),'b':object()};out=_Rows()
    out.mapping(o.registry,owner=o,name='registry')
    check,*_=plan(native,o,out.result());old=o.registry;items=list(old.items())
    try:
        if which=='replace':o.registry=dict(old)
        elif which=='order':old.clear();old.update(reversed(items))
        elif which=='membership':old['c']=object()
        else:old['a']=object()
        with pytest.raises(ValueError):check()
    finally:o.registry=old;old.clear();old.update(items)
    check()

def test_guard_plan_is_thread_owner_and_nonpersistent(native):
    seal=_Seal(Record('test',Fraction(2,3)))
    check,arena,binding,compiled=plan(native,seal,_graph_rows(seal));errors=[]
    t=threading.Thread(target=lambda:_capture(check,errors));t.start();t.join(2)
    assert not t.is_alive()and len(errors)==1 and isinstance(errors[0],ValueError)
    for obj in (arena,compiled):
        for f in (copy,deepcopy,pickle.dumps):
            with pytest.raises(TypeError):f(obj)
    with pytest.raises(ValueError):native.guard_exact_plans(arena,object(),((seal,compiled),))
    with pytest.raises(ValueError):native.compile_guard_plan(arena,binding,seal,_graph_rows(seal))
    check()

def _capture(call,errors):
    try:call()
    except BaseException as e:errors.append(e)

@pytest.fixture
def compiled_job(native):
    build=json.loads((Path(__file__).resolve().parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes())
    root,admission=admit_job_root(dumps_root(root_for(600)),'b'*64,build_binding=build)
    job=prepare_job_runtime(admission,root);enable_exact_guards(job,native)
    return job

def test_real_job_boundaries_consume_native_without_repeating_python_oracle(compiled_job):
    import ops_sim.v5.prepared_input_codec as codec
    j=compiled_job
    with j.transaction():pass
    watched={codec._full_snapshot.__code__}if hasattr(codec,'_full_snapshot')else{codec.PreparedInputCodec._full_snapshot.__code__}
    watched|={codec._owner_signature.__code__,codec._function_signature.__code__}
    calls=[];old=sys.getprofile()
    def observe(frame,event,arg):
        if event=='call'and frame.f_code in watched:calls.append(frame.f_code.co_name)
    before=j.exact_guard_statistics()
    sys.setprofile(observe)
    try:
        for _ in range(3):
            with j.transaction():pass
    finally:sys.setprofile(old)
    after=j.exact_guard_statistics()
    assert not calls
    assert after['native_guard_calls']>before['native_guard_calls']
    assert after['python_admission_oracle_calls']==before['python_admission_oracle_calls']
    assert after['descriptors_checked']>before['descriptors_checked']

@pytest.mark.parametrize('which',('unused-default','unused-field','registry','property','gate-function','gate-index','source'))
def test_admitted_full_schema_and_gate_mutation_negatives(compiled_job,which):
    from ops_sim.v5 import experiment_codec as typed
    from ops_sim.v5.lifecycle_job_prepared import PreparedRoleState
    import ops_sim.v5.lifecycle_exact_guards as owner
    j=compiled_job;session=j._guard_plan
    unused=next(o for o in typed.RECORD_FIELDS if fields(o))
    if which=='unused-default':target,name,new=fields(unused)[0],'default',object()
    elif which=='unused-field':target,name,new=fields(unused)[0],'compare',not fields(unused)[0].compare
    elif which=='registry':target,name,new=typed,'_RECORDS',dict(typed._RECORDS)
    elif which=='property':target,name,new=PreparedRoleState,'environment_policy',property(lambda self:None)
    elif which=='gate-function':target,name,new=owner,'_graph_rows',lambda x:()
    elif which=='gate-index':target,name,new=session,'_plans',__import__('weakref').WeakKeyDictionary()
    else:target,name,new=j,'source_binding','c'*64
    old=getattr(target,name);published=[]
    try:
        object.__setattr__(target,name,new)if not isinstance(target,type)and not hasattr(target,'__spec__')else setattr(target,name,new)
        with pytest.raises(ValueError):
            with j.transaction():published.append('entered')
        assert not published
    finally:
        object.__setattr__(target,name,old)if not isinstance(target,type)and not hasattr(target,'__spec__')else setattr(target,name,old)

def test_compiled_finally_failure_keeps_primary_and_no_detached_publication(compiled_job):
    j=compiled_job;root=j.external_root;old=root.duration_seconds;primary=RuntimeError('primary');published=[]
    try:
        with pytest.raises(RuntimeError)as caught:
            with j.transaction():
                object.__setattr__(root,'duration_seconds',old+1)
                raise primary
            published.append(True)
        assert caught.value is primary and not published
        assert getattr(primary,'__notes__',[])and j._active is None
    finally:object.__setattr__(root,'duration_seconds',old)

def test_real_native_gate_replacement_is_rejected_before_invocation(compiled_job):
    j=compiled_job;n=j._guard_plan._native;original=n.guard_exact_plans;calls=[]
    def foreign(*a,**k):calls.append(True)
    try:
        n.guard_exact_plans=foreign
        with pytest.raises(ValueError):j._full_guard()
        assert not calls
    finally:n.guard_exact_plans=original

def test_closed_job_invalidates_both_private_session_and_native_arena(compiled_job):
    j=compiled_job;session=j._guard_plan;j.close()
    with pytest.raises(ValueError):session.receipt()
    with pytest.raises(ValueError):session._native.guard_arena_receipt(session._arena,session._binding)

def test_fake_capability_module_cannot_admit_native_guard(native):
    from types import SimpleNamespace
    build=json.loads((Path(__file__).resolve().parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes())
    root,admission=admit_job_root(dumps_root(root_for(600)),'b'*64,build_binding=build)
    j=prepare_job_runtime(admission,root)
    fake=SimpleNamespace(**{n:getattr(native,n)for n in
        ('guard_plan_capability','make_guard_arena','compile_guard_plan','guard_exact_plans','guard_arena_receipt','close_guard_arena')})
    with pytest.raises(ValueError):enable_exact_guards(j,fake)
    assert j._guard_plan is j._guard_plan_pin is None

def test_mutated_secondary_annotator_cannot_hide_original_exception(compiled_job):
    from ops_sim.v5.lifecycle_job_prepared import PreparedJobRuntime
    j=compiled_job;original=PreparedJobRuntime._secondary
    primary=RuntimeError('actual original primary');published=[]
    def hostile(*a,**k):raise RuntimeError('foreign secondary annotator')
    try:
        with pytest.raises(RuntimeError)as caught:
            with j.transaction():
                PreparedJobRuntime._secondary=hostile
                raise primary
            published.append(True)
        assert caught.value is primary and not published
    finally:PreparedJobRuntime._secondary=original
