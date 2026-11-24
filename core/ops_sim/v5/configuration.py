"""Immutable V5 spacecraft and subsystem configuration ownership shells."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .adcs_config import AgilePointingConfig
from .degradation_config import BatteryAgeingModelConfig
from .ids import (
    ParameterId,
    SourceRecordId,
    SpacecraftConfigurationId,
    SubsystemConfigurationId,
)
from .parameters import ScalarParameter
from .payload_config import OpticalAcquisitionConfig
from .provenance import ParameterProvenance, SensitivityRange
from .thermal_config import ThermalNetworkConfig


class PayloadFamily(str, Enum):
    """Payload families admitted by the initial optical-EO architecture."""

    OPTICAL_EO = "optical-eo"


class PayloadMode(str, Enum):
    """Optical product/output-view capabilities in the V5 architecture."""

    PANCHROMATIC = "panchromatic"
    MULTISPECTRAL = "multispectral"


def _validate_subsystem_id(value: object) -> None:
    if type(value) is not SubsystemConfigurationId:
        raise TypeError(
            "configuration_id must be a SubsystemConfigurationId"
        )


def _validate_parameter(
    field_name: str,
    parameter: object,
    *,
    parameter_id: str,
    units: str,
    strictly_positive: bool,
) -> None:
    if type(parameter) is not ScalarParameter:
        raise TypeError(f"{field_name} must be a ScalarParameter")
    if (
        type(parameter.parameter_id) is not ParameterId
        or parameter.parameter_id.value != parameter_id
    ):
        raise ValueError(
            f"{field_name} must use ParameterId {parameter_id!r}"
        )
    if parameter.units != units:
        raise ValueError(f"{field_name} must use units {units!r}")
    if strictly_positive and parameter.value <= 0:
        raise ValueError(f"{field_name} must be strictly greater than zero")
    if not strictly_positive and parameter.value < 0:
        raise ValueError(f"{field_name} must be greater than or equal to zero")


def _revalidate_scalar_parameter(
    field_name: str,
    parameter: object,
) -> None:
    if type(parameter) is not ScalarParameter:
        raise TypeError(f"{field_name} must be a ScalarParameter")
    provenance = parameter.provenance
    if type(provenance) is not ParameterProvenance:
        raise TypeError(
            f"{field_name}.provenance must be a ParameterProvenance"
        )
    parameter_id = provenance.parameter_id
    if type(parameter_id) is not ParameterId:
        raise TypeError(
            f"{field_name}.parameter_id must be a ParameterId"
        )
    ParameterId(parameter_id.value)

    source_ids = provenance.source_ids
    if type(source_ids) is not tuple:
        raise TypeError(f"{field_name}.source_ids must be a tuple")
    for source_id in source_ids:
        if type(source_id) is not SourceRecordId:
            raise TypeError(
                f"{field_name}.source_ids must contain SourceRecordId values"
            )
        SourceRecordId(source_id.value)

    sensitivity_range = provenance.sensitivity_range
    if sensitivity_range is not None:
        if type(sensitivity_range) is not SensitivityRange:
            raise TypeError(
                f"{field_name}.sensitivity_range must be a SensitivityRange "
                "or None"
            )
        SensitivityRange(
            sensitivity_range.lower,
            sensitivity_range.upper,
        )

    ParameterProvenance(
        parameter_id,
        provenance.classification,
        provenance.units,
        source_ids,
        provenance.status,
        provenance.rationale,
        provenance.derivation,
        sensitivity_range,
    )
    ScalarParameter(parameter.value, provenance)


@dataclass(frozen=True, slots=True)
class BatteryConfig:
    """Own immutable Level-1 battery energy and bus-power parameters.

    ``max_charge_input_power_w`` is the bus-side power accepted before
    charge-efficiency losses. ``max_discharge_output_power_w`` is the
    bus-side power delivered after discharge-efficiency losses.
    """

    configuration_id: SubsystemConfigurationId
    nominal_energy_wh: ScalarParameter
    charge_efficiency: ScalarParameter
    discharge_efficiency: ScalarParameter
    max_charge_input_power_w: ScalarParameter
    max_discharge_output_power_w: ScalarParameter

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)
        _validate_parameter(
            "nominal_energy_wh",
            self.nominal_energy_wh,
            parameter_id="eps.battery.nominal-energy",
            units="Wh",
            strictly_positive=True,
        )
        _validate_parameter(
            "charge_efficiency",
            self.charge_efficiency,
            parameter_id="eps.battery.charge-efficiency",
            units="1",
            strictly_positive=True,
        )
        if self.charge_efficiency.value > 1:
            raise ValueError(
                "charge_efficiency must be less than or equal to one"
            )
        _validate_parameter(
            "discharge_efficiency",
            self.discharge_efficiency,
            parameter_id="eps.battery.discharge-efficiency",
            units="1",
            strictly_positive=True,
        )
        if self.discharge_efficiency.value > 1:
            raise ValueError(
                "discharge_efficiency must be less than or equal to one"
            )
        _validate_parameter(
            "max_charge_input_power_w",
            self.max_charge_input_power_w,
            parameter_id="eps.battery.max-charge-input-power",
            units="W",
            strictly_positive=True,
        )
        _validate_parameter(
            "max_discharge_output_power_w",
            self.max_discharge_output_power_w,
            parameter_id="eps.battery.max-discharge-output-power",
            units="W",
            strictly_positive=True,
        )


@dataclass(frozen=True, slots=True)
class SolarArrayConfig:
    """Own the solar-array identity and nominal generation parameter."""

    configuration_id: SubsystemConfigurationId
    nominal_generation_w: ScalarParameter

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)
        _validate_parameter(
            "nominal_generation_w",
            self.nominal_generation_w,
            parameter_id="eps.solar-array.nominal-generation",
            units="W",
            strictly_positive=True,
        )


@dataclass(frozen=True, slots=True)
class EPSConfig:
    """Own the electrical-power subsystem and its battery and solar array."""

    configuration_id: SubsystemConfigurationId
    battery: BatteryConfig
    solar_array: SolarArrayConfig

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)
        if type(self.battery) is not BatteryConfig:
            raise TypeError("battery must be a BatteryConfig")
        if type(self.solar_array) is not SolarArrayConfig:
            raise TypeError("solar_array must be a SolarArrayConfig")


@dataclass(frozen=True, slots=True)
class PayloadConfig:
    """Own payload identity, output views, and physical acquisition semantics."""

    configuration_id: SubsystemConfigurationId
    payload_family: PayloadFamily
    supported_modes: tuple[PayloadMode, ...]
    optical_acquisition: OpticalAcquisitionConfig

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)
        if type(self.payload_family) is not PayloadFamily:
            raise TypeError("payload_family must be a PayloadFamily")
        if type(self.supported_modes) is not tuple:
            raise TypeError("supported_modes must be a tuple")
        if not self.supported_modes:
            raise ValueError("supported_modes must not be empty")
        if not all(type(mode) is PayloadMode for mode in self.supported_modes):
            raise TypeError("supported_modes must contain only PayloadMode values")
        if len(set(self.supported_modes)) != len(self.supported_modes):
            raise ValueError("supported_modes must not contain duplicates")
        if type(self.optical_acquisition) is not OpticalAcquisitionConfig:
            raise TypeError(
                "optical_acquisition must be an OpticalAcquisitionConfig"
            )
        OpticalAcquisitionConfig(
            self.optical_acquisition.reference_nadir_swath_width_m,
            self.optical_acquisition.panchromatic_reference_sample_spacing_m,
            self.optical_acquisition.multispectral_reference_sample_spacing_m,
            self.optical_acquisition.multispectral_band_count,
            self.optical_acquisition.acquisition_bits_per_sample,
            self.optical_acquisition.acquisition_power_w,
            self.optical_acquisition.simultaneous_pan_and_multispectral,
        )


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """Own the storage identity and usable payload-data capacity."""

    configuration_id: SubsystemConfigurationId
    usable_capacity_gb: ScalarParameter

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)
        _validate_parameter(
            "usable_capacity_gb",
            self.usable_capacity_gb,
            parameter_id="storage.usable-capacity",
            units="GB",
            strictly_positive=True,
        )


@dataclass(frozen=True, slots=True)
class CommunicationsConfig:
    """Own communications identity and nominal downlink data-link rate."""

    configuration_id: SubsystemConfigurationId
    nominal_downlink_data_rate_bps: ScalarParameter

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)
        _revalidate_scalar_parameter(
            "nominal_downlink_data_rate_bps",
            self.nominal_downlink_data_rate_bps,
        )
        _validate_parameter(
            "nominal_downlink_data_rate_bps",
            self.nominal_downlink_data_rate_bps,
            parameter_id="communications.nominal-downlink-data-rate",
            units="bit/s",
            strictly_positive=True,
        )


@dataclass(frozen=True, slots=True)
class ADCSConfig:
    """Own ADCS identity and immutable agile-pointing capability."""

    configuration_id: SubsystemConfigurationId
    agile_pointing: AgilePointingConfig

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)
        if type(self.agile_pointing) is not AgilePointingConfig:
            raise TypeError("agile_pointing must be an AgilePointingConfig")
        AgilePointingConfig(
            self.agile_pointing.maximum_view_angle_from_nadir_deg,
            self.agile_pointing.post_slew_settling_time_seconds,
            self.agile_pointing.slew_time_anchors,
        )


@dataclass(frozen=True, slots=True)
class ThermalConfig:
    """Own the thermal subsystem identity and immutable thermal network."""

    configuration_id: SubsystemConfigurationId
    network: ThermalNetworkConfig

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)
        if type(self.network) is not ThermalNetworkConfig:
            raise TypeError("network must be a ThermalNetworkConfig")


@dataclass(frozen=True, slots=True)
class DegradationConfig:
    """Own immutable degradation model definition and initial conditions."""

    configuration_id: SubsystemConfigurationId
    initial_battery_usable_capacity_retention: ScalarParameter
    initial_solar_generation_retention: ScalarParameter
    initial_battery_energy_throughput_wh: ScalarParameter
    battery_ageing_model: BatteryAgeingModelConfig

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)
        _validate_parameter(
            "initial_battery_usable_capacity_retention",
            self.initial_battery_usable_capacity_retention,
            parameter_id=(
                "degradation.battery.initial-usable-capacity-retention"
            ),
            units="1",
            strictly_positive=True,
        )
        if self.initial_battery_usable_capacity_retention.value > 1:
            raise ValueError(
                "initial_battery_usable_capacity_retention must be less "
                "than or equal to one"
            )
        _validate_parameter(
            "initial_solar_generation_retention",
            self.initial_solar_generation_retention,
            parameter_id="degradation.solar.initial-generation-retention",
            units="1",
            strictly_positive=True,
        )
        if self.initial_solar_generation_retention.value > 1:
            raise ValueError(
                "initial_solar_generation_retention must be less than or "
                "equal to one"
            )
        _validate_parameter(
            "initial_battery_energy_throughput_wh",
            self.initial_battery_energy_throughput_wh,
            parameter_id="degradation.battery.initial-energy-throughput",
            units="Wh",
            strictly_positive=False,
        )
        if type(self.battery_ageing_model) is not BatteryAgeingModelConfig:
            raise TypeError(
                "battery_ageing_model must be a BatteryAgeingModelConfig"
            )
        BatteryAgeingModelConfig(
            self.battery_ageing_model.reference_temperature_k,
            self.battery_ageing_model
            .calendar_damage_rate_per_second_at_reference,
            self.battery_ageing_model.calendar_activation_energy_j_per_mol,
            self.battery_ageing_model
            .cycling_damage_per_normalized_energy_throughput_at_reference,
            self.battery_ageing_model.cycling_activation_energy_j_per_mol,
        )


@dataclass(frozen=True, slots=True)
class PropulsionConfig:
    """Own propulsion identity and the initial delta-v capability."""

    configuration_id: SubsystemConfigurationId
    initial_delta_v_m_per_s: ScalarParameter

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)
        _validate_parameter(
            "initial_delta_v_m_per_s",
            self.initial_delta_v_m_per_s,
            parameter_id="propulsion.initial-delta-v",
            units="m/s",
            strictly_positive=False,
        )


@dataclass(frozen=True, slots=True)
class OBCConfig:
    """Reserve immutable ownership for later onboard-computer parameters."""

    configuration_id: SubsystemConfigurationId

    def __post_init__(self) -> None:
        _validate_subsystem_id(self.configuration_id)


@dataclass(frozen=True, slots=True)
class SpacecraftConfiguration:
    """Aggregate one immutable spacecraft hardware configuration graph."""

    configuration_id: SpacecraftConfigurationId
    label: str
    schema_version: int
    eps: EPSConfig
    payload: PayloadConfig
    storage: StorageConfig
    communications: CommunicationsConfig
    adcs: ADCSConfig
    thermal: ThermalConfig
    degradation: DegradationConfig
    propulsion: PropulsionConfig
    obc: OBCConfig

    def __post_init__(self) -> None:
        if type(self.configuration_id) is not SpacecraftConfigurationId:
            raise TypeError(
                "configuration_id must be a SpacecraftConfigurationId"
            )
        if type(self.label) is not str:
            raise TypeError("label must be a string")
        if not self.label:
            raise ValueError("label must not be empty")
        if self.label != self.label.strip():
            raise ValueError(
                "label must not have leading or trailing whitespace"
            )
        if type(self.schema_version) is not int:
            raise TypeError("schema_version must be an integer")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be greater than zero")

        nested_contracts = (
            ("eps", self.eps, EPSConfig),
            ("payload", self.payload, PayloadConfig),
            ("storage", self.storage, StorageConfig),
            (
                "communications",
                self.communications,
                CommunicationsConfig,
            ),
            ("adcs", self.adcs, ADCSConfig),
            ("thermal", self.thermal, ThermalConfig),
            ("degradation", self.degradation, DegradationConfig),
            ("propulsion", self.propulsion, PropulsionConfig),
            ("obc", self.obc, OBCConfig),
        )
        for field_name, value, expected_type in nested_contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )

        subsystem_ids = (
            self.eps.configuration_id,
            self.eps.battery.configuration_id,
            self.eps.solar_array.configuration_id,
            self.payload.configuration_id,
            self.storage.configuration_id,
            self.communications.configuration_id,
            self.adcs.configuration_id,
            self.thermal.configuration_id,
            self.degradation.configuration_id,
            self.propulsion.configuration_id,
            self.obc.configuration_id,
        )
        if len(set(subsystem_ids)) != len(subsystem_ids):
            raise ValueError(
                "all subsystem configuration IDs must be unique"
            )


__all__ = [
    "ADCSConfig",
    "BatteryConfig",
    "CommunicationsConfig",
    "DegradationConfig",
    "EPSConfig",
    "OBCConfig",
    "PayloadConfig",
    "PayloadFamily",
    "PayloadMode",
    "PropulsionConfig",
    "SolarArrayConfig",
    "SpacecraftConfiguration",
    "StorageConfig",
    "ThermalConfig",
]
