# B70 exact guard repair candidate

Status: uncommitted Windows/PILOT candidate. B69 is HOLD for P2; stable peer
integration remains B68. No physics, numerical policy, tolerances, action grid,
V3 codec or scientific fees are changed. P1 ACTUAL/FORECAST consumers remain.
P3 is NOT_IMPLEMENTED; correctness eligibility precedes optional timing.

## Declaration/oracle domain

The compiled schema now pins fresh declaration module attributes and module
membership, not only formerly captured owners. The independent tests derive
required reads from retained oracle AST/imports and GLOBAL bytecode/AST, rather
than the descriptor builder's list. The review's16 cases are separately frozen.
The additional generation.__name__ dependency was found by this independent
inventory. Direct and nested-code globals of the retained roots, the fields
helper and check_schema_coverage are pinned, including dataclass generator
_FIELD/_FIELDS dependencies. Existing owner-domain, constructor/function,
metadata/property/default/closure/MRO/unused-owner/registry/Enum/Fraction checks
and the two precise canonical-identity/local-axis exceptions remain.

## Independent dispatch

The existing job identity entry calls an actually admitted immutable Cython
export INLINE, before invoking check/full/generation/graph. It does not rely on
the new Python dispatch helper to decide whether its own check is necessary.
The full-guard entry repeats the small independent check before CLOSED logic.
Generation dispatch uses the same direct immutable-C entry before the predicate.

The C arena privately retains the issued session, job and control plan in cdef
fields. The session cannot supply or replace that control plan. It validates
session fields/_pins, job dispatch bindings, function code/defaults/closures,
class dictionaries/MRO and module helper bindings before Python dispatch.
Native export identity is checked from private C state. A coordinated replacement
of session fields and its mutable _pins cannot rewrite this baseline. Replacing
a Python helper with no-op is rejected before its body. A fake Python callable
cannot replace the independently admitted immutable C entry. Different/native
foreign arenas or removed plan/pin are rejected rather than silently selecting
reference fallback. Python fallback remains for explicitly unprepared jobs.

This is the existing trusted-process source/build contract, not a sandbox
against arbitrary replacement of every trusted interpreter/module/caller.
Private methods alone grant no execution authority. Full source/runtime/binary
admission remains required. Plans are noncopyable, nonpersistent and bound to
process/thread/job/source. No CPython dictionary-version internals are used.
Callback/finally checks precede detached publication; a secondary guard error
cannot replace the original exception or traceback.

## Descriptor allocation closure and finite accounting

128MiB is an enforced descriptor-workspace reservation, NOT a whole Python
heap or RSS bound. Original model graphs, existing module/class/function objects,
allocator arenas and unrelated process state are not claimed to fit128MiB.
They keep their original input/graph ownership and resource admission. Strong
references keep declared targets alive for the job; their reference slots and
new snapshot containers are counted, not hidden as free authority.

Each plan has conservative R=4096+sum(row charges). A row charges512 bytes plus
128+64*n for EACH expected/extra tuple of length n, plus128+8*n for EACH name
or label string of length n. This covers the48-byte native row, seven-item row
tuple, row list/result-tuple overlap, reference slots, function-id/owner indexes,
snapshot tuple shells and their keys/values references, text and plan/weakref
bookkeeping. For the pinned64-bit CPython runtime these coefficients exceed
object/container layout sizes; tests and the external metadata inventory record
actual shallow container sizes separately. Original graph objects are retained,
not recursively cloned by descriptor preparation.

Before C allocation enforce live_reserved+2*R+2MiB <=128MiB. The factor2 covers
preparation coexistence of row list/tuple and growing indexes with final plan;
the fixed2MiB covers arena/session/index capacity and the bounded8192-pair
boundary package/list/set/transient mappingproxy keys. It is deliberately an
allocation model with headroom, not a statement about OS allocator fragmentation.
All producer row/sequence/text counts are bounded before snapshot allocation.
The native owner independently recomputes R; caller-reported sizes are not used.

Limits:262144 rows/plan,65536 sequence or mapping items,4096 characters/name or
label,1024 live issued plans,8192 boundary pairs. A future source change must
rejustify layout coefficients/closure and admission; no unverified128MiB total
heap claim follows from this profile. Actual RSS is recorded only in executions.
Resource refusal is explicit and retains paid control fees; it does not retry
with weaker checks or silently fall back.

The index holds weak owner/plan references. Dead entries are pruned before the
next admission; session plans hold strong graph edges only while their owner is
retained. Closing invalidates the arena; ordinary tracked-GC can release the
job/session/arena/control-plan cycle. The last-admission live reservation may
conservatively include entries that subsequently die until the next prune.
Lifetime counters remain monotone and do not become scientific work/state or a
checkpoint/receipt identity. Preparation/native dispatch attempts are separate.

## Acceptance and limitations

Fresh native C1/C2 mutations, independent completeness/control negatives,
callback/exit/primary-exception controls and current functional/restart evidence
are required. Tests and old saved B69 science are attributed to exact revisions;
metadata transcription is not native validation. Optional adjacent T7200 pairs
must follow correctness and source/build freeze, retain every failure and use
identical backend/physical inputs. Target15x has no advance guarantee.

No day/month/year/15years/Linux/cloud or physical qualification follows.
Historical1590/48/401 preservation FAIL remains; B7 cause UNKNOWN and combined
qualification UNRESOLVED. No frozen/adopted B70 authority before independent
review. Private caches/plans/addresses are not serialized execution grants.

## Resource repair V2 (recorded failure, no relaxed cap or comparisons)

V1 MAIN failed at clock370 when conservative live+2R+2MiB reservation exceeded
128MiB. It was NOT mathematical failure or completed continuation. Its exact
source, receipts, paid-prefix and failure remain. Fresh source requires new
initial stores. V2 uses a derived512-byte fixed-row allocation component plus
the SAME separately charged variable tuple/text closure and SAME2R+2MiB peak.
No descriptor comparison is removed, no cap is raised, no fees are refunded.

Fixed component on pinned64-bit CPython: C row48 + Python seven-item row tuple
96 + overallocated list slot16 + result tuple slot8 + conservative176 for
function/owner/class indexes, id integers, fresh callable wrappers and temporary
reference slots =344 bytes;512 provides168 bytes/row extra. Function-id entries
need at least3rows/function; owner entries at least8rows/owner. Fixed4096/plan
and2MiB transient arena reserve cover headers, bounded index capacity/tombstones,
recursion<=16 and the8192-pair validation package. Variable tuple shells/items
and name/label text are charged separately. Tests record actual container shell
sizes on the supported runtime. This is an explicit conservative allocation
model, not a proof of OS allocator/RSS behavior or recursive original graph size.
The capability retains512 as fixed per-row component and explicitly names the
V2 closure model; an old unversioned512*n upper-bound interpretation is invalid.
The independent control plan also seals original admission pins/build bytes and
native origin metadata before dispatch. New negatives cover coordinated build
pin replacement and all four actual native module-origin attributes.
