"""Independent canonical fixture, complete substitutions and binding boundaries."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
import inspect
import json
import math

import pytest

from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.context import SimulationInputs, with_coast_orbit
from ops_sim.v5.ids import (
    ControllerId, EnvironmentId, FlightRulesId, ModelManifestId, NumericalConfigId,
    ScenarioId, SourceRecordId, SpacecraftConfigurationId, WorldEventId, WorldId,
)
from ops_sim.v5.manifest import ModelManifest
from ops_sim.v5.orbit import TwoBodySolverConfig, TwoBodyTrajectory
from ops_sim.v5.orbit_binding import (
    CoastOrbitInputs, coast_binding_payload, derive_coast_manifest_id,
)
from ops_sim.v5.run_config import NumericalConfig
from ops_sim.v5.world import CommonWorld
from test_v56b1_two_body_contracts import _forge, _trajectory


def _coast():
    return CoastOrbitInputs(_trajectory(), TwoBodySolverConfig(1e-8, 100))


def _inputs():
    return build_demo_context().inputs


def _binding(coast=None, inputs=None):
    return with_coast_orbit(_inputs() if inputs is None else inputs, _coast() if coast is None else coast)


def _rich_payload():
    p = _coast().to_dict()
    p["initial_state"]["position_m"] = [x.hex() for x in (2.1, .1, .05)]
    p["initial_state"]["velocity_m_per_s"] = [x.hex() for x in (-.03, .95, .1)]
    p["initial_state"]["instant"]["elapsed_seconds"] = 7.25.hex()
    p["initial_state"]["instant"]["epoch"]["fractional_day"] = .375.hex()
    rotation = p["initial_state"]["frame"]["rotation"]
    rotation["epoch"]["fractional_day"] = .375.hex()
    rotation["initial_phase_rad"]["value"] = (-.7).hex()
    rotation["angular_velocity_rad_per_s"]["value"] = .0125.hex()
    p["initial_state"]["frame"]["ellipsoid"]["flattening"]["value"] = .01.hex()
    for parameter in _parameters(p):
        provenance = parameter["provenance"]
        provenance.update(source_ids=["source:first", "source:second"],
                          rationale="Synthetic provenance \u03b1", derivation="Independent test definition")
        value = float.fromhex(parameter["value"])
        provenance["sensitivity_range"] = {"lower": (value-1).hex(), "upper": (value+1).hex()}
    return p


def _parameters(p):
    f = p["initial_state"]["frame"]
    return [p["gravitational_parameter_m3_s2"], f["ellipsoid"]["equatorial_radius_m"],
            f["ellipsoid"]["flattening"], f["rotation"]["initial_phase_rad"],
            f["rotation"]["angular_velocity_rad_per_s"]]


def test_required_coast_fields_and_legacy_seven_positional_inputs():
    assert tuple(f.name for f in fields(CoastOrbitInputs)) == ("trajectory", "solver_config")
    assert CoastOrbitInputs.__slots__ == ("trajectory", "solver_config")
    assert all(f.default is MISSING and f.default_factory is MISSING for f in fields(CoastOrbitInputs))
    assert all(p.default is inspect.Parameter.empty for p in inspect.signature(CoastOrbitInputs).parameters.values())
    with pytest.raises(FrozenInstanceError):
        _coast().trajectory = _trajectory()
    original = _inputs()
    seven = [getattr(original, f.name) for f in fields(SimulationInputs) if f.name != "coast_orbit"]
    assert len(seven) == 7
    legacy = SimulationInputs(*seven)
    assert legacy.coast_orbit is None and legacy == original
    parameter = inspect.signature(SimulationInputs).parameters["coast_orbit"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None
    with pytest.raises(TypeError):
        SimulationInputs(*seven, None)


def test_round_trip_equal_independent_objects_deepcopy_and_key_order():
    coast = CoastOrbitInputs.from_dict(_rich_payload())
    wire = json.loads(json.dumps(coast.to_dict(), allow_nan=False))
    def reverse(value):
        if type(value) is dict:
            return {k: reverse(v) for k, v in reversed(tuple(value.items()))}
        if type(value) is list:
            return [reverse(v) for v in value]
        return value
    copies = [deepcopy(coast), CoastOrbitInputs.from_dict(wire), CoastOrbitInputs.from_dict(reverse(wire)),
              CoastOrbitInputs.from_dict(_rich_payload())]
    assert all(c == coast for c in copies)
    assert all(_binding(c).model_manifest == _binding(coast).model_manifest for c in copies)
    assert coast.to_dict() == _rich_payload()


def test_normalized_equivalent_numbers_and_rebinding_do_not_hash_chain():
    ints = CoastOrbitInputs(_trajectory(r=(2, 0, 0), v=(0, 1, 0), mu=2, earth=1, t0=0),
                            TwoBodySolverConfig(1, 100))
    floats = CoastOrbitInputs(_trajectory(r=(2., -0., 0.), v=(-0., 1., 0.)), TwoBodySolverConfig(1., 100))
    assert ints.to_dict() == floats.to_dict()
    original = _inputs()
    bound = _binding(ints, original)
    assert _binding(floats, bound) == bound
    assert original.coast_orbit is None
    for f in fields(SimulationInputs):
        if f.name not in ("model_manifest", "coast_orbit"):
            assert getattr(bound, f.name) is getattr(original, f.name)
    renamed = replace(original, model_manifest=replace(original.model_manifest, manifest_id=ModelManifestId("another-label")))
    assert _binding(ints, renamed).model_manifest == bound.model_manifest


_COAST_CHANGES = [
    (("initial_state", "position_m", 0), 2.100000000000001.hex()),
    (("initial_state", "velocity_m_per_s", 1), .9500000000000001.hex()),
    (("initial_state", "instant", "elapsed_seconds"), 7.5.hex()),
    (("initial_state", "frame", "rotation", "initial_phase_rad", "value"), (-.6).hex()),
    (("initial_state", "frame", "rotation", "angular_velocity_rad_per_s", "value"), .0126.hex()),
    (("initial_state", "frame", "ellipsoid", "equatorial_radius_m", "value"), 1.01.hex()),
    (("initial_state", "frame", "ellipsoid", "flattening", "value"), .011.hex()),
    (("initial_state", "frame", "ellipsoid", "name"), "Different synthetic definition"),
    (("gravitational_parameter_m3_s2", "value"), math.nextafter(2., math.inf).hex()),
    (("solver_config", "time_tolerance_seconds"), math.nextafter(1e-8, math.inf).hex()),
    (("solver_config", "max_iterations"), 101),
]


def _set(p, path, value):
    for key in path[:-1]:
        p = p[key]
    p[path[-1]] = value


@pytest.mark.parametrize("path,value", _COAST_CHANGES)
def test_each_valid_coast_change_changes_identity_and_rejects_stale_id(path, value):
    p = _rich_payload()
    original = _binding(CoastOrbitInputs.from_dict(p))
    _set(p, path, value)
    changed = CoastOrbitInputs.from_dict(p)  # Reach the binding guard with a valid graph.
    assert _binding(changed).model_manifest != original.model_manifest
    with pytest.raises(ValueError, match="coast binding identity mismatch"):
        replace(original, coast_orbit=changed)


@pytest.mark.parametrize("part,value", [("julian_day", 2451546), ("fractional_day", .4.hex())])
def test_coherent_reference_epoch_change(part, value):
    p = _rich_payload()
    old = _binding(CoastOrbitInputs.from_dict(p))
    p["initial_state"]["instant"]["epoch"][part] = value
    p["initial_state"]["frame"]["rotation"]["epoch"][part] = value
    coast = CoastOrbitInputs.from_dict(p)
    assert _binding(coast).model_manifest != old.model_manifest
    with pytest.raises(ValueError, match="coast binding identity mismatch"):
        replace(old, coast_orbit=coast)


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("field,value", [
    ("classification", "DERIVED_VALUE"), ("status", "TO_VERIFY"),
    ("rationale", "Another reason"), ("derivation", "Another derivation"),
    ("source_ids", ["source:second", "source:first"]),
    ("sensitivity_range", None),
])
def test_all_parameters_complete_provenance_is_bound(index, field, value):
    p = _rich_payload()
    original = _binding(CoastOrbitInputs.from_dict(p))
    _parameters(p)[index]["provenance"][field] = value
    changed = CoastOrbitInputs.from_dict(p)
    assert _binding(changed).model_manifest != original.model_manifest
    with pytest.raises(ValueError, match="coast binding identity mismatch"):
        replace(original, coast_orbit=changed)


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("endpoint", ["lower", "upper"])
def test_each_sensitivity_endpoint_is_independently_bound(index, endpoint):
    p = _rich_payload()
    original = _binding(CoastOrbitInputs.from_dict(p))
    bounds = _parameters(p)[index]["provenance"]["sensitivity_range"]
    bounds[endpoint] = (float.fromhex(bounds[endpoint])+(-.25 if endpoint == "lower" else .25)).hex()
    changed = CoastOrbitInputs.from_dict(p)
    assert _binding(changed).model_manifest != original.model_manifest
    with pytest.raises(ValueError, match="coast binding identity mismatch"):
        replace(original, coast_orbit=changed)


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("field,value", [
    ("parameter_id", "parameter:wrong-parameter"), ("units", "wrong-units"),
    ("classification", 1), ("status", "REJECTED"), ("rationale", 1),
    ("derivation", []), ("source_ids", ["source:duplicate", "source:duplicate"]),
])
def test_all_parameter_metadata_reconstructed_through_authoritative_contracts(index, field, value):
    p = _rich_payload()
    _parameters(p)[index]["provenance"][field] = value
    with pytest.raises((TypeError, ValueError)):
        CoastOrbitInputs.from_dict(p)


@pytest.mark.parametrize("path,value", [
    ("numerical_config.timestep_seconds", 30),
    ("numerical_config.geometry_sample_seconds", 2),
    ("numerical_config.checkpoint_interval_seconds", 120),
    ("common_world.horizon_seconds", 601),
    ("common_world.event_ids", (WorldEventId("b"), WorldEventId("a"))),
    ("model_manifest.schema_version", 2),
    ("model_manifest.controller_id", ControllerId("different")),
])
def test_run_content_changes_require_new_identity(path, value):
    legacy = _inputs()
    # Establish a cadence/event fixture whose single-item changes remain valid.
    legacy = replace(legacy, numerical_config=replace(legacy.numerical_config, timestep_seconds=60,
                     geometry_sample_seconds=1, checkpoint_interval_seconds=60),
                     common_world=replace(legacy.common_world, horizon_seconds=600,
                                          event_ids=(WorldEventId("a"), WorldEventId("b"))))
    bound = _binding(inputs=legacy)
    owner, field = path.split(".")
    changed = replace(getattr(legacy, owner), **{field: value})
    altered = replace(legacy, **{owner: changed})
    assert _binding(inputs=altered).model_manifest != bound.model_manifest
    with pytest.raises(ValueError, match="coast binding identity mismatch"):
        replace(bound, **{owner: changed})


@pytest.mark.parametrize("owner,field,id_type,manifest_field", [
    ("spacecraft_configuration", "configuration_id", SpacecraftConfigurationId, "spacecraft_configuration_id"),
    ("numerical_config", "configuration_id", NumericalConfigId, "numerical_config_id"),
    ("environment_config", "environment_id", EnvironmentId, "environment_id"),
    ("flight_rules_config", "flight_rules_id", FlightRulesId, "flight_rules_id"),
    ("common_world", "world_id", WorldId, "world_id"),
])
def test_coherent_manifest_associations_are_bound(owner, field, id_type, manifest_field):
    legacy = _inputs()
    bound = _binding(inputs=legacy)
    identity = id_type("changed-association")
    manifest = replace(legacy.model_manifest, **{manifest_field: identity})
    replacement = replace(getattr(legacy, owner), **{field: identity})
    changed = replace(legacy, model_manifest=manifest, **{owner: replacement})
    assert _binding(inputs=changed).model_manifest != bound.model_manifest
    stale = replace(manifest, manifest_id=bound.model_manifest.manifest_id)
    with pytest.raises(ValueError, match="coast binding identity mismatch"):
        replace(bound, model_manifest=stale, **{owner: replacement})


def test_coherent_scenario_association_is_bound():
    legacy = _inputs()
    bound = _binding(inputs=legacy)
    identity = ScenarioId("changed-scenario")
    scenario = replace(legacy.scenario_config, scenario_id=identity)
    world = replace(legacy.common_world, scenario_id=identity)
    manifest = replace(legacy.model_manifest, scenario_id=identity)
    changed = replace(legacy, scenario_config=scenario, common_world=world, model_manifest=manifest)
    assert _binding(inputs=changed).model_manifest != bound.model_manifest
    with pytest.raises(ValueError, match="coast binding identity mismatch"):
        replace(bound, scenario_config=scenario, common_world=world,
                model_manifest=replace(manifest, manifest_id=bound.model_manifest.manifest_id))


def test_only_exact_coast_inputs_are_accepted():
    class Subclass(CoastOrbitInputs):
        pass
    coast = _coast()
    bound = _binding(coast)
    for bad in (object(), {"trajectory": coast.trajectory}, Subclass(coast.trajectory, coast.solver_config)):
        with pytest.raises(TypeError, match="exact CoastOrbitInputs"):
            replace(bound, coast_orbit=bad)
        with pytest.raises(TypeError, match="exact CoastOrbitInputs"):
            with_coast_orbit(_inputs(), bad)


@pytest.mark.parametrize("identity", ["v56b2-coast", "v56b2-coast-sha256", "v56b2-coast-sha256-bad",
                                      "v56b2-coast-sha256-"+"0"*64, "v56b2-coast-future-format"])
def test_entire_reserved_namespace_rejected_without_coast(identity):
    legacy = _inputs()
    with pytest.raises(ValueError, match="reserved coast manifest namespace"):
        replace(legacy, model_manifest=replace(legacy.model_manifest, manifest_id=ModelManifestId(identity)))


def test_direct_construction_and_factory_cannot_repair_stale_or_stripped_inputs():
    legacy, coast = _inputs(), _coast()
    with pytest.raises(ValueError, match="coast binding identity mismatch"):
        replace(legacy, coast_orbit=coast)
    bound = _binding(coast, legacy)
    for forged in (_forge(bound, "coast_orbit", None),
                   _forge(bound, "coast_orbit.solver_config.max_iterations", 101)):
        with pytest.raises(ValueError):
            with_coast_orbit(forged, coast)
        values = {f.name: getattr(forged, f.name) for f in fields(SimulationInputs)}
        with pytest.raises(ValueError):
            SimulationInputs(**values)
    with pytest.raises(ValueError, match="reserved coast manifest namespace"):
        replace(bound, coast_orbit=None)


@pytest.mark.parametrize("path,value", [
    ("trajectory.initial_state.velocity.instant.elapsed_seconds", 1.),
    ("trajectory.initial_state.velocity.frame.rotation.initial_phase_rad.value", .3),
    ("trajectory.gravitational_parameter_m3_s2.provenance.rationale", None),
    ("trajectory.gravitational_parameter_m3_s2.provenance.parameter_id.value", " invalid "),
    ("solver_config.time_tolerance_seconds", True), ("solver_config.max_iterations", 0),
])
def test_forged_complete_coast_graph_revalidated_before_hashing(path, value):
    bad = _forge(_coast(), path, value)
    with pytest.raises((ValueError, TypeError)):
        bad.to_dict()
    with pytest.raises((ValueError, TypeError)):
        _binding(bad)


@pytest.mark.parametrize("path,value", [
    ("model_manifest.manifest_id.value", " invalid "),
    ("model_manifest.controller_id.value", " invalid "),
    ("model_manifest.schema_version", True),
    ("numerical_config.geometry_sample_seconds", True),
    ("common_world.horizon_seconds", True),
    ("common_world.event_ids", (WorldEventId("duplicate"), WorldEventId("duplicate"))),
])
def test_forged_run_graph_is_revalidated(path, value):
    bad = _forge(_binding(), path, value)
    with pytest.raises((ValueError, TypeError)):
        replace(bad)


def _objects(value, path=()):
    if type(value) is dict:
        yield path
        for key, child in value.items():
            yield from _objects(child, path+(key,))


@pytest.mark.parametrize("path", list(_objects(_rich_payload())))
@pytest.mark.parametrize("operation", ["missing", "extra", "wrong-type"])
def test_every_codec_object_rejects_wrong_structure(path, operation):
    p = _rich_payload()
    item = p
    for key in path:
        item = item[key]
    if operation == "missing":
        del item[next(iter(item))]
    elif operation == "extra":
        item["unexpected"] = None
    elif path:
        _set(p, path, [])
    else:
        p = []
    with pytest.raises((ValueError, TypeError)):
        CoastOrbitInputs.from_dict(p)


@pytest.mark.parametrize("encoding", [1, 1., True, None, "1", "0x1p+0", "0X1.0000000000000P+0",
                                         " 0x1.0000000000000p+0", "-0x0.0p+0", "nan", "inf",
                                         "0x1.0000000000000p-99999"])
def test_reader_rejects_noncanonical_binary64(encoding):
    p = _coast().to_dict()
    p["solver_config"]["time_tolerance_seconds"] = encoding
    with pytest.raises((ValueError, TypeError)):
        CoastOrbitInputs.from_dict(p)


@pytest.mark.parametrize("path,value", [
    (("representation_version",), 2), (("representation_version",), True),
    (("model",), "unknown"), (("model",), None),
    (("solver_config", "max_iterations"), 100.),
    (("initial_state", "position_m"), [0., 0., 0.]),
    (("initial_state", "velocity_m_per_s"), ["0x0.0p+0"]),
    (("initial_state", "instant", "epoch", "julian_day"), 2451545.),
    (("initial_state", "frame", "kind"), "EARTH_FIXED"),
    (("initial_state", "position_m"), ["0x0.0p+0"]*3),
])
def test_reader_rejects_versions_types_and_reconstructed_domains(path, value):
    p = _coast().to_dict()
    _set(p, path, value)
    with pytest.raises((ValueError, TypeError)):
        CoastOrbitInputs.from_dict(p)


def _literal_binding_fixture():
    # Written from the contract and exact binary fractions, without calling any
    # production encoder. IDs/provenance/null fields are deliberately explicit.
    def parameter(identifier, units, value):
        return {"value": value, "provenance": {
            "parameter_id": "parameter:"+identifier, "classification": "EXPLICIT_MODEL_ASSUMPTION",
            "units": units, "source_ids": [], "status": "VERIFIED",
            "rationale": "Synthetic B1 verification input", "derivation": None, "sensitivity_range": None}}
    epoch = {"julian_day": 2451545, "fractional_day": "0x1.0000000000000p-3"}
    coast = {"representation_version": 1, "model": "v56b1-elliptic-two-body",
             "initial_state": {
                 "position_m": ["0x1.0000000000000p+1", "0x0.0p+0", "0x0.0p+0"],
                 "velocity_m_per_s": ["0x0.0p+0", "0x1.0000000000000p+0", "0x0.0p+0"],
                 "instant": {"epoch": epoch, "elapsed_seconds": "0x0.0p+0"},
                 "frame": {"kind": "MODEL_INERTIAL", "ellipsoid": {
                     "name": "Synthetic B1 sphere",
                     "equatorial_radius_m": parameter("orbit.earth.equatorial-radius", "m", "0x1.0000000000000p+0"),
                     "flattening": parameter("orbit.earth.flattening", "1", "0x0.0p+0")},
                     "rotation": {"epoch": epoch,
                                  "initial_phase_rad": parameter("orbit.rotation.initial-phase", "rad", "0x1.0000000000000p-2"),
                                  "angular_velocity_rad_per_s": parameter("orbit.rotation.angular-rate", "rad/s", "-0x1.0000000000000p-3")}}},
             "gravitational_parameter_m3_s2": parameter("orbit.gravity.gravitational-parameter", "m^3/s^2", "0x1.0000000000000p+1"),
             "solver_config": {"time_tolerance_seconds": "0x1.0000000000000p-3", "max_iterations": 8}}
    return {"binding_version": 1, "coast_orbit": coast,
            "manifest": {"schema_version": 1, "spacecraft_configuration_id": "spacecraft-config:s",
                         "numerical_config_id": "numerical-config:n", "environment_id": "environment:e",
                         "flight_rules_id": "flight-rules:f", "scenario_id": "scenario:s",
                         "world_id": "world:w", "controller_id": "controller:c"},
            "numerical": {"timestep_seconds": 1, "geometry_sample_seconds": 1, "checkpoint_interval_seconds": 1},
            "world": {"horizon_seconds": 2, "event_ids": []}}


def test_independently_inspected_literal_payload_and_fixed_digest():
    coast = CoastOrbitInputs(_trajectory(), TwoBodySolverConfig(.125, 8))
    manifest = ModelManifest(ModelManifestId("ignored-label"), 1, SpacecraftConfigurationId("s"),
                             NumericalConfigId("n"), EnvironmentId("e"), FlightRulesId("f"),
                             ScenarioId("s"), WorldId("w"), ControllerId("c"))
    numerical = NumericalConfig(NumericalConfigId("n"), 1, 1, 1)
    world = CommonWorld(WorldId("w"), ScenarioId("s"), 2, ())
    assert coast_binding_payload(coast, manifest, numerical, world) == _literal_binding_fixture()
    assert derive_coast_manifest_id(coast, manifest, numerical, world).value == (
        "v56b2-coast-sha256-" + "5fd4b089db8e0a846b526cfedca4a16f4057d38f296b759c9d0ed90b53352125"
    )


class PlainText(str):
    pass


class ComparisonText(str):
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__

    def __str__(self):
        raise AssertionError("B2 must not coerce subclass text")

    def __format__(self, spec):
        raise AssertionError("B2 must not format subclass text")


_FRAME_PARAMETERS = (("ellipsoid", "equatorial_radius_m"), ("ellipsoid", "flattening"),
                     ("rotation", "initial_phase_rad"), ("rotation", "angular_velocity_rad_per_s"))
_PARAMETER_LOCATIONS = [
    (("gravitational_parameter_m3_s2",), ("trajectory.gravitational_parameter_m3_s2",)),
    *((('initial_state', 'frame')+p,
       tuple("trajectory.initial_state."+side+".frame."+".".join(p) for side in ("position", "velocity")))
      for p in _FRAME_PARAMETERS),
]
_TEXT_LOCATIONS = [
    (("initial_state", "frame", "ellipsoid", "name"),
     tuple("trajectory.initial_state."+side+".frame.ellipsoid.name" for side in ("position", "velocity"))),
    *((p+("provenance", field), tuple(x+".provenance."+field for x in objects))
      for p, objects in _PARAMETER_LOCATIONS for field in ("rationale", "derivation")),
]
_REVIEW_TEXT_PATHS = [_TEXT_LOCATIONS[i][0] for i in (0, 1, 2)]
_SCALAR_TEXT = "Test \U0001f680"
_SURROGATE_TEXT = "Test \ud83d\ude80"


def _text_payload(path, text):
    payload = _coast().to_dict()
    _set(payload, path, text)
    return payload


def _forge_text_fields(coast, object_paths, text):
    for path in object_paths:
        coast = _forge(coast, path, text)
    return coast


@pytest.mark.parametrize("path", _REVIEW_TEXT_PATHS)
def test_review_unicode_identity_alias_is_rejected(path):
    assert _SCALAR_TEXT != _SURROGATE_TEXT
    # The old JSON policy gives these unequal Python strings the same bytes.
    assert json.dumps(_SCALAR_TEXT, ensure_ascii=True) == json.dumps(_SURROGATE_TEXT, ensure_ascii=True)
    valid = CoastOrbitInputs.from_dict(_text_payload(path, _SCALAR_TEXT))
    bound = _binding(valid)
    with pytest.raises(ValueError, match="Unicode scalar values"):
        substitute = CoastOrbitInputs.from_dict(_text_payload(path, _SURROGATE_TEXT))
        replace(bound, coast_orbit=substitute)


@pytest.mark.parametrize("path", _REVIEW_TEXT_PATHS)
def test_review_unicode_roundtrip_loss_is_rejected(path):
    assert json.loads(json.dumps(_SURROGATE_TEXT, ensure_ascii=True)) == _SCALAR_TEXT
    with pytest.raises(ValueError, match="Unicode scalar values"):
        CoastOrbitInputs.from_dict(_text_payload(path, _SURROGATE_TEXT))
    # Normal escaped JSON for a non-BMP scalar remains a supported input.
    valid = CoastOrbitInputs.from_dict(json.loads(json.dumps(_text_payload(path, _SCALAR_TEXT),
                                                           ensure_ascii=True, allow_nan=False)))
    rebuilt = CoastOrbitInputs.from_dict(json.loads(json.dumps(valid.to_dict(), ensure_ascii=True, allow_nan=False)))
    assert rebuilt == valid and _binding(rebuilt).model_manifest == _binding(valid).model_manifest


@pytest.mark.parametrize("path,objects", _TEXT_LOCATIONS)
@pytest.mark.parametrize("text", ["Test \ud800", "Test \udfff", _SURROGATE_TEXT])
@pytest.mark.parametrize("boundary", ["direct", "read", "encode", "bind"])
def test_surrogates_rejected_in_every_portable_text_location(path, objects, text, boundary):
    forged = _forge_text_fields(_coast(), objects, text)
    # These are valid A/B1 domains; only B2 narrows the portable text contract.
    trajectory = TwoBodyTrajectory(forged.trajectory.initial_state, forged.trajectory.gravitational_parameter_m3_s2)
    with pytest.raises(ValueError, match="Unicode scalar values"):
        if boundary == "direct":
            CoastOrbitInputs(trajectory, forged.solver_config)
        elif boundary == "read":
            CoastOrbitInputs.from_dict(_text_payload(path, text))
        elif boundary == "encode":
            forged.to_dict()
        else:
            _binding(forged)


@pytest.mark.parametrize("path,objects", _TEXT_LOCATIONS)
@pytest.mark.parametrize("text_type", [PlainText, ComparisonText])
@pytest.mark.parametrize("boundary", ["direct", "read", "encode", "bind"])
def test_subclass_text_rejected_without_coercion(path, objects, text_type, boundary):
    text = text_type("Otherwise valid text")
    forged = _forge_text_fields(_coast(), objects, text)
    # Ellipsoid names already require exact str in A; provenance did not.
    with pytest.raises((TypeError, ValueError)):
        if boundary == "direct":
            CoastOrbitInputs(forged.trajectory, forged.solver_config)
        elif boundary == "read":
            CoastOrbitInputs.from_dict(_text_payload(path, text))
        elif boundary == "encode":
            forged.to_dict()
        else:
            _binding(forged)


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("field", ["parameter_id.value", "source_ids", "units"])
def test_all_parameter_id_source_and_units_text_require_builtin_str(index, field):
    coast = CoastOrbitInputs.from_dict(_rich_payload())
    p, objects = _PARAMETER_LOCATIONS[index]
    data = coast.to_dict()
    for key in p:
        data = data[key]
    provenance = data["provenance"]
    if field == "parameter_id.value":
        value = PlainText(provenance["parameter_id"].removeprefix("parameter:"))
    elif field == "source_ids":
        value = (SourceRecordId(PlainText("first")), SourceRecordId("second"))
    else:
        value = PlainText(provenance["units"])
    forged = _forge_text_fields(coast, tuple(x+".provenance."+field for x in objects), value)
    trajectory = TwoBodyTrajectory(forged.trajectory.initial_state, forged.trajectory.gravitational_parameter_m3_s2)
    for action in (lambda: CoastOrbitInputs(trajectory, forged.solver_config), forged.to_dict,
                   lambda: _binding(forged)):
        with pytest.raises(TypeError, match="exact str"):
            action()


def test_velocity_frame_text_cannot_hide_behind_overridden_equality():
    bad = _forge(_coast(), "trajectory.initial_state.velocity.frame.ellipsoid.flattening.provenance.rationale",
                 ComparisonText("Different velocity metadata"))
    trajectory = TwoBodyTrajectory(bad.trajectory.initial_state, bad.trajectory.gravitational_parameter_m3_s2)
    assert trajectory.initial_state.position.frame == trajectory.initial_state.velocity.frame
    for action in (lambda: CoastOrbitInputs(trajectory, bad.solver_config), bad.to_dict, lambda: _binding(bad)):
        with pytest.raises(TypeError, match="exact str"):
            action()


@pytest.mark.parametrize("path,objects", _TEXT_LOCATIONS)
@pytest.mark.parametrize("text", ["ASCII text", "Кириллица", _SCALAR_TEXT, "Caf\u00e9", "Cafe\u0301"])
def test_scalar_unicode_roundtrips_exactly_and_valid_text_changes_identity(path, objects, text):
    payload = _text_payload(path, text)
    coast = CoastOrbitInputs.from_dict(payload)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    rebuilt = CoastOrbitInputs.from_dict(json.loads(canonical))
    assert rebuilt == coast and rebuilt.to_dict() == payload
    assert _binding(rebuilt).model_manifest == _binding(coast).model_manifest
    changed = CoastOrbitInputs.from_dict(_text_payload(path, text+"!"))
    assert _binding(changed).model_manifest != _binding(coast).model_manifest


@pytest.mark.parametrize("path,objects", _TEXT_LOCATIONS)
def test_nfc_and_nfd_spellings_remain_distinct(path, objects):
    nfc = CoastOrbitInputs.from_dict(_text_payload(path, "Caf\u00e9"))
    nfd = CoastOrbitInputs.from_dict(_text_payload(path, "Cafe\u0301"))
    assert nfc != nfd
    assert _binding(nfc).model_manifest != _binding(nfd).model_manifest
