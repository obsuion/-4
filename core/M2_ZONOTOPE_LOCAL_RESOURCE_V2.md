# M2-B38 — explicit local control-ledger resource/API v2

Uncommitted candidate for independent implementation review. No default dispatch,
exports, checkpoint, physical owner or legacy source changes. M2 environment code
feeds later electrical/thermal/action execution; those adapters are not implemented.

## Public owners and opt-in input

`ZonotopeLocalIlluminationPolicyV2`, `ZonotopeLocalIlluminationRequestV2`,
`ZonotopeLocalIlluminationResultV2`, `evaluate_zonotope_local_illumination_v2` in
`ops_sim/v5/orbit_sun_zonotope_local_v2.py`; `_SessionV2` owns the fresh query graph.
Input-only codec `orbit_sun_zonotope_local_v2_document.py` exports digest/to_json/
from_json/save/load functions ending `_v2`. New API ID is
`m2-zonotope-local-illumination-v2`, API/resource/geometry resource version2.
Format `M2_ZONOTOPE_LOCAL_ILLUMINATION_V2_REQUEST`, document2, canonical1,
digest domain `m2-zonotope-local-illumination-request-v2`. Existing decomposed
segment/table fields are unchanged. No old API is switched to this policy.

All ten policy budgets are required: max_initial_steps, max_refinement_steps,
max_trials, max_passes, max_picard_attempts, max_geometry_cells,
max_retained_evidence_units, max_local_control_units,
max_geometry_leaf_operations, max_geometry_control_units. Bool is rejected.
Structural ceilings remain4096/28672/32768 steps,64 local trials,16 local passes,
12 Picard per step,65536 geometry cells,1048576 evidence units.

## Four resource domains

One exact `_CoefficientArithmeticV3`: leaf+legacy numerical reservations<=2**31.
All authority metadata, initial set/project/domain/plain-set, transport/Picard/
coefficients/Jacobian/PB6/reduction and B33 publication operations remain there.
It is never subclassed, proxied or reset. Two independent latched control ledgers:
local<=2**42, geometry control<=2**35. Exact rational geometry leaves<=2**26,
512 per cell including unchanged16384-bit guards; shape setup remains guarded.
No cross-ledger forgiveness. Already charged failures are not refunded.

Only B36-created seed/planning/pass/root/identity/count/support controls move to
local ledger; geometry retention/CLOSED controls move to geometry-control ledger.
SET_SCAN375424, STEP_CONTROL1556736 and CELL_CONTROL50944 remain unchanged.
The CELL proxy inside STEP is a control reserve; actual B33 publication remains
on proof arithmetic. These are operation/control units, not CPU/runtime/RSS.

Normalized sizing uses an iterative exact-type allowlist:32 units before each
visited logical node, maximum262272 nodes, counting allowance2**24, depth64,
text16384, containers4096,16k-bit integers/rationals. No arbitrary type equality,
hashing, descriptors or caller iteration hooks. Compute legacy metadata cost(q)
in that prepaid pass; reserve4*cost(q) before canonical identity/hash/copy work.
Each failed visited prefix is visible in input_nodes_visited/counting counters.
Input normalization/codec have a separate bounded structural prefix; zero proof
counters never imply zero normalization work. The codec admits safe complete
schemas/identities before decode,4Mi characters and original physical tree guards.
Results, trajectories, private sets, tubes, caches/checkpoints are not inputs.

## Admission and cumulative schedules

For pass n steps/g cells, B retained boundaries/M pieces/t trials:
Rlocal=1556736*n+2*375424*(B+1)+2048*(M+g)+8192.
Gcontrol=4096*(4*M+5*g+3); prospective leaves512*(g+1).
Evidence96*n+64*g+8*t+16; root96. Planning and both seed validations
retain the accepted schedules, with seed375424*(id+2) each invocation.
No count or credit resets across passes. Final evidence units are schema slots,
not byte limits. Output counters separate proof leaf/reserved/total, local
reserved units, geometry leaves/control units, caps, rejection flags and input
scan/identity counters. There is no misleading new combined v1 scalar counter.

Static H5 admission and corrected implementation-dependent bounds are delivered
externally with source bindings. Original B35 raw input SHA256
10efd75a15fa24e33f0e9acb197766942b9092b60971e28cbfa611fe81f16d9b
and digest2d68437fab3abe4c20c6a3e21ee15cc716943c3b31efaf87b11317ff540561bb
are immutable; the new document has different identity/digest and unchanged
physical subtrees. N3600/G3605 metadata is not a new scientific H5 execution.
The conditional1448593694 initial proof bound depends on the same frozen
protected call path/grid/full sets plus at most6+78*3600 snapshot copies;
future local Picard/rank/leaves/runtime remain UNKNOWN. Both long gates NOT_RUN.

## Ownership, physical evidence and failures

Retain actual complete query-owned sets, all generators/remainders/births,
original TT anchor, scales/times/parent edges and exact arithmetic ownership.
Both seed validations remain: independent content snapshots, membership,
parent lineage and original-root descent. Identity/digest alone is insufficient.
Never rebuild or accept a diagnostic as a seed. Continuous WHOLE SI tubes,
source/Sun exact union, dependent ray d=s-r, affine Sun/rounding and all kernels
are unchanged. Refine only current unresolved supports with explicit bridges.
Keep outside certificates; validate selected coverage before CLOSED sweeps;
positive/touching incompatible/opposing certificates fail atomically.

Normal prospective refusal returns budget_exhausted, retaining a complete prior
partition if available; initial refusal has no coverage. Any execution/domain/
ledger/lineage/publication failure returns computational_failure, with no accepted
pieces/windows/initial partition. Retained records are diagnostic only. Once a
ledger rejects, no further protected work passes through it. Terminal failure
snapshots use retained counters/plain records and the root/pass retention credits;
constant empty failure is possible when the first root reservation itself refuses.
No graph is copied or validated through failed proof arithmetic during failure.

## Short evidence, compatibility and limits

Tests exercise actual v2 queries, independent schedules/ceilings/prefixes,
full scientific short v1/v2 projection, ownership tampering, bridges, analytic
circle bounds, CLOSED overlays, hostile Decimal contexts and strict input codecs.
Projection retains physical request/shared structural limits, every set/tube/
geometry/parent/support/window field and scientific counters. It excludes only
new local API/record type/policy identities, versioned resource fields and the
policy-containing authority digest, validated independently for each lineage.
All442 accepted files remain byte-identical, preserving legacy byte behavior.

The short CLI requires explicit input/output and policy<=128 total orbital steps,
<=3 local passes and horizon<=30s. Derived JSON is never a checkpoint. Review
package contains frozen short inputs, actual results/replay and source-bound
focused gates. Author/reviewer counts are separate; reused B36 evidence is1391
passed, not a new suite execution. No long horizon, benchmarks or speedup claim.

Combined qualification UNRESOLVED; H5 refinement/day/physical/event-time accuracy
unestablished. Uncertainty width is not event-time accuracy; Family B and other
M2 obligations remain open; historical B7 cause UNKNOWN. Environment output,
target/station adapters and executor/restart integration remain later production
work. No staged files, commit, push, tag or live integration in this candidate.
