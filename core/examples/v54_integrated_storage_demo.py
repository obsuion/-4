"""Deterministic V5.4 onboard-storage integration demonstration.

All values are synthetic demonstration configuration.  This is not a
KazEOSat-1 operational schedule, recorder-capacity estimate, compression or
downlink model, flight plan, or calibration claim.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from json import dumps, loads
from math import fsum
from pathlib import Path
import sys


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.v52_integrated_eps_thermal_demo import (  # noqa: E402
    build_demo_context,
)
from ops_sim.v5.adcs import CommonFrameBoresightDirection  # noqa: E402
from ops_sim.v5.checkpoint import (  # noqa: E402
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.context import SimulationContext  # noqa: E402
from ops_sim.v5.engine import (  # noqa: E402
    ImagingStorageEngineAttempt,
    SimulationEngine,
)
from ops_sim.v5.ids import (  # noqa: E402
    ADCSBoresightFrameId,
    AcquisitionDataRecordId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
    ThermalNodeId,
)
from ops_sim.v5.imaging_execution import (  # noqa: E402
    ScheduledObservationAcquisitionExecution,
)
from ops_sim.v5.imaging_feasibility import (  # noqa: E402
    ObservationAcquisitionCandidate,
)
from ops_sim.v5.imaging_resources import (  # noqa: E402
    AcquisitionEPSIntervalEnvironment,
)
from ops_sim.v5.imaging_storage import (  # noqa: E402
    ImagingStorageAuthorizationStatus,
)
from ops_sim.v5.observation import (  # noqa: E402
    ObservationOpportunity,
    ObservationPointing,
)
from ops_sim.v5.observation_feasibility import (  # noqa: E402
    ObservationManeuverCandidate,
    ScheduledObservationExecution,
)
from ops_sim.v5.parameters import ScalarParameter  # noqa: E402
from ops_sim.v5.payload import (  # noqa: E402
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
)
from ops_sim.v5.power_loads import PowerLoadBreakdown  # noqa: E402
from ops_sim.v5.provenance import (  # noqa: E402
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.thermal import (  # noqa: E402
    ThermalIntervalInputs,
    ThermalNodeBoundaryInput,
)
from ops_sim.v5.thermal_coupling import (  # noqa: E402
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
)
from ops_sim.v5.thermal_routing import (  # noqa: E402
    ComponentHeatRoute,
    ComponentHeatRoutingConfig,
    ElectricalLoadComponent,
)


DEMO_START_SECONDS = 100
DEMO_TIMESTEP_SECONDS = 23
ACCUMULATION_STEPS = 12
CHECKPOINT_SPLIT_STEP = 6
CAPACITY_SUCCESSFUL_RECORDS = 3
EXPECTED_RECORD_EQUIVALENT_BITS = 12_000.0
_BITS_PER_DECIMAL_GIGABYTE = 8_000_000_000.0


@dataclass(frozen=True, slots=True)
class StorageAccumulationRow:
    """One successful public imaging-to-storage transaction."""

    step_index: int
    start_time_seconds: int
    end_time_seconds: int
    record_id: AcquisitionDataRecordId
    stored_record_count: int
    stored_occupancy_equivalent_bits: float
    battery_energy_wh: float
    authorization_status: ImagingStorageAuthorizationStatus
    physical_evidence_reused: bool


@dataclass(frozen=True, slots=True)
class CapacityBoundaryReport:
    """Synthetic exact-full boundary and rejected next-record evidence."""

    successful_rows: tuple[StorageAccumulationRow, ...]
    represented_capacity_equivalent_bits: float
    full_occupancy_equivalent_bits: float
    rejected_record_id: AcquisitionDataRecordId
    rejected_status: ImagingStorageAuthorizationStatus
    rejected_step_result_present: bool
    rejection_context_unchanged: bool
    rejection_authoritative_identities_unchanged: bool


@dataclass(frozen=True, slots=True)
class V54IntegratedStorageDemoReport:
    """Compact accumulation, replay, and capacity-boundary evidence."""

    direct_rows: tuple[StorageAccumulationRow, ...]
    restarted_rows: tuple[StorageAccumulationRow, ...]
    direct_restart_rows_equal: bool
    direct_restart_context_equal: bool
    restart_mutable_state_fresh: bool
    final_record_count: int
    final_occupancy_equivalent_bits: float
    checkpoint_split_step: int
    checkpoint_schema_version: int
    capacity_boundary: CapacityBoundaryReport


def _parameter(parameter_id: str, units: str, value: float) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale=(
                "Synthetic V5.4E demonstration configuration; not a real "
                "spacecraft property."
            ),
        ),
    )


def _build_demo_context(
    *,
    capacity_equivalent_bits: float | None = None,
) -> SimulationContext:
    """Build one fresh deterministic context for repeated D2 transactions."""
    context = build_demo_context()
    spacecraft_configuration = context.inputs.spacecraft_configuration
    if capacity_equivalent_bits is not None:
        storage = replace(
            spacecraft_configuration.storage,
            usable_capacity_gb=_parameter(
                "storage.usable-capacity",
                "GB",
                capacity_equivalent_bits / _BITS_PER_DECIMAL_GIGABYTE,
            ),
        )
        spacecraft_configuration = replace(
            spacecraft_configuration,
            storage=storage,
        )
    inputs = replace(
        context.inputs,
        spacecraft_configuration=spacecraft_configuration,
        numerical_config=replace(
            context.inputs.numerical_config,
            timestep_seconds=DEMO_TIMESTEP_SECONDS,
            geometry_sample_seconds=1,
            checkpoint_interval_seconds=DEMO_TIMESTEP_SECONDS,
        ),
    )
    return replace(
        context,
        simulation_time_seconds=DEMO_START_SECONDS,
        inputs=inputs,
    )


def _direction() -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId("v54e-common-frame"),
        0.0,
        0.0,
        1.0,
    )


def _previous_execution() -> ScheduledObservationExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("v54e-previous-opportunity"),
        ImagingRequestId("v54e-previous-request"),
        0,
        60,
        20,
        ObservationPointing(10.0, 0.0),
    )
    return ScheduledObservationExecution(
        ObservationManeuverCandidate(opportunity, _direction()),
        0,
    )


def _scheduled_execution(
    start_time_seconds: int,
    logical_index: int,
    series: str,
) -> ScheduledObservationAcquisitionExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId(
            f"v54e-{series}-opportunity-{logical_index:03d}"
        ),
        ImagingRequestId(f"v54e-{series}-request-{logical_index:03d}"),
        start_time_seconds,
        start_time_seconds + 2 * DEMO_TIMESTEP_SECONDS,
        DEMO_TIMESTEP_SECONDS,
        ObservationPointing(10.0, 0.0),
    )
    return ScheduledObservationAcquisitionExecution(
        ObservationAcquisitionCandidate(
            ObservationManeuverCandidate(opportunity, _direction()),
            OpticalAcquisitionInput(
                20.0,
                40.0,
                DEMO_TIMESTEP_SECONDS,
                OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
            ),
        ),
        start_time_seconds,
    )


def _environment() -> AcquisitionEPSIntervalEnvironment:
    return AcquisitionEPSIntervalEnvironment(
        False,
        0.0,
        PowerLoadBreakdown(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0),
    )


def _routing_config() -> ComponentHeatRoutingConfig:
    return ComponentHeatRoutingConfig(
        tuple(
            ComponentHeatRoute(
                component,
                ThermalNodeId(
                    "payload"
                    if component is ElectricalLoadComponent.PAYLOAD
                    else "bus"
                ),
                _parameter(
                    f"thermal.routing.{component.value}.retained-heat-fraction",
                    "1",
                    0.5,
                ),
            )
            for component in ElectricalLoadComponent
        )
    )


def _thermal_inputs(context: SimulationContext) -> ThermalIntervalInputs:
    temperature_by_id = {
        state.node_id: state.temperature_k
        for state in context.spacecraft_state.thermal.node_states
    }
    return ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(
                node.node_id,
                temperature_by_id[node.node_id],
            )
            for node in (
                context.inputs.spacecraft_configuration.thermal.network.nodes
            )
        )
    )


def _external_heat_sources(
    context: SimulationContext,
) -> ThermalHeatSourceInputs:
    return ThermalHeatSourceInputs(
        tuple(
            ThermalNodeHeatSourceInput(
                node.node_id,
                0.0,
                0.0,
                0.0,
                0.0,
            )
            for node in (
                context.inputs.spacecraft_configuration.thermal.network.nodes
            )
        )
    )


def _record_id(series: str, logical_index: int) -> AcquisitionDataRecordId:
    return AcquisitionDataRecordId(
        f"v54e-{series}-{logical_index:03d}"
    )


def _step_arguments(
    context: SimulationContext,
    logical_index: int,
    series: str,
) -> dict[str, object]:
    return {
        "context": context,
        "previous_execution": _previous_execution(),
        "execution": _scheduled_execution(
            context.simulation_time_seconds,
            logical_index,
            series,
        ),
        "record_id": _record_id(series, logical_index),
        "environment": _environment(),
        "routing_config": _routing_config(),
        "thermal_inputs": _thermal_inputs(context),
        "external_heat_sources": _external_heat_sources(context),
    }


def _execute_storage_step(
    engine: SimulationEngine,
    context: SimulationContext,
    logical_index: int,
    series: str,
) -> ImagingStorageEngineAttempt:
    """Drive exactly one logical attempt through the public D2 API."""
    return engine.step_imaging_to_storage(
        **_step_arguments(context, logical_index, series)
    )


def _occupancy_equivalent_bits(context: SimulationContext) -> float:
    """Derive display-only occupancy from persistent ordered records."""
    return fsum(
        record.stored_equivalent_bits
        for record in context.spacecraft_state.data_storage.stored_records
    )


def _mutable_references(context: SimulationContext) -> tuple[object, ...]:
    spacecraft = context.spacecraft_state
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
        context.ground_knowledge_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def _require_demonstrated(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"V5.4 integrated storage demo failed: {message}")


def _successful_row(
    logical_index: int,
    start_time_seconds: int,
    context: SimulationContext,
    attempt: ImagingStorageEngineAttempt,
) -> StorageAccumulationRow:
    authorization = attempt.authorization_result
    step = attempt.step_result
    _require_demonstrated(
        authorization.status is ImagingStorageAuthorizationStatus.AUTHORIZED,
        "successful transaction authorization",
    )
    _require_demonstrated(step is not None, "successful StepResult")
    if step is None:
        raise RuntimeError("authorized storage transaction lacks StepResult")
    f2 = authorization.imaging_authorization_result
    thermal = f2.thermal_proposal
    _require_demonstrated(thermal is not None, "authorized thermal proposal")
    if thermal is None:
        raise RuntimeError("authorized storage transaction lacks thermal evidence")
    evidence_reused = (
        step.eps_result is f2.electrical_result.eps_result
        and step.eps_capability_result
        is f2.electrical_result.eps_capability_result
        and step.thermal_coupling_result
        is thermal.eps_thermal_coupling_result
    )
    admission = authorization.storage_admission_result
    _require_demonstrated(admission is not None, "storage admission evidence")
    if admission is None:
        raise RuntimeError("authorized storage transaction lacks admission")
    stored_records = context.spacecraft_state.data_storage.stored_records
    _require_demonstrated(
        stored_records[-1] is admission.proposed_record,
        "exact proposed record identity",
    )
    return StorageAccumulationRow(
        logical_index + 1,
        start_time_seconds,
        step.end_time_seconds,
        admission.proposed_record.record_id,
        len(stored_records),
        _occupancy_equivalent_bits(context),
        context.spacecraft_state.battery.energy_wh,
        authorization.status,
        evidence_reused,
    )


def _run_accumulation(
    context: SimulationContext,
    logical_indices: range,
    *,
    series: str,
) -> tuple[StorageAccumulationRow, ...]:
    engine = SimulationEngine()
    rows = []
    mission_before = deepcopy(context.mission_state)
    controller_before = deepcopy(context.controller_state)
    onboard_before = deepcopy(context.spacecraft_state.onboard)
    knowledge_before = deepcopy(context.ground_knowledge_state)
    for logical_index in logical_indices:
        start_time_seconds = context.simulation_time_seconds
        records_before = context.spacecraft_state.data_storage.stored_records
        previous_record_identities = tuple(records_before)
        attempt = _execute_storage_step(
            engine,
            context,
            logical_index,
            series,
        )
        row = _successful_row(
            logical_index,
            start_time_seconds,
            context,
            attempt,
        )
        _require_demonstrated(
            row.stored_record_count == len(records_before) + 1,
            "one record appended per successful transaction",
        )
        _require_demonstrated(
            all(
                current is previous
                for current, previous in zip(
                    context.spacecraft_state.data_storage.stored_records,
                    previous_record_identities,
                )
            ),
            "prior record identities and order",
        )
        _require_demonstrated(
            row.end_time_seconds
            == start_time_seconds + DEMO_TIMESTEP_SECONDS,
            "one timestep clock advance",
        )
        _require_demonstrated(
            context.diagnostics.completed_steps == logical_index + 1,
            "one diagnostics increment",
        )
        _require_demonstrated(
            not rows
            or row.stored_occupancy_equivalent_bits
            > rows[-1].stored_occupancy_equivalent_bits,
            "monotonically increasing occupancy",
        )
        rows.append(row)
    _require_demonstrated(
        context.mission_state == mission_before,
        "mission state unchanged",
    )
    _require_demonstrated(
        context.controller_state == controller_before,
        "controller state unchanged",
    )
    _require_demonstrated(
        context.spacecraft_state.onboard == onboard_before,
        "onboard operations state unchanged",
    )
    _require_demonstrated(
        context.ground_knowledge_state == knowledge_before,
        "ground knowledge unchanged",
    )
    return tuple(rows)


def _checkpoint_json_restore(
    context: SimulationContext,
) -> tuple[SimulationContext, int, bool]:
    checkpoint = CheckpointState.from_context(context)
    payload = loads(
        dumps(checkpoint.to_dict(), allow_nan=False, sort_keys=True)
    )
    parsed = CheckpointState.from_dict(payload)
    restored = parsed.restore(context.inputs)
    fresh = all(
        restored_value is not source_value
        for restored_value, source_value in zip(
            _mutable_references(restored),
            _mutable_references(context),
        )
    )
    return restored, checkpoint.schema_version, fresh


def _run_capacity_boundary(
    record_equivalent_bits: float,
) -> CapacityBoundaryReport:
    intended_capacity = fsum(
        record_equivalent_bits
        for _ in range(CAPACITY_SUCCESSFUL_RECORDS)
    )
    context = _build_demo_context(
        capacity_equivalent_bits=intended_capacity
    )
    configured_gb = (
        context.inputs.spacecraft_configuration.storage.usable_capacity_gb.value
    )
    represented_capacity = float(
        configured_gb * _BITS_PER_DECIMAL_GIGABYTE
    )
    _require_demonstrated(
        represented_capacity == intended_capacity,
        "synthetic decimal-GB capacity representation",
    )
    successful_rows = _run_accumulation(
        context,
        range(CAPACITY_SUCCESSFUL_RECORDS),
        series="capacity",
    )
    full_occupancy = _occupancy_equivalent_bits(context)
    _require_demonstrated(
        full_occupancy == represented_capacity,
        "exact-full third-record boundary",
    )

    before = deepcopy(context)
    references = _mutable_references(context) + (
        context.spacecraft_state.data_storage.stored_records,
    )
    rejected_record_id = _record_id(
        "capacity",
        CAPACITY_SUCCESSFUL_RECORDS,
    )
    rejected = _execute_storage_step(
        SimulationEngine(),
        context,
        CAPACITY_SUCCESSFUL_RECORDS,
        "capacity",
    )
    context_unchanged = context == before
    identities_unchanged = all(
        current is original
        for current, original in zip(
            _mutable_references(context)
            + (context.spacecraft_state.data_storage.stored_records,),
            references,
        )
    )
    _require_demonstrated(
        rejected.authorization_result.status
        is ImagingStorageAuthorizationStatus.INSUFFICIENT_STORAGE_CAPACITY,
        "fourth complete record rejected",
    )
    _require_demonstrated(
        rejected.step_result is None,
        "rejected record has no StepResult",
    )
    _require_demonstrated(
        context_unchanged and identities_unchanged,
        "capacity rejection has no authoritative commit",
    )
    return CapacityBoundaryReport(
        successful_rows,
        represented_capacity,
        full_occupancy,
        rejected_record_id,
        rejected.authorization_result.status,
        rejected.step_result is not None,
        context_unchanged,
        identities_unchanged,
    )


def run_v54_integrated_storage_demo() -> V54IntegratedStorageDemoReport:
    """Run accumulation, schema-4 replay, and exact-capacity evidence."""
    direct_context = _build_demo_context()
    direct_rows = _run_accumulation(
        direct_context,
        range(ACCUMULATION_STEPS),
        series="accumulation",
    )
    _require_demonstrated(
        len(direct_rows) == ACCUMULATION_STEPS,
        "twelve successful direct intervals",
    )
    record_equivalent_bits = (
        direct_rows[0].stored_occupancy_equivalent_bits
    )
    _require_demonstrated(
        record_equivalent_bits == EXPECTED_RECORD_EQUIVALENT_BITS,
        "actual D2 geometry produces 12,000 equivalent bits",
    )

    split_context = _build_demo_context()
    restarted_prefix = _run_accumulation(
        split_context,
        range(CHECKPOINT_SPLIT_STEP),
        series="accumulation",
    )
    restarted_context, schema_version, restart_fresh = (
        _checkpoint_json_restore(split_context)
    )
    restarted_suffix = _run_accumulation(
        restarted_context,
        range(CHECKPOINT_SPLIT_STEP, ACCUMULATION_STEPS),
        series="accumulation",
    )
    restarted_rows = restarted_prefix + restarted_suffix
    rows_equal = direct_rows == restarted_rows
    contexts_equal = direct_context == restarted_context
    _require_demonstrated(rows_equal, "direct and restarted row equality")
    _require_demonstrated(
        contexts_equal,
        "direct and restarted final context equality",
    )
    _require_demonstrated(
        schema_version == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5,
        "live checkpoint schema is 5",
    )
    _require_demonstrated(restart_fresh, "fresh mutable restart graph")

    stored_records = direct_context.spacecraft_state.data_storage.stored_records
    expected_record_ids = tuple(
        _record_id("accumulation", index)
        for index in range(ACCUMULATION_STEPS)
    )
    _require_demonstrated(
        tuple(record.record_id for record in stored_records)
        == expected_record_ids,
        "record IDs retain attempt order",
    )
    capacity_boundary = _run_capacity_boundary(record_equivalent_bits)
    return V54IntegratedStorageDemoReport(
        direct_rows,
        restarted_rows,
        rows_equal,
        contexts_equal,
        restart_fresh,
        len(stored_records),
        _occupancy_equivalent_bits(direct_context),
        CHECKPOINT_SPLIT_STEP,
        schema_version,
        capacity_boundary,
    )


def main() -> None:
    """Print a concise deterministic V5.4E integration report."""
    report = run_v54_integrated_storage_demo()
    print("V5.4 integrated storage demo")
    print(
        "Synthetic integration evidence only; not recorder calibration, "
        "compression, downlink, or an operational flight plan."
    )
    print("accumulation:")
    for row in report.direct_rows:
        print(
            f"step={row.step_index} start_s={row.start_time_seconds} "
            f"end_s={row.end_time_seconds} record={row.record_id.value} "
            f"count={row.stored_record_count} "
            "occupancy_equivalent_bits="
            f"{row.stored_occupancy_equivalent_bits} "
            f"battery_Wh={row.battery_energy_wh} "
            f"status={row.authorization_status.value}"
        )
    print("checkpoint replay:")
    print(
        f"split_step={report.checkpoint_split_step} "
        f"schema={report.checkpoint_schema_version} "
        "direct_equals_restart="
        f"{report.direct_restart_context_equal and report.direct_restart_rows_equal} "
        f"fresh_mutable_state={report.restart_mutable_state_fresh}"
    )
    capacity = report.capacity_boundary
    print("capacity boundary:")
    print(
        f"successful_records={len(capacity.successful_rows)} "
        "represented_capacity_equivalent_bits="
        f"{capacity.represented_capacity_equivalent_bits} "
        "occupancy_equivalent_bits="
        f"{capacity.full_occupancy_equivalent_bits} "
        f"next_status={capacity.rejected_status.value} "
        f"context_unchanged={capacity.rejection_context_unchanged}"
    )


__all__ = [
    "CapacityBoundaryReport",
    "StorageAccumulationRow",
    "V54IntegratedStorageDemoReport",
    "run_v54_integrated_storage_demo",
]


if __name__ == "__main__":
    main()
