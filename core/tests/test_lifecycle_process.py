import sys
import pytest
from ops_sim.v5.lifecycle_process import linux_memory,linux_stat,OwnedPosixGroup,owned_factory

def test_linux_memory_units_not_windows_or_fake_zero():
    x=linux_memory('Name: worker\nVmRSS: 123 kB\nVmHWM: 256 kB\n')
    assert x['current_rss_bytes']==125952 and x['peak_rss_bytes']==262144

@pytest.mark.parametrize('text',['','VmRSS: 1 bytes\nVmHWM: 2 kB','VmRSS: 3 kB\nVmHWM: 2 kB'])
def test_linux_bad_or_unavailable_memory(text):
    with pytest.raises(ValueError):linux_memory(text)

def test_proc_stat_comm_may_contain_spaces_and_parentheses():
    rest=['S','11','22','22']+['0']*15+['123456']+['0']*3
    d=linux_stat('22 (a weird ) comm) '+' '.join(rest))
    assert d==dict(pid=22,state='S',ppid=11,pgrp=22,session=22,start_ticks=123456)

def test_current_backend_and_wrong_platform_refusal():
    if sys.platform=='win32':
        from ops_sim.v5.project_windows_job import OwnedJob
        assert owned_factory()is OwnedJob
        with pytest.raises(RuntimeError,match='NOT_THIS_RUNTIME'):OwnedPosixGroup([],None,{},None,None)


def test_membership_requires_live_anchor_or_bound_declaration():
    from ops_sim.v5.lifecycle_process import admit_group
    def record(pid,start=100,group=10,state='S'):
        return dict(pid=pid,ppid=1,pgrp=group,session=group,start_ticks=start,state=state)
    known={10:100}
    with pytest.raises(RuntimeError,match='anchorless'):
        admit_group({11:record(11,101)},known,10,100,{})
    assert admit_group({11:record(11,101)},known,10,100,{11:101})==[11]
    assert known=={10:100,11:101}
    with pytest.raises(RuntimeError,match='reused/escaped'):
        admit_group({11:record(11,102)},known,10,100,{11:101})
    with pytest.raises(RuntimeError,match='reused/escaped'):
        admit_group({11:record(11,101,group=20)},known,10,100,{11:101})


def test_current_live_root_binds_its_cooperative_group_not_other_sessions():
    from ops_sim.v5.lifecycle_process import admit_group
    root=dict(pid=10,ppid=1,pgrp=10,session=10,start_ticks=100,state='S')
    child=dict(pid=11,ppid=10,pgrp=10,session=10,start_ticks=101,state='S')
    unrelated=dict(pid=12,ppid=1,pgrp=12,session=12,start_ticks=102,state='S')
    assert admit_group({10:root,11:child,12:unrelated},{10:100},10,100,{})==[10,11]


# B61 PL-R1 fake-held-Popen regressions: no real proc/handle operation here.
from io import BytesIO
from types import SimpleNamespace
import subprocess

class HeldRoot:
    def __init__(self,*,alive=True,kill_error=None,wait_error=None,poll_error=None):
        self.alive=alive;self.kill_error=kill_error;self.wait_error=wait_error;self.poll_error=poll_error
        self.kill_called=0;self.wait_called=0;self.stdin=BytesIO()
    def poll(self):
        if self.poll_error:raise self.poll_error
        return None if self.alive else 0
    def kill(self):
        self.kill_called+=1
        if self.kill_error:raise self.kill_error
        self.alive=False
    def wait(self,timeout):
        self.wait_called+=1
        if self.wait_error:raise self.wait_error
        if self.alive:raise subprocess.TimeoutExpired('fake owned root',timeout)
        return 0

def group_with(root,error):
    g=object.__new__(OwnedPosixGroup);g.process=root;g.token='a'*32;g.closed=False;g.known={10:100};g.pid=10
    def broken():raise error
    g.state=broken
    return g

@pytest.mark.parametrize('error',[PermissionError('foreign proc'),PermissionError('owned proc'),ValueError('malformed proc'),ValueError('malformed declaration'),RuntimeError('identity refusal'),RuntimeError('anchor refusal')])
def test_scan_error_still_reaps_retained_root_and_does_not_signal_guessed_group(monkeypatch,error):
    root=HeldRoot();g=group_with(root,error)
    monkeypatch.setattr('ops_sim.v5.lifecycle_process.os.killpg',lambda *a:(_ for _ in ()).throw(AssertionError('guessed group')),raising=False)
    r=g.reap(kill=True)
    assert root.kill_called==root.wait_called==1 and r['root_reaped'] and r['root_cleanup_complete']
    assert not r['owned_job_empty'] and r['descendant_ownership']=='UNKNOWN' and not g.closed
    assert r['primary_error']==repr(error) and r['handles_closed']
    again=g.reap(kill=True);assert again['root_reaped'] and root.wait_called==2

def test_root_exit_race_reaped_despite_scan_failure():
    root=HeldRoot(alive=False);r=group_with(root,PermissionError('scan')).reap(kill=True)
    assert root.kill_called==0 and root.wait_called==1 and r['root_reaped'] and not r['owned_job_empty']

@pytest.mark.parametrize('kind',['kill','wait','poll','close'])
def test_secondary_cleanup_errors_preserve_primary_and_retained_authority(kind):
    root=HeldRoot(kill_error=OSError('kill')if kind=='kill'else None,wait_error=OSError('wait')if kind=='wait'else None,poll_error=OSError('poll')if kind=='poll'else None)
    if kind=='close':
        class BadStream:
            closed=False
            def close(self):raise OSError('close')
        root.stdin=BadStream()
    g=group_with(root,PermissionError('primary'));r=g.reap(kill=True)
    assert r['primary_error']==repr(PermissionError('primary')) and r['secondary_cleanup_errors']
    assert root.wait_called==1 and not g.closed
    if kind=='poll':assert root.kill_called==1 and r['root_reaped']

def test_absolute_cleanup_deadline_does_not_expand_allowance():
    import time
    root=HeldRoot(wait_error=subprocess.TimeoutExpired('fake',0));g=group_with(root,PermissionError('scan'))
    d=time.perf_counter()-1;r=g.reap(kill=True,cleanup_deadline=d)
    assert r['cleanup_deadline_monotonic']==d and root.kill_called==1 and root.wait_called==1
    assert not r['root_reaped'] and not g.closed and not r['cleanup_within_deadline']

def test_successful_empty_proof_and_idempotent_root_reaping():
    root=HeldRoot(alive=False);g=group_with(root,ValueError('unused'));g.state=lambda:dict(job_active_PIDs=[])
    r=g.reap(kill=True);assert r['owned_job_empty'] and r['root_reaped'] and g.closed
    r=g.reap(kill=True);assert r['owned_job_empty'] and r['root_reaped'] and g.closed


@pytest.mark.parametrize('pid',[10,11])
def test_real_monitor_control_flow_with_denied_owned_or_foreign_proc(monkeypatch,tmp_path,pid):
    from pathlib import Path
    g=group_with(HeldRoot(),RuntimeError('unused'));del g.state
    g.root_start=100;g.declarations=tmp_path/'declarations.json'
    native=Path.iterdir
    monkeypatch.setattr(Path,'iterdir',lambda p:iter([Path('/proc')/str(pid)])if str(p).replace('\\','/')=='/proc'else native(p))
    def denied(n):raise PermissionError('denied PID '+str(n))
    g._stat=denied
    r=g.reap(kill=True)
    assert r['root_reaped'] and not r['owned_job_empty'] and g.process.kill_called==1
    assert 'PermissionError'in r['primary_error']

@pytest.mark.parametrize('declaration',[{'token':'a'*32,'root':10.,'children':[]},{'token':'a'*32,'root':10,'children':[{'pid':True,'start_ticks':100}]},{'token':'a'*32,'root':10,'children':[{}]}])
def test_monitor_bad_declaration_cannot_cancel_direct_root_cleanup(tmp_path,declaration):
    import json
    g=group_with(HeldRoot(),RuntimeError('unused'));del g.state
    g.declarations=tmp_path/'children.json';g.declarations.write_text(json.dumps(declaration));g.root_start=100
    r=g.reap(kill=True);assert r['root_reaped'] and not r['owned_job_empty'] and g.process.wait_called==1
    assert 'declaration'in r['primary_error']

def test_reporting_exception_does_not_resurrect_reaped_root():
    root=HeldRoot();g=group_with(root,PermissionError('monitor'));receipt=g.reap(kill=True)
    try:raise RuntimeError('expected final reporting failure')
    except RuntimeError:pass
    assert receipt['root_reaped'] and not root.alive and root.wait_called==1
