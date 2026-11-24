"""Behavior-preserving engine transaction-kernel refactor for V5.3F3A."""

import ast
from copy import deepcopy
from dataclasses import MISSING, fields
from inspect import Parameter, signature
from pathlib import Path
import subprocess

import pytest

from examples.v52_integrated_eps_thermal_demo import (
    build_demo_context,
    build_step_inputs,
)
import ops_sim.v5.engine as engine_module
from ops_sim.v5.degradation import SolarDegradationForcingInput
from ops_sim.v5.engine import (
    STEP_PHASE_ORDER,
    SimulationEngine,
    SimulationPhase,
    StepResult,
)


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
F3A_COMMIT = "d2c2b3afae8f1e6e9a1396037f47364e8016eafd"
F3B_COMMIT = "c74e52faedf9af804277d93c83f46ebc318df893"


def _coupled_arguments(*, solar_loss: float | None = None):
    eps_inputs, thermal_inputs, heat_source_inputs = build_step_inputs(0)
    arguments = {
        "eps_inputs": eps_inputs,
        "thermal_inputs": thermal_inputs,
        "heat_source_inputs": heat_source_inputs,
    }
    if solar_loss is not None:
        arguments["solar_degradation_forcing"] = (
            SolarDegradationForcingInput(solar_loss)
        )
    return arguments


def _physical_result_fields(result: StepResult) -> tuple[object, ...]:
    return (
        result.eps_result,
        result.thermal_coupling_result,
        result.battery_degradation_result,
        result.solar_degradation_result,
        result.eps_capability_result,
        result.battery_capacity_reconciliation_result,
    )


def _authoritative_references(context) -> tuple[object, ...]:
    spacecraft = context.spacecraft_state
    knowledge = context.ground_knowledge_state
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
        knowledge,
        knowledge.latest_telemetry,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def _assert_authoritative_rollback(context, before, references) -> None:
    assert context == before
    assert all(
        actual is original
        for actual, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def _parse_engine() -> ast.Module:
    return ast.parse(
        ENGINE_PATH.read_text(encoding="utf-8"),
        filename=str(ENGINE_PATH),
    )


def _engine_method(tree: ast.Module, name: str) -> ast.FunctionDef:
    engine = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SimulationEngine"
    )
    return next(
        node
        for node in engine.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _module_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
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


def test_public_step_signature_remains_exact() -> None:
    parameters = signature(SimulationEngine.step).parameters

    assert tuple(parameters) == (
        "self",
        "context",
        "eps_inputs",
        "thermal_inputs",
        "heat_source_inputs",
        "solar_degradation_forcing",
    )
    assert parameters["self"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["context"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert all(
        parameter.kind is Parameter.KEYWORD_ONLY
        and parameter.default is None
        for parameter in tuple(parameters.values())[2:]
    )


def test_step_result_contract_and_f3a_exports_remain_live() -> None:
    result = SimulationEngine().step(build_demo_context())
    result_fields = fields(StepResult)

    assert tuple(field.name for field in result_fields) == (
        "start_time_seconds",
        "end_time_seconds",
        "dt_seconds",
        "executed_phases",
        "eps_result",
        "thermal_coupling_result",
        "battery_degradation_result",
        "solar_degradation_result",
        "eps_capability_result",
        "battery_capacity_reconciliation_result",
    )
    assert StepResult.__dataclass_params__.frozen
    assert not hasattr(result, "__dict__")
    assert all(field.default is MISSING for field in result_fields[:4])
    assert all(field.default is None for field in result_fields[4:])
    expected_f3a_exports = [
        "STEP_PHASE_ORDER",
        "SimulationEngine",
        "SimulationPhase",
        "StepResult",
    ]
    historical_source = subprocess.run(
        ["git", "show", f"{F3A_COMMIT}:ops_sim/v5/engine.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    historical_tree = ast.parse(historical_source)
    historical_exports = next(
        node
        for node in historical_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    )

    assert ast.literal_eval(historical_exports.value) == expected_f3a_exports
    assert all(name in engine_module.__all__ for name in expected_f3a_exports)


def test_phase_vocabulary_and_order_remain_exact() -> None:
    assert tuple((phase.name, phase.value) for phase in SimulationPhase) == (
        ("WORLD_ENVIRONMENT", "world-environment"),
        ("KNOWLEDGE_UPDATE", "knowledge-update"),
        ("PLANNING", "planning"),
        ("ONBOARD_ARBITRATION", "onboard-arbitration"),
        ("ACTION_EXECUTION", "action-execution"),
        ("PHYSICAL_INTEGRATION", "physical-integration"),
        (
            "FAILURE_CAPABILITY_RESOLUTION",
            "failure-capability-resolution",
        ),
        ("DIAGNOSTICS", "diagnostics"),
        ("ADVANCE_CLOCK", "advance-clock"),
    )
    assert STEP_PHASE_ORDER == tuple(SimulationPhase)


def test_private_callable_seam_is_private_and_context_independent() -> None:
    for name in (
        "_PhysicalIntegrationResult",
        "_PhysicalIntegrationHandler",
        "_PhysicalIntegrationHandlerFactory",
        "_complete_coupled_physical_integration",
    ):
        assert hasattr(engine_module, name)
        assert name not in engine_module.__all__


def test_private_transaction_and_coupled_tail_signatures_are_exact() -> None:
    kernel = signature(SimulationEngine._run_transaction).parameters
    prepare = signature(
        SimulationEngine._prepare_generic_physical_integration_handler
    ).parameters
    tail = signature(
        engine_module._complete_coupled_physical_integration
    ).parameters

    assert tuple(kernel) == (
        "self",
        "context",
        "physical_integration_handler_factory",
        "precommit_result_factory",
    )
    assert all(
        kernel[name].kind is Parameter.KEYWORD_ONLY
        for name in (
            "physical_integration_handler_factory",
            "precommit_result_factory",
        )
    )
    assert kernel["precommit_result_factory"].default is None
    assert tuple(prepare) == (
        "self",
        "eps_inputs",
        "thermal_inputs",
        "heat_source_inputs",
        "solar_degradation_forcing",
    )
    assert tuple(tail) == (
        "context",
        "interval",
        "eps_result",
        "thermal_coupling_result",
        "eps_capability_result",
        "solar_degradation_forcing",
    )
    assert all(
        tail[name].kind is Parameter.KEYWORD_ONLY
        for name in tuple(tail)[2:]
    )


def test_public_step_is_one_thin_delayed_kernel_delegation() -> None:
    step = _engine_method(_parse_engine(), "step")
    calls = _called_names(step)

    assert calls.count("_run_transaction") == 1
    assert calls.count(
        "_prepare_generic_physical_integration_handler"
    ) == 1
    assert not any(isinstance(node, ast.For) for node in ast.walk(step))
    assert set(calls).isdisjoint(
        {"from_context", "restore", "StepResult", "_commit"}
    )


def test_transaction_kernel_has_single_structural_owners() -> None:
    tree = _parse_engine()
    kernel = _engine_method(tree, "_run_transaction")
    calls = _called_names(kernel)
    phase_loops = [
        node
        for node in ast.walk(kernel)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "STEP_PHASE_ORDER"
    ]
    all_calls = _called_names(tree)

    assert calls.count("_validate_completed_context") == 2
    assert calls.count("from_context") == 1
    assert calls.count("restore") == 1
    assert calls.count("StepResult") == 1
    assert calls.count("_commit") == 1
    assert len(phase_loops) == 1
    assert all_calls.count("from_context") == 1
    assert all_calls.count("StepResult") == 1
    assert all_calls.count("_commit") == 1


def test_coupled_tail_and_generic_physics_have_single_owners() -> None:
    tree = _parse_engine()
    generic = _engine_method(tree, "_physical_integration")
    # Task 04A: legacy and dyadic completion wrappers share this one owner.
    for wrapper in ("_complete_coupled_physical_integration", "complete_coupled_physical_substep"):
        assert _called_names(_module_function(tree, wrapper)).count("_complete_coupled_physical_core") == 1
    tail = _module_function(tree, "_complete_coupled_physical_core")
    generic_calls = _called_names(generic)
    tail_calls = _called_names(tail)

    assert generic_calls.count("compute_eps_capability") == 1
    assert generic_calls.count("compute_eps_interval_transition") == 1
    assert generic_calls.count(
        "compute_eps_thermal_interval_transition"
    ) == 1
    assert generic_calls.count(
        "_complete_coupled_physical_integration"
    ) == 1
    for name in (
        "compute_battery_throughput_increment",
        "compute_battery_degradation_transition",
        "compute_explicit_solar_degradation_transition",
        "compute_battery_capacity_reconciliation",
    ):
        assert generic_calls.count(name) == 0
        assert tail_calls.count(name) == 1
    assert "compute_eps_interval_transition" not in tail_calls
    assert "compute_eps_thermal_interval_transition" not in tail_calls


def test_invalid_context_precedes_invalid_transient_input(monkeypatch) -> None:
    context = build_demo_context()
    context.spacecraft_state.battery.energy_wh = -1.0
    prepare_calls = []
    original_prepare = (
        SimulationEngine._prepare_generic_physical_integration_handler
    )

    def prepare(self, *args):
        prepare_calls.append(args)
        return original_prepare(self, *args)

    monkeypatch.setattr(
        SimulationEngine,
        "_prepare_generic_physical_integration_handler",
        prepare,
    )

    with pytest.raises(ValueError, match="energy_wh"):
        SimulationEngine().step(context, eps_inputs=object())
    assert prepare_calls == []


def test_transient_input_validation_precedes_horizon_validation() -> None:
    context = build_demo_context()
    context.simulation_time_seconds = 86_390

    with pytest.raises(TypeError, match="eps_inputs"):
        SimulationEngine().step(context, eps_inputs=object())


def test_handler_factory_precedes_one_checkpoint_capture_and_restore(
    monkeypatch,
) -> None:
    events = []
    original_prepare = (
        SimulationEngine._prepare_generic_physical_integration_handler
    )
    original_from_context = engine_module.CheckpointState.from_context
    original_restore = engine_module.CheckpointState.restore

    def prepare(self, *args):
        events.append("factory")
        return original_prepare(self, *args)

    def from_context(cls, context):
        events.append("capture")
        return original_from_context(context)

    def restore(self, inputs):
        events.append("restore")
        return original_restore(self, inputs)

    monkeypatch.setattr(
        SimulationEngine,
        "_prepare_generic_physical_integration_handler",
        prepare,
    )
    monkeypatch.setattr(
        engine_module.CheckpointState,
        "from_context",
        classmethod(from_context),
    )
    monkeypatch.setattr(
        engine_module.CheckpointState,
        "restore",
        restore,
    )

    SimulationEngine().step(build_demo_context())

    assert events == ["factory", "capture", "restore"]


def test_handler_runs_once_only_in_physical_phase_on_working_context() -> None:
    authoritative = build_demo_context()

    class ObservingEngine(SimulationEngine):
        def __init__(self):
            self.phase_calls = []
            self.physical_calls = []
            self.active_phase = None

        def _execute_phase(self, phase, context, interval, handler):
            self.active_phase = phase
            self.phase_calls.append((phase, context, interval, handler))
            return super()._execute_phase(
                phase,
                context,
                interval,
                handler,
            )

        def _physical_integration(self, context, interval, physical_inputs):
            self.physical_calls.append(
                (
                    self.active_phase,
                    context,
                    interval,
                    physical_inputs,
                )
            )
            return super()._physical_integration(
                context,
                interval,
                physical_inputs,
            )

    engine = ObservingEngine()
    result = engine.step(authoritative)

    assert tuple(call[0] for call in engine.phase_calls) == STEP_PHASE_ORDER
    assert len(engine.physical_calls) == 1
    phase, working, interval, physical_inputs = engine.physical_calls[0]
    assert phase is SimulationPhase.PHYSICAL_INTEGRATION
    assert working is not authoritative
    assert working.inputs is authoritative.inputs
    assert physical_inputs is None
    assert all(call[1] is working for call in engine.phase_calls)
    assert all(call[2] is interval for call in engine.phase_calls)
    assert all(callable(call[3]) for call in engine.phase_calls)
    assert interval.start_time_seconds == result.start_time_seconds
    assert interval.end_time_seconds == result.end_time_seconds


def test_step_kernel_factory_handler_tail_result_and_commit_are_each_once(
    monkeypatch,
) -> None:
    events = []
    original_run = SimulationEngine._run_transaction
    original_prepare = (
        SimulationEngine._prepare_generic_physical_integration_handler
    )
    original_tail = engine_module._complete_coupled_physical_integration
    original_result_type = engine_module.StepResult
    original_commit = SimulationEngine._commit

    def run(self, context, *, physical_integration_handler_factory):
        events.append("kernel")
        return original_run(
            self,
            context,
            physical_integration_handler_factory=(
                physical_integration_handler_factory
            ),
        )

    def prepare(self, *args):
        events.append("factory")
        handler = original_prepare(self, *args)

        def observed_handler(context, interval):
            events.append("handler")
            return handler(context, interval)

        return observed_handler

    def tail(*args, **kwargs):
        events.append("tail")
        return original_tail(*args, **kwargs)

    def result_constructor(*args, **kwargs):
        events.append("result")
        return original_result_type(*args, **kwargs)

    def commit(original, working):
        events.append("commit")
        return original_commit(original, working)

    monkeypatch.setattr(SimulationEngine, "_run_transaction", run)
    monkeypatch.setattr(
        SimulationEngine,
        "_prepare_generic_physical_integration_handler",
        prepare,
    )
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        tail,
    )
    monkeypatch.setattr(engine_module, "StepResult", result_constructor)
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(commit),
    )

    result = SimulationEngine().step(
        build_demo_context(),
        **_coupled_arguments(),
    )

    assert type(result) is original_result_type
    assert {name: events.count(name) for name in set(events)} == {
        "kernel": 1,
        "factory": 1,
        "handler": 1,
        "tail": 1,
        "result": 1,
        "commit": 1,
    }
    assert events.index("kernel") < events.index("factory")
    assert events.index("factory") < events.index("handler")
    assert events.index("handler") < events.index("tail")
    assert events[-2:] == ["result", "commit"]


@pytest.mark.parametrize(
    ("mode", "expected_tail_calls"),
    (("none", 0), ("eps", 0), ("coupled", 1), ("solar", 1)),
)
def test_coupled_tail_call_count_by_generic_mode(
    mode,
    expected_tail_calls,
    monkeypatch,
) -> None:
    calls = []
    original_tail = engine_module._complete_coupled_physical_integration

    def tail(*args, **kwargs):
        calls.append((args, kwargs))
        return original_tail(*args, **kwargs)

    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        tail,
    )
    inputs = build_step_inputs(0)
    if mode == "none":
        arguments = {}
    elif mode == "eps":
        arguments = {"eps_inputs": inputs[0]}
    elif mode == "coupled":
        arguments = _coupled_arguments()
    else:
        arguments = _coupled_arguments(solar_loss=0.01)

    SimulationEngine().step(build_demo_context(), **arguments)

    assert len(calls) == expected_tail_calls


def test_coupled_physics_and_tail_helpers_each_run_once(monkeypatch) -> None:
    helper_names = (
        "compute_eps_capability",
        "compute_eps_interval_transition",
        "compute_eps_thermal_interval_transition",
        "compute_battery_throughput_increment",
        "compute_battery_degradation_transition",
        "compute_explicit_solar_degradation_transition",
        "compute_battery_capacity_reconciliation",
    )
    calls = []
    for name in helper_names:
        original = getattr(engine_module, name)

        def wrapper(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(engine_module, name, wrapper)

    SimulationEngine().step(
        build_demo_context(),
        **_coupled_arguments(solar_loss=0.01),
    )

    assert tuple(calls) == helper_names


def test_no_physics_characterization_preserves_clock_and_state() -> None:
    context = build_demo_context()
    original_inputs = context.inputs
    original_spacecraft = context.spacecraft_state
    original_battery = context.spacecraft_state.battery

    result = SimulationEngine().step(context)

    assert (
        result.start_time_seconds,
        result.end_time_seconds,
        result.dt_seconds,
    ) == (0, 60, 60)
    assert result.executed_phases == STEP_PHASE_ORDER
    assert _physical_result_fields(result) == (None,) * 6
    assert context.simulation_time_seconds == 60
    assert context.diagnostics.completed_steps == 1
    assert context.spacecraft_state.battery.energy_wh == 250.0
    assert [
        node.temperature_k
        for node in context.spacecraft_state.thermal.node_states
    ] == [295.0, 293.0, 291.0]
    assert context.spacecraft_state.degradation.battery == (
        original_spacecraft.degradation.battery
    )
    assert context.inputs is original_inputs
    assert context.spacecraft_state is not original_spacecraft
    assert context.spacecraft_state.battery is not original_battery


def test_eps_only_characterization_is_numerically_unchanged() -> None:
    context = build_demo_context()
    eps_inputs = build_step_inputs(0)[0]

    result = SimulationEngine().step(context, eps_inputs=eps_inputs)

    assert result.eps_result is not None
    assert result.eps_capability_result is not None
    assert result.eps_result.battery.end_energy_wh == pytest.approx(
        251.68666666666667
    )
    assert result.eps_result.battery.charge_input_w == 110
    assert result.eps_result.battery.unmet_load_w == 0.0
    assert result.eps_capability_result.battery_usable_capacity_wh == 500.0
    assert _physical_result_fields(result)[1:4] == (None, None, None)
    assert result.battery_capacity_reconciliation_result is None
    assert context.spacecraft_state.battery.energy_wh == (
        result.eps_result.battery.end_energy_wh
    )
    assert [
        node.temperature_k
        for node in context.spacecraft_state.thermal.node_states
    ] == [295.0, 293.0, 291.0]
    assert (
        context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
        == 0.0
    )
    assert context.simulation_time_seconds == 60
    assert context.diagnostics.completed_steps == 1


def test_coupled_characterization_is_numerically_unchanged() -> None:
    context = build_demo_context()

    result = SimulationEngine().step(context, **_coupled_arguments())

    assert result.eps_result is not None
    assert result.thermal_coupling_result is not None
    assert result.battery_degradation_result is not None
    assert result.solar_degradation_result is None
    assert result.eps_capability_result is not None
    assert result.battery_capacity_reconciliation_result is not None
    assert result.eps_result.battery.end_energy_wh == pytest.approx(
        251.68666666666667
    )
    assert [
        transition.end_temperature_k
        for transition in (
            result.thermal_coupling_result.thermal_result.node_transitions
        )
    ] == pytest.approx(
        [294.9711357979018, 292.9738083288189, 290.964853888334]
    )
    degradation = result.battery_degradation_result
    assert degradation.throughput_increment_wh == pytest.approx(
        1.6866666666666668
    )
    assert degradation.representative_temperature_k == pytest.approx(
        292.98690416440945
    )
    assert degradation.end_cumulative_energy_throughput_wh == pytest.approx(
        1.6866666666666668
    )
    reconciliation = result.battery_capacity_reconciliation_result
    assert reconciliation.authoritative_end_energy_wh == pytest.approx(
        251.68666666666667
    )
    assert context.spacecraft_state.battery.energy_wh == (
        reconciliation.authoritative_end_energy_wh
    )
    assert [
        node.temperature_k
        for node in context.spacecraft_state.thermal.node_states
    ] == pytest.approx(
        [294.9711357979018, 292.9738083288189, 290.964853888334]
    )
    assert (
        context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
        == pytest.approx(1.6866666666666668)
    )
    assert context.simulation_time_seconds == 60
    assert context.diagnostics.completed_steps == 1


def test_solar_forced_characterization_is_numerically_unchanged() -> None:
    context = build_demo_context()

    result = SimulationEngine().step(
        context,
        **_coupled_arguments(solar_loss=0.01),
    )

    solar = result.solar_degradation_result
    assert solar is not None
    assert solar.start_generation_retention == 1.0
    assert solar.retention_loss == 0.01
    assert solar.end_generation_retention == 0.99
    assert (
        context.spacecraft_state.degradation.solar.generation_retention
        == 0.99
    )
    assert result.eps_capability_result.solar_generation_retention == 1.0
    assert result.eps_result.solar.generation_w == 180.0


def test_coupled_working_state_mutates_only_after_reconciliation(
    monkeypatch,
) -> None:
    initial = build_demo_context()
    observed_working = []
    original_reconciliation = (
        engine_module.compute_battery_capacity_reconciliation
    )

    class CapturingEngine(SimulationEngine):
        def _physical_integration(self, context, interval, physical_inputs):
            observed_working.append(context)
            return super()._physical_integration(
                context,
                interval,
                physical_inputs,
            )

    def reconcile(*args, **kwargs):
        working = observed_working[0]
        assert working.spacecraft_state.battery.energy_wh == 250.0
        assert [
            node.temperature_k
            for node in working.spacecraft_state.thermal.node_states
        ] == [295.0, 293.0, 291.0]
        battery = working.spacecraft_state.degradation.battery
        assert battery.usable_capacity_retention == 1.0
        assert battery.cumulative_energy_throughput_wh == 0.0
        return original_reconciliation(*args, **kwargs)

    monkeypatch.setattr(
        engine_module,
        "compute_battery_capacity_reconciliation",
        reconcile,
    )

    result = CapturingEngine().step(initial, **_coupled_arguments())

    assert len(observed_working) == 1
    assert observed_working[0] is not initial
    assert initial.spacecraft_state.battery.energy_wh == (
        result.battery_capacity_reconciliation_result
        .authoritative_end_energy_wh
    )


def test_handler_exception_after_working_mutation_rolls_back_every_domain(
) -> None:
    context = build_demo_context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    observed_working = []

    class ExpectedHandlerError(RuntimeError):
        pass

    def factory():
        def handler(working, interval):
            observed_working.append((working, interval))
            working.spacecraft_state.battery.energy_wh = 1.0
            working.spacecraft_state.thermal.node_states[0].temperature_k = 1.0
            working.spacecraft_state.degradation.battery.usable_capacity_retention = (
                0.5
            )
            working.diagnostics.completed_steps = 99
            working.simulation_time_seconds = 99
            raise ExpectedHandlerError("synthetic handler failure")

        return handler

    with pytest.raises(ExpectedHandlerError, match="synthetic handler"):
        SimulationEngine()._run_transaction(
            context,
            physical_integration_handler_factory=factory,
        )

    assert len(observed_working) == 1
    assert observed_working[0][0] is not context
    _assert_authoritative_rollback(context, before, references)


@pytest.mark.parametrize(
    "helper_name",
    (
        "compute_eps_interval_transition",
        "compute_eps_thermal_interval_transition",
        "compute_battery_degradation_transition",
    ),
)
def test_physical_helper_failures_propagate_with_identity_rollback(
    helper_name,
    monkeypatch,
) -> None:
    context = build_demo_context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    class ExpectedPhysicalError(RuntimeError):
        pass

    def fail(*args, **kwargs):
        raise ExpectedPhysicalError(f"synthetic {helper_name} failure")

    monkeypatch.setattr(engine_module, helper_name, fail)

    with pytest.raises(ExpectedPhysicalError, match=helper_name):
        SimulationEngine().step(context, **_coupled_arguments())

    _assert_authoritative_rollback(context, before, references)


def test_capacity_reconciliation_failure_has_complete_identity_rollback(
    monkeypatch,
) -> None:
    context = build_demo_context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    calls = []
    preceding_helpers = (
        "compute_eps_interval_transition",
        "compute_eps_thermal_interval_transition",
        "compute_battery_degradation_transition",
    )
    for helper_name in preceding_helpers:
        original = getattr(engine_module, helper_name)

        def wrapper(
            *args,
            _name=helper_name,
            _original=original,
            **kwargs,
        ):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(engine_module, helper_name, wrapper)

    class ExpectedReconciliationError(RuntimeError):
        pass

    def fail(*args, **kwargs):
        calls.append("compute_battery_capacity_reconciliation")
        raise ExpectedReconciliationError("synthetic reconciliation failure")

    monkeypatch.setattr(
        engine_module,
        "compute_battery_capacity_reconciliation",
        fail,
    )

    with pytest.raises(
        ExpectedReconciliationError,
        match="synthetic reconciliation failure",
    ):
        SimulationEngine().step(context, **_coupled_arguments())

    assert tuple(calls) == (
        *preceding_helpers,
        "compute_battery_capacity_reconciliation",
    )
    assert context.simulation_time_seconds == 0
    assert context.diagnostics.completed_steps == 0
    _assert_authoritative_rollback(context, before, references)


def test_invalid_completed_working_context_rolls_back_every_identity() -> None:
    context = build_demo_context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    class CorruptingEngine(SimulationEngine):
        @staticmethod
        def _advance_clock(working, interval):
            SimulationEngine._advance_clock(working, interval)
            working.spacecraft_state.battery.energy_wh = -1.0

    with pytest.raises(ValueError, match="energy_wh"):
        CorruptingEngine().step(context)

    _assert_authoritative_rollback(context, before, references)


def test_invalid_physical_result_carrier_rolls_back_every_identity() -> None:
    context = build_demo_context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    def factory():
        return lambda working, interval: object()

    with pytest.raises(TypeError, match="PHYSICAL_INTEGRATION"):
        SimulationEngine()._run_transaction(
            context,
            physical_integration_handler_factory=factory,
        )

    _assert_authoritative_rollback(context, before, references)


def test_step_result_validation_failure_occurs_once_before_commit(
    monkeypatch,
) -> None:
    context = build_demo_context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    result_calls = []
    commit_calls = []

    class ExpectedResultError(RuntimeError):
        pass

    def fail_result(*args, **kwargs):
        result_calls.append((args, kwargs))
        raise ExpectedResultError("synthetic StepResult failure")

    def fail_commit(*args):
        commit_calls.append(args)
        pytest.fail("commit must not be reached")

    monkeypatch.setattr(engine_module, "StepResult", fail_result)
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(fail_commit),
    )

    with pytest.raises(ExpectedResultError, match="StepResult"):
        SimulationEngine().step(context)

    assert len(result_calls) == 1
    assert commit_calls == []
    _assert_authoritative_rollback(context, before, references)


def test_checkpoint_schema_and_engine_f3b_dependencies_are_explicit() -> None:
    historical_checkpoint_source = subprocess.run(
        [
            "git",
            "show",
            "d2c2b3afae8f1e6e9a1396037f47364e8016eafd:ops_sim/v5/checkpoint.py",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    historical_engine_source = subprocess.run(
        ["git", "show", f"{F3B_COMMIT}:ops_sim/v5/engine.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    tree = ast.parse(historical_engine_source)
    imported_modules = {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }

    assert "CURRENT_CHECKPOINT_SCHEMA_VERSION = 3" in (
        historical_checkpoint_source
    )
    assert {
        module
        for module in imported_modules
        if module.startswith("imaging")
    } == {
        "imaging_authorization",
        "imaging_execution",
        "imaging_resources",
    }
    assert "thermal_routing" in imported_modules
    assert {
        "ImagingEngineStepAttempt",
        "ImagingExecutionAuthorizationResult",
        "ScheduledObservationAcquisitionExecution",
    } <= identifiers
    assert "imaging_thermal" not in imported_modules
    assert tuple(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "step_imaging"
    ) == ("step_imaging",)
    assert SimulationEngine.__slots__ == ()


def test_transaction_seam_has_one_production_definition() -> None:
    definitions = {
        name: []
        for name in (
            "_run_transaction",
            "_complete_coupled_physical_integration",
        )
    }
    for path in (ROOT / "ops_sim" / "v5").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in definitions:
                definitions[node.name].append(path.name)

    assert definitions == {
        "_run_transaction": ["engine.py"],
        "_complete_coupled_physical_integration": ["engine.py"],
    }


def test_d255_through_d262_and_f3a_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s003 = sources.partition("### S003 ")[2].partition("### S004 ")[0]
    s004 = sources.partition("### S004 ")[2].partition("### S005 ")[0]
    s005 = sources.partition("### S005 ")[2].partition("### S006 ")[0]
    combined = " ".join((s003 + s004 + s005).lower().split())

    for number in range(255, 263):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D254 ") < decisions.index("## D255 ")
    assert "v5.3f3a" in combined
    assert "no new physical source or value" in combined
    assert "transaction kernel" in combined
    assert "generic eps" in combined
    assert "thermal" in combined
    assert "degradation" in combined
    assert "reconciliation" in combined
    assert "schema 3" in combined
    assert "no imaging execution" in combined
