"""B60 cooperative Linux scope, separate from the unchanged Windows Job.

This is NOT a cgroup or security boundary. Only our fixed, cooperative workers
and descendants that remain in the created session are supported. Reopen never
reacquires a PID. Unknown /proc or identity prevents signaling and reports UNKNOWN.
"""
from pathlib import Path
import json, os, signal, subprocess, sys, time, uuid


def linux_stat(text):
    end=text.rfind(')'); pid=int(text[:text.index(' ')])
    rest=text[end+2:].split()
    if end<0 or len(rest)<22:raise ValueError('Linux stat fields')
    return dict(pid=pid,state=rest[0],ppid=int(rest[1]),pgrp=int(rest[2]),
                session=int(rest[3]),start_ticks=int(rest[19]))


def linux_memory(text):
    rows={}
    for line in text.splitlines():
        if line.startswith(('VmRSS:', 'VmHWM:')):
            key,n,unit=line.split()
            if unit!='kB' or not n.isdecimal():raise ValueError('Linux RSS units')
            rows[key[:-1]]=int(n)*1024
    if set(rows)!={'VmRSS','VmHWM'} or rows['VmHWM']<rows['VmRSS']:
        raise ValueError('Linux RSS fields unavailable')
    return dict(status='AVAILABLE',method='LINUX_PROC_SELF_STATUS',
                current_rss_bytes=rows['VmRSS'],peak_rss_bytes=rows['VmHWM'],error=None)


def memory_sample():
    try:return linux_memory(Path('/proc/self/status').read_text('ascii'))
    except (OSError,ValueError) as e:
        return dict(status='UNAVAILABLE',method='LINUX_PROC_SELF_STATUS',
                    current_rss_bytes=None,peak_rss_bytes=None,error=repr(e))


def owned_factory():
    if os.name=='nt':
        from .project_windows_job import OwnedJob
        return OwnedJob
    if sys.platform.startswith('linux'):return OwnedPosixGroup
    raise RuntimeError('UNSUPPORTED_OWNED_PROCESS_PLATFORM')


def admit_group(records,known,root,start,declared):
    """Pure membership admission; never take over a recycled, anchorless group."""
    for pid,ticks in {**declared,**known}.items():
        s=records.get(pid)
        if s is not None and (s['start_ticks']!=ticks or s['pgrp']!=root or s['session']!=root):
            raise RuntimeError('Linux known identity reused/escaped UNKNOWN')
    live_anchor=any(pid in records and records[pid]['start_ticks']==ticks and records[pid]['state']!='Z'
                    for pid,ticks in {**declared,**known}.items())
    members=[]
    for pid,s in records.items():
        if s['pgrp']!=root or s['session']!=root:continue
        if s['start_ticks']<start:raise RuntimeError('foreign Linux group member UNKNOWN')
        if s['state']=='Z':continue
        if pid not in known and pid not in declared and not live_anchor:
            raise RuntimeError('unverified anchorless Linux group UNKNOWN')
        known[pid]=s['start_ticks'];members.append(pid)
    return sorted(members)


class OwnedPosixGroup:
    """Popen-compatible runner adapter; one opaque token, one live owned scope."""
    def __init__(self,cmd,cwd,env,out,err,*,_fixture=False):
        if not sys.platform.startswith('linux'):raise RuntimeError('LINUX_BACKEND_NOT_THIS_RUNTIME')
        if type(_fixture)is not bool:raise TypeError('fixture selector')
        fixed=(type(cmd)is list and len(cmd)>=5 and cmd[1:4]==['-B','-m','ops_sim.v5.lifecycle_application'])
        if not fixed or (cmd[4]!='worker' and not (_fixture and cmd[4]=='fixture' and len(cmd)==6 and cmd[5]in FIXTURES)):
            raise ValueError('fixed lifecycle entrypoint required')
        self.token=uuid.uuid4().hex;self.closed=False;self.assigned_before_resume=False
        self.parent=os.getpid();self.known={};self.pid=None;self.root_start=None
        temp=Path(env['TMP']);self.identity=temp/('linux-owned-'+self.token+'.json')
        self.declarations=temp/('linux-descendants-'+self.token+'.json')
        from .lifetime_physical_storage import register_producer_path
        register_producer_path(self.identity);register_producer_path(self.declarations)
        env=dict(env,B60_OWNED_DECLARATIONS=str(self.declarations),B60_OWNER_TOKEN=self.token)
        actual=[cmd[0],'-B','-m','ops_sim.v5.lifecycle_posix_worker',str(self.identity),self.token,*cmd[4:]]
        self.process=subprocess.Popen(actual,cwd=cwd,env=env,stdin=subprocess.PIPE,
            stdout=out,stderr=err,shell=False,start_new_session=True,close_fds=True)
        self.pid=self.process.pid
        deadline=time.monotonic()+1
        try:
            while not self.identity.exists():
                if self.process.poll() is not None or time.monotonic()>=deadline:raise RuntimeError('Linux handshake unavailable')
                time.sleep(.005)
            d=json.loads(self.identity.read_bytes());s=self._stat(self.pid)
            if d!={'token':self.token,'pid':self.pid,'ppid':self.parent,'pgrp':self.pid,'session':self.pid}:
                raise RuntimeError('Linux launch handshake identity')
            if (s['ppid'],s['pgrp'],s['session'])!=(self.parent,self.pid,self.pid):raise RuntimeError('Linux /proc launch identity')
            self.root_start=s['start_ticks'];self.known[self.pid]=self.root_start
            self.assigned_before_resume=True
            self.process.stdin.write((self.token+'\n').encode('ascii'));self.process.stdin.flush();self.process.stdin.close()
        except BaseException as original:
            # A directly created Popen child is owned even before handshake.
            # Do not signal a guessed group on failed admission.
            end=time.perf_counter()+2;receipt=dict(root_PID=self.pid,token=self.token,scope='DIRECT_CREATED_PREGATE_ROOT_ONLY',errors=[])
            try:self.process.kill()
            except BaseException as e:receipt['errors'].append(repr(e))
            try:
                receipt['exit_code']=self.process.wait(timeout=max(0,end-time.perf_counter()))
                receipt['root_reaped']=True
            except BaseException as e:
                receipt['errors'].append(repr(e));receipt['root_reaped']=False
            try:
                if self.process.stdin and not self.process.stdin.closed:self.process.stdin.close()
            except BaseException as e:receipt['errors'].append(repr(e))
            self.closed=receipt['root_reaped']
            receipt.update(cleanup_deadline_monotonic=end,cleanup_within_two_seconds=time.perf_counter()<=end)
            error=RuntimeError('Linux launch admission failed; owned cleanup '+repr(receipt));error.owned_cleanup=receipt
            raise error from original

    @staticmethod
    def _stat(pid):return linux_stat(Path('/proc',str(pid),'stat').read_text('ascii'))

    def state(self):
        if self.closed:raise RuntimeError('closed owned Linux scope')
        declared={}
        if self.declarations.exists():
            if self.declarations.stat().st_size>16384:raise RuntimeError('Linux declaration quota UNKNOWN')
            d=json.loads(self.declarations.read_bytes())
            if type(d)is not dict or set(d)!={'token','root','children'}or type(d['token'])is not str or d['token']!=self.token or type(d['root'])is not int or d['root']!=self.pid or type(d['children'])is not list or len(d['children'])>16:
                raise RuntimeError('Linux child declarations UNKNOWN')
            for child in d['children']:
                if type(child)is not dict or set(child)!={'pid','start_ticks'}or any(type(v)is not int or v<1 for v in child.values())or child['pid']in declared:
                    raise RuntimeError('Linux declaration identity UNKNOWN')
                declared[child['pid']]=child['start_ticks']
        records={}
        for path in Path('/proc').iterdir():
            deadline=getattr(self,'_cleanup_scan_deadline',None)
            if deadline is not None and time.perf_counter()>=deadline:raise TimeoutError('Linux monitor cleanup deadline')
            if not path.name.isdecimal():continue
            try:s=self._stat(int(path.name))
            except FileNotFoundError:continue
            records[s['pid']]=s
        active=admit_group(records,self.known,self.pid,self.root_start,declared)
        return dict(job_active_PIDs=sorted(active),job_active_count=len(active),
            job_total_processes=len(self.known),job_all_owned_processes_CPU_seconds=None,
            CPU_scope='UNAVAILABLE_GROUP_CPU; actual worker CPU is reported by worker',
            root_launch_PID=self.pid,assigned_suspended_before_execution=False,
            backend='B60_COOPERATIVE_LINUX_SESSION_V1',security_isolation=False,
            ownership_scope='FIXED_COOPERATIVE_DESCENDANTS_REMAINING_IN_CREATED_SESSION',owner_token=self.token)

    def poll(self):return self.process.poll()

    def reap(self,kill=False,max_seconds=2.,cleanup_deadline=None):
        """Monitor failure cannot relinquish our directly retained Popen child.

        A failed scan never authorizes guessed group signaling. Root settlement
        and descendant proof are independent. Unproved scope stays UNKNOWN and
        repeated cleanup remains available while root/scope is unsettled.
        """
        start=time.perf_counter()
        if type(max_seconds) not in (int,float) or not __import__('math').isfinite(max_seconds):
            raise ValueError('finite cleanup allowance')
        end=start+min(2.,max(0.,max_seconds))
        if cleanup_deadline is not None:
            if type(cleanup_deadline) not in (int,float) or not __import__('math').isfinite(cleanup_deadline):
                raise ValueError('finite absolute cleanup deadline')
            end=min(end,cleanup_deadline)
        r=dict(cleanup_started_monotonic=start,cleanup_deadline_monotonic=end,
            root_exit_code=None,root_signaled=False,root_status_captured=False,
            root_reaped=False,root_kill_attempted=False,root_cleanup_complete=False,
            owned_job_empty=False,descendant_ownership='UNKNOWN',handles_closed=False,
            errors=[],primary_error=None,secondary_cleanup_errors=[],owner_token=self.token,
            backend='B60_COOPERATIVE_LINUX_SESSION_V1',security_isolation=False)
        def error(exc):
            value=repr(exc);r['errors'].append(value)
            if r['primary_error'] is None:r['primary_error']=value
            else:r['secondary_cleanup_errors'].append(value)
        monitor_ok=False
        self._cleanup_scan_deadline=end
        try:
            if getattr(self,'_scope_proved_empty',False):
                r['owned_job_empty']=True;r['descendant_ownership']='PROVED_EMPTY'
            elif time.perf_counter()<end:
                try:
                    r['before']=self.state();monitor_ok=True
                    if kill and r['before']['job_active_PIDs']:
                        for pid in r['before']['job_active_PIDs']:
                            if time.perf_counter()>=end:raise TimeoutError('Linux signal admission deadline')
                            st=self._stat(pid)
                            if st['start_ticks']!=self.known[pid] or st['pgrp']!=self.pid or st['session']!=self.pid:
                                raise RuntimeError('Linux signal ownership UNKNOWN')
                        os.killpg(self.pid,signal.SIGKILL)
                except BaseException as exc:error(exc)
            # Direct-created retained child authority survives ALL scan errors.
            # No PID/name lookup, fallback group signal or ownership substitution.
            code=None
            try:code=self.process.poll()
            except BaseException as exc:error(exc)
            if code is None and (kill or r['primary_error'] is not None):
                r['root_kill_attempted']=True
                try:self.process.kill()
                except ProcessLookupError:pass
                except BaseException as exc:error(exc)
            try:
                code=self.process.wait(timeout=max(0.,end-time.perf_counter()))
                r['root_exit_code']=code;r['root_reaped']=True
                r['root_signaled']=r['root_status_captured']=True
                r['root_cleanup_complete']=True
            except BaseException as exc:error(exc)
            if monitor_ok and not r['owned_job_empty']:
                while time.perf_counter()<end:
                    try:
                        r['after']=self.state()
                        if not r['after']['job_active_PIDs']:
                            r['owned_job_empty']=True;r['descendant_ownership']='PROVED_EMPTY';break
                    except BaseException as exc:error(exc);break
                    time.sleep(min(.005,max(0.,end-time.perf_counter())))
            if not r['owned_job_empty']:r['errors'].append('UNKNOWN_UNSETTLED_COOPERATIVE_SCOPE')
        finally:
            try:
                streams=[getattr(self.process,n,None)for n in ('stdin','stdout','stderr')]
                for stream in streams:
                    if stream is not None and not stream.closed:
                        try:stream.close()
                        except BaseException as exc:error(exc)
                r['handles_closed']=all(stream is None or stream.closed for stream in streams)
            except BaseException as exc:error(exc)
            if r['root_reaped'] and r['owned_job_empty'] and r['handles_closed'] and not self.declarations.exists():
                try:
                    # The optional declaration has no writer after proved
                    # scope closure. Retire only its proven absent placeholder.
                    from .lifetime_physical_storage import retire_producer_path
                    retire_producer_path(self.declarations)
                except BaseException as exc:error(exc)
            self._cleanup_scan_deadline=None
            self._scope_proved_empty=r['owned_job_empty']
            self.closed=r['root_reaped'] and r['owned_job_empty'] and r['handles_closed']
            r['adapter_closed']=self.closed
            r['cleanup_wall_seconds']=time.perf_counter()-start
            r['cleanup_within_two_seconds']=r['cleanup_wall_seconds']<=2
            r['cleanup_within_deadline']=time.perf_counter()<=end
            self._last_cleanup=dict(r)
        return r


FIXTURES=('normal','exception','child_first_exit','held_stdout','timeout','parent_report_exception')

def protocol_fixture(name):
    """Fixed nonnumerical Linux acceptance fixture; never selected by a job."""
    if name not in FIXTURES:raise ValueError('fixture')
    if name in ('child_first_exit','held_stdout'):
        child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(0.25)'],shell=False)
        s=OwnedPosixGroup._stat(child.pid)
        d=dict(token=os.environ['B60_OWNER_TOKEN'],root=os.getpid(),children=[dict(pid=child.pid,start_ticks=s['start_ticks'])])
        raw=json.dumps(d).encode('utf8')
        if len(raw)>16384:raise ValueError('prospective Linux declaration byte cap')
        from .lifetime_io_accounting import fsync
        with Path(os.environ['B60_OWNED_DECLARATIONS']).open('xb')as f:f.write(raw);f.flush();fsync(f.fileno())
        if name=='held_stdout':child.wait(timeout=1)
    elif name=='timeout':time.sleep(3)
    elif name=='exception':raise RuntimeError('EXPECTED_PROTOCOL_FIXTURE_EXCEPTION')
