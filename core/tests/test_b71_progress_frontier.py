"""B71 independent IMPORT_FROM oracle and actual native boundary cases."""
import ast,builtins,inspect,json,sys,textwrap
from types import ModuleType
import pytest
from test_b70_exact_guards import native,job
from ops_sim.v5 import lifecycle_job_prepared as jp,lifecycle_exact_guards as eg,prepared_input_codec as pc
CASES=(('rolling_document','AssemblyDesign',None),('spacecraft_project_v2_document','EXISTING',()),('spacecraft_project_v3_document','OWNERS',{}))

@pytest.mark.parametrize('name,member,value',CASES)
@pytest.mark.parametrize('boundary',('entry','callback','exit'))
def test_package_only_substitution_at_real_native_boundary(job,name,member,value,boundary):
    package=sys.modules['ops_sim.v5'];original=getattr(package,name)
    copy=ModuleType(original.__name__);copy.__dict__.update(vars(original));setattr(copy,member,jp.EnvironmentAgeingPolicy if value is None else value)
    canonical=sys.modules[original.__name__];root=job.external_root;ran=[]
    before=job._guard_plan._native.guard_process_counts()
    def mutate():setattr(package,name,copy)
    try:
        with pytest.raises(ValueError):
            if boundary=='entry':
                mutate()
                with job.transaction():ran.append('body')
            else:
                with job.transaction()as tx:
                    if boundary=='callback':tx.callback(mutate)
                    else:mutate()
                ran.append('published')
        assert not ran and sys.modules[original.__name__]is canonical and job.external_root is root
        with pytest.raises((ValueError,TypeError)):job._schema.guard()
    finally:setattr(package,name,original)
    job._full_guard();after=job._guard_plan._native.guard_process_counts()
    assert after['completed_plan_descriptor_checks']>before['completed_plan_descriptor_checks']

@pytest.mark.parametrize('name,member,value',CASES)
def test_original_primary_and_traceback_survive_failed_import_exit(job,name,member,value):
    package=sys.modules['ops_sim.v5'];original=getattr(package,name);copy=ModuleType(original.__name__);copy.__dict__.update(vars(original));setattr(copy,member,jp.EnvironmentAgeingPolicy if value is None else value)
    primary=RuntimeError('B71 primary exception');published=[]
    try:
        with pytest.raises(RuntimeError)as got:
            with job.transaction():
                setattr(package,name,copy);raise primary
            published.append(True)
        assert got.value is primary and got.value.__traceback__ and primary.__notes__ and not published
    finally:setattr(package,name,original)
    job._full_guard()

@pytest.mark.parametrize('name,member,value',CASES)
def test_missing_parent_attribute_uses_same_canonical_fallback(job,name,member,value):
    package=sys.modules['ops_sim.v5'];original=getattr(package,name);before=job._guard_plan._native.guard_process_counts()
    try:
        delattr(package,name)
        assert sys.modules[original.__name__]is original
        job._schema.guard();job._full_guard()
        with job.transaction():pass
        assert not hasattr(package,name)
    finally:setattr(package,name,original)
    job._full_guard();assert job._guard_plan._native.guard_process_counts()['completed_plan_descriptor_checks']>before['completed_plan_descriptor_checks']

def test_independent_ast_import_inventory_models_import_name_and_import_from(job):
    from ops_sim.v5.lifecycle_prepared import _Seal
    roots=(pc.PreparedInputCodec._full_snapshot,pc._owner_signature,pc._function_signature,jp._SchemaSeal.guard,_Seal.guard,jp._guard_generation_owner,jp._generation_function_state,pc.fields,pc.typed.check_schema_coverage)
    rows=eg._schema_rows(job._schema)+eg._generation_rows(jp._GENERATION_OWNER_BINDING)
    descriptors={(id(r[1]),r[2],id(r[3]))for r in rows if r[0]==11};expected=set();imports=[]
    # Independently execute only AST import statements with a recording builtin.
    # IMPORT_FROM itself is performed by Python, not a canonical importlib lookup.
    for fn in roots:
        tree=ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if not isinstance(node,ast.ImportFrom)or not node.level:continue
            records=[]
            def importing(name,globals=None,locals=None,fromlist=(),level=0):
                module=builtins.__import__(name,globals,locals,fromlist,level);records.append(module);return module
            env={'__package__':fn.__globals__['__package__'],'__builtins__':dict(vars(builtins),__import__=importing)}
            exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<B71 independent import-only>','exec'),env)
            origin=records[0]
            for alias in node.names:
                value=env[alias.asname or alias.name];expected.add((id(origin),alias.name,id(value)));imports.append((origin.__name__,alias.name))
    assert expected<=descriptors and len(expected)==len(set(imports)) and bool(expected)
    for name,_,_ in CASES:assert ('ops_sim.v5',name)in imports

# Current read/fold tests: only initial admitted frontier, no mission advance.
from copy import deepcopy
from test_lifecycle_b65 import started_pair
from ops_sim.v5 import lifecycle_execution as le
from ops_sim.v5.lifecycle_report import LifecycleReport
from ops_sim.v5.lifecycle_document import canonical


def test_progress_single_summary_exact_fallback_data_fees_and_no_numerical_entries():
    state,_=started_pair();ctx=state.backend_context;old=sys.getprofile();seen=[]
    codes={LifecycleReport.summary.__code__:'summary',LifecycleReport.validate.__code__:'validate'}
    def trace(frame,event,arg):
        if event=='call'and frame.f_code in codes:seen.append(codes[frame.f_code])
    before=ctx.native.native_entry_counts();work0=dict(ctx.job._work);roles0=ctx.actual.snapshot()
    sys.setprofile(trace)
    try:actual,totals=le.progress_frontier_projection(state,resources=True)
    finally:sys.setprofile(old)
    work1=dict(ctx.job._work);roles1=ctx.actual.snapshot()
    assert seen.count('summary')==1 and seen.count('validate')==2
    # Old full fallback on the SAME current state/current native role, inside
    # its own admitted boundary, preserves old logical consumer accounting.
    with ctx.transaction():expected,expected_totals=le._progress_projection(state,_resources=True)
    work2=dict(ctx.job._work);roles2=ctx.actual.snapshot()
    assert canonical(actual)==canonical(expected)and canonical(totals)==canonical(expected_totals)
    assert before==ctx.native.native_entry_counts()
    for n in ('environment_requests','projections'):
        assert work1[n]-work0[n]==work2[n]-work1[n]>0
    assert roles1['requests']-roles0['requests']==roles2['requests']-roles1['requests']
    assert ctx._work['progress_summary_calls']==1 and ctx._work['progress_secondary_validations']==1
    assert ctx._work['progress_frontiers_completed']==1
    assert not ctx.job._active


def test_public_and_worker_frontier_results_are_detached_and_not_cached():
    state,_=started_pair();ctx=state.backend_context;expected=canonical(le.progress_projection(state))
    first,totals=le.progress_frontier_projection(state,resources=True);first['credits']=999;totals['credits']=999
    assert canonical(le.progress_projection(state))==expected
    assert ctx._work['progress_summary_calls']==3
    assert not hasattr(state,'frontier_cache')and not hasattr(state.report,'frontier_cache')


@pytest.mark.parametrize('which',('forecast','foreign-report','stale-report','foreign-source','outside-transaction'))
def test_frontier_refuses_foreign_role_source_stale_data_and_unadmitted_call(which):
    state,reference=started_pair();ctx=state.backend_context;saved=[]
    def replace(owner,name,value):saved.append((owner,name,getattr(owner,name)));setattr(owner,name,value)
    try:
        if which=='forecast':replace(state.physical,'prepared_runtime',ctx.forecast)
        elif which=='foreign-report':replace(state,'report',reference.report)
        elif which=='stale-report':state.report.state['end_seconds']+=1
        elif which=='foreign-source':replace(ctx,'source_binding','f'*64)
        with pytest.raises((ValueError,TypeError)):
            if which=='outside-transaction':le._progress_projection(state,_fold=True)
            else:le.progress_frontier_projection(state)
    finally:
        for owner,name,value in reversed(saved):setattr(owner,name,value)


@pytest.mark.parametrize('mutation',('invalid-report','valid-report-drift','code-exit','primary-exit'))
def test_frontier_mutations_never_publish_and_primary_is_preserved(mutation):
    state,_=started_pair();ctx=state.backend_context;old=sys.getprofile();saved=deepcopy(state.report.state);original=LifecycleReport.validate;code=original.__code__;fired=[];published=[];primary=RuntimeError('B71 original frontier primary')
    def noop(self,*,prepared_runtime=None):return None
    def trace(frame,event,arg):
        # Mutation during the original SECOND logical consumer, after the
        # summary's data snapshot. No production callable replacement for tracing.
        if event=='call'and frame.f_code is original.__code__ and len(fired)<2:
            fired.append(1)
            if len(fired)==2:
                if mutation=='invalid-report':state.report.state['receipt_count']+=1
                elif mutation=='valid-report-drift':state.report.state['current']['minimum_energy_wh']-=0.125
                else:
                    original.__code__=noop.__code__
                    if mutation=='primary-exit':raise primary
    sys.setprofile(trace)
    try:
        with pytest.raises((ValueError,RuntimeError))as caught:
            value=le.progress_frontier_projection(state);published.append(value)
        assert not published
        if mutation=='primary-exit':assert caught.value is primary and primary.__traceback__
    finally:
        sys.setprofile(old);original.__code__=code;state.report.state.clear();state.report.state.update(saved)
    assert not ctx.job._active


def test_worker_source_uses_frontier_after_cadence_without_spanning_checkpoint():
    from ops_sim.v5 import lifecycle_application as app
    text=inspect.getsource(app._reference_execute_worker);tree=ast.parse(textwrap.dedent(text))
    calls=[n for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='progress_frontier_projection']
    assert len(calls)==1
    assert text.index('if last_progress_wall is None')<text.index('frontier_data=progress_frontier_projection')<text.index("journal.emit('boundary',progress)")
    assert 'totals=combine' not in text
    # Current actual mission receipts prove this source caller's execution;
    # this static check alone is deliberately not called runtime acceptance.
