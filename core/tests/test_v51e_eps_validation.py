"""Focused tests for V5.1E observable EPS conservation accounting."""

import ast
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from inspect import Parameter, signature
from pathlib import Path

import pytest

from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.checkpoint import CheckpointState
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
from ops_sim.v5.engine import STEP_PHASE_ORDER, SimulationEngine, StepResult
from ops_sim.v5.eps import BatteryTransition
from ops_sim.v5.eps_system import (
    EPSIntervalInputs,
    EPSIntervalResult,
    compute_eps_interval_transition,
)
from ops_sim.v5.eps_validation import (
    EPSConservationReport,
    compute_eps_conservation_report,
)
from ops_sim.v5.ids import (
    ADCSSlewAnchorId,
    AuthorityId,
    CommandId,
    ControllerId,
    DataProductId,
    EnvironmentId,
    FlightRulesId,
    MissionRequestId,
    ModelManifestId,
    NumericalConfigId,
    ParameterId,
    PlanId,
    ScenarioId,
    SpacecraftConfigurationId,
    SubsystemConfigurationId,
    TelemetrySnapshotId,
    ThermalNodeId,
    WorldEventId,
    WorldId,
)
from ops_sim.v5.knowledge import GroundKnowledgeState, TelemetrySnapshot
from ops_sim.v5.manifest import ModelManifest
from ops_sim.v5.mission import MissionState
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload_config import OpticalAcquisitionConfig
from ops_sim.v5.power_loads import PowerLoadBreakdown, compose_power_load
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
from ops_sim.v5.solar import SolarGenerationResult
from ops_sim.v5.state import (
    BatteryDegradationState,
    BatteryState,
    DataStorageState,
    DegradationState,
    FDIRState,
    OnboardOperationsState,
    OperationalMode,
    PropulsionState,
    SpacecraftState,
    SolarDegradationState,
    ThermalNodeState,
    ThermalState,
)
from ops_sim.v5.thermal_config import ThermalNetworkConfig, ThermalNodeConfig
from ops_sim.v5.world import CommonWorld


ROOT = Path(__file__).resolve().parents[1]
EPS_VALIDATION_PATH = ROOT / "ops_sim" / "v5" / "eps_validation.py"
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"

REPORT_FIELDS = (
    "dt_seconds",
    "generation_energy_wh",
    "requested_load_energy_wh",
    "served_load_energy_wh",
    "unmet_load_energy_wh",
    "charge_input_energy_wh",
    "discharge_output_energy_wh",
    "curtailed_generation_energy_wh",
    "conversion_loss_wh",
    "battery_energy_change_wh",
    "generation_link_residual_w",
    "load_link_residual_w",
    "bus_energy_residual_wh",
    "load_service_residual_wh",
    "battery_energy_residual_wh",
)

NONNEGATIVE_ENERGY_FIELDS = (
    "generation_energy_wh",
    "requested_load_energy_wh",
    "served_load_energy_wh",
    "unmet_load_energy_wh",
    "charge_input_energy_wh",
    "discharge_output_energy_wh",
    "curtailed_generation_energy_wh",
    "conversion_loss_wh",
)

SIGNED_FIELDS = (
    "battery_energy_change_wh",
    "generation_link_residual_w",
    "load_link_residual_w",
    "bus_energy_residual_wh",
    "load_service_residual_wh",
    "battery_energy_residual_wh",
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


def _thermal_network() -> ThermalNetworkConfig:
    def node(node_name: str) -> ThermalNodeConfig:
        prefix = f"thermal.node.{node_name}"
        return ThermalNodeConfig(
            ThermalNodeId(node_name),
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

    nodes = tuple(node(name) for name in ("bus", "battery", "payload"))
    return ThermalNetworkConfig(
        nodes,
        (),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("payload"),
    )


def _thermal_state() -> ThermalState:
    return ThermalState(
        (
            ThermalNodeState(ThermalNodeId("bus"), 300.0),
            ThermalNodeState(ThermalNodeId("battery"), 295.0),
            ThermalNodeState(ThermalNodeId("payload"), 290.0),
        )
    )


def _spacecraft_configuration(
    *,
    nominal_energy_wh: float = 2000.0,
    charge_efficiency: float = 1.0,
    discharge_efficiency: float = 1.0,
    max_charge_input_power_w: float = 1000.0,
    max_discharge_output_power_w: float = 1000.0,
    nominal_generation_w: float = 1000.0,
) -> SpacecraftConfiguration:
    return SpacecraftConfiguration(
        SpacecraftConfigurationId("reference-optical"),
        "Synthetic Optical Reference",
        1,
        EPSConfig(
            SubsystemConfigurationId("eps"),
            BatteryConfig(
                SubsystemConfigurationId("battery"),
                _parameter(
                    "eps.battery.nominal-energy",
                    "Wh",
                    nominal_energy_wh,
                ),
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
            ),
            SolarArrayConfig(
                SubsystemConfigurationId("solar-array"),
                _parameter(
                    "eps.solar-array.nominal-generation",
                    "W",
                    nominal_generation_w,
                ),
            ),
        ),
        PayloadConfig(
            SubsystemConfigurationId("payload"),
            PayloadFamily.OPTICAL_EO,
            (PayloadMode.PANCHROMATIC, PayloadMode.MULTISPECTRAL),
            _optical_acquisition(),
        ),
        StorageConfig(
            SubsystemConfigurationId("storage"),
            _parameter("storage.usable-capacity", "GB", 80.0),
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
        ThermalConfig(
            SubsystemConfigurationId("thermal"),
            _thermal_network(),
        ),
        DegradationConfig(
            SubsystemConfigurationId("degradation"),
            _parameter(
                "degradation.battery.initial-usable-capacity-retention",
                "1", 1.0,
            ),
            _parameter(
                "degradation.solar.initial-generation-retention", "1", 1.0
            ),
            _parameter(
                "degradation.battery.initial-energy-throughput", "Wh", 0.0
            ),
            _zero_damage_ageing_model(),
        ),
        PropulsionConfig(
            SubsystemConfigurationId("propulsion"),
            _parameter("propulsion.initial-delta-v", "m/s", 12.0),
        ),
        OBCConfig(SubsystemConfigurationId("obc")),
    )


def _simulation_inputs(
    dt_seconds: int,
    horizon_seconds: int,
    spacecraft: SpacecraftConfiguration,
) -> SimulationInputs:
    numerical = NumericalConfig(
        NumericalConfigId(f"step-{dt_seconds}"),
        dt_seconds,
        1,
        dt_seconds,
    )
    environment = EnvironmentConfig(EnvironmentId("level1-environment"))
    flight_rules = FlightRulesConfig(
        FlightRulesId("primary-flight-rules")
    )
    scenario = ScenarioConfig(ScenarioId("nominal-world"))
    world = CommonWorld(
        WorldId("world-0001"),
        scenario.scenario_id,
        horizon_seconds,
        (WorldEventId("event-0001"),),
    )
    manifest = ModelManifest(
        ModelManifestId("manifest-0001"),
        1,
        spacecraft.configuration_id,
        numerical.configuration_id,
        environment.environment_id,
        flight_rules.flight_rules_id,
        scenario.scenario_id,
        world.world_id,
        ControllerId("rolling-horizon"),
    )
    return SimulationInputs(
        spacecraft,
        numerical,
        environment,
        flight_rules,
        scenario,
        world,
        manifest,
    )


def _context(
    *,
    dt_seconds: int = 300,
    horizon_seconds: int = 3600,
    battery_energy_wh: float = 1000.0,
    telemetry_energy_wh: float = 1000.0,
    spacecraft: SpacecraftConfiguration | None = None,
) -> SimulationContext:
    spacecraft = spacecraft or _spacecraft_configuration()
    inputs = _simulation_inputs(dt_seconds, horizon_seconds, spacecraft)
    return SimulationContext(
        0,
        inputs,
        SpacecraftState(
            BatteryState(battery_energy_wh),
            PropulsionState(11.0),
            _thermal_state(),
            DegradationState(
                BatteryDegradationState(1.0, 0.0),
                SolarDegradationState(1.0),
            ),
            OnboardOperationsState(
                OperationalMode.STANDBY,
                FDIRState.NORMAL,
                PlanId("plan-0001"),
                AuthorityId("ground-authority-0001"),
                0,
                0,
            ),
            DataStorageState(()),
        ),
        GroundKnowledgeState(
            TelemetrySnapshot(
                TelemetrySnapshotId("snapshot-0001"),
                0,
                0,
                telemetry_energy_wh,
                11.0,
                OperationalMode.STANDBY,
            ),
            (WorldEventId("event-0001"),),
        ),
        GroundDataDeliveryState((), ()),
        MissionState(
            (MissionRequestId("request-0001"),),
            (MissionRequestId("request-0002"),),
            (DataProductId("product-0001"),),
            PlanId("plan-0001"),
            (CommandId("command-0001"),),
            (WorldEventId("event-0001"),),
        ),
        ControllerState(
            inputs.model_manifest.controller_id,
            PlanId("plan-0001"),
            2,
        ),
        Diagnostics(0),
    )


def _loads(base_bus_w: float = 100.0) -> PowerLoadBreakdown:
    return compose_power_load(
        base_bus_w=base_bus_w,
        obc_w=50.0,
        adcs_w=50.0,
        payload_w=100.0,
        communications_w=0.0,
        thermal_control_w=0.0,
        propulsion_w=0.0,
    )


def _eps_inputs(
    *,
    sunlit: bool = True,
    incidence_angle_deg: float = 60.0,
    load_breakdown: PowerLoadBreakdown | None = None,
) -> EPSIntervalInputs:
    return EPSIntervalInputs(
        sunlit,
        incidence_angle_deg,
        _loads() if load_breakdown is None else load_breakdown,
    )


def _pure_result(
    *,
    state_energy_wh: float = 1000.0,
    spacecraft: SpacecraftConfiguration | None = None,
    eps_inputs: EPSIntervalInputs | None = None,
    dt_seconds: int = 300,
) -> EPSIntervalResult:
    spacecraft = spacecraft or _spacecraft_configuration()
    return compute_eps_interval_transition(
        BatteryState(state_energy_wh),
        spacecraft.eps,
        eps_inputs or _eps_inputs(),
        dt_seconds=dt_seconds,
    )


def _report(**changes: object) -> EPSConservationReport:
    values: dict[str, object] = {
        "dt_seconds": 300,
        "generation_energy_wh": 10.0,
        "requested_load_energy_wh": 8.0,
        "served_load_energy_wh": 8.0,
        "unmet_load_energy_wh": 0.0,
        "charge_input_energy_wh": 2.0,
        "discharge_output_energy_wh": 0.0,
        "curtailed_generation_energy_wh": 0.0,
        "conversion_loss_wh": 0.0,
        "battery_energy_change_wh": 2.0,
        "generation_link_residual_w": 0.0,
        "load_link_residual_w": 0.0,
        "bus_energy_residual_wh": 0.0,
        "load_service_residual_wh": 0.0,
        "battery_energy_residual_wh": 0.0,
    }
    values.update(changes)
    return EPSConservationReport(**values)


def _assert_conserved(report: EPSConservationReport) -> None:
    assert report.is_within_tolerance(
        1.0e-12,
        absolute_power_tolerance_w=1.0e-12,
    )
    assert report.max_abs_energy_residual_wh <= 1.0e-12
    assert report.max_abs_power_link_residual_w <= 1.0e-12


def test_report_has_exact_frozen_slotted_required_structure() -> None:
    report = _report()

    assert tuple(field.name for field in fields(EPSConservationReport)) == (
        REPORT_FIELDS
    )
    assert not hasattr(report, "__dict__")
    assert isinstance(hash(report), int)
    for field in fields(EPSConservationReport):
        assert field.default is MISSING
        assert field.default_factory is MISSING
    with pytest.raises(FrozenInstanceError):
        report.dt_seconds = 60
    with pytest.raises(TypeError):
        EPSConservationReport()


def test_report_derived_properties_are_not_stored_fields() -> None:
    report = _report(
        generation_link_residual_w=-2.0,
        load_link_residual_w=3.0,
        bus_energy_residual_wh=-4.0,
        load_service_residual_wh=2.0,
        battery_energy_residual_wh=1.0,
    )

    assert report.max_abs_power_link_residual_w == 3.0
    assert report.max_abs_energy_residual_wh == 4.0
    assert {
        "max_abs_power_link_residual_w",
        "max_abs_energy_residual_wh",
    }.isdisjoint(field.name for field in fields(EPSConservationReport))


def test_report_requires_positive_exact_integer_duration() -> None:
    for invalid in (True, 1.0, "300"):
        with pytest.raises(TypeError):
            _report(dt_seconds=invalid)
    for invalid in (0, -1):
        with pytest.raises(ValueError):
            _report(dt_seconds=invalid)


@pytest.mark.parametrize("field_name", NONNEGATIVE_ENERGY_FIELDS)
def test_report_nonnegative_energy_fields_are_finite_reals(field_name) -> None:
    assert getattr(_report(**{field_name: 1}), field_name) == 1
    for invalid in (True, "1"):
        with pytest.raises(TypeError):
            _report(**{field_name: invalid})
    for invalid in (-0.001, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            _report(**{field_name: invalid})


@pytest.mark.parametrize("field_name", SIGNED_FIELDS)
def test_report_signed_fields_accept_negative_finite_reals(field_name) -> None:
    assert getattr(_report(**{field_name: -1}), field_name) == -1
    for invalid in (True, "1"):
        with pytest.raises(TypeError):
            _report(**{field_name: invalid})
    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            _report(**{field_name: invalid})


def test_tolerance_interface_has_no_defaults_and_validates_both_values() -> None:
    parameters = signature(
        EPSConservationReport.is_within_tolerance
    ).parameters

    assert tuple(parameters) == (
        "self",
        "absolute_energy_tolerance_wh",
        "absolute_power_tolerance_w",
    )
    assert parameters["absolute_energy_tolerance_wh"].default is (
        Parameter.empty
    )
    assert parameters["absolute_power_tolerance_w"].kind is (
        Parameter.KEYWORD_ONLY
    )
    assert parameters["absolute_power_tolerance_w"].default is Parameter.empty

    report = _report()
    for invalid in (True, "1"):
        with pytest.raises(TypeError):
            report.is_within_tolerance(
                invalid,
                absolute_power_tolerance_w=0.0,
            )
        with pytest.raises(TypeError):
            report.is_within_tolerance(
                0.0,
                absolute_power_tolerance_w=invalid,
            )
    for invalid in (-0.001, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            report.is_within_tolerance(
                invalid,
                absolute_power_tolerance_w=0.0,
            )
        with pytest.raises(ValueError):
            report.is_within_tolerance(
                0.0,
                absolute_power_tolerance_w=invalid,
            )


def test_tolerance_checks_every_residual_inclusively() -> None:
    report = _report(
        generation_link_residual_w=-0.2,
        load_link_residual_w=0.3,
        bus_energy_residual_wh=-0.4,
        load_service_residual_wh=0.2,
        battery_energy_residual_wh=0.1,
    )

    assert report.is_within_tolerance(
        0.4,
        absolute_power_tolerance_w=0.3,
    )
    assert not report.is_within_tolerance(
        0.399,
        absolute_power_tolerance_w=0.3,
    )
    assert not report.is_within_tolerance(
        0.4,
        absolute_power_tolerance_w=0.299,
    )


def test_compute_report_requires_exact_eps_result_type() -> None:
    with pytest.raises(TypeError, match="result must be an EPSIntervalResult"):
        compute_eps_conservation_report(object())


def test_charging_hand_calculation_reports_complete_energy_ledger() -> None:
    report = compute_eps_conservation_report(_pure_result())

    assert report.dt_seconds == 300
    assert report.generation_energy_wh == pytest.approx(500.0 / 12.0)
    assert report.requested_load_energy_wh == pytest.approx(25.0)
    assert report.served_load_energy_wh == pytest.approx(25.0)
    assert report.unmet_load_energy_wh == 0.0
    assert report.charge_input_energy_wh == pytest.approx(200.0 / 12.0)
    assert report.discharge_output_energy_wh == 0.0
    assert report.curtailed_generation_energy_wh == 0.0
    assert report.conversion_loss_wh == 0.0
    assert report.battery_energy_change_wh == pytest.approx(200.0 / 12.0)
    _assert_conserved(report)


def test_eclipse_discharging_hand_calculation_reports_complete_ledger() -> None:
    report = compute_eps_conservation_report(
        _pure_result(eps_inputs=_eps_inputs(sunlit=False))
    )

    assert report.generation_energy_wh == 0.0
    assert report.requested_load_energy_wh == pytest.approx(25.0)
    assert report.served_load_energy_wh == pytest.approx(25.0)
    assert report.discharge_output_energy_wh == pytest.approx(25.0)
    assert report.battery_energy_change_wh == pytest.approx(-25.0)
    assert report.unmet_load_energy_wh == 0.0
    assert report.charge_input_energy_wh == 0.0
    _assert_conserved(report)


@pytest.mark.parametrize(
    "spacecraft,eps_inputs,expected_change,expected_loss",
    (
        (
            _spacecraft_configuration(charge_efficiency=0.8),
            _eps_inputs(),
            200.0 / 12.0 * 0.8,
            200.0 / 12.0 * 0.2,
        ),
        (
            _spacecraft_configuration(discharge_efficiency=0.8),
            _eps_inputs(sunlit=False),
            -(300.0 / 0.8) / 12.0,
            (300.0 / 0.8 - 300.0) / 12.0,
        ),
    ),
)
def test_lossy_charge_and_discharge_report_conversion_accounting(
    spacecraft,
    eps_inputs,
    expected_change,
    expected_loss,
) -> None:
    report = compute_eps_conservation_report(
        _pure_result(spacecraft=spacecraft, eps_inputs=eps_inputs)
    )

    assert report.battery_energy_change_wh == pytest.approx(expected_change)
    assert report.conversion_loss_wh == pytest.approx(expected_loss)
    _assert_conserved(report)


@pytest.mark.parametrize(
    "state_energy_wh,spacecraft,eps_inputs,expected_curtail,expected_unmet",
    (
        (2000.0, _spacecraft_configuration(), _eps_inputs(), 200.0 / 12.0, 0.0),
        (0.0, _spacecraft_configuration(), _eps_inputs(sunlit=False), 0.0, 25.0),
        (
            1000.0,
            _spacecraft_configuration(max_charge_input_power_w=100.0),
            _eps_inputs(),
            100.0 / 12.0,
            0.0,
        ),
        (
            1000.0,
            _spacecraft_configuration(max_discharge_output_power_w=100.0),
            _eps_inputs(sunlit=False),
            0.0,
            200.0 / 12.0,
        ),
    ),
)
def test_capacity_and_power_boundaries_remain_explicit_and_conserved(
    state_energy_wh,
    spacecraft,
    eps_inputs,
    expected_curtail,
    expected_unmet,
) -> None:
    report = compute_eps_conservation_report(
        _pure_result(
            state_energy_wh=state_energy_wh,
            spacecraft=spacecraft,
            eps_inputs=eps_inputs,
        )
    )

    assert report.curtailed_generation_energy_wh == pytest.approx(
        expected_curtail
    )
    assert report.unmet_load_energy_wh == pytest.approx(expected_unmet)
    _assert_conserved(report)


@pytest.mark.parametrize(
    "eps_inputs",
    (
        _eps_inputs(sunlit=True, incidence_angle_deg=90.0),
        _eps_inputs(sunlit=False, incidence_angle_deg=0.0),
    ),
)
def test_zero_generation_geometry_reports_exact_zero_and_conserves(
    eps_inputs,
) -> None:
    report = compute_eps_conservation_report(
        _pure_result(eps_inputs=eps_inputs)
    )

    assert report.generation_energy_wh == 0.0
    assert report.discharge_output_energy_wh == pytest.approx(25.0)
    _assert_conserved(report)


def test_inconsistent_nested_result_exposes_link_and_conservation_residuals() -> None:
    inconsistent = EPSIntervalResult(
        SolarGenerationResult(1000.0, True, 0.0),
        _loads(),
        BatteryTransition(
            1000.0,
            1000.0,
            900.0,
            250.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            300,
        ),
    )

    report = compute_eps_conservation_report(inconsistent)

    assert report.generation_link_residual_w == -100.0
    assert report.load_link_residual_w == -50.0
    assert report.bus_energy_residual_wh == pytest.approx(750.0 / 12.0)
    assert report.load_service_residual_wh == pytest.approx(50.0 / 12.0)
    assert not report.is_within_tolerance(
        1.0,
        absolute_power_tolerance_w=1.0,
    )


def test_report_preserves_small_nonzero_residuals_without_correction() -> None:
    report = _report(bus_energy_residual_wh=1.0e-15)

    assert report.bus_energy_residual_wh == 1.0e-15
    assert report.max_abs_energy_residual_wh == 1.0e-15
    assert not report.is_within_tolerance(
        0.0,
        absolute_power_tolerance_w=0.0,
    )


def test_step_result_extends_legacy_shape_with_optional_exact_eps_result() -> None:
    legacy = StepResult(0, 300, 300, STEP_PHASE_ORDER)
    eps_result = _pure_result()
    observed = StepResult(0, 300, 300, STEP_PHASE_ORDER, eps_result)

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
    assert legacy.eps_result is None
    assert legacy.thermal_coupling_result is None
    assert legacy.battery_degradation_result is None
    assert legacy.solar_degradation_result is None
    assert legacy.eps_capability_result is None
    assert legacy.battery_capacity_reconciliation_result is None
    assert observed.eps_result is eps_result
    with pytest.raises(TypeError, match="eps_result"):
        StepResult(0, 300, 300, STEP_PHASE_ORDER, object())


class CapturingPhysicalResultEngine(SimulationEngine):
    __slots__ = ("captured",)

    def __init__(self) -> None:
        self.captured = None

    def _physical_integration(self, context, interval, eps_inputs):
        self.captured = super()._physical_integration(
            context,
            interval,
            eps_inputs,
        )
        return self.captured


def test_engine_exposes_the_actual_physical_integration_result_after_commit() -> None:
    context = _context()
    engine = CapturingPhysicalResultEngine()

    step_result = engine.step(context, eps_inputs=_eps_inputs())

    assert type(step_result.eps_result) is EPSIntervalResult
    assert step_result.eps_result is engine.captured.eps_result
    assert step_result.eps_capability_result is (
        engine.captured.eps_capability_result
    )
    assert step_result.eps_result.battery.start_energy_wh == 1000.0
    assert context.spacecraft_state.battery.energy_wh == pytest.approx(
        step_result.eps_result.battery.end_energy_wh
    )
    report = compute_eps_conservation_report(step_result.eps_result)
    _assert_conserved(report)


def test_no_eps_compatibility_step_reports_none() -> None:
    context = _context()

    result = SimulationEngine().step(context)

    assert result.eps_result is None
    assert context.spacecraft_state.battery.energy_wh == 1000.0
    assert context.simulation_time_seconds == 300
    assert context.diagnostics.completed_steps == 1


class FailAfterEPSIntegration(SimulationEngine):
    def _failure_capability_resolution(self, context, interval) -> None:
        assert context.spacecraft_state.battery.energy_wh != 1000.0
        raise RuntimeError("synthetic post-EPS failure")


def test_failed_transaction_exposes_no_success_result_and_rolls_back() -> None:
    context = _context()
    checkpoint = CheckpointState.from_context(context)
    domain_references = (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.data_storage,
        context.ground_knowledge_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )
    result = None

    with pytest.raises(RuntimeError, match="post-EPS"):
        result = FailAfterEPSIntegration().step(
            context,
            eps_inputs=_eps_inputs(),
        )

    assert result is None
    assert CheckpointState.from_context(context) == checkpoint
    current_references = (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.data_storage,
        context.ground_knowledge_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )
    assert all(
        current is original
        for current, original in zip(current_references, domain_references)
    )


def test_checkpoint_preserves_battery_truth_but_not_transient_eps_products() -> None:
    context = _context()
    result = SimulationEngine().step(context, eps_inputs=_eps_inputs())
    assert result.eps_result is not None
    report = compute_eps_conservation_report(result.eps_result)

    checkpoint = CheckpointState.from_context(context)
    payload = checkpoint.to_dict()
    restored = checkpoint.restore(context.inputs)

    assert checkpoint.spacecraft.battery_energy_wh == pytest.approx(
        result.eps_result.battery.end_energy_wh
    )
    assert restored == context
    assert not hasattr(restored, "eps_result")
    assert "eps_result" not in repr(payload)
    assert "EPSConservationReport" not in repr(payload)
    assert {
        "EPSIntervalResult",
        "EPSConservationReport",
    }.isdisjoint(str(field.type) for field in fields(CheckpointState))
    assert report not in tuple(
        getattr(checkpoint, field.name) for field in fields(CheckpointState)
    )


def test_observability_does_not_refresh_ground_telemetry() -> None:
    context = _context(telemetry_energy_wh=1000.0)
    knowledge_before = deepcopy(context.ground_knowledge_state)

    result = SimulationEngine().step(
        context,
        eps_inputs=_eps_inputs(sunlit=False),
    )

    assert result.eps_result is not None
    assert context.spacecraft_state.battery.energy_wh == pytest.approx(975.0)
    assert context.ground_knowledge_state == knowledge_before
    telemetry = context.ground_knowledge_state.latest_telemetry
    assert telemetry is not None
    assert telemetry.battery_energy_wh == 1000.0


def test_multistep_reports_reconcile_with_cumulative_battery_change() -> None:
    context = _context(horizon_seconds=900)
    forcings = (
        _eps_inputs(),
        _eps_inputs(sunlit=False),
        _eps_inputs(sunlit=True, incidence_angle_deg=0.0),
    )
    start_energy_wh = context.spacecraft_state.battery.energy_wh
    reports = []

    for forcing in forcings:
        step_result = SimulationEngine().step(context, eps_inputs=forcing)
        assert step_result.eps_result is not None
        report = compute_eps_conservation_report(step_result.eps_result)
        _assert_conserved(report)
        reports.append(report)

    assert sum(item.battery_energy_change_wh for item in reports) == (
        pytest.approx(
            context.spacecraft_state.battery.energy_wh - start_energy_wh
        )
    )
    assert context.simulation_time_seconds == 900
    assert context.diagnostics.completed_steps == 3


@pytest.mark.parametrize(
    "eps_inputs",
    (_eps_inputs(), _eps_inputs(sunlit=False)),
)
def test_one_hour_and_twelve_five_minute_ledgers_reconcile(eps_inputs) -> None:
    one_hour = _context(dt_seconds=3600, horizon_seconds=3600)
    sequential = _context(dt_seconds=300, horizon_seconds=3600)

    one_result = SimulationEngine().step(one_hour, eps_inputs=eps_inputs)
    assert one_result.eps_result is not None
    one_report = compute_eps_conservation_report(one_result.eps_result)
    sequential_reports = []
    for _ in range(12):
        result = SimulationEngine().step(sequential, eps_inputs=eps_inputs)
        assert result.eps_result is not None
        sequential_reports.append(
            compute_eps_conservation_report(result.eps_result)
        )

    for field_name in (
        "generation_energy_wh",
        "requested_load_energy_wh",
        "served_load_energy_wh",
        "unmet_load_energy_wh",
        "charge_input_energy_wh",
        "discharge_output_energy_wh",
        "curtailed_generation_energy_wh",
        "conversion_loss_wh",
        "battery_energy_change_wh",
    ):
        assert sum(
            getattr(report, field_name) for report in sequential_reports
        ) == pytest.approx(getattr(one_report, field_name))
    _assert_conserved(one_report)
    for report in sequential_reports:
        _assert_conserved(report)
    assert sequential.spacecraft_state.battery.energy_wh == pytest.approx(
        one_hour.spacecraft_state.battery.energy_wh
    )


@pytest.mark.parametrize(
    "state_energy_wh,eps_inputs",
    (
        (1000.0, _eps_inputs()),
        (1000.0, _eps_inputs(sunlit=False)),
        (2000.0, _eps_inputs()),
        (0.0, _eps_inputs(sunlit=False)),
    ),
)
def test_engine_result_exactly_matches_pure_composite_for_all_outcomes(
    state_energy_wh,
    eps_inputs,
) -> None:
    context = _context(battery_energy_wh=state_energy_wh)
    pure = compute_eps_interval_transition(
        context.spacecraft_state.battery,
        context.inputs.spacecraft_configuration.eps,
        eps_inputs,
        dt_seconds=300,
    )

    step_result = SimulationEngine().step(context, eps_inputs=eps_inputs)

    assert step_result.eps_result == pure
    assert step_result.eps_result is not None
    assert compute_eps_conservation_report(step_result.eps_result) == (
        compute_eps_conservation_report(pure)
    )


def test_eps_validation_module_is_pure_and_defines_exact_exports() -> None:
    from ops_sim.v5 import eps_validation

    assert eps_validation.__all__ == [
        "EPSConservationReport",
        "compute_eps_conservation_report",
    ]
    tree = ast.parse(
        EPS_VALIDATION_PATH.read_text(encoding="utf-8"),
        filename=str(EPS_VALIDATION_PATH),
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
        (1, "eps_system", ("EPSIntervalResult",)),
    }
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    prohibited_names = {
        "SimulationEngine",
        "SimulationContext",
        "BatteryState",
        "OperationalMode",
        "FDIRState",
        "CheckpointState",
        "DEFAULT_CONFIG",
        "random",
        "round",
    }
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert identifiers.isdisjoint(prohibited_names)


def test_engine_observability_path_uses_one_composite_call_and_no_storage() -> None:
    tree = ast.parse(
        ENGINE_PATH.read_text(encoding="utf-8"),
        filename=str(ENGINE_PATH),
    )
    composite_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "compute_eps_interval_transition"
    ]
    engine_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SimulationEngine"
    )
    assigned_instance_attributes = {
        target.attr
        for node in ast.walk(engine_class)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
        for target in (
            node.targets
            if isinstance(node, ast.Assign)
            else (node.target,)
        )
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    }

    assert len(composite_calls) == 1
    assert SimulationEngine.__slots__ == ()
    assert "eps_result" not in assigned_instance_attributes
