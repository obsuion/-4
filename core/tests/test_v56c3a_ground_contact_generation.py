"""Real C2c composition and explicitly synthetic adapter-seam/restart checks."""

from copy import deepcopy
from dataclasses import asdict, fields, replace
from fractions import Fraction
from types import SimpleNamespace
import json
import sys

import pytest

from ops_sim.v5.checkpoint import CheckpointState, CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.context import with_coast_orbit
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import GroundContactId, GroundStationId
from ops_sim.v5.orbit_binding import CoastOrbitInputs, COAST_BINDING_VERSION
from ops_sim.v5.orbit_visibility_grid import EngineGridVisibilityBlock as VisibilityBlock
from ops_sim.v5.orbit_visibility_windows import GroundVisibilityWindow as Window, GroundVisibilitySearchConfig as Config
import ops_sim.v5.communications as communications
import ops_sim.v5.downlink as downlink
import ops_sim.v5.orbit_ground_contacts as contacts
from test_v50d1_time_engine import _context as generic_context
from test_v56b1_two_body_contracts import _forge
from test_v56c1_ground_point_contracts import _point
from test_v56c2a_visibility_contracts import _policy
from test_v56c2c_grid_projection_contracts import _inputs
from test_v56c3a_ground_contact_contracts import Block, generate, _arguments, _projection


def _assert_mapping(result):
    source = result.visibility_projection
    assert result.station is source.point
    assert result.inputs is source.inputs and result.policy is source.policy
    assert result.search_config is source.search_config
    assert (result.search_start_seconds, result.search_end_seconds, result.first_step_start_seconds) == (
        source.search_start_seconds, source.search_end_seconds, source.first_step_start_seconds)
    assert type(result.contact_blocks) is tuple and len(result.contact_blocks) == len(source.blocks)
    assert result.total_step_count == source.total_step_count
    assert result.all_search_cells_resolved is source.all_search_cells_resolved
    for candidate, visibility in zip(result.contact_blocks, source.blocks):
        assert type(candidate) is Block and type(candidate.station_id) is GroundStationId
        assert candidate.station_id == result.station.point_id
        assert candidate.source_visibility_block == visibility
        # Compare complete serialized timing/window values, including binary float
        # endpoints, rather than tolerating any alteration at the domain boundary.
        assert json.dumps(asdict(candidate.source_visibility_block), sort_keys=True, allow_nan=False) == \
               json.dumps(asdict(visibility), sort_keys=True, allow_nan=False)
        for name in ("first_start_time_seconds", "timestep_seconds", "step_count",
                     "last_end_time_seconds", "represented_duration_seconds"):
            assert getattr(candidate, name) == getattr(visibility, name)
        for name in ("start_seconds", "end_seconds"):
            assert getattr(candidate.source_visibility_block.source_window, name).hex() == \
                   getattr(visibility.source_window, name).hex()


def test_real_hidden_pass_exactly_one_c2c_call_original_inputs_and_grid_phase(monkeypatch):
    owner, calls, sources = contacts.project_ground_visibility_to_engine_grid, [], []
    def project(*args):
        calls.append(args)
        result = owner(*args)
        sources.append(result)
        return result
    monkeypatch.setattr(contacts, "project_ground_visibility_to_engine_grid", project)
    cases = (_arguments(inputs=_inputs(60)), _arguments(), _arguments(first_step_start_seconds=1),
             _arguments(first_step_start_seconds=1000))
    results = []
    for args in cases:
        before = len(calls)
        result = generate(**args)
        assert len(calls) == before + 1
        assert all(actual is original for actual, original in zip(calls[-1], args.values()))
        assert result.visibility_projection is sources[-1]
        _assert_mapping(result)
        results.append(result)
    coarse, fine, phased, after = results
    assert coarse.visibility_projection.search_result.visible_windows and not coarse.contact_blocks
    assert fine.total_step_count == 1
    assert (fine.contact_blocks[0].first_start_time_seconds, fine.contact_blocks[0].last_end_time_seconds) == (9, 12)
    assert not phased.contact_blocks and not after.contact_blocks
    assert fine.station == phased.station == after.station
    assert fine.inputs.model_manifest == phased.inputs.model_manifest == after.inputs.model_manifest
    assert fine.visibility_projection.search_result == phased.visibility_projection.search_result
    assert fine != phased


def test_real_normalized_station_and_resolved_negative_evidence_are_retained():
    original = _forge(_point(), "latitude_rad.value", Fraction(0))
    normalized = _projection(station=original)
    assert type(normalized.station.latitude_rad.value) is float
    assert normalized.station is normalized.visibility_projection.point
    assert normalized.station is not original and original.latitude_rad.value == Fraction(0)
    below = _projection(station=_point(height=-.1))
    assert below.contact_blocks == () and below.total_step_count == 0
    assert below.all_search_cells_resolved is True
    _assert_mapping(below)


def _trusted_c2c_seam(monkeypatch, blocks, resolved):
    # This fixture asserts adapter behavior only, never an independent physical
    # visibility proof. It deliberately exposes no C2b search_result/cells so
    # C3a cannot derive stronger visibility or completeness from another owner.
    calls, sources = [], []
    def project(inputs, point, policy, start, end, config, origin):
        calls.append((inputs, point, policy, start, end, config, origin))
        source = SimpleNamespace(inputs=inputs, point=point, policy=policy,
            search_start_seconds=start, search_end_seconds=end, search_config=config,
            first_step_start_seconds=origin, blocks=blocks,
            total_step_count=sum(block.step_count for block in blocks), all_search_cells_resolved=resolved)
        sources.append(source)
        return source
    monkeypatch.setattr(contacts, "project_ground_visibility_to_engine_grid", project)
    return calls, sources


@pytest.mark.parametrize("second_start,resolved", [(120, False), (60, True)])
def test_source_windows_stay_distinct_across_unresolved_gap_or_adjacency(monkeypatch, second_start, resolved):
    blocks = (VisibilityBlock(0, 60, 1, Window(0., 60.)),
              VisibilityBlock(second_start, 60, 1, Window(float(second_start), float(second_start + 60))))
    calls, sources = _trusted_c2c_seam(monkeypatch, blocks, resolved)
    result = _projection(inputs=_inputs(60), search_start_seconds=0., search_end_seconds=180.)
    assert len(calls) == 1 and result.visibility_projection is sources[0]
    _assert_mapping(result)
    assert len(result.contact_blocks) == 2 and result.total_step_count == 2
    assert [(b.first_start_time_seconds, b.last_end_time_seconds) for b in result.contact_blocks] == [
        (0, 60), (second_start, second_start + 60)]
    assert result.all_search_cells_resolved is resolved


def test_trillion_step_source_maps_to_one_bounded_candidate_without_enumeration(monkeypatch):
    count = 2**40
    source = VisibilityBlock(0, 1, count, Window(0., float(count)))
    calls, sources = _trusted_c2c_seam(monkeypatch, (source,), True)
    result = _projection(inputs=_inputs(1, horizon=count), search_start_seconds=0., search_end_seconds=float(count))
    assert len(calls) == len(result.contact_blocks) == 1 and result.visibility_projection is sources[0]
    _assert_mapping(result)
    candidate = result.contact_blocks[0]
    assert candidate.step_count == candidate.last_end_time_seconds == candidate.represented_duration_seconds == count
    assert type(candidate.step_count) is int
    assert tuple(f.name for f in fields(candidate)) == ("station_id", "source_visibility_block")
    assert tuple(f.name for f in fields(candidate.source_visibility_block)) == (
        "first_start_time_seconds", "timestep_seconds", "step_count", "source_window")
    assert all(not isinstance(getattr(candidate, f.name), (tuple, list, range, dict)) for f in fields(candidate))
    small = Block(candidate.station_id, VisibilityBlock(0, 1, 1, Window(0., 1.)))
    assert sys.getsizeof(candidate) == sys.getsizeof(small)
    assert sys.getsizeof(candidate.source_visibility_block) == sys.getsizeof(small.source_visibility_block)
    assert sys.getsizeof(result.contact_blocks) == sys.getsizeof((small,))
    # Python integers scale with bit length, not count. Check the two-field
    # wrapper + nested source/window + stored ints (not the separate C2b proof).
    compact_bytes = (sys.getsizeof(candidate) + sys.getsizeof(candidate.source_visibility_block)
        + sys.getsizeof(candidate.source_visibility_block.source_window)
        + sum(sys.getsizeof(getattr(source, name)) for name in (
            "first_start_time_seconds", "timestep_seconds", "step_count")))
    assert compact_bytes < 1024
    print("C3A_HUGE_BLOCK", json.dumps(dict(step_count=count, candidate_blocks=1, compact_bytes=compact_bytes)))


def _changed_station(station, field):
    if field == "identity":
        return replace(station, point_id=GroundStationId("another-station"))
    if field == "provenance":
        return replace(station, longitude_rad=replace(station.longitude_rad,
            provenance=replace(station.longitude_rad.provenance, rationale="Independent synthetic station survey")))
    return replace(station, **{field: replace(getattr(station, field), value=.1)})


@pytest.mark.parametrize("field", ["longitude_rad", "latitude_rad", "ellipsoidal_height_m", "provenance", "identity"])
def test_same_timing_does_not_erase_station_geographic_or_identity_evidence(monkeypatch, field):
    source = VisibilityBlock(9, 3, 1, Window(8., 13.))
    calls, _ = _trusted_c2c_seam(monkeypatch, (source,), False)
    args = _arguments()
    original = generate(**args)
    changed_station = _changed_station(args["station"], field)
    changed = generate(**dict(args, station=changed_station))
    assert len(calls) == 2
    assert changed.station == changed_station and changed.station != original.station and changed != original
    assert changed.inputs.model_manifest == original.inputs.model_manifest
    assert changed.contact_blocks[0].source_visibility_block == original.contact_blocks[0].source_visibility_block
    if field == "identity":
        assert changed.station.geodetic_location == original.station.geodetic_location
        assert changed.contact_blocks != original.contact_blocks
    else:
        assert changed.station.point_id == original.station.point_id
        assert changed.contact_blocks == original.contact_blocks
    _assert_mapping(changed)


def test_real_schema5_json_restart_independent_b2_decode_and_external_evidence():
    inputs = _inputs()
    context = replace(generic_context(), inputs=inputs)
    before, coast_payload = deepcopy(context), inputs.coast_orbit.to_dict()
    payload = CheckpointState.from_context(context).to_dict()
    decoded = CheckpointState.from_dict(json.loads(json.dumps(payload, allow_nan=False)))
    coast = CoastOrbitInputs.from_dict(json.loads(json.dumps(coast_payload, allow_nan=False)))
    restored = decoded.restore(with_coast_orbit(inputs, coast))
    assert restored == context and coast == inputs.coast_orbit and coast is not inputs.coast_orbit
    assert payload["schema_version"] == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5 and COAST_BINDING_VERSION == 1
    assert tuple(payload) == ("schema_version", "simulation_time_seconds", "input_ids", "spacecraft",
        "ground_knowledge", "ground_data_delivery", "mission", "controller", "diagnostics")
    args = _arguments(inputs=inputs)
    original = generate(**args)
    assert generate(**dict(args, inputs=restored.inputs)) == original
    changes = [{"station": _changed_station(args["station"], field)} for field in (
        "longitude_rad", "latitude_rad", "ellipsoidal_height_m", "provenance", "identity")]
    changes += [{"policy": _policy(.2)}, {"search_config": Config(.03125, 10000)},
                {"search_start_seconds": 3.}, {"search_end_seconds": 17.}, {"first_step_start_seconds": 1}]
    for change in changes:
        evidence = generate(**dict(args, **change))
        assert evidence != original and evidence.inputs.model_manifest == original.inputs.model_manifest
        assert generate(**dict(args, inputs=restored.inputs, **change)) == evidence
    assert context == before and inputs.coast_orbit.to_dict() == coast_payload
    assert CheckpointState.from_context(context).to_dict() == payload
    assert CheckpointState.from_context(restored).to_dict() == payload


def test_generation_never_constructs_service_contact_identity_or_executes_service(monkeypatch):
    args = _arguments()
    def forbidden(*args, **kwargs): pytest.fail("C3a crossed the service/persistence boundary")
    monkeypatch.setattr(GroundContactId, "__init__", forbidden)
    monkeypatch.setattr(communications.ServiceableGroundContact, "__init__", forbidden)
    monkeypatch.setattr(communications, "compute_downlink_capacity", forbidden)
    monkeypatch.setattr(downlink, "evaluate_downlink_transmission", forbidden)
    monkeypatch.setattr(CheckpointState, "from_context", forbidden)
    for name in ("step", "step_imaging", "step_imaging_to_storage", "step_downlink"):
        monkeypatch.setattr(SimulationEngine, name, forbidden)
    result = generate(**args)
    assert result.contact_blocks
    _assert_mapping(result)
