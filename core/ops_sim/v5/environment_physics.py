"""Atomic pure EPS/thermal proposals from the opt-in B39 forcing adapter."""
from dataclasses import dataclass

from .environment_forcing import (adapt_environment_forcing, EnvironmentForcingSchedule,
                                 EnvironmentForcingCell, _type)
from .eps_system import compute_eps_interval_transition, compute_eps_substep_transition
from .thermal_coupling import (compute_eps_thermal_interval_transition,
                              compute_eps_thermal_substep_transition)
from .configuration import EPSConfig
from .thermal_config import ThermalNetworkConfig
from .eps_capability import validate_eps_capability_for_config
from .integration_time import RationalSeconds, checked_duration
from .state import BatteryState, ThermalState, ThermalNodeState
from .ids import ThermalNodeId


@dataclass(frozen=True, slots=True)
class EnvironmentStateProposal:
    battery_energy_wh: float
    temperatures_k: tuple[tuple[ThermalNodeId, float], ...]

    def to_states(self):
        """Explicitly create fresh existing typed states; never mutate a context."""
        return BatteryState(self.battery_energy_wh), ThermalState(tuple(
            ThermalNodeState(n, t) for n, t in self.temperatures_k))


@dataclass(frozen=True, slots=True)
class EnvironmentPhysicalStep:
    cell_index: int
    forcing: EnvironmentForcingCell
    eps_result: object
    thermal_coupling_result: object
    proposal: EnvironmentStateProposal


@dataclass(frozen=True, slots=True)
class EnvironmentPhysicalResult:
    status: str
    reason: str | None
    schedule: EnvironmentForcingSchedule
    final_proposal: EnvironmentStateProposal | None
    trajectory: tuple[EnvironmentPhysicalStep, ...] | None
    unresolved_regions: tuple[EnvironmentForcingCell, ...] = ()
    diagnostic_prefix: tuple[EnvironmentPhysicalStep, ...] = ()
    failed_cell_index: int | None = None

    @property
    def coverage_id(self):
        return self.schedule.coverage_id


def _proposal(battery, thermal):
    return EnvironmentStateProposal(battery.energy_wh, tuple(
        (n.node_id, n.temperature_k) for n in thermal.node_states))


def compute_environment_transition(source, request, battery_state, eps_config,
                                   thermal_state, thermal_config, *, capability=None):
    """Nominal physical integration on every certified forcing cell, atomically.

    Invalid inputs raise before execution. Positive unresolved cells refuse the
    entire trajectory. Later primitive failures return a diagnostic prefix only.
    No protection/mission grant, checkpoint, degradation evolution or enclosure.
    """
    schedule = adapt_environment_forcing(source, request)
    _type(battery_state, BatteryState, "battery state")
    _type(thermal_state, ThermalState, "thermal state")
    _type(eps_config, EPSConfig, "EPS config")
    _type(thermal_config, ThermalNetworkConfig, "thermal config")
    if type(thermal_config.nodes) is not tuple or not 1 <= len(thermal_config.nodes) <= 64 or type(thermal_config.links) is not tuple or len(thermal_config.links) > 2016:
        raise ValueError("bounded physical network exceeded")
    # Validate and own fresh mutable proposals before any primitive is called.
    battery = BatteryState(battery_state.energy_wh)
    thermal = ThermalState(tuple(ThermalNodeState(n.node_id, n.temperature_k)
                                 for n in thermal_state.node_states))
    EPSConfig(eps_config.configuration_id, eps_config.battery, eps_config.solar_array)
    eps_config.battery.__post_init__()
    eps_config.solar_array.__post_init__()
    ThermalNetworkConfig(thermal_config.nodes, thermal_config.links, thermal_config.bus_node_id,
                         thermal_config.battery_node_id, thermal_config.payload_node_id)
    for n in thermal_config.nodes:
        n.__post_init__()
    for link in thermal_config.links:
        link.__post_init__()
    nodes = {n.node_id for n in thermal_config.nodes}
    if nodes != set(schedule.request.node_ids) or nodes != {n.node_id for n in thermal.node_states}:
        raise ValueError("physical state/configuration/forcing node sets differ")
    if capability is not None:
        validate_eps_capability_for_config(capability, eps_config)
    for c in schedule.cells:
        if c.end_seconds > c.start_seconds:
            checked_duration(RationalSeconds.from_fraction(c.end_seconds-c.start_seconds))
    unresolved = tuple(c for c in schedule.cells if c.assessment == "UNRESOLVED"
                       and c.end_seconds > c.start_seconds)
    if unresolved:
        return EnvironmentPhysicalResult("unresolved", "UNRESOLVED_SOURCE_SUPPORT",
                                         schedule, None, None, unresolved)
    prefix = []
    for i, c in enumerate(schedule.cells):
        duration = c.end_seconds-c.start_seconds
        if duration == 0:
            continue
        case = c.alternatives[0]
        try:
            if duration.denominator == 1:
                eps = compute_eps_interval_transition(battery, eps_config, case.eps_inputs,
                    dt_seconds=duration.numerator, capability=capability)
                coupling = compute_eps_thermal_interval_transition(thermal, thermal_config,
                    case.thermal_inputs, case.heat_source_inputs, eps, dt_seconds=duration.numerator)
            else:
                token = RationalSeconds.from_fraction(duration)
                eps = compute_eps_substep_transition(battery, eps_config, case.eps_inputs,
                    duration=token, capability=capability)
                coupling = compute_eps_thermal_substep_transition(thermal, thermal_config,
                    case.thermal_inputs, case.heat_source_inputs, eps, duration=token)
            battery = BatteryState(eps.battery.end_energy_wh)
            thermal = ThermalState(tuple(ThermalNodeState(n.node_id, n.end_temperature_k)
                for n in coupling.thermal_result.node_transitions))
            prefix.append(EnvironmentPhysicalStep(i, c, eps, coupling, _proposal(battery, thermal)))
        except (TypeError, ValueError, ArithmeticError) as error:
            return EnvironmentPhysicalResult("physical_failure", type(error).__name__+": "+str(error),
                schedule, None, None, (), tuple(prefix), i)
    return EnvironmentPhysicalResult("zero_duration" if not prefix else "complete", None,
                                     schedule, _proposal(battery, thermal), tuple(prefix))
