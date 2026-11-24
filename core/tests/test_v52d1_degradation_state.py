"""State, configuration, and checkpoint validation for V5.2D1."""

import ast
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields, replace
import json
from pathlib import Path

import numpy as np
import pytest

from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.checkpoint import (
    BatteryDegradationStateSnapshot,
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
    DataStorageStateSnapshot,
    DegradationStateSnapshot,
    SolarDegradationStateSnapshot,
)
from ops_sim.v5.configuration import (
    ADCSConfig,
    BatteryConfig,
    CommunicationsConfig,
    DegradationConfig,
    EPSConfig,
    OBCConfig,
    PayloadConfig,
    PayloadFamily,
    PayloadMode,
    PropulsionConfig,
    SolarArrayConfig,
    SpacecraftConfiguration,
    StorageConfig,
    ThermalConfig,
)
from ops_sim.v5.context import SimulationContext, SimulationInputs
from ops_sim.v5.controller_state import ControllerState
from ops_sim.v5.data_delivery import GroundDataDeliveryState
from ops_sim.v5.degradation_config import BatteryAgeingModelConfig
from ops_sim.v5.diagnostics import Diagnostics
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.eps import compute_battery_transition
from ops_sim.v5.ids import (
    ADCSSlewAnchorId,
    ControllerId,
    EnvironmentId,
    FlightRulesId,
    ModelManifestId,
    NumericalConfigId,
    ParameterId,
    ScenarioId,
    SpacecraftConfigurationId,
    SubsystemConfigurationId,
    ThermalNodeId,
    WorldId,
)
from ops_sim.v5.knowledge import GroundKnowledgeState, TelemetrySnapshot
from ops_sim.v5.manifest import ModelManifest
from ops_sim.v5.mission import MissionState
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload_config import OpticalAcquisitionConfig
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.run_config import (
    EnvironmentConfig,
    FlightRulesConfig,
    NumericalConfig,
    ScenarioConfig,
)
from ops_sim.v5.solar import compute_solar_generation
from ops_sim.v5.state import (
    BatteryDegradationState,
    BatteryState,
    DataStorageState,
    DegradationState,
    FDIRState,
    OnboardOperationsState,
    OperationalMode,
    PropulsionState,
    SolarDegradationState,
    SpacecraftState,
    ThermalNodeState,
    ThermalState,
)
from ops_sim.v5.thermal_config import ThermalNetworkConfig, ThermalNodeConfig
from ops_sim.v5.world import CommonWorld


ROOT = Path(__file__).resolve().parents[1]
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
PRODUCTION_PATHS = {
    name: ROOT / "ops_sim" / "v5" / name
    for name in (
        "state.py",
        "configuration.py",
        "context.py",
        "checkpoint.py",
        "engine.py",
        "eps.py",
        "eps_system.py",
        "solar.py",
    )
}


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


def _agile_pointing() -> AgilePointingConfig:
    def anchor(
        anchor_value: str,
        angle_deg: float,
        elapsed_seconds: float,
    ) -> BoresightSlewTimeAnchor:
        prefix = f"adcs.slew-envelope.{anchor_value}"
        return BoresightSlewTimeAnchor(
            ADCSSlewAnchorId(anchor_value),
            _parameter(f"{prefix}.angular-separation", "deg", angle_deg),
            _parameter(f"{prefix}.elapsed-time", "s", elapsed_seconds),
        )

    return AgilePointingConfig(
        _parameter(
            "adcs.pointing.maximum-view-angle-from-nadir", "deg", 45.0
        ),
        _parameter("adcs.pointing.post-slew-settling-time", "s", 5.0),
        tuple(
            anchor(*values)
            for values in (
                ("zero", 0.0, 0.0),
                ("small", 10.0, 20.0),
                ("medium", 30.0, 50.0),
                ("large", 60.0, 90.0),
                ("extended", 90.0, 130.0),
            )
        ),
    )


def _optical_acquisition() -> OpticalAcquisitionConfig:
    return OpticalAcquisitionConfig(
        _parameter(
            "payload.optical.reference-nadir-swath-width", "m", 1000.0
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
        _parameter("payload.optical.acquisition-power", "W", 100.0),
        True,
    )


def _zero_damage_ageing_model() -> BatteryAgeingModelConfig:
    return BatteryAgeingModelConfig(
        _parameter(
            "degradation.battery.reference-temperature", "K", 300.0
        ),
        _parameter(
            "degradation.battery.calendar-damage-rate-at-reference",
            "1/s",
            0.0,
        ),
        _parameter(
            "degradation.battery.calendar-activation-energy", "J/mol", 0.0
        ),
        _parameter(
            "degradation.battery.cycling-damage-per-normalized-"
            "throughput-at-reference",
            "1",
            0.0,
        ),
        _parameter(
            "degradation.battery.cycling-activation-energy", "J/mol", 0.0
        ),
    )


def _degradation_config(
    *,
    battery_retention: object = 1.0,
    solar_retention: object = 1.0,
    throughput_wh: object = 0.0,
    configuration_id: str = "degradation",
) -> DegradationConfig:
    return DegradationConfig(
        SubsystemConfigurationId(configuration_id),
        _parameter(
            "degradation.battery.initial-usable-capacity-retention",
            "1",
            battery_retention,
        ),
        _parameter(
            "degradation.solar.initial-generation-retention",
            "1",
            solar_retention,
        ),
        _parameter(
            "degradation.battery.initial-energy-throughput",
            "Wh",
            throughput_wh,
        ),
        _zero_damage_ageing_model(),
    )


def _thermal_network() -> ThermalNetworkConfig:
    nodes = []
    for name in ("bus", "battery", "payload"):
        prefix = f"thermal.node.{name}"
        nodes.append(
            ThermalNodeConfig(
                ThermalNodeId(name),
                _parameter(f"{prefix}.heat-capacity", "J/K", 1000.0),
                _parameter(f"{prefix}.emissivity", "1", 0.8),
                _parameter(f"{prefix}.radiating-area", "m^2", 1.0),
                _parameter(
                    f"{prefix}.operating-min-temperature", "K", 270.0
                ),
                _parameter(
                    f"{prefix}.operating-max-temperature", "K", 320.0
                ),
                _parameter(
                    f"{prefix}.survival-min-temperature", "K", 250.0
                ),
                _parameter(
                    f"{prefix}.survival-max-temperature", "K", 340.0
                ),
            )
        )
    return ThermalNetworkConfig(
        tuple(nodes),
        (),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("payload"),
    )


def _spacecraft_config(
    degradation: DegradationConfig | None = None,
) -> SpacecraftConfiguration:
    return SpacecraftConfiguration(
        SpacecraftConfigurationId("degradation-optical"),
        "Synthetic Degradation Reference",
        1,
        EPSConfig(
            SubsystemConfigurationId("eps"),
            BatteryConfig(
                SubsystemConfigurationId("battery"),
                _parameter("eps.battery.nominal-energy", "Wh", 1000.0),
                _parameter("eps.battery.charge-efficiency", "1", 1.0),
                _parameter("eps.battery.discharge-efficiency", "1", 1.0),
                _parameter("eps.battery.max-charge-input-power", "W", 100.0),
                _parameter(
                    "eps.battery.max-discharge-output-power", "W", 100.0
                ),
            ),
            SolarArrayConfig(
                SubsystemConfigurationId("solar"),
                _parameter(
                    "eps.solar-array.nominal-generation", "W", 200.0
                ),
            ),
        ),
        PayloadConfig(
            SubsystemConfigurationId("payload"),
            PayloadFamily.OPTICAL_EO,
            (PayloadMode.PANCHROMATIC,),
            _optical_acquisition(),
        ),
        StorageConfig(
            SubsystemConfigurationId("storage"),
            _parameter("storage.usable-capacity", "GB", 10.0),
        ),
        CommunicationsConfig(
            SubsystemConfigurationId("communications"),
            _parameter(
                "communications.nominal-downlink-data-rate",
                "bit/s",
                1_000_000.0,
            ),
        ),
        ADCSConfig(SubsystemConfigurationId("adcs"), _agile_pointing()),
        ThermalConfig(SubsystemConfigurationId("thermal"), _thermal_network()),
        _degradation_config() if degradation is None else degradation,
        PropulsionConfig(
            SubsystemConfigurationId("propulsion"),
            _parameter("propulsion.initial-delta-v", "m/s", 10.0),
        ),
        OBCConfig(SubsystemConfigurationId("obc")),
    )


def _state(
    battery_retention: object = 0.91,
    solar_retention: object = 0.87,
    throughput_wh: object = 1234.5,
) -> SpacecraftState:
    return SpacecraftState(
        BatteryState(500.0),
        PropulsionState(9.0),
        ThermalState(
            tuple(
                ThermalNodeState(ThermalNodeId(name), 300.0)
                for name in ("bus", "battery", "payload")
            )
        ),
        DegradationState(
            BatteryDegradationState(battery_retention, throughput_wh),
            SolarDegradationState(solar_retention),
        ),
        OnboardOperationsState(
            OperationalMode.STANDBY,
            FDIRState.NORMAL,
            None,
            None,
            None,
            None,
        ),
        DataStorageState(()),
    )


def _context(
    *,
    state: SpacecraftState | None = None,
    degradation_config: DegradationConfig | None = None,
) -> SimulationContext:
    spacecraft = _spacecraft_config(degradation_config)
    numerical = NumericalConfig(NumericalConfigId("step"), 60, 10, 60)
    environment = EnvironmentConfig(EnvironmentId("environment"))
    flight_rules = FlightRulesConfig(FlightRulesId("rules"))
    scenario = ScenarioConfig(ScenarioId("scenario"))
    world = CommonWorld(WorldId("world"), scenario.scenario_id, 600, ())
    controller_id = ControllerId("controller")
    manifest = ModelManifest(
        ModelManifestId("manifest"),
        1,
        spacecraft.configuration_id,
        numerical.configuration_id,
        environment.environment_id,
        flight_rules.flight_rules_id,
        scenario.scenario_id,
        world.world_id,
        controller_id,
    )
    inputs = SimulationInputs(
        spacecraft,
        numerical,
        environment,
        flight_rules,
        scenario,
        world,
        manifest,
    )
    return SimulationContext(
        0,
        inputs,
        _state() if state is None else state,
        GroundKnowledgeState(None, ()),
        GroundDataDeliveryState((), ()),
        MissionState((), (), (), None, (), ()),
        ControllerState(controller_id, None, 0),
        Diagnostics(0),
    )


def test_d1_dataclasses_have_exact_required_fields_and_mutability() -> None:
    expected = {
        BatteryDegradationState: (
            "usable_capacity_retention",
            "cumulative_energy_throughput_wh",
        ),
        SolarDegradationState: ("generation_retention",),
        DegradationState: ("battery", "solar"),
        DegradationConfig: (
            "configuration_id",
            "initial_battery_usable_capacity_retention",
            "initial_solar_generation_retention",
            "initial_battery_energy_throughput_wh",
            "battery_ageing_model",
        ),
        BatteryDegradationStateSnapshot: (
            "usable_capacity_retention",
            "cumulative_energy_throughput_wh",
        ),
        SolarDegradationStateSnapshot: ("generation_retention",),
        DegradationStateSnapshot: ("battery", "solar"),
    }
    for class_type, names in expected.items():
        assert tuple(field.name for field in fields(class_type)) == names
        for field in fields(class_type):
            assert field.default is MISSING
            assert field.default_factory is MISSING

    state = BatteryDegradationState(0.9, 2.0)
    assert not hasattr(state, "__dict__")
    state.usable_capacity_retention = 0.8
    assert state.usable_capacity_retention == 0.8
    config = _degradation_config()
    assert not hasattr(config, "__dict__")
    with pytest.raises(FrozenInstanceError):
        config.configuration_id = SubsystemConfigurationId("changed")


@pytest.mark.parametrize(
    ("value", "error_type"),
    (
        (0.0, ValueError),
        (-0.1, ValueError),
        (1.01, ValueError),
        (True, TypeError),
        ("1", TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ),
)
def test_retention_state_rejects_invalid_values(value, error_type) -> None:
    with pytest.raises(error_type):
        BatteryDegradationState(value, 0.0)
    with pytest.raises(error_type):
        SolarDegradationState(value)


@pytest.mark.parametrize(
    ("value", "error_type"),
    (
        (-0.1, ValueError),
        (True, TypeError),
        ("0", TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ),
)
def test_throughput_state_rejects_invalid_values(value, error_type) -> None:
    with pytest.raises(error_type):
        BatteryDegradationState(1.0, value)


def test_degradation_config_owns_exact_parameter_contracts_and_bounds() -> None:
    config = _degradation_config(
        battery_retention=np.float64(0.95),
        solar_retention=np.float64(0.96),
        throughput_wh=np.int64(4),
    )
    assert config.initial_battery_usable_capacity_retention.units == "1"
    assert config.initial_solar_generation_retention.units == "1"
    assert config.initial_battery_energy_throughput_wh.units == "Wh"
    with pytest.raises(ValueError, match="ParameterId"):
        replace(
            config,
            initial_solar_generation_retention=_parameter("wrong", "1", 1.0),
        )
    with pytest.raises(ValueError, match="units"):
        replace(
            config,
            initial_battery_energy_throughput_wh=_parameter(
                "degradation.battery.initial-energy-throughput", "J", 0.0
            ),
        )
    with pytest.raises(ValueError):
        _degradation_config(battery_retention=0.0)
    with pytest.raises(ValueError):
        _degradation_config(solar_retention=1.01)
    with pytest.raises(ValueError):
        _degradation_config(throughput_wh=-1.0)


def test_spacecraft_aggregates_require_degradation_and_unique_config_id() -> None:
    assert tuple(field.name for field in fields(SpacecraftState)) == (
        "battery",
        "propulsion",
        "thermal",
        "degradation",
        "onboard",
        "data_storage",
    )
    assert tuple(field.name for field in fields(SpacecraftConfiguration)) == (
        "configuration_id",
        "label",
        "schema_version",
        "eps",
        "payload",
        "storage",
        "communications",
        "adcs",
        "thermal",
        "degradation",
        "propulsion",
        "obc",
    )
    with pytest.raises(TypeError, match="degradation"):
        replace(_state(), degradation=object())
    with pytest.raises(TypeError, match="degradation"):
        replace(_spacecraft_config(), degradation=object())
    with pytest.raises(ValueError, match="unique"):
        _spacecraft_config(
            _degradation_config(configuration_id="propulsion")
        )


def test_context_revalidates_truth_but_does_not_equal_configured_initials() -> None:
    context = _context(
        state=_state(0.71, 0.63, 9000.0),
        degradation_config=_degradation_config(
            battery_retention=0.99,
            solar_retention=0.98,
            throughput_wh=10.0,
        ),
    )
    assert context.spacecraft_state.degradation.battery == (
        BatteryDegradationState(0.71, 9000.0)
    )
    object.__setattr__(
        context.spacecraft_state.degradation.solar,
        "generation_retention",
        0.0,
    )
    with pytest.raises(ValueError):
        SimulationContext(
            context.simulation_time_seconds,
            context.inputs,
            context.spacecraft_state,
            context.ground_knowledge_state,
            context.ground_data_delivery_state,
            context.mission_state,
            context.controller_state,
            context.diagnostics,
        )


def test_schema_five_round_trip_preserves_numpy_truth_and_fresh_identity() -> None:
    context = _context(
        state=_state(
            np.float64(0.91),
            np.float64(0.87),
            np.int64(1234),
        )
    )
    checkpoint = CheckpointState.from_context(context)
    payload = checkpoint.to_dict()
    degradation_payload = payload["spacecraft"]["degradation"]
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    assert payload["schema_version"] == 5
    assert degradation_payload == {
        "battery": {
            "usable_capacity_retention": 0.91,
            "cumulative_energy_throughput_wh": 1234,
        },
        "solar": {"generation_retention": 0.87},
    }
    encoded = json.dumps(payload, allow_nan=False)
    parsed = CheckpointState.from_dict(json.loads(encoded))
    restored = parsed.restore(context.inputs)
    assert restored.spacecraft_state.degradation == (
        context.spacecraft_state.degradation
    )
    assert restored.spacecraft_state.degradation is not (
        context.spacecraft_state.degradation
    )
    assert restored.spacecraft_state.degradation.battery is not (
        context.spacecraft_state.degradation.battery
    )
    assert restored.spacecraft_state.degradation.solar is not (
        context.spacecraft_state.degradation.solar
    )


def test_previous_schema_two_is_rejected_without_default_or_migration() -> None:
    payload = CheckpointState.from_context(_context()).to_dict()
    payload["schema_version"] = 2
    payload["spacecraft"].pop("degradation")
    with pytest.raises(ValueError, match="schema_version 2; expected 5"):
        CheckpointState.from_dict(payload)


def test_engine_transaction_copies_but_does_not_evolve_degradation() -> None:
    context = _context()
    before = deepcopy(context.spacecraft_state.degradation)
    original_object = context.spacecraft_state.degradation
    telemetry_before = context.ground_knowledge_state.latest_telemetry
    SimulationEngine().step(context)
    assert context.spacecraft_state.degradation == before
    assert context.spacecraft_state.degradation is not original_object
    assert context.ground_knowledge_state.latest_telemetry is telemetry_before


def test_degradation_state_stays_out_of_low_level_eps_and_telemetry() -> None:
    state_source = PRODUCTION_PATHS["state.py"].read_text(encoding="utf-8")
    config_source = PRODUCTION_PATHS["configuration.py"].read_text(
        encoding="utf-8"
    )
    for name in ("eps.py", "solar.py"):
        source = PRODUCTION_PATHS[name].read_text(encoding="utf-8")
        assert "DegradationState" not in source
        assert "usable_capacity_retention" not in source
        assert "generation_retention" not in source
    eps_system_source = PRODUCTION_PATHS["eps_system.py"].read_text(
        encoding="utf-8"
    )
    assert "DegradationState" not in eps_system_source
    assert "usable_capacity_retention" not in eps_system_source
    prohibited = {
        "cycle_count",
        "remaining_useful_life",
        "arrhenius",
        "degradation_rate",
        "capacity_fade_rate",
    }
    identifiers = set()
    for source, path in (
        (state_source, PRODUCTION_PATHS["state.py"]),
        (config_source, PRODUCTION_PATHS["configuration.py"]),
    ):
        tree = ast.parse(source, filename=str(path))
        identifiers |= {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        identifiers |= {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
    assert identifiers.isdisjoint(prohibited)
    assert tuple(field.name for field in fields(TelemetrySnapshot)) == (
        "snapshot_id",
        "sampled_at_seconds",
        "received_at_seconds",
        "battery_energy_wh",
        "delta_v_remaining_m_per_s",
        "operational_mode",
    )

    context = _context(state=_state(0.1, 0.1, 50_000.0))
    battery = compute_battery_transition(
        BatteryState(990.0),
        context.inputs.spacecraft_configuration.eps.battery,
        generation_w=100.0,
        load_w=0.0,
        dt_seconds=3600,
    )
    solar = compute_solar_generation(
        context.inputs.spacecraft_configuration.eps.solar_array,
        sunlit=True,
        incidence_angle_deg=0.0,
    )
    assert battery.end_energy_wh == 1000.0
    assert solar.generation_w == 200.0


def test_d1_decisions_sources_and_exports_are_exact() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    for number in range(108, 113):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D107 ") < decisions.index("## D108 ")
    s003 = sources.partition("### S003 ")[2].partition("### S004 ")[0]
    s009 = sources.partition("### S009 ")[2]
    assert "E_usable_max(t) = E_nominal * r_capacity(t)" in s003
    assert "P_solar_capability(t) = P_nominal * r_solar(t)" in s003
    assert "do not modify V5.1 EPS or solar output" in s003
    assert "cumulative battery energy" in s009
    assert "throughput" in s009
    assert "freezes no real spacecraft degradation value or rate" in s009

    from ops_sim.v5 import checkpoint, configuration, state

    assert "DegradationConfig" in configuration.__all__
    assert state.__all__ == [
        "BatteryDegradationState",
        "BatteryState",
        "DataStorageState",
        "DegradationState",
        "FDIRState",
        "OnboardOperationsState",
        "OperationalMode",
        "PropulsionState",
        "SpacecraftState",
        "SolarDegradationState",
        "ThermalNodeState",
        "ThermalState",
    ]
    assert "BatteryDegradationStateSnapshot" in checkpoint.__all__
    assert "DataStorageStateSnapshot" in checkpoint.__all__
    assert "DegradationStateSnapshot" in checkpoint.__all__
    assert "SolarDegradationStateSnapshot" in checkpoint.__all__
