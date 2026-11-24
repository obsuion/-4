"""Composable deterministic and seeded-external scenario hooks."""

from collections import defaultdict

from .config import DEFAULT_CONFIG, SimulationConfig
from .event_catalog import (
    EventCatalog,
    ExternalEvent,
    generate_stochastic_event_catalog,
    validate_debris_damage_targets,
)
from .models import ContactInfo, Mode, SatelliteState


class Scenario:
    name = "nominal"

    def apply_pre_hour(self, state: SatelliteState, hour: int) -> None:
        pass

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return contact_info

    def apply_post_hour(self, state: SatelliteState, hour: int) -> None:
        pass

    def events_at_hour(self, hour: int) -> list[tuple[str, str]]:
        return []

    def debris_conjunctions_at_hour(
        self, hour: int
    ) -> tuple[ExternalEvent, ...]:
        return ()

    @property
    def battery_degradation_multiplier(self) -> float:
        return DEFAULT_CONFIG.maximum_health

    @property
    def solar_degradation_multiplier(self) -> float:
        return DEFAULT_CONFIG.maximum_health

    @property
    def payload_degradation_multiplier(self) -> float:
        return DEFAULT_CONFIG.maximum_health

    @property
    def storage_degradation_multiplier(self) -> float:
        return DEFAULT_CONFIG.maximum_health

    @property
    def comms_degradation_multiplier(self) -> float:
        return DEFAULT_CONFIG.maximum_health

    @property
    def imaging_rate_multiplier(self) -> float:
        return DEFAULT_CONFIG.maximum_health

    @property
    def downlink_capacity_multiplier(self) -> float:
        return DEFAULT_CONFIG.maximum_health


class PostLifeScenario(Scenario):
    """Base for sustained stresses activated at the configured design-life edge."""

    event_type = "post_life_stress_begins"
    event_description = "Post-design-life stress proxy activated"

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.start_hour = int(
            round(config.post_life_stress_start_year * config.hours_per_year)
        )
        self.active = False

    def apply_pre_hour(self, state: SatelliteState, hour: int) -> None:
        self.active = hour >= self.start_hour

    def events_at_hour(self, hour: int) -> list[tuple[str, str]]:
        if hour == self.start_hour:
            return [(self.event_type, self.event_description)]
        return []

    def active_multiplier(self, multiplier: float) -> float:
        return multiplier if self.active else self.config.maximum_health


def _retain_sparse_contact(
    contact_info: ContactInfo,
    hour: int,
    config: SimulationConfig,
    keep_every_n: int,
) -> ContactInfo:
    opportunity = hour // config.contact_interval_hours
    if opportunity % keep_every_n:
        return ContactInfo()
    return contact_info


class ContactOutageScenario(Scenario):
    name = "contact_outage"

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.start_hour = int(round(config.outage_start_year * config.hours_per_year))
        self.end_hour = self.start_hour + config.outage_duration_days * config.hours_per_day

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        if self.start_hour <= hour < self.end_hour:
            return ContactInfo()
        return contact_info

    def events_at_hour(self, hour: int) -> list[tuple[str, str]]:
        if hour == self.start_hour:
            return [("contact_outage_begins", "Command and data contacts set to zero")]
        if hour == self.end_hour:
            return [("contact_outage_ends", "Synthetic contact schedule restored")]
        return []


class HighBatteryDegradationScenario(Scenario):
    name = "high_battery_degradation"

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    @property
    def battery_degradation_multiplier(self) -> float:
        return self.config.high_battery_degradation_multiplier


class SolarArrayDegradationScenario(PostLifeScenario):
    name = "solar_array_degradation"
    event_type = "solar_array_degradation_begins"
    event_description = "Accelerated solar-array degradation activated"

    @property
    def solar_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.solar_stress_degradation_multiplier)


class ReducedDownlinkCapacityScenario(PostLifeScenario):
    name = "reduced_downlink_capacity"
    event_type = "reduced_downlink_capacity_begins"
    event_description = "X-band throughput proxy reduced"

    @property
    def downlink_capacity_multiplier(self) -> float:
        return self.active_multiplier(self.config.reduced_downlink_capacity_multiplier)


class StoragePressureScenario(PostLifeScenario):
    name = "storage_pressure"
    event_type = "storage_pressure_begins"
    event_description = "Backlog injected and storage degradation accelerated"

    def apply_pre_hour(self, state: SatelliteState, hour: int) -> None:
        super().apply_pre_hour(state, hour)
        if hour == self.start_hour:
            backlog = self.config.storage_pressure_initial_fraction * self.config.storage_capacity_gb
            added = min(backlog, self.config.storage_capacity_gb - state.data_buffer_gb)
            state.data_buffer_gb += added
            state.total_data_generated_gb += added

    @property
    def storage_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.storage_pressure_degradation_multiplier)


class PayloadDegradationScenario(PostLifeScenario):
    name = "payload_degradation"
    event_type = "payload_degradation_begins"
    event_description = "Accelerated payload degradation activated"

    @property
    def payload_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.payload_stress_degradation_multiplier)


class CommsDegradationScenario(PostLifeScenario):
    name = "comms_degradation"
    event_type = "comms_degradation_begins"
    event_description = "Accelerated communications degradation activated"

    @property
    def comms_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.comms_stress_degradation_multiplier)


class LowContactAvailabilityScenario(PostLifeScenario):
    name = "low_contact_availability"
    event_type = "low_contact_availability_begins"
    event_description = "Only one in three synthetic contact opportunities retained"

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        if not self.active:
            return contact_info
        return _retain_sparse_contact(
            contact_info, hour, self.config, self.config.low_contact_keep_every_n
        )


class ExtendedNoContact30DaysScenario(PostLifeScenario):
    name = "extended_no_contact_30_days"
    event_type = "extended_no_contact_begins"
    event_description = "Thirty-day command and data blackout begins"

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        super().__init__(config)
        self.end_hour = self.start_hour + config.extended_outage_days * config.hours_per_day

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        if self.start_hour <= hour < self.end_hour:
            return ContactInfo()
        return contact_info

    def events_at_hour(self, hour: int) -> list[tuple[str, str]]:
        if hour == self.start_hour:
            return [(self.event_type, self.event_description)]
        if hour == self.end_hour:
            return [("extended_no_contact_ends", "Synthetic contacts restored after 30 days")]
        return []


class RepeatedShortOutagesScenario(PostLifeScenario):
    name = "repeated_short_outages"

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        super().__init__(config)
        self.period_hours = config.repeated_outage_period_days * config.hours_per_day
        self.duration_hours = config.repeated_outage_duration_days * config.hours_per_day

    def _cycle_offset(self, hour: int) -> int:
        return (hour - self.start_hour) % self.period_hours

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        if hour >= self.start_hour and self._cycle_offset(hour) < self.duration_hours:
            return ContactInfo()
        return contact_info

    def events_at_hour(self, hour: int) -> list[tuple[str, str]]:
        if hour < self.start_hour:
            return []
        offset = self._cycle_offset(hour)
        if offset == 0:
            return [("short_outage_begins", "Scheduled three-day contact outage begins")]
        if offset == self.duration_hours:
            return [("short_outage_ends", "Scheduled three-day contact outage ends")]
        return []


class HighImagingDemandScenario(PostLifeScenario):
    name = "high_imaging_demand"
    event_type = "high_imaging_demand_begins"
    event_description = "Image data volume per imaging hour increased"

    @property
    def imaging_rate_multiplier(self) -> float:
        return self.active_multiplier(self.config.high_imaging_demand_multiplier)


class AttitudePointingStressScenario(PostLifeScenario):
    name = "attitude_pointing_stress"
    event_type = "attitude_pointing_stress_begins"
    event_description = "ADCS-health and energy pointing proxies activated during imaging"

    def apply_post_hour(self, state: SatelliteState, hour: int) -> None:
        if self.active and state.mode == Mode.IMAGING:
            # TODO: replace this proxy with pointing-error/duty-cycle dynamics when
            # an attitude model exists. V1.5 has only placeholder ADCS health.
            state.adcs_health = max(
                self.config.minimum_health,
                state.adcs_health - self.config.attitude_imaging_adcs_penalty,
            )
            state.soc = max(
                self.config.minimum_percent,
                state.soc - self.config.attitude_imaging_soc_penalty,
            )


class CombinedEnergyStressScenario(PostLifeScenario):
    name = "combined_energy_stress"
    event_type = "combined_energy_stress_begins"
    event_description = "Battery, solar-array, and hourly energy-margin stresses activated"

    @property
    def battery_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.combined_energy_battery_multiplier)

    @property
    def solar_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.combined_energy_solar_multiplier)

    def apply_post_hour(self, state: SatelliteState, hour: int) -> None:
        if self.active:
            # TODO: replace fixed SOC margin with a solar-generation/load model.
            state.soc = max(
                self.config.minimum_percent,
                state.soc - self.config.combined_energy_soc_penalty,
            )


class ExtremeCompoundPostLifeStressScenario(PostLifeScenario):
    name = "extreme_compound_post_life_stress"
    event_type = "extreme_compound_stress_begins"
    event_description = "Boundary stress test activated; this is not a failure prediction"

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        super().__init__(config)
        self.blackout_start_hour = int(
            round(config.extreme_blackout_start_year * config.hours_per_year)
        )
        self.blackout_end_hour = (
            self.blackout_start_hour
            + config.extreme_blackout_duration_days * config.hours_per_day
        )

    def apply_pre_hour(self, state: SatelliteState, hour: int) -> None:
        super().apply_pre_hour(state, hour)
        if hour == self.start_hour:
            backlog = self.config.storage_pressure_initial_fraction * self.config.storage_capacity_gb
            added = min(backlog, self.config.storage_capacity_gb - state.data_buffer_gb)
            state.data_buffer_gb += added
            state.total_data_generated_gb += added

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        if self.blackout_start_hour <= hour < self.blackout_end_hour:
            return ContactInfo()
        if self.active:
            return _retain_sparse_contact(
                contact_info, hour, self.config, self.config.low_contact_keep_every_n
            )
        return contact_info

    def events_at_hour(self, hour: int) -> list[tuple[str, str]]:
        events = super().events_at_hour(hour)
        if hour == self.blackout_start_hour:
            events.append(("compound_blackout_begins", "Thirty-day compound-stress blackout begins"))
        if hour == self.blackout_end_hour:
            events.append(("compound_blackout_ends", "Compound-stress blackout ends"))
        return events

    @property
    def battery_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.extreme_battery_multiplier)

    @property
    def solar_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.extreme_solar_multiplier)

    @property
    def payload_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.extreme_payload_multiplier)

    @property
    def storage_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.storage_pressure_degradation_multiplier)

    @property
    def comms_degradation_multiplier(self) -> float:
        return self.active_multiplier(self.config.extreme_comms_multiplier)

    @property
    def imaging_rate_multiplier(self) -> float:
        return self.active_multiplier(self.config.high_imaging_demand_multiplier)

    @property
    def downlink_capacity_multiplier(self) -> float:
        return self.active_multiplier(self.config.reduced_downlink_capacity_multiplier)

    def apply_post_hour(self, state: SatelliteState, hour: int) -> None:
        if not self.active:
            return
        # TODO: replace fixed energy/ADCS penalties with coupled EPS and attitude
        # dynamics. These deterministic deductions are boundary-test proxies.
        state.soc = max(
            self.config.minimum_percent,
            state.soc - self.config.extreme_energy_soc_penalty,
        )
        if state.mode == Mode.IMAGING:
            state.adcs_health = max(
                self.config.minimum_health,
                state.adcs_health - self.config.extreme_attitude_imaging_adcs_penalty,
            )


class StochasticPostLifeEventsScenario(Scenario):
    """Apply one reusable, policy-independent external event catalog."""

    name = "stochastic_post_life_events"

    def __init__(
        self,
        config: SimulationConfig = DEFAULT_CONFIG,
        seed: int | None = None,
        total_hours: int | None = None,
        event_catalog: EventCatalog | None = None,
    ) -> None:
        self.config = config
        if event_catalog is not None:
            self.event_catalog = event_catalog
        elif total_hours is not None:
            self.event_catalog = generate_stochastic_event_catalog(
                seed, self.name, total_hours, config
            )
        else:
            self.event_catalog = EventCatalog([], seed, self.name, 0)

        self._starts: dict[int, list[ExternalEvent]] = defaultdict(list)
        self._health_hits: dict[int, list[tuple[str, float]]] = defaultdict(list)
        self._storage_upsets: dict[int, list[ExternalEvent]] = defaultdict(list)
        self._debris_conjunctions: dict[
            int, list[ExternalEvent]
        ] = defaultdict(list)
        self._contact_disruption_hours: set[int] = set()
        for event in self.event_catalog.events:
            self._starts[event.hour].append(event)
            end_hour = event.hour + event.duration_hours
            if event.event_type == "contact_disruption":
                self._contact_disruption_hours.update(range(event.hour, end_hour))
            elif event.event_type == "storage_upset":
                self._storage_upsets[event.hour].append(event)
            elif event.event_type == "debris_conjunction":
                validate_debris_damage_targets(event.target)
                for active_hour in range(event.hour, end_hour):
                    self._debris_conjunctions[active_hour].append(event)
            else:
                hourly_loss = event.effect / event.duration_hours
                targets = event.target.split(",")
                for active_hour in range(event.hour, end_hour):
                    for target in targets:
                        self._health_hits[active_hour].append((target, hourly_loss))

    def apply_pre_hour(self, state: SatelliteState, hour: int) -> None:
        for field_name, loss in self._health_hits.get(hour, ()):
            current = getattr(state, field_name)
            setattr(
                state,
                field_name,
                max(
                    self.config.minimum_health,
                    min(self.config.maximum_health, current - loss),
                ),
            )
        for event in self._storage_upsets.get(hour, ()):
            lost = min(state.data_buffer_gb, max(self.config.minimum_percent, event.effect))
            state.data_buffer_gb -= lost
            state.data_lost_gb += lost

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        if hour in self._contact_disruption_hours:
            return ContactInfo()
        return contact_info

    def events_at_hour(self, hour: int) -> list[tuple[str, str]]:
        return [
            (
                f"external_{event.event_type}",
                f"{event.description}; severity={event.severity:.3f}, "
                f"duration={event.duration_hours} h",
            )
            for event in self._starts.get(hour, ())
        ]

    def debris_conjunctions_at_hour(
        self, hour: int
    ) -> tuple[ExternalEvent, ...]:
        return tuple(self._debris_conjunctions.get(hour, ()))


SCENARIOS = {
    Scenario.name: Scenario,
    ContactOutageScenario.name: ContactOutageScenario,
    HighBatteryDegradationScenario.name: HighBatteryDegradationScenario,
    SolarArrayDegradationScenario.name: SolarArrayDegradationScenario,
    ReducedDownlinkCapacityScenario.name: ReducedDownlinkCapacityScenario,
    StoragePressureScenario.name: StoragePressureScenario,
    PayloadDegradationScenario.name: PayloadDegradationScenario,
    CommsDegradationScenario.name: CommsDegradationScenario,
    LowContactAvailabilityScenario.name: LowContactAvailabilityScenario,
    ExtendedNoContact30DaysScenario.name: ExtendedNoContact30DaysScenario,
    RepeatedShortOutagesScenario.name: RepeatedShortOutagesScenario,
    HighImagingDemandScenario.name: HighImagingDemandScenario,
    AttitudePointingStressScenario.name: AttitudePointingStressScenario,
    CombinedEnergyStressScenario.name: CombinedEnergyStressScenario,
    ExtremeCompoundPostLifeStressScenario.name: ExtremeCompoundPostLifeStressScenario,
    StochasticPostLifeEventsScenario.name: StochasticPostLifeEventsScenario,
}


def make_scenario(
    name: str,
    config: SimulationConfig = DEFAULT_CONFIG,
    *,
    seed: int | None = None,
    total_hours: int | None = None,
    event_catalog: EventCatalog | None = None,
) -> Scenario:
    try:
        scenario_type = SCENARIOS[name.lower()]
    except KeyError as exc:
        choices = ", ".join(sorted(SCENARIOS))
        raise ValueError(f"Unknown scenario {name!r}; choose one of: {choices}") from exc
    if scenario_type is Scenario:
        return Scenario()
    if scenario_type is StochasticPostLifeEventsScenario:
        return scenario_type(
            config,
            seed=seed,
            total_hours=total_hours,
            event_catalog=event_catalog,
        )
    return scenario_type(config)
