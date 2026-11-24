# M2-B6: proof-preserving local illumination refinement

This bounded contract adds a fresh evaluation-local refinement owner on accepted
B4. The composition contract fixed before implementation is preserved in the
external review evidence. F3 mathematics and the B4 global baseline are unchanged.
Only B2 initial-box/validated-step and B3 geometry-cell kernels are shared by
minimal private refactors preserving expression order and old counters.

## Original authority and reconstruction

The public input is `LocalIlluminationRequest(coast, table, start, end,
requested_resolution_seconds, policy)`. The coast retains the original Cartesian
initial state, original epoch/anchor, gravity model, nominal solver and fixed F3
precision/radius/Picard parameters. The accepted Sun table retains its complete
frame, epochs, domain, sample positions and provenance. Refinement changes only
the validated enclosure step by exact halving; it does not change physical inputs
or substitute the nominal RK4 state for a validated box.

The strict input-only format is `M2_LOCAL_ILLUMINATION_REQUEST`, version 1,
canonical version 1, digest domain `m2-local-illumination-request-v1`. It binds
every original authority, the requested connected uncertainty width and all six
local numerical ceilings. The reader rejects unknown or missing envelope/input/
policy fields, malformed canonical values, normalization drift, invalid values
even when the sender recomputes the digest, and injected seed/certificate/cache
fields. An expected digest is independently checked. Existing canonical record
registration is unchanged. Exclusive-create save cannot overwrite an input.

Loading reconstructs inputs only. The offline example subsequently calls a fresh
`evaluate_local_illumination` evaluation and serializes its recomputed proof
records. It never imports a serialized result or trusts a sender-supplied seed.
The `--offline` flag disables Python networking before load and evaluation.

## Full-box composition and ancestry

The root boundary contains all six original represented position/velocity
components. For each signed step, the unchanged accepted F3 validated kernel
operates on the whole parent containing box and returns both its endpoint box and
continuous tube in that same call. Thus, inductively, the endpoint box contains
the same original-anchor real solution at the endpoint, and the tube contains
that solution over the closed signed source interval. Prefix steps are part of
this induction and of work accounting. There is no midpoint replacement, nominal
state seed, accumulated-error reset or second propagation just to recover boxes.

Positive local work starts at an anchorward left/source-initial boundary;
negative work starts at an anchorward right/source-initial boundary. Connected
unresolved spans crossing the original anchor become two directed tasks. If a
desired local edge lies inside a supporting step, bounded signed prefix steps
derive a genuine endpoint at that exact edge; the edge is not inferred from a
coarse tube. Nonaligned Sun knots split geometry coverage using the accepted Sun
envelope, without inventing an orbital endpoint.

Every retained boundary links to its parent validated step; every step links to
its parent and endpoint boundaries; every geometry record links to its supporting
step. Finite integer IDs are evaluation-local. Reuse checks the registered object
identity and an immutable signature of complete record values and ancestry.
Signatures snapshot primitive values recursively: floats by exact hexadecimal
binary64 representation, Decimals by their immutable representation tuples,
Fractions by numerator and denominator, and dataclasses/tuples by their complete
children. Keeping the original nested dataclass itself would not establish a
historical snapshot. A matching authority digest alone is not proof authority.

## Coverage composition and publication

Refinement selects every connected UNRESOLVED span, including connections across
different unresolved-reason labels. Certified old spans retain their original
support records. New geometry uses the accepted shape, Sun-envelope and ray
kernels. Refining time labels on a coarse tube alone is not an improvement in
orbital evidence.

New and old boxes need not be nested. Both derive from the same original
authority and contain the same solution on each closed overlap. Compatible
position, velocity and Sun intersections are checked, as are opposing certified
labels at closed shared endpoints. A contradiction or unsupported partition
causes atomic computational failure. Reporting windows are half-open, with the
final reporting endpoint included; this convention does not weaken closed proof
supports.

Budget, pass-count or exact-halving/floor stopping may publish only the last
complete supported partition. An integration, geometry, domain or integrity
failure exposes no usable windows, even if an earlier pass completed. Partial
ledger/pass history then remains diagnostic evidence, distinct from scientific
coverage.

The resolution metric is the largest connected unresolved duration. It is not a
maximum individual cell width, event existence test, event-time error bound,
physical orbit accuracy, or executor permission. Continuous-tube component widths
and endpoint-box component widths describe different numerical enclosures and
must be identified separately. Neither quantity establishes flight accuracy.
`combined_qualification` remains `UNRESOLVED` for every result.

## Quotas and accounting units

All six local ceilings require positive exact built-in integers:

| Ceiling | Maximum |
|---|---:|
| passes, including the initial pass | 16 |
| integration steps | 65,536 |
| Picard attempts | 1,048,576 |
| geometry cells | 65,536 |
| retained evidence units | 393,216 |
| B3 rational arithmetic operations | 33,562,624 |

Accepted per-pass F3/B3 bounds additionally constrain each plan. For a plan with
`n` integration steps and `g` geometry cells, reserve all work before executing
the pass: `n` steps, `n * fixed max_picard_iterations` Picard attempts, `g` geometry
cells, `512 * (g + 1)` B3 rational operations, and `12*n + 24*g + 16` retained
evidence units. Count seed-derivation and original-prefix work in `n`; charge
failed attempts and do not refund reservations. Rejected considered plans have
diagnostic planning counts but no executed work or admitted reservation.

Retained units are explicit conservative fixed-schema record/reference units,
not bytes or a measured memory bound. The current published ledger metric is
`4*boundaries + 4*steps + 2*geometry_records + 4*coverage_pieces + windows +
window_supports`. Reservation also provides slack for signatures, ancestry and
temporary planning/coverage structures. Exact-time Fraction components are
bounded by the existing 2,048-bit limit; B3's accepted rational ceiling remains
16,384 bits, and F3 precision admission remains unchanged. Input/table sizes and
per-pass plans retain accepted-owner limits. These finite limits do not promise a
specific process RSS or wall-clock runtime.

Attempted versus completed integration and geometry counters remain separate.
The owned F3 arithmetic session supplies actual Picard attempts; the owned B3
rational session supplies actual B3 arithmetic operations. The arithmetic quota
is specifically B3 rational geometry arithmetic, not a count of every Decimal
operation, interpreter instruction, signature comparison or serialization step.
New steps and reused boundary/certificate records are counted separately.
Unexpected exceptions can make work accounting incomplete, which must remain
explicit rather than manufacturing zero work for a lost call.

## Example wiring and timing limits

The example summary includes all derived result fields and complete ledger/pass
records, but excludes the input request object itself in favor of its strict
digest. It represents exact Fraction times by hexadecimal numerator/denominator
and Decimal bounds as strings. Timings are outside the scientific evidence.
Non-mutating wrappers measure integration kernels and geometry kernels;
orchestration is the remaining evaluation time. Input-load and inner evidence JSON
serialization timings are reported separately. In the inspected example,
`serialization_seconds` ends before the subsequent inner JSON parse, outer
envelope serialization and stdout emission; exclusive input-save time is also
outside `input_load_seconds`. These stages do not sum to complete child-process
wall time. The external owned-child measurement must supply that distinct total.
Instrumented/uninstrumented/replay equality must
be established by actual completed demonstrations, not inferred from this code
inspection. A timeout does not establish known completed scientific work.

Physical A has three total passes, physical B seven, both with initial 10-second
step and diagnostic one-second target. The unchanged accepted 1,800-second pilot
input is the physical authority. B is a separately labeled extension, not a
same-budget comparison. No success, one-day qualification or speedup is implied
before those bounded executions complete and their evidence is compared.

## Interfaces and independent acceptance checks

`LocalIlluminationPolicy` declares the six ceilings in the table above; there are
no inferred defaults. `evaluate_local_illumination(request)` constructs a fresh
`LocalIlluminationResult`. Status is `classified`, `resolution_reached`,
`budget_exhausted`, `numerical_limit` or `computational_failure`. Complete results
contain windows with exact supports, full 6D boundaries, signed tubes, geometry
records, pass histories and attempted/completed/reserved/reused counts. Failed
results have no usable windows. IDs address only this returned graph; importing
a previous graph is not an API. Per-pass maximum steps remains the supplied F3
policy's admitted value, never exceeding 4096; geometry remains at most 5118.

Coordinates, position boxes and Sun positions are metres in the declared shared
MODEL_INERTIAL frame; velocity is metres per second; time is exact simulation
seconds relative to the original TT epoch. No frame, epoch, ellipsoid, Sun
provenance, physical forcing or F3 policy is inferred or replaced by this layer.

The new tests use whole-arc analytic equatorial circles, including central
gravity and static-axis J2, with independent Taylor-series sine/cosine bounds
and their explicit remainder bounds. Synthetic n=1 and n=17/16 rad/s reference
solutions supply full position and velocity bounds over each closed source arc;
they do not sample the production trajectory or compare two calls to its solver.
Endpoint and tube containment use exact Fraction inequalities against Decimal
endpoints, with no acceptance tolerance. Independent inward-ray cross-product
bounds also verify a complete interior occulted interval. These intentionally
small synthetic problems verify composition, not Earth-flight accuracy.

Checks additionally cover signed nonzero-anchor/prefix grids, Sun knots,
multiple genuine propagation levels with nonzero retained uncertainty, old
certificate IDs, closed common-box contradictions, hostile nested mutations and
foreign/stale seeds, global quota reservations, late failures and atomic output,
strict input documents and fresh-process offline reconstruction. Existing B2,
B3 and B4 results/counters are checked against full before/after evidence and
their accepted regressions. Actual commands, source hashes, initial failures,
final test counts, demonstrations and long-study timings belong to the external
source-bound report; this contract alone is not a passing-test claim.

Example: `python -B -m examples.m2_local_illumination_demo --kind refinement
--offline --write-inputs <new-external-input.json>` creates an input-only document
and recomputes full evidence. Replay uses `--inputs <that-file> --expected-digest
<recorded-digest> --offline`; use external logs, TMP/TEMP and disabled bytecode.
Physical-A/B additionally require `--reference <unchanged-pilot-input.json>`.
No ephemeris fetch or fixture regeneration is required.

Deferred: event existence/uniqueness/timing, interval provider scientific combined
qualification, physical J2/Sun error bounds, target/station/Family B geometry,
engine execution grants, illumination/environment coupling, checkpoint authority
and wider M2. No result of this local numerical layer closes those obligations.
