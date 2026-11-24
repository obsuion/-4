"""Integrated imaging release demonstration for V5.3F4A."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields
import os
from pathlib import Path
import subprocess
import sys

import pytest

import examples.v53_integrated_imaging_demo as demo_module
from examples.v53_integrated_imaging_demo import (
    ImagingCaseReport,
    ReferenceSampleGridReport,
    ThermalNodeTemperatureReport,
    V53IntegratedImagingDemoReport,
    run_v53_integrated_imaging_demo,
)
from ops_sim.v5.checkpoint import CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.engine import ImagingEngineStepAttempt, SimulationEngine
from ops_sim.v5.imaging_execution import (
    ImagingExecutionAuthorizationStatus,
)
from ops_sim.v5.imaging_resources import AcquisitionServiceStatus
from ops_sim.v5.ids import ThermalNodeId
from ops_sim.v5.provenance import ProvenanceClass
from ops_sim.v5.thermal_routing import ElectricalLoadComponent


ROOT = Path(__file__).resolve().parents[1]
DEMO_PATH = ROOT / "examples" / "v53_integrated_imaging_demo.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"


@pytest.fixture(scope="module")
def demo_report() -> V53IntegratedImagingDemoReport:
    return run_v53_integrated_imaging_demo()


def _authoritative_references(context) -> tuple[object, ...]:
    spacecraft = context.spacecraft_state
    knowledge = context.ground_knowledge_state
    return (
        spacecraft,
        spacecraft.battery,
        spacecraft.propulsion,
        spacecraft.thermal,
        *spacecraft.thermal.node_states,
        spacecraft.degradation,
        spacecraft.degradation.battery,
        spacecraft.degradation.solar,
        spacecraft.onboard,
        spacecraft.data_storage,
        knowledge,
        knowledge.latest_telemetry,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def test_demo_import_has_no_output_or_execution_side_effect() -> None:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import examples.v53_integrated_imaging_demo",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == ""
    assert completed.stderr == ""


def test_demo_report_contracts_are_simple_frozen_slotted_values(
    demo_report,
) -> None:
    assert tuple(field.name for field in fields(ThermalNodeTemperatureReport)) == (
        "node_id",
        "start_temperature_k",
        "end_temperature_k",
    )
    assert tuple(field.name for field in fields(ReferenceSampleGridReport)) == (
        "cross_track_width_m",
        "along_track_length_m",
        "footprint_area_m2",
        "panchromatic_equivalent_samples",
        "multispectral_equivalent_samples_per_band",
        "multispectral_equivalent_samples_total",
        "total_equivalent_samples",
        "sample_grid_proxy_bits",
        "sample_grid_proxy_bytes",
        "sample_grid_proxy_megabits_per_square_km",
        "interpretation",
    )
    assert tuple(field.name for field in fields(ImagingCaseReport)) == (
        "name",
        "attempt",
        "authorization_status",
        "acquisition_service_status",
        "scheduled_start_seconds",
        "dt_seconds",
        "sequence_feasible",
        "transition_angular_separation_deg",
        "slew_elapsed_time_seconds",
        "settling_time_seconds",
        "candidate_readiness_seconds",
        "footprint_area_m2",
        "requested_acquisition_power_w",
        "requested_acquisition_energy_wh",
        "sample_grid_proxy_total_samples",
        "sample_grid_proxy_bits",
        "sample_grid_proxy_bytes",
        "total_eps_requested_power_w",
        "aggregate_served_power_w",
        "aggregate_unmet_power_w",
        "minimum_served_acquisition_power_w",
        "maximum_served_acquisition_power_w",
        "routed_payload_heat_w",
        "battery_conversion_heat_w",
        "start_battery_energy_wh",
        "raw_eps_end_battery_energy_wh",
        "authoritative_battery_end_energy_wh",
        "battery_throughput_increment_wh",
        "representative_battery_temperature_k",
        "start_battery_retention",
        "end_battery_retention",
        "start_solar_retention",
        "end_solar_retention",
        "thermal_node_temperatures",
        "committed_context_time_seconds",
        "committed_completed_steps",
        "step_result_present",
        "context_unchanged",
        "authoritative_identity_unchanged",
        "mission_state_unchanged",
    )
    assert tuple(field.name for field in fields(V53IntegratedImagingDemoReport)) == (
        "authorized",
        "sequence_infeasible",
        "full_service_impossible",
        "service_allocation_required",
        "reference_sample_grid",
        "replay_attempt_equal",
        "replay_context_equal",
        "repeat_attempt_equal",
        "repeat_context_equal",
        "checkpoint_schema_version",
    )

    for contract, instance in (
        (
            ThermalNodeTemperatureReport,
            demo_report.authorized.thermal_node_temperatures[0],
        ),
        (ReferenceSampleGridReport, demo_report.reference_sample_grid),
        (ImagingCaseReport, demo_report.authorized),
        (V53IntegratedImagingDemoReport, demo_report),
    ):
        assert contract.__dataclass_params__.frozen
        assert not hasattr(instance, "__dict__")
        assert all(
            field.default is MISSING and field.default_factory is MISSING
            for field in fields(contract)
        )
    with pytest.raises(FrozenInstanceError):
        demo_report.authorized.name = "changed"


def test_authorized_case_reports_the_exact_reviewed_proposal_chain(
    demo_report,
) -> None:
    case = demo_report.authorized
    attempt = case.attempt
    authorization = attempt.authorization_result
    electrical = authorization.electrical_result
    evaluation = electrical.acquisition_evaluation
    sequence = evaluation.sequence_result
    transition = sequence.transition_result
    acquisition = evaluation.acquisition_result
    eps_result = electrical.eps_result
    bounds = electrical.service_bounds
    thermal = authorization.thermal_proposal
    step = attempt.step_result

    assert type(attempt) is ImagingEngineStepAttempt
    assert case.name == "authorized"
    assert case.authorization_status is (
        ImagingExecutionAuthorizationStatus.AUTHORIZED
    )
    assert case.acquisition_service_status is AcquisitionServiceStatus.FULLY_SERVED
    assert authorization.status is case.authorization_status
    assert case.step_result_present is True
    assert step is not None
    assert transition is not None
    assert acquisition is not None
    assert eps_result is not None
    assert bounds is not None
    assert thermal is not None

    assert step.eps_result is electrical.eps_result
    assert step.eps_capability_result is electrical.eps_capability_result
    assert step.thermal_coupling_result is (
        thermal.eps_thermal_coupling_result
    )
    assert thermal.electrical_result is electrical

    assert case.scheduled_start_seconds == (
        authorization.execution.scheduled_start_seconds
    )
    assert case.dt_seconds == step.dt_seconds
    assert case.sequence_feasible is sequence.feasible is True
    assert case.transition_angular_separation_deg == (
        transition.angular_separation_deg
    )
    assert case.slew_elapsed_time_seconds == (
        transition.slew_elapsed_time_seconds
    )
    assert case.settling_time_seconds == transition.settling_time_seconds
    assert case.candidate_readiness_seconds == (
        sequence.candidate_next_start_seconds
    )
    assert case.footprint_area_m2 == acquisition.footprint_area_m2
    assert case.requested_acquisition_power_w == (
        acquisition.requested_acquisition_power_w
    )
    assert case.requested_acquisition_power_w == 90.0
    assert case.requested_acquisition_energy_wh == (
        acquisition.acquisition_energy_wh
    )
    assert case.sample_grid_proxy_total_samples == (
        acquisition.total_equivalent_samples
    )
    assert case.sample_grid_proxy_bits == (
        acquisition.uncompressed_equivalent_bits
    )
    assert case.sample_grid_proxy_bytes == (
        acquisition.uncompressed_equivalent_bytes
    )
    assert case.total_eps_requested_power_w == eps_result.battery.load_w
    assert case.total_eps_requested_power_w == 118.0
    assert case.aggregate_served_power_w == eps_result.battery.served_load_w
    assert case.aggregate_unmet_power_w == eps_result.battery.unmet_load_w == 0
    assert case.minimum_served_acquisition_power_w == (
        bounds.minimum_served_acquisition_power_w
    )
    assert case.maximum_served_acquisition_power_w == (
        bounds.maximum_served_acquisition_power_w
    )

    payload_heat = next(
        ledger.retained_heat_w
        for ledger in thermal.routed_internal_heat_result.component_ledgers
        if ledger.component is ElectricalLoadComponent.PAYLOAD
    )
    assert case.routed_payload_heat_w == payload_heat
    assert case.battery_conversion_heat_w == sum(
        ledger.battery_conversion_heat_w
        for ledger in thermal.eps_thermal_coupling_result.node_heat_ledgers
    )


def test_authorized_case_reports_and_commits_exact_endpoints(
    demo_report,
) -> None:
    case = demo_report.authorized
    authorization = case.attempt.authorization_result
    electrical = authorization.electrical_result
    proposal = authorization.thermal_proposal
    step = case.attempt.step_result
    assert proposal is not None
    assert step is not None
    degradation = step.battery_degradation_result
    reconciliation = step.battery_capacity_reconciliation_result
    assert degradation is not None
    assert reconciliation is not None

    assert case.start_battery_energy_wh == (
        electrical.eps_result.battery.start_energy_wh
    )
    assert case.raw_eps_end_battery_energy_wh == (
        electrical.eps_result.battery.end_energy_wh
    )
    assert case.authoritative_battery_end_energy_wh == (
        reconciliation.authoritative_end_energy_wh
    )
    assert case.battery_throughput_increment_wh == (
        degradation.throughput_increment_wh
    )
    assert case.representative_battery_temperature_k == (
        degradation.representative_temperature_k
    )
    assert case.start_battery_retention == (
        degradation.start_usable_capacity_retention
    )
    assert case.end_battery_retention == (
        degradation.end_usable_capacity_retention
    )
    assert case.start_solar_retention == (
        electrical.eps_capability_result.solar_generation_retention
    )
    if step.solar_degradation_result is None:
        assert case.end_solar_retention == case.start_solar_retention
    else:
        assert case.end_solar_retention == (
            step.solar_degradation_result.end_generation_retention
        )

    transitions = (
        proposal.eps_thermal_coupling_result.thermal_result.node_transitions
    )
    assert tuple(
        (
            item.node_id,
            item.start_temperature_k,
            item.end_temperature_k,
        )
        for item in case.thermal_node_temperatures
    ) == tuple(
        (
            item.node_id,
            item.start_temperature_k,
            item.end_temperature_k,
        )
        for item in transitions
    )
    assert case.committed_context_time_seconds == (
        case.scheduled_start_seconds + case.dt_seconds
    )
    assert case.committed_completed_steps == 1
    assert case.context_unchanged is False
    assert case.mission_state_unchanged is True


def test_all_three_nonauthorization_cases_return_without_commit(
    demo_report,
) -> None:
    sequence = demo_report.sequence_infeasible
    impossible = demo_report.full_service_impossible
    allocation = demo_report.service_allocation_required

    assert sequence.name == "sequence-infeasible"
    assert sequence.authorization_status is (
        ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE
    )
    assert sequence.acquisition_service_status is None
    assert sequence.sequence_feasible is False
    assert sequence.attempt.step_result is None
    assert sequence.attempt.authorization_result.thermal_proposal is None

    for case, service_status in (
        (impossible, AcquisitionServiceStatus.FULL_SERVICE_IMPOSSIBLE),
        (allocation, AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED),
    ):
        assert case.authorization_status is (
            ImagingExecutionAuthorizationStatus
            .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED
        )
        assert case.acquisition_service_status is service_status
        assert case.sequence_feasible is True
        assert case.attempt.step_result is None
        assert case.attempt.authorization_result.thermal_proposal is None
        assert case.aggregate_unmet_power_w > 0
        assert case.minimum_served_acquisition_power_w <= (
            case.maximum_served_acquisition_power_w
        )
        assert case.routed_payload_heat_w is None
        assert case.battery_throughput_increment_wh is None
        assert case.authoritative_battery_end_energy_wh is None

    assert impossible.maximum_served_acquisition_power_w < (
        impossible.requested_acquisition_power_w
    )
    assert allocation.minimum_served_acquisition_power_w < (
        allocation.requested_acquisition_power_w
    )
    assert allocation.maximum_served_acquisition_power_w == (
        allocation.requested_acquisition_power_w
    )

    for case in (sequence, impossible, allocation):
        assert case.step_result_present is False
        assert case.context_unchanged is True
        assert case.authoritative_identity_unchanged is True
        assert case.mission_state_unchanged is True
        assert case.committed_context_time_seconds == (
            case.scheduled_start_seconds
        )
        assert case.committed_completed_steps == 0


def test_four_cases_use_independent_equivalent_start_contexts_and_real_physics(
    monkeypatch,
) -> None:
    original = SimulationEngine.step_imaging
    records = []

    def capture(self, context, previous_execution, execution, **kwargs):
        before = deepcopy(context)
        references = _authoritative_references(context)
        attempt = original(
            self,
            context,
            previous_execution,
            execution,
            **kwargs,
        )
        records.append(
            {
                "context": context,
                "before": before,
                "after": deepcopy(context),
                "references_unchanged": all(
                    actual is expected
                    for actual, expected in zip(
                        _authoritative_references(context),
                        references,
                    )
                ),
                "attempt": attempt,
                "execution": execution,
                "routing_config": kwargs["routing_config"],
            }
        )
        return attempt

    monkeypatch.setattr(SimulationEngine, "step_imaging", capture)

    report = run_v53_integrated_imaging_demo()

    assert len(records) >= 6
    assert len({id(record["context"]) for record in records}) == len(records)
    assert all(record["before"] == records[0]["before"] for record in records)
    assert {
        record["attempt"].authorization_result.status
        for record in records
    } == {
        ImagingExecutionAuthorizationStatus.AUTHORIZED,
        ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE,
        (
            ImagingExecutionAuthorizationStatus
            .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED
        ),
    }
    assert {
        record["attempt"].authorization_result.electrical_result
        .service_bounds.status
        for record in records
        if (
            record["attempt"].authorization_result.electrical_result
            .service_bounds
        )
        is not None
    } == {
        AcquisitionServiceStatus.FULLY_SERVED,
        AcquisitionServiceStatus.FULL_SERVICE_IMPOSSIBLE,
        AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED,
    }

    for record in records:
        before = record["before"]
        after = record["after"]
        attempt = record["attempt"]
        execution = record["execution"]
        assert execution.scheduled_start_seconds == (
            before.simulation_time_seconds
        )
        assert (
            execution.candidate.acquisition_input.imaging_duration_seconds
            == before.inputs.numerical_config.timestep_seconds
        )
        optical = (
            before.inputs.spacecraft_configuration.payload.optical_acquisition
        )
        assert optical.acquisition_power_w.value == 90.0
        assert optical.acquisition_power_w.provenance.classification is (
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
        )
        assert all(
            route.retained_heat_fraction.provenance.classification
            is ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
            for route in record["routing_config"].routes
        )

        if attempt.step_result is None:
            assert after == before
            assert record["references_unchanged"] is True
        else:
            assert after.simulation_time_seconds == (
                before.simulation_time_seconds + attempt.step_result.dt_seconds
            )
            assert after.diagnostics.completed_steps == (
                before.diagnostics.completed_steps + 1
            )
            assert after.mission_state == before.mission_state
            assert after.mission_state.data_product_ids == ()
            step = attempt.step_result
            authorization = attempt.authorization_result
            degradation = step.battery_degradation_result
            reconciliation = step.battery_capacity_reconciliation_result
            assert degradation is not None
            assert reconciliation is not None
            assert after.spacecraft_state.battery.energy_wh == (
                reconciliation.authoritative_end_energy_wh
            )
            assert (
                after.spacecraft_state.degradation.battery
                .usable_capacity_retention
                == degradation.end_usable_capacity_retention
            )
            assert (
                after.spacecraft_state.degradation.battery
                .cumulative_energy_throughput_wh
                == degradation.end_cumulative_energy_throughput_wh
            )
            proposal = authorization.thermal_proposal
            assert proposal is not None
            assert {
                item.node_id: item.temperature_k
                for item in after.spacecraft_state.thermal.node_states
            } == {
                item.node_id: item.end_temperature_k
                for item in (
                    proposal.eps_thermal_coupling_result.thermal_result
                    .node_transitions
                )
            }

    assert report.authorized.step_result_present is True
    authorized_records = [
        record
        for record in records
        if record["attempt"].authorization_result.status
        is ImagingExecutionAuthorizationStatus.AUTHORIZED
    ]
    assert len(authorized_records) >= 3
    assert all(
        record["attempt"] == authorized_records[0]["attempt"]
        and record["after"] == authorized_records[0]["after"]
        for record in authorized_records[1:]
    )


def test_reference_twenty_kilometre_sample_grid_arithmetic_is_exact(
    demo_report,
) -> None:
    reference = demo_report.reference_sample_grid

    assert reference.cross_track_width_m == 20_000.0
    assert reference.along_track_length_m == 20_000.0
    assert reference.footprint_area_m2 == 400_000_000.0
    assert reference.panchromatic_equivalent_samples == 400_000_000.0
    assert reference.multispectral_equivalent_samples_per_band == 25_000_000.0
    assert reference.multispectral_equivalent_samples_total == 100_000_000.0
    assert reference.total_equivalent_samples == 500_000_000.0
    assert reference.sample_grid_proxy_bits == 6_000_000_000.0
    assert reference.sample_grid_proxy_bytes == 750_000_000.0
    assert reference.sample_grid_proxy_megabits_per_square_km == 15.0
    normalized = " ".join(reference.interpretation.lower().split())
    assert "derived level-1 sample-grid proxy" in normalized
    assert "not" in normalized
    assert "file size" in normalized
    assert "stored" in normalized
    assert "downlinked" in normalized


def test_replay_repeat_and_checkpoint_schema_are_exact_and_deterministic(
    demo_report,
) -> None:
    second = run_v53_integrated_imaging_demo()

    assert second == demo_report
    assert demo_report.replay_attempt_equal is True
    assert demo_report.replay_context_equal is True
    assert demo_report.repeat_attempt_equal is True
    assert demo_report.repeat_context_equal is True
    assert demo_report.checkpoint_schema_version == (
        CURRENT_CHECKPOINT_SCHEMA_VERSION
    ) == 5


def test_demo_adds_no_component_allocation_product_or_storage_claim() -> None:
    source = DEMO_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DEMO_PATH))
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    report_fields = {
        field.name
        for contract in (
            ImagingCaseReport,
            ReferenceSampleGridReport,
            V53IntegratedImagingDemoReport,
        )
        for field in fields(contract)
    }

    assert "sample_grid_proxy_bytes" in report_fields
    assert identifiers.isdisjoint(
        {
            "ServedPowerLedger",
            "ServedComponentPower",
            "DataProductId",
            "stored_bytes",
            "file_size",
            "downlinked_bytes",
            "storage_capacity",
        }
    )
    assert report_fields.isdisjoint(
        {
            "served_power_ledger",
            "component_service",
            "stored_bytes",
            "file_size",
            "downlinked_bytes",
            "data_product_id",
            "mission_request_id",
        }
    )


def test_demo_has_no_random_wall_clock_or_variable_duration_logic() -> None:
    source = DEMO_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DEMO_PATH))
    imported_roots = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    } | {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert imported_roots.isdisjoint({"random", "time", "datetime"})
    assert calls.isdisjoint({"random", "randint", "choice", "hash", "id"})
    assert identifiers.isdisjoint(
        {
            "duty_cycle",
            "substep",
            "partial_step",
            "variable_duration",
            "event_split",
            "round",
            "isclose",
        }
    )
    assert calls.isdisjoint(
        {
            "_run_transaction",
            "_physical_integration",
            "_complete_coupled_physical_integration",
        }
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "ops_sim.v5"
        ):
            assert all(not alias.name.startswith("_") for alias in node.names)


def test_main_prints_a_concise_deterministic_scope_safe_summary(
    capsys,
) -> None:
    demo_module.main()
    first = capsys.readouterr().out
    demo_module.main()
    second = capsys.readouterr().out

    assert first == second
    normalized = " ".join(first.lower().split())
    for token in (
        "authorized",
        "sequence-infeasible",
        "full-service-impossible",
        "service-allocation-required",
        "sample-grid proxy",
        "not a calibrated",
        "not a stored",
        "mission",
    ):
        assert token in normalized


def test_no_v5_production_file_is_changed_for_the_demo() -> None:
    changed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "c74e52f",
            "bcde7c7",
            "--",
            "ops_sim/v5",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert changed == []


def test_d274_through_d279_and_f4a_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s005 = sources.partition("### S005 ")[2].partition("### S006 ")[0]
    normalized = " ".join(s005.lower().split())

    for number in range(274, 280):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D273 ") < decisions.index("## D274 ")
    expected_headings = (
        "## D274 — F4A provides one deterministic end-to-end V5.3 imaging "
        "demonstration",
        "## D275 — Authorized demo means resource-served interval commit only",
        "## D276 — Sequence and both electrical nonauthorization classes are "
        "demonstrated without commit",
        "## D277 — 20×20 km sample-grid arithmetic remains a Level-1 proxy, "
        "not file size",
        "## D278 — Demo replay requires caller-resupplied imaging inputs and "
        "schema remains 3",
        "## D279 — F4A introduces no production physics, state, controller, "
        "storage, or variable-duration behavior",
    )
    assert all(decisions.count(heading) == 1 for heading in expected_headings)

    for phrase in (
        "v5.3f4a",
        "no new physical source or value",
        "no new equation",
        "no new literature",
        "independent equivalent start contexts",
        "authorized resource-served interval commit",
        "supported sequence infeasibility",
        "full-service impossibility",
        "service-allocation-required shortfall",
        "400,000,000 pan samples",
        "25,000,000 samples per ms band",
        "100,000,000 ms samples",
        "500,000,000 total samples",
        "6,000,000,000 bits",
        "750,000,000 decimal bytes",
        "15 mbit/km²",
        "derived level-1 sample-grid proxy",
        "caller-resupplied imaging inputs",
        "checkpoint schema remains 3",
        "no production state or physics",
        "variable-duration behavior",
    ):
        assert phrase in normalized
    assert "not a measured onboard file size" in normalized
    assert "stored, downlinked, or delivered data" in normalized
