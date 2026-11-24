"""Source-grounded pure degradation physics for V5.2D2A."""

import ast
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from inspect import Parameter, signature
from math import exp, isfinite
from pathlib import Path

import numpy as np
import pytest

from ops_sim.v5.configuration import (
    BatteryConfig,
    EPSConfig,
    SolarArrayConfig,
)
from ops_sim.v5.degradation import (
    BatteryAgeingModelConfig,
    BatteryDegradationIntervalInput,
    BatteryDegradationTransition,
    BatteryThroughputIncrement,
    SolarDegradationForcingInput,
    SolarDegradationTransition,
    compute_battery_degradation_transition,
    compute_battery_throughput_increment,
    compute_explicit_solar_degradation_transition,
)
from ops_sim.v5.eps_system import (
    EPSIntervalInputs,
    compute_eps_interval_transition,
)
from ops_sim.v5.ids import ParameterId, SubsystemConfigurationId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import (
    BatteryDegradationState,
    BatteryState,
    SolarDegradationState,
)


ROOT = Path(__file__).resolve().parents[1]
DEGRADATION_PATH = ROOT / "ops_sim" / "v5" / "degradation.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
GAS_CONSTANT_J_PER_MOL_K = 8.31446261815324
SMALLEST_POSITIVE_FLOAT = float.fromhex("0x0.0000000000001p-1022")


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


def _battery_config(
    *,
    nominal_energy_wh: object = 1000.0,
    charge_efficiency: object = 0.8,
    discharge_efficiency: object = 0.75,
) -> BatteryConfig:
    return BatteryConfig(
        SubsystemConfigurationId("d2a-battery"),
        _parameter("eps.battery.nominal-energy", "Wh", nominal_energy_wh),
        _parameter(
            "eps.battery.charge-efficiency",
            "1",
            charge_efficiency,
        ),
        _parameter(
            "eps.battery.discharge-efficiency",
            "1",
            discharge_efficiency,
        ),
        _parameter("eps.battery.max-charge-input-power", "W", 1000.0),
        _parameter(
            "eps.battery.max-discharge-output-power",
            "W",
            1000.0,
        ),
    )


def _eps_config(**battery_changes) -> EPSConfig:
    return EPSConfig(
        SubsystemConfigurationId("d2a-eps"),
        _battery_config(**battery_changes),
        SolarArrayConfig(
            SubsystemConfigurationId("d2a-solar"),
            _parameter("eps.solar-array.nominal-generation", "W", 200.0),
        ),
    )


def _ageing_config(
    *,
    reference_temperature_k: object = 300.0,
    calendar_rate: object = 0.0,
    calendar_activation_energy: object = 0.0,
    cycling_coefficient: object = 0.0,
    cycling_activation_energy: object = 0.0,
) -> BatteryAgeingModelConfig:
    return BatteryAgeingModelConfig(
        _parameter(
            "degradation.battery.reference-temperature",
            "K",
            reference_temperature_k,
        ),
        _parameter(
            "degradation.battery.calendar-damage-rate-at-reference",
            "1/s",
            calendar_rate,
        ),
        _parameter(
            "degradation.battery.calendar-activation-energy",
            "J/mol",
            calendar_activation_energy,
        ),
        _parameter(
            "degradation.battery.cycling-damage-per-normalized-"
            "throughput-at-reference",
            "1",
            cycling_coefficient,
        ),
        _parameter(
            "degradation.battery.cycling-activation-energy",
            "J/mol",
            cycling_activation_energy,
        ),
    )


def _loads(load_w: object) -> PowerLoadBreakdown:
    return PowerLoadBreakdown(load_w, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _eps_result(
    *,
    state_energy_wh: object,
    sunlit: bool,
    load_w: object,
    dt_seconds: int = 3600,
    config: EPSConfig | None = None,
):
    active_config = _eps_config() if config is None else config
    result = compute_eps_interval_transition(
        BatteryState(state_energy_wh),
        active_config,
        EPSIntervalInputs(sunlit, 0.0, _loads(load_w)),
        dt_seconds=dt_seconds,
    )
    return result, active_config.battery


def _interval(
    *,
    temperature_k: object = 300.0,
    throughput_wh: object = 0.0,
    dt_seconds: int = 100,
) -> BatteryDegradationIntervalInput:
    return BatteryDegradationIntervalInput(
        temperature_k,
        BatteryThroughputIncrement(0.0, throughput_wh, throughput_wh),
        dt_seconds,
    )


def test_public_dataclasses_are_exact_frozen_slotted_and_have_no_defaults() -> None:
    expected_fields = {
        BatteryThroughputIncrement: (
            "charge_energy_throughput_wh",
            "discharge_energy_throughput_wh",
            "total_energy_throughput_wh",
        ),
        BatteryAgeingModelConfig: (
            "reference_temperature_k",
            "calendar_damage_rate_per_second_at_reference",
            "calendar_activation_energy_j_per_mol",
            "cycling_damage_per_normalized_energy_throughput_at_reference",
            "cycling_activation_energy_j_per_mol",
        ),
        BatteryDegradationIntervalInput: (
            "battery_temperature_k",
            "throughput_increment",
            "dt_seconds",
        ),
        BatteryDegradationTransition: (
            "start_usable_capacity_retention",
            "end_usable_capacity_retention",
            "start_cumulative_energy_throughput_wh",
            "throughput_increment_wh",
            "end_cumulative_energy_throughput_wh",
            "representative_temperature_k",
            "calendar_temperature_acceleration",
            "cycling_temperature_acceleration",
            "calendar_damage",
            "cycling_damage",
            "total_damage",
            "dt_seconds",
        ),
        SolarDegradationForcingInput: ("retention_loss",),
        SolarDegradationTransition: (
            "start_generation_retention",
            "retention_loss",
            "end_generation_retention",
        ),
    }
    for class_type, expected in expected_fields.items():
        assert tuple(field.name for field in fields(class_type)) == expected
        assert all(
            field.default is MISSING and field.default_factory is MISSING
            for field in fields(class_type)
        )
        instance = {
            BatteryThroughputIncrement: BatteryThroughputIncrement(0, 0, 0),
            BatteryAgeingModelConfig: _ageing_config(),
            BatteryDegradationIntervalInput: _interval(),
            BatteryDegradationTransition: BatteryDegradationTransition(
                1.0,
                1.0,
                0.0,
                0.0,
                0.0,
                300.0,
                1.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1,
            ),
            SolarDegradationForcingInput: SolarDegradationForcingInput(0),
            SolarDegradationTransition: SolarDegradationTransition(
                1.0, 0.0, 1.0
            ),
        }[class_type]
        assert not hasattr(instance, "__dict__")
        with pytest.raises(FrozenInstanceError):
            instance.__setattr__(fields(class_type)[0].name, None)


def test_ageing_configuration_parameter_contracts_and_provenance() -> None:
    config = _ageing_config()
    expected = (
        (
            config.reference_temperature_k,
            "degradation.battery.reference-temperature",
            "K",
        ),
        (
            config.calendar_damage_rate_per_second_at_reference,
            "degradation.battery.calendar-damage-rate-at-reference",
            "1/s",
        ),
        (
            config.calendar_activation_energy_j_per_mol,
            "degradation.battery.calendar-activation-energy",
            "J/mol",
        ),
        (
            config.cycling_damage_per_normalized_energy_throughput_at_reference,
            "degradation.battery.cycling-damage-per-normalized-"
            "throughput-at-reference",
            "1",
        ),
        (
            config.cycling_activation_energy_j_per_mol,
            "degradation.battery.cycling-activation-energy",
            "J/mol",
        ),
    )
    for parameter, parameter_id, units in expected:
        assert parameter.parameter_id == ParameterId(parameter_id)
        assert parameter.units == units
        assert parameter.provenance.classification is (
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
        )
    with pytest.raises(ValueError, match="ParameterId"):
        replace(
            config,
            reference_temperature_k=_parameter("wrong", "K", 300.0),
        )
    with pytest.raises(ValueError, match="units"):
        replace(
            config,
            calendar_activation_energy_j_per_mol=_parameter(
                "degradation.battery.calendar-activation-energy",
                "K",
                0.0,
            ),
        )


@pytest.mark.parametrize(
    ("changes", "error_type"),
    (
        ({"reference_temperature_k": 0.0}, ValueError),
        ({"reference_temperature_k": -1.0}, ValueError),
        ({"calendar_rate": -1.0}, ValueError),
        ({"calendar_activation_energy": -1.0}, ValueError),
        ({"cycling_coefficient": -1.0}, ValueError),
        ({"cycling_activation_energy": -1.0}, ValueError),
        ({"calendar_rate": True}, TypeError),
        ({"cycling_coefficient": float("nan")}, ValueError),
        ({"cycling_activation_energy": float("inf")}, ValueError),
    ),
)
def test_ageing_configuration_rejects_invalid_bounds(changes, error_type) -> None:
    with pytest.raises(error_type):
        _ageing_config(**changes)


@pytest.mark.parametrize(
    ("values", "error_type"),
    (
        ((-1.0, 0.0, -1.0), ValueError),
        ((0.0, True, True), TypeError),
        ((0.0, 0.0, float("nan")), ValueError),
        ((1.0, 2.0, 4.0), ValueError),
    ),
)
def test_throughput_increment_validates_values_and_identity(
    values,
    error_type,
) -> None:
    with pytest.raises(error_type):
        BatteryThroughputIncrement(*values)


@pytest.mark.parametrize("dt_seconds", (0, -1, True, 1.0, np.int64(1)))
def test_interval_requires_exact_positive_integer_duration(dt_seconds) -> None:
    error_type = ValueError if type(dt_seconds) is int else TypeError
    with pytest.raises(error_type):
        _interval(dt_seconds=dt_seconds)
    with pytest.raises(TypeError, match="throughput_increment"):
        BatteryDegradationIntervalInput(300.0, object(), 1)


def test_lossy_charging_throughput_uses_battery_side_stored_energy() -> None:
    result, battery_config = _eps_result(
        state_energy_wh=100.0,
        sunlit=True,
        load_w=100.0,
    )
    increment = compute_battery_throughput_increment(result, battery_config)

    assert result.battery.charge_input_w == pytest.approx(100.0)
    assert result.battery.conversion_loss_wh == pytest.approx(20.0)
    independently_derived_charge_wh = 0.8 * 100.0 * 1.0
    assert increment.charge_energy_throughput_wh == pytest.approx(
        independently_derived_charge_wh
    )
    assert increment.discharge_energy_throughput_wh == 0.0
    assert increment.total_energy_throughput_wh == pytest.approx(80.0)
    assert increment.total_energy_throughput_wh != pytest.approx(100.0)


def test_lossy_discharging_throughput_uses_battery_side_extracted_energy() -> None:
    result, battery_config = _eps_result(
        state_energy_wh=500.0,
        sunlit=False,
        load_w=90.0,
    )
    increment = compute_battery_throughput_increment(result, battery_config)

    assert result.battery.discharge_output_w == pytest.approx(90.0)
    assert result.battery.conversion_loss_wh == pytest.approx(30.0)
    independently_derived_discharge_wh = 90.0 * 1.0 / 0.75
    assert increment.charge_energy_throughput_wh == 0.0
    assert increment.discharge_energy_throughput_wh == pytest.approx(
        independently_derived_discharge_wh
    )
    assert increment.total_energy_throughput_wh == pytest.approx(120.0)
    assert increment.total_energy_throughput_wh != pytest.approx(150.0)


def test_zero_battery_activity_has_exact_zero_throughput() -> None:
    result, battery_config = _eps_result(
        state_energy_wh=500.0,
        sunlit=True,
        load_w=200.0,
    )

    assert compute_battery_throughput_increment(
        result, battery_config
    ) == BatteryThroughputIncrement(0.0, 0.0, 0.0)


def test_throughput_uses_only_the_eps_embedded_interval_duration() -> None:
    result, battery_config = _eps_result(
        state_energy_wh=100.0,
        sunlit=True,
        load_w=100.0,
        dt_seconds=1800,
    )
    increment = compute_battery_throughput_increment(result, battery_config)
    parameters = signature(compute_battery_throughput_increment).parameters

    assert tuple(parameters) == ("eps_result", "battery_config")
    assert all(
        parameter.kind is Parameter.POSITIONAL_OR_KEYWORD
        for parameter in parameters.values()
    )
    assert result.battery.dt_seconds == 1800
    assert increment.charge_energy_throughput_wh == pytest.approx(40.0)


def test_calendar_only_hand_calculation() -> None:
    state = BatteryDegradationState(0.9, 10_000.0)
    transition = compute_battery_degradation_transition(
        state,
        _battery_config(),
        _ageing_config(calendar_rate=1.0e-8),
        _interval(dt_seconds=100),
    )

    assert transition.calendar_temperature_acceleration == 1.0
    assert transition.calendar_damage == pytest.approx(1.0e-6)
    assert transition.cycling_damage == 0.0
    assert transition.total_damage == pytest.approx(1.0e-6)
    assert transition.end_usable_capacity_retention == pytest.approx(
        0.9 - 1.0e-6
    )
    assert state == BatteryDegradationState(0.9, 10_000.0)


def test_cycling_only_hand_calculation() -> None:
    transition = compute_battery_degradation_transition(
        BatteryDegradationState(0.9, 10_000.0),
        _battery_config(nominal_energy_wh=1000.0),
        _ageing_config(cycling_coefficient=0.001),
        _interval(throughput_wh=100.0),
    )

    assert transition.cycling_temperature_acceleration == 1.0
    assert transition.calendar_damage == 0.0
    assert transition.cycling_damage == pytest.approx(0.001 * (100 / 1000))
    assert transition.total_damage == pytest.approx(0.0001)


def test_combined_damage_and_cumulative_throughput_are_separately_visible() -> None:
    transition = compute_battery_degradation_transition(
        BatteryDegradationState(0.9, 10_000.0),
        _battery_config(),
        _ageing_config(calendar_rate=1.0e-8, cycling_coefficient=0.001),
        _interval(throughput_wh=12.0, dt_seconds=100),
    )

    expected_calendar = 1.0e-8 * 100
    expected_cycling = 0.001 * (12 / 1000)
    assert transition.calendar_damage == pytest.approx(expected_calendar)
    assert transition.cycling_damage == pytest.approx(expected_cycling)
    assert transition.total_damage == pytest.approx(
        expected_calendar + expected_cycling
    )
    assert transition.start_cumulative_energy_throughput_wh == 10_000.0
    assert transition.throughput_increment_wh == 12.0
    assert transition.end_cumulative_energy_throughput_wh == 10_012.0


def test_arrhenius_reference_hot_and_cold_hand_cases() -> None:
    activation_energy = 50_000.0
    config = _ageing_config(
        calendar_rate=1.0e-8,
        calendar_activation_energy=activation_energy,
        cycling_coefficient=0.001,
        cycling_activation_energy=activation_energy,
    )
    state = BatteryDegradationState(0.9, 0.0)
    battery = _battery_config()

    reference = compute_battery_degradation_transition(
        state, battery, config, _interval(temperature_k=300.0)
    )
    hot = compute_battery_degradation_transition(
        state, battery, config, _interval(temperature_k=310.0)
    )
    cold = compute_battery_degradation_transition(
        state, battery, config, _interval(temperature_k=290.0)
    )
    expected_hot = exp(
        -(activation_energy / GAS_CONSTANT_J_PER_MOL_K)
        * (1 / 310.0 - 1 / 300.0)
    )
    expected_cold = exp(
        -(activation_energy / GAS_CONSTANT_J_PER_MOL_K)
        * (1 / 290.0 - 1 / 300.0)
    )

    assert reference.calendar_temperature_acceleration == 1.0
    assert reference.cycling_temperature_acceleration == 1.0
    assert hot.calendar_temperature_acceleration == pytest.approx(expected_hot)
    assert cold.calendar_temperature_acceleration == pytest.approx(
        expected_cold
    )
    assert hot.calendar_temperature_acceleration > 1.0
    assert 0 < cold.calendar_temperature_acceleration < 1.0


@pytest.mark.parametrize("temperature_k", (1.0, 300.0, 1.0e6))
def test_zero_activation_energy_has_exact_unit_acceleration(
    temperature_k,
) -> None:
    transition = compute_battery_degradation_transition(
        BatteryDegradationState(0.9, 0.0),
        _battery_config(),
        _ageing_config(calendar_rate=1.0e-8, cycling_coefficient=0.001),
        _interval(temperature_k=temperature_k, throughput_wh=1.0),
    )

    assert transition.calendar_temperature_acceleration == 1.0
    assert transition.cycling_temperature_acceleration == 1.0


@pytest.mark.parametrize(
    ("temperature", "error_type"),
    (
        (0.0, ValueError),
        (True, TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ),
)
def test_interval_temperature_rejects_invalid_values(
    temperature,
    error_type,
) -> None:
    with pytest.raises(error_type):
        _interval(temperature_k=temperature)


def test_arrhenius_overflow_is_an_intentional_value_error() -> None:
    with pytest.raises(ValueError, match="temperature acceleration"):
        compute_battery_degradation_transition(
            BatteryDegradationState(0.9, 0.0),
            _battery_config(),
            _ageing_config(
                calendar_rate=1.0e-8,
                calendar_activation_energy=1.0e308,
            ),
            _interval(temperature_k=1.0e308),
        )


def test_retention_crossing_zero_fails_without_mutation_or_clipping() -> None:
    state = BatteryDegradationState(1.0e-6, 10_000.0)
    with pytest.raises(ValueError, match="candidate retention"):
        compute_battery_degradation_transition(
            state,
            _battery_config(),
            _ageing_config(calendar_rate=0.001),
            _interval(dt_seconds=1),
        )
    assert state == BatteryDegradationState(1.0e-6, 10_000.0)


def test_transition_constructor_enforces_all_arithmetic_identities() -> None:
    valid = compute_battery_degradation_transition(
        BatteryDegradationState(0.9, 10_000.0),
        _battery_config(),
        _ageing_config(calendar_rate=1.0e-8, cycling_coefficient=0.001),
        _interval(throughput_wh=12.0),
    )
    for field_name in (
        "end_usable_capacity_retention",
        "end_cumulative_energy_throughput_wh",
        "total_damage",
    ):
        with pytest.raises(ValueError):
            replace(valid, **{field_name: getattr(valid, field_name) + 1.0e-4})


def test_finite_addition_significance_loss_is_not_rejected() -> None:
    transition = compute_battery_degradation_transition(
        BatteryDegradationState(0.9, 1.0e308),
        _battery_config(),
        _ageing_config(),
        _interval(throughput_wh=1.0),
    )

    assert transition.throughput_increment_wh == 1.0
    assert transition.end_cumulative_energy_throughput_wh == 1.0e308


def test_nonzero_damage_underflow_and_huge_duration_fail_intentionally() -> None:
    with pytest.raises(ValueError, match="nonzero product"):
        compute_battery_degradation_transition(
            BatteryDegradationState(0.9, 0.0),
            _battery_config(),
            _ageing_config(cycling_coefficient=SMALLEST_POSITIVE_FLOAT),
            _interval(throughput_wh=500.0),
        )
    with pytest.raises(ValueError, match="represented|finite"):
        compute_battery_degradation_transition(
            BatteryDegradationState(0.9, 0.0),
            _battery_config(),
            _ageing_config(calendar_rate=1.0e-8),
            _interval(dt_seconds=10**400),
        )


def test_numpy_real_interoperability_produces_finite_builtin_results() -> None:
    result, battery_config = _eps_result(
        state_energy_wh=np.float64(100.0),
        sunlit=True,
        load_w=np.float64(100.0),
        config=_eps_config(
            charge_efficiency=np.float64(0.8),
            discharge_efficiency=np.float64(0.75),
        ),
    )
    increment = compute_battery_throughput_increment(result, battery_config)
    transition = compute_battery_degradation_transition(
        BatteryDegradationState(np.float64(0.9), np.int64(10_000)),
        battery_config,
        _ageing_config(
            reference_temperature_k=np.float64(300.0),
            calendar_rate=np.float64(1.0e-8),
            cycling_coefficient=np.float64(0.001),
        ),
        BatteryDegradationIntervalInput(
            np.float64(300.0),
            increment,
            3600,
        ),
    )

    assert all(
        type(value) in {int, float} and isfinite(value)
        for value in (
            increment.charge_energy_throughput_wh,
            increment.discharge_energy_throughput_wh,
            increment.total_energy_throughput_wh,
            transition.end_usable_capacity_retention,
            transition.end_cumulative_energy_throughput_wh,
        )
    )


def test_explicit_solar_zero_and_nonzero_loss_are_pure() -> None:
    state = SolarDegradationState(0.9)
    zero = compute_explicit_solar_degradation_transition(
        state,
        SolarDegradationForcingInput(0.0),
    )
    nonzero = compute_explicit_solar_degradation_transition(
        state,
        SolarDegradationForcingInput(0.05),
    )

    assert zero == SolarDegradationTransition(0.9, 0.0, 0.9)
    assert nonzero.end_generation_retention == pytest.approx(0.85)
    assert state == SolarDegradationState(0.9)


@pytest.mark.parametrize(
    ("loss", "error_type"),
    (
        (-1.0, ValueError),
        (True, TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ),
)
def test_explicit_solar_forcing_rejects_invalid_values(loss, error_type) -> None:
    with pytest.raises(error_type):
        SolarDegradationForcingInput(loss)


@pytest.mark.parametrize("loss", (0.9, 1.0))
def test_explicit_solar_excessive_loss_fails_without_clipping(loss) -> None:
    state = SolarDegradationState(0.9)
    with pytest.raises(ValueError, match="candidate retention"):
        compute_explicit_solar_degradation_transition(
            state,
            SolarDegradationForcingInput(loss),
        )
    assert state == SolarDegradationState(0.9)


def test_production_module_is_pure_numpy_free_and_has_no_solar_time_law() -> None:
    source = DEGRADATION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DEGRADATION_PATH))
    prohibited_import_roots = {
        "numpy",
        "pandas",
        "engine",
        "context",
        "checkpoint",
        "controller",
        "thermal",
    }
    import_roots = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").lstrip(".").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    assert import_roots.isdisjoint(prohibited_import_roots)
    assert identifiers.isdisjoint(
        {
            "health",
            "damage_percent",
            "cycle_count",
            "remaining_useful_life",
            "isclose",
            "round",
            "clip",
            "clamp",
        }
    )
    assert "%/year" not in source
    assert "365" not in source
    assert "SimulationEngine" not in source
    assert "CheckpointState" not in source
    assert "SpacecraftState" not in source


def test_public_exports_are_explicit_and_narrow() -> None:
    from ops_sim.v5 import degradation

    assert degradation.__all__ == [
        "BatteryAgeingModelConfig",
        "BatteryDegradationIntervalInput",
        "BatteryDegradationTransition",
        "BatteryThroughputIncrement",
        "SolarDegradationForcingInput",
        "SolarDegradationTransition",
        "compute_battery_degradation_transition",
        "compute_battery_throughput_increment",
        "compute_explicit_solar_degradation_transition",
    ]


def test_pure_apis_require_exact_domain_types() -> None:
    eps_result, battery_config = _eps_result(
        state_energy_wh=100.0,
        sunlit=True,
        load_w=100.0,
    )
    with pytest.raises(TypeError, match="eps_result"):
        compute_battery_throughput_increment(object(), battery_config)
    with pytest.raises(TypeError, match="battery_config"):
        compute_battery_throughput_increment(eps_result, object())

    degradation_arguments = (
        BatteryDegradationState(0.9, 0.0),
        battery_config,
        _ageing_config(),
        _interval(),
    )
    for index in range(len(degradation_arguments)):
        invalid = list(degradation_arguments)
        invalid[index] = object()
        with pytest.raises(TypeError):
            compute_battery_degradation_transition(*invalid)

    with pytest.raises(TypeError, match="state"):
        compute_explicit_solar_degradation_transition(
            object(), SolarDegradationForcingInput(0.0)
        )
    with pytest.raises(TypeError, match="forcing"):
        compute_explicit_solar_degradation_transition(
            SolarDegradationState(1.0), object()
        )


def test_d2a_documentation_sources_and_decisions_are_explicit() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")

    for number in range(123, 131):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D122 ") < decisions.index("## D123 ")
    s001 = sources.partition("### S001 ")[2].partition("### S002 ")[0]
    s003 = sources.partition("### S003 ")[2].partition("### S004 ")[0]
    s004 = sources.partition("### S004 ")[2].partition("### S005 ")[0]
    s009 = sources.partition("### S009 ")[2]
    assert "830 kg" in s001 and "820 kg" in s001
    assert "228,000 km" in s001 and "220,000 km" in s001
    assert "7.25" in s001 and "7 years" in s001
    assert "1200 W" in s001 and "does not provide" in s001
    assert "LINEARIZED LEVEL-1 DAMAGE ACCUMULATION" in s003
    assert "Wh" in s003 and "Ah" in s003
    assert "reversible entropic heat" in s004
    assert "not a complete Li-ion battery heat-generation model" in s004
    assert "10.1016/j.jpowsour.2014.02.012" in s009
    assert "VES16" in s009
    assert "displacement damage" in s009.lower()
    assert "not automatically transferable" in s009
