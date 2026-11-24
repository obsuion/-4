"""YEAR-V2 immutable, bounded, lossless status field objects (DATA only).

The complete legacy job remains the logical authority. Identical large fields
are published once per job; references commit both encoded and decoded bytes.
Objects are never garbage-collected while any historical head can refer to them.
"""
import json,zlib,re
from hashlib import sha256

METHOD='YEAR_V2_LOSSLESS_STATUS_FIELD_OBJECTS_V1'
OBJECT='YEAR_V2_ZLIB_CANONICAL_FIELD_V1'
LIMIT=256*1024
MAX_OBJECTS=32

def raw(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')

def parse(data):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('duplicate immutable object key')
            d[k]=v
        return d
    value=json.loads(data,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite object')))
    if raw(value)!=data:raise ValueError('noncanonical immutable object')
    return value

def reference(value):
    if type(value)is not dict or set(value)!={'format','path','decoded_sha256','decoded_bytes','sha256','bytes'}:
        raise ValueError('exact immutable field reference')
    for n in ('decoded_sha256','sha256'):
        if type(value[n])is not str or re.fullmatch('[0-9a-f]{64}',value[n])is None:raise ValueError('field object digest')
    for n in ('decoded_bytes','bytes'):
        if type(value[n])is not int or not 1<=value[n]<=LIMIT:raise ValueError('bounded field object bytes')
    if value['format']!=OBJECT or value['path']!='objects/'+value['decoded_sha256']+'.zjson':raise ValueError('field object path/version')
    return value

def decode(ref,data):
    reference(ref)
    if type(data)is not bytes or len(data)!=ref['bytes']or sha256(data).hexdigest()!=ref['sha256']:raise ValueError('encoded field object binding')
    d=zlib.decompressobj();result=d.decompress(data,ref['decoded_bytes']+1)
    if len(result)!=ref['decoded_bytes']or not d.eof or d.unused_data or d.unconsumed_tail or sha256(result).hexdigest()!=ref['decoded_sha256']:raise ValueError('decoded field object binding/tail')
    return parse(result)

def prepare(job):
    # Check whole logical population before encoding individual field objects.
    if type(job)is not dict or len(job)>MAX_OBJECTS or len(raw(job))>LIMIT:raise ValueError('bounded whole job')
    fields={};objects={}
    for name,value in job.items():
        data=raw(value)
        if len(data)<512:
            fields[name]={'inline':value};continue
        encoded=zlib.compress(data,6)
        ref=dict(format=OBJECT,path='objects/'+sha256(data).hexdigest()+'.zjson',decoded_sha256=sha256(data).hexdigest(),decoded_bytes=len(data),sha256=sha256(encoded).hexdigest(),bytes=len(encoded))
        reference(ref);decode(ref,encoded)
        fields[name]={'object':ref};objects[ref['path']]=encoded
    return fields,tuple(sorted(objects.items()))

def restore(fields,read):
    if type(fields)is not dict or len(fields)>MAX_OBJECTS:raise ValueError('bounded field population')
    job={};total=0
    for name,value in fields.items():
        if type(name)is not str or type(value)is not dict:raise ValueError('strict field name/record')
        if set(value)=={'inline'}:
            if len(raw(value['inline']))>=512:raise ValueError('large inline field')
            job[name]=value['inline']
        elif set(value)=={'object'}:
            ref=reference(value['object']);total+=ref['decoded_bytes']
            if total>LIMIT:raise ValueError('aggregate decoded field bound')
            job[name]=decode(ref,read(ref))
        else:raise ValueError('strict inline/object choice')
    if len(raw(job))>LIMIT:raise ValueError('decoded whole job bound')
    return job
