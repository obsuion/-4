# Task 05E: bounded coupled battery/array design trade

This separate synthetic study asks whether explicitly executed attitude changes
and electrical distribution losses change feasible operations or delivered MS
products relative to a resource-only approximation of the **same feasible
designs**. An unchanged ordering or a tie is a legitimate result. The best
observed design is not a global optimum. Accepted Task 05C remains the principal
comparison; Task 05D remains a separately identified supplement. Neither their
program semantics nor their historical evidence is revised here. Full V5 is
still open.

This document declares methods and gates before the main study. Actual results,
run inventory, protocol/source hashes, figures and final test evidence belong
to the external `task05e-review` artifact set. A declared run is not a completed
run, and the tables below contain design inputs rather than measured outcomes.

## Component design and common constraints

The authoritative SOURCE/DERIVED/ASSUMED ledger is
[V5_DESIGN_TRADE_SOURCES.md](V5_DESIGN_TRADE_SOURCES.md). It records revisions,
locations, conflicts, consumers and integration limitations. The instrument is
the retained J-family MS reference. Its published 46 kg imager/electronics mass
is included in an assumed 70 kg, 0.8 by 0.8 by 1.0 m common core. This prevents
using an unrealistically small bus to amplify appendage inertia. Core mass
distribution, actuator operation and material/thermal coefficients are not
flight-calibrated inputs.

The design space is the Cartesian product of 2/4/6/8 BP8 packs and 2/4/6 complete
TSP assemblies. Every design must satisfy a 78 kg total ceiling, an eight-pack
reserved bay, at most two stowed assemblies on either x face, a 2.8 m deployed
span, and the declared current/voltage/routing rules. All twelve records are
exported, with all violated constraints. Catalog internal harness, hinges,
drive and mounting parts are counted once. Explicit external adaptors, pack
supports, regulator-equivalent banks, copper/return paths, connectors and
insulation add mass. The unused mass allowance remains spare mass.

The arrays are symmetric, rigid and locked, with body normals +z and deployment
along +/-x. Body y is the maneuver axis. Packs occupy actual symmetric x/z
positions in a separate battery bay. Imager/electronics reserved boxes, stowed
footprints and obstacle-clearing cable waypoints are explicit. The center of
mass and y-axis inertia follow component box moments and the parallel-axis
theorem. Uniform core/wing mass and projected cable mass distributions are
declared approximations; this is not a structural or deployment qualification.

Before operational scores, select the minimum and maximum feasible battery
count at each feasible array count. This produces:

| Design | Packs | Complete arrays | Working capacity, Wh | Reference array power, W |
|---|---:|---:|---:|---:|
| B2-A2 | 2 | 2 | 172 | 90 |
| B8-A2 | 8 | 2 | 688 | 90 |
| B2-A4 | 2 | 4 | 172 | 180 |
| B4-A4 | 4 | 4 | 344 | 180 |

These source-derived capacities and normal-incidence reference powers are not
predicted delivered power. The exported design table contains actual mass,
spare mass, placement, inertia, bay usage, routes, selected wire sections,
regulator banks and rejected alternatives.

## Electrical, attitude and thermal execution

Six separately conditioned strings represent each complete array; unequal
7s/8s strings are not directly paralleled. Actual fixed-wing normals and the
common Sun direction determine incidence. A declared 45 W net interface
reference is reduced by external string `I^2 R` losses and a separate assumed
0.95 regulator efficiency. The EPS scalar-incidence interface receives the
equivalent delivered power; diagnostics retain the geometric incidence and
each loss separately. Eclipse sets generation to zero. There is no free Sun
tracking while pointing at a target.

Wire gauges follow one ordered admissibility rule, with both conductors,
connector resistance/mass and installation lengths explicit. The regulated
load trunk solves the stable constant-power circuit equation; its loss is an
executed bus load. Short routes, excessive drop/current and invalid operating
points are rejected. The regulator equivalent is not certified P80/BP8/TSP
catalog compatibility. Existing 0.9 battery charge/discharge efficiencies apply
once under their accepted bus-input/bus-output conventions. Battery plug and
backplane loss is within that convention; no second cable loss is invented.

All designs use the same assumed one-axis wheel-equivalent technology:
0.02 N m torque, 0.2 N m s available momentum, 2 degrees/s maximum body rate,
`0.00034 kg m2` rotor inertia, and 5 s settling. For angular distance theta,
`alpha=tau/I` and `omega_cap=min(omega_rated,H/I)`. With
`theta_c=omega_cap^2/alpha`, motion takes `2*sqrt(theta/alpha)` when
`theta<=theta_c`, otherwise `theta/omega_cap+omega_cap/alpha`. Its elapsed
execution interval rounds upward to an integer second; the remaining fraction
is a physical rest interval with declared actuator demand. Settling executes
separately. Zero-angle transitions require no invented motion.

Motion/settling draw an assumed constant 25 W and holding draws 0.5 W, in
addition to the 12 W baseline. These are study assumptions, not demonstrated
hardware power bounds. Body plus rotor kinetic storage is removed from routed
heat while accelerating and restored while braking. Braking does not charge
the battery. The executor rejects kinetic growth that the declared electrical
draw cannot fund. Source bounds and the older/current wheel-power distinction
are preserved in the source ledger.

The existing EPS, battery-loss, degradation, thermal and protection owners
perform each physical subinterval. The only shared-owner extension is an
optional signed internal-heat adjustment for kinetic storage/release; its
default path retains legacy arithmetic. Bus heat capacity includes common bus,
root parts, mounts, distribution and external wiring; battery and payload
capacity use their respective masses. Specific heats are assumed 900/900/700
J/(kg K) for bus/battery/payload. Emissivity, emitting areas, a 280 K sink and
the absence of absorbed environmental heating remain explicit assumptions.
PV wiring/converter heat is exported separately from the three-node thermal
network. Load-wire and actuator heat enter the bus once; battery conversion
heat retains its existing owner. No panel-temperature model is claimed.

## Controller, products and continuation

The opt-in `TradeSpec` version-1 wrapper builds on unchanged accepted product,
acquisition, contact and protected physical executors. It does not reinterpret
an archived version-7 campaign. The same received-knowledge controller orders
requests by closing window, then accepted priority/deadline/identity rank.
All six requests are received at origin; idealized exact resource/temperature
telemetry is available at completed boundaries. No score truth informs choices.

Forecast and actual execution share the same maneuver/settle/hold/acquire
macro. A forecast-unavailable request is explicitly rejected. A physically
attempted denied motion becomes a same-duration protected hold at the original
attitude. Acquisition begins only after paid motion and settling, inside its
actual window. Its accepted prior-direction check receives the settled current
direction; a changed timing table is not used as evidence of physical turning.
Contact pointing also requires a paid return to zero angle. Protected contact
service and remaining idle time use accepted duration/custody semantics.
The unchanged contact owner requires one shared baseline: the adapter puts
idle-trunk wire loss there and adds the incremental transmit-trunk loss to the
transmitter's electrical demand. Both route to the same bus heat owner;
diagnostics separate useful mode power and wiring loss. This avoids changing
legacy contact semantics or paying transmit wiring loss while idling.

Integer MS sizing, acquired records, received bits and product credit retain
their accepted owners. Failed acquisition creates no successful product credit;
delivery requires actual receipt by the inclusive deadline. The fixed reference
sampling/product approximation is retained across +/-30-degree pointings.
This does not validate off-nadir sampling, radiometry, terrain coverage or a
full optical geometry model.

Continuation binds the explicit specification, full derived design record,
immutable inputs and embedded program. It preserves paid-event history,
observed attitude, attempts/rejections and a schema-5 physical checkpoint.
Restore reconstructs inputs and deterministically replays completed advances,
then compares history, feedback, attitude and checkpoint. Schema 5 and archived
codecs are unchanged; this envelope is a separate new-study contract. Restart
evidence must include a fresh process at a completed physical-action boundary.

## Frozen workloads and ablation

Both workloads use six distinct 10 by 30 km products, 60 s acquisitions,
70 s windows starting at `60+i*cadence` seconds, and alternating +30/-30-degree
directions. Priorities are 3,2,1,3,2,1, giving denominator 12. All configurations
share a 1600 s horizon, eclipse `[0,30)`, a fixed Sun at +20 degrees, 25% initial
working battery capacity, contact `[1450,1490)`, and deadline 1550 s.

Cadences are selected analytically before outcomes. A 60 s exposure plus a
70 s reference allowance for a 60-degree slew and settling defines the closer
130 s cadence. The relaxed 200 s cadence adds another 70 s allowance. Around
the declared common-core inertia, the reference maneuver is approximately
65 s including settling; 70 s is a rounded planning allowance, not a measured
feasibility result for every full design. No cadence is searched for a desired
ranking. Acquisitions/contacts occur after eclipse; holds split its boundary.
Initial motion can cross the eclipse boundary. Moving profiles use midpoint
forcing on their uniform rational mesh, without exact event location at that
jump. Refinement measures the resulting quadrature difference; it must not be
described as exact eclipse-boundary integration.

For each selected design:

- **FULL** uses component-derived inertia, fixed-wing illumination and the
  modeled PV/load wiring losses.
- **RESOURCE_ONLY** uses common-core reference inertia and ideal PV/load
  wiring. It still pays its reference maneuver/settle/hold durations, motor
  electricity, body-dependent illumination and the same regulator/battery
  efficiencies. This is an analytical counterfactual, not another real design.

Both variants retain the same full-design feasibility screen, component mass,
capacity, requests, controller, knowledge and scoring. No extra feasible designs
or favorable mass budget are introduced for the ablation.

## Matrix, pilots and budget rule

The nominal matrix has 32 cases: four designs by two workloads by two variants
by numerical levels L1/L2. Before inspecting main-study rankings, timing pilots
are B8-A2/close/FULL/L2 and B2-A4/relaxed/FULL/L2. Matching pilots may be reused
only with exact source/input identity and completed-result evidence. Preserve
failed invocations separately; a failed/incomplete run is not a zero score.

Use at most two case workers. Before main outcomes, freeze measured pilot
durations, the explicit runtime-projection formula, source hashes and protocol.
For the normal 64-case nominal-plus-sensitivity study, projected remaining
seconds equal `max(two completed pilot durations)*(64-2)/2*1.5`, with two
workers and a 1.5 contingency factor. The subtraction is allowed only for
completed pilots with exact specification and production-source hash matches.
Raw pilot outputs are retained without inspecting rankings before the freeze.
If projected nominal main plus sensitivity work exceeds 3600 wall seconds,
the predeclared fallback retains B2-A2, B8-A2 and B2-A4: 24 balanced nominal
cases with the same essential model. Report B4-A4 as omitted by the budget rule.
The fallback projection substitutes `56-number_of_matching_pilots` for the
remaining-run count; sensitivities remain the same 32 cases. If that projection
still exceeds 3600 s, report budget INCOMPLETE rather than shrinking essential
physics.
No selective workload/variant/resolution removal is allowed. If essential
physics or required verification cannot be completed, report INCOMPLETE.
The three-hour delivery target is a work budget, not an organizer cutoff.

Predeclared sensitivity is 32 additional fine-only cases: B8-A2 and B2-A4,
close workload, both variants, and eight one-factor endpoints. Vary only one
factor from nominal per case: core-inertia scale 0.75/1.25; torque
0.015/0.025 N m; harness-resistivity multiplier 0.5/2; mode-power factor
0.5/1.5. Recompute gauge admission when resistivity changes. No per-scenario
retuning or newly chosen favorable design follows the observed outcomes.

A separate predeclared **layout-only core-mass sensitivity** enumerates all
twelve allocations at common core masses 68 and 72 kg, retaining the 78 kg
ceiling and the same component placements. Its 24 records expose changes in
structural feasibility; they are not additional mission runs or a reselection
of the nominal design list. `mass-screen.json` is generated before the main
protocol freeze and its SHA-256 is bound into that protocol. The operational
inertia-scale sensitivity above remains distinct from this mass screen.

## Verification and interpretation gates

Motion/hold L1/L2 use two/four subdivisions of a base partition whose intervals
are no longer than 5 s. Acquisition/contact retain their accepted integration
owners. Physical action durations are unchanged between levels. The nominal
matrix supplies 16 refinement pairs, or 12 under the balanced fallback.

Check exact request/credit identities and phase/decision evidence; compare
physical samples only at shared exact rational times. At those times require
absolute battery differences no greater than 0.001 times the design's working
capacity in Wh and corresponding temperatures within 0.1 K. Report any action,
completion-time or protection diagnostic differences separately. Changed action
sequences or rankings are unresolved decision evidence, even if scalar bounds
pass. These are predeclared decision screens, not rigorous global error bounds,
continuous safety certification or validation of unobserved intermediate times.

Analytic checks cover component mass/COM/inertia, triangular/trapezoidal timing,
torque/rate/momentum caps, zero angle, independent circuit/voltage calculations,
source-to-load balance, real maneuver energy/heat, window boundaries, forbidden
installations and denied-action rollback. Require source-bound focused and
affected neighboring tests, one final full regression for changed production,
and fresh-process continuation equality. Historical 7290-pass evidence covers
only unchanged prior production; it cannot replace this gate.

Report priority-weighted delivery, every product's acquisition/receipt and exact
completion, actual phase durations, generated/served/curtailed energy, actuator
and harness losses, reserve, active constraints and thermal extrema. Preserve
ties. Let R be the set maximizing RESOURCE_ONLY credit; selection-loss range
is `[best_FULL-max(FULL over R), best_FULL-min(FULL over R)]`. Secondary metrics
explain ties without silently changing the primary preference rule. If an
effect disappears within uncertainty, say so.

Costs remain parametric. For any pair, break-even is
`sum((coefficient_A-coefficient_B)*unknown_unit_cost)=0`, using the exported
pack/array/regulator/mount/harness coefficients. No prices, equal-dollar designs
or economic optimum are asserted.

## Evidence delivery and scope boundary

The external `task05e-review` package must include the frozen protocol, complete
feasible/rejected table, all case/result identities, pilot reuse provenance,
raw results, numerical/sensitivity/restart/test evidence, failed/missing run
inventory, source/candidate hashes, candidate patch and reproduction commands.
Use its authoritative README/reproduction script with `PYTHONUTF8=1`,
`PYTHONDONTWRITEBYTECODE=1`, Python `-B`, disabled pytest cache and external TEMP
outputs. Two figures show the design/resource trade and FULL versus ablation
outcomes. The external Methods/Results/Limitations draft reports measured
results only; no result is implied by this predeclared contract.

Preserve accepted 05C/05D archives and historical protocols. Do not write SIDe
manuscript artifacts, stage/commit, tag, push or submit during implementation.
J2 visibility, propulsion, OBC processing, flexible wings, detailed array
thermal physics, long-horizon qualification and full-V5 completion remain out
of scope. Synthetic forcing, assumed mode power and simplified protection
sampling establish neither flight performance nor continuous safety.
