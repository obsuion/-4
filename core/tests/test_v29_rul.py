from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ops_sim.config import DEFAULT_CONFIG
from ops_sim.contacts import SyntheticContactModel
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.models import LossReason, SatelliteState
from ops_sim.policies import make_policy
from ops_sim.rul import (
    RULSample,
    build_survival_curve,
    classify_risk_driver,
    estimate_remaining_useful_life,
    summarize_rul_samples,
)
from ops_sim.scenarios import StochasticPostLifeEventsScenario
from ops_sim.simulator import Simulator


TINY_CONFIG = replace(
    DEFAULT_CONFIG,
    hours_per_year=4,
    checkpoint_hours=2,
    plan_duration_hours=4,
    emergency_after_hours=20,
    post_life_stress_start_year=0.0,
)


def make_sample(**changes) -> RULSample:
    values = {
        "policy": "adaptive",
        "scenario": "nominal",
        "operator_view": "omniscient",
        "planning_model": "reactive",
        "maneuver_model": "none",
        "orbit_evolution_model": "fixed",
        "contact_model": "synthetic",
        "sample_seed": 0,
        "start_year": 8.0,
        "horizon_years": 3.0,
        "warmup_failed": False,
        "alive_at_start": True,
        "survived_to_horizon": True,
        "additional_hours_survived": 3,
        "additional_years_survived": 3.0,
        "loss_reason": None,
        "risk_driver": "power",
        "risk_margin": 0.5,
        "start_soc": 80.0,
        "start_health": 0.9,
        "start_delta_v_remaining_m_per_s": 8.0,
        "start_fuel_remaining_percent": 80.0,
        "start_orbit_drift_proxy_km": 0.1,
        "final_soc": 70.0,
        "final_health": 0.8,
        "final_delta_v_remaining_m_per_s": 7.0,
        "final_fuel_remaining_percent": 70.0,
        "final_orbit_drift_proxy_km": 0.2,
        "data_downlinked_during_rul_gb": 10.0,
        "data_generated_during_rul_gb": 12.0,
        "debris_avoidance_executed_during_rul": 1,
        "debris_avoidance_skipped_during_rul": 0,
        "maneuver_count_during_rul": 2,
        "orbit_correction_count_during_rul": 2,
    }
    values.update(changes)
    return RULSample(**values)


def test_summary_and_survival_curve_are_horizon_censored():
    samples = [
        make_sample(
            sample_seed=0,
            warmup_failed=True,
            alive_at_start=False,
            survived_to_horizon=False,
            additional_hours_survived=0,
            additional_years_survived=0.0,
            loss_reason="critical_power",
        ),
        make_sample(
            sample_seed=1,
            survived_to_horizon=False,
            additional_hours_survived=1,
            additional_years_survived=1.0,
            loss_reason="critical_power",
        ),
        make_sample(sample_seed=2),
        make_sample(sample_seed=3),
    ]

    summary = summarize_rul_samples(samples)
    assert summary.samples == 4
    assert summary.alive_at_start_fraction == pytest.approx(0.75)
    assert summary.survived_to_horizon_fraction == pytest.approx(0.5)
    assert summary.expected_rul_years_censored == pytest.approx(1.75)
    assert summary.median_rul_years_censored == pytest.approx(2.0)
    assert summary.p05_rul_years_censored == pytest.approx(0.15)
    assert summary.p95_rul_years_censored == pytest.approx(3.0)
    assert summary.probability_survive_plus_1y == pytest.approx(0.75)
    assert summary.probability_survive_plus_2y == pytest.approx(0.5)
    assert summary.probability_survive_plus_3y == pytest.approx(0.5)
    assert summary.probability_survive_to_horizon == pytest.approx(0.5)
    assert summary.most_common_loss_reason == "critical_power"
    assert summary.most_common_risk_driver == "power"

    curve = build_survival_curve(samples)
    assert [point.years_after_start for point in curve] == [0.0, 1.0, 2.0, 3.0]
    assert [point.survival_probability for point in curve] == pytest.approx(
        [0.75, 0.75, 0.5, 0.5]
    )


def test_short_horizon_omits_longer_probability_fields_and_grid_points():
    samples = [make_sample(horizon_years=0.5, additional_years_survived=0.5)]
    summary = summarize_rul_samples(samples)
    assert summary.probability_survive_plus_1y is None
    assert summary.probability_survive_plus_2y is None
    assert summary.probability_survive_plus_3y is None
    assert [point.years_after_start for point in build_survival_curve(samples)] == [
        0.0,
        0.5,
    ]


def test_risk_driver_uses_dimensionless_margin_and_exact_loss_mapping():
    state = SatelliteState(comms_health=0.11)
    driver, margin = classify_risk_driver(state)
    assert driver == "comms"
    assert margin == pytest.approx((0.11 - 0.10) / (1.0 - 0.10))

    state.alive = False
    state.loss_reason = LossReason.COMMUNICATION_FAILURE
    driver, margin = classify_risk_driver(state)
    assert driver == "comms"
    assert margin == pytest.approx((0.11 - 0.10) / (1.0 - 0.10))


def test_deterministic_estimate_runs_warmup_then_continuation():
    samples, summary, curve = estimate_remaining_useful_life(
        policy_name="adaptive",
        scenario_name="nominal",
        start_year=1.0,
        horizon_years=1.0,
        samples=1,
        seed=7,
        config=TINY_CONFIG,
    )
    sample = samples[0]
    assert sample.sample_seed == 7
    assert sample.alive_at_start
    assert not sample.warmup_failed
    assert sample.survived_to_horizon
    assert sample.additional_hours_survived == 4
    assert sample.additional_years_survived == pytest.approx(1.0)
    assert summary.samples == 1
    assert summary.expected_rul_years_censored == pytest.approx(1.0)
    assert curve[-1].years_after_start == 1.0
    assert curve[-1].survival_probability == 1.0


def test_deterministic_samples_are_identical_except_for_provenance_seed():
    samples, _, _ = estimate_remaining_useful_life(
        policy_name="adaptive",
        scenario_name="nominal",
        start_year=1.0,
        horizon_years=1.0,
        samples=3,
        seed=20,
        config=TINY_CONFIG,
    )
    assert [sample.sample_seed for sample in samples] == [20, 21, 22]
    without_seed = []
    for sample in samples:
        values = sample.as_dict()
        values.pop("sample_seed")
        without_seed.append(values)
    assert without_seed[0] == without_seed[1] == without_seed[2]


def test_warmup_failure_has_zero_rul_and_mapped_loss_reason():
    failure_config = replace(TINY_CONFIG, eps_failure_health=1.01)
    samples, summary, _ = estimate_remaining_useful_life(
        policy_name="adaptive",
        scenario_name="nominal",
        start_year=1.0,
        horizon_years=1.0,
        samples=1,
        config=failure_config,
    )
    sample = samples[0]
    assert sample.warmup_failed
    assert not sample.alive_at_start
    assert not sample.survived_to_horizon
    assert sample.additional_hours_survived == 0
    assert sample.additional_years_survived == 0.0
    assert sample.loss_reason == "eps_failure"
    assert sample.risk_driver == "eps"
    assert summary.alive_at_start_fraction == 0.0


def test_continuation_uses_defensive_state_and_reports_only_deltas():
    class RecordingSimulator:
        def __init__(self):
            self.warmup_state = None
            self.continuation_state = None

        def run(self, years, state=None, start_hour=0):
            duration = int(round(years * TINY_CONFIG.hours_per_year))
            if state is None:
                state = SatelliteState(
                    hours_completed=duration,
                    total_data_generated_gb=100.0,
                    total_data_downlinked_gb=80.0,
                    maneuver_count=5,
                    orbit_correction_count=4,
                    debris_avoidance_executed_count=3,
                    debris_avoidance_skipped_count=2,
                )
                self.warmup_state = state
            else:
                assert start_hour == 4
                assert state is not self.warmup_state
                self.continuation_state = state
                state.hours_completed += duration
                state.total_data_generated_gb += 7.0
                state.total_data_downlinked_gb += 6.0
                state.maneuver_count += 2
                state.orbit_correction_count += 2
                state.debris_avoidance_executed_count += 1
                state.debris_avoidance_skipped_count += 1
            return SimpleNamespace(state=state)

    simulator = RecordingSimulator()
    samples, _, _ = estimate_remaining_useful_life(
        policy_name="adaptive",
        scenario_name="nominal",
        start_year=1.0,
        horizon_years=1.0,
        samples=1,
        config=TINY_CONFIG,
        simulator_factory=lambda _seed, _catalog: simulator,
    )
    sample = samples[0]
    assert simulator.warmup_state.total_data_generated_gb == 100.0
    assert simulator.continuation_state is not simulator.warmup_state
    assert sample.data_generated_during_rul_gb == 7.0
    assert sample.data_downlinked_during_rul_gb == 6.0
    assert sample.maneuver_count_during_rul == 2
    assert sample.orbit_correction_count_during_rul == 2
    assert sample.debris_avoidance_executed_during_rul == 1
    assert sample.debris_avoidance_skipped_during_rul == 1


def test_stochastic_catalog_covers_both_phases_and_is_reproducible():
    calls = []

    def catalog_factory(seed, scenario_name, total_hours, config):
        calls.append((seed, scenario_name, total_hours))
        return EventCatalog(
            events=[
                ExternalEvent(
                    hour=0,
                    event_type="solar_storm",
                    severity=1.0,
                    duration_hours=1,
                    target="solar_health",
                    effect=0.20,
                    description="warm-up hit",
                )
            ],
            seed=seed,
            scenario_name=scenario_name,
            total_hours=total_hours,
        )

    kwargs = {
        "policy_name": "adaptive",
        "scenario_name": "stochastic_post_life_events",
        "start_year": 1.0,
        "horizon_years": 1.0,
        "samples": 2,
        "seed": 42,
        "config": TINY_CONFIG,
        "event_catalog_factory": catalog_factory,
    }
    first, _, _ = estimate_remaining_useful_life(**kwargs)
    second, _, _ = estimate_remaining_useful_life(**kwargs)
    assert first == second
    assert calls == [
        (42, "stochastic_post_life_events", 8),
        (43, "stochastic_post_life_events", 8),
        (42, "stochastic_post_life_events", 8),
        (43, "stochastic_post_life_events", 8),
    ]
    assert all(sample.start_health < 1.0 for sample in first)


def test_future_stochastic_disruption_is_not_used_by_risk_aware_plan():
    config = replace(TINY_CONFIG, plan_duration_hours=8)
    built_simulators = []

    class RecordingSimulator(Simulator):
        warmup_plan = None

        def run(self, years, state=None, **kwargs):
            result = super().run(years, state=state, **kwargs)
            if state is None:
                self.warmup_plan = deepcopy(result.state.current_plan)
            return result

    def catalog_factory(seed, scenario_name, total_hours, _config):
        return EventCatalog(
            events=[
                ExternalEvent(
                    hour=4,
                    event_type="contact_disruption",
                    severity=1.0,
                    duration_hours=1,
                    target="contacts",
                    effect=1.0,
                    description="future disruption",
                )
            ],
            seed=seed,
            scenario_name=scenario_name,
            total_hours=total_hours,
        )

    def simulator_factory(_seed, catalog):
        simulator = RecordingSimulator(
            make_policy("adaptive", config),
            StochasticPostLifeEventsScenario(
                config=config, event_catalog=catalog
            ),
            config,
            contact_model=SyntheticContactModel(config),
            operator_view="delayed_telemetry",
            planning_model="risk_aware",
        )
        built_simulators.append(simulator)
        return simulator

    estimate_remaining_useful_life(
        policy_name="adaptive",
        scenario_name="stochastic_post_life_events",
        start_year=1.0,
        horizon_years=1.0,
        samples=1,
        config=config,
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        event_catalog_factory=catalog_factory,
        simulator_factory=simulator_factory,
    )

    plan = built_simulators[0].warmup_plan
    assert plan is not None
    # Hour 4 is disrupted in the catalog, but the hour-0 plan sees the base
    # synthetic opportunity because future scenario effects are not forecast.
    assert plan.expected_data_contact_min_by_hour[4] == pytest.approx(15.0)


@pytest.mark.parametrize("contact_model", ["synthetic", "geometry"])
@pytest.mark.parametrize("orbit_model", ["fixed", "drift_proxy"])
def test_estimator_supports_contact_and_orbit_model_combinations(
    contact_model, orbit_model
):
    samples, _, _ = estimate_remaining_useful_life(
        policy_name="adaptive",
        scenario_name="nominal",
        start_year=0.0,
        horizon_years=0.25,
        samples=1,
        config=TINY_CONFIG,
        contact_model_name=contact_model,
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model=orbit_model,
    )
    assert samples[0].additional_hours_survived == 1
    assert samples[0].contact_model == contact_model
    assert samples[0].orbit_evolution_model == orbit_model


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"samples": 0}, "samples must be a positive integer"),
        ({"seed": True}, "seed must be an integer"),
        ({"start_year": -1.0}, "start_year must be"),
        ({"horizon_years": float("inf")}, "horizon_years must be"),
        ({"contact_model_name": "invalid"}, "Unknown contact model"),
    ],
)
def test_estimator_rejects_invalid_inputs(kwargs, message):
    arguments = {
        "policy_name": "adaptive",
        "scenario_name": "nominal",
        "start_year": 0.0,
        "horizon_years": 0.0,
        "samples": 1,
        "config": TINY_CONFIG,
    }
    arguments.update(kwargs)
    with pytest.raises(ValueError, match=message):
        estimate_remaining_useful_life(**arguments)
