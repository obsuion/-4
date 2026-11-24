# M2-B27: invocation-local incremental J2 coefficients

This is a private coefficient kernel, not an endpoint method, orbit adapter, checkpoint owner or public v3 API. Existing v1/v2 definitions, policies, results, dispatch, rounding and accounting are unchanged. The original module remains a byte-identical prefix; all new definitions are appended.

## Identity and admission

`_CoefficientArithmeticV3(precision, max_scalar_operations=2**31)` has kernel identity `incremental-j2-jet-v1` and resource policy3. Its closed bootstrap never calls either older ledger constructor and never injects a larger ceiling afterward. Precision is exact int40..80; capacity exact int1..2**31. Per-query native Decimal contexts use ROUND_FLOOR/ROUND_CEILING/ROUND_HALF_EVEN, Emin=-200,Emax=200,clamp=0,capitals=1, with exactly InvalidOperation,DivisionByZero,Overflow,Underflow,Subnormal trapped.

`_coefficients_incremental_v1(box, order, model, ar)` admits:
- An exact new ledger, fixed identity, compatible native contexts/owners and balanced nonnegative exact integer counters. A rejected ledger stays rejected.
- Exact int order6 or7; exact tuple of six exact `_I` records. Both endpoints must be exact `_D` objects owned by that ledger, finite and ordered. No plain Decimal, foreign query, subclass or coercible authority.
- The existing exact `J2GravityModel` with normalized scalar/provenance authority. Its three metadata graphs are prepaid with unchanged `_reserve_parameter_metadata` before reconstruction. Raw values and optional exact SensitivityRange bounds must already be exact finite floats, preventing caller numerical hooks. Reconstruction calls only J2GravityModel, never a trajectory/F1 evaluator. Exact float.hex representations, canonical zeros and safe normalized metadata must survive the roundtrip.

The finite endpoint guard is precharged; the endpoint-order comparison charges through `_D`. Numeric authority guards/hex conversions/comparisons are precharged. Fixed structural/type/bootstrap validation is separate from propagation arithmetic; finite ledger/context/box control is reserved before accessing numerical authority.

Malformed structure/identity raises TypeError/ValueError. Exhaustion, division/radius/rational guards raise `_Unresolved`. Decimal trap/overflow failures are converted to explicit `_Unresolved` with their cause. No partial series is returned. Python exception tracebacks can retain local diagnostic frames; they are not a published result or continuation authority.

## Mathematical recurrence and prefix proof

For time Taylor coefficients, let q=x²+y²+z² and b=q^(-1/2). Since q*b'=-b*q'/2, coefficient t^(m-1) gives:

    m*q[0]*b[m] + sum_(i=1..m-1) (m-i)*q[i]*b[m-i]
      = -sum_(i=1..m) (i/2)*q[i]*b[m-i]
    b[m] = sum_(i=1..m) (i/2-m)*q[i]*b[m-i] / (m*q[0])

Initial b[0]=1/sqrt(q[0]) uses the existing validated sqrt. Its nearest-rounded root is bracketed by outward neighbors and checked by exact rational squared comparisons; it is not assumed to be a directed sqrt.

For N=6/7, stage m=0..N-1 begins with six state prefixes0..m complete. It extends, in dependency order:
1. Three square jets and q.
2. b,b2,b3.
3. Three central acceleration jets.
4. If J2 is nonzero, b5,b7,z2b7, three correction-term/product jets and corrected accelerations.
5. Six state coefficients m+1, using rhs[m]/(m+1).

Each product coefficient is the old `ar.total(ar.mul(left[j],right[m-j]) for j in range(m+1))`: same operand order, zero start, left-to-right summation and explicit contexts. At degree0 each position-square convolution executes its discarded product AND zero-start addition first; only then does the original interval-square override execute once. This patch does not implement the separate discarded-work proposal.

Mu and the J2 factor are evaluated once at their original first-degree locations, with original represented constants/nesting. i/2-m is a bounded exactly representable half-integer; its fixed Python scalar control is included in the schedule. No float replaces an interval.

Induction for successful equality: every degree-m operand depends only on state coefficients<=m and already established lower dependent coefficients. Identical incoming intervals/constants, operations per coefficient, product order and directed contexts give identical degree-m interval endpoints/representations. The state append then agrees at m+1. Fixed context flags/traps are essential; sticky flags do not alter successful operations. Therefore all six successful prefixes agree with the fresh legacy graph; removed recomputation intentionally changes work and exhaustion prefixes under this new identity.

Independent enclosure inclusion follows separately from outward interval operations and the valid recurrence on q[0]>0. Compatibility with legacy is not an independent proof. The kernel does not establish a whole temporal tube: a future adapter would still require the unchanged incoming-set/tube/domain proof.

All caches are local variables of one call. Center-order6 and tube-order7 have different input boxes and may never share caches. No globals, model-ID memoization, cross-step/query graph, nominal/F2 reset or removal of inherited uncertainty is introduced. Six complete lists of lengthN+1 are returned only after every append succeeds. Position coefficient units are m/s^k; velocity coefficients are (m/s)/s^k.

## New work and allocation schedule

Actual guarded primitives are inherited without alteration: conversion/context/finite-wrap/comparison/rational operations are charged before protected work. Rational conversion/intermediates keep the4096-bit cap. The exhaustion latch and operations=leaf_operations+reserved_units remain invariant. Counters are abstract work units, not seconds, instruction cycles or measured speed.

Let T=N(N+1)/2 and H=N(N-1)/2. A product jet is extended N times, using T ordered products/additions instead of repeatedly building lower outputs. K=8 for zeroJ2,14 otherwise. The square degree-zero discarded operations remain included.

For the new graph:
- K*T ordered convolution products; H reciprocal-recurrence terms.
- SevenN interval divisions: N reciprocal-root/recurrence divisions plus sixN state appends.
- One validated sqrt; three initial position-square overrides plus one gravity-radius square for nonzeroJ2.
- Direct interval multiplications: K*T+2H+(N-1)+3N, plus9N+3 for nonzeroJ2. Each interval division additionally invokes one interval multiply.
- Total calls: (K+2)N-1. These are structural calls, not measured CPU.

The retained interval-reference bound is six(N+1) state slots plus22N intermediate slots:
three squares; q/b/b2/b3/b5/b7/z2b7; four three-axis families(central,terms,corrections,accelerations). Maximum is202 atN7. Shared immutable intervals are references, not duplicated physical allocation. Optional zeroJ2 jets can be absent.

Sixty-four scratch interval-reference slots conservatively cover two fixed constants, six rhs references, current product/recurrence/q/append temporaries, endpoint pairs and the nonrecursive primitive's bounded temporary endpoints. ar.mul has eight candidate guarded endpoints; sqrt has bounded rational/context scratch already constrained by the primitive/rank contract. This is a bound on numeric workspace, not total Python object bytes/RSS or exception-traceback lifetime.

Upfront reservations, distinct from actual leaf work:
-512 fixed admission/control units.
-8*(28N+70) workspace/control units for retained28N+6 plus64scratch.
-1024*T degree schedule units.
-Existing three-parameter metadata reservations, including dynamic text/source-ID collision schedules, are additional.

Schedule derivation uses high-level kernel control-site units, not CPython bytecodes. One site unit covers an iterator/index/bounded scalar constant/reference/branch/call-setup event; two jet reads plus one index subtraction per product and two reads plus half-constant division/subtraction per recurrence are included in their 16/24 envelopes. Guarded primitive internals remain in their unchanged leaf contract. A call to an already guarded primitive retains its own unchanged accounting; the table pays the new caller/helper schedule, indices, fixed scalar constant arithmetic, branch/control and allocation/reference operations.

| Degree-m block | Conservative control units |
|---|---:|
| <=14 convolution coefficients: <=16 units per term plus16 setup/finish |14*(16*(m+1)+16)|
| Reciprocal recurrence, including bounded i/2-m arithmetic, indices and setup |24m+32|
| Square/q/b graph orchestration, constants/branch/correction scheduling |256|
| Six state appends, <=16 each |96|
| Sum |248m+832|

248m+832 <=1024(m+1) for all m>=0; summing gives1024*T. Eight workspace units per bounded slot cover allocation/reference bookkeeping separately. These estimates deliberately overbound branches; no repeated removed arithmetic is reported as an executed leaf. Reservations are finite schedules, not an operation trace. Their unit is abstract bounded work, not a universal CPU-cost ratio.

Numerical leaves and work-budget failure prefixes intentionally differ from old _coefficients. Neither rejected ledger top-up nor ceiling increase is performed. A call may use a compatible ledger already containing honest prior work, but always allocates a new graph. Cache state is not retained in the ledger or returned as a checkpoint.

## Verification contract and references

The bounded matrix is recorded outside the worktree before execution. It covers exact Decimal tuple equality for every prefix, orders6/7, point/nonpoint boxes, zero/positive/negativeJ2, precision40/50/80, hostile ambient contexts, strict admission/normalized authority, context/rank/trap guards, primitive precharge/latch, exact structural call counts, discarded degree-zero first evaluation, late atomic failure and graph isolation/release.

Independent references:
- ZeroJ2 circle with mu8,r2,w1 and v2: x=2cos(t),y=2sin(t); exact rational coefficients through degree7 and their velocity derivatives. It establishes these analytic point cases, not universal input containment.
- Differentiate Phi=-mu*q^-1/2+(mu*J2*Rg²/2)*(3z²*q^-5/2-q^-3/2) with an exact rational value/gradient/Hessian jet at perfect-square radii. Force=-gradPhi and jerk=-HessPhi*v independently check selected position/velocity derivatives for signedJ2. The oracle does not differentiate rounded production code.
- Existing zonotope/enclosure/seed regressions retain original analytic set proofs, directed arithmetic charges, strict context boundaries, atomic errors and v1/v2 result/counter behavior. No tolerance replaces exact-success equality.

No new publicC5, B20/H5/day run, simulator campaign, benchmark or external solver is authorized by this kernel gate.

## Technique background

Masahide Kashiwagi, “ベキ級数演算について” (Power Series Arithmetic), version2023/7/2, section9, printed pp23–24/PDF pages23–24. [Author documentation, section9](https://verifiedby.me/kv/psa/psa.pdf#page=24); [author repository](https://github.com/mskashi/kv).

The author describes preserving intermediate power-series values and extending only newly needed coefficients, with care when function expansion changes expression structure. Here the expression graph is a fixed bounded J2 graph, with invocation-owned intervals and a separate guarded ledger. This is technique background, not proof of this implementation. No third-party code was copied/imported, no dependency installed.

## Limits

Private kernel only; no public v3 result, endpoint adapter, dispatch replacement, persistence or illumination qualification. Original-anchor accumulated uncertainty remains the existing owners' responsibility. Speedup UNPROVEN; combined qualification UNRESOLVED; H5 unestablished; historical B7 cause UNKNOWN. Stop for independent review.
