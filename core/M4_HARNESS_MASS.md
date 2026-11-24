# B44/B45-R1 and B46 rigid/lumped harness mass candidate

This is an uncommitted review candidate on accepted B43. It does not declare
independent acceptance, installation feasibility, flight qualification or full M4.
The old M1, full-tensor M3, orbit, battery, thermal and custody owners are unchanged.

## Repaired construction contracts

R1 imports the accepted checked `_integer_quantity` helper for partial custody.
A 1 s contact moves 1000 of 12288 stored bits without credit; the next contact
delivers the remaining bits, one receipt, and releases storage. Forcing boundaries
can split that transfer internally. Duplicate consumed contacts reject before work.

R2 `reconstruction_planning.plan_reconstruction` uses immutable actions, not saved
results or the number of unique products. Every preceding CAPTURE may create a
record, including repeated captures of the same product. For S forcing segments,
N=2^integration_level and R preceding captures, contact physical reservation is
S*N*(2*R+1). At most R+S-1 transmit attempts can occur: a completed record leaves
custody; a forcing boundary can split at most one still-partial record. Actual
wait/transmit predictions plus idle proposals are bounded by N*(2*(R+S-1)+S)
for R>0, or N*S with no records. Selected transmit reuses its paid prediction.
Every construction proposal reserves exactly eight line calls.

Forcing S is bounded from all profile/table boundaries, nominal lighting grid or
continuous source supports, with the existing 8192-segment admission limit.
Noncontact partitions include physical maximum interval, all forcing cuts and
the four possible slew-profile cuts. HOLD duration is conservatively measured
from original world start; POINT uses the existing 120 s domain. Runtime provider,
index, spatial/geometry/output and construction compile/control costs have separate
finite bounds. Prior spent work plus replay bounds must fit before mission start.
These reservations are upper bounds, not measured execution counts. Unreturned
primitives retain UNKNOWN accounting. Repeated restore may exhaust finite quotas.

The seven-CAPTURE level-6 diagnostic actually reserves 11376 line calls. A 20000
cap rejects before start; a separately admitted 30000 cap permits replay, cumulative
22752 and seven receipts. No saved quota, hard ceiling or progress is reset.

R3 `ConstructionContactRefusal` carries known electrical refusal and actual returned
prediction work. Only the accepted ElectricalLimitError is an ordinary physical
denial. Atomic outer context, battery/thermal/clock/custody/consumed IDs stay intact;
cursor records the refusal once and later allowed actions may execute. Impossible
power is not served and no valid full ContactOutcome is fabricated. Arbitrary bugs
propagate with unreturned contact work UNKNOWN. Aggregate bus rejection occurs
after successful line calls; it must not invent a failed-line count.

## Authoritative assembly and distribution

`HarnessAugmentationInputs` binds exact M1 assembly and B45 construction digests,
body frame, eight routes, geometry/material/section/length/slack/connector ownership,
spatial rationale, method and policy. Methods are explicit version-1 identifiers.
The supported positive domain requires all eight routes EXCLUDED from M1 base and
INCLUDED exactly once in the B46 derived rigid/lumped reduction. The bare M1 result
remains separately available. Already-INCLUDED aggregate harness distribution is
UNSUPPORTED for numerical closure: no guessed subtraction or second addition.
The unassembled control reports NOT_MASS_CLOSED and uses original M3 hardware.

Coordinates are metres in the unchanged right-handed body axes. Component-local
points use the accepted component rotation/local-COM transform, exactly once.
Inertia is kg m^2 about the combined COM, expressed in those same body axes.
No principal-axis diagonalization, absolute-value repair or axis-only replacement.

Each nonzero polyline segment is two separately owned co-routed uniform slender
rods. For endpoints p,q, d=q-p and segment mass m, center=(p+q)/2 and
J=m/12*((d dot d)*Identity-d*d^T). This is exactly the unit-axis slender-rod law.
Zero-length segments carry no distributed conductor mass. Existing WireSpec's
binary64 **total** conductor mass, including both conductors, is authoritative.
Exact rational shares proportional to binary64 segment lengths and declared slack
allocate that total; a separate independently tuned density-mass estimate is not
introduced. Thus binary64 multiplication/summation rounding belongs to the inherited
mass model; exact allocation closes to that authoritative total, not an unrounded
real-number product of material coefficients.

Slack has no known installed shape. `DECLARED_POINT_MASS_TWO_CONDUCTORS_V1`
requires an explicit centroid, body or component-local frame and rationale. It is
a stated zero-intrinsic-inertia point reduction, not discovered loop geometry.
Every series connector has an explicit location. The authoritative connector total
is divided exactly by the declared count; coincident locations are permitted for
distinct physical instances. Resistance/count remains an electrical abstraction.

All contributions have distinct descendants of their disjoint route ownership
root. B45 proves route-root/base and route-root/route-root disjointness. Unique
generated one-level tags then prove contribution disjointness without a quadratic
scan. Omission, duplication, stale shape/frame/configuration and overlapping mass
claims reject. Closure per route is EXACT in Fraction arithmetic: conductor plus
connector total equals the sum of generated contributions.

## Full mass properties and physical consumer

Let base mass M0, COM c0 and tensor I0 be the accepted M1 result. For additions
m_j, c_j, J_j define P(x)=(x dot x)*Identity-x*x^T. The compiler uses:

M=M0+sum(m_j), c=(M0*c0+sum(m_j*c_j))/M,

I=I0+M0*P(c0-c)+sum(J_j+m_j*P(c_j-c)).

This shift-to-new-COM form avoids subtracting two large origin tensors. All nine
entries and the complete contribution ledger are retained. Arithmetic starts from
exact rational representations of the admitted binary64 inputs. Conversion to
binary64 occurs once for the actual effective tensor; accepted finite/symmetric/SPD
guards are then applied. No unexplained geometric tolerance or physical uncertainty
is added. Independent analytic point/parallel-axis references are exact; the unit
rod oracle uses 80-digit Decimal with 128*10^-79*max(1,mL^2) rounding allowance for
at most 64 operations. The local transform reference permits four binary64 ULP at
unit scale. Neither allowance represents installation or material uncertainty.

`EffectiveAssemblyHardware` is a new family, never a forged AssemblyHardware3D.
It independently recompiles base, configuration and augmentation before use.
Original actuator, camera axis, panel normal, body/quaternion conventions remain.
`plan_effective_slew` reuses the accepted constructive full-tensor formulas for
I*axis, axis cross I*axis, momentum/rate/torque, root/profile, kinetic/electrical
energy and heat. Long POINT explicitly dispatches to it only in B46 mass mode.
HOLD/CAPTURE/CONTACT retain the same environment, protection and custody laws.
Integer duration may stay unchanged; full profile and paid energy are compared.

No orbital reanchor, COM translation of the saved orbit, ray-origin lever arm,
gravity-gradient, aero or flexible dynamics is introduced. Source position and
camera ray retain the declared spacecraft-point model. Wire heat nodes, capacities
and conductances remain explicit B45 lumped inputs; mass does not silently derive
thermal capacity. No routing clearance, CAD, FEM or deployment claim is made.

## Admission, work and persistence

Finite caps: 32 base instances, exactly eight branches, at most 64 waypoints each,
2048 generated contributions/connector-point declarations, 64 m coordinate domain,
positive contribution and combined mass <=2^20 kg, final rational numerator and
denominator <=4096 bits. Input maximum 16 MiB, packet <=512 MiB and the bound
long-document quota; tree depth 64 and inherited finite tree cardinality. The fixed
input codec rejects unknown fields/types before dynamic execution. Large contribution
lists are rejected before typed spatial allocation. No arbitrary supplied tensor,
callback, pickle, file path or dynamic import is input authority.

Harness runtime quota: at most 128 owned compilation reservations, each 2^20
control units, total <=2^27. These fixed units price bounded owned validation and
compilation, not measured CPU or scalar arithmetic leaves. Pure input/static
admission is distinct; it cannot call orbital/physical execution. Runtime guard,
POINT planner and save own reservations. Costs remain cumulative through replay.

B46 input/continuation version 1 binds original epoch/world/source, M1 assembly,
B45 topology/thermal/routes, augmentation/mode, actuator and all policies. Complete
scientific state includes effective hardware and contribution ledger, pose/slew,
physical/electrical/thermal traces, custody/partial bits/receipts/credit and history.
Work is separate. Restore verifies external packet SHA/input digest, admits all
three cumulative ledgers, rebuilds original inputs and privately replays the prefix.
Saved tensor/graph/diagnostic results are never continuation authority. B44/B45
default formats remain accepted by repaired owners; no implicit migration.

## Bounded executable evidence

Five 600 s NOMINAL_LONG runs use original anchor128 through728, the same mission,
actuator/protection and authored detours. Unassembled/augmented/redistributed inputs
share exact B45 electrical and thermal authority. Redistribution changes only
declared slack/connector locations, preserving exact wire mass and electrical
lengths. Weakness versus repair changes only payload section1e-10 to1e-6 m^2,
recompiling electrical and mechanical cost. Point duration remains8 s in all cases;
inertia/profile/paid actuator energy changes are real, small, and not a winner claim.
The repair restores delivery but adds mass. An explicit partial boundary at169 s
has1000 transferred bits/no receipt. Fresh-process replay equals full uninterrupted
scientific bytes; same-runtime equality is not a cross-platform guarantee.

See the external final report for exact source-bound commands, counts, results and
retained failed fixture/postprocessing attempts. Historical day evidence is reused;
no new day/H5 run. MASS_CLOSED means only this rigid/lumped accounting closure.
Combined qualification remains UNRESOLVED; nominal day is not continuous-day
accuracy, physical/event/day qualification and full Version M remain open.
