"""B70 independent retained-oracle origin audit and real native boundary negatives."""
import ast,importlib,inspect,json,sys,threading
from pathlib import Path
from types import ModuleType
import pytest
from ops_sim.v5 import lifecycle_exact_guards as eg,lifecycle_job_prepared as jp,prepared_input_codec as pc
from ops_sim.v5.lifecycle_typed_platform import admit_typed_build
from ops_sim.v5.lifecycle_document import dumps_root
from lifetime_support import root_for

# Reviewer-declared domains, deliberately independent from _codec_rows.
REVIEW_ALIASES=(('command_estimation','CommandRollingRoot'),('command_estimation','EstimationPolicy'),
 ('lifecycle_contract','LifecycleRoot'),('lifecycle_contract','LifecyclePolicy'),('lifecycle_contract','LifecycleScenario'),
 ('long_mission_document','SunPositionTable'),('sun_table','SunPositionSample'),('sun_table','SunTableProvenance'),
 ('orbit_sun_zonotope_local_v2','ZonotopeLocalIlluminationRequestV2'),
 ('orbit_sun_zonotope_local_v2_document','ZonotopeLocalIlluminationPolicyV2'),
 ('orbit_sun_zonotope_local_v2_document','J2ZonotopeSegmentRequest'),('rolling_document','AssemblyDesign'),
 ('spacecraft_project_v2','SpacecraftProjectV2'),('spacecraft_project_v3','SpacecraftProjectV3'),
 ('spacecraft_project','ProjectLimits'),('design_repair','MissionRequirements'))

@pytest.fixture
def native():
    return admit_typed_build(json.loads((Path(__file__).resolve().parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes()))

@pytest.fixture
def job(native):
    build=json.loads((Path(__file__).resolve().parents[1]/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes())
    root,admission=jp.admit_job_root(dumps_root(root_for(600)),'b'*64,build_binding=build)
    j=jp.prepare_job_runtime(admission,root);eg.enable_exact_guards(j,native)
    return j

def module(n):return importlib.import_module('ops_sim.v5.'+n)

@pytest.mark.parametrize('origin,name',REVIEW_ALIASES)
def test_all_sixteen_fresh_declaration_aliases_refuse_real_native_entry(job,origin,name):
    owner=module(origin);old=getattr(owner,name);ran=[];job._full_guard()
    before=job._guard_plan._native.guard_process_counts()
    try:
        setattr(owner,name,jp.EnvironmentAgeingPolicy)
        with pytest.raises((ValueError,AttributeError)):
            with job.transaction():ran.append(True)
        with pytest.raises((ValueError,AttributeError)):job._schema.guard()
        assert not ran
    finally:setattr(owner,name,old)
    job._full_guard();after=job._guard_plan._native.guard_process_counts()
    assert after['completed_plan_descriptor_checks']>before['completed_plan_descriptor_checks']

def test_independent_ast_inventory_covers_all_retained_oracle_global_and_module_reads(job):
    # The expected list comes from the ORIGINAL oracle code/AST, not builder output.
    from ops_sim.v5.lifecycle_prepared import _Seal
    roots=(pc.PreparedInputCodec._full_snapshot,pc._owner_signature,pc._function_signature,
           jp._SchemaSeal.guard,_Seal.guard,jp._guard_generation_owner,jp._generation_function_state,pc.fields,pc.typed.check_schema_coverage)
    rows=eg._schema_rows(job._schema)+eg._generation_rows(jp._GENERATION_OWNER_BINDING)
    observed={(id(row[1]),row[2])for row in rows if row[0]in(2,3,8,9)}
    required=set();module_edges=[]
    for fn in roots:
        for name in fn.__code__.co_names:
            if name in fn.__globals__:required.add((id(fn.__globals__),name))
        tree=ast.parse(__import__('textwrap').dedent(inspect.getsource(fn)));env=dict(fn.__globals__)
        for node in ast.walk(tree):
            if isinstance(node,ast.Name)and isinstance(node.ctx,ast.Load)and node.id in fn.__globals__ and node.id not in fn.__code__.co_varnames and node.id not in fn.__code__.co_cellvars:required.add((id(fn.__globals__),node.id))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom)and node.level==1:
                if node.module:
                    m=module(node.module)
                    for alias in node.names:
                        env[alias.asname or alias.name]=getattr(m,alias.name)
                        required.add((id(m),alias.name));module_edges.append(m.__name__+'.'+alias.name)
                else:
                    for alias in node.names:env[alias.asname or alias.name]=module(alias.name)
        def resolve(node):
            if isinstance(node,ast.Name):return env.get(node.id)
            if isinstance(node,ast.Attribute):
                base=resolve(node.value)
                if isinstance(base,ModuleType):
                    if hasattr(base,node.attr):
                        required.add((id(base),node.attr));module_edges.append(base.__name__+'.'+node.attr)
                        return getattr(base,node.attr)
            return None
        for node in ast.walk(tree):
            if isinstance(node,ast.Attribute):resolve(node)
    assert required<=observed,sorted((name for _,name in required-observed))
    assert len(set(module_edges))>16

@pytest.mark.parametrize('method',('full','check','generation','graph'))
@pytest.mark.parametrize('boundary',('entry','callback','exit'))
def test_dispatch_code_is_checked_independently_before_body_and_publication(job,method,boundary):
    fn=getattr(eg.ExactGuardSession,method);old=fn.__code__;ran=[]
    def noop(self,argument):return None
    def mutate():fn.__code__=noop.__code__
    try:
        with pytest.raises(ValueError):
            if boundary=='entry':
                mutate()
                with job.transaction():ran.append('body')
            else:
                with job.transaction()as tx:
                    if boundary=='callback':tx.callback(mutate)
                    else:mutate()
                ran.append('publication')
        assert not ran
    finally:fn.__code__=old
    job._full_guard()

@pytest.mark.parametrize('which',('plans-and-pins','native-and-pins','arena-and-pins','session-and-job-pin','fake-native-gate','foreign-arena'))
def test_coordinated_mutable_session_replacements_do_not_reseal_themselves(job,which):
    from types import SimpleNamespace
    from weakref import WeakKeyDictionary
    s=job._guard_plan;oldpins=s._pins;oldjob=(job._guard_plan,job._guard_plan_pin,job._guard_gate,job._guard_gate_pin,job._guard_arena)
    changes=[];called=[]
    def replace(owner,name,value):changes.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
    try:
        if which in ('plans-and-pins','native-and-pins','arena-and-pins'):
            index,name,new=(5,'_plans',WeakKeyDictionary())if which=='plans-and-pins'else(1,'_native',SimpleNamespace())if which=='native-and-pins'else(4,'_arena',object())
            replace(s,name,new);pins=list(s._pins);pins[index]=new;replace(s,'_pins',tuple(pins))
        elif which=='session-and-job-pin':
            foreign=object.__new__(eg.ExactGuardSession);replace(job,'_guard_plan',foreign);replace(job,'_guard_plan_pin',foreign)
        elif which=='fake-native-gate':
            def fake(*a):called.append(True)
            replace(job,'_guard_gate',fake);replace(job,'_guard_gate_pin',fake)
        else:replace(job,'_guard_arena',s._native.make_guard_arena(s._binding))
        with pytest.raises((ValueError,TypeError)):
            with job.transaction():called.append('body')
        assert not called
    finally:
        for owner,name,value in reversed(changes):setattr(owner,name,value)
    job._full_guard()

@pytest.mark.parametrize('method',('full','check','generation','graph'))
def test_failed_exit_preserves_original_exception_and_never_detaches(job,method):
    fn=getattr(eg.ExactGuardSession,method);old=fn.__code__;primary=RuntimeError('original B70 exception');published=[]
    def noop(self,argument):return None
    try:
        with pytest.raises(RuntimeError)as got:
            with job.transaction():
                fn.__code__=noop.__code__
                raise primary
            published.append(True)
        assert got.value is primary and not published and getattr(primary,'__notes__',[])and job._active is None
    finally:fn.__code__=old
    job._full_guard()

def test_compiled_control_rejects_changed_native_export_before_call(job):
    n=job._guard_plan._native;old=n.dispatch_exact_guard;called=[]
    def fake(*a):called.append(True)
    try:
        n.dispatch_exact_guard=fake
        with pytest.raises(ValueError):job._guard_identity()
        assert not called
    finally:n.dispatch_exact_guard=old
    job._full_guard()

def test_resource_limits_refuse_before_large_sequence_snapshot_and_keep_dead_owner_lifecycle(native):
    from ops_sim.v5.lifecycle_prepared import _Seal
    out=eg._Rows()
    with pytest.raises(ValueError,match='sequence'):out.sequence(tuple(range(65537)))
    out=eg._Rows()
    with pytest.raises(ValueError,match='mapping'):out.mapping(dict.fromkeys(range(65537)))
    binding=object();arena=native.make_guard_arena(binding)
    import gc
    for _ in range(20):
        seal=_Seal(());rows=eg._graph_rows(seal);plan=native.compile_guard_plan(arena,binding,seal,rows)
        del seal,rows,plan
    gc.collect()
    seal=_Seal(());plan=native.compile_guard_plan(arena,binding,seal,eg._graph_rows(seal));native.guard_exact_plans(arena,binding,((seal,plan),))
    stats=native.guard_arena_receipt(arena,binding)
    assert stats['workspace_accounting']=='B70_DESCRIPTOR_CLOSURE_V2'and stats['live_workspace_reserved_bytes']<stats['max_live_bytes']


def test_generation_fresh_module_name_is_pinned_before_native_generation(job):
    old=jp._generation_owner.__name__
    try:
        jp._generation_owner.__name__='ops_sim.v5.foreign_generation'
        with pytest.raises(ValueError):job._dispatch_guard('generation',jp._GENERATION_OWNER_BINDING)
    finally:jp._generation_owner.__name__=old
    job._dispatch_guard('generation',jp._GENERATION_OWNER_BINDING)


@pytest.mark.parametrize('boundary',('entry','callback','exit'))
def test_python_dispatch_wrapper_cannot_disable_its_own_native_gate(job,boundary):
    fn=jp.PreparedJobRuntime._dispatch_guard;old=fn.__code__;ran=[]
    def noop(self,operation,argument):return None
    def mutate():fn.__code__=noop.__code__
    try:
        with pytest.raises(ValueError):
            if boundary=='entry':
                mutate()
                with job.transaction():ran.append('body')
            else:
                with job.transaction()as tx:
                    if boundary=='callback':tx.callback(mutate)
                    else:mutate()
                ran.append('publication')
        assert not ran
    finally:fn.__code__=old
    job._full_guard()


def test_removed_plan_and_pin_cannot_turn_native_job_into_reference_fallback(job):
    old=job._guard_plan
    try:
        job._guard_plan=job._guard_plan_pin=None
        with pytest.raises(ValueError):job._full_guard()
    finally:job._guard_plan=job._guard_plan_pin=old
    job._full_guard()

@pytest.mark.parametrize('target',('_guard_identity','_full_guard'))
def test_existing_job_entry_dispatch_code_is_sealed_outside_its_own_execution(job,target):
    fn=getattr(jp.PreparedJobRuntime,target);old=fn.__code__;ran=[]
    if target=='_guard_identity':
        def noop(self):return None
    else:
        def noop(self,transaction=None):return None
    try:
        fn.__code__=noop.__code__
        with pytest.raises(ValueError):
            with job.transaction():ran.append('body')
        assert not ran
    finally:fn.__code__=old
    job._full_guard()


def test_mutable_admission_pins_cannot_self_approve_a_foreign_build(job):
    admission=job._admission;oldraw=admission._build_raw;oldpins=job._admission_pins;ran=[]
    try:
        admission._build_raw=b'{}';pins=list(oldpins);pins[4]=admission._build_raw;job._admission_pins=tuple(pins)
        with pytest.raises(ValueError):
            with job.transaction():ran.append(True)
        assert not ran
    finally:admission._build_raw=oldraw;job._admission_pins=oldpins
    job._full_guard()

@pytest.mark.parametrize('name',('__file__','__name__','__loader__','__spec__'))
def test_actual_native_origin_metadata_is_checked_before_python_dispatch(job,name):
    n=job._guard_plan._native;old=getattr(n,name);ran=[]
    try:
        setattr(n,name,'foreign'if type(old)is str else object())
        with pytest.raises(ValueError):
            with job.transaction():ran.append(True)
        assert not ran
    finally:setattr(n,name,old)
    job._full_guard()

def test_fixed_row_allocation_layout_model_has_explicit_non_rss_headroom():
    import struct
    # Actual CPython allocation shells; original retained graph values are borrowed.
    assert struct.calcsize('P')==8
    row=sys.getsizeof((None,)*7)
    native_row=48
    # List growth/reference slot16 + final tuple slot8. Two seen-indexes,
    # fresh callable wrappers, class-set/temporary slots conservatively176/row.
    fixed=native_row+row+16+8+176
    assert fixed<=512
    for n in (0,1,8,64,512,4096,65536):
        assert sys.getsizeof(tuple([None]*n))<=128+64*n
        assert sys.getsizeof('x'*n)<=128+8*n
