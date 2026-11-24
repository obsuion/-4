from dataclasses import replace
import json
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.spacecraft_project import SpacecraftProject,project_source_identity
from ops_sim.v5.spacecraft_project_document import dumps_project
from ops_sim.v5.project_store import ProjectStore

@pytest.fixture
def setup(tmp_path):
    root=make_inputs(wire='weakness');store=ProjectStore(tmp_path/'external-store',root,create=True)
    project=SpacecraftProject(root,project_source_identity());created=store.create(project)
    return store,created,project

def test_save_load_reopen_preserves_revision_without_new_job(setup):
    store,p,project=setup;text=dumps_project(store.load(p['project_id']))
    loaded=store.load_document(text);assert loaded['project_id']==p['project_id'] and loaded['history_preserved']
    assert not loaded['new_actual_submission']
    reopened=ProjectStore(store.root,project.reference)
    assert dumps_project(reopened.load(p['project_id']))==text and reopened.jobs(p['project_id'])==[]

def test_edit_invalidates_current_preview_and_preserves_old_revision(setup):
    store,p,project=setup;a=store.preview(p['project_id'],p['revision'])
    q=store.edit(p['project_id'],p['revision'],placement='outboard')
    assert q['revision']!=p['revision'] and store.current_preview(p['project_id'],q['revision']) is None
    assert store.current_preview(p['project_id'],p['revision'])==a
    with pytest.raises(ValueError,match='stale'):store.edit(p['project_id'],p['revision'],title='stale')

@pytest.mark.parametrize('path',['../escape','/absolute','C:disk','folder\\escape','..'])
def test_path_containment_before_io(setup,path):
    store,_,_=setup
    with pytest.raises(ValueError):store.path(path)

def test_altered_input_and_preview_reject(setup):
    store,p,project=setup;store.load(p['project_id']);store.preview(p['project_id'],p['revision'])
    path=store.path('projects',p['project_id'],'revisions',p['revision'],'preview.json')
    d=json.loads(path.read_bytes());d['mass_properties']['total_mass_kg']+=1;path.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='preview'):store.current_preview(p['project_id'],p['revision'])
    path=store.path('projects',p['project_id'],'revisions',p['revision'],'input.json');path.write_text('{}')
    with pytest.raises(ValueError,match='altered'):store.load(p['project_id'])

def test_duplicate_submission_and_new_quota_gate(setup):
    store,p,project=setup;store.preview(p['project_id'],p['revision'])
    a,new=store.prepare_job(p['project_id'],p['revision'],'1'*32)
    b,newb=store.prepare_job(p['project_id'],p['revision'],'1'*32)
    assert new and not newb and a['job_id']==b['job_id']
    with pytest.raises(ValueError,match='active'):store.prepare_job(p['project_id'],p['revision'],'2'*32)
    assert len(store.jobs(p['project_id']))==1

def test_unknown_reopen_is_not_completed_or_automatically_restarted(setup):
    store,p,project=setup;store.preview(p['project_id'],p['revision']);j,_=store.prepare_job(p['project_id'],p['revision'],'1'*32)
    reopened=ProjectStore(store.root,project.reference,recover=True)
    assert reopened.job(j['job_id'])['status']=='UNKNOWN'
    with pytest.raises(ValueError):reopened.prepare_job(p['project_id'],p['revision'],'2'*32)

def test_repo_and_existing_directory_reject_before_write(setup,tmp_path):
    store,p,project=setup
    with pytest.raises(ValueError,match='already'):ProjectStore(store.root,project.reference,create=True)
    repo=tmp_path/'fake-repo';repo.mkdir();(repo/'.git').write_text('worktree marker')
    with pytest.raises(ValueError,match='repository'):ProjectStore(repo/'data',project.reference,create=True)
    assert not (repo/'data').exists()

def parent_fixture(store,p):
    from ops_sim.v5.command_document import PACKET,inputs_to_json
    from ops_sim.v5.spacecraft_project import materialize_project
    from ops_sim.v5.design_repair import ConstructorLedger
    from ops_sim.v5.command_estimation import CommandWork
    from dataclasses import asdict
    store.preview(p['project_id'],p['revision'])
    root,_,_=materialize_project(store.load(p['project_id']),ConstructorLedger())
    j,_=store.prepare_job(p['project_id'],p['revision'],'1'*32)
    # Static admission fixture only; never launched as physical authority.
    packet=dict(format=PACKET,version=1,inputs=json.loads(inputs_to_json(root)),root_identity=j['root_identity'],completed_decisions=7,
        scientific=dict(checkpoint=dict(simulation_time_seconds=200)),paid_work=dict(aggregate=asdict(CommandWork())))
    h=store._write(('jobs',j['job_id'],'checkpoint.rolling.json'),packet)
    path=store.path('jobs',j['job_id'],'checkpoint.rolling.json')
    j.update(status='INCOMPLETE',ownership_valid=True,checkpoint=dict(file=path.name,sha256=h,bytes=path.stat().st_size,
        clock=200,pending=['CONTACT'],partial_bits=[7712],completed_decisions=7))
    store.update_job(j);return j

@pytest.mark.parametrize('which',['runtime','interpreter','root','source','clock','method','input'])
def test_parent_drift_rejects_before_constructor_reservation_or_dispatch(setup,monkeypatch,which):
    store,p,_=setup;j=parent_fixture(store,p);paid=dict(store.meta['constructor']);reserved=store.meta['reserved_bytes']
    if which in ('runtime','interpreter'):
        j['runtime']=dict(j['runtime'],**({'python':'foreign'} if which=='runtime' else {'interpreter_sha256':'f'*64}));store.update_job(j)
    elif which in ('root','source'):
        j[which+'_identity']='f'*64;store.update_job(j)
    elif which=='clock':j['checkpoint']['clock']=201;store.update_job(j)
    else:
        q=store.read_json('jobs',j['job_id'],'request.json')
        q['format' if which=='method' else 'project_input_sha256']='foreign'
        store._write(('jobs',j['job_id'],'request.json'),q,mutable=True)
    def forbidden(*a,**k):raise AssertionError('constructor work was entered before rejection')
    monkeypatch.setattr('ops_sim.v5.project_store.ConstructorLedger.reserve',forbidden)
    with pytest.raises(ValueError):store.prepare_job(p['project_id'],p['revision'],'2'*32,resume_job=j['job_id'])
    assert store.meta['constructor']==paid and store.meta['reserved_bytes']==reserved and len(store._project_record(p['project_id'])['jobs'])==1

def test_partial_parent_without_full_science_is_admitted_only_with_bound_runtime(setup):
    store,p,_=setup;j=parent_fixture(store,p)
    next_job,new=store.prepare_job(p['project_id'],p['revision'],'2'*32,resume_job=j['job_id'])
    assert new and next_job['resume_from']==j['job_id']
    assert store.read_json('jobs',next_job['job_id'],'request.json')['resume']['expected_complete_science'] is None

def test_durable_completed_intent_does_not_create_duplicate_paid_job(setup):
    from ops_sim.v5.project_intents import make_intent
    store,p,_=setup;store.preview(p['project_id'],p['revision'])
    intent=make_intent(p['project_id'],p['revision'],'1'*32)
    j,new=store.prepare_job(p['project_id'],p['revision'],'1'*32,intent=intent)
    j.update(status='COMPLETED',ownership_valid=True);store.update_job(j)
    before=(dict(store.meta['constructor']),store.meta['reserved_bytes'])
    assert store.reconcile_intent(intent)['job_id']==j['job_id']
    same,new=store.prepare_job(p['project_id'],p['revision'],'1'*32,intent=intent)
    assert not new and same['job_id']==j['job_id'] and before==(store.meta['constructor'],store.meta['reserved_bytes'])
    different=dict(intent,action_id='2'*32)
    with pytest.raises(ValueError,match='idempotency'):store.prepare_job(p['project_id'],p['revision'],'1'*32,intent=different)
