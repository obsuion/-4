"""Pure common-frame boresight geometry and transition timing for V5.3C2."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from math import cos, isfinite, radians, sin
from pathlib import Path
import subprocess

import numpy as np
import pytest

import ops_sim.v5.adcs as adcs_module
from ops_sim.v5.adcs import (
    BoresightAngularSeparationResult,
    BoresightTransitionResult,
    CommonFrameBoresightDirection,
    compute_boresight_angular_separation,
    compute_boresight_transition,
)
from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    ADCSSlewAnchorId,
    ParameterId,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)


ROOT = Path(__file__).resolve().parents[1]
ADCS_PATH = ROOT / "ops_sim" / "v5" / "adcs.py"
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


def _config(
    *,
    maximum_view_angle_deg: object = 5.0,
    settling_seconds: object = 5.0,
    anchors: tuple[BoresightSlewTimeAnchor, ...] | None = None,
) -> AgilePointingConfig:
    active_anchors = (
        (
            _anchor("zero", 0.0, 0.0),
            _anchor("ten", 10.0, 20.0),
            _anchor("thirty", 30.0, 50.0),
            _anchor("sixty", 60.0, 90.0),
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


def _direction(
    x: object,
    y: object,
    z: object,
    *,
    frame_value: str = "test-common-frame",
) -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId(frame_value),
        x,
        y,
        z,
    )


def _look_direction(
    view_angle_deg: float,
    *,
    azimuth_sign: int = 1,
) -> CommonFrameBoresightDirection:
    angle_rad = radians(view_angle_deg)
    return _direction(
        azimuth_sign * sin(angle_rad),
        0.0,
        cos(angle_rad),
    )


def _patched_transition(
    monkeypatch,
    angle_deg: float,
    *,
    config: AgilePointingConfig | None = None,
) -> tuple[BoresightTransitionResult, int]:
    calls = 0

    def separation(start, end):
        nonlocal calls
        calls += 1
        assert type(start) is CommonFrameBoresightDirection
        assert type(end) is CommonFrameBoresightDirection
        return BoresightAngularSeparationResult(angle_deg)

    monkeypatch.setattr(
        adcs_module,
        "compute_boresight_angular_separation",
        separation,
    )
    result = compute_boresight_transition(
        _config() if config is None else config,
        _direction(1.0, 0.0, 0.0),
        _direction(0.0, 1.0, 0.0),
    )
    return result, calls


def test_adcs_boresight_frame_id_has_canonical_stable_behavior() -> None:
    frame_id = ADCSBoresightFrameId("inertial-at-t0")

    assert frame_id.canonical == "adcs-boresight-frame:inertial-at-t0"
    assert str(frame_id) == frame_id.canonical
    assert ADCSBoresightFrameId.from_canonical(frame_id.canonical) == frame_id
    with pytest.raises(ValueError):
        ADCSBoresightFrameId.from_canonical("adcs-slew-anchor:inertial-at-t0")


def test_c2_records_have_exact_frozen_slotted_required_fields() -> None:
    zero_id = ADCSSlewAnchorId("zero")
    contracts = {
        CommonFrameBoresightDirection: ("frame_id", "x", "y", "z"),
        BoresightAngularSeparationResult: ("angular_separation_deg",),
        BoresightTransitionResult: (
            "angular_separation_deg",
            "lower_anchor_id",
            "upper_anchor_id",
            "interpolation_fraction",
            "slew_elapsed_time_seconds",
            "settling_time_seconds",
            "total_transition_time_seconds",
        ),
    }
    instances = (
        _direction(1.0, 0.0, 0.0),
        BoresightAngularSeparationResult(0.0),
        BoresightTransitionResult(
            0.0,
            zero_id,
            zero_id,
            0.0,
            0.0,
            0.0,
            0.0,
        ),
    )

    for domain_type, instance in zip(contracts, instances):
        assert tuple(field.name for field in fields(domain_type)) == (
            contracts[domain_type]
        )
        assert domain_type.__dataclass_params__.frozen
        assert not hasattr(instance, "__dict__")
        assert all(
            field.default is MISSING and field.default_factory is MISSING
            for field in fields(domain_type)
        )
        with pytest.raises(FrozenInstanceError):
            setattr(instance, fields(domain_type)[0].name, None)


def test_direction_requires_exact_frame_id_and_revalidates_it() -> None:
    with pytest.raises(TypeError, match="frame_id"):
        CommonFrameBoresightDirection(ADCSSlewAnchorId("wrong"), 1, 0, 0)

    direction = _direction(1, 0, 0, frame_value="corrupted")
    object.__setattr__(direction.frame_id, "value", "UPPERCASE")
    with pytest.raises(ValueError, match="lowercase ASCII"):
        replace(direction)


@pytest.mark.parametrize(
    ("field_name", "invalid", "error_type"),
    (
        ("x", True, TypeError),
        ("x", "1", TypeError),
        ("y", float("nan"), ValueError),
        ("z", float("inf"), ValueError),
        ("z", float("-inf"), ValueError),
    ),
)
def test_direction_rejects_invalid_components(
    field_name,
    invalid,
    error_type,
) -> None:
    values = {"x": 1.0, "y": 2.0, "z": 3.0, field_name: invalid}
    with pytest.raises(error_type):
        _direction(**values)


@pytest.mark.parametrize(
    "components",
    ((0, 0, 0), (0.0, -0.0, 0.0), (np.int64(0), 0.0, 0)),
)
def test_direction_rejects_zero_vector(components) -> None:
    with pytest.raises(ValueError, match="nonzero"):
        _direction(*components)


def test_nonunit_direction_is_admitted_and_stored_unmodified() -> None:
    x = np.float64(1000.0)
    direction = _direction(x, np.int64(2000), 3000.0)

    assert direction.x is x
    assert direction.y == 2000
    assert direction.z == 3000.0


def test_geometry_requires_exact_types_and_revalidates_inputs() -> None:
    direction = _direction(1.0, 0.0, 0.0)
    with pytest.raises(TypeError, match="start"):
        compute_boresight_angular_separation(object(), direction)
    with pytest.raises(TypeError, match="end"):
        compute_boresight_angular_separation(direction, object())

    object.__setattr__(direction, "x", float("nan"))
    with pytest.raises(ValueError, match="x"):
        compute_boresight_angular_separation(direction, _direction(0, 1, 0))


def test_geometry_rejects_different_comparison_frames() -> None:
    with pytest.raises(ValueError, match="same frame_id"):
        compute_boresight_angular_separation(
            _direction(1, 0, 0, frame_value="frame-a"),
            _direction(1, 0, 0, frame_value="frame-b"),
        )


def test_identical_direction_has_zero_angular_separation() -> None:
    result = compute_boresight_angular_separation(
        _direction(1, 0, 0),
        _direction(1, 0, 0),
    )

    assert result.angular_separation_deg == 0


def test_scaled_same_direction_has_zero_angular_separation() -> None:
    result = compute_boresight_angular_separation(
        _direction(1, 0, 0),
        _direction(500, 0, 0),
    )

    assert result.angular_separation_deg == 0


def test_orthogonal_directions_have_ninety_degree_separation() -> None:
    result = compute_boresight_angular_separation(
        _direction(1, 0, 0),
        _direction(0, 1, 0),
    )

    assert result.angular_separation_deg == 90


def test_opposite_directions_have_straight_angle_separation() -> None:
    result = compute_boresight_angular_separation(
        _direction(1, 0, 0),
        _direction(-1, 0, 0),
    )

    assert result.angular_separation_deg == 180


@pytest.mark.parametrize(
    ("view_angle_deg", "expected_separation_deg"),
    ((30.0, 60.0), (35.0, 70.0)),
)
def test_opposite_azimuth_look_geometry_has_twice_the_view_angle(
    view_angle_deg,
    expected_separation_deg,
) -> None:
    result = compute_boresight_angular_separation(
        _look_direction(view_angle_deg, azimuth_sign=1),
        _look_direction(view_angle_deg, azimuth_sign=-1),
    )

    assert result.angular_separation_deg == pytest.approx(
        expected_separation_deg
    )


def test_positive_scale_invariance_for_general_directions() -> None:
    base = compute_boresight_angular_separation(
        _direction(1.0, 2.0, 3.0),
        _direction(-2.0, 1.0, 0.5),
    )
    scaled = compute_boresight_angular_separation(
        _direction(1000.0, 2000.0, 3000.0),
        _direction(-0.5, 0.25, 0.125),
    )

    assert scaled.angular_separation_deg == pytest.approx(
        base.angular_separation_deg
    )


def test_large_finite_vectors_normalize_without_overflow() -> None:
    result = compute_boresight_angular_separation(
        _direction(1.0e308, -1.0e308, 1.0e308),
        _direction(5.0e307, -5.0e307, 5.0e307),
    )

    assert result.angular_separation_deg == 0


def test_large_dynamic_range_vector_remains_a_valid_direction() -> None:
    result = compute_boresight_angular_separation(
        _direction(1.0e308, 1.0, 0.0),
        _direction(1.0e308, 1.0, 0.0),
    )

    assert result.angular_separation_deg == 0


def test_numpy_reals_are_admitted_and_geometry_output_is_builtin() -> None:
    result = compute_boresight_angular_separation(
        _direction(np.int64(1), np.float64(0), np.float64(0)),
        _direction(np.float64(0), np.int64(1), np.float64(0)),
    )

    assert type(result.angular_separation_deg) in {int, float}
    assert isfinite(result.angular_separation_deg)
    assert result.angular_separation_deg == 90


def test_geometry_uses_atan2_without_acos_clipping_or_tolerance_repair() -> None:
    source = ADCS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ADCS_PATH))
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert "atan2" in identifiers
    assert identifiers.isdisjoint(
        {"acos", "clip", "clamp", "isclose", "round", "epsilon"}
    )


def test_separation_result_rejects_invalid_domain_values() -> None:
    for invalid, error_type in (
        (True, TypeError),
        (-0.1, ValueError),
        (180.1, ValueError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ):
        with pytest.raises(error_type):
            BoresightAngularSeparationResult(invalid)
    assert BoresightAngularSeparationResult(180).angular_separation_deg == 180


def test_zero_slew_has_zero_settling_and_total_despite_configured_settling() -> None:
    direction = _direction(1.0, 2.0, 3.0)
    result = compute_boresight_transition(_config(), direction, direction)

    assert result.angular_separation_deg == 0
    assert result.lower_anchor_id == ADCSSlewAnchorId("zero")
    assert result.upper_anchor_id == ADCSSlewAnchorId("zero")
    assert result.interpolation_fraction == 0
    assert result.slew_elapsed_time_seconds == 0
    assert result.settling_time_seconds == 0
    assert result.total_transition_time_seconds == 0


def test_exact_nonzero_anchor_uses_configured_time_and_settling_once(
    monkeypatch,
) -> None:
    result, calls = _patched_transition(monkeypatch, 10.0)

    assert calls == 1
    assert result.lower_anchor_id == ADCSSlewAnchorId("ten")
    assert result.upper_anchor_id == ADCSSlewAnchorId("ten")
    assert result.interpolation_fraction == 0
    assert result.slew_elapsed_time_seconds == 20
    assert result.settling_time_seconds == 5
    assert result.total_transition_time_seconds == 25


def test_midpoint_interpolation_matches_independent_hand_calculation(
    monkeypatch,
) -> None:
    result, calls = _patched_transition(monkeypatch, 20.0)
    expected_fraction = (20 - 10) / (30 - 10)
    expected_slew = 20 + expected_fraction * (50 - 20)

    assert calls == 1
    assert result.lower_anchor_id == ADCSSlewAnchorId("ten")
    assert result.upper_anchor_id == ADCSSlewAnchorId("thirty")
    assert result.interpolation_fraction == expected_fraction == 0.5
    assert result.slew_elapsed_time_seconds == expected_slew == 35
    assert result.settling_time_seconds == 5
    assert result.total_transition_time_seconds == expected_slew + 5 == 40


def test_exact_last_anchor_remains_in_envelope(monkeypatch) -> None:
    result, calls = _patched_transition(monkeypatch, 60.0)

    assert calls == 1
    assert result.lower_anchor_id == ADCSSlewAnchorId("sixty")
    assert result.upper_anchor_id == ADCSSlewAnchorId("sixty")
    assert result.interpolation_fraction == 0
    assert result.slew_elapsed_time_seconds == 90
    assert result.settling_time_seconds == 5
    assert result.total_transition_time_seconds == 95


def test_above_envelope_separation_is_rejected_without_extrapolation(
    monkeypatch,
) -> None:
    with pytest.raises(ValueError, match="exceeds.*envelope"):
        _patched_transition(monkeypatch, 60.0001)


def test_plateau_envelope_interpolates_constant_slew_time(monkeypatch) -> None:
    config = _config(
        anchors=(
            _anchor("zero", 0.0, 0.0),
            _anchor("ten", 10.0, 20.0),
            _anchor("twenty", 20.0, 20.0),
        )
    )
    result, calls = _patched_transition(monkeypatch, 15.0, config=config)

    assert calls == 1
    assert result.interpolation_fraction == 0.5
    assert result.slew_elapsed_time_seconds == 20
    assert result.settling_time_seconds == 5
    assert result.total_transition_time_seconds == 25


def test_maximum_view_angle_is_not_a_maneuver_separation_cap() -> None:
    config = _config(
        maximum_view_angle_deg=5.0,
        anchors=(
            _anchor("zero", 0.0, 0.0),
            _anchor("ninety", 90.0, 120.0),
        ),
    )
    result = compute_boresight_transition(
        config,
        _look_direction(35.0, azimuth_sign=1),
        _look_direction(35.0, azimuth_sign=-1),
    )

    assert result.angular_separation_deg == pytest.approx(70.0)
    assert result.angular_separation_deg > 2 * 5.0
    assert result.total_transition_time_seconds > 0


def test_transition_requires_exact_types_and_revalidates_config() -> None:
    start = _direction(1, 0, 0)
    end = _direction(0, 1, 0)
    with pytest.raises(TypeError, match="config"):
        compute_boresight_transition(object(), start, end)
    with pytest.raises(TypeError, match="start"):
        compute_boresight_transition(_config(), object(), end)
    with pytest.raises(TypeError, match="end"):
        compute_boresight_transition(_config(), start, object())

    config = _config()
    object.__setattr__(
        config.post_slew_settling_time_seconds,
        "value",
        -1.0,
    )
    with pytest.raises(ValueError, match="post_slew_settling_time"):
        compute_boresight_transition(config, start, end)


def test_numpy_config_reals_produce_builtin_transition_numerics() -> None:
    config = _config(
        maximum_view_angle_deg=np.float64(5.0),
        settling_seconds=np.int64(5),
        anchors=(
            _anchor("zero", np.int64(0), np.float64(0.0)),
            _anchor("ninety", np.float64(90.0), np.int64(120)),
        ),
    )
    result = compute_boresight_transition(
        config,
        _direction(np.int64(1), np.int64(0), np.int64(0)),
        _direction(np.int64(0), np.int64(1), np.int64(0)),
    )

    for field_name in (
        "angular_separation_deg",
        "interpolation_fraction",
        "slew_elapsed_time_seconds",
        "settling_time_seconds",
        "total_transition_time_seconds",
    ):
        value = getattr(result, field_name)
        assert type(value) in {int, float}
        assert isfinite(value)


def test_transition_result_validates_domains_ids_and_total_identity() -> None:
    result = compute_boresight_transition(
        _config(
            anchors=(
                _anchor("zero", 0.0, 0.0),
                _anchor("ninety", 90.0, 120.0),
            )
        ),
        _direction(1, 0, 0),
        _direction(0, 1, 0),
    )
    with pytest.raises(TypeError, match="lower_anchor_id"):
        replace(result, lower_anchor_id=ADCSBoresightFrameId("wrong"))
    with pytest.raises(ValueError, match="interpolation_fraction"):
        replace(result, interpolation_fraction=0.5)
    with pytest.raises(ValueError, match="total_transition_time_seconds"):
        replace(
            result,
            total_transition_time_seconds=(
                result.total_transition_time_seconds + 1
            ),
        )
    with pytest.raises(ValueError, match="slew_elapsed_time_seconds"):
        replace(result, slew_elapsed_time_seconds=-1)


def test_distinct_result_anchors_require_strict_interior_fraction() -> None:
    for fraction in (0.0, 1.0):
        with pytest.raises(ValueError, match="strictly between"):
            BoresightTransitionResult(
                20.0,
                ADCSSlewAnchorId("lower"),
                ADCSSlewAnchorId("upper"),
                fraction,
                35.0,
                5.0,
                40.0,
            )


def test_zero_result_rejects_nonzero_time_or_distinct_anchor() -> None:
    with pytest.raises(ValueError, match="zero angular separation"):
        BoresightTransitionResult(
            0.0,
            ADCSSlewAnchorId("zero"),
            ADCSSlewAnchorId("zero"),
            0.0,
            0.0,
            1.0,
            1.0,
        )


def test_compute_functions_are_pure_and_mutate_no_inputs() -> None:
    config = _config(
        anchors=(
            _anchor("zero", 0.0, 0.0),
            _anchor("ninety", 90.0, 120.0),
        )
    )
    start = _direction(1.0, 0.0, 0.0)
    end = _direction(0.0, 1.0, 0.0)
    before = deepcopy((config, start, end))

    compute_boresight_angular_separation(start, end)
    compute_boresight_transition(config, start, end)

    assert (config, start, end) == before


def test_adcs_module_has_only_pure_configuration_dependencies() -> None:
    tree = ast.parse(
        ADCS_PATH.read_text(encoding="utf-8"),
        filename=str(ADCS_PATH),
    )
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
        "ids",
        "math",
        "numbers",
    }


def test_production_has_no_opportunity_orbit_frame_conversion_dependency() -> None:
    source = ADCS_PATH.read_text(encoding="utf-8")
    lower = source.lower()

    for prohibited in (
        "observation",
        "opportunity",
        "orbit",
        "mission",
        "world",
        "engine",
        "state",
        "context",
        "checkpoint",
        "payload",
        "eps",
        "thermal",
        "degradation",
        "latitude",
        "longitude",
        "eci",
        "ecef",
        "lvlh",
    ):
        assert prohibited not in lower


def test_production_has_no_constant_rate_actuator_or_energy_model() -> None:
    source = ADCS_PATH.read_text(encoding="utf-8")
    lower = source.lower()
    tree = ast.parse(source, filename=str(ADCS_PATH))

    for prohibited in (
        "slew_rate",
        "angular_velocity",
        "angular_acceleration",
        "reaction_wheel",
        "torque",
        "momentum",
        "slew_power",
        "slew_energy",
        "quaternion",
        "ape",
        "rpe",
        "pde",
        "knowledge_error",
        "extrapolat",
    ):
        assert prohibited not in lower
    assert not any(
        isinstance(node, ast.Constant)
        and type(node.value) in {int, float}
        and node.value in {35, 60, 90}
        for node in ast.walk(tree)
    )


def test_prior_c1_and_non_engine_runtime_sources_are_unchanged() -> None:
    for relative_path in (
        "ops_sim/v5/adcs_config.py",
        "ops_sim/v5/configuration.py",
        "ops_sim/v5/observation.py",
        "ops_sim/v5/payload.py",
        "ops_sim/v5/payload_config.py",
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
                f"ab652485a9fbbedae52fdbe870176297d46a4682:{relative_path}",
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
                f"8d1f97acb1404ad1c88901d4420ac8328518524e:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert after_slice == before_slice


def test_new_frame_id_is_explicitly_exported() -> None:
    from ops_sim.v5 import ids

    assert "ADCSBoresightFrameId" in ids.__all__


def test_adcs_module_has_exact_exports() -> None:
    assert adcs_module.__all__ == [
        "BoresightAngularSeparationResult",
        "BoresightTransitionResult",
        "CommonFrameBoresightDirection",
        "compute_boresight_angular_separation",
        "compute_boresight_transition",
    ]


def test_d188_through_d197_and_c2_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s006 = sources.partition("### S006 ")[2].partition("### S007 ")[0]
    lower = s006.lower()
    normalized = " ".join(lower.split())

    for number in range(188, 198):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D187 ") < decisions.index("## D188 ")
    assert "common frame" in lower
    assert "atan2" in lower and "cross" in lower and "dot" in lower
    assert "piecewise-linear" in lower
    assert "no extrapolation" in normalized
    assert "settling" in lower
    assert "maximum view" in lower
    assert "no new physical source" in lower
    assert "quaternion" in lower and "energy" in lower
