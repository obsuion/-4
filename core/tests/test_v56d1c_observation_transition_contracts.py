"""D1c reconstruction, hardened binding admission and frozen C2 ownership."""

import ast
from dataclasses import FrozenInstanceError, fields, replace
import inspect

import pytest

from ops_sim.v5.adcs import BoresightTransitionResult, CommonFrameBoresightDirection
from ops_sim.v5.adcs_config import AgilePointingConfig
from ops_sim.v5.ids import ADCSBoresightFrameId, SourceRecordId
import ops_sim.v5.orbit_observation_boresight as d1b
import ops_sim.v5.orbit_observation_transition as adapter
from ops_sim.v5.orbit_observation_transition import (
    OrbitBoundObservationTransition as Result,
    evaluate_orbit_bound_observation_transition as evaluate,
)
from test_v53c2_adcs_boresight_transition import _config
from test_v56b1_two_body_contracts import _forge
from test_v56d1b_observation_boresight_contracts import Binding, _arguments, _quick


Candidate = d1b.OrbitBoundObservationManeuverCandidate


def _pair(monkeypatch):
    _quick(monkeypatch)
    return Candidate(**_arguments()), Candidate(**_arguments())


def _forbidden(*args, **kwargs):
    pytest.fail("invalid admission reached C2")


def _record_composition(monkeypatch):
    calls, returned = [], {}
    construct = Candidate.__post_init__
    compose = d1b.derive_observation_opportunity_for_engine_step
    transition = adapter.compute_boresight_transition
    def constructor(self):
        calls.append("D1b")
        construct(self)
    def observation(*args):
        calls.append("D1a")
        return compose(*args)
    def c2(*args):
        calls.append("C2")
        returned["args"] = args
        returned["result"] = transition(*args)
        return returned["result"]
    monkeypatch.setattr(Candidate, "__post_init__", constructor)
    monkeypatch.setattr(d1b, "derive_observation_opportunity_for_engine_step", observation)
    monkeypatch.setattr(adapter, "compute_boresight_transition", c2)
    return calls, returned


def test_required_frozen_slotted_default_free_public_contract(monkeypatch):
    previous, next = _pair(monkeypatch)
    assert tuple(inspect.signature(Result).parameters) == ("config", "previous", "next")
    assert inspect.signature(Result).parameters == inspect.signature(evaluate).parameters
    assert tuple(f.name for f in fields(Result) if not f.init) == ("transition_result",)
    assert all(p.default is inspect.Parameter.empty for p in inspect.signature(Result).parameters.values())
    assert Result.__dataclass_params__.frozen and Result.__hash__ is None
    assert Result.__slots__ == ("config", "previous", "next", "transition_result")
    result = evaluate(_config(), previous, next)
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError): result.previous = next
    with pytest.raises(TypeError): hash(result)
    with pytest.raises(TypeError): Result()
    assert result.__eq__(object()) is NotImplemented
    assert adapter.__all__ == [Result.__name__, evaluate.__name__]
    assert not any(hasattr(result, name) for name in (
        "feasible", "scheduled", "common_frame", "legacy_start", "legacy_end", "catalog"))


def test_two_public_d1b_constructions_two_owned_d1a_then_one_c2(monkeypatch):
    previous, next = _pair(monkeypatch)
    config = _config()
    calls, returned = _record_composition(monkeypatch)
    result = evaluate(config, previous, next)
    assert calls == ["D1b", "D1a", "D1b", "D1a", "C2"]
    assert result.config == config and result.config is not config
    assert returned["args"][0] is result.config
    assert result.transition_result is returned["result"]
    assert type(result.transition_result) is BoresightTransitionResult
    for retained, source in ((result.previous, previous), (result.next, next)):
        assert retained == source and retained is not source
        assert retained.orbit_observation is not source.orbit_observation
    for ray, retained in zip(returned["args"][1:], (result.previous, result.next)):
        assert type(ray) is CommonFrameBoresightDirection
        assert ray is not retained.common_frame_boresight
        assert (ray.x, ray.y, ray.z) == (retained.common_frame_boresight.x,
            retained.common_frame_boresight.y, retained.common_frame_boresight.z)


@pytest.mark.parametrize("side", ["previous", "next"])
@pytest.mark.parametrize("field", ["orbit_observation", "common_frame_boresight", "maneuver_candidate"])
def test_each_forged_derived_d1b_field_is_ignored_and_recomputed(monkeypatch, side, field):
    previous, next = _pair(monkeypatch)
    args = dict(config=_config(), previous=previous, next=next)
    expected = evaluate(**args)
    args[side] = _forge(args[side], field, object())
    calls, _ = _record_composition(monkeypatch)
    assert evaluate(**args) == expected
    assert calls == ["D1b", "D1a", "D1b", "D1a", "C2"]


def test_replace_recomputes_complete_composition_and_forbids_extra_authority(monkeypatch):
    previous, next = _pair(monkeypatch)
    args = dict(config=_config(), previous=previous, next=next)
    result = evaluate(**args)
    calls, _ = _record_composition(monkeypatch)
    assert replace(_forge(result, "transition_result", object())) == result
    assert calls == ["D1b", "D1a", "D1b", "D1a", "C2"]
    for name in ("transition_result", "angular_separation", "comparison_boresight", "common_frame", "frame_equal"):
        with pytest.raises(TypeError): Result(**args, **{name: None})
        with pytest.raises(TypeError): evaluate(**args, **{name: None})
        with pytest.raises((TypeError, ValueError)): replace(result, **{name: None})
    changed = replace(result, config=_config(settling_seconds=7.))
    assert changed != result and changed.config.post_slew_settling_time_seconds.value == 7.


class ConfigSubclass(AgilePointingConfig): pass
class CandidateSubclass(Candidate): pass


@pytest.mark.parametrize("side", ["config", "previous", "next"])
@pytest.mark.parametrize("variant", ["none", "wrong", "subclass"])
def test_exact_owners_reject_before_any_d1b_or_c2(monkeypatch, side, variant):
    previous, next = _pair(monkeypatch)
    args = dict(config=_config(), previous=previous, next=next)
    source = args[side]
    cls = ConfigSubclass if side == "config" else CandidateSubclass
    values = {f.name: getattr(source, f.name) for f in fields(source) if f.init}
    bad = None if variant == "none" else object() if variant == "wrong" else cls(**values)
    monkeypatch.setattr(Candidate, "__post_init__", _forbidden)
    monkeypatch.setattr(adapter, "compute_boresight_transition", _forbidden)
    with pytest.raises(TypeError, match=side): evaluate(**dict(args, **{side: bad}))


@pytest.mark.parametrize("path,value", [
    ("maximum_view_angle_from_nadir_deg.value", 0.),
    ("post_slew_settling_time_seconds.value", -1.),
    ("slew_time_anchors", ()),
])
def test_existing_config_owner_revalidates_before_composition(monkeypatch, path, value):
    previous, next = _pair(monkeypatch)
    monkeypatch.setattr(Candidate, "__post_init__", _forbidden)
    monkeypatch.setattr(adapter, "compute_boresight_transition", _forbidden)
    with pytest.raises(ValueError): evaluate(_forge(_config(), path, value), previous, next)


@pytest.mark.parametrize("side", ["previous", "next"])
def test_invalid_d1b_init_inputs_reject_before_c2(monkeypatch, side):
    previous, next = _pair(monkeypatch)
    args = dict(config=_config(), previous=previous, next=next)
    args[side] = _forge(args[side], "step_start_seconds", True)
    monkeypatch.setattr(adapter, "compute_boresight_transition", _forbidden)
    with pytest.raises(TypeError): evaluate(**args)


@pytest.mark.parametrize("failure_at", [1, 2])
def test_d1b_owner_failure_propagates_same_exception(monkeypatch, failure_at):
    previous, next = _pair(monkeypatch)
    owner = d1b.derive_observation_opportunity_for_engine_step
    failure, calls = ValueError("D1a reconstruction failure"), []
    def broken(*args):
        calls.append(args)
        if len(calls) == failure_at: raise failure
        return owner(*args)
    monkeypatch.setattr(d1b, "derive_observation_opportunity_for_engine_step", broken)
    monkeypatch.setattr(adapter, "compute_boresight_transition", _forbidden)
    with pytest.raises(ValueError) as caught: evaluate(_config(), previous, next)
    assert caught.value is failure and len(calls) == failure_at


def test_c2_exception_is_not_caught_or_reclassified(monkeypatch):
    previous, next = _pair(monkeypatch)
    failure, calls = ValueError("C2 owner coverage failure"), []
    def broken(*args):
        calls.append(args)
        raise failure
    monkeypatch.setattr(adapter, "compute_boresight_transition", broken)
    with pytest.raises(ValueError) as caught: evaluate(_config(), previous, next)
    assert caught.value is failure and len(calls) == 1


class PlainText(str): pass
class AlwaysEqualText(str):
    def __eq__(self, other): return True
    def __ne__(self, other): return False
    def __hash__(self): raise AssertionError("external label hash")
    def __str__(self): raise AssertionError("external label string conversion")
class NeverEqualText(str):
    def __eq__(self, other): return False
    # StableId admission requires comparison to strip() to preserve actual text.
    def __ne__(self, other): return str.__ne__(self, other)
    def __hash__(self): raise AssertionError("external label hash")
    def __str__(self): raise AssertionError("external label string conversion")


@pytest.mark.parametrize("left_type", [PlainText, AlwaysEqualText, NeverEqualText])
@pytest.mark.parametrize("right_type", [PlainText, AlwaysEqualText, NeverEqualText])
def test_hostile_same_actual_text_shares_exact_original_id_only_in_c2(monkeypatch, left_type, right_type):
    previous, next = _pair(monkeypatch)
    left = ADCSBoresightFrameId(left_type("caller-axes"))
    right = ADCSBoresightFrameId(right_type("caller-axes"))
    previous = replace(previous, boresight_frame=Binding(left, previous.boresight_frame.frame))
    next = replace(next, boresight_frame=Binding(right, next.boresight_frame.frame))
    assert left is not right and previous.boresight_frame == next.boresight_frame
    calls, returned = _record_composition(monkeypatch)
    result = evaluate(_config(), previous, next)
    assert calls == ["D1b", "D1a", "D1b", "D1a", "C2"]
    start, end = returned["args"][1:]
    assert start.frame_id is end.frame_id is left
    assert result.previous.boresight_frame.frame_id is result.previous.common_frame_boresight.frame_id is left
    assert result.next.boresight_frame.frame_id is result.next.common_frame_boresight.frame_id is right
    assert previous.common_frame_boresight.frame_id is left and next.common_frame_boresight.frame_id is right
    ordinary_previous, ordinary_next = _pair(monkeypatch)
    ordinary = evaluate(_config(), ordinary_previous, ordinary_next)
    assert result == ordinary and ordinary == result


@pytest.mark.parametrize("text_type", [str, AlwaysEqualText, NeverEqualText])
def test_different_actual_labels_reject_before_shim_and_c2(monkeypatch, text_type):
    previous, next = _pair(monkeypatch)
    next = replace(next, boresight_frame=Binding(ADCSBoresightFrameId(text_type("other-axes")), next.boresight_frame.frame))
    monkeypatch.setattr(adapter, "CommonFrameBoresightDirection", _forbidden)
    monkeypatch.setattr(adapter, "compute_boresight_transition", _forbidden)
    with pytest.raises(ValueError, match="equal concrete boresight-frame bindings"):
        evaluate(_config(), previous, next)


@pytest.mark.parametrize("side", ["previous", "next"])
@pytest.mark.parametrize("field", ["parameter_id.value", "units", "source_ids", "rationale", "derivation"])
@pytest.mark.parametrize("text_type", [PlainText, AlwaysEqualText, NeverEqualText])
def test_metadata_reconstruction_reuses_d1b_exact_text_guard(monkeypatch, side, field, text_type):
    previous, next = _pair(monkeypatch)
    args = dict(config=_config(), previous=previous, next=next)
    parameter = args[side].boresight_frame.frame.rotation.initial_phase_rad
    if field == "parameter_id.value": value = text_type(parameter.provenance.parameter_id.value)
    elif field == "units": value = text_type(parameter.provenance.units)
    elif field == "source_ids":
        # Existing provenance validation hashes sources before C1/B2 admission.
        source_text = type("SourceText", (text_type,), {"__hash__": str.__hash__})
        value = (SourceRecordId(source_text("external-source")),)
    else: value = text_type("different metadata")
    args[side] = _forge(args[side], "boresight_frame.frame.rotation.initial_phase_rad.provenance." + field, value)
    checked, owner = [], d1b._frame_text
    def guard(frame):
        checked.append(frame)
        return owner(frame)
    monkeypatch.setattr(d1b, "_frame_text", guard)
    monkeypatch.setattr(adapter, "compute_boresight_transition", _forbidden)
    with pytest.raises(TypeError, match="portable text"): evaluate(**args)
    assert checked


def test_production_ast_ownership_scope_and_zero_id_constructors():
    tree = ast.parse(inspect.getsource(adapter))
    permitted = {
        "__future__": {"annotations"}, "dataclasses": {"dataclass", "field", "fields"},
        "adcs": {"BoresightTransitionResult", "CommonFrameBoresightDirection", "compute_boresight_transition"},
        "adcs_config": {"AgilePointingConfig"},
        "orbit_observation_boresight": {"OrbitBoundObservationManeuverCandidate"},
    }
    imports = [(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names]
    assert all(module in permitted and name in permitted[module] for module, name in imports)
    assert not any(isinstance(n, (ast.Import, ast.Try)) for n in ast.walk(tree))
    calls = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert calls.count("compute_boresight_transition") == 1
    assert calls.count("CommonFrameBoresightDirection") == 2
    assert calls.count("OrbitBoundObservationManeuverCandidate") == 1  # one site, two runtime constructions
    assert set(calls) <= {"dataclass", "field", "fields", "type", "getattr", "TypeError", "ValueError",
        "AgilePointingConfig", "OrbitBoundObservationManeuverCandidate", "CommonFrameBoresightDirection",
        "compute_boresight_transition", "OrbitBoundObservationTransition"}
    assert not any(n.endswith("Id") for n in calls)
    assert not any(isinstance(n, (ast.BinOp, ast.AugAssign)) for n in ast.walk(tree))
    assert [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)] == ["object.__setattr__"] * 4
