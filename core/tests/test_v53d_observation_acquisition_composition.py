"""Sequenced observation and optical-acquisition composition for V5.3D."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from inspect import signature
from pathlib import Path
import subprocess

import pytest

import ops_sim.v5.imaging_feasibility as imaging_module
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    ADCSSlewAnchorId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
)
from ops_sim.v5.imaging_feasibility import (
    ObservationAcquisitionCandidate,
    ObservationAcquisitionEvaluationResult,
    evaluate_observation_acquisition,
)
from ops_sim.v5.observation import ObservationOpportunity, ObservationPointing
from ops_sim.v5.observation_feasibility import (
    ObservationManeuverCandidate,
    ObservationSequenceFeasibilityReason,
    ScheduledObservationExecution,
    evaluate_observation_sequence_feasibility,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
    OpticalAcquisitionResult,
    compute_optical_acquisition,
)
from ops_sim.v5.payload_config import OpticalAcquisitionConfig
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)


ROOT = Path(__file__).resolve().parents[1]
IMAGING_FEASIBILITY_PATH = ROOT / "ops_sim" / "v5" / "imaging_feasibility.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"


def _parameter(parameter_id: str, units: str, value: object) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by a focused unit test.",
        ),
    )


def _anchor(
    anchor_value: str,
    angle_deg: object,
    elapsed_seconds: object,
) -> BoresightSlewTimeAnchor:
    prefix = f"adcs.slew-envelope.{anchor_value}"
    return BoresightSlewTimeAnchor(
        ADCSSlewAnchorId(anchor_value),
        _parameter(f"{prefix}.angular-separation", "deg", angle_deg),
        _parameter(f"{prefix}.elapsed-time", "s", elapsed_seconds),
    )


def _agile_config(
    *,
    maximum_view_angle_deg: object = 35.0,
    settling_seconds: object = 5.0,
    anchors: tuple[BoresightSlewTimeAnchor, ...] | None = None,
) -> AgilePointingConfig:
    active_anchors = (
        (
            _anchor("zero", 0.0, 0.0),
            _anchor("thirty", 30.0, 20.0),
            _anchor("ninety", 90.0, 80.0),
        )
        if anchors is None
        else anchors
    )
    return AgilePointingConfig(
        _parameter(
            "adcs.pointing.maximum-view-angle-from-nadir",
            "deg",
            maximum_view_angle_deg,
        ),
        _parameter(
            "adcs.pointing.post-slew-settling-time",
            "s",
            settling_seconds,
        ),
        active_anchors,
    )


def _optical_config(
    *,
    reference_swath_m: object = 100.0,
    acquisition_power_w: object = 90.0,
    simultaneous: bool = True,
) -> OpticalAcquisitionConfig:
    return OpticalAcquisitionConfig(
        _parameter(
            "payload.optical.reference-nadir-swath-width",
            "m",
            reference_swath_m,
        ),
        _parameter(
            "payload.optical.panchromatic-reference-sample-spacing",
            "m",
            1.0,
        ),
        _parameter(
            "payload.optical.multispectral-reference-sample-spacing",
            "m",
            4.0,
        ),
        _parameter("payload.optical.multispectral-band-count", "1", 4),
        _parameter(
            "payload.optical.acquisition-bits-per-sample",
            "bit/sample",
            12,
        ),
        _parameter(
            "payload.optical.acquisition-power",
            "W",
            acquisition_power_w,
        ),
        simultaneous,
    )


def _opportunity(
    value: str,
    *,
    window_start_seconds: int = 0,
    window_end_seconds: int = 100,
    imaging_duration_seconds: int = 20,
    view_angle_deg: object = 10.0,
) -> ObservationOpportunity:
    return ObservationOpportunity(
        ObservationOpportunityId(value),
        ImagingRequestId(f"request-{value}"),
        window_start_seconds,
        window_end_seconds,
        imaging_duration_seconds,
        ObservationPointing(view_angle_deg, 0.0),
    )


def _direction(
    x: object = 0.0,
    y: object = 0.0,
    z: object = 1.0,
    *,
    frame_value: str = "test-common-frame",
) -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId(frame_value),
        x,
        y,
        z,
    )


def _maneuver_candidate(
    opportunity: ObservationOpportunity,
    direction: CommonFrameBoresightDirection | None = None,
) -> ObservationManeuverCandidate:
    return ObservationManeuverCandidate(
        opportunity,
        _direction() if direction is None else direction,
    )


def _acquisition_input(
    *,
    width_m: object = 20.0,
    length_m: object = 40.0,
    duration_seconds: int = 20,
    selection: OpticalAcquisitionChannelSelection = (
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL
    ),
) -> OpticalAcquisitionInput:
    return OpticalAcquisitionInput(
        width_m,
        length_m,
        duration_seconds,
        selection,
    )


def _next_candidate(
    *,
    opportunity: ObservationOpportunity | None = None,
    direction: CommonFrameBoresightDirection | None = None,
    acquisition_input: OpticalAcquisitionInput | None = None,
) -> ObservationAcquisitionCandidate:
    active_opportunity = (
        _opportunity(
            "next",
            window_start_seconds=100,
            window_end_seconds=300,
        )
        if opportunity is None
        else opportunity
    )
    return ObservationAcquisitionCandidate(
        _maneuver_candidate(active_opportunity, direction),
        _acquisition_input() if acquisition_input is None else acquisition_input,
    )


def _previous_execution(
    *,
    opportunity: ObservationOpportunity | None = None,
    direction: CommonFrameBoresightDirection | None = None,
    scheduled_start_seconds: int = 40,
) -> ScheduledObservationExecution:
    active_opportunity = (
        _opportunity("previous") if opportunity is None else opportunity
    )
    return ScheduledObservationExecution(
        _maneuver_candidate(active_opportunity, direction),
        scheduled_start_seconds,
    )


def _evaluate(
    *,
    agile_config: AgilePointingConfig | None = None,
    optical_config: OpticalAcquisitionConfig | None = None,
    previous_execution: ScheduledObservationExecution | None = None,
    next_candidate: ObservationAcquisitionCandidate | None = None,
) -> ObservationAcquisitionEvaluationResult:
    return evaluate_observation_acquisition(
        _agile_config() if agile_config is None else agile_config,
        _optical_config() if optical_config is None else optical_config,
        _previous_execution() if previous_execution is None else previous_execution,
        _next_candidate() if next_candidate is None else next_candidate,
    )


def test_d_records_have_exact_frozen_slotted_required_fields() -> None:
    result = _evaluate()
    candidate = _next_candidate()
    contracts = {
        ObservationAcquisitionCandidate: (
            "maneuver_candidate",
            "acquisition_input",
        ),
        ObservationAcquisitionEvaluationResult: (
            "sequence_result",
            "acquisition_result",
            "feasible",
        ),
    }

    for domain_type, instance in zip(contracts, (candidate, result)):
        assert tuple(field.name for field in fields(domain_type)) == contracts[
            domain_type
        ]
        assert domain_type.__dataclass_params__.frozen
        assert not hasattr(instance, "__dict__")
        assert all(
            field.default is MISSING and field.default_factory is MISSING
            for field in fields(domain_type)
        )
        with pytest.raises(FrozenInstanceError):
            setattr(instance, fields(domain_type)[0].name, None)


def test_candidate_retains_distinct_reviewed_inputs_for_one_attempt() -> None:
    maneuver = _maneuver_candidate(_opportunity("paired"), _direction(1, 2, 3))
    acquisition_input = _acquisition_input(width_m=22.0, length_m=44.0)
    candidate = ObservationAcquisitionCandidate(maneuver, acquisition_input)

    assert candidate.maneuver_candidate is maneuver
    assert candidate.acquisition_input is acquisition_input
    assert candidate.maneuver_candidate.opportunity.imaging_duration_seconds == 20
    assert candidate.acquisition_input.imaging_duration_seconds == 20


def test_candidate_requires_exact_nested_types() -> None:
    maneuver = _maneuver_candidate(_opportunity("types"))
    acquisition_input = _acquisition_input()
    with pytest.raises(TypeError, match="maneuver_candidate"):
        ObservationAcquisitionCandidate(object(), acquisition_input)
    with pytest.raises(TypeError, match="acquisition_input"):
        ObservationAcquisitionCandidate(maneuver, object())


def test_candidate_revalidates_both_nested_objects() -> None:
    maneuver = _maneuver_candidate(_opportunity("corrupted-maneuver"))
    object.__setattr__(maneuver.common_frame_boresight, "x", float("nan"))
    with pytest.raises(ValueError, match="x"):
        ObservationAcquisitionCandidate(maneuver, _acquisition_input())

    acquisition_input = _acquisition_input()
    object.__setattr__(acquisition_input, "effective_cross_track_width_m", 0.0)
    with pytest.raises(ValueError, match="effective_cross_track_width_m"):
        ObservationAcquisitionCandidate(
            _maneuver_candidate(_opportunity("corrupted-input")),
            acquisition_input,
        )


def test_candidate_rejects_exact_duration_mismatch() -> None:
    maneuver = _maneuver_candidate(
        _opportunity("duration-mismatch", imaging_duration_seconds=20)
    )

    with pytest.raises(ValueError, match="durations must match exactly"):
        ObservationAcquisitionCandidate(
            maneuver,
            _acquisition_input(duration_seconds=19),
        )


def test_public_function_requires_exact_argument_types() -> None:
    agile = _agile_config()
    optical = _optical_config()
    previous = _previous_execution()
    candidate = _next_candidate()
    with pytest.raises(TypeError, match="agile_pointing_config"):
        evaluate_observation_acquisition(object(), optical, previous, candidate)
    with pytest.raises(TypeError, match="optical_acquisition_config"):
        evaluate_observation_acquisition(agile, object(), previous, candidate)
    with pytest.raises(TypeError, match="previous_execution"):
        evaluate_observation_acquisition(agile, optical, object(), candidate)
    with pytest.raises(TypeError, match="next_candidate"):
        evaluate_observation_acquisition(agile, optical, previous, object())


def test_public_function_revalidates_all_active_inputs(monkeypatch) -> None:
    monkeypatch.setattr(
        imaging_module,
        "evaluate_observation_sequence_feasibility",
        lambda *args: pytest.fail("C3 must not be reached"),
    )

    agile = _agile_config()
    object.__setattr__(agile.post_slew_settling_time_seconds, "value", -1.0)
    with pytest.raises(ValueError, match="post_slew_settling_time"):
        _evaluate(agile_config=agile)

    optical = _optical_config()
    object.__setattr__(optical.acquisition_power_w, "value", 0.0)
    with pytest.raises(ValueError, match="acquisition_power_w"):
        _evaluate(optical_config=optical)

    previous = _previous_execution()
    object.__setattr__(
        previous.candidate.common_frame_boresight,
        "x",
        float("nan"),
    )
    with pytest.raises(ValueError, match="x"):
        _evaluate(previous_execution=previous)

    candidate = _next_candidate()
    object.__setattr__(
        candidate.acquisition_input,
        "effective_along_track_length_m",
        0.0,
    )
    with pytest.raises(ValueError, match="effective_along_track_length_m"):
        _evaluate(next_candidate=candidate)


def test_success_calls_c3_and_b2_once_with_exact_active_inputs(
    monkeypatch,
) -> None:
    agile = _agile_config()
    optical = _optical_config()
    previous = _previous_execution()
    candidate = _next_candidate()
    expected_sequence = evaluate_observation_sequence_feasibility(
        agile,
        previous,
        candidate.maneuver_candidate,
    )
    expected_acquisition = compute_optical_acquisition(
        optical,
        candidate.acquisition_input,
    )
    c3_calls = 0
    b2_calls = 0

    def c3(config, execution, maneuver):
        nonlocal c3_calls
        c3_calls += 1
        assert config is agile
        assert execution is previous
        assert maneuver is candidate.maneuver_candidate
        return expected_sequence

    def b2(config, acquisition_input):
        nonlocal b2_calls
        b2_calls += 1
        assert config is optical
        assert acquisition_input is candidate.acquisition_input
        return expected_acquisition

    monkeypatch.setattr(
        imaging_module,
        "evaluate_observation_sequence_feasibility",
        c3,
    )
    monkeypatch.setattr(imaging_module, "compute_optical_acquisition", b2)

    result = evaluate_observation_acquisition(
        agile,
        optical,
        previous,
        candidate,
    )

    assert c3_calls == 1
    assert b2_calls == 1
    assert result.sequence_result is expected_sequence
    assert result.acquisition_result is expected_acquisition
    assert result.feasible is True


def test_feasible_hand_case_preserves_b2_sample_grid_and_energy() -> None:
    result = _evaluate()
    acquisition = result.acquisition_result
    expected_area = 20 * 40
    expected_pan = expected_area / 1**2
    expected_ms_per_band = expected_area / 4**2
    expected_ms_total = 4 * expected_ms_per_band
    expected_total = expected_pan + expected_ms_total
    expected_bits = 12 * expected_total
    expected_bytes = expected_bits / 8
    expected_energy_wh = 90 * 20 / 3600

    assert result.feasible is True
    assert acquisition is not None
    assert acquisition.footprint_area_m2 == expected_area == 800
    assert acquisition.panchromatic_equivalent_samples == expected_pan == 800
    assert acquisition.multispectral_equivalent_samples_per_band == (
        expected_ms_per_band
    ) == 50
    assert acquisition.multispectral_equivalent_samples_total == (
        expected_ms_total
    ) == 200
    assert acquisition.total_equivalent_samples == expected_total == 1000
    assert acquisition.uncompressed_equivalent_bits == expected_bits == 12_000
    assert acquisition.uncompressed_equivalent_bytes == expected_bytes == 1_500
    assert acquisition.requested_acquisition_power_w == 90
    assert acquisition.acquisition_energy_wh == expected_energy_wh == 0.5


@pytest.mark.parametrize(
    "failure_kind,expected_reason",
    (
        (
            "previous-view",
            ObservationSequenceFeasibilityReason.PREVIOUS_VIEW_LIMIT_EXCEEDED,
        ),
        (
            "next-view",
            ObservationSequenceFeasibilityReason.NEXT_VIEW_LIMIT_EXCEEDED,
        ),
        (
            "timing",
            ObservationSequenceFeasibilityReason.INSUFFICIENT_TRANSITION_TIME,
        ),
    ),
)
def test_supported_c3_infeasibility_short_circuits_b2(
    monkeypatch,
    failure_kind,
    expected_reason,
) -> None:
    previous_opportunity = _opportunity(
        "short-previous",
        view_angle_deg=36.0 if failure_kind == "previous-view" else 10.0,
    )
    next_opportunity = _opportunity(
        "short-next",
        window_start_seconds=100,
        window_end_seconds=150 if failure_kind == "timing" else 180,
        view_angle_deg=36.0 if failure_kind == "next-view" else 10.0,
    )
    previous_direction = (
        _direction(1, 0, 0) if failure_kind == "timing" else _direction()
    )
    next_direction = (
        _direction(0, 1, 0) if failure_kind == "timing" else _direction()
    )
    previous = _previous_execution(
        opportunity=previous_opportunity,
        direction=previous_direction,
    )
    candidate = _next_candidate(
        opportunity=next_opportunity,
        direction=next_direction,
    )
    monkeypatch.setattr(
        imaging_module,
        "compute_optical_acquisition",
        lambda *args: pytest.fail("B2 must not be called"),
    )

    result = _evaluate(previous_execution=previous, next_candidate=candidate)

    assert result.sequence_result.reason is expected_reason
    assert result.sequence_result.feasible is False
    assert result.acquisition_result is None
    assert result.feasible is False


def test_c3_exception_propagates_without_calling_b2(monkeypatch) -> None:
    def c3_failure(*args):
        raise ValueError("synthetic unsupported C3 composition")

    monkeypatch.setattr(
        imaging_module,
        "evaluate_observation_sequence_feasibility",
        c3_failure,
    )
    monkeypatch.setattr(
        imaging_module,
        "compute_optical_acquisition",
        lambda *args: pytest.fail("B2 must not be called"),
    )

    with pytest.raises(ValueError, match="unsupported C3 composition"):
        _evaluate()


def test_c3_frame_mismatch_error_propagates() -> None:
    previous = _previous_execution(
        direction=_direction(frame_value="frame-a")
    )
    candidate = _next_candidate(
        direction=_direction(frame_value="frame-b")
    )

    with pytest.raises(ValueError, match="same frame_id"):
        _evaluate(previous_execution=previous, next_candidate=candidate)


def test_c2_out_of_envelope_error_propagates() -> None:
    agile = _agile_config(
        anchors=(
            _anchor("zero", 0.0, 0.0),
            _anchor("thirty", 30.0, 20.0),
        )
    )
    previous = _previous_execution(direction=_direction(1, 0, 0))
    candidate = _next_candidate(direction=_direction(0, 1, 0))

    with pytest.raises(ValueError, match="exceeds.*envelope"):
        _evaluate(
            agile_config=agile,
            previous_execution=previous,
            next_candidate=candidate,
        )


def test_b2_channel_configuration_failure_propagates() -> None:
    candidate = _next_candidate(
        acquisition_input=_acquisition_input(
            selection=OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY
        )
    )

    with pytest.raises(ValueError, match="simultaneous"):
        _evaluate(next_candidate=candidate)


def test_fractional_c3_candidate_start_is_retained_exactly() -> None:
    agile = _agile_config(
        settling_seconds=5.0,
        anchors=(
            _anchor("zero", 0.0, 0.0),
            _anchor("ninety", 90.0, 35.25),
        ),
    )
    previous = _previous_execution(direction=_direction(1, 0, 0))
    next_opportunity = _opportunity(
        "fractional-next",
        window_start_seconds=70,
        window_end_seconds=300,
    )
    candidate = _next_candidate(
        opportunity=next_opportunity,
        direction=_direction(0, 1, 0),
    )

    result = _evaluate(
        agile_config=agile,
        previous_execution=previous,
        next_candidate=candidate,
    )

    assert result.sequence_result.transition_ready_seconds == 100.25
    assert result.sequence_result.candidate_next_start_seconds == 100.25
    assert type(result.sequence_result.candidate_next_start_seconds) is float
    assert candidate.acquisition_input.imaging_duration_seconds == 20


def test_width_above_reference_swath_remains_admissible() -> None:
    optical = _optical_config(reference_swath_m=10.0)
    candidate = _next_candidate(
        acquisition_input=_acquisition_input(width_m=20.0, length_m=40.0)
    )

    result = _evaluate(optical_config=optical, next_candidate=candidate)

    assert candidate.acquisition_input.effective_cross_track_width_m == 20
    assert optical.reference_nadir_swath_width_m.value == 10
    assert result.feasible is True
    assert result.acquisition_result is not None
    assert result.acquisition_result.footprint_area_m2 == 800


def test_result_accepts_only_exact_nested_types_and_bool() -> None:
    result = _evaluate()
    with pytest.raises(TypeError, match="sequence_result"):
        ObservationAcquisitionEvaluationResult(
            object(), result.acquisition_result, True
        )
    with pytest.raises(TypeError, match="acquisition_result"):
        ObservationAcquisitionEvaluationResult(result.sequence_result, object(), True)
    with pytest.raises(TypeError, match="feasible"):
        ObservationAcquisitionEvaluationResult(
            result.sequence_result,
            result.acquisition_result,
            1,
        )


def test_result_revalidates_both_nested_results() -> None:
    result = _evaluate()
    sequence = deepcopy(result.sequence_result)
    object.__setattr__(sequence, "feasible", False)
    with pytest.raises(ValueError, match="true exactly"):
        ObservationAcquisitionEvaluationResult(
            sequence,
            result.acquisition_result,
            False,
        )

    acquisition = deepcopy(result.acquisition_result)
    assert acquisition is not None
    object.__setattr__(
        acquisition,
        "uncompressed_equivalent_bytes",
        acquisition.uncompressed_equivalent_bytes + 1,
    )
    with pytest.raises(ValueError, match="divided by eight"):
        ObservationAcquisitionEvaluationResult(
            result.sequence_result,
            acquisition,
            True,
        )


def test_result_feasible_identity_and_acquisition_presence_are_enforced() -> None:
    feasible = _evaluate()
    with pytest.raises(ValueError, match="must equal"):
        replace(feasible, feasible=False)
    with pytest.raises(ValueError, match="requires an acquisition_result"):
        replace(feasible, acquisition_result=None)

    previous = _previous_execution(direction=_direction(1, 0, 0))
    candidate = _next_candidate(
        opportunity=_opportunity(
            "infeasible-result",
            window_start_seconds=100,
            window_end_seconds=150,
        ),
        direction=_direction(0, 1, 0),
    )
    infeasible = _evaluate(
        previous_execution=previous,
        next_candidate=candidate,
    )
    assert ObservationAcquisitionEvaluationResult(
        infeasible.sequence_result,
        None,
        False,
    ) == infeasible
    with pytest.raises(ValueError, match="requires acquisition_result to be None"):
        replace(infeasible, acquisition_result=feasible.acquisition_result)


def test_evaluation_is_pure_and_mutates_no_inputs_or_results() -> None:
    agile = _agile_config()
    optical = _optical_config()
    previous = _previous_execution()
    candidate = _next_candidate()
    before = deepcopy((agile, optical, previous, candidate))

    result = evaluate_observation_acquisition(
        agile,
        optical,
        previous,
        candidate,
    )

    assert (agile, optical, previous, candidate) == before
    assert result.sequence_result.feasible is True
    assert result.acquisition_result is not None


def test_public_api_accepts_no_external_reviewed_result() -> None:
    parameters = tuple(signature(evaluate_observation_acquisition).parameters)

    assert parameters == (
        "agile_pointing_config",
        "optical_acquisition_config",
        "previous_execution",
        "next_candidate",
    )
    assert "sequence_result" not in parameters
    assert "acquisition_result" not in parameters


def test_production_has_only_allowed_pure_composition_dependencies() -> None:
    source = IMAGING_FEASIBILITY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(IMAGING_FEASIBILITY_PATH))
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

    assert imported_modules <= {
        "__future__",
        "adcs_config",
        "dataclasses",
        "observation_feasibility",
        "payload",
        "payload_config",
    }
    assert imported_modules.isdisjoint(
        {
            "numpy",
            "engine",
            "state",
            "checkpoint",
            "context",
            "mission",
            "world",
            "eps",
            "thermal",
            "degradation",
            "communications",
            "propulsion",
            "orbit",
        }
    )


def test_production_duplicates_no_c2_c3_or_b2_equation() -> None:
    source = IMAGING_FEASIBILITY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(IMAGING_FEASIBILITY_PATH))
    numeric_constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and type(node.value) in {int, float}
    }
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert all(
        isinstance(node.op, ast.BitOr)
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
    )
    assert numeric_constants == set()
    assert identifiers.isdisjoint(
        {
            "atan2",
            "hypot",
            "sin",
            "cos",
            "radians",
            "round",
            "ceil",
            "floor",
            "isclose",
            "clip",
            "clamp",
        }
    )
    assert "compute_boresight_transition" not in identifiers
    assert "evaluate_observation_sequence_feasibility" in identifiers
    assert "compute_optical_acquisition" in identifiers


def test_production_adds_no_telemetry_compression_resource_or_frame_law() -> None:
    source = IMAGING_FEASIBILITY_PATH.read_text(encoding="utf-8").lower()

    for prohibited in (
        "270 mbit/s",
        "270_000_000",
        "compression",
        "battery",
        "solar",
        "storage",
        "thermal",
        "downlink",
        "cloud",
        "weather",
        "orbit",
        "ground speed",
        "frame conversion",
        "scheduler",
        "controller",
        "engine",
    ):
        assert prohibited not in source


def test_prior_non_engine_production_modules_are_unchanged() -> None:
    for relative_path in (
        "ops_sim/v5/observation.py",
        "ops_sim/v5/observation_feasibility.py",
        "ops_sim/v5/adcs.py",
        "ops_sim/v5/adcs_config.py",
        "ops_sim/v5/payload.py",
        "ops_sim/v5/payload_config.py",
        "ops_sim/v5/configuration.py",
        "ops_sim/v5/ids.py",
        "ops_sim/v5/state.py",
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/context.py",
        "ops_sim/v5/mission.py",
        "ops_sim/v5/world.py",
    ):
        before_slice = subprocess.run(
            [
                "git",
                "show",
                f"8fe59097ccee59d5eb2d50d56327791cc294df4c:{relative_path}",
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
                f"b1a2c2b2ad86c10acf56102006fb4c73858632b2:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert after_slice == before_slice


def test_imaging_feasibility_module_has_exact_exports() -> None:
    assert imaging_module.__all__ == [
        "ObservationAcquisitionCandidate",
        "ObservationAcquisitionEvaluationResult",
        "evaluate_observation_acquisition",
    ]


def test_d208_through_d216_and_s005_d_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s005 = sources.partition("### S005 ")[2].partition("### S006 ")[0]
    lower = s005.lower()
    normalized = " ".join(lower.split())

    for number in range(208, 217):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D207 ") < decisions.index("## D208 ")
    assert "v5.3d observation-acquisition composition" in lower
    assert "no new physical source or value" in normalized
    assert "exact identity" in lower and "imaging duration" in lower
    assert "explicit caller-supplied inputs" in normalized
    assert "c3 sequence feasibility must succeed before b2" in normalized
    assert "computed internally" in lower
    assert "level-1 sample-grid proxy" in normalized
    assert "requested payload electrical power" in normalized
    assert "270 mbit/s acquisition-generation" in normalized
    assert "reference nadir swath" in normalized and "feasibility cap" in normalized
    assert "eps service" in normalized
    assert "storage capacity" in normalized
    assert "thermal conversion" in normalized
