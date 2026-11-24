import csv
from dataclasses import replace

import pytest
import run

from ops_sim.config import DEFAULT_CONFIG
from ops_sim.event_catalog import (
    EVENT_CATALOG_FIELDS,
    EventCatalog,
    ExternalEvent,
    generate_stochastic_event_catalog,
    read_event_catalog,
    write_event_catalog,
)
from ops_sim.models import ContactInfo, SatelliteState
from ops_sim.policies import POLICIES
from ops_sim.scenarios import (
    SCENARIOS,
    StochasticPostLifeEventsScenario,
    make_scenario,
)


def event_rich_config():
    return replace(
        DEFAULT_CONFIG,
        post_life_stress_start_year=0.0,
        stochastic_solar_storm_probability_per_day=1.0,
        stochastic_radiation_event_probability_per_day=1.0,
        stochastic_contact_disruption_probability_per_day=1.0,
        stochastic_payload_glitch_probability_per_day=1.0,
        stochastic_storage_upset_probability_per_day=1.0,
        stochastic_thermal_stress_probability_per_day=1.0,
        stochastic_debris_conjunction_probability_per_day=1.0,
    )


def test_same_seed_creates_identical_catalog():
    config = event_rich_config()
    first = generate_stochastic_event_catalog(42, "stochastic_post_life_events", 72, config)
    second = generate_stochastic_event_catalog(42, "stochastic_post_life_events", 72, config)
    assert first == second


def test_different_seeds_create_different_catalogs():
    config = event_rich_config()
    first = generate_stochastic_event_catalog(1, "stochastic_post_life_events", 72, config)
    second = generate_stochastic_event_catalog(2, "stochastic_post_life_events", 72, config)
    assert first.events != second.events


def test_catalog_events_are_sorted_and_post_life_only():
    total_hours = 15 * DEFAULT_CONFIG.hours_per_year
    catalog = generate_stochastic_event_catalog(
        42, "stochastic_post_life_events", total_hours
    )
    start_hour = int(round(
        DEFAULT_CONFIG.post_life_stress_start_year * DEFAULT_CONFIG.hours_per_year
    ))
    assert catalog.events
    assert [event.hour for event in catalog.events] == sorted(
        event.hour for event in catalog.events
    )
    assert all(event.hour >= start_hour for event in catalog.events)


def test_event_catalog_csv_roundtrip(tmp_path):
    catalog = generate_stochastic_event_catalog(
        7, "stochastic_post_life_events", 72, event_rich_config()
    )
    path = tmp_path / "catalog.csv"
    write_event_catalog(path, catalog)

    with path.open(newline="", encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == EVENT_CATALOG_FIELDS
    assert read_event_catalog(path) == catalog


def test_catalog_without_debris_events_still_loads(tmp_path):
    catalog = EventCatalog(
        [ExternalEvent(
            4, "payload_glitch", 0.7, 2, "payload_health", 0.01,
            "old catalog event",
        )],
        3,
        "stochastic_post_life_events",
        10,
    )
    path = tmp_path / "old_catalog.csv"
    write_event_catalog(path, catalog)

    assert read_event_catalog(path) == catalog


def test_invalid_debris_target_is_rejected_while_loading_catalog(tmp_path):
    catalog = EventCatalog(
        [ExternalEvent(
            0, "debris_conjunction", 1.0, 1,
            "solar_health,not_a_health_field", 0.05,
            "invalid debris target",
        )],
        42,
        "stochastic_post_life_events",
        1,
    )
    path = tmp_path / "invalid_debris_catalog.csv"
    write_event_catalog(path, catalog)

    with pytest.raises(
        ValueError,
        match=r"Invalid debris damage target\(s\): not_a_health_field",
    ):
        read_event_catalog(path)


def test_seeded_debris_conjunctions_are_post_life_reproducible_and_serializable(
    tmp_path,
):
    config = replace(
        event_rich_config(),
        post_life_stress_start_year=(
            DEFAULT_CONFIG.hours_per_day / DEFAULT_CONFIG.hours_per_year
        ),
    )
    start_hour = int(round(
        config.post_life_stress_start_year * config.hours_per_year
    ))
    first = generate_stochastic_event_catalog(
        42, "stochastic_post_life_events", 72, config
    )
    second = generate_stochastic_event_catalog(
        42, "stochastic_post_life_events", 72, config
    )
    different = generate_stochastic_event_catalog(
        43, "stochastic_post_life_events", 72, config
    )

    debris = [
        event for event in first.events
        if event.event_type == "debris_conjunction"
    ]
    second_debris = [
        event for event in second.events
        if event.event_type == "debris_conjunction"
    ]
    different_debris = [
        event for event in different.events
        if event.event_type == "debris_conjunction"
    ]
    assert debris
    assert debris == second_debris
    assert debris != different_debris
    assert all(event.hour >= start_hour for event in debris)
    assert all(
        event.target == ",".join(config.debris_damage_targets)
        for event in debris
    )

    path = tmp_path / "debris_catalog.csv"
    write_event_catalog(path, first)
    loaded_debris = [
        event for event in read_event_catalog(path).events
        if event.event_type == "debris_conjunction"
    ]
    assert loaded_debris == debris


def test_empty_event_catalog_csv_roundtrip_does_not_crash(tmp_path):
    path = tmp_path / "empty_catalog.csv"
    write_event_catalog(
        path, EventCatalog([], 42, "stochastic_post_life_events", 100)
    )

    loaded = read_event_catalog(path)
    assert loaded.events == []


def test_stochastic_scenario_registration_and_factory_compatibility():
    assert "stochastic_post_life_events" in SCENARIOS
    for name in ("nominal", "contact_outage", "high_battery_degradation"):
        assert make_scenario(name).name == name

    catalog = EventCatalog([], 5, "stochastic_post_life_events", 100)
    scenario = make_scenario(
        "stochastic_post_life_events",
        seed=5,
        total_hours=100,
        event_catalog=catalog,
    )
    assert isinstance(scenario, StochasticPostLifeEventsScenario)
    assert scenario.event_catalog is catalog


def test_policy_all_generates_one_catalog_and_reuses_it(tmp_path, monkeypatch):
    total_hours = int(round(0.001 * DEFAULT_CONFIG.hours_per_year))
    catalog = EventCatalog(
        [ExternalEvent(0, "contact_disruption", 1.0, 1, "contacts", 1.0, "test")],
        42,
        "stochastic_post_life_events",
        total_hours,
    )
    generation_calls = []
    catalog_ids = []
    original_run_one = run._run_one

    def fake_generate(seed, scenario_name, requested_hours):
        generation_calls.append((seed, scenario_name, requested_hours))
        return catalog

    def capture_run_one(
        policy_name, scenario_name, years, requested_hours, shared_catalog,
        writers, contact_model, operator_view, planning_model, maneuver_model,
        orbit_evolution_model,
    ):
        catalog_ids.append(id(shared_catalog))
        return original_run_one(
            policy_name, scenario_name, years, requested_hours, shared_catalog,
            writers, contact_model, operator_view, planning_model,
            maneuver_model,
            orbit_evolution_model,
        )

    monkeypatch.setattr(run, "generate_stochastic_event_catalog", fake_generate)
    monkeypatch.setattr(run, "_run_one", capture_run_one)

    assert run.main([
        "--years", "0.001", "--policy", "all",
        "--scenario", "stochastic_post_life_events", "--seed", "42",
        "--log-level", "summary", "--results-dir", str(tmp_path),
    ]) == 0
    assert len(generation_calls) == 1
    assert len(catalog_ids) == len(POLICIES)
    assert len(set(catalog_ids)) == 1
    assert (
        tmp_path / "event_catalogs"
        / "stochastic_post_life_events_seed42.csv"
    ).exists()


def test_contact_disruption_zeros_contacts_for_active_window():
    event = ExternalEvent(
        10, "contact_disruption", 0.8, 3, "contacts", 1.0, "test disruption"
    )
    scenario = StochasticPostLifeEventsScenario(
        event_catalog=EventCatalog([event], 1, "stochastic_post_life_events", 20)
    )
    state = SatelliteState()
    contact = ContactInfo(15, 15)

    assert scenario.modify_contacts(contact, state, 9) == contact
    assert scenario.modify_contacts(contact, state, 10) == ContactInfo()
    assert scenario.modify_contacts(contact, state, 12) == ContactInfo()
    assert scenario.modify_contacts(contact, state, 13) == contact


def test_health_hit_events_clamp_health_to_valid_range():
    event = ExternalEvent(
        0,
        "solar_storm",
        1.0,
        1,
        "solar_health,battery_health,comms_health",
        2.0,
        "large test hit",
    )
    scenario = StochasticPostLifeEventsScenario(
        event_catalog=EventCatalog([event], 1, "stochastic_post_life_events", 1)
    )
    state = SatelliteState(solar_health=0.1, battery_health=0.1, comms_health=0.1)
    scenario.apply_pre_hour(state, 0)

    assert state.solar_health == 0
    assert state.battery_health == 0
    assert state.comms_health == 0


def test_monte_carlo_summary_has_one_row_per_seed_and_policy(tmp_path):
    assert run.main([
        "--years", "0.001", "--policy", "all",
        "--scenario", "stochastic_post_life_events", "--monte-carlo", "2",
        "--results-dir", str(tmp_path),
    ]) == 0

    with (tmp_path / "monte_carlo_summary.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2 * len(POLICIES)
    assert {row["seed"] for row in rows} == {"0", "1"}
    assert {row["policy"] for row in rows} == set(POLICIES)


def test_monte_carlo_defaults_to_summary_logging(tmp_path):
    assert run.main([
        "--years", "0.001", "--policy", "adaptive",
        "--scenario", "stochastic_post_life_events", "--monte-carlo", "1",
        "--results-dir", str(tmp_path),
    ]) == 0

    assert (tmp_path / "summary.csv").exists()
    assert (tmp_path / "monte_carlo_summary.csv").exists()
    assert not (tmp_path / "state_log.csv").exists()
    assert not (tmp_path / "checkpoints.csv").exists()
    assert not (tmp_path / "events_log.csv").exists()


def test_monte_carlo_explicit_full_logging_creates_detail_logs(tmp_path):
    assert run.main([
        "--years", "0.001", "--policy", "adaptive",
        "--scenario", "stochastic_post_life_events", "--monte-carlo", "1",
        "--log-level", "full", "--results-dir", str(tmp_path),
    ]) == 0

    assert (tmp_path / "state_log.csv").exists()
    assert (tmp_path / "checkpoints.csv").exists()
    assert (tmp_path / "events_log.csv").exists()


def test_monte_carlo_seed_is_start_of_seed_range(tmp_path):
    assert run.main([
        "--years", "0.001", "--policy", "adaptive",
        "--scenario", "stochastic_post_life_events", "--monte-carlo", "2",
        "--seed", "5", "--results-dir", str(tmp_path),
    ]) == 0

    with (tmp_path / "monte_carlo_summary.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        assert {row["seed"] for row in csv.DictReader(handle)} == {"5", "6"}


def test_external_event_start_is_emitted_for_events_log():
    event = ExternalEvent(
        4, "payload_glitch", 0.7, 2, "payload_health", 0.01, "test glitch"
    )
    scenario = StochasticPostLifeEventsScenario(
        event_catalog=EventCatalog([event], 3, "stochastic_post_life_events", 10)
    )

    assert scenario.events_at_hour(3) == []
    assert scenario.events_at_hour(4)[0][0] == "external_payload_glitch"


def test_summary_log_level_creates_no_empty_detail_logs(tmp_path):
    assert run.main([
        "--years", "0.001", "--policy", "adaptive", "--scenario", "nominal",
        "--log-level", "summary", "--results-dir", str(tmp_path),
    ]) == 0

    assert {path.name for path in tmp_path.iterdir()} == {"summary.csv"}


def test_summary_log_level_removes_stale_detail_logs(tmp_path):
    for filename in ("state_log.csv", "checkpoints.csv", "events_log.csv"):
        (tmp_path / filename).write_text("stale", encoding="utf-8")

    assert run.main([
        "--years", "0.001", "--policy", "adaptive", "--scenario", "nominal",
        "--log-level", "summary", "--results-dir", str(tmp_path),
    ]) == 0

    assert not (tmp_path / "state_log.csv").exists()
    assert not (tmp_path / "checkpoints.csv").exists()
    assert not (tmp_path / "events_log.csv").exists()


def test_invalid_monte_carlo_scenario_is_rejected(tmp_path):
    with pytest.raises(SystemExit, match="requires --scenario stochastic_post_life_events"):
        run.main([
            "--scenario", "nominal", "--monte-carlo", "2",
            "--results-dir", str(tmp_path),
        ])
