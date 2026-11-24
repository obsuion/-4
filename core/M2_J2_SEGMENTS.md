# M2-B2: bounded continuous J2 segment enclosures

Review candidate based on `acecaf95e0041fcdfedc0f5d2daf7613e1eb900d`.
This foundation exports continuous state containment over one requested time
interval. It does not classify illumination, search events, compute station or
target visibility, complete Family B, supply environmental forcing, or integrate
executors/checkpoints. M2-B1 **combined qualification remains UNRESOLVED**.

## Authority and API

`ops_sim/v5/orbit_j2_segments.py` provides:

- `J2SegmentRequest(coast, start, end)`: frozen complete `J2CoastOrbitInputs`
  and two `GeometryInstant` authorities, with strictly `start < end`.
- `evaluate_j2_segments(request)` / `J2SegmentResult(request)`: recomputed
  evidence, `status='enclosed'` or `status='unresolved'`, with useful `reason`.
- `J2SegmentCell`: immutable derived closed coverage and original source-step
  provenance, with Decimal position/velocity component bounds.

All constructors require exact owner types. The accepted canonical codec
reconstructs the complete nested input graph, rejecting forged values,
unsupported versions, hostile types and constructor-normalization drift. Both
request instants must use the original TT reference epoch; a different epoch
representing an equivalent absolute date is rejected. The original state,
anchor, concrete MODEL_INERTIAL frame, gravity provenance, F2 nominal solver,
F3 policy, and F4 version fields remain input authority. No default Earth or
orbit is introduced. Request/result replacement rebuilds or recomputes evidence.

This bounds the real solution of `r'=v, v'=a_F1(r)` for the exact real-number
interpretation of the represented binary64 initial state and gravity parameters.
F1's static symmetry axis remains MODEL_INERTIAL +z. It does not bound uncertain
hardware truth, gravity-model error, Earth-orientation error or Sun-table error.

## Exact time, original anchor and closed coverage

Let `a` be original elapsed anchor seconds, `[s,e]` the request, and `h>0` the
F3 enclosure step. Convert represented inputs directly to `Fraction`, without
float subtraction. There is one negative leg to `s` if `s<a`, and one positive
leg to `e` if `e>a`. A request entirely on one side uses only that side's leg.
Every leg starts from the same original initial point authority.

For leg span `d`, `full,tail = divmod(abs(d),h)` exactly. Integrate `full` signed
steps of length `h` followed by the exact signed remainder if nonzero, as in
F3's enclosure grid. The far boundary terminates that leg; no outward extension
beyond it is made. A near request boundary inside a step clips the *coverage*
of that step, leaving its actual whole-step tube intact. Prefix steps before
the requested interval still propagate their full accumulated endpoint boxes.
The near boundary never becomes an integration origin.

Each cell carries:

| Field | Representation and meaning |
|---|---|
| `start_seconds`, `end_seconds` | exact `Fraction`, chronological closed coverage, SI seconds relative to the original TT epoch |
| `source_initial_seconds`, `source_final_seconds` | exact `Fraction`, original integration step endpoints in integration order; descending for negative steps |
| `position_bounds_m` | three immutable `(Decimal lower, Decimal upper)` pairs for MODEL_INERTIAL x,y,z, metres |
| `velocity_bounds_m_per_s` | the corresponding three velocity bounds, metres/second |

The concrete frame and reference epoch reside in the complete result request.
Internal time boundaries are deliberately not converted to `GeometryInstant`:
even adding represented 0.01 s to a nonzero anchor may not be representable in
binary64. Exact rational boundaries retain that information with no cumulative
drift. To form the signed arithmetic step, directed Decimal division encloses
its exact numerator/denominator; the declared time partition itself remains exact.

Successful cells are chronologically ordered and nonempty. Their union is the
entire `[s,e]` and consecutive cells share exactly one closed boundary. Both
cells own that boundary; these are state enclosures, not disjoint delivery
intervals or event brackets. At a crossed anchor, the two signed legs share
the original initial instant. There is no claim of event-time resolution.

Example: anchor 32.125 s, `h=1/32` s, offsets `[3/64,9/64]` need five steps
from the anchor and return four cells. The first entire prefix step is not
returned; the second step is clipped to start at offset `3/64`. The final
step is the remainder `[4/32,9/64]`. Offsets `[-9/64,7/64]` need five negative
and four positive steps, counted together as nine.

## Mathematical coverage argument

This is the existing F3 box-Taylor/Picard argument, applied to exported tubes.
It is a project derivation under F3's stated arithmetic assumptions; no new
physical law, interval integrator or externally certified proof is introduced.

For accumulated start box `X`, exact signed duration `dt`, and the directed
Decimal interval `h` containing `dt`, define
`H=[min(0,h.lower),max(0,h.upper)]`. F3 searches for a finite box `B` satisfying

`X + H * F(B) subset interior(B)`.

`F(B)` is the outward inclusion extension of the declared F1 field. The radius
test proves that the entire box stays at least `min_radius_m` from the origin.
Consequently the autonomous field is smooth on a neighborhood of `B`.

The integral equation implies continuous containment by the first-exit
argument. The solution starts in the interior; if it first reached the boundary
while elapsed time lies between zero and `dt`, its integral still lies in the
strictly interior Picard image. This is a contradiction. Smoothness, boundedness
and the compact tube give uniqueness and continuation through the step. For
negative `dt`, integration of the same integral equation has a negative signed
time multiplier, already included by `H`; equivalently apply the argument to
the reversed-time field `-F`. A contraction estimate is not required for this
first-exit containment argument.

F3 then evaluates the unchanged sixth-order Taylor polynomial about `X`, with
the seventh-order Lagrange remainder evaluated on `B`:

`X_next = sum(k=0..6, c_k(X)*dt^k) + c_7(B)*dt^7`.

Outward coefficient/Horner arithmetic encloses every operation. The complete
`X_next` is the next step's input, including all accumulated uncertainty. By
induction, each exported actual Picard tube contains the real trajectory on its
entire source step. Restricting its claimed coverage to a clipped subinterval
is conservative without narrowing the state bounds. Endpoint hulls, samples,
nominal RK4 interpolation and agreement between numerical runs play no role.

The only F3 refactor is `_step_with_tube`: the existing arithmetic and domain
checks return the already computed tube alongside the endpoint and attempts.
The existing `_step` wrapper discards the tube and returns its original pair.
No arithmetic expression, order, policy, nominal call or counter is changed.
Twelve source-bound pre/post cases compare complete existing F3 results,
including nominal state, Decimal endpoints, bounds, authorities and counters.

The inherited arithmetic assumptions and field/Taylor derivation are documented
in `V5_J2_ENCLOSURE.md`, sections "Derivation implemented by this candidate" and
"Arithmetic contract". In particular: 40..80-digit per-query FLOOR/CEILING
contexts, exponent range [-200,200], explicit exception traps; exact represented
float conversion; square-root neighbor brackets checked by exact rational
squaring; exact negation/absolute value; no ambient Decimal-context dependence.
Its primary references to Neher/Jackson/Nedialkov section 4 and the General
Decimal Arithmetic specification remain inherited references, not new source
verification or an independent certification in this task. This implementation
is not a machine-checked formal proof. Coarse or wrapping-dominated valid tubes
are acceptable and are not advertised as tight.

## Budgets and failures

The request retains the accepted `J2EnclosurePolicy` without relaxation:

- `step_seconds` in [2^-20,1024] s; `max_steps` in [1,4096].
- `min_radius_m` in [1e-6,1e12] m; precision in [40,80] digits.
- At most 1..16 Picard attempts per step, as configured.
- Each original-anchor leg span is at most 86400 s. A crossed interval may
  extend to both sides, but the *same total* step budget covers both legs.
- Nonzero original r, v, mu, J2, gravity radius and retained F2 step magnitudes
  must lie in [1e-100,1e100], the existing F3 arithmetic envelope.

Before any integration or cell collection allocation, exact integer arithmetic
computes `planned_steps = sum(ceil(abs(d)/h))` over the at most two legs.
All prefixes count. It must not exceed the single `max_steps` value. Memory is
bounded by at most 4096 cells, each with six Decimal pairs and four rational
times, plus constant-size order-six/seven working arrays and the input graph.
At most `max_steps * max_picard_iterations <= 65536` Picard attempts can run.
The sort/tuple publication uses bounded additional references to those cells.
Limits are computational ceilings, not demonstrated useful horizons.

No nominal diagnostics are included. F2 solver authority is retained and
validated but F2's nominal grid, representable remainder and nominal work
admission are **not executed**: those govern a separate nominal query. No RK4
steps are performed (`nominal_steps=0`). An enclosed segment therefore does not
promise that an F3 endpoint-plus-nominal query at its boundary will succeed.
No change to that existing F3 API or its admission follows.

Malformed authorities raise errors before evaluation. Valid requests that fail
work/horizon admission, radius proof, Picard inclusion, Decimal arithmetic or
Taylor propagation return `status='unresolved'`, an explicit reason and
`cells=None`. They never return a successful-looking empty or partial tuple.
`planned_steps`, completed `enclosure_steps` and all attempted `picard_attempts`
are diagnostics only; a failed step is not counted as completed. Even a later
failure after valid tubes, including on the second crossing leg, discards all
coverage. Success is published only after both legs and the covering partition
pass. UNRESOLVED has no interpretation as "no eclipse" or "not visible".

## Input-only reproduction

`orbit_j2_segments_document.py` exposes `segment_request_digest`,
`segment_request_to_json/from_json`, `save_segment_request/load_segment_request`.
The version-1 envelope format is `M2_J2_SEGMENT_REQUEST`; digest domain is
`m2-j2-segment-request-v1`; existing canonical codec version 1 is unchanged.
Only the complete coast and requested start/end are encoded using already
allowlisted owners. Request/result/cell classes are not added to the allowlist.

Readers reject duplicate/unknown/missing fields, wrong types/versions, invalid
nested authorities, incompatible epochs, normalization drift and digest
mismatches, including redigested malformed graphs. Optional expected-digest
checking binds caller intent. JSON layout whitespace is irrelevant; canonical
typed content is mandatory. Saving uses exclusive creation. Loading reconstructs
inputs; callers explicitly recompute evidence. No tube/current state/cache is
persisted as authority; no network or fixture download is needed.

## Verification and measured examples

The new tests check complete analytic central and equatorial J2 circular arcs
using exact rational sine/cosine Taylor bounds plus monotonicity, in both
directions and across nonzero anchors. Synthetic `mu=8, r=2, Rg=1, J2=11/32`
gives exact angular rate `17/16`; central rate is 1. These are hand-solvable
model references, not Earth data. Whole-reference-interval containment is
compared exactly with `Fraction(Decimal)`; there is no fitted numerical tolerance.

A separate exact central circle has r=(3,4,0) m, v=(-4,3,0) m/s and mu=125
m^3/s^2. On `[5/8,21/32]` s, `x=3 cos(t)-4 sin(t)` changes sign once while
`y=3 sin(t)+4 cos(t)>0`. Since `x'=-y` and `x^2+y^2=25`, y attains 5 strictly
inside that one cell and vx attains -5. Rational endpoint bounds prove both
endpoint y upper bounds are below 5. Endpoint-only hulls miss the extremum;
the exported tube contains the analytic whole-interval ranges. This reasoning
does not depend on a finite sample grid.

Other checks cover exact time partitions and total budgets, accumulated prefix
boxes, signed source provenance, forged authorities, hostile Decimal contexts,
real and injected late failures, request order, strict input-only serialization
and fresh-process offline reconstruction. Existing F1/F2/F3/F4, M2-A and M2-B1
regressions accompany the new tests; logs and exact commands belong to the
external review package. No full simulator suite or scientific campaign is run.

`examples/m2_j2_segments_demo.py` reuses the explicit synthetic inclined F3
inputs with anchor 128 s, enclosure step 10 s and total budget 32. Measurements
on the task's local runtime (seconds, evaluation only, excluding process launch):

| Example: offsets from anchor (s) | Status | Planned/completed steps | Cells | Picard attempts | First / fresh replay wall (s) |
|---|---|---:|---:|---:|---:|
| forward [15,65] | enclosed | 7 / 7 | 6 | 20 | 0.150068 / 0.140427 |
| backward [-65,-15] | enclosed | 7 / 7 | 6 | 20 | 0.142469 / 0.141152 |
| crossing [-25,35] | enclosed | 7 / 7 | 7 | 20 | 0.143119 / 0.146562 |
| same crossing, total budget 1 | unresolved | 7 / 0 | None | 0 | 0.004182 / 0.004000 |

All four complete results (every Decimal endpoint, exact rational boundary and
counter) replayed identically in separate local processes from serialized inputs.
Python socket/urllib audit access was blocked and the block was checked. This is
same-runtime deterministic reconstruction, not general cross-runtime identity.
These short examples do not establish full-day usefulness or performance.

Example commands, from the source root with the existing environment and a new
external directory substituted for `<OUT>`:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m examples.m2_j2_segments_demo --kind forward --offline --write-inputs '<OUT>/forward.json'
python -B -m examples.m2_j2_segments_demo --inputs '<OUT>/forward.json' --offline
python -B -m pytest -q -ra -p no:cacheprovider --basetemp='<OUT>/pytest-new' tests/test_j2_segments.py tests/test_j2_segments_document.py
```

The review archive includes source-bound gate logs, exact Python path/environment,
all four documents/results, reproduction scripts and development-failure history.

## Remaining work

Interval illumination still needs qualified time-dependent Sun bounds and
direction error propagation, Earth/ray geometry on whole state tubes, interval
classification with explicit uncertainty and bounded event search. Family B,
J2 temporal station/target visibility, environmental forcing, executor/restart
integration, long-horizon usefulness and independent simulator benchmarks remain
open. This candidate does not reuse two-body visibility allowances as J2 bounds.
F1, F2, F4 binding, codec registration, checkpoint schema and accepted Sun owners
remain unchanged. Neither M2 nor full V5 is complete.
