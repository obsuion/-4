"""D1a external identity, immutable composition and unchanged V5.3 ownership."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import ast
import inspect
import math

import numpy as np
import pytest

from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import GroundStationId, GroundTargetId, ImagingRequestId, ObservationOpportunityId
from ops_sim.v5.observation import ImagingRequest, ObservationOpportunity, ObservationPointing
from ops_sim.v5.orbit_observation_opportunity import (
    OrbitDerivedObservationOpportunity as Result, derive_observation_opportunity_for_engine_step as derive,
)
import ops_sim.v5.observation_feasibility as feasibility
import ops_sim.v5.orbit_observation_opportunity as adapter
from test_v50d1_time_engine import _context as generic_context
from test_v53c3_observation_transition_feasibility import _config
from test_v56b1_two_body_contracts import _forge
from test_v56b2_orbit_binding import ComparisonText, PlainText
from test_v56c1_ground_point_contracts import _point
from test_v56c2c_grid_projection_contracts import _arguments as grid_arguments, _inputs


def _target(**changes):
    return _point(identity=GroundTargetId("synthetic"), **changes)


def _request(name="external-request", target=None, priority=1.):
    return ImagingRequest(ImagingRequestId(name), GroundTargetId("synthetic") if target is None else target, priority)


def _arguments(**changes):
    args = grid_arguments()
    args["target"] = _target()
    del args["point"]
    args.update(step_start_seconds=9, request=_request(), opportunity_id=ObservationOpportunityId("external-opportunity"))
    # Keep declaration order identical to the public signature for call checks.
    args = {name: args[name] for name in (
        "inputs", "target", "policy", "search_start_seconds", "search_end_seconds",
        "search_config", "first_step_start_seconds", "step_start_seconds", "request", "opportunity_id")}
    args.update(changes)
    return args


def _result(**changes):
    return derive(**_arguments(**changes))


class IntSubclass(int): pass
class TargetIdSubclass(GroundTargetId): pass
class RequestIdSubclass(ImagingRequestId): pass
class OpportunityIdSubclass(ObservationOpportunityId): pass
class ContraryText(str):
    def __eq__(self, other): return False
    def __ne__(self, other): return str.__ne__(self, other)
    def __hash__(self): raise AssertionError("external text hash must not be used")


def test_required_frozen_slotted_contract_and_no_extra_authority():
    names = tuple(_arguments())
    derived = ("visibility_projection", "supporting_visibility_block", "spacecraft_state", "geometry", "opportunity")
    assert tuple(inspect.signature(Result).parameters) == tuple(inspect.signature(derive).parameters) == names
    assert all(p.default is inspect.Parameter.empty for p in inspect.signature(Result).parameters.values())
    assert Result.__dataclass_params__.frozen and Result.__slots__ == names+derived
    assert tuple(f.name for f in fields(Result) if not f.init) == derived
    assert set(adapter.__all__) == {Result.__name__, derive.__name__}
    with pytest.raises(TypeError): Result()
    result = _result()
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError): result.step_start_seconds = 0
    for name in ("catalog", "common_frame_boresight", "feasible", "scheduled", "acquisition", "serviceable"):
        assert not hasattr(result, name)


def test_derived_fields_cannot_be_injected_and_replace_recomputes_all_owners(monkeypatch):
    result = _result()
    owners = ("project_ground_visibility_to_engine_grid", "evaluate_two_body_state", "evaluate_ground_point_geometry")
    calls = []
    for name in owners:
        owner = getattr(adapter, name)
        def spy(*args, _name=name, _owner=owner):
            calls.append(_name)
            return _owner(*args)
        monkeypatch.setattr(adapter, name, spy)
    for f in fields(Result):
        if f.init: continue
        with pytest.raises(TypeError): Result(**_arguments(), **{f.name: None})
        with pytest.raises((TypeError, ValueError), match="init=False"): replace(result, **{f.name: None})
        calls.clear()
        assert replace(_forge(result, f.name, None)) == result
        assert calls == list(owners)
    with pytest.raises(TypeError): _result(inputs=result.visibility_projection)


@pytest.mark.parametrize("name", ["target", "request", "opportunity_id"])
def test_exact_external_owner_type_before_visibility(monkeypatch, name):
    args = _arguments(); original = args[name]
    subtype = type("Subclass", (type(original),), {})
    args[name] = subtype(**{f.name: getattr(original, f.name) for f in fields(original) if f.init})
    def forbidden(*args): pytest.fail("invalid external owner reached C2c")
    monkeypatch.setattr(adapter, "project_ground_visibility_to_engine_grid", forbidden)
    with pytest.raises(TypeError): derive(**args)
    args[name] = None
    with pytest.raises(TypeError): derive(**args)


@pytest.mark.parametrize("field,value", [
    ("target.point_id", GroundStationId("synthetic")),
    ("target.point_id", TargetIdSubclass("synthetic")),
    ("target.point_id.value", ""), ("target.point_id.value", "BAD"),
    ("target.point_id.value", ComparisonText("synthetic")),
    ("request.request_id", RequestIdSubclass("external-request")),
    ("request.request_id", ObservationOpportunityId("external-request")),
    ("request.request_id.value", ""), ("request.request_id.value", " bad"),
    ("request.request_id.value", None),
    ("request.target_id", GroundStationId("synthetic")),
    ("request.target_id", TargetIdSubclass("synthetic")),
    ("request.target_id.value", "BAD"), ("request.target_id.value", ""),
    ("opportunity_id", OpportunityIdSubclass("external-opportunity")),
    ("opportunity_id", ImagingRequestId("external-opportunity")),
    ("opportunity_id.value", ""), ("opportunity_id.value", True),
    ("opportunity_id.value", "UPPER"), ("opportunity_id.value", "bad "),
])
def test_forged_and_wrong_id_graphs_are_revalidated(field, value):
    name, _, path = field.partition(".")
    args = _arguments()
    args[name] = _forge(args[name], path, value) if path else value
    with pytest.raises((TypeError, ValueError)): derive(**args)


@pytest.mark.parametrize("priority", [True, False, 0, -1, math.nan, math.inf, "1", None])
def test_request_priority_reuses_v53_admission(priority):
    with pytest.raises((TypeError, ValueError)):
        _result(request=_forge(_request(), "priority_weight", priority))


@pytest.mark.parametrize("value", [True, False, 9., Fraction(9), np.int64(9), IntSubclass(9), "9", None])
def test_selected_start_is_exact_builtin_int_before_visibility(monkeypatch, value):
    def forbidden(*args): pytest.fail("non-integer start reached C2c")
    monkeypatch.setattr(adapter, "project_ground_visibility_to_engine_grid", forbidden)
    with pytest.raises(TypeError): _result(step_start_seconds=value)


@pytest.mark.parametrize("start", [-1, 1000, 1001])
def test_selected_start_horizon_domain(start):
    with pytest.raises(ValueError, match="horizon"): _result(step_start_seconds=start)


@pytest.mark.parametrize("changes", [
    {"target": _forge(_target(), "latitude_rad.value", True)},
    {"target": _forge(_target(), "longitude_rad.provenance.units", "deg")},
    {"target": _forge(_target(), "ellipsoidal_height_m.provenance.rationale", "bad\ud800")},
    {"inputs": generic_context().inputs},
    {"inputs": _forge(_inputs(), "numerical_config.timestep_seconds", 4)},
    {"search_config": _forge(grid_arguments()["search_config"], "max_evaluations", True)},
    {"policy": _forge(grid_arguments()["policy"], "minimum_elevation_rad.value", math.nan)},
    {"search_start_seconds": -Fraction(1, 10**1000)},
    {"search_end_seconds": math.inf}, {"first_step_start_seconds": True},
])
def test_original_visibility_graph_is_admitted_by_existing_c2c_owners(changes):
    with pytest.raises((TypeError, ValueError)): _result(**changes)


@pytest.mark.parametrize("field", ["inputs", "policy", "search_config"])
def test_visibility_owner_subclasses_rejected(field):
    args = _arguments(); original = args[field]
    subtype = type("Subclass", (type(original),), {})
    args[field] = subtype(**{f.name: getattr(original, f.name) for f in fields(original) if f.init})
    with pytest.raises(TypeError): derive(**args)


def test_request_target_match_uses_actual_text_even_when_legacy_equality_lies():
    spoof = _request(target=GroundTargetId(ComparisonText("another-target")))
    assert spoof.target_id == _target().point_id
    with pytest.raises(ValueError, match="request target does not match"): _result(request=spoof)
    for text in (PlainText("synthetic"), ContraryText("synthetic"), ComparisonText("synthetic")):
        request = _request(target=GroundTargetId(text))
        result = _result(request=request)
        assert result.request.target_id is request.target_id
        assert result.request.request_id is request.request_id
        assert result.request.priority_weight is request.priority_weight
        assert result.opportunity.request_id is request.request_id


@pytest.mark.parametrize("kind", ["request", "opportunity"])
def test_external_identity_actual_text_controls_equality_and_never_geometry(kind):
    original = _result()
    def changed(text):
        return replace(original, **(
            {"request": _request(name=text)} if kind == "request" else
            {"opportunity_id": ObservationOpportunityId(text)}))
    a = changed(ComparisonText("first-external"))
    b = changed("different-external")
    assert a != b and b != a
    assert a.geometry == b.geometry and a.visibility_projection == b.visibility_projection
    assert a.inputs.model_manifest == b.inputs.model_manifest
    for text in (PlainText("first-external"), ContraryText("first-external"), "first-external"):
        same = changed(text)
        assert same == a and a == same
    assert a.__eq__(object()) is NotImplemented and a != object()
    assert Result.__hash__ is None
    with pytest.raises(TypeError): hash(a)


def test_priority_is_retained_and_affects_evidence_without_changing_geometry():
    original = _result()
    request = _request(priority=Fraction(3, 2))
    changed = replace(original, request=request)
    assert changed.request.priority_weight is request.priority_weight
    assert changed != original and changed.geometry == original.geometry
    assert changed.inputs.model_manifest == original.inputs.model_manifest


def test_owner_failures_propagate_unchanged_without_following_owner_calls(monkeypatch):
    owners = ("project_ground_visibility_to_engine_grid", "evaluate_two_body_state", "evaluate_ground_point_geometry")
    for index, name in enumerate(owners):
        with monkeypatch.context() as patch:
            failure = ValueError("explicit owner failure "+name)
            calls = []
            def fail(*args):
                calls.append(args)
                raise failure
            patch.setattr(adapter, name, fail)
            for following in owners[index+1:]:
                def forbidden(*args): pytest.fail("composition continued after failure")
                patch.setattr(adapter, following, forbidden)
            with pytest.raises(ValueError) as caught: _result()
            assert caught.value is failure and len(calls) == 1


def test_nested_opportunity_is_v53_value_and_visibility_does_not_imply_view_feasibility():
    result = _result()
    nested = result.opportunity
    assert type(nested) is ObservationOpportunity and type(nested.pointing) is ObservationPointing
    assert nested.opportunity_id is result.opportunity_id
    assert nested.request_id is result.request.request_id
    assert feasibility.evaluate_observation_view_feasibility(_config(maximum_view_angle_deg=35.), nested).feasible
    assert not feasibility.evaluate_observation_view_feasibility(_config(maximum_view_angle_deg=1.), nested).feasible
    with pytest.raises(TypeError, match="ObservationOpportunity"):
        feasibility.evaluate_observation_view_feasibility(_config(), result)
    # Existing ScheduledObservationExecution requires start >= window_start and
    # start <= window_end-duration. Their equality proves exactly one legal start
    # without inventing the common-frame boresight needed to build its candidate.
    assert nested.window_end_seconds-nested.imaging_duration_seconds == nested.window_start_seconds == 9


def test_runtime_only_caller_ids_are_revalidated_and_no_feasibility_or_execution(monkeypatch):
    args = _arguments()
    before = deepcopy(args)
    validations = []
    for cls in (GroundTargetId, ImagingRequestId, ObservationOpportunityId):
        owner = cls.__init__
        def spy(self, value, _owner=owner, _cls=cls):
            caller = inspect.currentframe().f_back.f_globals["__name__"]
            if caller == adapter.__name__: validations.append((_cls, value))
            return _owner(self, value)
        monkeypatch.setattr(cls, "__init__", spy)
    def forbidden(*args, **kwargs): pytest.fail("D1a invoked feasibility/execution/persistence")
    monkeypatch.setattr(feasibility, "evaluate_observation_view_feasibility", forbidden)
    monkeypatch.setattr(CheckpointState, "from_context", forbidden)
    for name in ("step", "step_imaging", "step_imaging_to_storage", "step_downlink"):
        monkeypatch.setattr(SimulationEngine, name, forbidden)
    result = derive(**args)
    assert validations == [(ImagingRequestId, args["request"].request_id.value),
                           (GroundTargetId, args["request"].target_id.value),
                           (ObservationOpportunityId, args["opportunity_id"].value)]
    assert result.opportunity.opportunity_id is args["opportunity_id"]
    assert args == before


def test_ast_ownership_call_counts_and_no_step_materialization():
    tree = ast.parse(inspect.getsource(adapter))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imports <= {"__future__", "dataclasses", "math", "context", "frames", "ids", "observation",
        "orbit", "orbit_config", "orbit_geometry", "orbit_visibility", "orbit_visibility_grid", "orbit_visibility_windows"}
    calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    for owner in ("project_ground_visibility_to_engine_grid", "evaluate_two_body_state", "evaluate_ground_point_geometry"):
        assert calls.count(owner) == 1
    for identity in ("GroundTargetId", "ImagingRequestId", "ObservationOpportunityId"):
        call, = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == identity]
        assert len(call.args) == 1 and isinstance(call.args[0], ast.Attribute) and call.args[0].attr == "value"
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert names.isdisjoint({"evaluate_ground_visibility", "find_ground_visibility_windows", "ObservationOpportunityCatalog",
        "ObservationManeuverCandidate", "CommonFrameBoresightDirection", "ADCSBoresightFrameId",
        "evaluate_observation_view_feasibility", "SimulationEngine", "CheckpointState", "source_window",
        "step_count", "range", "hash", "id", "uuid", "round", "isclose", "open", "Fraction"})
    for loop in (n for n in ast.walk(tree) if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "block"):
        identifiers = {n.id for n in ast.walk(loop) if isinstance(n, ast.Name)}
        assert identifiers.isdisjoint({"float", "int", "nextafter", "degrees"})
