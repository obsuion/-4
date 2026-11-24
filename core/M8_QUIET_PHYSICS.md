# B53 paid nominal quiet physics

This additive owner is `ops_sim/v5/lifecycle_quiet.py`, method
`B53_PAID_QUIET_STEP_DOUBLING_V1`, consumed by `lifecycle_physics.py` only for
stationary `HOLD_UNTIL`. The physical leaf remains
`construction_physics.construction_physical_substep`. POINT, CAPTURE, CONTACT,
moving attitude, transmitter service and paid full-tensor slew retain their
detailed numerical owners. An explicit `quiet_policy=None` selects the prior
B52 detailed HOLD policy. The new policy participates in immutable input and
checkpoint identity; old B52 evidence is not relabeled.

## Equations and error meaning

The accepted lumped thermal owner evaluates the declared node heat balance
over a sampled subinterval. In notation, its first-order update has the form
`T_i(next) = T_i + h Q_i(T, forcing) / C_i`, where `h` is seconds, `C_i` is
J/K and `Q_i` is watts. Its radiation/conduction, EPS transition, wire losses,
temperature-dependent ageing, capability change and capacity reconciliation
remain the existing owners, in their original order. No thermal or battery
coefficient is supplied by this numerical module.

For an admitted quiet proposal `h`, evaluate one full physical step from a
private copy and two successive half steps from a separate private copy:

```
y_full = Phi_h(y_0)
y_half = Phi_(h/2)(y_0)
y_fine = Phi_(h/2)(y_half)
```

The selected path is **the two existing half-step results**, with their actual
ledgers; there is no Richardson extrapolation of physical state. For a smooth
first-order method the usual local fine-path error estimate is
`abs(y_fine-y_full)/(2^1-1) = abs(y_fine-y_full)`. This is a nominal estimator,
not a rigorous upper error bound, global error guarantee or independent proof
that an unsampled continuous protection crossing is absent.

For each state component `j`, the scaled difference is

```
e_j = abs(y_fine_j-y_full_j)
      / (atol_j + rtol * max(abs(y_0_j), abs(y_full_j), abs(y_fine_j)))
```

For each physical integral `I`, compare the full-step integral with the sum
of the two half-step integrals, with scale
`atol_I + rtol*max(abs(I_full),abs(I_half1+I_half2))`. The norm is the maximum
over **all** these component and integral comparisons. Thus matching endpoints
cannot hide a discrepant energy/heat/ageing ledger. The metric vector includes
battery energy and cumulative throughput (Wh), every thermal node (K), battery
and solar retention, all ActionAccounting integrals, separate wire loss,
raw source PV generation and receiving-load energy. Damage and retention
integrals use the dimensionless absolute tolerance; other integrals use Wh.

Default declared local targets, fixed before comparison:

| Quantity | Absolute target | Relative target |
|---|---:|---:|
| Energy, throughput and energy integrals | 0.00002 Wh | 0.0000001 |
| Each node temperature | 0.002 K | 0.0000001 |
| Retention and damage | 0.000000001 | 0.0000001 |

These are study numerical inputs, not flight-calibrated accuracy. The policy
admits positive finite built-in tolerances, integer minimum/maximum proposals,
finite work/evidence caps and its exact method identity. Hardware/thermal
coefficient admission remains in the unchanged typed lower configurations.
Changing a target creates a distinct input; a failed comparison does not
authorize widening it. Different numerical methods need a separate declared
comparison tolerance and independently executed reference, not byte equality.

## Admission, boundaries and fallback

The default maximum proposal is 60 s, minimum macro proposal 4 s, detailed
fallback at most 2 s. Half durations and source cuts are exact Fractions;
5 seconds yields exact 2.5-second half steps, without rounding the boundary.
The accepted RationalSeconds leaf admits these durations. The context clock
changes only at the integer external action cut.

The caller first limits dispatch at release, deadline, contact, command/ACK,
telemetry, report and explicit pending-action boundaries. The quiet physical
adapter additionally partitions at every sampled-world lighting/profile cut;
it rejects UNRESOLVED illumination. Each full/half proposal stays inside one
such support interval, using its own actual midpoint orientation/forcing.
There is no claim of subcell illumination certification or event-time accuracy.

All three returned proposals must have identical charge/discharge,
curtailment, capacity-reconciliation, unmet-load and initial-full-capacity
regimes. Including the initial-full-capacity flag detects saturation onset
even when all three final states already lie at capacity. A regime change,
known physical refusal, scaled norm above one, temperature within 0.25 K of a
required operating bound or energy at/below 0.02 Wh shrinks the proposal.
Unknown kernel exceptions propagate; they are not treated as a successful
fallback. At the minimum macro size the adapter attempts the existing detailed
step. A detailed physical refusal remains an honest refused outer action.
Detailed fallback does not claim to satisfy a wide-step estimator or prove
continuous safety. Source/support and controller event boundaries still apply.

After acceptance, an error norm at/below 0.25 may double the next proposal,
up to the declared maximum. Otherwise it retains the current proposal. A
shortened event tail does not permanently ratchet the next free proposal down.
The latest proposal, exact clock, last accepted step/error and phase persist.
Every loop and selected local evidence list has an explicit finite cap.

## Paid work, atomicity and reporting

Every full, half and fallback leaf call reserves runtime and construction
work **before** its invocation. QuietWork separately records reservation,
returned/refused/unknown calls, full/half/fallback calls and accepted/rejected
macro proposals. No rejected work is refunded. Actual and forecast ledgers
are distinct; a later forecast invocation receives the same forecast ledger,
not a fresh allowance. Guard failures before a kernel return are not claimed
as successful physical work.

Only selected fine or detailed fallback cuts are returned to actual reporting.
Full-trial/rejected-trial temperatures and heat never enter actual extrema or
credit. `selected_parts/selected_seconds` describe local accepted private work;
they may include a private prefix later discarded by the enclosing HOLD
transaction. `committed_parts/committed_seconds` advance only when that entire
outer physical transaction is published. The fixed selected-step histogram
therefore describes local selection, with this explicit distinction. The
actual report remains authoritative for published samples and energy/heat
integrals. Selected heat/PV/conversion/capacity loss is not added a second time.

The dynamic clone copies every mutable context record while sharing only the
already admitted immutable inputs. The normal guard validates the source state;
unchanged leaf owners retain their own input and result validation. Context,
pose, acquisition/custody and adaptive controller are committed only after
completed-action admission. A rejected outer HOLD leaves actual state/clock
unchanged while preserving all spent work. The coordinator separately consumes
actual lighting support exactly once after successful publication; trial and
forecast queries never consume actual illumination duration.

Checkpoint fields include `quiet_controller`, `quiet_work` and the received
controller state used for a causal forecast. Reopening at the same explicit
boundary with the same policy preserves exact scientific continuation in a
supported same-runtime execution. A fresh segmentation at a different boundary
can produce a different approximation and is not claimed byte-identical.

## Bounded acquisition diagnosis

`LifecycleRefusalDetail` records actual VIEW, SETTLING or STORAGE rejection,
the exact lower owner and returned scalar evidence. The new adapter follows
the existing InitialAttitudeEvidence chain: MS association validation, view
feasibility, common-frame boresight transition, optical acquisition and whole
record storage admission. It does not run the old aggregate wrapper and then
repeat numerical calls to guess a reason. An additional 1024 spatial control
reservation pays bounded diagnostic bookkeeping; the existing 65536 capture
preparation reservation and all physical work remain paid. Constructor or
unsupported owner errors propagate instead of being misclassified. Geometric,
camera FOV, electrical and thermal refusals retain their separate owners.
Historical five generic B52 refusals are not retrospectively renamed.

## Verification contract and limits

The focused tests declare analytic exponential-cooling bounds for a scalar
Euler reference, constant-rate exact integrals, exact event/odd-half boundaries,
regime and near-guard fallback, nonrefunded quota/failure accounting, immutable
input state and exact same-boundary controller/work continuation. Real-leaf
tests compare 60 seconds against detailed 2 s and finer 1 s with separately
declared 0.005 Wh / 0.05 K bounds and check moving POINT remains detailed.
Those short test bounds are not a month/global tolerance. Activity, contact,
long-input day/night, capacity, wire, thermal and ageing comparison evidence
must be produced by the separately frozen B53 experiment protocol.

Writing tests is not execution evidence. Current run counts, measured speed,
month coverage, restart and UI evidence belong in the source-bound task report.
Kernel-call reduction alone does not establish runtime speedup. This owner
does not complete physical qualification, full thermal/exposure ageing,
continuous safety, wider design comparison or the remaining Version M model.
