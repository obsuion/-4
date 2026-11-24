# B57 lossless publication candidate

PublicationProfile is immutable execution/transport metadata. It is not added
to LifecycleRoot, its input document, controller policy or scientific identity.
The legacy absent profile branch retains the raw writer/reader. New store V3
and intent V3 bind the profile; each job may explicitly select compact or raw
for a diagnostic while the store status channel retains its default profile. Active parent codec work has a separate append-only paid ledger. Read-only status returns its per-read decode reservation in the head proof without mutating a store.
No historical B56 native state is migrated into new source.

The fixed profile uses independent standard-library zlib level6 frames. Limits:
decoded frame65536 bytes, encoded member131072 bytes,256 records, expansion1024.
Each frame records ordinal, first sequence, record count, both lengths and
SHA256 of encoded and decoded bytes. Chunk/index/frontier hashes bind order,
offsets and populations. Original canonical scientific records and event chain
are unmodified. Frames are complete authorities only after full validation.
Checkpoint snapshot flushes all buffered science; terminal finish seals frames,
indexes, manifests and the final separately reserved receipt. Torn live tails
are explicit and cannot authorize continuation. The saved full-artifact reader
rejects unexpected files and trailing index/chunk data; pinned historical
frontiers may have a later suffix outside their authority.

Memory is bounded by one decoded block, one encoded member and at most four
bounded chunks per live poll; decoded batch<=1MiB/1024 records, with complete backlog distinguished from incomplete tail. Scientific history is never held in an array.
Progress/status frames are individually flushed for incremental readers;
events/month rows/details use bounded blocks. No event downsampling occurs.
Original 1s opportunistic progress gating remains, with critical records forced.
It is not a heartbeat guarantee inside a long physical call.

Wrapper ledger preserves encoded publication reservations and adds deterministic
codec units:65536 fixed per stream, then before each canonical record encoding,2*maximum_record_bytes;
before a compression/hash attempt,8*decoded_bytes+8192. These are conservative
wrapper control units, not measured CPU or physical leaf calls. Restore/page
validation reserves encoded prefix bytes plus4*decoded bytes. Codec reservations
and whole parent costs are cumulative and never refunded. Native64MiB emergency
reserve and terminal headroom remain. Three possible pending frames have an
additional source-derived3*(131072+112) byte prospective allowance.

Typed retirement distinguishes autonomous SolarAction from LongMissionAction.
Solar does not claim a product, and its original pending plan/paid phase remains.
CAPTURE, issued commands, delayed/deferred ACK and custody remain pinned.
The regression's2s/12s deadlines are a declared synthetic narrow domain; they do
not change the original month input or establish reachability in B56 evidence.

The separately bound m8_compact_chain_cli.py admits exact source membership and
its own controller SHA. Five primaries plus two late diagnostics;8 jobs total,
128MiB/job,1536MiB store reservation. Settled TIME/approved OUTPUT may continue;
UserStop pauses and UNKNOWN suffixes block. UI reopen/status never dispatch.

Create from the exact B56 input with `examples.m8_lifecycle create --input ...
--publication-profile B57_LOSSLESS_ZLIB_BLOCKS_V1 --runner-store-policy
B54_FINITE_SEGMENTED_MAIN_LINEAGE_V1`; then chain-create with explicit
`--maximum-primary-segments 5`, chain-run with a durable command key, chain-stop,
chain-status, checkpoints, resume/diagnostic, report and export. Workbench uses
the same selectors, actual current/minimum Wh, sampled thermal maxima, credits/offers/expired/refused, prefix/full coverage and saved report rows endpoint. No voltage model is present.

Original B56 month starts80Wh; nominal battery capacity100Wh. Policy50%/75%,
hardware, numerics, heat, ageing and world stay frozen. B56's45003-event prefix
is saved-data roundtrip authority only. A new run may publish an observational
projection at transition45003 without changing a physical partition. Full
month/late equality, numerical qualification and hardware performance require
their own actual evidence; codec compression ratio does not establish speedup.
Battery resistance/voltage, O5, year/15-year campaigns and full V5 remain open.

The original frozen scientific revision is retained separately when a reader-only compatibility repair is prepared. Full jobs must carry strict bound intent. Bare legacy journal labels accept only job_id/root_identity and optional runtime; they grant no checkpoint/store/source authority. No frozen native state is migrated between source identities.

Revision boundary: the ongoing genuine month/late sequence remains on frozen scientific revision b57-04. The final reader candidate adds bare-legacy metadata compatibility, a decoded live batch bound and stricter completed-frontier admission. No active worker source is edited and no native is migrated. The scientific worker function, compact writer and all physical owners are compared exactly; saved results keep their original revision binding, followed by fresh final-reader short controls. This does not claim an unexecuted final-revision month.
