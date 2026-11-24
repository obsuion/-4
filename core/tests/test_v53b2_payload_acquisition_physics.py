"""Pure optical acquisition power and sample-grid physics for V5.3B2."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from enum import Enum
from math import isfinite
from pathlib import Path

import numpy as np
import pytest

from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.ids import ParameterId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
    OpticalAcquisitionResult,
    compute_optical_acquisition,
)
from ops_sim.v5.payload_config import OpticalAcquisitionConfig
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_PATH = ROOT / "ops_sim" / "v5" / "payload.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
SMALLEST_POSITIVE_FLOAT = float.fromhex("0x0.0000000000001p-1022")


def _parameter(parameter_id: str, units: str, value: object) -> ScalarParameter:
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


def _config(
    *,
    reference_swath_m: object = 20_000.0,
    pan_spacing_m: object = 1.0,
    ms_spacing_m: object = 4.0,
    ms_band_count: object = 4,
    bits_per_sample: object = 12,
    acquisition_power_w: object = 120.0,
    simultaneous: bool = True,
) -> OpticalAcquisitionConfig:
    return OpticalAcquisitionConfig(
        _parameter(
            "payload.optical.reference-nadir-swath-width",
            "m",
            reference_swath_m,
        ),
        _parameter(
            "payload.optical.panchromatic-reference-sample-spacing",
            "m",
            pan_spacing_m,
        ),
        _parameter(
            "payload.optical.multispectral-reference-sample-spacing",
            "m",
            ms_spacing_m,
        ),
        _parameter(
            "payload.optical.multispectral-band-count",
            "1",
            ms_band_count,
        ),
        _parameter(
            "payload.optical.acquisition-bits-per-sample",
            "bit/sample",
            bits_per_sample,
        ),
        _parameter(
            "payload.optical.acquisition-power",
            "W",
            acquisition_power_w,
        ),
        simultaneous,
    )


def _input(
    *,
    width_m: object = 20_000.0,
    length_m: object = 20_000.0,
    duration_seconds: object = 30,
    selection: object = (
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL
    ),
) -> OpticalAcquisitionInput:
    return OpticalAcquisitionInput(
        width_m,
        length_m,
        duration_seconds,
        selection,
    )


def _compute(
    *,
    config: OpticalAcquisitionConfig | None = None,
    acquisition_input: OpticalAcquisitionInput | None = None,
) -> OpticalAcquisitionResult:
    return compute_optical_acquisition(
        _config() if config is None else config,
        _input() if acquisition_input is None else acquisition_input,
    )


def test_channel_selection_enum_has_exact_physical_values() -> None:
    assert tuple(OpticalAcquisitionChannelSelection) == (
        OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY,
        OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY,
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
    )
    assert tuple(item.value for item in OpticalAcquisitionChannelSelection) == (
        "panchromatic-only",
        "multispectral-only",
        "pan-and-multispectral",
    )


def test_input_and_result_have_exact_frozen_slotted_required_fields() -> None:
    contracts = {
        OpticalAcquisitionInput: (
            "effective_cross_track_width_m",
            "effective_along_track_length_m",
            "imaging_duration_seconds",
            "channel_selection",
        ),
        OpticalAcquisitionResult: (
            "footprint_area_m2",
            "panchromatic_equivalent_samples",
            "multispectral_equivalent_samples_per_band",
            "multispectral_equivalent_samples_total",
            "total_equivalent_samples",
            "uncompressed_equivalent_bits",
            "uncompressed_equivalent_bytes",
            "requested_acquisition_power_w",
            "acquisition_energy_wh",
        ),
    }
    instances = (_input(), _compute())

    for domain_type, instance in zip(contracts, instances):
        assert tuple(field.name for field in fields(domain_type)) == (
            contracts[domain_type]
        )
        assert domain_type.__dataclass_params__.frozen
        assert not hasattr(instance, "__dict__")
        assert all(
            field.default is MISSING and field.default_factory is MISSING
            for field in fields(domain_type)
        )
        with pytest.raises(FrozenInstanceError):
            setattr(instance, fields(domain_type)[0].name, None)


@pytest.mark.parametrize(
    ("field_name", "invalid", "error_type"),
    (
        ("width_m", 0.0, ValueError),
        ("width_m", -1.0, ValueError),
        ("width_m", True, TypeError),
        ("width_m", float("nan"), ValueError),
        ("width_m", float("inf"), ValueError),
        ("width_m", "1", TypeError),
        ("length_m", 0.0, ValueError),
        ("length_m", -1.0, ValueError),
        ("length_m", False, TypeError),
        ("length_m", float("-inf"), ValueError),
    ),
)
def test_input_rejects_invalid_effective_dimensions(
    field_name,
    invalid,
    error_type,
) -> None:
    with pytest.raises(error_type):
        _input(**{field_name: invalid})


@pytest.mark.parametrize(
    ("duration", "error_type"),
    (
        (0, ValueError),
        (-1, ValueError),
        (True, TypeError),
        (60.0, TypeError),
        (np.int64(60), TypeError),
        ("60", TypeError),
    ),
)
def test_input_requires_exact_positive_python_integer_duration(
    duration,
    error_type,
) -> None:
    with pytest.raises(error_type):
        _input(duration_seconds=duration)


@pytest.mark.parametrize(
    "invalid",
    (
        "pan-and-multispectral",
        object(),
        Enum("OtherSelection", {"PAN": "pan"}).PAN,
    ),
)
def test_input_requires_exact_channel_selection_enum(invalid) -> None:
    with pytest.raises(TypeError, match="channel_selection"):
        _input(selection=invalid)


def test_kazeosat_like_twenty_by_twenty_kilometre_hand_calculation() -> None:
    result = _compute()

    assert result.footprint_area_m2 == 400_000_000
    assert result.panchromatic_equivalent_samples == 400_000_000
    assert result.multispectral_equivalent_samples_per_band == 25_000_000
    assert result.multispectral_equivalent_samples_total == 100_000_000
    assert result.total_equivalent_samples == 500_000_000
    assert result.uncompressed_equivalent_bits == 6_000_000_000
    assert result.uncompressed_equivalent_bytes == 750_000_000


def test_hand_result_is_fifteen_megabits_per_square_kilometre() -> None:
    result = _compute()
    footprint_area_km2 = 20 * 20
    independently_derived_mbit_per_km2 = (
        6_000_000_000 / 1_000_000 / footprint_area_km2
    )

    assert independently_derived_mbit_per_km2 == 15
    assert (
        result.uncompressed_equivalent_bits
        / 1_000_000
        / footprint_area_km2
    ) == 15


def test_hand_result_is_decimal_750_mb_sample_grid_proxy() -> None:
    result = _compute()
    independently_derived_bytes = 6_000_000_000 / 8

    assert independently_derived_bytes == 750_000_000
    assert result.uncompressed_equivalent_bytes == independently_derived_bytes
    assert result.uncompressed_equivalent_bytes / 1_000_000 == 750


def test_synthetic_120_w_for_30_seconds_is_one_wh() -> None:
    result = _compute()
    independently_derived_energy_wh = 120 * 30 / 3600

    assert independently_derived_energy_wh == 1
    assert result.requested_acquisition_power_w == 120
    assert result.acquisition_energy_wh == independently_derived_energy_wh


def test_90_w_for_60_seconds_is_one_point_five_wh_arithmetic() -> None:
    result = _compute(
        config=_config(acquisition_power_w=90.0),
        acquisition_input=_input(duration_seconds=60),
    )
    independently_derived_energy_wh = 90 * 60 / 3600

    assert independently_derived_energy_wh == 1.5
    assert result.acquisition_energy_wh == independently_derived_energy_wh


def test_pan_only_uses_only_pan_sample_grid() -> None:
    config = _config(
        pan_spacing_m=2.0,
        ms_spacing_m=4.0,
        ms_band_count=3,
        bits_per_sample=10,
        simultaneous=False,
    )
    result = _compute(
        config=config,
        acquisition_input=_input(
            width_m=8.0,
            length_m=8.0,
            selection=OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY,
        ),
    )

    assert result.panchromatic_equivalent_samples == 16
    assert result.multispectral_equivalent_samples_per_band == 0
    assert result.multispectral_equivalent_samples_total == 0
    assert result.total_equivalent_samples == 16
    assert result.uncompressed_equivalent_bits == 160


def test_ms_only_uses_every_multispectral_band_and_no_pan() -> None:
    config = _config(
        pan_spacing_m=2.0,
        ms_spacing_m=4.0,
        ms_band_count=3,
        bits_per_sample=10,
        simultaneous=False,
    )
    result = _compute(
        config=config,
        acquisition_input=_input(
            width_m=8.0,
            length_m=8.0,
            selection=OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY,
        ),
    )

    assert result.panchromatic_equivalent_samples == 0
    assert result.multispectral_equivalent_samples_per_band == 4
    assert result.multispectral_equivalent_samples_total == 12
    assert result.total_equivalent_samples == 12
    assert result.uncompressed_equivalent_bits == 120


def test_combined_selection_is_exact_pan_plus_all_ms_bands() -> None:
    config = _config(
        pan_spacing_m=2.0,
        ms_spacing_m=4.0,
        ms_band_count=3,
        bits_per_sample=10,
        simultaneous=True,
    )
    result = _compute(
        config=config,
        acquisition_input=_input(width_m=8.0, length_m=8.0),
    )

    assert result.panchromatic_equivalent_samples == 16
    assert result.multispectral_equivalent_samples_per_band == 4
    assert result.multispectral_equivalent_samples_total == 12
    assert result.total_equivalent_samples == 16 + 3 * 4
    assert result.uncompressed_equivalent_bits == (16 + 3 * 4) * 10


@pytest.mark.parametrize(
    "selection",
    (
        OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY,
        OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY,
    ),
)
def test_simultaneous_configuration_rejects_single_family_selection(
    selection,
) -> None:
    with pytest.raises(ValueError, match="simultaneous"):
        _compute(acquisition_input=_input(selection=selection))


def test_non_simultaneous_configuration_rejects_combined_selection() -> None:
    with pytest.raises(ValueError, match="non-simultaneous"):
        _compute(config=_config(simultaneous=False))


@pytest.mark.parametrize(
    "selection",
    (
        OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY,
        OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY,
    ),
)
def test_non_simultaneous_configuration_admits_each_single_family(
    selection,
) -> None:
    result = _compute(
        config=_config(simultaneous=False),
        acquisition_input=_input(selection=selection),
    )

    assert result.total_equivalent_samples > 0


def test_sample_equivalent_counts_remain_continuous_without_rounding() -> None:
    result = _compute(
        config=_config(
            pan_spacing_m=2.0,
            ms_spacing_m=4.0,
            ms_band_count=3,
        ),
        acquisition_input=_input(width_m=3.0, length_m=5.0),
    )

    assert result.footprint_area_m2 == 15
    assert result.panchromatic_equivalent_samples == 3.75
    assert result.multispectral_equivalent_samples_per_band == 0.9375
    assert result.multispectral_equivalent_samples_total == 2.8125
    assert result.total_equivalent_samples == 6.5625


def test_reference_nadir_swath_is_not_an_implicit_width_cap() -> None:
    result = _compute(
        config=_config(reference_swath_m=1000.0),
        acquisition_input=_input(width_m=1200.0, length_m=10.0),
    )

    assert result.footprint_area_m2 == 12_000
    assert result.panchromatic_equivalent_samples == 12_000


def test_compute_requires_exact_types_and_revalidates_nested_values() -> None:
    with pytest.raises(TypeError, match="config"):
        compute_optical_acquisition(object(), _input())
    with pytest.raises(TypeError, match="acquisition_input"):
        compute_optical_acquisition(_config(), object())

    config = _config()
    object.__setattr__(config.acquisition_power_w, "value", 0.0)
    with pytest.raises(ValueError, match="acquisition_power_w"):
        compute_optical_acquisition(config, _input())

    acquisition_input = _input()
    object.__setattr__(acquisition_input, "effective_cross_track_width_m", 0.0)
    with pytest.raises(ValueError, match="effective_cross_track_width_m"):
        compute_optical_acquisition(_config(), acquisition_input)


def test_numpy_reals_execute_and_results_are_finite_builtins() -> None:
    result = _compute(
        config=_config(
            pan_spacing_m=np.float64(1.0),
            ms_spacing_m=np.float64(4.0),
            ms_band_count=np.int64(4),
            bits_per_sample=np.int64(12),
            acquisition_power_w=np.float64(120.0),
        ),
        acquisition_input=_input(
            width_m=np.float64(20_000.0),
            length_m=np.int64(20_000),
        ),
    )

    assert all(
        type(getattr(result, field.name)) in {int, float}
        and isfinite(getattr(result, field.name))
        for field in fields(OpticalAcquisitionResult)
    )


def test_compute_is_pure_and_mutates_no_configuration_input_or_context() -> None:
    context = build_demo_context()
    config = context.inputs.spacecraft_configuration.payload.optical_acquisition
    acquisition_input = _input()
    context_before = deepcopy(context)
    config_before = deepcopy(config)
    input_before = deepcopy(acquisition_input)
    state_reference = context.spacecraft_state
    storage_reference = context.inputs.spacecraft_configuration.storage
    thermal_reference = context.inputs.spacecraft_configuration.thermal

    compute_optical_acquisition(config, acquisition_input)

    assert context == context_before
    assert config == config_before
    assert acquisition_input == input_before
    assert context.spacecraft_state is state_reference
    assert context.inputs.spacecraft_configuration.storage is storage_reference
    assert context.inputs.spacecraft_configuration.thermal is thermal_reference


def test_finite_addition_significance_loss_is_not_a_domain_failure() -> None:
    result = _compute(
        config=_config(
            pan_spacing_m=1.0,
            ms_spacing_m=1.0e154,
            ms_band_count=1,
            bits_per_sample=1,
        ),
        acquisition_input=_input(width_m=1.0e154, length_m=1.0e154),
    )

    assert result.panchromatic_equivalent_samples == 1.0e308
    assert result.multispectral_equivalent_samples_total == 1.0
    assert result.total_equivalent_samples == 1.0e308


def test_area_and_data_overflow_fail_intentionally() -> None:
    with pytest.raises(ValueError, match="footprint_area_m2|finite"):
        _compute(acquisition_input=_input(width_m=1.0e308, length_m=2.0))

    with pytest.raises(ValueError, match="uncompressed_equivalent_bits|finite"):
        _compute(config=_config(bits_per_sample=1.0e308))


def test_nonzero_product_and_quotient_underflow_fail_intentionally() -> None:
    with pytest.raises(ValueError, match="nonzero product"):
        _compute(
            acquisition_input=_input(
                width_m=SMALLEST_POSITIVE_FLOAT,
                length_m=0.5,
            )
        )

    with pytest.raises(ValueError, match="nonzero quotient"):
        _compute(
            acquisition_input=_input(
                width_m=SMALLEST_POSITIVE_FLOAT,
                length_m=1.0,
            ),
            config=_config(pan_spacing_m=2.0, ms_spacing_m=2.0),
        )


def test_huge_duration_fails_as_an_unrepresentable_energy_factor() -> None:
    acquisition_input = _input(duration_seconds=10**400)

    with pytest.raises(ValueError, match="represented|finite"):
        _compute(acquisition_input=acquisition_input)


def test_result_constructor_rejects_invalid_values_and_identities() -> None:
    result = _compute()
    with pytest.raises(TypeError):
        replace(result, footprint_area_m2=True)
    with pytest.raises(ValueError):
        replace(result, acquisition_energy_wh=float("nan"))
    with pytest.raises(ValueError, match="total_equivalent_samples"):
        replace(result, total_equivalent_samples=result.total_equivalent_samples + 1)
    with pytest.raises(ValueError, match="divided by eight"):
        replace(
            result,
            uncompressed_equivalent_bytes=(
                result.uncompressed_equivalent_bytes + 1
            ),
        )


def test_payload_module_has_only_pure_configuration_dependencies() -> None:
    tree = ast.parse(
        PAYLOAD_PATH.read_text(encoding="utf-8"),
        filename=str(PAYLOAD_PATH),
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
        "enum",
        "math",
        "numbers",
        "payload_config",
    }


def test_production_has_no_orbit_opportunity_mode_or_subsystem_coupling() -> None:
    source = PAYLOAD_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PAYLOAD_PATH))
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    prohibited = {
        "ObservationOpportunity",
        "PayloadMode",
        "SimulationEngine",
        "SimulationContext",
        "SpacecraftState",
        "CheckpointState",
        "PowerLoadBreakdown",
        "EPSIntervalResult",
        "ThermalHeatSourceInputs",
        "StorageConfig",
        "orbital_velocity",
        "ground_track_velocity",
        "line_rate",
        "compression_ratio",
        "compression_algorithm",
        "retained_heat_fraction",
        "served_payload_power",
        "isclose",
        "round",
        "clip",
        "clamp",
    }

    assert identifiers.isdisjoint(prohibited)
    assert "270 Mbit/s" not in source
    assert not any(
        isinstance(node, ast.Constant)
        and type(node.value) in {int, float}
        and node.value in {16, 270, 270_000_000}
        for node in ast.walk(tree)
    )


def test_public_exports_are_exact_and_narrow() -> None:
    from ops_sim.v5 import payload

    assert payload.__all__ == [
        "OpticalAcquisitionChannelSelection",
        "OpticalAcquisitionInput",
        "OpticalAcquisitionResult",
        "compute_optical_acquisition",
    ]


def test_d169_through_d177_are_recorded_once_after_d168() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")

    for number in range(169, 178):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D168 ") < decisions.index("## D169 ")


def test_source_register_records_b2_level_one_proxy_equations_and_example() -> None:
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s005 = sources.partition("### S005 ")[2].partition("### S006 ")[0]
    normalized = " ".join(s005.split())

    assert "DERIVED LEVEL-1 SAMPLE-GRID PROXY" in s005
    assert "15 Mbit/km^2" in s005
    assert "750 MB" in s005
    assert "20 km" in s005
    assert "not a measured onboard data volume" in normalized
    assert "A = W_eff * L_eff" in s005
    assert "E_requested = P_requested * t / 3600" in s005
