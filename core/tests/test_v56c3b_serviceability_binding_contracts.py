"""External V5.5 evidence, immutable C3b composition and ownership guards."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import ast
import inspect
import math

import numpy as np
import pytest

from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.communications import ServiceableGroundContact, compute_downlink_capacity
from ops_sim.v5.downlink import evaluate_downlink_transmission
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import GroundContactId, GroundStationId, GroundTargetId
from ops_sim.v5.orbit_contact_serviceability import (
    GroundContactGeometryBinding as Binding, bind_serviceable_ground_contact_to_geometry as bind,
)
import ops_sim.v5.communications as communications
import ops_sim.v5.downlink as downlink
import ops_sim.v5.orbit_contact_serviceability as binding
from test_v50d1_time_engine import _context as generic_context
from test_v55c_downlink_transmission import _config, _record
from test_v56b1_two_body_contracts import _forge
from test_v56b2_orbit_binding import PlainText, ComparisonText
from test_v56c1_ground_point_contracts import _point
from test_v56c3a_ground_contact_contracts import _arguments as geometric_arguments


def _contact(start=9, end=12, *, name="externally-declared", station_id=None):
    return ServiceableGroundContact(GroundContactId(name),
        GroundStationId("synthetic") if station_id is None else station_id, start, end)


def _arguments(**changes):
    args = dict(geometric_arguments(), serviceable_contact=_contact())
    args.update(changes)
    return args


def _binding(**changes):
    return bind(**_arguments(**changes))


class ContactSubclass(ServiceableGroundContact):
    pass


class ContactIdSubclass(GroundContactId):
    pass


class StationIdSubclass(GroundStationId):
    pass


class IntSubclass(int):
    pass


def test_public_frozen_slotted_default_free_eight_input_contract():
    names = ("inputs", "station", "policy", "search_start_seconds", "search_end_seconds",
             "search_config", "first_step_start_seconds", "serviceable_contact")
    assert tuple(inspect.signature(Binding).parameters) == tuple(inspect.signature(bind).parameters) == names
    assert Binding.__dataclass_params__.frozen
    assert Binding.__slots__ == names + ("geometric_projection", "supporting_block")
    assert all(p.default is inspect.Parameter.empty for p in inspect.signature(Binding).parameters.values())
    assert tuple(f.name for f in fields(Binding) if not f.init) == ("geometric_projection", "supporting_block")
    assert set(binding.__all__) == {Binding.__name__, bind.__name__}
    with pytest.raises(TypeError): Binding()
    result = _binding()
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError): result.serviceable_contact = None
    for name in ("serviceable", "serviceable_flag", "contact_id", "capacity_bits", "rf_available"):
        assert not hasattr(result, name)


def test_derived_outputs_cannot_be_injected_and_replace_recomposes_once(monkeypatch):
    result = _binding()
    owner, calls = binding.generate_geometric_ground_contacts, []
    def generate(*args):
        calls.append(args)
        return owner(*args)
    monkeypatch.setattr(binding, "generate_geometric_ground_contacts", generate)
    for name in ("geometric_projection", "supporting_block"):
        with pytest.raises(TypeError): Binding(**_arguments(), **{name: None})
        with pytest.raises((TypeError, ValueError), match="init=False"): replace(result, **{name: None})
        calls.clear()
        assert replace(_forge(result, name, None)) == result and len(calls) == 1
    calls.clear()
    changed = replace(result, serviceable_contact=_contact(name="another-external-contact"))
    assert len(calls) == 1 and changed != result
    assert changed.geometric_projection == result.geometric_projection
    with pytest.raises(TypeError): _binding(inputs=result.geometric_projection)


@pytest.mark.parametrize("contact", [None, True, ("synthetic", 9, 12),
    ContactSubclass(GroundContactId("external"), GroundStationId("synthetic"), 9, 12)])
def test_exact_serviceable_contact_required_before_geometry(monkeypatch, contact):
    def forbidden(*args): pytest.fail("invalid external contact reached geometry")
    monkeypatch.setattr(binding, "generate_geometric_ground_contacts", forbidden)
    with pytest.raises(TypeError): _binding(serviceable_contact=contact)


@pytest.mark.parametrize("field,value", [
    ("contact_id", GroundStationId("externally-declared")),
    ("contact_id", ContactIdSubclass("externally-declared")),
    ("contact_id", "externally-declared"), ("contact_id.value", ""),
    ("contact_id.value", " bad"), ("contact_id.value", True),
    ("ground_station_id", GroundTargetId("synthetic")),
    ("ground_station_id", StationIdSubclass("synthetic")),
    ("ground_station_id", GroundContactId("synthetic")),
    ("ground_station_id.value", ""), ("ground_station_id.value", "BAD"),
    ("ground_station_id.value", None),
])
def test_nested_external_ids_revalidated_without_changing_v55_owner(field, value):
    with pytest.raises((TypeError, ValueError)):
        _binding(serviceable_contact=_forge(_contact(), field, value))


@pytest.mark.parametrize("field", ["start_time_seconds", "end_time_seconds"])
@pytest.mark.parametrize("value", [True, False, 9., Fraction(9), np.int64(9), IntSubclass(9), "9", None, math.inf])
def test_contact_times_require_existing_exact_builtin_integer_domain(field, value):
    with pytest.raises(TypeError): _binding(serviceable_contact=_forge(_contact(), field, value))


@pytest.mark.parametrize("start,end", [(-1, 12), (9, 9), (9, 8)])
def test_invalid_external_intervals_are_not_clipped(start, end):
    contact = _forge(_forge(_contact(), "start_time_seconds", start), "end_time_seconds", end)
    with pytest.raises(ValueError): _binding(serviceable_contact=contact)


@pytest.mark.parametrize("field", ["inputs", "station", "policy", "search_config"])
def test_c3a_revalidates_exact_original_input_types(field):
    args = _arguments(); original = args[field]
    subclass = type("ContractSubclass", (type(original),), {})
    args[field] = subclass(**{f.name: getattr(original, f.name) for f in fields(original) if f.init})
    with pytest.raises(TypeError): bind(**args)


@pytest.mark.parametrize("changes", [
    {"station": _point(identity=GroundTargetId("synthetic"))},
    {"station": _forge(_point(), "latitude_rad.value", True)},
    {"station": _forge(_point(), "longitude_rad.provenance.units", "deg")},
    {"station": _forge(_point(), "point_id.value", ComparisonText("synthetic"))},
    {"inputs": generic_context().inputs},
    {"policy": _forge(geometric_arguments()["policy"], "minimum_elevation_rad.value", math.nan)},
    {"search_config": _forge(geometric_arguments()["search_config"], "max_evaluations", True)},
    {"search_start_seconds": -Fraction(1, 10**1000)},
    {"search_end_seconds": math.inf}, {"first_step_start_seconds": True},
    {"first_step_start_seconds": -1},
])
def test_original_graph_admission_is_owned_by_c3a(changes):
    with pytest.raises((TypeError, ValueError)): _binding(**changes)


def test_typed_station_match_cannot_be_spoofed_by_legacy_text_equality():
    ordinary = _contact(station_id=GroundStationId("another-station"))
    spoofed = _contact(station_id=GroundStationId(ComparisonText("another-station")))
    assert spoofed.ground_station_id == _point().point_id  # Demonstrate the legacy overload.
    assert str.__eq__(spoofed.ground_station_id.value, _point().point_id.value) is False
    for contact in (ordinary, spoofed):
        with pytest.raises(ValueError, match="station does not match"):
            _binding(serviceable_contact=contact)


def test_matching_legacy_text_subclasses_keep_exact_external_fields():
    contact = _contact(name=PlainText("external-text"), station_id=GroundStationId(PlainText("synthetic")))
    result = _binding(serviceable_contact=contact)
    assert type(result.serviceable_contact) is ServiceableGroundContact
    assert result.serviceable_contact is not contact
    for field in fields(contact):
        assert getattr(result.serviceable_contact, field.name) is getattr(contact, field.name)


def test_contact_identity_equality_uses_actual_text_without_rewriting_external_ids():
    original = _binding()
    first = _contact(name=ComparisonText("first-contact"))
    second = _contact(name="second-contact")
    assert first == second  # Existing V5.5 equality can be overloaded by text.
    a, b = replace(original,serviceable_contact=first), replace(original,serviceable_contact=second)
    assert a != b and b != a
    assert a.geometric_projection == b.geometric_projection
    assert a.serviceable_contact.contact_id is first.contact_id
    assert b.serviceable_contact.contact_id is second.contact_id
    plain = replace(original,serviceable_contact=_contact(name=PlainText("first-contact")))
    builtin = replace(original,serviceable_contact=_contact(name="first-contact"))
    assert a == plain == builtin and builtin == a
    assert a != object() and a.__eq__(object()) is NotImplemented
    # No implicit dictionary-key contract using caller-overloaded ID hashes.
    assert Binding.__hash__ is None
    with pytest.raises(TypeError): hash(a)


def test_equal_contact_identity_is_not_erased_by_false_text_equality_or_custom_hash():
    class ContraryText(str):
        def __eq__(self, other): return False
        def __ne__(self, other): return str.__ne__(self,other)
        def __hash__(self): return 42
    builtin = _binding(serviceable_contact=_contact(name="same-external"))
    external = _contact(name=ContraryText("same-external"))
    changed = replace(builtin,serviceable_contact=external)
    assert changed == builtin and builtin == changed
    assert changed.serviceable_contact.contact_id is external.contact_id


def test_c3a_failure_is_propagated_unchanged_after_one_call(monkeypatch):
    calls, failure = [], ValueError("C3a unsupported search envelope")
    def fail(*args):
        calls.append(args)
        raise failure
    monkeypatch.setattr(binding, "generate_geometric_ground_contacts", fail)
    with pytest.raises(ValueError) as caught: _binding()
    assert caught.value is failure and len(calls) == 1


def test_nested_contact_is_ordinary_v55_evidence_but_wrapper_is_not():
    external = _contact(9, 11)
    result = _binding(serviceable_contact=external)
    config, record, context = _config(10.), replace(_record(), acquisition_duration_seconds=9), generic_context()
    before = deepcopy(context)
    nested = result.serviceable_contact
    assert type(nested) is ServiceableGroundContact and nested == external
    capacity = compute_downlink_capacity(config, nested)
    assert capacity == compute_downlink_capacity(config, external)
    assert capacity.nominal_contact_capacity_bits == 20.
    transmission = evaluate_downlink_transmission(config, nested, record, None)
    assert transmission == evaluate_downlink_transmission(config, external, record, None)
    assert transmission.transmitted_equivalent_bits_this_service == 20.
    with pytest.raises(TypeError, match="ServiceableGroundContact"): compute_downlink_capacity(config, result)
    with pytest.raises(TypeError, match="ServiceableGroundContact"):
        evaluate_downlink_transmission(config, result, record, None)
    with pytest.raises(TypeError, match="ServiceableGroundContact"):
        SimulationEngine().step_downlink(context, result, record_id=record.record_id)
    assert context == before


def test_runtime_external_id_only_revalidated_and_no_execution_or_persistence(monkeypatch):
    args = _arguments(); external = args["serviceable_contact"]
    id_owner, validations = GroundContactId.__init__, []
    def validate_id(self, value):
        validations.append((value, inspect.currentframe().f_back.f_globals["__name__"]))
        id_owner(self, value)
    monkeypatch.setattr(GroundContactId, "__init__", validate_id)
    def forbidden(*args, **kwargs): pytest.fail("binding crossed an execution/persistence boundary")
    monkeypatch.setattr(communications, "compute_downlink_capacity", forbidden)
    monkeypatch.setattr(downlink, "evaluate_downlink_transmission", forbidden)
    monkeypatch.setattr(CheckpointState, "from_context", forbidden)
    for name in ("step", "step_imaging", "step_imaging_to_storage", "step_downlink"):
        monkeypatch.setattr(SimulationEngine, name, forbidden)
    result = bind(**args)
    assert validations == [(external.contact_id.value, "ops_sim.v5.communications")]
    assert result.serviceable_contact.contact_id is external.contact_id
    assert result.serviceable_contact.ground_station_id is external.ground_station_id


def test_ast_imports_owner_calls_and_integer_only_containment():
    tree = ast.parse(inspect.getsource(binding))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imports <= {"__future__", "dataclasses", "communications", "context", "orbit_config",
                       "orbit_geometry", "orbit_ground_contacts", "orbit_visibility", "orbit_visibility_windows"}
    imported_communications = [alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                              and node.module == "communications" for alias in node.names]
    assert imported_communications == ["ServiceableGroundContact"]
    calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert calls.count("generate_geometric_ground_contacts") == 1
    assert calls.count("ServiceableGroundContact") == 1
    assert set(calls).isdisjoint({"GroundContactId", "GroundStationId", "float", "int", "Fraction",
                                "round", "isclose", "nextafter", "range", "hash", "id", "open"})
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    assert names.isdisjoint({"compute_downlink_capacity", "evaluate_downlink_transmission", "SimulationEngine",
        "CheckpointState", "step_downlink", "evaluate_two_body_state", "evaluate_ground_point_geometry",
        "evaluate_ground_visibility", "find_ground_visibility_windows", "project_ground_visibility_to_engine_grid",
        "source_window", "step_count", "timestep_seconds", "epsilon", "uuid", "nominal_downlink_data_rate_bps"})
