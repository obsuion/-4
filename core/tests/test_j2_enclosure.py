"""Independent rational reference intervals and accumulated-error contracts.

No endpoint acceptance uses RK4 self-agreement, refinement or fitted tolerance.
The sin/cos references use exact rational Taylor polynomials with the analytic
Lagrange remainder |x|**(N+1)/(N+1)! (all real sin/cos derivatives <= 1).
"""

from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal, DecimalException, Inexact, ROUND_UP, localcontext
from fractions import Fraction as Q
from math import factorial
import subprocess
import sys

import pytest

from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5 import orbit_j2_enclosure as f3
from ops_sim.v5.orbit_config import GeometryInstant, TTEpoch
from test_v56f2_j2_coast_contracts import at, trajectory
from test_v56f1_j2_gravity_contracts import change_path, forge, TextTrap


def policy(h=1/32, **changes):
    return replace(f3.J2EnclosurePolicy(h, 256, .5, 50, 12), **changes)


def run(t=None, span=.5, h=1/32, p=None, maximum=256):
    t = trajectory(j2=11/32, v=(0, 17/8, 0)) if t is None else t
    return f3.evaluate_j2_enclosure(t, at(t, t.initial_state.position.instant.elapsed_seconds+span),
                                    f2.J2RK4SolverConfig(h, maximum), p or policy(h))


def trig_interval(x, sine):
    n = 100
    value = sum(((-1)**(k//2)*x**k/Q(factorial(k)) for k in range(1 if sine else 0, n+1, 2)), Q())
    remainder = abs(x)**(n+1)/factorial(n+1)
    return value-remainder, value+remainder


def scale(pair, factor):
    return tuple(sorted(factor*x for x in pair))


def circle_intervals(span, nonzero=True):
    n = Q(17, 16) if nonzero else Q(1)
    s, c = trig_interval(n*span, True), trig_interval(n*span, False)
    return (scale(c, 2), scale(s, 2), (Q(0), Q(0)),
            scale(s, -2*n), scale(c, 2*n), (Q(0), Q(0)))


def assert_contains(result, reference):
    assert result.status == 'enclosed', result.reason
    actual = (*result.nominal_state.position.components_m,
              *result.nominal_state.velocity.components_m_per_s)
    bounds = (result.position_error_bound_m,)*3+(result.velocity_error_bound_m_per_s,)*3
    for pair, (lo, hi), nominal, bound in zip(result.endpoint_intervals, reference, actual, bounds):
        # Exact rational comparisons include the entire independent uncertainty.
        assert Q(pair[0]) <= lo <= hi <= Q(pair[1])
        assert max(abs(lo-Q(nominal)), abs(hi-Q(nominal))) <= Q(bound)


@pytest.mark.parametrize('nonzero', [False, True], ids=['central', 'J2'])
@pytest.mark.parametrize('span', [-1.03125, -.5, .015625, .5, 1.03125])
@pytest.mark.parametrize('anchor', [0, 32.125])
def test_exact_circular_references_with_independent_uncertainty(nonzero, span, anchor):
    t = trajectory(v=(0, 17/8 if nonzero else 2, 0), j2=11/32 if nonzero else 0, t0=anchor)
    result = run(t, span)
    assert_contains(result, circle_intervals(Q(result.instant.elapsed_seconds)-Q(anchor), nonzero))
    assert result.nominal_state == f2.evaluate_j2_cartesian_state(t, result.instant, result.solver_config)
    full, tail = divmod(abs(Q(span)), Q(1,32))
    assert result.enclosure_steps == result.nominal_steps == full+bool(tail)


@pytest.mark.parametrize('sign', [-1, 1])
def test_zero_j2_rectilinear_parabolic_exact_binary_endpoint(sign):
    # r0=2, v0=2, mu=4: r(t)=2*(1+3*t/2)**(2/3), v=2/sqrt(r/2).
    # Choose t=7/6? Instead choose cube coordinate u=1 +/- 3/8,
    # t=(u**3-1)*2/3, exactly dyadic because numerator divisible by 3.
    u = Q(1)+sign*Q(3,8)
    span = (u**3-1)*Q(2,3)
    assert Q(float(span)) == span
    t = trajectory(r=(2,0,0), v=(2,0,0), mu=4, j2=0, t0=0)
    result = run(t,float(span),p=policy(min_radius_m=.25))
    exact = (2*u*u, Q(0), Q(0), 2/u, Q(0), Q(0))
    assert_contains(result, tuple((x,x) for x in exact))


@pytest.mark.parametrize('span', [-.5,.5])
def test_zero_j2_circle_in_polar_plane(span):
    reference=circle_intervals(Q(span),False)
    polar=tuple(reference[i] for i in (0,2,1,3,5,4))
    assert_contains(run(trajectory(v=(0,0,2),j2=0),span),polar)


def test_zero_span_has_exact_zero_bounds_and_no_steps():
    result = run(span=0)
    assert result.status == 'enclosed'
    assert result.nominal_state == result.trajectory.initial_state
    assert result.position_error_bound_m == result.velocity_error_bound_m_per_s == 0
    assert result.enclosure_steps == result.nominal_steps == result.picard_attempts == 0


def test_reordered_repeated_and_reconstructed_queries_are_identical():
    times = (.125,-.25,.5,.125)
    forward = [run(span=t) for t in times]
    reverse = [run(span=t) for t in reversed(times)]
    assert forward == list(reversed(reverse)) and forward[0] == forward[-1]
    assert replace(forward[0]) == forward[0]


def test_enclosure_grid_is_independent_of_nominal_solver_grid():
    result = run(span=.515625, h=1/16, p=policy(1/64))
    assert result.nominal_steps == 9 and result.enclosure_steps == 33
    assert_contains(result, circle_intervals(Q(33,64)))


def test_complete_authorities_preserved_and_outputs_cannot_be_injected():
    result = run(span=0)
    assert result.trajectory == trajectory(j2=11/32, v=(0,17/8,0))
    assert result.instant == result.trajectory.initial_state.position.instant
    assert [f.name for f in fields(result) if f.init] == ['trajectory','instant','solver_config','policy']
    with pytest.raises(FrozenInstanceError):
        result.status = 'unresolved'
    with pytest.raises(TypeError):
        f3.J2EnclosureResult(result.trajectory,result.instant,result.solver_config,result.policy,status='enclosed')
    bad = forge(result, status='unresolved', position_error_bound_m=123, policy_version=999)
    assert replace(bad) == result
    changed = change_path(result.trajectory,'gravity_model.j2.provenance.rationale','Different provenance')
    updated = replace(result, trajectory=changed)
    assert updated != result and updated.nominal_state == result.nominal_state
    assert updated.trajectory.gravity_model.j2.provenance.rationale == 'Different provenance'


@pytest.mark.parametrize('path,bad', [
    ('initial_state.position.components_m', (True,0,0)),
    ('initial_state.velocity.components_m_per_s', (float('nan'),0,0)),
    ('initial_state.velocity.instant.elapsed_seconds', 0),
    ('initial_state.position.frame.ellipsoid.name',TextTrap('bad')),
    ('initial_state.velocity.frame.ellipsoid.name','\ud800'),
    ('gravity_model.j2.provenance.units',TextTrap('1')),
    ('gravity_model.reference_radius_m.value',0),
], ids=['bool-position','nan-velocity','instant-mismatch','hostile-frame',
        'surrogate-frame','hostile-units','zero-radius'])
def test_invalid_authority_is_an_error_even_zero_span(path,bad):
    t=trajectory()
    with pytest.raises((TypeError,ValueError)):
        f3.evaluate_j2_enclosure(change_path(t,path,bad),at(t,32.125),f2.J2RK4SolverConfig(1,1),policy())


def test_incompatible_epoch_and_forged_policy_are_errors():
    t=trajectory(); request=GeometryInstant(TTEpoch(2451546,.125),32.125)
    with pytest.raises(ValueError,match='same TT'):
        f3.evaluate_j2_enclosure(t,request,f2.J2RK4SolverConfig(1,1),policy())
    with pytest.raises(TypeError):
        run(span=0,p=forge(policy(),max_steps=True))
    with pytest.raises(ValueError):
        f3.evaluate_j2_enclosure(t,at(t,32.125),forge(f2.J2RK4SolverConfig(1,1),step_seconds=0),policy())


@pytest.mark.parametrize('key,value', [('step_seconds',0),('step_seconds',True),('step_seconds',2048),
    ('min_radius_m',0),('precision_digits',39),('precision_digits',81),('max_steps',4097),
    ('max_steps',True),('max_picard_iterations',17)])
def test_policy_limits(key,value):
    with pytest.raises((TypeError,ValueError)):
        policy(**{key:value})


@pytest.mark.parametrize('case', ['enclosure-work','nominal-work','global-nominal-work','horizon',
    'picard','radius','continuous-radius','input-envelope','nominal-arithmetic','remainder','decimal-range'])
def test_unresolved_has_no_nominal_or_bounds(case):
    t=trajectory();p=policy();span=.5;h=1/32;maximum=256
    if case=='enclosure-work':p=replace(p,max_steps=1)
    if case=='nominal-work':maximum=1
    if case=='global-nominal-work':h=2**-14;maximum=10000
    if case=='horizon':span=86401
    if case=='picard':p=replace(p,max_picard_iterations=1)
    if case=='radius':p=replace(p,min_radius_m=3)
    if case=='continuous-radius':
        # Origin is safe; the accepted whole-step tube must also be safe.
        t=trajectory(v=(-10,0,0));span=.125;p=policy(.125,min_radius_m=1.5);h=.125
    if case=='input-envelope':t=trajectory(v=(2**-1074,0,0));span=0
    if case=='nominal-arithmetic':t=trajectory(t0=0);span=2**-60;h=2**-60
    if case=='remainder':t=trajectory(t0=-2**-53);span=1;h=2
    if case=='decimal-range':t=trajectory(r=(1e60,0,0),v=(0,1,0),mu=1e100,rg=1,j2=0,t0=0)
    result=(f3.evaluate_j2_enclosure(t,at(t,1),f2.J2RK4SolverConfig(2,1),p)
            if case=='remainder' else run(t,span,h,p,maximum))
    assert result.status=='unresolved' and result.reason
    assert result.nominal_state is result.endpoint_intervals is None
    assert result.position_error_bound_m is result.velocity_error_bound_m_per_s is None
    if case=='picard':assert result.picard_attempts==1
    if case in ('enclosure-work','nominal-work','global-nominal-work','horizon'):
        assert result.picard_attempts==result.enclosure_steps==result.nominal_steps==0


def test_work_rejection_never_enters_integrators(monkeypatch):
    def forbidden(*a):raise AssertionError('integration before work admission')
    monkeypatch.setattr(f3,'_step',forbidden)
    monkeypatch.setattr(f2,'evaluate_j2_cartesian_state',forbidden)
    assert run(p=policy(max_steps=1)).status=='unresolved'


def test_ambient_decimal_context_cannot_change_outputs():
    baseline=run(span=.0625)
    with localcontext() as ctx:
        ctx.prec=3;ctx.rounding=ROUND_UP;ctx.traps[Inexact]=True
        assert run(span=.0625)==baseline


def test_directed_primitives_contain_exact_rational_extrema():
    ar=f3._Arithmetic(40)
    for numbers in [('-1.123456789012345678901234567890123456789012345','2.7','3.1','4.00001'),
                    ('-3','-2','-7','-1'),('1e80','2e80','1e-80','3e-80')]:
        a,b=f3._I(*map(Decimal,numbers[:2])),f3._I(*map(Decimal,numbers[2:]))
        for op,exact in [(ar.add,lambda x,y:x+y),(ar.sub,lambda x,y:x-y),
                         (ar.mul,lambda x,y:x*y),(ar.div,lambda x,y:x/y)]:
            result=op(a,b);values=[exact(Q(x),Q(y)) for x in (a.lo,a.hi) for y in (b.lo,b.hi)]
            assert Q(result.lo)<=min(values)<=max(values)<=Q(result.hi)
    root=ar.sqrt(f3._I(Decimal(2),Decimal(3)))
    assert Q(root.lo)**2<=2 and Q(root.hi)**2>=3
    square=ar.square(f3._I(Decimal(-2),Decimal(3)))
    assert square.lo==0 and square.hi==9
    with pytest.raises(DecimalException):ar.mul(ar.point(Decimal('1e200')),ar.point(10))
    with pytest.raises(DecimalException):ar.mul(ar.point(Decimal('1e-200')),ar.point(Decimal('.1')))


def test_outward_float_export_including_underflow():
    for x in ('1.000000000000000000000000000001','1e-400','0','1e100'):
        d=Decimal(x);assert Q(f3._upper_float(d))>=Q(d)
    with pytest.raises(f3._Unresolved):f3._upper_float(Decimal('1e400'))


def test_interval_force_extension_matches_independent_potential_gradient():
    # At (3,4,12), radius=13 exactly. Differentiate unsimplified
    # Phi=-mu/r+A*(3*z*z/r**5-1/r**3) using exact rational arithmetic.
    for j2 in (Q(-1,16),Q(0),Q(11,32)):
        t=trajectory(r=(3,4,12),j2=float(j2));ar=f3._Arithmetic(50)
        state=[ar.point(x) for x in (3,4,12,0,0,0)]
        rhs=f3._field([[x] for x in state],t.gravity_model,ar)
        for i,x in enumerate((3,4,12)):
            derivative=Q(8*x,13**3)+4*j2*((Q(6*12,13**5) if i==2 else 0)-Q(15*12**2*x,13**7)+Q(3*x,13**5))
            assert Q(rhs[i+3][0].lo)<=-derivative<=Q(rhs[i+3][0].hi)


def test_tube_includes_entire_analytic_arc_not_only_endpoints():
    t=trajectory(j2=11/32,v=(0,17/8,0));ar=f3._Arithmetic(50)
    initial=[ar.point(x) for x in (2,0,0,0,17/8,0)]
    tube,_=f3._tube(initial,ar.point(.125),t.gravity_model,policy(),ar)
    for k in range(17):
        reference=circle_intervals(Q(k,128))
        for b,(lo,hi) in zip(tube,reference):assert Q(b.lo)<=lo<=hi<=Q(b.hi)
    # Samples supplement the algebraic Picard-inclusion check in production;
    # they are not the continuous-domain justification.


def test_smaller_steps_and_more_precision_preserve_containment_without_ratio_claim():
    for h,precision in ((1/16,40),(1/32,50),(1/64,80)):
        assert_contains(run(span=.25,h=h,p=policy(h,precision_digits=precision)),circle_intervals(Q(1,4)))


@pytest.mark.parametrize('span', [-.5,.5])
def test_negative_j2_exact_circle(span):
    # mu/r^3=1, J2=-5/8, Rg/r=1/2 -> n^2=49/64 exactly.
    t=trajectory(v=(0,7/4,0),j2=-5/8)
    n=Q(7,8);s,c=trig_interval(n*Q(span),True),trig_interval(n*Q(span),False)
    reference=(scale(c,2),scale(s,2),(Q(0),Q(0)),scale(s,-2*n),scale(c,2*n),(Q(0),Q(0)))
    assert_contains(run(t,span),reference)


def test_arithmetic_floor_does_not_require_monotonic_improvement():
    for h in (1/256,1/512,1/1024):
        result=run(span=1/64,h=h)
        assert_contains(result,circle_intervals(Q(1,64)))
        assert result.position_error_bound_m>0 and result.velocity_error_bound_m_per_s>0


def test_fresh_process_recomputation_is_exact():
    script="""import sys
sys.path.insert(0,'tests')
from test_j2_enclosure import run
r=run(span=.125)
print(repr((r.nominal_state.position.components_m,r.nominal_state.velocity.components_m_per_s,r.endpoint_intervals,r.position_error_bound_m,r.velocity_error_bound_m_per_s)))
"""
    result=run(span=.125)
    expected=repr((result.nominal_state.position.components_m,result.nominal_state.velocity.components_m_per_s,
                   result.endpoint_intervals,result.position_error_bound_m,result.velocity_error_bound_m_per_s))
    assert subprocess.check_output([sys.executable,'-B','-c',script],text=True).strip()==expected
