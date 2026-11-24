"""Versioned coast definitions and bounded run-content identity (no propagation).

The digest covers coast content, manifest associations, numerical values and
world horizon/events only. Hardware and other definitions retain their legacy
ID protections. This is reproducibility checking, not authentication or a
fingerprint of source documents, executable files or the complete experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .frames import CartesianPosition, CartesianState, CartesianVelocity
from .ids import (
    ControllerId, EnvironmentId, FlightRulesId, ModelManifestId, NumericalConfigId,
    ParameterId, ScenarioId, SourceRecordId, SpacecraftConfigurationId,
    WorldEventId, WorldId,
)
from .manifest import ModelManifest
from .orbit import TwoBodySolverConfig, TwoBodyTrajectory
from .orbit_config import (
    FrameDefinition, FrameKind, GeometryInstant, ReferenceEllipsoid, TTEpoch,
    UniformRotationDefinition, _exact, _real,
)
from .parameters import ScalarParameter
from .provenance import (
    ParameterProvenance, ProvenanceClass, ProvenanceStatus, SensitivityRange,
)
from .run_config import NumericalConfig
from .world import CommonWorld


COAST_REPRESENTATION_VERSION = 1
COAST_MODEL = "v56b1-elliptic-two-body"
COAST_BINDING_VERSION = 1
COAST_MANIFEST_NAMESPACE = "v56b2-coast"
COAST_MANIFEST_PREFIX = COAST_MANIFEST_NAMESPACE + "-sha256-"


@dataclass(frozen=True, slots=True)
class CoastOrbitInputs:
    """One run's immutable coast definition; no current-state or query cache."""

    trajectory: TwoBodyTrajectory
    solver_config: TwoBodySolverConfig

    def __post_init__(self) -> None:
        _exact(self.trajectory, TwoBodyTrajectory, "trajectory")
        _exact(self.solver_config, TwoBodySolverConfig, "solver_config")
        trajectory = TwoBodyTrajectory(
            self.trajectory.initial_state, self.trajectory.gravitational_parameter_m3_s2,
        )
        solver = TwoBodySolverConfig(
            self.solver_config.time_tolerance_seconds, self.solver_config.max_iterations,
        )
        _coast_text(trajectory)
        object.__setattr__(self, "trajectory", trajectory)
        object.__setattr__(self, "solver_config", solver)

    def to_dict(self) -> dict[str, object]:
        """Return strict portable definitions, separately from checkpoint state."""
        coast = _validated_coast(self)
        state = coast.trajectory.initial_state
        frame = state.position.frame
        return {
            "representation_version": COAST_REPRESENTATION_VERSION,
            "model": COAST_MODEL,
            "initial_state": {
                "position_m": [x.hex() for x in state.position.components_m],
                "velocity_m_per_s": [x.hex() for x in state.velocity.components_m_per_s],
                "instant": {"epoch": _epoch_dict(state.position.instant.epoch),
                            "elapsed_seconds": state.position.instant.elapsed_seconds.hex()},
                "frame": {
                    "kind": frame.kind.value,
                    "ellipsoid": {"name": frame.ellipsoid.name,
                                  "equatorial_radius_m": _parameter_dict(frame.ellipsoid.equatorial_radius_m),
                                  "flattening": _parameter_dict(frame.ellipsoid.flattening)},
                    "rotation": {"epoch": _epoch_dict(frame.rotation.epoch),
                                 "initial_phase_rad": _parameter_dict(frame.rotation.initial_phase_rad),
                                 "angular_velocity_rad_per_s": _parameter_dict(frame.rotation.angular_velocity_rad_per_s)},
                },
            },
            "gravitational_parameter_m3_s2": _parameter_dict(coast.trajectory.gravitational_parameter_m3_s2),
            "solver_config": {"time_tolerance_seconds": coast.solver_config.time_tolerance_seconds.hex(),
                              "max_iterations": coast.solver_config.max_iterations},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> CoastOrbitInputs:
        """Reject unknown structure/encodings, then rebuild through A/B1 contracts."""
        p = _object(payload, ("representation_version", "model", "initial_state",
                              "gravitational_parameter_m3_s2", "solver_config"))
        if _integer(p["representation_version"]) != COAST_REPRESENTATION_VERSION:
            raise ValueError("unknown coast representation version")
        if _text(p["model"]) != COAST_MODEL:
            raise ValueError("unknown coast model")
        state = _object(p["initial_state"], ("position_m", "velocity_m_per_s", "instant", "frame"))
        instant = _object(state["instant"], ("epoch", "elapsed_seconds"))
        when = GeometryInstant(_read_epoch(instant["epoch"]), _number(instant["elapsed_seconds"]))
        frame = _object(state["frame"], ("kind", "ellipsoid", "rotation"))
        ellipsoid = _object(frame["ellipsoid"], ("name", "equatorial_radius_m", "flattening"))
        rotation = _object(frame["rotation"], ("epoch", "initial_phase_rad", "angular_velocity_rad_per_s"))
        axes = FrameDefinition(
            FrameKind(_text(frame["kind"])),
            ReferenceEllipsoid(_text(ellipsoid["name"]), _read_parameter(ellipsoid["equatorial_radius_m"]),
                               _read_parameter(ellipsoid["flattening"])),
            UniformRotationDefinition(_read_epoch(rotation["epoch"]),
                                      _read_parameter(rotation["initial_phase_rad"]),
                                      _read_parameter(rotation["angular_velocity_rad_per_s"])),
        )
        solver = _object(p["solver_config"], ("time_tolerance_seconds", "max_iterations"))
        return cls(
            TwoBodyTrajectory(CartesianState(
                CartesianPosition(axes, when, _read_vector(state["position_m"])),
                CartesianVelocity(axes, when, _read_vector(state["velocity_m_per_s"])),
            ), _read_parameter(p["gravitational_parameter_m3_s2"])),
            TwoBodySolverConfig(_number(solver["time_tolerance_seconds"]), _integer(solver["max_iterations"])),
        )


def _validated_coast(value: object) -> CoastOrbitInputs:
    _exact(value, CoastOrbitInputs, "coast_orbit")
    return CoastOrbitInputs(value.trajectory, value.solver_config)


def _epoch_dict(epoch: TTEpoch) -> dict[str, object]:
    return {"julian_day": epoch.julian_day, "fractional_day": epoch.fractional_day.hex()}


def _parameter_dict(parameter: ScalarParameter) -> dict[str, object]:
    p = parameter.provenance
    bounds = p.sensitivity_range
    return {"value": parameter.value.hex(), "provenance": {
        "parameter_id": p.parameter_id.canonical, "classification": p.classification.value,
        "units": p.units, "source_ids": [s.canonical for s in p.source_ids], "status": p.status.value,
        "rationale": p.rationale, "derivation": p.derivation,
        "sensitivity_range": None if bounds is None else {"lower": bounds.lower.hex(), "upper": bounds.upper.hex()},
    }}


def _object(value: object, keys: tuple[str, ...]) -> dict[str, object]:
    _exact(value, dict, "portable object")
    if set(value) != set(keys) or not all(type(key) is str for key in value):
        raise ValueError("portable object has missing or extra keys")
    return value


def _text(value: object) -> str:
    """Exact scalar-Unicode text; preserve content without coercion/normalization."""
    _exact(value, str, "portable text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("portable text must contain only Unicode scalar values (no surrogates)") from error
    return value


def _parameter_text(parameter: ScalarParameter) -> None:
    """Inspect known text fields after authoritative A/B1 graph validation."""
    p = parameter.provenance
    _text(p.parameter_id.value)
    _text(p.classification.value)
    _text(p.units)
    for source in p.source_ids:
        _text(source.value)
    _text(p.status.value)
    for optional in (p.rationale, p.derivation):
        if optional is not None:
            _text(optional)


def _coast_text(trajectory: TwoBodyTrajectory) -> None:
    # Both frames survive A/B1 reconstruction. Subclass equality must not hide
    # invalid velocity-frame text when the codec later encodes the shared frame.
    for frame in (trajectory.initial_state.position.frame, trajectory.initial_state.velocity.frame):
        _text(frame.kind.value)
        _text(frame.ellipsoid.name)
        for parameter in (frame.ellipsoid.equatorial_radius_m, frame.ellipsoid.flattening,
                          frame.rotation.initial_phase_rad, frame.rotation.angular_velocity_rad_per_s):
            _parameter_text(parameter)
    _parameter_text(trajectory.gravitational_parameter_m3_s2)


def _integer(value: object) -> int:
    _exact(value, int, "portable integer")
    return value


def _number(value: object) -> float:
    text = _text(value)
    try:
        number = _real("portable number", float.fromhex(text))
    except (ValueError, OverflowError) as error:
        raise ValueError("invalid canonical binary64 encoding") from error
    if number.hex() != text:
        raise ValueError("invalid canonical binary64 encoding")
    return number


def _read_epoch(value: object) -> TTEpoch:
    p = _object(value, ("julian_day", "fractional_day"))
    return TTEpoch(_integer(p["julian_day"]), _number(p["fractional_day"]))


def _read_vector(value: object) -> tuple[float, float, float]:
    _exact(value, list, "portable vector")
    if len(value) != 3:
        raise ValueError("portable vector must have three components")
    return tuple(_number(x) for x in value)


def _read_parameter(value: object) -> ScalarParameter:
    parameter = _object(value, ("value", "provenance"))
    p = _object(parameter["provenance"], ("parameter_id", "classification", "units", "source_ids",
                                          "status", "rationale", "derivation", "sensitivity_range"))
    _exact(p["source_ids"], list, "portable source IDs")
    bounds = p["sensitivity_range"]
    if bounds is not None:
        bounds = _object(bounds, ("lower", "upper"))
        bounds = SensitivityRange(_number(bounds["lower"]), _number(bounds["upper"]))
    return ScalarParameter(_number(parameter["value"]), ParameterProvenance(
        ParameterId.from_canonical(_text(p["parameter_id"])),
        ProvenanceClass(_text(p["classification"])), _text(p["units"]),
        tuple(SourceRecordId.from_canonical(_text(s)) for s in p["source_ids"]),
        ProvenanceStatus(_text(p["status"])),
        None if p["rationale"] is None else _text(p["rationale"]),
        None if p["derivation"] is None else _text(p["derivation"]), bounds,
    ))


def _id(value: object, cls: type):
    _exact(value, cls, "binding ID")
    return cls(_text(value.value))


def coast_binding_payload(
    coast_orbit: CoastOrbitInputs, manifest: ModelManifest,
    numerical_config: NumericalConfig, common_world: CommonWorld,
) -> dict[str, object]:
    """Revalidate and encode the explicitly bounded binding; exclude manifest_id."""
    context = _binding_context(manifest, numerical_config, common_world)
    return {"binding_version": COAST_BINDING_VERSION,
            "coast_orbit": CoastOrbitInputs.to_dict(coast_orbit), **context}


def _binding_context(manifest, numerical_config, common_world) -> dict[str, object]:
    """Shared association context; keep the historical B2 payload byte-stable."""
    _exact(manifest, ModelManifest, "model_manifest")
    m = ModelManifest(
        _id(manifest.manifest_id, ModelManifestId), manifest.schema_version,
        _id(manifest.spacecraft_configuration_id, SpacecraftConfigurationId),
        _id(manifest.numerical_config_id, NumericalConfigId), _id(manifest.environment_id, EnvironmentId),
        _id(manifest.flight_rules_id, FlightRulesId), _id(manifest.scenario_id, ScenarioId),
        _id(manifest.world_id, WorldId), _id(manifest.controller_id, ControllerId),
    )
    _exact(numerical_config, NumericalConfig, "numerical_config")
    n = NumericalConfig(_id(numerical_config.configuration_id, NumericalConfigId),
                        numerical_config.timestep_seconds, numerical_config.geometry_sample_seconds,
                        numerical_config.checkpoint_interval_seconds)
    _exact(common_world, CommonWorld, "common_world")
    _exact(common_world.event_ids, tuple, "event_ids")
    w = CommonWorld(_id(common_world.world_id, WorldId), _id(common_world.scenario_id, ScenarioId),
                    common_world.horizon_seconds, tuple(_id(e, WorldEventId) for e in common_world.event_ids))
    if (m.numerical_config_id != n.configuration_id or m.world_id != w.world_id
            or m.scenario_id != w.scenario_id):
        raise ValueError("coast binding input associations mismatch")
    return {"manifest": {"schema_version": m.schema_version,
                         "spacecraft_configuration_id": m.spacecraft_configuration_id.canonical,
                         "numerical_config_id": m.numerical_config_id.canonical,
                         "environment_id": m.environment_id.canonical,
                         "flight_rules_id": m.flight_rules_id.canonical,
                         "scenario_id": m.scenario_id.canonical, "world_id": m.world_id.canonical,
                         "controller_id": m.controller_id.canonical},
            "numerical": {"timestep_seconds": n.timestep_seconds,
                          "geometry_sample_seconds": n.geometry_sample_seconds,
                          "checkpoint_interval_seconds": n.checkpoint_interval_seconds},
            "world": {"horizon_seconds": w.horizon_seconds, "event_ids": [e.canonical for e in w.event_ids]}}


def derive_coast_manifest_id(
    coast_orbit: CoastOrbitInputs, manifest: ModelManifest,
    numerical_config: NumericalConfig, common_world: CommonWorld,
) -> ModelManifestId:
    """SHA-256 of canonical UTF-8 JSON; no cached digest, propagation or Git input."""
    payload = coast_binding_payload(coast_orbit, manifest, numerical_config, common_world)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return ModelManifestId(COAST_MANIFEST_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest())


def _validate_coast_binding(coast_orbit, manifest, numerical_config, common_world) -> None:
    identity = _id(manifest.manifest_id, ModelManifestId)
    if coast_orbit is None:
        # Apply the same text policy to the known identity inputs on both paths;
        # ordinary legacy IDs remain valid. No global StableId rule is changed.
        for value, cls in (
            (manifest.spacecraft_configuration_id, SpacecraftConfigurationId),
            (manifest.numerical_config_id, NumericalConfigId), (manifest.environment_id, EnvironmentId),
            (manifest.flight_rules_id, FlightRulesId), (manifest.scenario_id, ScenarioId),
            (manifest.world_id, WorldId), (manifest.controller_id, ControllerId),
            (numerical_config.configuration_id, NumericalConfigId),
            (common_world.world_id, WorldId), (common_world.scenario_id, ScenarioId),
        ):
            _id(value, cls)
        for event_id in common_world.event_ids:
            _id(event_id, WorldEventId)
        if identity.value.startswith(COAST_MANIFEST_NAMESPACE):
            raise ValueError("reserved coast manifest namespace requires coast_orbit")
    elif identity != derive_coast_manifest_id(coast_orbit, manifest, numerical_config, common_world):
        raise ValueError("coast binding identity mismatch")


__all__ = (
    "CoastOrbitInputs", "COAST_REPRESENTATION_VERSION", "COAST_MODEL", "COAST_BINDING_VERSION",
    "COAST_MANIFEST_NAMESPACE", "COAST_MANIFEST_PREFIX", "coast_binding_payload", "derive_coast_manifest_id",
)
