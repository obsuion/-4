"""Numeric-interoperability regressions for V5.1G EPS hardening."""

import ast
from dataclasses import fields
from math import isfinite
from numbers import Real
from pathlib import Path
import warnings

import numpy as np
import pytest

from ops_sim.v5.configuration import (
    BatteryConfig,
    EPSConfig,
    SolarArrayConfig,
)
from ops_sim.v5.eps import BatteryTransition, compute_battery_transition
from ops_sim.v5.eps_system import (
    EPSIntervalInputs,
    compute_eps_interval_transition,
)
from ops_sim.v5.eps_validation import compute_eps_conservation_report
from ops_sim.v5.ids import ParameterId, SubsystemConfigurationId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.power_loads import PowerLoadBreakdown, compose_power_load
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import BatteryState


ROOT = Path(__file__).resolve().parents[1]
EPS_PATH = ROOT / "ops_sim" / "v5" / "eps.py"
POWER_LOADS_PATH = ROOT / "ops_sim" / "v5" / "power_loads.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"


class _BrokenRatioFloat(float):
    """Admitted Real with a deliberately unusable scalar adapter."""

    def as_integer_ratio(self):
        raise AttributeError("synthetic scalar adapter failure")


class _NonIntegralIndexFloat(float):
    """Non-integral Real exposing an inapplicable integer protocol."""

    def __index__(self):
        return 1


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
    capacity_wh: object = 1000.0,
    charge_efficiency: object = 1.0,
    discharge_efficiency: object = 1.0,
    max_charge_input_power_w: object = 1000.0,
    max_discharge_output_power_w: object = 1000.0,
) -> BatteryConfig:
    return BatteryConfig(
        SubsystemConfigurationId("battery-numeric-real"),
        _parameter("eps.battery.nominal-energy", "Wh", capacity_wh),
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
        _parameter(
            "eps.battery.max-charge-input-power",
            "W",
            max_charge_input_power_w,
        ),
        _parameter(
            "eps.battery.max-discharge-output-power",
            "W",
            max_discharge_output_power_w,
        ),
    )


def _eps_config(
    *,
    capacity_wh: object = 1000.0,
    charge_efficiency: object = 1.0,
    discharge_efficiency: object = 1.0,
    max_charge_input_power_w: object = 1000.0,
    max_discharge_output_power_w: object = 1000.0,
    nominal_generation_w: object = 400.0,
) -> EPSConfig:
    return EPSConfig(
        SubsystemConfigurationId("eps-numeric-real"),
        _battery_config(
            capacity_wh=capacity_wh,
            charge_efficiency=charge_efficiency,
            discharge_efficiency=discharge_efficiency,
            max_charge_input_power_w=max_charge_input_power_w,
            max_discharge_output_power_w=max_discharge_output_power_w,
        ),
        SolarArrayConfig(
            SubsystemConfigurationId("solar-numeric-real"),
            _parameter(
                "eps.solar-array.nominal-generation",
                "W",
                nominal_generation_w,
            ),
        ),
    )


def _loads(component_value: object) -> PowerLoadBreakdown:
    return compose_power_load(
        base_bus_w=component_value,
        obc_w=component_value,
        adcs_w=component_value,
        payload_w=component_value,
        communications_w=component_value,
        thermal_control_w=component_value,
        propulsion_w=component_value,
    )


def _assert_valid_transition(
    transition: BatteryTransition,
    *,
    capacity_wh: object,
) -> None:
    assert 0 <= transition.end_energy_wh <= capacity_wh
    for value in (
        transition.start_energy_wh,
        transition.end_energy_wh,
        transition.generation_w,
        transition.load_w,
        transition.charge_input_w,
        transition.discharge_output_w,
        transition.curtailed_generation_w,
        transition.unmet_load_w,
        transition.conversion_loss_wh,
    ):
        assert isfinite(value)
        assert value >= 0


def test_numpy_int64_battery_state_is_usable_by_exact_ratio_physics() -> None:
    state = BatteryState(np.int64(100))

    transition = compute_battery_transition(
        state,
        _battery_config(),
        generation_w=300.0,
        load_w=100.0,
        dt_seconds=3600,
    )

    assert transition.start_energy_wh == 100
    assert transition.end_energy_wh == pytest.approx(300.0)
    assert state.energy_wh == np.int64(100)
    _assert_valid_transition(transition, capacity_wh=1000.0)


def test_numpy_int64_generation_executes_with_independent_expected_energy() -> None:
    transition = compute_battery_transition(
        BatteryState(100.0),
        _battery_config(),
        generation_w=np.int64(300),
        load_w=100.0,
        dt_seconds=3600,
    )

    expected_end_wh = 100.0 + (300 - 100) * 1.0
    assert transition.end_energy_wh == pytest.approx(expected_end_wh)
    assert transition.charge_input_w == 200
    assert transition.curtailed_generation_w == 0
    _assert_valid_transition(transition, capacity_wh=1000.0)


def test_numpy_int64_load_executes_with_independent_expected_energy() -> None:
    transition = compute_battery_transition(
        BatteryState(500.0),
        _battery_config(),
        generation_w=100.0,
        load_w=np.int64(300),
        dt_seconds=3600,
    )

    expected_end_wh = 500.0 - (300 - 100) * 1.0
    assert transition.end_energy_wh == pytest.approx(expected_end_wh)
    assert transition.discharge_output_w == 200
    assert transition.unmet_load_w == 0
    _assert_valid_transition(transition, capacity_wh=1000.0)


def test_numpy_integral_configuration_values_drive_valid_transition() -> None:
    capacity_wh = np.int64(1000)
    max_charge_input_power_w = np.int64(150)
    config = _battery_config(
        capacity_wh=capacity_wh,
        max_charge_input_power_w=max_charge_input_power_w,
    )

    transition = compute_battery_transition(
        BatteryState(100.0),
        config,
        generation_w=500.0,
        load_w=0.0,
        dt_seconds=3600,
    )

    assert config.nominal_energy_wh.value is capacity_wh
    assert config.max_charge_input_power_w.value is max_charge_input_power_w
    assert transition.charge_input_w == 150
    assert transition.end_energy_wh == pytest.approx(250.0)
    assert transition.curtailed_generation_w == pytest.approx(500 - 150)
    _assert_valid_transition(transition, capacity_wh=capacity_wh)


def test_numpy_float64_efficiency_preserves_loss_accounting() -> None:
    config = _battery_config(charge_efficiency=np.float64(0.8))

    transition = compute_battery_transition(
        BatteryState(100.0),
        config,
        generation_w=200.0,
        load_w=100.0,
        dt_seconds=3600,
    )

    assert transition.end_energy_wh == pytest.approx(180.0)
    assert transition.charge_input_w == pytest.approx(100.0)
    assert transition.conversion_loss_wh == pytest.approx(20.0)
    _assert_valid_transition(transition, capacity_wh=1000.0)


def test_numpy_int64_efficiency_uses_integral_ratio_path() -> None:
    efficiency = np.int64(1)
    config = _battery_config(charge_efficiency=efficiency)

    transition = compute_battery_transition(
        BatteryState(100.0),
        config,
        generation_w=300.0,
        load_w=100.0,
        dt_seconds=3600,
    )

    assert config.charge_efficiency.value is efficiency
    assert transition.charge_input_w == 200.0
    assert transition.end_energy_wh == pytest.approx(300.0)
    assert transition.conversion_loss_wh == 0.0
    _assert_valid_transition(transition, capacity_wh=1000.0)


def test_real_with_broken_ratio_adapter_has_only_a_public_outcome() -> None:
    efficiency = _BrokenRatioFloat(0.8)
    assert isinstance(efficiency, Real)
    with pytest.raises(AttributeError, match="scalar adapter"):
        efficiency.as_integer_ratio()

    try:
        transition = compute_battery_transition(
            BatteryState(100.0),
            _battery_config(charge_efficiency=efficiency),
            generation_w=300.0,
            load_w=100.0,
            dt_seconds=3600,
        )
    except (TypeError, ValueError) as error:
        assert type(error) in {TypeError, ValueError}
    else:
        assert transition.end_energy_wh == pytest.approx(260.0)
        assert transition.conversion_loss_wh == pytest.approx(40.0)
        _assert_valid_transition(transition, capacity_wh=1000.0)


def test_bool_remains_an_intentional_public_type_error() -> None:
    with pytest.raises(TypeError, match="generation_w") as captured:
        compute_battery_transition(
            BatteryState(100.0),
            _battery_config(),
            generation_w=True,
            load_w=100.0,
            dt_seconds=3600,
        )

    assert type(captured.value) is TypeError


def test_nonintegral_real_with_index_protocol_preserves_its_value() -> None:
    value = _NonIntegralIndexFloat(1.5)
    transition = compute_battery_transition(
        BatteryState(100.0),
        _battery_config(),
        generation_w=value,
        load_w=0.0,
        dt_seconds=3600,
    )
    breakdown = PowerLoadBreakdown(value, 0, 0, 0, 0, 0, 0)

    assert transition.charge_input_w == pytest.approx(1.5)
    assert transition.end_energy_wh == pytest.approx(101.5)
    assert breakdown.total_load_w == pytest.approx(1.5)


@pytest.mark.parametrize(
    "scalar_type",
    (int, float, np.int32, np.int64, np.float32, np.float64),
    ids=(
        "built-in-int",
        "built-in-float",
        "numpy-int32",
        "numpy-int64",
        "numpy-float32",
        "numpy-float64",
    ),
)
def test_generation_numeric_type_matrix_has_only_public_outcomes(
    scalar_type,
) -> None:
    generation_w = scalar_type(300)

    if not isinstance(generation_w, Real):
        with pytest.raises(TypeError, match="generation_w"):
            compute_battery_transition(
                BatteryState(100.0),
                _battery_config(),
                generation_w=generation_w,
                load_w=100.0,
                dt_seconds=3600,
            )
        return

    transition = compute_battery_transition(
        BatteryState(100.0),
        _battery_config(),
        generation_w=generation_w,
        load_w=100.0,
        dt_seconds=3600,
    )
    assert transition.end_energy_wh == pytest.approx(300.0)
    _assert_valid_transition(transition, capacity_wh=1000.0)


@pytest.mark.parametrize(
    ("invalid_value", "field_name"),
    (
        (np.float64(float("nan")), "generation_w"),
        (np.float64(float("inf")), "load_w"),
        (np.int64(-1), "generation_w"),
    ),
)
def test_invalid_numpy_reals_raise_intentional_value_error(
    invalid_value,
    field_name,
) -> None:
    arguments = {"generation_w": 1.0, "load_w": 1.0}
    arguments[field_name] = invalid_value

    with pytest.raises(ValueError) as captured:
        compute_battery_transition(
            BatteryState(100.0),
            _battery_config(),
            **arguments,
            dt_seconds=1,
        )

    assert type(captured.value) is ValueError


def test_seven_large_numpy_integrals_sum_exactly_without_warning_or_wrap() -> None:
    component = np.int64(2**62)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        breakdown = PowerLoadBreakdown(*((component,) * 7))
        total_load_w = breakdown.total_load_w

    assert total_load_w == 7 * 2**62
    assert total_load_w == 32281802128991715328
    assert total_load_w > 0
    assert type(total_load_w) is int
    assert all(
        getattr(breakdown, field.name) is component
        for field in fields(PowerLoadBreakdown)
    )


def test_huge_integral_load_preserves_exact_service_accounting() -> None:
    component = np.int64(2**62)
    loads = PowerLoadBreakdown(*((component,) * 7))
    result = compute_eps_interval_transition(
        BatteryState(1000.0),
        _eps_config(),
        EPSIntervalInputs(False, 0.0, loads),
        dt_seconds=3600,
    )
    report = compute_eps_conservation_report(result)

    assert result.battery.discharge_output_w == 1000
    assert result.battery.unmet_load_w == 7 * 2**62 - 1000
    assert type(result.battery.unmet_load_w) is int
    assert result.battery.served_load_w == 1000
    assert report.is_within_tolerance(
        0.0,
        absolute_power_tolerance_w=0.0,
    )


def test_float_aggregate_overflow_remains_an_intentional_value_error() -> None:
    with pytest.raises(ValueError, match="total_load_w must be finite"):
        PowerLoadBreakdown(1.0e308, 1.0e308, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_ordinary_integral_and_float_load_totals_remain_unweighted() -> None:
    integral = PowerLoadBreakdown(1, 2, 3, 4, 5, 6, 7)
    floating = PowerLoadBreakdown(0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5)

    assert integral.total_load_w == 28
    assert type(integral.total_load_w) is int
    assert floating.total_load_w == pytest.approx(24.5)


def test_numpy_load_breakdown_feeds_battery_without_dtype_wrap() -> None:
    loads = _loads(np.int64(10))

    transition = compute_battery_transition(
        BatteryState(np.int64(500)),
        _battery_config(),
        generation_w=0,
        load_w=loads.total_load_w,
        dt_seconds=3600,
    )

    assert loads.total_load_w == 70
    assert transition.end_energy_wh == pytest.approx(430.0)
    assert transition.discharge_output_w == 70
    assert transition.unmet_load_w == 0
    _assert_valid_transition(transition, capacity_wh=1000.0)


def test_numpy_backed_composite_eps_pipeline_and_conservation() -> None:
    config = _eps_config(
        capacity_wh=np.int64(1000),
        charge_efficiency=np.float64(0.8),
        nominal_generation_w=np.int64(400),
    )
    loads = _loads(np.int64(20))

    result = compute_eps_interval_transition(
        BatteryState(np.int64(200)),
        config,
        EPSIntervalInputs(True, np.float64(0.0), loads),
        dt_seconds=3600,
    )
    report = compute_eps_conservation_report(result)

    assert result.solar.generation_w == pytest.approx(400.0)
    assert result.loads.total_load_w == 140
    assert result.battery.charge_input_w == pytest.approx(260.0)
    assert result.battery.end_energy_wh == pytest.approx(408.0)
    assert result.battery.conversion_loss_wh == pytest.approx(52.0)
    _assert_valid_transition(result.battery, capacity_wh=np.int64(1000))

    assert report.generation_energy_wh == pytest.approx(400.0)
    assert report.requested_load_energy_wh == pytest.approx(140.0)
    assert report.charge_input_energy_wh == pytest.approx(260.0)
    assert report.battery_energy_change_wh == pytest.approx(208.0)
    assert report.generation_link_residual_w == 0
    assert report.load_link_residual_w == 0
    assert report.is_within_tolerance(
        1.0e-12,
        absolute_power_tolerance_w=0.0,
    )


def test_real_ratio_conversion_is_centralized_and_numpy_free() -> None:
    tree = ast.parse(
        EPS_PATH.read_text(encoding="utf-8"),
        filename=str(EPS_PATH),
    )
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    assert "_real_as_integer_ratio" in functions
    ratio_helper = functions["_real_as_integer_ratio"]
    product = functions["_product_ratio"]
    helper_calls = [
        node
        for node in ast.walk(product)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_real_as_integer_ratio"
    ]
    assert len(helper_calls) == 1

    direct_ratio_attributes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "as_integer_ratio"
    ]
    assert direct_ratio_attributes
    assert all(
        attribute in set(ast.walk(ratio_helper))
        for attribute in direct_ratio_attributes
    )


def test_v51g_production_has_no_numpy_legacy_or_endpoint_clipping() -> None:
    production_paths = tuple((ROOT / "ops_sim" / "v5").glob("*.py"))
    prohibited_import_roots = {"numpy", "pandas"}
    prohibited_identifiers = {
        "DEFAULT_CONFIG",
        "Simulator",
        "SatelliteState",
        "EPSILON",
        "epsilon",
        "isclose",
        "round",
        "clamp",
    }

    for path in production_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        import_roots = {
            alias.name.partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").partition(".")[0]
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
        assert identifiers.isdisjoint(prohibited_identifiers)

    for path in (EPS_PATH, POWER_LOADS_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        identifiers = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        assert identifiers.isdisjoint({"OperationalMode", "FDIRState"})

    eps_tree = ast.parse(
        EPS_PATH.read_text(encoding="utf-8"),
        filename=str(EPS_PATH),
    )
    for node in ast.walk(eps_tree):
        targets = ()
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        if not any(
            isinstance(target, ast.Name) and target.id == "end_energy_wh"
            for target in targets
        ):
            continue
        assert not (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id in {"min", "max", "round"}
        )


def test_v51g_preserves_exact_seven_component_load_ledger() -> None:
    assert tuple(field.name for field in fields(BatteryConfig)) == (
        "configuration_id",
        "nominal_energy_wh",
        "charge_efficiency",
        "discharge_efficiency",
        "max_charge_input_power_w",
        "max_discharge_output_power_w",
    )
    assert tuple(field.name for field in fields(PowerLoadBreakdown)) == (
        "base_bus_w",
        "obc_w",
        "adcs_w",
        "payload_w",
        "communications_w",
        "thermal_control_w",
        "propulsion_w",
    )


def test_v51g_decisions_are_present_once_and_state_numeric_contracts() -> None:
    decision_log = DECISION_LOG_PATH.read_text(encoding="utf-8")

    assert decision_log.count("## D077 ") == 1
    assert decision_log.count("## D078 ") == 1
    d077 = decision_log.partition("## D077 ")[2].partition("## D078 ")[0]
    d078 = decision_log.partition("## D078 ")[2]
    assert "numbers.Real" in d077
    assert "TypeError" in d077
    assert "ValueError" in d077
    assert "seven-component" in d078
    assert "finite and nonnegative" in d078


def test_v51g_public_exports_remain_narrow() -> None:
    from ops_sim.v5 import eps, power_loads

    assert eps.__all__ == [
        "BatteryTransition",
        "battery_soc_fraction",
        "compute_battery_transition",
    ]
    assert power_loads.__all__ == [
        "PowerLoadBreakdown",
        "compose_power_load",
    ]
