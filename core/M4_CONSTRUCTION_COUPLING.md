# B45: opt-in coupled construction, candidate V1

Uncommitted additive candidate on accepted B43. This is a bounded synthetic
engineering model, not independently accepted, flight calibrated or full M4.
Frozen pre-M4 B44 and all initial failures remain in external evidence.

`ConstructionMissionInputs` binds an immutable `LongMissionInputs` and
`ConstructionConfiguration`. The latter binds the exact M1 assembly-document
digest, body frame, ports, routes, wire properties, declared mass claims,
thermal instance/lumping graph, full node/link provenance, boundary inputs,
bus/source limits and model identities. Runtime recompiles from these inputs
before every action. Serialized derived geometry cannot grant execution.

One ideal fixed-voltage regulated bus supplies exactly seven independently
owned receiving component branches and one PV source branch. Bus endpoints
may share the declared bus instance; distinct branch ports are mandatory.
Unsupported loops, cross-fed sources, converters and parallel batteries reject.
This separate validator does not change M1-C independent-line topology.
One two-conductor port denotes positive/return, not two independent sources.
Internal branches may start/end on the bus instance with explicit authored
slack/waypoints. Geometry remains authored, with no clearance or bend proof.

Caps before allocation:64 ports/lines,32 assembly instances,64 thermal nodes,
256 links,64 waypoints per route,8 actual electrical branches. Input16MiB;
causal packet at most the bound B44 limit, hard512MiB; tree8Mi nodes/depth64.
Runtime line reservations65536 (hard262144),compilations256 (hard1024),
control reservations2^26 (hard2^28). Each attempted cut reserves8 line calls;
returned/refused/unknown calls are separate, unused reservations not refunded.
Runtime compilation reserves32768 schema/control units, not a CPU estimate.
Static immutable-input validation is distinct from execution work. B44 work,
source quotas, numerical steps and protection laws remain unchanged.

## Electrical and heat ownership

M1 transform: body port = component COM + R*(local point-local COM).
Route = recomputed endpoint/polyline length + authored one-way slack.
Unchanged WireSpec owns both conductors, series contacts,R and mass.
Constant receiving power uses `constant_power_load` low root:
I=2P/(V+sqrt(V^2-4RP)); R=0 uses P/V. Discriminant<=0/current/drop/collapsed
voltage reject. Load source demand=P+I^2R. Aggregate bus current limit and
the unchanged battery/EPS capability owner constrain the shared supply.
No successful action permits unmet source demand; idle also requires full
service in this bounded construction consumer. There is no partial shedding.
Infeasibility does not publish full-demand heat or acquisition/custody.

PV uses explicitly declared inherited approximation I=P_source/V_source,
P_delivered=P_source-I^2R. The existing solar formula/config/incidence is not
changed: its output is the upstream capability at the entrance to the new
external PV route. This added boundary convention is a model assumption,
not a flight bus/MPPT characterization. Available PV is assumed carried even
when downstream battery charging is curtailed; curtailment is a separate
accepted EPS term. Ideal regulated bus conversion loss is explicitly zero.

| Term | Owner and destination |
|---|---|
| receiving component demand | actual served-power routing and declared retained fractions |
| all conductor+connector Joule heat | each branch's mandatory thermal node, exactly once |
| battery charge/discharge conversion | unchanged battery transition; unchanged thermal coupling battery node |
| regulator loss | explicitly ideal zero; no undocumented coefficient |
| motor mechanical storage/release | B44 actual paid M3 signed bus heat adjustment |
| absorbed solar/albedo/IR | genuine/explicit nominal B44 forcing, separate from electrical heat |

`ConstructionEPSResult` is a new typed composition. A private legacy
EPSSubstepResult carrier transports the unchanged raw solar geometry,
receiving breakdown and wire-inclusive actual battery transition to the
pure thermal/ageing owners. It is explicitly not an output of the legacy
EPS composition or a receiving-service grant. Heat routing does not falsely
equate receiving watts with wire-inclusive source watts. No wire loss is
an artificial payload load; no solar/incidence correction hides it.
`ConstructionPhysicalResult` retains both the complete electrical composition
and unchanged accepted physical completion proposals. Per-cut balances come
from actual transitions, not a post-hoc independent demo.

Thermal links/capacities/radiation/boundaries are explicit assumed/sourced
parameters. No distance-to-conductance or mass-to-capacity inference. Instances
share a node only with an explicit lumping group; a group cannot span nodes.
Actual temperatures advance through the existing solver; operating/survival
protection and one private outer transaction remain. Predictions are labelled
and excluded from actual balance/extrema reporting.

## Mission and persistence

`start_construction_mission`/`advance_construction_mission` invoke B44 actual
POINT/CAPTURE/HOLD/CONTACT paths via a narrow new-module opt-in. No accepted
production owner is edited. Legacy no-coupling dispatch remains identical;
the context-input content guard is a new refusal before numerical work.
Contact composition preserves existing validated plans, exact bit/rate time,
service/custody/protection owners and retains selected versus prediction cuts.
Electrical/thermal refusal discards the whole private action; spent work remains.

Input format B45_CONSTRUCTION_MISSION_INPUT_V1 and packet
B45_CONSTRUCTION_ACTION_BOUNDARY_V1 have fixed allowlisted input types.
No callback/pickle/eval/arbitrary import or implicit B44 migration. Externally
retained packet SHA and immutable input digest required. Fresh original-anchor
provider/source, route recompile and private prefix replay must match full
canonical causal science and checkpoint. Reconstruction pays both cumulative
ledgers; receipts are not replay-published. Derived compiler data is comparison
evidence only. Same-runtime exact restart is distinct from physical accuracy.

## Declared comparisons and error checks

Five600s NOMINAL_LONG cases share assembly/full tensor/world/actions/power,
apart from the stated change. Baseline:28V,1e-7m2 sections,0.2m slack.
Route-only:all slack2m; same wire material/section/limits/thermal/mission.
Thermal-only:first declared conductance reduced10x; same geometry/electrical.
Weakness:payload section1e-10m2; predicted unstable/drop constraint during
actual capture. Repair:payload section1e-6m2; unchanged mission requirements,
deadlines/protection/receiving power. Effects are measured, never promised.
All material/current/drop/radiative inputs are synthetic assumptions.

Hand roots and independent80-digit Decimal checks bound binary64 current
within2ULP. Per-cut sums use4/8ULP of the participating power scale; stored
energy cancellation uses8ULP of start Wh. These explicit representation bounds
are for arithmetic checks, not continuous temperature/event-time accuracy.

Harness conductor/connector mass is calculated and declared INCLUDED/EXCLUDED.
INCLUDED is not added twice or proved numerically included in an aggregate.
EXCLUDED remains not mass closed. Optional route-mass COM/tensor augmentation
is NOT implemented. B44 placement-only paid-tensor results remain separate.
Combined qualification UNRESOLVED; nominal day is not enclosure qualification.
