"""Deterministic V5.5 multi-contact downlink integration demonstration.

All contacts, records, and configuration changes in this module are synthetic
demonstration inputs.  This is integration evidence only, not a KazEOSat
operational replay, calibrated throughput claim, or completion model.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from json import dumps, loads
from math import fsum, isfinite
from pathlib import Path
import sys


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.v52_integrated_eps_thermal_demo import (  # noqa: E402
    build_demo_context,
)
from ops_sim.v5.checkpoint import (  # noqa: E402
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.communications import (  # noqa: E402
    ServiceableGroundContact,
)
from ops_sim.v5.context import SimulationContext  # noqa: E402
from ops_sim.v5.data_delivery import (  # noqa: E402
    DownlinkTransferProgress,
    GroundDataDeliveryState,
)
from ops_sim.v5.downlink import DownlinkTransmissionStatus  # noqa: E402
from ops_sim.v5.engine import (  # noqa: E402
    DownlinkEngineStepResult,
    SimulationEngine,
)
from ops_sim.v5.ids import (  # noqa: E402
    AcquisitionDataRecordId,
    GroundContactId,
    GroundStationId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
)
from ops_sim.v5.onboard_data import (  # noqa: E402
    OnboardAcquisitionDataRecord,
)
from ops_sim.v5.parameters import ScalarParameter  # noqa: E402
from ops_sim.v5.payload import (  # noqa: E402
    OpticalAcquisitionChannelSelection,
)
from ops_sim.v5.provenance import (  # noqa: E402
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import DataStorageState  # noqa: E402


DEMO_START_SECONDS = 100
DEMO_TIMESTEP_SECONDS = 23
DEMO_CONTACT_CAPACITY_BITS = 5_000.0
CHECKPOINT_SPLIT_INDEX = 1
PHYSICAL_LIMITATION = (
    "Communications power and concurrent physical evolution are not modeled "
    "during V5.5 downlink bookkeeping."
)
_RECORD_A_ID = AcquisitionDataRecordId("v55e-record-a")
_RECORD_B_ID = AcquisitionDataRecordId("v55e-record-b")
_GROUND_STATION_ID = GroundStationId("v55e-synthetic-station")


def _require_exact_type(name: str, value: object, expected: type[object]) -> None:
    if type(value) is not expected:
        raise TypeError(f"{name} must be a {expected.__name__}")


def _require_finite_nonnegative(name: str, value: object) -> float:
    if type(value) is not float:
        raise TypeError(f"{name} must be a built-in float")
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value < 0.0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return value


@dataclass(frozen=True, slots=True)
class DownlinkServiceRow:
    """Inspectable evidence for one committed caller-selected service step."""

    attempt_index: int
    contact_id: GroundContactId
    contact_start_seconds: int
    contact_end_seconds: int
    selected_record_id: AcquisitionDataRecordId
    status: DownlinkTransmissionStatus
    nominal_contact_capacity_bits: float
    transmitted_equivalent_bits_this_service: float
    progress_before_equivalent_bits: float
    progress_after_equivalent_bits: float
    remaining_before_equivalent_bits: float
    remaining_after_equivalent_bits: float
    unused_contact_capacity_bits: float
    utilization_ratio: float
    storage_freed_equivalent_bits: float
    onboard_occupancy_after_equivalent_bits: float
    onboard_record_ids_after: tuple[AcquisitionDataRecordId, ...]
    partial_progress_after: tuple[DownlinkTransferProgress, ...]
    completed_record_ids_after: tuple[AcquisitionDataRecordId, ...]
    simulation_time_after_seconds: int
    physical_evidence_fields_all_none: bool

    def __post_init__(self) -> None:
        if type(self.attempt_index) is not int:
            raise TypeError("attempt_index must be a built-in int")
        if self.attempt_index <= 0:
            raise ValueError("attempt_index must be strictly positive")
        _require_exact_type("contact_id", self.contact_id, GroundContactId)
        GroundContactId(self.contact_id.value)
        _require_exact_type(
            "selected_record_id",
            self.selected_record_id,
            AcquisitionDataRecordId,
        )
        AcquisitionDataRecordId(self.selected_record_id.value)
        _require_exact_type("status", self.status, DownlinkTransmissionStatus)
        for name in (
            "contact_start_seconds",
            "contact_end_seconds",
            "simulation_time_after_seconds",
        ):
            if type(getattr(self, name)) is not int:
                raise TypeError(f"{name} must be a built-in int")
        if self.contact_start_seconds < 0:
            raise ValueError("contact_start_seconds must be nonnegative")
        if self.contact_end_seconds <= self.contact_start_seconds:
            raise ValueError("contact end must be after contact start")
        if self.simulation_time_after_seconds != self.contact_end_seconds:
            raise ValueError("simulation time after must equal contact end")

        numeric_names = (
            "nominal_contact_capacity_bits",
            "transmitted_equivalent_bits_this_service",
            "progress_before_equivalent_bits",
            "progress_after_equivalent_bits",
            "remaining_before_equivalent_bits",
            "remaining_after_equivalent_bits",
            "unused_contact_capacity_bits",
            "utilization_ratio",
            "storage_freed_equivalent_bits",
            "onboard_occupancy_after_equivalent_bits",
        )
        for name in numeric_names:
            _require_finite_nonnegative(name, getattr(self, name))
        if self.nominal_contact_capacity_bits <= 0.0:
            raise ValueError("nominal contact capacity must be positive")
        if self.transmitted_equivalent_bits_this_service <= 0.0:
            raise ValueError("service must be positive")
        if not 0.0 < self.utilization_ratio <= 1.0:
            raise ValueError("utilization_ratio must satisfy 0 < value <= 1")

        if type(self.onboard_record_ids_after) is not tuple:
            raise TypeError("onboard_record_ids_after must be a tuple")
        if type(self.partial_progress_after) is not tuple:
            raise TypeError("partial_progress_after must be a tuple")
        if type(self.completed_record_ids_after) is not tuple:
            raise TypeError("completed_record_ids_after must be a tuple")
        id_tuples = (
            ("onboard_record_ids_after", self.onboard_record_ids_after),
            ("completed_record_ids_after", self.completed_record_ids_after),
        )
        for name, values in id_tuples:
            if not all(type(value) is AcquisitionDataRecordId for value in values):
                raise TypeError(f"{name} must contain acquisition record IDs")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must contain unique IDs")
        if not all(
            type(progress) is DownlinkTransferProgress
            for progress in self.partial_progress_after
        ):
            raise TypeError(
                "partial_progress_after must contain transfer progress values"
            )
        for progress in self.partial_progress_after:
            DownlinkTransferProgress(
                progress.record_id,
                progress.transmitted_equivalent_bits,
            )
        if self.status is DownlinkTransmissionStatus.PARTIAL:
            if self.storage_freed_equivalent_bits != 0.0:
                raise ValueError("PARTIAL service must not free storage")
        elif self.remaining_after_equivalent_bits != 0.0:
            raise ValueError("COMPLETE service must leave zero remaining bits")
        if type(self.physical_evidence_fields_all_none) is not bool:
            raise TypeError("physical_evidence_fields_all_none must be a bool")


@dataclass(frozen=True, slots=True)
class V55IntegratedDownlinkDemoReport:
    """Compact direct, restart, repeat, and storage-release evidence."""

    direct_rows: tuple[DownlinkServiceRow, ...]
    restarted_rows: tuple[DownlinkServiceRow, ...]
    repeat_rows: tuple[DownlinkServiceRow, ...]
    direct_restart_rows_equal: bool
    direct_restart_final_context_equal: bool
    repeat_rows_equal: bool
    direct_repeat_final_context_equal: bool
    restart_mutable_state_fresh: bool
    checkpoint_split_index: int
    checkpoint_schema_version: int
    initial_onboard_occupancy_equivalent_bits: float
    occupancy_after_a_partial_service_equivalent_bits: float
    occupancy_after_a_completion_equivalent_bits: float
    final_onboard_occupancy_equivalent_bits: float
    final_completed_record_ids: tuple[AcquisitionDataRecordId, ...]
    final_partial_transfer_count: int
    initial_completed_steps: int
    final_completed_steps: int
    final_simulation_time_seconds: int
    physical_domains_unchanged: bool

    def __post_init__(self) -> None:
        for name in ("direct_rows", "restarted_rows", "repeat_rows"):
            rows = getattr(self, name)
            if type(rows) is not tuple:
                raise TypeError(f"{name} must be a tuple")
            if not all(type(row) is DownlinkServiceRow for row in rows):
                raise TypeError(f"{name} must contain DownlinkServiceRow values")
        if len(self.direct_rows) != 4:
            raise ValueError("direct_rows must contain four service intervals")
        if len(self.restarted_rows) != len(self.direct_rows):
            raise ValueError("restarted_rows length must match direct_rows")
        if len(self.repeat_rows) != len(self.direct_rows):
            raise ValueError("repeat_rows length must match direct_rows")

        bool_names = (
            "direct_restart_rows_equal",
            "direct_restart_final_context_equal",
            "repeat_rows_equal",
            "direct_repeat_final_context_equal",
            "restart_mutable_state_fresh",
            "physical_domains_unchanged",
        )
        for name in bool_names:
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a bool")
        if self.direct_restart_rows_equal != (
            self.direct_rows == self.restarted_rows
        ):
            raise ValueError("direct/restart row-equality flag is inconsistent")
        if self.repeat_rows_equal != (self.direct_rows == self.repeat_rows):
            raise ValueError("repeat row-equality flag is inconsistent")
        for name in (
            "direct_restart_final_context_equal",
            "direct_repeat_final_context_equal",
            "restart_mutable_state_fresh",
            "physical_domains_unchanged",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must be demonstrated")

        for name in (
            "checkpoint_split_index",
            "checkpoint_schema_version",
            "final_partial_transfer_count",
            "initial_completed_steps",
            "final_completed_steps",
            "final_simulation_time_seconds",
        ):
            if type(getattr(self, name)) is not int:
                raise TypeError(f"{name} must be a built-in int")
        if self.checkpoint_split_index != CHECKPOINT_SPLIT_INDEX:
            raise ValueError("checkpoint split must follow the first contact")
        if self.checkpoint_schema_version != CURRENT_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("checkpoint schema must equal the live schema")
        if self.final_completed_steps - self.initial_completed_steps != 4:
            raise ValueError("diagnostics must advance exactly four steps")
        if self.final_simulation_time_seconds != self.direct_rows[-1].simulation_time_after_seconds:
            raise ValueError("final simulation time must equal the last row time")

        occupancy_names = (
            "initial_onboard_occupancy_equivalent_bits",
            "occupancy_after_a_partial_service_equivalent_bits",
            "occupancy_after_a_completion_equivalent_bits",
            "final_onboard_occupancy_equivalent_bits",
        )
        for name in occupancy_names:
            _require_finite_nonnegative(name, getattr(self, name))
        if self.occupancy_after_a_partial_service_equivalent_bits != (
            self.direct_rows[0].onboard_occupancy_after_equivalent_bits
        ):
            raise ValueError("partial-service occupancy is inconsistent")
        if self.occupancy_after_a_completion_equivalent_bits != (
            self.direct_rows[2].onboard_occupancy_after_equivalent_bits
        ):
            raise ValueError("A-completion occupancy is inconsistent")
        if self.final_onboard_occupancy_equivalent_bits != (
            self.direct_rows[-1].onboard_occupancy_after_equivalent_bits
        ):
            raise ValueError("final occupancy is inconsistent")

        if type(self.final_completed_record_ids) is not tuple:
            raise TypeError("final_completed_record_ids must be a tuple")
        if not all(
            type(record_id) is AcquisitionDataRecordId
            for record_id in self.final_completed_record_ids
        ):
            raise TypeError(
                "final_completed_record_ids must contain acquisition record IDs"
            )
        if self.final_completed_record_ids != (
            self.direct_rows[-1].completed_record_ids_after
        ):
            raise ValueError("final completed record order is inconsistent")
        if self.final_partial_transfer_count != len(
            self.direct_rows[-1].partial_progress_after
        ):
            raise ValueError("final partial-transfer count is inconsistent")


def _parameter(value: float) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId("communications.nominal-downlink-data-rate"),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            "bit/s",
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale=(
                "Synthetic V5.5E rate derived from 5,000 bits per 23-second "
                "demonstration interval; not a spacecraft performance claim."
            ),
        ),
    )


def _record(
    record_id: AcquisitionDataRecordId,
    *,
    stored_equivalent_bits: float,
    scheduled_start_seconds: int,
) -> OnboardAcquisitionDataRecord:
    return OnboardAcquisitionDataRecord(
        record_id,
        ImagingRequestId(f"{record_id.value}-request"),
        ObservationOpportunityId(f"{record_id.value}-opportunity"),
        scheduled_start_seconds,
        10,
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        stored_equivalent_bits,
        stored_equivalent_bits,
    )


def _initial_records() -> tuple[OnboardAcquisitionDataRecord, ...]:
    return (
        _record(
            AcquisitionDataRecordId(_RECORD_A_ID.value),
            stored_equivalent_bits=12_000.0,
            scheduled_start_seconds=10,
        ),
        _record(
            AcquisitionDataRecordId(_RECORD_B_ID.value),
            stored_equivalent_bits=4_000.0,
            scheduled_start_seconds=30,
        ),
    )


def _build_demo_context() -> SimulationContext:
    """Build one fresh synthetic context using normal public configuration."""
    context = build_demo_context()
    spacecraft_configuration = context.inputs.spacecraft_configuration
    communications = replace(
        spacecraft_configuration.communications,
        nominal_downlink_data_rate_bps=_parameter(
            DEMO_CONTACT_CAPACITY_BITS / DEMO_TIMESTEP_SECONDS
        ),
    )
    inputs = replace(
        context.inputs,
        spacecraft_configuration=replace(
            spacecraft_configuration,
            communications=communications,
        ),
        numerical_config=replace(
            context.inputs.numerical_config,
            timestep_seconds=DEMO_TIMESTEP_SECONDS,
            geometry_sample_seconds=1,
            checkpoint_interval_seconds=DEMO_TIMESTEP_SECONDS,
        ),
    )
    spacecraft_state = replace(
        context.spacecraft_state,
        data_storage=DataStorageState(_initial_records()),
    )
    return replace(
        context,
        simulation_time_seconds=DEMO_START_SECONDS,
        inputs=inputs,
        spacecraft_state=spacecraft_state,
        ground_data_delivery_state=GroundDataDeliveryState((), ()),
    )


def _contacts() -> tuple[ServiceableGroundContact, ...]:
    return tuple(
        ServiceableGroundContact(
            GroundContactId(f"v55e-contact-{index + 1}"),
            GroundStationId(_GROUND_STATION_ID.value),
            DEMO_START_SECONDS + index * DEMO_TIMESTEP_SECONDS,
            DEMO_START_SECONDS + (index + 1) * DEMO_TIMESTEP_SECONDS,
        )
        for index in range(4)
    )


def _selected_record_ids() -> tuple[AcquisitionDataRecordId, ...]:
    return (
        AcquisitionDataRecordId(_RECORD_A_ID.value),
        AcquisitionDataRecordId(_RECORD_A_ID.value),
        AcquisitionDataRecordId(_RECORD_A_ID.value),
        AcquisitionDataRecordId(_RECORD_B_ID.value),
    )


def _occupancy_equivalent_bits(context: SimulationContext) -> float:
    """Derive display-only occupancy from the complete ordered record sequence."""
    return fsum(
        record.stored_equivalent_bits
        for record in context.spacecraft_state.data_storage.stored_records
    )


def _unchanging_domain_values(context: SimulationContext) -> tuple[object, ...]:
    spacecraft = context.spacecraft_state
    return (
        spacecraft.battery,
        spacecraft.propulsion,
        spacecraft.thermal,
        spacecraft.degradation,
        spacecraft.onboard,
        context.ground_knowledge_state,
        context.mission_state,
        context.controller_state,
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
        context.ground_data_delivery_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def _require_demonstrated(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"V5.5 integrated downlink demo failed: {message}")


def _service_row(
    attempt_index: int,
    context: SimulationContext,
    contact: ServiceableGroundContact,
    selected_record_id: AcquisitionDataRecordId,
    result: DownlinkEngineStepResult,
) -> DownlinkServiceRow:
    transmission = result.transmission_result
    step = result.step_result
    physical_fields = (
        step.eps_result,
        step.thermal_coupling_result,
        step.battery_degradation_result,
        step.solar_degradation_result,
        step.eps_capability_result,
        step.battery_capacity_reconciliation_result,
    )
    physical_none = physical_fields == (None,) * 6
    _require_demonstrated(physical_none, "downlink physical evidence is absent")
    _require_demonstrated(
        transmission.capacity_proposal.contact is contact,
        "caller-supplied contact identity",
    )
    _require_demonstrated(
        transmission.record.record_id == selected_record_id,
        "caller-selected record service",
    )
    delivery = context.ground_data_delivery_state
    stored_records = context.spacecraft_state.data_storage.stored_records
    return DownlinkServiceRow(
        attempt_index,
        contact.contact_id,
        contact.start_time_seconds,
        contact.end_time_seconds,
        selected_record_id,
        transmission.status,
        transmission.capacity_proposal.nominal_contact_capacity_bits,
        transmission.transmitted_equivalent_bits_this_service,
        transmission.progress_before_equivalent_bits,
        transmission.progress_after_equivalent_bits,
        transmission.remaining_before_equivalent_bits,
        transmission.remaining_after_equivalent_bits,
        transmission.unused_contact_capacity_bits,
        transmission.utilization_ratio,
        transmission.storage_freed_equivalent_bits,
        _occupancy_equivalent_bits(context),
        tuple(record.record_id for record in stored_records),
        delivery.partial_transfers,
        tuple(
            completed.record.record_id
            for completed in delivery.completed_deliveries
        ),
        context.simulation_time_seconds,
        physical_none,
    )


def _run_contacts(
    context: SimulationContext,
    indices: range,
    *,
    initial_completed_steps: int,
    unchanged_values: tuple[object, ...],
) -> tuple[DownlinkServiceRow, ...]:
    engine = SimulationEngine()
    contacts = _contacts()
    selected_ids = _selected_record_ids()
    rows = []
    for index in indices:
        contact = contacts[index]
        selected_id = selected_ids[index]
        _require_demonstrated(
            context.simulation_time_seconds == contact.start_time_seconds,
            "contact alignment",
        )
        result = engine.step_downlink(
            context,
            contact,
            record_id=selected_id,
        )
        _require_demonstrated(
            type(result) is DownlinkEngineStepResult,
            "public downlink result type",
        )
        row = _service_row(
            index + 1,
            context,
            contact,
            selected_id,
            result,
        )
        _require_demonstrated(
            context.diagnostics.completed_steps
            == initial_completed_steps + index + 1,
            "one diagnostics increment per contact",
        )
        _require_demonstrated(
            _unchanging_domain_values(context) == unchanged_values,
            "physical, onboard, knowledge, mission, and controller values",
        )
        rows.append(row)
    return tuple(rows)


def _checkpoint_json_restore(
    context: SimulationContext,
) -> tuple[SimulationContext, int, bool]:
    source_references = _mutable_references(context)
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
            source_references,
        )
    )
    return restored, parsed.schema_version, fresh


def _run_direct_scenario() -> tuple[
    tuple[DownlinkServiceRow, ...],
    SimulationContext,
]:
    context = _build_demo_context()
    initial_completed_steps = context.diagnostics.completed_steps
    unchanged_values = deepcopy(_unchanging_domain_values(context))
    rows = _run_contacts(
        context,
        range(4),
        initial_completed_steps=initial_completed_steps,
        unchanged_values=unchanged_values,
    )
    return rows, context


def run_v55_integrated_downlink_demo() -> V55IntegratedDownlinkDemoReport:
    """Run direct, schema-5 restart, repeat, and storage-release evidence."""
    direct_initial = _build_demo_context()
    initial_occupancy = _occupancy_equivalent_bits(direct_initial)
    initial_completed_steps = direct_initial.diagnostics.completed_steps
    unchanged_values = deepcopy(_unchanging_domain_values(direct_initial))
    direct_rows = _run_contacts(
        direct_initial,
        range(4),
        initial_completed_steps=initial_completed_steps,
        unchanged_values=unchanged_values,
    )
    direct_context = direct_initial

    restart_source = _build_demo_context()
    restart_unchanged_values = deepcopy(
        _unchanging_domain_values(restart_source)
    )
    restarted_prefix = _run_contacts(
        restart_source,
        range(CHECKPOINT_SPLIT_INDEX),
        initial_completed_steps=initial_completed_steps,
        unchanged_values=restart_unchanged_values,
    )
    restarted_context, schema_version, restart_fresh = (
        _checkpoint_json_restore(restart_source)
    )
    _require_demonstrated(
        _unchanging_domain_values(restarted_context)
        == restart_unchanged_values,
        "restart preserves non-delivery values",
    )
    restarted_suffix = _run_contacts(
        restarted_context,
        range(CHECKPOINT_SPLIT_INDEX, 4),
        initial_completed_steps=initial_completed_steps,
        unchanged_values=restart_unchanged_values,
    )
    restarted_rows = restarted_prefix + restarted_suffix

    repeat_rows, repeat_context = _run_direct_scenario()
    rows_equal = direct_rows == restarted_rows
    contexts_equal = direct_context == restarted_context
    repeat_rows_equal = direct_rows == repeat_rows
    repeat_context_equal = direct_context == repeat_context
    _require_demonstrated(rows_equal, "direct/restart row equality")
    _require_demonstrated(contexts_equal, "direct/restart context equality")
    _require_demonstrated(repeat_rows_equal, "fresh direct repeat row equality")
    _require_demonstrated(
        repeat_context_equal,
        "fresh direct repeat context equality",
    )
    _require_demonstrated(restart_fresh, "fresh mutable restart graph")
    _require_demonstrated(
        schema_version == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5,
        "live checkpoint schema is 5",
    )

    expected_statuses = (
        DownlinkTransmissionStatus.PARTIAL,
        DownlinkTransmissionStatus.PARTIAL,
        DownlinkTransmissionStatus.COMPLETE,
        DownlinkTransmissionStatus.COMPLETE,
    )
    _require_demonstrated(
        tuple(row.status for row in direct_rows) == expected_statuses,
        "PARTIAL/PARTIAL/COMPLETE/COMPLETE sequence",
    )
    _require_demonstrated(
        tuple(row.onboard_occupancy_after_equivalent_bits for row in direct_rows)
        == (16_000.0, 16_000.0, 4_000.0, 0.0),
        "whole-record storage release",
    )
    _require_demonstrated(
        direct_rows[2].unused_contact_capacity_bits == 3_000.0
        and direct_rows[2].onboard_record_ids_after == (_RECORD_B_ID,)
        and direct_rows[2].partial_progress_after == (),
        "contact-3 unused capacity is not reassigned to B",
    )
    final_delivery = direct_context.ground_data_delivery_state
    final_completed_ids = tuple(
        completed.record.record_id
        for completed in final_delivery.completed_deliveries
    )
    physical_unchanged = (
        all(row.physical_evidence_fields_all_none for row in direct_rows)
        and _unchanging_domain_values(direct_context) == unchanged_values
    )
    return V55IntegratedDownlinkDemoReport(
        direct_rows,
        restarted_rows,
        repeat_rows,
        rows_equal,
        contexts_equal,
        repeat_rows_equal,
        repeat_context_equal,
        restart_fresh,
        CHECKPOINT_SPLIT_INDEX,
        schema_version,
        initial_occupancy,
        direct_rows[0].onboard_occupancy_after_equivalent_bits,
        direct_rows[2].onboard_occupancy_after_equivalent_bits,
        _occupancy_equivalent_bits(direct_context),
        final_completed_ids,
        len(final_delivery.partial_transfers),
        initial_completed_steps,
        direct_context.diagnostics.completed_steps,
        direct_context.simulation_time_seconds,
        physical_unchanged,
    )


def main() -> None:
    """Print concise deterministic V5.5E integration evidence."""
    report = run_v55_integrated_downlink_demo()
    statuses = "/".join(row.status.value.upper() for row in report.direct_rows)
    services = ",".join(
        str(row.transmitted_equivalent_bits_this_service)
        for row in report.direct_rows
    )
    unused = ",".join(
        str(row.unused_contact_capacity_bits) for row in report.direct_rows
    )
    completed = ",".join(
        record_id.value for record_id in report.final_completed_record_ids
    )
    print("V5.5 integrated multi-contact downlink demo")
    print(
        "Synthetic integration evidence only; not a real delivered-throughput, "
        "operational replay, or completion claim."
    )
    print(f"intervals=4 statuses={statuses} service_bits={services}")
    print(
        f"checkpoint_split_after={report.checkpoint_split_index} "
        f"schema={report.checkpoint_schema_version} "
        "direct_restart_equal="
        f"{report.direct_restart_rows_equal and report.direct_restart_final_context_equal} "
        f"repeat_equal={report.repeat_rows_equal}"
    )
    print(
        "whole-record storage occupancy_bits="
        f"{report.initial_onboard_occupancy_equivalent_bits}->"
        f"{report.occupancy_after_a_partial_service_equivalent_bits}->"
        f"{report.occupancy_after_a_completion_equivalent_bits}->"
        f"{report.final_onboard_occupancy_equivalent_bits}"
    )
    print(
        f"unused_capacity_bits={unused}; unused capacity was not automatically "
        "reassigned to another record"
    )
    print(
        f"completed_order={completed} "
        f"partial_transfers={report.final_partial_transfer_count} "
        f"final_time_s={report.final_simulation_time_seconds}"
    )
    print(PHYSICAL_LIMITATION)


__all__ = [
    "DownlinkServiceRow",
    "V55IntegratedDownlinkDemoReport",
    "run_v55_integrated_downlink_demo",
]


if __name__ == "__main__":
    main()
