"""Task-owned suspended Windows launch, inherited Job containment, finite reaping."""
import ctypes,os,subprocess,time
from ctypes import wintypes as W
K=ctypes.WinDLL('kernel32',use_last_error=True)
SIZE=ctypes.c_size_t;ULL=ctypes.c_ulonglong
class IO(ctypes.Structure):_fields_=[(n,ULL) for n in ['ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount']]
class BASIC(ctypes.Structure):_fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),('LimitFlags',W.DWORD),('MinimumWorkingSetSize',SIZE),('MaximumWorkingSetSize',SIZE),('ActiveProcessLimit',W.DWORD),('Affinity',SIZE),('PriorityClass',W.DWORD),('SchedulingClass',W.DWORD)]
class EXT(ctypes.Structure):_fields_=[('BasicLimitInformation',BASIC),('IoInfo',IO),('ProcessMemoryLimit',SIZE),('JobMemoryLimit',SIZE),('PeakProcessMemoryUsed',SIZE),('PeakJobMemoryUsed',SIZE)]
class ACCOUNT(ctypes.Structure):_fields_=[('TotalUserTime',ctypes.c_longlong),('TotalKernelTime',ctypes.c_longlong),('ThisPeriodTotalUserTime',ctypes.c_longlong),('ThisPeriodTotalKernelTime',ctypes.c_longlong),('TotalPageFaultCount',W.DWORD),('TotalProcesses',W.DWORD),('ActiveProcesses',W.DWORD),('TotalTerminatedProcesses',W.DWORD)]
class START(ctypes.Structure):_fields_=[('cb',W.DWORD),('lpReserved',W.LPWSTR),('lpDesktop',W.LPWSTR),('lpTitle',W.LPWSTR),('dwX',W.DWORD),('dwY',W.DWORD),('dwXSize',W.DWORD),('dwYSize',W.DWORD),('dwXCountChars',W.DWORD),('dwYCountChars',W.DWORD),('dwFillAttribute',W.DWORD),('dwFlags',W.DWORD),('wShowWindow',W.WORD),('cbReserved2',W.WORD),('lpReserved2',ctypes.POINTER(ctypes.c_byte)),('hStdInput',W.HANDLE),('hStdOutput',W.HANDLE),('hStdError',W.HANDLE)]
class PROC(ctypes.Structure):_fields_=[('hProcess',W.HANDLE),('hThread',W.HANDLE),('dwProcessId',W.DWORD),('dwThreadId',W.DWORD)]
def api(name,args,ret):
 f=getattr(K,name);f.argtypes=args;f.restype=ret;return f
createjob=api('CreateJobObjectW',[ctypes.c_void_p,W.LPCWSTR],W.HANDLE)
setjob=api('SetInformationJobObject',[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD],W.BOOL)
queryjob=api('QueryInformationJobObject',[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD)],W.BOOL)
createproc=api('CreateProcessW',[W.LPCWSTR,W.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,W.BOOL,W.DWORD,ctypes.c_void_p,W.LPCWSTR,ctypes.POINTER(START),ctypes.POINTER(PROC)],W.BOOL)
assign=api('AssignProcessToJobObject',[W.HANDLE,W.HANDLE],W.BOOL)
resume=api('ResumeThread',[W.HANDLE],W.DWORD)
close=api('CloseHandle',[W.HANDLE],W.BOOL)
wait=api('WaitForSingleObject',[W.HANDLE,W.DWORD],W.DWORD)
exitcode=api('GetExitCodeProcess',[W.HANDLE,ctypes.POINTER(W.DWORD)],W.BOOL)
terminatejob=api('TerminateJobObject',[W.HANDLE,W.UINT],W.BOOL)
terminateproc=api('TerminateProcess',[W.HANDLE,W.UINT],W.BOOL)
def require(ok,what):
 if not ok:raise OSError(ctypes.get_last_error(),what)
class OwnedJob:
 def __init__(self,cmd,cwd,env,out,err):
  import msvcrt
  self.job=createjob(None,None);require(self.job,'CreateJobObjectW')
  self.process=None;self.pid=None;self.closed=False;self.assigned_before_resume=False
  limits=EXT();limits.BasicLimitInformation.LimitFlags=0x2000
  require(setjob(self.job,9,ctypes.byref(limits),ctypes.sizeof(limits)),'Job KILL_ON_JOB_CLOSE')
  self.null=open('NUL','rb');handles=[msvcrt.get_osfhandle(f.fileno()) for f in [self.null,out,err]]
  for h in handles:os.set_handle_inheritable(h,True)
  si=START();si.cb=ctypes.sizeof(si);si.dwFlags=0x100;si.hStdInput,si.hStdOutput,si.hStdError=handles
  pi=PROC();line=ctypes.create_unicode_buffer(subprocess.list2cmdline(cmd))
  environment=ctypes.create_unicode_buffer('\0'.join(k+'='+str(v) for k,v in sorted(env.items(),key=lambda x:x[0].upper()))+'\0\0')
  try:
   require(createproc(None,line,None,None,True,0x4|0x400|0x08000000,environment,str(cwd),ctypes.byref(si),ctypes.byref(pi)),'CreateProcessW suspended')
   self.process=pi.hProcess;self.pid=pi.dwProcessId
   if not assign(self.job,self.process):
    error=ctypes.get_last_error();terminateproc(self.process,0xE0000002);wait(self.process,2000)
    raise OSError(error,'Assign suspended task process to private Job')
   self.assigned_before_resume=True
   require(resume(pi.hThread)!=0xFFFFFFFF,'ResumeThread')
  except BaseException:
   if self.assigned_before_resume:terminatejob(self.job,0xE0000002)
   if self.process:wait(self.process,2000);close(self.process)
   close(self.job);self.closed=True;raise
  finally:
   if pi.hThread:close(pi.hThread)
   for h in handles:os.set_handle_inheritable(h,False)
   self.null.close()
 def state(self):
  buf=ctypes.create_string_buffer(8192);returned=W.DWORD()
  require(queryjob(self.job,3,buf,len(buf),ctypes.byref(returned)),'Query owned Job PID list')
  count=W.DWORD.from_buffer(buf,4).value;assert count<=1023
  ids=list((SIZE*count).from_buffer(buf,8))
  account=ACCOUNT();require(queryjob(self.job,1,ctypes.byref(account),ctypes.sizeof(account),None),'Query owned Job accounting')
  return {'job_active_PIDs':ids,'job_active_count':account.ActiveProcesses,'job_total_processes':account.TotalProcesses,
   'job_all_owned_processes_CPU_seconds':(account.TotalUserTime+account.TotalKernelTime)/1e7,
   'CPU_scope':'all processes in this private Job; not worker-only CPU',
   'root_launch_PID':self.pid,'assigned_suspended_before_execution':self.assigned_before_resume}
 def poll(self):
  v=wait(self.process,0)
  if v==0:
   c=W.DWORD();require(exitcode(self.process,ctypes.byref(c)),'Root exit status');return c.value
  if v==258:return None
  raise OSError(ctypes.get_last_error(),'Wait root process')
 def reap(self,kill=False,max_seconds=2.,cleanup_deadline=None):
  # One absolute deadline for both Job-empty observation and root signaling.
  t=time.perf_counter();end=t+min(2.,max(0.,max_seconds))
  if cleanup_deadline is not None:end=min(end,cleanup_deadline)
  result={'cleanup_started_monotonic':t,'cleanup_deadline_monotonic':end,
   'cleanup_allowance_seconds':max(0.,end-t),'before':None,'after':None,
   'owned_job_empty':False,'root_signaled':False,'root_status_captured':False,
   'root_exit_code':None,'root_reaped':False,'job_terminated':False,'errors':[],
   'root_wait_return':None,'root_wait_api_error':None,'root_status_api_error':None,
   'stage_timings':{}}
  try:
   stage=time.perf_counter();before=self.state();result['before']=before
   result['stage_timings']['before_query_seconds']=time.perf_counter()-stage
   if kill and (before['job_active_count'] or before['job_active_PIDs']):
    stage=time.perf_counter();ok=terminatejob(self.job,0xE0000001)
    error=None if ok else ctypes.get_last_error() # capture before any next API
    result['terminate_job_api_success']=bool(ok);result['terminate_job_api_error']=error
    result['job_terminated']=bool(ok)
    result['stage_timings']['terminate_job_seconds']=time.perf_counter()-stage
    if not ok:result['errors'].append({'operation':'TerminateJobObject','error':error})
   stage=time.perf_counter()
   while True:
    after=self.state();result['after']=after
    empty=after['job_active_count']==0 and not after['job_active_PIDs']
    if empty or time.perf_counter()>=end:break
    time.sleep(min(.01,max(0.,end-time.perf_counter())))
   result['owned_job_empty']=empty
   result['job_empty_observed_monotonic']=time.perf_counter() if empty else None
   result['stage_timings']['job_empty_observation_seconds']=time.perf_counter()-stage
   remaining=max(0.,end-time.perf_counter());milliseconds=min(0xFFFFFFFE,int(remaining*1000))
   result['root_wait_milliseconds']=milliseconds
   stage=time.perf_counter();value=wait(self.process,milliseconds)
   error=ctypes.get_last_error() if value==0xFFFFFFFF else None
   result['root_wait_return']=value;result['root_wait_api_error']=error
   result['stage_timings']['root_wait_seconds']=time.perf_counter()-stage
   if value==0: # WAIT_OBJECT_0 proves signal; status is a distinct observation.
    result['root_signaled']=True;result['root_signal_observed_monotonic']=time.perf_counter()
    stage=time.perf_counter();code=W.DWORD();ok=exitcode(self.process,ctypes.byref(code))
    error=None if ok else ctypes.get_last_error()
    result['root_status_api_success']=bool(ok);result['root_status_api_error']=error
    result['root_status_captured']=bool(ok);result['root_exit_code']=code.value if ok else None
    result['root_status_observed_monotonic']=time.perf_counter() if ok else None
    result['stage_timings']['root_status_seconds']=time.perf_counter()-stage
    if not ok:result['errors'].append({'operation':'GetExitCodeProcess','error':error})
   elif value==258: # WAIT_TIMEOUT: no status success can substitute for a signal.
    result['errors'].append({'operation':'WaitForSingleObject','result':'WAIT_TIMEOUT'})
   elif value==0xFFFFFFFF:
    result['errors'].append({'operation':'WaitForSingleObject','result':'WAIT_FAILED','error':error})
   else:result['errors'].append({'operation':'WaitForSingleObject','unexpected_return':value})
   result['root_reaped']=result['root_signaled'] and result['root_status_captured']
  except BaseException as error:
   result['errors'].append({'operation':'reap','exception':type(error).__name__+': '+str(error)})
  finally:
   # Observe first, close second; no exception path restarts the cleanup allowance.
   result['handle_close_started_monotonic']=time.perf_counter();stage=time.perf_counter()
   closures=[]
   for name,handle in [('root_process',self.process),('private_job',self.job)]:
    ok=close(handle);error=None if ok else ctypes.get_last_error()
    closures.append({'handle':name,'closed':bool(ok),'api_error':error})
   result['handle_closures']=closures;result['handles_closed']=all(x['closed'] for x in closures)
   self.closed=result['handles_closed'];result['stage_timings']['close_handles_seconds']=time.perf_counter()-stage
   result['cleanup_wall_seconds']=time.perf_counter()-t
   result['cleanup_within_two_seconds']=result['cleanup_wall_seconds']<=2.
  return result
