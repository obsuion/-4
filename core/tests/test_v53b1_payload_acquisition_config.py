"""Optical payload acquisition configuration contracts for V5.3B1."""

import ast
from dataclasses import FrozenInstanceError, MISSING, fields
from pathlib import Path
import subprocess

import numpy as np
import pytest

from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.configuration import (
    PayloadConfig,
    PayloadFamily,
    PayloadMode,
    SpacecraftConfiguration,
)
from ops_sim.v5.ids import ParameterId, SubsystemConfigurationId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload_config import OpticalAcquisitionConfig
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_CONFIG_PATH = ROOT / "ops_sim" / "v5" / "payload_config.py"
CONFIGURATION_PATH = ROOT / "ops_sim" / "v5" / "configuration.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"

PARAMETER_CONTRACTS = (
    (
        "reference_nadir_swath_width_m",
        "payload.optical.reference-nadir-swath-width",
        "m",
        1000.0,
    ),
    (
        "panchromatic_reference_sample_spacing_m",
        "payload.optical.panchromatic-reference-sample-spacing",
        "m",
        1.0,
    ),
    (
        "multispectral_reference_sample_spacing_m",
        "payload.optical.multispectral-reference-sample-spacing",
        "m",
        4.0,
    ),
    (
        "multispectral_band_count",
        "payload.optical.multispectral-band-count",
        "1",
        4,
    ),
    (
        "acquisition_bits_per_sample",
        "payload.optical.acquisition-bits-per-sample",
        "bit/sample",
        12,
    ),
    (
        "acquisition_power_w",
        "payload.optical.acquisition-power",
        "W",
        100.0,
    ),
)


def _parameter(
    parameter_id: str,
    units: str,
    value: object,
) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by a focused unit test.",
        ),
    )


def _acquisition(**changes) -> OpticalAcquisitionConfig:
    values = {
        field_name: _parameter(parameter_id, units, value)
        for field_name, parameter_id, units, value in PARAMETER_CONTRACTS
    }
    values["simultaneous_pan_and_multispectral"] = True
    values.update(changes)
    return OpticalAcquisitionConfig(**values)


def _payload(
    acquisition: object | None = None,
) -> PayloadConfig:
    active_acquisition = _acquisition() if acquisition is None else acquisition
    return PayloadConfig(
        SubsystemConfigurationId("payload-b1"),
        PayloadFamily.OPTICAL_EO,
        (PayloadMode.PANCHROMATIC, PayloadMode.MULTISPECTRAL),
        active_acquisition,
    )


def test_optical_acquisition_has_exact_frozen_slotted_required_fields() -> None:
    assert tuple(field.name for field in fields(OpticalAcquisitionConfig)) == (
        "reference_nadir_swath_width_m",
        "panchromatic_reference_sample_spacing_m",
        "multispectral_reference_sample_spacing_m",
        "multispectral_band_count",
        "acquisition_bits_per_sample",
        "acquisition_power_w",
        "simultaneous_pan_and_multispectral",
    )
    config = _acquisition()
    assert not hasattr(config, "__dict__")
    assert OpticalAcquisitionConfig.__dataclass_params__.frozen
    with pytest.raises(FrozenInstanceError):
        config.acquisition_power_w = config.acquisition_power_w


def test_optical_acquisition_fields_have_no_defaults() -> None:
    for field in fields(OpticalAcquisitionConfig):
        assert field.default is MISSING
        assert field.default_factory is MISSING


@pytest.mark.parametrize(
    "field_name,parameter_id,units,_value",
    PARAMETER_CONTRACTS,
)
def test_parameters_use_exact_ids_units_and_retain_provenance(
    field_name,
    parameter_id,
    units,
    _value,
) -> None:
    parameter = getattr(_acquisition(), field_name)

    assert type(parameter) is ScalarParameter
    assert parameter.parameter_id == ParameterId(parameter_id)
    assert parameter.units == units
    assert parameter.provenance.classification is (
        ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
    )


@pytest.mark.parametrize(
    "field_name",
    (
        "reference_nadir_swath_width_m",
        "panchromatic_reference_sample_spacing_m",
        "multispectral_reference_sample_spacing_m",
        "acquisition_power_w",
    ),
)
@pytest.mark.parametrize("invalid", (0.0, -0.001))
def test_continuous_physical_parameters_must_be_positive(
    field_name,
    invalid,
) -> None:
    _, parameter_id, units, _ = next(
        contract for contract in PARAMETER_CONTRACTS
        if contract[0] == field_name
    )
    with pytest.raises(ValueError, match="greater than zero"):
        _acquisition(
            **{field_name: _parameter(parameter_id, units, invalid)}
        )


@pytest.mark.parametrize(
    "field_name,parameter_id,units",
    (
        (
            "multispectral_band_count",
            "payload.optical.multispectral-band-count",
            "1",
        ),
        (
            "acquisition_bits_per_sample",
            "payload.optical.acquisition-bits-per-sample",
            "bit/sample",
        ),
    ),
)
@pytest.mark.parametrize("invalid", (0, -1, 1.5))
def test_count_parameters_require_positive_exact_integral_values(
    field_name,
    parameter_id,
    units,
    invalid,
) -> None:
    with pytest.raises(ValueError):
        _acquisition(
            **{field_name: _parameter(parameter_id, units, invalid)}
        )


@pytest.mark.parametrize(
    "field_name,parameter_id,units",
    (
        (
            "multispectral_band_count",
            "payload.optical.multispectral-band-count",
            "1",
        ),
        (
            "acquisition_bits_per_sample",
            "payload.optical.acquisition-bits-per-sample",
            "bit/sample",
        ),
    ),
)
def test_count_parameters_reject_bool_even_after_nested_corruption(
    field_name,
    parameter_id,
    units,
) -> None:
    parameter = _parameter(parameter_id, units, 1)
    object.__setattr__(parameter, "value", True)

    with pytest.raises(TypeError):
        _acquisition(**{field_name: parameter})


@pytest.mark.parametrize("invalid", (0, 1, "true", None))
def test_simultaneous_acquisition_flag_requires_exact_bool(invalid) -> None:
    with pytest.raises(TypeError, match="boolean"):
        _acquisition(simultaneous_pan_and_multispectral=invalid)


def test_numpy_real_values_are_admitted_without_production_numpy() -> None:
    config = _acquisition(
        reference_nadir_swath_width_m=_parameter(
            "payload.optical.reference-nadir-swath-width",
            "m",
            np.float64(1000.0),
        ),
        multispectral_band_count=_parameter(
            "payload.optical.multispectral-band-count",
            "1",
            np.int64(4),
        ),
        acquisition_bits_per_sample=_parameter(
            "payload.optical.acquisition-bits-per-sample",
            "bit/sample",
            np.float64(12.0),
        ),
    )

    assert config.reference_nadir_swath_width_m.value == 1000.0
    assert config.multispectral_band_count.value == 4
    assert config.acquisition_bits_per_sample.value == 12.0


@pytest.mark.parametrize(
    "field_name,wrong_parameter_id,wrong_units",
    (
        (
            "reference_nadir_swath_width_m",
            "payload.optical.wrong-swath",
            "m",
        ),
        (
            "acquisition_power_w",
            "payload.optical.acquisition-power",
            "kW",
        ),
    ),
)
def test_wrong_parameter_identity_or_units_are_rejected(
    field_name,
    wrong_parameter_id,
    wrong_units,
) -> None:
    with pytest.raises(ValueError):
        _acquisition(
            **{
                field_name: _parameter(
                    wrong_parameter_id,
                    wrong_units,
                    1.0,
                )
            }
        )


def test_payload_config_owns_required_exact_acquisition_config() -> None:
    acquisition = _acquisition()
    payload = _payload(acquisition)

    assert tuple(field.name for field in fields(PayloadConfig)) == (
        "configuration_id",
        "payload_family",
        "supported_modes",
        "optical_acquisition",
    )
    assert payload.optical_acquisition is acquisition
    assert fields(PayloadConfig)[-1].default is MISSING
    with pytest.raises(TypeError):
        PayloadConfig(
            SubsystemConfigurationId("missing-acquisition"),
            PayloadFamily.OPTICAL_EO,
            (PayloadMode.PANCHROMATIC,),
        )
    with pytest.raises(TypeError, match="optical_acquisition"):
        _payload(object())


def test_payload_config_revalidates_corrupted_nested_acquisition() -> None:
    acquisition = _acquisition()
    object.__setattr__(
        acquisition.acquisition_power_w,
        "value",
        0.0,
    )

    with pytest.raises(ValueError, match="acquisition_power_w"):
        _payload(acquisition)


def test_spacecraft_configuration_owns_acquisition_transitively() -> None:
    spacecraft = build_demo_context().inputs.spacecraft_configuration

    assert type(spacecraft) is SpacecraftConfiguration
    assert type(spacecraft.payload) is PayloadConfig
    assert type(spacecraft.payload.optical_acquisition) is (
        OpticalAcquisitionConfig
    )
    assert spacecraft.payload.optical_acquisition.simultaneous_pan_and_multispectral


def test_b1_historical_state_and_checkpoint_schemas_are_unchanged() -> None:
    commit = "faae57a057623c396f7e628bd2e88f78de452815"
    state_source = subprocess.run(
        ["git", "show", f"{commit}:ops_sim/v5/state.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    checkpoint_source = subprocess.run(
        ["git", "show", f"{commit}:ops_sim/v5/checkpoint.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    state_tree = ast.parse(state_source)
    spacecraft = next(
        node
        for node in state_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SpacecraftState"
    )
    state_fields = tuple(
        node.target.id
        for node in spacecraft.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    )

    assert "CURRENT_CHECKPOINT_SCHEMA_VERSION = 3" in checkpoint_source
    assert state_fields == (
        "battery",
        "propulsion",
        "thermal",
        "degradation",
        "onboard",
    )
    assert "payload" not in state_fields
    assert "optical_acquisition" not in checkpoint_source


def test_state_checkpoint_and_observation_sources_are_unchanged() -> None:
    for relative_path in (
        "ops_sim/v5/state.py",
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/observation.py",
    ):
        before_slice = subprocess.run(
            [
                "git",
                "show",
                f"e79edd3ea3b232b0d4881f8b52b56a5e8b52fce6:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        after_slice = subprocess.run(
            [
                "git",
                "show",
                f"faae57a057623c396f7e628bd2e88f78de452815:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert after_slice == before_slice


def test_payload_modes_remain_product_output_view_capabilities() -> None:
    assert tuple(PayloadMode) == (
        PayloadMode.PANCHROMATIC,
        PayloadMode.MULTISPECTRAL,
    )
    assert "product/output-view" in PayloadMode.__doc__
    config = _acquisition(simultaneous_pan_and_multispectral=True)
    assert _payload(config).supported_modes == (
        PayloadMode.PANCHROMATIC,
        PayloadMode.MULTISPECTRAL,
    )


def test_payload_config_has_only_configuration_dependencies() -> None:
    tree = ast.parse(
        PAYLOAD_CONFIG_PATH.read_text(encoding="utf-8"),
        filename=str(PAYLOAD_CONFIG_PATH),
    )
    imported_modules = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert imported_modules <= {
        "__future__",
        "dataclasses",
        "math",
        "numbers",
        "ids",
        "parameters",
    }


def test_b1_adds_no_runtime_physics_results_or_forbidden_equations() -> None:
    source = PAYLOAD_CONFIG_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PAYLOAD_CONFIG_PATH))
    public_class_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    }
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    numeric_constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and type(node.value) in {int, float}
    }

    assert public_class_names == {"OpticalAcquisitionConfig"}
    assert not any(name.startswith("compute_") for name in function_names)
    assert not any(name.endswith(("Input", "Result")) for name in public_class_names)
    assert {90, 180, 270}.isdisjoint(numeric_constants)
    for prohibited in (
        "compression_ratio",
        "compression_algorithm",
        "data_volume",
        "payload_energy",
        "footprint",
        "imaging_duration",
    ):
        assert prohibited not in source
    assert not any(
        isinstance(node, ast.BinOp)
        and isinstance(
            node.op,
            (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow),
        )
        for node in ast.walk(tree)
    )


def test_configuration_does_not_physically_branch_on_payload_mode() -> None:
    tree = ast.parse(
        CONFIGURATION_PATH.read_text(encoding="utf-8"),
        filename=str(CONFIGURATION_PATH),
    )
    assert not any(
        isinstance(node, ast.If)
        and any(
            isinstance(child, ast.Attribute)
            and child.attr in {"PANCHROMATIC", "MULTISPECTRAL"}
            for child in ast.walk(node.test)
        )
        for node in ast.walk(tree)
    )


def test_payload_config_module_has_exact_exports() -> None:
    from ops_sim.v5 import payload_config

    assert payload_config.__all__ == ["OpticalAcquisitionConfig"]


def test_d163_through_d168_and_b1_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    lower = sources.lower()

    for number in range(163, 169):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D162 ") < decisions.index("## D163 ")
    assert "WMO OSCAR" in sources
    assert "90 W" in sources
    assert "180 W" in sources
    assert "GISTDA" in sources
    assert "THEOS-2" in sources
    assert "multiple" in lower and "retina" in lower
    assert "compression" in lower
    assert "reference sample" in lower
    assert "270 Mbit/s" in sources
