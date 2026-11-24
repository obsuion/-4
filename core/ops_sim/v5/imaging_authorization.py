"""Pure current-step imaging authorization and proposal composition."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

from .context import SimulationContext
from .imaging_execution import (
    ImagingExecutionAuthorizationStatus,
    ScheduledObservationAcquisitionExecution,
)
from .imaging_resources import (
    AcquisitionEPSIntervalEnvironment,
    AcquisitionServiceStatus,
    ObservationAcquisitionEPSResult,
    evaluate_observation_acquisition_eps,
)
from .imaging_thermal import (
    ObservationAcquisitionSingleIntervalThermalProposal,
    evaluate_observation_acquisition_single_interval_thermal_proposal,
)
from .observation_feasibility import ScheduledObservationExecution
from .thermal import ThermalIntervalInputs
from .thermal_coupling import ThermalHeatSourceInputs
from .thermal_routing import (
    ComponentHeatRoutingConfig,
    ElectricalLoadComponent,
    ServedComponentPower,
    ServedPowerLedger,
)


_LOAD_FIELD_BY_COMPONENT = (
    (ElectricalLoadComponent.BASE_BUS, "base_bus_w"),
    (ElectricalLoadComponent.OBC, "obc_w"),
    (ElectricalLoadComponent.ADCS, "adcs_w"),
    (ElectricalLoadComponent.PAYLOAD, "payload_w"),
    (ElectricalLoadComponent.COMMUNICATIONS, "communications_w"),
    (ElectricalLoadComponent.THERMAL_CONTROL, "thermal_control_w"),
    (ElectricalLoadComponent.PROPULSION, "propulsion_w"),
)


def _revalidate_eps_config(eps_config: object) -> None:
    replace(eps_config)
    replace(eps_config.configuration_id)
    replace(eps_config.battery.configuration_id)
    for field in fields(eps_config.battery)[1:]:
        replace(getattr(eps_config.battery, field.name))
    replace(eps_config.battery)
    replace(eps_config.solar_array.configuration_id)
    for field in fields(eps_config.solar_array)[1:]:
        replace(getattr(eps_config.solar_array, field.name))
    replace(eps_config.solar_array)


def _revalidate_thermal_config(thermal_config: object) -> None:
    replace(thermal_config)
    for node in thermal_config.nodes:
        replace(node)
        for field in fields(node)[1:]:
            replace(getattr(node, field.name))
    for link in thermal_config.links:
        replace(link)
        for field in fields(link)[3:]:
            replace(getattr(link, field.name))


def _revalidate_routing_config(
    routing_config: ComponentHeatRoutingConfig,
) -> None:
    replace(routing_config)
    for route in routing_config.routes:
        for field in fields(route)[2:]:
            replace(getattr(route, field.name))


def _revalidate_context(context: SimulationContext) -> None:
    replace(context.inputs)
    replace(context.inputs.numerical_config)

    spacecraft_config = context.inputs.spacecraft_configuration
    replace(spacecraft_config)
    replace(spacecraft_config.adcs)
    replace(spacecraft_config.adcs.agile_pointing)
    replace(spacecraft_config.payload)
    replace(spacecraft_config.payload.optical_acquisition)
    _revalidate_eps_config(spacecraft_config.eps)
    replace(spacecraft_config.thermal)
    _revalidate_thermal_config(spacecraft_config.thermal.network)

    spacecraft_state = context.spacecraft_state
    replace(spacecraft_state)
    replace(spacecraft_state.battery)
    replace(spacecraft_state.degradation)
    replace(spacecraft_state.thermal)
    replace(context)


def _all_requested_served_power(
    electrical_result: ObservationAcquisitionEPSResult,
) -> ServedPowerLedger:
    loads = electrical_result.eps_inputs.load_breakdown
    return ServedPowerLedger(
        tuple(
            ServedComponentPower(
                component,
                getattr(loads, field_name),
                getattr(loads, field_name),
            )
            for component, field_name in _LOAD_FIELD_BY_COMPONENT
        )
    )


@dataclass(frozen=True, slots=True)
class ImagingExecutionAuthorizationResult:
    """Transient F2 authorization evidence without authoritative commit."""

    execution: ScheduledObservationAcquisitionExecution
    electrical_result: ObservationAcquisitionEPSResult
    thermal_proposal: (
        ObservationAcquisitionSingleIntervalThermalProposal | None
    )
    status: ImagingExecutionAuthorizationStatus

    def __post_init__(self) -> None:
        if type(self.execution) is not ScheduledObservationAcquisitionExecution:
            raise TypeError(
                "execution must be a "
                "ScheduledObservationAcquisitionExecution"
            )
        if type(self.electrical_result) is not ObservationAcquisitionEPSResult:
            raise TypeError(
                "electrical_result must be an ObservationAcquisitionEPSResult"
            )
        if self.thermal_proposal is not None and type(
            self.thermal_proposal
        ) is not ObservationAcquisitionSingleIntervalThermalProposal:
            raise TypeError(
                "thermal_proposal must be an "
                "ObservationAcquisitionSingleIntervalThermalProposal or None"
            )
        if type(self.status) is not ImagingExecutionAuthorizationStatus:
            raise TypeError(
                "status must be an ImagingExecutionAuthorizationStatus"
            )

        replace(self.execution)
        replace(self.electrical_result)
        if self.thermal_proposal is not None:
            replace(self.thermal_proposal)

        feasible = self.electrical_result.acquisition_evaluation.feasible
        eps_result = self.electrical_result.eps_result
        service_bounds = self.electrical_result.service_bounds
        if self.status is ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE:
            if feasible:
                raise ValueError(
                    "SEQUENCE_INFEASIBLE requires an infeasible acquisition"
                )
            if eps_result is not None or service_bounds is not None:
                raise ValueError(
                    "SEQUENCE_INFEASIBLE requires no EPS proposal"
                )
            if self.thermal_proposal is not None:
                raise ValueError(
                    "SEQUENCE_INFEASIBLE requires thermal_proposal to be None"
                )
            return

        if not feasible or eps_result is None or service_bounds is None:
            raise ValueError(
                "electrical authorization statuses require a feasible "
                "acquisition and EPS proposal"
            )
        full_service_established = (
            service_bounds.status is AcquisitionServiceStatus.FULLY_SERVED
            and eps_result.battery.unmet_load_w == 0
        )
        if self.status is (
            ImagingExecutionAuthorizationStatus
            .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED
        ):
            if full_service_established:
                raise ValueError(
                    "ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED requires full "
                    "electrical service not to be established"
                )
            if self.thermal_proposal is not None:
                raise ValueError(
                    "ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED requires "
                    "thermal_proposal to be None"
                )
            return

        if not full_service_established:
            raise ValueError(
                "AUTHORIZED requires FULLY_SERVED and exactly zero unmet load"
            )
        if self.thermal_proposal is None:
            raise ValueError("AUTHORIZED requires a thermal_proposal")
        if self.thermal_proposal.electrical_result is not self.electrical_result:
            raise ValueError(
                "thermal_proposal must contain the same electrical_result"
            )


def evaluate_imaging_engine_step_authorization(
    context: SimulationContext,
    previous_execution: ScheduledObservationExecution,
    execution: ScheduledObservationAcquisitionExecution,
    environment: AcquisitionEPSIntervalEnvironment,
    routing_config: ComponentHeatRoutingConfig,
    thermal_inputs: ThermalIntervalInputs,
    external_heat_sources: ThermalHeatSourceInputs,
) -> ImagingExecutionAuthorizationResult:
    """Evaluate current-step electrical and thermal prerequisites purely."""
    contracts = (
        ("context", context, SimulationContext),
        (
            "previous_execution",
            previous_execution,
            ScheduledObservationExecution,
        ),
        (
            "execution",
            execution,
            ScheduledObservationAcquisitionExecution,
        ),
        (
            "environment",
            environment,
            AcquisitionEPSIntervalEnvironment,
        ),
        (
            "routing_config",
            routing_config,
            ComponentHeatRoutingConfig,
        ),
        ("thermal_inputs", thermal_inputs, ThermalIntervalInputs),
        (
            "external_heat_sources",
            external_heat_sources,
            ThermalHeatSourceInputs,
        ),
    )
    for field_name, value, expected_type in contracts:
        if type(value) is not expected_type:
            raise TypeError(
                f"{field_name} must be a {expected_type.__name__}"
            )

    _revalidate_context(context)
    replace(previous_execution)
    replace(execution)
    replace(environment)
    _revalidate_routing_config(routing_config)
    replace(thermal_inputs)
    replace(external_heat_sources)

    if execution.scheduled_start_seconds != context.simulation_time_seconds:
        raise ValueError(
            "execution scheduled start must equal current context time"
        )
    configured_dt_seconds = context.inputs.numerical_config.timestep_seconds
    acquisition_duration_seconds = (
        execution.candidate.acquisition_input.imaging_duration_seconds
    )
    if acquisition_duration_seconds != configured_dt_seconds:
        raise ValueError(
            "acquisition duration must equal configured engine timestep"
        )

    spacecraft_config = context.inputs.spacecraft_configuration
    electrical_result = evaluate_observation_acquisition_eps(
        spacecraft_config.adcs.agile_pointing,
        spacecraft_config.payload.optical_acquisition,
        spacecraft_config.eps,
        context.spacecraft_state.battery,
        context.spacecraft_state.degradation,
        previous_execution,
        execution.candidate,
        environment,
    )
    if type(electrical_result) is not ObservationAcquisitionEPSResult:
        raise TypeError(
            "E1 must return an ObservationAcquisitionEPSResult"
        )
    replace(electrical_result)
    if not electrical_result.acquisition_evaluation.feasible:
        return ImagingExecutionAuthorizationResult(
            execution,
            electrical_result,
            None,
            ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE,
        )

    candidate_next_start_seconds = (
        electrical_result.acquisition_evaluation.sequence_result
        .candidate_next_start_seconds
    )
    if execution.scheduled_start_seconds < candidate_next_start_seconds:
        raise ValueError(
            "execution scheduled start must not precede C3 readiness"
        )

    eps_result = electrical_result.eps_result
    service_bounds = electrical_result.service_bounds
    if (
        service_bounds.status is not AcquisitionServiceStatus.FULLY_SERVED
        or eps_result.battery.unmet_load_w != 0
    ):
        return ImagingExecutionAuthorizationResult(
            execution,
            electrical_result,
            None,
            ImagingExecutionAuthorizationStatus
            .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED,
        )

    served_power_ledger = _all_requested_served_power(electrical_result)
    thermal_proposal = (
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            electrical_result,
            served_power_ledger,
            routing_config,
            context.spacecraft_state.thermal,
            spacecraft_config.thermal.network,
            thermal_inputs,
            external_heat_sources,
        )
    )
    return ImagingExecutionAuthorizationResult(
        execution,
        electrical_result,
        thermal_proposal,
        ImagingExecutionAuthorizationStatus.AUTHORIZED,
    )


__all__ = [
    "ImagingExecutionAuthorizationResult",
    "evaluate_imaging_engine_step_authorization",
]
