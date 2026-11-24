"""Fixed-record graph codec for locally generated advanced state, never user input.

No executable payload types, paths, imports or callbacks. Immutable root references
are opaque hashes resolved only in a caller-supplied, already bound root.
"""
from dataclasses import fields, is_dataclass
from fractions import Fraction
from hashlib import sha256
from enum import Enum
import json, math
from ._snapshot_records import (RECORD_FIELDS, RECORDS, ENUMS, validate_schema, GroundPointGeometry,
    restore_ground_geometry,GroundVisibilityResult,restore_ground_visibility)
from .experiment_codec import parse_json, object_fields
from .rolling_cache import canonical_size

MAX_BYTES = 128*2**20
MAX_NODES = 262144
MAX_ITEMS = 65536
MAX_DEPTH = 64
FORMAT = 'B51_FIXED_ADVANCED_GRAPH_V1'
CONTROL_ALLOWANCE = 16*9*MAX_NODES+2*((MAX_BYTES+63)//64)

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))

class GraphCodec:
    def __init__(self, root):
        validate_schema()
        self.roots={}; self.root_ids={}; self.visits=0
        def index(v, path, depth):
            self.visits+=1
            if self.visits>MAX_NODES or depth>32: raise ValueError('immutable root index bound')
            if type(v) in (str,int,float,bool,type(None),Fraction) or isinstance(v,Enum): return
            if is_dataclass(v) or type(v) is tuple:
                key=sha256(canonical(path).encode()).hexdigest()
                self.roots[key]=v; self.root_ids.setdefault(id(v),key)
                children=((f.name,getattr(v,f.name)) for f in fields(v)) if is_dataclass(v) else enumerate(v)
                for k,x in children:index(x,(*path,k),depth+1)
        index(root,('root',),0)
        self.units=0

    def encode(self, value):
        nodes=[]; memo={}; active=set(); self.units=0;prospective_bytes=0
        def charge(token):
            nonlocal prospective_bytes
            # Conservative construction precharge, distinct from exact final
            # byte length. Stops scalar growth before a large parent allocation.
            prospective_bytes+=len(canonical(token).encode())+4
            if prospective_bytes>MAX_BYTES:raise ValueError('snapshot construction byte allowance')
            return token
        def enc(v, depth):
            self.units+=1
            if self.units>8*MAX_NODES or depth>MAX_DEPTH:raise ValueError('snapshot traversal bound')
            t=type(v)
            if v is None:return charge(['none'])
            if t is bool:return charge(['bool',v])
            if t is int:
                if v.bit_length()>4096:raise ValueError('snapshot integer bound')
                return charge(['int',str(v)])
            if t is float:
                if not math.isfinite(v):raise ValueError('finite snapshot float')
                return charge(['float',v.hex()])
            if t is str:
                if len(v.encode('utf-8'))>2**20:raise ValueError('snapshot string bound')
                return charge(['str',v])
            if t is Fraction:return charge(['rational',str(v.numerator),str(v.denominator)])
            if isinstance(v,Enum):
                name=t.__module__+'.'+t.__name__
                if ENUMS.get(name) is not t:raise TypeError('snapshot enum allowlist')
                return charge(['enum',name,v.name])
            if id(v) in self.root_ids:return charge(['root',self.root_ids[id(v)]])
            if id(v) in active:raise ValueError('snapshot cycles forbidden')
            if id(v) in memo:return charge(['ref',memo[id(v)]])
            if len(nodes)>=MAX_NODES:raise ValueError('snapshot node bound')
            n=len(nodes);memo[id(v)]=n;nodes.append(None);active.add(id(v))
            charge(['node-overhead',n,t.__name__])
            if t in (tuple,list):
                if len(v)>MAX_ITEMS:raise ValueError('snapshot sequence bound')
                node=['tuple' if t is tuple else 'list',[enc(x,depth+1) for x in v]]
            elif t is dict:
                if len(v)>MAX_ITEMS or any(type(k) not in (str,int,Fraction) for k in v):raise ValueError('snapshot map bound/keys')
                pairs=[[enc(k,depth+1),enc(x,depth+1)] for k,x in v.items()]
                pairs.sort(key=lambda p:canonical(p[0]));node=['map',pairs]
            elif t in RECORD_FIELDS:
                node=['record',t.__module__+'.'+t.__name__,[enc(getattr(v,k),depth+1) for k in RECORD_FIELDS[t]]]
            else:raise TypeError('unsupported snapshot owner: '+str(t))
            active.remove(id(v));nodes[n]=node
            return charge(['ref',n])
        value=enc(value,0)
        graph=dict(format=FORMAT,version=1,value=value,nodes=nodes)
        canonical_size(graph,MAX_BYTES)
        return graph

    def decode(self, graph):
        object_fields(graph,('format','version','value','nodes'))
        if graph['format']!=FORMAT or type(graph['version']) is not int or graph['version']!=1:raise ValueError('snapshot graph version')
        nodes=graph['nodes']
        if type(nodes) is not list or len(nodes)>MAX_NODES:raise ValueError('snapshot node bound')
        done={};active=set();self.units=0
        def integer(s):
            if type(s) is not str or len(s)>1235:raise ValueError('snapshot integer spelling')
            v=int(s)
            if str(v)!=s or v.bit_length()>4096:raise ValueError('noncanonical integer')
            return v
        def dec(v,depth):
            self.units+=1
            if self.units>8*MAX_NODES or depth>MAX_DEPTH or type(v) is not list or not v or type(v[0]) is not str:raise ValueError('bounded snapshot token')
            tag=v[0]
            if tag=='none' and len(v)==1:return None
            if tag=='bool' and len(v)==2 and type(v[1]) is bool:return v[1]
            if tag=='int' and len(v)==2:return integer(v[1])
            if tag=='str' and len(v)==2 and type(v[1]) is str and len(v[1].encode())<=2**20:return v[1]
            if tag=='float' and len(v)==2 and type(v[1]) is str:
                x=float.fromhex(v[1])
                if not math.isfinite(x) or x.hex()!=v[1]:raise ValueError('noncanonical finite float')
                return x
            if tag=='rational' and len(v)==3:
                a,b=integer(v[1]),integer(v[2])
                if b<=0:raise ValueError('positive rational denominator')
                q=Fraction(a,b)
                if (q.numerator,q.denominator)!=(a,b):raise ValueError('noncanonical rational')
                return q
            if tag=='enum' and len(v)==3 and type(v[1]) is str and type(v[2]) is str and v[1] in ENUMS:
                return ENUMS[v[1]][v[2]]
            if tag=='root' and len(v)==2 and type(v[1]) is str and v[1] in self.roots:return self.roots[v[1]]
            if tag!='ref' or len(v)!=2 or type(v[1]) is not int or not 0<=v[1]<len(nodes):raise ValueError('snapshot token allowlist')
            n=v[1]
            if n in active:raise ValueError('snapshot cycle')
            if n in done:return done[n]
            active.add(n);node=nodes[n]
            if type(node) is not list or not node:raise ValueError('snapshot node schema')
            kind=node[0]
            if kind in ('tuple','list') and len(node)==2 and type(node[1]) is list and len(node[1])<=MAX_ITEMS:
                xs=[dec(x,depth+1) for x in node[1]];result=tuple(xs) if kind=='tuple' else xs
            elif kind=='map' and len(node)==2 and type(node[1]) is list and len(node[1])<=MAX_ITEMS:
                result={};last=None
                for pair in node[1]:
                    if type(pair) is not list or len(pair)!=2:raise ValueError('snapshot map pair')
                    order=canonical(pair[0])
                    if last is not None and order<=last:raise ValueError('snapshot map ordering')
                    k=dec(pair[0],depth+1)
                    if type(k) not in (str,int,Fraction) or k in result:raise ValueError('snapshot map duplicate/key')
                    result[k]=dec(pair[1],depth+1);last=order
            elif kind=='record' and len(node)==3 and type(node[1]) is str and node[1] in RECORDS and type(node[2]) is list:
                owner=RECORDS[node[1]];names=RECORD_FIELDS[owner]
                if len(node[2])!=len(names):raise ValueError('snapshot record fields')
                values=dict(zip(names,(dec(x,depth+1) for x in node[2])))
                if owner is GroundPointGeometry:result=restore_ground_geometry(values)
                elif owner is GroundVisibilityResult:result=restore_ground_visibility(values)
                else:result=owner(**values)
            else:raise ValueError('snapshot node allowlist')
            active.remove(n);done[n]=result;return result
        result=dec(graph['value'],0)
        if len(done)!=len(nodes):raise ValueError('unreachable snapshot nodes')
        return result

def parse_snapshot(raw):
    if type(raw) is not bytes or not 0<len(raw)<=MAX_BYTES:raise ValueError('snapshot bytes')
    value=parse_json(raw.decode('utf-8'))
    canonical_size(value,MAX_BYTES)
    if canonical(value).encode()!=raw:raise ValueError('noncanonical snapshot JSON')
    return value

def admit_graph_structure(graph):
    """Data-only admission before compilation/dispatch; invokes no record owner."""
    object_fields(graph,('format','version','value','nodes'))
    if graph['format']!=FORMAT or type(graph['version']) is not int or graph['version']!=1 or type(graph['nodes']) is not list or len(graph['nodes'])>MAX_NODES:raise ValueError('snapshot graph structure/version')
    def token(v):
        if type(v) is not list or not v or type(v[0]) is not str:raise ValueError('snapshot structural token')
        tag=v[0]
        if tag=='ref' and len(v)==2 and type(v[1]) is int and 0<=v[1]<len(graph['nodes']):return
        if tag=='root' and len(v)==2 and type(v[1]) is str and len(v[1])==64 and all(c in '0123456789abcdef' for c in v[1]):return
        if tag=='none' and len(v)==1:return
        if tag=='bool' and len(v)==2 and type(v[1]) is bool:return
        if tag=='str' and len(v)==2 and type(v[1]) is str and len(v[1].encode())<=2**20:return
        if tag=='int' and len(v)==2 and type(v[1]) is str and len(v[1])<=1235 and str(int(v[1]))==v[1] and int(v[1]).bit_length()<=4096:return
        if tag=='float' and len(v)==2 and type(v[1]) is str:
            f=float.fromhex(v[1])
            if math.isfinite(f) and f.hex()==v[1]:return
        if tag=='rational' and len(v)==3 and all(type(x) is str and len(x)<=1235 for x in v[1:]):
            a,b=map(int,v[1:])
            if b>0 and [str(a),str(b)]==v[1:] and max(abs(a).bit_length(),b.bit_length())<=4096:
                q=Fraction(a,b)
                if (q.numerator,q.denominator)==(a,b):return
        if tag=='enum' and len(v)==3 and type(v[1]) is str and type(v[2]) is str and v[1] in ENUMS and v[2] in ENUMS[v[1]].__members__:return
        raise ValueError('noncanonical/unknown snapshot structural token')
    token(graph['value'])
    for node in graph['nodes']:
        if type(node) is not list or not node:raise ValueError('snapshot structural node')
        kind=node[0]
        if kind in ('list','tuple') and len(node)==2 and type(node[1]) is list and len(node[1])<=MAX_ITEMS:
            for x in node[1]:token(x)
        elif kind=='map' and len(node)==2 and type(node[1]) is list and len(node[1])<=MAX_ITEMS:
            last=None
            for pair in node[1]:
                if type(pair) is not list or len(pair)!=2:raise ValueError('snapshot map structural pair')
                for x in pair:token(x)
                if pair[0][0] not in ('str','int','rational'):raise ValueError('snapshot map structural key')
                key=canonical(pair[0])
                if last is not None and key<=last:raise ValueError('snapshot map structural order')
                last=key
        elif kind=='record' and len(node)==3 and type(node[1]) is str and node[1] in RECORDS and type(node[2]) is list and len(node[2])==len(RECORD_FIELDS[RECORDS[node[1]]]):
            for x in node[2]:token(x)
        else:raise ValueError('unknown snapshot structural node')
    # Bounded iterative cycle/depth/reachability check, without constructors.
    done=set();active=set();todo=[(graph['value'],0,False)]
    while todo:
        v,depth,leave=todo.pop()
        if depth>MAX_DEPTH:raise ValueError('snapshot graph structural depth')
        if v[0]!='ref':continue
        n=v[1]
        if leave:active.remove(n);done.add(n);continue
        if n in active:raise ValueError('snapshot graph structural cycle')
        if n in done:continue
        active.add(n);todo.append((v,depth,True));node=graph['nodes'][n]
        children=node[2] if node[0]=='record' else [x for pair in node[1] for x in pair] if node[0]=='map' else node[1]
        todo.extend((x,depth+1,False) for x in reversed(children))
    if len(done)!=len(graph['nodes']):raise ValueError('snapshot structural unreachable nodes')
    return graph
