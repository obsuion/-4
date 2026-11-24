"""General input/store/API integration. No worker, mission or browser launched."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from http.client import HTTPMessage
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

from lifetime_support import root_for
from ops_sim.v5.spacecraft_project import (SpacecraftProject,project_source_identity,
    preview_project,edit_project)
from ops_sim.v5.spacecraft_project_v2 import SpacecraftProjectV2,project_from_root
from ops_sim.v5.spacecraft_project_document import dumps_project,loads_project
from ops_sim.v5.design_repair import ConstructorLedger
from ops_sim.v5.project_store import ProjectStore
from ops_sim.v5.project_workbench import Workbench,ASSETS,edited_design_document
from ops_sim.v5.lifecycle_application import LifecycleWorkspace,LifecycleStore
from ops_sim.v5.long_mission_document import canonical_json
from ops_sim.v5.rolling_physics import digest


@pytest.fixture
def project():return project_from_root(root_for(600),title='User authored spacecraft')


def test_v2_dispatch_roundtrip_and_exact_v1_reader_are_separate(project):
    text=dumps_project(project)
    restored=loads_project(text,expected_identity=project.identity,
        expected_source_identity=project.source_identity,expected_reference_identity=digest(project.reference))
    assert type(restored)is SpacecraftProjectV2 and dumps_project(restored)==text
    from examples.m5_command_mission_demo import make_inputs
    legacy=SpacecraftProject(make_inputs(wire='weakness'),project.source_identity)
    assert type(loads_project(dumps_project(legacy)))is SpacecraftProject
    with pytest.raises(ValueError,match='V2 design specification'):
        edit_project(project,placement='compact')
    assert edit_project(project,title='Explicit title edit').title=='Explicit title edit'


def test_json_editor_rebuilds_only_outer_digest_and_keeps_nested_authority(project):
    document=json.loads(dumps_project(project));nested=deepcopy(document['inputs']['common'])
    document['inputs']['title']='New author title'
    with pytest.raises(ValueError,match='content digest'):loads_project(canonical_json(document))
    text=edited_design_document(canonical_json(document),rebuild_outer_digest=True)
    assert json.loads(text)['inputs']['common']==nested
    assert loads_project(text).title=='New author title'
    document=json.loads(text);document['inputs']['common']['digest']='0'*64
    edited=edited_design_document(canonical_json(document),rebuild_outer_digest=True)
    with pytest.raises(ValueError):loads_project(edited)


def test_json_editor_rejects_legacy_boolean_versions_and_nonboolean_permission(project):
    document=json.loads(dumps_project(project))
    document['version']=True
    with pytest.raises(ValueError,match='V2 design'):edited_design_document(canonical_json(document),rebuild_outer_digest=True)
    with pytest.raises(ValueError,match='explicit'):edited_design_document(dumps_project(project),rebuild_outer_digest=1)


def test_saved_general_revision_has_exact_lineage_and_requires_new_preview(project,tmp_path):
    store=ProjectStore(tmp_path/'projects',project.reference,create=True)
    created=store.create(project);pid=created['project_id']
    first=store.preview(pid,project.identity)
    assert first['format']=='B66_PAID_GENERAL_DESIGN_PREVIEW_V2'
    assert first['specification_identity']==project.specification.identity
    changed=replace(project,title='New immutable revision')
    record=store.edit_document(pid,project.identity,dumps_project(changed))
    assert record['revision']==changed.identity
    assert store.current_preview(pid,changed.identity)is None
    assert store.current_preview(pid,project.identity)==first
    reopened=ProjectStore(store.root,project.reference)
    assert dumps_project(reopened.load(pid))==dumps_project(changed)
    assert reopened.load(pid,project.identity).identity==project.identity
    assert reopened.snapshot()['projects'][0]['general_design']is True
    with pytest.raises(ValueError,match='stale'):
        store.edit_document(pid,project.identity,dumps_project(project))


def test_design_lifecycle_binds_document_common_and_spec_without_policy_regeneration(project,tmp_path,monkeypatch):
    store=ProjectStore(tmp_path/'projects',project.reference,create=True)
    created=store.create(project);store.preview(created['project_id'],project.identity)
    workspace=LifecycleWorkspace(tmp_path/'missions',project_store=store)
    body=dict(project_id=created['project_id'],revision=project.identity)
    result=workspace.create_design_project(body);mission=workspace.store(result['root_identity'])
    assert mission.root_input.policy==project.common.policy
    assert mission.root_input.scenario==project.common.scenario
    assert mission.root_input.duration_seconds==project.common.duration_seconds
    assert mission.root_input.sun_mode==project.common.sun_mode
    lineage=mission.meta['project'];raw=mission.path('design-project-input.json').read_bytes()
    assert lineage['revision']==project.identity
    assert lineage['specification_identity']==project.specification.identity
    assert lineage['common_identity']==project.common.identity
    assert lineage['document_sha256']==sha256(raw).hexdigest()
    assert raw.decode()==dumps_project(project)
    # Reopen independently recomputes the supported static spec-to-root binding,
    # with paid preparation, never mission evolution or a physical-prefix replay.
    from ops_sim.v5 import spacecraft_project_v2
    monkeypatch.setattr(spacecraft_project_v2,'materialize_lifecycle_project',lambda *a:pytest.fail('reopen compiled a design'))
    reopened=LifecycleStore(mission.directory)
    assert reopened._design_lineage_constructor_work['compiles']==1
    from ops_sim.v5 import spacecraft_project_document
    monkeypatch.setattr(spacecraft_project_document,'loads_project',lambda *a,**k:pytest.fail('repeat pin reconstructed project/common DATA'))
    reopened._pinned()
    reopened._pinned()
    assert reopened.meta['project']==lineage
    assert workspace.create_design_project(body)['root_identity']==result['root_identity']
    assert reopened.jobs()==[]
    path=reopened.path('design-project-input.json');path.write_bytes(raw+b'\n')
    with pytest.raises(ValueError,match='design document changed'):reopened._pinned()


def test_reopen_does_not_trust_rewritten_project_selfhashes_as_plant_proof(project,tmp_path):
    store=ProjectStore(tmp_path/'projects',project.reference,create=True)
    created=store.create(project);store.preview(created['project_id'],project.identity)
    workspace=LifecycleWorkspace(tmp_path/'missions',project_store=store)
    result=workspace.create_design_project(dict(project_id=created['project_id'],revision=project.identity))
    mission=workspace.store(result['root_identity'])
    spec=project.specification
    assembly=replace(spec.assembly,definitions=tuple(replace(d,mass_kg=d.mass_kg*2.)
        if d.definition_id=='camera' else d for d in spec.assembly.definitions))
    changed=replace(project,specification=replace(spec,assembly=assembly))
    raw=dumps_project(changed).encode()
    mission.path('design-project-input.json').write_bytes(raw)
    meta=json.loads(mission.path('store.json').read_bytes())
    meta['project'].update(revision=changed.identity,specification_identity=changed.specification.identity,
        document_sha256=sha256(raw).hexdigest())
    mission.path('store.json').write_text(canonical_json(meta),encoding='utf-8')
    with pytest.raises(ValueError,match='COMPILED_DESIGN'):
        LifecycleStore(mission.directory)


def _post(app,path,body):
    encoded=canonical_json(body).encode();handler=object.__new__(app.handler())
    handler.headers=HTTPMessage()
    for key,value in [('Host','127.0.0.1:8765'),('Origin','http://127.0.0.1:8765'),
        ('X-CSRF-Token',app.token),('Cookie','kaz-session='+app.session),('Content-Type','application/json'),('Content-Length',str(len(encoded)))]:
        handler.headers.add_header(key,value)
    handler.path=path;handler.rfile=BytesIO(encoded);answer=[]
    handler.respond=lambda status,payload,*a,**k:answer.append((status,payload))
    handler.do_POST()
    assert len(answer)==1
    return answer[0]


def test_actual_http_handler_design_template_import_save_and_apply(project,tmp_path):
    store=ProjectStore(tmp_path/'projects',project.reference,create=True)
    app=Workbench(store,runner=SimpleNamespace(active=None),design_common=project.common)
    app.server=SimpleNamespace(server_port=8765)
    try:
        code,result=_post(app,'/api/design/template',dict(title='An authored template'))
        assert code==200 and result['dispatch']is False and result['mission_origin']=='EXPLICIT_SUPPLIED_COMMON'
        code,created=_post(app,'/api/design/create',dict(document=canonical_json(result['document']),rebuild_outer_digest=False))
        assert code==200
        code,saved=_post(app,'/api/save',dict(project_id=created['project_id'],revision=created['revision']))
        assert code==200
        document=saved['document'];document['inputs']['title']='Edited through JSON'
        code,applied=_post(app,'/api/design/apply',dict(project_id=created['project_id'],revision=created['revision'],
            document=canonical_json(document),rebuild_outer_digest=True))
        assert code==200 and applied['revision']!=created['revision']
        assert store.load(created['project_id']).title=='Edited through JSON'
        assert store.jobs(created['project_id'])==[]
    finally:app.release_owner()


def test_general_ui_routes_real_consumer_and_explicitly_disables_legacy_presets():
    html=(ASSETS/'index.html').read_text(encoding='utf8')
    script=(ASSETS/'workbench.js').read_text(encoding='utf8')
    lifecycle=(ASSETS/'lifecycle.js').read_text(encoding='utf8')
    for name in ('design-new','design-json','design-apply','design-read','design-bind'):
        assert 'id="'+name+'"'in html
    assert "api('/api/design/apply'"in script and "api('/api/design/lifecycle'"in script
    assert 'p.general_design' in script and 'node.disabled=general' in lifecycle
    assert 'Unsupported circuit/orientation' in html
    assert "api('submit',b)"in lifecycle  # Existing actual owned Runner route.
