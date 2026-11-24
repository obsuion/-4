# YEAR-V3: administrative no-launch disposition and prepared CONTACT

Review candidate; no rollout, year execution, physical qualification or speedup is implied.

The explicit `YEAR_V3_NO_LAUNCH_OBJECT_STORE_POLICY_V4` is a prospective variant
of `LifetimeCampaignPolicyV2`. It preserves lossless V2 field-object storage and
all finite policy fields. Old policies/records remain readable; historical stores,
including CAMPAIGN B2289, are not renamed, migrated or repaired.

`LifecycleRunner` writes an immutable source/runtime/request/intent/dispatch/owner
boundary before `on_launch`, with 24,576 bytes prepaid irrevocably against that
job's existing parent output ledger (three bounded 8,192-byte files). The journal
has its original prospective whole-population reservation. An on-launch exception
can issue `YEAR_V3_RUNNER_NO_LAUNCH_PROOF_V1` only while this same runner has not
created/started a thread and has not attempted scientific launch. REFUSED status
must commit, and this exact dispatch owner must be released. A durable attempt
marker precedes `Thread.start`. An exception from an attempted Thread.start is
UNKNOWN, deliberately not a no-start proof. Missing PID/receipt, crash, attempted
launch, unreleased owner, incomplete publication or quarantine never grants recovery.

Public APIs in `lifetime_supervisor`:

- `reconcile_no_launch(directory, job_id, proof_sha256)` closes the exact durable
  DISPATCH/DIAGNOSTIC with a versioned administrative journal disposition. Duplicate
  identical reconciliation is idempotent. It never writes a scientific result,
  advances clock/checkpoint, grants credit, deletes FAIL/job/journal or refunds work.
- `authorize_no_launch_recovery(directory, job_id, proof_sha256, new_key=...)`
  records one explicit finite new-intent authority and returns its record SHA.
  The key must be new. The authority binds the full original intent with only its
  idempotency key replaced. Duplicate identical authorization is idempotent;
  different replacement, foreign proof, reuse or multiple pending refusals fail closed.
- `run(directory, no_launch_authority=...)` or the corresponding explicit
  `diagnostic(..., no_launch_authority=...)` consumes that authority once through
  the existing runner. Ordinary RESOURCE chains and explicit USER Continue retain
  their prior meaning. There is no automatic retry of PROCESS_FAILURE/UNKNOWN.

A no-launch job still consumes its original job/role/output/wall reservations and
ordinal. Only disposed no-launch jobs are excluded from scientific tip selection.
The last real settled checkpoint remains authoritative. Read-only result V5 exports
administrative dispositions/proofs separately from PRIMARY scientific results and
credit; status still shows the original REFUSED job. A failed proof/status/journal
publication is preserved and blocks recovery. This is integrity under the existing
local source-bound store authority, not a cryptographic signature against a user
who can rewrite every file and every trust anchor.

The private CONTACT capability owns one synchronous closed typed-generation
operation. Full raw input/schema/checkpoint/protection/integration admission runs
at its entry. Per-cut plan/forcing/schema, consumed/selected IDs, clock/horizon,
partial bits, dynamic schema-5 lossless roundtrip and all physical power/thermal/
storage/service/budget transitions remain checked. Only repeated immutable input,
protection-policy and integration-policy preparation is removed from inner cuts.
No plan/forcing/result/state is cached for a mission. Callback suspension/epoch,
foreign input/policy/runtime, scope exit or restart invalidates the capability.
ACTUAL/FORECAST retain separate runtime/work/dynamic state. The untrusted public
validator always performs complete original admission. Candidate state remains
private and late failures retain paid work under the existing transaction contract.
New consumer functions are included in the existing typed callable-origin pins.
Operational preparation counts are separate from scientific model work.

The generated native numerical C and all original numerical source are unchanged;
a current native build/receipt is bound separately. Functional/timing outcomes and
any limitations are in external source-bound validation addenda, not retroactively
written into an immutable FROZEN ABI. A profiled run is never a timing comparator.
