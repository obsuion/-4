# Finite 90-day preparation

`ops_sim.v5.ninety_day_project` prepares fresh, source-bound 90-day DATA for the existing V5 serial lifetime consumer. It adds no propagator, numerical method, process launcher, policy-cap increase or checkpoint migration. CORE does not execute the five 90-day trajectories; CAMPAIGN selects a proposal after its measured pilot and before creating/dispatching its long stores.

The input is any supported exact `SpacecraftProjectV3` with `DesignSpecificationV2`, including `ninety_day_designs.AuthoredDesign.project`. The preparation owner does not whitelist D1–D5 names or substitute precompiled roots. The original anchor is 128 s; duration is 7,776,000 s; target is 7,776,128 s. The existing owner must independently confirm the complete root, world, resource plan, input codec, build and runtime. At inherited cadence 900 s/deadline 600 s, the owner formula gives 8,640 complete offered windows. Offered requests are not acquisitions, deliveries or credits.

## Public DATA and execution interface

```python
from ops_sim.v5 import ninety_day_project as long

policy = long.policy_for('P64')  # Or P96; exact existing LifetimeCampaignPolicyV2.
raw = long.compile_job(authored.project, 'P64', compile_ledger, build_bytes)
project, root, execution = long.admit_job(raw, independent_ledger)
created = long.create_store(raw, new_projects_directory, new_workspace_directory,
                            creation_ledger)
actual_store_path = created['store']  # Returned by the real existing owner.

# Run only when the separate caller's numerical grant/admission permits it.
long.run(actual_store_path, maximum_segments=1)
long.status(actual_store_path)
long.stop(actual_store_path)
long.resume(actual_store_path, maximum_segments=1)
long.export_result(actual_store_path, new_reserved_export_path)
```

Compilation/admission/creation use the existing paid constructor ledgers. The example is an API contract, not evidence that these calls ran. `create_store` performs the existing creation path once and reports the actual path, project/root/plan identities, profile, policy identity, embedded V5 job SHA and outer 90D job SHA. It does not dispatch. The export path must be the existing owner's reserved `.exports` directory, not an invented arbitrary path.

The canonical `CORE_90D_V6_PREPARED_SERIAL_JOB_V1` envelope contains the exact existing `YEAR_V5_EXPLICIT_SHORT_CIRCUIT_PACKED_JOB_V2` bytes. Its digest binds the profile, fixed horizon, inner raw SHA, policy identity and capacity proposal. Strict envelope admission precedes the existing complete independent V5 admission. The envelope never grants trust to an authored root without the existing reconstruction. A rehashed declaration cannot change the inner policy, horizon or finite dimensions silently.

`run`/`resume` require an explicit exact integer from 1 to 96 per invocation; the existing store's remaining role/elapsed/output quotas remain authoritative. The profile cannot be changed in an existing store. A different P64/P96 selection requires fresh DATA and a fresh source-bound store. A settled native suffix remains the only continuation authority; telemetry, UNKNOWN and unclosed writes are not checkpoints.

## Two unchanged-cap proposals

| Field | P64 | P96 |
|---|---:|---:|
| PRIMARY limit | 64 | 96 |
| Reserved DIAGNOSTIC slots | 2 | 2 |
| Full PRIMARY observed-wall allowance, s | 57,728 | 86,592 |
| DIAGNOSTIC observed-wall allowance, s | 1,804 | 1,804 |
| Soft / hard / finalization / cleanup, s | 840 / 900 / 60 / 2 | 840 / 900 / 60 / 2 |
| Journal records / record bytes | 512 / 4,096 | 512 / 4,096 |
| Existing constructor journal minimum | 148 | 212 |

The journal payload reserve is 2 MiB within the existing 64 MiB metadata allowance. The minimum is the existing policy's admission formula `2*maximum_jobs+16`, not a proof that every future Stop/recovery/control sequence fits. Runtime journal limits still apply.

Expected policy identities can be derived independently from the exact source fields using canonical sorted JSON. Actual policy construction/codec gates must confirm them; this document does not claim such a gate ran:

- P64: `88362f8e97913ef7b04bcf1f59a738e72918b7025a6718585f361db55e5fa2dc`.
- P96: `7d9739fca0caf4eb1f0f54384637ae7e77ac9b42966022e6aa61c5a3969c346d`.

## Capacity dimensions and safe refusal

`capacity_proposal` reads dimensions from the actual existing physical, packed, pool and result owners. It does not allocate space or inspect a filesystem. Its finite values are:

- Physical owner: 4,096 pages × 4,096 bytes, 32,768 cumulative FILE names and 16,384 operation rows. Retired scientific names are not reused.
- Active segment: prospective 512 FILE names plus three original mutable ledger names; separate terminal FILE/directory/index-row headroom remains in the existing owner.
- Packed job: 65,536 logical objects, 128 blocks × 1 MiB, 16 MiB index, with reserved terminal objects/blocks/index pages. Logical objects are not physical FILE names.
- Public physical export: **128 MiB** per operation. The result reader's separate **512 MiB** ceiling does not increase that grant. All retained per-job scientific endpoints, initial DATA, view and the 8 MiB manifest reserve must fit the 128 MiB public boundary. The result FILE-count cap is 16,384.
- Per-study physical commitment: **8,053,063,680 bytes = 7.5 GiB**. Backup is reserved, not created. These caps do not establish actual 90D or annual sufficiency.

P64 includes 66 possible jobs and P96 includes 98. Multiplying their full 512-FILE grants gives 33,792 / 50,176 names, both above 32,768. This deliberately visible failure of the coarse maximum does **not** prove actual exhaustion: only unsettled unused slots remain reserved, while settled jobs retain their actual cumulative names. It prevents an unconditional completion claim. Admission must inspect actual cumulative claims/retired names, mutable names, outstanding slots and pages before the next finite grant.

Normal final verification creates all three mutable ledgers before seal. Once all three exist, unused original page escrow is released. A SEALED row whose mutable names are still missing keeps the original conservative escrow. It is incorrect to reserve 1,024 pages permanently for every normally SEALED segment, or to release it merely because a row says SEALED.

The existing pinned SQLite/pager proof and 704 MiB temporary allowance are unchanged. One UNKNOWN producer is retained and causes HALT; no second scientific launch is admitted over an uncertain suffix. Terminal refusal/ACK, actual allocation-unit limits, page limits, source bindings and the current pool/disk screen remain required. Exhaustion must preserve the available settled state; this preparation layer does not disable a guard or manufacture completion.

For five designs, `group_capacity_proposal` conservatively sums five complete commitments: **40,265,318,400 bytes = 37.5 GiB**, then adds **4,227,072 bytes** of shared-pool metadata without subtracting overlap already allowed in per-owner metadata. Total is **40,269,545,472 bytes** before other stores' outstanding commitments. The actual pool has a 128-study bound and must independently admit current free space, namespace and existing foreign reservations. This arithmetic is not a current free-space measurement or proof that all trajectories finish.

## Measured-day estimates and evidence

`estimate_from_day` accepts one exact `CORE_90D_V6_BOUND_DAY_OBSERVATION_V1` DATA record with source/specification/root/evidence SHA bindings, the complete `[128,86528]` horizon, separate parent/worker clocks, retained file data, cumulative names/pages and actual export bytes. The caller must retain and independently verify the raw evidence. Declared DATA alone does not establish measurement truth.

The result is explicitly `ESTIMATED_FROM_DAY_WITH_ENFORCED_HALT`: stationary cost/retention multiplied by 90, upward-rounded PRIMARY count at soft 840 s and a declared twofold planning margin. The margin is not a proved bound. A projected page/name/output excess remains visible; the estimator does not increase caps. One hardware design's day is not a measurement of the other four.

The accepted historical V5 day is useful context but does not match all five new assemblies. New D1 short/day controls and actual physical-owner growth admission are separate required gates. No 90D execution, complete-capacity guarantee, year result, physical calibration or hardware winner follows from source formulas, a synthetic metadata corpus or successful short controls.

## Reference comparison and handoff

The V5 reference already supports general V3 DATA. A new producer can export a genuine V3 document; each implementation strictly loads it, explicitly rebinds only initial `source_identity`, reserializes and independently compiles through the same existing owners. This is fresh input DATA, never a checkpoint migration or trusted compiled-root substitution.

V5→V6 storage-query optimization is intended to preserve every scientific value and every model/work counter. Comparisons retain the full corresponding views, with only explicitly declared source/provenance mappings if necessary. The V4→V5 physical projector that dropped changed work records is not appropriate here.

The task-local DRAFT ABI is not peer ACK or run permission. Root publishes a new immutable matching FINAL only after actual source/build/runtime, all five constructor outputs, finite proposals, connected controls, export/readback and preservation gates. CAMPAIGN ACK must name the exact FINAL manifest and compatible source/runtime. Earlier shared slots, stores, inputs and ledgers remain unchanged.

Initial validation of this file/module is AST/static only. Root-owned focused gates and actual constructor/mission results are recorded separately. Historical FAIL1590/48/401 remains OPEN/NO_EXCEPTION; B7 remains UNKNOWN; combined/physical qualification remains UNRESOLVED.
