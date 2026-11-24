# YEAR-V5 packed DATA and prospective terminal storage

This additive candidate uses policy `YEAR_V5_PACKED_TERMINAL_STORAGE_POLICY_V6`
and store `YEAR_V5_PACKED_PHYSICAL_LIFETIME_STORE_V2`. It does not migrate a V4
workspace or alter its policy, object layout, physical accounting or reader.
Scientific checkpoint authority, event/month/detail streams and numerical
results remain with their existing owners. Administrative status is DATA.

## Packed status and strict consume

`lifetime_status.preflight(..., packed_store=True)` and its existing Publisher
produce `YEAR_V5_PACKED_STATUS_ENVELOPE_V1`. Full canonical field references use
`YEAR_V5_PACKED_CANONICAL_JOB_FIELD_REFS_V1`; lossless hydration restores the same
full job wire. Logical `objects/<decoded-sha>.zjson` and
`details/<sequence>-<encoded-sha>.json` names are not individual physical files.

`lifetime_packed_status.PackedStatus` owns `status63/packed-v1/index.sqlite3`,
its stable PERSIST journal and at most 128 one-MiB `block-%08d.bin` files.
The index is bounded to 4096 4096-byte pages and 65536 logical objects. Ordinary
publication retains 128 logical entries, two blocks/two MiB and 128 index pages
for terminal status. These are finite limits, not a year-capacity guarantee.

Each frame is a four-byte unsigned big-endian header length, canonical JSON
header and exact payload. The header binds format, logical key, monotone
sequence, FIELD/DETAILS role, source/context digest, encoded length/SHA-256,
codec, decoded length/SHA-256. FIELD data uses the existing bounded canonical
zlib codec. DETAILS data is canonical JSON. Index rows bind key hash, block,
offset, frame length, payload length/digest, role and sequence. Every consume
checks the named range, canonical header, source, key, role, sequence, encoded
and decoded bytes. A filename or mtime is never an integrity proof.

New frame bytes are fsynced before the SQLite FULL commit. The status head is
published only after all indexed objects commit. Append/index failure
quarantines the writer; unindexed tails are not truncated or adopted. Head
failure may leave complete unreferenced DATA but cannot publish a head ahead of
its missing objects. Closing seals the current block. Explicit `verify_import`
checks every sealed block and indexed object; physical producer settlement
requires this complete new-job check. Ordinary append checks its frontier and
named duplicate, not old completed blocks. The old-prefix counter explicitly
excludes the current block's one-time seal and named-object consumption.

The pinned SQLite3.50.4/source-identity gate remains required. PERSIST/FULL and
journal-size-limit zero preserve the same journal name across transactions;
they do not imply independent Windows directory power-loss qualification.

The parent-created administrative writer is explicitly process-owned and
thread-serialized. A private RLock covers every public read/contains/put/import/
snapshot/close operation, including nested calls. SQLite check_same_thread is
false only for this locked owner, allowing the existing parent-to-Runner-thread
handoff and main-thread close. Thread-capable pinned SQLite is required.
The creator PID is checked before acquiring the lock and again under it,
before any connection/block use. A foreign process cannot adopt an inherited
connection or lock. Construction completes before the object is shared;
separate fresh-process readers construct their own handles. Physical-owner
foreign-thread/process guards and the caller's existing store RLock remain
unchanged. This is not concurrent scientific execution or writer adoption.

## Positive incremental pool and trust boundary

The new namespace consists of a bounded 16-KiB
`LIFETIME-PHYSICAL-POOL-V2.json` header, one bounded 16-KiB slot per study in
`LIFETIME-PHYSICAL-POOL-V2/` (at most 128 studies), and a bounded lock. Ordinary
Continue rewrites only changed slots. The header changes only when a study is
added. No ever-growing per-file pool JSON or historical content scan occurs.
Both publication overlap and pending names are bounded. Unknown `.pending`
files and unindexed slot names fail closed; they are not repaired implicitly.

A slot binds key, policy identity, exact contract, four independent owner
roles, initialized marker, credited sequence/bytes and seal-chain digest.
Actual physical credit comes from the source-owned SQLite
`packed_pool_seals(sequence, operation, cumulative_allocated_bytes, chain)`
ledger. Before advancing credit, the pool verifies each newly sealed producer
manifest, content and native allocation against that committed ledger. Cached
slot values alone, SHA-like names, size/mtime and hardlinks earn no credit.
UNKNOWN/orphaned/unregistered bytes remain charged. A lost initialized owner
cannot become a legacy workspace. Native allocation uses the unchanged strict
V4 single-link/regular/nonreparse guard. Root volume and directory identity
bind the namespace; copied directories require a separate verified import,
not automatic execution admission.

This is an explicit changed integrity scope: untouched sealed producer blocks
are source-owner-controlled immutable history. They are verified at seal,
named consume and explicit full import/audit, rather than rehashed on every
poll. This is not a claim to detect arbitrary administrative tampering in all
old, unconsumed DATA on every poll. The read-only workspace helper validates
the bounded owner/slot bindings and positive external ownership; a final
explicit audit may sweep all immutable `files` rows once. Execution checkpoint
consumers retain their existing exact source/context/scientific bindings.

## Terminal-family namespace and metadata escrow

Before a segment can launch, the physical owner reserves its byte grant plus
512 FILE names, three declared parent-append names, 528 directory slots, 128
terminal index rows and 1024 metadata pages. Ordinary segment creation keeps
64 FILE and 64 directory names unused; it cannot consume the promised index
page headroom. The existing final/failure/Stop/quota checkpoint boundary
activates terminal spending before encoding. Parent Stop/error paths also
activate it. Packed parent terminal/STOP_REQUESTED publication activates its
own existing RESERVED namespace before error-reservation or packed paths, even
if no worker checkpoint exists. It cannot adopt an UNKNOWN producer. Legacy
activation is a no-op. UNKNOWN retains all unused
namespace/page escrow. Only proved producer closure releases unused slots;
actual and retired scientific names remain cumulative and cannot be reused.

The three administrative parent ledger names are a persistent exception to
releasing unused scientific-name escrow: their original job retains every
unused one across SEALED. Existing publication/codec ledgers may be appended
monotonically after seal; the first late validation ledger consumes the third
original slot. Exact job/scope/kind/leaf and the original SEGMENT grant must
match this source-owned database. UNKNOWN does not permit adoption or append.
No fourth name, scientific/retired claim conversion, orphan or producer change
is admitted. Existing bytes must have the exact prior reserved length; a
missing/partial append retains its charge and refuses automatic retry.
Namespace V2 counts those closed-job future slots in the unchanged global32768
cap. Until all three names are allocated, it conservatively retains the
original segment metadata-page escrow; it does not assume an unproved small
late-insertion SQLite split bound. This may honestly limit a chain which never
consumes its predeclared validation name. No old store is upgraded or edited.

Global caps remain 32768 FILE names, 4096 FILE names per legacy operation and
4096 physical-owner pages. There is no generic MAX_FILES or old-pool-size
increase. `admission_status` distinguishes
`GLOBAL_NAMESPACE_OR_METADATA_BUDGET_EXHAUSTED` from retained-byte exhaustion.
The supervisor can therefore save a durable resource HALT without launching an
empty retry loop. Segment limits remain finite; a year with too many segments
can honestly HALT despite free retained bytes.

Any packed UNKNOWN escrow refuses a new segment with
`UNKNOWN_UNSETTLED_PRODUCER`, without refund or a resume override. Its last
proved checkpoint remains readable/exportable. This prevents a second packed
rollback journal from accumulating over an uncertain first journal; U704 MiB
admits one packed journal overlap, not arbitrarily many UNKNOWN producers.
The legacy V4 admission branch is unchanged.

SQLite COMMIT is the durable boundary. A failure before COMMIT leaves the old
tip and full reservation. A failure after a real COMMIT but before caller
acknowledgment is reported as a failed call with the newly committed exact tip
visible on reopen; it is not falsely reported as rollback, success or refunded
UNKNOWN. No automatic retry or state repair is performed by these owners.

## Conditional physical commitment

The new explicit formula, in MiB, is

`C = R2560 + A512 + T128 + U704 + X640 + B2560 + M576 = 7680`.

Thus C is 7.5 GiB under the admitted allocation unit, pinned SQLite and finite
namespace assumptions. R and the independent full-copy backup B each change
from V4's 3072 MiB to 2560 MiB. U changes from 128 to 704 MiB to include one
concurrent bounded packed-index journal. The pinned worst-case whole-database
journal bound is 553877504 bytes; adding the old128-MiB overlap fits U704 MiB.
The physical owner retains its separate bounded database/journal allowance.
No hardlink backup credit is used. Backup execution is a separate operation;
the formula does not claim a backup was created. RAW fallback, export and
temporary overlap remain prospectively charged. This resource formula alone
establishes neither year capacity nor completed annual scientific execution.

Focused fault/codec/capacity tests and a separately timed synthetic corpus are
review gates, not results claimed by this document. The corpus exceeds 32768
logical objects and four MiB of equivalent old inventory while reporting real
index/block bytes, RSS samples and explicit-import cost. An actual mission
chain, fresh restart and final export remain distinct integration evidence.
