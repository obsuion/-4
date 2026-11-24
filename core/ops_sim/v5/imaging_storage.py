"""Pure imaging-authorization and whole-record storage composition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .context import SimulationContext
from .ids import AcquisitionDataRecordId
from .imaging_authorization import (
    ImagingExecutionAuthorizationResult,
    evaluate_imaging_engine_step_authorization,
)
from .imaging_execution import (
    ImagingExecutionAuthorizationStatus,
    ScheduledObservationAcquisitionExecution,
)
from .imaging_resources import AcquisitionEPSIntervalEnvironment
from .observation_feasibility import ScheduledObservationExecution
from .onboard_data import (
    OnboardAcquisitionDataRecord,
    OnboardAcquisitionDataVolumeProposal,
    compute_onboard_acquisition_data_volume_proposal,
)
from .storage import (
    StorageAdmissionResult,
    StorageAdmissionStatus,
    evaluate_storage_admission,
)
from .thermal import ThermalIntervalInputs
from .thermal_coupling import ThermalHeatSourceInputs
from .thermal_routing import ComponentHeatRoutingConfig


class ImagingStorageAuthorizationStatus(str, Enum):
    """Pure imaging-to-storage authorization classifications."""

    AUTHORIZED = "authorized"
    IMAGING_NOT_AUTHORIZED = "imaging-not-authorized"
    INSUFFICIENT_STORAGE_CAPACITY = "insufficient-storage-capacity"


def _revalidate_imaging_authorization_result(
    result: ImagingExecutionAuthorizationResult,
) -> None:
    ImagingExecutionAuthorizationResult(
        result.execution,
        result.electrical_result,
        result.thermal_proposal,
        result.status,
    )


def _revalidate_data_volume_proposal(
    proposal: OnboardAcquisitionDataVolumeProposal,
) -> None:
    OnboardAcquisitionDataVolumeProposal(
        proposal.acquisition_result,
        proposal.uncompressed_equivalent_bits,
        proposal.stored_equivalent_bits,
    )


def _revalidate_storage_admission_result(
    result: StorageAdmissionResult,
) -> None:
    StorageAdmissionResult(
        result.proposed_record,
        result.configured_usable_capacity_bits,
        result.stored_equivalent_bits_before,
        result.available_capacity_bits_before,
        result.stored_equivalent_bits_after_if_admitted,
        result.status,
    )


@dataclass(frozen=True, slots=True)
class ImagingStorageAuthorizationResult:
    """Pure F2, acquisition-volume, and storage-admission evidence."""

    imaging_authorization_result: ImagingExecutionAuthorizationResult
    data_volume_proposal: OnboardAcquisitionDataVolumeProposal | None
    storage_admission_result: StorageAdmissionResult | None
    status: ImagingStorageAuthorizationStatus

    def __post_init__(self) -> None:
        if type(self.imaging_authorization_result) is not (
            ImagingExecutionAuthorizationResult
        ):
            raise TypeError(
                "imaging_authorization_result must be an "
                "ImagingExecutionAuthorizationResult"
            )
        _revalidate_imaging_authorization_result(
            self.imaging_authorization_result
        )
        if self.data_volume_proposal is not None and type(
            self.data_volume_proposal
        ) is not OnboardAcquisitionDataVolumeProposal:
            raise TypeError(
                "data_volume_proposal must be an "
                "OnboardAcquisitionDataVolumeProposal or None"
            )
        if self.data_volume_proposal is not None:
            _revalidate_data_volume_proposal(self.data_volume_proposal)
        if self.storage_admission_result is not None and type(
            self.storage_admission_result
        ) is not StorageAdmissionResult:
            raise TypeError(
                "storage_admission_result must be a StorageAdmissionResult "
                "or None"
            )
        if self.storage_admission_result is not None:
            _revalidate_storage_admission_result(
                self.storage_admission_result
            )
        if type(self.status) is not ImagingStorageAuthorizationStatus:
            raise TypeError(
                "status must be an ImagingStorageAuthorizationStatus"
            )

        imaging_authorized = self.imaging_authorization_result.status is (
            ImagingExecutionAuthorizationStatus.AUTHORIZED
        )
        if self.status is (
            ImagingStorageAuthorizationStatus.IMAGING_NOT_AUTHORIZED
        ):
            if imaging_authorized:
                raise ValueError(
                    "IMAGING_NOT_AUTHORIZED requires F2 nonauthorization"
                )
            if self.data_volume_proposal is not None:
                raise ValueError(
                    "IMAGING_NOT_AUTHORIZED requires data_volume_proposal "
                    "to be None"
                )
            if self.storage_admission_result is not None:
                raise ValueError(
                    "IMAGING_NOT_AUTHORIZED requires "
                    "storage_admission_result to be None"
                )
            return

        if not imaging_authorized:
            raise ValueError(
                "storage authorization statuses require F2 authorization"
            )
        if self.data_volume_proposal is None:
            raise ValueError(
                "storage authorization statuses require a "
                "data_volume_proposal"
            )
        if self.storage_admission_result is None:
            raise ValueError(
                "storage authorization statuses require a "
                "storage_admission_result"
            )

        acquisition_result = (
            self.imaging_authorization_result.electrical_result
            .acquisition_evaluation.acquisition_result
        )
        if self.data_volume_proposal.acquisition_result is not acquisition_result:
            raise ValueError(
                "data_volume_proposal must retain the exact F2 acquisition "
                "result"
            )
        execution = self.imaging_authorization_result.execution
        acquisition_input = execution.candidate.acquisition_input
        opportunity = execution.candidate.maneuver_candidate.opportunity
        record = self.storage_admission_result.proposed_record
        if record.imaging_request_id is not opportunity.request_id:
            raise ValueError(
                "proposed record must retain the exact imaging request lineage"
            )
        if record.observation_opportunity_id is not opportunity.opportunity_id:
            raise ValueError(
                "proposed record must retain the exact observation opportunity "
                "lineage"
            )
        if record.scheduled_start_seconds != execution.scheduled_start_seconds:
            raise ValueError(
                "proposed record scheduled start must equal execution start"
            )
        if record.acquisition_duration_seconds != (
            acquisition_input.imaging_duration_seconds
        ):
            raise ValueError(
                "proposed record duration must equal acquisition duration"
            )
        if record.channel_selection is not acquisition_input.channel_selection:
            raise ValueError(
                "proposed record channel must equal acquisition channel"
            )
        if record.uncompressed_equivalent_bits != (
            self.data_volume_proposal.uncompressed_equivalent_bits
        ):
            raise ValueError(
                "proposed record uncompressed bits must equal the data-volume "
                "proposal"
            )
        if record.stored_equivalent_bits != (
            self.data_volume_proposal.stored_equivalent_bits
        ):
            raise ValueError(
                "proposed record stored bits must equal the data-volume proposal"
            )

        expected_storage_status = (
            StorageAdmissionStatus.ADMISSIBLE
            if self.status is ImagingStorageAuthorizationStatus.AUTHORIZED
            else StorageAdmissionStatus.INSUFFICIENT_CAPACITY
        )
        if self.storage_admission_result.status is not expected_storage_status:
            raise ValueError(
                "status is inconsistent with storage admission status"
            )


def authorize_imaging_storage_execution(
    context: SimulationContext,
    previous_execution: ScheduledObservationExecution,
    execution: ScheduledObservationAcquisitionExecution,
    *,
    record_id: AcquisitionDataRecordId,
    environment: AcquisitionEPSIntervalEnvironment,
    routing_config: ComponentHeatRoutingConfig,
    thermal_inputs: ThermalIntervalInputs,
    external_heat_sources: ThermalHeatSourceInputs,
) -> ImagingStorageAuthorizationResult:
    """Compose F2 authorization with pure whole-record storage admission."""
    contracts = (
        ("context", context, SimulationContext),
        (
            "previous_execution",
            previous_execution,
            ScheduledObservationExecution,
        ),
        (
            "execution",
            execution,
            ScheduledObservationAcquisitionExecution,
        ),
        ("record_id", record_id, AcquisitionDataRecordId),
        (
            "environment",
            environment,
            AcquisitionEPSIntervalEnvironment,
        ),
        (
            "routing_config",
            routing_config,
            ComponentHeatRoutingConfig,
        ),
        ("thermal_inputs", thermal_inputs, ThermalIntervalInputs),
        (
            "external_heat_sources",
            external_heat_sources,
            ThermalHeatSourceInputs,
        ),
    )
    for field_name, value, expected_type in contracts:
        if type(value) is not expected_type:
            raise TypeError(
                f"{field_name} must be a {expected_type.__name__}"
            )
    AcquisitionDataRecordId(record_id.value)

    imaging_result = evaluate_imaging_engine_step_authorization(
        context,
        previous_execution,
        execution,
        environment,
        routing_config,
        thermal_inputs,
        external_heat_sources,
    )
    if type(imaging_result) is not ImagingExecutionAuthorizationResult:
        raise TypeError(
            "F2 must return an ImagingExecutionAuthorizationResult"
        )
    _revalidate_imaging_authorization_result(imaging_result)
    if imaging_result.status is not ImagingExecutionAuthorizationStatus.AUTHORIZED:
        return ImagingStorageAuthorizationResult(
            imaging_result,
            None,
            None,
            ImagingStorageAuthorizationStatus.IMAGING_NOT_AUTHORIZED,
        )

    acquisition_result = (
        imaging_result.electrical_result.acquisition_evaluation
        .acquisition_result
    )
    if acquisition_result is None:
        raise ValueError("F2 authorization must contain an acquisition result")
    data_volume = compute_onboard_acquisition_data_volume_proposal(
        acquisition_result
    )
    if type(data_volume) is not OnboardAcquisitionDataVolumeProposal:
        raise TypeError(
            "A1 must return an OnboardAcquisitionDataVolumeProposal"
        )
    _revalidate_data_volume_proposal(data_volume)

    acquisition_input = imaging_result.execution.candidate.acquisition_input
    opportunity = (
        imaging_result.execution.candidate.maneuver_candidate.opportunity
    )
    proposed_record = OnboardAcquisitionDataRecord(
        record_id,
        opportunity.request_id,
        opportunity.opportunity_id,
        imaging_result.execution.scheduled_start_seconds,
        acquisition_input.imaging_duration_seconds,
        acquisition_input.channel_selection,
        data_volume.uncompressed_equivalent_bits,
        data_volume.stored_equivalent_bits,
    )
    storage_result = evaluate_storage_admission(
        context.inputs.spacecraft_configuration.storage,
        context.spacecraft_state.data_storage.stored_records,
        proposed_record,
    )
    if type(storage_result) is not StorageAdmissionResult:
        raise TypeError("B1 must return a StorageAdmissionResult")
    _revalidate_storage_admission_result(storage_result)
    status = (
        ImagingStorageAuthorizationStatus.AUTHORIZED
        if storage_result.status is StorageAdmissionStatus.ADMISSIBLE
        else ImagingStorageAuthorizationStatus.INSUFFICIENT_STORAGE_CAPACITY
    )
    return ImagingStorageAuthorizationResult(
        imaging_result,
        data_volume,
        storage_result,
        status,
    )


__all__ = [
    "ImagingStorageAuthorizationStatus",
    "ImagingStorageAuthorizationResult",
    "authorize_imaging_storage_execution",
]
