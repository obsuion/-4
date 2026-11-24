import csv
from pathlib import Path

import pytest

import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import POLICIES, Policy, make_policy
from ops_sim.scenarios import Scenario
from ops_sim.simulator import PLANNING_MODELS, Simulator


EXPECTED_OPERATORS = {
    "aggressive",
    "conservative",
    "adaptive",
    "balanced",
    "survival_first",
    "data_maximizer",
    "power_saver",
    "downlink_priority",
    "storage_guardian",
    "outage_resilient",
    "battery_protective",
    "contact_opportunist",
}
DETAILED_PLANNING_FIELDS = {
    "planning_energy_risk",
    "planning_storage_risk",
    "planning_expected_data_contact_min",
    "planning_expected_cmd_contact_min",
}
V25_PLAN_FIELDS = {
    "planned_mode",
    "plan_mode_index",
    "plan_modes_remaining",
    "plan_uploaded_this_hour",
    "plan_policy",
    "plan_based_on_telemetry_hour",
    "plan_based_on_telemetry_age_hours",
}
V24_GEOMETRY_FIELDS = {
    "contact_model",
    "base_cmd_contact_min",
    "base_data_contact_min",
    "geometry_raw_visible_seconds",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_fields(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return set(csv.DictReader(handle).fieldnames or [])


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


class RecordingPolicy(Policy):
    name = "recording"

    def __init__(self, mode: Mode = Mode.IMAGING):
        super().__init__()
        self.mode = mode
        self.calls = 0

    @property
    def safe_threshold(self) -> float:
        return DEFAULT_CONFIG.adaptive_safe_threshold

    def select_mode(self, state: SatelliteState, contact: ContactInfo) -> Mode:
        self.calls += 1
        return self.mode


class FirstHourCommandContactModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(5.0, 0.0) if hour == 0 else ContactInfo()


class FirstHourDataContactModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(5.0, 5.0) if hour == 0 else ContactInfo()


class ForecastDataContactModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        if hour == 0:
            return ContactInfo(5.0, 0.0)
        if hour == 2:
            return ContactInfo(5.0, 10.0)
        return ContactInfo()


class FutureContactDisruptionScenario(Scenario):
    name = "future_contact_disruption"

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return ContactInfo() if hour == 2 else contact_info


class ZeroFinalContactScenario(Scenario):
    name = "zero_final_contact"

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return ContactInfo()


class LowPowerAfterUploadScenario(Scenario):
    name = "low_power_after_upload"

    def apply_pre_hour(self, state: SatelliteState, hour: int) -> None:
        if hour == 1:
            state.soc = 10.0


def test_policy_library_contains_exactly_twelve_selectable_operators():
    assert set(POLICIES) == EXPECTED_OPERATORS
    assert len(POLICIES) == 12
    assert {"aggressive", "conservative", "adaptive"} <= set(POLICIES)
    assert {make_policy(name).name for name in EXPECTED_OPERATORS} == (
        EXPECTED_OPERATORS
    )
    assert run.build_parser().parse_args([]).policy == "adaptive"


def test_policy_all_runs_all_twelve_operators(tmp_path):
    assert run.main([
        "--years", str(hours_as_years(1)),
        "--policy", "all",
        "--scenario", "nominal",
        "--log-level", "summary",
        "--results-dir", str(tmp_path),
    ]) == 0

    rows = read_rows(tmp_path / "summary.csv")
    assert len(rows) == 12
    assert {row["policy"] for row in rows} == EXPECTED_OPERATORS


def test_operator_reactive_decisions_are_distinct():
    shared_state = SatelliteState(soc=50.0, data_buffer_gb=100.0)
    decisions = {
        name: policy_type().select_mode(shared_state, ContactInfo())
        for name, policy_type in POLICIES.items()
    }

    assert len(set(decisions.values())) > 1
    assert decisions["aggressive"] != decisions["conservative"]

    healthy = SatelliteState(soc=80.0)
    assert make_policy("survival_first").select_mode(
        healthy, ContactInfo()
    ) != make_policy("data_maximizer").select_mode(healthy, ContactInfo())


def test_specialized_operator_reactive_priorities():
    buffered = SatelliteState(soc=80.0, data_buffer_gb=25.0)
    assert make_policy("downlink_priority").select_mode(
        buffered, ContactInfo(5.0, 5.0)
    ) == Mode.DOWNLINK

    pressured = SatelliteState(soc=80.0, data_buffer_gb=800.0)
    assert make_policy("storage_guardian").select_mode(
        pressured, ContactInfo()
    ) != Mode.IMAGING

    weak_battery = SatelliteState(soc=80.0, battery_health=0.30)
    for name in ("battery_protective", "power_saver"):
        assert make_policy(name).select_mode(
            weak_battery, ContactInfo()
        ) not in (Mode.IMAGING, Mode.DOWNLINK)


def test_planning_model_defaults_and_validation():
    args = run.build_parser().parse_args([])
    assert args.planning_model == "reactive"
    assert PLANNING_MODELS == ("reactive", "risk_aware")
    assert run.build_parser().parse_args([
        "--planning-model", "risk_aware"
    ]).planning_model == "risk_aware"

    with pytest.raises(SystemExit):
        run.build_parser().parse_args(["--planning-model", "invalid"])
    with pytest.raises(ValueError, match="planning_model must be one of"):
        Simulator(make_policy("adaptive"), planning_model="invalid")


@pytest.mark.parametrize("planning_model", PLANNING_MODELS)
def test_cli_accepts_both_planning_models(tmp_path, planning_model):
    results_dir = tmp_path / planning_model
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--operator-view", "delayed_telemetry",
        "--planning-model", planning_model,
        "--results-dir", str(results_dir),
    ]) == 0
    assert read_rows(results_dir / "summary.csv")[0]["planning_model"] == (
        planning_model
    )


def test_reactive_delayed_plan_keeps_v25_no_live_command_behavior():
    policy = RecordingPolicy(Mode.IMAGING)
    records = []
    result = Simulator(
        policy,
        contact_model=FirstHourCommandContactModel(),
        operator_view="delayed_telemetry",
        planning_model="reactive",
    ).run(hours_as_years(3), on_hour=records.append)

    assert policy.calls == DEFAULT_CONFIG.plan_duration_hours
    assert result.planning_model == "reactive"
    assert [record.planned_mode for record in records] == [
        Mode.IMAGING.value
    ] * 3
    assert [record.mode for record in records] == [Mode.IMAGING.value] * 3


def test_risk_aware_plans_are_valid_distinct_and_keep_provenance():
    plans = {}
    for name in POLICIES:
        result = Simulator(
            make_policy(name),
            operator_view="delayed_telemetry",
            planning_model="risk_aware",
        ).run(hours_as_years(1))
        plan = result.state.current_plan
        assert len(plan.planned_modes) == plan.duration_hours == 24
        assert all(isinstance(mode, Mode) for mode in plan.planned_modes)
        assert plan.policy_name == name
        assert plan.based_on_telemetry_hour == 0
        assert plan.based_on_telemetry_age_hours == 0
        plans[name] = plan.planned_modes

    assert len(set(plans.values())) >= 6
    assert plans["aggressive"] != plans["conservative"]
    assert plans["survival_first"] != plans["data_maximizer"]


def test_risk_aware_low_energy_avoids_repeated_imaging():
    state = SatelliteState(soc=25.0, battery_health=0.50)
    records = []
    result = Simulator(
        make_policy("data_maximizer"),
        contact_model=FirstHourCommandContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
    ).run(hours_as_years(1), state=state, on_hour=records.append)

    plan = result.state.current_plan
    assert plan.planned_modes.count(Mode.IMAGING) < plan.duration_hours / 4
    assert records[0].planning_energy_risk is True
    assert records[0].planned_mode != Mode.IMAGING.value
    assert records[0].mode == Mode.SAFE.value


def test_risk_aware_real_safe_override_can_replace_planned_mode():
    records = []
    Simulator(
        make_policy("aggressive"),
        LowPowerAfterUploadScenario(),
        contact_model=FirstHourCommandContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
    ).run(hours_as_years(2), on_hour=records.append)

    assert records[1].planned_mode == Mode.IMAGING.value
    assert records[1].mode == Mode.SAFE.value


def test_risk_aware_storage_and_downlink_priorities():
    pressured_records = []
    Simulator(
        make_policy("storage_guardian"),
        contact_model=FirstHourCommandContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=80.0, data_buffer_gb=800.0),
        on_hour=pressured_records.append,
    )
    assert pressured_records[0].planning_storage_risk is True
    assert pressured_records[0].planned_mode != Mode.IMAGING.value

    downlink_records = []
    Simulator(
        make_policy("downlink_priority"),
        contact_model=FirstHourDataContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=80.0, data_buffer_gb=100.0),
        on_hour=downlink_records.append,
    )
    assert downlink_records[0].planned_mode == Mode.DOWNLINK.value


def test_risk_aware_future_contacts_use_base_forecast_not_scenario_disruption():
    records = []
    Simulator(
        make_policy("downlink_priority"),
        FutureContactDisruptionScenario(),
        contact_model=ForecastDataContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
    ).run(
        hours_as_years(3),
        state=SatelliteState(soc=80.0, data_buffer_gb=100.0),
        on_hour=records.append,
    )

    assert records[2].base_data_contact_min == 10.0
    assert records[2].data_contact_min == 0.0
    assert records[2].planning_expected_data_contact_min == 10.0
    assert records[2].planned_mode == Mode.DOWNLINK.value
    assert records[1].planning_expected_data_contact_min == 0.0
    assert records[1].planned_mode != records[2].planned_mode


def test_risk_aware_disrupted_upload_contact_creates_no_plan():
    result = Simulator(
        make_policy("adaptive"),
        ZeroFinalContactScenario(),
        contact_model=FirstHourCommandContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
    ).run(hours_as_years(1))
    assert result.state.current_plan is None


def test_v26_state_and_aggregate_schemas(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--operator-view", "delayed_telemetry",
        "--planning-model", "risk_aware",
        "--results-dir", str(tmp_path),
    ]) == 0

    state_rows = read_rows(tmp_path / "state_log.csv")
    assert DETAILED_PLANNING_FIELDS <= set(state_rows[0])
    assert {row["planning_model"] for row in state_rows} == {"risk_aware"}
    assert state_rows[0]["planning_expected_data_contact_min"] != ""
    assert state_rows[0]["planning_expected_cmd_contact_min"] != ""

    summary_rows = read_rows(tmp_path / "summary.csv")
    assert summary_rows[0]["planning_model"] == "risk_aware"
    assert DETAILED_PLANNING_FIELDS.isdisjoint(summary_rows[0])
    for filename in ("checkpoints.csv", "events_log.csv"):
        fields = read_fields(tmp_path / filename)
        assert "planning_model" not in fields
        assert DETAILED_PLANNING_FIELDS.isdisjoint(fields)


def test_geometry_risk_aware_delayed_run_has_v24_v25_v26_fields(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--contact-model", "geometry",
        "--operator-view", "delayed_telemetry",
        "--planning-model", "risk_aware",
        "--results-dir", str(tmp_path),
    ]) == 0

    row = read_rows(tmp_path / "state_log.csv")[0]
    assert V24_GEOMETRY_FIELDS <= set(row)
    assert V25_PLAN_FIELDS <= set(row)
    assert DETAILED_PLANNING_FIELDS <= set(row)
    assert row["planning_model"] == "risk_aware"


def test_monte_carlo_risk_aware_delayed_uses_summary_logging(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "stochastic_post_life_events",
        "--monte-carlo", "2",
        "--operator-view", "delayed_telemetry",
        "--planning-model", "risk_aware",
        "--results-dir", str(tmp_path),
    ]) == 0

    for filename in ("summary.csv", "monte_carlo_summary.csv"):
        rows = read_rows(tmp_path / filename)
        assert len(rows) == 2
        assert {row["planning_model"] for row in rows} == {"risk_aware"}
        assert DETAILED_PLANNING_FIELDS.isdisjoint(rows[0])
    assert not (tmp_path / "state_log.csv").exists()
    assert not (tmp_path / "checkpoints.csv").exists()
    assert not (tmp_path / "events_log.csv").exists()


def test_readme_documents_v26_operator_and_planning_boundaries():
    normalized = " ".join(Path("README.md").read_text(encoding="utf-8").split()).lower()

    assert "v2.6" in normalized
    assert all(f"`{name}`" in normalized for name in EXPECTED_OPERATORS)
    assert "`reactive` remains the default" in normalized
    assert "not a full optimizer" in normalized
    assert "future stochastic disruptions" in normalized
    assert "not forecast" in normalized
