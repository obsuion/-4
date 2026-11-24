# B44 long connected mission — unreviewed candidate

This additive family connects static M1 compilation and the accepted full
spatial paid slew, EPS, thermal, degradation, protection, acquisition, storage
and multi-record custody owners. Existing V3/V4, checkpoint schema5 and every
accepted numerical/physical source remain unchanged. This is engineering
execution of declared synthetic plants, not full M2/M3 or physical qualification.

## Explicit authorities and modes

`LongMissionInputs` owns an immutable original `LongEnvironment`, finite
`LongMissionLimits`, catalog, mounted capabilities/actuator, unique program and
tuple of distinct `MSProductSpec` records. CAPTURE explicitly binds the real
request ID; opportunity, onboard record, capture group, delivery deadline and
credit retain their separate identities. CONTACT uses declared station/RF/rate
and actual accepted custody/receipt execution. Geometry is no RF availability
or successful receipt claim. Protections remain enabled.

`NOMINAL_LONG` uses binary64 RK4 point geometry and parallel-ray lighting held
on the explicit original-anchor lighting grid. Point samples authorize actions
only in this nominal contract. No interval visibility/illumination certificate
or enclosed physical evolution is claimed.

`CONTINUOUS_ACQUIRED_LONG` acquires one complete genuine B38 v2 graph from the
original root. The original producer limits, arithmetic and resource versions
are unchanged. Initial step admission refuses a day at the example's256-step
ceiling before the public evaluation. Unresolved illumination cannot feed
physics; unresolved/blocked whole-tube geometry cannot authorize acquisition
or contact. There is no fallback to nominal mode.

Time is simulation-relative exact Fraction seconds bound to the full accepted
TT epoch and MODEL_INERTIAL frame; Sun table and Earth-fixed catalog retain
complete ellipsoid/rotation identity. Binary64 nominal evaluation rounding is
explicit (at most half an ULP); it is no proof time bound. Maximum declared
elapsed duration86400s; local continuous geometry queries remain at most120s.
Ordinary mean rotation fits |phase|<=32; unsupported faster phases refuse.

## Original-grid nominal provider and acquired index

`LongNominalProvider` uses unchanged F2 `_rk4_step`/`_force` ordering with signed
full-step prefixes. For elapsed d, n=floor(|d|/h), remainder=|d|-nh. Every tail
is evaluated from that original-grid prefix and stored separately; a tail is
never the seed of a later full step. Keys bind trajectory/gravity/full frame,
epoch/grid/policy. There is no cache deserialization or new orbit authority.
Camera, panel, lighting and ground samples share this one process-local cache.

Each successful full/tail RK4 invocation entails four known force calls;
initial provider force admission entails one. Charges distinguish reserved
from completed force work, full/tail calls, reads/records, wrapper control
reservations and unknown failed primitive events. Failed primitive internals
are not guessed or refunded. These counters cover provider calls, not all
historical input-constructor force-admission validations or CPU seconds.

`AcquiredLongEnvironment` validates the complete source request/signature,
ancestry and partition once at acquisition, indexes CLOSED supports/profile
starts and performs local bisect selection. Whole source mutation/signature
guards run at action boundaries, not at every physical cut. All lookups,
index construction and mutation guards have finite charged control schedules.
Partition pieces use the producer's half-open/final-end convention; their
supporting geometric tubes are CLOSED. Clipping time never narrows a tube.
Local geometry reuses B43 rational ellipsoid/normal/LOS/FOV/end-ray derivation
on the real long source. Source step/boundary IDs, method, original root and
whole support remain visible. EPS/thermal integration is still nominal.

## Connected transactions and finite costs

Each action works on a private checked context. POINT compiles full inertia
and mounts, pays ideal net torque acceleration/braking/settling and electronics.
Per-cut panel incidence uses actual quaternion and nominal Sun-spacecraft ray.
Mechanical storage heat adjustment is separate from routed input heat; no
regeneration is invented. HOLD physically advances EPS/thermal/degradation at
all source/profile/lighting and declared integration cuts. Retention composes
over those cuts using the unchanged degradation owner.

An atomic refusal leaves published time/state/custody untouched and emits a
refused outcome. A subsequent explicit HOLD covers that remaining time; no
clock teleport or recovery override exists. Paid returned work counts before
late refusal; unreturned primitive work is an UNKNOWN event. Thermal endpoint
failures retain a typed private endpoint diagnostic where available, never a
published checkpoint. SAFE/BACKUP/emergency regimes refuse before paid work.
Partial transfers and consumed contact IDs persist across action boundaries.

Finite input admission caps actions128/products16/catalog16/thermal nodes64,
profiles128, source records16384, physical calls65536, nominal queries65536,
full steps20000, cache records65536 and provider force reservations262144.
Default physical interval30s, retained cuts4096; actions outside those declared
budgets can correctly refuse. Source B38 quotas are never enlarged by this API.

Prospective physical partitions/contact bindings admit retained cut count and
64KiB-per-cut scheduling allowance plus16MiB root overhead before primitive
work. Complete causal publication also validates the exact tree and encoded
size before the outer context commit. Default document cap256MiB, hard512MiB;
schema traversal is bounded to8Mi nodes/depth64 with bounded containers/strings.
Output reserves those maximum schema visits plus maximum encoded64-byte blocks
before each action/public serialization. Cumulative output control quota2**34
is a scheduling ceiling, not measured arithmetic leaves or elapsed time.
All causal fields remain encoded; no selected-field equality is substituted.

## New V5 input and continuation

`long_mission_document` has a fixed allowlisted immutable-input codec; no
callbacks, arbitrary imports, paths, pickle, eval or numerical result decoder.
Every schema is admitted before object construction. Old documents do not
migrate implicitly. Exact Fraction, Decimal and binary64 output encodings retain
the accepted canonical conventions.

Completed-boundary packets require externally retained packet SHA256 and input
digest. Save checks action/clock/context/pose consistency and rejects stale
mutable aliases. Cache/index/certificates are comparison DATA, never restored
authority. Fresh restore starts from the original orbit/environment, reacquires
B38 in continuous mode and privately replays the prefix using fresh caches.
Complete canonical science and checkpoint must match, not selected final fields.
Historical acquisitions/receipts/consumed IDs are reconstructed once privately,
then continued; there is no appended duplicate history or new physical root.

All replay cost ceilings are admitted before numerical acquisition. Costs add
to prior cumulative work; the prior history must cover the independently measured
equivalent prefix. Reconstruction-specific comparisons are separately paid.
Repeated restore can exhaust its finite quota. Runtime costs are separately
reported; science contains full immutable work policy, source/provider/world,
all permissions/actions/physical cuts/context/custody/product credit. Same-runtime
canonical equality is required; cross-platform float equality is not promised.

## Runnable cases and verification

`python -B -m examples.m3_long_mission_demo --mode CONTINUOUS_ACQUIRED_LONG --duration 600 --output <external-file>` selects the conditional600s case.
The NOMINAL_LONG default86400s case offers two requests separated6000s and an
explicit POINT attempt on the already declared opposite-side catalog target.
This common negative entry demonstrates real nominal geometry refusal. Compact
and outboard variants differ only in the two battery placements (.25/.7m).
All other world/controller/program/actuator/physical inputs are shared.

Synthetic loads are2W aggregate housekeeping (separate OBC zero), declared
station availability/RF1000bit/s, fixed distant synthetic Sun and explicit
radiation. The separately revised DAY-RADIATIVE-03 plant assigns emissivity0.8
to every thermal node, retaining areas/capacities/links/sink/protections. The
inherited short-demo zero-emissivity day refusal and earlier 1+.2W routing
refusal are retained in external evidence; they are not relabeled successes.
No winning hardware, flight power calibration or continuous safety is inferred.

Tests compare short/late/signed/off-grid cache queries exactly with independently
executed accepted F2, check ancestry/whole tubes and local domain guards, actual
600s paid acquisition/custody/credit, long idle cuts, strict mode/identity/memory
admission, unresolved refusal, late rollback/unknown work, duplicates, packet
tampering, cumulative reconstruction and complete replay equality. A genuine
module-cached source is reused for finite negative fixtures; that reuse is no
additional fresh producer evaluation. Actual process runs/counts/failures and
source-bound final gate are in the review package, not predicted by this contract.

Full-day restart may be NOT_RUN when the600s fresh-process replay is used.
Nominal day completion does not establish day enclosure, numerical/physical
qualification, event-time accuracy or a hardware winner. Event search/Family B,
realistic plant and wider M2/M3 obligations remain open. Combined qualification
UNRESOLVED; historical B7 cause UNKNOWN.
