"""Configuration ownership and dependency cleanup for V5.2D2B1."""

import ast
from copy import deepcopy
from dataclasses import MISSING, fields, replace
from inspect import Parameter, signature
import json
from pathlib import Path

import numpy as np
import pytest

from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    BatteryDegradationStateSnapshot,
    CheckpointState,
    DegradationStateSnapshot,
    SolarDegradationStateSnapshot,
    SpacecraftStateSnapshot,
)
from ops_sim.v5.configuration import DegradationConfig
from ops_sim.v5.degradation import (
    BatteryAgeingModelConfig as PublicBatteryAgeingModelConfig,
    BatteryDegradationIntervalInput,
    BatteryDegradationTransition,
    BatteryThroughputIncrement,
    compute_battery_degradation_transition,
    compute_battery_throughput_increment,
)
from ops_sim.v5.degradation_config import BatteryAgeingModelConfig
from ops_sim.v5.engine import STEP_PHASE_ORDER, SimulationEngine, StepResult
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
from ops_sim.v5.state import BatteryDegradationState


ROOT = Path(__file__).resolve().parents[1]
V5_PATH = ROOT / "ops_sim" / "v5"
DEGRADATION_CONFIG_PATH = V5_PATH / "degradation_config.py"
ENGINE_PATH = V5_PATH / "engine.py"
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


def _ageing_model(
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


def _degradation_config(
    ageing_model: BatteryAgeingModelConfig | object | None = None,
) -> DegradationConfig:
    return DegradationConfig(
        SubsystemConfigurationId("d2b1-degradation"),
        _parameter(
            "degradation.battery.initial-usable-capacity-retention", "1", 1.0
        ),
        _parameter(
            "degradation.solar.initial-generation-retention", "1", 1.0
        ),
        _parameter(
            "degradation.battery.initial-energy-throughput", "Wh", 0.0
        ),
        _ageing_model() if ageing_model is None else ageing_model,
    )


def test_authoritative_ageing_class_is_moved_once_and_reexported() -> None:
    assert PublicBatteryAgeingModelConfig is BatteryAgeingModelConfig
    definitions = []
    for path in V5_PATH.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        definitions.extend(
            (path, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and node.name == "BatteryAgeingModelConfig"
        )
    assert [(path.name, node.name) for path, node in definitions] == [
        ("degradation_config.py", "BatteryAgeingModelConfig")
    ]


def test_degradation_config_module_has_the_exact_acyclic_dependencies() -> None:
    source = DEGRADATION_CONFIG_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DEGRADATION_CONFIG_PATH))
    imported_roots = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imported_roots <= {
        "__future__",
        "dataclasses",
        "math",
        "numbers",
        "ids",
        "parameters",
    }
    assert imported_roots.isdisjoint(
        {
            "configuration",
            "degradation",
            "state",
            "engine",
            "context",
            "checkpoint",
            "thermal",
            "eps",
            "numpy",
            "pandas",
        }
    )


def test_ageing_model_exact_shape_and_parameter_contract_are_unchanged() -> None:
    model = _ageing_model(reference_temperature_k=np.float64(300.0))
    assert tuple(field.name for field in fields(BatteryAgeingModelConfig)) == (
        "reference_temperature_k",
        "calendar_damage_rate_per_second_at_reference",
        "calendar_activation_energy_j_per_mol",
        "cycling_damage_per_normalized_energy_throughput_at_reference",
        "cycling_activation_energy_j_per_mol",
    )
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(BatteryAgeingModelConfig)
    )
    expected = (
        (
            model.reference_temperature_k,
            "degradation.battery.reference-temperature",
            "K",
        ),
        (
            model.calendar_damage_rate_per_second_at_reference,
            "degradation.battery.calendar-damage-rate-at-reference",
            "1/s",
        ),
        (
            model.calendar_activation_energy_j_per_mol,
            "degradation.battery.calendar-activation-energy",
            "J/mol",
        ),
        (
            model.cycling_damage_per_normalized_energy_throughput_at_reference,
            "degradation.battery.cycling-damage-per-normalized-"
            "throughput-at-reference",
            "1",
        ),
        (
            model.cycling_activation_energy_j_per_mol,
            "degradation.battery.cycling-activation-energy",
            "J/mol",
        ),
    )
    for parameter, parameter_id, units in expected:
        assert parameter.parameter_id == ParameterId(parameter_id)
        assert parameter.units == units
    with pytest.raises(ValueError, match="ParameterId"):
        replace(
            model,
            reference_temperature_k=_parameter("wrong", "K", 300.0),
        )
    with pytest.raises(ValueError, match="units"):
        replace(
            model,
            cycling_activation_energy_j_per_mol=_parameter(
                "degradation.battery.cycling-activation-energy", "K", 0.0
            ),
        )


@pytest.mark.parametrize(
    "changes",
    (
        {"reference_temperature_k": 0.0},
        {"calendar_rate": -1.0},
        {"calendar_activation_energy": -1.0},
        {"cycling_coefficient": -1.0},
        {"cycling_activation_energy": -1.0},
    ),
)
def test_moved_ageing_model_bounds_remain_unchanged(changes) -> None:
    with pytest.raises(ValueError):
        _ageing_model(**changes)


def test_degradation_config_owns_required_exact_ageing_model() -> None:
    config = _degradation_config()
    assert tuple(field.name for field in fields(DegradationConfig)) == (
        "configuration_id",
        "initial_battery_usable_capacity_retention",
        "initial_solar_generation_retention",
        "initial_battery_energy_throughput_wh",
        "battery_ageing_model",
    )
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(DegradationConfig)
    )
    assert type(config.battery_ageing_model) is BatteryAgeingModelConfig
    with pytest.raises(TypeError, match="battery_ageing_model"):
        DegradationConfig(
            config.configuration_id,
            config.initial_battery_usable_capacity_retention,
            config.initial_solar_generation_retention,
            config.initial_battery_energy_throughput_wh,
        )
    with pytest.raises(TypeError, match="battery_ageing_model"):
        _degradation_config(object())


def test_degradation_config_revalidates_nested_ageing_model() -> None:
    model = _ageing_model()
    object.__setattr__(
        model,
        "reference_temperature_k",
        _parameter("wrong", "K", 300.0),
    )
    with pytest.raises(ValueError, match="ParameterId"):
        _degradation_config(model)


def test_spacecraft_configuration_owns_ageing_model_transitively() -> None:
    spacecraft = build_demo_context().inputs.spacecraft_configuration
    model = spacecraft.degradation.battery_ageing_model
    assert type(model) is BatteryAgeingModelConfig
    assert model.reference_temperature_k.value == 300.0
    assert model.calendar_damage_rate_per_second_at_reference.value == 0.0
    assert model.calendar_activation_energy_j_per_mol.value == 0.0
    assert (
        model.cycling_damage_per_normalized_energy_throughput_at_reference.value
        == 0.0
    )
    assert model.cycling_activation_energy_j_per_mol.value == 0.0
    assert all(
        parameter.provenance.classification
        is ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
        for parameter in (
            model.reference_temperature_k,
            model.calendar_damage_rate_per_second_at_reference,
            model.calendar_activation_energy_j_per_mol,
            model.cycling_damage_per_normalized_energy_throughput_at_reference,
            model.cycling_activation_energy_j_per_mol,
        )
    )


def test_schema_four_json_restart_uses_supplied_immutable_ageing_model() -> None:
    context = build_demo_context()
    context.spacecraft_state.degradation.battery.usable_capacity_retention = 0.91
    context.spacecraft_state.degradation.battery.cumulative_energy_throughput_wh = (
        1234.5
    )
    context.spacecraft_state.degradation.solar.generation_retention = 0.87
    model = (
        context.inputs.spacecraft_configuration.degradation.battery_ageing_model
    )
    checkpoint = CheckpointState.from_context(context)
    payload = checkpoint.to_dict()
    parsed = CheckpointState.from_dict(
        json.loads(json.dumps(payload, allow_nan=False, sort_keys=True))
    )
    restored = parsed.restore(context.inputs)

    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == checkpoint.schema_version == 5
    assert restored.inputs is context.inputs
    assert (
        restored.inputs.spacecraft_configuration.degradation
        .battery_ageing_model
        is model
    )
    assert restored.spacecraft_state.degradation == (
        context.spacecraft_state.degradation
    )
    assert restored.spacecraft_state.degradation is not (
        context.spacecraft_state.degradation
    )
    assert "battery_ageing_model" not in json.dumps(payload, sort_keys=True)


def test_ageing_model_is_absent_from_mutable_snapshot_and_result_shapes() -> None:
    snapshot_types = (
        CheckpointState,
        SpacecraftStateSnapshot,
        DegradationStateSnapshot,
        BatteryDegradationStateSnapshot,
        SolarDegradationStateSnapshot,
        StepResult,
        BatteryDegradationTransition,
    )
    assert all(
        "battery_ageing_model"
        not in {field.name for field in fields(snapshot_type)}
        for snapshot_type in snapshot_types
    )


def test_d2a_throughput_and_damage_hand_calculations_are_unchanged() -> None:
    context = build_demo_context()
    battery_config = context.inputs.spacecraft_configuration.eps.battery
    eps_result = compute_eps_interval_transition(
        context.spacecraft_state.battery,
        context.inputs.spacecraft_configuration.eps,
        EPSIntervalInputs(
            False,
            0.0,
            PowerLoadBreakdown(90.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        ),
        dt_seconds=3600,
    )
    throughput = compute_battery_throughput_increment(
        eps_result,
        battery_config,
    )
    transition = compute_battery_degradation_transition(
        BatteryDegradationState(0.9, 10_000.0),
        battery_config,
        _ageing_model(calendar_rate=1.0e-8, cycling_coefficient=0.001),
        BatteryDegradationIntervalInput(
            300.0,
            BatteryThroughputIncrement(0.0, 12.0, 12.0),
            100,
        ),
    )

    assert eps_result.battery.discharge_output_w == pytest.approx(90.0)
    assert throughput == BatteryThroughputIncrement(0.0, 100.0, 100.0)
    assert transition.calendar_damage == pytest.approx(1.0e-6)
    assert transition.cycling_damage == pytest.approx(0.001 * (12 / 500))
    assert transition.total_damage == pytest.approx(2.5e-5)
    assert transition.end_usable_capacity_retention == pytest.approx(0.899975)
    assert transition.end_cumulative_energy_throughput_wh == 10_012.0


def test_engine_keeps_ageing_ownership_external_and_no_physics_unchanged() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ENGINE_PATH))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "degradation_config" not in imported_modules
    assert "BatteryAgeingModelConfig" not in source
    assert tuple(signature(SimulationEngine.step).parameters) == (
        "self",
        "context",
        "eps_inputs",
        "thermal_inputs",
        "heat_source_inputs",
        "solar_degradation_forcing",
    )
    assert all(
        parameter.kind
        in {Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY}
        for parameter in signature(SimulationEngine.step).parameters.values()
    )

    context = build_demo_context()
    before = deepcopy(context.spacecraft_state.degradation)
    model = (
        context.inputs.spacecraft_configuration.degradation.battery_ageing_model
    )
    result = SimulationEngine().step(context)
    assert result.executed_phases == STEP_PHASE_ORDER
    assert context.spacecraft_state.degradation == before
    assert (
        context.inputs.spacecraft_configuration.degradation
        .battery_ageing_model
        is model
    )


def test_d2b1_decisions_and_source_ownership_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    for number in range(131, 134):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D130 ") < decisions.index("## D131 ")
    s003 = sources.partition("### S003 ")[2].partition("### S004 ")[0]
    assert "BatteryAgeingModelConfig" in s003
    assert "DegradationConfig" in s003
    assert "immutable" in s003
    assert "schema 3" in s003.lower()
    assert "mutable degradation truth" in s003
