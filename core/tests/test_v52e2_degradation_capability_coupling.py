"""Degradation-aware EPS capability coupling for V5.2E2."""

import ast
from copy import deepcopy
from dataclasses import fields, replace
import json
from pathlib import Path
import subprocess

import pytest

import ops_sim.v5.eps_system as eps_system_module
from examples.v52_integrated_eps_thermal_demo import (
    DemoRow,
    build_demo_context,
    build_step_inputs,
    run_demo,
)
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.engine import STEP_PHASE_ORDER, SimulationEngine, StepResult
from ops_sim.v5.eps import compute_battery_transition
from ops_sim.v5.eps_capability import (
    BatteryCapacityReconciliationResult,
    EPSCapabilityResult,
    compute_battery_capacity_reconciliation,
    compute_eps_capability,
)
from ops_sim.v5.eps_system import (
    EPSIntervalInputs,
    compute_eps_interval_transition,
)
from ops_sim.v5.eps_validation import compute_eps_conservation_report
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.state import (
    BatteryDegradationState,
    BatteryState,
    DegradationState,
    SolarDegradationState,
)
from ops_sim.v5.degradation import SolarDegradationForcingInput


ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_PATH = ROOT / "ops_sim" / "v5" / "eps_capability.py"
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"
EPS_SYSTEM_PATH = ROOT / "ops_sim" / "v5" / "eps_system.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"


def _eps_config(*, battery_wh: float = 1000.0, solar_w: float = 1000.0):
    base = build_demo_context().inputs.spacecraft_configuration.eps
    battery = replace(
        base.battery,
        nominal_energy_wh=replace(
            base.battery.nominal_energy_wh,
            value=battery_wh,
        ),
    )
    solar = replace(
        base.solar_array,
        nominal_generation_w=replace(
            base.solar_array.nominal_generation_w,
            value=solar_w,
        ),
    )
    return replace(base, battery=battery, solar_array=solar)


def _degradation(
    battery_retention: float = 0.8,
    solar_retention: float = 0.6,
) -> DegradationState:
    return DegradationState(
        BatteryDegradationState(battery_retention, 0.0),
        SolarDegradationState(solar_retention),
    )


def _capability(
    *,
    battery_retention: float = 0.8,
    solar_retention: float = 0.6,
) -> EPSCapabilityResult:
    return compute_eps_capability(
        _eps_config(),
        _degradation(battery_retention, solar_retention),
    )


def _eps_inputs(
    *,
    sunlit: bool = True,
    incidence_angle_deg: float = 0.0,
    load_w: float = 0.0,
) -> EPSIntervalInputs:
    return EPSIntervalInputs(
        sunlit,
        incidence_angle_deg,
        PowerLoadBreakdown(load_w, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


def _assert_capability_rejected_before_composition(
    monkeypatch,
    config,
    capability: EPSCapabilityResult,
    *,
    match: str,
) -> None:
    physical_calls = []

    def unexpected_physical_call(*args, **kwargs):
        physical_calls.append((args, kwargs))
        raise AssertionError("physical composition must not be reached")

    monkeypatch.setattr(
        eps_system_module,
        "compute_solar_generation",
        unexpected_physical_call,
    )
    monkeypatch.setattr(
        eps_system_module,
        "compute_battery_transition",
        unexpected_physical_call,
    )

    with pytest.raises(ValueError, match=match):
        compute_eps_interval_transition(
            BatteryState(100.0),
            config,
            _eps_inputs(),
            dt_seconds=1,
            capability=capability,
        )

    assert physical_calls == []


def _context(
    *,
    battery_retention: float = 0.8,
    solar_retention: float = 0.6,
    battery_energy_wh: float = 250.0,
    calendar_rate: float = 0.0,
):
    context = build_demo_context()
    context.spacecraft_state.battery.energy_wh = battery_energy_wh
    context.spacecraft_state.degradation.battery.usable_capacity_retention = (
        battery_retention
    )
    context.spacecraft_state.degradation.solar.generation_retention = (
        solar_retention
    )
    model = (
        context.inputs.spacecraft_configuration.degradation
        .battery_ageing_model
    )
    model = replace(
        model,
        calendar_damage_rate_per_second_at_reference=replace(
            model.calendar_damage_rate_per_second_at_reference,
            value=calendar_rate,
        ),
    )
    spacecraft = context.inputs.spacecraft_configuration
    spacecraft = replace(
        spacecraft,
        degradation=replace(
            spacecraft.degradation,
            battery_ageing_model=model,
        ),
    )
    context.inputs = replace(
        context.inputs,
        spacecraft_configuration=spacecraft,
    )
    return context


def _coupled_step(
    context,
    step_index: int = 0,
    *,
    solar_loss: float | None = None,
):
    eps_inputs, thermal_inputs, heat_source_inputs = build_step_inputs(
        step_index
    )
    forcing = (
        None
        if solar_loss is None
        else SolarDegradationForcingInput(solar_loss)
    )
    return SimulationEngine().step(
        context,
        eps_inputs=eps_inputs,
        thermal_inputs=thermal_inputs,
        heat_source_inputs=heat_source_inputs,
        solar_degradation_forcing=forcing,
    )


def _run_steps(context, start: int, count: int) -> None:
    for step_index in range(start, start + count):
        solar_loss = 0.01 if step_index in {2, 7} else None
        _coupled_step(context, step_index, solar_loss=solar_loss)


def test_capability_result_has_exact_frozen_slotted_fields() -> None:
    assert tuple(field.name for field in fields(EPSCapabilityResult)) == (
        "battery_capacity_retention",
        "battery_usable_capacity_wh",
        "solar_generation_retention",
        "solar_nominal_generation_capability_w",
    )
    result = _capability()
    assert not hasattr(result, "__dict__")


def test_reconciliation_result_has_exact_frozen_slotted_fields() -> None:
    assert tuple(
        field.name for field in fields(BatteryCapacityReconciliationResult)
    ) == (
        "proposed_end_energy_wh",
        "end_capacity_retention",
        "end_usable_capacity_wh",
        "unavailable_energy_wh",
        "authoritative_end_energy_wh",
    )
    result = compute_battery_capacity_reconciliation(
        700.0,
        _eps_config().battery,
        0.8,
    )
    assert not hasattr(result, "__dict__")


def test_battery_capability_hand_calculation() -> None:
    result = _capability(battery_retention=0.8)

    assert result.battery_capacity_retention == 0.8
    assert result.battery_usable_capacity_wh == 800.0


def test_solar_capability_hand_calculation_at_zero_and_sixty_degrees() -> None:
    config = _eps_config()
    capability = _capability(solar_retention=0.6)

    direct = compute_eps_interval_transition(
        BatteryState(100.0),
        config,
        _eps_inputs(incidence_angle_deg=0.0),
        dt_seconds=1,
        capability=capability,
    )
    oblique = compute_eps_interval_transition(
        BatteryState(100.0),
        config,
        _eps_inputs(incidence_angle_deg=60.0),
        dt_seconds=1,
        capability=capability,
    )

    assert direct.solar.nominal_generation_w == 600.0
    assert direct.solar.generation_w == 600.0
    assert oblique.solar.generation_w == pytest.approx(300.0)


def test_valid_computed_capability_passes_relationship_validation() -> None:
    config = _eps_config()
    capability = compute_eps_capability(config, _degradation())

    result = compute_eps_interval_transition(
        BatteryState(100.0),
        config,
        _eps_inputs(),
        dt_seconds=1,
        capability=capability,
    )

    assert result.solar.nominal_generation_w == 600.0
    assert result.battery.end_energy_wh > 100.0


def test_wrong_smaller_battery_capacity_is_rejected_before_composition(
    monkeypatch,
) -> None:
    config = _eps_config()
    capability = replace(
        compute_eps_capability(config, _degradation()),
        battery_usable_capacity_wh=650.0,
    )

    _assert_capability_rejected_before_composition(
        monkeypatch,
        config,
        capability,
        match="battery_usable_capacity_wh",
    )


def test_wrong_smaller_solar_capability_is_rejected_before_composition(
    monkeypatch,
) -> None:
    config = _eps_config()
    capability = replace(
        compute_eps_capability(config, _degradation()),
        solar_nominal_generation_capability_w=500.0,
    )

    _assert_capability_rejected_before_composition(
        monkeypatch,
        config,
        capability,
        match="solar_nominal_generation_capability_w",
    )


def test_capability_from_different_eps_config_is_rejected_before_composition(
    monkeypatch,
) -> None:
    config = _eps_config()
    capability = compute_eps_capability(
        _eps_config(battery_wh=900.0, solar_w=900.0),
        _degradation(),
    )

    _assert_capability_rejected_before_composition(
        monkeypatch,
        config,
        capability,
        match="battery_usable_capacity_wh",
    )


def test_both_mismatched_capabilities_are_rejected_before_composition(
    monkeypatch,
) -> None:
    config = _eps_config()
    capability = EPSCapabilityResult(0.8, 650.0, 0.6, 500.0)

    _assert_capability_rejected_before_composition(
        monkeypatch,
        config,
        capability,
        match="battery_usable_capacity_wh",
    )


def test_retention_one_is_exactly_nominal_compatible() -> None:
    config = _eps_config()
    inputs = _eps_inputs(load_w=100.0)
    state = BatteryState(500.0)
    nominal = compute_eps_interval_transition(
        state,
        config,
        inputs,
        dt_seconds=60,
    )
    capability_aware = compute_eps_interval_transition(
        state,
        config,
        inputs,
        dt_seconds=60,
        capability=compute_eps_capability(config, _degradation(1.0, 1.0)),
    )

    assert capability_aware == nominal


def test_degraded_battery_charge_stops_at_effective_ceiling() -> None:
    config = _eps_config()
    result = compute_eps_interval_transition(
        BatteryState(790.0),
        config,
        _eps_inputs(load_w=0.0),
        dt_seconds=3600,
        capability=_capability(),
    )

    assert result.battery.end_energy_wh == 800.0
    assert result.battery.end_energy_wh < config.battery.nominal_energy_wh.value


def test_degraded_battery_discharge_uses_effective_energy_state() -> None:
    config = _eps_config()
    result = compute_eps_interval_transition(
        BatteryState(500.0),
        config,
        _eps_inputs(sunlit=False, load_w=100.0),
        dt_seconds=3600,
        capability=_capability(),
    )

    assert result.battery.discharge_output_w == 100.0
    assert result.battery.end_energy_wh == pytest.approx(
        500.0 - 100.0 / config.battery.discharge_efficiency.value
    )


def test_capacity_retention_does_not_scale_discharge_power_limit() -> None:
    config = _eps_config()
    capability = compute_eps_capability(config, _degradation(0.5, 1.0))
    result = compute_battery_transition(
        BatteryState(500.0),
        config.battery,
        generation_w=0.0,
        load_w=200.0,
        dt_seconds=60,
        usable_capacity_wh=capability.battery_usable_capacity_wh,
    )

    assert capability.battery_usable_capacity_wh == 500.0
    assert config.battery.max_discharge_output_power_w.value == 150.0
    assert result.discharge_output_w == 150.0


def test_degraded_solar_generation_uses_retained_nominal_capability() -> None:
    context = _context(solar_retention=0.6)
    inputs, _, _ = build_step_inputs(0)

    result = SimulationEngine().step(context, eps_inputs=inputs)

    assert result.eps_result is not None
    assert result.eps_result.solar.nominal_generation_w == 108.0
    assert result.eps_result.solar.generation_w == 108.0


def test_incidence_geometry_applies_after_retention_exactly_once() -> None:
    config = _eps_config()
    capability = _capability(solar_retention=0.6)
    result = compute_eps_interval_transition(
        BatteryState(100.0),
        config,
        _eps_inputs(incidence_angle_deg=60.0),
        dt_seconds=1,
        capability=capability,
    )

    assert result.solar.nominal_generation_w == 1000.0 * 0.6
    assert result.solar.generation_w == pytest.approx(1000.0 * 0.6 * 0.5)


def test_start_energy_above_effective_capacity_is_rejected_atomically() -> None:
    context = _context(battery_retention=0.4, battery_energy_wh=250.0)
    checkpoint = CheckpointState.from_context(context)
    references = (
        context.spacecraft_state,
        context.spacecraft_state.data_storage,
        context.diagnostics,
    )
    inputs, _, _ = build_step_inputs(0)

    with pytest.raises(ValueError, match="usable battery energy"):
        SimulationEngine().step(context, eps_inputs=inputs)

    assert CheckpointState.from_context(context) == checkpoint
    assert (
        context.spacecraft_state,
        context.spacecraft_state.data_storage,
        context.diagnostics,
    ) == references


def test_zero_reconciliation_hand_calculation() -> None:
    result = compute_battery_capacity_reconciliation(
        700.0,
        _eps_config().battery,
        0.8,
    )

    assert result.end_usable_capacity_wh == 800.0
    assert result.unavailable_energy_wh == 0.0
    assert result.authoritative_end_energy_wh == 700.0


def test_active_reconciliation_hand_calculation() -> None:
    result = compute_battery_capacity_reconciliation(
        850.0,
        _eps_config().battery,
        0.8,
    )

    assert result.end_usable_capacity_wh == 800.0
    assert result.unavailable_energy_wh == 50.0
    assert result.authoritative_end_energy_wh == 800.0


def test_reconciliation_unavailable_energy_is_not_conversion_heat() -> None:
    context = _context(
        battery_retention=0.8,
        solar_retention=1.0,
        battery_energy_wh=400.0,
        calendar_rate=1.0e-6,
    )
    result = _coupled_step(context, 0)
    reconciliation = result.battery_capacity_reconciliation_result
    assert reconciliation is not None
    assert reconciliation.unavailable_energy_wh > 0
    assert result.eps_result is not None
    assert result.eps_result.battery.conversion_loss_wh == 0.0
    assert result.thermal_coupling_result is not None
    battery_ledger = next(
        ledger
        for ledger in result.thermal_coupling_result.node_heat_ledgers
        if ledger.node_id.value == "battery"
    )
    assert battery_ledger.battery_conversion_heat_w == 0.0
    assert battery_ledger.total_applied_heat_w == pytest.approx(1.7)


def test_raw_eps_proposal_conservation_remains_internally_valid() -> None:
    context = _context(
        battery_retention=0.8,
        solar_retention=1.0,
        battery_energy_wh=400.0,
        calendar_rate=1.0e-6,
    )
    result = _coupled_step(context, 0)
    assert result.eps_result is not None
    report = compute_eps_conservation_report(result.eps_result)
    assert report.is_within_tolerance(
        1.0e-12,
        absolute_power_tolerance_w=1.0e-12,
    )
    reconciliation = result.battery_capacity_reconciliation_result
    assert reconciliation is not None
    assert result.eps_result.battery.end_energy_wh - (
        context.spacecraft_state.battery.energy_wh
    ) == pytest.approx(reconciliation.unavailable_energy_wh)


def test_step_result_appends_capability_fields_with_legacy_defaults() -> None:
    assert tuple(field.name for field in fields(StepResult)) == (
        "start_time_seconds",
        "end_time_seconds",
        "dt_seconds",
        "executed_phases",
        "eps_result",
        "thermal_coupling_result",
        "battery_degradation_result",
        "solar_degradation_result",
        "eps_capability_result",
        "battery_capacity_reconciliation_result",
    )
    legacy = StepResult(0, 60, 60, STEP_PHASE_ORDER)
    assert legacy.eps_capability_result is None
    assert legacy.battery_capacity_reconciliation_result is None


def test_eps_only_uses_capability_without_evolving_degradation() -> None:
    context = _context(battery_retention=0.8, solar_retention=0.6)
    before = deepcopy(context.spacecraft_state.degradation)
    inputs, _, _ = build_step_inputs(0)

    result = SimulationEngine().step(context, eps_inputs=inputs)

    assert result.eps_capability_result == EPSCapabilityResult(
        0.8,
        400.0,
        0.6,
        108.0,
    )
    assert result.battery_capacity_reconciliation_result is None
    assert result.battery_degradation_result is None
    assert context.spacecraft_state.degradation == before


def test_full_coupled_step_uses_start_retention_for_current_eps() -> None:
    context = _context(
        battery_retention=0.8,
        solar_retention=0.6,
        calendar_rate=1.0e-6,
    )

    result = _coupled_step(context, 0, solar_loss=0.1)

    assert result.eps_capability_result == EPSCapabilityResult(
        0.8,
        400.0,
        0.6,
        108.0,
    )
    assert result.eps_result is not None
    assert result.eps_result.solar.nominal_generation_w == 108.0
    assert result.solar_degradation_result is not None
    assert result.solar_degradation_result.end_generation_retention == 0.5


def test_battery_ageing_endpoint_changes_capability_next_step_only() -> None:
    context = _context(
        battery_retention=0.8,
        solar_retention=1.0,
        calendar_rate=1.0e-6,
    )

    first = _coupled_step(context, 0)
    assert first.eps_capability_result is not None
    assert first.eps_capability_result.battery_capacity_retention == 0.8
    assert first.battery_degradation_result is not None
    aged_retention = (
        first.battery_degradation_result.end_usable_capacity_retention
    )
    second = _coupled_step(context, 1)

    assert second.eps_capability_result is not None
    assert second.eps_capability_result.battery_capacity_retention == (
        aged_retention
    )
    assert second.eps_capability_result.battery_usable_capacity_wh == (
        500.0 * aged_retention
    )


def test_solar_forcing_endpoint_changes_generation_next_step_only() -> None:
    context = _context(battery_retention=1.0, solar_retention=1.0)

    first = _coupled_step(context, 0, solar_loss=0.1)
    second = _coupled_step(context, 1)

    assert first.eps_capability_result is not None
    assert first.eps_capability_result.solar_generation_retention == 1.0
    assert first.eps_result is not None
    assert first.eps_result.solar.nominal_generation_w == 180.0
    assert second.eps_capability_result is not None
    assert second.eps_capability_result.solar_generation_retention == 0.9
    assert second.eps_result is not None
    assert second.eps_result.solar.nominal_generation_w == 162.0


def test_no_physics_path_remains_unchanged() -> None:
    context = _context()
    battery_before = deepcopy(context.spacecraft_state.battery)
    thermal_before = deepcopy(context.spacecraft_state.thermal)
    degradation_before = deepcopy(context.spacecraft_state.degradation)

    result = SimulationEngine().step(context)

    assert result.eps_capability_result is None
    assert result.battery_capacity_reconciliation_result is None
    assert context.spacecraft_state.battery == battery_before
    assert context.spacecraft_state.thermal == thermal_before
    assert context.spacecraft_state.degradation == degradation_before
    assert context.simulation_time_seconds == 60
    assert context.diagnostics.completed_steps == 1


def test_zero_damage_demo_keeps_its_sixteen_numerical_rows() -> None:
    current_rows = run_demo()
    expected_rows = (
        DemoRow(
            1, 60, True, 70.0, 180.0, 251.68666666666667,
            0.14666666666666658, 294.9711357979018, 292.9738083288189,
            290.964853888334, 10.499999999999993, 0.0,
        ),
        DemoRow(
            2, 120, True, 150.0, 180.0, 252.14666666666668,
            0.03999999999999998, 294.94652304813644, 292.94323207567203,
            290.9504411145865, 4.599999999999999, 0.0,
        ),
        DemoRow(
            3, 180, False, 60.0, 0.0, 251.03555555555556,
            0.11111111111111108, 294.914455804087, 292.9155334424863,
            290.91318389767633, 8.366666666666665, 0,
        ),
        DemoRow(
            4, 240, False, 120.0, 0.0, 248.81333333333333,
            0.22222222222222215, 294.88664700519894, 292.8932516012669,
            290.8926634002036, 15.533333333333331, 0,
        ),
        DemoRow(
            5, 300, True, 70.0, 180.0, 250.5, 0.14666666666666658,
            294.8579939532719, 292.8672271623545, 290.857710749784,
            10.499999999999993, 0.0,
        ),
        DemoRow(
            6, 360, True, 150.0, 180.0, 250.96, 0.03999999999999998,
            294.8335918827594, 292.8368178539364, 290.8434910206798,
            4.599999999999999, 0.0,
        ),
        DemoRow(
            7, 420, False, 60.0, 0.0, 249.8488888888889,
            0.11111111111111108, 294.8017348571058, 292.80928587078176,
            290.80642647452515, 8.366666666666665, 0,
        ),
        DemoRow(
            8, 480, False, 120.0, 0.0, 247.62666666666667,
            0.22222222222222215, 294.77413580139256, 292.78717039046455,
            290.786098228809, 15.533333333333331, 0,
        ),
        DemoRow(
            9, 540, True, 70.0, 180.0, 249.31333333333333,
            0.14666666666666658, 294.7456920274943, 292.7613120332671,
            290.75133744570854, 10.499999999999993, 0.0,
        ),
        DemoRow(
            10, 600, True, 150.0, 180.0, 249.77333333333334,
            0.03999999999999998, 294.7214987693016, 292.7310685213347,
            290.73730917144803, 4.599999999999999, 0.0,
        ),
        DemoRow(
            11, 660, False, 60.0, 0.0, 248.66222222222223,
            0.11111111111111108, 294.68985010023056, 292.7037020423269,
            290.70043571003447, 8.366666666666665, 0,
        ),
        DemoRow(
            12, 720, False, 120.0, 0.0, 246.44,
            0.22222222222222215, 294.6624589311086, 292.681751779346,
            290.6802981341979, 15.533333333333331, 0,
        ),
        DemoRow(
            13, 780, True, 70.0, 180.0, 248.12666666666667,
            0.14666666666666658, 294.6342225837956, 292.65605836254497,
            290.6457276403992, 10.499999999999993, 0.0,
        ),
        DemoRow(
            14, 840, True, 150.0, 180.0, 248.58666666666667,
            0.03999999999999998, 294.61023629161673, 292.6259795080678,
            290.63188924704167, 4.599999999999999, 0.0,
        ),
        DemoRow(
            15, 900, False, 60.0, 0.0, 247.47555555555556,
            0.11111111111111108, 294.57879413787083, 292.5987773965122,
            290.5952053001658, 8.366666666666665, 0,
        ),
        DemoRow(
            16, 960, False, 120.0, 0.0, 245.25333333333333,
            0.22222222222222215, 294.55160901924063, 292.57699121646885,
            290.575256828092, 15.533333333333331, 0,
        ),
    )

    assert current_rows == expected_rows


def test_twenty_four_steps_keep_completed_energy_within_usable_capacity() -> None:
    context = _context(
        battery_retention=1.0,
        solar_retention=1.0,
        calendar_rate=1.0e-6,
    )

    for step_index in range(24):
        result = _coupled_step(context, step_index)
        reconciliation = result.battery_capacity_reconciliation_result
        assert reconciliation is not None
        assert context.spacecraft_state.battery.energy_wh <= (
            reconciliation.end_usable_capacity_wh
        )


def test_schema_four_json_restart_matches_direct_e2_execution() -> None:
    direct = _context(
        battery_retention=1.0,
        solar_retention=1.0,
        calendar_rate=1.0e-7,
    )
    split = _context(
        battery_retention=1.0,
        solar_retention=1.0,
        calendar_rate=1.0e-7,
    )
    _run_steps(direct, 0, 12)
    _run_steps(split, 0, 5)
    checkpoint = CheckpointState.from_context(split)
    assert checkpoint.schema_version == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    payload = json.loads(json.dumps(checkpoint.to_dict(), allow_nan=False))
    restored = CheckpointState.from_dict(payload).restore(split.inputs)
    _run_steps(restored, 5, 7)

    assert restored == direct


def test_e2_production_has_no_numpy_dependency() -> None:
    for path in (
        CAPABILITY_PATH,
        ROOT / "ops_sim" / "v5" / "eps.py",
        ROOT / "ops_sim" / "v5" / "solar.py",
        ROOT / "ops_sim" / "v5" / "eps_system.py",
        ENGINE_PATH,
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots = {
            alias.name.partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert "numpy" not in roots


def test_reconciliation_uses_explicit_branch_without_hidden_endpoint_calls() -> None:
    tree = ast.parse(
        CAPABILITY_PATH.read_text(encoding="utf-8"),
        filename=str(CAPABILITY_PATH),
    )
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "compute_battery_capacity_reconciliation"
    )
    called_names = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called_names.isdisjoint({"min", "max", "round"})
    assert any(isinstance(node, ast.If) for node in ast.walk(function))


def test_engine_delegates_capability_without_duplicate_retention_equations() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ENGINE_PATH))
    called_names = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert called_names.count("compute_eps_capability") == 1
    assert called_names.count("compute_battery_capacity_reconciliation") == 1
    assert "nominal_energy_wh.value *" not in source
    assert "nominal_generation_w.value *" not in source


def test_eps_system_delegates_capability_relationship_without_arithmetic() -> None:
    eps_system_tree = ast.parse(
        EPS_SYSTEM_PATH.read_text(encoding="utf-8"),
        filename=str(EPS_SYSTEM_PATH),
    )
    composite = next(
        node
        for node in ast.walk(eps_system_tree)
        if isinstance(node, ast.FunctionDef)
        # Task 04A: both duration wrappers delegate to this single composition.
        and node.name == "_compute_eps_transition"
    )
    composite_calls = [
        node.func.id
        for statement in composite.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    composite_attributes = {
        node.attr
        for statement in composite.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Attribute)
    }

    assert composite_calls.count("validate_eps_capability_for_config") == 1
    assert {
        "nominal_energy_wh",
        "nominal_generation_w",
    }.isdisjoint(composite_attributes)
    assert not any(
        isinstance(node, ast.BinOp)
        for statement in composite.body
        for node in ast.walk(statement)
    )

    capability_tree = ast.parse(
        CAPABILITY_PATH.read_text(encoding="utf-8"),
        filename=str(CAPABILITY_PATH),
    )
    validator = next(
        node
        for node in ast.walk(capability_tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "validate_eps_capability_for_config"
    )
    validator_calls = [
        node.func.id
        for node in ast.walk(validator)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert validator_calls.count("_checked_product") == 2
    assert set(validator_calls).isdisjoint(
        {"isclose", "min", "max", "round"}
    )


def test_historical_handoff_tag_remains_fixed() -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "cup-handoff-2026-08-31^{}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip().startswith("3d2ebc8")


def test_d141_through_d148_and_e2_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    for number in range(141, 149):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D140 ") < decisions.index("## D141 ")
    assert "V5.2E2" in sources
    assert "power fade" in sources.lower()
    assert "unavailable energy" in sources.lower()
    assert "chemistry-specific" in sources.lower()
