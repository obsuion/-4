"""Deterministic end-to-end V5.3 imaging transaction demonstration.

The values in this module are synthetic explicit model assumptions.  The
demonstration is not a calibrated spacecraft scenario, and its sample-grid
quantities are not stored, downlinked, or delivered product sizes.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
import sys


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.v52_integrated_eps_thermal_demo import (  # noqa: E402
    build_demo_context,
)
from ops_sim.v5.adcs import CommonFrameBoresightDirection  # noqa: E402
from ops_sim.v5.checkpoint import (  # noqa: E402
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.context import SimulationContext  # noqa: E402
from ops_sim.v5.engine import (  # noqa: E402
    ImagingEngineStepAttempt,
    SimulationEngine,
)
from ops_sim.v5.ids import (  # noqa: E402
    ADCSBoresightFrameId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
    ThermalNodeId,
)
from ops_sim.v5.imaging_execution import (  # noqa: E402
    ImagingExecutionAuthorizationStatus,
    ScheduledObservationAcquisitionExecution,
)
from ops_sim.v5.imaging_feasibility import (  # noqa: E402
    ObservationAcquisitionCandidate,
)
from ops_sim.v5.imaging_resources import (  # noqa: E402
    AcquisitionEPSIntervalEnvironment,
    AcquisitionServiceStatus,
)
from ops_sim.v5.observation import (  # noqa: E402
    ObservationOpportunity,
    ObservationPointing,
)
from ops_sim.v5.observation_feasibility import (  # noqa: E402
    ObservationManeuverCandidate,
    ScheduledObservationExecution,
)
from ops_sim.v5.parameters import ScalarParameter  # noqa: E402
from ops_sim.v5.payload import (  # noqa: E402
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
    compute_optical_acquisition,
)
from ops_sim.v5.power_loads import PowerLoadBreakdown  # noqa: E402
from ops_sim.v5.provenance import (  # noqa: E402
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import BatteryState  # noqa: E402
from ops_sim.v5.thermal import (  # noqa: E402
    ThermalIntervalInputs,
    ThermalNodeBoundaryInput,
)
from ops_sim.v5.thermal_coupling import (  # noqa: E402
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
)
from ops_sim.v5.thermal_routing import (  # noqa: E402
    ComponentHeatRoute,
    ComponentHeatRoutingConfig,
    ElectricalLoadComponent,
)


DEMO_START_SECONDS = 200
DEMO_TIMESTEP_SECONDS = 60
DEMO_ACQUISITION_POWER_W = 90.0
DEMO_START_BATTERY_ENERGY_WH = 1.0
DEMO_FOOTPRINT_WIDTH_M = 1_000.0
DEMO_FOOTPRINT_LENGTH_M = 1_000.0

REFERENCE_SCENE_SIDE_M = 20_000.0
_SQUARE_METERS_PER_SQUARE_KILOMETER = 1_000_000
_BITS_PER_MEGABIT = 1_000_000


@dataclass(frozen=True, slots=True)
class ThermalNodeTemperatureReport:
    """Start and committed endpoint for one synthetic thermal node."""

    node_id: ThermalNodeId
    start_temperature_k: float
    end_temperature_k: float


@dataclass(frozen=True, slots=True)
class ReferenceSampleGridReport:
    """Independent 20 km square B2 sample-grid reference arithmetic."""

    cross_track_width_m: float
    along_track_length_m: float
    footprint_area_m2: float
    panchromatic_equivalent_samples: float
    multispectral_equivalent_samples_per_band: float
    multispectral_equivalent_samples_total: float
    total_equivalent_samples: float
    sample_grid_proxy_bits: float
    sample_grid_proxy_bytes: float
    sample_grid_proxy_megabits_per_square_km: float
    interpretation: str


@dataclass(frozen=True, slots=True)
class ImagingCaseReport:
    """Inspectable outcome of one independently started imaging attempt."""

    name: str
    attempt: ImagingEngineStepAttempt
    authorization_status: ImagingExecutionAuthorizationStatus
    acquisition_service_status: AcquisitionServiceStatus | None
    scheduled_start_seconds: int
    dt_seconds: int
    sequence_feasible: bool
    transition_angular_separation_deg: float | None
    slew_elapsed_time_seconds: float | None
    settling_time_seconds: float | None
    candidate_readiness_seconds: int | float | None
    footprint_area_m2: float | None
    requested_acquisition_power_w: float | None
    requested_acquisition_energy_wh: float | None
    sample_grid_proxy_total_samples: float | None
    sample_grid_proxy_bits: float | None
    sample_grid_proxy_bytes: float | None
    total_eps_requested_power_w: float | None
    aggregate_served_power_w: float | None
    aggregate_unmet_power_w: float | None
    minimum_served_acquisition_power_w: float | None
    maximum_served_acquisition_power_w: float | None
    routed_payload_heat_w: float | None
    battery_conversion_heat_w: float | None
    start_battery_energy_wh: float
    raw_eps_end_battery_energy_wh: float | None
    authoritative_battery_end_energy_wh: float | None
    battery_throughput_increment_wh: float | None
    representative_battery_temperature_k: float | None
    start_battery_retention: float
    end_battery_retention: float
    start_solar_retention: float
    end_solar_retention: float
    thermal_node_temperatures: tuple[ThermalNodeTemperatureReport, ...]
    committed_context_time_seconds: int
    committed_completed_steps: int
    step_result_present: bool
    context_unchanged: bool
    authoritative_identity_unchanged: bool
    mission_state_unchanged: bool


@dataclass(frozen=True, slots=True)
class V53IntegratedImagingDemoReport:
    """Complete deterministic F4A demonstration report."""

    authorized: ImagingCaseReport
    sequence_infeasible: ImagingCaseReport
    full_service_impossible: ImagingCaseReport
    service_allocation_required: ImagingCaseReport
    reference_sample_grid: ReferenceSampleGridReport
    replay_attempt_equal: bool
    replay_context_equal: bool
    repeat_attempt_equal: bool
    repeat_context_equal: bool
    checkpoint_schema_version: int


def _routing_parameter(
    component: ElectricalLoadComponent,
    value: float,
) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(
                f"thermal.routing.{component.value}.retained-heat-fraction"
            ),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            "1",
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale=(
                "Synthetic V5.3 imaging demonstration route; not a "
                "calibrated spacecraft property."
            ),
        ),
    )


def _acquisition_power_parameter() -> ScalarParameter:
    return ScalarParameter(
        DEMO_ACQUISITION_POWER_W,
        ParameterProvenance(
            ParameterId("payload.optical.acquisition-power"),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            "W",
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale=(
                "Synthetic V5.3 imaging demonstration demand; not a "
                "calibrated spacecraft property."
            ),
        ),
    )


def _build_start_context() -> SimulationContext:
    """Return one fresh context equal to every other case start."""
    context = build_demo_context()
    spacecraft_config = context.inputs.spacecraft_configuration
    optical = spacecraft_config.payload.optical_acquisition
    if optical is None:
        raise RuntimeError("the V5.2 demonstration must provide optical config")
    optical = replace(
        optical,
        acquisition_power_w=_acquisition_power_parameter(),
    )
    payload = replace(
        spacecraft_config.payload,
        optical_acquisition=optical,
    )
    spacecraft_config = replace(
        spacecraft_config,
        payload=payload,
    )
    numerical_config = replace(
        context.inputs.numerical_config,
        timestep_seconds=DEMO_TIMESTEP_SECONDS,
        checkpoint_interval_seconds=DEMO_TIMESTEP_SECONDS,
    )
    inputs = replace(
        context.inputs,
        spacecraft_configuration=spacecraft_config,
        numerical_config=numerical_config,
    )
    spacecraft_state = replace(
        context.spacecraft_state,
        battery=BatteryState(DEMO_START_BATTERY_ENERGY_WH),
    )
    return replace(
        context,
        simulation_time_seconds=DEMO_START_SECONDS,
        inputs=inputs,
        spacecraft_state=spacecraft_state,
    )


def _previous_execution() -> ScheduledObservationExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("v53-demo-previous-opportunity"),
        ImagingRequestId("v53-demo-previous-request"),
        0,
        60,
        20,
        ObservationPointing(10.0, 0.0),
    )
    candidate = ObservationManeuverCandidate(
        opportunity,
        CommonFrameBoresightDirection(
            ADCSBoresightFrameId("v53-demo-common-frame"),
            0.0,
            0.0,
            1.0,
        ),
    )
    return ScheduledObservationExecution(candidate, 0)


def _scheduled_execution(
    view_angle_from_nadir_deg: float,
) -> ScheduledObservationAcquisitionExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("v53-demo-imaging-opportunity"),
        ImagingRequestId("v53-demo-imaging-request"),
        DEMO_START_SECONDS,
        DEMO_START_SECONDS + 2 * DEMO_TIMESTEP_SECONDS,
        DEMO_TIMESTEP_SECONDS,
        ObservationPointing(view_angle_from_nadir_deg, 90.0),
    )
    maneuver = ObservationManeuverCandidate(
        opportunity,
        CommonFrameBoresightDirection(
            ADCSBoresightFrameId("v53-demo-common-frame"),
            1.0,
            0.0,
            0.0,
        ),
    )
    acquisition = OpticalAcquisitionInput(
        DEMO_FOOTPRINT_WIDTH_M,
        DEMO_FOOTPRINT_LENGTH_M,
        DEMO_TIMESTEP_SECONDS,
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
    )
    return ScheduledObservationAcquisitionExecution(
        ObservationAcquisitionCandidate(maneuver, acquisition),
        DEMO_START_SECONDS,
    )


def _authorized_environment() -> AcquisitionEPSIntervalEnvironment:
    return AcquisitionEPSIntervalEnvironment(
        True,
        0.0,
        PowerLoadBreakdown(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0),
    )


def _impossible_environment() -> AcquisitionEPSIntervalEnvironment:
    return AcquisitionEPSIntervalEnvironment(
        False,
        0.0,
        PowerLoadBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


def _allocation_environment() -> AcquisitionEPSIntervalEnvironment:
    return AcquisitionEPSIntervalEnvironment(
        True,
        0.0,
        PowerLoadBreakdown(200.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


def _routing_config() -> ComponentHeatRoutingConfig:
    fractions = {
        ElectricalLoadComponent.BASE_BUS: 0.8,
        ElectricalLoadComponent.OBC: 0.7,
        ElectricalLoadComponent.ADCS: 0.5,
        ElectricalLoadComponent.PAYLOAD: 0.6,
        ElectricalLoadComponent.COMMUNICATIONS: 0.4,
        ElectricalLoadComponent.THERMAL_CONTROL: 1.0,
        ElectricalLoadComponent.PROPULSION: 0.5,
    }
    return ComponentHeatRoutingConfig(
        tuple(
            ComponentHeatRoute(
                component,
                ThermalNodeId(
                    "payload"
                    if component is ElectricalLoadComponent.PAYLOAD
                    else "bus"
                ),
                _routing_parameter(component, fractions[component]),
            )
            for component in ElectricalLoadComponent
        )
    )


def _thermal_inputs(context: SimulationContext) -> ThermalIntervalInputs:
    sink_temperature_by_node = {
        ThermalNodeId("bus"): 270.0,
        ThermalNodeId("battery"): 268.0,
        ThermalNodeId("payload"): 265.0,
    }
    nodes = context.inputs.spacecraft_configuration.thermal.network.nodes
    return ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(
                node.node_id,
                sink_temperature_by_node[node.node_id],
            )
            for node in nodes
        )
    )


def _external_heat_sources(
    context: SimulationContext,
) -> ThermalHeatSourceInputs:
    external_by_node = {
        ThermalNodeId("bus"): (3.0, 0.5, 1.0),
        ThermalNodeId("battery"): (0.0, 0.0, 0.2),
        ThermalNodeId("payload"): (2.0, 0.3, 0.8),
    }
    nodes = context.inputs.spacecraft_configuration.thermal.network.nodes
    return ThermalHeatSourceInputs(
        tuple(
            ThermalNodeHeatSourceInput(
                node.node_id,
                0.0,
                *external_by_node[node.node_id],
            )
            for node in nodes
        )
    )


def _authoritative_references(context: SimulationContext) -> tuple[object, ...]:
    spacecraft = context.spacecraft_state
    return (
        spacecraft,
        spacecraft.battery,
        spacecraft.propulsion,
        spacecraft.thermal,
        *spacecraft.thermal.node_states,
        spacecraft.degradation,
        spacecraft.degradation.battery,
        spacecraft.degradation.solar,
        spacecraft.onboard,
        spacecraft.data_storage,
        context.ground_knowledge_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def _case_report(
    name: str,
    context: SimulationContext,
    start_context: SimulationContext,
    start_references: tuple[object, ...],
    attempt: ImagingEngineStepAttempt,
) -> ImagingCaseReport:
    authorization = attempt.authorization_result
    electrical = authorization.electrical_result
    sequence = electrical.acquisition_evaluation.sequence_result
    transition = sequence.transition_result
    acquisition = electrical.acquisition_evaluation.acquisition_result
    eps_result = electrical.eps_result
    bounds = electrical.service_bounds
    thermal_proposal = authorization.thermal_proposal
    step_result = attempt.step_result

    routed_payload_heat_w = None
    battery_conversion_heat_w = None
    if thermal_proposal is not None:
        routed_payload_heat_w = next(
            ledger.retained_heat_w
            for ledger in thermal_proposal.routed_internal_heat_result
            .component_ledgers
            if ledger.component is ElectricalLoadComponent.PAYLOAD
        )
        battery_node_id = (
            context.inputs.spacecraft_configuration.thermal.network
            .battery_node_id
        )
        battery_conversion_heat_w = next(
            ledger.battery_conversion_heat_w
            for ledger in thermal_proposal.eps_thermal_coupling_result
            .node_heat_ledgers
            if ledger.node_id == battery_node_id
        )

    degradation = (
        None
        if step_result is None
        else step_result.battery_degradation_result
    )
    start_temperature_by_id = {
        node.node_id: node.temperature_k
        for node in start_context.spacecraft_state.thermal.node_states
    }
    thermal_node_temperatures = tuple(
        ThermalNodeTemperatureReport(
            node.node_id,
            start_temperature_by_id[node.node_id],
            node.temperature_k,
        )
        for node in context.spacecraft_state.thermal.node_states
    )
    return ImagingCaseReport(
        name,
        attempt,
        authorization.status,
        None if bounds is None else bounds.status,
        authorization.execution.scheduled_start_seconds,
        authorization.execution.candidate.acquisition_input
        .imaging_duration_seconds,
        sequence.feasible,
        None if transition is None else transition.angular_separation_deg,
        None if transition is None else transition.slew_elapsed_time_seconds,
        None if transition is None else transition.settling_time_seconds,
        sequence.candidate_next_start_seconds,
        None if acquisition is None else acquisition.footprint_area_m2,
        (
            None
            if acquisition is None
            else acquisition.requested_acquisition_power_w
        ),
        None if acquisition is None else acquisition.acquisition_energy_wh,
        None if acquisition is None else acquisition.total_equivalent_samples,
        (
            None
            if acquisition is None
            else acquisition.uncompressed_equivalent_bits
        ),
        (
            None
            if acquisition is None
            else acquisition.uncompressed_equivalent_bytes
        ),
        None if eps_result is None else eps_result.battery.load_w,
        None if eps_result is None else eps_result.battery.served_load_w,
        None if eps_result is None else eps_result.battery.unmet_load_w,
        (
            None
            if bounds is None
            else bounds.minimum_served_acquisition_power_w
        ),
        (
            None
            if bounds is None
            else bounds.maximum_served_acquisition_power_w
        ),
        routed_payload_heat_w,
        battery_conversion_heat_w,
        start_context.spacecraft_state.battery.energy_wh,
        None if eps_result is None else eps_result.battery.end_energy_wh,
        (
            None
            if step_result is None
            else context.spacecraft_state.battery.energy_wh
        ),
        None if degradation is None else degradation.throughput_increment_wh,
        (
            None
            if degradation is None
            else degradation.representative_temperature_k
        ),
        start_context.spacecraft_state.degradation.battery
        .usable_capacity_retention,
        context.spacecraft_state.degradation.battery.usable_capacity_retention,
        start_context.spacecraft_state.degradation.solar.generation_retention,
        context.spacecraft_state.degradation.solar.generation_retention,
        thermal_node_temperatures,
        context.simulation_time_seconds,
        context.diagnostics.completed_steps,
        step_result is not None,
        context == start_context,
        all(
            current is original
            for current, original in zip(
                _authoritative_references(context),
                start_references,
            )
        ),
        context.mission_state == start_context.mission_state,
    )


def _execute_case(
    name: str,
    context: SimulationContext,
    *,
    view_angle_from_nadir_deg: float,
    environment: AcquisitionEPSIntervalEnvironment,
) -> ImagingCaseReport:
    start_context = deepcopy(context)
    start_references = _authoritative_references(context)
    attempt = SimulationEngine().step_imaging(
        context,
        _previous_execution(),
        _scheduled_execution(view_angle_from_nadir_deg),
        environment=environment,
        routing_config=_routing_config(),
        thermal_inputs=_thermal_inputs(context),
        external_heat_sources=_external_heat_sources(context),
    )
    return _case_report(
        name,
        context,
        start_context,
        start_references,
        attempt,
    )


def _reference_sample_grid() -> ReferenceSampleGridReport:
    context = _build_start_context()
    optical_config = (
        context.inputs.spacecraft_configuration.payload.optical_acquisition
    )
    if optical_config is None:
        raise RuntimeError("the demonstration must provide optical config")
    result = compute_optical_acquisition(
        optical_config,
        OpticalAcquisitionInput(
            REFERENCE_SCENE_SIDE_M,
            REFERENCE_SCENE_SIDE_M,
            DEMO_TIMESTEP_SECONDS,
            OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        ),
    )
    area_km2 = (
        result.footprint_area_m2
        / _SQUARE_METERS_PER_SQUARE_KILOMETER
    )
    density = (
        result.uncompressed_equivalent_bits
        / _BITS_PER_MEGABIT
        / area_km2
    )
    return ReferenceSampleGridReport(
        REFERENCE_SCENE_SIDE_M,
        REFERENCE_SCENE_SIDE_M,
        result.footprint_area_m2,
        result.panchromatic_equivalent_samples,
        result.multispectral_equivalent_samples_per_band,
        result.multispectral_equivalent_samples_total,
        result.total_equivalent_samples,
        result.uncompressed_equivalent_bits,
        result.uncompressed_equivalent_bytes,
        density,
        (
            "DERIVED LEVEL-1 SAMPLE-GRID PROXY; not a measured onboard "
            "file size and not a stored, downlinked, or delivered data "
            "quantity."
        ),
    )


def _require_demonstrated(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"V5.3 integrated imaging demo failed: {message}")


def _verify_authorized_case(report: ImagingCaseReport) -> None:
    attempt = report.attempt
    authorization = attempt.authorization_result
    step_result = attempt.step_result
    _require_demonstrated(
        authorization.status is ImagingExecutionAuthorizationStatus.AUTHORIZED,
        "authorized status",
    )
    _require_demonstrated(step_result is not None, "authorized StepResult")
    _require_demonstrated(
        report.acquisition_service_status
        is AcquisitionServiceStatus.FULLY_SERVED,
        "full electrical service",
    )
    _require_demonstrated(
        report.committed_context_time_seconds
        == report.scheduled_start_seconds + report.dt_seconds,
        "one exact clock advance",
    )
    _require_demonstrated(
        report.committed_completed_steps == 1,
        "one completed-step increment",
    )
    if step_result is None:
        raise RuntimeError("authorized demonstration lacks StepResult")
    electrical = authorization.electrical_result
    thermal = authorization.thermal_proposal
    reconciliation = step_result.battery_capacity_reconciliation_result
    degradation = step_result.battery_degradation_result
    _require_demonstrated(
        step_result.eps_result is electrical.eps_result,
        "exact EPS proposal identity",
    )
    _require_demonstrated(
        step_result.eps_capability_result is electrical.eps_capability_result,
        "exact EPS capability identity",
    )
    _require_demonstrated(thermal is not None, "thermal proposal")
    if thermal is None:
        raise RuntimeError("authorized demonstration lacks thermal proposal")
    _require_demonstrated(
        step_result.thermal_coupling_result
        is thermal.eps_thermal_coupling_result,
        "exact thermal proposal identity",
    )
    _require_demonstrated(
        reconciliation is not None
        and report.authoritative_battery_end_energy_wh
        == reconciliation.authoritative_end_energy_wh,
        "authoritative reconciled battery endpoint",
    )
    _require_demonstrated(
        degradation is not None
        and report.end_battery_retention
        == degradation.end_usable_capacity_retention,
        "battery degradation endpoint",
    )
    transition_by_id = {
        item.node_id: item.end_temperature_k
        for item in thermal.eps_thermal_coupling_result.thermal_result
        .node_transitions
    }
    _require_demonstrated(
        all(
            item.end_temperature_k == transition_by_id[item.node_id]
            for item in report.thermal_node_temperatures
        ),
        "thermal proposal endpoints",
    )
    _require_demonstrated(
        report.mission_state_unchanged,
        "mission state remains unchanged",
    )


def _verify_nonauthorized_case(
    report: ImagingCaseReport,
    expected_service_status: AcquisitionServiceStatus | None,
) -> None:
    _require_demonstrated(
        report.authorization_status
        is not ImagingExecutionAuthorizationStatus.AUTHORIZED,
        f"{report.name} status",
    )
    _require_demonstrated(
        report.acquisition_service_status is expected_service_status,
        f"{report.name} electrical classification",
    )
    _require_demonstrated(
        not report.step_result_present,
        f"{report.name} has no StepResult",
    )
    _require_demonstrated(
        report.context_unchanged and report.authoritative_identity_unchanged,
        f"{report.name} has no authoritative commit",
    )
    _require_demonstrated(
        report.battery_throughput_increment_wh is None,
        f"{report.name} has no degradation result",
    )
    _require_demonstrated(
        report.mission_state_unchanged,
        f"{report.name} leaves mission state unchanged",
    )


def run_v53_integrated_imaging_demo() -> V53IntegratedImagingDemoReport:
    """Run all four independent cases plus replay and repeat proofs."""
    case_contexts = tuple(_build_start_context() for _ in range(4))
    _require_demonstrated(
        all(context == case_contexts[0] for context in case_contexts[1:]),
        "four cases start from equivalent contexts",
    )

    authorized_context = case_contexts[0]
    authorized = _execute_case(
        "authorized",
        authorized_context,
        view_angle_from_nadir_deg=10.0,
        environment=_authorized_environment(),
    )
    sequence_infeasible = _execute_case(
        "sequence-infeasible",
        case_contexts[1],
        view_angle_from_nadir_deg=50.0,
        environment=_authorized_environment(),
    )
    full_service_impossible = _execute_case(
        "full-service-impossible",
        case_contexts[2],
        view_angle_from_nadir_deg=10.0,
        environment=_impossible_environment(),
    )
    service_allocation_required = _execute_case(
        "service-allocation-required",
        case_contexts[3],
        view_angle_from_nadir_deg=10.0,
        environment=_allocation_environment(),
    )

    _verify_authorized_case(authorized)
    _verify_nonauthorized_case(sequence_infeasible, None)
    _require_demonstrated(
        sequence_infeasible.authorization_status
        is ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE,
        "supported sequence-infeasible classification",
    )
    _verify_nonauthorized_case(
        full_service_impossible,
        AcquisitionServiceStatus.FULL_SERVICE_IMPOSSIBLE,
    )
    _verify_nonauthorized_case(
        service_allocation_required,
        AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED,
    )

    checkpoint_source = _build_start_context()
    checkpoint = CheckpointState.from_context(checkpoint_source)
    replay_context = checkpoint.restore(checkpoint_source.inputs)
    replay = _execute_case(
        "authorized",
        replay_context,
        view_angle_from_nadir_deg=10.0,
        environment=_authorized_environment(),
    )
    repeat_context = _build_start_context()
    repeat = _execute_case(
        "authorized",
        repeat_context,
        view_angle_from_nadir_deg=10.0,
        environment=_authorized_environment(),
    )

    replay_attempt_equal = authorized.attempt == replay.attempt
    replay_context_equal = authorized_context == replay_context
    repeat_attempt_equal = authorized.attempt == repeat.attempt
    repeat_context_equal = authorized_context == repeat_context
    _require_demonstrated(
        replay_attempt_equal and replay_context_equal,
        "checkpoint replay equivalence",
    )
    _require_demonstrated(
        repeat_attempt_equal and repeat_context_equal,
        "deterministic repeat equivalence",
    )
    _require_demonstrated(
        checkpoint.schema_version == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5,
        "checkpoint schema is 5",
    )

    return V53IntegratedImagingDemoReport(
        authorized,
        sequence_infeasible,
        full_service_impossible,
        service_allocation_required,
        _reference_sample_grid(),
        replay_attempt_equal,
        replay_context_equal,
        repeat_attempt_equal,
        repeat_context_equal,
        checkpoint.schema_version,
    )


def _service_text(report: ImagingCaseReport) -> str:
    status = report.acquisition_service_status
    return "not-evaluated" if status is None else status.value


def main() -> None:
    """Print a concise deterministic summary of the F4A demonstration."""
    report = run_v53_integrated_imaging_demo()
    print("V5.3 synthetic integrated imaging release demonstration")
    print(
        "Not a calibrated KazEOSat scenario; no mission, product, storage, "
        "downlink, or delivery claim."
    )
    for case in (
        report.authorized,
        report.sequence_infeasible,
        report.full_service_impossible,
        report.service_allocation_required,
    ):
        print(
            f"{case.name}: authorization={case.authorization_status.value} "
            f"service={_service_text(case)} "
            f"step_result={str(case.step_result_present).lower()} "
            f"time_s={case.committed_context_time_seconds} "
            f"completed_steps={case.committed_completed_steps}"
        )
    authorized = report.authorized
    print(
        "authorized resources: "
        f"requested_W={authorized.total_eps_requested_power_w} "
        f"served_W={authorized.aggregate_served_power_w} "
        f"unmet_W={authorized.aggregate_unmet_power_w} "
        f"sample_grid_proxy_bytes={authorized.sample_grid_proxy_bytes}"
    )
    reference = report.reference_sample_grid
    print(
        "20 km x 20 km reference: "
        f"samples={reference.total_equivalent_samples} "
        f"bits={reference.sample_grid_proxy_bits} "
        f"sample_grid_proxy_bytes={reference.sample_grid_proxy_bytes} "
        "density_Mbit_per_km2="
        f"{reference.sample_grid_proxy_megabits_per_square_km}"
    )
    print(reference.interpretation)
    print(
        "replay_equal="
        f"{str(report.replay_attempt_equal and report.replay_context_equal).lower()} "
        "repeat_equal="
        f"{str(report.repeat_attempt_equal and report.repeat_context_equal).lower()} "
        f"checkpoint_schema={report.checkpoint_schema_version}"
    )


__all__ = [
    "ImagingCaseReport",
    "ReferenceSampleGridReport",
    "ThermalNodeTemperatureReport",
    "V53IntegratedImagingDemoReport",
    "run_v53_integrated_imaging_demo",
]


if __name__ == "__main__":
    main()
