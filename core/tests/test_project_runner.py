import json,threading
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.spacecraft_project import SpacecraftProject,project_source_identity
from ops_sim.v5.project_store import ProjectStore
from ops_sim.v5.project_runner import ProjectRunner,IncrementalJournal,validate_progress
from ops_sim.v5.project_worker import PROGRESS

IDENTITY=dict(job_id='a'*32,revision='b'*64,source_identity='c'*64,root_identity='d'*64)
def record(seq,kind='identity',data=None):
    return dict(format=PROGRESS,sequence=seq,kind=kind,identity=IDENTITY,data=data or dict(worker_PID=10,worker_PPID=9,runtime=dict(python='fake',platform='synthetic',executable='none',interpreter_sha256='0'*64)))

def test_incremental_reader_explicit_partial_tail_and_sequence(tmp_path):
    p=tmp_path/'journal';one=json.dumps(record(1)).encode()+b'\n';two=json.dumps(record(2)).encode()+b'\n'
    p.write_bytes(one+two[:20]);reader=IncrementalJournal(p,IDENTITY,2**20)
    assert len(reader.read())==1 and reader.sequence==1 and reader.tail
    with p.open('ab') as f:f.write(two[20:])
    assert len(reader.read())==1 and not reader.tail and reader.read()==[]
    with p.open('ab') as f:f.write(two)
    with pytest.raises(ValueError,match='sequence'):reader.read()

@pytest.mark.parametrize('mutation',[lambda d:d.update(sequence=True),lambda d:d.update(kind='arbitrary'),lambda d:d['data'].update(worker_PID=False),lambda d:d['data'].update(extra='unknown')])
def test_strict_progress_schema_rejects(mutation):
    d=record(1);mutation(d)
    with pytest.raises(ValueError):validate_progress(d,IDENTITY,1)

class FakeOwnedJob:
    calls=[];started=threading.Event();hold=False;bad_cleanup=False
    def __init__(self,cmd,cwd,env,out,err):
        self.pid=123;self.closed=False;self.assigned_before_resume=True;type(self).calls.append(self);type(self).started.set()
        assert cmd[1:4]==['-B','-m','ops_sim.v5.project_worker'] and env['PYTHONDONTWRITEBYTECODE']=='1'
    def state(self):return dict(job_active_PIDs=[123] if self.hold else [],job_active_count=int(self.hold))
    def poll(self):return None if self.hold else 0
    def reap(self,kill=False,**kwargs):
        self.kill=kill;self.closed=True
        return dict(owned_job_empty=not self.bad_cleanup,root_signaled=True,root_status_captured=True,handles_closed=True,errors=[],cleanup_within_two_seconds=True,root_exit_code=0)

def setup_runner(tmp_path,factory=FakeOwnedJob):
    root=make_inputs(wire='weakness');store=ProjectStore(tmp_path/'store',root,create=True);p=store.create(SpacecraftProject(root,project_source_identity()))
    store.preview(p['project_id'],p['revision']);runner=ProjectRunner(store,job_factory=factory)
    FakeOwnedJob.calls=[];FakeOwnedJob.started.clear();return store,p,runner

def test_exit_zero_without_science_is_incomplete_and_duplicate_does_not_launch(tmp_path):
    FakeOwnedJob.hold=False;FakeOwnedJob.bad_cleanup=False;store,p,r=setup_runner(tmp_path)
    j=r.submit(p['project_id'],p['revision'],'1'*32);r.thread.join(3)
    assert store.job(j['job_id'])['status']=='INCOMPLETE' and store.job(j['job_id'])['result'] is None
    r.submit(p['project_id'],p['revision'],'1'*32);assert len(FakeOwnedJob.calls)==1
    r.close()

def test_stop_shutdown_settle_only_owned_handle_and_close_dispatch(tmp_path):
    FakeOwnedJob.hold=True;FakeOwnedJob.bad_cleanup=False;store,p,r=setup_runner(tmp_path)
    j=r.submit(p['project_id'],p['revision'],'1'*32);assert FakeOwnedJob.started.wait(3)
    r.stop(j['job_id']);r.close()
    assert FakeOwnedJob.calls[0].kill and store.job(j['job_id'])['status']=='CANCELLED'
    with pytest.raises(ValueError,match='closed'):r.submit(p['project_id'],p['revision'],'2'*32)
    FakeOwnedJob.hold=False

def test_invalid_owned_cleanup_remains_unknown_and_blocks_dispatch(tmp_path):
    FakeOwnedJob.hold=False;FakeOwnedJob.bad_cleanup=True;store,p,r=setup_runner(tmp_path)
    j=r.submit(p['project_id'],p['revision'],'1'*32);r.thread.join(3)
    assert store.job(j['job_id'])['status']=='UNKNOWN'
    with pytest.raises(ValueError):r.submit(p['project_id'],p['revision'],'2'*32)
    with pytest.raises(RuntimeError):r.close()
    FakeOwnedJob.bad_cleanup=False
