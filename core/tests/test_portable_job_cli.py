import pytest
from ops_sim.v5.portable_job_cli import main

def test_no_arbitrary_cli_command():
    with pytest.raises(SystemExit):main(['shell','echo'])

def test_cli_inspect_never_dispatches(tmp_path,capsys):
    from ops_sim.v5.portable_job import write_bundle,RESULT,canonical
    p=tmp_path/'result.zip';v=dict(format=RESULT,root_identity='a'*64,jobs=[],read_only=True,native_execution_rights=False,credits_scope='DISPLAY',runtime={})
    write_bundle(p,RESULT,{'view.json':canonical(v)})
    result=main(['inspect-result',str(p)])
    assert result==v and 'false'in capsys.readouterr().out


def test_offline_result_view_does_not_require_science_dependencies(tmp_path,monkeypatch):
    import importlib.metadata
    from ops_sim.v5.portable_job import write_bundle,RESULT,canonical
    p=tmp_path/'result.zip';v=dict(format=RESULT,root_identity='a'*64,jobs=[],read_only=True,native_execution_rights=False,credits_scope='DISPLAY',runtime={})
    write_bundle(p,RESULT,{'view.json':canonical(v)})
    monkeypatch.setattr(importlib.metadata,'version',lambda name:(_ for _ in ()).throw(AssertionError('dependency lookup during read-only view')))
    assert main(['inspect-result',str(p)])==v
