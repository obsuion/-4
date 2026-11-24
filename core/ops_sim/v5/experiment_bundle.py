"""Versioned content-bound continuation around the unchanged schema-5 API.

This is integrity/reproducibility checking, not authentication. A party that
replaces a valid experiment and all its digests can declare a different run.
Legacy CheckpointState.restore remains ID-based outside this boundary.
"""

from dataclasses import dataclass
from pathlib import Path

from .checkpoint import CheckpointState
from .context import SimulationInputs
from .continuation import (
    RANDOMNESS_MODE, ContinuationMemory, ContinuationProgram, ContinuationState,
    checked_checkpoint,
)
from .experiment_codec import (
    CANONICAL_VERSION, canonical_content, canonical_copy, content_digest,
    decode_content, json_text, object_fields, parse_json,
)
from .experiment_provenance import capture_provenance, validate_provenance
from .operational_continuation import OperationalProgram, OperationalMemory, OperationalState
from .substepped_continuation import SubsteppedProgram, SubsteppedMemory, SubsteppedState
from .contact_continuation import ContactProgram, ContactMemory, ContactState
from .ms_continuation import MSMissionProgram, MSMissionMemory, MSMissionState
from .campaign_contract import MSCampaignProgram, MSCampaignMemory
from .campaign_continuation import MSCampaignState


BUNDLE_VERSION = 1
_FIELDS = ("bundle_version", "canonical_version", "inputs", "program", "randomness",
           "input_digest", "checkpoint", "memory", "runtime_digest", "provenance", "bundle_digest")


def experiment_input_digest(inputs: SimulationInputs, program: ContinuationProgram | OperationalProgram | SubsteppedProgram | ContactProgram | MSMissionProgram | MSCampaignProgram):
    if type(inputs) is not SimulationInputs or type(program) not in (ContinuationProgram, OperationalProgram, SubsteppedProgram, ContactProgram, MSMissionProgram, MSCampaignProgram):
        raise TypeError("input identity requires SimulationInputs and a supported program")
    return content_digest("v5-experiment-input-v1", (inputs, program, RANDOMNESS_MODE))


def _runtime_digest(payload):
    return content_digest("v5-continuation-state-v1", {
        "input_digest": payload["input_digest"], "checkpoint": payload["checkpoint"], "memory": payload["memory"],
    })


def _bundle_digest(payload):
    return content_digest("v5-experiment-bundle-v1", {k: v for k, v in payload.items() if k != "bundle_digest"})


def _validated_payload(payload):
    object_fields(payload, _FIELDS)
    for field, expected in (("bundle_version", BUNDLE_VERSION), ("canonical_version", CANONICAL_VERSION)):
        if type(payload[field]) is not int or payload[field] != expected:
            raise ValueError(f"unsupported {field}")
    if type(payload["randomness"]) is not str or payload["randomness"] != RANDOMNESS_MODE:
        raise ValueError("unsupported or missing randomness mode")
    inputs, program = decode_content(payload["inputs"]), decode_content(payload["program"])
    identity = experiment_input_digest(inputs, program)
    if identity != payload["input_digest"]:
        raise ValueError("immutable input content digest mismatch")
    checkpoint = object_fields(payload["checkpoint"], ("input_digest", "schema5"))
    if checkpoint["input_digest"] != identity:
        raise ValueError("checkpoint input binding mismatch")
    if _runtime_digest(payload) != payload["runtime_digest"]:
        raise ValueError("checkpoint/memory integrity mismatch")
    validate_provenance(payload["provenance"])
    if _bundle_digest(payload) != payload["bundle_digest"]:
        raise ValueError("bundle integrity mismatch")
    # Checksums do not substitute for constructor and cross-owner validation.
    memory = decode_content(payload["memory"])
    expected_memory = {ContinuationProgram: ContinuationMemory, OperationalProgram: OperationalMemory,
                       SubsteppedProgram: SubsteppedMemory, ContactProgram: ContactMemory,
                       MSMissionProgram: MSMissionMemory, MSCampaignProgram: MSCampaignMemory}[type(program)]
    if type(memory) is not expected_memory:
        raise TypeError("bundle requires the program's explicit memory type")
    snapshot = CheckpointState.from_dict(checkpoint["schema5"])
    if canonical_content(checkpoint["schema5"]) != canonical_content(snapshot.to_dict()):
        raise ValueError("checkpoint wire content is not losslessly representable by schema 5")
    context = snapshot.restore(inputs)
    owner = {ContinuationProgram: ContinuationState, OperationalProgram: OperationalState,
             SubsteppedProgram: SubsteppedState, ContactProgram: ContactState,
             MSMissionProgram: MSMissionState, MSCampaignProgram: MSCampaignState}[type(program)]
    return owner(context, program, memory)


@dataclass(frozen=True, slots=True)
class ExperimentBundle:
    """Immutable JSON authority; accessors return fresh values, never a mutable alias."""

    json_content: str

    def __post_init__(self):
        payload = parse_json(self.json_content)
        _validated_payload(payload)
        object.__setattr__(self, "json_content", json_text(payload))

    @classmethod
    def from_json(cls, text: str):
        return cls(text)

    def to_json(self):
        # Revalidate even if an external caller bypassed frozen guards.
        _validated_payload(parse_json(self.json_content))
        return self.json_content

    @property
    def input_digest(self):
        return parse_json(self.to_json())["input_digest"]

    @property
    def runtime_digest(self):
        return parse_json(self.to_json())["runtime_digest"]

    def restore(self, *, repository_root: Path, expected_inputs: SimulationInputs | None = None,
                expected_program: ContinuationProgram | OperationalProgram | SubsteppedProgram | ContactProgram | MSMissionProgram | MSCampaignProgram | None = None):
        """Return fresh state after content and code/environment compatibility checks.

        No existing context, memory, queue or RNG is mutated. If supplied, caller
        inputs/program are compared before calling the low-level restore API.
        Otherwise validated constructors reconstruct them from embedded content.
        """
        payload = object_fields(parse_json(self.json_content), _FIELDS)
        if expected_inputs is not None:
            if type(expected_inputs) is not SimulationInputs:
                raise TypeError("expected_inputs must be SimulationInputs")
            if canonical_content(expected_inputs) != payload["inputs"]:
                raise ValueError("supplied input content differs from bundle")
        if expected_program is not None:
            if type(expected_program) not in (ContinuationProgram, OperationalProgram, SubsteppedProgram, ContactProgram, MSMissionProgram, MSCampaignProgram):
                raise TypeError("expected_program must be a supported program")
            if canonical_content(expected_program) != payload["program"]:
                raise ValueError("supplied program/forcing content differs from bundle")
        current = capture_provenance(repository_root)
        validate_provenance(payload["provenance"])
        if current["compatibility_digest"] != payload["provenance"]["compatibility_digest"]:
            raise ValueError("implementation/environment compatibility mismatch")
        return _validated_payload(payload)


def create_bundle(state: ContinuationState | OperationalState | SubsteppedState | ContactState | MSMissionState | MSCampaignState, *, repository_root: Path) -> ExperimentBundle:
    """Capture a validated completed boundary, all explicit memory and actual code."""
    if type(state) not in (ContinuationState, OperationalState, SubsteppedState, ContactState, MSMissionState, MSCampaignState):
        raise TypeError("state must be a supported continuation state")
    state.__post_init__()
    inputs = canonical_copy(state.context.inputs)
    program = canonical_copy(state.program)
    identity = experiment_input_digest(inputs, program)
    payload = {
        "bundle_version": BUNDLE_VERSION, "canonical_version": CANONICAL_VERSION,
        "inputs": canonical_content(inputs), "program": canonical_content(program),
        "randomness": RANDOMNESS_MODE, "input_digest": identity,
        "checkpoint": {"input_digest": identity, "schema5": checked_checkpoint(state.context).to_dict()},
        "memory": canonical_content(state.memory), "provenance": capture_provenance(repository_root),
    }
    payload["runtime_digest"] = _runtime_digest(payload)
    payload["bundle_digest"] = _bundle_digest(payload)
    return ExperimentBundle(json_text(payload))


__all__ = ["BUNDLE_VERSION", "ExperimentBundle", "create_bundle", "experiment_input_digest"]
