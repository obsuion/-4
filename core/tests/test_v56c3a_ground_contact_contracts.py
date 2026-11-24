"""C3a station ownership, nested admission and strict V5.5 domain separation."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import ast
import inspect
import math

import pytest

from ops_sim.v5.communications import ServiceableGroundContact, compute_downlink_capacity
from ops_sim.v5.downlink import evaluate_downlink_transmission
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import GroundContactId, GroundStationId, GroundTargetId, ParameterId
from ops_sim.v5.orbit_visibility_grid import EngineGridVisibilityBlock as VisibilityBlock
from ops_sim.v5.orbit_visibility_windows import GroundVisibilityWindow as Window
from ops_sim.v5.orbit_ground_contacts import (
    GeometricGroundContactBlock as Block, GroundStationContactProjection as Projection,
    generate_geometric_ground_contacts as generate,
)
import ops_sim.v5.orbit_ground_contacts as contacts
from test_v50d1_time_engine import _context as generic_context
from test_v55a_contact_capacity import _config as communications_config
from test_v55c_downlink_transmission import _record
from test_v56b1_two_body_contracts import _forge
from test_v56b2_orbit_binding import ComparisonText
from test_v56c1_ground_point_contracts import _point
from test_v56c2c_grid_projection_contracts import _arguments as grid_arguments, _inputs


def _arguments(**changes):
    original = grid_arguments()
    args = dict(inputs=original["inputs"], station=original["point"], policy=original["policy"],
        search_start_seconds=original["search_start_seconds"], search_end_seconds=original["search_end_seconds"],
        search_config=original["search_config"], first_step_start_seconds=original["first_step_start_seconds"])
    args.update(changes)
    return args


def _projection(**changes):
    return generate(**_arguments(**changes))


def _source():
    return VisibilityBlock(12, 60, 2, Window(12., 137.))


class StationSubclass(GroundStationId):
    pass


class BlockSubclass(VisibilityBlock):
    pass


class WindowSubclass(Window):
    pass


def test_public_required_frozen_slotted_contracts_and_delegated_properties():
    names = ("inputs", "station", "policy", "search_start_seconds", "search_end_seconds",
             "search_config", "first_step_start_seconds")
    assert tuple(inspect.signature(Block).parameters) == ("station_id", "source_visibility_block")
    assert tuple(inspect.signature(Projection).parameters) == tuple(inspect.signature(generate).parameters) == names
    for cls in (Block, Projection):
        assert cls.__dataclass_params__.frozen
        assert cls.__slots__ == tuple(f.name for f in fields(cls))
        assert all(p.default is inspect.Parameter.empty for p in inspect.signature(cls).parameters.values())
        with pytest.raises(TypeError): cls()
    result = _projection()
    candidate = Block(GroundStationId("supplied-station"), _source())
    for value in (result, candidate):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError): setattr(value, fields(value)[0].name, None)
    for name, expected in (("first_start_time_seconds", 12), ("timestep_seconds", 60),
                           ("step_count", 2), ("last_end_time_seconds", 132),
                           ("represented_duration_seconds", 120)):
        assert getattr(candidate, name) == getattr(candidate.source_visibility_block, name) == expected
        assert type(getattr(candidate, name)) is int
        assert isinstance(getattr(Block, name), property) and getattr(Block, name).fset is None
        with pytest.raises(TypeError): Block(candidate.station_id, _source(), **{name: expected})
    assert set(contacts.__all__) == {Block.__name__, Projection.__name__, generate.__name__}


def test_derived_fields_are_not_injectable_and_replace_recomposes_once(monkeypatch):
    result = _projection()
    owner, calls = contacts.project_ground_visibility_to_engine_grid, []
    def project(*args):
        calls.append(args)
        return owner(*args)
    monkeypatch.setattr(contacts, "project_ground_visibility_to_engine_grid", project)
    derived = ("visibility_projection", "contact_blocks", "total_step_count", "all_search_cells_resolved")
    assert tuple(f.name for f in fields(Projection) if not f.init) == derived
    for name in derived:
        with pytest.raises(TypeError): Projection(**_arguments(), **{name: None})
        with pytest.raises((TypeError, ValueError), match="init=False"): replace(result, **{name: None})
        calls.clear()
        assert replace(_forge(result, name, None)) == result and len(calls) == 1


@pytest.mark.parametrize("identity", [GroundTargetId("synthetic"), StationSubclass("synthetic"),
    GroundContactId("synthetic"), "synthetic", None])
@pytest.mark.parametrize("origin", [0, 1000])
def test_station_domain_rejected_even_when_no_engine_step_could_fit(identity, origin):
    # Forge only where C1 itself would reject construction; C3a must revalidate.
    point = _forge(_point(), "point_id", identity)
    with pytest.raises(TypeError): _projection(station=point, first_step_start_seconds=origin)
    with pytest.raises(TypeError): Block(identity, _source())


def test_identical_geographic_target_is_valid_c1_input_but_not_c3a_station():
    station = _point()
    target = replace(station, point_id=GroundTargetId(station.point_id.value))
    assert target.geodetic_location == station.geodetic_location
    assert _projection(station=station).station == station
    with pytest.raises(TypeError): _projection(station=target)
    with pytest.raises(TypeError): _projection(station=target, inputs=_inputs(60))


@pytest.mark.parametrize("value", ["", " bad", "BAD", "a:b", "x" * 129, "bad\ud800",
                                  ComparisonText("synthetic"), 1, True, None])
def test_forged_station_id_text_is_revalidated_in_both_public_values(value):
    identity = _forge(GroundStationId("synthetic"), "value", value)
    with pytest.raises((TypeError, ValueError)): Block(identity, _source())
    with pytest.raises((TypeError, ValueError)):
        _projection(station=_forge(_point(), "point_id", identity), first_step_start_seconds=1000)


@pytest.mark.parametrize("source", [None, (12, 60, 2), BlockSubclass(12, 60, 2, Window(12., 137.)),
    _forge(_source(), "first_start_time_seconds", True),
    _forge(_source(), "first_start_time_seconds", 11),
    _forge(_source(), "timestep_seconds", 0),
    _forge(_source(), "timestep_seconds", Fraction(60)),
    _forge(_source(), "step_count", 0),
    _forge(_source(), "step_count", 3),
    _forge(_source(), "step_count", 2.),
    _forge(_source(), "source_window", None),
    _forge(_source(), "source_window", WindowSubclass(12., 137.)),
    _forge(_source(), "source_window.start_seconds", True),
    _forge(_source(), "source_window.end_seconds", math.inf),
    _forge(_source(), "source_window.end_seconds", 131.),
])
def test_source_block_requires_exact_type_and_revalidates_nested_containment(source):
    with pytest.raises((TypeError, ValueError)): Block(GroundStationId("synthetic"), source)


def test_source_reconstruction_canonicalizes_through_existing_c2c_policy():
    class RatioBomb(float):
        def as_integer_ratio(self): raise AssertionError("uncanonicalized numeric adapter")
    source = _forge(_source(), "source_window.start_seconds", RatioBomb(12.))
    candidate = Block(GroundStationId("synthetic"), source)
    assert candidate.source_visibility_block == _source()
    assert candidate.source_visibility_block is not source
    assert type(candidate.source_visibility_block.source_window.start_seconds) is float


@pytest.mark.parametrize("field", ["inputs", "station", "policy", "search_config"])
def test_original_graph_requires_exact_owner_types(field):
    args = _arguments()
    original = args[field]
    subclass = type("ContractSubclass", (type(original),), {})
    args[field] = subclass(**{f.name: getattr(original, f.name) for f in fields(original) if f.init})
    with pytest.raises(TypeError): generate(**args)


@pytest.mark.parametrize("path,value", [
    ("latitude_rad.value", True), ("latitude_rad.value", math.nan), ("latitude_rad.value", 2.),
    ("longitude_rad.provenance.units", "deg"),
    ("ellipsoidal_height_m.provenance.parameter_id", ParameterId("wrong")),
    ("latitude_rad.provenance.rationale", "bad\ud800"),
    ("ellipsoid.name", ComparisonText("Synthetic")),
])
def test_complete_station_graph_is_validated_even_after_search_end(path, value):
    with pytest.raises((TypeError, ValueError)):
        _projection(station=_forge(_point(), path, value), first_step_start_seconds=1000)


@pytest.mark.parametrize("changes", [
    {"inputs": generic_context().inputs},
    {"inputs": _forge(_inputs(), "numerical_config.timestep_seconds", 4)},
    {"policy": _forge(grid_arguments()["policy"], "minimum_elevation_rad.value", math.nan)},
    {"search_config": _forge(grid_arguments()["search_config"], "max_evaluations", True)},
    {"search_start_seconds": -Fraction(1, 10**1000)},
    {"search_end_seconds": math.inf},
    {"search_start_seconds": 2., "search_end_seconds": 2.},
    {"first_step_start_seconds": True}, {"first_step_start_seconds": 0.},
    {"first_step_start_seconds": -1}, {"first_step_start_seconds": 1001},
])
def test_c2c_admission_and_bound_inputs_are_not_bypassed(changes):
    with pytest.raises((TypeError, ValueError)): _projection(**changes)


@pytest.mark.parametrize("origin", [0, 1000])
def test_owner_failure_propagates_unchanged_without_empty_fallback(monkeypatch, origin):
    failure = ValueError("C2c search domain failure")
    calls = []
    def fail(*args):
        calls.append(args)
        raise failure
    monkeypatch.setattr(contacts, "project_ground_visibility_to_engine_grid", fail)
    with pytest.raises(ValueError) as caught: _projection(first_step_start_seconds=origin)
    assert caught.value is failure and len(calls) == 1


def test_v55_serviceable_contact_domain_and_consumers_remain_separate():
    assert tuple(inspect.signature(ServiceableGroundContact).parameters) == (
        "contact_id", "ground_station_id", "start_time_seconds", "end_time_seconds")
    context, record, config = generic_context(), _record(), communications_config()
    before = deepcopy(context)
    result = _projection()
    for evidence in (result, *result.contact_blocks):
        assert not isinstance(evidence, (GroundContactId, ServiceableGroundContact))
        assert all(not hasattr(evidence, name) for name in (
            "contact_id", "serviceable", "capacity_bits", "nominal_downlink_data_rate_bps",
            "start_time_seconds", "end_time_seconds"))
        with pytest.raises(TypeError, match="ServiceableGroundContact"):
            compute_downlink_capacity(config, evidence)
        with pytest.raises(TypeError, match="ServiceableGroundContact"):
            evaluate_downlink_transmission(config, evidence, record, None)
        with pytest.raises(TypeError, match="ServiceableGroundContact"):
            SimulationEngine().step_downlink(context, evidence, record_id=record.record_id)
    assert context == before
    with pytest.raises(TypeError): Block(GroundContactId("synthetic"), _source())
    with pytest.raises(TypeError): Block(GroundStationId("synthetic"), _source(), contact_id=GroundContactId("synthetic"))


def test_ast_no_service_identity_capacity_engine_persistence_or_independent_physics():
    tree = ast.parse(inspect.getsource(contacts))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imports <= {"__future__", "dataclasses", "context", "ids", "orbit_binding", "orbit_config",
                       "orbit_geometry", "orbit_visibility", "orbit_visibility_grid", "orbit_visibility_windows"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    assert names.isdisjoint({"ServiceableGroundContact", "GroundContactId", "compute_downlink_capacity",
        "evaluate_downlink_transmission", "SimulationEngine", "step_downlink", "CheckpointState",
        "ObservationOpportunity", "evaluate_two_body_state", "evaluate_ground_visibility",
        "evaluate_ground_point_geometry", "find_ground_visibility_windows", "_project_window",
        "nominal_downlink_data_rate_bps", "complete_to_tolerance", "search_result", "Fraction",
        "round", "isclose", "nextafter", "range", "hash", "id", "uuid", "uuid4", "open"})
    assert sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "project_ground_visibility_to_engine_grid" for node in ast.walk(tree)) == 1
