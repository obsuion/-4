"""Focused tests for separated V5.0B3 runtime state domains."""

import ast
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from ops_sim.v5.controller_state import ControllerState
from ops_sim.v5.diagnostics import Diagnostics
from ops_sim.v5.ids import (
    AuthorityId,
    CommandId,
    ControllerId,
    DataProductId,
    MissionRequestId,
    ParameterId,
    PlanId,
    TelemetrySnapshotId,
    ThermalNodeId,
    WorldEventId,
)
from ops_sim.v5.knowledge import GroundKnowledgeState, TelemetrySnapshot
from ops_sim.v5.mission import MissionState
from ops_sim.v5.state import (
    BatteryDegradationState,
    BatteryState,
    DataStorageState,
    DegradationState,
    FDIRState,
    OnboardOperationsState,
    OperationalMode,
    PropulsionState,
    SpacecraftState,
    SolarDegradationState,
    ThermalNodeState,
    ThermalState,
)


ROOT = Path(__file__).resolve().parents[1]
B3_MODULE_PATHS = (
    ROOT / "ops_sim" / "v5" / "state.py",
    ROOT / "ops_sim" / "v5" / "knowledge.py",
    ROOT / "ops_sim" / "v5" / "mission.py",
    ROOT / "ops_sim" / "v5" / "controller_state.py",
    ROOT / "ops_sim" / "v5" / "diagnostics.py",
)


def _onboard(**changes) -> OnboardOperationsState:
    values = {
        "operational_mode": OperationalMode.STANDBY,
        "fdir_state": FDIRState.NORMAL,
        "accepted_plan_id": None,
        "accepted_authority_id": None,
        "last_qualifying_contact_time_seconds": None,
        "critical_energy_since_seconds": None,
    }
    values.update(changes)
    return OnboardOperationsState(**values)


def _thermal_state() -> ThermalState:
    return ThermalState(
        (
            ThermalNodeState(ThermalNodeId("bus"), 300.0),
            ThermalNodeState(ThermalNodeId("battery"), 295.0),
            ThermalNodeState(ThermalNodeId("payload"), 290.0),
        )
    )


def _spacecraft(**changes) -> SpacecraftState:
    values = {
        "battery": BatteryState(120.0),
        "propulsion": PropulsionState(12.0),
        "thermal": _thermal_state(),
        "degradation": DegradationState(
            BatteryDegradationState(1.0, 0.0),
            SolarDegradationState(1.0),
        ),
        "onboard": _onboard(),
        "data_storage": DataStorageState(()),
    }
    values.update(changes)
    return SpacecraftState(**values)


def _snapshot(**changes) -> TelemetrySnapshot:
    values = {
        "snapshot_id": TelemetrySnapshotId("snapshot-0001"),
        "sampled_at_seconds": 100,
        "received_at_seconds": 110,
        "battery_energy_wh": 120.0,
        "delta_v_remaining_m_per_s": 12.0,
        "operational_mode": OperationalMode.STANDBY,
    }
    values.update(changes)
    return TelemetrySnapshot(**values)


def _mission(**changes) -> MissionState:
    values = {
        "pending_request_ids": (),
        "completed_request_ids": (),
        "data_product_ids": (),
        "active_plan_id": None,
        "command_ids": (),
        "resolved_world_event_ids": (),
    }
    values.update(changes)
    return MissionState(**values)


@pytest.mark.parametrize(
    "state_type,field_name",
    (
        (BatteryState, "energy_wh"),
        (PropulsionState, "delta_v_remaining_m_per_s"),
    ),
)
@pytest.mark.parametrize("value", (0, 0.0, 1, 1.5))
def test_physical_states_accept_zero_and_positive_finite_reals(
    state_type,
    field_name,
    value,
) -> None:
    state = state_type(value)

    assert getattr(state, field_name) == value


@pytest.mark.parametrize("state_type", (BatteryState, PropulsionState))
def test_physical_states_reject_negative_values(state_type) -> None:
    with pytest.raises(ValueError):
        state_type(-0.001)


@pytest.mark.parametrize("state_type", (BatteryState, PropulsionState))
def test_physical_states_reject_bool_nonreal_and_nonfinite(state_type) -> None:
    for value in (True, False, "1"):
        with pytest.raises(TypeError):
            state_type(value)
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            state_type(value)


@pytest.mark.parametrize(
    "state,field_name,replacement",
    (
        (BatteryState(1.0), "energy_wh", 2.0),
        (
            PropulsionState(1.0),
            "delta_v_remaining_m_per_s",
            2.0,
        ),
    ),
)
def test_physical_states_are_slotted_and_intentionally_mutable(
    state,
    field_name,
    replacement,
) -> None:
    assert not hasattr(state, "__dict__")

    setattr(state, field_name, replacement)

    assert getattr(state, field_name) == replacement


def test_operational_and_fdir_enums_have_exact_distinct_values() -> None:
    assert tuple(item.value for item in OperationalMode) == (
        "safe",
        "standby",
        "imaging",
        "downlink",
        "maneuver",
        "backup",
        "emergency-beacon",
    )
    assert tuple(item.value for item in FDIRState) == (
        "normal",
        "backup",
        "emergency-beacon",
    )
    assert OperationalMode is not FDIRState
    assert type(OperationalMode.BACKUP) is not type(FDIRState.BACKUP)


def test_operational_mode_and_fdir_regime_may_differ() -> None:
    onboard = _onboard(
        operational_mode=OperationalMode.SAFE,
        fdir_state=FDIRState.EMERGENCY_BEACON,
    )

    assert onboard.operational_mode is OperationalMode.SAFE
    assert onboard.fdir_state is FDIRState.EMERGENCY_BEACON


def test_onboard_operations_accepts_optional_typed_identity() -> None:
    onboard = _onboard(
        accepted_plan_id=PlanId("plan-0001"),
        accepted_authority_id=AuthorityId("ground-authority-0001"),
        last_qualifying_contact_time_seconds=0,
        critical_energy_since_seconds=25,
    )

    assert onboard.accepted_plan_id == PlanId("plan-0001")
    assert onboard.accepted_authority_id == AuthorityId(
        "ground-authority-0001"
    )
    assert onboard.last_qualifying_contact_time_seconds == 0
    assert onboard.critical_energy_since_seconds == 25
    assert _onboard().accepted_plan_id is None


@pytest.mark.parametrize(
    "changes",
    (
        {"operational_mode": "standby"},
        {"operational_mode": FDIRState.NORMAL},
        {"fdir_state": "normal"},
        {"fdir_state": OperationalMode.STANDBY},
    ),
)
def test_onboard_operations_rejects_wrong_enum_types(changes) -> None:
    with pytest.raises(TypeError):
        _onboard(**changes)


@pytest.mark.parametrize(
    "changes",
    (
        {"accepted_plan_id": AuthorityId("wrong-plan")},
        {"accepted_plan_id": ParameterId("wrong-plan")},
        {"accepted_authority_id": PlanId("wrong-authority")},
        {"accepted_authority_id": ParameterId("wrong-authority")},
    ),
)
def test_onboard_operations_rejects_wrong_identity_types(changes) -> None:
    with pytest.raises(TypeError):
        _onboard(**changes)


@pytest.mark.parametrize(
    "field_name",
    (
        "last_qualifying_contact_time_seconds",
        "critical_energy_since_seconds",
    ),
)
@pytest.mark.parametrize("value", (None, 0, 1, 3600))
def test_onboard_operations_accepts_optional_nonnegative_timestamps(
    field_name,
    value,
) -> None:
    onboard = _onboard(**{field_name: value})

    assert getattr(onboard, field_name) == value


@pytest.mark.parametrize(
    "field_name",
    (
        "last_qualifying_contact_time_seconds",
        "critical_energy_since_seconds",
    ),
)
def test_onboard_operations_rejects_invalid_timestamps(field_name) -> None:
    with pytest.raises(ValueError):
        _onboard(**{field_name: -1})
    for value in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            _onboard(**{field_name: value})


def test_onboard_operations_is_slotted_and_intentionally_mutable() -> None:
    onboard = _onboard()
    assert not hasattr(onboard, "__dict__")

    onboard.operational_mode = OperationalMode.SAFE
    onboard.accepted_plan_id = PlanId("plan-0002")

    assert onboard.operational_mode is OperationalMode.SAFE
    assert onboard.accepted_plan_id == PlanId("plan-0002")


def test_spacecraft_state_has_exact_minimal_truth_structure() -> None:
    spacecraft = _spacecraft()

    assert tuple(field.name for field in fields(SpacecraftState)) == (
        "battery",
        "propulsion",
        "thermal",
        "degradation",
        "onboard",
        "data_storage",
    )
    assert type(spacecraft.battery) is BatteryState
    assert type(spacecraft.propulsion) is PropulsionState
    assert type(spacecraft.thermal) is ThermalState
    assert type(spacecraft.onboard) is OnboardOperationsState
    assert type(spacecraft.data_storage) is DataStorageState


@pytest.mark.parametrize(
    "field_name",
    ("battery", "propulsion", "thermal", "onboard", "data_storage"),
)
def test_spacecraft_state_rejects_wrong_nested_types(field_name) -> None:
    with pytest.raises(TypeError):
        _spacecraft(**{field_name: object()})


def test_spacecraft_state_is_slotted_and_intentionally_mutable() -> None:
    spacecraft = _spacecraft()
    replacement = BatteryState(80.0)
    assert not hasattr(spacecraft, "__dict__")

    spacecraft.battery = replacement

    assert spacecraft.battery is replacement


def test_telemetry_snapshot_accepts_equal_and_later_receipt_times() -> None:
    immediate = _snapshot(sampled_at_seconds=100, received_at_seconds=100)
    delayed = _snapshot(sampled_at_seconds=100, received_at_seconds=125)

    assert immediate.received_at_seconds == immediate.sampled_at_seconds
    assert delayed.received_at_seconds > delayed.sampled_at_seconds


def test_telemetry_snapshot_is_frozen_slotted_and_explicit() -> None:
    snapshot = _snapshot()

    assert tuple(field.name for field in fields(TelemetrySnapshot)) == (
        "snapshot_id",
        "sampled_at_seconds",
        "received_at_seconds",
        "battery_energy_wh",
        "delta_v_remaining_m_per_s",
        "operational_mode",
    )
    assert not hasattr(snapshot, "__dict__")
    assert isinstance(hash(snapshot), int)
    with pytest.raises(FrozenInstanceError):
        snapshot.received_at_seconds = 120


def test_telemetry_snapshot_rejects_receipt_before_sample() -> None:
    with pytest.raises(ValueError):
        _snapshot(sampled_at_seconds=100, received_at_seconds=99)


@pytest.mark.parametrize("field_name", ("sampled_at_seconds", "received_at_seconds"))
def test_telemetry_snapshot_rejects_invalid_timestamps(field_name) -> None:
    with pytest.raises(ValueError):
        _snapshot(**{field_name: -1})
    for value in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            _snapshot(**{field_name: value})


@pytest.mark.parametrize(
    "field_name",
    ("battery_energy_wh", "delta_v_remaining_m_per_s"),
)
def test_telemetry_snapshot_rejects_invalid_physical_values(field_name) -> None:
    with pytest.raises(ValueError):
        _snapshot(**{field_name: -0.001})
    for value in (True, False, "1"):
        with pytest.raises(TypeError):
            _snapshot(**{field_name: value})
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            _snapshot(**{field_name: value})


def test_telemetry_snapshot_rejects_wrong_identity_and_mode_types() -> None:
    with pytest.raises(TypeError):
        _snapshot(snapshot_id=PlanId("wrong-snapshot"))
    with pytest.raises(TypeError):
        _snapshot(operational_mode="standby")
    with pytest.raises(TypeError):
        _snapshot(operational_mode=FDIRState.NORMAL)


def test_ground_knowledge_accepts_empty_and_explicit_knowledge() -> None:
    empty = GroundKnowledgeState(None, ())
    snapshot = _snapshot()
    event_ids = (WorldEventId("event-0001"), WorldEventId("event-0002"))
    populated = GroundKnowledgeState(snapshot, event_ids)

    assert empty.latest_telemetry is None
    assert empty.known_world_event_ids == ()
    assert populated.latest_telemetry is snapshot
    assert populated.known_world_event_ids is event_ids


def test_ground_knowledge_rejects_wrong_snapshot_type() -> None:
    with pytest.raises(TypeError):
        GroundKnowledgeState(_spacecraft(), ())


def test_ground_knowledge_requires_typed_unique_event_tuple() -> None:
    event_id = WorldEventId("event-0001")
    with pytest.raises(TypeError):
        GroundKnowledgeState(None, [event_id])
    with pytest.raises(TypeError):
        GroundKnowledgeState(None, (PlanId("wrong-event"),))
    with pytest.raises(ValueError):
        GroundKnowledgeState(None, (event_id, event_id))


def test_ground_knowledge_is_slotted_and_intentionally_mutable() -> None:
    knowledge = GroundKnowledgeState(None, ())
    snapshot = _snapshot()
    assert not hasattr(knowledge, "__dict__")

    knowledge.latest_telemetry = snapshot
    knowledge.known_world_event_ids = (WorldEventId("event-0001"),)

    assert knowledge.latest_telemetry is snapshot
    assert knowledge.known_world_event_ids == (WorldEventId("event-0001"),)


def test_mission_state_accepts_empty_and_typed_identity_state() -> None:
    assert _mission().pending_request_ids == ()
    mission = _mission(
        pending_request_ids=(MissionRequestId("request-0001"),),
        completed_request_ids=(MissionRequestId("request-0002"),),
        data_product_ids=(DataProductId("product-0001"),),
        active_plan_id=PlanId("plan-0001"),
        command_ids=(CommandId("command-0001"),),
        resolved_world_event_ids=(WorldEventId("event-0001"),),
    )

    assert mission.active_plan_id == PlanId("plan-0001")


MISSION_TUPLE_CASES = (
    ("pending_request_ids", MissionRequestId("request-0001")),
    ("completed_request_ids", MissionRequestId("request-0002")),
    ("data_product_ids", DataProductId("product-0001")),
    ("command_ids", CommandId("command-0001")),
    ("resolved_world_event_ids", WorldEventId("event-0001")),
)


@pytest.mark.parametrize("field_name,identifier", MISSION_TUPLE_CASES)
def test_mission_state_rejects_list_and_duplicate_ids(
    field_name,
    identifier,
) -> None:
    with pytest.raises(TypeError):
        _mission(**{field_name: [identifier]})
    with pytest.raises(ValueError):
        _mission(**{field_name: (identifier, identifier)})


@pytest.mark.parametrize("field_name,identifier", MISSION_TUPLE_CASES)
def test_mission_state_rejects_wrong_tuple_id_types(
    field_name,
    identifier,
) -> None:
    with pytest.raises(TypeError):
        _mission(**{field_name: (ParameterId("wrong-id"),)})


def test_mission_state_rejects_pending_completed_overlap() -> None:
    request_id = MissionRequestId("request-0001")
    with pytest.raises(ValueError):
        _mission(
            pending_request_ids=(request_id,),
            completed_request_ids=(request_id,),
        )


def test_mission_state_accepts_optional_plan_and_rejects_wrong_type() -> None:
    assert _mission(active_plan_id=None).active_plan_id is None
    assert _mission(active_plan_id=PlanId("plan-0001")).active_plan_id == (
        PlanId("plan-0001")
    )
    with pytest.raises(TypeError):
        _mission(active_plan_id=CommandId("wrong-plan"))


def test_mission_state_is_slotted_minimal_and_intentionally_mutable() -> None:
    mission = _mission()
    assert tuple(field.name for field in fields(MissionState)) == (
        "pending_request_ids",
        "completed_request_ids",
        "data_product_ids",
        "active_plan_id",
        "command_ids",
        "resolved_world_event_ids",
    )
    assert not hasattr(mission, "__dict__")

    mission.active_plan_id = PlanId("plan-0001")
    mission.pending_request_ids = (MissionRequestId("request-0001"),)

    assert mission.active_plan_id == PlanId("plan-0001")
    assert mission.pending_request_ids == (MissionRequestId("request-0001"),)


def test_controller_state_validates_identity_and_replan_count() -> None:
    controller = ControllerState(
        ControllerId("rolling-horizon"),
        PlanId("plan-0001"),
        0,
    )

    assert controller.latest_plan_id == PlanId("plan-0001")
    assert ControllerState(
        ControllerId("rolling-horizon"), None, 2
    ).replan_count == 2


def test_controller_state_rejects_wrong_identity_types() -> None:
    with pytest.raises(TypeError):
        ControllerState(ParameterId("wrong-controller"), None, 0)
    with pytest.raises(TypeError):
        ControllerState(
            ControllerId("rolling-horizon"),
            CommandId("wrong-plan"),
            0,
        )


def test_controller_state_rejects_invalid_replan_count() -> None:
    with pytest.raises(ValueError):
        ControllerState(ControllerId("rolling-horizon"), None, -1)
    for value in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            ControllerState(ControllerId("rolling-horizon"), None, value)


def test_controller_state_is_slotted_and_intentionally_mutable() -> None:
    controller = ControllerState(
        ControllerId("rolling-horizon"), None, 0
    )
    assert not hasattr(controller, "__dict__")

    controller.latest_plan_id = PlanId("plan-0001")
    controller.replan_count = 1

    assert controller.latest_plan_id == PlanId("plan-0001")
    assert controller.replan_count == 1


@pytest.mark.parametrize("completed_steps", (0, 1, 25))
def test_diagnostics_accepts_nonnegative_steps(completed_steps) -> None:
    assert Diagnostics(completed_steps).completed_steps == completed_steps


def test_diagnostics_rejects_invalid_steps() -> None:
    with pytest.raises(ValueError):
        Diagnostics(-1)
    for value in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            Diagnostics(value)


def test_diagnostics_is_minimal_slotted_and_intentionally_mutable() -> None:
    diagnostics = Diagnostics(0)
    assert tuple(field.name for field in fields(Diagnostics)) == (
        "completed_steps",
    )
    assert not hasattr(diagnostics, "__dict__")

    diagnostics.completed_steps = 1

    assert diagnostics.completed_steps == 1


def test_runtime_mutability_and_snapshot_immutability_are_explicit() -> None:
    mutable_types = (
        BatteryState,
        PropulsionState,
        ThermalNodeState,
        ThermalState,
        OnboardOperationsState,
        DataStorageState,
        SpacecraftState,
        GroundKnowledgeState,
        MissionState,
        ControllerState,
        Diagnostics,
    )
    assert all(not item.__dataclass_params__.frozen for item in mutable_types)
    assert TelemetrySnapshot.__dataclass_params__.frozen


def test_state_domains_exclude_prohibited_derived_fields() -> None:
    domain_types = (
        BatteryState,
        PropulsionState,
        ThermalNodeState,
        ThermalState,
        OnboardOperationsState,
        DataStorageState,
        SpacecraftState,
        TelemetrySnapshot,
        GroundKnowledgeState,
        MissionState,
        ControllerState,
        Diagnostics,
    )
    prohibited = {
        "soc",
        "battery_percent",
        "delta_v_used",
        "fuel_percent",
        "telemetry_age",
        "hours_since_contact",
        "critical_soc_hours",
        "plan_age",
        "request_completion_fraction",
        "total_image_count",
        "total_data_generated",
        "total_data_downlinked",
        "total_data_lost",
        "current_simulation_year",
        "simulation_time_seconds",
        "simulation_clock",
        "alive",
        "total_health",
        "minimum_soc",
        "mode_durations",
    }
    for domain_type in domain_types:
        assert prohibited.isdisjoint(
            field.name for field in fields(domain_type)
        )


def test_non_spacecraft_domains_do_not_contain_spacecraft_truth() -> None:
    non_spacecraft_types = (
        TelemetrySnapshot,
        GroundKnowledgeState,
        MissionState,
        ControllerState,
        Diagnostics,
    )
    for domain_type in non_spacecraft_types:
        assert "SpacecraftState" not in {
            str(field.type) for field in fields(domain_type)
        }

    for path in B3_MODULE_PATHS[1:]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not any(
            isinstance(node, ast.Name) and node.id == "SpacecraftState"
            for node in ast.walk(tree)
        ), f"{path.name} references SpacecraftState"


def test_b3_modules_do_not_reference_default_config() -> None:
    for path in B3_MODULE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id != "DEFAULT_CONFIG"
            if isinstance(node, ast.Attribute):
                assert node.attr != "DEFAULT_CONFIG"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                assert all(
                    alias.name != "DEFAULT_CONFIG" for alias in node.names
                )


def test_b3_modules_define_explicit_exports() -> None:
    from ops_sim.v5 import (
        controller_state,
        diagnostics,
        knowledge,
        mission,
        state,
    )

    assert state.__all__ == [
        "BatteryDegradationState",
        "BatteryState",
        "DataStorageState",
        "DegradationState",
        "FDIRState",
        "OnboardOperationsState",
        "OperationalMode",
        "PropulsionState",
        "SpacecraftState",
        "SolarDegradationState",
        "ThermalNodeState",
        "ThermalState",
    ]
    assert knowledge.__all__ == [
        "GroundKnowledgeState",
        "TelemetrySnapshot",
    ]
    assert mission.__all__ == ["MissionState"]
    assert controller_state.__all__ == ["ControllerState"]
    assert diagnostics.__all__ == ["Diagnostics"]
