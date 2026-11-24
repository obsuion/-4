"""F1 ownership, scientific metadata, and bounded dependency contract."""

import ast
from dataclasses import FrozenInstanceError, MISSING, fields, replace
import inspect
from pathlib import Path

import pytest

from ops_sim.v5 import orbit_j2_gravity as gravity
from ops_sim.v5.frames import CartesianPosition, CartesianState, CartesianVelocity
from ops_sim.v5.ids import ParameterId, SourceRecordId
from ops_sim.v5.orbit_config import (
    FrameDefinition, FrameKind, GeometryInstant, ReferenceEllipsoid, TTEpoch,
    UniformRotationDefinition,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import (
    ParameterProvenance, ProvenanceClass, ProvenanceStatus, SensitivityRange,
)


def parameter(identifier, value, units):
    return ScalarParameter(value, ParameterProvenance(
        ParameterId(identifier), ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
        units, (SourceRecordId("synthetic-z"), SourceRecordId("synthetic-a")),
        ProvenanceStatus.VERIFIED, rationale="Synthetic F1 verification input",
    ))


def make_model(mu=8, j2=1/16, radius=1):
    return gravity.J2GravityModel(
        parameter("orbit.gravity.gravitational-parameter", mu, "m^3/s^2"),
        parameter("orbit.gravity.j2", j2, "1"),
        parameter("orbit.gravity.reference-radius", radius, "m"),
    )


def make_position(components=(2, 0, 0)):
    epoch = TTEpoch(2451545, 0.125)
    ellipsoid = ReferenceEllipsoid("Synthetic shape", parameter("orbit.earth.equatorial-radius", 1, "m"),
                                   parameter("orbit.earth.flattening", 0.125, "1"))
    rotation = UniformRotationDefinition(epoch, parameter("orbit.rotation.initial-phase", 0.25, "rad"),
                                         parameter("orbit.rotation.angular-rate", -0.0625, "rad/s"))
    return CartesianPosition(FrameDefinition(FrameKind.MODEL_INERTIAL, ellipsoid, rotation),
                             GeometryInstant(epoch, 32.125), components)


def forge(value, /, **changes):
    result = object.__new__(type(value))
    for field in fields(value):
        object.__setattr__(result, field.name, changes.get(field.name, getattr(value, field.name)))
    return result


def change_path(value, path, replacement):
    first, *rest = path.split(".")
    current = getattr(value, first)
    return forge(value, **{first: change_path(current, ".".join(rest), replacement) if rest else replacement})


def outputs(result):
    return (result.acceleration_x_m_per_s2, result.acceleration_y_m_per_s2,
            result.acceleration_z_m_per_s2, result.specific_potential_m2_per_s2)


def test_exact_public_api_frozen_slots_required_inputs_and_no_output_injection():
    assert gravity.__all__ == ["J2GravityEvaluation", "J2GravityModel", "evaluate_j2_gravity"]
    assert tuple(f.name for f in fields(gravity.J2GravityModel)) == (
        "gravitational_parameter_m3_s2", "j2", "reference_radius_m")
    for owner in (gravity.J2GravityModel, gravity.J2GravityEvaluation):
        assert all(p.default is inspect.Parameter.empty for p in inspect.signature(owner).parameters.values())
        assert all(f.default is MISSING and f.default_factory is MISSING for f in fields(owner))
        assert owner.__hash__ is None
    result = gravity.evaluate_j2_gravity(make_model(), make_position())
    assert tuple(f.name for f in fields(result) if f.init) == ("model", "position")
    assert not hasattr(result, "__dict__") and not hasattr(result.model, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.specific_potential_m2_per_s2 = 0
    with pytest.raises(FrozenInstanceError):
        result.model.j2 = result.model.j2
    with pytest.raises(TypeError):
        gravity.J2GravityEvaluation(result.model, result.position, acceleration_x_m_per_s2=1)


def test_reconstruct_complete_evidence_and_replace_recomputes_all_outputs():
    model, position = make_model(), make_position()
    result = gravity.evaluate_j2_gravity(model, position)
    assert result.model == model and result.model is not model
    assert result.position == position and result.position is not position
    assert result.position.frame == position.frame
    assert result.position.instant == position.instant
    assert result.model.j2.provenance == model.j2.provenance
    assert result.model.j2.provenance is not model.j2.provenance
    poisoned = forge(result, **{f.name: 12345 for f in fields(result) if not f.init})
    assert outputs(replace(poisoned)) == outputs(result)
    changed = replace(poisoned, position=make_position((0, 0, 2)))
    assert outputs(changed) == (0, 0, -61/32, -63/16)
    assert outputs(replace(result, model=make_model(j2=0))) == (-2, 0, 0, -4)


def test_evaluator_delegates_to_result_owner(monkeypatch):
    sentinel, calls = object(), []
    monkeypatch.setattr(gravity, "J2GravityEvaluation", lambda *args: calls.append(args) or sentinel)
    model, position = make_model(), make_position()
    assert gravity.evaluate_j2_gravity(model, position) is sentinel
    assert calls == [(model, position)]


@pytest.mark.parametrize("name", ["gravitational_parameter_m3_s2", "j2", "reference_radius_m"])
@pytest.mark.parametrize("mutation", ["id", "units", "bool", "nan", "inf", "rejected", "superseded", "range", "source", "classification"])
def test_rejects_forged_parameter_graphs(name, mutation):
    model = make_model()
    scalar = getattr(model, name)
    if mutation == "id":
        scalar = change_path(scalar, "provenance.parameter_id", ParameterId("incorrect"))
    elif mutation == "units":
        scalar = change_path(scalar, "provenance.units", "incorrect")
    elif mutation in ("bool", "nan", "inf"):
        scalar = forge(scalar, value={"bool": True, "nan": float("nan"), "inf": float("inf")}[mutation])
    elif mutation in ("rejected", "superseded"):
        scalar = change_path(scalar, "provenance.status", ProvenanceStatus[mutation.upper()])
    elif mutation == "range":
        scalar = change_path(scalar, "provenance.sensitivity_range", forge(SensitivityRange(0, 1), lower=2))
    elif mutation == "source":
        scalar = change_path(scalar, "provenance.source_ids", (SourceRecordId("repeated"),)*2)
    else:
        scalar = change_path(scalar, "provenance.classification", "EXPLICIT_MODEL_ASSUMPTION")
    with pytest.raises((ValueError, TypeError)):
        gravity.evaluate_j2_gravity(forge(model, **{name: scalar}), make_position())


@pytest.mark.parametrize("field", ["gravitational_parameter_m3_s2", "reference_radius_m"])
@pytest.mark.parametrize("value", [0, -1])
def test_positive_mu_and_radius(field, value):
    model = make_model()
    with pytest.raises(ValueError):
        replace(model, **{field: replace(getattr(model, field), value=value)})


@pytest.mark.parametrize("field", ["mu", "j2", "radius"])
@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -float("inf")])
def test_nonfinite_and_bool_rejected_by_scalar_owner(field, value):
    with pytest.raises((ValueError, TypeError)):
        make_model(**{field: value})


class TextTrap(str):
    def _trap(self, *args):
        raise AssertionError("caller text hook executed")
    __eq__ = __ne__ = __hash__ = __str__ = __format__ = strip = encode = _trap


PARAMETER_TEXT_PATHS = (
    "provenance.parameter_id.value", "provenance.units",
    "provenance.rationale", "provenance.derivation", "source",
)


def poison_text(scalar, path, text):
    if path == "source":
        return change_path(scalar, "provenance.source_ids", (forge(SourceRecordId("valid"), value=text),))
    return change_path(scalar, path, text)


@pytest.mark.parametrize("name", ["gravitational_parameter_m3_s2", "j2", "reference_radius_m"])
@pytest.mark.parametrize("path", PARAMETER_TEXT_PATHS)
@pytest.mark.parametrize("bad", [TextTrap("different"), "\ud800", "\udfff", "\ud800\udfff"], ids=["hostile", "high", "low", "pair"])
def test_model_metadata_cannot_spoof_admission(name, path, bad):
    model = make_model()
    broken = forge(model, **{name: poison_text(getattr(model, name), path, bad)})
    with pytest.raises((TypeError, ValueError)):
        gravity.evaluate_j2_gravity(broken, make_position())


FRAME_PARAMETER_PATHS = (
    "frame.ellipsoid.equatorial_radius_m", "frame.ellipsoid.flattening",
    "frame.rotation.initial_phase_rad", "frame.rotation.angular_velocity_rad_per_s",
)


@pytest.mark.parametrize("parameter_path", FRAME_PARAMETER_PATHS)
@pytest.mark.parametrize("text_path", PARAMETER_TEXT_PATHS)
@pytest.mark.parametrize("bad", [TextTrap("different"), "\ud800"], ids=["hostile", "surrogate"])
def test_all_frame_scientific_metadata_is_checked(parameter_path, text_path, bad):
    position = make_position()
    scalar = position
    for name in parameter_path.split("."):
        scalar = getattr(scalar, name)
    broken = change_path(position, parameter_path, poison_text(scalar, text_path, bad))
    with pytest.raises((ValueError, TypeError)):
        gravity.evaluate_j2_gravity(make_model(), broken)


@pytest.mark.parametrize("bad", [TextTrap("different"), "\ud800"], ids=["hostile", "surrogate"])
def test_ellipsoid_name_text_is_checked(bad):
    with pytest.raises((TypeError, ValueError)):
        gravity.evaluate_j2_gravity(make_model(), change_path(make_position(), "frame.ellipsoid.name", bad))


def test_provenance_unicode_source_order_and_sensitivity_are_preserved():
    original = make_model()
    p = original.j2.provenance
    p = replace(p, rationale="Допущение \U0001f680 é", derivation="explicit synthetic coefficient",
                sensitivity_range=SensitivityRange(-1, 1))
    model = replace(original, j2=ScalarParameter(1/16, p))
    other = replace(model, j2=replace(model.j2, provenance=replace(p, rationale="Допущение \U0001f680 e\u0301")))
    result = gravity.evaluate_j2_gravity(model, make_position())
    assert result.model != other
    assert result.model.j2.provenance == p
    assert tuple(s.value for s in result.model.j2.provenance.source_ids) == ("synthetic-z", "synthetic-a")
    assert result.model.j2.provenance.sensitivity_range == SensitivityRange(-1, 1)
    assert original.j2.provenance.derivation is None


@pytest.mark.parametrize("status", [ProvenanceStatus.TO_RESEARCH, ProvenanceStatus.TO_VERIFY, ProvenanceStatus.VERIFIED])
def test_admissible_existing_provenance_statuses_are_not_redefined(status):
    model = make_model()
    changed = replace(model, j2=replace(model.j2, provenance=replace(model.j2.provenance, status=status)))
    assert gravity.evaluate_j2_gravity(changed, make_position()).model.j2.provenance.status is status


def test_exact_public_and_nested_owners():
    class ModelSubclass(gravity.J2GravityModel):
        pass
    class PositionSubclass(CartesianPosition):
        pass
    class ScalarSubclass(ScalarParameter):
        pass
    m, p = make_model(), make_position()
    bad_model = ModelSubclass(m.gravitational_parameter_m3_s2, m.j2, m.reference_radius_m)
    bad_position = PositionSubclass(p.frame, p.instant, p.components_m)
    state = CartesianState(p, CartesianVelocity(p.frame, p.instant, (0, 1, 0)))
    for model, position in ((bad_model, p), (m, bad_position), (m, state), (None, p), (m, None)):
        with pytest.raises(TypeError):
            gravity.evaluate_j2_gravity(model, position)
    with pytest.raises(TypeError):
        replace(m, j2=ScalarSubclass(m.j2.value, m.j2.provenance))
    for path, bad in (("provenance", None), ("provenance.parameter_id", SourceRecordId("wrong")),
                      ("provenance.source_ids", [SourceRecordId("wrong")]),
                      ("provenance.source_ids", (ParameterId("wrong"),)),
                      ("provenance.sensitivity_range", (0, 1))):
        with pytest.raises(TypeError):
            gravity.evaluate_j2_gravity(forge(m, j2=change_path(m.j2, path, bad)), p)


@pytest.mark.parametrize("path,bad", [
    ("components_m", (0, 0, 0)), ("components_m", (True, 0, 1)),
    ("components_m", (float("inf"), 0, 1)), ("components_m", [1, 0, 0]),
    ("frame.kind", FrameKind.EARTH_FIXED), ("frame.kind", "MODEL_INERTIAL"),
    ("instant.elapsed_seconds", True), ("instant.elapsed_seconds", 2**41),
    ("instant.epoch", TTEpoch(2451546, 0.125)),
])
def test_position_domain_and_complete_time_validation(path, bad):
    with pytest.raises((TypeError, ValueError)):
        gravity.evaluate_j2_gravity(make_model(), change_path(make_position(), path, bad))


def test_shape_and_rotation_are_evidence_but_not_gravity_parameter_authority():
    model, position = make_model(), make_position((3, 4, 12))
    changed_shape = replace(position.frame.ellipsoid,
                            equatorial_radius_m=parameter("orbit.earth.equatorial-radius", 100, "m"),
                            flattening=parameter("orbit.earth.flattening", 0.25, "1"))
    changed_rotation = replace(position.frame.rotation,
                               initial_phase_rad=parameter("orbit.rotation.initial-phase", -1, "rad"),
                               angular_velocity_rad_per_s=parameter("orbit.rotation.angular-rate", 0, "rad/s"))
    changed = replace(position, frame=replace(position.frame, ellipsoid=changed_shape, rotation=changed_rotation),
                      instant=replace(position.instant, elapsed_seconds=-8))
    assert outputs(gravity.evaluate_j2_gravity(model, changed)) == outputs(gravity.evaluate_j2_gravity(model, position))
    with pytest.raises(ValueError):
        replace(model, reference_radius_m=position.frame.ellipsoid.equatorial_radius_m)


def test_ast_import_and_instantaneous_ownership_guards():
    tree = ast.parse(Path(gravity.__file__).read_text(encoding="utf-8"))
    allowed = {"__future__", "dataclasses", "math", "frames", "ids", "orbit_config", "parameters", "provenance"}
    assert all(isinstance(node, ast.ImportFrom) and node.module in allowed
               for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))
    forbidden = ("rk4", "timestep", "propagat", "trajectory", "contact", "visibility", "opportunity",
                 "scheduler", "controller", "checkpoint", "engine", "uuid", "hashlib")
    names = [node.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Name)]
    names += [node.attr.lower() for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
    assert not any(word in name for name in names for word in forbidden)
    assert not any(isinstance(node, ast.While) for node in ast.walk(tree))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range"
                   for node in ast.walk(tree))
    # All numeric literals are algebraic coefficients/powers, never an Earth bundle.
    numbers = {node.value for node in ast.walk(tree)
               if isinstance(node, ast.Constant) and type(node.value) in (int, float)}
    assert numbers <= {0, 0.5, 1, 1.5, 2, 3, 5}
