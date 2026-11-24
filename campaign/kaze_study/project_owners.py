"""Locally registered executable closures. Imported paths never register owners."""
from pathlib import Path
from .data import read, read_bytes, digest, identity, inside
from .errors import Refusal

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_SHA256 = '9a990a94fc57919ddda96707d1114880a7a57d920d255169497c7ae878f6ffe0'

def registered(compiler=None, adapter=None):
    raw=read_bytes(ROOT/'fixtures/registered-owners.json')
    if digest(raw)!=REGISTRY_SHA256:raise Refusal('REGISTERED_OWNER_REGISTRY_DRIFT')
    from .data import parse
    profiles=parse(raw)
    matches=[dict(v,adapter=k) for k,v in profiles.items()
             if (compiler is None or v['compiler']==compiler) and (adapter is None or k==adapter)]
    if len(matches)!=1:raise Refusal('UNTRUSTED_COMPILER_REVISION_REQUIRES_VERSIONED_ADAPTER')
    p=matches[0]
    if identity(p['files'])!=p['compiler']:raise Refusal('REGISTERED_OWNER_CLOSURE_PIN')
    return p

def verify_implementation(profile):
    root=ROOT/profile['trusted_root']
    actual={p.relative_to(root).as_posix() for p in (root/'kaze_designs').rglob('*') if p.is_file()}
    if actual!=set(profile['files']):raise Refusal('TRUSTED_COMPILER_MEMBERSHIP')
    for name,pin in profile['files'].items():
        if digest(read_bytes(inside(root,name)))!=pin:raise Refusal('TRUSTED_COMPILER_FILE_DRIFT',name)
    return root
