# M2-B33 — original-anchor continuous zonotope segments

Review candidate, additive opt-in API. Existing `orbit_j2_zonotope.py` remains
69630 bytes, raw SHA256 `8f0d23afce2d9f8ad9b7b9ee6d64a17590497dee4ae8a03fd0ead269263bb37b`,
Git blob `9e441ba3db8e9264b3eecaa99aa28ccc2cdbe221`. No existing registry,
package export, codec, dispatch, F3, kernel or ledger owner is changed.

## Inputs and identities

`J2ZonotopeSegmentRequest(trajectory, end, policy)` takes exact accepted
J2CartesianTrajectory, GeometryInstant and J2ZonotopePolicyV3 types. Its start
is exclusively the original trajectory anchor. Same TT epoch; forward, nonempty
full span only. No start override, supplied box, nominal solver, checkpoint,
backward leg, late prefix, cache or incoming diagnostic. Derived evidence is not
restart authority. The original frame/provenance and policy own every cell.

API `m2-j2-zonotope-segments-v1`, API version1, publication version1; inherited
transport resource version3/kernel `incremental-j2-jet-v1`, PB6 method
`m2-centered-zonotope-pb6-v1` version1. Publication version is a separate owner
contract, not a revision of existing endpoint resource policy. Ceiling<=2**31,
precision40..80, accepted radius/step/rank/scales/Picard constraints and original
86400-second horizon/base max_steps remain admission ceilings, not day qualification.

Structural constant-size type/identity/canonical numeric/time checks may raise
before the ledger. Dynamic frame/model/provenance reconstruction is precharged
through `_reserve_authority_metadata`, then `_coast._authorities`. A data-only
`object.__new__` trajectory binding avoids its public constructor's F1 call.
Standalone callers that construct a public trajectory perform F1 admission
outside this query; fixture tests identify that setup explicitly. Input-document
load/binding and segment evaluation make no setup F1 or nominal F2 calls.
There are no invented nominal/force counters in the segment result.

## Proof and time/frame conventions

One cumulative `_CoefficientArithmeticV3`, initialized once per request. Original
six SI components -> accepted `_initial_set` -> initial domain. Every step passes
the FULL center/generators/births/time to `_transport_step_v3`. No reset to a
point, projected box or nominal state between steps. All coefficient, Jacobian,
PB6, strict Picard, directed rounding and reduction math belongs to unchanged
accepted helpers. `_transport_step_v3` alone makes its all-set projection and
returns the whole SI Picard tube.

For the real accepted F1 equation, an all-set box projection contains the incoming
zonotope. Strict Picard inclusion/domain gives a continuous whole-step tube for
all those incoming states. Accepted Taylor/variational transport plus conservative
reduction encloses the next full set. This induction begins at original data,
including exact binary64 representation, and carries accumulated uncertainty.

Grid: exact Fraction(original anchor)+k*Fraction(base step), then an exact final
remainder. No repeated binary64 time addition, endpoint interpolation or dense
nominal sample proof. Cells retain whole chronological CLOSED source supports,
source index and identical coverage/source boundaries. Adjacent cells share a
boundary; their interiors partition the complete nonempty span without gaps.
Elapsed seconds are relative to the input TT epoch. Position bounds MODEL_INERTIAL
x/y/z in metres; velocity bounds in metres/second, with concrete frame/epoch in
result.request. No frame conversion, Earth orientation or Sun geometry is added.

Published tube pairs are finite exact plain Decimal copies of the accepted
outward interval endpoints, not new rounding. No private `_D` or ledger references.
Final endpoint projection and a plain diagnostic set are derived audit outputs.
Diagnostic center/generator units remain SCALED by policy.scale_exponents as in
accepted v3; endpoint/cell bounds are SI. Neither can be supplied as input authority.
Tube and final projected zonotope are distinct overapproximations of the true
endpoint. One enclosing set need not be a subset of the other; no such subset
assertion is imposed or inferred from nominal samples.

## Publication/resource contract

Primitive/context/rational work charges use accepted helpers. The new owner
precharges every additional validation/copy/allocation/control envelope BEFORE
execution. Operations=charged leaves+reserved control; one rejection latch and
one unchanged max_scalar_operations limit. No schedule upper is debited, no top-up.

The accepted4096-bit conversion guard implies at most1024 admitted Decimal
representation positions. Published proofs are additionally checked with that
same rank guard before plain copies; outputs of the accepted precision contexts
are within it. Composite control units below conservatively cover object/tuple
allocation, type/finite checks and bounded representation/comparison/copy scans.
They are semantic allocation/control bounds, not elapsed time, RSS, or measured
CPU operation counts. Executed guarded leaves are ADDITIONAL, not silently omitted.

| New work | Precharged reservation |
|---|---:|
| Constant structural normalization/exact grid setup | 2048 |
| Initial domain legacy control | 128 |
| Internal bounded pending-list allocation | 64 |
| Whole cell copy/type/support/interval validation | 1024+12*(64+4*1024)=50944 per cell |
| Each internal append | 16 per cell |
| Final projection/diagnostic/control allocation | 2048+90*(64+4*1024)=376448 |
| Complete partition revalidation/tuple publication | (256+12*(32+1024))=12928 per cell |

Twelve endpoints per cell; four bounded representation passes per endpoint;
1024 fixed support/schema/allocation allowance. Final at most12 endpoint bounds
and6+12*6 diagnostic components=90 values. Partition rechecks twelve endpoints
and bounded exact time/source/index/support checks for each cell. Exact Fraction
operations/comparisons use `_fraction/_rmul/_radd/_rcompare`, with before-work
rank guards and leaf debits. `_publish_bounds` explicitly charges shape/type/
ownership/rank/finite/ordering/plain-copy work. Existing `_initial_set`, `_project_box`,
`_plain_set`, metadata and transport reservations are separately charged unchanged.

Thus new composite overhead for N admitted cells is
`2048+128+64+N*(50944+16)+376448+12928*N`, plus the accepted helper charges and
new executed grid/copy/guard leaves. This is ONLY the new-owner overhead, not a
whole-query bound or promise of success. No B30/B32 endpoint bound is reused as
a segment bound: nominal F2 prepayments disappear and publication changes totals
and rejection points. Actual counters, Picard attempts and reductions are reported.

All cells, final projection and diagnostic are published together only after all
transport, per-cell and final partition/publication checks pass. Late failure
publishes NONE of those fields; internal completed steps are diagnostics, not
coverage/checkpoints. Rejected ledger admits no subsequent protected work.
Reason and eight scalar counters are retained as bounded failure bookkeeping,
matching the accepted latch/reporting pattern; they do not revalidate/copy proofs.

## Strict input-only document

Format M2_J2_ZONOTOPE_SEGMENT_REQUEST/version1, digest domain
`m2-j2-zonotope-segment-request-v1`, canonical codec version1. Inputs are original
initial_state/gravity_model/end, decomposed accepted base policy/scales/ceiling,
and fixed API/publication/transport/kernel/method identities. No new codec types.
Canonical primitive/allowlisted existing owners bind every epoch/frame/provenance
value. Safe typed-node gate rejects full trajectories/coast bundles/results before
constructor decoding, including redigested malformed data. No hidden F1 evaluation.
Unknown/missing fields, wrong fixed identities/versions, bool-as-int, subclasses,
nonfinite/noncanonical/normalization drift, digest mismatch and result/cache fields
reject. File saves are exclusive and do not overwrite existing evidence.

## Verification and limits

Tests use exact rational whole-arc sine/cosine reference brackets for the independent
analytic circle, not dense samples/tolerance fitting. The publication copy path
retains exact Decimal tuples under hostile ambient precision/rounding/traps.
Short final diagnostic/projection equality with accepted endpoint v3 verifies
transport compatibility only; equal counters or independent containment are NOT
claimed. Fixtures' initial public trajectory construction is outside the segment
query. Input-only loading/evaluator tests prohibit F1/F2 calls after setup.
Late transport/work/rank/publication failure, cumulative set/ledger identity,
latch/ownership, immutable/forged fields and redigested input attacks are covered.

Four external example documents use short spans<=60s: multi-step/nonzero anchor/
remainder; short endpoint compatibility; budget exhaustion; domain refusal.
Fresh offline processes compare COMPLETE scientific results with exact Decimal
representation/Fractions/identities/cells/diagnostic/counters/status/reason. Timings
and PID are external. Examples are computational demonstrations, no physical
hardware calibration or performance benchmark. No H5/day run is authorized here.

This owner is not an old B2 certificate and does not alter B3/B6 or Sun dispatch.
Illumination, refinement/windows, event search, Family B, executor/restart and
physical/day/event-time qualification remain open. Combined qualification remains
UNRESOLVED; historical B7 cause UNKNOWN. Stop at uncommitted independent review.
