"""Administrative parent/Runner-thread handoff; no numerical child is run."""
from copy import deepcopy
from hashlib import sha256
from threading import Event,RLock,Thread
import zlib

import pytest

from ops_sim.v5 import lifetime_packed_status as packed
from ops_sim.v5 import lifetime_status as status
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy
from test_year_packed_status import job,binding,field


@pytest.fixture(autouse=True)
def standalone_data(monkeypatch):
    monkeypatch.setattr(packed,'_claim',lambda path:None)


def join(thread):
    thread.join(5)
    assert not thread.is_alive(),'synthetic administrative thread did not settle'


def test_parent_creates_runner_thread_publishes_parent_closes_exact_data(tmp_path):
    from types import SimpleNamespace
    class Writer:
        def __init__(self,*args,**kwargs):self.sequence=0;self.head=SimpleNamespace(closed=False)
        def publish(self,value,*,terminal=False):self.sequence+=1;return self.sequence
        def close(self):self.head.closed=True
    publisher=status.Publisher(tmp_path/'status63',binding(),LifecycleStreamPolicy(),
        writer_factory=Writer,packed_store=True)
    store_lock=RLock();value=job();value['progress']=dict(padding='x'*7000)
    initial=status.preflight(value,binding(),packed_store=True)
    with store_lock:assert publisher.publish(initial)==1
    result={};errors=[]
    def runner():
        try:
            # Mirrors the existing LifecycleStore.update_job RLock boundary:
            # the parent-created Publisher passes to its Runner thread.
            with store_lock:
                admitted=initial.job;admitted['status']='ADMITTED'
                plan=status.preflight(admitted,binding(),packed_store=True)
                assert publisher.publish(plan)==2
                running=plan.job;running['status']='RUNNING'
                running['progress']=dict(padding='y'*9000)
                final=status.preflight(running,binding(),packed_store=True)
                assert publisher.publish(final)==3
                result['plan']=final
        except BaseException as error:errors.append(error)
    thread=Thread(target=runner,name='synthetic-existing-runner-thread')
    thread.start();join(thread)
    try:
        assert errors==[]
        final=result['plan']
        assert status.hydrate(publisher.directory,final.envelope,binding())==final.job
        assert publisher.sequence==3
    finally:
        # Exercise the actual main-thread close after worker-thread DB use.
        with store_lock:publisher.close()
    with packed.PackedStatus(publisher.directory,binding())as reader:
        assert reader.verify_import()['objects']>0
        assert status.hydrate(publisher.directory,initial.envelope,binding())==initial.job
        assert status.hydrate(publisher.directory,final.envelope,binding())==final.job


def test_two_thread_attempts_serialize_entire_put_and_exception_releases_lock(tmp_path,monkeypatch):
    first_inside=Event();release_first=Event();second_attempted=Event();second_inside=Event()
    original=packed._decoded_metadata;firstkey,firstdata=field(10);secondkey,seconddata=field(11)
    observed=[];errors=[]
    def guarded_decode(key,data,role):
        if key==firstkey and not first_inside.is_set():
            observed.append('FIRST_INSIDE');first_inside.set()
            if not release_first.wait(5):raise AssertionError('synthetic first release deadline')
        if key==secondkey:
            observed.append('SECOND_INSIDE');second_inside.set()
        return original(key,data,role)
    monkeypatch.setattr(packed,'_decoded_metadata',guarded_decode)
    with packed.PackedStatus(tmp_path,binding(),create=True)as store:
        def invoke(key,data,*,second=False):
            try:
                if second:second_attempted.set()
                store.put(key,data,role='FIELD')
            except BaseException as error:errors.append(error)
        first=Thread(target=invoke,args=(firstkey,firstdata))
        second=Thread(target=invoke,args=(secondkey,seconddata),kwargs=dict(second=True))
        first.start()
        try:
            assert first_inside.wait(5)
            second.start();assert second_attempted.wait(5)
            # First owns the public operation while waiting outside SQLite;
            # second may not even begin codec/guard work until it is released.
            assert not second_inside.wait(.05)
        finally:
            release_first.set();join(first)
            if second.ident is not None:join(second)
        assert errors==[] and second_inside.is_set()
        assert observed.index('FIRST_INSIDE')<observed.index('SECOND_INSIDE')
        assert store.snapshot()['logical_objects']==2
        with pytest.raises(ValueError):store.put('objects/'+'0'*64+'.zjson',firstdata,role='FIELD')
        third=Thread(target=invoke,args=field(12));third.start();join(third)
        assert errors==[] and store.snapshot()['logical_objects']==3
        assert store.contains(firstkey,firstdata)and store.read(secondkey)==seconddata


@pytest.mark.parametrize('operation',('read','contains','put','verify_import','snapshot','close','enter'))
def test_foreign_pid_rejected_before_lock_or_sqlite_handle(tmp_path,monkeypatch,operation):
    store=packed.PackedStatus(tmp_path,binding(),create=True);key,data=field()
    store.put(key,data,role='FIELD');real_pid=store._pid;real_lock=store._lock
    class ForbiddenLock:
        def __enter__(self):raise AssertionError('foreign process reached inherited lock')
        def __exit__(self,*args):raise AssertionError('foreign process reached inherited lock')
    try:
        with monkeypatch.context()as patch:
            patch.setattr(packed.os,'getpid',lambda:real_pid+1)
            patch.setattr(store,'_lock',ForbiddenLock())
            calls=dict(read=lambda:store.read(key),contains=lambda:store.contains(key,data),
                put=lambda:store.put(*field(1),role='FIELD'),verify_import=store.verify_import,
                snapshot=store.snapshot,close=store.close,enter=store.__enter__)
            with pytest.raises(ValueError,match='foreign-process'):calls[operation]()
        assert store.snapshot()['logical_objects']==1 and store.read(key)==data
    finally:
        store._lock=real_lock;store.close()


def test_non_thread_capable_sqlite_refused_before_output(tmp_path,monkeypatch):
    monkeypatch.setattr(packed.sqlite3,'threadsafety',0)
    with pytest.raises(ValueError,match='thread-capable'):packed.PackedStatus(tmp_path,binding(),create=True)
    assert not(tmp_path/'packed-v1').exists()
