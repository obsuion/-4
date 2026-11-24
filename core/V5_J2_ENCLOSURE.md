# Task 06A: bounded accumulated J2 numerical error

Review candidate, 2026-09-23. Owner: `ops_sim/v5/orbit_j2_enclosure.py`.
F1/F2 remain unchanged. This closes the accumulated **endpoint** numerical-error
obligation for successful queries under the following explicit policy; it does
not establish flight accuracy, arbitrary-horizon usefulness or J2 visibility.

## Contract and admitted domain

`evaluate_j2_enclosure(trajectory, instant, solver_config, policy)` returns an
immutable `J2EnclosureResult`. Constructor admission reconstructs the complete
original Cartesian state (both frames and instants), F1 gravity/provenance,
requested TT instant, F2 solver and F3 policy. Exact owner types are required.
The original reference epoch must agree; absolute-date equivalence through a
different reference epoch is not sufficient. No metadata is discarded in the
result, and no output can be supplied to its constructor. `replace` recomputes.

The enclosed continuous IVP is precisely `r'=v`, `v'=a_F1(r)`, with real-number
interpretations of the **represented binary64** Cartesian components and F1
mu, unnormalized J2 and independent gravity radius. Its static symmetry axis is
MODEL_INERTIAL +z. Frame/TT metadata binds the query but does not rotate the field.
Neither provenance uncertainty nor Earth orientation/flight uncertainty enters
the enclosure. F1 is the sole physical parameter authority. `_field` is its
interval derivative extension of D317, not an independently fitted gravity model.

`J2EnclosurePolicy(step_seconds, max_steps, min_radius_m, precision_digits,
max_picard_iterations)` has no defaults. Policy version 1 fixes Taylor order six
and remainder order seven. Exact integer ranges: digits 40..80; enclosure steps
1..4096; Picard attempts per step 1..16. Enclosure step is in [2^-20,1024] seconds;
the positive radius floor is in [1e-6,1e12] metres. These limits bound computation,
not a mission or Earth model. Dynamical nonzero inputs (r, v, mu, J2, gravity radius,
F2 step) must have magnitude in [1e-100,1e100]; zeros are allowed where F1 permits.
Absolute span is at most 86400 seconds. The nominal RK4 count must not exceed
either its configured limit or 4096. All counts use exact rational represented
times before integration. The F2 remainder must retain F2's exact binary64
representability. F3's independent signed step grid uses rational durations
enclosed by directed Decimal division, including its final fractional step.

Every accepted whole-step box must establish radius >= `min_radius_m`, with a
strict Picard inclusion and finite arithmetic. Decimal precision/exponent limits,
wrapping, a failed tube search, an F2 arithmetic rejection or work exhaustion may
still make a syntactically valid request unresolved. Admission does **not** promise
that all queries within the static limits will succeed. No adaptive retry, cache,
reanchoring or heuristic bound enlargement after a reference comparison exists.

For `status='enclosed'`:

- `nominal_state` is exactly the state returned by the unchanged F2 evaluator.
- Six `endpoint_intervals` are Decimal lower/upper pairs in order x,y,z,vx,vy,vz.
- `position_error_bound_m` and `velocity_error_bound_m_per_s` bound the separate
  infinity norms between nominal and continuous endpoint (not Euclidean norms).
- Work records report completed enclosure/nominal steps and all attempted Picard
  inclusions, including a failed tube search. A failed nominal evaluation does not
  report its partial RK4 count; it is bounded above by the preflight step count.

For `status='unresolved'`, reason is explicit and **all** intervals, error bounds
and nominal state are `None`, including after a later-step failure. Completed
work counts are diagnostic only. Invalid configuration/metadata remains an
exception. Initial F1 evaluability is part of valid trajectory admission. Zero
span still validates authorities/domain and returns the original state with
exact zero numerical error when admitted. There is no visibility boolean.

## Derivation implemented by this candidate

The following is a project derivation specialized to the F1 autonomous analytic
field away from r=0. It is the direct box Taylor method, not Lohner QR or a
multivariate Taylor-model implementation. The primary reference is Neher,
Jackson and Nedialkov, *On Taylor model based integration of ODEs*, Karlsruhe
preprint 05/21 (2005), section 4, printed p.7, equations (4.1)-(4.5), with the
directed-rounding rule in section 2.1.2, p.3, and wrapping discussion in section
5.1, pp.8-9: <https://publikationen.bibliothek.kit.edu/1000004610/1003614>.

Let X contain the exact state at the start of a signed step h and let
H=[min(0,h),max(0,h)]. Find a finite box B such that

`X + H * F(B) subset interior(B)`.

Interval F is an inclusion extension of the mathematical F1 force and identity
velocity. The first-exit argument gives continuous containment: a local solution
starts in the interior, and at any prospective first exit its integral equation
puts it strictly back inside B. Smoothness on a neighborhood of the compact box
with radius bounded away from zero ensures uniqueness and continuation through
the whole step. The same argument applies to negative h. This is a whole-tube
check, not sampled radial admission. Candidate inflation by width/8 plus
`1e-30*max(1,abs(endpoints))` is only a bounded search heuristic; strict inclusion
is the acceptance test. Only coordinates which fail containment are expanded.

For each component let c_k(X) enclose y^(k)(0)/k! for every state in X. Automatic
Taylor coefficient arithmetic computes these by `c_(k+1)=[F(c)]_k/(k+1)`.
Products use coefficient convolution. With q=x*x+y*y+z*z and b=q^(-1/2),
differentiate `q*b'=-b*q'/2`; for k>=1 this gives

`b_k = sum_(i=1..k) (i/2-k)*q_i*b_(k-i) / (k*q_0)`.

The constant b_0 is the outward reciprocal square root of q_0. Convolution
then supplies b^3, b^5 and b^7 for the exact F1 expression

`a_i = -mu*r_i*b^3 + (3/2)*mu*J2*Rg^2*r_i*(5*z^2*b^7-d_i*b^5)`,
`d=(1,1,3)`.

These algebraic constants are exact; no physical coefficient is chosen here.
Induction through interval operations encloses each coefficient, including for
an interval initial state. Taylor's componentwise Lagrange theorem gives

`y(h) in sum_(k=0..6) c_k(X)*h^k + c_7(B)*h^7 = X_next`.

Each component may have a different remainder evaluation time, which the box
permits. Horner evaluation encloses both terms. Repeating with **X_next**, not a
rounded midpoint or reanchored F2 state, accumulates all preceding local defects
and their nonlinear propagation. Interval evaluation of c_k(X_next) encloses
their amplification/dependency; no assumed scalar Lipschitz multiplier is used.
The recurrence is an inclusion proof by induction from a point initial box.
Wrapping can greatly overestimate width or stop the method; this affects
usefulness, not permission to shrink the bound.

Finally let n be the *actual represented output* of F2 and [l,u] the independent
solution box. Directed subtraction gives each endpoint error interval [l-n,u-n];
its maximum absolute endpoint, then the three-component maximum, gives each
reported norm bound. This includes F2 force/norm/product rounding, RK stage and
sum rounding, its represented 1/6 coefficient, and truncation **without** treating
any of those operations as exact or estimating them through step doubling.
This is distance to an independently enclosed solution, not agreement between
two approximate integrators. A poor nominal endpoint merely gives a large bound.

## Arithmetic contract

Per-query Decimal contexts explicitly set precision, FLOOR/CEILING rounding,
Emin=-200, Emax=200, clamp=0 and traps for invalid operation, division by zero,
overflow, underflow and subnormal results. No operation uses ambient precision
or rounding. Float inputs convert exactly with `Decimal.from_float`; integer
coefficient inputs and Fraction time arithmetic are exact. Addition, subtraction,
products, quotients, coefficient sums, Horner evaluation, domain tests and error
export all round outward. Negation and absolute value use exact copy operations,
because ordinary Decimal unary operators can round. There are no Decimal powers
with a rounded noninteger exponent and no transcendental libm calls in the bound.

Decimal square root is not assumed to obey directed rounding: neighboring
representable numbers bracket its result, and **exact Fraction squared
inequalities** validate that bracket on every call. Failure is unresolved.
The final binary64 upper bound is compared with its exact Decimal value and
advanced with `nextafter(+inf)` if needed; nonfinite output is unresolved.

Assumptions: the runtime implements Python Decimal's specified correctly directed
basic arithmetic, exact conversion, integer/Fraction operations and binary64
conversion/nextafter; execution is free from runtime/hardware corruption. This
working software and its derivation are not a machine-checked formal proof or an
independently certified interval library. Primary arithmetic specification:
Mike Cowlishaw, *General Decimal Arithmetic*, v1.70, arithmetic operation rules
and add/subtract, multiply, divide, next-minus/next-plus, square-root:
<https://speleotrove.com/decimal/daops.html>. Python's corresponding interface:
<https://docs.python.org/3/library/decimal.html> (Decimal.from_float, Context,
rounding modes, copy_abs/copy_negate, traps). These passages were checked for this
task on 2026-09-23. They specify arithmetic, not validation of this repository.

## Verification and usefulness

`tests/test_j2_enclosure.py` uses exact rational sin/cos polynomials of degree
100 and independent Lagrange remainder `abs(angle)^101/101!`, since every real
sin/cos derivative has magnitude <=1. Exact Fraction comparisons require the
**whole reference interval** inside the solution box and nominal +/- reported
bound. There is no unexplained tolerance or 90/110-digit agreement promoted to
a certificate. Synthetic nonzero J2 uses F2's exact mu=8,r=2,Rg=1,J2=11/32,
n=17/16 circle. Zero J2 also uses its exact n=1 circle and the independent radial
parabola mu=4,r0=2,v0=2: r=2*(1+3t/2)^(2/3), v=2/(1+3t/2)^(1/3), evaluated at
exact binary cube-coordinate endpoints. Both time directions are checked.

Metadata, zero span, nonzero anchor, fractional independent grids, ordering,
fresh-process reconstruction, work/domain/arithmetic failure and ambient-context
isolation are tested separately. Rational extrema check primitive rounding and
an exact gradient of the unsimplified F1 potential checks the interval force
extension. Refinement/precision variations require containment, not a monotonic
bound ratio or shrinkage below the arithmetic floor.

The reproducible pilot uses explicitly **assumed synthetic** physical inputs,
never a sourced Earth bundle or flight calibration. For the inclined case:
r=(7000000,100000,200000) m, v=(-100,6000,4500) m/s, mu=4e14 m^3/s^2,
J2=1/1024, Rg=6400000 m, anchor=128 s, radius floor=6000000 m, 50 digits,
12 Picard attempts, 256 steps. Actual initial measurements:

| Span (s) | F2/F3 step (s) | Position infinity bound (m) | Velocity infinity bound (m/s) | Wall (s) |
|---:|---:|---:|---:|---:|
| -60 | 10 | 3.9926025005582806e-5 | 4.72233836730658e-8 | 0.1153 |
| 60 | 10 | 3.9679256041977724e-5 | 4.698222286862252e-8 | 0.1157 |
| 300 | 10 | 1.9298082794801032e-4 | 2.5228852375648325e-7 | 0.5779 |
| 600 | 10 | 3.6919105529499417e-4 | 5.990285321152896e-7 | 1.1291 |
| 600 | 5 | 2.2990218749689134e-5 | 3.736394667562831e-8 | 2.3385 |

The 0.5 s exact-J2 circle (h=1/32) completed 16 steps in 0.3019 s with
1.0505855508349781e-8 m / 1.2126367136061546e-8 m/s bounds. Runtime is a small
host measurement, not a campaign benchmark. These short-arc bounds are small;
there is no established visibility tolerance to which they can be declared
sufficient. The method may wrap badly over longer arcs and has not qualified
the entire 86400 s admission ceiling. No long-horizon optimizer is added.

Reproduce using the existing environment (PowerShell; output paths outside repo):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$task06aTemp = Join-Path $env:TEMP ('task06a-reproduce-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $task06aTemp | Out-Null
.\.venv\Scripts\python.exe -B -m examples.v5_j2_enclosure_pilot > (Join-Path $task06aTemp 'pilot.json')
.\.venv\Scripts\python.exe -B -m pytest -q -ra -p no:cacheprovider --basetemp="$task06aTemp\focused" tests/test_j2_enclosure.py
.\.venv\Scripts\python.exe -B -m pytest -q -ra -p no:cacheprovider --basetemp="$task06aTemp\full"
```

The external evidence archive records actual commands, exit status, source hashes,
pilot output, focused/adjacent/full logs and failed development evidence. Current
validation counts belong in MODEL_STATUS, not in the historical F1/F2 reports.

## Remaining boundary

F4 must approve persistence/content identity for the original state, complete
frame/TT authority, F1 model, nominal solver and F3 numerical policy, and define
deterministic recomputation/rejection. No mutable integrated state or schema
change follows from this additive endpoint owner. Schema 5, B2 1/1 and its fixed
digest, programs 1-7, MS semantics and the accepted 05C study remain unchanged.

Later temporal visibility still needs a J2 search/segment interface, continuous
geometry/error propagation and event handling with explicit work failure. The
internal coarse tubes used to validate Taylor remainders are not exported as
tight visibility enclosures. Family B's interval-view/end-ray obligation remains
open. There is no engine/J2 binding, orbit-driven MS campaign, maneuver, hardware
validation or full-V5 completion. Nothing here alters the accepted 05C results.
