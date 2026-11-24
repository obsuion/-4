"""Focused tests for V5.1C Level-1 solar generation."""

import ast
from dataclasses import MISSING, FrozenInstanceError, fields
from inspect import Parameter, signature
from math import cos, radians
from pathlib import Path

import pytest

from ops_sim.v5.configuration import BatteryConfig, SolarArrayConfig
from ops_sim.v5.eps import compute_battery_transition
from ops_sim.v5.ids import ParameterId, SubsystemConfigurationId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.power_loads import compose_power_load
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.solar import (
    SolarGenerationResult,
    compute_solar_generation,
)
from ops_sim.v5.state import BatteryState


ROOT = Path(__file__).resolve().parents[1]
SOLAR_PATH = ROOT / "ops_sim" / "v5" / "solar.py"


def _parameter(parameter_id: str, units: str, value: float) -> ScalarParameter:
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


def _solar_config(nominal_generation_w: float = 1000.0) -> SolarArrayConfig:
    return SolarArrayConfig(
        SubsystemConfigurationId("solar-array-test"),
        _parameter(
            "eps.solar-array.nominal-generation",
            "W",
            nominal_generation_w,
        ),
    )


def _battery_config() -> BatteryConfig:
    return BatteryConfig(
        SubsystemConfigurationId("battery-test"),
        _parameter("eps.battery.nominal-energy", "Wh", 2000.0),
        _parameter("eps.battery.charge-efficiency", "1", 1.0),
        _parameter("eps.battery.discharge-efficiency", "1", 1.0),
        _parameter("eps.battery.max-charge-input-power", "W", 1000.0),
        _parameter("eps.battery.max-discharge-output-power", "W", 1000.0),
    )


def test_solar_generation_result_has_exact_derived_structure() -> None:
    result = SolarGenerationResult(1000.0, True, 0.0)

    assert tuple(field.name for field in fields(SolarGenerationResult)) == (
        "nominal_generation_w",
        "sunlit",
        "incidence_angle_deg",
    )
    assert {
        "illumination_factor",
        "incidence_factor",
        "generation_w",
    }.isdisjoint(field.name for field in fields(SolarGenerationResult))
    assert not hasattr(result, "__dict__")
    assert isinstance(hash(result), int)
    with pytest.raises(FrozenInstanceError):
        result.sunlit = False


def test_solar_generation_result_fields_have_no_defaults() -> None:
    for field in fields(SolarGenerationResult):
        assert field.default is MISSING
        assert field.default_factory is MISSING

    with pytest.raises(TypeError):
        SolarGenerationResult()


@pytest.mark.parametrize("value", (1, 1.25))
def test_nominal_generation_accepts_positive_finite_reals(value) -> None:
    result = SolarGenerationResult(value, True, 0.0)

    assert result.nominal_generation_w == value


def test_nominal_generation_rejects_nonpositive_values() -> None:
    for invalid in (0, 0.0, -0.001):
        with pytest.raises(ValueError):
            SolarGenerationResult(invalid, True, 0.0)


def test_nominal_generation_rejects_bool_nonreal_and_nonfinite() -> None:
    for invalid in (True, False, "1000"):
        with pytest.raises(TypeError):
            SolarGenerationResult(invalid, True, 0.0)
    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            SolarGenerationResult(invalid, True, 0.0)


@pytest.mark.parametrize("sunlit", (True, False))
def test_sunlit_accepts_exact_boolean_values(sunlit) -> None:
    assert SolarGenerationResult(1.0, sunlit, 0.0).sunlit is sunlit


@pytest.mark.parametrize("invalid", (0, 1, "true", None))
def test_sunlit_rejects_non_boolean_values(invalid) -> None:
    with pytest.raises(TypeError):
        SolarGenerationResult(1.0, invalid, 0.0)


@pytest.mark.parametrize("angle", (0, 30, 60, 90, 120, 180))
def test_incidence_angle_accepts_entire_required_domain_sample(angle) -> None:
    assert SolarGenerationResult(1.0, True, angle).incidence_angle_deg == angle


def test_incidence_angle_rejects_out_of_domain_values() -> None:
    for invalid in (-0.001, 180.001):
        with pytest.raises(ValueError):
            SolarGenerationResult(1.0, True, invalid)


def test_incidence_angle_rejects_bool_nonreal_and_nonfinite() -> None:
    for invalid in (True, False, "60"):
        with pytest.raises(TypeError):
            SolarGenerationResult(1.0, True, invalid)
    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            SolarGenerationResult(1.0, True, invalid)


@pytest.mark.parametrize("sunlit,expected", ((True, 1.0), (False, 0.0)))
def test_binary_illumination_factor_is_exact(sunlit, expected) -> None:
    result = SolarGenerationResult(1000.0, sunlit, 30.0)

    assert result.illumination_factor == expected


@pytest.mark.parametrize(
    "angle,expected_factor,expected_generation_w",
    (
        (0, 1.0, 1000.0),
        (30, cos(radians(30)), 866.0254037844386),
        (60, 0.5, 500.0),
        (90, 0.0, 0.0),
        (120, 0.0, 0.0),
        (180, 0.0, 0.0),
    ),
)
def test_synthetic_incidence_hand_calculations(
    angle,
    expected_factor,
    expected_generation_w,
) -> None:
    result = SolarGenerationResult(1000.0, True, angle)

    assert result.incidence_factor == pytest.approx(expected_factor)
    assert result.generation_w == pytest.approx(expected_generation_w)
    if angle >= 90:
        assert result.incidence_factor == 0.0
        assert result.generation_w == 0.0


@pytest.mark.parametrize("angle", (0, 30, 60, 90, 180))
def test_eclipse_dominates_incidence_and_returns_exact_zero(angle) -> None:
    result = SolarGenerationResult(1000.0, False, angle)

    assert result.illumination_factor == 0.0
    assert result.generation_w == 0.0


@pytest.mark.parametrize("angle", (120, 180))
def test_back_side_never_uses_absolute_cosine(angle) -> None:
    result = SolarGenerationResult(1000.0, True, angle)

    assert abs(cos(radians(angle))) > 0
    assert result.incidence_factor == 0.0
    assert result.generation_w == 0.0


def test_generation_is_bounded_nonnegative_over_admitted_angles() -> None:
    results = tuple(
        SolarGenerationResult(1000.0, True, angle)
        for angle in range(181)
    )

    assert all(0.0 <= result.generation_w <= 1000.0 for result in results)
    assert results[0].generation_w == 1000.0
    assert all(result.generation_w == 0.0 for result in results[90:])


def test_front_side_generation_decreases_with_incidence_angle() -> None:
    powers = tuple(
        SolarGenerationResult(1000.0, True, angle).generation_w
        for angle in (0, 30, 60, 90)
    )

    assert powers[0] > powers[1] > powers[2] > powers[3]


def test_compute_solar_generation_is_pure_and_uses_only_config_nominal() -> None:
    config = _solar_config(750.0)
    original_parameter = config.nominal_generation_w

    result = compute_solar_generation(
        config,
        sunlit=True,
        incidence_angle_deg=60.0,
    )

    assert type(result) is SolarGenerationResult
    assert result.nominal_generation_w == config.nominal_generation_w.value
    assert result.sunlit is True
    assert result.incidence_angle_deg == 60.0
    assert result.generation_w == pytest.approx(375.0)
    assert config.nominal_generation_w is original_parameter
    assert config == _solar_config(750.0)


def test_compute_solar_generation_requires_exact_config_type() -> None:
    with pytest.raises(TypeError, match="config must be a SolarArrayConfig"):
        compute_solar_generation(
            object(),
            sunlit=True,
            incidence_angle_deg=0.0,
        )


def test_compute_solar_generation_validates_runtime_inputs() -> None:
    with pytest.raises(TypeError):
        compute_solar_generation(
            _solar_config(),
            sunlit=1,
            incidence_angle_deg=0.0,
        )
    with pytest.raises(ValueError):
        compute_solar_generation(
            _solar_config(),
            sunlit=True,
            incidence_angle_deg=180.001,
        )


def test_compute_solar_generation_signature_has_no_timestep() -> None:
    parameters = signature(compute_solar_generation).parameters

    assert tuple(parameters) == (
        "config",
        "sunlit",
        "incidence_angle_deg",
        "nominal_generation_capability_w",
    )
    assert parameters["config"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["sunlit"].kind is Parameter.KEYWORD_ONLY
    assert parameters["incidence_angle_deg"].kind is Parameter.KEYWORD_ONLY
    assert parameters["nominal_generation_capability_w"].kind is (
        Parameter.KEYWORD_ONLY
    )
    assert all(
        parameter.default is Parameter.empty
        for parameter in tuple(parameters.values())[:-1]
    )
    assert parameters["nominal_generation_capability_w"].default is None


def test_solar_load_battery_pipeline_has_expected_energy_result() -> None:
    solar = compute_solar_generation(
        _solar_config(1000.0),
        sunlit=True,
        incidence_angle_deg=60.0,
    )
    loads = compose_power_load(
        base_bus_w=100.0,
        obc_w=50.0,
        adcs_w=50.0,
        payload_w=100.0,
        communications_w=0.0,
        thermal_control_w=0.0,
        propulsion_w=0.0,
    )

    transition = compute_battery_transition(
        BatteryState(1000.0),
        _battery_config(),
        generation_w=solar.generation_w,
        load_w=loads.total_load_w,
        dt_seconds=300,
    )

    assert solar.generation_w == pytest.approx(500.0)
    assert loads.total_load_w == 300.0
    assert transition.charge_input_w == pytest.approx(200.0)
    assert transition.end_energy_wh == pytest.approx(1016.6666666666666)


def test_solar_power_is_independent_of_battery_timestep() -> None:
    solar = compute_solar_generation(
        _solar_config(1000.0),
        sunlit=True,
        incidence_angle_deg=60.0,
    )
    loads = compose_power_load(
        base_bus_w=300.0,
        obc_w=0.0,
        adcs_w=0.0,
        payload_w=0.0,
        communications_w=0.0,
        thermal_control_w=0.0,
        propulsion_w=0.0,
    )

    transitions = tuple(
        compute_battery_transition(
            BatteryState(1000.0),
            _battery_config(),
            generation_w=solar.generation_w,
            load_w=loads.total_load_w,
            dt_seconds=dt_seconds,
        )
        for dt_seconds in (60, 300, 3600)
    )

    assert solar.generation_w == pytest.approx(500.0)
    assert tuple(item.generation_w for item in transitions) == pytest.approx(
        (500.0, 500.0, 500.0)
    )
    changes = tuple(item.energy_change_wh for item in transitions)
    assert changes[1] == pytest.approx(5 * changes[0])
    assert changes[2] == pytest.approx(60 * changes[0])
    assert solar.generation_w == pytest.approx(500.0)


def test_solar_module_is_structurally_isolated() -> None:
    tree = ast.parse(
        SOLAR_PATH.read_text(encoding="utf-8"),
        filename=str(SOLAR_PATH),
    )
    imports = {
        (node.level, node.module, tuple(alias.name for alias in node.names))
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imports == {
        (0, "__future__", ("annotations",)),
        (0, "dataclasses", ("dataclass",)),
        (0, "math", ("cos", "isfinite", "radians")),
        (0, "numbers", ("Real",)),
        (1, "configuration", ("SolarArrayConfig",)),
    }
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))

    prohibited_names = {
        "OperationalMode",
        "SimulationEngine",
        "BatteryState",
        "BatteryConfig",
        "PowerLoadBreakdown",
        "ControllerState",
        "MissionState",
        "Diagnostics",
        "DEFAULT_CONFIG",
        "dt_seconds",
        "random",
    }
    assert not any(
        isinstance(node, ast.Name) and node.id in prohibited_names
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Constant)
        and type(node.value) is int
        and node.value == 3600
        for node in ast.walk(tree)
    )


def test_solar_module_has_no_mode_table_or_hidden_physical_modifiers() -> None:
    tree = ast.parse(SOLAR_PATH.read_text(encoding="utf-8"))

    assert not any(isinstance(node, ast.Dict) for node in ast.walk(tree))
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    prohibited_identifiers = {
        "health_multiplier",
        "degradation_multiplier",
        "temperature_multiplier",
        "eclipse_fraction_per_orbit",
        "soc",
        "battery_energy",
        "mode_power",
    }
    assert identifiers.isdisjoint(prohibited_identifiers)

    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        target_names = {
            target.id for target in targets if isinstance(target, ast.Name)
        }
        if target_names == {"__all__"}:
            continue
        assert not isinstance(node.value, (ast.List, ast.Dict, ast.Set))


def test_solar_module_instantiates_no_configuration_or_power_profile() -> None:
    tree = ast.parse(SOLAR_PATH.read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.endswith("Config")
        for node in ast.walk(tree)
    )
    result_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "SolarGenerationResult"
    ]
    assert len(result_calls) == 1
    assert all(
        isinstance(argument, (ast.Name, ast.Attribute))
        for argument in result_calls[0].args
    )
    assert result_calls[0].keywords == []
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "abs"
        for node in ast.walk(tree)
    )


def test_solar_module_defines_exact_exports() -> None:
    from ops_sim.v5 import solar

    assert solar.__all__ == [
        "SolarGenerationResult",
        "compute_solar_generation",
    ]
