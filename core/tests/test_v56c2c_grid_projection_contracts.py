"""Exact C2c public contracts, composition ownership and schema-5 restart."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import ast
import inspect
import json
import math

import numpy as np
import pytest

from ops_sim.v5.checkpoint import CheckpointState, CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.context import with_coast_orbit
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.orbit_binding import CoastOrbitInputs, COAST_BINDING_VERSION
from ops_sim.v5.orbit_visibility_windows import (
    GroundVisibilityWindow as Window, GroundVisibilitySearchConfig as Config,
    TemporalVisibilityStatus as S,
)
from ops_sim.v5.orbit_visibility_grid import (
    EngineGridVisibilityBlock as Block, GroundVisibilityGridProjection as Projection,
    project_ground_visibility_to_engine_grid as project,
)
import ops_sim.v5.orbit_visibility_grid as grid
from test_v50d1_time_engine import _context as generic_context
from test_v56b1_two_body_contracts import _forge
from test_v56b2_orbit_binding import ComparisonText
from test_v56c1_ground_point_contracts import _point
from test_v56c2a_visibility_contracts import _policy
from test_v56c2b_window_contracts import _run_inputs


def _inputs(dt=3, *, sample=1, horizon=1000, trajectory=None):
    coast = _run_inputs(trajectory).coast_orbit
    legacy = generic_context().inputs
    legacy = replace(legacy, numerical_config=replace(legacy.numerical_config,
        timestep_seconds=dt, geometry_sample_seconds=sample, checkpoint_interval_seconds=dt),
        common_world=replace(legacy.common_world, horizon_seconds=horizon))
    return with_coast_orbit(legacy, coast)


def _arguments(**changes):
    args = dict(inputs=_inputs(), point=_point(), policy=_policy(0.), search_start_seconds=2.,
        search_end_seconds=18., search_config=Config(.015625,10000), first_step_start_seconds=0)
    args.update(changes)
    return args


def _projection(**changes):
    return project(**_arguments(**changes))


def test_public_required_fields_frozen_slots_and_derived_recomputation(monkeypatch):
    expected_block = ("first_start_time_seconds","timestep_seconds","step_count","source_window")
    names = ("inputs","point","policy","search_start_seconds","search_end_seconds","search_config","first_step_start_seconds")
    assert tuple(inspect.signature(Block).parameters) == expected_block
    assert tuple(inspect.signature(Projection).parameters) == tuple(inspect.signature(project).parameters) == names
    for cls in (Block,Projection):
        assert cls.__dataclass_params__.frozen
        assert cls.__slots__ == tuple(f.name for f in fields(cls))
        assert all(p.default is inspect.Parameter.empty for p in inspect.signature(cls).parameters.values())
        with pytest.raises(TypeError): cls()
    result = _projection()
    for value in (result,*result.blocks):
        assert not hasattr(value,"__dict__")
        with pytest.raises(FrozenInstanceError): setattr(value,fields(value)[0].name,None)
    owner,calls=grid.find_ground_visibility_windows,[]
    def search(*args):
        calls.append(args)
        return owner(*args)
    monkeypatch.setattr(grid,"find_ground_visibility_windows",search)
    for name in ("search_result","timestep_seconds","blocks","total_step_count","all_search_cells_resolved"):
        with pytest.raises(TypeError): Projection(**_arguments(),**{name:None})
        calls.clear()
        assert replace(_forge(result,name,None)) == result and len(calls)==1
    assert set(grid.__all__) == {Block.__name__,Projection.__name__,project.__name__}


class IntSubclass(int): pass


@pytest.mark.parametrize("field", ["first_start_time_seconds","timestep_seconds","step_count"])
@pytest.mark.parametrize("value", [True,False,1.,Fraction(1),np.int64(1),IntSubclass(1),None,"1",math.inf])
def test_block_integer_fields_require_exact_builtin_int(field,value):
    args=dict(first_start_time_seconds=0,timestep_seconds=1,step_count=1,source_window=Window(0.,100.))
    args[field]=value
    with pytest.raises(TypeError): Block(**args)


@pytest.mark.parametrize("first,dt,count", [(-1,1,1),(0,0,1),(0,-1,1),(0,1,0),(0,1,-1)])
def test_block_integer_ranges(first,dt,count):
    with pytest.raises(ValueError): Block(first,dt,count,Window(0.,100.))


@pytest.mark.parametrize("window", [None,(0.,120.),_forge(Window(0.,120.),"start_seconds",True),
    _forge(Window(0.,120.),"end_seconds",math.inf),_forge(Window(0.,120.),"start_seconds",121.),
    _forge(Window(0.,120.),"end_seconds",Fraction(1,10**1000))])
def test_block_source_window_is_exact_and_revalidated(window):
    with pytest.raises((TypeError,ValueError)): Block(60,60,1,window)


def test_window_subclass_rejected_and_canonical_numeric_adapter_rebuilt():
    class WindowSubclass(Window): pass
    with pytest.raises(TypeError): Block(0,1,1,WindowSubclass(0.,2.))
    class RatioBomb(float):
        def as_integer_ratio(self): raise AssertionError("raw source numeric adapter used")
    source=_forge(Window(0.,2.),"start_seconds",RatioBomb(0.))
    assert Block(0,1,1,source) == Block(0,1,1,Window(0.,2.))


@pytest.mark.parametrize("first,end,count", [(0,120.,1),(60,119.5,1),(60,120.,2)])
def test_block_checks_both_containment_boundaries(first,end,count):
    with pytest.raises(ValueError,match="inside"): Block(first,60,count,Window(12.,end))


@pytest.mark.parametrize("origin", [True,False,1.,Fraction(1),np.int64(1),IntSubclass(1),"1",None])
def test_origin_requires_exact_int(origin):
    with pytest.raises(TypeError): _projection(first_step_start_seconds=origin)


@pytest.mark.parametrize("origin", [-1,1001])
def test_origin_must_lie_in_world_horizon(origin):
    with pytest.raises(ValueError,match="horizon"): _projection(first_step_start_seconds=origin)


def test_origin_at_horizon_and_huge_integer_origin_are_valid_empty_compositions(monkeypatch):
    owner,calls=grid.find_ground_visibility_windows,[]
    def search(*args):
        calls.append(args)
        return owner(*args)
    monkeypatch.setattr(grid,"find_ground_visibility_windows",search)
    for horizon in (1000,10**100):
        inputs=_inputs(horizon=horizon)
        result=_projection(inputs=inputs,first_step_start_seconds=horizon)
        assert result.first_step_start_seconds==horizon and not result.blocks and result.total_step_count==0
    assert len(calls)==2


@pytest.mark.parametrize("which", ["inputs","point","policy","search_config"])
def test_exact_original_input_classes_are_revalidated(which):
    args=_arguments(); original=args[which]
    subtype=type("ContractSubclass",(type(original),),{})
    args[which]=subtype(**{f.name:getattr(original,f.name) for f in fields(original) if f.init})
    with pytest.raises(TypeError): project(**args)


def test_binding_and_active_numerical_config_are_not_bypassed():
    inputs=_inputs()
    for path,value in (("numerical_config.timestep_seconds",4),
                       ("numerical_config.timestep_seconds",True),
                       ("common_world.horizon_seconds",1001)):
        with pytest.raises((TypeError,ValueError)):
            _projection(inputs=_forge(inputs,path,value))
    with pytest.raises(ValueError,match="B2-bound"):
        _projection(inputs=generic_context().inputs)
    with pytest.raises(TypeError): project(_projection().search_result,*list(_arguments().values())[1:])


@pytest.mark.parametrize("changes", [
    {"point":_forge(_point(),"point_id.value",ComparisonText("synthetic"))},
    {"policy":_forge(_policy(0.),"minimum_elevation_rad.provenance.rationale","bad\ud800")},
    {"search_config":_forge(Config(.1,1),"max_evaluations",True)},
    {"search_start_seconds":-Fraction(1,10**1000)},
    {"search_end_seconds":Fraction(1000)+Fraction(1,10**100)},
    {"search_start_seconds":2.,"search_end_seconds":2.},
    {"search_end_seconds":math.inf},
])
def test_c2b_validates_original_graph_even_when_origin_is_after_search(changes):
    with pytest.raises((TypeError,ValueError)): _projection(first_step_start_seconds=1000,**changes)


def test_c2b_exception_propagates_instead_of_returning_empty(monkeypatch):
    def fail(*args): raise ValueError("search domain failure")
    monkeypatch.setattr(grid,"find_ground_visibility_windows",fail)
    with pytest.raises(ValueError,match="search domain failure"): _projection(first_step_start_seconds=1000)


def test_real_schema5_restart_rebuilt_coast_and_external_argument_changes(monkeypatch):
    inputs=_inputs();context=replace(generic_context(),inputs=inputs)
    before=deepcopy(context); coast_before=inputs.coast_orbit.to_dict()
    payload=CheckpointState.from_context(context).to_dict()
    recovered=CheckpointState.from_dict(json.loads(json.dumps(payload,allow_nan=False)))
    coast=CoastOrbitInputs.from_dict(json.loads(json.dumps(coast_before,allow_nan=False)))
    rebuilt_inputs=with_coast_orbit(inputs,coast)
    restored=recovered.restore(rebuilt_inputs)
    assert restored==context and coast==inputs.coast_orbit and coast is not inputs.coast_orbit
    assert payload["schema_version"]==CURRENT_CHECKPOINT_SCHEMA_VERSION==5 and COAST_BINDING_VERSION==1
    assert tuple(payload)==("schema_version","simulation_time_seconds","input_ids","spacecraft",
        "ground_knowledge","ground_data_delivery","mission","controller","diagnostics")
    def forbidden(*args,**kwargs): pytest.fail("projection touched engine or checkpoint")
    monkeypatch.setattr(CheckpointState,"from_context",forbidden)
    for name in ("step","step_imaging","step_imaging_to_storage","step_downlink"):
        monkeypatch.setattr(SimulationEngine,name,forbidden)
    args=_arguments(inputs=inputs); original=project(**args)
    assert project(**dict(args,inputs=restored.inputs))==original
    for changes in (
        {"point":replace(args["point"],longitude_rad=replace(args["point"].longitude_rad,value=.1))},
        {"policy":_policy(.2)}, {"search_config":Config(.03125,10000)},
        {"search_start_seconds":3.}, {"search_end_seconds":17.}, {"first_step_start_seconds":1},
    ):
        changed=project(**dict(args,**changes))
        assert changed!=original and changed.inputs.model_manifest==original.inputs.model_manifest
        for name,value in changes.items(): assert getattr(changed,name)==value
    assert context==before and inputs.coast_orbit.to_dict()==coast_before


def test_import_ast_scope_excludes_engine_and_independent_physics():
    tree=ast.parse(inspect.getsource(grid))
    imports={node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)}
    imports|={alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names}
    assert imports.isdisjoint({"engine","checkpoint","communications","observation","observation_feasibility","orbit"})
    identifiers={node.id for node in ast.walk(tree) if isinstance(node,ast.Name)}
    identifiers|={node.attr for node in ast.walk(tree) if isinstance(node,ast.Attribute)}
    assert identifiers.isdisjoint({"evaluate_two_body_state","evaluate_ground_visibility","SimulationContext",
        "SimulationEngine","ServiceableGroundContact","ObservationOpportunity","round","epsilon","isclose","nextafter","open"})
    assert sum(isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
               and node.func.id=="find_ground_visibility_windows" for node in ast.walk(tree))==1
