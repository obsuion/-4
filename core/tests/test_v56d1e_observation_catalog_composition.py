"""D1b reconstruction ownership, compact support and real external restart."""

from copy import deepcopy
from dataclasses import fields, replace
import hashlib
import json

import pytest

from ops_sim.v5.checkpoint import CheckpointState, CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.context import with_coast_orbit
from ops_sim.v5.ids import ObservationOpportunityId
from ops_sim.v5.orbit_binding import CoastOrbitInputs, COAST_BINDING_VERSION, COAST_REPRESENTATION_VERSION
import ops_sim.v5.adcs as adcs
import ops_sim.v5.observation as legacy
import ops_sim.v5.observation_feasibility as c3
import ops_sim.v5.orbit_observation_opportunity as d1a
import ops_sim.v5.orbit_observation_boresight as d1b
import ops_sim.v5.orbit_observation_transition as d1c
import ops_sim.v5.orbit_observation_sequence as d1d
from test_v50d1_time_engine import _context as generic_context
from test_v56b1_two_body_contracts import _forge
from test_v56b2_orbit_binding import _literal_binding_fixture
from test_v56c2c_grid_projection_contracts import _inputs
from test_v56d1a_observation_opportunity_geometry import _projection_seam, _block
from test_v56d1b_observation_boresight_contracts import _arguments, _quick
from test_v56d1c_observation_transition_geometry import _snapshots
from test_v56d1e_observation_catalog_contracts import Catalog, Candidate, _candidate, _trace


def _pipeline(monkeypatch):
    calls, values = [], []
    owner = Candidate.__post_init__
    def construct(self):
        calls.append("D1b")
        owner(self)
        values.append(self)
    monkeypatch.setattr(Candidate, "__post_init__", construct)
    for module, name, label in (
        (d1b, "derive_observation_opportunity_for_engine_step", "D1a"),
        (d1a, "project_ground_visibility_to_engine_grid", "C2c"),
        (d1a, "evaluate_two_body_state", "B1"),
        (d1a, "evaluate_ground_point_geometry", "C1"),
    ):
        function = getattr(module, name)
        def spy(*args, _function=function, _label=label):
            calls.append(_label)
            return _function(*args)
        monkeypatch.setattr(module, name, spy)
    return calls, values


def _forbidden(*args, **kwargs):
    pytest.fail("catalog reached another collection or pairwise feasibility owner")


def _forbid_pairwise_and_legacy_catalogs(monkeypatch):
    for name in ("TargetCatalog", "ImagingRequestCatalog", "ObservationOpportunityCatalog", "ObservationCampaign", "GroundTarget"):
        monkeypatch.setattr(legacy, name, _forbidden)
    for module, name in ((adcs, "compute_boresight_transition"), (c3, "compute_boresight_transition"),
        (c3, "evaluate_observation_sequence_feasibility"), (d1c, "compute_boresight_transition"),
        (d1c, "evaluate_orbit_bound_observation_transition"), (d1d, "evaluate_orbit_bound_observation_transition"),
        (d1d, "evaluate_observation_sequence_feasibility"), (d1d, "evaluate_orbit_bound_observation_sequence_feasibility")):
        monkeypatch.setattr(module, name, _forbidden)


def test_exactly_one_ordered_owner_chain_per_item_with_no_pairwise_or_legacy_catalog(monkeypatch):
    _quick(monkeypatch)
    supplied = (_candidate("z"), _candidate("a"))
    _forbid_pairwise_and_legacy_catalogs(monkeypatch)
    calls, reconstructed = _pipeline(monkeypatch)
    result = Catalog(supplied)
    assert calls == ["D1b", "D1a", "C2c", "B1", "C1"] * 2
    assert all(a is b for a, b in zip(result.candidates, reconstructed))
    for original, rebuilt in zip(supplied, result.candidates):
        assert rebuilt is not original and rebuilt == original
        assert rebuilt.orbit_observation is not original.orbit_observation
        assert rebuilt.common_frame_boresight is not original.common_frame_boresight
        assert rebuilt.maneuver_candidate is not original.maneuver_candidate
        assert rebuilt.maneuver_candidate.opportunity is rebuilt.orbit_observation.opportunity
        assert rebuilt.maneuver_candidate.common_frame_boresight is rebuilt.common_frame_boresight
        assert rebuilt.opportunity_id is original.opportunity_id


def test_all_and_only_eleven_init_inputs_cross_the_reconstruction_boundary(monkeypatch):
    _quick(monkeypatch)
    supplied = (_candidate("first"), _candidate("second"))
    init_names = tuple(f.name for f in fields(Candidate) if f.init)
    derived_names = tuple(f.name for f in fields(Candidate) if not f.init)
    assert len(init_names) == 11 and len(derived_names) == 3
    owner, calls = Candidate.__post_init__, []
    def construct(self):
        original = supplied[len(calls)]
        assert all(getattr(self, name) is getattr(original, name) for name in init_names)
        assert all(not hasattr(self, name) for name in derived_names)
        calls.append(self)
        return owner(self)
    monkeypatch.setattr(Candidate, "__post_init__", construct)
    result = Catalog(supplied)
    assert len(calls) == 2 and all(a is b for a, b in zip(calls, result.candidates))


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("path", ["orbit_observation", "common_frame_boresight", "maneuver_candidate",
    "orbit_observation.opportunity", "orbit_observation.geometry", "orbit_observation.spacecraft_state"])
def test_supplied_derived_d1b_and_d1a_evidence_is_ignored(monkeypatch, index, path):
    _quick(monkeypatch)
    supplied = [_candidate("first"), _candidate("second")]
    expected = Catalog(tuple(supplied))
    supplied[index] = _forge(supplied[index], path, object())
    calls = _trace(monkeypatch)
    assert Catalog(tuple(supplied)) == expected
    assert len(calls) == 2


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("path,value", [("step_start_seconds", True), ("boresight_frame", None),
    ("request.priority_weight", 0.), ("opportunity_id.value", "INVALID")])
def test_invalid_authoritative_input_propagates_existing_owner_exception(monkeypatch, index, path, value):
    _quick(monkeypatch)
    supplied = [_candidate("first"), _candidate("second")]
    supplied[index] = _forge(supplied[index], path, value)
    owner, calls, errors = Candidate.__post_init__, [], []
    def construct(self):
        calls.append(self)
        try:
            return owner(self)
        except (TypeError, ValueError) as error:
            errors.append(error)
            raise
    monkeypatch.setattr(Candidate, "__post_init__", construct)
    with pytest.raises((TypeError, ValueError)) as caught: Catalog(tuple(supplied))
    assert len(calls) == index + 1 and errors == [caught.value]
    assert errors[0] is caught.value


@pytest.mark.parametrize("index", [1, 2])
def test_owner_exception_identity_and_no_second_d1b_pass(monkeypatch, index):
    _quick(monkeypatch)
    supplied = (_candidate("a"), _candidate("b"), _candidate("c"))
    owner, calls, failure = Candidate.__post_init__, [], ValueError("independent owner sentinel")
    def construct(self):
        calls.append(self)
        if len(calls) == index: raise failure
        return owner(self)
    monkeypatch.setattr(Candidate, "__post_init__", construct)
    with pytest.raises(ValueError) as caught: Catalog(supplied)
    assert caught.value is failure and len(calls) == index


def test_all_reconstructions_precede_even_an_earlier_duplicate(monkeypatch):
    _quick(monkeypatch)
    a = _candidate("same")
    invalid = _forge(_candidate("last"), "step_start_seconds", True)
    calls = _trace(monkeypatch)
    with pytest.raises(TypeError, match="step_start_seconds"): Catalog((a, a, invalid))
    assert len(calls) == 3


def test_replace_reconstructs_every_item_and_reruns_uniqueness(monkeypatch):
    _quick(monkeypatch)
    a, b = _candidate("a"), _candidate("b")
    original = Catalog((a, b))
    calls = _trace(monkeypatch)
    rebuilt = replace(original)
    assert rebuilt == original and len(calls) == 2
    assert all(a is not b for a, b in zip(rebuilt.candidates, original.candidates))
    calls.clear()
    with pytest.raises(ValueError, match="unique by actual text"):
        replace(_forge(original, "candidates", (a, a)))
    assert len(calls) == 2


def test_distinct_valid_world_frame_search_policy_and_descending_times_are_not_cross_gated(monkeypatch):
    # Test-only support seam; each D1b/B1/C1 remains real. This is admission
    # evidence, not a claim these two candidates form a feasible sequence.
    first, second = _snapshots(monkeypatch, times=(9, 0), phase=.2)
    first = replace(first, opportunity_id=ObservationOpportunityId("z"))
    second = replace(second, opportunity_id=ObservationOpportunityId("a"),
        request=replace(second.request, priority_weight=2.),
        policy=replace(second.policy, minimum_elevation_rad=replace(second.policy.minimum_elevation_rad, value=.1)),
        search_start_seconds=0., search_end_seconds=19.)
    assert first.inputs is not second.inputs and first.inputs != second.inputs
    assert first.boresight_frame != second.boresight_frame
    assert first.policy != second.policy
    assert (first.search_start_seconds, first.search_end_seconds) != (second.search_start_seconds, second.search_end_seconds)
    _forbid_pairwise_and_legacy_catalogs(monkeypatch)
    result = Catalog((first, second))
    assert tuple(c.step_start_seconds for c in result.candidates) == (9, 0)
    assert result.candidates[0] == first and result.candidates[1] == second


def test_huge_compact_block_materializes_only_supplied_items(monkeypatch):
    # Certified-support seam only: retain real selected-start B1/C1 geometry.
    count = 2**38
    block = _block(0, 3, count)
    projection_calls, _ = _projection_seam(monkeypatch, (block,))
    args = _arguments(inputs=_inputs(3, horizon=3*count+3),
        search_start_seconds=0., search_end_seconds=float(3*count))
    supplied = tuple(Candidate(**dict(args, opportunity_id=ObservationOpportunityId(t))) for t in ("a", "b"))
    projection_calls.clear()
    calls = _trace(monkeypatch)
    result = Catalog(supplied)
    assert len(result.candidates) == len(calls) == len(projection_calls) == 2
    assert all(c.orbit_observation.supporting_visibility_block.step_count == count for c in result.candidates)
    assert len(fields(result)) == 1


def test_real_schema5_json_restart_recomputes_external_catalog_with_distinct_ids():
    # Real C2c hidden pass; no visibility, orbit or geometry seams in this test.
    args = _arguments()
    context = replace(generic_context(), inputs=args["inputs"])
    before = deepcopy(context)
    payload = CheckpointState.from_context(context).to_dict()
    coast_payload = context.inputs.coast_orbit.to_dict()
    checkpoint = CheckpointState.from_dict(json.loads(json.dumps(payload, allow_nan=False)))
    coast = CoastOrbitInputs.from_dict(json.loads(json.dumps(coast_payload, allow_nan=False)))
    restored = checkpoint.restore(with_coast_orbit(context.inputs, coast))
    assert coast == context.inputs.coast_orbit and coast is not context.inputs.coast_orbit
    ids = (ObservationOpportunityId("external-a"), ObservationOpportunityId("external-b"))
    original_inputs = tuple(Candidate(**dict(args, opportunity_id=identity)) for identity in ids)
    restart_inputs = tuple(Candidate(**dict(args, inputs=restored.inputs, opportunity_id=identity)) for identity in ids)
    original, restarted = Catalog(original_inputs), Catalog(restart_inputs)
    assert original == restarted and restarted == original
    for index, (left, right) in enumerate(zip(original.candidates, restarted.candidates)):
        assert left is not original_inputs[index] and right is not restart_inputs[index] and left is not right
        assert left.orbit_observation is not right.orbit_observation
        assert left.opportunity_id is right.opportunity_id is ids[index]
        assert (left.orbit_observation.opportunity.window_start_seconds,
                left.orbit_observation.opportunity.window_end_seconds) == (9, 12)
    assert context == before == restored
    assert CheckpointState.from_context(context).to_dict() == CheckpointState.from_context(restored).to_dict() == payload
    assert context.inputs.coast_orbit.to_dict() == coast_payload
    assert (CURRENT_CHECKPOINT_SCHEMA_VERSION, payload["schema_version"], COAST_BINDING_VERSION,
        COAST_REPRESENTATION_VERSION, coast_payload["representation_version"]) == (5, 5, 1, 1, 1)
    assert tuple(payload) == ("schema_version", "simulation_time_seconds", "input_ids", "spacecraft",
        "ground_knowledge", "ground_data_delivery", "mission", "controller", "diagnostics")
    encoded = json.dumps(payload, sort_keys=True)
    assert not any(name in encoded for name in ("catalog", "candidates", "external-a", "external-b", "boresight_frame"))
    # Independent preserved B2 literal vector; the existing B2 gate additionally
    # checks production binding output against this fixture and fixed digest.
    literal_bytes = json.dumps(_literal_binding_fixture(), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    assert hashlib.sha256(literal_bytes).hexdigest() == "5fd4b089db8e0a846b526cfedca4a16f4057d38f296b759c9d0ed90b53352125"
