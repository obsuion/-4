"""B69 descriptor preparation; native comparisons retain the Python oracle.

Descriptors are invocation-owned strong graphs, not serialized receipts.
Only preparation loops over Python metadata. Production boundaries consume
private C arrays; old Python guards remain the explicit unprepared fallback.
"""
from dataclasses import fields
from enum import EnumMeta
from types import FunctionType,CodeType
from weakref import WeakKeyDictionary,ref
import os,threading,sys,dis,builtins
from types import ModuleType

METHOD='B69_COMPILED_EXACT_GUARD_PLAN_V1'
MAX_ROWS=262144
MAX_BYTES=128*2**20
MAX_SEQUENCE_ITEMS=65536
MAX_LIVE_PLANS=1024
MAX_LABEL=4096
_KEY=object()

class _Rows:
    __slots__=('rows','functions','owners','workspace')
    def __init__(self):
        self.rows=[];self.functions=set();self.owners=set();self.workspace=4096
    def add(self,kind,target,name=None,expected=None,extra=None,mode=0,label=''):
        if len(self.rows)>=MAX_ROWS:raise ValueError('B69 bounded compiled descriptor preparation')
        label=label or str(name)
        # Conservative peak descriptor-only workspace, NOT total Python heap/RSS.
        charge=512
        for value in (expected,extra):
            if type(value)is tuple:
                if len(value)>MAX_SEQUENCE_ITEMS:raise ValueError('B70 bounded descriptor sequence')
                charge+=128+64*len(value)
        for value in (name,label):
            if type(value)is str:
                if len(value)>MAX_LABEL:raise ValueError('B70 bounded descriptor text')
                charge+=128+8*len(value)
        if self.workspace+charge>MAX_BYTES//2:raise ValueError('B70 descriptor preparation peak limit')
        self.workspace+=charge
        self.rows.append((kind,target,name,expected,extra,mode,label))
    def attr(self,target,name,*,value=False,optional=False):
        previous=getattr(target,name,None)if optional else getattr(target,name)
        self.add(8 if optional else 3 if value else 2,target,name,previous)
        return previous
    def sequence(self,value,*,owner=None,name=None,mode=0):
        if type(value)is not tuple:raise TypeError('B69 canonical tuple descriptor source')
        self.add(4,value if owner is None else owner,name,value,mode=mode)
    def mapping(self,mapping,*,owner=None,name=None,identity=True,key_identity=False):
        if owner is not None and identity:self.attr(owner,name)
        if len(mapping)>MAX_SEQUENCE_ITEMS:raise ValueError('B70 bounded descriptor mapping')
        # Refuse before allocating keys/values snapshots, including transient list/set overhead.
        if self.workspace+1024+128*len(mapping)>MAX_BYTES//2:raise ValueError('B70 mapping preparation peak')
        keys=tuple(mapping.keys());values=tuple(mapping.values())
        self.add(5 if owner is None or identity else 6,mapping if owner is None or identity else owner,
                 None if owner is None or identity else name,keys,values,0 if key_identity else 1,label=name or 'mapping')
    def function(self,fn,depth=0):
        if depth>16:raise ValueError('B69 bounded callable closure preparation')
        if id(fn)in self.functions:return
        self.functions.add(id(fn))
        defaults=self.attr(fn,'__defaults__',optional=True)
        keywords=self.attr(fn,'__kwdefaults__',optional=True)
        self.attr(fn,'__code__',optional=True)
        if type(defaults)is tuple:self.sequence(defaults)
        if type(keywords)is dict:self.mapping(keywords)
        if type(fn)is FunctionType:
            closure=self.attr(fn,'__closure__')
            if closure is not None:
                self.sequence(closure)
                for cell in closure:
                    try:value=cell.cell_contents
                    except ValueError:self.add(7,cell,mode=1,label='empty closure cell');continue
                    self.add(7,cell,expected=value,label='closure cell')
                    if type(value)is FunctionType:self.function(value,depth+1)
    def bound_function(self,owner,name,fn=None,optional=False):
        current=self.attr(owner,name,optional=optional)
        if fn is not None and current is not fn:raise ValueError('B69 preparation callable drift')
        self.function(current)
    def owner(self,owner):
        if owner in self.owners:return
        self.owners.add(owner)
        self.attr(owner,'__module__',value=True);self.attr(owner,'__name__',value=True)
        self.sequence(owner.__mro__,owner=owner,name='__mro__')
        for name in ('__init__','__new__','__post_init__','__setattr__','__getattribute__'):
            self.bound_function(owner,name,optional=True)
        if isinstance(owner,EnumMeta):
            self.mapping(owner.__members__,owner=owner,name='__members__',identity=False)
            return
        self.mapping(owner.__dataclass_fields__,owner=owner,name='__dataclass_fields__')
        for f in fields(owner):
            self.attr(f,'name',value=True)
            for n in ('type','default','default_factory','init','repr','hash','compare','kw_only','metadata','_field_type'):
                self.attr(f,n,optional=n=='_field_type')
            self.mapping(f.metadata,key_identity=True)
        params=self.attr(owner,'__dataclass_params__',optional=True)
        for n in ('init','repr','eq','order','unsafe_hash','frozen','match_args','kw_only','slots','weakref_slot'):
            self.attr(params,n,optional=True)
    def result(self):return tuple(self.rows)

def _codec_rows(codec,out):
    from . import prepared_input_codec as pc
    from . import rolling_document as rd
    from . import spacecraft_project_v2_document as vd
    from . import spacecraft_project_v3_document as v3
    # Pin fresh declaration ORIGINS, not only the formerly captured classes.
    # The independent test derives this domain from retained oracle AST/imports.
    from . import command_estimation, lifecycle_contract, sun_table
    from . import spacecraft_project_v2, spacecraft_project_v3, spacecraft_project, design_repair
    for module in (rd,vd,v3,pc.typed,pc.registry,pc.long_doc,pc.construction_doc,pc.mass_doc):
        out.add(9,sys.modules,module.__name__,module,label='oracle module membership')
    for module,names in ((command_estimation,('CommandRollingRoot','EstimationPolicy')),
            (lifecycle_contract,('LifecycleRoot','LifecyclePolicy','LifecycleScenario')),
            (sun_table,('SunPositionSample','SunTableProvenance')),
            (pc.long_doc,('SunPositionTable','light','source_doc')),
            (pc.long_doc.light,('ZonotopeLocalIlluminationRequestV2',)),
            (pc.long_doc.source_doc,('ZonotopeLocalIlluminationPolicyV2','J2ZonotopeSegmentRequest')),
            (rd,('AssemblyDesign',)),(spacecraft_project_v2,('SpacecraftProjectV2',)),
            (spacecraft_project_v3,('SpacecraftProjectV3',)),(spacecraft_project,('ProjectLimits',)),
            (design_repair,('MissionRequirements',)),(v3,('DesignSpecificationV2','SpacecraftProjectV3'))):
        out.add(9,sys.modules,module.__name__,module,label='fresh declaration module origin')
        for name in names:out.attr(module,name)
    for name in ('typed','registry','long_doc','construction_doc','mass_doc','fields','EnumMeta'):
        out.attr(pc,name)
    for name in ('_owner_signature','_function_signature'):
        out.bound_function(pc,name)
    for name in ('_full_snapshot','owner','_guard_typed','canonical_content'):
        out.bound_function(pc.PreparedInputCodec,name)
    out.attr(pc,'PreparedInputCodec')
    out.attr(pc.typed,'fields')
    for owner,name in ((pc.typed,'RECORD_FIELDS'),(pc.registry,'RECORD_FIELDS'),
            (pc.typed,'ENUM_TYPES'),(pc.registry,'ENUM_TYPES'),
            (pc.typed,'_RECORDS'),(pc.typed,'_ENUMS'),
            (pc.long_doc,'_NEW'),(pc.long_doc,'_NEW_MAP'),
            (pc.construction_doc,'OWNERS'),(pc.construction_doc,'MAP'),
            (pc.mass_doc,'MAP'),(rd,'NEW'),(rd,'MAP'),(rd,'ENUMS'),
            (pc.long_doc,'_OLD_EXACT'),(pc.long_doc,'_OLD_PREFIXES'),
            (vd,'OWNERS'),(vd,'EXISTING'),(v3,'OWNERS')):
        v=out.attr(owner,name)
        if type(v)is dict:
            out.mapping(v,key_identity=any(type(k)is not str for k in v))
            if name=='RECORD_FIELDS':
                for names in v.values():out.sequence(names,mode=1)
        elif type(v)is tuple:
            out.sequence(v,mode=1 if name in('_OLD_EXACT','_OLD_PREFIXES')else 0)
        else:raise TypeError('B69 canonical registry descriptor')
    out.add(1,codec,expected=pc.PreparedInputCodec,label='exact codec owner')
    out.sequence(pc.PreparedInputCodec.__mro__,owner=pc.PreparedInputCodec,name='__mro__')
    out.mapping(vars(pc.PreparedInputCodec),owner=pc.PreparedInputCodec,name='__dict__',identity=False)
    for name in ('_seal','_owners','_functions','_retained'):
        value=out.attr(codec,name)
        if type(value)is dict:out.mapping(value,key_identity=True)
    for owner in codec._owners:out.owner(owner)
    for name in ('_encode','_decode','_integer','_text','object_fields','check_schema_coverage','_encode_reference','_decode_reference','_check_schema_coverage_reference'):
        out.bound_function(pc.typed,name)
    for m in (vd,v3):
        for name in ('specification_data','_decode','dumps_project','_dumps_project','loads_project','_loads_project'):
            out.bound_function(m,name)
    for owner,name in ((v3.DesignSpecificationV2,'identity'),(v3.DesignSpecificationV2,'declaration_identity'),
                       (v3.SpacecraftProjectV3,'identity'),(v3.SpacecraftProjectV3,'comparison_identity')):
        descriptor=out.attr(owner,name)
        for n in ('fget','fset','fdel'):
            f=out.attr(descriptor,n)
            if f is not None:out.function(f)
    for n in ('_ENCODE','_DECODE','_CHECK','_OBJECT','_ENCODE_REFERENCE','_DECODE_REFERENCE','_SCHEMA_REFERENCE','metadata','_META_CLASS','_META_NAMES','_META_ACTIVE','_META_BINDINGS'):
        out.attr(pc,n)
    out.attr(pc.metadata,'_Scope');out.attr(pc.metadata,'_ACTIVE');out.attr(pc.metadata,'_NAMES')
    out.sequence(pc.metadata._NAMES,mode=1)
    out.mapping(vars(pc.metadata._Scope),owner=pc.metadata._Scope,name='__dict__',identity=False)
    for owner,name,fn,code in pc._META_BINDINGS:out.bound_function(owner,name,fn)

def _relative_import_rows(out,fn):
    """Capture IMPORT_NAME + IMPORT_FROM, including CPython's circular fallback.

    The imported parent may expose an object distinct from sys.modules[name].
    Pin the resolved object, not attribute presence: deleting the attribute is
    legal when IMPORT_FROM's canonical sys.modules fallback returns that object.
    No imported object is executable authority outside this owned preparation.
    """
    for name in ('__package__','__name__','__spec__','__builtins__'):
        if name in fn.__globals__:
            out.add(9,fn.__globals__,name,fn.__globals__[name],label='import caller origin '+name)
    source=fn.__builtins__
    out.add(9,source,'__import__',builtins.__import__,label='original import implementation')
    codes=[fn.__code__]
    while codes:
        code=codes.pop();codes.extend(v for v in code.co_consts if type(v)is CodeType)
        ops=list(dis.get_instructions(code))
        for i,op in enumerate(ops):
            if op.opname!='IMPORT_NAME':continue
            if i<2 or ops[i-2].opname not in ('LOAD_CONST','LOAD_SMALL_INT') or ops[i-1].opname!='LOAD_CONST':
                raise ValueError('B71 unsupported import bytecode shape')
            level,fromlist=ops[i-2].argval,ops[i-1].argval
            if not level:continue
            if type(fromlist)is not tuple or not all(type(n)is str and n!='*'for n in fromlist):
                raise ValueError('B71 bounded explicit relative imports')
            module=builtins.__import__(op.argval,fn.__globals__,None,fromlist,level)
            if type(module)is not ModuleType:raise TypeError('B71 exact import origin module')
            out.add(9,sys.modules,module.__name__,module,label='IMPORT_NAME origin')
            out.attr(module,'__name__',value=True)
            for name in fromlist:
                fullname=module.__name__+'.'+name
                try:value=getattr(module,name)
                except AttributeError:value=sys.modules[fullname]
                out.add(11,module,name,value,(sys.modules,fullname),label='IMPORT_FROM '+fullname)
                if type(value)is ModuleType:
                    out.add(9,sys.modules,fullname,value,label='imported module canonical membership')
                    out.attr(value,'__name__',value=True)


def _schema_rows(schema):
    out=_Rows()
    for n in ('codec','functions','properties','retained','_pins'):out.attr(schema,n)
    _codec_rows(schema.codec,out)
    # Independently pin every resolved GLOBAL dependency of the retained oracle
    # roots, including aliases used by owner/function/generation helpers.
    from . import prepared_input_codec as pc, lifecycle_job_prepared as jp
    from .lifecycle_prepared import _Seal
    roots=(pc.PreparedInputCodec._full_snapshot,pc._owner_signature,pc._function_signature,
           jp._SchemaSeal.guard,_Seal.guard,jp._guard_generation_owner,jp._generation_function_state,fields,pc.typed.check_schema_coverage)
    for fn in roots:
        out.function(fn)
        _relative_import_rows(out,fn)
        codes=[fn.__code__];names=set()
        while codes:
            code=codes.pop();names.update(code.co_names)
            codes.extend(v for v in code.co_consts if type(v)is CodeType)
        for name in names:
            if name in fn.__globals__:
                value=fn.__globals__[name]
                out.add(9,fn.__globals__,name,value,label='oracle global '+name)
                if type(value)is FunctionType:out.function(value)
    from . import lifecycle_exact_guards as own
    for name in ('_Rows','ExactGuardSession','_KEY','METHOD','MAX_ROWS','MAX_BYTES','fields','EnumMeta','FunctionType','CodeType','WeakKeyDictionary','ref','os','threading','sys','MAX_SEQUENCE_ITEMS','MAX_LIVE_PLANS','MAX_LABEL','ModuleType','dis','builtins'):
        out.attr(own,name)
    out.attr(sys,'modules');out.attr(builtins,'__import__')
    out.bound_function(dis,'get_instructions')
    classes=set(owner for owner,name,fn,signature in schema.functions if isinstance(owner,type))
    for owner in classes:
        out.sequence(owner.__mro__,owner=owner,name='__mro__')
        out.mapping(vars(owner),owner=owner,name='__dict__',identity=False)
    for owner,name,function,signature in schema.functions:
        out.bound_function(owner,name,function)
    for owner,name,descriptor,accessors in schema.properties:
        out.attr(owner,name)
        for n in ('fget','fset','fdel'):
            f=out.attr(descriptor,n)
            if f is not None:out.function(f)
    return out.result()

def _graph_rows(seal):
    from .assembly_attitude import ComponentAxisBinding
    from fractions import Fraction
    out=_Rows()
    owner_ref=ref(seal)
    for name in ('edges','scalars','nodes'):
        out.add(10,owner_ref,name,getattr(seal,name),label='sealed descriptor owner '+name)
    for item,owner,mapping,schema,values in seal.edges:
        out.add(1,item,expected=owner,label='record type')
        out.attr(owner,'__dataclass_fields__')
        out.mapping(mapping)
        for name,field,declared_name,init in schema:
            out.attr(field,'name',value=True);out.attr(field,'init')
        for name,previous,init in values:
            if name=='_identity'and init is False:
                out.add(3,item,name,previous,label='canonical derived identity')
            elif owner is ComponentAxisBinding and name=='local_axis':
                out.add(4,item,name,previous,mode=2,label='canonical local axis')
            else:out.add(2,item,name,previous,label='record edge '+name)
    for kind,item,*previous in seal.scalars:
        if kind=='fraction':
            out.add(1,item,expected=Fraction,label='Fraction type')
            out.add(3,item,'numerator',previous[0],label='Fraction numerator')
            out.add(3,item,'denominator',previous[1],label='Fraction denominator')
        else:
            owner,name,value=previous
            out.add(1,item,expected=owner,label='Enum type')
            out.add(2,item,'name',name,label='Enum name')
            out.add(2,item,'value',value,label='Enum value')
            out.mapping(owner.__members__,owner=owner,name='__members__',identity=False)
    return out.result()

def _generation_rows(pin):
    from . import lifecycle_job_prepared as jp
    module=jp._generation_owner;owner=pin[0];out=_Rows()
    out.attr(jp,'_GENERATION_OWNER_BINDING')
    out.attr(module,'_Generation');out.attr(module,'__name__',value=True);out.attr(owner,'__bases__');out.attr(owner,'__mro__')
    out.mapping(vars(owner),owner=owner,name='__dict__',identity=False)
    for name,fn,state in pin[4]:out.bound_function(owner,name,fn)
    out.bound_function(module,'enable',pin[5])
    for name,value in pin[7]:out.attr(module,name)
    out.attr(jp,'_generation_owner')
    out.attr(jp.sys,'modules')
    out.add(9,jp.sys.modules,module.__name__,module,label='generation sys.modules origin')
    return out.result()

def _control_rows(session,job):
    """Independent native pre-dispatch closure; never dispatched by full/check."""
    out=_Rows()
    for name in ('_job','_native','_binding','_calls','_arena','_plans','_schema','_generation','_pins'):
        out.attr(session,name)
    for name in ('_guard_plan','_guard_plan_pin','_guard_gate','_guard_gate_pin','_guard_arena','_guard_binding','_guard_records_enabled'):
        out.attr(job,name)
    out.attr(job,'_binding');out.attr(job,'source_binding',value=True);out.attr(job,'_runtime')
    out.attr(job,'_admission_pins');admission=out.attr(job,'_admission')
    from . import lifecycle_job_prepared as jp
    for name in ('PreparedJobRuntime','_ThermalStaticAlias','_JOB_WORK_FIELDS','CONTROL_METHOD',
            'MAX_CONTROL_UNITS','_GENERATION_OWNER_BINDING','_generation_owner','_runtime'):
        value=out.attr(jp,name)
        if type(value)is FunctionType:out.function(value)
    out.sequence(jp._JOB_WORK_FIELDS,mode=1)
    for name in ('_raw','_raw_sha','_build_raw','_schema','_root_seal','_codec_receipt','_work','_binding'):
        out.attr(admission,name)
    for name in ('__file__','__name__','__loader__','__spec__'):
        out.attr(session._native,name)
    out.add(9,sys.modules,session._native.__name__,session._native,label='actual native module origin')
    from . import lifecycle_exact_guards as own
    for name in ('ExactGuardSession','_Rows','_control_rows','_schema_rows','_codec_rows','_graph_rows','_generation_rows','_record_capability','_identity_descriptor','_KEY','METHOD','MAX_ROWS','MAX_BYTES'):
        value=out.attr(own,name)
        if type(value)is FunctionType:out.function(value)
    for cls in (ExactGuardSession,_Rows,type(job)):
        out.sequence(cls.__mro__,owner=cls,name='__mro__')
        out.mapping(vars(cls),owner=cls,name='__dict__',identity=False)
        for name,fn in vars(cls).items():
            if type(fn)is FunctionType:out.bound_function(cls,name,fn)
    # Native export identities are also checked from private C state, not this tuple.
    for name,fn in session._calls:out.attr(session._native,name)
    return out.result()

def _record_capability():
    return dict(method='YEAR_V4_NATIVE_JOB_GUARD_RECORD_V1',per_job_records=1,
        record_reservation_bytes=65536,exact_generation_binding=True,
        fixed_native_owner_pins=True,dynamic_ledgers_checked=True,
        class_method_mro_closure_checks=True,legacy_fallback='STRICT_PYTHON_GUARDS',
        scientific_work='UNCHANGED',persistent=False)

def _identity_descriptor(job):
    """Once-only static DATA for private native job identity fields."""
    from . import lifecycle_job_prepared as jp
    return (jp.PreparedJobRuntime,jp._ThermalStaticAlias,jp._JOB_WORK_FIELDS,
        jp.CONTROL_METHOD,jp.MAX_CONTROL_UNITS,jp._GENERATION_OWNER_BINDING,
        jp._generation_owner,jp._runtime())

class ExactGuardSession:
    """Private one-job arena, weak owner index and strong native descriptors."""
    __slots__=('_job','_native','_binding','_calls','_arena','_plans','_schema',
               '_generation','_pins','_oracle_calls','__weakref__')
    def __init__(self,job,native,key):
        if key is not _KEY:raise TypeError('B69 private exact guard preparation')
        self._job=job;self._native=native
        self._binding=(self,job,job._binding,job.source_binding,job._runtime,os.getpid(),threading.get_ident())
        self._calls=tuple((n,getattr(native,n))for n in ('guard_plan_capability','make_guard_arena','compile_guard_plan','guard_exact_plans','guard_arena_receipt','close_guard_arena','bind_guard_dispatch','dispatch_exact_guard'))
        if hasattr(native,'guard_record_capability'):
            if native.guard_record_capability()!=_record_capability():raise ValueError('YEAR-V4 actual guard record capability')
            self._calls+=tuple((n,getattr(native,n))for n in ('guard_record_capability','guard_record_counts','bind_guard_identity','bind_guard_generation'))
        self._arena=native.make_guard_arena(self._binding);self._plans=WeakKeyDictionary()
        self._oracle_calls=0
        # Full Python oracle once before preparation, plus native differential
        # admission. Later boundaries never construct owner-signature tuples.
        job._schema.guard();self._oracle_calls+=1
        self._schema=self._prepare(job._schema,_schema_rows(job._schema))
        from .lifecycle_job_prepared import _GENERATION_OWNER_BINDING,_guard_generation_owner
        _guard_generation_owner();self._oracle_calls+=1
        self._generation=self._prepare(__import__(__package__+'.lifecycle_generation',fromlist=['*']),_generation_rows(_GENERATION_OWNER_BINDING))
        self._pins=(job,native,self._binding,self._calls,self._arena,self._plans,self._schema,self._generation)
    def _prepare(self,owner,rows):
        # Admission prepays conservative bounded workspace/control; fees remain
        # even on compilation/refusal. Native arena independently caps memory.
        self._job._charge(1024+len(rows)*2,'public_boundaries')
        return self._native.compile_guard_plan(self._arena,self._binding,owner,rows)
    def check(self,job):
        p=self._pins
        if job._closed:raise ValueError('B69 closed job exact guard session')
        if (type(self)is not ExactGuardSession or job is not p[0]or self._job is not p[0]or
                self._native is not p[1]or self._binding is not p[2]or self._calls is not p[3]or
                self._arena is not p[4]or self._plans is not p[5]or self._schema is not p[6]or self._generation is not p[7]):
            raise ValueError('B69 replaced exact guard session')
        if (self._binding[2]is not job._binding or self._binding[3]!=job.source_binding or
                self._binding[4]!=job._runtime or self._binding[5]!=os.getpid()or self._binding[6]!=threading.get_ident()):
            raise ValueError('B69 source/process/thread exact guard session')
        for name,fn in self._calls:
            if getattr(self._native,name)is not fn:raise ValueError('B69 changed compiled validation gate')
    def generation(self,pin):
        self.check(self._job)
        from . import lifecycle_job_prepared as jp
        if pin is not jp._GENERATION_OWNER_BINDING:raise ValueError('B69 generation pin owner')
        self._native.guard_exact_plans(self._arena,self._binding,((jp._generation_owner,self._generation),))
    def _plan(self,seal):
        plan=self._plans.get(seal)
        if plan is None:
            # First-use oracle is reference, not a per-boundary duplicate.
            seal.guard();self._oracle_calls+=1
            plan=self._prepare(seal,_graph_rows(seal));self._plans[seal]=plan
        return plan
    def full(self,transaction):
        j=self._job;self.check(j)
        j._schema.codec._charge('full_schema_scans')
        j._schema.codec._charge('full_owner_checks',len(j._schema.codec._owners))
        seals=[j._external_seal,j._owned_seal]
        for alias in j._thermal_aliases.values():
            alias.check(j,alias.network);seals.extend((alias.seal,alias.owner._seal))
        for role in j._roles.values():
            role._guard_identity()
            seals.extend(entry.seal for entry in role._cache.values())
        if transaction is not None:seals.extend(entry.seal for entry in transaction._entries.values())
        package=[(j._schema,self._schema)]
        seen=set()
        for seal in seals:
            if seal not in seen:package.append((seal,self._plan(seal)));seen.add(seal)
        self._native.guard_exact_plans(self._arena,self._binding,tuple(package))
    def graph(self,seal):
        self.check(self._job)
        self._native.guard_exact_plans(self._arena,self._binding,((seal,self._plan(seal)),))
    def receipt(self):
        self.check(self._job)
        return dict(self._native.guard_arena_receipt(self._arena,self._binding),python_admission_oracle_calls=self._oracle_calls,cache='WEAK_OWNER_INDEX_STRONG_NATIVE_DESCRIPTOR_EDGES')
    def close(self):
        self.check(self._job)
        self._native.close_guard_arena(self._arena,self._binding)
    def __copy__(self):raise TypeError('B69 exact session cannot be copied')
    def __deepcopy__(self,memo):raise TypeError('B69 exact session cannot be copied')
    def __reduce_ex__(self,protocol):raise TypeError('B69 exact session is not persistent DATA')

def enable_exact_guards(job,native):
    from .lifecycle_job_prepared import PreparedJobRuntime
    if type(job)is not PreparedJobRuntime or job._active is not None or job._guard_plan is not None:
        raise ValueError('B69 once-only exact job guard preparation')
    # Independently admit actual source/runtime/binary, not a caller module or
    # a capability dictionary. Prepay this bounded one-time control work.
    import json
    from .lifecycle_typed_platform import admit_typed_build
    job._charge(1024+MAX_ROWS,'public_boundaries')
    build=json.loads(job._admission._build_raw)
    if native is not admit_typed_build(build):raise ValueError('B69 foreign native guard library')
    expected=dict(method=METHOD,max_rows=MAX_ROWS,max_live_bytes=MAX_BYTES,per_row_reservation_bytes=512,
        workspace_accounting='B70_DESCRIPTOR_CLOSURE_V2',max_sequence_items=MAX_SEQUENCE_ITEMS,max_live_plans=MAX_LIVE_PLANS,independent_dispatch=True,
        same_public_boundaries=True,public_cpython_api=True,undocumented_dict_versions=False,numerical_entries=False,persistent=False)
    capability=native.guard_plan_capability()
    if type(capability)is not dict or capability!=expected:raise ValueError('B69 actual compiled guard capability mismatch')
    job._full_guard()
    session=ExactGuardSession(job,native,_KEY)
    job._guard_plan=session;job._guard_plan_pin=session
    job._guard_gate=native.dispatch_exact_guard;job._guard_gate_pin=native.dispatch_exact_guard
    job._guard_arena=session._arena;job._guard_binding=session._binding
    job._guard_records_enabled=hasattr(native,'guard_record_capability')
    rows=_control_rows(session,job)
    # Charge directly before enabling dispatch; _charge would call the not-yet-bound gate.
    job._work['control_units_reserved']+=1024+len(rows)*2
    job._work['public_boundaries']+=1
    if job._work['control_units_reserved']>__import__(__package__+'.lifecycle_job_prepared',fromlist=['MAX_CONTROL_UNITS']).MAX_CONTROL_UNITS:
        raise ValueError('B70 control admission capacity')
    native.bind_guard_dispatch(session._arena,session._binding,session,job,rows)
    if job._guard_records_enabled:
        # Finite native record reservation is administration, never model work.
        if job._work['control_units_reserved']+65536>__import__(__package__+'.lifecycle_job_prepared',fromlist=['MAX_CONTROL_UNITS']).MAX_CONTROL_UNITS:
            raise ValueError('YEAR-V4 job identity record control capacity')
        job._work['control_units_reserved']+=65536
        native.bind_guard_identity(session._arena,session._binding,session,job,_identity_descriptor(job))
    # Close the one-time metadata capture window against the retained oracle.
    # No oracle is rerun at subsequent production boundaries.
    job._schema.guard();session._oracle_calls+=1
    from .lifecycle_job_prepared import _guard_generation_owner
    _guard_generation_owner();session._oracle_calls+=1
    job._full_guard()
    return session
