"""Fixed Linux worker gate; no model imports or work before opaque handshake."""
import json,os,sys
from pathlib import Path
from .lifetime_io_accounting import fsync

def main():
    path,token,*arguments=sys.argv[1:]
    if len(token)!=32 or any(c not in '0123456789abcdef'for c in token):raise ValueError('owner token')
    if not arguments or arguments[0]not in ('worker','fixture'):raise ValueError('fixed worker')
    d=dict(token=token,pid=os.getpid(),ppid=os.getppid(),pgrp=os.getpgrp(),session=os.getsid(0))
    raw=json.dumps(d).encode()
    if len(raw)>1024:raise ValueError('prospective Linux handshake byte cap')
    with Path(path).open('xb') as f:f.write(raw);f.flush();fsync(f.fileno())
    if sys.stdin.buffer.readline(34)!=(token+'\n').encode('ascii'):raise RuntimeError('parent gate EOF/token')
    if arguments[0]=='fixture':
        from .lifecycle_process import protocol_fixture
        if len(arguments)!=2:raise ValueError('fixed fixture arguments')
        return protocol_fixture(arguments[1])
    from .lifecycle_application import main as worker_main
    sys.argv=['lifecycle_application',*arguments];worker_main()

if __name__=='__main__':main()
