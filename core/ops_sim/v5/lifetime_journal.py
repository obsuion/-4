"""Immutable bounded supervisor journal and OS-held lease. No PID adoption."""
from .lifetime_io_accounting import fsync as _io_fsync
from contextlib import contextmanager
from pathlib import Path
from hashlib import sha256
import json,os,sys

def encoded(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')

def publish(path,value,limit):
    p=Path(path);raw=encoded(value)
    if len(raw)>limit:raise ValueError('B62 immutable publication cap')
    if p.is_symlink()or p.exists():raise ValueError('B62 new publication required')
    from .lifetime_physical_storage import register_producer_path,retire_producer_path
    pending=p.with_suffix('.pending')
    register_producer_path(p);register_producer_path(pending,additional_bytes=len(raw))
    p.parent.mkdir(parents=True,exist_ok=True)
    with pending.open('xb')as f:f.write(raw);f.flush();_io_fsync(f.fileno())
    os.rename(pending,p)
    retire_producer_path(pending)
    if sys.platform.startswith('linux'):
        fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:_io_fsync(fd)
        finally:os.close(fd)

@contextmanager
def lease(path,*,windows=False):
    p=Path(path)
    if p.is_symlink():raise ValueError('B62 lease link')
    from .lifetime_physical_storage import register_producer_path
    register_producer_path(p)
    p.parent.mkdir(parents=True,exist_ok=True)
    f=p.open('a+b')
    try:
        if sys.platform=='win32' and windows:
            import msvcrt
            f.seek(0,2)
            if f.tell()==0:f.write(b'0');f.flush()
            f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        elif sys.platform.startswith('linux'):
            import fcntl
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        else:raise ValueError('B62 actual supported OS lease required')
        yield f
    finally:f.close() # OS releases only this retained handle's lock.

class Journal:
    ACTIONS={'DISPATCH','SETTLED','HALT','EXPLICIT_CONTINUE','RECOVER_SETTLED','DIAGNOSTIC','DIAGNOSTIC_SETTLED','NO_LAUNCH_DISPOSITION','NO_LAUNCH_RECOVERY'}
    def __init__(self,store,plan):
        self.store=store;self.plan=plan;self.folder=store.path('lifetime-journal')
        self.sequence=0;self.previous='0'*64
        for record in self.records():self.sequence=record['sequence'];self.previous=sha256(encoded(record)).hexdigest()
    def _files(self):
        if not self.folder.exists():return []
        files=sorted(self.folder.iterdir())
        if len(files)>self.store.runner_policy.maximum_journal_records:raise ValueError('B62 journal population')
        for n,p in enumerate(files,1):
            if p.is_symlink()or p.name!=f'{n:08}.json':raise ValueError('B62 incomplete/foreign journal; preserve without retry')
        return files
    def records(self):
        previous='0'*64
        for n,p in enumerate(self._files(),1):
            if p.stat().st_size>self.store.runner_policy.maximum_journal_record_bytes:raise ValueError('B62 journal record cap')
            raw=p.read_bytes();v=json.loads(raw)
            if type(v)is not dict or set(v)!={'format','sequence','previous_sha256','plan_identity','action','data'}or v['format']!='B62_DURABLE_SUPERVISOR_JOURNAL_V1' or type(v['sequence'])is not int or v['sequence']!=n or v['previous_sha256']!=previous or v['plan_identity']!=self.plan['plan_identity']or v['action']not in self.ACTIONS or encoded(v)!=raw:raise ValueError('B62 journal schema/hash/sequence')
            previous=sha256(raw).hexdigest();yield v
    def append(self,action,data):
        if action not in self.ACTIONS or self.sequence>=self.store.runner_policy.maximum_journal_records:raise ValueError('B62 journal admission')
        v=dict(format='B62_DURABLE_SUPERVISOR_JOURNAL_V1',sequence=self.sequence+1,previous_sha256=self.previous,plan_identity=self.plan['plan_identity'],action=action,data=data)
        publish(self.folder/f'{self.sequence+1:08}.json',v,self.store.runner_policy.maximum_journal_record_bytes)
        self.sequence+=1;self.previous=sha256(encoded(v)).hexdigest();return v
