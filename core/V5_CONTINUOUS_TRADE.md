# Task 05F-A: continuous coupled allocation study contract

This is the separate, opt-in implementation and readiness contract for an
event-driven continuation of the accepted Task 05E component trade. The
candidate is unaccepted, unstaged and uncommitted. This slice does not authorize
the production month campaign. Accepted 05C/05D/05E contracts, artifacts and
manuscript files remain their existing authorities.

The primary question is whether more storage or more generation sustains timely
delivered products through repeated demand, illumination and recovery cycles,
under the retained coupled electrical, attitude, thermal and protection model.
It is not an EPS-only comparison: battery charging heat can constrain the
generation-rich design even when payload average heat is admissible. Ties,
inactive constraints and protection-limited results remain valid findings.

## Fixed physical scope and source authority

The accepted [component/layout ledger](V5_DESIGN_TRADE_SOURCES.md) and
[bounded study contract](V5_DESIGN_TRADE.md) remain the source, derivation and
assumption authorities. No new hardware, orbit-visibility model, numerical
engine, actuator, thermal node, hydraulic mechanism, propulsion, processing,
flexible structure or deployment dynamics is introduced.

The primary pair was chosen before new operational scores:

| Design | Working capacity | Initial energy (50%) | Reference array power | Derived mass | Body y inertia |
|---|---:|---:|---:|---:|---:|
| B8-A2 | 688 Wh | 344 Wh | 90 W | 76.6981248 kg | 10.84203876946 kg m2 |
| B4-A4 | 344 Wh | 172 Wh | 180 W | 77.2736576 kg | 11.97429960593 kg m2 |

An A unit is one complete approximately 45 W TSP assembly containing three
panel sections. These are assumed whole-spacecraft allocations, not measured
flight configurations, equal actual masses or equal-dollar designs. The 78 kg,
eight-pack and two-assemblies-per-side screen is unchanged. The other feasible
designs B2-A2/B4-A2/B6-A2/B2-A4 are optional extensions. Rejected six-array
layouts are not reinstated.

Retain the accepted 12 W baseline, 0.5 W attitude holding, 25 W motion/settling,
93 W imaging increment and 93 W transmitter increment. Retain 0.02 N m torque,
0.2 N m s momentum, 2 degrees/s rated rate, 0.00034 kg m2 rotor inertia and
5 s settling. External wire losses and the 0.95 solar regulator efficiency
apply exactly once; battery charge/discharge efficiencies are each 0.9 under
their existing bus-input/bus-output meanings. Mechanical kinetic energy is
stored/released through the existing paid macro; braking does not recharge
the battery. Hardware health stays fixed: calendar/cycling coefficients zero,
no solar-ageing forcing. Throughput is not a calibrated life prediction.

All nodes start at 293.15 K with zero-angle settled attitude, empty onboard
storage and no delivered products. The initial states have different absolute
energy by design. There is no warm-up, reset or unreported discarded interval.

## Pre-score workload and environment declaration

The primary workload is **regular**. **Burst/recovery** is retained as an
optional secondary workload with the same offered product requirements and
priority weights. The regular workload isolates repeated resource availability
from a tight alternating-slew feasibility constraint. This choice was made
using the independent budgets below, before comparative mission scores.

Both workloads use the following common versioned inputs:

| Quantity | Declaration |
|---|---|
| Full physical horizon | 2,592,000 s (30 continuous days; 480 cycles) |
| Synthetic cycle | 5,400 s; illuminated phase [0,3600), dark phase [3600,5400) |
| Sun | Fixed common-frame +70 degrees; arrays rigidly locked to body |
| Requests | Six distinct requests per cycle, all released at that cycle's origin |
| Regular starts | Cycle origin +120+600i s, i=0,...,5 |
| Burst starts | Cycle origin +120+130i s, i=0,...,5 |
| Window / exposure | 70 s acquisition window; 60 s physical acquisition |
| Directions | +30,-30,+30,-30,+30,-30 degrees |
| Priorities | 3,2,1,3,2,1; offered denominator 12 per cycle |
| Products | Six distinct 10 by 30 km MS products per cycle; unchanged accepted integer sizing |
| Contact | Cycle origin +[3420,3500), common adequate contact for both workloads |
| Delivery deadline | Cycle origin +3500 s; existing inclusive completion rule |
| Forecast horizon | One cycle, with only requests already released to the controller |

The +70-degree Sun is a newly declared synthetic incidence family, selected
from a pre-score physical balance because inherited +20-degree illumination
provides a large average energy surplus for both primary designs. It is not
geographic, seasonal, J2, attitude-control or visibility validation. It does
not change nominal array reference power, cooling, safety limits or mode
power. Inherited +20 degrees is retained in the independent analytical evidence
as the weak-energy-contrast reference; it is not silently mixed into +70-degree
pilot attribution. No illumination search follows observed mission rankings.

The controller retains earliest-closing-window order, then accepted priority,
deadline and identity ordering. It uses received release knowledge and exact
boundary telemetry, with the existing paid forecast/actual maneuver macro.
It turns toward the next selected published target immediately and holds that
attitude until acquisition; it does not implicitly return to zero or track
the Sun between requests. After all attempts in the current cycle, it pays
the return to zero for contact/recovery. Unpublished future-cycle requests
are not forecast inputs. A forecast clone cannot modify actual state.

IDs include the cycle and opportunity so a repeated footprint is a new
physical acquisition, request and product. All offered requests remain in
their denominator even if rejected, expired, missed, undelivered or late.
Late/live records are retained and remain eligible for causally ordered
contact service; a late receipt earns no on-time product credit. Delivered
truth and incomplete transfers are never erased to reduce history size.
No optimizer or optimality claim is introduced. The accepted contact owner
stops service at the first denied record and physically idles for the rest of
that contact; it does not retry within the same contact after recovery. Later
contacts can revisit the retained backlog.

Time-dependent forcing is right-continuous on half-open intervals. At a
light-to-dark endpoint the following physical interval uses darkness; at
cycle origin it uses illumination. Hold and motion profiles split at forcing
discontinuities; contact segments cut before the next discontinuity. Every
supported 60 s acquisition fits wholly inside one illuminated interval. An
exposure crossing an illumination boundary is rejected; internally variable
illumination during an acquisition is not implemented in this bounded domain.
Deadline credit retains the accepted inclusive completion convention, which
is distinct from the half-open physical forcing convention.

Pilot summaries score the completed observation interval [0,now). At an exact
cycle endpoint the next cycle's requests may be published to current knowledge,
but enter the following observation interval's offered denominator. Thus the
initial zero-duration summary offers zero products, a completed 5400 s summary
offers six, and a completed 24-hour summary offers 96. This endpoint convention
does not drop demand from any elapsed physical interval.

## Independent energy and thermal budget

The external `task05fa-budget-20260924` evidence contains an independent
engineering calculation, not a campaign, controller score, qualification
pilot or month result. It imports the accepted hardware derivation only;
the circuit, slew trajectory, net battery balance and scalar thermal ODE are
evaluated separately. No operational protection is applied in these screens.
Accepted component/source values are reused without a new literature search.

For a phase at geometric incidence c=max(0,cos(theta-70 degrees)), the
independent calculation applies the accepted six conditioned strings per
assembly, external I-squared-R loss, 0.95 regulator efficiency, and stable
28 V constant-power load-trunk root. Battery change is the time integral of
0.9 times positive bus surplus, or bus deficit divided by 0.9. Thus a zero
net bus balance is not a zero net storage balance when cycling losses exist.

Each integer product contains 426,241,440 bits. Six products contain
2,557,448,640 bits (0.31968108 decimal GB), versus the retained 6 GB storage
capacity. At the retained 160,000,000 bit/s useful rate they require
15.984054 s of transmitter time. The budget conservatively uses 16 s. The
80 s common contact can carry 12.8 Gbit if physically available; communications
and finite storage remain active constraints even though their nominal
capacity is adequate. Roughly 18.8 full cycles of completely undrained demand
would fill storage, so backlog cannot be dismissed for a long failed case.

The regular workload's first and final 30-degree motions take 39/42 rounded
seconds for B8-A2/B4-A4; each 60-degree alternating motion takes 67/73 s.
Including seven 5 s settling intervals gives 448/484 s of motion/settling
per fully served cycle. These paid differences remain in the balance.

| Regular, +70-degree Sun, full offered execution | B8-A2 | B4-A4 |
|---|---:|---:|
| Solar bus energy per cycle | 28.405 Wh | 56.801 Wh |
| Electrical load per cycle, including load wire | 31.573 Wh | 31.819 Wh |
| Orbit-average solar bus power | 18.937 W | 37.867 W |
| Orbit-average load | 21.049 W | 21.212 W |
| Unconstrained battery change per cycle | -7.205 Wh | +18.664 Wh |
| Dark-only battery withdrawal | 6.948 Wh | 6.948 Wh |
| Mean bus heat | 14.849 W | 15.012 W |
| Mean battery heat before charge saturation | 2.692 W | 4.212 W |

These are prospective open-loop balances before denials, capacity curtailment
or altered action choices. They do not predict product credit. Held at zero,
the same solar assumptions give 19.477/38.955 W orbit-average generation;
the actual preturn/hold schedule explains the different values in the table.
At inherited +20 degrees, the same regular budget gives approximately
+32.187/+95.610 Wh per cycle before saturation, so sustained energy scarcity
is weak for both designs. Initial charging heat can still be important.

The dark withdrawal is small compared with either initial reserve. B8-A2's
issue is cumulative cycle imbalance: 344/7.205 is about 47.7 cycles or 71.6 h
if all offered actions remain possible. This makes the required 72-hour pilot
informative near the predicted onset of low-energy operation. It does not
justify multiplying a short result into a month or assigning a mission score
from the budget.

The payload capacity is 46*700=32,200 J/K. With emissivity 0.2, area 0.2 m2,
280 K sink and no links, radiation at 320 K removes 9.841955 W. The offered
360/5400=6.667% duty creates 6.2 W average payload heat, below the stationary
9.84/93 approximately 10.6% ceiling-duty estimate. The six images add at most
1.040 K adiabatically. An independent scalar periodic ODE screen gives
approximately 306.75--307.20 K for regular timing and 306.53--307.43 K for
the ideal offered burst. These values support thermal recovery under this
specific boundary model; they are not measured flight duty limits or proof
of the complete protected mission's safety.

Bus radiation at 320 K is 19.684 W. The above approximately 15 W mean bus
heat corresponds to mean-equilibrium estimates near 311.5--311.8 K. Brief
motion/communication heat and protected trajectories still require the actual
numerical pilot.

**Battery charging heat is a material constraint.** B4-A4's battery area is
0.08 m2 and heat capacity is 1,749.6 J/K. Its 320 K radiative removal is only
3.937 W, below the 4.212 W unconstrained mean charging/discharging heat.
A separate finite-capacity 24-hour open-loop screen, starting at 172 Wh and
293.15 K, crosses 320 K near 29,479 s (8.19 h), peaks near 322.52 K as the
battery first fills near 45,642 s (12.68 h), and then cools as excess generation
is curtailed. The analogous B8-A2 screen peaks near 295.94 K in the battery.
The accepted protection owner can change actions before those unprotected
values occur. The actual pilot must retain and report that feedback; no
cooling, threshold, efficiency or initial-state retuning is justified by this
screen. The result is a coupled energy/thermal allocation question.

Burst timing is intentionally a second physical question. B8-A2's 60 s
acquisition plus 72 s paid turn/settle accumulates 2 s delay per alternating
request at 130 s cadence; the sixth acquisition uses the full 10 s window
slack. B4-A4's corresponding 138 s produces 8 s delay per transition, so the
third consecutive alternating acquisition already needs 16 s slack and cannot
fit a 70 s window. Skips can change subsequent geometry and generation. This
independent timing result is why burst is secondary, not a workload chosen
to enforce a desired ranking. Its offered denominator remains unchanged.

## Reuse, continuity and numerical qualification

Use a thin new versioned coordinator around the accepted design, physical,
acquisition, custody and contact owners. Do not route through the legacy
hourly simulator, empty engine hooks, bounded replay wrapper, or a removed
4096-substep guard. Existing archived program contracts keep their meanings.
Shared-owner changes must be opt-in, justified and covered by adjacent checks.

The new continuation binds validated immutable world/program inputs, source
identity, numerical policy, live physical checkpoint, attitude, controller
knowledge, request attempts, partial custody, delivered truth and cumulative
accounting. Normal advancement must not replay completed history. Internal
chunks share one continuous clock, battery, temperatures and custody; a day
boundary does not create a new run. A changed input/source/numerical identity
prevents claims that a shorter pilot is an eligible extension of another.

Exact restart is scoped to the same completed boundary followed by the same
declared stop/chunk schedule, on the same bound runtime. Standard readiness
stops are cycle boundaries; wall-budget stops occur between completed advances.
The partial-transfer fixture declares 1 s contact chunks in its immutable spec.
An arbitrary `--debug-phase-stop` can introduce an additional contact/hold
partition and change contact identities or sampled trajectories. Equivalence
to an uninterrupted default partition is not claimed for that debug route.
Checkpoint and stream hashes detect changes but are not authentication or a
proof of historical causality; independent energy/custody audits are separate.

The implemented nominal policy has maximum physical dt 60 s for stationary
holds, 5 s for motion/settling, 15 s for acquisitions and 20 s for contacts;
actual exact subdivisions may be shorter. The finer policy halves each
maximum. Event splits take precedence. Sampling frequency is a separate
output choice and cannot replace physical integration. These step sizes are
unqualified until the specified comparisons complete; integration level alone
does not define a maximum dt for arbitrary action duration.

Default contact chunks are the same 20 s physical intervals in both policies;
the contact owner uses IntegrationPolicy(0) for nominal and (1) for finer
execution, so refinement changes numerical substeps without changing service
opportunities or the contact-retry rule. Shorter explicitly declared contact
chunks support partial-custody restart probes and have their own input identity.

Before examining refinement differences, retain the accepted screens:
absolute shared-boundary energy differences at most 0.001 of working capacity
(0.688 Wh / 0.344 Wh), and corresponding temperatures within 0.1 K. Request,
delivery-credit, action and denial-reason identities should match exactly;
completion times should match. Any changed threshold-dependent action,
completion time or reason is reported separately as unresolved decision
sensitivity even if scalar bounds pass. No global error bound or continuous
safety claim follows from sampled agreement. Both complete 30-day primary
cases later require their own full-horizon finer-policy comparisons.

## Readiness evidence and completion boundary

The minimum required evidence in this slice is:

- A short multi-cycle boundary case, partial downlink across a checkpoint,
  fresh-process restore versus uninterrupted execution, forcing change during
  an action, denied/replanned action, and independent energy/custody checks.
- 24-hour technical pilots for both primary designs under regular FULL and
  a 72-hour B8-A2 scaling pilot with real accumulated products and custody.
- Finer-policy comparisons for both full 24-hour pilots, with physical,
  identity, completion-time, action and reason checks under the declared screens.
- Measured wall time, peak resident memory, physical substeps, event/request
  counts, output bytes and history-growth behavior. Incomplete pilots are
  explicitly incomplete; standby-only or horizon-linear extrapolation is
  insufficient evidence of mission scaling.
- Focused and adjacent checks, then one full regression on the frozen final
  production/test bytes. Historical passed suites do not cover this candidate.
  Passed full regression is not repeated solely for packaging.
- Streamed, hash-bound request/event/custody/accounting evidence, selected
  trace windows, input/source identities, raw outputs, exact reproduction
  commands, failed/incomplete inventory, candidate patch and review ZIP.

Retained ground-delivery history remains authoritative. Streamed diagnostics
may be evicted, but live or delivered truth cannot be discarded. A compact
ledger is justified only by a measured bottleneck and its added restart and
identity obligations. Runtime forecasts must use measured growth and explicit
reserve; the six-hour planning budget is not a promise or a venue deadline.

The later minimum month result is the primary hardware pair under the one
declared primary workload, plus both full-horizon finer-policy comparisons.
The second workload, RESOURCE_ONLY controls and other four designs are optional
extensions subject to measured runtime and independent review. Any omitted
extension is listed. Without new ablations there is no new month-scale claim
about FULL versus RESOURCE_ONLY. RESOURCE_ONLY, if run, retains common-core
inertia, ideal external wires, paid reference turns and all remaining common
power/thermal constraints; it is an analytical counterfactual.

Later reporting includes all time from zero, a predeclared final-week window
[1,987,200,2,592,000] s and initial-SOC sensitivities of 25 and 75 percent of
each design's own working capacity, around the 50 percent primary condition.
Initial temperatures and the complete workload remain common. These endpoints
are declared before the readiness comparisons; no sensitivity execution or
result is implied by this readiness contract.

Task05F-B may start only after independent review of the concrete candidate
and readiness evidence. If a qualified month pair does not fit the remaining
budget, accepted 05E remains the article baseline and all new pilots remain
preliminary engineering evidence. No commit, staging, tagging, push,
publication, manuscript edit or month-wide campaign is part of this slice.
