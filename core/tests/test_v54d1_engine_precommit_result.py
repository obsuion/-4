"""Precommit transaction-completion result construction for V5.4D1."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import replace
from inspect import Parameter, signature
from pathlib import Path
import subprocess
from typing import TypeVar

import pytest

from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.checkpoint import CURRENT_CHECKPOINT_SCHEMA_VERSION
import ops_sim.v5.engine as engine_module
from ops_sim.v5.engine import (
    STEP_PHASE_ORDER,
    ImagingEngineStepAttempt,
    SimulationEngine,
    StepResult,
)
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
    ThermalNodeId,
)
from ops_sim.v5.imaging_authorization import ImagingExecutionAuthorizationResult
from ops_sim.v5.imaging_execution import (
    ImagingExecutionAuthorizationStatus,
    ScheduledObservationAcquisitionExecution,
)
from ops_sim.v5.imaging_feasibility import ObservationAcquisitionCandidate
from ops_sim.v5.imaging_resources import AcquisitionEPSIntervalEnvironment
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
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.thermal import ThermalIntervalInputs, ThermalNodeBoundaryInput
from ops_sim.v5.thermal_coupling import (
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
)
from ops_sim.v5.thermal_routing import (
    ComponentHeatRoute,
    ComponentHeatRoutingConfig,
    ElectricalLoadComponent,
)


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"
C_COMMIT = "c294a794f811532deb9d5666d0ca01999c90951f"
D1_COMMIT = "ed7fd889f53339bf0fb220df76b69c53c36a448e"
COMPONENTS = tuple(ElectricalLoadComponent)


def _committed_text(commit: str, relative_path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def _parameter(parameter_id: str, units: str, value: object) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by the V5.4D1 tests.",
        ),
    )


def _context(*, max_discharge_w: float = 150.0):
    context = build_demo_context()
    spacecraft_config = context.inputs.spacecraft_configuration
    battery = replace(
        spacecraft_config.eps.battery,
        max_discharge_output_power_w=replace(
            spacecraft_config.eps.battery.max_discharge_output_power_w,
            value=max_discharge_w,
        ),
    )
    inputs = replace(
        context.inputs,
        spacecraft_configuration=replace(
            spacecraft_config,
            eps=replace(spacecraft_config.eps, battery=battery),
        ),
        numerical_config=replace(
            context.inputs.numerical_config,
            timestep_seconds=23,
            geometry_sample_seconds=1,
            checkpoint_interval_seconds=23,
        ),
    )
    return replace(context, simulation_time_seconds=100, inputs=inputs)


def _direction() -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId("v54d1-common-frame"),
        0.0,
        0.0,
        1.0,
    )


def _previous_execution() -> ScheduledObservationExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("v54d1-previous"),
        ImagingRequestId("v54d1-previous-request"),
        0,
        60,
        20,
        ObservationPointing(10.0, 0.0),
    )
    return ScheduledObservationExecution(
        ObservationManeuverCandidate(opportunity, _direction()),
        0,
    )


def _execution(
    *, view_angle_deg: float = 10.0,
) -> ScheduledObservationAcquisitionExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("v54d1-next"),
        ImagingRequestId("v54d1-next-request"),
        100,
        300,
        23,
        ObservationPointing(view_angle_deg, 0.0),
    )
    return ScheduledObservationAcquisitionExecution(
        ObservationAcquisitionCandidate(
            ObservationManeuverCandidate(opportunity, _direction()),
            OpticalAcquisitionInput(
                20.0,
                40.0,
                23,
                OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
            ),
        ),
        100,
    )


def _loads() -> PowerLoadBreakdown:
    return PowerLoadBreakdown(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)


def _environment() -> AcquisitionEPSIntervalEnvironment:
    return AcquisitionEPSIntervalEnvironment(False, 0.0, _loads())


def _routing() -> ComponentHeatRoutingConfig:
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
            for component in COMPONENTS
        )
    )


def _thermal_inputs(context) -> ThermalIntervalInputs:
    temperatures = {
        state.node_id: state.temperature_k
        for state in context.spacecraft_state.thermal.node_states
    }
    return ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(node.node_id, temperatures[node.node_id])
            for node in (
                context.inputs.spacecraft_configuration.thermal.network.nodes
            )
        )
    )


def _external_heat_sources(context) -> ThermalHeatSourceInputs:
    return ThermalHeatSourceInputs(
        tuple(
            ThermalNodeHeatSourceInput(node.node_id, 0.0, 0.0, 0.0, 0.0)
            for node in (
                context.inputs.spacecraft_configuration.thermal.network.nodes
            )
        )
    )


def _imaging_arguments(*, context=None, view_angle_deg: float = 10.0):
    active_context = _context() if context is None else context
    return {
        "context": active_context,
        "previous_execution": _previous_execution(),
        "execution": _execution(view_angle_deg=view_angle_deg),
        "environment": _environment(),
        "routing_config": _routing(),
        "thermal_inputs": _thermal_inputs(active_context),
        "external_heat_sources": _external_heat_sources(active_context),
    }


def _authoritative_references(context) -> tuple[object, ...]:
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
        spacecraft.data_storage.stored_records,
        context.ground_knowledge_state,
        context.ground_knowledge_state.latest_telemetry,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def _assert_rollback(context, before, references) -> None:
    assert context == before
    assert all(
        actual is original
        for actual, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def _method(tree: ast.Module, name: str) -> ast.FunctionDef:
    engine_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SimulationEngine"
    )
    return next(
        node
        for node in engine_class.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def test_private_kernel_signature_typing_default_and_exports_are_exact() -> None:
    parameters = signature(SimulationEngine._run_transaction).parameters

    assert tuple(parameters) == (
        "self",
        "context",
        "physical_integration_handler_factory",
        "precommit_result_factory",
    )
    assert parameters["context"].kind is Parameter.POSITIONAL_OR_KEYWORD
    physical_factory = parameters["physical_integration_handler_factory"]
    assert physical_factory.kind is Parameter.KEYWORD_ONLY
    assert physical_factory.default is Parameter.empty
    assert physical_factory.annotation == "_PhysicalIntegrationHandlerFactory"
    result_factory = parameters["precommit_result_factory"]
    assert result_factory.kind is Parameter.KEYWORD_ONLY
    assert result_factory.default is None
    assert result_factory.annotation == (
        "Callable[[StepResult], _TransactionResultT] | None"
    )
    assert signature(SimulationEngine._run_transaction).return_annotation == (
        "StepResult | _TransactionResultT"
    )
    assert type(engine_module._TransactionResultT) is type(TypeVar("ProbeT"))
    assert engine_module._TransactionResultT.__name__ == "_TransactionResultT"
    d1_exports = [
        "STEP_PHASE_ORDER",
        "ImagingEngineStepAttempt",
        "SimulationEngine",
        "SimulationPhase",
        "StepResult",
    ]
    assert all(name in engine_module.__all__ for name in d1_exports)
    assert "_TransactionResultT" not in engine_module.__all__

    historical_tree = ast.parse(
        _committed_text(D1_COMMIT, "ops_sim/v5/engine.py")
    )
    historical_exports = next(
        node
        for node in historical_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    )
    assert ast.literal_eval(historical_exports.value) == d1_exports


def test_public_engine_signatures_remain_exact() -> None:
    generic = signature(SimulationEngine.step).parameters
    assert tuple(generic) == (
        "self",
        "context",
        "eps_inputs",
        "thermal_inputs",
        "heat_source_inputs",
        "solar_degradation_forcing",
    )
    assert generic["context"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert all(
        parameter.kind is Parameter.KEYWORD_ONLY and parameter.default is None
        for name, parameter in generic.items()
        if name not in {"self", "context"}
    )

    imaging = signature(SimulationEngine.step_imaging).parameters
    assert tuple(imaging) == (
        "self",
        "context",
        "previous_execution",
        "execution",
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
        "solar_degradation_forcing",
    )
    for name in ("context", "previous_execution", "execution"):
        assert imaging[name].kind is Parameter.POSITIONAL_OR_KEYWORD
        assert imaging[name].default is Parameter.empty
    for name in (
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
    ):
        assert imaging[name].kind is Parameter.KEYWORD_ONLY
        assert imaging[name].default is Parameter.empty
    assert imaging["solar_degradation_forcing"].kind is Parameter.KEYWORD_ONLY
    assert imaging["solar_degradation_forcing"].default is None


def test_generic_default_path_constructs_then_commits_exact_step_result(
    monkeypatch,
) -> None:
    context = _context()
    battery_before = context.spacecraft_state.battery.energy_wh
    events: list[str] = []
    constructed: list[StepResult] = []
    original_result = engine_module.StepResult
    original_commit = SimulationEngine._commit

    def construct_result(*args, **kwargs):
        result = original_result(*args, **kwargs)
        constructed.append(result)
        events.append("step-result")
        return result

    def commit(original, working):
        assert constructed
        assert original.simulation_time_seconds == 100
        events.append("commit")
        return original_commit(original, working)

    monkeypatch.setattr(engine_module, "StepResult", construct_result)
    monkeypatch.setattr(SimulationEngine, "_commit", staticmethod(commit))

    result = SimulationEngine().step(context)

    assert result is constructed[0]
    assert type(result) is original_result
    assert events == ["step-result", "commit"]
    assert result.executed_phases == STEP_PHASE_ORDER
    assert result.start_time_seconds == 100
    assert result.end_time_seconds == 123
    assert result.dt_seconds == 23
    assert all(
        getattr(result, name) is None
        for name in (
            "eps_result",
            "thermal_coupling_result",
            "battery_degradation_result",
            "solar_degradation_result",
            "eps_capability_result",
            "battery_capacity_reconciliation_result",
        )
    )
    assert context.spacecraft_state.battery.energy_wh == battery_before
    assert context.simulation_time_seconds == 123
    assert context.diagnostics.completed_steps == 1


def test_custom_factory_gets_exact_step_before_commit_and_exact_result_returns(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    events: list[str] = []
    received: list[StepResult] = []
    sentinel = object()
    original_result = engine_module.StepResult
    original_commit = SimulationEngine._commit

    def construct_result(*args, **kwargs):
        result = original_result(*args, **kwargs)
        events.append("step-result")
        return result

    def factory(result):
        assert type(result) is original_result
        assert context == before
        assert _authoritative_references(context) == references
        received.append(result)
        events.append("factory")
        return sentinel

    def commit(original, working):
        assert events == ["step-result", "factory"]
        events.append("commit")
        return original_commit(original, working)

    monkeypatch.setattr(engine_module, "StepResult", construct_result)
    monkeypatch.setattr(SimulationEngine, "_commit", staticmethod(commit))

    returned = SimulationEngine()._run_transaction(
        context,
        physical_integration_handler_factory=lambda: (
            lambda working, interval: None
        ),
        precommit_result_factory=factory,
    )

    assert returned is sentinel
    assert len(received) == 1
    assert events == ["step-result", "factory", "commit"]
    assert context.simulation_time_seconds == 123
    assert context.diagnostics.completed_steps == 1


def test_invalid_noncallable_factory_fails_before_handler_checkpoint_or_commit(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    def forbidden(*args, **kwargs):
        pytest.fail("transaction work must not begin")

    monkeypatch.setattr(engine_module.CheckpointState, "from_context", forbidden)
    monkeypatch.setattr(SimulationEngine, "_commit", staticmethod(forbidden))

    with pytest.raises(TypeError, match="precommit_result_factory.*callable"):
        SimulationEngine()._run_transaction(
            context,
            physical_integration_handler_factory=forbidden,
            precommit_result_factory=object(),
        )

    _assert_rollback(context, before, references)


def test_completed_context_validation_precedes_factory_preflight() -> None:
    context = _context()
    context.spacecraft_state.battery.energy_wh = -1.0

    with pytest.raises(ValueError, match="energy_wh"):
        SimulationEngine()._run_transaction(
            context,
            physical_integration_handler_factory=lambda: pytest.fail(
                "handler factory must not run"
            ),
            precommit_result_factory=object(),
        )


def test_custom_factory_exception_propagates_unchanged_with_complete_rollback(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    calls: list[StepResult] = []

    class ExpectedFactoryError(RuntimeError):
        pass

    expected = ExpectedFactoryError("synthetic precommit factory failure")

    def factory(result):
        calls.append(result)
        raise expected

    def forbidden_commit(*args, **kwargs):
        pytest.fail("commit must follow successful factory construction")

    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(forbidden_commit),
    )

    with pytest.raises(ExpectedFactoryError) as caught:
        SimulationEngine()._run_transaction(
            context,
            physical_integration_handler_factory=lambda: (
                lambda working, interval: None
            ),
            precommit_result_factory=factory,
        )

    assert caught.value is expected
    assert len(calls) == 1
    assert type(calls[0]) is StepResult
    _assert_rollback(context, before, references)


def test_authorized_imaging_constructs_exact_attempt_before_one_commit(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    events: list[str] = []
    attempts: list[ImagingEngineStepAttempt] = []
    authorizations: list[ImagingExecutionAuthorizationResult] = []
    step_results: list[StepResult] = []
    original_attempt = engine_module.ImagingEngineStepAttempt
    original_authorize = (
        engine_module.evaluate_imaging_engine_step_authorization
    )
    original_run = SimulationEngine._run_transaction
    original_commit = SimulationEngine._commit

    def authorize(*args, **kwargs):
        result = original_authorize(*args, **kwargs)
        authorizations.append(result)
        return result

    def observing_run(
        self,
        context,
        *,
        physical_integration_handler_factory,
        precommit_result_factory=None,
    ):
        def capture_result(result):
            step_results.append(result)
            return precommit_result_factory(result)

        return original_run(
            self,
            context,
            physical_integration_handler_factory=(
                physical_integration_handler_factory
            ),
            precommit_result_factory=capture_result,
        )

    def construct_attempt(authorization, step_result):
        assert context == before
        assert _authoritative_references(context) == references
        assert authorization is authorizations[0]
        assert step_result is step_results[0]
        attempt = original_attempt(authorization, step_result)
        attempts.append(attempt)
        events.append("attempt")
        return attempt

    def commit(original, working):
        assert len(attempts) == 1
        events.append("commit")
        return original_commit(original, working)

    monkeypatch.setattr(
        engine_module,
        "evaluate_imaging_engine_step_authorization",
        authorize,
    )
    monkeypatch.setattr(SimulationEngine, "_run_transaction", observing_run)
    monkeypatch.setattr(
        engine_module,
        "ImagingEngineStepAttempt",
        construct_attempt,
    )
    monkeypatch.setattr(SimulationEngine, "_commit", staticmethod(commit))

    returned = SimulationEngine().step_imaging(
        **_imaging_arguments(context=context)
    )

    assert returned is attempts[0]
    assert type(returned) is original_attempt
    assert returned.authorization_result is authorizations[0]
    assert returned.step_result is step_results[0]
    assert events == ["attempt", "commit"]
    authorization = returned.authorization_result
    result = returned.step_result
    assert authorization.status is ImagingExecutionAuthorizationStatus.AUTHORIZED
    assert result is not None
    assert result.eps_result is authorization.electrical_result.eps_result
    assert result.eps_capability_result is (
        authorization.electrical_result.eps_capability_result
    )
    assert result.thermal_coupling_result is (
        authorization.thermal_proposal.eps_thermal_coupling_result
    )
    assert context.spacecraft_state.battery.energy_wh == (
        result.battery_capacity_reconciliation_result.authoritative_end_energy_wh
    )
    assert {
        node.node_id: node.temperature_k
        for node in context.spacecraft_state.thermal.node_states
    } == {
        transition.node_id: transition.end_temperature_k
        for transition in (
            result.thermal_coupling_result.thermal_result.node_transitions
        )
    }
    assert context.simulation_time_seconds == 123
    assert context.diagnostics.completed_steps == 1


def test_authorized_outer_constructor_failure_prevents_commit_and_rolls_back(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    class ExpectedAttemptError(RuntimeError):
        pass

    expected = ExpectedAttemptError("synthetic outer-attempt failure")

    def fail_attempt(authorization, step_result):
        assert authorization.status is ImagingExecutionAuthorizationStatus.AUTHORIZED
        assert type(step_result) is StepResult
        raise expected

    monkeypatch.setattr(engine_module, "ImagingEngineStepAttempt", fail_attempt)
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )

    with pytest.raises(ExpectedAttemptError) as caught:
        SimulationEngine().step_imaging(
            **_imaging_arguments(context=context)
        )

    assert caught.value is expected
    _assert_rollback(context, before, references)


def test_missing_retained_authorization_is_detected_before_commit(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    def prepare_without_retention(self, *args, **kwargs):
        return lambda working, interval: None

    monkeypatch.setattr(
        SimulationEngine,
        "_prepare_imaging_physical_integration_handler",
        prepare_without_retention,
    )
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )

    with pytest.raises(RuntimeError, match="did not retain authorization"):
        SimulationEngine().step_imaging(
            **_imaging_arguments(context=context)
        )

    _assert_rollback(context, before, references)


def test_nonauthorization_skips_precommit_factory_and_commit(monkeypatch) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    factory_calls: list[StepResult] = []
    authorizations: list[ImagingExecutionAuthorizationResult] = []
    original_run = SimulationEngine._run_transaction
    original_authorize = (
        engine_module.evaluate_imaging_engine_step_authorization
    )

    def authorize(*args, **kwargs):
        result = original_authorize(*args, **kwargs)
        authorizations.append(result)
        return result

    def observing_run(
        self,
        context,
        *,
        physical_integration_handler_factory,
        precommit_result_factory=None,
    ):
        assert precommit_result_factory is not None

        def observe_factory(result):
            factory_calls.append(result)
            return precommit_result_factory(result)

        return original_run(
            self,
            context,
            physical_integration_handler_factory=(
                physical_integration_handler_factory
            ),
            precommit_result_factory=observe_factory,
        )

    monkeypatch.setattr(SimulationEngine, "_run_transaction", observing_run)
    monkeypatch.setattr(
        engine_module,
        "evaluate_imaging_engine_step_authorization",
        authorize,
    )
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )

    attempt = SimulationEngine().step_imaging(
        **_imaging_arguments(context=context, view_angle_deg=50.0)
    )

    assert type(attempt) is ImagingEngineStepAttempt
    assert attempt.authorization_result.status is (
        ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE
    )
    assert attempt.authorization_result is authorizations[0]
    assert attempt.step_result is None
    assert factory_calls == []
    _assert_rollback(context, before, references)


def test_kernel_ast_enforces_precommit_order_and_bare_postcommit_return() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    kernel = _method(tree, "_run_transaction")
    calls = [node for node in ast.walk(kernel) if isinstance(node, ast.Call)]
    step_result_calls = [call for call in calls if _call_name(call) == "StepResult"]
    factory_calls = [
        call
        for call in calls
        if _call_name(call) == "precommit_result_factory"
    ]
    commit_calls = [call for call in calls if _call_name(call) == "_commit"]
    assignments = {
        target.id: node
        for node in kernel.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert len(step_result_calls) == 1
    assert len(factory_calls) == 1
    assert len(commit_calls) == 1
    assert "proposed_result" in assignments
    assert "completion_result" in assignments
    assert isinstance(assignments["completion_result"].value, ast.IfExp)
    assert (
        step_result_calls[0].lineno
        < assignments["completion_result"].lineno
        <= factory_calls[0].lineno
        < commit_calls[0].lineno
    )
    commit_index = next(
        index
        for index, statement in enumerate(kernel.body)
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and _call_name(statement.value) == "_commit"
    )
    assert len(kernel.body[:commit_index]) > 0
    assert len(kernel.body[commit_index + 1 :]) == 1
    final_return = kernel.body[-1]
    assert isinstance(final_return, ast.Return)
    assert isinstance(final_return.value, ast.Name)
    assert final_return.value.id == "completion_result"


def test_step_methods_ast_preserve_result_ownership_and_factory_boundaries() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    generic = _method(tree, "step")
    imaging = _method(tree, "step_imaging")
    generic_calls = [node for node in ast.walk(generic) if isinstance(node, ast.Call)]
    imaging_calls = [node for node in ast.walk(imaging) if isinstance(node, ast.Call)]

    assert not any(_call_name(call) == "StepResult" for call in generic_calls)
    assert not any(_call_name(call) == "StepResult" for call in imaging_calls)
    generic_kernel_call = next(
        call for call in generic_calls if _call_name(call) == "_run_transaction"
    )
    assert [keyword.arg for keyword in generic_kernel_call.keywords] == [
        "physical_integration_handler_factory"
    ]

    build_attempt = next(
        node
        for node in imaging.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_attempt"
    )
    assert sum(
        _call_name(call) == "ImagingEngineStepAttempt"
        for call in ast.walk(build_attempt)
        if isinstance(call, ast.Call)
    ) == 1
    transaction_try = next(node for node in imaging.body if isinstance(node, ast.Try))
    assert len(transaction_try.body) == 1
    assert isinstance(transaction_try.body[0], ast.Return)
    assert isinstance(transaction_try.body[0].value, ast.Call)
    assert _call_name(transaction_try.body[0].value) == "_run_transaction"
    assert {
        keyword.arg for keyword in transaction_try.body[0].value.keywords
    } == {
        "physical_integration_handler_factory",
        "precommit_result_factory",
    }


def test_d1_adds_no_storage_engine_api_or_other_deferred_behavior() -> None:
    tree = ast.parse(_committed_text(D1_COMMIT, "ops_sim/v5/engine.py"))
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    identifiers = {
        value.lower()
        for node in ast.walk(tree)
        for value in (
            (node.id,)
            if isinstance(node, ast.Name)
            else (node.attr,)
            if isinstance(node, ast.Attribute)
            else (node.name,)
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
            else ()
        )
    }

    engine_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SimulationEngine"
    )
    assert "step_imaging_to_storage" not in {
        node.name
        for node in engine_class.body
        if isinstance(node, ast.FunctionDef)
    }
    assert "imaging_storage" not in imported_modules
    assert identifiers.isdisjoint(
        {
            "imagingstorageengineattempt",
            "authorize_imaging_storage_execution",
            "acquisitiondatarecordid",
            "storageadmissionresult",
            "evaluate_storage_admission",
        }
    )
    kernel = _method(tree, "_run_transaction")
    imaging = _method(tree, "step_imaging")
    scoped_identifiers = {
        node.attr.lower()
        for method in (kernel, imaging)
        for node in ast.walk(method)
        if isinstance(node, ast.Attribute)
    }
    assert scoped_identifiers.isdisjoint({"data_storage", "stored_records"})
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5


def test_d293_source_register_and_d1_historical_scope_are_exact() -> None:
    decisions = _committed_text(D1_COMMIT, "V5_DECISION_LOG.md")
    heading = (
        "## D293 — V5.4D1 constructs transaction completion evidence "
        "before authoritative commit"
    )
    assert decisions.count(heading) == 1
    assert decisions.index("## D292 ") < decisions.index(heading)
    assert "## D294 " not in decisions
    normalized = " ".join(decisions.partition(heading)[2].lower().split())
    for phrase in (
        "shared `_run_transaction`",
        "exactly one `stepresult`",
        "private precommit result factory",
        "authoritative commit occurs only after",
        "factory failure propagates with no commit",
        "after `_commit`, the kernel performs only a bare return",
        "generic `step` behavior is unchanged",
        "existing `step_imaging` signature",
        "no imaging-to-storage engine integration",
        "schema change",
        "new physical source, numerical value, or literature basis",
    ):
        assert phrase in normalized

    c_source_register = _committed_text(
        C_COMMIT,
        "V5_SOURCE_REGISTER.md",
    )
    d1_source_register = _committed_text(
        D1_COMMIT,
        "V5_SOURCE_REGISTER.md",
    )
    assert d1_source_register == c_source_register

    production_changes = set(
        subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                C_COMMIT,
                D1_COMMIT,
                "--",
                "ops_sim/v5",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    changes = set(
        subprocess.run(
            ["git", "diff", "--name-only", C_COMMIT, D1_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )

    assert production_changes == {"ops_sim/v5/engine.py"}
    assert changes == {
        "V5_DECISION_LOG.md",
        "ops_sim/v5/engine.py",
        "tests/test_v53f3a_engine_transaction_refactor.py",
        "tests/test_v54c_imaging_storage_authorization.py",
        "tests/test_v54d1_engine_precommit_result.py",
    }
