# B55-R1 construction-aware power recovery candidate

This candidate connects the existing allocation and sampled service owners to
the chronological lifecycle. It is an explicit new method. Implementation,
passing checks, completed scenarios and physical qualification are separate
claims: only source-bound saved results establish which scenarios ran and how
far they progressed. This contract does not assert completion of cases A–G,
the production month, MAIN/loupe continuation or HTTP acceptance.

## Version and input authority

The optional immutable `LifecycleRoot.service_policy` selects
`B55_CONSTRUCTION_RECOVERY_CHRONOLOGICAL_NOMINAL_V1`. Its explicit CREATE
selector is `B55_CONSTRUCTION_RECOVERY_POLICY_V1`; `LEGACY` keeps the historical
`None` behavior. Inputs use `B55_FINITE_POWER_SERVICE_LIFECYCLE_INPUT_V3` and
native checkpoints use `B55_POWER_SERVICE_CHECKPOINT_V4`. The complete policy
and its identity belong to the root/input/restore bindings. An existing legacy
root or checkpoint cannot be retagged or silently resumed with this policy.

Legacy roots omit new service fields from their old input/checkpoint schemas
and scientific observation representation. None of the new accounting fields
is authority to migrate an old result. B55 full endpoint scientific equality
and wrapper publication accounting are distinct comparisons.

An optional B55-only `reduced_sun_policy` may explicitly bind the already
implemented immutable `ReducedSunPolicy` for a declared REDUCED synthetic
fixture. `None` preserves the original wires/identities and the original month
input. An explicit override uses
`B55_POWER_SERVICE_EXPLICIT_REDUCED_SUN_INPUT_V4`, version 4, with a separated
input digest; it is not a replacement or retagging of any earlier fixture.
ACTUAL and FORECAST use the same immutable authored Sun policy with independent
cache/work scopes. This supplies a previously unbound existing phase input for
a separately named synthetic eclipse case; it adds no Sun physics, source
calibration or evidence of physical realism.

## Authored assumptions and sampled state

`lifecycle_service.PowerServicePolicy`, `PowerServiceState` and
`PowerServiceWork` are immutable. The selected states are `NORMAL`, `SAFE`,
`POWER_OFF` and `RECOVERY`. The fixed named selector uses these ASSUMED defaults:

| Input | Default and interpretation |
| --- | --- |
| Low reserve | 0.10 of **current usable** battery capacity |
| Recovery reserve | 0.30 of current usable capacity |
| Minimum dwell | 60 s since the current mode entry |
| Boot support | 120 s of selected, fully essential-served RECOVERY support |
| Additional POINT reserve | 0.05 of current usable capacity |
| CONTACT service chunk | 1 s, an explicit new-method action partition |
| Stationary domain | Rested ideal pose, no disturbances and no free attitude reset |
| Storage | Nonvolatile retained custody; reboot does not erase partial data |
| Housekeeping | Positive BASE_BUS + OBC demand includes computer and NORMAL low-rate telemetry when these are authored as an aggregate |

These values are reduced modeling assumptions, not flight-calibrated limits,
terminal-voltage/brownout thresholds or a demonstrated conservative bound.
They were declared before inspecting new recovery outcomes. Hardware, forcing,
ageing, controller requests and numerical settings are not fitted to obtain a
month completion.

At an accepted physical boundary, NORMAL enters SAFE at the low reserve and
an observed essential electrical deficit enters POWER_OFF. SAFE/OFF may enter
RECOVERY only after the high reserve, minimum dwell and restored essential
service. Boot loses support or reserve explicitly; NORMAL is reached only
after accepted boot support. These are sampled decisions, not exact physical
switch times. A decision cannot advance a stale clock or already consumed
work frontier. Every degraded selected mode requires the stationary domain.

## Construction-aware physical transaction

`construction_service.service_physical_substep` reuses the compiled regulated
star, wire/EPS and coupled thermal/ageing owners. It distinguishes desired
normal demand, commanded receiving demand and served receiving demand. SAFE,
POWER_OFF and RECOVERY shed nonessential branches but retain the authored
positive essential request: POWER_OFF is not a fictitious zero-demand model.
The diagnostic retains essential deficit, full-demand trial and selected
electrical results. A finite deterministic 32-bisection allocation is a
feasibility approximation, not an interval proof.

Private allocation and quiet full/half proposals pay their own work, including
failed proposals. Rejected trials do not publish physical time, heat, ageing,
selected mode duration, pose, mission output or receipts. The selected private
context, immutable service state/work, pose/pending action and custody publish
as one coherent candidate transaction. No independent helper grants power or
mutates the actual context. Receiving-energy accounting uses exact rational
sums of the admitted component binary64 powers, avoiding a second rounded
sum solely for accounting. This exact bookkeeping does not make the physical
integration exact.

The actual model stores `service_state`, `service_work`,
`service_allocation_work` and `last_service_diagnostic`. Independent forecasting
starts from the received service snapshot with a fresh forecast ledger. Its
private probes cannot advance the actual selected service frontier.

Exact selected support comes from the battery owner's serialized rational or
dyadic duration, including a non-dyadic final CONTACT receipt fraction. Mode,
boot and receiving Wh use that exact support and must exactly match the service
diagnostic interval. Original EPS/heat Wh equations and the audit's EPS sums
retain the accepted binary64 `dt_seconds` convention. Those separate numerical
scopes are declared rather than reconciled with a tolerance.

A late coordinator/report/guard failure retains paid attempts but restores the
prior selected lighting, physical/service/report/pose/custody frontier and
selected bookkeeping. Sparse retirement is staged without cache eviction;
both retention calls are admitted before either scope evicts, after the full
candidate guard. Previously paid numerical and cache work is not refunded.

## Electrical service, actions and custody

Aggregate low-rate telemetry/OBC service is separate from high-rate TX.
`communications_serviceable` is the explicit low-rate NORMAL housekeeping
assumption; its projection also names `low_rate_telemetry_serviceable`.
`tx_fully_served` is a separate per-selected-cut grant. Partial essential watts
do not operate the computer/radio; partial high-rate TX does not earn full
bits. Genuine CONTACT geometry and declared station serviceability remain
required.

The B55 CONTACT adapter checks receiving TX service at each declared one-second
chunk. Positive selected transmission prefixes, paid physical evolution and
nonvolatile partial custody survive interruption. Unsupported suffixes do not
earn bits, receipts or completion. Incomplete CAPTURE does not create a
product. A stationary interrupted action returns an explicit refused/partial
disposition with its paid prefix. Moving POINT recovery is outside this
stationary model: the current pose, phase and pending work are retained and
the result is explicitly incomplete/unsupported. It cannot teleport to a
rested pose. A retained pending POINT cannot generate terminal command ACK.

NORMAL physical equivalence is exact only where the operation partition is
unchanged, after separating declared new method/root/service/work identities.
The new CONTACT partition is declared and requires numerical comparison;
cross-method bitwise physical equality is not promised for CONTACT.

## Quiet physics and thermal domain

Quiet HOLD uses the existing paid adaptive owner with mode-aware active
constraints, forcing/event boundaries, recovery/dwell/boot cuts and its
declared error screens. Private full/half probes carry separate service
bundles; only selected support counts toward mode and boot duration. OFF at
zero energy does not authorize resetting state, skipping generation/thermal
physics or claiming continuous safety. NORMAL uses operating limits; degraded
support is tested in the declared survival domain. Rejected trial temperature
is a diagnostic and is never an actual selected temperature extremum.

## Delayed knowledge and long blackout bookkeeping

Actual FDIR reads actual state. The ground controller reads received packets
and its paid model estimates; it is not handed actual SAFE/OFF mode as hidden
knowledge. Stale observations suppress an unsupported forecast/action without
being replaced by the private actual state.

Previously transmitted in-flight packets retain their original delivery time.
While functional telemetry is unavailable, genuine terminal command metadata
can remain as bounded deferred feedback. It contains no invented resource
snapshot. After paid boot and restored NORMAL low-rate service, a later packet
contains current observed resources plus the original genuine command
completion time. The declared downlink latency still applies; only receipt of
that packet resolves the issued intent exactly once.

Public expiry is not ACK. Sparse active requests and a bounded pinned set keep
unresolved command/feedback/custody obligations without retaining every
historical request or an unbounded old environment cache. Expiry may retire
public opportunities; reboot, shedding or queue pressure cannot erase paid
partial custody. Ground accounting and delivered product credit still require
the actual accepted delivery owner.

## Checkpoint, reports and application

The fixed native registry persists service policy/state/work, selected
diagnostics, active/pinned requests, genuine deferred feedback, pending action,
pose, custody, report frontiers and independent actual/forecast ledgers. Restore
remains data-only admission followed by actual future suffix execution; an
output graph is not a new initial-orbit or continuation authority by itself.

Progress exposes current actual mode/reason, distinct low-rate/TX flags,
selected durations, boot/counters, receiving energies and bounded pin/deferred
counts. These actual observables do not become inputs to the ground planner.
Report totals separately record desired, commanded, served, shed and essential
unserved receiving Wh. Selected mode durations sum exactly to the covered
actual interval. Actual denied actions, interrupted actions and publicly
expired requests remain separate counts.

Sparse energy audits group selected support by original-root day and mode;
the epoch is the original root start (128 s in this study). Their first/last
support, covered seconds, gaps/day crossing flags, sampled extrema and exact
stored-energy deltas are explicit. They do not interpolate an end-of-day
state or introduce extra physical cuts. Only retained rows establish the
published detail; cumulative totals do not preserve an unbounded audit list.

On a model-incomplete stop, a nonempty actual prefix may seal one
PARTIAL_TERMINAL row. A cooperative application Stop keeps the native ACTIVE
continuation state and publishes a copied report-view sidecar pinned to that
native SHA. The copied partial row is observational, not an alternative
restart state. An empty endpoint row is not manufactured to announce failure.
App input/progress/report/restore readers admit the new version strictly;
legacy None schemas retain their historical shape. Finite job/store/output
budgets and the existing two named predecessor slots remain in force.

## Predeclared verification screens and limitations

`PROTOCOL-R1.json` freezes short comparisons before actual A–G results:

| Comparison | Acceptance screen |
| --- | --- |
| Actual shared saved sample times | Energy difference ≤ 0.01 Wh; each node temperature difference ≤ 0.125 K |
| Recorded matching mode/reason sequence | Sampled transition time difference ≤ 2 s |
| Same-policy, same-environment fresh continuation | Complete canonical scientific endpoint bytes exactly equal, no scientific exclusions |
| Credit, bits, request/command identity | Exact discrete accounting; separately report every action/completion/protection disagreement |
| NORMAL unchanged action partition | Exact physical checkpoint spacecraft, quaternion/clock and compatible mission totals; declared identity/accounting additions separated |

The energy/thermal screens are half the existing 0.02 Wh/0.25 K operating guard
margins. They are nominal convergence screens, not global error bounds or
continuous safety proof. Missing shared samples or hidden within-event mode
switches are NOT_CHECKED, not PASS; switch uncertainty is not event-time
accuracy. CONTACT uses the declared new partition rather than changing old
method results. No tolerance is widened after inspecting a failure.

The source-bound commands, frozen revisions, saved failures, actual case
inventory and final verifier determine achieved evidence. A smoke/focused
gate does not qualify the blackout, partial CONTACT, month or restart. Historical
general preservation remains FAIL_UNEXPLAINED_NO_EXCEPTION even when new-task
entry/exit bytes match. B55 does not complete full Version M or full V5;
continuous validated H5/physical calibration and wider mission qualification
remain separate obligations.

The initial D01 production CONTACT exposed a report-duration error on a final
fractional receipt part and then a selected-lighting/report transaction error.
Its complete endpoint was not established. The coherent prior native prefix
ends at 532 s; the failed attempt's prematurely advanced lighting-derived
`actual_coverage` value of 537 s is not coherent accepted coverage. The failed
source, outputs and publication error are retained; a corrected later run has
its own input/source/launch binding and does not overwrite D01.

After a request's public deadline and genuine causal reconciliation, the
existing explicit `retire_lifecycle_products(..., allow_discard_expired=True)`
mechanism may dispose of an expired product, including its partial transfer.
The accounted `known_expired_discards` records that disposition. This is
different from silently erasing custody on reboot, shedding or queue pressure;
unresolved issued command/feedback references remain pinned until reconciled.
