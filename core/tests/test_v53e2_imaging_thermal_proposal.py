"""Single-interval optical-acquisition thermal proposals for V5.3E2."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from inspect import Parameter, signature
from pathlib import Path
import subprocess

import pytest

import ops_sim.v5.imaging_thermal as imaging_thermal_module
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
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    ADCSSlewAnchorId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
    SubsystemConfigurationId,
    ThermalNodeId,
)
from ops_sim.v5.imaging_feasibility import ObservationAcquisitionCandidate
from ops_sim.v5.imaging_resources import (
    AcquisitionEPSIntervalEnvironment,
    AcquisitionServiceStatus,
    ObservationAcquisitionEPSResult,
    evaluate_observation_acquisition_eps,
)
from ops_sim.v5.imaging_thermal import (
    ObservationAcquisitionSingleIntervalThermalProposal,
    evaluate_observation_acquisition_single_interval_thermal_proposal,
)
from ops_sim.v5.observation import ObservationOpportunity, ObservationPointing
from ops_sim.v5.observation_feasibility import (
    ObservationManeuverCandidate,
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
    ThermalNodeState,
    ThermalState,
)
from ops_sim.v5.thermal import (
    ThermalIntervalInputs,
    ThermalNodeBoundaryInput,
)
from ops_sim.v5.thermal_config import (
    ThermalNetworkConfig,
    ThermalNodeConfig,
)
from ops_sim.v5.thermal_coupling import (
    EPSThermalCouplingResult,
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
    compute_eps_thermal_interval_transition,
)
from ops_sim.v5.thermal_routing import (
    ComponentHeatRoute,
    ComponentHeatRoutingConfig,
    ElectricalLoadComponent,
    RoutedInternalHeatResult,
    ServedComponentPower,
    ServedPowerLedger,
    compose_routed_internal_heat_sources,
    compute_routed_internal_heat,
)


ROOT = Path(__file__).resolve().parents[1]
E2_PATH = ROOT / "ops_sim" / "v5" / "imaging_thermal.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
COMPONENTS = tuple(ElectricalLoadComponent)
LOAD_FIELD_BY_COMPONENT = {
    ElectricalLoadComponent.BASE_BUS: "base_bus_w",
    ElectricalLoadComponent.OBC: "obc_w",
    ElectricalLoadComponent.ADCS: "adcs_w",
    ElectricalLoadComponent.PAYLOAD: "payload_w",
    ElectricalLoadComponent.COMMUNICATIONS: "communications_w",
    ElectricalLoadComponent.THERMAL_CONTROL: "thermal_control_w",
    ElectricalLoadComponent.PROPULSION: "propulsion_w",
}
DEFAULT_FRACTIONS = {
    ElectricalLoadComponent.BASE_BUS: 1.0,
    ElectricalLoadComponent.OBC: 1.0,
    ElectricalLoadComponent.ADCS: 0.8,
    ElectricalLoadComponent.PAYLOAD: 0.5,
    ElectricalLoadComponent.COMMUNICATIONS: 0.4,
    ElectricalLoadComponent.THERMAL_CONTROL: 1.0,
    ElectricalLoadComponent.PROPULSION: 0.2,
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


def _agile_config() -> AgilePointingConfig:
    return AgilePointingConfig(
        _parameter(
            "adcs.pointing.maximum-view-angle-from-nadir",
            "deg",
            35.0,
        ),
        _parameter("adcs.pointing.post-slew-settling-time", "s", 5.0),
        (_anchor("zero", 0.0, 0.0), _anchor("ninety", 90.0, 80.0)),
    )


def _optical_config(*, acquisition_power_w: object = 90.0):
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
        True,
    )


def _eps_config(
    *,
    max_discharge_w: object = 1000.0,
    discharge_efficiency: object = 1.0,
) -> EPSConfig:
    return EPSConfig(
        SubsystemConfigurationId("e2-eps"),
        BatteryConfig(
            SubsystemConfigurationId("e2-battery"),
            _parameter("eps.battery.nominal-energy", "Wh", 1000.0),
            _parameter("eps.battery.charge-efficiency", "1", 1.0),
            _parameter(
                "eps.battery.discharge-efficiency",
                "1",
                discharge_efficiency,
            ),
            _parameter("eps.battery.max-charge-input-power", "W", 1000.0),
            _parameter(
                "eps.battery.max-discharge-output-power",
                "W",
                max_discharge_w,
            ),
        ),
        SolarArrayConfig(
            SubsystemConfigurationId("e2-solar"),
            _parameter("eps.solar-array.nominal-generation", "W", 1000.0),
        ),
    )


def _degradation() -> DegradationState:
    return DegradationState(
        BatteryDegradationState(1.0, 0.0),
        SolarDegradationState(1.0),
    )


def _opportunity(
    value: str,
    *,
    window_start_seconds: int,
    window_end_seconds: int,
    duration_seconds: int,
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


def _direction() -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId("e2-common-frame"),
        0.0,
        0.0,
        1.0,
    )


def _previous_execution() -> ScheduledObservationExecution:
    return ScheduledObservationExecution(
        ObservationManeuverCandidate(
            _opportunity(
                "previous",
                window_start_seconds=0,
                window_end_seconds=60,
                duration_seconds=20,
            ),
            _direction(),
        ),
        0,
    )


def _next_candidate(
    *,
    duration_seconds: int = 23,
    view_angle_deg: object = 10.0,
) -> ObservationAcquisitionCandidate:
    opportunity = _opportunity(
        "next",
        window_start_seconds=100,
        window_end_seconds=200,
        duration_seconds=duration_seconds,
        view_angle_deg=view_angle_deg,
    )
    return ObservationAcquisitionCandidate(
        ObservationManeuverCandidate(opportunity, _direction()),
        OpticalAcquisitionInput(
            20.0,
            40.0,
            duration_seconds,
            OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        ),
    )


def _loads(
    *,
    base_bus_w: object = 10.0,
    obc_w: object = 5.0,
    adcs_w: object = 3.0,
    payload_w: object = 15.0,
    communications_w: object = 2.0,
    thermal_control_w: object = 4.0,
    propulsion_w: object = 1.0,
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


def _electrical_result(
    *,
    max_discharge_w: object = 1000.0,
    discharge_efficiency: object = 1.0,
    duration_seconds: int = 23,
    view_angle_deg: object = 10.0,
    non_acquisition_loads: PowerLoadBreakdown | None = None,
) -> ObservationAcquisitionEPSResult:
    return evaluate_observation_acquisition_eps(
        _agile_config(),
        _optical_config(),
        _eps_config(
            max_discharge_w=max_discharge_w,
            discharge_efficiency=discharge_efficiency,
        ),
        BatteryState(500.0),
        _degradation(),
        _previous_execution(),
        _next_candidate(
            duration_seconds=duration_seconds,
            view_angle_deg=view_angle_deg,
        ),
        AcquisitionEPSIntervalEnvironment(
            False,
            0.0,
            _loads()
            if non_acquisition_loads is None
            else non_acquisition_loads,
        ),
    )


def _node(
    name: str,
    *,
    heat_capacity: object = 1_000_000.0,
    emissivity: object = 0.0,
    radiating_area: object = 1.0,
) -> ThermalNodeConfig:
    prefix = f"thermal.node.{name}"
    return ThermalNodeConfig(
        ThermalNodeId(name),
        _parameter(f"{prefix}.heat-capacity", "J/K", heat_capacity),
        _parameter(f"{prefix}.emissivity", "1", emissivity),
        _parameter(f"{prefix}.radiating-area", "m^2", radiating_area),
        _parameter(f"{prefix}.operating-min-temperature", "K", 270.0),
        _parameter(f"{prefix}.operating-max-temperature", "K", 320.0),
        _parameter(f"{prefix}.survival-min-temperature", "K", 250.0),
        _parameter(f"{prefix}.survival-max-temperature", "K", 340.0),
    )


def _network(
    *,
    payload_heat_capacity: object = 1_000_000.0,
    payload_emissivity: object = 0.0,
) -> ThermalNetworkConfig:
    return ThermalNetworkConfig(
        (
            _node("bus"),
            _node("battery"),
            _node(
                "payload",
                heat_capacity=payload_heat_capacity,
                emissivity=payload_emissivity,
            ),
        ),
        (),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("payload"),
    )


def _thermal_state(
    names: tuple[str, ...] = ("bus", "battery", "payload"),
) -> ThermalState:
    return ThermalState(
        tuple(ThermalNodeState(ThermalNodeId(name), 300.0) for name in names)
    )


def _thermal_inputs(
    names: tuple[str, ...] = ("bus", "battery", "payload"),
    *,
    payload_sink_temperature_k: object = 300.0,
) -> ThermalIntervalInputs:
    return ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(
                ThermalNodeId(name),
                (
                    payload_sink_temperature_k
                    if name == "payload"
                    else 300.0
                ),
            )
            for name in names
        )
    )


def _external_sources(
    names: tuple[str, ...] = ("bus", "battery", "payload"),
    *,
    internal_by_node: dict[str, object] | None = None,
    solar_by_node: dict[str, object] | None = None,
    albedo_by_node: dict[str, object] | None = None,
    earth_ir_by_node: dict[str, object] | None = None,
) -> ThermalHeatSourceInputs:
    internal = {} if internal_by_node is None else internal_by_node
    solar = {} if solar_by_node is None else solar_by_node
    albedo = {} if albedo_by_node is None else albedo_by_node
    earth_ir = {} if earth_ir_by_node is None else earth_ir_by_node
    return ThermalHeatSourceInputs(
        tuple(
            ThermalNodeHeatSourceInput(
                ThermalNodeId(name),
                internal.get(name, 0.0),
                solar.get(name, 0.0),
                albedo.get(name, 0.0),
                earth_ir.get(name, 0.0),
            )
            for name in names
        )
    )


def _fraction(
    component: ElectricalLoadComponent,
    value: object,
) -> ScalarParameter:
    return _parameter(
        f"thermal.routing.{component.value}.retained-heat-fraction",
        "1",
        value,
    )


def _routing(
    *,
    fractions: dict[ElectricalLoadComponent, object] | None = None,
    node_names: dict[ElectricalLoadComponent, str] | None = None,
) -> ComponentHeatRoutingConfig:
    active_fractions = (
        DEFAULT_FRACTIONS if fractions is None else fractions
    )
    active_nodes = {} if node_names is None else node_names
    return ComponentHeatRoutingConfig(
        tuple(
            ComponentHeatRoute(
                component,
                ThermalNodeId(
                    active_nodes.get(
                        component,
                        (
                            "payload"
                            if component is ElectricalLoadComponent.PAYLOAD
                            else "bus"
                        ),
                    )
                ),
                _fraction(
                    component,
                    active_fractions.get(component, 0.0),
                ),
            )
            for component in COMPONENTS
        )
    )


def _served_ledger(
    electrical_result: ObservationAcquisitionEPSResult,
    *,
    served_by_component: dict[ElectricalLoadComponent, object] | None = None,
) -> ServedPowerLedger:
    assert electrical_result.eps_inputs is not None
    loads = electrical_result.eps_inputs.load_breakdown
    active_served = (
        {} if served_by_component is None else served_by_component
    )
    return ServedPowerLedger(
        tuple(
            ServedComponentPower(
                component,
                getattr(loads, LOAD_FIELD_BY_COMPONENT[component]),
                active_served.get(
                    component,
                    getattr(loads, LOAD_FIELD_BY_COMPONENT[component]),
                ),
            )
            for component in COMPONENTS
        )
    )


def _arguments(
    *,
    electrical_result: ObservationAcquisitionEPSResult | None = None,
    served_power_ledger: ServedPowerLedger | None = None,
    routing_config: ComponentHeatRoutingConfig | None = None,
    thermal_state: ThermalState | None = None,
    thermal_config: ThermalNetworkConfig | None = None,
    thermal_inputs: ThermalIntervalInputs | None = None,
    external_heat_sources: ThermalHeatSourceInputs | None = None,
) -> dict[str, object]:
    electrical = (
        _electrical_result()
        if electrical_result is None
        else electrical_result
    )
    if served_power_ledger is None:
        served_power_ledger = _served_ledger(electrical)
    return {
        "electrical_result": electrical,
        "served_power_ledger": served_power_ledger,
        "routing_config": _routing()
        if routing_config is None
        else routing_config,
        "thermal_state": _thermal_state()
        if thermal_state is None
        else thermal_state,
        "thermal_config": _network()
        if thermal_config is None
        else thermal_config,
        "thermal_inputs": _thermal_inputs()
        if thermal_inputs is None
        else thermal_inputs,
        "external_heat_sources": _external_sources()
        if external_heat_sources is None
        else external_heat_sources,
    }


def _evaluate_e2(
    **changes: object,
) -> ObservationAcquisitionSingleIntervalThermalProposal:
    return evaluate_observation_acquisition_single_interval_thermal_proposal(
        **_arguments(**changes)
    )


def _component_ledgers(result: RoutedInternalHeatResult):
    return {ledger.component: ledger for ledger in result.component_ledgers}


def _node_heat_ledgers(result: EPSThermalCouplingResult):
    return {
        ledger.node_id.value: ledger for ledger in result.node_heat_ledgers
    }


def _node_transitions(result: EPSThermalCouplingResult):
    return {
        item.node_id.value: item
        for item in result.thermal_result.node_transitions
    }


def test_e2_result_has_exact_frozen_slotted_required_fields() -> None:
    result = _evaluate_e2()

    assert tuple(
        field.name
        for field in fields(
            ObservationAcquisitionSingleIntervalThermalProposal
        )
    ) == (
        "electrical_result",
        "routed_internal_heat_result",
        "eps_thermal_coupling_result",
    )
    assert (
        ObservationAcquisitionSingleIntervalThermalProposal
        .__dataclass_params__.frozen
    )
    assert not hasattr(result, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(
            ObservationAcquisitionSingleIntervalThermalProposal
        )
    )
    with pytest.raises(FrozenInstanceError):
        result.electrical_result = object()


def test_public_signature_is_exact_required_and_has_no_thermal_dt() -> None:
    parameters = signature(
        evaluate_observation_acquisition_single_interval_thermal_proposal
    ).parameters

    assert tuple(parameters) == (
        "electrical_result",
        "served_power_ledger",
        "routing_config",
        "thermal_state",
        "thermal_config",
        "thermal_inputs",
        "external_heat_sources",
    )
    assert "thermal_dt_seconds" not in parameters
    assert "dt_seconds" not in parameters
    assert all(
        parameter.kind is Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is Parameter.empty
        for parameter in parameters.values()
    )


@pytest.mark.parametrize(
    "argument_name",
    (
        "electrical_result",
        "served_power_ledger",
        "routing_config",
        "thermal_state",
        "thermal_config",
        "thermal_inputs",
        "external_heat_sources",
    ),
)
def test_public_function_requires_exact_top_level_types(argument_name) -> None:
    arguments = _arguments()
    arguments[argument_name] = object()

    with pytest.raises(TypeError, match=argument_name):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )


def test_result_requires_exact_nested_types() -> None:
    result = _evaluate_e2()

    for field_name in (
        "electrical_result",
        "routed_internal_heat_result",
        "eps_thermal_coupling_result",
    ):
        with pytest.raises(TypeError, match=field_name):
            replace(result, **{field_name: object()})


def test_result_revalidates_all_three_nested_reviewed_results() -> None:
    result = _evaluate_e2()

    corrupted_electrical = deepcopy(result.electrical_result)
    assert corrupted_electrical.eps_result is not None
    object.__setattr__(corrupted_electrical.eps_result.loads, "payload_w", -1.0)
    with pytest.raises(ValueError, match="payload_w"):
        replace(result, electrical_result=corrupted_electrical)

    corrupted_routed = deepcopy(result.routed_internal_heat_result)
    routed_ledger = corrupted_routed.component_ledgers[0]
    object.__setattr__(
        routed_ledger,
        "retained_heat_w",
        routed_ledger.retained_heat_w + 1.0,
    )
    with pytest.raises(ValueError, match="retained_heat_w"):
        replace(result, routed_internal_heat_result=corrupted_routed)

    corrupted_coupling = deepcopy(result.eps_thermal_coupling_result)
    node_ledger = corrupted_coupling.node_heat_ledgers[0]
    object.__setattr__(
        node_ledger,
        "total_applied_heat_w",
        node_ledger.total_applied_heat_w + 1.0,
    )
    with pytest.raises(ValueError, match="total_applied_heat_w"):
        replace(result, eps_thermal_coupling_result=corrupted_coupling)


def test_function_revalidates_inputs_before_routing(monkeypatch) -> None:
    arguments = _arguments()
    state = arguments["thermal_state"]
    assert type(state) is ThermalState
    object.__setattr__(state.node_states[0], "temperature_k", float("nan"))
    monkeypatch.setattr(
        imaging_thermal_module,
        "compute_routed_internal_heat",
        lambda *args, **kwargs: pytest.fail("routing must not be reached"),
    )

    with pytest.raises(ValueError, match="temperature_k"):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )


def test_infeasible_e1_is_rejected_before_any_thermal_helper(monkeypatch) -> None:
    electrical = _electrical_result(view_angle_deg=36.0)
    assert electrical.acquisition_evaluation.feasible is False
    assert electrical.eps_inputs is None
    calls = {"route": 0, "compose": 0, "couple": 0}

    def fail(name):
        def called(*args, **kwargs):
            calls[name] += 1
            pytest.fail(f"{name} must not be reached")

        return called

    monkeypatch.setattr(
        imaging_thermal_module,
        "compute_routed_internal_heat",
        fail("route"),
    )
    monkeypatch.setattr(
        imaging_thermal_module,
        "compose_routed_internal_heat_sources",
        fail("compose"),
    )
    monkeypatch.setattr(
        imaging_thermal_module,
        "compute_eps_thermal_interval_transition",
        fail("couple"),
    )
    arguments = _arguments(
        electrical_result=electrical,
        served_power_ledger=ServedPowerLedger(
            tuple(
                ServedComponentPower(component, 0.0, 0.0)
                for component in COMPONENTS
            )
        ),
    )

    with pytest.raises(
        ValueError,
        match="feasible acquisition and EPS proposal",
    ):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )
    assert calls == {"route": 0, "compose": 0, "couple": 0}


def test_result_constructor_rejects_infeasible_electrical_result() -> None:
    valid = _evaluate_e2()
    infeasible = _electrical_result(view_angle_deg=36.0)

    with pytest.raises(
        ValueError,
        match="feasible acquisition and EPS proposal",
    ):
        replace(valid, electrical_result=infeasible)


def test_missing_required_e1_eps_field_uses_intentional_precondition_error(
    monkeypatch,
) -> None:
    electrical = _electrical_result()
    ledger = _served_ledger(electrical)
    object.__setattr__(electrical, "eps_result", None)
    monkeypatch.setattr(
        imaging_thermal_module,
        "compute_routed_internal_heat",
        lambda *args, **kwargs: pytest.fail("routing must not be reached"),
    )

    with pytest.raises(
        ValueError,
        match="feasible acquisition and EPS proposal",
    ):
        _evaluate_e2(
            electrical_result=electrical,
            served_power_ledger=ledger,
        )


def test_reviewed_helpers_are_called_once_in_required_order(monkeypatch) -> None:
    arguments = _arguments()
    electrical = arguments["electrical_result"]
    served = arguments["served_power_ledger"]
    routing = arguments["routing_config"]
    thermal_state = arguments["thermal_state"]
    thermal_config = arguments["thermal_config"]
    thermal_inputs = arguments["thermal_inputs"]
    external = arguments["external_heat_sources"]
    assert type(electrical) is ObservationAcquisitionEPSResult
    assert electrical.eps_inputs is not None
    assert electrical.eps_result is not None
    original_route = imaging_thermal_module.compute_routed_internal_heat
    original_compose = (
        imaging_thermal_module.compose_routed_internal_heat_sources
    )
    original_couple = (
        imaging_thermal_module.compute_eps_thermal_interval_transition
    )
    calls = []

    def route(loads, ledger, config, network, *, eps_result):
        calls.append("route")
        assert loads is electrical.eps_inputs.load_breakdown
        assert ledger is served
        assert config is routing
        assert network is thermal_config
        assert eps_result is electrical.eps_result
        return original_route(
            loads,
            ledger,
            config,
            network,
            eps_result=eps_result,
        )

    def compose(routed_heat, heat_sources):
        calls.append("compose")
        assert calls == ["route", "compose"]
        assert heat_sources is external
        return original_compose(routed_heat, heat_sources)

    def couple(
        state,
        config,
        inputs,
        heat_sources,
        eps_result,
        *,
        dt_seconds,
    ):
        calls.append("couple")
        assert calls == ["route", "compose", "couple"]
        assert state is thermal_state
        assert config is thermal_config
        assert inputs is thermal_inputs
        assert eps_result is electrical.eps_result
        assert dt_seconds == 23
        return original_couple(
            state,
            config,
            inputs,
            heat_sources,
            eps_result,
            dt_seconds=dt_seconds,
        )

    monkeypatch.setattr(
        imaging_thermal_module,
        "compute_routed_internal_heat",
        route,
    )
    monkeypatch.setattr(
        imaging_thermal_module,
        "compose_routed_internal_heat_sources",
        compose,
    )
    monkeypatch.setattr(
        imaging_thermal_module,
        "compute_eps_thermal_interval_transition",
        couple,
    )

    result = (
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )
    )

    assert calls == ["route", "compose", "couple"]
    assert result.electrical_result is electrical
    assert result.eps_thermal_coupling_result.thermal_result.dt_seconds == 23


def test_explicit_served_payload_routes_to_hand_calculated_heat() -> None:
    electrical = _electrical_result(max_discharge_w=105.0)
    assert electrical.eps_inputs is not None
    assert electrical.eps_result is not None
    assert electrical.eps_inputs.load_breakdown.payload_w == 105.0
    ledger = _served_ledger(
        electrical,
        served_by_component={ElectricalLoadComponent.PAYLOAD: 80.0},
    )

    result = _evaluate_e2(
        electrical_result=electrical,
        served_power_ledger=ledger,
    )
    payload = _component_ledgers(
        result.routed_internal_heat_result
    )[ElectricalLoadComponent.PAYLOAD]

    assert electrical.eps_result.battery.served_load_w == 105.0
    assert payload.requested_power_w == 105.0
    assert payload.served_power_w == 80.0
    assert payload.retained_heat_fraction == 0.5
    assert payload.retained_heat_w == 40.0
    assert payload.thermal_node_id == ThermalNodeId("payload")


def test_routed_internal_heat_replaces_placeholder_and_preserves_external_heat(
) -> None:
    electrical = _electrical_result(max_discharge_w=105.0)
    ledger = _served_ledger(
        electrical,
        served_by_component={ElectricalLoadComponent.PAYLOAD: 80.0},
    )
    external = _external_sources(
        internal_by_node={"payload": 999.0},
        solar_by_node={"payload": 1.25},
        albedo_by_node={"payload": 2.5},
        earth_ir_by_node={"payload": 3.75},
    )

    result = _evaluate_e2(
        electrical_result=electrical,
        served_power_ledger=ledger,
        external_heat_sources=external,
    )
    payload = _node_heat_ledgers(
        result.eps_thermal_coupling_result
    )["payload"]

    assert payload.internal_dissipation_w == 40.0
    assert payload.internal_dissipation_w != 999.0 + 40.0
    assert payload.absorbed_solar_w == 1.25
    assert payload.absorbed_albedo_w == 2.5
    assert payload.absorbed_earth_ir_w == 3.75
    assert payload.battery_conversion_heat_w == 0.0
    assert payload.total_applied_heat_w == 47.5


def test_battery_conversion_heat_matches_direct_v52_coupling_once() -> None:
    electrical = _electrical_result(discharge_efficiency=0.8)
    assert electrical.eps_inputs is not None
    assert electrical.eps_result is not None
    ledger = _served_ledger(electrical)
    routing = _routing()
    thermal_config = _network()
    thermal_state = _thermal_state()
    thermal_inputs = _thermal_inputs()
    external = _external_sources()
    dt_seconds = electrical.eps_result.battery.dt_seconds

    direct_routed = compute_routed_internal_heat(
        electrical.eps_inputs.load_breakdown,
        ledger,
        routing,
        thermal_config,
        eps_result=electrical.eps_result,
    )
    direct_composed = compose_routed_internal_heat_sources(
        direct_routed,
        external,
    )
    direct_coupling = compute_eps_thermal_interval_transition(
        thermal_state,
        thermal_config,
        thermal_inputs,
        direct_composed,
        electrical.eps_result,
        dt_seconds=dt_seconds,
    )
    result = _evaluate_e2(
        electrical_result=electrical,
        served_power_ledger=ledger,
        routing_config=routing,
        thermal_state=thermal_state,
        thermal_config=thermal_config,
        thermal_inputs=thermal_inputs,
        external_heat_sources=external,
    )

    assert result.eps_thermal_coupling_result == direct_coupling
    ledgers = result.eps_thermal_coupling_result.node_heat_ledgers
    battery_heat = tuple(
        item.battery_conversion_heat_w
        for item in ledgers
        if item.battery_conversion_heat_w > 0
    )
    expected_heat_w = (
        electrical.eps_result.battery.conversion_loss_wh
        * 3600
        / dt_seconds
    )
    assert battery_heat == (expected_heat_w,)
    assert _node_heat_ledgers(
        result.eps_thermal_coupling_result
    )["battery"].battery_conversion_heat_w == expected_heat_w


def test_e2_inherits_exact_acquisition_eps_duration() -> None:
    electrical = _electrical_result(duration_seconds=23)
    assert electrical.eps_result is not None

    result = _evaluate_e2(electrical_result=electrical)

    assert electrical.eps_result.battery.dt_seconds == 23
    assert result.eps_thermal_coupling_result.thermal_result.dt_seconds == 23


@pytest.mark.parametrize(
    ("max_discharge_w", "payload_served_w", "expected_status"),
    (
        (1000.0, 105.0, AcquisitionServiceStatus.FULLY_SERVED),
        (60.0, 35.0, AcquisitionServiceStatus.FULL_SERVICE_IMPOSSIBLE),
        (105.0, 80.0, AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED),
    ),
)
def test_all_three_e1_statuses_are_accepted_and_preserved(
    max_discharge_w,
    payload_served_w,
    expected_status,
) -> None:
    electrical = _electrical_result(max_discharge_w=max_discharge_w)
    ledger = _served_ledger(
        electrical,
        served_by_component={
            ElectricalLoadComponent.PAYLOAD: payload_served_w
        },
    )
    assert electrical.service_bounds is not None
    assert electrical.service_bounds.status is expected_status

    result = _evaluate_e2(
        electrical_result=electrical,
        served_power_ledger=ledger,
    )

    assert result.electrical_result is electrical
    assert result.electrical_result.service_bounds.status is expected_status
    assert type(result.eps_thermal_coupling_result) is EPSThermalCouplingResult


def test_background_payload_keeps_acquisition_service_ambiguous() -> None:
    electrical = _electrical_result(max_discharge_w=105.0)
    assert electrical.eps_inputs is not None
    assert electrical.service_bounds is not None
    acquisition = electrical.acquisition_evaluation.acquisition_result
    assert acquisition is not None
    ledger = _served_ledger(
        electrical,
        served_by_component={
            ElectricalLoadComponent.BASE_BUS: 5.0,
            ElectricalLoadComponent.PAYLOAD: 85.0,
        },
    )

    result = _evaluate_e2(
        electrical_result=electrical,
        served_power_ledger=ledger,
    )
    payload = _component_ledgers(
        result.routed_internal_heat_result
    )[ElectricalLoadComponent.PAYLOAD]

    assert acquisition.requested_acquisition_power_w == 90.0
    assert electrical.eps_inputs.load_breakdown.payload_w == 15.0 + 90.0
    assert payload.served_power_w == 85.0
    assert electrical.service_bounds.minimum_served_acquisition_power_w == 65.0
    assert electrical.service_bounds.maximum_served_acquisition_power_w == 90.0
    result_fields = {field.name for field in fields(type(result))}
    assert result_fields.isdisjoint(
        {
            "exact_served_acquisition_power",
            "acquisition_served_fraction",
            "acquisition_specific_heat_w",
        }
    )


def test_nested_e1_and_b2_data_are_preserved_without_scaling() -> None:
    electrical = _electrical_result(max_discharge_w=60.0)
    acquisition = electrical.acquisition_evaluation.acquisition_result
    assert acquisition is not None
    before = deepcopy(electrical)
    ledger = _served_ledger(
        electrical,
        served_by_component={ElectricalLoadComponent.PAYLOAD: 35.0},
    )

    result = _evaluate_e2(
        electrical_result=electrical,
        served_power_ledger=ledger,
    )

    assert result.electrical_result is electrical
    assert result.electrical_result == before
    assert result.electrical_result.acquisition_evaluation.acquisition_result is (
        acquisition
    )
    assert acquisition.total_equivalent_samples == 1000.0
    assert acquisition.uncompressed_equivalent_bits == 12000.0
    assert acquisition.uncompressed_equivalent_bytes == 1500.0


@pytest.mark.parametrize("failure_kind", ("missing", "duplicate"))
def test_incomplete_or_duplicate_served_ledger_failure_propagates(
    failure_kind,
) -> None:
    arguments = _arguments()
    ledger = deepcopy(arguments["served_power_ledger"])
    assert type(ledger) is ServedPowerLedger
    if failure_kind == "missing":
        components = ledger.components[:-1]
        message = "exactly one entry"
    else:
        components = (*ledger.components[:-1], ledger.components[0])
        message = "duplicate"
    object.__setattr__(ledger, "components", components)
    arguments["served_power_ledger"] = ledger

    with pytest.raises(ValueError, match=message):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )


def test_served_greater_than_requested_failure_propagates() -> None:
    arguments = _arguments()
    ledger = deepcopy(arguments["served_power_ledger"])
    assert type(ledger) is ServedPowerLedger
    payload = next(
        item
        for item in ledger.components
        if item.component is ElectricalLoadComponent.PAYLOAD
    )
    object.__setattr__(
        payload,
        "served_power_w",
        payload.requested_power_w + 1.0,
    )
    arguments["served_power_ledger"] = ledger

    with pytest.raises(ValueError, match="less than or equal"):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )


def test_ledger_requested_component_mismatch_propagates_from_routing() -> None:
    electrical = _electrical_result()
    ledger = _served_ledger(electrical)
    payload = next(
        item
        for item in ledger.components
        if item.component is ElectricalLoadComponent.PAYLOAD
    )
    changed_payload = replace(
        payload,
        requested_power_w=payload.requested_power_w + 1.0,
    )
    mismatched = ServedPowerLedger(
        tuple(
            changed_payload
            if item.component is ElectricalLoadComponent.PAYLOAD
            else item
            for item in ledger.components
        )
    )

    with pytest.raises(ValueError, match="requested power for payload.*loads"):
        _evaluate_e2(
            electrical_result=electrical,
            served_power_ledger=mismatched,
        )


def test_ledger_aggregate_served_sum_mismatch_propagates_from_routing() -> None:
    electrical = _electrical_result()
    ledger = _served_ledger(
        electrical,
        served_by_component={ElectricalLoadComponent.PAYLOAD: 104.0},
    )

    with pytest.raises(ValueError, match="total served.*EPS served"):
        _evaluate_e2(
            electrical_result=electrical,
            served_power_ledger=ledger,
        )


def test_missing_route_failure_propagates() -> None:
    arguments = _arguments()
    routing = deepcopy(arguments["routing_config"])
    assert type(routing) is ComponentHeatRoutingConfig
    object.__setattr__(routing, "routes", routing.routes[:-1])
    arguments["routing_config"] = routing

    with pytest.raises(ValueError, match="exactly one entry"):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )


def test_invalid_route_fraction_value_failure_propagates() -> None:
    arguments = _arguments()
    routing = deepcopy(arguments["routing_config"])
    assert type(routing) is ComponentHeatRoutingConfig
    object.__setattr__(routing.routes[0].retained_heat_fraction, "value", 1.1)
    arguments["routing_config"] = routing

    with pytest.raises(ValueError, match="less than or equal to one"):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )


def test_invalid_route_provenance_failure_propagates() -> None:
    arguments = _arguments()
    routing = deepcopy(arguments["routing_config"])
    assert type(routing) is ComponentHeatRoutingConfig
    object.__setattr__(
        routing.routes[0].retained_heat_fraction.provenance,
        "status",
        ProvenanceStatus.REJECTED,
    )
    arguments["routing_config"] = routing

    with pytest.raises(ValueError, match="REJECTED"):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )


@pytest.mark.parametrize("corruption", ("value", "provenance"))
def test_nested_thermal_configuration_failure_precedes_routing(
    corruption,
    monkeypatch,
) -> None:
    arguments = _arguments()
    network = deepcopy(arguments["thermal_config"])
    assert type(network) is ThermalNetworkConfig
    parameter = network.nodes[0].heat_capacity_j_per_k
    if corruption == "value":
        object.__setattr__(parameter, "value", -1.0)
        message = "heat_capacity_j_per_k"
    else:
        object.__setattr__(
            parameter.provenance,
            "status",
            ProvenanceStatus.REJECTED,
        )
        message = "REJECTED"
    arguments["thermal_config"] = network
    monkeypatch.setattr(
        imaging_thermal_module,
        "compute_routed_internal_heat",
        lambda *args, **kwargs: pytest.fail("routing must not be reached"),
    )

    with pytest.raises(ValueError, match=message):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )


@pytest.mark.parametrize(
    ("field_name", "nested_field", "invalid", "message"),
    (
        (
            "thermal_inputs",
            "radiative_sink_temperature_k",
            float("nan"),
            "radiative_sink_temperature_k",
        ),
        (
            "external_heat_sources",
            "absorbed_solar_w",
            -1.0,
            "absorbed_solar_w",
        ),
    ),
)
def test_nested_interval_inputs_are_revalidated_before_routing(
    field_name,
    nested_field,
    invalid,
    message,
    monkeypatch,
) -> None:
    arguments = _arguments()
    value = deepcopy(arguments[field_name])
    nested_values = (
        value.node_boundaries
        if field_name == "thermal_inputs"
        else value.node_sources
    )
    object.__setattr__(nested_values[0], nested_field, invalid)
    arguments[field_name] = value
    monkeypatch.setattr(
        imaging_thermal_module,
        "compute_routed_internal_heat",
        lambda *args, **kwargs: pytest.fail("routing must not be reached"),
    )

    with pytest.raises(ValueError, match=message):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )


def test_route_destination_absent_from_network_failure_propagates() -> None:
    routing = _routing(
        node_names={ElectricalLoadComponent.PAYLOAD: "absent"}
    )

    with pytest.raises(ValueError, match="route thermal node ID.*exist"):
        _evaluate_e2(routing_config=routing)


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "message"),
    (
        (
            "thermal_state",
            _thermal_state(("bus", "battery", "other")),
            "runtime thermal node IDs",
        ),
        (
            "thermal_inputs",
            _thermal_inputs(("bus", "battery", "other")),
            "boundary node IDs",
        ),
        (
            "external_heat_sources",
            _external_sources(("bus", "battery", "other")),
            "routed-heat node IDs",
        ),
    ),
)
def test_thermal_node_set_failures_propagate(
    field_name,
    invalid_value,
    message,
) -> None:
    with pytest.raises(ValueError, match=message):
        _evaluate_e2(**{field_name: invalid_value})


def test_thermal_config_node_set_mismatch_propagates() -> None:
    alternate_network = ThermalNetworkConfig(
        (_node("bus"), _node("battery"), _node("other")),
        (),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("other"),
    )
    routing = _routing(
        node_names={ElectricalLoadComponent.PAYLOAD: "other"}
    )

    with pytest.raises(ValueError, match="routed-heat node IDs"):
        _evaluate_e2(
            thermal_config=alternate_network,
            routing_config=routing,
        )


def test_positive_endpoint_beyond_survival_range_remains_a_proposal() -> None:
    network = _network(payload_heat_capacity=1.0)

    result = _evaluate_e2(thermal_config=network)
    payload = _node_transitions(
        result.eps_thermal_coupling_result
    )["payload"]

    assert payload.end_temperature_k > 340.0
    assert payload.end_temperature_k > (
        next(
            node
            for node in network.nodes
            if node.node_id == ThermalNodeId("payload")
        ).survival_max_temperature_k.value
    )
    assert not hasattr(result, "feasible")
    assert not hasattr(result, "thermal_status")


def test_nonpositive_thermal_endpoint_failure_propagates() -> None:
    network = _network(
        payload_heat_capacity=1.0,
        payload_emissivity=1.0,
    )

    with pytest.raises(ValueError, match="end temperature.*greater than zero"):
        _evaluate_e2(
            thermal_config=network,
            thermal_inputs=_thermal_inputs(
                payload_sink_temperature_k=1.0
            ),
        )


def test_e2_evaluation_is_pure_and_mutates_no_input() -> None:
    arguments = _arguments(
        external_heat_sources=_external_sources(
            internal_by_node={"payload": 999.0},
            solar_by_node={"bus": 1.0, "payload": 2.0},
            albedo_by_node={"payload": 3.0},
            earth_ir_by_node={"battery": 4.0},
        )
    )
    before = deepcopy(arguments)

    result = (
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )
    )

    assert arguments == before
    assert result.electrical_result is arguments["electrical_result"]
    assert (
        arguments["external_heat_sources"].node_sources[2]
        .internal_dissipation_w
        == 999.0
    )


def test_failed_e2_evaluation_mutates_no_input() -> None:
    electrical = _electrical_result()
    mismatched_ledger = _served_ledger(
        electrical,
        served_by_component={ElectricalLoadComponent.PAYLOAD: 104.0},
    )
    arguments = _arguments(
        electrical_result=electrical,
        served_power_ledger=mismatched_ledger,
    )
    before = deepcopy(arguments)

    with pytest.raises(ValueError, match="total served"):
        evaluate_observation_acquisition_single_interval_thermal_proposal(
            **arguments
        )

    assert arguments == before


def test_production_delegates_without_allocation_or_thermal_equations() -> None:
    source = E2_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(E2_PATH))
    public_function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name
        == "evaluate_observation_acquisition_single_interval_thermal_proposal"
    )
    called_names = [
        node.func.id
        for node in ast.walk(public_function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert called_names.count("compute_routed_internal_heat") == 1
    assert called_names.count("compose_routed_internal_heat_sources") == 1
    assert called_names.count("compute_eps_thermal_interval_transition") == 1
    assert "validate_served_power_matches_loads" not in called_names
    assert not any(isinstance(node, ast.BinOp) for node in ast.walk(tree))
    assert identifiers.isdisjoint(
        {
            "minimum_served_acquisition_power_w",
            "maximum_served_acquisition_power_w",
            "served_load_w",
            "unmet_load_w",
            "conversion_loss_wh",
        }
    )
    assert not any(
        isinstance(node, ast.Constant) and node.value == 3600
        for node in ast.walk(tree)
    )


def test_production_has_no_allocation_partial_image_or_feasibility_law() -> None:
    source = E2_PATH.read_text(encoding="utf-8").lower()

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
        "served_fraction",
        "exact_served_acquisition_power",
        "acquisition_served_fraction",
        "acquisition_specific_heat_w",
        "partial_image",
        "generated_bytes",
        "stored_bytes",
        "compression",
        "packet",
        "downlink",
        "thermally_feasible",
        "thermally_infeasible",
        "thermal_dt_seconds",
        "substep",
    ):
        assert prohibited not in source


def test_production_has_only_allowed_pure_dependencies() -> None:
    source = E2_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(E2_PATH))
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
        "imaging_resources",
        "state",
        "thermal",
        "thermal_config",
        "thermal_coupling",
        "thermal_routing",
    }
    assert imported_modules.isdisjoint(
        {
            "numpy",
            "engine",
            "context",
            "checkpoint",
            "mission",
            "world",
            "storage",
            "communications",
            "orbit",
            "propulsion",
        }
    )


def test_imaging_thermal_module_has_exact_exports() -> None:
    assert imaging_thermal_module.__all__ == [
        "ObservationAcquisitionSingleIntervalThermalProposal",
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
    ]


def test_prior_non_engine_production_modules_are_unchanged() -> None:
    for relative_path in (
        "ops_sim/v5/imaging_resources.py",
        "ops_sim/v5/imaging_feasibility.py",
        "ops_sim/v5/observation_feasibility.py",
        "ops_sim/v5/payload.py",
        "ops_sim/v5/payload_config.py",
        "ops_sim/v5/adcs.py",
        "ops_sim/v5/adcs_config.py",
        "ops_sim/v5/thermal_routing.py",
        "ops_sim/v5/thermal_coupling.py",
        "ops_sim/v5/thermal.py",
        "ops_sim/v5/thermal_config.py",
        "ops_sim/v5/power_loads.py",
        "ops_sim/v5/eps.py",
        "ops_sim/v5/eps_system.py",
        "ops_sim/v5/eps_capability.py",
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
                f"6551767b8c3474e8550ab4bb5d588ebbb2a8fe96:{relative_path}",
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
                f"e948327562dbb620eda072d71c98bff9d5b6f146:{relative_path}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert after_slice == before_slice


def test_d228_through_d237_and_e2_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s004 = sources.partition("### S004 ")[2].partition("### S005 ")[0]
    lower = s004.lower()
    normalized = " ".join(lower.split())

    for number in range(228, 238):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D227 ") < decisions.index("## D228 ")
    assert "v5.3e2" in lower
    assert "no new physical source or value" in normalized
    assert "explicit" in lower and "served-power" in lower
    assert "complete" in lower and "allocation" in lower
    assert "payload" in lower and "acquisition" in lower
    assert "replaces" in lower and "internal" in lower
    assert "solar" in lower and "albedo" in lower and "earth-ir" in lower
    assert "battery conversion" in lower and "exactly once" in normalized
    assert (
        "no independent thermal timestep" in normalized
        or "no independent timestep" in normalized
    )
    assert "explicit-euler" in lower and "convergence" in lower
    assert "operating" in lower and "survival" in lower
    assert "feasibility" in lower and "state" in lower
