"""C2b contracts, adversarial validation, bounded resources and real restart."""

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
from ops_sim.v5.orbit import TwoBodyTrajectory, TwoBodySolverConfig
from ops_sim.v5.orbit_binding import CoastOrbitInputs, COAST_BINDING_VERSION
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.orbit_visibility import GroundVisibilityStatus
import ops_sim.v5.orbit_visibility_windows as windows
from ops_sim.v5.orbit_visibility_windows import (
    GroundVisibilitySearchConfig as Config, GroundVisibilitySearchResult as Result,
    TemporalVisibilityStatus as S, TemporalUnresolvedReason as R,
    TemporalVisibilityCell as Cell, GroundVisibilityWindow as Window,
    find_ground_visibility_windows as find,
)
from test_v50d1_time_engine import _context as generic_context
from test_v56a_time_frame_contracts import _parameter
from test_v56b1_two_body_contracts import _forge
from test_v56b2_orbit_binding import ComparisonText, PlainText
from test_v56c1_ground_point_contracts import _point, _state, _TEXT_PATHS
from test_v56c2a_visibility_contracts import _policy


def _run_inputs(trajectory=None, *, sample=10, horizon=1000, tolerance=1e-10):
    if trajectory is None:
        point = _point()
        trajectory = TwoBodyTrajectory(_state(point, r=(2., 0., 0.), v=(0., 1., 0.), t=10.),
            _parameter("orbit.gravity.gravitational-parameter", "m^3/s^2", 2.))
    legacy = generic_context().inputs
    step = max(60, sample)
    legacy = replace(legacy, numerical_config=replace(legacy.numerical_config,
        timestep_seconds=step, geometry_sample_seconds=sample, checkpoint_interval_seconds=step),
        common_world=replace(legacy.common_world, horizon_seconds=horizon))
    return with_coast_orbit(legacy, CoastOrbitInputs(trajectory, TwoBodySolverConfig(tolerance, 100)))


def _search(inputs=None, point=None, policy=None, start=2., end=18., config=None):
    inputs = _run_inputs() if inputs is None else inputs
    point = _point(ellipsoid=inputs.coast_orbit.trajectory.initial_state.position.frame.ellipsoid) if point is None else point
    return find(inputs, point, _policy(0.) if policy is None else policy, start, end,
                Config(.125, 3000) if config is None else config)


def _coverage(result):
    assert result.cells[0].start_seconds == result.start_seconds
    assert result.cells[-1].end_seconds == result.end_seconds
    assert all(a.end_seconds == b.start_seconds for a, b in zip(result.cells, result.cells[1:]))
    assert all(c.start_seconds < c.end_seconds for c in result.cells)
    assert sum((Fraction(c.end_seconds)-Fraction(c.start_seconds) for c in result.cells), Fraction(0)) == Fraction(result.end_seconds)-Fraction(result.start_seconds)
    assert result.evaluation_count <= result.config.max_evaluations
    for window in result.visible_windows:
        covered = [c for c in result.cells if window.start_seconds <= c.start_seconds < window.end_seconds]
        assert covered and covered[0].start_seconds == window.start_seconds and covered[-1].end_seconds == window.end_seconds
        assert all(c.status is S.VISIBLE for c in covered)
    assert result.complete_to_tolerance == (not any(c.unresolved_reason in (R.EVALUATION_LIMIT, R.TIME_RESOLUTION)
        and Fraction(c.end_seconds)-Fraction(c.start_seconds) > Fraction(result.config.boundary_tolerance_seconds) for c in result.cells))


def test_public_signatures_frozen_slots_default_free_and_derived_outputs():
    classes = (Config, Cell, Window, Result)
    for cls in classes:
        assert cls.__dataclass_params__.frozen
        assert cls.__slots__ == tuple(f.name for f in fields(cls))
        assert all(p.default is inspect.Parameter.empty for p in inspect.signature(cls).parameters.values())
        with pytest.raises(TypeError): cls()
    names = ("inputs", "point", "policy", "start_seconds", "end_seconds", "config")
    assert tuple(inspect.signature(Result).parameters) == tuple(inspect.signature(find).parameters) == names
    assert tuple(inspect.signature(Config).parameters) == ("boundary_tolerance_seconds", "max_evaluations")
    assert tuple(inspect.signature(Cell).parameters) == ("start_seconds", "end_seconds", "status", "representative_seconds",
        "representative", "line_of_sight_temporal_allowance", "elevation_temporal_allowance_rad", "unresolved_reason")
    assert set(S.__members__) == {"VISIBLE", "NOT_VISIBLE", "UNRESOLVED"}
    assert set(R.__members__) == {"BOUNDARY_TOLERANCE", "EVALUATION_LIMIT", "TIME_RESOLUTION"}
    result = _search()
    _coverage(result)
    for value in (result, result.config, *result.cells, *result.visible_windows):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError): setattr(value, fields(value)[0].name, None)
    for name in ("cells", "visible_windows", "evaluation_count", "complete_to_tolerance"):
        with pytest.raises(TypeError): Result(*(getattr(result, n) for n in names), **{name: None})
        assert replace(_forge(result, name, None)) == result
    assert set(windows.__all__) == {cls.__name__ for cls in classes} | {S.__name__, R.__name__, find.__name__}


@pytest.mark.parametrize("value", [True, False, "1", None, complex(1), math.inf, -math.inf,
    math.nan, 0, -1, 2**53+1, Fraction(1, 10**1000)])
def test_invalid_tolerance(value):
    with pytest.raises((TypeError, ValueError)): Config(value, 10)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1., "1", None, np.int64(10)])
def test_budget_requires_exact_positive_builtin_int(value):
    with pytest.raises((TypeError, ValueError)): Config(.1, value)


@pytest.mark.parametrize("which", ["inputs", "config", "point", "policy", "budget"])
def test_exact_domain_types_reject_subclasses(which):
    arguments = dict(inputs=_run_inputs(), point=_point(), policy=_policy(0.),
                     start_seconds=2., end_seconds=18., config=Config(100., 1))
    if which == "budget":
        class IntegerSubclass(int): pass
        with pytest.raises(TypeError): Config(1., IntegerSubclass(1))
        return
    original = arguments[which]
    subclass = type("ContractSubclass", (type(original),), {})
    arguments[which] = subclass(**{f.name:getattr(original,f.name) for f in fields(original) if f.init})
    with pytest.raises(TypeError): find(**arguments)


@pytest.mark.parametrize("start,end", [(True, 2.), (0., False), (math.nan, 2.), (0., math.inf),
    (0., "2"), (None, 2.), (0., 0.), (3., 2.), (-1., 2.), (2**53+1, 2**54),
    (0., 1001.), (0., Fraction(1000)+Fraction(1,10**100)),
    (-Fraction(1,10**1000), 2.), (0., Fraction(1,10**1000))])
def test_original_and_normalized_confinement_rejections(start, end):
    with pytest.raises((TypeError, ValueError)): _search(start=start, end=end)


def test_zero_and_horizon_endpoints_and_original_a_cap():
    result = _search(start=0., end=1000., config=Config(1001., 2))
    _coverage(result)
    inputs = _run_inputs(horizon=2**41)
    with pytest.raises(ValueError): _search(inputs, start=0., end=Fraction(2**40)+Fraction(1,10**100))


def test_missing_coast_wrong_exact_inputs_and_binding_mismatch():
    with pytest.raises(ValueError, match="B2-bound"): _search(generic_context().inputs, _point())
    with pytest.raises(TypeError): find(None, _point(), _policy(0.), 0., 1., Config(.1, 1))
    inputs = _run_inputs()
    for path, value in (("numerical_config.geometry_sample_seconds", 11),
                        ("common_world.horizon_seconds", 1001),
                        ("coast_orbit.solver_config.time_tolerance_seconds", 1e-9)):
        with pytest.raises(ValueError, match="binding"): _search(_forge(inputs, path, value))


@pytest.mark.parametrize("path,value", [("boundary_tolerance_seconds", True),
    ("boundary_tolerance_seconds", Fraction(1,10**1000)), ("max_evaluations", True), ("max_evaluations", 0)])
def test_forged_config_revalidated_even_on_early_exit(path, value):
    with pytest.raises((TypeError, ValueError)): _search(config=_forge(Config(1., 1), path, value))


@pytest.mark.parametrize("path", _TEXT_PATHS)
@pytest.mark.parametrize("value", [ComparisonText("Evidence"), PlainText("Evidence"), "bad\ud800", "bad\udfff"])
def test_point_deep_text_validation_precedes_budget_or_equality(path, value):
    with pytest.raises((TypeError, ValueError)):
        _search(point=_forge(_point(), path, value), config=Config(100., 1))


@pytest.mark.parametrize("path,value", [
    ("minimum_elevation_rad.value", True), ("minimum_elevation_rad.value", math.inf),
    ("minimum_elevation_rad.value", Fraction(math.pi/2)+Fraction(1,10**100)),
    ("minimum_elevation_rad.provenance.units", PlainText("rad")),
    ("minimum_elevation_rad.provenance.rationale", "bad\ud800"),
    ("minimum_elevation_rad.provenance.parameter_id.value", ComparisonText("orbit.visibility.minimum-elevation")),
])
def test_policy_deep_validation_precedes_search(path, value):
    with pytest.raises((TypeError, ValueError)):
        _search(policy=_forge(_policy(0.), path, value), config=Config(100., 1))


def test_complete_ellipsoid_definition_must_match():
    point = _point()
    with pytest.raises(ValueError, match="ellipsoid"):
        _search(point=replace(point, ellipsoid=replace(point.ellipsoid, name="Different evidence")))


def test_admitted_numeric_subclass_is_normalized_before_envelope_arithmetic():
    class RatioBomb(float):
        def as_integer_ratio(self): raise AssertionError("raw numeric adapter used")
    inputs = _run_inputs()
    damaged = _forge(inputs, "coast_orbit.trajectory.initial_state.position.components_m", (RatioBomb(2.), 0., 0.))
    assert _search(damaged) == _search(inputs)


def test_zero_anchored_seed_grid_breadth_first_and_overlapping_search(monkeypatch):
    inputs = _run_inputs(sample=60)
    calls = []
    owner = windows.evaluate_two_body_state
    def evaluate(trajectory, instant, config):
        calls.append(instant.elapsed_seconds)
        return owner(trajectory, instant, config)
    monkeypatch.setattr(windows, "evaluate_two_body_state", evaluate)
    result = _search(inputs, start=12., end=137., config=Config(.125, 4))
    assert calls[:3] == [36., 90., 128.5]
    assert calls[3] == 24.
    _coverage(result)
    calls.clear()
    _search(inputs, start=20., end=150., config=Config(100., 3))
    assert calls == [40., 90., 135.]


@pytest.mark.parametrize("tolerance", [.001, 1., 2.**41])
def test_huge_seed_frontier_after_one_evaluation_is_compact_uncertainty(tolerance):
    # Slow valid orbit keeps the entire confinement in B1's period envelope.
    p = _point()
    trajectory = TwoBodyTrajectory(_state(p, r=(2.,0.,0.), v=(0.,2.**-30,0.), t=0.),
        _parameter("orbit.gravity.gravitational-parameter", "m^3/s^2", 2.**-59))
    inputs = _run_inputs(trajectory, sample=1, horizon=2**40)
    result = _search(inputs, start=0., end=2.**40, config=Config(tolerance, 1))
    _coverage(result)
    assert result.evaluation_count == 1 and len(result.cells) == 2
    tail = result.cells[-1]
    assert tail.start_seconds == 1. and tail.end_seconds == 2.**40
    assert tail.representative is None and tail.status is S.UNRESOLVED
    assert tail.unresolved_reason is (R.BOUNDARY_TOLERANCE if tolerance >= 2**40 else R.EVALUATION_LIMIT)


def test_binary64_midpoint_collapse_without_snapping_or_evaluation(monkeypatch):
    start = float(2**39); end = math.nextafter(start, math.inf)
    p = _point()
    trajectory = TwoBodyTrajectory(_state(p, r=(2.,0.,0.), v=(0.,2.**-30,0.), t=start),
        _parameter("orbit.gravity.gravitational-parameter", "m^3/s^2", 2.**-59))
    inputs = _run_inputs(trajectory, horizon=2**40)
    monkeypatch.setattr(windows, "evaluate_two_body_state", lambda *a: pytest.fail("midpoint was snapped"))
    result = _search(inputs, start=start, end=end, config=Config((end-start)/2, 1))
    assert result.evaluation_count == 0 and not result.complete_to_tolerance
    assert result.cells[0].unresolved_reason is R.TIME_RESOLUTION
    assert result.cells[0].representative is None
    _coverage(result)
    small = _search(inputs, start=start, end=end, config=Config(end-start, 1))
    assert small.complete_to_tolerance and small.cells[0].unresolved_reason is R.BOUNDARY_TOLERANCE


def test_b1_endpoint_span_admission_even_when_no_evaluation_occurs():
    p = _point()
    trajectory = TwoBodyTrajectory(_state(p, r=(2.,0.,0.), v=(0.,2.**-30,0.), t=-2.**39),
        _parameter("orbit.gravity.gravitational-parameter", "m^3/s^2", 2.**-59))
    inputs = _run_inputs(trajectory, horizon=2**40)
    with pytest.raises(ValueError, match="span"):
        _search(inputs, start=2.**39, end=math.nextafter(2.**39, math.inf), config=Config(1., 1))


def test_a_rotation_confinement_endpoints_checked_before_representatives():
    p = _point()
    trajectory = TwoBodyTrajectory(_state(p,r=(2.,0.,0.),v=(0.,1.,0.),rate=2.**19,t=0.),
        _parameter("orbit.gravity.gravitational-parameter","m^3/s^2",2.))
    with pytest.raises(ValueError, match="accumulated-phase"):
        _search(_run_inputs(trajectory),start=0.,end=3.,config=Config(10.,1))


def test_unsupported_b1_anchor_policy_rejects_explicitly():
    with pytest.raises(ValueError, match="position-error budget"):
        _search(_run_inputs(tolerance=1.))


@pytest.mark.parametrize("owner", ["evaluate_two_body_state", "evaluate_ground_visibility"])
def test_unexpected_domain_failures_propagate_and_do_not_become_not_visible(monkeypatch, owner):
    def fail(*args): raise ValueError("deliberate domain failure")
    monkeypatch.setattr(windows, owner, fail)
    with pytest.raises(ValueError, match="deliberate domain failure"): _search(config=Config(.1, 1))


def test_real_coincident_ground_spacecraft_domain_failure_is_not_hidden():
    # At t=10 the radius2 spacecraft meets the height1 geographic point.
    with pytest.raises(ValueError, match="range|coincident|separation"):
        _search(point=_point(height=1.),inputs=_run_inputs(sample=20),config=Config(.1,1))


def test_replace_recomputes_no_global_cache_and_inputs_do_not_mutate(monkeypatch):
    inputs, point, policy, config = _run_inputs(), _point(), _policy(0.), Config(.5, 1000)
    before = deepcopy((inputs, point, policy, config))
    calls = []
    owner = windows.evaluate_ground_visibility
    def evaluate(*args):
        calls.append(args[1].position.instant.elapsed_seconds)
        return owner(*args)
    monkeypatch.setattr(windows, "evaluate_ground_visibility", evaluate)
    result = find(inputs, point, policy, 2., 18., config)
    count = len(calls)
    assert count == result.evaluation_count == len(set(calls))
    calls.clear()
    assert replace(result) == result and len(calls) == count
    assert (inputs, point, policy, config) == before
    changed = replace(result, policy=_policy(.3))
    assert changed != result and changed.inputs is inputs
    assert changed.inputs.model_manifest == result.inputs.model_manifest
    moved = replace(result, point=replace(point, longitude_rad=replace(point.longitude_rad, value=.1)))
    assert moved != result and moved.inputs.model_manifest == result.inputs.model_manifest


def test_real_schema5_json_restart_and_independent_coast_rebuild(monkeypatch):
    context = generic_context()
    inputs = _run_inputs()
    context = replace(context, inputs=inputs)
    payload = CheckpointState.from_context(context).to_dict()
    restored_checkpoint = CheckpointState.from_dict(json.loads(json.dumps(payload, allow_nan=False)))
    coast = CoastOrbitInputs.from_dict(json.loads(json.dumps(inputs.coast_orbit.to_dict(), allow_nan=False)))
    rebound = with_coast_orbit(inputs, coast)
    restored = restored_checkpoint.restore(rebound)
    assert coast == inputs.coast_orbit and coast is not inputs.coast_orbit
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == payload["schema_version"] == 5
    assert COAST_BINDING_VERSION == 1
    assert tuple(payload) == ("schema_version", "simulation_time_seconds", "input_ids", "spacecraft",
        "ground_knowledge", "ground_data_delivery", "mission", "controller", "diagnostics")
    before = deepcopy(context)
    def fail(*args, **kwargs): pytest.fail("search touched checkpoint/engine")
    monkeypatch.setattr(CheckpointState, "from_context", fail)
    for name in ("step", "step_imaging", "step_imaging_to_storage", "step_downlink"):
        monkeypatch.setattr(SimulationEngine, name, fail)
    assert _search(restored.inputs) == _search(inputs)
    assert context == before


def test_module_has_no_operational_or_persistence_dependencies():
    tree = ast.parse(inspect.getsource(windows))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported.isdisjoint({"checkpoint", "engine", "communications", "observation", "observation_feasibility"})
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert names.isdisjoint({"ServiceableGroundContact", "ObservationOpportunity", "SimulationContext", "open"})
