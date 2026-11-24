"""Seeded, policy-independent external stress-event catalogs for V2.3."""

import csv
import random
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_CONFIG, SimulationConfig
from .models import HEALTH_FIELDS


EVENT_CATALOG_FIELDS = [
    "seed", "scenario", "total_hours", "hour", "event_type", "severity",
    "duration_hours", "target", "effect", "description",
]


@dataclass(frozen=True)
class ExternalEvent:
    hour: int
    event_type: str
    severity: float
    duration_hours: int
    target: str
    effect: float
    description: str


@dataclass(frozen=True)
class EventCatalog:
    events: list[ExternalEvent]
    seed: int | None
    scenario_name: str
    total_hours: int


def validate_debris_damage_targets(target: str) -> tuple[str, ...]:
    targets = tuple(dict.fromkeys(
        item.strip()
        for item in target.split(",")
        if item.strip()
    ))
    invalid_targets = sorted(set(targets) - HEALTH_FIELDS)
    if not targets or invalid_targets:
        invalid_label = (
            ", ".join(invalid_targets) if invalid_targets else "<empty>"
        )
        allowed = ", ".join(sorted(HEALTH_FIELDS))
        raise ValueError(
            "Invalid debris damage target(s): "
            f"{invalid_label}; allowed health fields: {allowed}"
        )
    return targets


def generate_stochastic_event_catalog(
    seed: int | None,
    scenario_name: str,
    total_hours: int,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> EventCatalog:
    """Generate a deterministic catalog for a seed without touching global RNG state."""
    rng = random.Random(seed)
    start_hour = int(
        round(config.post_life_stress_start_year * config.hours_per_year)
    )
    definitions = (
        (
            "solar_storm",
            config.stochastic_solar_storm_probability_per_day,
            config.stochastic_solar_storm_duration_hours,
            "solar_health,battery_health,comms_health",
            config.stochastic_solar_storm_health_effect,
            "Solar-storm health stress proxy",
        ),
        (
            "radiation_event",
            config.stochastic_radiation_event_probability_per_day,
            config.stochastic_radiation_event_duration_hours,
            "obc_health,adcs_health,comms_health",
            config.stochastic_radiation_health_effect,
            "Radiation health stress proxy",
        ),
        (
            "contact_disruption",
            config.stochastic_contact_disruption_probability_per_day,
            config.stochastic_contact_disruption_duration_hours,
            "contacts",
            config.maximum_health,
            "Command and data contact disruption",
        ),
        (
            "payload_glitch",
            config.stochastic_payload_glitch_probability_per_day,
            config.stochastic_payload_glitch_duration_hours,
            "payload_health",
            config.stochastic_payload_glitch_health_effect,
            "Payload health glitch proxy",
        ),
        (
            "storage_upset",
            config.stochastic_storage_upset_probability_per_day,
            config.stochastic_storage_upset_duration_hours,
            "data_buffer_gb",
            config.stochastic_storage_upset_data_effect_gb,
            "Instantaneous payload-data storage upset",
        ),
        (
            "thermal_stress",
            config.stochastic_thermal_stress_probability_per_day,
            config.stochastic_thermal_stress_duration_hours,
            "thermal_health",
            config.stochastic_thermal_stress_health_effect,
            "Thermal health stress proxy",
        ),
        (
            "debris_conjunction",
            config.stochastic_debris_conjunction_probability_per_day,
            config.stochastic_debris_conjunction_duration_hours,
            ",".join(config.debris_damage_targets),
            config.stochastic_debris_conjunction_damage_effect,
            "Synthetic debris/conjunction avoidance opportunity",
        ),
    )
    events: list[ExternalEvent] = []
    for day_start in range(start_hour, total_hours, config.hours_per_day):
        hours_in_day = min(config.hours_per_day, total_hours - day_start)
        for event_type, probability, duration, target, base_effect, description in definitions:
            if rng.random() >= probability:
                continue
            severity = rng.uniform(
                config.stochastic_min_severity, config.stochastic_max_severity
            )
            event_hour = day_start + rng.randrange(hours_in_day)
            events.append(
                ExternalEvent(
                    hour=event_hour,
                    event_type=event_type,
                    severity=severity,
                    duration_hours=duration,
                    target=target,
                    effect=base_effect * severity,
                    description=description,
                )
            )
    events.sort(key=lambda event: event.hour)
    return EventCatalog(events, seed, scenario_name, total_hours)


def write_event_catalog(path: str | Path, catalog: EventCatalog) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_CATALOG_FIELDS)
        writer.writeheader()
        for event in catalog.events:
            writer.writerow({
                "seed": "" if catalog.seed is None else catalog.seed,
                "scenario": catalog.scenario_name,
                "total_hours": catalog.total_hours,
                "hour": event.hour,
                "event_type": event.event_type,
                "severity": event.severity,
                "duration_hours": event.duration_hours,
                "target": event.target,
                "effect": event.effect,
                "description": event.description,
            })


def read_event_catalog(path: str | Path) -> EventCatalog:
    source = Path(path)
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return EventCatalog([], None, "", 0)
    first = rows[0]
    seed = int(first["seed"]) if first["seed"] else None
    events = []
    for row in rows:
        if row["event_type"] == "debris_conjunction":
            validate_debris_damage_targets(row["target"])
        events.append(
            ExternalEvent(
                hour=int(row["hour"]),
                event_type=row["event_type"],
                severity=float(row["severity"]),
                duration_hours=int(row["duration_hours"]),
                target=row["target"],
                effect=float(row["effect"]),
                description=row["description"],
            )
        )
    events.sort(key=lambda event: event.hour)
    return EventCatalog(events, seed, first["scenario"], int(first["total_hours"]))
