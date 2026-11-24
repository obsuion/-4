from fractions import Fraction
from copy import deepcopy
from hashlib import sha256
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.rolling_snapshot_document import GraphCodec
from ops_sim.v5.rolling_snapshot import capture_snapshot,restore_snapshot,METHOD,admit_snapshot
from ops_sim.v5.rolling_execution import start_rolling,scientific_projection,work_projection
from ops_sim.v5.rolling_physics import digest
from ops_sim.v5.project_diagnostics import RestoreWatch
from ops_sim.v5.project_store import runtime_identity

def bindings(state):return dict(root_identity=state.root_identity,revision='1'*64,source_identity='2'*64,
    runtime=runtime_identity(),project_input_sha256='3'*64,method=METHOD,clock=state.physical.context.simulation_time_seconds)

def test_graph_exact_scalars_aliases_and_tuple_list():
    shared=[Fraction(3,7),-0.0,1.5];v=(shared,shared,{Fraction(1,3):[1,'λ'],2:None})
    codec=GraphCodec(())
    w=codec.decode(codec.encode(v))
    assert w[0] is w[1] and w[0][1].hex()==(-0.0).hex() and type(w) is tuple and type(w[0]) is list
    assert w==v

@pytest.mark.parametrize('token',[['float','nan'],['int','01'],['rational','2','4'],['enum','os','system'],['root','0'*64],['ref',True]])
def test_graph_rejects_noncanonical_or_unknown(token):
    c=GraphCodec(());g=c.encode(1);g['value']=token
    with pytest.raises((ValueError,KeyError)):c.decode(g)

def test_graph_cycles_and_unknown_owner_reject():
    c=GraphCodec(());a=[];a.append(a)
    with pytest.raises(ValueError,match='cycle'):c.encode(a)
    with pytest.raises(TypeError):c.encode(object())

def test_initial_owner_snapshot_roundtrip_without_numerical_restore():
    root=make_inputs(wire='weakness');state=start_rolling(root);b=bindings(state)
    before=work_projection(state);raw,paid=capture_snapshot(state,b)
    with RestoreWatch() as watch:restored,report,proof=restore_snapshot(raw,root,expected_sha256=sha256(raw).hexdigest(),expected_bindings=b)
    assert watch.proof()['prefix_force_calls']==0
    assert digest(scientific_projection(restored))==digest(scientific_projection(state))
    assert work_projection(restored)==before and report is None and paid['encoding_bytes']==len(raw)
    assert proof['restored_clock']==128

def test_snapshot_foreign_and_corrupt_reject_before_restore_calls():
    root=make_inputs(wire='weakness');state=start_rolling(root);b=bindings(state);raw,_=capture_snapshot(state,b);h=sha256(raw).hexdigest()
    for bad in (dict(b,revision='4'*64),dict(b,clock=129),dict(b,runtime=dict(b['runtime'],interpreter_sha256='f'*64))):
        with RestoreWatch() as watch:
            with pytest.raises(ValueError):admit_snapshot(raw,expected_sha256=h,expected_bindings=bad)
        assert not any(watch.counts.values())
    with pytest.raises(ValueError):admit_snapshot(raw+b' ',expected_sha256=h,expected_bindings=b)
