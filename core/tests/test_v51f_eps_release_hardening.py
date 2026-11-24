"""Release-hardening regressions for V5.1F EPS boundaries and transactions."""

import ast
from copy import deepcopy
from dataclasses import fields, replace
from math import isfinite, nextafter
from pathlib import Path
import subprocess

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
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.eps import BatteryTransition, compute_battery_transition
from ops_sim.v5.eps_system import EPSIntervalInputs, EPSIntervalResult
from ops_sim.v5.eps_validation import compute_eps_conservation_report
from ops_sim.v5.ids import (
    ADCSSlewAnchorId,
    AuthorityId,
    ControllerId,
    EnvironmentId,
    FlightRulesId,
    ModelManifestId,
    NumericalConfigId,
    ParameterId,
    PlanId,
    ScenarioId,
    SpacecraftConfigurationId,
    SubsystemConfigurationId,
    TelemetrySnapshotId,
    ThermalNodeId,
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
EPS_PATH = ROOT / "ops_sim" / "v5" / "eps.py"
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
V51F_COMMIT = "4c1fe8357abe69762df54c88aa2c8b4af3930f76"
SMALLEST_POSITIVE_FLOAT = float.fromhex("0x0.0000000000001p-1022")


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


def _battery_config(
    *,
    capacity_wh: float = 2000.0,
    charge_efficiency: float = 0.9,
    discharge_efficiency: float = 0.9,
    max_charge_input_power_w: float = 1000.0,
    max_discharge_output_power_w: float = 1000.0,
) -> BatteryConfig:
    return BatteryConfig(
        SubsystemConfigurationId("battery-hardening"),
        _parameter("eps.battery.nominal-energy", "Wh", capacity_wh),
        _parameter("eps.battery.charge-efficiency", "1", charge_efficiency),
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


def _spacecraft_configuration(
    *,
    capacity_wh: float = 2000.0,
    charge_efficiency: float = 0.9,
    discharge_efficiency: float = 0.9,
    max_charge_input_power_w: float = 1000.0,
    max_discharge_output_power_w: float = 1000.0,
    nominal_generation_w: float = 1000.0,
) -> SpacecraftConfiguration:
    return SpacecraftConfiguration(
        SpacecraftConfigurationId("hardening-optical"),
        "Synthetic Hardening Optical Reference",
        1,
        EPSConfig(
            SubsystemConfigurationId("eps-hardening"),
            _battery_config(
                capacity_wh=capacity_wh,
                charge_efficiency=charge_efficiency,
                discharge_efficiency=discharge_efficiency,
                max_charge_input_power_w=max_charge_input_power_w,
                max_discharge_output_power_w=max_discharge_output_power_w,
            ),
            SolarArrayConfig(
                SubsystemConfigurationId("solar-hardening"),
                _parameter(
                    "eps.solar-array.nominal-generation",
                    "W",
                    nominal_generation_w,
                ),
            ),
        ),
        PayloadConfig(
            SubsystemConfigurationId("payload-hardening"),
            PayloadFamily.OPTICAL_EO,
            (PayloadMode.PANCHROMATIC, PayloadMode.MULTISPECTRAL),
            _optical_acquisition(),
        ),
        StorageConfig(
            SubsystemConfigurationId("storage-hardening"),
            _parameter("storage.usable-capacity", "GB", 80.0),
        ),
        CommunicationsConfig(
            SubsystemConfigurationId("communications-hardening"),
            _parameter(
                "communications.nominal-downlink-data-rate",
                "bit/s",
                1_000_000.0,
            ),
        ),
        ADCSConfig(
            SubsystemConfigurationId("adcs-hardening"), _agile_pointing()
        ),
        ThermalConfig(
            SubsystemConfigurationId("thermal-hardening"),
            _thermal_network(),
        ),
        DegradationConfig(
            SubsystemConfigurationId("degradation-hardening"),
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
            SubsystemConfigurationId("propulsion-hardening"),
            _parameter("propulsion.initial-delta-v", "m/s", 12.0),
        ),
        OBCConfig(SubsystemConfigurationId("obc-hardening")),
    )


def _simulation_inputs(
    spacecraft: SpacecraftConfiguration,
    *,
    dt_seconds: int = 300,
    horizon_seconds: int = 3600,
) -> SimulationInputs:
    numerical = NumericalConfig(
        NumericalConfigId(f"hardening-step-{dt_seconds}"),
        dt_seconds,
        1,
        dt_seconds,
    )
    environment = EnvironmentConfig(EnvironmentId("hardening-environment"))
    flight_rules = FlightRulesConfig(FlightRulesId("hardening-flight-rules"))
    scenario = ScenarioConfig(ScenarioId("hardening-scenario"))
    world = CommonWorld(
        WorldId("hardening-world"),
        scenario.scenario_id,
        horizon_seconds,
        (),
    )
    manifest = ModelManifest(
        ModelManifestId("hardening-manifest"),
        1,
        spacecraft.configuration_id,
        numerical.configuration_id,
        environment.environment_id,
        flight_rules.flight_rules_id,
        scenario.scenario_id,
        world.world_id,
        ControllerId("hardening-controller"),
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
    spacecraft: SpacecraftConfiguration | None = None,
    battery_energy_wh: float = 1000.0,
    dt_seconds: int = 300,
    horizon_seconds: int = 3600,
) -> SimulationContext:
    spacecraft = spacecraft or _spacecraft_configuration()
    inputs = _simulation_inputs(
        spacecraft,
        dt_seconds=dt_seconds,
        horizon_seconds=horizon_seconds,
    )
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
                PlanId("hardening-plan"),
                AuthorityId("hardening-authority"),
                0,
                None,
            ),
            DataStorageState(()),
        ),
        GroundKnowledgeState(
            TelemetrySnapshot(
                TelemetrySnapshotId("hardening-telemetry"),
                0,
                0,
                battery_energy_wh,
                11.0,
                OperationalMode.STANDBY,
            ),
            (),
        ),
        GroundDataDeliveryState((), ()),
        MissionState((), (), (), PlanId("hardening-plan"), (), ()),
        ControllerState(
            inputs.model_manifest.controller_id,
            PlanId("hardening-plan"),
            0,
        ),
        Diagnostics(0),
    )


def _loads(total_w: float) -> PowerLoadBreakdown:
    return compose_power_load(
        base_bus_w=total_w,
        obc_w=0.0,
        adcs_w=0.0,
        payload_w=0.0,
        communications_w=0.0,
        thermal_control_w=0.0,
        propulsion_w=0.0,
    )


def _assert_transition_invariants(
    transition: BatteryTransition,
    capacity_wh: float,
) -> None:
    assert 0.0 <= transition.end_energy_wh <= capacity_wh
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
        assert value >= 0.0


def _conservation_report(
    transition: BatteryTransition,
):
    if transition.generation_w == 0.0:
        solar = SolarGenerationResult(1.0, False, 0.0)
    else:
        solar = SolarGenerationResult(
            transition.generation_w,
            True,
            0.0,
        )
    result = EPSIntervalResult(
        solar,
        _loads(transition.load_w),
        transition,
    )
    return compute_eps_conservation_report(result)


def _assert_conserved(transition: BatteryTransition) -> None:
    report = _conservation_report(transition)
    assert report.generation_link_residual_w == 0.0
    assert report.load_link_residual_w == 0.0
    assert report.is_within_tolerance(
        1.0e-10,
        absolute_power_tolerance_w=0.0,
    )


def test_awkward_capacity_limiter_lands_exactly_and_follow_on_succeeds() -> None:
    capacity_wh = 15.663473633892588
    start_energy_wh = 3.909119746732411
    config = _battery_config(
        capacity_wh=capacity_wh,
        charge_efficiency=1.0,
        max_charge_input_power_w=200.0,
    )

    transition = compute_battery_transition(
        BatteryState(start_energy_wh),
        config,
        generation_w=200.0,
        load_w=0.0,
        dt_seconds=300,
    )

    room_wh = capacity_wh - start_energy_wh
    assert transition.end_energy_wh == capacity_wh
    assert transition.energy_change_wh == room_wh
    assert transition.charge_input_w == room_wh / (300.0 / 3600.0)
    _assert_transition_invariants(transition, capacity_wh)
    _assert_conserved(transition)
    report = _conservation_report(transition)
    independently_derived_residual_wh = transition.energy_change_wh - (
        transition.charge_input_w * (300.0 / 3600.0)
        - transition.conversion_loss_wh
    )
    assert report.battery_energy_residual_wh == (
        independently_derived_residual_wh
    )
    assert report.battery_energy_residual_wh != 0.0

    follow_on = compute_battery_transition(
        BatteryState(transition.end_energy_wh),
        config,
        generation_w=0.0,
        load_w=1.0,
        dt_seconds=7,
    )
    assert 0.0 < follow_on.end_energy_wh < capacity_wh
    _assert_transition_invariants(follow_on, capacity_wh)


def test_awkward_energy_limiter_lands_exactly_zero_and_follow_on_succeeds() -> None:
    start_energy_wh = 99.175148861098634
    config = _battery_config(
        capacity_wh=100.0,
        discharge_efficiency=1.0,
        max_discharge_output_power_w=2000.0,
    )

    transition = compute_battery_transition(
        BatteryState(start_energy_wh),
        config,
        generation_w=0.0,
        load_w=2000.0,
        dt_seconds=300,
    )

    assert transition.end_energy_wh == 0.0
    assert transition.energy_change_wh == -start_energy_wh
    assert transition.discharge_output_w == (
        start_energy_wh / (300.0 / 3600.0)
    )
    _assert_transition_invariants(transition, 100.0)
    _assert_conserved(transition)
    report = _conservation_report(transition)
    independently_derived_residual_wh = transition.energy_change_wh - (
        -transition.discharge_output_w * (300.0 / 3600.0)
        - transition.conversion_loss_wh
    )
    assert report.battery_energy_residual_wh == (
        independently_derived_residual_wh
    )
    assert report.battery_energy_residual_wh != 0.0

    follow_on = compute_battery_transition(
        BatteryState(transition.end_energy_wh),
        config,
        generation_w=1.0,
        load_w=0.0,
        dt_seconds=7,
    )
    assert follow_on.end_energy_wh > 0.0
    _assert_transition_invariants(follow_on, 100.0)


def test_near_boundary_rounding_does_not_overdraw_available_power() -> None:
    capacity_wh = 1.0
    start_energy_wh = nextafter(capacity_wh, 0.0)
    room_wh = capacity_wh - start_energy_wh
    available_charge_input_w = 0.75 * room_wh / (1.0 / 3600.0)
    config = _battery_config(
        capacity_wh=capacity_wh,
        charge_efficiency=1.0,
        max_charge_input_power_w=1.0,
    )

    transition = compute_battery_transition(
        BatteryState(start_energy_wh),
        config,
        generation_w=available_charge_input_w,
        load_w=0.0,
        dt_seconds=1,
    )

    assert transition.charge_input_w == available_charge_input_w
    assert transition.curtailed_generation_w == 0.0
    _assert_transition_invariants(transition, capacity_wh)
    _assert_conserved(transition)


def test_active_capacity_boundary_preserves_available_power_limit() -> None:
    capacity_wh = 1.162832979405414e-13
    start_energy_wh = 4.454825164341676e-14
    available_charge_input_w = 1.434700925942493e-11
    config = _battery_config(
        capacity_wh=capacity_wh,
        charge_efficiency=0.3,
        max_charge_input_power_w=1.0,
    )

    transition = compute_battery_transition(
        BatteryState(start_energy_wh),
        config,
        generation_w=available_charge_input_w,
        load_w=0.0,
        dt_seconds=60,
    )

    assert transition.end_energy_wh == capacity_wh
    assert transition.charge_input_w == available_charge_input_w
    assert transition.curtailed_generation_w == 0.0
    _assert_transition_invariants(transition, capacity_wh)
    _assert_conserved(transition)


def test_capacity_limited_engine_step_commits_exact_capacity() -> None:
    capacity_wh = 15.663473633892588
    spacecraft = _spacecraft_configuration(
        capacity_wh=capacity_wh,
        charge_efficiency=1.0,
        max_charge_input_power_w=200.0,
        nominal_generation_w=200.0,
    )
    context = _context(
        spacecraft=spacecraft,
        battery_energy_wh=3.909119746732411,
    )

    result = SimulationEngine().step(
        context,
        eps_inputs=EPSIntervalInputs(True, 0.0, _loads(0.0)),
    )

    assert result.eps_result is not None
    assert result.eps_result.battery.end_energy_wh == capacity_wh
    assert context.spacecraft_state.battery.energy_wh == capacity_wh
    assert CheckpointState.from_context(context).restore(context.inputs) == context


def test_partitioned_depletion_matches_long_interval_at_exact_zero() -> None:
    capacity_wh = 800.0
    config = _battery_config(
        capacity_wh=capacity_wh,
        discharge_efficiency=0.95,
        max_discharge_output_power_w=1000.0,
    )
    long_transition = compute_battery_transition(
        BatteryState(713.0),
        config,
        generation_w=0.0,
        load_w=1000.0,
        dt_seconds=3600,
    )

    energy_wh = 713.0
    for _ in range(3600):
        transition = compute_battery_transition(
            BatteryState(energy_wh),
            config,
            generation_w=0.0,
            load_w=1000.0,
            dt_seconds=1,
        )
        _assert_transition_invariants(transition, capacity_wh)
        energy_wh = transition.end_energy_wh

    assert long_transition.end_energy_wh == 0.0
    assert energy_wh == 0.0
    _assert_transition_invariants(long_transition, capacity_wh)
    _assert_conserved(long_transition)


def test_deterministic_awkward_boundary_grid_and_follow_on_transitions() -> None:
    capacities = (15.663473633892588, 61.9358720085285, 713.1250000000001)
    efficiencies = (0.5, 0.8, 0.95, 1.0)
    durations = (1, 7, 60, 300, 3600)

    for capacity_wh in capacities:
        for efficiency in efficiencies:
            config = _battery_config(
                capacity_wh=capacity_wh,
                charge_efficiency=efficiency,
                discharge_efficiency=efficiency,
                max_charge_input_power_w=5000.0,
                max_discharge_output_power_w=5000.0,
            )
            for dt_seconds in durations:
                for start_energy_wh, generation_w, load_w in (
                    (nextafter(capacity_wh, 0.0), 10000.0, 0.0),
                    (capacity_wh * 0.123456789, 10000.0, 0.0),
                    (
                        nextafter(capacity_wh * 1.0e-12, capacity_wh),
                        0.0,
                        10000.0,
                    ),
                    (capacity_wh * 0.876543211, 0.0, 10000.0),
                ):
                    transition = compute_battery_transition(
                        BatteryState(start_energy_wh),
                        config,
                        generation_w=generation_w,
                        load_w=load_w,
                        dt_seconds=dt_seconds,
                    )
                    _assert_transition_invariants(transition, capacity_wh)
                    _assert_conserved(transition)

                    follow_on = compute_battery_transition(
                        BatteryState(transition.end_energy_wh),
                        config,
                        generation_w=1.0,
                        load_w=1.0,
                        dt_seconds=7,
                    )
                    assert follow_on.end_energy_wh == transition.end_energy_wh
                    _assert_transition_invariants(follow_on, capacity_wh)


@pytest.mark.parametrize("flow", ("charge", "discharge"))
def test_smallest_positive_efficiency_returns_finite_bounded_transition(
    flow,
) -> None:
    config = _battery_config(
        capacity_wh=100.0,
        charge_efficiency=SMALLEST_POSITIVE_FLOAT,
        discharge_efficiency=SMALLEST_POSITIVE_FLOAT,
        max_charge_input_power_w=1000.0,
        max_discharge_output_power_w=1000.0,
    )
    generation_w, load_w = (
        (1000.0, 0.0) if flow == "charge" else (0.0, 1000.0)
    )

    transition = compute_battery_transition(
        BatteryState(50.0),
        config,
        generation_w=generation_w,
        load_w=load_w,
        dt_seconds=1,
    )

    _assert_transition_invariants(transition, 100.0)
    _assert_conserved(transition)
    if flow == "discharge":
        assert transition.end_energy_wh == 0.0


def test_unrepresentable_timestep_raises_value_error_without_raw_overflow() -> None:
    with pytest.raises(ValueError, match="represented|finite"):
        compute_battery_transition(
            BatteryState(50.0),
            _battery_config(capacity_wh=100.0),
            generation_w=1.0,
            load_w=1.0,
            dt_seconds=10**400,
        )


def test_conservation_report_uses_same_timestep_representability_guard() -> None:
    transition = compute_battery_transition(
        BatteryState(50.0),
        _battery_config(capacity_wh=100.0),
        generation_w=1.0,
        load_w=1.0,
        dt_seconds=1,
    )
    object.__setattr__(transition, "dt_seconds", 10**400)
    result = EPSIntervalResult(
        SolarGenerationResult(1.0, True, 0.0),
        _loads(1.0),
        transition,
    )

    with pytest.raises(ValueError, match="represented|finite"):
        compute_eps_conservation_report(result)


def test_finite_component_loads_reject_nonfinite_aggregate() -> None:
    with pytest.raises(ValueError, match="total_load_w must be finite"):
        PowerLoadBreakdown(
            1.0e308,
            1.0e308,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        )


def test_context_rejects_over_capacity_and_accepts_exact_capacity() -> None:
    spacecraft = _spacecraft_configuration(capacity_wh=100.0)

    assert _context(spacecraft=spacecraft, battery_energy_wh=0.0)
    assert _context(spacecraft=spacecraft, battery_energy_wh=100.0)
    with pytest.raises(ValueError, match="battery energy.*capacity"):
        _context(spacecraft=spacecraft, battery_energy_wh=100.00000000000001)


@pytest.mark.parametrize(
    "invalid_energy,expected_exception",
    (
        (-1.0, ValueError),
        (True, TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ),
)
def test_context_revalidates_mutated_battery_state(
    invalid_energy,
    expected_exception,
) -> None:
    context = _context(
        spacecraft=_spacecraft_configuration(capacity_wh=100.0),
        battery_energy_wh=50.0,
    )
    context.spacecraft_state.battery.energy_wh = invalid_energy

    with pytest.raises(expected_exception):
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


def _mutable_references(context: SimulationContext) -> tuple[object, ...]:
    return (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.propulsion,
        context.spacecraft_state.thermal,
        *context.spacecraft_state.thermal.node_states,
        context.spacecraft_state.onboard,
        context.spacecraft_state.data_storage,
        context.ground_knowledge_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def test_mutated_over_capacity_no_eps_step_rejects_atomically() -> None:
    context = _context(
        spacecraft=_spacecraft_configuration(capacity_wh=100.0),
        battery_energy_wh=99.0,
    )
    context.spacecraft_state.battery.energy_wh = 100.00000000000001
    before = deepcopy(context)
    references = _mutable_references(context)

    with pytest.raises(ValueError, match="battery energy.*capacity"):
        SimulationEngine().step(context)

    assert context == before
    assert all(
        current is original
        for current, original in zip(_mutable_references(context), references)
    )


def test_checkpoint_creation_and_restore_enforce_active_capacity() -> None:
    spacecraft = _spacecraft_configuration(capacity_wh=100.0)
    at_capacity = _context(spacecraft=spacecraft, battery_energy_wh=100.0)
    checkpoint = CheckpointState.from_context(at_capacity)

    assert checkpoint.restore(at_capacity.inputs) == at_capacity

    mutated = _context(spacecraft=spacecraft, battery_energy_wh=99.0)
    mutated.spacecraft_state.battery.energy_wh = 100.00000000000001
    with pytest.raises(ValueError, match="battery energy.*capacity"):
        CheckpointState.from_context(mutated)

    invalid_state = _context(spacecraft=spacecraft, battery_energy_wh=99.0)
    invalid_state.spacecraft_state.battery.energy_wh = -1.0
    with pytest.raises(ValueError, match="energy_wh"):
        CheckpointState.from_context(invalid_state)

    invalid_checkpoint = replace(
        checkpoint,
        spacecraft=replace(
            checkpoint.spacecraft,
            battery_energy_wh=100.00000000000001,
        ),
    )
    with pytest.raises(ValueError, match="battery energy.*capacity"):
        invalid_checkpoint.restore(at_capacity.inputs)


class InvalidPhysicalResultEngine(SimulationEngine):
    def _physical_integration(self, context, interval, eps_inputs):
        return object()


def test_invalid_physical_result_is_rejected_before_commit() -> None:
    context = _context()
    before = deepcopy(context)
    references = _mutable_references(context)

    with pytest.raises(TypeError, match="EPSIntervalResult"):
        InvalidPhysicalResultEngine().step(
            context,
            eps_inputs=EPSIntervalInputs(True, 0.0, _loads(0.0)),
        )

    assert context == before
    assert all(
        current is original
        for current, original in zip(_mutable_references(context), references)
    )


def test_step_result_construction_failure_is_rejected_before_commit(
    monkeypatch,
) -> None:
    from ops_sim.v5 import engine as engine_module

    context = _context()
    before = deepcopy(context)
    references = _mutable_references(context)

    def reject_step_result(*args, **kwargs):
        raise RuntimeError("synthetic StepResult construction failure")

    monkeypatch.setattr(engine_module, "StepResult", reject_step_result)

    with pytest.raises(RuntimeError, match="StepResult construction"):
        SimulationEngine().step(
            context,
            eps_inputs=EPSIntervalInputs(True, 0.0, _loads(0.0)),
        )

    assert context == before
    assert all(
        current is original
        for current, original in zip(_mutable_references(context), references)
    )


def test_hardening_uses_analytical_boundaries_without_epsilon_clipping() -> None:
    tree = ast.parse(
        EPS_PATH.read_text(encoding="utf-8"),
        filename=str(EPS_PATH),
    )
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert "epsilon" not in {item.lower() for item in identifiers}
    assert "isclose" not in identifiers
    assert "round" not in identifiers

    for node in ast.walk(tree):
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


def test_transaction_constructs_one_step_result_before_one_commit() -> None:
    tree = ast.parse(
        ENGINE_PATH.read_text(encoding="utf-8"),
        filename=str(ENGINE_PATH),
    )
    engine_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SimulationEngine"
    )
    step = next(
        node
        for node in engine_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "step"
    )
    transaction = next(
        node
        for node in engine_class.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_run_transaction"
    )
    transaction_calls = [
        node
        for node in ast.walk(step)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_run_transaction"
    ]
    step_result_calls = [
        node
        for node in ast.walk(transaction)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "StepResult"
    ]
    commit_calls = [
        node
        for node in ast.walk(transaction)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_commit"
    ]
    all_step_result_calls = [
        node
        for node in ast.walk(engine_class)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "StepResult"
    ]
    all_commit_calls = [
        node
        for node in ast.walk(engine_class)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_commit"
    ]

    assert len(transaction_calls) == 1
    assert len(step_result_calls) == len(commit_calls) == 1
    assert step_result_calls == all_step_result_calls
    assert commit_calls == all_commit_calls
    assert step_result_calls[0].lineno < commit_calls[0].lineno
    assert SimulationEngine.__slots__ == ()
    assert not hasattr(SimulationEngine(), "__dict__")


def test_v51f_adds_no_physical_parameter_legacy_import_or_duplicate_equation() -> None:
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

    production_paths = tuple((ROOT / "ops_sim" / "v5").glob("*.py"))
    definitions = []
    for path in production_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "compute_battery_transition"
            ):
                definitions.append(path.name)
            if isinstance(node, (ast.Name, ast.Attribute)):
                identifier = (
                    node.id if isinstance(node, ast.Name) else node.attr
                )
                assert identifier not in {
                    "DEFAULT_CONFIG",
                    "Simulator",
                    "SatelliteState",
                }

    assert definitions == ["eps.py"]


def test_v51f_decisions_and_historical_exports_remain_live() -> None:
    decision_log = DECISION_LOG_PATH.read_text(encoding="utf-8")
    for decision_number in range(72, 77):
        assert decision_log.count(f"## D{decision_number:03d} ") == 1

    from ops_sim.v5 import engine, eps, eps_validation, power_loads

    assert eps.__all__ == [
        "BatteryTransition",
        "battery_soc_fraction",
        "compute_battery_transition",
    ]
    assert eps_validation.__all__ == [
        "EPSConservationReport",
        "compute_eps_conservation_report",
    ]
    assert power_loads.__all__ == [
        "PowerLoadBreakdown",
        "compose_power_load",
    ]
    expected_engine_exports = [
        "STEP_PHASE_ORDER",
        "SimulationEngine",
        "SimulationPhase",
        "StepResult",
    ]
    historical_source = subprocess.run(
        ["git", "show", f"{V51F_COMMIT}:ops_sim/v5/engine.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    historical_tree = ast.parse(historical_source)
    historical_exports = next(
        node
        for node in historical_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    )

    assert ast.literal_eval(historical_exports.value) == expected_engine_exports
    assert all(name in engine.__all__ for name in expected_engine_exports)
