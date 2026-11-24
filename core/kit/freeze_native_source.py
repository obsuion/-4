"""Finalize exact membership after a platform build, before execution freeze.

Run only in an explicit external source copy. No model imports or calculations.
The resulting raw source identity must be rebound; existing stores never migrate.
"""
from pathlib import Path
import argparse,json,hashlib
def finalize(source):
    source=Path(source).resolve();owner=source/'ops_sim/v5/lifetime_source.py'
    if (source/'.git').exists():raise ValueError('B65 freeze refuses a Git checkout')
    paths=[]
    for p in sorted(source.rglob('*')):
        if p.is_symlink():raise ValueError('B65 source links forbidden')
        if p.is_file():
            n=p.relative_to(source).as_posix()
            if any(x in('.git','.venv','__pycache__','.pytest_cache')for x in p.relative_to(source).parts):raise ValueError('B65 source cache/metadata pollution')
            if p.suffix in('.lib','.pdb','.o','.obj'):raise ValueError('B65 move build intermediates outside source before freeze')
            paths.append(n)
    if not 1<=len(paths)<=1024:raise ValueError('B65 finite source membership')
    prefix=owner.read_text('utf8').split('\nB63_SOURCE_PATHS = ',1)[0]
    owner.write_text(prefix+'\nB63_SOURCE_PATHS = '+repr(tuple(paths))+'\nB64_SOURCE_PATHS = B63_SOURCE_PATHS\nB65_SOURCE_PATHS = B63_SOURCE_PATHS\n',encoding='utf8',newline='\n')
    manifest={n:dict(bytes=(source/n).stat().st_size,sha256=hashlib.sha256((source/n).read_bytes()).hexdigest())for n in paths}
    return dict(format='B65_FINALIZED_SOURCE_MEMBERSHIP_V1',files=len(manifest),source_identity=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest(),manifest=manifest)
def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists()or a.output.resolve().is_relative_to(a.source.resolve()):raise ValueError('B65 new external source receipt required')
    value=finalize(a.source);a.output.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8');print(value['source_identity'])
if __name__=='__main__':main()
