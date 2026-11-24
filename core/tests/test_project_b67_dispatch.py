"""General lifecycle inputs must never enter the short rolling executor."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from http.client import HTTPMessage
from io import BytesIO
import json
import pytest

from test_spacecraft_design import common, specification
from ops_sim.v5.spacecraft_project_v2 import SpacecraftProjectV2
from ops_sim.v5.spacecraft_project import project_source_identity
from ops_sim.v5.project_store import ProjectStore
from ops_sim.v5.project_runner import ProjectRunner
from ops_sim.v5.project_workbench import Workbench
from ops_sim.v5.project_intents import make_intent


def bytes_of(root):
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def general(tmp_path, common, specification):
    store = ProjectStore(tmp_path/'store', common.base, create=True)
    project = SpacecraftProjectV2(common, specification, project_source_identity())
    return store, store.create(project), project


@pytest.mark.parametrize('entry', ('store', 'runner', 'resume', 'submit_intent'))
def test_refusal_precedes_any_intent_job_quota_or_launch(general, entry):
    store, record, _ = general
    before = bytes_of(store.root)
    launched = []
    runner = ProjectRunner(store, on_launch=launched.append)
    args = (record['project_id'], record['revision'], '1'*32)
    kwargs = {'resume_job': '2'*32} if entry == 'resume' else {}
    if entry == 'submit_intent':
        kwargs['intent'] = make_intent(*args)
    with pytest.raises(ValueError, match='GENERAL_PROJECT_REQUIRES_FULL_LIFECYCLE_DISPATCH'):
        (store.prepare_job if entry == 'store' else runner.submit)(*args, **kwargs)
    assert bytes_of(store.root) == before
    assert launched == [] and runner.active is None and runner.thread is None
    assert store.jobs(record['project_id']) == []


@pytest.mark.parametrize('route', ('run', 'submit', 'resume'))
def test_http_routes_cannot_bypass_guard(general, route, monkeypatch):
    store, rec, _ = general
    app = Workbench(store)
    app.server = SimpleNamespace(server_port=8765)
    handler = object.__new__(app.handler())
    handler.headers = HTTPMessage()
    for k, v in [('Host', '127.0.0.1:8765'), ('Origin', 'http://127.0.0.1:8765'),
                 ('X-CSRF-Token', app.token), ('Cookie', 'kaz-session='+app.session),
                 ('Content-Type', 'application/json')]:
        handler.headers.add_header(k, v)
    body = dict(project_id=rec['project_id'], revision=rec['revision'], idempotency_key='1'*32)
    if route == 'submit':
        body = make_intent(rec['project_id'], rec['revision'], '1'*32)
    if route == 'resume':
        # A preexisting job lookup cannot authorize another executor type.
        monkeypatch.setattr(store, 'job', lambda jid: dict(job_id=jid, **rec))
        body = dict(job_id='2'*32, idempotency_key='1'*32)
    raw = json.dumps(body).encode()
    handler.headers.add_header('Content-Length', str(len(raw)))
    handler.rfile = BytesIO(raw)
    handler.path = '/api/'+route
    responses = []
    handler.respond = lambda status, value, *a, **k: responses.append((status, value))
    before = bytes_of(store.root)
    try:
        handler.do_POST()
        assert responses == [(400, {'error': 'GENERAL_PROJECT_REQUIRES_FULL_LIFECYCLE_DISPATCH'})]
        assert bytes_of(store.root) == before
        assert app.runner.active is None and app.runner.thread is None
    finally:
        app.release_owner()


def test_worker_defense_before_journal_or_materialization(general, monkeypatch):
    from ops_sim.v5 import project_worker as worker
    from ops_sim.v5.spacecraft_project_document import dumps_project
    store, rec, project = general
    jid = '4'*32
    folder = store.path('jobs', jid)
    folder.mkdir(parents=True)
    raw = dumps_project(project).encode()
    (folder/'project-input.json').write_bytes(raw)
    request = dict(format='M8_ALLOWLISTED_PROJECT_WORKER_REQUEST_V2', job_id=jid,
        project_id=rec['project_id'], revision=rec['revision'],
        source_identity=project.source_identity, root_identity='a'*64,
        project_input_sha256=sha256(raw).hexdigest(), preview_sha256='b'*64,
        constructor_before={}, constructor_reserved={}, runtime={}, resume=None,
        intent=make_intent(rec['project_id'], rec['revision'], '5'*32))
    q = json.dumps(request).encode()
    (folder/'request.json').write_bytes(q)
    before = bytes_of(store.root)
    def forbidden(*a, **k):
        raise AssertionError('numerical/constructor/publication must not be entered')
    monkeypatch.setattr(worker, 'materialize_project', forbidden)
    monkeypatch.setattr(worker, 'start_rolling', forbidden)
    monkeypatch.setattr(worker, 'Journal', forbidden)
    with pytest.raises(ValueError, match='GENERAL_PROJECT_REQUIRES_FULL_LIFECYCLE_DISPATCH'):
        worker.execute(store.root, jid, sha256(q).hexdigest())
    assert bytes_of(store.root) == before
