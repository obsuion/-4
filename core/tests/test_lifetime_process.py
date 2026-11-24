from io import BytesIO
import pytest
from ops_sim.v5.lifecycle_process import OwnedPosixGroup

def test_monitor_failure_without_explicit_kill_still_settles_retained_child(monkeypatch):
    class Held:
        alive=True
        stdin=BytesIO();stdout=BytesIO();stderr=BytesIO()
        def poll(self):return None if self.alive else 0
        def kill(self):self.alive=False
        def wait(self,timeout):assert not self.alive;return 0
    g=object.__new__(OwnedPosixGroup);g.process=Held();g.token='a'*32;g.closed=False
    g.state=lambda:(_ for _ in ()).throw(PermissionError('monitor'))
    monkeypatch.setattr('ops_sim.v5.lifecycle_process.os.killpg',lambda *a:(_ for _ in ()).throw(AssertionError('guessed group')),raising=False)
    r=g.reap(kill=False)
    assert r['root_kill_attempted']and r['root_reaped']and r['handles_closed']
    assert not r['owned_job_empty']and not g.closed and r['primary_error']
    assert all(x.closed for x in (g.process.stdin,g.process.stdout,g.process.stderr))
