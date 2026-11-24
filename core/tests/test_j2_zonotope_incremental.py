"""Opt-in endpoint-v3 integration, exact science and cumulative resource contracts."""
import dataclasses
from decimal import Decimal
from fractions import Fraction
import enum
import pytest

from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5 import orbit_j2_enclosure as old
from ops_sim.v5 import orbit_j2_zonotope as z
from test_v56f2_j2_coast_contracts import at, trajectory

EXCLUDED = {"scalar_operations", "charged_leaf_operations", "reserved_control_operations",
            "resource_policy_version", "kernel_id", "budget_rejected"}


def projection(value):
    if isinstance(value, enum.Enum):
        return ("enum", type(value).__module__, type(value).__qualname__, value.name)
    if type(value) is float:
        return ("float_hex", value.hex())
    if isinstance(value, Decimal):
        return ("decimal_tuple", tuple(value.as_tuple()))
    if isinstance(value, Fraction):
        return ("fraction", value.numerator, value.denominator)
    if dataclasses.is_dataclass(value):
        result = type(value) in (z.J2ZonotopeResultV2, z.J2ZonotopeResultV3)
        policy = type(value) in (z.J2ZonotopePolicyV2, z.J2ZonotopePolicyV3)
        name = "result" if result else "policy" if policy else type(value).__module__+"."+type(value).__qualname__
        return (name, tuple((f.name, projection(getattr(value, f.name)))
                            for f in dataclasses.fields(value)
                            if not ((result or policy) and f.name in EXCLUDED)))
    if isinstance(value, (tuple, list)):
        return tuple(projection(v) for v in value)
    assert value is None or type(value) in (str, int, bool)
    return value


def policy(cap=2**24, precision=50, scales=(0,)*6, **base_changes):
    base = dataclasses.replace(old.J2EnclosurePolicy(1/32, 4096, .5, precision, 12), **base_changes)
    return z.J2ZonotopePolicyV3(base, scales, cap)


def run(span=1/32, *, t=None, p=None, config=None):
    t = trajectory(t0=128) if t is None else t
    return z.evaluate_j2_zonotope_enclosure_v3(
        t, at(t, 128+span), config or f2.J2RK4SolverConfig(1/32, 4096), p or policy())


def atomic(result):
    assert result.status == "unresolved" and result.reason
    assert all(getattr(result, name) is None for name in (
        "nominal_state", "endpoint_intervals", "position_error_bound_m",
        "velocity_error_bound_m_per_s", "diagnostic_state"))
    assert result.scalar_operations == result.charged_leaf_operations + result.reserved_control_operations
    assert 0 <= result.scalar_operations <= result.policy.max_scalar_operations


@pytest.mark.parametrize("span", [0, 1/32, -1/32, 3/64, -3/64, 1/8])
@pytest.mark.parametrize("j2", [0, 11/32, -11/32])
@pytest.mark.parametrize("precision", [40, 50, 80])
def test_full_scientific_equality_v2_forward_backward_remainder_zero(span, j2, precision):
    t = trajectory(r=(2, 0, 0), v=(0, 17/8, 0), mu=8, j2=j2, rg=1, t0=128)
    p = policy(precision=precision)
    c = f2.J2RK4SolverConfig(1/32, 4096)
    instant = at(t, 128+span)
    v2 = z.evaluate_j2_zonotope_enclosure_v2(
        t, instant, c, z.J2ZonotopePolicyV2(p.base_policy, p.scale_exponents, p.max_scalar_operations))
    v3 = z.evaluate_j2_zonotope_enclosure_v3(t, instant, c, p)
    assert v2.status == v3.status == "enclosed", v3.reason
    assert projection(v2) == projection(v3)
    assert v3.diagnostic_state.time == Fraction(128+span)
    assert v3.trajectory.initial_state == t.initial_state
    assert v3.scalar_operations == v3.charged_leaf_operations + v3.reserved_control_operations
    assert not v3.budget_rejected and v3.nominal_evaluations == 1
    assert v3.resource_policy_version == v3.policy.resource_policy_version == 3
    assert v3.kernel_id == v3.policy.kernel_id == "incremental-j2-jet-v1"


def test_actual_kernel_order_owner_and_no_legacy_fallback(monkeypatch):
    t = trajectory(t0=128);p = policy()
    expected = z.evaluate_j2_zonotope_enclosure_v2(
        t, at(t, 128+3/64), f2.J2RK4SolverConfig(1/32, 4096),
        z.J2ZonotopePolicyV2(p.base_policy, p.scale_exponents, p.max_scalar_operations))
    original = z._coefficients_incremental_v1
    seen = []
    def incremental(box, order, model, ar):
        assert type(ar) is z._CoefficientArithmeticV3
        assert type(box) is tuple and all(e._ar is ar for i in box for e in (i.lo, i.hi))
        before = ar.operations
        answer = original(box, order, model, ar)
        seen.append((ar, order, before, ar.operations))
        return answer
    def legacy(*args):
        raise AssertionError("v3 must never invoke the legacy coefficient kernel")
    monkeypatch.setattr(z, "_coefficients_incremental_v1", incremental)
    monkeypatch.setattr(old, "_coefficients", legacy)
    result = run(3/64, t=t, p=p)
    assert result.status == "enclosed" and projection(result) == projection(expected)
    assert [x[1] for x in seen] == [6, 7, 6, 7]
    assert len({id(x[0]) for x in seen}) == 1
    assert all(a[3] < b[2] for a, b in zip(seen, seen[1:]))
    assert result.scalar_operations > seen[-1][3]  # final publication shares ledger


def test_original_anchor_fresh_cumulative_query_owner(monkeypatch):
    real = z._coefficients_incremental_v1;owners=[];starts=[]
    def spy(box, order, model, ar):
        owners.append(ar);starts.append(ar.operations)
        return real(box, order, model, ar)
    monkeypatch.setattr(z, "_coefficients_incremental_v1", spy)
    first = run(1/16);second = run(1/16)
    assert projection(first) == projection(second) and first.status == "enclosed"
    assert len(owners) == 8 and owners[0] is owners[3] and owners[4] is owners[7]
    assert owners[0] is not owners[4] and starts[0] == starts[4]
    assert first.trajectory.initial_state.position.instant.elapsed_seconds == 128


@pytest.mark.parametrize("cap", [1, 511, 512, 1024, 8192])
def test_budget_failure_bounded_atomic_and_rejected_latch(cap):
    r = run(p=policy(cap=cap));atomic(r)
    assert r.budget_rejected is True and r.nominal_evaluations == 0


def test_direct_rejected_latch_cannot_be_restarted():
    ar = z._CoefficientArithmeticV3(50, 512)
    ar.reserve(512, "test bound")
    with pytest.raises(z._Unresolved):
        ar.charge()
    counts = ar.operations, ar.leaf_operations, ar.reserved_units
    assert ar.rejected
    with pytest.raises(z._Unresolved):
        ar.reserve(0, "no top-up")
    assert (ar.operations, ar.leaf_operations, ar.reserved_units) == counts


def test_atomic_failure_on_second_transport_after_completed_work(monkeypatch):
    real = z._coefficients_incremental_v1;calls = 0
    def fail_after_first_step(box, order, model, ar):
        nonlocal calls
        calls += 1
        if calls == 3:
            assert ar.completed_steps == 1 and ar.attempted_steps == 2
            raise ValueError("injected second-leg coefficient failure")
        return real(box, order, model, ar)
    monkeypatch.setattr(z, "_coefficients_incremental_v1", fail_after_first_step)
    r = run(1/16);atomic(r)
    assert r.completed_steps == 1 and r.attempted_steps == 2 and calls == 3
    assert "injected second-leg" in r.reason and not r.budget_rejected
    assert r.nominal_counter_provenance == "DERIVED_FROM_SUCCESSFUL_F2_FIXED_GRID"


def test_exhaustion_after_completed_work_is_atomic(monkeypatch):
    real = z._coefficients_incremental_v1;calls=0
    def exhaust(box, order, model, ar):
        nonlocal calls
        calls += 1
        if calls == 3:
            ar.charge(ar.limit-ar.operations+1)
        return real(box, order, model, ar)
    monkeypatch.setattr(z, "_coefficients_incremental_v1", exhaust)
    r=run(1/16);atomic(r)
    assert r.completed_steps == 1 and r.budget_rejected and calls == 3


def test_final_publication_failure_never_exposes_success_fields(monkeypatch):
    def fail(*args):
        raise RuntimeError("injected final immutable publication failure")
    monkeypatch.setattr(z, "_plain_set", fail)
    r = run();atomic(r)
    assert r.completed_steps == 1 and "final immutable" in r.reason


@pytest.mark.parametrize("cap", [True, False, 0, -1, 2**31+1, 1.0, None])
def test_strict_cap_rejection(cap):
    with pytest.raises((TypeError, ValueError)):
        policy(cap=cap)


@pytest.mark.parametrize("scales", [[0]*6, (0,)*5, (0,)*7, (True, 0, 0, 0, 0, 0), (33, 0, 0, 0, 0, 0)])
def test_strict_scale_domains(scales):
    with pytest.raises((TypeError, ValueError)):
        policy(scales=scales)


@pytest.mark.parametrize("field,value", [
    ("resource_policy_version", 2), ("resource_policy_version", True),
    ("kernel_id", "legacy"), ("kernel_id", 3), ("method_id", "other"),
    ("method_version", True), ("pb_order", 7), ("max_generators", 13),
    ("retained_generators", 5), ("rank_bit_cap", 8192)])
def test_forged_fixed_identity_is_structural_rejection(field, value):
    p=policy();object.__setattr__(p, field, value)
    with pytest.raises((TypeError, ValueError)):
        run(p=p)


def test_legacy_policy_not_silently_promoted():
    p=policy();oldp=z.J2ZonotopePolicyV2(p.base_policy, p.scale_exponents, p.max_scalar_operations)
    with pytest.raises(TypeError):
        run(p=oldp)


@pytest.mark.parametrize("changes", [{"min_radius_m":10}, {"max_steps":1}])
def test_inherited_radius_and_grid_guard_atomic(changes):
    r=run(1/16, p=policy(**changes));atomic(r)


def test_horizon_ceiling_not_expanded():
    r=run(86401);atomic(r)
    assert r.attempted_steps == r.nominal_evaluations == 0


def test_context_guard_failure_after_ledger_is_retained(monkeypatch):
    real=z._CoefficientArithmeticV3.__init__
    def corrupt(self,*args):
        real(self,*args)
        self.down._context.rounding = "ROUND_UP"
    monkeypatch.setattr(z._CoefficientArithmeticV3, "__init__", corrupt)
    r=run();atomic(r)
    assert "context settings" in r.reason


def test_immutable_required_inputs_and_append_only_exports():
    p=policy(cap=2**31);r=run(0,p=p)
    assert not hasattr(p,"__dict__") and not hasattr(r,"__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.max_scalar_operations=1
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.status="enclosed"
    assert z.__all__ == [
        "J2ZonotopePolicy","J2ZonotopeResult","evaluate_j2_zonotope_enclosure",
        "J2ZonotopePolicyV2","J2ZonotopeResultV2","evaluate_j2_zonotope_enclosure_v2",
        "J2ZonotopePolicyV3","J2ZonotopeResultV3","evaluate_j2_zonotope_enclosure_v3"]
