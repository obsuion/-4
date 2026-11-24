# CORE 90D V6 declared-design producer

`ops_sim.v5.ninety_day_designs` authors ordinary `SpacecraftProjectV3` and
`DesignSpecificationV2` inputs. It does not load a saved compiled root, map
design names to results, evaluate missions or write files. IDs are opaque
declared input labels; the five rows may be renamed without changing physics.
The exact original task intent is retained in
`tests/fixtures/ninety_day_intent_v1.json`.

The explicit API is `loads_intent(raw)`,
`author_project(common, intent, design_id, ledger, source_identity=...)`,
`compile_project(authored, ledger)`, `confirm_compiled(authored, root, ledger)`
and `design_report(authored, actual_admission)`. The immutable author result's
`.project` is consumed by the existing V3 codec/preview and V6 long preparation.
Authoring reserves one constructor unit before seed/geometry/route work;
compilation and independent full-root admission each reserve two through the
existing B68 owner. Thus author + compile + independent admission costs five
units per design, before any mission execution. A refusal is not refunded.

All batteries are the explicitly ASSUMED 50 Wh, 1 kg, 0.1 m cuboid modules;
PV modules are ASSUMED 25 W, 0.4 kg, 0.1×0.6×0.05 m; the camera is ASSUMED
0.2 kg, 0.1 m cuboid. The saved `b66_common_initial` mass/rating values match.
Per-module electrical/Rint/efficiency/ageing laws are inherited from the seed;
bank current/power/resistance/cycling accounting is recomputed by existing
`spacecraft_design._bank`. There is no new vendor calibration. Common initial
usable-SOC fraction and temperatures, controller, camera/RF/actuator, requests,
external forcing, node graph and ordinary ASSUMED ageing remain shared.

The CORE is occupied uniform equipment/support mass, not an empty hull.
Its declared mass covers support/installation equipment once. External harness
mass is excluded from that lump and added by the genuine B46 owner. Uniform
1 mm envelope padding, 1 mm clearance and a region extending 2 mm beyond the
envelopes are explicit installation declarations. Existing camera/PV rotations
and normals are retained; panel local dimensions are not mistaken for body
dimensions. Overall extents come from every rotated installed cuboid. No CAD,
collision-routing, flexible structure, strength or launch qualification follows.
Any actual geometry refusal is preserved before science; this owner performs
no outcome-driven pose repair and records an empty coordinate diff when none
was needed.

One common ASSUMED peripheral routing policy is frozen before science: true
local ports are transformed by M1/M4, then the external branch polyline visits
a +Z plane and +X rail 0.02 m beyond installed occupied extents. All eight
supported branches retain their inherited material, section, slack and two
connector rules. Both conductors, rods, endpoint connectors and the declared
rail slack point contribute genuine mass/COM/tensor. This is an installation
routing policy, not a claim that battery placement necessarily changes a real
battery lead. Internal common-SOC battery and co-oriented PV bank connections
remain ideal and unresolved. Wire intersections/shadowing/channels are not
inferred from component placement. Supports are included in the occupied CORE
lump; their geometry/strength is not solved.

Per-role seed specific heats and emissivities are retained; they are synthetic
assumptions, not material measurements. CORE exposed area is always
`(seed CORE area / seed CORE surface) * 2*(xy+xz+yz)`. The same fraction is used
for every design; no area is chosen after thermal results. Other identical
module areas scale only by multiplicity. Existing three thermal nodes and
contact conductances/forcing are unchanged. Resolved conductor/slack/connector
mass uses a predeclared common effective copper-equivalent 385 J/(kg K), with
capacity to the existing BUS node through the exact B68 route-mass/capacity
owner. This is ASSUMED, including the effective connector treatment; there are
no compensating specific heats, automatic thermal contacts or new nodes.

D1/D4 keep the same parts, functional laws and CORE. Only battery poses and
necessarily derived extents, routes, harness mass/capacity and mechanical
properties differ under this stated routing policy. Other rows compare whole
designs. The producer does not alter duration or cumulative numerical policy;
V6 preparation independently binds the 90-day original-anchor job and finite
P64/P96 proposal. Source/static admission and a storage corpus do not establish
90-day completion, capacity, physical qualification or a hardware winner.
