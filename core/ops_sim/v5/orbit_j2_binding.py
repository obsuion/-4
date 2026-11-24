"""F4 immutable J2 definitions and bounded content binding, without propagation.

Portable definitions use the existing strict typed codec, canonical version 1.
Imports of that codec are local because its explicit allowlist includes this
owner. No result, Decimal interval, current orbital state or cache is authority.
"""

from dataclasses import dataclass, field
import hashlib
import json

from .ids import ModelManifestId
from .orbit_binding import _binding_context, _id, _validate_coast_binding
from .orbit_config import _exact
from .orbit_j2 import J2CartesianTrajectory, J2RK4SolverConfig
from .orbit_j2_enclosure import J2EnclosurePolicy


J2_MODEL = "v56f-static-axis-cartesian-j2"
J2_REPRESENTATION_VERSION = 1
J2_BINDING_VERSION = 1
J2_F3_POLICY_VERSION = 1
J2_MANIFEST_NAMESPACE = "v56f4-j2-coast"
J2_MANIFEST_PREFIX = J2_MANIFEST_NAMESPACE + "-sha256-"


@dataclass(frozen=True, slots=True)
class J2CoastOrbitInputs:
    """One original trajectory, nominal solver and accumulated-error policy.

    Version fields are explicit persisted semantics, not tunable algorithms.
    Only the declared values are accepted. Construction rechecks F1/F2/F3
    input owners (including F2's constant-work initial-force admission), never
    integrates. Physical owners retain their existing zero normalization.
    """

    trajectory: J2CartesianTrajectory
    solver_config: J2RK4SolverConfig
    enclosure_policy: J2EnclosurePolicy
    model: str = field(default=J2_MODEL, kw_only=True)
    representation_version: int = field(default=J2_REPRESENTATION_VERSION, kw_only=True)
    binding_version: int = field(default=J2_BINDING_VERSION, kw_only=True)
    policy_version: int = field(default=J2_F3_POLICY_VERSION, kw_only=True)

    def __post_init__(self):
        _exact(self.model, str, "J2 model")
        if self.model != J2_MODEL:
            raise ValueError("unknown J2 model")
        for name, supported in (("representation_version", J2_REPRESENTATION_VERSION),
                                ("binding_version", J2_BINDING_VERSION),
                                ("policy_version", J2_F3_POLICY_VERSION)):
            _exact(getattr(self, name), int, name)
            if getattr(self, name) != supported:
                raise ValueError(f"unsupported J2 {name}")
        _exact(self.trajectory, J2CartesianTrajectory, "trajectory")
        _exact(self.solver_config, J2RK4SolverConfig, "solver_config")
        _exact(self.enclosure_policy, J2EnclosurePolicy, "enclosure_policy")
        trajectory = J2CartesianTrajectory(self.trajectory.initial_state, self.trajectory.gravity_model)
        solver = J2RK4SolverConfig(self.solver_config.step_seconds, self.solver_config.max_steps)
        p = self.enclosure_policy
        policy = J2EnclosurePolicy(p.step_seconds, p.max_steps, p.min_radius_m,
                                   p.precision_digits, p.max_picard_iterations)
        object.__setattr__(self, "trajectory", trajectory)
        object.__setattr__(self, "solver_config", solver)
        object.__setattr__(self, "enclosure_policy", policy)

    def to_dict(self):
        from .experiment_codec import canonical_content

        _exact(self, J2CoastOrbitInputs, "J2 coast_orbit")
        return canonical_content(self)

    @classmethod
    def from_dict(cls, payload):
        from .experiment_codec import decode_content

        value = decode_content(payload)
        _exact(value, J2CoastOrbitInputs, "J2 coast_orbit")
        return value

    def to_json(self):
        from .experiment_codec import json_text

        return json_text(J2CoastOrbitInputs.to_dict(self))

    @classmethod
    def from_json(cls, text):
        from .experiment_codec import parse_json

        return cls.from_dict(parse_json(text))


def j2_coast_binding_payload(coast_orbit, manifest, numerical_config, common_world):
    """Complete J2 input plus B2's bounded association/world/numerical context.

    This is not the full experiment digest or executable/environment provenance.
    The prior manifest label is validated but excluded from the hashed content.
    """
    context = _binding_context(manifest, numerical_config, common_world)
    return {"binding_version": J2_BINDING_VERSION,
            "coast_orbit": J2CoastOrbitInputs.to_dict(coast_orbit), **context}


def derive_j2_coast_manifest_id(coast_orbit, manifest, numerical_config, common_world):
    payload = j2_coast_binding_payload(coast_orbit, manifest, numerical_config, common_world)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    return ModelManifestId(J2_MANIFEST_PREFIX + hashlib.sha256(encoded).hexdigest())


def _validate_bound_coast(coast_orbit, manifest, numerical_config, common_world):
    """Exact-type dispatch; reserved identities cannot downgrade to legacy inputs."""
    identity = _id(manifest.manifest_id, ModelManifestId)
    if type(coast_orbit) is J2CoastOrbitInputs:
        if identity != derive_j2_coast_manifest_id(coast_orbit, manifest, numerical_config, common_world):
            raise ValueError("J2 coast binding identity mismatch")
    else:
        if identity.value.startswith(J2_MANIFEST_NAMESPACE):
            raise ValueError("reserved J2 coast manifest namespace requires J2CoastOrbitInputs")
        _validate_coast_binding(coast_orbit, manifest, numerical_config, common_world)


__all__ = ["J2CoastOrbitInputs", "J2_MODEL", "J2_REPRESENTATION_VERSION",
           "J2_BINDING_VERSION", "J2_F3_POLICY_VERSION", "J2_MANIFEST_NAMESPACE",
           "J2_MANIFEST_PREFIX", "j2_coast_binding_payload", "derive_j2_coast_manifest_id"]
