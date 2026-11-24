# B69 exact validation control only; no numerical entry/fee changes.
from libc.stdlib cimport calloc, free
from cpython.ref cimport PyObject
from cpython.object cimport PyObject_GetAttr, PyObject_RichCompareBool, Py_EQ
from cpython.dict cimport PyDict_Next, PyDict_Size, PyDict_GetItemWithError
from cpython.tuple cimport PyTuple_GET_SIZE, PyTuple_GET_ITEM
from cpython.float cimport PyFloat_CheckExact
import weakref as _g_weakref

cdef extern from *:
    """
    #ifdef _WIN32
    #include <process.h>
    static long b69_process_id(void) { return (long)_getpid(); }
    #else
    #include <unistd.h>
    static long b69_process_id(void) { return (long)getpid(); }
    #endif
    """
    long b69_process_id() noexcept
cdef extern from "Python.h":
    unsigned long PyThread_get_thread_ident() noexcept

cdef union _GuardBits:
    double value
    uint64_t bits

cdef struct _GuardRow:
    int kind
    int mode
    PyObject* target
    PyObject* name
    PyObject* expected
    PyObject* extra
    PyObject* label

cdef object _G_KEY = object()
cdef object _G_EXPORTS
cdef object _G_MODULE
cdef uint64_t _G_ARENAS=0
cdef uint64_t _G_PLANS=0
cdef uint64_t _G_ATTEMPTS=0
cdef uint64_t _G_COMPLETED=0
cdef uint64_t _G_CHECKED=0
cdef uint64_t _G_DISPATCH_ATTEMPTS=0
cdef uint64_t _G_DISPATCH_OK=0
cdef uint64_t _G_DISPATCH_ROWS=0
cdef Py_ssize_t _G_MAX_ROWS = 262144
cdef Py_ssize_t _G_MAX_BYTES = 134217728

cdef void _guard_native_exports() except *:
    cdef Py_ssize_t i
    cdef object name, expected
    for i in range(PyTuple_GET_SIZE(_G_EXPORTS)):
        name, expected = <object>PyTuple_GET_ITEM(_G_EXPORTS,i)
        if PyObject_GetAttr(_G_MODULE,name) is not expected:
            raise ValueError('B69 native validation callable binding drift')

cdef class _ExactGuardArena:
    cdef object _key, _binding, _issued, _dispatch_plan, _dispatch_session, _dispatch_job, _identity_record
    cdef long _pid
    cdef unsigned long _thread
    cdef Py_ssize_t _live_bytes, _record_bytes
    cdef uint64_t _plans, _rows, _calls, _checks
    cdef bint _closed
    def __init__(self,key,binding):
        if key is not _G_KEY:raise TypeError('B69 private arena factory')
        self._key=key;self._binding=binding;self._issued={}
        self._dispatch_plan=None;self._dispatch_session=None;self._dispatch_job=None;self._identity_record=None;self._record_bytes=0
        self._pid=b69_process_id();self._thread=PyThread_get_thread_ident()
        self._closed=False
    cdef void check(self,object binding) except *:
        _guard_native_exports()
        if (self._key is not _G_KEY or self._closed or binding is not self._binding or
                self._pid!=b69_process_id() or self._thread!=PyThread_get_thread_ident()):
            raise ValueError('B69 foreign/process/thread/closed exact guard arena')
    def __copy__(self):raise TypeError('B69 guard arena cannot be copied')
    def __deepcopy__(self,memo):raise TypeError('B69 guard arena cannot be copied')
    def __reduce_ex__(self,protocol):raise TypeError('B69 guard arena is not persistent DATA')

cdef class _ExactGuardPlan:
    cdef object _rows_owner, _owner_ref, _arena_owner
    cdef _GuardRow* _rows
    cdef Py_ssize_t _size, _reservation
    cdef object __weakref__
    def __cinit__(self):
        self._rows=NULL;self._size=0;self._reservation=0
    def __init__(self,key):
        if key is not _G_KEY:raise TypeError('B69 private exact plan factory')
    def __dealloc__(self):
        if self._rows!=NULL:free(self._rows)
        # No Python calls/resurrection in dealloc; the cdef owner may have been
        # cleared by GC. Reservations are otherwise released at saved boundary.
    def __copy__(self):raise TypeError('B69 exact plan cannot be copied')
    def __deepcopy__(self,memo):raise TypeError('B69 exact plan cannot be copied')
    def __reduce_ex__(self,protocol):raise TypeError('B69 exact plan is not persistent DATA')

cdef bint _g_equal(object current,object expected) except *:
    # All value-comparison domains are exact builtins. Never execute hostile eq.
    if type(current) is not type(expected):return False
    if type(current) not in (str,int,bool,bytes,type(None)):return False
    return PyObject_RichCompareBool(current,expected,Py_EQ)==1

cdef void _g_tuple(object actual,object expected,int mode) except *:
    cdef Py_ssize_t i,n
    cdef object a,b
    cdef _GuardBits x,y
    if type(actual)is not tuple or type(expected)is not tuple:
        raise ValueError('B69 exact tuple descriptor')
    n=PyTuple_GET_SIZE(expected)
    if PyTuple_GET_SIZE(actual)!=n:raise ValueError('B69 tuple length drift')
    for i in range(n):
        a=<object>PyTuple_GET_ITEM(actual,i);b=<object>PyTuple_GET_ITEM(expected,i)
        if mode==0:
            if a is not b:raise ValueError('B69 tuple identity/member/order drift')
        elif mode==1:
            if not _g_equal(a,b):raise ValueError('B69 tuple exact value drift')
        elif mode==2:
            if not PyFloat_CheckExact(a) or not PyFloat_CheckExact(b):
                raise ValueError('B69 local-axis exact binary64 tuple')
            x.value=PyFloat_AS_DOUBLE(a);y.value=PyFloat_AS_DOUBLE(b)
            if x.bits!=y.bits:raise ValueError('B69 local-axis signed-bit drift')
        else:raise ValueError('B69 invalid tuple comparison mode')

cdef void _g_mapping(object mapping,object keys,object values,int mode) except *:
    cdef Py_ssize_t i=0,pos=0,n=PyTuple_GET_SIZE(keys)
    cdef PyObject* key
    cdef PyObject* value
    cdef object ks,vs,k,v
    if type(mapping)is dict:
        if PyDict_Size(mapping)!=n:raise ValueError('B69 mapping size drift')
        while PyDict_Next(mapping,&pos,&key,&value):
            k=<object>PyTuple_GET_ITEM(keys,i);v=<object>PyTuple_GET_ITEM(values,i)
            if mode==0:
                if key!=<PyObject*>k:raise ValueError('B69 mapping key identity/order drift')
            elif not _g_equal(<object>key,k):raise ValueError('B69 mapping key value/order drift')
            if value!=<PyObject*>v:raise ValueError('B69 mapping value identity drift')
            i+=1
    else:
        # Public mappingproxy iterator: retain exact key/member/order checks
        # without allocating an entire keys tuple on every guard dispatch.
        if len(mapping)!=n:raise ValueError('B69 mapping size drift')
        i=0
        for ks in mapping:
            if i>=n:raise ValueError('B69 mapping size drift')
            k=<object>PyTuple_GET_ITEM(keys,i)
            if mode==0:
                if ks is not k:raise ValueError('B69 mapping key identity/order drift')
            elif not _g_equal(ks,k):raise ValueError('B69 mapping key value/order drift')
            if mapping[ks] is not <object>PyTuple_GET_ITEM(values,i):
                raise ValueError('B69 mappingproxy member drift')
            i+=1
        if i!=n:raise ValueError('B69 mapping size drift')

cdef void _g_run(_ExactGuardPlan plan) except *:
    cdef Py_ssize_t i
    cdef _GuardRow* row
    cdef object target,name,expected,extra,current
    for i in range(plan._size):
        row=&plan._rows[i]
        target=<object>row.target;name=<object>row.name
        expected=<object>row.expected;extra=<object>row.extra
        try:
            if row.kind==1:
                if type(target)is not expected:raise ValueError('type')
            elif row.kind==2:
                if PyObject_GetAttr(target,name)is not expected:raise ValueError('attribute identity')
            elif row.kind==3:
                if not _g_equal(PyObject_GetAttr(target,name),expected):raise ValueError('attribute exact value')
            elif row.kind==4:
                current=target if name is None else PyObject_GetAttr(target,name)
                _g_tuple(current,expected,row.mode)
            elif row.kind==5:
                _g_mapping(target,expected,extra,row.mode)
            elif row.kind==6:
                _g_mapping(PyObject_GetAttr(target,name),expected,extra,row.mode)
            elif row.kind==7:
                try:current=PyObject_GetAttr(target,'cell_contents')
                except ValueError:
                    if row.mode==1:continue
                    raise
                if row.mode==1 or current is not expected:raise ValueError('closure cell')
            elif row.kind==8:
                try:current=PyObject_GetAttr(target,name)
                except AttributeError:current=None
                if current is not expected:raise ValueError('optional attribute identity')
            elif row.kind==9:
                if type(target)is not dict or PyDict_GetItemWithError(target,name)!=row.expected:
                    raise ValueError('dictionary member binding')
            elif row.kind==10:
                current=target()
                if current is None or PyObject_GetAttr(current,name)is not expected:
                    raise ValueError('sealed descriptor owner binding')
            elif row.kind==11:
                # Exactly IMPORT_FROM's public attribute-first / sys.modules
                # circular-import fallback, never importlib canonicalization.
                try:current=PyObject_GetAttr(target,name)
                except AttributeError:
                    if (type(extra)is not tuple or len(extra)!=2 or type(extra[0])is not dict):
                        raise ValueError('import fallback metadata')
                    current=extra[0][extra[1]]
                if current is not expected:raise ValueError('resolved import identity')
            else:raise ValueError('unknown native descriptor opcode')
        except BaseException as error:
            raise ValueError('B69 exact guard drift: '+str(<object>row.label)) from error


# YEAR-V4 invocation-owned identity/generation records. These are private C
# fields, not persisted receipts, a trusted boolean, or a physical-state cache.
cdef uint64_t _R_CREATED=0
cdef uint64_t _R_GENERATIONS=0
cdef uint64_t _R_ATTEMPTS=0
cdef uint64_t _R_COMPLETED=0
cdef uint64_t _R_FAILED=0
cdef object _R_CAP=281474976710656
cdef object _R_JOB_ATTRS=('static','external_root','external_model','_admission','_schema',
    '_external_seal','_owned_seal','_work','_roles','_thermal_aliases','_admission_pins')
cdef object _R_ADMISSION_ATTRS=('root','source_binding','_raw','_raw_sha','_build_raw',
    '_schema','_root_seal','_codec_receipt','_work')
cdef object _R_GENERATION_FIELDS=('full_requests','closed_requests','activations',
    'callback_suspensions','invalidations','machine_world_steps','reference_world_steps')

cdef class _JobGuardRecord:
    cdef object job,session,job_type,alias_type,job_binding,source,runtime,system
    cdef object job_values,admission,admission_pins,admission_items,work,work_keys,control_method
    cdef object roles,actual,forecast,aliases,baseline,environment
    cdef object generation_pin,generation_module,generation_type,generation,generation_pins
    cdef object generation_hook,generation_counts
    cdef _ExactGuardPlan generation_plan
    cdef bint busy
    cdef Py_ssize_t reservation

cdef object _r_item(object mapping,object key):
    cdef PyObject* value
    if type(mapping)is not dict:raise ValueError('B64 exact native control ledger')
    value=PyDict_GetItemWithError(mapping,key)
    if value==NULL:raise ValueError('B64 missing native control ledger field')
    return <object>value

cdef void _r_keys(object mapping) except *:
    cdef Py_ssize_t pos=0
    cdef PyObject* key
    cdef PyObject* value
    if type(mapping)is not dict:raise ValueError('B64 exact native control ledger')
    while PyDict_Next(mapping,&pos,&key,&value):
        if type(<object>key)is not str:raise ValueError('B64 exact native control ledger keys')

cdef uint64_t _r_integer(object value,uint64_t maximum,bint inclusive=True) except *:
    if type(value)is not int or value<0 or (value>maximum if inclusive else value>=maximum):
        raise ValueError('B64 finite versioned operational ledger')
    return value

cdef void _r_runtime(_JobGuardRecord r) except *:
    cdef object current=r.runtime
    if (type(current)is not tuple or len(current)!=6 or current[0]!=b69_process_id() or
            not _g_equal(r.system.implementation.name,current[1]) or
            not _g_equal(r.system.version,current[2]) or
            not _g_equal(r.system.executable,current[3]) or
            not _g_equal(r.system.implementation.cache_tag,current[4]) or
            not _g_equal(r.system.platform,current[5])):
        raise ValueError('B64 foreign/copied/stale job authority')

cdef void _r_generation_cheap(_JobGuardRecord r) except *:
    cdef object g=r.generation,p,counts,key,value,phase
    cdef Py_ssize_t i
    if g is None:
        if r.job._validation is not None or r.job._validation_pin is not None:
            raise ValueError('YEAR-V4 generation must bind before checked use')
        return
    if (r.job._validation is not g or r.job._validation_pin is not g or type(g)is not r.generation_type):
        raise ValueError('B65 changed validation owner')
    # Method/class/MRO/closure guards execute before this direct equivalent of
    # _Generation.cheap. No method on the generation decides its own validity.
    _g_run(r.generation_plan)
    p=g._pins;counts=g._counts;phase=g._phase
    if (p is not r.generation_pins or type(p)is not tuple or len(p)!=8 or
            g._job is not r.job or g._hook is not r.generation_hook or
            p[0]is not g or p[1]is not r.job or p[2]is not g._hook or
            p[3]!=b69_process_id()or p[4]!=PyThread_get_thread_ident()or
            p[5]is not r.job_binding or not _g_equal(p[6],r.job.source_binding)or
            p[7]is not r.admission_pins or r.job._closed or
            counts is not r.generation_counts or type(counts)is not dict or
            PyDict_Size(counts)!=7):
        raise ValueError('B65 foreign/thread/generation/control drift')
    _r_integer(g._epoch,1099511627776,True)
    _r_keys(counts)
    for i in range(7):
        key=<object>PyTuple_GET_ITEM(_R_GENERATION_FIELDS,i)
        value=_r_item(counts,key);_r_integer(value,1099511627776,False)
    if type(phase)is not str or phase not in('IDLE','CLOSED','CALLBACK','BOUNDARY','INVALID'):
        raise ValueError('B65 generation phase')
    if phase=='INVALID':raise ValueError('B65 invalidated generation')

cdef void _r_job_identity(_JobGuardRecord r,object job) except *:
    cdef Py_ssize_t i,pos=0,n
    cdef PyObject* key
    cdef PyObject* value
    cdef object name,current,pair,expected,binding
    cdef uint64_t attempts,finished,failed
    if (job is not r.job or type(job)is not r.job_type or job._self is not job or
            job._closed or job._binding is not r.job_binding or
            job._runtime is not r.runtime or not _g_equal(job.source_binding,r.source)):
        raise ValueError('B64 foreign/copied/stale job authority')
    _r_runtime(r)
    # Every fixed owner edge is checked against the private native pin record.
    for i in range(11):
        name=<object>PyTuple_GET_ITEM(_R_JOB_ATTRS,i)
        if PyObject_GetAttr(job,name)is not <object>PyTuple_GET_ITEM(r.job_values,i):
            raise ValueError('B64 replaced job seal or ledger')
    if (type(job._roles)is not dict or PyDict_Size(job._roles)!=2 or
            _r_item(job._roles,'ACTUAL')is not r.actual or
            _r_item(job._roles,'FORECAST')is not r.forecast):
        raise ValueError('B64 foreign/copied/stale job authority')
    if type(job._thermal_aliases)is not dict or PyDict_Size(job._thermal_aliases)>1:
        raise ValueError('B64 replaced job seal or ledger')
    pos=0
    while PyDict_Next(job._thermal_aliases,&pos,&key,&value):
        if (not _g_equal(<object>key,'TYPED_CONSTRUCTION_V1')or
                type(<object>value)is not r.alias_type):
            raise ValueError('B64 replaced job seal or ledger')
    if (not _g_equal(job._baseline_identity,r.baseline)or
            not _g_equal(job.static.environment_policy_identity,r.environment)):
        raise ValueError('B68 prepared static digest drift')
    if r.admission._phase!='CONSUMED':
        raise ValueError('B64 consumed input admission drift')
    for i in range(9):
        name=<object>PyTuple_GET_ITEM(_R_ADMISSION_ATTRS,i)
        current=PyObject_GetAttr(r.admission,name)
        expected=<object>PyTuple_GET_ITEM(r.admission_pins,i)
        if i in(1,3):
            if not _g_equal(current,expected):raise ValueError('B64 consumed input admission drift')
        elif current is not expected:raise ValueError('B64 consumed input admission drift')
    # Admission work is sealed; order and exact values match the old items tuple.
    current=r.admission._work;n=PyTuple_GET_SIZE(r.admission_items)
    if type(current)is not dict or PyDict_Size(current)!=n:
        raise ValueError('B64 consumed input admission drift')
    pos=0;i=0
    while PyDict_Next(current,&pos,&key,&value):
        pair=<object>PyTuple_GET_ITEM(r.admission_items,i)
        if not _g_equal(<object>key,pair[0])or not _g_equal(<object>value,pair[1]):
            raise ValueError('B64 consumed input admission drift')
        i+=1
    _r_integer(job._generation,281474976710656,False)
    current=job._work
    if type(current)is not dict or PyDict_Size(current)!=PyTuple_GET_SIZE(r.work_keys):
        raise ValueError('B64 finite versioned operational ledger')
    _r_keys(current)
    if not _g_equal(_r_item(current,'method'),r.control_method):
        raise ValueError('B64 finite versioned operational ledger')
    for i in range(PyTuple_GET_SIZE(r.work_keys)):
        name=<object>PyTuple_GET_ITEM(r.work_keys,i)
        if name!='method':_r_integer(_r_item(current,name),281474976710656,True)
    attempts=_r_integer(_r_item(current,'transaction_attempts'),281474976710656,True)
    finished=_r_integer(_r_item(current,'transaction_completed'),281474976710656,True)
    failed=_r_integer(_r_item(current,'transaction_failed'),281474976710656,True)
    if finished+failed>attempts:raise ValueError('B64 finite versioned operational ledger')
    _r_generation_cheap(r)

def guard_record_capability():
    return dict(method='YEAR_V4_NATIVE_JOB_GUARD_RECORD_V1',per_job_records=1,
        record_reservation_bytes=65536,exact_generation_binding=True,
        fixed_native_owner_pins=True,dynamic_ledgers_checked=True,
        class_method_mro_closure_checks=True,legacy_fallback='STRICT_PYTHON_GUARDS',
        scientific_work='UNCHANGED',persistent=False)

def bind_guard_identity(arena,binding,session,job,descriptor):
    global _R_CREATED
    cdef _ExactGuardArena a
    cdef _JobGuardRecord r
    cdef object p,keys
    if type(arena)is not _ExactGuardArena:raise TypeError('YEAR-V4 actual guard record arena')
    a=arena;a.check(binding)
    if a._dispatch_job is not job or a._dispatch_session is not session or a._dispatch_plan is None:
        raise ValueError('YEAR-V4 bound native dispatch precedes identity record')
    if a._identity_record is not None:raise ValueError('YEAR-V4 once-only job identity record')
    _g_run(a._dispatch_plan)
    if (type(descriptor)is not tuple or len(descriptor)!=8 or type(job)is not descriptor[0]or
            descriptor[4]!=281474976710656 or type(descriptor[2])is not tuple or
            descriptor[3]!='B69_JOB_PREPARATION_CONTROL_V2'):
        raise ValueError('YEAR-V4 exact job identity descriptor')
    if job._active is not None or job._validation is not None or job._validation_pin is not None:
        raise ValueError('YEAR-V4 identity admission precedes generation activation')
    p=job._binding
    if type(p)is not tuple or len(p)!=16 or p[0]is not job:
        raise ValueError('B64 foreign/copied/stale job authority')
    if (p[1]is not job.static or p[2]is not job.external_root or p[3]is not job.external_model or
            p[4]is not job._admission or not _g_equal(p[5],job.source_binding)or
            p[6]!=job._runtime or p[7]is not job._roles['ACTUAL']or p[8]is not job._roles['FORECAST']or
            p[9]is not job._schema or p[10]is not job._external_seal or p[11]is not job._owned_seal or
            p[12]is not job._work or p[13]is not job._roles or p[14]is not job._thermal_aliases or
            type(p[15])is not tuple or len(p[15])!=2):
        raise ValueError('B64 replaced job seal or ledger')
    if type(job._admission_pins)is not tuple or len(job._admission_pins)!=10:
        raise ValueError('B64 consumed input admission drift')
    if _R_CREATED>=281474976710656 or a._live_bytes+65536>_G_MAX_BYTES:
        raise ValueError('YEAR-V4 finite native identity record capacity')
    r=_JobGuardRecord.__new__(_JobGuardRecord)
    r.job=job;r.session=session;r.job_type=descriptor[0];r.alias_type=descriptor[1]
    r.work_keys=descriptor[2];r.control_method=descriptor[3];r.job_binding=p
    r.source=job.source_binding;r.runtime=job._runtime;r.system=sys
    r.job_values=tuple(getattr(job,n)for n in _R_JOB_ATTRS)
    r.admission=job._admission;r.admission_pins=job._admission_pins
    r.admission_items=job._admission_pins[9];r.work=job._work
    r.roles=job._roles;r.actual=p[7];r.forecast=p[8];r.aliases=job._thermal_aliases
    r.baseline=p[15][0];r.environment=p[15][1]
    r.generation_pin=descriptor[5];r.generation_module=descriptor[6];r.generation_type=descriptor[5][0]
    if type(session._generation)is not _ExactGuardPlan:raise ValueError('YEAR-V4 exact generation descriptor')
    r.generation_plan=session._generation;r.generation=None;r.generation_pins=None
    r.generation_hook=None;r.generation_counts=None;r.busy=False;r.reservation=65536
    if descriptor[7]!=r.runtime:raise ValueError('YEAR-V4 runtime admission binding')
    _r_job_identity(r,job)
    a._identity_record=r;a._record_bytes=65536;a._live_bytes+=65536;_R_CREATED+=1

def bind_guard_generation(arena,binding,session,job,generation):
    global _R_GENERATIONS
    cdef _ExactGuardArena a
    cdef _JobGuardRecord r
    if type(arena)is not _ExactGuardArena:raise TypeError('YEAR-V4 actual generation record arena')
    a=arena;a.check(binding)
    if (a._dispatch_job is not job or a._dispatch_session is not session or
            type(a._identity_record)is not _JobGuardRecord):
        raise ValueError('YEAR-V4 generation identity record owner')
    r=a._identity_record
    _g_run(a._dispatch_plan);_g_run(r.generation_plan)
    if (r.generation is not None or type(generation)is not r.generation_type or
            job._validation is not generation or job._validation_pin is not generation or
            job._active is not None or generation._phase!='IDLE'or generation._root is not None):
        raise ValueError('YEAR-V4 once-only inactive generation binding')
    if _R_GENERATIONS>=281474976710656:raise ValueError('YEAR-V4 generation record control cap')
    r.generation=generation;r.generation_pins=generation._pins
    r.generation_hook=generation._hook;r.generation_counts=generation._counts
    try:_r_job_identity(r,job)
    except BaseException:
        # A failed one-time admission never becomes a live record authority.
        r.generation=None;r.generation_pins=None;r.generation_hook=None;r.generation_counts=None
        raise
    _R_GENERATIONS+=1

cdef void _r_dispatch_identity(_ExactGuardArena a,object session,object job,object argument) except *:
    global _R_ATTEMPTS,_R_COMPLETED,_R_FAILED
    cdef _JobGuardRecord r
    if type(a._identity_record)is not _JobGuardRecord:
        raise ValueError('YEAR-V4 native job identity record is not admitted')
    r=a._identity_record
    if r.job is not job or r.session is not session or argument is not job or r.busy:
        raise ValueError('YEAR-V4 foreign/reentrant native identity request')
    if _R_ATTEMPTS>=281474976710656:raise ValueError('YEAR-V4 identity record call cap')
    _R_ATTEMPTS+=1;r.busy=True
    try:
        _g_run(a._dispatch_plan)
        _r_job_identity(r,job)
    except BaseException:
        _R_FAILED+=1;raise
    else:_R_COMPLETED+=1
    finally:r.busy=False

def guard_record_counts():
    return dict(method='YEAR_V4_NATIVE_JOB_GUARD_RECORD_COUNTS_V1',records_created=int(_R_CREATED),
        generations_bound=int(_R_GENERATIONS),identity_attempts=int(_R_ATTEMPTS),
        identity_completed=int(_R_COMPLETED),identity_failed=int(_R_FAILED),
        record_reservation_bytes=65536,reset_available=False,scientific_work='UNCHANGED',
        scope='SOURCE_BOUND_INVOCATION_CONTROL_NOT_CHECKPOINT_OR_PHYSICAL_STATE')

def guard_plan_capability():
    return dict(method='B69_COMPILED_EXACT_GUARD_PLAN_V1',max_rows=int(_G_MAX_ROWS),
        max_live_bytes=int(_G_MAX_BYTES),per_row_reservation_bytes=512,workspace_accounting='B70_DESCRIPTOR_CLOSURE_V2',
        max_sequence_items=65536,max_live_plans=1024,independent_dispatch=True,
        same_public_boundaries=True,public_cpython_api=True,undocumented_dict_versions=False,
        numerical_entries=False,persistent=False)

def make_guard_arena(binding):
    global _G_ARENAS
    _guard_native_exports()
    if _G_ARENAS>=281474976710656:raise ValueError('B69 arena control limit')
    arena=_ExactGuardArena(_G_KEY,binding);_G_ARENAS+=1
    return arena

cdef Py_ssize_t _guard_workspace(object rows) except -1:
    # 512/row covers C row48, tuple shells/row list/result tuple, strong
    # reference slots, function/owner seen-indexes and allocator headroom.
    # Variable nested snapshots and text are counted separately BEFORE C alloc.
    # This enforced descriptor reservation is not a process RSS claim.
    cdef Py_ssize_t total=4096,i,j,size
    cdef object row,value
    for i in range(PyTuple_GET_SIZE(rows)):
        row=<object>PyTuple_GET_ITEM(rows,i)
        if type(row)is not tuple or len(row)!=7:raise ValueError('B70 exact row workspace shape')
        total+=512
        for j in (3,4):
            value=<object>PyTuple_GET_ITEM(row,j)
            if type(value)is tuple:
                size=PyTuple_GET_SIZE(value)
                if size>65536:raise ValueError('B70 descriptor sequence cap')
                total+=128+64*size
        for j in (2,6):
            value=<object>PyTuple_GET_ITEM(row,j)
            if type(value)is str:
                size=len(value)
                if size>4096:raise ValueError('B70 descriptor text cap')
                total+=128+8*size
        if total>_G_MAX_BYTES//2:raise ValueError('B70 descriptor preparation peak cap')
    return total

def compile_guard_plan(arena,binding,owner,rows):
    global _G_PLANS
    cdef _ExactGuardArena a
    cdef _ExactGuardPlan plan
    cdef Py_ssize_t i,n,reservation
    cdef object row,ref,previous
    if type(arena)is not _ExactGuardArena:raise TypeError('B69 exact arena')
    a=arena;a.check(binding)
    if type(rows)is not tuple or not 0<len(rows)<=_G_MAX_ROWS:
        raise ValueError('B69 bounded exact plan rows')
    # Remove only dead weak capabilities, never replace an issued live owner.
    dead=[k for k,v in a._issued.items()if k()is None or v()is None]
    for k in dead:del a._issued[k]
    ref=_g_weakref.ref(owner)
    if ref in a._issued:raise ValueError('B69 once-only plan for retained owner')
    n=len(rows);reservation=_guard_workspace(rows)
    # Exact conservative live accounting is recomputed over retained plans, not
    # filesystem scans, caller supplied sizes or arithmetic/scientific ledgers.
    a._live_bytes=a._record_bytes
    for previous in a._issued.values():
        plan=previous()
        if plan is not None:a._live_bytes+=plan._reservation
    if len(a._issued)>=1024:raise ValueError('B70 bounded live guard plans')
    if a._live_bytes+2*reservation+2097152>_G_MAX_BYTES:raise ValueError('B70 exact guard workspace limit live='+str(a._live_bytes)+' incoming='+str(reservation)+' peak='+str(a._live_bytes+2*reservation+2097152)+' cap='+str(_G_MAX_BYTES))
    plan=_ExactGuardPlan(_G_KEY);plan._rows_owner=rows;plan._owner_ref=ref
    plan._arena_owner=a;plan._size=n;plan._reservation=reservation
    plan._rows=<_GuardRow*>calloc(n,sizeof(_GuardRow))
    if plan._rows==NULL:raise MemoryError('B69 exact guard allocation')
    for i in range(n):
        row=<object>PyTuple_GET_ITEM(rows,i)
        if type(row)is not tuple or len(row)!=7 or type(row[0])is not int or type(row[5])is not int:
            raise ValueError('B69 exact native descriptor shape')
        if not 1<=row[0]<=11 or not 0<=row[5]<=2 or type(row[6])is not str:
            raise ValueError('B69 exact native descriptor domain')
        plan._rows[i].kind=row[0];plan._rows[i].mode=row[5]
        plan._rows[i].target=PyTuple_GET_ITEM(row,1);plan._rows[i].name=PyTuple_GET_ITEM(row,2)
        plan._rows[i].expected=PyTuple_GET_ITEM(row,3);plan._rows[i].extra=PyTuple_GET_ITEM(row,4)
        plan._rows[i].label=PyTuple_GET_ITEM(row,6)
    _g_run(plan)
    a._issued[ref]=_g_weakref.ref(plan);a._live_bytes+=reservation
    if _G_PLANS>=281474976710656:raise ValueError('B69 plan control limit')
    a._plans+=1;a._rows+=n;_G_PLANS+=1
    return plan

def guard_exact_plans(arena,binding,plans):
    global _G_ATTEMPTS,_G_COMPLETED,_G_CHECKED
    cdef _ExactGuardArena a
    cdef _ExactGuardPlan plan
    cdef Py_ssize_t i,n
    cdef object pair,owner,raw,ref
    if type(arena)is not _ExactGuardArena or type(plans)is not tuple:
        raise TypeError('B69 exact arena/plan package')
    a=arena;a.check(binding);n=PyTuple_GET_SIZE(plans)
    if _G_ATTEMPTS>=281474976710656:raise ValueError('B69 guard control limit')
    _G_ATTEMPTS+=1
    if a._calls>=281474976710656:raise ValueError('B69 bounded native guard call ledger')
    if not 1<=n<=8192:raise ValueError('B69 bounded plan package')
    for i in range(n):
        pair=<object>PyTuple_GET_ITEM(plans,i)
        if type(pair)is not tuple or len(pair)!=2:raise TypeError('B69 exact owner/plan pair')
        owner=pair[0];raw=pair[1]
        if type(raw)is not _ExactGuardPlan:raise TypeError('B69 exact private compiled plan')
        plan=raw
        if plan._arena_owner is not a or plan._owner_ref()is not owner:
            raise ValueError('B69 plan owner/arena mismatch')
        ref=plan._owner_ref
        if ref not in a._issued or a._issued[ref]()is not plan:
            raise ValueError('B69 unissued/replaced compiled plan')
        if a._checks>72057594037927936-plan._size:raise ValueError('B69 bounded native guard row ledger')
        if _G_CHECKED>72057594037927936-plan._size:raise ValueError('B69 process descriptor limit')
        _g_run(plan);a._checks+=plan._size;_G_CHECKED+=plan._size
    a._calls+=1;_G_COMPLETED+=1

def bind_guard_dispatch(arena,binding,session,job,rows):
    cdef _ExactGuardArena a
    if type(arena)is not _ExactGuardArena:raise TypeError('B70 actual arena required')
    a=arena;a.check(binding)
    if a._dispatch_plan is not None:raise ValueError('B70 once-only dispatch admission')
    # Independent private cdef state cannot be replaced through session._pins.
    plan=compile_guard_plan(arena,binding,session,rows)
    a._dispatch_plan=plan;a._dispatch_session=session;a._dispatch_job=job

def dispatch_exact_guard(arena,binding,session,job,operation,argument):
    global _G_DISPATCH_ATTEMPTS,_G_DISPATCH_OK,_G_DISPATCH_ROWS
    cdef _ExactGuardArena a
    cdef _ExactGuardPlan plan
    cdef _JobGuardRecord record
    if type(arena)is not _ExactGuardArena:raise TypeError('B70 actual dispatch arena')
    a=arena;a.check(binding)
    if (a._dispatch_plan is None or session is not a._dispatch_session or job is not a._dispatch_job):
        raise ValueError('B70 private dispatch owner/binding drift')
    plan=a._dispatch_plan
    if _G_DISPATCH_ATTEMPTS>=281474976710656:raise ValueError('B70 dispatch control cap')
    _G_DISPATCH_ATTEMPTS+=1
    if type(operation)is str and operation=='identity':
        _r_dispatch_identity(a,session,job,argument)
        if _G_DISPATCH_ROWS>72057594037927936-plan._size:raise ValueError('B70 dispatch row control cap')
        _G_DISPATCH_OK+=1;_G_DISPATCH_ROWS+=plan._size
        return
    # The saved control plan executes here BEFORE full/check/generation/graph.
    # It is not selected, supplied or dispatched by the Python method checked.
    _g_run(plan)
    if _G_DISPATCH_ROWS>72057594037927936-plan._size:raise ValueError('B70 dispatch row control cap')
    _G_DISPATCH_OK+=1;_G_DISPATCH_ROWS+=plan._size
    if type(operation)is not str or operation not in ('check','full','generation','graph','receipt','close'):
        raise ValueError('B70 closed dispatch operation domain')
    if operation=='generation'and type(a._identity_record)is _JobGuardRecord:
        record=<_JobGuardRecord>a._identity_record
        if argument is not record.generation_pin:raise ValueError('B69 generation pin owner')
        _g_run(record.generation_plan)
        return
    if operation in ('receipt','close'):
        if argument is not None:raise ValueError('B70 closed no-argument dispatch')
        return PyObject_GetAttr(session,operation)()
    return PyObject_GetAttr(session,operation)(argument)

def guard_arena_receipt(arena,binding):
    cdef _ExactGuardArena a
    if type(arena)is not _ExactGuardArena:raise TypeError('B69 exact arena')
    a=arena;a.check(binding)
    return dict(method='B69_COMPILED_EXACT_GUARD_PLAN_V1',plans_created=int(a._plans),
        descriptors_compiled=int(a._rows),native_guard_calls=int(a._calls),
        descriptors_checked=int(a._checks),live_workspace_reserved_bytes=int(a._live_bytes),
        workspace_accounting='B70_DESCRIPTOR_CLOSURE_V2',transient_peak_reserve_bytes=2097152,max_live_plans=1024,
        max_live_bytes=int(_G_MAX_BYTES),pid=int(a._pid),thread=int(a._thread),
        scope='PRIVATE_VALIDATION_CONTROL_NOT_SCIENTIFIC_WORK')

def guard_process_counts():
    return dict(method='B69_PROCESS_EXACT_GUARD_CONTROL_V1',arenas=int(_G_ARENAS),plans=int(_G_PLANS),
        validation_attempts=int(_G_ATTEMPTS),validation_completed=int(_G_COMPLETED),
        completed_plan_descriptor_checks=int(_G_CHECKED),dispatch_attempts=int(_G_DISPATCH_ATTEMPTS),
        dispatch_completed=int(_G_DISPATCH_OK),dispatch_descriptor_checks=int(_G_DISPATCH_ROWS),reset_available=False,
        scientific_work='UNCHANGED',scope='OBSERVATIONAL_CONTROL_NOT_STATE_OR_CHECKPOINT_BINDING')

def close_guard_arena(arena,binding):
    cdef _ExactGuardArena a
    if type(arena)is not _ExactGuardArena:raise TypeError('B69 exact arena')
    a=arena;a.check(binding);a._closed=True

_G_MODULE=sys.modules[__name__]
_G_EXPORTS=tuple((n,globals()[n])for n in ('guard_plan_capability','make_guard_arena',
    'compile_guard_plan','guard_exact_plans','guard_arena_receipt','close_guard_arena','guard_process_counts','bind_guard_dispatch','dispatch_exact_guard',
    'guard_record_capability','guard_record_counts','bind_guard_identity','bind_guard_generation'))
