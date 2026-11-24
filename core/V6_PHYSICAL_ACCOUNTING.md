# CORE-90D-V6 scalar/grouped physical accounting

This candidate changes only administrative accounting in
`lifetime_physical_storage.py`. It does not change an orbit, physical solver,
work unit, storage format, policy cap, native allocation oracle, settlement,
content verification or scientific result. Existing V5 stores are not edited
or migrated by this change.

`snapshot()` reads bounded scalar grant columns, without producer or manifest
BLOBs. `namespace_snapshot()` uses one grouped claim query, one bounded mutable
projection and one namespace/grant join. It no longer executes three COUNT
queries for every historical grant. The snapshot reuses these projections
within its read view. This is a logical SQL/data-projection statement, not a
claim about zero filesystem reads of SQLite overflow pages or a measured whole
worker speedup.

All sums are Python exact integers after validating every contributing row.
Accounting uses no SQLite SUM, so mixed INTEGER/REAL coercion and SQLite signed
SUM overflow cannot silently change a result. Invalid role/state, negative,
noninteger or out-of-range saved quantities and finite population violations
fail closed. Invalid unused scalar fields, orphan claim/namespace groups and
malformed namespace reservations are also rejected rather than skipped. These
additional corruption refusals cover blind spots in the old projection; they
do not change valid source-produced values. Complete producer/manifests remain
on their original seal, consume, import and export boundaries.

For every grant, role charge is `charged_bytes` when SEALED and
`reserved_bytes` otherwise. RETAINED active reservation sums only unsealed
RETAINED grants; UNKNOWN reservation sums UNKNOWN grants of all roles. SEALED
logical/allocation totals, mutable charge, static precharge, role caps,
terminal headroom and the existing peak-bound formula remain unchanged.

Grouped namespace accounting retains cumulative retired scientific names. Each
original job keeps its unused three parent mutable names across SEALED and
the original conservative metadata-page hold until all three exist. Existing
late validation/append and UNKNOWN refusal semantics remain unchanged. Scalar
totals do not grant new ownership or pool credit.

Public accounting obtains one deferred read transaction and ends it with a
read-only rollback; if a mutation already owns a transaction, that same view
is reused. No durable logical COMMIT or filesystem write is added by the read.
The mutation commit still checks metadata escrow in that same transaction.
No mtime/content cache, weaker FULL/fsync mode or trusted metadata substitute
is introduced.

`test_physical_accounting_v6.py` contains an independent transcription of the
V5 equations and real temporary-owner cases: zero/one/several operations,
mixed roles/states, late mutable names, near active cap, corrupted fields,
transaction consistency and retained full-manifest seal refusal. Its growth
case creates one STATIC control reservation plus 192 SEGMENT-equivalent
producer reservations, real positive path claims, three real mutable files
per producer and 192 real native-allocation/content-verified settlements.
It records comparisons and constant SQL statement counts at 1/64/96/192,
database bytes, namespace and actual populations. Claims/allocation are never
disabled or faked. The configured mission policy is not used to authorize192
scientific jobs: this is component-level storage metadata qualification only.
It proves neither 90D capacity, year capacity nor a mission performance ratio.
Runtime and final scientific acceptance are separate root-owned gates.
