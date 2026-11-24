import pytest
from ops_sim.v5.project_diagnostics import validate_window,RestoreWatch
from ops_sim.v5.project_intents import make_intent,DIRECT

def test_window_requires_same_supported_committed_domain():
    i=make_intent('1'*32,'2'*64,'3'*32,parent='4'*32,snapshot_sha='5'*64,method=DIRECT,window_end=728)
    assert validate_window(i,200)==728
    with pytest.raises(ValueError):validate_window(i,728)

def test_restore_instrumentation_records_real_calls_and_restores_originals():
    from ops_sim.v5 import long_nominal_provider as owner
    original=owner._gravity
    with RestoreWatch() as watch:
        with pytest.raises(AttributeError):owner._gravity(None,None)
    assert owner._gravity is original
    assert watch.counts['ops_sim.v5.long_nominal_provider._gravity']==1
    with pytest.raises(ValueError):watch.proof()
