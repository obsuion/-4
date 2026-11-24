"""Pure single-interval optical-acquisition thermal composition."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

from .imaging_resources import ObservationAcquisitionEPSResult
from .state import ThermalState
from .thermal import ThermalIntervalInputs
from .thermal_config import ThermalNetworkConfig
from .thermal_coupling import (
    EPSThermalCouplingResult,
    ThermalHeatSourceInputs,
    compute_eps_thermal_interval_transition,
)
from .thermal_routing import (
    ComponentHeatRoutingConfig,
    RoutedInternalHeatResult,
    ServedPowerLedger,
    compose_routed_internal_heat_sources,
    compute_routed_internal_heat,
)


_ELECTRICAL_PROPOSAL_REQUIRED = (
    "electrical_result must contain a feasible acquisition and EPS proposal"
)


def _require_electrical_proposal(
    electrical_result: ObservationAcquisitionEPSResult,
) -> None:
    """Require the complete E1 proposal consumed by thermal composition."""
    acquisition_evaluation = getattr(
        electrical_result,
        "acquisition_evaluation",
        None,
    )
    if (
        getattr(acquisition_evaluation, "feasible", False) is not True
        or getattr(electrical_result, "eps_inputs", None) is None
        or getattr(electrical_result, "eps_capability_result", None) is None
        or getattr(electrical_result, "eps_result", None) is None
        or getattr(electrical_result, "service_bounds", None) is None
    ):
        raise ValueError(_ELECTRICAL_PROPOSAL_REQUIRED)


def _revalidate_electrical_result(
    electrical_result: ObservationAcquisitionEPSResult,
) -> None:
    """Revalidate E1 while preserving the E2 precondition error contract."""
    try:
        replace(electrical_result)
    except (TypeError, ValueError):
        _require_electrical_proposal(electrical_result)
        raise
    _require_electrical_proposal(electrical_result)


def _revalidate_routing_config(
    routing_config: ComponentHeatRoutingConfig,
) -> None:
    """Reapply the complete reviewed route and parameter contracts."""
    replace(routing_config)
    for route in routing_config.routes:
        for field in fields(route)[2:]:
            replace(getattr(route, field.name))


def _revalidate_thermal_config(
    thermal_config: ThermalNetworkConfig,
) -> None:
    """Reapply the reviewed network and nested scalar contracts."""
    replace(thermal_config)
    for node in thermal_config.nodes:
        replace(node)
        for field in fields(node)[1:]:
            replace(getattr(node, field.name))
    for link in thermal_config.links:
        replace(link)
        for field in fields(link)[3:]:
            replace(getattr(link, field.name))


@dataclass(frozen=True, slots=True)
class ObservationAcquisitionSingleIntervalThermalProposal:
    """One transient acquisition-length thermal proposal, not a commit."""

    electrical_result: ObservationAcquisitionEPSResult
    routed_internal_heat_result: RoutedInternalHeatResult
    eps_thermal_coupling_result: EPSThermalCouplingResult

    def __post_init__(self) -> None:
        contracts = (
            (
                "electrical_result",
                self.electrical_result,
                ObservationAcquisitionEPSResult,
            ),
            (
                "routed_internal_heat_result",
                self.routed_internal_heat_result,
                RoutedInternalHeatResult,
            ),
            (
                "eps_thermal_coupling_result",
                self.eps_thermal_coupling_result,
                EPSThermalCouplingResult,
            ),
        )
        for field_name, value, expected_type in contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )

        _revalidate_electrical_result(self.electrical_result)
        replace(self.routed_internal_heat_result)
        replace(self.eps_thermal_coupling_result)


def evaluate_observation_acquisition_single_interval_thermal_proposal(
    electrical_result: ObservationAcquisitionEPSResult,
    served_power_ledger: ServedPowerLedger,
    routing_config: ComponentHeatRoutingConfig,
    thermal_state: ThermalState,
    thermal_config: ThermalNetworkConfig,
    thermal_inputs: ThermalIntervalInputs,
    external_heat_sources: ThermalHeatSourceInputs,
) -> ObservationAcquisitionSingleIntervalThermalProposal:
    """Return one V5.2 thermal proposal from an explicit service allocation.

    The interval is the E1 acquisition-length EPS interval and is evaluated as
    one explicit-Euler step. It is not a convergence or operational-feasibility
    claim. ``external_heat_sources`` supplies absorbed solar, albedo, and
    Earth-IR heat; its internal-dissipation values are placeholders replaced by
    the routed component heat rather than added to it.
    """
    contracts = (
        (
            "electrical_result",
            electrical_result,
            ObservationAcquisitionEPSResult,
        ),
        ("served_power_ledger", served_power_ledger, ServedPowerLedger),
        ("routing_config", routing_config, ComponentHeatRoutingConfig),
        ("thermal_state", thermal_state, ThermalState),
        ("thermal_config", thermal_config, ThermalNetworkConfig),
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

    _revalidate_electrical_result(electrical_result)
    replace(served_power_ledger)
    _revalidate_routing_config(routing_config)
    replace(thermal_state)
    _revalidate_thermal_config(thermal_config)
    replace(thermal_inputs)
    replace(external_heat_sources)
    routed_internal_heat_result = compute_routed_internal_heat(
        electrical_result.eps_inputs.load_breakdown,
        served_power_ledger,
        routing_config,
        thermal_config,
        eps_result=electrical_result.eps_result,
    )
    composed_heat_sources = compose_routed_internal_heat_sources(
        routed_internal_heat_result,
        external_heat_sources,
    )
    dt_seconds = electrical_result.eps_result.battery.dt_seconds
    eps_thermal_coupling_result = compute_eps_thermal_interval_transition(
        thermal_state,
        thermal_config,
        thermal_inputs,
        composed_heat_sources,
        electrical_result.eps_result,
        dt_seconds=dt_seconds,
    )
    return ObservationAcquisitionSingleIntervalThermalProposal(
        electrical_result,
        routed_internal_heat_result,
        eps_thermal_coupling_result,
    )


__all__ = [
    "ObservationAcquisitionSingleIntervalThermalProposal",
    "evaluate_observation_acquisition_single_interval_thermal_proposal",
]
