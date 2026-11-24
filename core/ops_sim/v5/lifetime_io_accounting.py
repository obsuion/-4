"""Bounded administrative durability-call counts, separate from scientific work.

SQLite counts explicit application COMMIT, not internal filesystem syscalls.
"""
import os
from threading import Lock
_LIMIT=2**40
_LOCK=Lock()
_COUNTS={n:0 for n in ('fsync_attempted','fsync_completed','fsync_failed',
    'directory_fsync_attempted','directory_fsync_completed','directory_fsync_failed',
    'sqlite_commit_attempted','sqlite_commit_completed','sqlite_commit_failed')}
def _increment(name):
    with _LOCK:
        if _COUNTS[name]>=_LIMIT:raise ValueError('YEAR_V4 administrative IO count ceiling')
        _COUNTS[name]+=1
def fsync(fd,*,directory=False):
    if type(directory)is not bool:raise TypeError('exact directory flag')
    prefix='directory_fsync'if directory else 'fsync'
    _increment(prefix+'_attempted')
    try:value=os.fsync(fd)
    except BaseException:
        _increment(prefix+'_failed');raise
    _increment(prefix+'_completed');return value
def sqlite_commit(call):
    _increment('sqlite_commit_attempted')
    try:value=call()
    except BaseException:
        _increment('sqlite_commit_failed');raise
    _increment('sqlite_commit_completed');return value
def snapshot():
    with _LOCK:counts=dict(_COUNTS)
    for prefix in ('fsync','directory_fsync','sqlite_commit'):
        if counts[prefix+'_completed']+counts[prefix+'_failed']>counts[prefix+'_attempted']:
            raise ValueError('YEAR_V4 administrative IO count balance')
    return dict(format='YEAR_V4_PROCESS_DURABILITY_CALLS_V1',PID=os.getpid(),limit=_LIMIT,counts=counts,
        scope='EXPLICIT_PRODUCTION_WRAPPER_CALLS_NOT_SQLITE_INTERNAL_OR_KERNEL_SYSCALL_COUNTS',reset_available=False)
