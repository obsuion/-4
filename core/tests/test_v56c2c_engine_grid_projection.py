"""Independent exact containment enumeration and real certified-window composition."""

from dataclasses import fields, replace
from fractions import Fraction
from types import SimpleNamespace
import json
import math
import sys

import pytest

from ops_sim.v5.orbit import TwoBodyTrajectory
from ops_sim.v5.orbit_visibility_windows import GroundVisibilityWindow as Window, GroundVisibilitySearchConfig as Config, TemporalVisibilityStatus as S
from ops_sim.v5.orbit_visibility_grid import EngineGridVisibilityBlock as Block
import ops_sim.v5.orbit_visibility_grid as grid
from test_v56a_time_frame_contracts import _parameter
from test_v56c1_ground_point_contracts import _point, _state
from test_v56c2a_visibility_contracts import _policy
from test_v56c2c_grid_projection_contracts import _inputs, _projection, _arguments


@pytest.mark.parametrize("a,b,g,dt,expected", [
    (12.,137.,0,60,(60,1,120,60)),(12.,137.,12,60,(12,2,132,120)),
    (60.,120.,0,60,(60,1,120,60)),(60.,119.5,0,60,None),
    (59.5,120.,0,60,(60,1,120,60)),(60.125,120.,0,60,None),
    (59.875,120.25,0,60,(60,1,120,60)),(12.,71.5,12,60,None),
    (12.,72.,12,60,(12,1,72,60)),(12.,252.,12,60,(12,4,252,240)),
    (0.,120.,121,60,None),(0.,120.,120,60,None),
    (math.nextafter(60.,math.inf),120.,0,60,None),
    (math.nextafter(60.,-math.inf),120.,0,60,(60,1,120,60)),
    (60.,math.nextafter(120.,-math.inf),0,60,None),
    (60.,math.nextafter(120.,math.inf),0,60,(60,1,120,60)),
    (0.,1.,0,1,(0,1,1,1)),(0.,math.nextafter(1.,0.),0,1,None),
])
def test_hand_solved_half_open_audit_and_adjacent_binary_boundaries(a,b,g,dt,expected):
    result=grid._project_window(Window(a,b),g,dt)
    if expected is None:
        assert result is None
    else:
        assert (result.first_start_time_seconds,result.step_count,result.last_end_time_seconds,
                result.represented_duration_seconds)==expected
        assert result.source_window==Window(a,b)


def _small_reference(a,b,g,dt):
    # Fixed independent enumeration bound: all fixture windows end below128
    # and every dt>=1, hence k>=200 cannot satisfy containment. No production
    # index/floor/ceil helper is used to choose candidates or expected answers.
    return tuple((g+k*dt,g+(k+1)*dt) for k in range(200)
                 if Fraction(g+k*dt)>=Fraction(a) and Fraction(g+(k+1)*dt)<=Fraction(b))


@pytest.mark.parametrize("dt", [1,2,3,7,11,60])
@pytest.mark.parametrize("g", [0,1,5,12,31])
def test_deterministic_small_grid_against_independent_enumeration(dt,g):
    counts={"empty":0,"one":0,"many":0}
    for j in range(41):
        a=((17*j+3)%181)/4
        b=a+(1+(29*j)%201)/8
        expected=_small_reference(a,b,g,dt)
        block=grid._project_window(Window(a,b),g,dt)
        counts["empty" if not expected else "one" if len(expected)==1 else "many"]+=1
        if not expected:
            assert block is None
        else:
            assert block.first_start_time_seconds==expected[0][0]
            assert block.step_count==len(expected)
            assert block.last_end_time_seconds==expected[-1][1]
            assert block.represented_duration_seconds==sum(e-s for s,e in expected)
            assert Fraction(block.first_start_time_seconds)>=Fraction(a)
            assert Fraction(block.last_end_time_seconds)<=Fraction(b)
    assert sum(counts.values())==41


@pytest.mark.parametrize("a,b,g,dt,first,count,last", [
    (0.,2.**40,0,1,0,2**40,2**40),
    (.5,2.**40-.5,0,1,1,2**40-2,2**40-1),
    (12.,2.**40,12,60,12,(2**40-12)//60,12+60*((2**40-12)//60)),
])
def test_huge_counts_are_algebraic_compact_blocks(a,b,g,dt,first,count,last):
    block=grid._project_window(Window(a,b),g,dt)
    assert block.first_start_time_seconds==first and block.step_count==count
    assert block.last_end_time_seconds==last and block.represented_duration_seconds==count*dt
    assert type(block.step_count) is int and type(block.last_end_time_seconds) is int
    assert tuple(f.name for f in fields(block))==("first_start_time_seconds","timestep_seconds","step_count","source_window")
    assert all(not isinstance(getattr(block,f.name),(tuple,list,range,dict)) for f in fields(block))
    small=Block(0,1,1,Window(0.,1.))
    assert sys.getsizeof(block)==sys.getsizeof(small)
    print("C2C_LARGE_BLOCK",json.dumps(dict(first=first,count=count,last=last,duration=count*dt)))


def _assert_blocks_contained(result):
    assert result.timestep_seconds==result.inputs.numerical_config.timestep_seconds
    assert result.total_step_count==sum(b.step_count for b in result.blocks)
    assert type(result.total_step_count) is int
    assert len(result.blocks)<=len(result.search_result.visible_windows)
    assert list(result.blocks)==sorted(result.blocks,key=lambda b:b.first_start_time_seconds)
    for block in result.blocks:
        assert block.source_window in result.search_result.visible_windows
        assert block.first_start_time_seconds>=result.first_step_start_seconds
        assert (block.first_start_time_seconds-result.first_step_start_seconds)%result.timestep_seconds==0
        assert Fraction(block.first_start_time_seconds)>=Fraction(block.source_window.start_seconds)
        assert Fraction(block.last_end_time_seconds)<=Fraction(block.source_window.end_seconds)
        for cell in result.search_result.cells:
            overlap=max(Fraction(block.first_start_time_seconds),Fraction(cell.start_seconds)) < min(Fraction(block.last_end_time_seconds),Fraction(cell.end_seconds))
            if overlap: assert cell.status is S.VISIBLE


def test_real_hidden_pass_one_c2b_call_and_grid_phase_changes(monkeypatch):
    owner,calls,results=grid.find_ground_visibility_windows,[],[]
    def search(*args):
        calls.append(args); result=owner(*args); results.append(result); return result
    monkeypatch.setattr(grid,"find_ground_visibility_windows",search)
    coarse=_projection(inputs=_inputs(60))
    fine=_projection(inputs=_inputs(3))
    phased=replace(fine,first_step_start_seconds=1)
    after=replace(fine,first_step_start_seconds=1000)
    assert len(calls)==4
    for result,search_result,args in zip((coarse,fine,phased,after),results,calls):
        assert result.search_result is search_result
        assert args==(result.inputs,result.point,result.policy,result.search_start_seconds,result.search_end_seconds,result.search_config)
        _assert_blocks_contained(result)
    assert coarse.search_result.visible_windows and not coarse.blocks
    assert fine.total_step_count==1
    assert (fine.blocks[0].first_start_time_seconds,fine.blocks[0].last_end_time_seconds)==(9,12)
    assert not phased.blocks and not after.blocks
    assert fine.search_result==phased.search_result==after.search_result
    assert fine.inputs.model_manifest==phased.inputs.model_manifest==after.inputs.model_manifest
    assert fine.inputs.model_manifest!=coarse.inputs.model_manifest
    visible_duration=sum(w.end_seconds-w.start_seconds for w in fine.search_result.visible_windows)
    assert visible_duration>fine.blocks[0].represented_duration_seconds
    print("C2C_REAL_PASS",json.dumps(dict(certified_visible_seconds=visible_duration,
        coarse_steps=coarse.total_step_count,fine_steps=fine.total_step_count,phase_one_steps=phased.total_step_count)))


def test_real_separated_windows_never_bridge_hidden_gap():
    point=_point(height=3.)
    trajectory=TwoBodyTrajectory(_state(point,r=(-4.,0.,0.),v=(0.,-1.,0.),t=10.),
        _parameter("orbit.gravity.gravitational-parameter","m^3/s^2",4.))
    result=_projection(inputs=_inputs(1,trajectory=trajectory),point=point,policy=_policy(-math.pi/2),
                       search_config=Config(.03125,15000))
    assert len(result.search_result.visible_windows)==len(result.blocks)==2
    assert result.blocks[0].last_end_time_seconds<result.blocks[1].first_start_time_seconds
    assert any(c.status is S.UNRESOLVED for c in result.search_result.cells)
    assert not result.all_search_cells_resolved
    _assert_blocks_contained(result)


def test_unresolved_time_never_becomes_a_block_or_an_exhaustiveness_claim():
    bounded=_projection()
    assert bounded.blocks and bounded.search_result.complete_to_tolerance
    assert any(c.status is S.UNRESOLVED for c in bounded.search_result.cells)
    assert not bounded.all_search_cells_resolved
    limited=_projection(search_config=Config(.001,1))
    assert not limited.blocks and not limited.all_search_cells_resolved
    assert not limited.search_result.complete_to_tolerance
    blocked=_projection(point=_point(height=-.1))
    assert not blocked.blocks and blocked.all_search_cells_resolved
    for result in (bounded,limited,blocked): _assert_blocks_contained(result)


def test_synthetic_unresolved_only_gap_is_never_bridged(monkeypatch):
    # Trusted C2b-call seam fixture for adapter logic only, not physics evidence.
    # The public entry still receives the original seven arguments and invokes
    # its C2b owner; no public precomputed-result input is introduced.
    args=_arguments(inputs=_inputs(60),search_start_seconds=0.,search_end_seconds=180.,
                    search_config=Config(60.,1000))
    cells=tuple(SimpleNamespace(start_seconds=float(i*60),end_seconds=float((i+1)*60),status=status)
                for i,status in enumerate((S.VISIBLE,S.UNRESOLVED,S.VISIBLE)))
    source=SimpleNamespace(inputs=args["inputs"],point=args["point"],policy=args["policy"],
        start_seconds=0.,end_seconds=180.,config=args["search_config"],cells=cells,
        visible_windows=(Window(0.,60.),Window(120.,180.)),complete_to_tolerance=True)
    calls=[]
    def search(*originals):
        calls.append(originals)
        return source
    monkeypatch.setattr(grid,"find_ground_visibility_windows",search)
    result=grid.project_ground_visibility_to_engine_grid(**args)
    assert len(calls)==1 and result.search_result is source
    assert [(b.first_start_time_seconds,b.step_count,b.last_end_time_seconds) for b in result.blocks]==[(0,1,60),(120,1,180)]
    assert result.total_step_count==2 and not result.all_search_cells_resolved
    assert result.search_result.complete_to_tolerance
    _assert_blocks_contained(result)


def test_resolved_visible_search_reports_its_narrow_flag():
    result=_projection(inputs=_inputs(1),search_start_seconds=9.5,search_end_seconds=10.5)
    assert all(c.status is S.VISIBLE for c in result.search_result.cells)
    assert result.all_search_cells_resolved
    assert not result.blocks  # No complete integer-grid step fits [9.5,10.5).
