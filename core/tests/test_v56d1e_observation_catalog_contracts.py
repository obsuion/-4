"""Exact bulk shape, actual-text identities and ordered D1b evidence."""

from dataclasses import FrozenInstanceError, fields, replace
import ast
import inspect

import pytest

from ops_sim.v5.ids import ObservationOpportunityId
import ops_sim.v5.orbit_observation_catalog as adapter
from ops_sim.v5.orbit_observation_catalog import OrbitBoundObservationCandidateCatalog as Catalog
from ops_sim.v5.orbit_observation_boresight import OrbitBoundObservationManeuverCandidate as Candidate
from test_v56b1_two_body_contracts import _forge
from test_v56d1b_observation_boresight_contracts import _arguments, _quick


def _candidate(text="opportunity-a", **changes):
    return Candidate(**_arguments(opportunity_id=ObservationOpportunityId(text), **changes))


def _trace(monkeypatch):
    owner, calls = Candidate.__post_init__, []
    def construct(self):
        calls.append(self)
        return owner(self)
    monkeypatch.setattr(Candidate, "__post_init__", construct)
    return calls


def _forbidden(*args, **kwargs):
    pytest.fail("owner reached before complete collection type admission")


class PlainText(str): pass
class AlwaysText(str):
    def __eq__(self, other): return True
    __ne__ = str.__ne__
    def __hash__(self): raise AssertionError("caller hash invoked")
class NeverText(str):
    def __eq__(self, other): return False
    __ne__ = str.__ne__
    def __hash__(self): raise AssertionError("caller hash invoked")
class StringBomb(str):
    def __str__(self): raise AssertionError("caller str invoked")
    def __format__(self, spec): raise AssertionError("caller format invoked")
    def __hash__(self): raise AssertionError("caller hash invoked")
class LongText(str):
    # Exposes the existing owner-admitted length behavior, not a new ID policy.
    def __len__(self): return 1
class TupleSubclass(tuple): pass
class CandidateSubclass(Candidate): pass


class GuardedText(str):
    armed = False
    calls = []

    def _hook(self, name):
        if GuardedText.armed:
            GuardedText.calls.append(name)
            raise AssertionError("new boundary invoked caller " + name)

    def __eq__(self, other):
        self._hook("__eq__")
        return str.__eq__(self, other)

    def __ne__(self, other):
        self._hook("__ne__")
        return str.__ne__(self, other)

    def __hash__(self):
        self._hook("__hash__")
        return str.__hash__(self)

    def __str__(self):
        self._hook("__str__")
        return str.__str__(self)

    def __format__(self, spec):
        self._hook("__format__")
        return str.__format__(self, spec)


def test_required_single_field_frozen_slotted_unhashable_contract(monkeypatch):
    _quick(monkeypatch)
    signature = inspect.signature(Catalog)
    assert tuple(signature.parameters) == ("candidates",)
    assert signature.parameters["candidates"].default is inspect.Parameter.empty
    assert tuple(f.name for f in fields(Catalog)) == ("candidates",)
    assert all(f.init for f in fields(Catalog))
    assert Catalog.__slots__ == ("candidates",)
    assert Catalog.__dataclass_params__.frozen and Catalog.__hash__ is None
    assert adapter.__all__ == ["OrbitBoundObservationCandidateCatalog"]
    with pytest.raises(TypeError): Catalog()
    result = Catalog((_candidate(),))
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError): result.candidates = ()
    with pytest.raises(TypeError): hash(result)
    assert result.__eq__(object()) is NotImplemented
    for name in ("catalog", "index", "cache", "feasible", "scheduled", "opportunity_id"):
        assert not hasattr(result, name)
        with pytest.raises(TypeError): Catalog(result.candidates, **{name: None})
        with pytest.raises(TypeError): replace(result, **{name: None})


def test_empty_never_constructs_d1b(monkeypatch):
    monkeypatch.setattr(Candidate, "__post_init__", _forbidden)
    assert Catalog(()).candidates == ()
    assert Catalog(()) == Catalog(())


def test_singleton_reconstructs_and_retains_original_ids(monkeypatch):
    _quick(monkeypatch)
    original = _candidate(StringBomb("opportunity-a"))
    supplied = (original,)
    calls = _trace(monkeypatch)
    result = Catalog(supplied)
    assert len(calls) == 1 and result.candidates[0] is calls[0]
    assert result.candidates is not supplied and result.candidates[0] is not original
    rebuilt = result.candidates[0]
    assert rebuilt == original
    assert rebuilt.opportunity_id is original.opportunity_id
    assert rebuilt.opportunity_id.value is original.opportunity_id.value
    assert rebuilt.request.request_id is original.request.request_id
    assert rebuilt.request.target_id is original.request.target_id
    assert rebuilt.boresight_frame.frame_id is original.boresight_frame.frame_id


@pytest.mark.parametrize("kind", ["list", "generator", "tuple-subclass", "none", "dict"])
def test_wrong_outer_type_precedes_d1b(monkeypatch, kind):
    _quick(monkeypatch)
    item = _candidate()
    value = {"list": [item], "generator": (x for x in (item,)),
        "tuple-subclass": TupleSubclass((item,)), "none": None, "dict": {0: item}}[kind]
    monkeypatch.setattr(Candidate, "__post_init__", _forbidden)
    with pytest.raises(TypeError, match="exact tuple"): Catalog(value)


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("kind", ["none", "object", "derived", "subclass"])
def test_all_item_types_precede_any_reconstruction(monkeypatch, index, kind):
    _quick(monkeypatch)
    item = _candidate()
    wrong = {"none": None, "object": object(), "derived": item.orbit_observation,
        "subclass": CandidateSubclass(**{f.name: getattr(item, f.name) for f in fields(Candidate) if f.init})}[kind]
    supplied = [item, item, item]
    supplied[index] = wrong
    monkeypatch.setattr(Candidate, "__post_init__", _forbidden)
    with pytest.raises(TypeError, match="only exact"): Catalog(tuple(supplied))


@pytest.mark.parametrize("left_type", [str, PlainText, AlwaysText, NeverText, StringBomb])
@pytest.mark.parametrize("right_type", [str, PlainText, AlwaysText, NeverText, StringBomb])
def test_actual_text_not_caller_equality_defines_duplicates(monkeypatch, left_type, right_type):
    _quick(monkeypatch)
    left = _candidate(left_type("same-opportunity"))
    same = _candidate(right_type("same-opportunity"))
    different = _candidate(right_type("different-opportunity"))
    with pytest.raises(ValueError, match="unique by actual text"): Catalog((left, same))
    result = Catalog((left, different))
    assert tuple(str.__str__(v.opportunity_id.value) for v in result.candidates) == (
        "same-opportunity", "different-opportunity")
    assert result.candidates[0].opportunity_id is left.opportunity_id
    assert result.candidates[1].opportunity_id is different.opportunity_id


def test_nonadjacent_duplicate_and_identical_item_are_rejected(monkeypatch):
    _quick(monkeypatch)
    a, b, another_a = (_candidate(NeverText(t)) for t in ("a", "b", "a"))
    for supplied in ((a, b, another_a), (a, a)):
        with pytest.raises(ValueError, match="unique by actual text"): Catalog(supplied)


@pytest.mark.parametrize("text_type", [str, PlainText, AlwaysText, NeverText, StringBomb, LongText])
def test_base_descriptor_key_is_exact_complete_builtin_text(text_type):
    actual = "long-" + "a" * 200 if text_type is LongText else "actual.id-1"
    identifier = ObservationOpportunityId(text_type(actual))
    key = adapter._opportunity_key(identifier)
    assert key[0] is ObservationOpportunityId and type(key[1]) is str
    assert type(str.__str__(identifier.value)) is str
    assert str.__eq__(key[1], actual) is True and len(key[1]) == len(actual)
    assert identifier.value is not key[1] if text_type is not str else identifier.value is key[1]


def test_long_actual_content_is_neither_truncated_nor_renormalized(monkeypatch):
    _quick(monkeypatch)
    prefix = "a" * 200
    first, second, duplicate = (_candidate(LongText(t)) for t in (prefix + "x", prefix + "y", prefix + "x"))
    assert len(first.opportunity_id.value) == 1
    result = Catalog((first, second))
    assert tuple(str.__str__(c.opportunity_id.value) for c in result.candidates) == (prefix + "x", prefix + "y")
    with pytest.raises(ValueError, match="unique by actual text"): Catalog((first, second, duplicate))


@pytest.mark.parametrize("duplicate", [False, True])
def test_zero_new_uniqueness_hooks_armed_after_last_nested_owner(monkeypatch, duplicate):
    _quick(monkeypatch)
    supplied = tuple(_candidate(GuardedText(t)) for t in ("a", "a" if duplicate else "b"))
    owner, count = Candidate.__post_init__, []
    def construct(self):
        owner(self)
        count.append(self)
        if len(count) == len(supplied):
            GuardedText.calls.clear()
            GuardedText.armed = True
    monkeypatch.setattr(Candidate, "__post_init__", construct)
    try:
        if duplicate:
            with pytest.raises(ValueError, match="unique by actual text"): Catalog(supplied)
        else:
            assert len(Catalog(supplied).candidates) == 2
        assert len(count) == 2 and GuardedText.calls == []
    finally:
        GuardedText.armed = False


def test_ordered_equality_uses_d1b_evidence_without_new_text_hooks(monkeypatch):
    _quick(monkeypatch)
    a, b = _candidate(GuardedText("a")), _candidate(GuardedText("b"))
    left, equal = Catalog((a, b)), Catalog((a, b))
    reverse, short, other = Catalog((b, a)), Catalog((a,)), Catalog((b,))
    changed = replace(a, request=replace(a.request, priority_weight=2.))
    different_evidence = Catalog((changed, b))
    assert left.candidates[0] is not equal.candidates[0]
    GuardedText.calls.clear()
    GuardedText.armed = True
    try:
        assert left == equal and equal == left and not left != equal
        assert left != reverse and reverse != left and left != short and short != other
        assert left != different_evidence and different_evidence != left
        assert left.__eq__(object()) is NotImplemented
        assert GuardedText.calls == []
    finally:
        GuardedText.armed = False


def test_original_order_and_repeated_request_target_and_time_are_allowed(monkeypatch):
    _quick(monkeypatch)
    a, b = _candidate("z"), _candidate("a")
    result = Catalog((a, b))
    assert tuple(c.opportunity_id.value for c in result.candidates) == ("z", "a")
    assert result.candidates[0].request == result.candidates[1].request
    assert result.candidates[0].target == result.candidates[1].target
    assert result.candidates[0].step_start_seconds == result.candidates[1].step_start_seconds


def test_ast_imports_and_calls_exclude_other_owners_and_identity_generation():
    tree = ast.parse(inspect.getsource(adapter))
    imports = {(node.module, tuple(a.name for a in node.names)) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imports == {("__future__", ("annotations",)), ("dataclasses", ("dataclass", "fields")),
        ("ids", ("ObservationOpportunityId",)),
        ("orbit_observation_boresight", ("OrbitBoundObservationManeuverCandidate",))}
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))}
    forbidden = {"sorted", "sort", "hash", "str", "format", "lower", "casefold", "strip", "encode", "normalize",
        "ObservationOpportunityId", "uuid4", "sha256", "TargetCatalog", "ImagingRequestCatalog",
        "ObservationOpportunityCatalog", "ObservationCampaign", "GroundTarget",
        "derive_observation_opportunity_for_engine_step", "project_ground_visibility_to_engine_grid",
        "evaluate_two_body_state", "evaluate_ground_point_geometry", "compute_boresight_transition",
        "evaluate_observation_sequence_feasibility", "evaluate_orbit_bound_observation_transition",
        "evaluate_orbit_bound_observation_sequence_feasibility", "range"}
    assert not calls & forbidden
    assert not any(isinstance(node, ast.JoinedStr) for node in ast.walk(tree))
