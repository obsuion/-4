# M2-A-ORBIT: supplied-Sun point geometry

Contract written before implementation/testing, on accepted M1-C
94c83a18dec22faedc4628da611ea0396ebecd18. The author has replaced the
scenario-layer detour with orbital M2. M2_SCENARIOS.md and scenario_inputs.py
are deferred, untouched, unimported and excluded from this candidate.

## Owners and boundaries

| Authority | Existing path / symbol | Adapter use |
|---|---|---|
| TT and original clock epoch | ops_sim/v5/orbit_config.py: TTEpoch, GeometryInstant | Same explicit epoch; no UTC/UT1/TDB conversion |
| Full frames / Earth shape | orbit_config.py: FrameDefinition, ReferenceEllipsoid | Same a/f, rotation epoch/phase/rate/provenance; kind alone insufficient |
| Vectors and rotation | frames.py: CartesianDirection, transform_direction | Nonzero dimensionless spacecraft-to-Sun vector; transform only compatible opposite kinds |
| Two-body | orbit_binding.py: CoastOrbitInputs; orbit.py: evaluate_two_body_state | Unchanged original trajectory and numerical policy |
| J2/F3/F4 | orbit_j2_binding.py: J2CoastOrbitInputs; orbit_j2_enclosure.py: evaluate_j2_enclosure | Full origin-anchored nominal/interval evidence retained |
| Runtime query boundary | context.py: evaluate_context_coast / evaluate_context_j2_enclosure | New context helper uses their validation/query paths, without advancing time |
| Portable input codec | experiment_codec.py: canonical_content/decode_content/content_digest | Both coast owners, frames and instants are allowlisted; CartesianDirection is NOT |
| Physical execution | existing engine, EPS, thermal, ADCS, restart | No changes or execution grants |

Accepted basis: D303/D304 (V5_DECISION_LOG.md), S008
(V5_SOURCE_REGISTER.md:1128 onwards), V5_J2_ENCLOSURE.md and
V5_J2_BINDING.md. No new published constants or ephemerides are adopted.
The ray equations below are an explicit algebraic derivation, not a sourced
spacecraft model. Existing owners retain their numerical admission limits.

## Immutable inputs and time

OrbitSunQuery contains exactly one CoastOrbitInputs or J2CoastOrbitInputs,
an explicit GeometryInstant and SuppliedSunDirection. Sun input contains an
existing CartesianDirection, origin label SYNTHETIC or EXTERNALLY_SUPPLIED,
source IDs and nonblank rationale. External origin requires at least one
source ID. These labels are provenance declarations, not authenticated accuracy.

Input direction is dimensionless, nonzero, points FROM spacecraft TOWARD Sun.
Its arbitrary positive magnitude is immaterial. Output supplies a robustly
normalized direction for convenience (divide by maximum component, then hypot).
Ray classification uses the original represented components, not rounded unit
components. Opposite sign reverses the physical ray. No implicit finite solar
distance, solar disk, penumbra, atmosphere, refraction or seasonal model.

Sun instant equals the query instant exactly, including original TT epoch.
Frames require equal complete ellipsoid/rotation definitions. Earth-fixed Sun
input may be transformed to MODEL_INERTIAL by the accepted transform. No
kind-only compatibility or absolute-date equivalence with a different epoch.

Context helper maps simulation_time_seconds directly to elapsed seconds at the
ORIGINAL reference epoch. Initial orbit sample at 128 s and clock 100 s means
query at 100 s (span -28), never at 228 s. Neither helper reanchors. Direct point
queries permit the existing signed/fractional GeometryInstant domain; context
queries retain existing integer clock/horizon validation.

Queries are pure. No input/context/history mutation, new checkpoint schema,
cache, controller call or integration into executors. No relaxed policy,
fallback propagator or generated bound replacing missing F3 evidence.

## Nominal ray derivation

Earth is the declared axisymmetric ellipsoid: a>0, b=a(1-f)>0, z polar.
Both accepted frames share its origin and z; a z rotation leaves this quadratic
unchanged. Use exact rational interpretations of represented a and f and derive
b exactly, rather than rounding the derived radius or replacing it by a sphere.

For r in metres, nonzero direction d, and ray r+lambda*d, lambda>=0:
Q=diag(1/a^2,1/a^2,1/b^2),
A=d^T Q d>0, B=r^T Q d, C=r^T Q r-1.
The ellipsoid quadratic along the ray is A*lambda^2+2B*lambda+C.
For C>0: B>=0 implies ILLUMINATED; otherwise minimum is C-B^2/A.
Thus D=A*C-B^2 >0 means ILLUMINATED, D<0 means OCCULTED, D=0 means
TANGENT. Closed-surface convention counts exact tangency as occultation in
the qualified binary result, while nominal output retains TANGENT explicitly.

C<=0 (nominal point on/inside Earth) yields INVALID_POSITION, no usable
illumination permission. It is not a spacecraft failure simulation.
Exact Fraction arithmetic gives signs without a tolerance or cancellation
heuristic for the represented nominal state and direction. Near-boundary
values are not rounded to tangency. Large but valid binary values do not
overflow this quadratic arithmetic.

## Numerical qualification, separately reported

Qualified status is ILLUMINATED, OCCULTED or UNRESOLVED with an explicit reason.
It is conditional on the declared mathematical shape, exact supplied Sun ray
and exact initial/model inputs; it does NOT bound Sun ephemeris uncertainty,
Earth/model error, initial orbit uncertainty or real eclipse timing.

For same MODEL_INERTIAL Sun input and successful J2 F3, use the original
Decimal endpoint position box. Convert endpoints exactly to Fraction and
evaluate interval B, C and D using inclusion arithmetic (including a true
interval square). All positions must be exterior: lower(C)>0. Then:
- lower(B)>=0 or lower(D)>0 proves ILLUMINATED;
- upper(B)<0 and upper(D)<=0 proves OCCULTED;
- otherwise UNRESOLVED (position/boundary enclosure cannot decide).
Dependency widening may cause unresolved; it cannot authorize shrinking bounds.
Velocity intervals/error and original J2 trajectory/policies remain in the result.

F3 unresolved remains unresolved with its original reason, absent bounds and
absent nominal state; do not evaluate a fallback F2/two-body state.
Successful two-body provides nominal geometry, but qualification is UNRESOLVED:
its existing residual target is not a certified complete endpoint bound. No
zero-error substitution, even at its original sample.

A compatible rotated Sun input provides nominal geometry but qualified status
UNRESOLVED: this slice supplies no rigorous trigonometric/frame-transformation
error enclosure. Ordinary successful rotation is not a proof. Same-frame input
avoids this additional arithmetic uncertainty; input-ray accuracy remains an
explicit conditioning assumption, not a flight guarantee.

UNRESOLVED is neither a physical failure nor permission to execute an action.
This is a point result, never a contact/visibility interval or solar forcing.

## Portable reconstruction

New strict version-1 M2_ORBIT_SUN_QUERY envelope adapts custom query/Sun fields
to existing typed-codec primitive maps and allowlisted coast/frame/instant
records. Direction is explicitly frame/instant/components, not an assumed
allowlisted CartesianDirection. No allowlist changes, second numeric codec,
new experiment framework or persisted derived geometry. Canonical version 1.
Identity uses existing content_digest, domain m2-orbit-sun-query-v1, covering
all authoritative orbit/solver/policy/Sun/provenance/query fields. Strict keys,
types, versions, duplicate-key and optional expected-digest checks. Input
definitions are sufficient for independent fresh-process reconstruction.
Saved results are report-only, never read as authority. No checkpoint change.

## Verification fixed before results

Analytic sphere and oblate-axis cases use exact expected ray signs, including
tangent and adjacent binary64 offsets. Independent Decimal quadratic roots
check additional non-axis rays; no production classifier in that reference.
No tolerance for labels, identities, times, persistence or same-runtime repeated
results. Output unit-vector norm tolerance 2e-15 absolute covers division/hypot
rounding; unit output is not used by the proof. Equivalent-frame nominal
directions use 2e-15 per component for short synthetic rotations, consistent
with existing frame tests; transformed queries do not receive qualification.

Short two-body/context clock checks compare directly to unchanged owner output.
Short J2 queries compare complete F3 evidence and preserve forced work-limit
unresolved. Include boundary boxes that cannot prove a side, invalid positions,
epoch/frame/provenance mismatch, strict decoding, nonmutation and fresh processes.
Run focused new and adjacent orbit/frame/codec/binding regression only. Record
bounded example timings; no new day/month calculations or full-suite rerun.

Remaining M2: time-dependent Sun provider/accuracy, interval visibility and
eclipse transitions, J2/Family B adequacy, environmental forcing, executor and
restart integration, external simulator benchmark. No M1 mass closure, ADCS
dynamics or thermal integration. Stop with an unstaged/uncommitted review ZIP.
