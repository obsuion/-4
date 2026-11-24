# M2-B1: offline TT Sun-position table and point-query integration

Pre-implementation contract. Baseline 69a3b73b6c7c49e4f82b45316f0a2f6fd5940f83
on m1-assembly-20260930-73347d98. Deferred scenario files remain untouched.
This implements one finite table provider, not a general ephemeris framework.

## Owners and additive boundary

| Existing owner | Use |
|---|---|
| orbit_config.TTEpoch / GeometryInstant / FrameDefinition | Original split TT epoch; complete model axes, rotation and Earth definitions |
| frames.CartesianPosition / CartesianDirection | SI geocentric position; dimensionless ray in matched axes |
| orbit_binding.CoastOrbitInputs; orbit_j2_binding.J2CoastOrbitInputs | Original immutable trajectory and all numerical policies |
| orbit_sun._result / accepted M2-A ray calculation | Same nominal ray/ellipsoid model and fixed-ray conditional assessment |
| orbit / orbit_j2_enclosure | Existing nominal two-body and accumulated J2 endpoint query |
| context / engine._validate_completed_context | Read-only actual-clock validation; no execution |
| experiment_codec | Existing scalar/record encoding, strict parsing and content digest |

Only M2-A change: extract its existing orbit dispatch into a private
_evaluate_coast_at helper, used by both point adapters. No supplied-ray public
API or result meaning changes. The new path propagates the orbit exactly once.
No codec allowlist, schema 5, physical solver or executor changes.

## Immutable table authority

SunPositionSample stores a finite binary64 elapsed TT time and three geocentric
position components in metres. SunPositionTable stores:
- original TTEpoch, complete MODEL_INERTIAL FrameDefinition;
- explicit closed domain matching first/last sample times;
- 2..1024 samples in strictly increasing order, no sorting/duplicate repair;
- interpolation policy LINEAR_POSITION_V1;
- complete SunTableProvenance.

Source target is Sun (10), center is Earth body center (500@399).
Provenance explicitly records source kind (SYNTHETIC or HORIZONS), axes,
reference plane, geometric convention, TT timescale, original units,
SI conversion, fixed alignment, source IDs, retrieval details, exact request
and response SHA-256, ephemeris ID, accuracy statement and alignment rationale.
All metadata is input content, not authenticated by a string or digest.
External source/retrieval/hash fields are mandatory for HORIZONS.
Synthetic inputs have no fabricated retrieval/hash/source evidence.

Supported coordinate combinations:
- synthetic MODEL_INERTIAL / MODEL_EQUATOR / IDENTITY_MODEL;
- Horizons ICRF / FRAME / ASSUMED_ICRF_MODEL_IDENTITY.
The latter explicitly declares equal coordinate components in model axes.
It is not a verified Earth-orientation or precession/nutation transformation.
The exact model frame binds this assumption, including Earth shape and rotation.
No general rotation matrix or automatic ICRF-to-MODEL_INERTIAL identification.

Only GEOMETRIC vectors, source timescale TT, source units M or KM are admitted.
Conversions are IDENTITY_METRES or EXACT_KM_TIMES_1000 respectively.
Runtime samples are always metres. Source conversion is offline.
No TDB/UTC coercion or time conversion is implemented.
Accuracy policy is UNQUANTIFIED with an explicit explanatory statement.
This slice does not admit or assert a provider uniform error bound.

All new numeric inputs require built-in int/float, excluding bool/subclasses,
with existing exact-integer/binary64 admission and finite checks. Zero Sun
position samples or an interpolated zero position reject. Nonfinite/undefined
spacecraft-to-Sun directions reject. Original definitions remain immutable.

## Interpolation and domain

For t_i < t < t_(i+1),
s(t)=(1-w)*s_i+w*s_(i+1), w=(t-t_i)/(t_(i+1)-t_i).
This is the definition of the piecewise-linear table, not an approximation
chosen at runtime. Fraction arithmetic on represented times/components computes
the affine expression exactly before one final binary64 rounding/component.
At a node return the stored component tuple exactly. The closed last endpoint
is supported. No extrapolation, clamping or silent segment insertion.
Query epoch must equal the original reference epoch, not merely an equivalent
absolute date under another reference origin. No large Julian-date float.

## Integration and three distinct meanings

TableOrbitSunQuery binds the complete table, existing coast and GeometryInstant.
Table frame must equal the orbit's complete MODEL_INERTIAL frame; epochs agree.
The provider is queried before the sole orbit propagation, so domain mismatches
reject without expensive orbit work.

For nominal orbit position r(t), derive spacecraft-to-Sun displacement
s(t)-r(t) in metres; form the dimensionless ray by expressing it per one metre.
Subtract represented components exactly then round once; reject overflow or
the zero direction. Never substitute geocentric s(t) as the spacecraft ray.
Use accepted M2-A normalization, closed ellipsoid and parallel-ray model.

Outputs keep separate:
1. nominal geometry from interpolated s(t) and nominal r(t);
2. conditional M2-A assessment with that represented ray held fixed;
3. combined_qualification, always UNRESOLVED in M2-B1.

The fixed-ray F3 position enclosure does not cover the ray's dependence on the
uncertain spacecraft position. Ephemeris, interpolation, source time conversion
and frame alignment error also lack end-to-end bounds. None becomes zero.
Reasons enumerate these limitations. UNRESOLVED is no physical failure and no
action grant. Solar disk, penumbra, atmosphere and finite light propagation
remain absent; finite s(t) only supplies the ray direction.

On unresolved F3 retain its original evidence, absent state/bounds and reason;
return no spacecraft direction or conditional M2-A result. Do not compute a
fallback nominal state. Original anchors/policies remain intact.
Context helper uses GeometryInstant(original_epoch, simulation_time_seconds):
anchor 128 s and actual clock 127 s still query 127 s. No context/history mutation.
Executor and restart integration remain outside this slice.

## Strict portable inputs

Version-1 M2_SUN_POSITION_TABLE and M2_TABLE_ORBIT_QUERY envelopes adapt new
records to strict primitive maps plus already allowlisted frame/epoch/coast
records. Samples/provenance are fixed-field maps, no codec registration.
Existing canonical version 1 and content_digest domains m2-sun-table-v1 and
m2-table-orbit-query-v1 cover all authoritative content. No results persisted as
authority. Reject unknown/missing fields, types, versions, duplicate keys,
normalization drift, digest tampering and optional expected-digest mismatch.
Exclusive-create save; load performs no network request or fixture regeneration.

## External example / primary-source decision

Primary documentation read before request:
- https://ssd.jpl.nasa.gov/horizons/manual.html — Specification of Time;
  Reference Frames; vector output description.
- https://ssd-api.jpl.nasa.gov/doc/horizons.html — TIME_TYPE, REF_SYSTEM,
  REF_PLANE, OUT_UNITS, VEC_CORR and vector parameters.

The manual permits TT vectors while the API table lists TDB/UT only.
Explicit TIME_TYPE=TT requests succeeded; returned headers say JDTT, TT,
Sun (10), Earth (399), BODY CENTER, ICRF, KM-S, GEOMETRIC, DE441.
No TT=TDB approximation was used. Horizons' internal ephemeris time conversion
is source-owned; its uncertainty is not certified here.

Six-hour 2026-10-01 TT table: seven hourly nodes; six separate midpoint
reference timestamps. KM decimal strings are multiplied by exact integer 1000
before conversion to binary64. Calendar rows validate exact requested TT times;
printed JD labels are reconciled within half their last displayed decimal day.
Model alignment is explicitly assumed, not Earth orientation inferred from TT.

Raw requests/responses, retrieval metadata, hashes and offline conversion script
remain in external review evidence. Only the small portable table is a source
fixture. Source physical-property header values are not adopted as coefficients.
Source API accepted TT; initial sandbox network failure is retained.

## Verification fixed before results

External protocol was recorded before retrieval: [00:00,06:00] TT, hourly nodes,
independent midpoint request, maximum sampled Euclidean discrepancy <=20000 m
and angular discrepancy <=2e-6 rad. No post-result tolerance adjustment.
This is interpolation/reference consistency with the same DE441 source,
not independent ephemeris validation or a rigorous uniform bound.
Compare numerical affine evaluation to 90-digit Decimal: <=1 ulp/component;
exact nodes, identities, times, labels and same-runtime replay compare exactly.

Synthetic moving tables, boundaries, duplicates/nonfinite values, mismatched
metadata, finite-distance direction/sign, original-clock mapping, nominal light/
shadow, conditional versus combined labels, preserved F3 unresolved, strict
decoding, digest changes, nonmutation and network-disabled fresh-process replay.
Run focused new and adjacent tests only; measure bounded point-query costs.
No spacecraft day/month campaign, repeated long F3 scan or full suite.

Open: temporal light/shadow intervals, station/target visibility, J2/Family B,
environmental forcing, executor/restart integration, longer-horizon adequacy,
external simulator benchmark. No M1 mass closure, ADCS/thermal integration,
scenario repair, staging, commit, merge, tag, push, cleanup or process control.
