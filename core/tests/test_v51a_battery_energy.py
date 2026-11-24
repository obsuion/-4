"""Focused tests for source-aware V5.1A battery energy physics."""

import ast
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from ops_sim.v5.configuration import BatteryConfig
from ops_sim.v5.eps import (
    BatteryTransition,
    battery_soc_fraction,
    compute_battery_transition,
)
from ops_sim.v5.ids import ParameterId, SubsystemConfigurationId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import BatteryState


ROOT = Path(__file__).resolve().parents[1]
EPS_PATH = ROOT / "ops_sim" / "v5" / "eps.py"

BATTERY_PARAMETER_CONTRACTS = (
    ("nominal_energy_wh", "eps.battery.nominal-energy", "Wh", 5000.0),
    ("charge_efficiency", "eps.battery.charge-efficiency", "1", 0.90),
    (
        "discharge_efficiency",
        "eps.battery.discharge-efficiency",
        "1",
        0.90,
    ),
    (
        "max_charge_input_power_w",
        "eps.battery.max-charge-input-power",
        "W",
        500.0,
    ),
    (
        "max_discharge_output_power_w",
        "eps.battery.max-discharge-output-power",
        "W",
        1000.0,
    ),
)


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


def _config_values() -> dict[str, object]:
    values: dict[str, object] = {
        "configuration_id": SubsystemConfigurationId("battery-test"),
    }
    values.update(
        {
            field_name: _parameter(parameter_id, units, value)
            for field_name, parameter_id, units, value in (
                BATTERY_PARAMETER_CONTRACTS
            )
        }
    )
    return values


def _config(**scalar_changes: float) -> BatteryConfig:
    values = _config_values()
    contracts = {
        field_name: (parameter_id, units)
        for field_name, parameter_id, units, _ in BATTERY_PARAMETER_CONTRACTS
    }
    for field_name, value in scalar_changes.items():
        parameter_id, units = contracts[field_name]
        values[field_name] = _parameter(parameter_id, units, value)
    return BatteryConfig(**values)


def _transition(**changes) -> BatteryTransition:
    values = {
        "start_energy_wh": 100.0,
        "end_energy_wh": 101.0,
        "generation_w": 20.0,
        "load_w": 10.0,
        "charge_input_w": 10.0,
        "discharge_output_w": 0.0,
        "curtailed_generation_w": 0.0,
        "unmet_load_w": 0.0,
        "conversion_loss_wh": 0.1,
        "dt_seconds": 360,
    }
    values.update(changes)
    return BatteryTransition(**values)


def test_battery_config_has_exact_required_parameter_contracts() -> None:
    config = _config()

    assert tuple(field.name for field in fields(BatteryConfig)) == (
        "configuration_id",
        "nominal_energy_wh",
        "charge_efficiency",
        "discharge_efficiency",
        "max_charge_input_power_w",
        "max_discharge_output_power_w",
    )
    for field_name, parameter_id, units, value in BATTERY_PARAMETER_CONTRACTS:
        parameter = getattr(config, field_name)
        assert parameter.parameter_id == ParameterId(parameter_id)
        assert parameter.units == units
        assert parameter.value == value


@pytest.mark.parametrize(
    "field_name,parameter_id,units,_value",
    BATTERY_PARAMETER_CONTRACTS[1:],
)
def test_each_new_battery_field_rejects_wrong_parameter_id(
    field_name,
    parameter_id,
    units,
    _value,
) -> None:
    values = _config_values()
    values[field_name] = _parameter("wrong.parameter", units, 0.5)

    with pytest.raises(ValueError, match="ParameterId"):
        BatteryConfig(**values)


@pytest.mark.parametrize(
    "field_name,parameter_id,_units,value",
    BATTERY_PARAMETER_CONTRACTS[1:],
)
def test_each_new_battery_field_rejects_wrong_units(
    field_name,
    parameter_id,
    _units,
    value,
) -> None:
    values = _config_values()
    values[field_name] = _parameter(parameter_id, "wrong-unit", value)

    with pytest.raises(ValueError, match="units"):
        BatteryConfig(**values)


@pytest.mark.parametrize(
    "field_name",
    ("charge_efficiency", "discharge_efficiency"),
)
@pytest.mark.parametrize("value", (0.0, -0.001, 1.001))
def test_battery_efficiencies_require_zero_exclusive_one_inclusive(
    field_name,
    value,
) -> None:
    with pytest.raises(ValueError):
        _config(**{field_name: value})


@pytest.mark.parametrize(
    "field_name",
    ("max_charge_input_power_w", "max_discharge_output_power_w"),
)
@pytest.mark.parametrize("value", (0.0, -0.001))
def test_battery_power_limits_must_be_strictly_positive(
    field_name,
    value,
) -> None:
    with pytest.raises(ValueError):
        _config(**{field_name: value})


def test_expanded_battery_config_has_no_defaults_and_is_deeply_immutable() -> None:
    config = _config()

    for field in fields(BatteryConfig):
        assert field.default is MISSING
        assert field.default_factory is MISSING
    assert not hasattr(config, "__dict__")
    assert not hasattr(config.charge_efficiency, "__dict__")
    assert not hasattr(config.charge_efficiency.provenance, "__dict__")
    with pytest.raises(FrozenInstanceError):
        config.charge_efficiency = _parameter(
            "eps.battery.charge-efficiency", "1", 1.0
        )
    with pytest.raises(FrozenInstanceError):
        config.charge_efficiency.provenance.units = "percent"


def test_battery_transition_is_frozen_slotted_and_has_exact_fields() -> None:
    transition = _transition()

    assert tuple(field.name for field in fields(BatteryTransition)) == (
        "start_energy_wh",
        "end_energy_wh",
        "generation_w",
        "load_w",
        "charge_input_w",
        "discharge_output_w",
        "curtailed_generation_w",
        "unmet_load_w",
        "conversion_loss_wh",
        "dt_seconds",
    )
    assert not hasattr(transition, "__dict__")
    with pytest.raises(FrozenInstanceError):
        transition.end_energy_wh = 102.0


TRANSITION_REAL_FIELDS = tuple(
    field.name for field in fields(BatteryTransition) if field.name != "dt_seconds"
)


@pytest.mark.parametrize("field_name", TRANSITION_REAL_FIELDS)
def test_battery_transition_rejects_invalid_real_fields(field_name) -> None:
    for invalid in (True, "1"):
        with pytest.raises(TypeError):
            _transition(**{field_name: invalid})
    for invalid in (float("nan"), float("inf"), float("-inf"), -0.001):
        with pytest.raises(ValueError):
            _transition(**{field_name: invalid})


def test_battery_transition_validates_duration_and_exclusive_flow() -> None:
    for invalid in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            _transition(dt_seconds=invalid)
    for invalid in (0, -1):
        with pytest.raises(ValueError):
            _transition(dt_seconds=invalid)
    with pytest.raises(ValueError):
        _transition(charge_input_w=1.0, discharge_output_w=1.0)


def test_battery_transition_derives_accounting_properties() -> None:
    transition = _transition(
        start_energy_wh=100.0,
        end_energy_wh=98.0,
        generation_w=20.0,
        load_w=50.0,
        charge_input_w=0.0,
        discharge_output_w=25.0,
        unmet_load_w=5.0,
    )

    assert transition.energy_change_wh == -2.0
    assert transition.net_bus_power_w == -30.0
    assert transition.served_load_w == 45.0
    assert {
        "energy_change_wh",
        "net_bus_power_w",
        "served_load_w",
    }.isdisjoint(field.name for field in fields(BatteryTransition))


@pytest.mark.parametrize(
    "energy_wh,expected_soc",
    ((0.0, 0.0), (2500.0, 0.5), (5000.0, 1.0)),
)
def test_soc_is_derived_from_energy_and_nominal_capacity(
    energy_wh,
    expected_soc,
) -> None:
    assert battery_soc_fraction(
        BatteryState(energy_wh),
        _config(),
    ) == expected_soc


def test_soc_rejects_state_above_capacity_and_exact_wrong_types() -> None:
    with pytest.raises(ValueError, match="must not exceed"):
        battery_soc_fraction(BatteryState(5000.001), _config())
    with pytest.raises(TypeError, match="state must be"):
        battery_soc_fraction(object(), _config())
    with pytest.raises(TypeError, match="config must be"):
        battery_soc_fraction(BatteryState(1.0), object())


def test_soc_revalidates_mutable_battery_state() -> None:
    state = BatteryState(1.0)
    state.energy_wh = -1.0

    with pytest.raises(ValueError):
        battery_soc_fraction(state, _config())


def test_approved_charging_hand_calculation() -> None:
    transition = compute_battery_transition(
        BatteryState(3000.0),
        _config(),
        generation_w=900.0,
        load_w=500.0,
        dt_seconds=300,
    )

    assert transition.charge_input_w == 400.0
    assert transition.discharge_output_w == 0.0
    assert transition.end_energy_wh == pytest.approx(3030.0)
    assert transition.curtailed_generation_w == 0.0
    assert transition.unmet_load_w == 0.0
    assert transition.conversion_loss_wh == pytest.approx(10.0 / 3.0)


def test_approved_discharging_hand_calculation() -> None:
    transition = compute_battery_transition(
        BatteryState(3000.0),
        _config(),
        generation_w=200.0,
        load_w=800.0,
        dt_seconds=300,
    )

    assert transition.charge_input_w == 0.0
    assert transition.discharge_output_w == 600.0
    assert transition.end_energy_wh == pytest.approx(2944.4444444444443)
    assert transition.curtailed_generation_w == 0.0
    assert transition.unmet_load_w == 0.0
    assert transition.conversion_loss_wh == pytest.approx(5.555555555555557)


def test_full_battery_explicitly_curtails_all_surplus() -> None:
    transition = compute_battery_transition(
        BatteryState(5000.0),
        _config(),
        generation_w=900.0,
        load_w=500.0,
        dt_seconds=300,
    )

    assert transition.end_energy_wh == 5000.0
    assert transition.charge_input_w == 0.0
    assert transition.curtailed_generation_w == 400.0


def test_empty_battery_explicitly_reports_all_deficit_as_unmet() -> None:
    transition = compute_battery_transition(
        BatteryState(0.0),
        _config(),
        generation_w=200.0,
        load_w=800.0,
        dt_seconds=300,
    )

    assert transition.end_energy_wh == 0.0
    assert transition.discharge_output_w == 0.0
    assert transition.unmet_load_w == 600.0


def test_charge_power_limit_curtails_unaccepted_surplus() -> None:
    transition = compute_battery_transition(
        BatteryState(1000.0),
        _config(max_charge_input_power_w=200.0),
        generation_w=1000.0,
        load_w=100.0,
        dt_seconds=300,
    )

    assert transition.charge_input_w == 200.0
    assert transition.curtailed_generation_w == 700.0


def test_discharge_power_limit_reports_remaining_deficit_as_unmet() -> None:
    transition = compute_battery_transition(
        BatteryState(3000.0),
        _config(max_discharge_output_power_w=200.0),
        generation_w=100.0,
        load_w=1000.0,
        dt_seconds=300,
    )

    assert transition.discharge_output_w == 200.0
    assert transition.unmet_load_w == 700.0


def test_capacity_limited_charge_lands_at_capacity_and_curtails() -> None:
    transition = compute_battery_transition(
        BatteryState(99.0),
        _config(
            nominal_energy_wh=100.0,
            charge_efficiency=0.80,
            max_charge_input_power_w=1000.0,
        ),
        generation_w=100.0,
        load_w=0.0,
        dt_seconds=3600,
    )

    assert transition.end_energy_wh == pytest.approx(100.0)
    assert transition.charge_input_w == pytest.approx(1.25)
    assert transition.curtailed_generation_w == pytest.approx(98.75)


def test_energy_limited_discharge_lands_at_zero_and_reports_unmet_load() -> None:
    transition = compute_battery_transition(
        BatteryState(10.0),
        _config(
            nominal_energy_wh=100.0,
            discharge_efficiency=0.80,
            max_discharge_output_power_w=1000.0,
        ),
        generation_w=0.0,
        load_w=100.0,
        dt_seconds=3600,
    )

    assert transition.end_energy_wh == pytest.approx(0.0)
    assert transition.discharge_output_w == pytest.approx(8.0)
    assert transition.unmet_load_w == pytest.approx(92.0)


@pytest.mark.parametrize(
    "generation_w,load_w",
    ((200.0, 100.0), (100.0, 200.0)),
)
def test_perfect_efficiencies_produce_zero_conversion_loss(
    generation_w,
    load_w,
) -> None:
    transition = compute_battery_transition(
        BatteryState(1000.0),
        _config(charge_efficiency=1.0, discharge_efficiency=1.0),
        generation_w=generation_w,
        load_w=load_w,
        dt_seconds=300,
    )

    assert transition.conversion_loss_wh == pytest.approx(0.0)


@pytest.mark.parametrize(
    "generation_w,load_w",
    ((500.0, 500.0), (0.0, 0.0)),
)
def test_balanced_or_zero_bus_power_leaves_battery_unchanged(
    generation_w,
    load_w,
) -> None:
    transition = compute_battery_transition(
        BatteryState(3000.0),
        _config(),
        generation_w=generation_w,
        load_w=load_w,
        dt_seconds=300,
    )

    assert transition.end_energy_wh == 3000.0
    assert transition.charge_input_w == 0.0
    assert transition.discharge_output_w == 0.0
    assert transition.curtailed_generation_w == 0.0
    assert transition.unmet_load_w == 0.0
    assert transition.conversion_loss_wh == 0.0


def test_transition_rejects_state_above_capacity_before_calculation() -> None:
    with pytest.raises(ValueError, match="must not exceed"):
        compute_battery_transition(
            BatteryState(5000.001),
            _config(),
            generation_w=0.0,
            load_w=0.0,
            dt_seconds=300,
        )


@pytest.mark.parametrize("field_name", ("generation_w", "load_w"))
def test_transition_rejects_invalid_external_power_inputs(field_name) -> None:
    arguments = {"generation_w": 1.0, "load_w": 1.0, "dt_seconds": 300}
    for invalid in (True, "1"):
        with pytest.raises(TypeError):
            compute_battery_transition(
                BatteryState(1.0),
                _config(),
                **{**arguments, field_name: invalid},
            )
    for invalid in (float("nan"), float("inf"), float("-inf"), -0.001):
        with pytest.raises(ValueError):
            compute_battery_transition(
                BatteryState(1.0),
                _config(),
                **{**arguments, field_name: invalid},
            )


def test_transition_rejects_invalid_duration_and_exact_wrong_types() -> None:
    for invalid in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            compute_battery_transition(
                BatteryState(1.0),
                _config(),
                generation_w=0.0,
                load_w=0.0,
                dt_seconds=invalid,
            )
    for invalid in (0, -1):
        with pytest.raises(ValueError):
            compute_battery_transition(
                BatteryState(1.0),
                _config(),
                generation_w=0.0,
                load_w=0.0,
                dt_seconds=invalid,
            )
    with pytest.raises(TypeError, match="state must be"):
        compute_battery_transition(
            object(), _config(), generation_w=0.0, load_w=0.0, dt_seconds=1
        )
    with pytest.raises(TypeError, match="config must be"):
        compute_battery_transition(
            BatteryState(0.0),
            object(),
            generation_w=0.0,
            load_w=0.0,
            dt_seconds=1,
        )


def test_transition_revalidates_state_and_does_not_mutate_it() -> None:
    state = BatteryState(3000.0)
    config = _config()

    transition = compute_battery_transition(
        state,
        config,
        generation_w=900.0,
        load_w=500.0,
        dt_seconds=300,
    )

    assert transition.end_energy_wh == pytest.approx(3030.0)
    assert state.energy_wh == 3000.0
    assert config == _config()

    state.energy_wh = -1.0
    with pytest.raises(ValueError):
        compute_battery_transition(
            state,
            config,
            generation_w=0.0,
            load_w=0.0,
            dt_seconds=300,
        )


@pytest.mark.parametrize(
    "start_energy_wh,generation_w,load_w,dt_seconds",
    (
        (3000.0, 900.0, 500.0, 300),
        (3000.0, 200.0, 800.0, 300),
        (5000.0, 900.0, 500.0, 300),
        (0.0, 200.0, 800.0, 300),
        (4999.0, 1000.0, 0.0, 3600),
        (1.0, 0.0, 1000.0, 3600),
        (3000.0, 500.0, 500.0, 7),
    ),
)
def test_transitions_satisfy_bus_and_stored_energy_conservation(
    start_energy_wh,
    generation_w,
    load_w,
    dt_seconds,
) -> None:
    config = _config()
    transition = compute_battery_transition(
        BatteryState(start_energy_wh),
        config,
        generation_w=generation_w,
        load_w=load_w,
        dt_seconds=dt_seconds,
    )
    dt_hours = dt_seconds / 3600.0

    generation_energy_wh = transition.generation_w * dt_hours
    battery_output_energy_wh = transition.discharge_output_w * dt_hours
    served_load_energy_wh = transition.served_load_w * dt_hours
    charge_input_energy_wh = transition.charge_input_w * dt_hours
    curtailed_energy_wh = transition.curtailed_generation_w * dt_hours
    assert generation_energy_wh + battery_output_energy_wh == pytest.approx(
        served_load_energy_wh
        + charge_input_energy_wh
        + curtailed_energy_wh
    )

    expected_change_wh = (
        config.charge_efficiency.value
        * transition.charge_input_w
        * dt_hours
        - (
            transition.discharge_output_w
            / config.discharge_efficiency.value
        )
        * dt_hours
    )
    assert transition.energy_change_wh == pytest.approx(expected_change_wh)


def _sequential_final_energy(
    *,
    start_energy_wh: float,
    config: BatteryConfig,
    generation_w: float,
    load_w: float,
) -> float:
    energy_wh = start_energy_wh
    for _ in range(12):
        transition = compute_battery_transition(
            BatteryState(energy_wh),
            config,
            generation_w=generation_w,
            load_w=load_w,
            dt_seconds=300,
        )
        energy_wh = transition.end_energy_wh
    return energy_wh


@pytest.mark.parametrize(
    "start_energy_wh,generation_w,load_w",
    ((1000.0, 200.0, 100.0), (1000.0, 0.0, 100.0)),
)
def test_one_hour_matches_twelve_five_minute_transitions(
    start_energy_wh,
    generation_w,
    load_w,
) -> None:
    config = _config(
        nominal_energy_wh=10000.0,
        max_charge_input_power_w=1000.0,
        max_discharge_output_power_w=1000.0,
    )
    one_hour = compute_battery_transition(
        BatteryState(start_energy_wh),
        config,
        generation_w=generation_w,
        load_w=load_w,
        dt_seconds=3600,
    )

    sequential = _sequential_final_energy(
        start_energy_wh=start_energy_wh,
        config=config,
        generation_w=generation_w,
        load_w=load_w,
    )

    assert sequential == pytest.approx(one_hour.end_energy_wh)


def test_eps_module_is_pure_isolated_and_has_explicit_exports() -> None:
    from ops_sim.v5 import eps

    assert eps.__all__ == [
        "BatteryTransition",
        "battery_soc_fraction",
        "compute_battery_transition",
    ]

    tree = ast.parse(
        EPS_PATH.read_text(encoding="utf-8"),
        filename=str(EPS_PATH),
    )
    import_contracts = {
        (node.level, node.module, tuple(alias.name for alias in node.names))
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert import_contracts == {
        (0, "__future__", ("annotations",)),
        (0, "dataclasses", ("dataclass",)),
        (0, "math", ("isfinite",)),
        (0, "numbers", ("Real",)),
        (1, "configuration", ("BatteryConfig",)),
        # Task 04A: explicit time value only; physical/policy isolation remains.
        (1, "integration_time", ("DyadicDuration", "checked_duration", "validate_substep_seconds")),
        (1, "state", ("BatteryState",)),
    }
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))

    prohibited_names = {
        "DEFAULT_CONFIG",
        "OperationalMode",
        "FDIRState",
        "SimulationEngine",
        "ControllerState",
        "MissionState",
        "Diagnostics",
    }
    assert not any(
        isinstance(node, ast.Name) and node.id in prohibited_names
        for node in ast.walk(tree)
    )
    assert "legacy" not in {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
