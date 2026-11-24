"""Finite NONNUMERICAL native Linux acceptance, NOT_RUN on Windows.

Run: python -B -m examples.m8_linux_acceptance --output NEW_EXTERNAL_DIRECTORY
No scientific evaluations, installs, network, unowned signals or old-PID
reacquisition. Package __init__ imports config/simulator; import is not evaluation.
At most six owned groups, execution <=2 seconds each, shared cleanup <=2 each,
whole <=30 seconds. The independent sentinel is never a group member.
"""
import argparse,json,os,subprocess,sys,time
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not sys.platform.startswith('linux'):raise RuntimeError('ACTUAL_POSIX_NOT_RUN_THIS_PLATFORM')
    a.output.mkdir(parents=True,exist_ok=False)
    from ops_sim.v5.lifecycle_process import OwnedPosixGroup,FIXTURES,memory_sample
    start=time.perf_counter();records=[]
    sentinel=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'],shell=False,start_new_session=True)
    try:
        for mode in FIXTURES:
            if time.perf_counter()-start+4>30:raise RuntimeError('FINITE_PROTOCOL_SEQUENCE_REMAINDER')
            with (a.output/(mode+'.out')).open('xb')as out,(a.output/(mode+'.err')).open('xb')as err:
                env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',TMP=str(a.output),TEMP=str(a.output))
                owned=OwnedPosixGroup([sys.executable,'-B','-m','ops_sim.v5.lifecycle_application','fixture',mode],Path.cwd(),env,out,err,_fixture=True)
                deadline=time.perf_counter()+2;timeout=False
                try:
                    while owned.poll()is None or owned.state()['job_active_count']:
                        if time.perf_counter()>=deadline:timeout=True;break
                        time.sleep(.01)
                finally:
                    receipt=owned.reap(kill=timeout,max_seconds=2,cleanup_deadline=time.perf_counter()+2)
                    # Durable settlement precedes deliberately failing parent report.
                    with (a.output/(mode+'.settled.json')).open('x')as f:json.dump(receipt,f);f.flush();os.fsync(f.fileno())
                if mode=='parent_report_exception':
                    try:raise RuntimeError('EXPECTED_PARENT_REPORT_EXCEPTION')
                    except RuntimeError as e:records.append(dict(mode=mode,expected_error=str(e)))
                assert sentinel.poll()is None
                assert receipt['owned_job_empty']and receipt['root_status_captured']and receipt['handles_closed']and not receipt['errors']
                assert receipt['cleanup_within_two_seconds']
                records.append(dict(mode=mode,timeout=timeout,receipt=receipt,sentinel_preserved=True))
        result=dict(status='PASS_NATIVE_LINUX_COOPERATIVE_SCOPE',records=records,memory=memory_sample(),seconds=time.perf_counter()-start)
        (a.output/'RESULT.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        # Only the explicitly created sentinel handle, after preservation proof.
        sentinel.terminate();sentinel.wait(timeout=2)

if __name__=='__main__':main()
