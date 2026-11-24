# B41: corrected bounded environment-aware mission execution

Status: opt-in review candidate after accepted B39. Legacy context/checkpoint
schema and every accepted numerical/M1 owner are unchanged. Full M2/M3 and
combined physical qualification are not complete.

## Input, geometry and time contract

`EnvironmentMissionInputs` owns immutable simulation inputs, initial completed
checkpoint, original-anchor B38 request, forcing profile, real M1 design,
capability axes, actuator policy, target/station catalog, one MS product,
action program and finite cumulative runtime limits. CommonWorld continues to
own identities/horizon/events; this program owns its request. No fictitious
request registry was added. This path admits an explicitly event-free world,
empty initial data custody, integer action boundaries and <=120 s source span.
No second coast authority may be attached to SimulationInputs.

`mission_environment.sample_catalog` evaluates the existing origin-anchored
nominal J2 Cartesian owner at ordered finite timestamps, then the existing C1
point geometry and C2a ellipsoid/elevation owners. Full TT epoch/frame/ellipsoid
identities are checked. Requested times remain Fractions; conversion to a
binary64 GeometryInstant is explicit, bounded by half an ULP and recorded.
Ranges are metres; geodetic/view angles radians; optical legacy inputs degrees.
Directions are simultaneous MODEL_INERTIAL vectors. No local direction at
another time is silently compared as the same frame.

The comparison/control geometry mode is **NOMINAL_SAMPLED_J2_POINT_GRID_V1**. Every requested
sample must be visible; boundary/UNRESOLVED is not visibility admission. Finite
samples cannot prove visibility between samples. Station availability, RF
admission and rate are independent explicit assumptions; geometric LOS alone
never creates serviceability, electrical feasibility or receipt.

## Execution and physical ownership

`start_environment_mission` executes the actual B38 owner from its original
anchor. Saved results are never accepted as replacement numerical authority.
`advance_environment_mission` creates a private checked context, splits at the
exact union of B39 support/profile boundaries and action phase boundaries,
refines to its declared maximum interval, calls the existing physical
completion owner and validates before one `_commit_action`. Exact Fractions
own boundaries; binary64 evaluates the existing nominal physical equations.
Refused actions advance only the declared program cursor, without clock,
attitude, custody or physical-state mutation. Primitive/commit errors publish
no partial action. Paid runtime work is retained even on refusal/error.

Acquisition retains nominal old view-envelope/settling metadata and uses the
explicit sampled or whole-interval admission mode before physical execution,
MS integer sizing, `_imaging_request` storage admission, physical payload
power and a real onboard record. It never begins with a synthetic acquisition.
Contact delegates each supported constant integral source/profile cell to
`execute_contact_plan`. Fractional contact forcing discontinuities are
explicitly refused. Within each cell, panel incidence is calculated from the
held mount/attitude at its midpoint and declared piecewise constant for that
cell; existing exact bit/rate service times, partial transfers, protection and
custody remain authoritative. Source/cell/derived forcing bindings are saved
alongside the genuine ContactOutcomes. Product credit uses `assess_ms_product`
on actual acquisition and completing custody/service associations.

EPS capability, battery calendar/cycling damage, solar retention, conversion
loss heat and operating-node protection use unchanged owners. Routed served
load heat owns internal dissipation; supplied profile internal heat must be
zero. Radiation/sinks explicitly exclude those internal/conversion terms.
Mechanical storage subtracts only from ADCS routed heat; admission requires
ADCS retained fraction 1 at the declared bus node. Braking releases stored heat
and gives no battery regeneration. Other mode/harness physics are not inferred.

## Persistence and trust

`environment_mission_continuation` format 2 is additive, separate from the live
checkpoint schema. Save/load/continue occurs only at completed action
boundaries. The packet contains the original input document, checked context,
cursor, full scientific comparison data and cumulative RuntimeWork. The caller
must retain both expected input digest and exact packet SHA-256 externally.
A digest binds data; it is not an attestation or cryptographic authorization.
Decoder has an explicit immutable-input whitelist, exact fields/types, finite
size/depth and existing checkpoint manifest validation. Arbitrary result-type
names in saved scientific comparison data are never imported or deserialized.

Restore recomputes one fresh B38 result from the original anchor and privately
replays the finite completed prefix through the same physical/custody owners.
Full causal scientific bytes and context must match before a state is returned.
It does not republish prior deliveries. Previously paid work remains spent;
all reconstruction work is added and quota-checked. Runtime deltas are saved
separately. Tampered bindings, cursor, resets and foreign assembly/policy fail.
No mid-action restart or arbitrary cached enclosure checkpoint exists.

Scientific projection was defined before comparisons: input digest, complete
original-source result, checkpoint (all physical/custody/mission fields),
attitude, cursor, complete causal outcomes/forcing/cuts, acquired evidence,
consumed contacts and product assessment. Only cumulative runtime recomputation
work and process/timing observations are separate; no physical field is
removed to make a comparison pass. Fresh process equality is same-runtime
functional evidence, not a general cross-runtime bitwise promise.

## Demonstration and limitations

`python -B -m examples.m3_constructor_mission_demo --variant compact --output OUT`
executes the short 128..192 s synthetic program. `--write-input` and
`--write-assembly` export editable strict documents without numerical execution
when no output is requested. `--input` or `--assembly` consumes those documents.
`--checkpoint-output`, `--stop-after`, `--resume`, `--packet-sha256`,
`--input-digest` and `--work-output` expose the restart contract.
All output paths must be outside source repositories for review executions.

Both designs share a static spherical Earth, supplied TT epoch, original J2
trajectory, prescribed far Sun table, target/station, acquisition/deadline,
actuator/controller program, sampling and physical configuration. These are
ASSUMED test inputs, not KazEOSat coefficients. Only battery placements change.
The numerical builder mass and EPS capacity/generation are distinct declared
inputs; this example establishes no hardware sizing closure or robust winner.

Limits: sampled geometry/protection, nominal reduced EPS/thermal Euler steps,
prescribed forcing rather than thermal illumination/attitude heat deepening,
principal-y ideal wheel only, no RF/antenna link budget, station scheduling,
collision solver, full 3-axis attitude, dynamic harness, day/H5 campaign or
flight calibration. Combined qualification remains UNRESOLVED; B7 cause UNKNOWN.

B41 adds the separate continuous sphere/equator/held-camera contract in
M2_CONTINUOUS_MISSION_GEOMETRY.md. NORMAL activity only is admitted; no FDIR
recovery is inferred. Unsafe contacts refuse atomically; successful contact
terminal mode remains authoritative, and returned work is paid before refusal.
