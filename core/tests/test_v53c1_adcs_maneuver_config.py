"""Level-1 agile-ADCS boresight maneuver configuration for V5.3C1."""

import ast
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from math import nextafter
from pathlib import Path
import subprocess

import numpy as np
import pytest

from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.configuration import ADCSConfig, SpacecraftConfiguration
from ops_sim.v5.ids import (
    ADCSSlewAnchorId,
    ParameterId,
    SubsystemConfigurationId,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
ROOT = Path(__file__).resolve().parents[1]
ADCS_CONFIG_PATH = ROOT / "ops_sim" / "v5" / "adcs_config.py"
CONFIGURATION_PATH = ROOT / "ops_sim" / "v5" / "configuration.py"
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
    maximum_view_angle_deg: object = 40.0,
    settling_seconds: object = 5.0,
    anchors: object | None = None,
) -> AgilePointingConfig:
    active_anchors = (
        (
            _anchor("zero", 0.0, 0.0),
            _anchor("near", 10.0, 20.0),
            _anchor("far", 60.0, 90.0),
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


def test_adcs_slew_anchor_id_has_canonical_stable_behavior() -> None:
    anchor_id = ADCSSlewAnchorId("large-angle")

    assert anchor_id.canonical == "adcs-slew-anchor:large-angle"
    assert str(anchor_id) == anchor_id.canonical
    assert ADCSSlewAnchorId.from_canonical(anchor_id.canonical) == anchor_id
    with pytest.raises(ValueError):
        ADCSSlewAnchorId.from_canonical("parameter:large-angle")


def test_anchor_and_config_have_exact_frozen_slotted_required_fields() -> None:
    contracts = {
        BoresightSlewTimeAnchor: (
            "anchor_id",
            "angular_separation_deg",
            "slew_elapsed_time_seconds",
        ),
        AgilePointingConfig: (
            "maximum_view_angle_from_nadir_deg",
            "post_slew_settling_time_seconds",
            "slew_time_anchors",
        ),
    }
    instances = (_anchor("zero", 0.0, 0.0), _config())

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


def test_anchor_uses_dynamic_parameter_ids_units_and_retains_provenance() -> None:
    anchor = _anchor("maneuver-a", 25.0, 42.0)

    assert anchor.angular_separation_deg.parameter_id == ParameterId(
        "adcs.slew-envelope.maneuver-a.angular-separation"
    )
    assert anchor.angular_separation_deg.units == "deg"
    assert anchor.slew_elapsed_time_seconds.parameter_id == ParameterId(
        "adcs.slew-envelope.maneuver-a.elapsed-time"
    )
    assert anchor.slew_elapsed_time_seconds.units == "s"
    assert anchor.angular_separation_deg.provenance.classification is (
        ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
    )


@pytest.mark.parametrize(
    ("angle", "elapsed", "error_type"),
    (
        (-0.1, 1.0, ValueError),
        (1.0, -0.1, ValueError),
        (1.0, 0.0, ValueError),
        (True, 1.0, TypeError),
        (1.0, float("nan"), ValueError),
    ),
)
def test_anchor_rejects_invalid_angle_and_elapsed_time(
    angle,
    elapsed,
    error_type,
) -> None:
    with pytest.raises(error_type):
        _anchor("invalid", angle, elapsed)


def test_zero_anchor_and_positive_angle_time_anchor_are_admitted() -> None:
    assert _anchor("zero", 0.0, 0.0).slew_elapsed_time_seconds.value == 0
    assert _anchor("positive", 12.0, 15.0).angular_separation_deg.value == 12


def test_straight_angle_anchor_with_positive_time_is_admitted() -> None:
    anchor = _anchor("straight", 180.0, 150.0)

    assert anchor.angular_separation_deg.value == 180.0


def test_next_representable_value_above_straight_angle_is_rejected() -> None:
    above_straight = nextafter(180.0, float("inf"))

    with pytest.raises(ValueError, match="straight angle"):
        _anchor("above-straight", above_straight, 151.0)


def test_ordinary_value_above_straight_angle_is_rejected() -> None:
    with pytest.raises(ValueError, match="straight angle"):
        _anchor("impossible", 181.0, 151.0)


def test_anchor_requires_exact_id_parameter_ids_and_units() -> None:
    with pytest.raises(TypeError, match="anchor_id"):
        BoresightSlewTimeAnchor(
            ParameterId("wrong"),
            _parameter("wrong.angular-separation", "deg", 1.0),
            _parameter("wrong.elapsed-time", "s", 1.0),
        )
    anchor = _anchor("identity", 1.0, 1.0)
    with pytest.raises(ValueError, match="ParameterId"):
        replace(
            anchor,
            angular_separation_deg=_parameter("wrong", "deg", 1.0),
        )
    with pytest.raises(ValueError, match="units"):
        replace(
            anchor,
            slew_elapsed_time_seconds=_parameter(
                "adcs.slew-envelope.identity.elapsed-time", "min", 1.0
            ),
        )


def test_anchor_revalidates_corrupted_nested_id() -> None:
    anchor = _anchor("corrupted-id", 1.0, 1.0)
    object.__setattr__(anchor.anchor_id, "value", "UPPERCASE")

    with pytest.raises(ValueError, match="lowercase ASCII"):
        replace(anchor)


@pytest.mark.parametrize("maximum", (0.0, -0.1, 90.0, 91.0))
def test_maximum_view_angle_must_be_strictly_between_zero_and_ninety(
    maximum,
) -> None:
    with pytest.raises(ValueError, match="maximum_view_angle"):
        _config(maximum_view_angle_deg=maximum)


def test_settling_time_accepts_zero_and_rejects_negative() -> None:
    assert _config(settling_seconds=0.0).post_slew_settling_time_seconds.value == 0
    with pytest.raises(ValueError, match="post_slew_settling_time"):
        _config(settling_seconds=-0.1)


def test_pointing_parameters_require_exact_ids_and_units() -> None:
    config = _config()
    with pytest.raises(ValueError, match="ParameterId"):
        replace(
            config,
            maximum_view_angle_from_nadir_deg=_parameter(
                "adcs.pointing.wrong", "deg", 40.0
            ),
        )
    with pytest.raises(ValueError, match="units"):
        replace(
            config,
            post_slew_settling_time_seconds=_parameter(
                "adcs.pointing.post-slew-settling-time", "min", 5.0
            ),
        )


def test_slew_envelope_requires_exact_tuple_two_anchors_and_exact_items() -> None:
    zero = _anchor("zero", 0.0, 0.0)
    second = _anchor("second", 1.0, 1.0)
    with pytest.raises(TypeError, match="tuple"):
        _config(anchors=[zero, second])
    with pytest.raises(ValueError, match="at least two"):
        _config(anchors=(zero,))
    with pytest.raises(TypeError, match="BoresightSlewTimeAnchor"):
        _config(anchors=(zero, object()))


def test_slew_envelope_requires_unique_ids_and_strictly_increasing_angles() -> None:
    with pytest.raises(ValueError, match="unique"):
        _config(
            anchors=(
                _anchor("same", 0.0, 0.0),
                _anchor("same", 10.0, 10.0),
            )
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        _config(
            anchors=(
                _anchor("zero", 0.0, 0.0),
                _anchor("high", 10.0, 20.0),
                _anchor("low", 5.0, 30.0),
            )
        )


def test_slew_envelope_requires_nondecreasing_elapsed_times() -> None:
    with pytest.raises(ValueError, match="nondecreasing"):
        _config(
            anchors=(
                _anchor("zero", 0.0, 0.0),
                _anchor("first", 10.0, 20.0),
                _anchor("second", 20.0, 19.0),
            )
        )
    assert _config(
        anchors=(
            _anchor("zero", 0.0, 0.0),
            _anchor("first", 10.0, 20.0),
            _anchor("second", 20.0, 20.0),
        )
    ).slew_time_anchors[-1].slew_elapsed_time_seconds.value == 20


@pytest.mark.parametrize(
    "first",
    (
        lambda: _anchor("nonzero-angle", 1.0, 1.0),
        lambda: _anchor("nonzero-time", 0.0, 1.0),
    ),
)
def test_first_anchor_must_be_exact_zero_angle_and_time(first) -> None:
    with pytest.raises(ValueError, match="first.*0 deg / 0 s"):
        _config(anchors=(first(), _anchor("later", 10.0, 20.0)))


def test_envelope_need_not_cover_twice_the_maximum_view_angle() -> None:
    config = _config(
        maximum_view_angle_deg=40.0,
        anchors=(
            _anchor("zero", 0.0, 0.0),
            _anchor("last", 60.0, 90.0),
        ),
    )

    assert config.slew_time_anchors[-1].angular_separation_deg.value == 60


def test_numpy_reals_are_admitted_without_production_numpy() -> None:
    config = _config(
        maximum_view_angle_deg=np.float64(40.0),
        settling_seconds=np.int64(5),
        anchors=(
            _anchor("zero", np.int64(0), np.float64(0.0)),
            _anchor("later", np.float64(10.0), np.int64(20)),
        ),
    )

    assert config.maximum_view_angle_from_nadir_deg.value == 40.0


def test_adcs_config_owns_required_exact_agile_pointing_config() -> None:
    pointing = _config()
    adcs = ADCSConfig(SubsystemConfigurationId("adcs-c1"), pointing)

    assert tuple(field.name for field in fields(ADCSConfig)) == (
        "configuration_id",
        "agile_pointing",
    )
    assert fields(ADCSConfig)[1].default is MISSING
    assert adcs.agile_pointing is pointing
    with pytest.raises(TypeError):
        ADCSConfig(SubsystemConfigurationId("missing"))
    with pytest.raises(TypeError, match="agile_pointing"):
        ADCSConfig(SubsystemConfigurationId("wrong"), object())


def test_adcs_config_revalidates_corrupted_nested_pointing_config() -> None:
    pointing = _config()
    object.__setattr__(
        pointing.maximum_view_angle_from_nadir_deg,
        "value",
        0.0,
    )

    with pytest.raises(ValueError, match="maximum_view_angle"):
        ADCSConfig(SubsystemConfigurationId("corrupted"), pointing)


def test_spacecraft_configuration_owns_agile_pointing_transitively() -> None:
    spacecraft = build_demo_context().inputs.spacecraft_configuration

    assert type(spacecraft) is SpacecraftConfiguration
    assert type(spacecraft.adcs) is ADCSConfig
    assert type(spacecraft.adcs.agile_pointing) is AgilePointingConfig
    assert len(spacecraft.adcs.agile_pointing.slew_time_anchors) == 5


def test_c1_historical_state_and_checkpoint_schemas_are_unchanged() -> None:
    commit = "ab652485a9fbbedae52fdbe870176297d46a4682"
    state_source = subprocess.run(
        ["git", "show", f"{commit}:ops_sim/v5/state.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    checkpoint_source = subprocess.run(
        ["git", "show", f"{commit}:ops_sim/v5/checkpoint.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    state_tree = ast.parse(state_source)
    spacecraft = next(
        node
        for node in state_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SpacecraftState"
    )
    state_fields = tuple(
        node.target.id
        for node in spacecraft.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    )

    assert "CURRENT_CHECKPOINT_SCHEMA_VERSION = 3" in checkpoint_source
    assert state_fields == (
        "battery",
        "propulsion",
        "thermal",
        "degradation",
        "onboard",
    )
    assert "adcs" not in state_fields
    assert "agile_pointing" not in checkpoint_source


def test_state_checkpoint_and_prior_v53_sources_are_unchanged() -> None:
    for relative_path in (
        "ops_sim/v5/state.py",
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/observation.py",
        "ops_sim/v5/payload.py",
        "ops_sim/v5/payload_config.py",
    ):
        before_slice = subprocess.run(
            [
                "git",
                "show",
                f"200b2d54dc81c3d67933d67dfba8baf237cb5b8b:{relative_path}",
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
                f"ab652485a9fbbedae52fdbe870176297d46a4682:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert after_slice == before_slice


def test_adcs_config_has_only_configuration_dependencies() -> None:
    tree = ast.parse(
        ADCS_CONFIG_PATH.read_text(encoding="utf-8"),
        filename=str(ADCS_CONFIG_PATH),
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
        "dataclasses",
        "ids",
        "math",
        "numbers",
        "parameters",
    }


def test_production_adds_no_runtime_law_or_deferred_pointing_parameters() -> None:
    source = ADCS_CONFIG_PATH.read_text(encoding="utf-8")
    lower = source.lower()
    tree = ast.parse(source, filename=str(ADCS_CONFIG_PATH))
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    prohibited_terms = (
        "slew_rate_deg_per_s",
        "maximum_angular_rate",
        "angular_acceleration",
        "pointing_accuracy",
        "pointing_stability",
        "attitude_knowledge_error",
        "location_accuracy",
        "observationopportunity",
        "observationpointing",
        "observationcampaign",
    )

    assert not any(
        name.startswith(("compute_", "interpolate_"))
        for name in function_names
    )
    assert all(term not in lower for term in prohibited_terms)
    assert not any(
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and {
            child.value
            for child in (node.left, node.right)
            if isinstance(child, ast.Constant)
        }
        == {60, 90}
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Constant)
        and type(node.value) in {int, float}
        and node.value in {35, 60, 90}
        for node in ast.walk(tree)
    )


def test_configuration_does_not_add_observation_or_execution_dependencies() -> None:
    source = CONFIGURATION_PATH.read_text(encoding="utf-8")
    assert "observation" not in source
    assert "compute_slew" not in source
    assert "interpolate" not in source


def test_adcs_config_module_has_exact_exports() -> None:
    from ops_sim.v5 import adcs_config

    assert adcs_config.__all__ == [
        "AgilePointingConfig",
        "BoresightSlewTimeAnchor",
    ]


def test_d178_through_d187_and_c1_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s006 = sources.partition("### S006 ")[2].partition("### S007 ")[0]
    lower = s006.lower()

    for number in range(178, 188):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D177 ") < decisions.index("## D178 ")
    assert "35 degrees" in s006
    assert "60 degree" in s006 and "90 seconds" in s006
    assert "ECSS-E-ST-60-10C" in s006
    assert "APE" in s006 and "RPE" in s006 and "knowledge" in lower
    assert "stabilization" in lower
    assert "piecewise" in lower
    assert "transition-time" in lower and "database" in lower
    assert "common frame" in lower
    assert "extrapolat" in lower
