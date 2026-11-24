# Task 03B: sampled onboard protection and physical standby

This is a bounded operational policy for comparison of the twelve constrained
hardware architectures under common policy and conditions. It is not a ground
mission controller, spacecraft-calibrated FDIR, reliability model or completion
of V5. Task 04 is outside scope.

## Existing decisions and explicit model assumptions

D008/D009 separate immutable configuration, onboard truth and ground belief;
onboard protection can observe truth, ground planning cannot. D028 forbids
causal diagnostics. D029 separates activity from FDIR regime. D063 forbids
implicit telemetry refresh. D065 permits numerical integration with unmet
electrical demand. `FlightRulesConfig` still identifies rules; its ID alone
does not implement the new policy.

Task 03B adds explicit, content-bound `ProtectionPolicy` assumptions:

- Perfect observation of current onboard temperatures/energy/capability at
  completed boundaries, and only explicitly supplied current-interval inputs.
- Inclusive existing operating and survival limits in `ThermalNodeConfig`.
  There are no new numerical thresholds and no reserve percentage.
- Imaging requires at least configured bus, battery and payload nodes;
  downlink requires at least bus, battery and the explicitly mapped transmitter
  node; standby requires at least bus and battery. Extra dependencies are
  explicit. Empty, duplicate, unknown and incomplete bindings fail closed.
- Communications has no dedicated legacy thermal role. Its node and binding
  rationale are required, independently of heat routing. The demonstration
  explicitly assumes a shared bus/transmitter temperature.
- Every declared standby component demand is essential. Standby demand is one
  `PowerLoadBreakdown`, not an additional load added to the mission demand.
  Payload, communications and propulsion must be zero, total demand positive.
  No telemetry functionality is inferred from an OBC/bus load being supplied.
- The complete explicit component service order allocates the single EPS
  served-power result during deficient standby. This load-shedding assumption
  affects heat. All-standby essential deficit is exactly EPS `unmet_load_w`.
  Demand is never counted twice; no allocation is inferred from aggregate
  mission-action power. Existing exact routing reconciliation remains in force;
  unrepresentable ledger arithmetic raises instead of relaxing its checks.
- Recovery is reevaluation at the next admissible sampled boundary. No latch,
  dwell timer, hysteresis, beacon schedule, redundancy switching or damage law.

Policy rationale, communications rationale, standby watts/forcing/rationale,
all action inputs and existing parameter provenance are bound by experiment
content. Real mission role mappings, essential demands, thermal coefficients
and any future reserve/recovery calibration require independent author input.
The synthetic coefficients are not KazEOSat measurements.

### Task 03B-R1 standby allocation arithmetic

`_standby_service_ledger` is local to `operational_protection.py`. It consumes
the ONE standby EPS result; it neither recalculates EPS nor changes requested
loads, supply limits, unmet power or essential-power admission. At full service
(`eps.battery.unmet_load_w == 0`), every original normalized demand is served
unchanged. Repeated subtraction must not fabricate a last-component shortage.

At a deficit, exact rational arithmetic on the admitted binary numeric values
determines the complete higher-priority prefix and one partial component.
Lower-priority components receive zero. The partial starts at the nearest
binary64 value of the exact residual (Python's ties-to-even conversion), capped
at the largest binary64 value not exceeding its demand. Its aggregate is tested
in `ElectricalLoadComponent` order using the unchanged routing owner's checked
sequential accumulator. This is deliberately distinct from the compensated
builtin `sum` used by `PowerLoadBreakdown.total_load_w` in Python 3.14.

If that nearest residual does not reconcile, the local helper searches the
monotonically ordered nonnegative binary64 encodings toward the EPS total.
It selects the nearest edge of the exactly reconciling plateau, with at most
64 bisection iterations. Only the partial component can change; the full
priority prefix and zero suffix cannot. Every served component remains between
zero and its original demand. The existing thermal owner then independently
validates the complete ledger, requested total, exact served total and heat.
Heat derives solely from that accepted ledger. There is no tolerance, chosen
decimal precision, extra power budget or altered shedding priority.

The equality contract is the existing normalized floating-point accounting,
not equality of exact real sums: the exact sum of stored binary components can
differ from the EPS value by sequential addition rounding. Reconciliation may
move the partial in either direction within the owner's rounding plateau; it
does not change EPS energy or count the discrepancy as additional supply.
The correctly rounded residual is preferred over maximizing the plateau's
served value. This avoids an arbitrary representational power preference.

Two explicit numerical boundaries remain. Full demand must itself pass the
old exact aggregate check: for example `.1/.2/.3 W` has EPS total `.6 W` but
sequential routing total `.6000000000000001 W`; full service cannot both preserve
those demands and satisfy that owner. At a deficit, if no binary64 partial
within `[0, demand]` makes the fixed exact-priority prefix reconcile, execution
rejects atomically. The monotone search establishes that boundary rather than
assuming it after one unsuccessful subtraction. It does not reduce already
full higher-priority loads or feed lower priorities to conceal a rounding gap.
These cases are distinct from the four review reproductions, whose independent
ledgers are accepted by the unchanged thermal owner and now execute.

## Transition table and state ownership

| Current observation / prediction | Selection | Activity / FDIR | Recovery and persistence |
| --- | --- | --- | --- |
| Action required nodes within inclusive operating limits at start and predicted end; existing geometry/storage/electrical authorization succeeds; standby essential service and required-node prediction admissible | Requested imaging or coupled downlink | IMAGING or DOWNLINK / NORMAL | Next request reevaluates; successful acquisition alone changes prior-attitude memory |
| Required action node outside operating range at start or predicted end, insufficient action power, unavailable acquisition/storage, or missing onboard record | Explicit physical standby | STANDBY / BACKUP when core service is admissible | No permanent latch; request/forcing interval is consumed even on denial |
| Essential standby demand unmet, or required standby node outside operating limits at start or predicted standby end | Physical standby still integrated | SAFE / BACKUP | Time advance does not assert electronics/mission functionality; next admissible sampled request can recover |
| Explicit standby request with admissible essential supply and required nodes | Physical standby | STANDBY / NORMAL | Can recover from BACKUP without acquiring/transmitting |
| Actual sampled survival excursion on any node | Separate start/end observation of the selected transition | No automatic extra state or death | No inferred crossing time, duration or post-survival damage |
| Malformed inputs, unowned regime, invalid physical proposal or late validation failure | No external commit | Original state retained | Error, not an availability denial |

`OperationalMode` owns activity; `FDIRState.NORMAL/BACKUP` owns this policy's
normal/reduced-operation regime. BACKUP here does not assert alternate hardware.
This boundary accepts only SAFE/STANDBY/IMAGING/DOWNLINK activity and
NORMAL/BACKUP FDIR; other regimes raise rather than being silently cleared.
Accepted plan/authority and qualifying-contact timestamps are untouched.

`critical_energy_since_seconds` means the first sampled request-start boundary
at which the current full-interval standby proposal finds unmet essential power,
retained across consecutive sampled deficits. It clears on an admissible
essential-power sample, even if another thermal/mission denial remains.
This is a supply test (energy, generation and discharge power), not an empty
battery test or an exact physical crossing instant. Electrical recovery is
independent of generic mission-action power insufficiency.

Existing onboard fields persist in schema 5. Ground knowledge stays unchanged:
no new telemetry path is claimed. Diagnostics only record the existing completed
step count; they neither trigger nor clear protection.

## Protected boundary and transactional composition

Public APIs in `ops_sim.v5.operational_protection`:

- `evaluate_action_availability(context, previous_execution, request, *, policy)`
  returns transient read-only evidence. Repeating it changes no timers,
  diagnostics, context, data or external memory.
- `execute_protected_request(context, previous_execution, request, *, policy)`
  accepts explicit `ProtectedRequest(ImagingAction | CoupledDownlinkAction |
  StandbyAction, StandbyInputs)` and returns `ProtectedStepResult`.

Both require complete policy and standby inputs. Missing inputs never select
an unprotected execution path. Downlink missing onboard data is a valid
unavailable request here; the operational script additionally rejects a record
reference with no preceding producer. Existing low-level selection errors are
unchanged.

A current-step imaging request that cannot yet satisfy the existing ADCS
readiness calculation is unavailable and consumes standby here. A wrong-step
request, duplicate acquisition identity or future-dated previous acquisition
is malformed and raises. This does not reinterpret low-level imaging errors.

Private checkpoint-restored proposals reuse `SimulationEngine` transactions:
imaging-to-storage and Task 03A downlink propose complete action endpoints.
Standby computes EPS once, allocates served components, routes their heat,
computes existing EPS/thermal coupling and invokes the shared physical completion
owner for throughput, nonzero ageing, solar degradation and capacity
reconciliation. Conversion losses enter thermal coupling once; reconciliation
loss is not heat. No new EPS, thermal integrator or degradation law is added.

Start/end operating admission checks the same completed mission proposal that
will be committed if accepted. An unavailable mission proposal is discarded;
standby starts from the original boundary. Protection updates, selected result,
completed context and lossless schema-5 representation are validated before one
external engine commit. Private proposal calculations are not extra elapsed
intervals. A valid denial advances clock and completed-step count exactly once.
Passive thermal evolution continues outside operating/survival ranges.

Historical `SimulationEngine.step`, `step_imaging`, `step_imaging_to_storage`,
`step_downlink`, `step_coupled_downlink` remain lower-level kernels with their
original meanings. In particular Task 03A electrical denial still does not
advance time, and legacy downlink remains data-only. Only the new protected
boundary and operational version-3 executor enforce Task 03B policy.

## Sampling limitation

Admission is nominal current-state / completed-endpoint prediction for the
existing fixed-step Euler model. It proves neither absence of an interior
temperature excursion nor continuous-time safety. No substeps, interpolated
crossings, temperature clamps or future common-world knowledge are introduced.
Discarded predicted violations are availability evidence, not actual survival
observations. Actual survival checks include every configured node at the
start and end of the selected interval; equality is within range. Survival
observations alone create no persistent damage. Unsupported post-survival
damage remains open.

Mission and standby interval forcing are explicit separately. They may describe
different declared operational assumptions; no attitude-dependent forcing model
is inferred from the switch. The demonstration labels its differing mission
payload heat and standby heat explicitly.

## Version-3 outcome continuation and integrity

`ops_sim.v5.operational_continuation` provides `OperationalProgram(version=3)`,
`OperationalMemory`, `OperationalState` and `advance_operational_continuation`.
It is a distinct type; old `ContinuationProgram` versions 1/2 retain their
schemas and reject version 3. A maximum of 128 fixed-step requests is supported.
Every request has an explicit fallback. There are no queues, RNG, event
processing, replanning or rolling-horizon controller.

Immutable program origin checkpoint and prior successful acquisition define
the experiment initial condition. Current physical/data/ground/onboard truth
remains in the runtime schema-5 checkpoint. Typed outcome history records each
consumed request, availability/reasons, actual action, sampled survival nodes,
activity/protection, timestamp and recovery. Only successful imaging advances
previous-acquisition memory. Denial records no acquisition/delivery, consumes
its forcing position and cannot reuse an elapsed contact.

Restore validates the bounded prefix by deterministic execution from the
immutable origin, comparing all outcomes, previous acquisition and complete
runtime checkpoint exactly. Missing/reordered/forged outcomes or altered
physical state fail even with recomputed checksums. This stronger validation
costs linear replay in the prefix per validation; it is deliberately bounded,
not a production campaign optimization. Origin is historical initial data,
not a mutable duplicate of current truth. Replacing an entire valid experiment
and all digests remains declaration of a different experiment, not authentication.

`ExperimentBundle` accepts the new explicit program/memory pair through the
existing strict allowlist. Bundle, canonical and provenance versions remain 1;
checkpoint schema remains 5; B2 versions/digest and UTF-8 Git pathname handling
are unchanged. Strict actual-source/environment equality remains required.

## Independent verification and executable example

`examples/v5_operational_protection_demo.py` accepts `--output`, optional
`--trace-output`, `--stop-after`, `--bundle-output`, `--resume`, and `--numerical`.
Use `python -B -m examples.v5_operational_protection_demo` with all output paths
in an existing directory outside the repository.

The 23-second trace has a 400 K payload with existing 320 K operating/340 K
survival maxima. With synthetic payload C=23 J/K and bus-payload G=1 W/K,
the Euler standby endpoint is exactly 300 K from a 300 K bus and zero payload
forcing. Later imaging succeeds; downlink transfers 9000 of 12000 bits; a
different predicted hot acquisition is denied; its later data request honestly
reports unavailable data. The acquired record eventually completes delivery.

This trace verifies discrete policy composition, not physically validated
cooling or recovery time. For its first standby, the declared two-node equations
are `Cb*dTb/dt = Qb + G*(Tp-Tb)` and
`Cp*dTp/dt = Qp - G*(Tp-Tb)`, with Cb=3600 J/K, Cp=23 J/K,
G=1 W/K, Qb=12 W, Qp=0, Tb(0)=300 K and Tp(0)=400 K.
An independent closed-form derivation uses total energy
`E(t)=Cb*Tb(0)+Cp*Tp(0)+(Qb+Qp)*t` and difference
`D(t)=Dinf+(D(0)-Dinf)*exp(-lambda*t)`, where
`lambda=G*(1/Cb+1/Cp)` and `Dinf=(Qp/Cp-Qb/Cb)/lambda`.
Then `Tb=(E-Cp*D)/(Cb+Cp)` and `Tp=(E+Cb*D)/(Cb+Cp)`.
At 23 s the exact ODE endpoint is approximately Tb=300.4792651133611 K,
Tp=336.98459095216606 K, versus the one-step Euler payload endpoint 300 K.
Thermal numerical qualification and recovery-time sensitivity belong to
Task 04. R1 does not change the thermal integrator or start that task.

The isolated-node standby reference uses dt=36 s, 20 W explicit demand, zero
generation, 80 Wh initial energy and discharge efficiency 0.8:
cell throughput = 20*(36/3600)/0.8 = 0.25 Wh; end energy = 79.75 Wh;
conversion loss = 0.05 Wh = 5 W. Half-retained component power gives 10 W bus
heat. With C=3600 J/K and external bus/battery/payload heat 2/1/3 W,
endpoints are 300.12/300.06/300.03 K. Nonzero calendar/cycling Arrhenius damage
is independently evaluated using 50-digit Decimal exponentials at 300.03 K
representative battery temperature. A documented 64-ULP arithmetic bound is
used only for this numeric reference, never as admission tolerance. Exact
bit accounting and same-environment restart remain exact comparisons.
