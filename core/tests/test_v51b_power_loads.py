"""Focused tests for V5.1B component-wise electrical-load composition."""

import ast
from dataclasses import MISSING, FrozenInstanceError, fields
from inspect import Parameter, signature
from pathlib import Path

import pytest

from ops_sim.v5.configuration import BatteryConfig
from ops_sim.v5.eps import compute_battery_transition
from ops_sim.v5.ids import ParameterId, SubsystemConfigurationId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.power_loads import (
    PowerLoadBreakdown,
    compose_power_load,
)
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import BatteryState


ROOT = Path(__file__).resolve().parents[1]
POWER_LOADS_PATH = ROOT / "ops_sim" / "v5" / "power_loads.py"

LOAD_FIELDS = (
    "base_bus_w",
    "obc_w",
    "adcs_w",
    "payload_w",
    "communications_w",
    "thermal_control_w",
    "propulsion_w",
)


def _component_values(value: float = 0.0) -> dict[str, float]:
    return {field_name: value for field_name in LOAD_FIELDS}


def _breakdown(**changes) -> PowerLoadBreakdown:
    values = _component_values()
    values.update(changes)
    return PowerLoadBreakdown(**values)


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


def _battery_config() -> BatteryConfig:
    return BatteryConfig(
        SubsystemConfigurationId("battery-test"),
        _parameter("eps.battery.nominal-energy", "Wh", 2000.0),
        _parameter("eps.battery.charge-efficiency", "1", 0.90),
        _parameter("eps.battery.discharge-efficiency", "1", 0.90),
        _parameter("eps.battery.max-charge-input-power", "W", 1000.0),
        _parameter("eps.battery.max-discharge-output-power", "W", 1000.0),
    )


def test_power_load_breakdown_has_exact_required_structure() -> None:
    breakdown = _breakdown()

    assert tuple(field.name for field in fields(PowerLoadBreakdown)) == (
        LOAD_FIELDS
    )
    assert "total_load_w" not in {
        field.name for field in fields(PowerLoadBreakdown)
    }
    assert not hasattr(breakdown, "__dict__")
    assert isinstance(hash(breakdown), int)
    with pytest.raises(FrozenInstanceError):
        breakdown.base_bus_w = 1.0


def test_power_load_breakdown_fields_have_no_defaults() -> None:
    for field in fields(PowerLoadBreakdown):
        assert field.default is MISSING
        assert field.default_factory is MISSING

    with pytest.raises(TypeError):
        PowerLoadBreakdown()


@pytest.mark.parametrize("field_name", LOAD_FIELDS)
@pytest.mark.parametrize("value", (0, 7, 1.25))
def test_every_component_accepts_zero_and_positive_finite_reals(
    field_name,
    value,
) -> None:
    breakdown = _breakdown(**{field_name: value})

    assert getattr(breakdown, field_name) == value
    assert breakdown.total_load_w == value


@pytest.mark.parametrize("field_name", LOAD_FIELDS)
def test_every_component_rejects_bool_and_nonreal_values(field_name) -> None:
    for invalid in (True, False, "1"):
        with pytest.raises(TypeError):
            _breakdown(**{field_name: invalid})


@pytest.mark.parametrize("field_name", LOAD_FIELDS)
def test_every_component_rejects_nonfinite_values(field_name) -> None:
    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            _breakdown(**{field_name: invalid})


@pytest.mark.parametrize("field_name", LOAD_FIELDS)
def test_every_component_rejects_negative_values(field_name) -> None:
    with pytest.raises(ValueError):
        _breakdown(**{field_name: -0.001})


def test_synthetic_hand_calculation_totals_exactly_785_w() -> None:
    # Synthetic test-only component powers; these describe no real spacecraft.
    breakdown = PowerLoadBreakdown(
        base_bus_w=180,
        obc_w=60,
        adcs_w=90,
        payload_w=420,
        communications_w=0,
        thermal_control_w=35,
        propulsion_w=0,
    )

    assert breakdown.total_load_w == 785


def test_all_zero_components_produce_zero_total_load() -> None:
    assert _breakdown().total_load_w == 0.0


@pytest.mark.parametrize("field_name", LOAD_FIELDS)
def test_each_single_component_equals_the_total_when_others_are_zero(
    field_name,
) -> None:
    breakdown = _breakdown(**{field_name: 12.5})

    assert breakdown.total_load_w == 12.5


def test_total_is_unweighted_unrounded_sum_of_stored_fields() -> None:
    breakdown = PowerLoadBreakdown(
        0.125,
        1.25,
        2.375,
        3.5,
        4.625,
        5.75,
        6.875,
    )

    assert breakdown.total_load_w == pytest.approx(
        sum(getattr(breakdown, field_name) for field_name in LOAD_FIELDS)
    )


def test_compose_power_load_preserves_every_explicit_component() -> None:
    values = {
        "base_bus_w": 1,
        "obc_w": 2,
        "adcs_w": 3,
        "payload_w": 4,
        "communications_w": 5,
        "thermal_control_w": 6,
        "propulsion_w": 7,
    }
    original_values = dict(values)

    breakdown = compose_power_load(**values)

    assert type(breakdown) is PowerLoadBreakdown
    assert {
        field_name: getattr(breakdown, field_name)
        for field_name in LOAD_FIELDS
    } == values
    assert breakdown.total_load_w == 28
    assert values == original_values


@pytest.mark.parametrize("missing_field", LOAD_FIELDS)
def test_compose_power_load_requires_every_keyword(missing_field) -> None:
    values = _component_values()
    del values[missing_field]

    with pytest.raises(TypeError):
        compose_power_load(**values)


def test_compose_power_load_rejects_unknown_component_names() -> None:
    with pytest.raises(TypeError):
        compose_power_load(**_component_values(), miscellaneous_w=1.0)


@pytest.mark.parametrize("field_name", LOAD_FIELDS)
def test_compose_power_load_uses_dataclass_validation(field_name) -> None:
    values = _component_values()
    values[field_name] = -1.0

    with pytest.raises(ValueError):
        compose_power_load(**values)


def test_compose_power_load_signature_is_explicit_keyword_only() -> None:
    parameters = signature(compose_power_load).parameters

    assert tuple(parameters) == LOAD_FIELDS
    assert all(
        parameter.kind is Parameter.KEYWORD_ONLY
        and parameter.default is Parameter.empty
        for parameter in parameters.values()
    )


def test_total_load_plugs_directly_into_v51a_battery_transition() -> None:
    loads = compose_power_load(
        base_bus_w=180.0,
        obc_w=60.0,
        adcs_w=90.0,
        payload_w=420.0,
        communications_w=0.0,
        thermal_control_w=35.0,
        propulsion_w=0.0,
    )

    transition = compute_battery_transition(
        BatteryState(1000.0),
        _battery_config(),
        generation_w=185.0,
        load_w=loads.total_load_w,
        dt_seconds=300,
    )

    assert loads.total_load_w == 785.0
    assert transition.load_w == loads.total_load_w
    assert transition.discharge_output_w == 600.0
    assert transition.end_energy_wh == pytest.approx(944.4444444444445)


def test_load_is_a_timestep_independent_power_rate() -> None:
    loads = compose_power_load(
        base_bus_w=100.0,
        obc_w=20.0,
        adcs_w=30.0,
        payload_w=40.0,
        communications_w=50.0,
        thermal_control_w=10.0,
        propulsion_w=0.0,
    )
    config = _battery_config()

    transitions = tuple(
        compute_battery_transition(
            BatteryState(1000.0),
            config,
            generation_w=0.0,
            load_w=loads.total_load_w,
            dt_seconds=dt_seconds,
        )
        for dt_seconds in (60, 300, 3600)
    )

    assert loads.total_load_w == 250.0
    assert tuple(item.load_w for item in transitions) == (250.0, 250.0, 250.0)
    changes = tuple(-item.energy_change_wh for item in transitions)
    assert changes[1] == pytest.approx(5 * changes[0])
    assert changes[2] == pytest.approx(60 * changes[0])
    assert loads.total_load_w == 250.0


def test_power_load_module_is_structurally_isolated() -> None:
    tree = ast.parse(
        POWER_LOADS_PATH.read_text(encoding="utf-8"),
        filename=str(POWER_LOADS_PATH),
    )
    imports = {
        (node.level, node.module, tuple(alias.name for alias in node.names))
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imports == {
        (0, "__future__", ("annotations",)),
        (0, "dataclasses", ("dataclass",)),
        (0, "math", ("isfinite",)),
        (0, "numbers", ("Real",)),
    }
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))

    prohibited_names = {
        "OperationalMode",
        "SimulationEngine",
        "ControllerState",
        "MissionState",
        "Diagnostics",
        "DEFAULT_CONFIG",
        "BatteryState",
        "BatteryConfig",
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


def test_power_load_module_has_no_mode_table_or_mutable_registry() -> None:
    tree = ast.parse(POWER_LOADS_PATH.read_text(encoding="utf-8"))

    assert not any(isinstance(node, ast.Dict) for node in ast.walk(tree))
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

    prohibited_groupings = {
        "housekeeping_w",
        "mission_w",
        "high_load_w",
        "mode_load_w",
        "stress_load_w",
    }
    assert prohibited_groupings.isdisjoint(
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    )


def test_production_module_contains_no_concrete_load_profile() -> None:
    tree = ast.parse(POWER_LOADS_PATH.read_text(encoding="utf-8"))

    numeric_constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and type(node.value) in {int, float}
    }
    assert numeric_constants <= {0}

    constructor_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PowerLoadBreakdown"
    ]
    assert len(constructor_calls) == 1
    assert all(
        isinstance(argument, ast.Name)
        for argument in constructor_calls[0].args
    )
    assert constructor_calls[0].keywords == []


def test_power_load_module_defines_exact_exports() -> None:
    from ops_sim.v5 import power_loads

    assert power_loads.__all__ == [
        "PowerLoadBreakdown",
        "compose_power_load",
    ]

