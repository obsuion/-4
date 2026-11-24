"""Explicit whole-interval downlink demand and transient physical evidence.

The transmitter is on for the entire contact, including unused data capacity.
All seven component loads require full service; this is not load arbitration.
Equations remain owned by EPS, thermal routing/coupling and degradation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING

from .communications import ServiceableGroundContact
from .degradation import SolarDegradationForcingInput
from .downlink import DownlinkTransmissionResult
from .eps_capability import EPSCapabilityResult, compute_eps_capability
from .eps_system import EPSIntervalInputs, EPSIntervalResult, compute_eps_interval_transition
from .ids import ParameterId
from .parameters import ScalarParameter
from .power_loads import PowerLoadBreakdown
from .provenance import ProvenanceClass
from .thermal import ThermalIntervalInputs
from .thermal_coupling import EPSThermalCouplingResult, ThermalHeatSourceInputs, compute_eps_thermal_interval_transition
from .thermal_routing import (
    ComponentHeatRoutingConfig, ElectricalLoadComponent, RoutedInternalHeatResult,
    ServedComponentPower, ServedPowerLedger, compute_routed_internal_heat,
    compose_routed_internal_heat_sources,
)

if TYPE_CHECKING:
    from .engine import StepResult


@dataclass(frozen=True, slots=True)
class DownlinkTransmitterConfig:
    """Bus-side on-state demand; no bitrate-to-power conversion is inferred."""

    electrical_power_w: ScalarParameter

    def __post_init__(self) -> None:
        parameter = self.electrical_power_w
        if type(parameter) is not ScalarParameter:
            raise TypeError("electrical_power_w must be a ScalarParameter")
        parameter.__post_init__()
        parameter.provenance.__post_init__()
        if (type(parameter.parameter_id) is not ParameterId
                or parameter.parameter_id.value != "communications.transmitter-electrical-power"):
            raise ValueError("transmitter power requires its semantic ParameterId")
        if parameter.units != "W" or parameter.value <= 0 or float(parameter.value) <= 0:
            raise ValueError("transmitter electrical power must be positive and representable in W")
        if (not parameter.provenance.source_ids
                and parameter.provenance.classification is not ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION):
            raise ValueError("transmitter power requires sources or an explicit model assumption")


@dataclass(frozen=True, slots=True)
class CoupledDownlinkInputs:
    """Constant full-step forcing; communications belongs only to transmitter.

    External heat sources must have zero internal dissipation: that term is
    supplied exclusively by routing actually serviced electrical components.
    Explicit absorbed radiation must not duplicate the thermal sink forcing.
    """

    transmitter: DownlinkTransmitterConfig
    baseline_loads: PowerLoadBreakdown
    sunlit: bool
    incidence_angle_deg: float
    routing_config: ComponentHeatRoutingConfig
    thermal_inputs: ThermalIntervalInputs
    external_heat_sources: ThermalHeatSourceInputs
    solar_degradation_forcing: SolarDegradationForcingInput | None

    def __post_init__(self) -> None:
        for name, owner in (
            ("transmitter", DownlinkTransmitterConfig),
            ("baseline_loads", PowerLoadBreakdown),
            ("routing_config", ComponentHeatRoutingConfig),
            ("thermal_inputs", ThermalIntervalInputs),
            ("external_heat_sources", ThermalHeatSourceInputs),
        ):
            value = getattr(self, name)
            if type(value) is not owner:
                raise TypeError(f"{name} must be an exact {owner.__name__}")
            value.__post_init__()
        if self.baseline_loads.communications_w != 0:
            raise ValueError("baseline communications_w must be zero; transmitter owns that demand")
        EPSIntervalInputs(self.sunlit, self.incidence_angle_deg, self.baseline_loads)
        if any(source.internal_dissipation_w != 0 for source in self.external_heat_sources.node_sources):
            raise ValueError("external heat sources must not supply internal dissipation")
        if self.solar_degradation_forcing is not None:
            if type(self.solar_degradation_forcing) is not SolarDegradationForcingInput:
                raise TypeError("solar forcing must be SolarDegradationForcingInput or explicit None")
            self.solar_degradation_forcing.__post_init__()

    @property
    def eps_inputs(self) -> EPSIntervalInputs:
        return EPSIntervalInputs(
            self.sunlit, self.incidence_angle_deg,
            replace(self.baseline_loads, communications_w=self.transmitter.electrical_power_w.value),
        )


def validate_coupled_downlink_inputs(inputs: CoupledDownlinkInputs, network) -> CoupledDownlinkInputs:
    """Rebuild the exact allowlisted graph, including nested numeric provenance.

    This entry point deliberately shares the experiment codec's closed scalar
    contract, so direct calls cannot admit forcing that the bundle cannot bind.
    """
    from .experiment_codec import canonical_copy

    if type(inputs) is not CoupledDownlinkInputs:
        raise TypeError("physical_inputs must be CoupledDownlinkInputs")
    checked = canonical_copy(inputs)
    node_ids = {node.node_id for node in network.nodes}
    if {x.node_id for x in checked.thermal_inputs.node_boundaries} != node_ids:
        raise ValueError("thermal boundaries must cover exactly the configured nodes")
    if {x.node_id for x in checked.external_heat_sources.node_sources} != node_ids:
        raise ValueError("external heat must cover exactly the configured nodes")
    if any(route.thermal_node_id not in node_ids for route in checked.routing_config.routes):
        raise ValueError("heat route must name a configured thermal node")
    return checked


def route_fully_served_downlink_heat(eps_result, routing_config, network) -> RoutedInternalHeatResult:
    """Allocate only the already established full EPS service, never prioritize."""
    if eps_result.battery.unmet_load_w != 0:
        raise ValueError("full required electrical service was not established")
    loads = eps_result.loads
    ledger = ServedPowerLedger(tuple(
        ServedComponentPower(component, power, power)
        for component in ElectricalLoadComponent
        for power in (getattr(loads, component.value.replace("-", "_") + "_w"),)
    ))
    return compute_routed_internal_heat(
        loads, ledger, routing_config, network, eps_result=eps_result,
    )


class CoupledDownlinkDenialReason(str, Enum):
    INSUFFICIENT_ELECTRICAL_SERVICE = "insufficient-electrical-service"


@dataclass(frozen=True, slots=True)
class CoupledDownlinkResourceProposal:
    """Pure electrical authorization and optional thermal proposal; no mutation."""

    eps_result: EPSIntervalResult
    eps_capability_result: EPSCapabilityResult
    routed_heat_result: RoutedInternalHeatResult | None
    thermal_coupling_result: EPSThermalCouplingResult | None

    @property
    def authorized(self) -> bool:
        return self.eps_result.battery.unmet_load_w == 0


def evaluate_coupled_downlink_resources(
    battery_state, degradation_state, thermal_state, eps_config, thermal_config,
    inputs: CoupledDownlinkInputs, *, dt_seconds: int,
) -> CoupledDownlinkResourceProposal:
    """Compose existing pure owners, like imaging resource/thermal proposals.

    No data, degradation, reconciliation, clock or state transition is applied
    here. The engine's shared physical completion remains their sole owner.
    """
    capability = compute_eps_capability(eps_config, degradation_state)
    eps = compute_eps_interval_transition(
        battery_state, eps_config, inputs.eps_inputs,
        dt_seconds=dt_seconds, capability=capability,
    )
    if eps.battery.unmet_load_w != 0:
        return CoupledDownlinkResourceProposal(eps, capability, None, None)
    routed = route_fully_served_downlink_heat(eps, inputs.routing_config, thermal_config)
    sources = compose_routed_internal_heat_sources(routed, inputs.external_heat_sources)
    thermal = compute_eps_thermal_interval_transition(
        thermal_state, thermal_config, inputs.thermal_inputs, sources, eps,
        dt_seconds=dt_seconds,
    )
    return CoupledDownlinkResourceProposal(eps, capability, routed, thermal)


@dataclass(frozen=True, slots=True)
class CoupledDownlinkAttempt:
    """A committed full-step result or an uncommitted electrical proposal.

    A denied EPS proposal is diagnostic evidence, not an applied transition.
    No data/thermal evidence is reported as executed on denial.
    """

    contact: ServiceableGroundContact
    physical_inputs: CoupledDownlinkInputs
    eps_result: EPSIntervalResult
    eps_capability_result: EPSCapabilityResult
    transmission_result: DownlinkTransmissionResult | None
    routed_heat_result: RoutedInternalHeatResult | None
    step_result: StepResult | None

    def __post_init__(self) -> None:
        from .engine import StepResult

        for value, owner in (
            (self.contact, ServiceableGroundContact),
            (self.physical_inputs, CoupledDownlinkInputs),
            (self.eps_result, EPSIntervalResult),
            (self.eps_capability_result, EPSCapabilityResult),
        ):
            if type(value) is not owner:
                raise TypeError(f"expected exact {owner.__name__}")
            value.__post_init__()
        eps = self.eps_result
        eps.battery.__post_init__()
        eps.solar.__post_init__()
        eps.loads.__post_init__()
        if eps.loads != self.physical_inputs.eps_inputs.load_breakdown:
            raise ValueError("EPS loads must equal the declared required loads")
        if eps.battery.load_w != eps.loads.total_load_w:
            raise ValueError("EPS battery demand must equal the component total")
        duration = self.contact.end_time_seconds - self.contact.start_time_seconds
        if eps.battery.dt_seconds != duration:
            raise ValueError("EPS and contact must describe the same interval")
        if not self.authorized:
            if any(x is not None for x in (self.transmission_result, self.routed_heat_result, self.step_result)):
                raise ValueError("denial must not contain committed data/physical evidence")
            return
        for value, owner in ((self.transmission_result, DownlinkTransmissionResult),
                             (self.routed_heat_result, RoutedInternalHeatResult),
                             (self.step_result, StepResult)):
            if type(value) is not owner:
                raise TypeError(f"authorized attempt requires {owner.__name__}")
            value.__post_init__()
        step = self.step_result
        if self.transmission_result.capacity_proposal.contact is not self.contact:
            raise ValueError("transmission must retain the admitted contact")
        if (step.start_time_seconds != self.contact.start_time_seconds
                or step.end_time_seconds != self.contact.end_time_seconds):
            raise ValueError("step and contact must describe the same interval")
        if step.eps_result is not eps or step.eps_capability_result is not self.eps_capability_result:
            raise ValueError("step must reuse the authoritative EPS evidence")
        if any(x is None for x in (step.thermal_coupling_result, step.battery_degradation_result,
                                  step.battery_capacity_reconciliation_result)):
            raise ValueError("authorized downlink requires the complete coupled physical result")
        step.thermal_coupling_result.__post_init__()
        step.thermal_coupling_result.thermal_result.__post_init__()
        step.battery_degradation_result.__post_init__()
        step.battery_capacity_reconciliation_result.__post_init__()
        if step.thermal_coupling_result.thermal_result.dt_seconds != duration:
            raise ValueError("thermal evolution and contact must describe the same interval")
        if step.battery_degradation_result.dt_seconds != duration:
            raise ValueError("ageing and contact must describe the same interval")
        if step.battery_capacity_reconciliation_result.proposed_end_energy_wh != eps.battery.end_energy_wh:
            raise ValueError("reconciliation must start from the authoritative EPS proposal")
        if (step.battery_capacity_reconciliation_result.end_capacity_retention
                != step.battery_degradation_result.end_usable_capacity_retention):
            raise ValueError("reconciliation must use this interval's end retention")
        if ((step.solar_degradation_result is None)
                != (self.physical_inputs.solar_degradation_forcing is None)):
            raise ValueError("solar degradation evidence must match explicit forcing presence")
        if step.solar_degradation_result is not None:
            step.solar_degradation_result.__post_init__()
            if step.solar_degradation_result.retention_loss != self.physical_inputs.solar_degradation_forcing.retention_loss:
                raise ValueError("solar degradation must apply the declared forcing")

    @property
    def authorized(self) -> bool:
        return self.eps_result.battery.unmet_load_w == 0

    @property
    def time_advanced(self) -> bool:
        return self.step_result is not None

    @property
    def denial_reason(self) -> CoupledDownlinkDenialReason | None:
        return None if self.authorized else CoupledDownlinkDenialReason.INSUFFICIENT_ELECTRICAL_SERVICE


__all__ = ["DownlinkTransmitterConfig", "CoupledDownlinkInputs", "CoupledDownlinkAttempt",
           "CoupledDownlinkDenialReason"]
