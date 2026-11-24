"""Final cross-cutting release audit for the frozen V5.3 implementation."""

from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
import importlib
from inspect import signature
from math import cos, radians, sin
from pathlib import Path
import re
import subprocess

import pytest

import examples.v53_integrated_imaging_demo as demo
import ops_sim.v5.adcs as adcs_module
from ops_sim.v5.adcs import (
    BoresightAngularSeparationResult,
    CommonFrameBoresightDirection,
    compute_boresight_angular_separation,
    compute_boresight_transition,
)
from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.degradation import SolarDegradationForcingInput
import ops_sim.v5.engine as engine_module
from ops_sim.v5.engine import (
    STEP_PHASE_ORDER,
    ImagingEngineStepAttempt,
    SimulationEngine,
    StepResult,
)
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    ADCSSlewAnchorId,
    GroundTargetId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
)
import ops_sim.v5.imaging_authorization as authorization_module
from ops_sim.v5.imaging_execution import (
    ImagingExecutionAuthorizationStatus,
    ScheduledObservationAcquisitionExecution,
)
from ops_sim.v5.imaging_feasibility import ObservationAcquisitionCandidate
from ops_sim.v5.imaging_resources import (
    AcquisitionEPSIntervalEnvironment,
    AcquisitionServiceStatus,
    evaluate_observation_acquisition_eps,
)
from ops_sim.v5.imaging_thermal import (
    evaluate_observation_acquisition_single_interval_thermal_proposal,
)
from ops_sim.v5.observation import (
    GroundTarget,
    ImagingRequest,
    ImagingRequestCatalog,
    ObservationCampaign,
    ObservationOpportunity,
    ObservationOpportunityCatalog,
    ObservationPointing,
    TargetCatalog,
)
from ops_sim.v5.observation_feasibility import (
    ObservationManeuverCandidate,
    ScheduledObservationExecution,
    evaluate_observation_view_feasibility,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
    compute_optical_acquisition,
)
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import BatteryState
from ops_sim.v5.thermal_coupling import ThermalHeatSourceInputs
from ops_sim.v5.thermal_routing import (
    ElectricalLoadComponent,
    ServedComponentPower,
    ServedPowerLedger,
)


ROOT = Path(__file__).resolve().parents[1]
V5_DIR = ROOT / "ops_sim" / "v5"
AUDIT_PATH = ROOT / "V5_3_RELEASE_AUDIT.md"
MODEL_STATUS_PATH = ROOT / "MODEL_STATUS.md"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"


def _v53_final_text(relative_path: str) -> str:
    return subprocess.run(
        ["git", "show", f"v5.3-final:{relative_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout

RELEASE_MODULES = (
    "observation",
    "observation_feasibility",
    "adcs_config",
    "adcs",
    "payload_config",
    "payload",
    "imaging_feasibility",
    "imaging_resources",
    "imaging_thermal",
    "imaging_execution",
    "imaging_authorization",
    "engine",
)

COMPONENT_LOAD_FIELD = {
    ElectricalLoadComponent.BASE_BUS: "base_bus_w",
    ElectricalLoadComponent.OBC: "obc_w",
    ElectricalLoadComponent.ADCS: "adcs_w",
    ElectricalLoadComponent.PAYLOAD: "payload_w",
    ElectricalLoadComponent.COMMUNICATIONS: "communications_w",
    ElectricalLoadComponent.THERMAL_CONTROL: "thermal_control_w",
    ElectricalLoadComponent.PROPULSION: "propulsion_w",
}


def _parameter(parameter_id: str, units: str, value: object) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by the V5.3 release audit.",
        ),
    )


def _anchor(name: str, angle_deg: object, seconds: object):
    prefix = f"adcs.slew-envelope.{name}"
    return BoresightSlewTimeAnchor(
        ADCSSlewAnchorId(name),
        _parameter(f"{prefix}.angular-separation", "deg", angle_deg),
        _parameter(f"{prefix}.elapsed-time", "s", seconds),
    )


def _slew_config(*, plateau: bool = False) -> AgilePointingConfig:
    return AgilePointingConfig(
        _parameter(
            "adcs.pointing.maximum-view-angle-from-nadir",
            "deg",
            45.0,
        ),
        _parameter("adcs.pointing.post-slew-settling-time", "s", 5.0),
        (
            _anchor("zero", 0.0, 0.0),
            _anchor("ten", 10.0, 20.0),
            _anchor("thirty", 30.0, 50.0),
            _anchor("sixty", 60.0, 50.0 if plateau else 90.0),
        ),
    )


def _direction(
    angle_deg: float,
    azimuth_deg: float = 0.0,
    *,
    scale: float = 1.0,
    frame: str = "v53f4b-common-frame",
) -> CommonFrameBoresightDirection:
    theta = radians(angle_deg)
    phi = radians(azimuth_deg)
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId(frame),
        scale * sin(theta) * cos(phi),
        scale * sin(theta) * sin(phi),
        scale * cos(theta),
    )


def _engine_arguments(context=None) -> dict[str, object]:
    active = demo._build_start_context() if context is None else context
    return {
        "context": active,
        "previous_execution": demo._previous_execution(),
        "execution": demo._scheduled_execution(10.0),
        "environment": demo._authorized_environment(),
        "routing_config": demo._routing_config(),
        "thermal_inputs": demo._thermal_inputs(active),
        "external_heat_sources": demo._external_heat_sources(active),
    }


def _authoritative_references(context) -> tuple[object, ...]:
    spacecraft = context.spacecraft_state
    knowledge = context.ground_knowledge_state
    return (
        context.inputs,
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


def _assert_rollback(context, before, references) -> None:
    assert context == before
    assert tuple(map(id, _authoritative_references(context))) == tuple(
        map(id, references)
    )


def _loads(
    *,
    base_bus_w: float = 0.0,
    payload_w: float = 0.0,
) -> PowerLoadBreakdown:
    return PowerLoadBreakdown(
        base_bus_w,
        0.0,
        0.0,
        payload_w,
        0.0,
        0.0,
        0.0,
    )


def _e1_case(
    *,
    acquisition_power_w: float,
    non_acquisition_loads: PowerLoadBreakdown,
    max_discharge_w: float,
):
    context = demo._build_start_context()
    spacecraft_config = context.inputs.spacecraft_configuration
    optical = spacecraft_config.payload.optical_acquisition
    assert optical is not None
    optical = replace(
        optical,
        acquisition_power_w=replace(
            optical.acquisition_power_w,
            value=acquisition_power_w,
        ),
    )
    battery_config = replace(
        spacecraft_config.eps.battery,
        max_discharge_output_power_w=replace(
            spacecraft_config.eps.battery.max_discharge_output_power_w,
            value=max_discharge_w,
        ),
    )
    eps_config = replace(spacecraft_config.eps, battery=battery_config)
    result = evaluate_observation_acquisition_eps(
        spacecraft_config.adcs.agile_pointing,
        optical,
        eps_config,
        BatteryState(500.0),
        context.spacecraft_state.degradation,
        demo._previous_execution(),
        demo._scheduled_execution(10.0).candidate,
        AcquisitionEPSIntervalEnvironment(
            False,
            0.0,
            non_acquisition_loads,
        ),
    )
    return context, result


def _rebuild_execution(
    execution: ScheduledObservationAcquisitionExecution,
    *,
    duration_seconds: int | None = None,
    direction: CommonFrameBoresightDirection | None = None,
) -> ScheduledObservationAcquisitionExecution:
    candidate = execution.candidate
    maneuver = candidate.maneuver_candidate
    opportunity = maneuver.opportunity
    duration = (
        opportunity.imaging_duration_seconds
        if duration_seconds is None
        else duration_seconds
    )
    opportunity = replace(opportunity, imaging_duration_seconds=duration)
    maneuver = ObservationManeuverCandidate(
        opportunity,
        maneuver.common_frame_boresight if direction is None else direction,
    )
    acquisition_input = replace(
        candidate.acquisition_input,
        imaging_duration_seconds=duration,
    )
    return ScheduledObservationAcquisitionExecution(
        ObservationAcquisitionCandidate(maneuver, acquisition_input),
        execution.scheduled_start_seconds,
    )


def _normalized_words(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _called_names(node: ast.AST) -> tuple[str, ...]:
    names = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name):
            names.append(item.func.id)
        elif isinstance(item.func, ast.Attribute):
            names.append(item.func.attr)
    return tuple(names)


@pytest.fixture(scope="module")
def repeated_demo_reports():
    return (
        demo.run_v53_integrated_imaging_demo(),
        demo.run_v53_integrated_imaging_demo(),
    )


def test_observation_domain_is_immutable_local_and_cross_referenced() -> None:
    target = GroundTarget(GroundTargetId("audit-target"), 45.0, 67.0)
    request = ImagingRequest(
        ImagingRequestId("audit-request"),
        target.target_id,
        2.0,
    )
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("audit-opportunity"),
        request.request_id,
        100,
        200,
        60,
        ObservationPointing(45.0, 180.0),
    )
    campaign = ObservationCampaign(
        TargetCatalog((target,)),
        ImagingRequestCatalog((request,)),
        ObservationOpportunityCatalog((opportunity,)),
    )

    assert campaign.opportunities.opportunities[0].request_id == request.request_id
    assert not hasattr(target, "__dict__")
    with pytest.raises(FrozenInstanceError):
        target.latitude_deg = 0.0

    at_limit = evaluate_observation_view_feasibility(
        _slew_config(),
        opportunity,
    )
    outside = evaluate_observation_view_feasibility(
        _slew_config(),
        replace(opportunity, pointing=ObservationPointing(45.1, 180.0)),
    )
    assert at_limit.feasible is True
    assert outside.feasible is False
    assert at_limit.maximum_view_angle_from_nadir_deg == 45.0


def test_adcs_independent_vectors_and_structure_are_robust() -> None:
    frame = ADCSBoresightFrameId("v53f4b-common-frame")
    z = CommonFrameBoresightDirection(frame, 0.0, 0.0, 1.0)
    x = CommonFrameBoresightDirection(frame, 1.0, 0.0, 0.0)
    minus_z = CommonFrameBoresightDirection(frame, 0.0, 0.0, -1.0)

    assert compute_boresight_angular_separation(z, z).angular_separation_deg == 0
    assert compute_boresight_angular_separation(z, x).angular_separation_deg == 90
    assert (
        compute_boresight_angular_separation(z, minus_z).angular_separation_deg
        == 180
    )
    for off_axis, expected in ((30.0, 60.0), (35.0, 70.0)):
        separation = compute_boresight_angular_separation(
            _direction(off_axis, 0.0),
            _direction(off_axis, 180.0),
        )
        assert separation.angular_separation_deg == pytest.approx(expected)

    baseline = compute_boresight_angular_separation(
        _direction(23.0, 17.0),
        _direction(41.0, 221.0),
    )
    scaled = compute_boresight_angular_separation(
        _direction(23.0, 17.0, scale=7.0),
        _direction(41.0, 221.0, scale=0.125),
    )
    assert scaled.angular_separation_deg == pytest.approx(
        baseline.angular_separation_deg
    )
    with pytest.raises(ValueError, match="nonzero"):
        CommonFrameBoresightDirection(frame, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="same frame"):
        compute_boresight_angular_separation(
            z,
            CommonFrameBoresightDirection(
                ADCSBoresightFrameId("other-frame"),
                0.0,
                0.0,
                1.0,
            ),
        )

    tree = ast.parse((V5_DIR / "adcs.py").read_text(encoding="utf-8"))
    angular_function = _function(
        tree,
        "compute_boresight_angular_separation",
    )
    calls = _called_names(angular_function)
    assert calls.count("atan2") == 1
    assert set(calls).isdisjoint({"acos", "clip", "clamp", "isclose"})
    atan2_call = next(
        node
        for node in ast.walk(angular_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "atan2"
    )
    assert tuple(ast.unparse(argument) for argument in atan2_call.args) == (
        "cross_norm",
        "dot",
    )
    dot_assignments = tuple(
        node
        for node in ast.walk(angular_function)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "dot"
            for target in node.targets
        )
    )
    assert len(dot_assignments) == 1
    dot_value = dot_assignments[0].value
    assert isinstance(dot_value, ast.Call)
    assert isinstance(dot_value.func, ast.Name)
    assert dot_value.func.id == "_checked_sum"
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert all("observation" not in module and "orbit" not in module for module in imports)


def test_synthetic_slew_envelope_anchors_interpolation_and_limits(
    monkeypatch,
) -> None:
    config = _slew_config()
    start = _direction(0.0)

    def transition_at(angle):
        monkeypatch.setattr(
            adcs_module,
            "compute_boresight_angular_separation",
            lambda start, end: BoresightAngularSeparationResult(angle),
        )
        return compute_boresight_transition(config, start, _direction(1.0))

    expected = {
        0.0: (0.0, 0.0, 0.0),
        10.0: (20.0, 5.0, 25.0),
        30.0: (50.0, 5.0, 55.0),
        60.0: (90.0, 5.0, 95.0),
    }
    for angle, times in expected.items():
        result = transition_at(angle)
        assert (
            result.slew_elapsed_time_seconds,
            result.settling_time_seconds,
            result.total_transition_time_seconds,
        ) == times

    midpoint = transition_at(20.0)
    assert midpoint.interpolation_fraction == pytest.approx(0.5)
    assert midpoint.slew_elapsed_time_seconds == pytest.approx(35.0)
    assert midpoint.total_transition_time_seconds == pytest.approx(40.0)

    monkeypatch.setattr(
        adcs_module,
        "compute_boresight_angular_separation",
        lambda start, end: BoresightAngularSeparationResult(45.0),
    )
    plateau = compute_boresight_transition(
        _slew_config(plateau=True), start, _direction(1.0)
    )
    assert plateau.slew_elapsed_time_seconds == 50.0
    assert plateau.settling_time_seconds == 5.0

    # The configured local 45 degree viewing limit is not a common-frame
    # separation cap: the 60 degree envelope anchor remains valid.
    assert transition_at(60.0).angular_separation_deg == 60.0
    with pytest.raises(ValueError, match="exceeds.*envelope"):
        transition_at(61.0)


def test_twenty_kilometre_sample_grid_and_acquisition_nonclaims() -> None:
    context = demo._build_start_context()
    config = context.inputs.spacecraft_configuration.payload.optical_acquisition
    assert config is not None
    result = compute_optical_acquisition(
        config,
        OpticalAcquisitionInput(
            20_000.0,
            20_000.0,
            60,
            OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        ),
    )
    area = 20_000.0 * 20_000.0
    pan = area / 1.0**2
    ms_per_band = area / 4.0**2
    ms_total = 4 * ms_per_band
    total = pan + ms_total
    bits = 12 * total
    byte_count = bits / 8
    density = bits / (area / 1_000_000) / 1_000_000
    assert (
        result.footprint_area_m2,
        result.panchromatic_equivalent_samples,
        result.multispectral_equivalent_samples_per_band,
        result.multispectral_equivalent_samples_total,
        result.total_equivalent_samples,
        result.uncompressed_equivalent_bits,
        result.uncompressed_equivalent_bytes,
        density,
    ) == (
        400_000_000.0,
        400_000_000.0,
        25_000_000.0,
        100_000_000.0,
        500_000_000.0,
        6_000_000_000.0,
        750_000_000.0,
        15.0,
    )

    # Width beyond the synthetic config's reference swath is still an admitted
    # explicit footprint input, not an automatic feasibility failure.
    assert config.reference_nadir_swath_width_m.value == 1_000.0
    assert compute_optical_acquisition(
        config,
        OpticalAcquisitionInput(
            21_000.0,
            1_000.0,
            60,
            OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        ),
    ).footprint_area_m2 == 21_000_000.0

    fractional = compute_optical_acquisition(
        config,
        OpticalAcquisitionInput(
            1.0,
            1.0,
            60,
            OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        ),
    )
    assert (
        fractional.panchromatic_equivalent_samples,
        fractional.multispectral_equivalent_samples_per_band,
        fractional.multispectral_equivalent_samples_total,
        fractional.total_equivalent_samples,
        fractional.uncompressed_equivalent_bits,
        fractional.uncompressed_equivalent_bytes,
    ) == (1.0, 0.0625, 0.25, 1.25, 15.0, 1.875)

    tree = ast.parse((V5_DIR / "payload.py").read_text(encoding="utf-8"))
    compute = _function(tree, "compute_optical_acquisition")
    assert set(_called_names(compute)).isdisjoint(
        {"int", "round", "ceil", "floor", "compress", "store", "downlink"}
    )
    assert not any(
        isinstance(node, ast.Constant) and node.value in {270, 270_000_000}
        for node in ast.walk(tree)
    )
    identifiers = {
        node.id.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    } | {
        node.attr.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    assert identifiers.isdisjoint(
        {
            "compression_ratio",
            "compressed_bytes",
            "stored_bytes",
            "packet_overhead",
            "file_overhead",
        }
    )


def test_eps_three_service_classes_and_exact_cancellation_regression() -> None:
    _, fully = _e1_case(
        acquisition_power_w=90.0,
        non_acquisition_loads=_loads(base_bus_w=100.0),
        max_discharge_w=1_000.0,
    )
    _, impossible = _e1_case(
        acquisition_power_w=90.0,
        non_acquisition_loads=_loads(),
        max_discharge_w=60.0,
    )
    _, allocation = _e1_case(
        acquisition_power_w=90.0,
        non_acquisition_loads=_loads(base_bus_w=100.0),
        max_discharge_w=150.0,
    )
    _, cancellation = _e1_case(
        acquisition_power_w=0.01,
        non_acquisition_loads=_loads(base_bus_w=100.0),
        max_discharge_w=1_000.0,
    )

    fully_bounds = fully.service_bounds
    impossible_bounds = impossible.service_bounds
    allocation_bounds = allocation.service_bounds
    cancellation_bounds = cancellation.service_bounds
    assert all(
        value is not None
        for value in (
            fully_bounds,
            impossible_bounds,
            allocation_bounds,
            cancellation_bounds,
        )
    )
    assert fully.eps_result is not None
    assert fully.eps_result.battery.unmet_load_w == 0
    assert fully_bounds.status is AcquisitionServiceStatus.FULLY_SERVED
    assert (
        fully_bounds.minimum_served_acquisition_power_w,
        fully_bounds.maximum_served_acquisition_power_w,
    ) == (90.0, 90.0)

    assert impossible.eps_result is not None
    assert impossible_bounds.status is (
        AcquisitionServiceStatus.FULL_SERVICE_IMPOSSIBLE
    )
    assert impossible.eps_result.battery.served_load_w == 60.0
    assert (
        impossible_bounds.minimum_served_acquisition_power_w,
        impossible_bounds.maximum_served_acquisition_power_w,
    ) == (60.0, 60.0)
    assert impossible_bounds.maximum_served_acquisition_power_w < 90.0

    assert allocation.eps_result is not None
    assert allocation.eps_result.battery.load_w == 190.0
    assert allocation.eps_result.battery.served_load_w == 150.0
    assert allocation_bounds.status is (
        AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED
    )
    assert (
        allocation_bounds.minimum_served_acquisition_power_w,
        allocation_bounds.maximum_served_acquisition_power_w,
    ) == (max(0.0, 150.0 - 100.0), min(90.0, 150.0)) == (50.0, 90.0)

    assert cancellation.eps_result is not None
    assert cancellation.eps_result.battery.unmet_load_w == 0
    assert cancellation_bounds.status is AcquisitionServiceStatus.FULLY_SERVED
    assert cancellation_bounds.minimum_served_acquisition_power_w == 0.01
    assert cancellation_bounds.maximum_served_acquisition_power_w == 0.01

    resources_tree = ast.parse(
        (V5_DIR / "imaging_resources.py").read_text(encoding="utf-8")
    )
    service_bounds_function = _function(resources_tree, "_service_bounds")
    classification = next(
        node
        for node in service_bounds_function.body
        if isinstance(node, ast.If)
        and any(
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "status"
                for target in statement.targets
            )
            for statement in node.body
        )
    )
    assert ast.unparse(classification.test) == (
        "minimum_power == requested_power"
    )
    impossible_branch = classification.orelse
    assert len(impossible_branch) == 1
    assert isinstance(impossible_branch[0], ast.If)
    assert ast.unparse(impossible_branch[0].test) == (
        "maximum_power < requested_power"
    )
    classification_names = {
        node.id.lower()
        for node in ast.walk(classification)
        if isinstance(node, ast.Name)
    }
    assert classification_names.isdisjoint(
        {"epsilon", "tolerance", "tol", "isclose", "approx"}
    )
    assert set(_called_names(classification)).isdisjoint(
        {"isclose", "approx", "clip", "clamp"}
    )


def test_hand_checkable_thermal_accounting_uses_served_component_power() -> None:
    background = _loads(base_bus_w=25.0, payload_w=15.0)
    context, electrical = _e1_case(
        acquisition_power_w=90.0,
        non_acquisition_loads=background,
        max_discharge_w=105.0,
    )
    assert electrical.eps_inputs is not None
    assert electrical.eps_result is not None
    loads = electrical.eps_inputs.load_breakdown
    served = ServedPowerLedger(
        tuple(
            ServedComponentPower(
                component,
                getattr(loads, COMPONENT_LOAD_FIELD[component]),
                (
                    80.0
                    if component is ElectricalLoadComponent.PAYLOAD
                    else getattr(loads, COMPONENT_LOAD_FIELD[component])
                ),
            )
            for component in ElectricalLoadComponent
        )
    )
    routing = demo._routing_config()
    routing = replace(
        routing,
        routes=tuple(
            replace(
                route,
                retained_heat_fraction=replace(
                    route.retained_heat_fraction,
                    value=0.5,
                ),
            )
            if route.component is ElectricalLoadComponent.PAYLOAD
            else route
            for route in routing.routes
        ),
    )
    external = demo._external_heat_sources(context)
    external_with_placeholders = ThermalHeatSourceInputs(
        tuple(
            replace(
                source,
                internal_dissipation_w=999.0,
                absorbed_solar_w=(
                    1.25
                    if source.node_id.value == "payload"
                    else source.absorbed_solar_w
                ),
                absorbed_albedo_w=(
                    2.5
                    if source.node_id.value == "payload"
                    else source.absorbed_albedo_w
                ),
                absorbed_earth_ir_w=(
                    3.75
                    if source.node_id.value == "payload"
                    else source.absorbed_earth_ir_w
                ),
            )
            for source in external.node_sources
        )
    )
    proposal = evaluate_observation_acquisition_single_interval_thermal_proposal(
        electrical,
        served,
        routing,
        context.spacecraft_state.thermal,
        context.inputs.spacecraft_configuration.thermal.network,
        demo._thermal_inputs(context),
        external_with_placeholders,
    )

    component_by_id = {
        item.component: item
        for item in proposal.routed_internal_heat_result.component_ledgers
    }
    payload = component_by_id[ElectricalLoadComponent.PAYLOAD]
    assert electrical.eps_result.battery.served_load_w == 105.0
    assert payload.requested_power_w == 105.0
    assert payload.served_power_w == 80.0
    assert payload.served_power_w != payload.requested_power_w
    assert payload.served_power_w != 90.0
    assert payload.retained_heat_fraction == 0.5
    assert payload.retained_heat_w == 40.0
    for item in component_by_id.values():
        assert item.retained_heat_w == pytest.approx(
            item.served_power_w * item.retained_heat_fraction
        )

    routed_by_node = {
        item.node_id: item.applied_heat_into_w
        for item in proposal.routed_internal_heat_result.node_internal_heat_w
    }
    external_by_node = {
        item.node_id: item for item in external_with_placeholders.node_sources
    }
    ledgers = proposal.eps_thermal_coupling_result.node_heat_ledgers
    for ledger in ledgers:
        source = external_by_node[ledger.node_id]
        assert ledger.internal_dissipation_w == routed_by_node[ledger.node_id]
        assert ledger.internal_dissipation_w != routed_by_node[ledger.node_id] + 999
        assert ledger.absorbed_solar_w == source.absorbed_solar_w
        assert ledger.absorbed_albedo_w == source.absorbed_albedo_w
        assert ledger.absorbed_earth_ir_w == source.absorbed_earth_ir_w
        assert ledger.total_applied_heat_w == pytest.approx(
            ledger.internal_dissipation_w
            + ledger.absorbed_solar_w
            + ledger.absorbed_albedo_w
            + ledger.absorbed_earth_ir_w
            + ledger.battery_conversion_heat_w
        )
    payload_node = next(
        item for item in ledgers if item.node_id.value == "payload"
    )
    assert payload_node.internal_dissipation_w == 40.0
    assert payload_node.absorbed_solar_w == 1.25
    assert payload_node.absorbed_albedo_w == 2.5
    assert payload_node.absorbed_earth_ir_w == 3.75
    assert payload_node.battery_conversion_heat_w == 0.0
    assert payload_node.total_applied_heat_w == 47.5
    expected_conversion_heat = (
        electrical.eps_result.battery.conversion_loss_wh
        * 3600
        / electrical.eps_result.battery.dt_seconds
    )
    assert sum(item.battery_conversion_heat_w for item in ledgers) == pytest.approx(
        expected_conversion_heat
    )

    thermal_tree = ast.parse(
        (V5_DIR / "imaging_thermal.py").read_text(encoding="utf-8")
    )
    public_function = _function(
        thermal_tree,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
    )
    attributes = {
        node.attr
        for node in ast.walk(public_function)
        if isinstance(node, ast.Attribute)
    }
    assert attributes.isdisjoint(
        {
            "requested_acquisition_power_w",
            "minimum_served_acquisition_power_w",
            "maximum_served_acquisition_power_w",
            "acquisition_energy_wh",
        }
    )
    thermal_identifiers = attributes | {
        node.id
        for node in ast.walk(public_function)
        if isinstance(node, ast.Name)
    }
    assert thermal_identifiers.isdisjoint(
        {"waste_heat", "acquisition_heat", "requested_acquisition_heat"}
    )


def test_authorized_step_has_one_causal_chain_and_exact_commit(monkeypatch) -> None:
    context = demo._build_start_context()
    before = deepcopy(context)
    counts = Counter()
    events = []
    original_f2 = engine_module.evaluate_imaging_engine_step_authorization
    original_e1 = authorization_module.evaluate_observation_acquisition_eps
    original_e2 = (
        authorization_module
        .evaluate_observation_acquisition_single_interval_thermal_proposal
    )
    original_tail = engine_module._complete_coupled_physical_integration
    original_degradation = engine_module.compute_battery_degradation_transition
    original_reconciliation = engine_module.compute_battery_capacity_reconciliation
    original_commit = SimulationEngine._commit

    def counted(name, function):
        def wrapper(*args, **kwargs):
            counts[name] += 1
            events.append(name)
            return function(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(
        engine_module,
        "evaluate_imaging_engine_step_authorization",
        counted("f2", original_f2),
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_eps",
        counted("e1", original_e1),
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
        counted("e2", original_e2),
    )
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        counted("tail", original_tail),
    )
    monkeypatch.setattr(
        engine_module,
        "compute_battery_degradation_transition",
        counted("degradation", original_degradation),
    )
    monkeypatch.setattr(
        engine_module,
        "compute_battery_capacity_reconciliation",
        counted("reconciliation", original_reconciliation),
    )

    def forbidden_generic(*args, **kwargs):
        counts["generic"] += 1
        pytest.fail("generic physical integration must not run for imaging")

    def commit(original, working):
        counts["commit"] += 1
        events.append("commit")
        return original_commit(original, working)

    monkeypatch.setattr(
        SimulationEngine,
        "_physical_integration",
        staticmethod(forbidden_generic),
    )
    monkeypatch.setattr(SimulationEngine, "_commit", staticmethod(commit))

    attempt = SimulationEngine().step_imaging(**_engine_arguments(context))
    result = attempt.step_result
    authorization = attempt.authorization_result
    assert result is not None
    assert counts == {
        "f2": 1,
        "e1": 1,
        "e2": 1,
        "tail": 1,
        "degradation": 1,
        "reconciliation": 1,
        "commit": 1,
    }
    assert events == [
        "f2",
        "e1",
        "e2",
        "tail",
        "degradation",
        "reconciliation",
        "commit",
    ]

    engine_tree = ast.parse((V5_DIR / "engine.py").read_text(encoding="utf-8"))
    transaction = _function(engine_tree, "_run_transaction")
    assert _called_names(transaction).count("StepResult") == 1
    assert type(attempt) is ImagingEngineStepAttempt
    assert type(result) is StepResult
    assert result.eps_result is authorization.electrical_result.eps_result
    assert result.eps_capability_result is (
        authorization.electrical_result.eps_capability_result
    )
    assert result.thermal_coupling_result is (
        authorization.thermal_proposal.eps_thermal_coupling_result
    )
    assert result.executed_phases == STEP_PHASE_ORDER
    assert len(result.executed_phases) == 9
    assert result.solar_degradation_result is None
    assert context.simulation_time_seconds == (
        before.simulation_time_seconds + result.dt_seconds
    )
    assert context.diagnostics.completed_steps == before.diagnostics.completed_steps + 1
    assert context.spacecraft_state.battery.energy_wh == (
        result.battery_capacity_reconciliation_result.authoritative_end_energy_wh
    )
    assert context.spacecraft_state.degradation.battery.usable_capacity_retention == (
        result.battery_degradation_result.end_usable_capacity_retention
    )
    assert (
        context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
        == result.battery_degradation_result
        .end_cumulative_energy_throughput_wh
    )
    assert {
        node.node_id: node.temperature_k
        for node in context.spacecraft_state.thermal.node_states
    } == {
        transition.node_id: transition.end_temperature_k
        for transition in result.thermal_coupling_result.thermal_result.node_transitions
    }
    assert context.mission_state == before.mission_state


@pytest.mark.parametrize(
    ("case", "expected_service"),
    (
        ("sequence", None),
        ("full-service-impossible", AcquisitionServiceStatus.FULL_SERVICE_IMPOSSIBLE),
        ("allocation-required", AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED),
    ),
)
def test_supported_nonauthorization_matrix_preserves_values_and_identities(
    case,
    expected_service,
    monkeypatch,
) -> None:
    context = demo._build_start_context()
    arguments = _engine_arguments(context)
    if case == "sequence":
        arguments["execution"] = demo._scheduled_execution(50.0)
    elif case == "full-service-impossible":
        arguments["environment"] = demo._impossible_environment()
    else:
        arguments["environment"] = demo._allocation_environment()
    before = deepcopy(context)
    references = _authoritative_references(context)
    commit_calls = []

    def forbidden_commit(*args):
        commit_calls.append(args)
        pytest.fail("nonauthorization must not commit")

    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(forbidden_commit),
    )
    attempt = SimulationEngine().step_imaging(**arguments)

    assert attempt.step_result is None
    assert attempt.authorization_result.thermal_proposal is None
    if case == "sequence":
        assert attempt.authorization_result.status is (
            ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE
        )
        assert attempt.authorization_result.electrical_result.service_bounds is None
    else:
        assert attempt.authorization_result.status is (
            ImagingExecutionAuthorizationStatus.ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED
        )
        assert (
            attempt.authorization_result.electrical_result.service_bounds.status
            is expected_service
        )
    assert commit_calls == []
    _assert_rollback(context, before, references)


@pytest.mark.parametrize(
    "case",
    (
        "boundary-mismatch",
        "duration-mismatch",
        "frame-mismatch",
        "unsupported-envelope",
        "invalid-acquisition",
        "thermal-failure",
        "degradation-failure",
        "reconciliation-failure",
        "final-context-validation-failure",
        "step-result-validation-failure",
    ),
)
def test_exception_rollback_matrix_preserves_values_and_identities(
    case,
    monkeypatch,
) -> None:
    context = demo._build_start_context()
    arguments = _engine_arguments(context)
    engine = SimulationEngine()
    expected_exception = ValueError

    if case == "boundary-mismatch":
        arguments["execution"] = replace(
            arguments["execution"],
            scheduled_start_seconds=context.simulation_time_seconds + 1,
        )
    elif case == "duration-mismatch":
        arguments["execution"] = _rebuild_execution(
            arguments["execution"],
            duration_seconds=(
                context.inputs.numerical_config.timestep_seconds - 1
            ),
        )
    elif case == "frame-mismatch":
        previous = arguments["previous_execution"]
        arguments["previous_execution"] = ScheduledObservationExecution(
            ObservationManeuverCandidate(
                previous.candidate.opportunity,
                CommonFrameBoresightDirection(
                    ADCSBoresightFrameId("v53f4b-other-frame"),
                    0.0,
                    0.0,
                    1.0,
                ),
            ),
            previous.scheduled_start_seconds,
        )
    elif case == "unsupported-envelope":
        current_direction = (
            arguments["execution"].candidate.maneuver_candidate
            .common_frame_boresight
        )
        arguments["execution"] = _rebuild_execution(
            arguments["execution"],
            direction=CommonFrameBoresightDirection(
                current_direction.frame_id,
                0.0,
                0.0,
                -1.0,
            ),
        )
    elif case == "invalid-acquisition":
        object.__setattr__(
            arguments["execution"].candidate.acquisition_input,
            "effective_cross_track_width_m",
            -1.0,
        )
    elif case == "thermal-failure":
        expected_exception = RuntimeError

        def fail_thermal(*args, **kwargs):
            raise RuntimeError("synthetic thermal failure")

        monkeypatch.setattr(
            authorization_module,
            "evaluate_observation_acquisition_single_interval_thermal_proposal",
            fail_thermal,
        )
    elif case == "degradation-failure":
        expected_exception = RuntimeError

        def fail_degradation(*args, **kwargs):
            raise RuntimeError("synthetic degradation failure")

        monkeypatch.setattr(
            engine_module,
            "compute_battery_degradation_transition",
            fail_degradation,
        )
    elif case == "reconciliation-failure":
        expected_exception = RuntimeError

        def fail_reconciliation(*args, **kwargs):
            raise RuntimeError("synthetic reconciliation failure")

        monkeypatch.setattr(
            engine_module,
            "compute_battery_capacity_reconciliation",
            fail_reconciliation,
        )
    elif case == "final-context-validation-failure":

        class CorruptingEngine(SimulationEngine):
            @staticmethod
            def _advance_clock(working, interval):
                SimulationEngine._advance_clock(working, interval)
                working.spacecraft_state.battery.energy_wh = -1.0

        engine = CorruptingEngine()
    else:
        expected_exception = RuntimeError

        def fail_step_result(self):
            raise RuntimeError("synthetic StepResult failure")

        monkeypatch.setattr(StepResult, "__post_init__", fail_step_result)

    before = deepcopy(context)
    references = _authoritative_references(context)
    commit_calls = []
    original_commit = SimulationEngine._commit

    def counted_commit(original, working):
        commit_calls.append((original, working))
        return original_commit(original, working)

    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(counted_commit),
    )
    with pytest.raises(expected_exception):
        engine.step_imaging(**arguments)

    assert commit_calls == []
    _assert_rollback(context, before, references)


def test_optional_solar_degradation_uses_start_capability_and_commits_endpoint(
    monkeypatch,
) -> None:
    context = demo._build_start_context()
    start_retention = (
        context.spacecraft_state.degradation.solar.generation_retention
    )
    calls = []
    original = engine_module.compute_explicit_solar_degradation_transition

    def solar(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        engine_module,
        "compute_explicit_solar_degradation_transition",
        solar,
    )
    arguments = _engine_arguments(context)
    arguments["solar_degradation_forcing"] = SolarDegradationForcingInput(0.01)
    attempt = SimulationEngine().step_imaging(**arguments)
    result = attempt.step_result
    assert result is not None
    assert len(calls) == 1
    assert result.solar_degradation_result is not None
    assert result.solar_degradation_result.start_generation_retention == (
        start_retention
    )
    assert result.solar_degradation_result.end_generation_retention == (
        start_retention - 0.01
    )
    assert result.eps_capability_result.solar_generation_retention == (
        start_retention
    )
    assert context.spacecraft_state.degradation.solar.generation_retention == (
        result.solar_degradation_result.end_generation_retention
    )


def test_checkpoint_restore_with_resupplied_imaging_inputs_replays_exactly() -> None:
    direct_context = demo._build_start_context()
    checkpoint_source = demo._build_start_context()
    checkpoint = CheckpointState.from_context(checkpoint_source)
    replay_context = checkpoint.restore(checkpoint_source.inputs)
    direct_arguments = _engine_arguments(direct_context)
    replay_arguments = _engine_arguments(replay_context)
    direct_arguments.pop("context")
    replay_arguments.pop("context")
    assert direct_arguments == replay_arguments

    direct_attempt = SimulationEngine().step_imaging(
        direct_context,
        **direct_arguments,
    )
    replay_attempt = SimulationEngine().step_imaging(
        replay_context,
        **replay_arguments,
    )
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == checkpoint.schema_version == 5
    assert direct_attempt == replay_attempt
    assert direct_attempt.step_result == replay_attempt.step_result
    assert direct_context == replay_context
    checkpoint_fields = tuple(field.name for field in fields(CheckpointState))
    assert checkpoint_fields == (
        "schema_version",
        "simulation_time_seconds",
        "model_manifest_id",
        "spacecraft_configuration_id",
        "numerical_config_id",
        "environment_id",
        "flight_rules_id",
        "scenario_id",
        "world_id",
        "controller_id",
        "spacecraft",
        "ground_knowledge",
        "ground_data_delivery",
        "mission",
        "controller",
        "diagnostics",
    )
    assert set(checkpoint_fields).isdisjoint(
        {
            "execution",
            "selected_execution",
            "acquisition",
            "acquisition_result",
            "imaging_result",
            "imaging_execution",
            "imaging_attempt",
            "authorization_result",
            "step_result",
        }
    )


def test_complete_demo_repeats_with_exact_report_and_output(
    repeated_demo_reports,
    capsys,
) -> None:
    first, second = repeated_demo_reports
    assert first == second
    assert first.repeat_attempt_equal is True
    assert first.repeat_context_equal is True
    assert first.replay_attempt_equal is True
    assert first.replay_context_equal is True
    assert first.checkpoint_schema_version == 5

    demo.main()
    first_output = capsys.readouterr()
    demo.main()
    second_output = capsys.readouterr()
    assert first_output == second_output


def test_no_forbidden_v53_semantic_drift_in_production_structure() -> None:
    trees = {
        name: ast.parse(_v53_final_text(f"ops_sim/v5/{name}.py"))
        for name in RELEASE_MODULES
    }
    identifiers = {
        value.lower()
        for tree in trees.values()
        for node in ast.walk(tree)
        for value in (
            (node.id,) if isinstance(node, ast.Name) else
            (node.attr,) if isinstance(node, ast.Attribute) else
            (node.name,) if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else
            ()
        )
    }
    forbidden_identifiers = {
        "compression_ratio",
        "compressed_bytes",
        "storage_capacity_bytes",
        "stored_bytes",
        "store_image",
        "downlink_image",
        "downlinked_bytes",
        "complete_product",
        "product_completed",
        "missionrequestid",
        "mission_imaging_request_binding",
        "select_target",
        "target_selection",
        "shortfall_allocation_policy",
        "allocate_shortfall",
        "partial_image",
        "partial_image_fraction",
        "duty_cycle",
        "substep",
        "partial_step",
        "quaternion",
        "reaction_wheel",
        "actuator_dynamics",
        "slew_energy_wh",
        "orbit_derived_opportunity",
        "convert_opportunity_to_frame",
        "thermal_feasibility_status",
        "slew_rate",
        "angular_rate",
        "constant_slew_rate",
    }
    assert identifiers.isdisjoint(forbidden_identifiers)

    callable_names = {
        value.lower()
        for tree in trees.values()
        for node in ast.walk(tree)
        for value in (
            (node.name,) if isinstance(node, ast.FunctionDef) else
            (node.func.id,) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) else
            (node.func.attr,) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) else
            ()
        )
    }
    assert not any(
        forbidden_part in name
        for name in callable_names
        for forbidden_part in (
            "compress",
            "downlink",
            "store_image",
            "complete_product",
            "partial_image",
            "select_target",
            "allocate_shortfall",
            "substep",
            "quaternion",
            "reaction_wheel",
            "convert_opportunity",
            "observation_to_frame",
            "thermal_feasibility",
        )
    )

    imported_names = {
        value.lower()
        for tree in trees.values()
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
        for value in (
            node.module or "" if isinstance(node, ast.ImportFrom) else "",
            alias.name,
            alias.asname or "",
        )
        if value
    }
    assert all(
        not any(term in imported_name for term in ("storage", "downlink", "orbit"))
        for imported_name in imported_names
    )

    imaging_methods = tuple(
        _function(trees["engine"], name)
        for name in (
            "step_imaging",
            "_prepare_imaging_physical_integration_handler",
        )
    )
    mutated_attributes = {
        target.attr
        for method in imaging_methods
        for node in ast.walk(method)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
        for target in (
            node.targets
            if isinstance(node, ast.Assign)
            else (node.target,)
        )
        if isinstance(target, ast.Attribute)
    }
    assert mutated_attributes.isdisjoint(
        {
            "mission_state",
            "pending_request_ids",
            "completed_request_ids",
            "data_product_ids",
            "controller_state",
            "stored_bytes",
        }
    )


def test_release_public_exports_and_signatures_are_exact() -> None:
    expected_exports = {
        "observation": [
            "GroundTarget",
            "ImagingRequest",
            "ImagingRequestCatalog",
            "ObservationCampaign",
            "ObservationOpportunity",
            "ObservationOpportunityCatalog",
            "ObservationPointing",
            "TargetCatalog",
        ],
        "observation_feasibility": [
            "ObservationManeuverCandidate",
            "ObservationSequenceFeasibilityReason",
            "ObservationSequenceFeasibilityResult",
            "ObservationViewFeasibilityResult",
            "ScheduledObservationExecution",
            "evaluate_observation_sequence_feasibility",
            "evaluate_observation_view_feasibility",
        ],
        "adcs_config": ["AgilePointingConfig", "BoresightSlewTimeAnchor"],
        "adcs": [
            "BoresightAngularSeparationResult",
            "BoresightTransitionResult",
            "CommonFrameBoresightDirection",
            "compute_boresight_angular_separation",
            "compute_boresight_transition",
        ],
        "payload_config": ["OpticalAcquisitionConfig"],
        "payload": [
            "OpticalAcquisitionChannelSelection",
            "OpticalAcquisitionInput",
            "OpticalAcquisitionResult",
            "compute_optical_acquisition",
        ],
        "imaging_feasibility": [
            "ObservationAcquisitionCandidate",
            "ObservationAcquisitionEvaluationResult",
            "evaluate_observation_acquisition",
        ],
        "imaging_resources": [
            "AcquisitionEPSIntervalEnvironment",
            "AcquisitionServiceBounds",
            "AcquisitionServiceStatus",
            "ObservationAcquisitionEPSResult",
            "evaluate_observation_acquisition_eps",
        ],
        "imaging_thermal": [
            "ObservationAcquisitionSingleIntervalThermalProposal",
            "evaluate_observation_acquisition_single_interval_thermal_proposal",
        ],
        "imaging_execution": [
            "ImagingExecutionAuthorizationStatus",
            "ScheduledObservationAcquisitionExecution",
        ],
        "imaging_authorization": [
            "ImagingExecutionAuthorizationResult",
            "evaluate_imaging_engine_step_authorization",
        ],
        "engine": [
            "STEP_PHASE_ORDER",
            "ImagingEngineStepAttempt",
            "SimulationEngine",
            "SimulationPhase",
            "StepResult",
        ],
    }
    modules = {
        name: importlib.import_module(f"ops_sim.v5.{name}")
        for name in RELEASE_MODULES
    }
    historical_exports = {}
    for name in RELEASE_MODULES:
        tree = ast.parse(_v53_final_text(f"ops_sim/v5/{name}.py"))
        exports_assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
        )
        historical_exports[name] = ast.literal_eval(exports_assignment.value)

    assert historical_exports == expected_exports
    assert all(
        all(export_name in modules[name].__all__ for export_name in exports)
        for name, exports in expected_exports.items()
    )

    expected_signatures = {
        "observation.GroundTarget": "(target_id: 'GroundTargetId', latitude_deg: 'float', longitude_deg: 'float') -> None",
        "observation.ImagingRequest": "(request_id: 'ImagingRequestId', target_id: 'GroundTargetId', priority_weight: 'float') -> None",
        "observation.ImagingRequestCatalog": "(requests: 'tuple[ImagingRequest, ...]') -> None",
        "observation.ObservationCampaign": "(targets: 'TargetCatalog', requests: 'ImagingRequestCatalog', opportunities: 'ObservationOpportunityCatalog') -> None",
        "observation.ObservationOpportunity": "(opportunity_id: 'ObservationOpportunityId', request_id: 'ImagingRequestId', window_start_seconds: 'int', window_end_seconds: 'int', imaging_duration_seconds: 'int', pointing: 'ObservationPointing') -> None",
        "observation.ObservationOpportunityCatalog": "(opportunities: 'tuple[ObservationOpportunity, ...]') -> None",
        "observation.ObservationPointing": "(view_angle_from_nadir_deg: 'float', view_azimuth_deg: 'float') -> None",
        "observation.TargetCatalog": "(targets: 'tuple[GroundTarget, ...]') -> None",
        "observation_feasibility.ObservationManeuverCandidate": "(opportunity: 'ObservationOpportunity', common_frame_boresight: 'CommonFrameBoresightDirection') -> None",
        "observation_feasibility.ObservationSequenceFeasibilityReason": "(*values)",
        "observation_feasibility.ObservationSequenceFeasibilityResult": "(previous_opportunity_id: 'ObservationOpportunityId', next_opportunity_id: 'ObservationOpportunityId', previous_end_seconds: 'int', next_latest_start_seconds: 'int', previous_view: 'ObservationViewFeasibilityResult', next_view: 'ObservationViewFeasibilityResult', transition_result: 'BoresightTransitionResult | None', transition_ready_seconds: 'int | float | None', candidate_next_start_seconds: 'int | float | None', feasible: 'bool', reason: 'ObservationSequenceFeasibilityReason') -> None",
        "observation_feasibility.ObservationViewFeasibilityResult": "(opportunity_id: 'ObservationOpportunityId', requested_view_angle_from_nadir_deg: 'float', maximum_view_angle_from_nadir_deg: 'float', feasible: 'bool') -> None",
        "observation_feasibility.ScheduledObservationExecution": "(candidate: 'ObservationManeuverCandidate', scheduled_start_seconds: 'int') -> None",
        "observation_feasibility.evaluate_observation_sequence_feasibility": "(config: 'AgilePointingConfig', previous_execution: 'ScheduledObservationExecution', next_candidate: 'ObservationManeuverCandidate') -> 'ObservationSequenceFeasibilityResult'",
        "observation_feasibility.evaluate_observation_view_feasibility": "(config: 'AgilePointingConfig', opportunity: 'ObservationOpportunity') -> 'ObservationViewFeasibilityResult'",
        "adcs_config.AgilePointingConfig": "(maximum_view_angle_from_nadir_deg: 'ScalarParameter', post_slew_settling_time_seconds: 'ScalarParameter', slew_time_anchors: 'tuple[BoresightSlewTimeAnchor, ...]') -> None",
        "adcs_config.BoresightSlewTimeAnchor": "(anchor_id: 'ADCSSlewAnchorId', angular_separation_deg: 'ScalarParameter', slew_elapsed_time_seconds: 'ScalarParameter') -> None",
        "adcs.BoresightAngularSeparationResult": "(angular_separation_deg: 'float') -> None",
        "adcs.BoresightTransitionResult": "(angular_separation_deg: 'float', lower_anchor_id: 'ADCSSlewAnchorId', upper_anchor_id: 'ADCSSlewAnchorId', interpolation_fraction: 'float', slew_elapsed_time_seconds: 'float', settling_time_seconds: 'float', total_transition_time_seconds: 'float') -> None",
        "adcs.CommonFrameBoresightDirection": "(frame_id: 'ADCSBoresightFrameId', x: 'float', y: 'float', z: 'float') -> None",
        "adcs.compute_boresight_angular_separation": "(start: 'CommonFrameBoresightDirection', end: 'CommonFrameBoresightDirection') -> 'BoresightAngularSeparationResult'",
        "adcs.compute_boresight_transition": "(config: 'AgilePointingConfig', start: 'CommonFrameBoresightDirection', end: 'CommonFrameBoresightDirection') -> 'BoresightTransitionResult'",
        "payload_config.OpticalAcquisitionConfig": "(reference_nadir_swath_width_m: 'ScalarParameter', panchromatic_reference_sample_spacing_m: 'ScalarParameter', multispectral_reference_sample_spacing_m: 'ScalarParameter', multispectral_band_count: 'ScalarParameter', acquisition_bits_per_sample: 'ScalarParameter', acquisition_power_w: 'ScalarParameter', simultaneous_pan_and_multispectral: 'bool') -> None",
        "payload.OpticalAcquisitionChannelSelection": "(*values)",
        "payload.OpticalAcquisitionInput": "(effective_cross_track_width_m: 'float', effective_along_track_length_m: 'float', imaging_duration_seconds: 'int', channel_selection: 'OpticalAcquisitionChannelSelection') -> None",
        "payload.OpticalAcquisitionResult": "(footprint_area_m2: 'float', panchromatic_equivalent_samples: 'float', multispectral_equivalent_samples_per_band: 'float', multispectral_equivalent_samples_total: 'float', total_equivalent_samples: 'float', uncompressed_equivalent_bits: 'float', uncompressed_equivalent_bytes: 'float', requested_acquisition_power_w: 'float', acquisition_energy_wh: 'float') -> None",
        "payload.compute_optical_acquisition": "(config: 'OpticalAcquisitionConfig', acquisition_input: 'OpticalAcquisitionInput') -> 'OpticalAcquisitionResult'",
        "imaging_feasibility.ObservationAcquisitionCandidate": "(maneuver_candidate: 'ObservationManeuverCandidate', acquisition_input: 'OpticalAcquisitionInput') -> None",
        "imaging_feasibility.ObservationAcquisitionEvaluationResult": "(sequence_result: 'ObservationSequenceFeasibilityResult', acquisition_result: 'OpticalAcquisitionResult | None', feasible: 'bool') -> None",
        "imaging_feasibility.evaluate_observation_acquisition": "(agile_pointing_config: 'AgilePointingConfig', optical_acquisition_config: 'OpticalAcquisitionConfig', previous_execution: 'ScheduledObservationExecution', next_candidate: 'ObservationAcquisitionCandidate') -> 'ObservationAcquisitionEvaluationResult'",
        "imaging_resources.AcquisitionEPSIntervalEnvironment": "(sunlit: 'bool', incidence_angle_deg: 'float', non_acquisition_loads: 'PowerLoadBreakdown') -> None",
        "imaging_resources.AcquisitionServiceBounds": "(minimum_served_acquisition_power_w: 'float', maximum_served_acquisition_power_w: 'float', minimum_served_acquisition_energy_wh: 'float', maximum_served_acquisition_energy_wh: 'float', status: 'AcquisitionServiceStatus') -> None",
        "imaging_resources.AcquisitionServiceStatus": "(*values)",
        "imaging_resources.ObservationAcquisitionEPSResult": "(acquisition_evaluation: 'ObservationAcquisitionEvaluationResult', eps_inputs: 'EPSIntervalInputs | None', eps_capability_result: 'EPSCapabilityResult | None', eps_result: 'EPSIntervalResult | None', service_bounds: 'AcquisitionServiceBounds | None') -> None",
        "imaging_resources.evaluate_observation_acquisition_eps": "(agile_pointing_config: 'AgilePointingConfig', optical_acquisition_config: 'OpticalAcquisitionConfig', eps_config: 'EPSConfig', battery_state: 'BatteryState', degradation_state: 'DegradationState', previous_execution: 'ScheduledObservationExecution', next_candidate: 'ObservationAcquisitionCandidate', environment: 'AcquisitionEPSIntervalEnvironment') -> 'ObservationAcquisitionEPSResult'",
        "imaging_thermal.ObservationAcquisitionSingleIntervalThermalProposal": "(electrical_result: 'ObservationAcquisitionEPSResult', routed_internal_heat_result: 'RoutedInternalHeatResult', eps_thermal_coupling_result: 'EPSThermalCouplingResult') -> None",
        "imaging_thermal.evaluate_observation_acquisition_single_interval_thermal_proposal": "(electrical_result: 'ObservationAcquisitionEPSResult', served_power_ledger: 'ServedPowerLedger', routing_config: 'ComponentHeatRoutingConfig', thermal_state: 'ThermalState', thermal_config: 'ThermalNetworkConfig', thermal_inputs: 'ThermalIntervalInputs', external_heat_sources: 'ThermalHeatSourceInputs') -> 'ObservationAcquisitionSingleIntervalThermalProposal'",
        "imaging_execution.ImagingExecutionAuthorizationStatus": "(*values)",
        "imaging_execution.ScheduledObservationAcquisitionExecution": "(candidate: 'ObservationAcquisitionCandidate', scheduled_start_seconds: 'int') -> None",
        "imaging_authorization.ImagingExecutionAuthorizationResult": "(execution: 'ScheduledObservationAcquisitionExecution', electrical_result: 'ObservationAcquisitionEPSResult', thermal_proposal: 'ObservationAcquisitionSingleIntervalThermalProposal | None', status: 'ImagingExecutionAuthorizationStatus') -> None",
        "imaging_authorization.evaluate_imaging_engine_step_authorization": "(context: 'SimulationContext', previous_execution: 'ScheduledObservationExecution', execution: 'ScheduledObservationAcquisitionExecution', environment: 'AcquisitionEPSIntervalEnvironment', routing_config: 'ComponentHeatRoutingConfig', thermal_inputs: 'ThermalIntervalInputs', external_heat_sources: 'ThermalHeatSourceInputs') -> 'ImagingExecutionAuthorizationResult'",
        "engine.ImagingEngineStepAttempt": "(authorization_result: 'ImagingExecutionAuthorizationResult', step_result: 'StepResult | None') -> None",
        "engine.SimulationEngine": "()",
        "engine.SimulationPhase": "(*values)",
        "engine.StepResult": "(start_time_seconds: 'int', end_time_seconds: 'int', dt_seconds: 'int', executed_phases: 'tuple[SimulationPhase, ...]', eps_result: 'EPSIntervalResult | None' = None, thermal_coupling_result: 'EPSThermalCouplingResult | None' = None, battery_degradation_result: 'BatteryDegradationTransition | None' = None, solar_degradation_result: 'SolarDegradationTransition | None' = None, eps_capability_result: 'EPSCapabilityResult | None' = None, battery_capacity_reconciliation_result: 'BatteryCapacityReconciliationResult | None' = None) -> None",
        "engine.SimulationEngine.step": "(self, context: 'SimulationContext', *, eps_inputs: 'EPSIntervalInputs | None' = None, thermal_inputs: 'ThermalIntervalInputs | None' = None, heat_source_inputs: 'ThermalHeatSourceInputs | None' = None, solar_degradation_forcing: 'SolarDegradationForcingInput | None' = None) -> 'StepResult'",
        "engine.SimulationEngine.step_imaging": "(self, context: 'SimulationContext', previous_execution: 'ScheduledObservationExecution', execution: 'ScheduledObservationAcquisitionExecution', *, environment: 'AcquisitionEPSIntervalEnvironment', routing_config: 'ComponentHeatRoutingConfig', thermal_inputs: 'ThermalIntervalInputs', external_heat_sources: 'ThermalHeatSourceInputs', solar_degradation_forcing: 'SolarDegradationForcingInput | None' = None) -> 'ImagingEngineStepAttempt'",
    }
    actual_signatures = {
        f"{module_name}.{export_name}": str(signature(getattr(module, export_name)))
        for module_name, module in modules.items()
        for export_name in expected_exports[module_name]
        if callable(getattr(module, export_name))
    }
    actual_signatures["engine.SimulationEngine.step"] = str(
        signature(SimulationEngine.step)
    )
    actual_signatures["engine.SimulationEngine.step_imaging"] = str(
        signature(SimulationEngine.step_imaging)
    )
    assert actual_signatures == expected_signatures
    assert tuple(field.name for field in fields(ImagingEngineStepAttempt)) == (
        "authorization_result",
        "step_result",
    )
    assert tuple(field.name for field in fields(CheckpointState)).count(
        "schema_version"
    ) == 1
    assert "CURRENT_CHECKPOINT_SCHEMA_VERSION = 3" in _v53_final_text(
        "ops_sim/v5/checkpoint.py"
    )


def test_release_documents_status_provenance_and_decisions_are_consistent() -> None:
    audit = _v53_final_text("V5_3_RELEASE_AUDIT.md")
    status = _v53_final_text("MODEL_STATUS.md")
    decisions = _v53_final_text("V5_DECISION_LOG.md")
    sources = _v53_final_text("V5_SOURCE_REGISTER.md")
    headings = [
        _normalized_words(line.lstrip("# "))
        for line in audit.splitlines()
        if line.startswith("#")
    ]
    required_heading_words = (
        ("release", "identity"),
        ("implemented", "scope"),
        ("explicit", "non", "scope"),
        ("source", "provenance", "boundary"),
        ("observation", "domain", "checks"),
        ("adcs", "geometry", "timing", "checks"),
        ("optical", "acquisition", "checks"),
        ("eps", "service", "bound", "checks"),
        ("thermal", "routing", "checks"),
        ("transactional", "engine", "checks"),
        ("rollback", "nonauthorization", "matrix"),
        ("checkpoint", "replay", "checks"),
        ("deterministic", "demo", "evidence"),
        ("numerical", "limitations"),
        ("deferred", "work"),
        ("release", "verdict"),
    )
    assert all(
        any(all(word in heading for word in words) for heading in headings)
        for words in required_heading_words
    )
    normalized_audit = _normalized_words(audit)

    def ownership_clause(section: str, milestone: str) -> str:
        match = re.search(
            rf"(?ms)^- {re.escape(milestone)} owns\b.*?"
            rf"(?=^- V5\.\d+ owns\b|\n\n|\Z)",
            section,
        )
        assert match is not None, f"missing {milestone} ownership clause"
        return _normalized_words(match.group(0))

    audit_deferred = audit.partition("## Deferred work")[2].partition(
        "## Release verdict"
    )[0]
    status_current = status.partition(
        "## Current V5.3 release-candidate status"
    )[2].partition("## Historical status")[0]
    for ownership_section in (audit_deferred, status_current):
        v54 = ownership_clause(ownership_section, "V5.4")
        v55 = ownership_clause(ownership_section, "V5.5")
        v56 = ownership_clause(ownership_section, "V5.6")
        v57 = ownership_clause(ownership_section, "V5.7")
        v58 = ownership_clause(ownership_section, "V5.8")

        assert all(
            word in v54
            for word in (
                "onboard",
                "data",
                "storage",
                "obc",
                "compression",
                "packet",
                "file",
                "capacity",
                "state",
                "bookkeeping",
            )
        )
        assert all(
            word not in v54
            for word in ("communications", "downlink", "transmission", "delivery")
        )
        assert all(
            word in v55
            for word in (
                "communications",
                "link",
                "contact",
                "capacity",
                "downlink",
                "transmission",
                "delivery",
            )
        )
        assert all(
            word in v56
            for word in ("orbit", "opportunities", "frame", "conversion", "coupling")
        )
        assert all(
            word in v57
            for word in (
                "missionrequestid",
                "imagingrequestid",
                "binding",
                "mission",
                "product",
                "completion",
                "controller",
                "scheduling",
            )
        )
        assert all(
            word in v58
            for word in (
                "variable",
                "duration",
                "execution",
                "substeps",
                "multirate",
                "event",
                "refinement",
            )
        )

    for words in (
        ("immutable", "ground", "targets", "imaging", "requests", "opportunities"),
        ("local", "view", "angle", "feasibility"),
        ("common", "frame", "boresight", "directions"),
        ("piecewise", "linear", "slew", "settling"),
        ("sample", "grid", "level", "1", "simultaneous", "pan", "ms"),
        ("requested", "acquisition", "power", "energy"),
        ("allocation", "free", "electrical", "service", "bounds"),
        ("served", "component", "thermal", "routing"),
        ("battery", "conversion", "heat"),
        ("fixed", "step", "authorization", "atomic", "step", "imaging"),
        ("degradation", "reconciliation", "transaction", "tail"),
        ("deterministic", "end", "to", "end", "demonstration"),
    ):
        assert all(word in normalized_audit for word in words)
    for words in (
        ("orbit", "derived", "observation", "opportunities"),
        ("opportunity", "local", "inertial", "common", "frame", "conversion"),
        ("reaction", "wheel", "torque", "momentum"),
        ("adcs", "electrical", "slew", "energy", "model"),
        ("missionrequestid", "imagingrequestid", "binding"),
        ("shortfall", "component", "allocation", "policy"),
        ("variable", "duration", "engine", "execution"),
        ("universal", "timestep", "convergence", "proof"),
    ):
        assert all(word in normalized_audit for word in words)
    assert (
        "thermal remains explicit euler" in normalized_audit
        or "thermal integration remains explicit euler" in normalized_audit
    )
    assert (
        "does not establish variable duration timestep convergence"
        in normalized_audit
        or "establishes no variable duration timestep convergence"
        in normalized_audit
    )
    assert "v5 8" in normalized_audit and "multirate" in normalized_audit
    assert (
        "V5.3 RELEASE-CANDIDATE PASS — ready for human actual review and "
        "`v5.3-final` tag."
    ) in " ".join(audit.split())
    for words in (
        ("sequence", "infeasible", "stepresult", "none"),
        ("electrical", "full", "service", "impossible"),
        ("electrical", "allocation", "required"),
        ("boundary", "mismatch"),
        ("duration", "dt", "mismatch"),
        ("frame", "mismatch"),
        ("unsupported", "slew", "envelope"),
        ("invalid", "acquisition", "composition"),
        ("thermal", "failure"),
        ("degradation", "failure"),
        ("reconciliation", "failure"),
        ("final", "context", "validation", "failure"),
        ("stepresult", "validation", "failure"),
    ):
        assert all(word in normalized_audit for word in words)

    normalized_status = _normalized_words(status)
    assert all(
        phrase in normalized_status
        for phrase in ("implemented v5 3", "release candidate complete")
    )
    assert all(
        word in normalized_status for word in ("pending", "final", "human", "review")
    )
    assert "v5 3 final tag already exists" not in normalized_status
    assert "already tagged v5 3 final" not in normalized_status

    expected_decisions = (
        "## D280 — F4B is verification/freeze only and changes no production model",
        "## D281 — V5.3 release audit covers geometry, acquisition, EPS bounds, thermal, and transactional execution",
        "## D282 — V5.3 final evidence includes all supported nonauthorization and rollback classes",
        "## D283 — Sample-grid quantities remain acquisition proxies, not storage/product truth",
        "## D284 — Mission/request binding, storage, controller, orbit conversion, and variable-duration integration remain deferred",
        "## D285 — No misleading V5.3 timestep-refinement claim is made because acquisition duration is currently tied to engine dt",
        "## D286 — Checkpoint schema remains 3 and imaging replay requires explicit caller-resupplied inputs",
        "## D287 — V5.3 is release-candidate complete pending human review and tag",
    )
    assert all(decisions.count(heading) == 1 for heading in expected_decisions)
    positions = [decisions.index(heading) for heading in expected_decisions]
    assert positions == sorted(positions)
    assert decisions.index("## D279 ") < positions[0]
    assert decisions.count("## D280 ") == decisions.count("## D287 ") == 1
    decision_headings = tuple(
        line
        for line in decisions.splitlines()
        if re.fullmatch(r"## D\d{3} .+", line)
    )
    first_f4b = decision_headings.index(expected_decisions[0])
    assert decision_headings[first_f4b:first_f4b + 8] == expected_decisions

    s005 = sources.partition("### S005 ")[2].partition("### S006 ")[0]
    normalized_s005 = _normalized_words(s005)
    assert "v5 3f4b" in normalized_s005
    assert "no new physical source or value" in normalized_s005
    assert "no new equation" in normalized_s005
    assert "no new literature" in normalized_s005
    assert "270 mbit s" in normalized_s005 and "telemetry" in normalized_s005
    assert "sample grid" in normalized_s005 and "level 1" in normalized_s005
    assert "storage" in normalized_s005 and "mission" in normalized_s005
    assert "explicit euler" in normalized_s005

    # Airbus mission-specific values and WMO instrument evidence remain
    # separately identified rather than silently merged into one source.
    assert "airbus" in normalized_audit and "wmo" in normalized_audit
    for phrase in (
        "20 km nadir swath",
        "1 m pan",
        "simultaneous acquisition",
        "12 bit sample",
        "20 2000 km strip",
        "270 mbit s",
        "35 viewing",
        "60 in 90 s",
        "naomi pushbroom",
        "7000 pan",
        "1750 ms",
        "90 w candidate",
    ):
        assert phrase in normalized_audit
    assert all(word in normalized_audit for word in ("four", "4 m", "ms", "bands"))
    assert any(
        phrase in normalized_audit
        for phrase in ("remain distinct", "kept distinct", "not silently merged")
    )


def test_release_audit_contains_final_observed_counts() -> None:
    audit = AUDIT_PATH.read_text(encoding="utf-8")
    assert "COUNT_PENDING" not in audit
