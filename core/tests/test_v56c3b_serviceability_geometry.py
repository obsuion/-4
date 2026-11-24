"""Real C3a binding, independent integer references and explicit adapter seams."""

from copy import deepcopy
from dataclasses import fields, replace
from types import SimpleNamespace
import json
import sys

import pytest

from ops_sim.v5.checkpoint import CheckpointState, CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.context import with_coast_orbit
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import GroundContactId, GroundStationId
from ops_sim.v5.orbit_binding import CoastOrbitInputs, COAST_BINDING_VERSION
from ops_sim.v5.orbit_ground_contacts import GeometricGroundContactBlock as Block
from ops_sim.v5.orbit_visibility_grid import EngineGridVisibilityBlock as GridBlock
from ops_sim.v5.orbit_visibility_windows import GroundVisibilityWindow as Window, GroundVisibilitySearchConfig as Config
from ops_sim.v5.state import DataStorageState
import ops_sim.v5.orbit_contact_serviceability as binding
from test_v50d1_time_engine import _context as generic_context
from test_v55d_downlink_engine_integration import _record as downlink_record
from test_v56c1_ground_point_contracts import _point
from test_v56c2a_visibility_contracts import _policy
from test_v56c2c_grid_projection_contracts import _inputs
from test_v56c3a_ground_contact_generation import _changed_station
from test_v56c3b_serviceability_binding_contracts import Binding, bind, _arguments, _binding, _contact


def _assert_retained(result, external):
    projection = result.geometric_projection
    for name in ("inputs", "station", "policy", "search_start_seconds", "search_end_seconds",
                 "search_config", "first_step_start_seconds"):
        assert getattr(result, name) is getattr(projection, name)
    assert any(result.supporting_block is block for block in projection.contact_blocks)
    assert result.serviceable_contact == external
    for f in fields(external):
        assert getattr(result.serviceable_contact, f.name) is getattr(external, f.name)
    assert external.ground_station_id == projection.station.point_id
    assert external.start_time_seconds >= result.supporting_block.first_start_time_seconds
    assert external.end_time_seconds <= result.supporting_block.last_end_time_seconds


def test_real_hidden_pass_and_substep_one_c3a_call_on_original_seven_inputs(monkeypatch):
    owner, calls, projections = binding.generate_geometric_ground_contacts, [], []
    def generate(*args):
        calls.append(args)
        result = owner(*args)
        projections.append(result)
        return result
    monkeypatch.setattr(binding, "generate_geometric_ground_contacts", generate)
    for end in (12, 11):
        args = _arguments(serviceable_contact=_contact(9, end))
        before = len(calls)
        result = bind(**args)
        assert len(calls) == before + 1 and result.geometric_projection is projections[-1]
        assert all(actual is original for actual, original in zip(calls[-1], list(args.values())[:7]))
        _assert_retained(result, args["serviceable_contact"])
        assert (result.supporting_block.first_start_time_seconds, result.supporting_block.last_end_time_seconds) == (9, 12)
        assert not result.geometric_projection.all_search_cells_resolved
    assert projections[0] == projections[1]


@pytest.mark.parametrize("changes", [
    {"serviceable_contact": _contact(8, 12)},
    {"first_step_start_seconds": 1}, {"first_step_start_seconds": 1000},
    {"inputs": _inputs(60)}, {"station": _point(height=-.1)},
])
def test_external_declaration_cannot_bypass_real_missing_geometry(changes):
    with pytest.raises(ValueError, match="geometry support"):
        _binding(**changes)


def _grid_block(first=60, last=180, dt=60):
    return GridBlock(first, dt, (last-first)//dt, Window(float(first), float(last)))


def _trusted_c3a_seam(monkeypatch, source_blocks, resolved=False):
    # Adapter fixture only, not a new physical oracle. Deliberately exposes no
    # C2c/C2b internals: C3b must use C3a's already-established integer blocks.
    calls, projections = [], []
    def generate(inputs, station, policy, start, end, config, origin):
        calls.append((inputs, station, policy, start, end, config, origin))
        blocks = tuple(Block(station.point_id, source) for source in source_blocks)
        projection = SimpleNamespace(inputs=inputs, station=station, policy=policy,
            search_start_seconds=start, search_end_seconds=end, search_config=config,
            first_step_start_seconds=origin, contact_blocks=blocks,
            total_step_count=sum(block.step_count for block in blocks), all_search_cells_resolved=resolved)
        projections.append(projection)
        return projection
    monkeypatch.setattr(binding, "generate_geometric_ground_contacts", generate)
    return calls, projections


@pytest.mark.parametrize("start,end,valid", [
    (60,180,True), (60,120,True), (70,110,True), (120,180,True),
    (59,120,False), (60,181,False), (0,60,False), (180,181,False),
])
def test_hand_solved_half_open_contact_containment_without_grid_alignment(monkeypatch, start, end, valid):
    calls, projections = _trusted_c3a_seam(monkeypatch, (_grid_block(),))
    external = _contact(start, end)
    args = _arguments(inputs=_inputs(60), search_start_seconds=0., search_end_seconds=240., serviceable_contact=external)
    if valid:
        result = bind(**args)
        assert result.geometric_projection is projections[0]
        _assert_retained(result, external)
    else:
        with pytest.raises(ValueError, match="geometry support"): bind(**args)
    assert len(calls) == 1
    assert (external.start_time_seconds, external.end_time_seconds) == (start, end)


def test_small_intervals_against_independent_unit_second_set_reference(monkeypatch):
    # This bounded oracle enumerates only the fixed six-second fixture. A contact
    # is supported iff its integer unit segments belong to one source set.
    _trusted_c3a_seam(monkeypatch, (_grid_block(0,2,1), _grid_block(4,6,1)))
    covered = ({0,1}, {4,5})
    args = _arguments(inputs=_inputs(1), search_start_seconds=0., search_end_seconds=6.)
    for start in range(7):
        for end in range(start+1,8):
            external = _contact(start,end)
            segments = set(range(start,end))
            expected = [i for i, source in enumerate(covered) if segments <= source]
            if expected:
                result = bind(**dict(args,serviceable_contact=external))
                assert result.supporting_block is result.geometric_projection.contact_blocks[expected[0]]
            else:
                with pytest.raises(ValueError,match="geometry support"):
                    bind(**dict(args,serviceable_contact=external))


@pytest.mark.parametrize("start,end,valid", [(70,110,True),(190,230,True),(60,240,False),(100,200,False),(120,180,False)])
def test_no_union_or_bridging_of_unresolved_gap(monkeypatch, start, end, valid):
    calls, _ = _trusted_c3a_seam(monkeypatch, (_grid_block(60,120), _grid_block(180,240)), resolved=False)
    args = _arguments(inputs=_inputs(60), search_start_seconds=0., search_end_seconds=240., serviceable_contact=_contact(start,end))
    if valid:
        result = bind(**args)
        assert not result.geometric_projection.all_search_cells_resolved
        assert len(result.geometric_projection.contact_blocks) == 2
        _assert_retained(result, args["serviceable_contact"])
    else:
        with pytest.raises(ValueError,match="geometry support"): bind(**args)
    assert len(calls) == 1


def test_even_adjacent_blocks_cannot_be_merged_for_one_contact(monkeypatch):
    _trusted_c3a_seam(monkeypatch, (_grid_block(60,120), _grid_block(120,180)), resolved=True)
    with pytest.raises(ValueError,match="geometry support"):
        _binding(inputs=_inputs(60), search_start_seconds=0., search_end_seconds=180., serviceable_contact=_contact(70,170))


@pytest.mark.parametrize("sources", [(_grid_block(),_grid_block()), (_grid_block(),_grid_block(120,240))])
def test_multiple_supporting_blocks_are_explicit_domain_inconsistency(monkeypatch, sources):
    calls, _ = _trusted_c3a_seam(monkeypatch,sources)
    with pytest.raises(ValueError,match="inconsistent geometry support: more than one"):
        _binding(inputs=_inputs(60), search_start_seconds=0., search_end_seconds=240., serviceable_contact=_contact(130,170))
    assert len(calls) == 1


def test_huge_count_and_nonrepresentable_integer_edges_without_step_materialization(monkeypatch):
    base, count = 2**60, 2**40
    first, last = base+1, base+1+count
    source = GridBlock(first,1,count,Window(float(base),float(last+4096)))
    calls, _ = _trusted_c3a_seam(monkeypatch,(source,),resolved=True)
    args = _arguments(inputs=_inputs(1,horizon=last+4096), search_start_seconds=float(base),
        search_end_seconds=float(last+4096), first_step_start_seconds=first)
    results = []
    for start,end in ((first,last),(first,first+1),(last-1,last)):
        result = bind(**dict(args,serviceable_contact=_contact(start,end)))
        _assert_retained(result,result.serviceable_contact)
        assert len(result.geometric_projection.contact_blocks) == 1
        assert result.supporting_block.step_count == count
        results.append(result)
    for start,end in ((first-1,first+1),(last-1,last+1)):
        # Float coercion would erase precisely these one-second violations.
        with pytest.raises(ValueError,match="geometry support"):
            bind(**dict(args,serviceable_contact=_contact(start,end)))
    assert len(calls) == 5
    assert all(type(r.serviceable_contact.start_time_seconds) is int for r in results)
    _trusted_c3a_seam(monkeypatch,(_grid_block(0,1,1),))
    small = _binding(inputs=_inputs(1),search_start_seconds=0.,search_end_seconds=1.,serviceable_contact=_contact(0,1))
    assert sys.getsizeof(results[0]) == sys.getsizeof(small)
    assert len(fields(results[0])) == 10
    assert results[0].supporting_block is results[0].geometric_projection.contact_blocks[0]


def test_contact_id_changes_external_evidence_only():
    original = _binding()
    external = replace(original.serviceable_contact,contact_id=GroundContactId("second-caller-identity"))
    changed = replace(original,serviceable_contact=external)
    assert changed != original
    assert changed.serviceable_contact.contact_id is external.contact_id
    assert changed.geometric_projection == original.geometric_projection
    assert changed.inputs.model_manifest == original.inputs.model_manifest


@pytest.mark.parametrize("field", ["longitude_rad","latitude_rad","ellipsoidal_height_m","provenance","identity"])
def test_complete_station_evidence_retained_even_at_coincident_timing(monkeypatch,field):
    _trusted_c3a_seam(monkeypatch,(_grid_block(9,12,3),))
    args = _arguments(); original = bind(**args)
    station = _changed_station(args["station"],field)
    if field == "identity":
        with pytest.raises(ValueError,match="station does not match"):
            bind(**dict(args,station=station))
        external = replace(args["serviceable_contact"],ground_station_id=station.point_id)
    else:
        external = args["serviceable_contact"]
    changed = bind(**dict(args,station=station,serviceable_contact=external))
    assert changed != original and changed.geometric_projection != original.geometric_projection
    assert changed.station == station and changed.inputs.model_manifest == original.inputs.model_manifest
    assert changed.serviceable_contact.contact_id is original.serviceable_contact.contact_id


def test_step_downlink_retains_full_current_step_alignment_after_binding(monkeypatch):
    # Geometry supports [9,11); the unchanged engine at9 with dt3 rejects it
    # before checkpoint capture. Bind first: C3b itself executes no engine step.
    result = _binding(serviceable_contact=_contact(9,11))
    base = generic_context()
    context = replace(base, inputs=result.inputs,simulation_time_seconds=9,
        spacecraft_state=replace(base.spacecraft_state,
            data_storage=DataStorageState((downlink_record("early",start=0,duration=1),))))
    before = deepcopy(context)
    record = context.spacecraft_state.data_storage.stored_records[0]
    with monkeypatch.context() as guard:
        def forbidden(*args): pytest.fail("misaligned nested contact reached checkpoint capture")
        guard.setattr(CheckpointState,"from_context",forbidden)
        with pytest.raises(ValueError,match="full step end"):
            SimulationEngine().step_downlink(context,result.serviceable_contact,record_id=record.record_id)
    assert context == before
    full = _binding(serviceable_contact=_contact(9,12))
    executed = SimulationEngine().step_downlink(context,full.serviceable_contact,record_id=record.record_id)
    assert context.simulation_time_seconds == 12
    assert executed.step_result.dt_seconds == 3
    assert executed.transmission_result.capacity_proposal.contact == full.serviceable_contact


def test_real_schema5_restart_independent_coast_codec_and_one_at_a_time_external_changes():
    inputs = _inputs(1)
    context = replace(generic_context(),inputs=inputs)
    before = deepcopy(context)
    coast_payload = inputs.coast_orbit.to_dict()
    payload = CheckpointState.from_context(context).to_dict()
    checkpoint = CheckpointState.from_dict(json.loads(json.dumps(payload,allow_nan=False)))
    coast = CoastOrbitInputs.from_dict(json.loads(json.dumps(coast_payload,allow_nan=False)))
    restored = checkpoint.restore(with_coast_orbit(inputs,coast))
    assert restored == context and coast == inputs.coast_orbit and coast is not inputs.coast_orbit
    assert payload["schema_version"] == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5 and COAST_BINDING_VERSION == 1
    assert tuple(payload) == ("schema_version","simulation_time_seconds","input_ids","spacecraft",
        "ground_knowledge","ground_data_delivery","mission","controller","diagnostics")
    args = _arguments(inputs=inputs,serviceable_contact=_contact(9,11))
    original = bind(**args)
    assert bind(**dict(args,inputs=restored.inputs)) == original
    changes = [{"station":_changed_station(args["station"],field)} for field in (
        "longitude_rad","latitude_rad","ellipsoidal_height_m","provenance")]
    changes += [{"policy":_policy(.2)}, {"search_config":Config(.03125,10000)},
        {"search_start_seconds":3.}, {"search_end_seconds":17.}, {"first_step_start_seconds":1},
        {"serviceable_contact":_contact(9,10)}, {"serviceable_contact":_contact(9,11,name="external-second")}]
    for change in changes:
        evidence = bind(**dict(args,**change))
        assert evidence != original and evidence.inputs.model_manifest == original.inputs.model_manifest
        assert bind(**dict(args,inputs=restored.inputs,**change)) == evidence
    station = _changed_station(args["station"],"identity")
    for active_inputs in (inputs,restored.inputs):
        with pytest.raises(ValueError,match="station does not match"):
            bind(**dict(args,inputs=active_inputs,station=station))
        with pytest.raises(ValueError,match="station does not match"):
            bind(**dict(args,inputs=active_inputs,serviceable_contact=replace(args["serviceable_contact"],ground_station_id=station.point_id)))
    matched = dict(args,station=station,serviceable_contact=replace(args["serviceable_contact"],ground_station_id=station.point_id))
    changed = bind(**matched)
    assert changed != original and changed.inputs.model_manifest == original.inputs.model_manifest
    assert bind(**dict(matched,inputs=restored.inputs)) == changed
    assert context == before and inputs.coast_orbit.to_dict() == coast_payload
    assert CheckpointState.from_context(context).to_dict() == payload
    assert CheckpointState.from_context(restored).to_dict() == payload
