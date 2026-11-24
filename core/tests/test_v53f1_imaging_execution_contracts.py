"""Scheduled imaging-execution domain contracts for V5.3F1."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from enum import Enum
from pathlib import Path
import subprocess

import numpy as np
import pytest

import ops_sim.v5.imaging_execution as execution_module
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    ImagingRequestId,
    MissionRequestId,
    ObservationOpportunityId,
)
from ops_sim.v5.imaging_execution import (
    ImagingExecutionAuthorizationStatus,
    ScheduledObservationAcquisitionExecution,
)
from ops_sim.v5.imaging_feasibility import ObservationAcquisitionCandidate
from ops_sim.v5.observation import ObservationOpportunity, ObservationPointing
from ops_sim.v5.observation_feasibility import ObservationManeuverCandidate
from ops_sim.v5.payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
)


ROOT = Path(__file__).resolve().parents[1]
EXECUTION_PATH = ROOT / "ops_sim" / "v5" / "imaging_execution.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"


def _candidate(
    *,
    duration_seconds: int = 23,
    window_start_seconds: int = 100,
    window_end_seconds: int = 200,
) -> ObservationAcquisitionCandidate:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("f1-opportunity"),
        ImagingRequestId("f1-request"),
        window_start_seconds,
        window_end_seconds,
        duration_seconds,
        ObservationPointing(10.0, 20.0),
    )
    maneuver_candidate = ObservationManeuverCandidate(
        opportunity,
        CommonFrameBoresightDirection(
            ADCSBoresightFrameId("f1-common-frame"),
            0.0,
            0.0,
            1.0,
        ),
    )
    return ObservationAcquisitionCandidate(
        maneuver_candidate,
        OpticalAcquisitionInput(
            20.0,
            40.0,
            duration_seconds,
            OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        ),
    )


def test_authorization_status_has_exact_three_ordered_string_values() -> None:
    assert issubclass(ImagingExecutionAuthorizationStatus, str)
    assert issubclass(ImagingExecutionAuthorizationStatus, Enum)
    assert tuple(
        (item.name, item.value) for item in ImagingExecutionAuthorizationStatus
    ) == (
        ("AUTHORIZED", "authorized"),
        ("SEQUENCE_INFEASIBLE", "sequence-infeasible"),
        (
            "ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED",
            "electrical-full-service-not-established",
        ),
    )


def test_scheduled_execution_has_exact_frozen_slotted_required_fields() -> None:
    execution = ScheduledObservationAcquisitionExecution(_candidate(), 100)

    assert tuple(
        field.name for field in fields(ScheduledObservationAcquisitionExecution)
    ) == ("candidate", "scheduled_start_seconds")
    assert ScheduledObservationAcquisitionExecution.__dataclass_params__.frozen
    assert not hasattr(execution, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(ScheduledObservationAcquisitionExecution)
    )
    with pytest.raises(FrozenInstanceError):
        execution.scheduled_start_seconds = 101


def test_scheduled_execution_requires_exact_candidate_type() -> None:
    candidate = _candidate()

    class CandidateSubclass(ObservationAcquisitionCandidate):
        pass

    subclass = CandidateSubclass(
        candidate.maneuver_candidate,
        candidate.acquisition_input,
    )
    for invalid in (object(), subclass):
        with pytest.raises(TypeError, match="candidate"):
            ScheduledObservationAcquisitionExecution(invalid, 100)


@pytest.mark.parametrize(
    ("corruption", "message"),
    (
        ("opportunity", "window_start_seconds"),
        ("acquisition", "effective_cross_track_width_m"),
        ("duration", "durations must match exactly"),
        ("request_identity", "request_id"),
    ),
)
def test_complete_nested_candidate_is_revalidated(
    corruption,
    message,
) -> None:
    candidate = deepcopy(_candidate())
    if corruption == "opportunity":
        object.__setattr__(
            candidate.maneuver_candidate.opportunity,
            "window_start_seconds",
            -1,
        )
    elif corruption == "acquisition":
        object.__setattr__(
            candidate.acquisition_input,
            "effective_cross_track_width_m",
            -1.0,
        )
    elif corruption == "duration":
        object.__setattr__(
            candidate.acquisition_input,
            "imaging_duration_seconds",
            22,
        )
    else:
        object.__setattr__(
            candidate.maneuver_candidate.opportunity,
            "request_id",
            MissionRequestId("f1-request"),
        )

    with pytest.raises((TypeError, ValueError), match=message):
        ScheduledObservationAcquisitionExecution(candidate, 100)


@pytest.mark.parametrize("invalid", (True, 100.0, np.int64(100), "100"))
def test_scheduled_start_requires_exact_builtin_integer(invalid) -> None:
    with pytest.raises(TypeError, match="scheduled_start_seconds"):
        ScheduledObservationAcquisitionExecution(_candidate(), invalid)


def test_negative_scheduled_start_is_rejected() -> None:
    candidate = _candidate(window_start_seconds=0)

    with pytest.raises(ValueError, match="greater than or equal to zero"):
        ScheduledObservationAcquisitionExecution(candidate, -1)


@pytest.mark.parametrize("scheduled_start_seconds", (100, 177))
def test_exact_window_start_and_latest_legal_start_are_accepted(
    scheduled_start_seconds,
) -> None:
    execution = ScheduledObservationAcquisitionExecution(
        _candidate(),
        scheduled_start_seconds,
    )

    assert execution.scheduled_start_seconds == scheduled_start_seconds


@pytest.mark.parametrize(
    ("scheduled_start_seconds", "message"),
    ((99, "must not precede"), (178, "fit inside")),
)
def test_invalid_opportunity_timing_is_rejected_by_reviewed_contract(
    scheduled_start_seconds,
    message,
) -> None:
    with pytest.raises(ValueError, match=message):
        ScheduledObservationAcquisitionExecution(
            _candidate(),
            scheduled_start_seconds,
        )


def test_window_validation_delegates_exact_candidate_and_start(monkeypatch) -> None:
    candidate = _candidate()
    calls = []

    def scheduled_observation(active_candidate, scheduled_start_seconds):
        calls.append((active_candidate, scheduled_start_seconds))

    monkeypatch.setattr(
        execution_module,
        "ScheduledObservationExecution",
        scheduled_observation,
    )

    execution = ScheduledObservationAcquisitionExecution(candidate, 100)

    assert calls == [(candidate.maneuver_candidate, 100)]
    assert execution.candidate is candidate


def test_candidate_identity_and_nested_imaging_identities_are_retained() -> None:
    candidate = _candidate()
    execution = ScheduledObservationAcquisitionExecution(candidate, 100)
    opportunity = execution.candidate.maneuver_candidate.opportunity

    assert execution.candidate is candidate
    assert type(opportunity.request_id) is ImagingRequestId
    assert type(opportunity.opportunity_id) is ObservationOpportunityId
    assert opportunity.request_id != MissionRequestId(opportunity.request_id.value)
    assert "mission_request_id" not in {
        field.name for field in fields(type(execution))
    }


def test_f1_does_not_require_current_engine_boundary_equality() -> None:
    synthetic_current_engine_time_seconds = 120

    execution = ScheduledObservationAcquisitionExecution(_candidate(), 100)

    assert execution.scheduled_start_seconds == 100
    assert (
        execution.scheduled_start_seconds
        != synthetic_current_engine_time_seconds
    )


def test_f1_admits_duration_without_engine_timestep_knowledge() -> None:
    synthetic_engine_timestep_seconds = 60
    candidate = _candidate(duration_seconds=23)

    execution = ScheduledObservationAcquisitionExecution(candidate, 100)

    assert execution.candidate.acquisition_input.imaging_duration_seconds == 23
    assert (
        execution.candidate.acquisition_input.imaging_duration_seconds
        != synthetic_engine_timestep_seconds
    )


def test_reconstruction_revalidates_and_does_not_mutate_candidate() -> None:
    candidate = _candidate()
    before = deepcopy(candidate)
    execution = ScheduledObservationAcquisitionExecution(candidate, 100)

    reconstructed = replace(execution)

    assert candidate == before
    assert execution.candidate is candidate
    assert reconstructed.candidate is candidate


def test_production_has_no_window_arithmetic_or_new_identity_type() -> None:
    source = EXECUTION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXECUTION_PATH))
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    class_names = tuple(
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    )

    assert class_names == (
        "ImagingExecutionAuthorizationStatus",
        "ScheduledObservationAcquisitionExecution",
    )
    assert not any(isinstance(node, ast.BinOp) for node in ast.walk(tree))
    assert identifiers.isdisjoint(
        {
            "window_start_seconds",
            "window_end_seconds",
            "StableId",
            "execution_id",
            "CommandId",
            "DataProductId",
            "MissionRequestId",
            "ManeuverId",
            "MissionImagingRequestBinding",
        }
    )


def test_production_has_only_context_independent_dependencies() -> None:
    source = EXECUTION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXECUTION_PATH))
    imported_modules = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    module_functions = tuple(
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    )

    assert imported_modules <= {
        "__future__",
        "dataclasses",
        "enum",
        "imaging_feasibility",
        "observation_feasibility",
    }
    assert imported_modules.isdisjoint(
        {
            "numpy",
            "engine",
            "context",
            "checkpoint",
            "state",
            "run_config",
            "configuration",
            "eps",
            "thermal",
            "degradation",
            "mission",
        }
    )
    assert module_functions == ()


def test_imaging_execution_module_has_exact_exports() -> None:
    assert execution_module.__all__ == [
        "ImagingExecutionAuthorizationStatus",
        "ScheduledObservationAcquisitionExecution",
    ]


def test_prior_non_engine_production_modules_are_unchanged() -> None:
    for relative_path in (
        "ops_sim/v5/imaging_feasibility.py",
        "ops_sim/v5/imaging_resources.py",
        "ops_sim/v5/imaging_thermal.py",
        "ops_sim/v5/observation.py",
        "ops_sim/v5/observation_feasibility.py",
        "ops_sim/v5/mission.py",
        "ops_sim/v5/ids.py",
        "ops_sim/v5/context.py",
        "ops_sim/v5/state.py",
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/run_config.py",
        "ops_sim/v5/configuration.py",
    ):
        before_slice = subprocess.run(
            [
                "git",
                "show",
                f"e948327562dbb620eda072d71c98bff9d5b6f146:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        after_slice = subprocess.run(
            [
                "git",
                "show",
                f"afb8ba20479a36ef3b89a9a63f2e2dd5223b6345:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert after_slice == before_slice


def test_d238_through_d244_and_f1_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s005 = sources.partition("### S005 ")[2].partition("### S006 ")[0]
    lower = s005.lower()
    normalized = " ".join(lower.split())

    for number in range(238, 245):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D237 ") < decisions.index("## D238 ")
    expected_headings = (
        "## D238 — F begins with context-independent scheduled acquisition "
        "identity",
        "## D239 — Scheduled acquisition reuses existing opportunity-window "
        "validation",
        "## D240 — Imaging execution identity uses existing ImagingRequestId, "
        "ObservationOpportunityId, and scheduled start; no new execution ID",
        "## D241 — MissionRequestId and ImagingRequestId remain distinct in "
        "V5.3F",
        "## D242 — Engine-step boundary equality belongs to later runtime "
        "authorization",
        "## D243 — Acquisition-duration/engine-dt equality belongs to later "
        "runtime authorization",
        "## D244 — F1 adds no physical execution, mission mutation, product "
        "state, or checkpoint state",
    )
    assert all(decisions.count(heading) == 1 for heading in expected_headings)
    assert "v5.3f1" in lower
    assert "no new physical source or value" in normalized
    assert "one existing acquisition candidate" in normalized
    assert "observation-window" in lower and "reuses" in lower
    assert "missionrequestid" in lower and "imagingrequestid" in lower
    assert "no new execution identity" in normalized
    assert "mission-request bridge" in normalized
    assert "engine" in lower and "timestep" in lower
    assert "resource-service" in lower
    assert "no new persistent state" in normalized
