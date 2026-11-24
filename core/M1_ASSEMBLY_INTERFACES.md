# M1-C: explicit static assembly interfaces

Bounded contract written before implementation/testing. Baseline
`1864f7b85e910d3d96f32d4b702c5ebecf89099a`, isolated branch
`m1-assembly-20260930-73347d98`. No accepted owner is changed.

## Inputs, authority and outcomes

Immutable `AssemblyInterfaces` binds to the exact M1-B assembly-document SHA-256
and names its body frame. It contains electrical ports, independent line
connections, thermal instance bindings, optional explicit thermal network and
radiative boundaries, and a required supply-assumption rationale. All new IDs
use M1-A exact Unicode scalar validation. New numerical inputs are finite
built-in binary64-compatible numbers; bool and numeric subclasses reject.
Tuples, nested records and referenced authorities are revalidated.

`ElectricalPort` names a physical instance, its definition's local frame,
local point in metres, and exactly SOURCE or LOAD. A port is one two-conductor
interface (positive/return treated together), not one conductor terminal.
Mechanical-only instances need no ports. Body endpoints always derive from
the currently resolved M1-A placement:
`p_B = center_body + R * (p_C - center_local)`.
The local origin and COM must not be interchanged or offset twice.

`LineConnection` names one SOURCE port and one LOAD port on distinct instances,
ordered authored body-frame waypoints, nonnegative one-way slack in metres,
wire properties excluding length, an operating point, harness mass declaration,
and an optional wire-loss thermal destination. Identical duplicate connections,
duplicate IDs, wrong roles, unknown endpoints/instances/frames/nodes or invalid
types are malformed inputs and raise TypeError/ValueError. One physical instance
may participate in at most one line: shared ports, different ports on the same
device, branching, cascades and shared buses are UNSUPPORTED. Even if their
operating points look independent, these topologies are not evaluated as circuits.
Unused declared ports are INCOMPLETE; no port is silently ignored.

Compilation first verifies the digest, references and M1-B assessment. Authorized
poses alone are insufficient. Any M1-B violation is a CONSTRAINT issue; missing
installation/mass declarations are INCOMPLETE. Neither can issue a usable
compilation. Malformed input raises; well-formed CONSTRAINT, INCOMPLETE and
UNSUPPORTED issues are sorted deterministic records with affected IDs. Independent
issues are collected. `compilation` is None unless all required checks pass.
Successful independent line diagnostics may accompany an incomplete report,
but are explicitly static diagnostics, never a mission-execution permission.

## Existing owners and accounting

| Interface/assembly input | Existing owner | Derived quantity |
|---|---|---|
| Qualified choices, selected poses | M1-B assess_design; M1-A placement | Physical instance COM/rotation |
| Local ports, authored waypoints/slack | Thin interface geometry adapter | Body endpoints, polyline and one-way length m |
| Wire material/section/connectors/limits plus derived length | design_trade_physics.WireSpec | Loop resistance ohm; conductor, connector and total harness kg |
| CONSTANT_LOAD operating point, V and receiving W | constant_power_load | Stable low-current solution, supply W, receiving W, loss W |
| GENERATED operating point, V and sending W | generated_power_line | Fixed-source current approximation and delivered W |
| Nodes, links, capacities, role references and provenance | ThermalNodeConfig/ThermalLinkConfig/ThermalNetworkConfig; ScalarParameter | Validated immutable thermal configuration |
| Explicit sinks K; line loss destinations | ThermalIntervalInputs; ThermalAppliedHeatInputs | Boundary inputs and per-node wire-loss-only diagnostic W |

Polyline length is the sum of Euclidean distances between recomputed source,
ordered waypoints and recomputed load. Slack is added once to one-way length;
WireSpec owns the two-conductor return and all electrical/mass formulas. No
automatic routing, obstacle clearance, cable bend radius or route feasibility
claim. Finite-arithmetic overflow rejects; no rounding/clamping of geometry.

Operating points assume IDEAL_INDEPENDENT_SOURCES at explicitly declared source
voltages. The CONSTANT_LOAD power is receiving demand; GENERATED power is source
power. Current, voltage-drop, nonpositive receiving voltage and unstable-root
rejections come from the existing electrical owner and become CONSTRAINT issues.
No current limit is relaxed and no load is silently curtailed.

Each line's `HarnessMassDeclaration` is INCLUDED, EXCLUDED or UNSPECIFIED.
INCLUDED identifies an existing instance and nonempty M1-A coverage paths fully
contained by that instance's declared mass ownership. EXCLUDED declares paths
disjoint from all assembled coverage; calculated mass is explicitly unassembled.
UNSPECIFIED has neither paths nor owner and blocks usable compilation as
incomplete. Cross-line ancestor/child coverage overlaps are constraint violations,
including different IDs. Wrong included owner references are malformed; an
unfulfilled or conflicting declared ownership claim is a constraint violation.
No calculated wire mass is added to assembly mass or compared with the whole
mass of an aggregate owner. INCLUDED is a declared accounting boundary, not
proof that its mass numerically contains this route's estimate. EXCLUDED is a
supported diagnostic with unassembled mass, not a mass-closed hardware design.
Placement and coupled accounting of new harness mass remain M4 work.

## Thermal boundary

`ThermalBinding` maps one instance to a configured thermal node. Multiple
instances may share a node only when all explicitly name the same nonempty
lumping group; otherwise the mapping is INCOMPLETE. A group cannot denote two
different nodes. Every electrical endpoint instance requires a binding;
mechanical-only instances need none. No node per component, capacity from mass,
conductance from distance or boundary temperature is inferred.

The full existing thermal network (including three distinct mandatory bus,
battery and payload roles), ScalarParameter provenance, capacities, radiation
properties, conductances and temperature limits is supplied. All nodes require
explicit radiative sink boundaries. Missing network/boundaries/destination is
INCOMPLETE; references to nonexistent nodes in a supplied network are malformed.

Only each line's total conductor-plus-series-connector Joule loss is routed,
once and wholly to its one declared node. All configured nodes appear in the
derived ThermalAppliedHeatInputs, with explicit zero for no mapped wire loss.
This is a WIRE_LOSS_ONLY diagnostic accounting boundary: receiving electrical
power is not automatically load heat, and EPS/battery/regulator conversion
losses are excluded. If these diagnostics are used later, M4 must reconcile
them with actual served-power, EPS and existing heat-source owners; adding
them to another already inclusive wire-loss term would double count. This
slice never advances thermal state or bypasses served-power/EPS execution.

## Interface document version 1

Separate format M1_ASSEMBLY_INTERFACES, version 1; no change to M1-B document v1,
simulation schema 5, experiment type allowlist or frozen source fingerprints.
Two files (assembly plus interface) contain all operational input definitions.
Source IDs inside thermal provenance remain provenance references, not runtime
catalog dependencies. Loading requires the assembly, checks its exact digest
and every cross-reference, and never trusts cached endpoints, lengths or outputs.
Well-formed incomplete/inadmissible inputs can round trip and are reassessed.

New numerical fields use canonical finite float.hex strings, signed zero kept.
Unordered ports/lines/bindings sort by ID; thermal nodes/links/boundaries sort by
ID; ownership paths and provenance source-ID sets sort; waypoint order matters.
Thermal records reuse the accepted version-1 typed canonical codec, including
strict nested fields, exact integer/float types and complete provenance. That
embedded codec version is explicitly pinned. New M1 records are not registered.
JSON is UTF-8, sorted keys, compact separators, no BOM/newline, no Unicode
normalization. SHA-256 uses `b'M1-ASSEMBLY-INTERFACES\0v1\0'` plus canonical JSON.
Identity includes the assembly digest, all supplied policies and provenance;
it is not universal physical equivalence or authorship authentication. An
optional trusted expected interface digest detects otherwise valid edits.
Duplicate JSON keys, unknown/missing fields, invalid types, nonfinite values,
unsupported versions and stale assembly bindings reject. Save uses exclusive
creation. No dynamic state or derived quantity is authoritative persistent input.

## Verification and limits

Synthetic two-placement example, declared assumptions only: source port at
(0,0,0), receiving port at (1,0,0) or (2,0,0) m; same physical inventory,
same wire/material/operating inputs. Unit reference section=1 m^2,
resistivity=.25 ohm*m, density=10 kg/m^3, no connectors gives R=.5 or 1 ohm
and harness mass=20 or 40 kg. These exaggerated unit fixtures are not hardware
coefficients. At V=10 V and receiving demand 18 W the near line has I=2 A,
loss=2 W, source=20 W. The far low-current root is checked independently with
80-digit Decimal arithmetic. Heat goes explicitly to the bus node. Generated
20 W at 10 V gives I=2 A and losses 2/4 W, delivered 18/16 W.

Nonzero local COM plus a 90-degree proper rotation tests the port transform
without a second mount offset. Test stale binding, arbitrary malformed inputs,
missing endpoints/heat, unsupported branching, duplicate ownership, installation
qualification, electrical limit boundaries, canonical ordering and fresh-process
reload. Small numeric comparisons allow max(2e-14 absolute SI, 2e-14 relative)
for bounded fixtures, roughly 100--200 binary64 roundoffs; exact hand cases and
all identities/outcomes compare exactly. These are arithmetic test budgets,
not physical uncertainty or a global error theorem. Relevant M1-A/M1-B,
electrical and thermal regressions only; no full suite/campaign.

No network solver, thermal integrator, dynamic ADCS, orbit, deployment mechanics,
CAD routing or mission-performance claim. Remaining dynamic/mass integration
belongs to M4. Deliver an unstaged review candidate and stop before M2.
