"""D1d immutable admission, owner order, hostile identity and consistency."""

import ast
from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import inspect
import math

import numpy as np
import pytest

from ops_sim.v5.adcs_config import AgilePointingConfig
from ops_sim.v5.ids import ADCSBoresightFrameId, ADCSSlewAnchorId, ImagingRequestId, ObservationOpportunityId, ParameterId, SourceRecordId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import ParameterProvenance, ProvenanceClass, ProvenanceStatus, SensitivityRange
from ops_sim.v5.observation_feasibility import ObservationSequenceFeasibilityReason as Reason
import ops_sim.v5.observation_feasibility as c3
import ops_sim.v5.orbit_observation_boresight as d1b
import ops_sim.v5.orbit_observation_transition as d1c
import ops_sim.v5.orbit_observation_sequence as adapter
from ops_sim.v5.orbit_observation_sequence import (
    OrbitBoundObservationSequenceFeasibility as Result,
    evaluate_orbit_bound_observation_sequence_feasibility as evaluate,
)
from test_v53c2_adcs_boresight_transition import _anchor, _config as legacy_config
from test_v56b1_two_body_contracts import _forge
from test_v56d1b_observation_boresight_contracts import Binding
from test_v56d1c_observation_transition_contracts import AlwaysEqualText, NeverEqualText, PlainText
from test_v56d1c_observation_transition_geometry import _snapshots


Candidate = d1b.OrbitBoundObservationManeuverCandidate


def _config(*, maximum=80., duration=2., settling=0.):
    return legacy_config(maximum_view_angle_deg=maximum, settling_seconds=settling,
        anchors=(_anchor("zero", 0., 0.), _anchor("right", 90., duration)))


def _pair(monkeypatch, *, times=(0, 3), phase=0.):
    # Committed D1c seam isolates sequence composition from visibility search;
    # B1 initial-time states, C1 and all D1a/D1b reconstruction remain real.
    return _snapshots(monkeypatch, (1., -1., 0.), times=times, phase=phase)


def _forbidden(*args, **kwargs):
    pytest.fail("later owner reached before required admission")


def _trace(monkeypatch):
    calls, values = [], {}
    owner = Candidate.__post_init__
    def construct(self):
        calls.append("D1b")
        return owner(self)
    monkeypatch.setattr(Candidate, "__post_init__", construct)
    owners = ((d1b, "derive_observation_opportunity_for_engine_step", "D1a"),
        (adapter, "ScheduledObservationExecution", "execution"),
        (adapter, "evaluate_observation_view_feasibility", "view"),
        (adapter, "evaluate_orbit_bound_observation_transition", "D1c"),
        (adapter, "CommonFrameBoresightDirection", "safe-ray"),
        (adapter, "ObservationManeuverCandidate", "safe-candidate"),
        (d1c, "compute_boresight_transition", "D1c-C2"),
        (adapter, "evaluate_observation_sequence_feasibility", "C3"),
        (c3, "evaluate_observation_view_feasibility", "C3-view"),
        (c3, "compute_boresight_transition", "C3-C2"))
    for module, name, label in owners:
        function = getattr(module, name)
        def spy(*args, _function=function, _label=label):
            calls.append(_label)
            result = _function(*args)
            values.setdefault(_label, []).append((args, result))
            return result
        monkeypatch.setattr(module, name, spy)
    return calls, values


PASS_ORDER = ["D1b", "D1a", "D1b", "D1a", "execution", "view", "view", "D1c",
    "D1b", "D1a", "D1b", "D1a", "D1c-C2", "safe-ray", "safe-ray",
    "safe-candidate", "safe-candidate", "execution", "C3", "C3-view", "C3-view", "C3-C2"]
VIEW_ORDER = ["D1b", "D1a", "D1b", "D1a", "execution", "view", "view", "C3", "C3-view", "C3-view"]


def test_public_contract_is_required_frozen_slotted_unhashable(monkeypatch):
    previous, next = _pair(monkeypatch)
    assert tuple(inspect.signature(Result).parameters) == ("config", "previous", "next")
    assert inspect.signature(Result).parameters == inspect.signature(evaluate).parameters
    assert all(p.default is inspect.Parameter.empty for p in inspect.signature(Result).parameters.values())
    derived = ("previous_execution", "transition_evidence", "sequence_result")
    assert tuple(f.name for f in fields(Result) if not f.init) == derived
    assert Result.__slots__ == ("config", "previous", "next", *derived)
    assert Result.__dataclass_params__.frozen and Result.__hash__ is None
    value = evaluate(_config(), previous, next)
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError): value.next = previous
    with pytest.raises(TypeError): hash(value)
    with pytest.raises(TypeError): Result()
    assert value.__eq__(object()) is NotImplemented
    assert adapter.__all__ == [Result.__name__, evaluate.__name__]
    assert not any(hasattr(value, name) for name in ("safe_previous_execution", "safe_next_candidate", "catalog", "scheduled"))


@pytest.mark.parametrize("maximum", [5., 80.])
def test_owner_order_retention_and_intentional_nested_c2_calls(monkeypatch, maximum):
    previous, next = _pair(monkeypatch)
    config = _config(maximum=maximum)
    calls, values = _trace(monkeypatch)
    result = evaluate(config, previous, next)
    assert calls == (VIEW_ORDER if maximum == 5. else PASS_ORDER)
    assert result.config == config and result.config is not config
    assert result.previous == previous and result.previous is not previous
    assert result.next == next and result.next is not next
    assert result.previous_execution is values["execution"][0][1]
    assert result.previous_execution.candidate is result.previous.maneuver_candidate
    assert result.previous_execution.scheduled_start_seconds == previous.step_start_seconds
    assert result.sequence_result is values["C3"][0][1]
    assert type(result.sequence_result) is c3.ObservationSequenceFeasibilityResult
    assert values["view"][0][0][1] is result.previous.orbit_observation.opportunity
    assert values["view"][1][0][1] is result.next.orbit_observation.opportunity
    if maximum == 5.:
        assert result.transition_evidence is None
        assert values["C3"][0][0][1] is result.previous_execution
        assert values["C3"][0][0][2] is result.next.maneuver_candidate
    else:
        assert result.transition_evidence is values["D1c"][0][1]
        assert values["D1c"][0][0] == (result.config, result.previous, result.next)
        assert values["C3"][0][0][1] is not result.previous_execution
        assert values["C3"][0][0][2] is not result.next.maneuver_candidate
        assert result.transition_evidence.transition_result is values["D1c-C2"][0][1]
        assert result.sequence_result.transition_result is values["C3-C2"][0][1]
        assert result.sequence_result.transition_result == result.transition_evidence.transition_result


class ConfigSubclass(AgilePointingConfig): pass
class CandidateSubclass(Candidate): pass


@pytest.mark.parametrize("field", ["config", "previous", "next"])
@pytest.mark.parametrize("kind", ["none", "wrong", "subclass"])
def test_all_exact_types_are_admitted_before_config_reconstruction(monkeypatch, field, kind):
    previous, next = _pair(monkeypatch)
    args = dict(config=_config(), previous=previous, next=next)
    value = args[field]
    subclass = ConfigSubclass if field == "config" else CandidateSubclass
    values = {f.name: getattr(value, f.name) for f in fields(value) if f.init}
    args[field] = None if kind == "none" else object() if kind == "wrong" else subclass(**values)
    monkeypatch.setattr(AgilePointingConfig, "__post_init__", _forbidden)
    monkeypatch.setattr(Candidate, "__post_init__", _forbidden)
    with pytest.raises(TypeError, match=field): evaluate(**args)


@pytest.mark.parametrize("path,value", [("maximum_view_angle_from_nadir_deg.value", 90.),
    ("post_slew_settling_time_seconds.value", -1.), ("slew_time_anchors", ())])
def test_config_owner_revalidation_precedes_d1b(monkeypatch, path, value):
    previous, next = _pair(monkeypatch)
    monkeypatch.setattr(Candidate, "__post_init__", _forbidden)
    with pytest.raises(ValueError): evaluate(_forge(_config(), path, value), previous, next)


@pytest.mark.parametrize("side", ["previous", "next"])
def test_invalid_d1b_init_precedes_view_or_transition(monkeypatch, side):
    previous, next = _pair(monkeypatch)
    args = dict(config=_config(), previous=previous, next=next)
    args[side] = _forge(args[side], "step_start_seconds", True)
    for name in ("ScheduledObservationExecution", "evaluate_observation_view_feasibility",
                 "evaluate_orbit_bound_observation_transition", "evaluate_observation_sequence_feasibility"):
        monkeypatch.setattr(adapter, name, _forbidden)
    with pytest.raises(TypeError): evaluate(**args)


@pytest.mark.parametrize("index", [1, 2])
def test_d1b_reconstruction_failure_order_and_exception_identity(monkeypatch, index):
    previous, next = _pair(monkeypatch)
    owner, calls, failure = d1b.derive_observation_opportunity_for_engine_step, [], ValueError("D1a failure")
    def broken(*args):
        calls.append(args)
        if len(calls) == index: raise failure
        return owner(*args)
    monkeypatch.setattr(d1b, "derive_observation_opportunity_for_engine_step", broken)
    monkeypatch.setattr(adapter, "ScheduledObservationExecution", _forbidden)
    monkeypatch.setattr(adapter, "evaluate_observation_view_feasibility", _forbidden)
    with pytest.raises(ValueError) as caught: evaluate(_config(), previous, next)
    assert caught.value is failure and len(calls) == index


@pytest.mark.parametrize("side", ["previous", "next"])
@pytest.mark.parametrize("field", ["parameter_id.value", "units", "source_ids", "rationale", "derivation"])
def test_d1b_metadata_guard_precedes_even_a_decisive_view_failure(monkeypatch, side, field):
    previous, next = _pair(monkeypatch)
    args = dict(config=_config(maximum=5.), previous=previous, next=next)
    metadata = args[side].boresight_frame.frame.rotation.initial_phase_rad.provenance
    value = (SourceRecordId(PlainText("external-source")),) if field == "source_ids" else PlainText(
        metadata.parameter_id.value if field == "parameter_id.value" else getattr(metadata, field) or "changed")
    args[side] = _forge(args[side], "boresight_frame.frame.rotation.initial_phase_rad.provenance." + field, value)
    monkeypatch.setattr(adapter, "evaluate_observation_view_feasibility", _forbidden)
    monkeypatch.setattr(adapter, "evaluate_orbit_bound_observation_transition", _forbidden)
    with pytest.raises(TypeError, match="portable text"): evaluate(**args)


@pytest.mark.parametrize("side", ["previous", "next"])
@pytest.mark.parametrize("field", ["orbit_observation", "common_frame_boresight", "maneuver_candidate"])
@pytest.mark.parametrize("maximum", [5., 80.])
def test_supplied_derived_d1b_fields_are_ignored(monkeypatch, side, field, maximum):
    previous, next = _pair(monkeypatch)
    args = dict(config=_config(maximum=maximum), previous=previous, next=next)
    expected = evaluate(**args)
    args[side] = _forge(args[side], field, object())
    calls, _ = _trace(monkeypatch)
    assert evaluate(**args) == expected
    assert calls == (VIEW_ORDER if maximum == 5. else PASS_ORDER)


@pytest.mark.parametrize("field", ["previous_execution", "transition_evidence", "sequence_result"])
def test_replace_recomputes_all_outputs_and_no_injection(monkeypatch, field):
    previous, next = _pair(monkeypatch)
    args = dict(config=_config(), previous=previous, next=next)
    original = evaluate(**args)
    calls, _ = _trace(monkeypatch)
    assert replace(_forge(original, field, object())) == original
    assert calls == PASS_ORDER
    for name in (field, "view_result", "transition_result", "candidate_next_start", "frame_equal"):
        with pytest.raises(TypeError): Result(**args, **{name: None})
        with pytest.raises(TypeError): evaluate(**args, **{name: None})
        with pytest.raises((ValueError, TypeError)): replace(original, **{name: None})


@pytest.mark.parametrize("owner", ["ScheduledObservationExecution", "evaluate_observation_view_feasibility",
    "evaluate_orbit_bound_observation_transition", "evaluate_observation_sequence_feasibility"])
def test_owner_exception_objects_propagate_unchanged(monkeypatch, owner):
    previous, next = _pair(monkeypatch)
    failure, reached = ValueError("existing owner failed"), []
    def broken(*args):
        reached.append(args)
        raise failure
    monkeypatch.setattr(adapter, owner, broken)
    if owner != "evaluate_observation_sequence_feasibility":
        monkeypatch.setattr(adapter, "evaluate_observation_sequence_feasibility", _forbidden)
    with pytest.raises(ValueError) as caught: evaluate(_config(), previous, next)
    assert caught.value is failure and len(reached) == 1


@pytest.mark.parametrize("left_type", [PlainText, AlwaysEqualText, NeverEqualText])
@pytest.mark.parametrize("right_type", [PlainText, AlwaysEqualText, NeverEqualText])
def test_hostile_same_frame_labels_safe_c3_pair_preserves_original_ids(monkeypatch, left_type, right_type):
    previous, next = _pair(monkeypatch)
    plain = evaluate(_config(), previous, next)
    left, right = ADCSBoresightFrameId(left_type("caller-axes")), ADCSBoresightFrameId(right_type("caller-axes"))
    previous = replace(previous, boresight_frame=Binding(left, previous.boresight_frame.frame))
    next = replace(next, boresight_frame=Binding(right, next.boresight_frame.frame))
    calls, values = _trace(monkeypatch)
    result = evaluate(_config(), previous, next)
    assert calls == PASS_ORDER
    assert result == plain and plain == result
    assert result.previous.boresight_frame.frame_id is result.previous.common_frame_boresight.frame_id is left
    assert result.next.boresight_frame.frame_id is result.next.common_frame_boresight.frame_id is right
    assert result.previous_execution.candidate.common_frame_boresight.frame_id is left
    for label in ("D1c-C2", "C3-C2"):
        start, end = values[label][0][0][1:]
        assert start.frame_id is end.frame_id is left
        for ray, source in ((start, result.previous), (end, result.next)):
            assert (ray.x, ray.y, ray.z) == tuple(getattr(source.common_frame_boresight, a) for a in ("x", "y", "z"))
    assert previous.common_frame_boresight.frame_id is left and next.common_frame_boresight.frame_id is right
    assert result.sequence_result.transition_result == result.transition_evidence.transition_result


@pytest.mark.parametrize("type_", [str, AlwaysEqualText, NeverEqualText])
def test_different_actual_labels_are_rejected_by_d1c_before_c3(monkeypatch, type_):
    previous, next = _pair(monkeypatch)
    next = replace(next, boresight_frame=Binding(ADCSBoresightFrameId(type_("other-axes")), next.boresight_frame.frame))
    for name in ("CommonFrameBoresightDirection", "evaluate_observation_sequence_feasibility"):
        monkeypatch.setattr(adapter, name, _forbidden)
    with pytest.raises(ValueError, match="equal concrete boresight-frame bindings"):
        evaluate(_config(), previous, next)


def test_same_label_different_concrete_frames_rejects_by_d1c(monkeypatch):
    previous, next = _pair(monkeypatch, phase=.125)
    failure, owner = [], adapter.evaluate_orbit_bound_observation_transition
    def spy(*args):
        try: return owner(*args)
        except ValueError as error:
            failure.append(error)
            raise
    monkeypatch.setattr(adapter, "evaluate_orbit_bound_observation_transition", spy)
    monkeypatch.setattr(adapter, "CommonFrameBoresightDirection", _forbidden)
    monkeypatch.setattr(adapter, "evaluate_observation_sequence_feasibility", _forbidden)
    with pytest.raises(ValueError, match="equal concrete boresight-frame bindings") as caught:
        evaluate(_config(), previous, next)
    assert len(failure) == 1 and caught.value is failure[0]


@pytest.mark.parametrize("path,value", [
    ("transition_result", None),
    ("transition_result.angular_separation_deg", 89.),
    ("transition_result.interpolation_fraction", .25),
    ("transition_result.slew_elapsed_time_seconds", 3.),
    ("transition_result.settling_time_seconds", 1.),
    ("transition_result.total_transition_time_seconds", 3.),
])
def test_every_numeric_transition_disagreement_rejects(monkeypatch, path, value):
    previous, next = _pair(monkeypatch)
    owner = adapter.evaluate_observation_sequence_feasibility
    monkeypatch.setattr(adapter, "evaluate_observation_sequence_feasibility",
        lambda *args: _forge(owner(*args), path, value))
    with pytest.raises(ValueError, match="contradicts D1c transition evidence"):
        evaluate(_config(), previous, next)


@pytest.mark.parametrize("side", ["lower_anchor_id", "upper_anchor_id"])
@pytest.mark.parametrize("type_", [PlainText, AlwaysEqualText, NeverEqualText])
@pytest.mark.parametrize("same", [False, True])
def test_transition_consistency_uses_actual_anchor_text(monkeypatch, side, type_, same):
    previous, next = _pair(monkeypatch)
    owner = adapter.evaluate_observation_sequence_feasibility
    text = type_("right" if same else "different")
    monkeypatch.setattr(adapter, "evaluate_observation_sequence_feasibility",
        lambda *args: _forge(owner(*args), "transition_result." + side, ADCSSlewAnchorId(text)))
    # This test-only return seam isolates the consistency guard from C2's own
    # legacy lower/upper-ID validation. No output seam is caller authority.
    if same: assert evaluate(_config(), previous, next).sequence_result.feasible
    else:
        with pytest.raises(ValueError, match="contradicts D1c transition evidence"):
            evaluate(_config(), previous, next)


@pytest.mark.parametrize("path,value", [("reason", Reason.FEASIBLE), ("transition_result", object()),
    ("transition_ready_seconds", 1.), ("candidate_next_start_seconds", 2.)])
def test_c3_view_failure_contradictions_are_rejected(monkeypatch, path, value):
    previous, next = _pair(monkeypatch)
    owner = adapter.evaluate_observation_sequence_feasibility
    monkeypatch.setattr(adapter, "evaluate_observation_sequence_feasibility",
        lambda *args: _forge(owner(*args), path, value))
    monkeypatch.setattr(adapter, "evaluate_orbit_bound_observation_transition", _forbidden)
    with pytest.raises(ValueError, match="contradicts public view-failure precedence"):
        evaluate(_config(maximum=5.), previous, next)


@pytest.mark.parametrize("text_type", [AlwaysEqualText, NeverEqualText])
@pytest.mark.parametrize("maximum", [5., 80.])
def test_equality_retains_legacy_external_identity_without_bare_id_equality(monkeypatch, text_type, maximum):
    previous, next = _pair(monkeypatch)
    config = _config(maximum=maximum)
    ordinary = evaluate(config, previous, next)
    def represented(candidate):
        return replace(candidate,
            opportunity_id=ObservationOpportunityId(text_type(candidate.opportunity_id.value)),
            request=replace(candidate.request, request_id=ImagingRequestId(text_type(candidate.request.request_id.value))),
            boresight_frame=Binding(ADCSBoresightFrameId(text_type("caller-axes")), candidate.boresight_frame.frame))
    value = evaluate(config, represented(previous), represented(next))
    assert value == ordinary and ordinary == value
    changed = replace(value, next=replace(value.next, opportunity_id=ObservationOpportunityId(text_type("other-opportunity"))))
    assert changed != value
    with pytest.raises(TypeError): hash(value)


@pytest.mark.parametrize("text_type", [AlwaysEqualText, NeverEqualText])
def test_real_legacy_anchor_subclasses_keep_equal_represented_sequence(monkeypatch, text_type):
    previous, next = _pair(monkeypatch)
    config = _config()
    ordinary = evaluate(config, previous, next)
    # Config's frozen anchor owner legitimately formats and hashes its IDs.
    # Preserve those admission operations while keeping hostile equality.
    admitted = type("AdmittedAnchorText", (text_type,), {"__hash__": str.__hash__, "__str__": str.__str__})
    anchors = tuple(replace(a, anchor_id=ADCSSlewAnchorId(admitted(a.anchor_id.value))) for a in config.slew_time_anchors)
    result = evaluate(replace(config, slew_time_anchors=anchors), previous, next)
    assert result == ordinary and ordinary == result
    assert str.__eq__(result.sequence_result.transition_result.lower_anchor_id.value, "right") is True
    assert str.__eq__(result.transition_evidence.transition_result.upper_anchor_id.value, "right") is True


@pytest.mark.parametrize("path,value", [
    ("previous_execution.scheduled_start_seconds", 1),
    ("previous_execution.candidate.common_frame_boresight.x", .125),
    ("previous_execution.candidate.opportunity.request_id.value", AlwaysEqualText("wrong-request")),
    ("transition_evidence", None),
    ("transition_evidence.transition_result.lower_anchor_id.value", AlwaysEqualText("wrong-anchor")),
    ("sequence_result.previous_opportunity_id.value", AlwaysEqualText("wrong-opportunity")),
    ("sequence_result.previous_view.maximum_view_angle_from_nadir_deg", 79.),
    ("sequence_result.transition_ready_seconds", math.nextafter(3., math.inf)),
    ("sequence_result.transition_result.upper_anchor_id.value", AlwaysEqualText("wrong-anchor")),
])
def test_equality_covers_all_retained_evidence_not_only_inputs(monkeypatch, path, value):
    previous, next = _pair(monkeypatch)
    result = evaluate(_config(), previous, next)
    assert _forge(result, path, value) != result


class AdmittedEqualText(AlwaysEqualText):
    # Existing provenance admission hashes source IDs for uniqueness.
    __hash__ = str.__hash__


class AdmittedUnequalText(NeverEqualText):
    __hash__ = str.__hash__


PARAMETER_LOCATIONS = (
    "maximum_view_angle_from_nadir_deg", "post_slew_settling_time_seconds",
    (0, "angular_separation_deg"), (0, "slew_elapsed_time_seconds"),
    (1, "angular_separation_deg"), (1, "slew_elapsed_time_seconds"),
)
PROVENANCE_TEXT_FIELDS = ("rationale", "units", "parameter_id", "derivation", "source_ids")


def _config_parameter(config, location):
    if isinstance(location, tuple):
        index, name = location
        return getattr(config.slew_time_anchors[index], name)
    return getattr(config, location)


def _admitted_parameter_config(config, location, **metadata):
    parameter = _config_parameter(config, location)
    provenance = parameter.provenance
    for name, value in metadata.items():
        provenance = _forge(provenance, name, value)
    # Prove the forged evidence remains admitted by unchanged owners before
    # testing D1d equality. Do not use D1d's comparison to prove admission.
    checked = ParameterProvenance(**{f.name: getattr(provenance, f.name) for f in fields(provenance)})
    assert all(getattr(checked, name) is value for name, value in metadata.items())
    updated = ScalarParameter(parameter.value, provenance)
    if isinstance(location, tuple):
        index, name = location
        anchors = list(config.slew_time_anchors)
        anchors[index] = _forge(anchors[index], name, updated)
        forged = _forge(config, "slew_time_anchors", tuple(anchors))
    else:
        forged = _forge(config, location, updated)
    admitted = AgilePointingConfig(forged.maximum_view_angle_from_nadir_deg,
        forged.post_slew_settling_time_seconds, forged.slew_time_anchors)
    assert _config_parameter(admitted, location) is updated
    assert _config_parameter(admitted, location).provenance is provenance
    return admitted


def _provenance_text_value(parameter, field, text_type, *, different=False):
    actual = {"rationale": "retained rationale", "units": parameter.units,
        "parameter_id": parameter.parameter_id.value, "derivation": "retained derivation",
        "source_ids": "retained-source"}[field]
    text = text_type("different-actual-text" if different else actual)
    if field == "parameter_id": return ParameterId(text)
    if field == "source_ids": return (SourceRecordId(text),)
    return text


@pytest.mark.parametrize("maximum", [5., 80.])
@pytest.mark.parametrize("location", PARAMETER_LOCATIONS)
@pytest.mark.parametrize("field", PROVENANCE_TEXT_FIELDS)
def test_config_provenance_hostile_actual_differences_survive(monkeypatch, maximum, location, field):
    previous, next = _pair(monkeypatch)
    config = _config(maximum=maximum)
    parameter = _config_parameter(config, location)
    left_config = _admitted_parameter_config(config, location,
        **{field: _provenance_text_value(parameter, field, AdmittedEqualText)})
    right_config = _admitted_parameter_config(config, location,
        **{field: _provenance_text_value(parameter, field, AdmittedEqualText, different=True)})
    # The inherited comparison erases this difference; admission remains valid.
    assert left_config == right_config and right_config == left_config
    left, right = (evaluate(c, previous, next) for c in (left_config, right_config))
    assert left != right and right != left


@pytest.mark.parametrize("maximum", [5., 80.])
@pytest.mark.parametrize("location", PARAMETER_LOCATIONS)
@pytest.mark.parametrize("field", PROVENANCE_TEXT_FIELDS)
@pytest.mark.parametrize("text_type", [PlainText, AdmittedEqualText, AdmittedUnequalText])
def test_config_provenance_same_actual_text_stays_equal(monkeypatch, maximum, location, field, text_type):
    previous, next = _pair(monkeypatch)
    config = _config(maximum=maximum)
    parameter = _config_parameter(config, location)
    plain_config = _admitted_parameter_config(config, location,
        **{field: _provenance_text_value(parameter, field, str)})
    subclass_config = _admitted_parameter_config(config, location,
        **{field: _provenance_text_value(parameter, field, text_type)})
    plain, subclass = (evaluate(c, previous, next) for c in (plain_config, subclass_config))
    assert plain == subclass and subclass == plain


@pytest.mark.parametrize("field,left_value,right_value", [
    ("classification", ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION, ProvenanceClass.LITERATURE_VALUE),
    ("status", ProvenanceStatus.TO_RESEARCH, ProvenanceStatus.TO_VERIFY),
    ("rationale", None, "retained rationale"),
    ("derivation", None, "retained derivation"),
    ("sensitivity_range", None, SensitivityRange(0., 85.)),
    ("sensitivity_range", SensitivityRange(0., 85.), SensitivityRange(1., 85.)),
    ("sensitivity_range", SensitivityRange(0., 85.), SensitivityRange(0., 86.)),
    ("source_ids", (), (SourceRecordId("first"),)),
    ("source_ids", (SourceRecordId("first"), SourceRecordId("second")),
        (SourceRecordId("second"), SourceRecordId("first"))),
])
def test_config_provenance_retains_nontext_presence_order_and_bounds(monkeypatch, field, left_value, right_value):
    previous, next = _pair(monkeypatch)
    config = _config()
    location = "maximum_view_angle_from_nadir_deg"
    common = {"classification": ProvenanceClass.LITERATURE_VALUE} if field == "rationale" else {}
    left = evaluate(_admitted_parameter_config(config, location, **(common | {field: left_value})), previous, next)
    right = evaluate(_admitted_parameter_config(config, location, **(common | {field: right_value})), previous, next)
    assert left != right and right != left


NUMERIC_METHOD_CALLS = []


class HostileNumericMethods:
    equality = True

    def __eq__(self, other):
        NUMERIC_METHOD_CALLS.append("eq")
        return self.equality

    def __ne__(self, other):
        NUMERIC_METHOD_CALLS.append("ne")
        return not self.equality

    def __hash__(self):
        NUMERIC_METHOD_CALLS.append("hash")
        raise AssertionError("caller numeric hash")


class AlwaysEqualFloat(HostileNumericMethods, float): pass
class NeverEqualFloat(AlwaysEqualFloat): equality = False
class AlwaysEqualInt(HostileNumericMethods, int): pass
class NeverEqualInt(AlwaysEqualInt): equality = False
class AlwaysEqualFraction(HostileNumericMethods, Fraction): pass
class NeverEqualFraction(AlwaysEqualFraction): equality = False


def _admitted_numeric_config(config, location, *, value=None, bounds=None):
    original = _config_parameter(config, location)
    provenance = original.provenance
    if bounds is not None:
        sensitivity = SensitivityRange(*bounds)
        assert sensitivity.lower is bounds[0] and sensitivity.upper is bounds[1]
        provenance = replace(provenance, sensitivity_range=sensitivity)
    retained = original.value if value is None else value
    parameter = ScalarParameter(retained, provenance)
    if isinstance(location, tuple):
        index, name = location
        anchors = list(config.slew_time_anchors)
        anchors[index] = replace(anchors[index], **{name: parameter})
        admitted = replace(config, slew_time_anchors=tuple(anchors))
    else:
        admitted = replace(config, **{location: parameter})
    # Every constructor above is the unchanged public owner. Check admission
    # and exact retention before evaluating any D1d semantic equality.
    assert type(admitted) is AgilePointingConfig
    assert _config_parameter(admitted, location) is parameter
    assert parameter.value is retained and parameter.provenance is provenance
    return admitted


def _assert_numeric_evidence(left, right, *, same):
    # Reset only AFTER all owner admission/composition has completed.
    NUMERIC_METHOD_CALLS.clear()
    results = (left == right, right == left, left != right, right != left)
    assert NUMERIC_METHOD_CALLS == []
    assert results == (same, same, not same, not same)


@pytest.mark.parametrize("numeric_type", [AlwaysEqualFloat, AlwaysEqualInt])
@pytest.mark.parametrize("location,left_value,right_value", [
    ("post_slew_settling_time_seconds", 0., 1.),
    ("maximum_view_angle_from_nadir_deg", 5., 6.),
    ((1, "angular_separation_deg"), 90., 91.),
    ((1, "slew_elapsed_time_seconds"), 2., 3.),
])
def test_numeric_different_scalar_on_view_failure(monkeypatch, numeric_type, location, left_value, right_value):
    previous, next = _pair(monkeypatch)
    config = _config(maximum=5.)
    configs = [_admitted_numeric_config(config, location, value=numeric_type(v)) for v in (left_value, right_value)]
    # Inherited dataclass comparison falsely equates the admitted numbers.
    assert configs[0] == configs[1] and configs[1] == configs[0]
    left, right = [evaluate(c, previous, next) for c in configs]
    assert left.transition_evidence is right.transition_evidence is None
    assert left.sequence_result.reason is right.sequence_result.reason is Reason.NEXT_VIEW_LIMIT_EXCEEDED
    _assert_numeric_evidence(left, right, same=False)


@pytest.mark.parametrize("numeric_type", [AlwaysEqualFloat, NeverEqualFloat, AlwaysEqualInt, NeverEqualInt])
@pytest.mark.parametrize("maximum", [5., 80.])
@pytest.mark.parametrize("location", PARAMETER_LOCATIONS)
@pytest.mark.parametrize("field", ["value", "lower", "upper"])
def test_numeric_same_content_and_method_trap(monkeypatch, numeric_type, maximum, location, field):
    previous, next = _pair(monkeypatch)
    config = _config(maximum=maximum)
    value = _config_parameter(config, location).value
    bounds = (0., value + 2.)
    plain = _admitted_numeric_config(config, location, value=value, bounds=bounds)
    if field == "value": value = numeric_type(value)
    elif field == "lower": bounds = (numeric_type(bounds[0]), bounds[1])
    else: bounds = (bounds[0], numeric_type(bounds[1]))
    hostile = _admitted_numeric_config(config, location, value=value, bounds=bounds)
    left, right = [evaluate(c, previous, next) for c in (plain, hostile)]
    _assert_numeric_evidence(left, right, same=True)


@pytest.mark.parametrize("numeric_type", [AlwaysEqualFloat, AlwaysEqualInt])
@pytest.mark.parametrize("maximum", [5., 80.])
@pytest.mark.parametrize("location", PARAMETER_LOCATIONS)
@pytest.mark.parametrize("field", ["lower", "upper"])
def test_numeric_different_sensitivity_bounds(monkeypatch, numeric_type, maximum, location, field):
    previous, next = _pair(monkeypatch)
    config = _config(maximum=maximum)
    value = _config_parameter(config, location).value
    # The maximum-view cases use the requested exact lower bounds 0 vs 1.
    lower = 0. if value >= 1. else -1.
    upper = value + 2.
    first = (numeric_type(lower), numeric_type(upper))
    second = (numeric_type(lower + (field == "lower")), numeric_type(upper + (field == "upper")))
    configs = [_admitted_numeric_config(config, location, bounds=bounds) for bounds in (first, second)]
    assert configs[0] == configs[1] and configs[1] == configs[0]
    left, right = [evaluate(c, previous, next) for c in configs]
    _assert_numeric_evidence(left, right, same=False)


@pytest.mark.parametrize("left_value,right_value,same", [
    (0, -0., True), (NeverEqualInt(1), NeverEqualFloat(1.), True),
    (AlwaysEqualInt(2**53 + 1), AlwaysEqualInt(2**53), False),
    (AlwaysEqualInt(2**53 + 1), AlwaysEqualFloat(2**53), False),
    (1., math.nextafter(1., math.inf), False),
    (NeverEqualFraction(1, 2), .5, True),
    (AlwaysEqualFraction(1, 2), AlwaysEqualFraction(3, 4), False),
    # Wider non-Integral Real uses the existing ADCS float representation.
    (NeverEqualFraction(1, 3), float(Fraction(1, 3)), True),
    (Fraction(2**54 + 1, 2**54), 1., True),
    # Wider Integral keeps its int representation, without a float detour.
    (np.int64(2**53 + 1), 2**53 + 1, True),
    (np.int64(2**53 + 1), 2**53, False),
])
def test_numeric_builtin_precision_and_wider_real_rule(monkeypatch, left_value, right_value, same):
    previous, next = _pair(monkeypatch)
    config = _config(maximum=5.)
    location = "post_slew_settling_time_seconds"
    configs = [_admitted_numeric_config(config, location, value=v) for v in (left_value, right_value)]
    left, right = [evaluate(c, previous, next) for c in configs]
    _assert_numeric_evidence(left, right, same=same)


def test_production_ast_has_no_direct_physics_timing_or_generated_identity():
    tree = ast.parse(inspect.getsource(adapter))
    permitted = {
        "__future__": {"annotations"}, "dataclasses": {"dataclass", "field", "fields"},
        "numbers": {"Integral"},
        "adcs": {"CommonFrameBoresightDirection"}, "adcs_config": {"AgilePointingConfig"},
        "observation_feasibility": {"ObservationManeuverCandidate", "ScheduledObservationExecution",
            "ObservationSequenceFeasibilityReason", "ObservationSequenceFeasibilityResult",
            "evaluate_observation_view_feasibility", "evaluate_observation_sequence_feasibility"},
        "orbit_observation_boresight": {"OrbitBoundObservationManeuverCandidate"},
        "orbit_observation_transition": {"OrbitBoundObservationTransition", "evaluate_orbit_bound_observation_transition"},
        "parameters": {"ScalarParameter"},
        "provenance": {"ParameterProvenance", "SensitivityRange"},
    }
    assert not any(isinstance(n, (ast.Import, ast.Try)) for n in ast.walk(tree))
    imports = [(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names]
    assert all(m in permitted and name in permitted[m] for m, name in imports)
    calls = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert calls.count("evaluate_observation_view_feasibility") == 2
    assert calls.count("evaluate_orbit_bound_observation_transition") == 1
    assert calls.count("evaluate_observation_sequence_feasibility") == 1
    assert calls.count("OrbitBoundObservationManeuverCandidate") == 1  # two loop iterations
    assert not any(n.endswith("Id") for n in calls)
    forbidden = {"compute_boresight_transition", "compute_boresight_angular_separation",
        "derive_observation_maneuver_candidate_for_engine_step", "derive_observation_opportunity_for_engine_step",
        "evaluate_two_body_state", "evaluate_ground_point_geometry", "project_ground_visibility_to_engine_grid",
        "find_ground_visibility_windows", "evaluate_ground_visibility", "ObservationOpportunityCatalog", "ObservationCampaign",
        "hash", "round", "max", "min", "float", "int", "set"}
    # Numeric conversion is allowed only inside the local evidence-equality
    # representation helper, never in composition or a physical calculation.
    representation = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_represented_real")
    representation_nodes = set(ast.walk(representation))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in forbidden:
            assert node in representation_nodes and node.id in {"int", "float"}
    assert "str" not in calls
    # The only BinOp is the Optional annotation's |, never timing arithmetic.
    assert all(isinstance(n.op, ast.BitOr) for n in ast.walk(tree) if isinstance(n, ast.BinOp))
    assert not any(isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE))
                   for n in ast.walk(tree) if isinstance(n, ast.Compare) for op in n.ops)
