"""V4 native job/generation records: control-only real-owner negatives.

The existing immutable build is admitted by its receipt. These tests start no
scientific worker and make no numerical transition. The old generation/full
boundary tests remain part of affected acceptance.
"""
import json
from pathlib import Path
import sys
import threading
import pytest
from lifetime_support import root_for
from ops_sim.v5 import lifecycle_job_prepared as jp,lifecycle_exact_guards as eg
from ops_sim.v5 import lifecycle_generation as generation
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.lifecycle_typed_platform import admit_typed_build

@pytest.fixture
def record_job():
    receipt=Path(__file__).resolve().parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json'
    build=json.loads(receipt.read_bytes());native=admit_typed_build(build)
    root,admission=jp.admit_job_root(dumps_root(root_for(600)),'b'*64,build_binding=build)
    job=jp.prepare_job_runtime(admission,root)
    session=eg.enable_exact_guards(job,native)
    assert job._guard_records_enabled is True
    validation=generation.enable(job,lambda:None)
    native.bind_guard_generation(session._arena,session._binding,session,job,validation)
    job._guard_identity()
    yield job,native
    if not job._closed:job.close()

def test_identity_uses_one_native_record_without_python_pin_or_signature_pipeline(record_job):
    job,native=record_job
    forbidden={jp._guard_generation_owner.__code__,generation._Generation.cheap.__code__,
        eg.ExactGuardSession.check.__code__,eg.ExactGuardSession.generation.__code__}
    called=[];previous=sys.getprofile()
    before=native.guard_record_counts();fees=dict(job._work);entries=native.native_entry_counts()
    def watch(frame,event,arg):
        if event=='call'and frame.f_code in forbidden:called.append(frame.f_code.co_name)
    try:
        sys.setprofile(watch)
        for _ in range(20):job._guard_identity()
    finally:sys.setprofile(previous)
    after=native.guard_record_counts()
    assert not called
    assert after['identity_attempts']==before['identity_attempts']+20
    assert after['identity_completed']==before['identity_completed']+20
    assert after['identity_failed']==before['identity_failed']
    assert job._work==fees and native.native_entry_counts()==entries
    assert after['scientific_work']=='UNCHANGED'and after['reset_available']is False

@pytest.mark.parametrize('which',(
    'self','closed','runtime','source','roles','role-swap','work-owner','work-missing','work-extra',
    'work-bool','work-negative','work-overflow','work-balance','generation',
    'admission-phase','admission-bytes','admission-work','admission-order',
    'alias-key','alias-type','static-digest','record-mode'))
def test_fixed_native_job_record_preserves_every_identity_and_ledger_family(record_job,which):
    job,native=record_job;changes=[];work=dict(job._work);roles=dict(job._roles)
    admission=job._admission;admission_work=list(admission._work.items());aliases=dict(job._thermal_aliases)
    def change(owner,name,value):
        changes.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
    try:
        if which=='self':change(job,'_self',object())
        elif which=='closed':change(job,'_closed',True)
        elif which=='runtime':change(job,'_runtime',tuple([*job._runtime]))
        elif which=='source':change(job,'source_binding','c'*64)
        elif which=='roles':change(job,'_roles',dict(job._roles))
        elif which=='role-swap':job._roles['ACTUAL'],job._roles['FORECAST']=job._roles['FORECAST'],job._roles['ACTUAL']
        elif which=='work-owner':change(job,'_work',dict(job._work))
        elif which=='work-missing':job._work.pop('report_parts')
        elif which=='work-extra':job._work['foreign']=0
        elif which=='work-bool':job._work['report_parts']=True
        elif which=='work-negative':job._work['report_parts']=-1
        elif which=='work-overflow':job._work['report_parts']=2**48+1
        elif which=='work-balance':job._work['transaction_completed']=job._work['transaction_attempts']+1
        elif which=='generation':change(job,'_generation',2**48)
        elif which=='admission-phase':change(admission,'_phase','READY')
        elif which=='admission-bytes':change(admission,'_raw',b'foreign')
        elif which=='admission-work':admission._work['control_units_reserved']+=1
        elif which=='admission-order':
            admission._work.clear();admission._work.update(reversed(admission_work))
        elif which=='alias-key':job._thermal_aliases['FOREIGN']=object()
        elif which=='alias-type':job._thermal_aliases['TYPED_CONSTRUCTION_V1']=object()
        elif which=='static-digest':change(job,'_baseline_identity','d'*64)
        else:change(job,'_guard_records_enabled',False)
        entries=native.native_entry_counts();published=[]
        with pytest.raises((ValueError,TypeError,AttributeError)):
            job._guard_identity();published.append(True)
        assert not published and native.native_entry_counts()==entries
    finally:
        for owner,name,value in reversed(changes):setattr(owner,name,value)
        job._work.clear();job._work.update(work)
        job._roles.clear();job._roles.update(roles)
        admission._work.clear();admission._work.update(admission_work)
        job._thermal_aliases.clear();job._thermal_aliases.update(aliases)
    job._guard_identity()

@pytest.mark.parametrize('which',(
    'validation-pin','validation-both','generation-pins','hook','counts-owner',
    'counts-bool','counts-negative','counts-overflow','counts-key','epoch-negative','epoch-overflow','phase','invalid'))
def test_bound_generation_record_rejects_copied_authority_and_dynamic_counter_drift(record_job,which):
    job,native=record_job;g=job._validation;changes=[];counts=dict(g._counts)
    def change(owner,name,value):
        changes.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
    try:
        if which=='validation-pin':change(job,'_validation_pin',object())
        elif which=='validation-both':
            foreign=object.__new__(generation._Generation)
            for name in generation._Generation.__slots__:setattr(foreign,name,getattr(g,name))
            foreign._pins=(foreign,job,foreign._hook,*g._pins[3:])
            change(job,'_validation',foreign);change(job,'_validation_pin',foreign)
        elif which=='generation-pins':change(g,'_pins',tuple([*g._pins]))
        elif which=='hook':change(g,'_hook',lambda:None)
        elif which=='counts-owner':change(g,'_counts',dict(g._counts))
        elif which=='counts-bool':g._counts['closed_requests']=True
        elif which=='counts-negative':g._counts['closed_requests']=-1
        elif which=='counts-overflow':g._counts['closed_requests']=2**40
        elif which=='counts-key':g._counts['foreign']=0
        elif which=='epoch-negative':change(g,'_epoch',-1)
        elif which=='epoch-overflow':change(g,'_epoch',2**40+1)
        elif which=='phase':change(g,'_phase','FOREIGN')
        else:change(g,'_phase','INVALID')
        with pytest.raises((ValueError,TypeError,AttributeError)):job._guard_identity()
    finally:
        for owner,name,value in reversed(changes):setattr(owner,name,value)
        g._counts.clear();g._counts.update(counts)
    job._guard_identity()

def test_dynamic_work_key_order_and_exact_inclusive_bounds_are_preserved(record_job):
    job,native=record_job;g=job._validation
    job_values=list(job._work.items());counts=list(g._counts.items());epoch=g._epoch
    try:
        job._work.clear();job._work.update(reversed(job_values))
        g._counts.clear();g._counts.update(reversed(counts))
        job._work['report_parts']=2**48
        g._epoch=2**40
        g._counts['closed_requests']=2**40-1
        job._guard_identity()
    finally:
        job._work.clear();job._work.update(job_values)
        g._counts.clear();g._counts.update(counts);g._epoch=epoch
    job._guard_identity()

@pytest.mark.parametrize('name',('cheap','closed','activate','callback_begin','callback_end','finish','snapshot'))
def test_generation_class_and_method_changes_reject_before_mutated_method_runs(record_job,name):
    job,native=record_job;owner=generation._Generation;old=getattr(owner,name);called=[]
    def foreign(*args,**kwargs):called.append(True);return True
    try:
        setattr(owner,name,foreign)
        with pytest.raises(ValueError):job._guard_identity()
        assert not called
    finally:setattr(owner,name,old)
    job._guard_identity()

def test_class_dictionary_membership_and_declaring_class_origin_are_sealed(record_job):
    job,native=record_job;owner=generation._Generation;old=jp.PreparedJobRuntime
    try:
        owner.foreign_record_gate=object()
        with pytest.raises(ValueError):job._guard_identity()
    finally:del owner.foreign_record_gate
    try:
        jp.PreparedJobRuntime=type('ForeignJob',(old,),{'__slots__':()})
        with pytest.raises(ValueError):job._guard_identity()
    finally:jp.PreparedJobRuntime=old
    job._guard_identity()

def test_foreign_thread_and_arena_cannot_reuse_current_record(record_job):
    job,native=record_job;errors=[]
    def check():
        try:job._guard_identity()
        except BaseException as error:errors.append(error)
    thread=threading.Thread(target=check);thread.start();thread.join(2)
    assert not thread.is_alive()and len(errors)==1 and isinstance(errors[0],ValueError)
    s=job._guard_plan
    with pytest.raises(ValueError):
        native.dispatch_exact_guard(native.make_guard_arena(s._binding),s._binding,s,job,'identity',job)
    job._guard_identity()

def test_identity_and_generation_records_are_once_only_and_roles_never_alias(record_job):
    job,native=record_job;s=job._guard_plan
    assert job._roles['ACTUAL']is not job._roles['FORECAST']
    assert job._roles['ACTUAL']._job is job._roles['FORECAST']._job is job
    with pytest.raises(ValueError):
        native.bind_guard_identity(s._arena,s._binding,s,job,eg._identity_descriptor(job))
    with pytest.raises(ValueError):
        native.bind_guard_generation(s._arena,s._binding,s,job,job._validation)
    job._guard_identity()

def test_control_counter_subclasses_do_not_execute_comparison_callbacks(record_job):
    job,native=record_job;old=job._work['report_parts'];called=[]
    class EvilInteger(int):
        def __lt__(self,other):called.append(True);return False
        def __le__(self,other):called.append(True);return True
        def __eq__(self,other):called.append(True);return True
    try:
        job._work['report_parts']=EvilInteger(0)
        with pytest.raises(ValueError):job._guard_identity()
        assert not called
    finally:job._work['report_parts']=old
    job._guard_identity()

def test_full_callback_boundaries_still_reject_graph_mutation_and_preserve_primary(record_job):
    job,native=record_job;root=job.external_root;duration=root.duration_seconds;primary=RuntimeError('original callback')
    def callback():
        object.__setattr__(root,'duration_seconds',duration+1)
        raise primary
    try:
        with pytest.raises(RuntimeError)as caught:
            with job.transaction()as tx:tx.callback(callback)
        assert caught.value is primary and job._active is None
        assert getattr(primary,'__notes__',[])
    finally:object.__setattr__(root,'duration_seconds',duration)
    job._full_guard()

def test_unprepared_legacy_job_keeps_strict_python_identity_fallback():
    root,admission=jp.admit_job_root(dumps_root(root_for(600)),'b'*64,build_binding={'synthetic':'guard fallback only'})
    job=jp.prepare_job_runtime(admission,root)
    assert job._guard_records_enabled is False and job._guard_plan is None
    before=dict(job._work);job._guard_identity();assert job._work==before
    old=job._work['report_parts']
    try:
        job._work['report_parts']=True
        with pytest.raises(ValueError):job._guard_identity()
    finally:job._work['report_parts']=old
    job.close()
