from types import SimpleNamespace
from http.client import HTTPMessage
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.project_store import ProjectStore
from ops_sim.v5.project_workbench import Workbench,ASSETS

def handler(tmp_path):
    app=Workbench(ProjectStore(tmp_path/'store',make_inputs(wire='weakness'),create=True))
    app.server=SimpleNamespace(server_port=8765)
    h=object.__new__(app.handler());h.headers=HTTPMessage()
    for k,v in [('Host','127.0.0.1:8765'),('Origin','http://127.0.0.1:8765'),('X-CSRF-Token',app.token),('Cookie','kaz-session='+app.session),('Content-Type','application/json')]:h.headers.add_header(k,v)
    return app,h

def test_same_origin_session_csrf_all_required_before_mutation(tmp_path):
    _,h=handler(tmp_path);h.guard(True)

@pytest.mark.parametrize('field,value',[('Host','evil.example'),('Origin','https://evil.example'),('X-CSRF-Token','wrong'),('Cookie','kaz-session=wrong'),('Content-Type','text/plain')])
def test_foreign_requests_reject(tmp_path,field,value):
    _,h=handler(tmp_path);h.headers.replace_header(field,value)
    with pytest.raises(ValueError):h.guard(True)

def test_duplicate_host_and_missing_origin_reject(tmp_path):
    _,h=handler(tmp_path);h.headers.add_header('Host','127.0.0.1:8765')
    with pytest.raises(ValueError):h.guard()
    _,h=handler(tmp_path/'again');del h.headers['Origin']
    with pytest.raises(ValueError):h.guard(True)

def test_assets_use_real_api_and_declared_preview_geometry():
    text=(ASSETS/'index.html').read_text(encoding='utf-8');script=(ASSETS/'workbench.js').read_text(encoding='utf-8')
    for button in ('create','apply','preview','run','stop','resume','save','load','export'):assert 'id="'+button+'"' in text
    assert 'vertices_body_m' in script and 'points_body_m' in script and 'mass_properties' in script
    assert "api('/api/submit'" in script
    assert "submitIntent('INITIAL')" in script and "submitIntent('B48_CAUSAL')" in script and "submitIntent('B51_DIRECT')" in script
    assert 'draft.requireApplied()' in script and 'intents.send(' in script and "api('/api/intent/'" in script
    assert 'chrome.runtime' not in script and 'postMessage' not in script

def test_second_application_owner_refuses_without_touching_pid_or_state(tmp_path):
    app,_=handler(tmp_path);before=app.owner_file.read_bytes()
    with pytest.raises(FileExistsError):Workbench(app.store)
    assert app.owner_file.read_bytes()==before
    app.release_owner();assert not app.owner_file.exists()
