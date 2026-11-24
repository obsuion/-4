# M2-B3: bounded interval illumination of the declared model

Review candidate based on `33380b797fec02b2d2d8186cb509e40cc733b681`, branch
`m1-assembly-20260930-73347d98`. Six additive files; all 396 prior tracked
files, including M2-A/B1/B2 and F1/F2/F3/F4, remain unchanged.

This slice combines continuous J2 state tubes, the declared piecewise-affine
Sun model and whole-cell half-ray/ellipsoid geometry. It supplies conditional
`ILLUMINATED`, `OCCULTED` or `UNRESOLVED` model assessments. It does not supply
adaptive event search, event-time accuracy, physical solar forcing, station or
target visibility, Family B completion, executor/restart integration or an
external simulator benchmark. **Combined Sun qualification remains UNRESOLVED.**

## Authority, frames and API

`orbit_sun_intervals.py` exposes frozen, slotted inputs:

- `IntervalIlluminationRequest(coast, table, start, end, policy)` retains the
  complete `J2CoastOrbitInputs`, `SunPositionTable` with all provenance, original
  TT `GeometryInstant` endpoints, and explicit `IntervalIlluminationPolicy`.
- `IntervalIlluminationPolicy(max_cells)` requires an exact built-in integer
  in [1,5118]. This is a computational budget, not a geometry tolerance.
- `evaluate_interval_illumination(request)` / `IntervalIlluminationResult(request)`
  rebuilds inputs and recomputes evidence. Derived outputs are not constructor
  inputs and are never reconstruction authority.

B2 validates/rebuilds the nested J2 trajectory, gravity/provenance, numerical
policies, concrete frame and original-epoch instants through the accepted
canonical codec. The accepted Sun owner rebuilds the complete table. Two-body
inputs reject explicitly; there is no dispatch fallback. `start < end` is
mandatory. Both model frames must be completely identical, including Earth
shape, rotation metadata and provenance, and TT epochs must match exactly.
No axes transformation or equivalent-date substitution is performed. The
entire closed request must lie within the closed Sun-table domain.

These structural/domain checks and time-only work planning precede numerical
propagation. The Sun domain need not include a J2 prefix outside the requested
interval: B2 still integrates that prefix, but no Sun geometry is claimed there.
No deferred scenario file is used. No context clock, codec registration,
checkpoint schema, accepted point owner or physical executor is modified.

## Continuous coverage and original-anchor propagation

For an admitted request, call accepted `evaluate_j2_segments` once. Preserve
its original anchor, signed legs, accumulated endpoint boxes, exact Fraction
time grid, full continuous Picard tubes and diagnostic counters. Numerical
failure remains upstream failure with its original evidence; no nominal
state or second propagation is substituted. A geometry-budget preflight
rejection calls no propagator. A known B2 horizon/work rejection invokes B2
once to obtain its actual bounded failure evidence, without integration.

Exact time-only planning reuses B2's original-anchor grid definition. Only
after its step count is known to fit the existing limit does planning enumerate
grid boundaries. The common refinement is the sorted union of request endpoints,
J2 coverage boundaries and Sun knots strictly inside the request. A linear
sweep associates each refined cell with one J2 source cell and one adjacent
Sun-node pair; no Cartesian product is formed.

All coverage boundaries remain exact `Fraction` elapsed SI seconds relative
to the original TT epoch. They are never rounded into `GeometryInstant`.
Cells are closed, chronological and gap-free; adjacent cells share endpoints.
At a knot, both affine segments give the same exact represented node, so the
two neighboring closed cells are compatible. This is not an event-time bracket.

Clipping a J2 cell does not shrink its state box. `j2_cell_index` refers into
`result.j2_evidence.cells`, retaining its complete position/velocity tube and
signed `source_initial_seconds`/`source_final_seconds`. The original full tube
is used for every refinement of that source cell. Sun restriction may tighten
the affine Sun range, but repeated clipping does not reduce orbital uncertainty.

## Sun envelope: exact model and B1 rounding

For adjacent table nodes `(t0,s0)` and `(t1,s1)`, the proof's continuous model is

`s(t) = s0 + w(t)*(s1-s0),  w(t)=(t-t0)/(t1-t0)`.

All node times/components are interpreted as their exact represented binary64
values. Weights and affine evaluations are exact Fractions. On any refined
cell `[u,v]` inside this segment, each component is affine, so its exact range
`[L,U]` is the min/max of the exact values at u and v, including constant or
decreasing components. This is a whole-interval extremum argument, not sampling.

B1 point evaluation computes the exact affine component then rounds once to
binary64 (at nodes it returns the stored tuple). Correctly rounded conversion
`RN` is monotone. Therefore, for every real x in `[L,U]`,

`RN(L) <= RN(x) <= RN(U)`.

The exported component envelope is

`[min(L, exact(RN(L))), max(U, exact(RN(U)))]`.

It contains both the entire exact affine path and all admissible rounded B1
provider component values. Conversions back to Fraction are exact. This covers
subnormal/zero rounding without an empirical epsilon or a relative-error formula
that fails near zero. Convex interpolation of finite binary64 nodes cannot exceed
the finite node range; there is no overflowing float extrapolation. The code
relies on the runtime's correctly rounded rational-to-binary64 conversion, also
used by B1, and exact integer/Fraction operations. It does not depend on ambient
Decimal precision or rounding.

`exact_sun_bounds_m`, `provider_sun_bounds_m`, original `sun_segment_index` and
exact `sun_weights` retain the derivation. B1 rejects an all-zero interpolated
position. Nonzero nodes do not establish a nonzero affine path, and the enlarged
rounded envelope can include zero even when the exact path narrowly avoids it.
Such uncertainty must pass the domain tests below or remains UNRESOLVED.

This envelope is strictly numerical. It is not a uniform bound on ephemeris,
physical interpolation, source time or frame-alignment error. The archived
Horizons holdout discrepancy is not used as an error allowance.

## Whole-cell dependent-ray derivation

Earth is the bound axisymmetric ellipsoid. Interpret represented equatorial
radius a and flattening f exactly; form `b=a*(1-f)` exactly, without using the
rounded convenience radius or replacing an oblate shape by a sphere. Let

`Q = diag(1/a^2, 1/a^2, 1/b^2)`.

For every spacecraft position `r` in the B2 position tube and every Sun position
`s` in the envelope, use `d=s-r`. Interval subtraction includes the complete
uncertain spacecraft position in **both** r and d. Neither d=s nor a ray frozen
at nominal r is used. Finite Sun distance supplies direction only: retain
M2-A's half-ray `r + lambda*d`, `lambda >= 0`. There is no finite-Sun endpoint
cutoff, solar disk, penumbra, atmospheric/refraction or light-time model.

Exact rational interval addition, multiplication and true interval squares give

`A=d^T Q d, B=r^T Q d, C=r^T Q r-1, D=A*C-B^2`.

For an interval crossing zero, its square lower bound is zero, not the smaller
squared endpoint. Every scalar operation is exact and all Cartesian component
combinations are enclosed. Treating repeated r/d and time-dependent components
as independent can widen bounds; it cannot invalidate containment. No midpoint
or nominal verdict overrides an interval result.

Before certifying either class, establish all whole-cell domain conditions:

1. `lower(sum(s_i^2)) > 0`: nonzero admissible geocentric Sun vectors throughout
   the full envelope (all components are already finite).
2. `lower(C) > 0`: every spacecraft position is strictly exterior.
3. `lower(A) > 0`: every spacecraft-to-Sun direction is defined and nonzero.

Failure to establish a condition yields UNRESOLVED with its specific reason.
It need not mean every point is invalid; correlation loss may prevent the proof.
An exactly zero Sun path or d is included in this conservative rejection.

The ellipsoid quadratic on the half-ray is

`A*lambda^2 + 2*B*lambda + C`.

Under A>0 and C>0, B>=0 puts its minimum over lambda>=0 at the exterior start.
For B<0 the minimum is `C-B^2/A = D/A`. Thus sufficient whole-box conditions are:

| Conditional model assessment | Whole-cell test after domain checks |
|---|---|
| ILLUMINATED | `lower(B)>=0` **or** `lower(D)>0` |
| OCCULTED | `upper(B)<0` **and** `upper(D)<=0` |
| UNRESOLVED | all remaining cases |

The Earth is closed. A proven D=0 with inward B is contact and counts as
OCCULTED, consistently with M2-A's qualified result. Merely enclosing zero in
D does not prove contact: unless the complete upper bound is nonpositive with
inward B, classification stays UNRESOLVED. Tangency ambiguity is not rounded to
one side. There is no fitted tolerance or event-location claim.

The exported A/B/C/D intervals are dimensionless when d is expressed in metres
and lambda is dimensionless; position/Sun/direction bounds are metres, and the
Sun norm-squared bound is square metres. The complete frame remains in the
request. B2 retains all six state-component bounds and units.

This is an algebraic project derivation using the inherited M2-A ray convention
and B2 continuous containment argument. F3's arithmetic/ODE assumptions remain
those in `V5_J2_ENCLOSURE.md` and `M2_J2_SEGMENTS.md`. No new published physical
constant or scientific approximation was imported. This is not a machine-checked
formal proof or independent validation of the physical model.

## Completion, failure and bounded work

Three meanings remain separate:

- `status='complete'`: a full immutable partition was evaluated. Some or all
  cells may still have assessment UNRESOLVED.
- `all_cells_classified`: true only when a complete partition has no unresolved
  geometry cell. It is not a physical qualification or action grant.
- `combined_qualification='UNRESOLVED'`: always, for synthetic and externally
  sourced tables. Reasons retain unquantified physical ephemeris/interpolation,
  source time, frame alignment and initial-state/gravity-model errors.

`status='unresolved'` is computational failure: `cells=None`, explicit reason,
absent or preserved upstream evidence, and diagnostic work counts. No partial
or empty successful-looking partition is exposed. Even a late geometry failure
after completed cells discards the whole publication. Upstream failure similarly
retains B2's absent cells and original reason. No failure denotes "no eclipse".

At most 4096 B2 cells and at most 1022 internal knots from a 1024-node Sun table
give at most **5118 refined cells**, with at most 5119 boundaries. The user budget
may be smaller. Exact time-only planning rejects insufficient geometry budgets
before propagation. It enumerates at most the admitted 4096 B2 step boundaries;
an unbounded rejected prefix is never enumerated. Sorting the union and a
two-pointer sweep avoid product-sized allocations or repeated propagations.

B2 remains responsible for all original-anchor/prefix/both-leg enclosure work,
Picard limits, arithmetic limits and radius admission. There is no nominal
propagation or nominal sampling in this slice. `propagation_calls` is 0 or 1;
actual B2 step and attempt counts remain in `j2_evidence`.

Geometry uses a fixed version-1 ceiling of 16384 bits for each rational numerator
and denominator, checked on operands and results. Each binary scalar arithmetic
operation therefore creates integer products of at most 32768 bits (addition
may need one more bit) before reduction. Conversions from finite table/frame
binary64 values and bounded F3 Decimal endpoints are already finite-size.
Comparisons also involve only bounded cross-products. A ceiling violation
returns atomic computational UNRESOLVED; no rounding/shrinking or policy
relaxation repairs it.

There is a fixed allowance of 512 counted scalar operations for shape setup
and separately for each cell. The present expression performs six setup
operations and 126 per cell, including affine evaluation and all domain tests.
The total counted-operation ceiling is `512*(1+max_cells)`, at most 2,620,928.
Comparison/gcd costs are not counted as scalar operations but their operand
sizes and the finite expression/sort sizes are bounded. Output allocation is
linear: at most 38 rational field references per geometry cell, plus bounded
time arrays and the single retained B2 result; there is no refinement history
or Cartesian-product state. This supplies finite algorithmic limits, not a
promise of low RAM/wall cost for every extreme admissible input. Requests should
declare a budget appropriate to their use. No long-horizon usefulness is claimed.

## Serialization and offline reproduction

`orbit_sun_intervals_document.py` provides `interval_request_digest`,
`interval_request_to_json/from_json`, `save_interval_request/load_interval_request`.
Format `M2_INTERVAL_ILLUMINATION_REQUEST`, version 1, canonical codec version 1,
domain `m2-interval-illumination-request-v1`. The complete coast, original
instants, geometry policy and Sun table/provenance are bound. Sun serialization
uses the accepted table adapters; no codec allowlist entry is added.

Readers reject wrong types/versions, duplicate/unknown/missing fields,
noncanonical normalization, incompatible authorities and digest mismatches,
including malformed content whose hash was recomputed. Optional expected-digest
checking binds caller intent. Saving is exclusive-create. Loading rebuilds
inputs without propagating; evaluation recomputes evidence offline. Derived
cells, current states and caches are not persisted as authority.

The example's result export is report-only. Exact geometry Fractions use signed
hexadecimal numerator/denominator strings, avoiding Python's decimal-integer
text length ceiling; B2 Decimal bounds retain their complete strings. Every
cell, source reference, bound, reason and counter is compared in fresh replays.

## Executed validation and measured examples

Two source-bound local gates passed: 131 new tests and 479 relevant existing
M2-A/B1/B2, F3, F4-binding and canonical-codec tests; 610 distinct tests total,
zero failures/skips. Exact commands, exit codes and XML/logs are in the external
review archive. No full simulator suite or scientific campaign was run.

Whole-interval references include the exact equatorial J2 circle R=2 m,
n=17/16 s^-1. On [0,1/32] s, analytic cosine/sine inequalities bound the entire
arc. With Sun x=+100 m and |Sun y|<=1 m, all rays point outward; with x=-100 m,
cross-product distance and inwardness inequalities prove all rays meet Earth.
These are synthetic mathematical cases, not spacecraft constants.

An affine Sun path from (-1,16,0) to (-1,-16,0) on the same short arc gives
illuminated endpoints but an occulted interior instant. Exact rational Taylor
sin/cos enclosures and independent cross-product ray-distance inequalities
separate those signs. The full-cell result is UNRESOLVED; endpoint-only logic
would miss the internal geometry change. Whole-cell soundness follows from
the interval derivation above, not from that finite set of witness instants.

Other tests cover exact tangency and adjacent binary64 offsets, oblate shape,
half-ray hits beyond the finite Sun endpoint, varying Sun vectors, knots and
noncoincident grids, both signed time directions and anchor crossings, retained
prefix work, nonrepresentable internal times, d=s-r dependence, zero interpolated
Sun despite nonzero nodes, domain/budget/bit/operation failures, atomic late
failure, forged authorities, hostile Decimal contexts and strict reconstruction.
No test requires nominal RK4 samples to lie in the real-solution tube.

Six bounded examples ran and replayed exactly in fresh local Python processes.
Python network audit access was blocked and the block verified; no ephemeris
was fetched. Evaluation-only wall seconds, excluding process launch:

| Example | Computational status / assessment | J2 steps / geometry cells | First / replay (s) |
|---|---|---|---:|
| changing Sun, outward | complete / ILLUMINATED | 1 / 1 | 0.031315 / 0.031374 |
| changing Sun, inward | complete / OCCULTED | 1 / 1 | 0.032312 / 0.033782 |
| changing Sun, internal transition | complete / UNRESOLVED | 1 / 1 | 0.031796 / 0.031968 |
| two planned cells, geometry budget 1 | unresolved / no cells | no propagation / None | 0.010047 / 0.008984 |
| B2 work budget exceeded | unresolved / no cells | 0 / None | 0.013844 / 0.013269 |
| archived Horizons table, synthetic orbit | complete / OCCULTED | 1 / 1 | 0.034471 / 0.034072 |

Synthetic examples use the accepted F3 assumed circle over 1/32 s (the upstream
failure requests 1/16 s). The external example uses the existing six-hour TT
table with an explicitly synthetic inclined orbit for only ten seconds. It is
a conditional model demonstration, not an observed eclipse or ephemeris test.
All combined qualifications remain UNRESOLVED. Exact replay is evidence for this
runtime only, not a general cross-platform bitwise guarantee or full-day claim.

From the source directory, using the existing environment and a new external
output directory in place of `<OUT>`:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m examples.m2_interval_illumination_demo --kind ambiguous --offline --write-inputs '<OUT>/request.json'
python -B -m examples.m2_interval_illumination_demo --inputs '<OUT>/request.json' --offline
python -B -m pytest -q -ra -p no:cacheprovider --basetemp='<OUT>/pytest' tests/test_orbit_sun_intervals.py tests/test_orbit_sun_intervals_document.py
```

## Remaining boundary

M2-B1 behavior is unchanged. Conditional interval assessments now enclose the
joint mathematical r and s-r dependence, but actual Sun/model alignment and
ephemeris accuracy remain unbounded. Adaptive event/root search, event-time
accuracy, finite solar disk/penumbra, station/target visibility, Family B,
environmental forcing, executor/restart integration, long-horizon qualification
and an external simulator benchmark remain open. This is no hardware-winner,
mission-success, full-M2 or full-V5 completion claim. Stop for independent review.
