"""Optical-acquisition EPS evaluation and service bounds for V5.3E1."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from enum import Enum
from inspect import Parameter, signature
from math import isfinite
from pathlib import Path
import subprocess

import numpy as np
import pytest

import ops_sim.v5.imaging_resources as resource_module
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.configuration import (
    BatteryConfig,
    EPSConfig,
    SolarArrayConfig,
)
from ops_sim.v5.eps_capability import compute_eps_capability
from ops_sim.v5.eps_system import (
    EPSIntervalInputs,
    EPSIntervalResult,
    compute_eps_interval_transition,
)
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    ADCSSlewAnchorId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
    SubsystemConfigurationId,
)
from ops_sim.v5.imaging_feasibility import (
    ObservationAcquisitionCandidate,
    ObservationAcquisitionEvaluationResult,
    evaluate_observation_acquisition,
)
from ops_sim.v5.imaging_resources import (
    AcquisitionEPSIntervalEnvironment,
    AcquisitionServiceBounds,
    AcquisitionServiceStatus,
    ObservationAcquisitionEPSResult,
    evaluate_observation_acquisition_eps,
)
from ops_sim.v5.observation import ObservationOpportunity, ObservationPointing
from ops_sim.v5.observation_feasibility import (
    ObservationManeuverCandidate,
    ObservationSequenceFeasibilityReason,
    ScheduledObservationExecution,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
)
from ops_sim.v5.payload_config import OpticalAcquisitionConfig
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import (
    BatteryDegradationState,
    BatteryState,
    DegradationState,
    SolarDegradationState,
)


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_PATH = ROOT / "ops_sim" / "v5" / "imaging_resources.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
LOAD_FIELDS = (
    "base_bus_w",
    "obc_w",
    "adcs_w",
    "payload_w",
    "communications_w",
    "thermal_control_w",
    "propulsion_w",
)


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


def _anchor(
    anchor_value: str,
    angle_deg: object,
    elapsed_seconds: object,
) -> BoresightSlewTimeAnchor:
    prefix = f"adcs.slew-envelope.{anchor_value}"
    return BoresightSlewTimeAnchor(
        ADCSSlewAnchorId(anchor_value),
        _parameter(f"{prefix}.angular-separation", "deg", angle_deg),
        _parameter(f"{prefix}.elapsed-time", "s", elapsed_seconds),
    )


def _agile_config(
    *,
    maximum_view_angle_deg: object = 35.0,
    anchors: tuple[BoresightSlewTimeAnchor, ...] | None = None,
) -> AgilePointingConfig:
    return AgilePointingConfig(
        _parameter(
            "adcs.pointing.maximum-view-angle-from-nadir",
            "deg",
            maximum_view_angle_deg,
        ),
        _parameter("adcs.pointing.post-slew-settling-time", "s", 5.0),
        (
            (_anchor("zero", 0.0, 0.0), _anchor("ninety", 90.0, 80.0))
            if anchors is None
            else anchors
        ),
    )


def _optical_config(
    *,
    acquisition_power_w: object = 90.0,
    simultaneous: bool = True,
) -> OpticalAcquisitionConfig:
    return OpticalAcquisitionConfig(
        _parameter(
            "payload.optical.reference-nadir-swath-width", "m", 100.0
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
            "payload.optical.acquisition-bits-per-sample", "bit/sample", 12
        ),
        _parameter(
            "payload.optical.acquisition-power", "W", acquisition_power_w
        ),
        simultaneous,
    )


def _eps_config(
    *,
    battery_capacity_wh: object = 1000.0,
    max_charge_w: object = 1000.0,
    max_discharge_w: object = 1000.0,
    solar_w: object = 1000.0,
) -> EPSConfig:
    return EPSConfig(
        SubsystemConfigurationId("e1-eps"),
        BatteryConfig(
            SubsystemConfigurationId("e1-battery"),
            _parameter("eps.battery.nominal-energy", "Wh", battery_capacity_wh),
            _parameter("eps.battery.charge-efficiency", "1", 1.0),
            _parameter("eps.battery.discharge-efficiency", "1", 1.0),
            _parameter("eps.battery.max-charge-input-power", "W", max_charge_w),
            _parameter(
                "eps.battery.max-discharge-output-power",
                "W",
                max_discharge_w,
            ),
        ),
        SolarArrayConfig(
            SubsystemConfigurationId("e1-solar"),
            _parameter("eps.solar-array.nominal-generation", "W", solar_w),
        ),
    )


def _degradation(
    *,
    battery_retention: object = 1.0,
    solar_retention: object = 1.0,
) -> DegradationState:
    return DegradationState(
        BatteryDegradationState(battery_retention, 0.0),
        SolarDegradationState(solar_retention),
    )


def _opportunity(
    value: str,
    *,
    window_start_seconds: int,
    window_end_seconds: int,
    duration_seconds: int = 20,
    view_angle_deg: object = 10.0,
) -> ObservationOpportunity:
    return ObservationOpportunity(
        ObservationOpportunityId(value),
        ImagingRequestId(f"request-{value}"),
        window_start_seconds,
        window_end_seconds,
        duration_seconds,
        ObservationPointing(view_angle_deg, 0.0),
    )


def _direction(
    x: object = 0.0,
    y: object = 0.0,
    z: object = 1.0,
    *,
    frame_value: str = "e1-common-frame",
) -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId(frame_value),
        x,
        y,
        z,
    )


def _previous_execution(
    *,
    direction: CommonFrameBoresightDirection | None = None,
    view_angle_deg: object = 10.0,
) -> ScheduledObservationExecution:
    candidate = ObservationManeuverCandidate(
        _opportunity(
            "previous",
            window_start_seconds=0,
            window_end_seconds=60,
            view_angle_deg=view_angle_deg,
        ),
        _direction() if direction is None else direction,
    )
    return ScheduledObservationExecution(candidate, 0)


def _next_candidate(
    *,
    direction: CommonFrameBoresightDirection | None = None,
    duration_seconds: int = 20,
    view_angle_deg: object = 10.0,
    window_end_seconds: int = 200,
    channel_selection: OpticalAcquisitionChannelSelection = (
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL
    ),
) -> ObservationAcquisitionCandidate:
    opportunity = _opportunity(
        "next",
        window_start_seconds=100,
        window_end_seconds=window_end_seconds,
        duration_seconds=duration_seconds,
        view_angle_deg=view_angle_deg,
    )
    return ObservationAcquisitionCandidate(
        ObservationManeuverCandidate(
            opportunity,
            _direction() if direction is None else direction,
        ),
        OpticalAcquisitionInput(
            20.0,
            40.0,
            duration_seconds,
            channel_selection,
        ),
    )


def _loads(
    *,
    base_bus_w: object = 0.0,
    obc_w: object = 0.0,
    adcs_w: object = 0.0,
    payload_w: object = 0.0,
    communications_w: object = 0.0,
    thermal_control_w: object = 0.0,
    propulsion_w: object = 0.0,
) -> PowerLoadBreakdown:
    return PowerLoadBreakdown(
        base_bus_w,
        obc_w,
        adcs_w,
        payload_w,
        communications_w,
        thermal_control_w,
        propulsion_w,
    )


def _environment(
    *,
    sunlit: bool = False,
    incidence_angle_deg: object = 0.0,
    loads: PowerLoadBreakdown | None = None,
) -> AcquisitionEPSIntervalEnvironment:
    return AcquisitionEPSIntervalEnvironment(
        sunlit,
        incidence_angle_deg,
        _loads() if loads is None else loads,
    )


def _evaluate(
    *,
    agile_config: AgilePointingConfig | None = None,
    optical_config: OpticalAcquisitionConfig | None = None,
    eps_config: EPSConfig | None = None,
    battery_state: BatteryState | None = None,
    degradation_state: DegradationState | None = None,
    previous_execution: ScheduledObservationExecution | None = None,
    next_candidate: ObservationAcquisitionCandidate | None = None,
    environment: AcquisitionEPSIntervalEnvironment | None = None,
) -> ObservationAcquisitionEPSResult:
    return evaluate_observation_acquisition_eps(
        _agile_config() if agile_config is None else agile_config,
        _optical_config() if optical_config is None else optical_config,
        _eps_config() if eps_config is None else eps_config,
        BatteryState(500.0) if battery_state is None else battery_state,
        _degradation() if degradation_state is None else degradation_state,
        (
            _previous_execution()
            if previous_execution is None
            else previous_execution
        ),
        _next_candidate() if next_candidate is None else next_candidate,
        _environment() if environment is None else environment,
    )


def test_service_status_has_exact_three_string_values() -> None:
    assert issubclass(AcquisitionServiceStatus, str)
    assert issubclass(AcquisitionServiceStatus, Enum)
    assert tuple(item.value for item in AcquisitionServiceStatus) == (
        "fully-served",
        "full-service-impossible",
        "service-allocation-required",
    )


def test_e1_records_have_exact_frozen_slotted_required_fields() -> None:
    result = _evaluate()
    contracts = {
        AcquisitionEPSIntervalEnvironment: (
            "sunlit",
            "incidence_angle_deg",
            "non_acquisition_loads",
        ),
        AcquisitionServiceBounds: (
            "minimum_served_acquisition_power_w",
            "maximum_served_acquisition_power_w",
            "minimum_served_acquisition_energy_wh",
            "maximum_served_acquisition_energy_wh",
            "status",
        ),
        ObservationAcquisitionEPSResult: (
            "acquisition_evaluation",
            "eps_inputs",
            "eps_capability_result",
            "eps_result",
            "service_bounds",
        ),
    }
    instances = (
        _environment(),
        result.service_bounds,
        result,
    )

    for domain_type, instance in zip(contracts, instances):
        assert tuple(field.name for field in fields(domain_type)) == contracts[
            domain_type
        ]
        assert domain_type.__dataclass_params__.frozen
        assert not hasattr(instance, "__dict__")
        assert all(
            field.default is MISSING and field.default_factory is MISSING
            for field in fields(domain_type)
        )
        with pytest.raises(FrozenInstanceError):
            setattr(instance, fields(domain_type)[0].name, None)


def test_environment_retains_eps_geometry_validation_and_revalidates_loads() -> None:
    loads = _loads(payload_w=15.0)
    environment = AcquisitionEPSIntervalEnvironment(True, 180.0, loads)

    assert environment.sunlit is True
    assert environment.incidence_angle_deg == 180.0
    assert environment.non_acquisition_loads is loads
    with pytest.raises(TypeError, match="sunlit"):
        AcquisitionEPSIntervalEnvironment(1, 0.0, loads)
    with pytest.raises(ValueError, match="between zero and 180"):
        AcquisitionEPSIntervalEnvironment(True, 180.1, loads)
    with pytest.raises(TypeError, match="non_acquisition_loads"):
        AcquisitionEPSIntervalEnvironment(True, 0.0, object())

    object.__setattr__(loads, "payload_w", -1.0)
    with pytest.raises(ValueError, match="payload_w"):
        replace(environment)


def test_service_bounds_require_builtin_finite_ordered_values_and_enum() -> None:
    valid = AcquisitionServiceBounds(
        1.0,
        2.0,
        3.0,
        4.0,
        AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED,
    )
    with pytest.raises(TypeError, match="built-in"):
        replace(valid, minimum_served_acquisition_power_w=np.float64(1.0))
    with pytest.raises(ValueError, match="finite"):
        replace(valid, maximum_served_acquisition_energy_wh=float("inf"))
    with pytest.raises(ValueError, match="minimum served acquisition power"):
        replace(valid, minimum_served_acquisition_power_w=3.0)
    with pytest.raises(ValueError, match="minimum served acquisition energy"):
        replace(valid, minimum_served_acquisition_energy_wh=5.0)
    with pytest.raises(TypeError, match="status"):
        replace(valid, status="service-allocation-required")


@pytest.mark.parametrize(
    "argument_name",
    (
        "agile_pointing_config",
        "optical_acquisition_config",
        "eps_config",
        "battery_state",
        "degradation_state",
        "previous_execution",
        "next_candidate",
        "environment",
    ),
)
def test_public_function_requires_exact_top_level_types(argument_name) -> None:
    values = {
        "agile_pointing_config": _agile_config(),
        "optical_acquisition_config": _optical_config(),
        "eps_config": _eps_config(),
        "battery_state": BatteryState(500.0),
        "degradation_state": _degradation(),
        "previous_execution": _previous_execution(),
        "next_candidate": _next_candidate(),
        "environment": _environment(),
    }
    values[argument_name] = object()

    with pytest.raises(TypeError, match=argument_name):
        evaluate_observation_acquisition_eps(**values)


def test_public_function_revalidates_inputs_before_d(monkeypatch) -> None:
    monkeypatch.setattr(
        resource_module,
        "evaluate_observation_acquisition",
        lambda *args: pytest.fail("D must not be reached"),
    )
    loads = _loads()
    environment = _environment(loads=loads)
    object.__setattr__(loads, "base_bus_w", -1.0)

    with pytest.raises(ValueError, match="base_bus_w"):
        evaluate_observation_acquisition_eps(
            _agile_config(),
            _optical_config(),
            _eps_config(),
            BatteryState(500.0),
            _degradation(),
            _previous_execution(),
            _next_candidate(),
            environment,
        )


def test_d_capability_and_eps_are_each_called_exactly_once(monkeypatch) -> None:
    agile = _agile_config()
    optical = _optical_config()
    eps_config = _eps_config()
    battery = BatteryState(500.0)
    degradation = _degradation()
    previous = _previous_execution()
    candidate = _next_candidate(duration_seconds=23)
    environment = _environment(sunlit=True, incidence_angle_deg=60.0)
    original_d = resource_module.evaluate_observation_acquisition
    original_capability = resource_module.compute_eps_capability
    original_eps = resource_module.compute_eps_interval_transition
    calls = {"d": 0, "capability": 0, "eps": 0}

    def d_call(config, payload_config, execution, active_candidate):
        calls["d"] += 1
        assert config is agile
        assert payload_config is optical
        assert execution is previous
        assert active_candidate is candidate
        return original_d(config, payload_config, execution, active_candidate)

    def capability_call(config, active_degradation):
        calls["capability"] += 1
        assert config is eps_config
        assert active_degradation is degradation
        return original_capability(config, active_degradation)

    def eps_call(state, config, inputs, *, dt_seconds, capability):
        calls["eps"] += 1
        assert state is battery
        assert config is eps_config
        assert inputs.sunlit is environment.sunlit
        assert inputs.incidence_angle_deg is environment.incidence_angle_deg
        assert dt_seconds == 23
        return original_eps(
            state,
            config,
            inputs,
            dt_seconds=dt_seconds,
            capability=capability,
        )

    monkeypatch.setattr(resource_module, "evaluate_observation_acquisition", d_call)
    monkeypatch.setattr(resource_module, "compute_eps_capability", capability_call)
    monkeypatch.setattr(resource_module, "compute_eps_interval_transition", eps_call)

    result = evaluate_observation_acquisition_eps(
        agile,
        optical,
        eps_config,
        battery,
        degradation,
        previous,
        candidate,
        environment,
    )

    assert calls == {"d": 1, "capability": 1, "eps": 1}
    assert result.eps_result is not None
    assert result.eps_result.battery.dt_seconds == 23


def test_d_infeasibility_short_circuits_capability_and_eps(monkeypatch) -> None:
    candidate = _next_candidate(view_angle_deg=36.0)
    monkeypatch.setattr(
        resource_module,
        "compute_eps_capability",
        lambda *args: pytest.fail("capability must not be computed"),
    )
    monkeypatch.setattr(
        resource_module,
        "compute_eps_interval_transition",
        lambda *args, **kwargs: pytest.fail("EPS must not be computed"),
    )

    result = _evaluate(next_candidate=candidate)

    assert result.acquisition_evaluation.feasible is False
    assert result.acquisition_evaluation.sequence_result.reason is (
        ObservationSequenceFeasibilityReason.NEXT_VIEW_LIMIT_EXCEEDED
    )
    assert result.eps_inputs is None
    assert result.eps_capability_result is None
    assert result.eps_result is None
    assert result.service_bounds is None


def test_d_frame_mismatch_exception_propagates() -> None:
    with pytest.raises(ValueError, match="same frame_id"):
        _evaluate(
            previous_execution=_previous_execution(
                direction=_direction(frame_value="frame-a")
            ),
            next_candidate=_next_candidate(
                direction=_direction(frame_value="frame-b")
            ),
        )


def test_c2_out_of_envelope_exception_propagates() -> None:
    agile = _agile_config(
        anchors=(
            _anchor("zero", 0.0, 0.0),
            _anchor("thirty", 30.0, 20.0),
        )
    )
    with pytest.raises(ValueError, match="exceeds.*envelope"):
        _evaluate(
            agile_config=agile,
            previous_execution=_previous_execution(direction=_direction(1, 0, 0)),
            next_candidate=_next_candidate(direction=_direction(0, 1, 0)),
        )


def test_b2_channel_configuration_exception_propagates() -> None:
    candidate = _next_candidate(
        channel_selection=OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY
    )

    with pytest.raises(ValueError, match="simultaneous"):
        _evaluate(next_candidate=candidate)


def test_acquisition_power_is_added_once_and_baseline_payload_is_preserved() -> None:
    baseline = _loads(
        base_bus_w=10.0,
        obc_w=20.0,
        adcs_w=30.0,
        payload_w=15.0,
        communications_w=40.0,
        thermal_control_w=50.0,
        propulsion_w=60.0,
    )
    result = _evaluate(environment=_environment(loads=baseline))
    acquisition = result.acquisition_evaluation.acquisition_result
    assert acquisition is not None
    assert result.eps_inputs is not None
    combined = result.eps_inputs.load_breakdown

    assert acquisition.requested_acquisition_power_w == 90.0
    assert combined.payload_w == 15.0 + 90.0 == 105.0
    assert combined.total_load_w == baseline.total_load_w + 90.0 == 315.0
    for field_name in LOAD_FIELDS:
        if field_name != "payload_w":
            assert getattr(combined, field_name) == getattr(baseline, field_name)
    assert baseline.payload_w == 15.0


def test_fully_served_physical_case_has_exact_bounds_and_energy() -> None:
    result = _evaluate(
        environment=_environment(loads=_loads(base_bus_w=100.0)),
        eps_config=_eps_config(max_discharge_w=1000.0),
        battery_state=BatteryState(500.0),
    )
    acquisition = result.acquisition_evaluation.acquisition_result
    eps = result.eps_result
    bounds = result.service_bounds
    assert acquisition is not None and eps is not None and bounds is not None

    assert acquisition.requested_acquisition_power_w == 90.0
    assert eps.battery.load_w == 190.0
    assert eps.battery.served_load_w == 190.0
    assert eps.battery.unmet_load_w == 0.0
    assert bounds.minimum_served_acquisition_power_w == 90.0
    assert bounds.maximum_served_acquisition_power_w == 90.0
    assert bounds.minimum_served_acquisition_energy_wh == 0.5
    assert bounds.maximum_served_acquisition_energy_wh == 0.5
    assert bounds.minimum_served_acquisition_energy_wh == (
        acquisition.acquisition_energy_wh
    )
    assert bounds.status is AcquisitionServiceStatus.FULLY_SERVED


def test_decimal_fully_served_case_avoids_bound_cancellation() -> None:
    requested_acquisition_power = 0.01
    duration_seconds = 20
    result = _evaluate(
        optical_config=_optical_config(
            acquisition_power_w=requested_acquisition_power
        ),
        environment=_environment(loads=_loads(base_bus_w=100.0)),
        eps_config=_eps_config(max_discharge_w=1000.0),
        battery_state=BatteryState(500.0),
        next_candidate=_next_candidate(duration_seconds=duration_seconds),
    )
    acquisition = result.acquisition_evaluation.acquisition_result
    eps = result.eps_result
    bounds = result.service_bounds
    assert acquisition is not None and eps is not None and bounds is not None

    assert acquisition.requested_acquisition_power_w == (
        requested_acquisition_power
    )
    assert eps.battery.load_w == 100.01
    assert eps.battery.unmet_load_w == 0.0
    assert bounds.minimum_served_acquisition_power_w == (
        requested_acquisition_power
    )
    assert bounds.maximum_served_acquisition_power_w == (
        requested_acquisition_power
    )
    assert bounds.minimum_served_acquisition_energy_wh == (
        requested_acquisition_power * duration_seconds / 3600
    )
    assert bounds.maximum_served_acquisition_energy_wh == (
        requested_acquisition_power * duration_seconds / 3600
    )
    assert bounds.status is AcquisitionServiceStatus.FULLY_SERVED


def test_full_service_impossible_physical_case_has_exact_bounds() -> None:
    result = _evaluate(
        environment=_environment(),
        eps_config=_eps_config(max_discharge_w=60.0),
        battery_state=BatteryState(500.0),
    )
    eps = result.eps_result
    bounds = result.service_bounds
    assert eps is not None and bounds is not None

    requested_acquisition = 90.0
    total_requested = 90.0
    aggregate_served = 60.0
    other_requested = total_requested - requested_acquisition
    expected_minimum = max(0, aggregate_served - other_requested)
    expected_maximum = min(requested_acquisition, aggregate_served)
    assert eps.battery.load_w == total_requested
    assert eps.battery.served_load_w == aggregate_served
    assert bounds.minimum_served_acquisition_power_w == expected_minimum == 60.0
    assert bounds.maximum_served_acquisition_power_w == expected_maximum == 60.0
    assert bounds.minimum_served_acquisition_energy_wh == 60 * 20 / 3600
    assert bounds.maximum_served_acquisition_energy_wh == 60 * 20 / 3600
    assert bounds.status is AcquisitionServiceStatus.FULL_SERVICE_IMPOSSIBLE


def test_service_allocation_required_physical_case_has_hand_bounds() -> None:
    result = _evaluate(
        environment=_environment(loads=_loads(base_bus_w=100.0)),
        eps_config=_eps_config(max_discharge_w=150.0),
        battery_state=BatteryState(500.0),
    )
    eps = result.eps_result
    bounds = result.service_bounds
    assert eps is not None and bounds is not None

    requested_acquisition = 90.0
    total_requested = 190.0
    aggregate_served = 150.0
    other_requested = total_requested - requested_acquisition
    expected_minimum = max(0, aggregate_served - other_requested)
    expected_maximum = min(requested_acquisition, aggregate_served)
    assert eps.battery.load_w == total_requested
    assert eps.battery.served_load_w == aggregate_served
    assert other_requested == 100.0
    assert bounds.minimum_served_acquisition_power_w == expected_minimum == 50.0
    assert bounds.maximum_served_acquisition_power_w == expected_maximum == 90.0
    assert bounds.minimum_served_acquisition_energy_wh == 50 * 20 / 3600
    assert bounds.maximum_served_acquisition_energy_wh == 90 * 20 / 3600
    assert 0 <= 50.0 <= 90.0 <= requested_acquisition
    assert bounds.status is (
        AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED
    )


def test_requested_energy_and_sample_grid_are_not_scaled_by_service() -> None:
    candidate = _next_candidate()
    optical = _optical_config()
    direct_d = evaluate_observation_acquisition(
        _agile_config(),
        optical,
        _previous_execution(),
        candidate,
    )
    result = _evaluate(
        optical_config=optical,
        next_candidate=candidate,
        eps_config=_eps_config(max_discharge_w=60.0),
    )

    assert result.acquisition_evaluation.acquisition_result == (
        direct_d.acquisition_result
    )
    assert result.service_bounds is not None
    assert result.service_bounds.maximum_served_acquisition_energy_wh < (
        result.acquisition_evaluation.acquisition_result.acquisition_energy_wh
    )
    assert (
        result.acquisition_evaluation.acquisition_result.total_equivalent_samples
        == 1000.0
    )
    assert (
        result.acquisition_evaluation.acquisition_result.uncompressed_equivalent_bits
        == 12000.0
    )


def test_degraded_capability_and_eps_equal_reviewed_direct_chain() -> None:
    eps_config = _eps_config(solar_w=400.0)
    battery = BatteryState(500.0)
    degradation = _degradation(
        battery_retention=0.8,
        solar_retention=0.6,
    )
    environment = _environment(
        sunlit=True,
        incidence_angle_deg=60.0,
        loads=_loads(base_bus_w=100.0, payload_w=15.0),
    )
    candidate = _next_candidate()
    result = _evaluate(
        eps_config=eps_config,
        battery_state=battery,
        degradation_state=degradation,
        environment=environment,
        next_candidate=candidate,
    )
    assert result.eps_inputs is not None
    expected_capability = compute_eps_capability(eps_config, degradation)
    expected_eps = compute_eps_interval_transition(
        battery,
        eps_config,
        result.eps_inputs,
        dt_seconds=candidate.acquisition_input.imaging_duration_seconds,
        capability=expected_capability,
    )

    assert result.eps_capability_result == expected_capability
    assert result.eps_result == expected_eps
    assert expected_capability.battery_usable_capacity_wh == 800.0
    assert expected_capability.solar_nominal_generation_capability_w == 240.0
    assert result.eps_result.solar.nominal_generation_w == 240.0
    assert result.eps_result.solar.generation_w == pytest.approx(120.0)


def test_battery_retention_does_not_scale_discharge_power_limit() -> None:
    result = _evaluate(
        eps_config=_eps_config(max_discharge_w=150.0),
        battery_state=BatteryState(500.0),
        degradation_state=_degradation(
            battery_retention=0.5,
            solar_retention=1.0,
        ),
        environment=_environment(loads=_loads(base_bus_w=100.0)),
    )
    assert result.eps_capability_result is not None
    assert result.eps_result is not None
    assert result.eps_capability_result.battery_usable_capacity_wh == 500.0
    assert result.eps_result.battery.discharge_output_w == 150.0


def test_result_presence_and_exact_nested_type_invariants() -> None:
    result = _evaluate()
    assert type(result.acquisition_evaluation) is (
        ObservationAcquisitionEvaluationResult
    )
    assert type(result.eps_inputs) is EPSIntervalInputs
    assert type(result.eps_result) is EPSIntervalResult
    assert type(result.service_bounds) is AcquisitionServiceBounds
    with pytest.raises(TypeError, match="eps_inputs"):
        replace(result, eps_inputs=object())
    with pytest.raises(TypeError, match="eps_capability_result"):
        replace(result, eps_capability_result=object())
    with pytest.raises(TypeError, match="eps_result"):
        replace(result, eps_result=object())
    with pytest.raises(TypeError, match="service_bounds"):
        replace(result, service_bounds=object())
    with pytest.raises(TypeError, match="eps_result"):
        replace(result, eps_result=None)


def test_result_revalidates_nested_eps_objects_and_cross_fields() -> None:
    result = _evaluate()
    assert result.eps_result is not None
    corrupted_loads = deepcopy(result.eps_result.loads)
    object.__setattr__(corrupted_loads, "base_bus_w", -1.0)
    corrupted_eps = replace(result.eps_result, loads=corrupted_loads)
    with pytest.raises(ValueError, match="base_bus_w"):
        replace(result, eps_result=corrupted_eps)

    wrong_inputs = replace(
        result.eps_inputs,
        load_breakdown=replace(result.eps_inputs.load_breakdown, obc_w=1.0),
    )
    with pytest.raises(ValueError, match="loads must equal"):
        replace(result, eps_inputs=wrong_inputs)

    wrong_bounds = replace(
        result.service_bounds,
        status=AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED,
    )
    with pytest.raises(ValueError, match="status"):
        replace(result, service_bounds=wrong_bounds)


def test_infeasible_result_rejects_any_eps_or_service_presence() -> None:
    infeasible = _evaluate(next_candidate=_next_candidate(view_angle_deg=36.0))
    feasible = _evaluate()
    assert feasible.eps_inputs is not None

    with pytest.raises(ValueError, match="all EPS and service fields"):
        replace(infeasible, eps_inputs=feasible.eps_inputs)


def test_evaluation_is_pure_and_mutates_nothing() -> None:
    arguments = (
        _agile_config(),
        _optical_config(),
        _eps_config(),
        BatteryState(500.0),
        _degradation(battery_retention=0.8, solar_retention=0.6),
        _previous_execution(),
        _next_candidate(),
        _environment(loads=_loads(base_bus_w=100.0, payload_w=15.0)),
    )
    before = deepcopy(arguments)

    result = evaluate_observation_acquisition_eps(*arguments)

    assert arguments == before
    assert result.eps_result is not None
    assert arguments[3].energy_wh == 500.0
    assert arguments[4].battery.usable_capacity_retention == 0.8
    assert arguments[4].solar.generation_retention == 0.6


def test_numpy_inputs_produce_builtin_service_bound_numbers() -> None:
    result = _evaluate(
        optical_config=_optical_config(acquisition_power_w=np.float64(90.0)),
        eps_config=_eps_config(solar_w=np.int64(1000)),
        battery_state=BatteryState(np.int64(500)),
        environment=_environment(
            incidence_angle_deg=np.float64(0.0),
            loads=_loads(base_bus_w=np.int64(100), payload_w=np.int64(15)),
        ),
    )
    assert result.service_bounds is not None
    for field_name in (
        "minimum_served_acquisition_power_w",
        "maximum_served_acquisition_power_w",
        "minimum_served_acquisition_energy_wh",
        "maximum_served_acquisition_energy_wh",
    ):
        value = getattr(result.service_bounds, field_name)
        assert type(value) in {int, float}
        assert isfinite(value)


def test_public_signature_accepts_no_external_computed_result() -> None:
    parameters = signature(evaluate_observation_acquisition_eps).parameters

    assert tuple(parameters) == (
        "agile_pointing_config",
        "optical_acquisition_config",
        "eps_config",
        "battery_state",
        "degradation_state",
        "previous_execution",
        "next_candidate",
        "environment",
    )
    assert all(
        parameter.kind is Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is Parameter.empty
        for parameter in parameters.values()
    )


def test_production_has_only_allowed_pure_dependencies() -> None:
    source = RESOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(RESOURCE_PATH))
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
        "adcs_config",
        "configuration",
        "dataclasses",
        "enum",
        "eps_capability",
        "eps_system",
        "imaging_feasibility",
        "math",
        "numbers",
        "observation_feasibility",
        "payload_config",
        "power_loads",
        "state",
    }
    assert imported_modules.isdisjoint(
        {
            "numpy",
            "engine",
            "context",
            "checkpoint",
            "mission",
            "world",
            "thermal",
            "thermal_routing",
            "thermal_coupling",
            "storage",
        }
    )


def test_production_has_no_allocation_partial_image_or_deferred_coupling_law() -> None:
    source = RESOURCE_PATH.read_text(encoding="utf-8").lower()

    for prohibited in (
        "payload_first",
        "payload-first",
        "payload_last",
        "payload-last",
        "platform_first",
        "platform-first",
        "proportional",
        "priority",
        "shedding",
        "isclose",
        "epsilon",
        "round(",
        "served_fraction",
        "partial_image",
        "generated_bytes",
        "stored_bytes",
        "compression",
        "packet",
        "downlink",
        "thermal_routing",
        "thermal_coupling",
        "servedpowerledger",
        "componentheatroutingconfig",
        "temperature",
        "checkpoint",
        "simulationengine",
    ):
        assert prohibited not in source


def test_production_delegates_without_retention_or_eps_equation_duplication() -> None:
    source = RESOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(RESOURCE_PATH))
    public_function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "evaluate_observation_acquisition_eps"
    )
    called_names = [
        node.func.id
        for node in ast.walk(public_function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]

    assert called_names.count("evaluate_observation_acquisition") == 1
    assert called_names.count("compute_eps_capability") == 1
    assert called_names.count("compute_eps_interval_transition") == 1
    assert "usable_capacity_retention *" not in source
    assert "generation_retention *" not in source
    assert "max_discharge_output_power_w" not in source
    assert "max_charge_input_power_w" not in source
    assert "compute_solar_generation" not in source
    assert "compute_battery_transition" not in source


def test_prior_non_engine_production_modules_are_unchanged() -> None:
    for relative_path in (
        "ops_sim/v5/imaging_feasibility.py",
        "ops_sim/v5/observation_feasibility.py",
        "ops_sim/v5/payload.py",
        "ops_sim/v5/payload_config.py",
        "ops_sim/v5/adcs.py",
        "ops_sim/v5/adcs_config.py",
        "ops_sim/v5/power_loads.py",
        "ops_sim/v5/eps.py",
        "ops_sim/v5/eps_system.py",
        "ops_sim/v5/eps_capability.py",
        "ops_sim/v5/solar.py",
        "ops_sim/v5/degradation.py",
        "ops_sim/v5/degradation_config.py",
        "ops_sim/v5/state.py",
        "ops_sim/v5/configuration.py",
        "ops_sim/v5/context.py",
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/mission.py",
        "ops_sim/v5/world.py",
    ):
        before_slice = subprocess.run(
            [
                "git",
                "show",
                f"b1a2c2b2ad86c10acf56102006fb4c73858632b2:{relative_path}",
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
                f"6551767b8c3474e8550ab4bb5d588ebbb2a8fe96:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert after_slice == before_slice


def test_imaging_resources_module_has_exact_exports() -> None:
    assert resource_module.__all__ == [
        "AcquisitionEPSIntervalEnvironment",
        "AcquisitionServiceBounds",
        "AcquisitionServiceStatus",
        "ObservationAcquisitionEPSResult",
        "evaluate_observation_acquisition_eps",
    ]


def test_d217_through_d227_and_e1_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s003 = sources.partition("### S003 ")[2].partition("### S004 ")[0]
    s005 = sources.partition("### S005 ")[2].partition("### S006 ")[0]
    lower = s003.lower()
    normalized = " ".join(lower.split())

    for number in range(217, 228):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D216 ") < decisions.index("## D217 ")
    assert "v5.3e1" in lower
    assert "no new physical source or value" in normalized
    assert "non-acquisition" in lower and "payload" in lower
    assert "min(90 w, 150 w) = 90 w" in normalized
    assert "max(0 w, 150 w - 100 w) = 50 w" in normalized
    assert "constant or interval-average" in normalized
    assert "no priority" in lower and "load-shedding" in lower
    assert "requested energy" in lower and "served energy" in lower
    assert "partial-image" in lower
    assert "start-of-interval" in lower and "exactly once" in lower
    assert "power fade" in lower
    assert "v5.3e1" in s005.lower() and "eps service bounds" in s005.lower()
