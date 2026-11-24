# Task 04A: physical action time and coupled internal integration

This separately reviewed execution mode implements the author's Task 04A
contract. It does not declare V5.8 complete or select a universally adequate
timestep. D094/D095's explicit Euler equations and explicit numerical failures
remain. D150 and D285's broader qualification work remains open. D234, D247,
D248 and D273 still describe the historical imaging/engine APIs; those APIs
retain their integer duration and configured full-step admission. No historical
decision or source record is rewritten to imply prior substep approval.

## Explicit time and forcing

`integration_time.IntegrationPolicy(subdivision_level=k)` selects
`coupled-euler-midpoint-ageing-v1`. A `substepped_execution.TimedRequest` binds
one existing `ProtectedRequest` to integer seconds `[t0,t1)`, with `D=t1-t0>0`.
It must start at the current completed clock and end within the world horizon.
Exposure or contact duration must equal D. Standby also consumes all of D.
`NumericalConfig`, its geometry sampling and its checkpoint interval are not
modified or cloned. D may differ from its legacy `timestep_seconds`.

The numerical partition has N=2**k equal internal durations, represented by
`DyadicDuration(D,k)`. Offset i is the exact rational `(i*D)/2**k` seconds.
No absolute float clock or cumulative addition constructs these boundaries.
The policy admits exact built-in integers, 0<=k<=12 and 1<=D<=2**40 seconds.
Thus every offset numerator is at most 2**52 and internal duration/offset
conversion to binary64 is exact. The public origin remains an integer without
that binary64 limitation. Integer completed clocks advance by D once.
An action's maximum is 4096 substeps; reaching this limit says nothing about
convergence. A version-4 program additionally limits worst-case EPS evaluations
(mission and standby) to 16384 and requests to 128. Limits are validated before
execution, with no automatic coarsening or truncated run.

The only admitted forcing contract is
`constant-over-action-uniform-solar-loss-v1`. Sunlit flag, incidence, loads,
routing, sink boundaries and explicit external heat are constant for the whole
declared action. Action and fallback forcing can differ explicitly. Changes
between actions occur at their declared integer boundaries. A nonempty
`forcing_change_times_seconds` is rejected; world-event execution is rejected.
There is no event stepping across an undeclared change. Geometry, declared
serviceability and scheduled ADCS directions are supplied action inputs; no
substep creates a geometry sample, request, exposure or ground decision.

The existing `SolarDegradationForcingInput.retention_loss`, when used in this
new contract, is the total action loss, distributed uniformly as loss/N after
each subinterval. This is an explicit forcing assumption, not a radiation law.
The next EPS evaluation uses the resulting solar retention. Positive per-step
loss that underflows binary64 is rejected. Repeated retention subtraction has
ordinary floating-point rounding; equal whole-action forcing is not a claim
of bit-identical final retention between different numerical policies.

## Duration APIs and physical ownership

Legacy public signatures, integer validation, return types and `__all__`
contracts remain. New APIs are imported explicitly from their owner modules:

| Owner | Duration-aware entry point / result |
| --- | --- |
| `eps.py` | `compute_battery_substep_transition`, `BatterySubstepTransition` |
| `eps_system.py` | `compute_eps_substep_transition`, `EPSSubstepResult` |
| `thermal.py` | `compute_thermal_substep_transition`, `ThermalSubstepResult` |
| `thermal_routing.py` | `compute_substep_routed_internal_heat` |
| `thermal_coupling.py` | `compute_eps_thermal_substep_transition`, `EPSThermalSubstepResult` |
| `degradation.py` | `compute_battery_substep_throughput`, `compute_battery_degradation_substep`, `BatteryDegradationSubstepInput/Transition` |
| `engine.py` | `complete_coupled_physical_substep`, shared physical completion |

New duration records validate both a dyadic token and matching float seconds.
They share field validation with their legacy records; legacy consumers still
reject the new record types. Constructors are never bypassed. Integer and
dyadic wrappers delegate to one arithmetic owner, rather than parallel model
implementations. Explicit Euler still evaluates all thermal fluxes from the
same initial temperature vector for each subinterval.

For each internal subinterval the new executor:

1. Derives capability from current battery/solar degradation.
2. Computes one authoritative EPS result, including efficiency, available
   energy, charging/discharging power constraints and capacity.
3. Derives component service and routed heat from that same EPS result.
4. Applies explicit heat and battery conversion loss once through the existing
   EPS/thermal coupling; evolves all thermal nodes simultaneously.
5. Uses the existing battery-side Wh throughput and midpoint of the battery
   node's start/end temperature for calendar/Arrhenius/cycling ageing.
6. Applies the declared solar loss and reconciles energy against the resulting
   capacity, then uses the updated physical state for the next subinterval.

There is no second full-action energy or ageing transition. Inaccessible Wh
from capacity reconciliation are recorded separately and are not thermal heat.
No conversion loss is duplicated in component or external heating.

`ActionAccounting` sums selected-path generation, requested/served/unmet load,
charging input, discharge output, curtailment, conversion loss, battery-side
throughput, inaccessible energy, routed heat and external heat in Wh. Calendar,
cycling and solar retention losses are dimensionless. Finite sums use `fsum`;
these are energy aggregates, not relaxed per-substep power admission checks.
Positive energy underflow is an explicit integration-specific error. It must
not erase a positive essential-power deficit. Existing R1 exact sequential
service sums, incompatible full-service sums and unrepresentable fixed-prefix
partial service retain their existing rejection boundaries without epsilon.

## One action, protection and atomicity

Public new boundaries are `execute_substepped_request` and read-only
`evaluate_substepped_availability`, with explicit `policy` and `integration`.
Both calculate the same refined proposal. The standby proposal uses the
unchanged R1 essential-demand priority allocator. Fully served mission loads
remain fully served on every subinterval. At the first EPS deficit, a mission
prediction stops before thermal evolution of that deficient interval: no
mission load-shedding heat model, partial exposure or data credit is invented.
Its predicted trace is a prefix; the availability result records unmet W and
the work counter includes the deficient EPS evaluation.

All required operating limits are checked inclusively at the initial state and
every calculated subinterval endpoint. Standby's essential service and required
node trajectory are checked too, as in Task 03B. This is protection of a
computed sampled trajectory, not a continuous-extrema/crossing certificate.
Invalid physical numerical proposals remain errors, not a fabricated denial.
If admission fails, the mission proposal is discarded and exactly the full-D
standby proposal from the original state is selected. Both proposals use the
same dyadic partition; their energies/states are never both applied.

Imaging calls the existing ADCS/acquisition composition once with full exposure
duration, verifies exact scheduled readiness/window, and checks whole-product
storage before admission. One selected image creates at most one complete
record at the actual end. Previous successful acquisition memory advances only
for that selected image. Rejected images preserve previous memory and custody.

Downlink calls the unchanged single-record transmission/data mutation owner
once. A partial transfer retains the whole onboard allocation; completion
removes that record/allocation and credits reception once, at the conservative
contact-end timestamp. The transmitter stays on for all of D even if capacity
exceeds the selected record's remainder. Early TX shutdown, residual idle
physics and a second record are Task 04B, not implemented here.

`SubsteppedOutcome` separates the predicted mission trace from the actual
selected trace. Samples include exact offset numerators, temperatures,
battery/solar state, operating and survival observations. Endpoint unmet W is
the preceding subinterval's average EPS result, not an instantaneous crossing.
Several violating samples do not increment a failure counter. No permanent
damage is inferred. Perfect sampled onboard observation is the declared policy;
ground knowledge, telemetry and controller state do not refresh implicitly.

Activity mode and reversible NORMAL/BACKUP FDIR are decided once at the outer
boundary. `critical_energy_since_seconds` is the integer start boundary owning
the first action with any selected essential deficit (or an earlier still-active
boundary). It is not a fractional physical onset time. Recovery occurs only at
the next outer request decision under the sampled admissibility rule.

The original context and external continuation memory remain untouched while
private proposals execute. Result, trace-to-physics, final checkpoint and
protection ownership checks precede one external engine commit. Assignment
rollback also restores the original context if the commit hook raises. There
are no repeated calls to public fixed-step engine actions. A selected action
advances clock by D and `diagnostics.completed_steps` by one. Actual numerical
substeps, all evaluated EPS proposals and all evaluated thermal proposals are
separate reported/derived counters; they do not drive policy decisions.

## Version-4 continuation

`SubsteppedProgram(4, ...)`, `SubsteppedMemory`, `SubsteppedState` and
`advance_substepped_continuation` extend the existing bundle through explicit
allowlisted types. Versions 1/2/3 are not reinterpreted. Bundle/canonical/
provenance versions remain 1, checkpoint schema remains 5, B2 remains 1/1 with
its fixed digest. No physical state moves to an external runner.

The canonical input digest includes unchanged `SimulationInputs`, immutable
origin checkpoint, previous acquisition, every physical request interval,
mission/fallback forcing, protection policy, integration policy and assumptions.
Different subdivision levels therefore have different experiment identities.
The demonstration separately hashes the physical scenario excluding integration
for comparison only; that hash cannot authorize continuation or replace the
bundle's input digest. Strict source/environment compatibility remains intact.

Only completed-action boundaries can restart. Bounded replay from the immutable
origin checks every recorded outcome, previous successful acquisition and the
entire schema-5 checkpoint, including rehashed but false runtime history.
Mid-action checkpoints are unsupported. Same-policy JSON restoration in a
fresh process must reproduce complete checkpoint, outcomes, records, clocks and
metrics exactly. Numerical tolerances are not used for restart equality.

## Independent references and qualification boundary

The two linear thermal references use an independent closed-form derivation.
For two capacities Cb,Cp, conductance G and constant powers Qb,Qp, let
`delta=Tp-Tb`, `lambda=G*(1/Cb+1/Cp)` and
`delta_inf=(Qp/Cp-Qb/Cb)/lambda`. Then

`delta(t)=delta_inf+(delta(0)-delta_inf)*exp(-lambda*t)` and
`M(t)=(Cb*Tb(0)+Cp*Tp(0)+(Qb+Qp)*t)/(Cb+Cp)`.

Recover `Tb=M-Cp*delta/(Cb+Cp)`, `Tp=M+Cb*delta/(Cb+Cp)`.
The example evaluates this derivation with 60-digit Decimal arithmetic. The
third battery node is isolated and cannot influence these two-node references.
All coefficients are synthetic verification inputs with explicit provenance.

For Cb=Cp=10 J/K, G=1 W/K, 310/290 K, zero heat and D=12 s, the old Euler
result remains exactly 286/314 K. The analytical result is
300.9071795328941/299.0928204671059 K. The h=6 s result has a smaller endpoint
error than h=3 s by accidental cancellation after an oscillatory coarse step;
global monotonic improvement from every coarse step is not claimed. The tested
convergent range starts at h=3 s and reaches h=12/4096 s, with maximum error
below 0.00065 K. Conservation is checked separately and is insufficient alone.

For Cb=3600 J/K, Cp=23 J/K, G=1 W/K, Qb=12 W, Qp=0, 300/400 K and D=23 s,
the exact result is 300.4792651133611/336.98459095216606 K. Refinement through
h=23/4096 s has maximum temperature error below 0.0046 K. The old payload
endpoint 300 K is not qualified cooling. With unchanged configuration and a
next request at 123 s, the coarse calculation can admit imaging but the refined
initial payload temperature exceeds the same 320 K operating maximum and the
request falls back to standby. Request time and configuration are not moved.

Additional references use literal rational charging/discharging balances,
nonzero calendar/cycling ageing, independently calculated Decimal Arrhenius
midpoint factors, power/capacity constraints, routed and conversion heat, and
fractional 5.75 s intervals. Short electrical balances use 64 reference ULPs;
the midpoint Arrhenius sums allow 128 reference ULPs for exponential and
reciprocal-temperature cancellation. Capacity reconciliation involves endpoint
subtraction and uses bounds scaled to stored-energy ULPs. These arithmetic
bounds are distinct from Kelvin error against the continuous thermal solution;
they do not relax any admission threshold or per-component power equality.

`examples/v5_substepped_execution_demo.py` provides `--numerical`, normal
execution, `--level`, `--stop-after`, `--bundle-output` and JSON-only `--resume`.
All output paths must be outside the repository. Its 23 s action schedule is
image, partial delivery, standby, predicted-hot denial, completion; it delivers
one 12000-bit record, counts five outer actions, and ends at 215 s. Tests restore
at boundaries 1, 2, 4 and 5 for policies h=11.5 and 5.75 s and compare full
state/history exactly in a new process with fixture regeneration forbidden.

Task 04C must still qualify nonlinear radiative/stiff networks, policy-boundary
sensitivity, whole campaigns, acceptable hardware/configuration ranges,
rounding accumulation and method/timestep adequacy. No general stability,
continuous safety, complete V5.8, controller planning, interval-view/J2
certification, maneuver/propulsion extension or permanent damage is claimed.

Mechanical updates to existing architecture checks only follow the extracted
EPS/completion helpers and the explicit time-value import. Tests still require
one arithmetic owner and preserve forbidden dependencies; behavior, historic
release guards and exact bit accounting have not been weakened.
