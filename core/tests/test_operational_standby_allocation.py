"""R1: independent decimal witnesses, owner rounding and fractional restart."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from math import inf, nextafter
import json
import os
import subprocess
import sys

import pytest

from examples import v5_operational_protection_demo as demo
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.continuation import CoupledDownlinkAction
from ops_sim.v5.eps_capability import compute_eps_capability
from ops_sim.v5.eps_system import EPSIntervalInputs, compute_eps_interval_transition
from ops_sim.v5.experiment_bundle import create_bundle
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.operational_continuation import (
    OperationalProgram, OperationalMemory, OperationalState, advance_operational_continuation)
from ops_sim.v5.operational_protection import (
    ActionKind, ProtectedRequest, StandbyAction, execute_protected_request,
    evaluate_action_availability)
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.thermal_routing import (
    ElectricalLoadComponent as C, ServedComponentPower, ServedPowerLedger,
    compute_routed_internal_heat)
import ops_sim.v5.operational_protection as protection


FORWARD = tuple(C)
REVERSE = tuple(reversed(FORWARD))
THERMAL_FIRST = (C.THERMAL_CONTROL, C.OBC, C.BASE_BUS, C.ADCS,
                 C.PAYLOAD, C.COMMUNICATIONS, C.PROPULSION)
FULL = ((.1, .1, 1.1, 0.), (12.1, 3.1, 5.1, 1.3), (12.1, 3.3, 5.2, 1.1))
DEFICIENT = (21.977, 18.199, 20.138, 25.591)


def case(demands, *, maximum=200., energy=80., sunlit=False, order=FORWARD):
    context = demo.physical.reference_context()
    cfg = context.inputs.spacecraft_configuration
    battery = replace(cfg.eps.battery, max_discharge_output_power_w=demo.physical.parameter_value(
        cfg.eps.battery.max_discharge_output_power_w, maximum))
    context.inputs = replace(context.inputs, spacecraft_configuration=replace(
        cfg, eps=replace(cfg.eps, battery=battery)))
    context.spacecraft_state.battery.energy_wh = energy
    loads = PowerLoadBreakdown(*demands[:3], 0., 0., demands[3], 0.)
    request = ProtectedRequest(StandbyAction("fractional-standby"),
                              demo.standby(context, loads=loads, sunlit=sunlit))
    return (context, demo.physical.storage._previous_execution(), request,
            replace(demo.policy(context), standby_service_order=order))


def actual_eps(context, request):
    cfg = context.inputs.spacecraft_configuration.eps
    s = request.standby
    return compute_eps_interval_transition(context.spacecraft_state.battery, cfg,
        EPSIntervalInputs(s.sunlit, s.incidence_angle_deg, s.loads), dt_seconds=36,
        capability=compute_eps_capability(cfg, context.spacecraft_state.degradation))


def seven(values):
    return (*values[:3], 0., 0., values[3], 0.)


def sequential(values):
    # Independent explicit fold: NOT Python 3.14's compensated builtin sum.
    total = 0
    for value in values:
        total = total + value
    return total


def witness(context, request, eps, expected):
    ledger = ServedPowerLedger(tuple(ServedComponentPower(c, demand, served)
        for c, demand, served in zip(C, seven((request.standby.loads.base_bus_w,
            request.standby.loads.obc_w, request.standby.loads.adcs_w,
            request.standby.loads.thermal_control_w)), expected)))
    return compute_routed_internal_heat(request.standby.loads, ledger,
        request.standby.routing_config, context.inputs.spacecraft_configuration.thermal.network,
        eps_result=eps)


def check_execution(context, previous, request, policy, eps, expected=None):
    before = deepcopy(context)
    result = execute_protected_request(context, previous, request, policy=policy)
    assert result.step_result.eps_result == eps
    components = result.standby_routed_heat.component_ledgers
    served = tuple(x.served_power_w for x in components)
    if expected is not None:
        assert served == expected
    assert sequential(served) == eps.battery.served_load_w
    assert all(0 <= x.served_power_w <= x.requested_power_w for x in components)
    by_component = {x.component: x for x in components}
    shortage_seen = False
    for c in policy.standby_service_order:
        x = by_component[c]
        if shortage_seen:
            assert x.served_power_w == 0
        shortage_seen |= x.served_power_w < x.requested_power_w
        assert x.retained_heat_fraction == .5  # independently declared fixture
        assert x.retained_heat_w == x.served_power_w * .5
    assert context.simulation_time_seconds == before.simulation_time_seconds + 36
    assert context.diagnostics.completed_steps == before.diagnostics.completed_steps + 1
    assert context.spacecraft_state.data_storage == before.spacecraft_state.data_storage
    assert context.ground_data_delivery_state == before.ground_data_delivery_state
    assert context.ground_knowledge_state == before.ground_knowledge_state
    assert result.outcome.actual_kind is ActionKind.STANDBY
    assert result.outcome.availability.essential_unmet_w == eps.battery.unmet_load_w
    return result


@pytest.mark.parametrize("demands", FULL)
@pytest.mark.parametrize("order", (FORWARD, REVERSE, THERMAL_FIRST))
def test_full_service_original_decimal_demands_and_independent_routing_witness(demands, order):
    c, previous, request, policy = case(demands, order=order)
    eps = actual_eps(c, request)
    assert eps.battery.unmet_load_w == 0
    assert eps.battery.served_load_w == request.standby.loads.total_load_w
    expected = seven(demands)
    accepted = witness(c, request, eps, expected)
    result = check_execution(c, previous, request, policy, eps, expected)
    assert result.standby_routed_heat == accepted


@pytest.mark.parametrize("order", (FORWARD, REVERSE, THERMAL_FIRST))
def test_qualified_deficit_preserves_declared_priority_with_exact_owner_total(order):
    c, previous, request, policy = case(DEFICIENT, maximum=59.106, order=order)
    eps = actual_eps(c, request)
    assert eps.battery.served_load_w == 59.106
    assert eps.battery.unmet_load_w == 26.799
    if order == FORWARD:
        expected = seven((21.977, 18.199, 18.93, 0.))
        accepted = witness(c, request, eps, expected)
    else:
        expected = None
    result = check_execution(c, previous, request, policy, eps, expected)
    if order == FORWARD:
        assert result.standby_routed_heat == accepted
    else:
        # Independent exact-binary reference for the full priority prefix.
        demand = dict(zip(C, seven(DEFICIENT)))
        residual = Fraction(59.106)
        served = {x.component: x.served_power_w for x in result.standby_routed_heat.component_ledgers}
        for component in order:
            if Fraction(demand[component]) <= residual:
                assert served[component] == demand[component]
                residual -= Fraction(demand[component])
            else:
                # All these qualified permutations admit the nearest residual.
                assert served[component] == float(residual)
                break


@pytest.mark.parametrize("energy,maximum,sunlit,expected,unmet", [
    (0., 200., False, (0., 0., 0., 0.), 1.75),
    (80., 1.75, False, (.25, .5, .75, .25), 0.),
    (80., .5, False, (.25, .25, 0., 0.), 1.25),
    (0., 200., True, (.25, .5, .75, .25), 0.),
])
def test_zero_exact_full_deficient_surplus(energy, maximum, sunlit, expected, unmet):
    c, previous, request, policy = case((.25, .5, .75, .25), energy=energy,
        maximum=maximum, sunlit=sunlit)
    eps = actual_eps(c, request)
    assert eps.battery.unmet_load_w == unmet
    witness(c, request, eps, seven(expected))
    check_execution(c, previous, request, policy, eps, seven(expected))


@pytest.mark.parametrize("demands,maximum,order,preferred,partial", [
    ((4.164, 2.587, 19.68, 30.202), 51.883,
     (C.OBC, C.BASE_BUS, C.PROPULSION, C.COMMUNICATIONS, C.ADCS, C.PAYLOAD, C.THERMAL_CONTROL),
     25.452, nextafter(25.452, inf)),
    ((99.996, 33.595, 11.912, 71.532), 146.818,
     (C.OBC, C.PROPULSION, C.PAYLOAD, C.BASE_BUS, C.COMMUNICATIONS, C.THERMAL_CONTROL, C.ADCS),
     13.227000000000018, nextafter(13.227000000000018, 0.)),
])
def test_nearest_owner_consistent_partial_on_either_side(demands, maximum, order, preferred, partial):
    c, previous, request, policy = case(demands, maximum=maximum, order=order)
    eps = actual_eps(c, request)
    assert eps.battery.served_load_w == maximum and eps.battery.unmet_load_w > 0
    prefix = demands[:3] if maximum == 51.883 else (*demands[:2], 0.)
    assert float(Fraction(maximum) - sum(map(Fraction, prefix))) == preferred
    assert sequential(seven((*prefix, preferred))) != maximum
    expected = seven((*prefix, partial))
    witness(c, request, eps, expected)
    check_execution(c, previous, request, policy, eps, expected)


def test_no_representable_fixed_prefix_rejects_atomically_with_independent_gap_proof():
    order = (C.PAYLOAD, C.BASE_BUS, C.THERMAL_CONTROL, C.PROPULSION,
             C.COMMUNICATIONS, C.ADCS, C.OBC)
    c, previous, request, policy = case((.721, 40.482, 65.091, 30.281), maximum=113.808, order=order)
    eps = actual_eps(c, request)
    assert eps.battery.served_load_w == 113.808 and eps.battery.unmet_load_w > 0
    high = 17.715000000000014
    low = nextafter(high, 0.)
    # Adjacent binary64 values bracket a missing target of this monotone fold.
    assert sequential((.721, low, 65.091, 0., 0., 30.281, 0.)) < 113.808
    assert sequential((.721, high, 65.091, 0., 0., 30.281, 0.)) > 113.808
    before = deepcopy(c)
    with pytest.raises(ValueError, match="no representable EPS-reconciled"):
        execute_protected_request(c, previous, request, policy=policy)
    assert c == before


def test_full_service_with_incompatible_aggregation_contract_remains_explicit_rejection():
    c, previous, request, policy = case((.1, .2, .3, 0.))
    eps = actual_eps(c, request)
    assert eps.battery.unmet_load_w == 0
    assert eps.battery.served_load_w == .6
    assert sequential(seven((.1, .2, .3, 0.))) == .6000000000000001
    with pytest.raises(ValueError, match="total served component power"):
        witness(c, request, eps, seven((.1, .2, .3, 0.)))
    before = deepcopy(c)
    with pytest.raises(ValueError, match="total served component power"):
        execute_protected_request(c, previous, request, policy=policy)
    assert c == before


@pytest.mark.parametrize("demands,maximum", [(FULL[0], 200.), (DEFICIENT, 59.106)])
def test_read_only_availability_and_single_authoritative_standby_eps(monkeypatch, demands, maximum):
    c, previous, request, policy = case(demands, maximum=maximum)
    before = deepcopy(c)
    calls = []
    original = protection.compute_eps_interval_transition
    def observe(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result)
        return result
    monkeypatch.setattr(protection, "compute_eps_interval_transition", observe)
    a = evaluate_action_availability(c, previous, request, policy=policy)
    assert len(calls) == 1 and c == before
    assert evaluate_action_availability(c, previous, request, policy=policy) == a
    assert len(calls) == 2 and c == before
    result = execute_protected_request(c, previous, request, policy=policy)
    assert len(calls) == 3
    assert result.step_result.eps_result is calls[-1]


def test_denied_mission_fallback_uses_fractional_standby_one_interval():
    c, previous, request, policy = case(FULL[0])
    # Hot required bus denies a real current-step downlink; storage is present.
    next(n for n in c.spacecraft_state.thermal.node_states if n.node_id.value == "bus").temperature_k = 321.
    request = replace(request, action=CoupledDownlinkAction("denied", demo.physical.contact(c),
        demo.physical.record().record_id, demo.physical.physical_inputs(c)))
    result = check_execution(c, previous, request, policy, actual_eps(c, request), seven(FULL[0]))
    assert result.outcome.availability.reasons
    assert result.requested_attempt is None


@pytest.mark.parametrize("demands,maximum", [(FULL[0], 200.), (DEFICIENT, 59.106)])
def test_fractional_late_failure_preserves_context_and_external_identities(monkeypatch, demands, maximum):
    c, previous, request, policy = case(demands, maximum=maximum)
    before = deepcopy(c)
    state, battery, ground = c.spacecraft_state, c.spacecraft_state.battery, c.ground_data_delivery_state
    def fail(result):
        assert result.standby_routed_heat is not None
        raise RuntimeError("late fractional result failure")
    monkeypatch.setattr(protection.ProtectedStepResult, "__post_init__", fail)
    with pytest.raises(RuntimeError, match="late fractional"):
        execute_protected_request(c, previous, request, policy=policy)
    assert c == before
    assert c.spacecraft_state is state and state.battery is battery
    assert c.ground_data_delivery_state is ground


@pytest.mark.parametrize("boundary", (0, 1, 2, 3))
def test_fractional_v3_json_fresh_process_restart(tmp_path, boundary):
    c, previous, request, policy = case(FULL[0], maximum=59.106)
    requests = tuple(ProtectedRequest(StandbyAction("fractional-" + str(i)),
        demo.standby(c, sunlit=False, loads=PowerLoadBreakdown(*seven(d))))
        for i, d in enumerate((FULL[0], DEFICIENT, FULL[2])))
    program = OperationalProgram(3, CheckpointState.from_context(c), previous, policy, requests,
                                 ("Synthetic fractional full/deficient/recovery standby sequence.",))
    states = [OperationalState(c, program, OperationalMemory((), previous))]
    for _ in requests:
        states.append(advance_operational_continuation(states[-1]))
    saved, output = tmp_path / "fractional.json", tmp_path / "resumed.json"
    saved.write_text(create_bundle(states[boundary], repository_root=demo.ROOT).to_json(), encoding="utf-8")
    code = "\n".join([
        "import sys",
        "from pathlib import Path",
        "from ops_sim.v5.experiment_bundle import ExperimentBundle",
        "from ops_sim.v5.operational_continuation import advance_operational_continuation",
        "s=ExperimentBundle.from_json(Path(sys.argv[1]).read_text(encoding='utf-8')).restore(repository_root=Path.cwd())",
        "while len(s.memory.outcomes)<len(s.program.requests): s=advance_operational_continuation(s)",
        "from ops_sim.v5.experiment_codec import canonical_content",
        "from ops_sim.v5.checkpoint import CheckpointState",
        "import json",
        "Path(sys.argv[2]).write_text(json.dumps([canonical_content(CheckpointState.from_context(s.context)),canonical_content(s.memory)]),encoding='utf-8')",
    ])
    process = subprocess.run([sys.executable, "-B", "-c", code, str(saved), str(output)],
        cwd=demo.ROOT, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "GIT_OPTIONAL_LOCKS": "0"})
    assert process.returncode == 0, process.stdout + process.stderr
    final = states[-1]
    assert json.loads(output.read_text(encoding="utf-8")) == [
        canonical_content(CheckpointState.from_context(final.context)), canonical_content(final.memory)]
    assert final.context.simulation_time_seconds == 208
    assert final.memory.previous_execution == previous
    assert final.context.spacecraft_state.data_storage == c.spacecraft_state.data_storage
    assert final.context.ground_data_delivery_state == c.ground_data_delivery_state
    assert [o.availability.essential_unmet_w for o in final.memory.outcomes] == [0., 26.799, 0.]
    assert final.memory.outcomes[-1].recovered
