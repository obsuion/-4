# YEAR-V2 review candidate

Exact canonical metadata loops use the existing admitted native owner. The original
canonical encode/decode/normalization/schema roundtrip order and constructors are
retained. No physical equations, numerical steps, tolerance or workload changes.
Native metadata counts are separate monotone implementation work, not model work.
The canonical recursion domain is explicitly bounded to900; valid admitted model
inputs remain within their existing64-depth domain. No graph/result cache.

New stores explicitly select YEAR_V2_LOSSLESS_OBJECT_STORE_POLICY_V3. This is a new
policy identity within the existing typed LifetimeCampaignPolicyV2 family, not
an alias for an existing store. Old B63 policy and status readers remain supported.
YEAR_V2_OBJECT_STATUS_ENVELOPE_V1 references canonical details field refs; large
fields are bounded lossless zlib6 objects addressed by decoded SHA256, with both
encoded and decoded hashes/sizes checked. Objects are append-only, retained for
all historical heads, charged before writes; late failure quarantines the writer.
No stream chunks/checkpoint prefixes are discarded. Export includes object files.
Continuation remains exactly source/build/runtime/root/policy/profile bound.
Initial authored DATA may explicitly change source_identity; old checkpoints
cannot be renamed or retagged. compile_job/admit_job/create_store/direct store and
existing serial lifetime supervisor remain the entry owners.

Worst-case pool reserves are unchanged until a proven supported bound replaces
them. Smaller measured files alone do not justify lower admission reserves.
Year and15-year execution are NOT_RUN. Linux, physical/day/event-time qualification
are separate statuses. FROZEN refers to stable candidate ABI, not acceptance.
