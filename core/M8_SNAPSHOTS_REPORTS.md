# B51 direct snapshots, incremental reports and diagnostic suffix

This uncommitted candidate repairs the supplied independent R1–R3 findings.
The supplied text is review authority; no separate reviewer file was supplied.
It adds a separately versioned direct method. Existing B48 paid causal replay
continues to mean reconstruction from the original immutable root.

Actual state map:

| Owner | State/consumer | Direct V1 contract |
|---|---|---|
| `rolling_execution.RollingState` | root, complete decisions/command lineage, knowledge, queued delayed observations, intents/reconciliation/diagnosis, aggregate work | Retain full bounded short prefix; keep `guard_rolling` unchanged |
| `rolling_physics.AdaptivePhysicalState` | context, body attitude/rest, commands/outcomes/acquisitions, consumed contacts, runtime/construction/harness work | Same complete committed boundary; no call to `start_physical` on restore |
| `checkpoint.CheckpointState` | clock, battery/retention/throughput, temperatures, mode/protection, storage, custody/partial transfers, mission/controller/diagnostics | Existing capture/restore and validation; no live schema change |
| `rolling_cache.PublicCacheBank` | distinct actual/forecast banks with shared cumulative `CommandWork` | Preserve both banks and rebinding of their fixed owned charge callbacks |
| `long_nominal_provider.LongNominalProvider` | original trajectory/grid anchor, signed full prefixes, exact-key tails, policy/identity/work | Preserve caches; explicit restore avoids constructor's initial gravity call |
| `long_environment.AcquiredLongEnvironment` | original lighting grid and cached held samples, index fields/counters | V1 supports NOMINAL_LONG only; never replace an acquired tube/uncertainty with nominal state |
| `command_estimation` | outstanding intents, received observation, queued feedback and private forecast records | Preserve old guard and future planning; post-restore forecasts may normally propagate unconfirmed older observations |
| `mission_report` | actual committed events, returned extrema, exact sums, receipt/credit deduplication, sealed rows | Separate bounded reporting work; reports do not seed physics |

Snapshot trust is advanced-state trust: only the source-bound running owner
publishes a generated immutable store artifact/manifest at a committed boundary.
External expected SHA/root/revision/source/runtime/method remain mandatory.
Integrity/structural validation is not an independent reachability proof.
No pickle/eval/payload imports/callbacks/filesystem paths. Fixed record schemas,
finite depth/count/bytes and exact scalar spellings reject unknown structures.

Direct prefix actual/forecast/nominal-force calls must be measured as zero in
the restore phase. Later suffix planning keeps the unchanged delayed-knowledge
policy, including its paid unconfirmed estimates; that is not seven-decision
restore replay. Definitions and indices may be rebuilt without force evaluation.
No RNG occurs in these supported owners; no RNG state is silently omitted.

Report semantics: explicit FIXED_30_DAY_BUCKET_V1, 2,592,000 seconds per bucket,
not Gregorian months. For the real short demo an offset places a true returned
cut boundary at a bucket boundary. First covered bucket and terminal partial
bucket are sealed with their actual coverage; neither is a simulated month.
Unsplittable physical contributions crossing a bucket fail with
NEEDS_REPORT_BOUNDARY_SUBSTEP; no interpolation of energy/temperature/event times.
Peak values are returned/sample extrema, not continuous safety certificates.

Diagnostic jobs have their own identity, budget and outputs, use the same root,
policy/step/age/environment and pinned snapshot, and cannot modify main credit.
Logging mode changes only diagnostics. Source/runtime drift rejects before
compilation/reservation/dispatch. Uncertain Run/Resume/diagnostic intents retain
their exact durable key/content and reconcile; an explicit new action is needed
to request another run.

V1 retains bounded complete short history/forecasts for existing guards. It is
not constant-size long state and does not remove all long-history bottlenecks.
The actual domain stays128–728 s; nominal cap86400 and old numerical quotas stay.
Snapshot cap128 MiB; additional snapshot/report control is separately bounded.
The store is explicitly V2 and refuses V1 reopening/migration. Snapshot control
uses separate prospective wrapper reservations; these are not Decimal leaves,
measured CPU operations or extra mission credit. Original root work is retained.
Two fixed cached derived records (GroundPointGeometry/GroundVisibilityResult)
have explicit field restorers; their prior geometry is not evaluated again.
SOC is derived from returned battery energy/capacity; extrema remain returned
state extrema. Rational energy sums are exact sums on returned binary64 inputs,
not exact physical forcing. The priority denominator is the common mission's
offered-weight authority; diagnostic-window credit can concern carried-in work.
Direct reports retain cumulative rows and additionally publish a window-only
report. The former includes prefix receipts; neither can be summed with the
main job to create extra mission credit. Detail chunks contain actual selected
returned parts; rejected forecast/trial temperatures are excluded.
15-year chronological month reports remain the goal, not an achieved campaign.
Four age slices would be additional experiments, not that chronological history.
Long coordinator/history compaction, 30-day/year/15-year speed and qualification,
broader hardware/recovery/orbital maneuvers/ageing/server remain CODE LEFT.
