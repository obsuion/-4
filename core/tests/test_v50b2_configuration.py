"""Focused tests for V5.0B2 immutable configuration foundations."""

from dataclasses import MISSING, FrozenInstanceError, fields, replace

import pytest

from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.configuration import (
    ADCSConfig,
    BatteryConfig,
    CommunicationsConfig,
    DegradationConfig,
    EPSConfig,
    OBCConfig,
    PayloadConfig,
    PayloadFamily,
    PayloadMode,
    PropulsionConfig,
    SolarArrayConfig,
    SpacecraftConfiguration,
    StorageConfig,
    ThermalConfig,
)
from ops_sim.v5.degradation_config import BatteryAgeingModelConfig
from ops_sim.v5.ids import (
    ADCSSlewAnchorId,
    ParameterId,
    SourceRecordId,
    SpacecraftConfigurationId,
    SubsystemConfigurationId,
    ThermalNodeId,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload_config import OpticalAcquisitionConfig
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
    SensitivityRange,
)
from ops_sim.v5.thermal_config import ThermalNetworkConfig, ThermalNodeConfig


PHYSICAL_CONFIG_CASES = (
    (
        BatteryConfig,
        "battery",
        "eps.battery.nominal-energy",
        "Wh",
        120.0,
    ),
    (
        SolarArrayConfig,
        "solar-array",
        "eps.solar-array.nominal-generation",
        "W",
        240.0,
    ),
    (
        StorageConfig,
        "storage",
        "storage.usable-capacity",
        "GB",
        80.0,
    ),
    (
        CommunicationsConfig,
        "communications",
        "communications.nominal-downlink-data-rate",
        "bit/s",
        1_000_000.0,
    ),
    (
        PropulsionConfig,
        "propulsion",
        "propulsion.initial-delta-v",
        "m/s",
        12.0,
    ),
)


def _provenance(
    parameter_id: str,
    units: str,
    *,
    status: ProvenanceStatus = ProvenanceStatus.TO_RESEARCH,
    sensitivity_range: SensitivityRange | None = None,
) -> ParameterProvenance:
    return ParameterProvenance(
        parameter_id=ParameterId(parameter_id),
        classification=ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
        units=units,
        source_ids=(),
        status=status,
        rationale="Synthetic value used only by a focused unit test.",
        sensitivity_range=sensitivity_range,
    )


def _parameter(
    parameter_id: str,
    units: str,
    value: float,
    **provenance_changes,
) -> ScalarParameter:
    return ScalarParameter(
        value,
        _provenance(parameter_id, units, **provenance_changes),
    )


def _agile_pointing() -> AgilePointingConfig:
    def anchor(
        anchor_value: str,
        angle_deg: float,
        elapsed_seconds: float,
    ) -> BoresightSlewTimeAnchor:
        prefix = f"adcs.slew-envelope.{anchor_value}"
        return BoresightSlewTimeAnchor(
            ADCSSlewAnchorId(anchor_value),
            _parameter(f"{prefix}.angular-separation", "deg", angle_deg),
            _parameter(f"{prefix}.elapsed-time", "s", elapsed_seconds),
        )

    return AgilePointingConfig(
        _parameter(
            "adcs.pointing.maximum-view-angle-from-nadir", "deg", 45.0
        ),
        _parameter("adcs.pointing.post-slew-settling-time", "s", 5.0),
        tuple(
            anchor(*values)
            for values in (
                ("zero", 0.0, 0.0),
                ("small", 10.0, 20.0),
                ("medium", 30.0, 50.0),
                ("large", 60.0, 90.0),
                ("extended", 90.0, 130.0),
            )
        ),
    )


def _optical_acquisition() -> OpticalAcquisitionConfig:
    return OpticalAcquisitionConfig(
        _parameter(
            "payload.optical.reference-nadir-swath-width", "m", 1000.0
        ),
        _parameter(
            "payload.optical.panchromatic-reference-sample-spacing",
            "m",
            1.0,
        ),
        _parameter(
            "payload.optical.multispectral-reference-sample-spacing",
            "m",
            4.0,
        ),
        _parameter("payload.optical.multispectral-band-count", "1", 4),
        _parameter(
            "payload.optical.acquisition-bits-per-sample",
            "bit/sample",
            12,
        ),
        _parameter("payload.optical.acquisition-power", "W", 100.0),
        True,
    )


def _zero_damage_ageing_model() -> BatteryAgeingModelConfig:
    return BatteryAgeingModelConfig(
        _parameter(
            "degradation.battery.reference-temperature", "K", 300.0
        ),
        _parameter(
            "degradation.battery.calendar-damage-rate-at-reference",
            "1/s",
            0.0,
        ),
        _parameter(
            "degradation.battery.calendar-activation-energy", "J/mol", 0.0
        ),
        _parameter(
            "degradation.battery.cycling-damage-per-normalized-"
            "throughput-at-reference",
            "1",
            0.0,
        ),
        _parameter(
            "degradation.battery.cycling-activation-energy", "J/mol", 0.0
        ),
    )


def _thermal_network() -> ThermalNetworkConfig:
    def node(node_name: str) -> ThermalNodeConfig:
        prefix = f"thermal.node.{node_name}"
        return ThermalNodeConfig(
            ThermalNodeId(node_name),
            _parameter(f"{prefix}.heat-capacity", "J/K", 1000.0),
            _parameter(f"{prefix}.emissivity", "1", 0.8),
            _parameter(f"{prefix}.radiating-area", "m^2", 1.0),
            _parameter(
                f"{prefix}.operating-min-temperature", "K", 270.0
            ),
            _parameter(
                f"{prefix}.operating-max-temperature", "K", 320.0
            ),
            _parameter(
                f"{prefix}.survival-min-temperature", "K", 250.0
            ),
            _parameter(
                f"{prefix}.survival-max-temperature", "K", 340.0
            ),
        )

    nodes = tuple(node(name) for name in ("bus", "battery", "payload"))
    return ThermalNetworkConfig(
        nodes,
        (),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("payload"),
    )


def _battery(
    configuration_id: str = "battery",
    value: float = 120.0,
) -> BatteryConfig:
    return BatteryConfig(
        SubsystemConfigurationId(configuration_id),
        _parameter("eps.battery.nominal-energy", "Wh", value),
        *_battery_operating_parameters(),
    )


def _battery_operating_parameters() -> tuple[ScalarParameter, ...]:
    return (
        _parameter("eps.battery.charge-efficiency", "1", 0.90),
        _parameter("eps.battery.discharge-efficiency", "1", 0.90),
        _parameter("eps.battery.max-charge-input-power", "W", 50.0),
        _parameter("eps.battery.max-discharge-output-power", "W", 50.0),
    )


def _physical_configuration(
    config_type,
    config_id: str,
    parameter: object,
):
    arguments = (
        (parameter, *_battery_operating_parameters())
        if config_type is BatteryConfig
        else (parameter,)
    )
    return config_type(SubsystemConfigurationId(config_id), *arguments)


def _solar_array(
    configuration_id: str = "solar-array",
    value: float = 240.0,
) -> SolarArrayConfig:
    return SolarArrayConfig(
        SubsystemConfigurationId(configuration_id),
        _parameter("eps.solar-array.nominal-generation", "W", value),
    )


def _eps(
    configuration_id: str = "eps",
    *,
    battery: BatteryConfig | None = None,
    solar_array: SolarArrayConfig | None = None,
) -> EPSConfig:
    return EPSConfig(
        SubsystemConfigurationId(configuration_id),
        battery or _battery(),
        solar_array or _solar_array(),
    )


def _payload(configuration_id: str = "payload") -> PayloadConfig:
    return PayloadConfig(
        SubsystemConfigurationId(configuration_id),
        PayloadFamily.OPTICAL_EO,
        (PayloadMode.PANCHROMATIC, PayloadMode.MULTISPECTRAL),
        _optical_acquisition(),
    )


def _storage(configuration_id: str = "storage") -> StorageConfig:
    return StorageConfig(
        SubsystemConfigurationId(configuration_id),
        _parameter("storage.usable-capacity", "GB", 80.0),
    )


def _communications(
    configuration_id: str = "communications",
) -> CommunicationsConfig:
    return CommunicationsConfig(
        SubsystemConfigurationId(configuration_id),
        _parameter(
            "communications.nominal-downlink-data-rate",
            "bit/s",
            1_000_000.0,
        ),
    )


def _propulsion(
    configuration_id: str = "propulsion",
    value: float = 12.0,
) -> PropulsionConfig:
    return PropulsionConfig(
        SubsystemConfigurationId(configuration_id),
        _parameter("propulsion.initial-delta-v", "m/s", value),
    )


def _spacecraft_values() -> dict[str, object]:
    return {
        "configuration_id": SpacecraftConfigurationId("reference-optical"),
        "label": "Synthetic Optical Reference",
        "schema_version": 1,
        "eps": _eps(),
        "payload": _payload(),
        "storage": _storage(),
        "communications": _communications(),
        "adcs": ADCSConfig(
            SubsystemConfigurationId("adcs"), _agile_pointing()
        ),
        "thermal": ThermalConfig(
            SubsystemConfigurationId("thermal"),
            _thermal_network(),
        ),
        "degradation": DegradationConfig(
            SubsystemConfigurationId("degradation"),
            _parameter(
                "degradation.battery.initial-usable-capacity-retention",
                "1",
                1.0,
            ),
            _parameter(
                "degradation.solar.initial-generation-retention", "1", 1.0
            ),
            _parameter(
                "degradation.battery.initial-energy-throughput", "Wh", 0.0
            ),
            _zero_damage_ageing_model(),
        ),
        "propulsion": _propulsion(),
        "obc": OBCConfig(SubsystemConfigurationId("obc")),
    }


def _spacecraft(**changes) -> SpacecraftConfiguration:
    values = _spacecraft_values()
    values.update(changes)
    return SpacecraftConfiguration(**values)


def _subsystem_instances() -> tuple[object, ...]:
    return (
        _battery(),
        _solar_array(),
        _eps(),
        _payload(),
        _storage(),
        _communications(),
        ADCSConfig(SubsystemConfigurationId("adcs"), _agile_pointing()),
        ThermalConfig(
            SubsystemConfigurationId("thermal"),
            _thermal_network(),
        ),
        DegradationConfig(
            SubsystemConfigurationId("degradation"),
            _parameter(
                "degradation.battery.initial-usable-capacity-retention",
                "1",
                1.0,
            ),
            _parameter(
                "degradation.solar.initial-generation-retention", "1", 1.0
            ),
            _parameter(
                "degradation.battery.initial-energy-throughput", "Wh", 0.0
            ),
            _zero_damage_ageing_model(),
        ),
        _propulsion(),
        OBCConfig(SubsystemConfigurationId("obc")),
    )


@pytest.mark.parametrize("value", (1, 1.5, -2, -2.5, 0))
def test_scalar_parameter_accepts_finite_real_values(value) -> None:
    provenance = _provenance("test.scalar", "1")

    parameter = ScalarParameter(value, provenance)

    assert parameter.value == value
    assert parameter.provenance is provenance


def test_scalar_parameter_is_immutable_slotted_and_exposes_provenance() -> None:
    provenance = _provenance("test.scalar", "kg")
    parameter = ScalarParameter(4.0, provenance)

    assert parameter.parameter_id is provenance.parameter_id
    assert parameter.units == "kg"
    assert not hasattr(parameter, "__dict__")
    assert isinstance(hash(parameter), int)
    with pytest.raises(FrozenInstanceError):
        parameter.value = 5.0


def test_scalar_parameter_rejects_bool_nonreal_and_nonfinite_values() -> None:
    provenance = _provenance("test.scalar", "1")
    for value in (True, False, "1"):
        with pytest.raises(TypeError):
            ScalarParameter(value, provenance)
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            ScalarParameter(value, provenance)


def test_scalar_parameter_rejects_wrong_provenance_type() -> None:
    with pytest.raises(TypeError):
        ScalarParameter(1.0, "not provenance")


@pytest.mark.parametrize(
    "status",
    (ProvenanceStatus.REJECTED, ProvenanceStatus.SUPERSEDED),
)
def test_scalar_parameter_rejects_inadmissible_provenance(status) -> None:
    with pytest.raises(ValueError):
        ScalarParameter(
            1.0,
            _provenance("test.scalar", "1", status=status),
        )


@pytest.mark.parametrize(
    "status",
    (
        ProvenanceStatus.TO_RESEARCH,
        ProvenanceStatus.TO_VERIFY,
        ProvenanceStatus.VERIFIED,
    ),
)
def test_scalar_parameter_accepts_admissible_provenance(status) -> None:
    parameter = ScalarParameter(
        1.0,
        _provenance("test.scalar", "1", status=status),
    )

    assert parameter.provenance.status is status


@pytest.mark.parametrize("value", (1.0, 1.5, 2.0))
def test_scalar_parameter_accepts_inclusive_sensitivity_range(value) -> None:
    parameter = _parameter(
        "test.scalar",
        "1",
        value,
        sensitivity_range=SensitivityRange(1.0, 2.0),
    )

    assert parameter.value == value


@pytest.mark.parametrize("value", (0.999, 2.001))
def test_scalar_parameter_rejects_value_outside_sensitivity_range(
    value,
) -> None:
    with pytest.raises(ValueError):
        _parameter(
            "test.scalar",
            "1",
            value,
            sensitivity_range=SensitivityRange(1.0, 2.0),
        )


@pytest.mark.parametrize(
    "config_type,config_id,parameter_id,units,value",
    PHYSICAL_CONFIG_CASES,
)
def test_physical_field_contracts_accept_exact_identity_and_units(
    config_type,
    config_id,
    parameter_id,
    units,
    value,
) -> None:
    parameter = _parameter(parameter_id, units, value)

    configuration = _physical_configuration(
        config_type,
        config_id,
        parameter,
    )

    assert configuration.configuration_id.value == config_id
    assert any(
        getattr(configuration, field.name) is parameter
        for field in fields(config_type)
    )


@pytest.mark.parametrize(
    "config_type,config_id,parameter_id,units,value",
    PHYSICAL_CONFIG_CASES,
)
def test_physical_field_contracts_reject_wrong_parameter_id(
    config_type,
    config_id,
    parameter_id,
    units,
    value,
) -> None:
    with pytest.raises(ValueError):
        _physical_configuration(
            config_type,
            config_id,
            _parameter("wrong.parameter", units, value),
        )


@pytest.mark.parametrize(
    "config_type,config_id,parameter_id,units,value",
    PHYSICAL_CONFIG_CASES,
)
def test_physical_field_contracts_reject_wrong_units(
    config_type,
    config_id,
    parameter_id,
    units,
    value,
) -> None:
    with pytest.raises(ValueError):
        _physical_configuration(
            config_type,
            config_id,
            _parameter(parameter_id, "wrong-unit", value),
        )


@pytest.mark.parametrize(
    "config_type,config_id,parameter_id,units,value",
    PHYSICAL_CONFIG_CASES,
)
def test_physical_fields_reject_plain_numbers(
    config_type,
    config_id,
    parameter_id,
    units,
    value,
) -> None:
    with pytest.raises(TypeError):
        _physical_configuration(config_type, config_id, value)


@pytest.mark.parametrize(
    "config_type,config_id,parameter_id,units,_valid_value",
    PHYSICAL_CONFIG_CASES[:-1],
)
@pytest.mark.parametrize("value", (0.0, -0.001))
def test_positive_physical_fields_reject_zero_and_negative_values(
    config_type,
    config_id,
    parameter_id,
    units,
    _valid_value,
    value,
) -> None:
    with pytest.raises(ValueError):
        _physical_configuration(
            config_type,
            config_id,
            _parameter(parameter_id, units, value),
        )


def test_propulsion_accepts_zero_and_rejects_negative_delta_v() -> None:
    assert _propulsion(value=0.0).initial_delta_v_m_per_s.value == 0.0
    with pytest.raises(ValueError):
        _propulsion(value=-0.001)


def test_current_communications_contract_is_exact_required_and_synthetic() -> None:
    configuration = _communications()
    parameter = configuration.nominal_downlink_data_rate_bps

    assert tuple(field.name for field in fields(CommunicationsConfig)) == (
        "configuration_id",
        "nominal_downlink_data_rate_bps",
    )
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(CommunicationsConfig)
    )
    assert type(parameter) is ScalarParameter
    assert parameter.parameter_id == ParameterId(
        "communications.nominal-downlink-data-rate"
    )
    assert parameter.units == "bit/s"
    assert parameter.value == 1_000_000.0
    assert parameter.provenance.classification is (
        ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
    )
    assert parameter.provenance.status is ProvenanceStatus.TO_RESEARCH
    assert parameter.provenance.source_ids == ()


def test_communications_revalidates_corrupted_parameter_and_provenance() -> None:
    corrupted_value = _parameter(
        "communications.nominal-downlink-data-rate",
        "bit/s",
        1_000_000.0,
    )
    object.__setattr__(corrupted_value, "value", float("nan"))
    with pytest.raises(ValueError, match="finite"):
        CommunicationsConfig(
            SubsystemConfigurationId("communications"),
            corrupted_value,
        )

    corrupted_id = _parameter(
        "communications.nominal-downlink-data-rate",
        "bit/s",
        1_000_000.0,
    )
    object.__setattr__(
        corrupted_id.provenance.parameter_id,
        "value",
        "CORRUPTED",
    )
    with pytest.raises(ValueError, match="StableId value"):
        CommunicationsConfig(
            SubsystemConfigurationId("communications"),
            corrupted_id,
        )


def test_payload_enums_have_only_the_b2_optical_values() -> None:
    assert tuple(PayloadFamily) == (PayloadFamily.OPTICAL_EO,)
    assert tuple(PayloadMode) == (
        PayloadMode.PANCHROMATIC,
        PayloadMode.MULTISPECTRAL,
    )


def test_payload_accepts_one_or_both_modes_and_retains_tuple() -> None:
    one_mode = (PayloadMode.PANCHROMATIC,)
    both_modes = (PayloadMode.PANCHROMATIC, PayloadMode.MULTISPECTRAL)

    first = PayloadConfig(
        SubsystemConfigurationId("payload-one"),
        PayloadFamily.OPTICAL_EO,
        one_mode,
        _optical_acquisition(),
    )
    second = PayloadConfig(
        SubsystemConfigurationId("payload-two"),
        PayloadFamily.OPTICAL_EO,
        both_modes,
        _optical_acquisition(),
    )

    assert first.supported_modes is one_mode
    assert second.supported_modes is both_modes


def test_payload_rejects_empty_list_duplicate_and_wrong_mode_values() -> None:
    payload_id = SubsystemConfigurationId("payload")
    with pytest.raises(ValueError):
        PayloadConfig(
            payload_id,
            PayloadFamily.OPTICAL_EO,
            (),
            _optical_acquisition(),
        )
    with pytest.raises(TypeError):
        PayloadConfig(
            payload_id,
            PayloadFamily.OPTICAL_EO,
            [PayloadMode.PANCHROMATIC],
            _optical_acquisition(),
        )
    with pytest.raises(ValueError):
        PayloadConfig(
            payload_id,
            PayloadFamily.OPTICAL_EO,
            (PayloadMode.PANCHROMATIC, PayloadMode.PANCHROMATIC),
            _optical_acquisition(),
        )
    with pytest.raises(TypeError):
        PayloadConfig(
            payload_id,
            PayloadFamily.OPTICAL_EO,
            ("panchromatic",),
            _optical_acquisition(),
        )


def test_payload_rejects_wrong_family_type() -> None:
    with pytest.raises(TypeError):
        PayloadConfig(
            SubsystemConfigurationId("payload"),
            "optical-eo",
            (PayloadMode.PANCHROMATIC,),
            _optical_acquisition(),
        )


def test_every_subsystem_shell_constructs_and_is_immutable_and_slotted() -> None:
    for configuration in _subsystem_instances():
        assert type(configuration.configuration_id) is SubsystemConfigurationId
        assert not hasattr(configuration, "__dict__")
        assert isinstance(hash(configuration), int)
        with pytest.raises(FrozenInstanceError):
            configuration.configuration_id = SubsystemConfigurationId(
                "replacement"
            )


def test_every_subsystem_shell_rejects_wrong_configuration_id_type() -> None:
    for configuration in _subsystem_instances():
        with pytest.raises(TypeError):
            replace(
                configuration,
                configuration_id=ParameterId("wrong-id-type"),
            )


def test_eps_rejects_wrong_nested_types() -> None:
    eps_id = SubsystemConfigurationId("eps")
    with pytest.raises(TypeError):
        EPSConfig(eps_id, _solar_array(), _solar_array())
    with pytest.raises(TypeError):
        EPSConfig(eps_id, _battery(), _battery())


def test_spacecraft_configuration_accepts_complete_unicode_design() -> None:
    configuration = _spacecraft(
        label="Синтетическая оптическая платформа"
    )

    assert configuration.schema_version == 1
    assert configuration.label == "Синтетическая оптическая платформа"
    assert not hasattr(configuration, "__dict__")
    assert isinstance(hash(configuration), int)


@pytest.mark.parametrize("label", ("", " ", " leading", "trailing "))
def test_spacecraft_configuration_rejects_invalid_labels(label) -> None:
    with pytest.raises(ValueError):
        _spacecraft(label=label)


def test_spacecraft_configuration_rejects_non_string_label() -> None:
    with pytest.raises(TypeError):
        _spacecraft(label=17)


@pytest.mark.parametrize("schema_version", (0, -1))
def test_spacecraft_configuration_rejects_nonpositive_schema(schema_version) -> None:
    with pytest.raises(ValueError):
        _spacecraft(schema_version=schema_version)


@pytest.mark.parametrize("schema_version", (True, 1.0, "1"))
def test_spacecraft_configuration_rejects_noninteger_schema(schema_version) -> None:
    with pytest.raises(TypeError):
        _spacecraft(schema_version=schema_version)


def test_spacecraft_configuration_rejects_wrong_identity_type() -> None:
    with pytest.raises(TypeError):
        _spacecraft(configuration_id=SubsystemConfigurationId("spacecraft"))


@pytest.mark.parametrize(
    "field_name",
    (
        "eps",
        "payload",
        "storage",
        "communications",
        "adcs",
        "thermal",
        "propulsion",
        "obc",
    ),
)
def test_spacecraft_configuration_rejects_every_wrong_nested_type(
    field_name,
) -> None:
    with pytest.raises(TypeError):
        _spacecraft(**{field_name: object()})


@pytest.mark.parametrize(
    "duplicate_kind",
    (
        "sibling",
        "eps-battery",
        "battery-solar",
        "nested-unrelated",
    ),
)
def test_spacecraft_configuration_rejects_deep_duplicate_ids(
    duplicate_kind,
) -> None:
    values = _spacecraft_values()
    eps = values["eps"]
    assert type(eps) is EPSConfig
    if duplicate_kind == "sibling":
        payload = values["payload"]
        assert type(payload) is PayloadConfig
        values["storage"] = _storage(payload.configuration_id.value)
    elif duplicate_kind == "eps-battery":
        values["eps"] = _eps(
            eps.battery.configuration_id.value,
            battery=eps.battery,
            solar_array=eps.solar_array,
        )
    elif duplicate_kind == "battery-solar":
        values["eps"] = _eps(
            battery=eps.battery,
            solar_array=_solar_array(eps.battery.configuration_id.value),
        )
    else:
        values["communications"] = _communications(
            eps.battery.configuration_id.value
        )

    with pytest.raises(ValueError):
        SpacecraftConfiguration(**values)


def test_complete_configuration_graph_is_deeply_immutable() -> None:
    configuration = _spacecraft()

    with pytest.raises(FrozenInstanceError):
        configuration.label = "Replacement"
    with pytest.raises(FrozenInstanceError):
        configuration.eps.battery.nominal_energy_wh.value = 1.0
    with pytest.raises(FrozenInstanceError):
        configuration.eps.battery.nominal_energy_wh.provenance.units = "kWh"
    with pytest.raises(FrozenInstanceError):
        configuration.payload.supported_modes = (PayloadMode.PANCHROMATIC,)
    assert type(configuration.payload.supported_modes) is tuple
    assert type(
        configuration.eps.battery.nominal_energy_wh.provenance.source_ids
    ) is tuple


def test_frozen_subsystem_can_be_shared_across_spacecraft() -> None:
    shared_storage = _storage("shared-storage")
    first = _spacecraft(storage=shared_storage)
    second = _spacecraft(
        configuration_id=SpacecraftConfigurationId("second-optical"),
        label="Second Synthetic Optical Reference",
        storage=shared_storage,
    )

    assert first.storage is shared_storage
    assert second.storage is shared_storage
    assert first.storage.configuration_id == second.storage.configuration_id
    with pytest.raises(FrozenInstanceError):
        shared_storage.usable_capacity_gb = _parameter(
            "storage.usable-capacity", "GB", 100.0
        )


def test_configuration_dataclasses_have_no_field_defaults() -> None:
    configuration_types = (
        ScalarParameter,
        BatteryConfig,
        SolarArrayConfig,
        EPSConfig,
        PayloadConfig,
        StorageConfig,
        CommunicationsConfig,
        ADCSConfig,
        ThermalConfig,
        PropulsionConfig,
        OBCConfig,
        SpacecraftConfiguration,
    )
    for configuration_type in configuration_types:
        for field in fields(configuration_type):
            assert field.default is MISSING
            assert field.default_factory is MISSING


def test_new_configuration_modules_have_explicit_exports() -> None:
    from ops_sim.v5 import configuration, parameters

    assert parameters.__all__ == ["ScalarParameter"]
    assert set(configuration.__all__) == {
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
    }


def test_external_provenance_fixture_uses_typed_source_identity() -> None:
    provenance = ParameterProvenance(
        parameter_id=ParameterId("test.external"),
        classification=ProvenanceClass.LITERATURE_VALUE,
        units="1",
        source_ids=(SourceRecordId("s003-test-only"),),
        status=ProvenanceStatus.VERIFIED,
    )

    assert ScalarParameter(1.0, provenance).provenance is provenance
