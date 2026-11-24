import csv
from pathlib import Path

import pytest

import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import POLICIES, Policy, make_policy
from ops_sim.scenarios import Scenario
from ops_sim.simulator import OPERATOR_VIEWS, Simulator


TELEMETRY_FIELDS = {
    "operator_view",
    "telemetry_updated_this_hour",
    "last_telemetry_hour",
    "telemetry_age_hours",
    "observed_soc",
    "observed_health",
    "observed_buffer_gb",
    "observed_effective_energy_margin",
    "observed_battery_health",
    "observed_solar_health",
    "observed_comms_health",
    "observed_payload_health",
    "observed_storage_health",
}
STATE_ONLY_TELEMETRY_FIELDS = TELEMETRY_FIELDS - {"operator_view"}
PLAN_FIELDS = {
    "plan_uploaded_this_hour",
    "plan_policy",
    "plan_based_on_telemetry_hour",
    "plan_based_on_telemetry_age_hours",
    "planned_mode",
    "plan_mode_index",
    "plan_modes_remaining",
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

    def __init__(self, requested_mode: Mode = Mode.IMAGING):
        super().__init__()
        self.requested_mode = requested_mode
        self.seen: list[SatelliteState] = []

    @property
    def safe_threshold(self) -> float:
        return DEFAULT_CONFIG.adaptive_safe_threshold

    def select_mode(self, state: SatelliteState, contact: ContactInfo) -> Mode:
        self.seen.append(state)
        return self.requested_mode


class MutatingPolicy(RecordingPolicy):
    def select_mode(self, state: SatelliteState, contact: ContactInfo) -> Mode:
        self.seen.append(state)
        state.soc = 0.0
        state.data_buffer_gb = DEFAULT_CONFIG.storage_capacity_gb
        return self.requested_mode


class NoContactModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo()


class ContactAtHourOneModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(cmd_contact_min=5.0) if hour == 1 else ContactInfo()


class FirstHourCommandContactModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(cmd_contact_min=5.0) if hour == 0 else ContactInfo()


class AlwaysCommandContactModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(cmd_contact_min=5.0)


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


def test_operator_view_defaults_and_validation():
    args = run.build_parser().parse_args([])
    assert args.operator_view == "omniscient"
    assert OPERATOR_VIEWS == ("omniscient", "delayed_telemetry")

    with pytest.raises(SystemExit):
        run.build_parser().parse_args(["--operator-view", "invalid"])
    with pytest.raises(ValueError, match="operator_view must be one of"):
        Simulator(RecordingPolicy(), operator_view="invalid")


@pytest.mark.parametrize("operator_view", OPERATOR_VIEWS)
def test_cli_accepts_both_operator_views(tmp_path, operator_view):
    results_dir = tmp_path / operator_view
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--operator-view", operator_view,
        "--results-dir", str(results_dir),
    ]) == 0

    assert read_rows(results_dir / "summary.csv")[0]["operator_view"] == operator_view


def test_omniscient_default_keeps_live_hourly_policy_selection():
    policy = RecordingPolicy(Mode.IMAGING)
    records = []
    Simulator(policy, contact_model=NoContactModel()).run(
        hours_as_years(3), on_hour=records.append
    )

    assert len(policy.seen) == 3
    assert [record.mode for record in records] == [Mode.IMAGING.value] * 3


def test_delayed_telemetry_refreshes_on_final_command_contact():
    policy = RecordingPolicy()
    simulator = Simulator(
        policy,
        contact_model=ContactAtHourOneModel(),
        operator_view="delayed_telemetry",
    )
    records = []
    result = simulator.run(hours_as_years(2), on_hour=records.append)

    assert records[0].telemetry_updated_this_hour is False
    assert records[0].last_telemetry_hour == 0
    assert records[0].telemetry_age_hours == 0
    assert records[1].telemetry_updated_this_hour is True
    assert records[1].last_telemetry_hour == 1
    assert records[1].telemetry_age_hours == 0
    assert len(policy.seen) == DEFAULT_CONFIG.plan_duration_hours
    assert policy.seen[0].soc == pytest.approx(records[1].observed_soc)
    assert policy.seen[0].data_buffer_gb == pytest.approx(
        records[1].observed_buffer_gb
    )
    assert records[0].plan_uploaded_this_hour is False
    assert records[1].plan_uploaded_this_hour is True
    assert records[1].plan_policy == policy.name
    assert records[1].plan_based_on_telemetry_hour == 1
    assert records[1].plan_based_on_telemetry_age_hours == 0
    assert result.state.current_plan.policy_name == policy.name
    assert result.state.current_plan.based_on_telemetry_hour == 1
    assert result.state.current_plan.based_on_telemetry_age_hours == 0
    assert result.state.current_plan.duration_hours == (
        DEFAULT_CONFIG.plan_duration_hours
    )
    assert len(result.state.current_plan.planned_modes) == (
        result.state.current_plan.duration_hours
    )
    assert set(result.state.current_plan.planned_modes) == {Mode.IMAGING}
    assert records[1].planned_mode == Mode.IMAGING.value
    assert records[1].plan_mode_index == 0
    assert records[1].plan_modes_remaining == DEFAULT_CONFIG.plan_duration_hours
    assert simulator.observed_state is not result.state
    assert records[1].observed_soc != pytest.approx(records[1].soc)


def test_no_contact_keeps_policy_view_stale_while_real_state_changes():
    policy = RecordingPolicy()
    records = []
    result = Simulator(
        policy,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
    ).run(hours_as_years(3), on_hour=records.append)

    assert [record.telemetry_age_hours for record in records] == [0, 1, 2]
    assert [record.last_telemetry_hour for record in records] == [0, 0, 0]
    assert not any(record.telemetry_updated_this_hour for record in records)
    assert not any(record.plan_uploaded_this_hour for record in records)
    assert result.state.current_plan is None
    assert policy.seen == []
    assert {record.mode for record in records} == {Mode.BACKUP.value}
    assert all(record.planned_mode is None for record in records)
    assert all(record.plan_mode_index is None for record in records)
    assert all(record.plan_modes_remaining == 0 for record in records)
    assert [record.observed_soc for record in records] == [
        DEFAULT_CONFIG.initial_soc
    ] * 3
    assert records[-1].soc != pytest.approx(records[-1].observed_soc)
    assert result.state.soc == pytest.approx(records[-1].soc)


def test_policy_receives_a_defensive_copy_of_the_observed_snapshot():
    policy = MutatingPolicy(Mode.STANDBY)
    records = []
    simulator = Simulator(
        policy,
        contact_model=FirstHourCommandContactModel(),
        operator_view="delayed_telemetry",
    )
    result = simulator.run(hours_as_years(1), on_hour=records.append)

    assert len(policy.seen) == DEFAULT_CONFIG.plan_duration_hours
    assert all(state.soc == 0.0 for state in policy.seen)
    assert all(
        state.data_buffer_gb == DEFAULT_CONFIG.storage_capacity_gb
        for state in policy.seen
    )
    assert simulator.observed_state.soc == pytest.approx(DEFAULT_CONFIG.initial_soc)
    assert simulator.observed_state.data_buffer_gb == 0.0
    assert records[0].observed_soc == pytest.approx(DEFAULT_CONFIG.initial_soc)
    assert result.state.soc > 0.0
    assert result.state.data_buffer_gb == 0.0


def test_scenario_disrupted_final_contact_does_not_refresh_telemetry():
    policy = RecordingPolicy()
    records = []
    result = Simulator(
        policy,
        ZeroFinalContactScenario(),
        contact_model=AlwaysCommandContactModel(),
        operator_view="delayed_telemetry",
    ).run(hours_as_years(2), on_hour=records.append)

    assert all(record.base_cmd_contact_min == 5.0 for record in records)
    assert all(record.cmd_contact_min == 0.0 for record in records)
    assert not any(record.telemetry_updated_this_hour for record in records)
    assert not any(record.plan_uploaded_this_hour for record in records)
    assert result.state.current_plan is None
    assert policy.seen == []
    assert [record.telemetry_age_hours for record in records] == [0, 1]
    assert records[1].observed_soc == pytest.approx(DEFAULT_CONFIG.initial_soc)
    assert records[1].soc != pytest.approx(records[1].observed_soc)


def test_onboard_safe_override_uses_real_state_not_stale_observation():
    policy = RecordingPolicy(Mode.IMAGING)
    records = []
    Simulator(
        policy,
        LowPowerAfterUploadScenario(),
        contact_model=FirstHourCommandContactModel(),
        operator_view="delayed_telemetry",
    ).run(hours_as_years(2), on_hour=records.append)

    assert policy.seen[0].soc == pytest.approx(DEFAULT_CONFIG.initial_soc)
    assert len(policy.seen) == DEFAULT_CONFIG.plan_duration_hours
    assert records[1].observed_soc == pytest.approx(DEFAULT_CONFIG.initial_soc)
    assert records[1].planned_mode == Mode.IMAGING.value
    assert records[1].mode == Mode.SAFE.value
    assert records[1].soc < policy.safe_threshold


def test_no_contact_hours_execute_stored_plan_without_live_policy_calls():
    policy = RecordingPolicy(Mode.IMAGING)
    records = []
    result = Simulator(
        policy,
        contact_model=FirstHourCommandContactModel(),
        operator_view="delayed_telemetry",
    ).run(hours_as_years(3), on_hour=records.append)

    assert len(policy.seen) == DEFAULT_CONFIG.plan_duration_hours
    assert len(result.state.current_plan.planned_modes) == (
        DEFAULT_CONFIG.plan_duration_hours
    )
    assert [record.planned_mode for record in records] == [
        Mode.IMAGING.value
    ] * 3
    assert [record.mode for record in records] == [Mode.IMAGING.value] * 3
    assert [record.plan_mode_index for record in records] == [0, 1, 2]
    assert [record.plan_modes_remaining for record in records] == [24, 23, 22]
    assert [record.cmd_contact_min for record in records] == [5.0, 0.0, 0.0]


def test_state_log_has_v25_fields_and_summary_keeps_only_operator_view(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--operator-view", "delayed_telemetry",
        "--results-dir", str(tmp_path),
    ]) == 0

    state_rows = read_rows(tmp_path / "state_log.csv")
    assert TELEMETRY_FIELDS <= set(state_rows[0])
    assert PLAN_FIELDS <= set(state_rows[0])
    assert {row["operator_view"] for row in state_rows} == {"delayed_telemetry"}
    for field in STATE_ONLY_TELEMETRY_FIELDS:
        assert all(row[field] != "" for row in state_rows)

    summary_rows = read_rows(tmp_path / "summary.csv")
    assert summary_rows[0]["operator_view"] == "delayed_telemetry"
    assert STATE_ONLY_TELEMETRY_FIELDS.isdisjoint(summary_rows[0])
    assert PLAN_FIELDS.isdisjoint(summary_rows[0])
    assert STATE_ONLY_TELEMETRY_FIELDS.isdisjoint(
        read_fields(tmp_path / "checkpoints.csv")
    )
    assert PLAN_FIELDS.isdisjoint(read_fields(tmp_path / "checkpoints.csv"))
    assert STATE_ONLY_TELEMETRY_FIELDS.isdisjoint(
        read_fields(tmp_path / "events_log.csv")
    )
    assert PLAN_FIELDS.isdisjoint(read_fields(tmp_path / "events_log.csv"))


def test_omniscient_state_log_fields_are_valid(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--results-dir", str(tmp_path),
    ]) == 0

    rows = read_rows(tmp_path / "state_log.csv")
    assert {row["operator_view"] for row in rows} == {"omniscient"}
    assert TELEMETRY_FIELDS <= set(rows[0])
    for row in rows:
        for field in STATE_ONLY_TELEMETRY_FIELDS - {
            "telemetry_updated_this_hour"
        }:
            float(row[field])


def test_geometry_contacts_work_with_delayed_telemetry(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--contact-model", "geometry",
        "--operator-view", "delayed_telemetry",
        "--results-dir", str(tmp_path),
    ]) == 0

    rows = read_rows(tmp_path / "state_log.csv")
    assert rows
    assert rows[0]["contact_model"] == "geometry"
    assert "geometry_raw_visible_seconds" in rows[0]
    assert TELEMETRY_FIELDS <= set(rows[0])
    assert rows[0]["operator_view"] == "delayed_telemetry"


def test_plan_policy_records_each_plan_generation_strategy(tmp_path):
    assert run.main([
        "--years", str(hours_as_years(1)),
        "--policy", "all",
        "--scenario", "nominal",
        "--operator-view", "delayed_telemetry",
        "--results-dir", str(tmp_path),
    ]) == 0

    uploaded_rows = [
        row for row in read_rows(tmp_path / "state_log.csv")
        if row["plan_uploaded_this_hour"] == "True"
    ]
    expected_policies = set(POLICIES)
    assert {row["policy"] for row in uploaded_rows} == expected_policies
    assert {row["plan_policy"] for row in uploaded_rows} == expected_policies
    assert all(row["policy"] == row["plan_policy"] for row in uploaded_rows)
    assert {row["plan_based_on_telemetry_hour"] for row in uploaded_rows} == {"0"}
    assert {row["plan_based_on_telemetry_age_hours"] for row in uploaded_rows} == {
        "0"
    }


def test_builtin_policies_generate_distinct_explicit_mode_sequences():
    sequences = {}
    for policy_name in ("aggressive", "conservative", "adaptive"):
        result = Simulator(
            make_policy(policy_name), operator_view="delayed_telemetry"
        ).run(hours_as_years(1))
        plan = result.state.current_plan
        assert plan.policy_name == policy_name
        assert len(plan.planned_modes) == plan.duration_hours
        sequences[policy_name] = plan.planned_modes

    assert len(set(sequences.values())) == 3


def test_monte_carlo_summary_records_delayed_operator_view(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "stochastic_post_life_events",
        "--monte-carlo", "2",
        "--operator-view", "delayed_telemetry",
        "--results-dir", str(tmp_path),
    ]) == 0

    for filename in ("summary.csv", "monte_carlo_summary.csv"):
        rows = read_rows(tmp_path / filename)
        assert len(rows) == 2
        assert {row["operator_view"] for row in rows} == {"delayed_telemetry"}
        assert STATE_ONLY_TELEMETRY_FIELDS.isdisjoint(rows[0])
        assert PLAN_FIELDS.isdisjoint(rows[0])
    assert not (tmp_path / "state_log.csv").exists()
    assert not (tmp_path / "checkpoints.csv").exists()
    assert not (tmp_path / "events_log.csv").exists()


def test_readme_documents_v25_operator_view():
    readme = Path("README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split()).lower()

    assert "V2.5 delayed telemetry operator view" in readme
    assert "--operator-view delayed_telemetry" in readme
    assert "`omniscient` remains the default" in readme
    assert "onboard safety" in normalized
    assert "use real state" in normalized
    assert "ground is not modeled as commanding the satellite every hour" in normalized
    assert "uploads a 24-hour daily plan" in normalized
    assert "stores an explicit simplified sequence of planned modes" in normalized
    assert "executes the stored plan entry" in normalized
    assert "does not call the policy as a live ground command each hour" in normalized
    assert "different policies generate different uploaded mode sequences" in normalized
    assert "not a full schedule optimizer" in normalized
