"""Runnable synthetic V5.2 EPS-to-thermal integration demonstration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import TextIO


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops_sim.v5.adcs_config import (  # noqa: E402
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.configuration import (  # noqa: E402
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
from ops_sim.v5.context import SimulationContext, SimulationInputs  # noqa: E402
from ops_sim.v5.controller_state import ControllerState  # noqa: E402
from ops_sim.v5.data_delivery import GroundDataDeliveryState  # noqa: E402
from ops_sim.v5.degradation_config import (  # noqa: E402
    BatteryAgeingModelConfig,
)
from ops_sim.v5.diagnostics import Diagnostics  # noqa: E402
from ops_sim.v5.engine import SimulationEngine  # noqa: E402
from ops_sim.v5.eps_system import EPSIntervalInputs  # noqa: E402
from ops_sim.v5.ids import (  # noqa: E402
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
    TelemetrySnapshotId,
    ThermalLinkId,
    ThermalNodeId,
    WorldId,
)
from ops_sim.v5.knowledge import (  # noqa: E402
    GroundKnowledgeState,
    TelemetrySnapshot,
)
from ops_sim.v5.manifest import ModelManifest  # noqa: E402
from ops_sim.v5.mission import MissionState  # noqa: E402
from ops_sim.v5.parameters import ScalarParameter  # noqa: E402
from ops_sim.v5.payload_config import OpticalAcquisitionConfig  # noqa: E402
from ops_sim.v5.power_loads import PowerLoadBreakdown  # noqa: E402
from ops_sim.v5.provenance import (  # noqa: E402
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.run_config import (  # noqa: E402
    EnvironmentConfig,
    FlightRulesConfig,
    NumericalConfig,
    ScenarioConfig,
)
from ops_sim.v5.state import (  # noqa: E402
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
from ops_sim.v5.thermal import (  # noqa: E402
    ThermalIntervalInputs,
    ThermalNodeBoundaryInput,
)
from ops_sim.v5.thermal_config import (  # noqa: E402
    ThermalLinkConfig,
    ThermalNetworkConfig,
    ThermalNodeConfig,
)
from ops_sim.v5.thermal_coupling import (  # noqa: E402
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
)
from ops_sim.v5.world import CommonWorld  # noqa: E402


TIMESTEP_SECONDS = 60
DEFAULT_DEMO_STEPS = 16
THERMAL_NODE_NAMES = ("bus", "battery", "payload")


@dataclass(frozen=True, slots=True)
class SyntheticForcing:
    """One explicit entry in the repeating non-orbital forcing schedule."""

    label: str
    sunlit: bool
    base_bus_w: float
    payload_w: float
    bus_internal_heat_w: float
    battery_internal_heat_w: float
    payload_internal_heat_w: float


@dataclass(frozen=True, slots=True)
class DemoRow:
    """One completed-step row from the integrated demonstration."""

    step: int
    time_s: int
    sunlit: bool
    load_w: float
    solar_generation_w: float
    battery_energy_wh: float
    battery_conversion_loss_wh: float
    bus_temperature_k: float
    battery_temperature_k: float
    payload_temperature_k: float
    battery_applied_heat_w: float
    unmet_load_w: float


SYNTHETIC_FORCING_SCHEDULE = (
    SyntheticForcing("sunlit standby", True, 50.0, 20.0, 18.0, 1.5, 4.0),
    SyntheticForcing("sunlit high load", True, 50.0, 100.0, 25.0, 2.0, 35.0),
    SyntheticForcing("eclipse standby", False, 50.0, 10.0, 16.0, 1.5, 3.0),
    SyntheticForcing("eclipse high load", False, 50.0, 70.0, 23.0, 2.0, 28.0),
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
            rationale=(
                "Synthetic V5.2 demonstration value; not a real spacecraft "
                "property."
            ),
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


def _thermal_node(
    name: str,
    *,
    heat_capacity_j_per_k: float,
    emissivity: float,
    radiating_area_m2: float,
) -> ThermalNodeConfig:
    prefix = f"thermal.node.{name}"
    return ThermalNodeConfig(
        ThermalNodeId(name),
        _parameter(
            f"{prefix}.heat-capacity", "J/K", heat_capacity_j_per_k
        ),
        _parameter(f"{prefix}.emissivity", "1", emissivity),
        _parameter(f"{prefix}.radiating-area", "m^2", radiating_area_m2),
        _parameter(f"{prefix}.operating-min-temperature", "K", 270.0),
        _parameter(f"{prefix}.operating-max-temperature", "K", 320.0),
        _parameter(f"{prefix}.survival-min-temperature", "K", 250.0),
        _parameter(f"{prefix}.survival-max-temperature", "K", 340.0),
    )


def _thermal_network() -> ThermalNetworkConfig:
    nodes = (
        _thermal_node(
            "bus",
            heat_capacity_j_per_k=100_000.0,
            emissivity=0.65,
            radiating_area_m2=0.8,
        ),
        _thermal_node(
            "battery",
            heat_capacity_j_per_k=80_000.0,
            emissivity=0.75,
            radiating_area_m2=0.5,
        ),
        _thermal_node(
            "payload",
            heat_capacity_j_per_k=90_000.0,
            emissivity=0.70,
            radiating_area_m2=0.7,
        ),
    )
    links = (
        ThermalLinkConfig(
            ThermalLinkId("bus-battery"),
            ThermalNodeId("bus"),
            ThermalNodeId("battery"),
            _parameter("thermal.link.bus-battery.conductance", "W/K", 0.8),
        ),
        ThermalLinkConfig(
            ThermalLinkId("bus-payload"),
            ThermalNodeId("bus"),
            ThermalNodeId("payload"),
            _parameter("thermal.link.bus-payload.conductance", "W/K", 0.6),
        ),
    )
    return ThermalNetworkConfig(
        nodes,
        links,
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("payload"),
    )


def _spacecraft_configuration() -> SpacecraftConfiguration:
    return SpacecraftConfiguration(
        SpacecraftConfigurationId("v52-integrated-demo"),
        "Synthetic V5.2 Integrated Demonstration",
        1,
        EPSConfig(
            SubsystemConfigurationId("demo-eps"),
            BatteryConfig(
                SubsystemConfigurationId("demo-battery"),
                _parameter("eps.battery.nominal-energy", "Wh", 500.0),
                _parameter("eps.battery.charge-efficiency", "1", 0.92),
                _parameter("eps.battery.discharge-efficiency", "1", 0.90),
                _parameter(
                    "eps.battery.max-charge-input-power", "W", 120.0
                ),
                _parameter(
                    "eps.battery.max-discharge-output-power", "W", 150.0
                ),
            ),
            SolarArrayConfig(
                SubsystemConfigurationId("demo-solar-array"),
                _parameter(
                    "eps.solar-array.nominal-generation", "W", 180.0
                ),
            ),
        ),
        PayloadConfig(
            SubsystemConfigurationId("demo-payload"),
            PayloadFamily.OPTICAL_EO,
            (PayloadMode.PANCHROMATIC,),
            _optical_acquisition(),
        ),
        StorageConfig(
            SubsystemConfigurationId("demo-storage"),
            _parameter("storage.usable-capacity", "GB", 64.0),
        ),
        CommunicationsConfig(
            SubsystemConfigurationId("demo-communications"),
            _parameter(
                "communications.nominal-downlink-data-rate",
                "bit/s",
                1_000_000.0,
            ),
        ),
        ADCSConfig(SubsystemConfigurationId("demo-adcs"), _agile_pointing()),
        ThermalConfig(
            SubsystemConfigurationId("demo-thermal"),
            _thermal_network(),
        ),
        DegradationConfig(
            SubsystemConfigurationId("demo-degradation"),
            _parameter(
                "degradation.battery.initial-usable-capacity-retention",
                "1",
                1.0,
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
            SubsystemConfigurationId("demo-propulsion"),
            _parameter("propulsion.initial-delta-v", "m/s", 12.0),
        ),
        OBCConfig(SubsystemConfigurationId("demo-obc")),
    )


def build_demo_context() -> SimulationContext:
    """Construct a fresh deterministic synthetic demonstration context."""
    spacecraft = _spacecraft_configuration()
    numerical = NumericalConfig(
        NumericalConfigId("v52-demo-step"),
        TIMESTEP_SECONDS,
        10,
        TIMESTEP_SECONDS,
    )
    environment = EnvironmentConfig(EnvironmentId("v52-demo-environment"))
    flight_rules = FlightRulesConfig(FlightRulesId("v52-demo-rules"))
    scenario = ScenarioConfig(ScenarioId("v52-demo-synthetic-schedule"))
    world = CommonWorld(
        WorldId("v52-demo-world"),
        scenario.scenario_id,
        86_400,
        (),
    )
    controller_id = ControllerId("v52-demo-controller")
    manifest = ModelManifest(
        ModelManifestId("v52-demo-manifest"),
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
        SpacecraftState(
            BatteryState(250.0),
            PropulsionState(12.0),
            ThermalState(
                (
                    ThermalNodeState(ThermalNodeId("bus"), 295.0),
                    ThermalNodeState(ThermalNodeId("battery"), 293.0),
                    ThermalNodeState(ThermalNodeId("payload"), 291.0),
                )
            ),
            DegradationState(
                BatteryDegradationState(1.0, 0.0),
                SolarDegradationState(1.0),
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
        ),
        GroundKnowledgeState(
            TelemetrySnapshot(
                TelemetrySnapshotId("v52-demo-initial-telemetry"),
                0,
                0,
                250.0,
                12.0,
                OperationalMode.STANDBY,
            ),
            (),
        ),
        GroundDataDeliveryState((), ()),
        MissionState((), (), (), None, (), ()),
        ControllerState(controller_id, None, 0),
        Diagnostics(0),
    )


def forcing_for_step(step_index: int) -> SyntheticForcing:
    """Return the deterministic repeating forcing entry for one zero-based step."""
    if type(step_index) is not int:
        raise TypeError("step_index must be an integer")
    if step_index < 0:
        raise ValueError("step_index must be greater than or equal to zero")
    return SYNTHETIC_FORCING_SCHEDULE[
        step_index % len(SYNTHETIC_FORCING_SCHEDULE)
    ]


def build_step_inputs(
    step_index: int,
) -> tuple[
    EPSIntervalInputs,
    ThermalIntervalInputs,
    ThermalHeatSourceInputs,
]:
    """Build explicit EPS, boundary, and heat inputs for one demo step."""
    forcing = forcing_for_step(step_index)
    eps_inputs = EPSIntervalInputs(
        forcing.sunlit,
        0.0,
        PowerLoadBreakdown(
            forcing.base_bus_w,
            0.0,
            0.0,
            forcing.payload_w,
            0.0,
            0.0,
            0.0,
        ),
    )
    thermal_inputs = ThermalIntervalInputs(
        (
            ThermalNodeBoundaryInput(ThermalNodeId("bus"), 270.0),
            ThermalNodeBoundaryInput(ThermalNodeId("battery"), 268.0),
            ThermalNodeBoundaryInput(ThermalNodeId("payload"), 265.0),
        )
    )
    heat_source_inputs = ThermalHeatSourceInputs(
        (
            ThermalNodeHeatSourceInput(
                ThermalNodeId("bus"),
                forcing.bus_internal_heat_w,
                3.0 if forcing.sunlit else 0.0,
                0.5 if forcing.sunlit else 0.0,
                1.0,
            ),
            ThermalNodeHeatSourceInput(
                ThermalNodeId("battery"),
                forcing.battery_internal_heat_w,
                0.0,
                0.0,
                0.2,
            ),
            ThermalNodeHeatSourceInput(
                ThermalNodeId("payload"),
                forcing.payload_internal_heat_w,
                2.0 if forcing.sunlit else 0.0,
                0.3 if forcing.sunlit else 0.0,
                0.8,
            ),
        )
    )
    return eps_inputs, thermal_inputs, heat_source_inputs


def _demo_row(
    step_number: int,
    context: SimulationContext,
    sunlit: bool,
    result,
) -> DemoRow:
    eps_result = result.eps_result
    coupling_result = result.thermal_coupling_result
    if eps_result is None or coupling_result is None:
        raise RuntimeError("demo step did not produce coupled physical results")
    temperature_by_name = {
        node.node_id.value: node.temperature_k
        for node in context.spacecraft_state.thermal.node_states
    }
    battery_heat = next(
        ledger.total_applied_heat_w
        for ledger in coupling_result.node_heat_ledgers
        if ledger.node_id == ThermalNodeId("battery")
    )
    return DemoRow(
        step_number,
        context.simulation_time_seconds,
        sunlit,
        eps_result.loads.total_load_w,
        eps_result.solar.generation_w,
        context.spacecraft_state.battery.energy_wh,
        eps_result.battery.conversion_loss_wh,
        temperature_by_name["bus"],
        temperature_by_name["battery"],
        temperature_by_name["payload"],
        battery_heat,
        eps_result.battery.unmet_load_w,
    )


def _print_heading(stream: TextIO) -> None:
    print("V5.2 synthetic integrated EPS/thermal demonstration", file=stream)
    print(
        "Reduced-order model; not flight software; not telemetry replay; "
        "not a KazEOSat-1 digital twin.",
        file=stream,
    )
    print(
        "Thermal forcing is explicitly supplied, not orbit-derived.",
        file=stream,
    )
    print(
        "Battery retention uses zero-damage coefficients; throughput history "
        "still accumulates.",
        file=stream,
    )
    print(
        "Synthetic forcing schedule repeats: sunlit standby, sunlit high "
        "load, eclipse standby, eclipse high load.",
        file=stream,
    )
    print(
        "step time_s sunlit load_W solar_generation_W battery_energy_Wh "
        "battery_conversion_loss_Wh bus_temperature_K "
        "battery_temperature_K payload_temperature_K "
        "battery_applied_heat_W unmet_load_W",
        file=stream,
    )


def _print_row(row: DemoRow, stream: TextIO) -> None:
    print(
        f"{row.step:4d} {row.time_s:6d} "
        f"{str(row.sunlit).lower():>7} {row.load_w:7.1f} "
        f"{row.solar_generation_w:18.1f} {row.battery_energy_wh:18.3f} "
        f"{row.battery_conversion_loss_wh:26.6f} "
        f"{row.bus_temperature_k:17.3f} "
        f"{row.battery_temperature_k:21.3f} "
        f"{row.payload_temperature_k:21.3f} "
        f"{row.battery_applied_heat_w:22.3f} {row.unmet_load_w:12.1f}",
        file=stream,
    )


def run_demo(
    *,
    steps: int = DEFAULT_DEMO_STEPS,
    stream: TextIO | None = None,
) -> tuple[DemoRow, ...]:
    """Run and print the deterministic integrated demonstration."""
    if type(steps) is not int:
        raise TypeError("steps must be an integer")
    if steps <= 0:
        raise ValueError("steps must be greater than zero")
    output = sys.stdout if stream is None else stream
    context = build_demo_context()
    engine = SimulationEngine()
    rows = []
    _print_heading(output)
    for step_index in range(steps):
        forcing = forcing_for_step(step_index)
        eps_inputs, thermal_inputs, heat_source_inputs = build_step_inputs(
            step_index
        )
        result = engine.step(
            context,
            eps_inputs=eps_inputs,
            thermal_inputs=thermal_inputs,
            heat_source_inputs=heat_source_inputs,
        )
        row = _demo_row(step_index + 1, context, forcing.sunlit, result)
        rows.append(row)
        _print_row(row, output)
    return tuple(rows)


def main() -> None:
    """Run the default 16-step demonstration."""
    run_demo()


if __name__ == "__main__":
    main()
