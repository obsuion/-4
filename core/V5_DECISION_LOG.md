# V5 Decision Log

Status: ACTIVE
Branch: v5-redesign
Baseline: v4.0-final

This file records architectural and scientific decisions for V5.
Decisions are changed only explicitly and are never silently overwritten by implementation.

---

## D001 — V4.0 is the immutable baseline

Decision:
V5 is developed on a separate branch derived from v4.0-final.

V4.0 behavior, tags, historical policies, research infrastructure, and published
results remain untouched.

Reason:
V5 is a redesign rather than an incremental claim that V4 physics was high fidelity.

---

## D002 — Primary research variable is spacecraft architecture

Decision:
The primary V5 independent variable is SpacecraftConfiguration.

The historical twelve operator policies are not the primary experiment.

Reason:
The scientific question concerns hardware/system architecture trade-offs under
common professional operations.

---

## D003 — One common professional controller

Decision:
All primary spacecraft configurations are operated by the same
MissionOperationsController implementation and flight rules.

Reason:
Changing both spacecraft and controller would confound architectural comparisons.

---

## D004 — Legacy policies are preserved

Decision:
The twelve historical V4 policies remain available for regression,
legacy reproduction, and controller-sensitivity studies.

They are disabled from the primary V5 experiment path.

---

## D005 — Optical EO is the primary mission family

Decision:
Primary V5 comparison is restricted to optical LEO Earth-observation architectures,
including panchromatic and multispectral operation.

SAR and hyperspectral mission physics are deferred.

Reason:
Mixing fundamentally different payload families would make the architecture
comparison difficult to interpret.

---

## D006 — Reduced-order physical modeling

Decision:
V5 uses Level-1 reduced-order physics.

A subsystem model should be upgraded when:
1. the existing proxy can distort the research conclusion, and
2. a simpler physically meaningful model is available.

High fidelity is not a goal by itself.

---

## D007 — Parameter provenance is mandatory

Decision:
Important parameters must be labeled as:

- PUBLIC SPECIFICATION
- LITERATURE VALUE
- DERIVED VALUE
- EXPLICIT MODEL ASSUMPTION

Assumptions affecting conclusions require sensitivity analysis where practical.

---

## D008 — Configuration and state are separate

Decision:
Hardware/design parameters belong to immutable SpacecraftConfiguration.

Dynamic physical quantities belong to SpacecraftState.

Ground belief belongs to GroundKnowledgeState.

Mission requests/plans/products belong to MissionState.

Diagnostics and research counters are not physical spacecraft state.

---

## D009 — Controller cannot access hidden real state

Decision:
The primary ground controller operates on GroundKnowledgeState.

Delayed or stale telemetry remains part of the operational problem.

Onboard FDIR may react to actual onboard state and remains separate from ground planning.

---

## D010 — Time is represented in seconds

Decision:
The V5 engine must support simulation_time_seconds and timestep_seconds.

The final timestep is selected through convergence testing rather than assumed.

A 3600-second compatibility mode may temporarily reproduce V4 behavior during migration.

---

## D011 — No artificial subsystem multipliers when a causal mechanism exists

Decision:
Primary V5 should prefer causal chains such as:

payload operation
→ electrical load
→ battery/thermal consequence
→ capability/degradation consequence

rather than repeatedly multiplying mission output by unrelated health coefficients.

---

## D012 — No double ADCS penalty

Decision:
Observation feasibility and quality will use one coherent ADCS/pointing mechanism.

The historical combination of ADCS-health scaling and separate pointing scaling
must not survive into the primary V5 model without explicit physical justification.

---

## D013 — Primary results are multidimensional

Decision:
There is no primary universal spacecraft score.

Primary analysis uses:
- mission productivity
- delivered mission value
- survival
- resource margins
- degradation
- failure modes
- Pareto trade-offs

Any scalar utility metric is supplementary.

---

## D014 — Configurations require trade-offs

Decision:
The twelve spacecraft configurations must exist inside a common comparison envelope.

Improved power, storage, payload, ADCS, communications, propulsion, or redundancy
must carry explicit design cost/trade-off.

No configuration may become the trivial winner by receiving improvements everywhere.

---

## D015 — Common stochastic worlds

Decision:
Where stochastic events are compared across spacecraft configurations,
Common Random Numbers or equivalent shared event catalogs are used.

Reason:
Architecture comparisons should not be dominated by different random histories.

---

## D016 — Professional controller development strategy

Decision:
The controller architecture is introduced early.

The first accepted primary planner may be a transparent deterministic
rolling-horizon heuristic.

CP-SAT / MILP is permitted later if justified by the scheduling formulation.

Reason:
The physical model must not depend on one optimization backend.

---

## D017 — V5 model completion is separate from paper completion

Decision:
V5 code-complete means the physical/operational model, twelve configurations,
validation, and pilot are complete.

Large Monte Carlo campaigns, paper figures, manuscript polishing, archival packaging,
and publication work follow after model freeze.

---

## D018 — No uncontrolled implementation

Decision:
Every substantive subversion follows:

science explanation
→ user understanding
→ design contract
→ read-only source audit
→ implementation plan
→ implementation
→ actual diff review
→ code explanation
→ focused tests
→ regression tests
→ numerical/scientific validation
→ user approval
→ commit/tag

No commit or tag occurs before approval.

---

## Deferred Features

Deferred unless validation shows they are required:

- full SGP4/TLE operational propagation
- high-fidelity atmospheric drag
- 6-DOF attitude dynamics
- electrochemical battery simulation
- finite-element thermal simulation
- complete RF BER/FER propagation
- machine-learning mission controller
- SAR payload physics
- hyperspectral payload physics
- real-time weather ingestion
- global operational ground network

---

## D019 — Isolated V5 namespace

Decision:
V5 foundation code lives under `ops_sim/v5`.

V4 imports do not depend on V5, and V5 pure-domain modules do not import the
legacy runtime.

---

## D020 — Stable typed identity

Decision:
Persistent identity uses explicit typed canonical IDs. Python `id()`,
process-randomized `hash()`, implicit timestamps, and automatically generated
random UUIDs are prohibited as persisted identity.

Human-facing labels remain separate from machine IDs.

---

## D021 — Parameter provenance primitives

Decision:
Scientific parameter provenance is immutable and machine-readable. Units are
explicit, and `1` represents a dimensionless quantity. V5.0B1 introduces no
physical parameter values.

Later constructible spacecraft configurations must enforce admissible
provenance status.

---

## D022 — Provenance-coupled physical values

Decision:
Every scientific scalar introduced into a constructible V5 spacecraft
configuration is represented by an immutable value/provenance pair.

`REJECTED` and `SUPERSEDED` provenance cannot enter a constructible
configuration. Parameter identity and units are validated by the owning domain
field.

---

## D023 — Deeply immutable spacecraft configuration

Decision:
`SpacecraftConfiguration` and every nested subsystem configuration are frozen
and slotted. Hardware configuration is the experimental independent variable
and cannot mutate during a simulation.

Human-facing labels remain separate from canonical machine IDs.

---

## D024 — Minimum constructible hardware shells

Decision:
V5.0B2 defines only the minimum ownership structure required before subsystem
science is approved. Deferred subsystem properties receive no invented
defaults.

Empty-looking communications, ADCS, thermal, and OBC shells are intentional
ownership boundaries, not claims that those subsystems have no physics.

---

## D025 — Runtime state domains are separated

Decision:
`SpacecraftState` contains spacecraft and onboard truth only.
`GroundKnowledgeState`, `MissionState`, `ControllerState`, and `Diagnostics`
are separate authoritative domains. The simulation clock does not belong to
spacecraft state.

---

## D026 — Ground knowledge is explicit and incomplete

Decision:
Ground operations do not receive a deepcopy of `SpacecraftState`.
`TelemetrySnapshot` defines exactly what information crossed the
spacecraft-ground boundary. Telemetry age is derived from timestamps rather
than stored as a mutable counter.

---

## D027 — Derived quantities are not duplicate mutable state

Decision:
SOC, delta-v used, elapsed ages, mission totals, current year, and similar
values are derived from authoritative state, configuration, and history.
Duplicate mutable representations are prohibited unless later justified.

---

## D028 — Diagnostics are non-causal

Decision:
Diagnostics observe transitions and accumulate research outputs. Physics,
onboard FDIR, and the professional ground controller must not use Diagnostics
as an implicit decision input.

---

## D029 — Operational mode and FDIR regime are distinct

Decision:
`OperationalMode` represents current spacecraft activity. `FDIRState`
represents the onboard fallback and protection regime. They may differ and
must not be forced into one redundant boolean or state representation.

---

## D030 — Controlled inputs are separate from spacecraft hardware

Decision:
Numerical, environment, flight-rule, and scenario configurations are immutable
controlled experiment inputs. They are not fields of
`SpacecraftConfiguration` or `SpacecraftState`.

---

## D031 — SimulationInputs enforces one coherent run definition

Decision:
`SimulationInputs` owns the immutable objects used by one run. `ModelManifest`
IDs must match all supplied input objects. Mixed hidden configuration objects
are rejected.

---

## D032 — CommonWorld is immutable and horizon-specific

Decision:
Compared spacecraft configurations share the same realised `CommonWorld`.
It uses stable event IDs and immutable tuples; no RNG or mutable event list is
retained in the realised world.

---

## D033 — SimulationContext is the complete runtime owner

Decision:
`SimulationContext` contains the authoritative clock and all future-relevant
mutable state domains. In V5.0B4 it represents only completed-step boundaries.
Future behavior must not depend on hidden state outside the context and
immutable inputs.

---

## D034 — Checkpoints are portable completed-step snapshots

Decision:
`CheckpointState` contains immutable snapshots of all authoritative mutable
domains and stable identities of immutable inputs. Restore requires matching
`SimulationInputs`. Mid-step checkpoints are deferred until an explicit
execution-phase model is justified.

---

## D035 — Cumulative diagnostics survive restart; caches do not

Decision:
Diagnostics are checkpointed to preserve cumulative research outputs.
Rebuildable caches, object identity, RNG instances, and ephemeral step-local
values are excluded.

---

## D036 — Seconds are the authoritative V5 engine timebase

Decision:
Simulation time and main-step duration are integer seconds.
`NumericalConfig.timestep_seconds` is the sole authoritative main-step dt.
The value 3600 has no privileged engine semantics.

---

## D037 — V5 engine is stateless across completed steps

Decision:
Future-authoritative state lives in `SimulationContext` or immutable
`SimulationInputs`. The engine owns no hidden clock, RNG, cache, controller
memory, or event history between completed steps.

---

## D038 — Step phase order is an explicit model contract

Decision:
The canonical order is world/environment → knowledge update → planning →
onboard arbitration → action execution → physical integration →
failure/capability resolution → diagnostics → clock advancement.

Later subsystem versions must integrate into this order explicitly.

---

## D039 — Successful steps are atomic with respect to pre-step validation

Decision:
All completed-context validation occurs before phase mutation. A validation or
horizon rejection leaves runtime state unchanged. One successful step advances
exactly one configured dt and increments `completed_steps` exactly once.

---

## D040 — Main-step intervals are half-open

Decision:
Every V5 main timestep represents `[start_time_seconds, end_time_seconds)`.
The start boundary is included and the end boundary is excluded. Adjacent
steps therefore partition time without overlap or double-counting.

---

## D041 — Simulation steps are transactional

Decision:
Substantive phases execute only against an independent working
`SimulationContext`. The caller's authoritative context is committed only
after all phases and post-step validation succeed. Any pre-commit exception
leaves the caller's context unchanged.

---

## D042 — Invalid proposed transitions are rejected before commit

Decision:
Post-step completed-context validation is mandatory. A phase that produces
invalid state causes the entire timestep to fail without partial mutation of
the authoritative context.

---

## D043 — Checkpoint/restore is the canonical state-cloning boundary

Decision:
Transactional working contexts are created through the explicit portable
checkpoint contract rather than an independent opaque deepcopy mechanism.
This keeps restart completeness and timestep atomicity aligned.

---

## D044 — Immutable run inputs retain identity across steps

Decision:
A successful transactional commit preserves the original `SimulationInputs`
object. Only authoritative mutable runtime domains and the clock are replaced
by their validated working results.

---

## D045 — Battery energy in Wh is authoritative

Decision:
V5 battery state stores energy in Wh. SOC is derived from stored energy and
usable capacity. V5.1A uses nominal energy as usable capacity; capacity fade
is deferred.

---

## D046 — Battery power limits use explicit bus-side semantics

Decision:
`max_charge_input_power_w` is bus power accepted before charge-efficiency
loss. `max_discharge_output_power_w` is bus power delivered after
discharge-efficiency loss. These conventions must remain explicit in future
EPS coupling.

---

## D047 — EPS resource boundaries require explicit accounting

Decision:
Excess available generation becomes `curtailed_generation_w`. Unsatisfied
demand becomes `unmet_load_w`. Capacity and zero-energy bounds may not be
hidden by silent clipping.

---

## D048 — Battery transitions are pure proposals

Decision:
V5.1A computes an immutable `BatteryTransition` without mutating authoritative
`BatteryState`. Engine integration and state application are deferred.

---

## D049 — Battery conversion losses are explicit

Decision:
Charge and discharge efficiency losses are represented in Wh. Energy
accounting is tested separately from mission behavior or thermal consequences.

---

## D050 — Spacecraft electrical load is component-wise

Decision:
V5 load demand is the sum of explicit bus-side subsystem contributions. An
operational mode does not directly own a watt value.

---

## D051 — Operational behavior activates hardware; hardware creates load

Decision:
Mission actions and subsystem behavior will determine component activity. The
resulting subsystem electrical demands feed the common load ledger.
Mode-specific magic power deltas or tables are prohibited from the primary V5
physics path.

---

## D052 — Total electrical load is derived

Decision:
`PowerLoadBreakdown` stores only named component contributions.
`total_load_w` is derived as their exact sum and is not duplicate mutable
state.

---

## D053 — Load accounting excludes generation and conversion losses

Decision:
Solar and other generation are modeled on the generation side of the EPS
balance. Battery charge/discharge conversion losses remain inside battery
physics. Neither is hidden inside spacecraft electrical load.

---

## D054 — PowerLoadBreakdown is transient, not authoritative state

Decision:
The load ledger describes one interval's requested bus demand. It is
recomputed from subsystem and action models and is not checkpointed as
future-authoritative state.

---

## D055 — Solar generation is a separate bus-side EPS source

Decision:
Solar generation is not represented as negative spacecraft load. V5.1C output
is directly compatible with the `generation_w` input of battery physics.

---

## D056 — V5.1C uses binary illumination

Decision:
Direct illumination has factor one and eclipse has factor zero. Partial
illumination and penumbra are deferred to later environment fidelity.

---

## D057 — V5.1C uses a one-sided cosine incidence law

Decision:
Incidence angle is measured between the panel normal and Sun direction.
Generation scales with `max(0, cos(theta))`; angles at or beyond 90 degrees
generate zero in this one-sided Level-1 model.

---

## D058 — Solar geometry is externally supplied in V5.1C

Decision:
`sunlit` and `incidence_angle_deg` are explicit runtime inputs. Orbit,
Sun-vector, attitude, and panel-normal calculations are deferred to their
owning models.

---

## D059 — Solar generation results are transient and derived

Decision:
`SolarGenerationResult` stores only nominal generation, illumination state,
and incidence angle. Illumination factor, incidence factor, and `generation_w`
are derived. The result is not authoritative state and is not checkpointed.

---

## D060 — EPS interval forcing is explicit

Decision:
V5.1D receives solar illumination/incidence and the requested component-load
ledger explicitly for each engine interval. The engine does not invent
temporary solar or load values.

---

## D061 — V5.1D integrates EPS only in PHYSICAL_INTEGRATION

Decision:
Solar generation, component load, and battery transition are composed during
the physical-integration phase. The pure proposed battery transition is
computed before its end energy is applied to the transactional working state.

---

## D062 — Missing EPS interval inputs preserve V5.0D compatibility

Decision:
`eps_inputs=None` performs no EPS physical evolution. This exists for
controlled compatibility and testing; it is not the intended final primary-run
behavior once the full EPS forcing pipeline is available.

---

## D063 — Physical truth does not automatically refresh ground knowledge

Decision:
A battery-energy change does not modify `TelemetrySnapshot`. New ground
knowledge requires an explicit future telemetry and knowledge-update path.

---

## D064 — EPS interval inputs and results are transient

Decision:
`EPSIntervalInputs` and `EPSIntervalResult` are not future-authoritative state
and are not checkpointed. The persistent physical consequence in V5.1D is the
resulting battery energy.

---

## D065 — Power insufficiency is a modeled outcome, not an integration exception

Decision:
Nonzero `unmet_load_w` and `curtailed_generation_w` do not automatically fail
a timestep. Their operational consequences belong to later FDIR and
failure/capability-resolution logic.

---

## D066 — Successful steps expose transient EPS accounting

Decision:
A successful engine step with EPS forcing returns the actual
`EPSIntervalResult` produced during physical integration. A no-EPS compatibility
step reports `None`. The result is exposed only after transactional commit.

---

## D067 — EPS conservation is independently observable

Decision:
Bus-energy, load-service, and battery-energy conservation residuals are
reported from the computed ledger. They are not rounded, clipped, or silently
corrected to zero.

---

## D068 — Composition links are validated explicitly

Decision:
The solar-to-battery generation link and load-ledger-to-battery load link each
have an explicit power residual. This makes composition inconsistencies
observable independently of internal energy conservation.

---

## D069 — Conservation tolerance is caller-controlled

Decision:
V5.1E defines no universal pass/fail tolerance. Callers must supply explicit
nonnegative absolute energy and power tolerances for their numerical context.

---

## D070 — EPS accounting remains non-authoritative

Decision:
`EPSIntervalResult` and `EPSConservationReport` are observational products, not
future-authoritative state. Checkpoints preserve the resulting battery truth,
not transient interval ledgers or reports.

---

## D071 — V5.1E freezes no new physical law or parameter

Decision:
V5.1E introduces no new physical law, parameter, threshold, controller action,
FDIR consequence, telemetry refresh, or hidden state. It reports the existing
V5.1A–V5.1D computations.

---

## D072 — Active resource boundaries land analytically

Decision:
When battery capacity or empty energy is the active limiter, V5 assigns the
mathematically exact boundary endpoint. Generic epsilon clipping is
prohibited.

---

## D073 — Runtime battery truth is configuration-relative

Decision:
A completed `SimulationContext` is valid only when battery energy lies between
zero and the nominal usable capacity of its active immutable configuration.
The same invariant applies to checkpoint creation and restoration.

---

## D074 — Step-result validation precedes authoritative commit

Decision:
Every potentially raising `StepResult` and physical-phase result validation is
completed before `_commit`. A failed step call cannot expose committed
authoritative state.

---

## D075 — Numerical representability failures are explicit

Decision:
EPS unit conversion and limiting arithmetic must not leak raw
`ZeroDivisionError` or `OverflowError` for admitted inputs. Genuinely
unrepresentable finite-output combinations fail with clear `ValueError`
rather than silent corruption.

---

## D076 — Aggregate requested load must be finite

Decision:
Individually finite component contributions are insufficient if their sum
overflows. `PowerLoadBreakdown` rejects a non-finite derived total.

---

## D077 — Admitted Real scalars must be operationally supported

Decision:
V5 numeric validators may admit `numbers.Real` implementations beyond
built-in `float` and `int`. Downstream arithmetic must not assume
implementation-specific scalar methods without a supported conversion
boundary. An admitted scalar implementation must either execute correctly or
fail intentionally with a documented `TypeError` or `ValueError`, never a raw
adapter exception.

---

## D078 — Aggregate load arithmetic is non-wrapping

Decision:
`PowerLoadBreakdown` remains the exact unweighted seven-component ledger.
Aggregate arithmetic must not inherit fixed-width integer overflow semantics
from an individual scalar implementation, and the derived total must be
finite and nonnegative.

---

## D079 — Thermal hardware is represented as an extensible lumped network

Decision:
V5 thermal configuration consists of immutable lumped thermal nodes and
undirected effective conductive links. The configuration is not restricted to
exactly three nodes.

---

## D080 — Three thermal roles are mandatory but not exhaustive

Decision:
Every thermal network identifies bus/electronics, battery, and payload roles.
Additional thermal nodes may be introduced later without replacing the
network model.

---

## D081 — Thermal node parameters have explicit physical ownership

Decision:
Heat capacity, emissivity, radiating area, and operating and survival
temperature bounds belong to a named thermal node. Runtime temperature is not
a hardware parameter.

---

## D082 — Thermal links own effective conductance

Decision:
A listed link represents one undirected effective conductive coupling in W/K.
Zero coupling is represented by absence of a link.

---

## D083 — V5.2A1 freezes no thermal numerical value

Decision:
This slice defines units, topology, identities, and provenance contracts only.
No real or reference spacecraft thermal property is introduced.

---

## D084 — Thermal fidelity may deepen without replacing the baseline architecture

Decision:
The network form intentionally supports later radiator, communications, ADCS,
propulsion, solar-array structure, or other nodes. Additional fidelity remains
subject to sensitivity and research relevance.

---

## D085 — ThermalNetworkConfig is owned by ThermalConfig

Decision:
The spacecraft thermal subsystem configuration contains one immutable generic
`ThermalNetworkConfig`. Runtime thermal truth is interpreted relative to this
active network.

---

## D086 — Runtime thermal truth is node-identified and extensible

Decision:
`ThermalState` stores mutable temperatures as `ThermalNodeState` values keyed
semantically by stable `ThermalNodeId`. Runtime state is not restricted to
three fixed temperature fields.

---

## D087 — Completed thermal truth must match the active network

Decision:
At completed-step boundaries, runtime thermal node identities must equal the
configured thermal-node identity set. Ordering is not semantic identity.
Operating and survival temperature limits are not structural validity bounds.

---

## D088 — Thermal truth advances checkpoint schema to version 2

Decision:
Because temperature is new authoritative runtime state, portable checkpoints
explicitly preserve it under schema version 2. Schema-1 snapshots do not
contain enough information for deterministic V5.2 thermal restart and are not
silently defaulted or inferred.

---

## D089 — Portable checkpoints normalize admitted numeric scalars for JSON

Decision:
Checkpoint serialization converts admitted `Real` scalar implementations to
JSON-native numeric primitives without mutating authoritative state.
Production checkpoint code remains independent of NumPy.

---

## D090 — V5.2A2 introduces state, not heat-flow physics

Decision:
A2 adds configuration-bound thermal truth, validation, transaction copying,
and checkpoint persistence only. No temperature evolution, heat-flow law,
FDIR response, or automatic telemetry refresh is introduced.

---

## D091 — Thermal links are evaluated once with signed conservative exchange

Decision:
Each undirected conductive link produces one signed heat flow from its two
start-of-interval temperatures. Equal and opposite node contributions preserve
internal conductive energy accounting.

---

## D092 — Radiation uses a signed effective sink boundary

Decision:
Each node exchanges radiation with an explicit transient effective sink using
epsilon sigma A (T_sink^4 - T^4). Positive radiative heat means energy enters
the node. The sink is not itself a spacecraft hardware parameter.

---

## D093 — Thermal transitions are simultaneous and identity-based

Decision:
All heat flows are evaluated from the complete start-of-interval temperature
vector before any proposed endpoint is formed. `ThermalNodeId`, not tuple
position, defines physical identity.

---

## D094 — V5.2B uses transparent explicit-Euler integration

Decision:
The initial Level-1 thermal transition uses
T_next = T + Q_net dt / C.
No hidden substeps or higher-order solver are introduced before convergence
evidence.

---

## D095 — Invalid thermal numerical endpoints are explicit failures

Decision:
Nonfinite, nonpositive, or unrepresentable proposed temperatures are rejected
with intentional errors rather than clipped, rounded, or silently corrected.

---

## D096 — V5.2B introduces only conduction and radiative exchange

Decision:
Internal subsystem heat, EPS conversion heat, absorbed solar/albedo/Earth-IR
forcing, heater behavior, degradation, FDIR interpretation, and engine mutation
remain deferred.

---

## D097 — Applied thermal heat is an explicit node term

Decision:
The source-aware thermal balance adds one signed applied-heat contribution per
configured `ThermalNodeId` while preserving the V5.2B conduction and radiation
laws.

---

## D098 — Battery conversion loss is deposited once at the battery thermal role

Decision:
V5.1 battery conversion-loss energy is converted to interval-average thermal
power and added exactly once to the configured battery thermal node.

---

## D099 — Electrical bus load is not automatically waste heat

Decision:
V5.2C1 does not assume that requested or served electrical component power is
identical to internal thermal dissipation. Internal dissipation remains an
explicit transient input until sourced routing semantics are introduced.

---

## D100 — External absorbed heat is explicit transient forcing

Decision:
Absorbed solar, albedo, and Earth-IR powers enter as explicit nonnegative
per-node thermal forcing. C1 does not calculate them from orbital geometry.

---

## D101 — Radiative sink and absorbed forcing must not double count

Decision:
The effective radiative sink boundary and explicit absorbed radiative forcing
must represent non-overlapping terms. The same incoming flux must not be
encoded in both.

---

## D102 — V5.2C1 remains pure coupling

Decision:
C1 produces transient source ledgers and a proposed thermal transition without
mutating authoritative state, engine behavior, checkpoints, telemetry, or
degradation state.

---

## D103 — Requested, served, and retained-heat power are distinct

Decision:
Component demand, electrical power actually served, and power retained inside
the modeled thermal network as heat are separate quantities.

---

## D104 — Component service allocation is explicit

Decision:
C2 requires a complete caller-supplied served-component ledger. Aggregate
unmet power does not imply component priority, proportional curtailment, or
any other allocation rule.

---

## D105 — Retained heat is routed by configuration

Decision:
Each electrical load component owns a provenance-backed retained-heat fraction
and a configured thermal-node destination. Multiple components may route heat
to the same node.

---

## D106 — Battery conversion heat remains separate from subsystem-load routing

Decision:
C2 routes heat retained from the seven subsystem load components only. V5.1
battery conversion loss remains the separate C1 battery-role heat term and is
not duplicated as a routing component.

---

## D107 — C2 freezes no component heat fraction

Decision:
C2 defines retained-heat parameter identities, units, bounds, routing, and
provenance contracts without assigning real spacecraft values. Material
fractions require sourced or explicit-assumption values and sensitivity study.

---

## D108 — Degradation modifies named physical capability

Decision:
V5.2D1 represents battery usable-capacity retention and solar-generation
retention directly. It introduces no generic health, condition, damage,
remaining-useful-life, or similar catch-all state.

---

## D109 — Battery throughput is authoritative degradation history

Decision:
Cumulative battery energy throughput in Wh is preserved as authoritative
runtime history. D1 introduces no arbitrary or inferred cycle counter.

---

## D110 — D1 defines degradation state, not ageing rates

Decision:
D1 owns initial conditions and checkpointed physical state only. No ageing
law, rate, Arrhenius term, empirical coefficient, or automatic evolution is
introduced.

---

## D111 — Effective EPS capability coupling is deferred

Decision:
Battery capacity retention and solar-generation retention do not yet modify
V5.1 EPS or solar physics. Applying retained capability is deferred until a
separate, validated coupling slice.

---

## D112 — Degradation truth is checkpointed but not automatically telemetered

Decision:
Portable checkpoints preserve degradation truth for deterministic restart.
D1 does not extend telemetry or imply that onboard degradation state is known
to the ground.

---

## D113 — Coupled EPS and thermal physics share one engine interval

Decision:
When all coupled inputs are supplied, the EPS and thermal proposals use the
same authoritative half-open engine interval and its single duration.

---

## D114 — EPS proposal precedes thermal forcing calculation

Decision:
The engine computes one EPS proposal first and passes that same interval
result to thermal coupling so its battery conversion loss enters the current
thermal interval exactly once.

---

## D115 — Coupled physical mutation is transactional

Decision:
Authoritative battery energy and thermal temperatures change only after both
pure proposals and their endpoints are valid. Any later step failure leaves
the caller's completed context unchanged.

---

## D116 — Thermal authoritative state updates by ThermalNodeId

Decision:
The engine matches proposed endpoint temperatures to runtime thermal state by
`ThermalNodeId`, independent of configuration or runtime tuple order.

---

## D117 — E1 introduces no same-step thermal feedback into EPS

Decision:
EPS uses start-of-interval battery state and explicit EPS inputs. Current
thermal endpoints do not modify the EPS proposal in the same interval.

---

## D118 — C2 service allocation remains explicit upstream input

Decision:
The engine consumes already-resolved thermal heat-source inputs. It does not
infer served-component allocation, load priority, or routing from aggregate
unmet electrical power.

---

## D119 — Repeated coupled execution is a release requirement

Decision:
The integrated EPS-to-thermal slice must remain valid, conservative, and
transactional over repeated completed engine steps, not only isolated cases.

---

## D120 — Integrated restart must reproduce uninterrupted execution

Decision:
Checkpoint capture, schema-3 JSON round trip, restore, and continuation must
produce the same authoritative endpoint as uninterrupted coupled execution.

---

## D121 — V5.2F1 demonstration is synthetic and non-operational

Decision:
The runnable demonstration is an explanatory reduced-order example, not flight
software, telemetry replay, operational prediction, or a KazEOSat-1 digital
twin.

---

## D122 — F1 adds no new physical law

Decision:
F1 reuses existing EPS, thermal, coupling, state, and checkpoint contracts. It
introduces no new equation, parameter claim, degradation evolution, or hidden
service-allocation rule.

---

## D123 — Battery degradation separates calendar and cycling damage

Decision:
D2A reports calendar and cycling retention damage separately before summing
them into one pure battery degradation proposal.

---

## D124 — V5 battery throughput is battery-side energy throughput in Wh

Decision:
Throughput is absolute battery-side stored plus extracted energy movement. It
is neither net SOC change nor literature charge throughput in Ah.

---

## D125 — D2A uses a linearized Level-1 damage accumulation model

Decision:
The simple linear damage law is an explicit reduced-order V5 modeling choice,
not a chemistry-specific or validated cell-lifetime model.

---

## D126 — Temperature acceleration is normalized to an explicit reference temperature

Decision:
Calendar and cycling damage use separate Arrhenius factors equal to one at the
configured reference temperature.

---

## D127 — Literature coefficients are not transferred across incompatible chemistry or throughput definitions

Decision:
Cell-specific fitted coefficients are not copied into V5 without compatible
chemistry, stress variables, units, provenance, and sensitivity evidence.

---

## D128 — Solar degradation remains explicit until radiation environment exists

Decision:
D2A accepts explicit solar-retention loss only. It introduces no elapsed-time,
radiation-dose, equivalent-fluence, or fixed-percent-per-year law.

---

## D129 — C1 battery conversion heat is not a complete electrochemical heat model

Decision:
C1 conversion heat remains a Level-1 irreversible-loss proxy; reversible
entropic and deeper chemistry-dependent heat terms remain deferred.

---

## D130 — Conflicting public KazEOSat values remain source-specific until resolved

Decision:
V5 records conflicting mass, lifetime, orbit, productivity, and power claims
with their own sources rather than silently selecting one production value.

---

## D131 — Battery ageing model parameters belong to immutable degradation configuration

Decision:
Ageing coefficients and reference temperature are immutable run configuration,
not mutable state or transient forcing.

---

## D132 — Degradation configuration and degradation physics have an acyclic dependency boundary

Decision:
`BatteryAgeingModelConfig` is defined independently of `BatteryConfig` so
configuration may own it while pure degradation physics consumes both.

---

## D133 — Immutable ageing configuration does not change checkpoint schema

Decision:
Schema-3 checkpoints continue to contain mutable degradation truth only;
restore receives the immutable configuration through `SimulationInputs`.

---

## D134 — Coupled engine intervals evolve battery degradation

Decision:
Every complete coupled EPS-and-thermal engine interval produces one battery
degradation proposal from the same interval's physical results. No-physics and
EPS-only compatibility paths do not evolve degradation.

---

## D135 — Representative battery temperature is endpoint arithmetic mean

Decision:
D2B2 uses `(T_battery,start + T_battery,end) / 2` as the interval
representative battery temperature. This trapezoidal Level-1 approximation is
not a claim of linear temperature evolution and remains subject to timestep
and convergence study.

---

## D136 — Battery throughput uses the same EPS proposal and active battery config

Decision:
Battery-side throughput is derived once from the exact `EPSIntervalResult` and
active `BatteryConfig` used by the current engine interval. The engine accepts
no alternate caller-supplied battery configuration and duplicates no
throughput equation.

---

## D137 — Current-interval degradation does not feed back into current EPS/thermal

Decision:
EPS and thermal proposals use start-of-interval authoritative state. Their
current results drive the degradation endpoint; that new endpoint does not
modify EPS or thermal capability in the same interval. Capability coupling is
deferred to E2.

---

## D138 — Solar degradation evolves only from explicit engine forcing

Decision:
Solar-generation retention changes only when a complete coupled interval also
receives an explicit `SolarDegradationForcingInput`. D2B2 introduces no hidden
elapsed-time, radiation, or fixed-rate solar law.

---

## D139 — Zero damage coefficients do not suppress throughput history

Decision:
Zero calendar and cycling damage coefficients preserve battery capacity
retention, but a coupled interval still records actual battery-side energy
throughput. Usage history and retention damage are separate physical truths.

---

## D140 — Degradation mutation is part of the physical transaction

Decision:
Battery energy, thermal temperatures, battery degradation, and optional solar
degradation mutate the working context only after every current-interval
proposal and endpoint is valid. Any failure preserves the caller's complete
pre-step context and object identities.

---

## D141 — Start-of-interval retention determines current EPS capability

Decision:
Every EPS interval derives battery and solar capability from authoritative
degradation retention at the interval start.

---

## D142 — Battery retention scales usable energy capacity, not power limits

Decision:
Battery retention multiplies nominal energy capacity only. Charge and
discharge power limits and efficiencies remain independently configured.

---

## D143 — Solar retention scales nominal generation before geometry

Decision:
Solar retention multiplies nominal generation once, before illumination and
incidence geometry are applied.

---

## D144 — End-of-interval capacity reconciliation is explicit

Decision:
If the degradation endpoint lowers usable capacity below proposed stored
energy, an observable reconciliation reports the unavailable energy and makes
the endpoint capacity authoritative.

---

## D145 — Reconciliation unavailable energy is not bus load or thermal heat

Decision:
Unavailable energy records loss of modeled usable stored-energy availability.
It is not load, curtailment, conversion loss, unmet demand, or thermal forcing.

---

## D146 — Capacity fade does not proportionally rescale sub-capacity stored energy

Decision:
When proposed stored energy remains within the new usable capacity, it is
preserved exactly and reconciliation reports zero unavailable energy.

---

## D147 — Degradation endpoint affects EPS beginning with the next interval

Decision:
Current EPS and thermal proposals use start retention. A newly computed
degradation endpoint can change capability only for subsequent intervals.

---

## D148 — Invalid start energy above degraded usable capacity is rejected

Decision:
An EPS physics request whose start energy exceeds start-of-interval usable
capacity is invalid and fails transactionally without silent correction.

---

## D149 — V5.2 release requires integrated timestep-refinement evidence

Decision:
The V5.2 release gate includes one fixed-physical-time coupled scenario at
successively refined timesteps and requires consistent endpoint refinement.

---

## D150 — F2 does not freeze a universal V5 timestep

Decision:
F2 records local refinement evidence for the completed V5.2 slice. V5.8
retains ownership of broader timestep selection and numerical methodology.

---

## D151 — Explicit-Euler thermal behavior is checked analytically

Decision:
The thermal release audit compares the explicit-Euler result with the
independent equal-capacity two-node conduction solution and requires endpoint
error to decrease under refinement.

---

## D152 — Completed E2 state remains inside degraded EPS capability

Decision:
Every audited completed coupled step must leave authoritative stored battery
energy at or below its reconciled degraded usable capacity.

---

## D153 — Raw EPS conservation remains distinct from reconciliation

Decision:
EPS conservation is assessed on the raw EPS proposal. Endpoint capacity
reconciliation remains a separate observable transaction result.

---

## D154 — V5.2 release requires replay and schema-3 restart equivalence

Decision:
Identical forcing must reproduce every step result and final context, and a
JSON schema-3 checkpoint continuation must match uninterrupted execution.

---

## D155 — V5.2 release requires transactional failure isolation

Decision:
The release audit must show that representative horizon, input, capability,
thermal, battery-degradation, and solar-degradation failures preserve caller
state and mutable object identities.

---

## D156 — F2 adds no new physical law

Decision:
F2 adds tests and release evidence only. It changes no production equation,
parameter, physical model, checkpoint schema, or engine behavior.

---

## D157 — V5.3 separates target, request, and observation opportunity

Decision:
A geographic ground target, mission imaging request, and candidate observation
opportunity are distinct immutable input concepts.

---

## D158 — Observation opportunities are explicit until orbit geometry exists

Decision:
V5.3A accepts upstream opportunity windows and pointing directions without
computing visibility. Later V5.6 orbit and geometry work owns their generation.

---

## D159 — Opportunity pointing is spacecraft-local

Decision:
Opportunity view angle and abstract local-orbital-frame azimuth describe a
spacecraft-local direction and are not silently equated with surface incidence.

---

## D160 — Viewing limits belong to spacecraft configuration

Decision:
Platform viewing envelopes, including the public approximate KazEOSat-1 value,
belong to later spacecraft capability configuration, not generic target geometry.

---

## D161 — Published agility is a maneuver anchor, not a constant rate

Decision:
The public 60 degree in 90 second agility statement is recorded as one maneuver
anchor and is not divided into a universal constant slew rate or settling law.

---

## D162 — KazEOSat-like acquisition respects simultaneous five-band evidence

Decision:
The Airbus statement that all five bands are acquired simultaneously prevents
V5.3A from inferring independent physical PAN-only and MS-only acquisitions.

---

## D163 — Physical optical acquisition is separate from product-mode labels

Decision:
`PayloadMode` values remain product/output-view capabilities. Immutable optical
acquisition configuration separately owns the physical simultaneous-band truth.

---

## D164 — KazEOSat-like acquisition is simultaneous PAN plus four MS bands

Decision:
The later KazEOSat-like reference configuration must represent one PAN and four
multispectral bands acquired simultaneously rather than detector-family switches.

---

## D165 — Published resolution is a Level-1 reference sampling proxy

Decision:
Published spatial resolution may support reference sample spacing, but it is
not claimed as exact detector pitch, raw GSD, cadence, or off-nadir sampling.

---

## D166 — Payload acquisition power is separate from other power demands

Decision:
Acquisition power is requested payload electrical power only. Thermal control,
ADCS, platform, communications, storage, and retained heat remain separate.

---

## D167 — WMO 90 W is a candidate, not a 180 W split model

Decision:
The WMO OSCAR 90 W instrument value remains a LITERATURE VALUE candidate and
does not justify 90 W imaging plus 90 W thermal control or any 180 W model.

---

## D168 — Compression remains explicit and unfrozen

Decision:
NAOMI heritage supports compression capability but not one KazEOSat-specific
algorithm or ratio. B1 freezes neither, and B2 remains uncompressed-equivalent.

---

## D169 — B2 consumes explicit footprint and duration

Decision:
B2 accepts effective cross-track width, effective along-track length, and
imaging duration as independent transient inputs; it derives none from orbit.

---

## D170 — Payload data volume is an uncompressed ground-sample-equivalent proxy

Decision:
B2 sample and data quantities are continuous Level-1 sample-grid equivalents,
not exact detector read counts or measured onboard file sizes.

---

## D171 — B2 does not infer strip length from imaging duration

Decision:
No orbital velocity, ground-track velocity, line rate, or pointing law converts
B2 imaging duration into along-track footprint length.

---

## D172 — Physical acquisition channel selection is distinct from product modes

Decision:
B2 physical PAN/MS detector-family selection neither imports nor branches on
the product/output-view capabilities represented by `PayloadMode`.

---

## D173 — 270 Mbit/s is not an acquisition data-generation rate

Decision:
The published X-band instrument telemetry characteristic is not used to derive
B2 detector samples, acquisition bits, or data volume from duration.

---

## D174 — Payload acquisition energy is requested electrical energy P*t

Decision:
B2 reports `E_requested = P_requested * t / 3600` in Wh without claiming that
EPS served the complete requested payload power.

---

## D175 — Acquisition energy is not automatically thermal heat

Decision:
B2 performs no heat conversion or routing. V5.2C2 remains the owner of later
served-power and retained-heat relationships.

---

## D176 — Reference nadir swath is not a generic B2 feasibility bound

Decision:
B2 does not clip or reject an explicit effective width against the configured
reference nadir swath; later geometry and capability models own feasibility.

---

## D177 — B2 introduces no compression or packet/file overhead

Decision:
B2 freezes no compression algorithm, ratio, reduction factor, telemetry
framing, packet overhead, file overhead, or container-width conversion.

---

## D178 — V5.3C begins with a Level-1 boresight maneuver model

Decision:
V5.3C begins with configuration-owned boresight viewing and maneuver-time
capability; it does not introduce a full attitude-dynamics execution model.

---

## D179 — Boresight direction is not complete spacecraft attitude

Decision:
A payload boresight direction does not uniquely specify spacecraft roll about
that direction, full body attitude, angular velocity, or actuator state.

---

## D180 — Angular separation requires a common comparison frame

Decision:
Maneuver angular separation is meaningful only after both boresight directions
are expressed in one explicit common frame. C1 performs no frame conversion.

---

## D181 — Viewing limit and maneuver separation are distinct quantities

Decision:
Maximum view angle from nadir constrains one commanded boresight direction;
maneuver separation compares two directions and may be larger.

---

## D182 — Slew duration is configuration-owned through an anchor envelope

Decision:
C1 owns an ordered envelope of angular-separation and elapsed-time anchors
rather than a universal rate, acceleration, or actuator law.

---

## D183 — The public 60 deg / 90 s value is one anchor, not a constant rate

Decision:
The Airbus agility statement is one maneuver anchor and is not divided to
create a constant slew rate or used to infer a complete maneuver law.

---

## D184 — Post-slew settling is a separate explicit parameter

Decision:
Settling time is owned separately from slew elapsed time and is not inferred
from the anchor envelope or folded into its values.

---

## D185 — Out-of-envelope maneuver duration will not be extrapolated

Decision:
C1 defines no evaluation law. Later C2 will reject maneuver separations outside
the configured envelope rather than extrapolate duration.

---

## D186 — Product location accuracy is not ADCS pointing accuracy

Decision:
Published product location accuracy is not adopted as spacecraft pointing,
stability, performance-error, or attitude-knowledge capability.

---

## D187 — APE, RPE, knowledge error, and full quaternion dynamics remain deferred

Decision:
APE, RPE, PDE, attitude knowledge error, full quaternion state, actuator
dynamics, and maneuver execution remain outside C1.

---

## D188 — C2 compares boresights only in one explicit common frame

Decision:
C2 compares two boresight direction vectors only when their caller-supplied
common Cartesian comparison-frame identities are exactly equal.

---

## D189 — Boresight vectors are normalized for comparison, not stored state

Decision:
C2 admits nonzero non-unit vectors and normalizes them transiently without
changing the immutable caller-supplied direction components.

---

## D190 — Angular separation uses cross magnitude and dot product

Decision:
C2 evaluates `gamma = atan2(||u_start × u_end||, u_start · u_end)` in degrees,
without inverse-cosine clipping or tolerance-based angle repair.

---

## D191 — Maximum view angle is not a C2 separation cap

Decision:
C2 does not apply the configured maximum view angle because an arbitrary
comparison frame carries no nadir-axis or observation-feasibility semantics.

---

## D192 — Slew time is piecewise-linear between configured anchors

Decision:
C2 linearly interpolates elapsed time only between the ordered C1
angular-separation anchors that bracket the computed separation.

---

## D193 — Exact anchor matches use exact configured time

Decision:
When computed separation exactly equals an anchor angle, C2 returns that
anchor's configured elapsed time with no interpolation.

---

## D194 — C2 does not extrapolate beyond the anchor envelope

Decision:
C2 rejects separation above the last configured anchor rather than clamping,
extending the final slope, or substituting the final anchor time.

---

## D195 — Settling follows nonzero slew exactly once

Decision:
C2 adds configured post-slew settling once after every nonzero in-envelope
slew and keeps settling separate from anchor elapsed times.

---

## D196 — Zero angular change has zero transition time

Decision:
Exactly equal boresight directions produce zero slew, zero settling, and zero
total transition time even when configured settling is positive.

---

## D197 — C2 remains boresight-only without actuator or energy dynamics

Decision:
C2 adds no full attitude state, quaternion dynamics, actuator behavior,
angular-rate law, ADCS power demand, or maneuver-energy relationship.

---

## D198 — C3 pairs local observation geometry with explicit common-frame boresight input

Decision:
C3 pairs each observation opportunity with a caller-supplied common-frame
boresight while preserving both representations as distinct inputs.

---

## D199 — C3 does not derive common-frame attitude from ObservationPointing

Decision:
C3 performs no orbit, frame, or trigonometric conversion from local
`ObservationPointing` values into common-frame boresight directions.

---

## D200 — View-envelope feasibility and maneuver separation remain distinct

Decision:
C3 checks each local off-nadir view against the configured maximum separately
from C2 common-frame angular separation and transition timing.

---

## D201 — Slew begins only after the previous acquisition completes

Decision:
The previous scheduled start plus its imaging duration defines the earliest
instant at which C3 permits the following slew to begin.

---

## D202 — Earliest next start respects both window opening and ADCS readiness

Decision:
C3 uses the later of the next window opening and the completed transition plus
settling time as the earliest candidate start for that opportunity.

---

## D203 — Exact latest legal start remains feasible

Decision:
A candidate start exactly equal to window end minus imaging duration is
feasible; C3 applies no timing tolerance or discretization.

---

## D204 — C2 out-of-envelope timing remains unsupported, not infeasible

Decision:
C3 propagates C2 out-of-envelope failure because absent transition-time model
coverage does not demonstrate physical spacecraft infeasibility.

---

## D205 — Frame mismatch is invalid composition, not mission infeasibility

Decision:
C3 propagates different-frame failure because boresight separation is
undefined without the deferred frame transformation.

---

## D206 — C3 computes transition internally from active inputs

Decision:
C3 computes one C2 transition from the active pointing configuration and the
two candidate boresights; it accepts no external transition result.

---

## D207 — C3 adds no resource, scheduler, controller, or engine behavior

Decision:
C3 evaluates one specified opportunity pair using view, ADCS timing, and
window fit only, without resource service, selection, or state mutation.

---

## D208 — V5.3D composes reviewed C3 feasibility with B2 acquisition physics

Decision:
V5.3D evaluates one specified next acquisition by composing the reviewed C3
sequence result with the reviewed B2 optical-acquisition calculation.

---

## D209 — Opportunity and payload acquisition duration must match exactly

Decision:
The opportunity and optical-acquisition input must carry the same exact
integer imaging duration because they describe one acquisition attempt.

---

## D210 — Effective footprint remains an explicit caller input

Decision:
V5.3D derives no footprint dimension from pointing, timing, swath, speed, or
orbit geometry; later geometry work may supply those explicit B2 inputs.

---

## D211 — Supported C3 infeasibility short-circuits payload acquisition

Decision:
When C3 reports a supported infeasibility, V5.3D returns that sequence result
without evaluating B2 acquisition demand.

---

## D212 — C3 and B2 results are computed internally from active inputs

Decision:
V5.3D accepts no external C3 or B2 result and invokes each reviewed function
from the active configurations and candidate inputs.

---

## D213 — C3 and B2 exceptions remain invalid or unsupported composition

Decision:
V5.3D propagates C3 frame/envelope failures and B2 request/configuration
failures instead of inventing a new physical-infeasibility classification.

---

## D214 — D preserves B2 requested-energy and sample-grid-proxy semantics

Decision:
V5.3D preserves B2 requested payload power and energy and its uncompressed
Level-1 sample-grid proxy without claiming service or execution.

---

## D215 — D adds no swath cap, compression, or 270 Mbit/s acquisition law

Decision:
V5.3D neither caps footprint width by reference swath nor introduces
compression or interprets telemetry rate as acquisition generation.

---

## D216 — D adds no resource, scheduler, state, or engine behavior

Decision:
V5.3D performs pure composition only, without resource feasibility,
opportunity selection, controller behavior, or runtime-state mutation.

---

## D217 — E1 reuses the reviewed D and EPS physics

Decision:
V5.3E1 computes the active V5.3D acquisition evaluation internally and then
reuses the existing degradation-aware EPS capability and interval transition;
it duplicates none of their physical equations.

---

## D218 — Acquisition power is added exactly once to payload demand

Decision:
For a D-feasible acquisition, E1 adds requested acquisition power exactly once
to the caller-supplied non-acquisition `payload_w`; a nonzero payload standby or
background demand remains part of the combined request.

---

## D219 — Aggregate EPS shortfall does not allocate component service

Decision:
Existing aggregate served and unmet bus power identifies no payload-first,
platform-first, proportional, priority, or load-shedding allocation, and E1
introduces none.

---

## D220 — Acquisition service is represented by allocation-free bounds

Decision:
With acquisition request `A`, aggregate request `R`, aggregate service `S`, and
other request `B = R - A`, E1 reports the exact bounds
`P_min = max(0, S - B)` and `P_max = min(A, S)` rather than an actual allocation.

---

## D221 — E1 has three exact full-service classifications

Decision:
E1 reports `FULLY_SERVED` when `P_min = A`, `FULL_SERVICE_IMPOSSIBLE` when
`P_max < A`, and `SERVICE_ALLOCATION_REQUIRED` otherwise, without a tolerance
or probabilistic interpretation.

---

## D222 — Requested acquisition energy is not served energy

Decision:
The nested B2 energy remains full requested acquisition energy. E1 separately
reports lower and upper served-acquisition energy bounds over the same imaging
duration and does not relabel requested energy as service.

---

## D223 — Partial electrical service does not scale image output

Decision:
E1 does not scale footprint, sample counts, bits, bytes, or image quality from
an electrical-service bound because no payload performance-versus-power or
partial-image law exists.

---

## D224 — Start-of-interval degradation capability is applied exactly once

Decision:
E1 calls the existing EPS capability calculation once and passes that result
once to the existing EPS interval transition, preserving the reviewed battery
capacity-retention and solar-retention semantics.

---

## D225 — E1 evolves no degradation and adds no battery power fade

Decision:
E1 reads start degradation state without evolving it, applying endpoint
degradation, scaling battery charge or discharge power limits, or reconciling
an authoritative battery endpoint.

---

## D226 — The E1 EPS result remains a pure transient proposal

Decision:
E1 mutates no battery, degradation, mission, or spacecraft state and returns
the existing EPS interval result only as a transient proposal.

---

## D227 — Thermal, storage, and engine coupling remain deferred

Decision:
E1 adds no heat routing, thermal evolution, storage or data mutation, downlink,
checkpoint, controller, scheduler, or engine integration; later slices own
those behaviors.

---

## D228 — E2 requires explicit complete component service

Decision:
V5.3E2 requires a caller-supplied complete `ServedPowerLedger` covering all
seven electrical-load components and delegates its validation to the reviewed
V5.2 served-power routing layer.

---

## D229 — E2 derives no allocation from E1 service bounds

Decision:
E2 does not construct component service from E1 acquisition-service bounds,
status, aggregate served load, or aggregate unmet load; no electrical
allocation, priority, proportional-curtailment, or load-shedding law is added.

---

## D230 — Served PAYLOAD power is not necessarily served acquisition power

Decision:
Because E1 combines acquisition and non-acquisition payload demand, the
ledger's served `PAYLOAD` value is total served payload power and is not an
exact acquisition-service or acquisition-specific-heat quantity.

---

## D231 — E2 reuses V5.2 retained-heat routing

Decision:
E2 requires the existing explicit `ComponentHeatRoutingConfig` and reuses
`P_heat,k = P_served,k * f_heat,k` without changing its route, provenance,
unit, or retained-fraction contracts and without inventing defaults.

---

## D232 — Routed internal heat replaces internal-source placeholders

Decision:
E2 uses the reviewed composition in which routed internal heat replaces, rather
than adds to, supplied per-node internal-dissipation placeholders while solar,
albedo, and Earth-IR absorbed heat remain unchanged.

---

## D233 — Existing EPS/thermal coupling solely owns battery conversion heat

Decision:
E2 delegates battery conversion-loss heat to the existing EPS/thermal coupling
exactly once and does not add it to routed component heat, external heat, or a
second battery source.

---

## D234 — E2 inherits acquisition EPS duration as thermal dt

Decision:
E2 passes the exact E1 EPS interval duration to thermal coupling and exposes no
independent thermal timestep, rounding, quantization, or substepping control.

---

## D235 — E2 returns one explicit-Euler interval proposal

Decision:
The E2 thermal output is one V5.2 explicit-Euler proposal over the acquisition
interval; it is not evidence of timestep adequacy, convergence, stability, or
continuous-time exactness, which remain V5.8 concerns.

---

## D236 — Thermal ranges do not decide acquisition feasibility

Decision:
Configured operating and survival ranges remain reportable physical context;
E2 adds no thermal feasibility classification and may return a numerically
valid positive endpoint outside those ranges.

---

## D237 — E2 mutates no authoritative state

Decision:
E2 returns a pure transient proposal without committing thermal, battery,
degradation, spacecraft, data, or mission state. F remains the owner of
authoritative transaction, commit, rollback, and runtime integration.

---

## D238 — F begins with context-independent scheduled acquisition identity

Decision:
V5.3F begins with an immutable, context-independent contract pairing one
explicitly selected `ObservationAcquisitionCandidate` with one exact
nonnegative built-in-integer scheduled start. Construction establishes
schedule structure only, not execution authorization or success.

---

## D239 — Scheduled acquisition reuses existing opportunity-window validation

Decision:
F1 reuses `ScheduledObservationExecution` to validate the candidate maneuver's
scheduled start against its opportunity window. It duplicates no window-start,
latest-start, duration, or end-time arithmetic.

---

## D240 — Imaging execution identity uses existing ImagingRequestId, ObservationOpportunityId, and scheduled start; no new execution ID

Decision:
F1 preserves the complete acquisition candidate; its nested `ImagingRequestId`
and `ObservationOpportunityId` together with scheduled start provide scheduled-
execution identity. No new `StableId`, `CommandId`, `ManeuverId`,
`DataProductId`, or standalone execution ID is introduced.

---

## D241 — MissionRequestId and ImagingRequestId remain distinct in V5.3F

Decision:
`MissionRequestId` and `ImagingRequestId` remain distinct typed identities. F1
performs no value-string comparison or conversion; the conceptual
`MissionImagingRequestBinding` is deferred to V5.7 and is not implemented in
F1.

---

## D242 — Engine-step boundary equality belongs to later runtime authorization

Decision:
Because F1 has no `SimulationContext`, it does not require scheduled start to
equal the current engine-step start. Exact engine-boundary compatibility
belongs to later F2/F3 runtime authorization.

---

## D243 — Acquisition-duration/engine-dt equality belongs to later runtime authorization

Decision:
Because F1 has no `NumericalConfig`, it does not compare acquisition duration
with configured engine dt. Exact duration/dt compatibility belongs to later
F2/F3 runtime authorization.

---

## D244 — F1 adds no physical execution, mission mutation, product state, or checkpoint state

Decision:
F1 evaluates no sequence, EPS, thermal, or degradation physics; commits no
execution; mutates no mission or spacecraft state; creates no product or
storage state; and adds no persistent or checkpointed field or schema change.

---

## D245 — F2 binds authorization to the current context snapshot without mutation

Decision:
V5.3F2 reads the active `SimulationContext` configuration and state and returns
only transient authorization evidence. It mutates no context, spacecraft,
mission, diagnostic, or simulation-time state.

---

## D246 — Selected scheduled start must equal current engine-step boundary

Decision:
The selected scheduled start must equal current context time exactly. After a
feasible E1 result, that start must also be no earlier than C3's exact
`candidate_next_start_seconds`, with no tolerance or rounding.

---

## D247 — Acquisition duration must equal configured engine timestep

Decision:
F2 requires acquisition duration to equal the active numerical configuration's
engine timestep exactly. A mismatch is an invalid current-interval request,
not sequence infeasibility.

---

## D248 — F2 performs no duty-cycle averaging or implicit substep

Decision:
F2 does not average or rescale acquisition power or energy across a different
engine duration, split the interval, quantize time, or introduce an implicit
substep.

---

## D249 — E1 is computed internally from active context configuration/state

Decision:
After boundary and duration validation, F2 calls E1 exactly once with the
active agile-pointing, optical-acquisition, EPS, battery, and degradation
objects. It accepts no alternate physical snapshot and does not call D
separately.

---

## D250 — Supported sequence infeasibility is a non-authorization result

Decision:
A supported D/C3 sequence-infeasible E1 result returns
`SEQUENCE_INFEASIBLE` without constructing component service or invoking E2.
Invalid or unsupported evaluation failures continue to propagate.

---

## D251 — Only exact full electrical service with zero unmet load proceeds

Decision:
Electrical authorization proceeds only when E1 reports `FULLY_SERVED` and the
aggregate EPS unmet load is exactly zero. Any other service status or nonzero
unmet load returns `ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED` without E2.

---

## D252 — Zero aggregate unmet load uniquely determines all components fully served

Decision:
When aggregate served power equals aggregate requested power and every
component is bounded by its request, all seven component values are uniquely
`served=requested`. F2 constructs that complete ledger only in this special
case; it introduces no shortfall allocation, priority, or shedding rule.

---

## D253 — F2 computes E2 internally only after exact electrical authorization

Decision:
Only after exact electrical authorization, F2 calls E2 exactly once with the
derived all-served ledger, active thermal state and network, and explicit
routing and heat inputs. E2 failures propagate, and thermal operating or
survival ranges add no F2 authorization rule.

---

## D254 — AUTHORIZED is a transient prerequisite result, not an engine commit or mission/product success

Decision:
`AUTHORIZED` means only that the narrow current-step boundary, duration,
sequence, electrical-service, and thermal-proposal prerequisites succeeded. It
does not commit state, evolve degradation, create a `StepResult`, store an
image, or establish mission or product success; F3 owns the transaction.

---

## D255 — F3A introduces one reusable private engine transaction kernel

Decision:
V5.3F3A factors the existing `SimulationEngine.step` transaction machinery
into one private kernel. Generic stepping retains the same behavior while the
kernel provides the single outer-transaction owner required by F3B.

---

## D256 — Delayed physical-handler preparation preserves validation precedence

Decision:
The public step supplies a zero-argument physical-handler factory. The kernel
validates the completed context before invoking that factory to validate and
bundle transient inputs, preserving the existing exception precedence.

---

## D257 — Physical handler remains inside the existing PHYSICAL_INTEGRATION phase

Decision:
The prepared handler is invoked exactly once and only in the existing
`PHYSICAL_INTEGRATION` phase. It receives the checkpoint-restored working
context and the same `StepInterval` observed by every phase; no phase is added.

---

## D258 — Public step signature, phase vocabulary, and StepResult remain unchanged

Decision:
F3A changes neither the public `SimulationEngine.step` signature nor the phase
enum and order. `StepResult` retains its exact fields, validation, exports, and
semantics and is constructed once for each successful transaction.

---

## D259 — Transaction operates on one checkpoint-restored working context and commits once

Decision:
The kernel captures and restores one checkpoint, runs all phases against that
isolated working context, validates the completed context and result, and then
commits exactly once and last. Any earlier failure leaves authoritative state
unchanged because no commit occurs.

---

## D260 — Coupled degradation/reconciliation/state-application tail has one private owner

Decision:
One private tail owns the existing battery-throughput, representative-
temperature, degradation, optional solar-degradation, capacity-reconciliation,
endpoint-validation, and working-state-application sequence. Its equations,
ordering, and mutation timing are unchanged.

---

## D261 — Checkpoint schema 3 and persistent state remain unchanged

Decision:
F3A changes no checkpoint serialization or restore semantics, adds no
persistent transaction or strategy state, and leaves checkpoint schema 3
unchanged.

---

## D262 — F3A is imaging-free and only prepares the F3B integration seam

Decision:
F3A imports no imaging module and adds no imaging execution, authorization,
status, result, or public API. It introduces only the private transaction and
physical-handler seams that later F3B may use.

---

## D263 — F3B adds dedicated step_imaging on the shared transaction kernel

Decision:
V5.3F3B adds a dedicated `SimulationEngine.step_imaging` entry point that uses
the same private transaction kernel as generic stepping. The generic `step`
signature and behavior remain unchanged.

---

## D264 — F2 authorization is computed inside the restored working transaction

Decision:
The delayed imaging handler computes F2 authorization exactly once during the
physical-integration phase against the checkpoint-restored working context,
not the authoritative context or an independently prepared physical snapshot.

---

## D265 — Supported nonauthorization aborts the transaction with no commit

Decision:
`SEQUENCE_INFEASIBLE` and `ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED` return a
transient imaging attempt with no `StepResult`. A private control path aborts
the transaction before degradation, reconciliation, clock or diagnostic
advance, result construction, and authoritative commit.

---

## D266 — Authorized imaging reuses exact F2 EPS/capability/thermal proposal objects

Decision:
Authorized imaging passes the exact EPS interval, EPS capability, and thermal
coupling objects nested in the F2 result into the engine transaction. Object
identity in the resulting `StepResult` proves that no parallel proposal was
substituted.

---

## D267 — Imaging never recomputes generic EPS or thermal integration

Decision:
The imaging handler neither invokes generic `_physical_integration` nor calls
D, E1, or E2 separately. F2 remains the sole owner of its D/E1/E2 composition,
so one authorized imaging attempt has one physical causal chain.

---

## D268 — Shared degradation/reconciliation tail completes authorized imaging once

Decision:
After authorization, the shared coupled tail runs exactly once to compute
battery throughput, representative temperature, battery degradation, optional
solar degradation, capacity reconciliation, validation, and working-state
application without changing their equations or ordering.

---

## D269 — Ordinary imaging/physical failures propagate with atomic rollback

Decision:
Only the two supported nonauthorization statuses use private control flow.
All ordinary imaging, thermal, degradation, reconciliation, result-validation,
and final-context failures propagate, and checkpoint isolation prevents any
authoritative commit.

---

## D270 — Successful result means resource-served imaging interval committed

Decision:
An `AUTHORIZED` attempt with a `StepResult` means only that the resource-served
imaging interval completed the existing physical/runtime transaction and was
committed once, including one diagnostic and clock advance.

---

## D271 — Mission completion, product/storage, and controller policy remain deferred

Decision:
F3B does not complete a mission request, create or store a data product, bridge
mission and imaging request identities, choose a target or opportunity, or add
scheduling, controller, allocation, or delivery policy.

---

## D272 — Imaging attempt evidence is transient; checkpoint schema remains 3

Decision:
`ImagingEngineStepAttempt` is returned transiently and is not stored in engine,
spacecraft, mission, or checkpoint state. Replay requires caller-supplied
imaging inputs, and checkpoint schema 3 remains unchanged.

---

## D273 — Variable-duration imaging remains deferred to V5.8

Decision:
F3B retains F2's exact acquisition-duration/effective-engine-timestep equality
and adds no partial interval, substep, duty-cycle averaging, time quantization,
or event splitting. Variable-duration integration remains V5.8 work.

---

## D274 — F4A provides one deterministic end-to-end V5.3 imaging demonstration

Decision:
V5.3F4A adds one executable example that deterministically demonstrates the
reviewed observation, ADCS, acquisition, EPS, authorization, heat-routing,
thermal, engine, degradation, reconciliation, and commit chain. Its four cases
start from independent equivalent contexts and use public reviewed APIs.

---

## D275 — Authorized demo means resource-served interval commit only

Decision:
The authorized case demonstrates one resource-served imaging interval committed
through the existing engine transaction, including its physical endpoints,
degradation, reconciliation, diagnostic increment, and clock advance. It is not
mission/request completion, product creation, storage, downlink, or delivery.

---

## D276 — Sequence and both electrical nonauthorization classes are demonstrated without commit

Decision:
F4A separately demonstrates supported sequence infeasibility, full-service
impossibility, and service-allocation-required electrical shortfall. Each
returns the reviewed nonauthorization evidence with no `StepResult` and leaves
the authoritative starting context unchanged.

---

## D277 — 20×20 km sample-grid arithmetic remains a Level-1 proxy, not file size

Decision:
The independent 20 km by 20 km PAN-plus-four-MS-band reference check reports
400,000,000 PAN samples, 25,000,000 samples per MS band, 100,000,000 total MS
samples, 500,000,000 total samples, 6,000,000,000 bits, 750,000,000 decimal
bytes, and 15 Mbit/km². These are DERIVED LEVEL-1 SAMPLE-GRID PROXY quantities,
not measured onboard data or a stored, downlinked, or delivered file size.

---

## D278 — Demo replay requires caller-resupplied imaging inputs and schema remains 3

Decision:
F4A demonstrates equivalent direct and checkpoint-restored authorized runs by
resupplying the same explicit imaging inputs. Equal attempts and committed
contexts establish deterministic replay without persisting transient imaging
evidence, and checkpoint schema 3 remains unchanged.

---

## D279 — F4A introduces no production physics, state, controller, storage, or variable-duration behavior

Decision:
F4A changes no production module and introduces no physical or numerical law,
persistent state, mission mutation, product or storage model, controller or
scheduler policy, orbit conversion, partial interval, substep, duty-cycle
averaging, or variable-duration execution behavior.

---

## D280 — F4B is verification/freeze only and changes no production model

Decision:
V5.3F4B adds release-audit evidence and no production feature, physical or
numerical equation, configuration parameter, persistent state, execution
behavior, or public production API. The reviewed V5.3 implementation remains
unchanged while its release claims and boundaries are frozen for human review.

---

## D281 — V5.3 release audit covers geometry, acquisition, EPS bounds, thermal, and transactional execution

Decision:
The final V5.3 audit independently checks observation-domain contracts,
common-frame boresight geometry, configured slew timing, optical sample-grid
arithmetic, allocation-free EPS service bounds, served-power heat routing, and
the atomic imaging-engine causal chain.

---

## D282 — V5.3 final evidence includes all supported nonauthorization and rollback classes

Decision:
Release evidence covers sequence infeasibility and both electrical
nonauthorization classifications as noncommitting results. Boundary, duration,
frame, slew-envelope, composition, thermal, degradation, reconciliation,
completed-context, and result-validation failures propagate while preserving
authoritative values and object identities.

---

## D283 — Sample-grid quantities remain acquisition proxies, not storage/product truth

Decision:
V5.3 sample, bit, and byte quantities remain continuous Level-1 acquisition
sample-grid proxies. They do not establish compressed or packetized size,
stored bytes, product creation, downlink, delivery, or mission completion.

---

## D284 — Mission/request binding, storage, controller, orbit conversion, and variable-duration integration remain deferred

Decision:
F4B adds none of the deferred mission-to-imaging identity bridge, onboard
storage and communications behavior, controller target selection, opportunity
or common-frame generation from orbit, or variable-duration and multirate
execution. Existing later-slice ownership remains unchanged.

---

## D285 — No misleading V5.3 timestep-refinement claim is made because acquisition duration is currently tied to engine dt

Decision:
Current imaging authorization requires acquisition duration to equal the engine
timestep. F4B therefore does not vary that timestep and present the resulting
change in physical acquisition duration as a convergence study; V5.8 retains
general refinement, substepping, multirate, and event-method ownership.

---

## D286 — Checkpoint schema remains 3 and imaging replay requires explicit caller-resupplied inputs

Decision:
V5.3 adds no imaging attempt or result to persistent checkpoint state.
Equivalent replay restores schema-3 authoritative state and requires the caller
to resupply the same observation, acquisition, resource, routing, and thermal
inputs before executing the imaging transaction again.

---

## D287 — V5.3 is release-candidate complete pending human review and tag

Decision:
With the F4B verification and regression gates passing, the implemented V5.3
scope is release-candidate complete. This status is evidence for human actual
review and a possible later `v5.3-final` tag; F4B neither creates nor claims
that tag.

---

## D288 — V5.4A1 preserves V5.3 acquisition data as continuous equivalent-bit bookkeeping

Decision:
V5.4A1 uses equivalent bits as its canonical unit and copies the exact
`OpticalAcquisitionResult.uncompressed_equivalent_bits` value. Initially,
stored equivalent volume equals uncompressed equivalent volume; this identity
means only that the model applies no reduction, not that real spacecraft
hardware performs no compression. A1 adds no rounding, overhead, record
identity, storage state or admission, checkpoint, engine, communications, or
mission behavior.

---

## D289 — V5.4A2 gives each onboard acquisition-data record an explicit caller-supplied identity

Decision:
`AcquisitionDataRecordId` is caller supplied, never model generated, and is
distinct from `ImagingRequestId`, `ObservationOpportunityId`,
`MissionRequestId`, and `DataProductId`. `OnboardAcquisitionDataRecord` is an
immutable eight-field Level-1 record description; request and opportunity IDs
provide lineage rather than uniqueness. Its continuous stored and uncompressed
equivalent-bit quantities remain exactly equal under the current
identity/no-reduction rule. A standalone record does not establish spacecraft
storage commit, and A2 adds no storage state or capacity admission, checkpoint,
engine, communications, mission, or product behavior.

---

## D290 — V5.4B1 uses decimal-GB whole-record storage admission in equivalent bits

Decision:
The existing `StorageConfig.usable_capacity_gb` is interpreted as decimal GB,
where 1 GB equals 8,000,000,000 bits. Occupancy is derived deterministically
with `math.fsum` from stored-record equivalent-bit volumes. The authoritative
hypothetical total is `math.fsum` over the complete ordered sequence of
existing volumes plus the candidate; it is not reconstructed from the rounded
stored-before subtotal. A complete record is admissible exactly when that total
is less than or equal to capacity; the exact-full boundary is admitted.
Duplicate record IDs reject. B1 adds no overwrite, eviction, partial storage,
persistent state, checkpoint, or engine behavior. Insufficient capacity is only
a pure B1 result, not yet an engine nonauthorization outcome.

---

## D291 — V5.4B2 makes ordered acquisition-data records persistent spacecraft truth and increments checkpoint schema to 4

Decision:
`DataStorageState` owns exactly the insertion-ordered tuple of immutable
`OnboardAcquisitionDataRecord` values. It is an explicit mutable peer at
`SpacecraftState.data_storage`; construction has no hidden empty default,
duplicate record IDs reject, and request and opportunity lineage may repeat.
No redundant occupancy or capacity field is stored in the state.

`SimulationContext` owns the active storage-capacity invariant and reuses the
V5.4B1 decimal-GB and complete-sequence `math.fsum` semantics. Checkpoint
schema advances from 3 to 4 so the ordered records are persistent restart
truth. The ordinary current parser accepts schema 4 only and rejects schema 3;
it does not invent an empty historical storage state. B2 adds no admission-
policy change, imaging record creation or append, record removal, overwrite or
eviction, compression, communications or downlink, mission/product completion,
storage/OBC power, throughput, or variable-duration behavior.

---

## D292 — V5.4C composes physical imaging authorization with whole-record storage admission without mutation

Decision:
F2 runs exactly once. Any supported V5.3 nonauthorization stops before
data-volume or storage-admission work. An F2-authorized attempt reuses its exact
nested `OpticalAcquisitionResult`; A1 produces the exact equivalent-bit
proposal, and the A2 record uses the caller-supplied `AcquisitionDataRecordId`
with the existing scheduled-execution request, opportunity, timing, and channel
lineage.

B1 evaluates admission against current persistent stored-record truth.
Insufficient capacity is a supported pure nonauthorization result, while
duplicate record identity remains an exception. C performs no state mutation
or engine commit and adds no physical recomputation, storage append, removal,
communications, mission/product completion, compression, throughput, or power
model.

---

## D293 — V5.4D1 constructs transaction completion evidence before authoritative commit

Decision:
The shared `_run_transaction` kernel validates the completed working context,
constructs and validates exactly one `StepResult`, and then optionally invokes
one private precommit result factory to construct and validate richer public
completion evidence. Authoritative commit occurs only after all completion-
result construction succeeds; factory failure propagates with no commit and
complete authoritative value and identity rollback. After `_commit`, the
kernel performs only a bare return of the already-created result.

Generic `step` behavior is unchanged. The existing `step_imaging` signature,
result contract, authorization evidence, physical equations, and supported
nonauthorization behavior are unchanged, while its authorized outer attempt is
now constructed before commit. D1 retains one checkpoint, one restore, one
nine-phase loop, one `StepResult`, and one commit. It adds no imaging-to-storage
engine integration, storage authorization or append/removal, schema change,
physical recomputation, mission or communications behavior, power model, or
new physical source, numerical value, or literature basis.

---

## D294 — V5.4D2 atomically commits one storage-authorized imaging interval and one onboard acquisition-data record

Decision:
`authorize_imaging_storage_execution` executes exactly once during
`PHYSICAL_INTEGRATION` on the restored working context. Either supported C
nonauthorization status aborts without physical or storage commit. For an
authorized result, the engine reuses the exact V5.3 EPS and thermal evidence,
runs the shared physical and degradation tail exactly once, and then appends
the exact C-proposed record to the working context's ordered storage after the
physical tail succeeds.

Final completed-context validation checks the postappend storage state, and
the D1 precommit seam constructs the outer attempt before the single
authoritative commit. The physical endpoint and record therefore commit
atomically. Duplicate record identity and ordinary failures propagate with
complete transaction rollback. The existing `step` and `step_imaging` APIs
and behavior remain unchanged.

D2 performs no second admission evaluation or capacity arithmetic and adds no
mission, communications, record-removal, compression, throughput, or
storage/OBC-power semantics.

---

## D295 — V5.4E demonstrates deterministic storage accumulation, capacity rejection, and schema-4 replay without new model physics

Decision:
V5.4E adds integration evidence, not a new production model. A deterministic
synthetic demonstration drives only the public V5.4D2 engine API for at least
twelve consecutive authorized intervals. Each successful transaction advances
the physical state once and appends exactly one ordered acquisition-data record;
reporting derives occupancy from the complete record sequence with `math.fsum`.

An uninterrupted run and a run split through the full schema-4 JSON checkpoint
pipeline produce equal interval rows and equal final contexts, with a fresh
restored mutable state graph. A separate capacity case derives its synthetic
capacity from the actual demonstrated record size: the exact-full third record
commits, while the next whole record returns insufficient capacity with no
physical or storage commit and complete authoritative identity preservation.

E changes no production module, physical equation, checkpoint schema, or
authorization policy. It adds no eviction, removal, downlink, communications,
mission/product completion, compression, throughput, storage/OBC-power model,
new physical source, recorder-capacity calibration, or KazEOSat recorder-
hardware claim.

---

## D296 — V5.4 is release-candidate complete pending human review and tag

Decision:
V5.4F is verification and freeze evidence only. It changes no production
module, equation, configuration value, state, checkpoint schema, runtime
behavior, or public API. It also changes no physical source, literature source,
or spacecraft value. F fixes only test/evidence defects and historical
assertions.

The final gate verifies the A1-through-E causal chain and its authoritative
ownership boundaries, continuous equivalent-bit semantics, decimal-GB capacity
and complete-sequence `math.fsum`, exact-full admission, and schema-4
persistence and restart. It verifies pure C composition, D1 precommit safety,
D2 atomic physical-plus-record commit and rollback, backward compatibility, and
E accumulation, replay, and capacity evidence. Green focused and full release
gates make the implemented frozen Level-1 scope **RELEASE-CANDIDATE COMPLETE**
pending human review and explicit tag creation.

F does not create or claim `v5.4-final`. Release-candidate status does not claim
external calibration, flight qualification, operational validation, real
recorder fidelity, or KazEOSat-1 digital-twin status.

---

## D297 — V5.5A defines externally supplied serviceable contacts and nominal X-band capacity

Decision:
V5.5A adds typed `GroundContactId` and `GroundStationId` values and an
immutable `ServiceableGroundContact` containing exactly contact identity,
station identity, and a positive half-open integer-second
`[start_time_seconds, end_time_seconds)` interval. Serviceability is supplied
externally; V5.5A derives no orbit, AOS/LOS, visibility, elevation, or station
geometry.

`CommunicationsConfig` now requires `nominal_downlink_data_rate_bps` with
`ParameterId("communications.nominal-downlink-data-rate")` and units `bit/s`.
The KazEOSat-like reference value is `270_000_000.0 bit/s`, classified PUBLIC
SPECIFICATION and sourced to the Airbus KazEOSat-1 technical sheet. It is
interpreted only as a nominal X-band data-link rate, not detector generation,
recorder-write, RF-symbol, protocol-adjusted or measured net, or guaranteed
operational throughput.

The pure `compute_downlink_capacity` relation is `nominal_contact_capacity_bits
= nominal_downlink_data_rate_bps × serviceable_contact_duration_seconds`. It
returns complete finite built-in-float evidence, performs no mutation, and
applies no arbitrary efficiency factor or RF/link-budget correction. A adds no
persistent communications state, checkpoint-schema change, partial
transmission, record removal or delivery, engine behavior, communications
power or thermal coupling, controller policy, or mission/product completion.

---

## D298 — V5.5B makes delivery and partial-transfer progress authoritative persistent truth

Decision:
`GroundDataDeliveryState` is a required top-level `SimulationContext` peer
after ground knowledge and before mission state. It owns insertion-ordered
tuples of strictly positive `DownlinkTransferProgress` values and immutable
`CompletedAcquisitionDelivery` values. Record identity is the uniqueness
boundary; repeated request or opportunity lineage and reuse of one completing
contact remain valid.

Context validation binds each partial-transfer ID to exactly one current
onboard record and requires transmitted equivalent bits to remain strictly
below that record's stored equivalent bits. Completed record IDs are disjoint
from partial progress and current onboard storage. A completed acquisition must
end no later than its completing contact begins, and that contact must end no
later than current simulation time. Zero progress is represented by absence;
no remaining-bit, backlog, utilization, counter, or cached-total field is
stored. A partial transfer retains the full onboard record.

The live checkpoint advances from schema 4 to schema 5 and requires ordered
`ground_data_delivery` progress and completion payloads. The schema-5 parser
rejects schema 4 before inspecting schema-specific shape and performs no silent
empty-state migration. Existing engine transactions carry and validate the new
peer but do not change it. B adds no transmission evaluator, `step_downlink`,
record removal, communications EPS/thermal evolution, scheduling or controller
behavior, orbit-derived contact, `DataProductId`, or customer, product, or
mission completion. It changes no physical source, provenance value, or
spacecraft numerical value.

---

## D299 — V5.5C evaluates pure partial or complete service of one onboard acquisition record

Decision:
V5.5C adds one context-free evaluator for one selected onboard acquisition
record and one externally supplied serviceable contact. It obtains represented
nominal capacity only through `compute_downlink_capacity`, uses only
`record.stored_equivalent_bits` for transmission arithmetic, and treats absent
progress as exactly `0.0`. Supplied progress must identify that record and be
strictly between zero and its stored total.

Capacity greater than or equal to represented remaining bits produces exact
COMPLETE evidence: progress becomes the stored total, remaining becomes zero,
and the full stored quantity is identified as freed. Lower capacity produces
PARTIAL evidence using complete-pair `math.fsum`; the represented progress must
strictly increase without reaching the total, remaining bits must strictly
decrease while staying positive, and freed storage is zero. The boundary uses
no tolerance, rounding, quantization, or repair of lost floating-point
increments. Unused capacity and utilization are explicit finite evidence.

C produces transient evidence only. It performs no state mutation, record
movement, completed-delivery creation, clock advancement, checkpoint or engine
change, and adds no `step_downlink`. Communications power and concurrent physical
evolution are not modeled during V5.5 downlink bookkeeping. COMPLETE denotes
link-service completion of one acquisition record, not mission, product, or
customer completion. C adds no physical source, provenance value, spacecraft
numerical value, contact geometry, scheduling, or controller policy.

---

## D300 — V5.5D atomically applies one caller-selected downlink result through the shared engine transaction

Decision:
`SimulationEngine.step_downlink` accepts one explicit onboard acquisition
record ID and one externally supplied serviceable contact exactly aligned to
the current full engine step and within the common-world horizon. Request,
contact, context, and alignment validation occur before checkpoint capture.
The existing `_run_transaction` kernel then supplies one checkpoint-isolated
working context, complete-context validation, precommit result construction,
and one authoritative commit.

Inside the working context, D rejects an already delivered or absent selected
record, reuses its optional persistent progress, and invokes the V5.5C
`evaluate_downlink_transmission` evaluator exactly once. PARTIAL replaces the
selected progress tuple slot or appends one new strictly positive progress
value while retaining the full onboard record. COMPLETE moves the exact full
record from onboard storage to one appended `CompletedAcquisitionDelivery` and
removes its progress. Other records, progress values, and completed deliveries
retain relative order and immutable identity. One contact services only the
caller-selected record; unused capacity is not reassigned.

Both PARTIAL and COMPLETE are successful committed steps. Dedicated
`DownlinkEngineStepResult` evidence is constructed before commit and wraps the
exact C transmission result plus the canonical `StepResult`. The physical
handler returns `None`, so every EPS, thermal, degradation, and capability
field in that step result is `None`; only normal time, diagnostics, and required
storage/delivery state advance. Communications power and concurrent physical
evolution are not modeled during V5.5 downlink bookkeeping.

D retains checkpoint schema 5 and adds no transmission arithmetic, second-
record allocation, automatic selection or scheduling, orbit-derived contact,
controller policy, link retry or acknowledgement behavior, power or thermal
communications model, or mission, product, or customer completion. It adds no
new physical source, provenance value, or spacecraft numerical value.

---

## D301 — V5.5E demonstrates multi-contact delivery, restart, and whole-record storage release

Decision:
V5.5E adds no production behavior. It demonstrates the already committed
V5.5A-D contracts through a synthetic four-contact scenario with one
caller-selected record per interval, repeated partial progress, later complete
delivery, and explicit unused capacity that is not reassigned to another
record. Partial service retains the full onboard record; completion releases
the complete stored volume as whole-record storage release.

The demonstration includes a portable schema-5 JSON checkpoint/restart after
the first contact, exact direct-versus-restarted final equality, and a
deterministic repeat from a fresh context. Communications power and concurrent
physical evolution are not modeled during V5.5 downlink bookkeeping. E adds no
physical source, numerical spacecraft value, scheduling or controller policy,
orbit-derived contact, mission/product/customer completion, or release tag.

---

## D302 — V5.5 is release-candidate complete pending human review and tag

Decision:
V5.5F is verification and freeze evidence only. F changes no production
module, equation, configuration value, state, checkpoint schema, runtime
behavior, or public API. It adds no new physical source, literature value, or
spacecraft numerical value. The final focused, compatibility, demonstration,
and complete-repository gates verify V5.5A-E as one immutable causal and state
chain.

After green gates, the bounded implemented V5.5 scope is
**RELEASE-CANDIDATE COMPLETE** pending final human review and explicit tag
creation. This means internal release evidence for the implemented scope only;
it does not mean external calibration, flight qualification, operational
validation, real delivered-throughput validation, or KazEOSat-1 digital-twin
status. F does not create or claim `v5.5-final`. Explicit annotated-tag
creation remains a separate human-reviewed action.

---

## D303 — V5.6A establishes explicit TT and model Earth/frame transforms

Decision:
The author-approved V5.6A scope is standalone immutable time, reference-shape,
geographic and frame evidence plus pure elementary transforms. Its production
owners are `ops_sim/v5/orbit_config.py` and `ops_sim/v5/frames.py`; no existing
production module, engine clock, context, checkpoint, ADCS or observation
contract changes. The live checkpoint remains schema 5.

TT is explicit in `TTEpoch`: an integer Julian-day component and a canonical
fraction in `[0,1)`. Julian-date integer boundaries are TT noon, not civil
midnight. There is no default epoch or date, timezone, UTC/leap-second parsing,
TDB conversion or ephemeris-time alias. `GeometryInstant` carries the explicit
reference epoch and signed elapsed seconds, allowing fractional geometry time
without changing integer engine execution time. Split-date mapping performs
day carry on exact rational forms of admitted binary inputs and rounds only
the final fractional day; reverse mapping subtracts split components before
rounding elapsed seconds. Tiny offsets below representation resolution can
round away, but no large Julian-date float is formed.
For reverse mapping the seconds envelope applies after nearest-binary64
rounding; this permits a rounded split date at an elapsed endpoint to map back
to that endpoint. A representable seconds result outside the envelope rejects.

Reference shape independently stores only provenance-bearing `a` and `f`.
The named WGS84 values are `a=6_378_137.0 m`, reciprocal flattening
`298.257223563`, and derived `f=1/298.257223563`. The optional named nominal
rate is `7.292115e-5 rad/s`. S008 records verified primary passages and separates
published reference parameters, derived equations, and model assumptions.
Geographic input names its ellipsoid and explicitly requires geodetic latitude,
east longitude, and ellipsoidal height. Ranges are `[-pi/2,pi/2]` and
`[-pi,pi)` radians. Constructors do not wrap angles or assume height zero.
Supported negative heights satisfy `h > -a*(1-f)^2`, excluding the inward
normal-coordinate fold/degeneracy domain without imposing nonnegative height.

The right-handed model frames share Earth centre and north z. EARTH_FIXED x
points to latitude/longitude zero; MODEL_INERTIAL axes are nonrotating model
comparison axes. Complete immutable definitions carry shape, explicit TT
epoch, initial phase and rate/provenance, not merely frame-kind labels.
Uniform rotation `theta=theta0+omega*t` is an EXPLICIT MODEL ASSUMPTION.
Both phase and signed rate are explicit inputs; zero rate is supported.
No TT date implies initial orientation. These frames are not full GCRS/ITRS,
TEME, ITRF or SPICE J2000, and no actual ERA/UT1 relationship is implemented.

The active convention is `Rz=((c,-s,0),(s,c,0),(0,0,1))`:
`rI=R*rF`, `vI=R*vF+Omega cross rI`; the inverse subtracts the rotational
velocity term before applying `R.T`. Directions rotate without a translational
term or implicit normalization. Position and velocity evidence must have equal
frames and instants before forming a state. Every public transform revalidates
nested inputs, including forged immutable provenance, preserves evaluation time,
and returns new immutable evidence. Different-time directions in the same fixed
inertial definition retain compatible axes. No local frame or ADCS adapter is
introduced. Geodetic conversion returns position and reference-surface normal;
the latter is generally distinct from the geocentric radial direction.

Supported arithmetic limits are `abs(day)<=2**31-1`, `abs(elapsed)<=2**40 s`,
and `abs(omega*t)<=2**20 rad`. The ellipsoid requires `(1-f)^2>=2**-40` and
finite positive derived radii. These are numerical representation/conditioning
limits, not mission-horizon or final-accuracy decisions. Inputs normalize to
finite binary64; bool and lossy integer-to-float conversion are rejected.
Fractional-day rounding is at most about 4.8 ps; elapsed binary64 spacing near
`2**40 s` is about 244 microseconds. The shared phase evaluator reduces by
binary `tau`; its argument-reduction error is bounded separately from model
fidelity. Overflow rejects rather than clipping or snapping results.

Independent tests use hand-solvable axes/spheres/states, Decimal support-function
ellipsoid references, and a separately generated complex-derivative velocity
reference, including a decades-scale elapsed time. Their explicitly scaled
numerical bounds are recorded in S008 and the tests; they are not orbit/contact
accuracy claims. Runtime functions and tests require no network, new dependency,
SPICE installation, Earth-orientation download, or ephemeris dataset.

A propagates no orbit, generates no contact/opportunity, and implements no
visibility, serviceability, maneuver, controller, or checkpoint integration.
Geometry input binding and future spacecraft-specific maneuver persistence
remain unresolved integration work. This decision approves no propagator,
J2, maneuver law, final orbit accuracy, or remaining successor roadmap.

## D304 — V5.6B1 adds pure bound two-body Cartesian propagation

Decision (author-approved B1 scope, 2026-09-14):
`ops_sim/v5/orbit.py` adds a standalone deterministic evaluator from one
authoritative initial Cartesian state and explicit gravitational parameter to
a Cartesian state at a requested instant. `TwoBodyTrajectory(initial_state,
gravitational_parameter_m3_s2)` and `TwoBodySolverConfig(time_tolerance_seconds,
max_iterations)` are frozen, slotted and default-free. The public evaluator is
`evaluate_two_body_state(trajectory, instant, solver_config) -> CartesianState`.
The optional `nominal_earth_gravitational_parameter()` factory supplies NGA's
general geocentric `398_600_441_800_000.0 m^3/s^2`, PUBLIC_SPECIFICATION /
VERIFIED, with the existing `nga-wgs84-defining-parameters` record. It is not
the separate GPS-user value or a spacecraft calibration. Synthetic mu values
carry explicit model-assumption provenance.

A is committed at `b3dcd0deb76199523092bbea3c4d688dfd73cf83`. B1 reuses its
Cartesian position/velocity/state, complete frame, TT epoch/GeometryInstant,
and narrow numeric/provenance validators. Every call revalidates the complete
nested graph, including at zero duration. Only MODEL_INERTIAL initial states
are admitted; requested and initial instants share the same reference TT epoch.
Duration is requested elapsed seconds minus the initial elapsed seconds, which
need not be zero. Exact rational subtraction avoids large Julian-date floats.
Output retains the complete original frame and actual requested instant.
Earth rotation metadata is not orbital angular velocity and is not applied.

The adopted force is `r_ddot=-mu*r/|r|^3`. A scaled universal-variable root and
one Lagrange reconstruction path operate directly on Cartesian inputs; no
classical-element conversion or legacy proxy is used in production. S008 and
the module derive the scaling, signs, residual units and cancellation-safe g.
An analytic monotone root bracket safeguards Newton/bisection; Stumpff C/S use
bounded small-argument series and stable trigonometric identities. The solver
accepts only when absolute reduced time residual plus its documented working
roundoff allowance is at most the explicit tolerance. That tolerance is not a
global position or operational error guarantee. Unresolved binary64 accuracy,
stagnation, invalid arithmetic and iteration exhaustion raise visible errors.
No last-iterate success, clipping, tolerance inflation or invariant projection.

The admitted family is nondegenerate bound ellipses, including circles, with
derived `e <= 1-2^-8`; radius, gravitational speed and time scales each lie in
`[2^-128,2^128]` in SI units, with finite supported derived arithmetic.
`abs(dt)<=2^40 s` and `abs(dt/period)<=2^20` independently constrain the span.
These are numerical-domain choices, not the supported domain of SPICE or a
mission horizon. Pericentre is computed stably from `p/(1+e)`, where
`p=|r cross v|^2/mu`, and must be strictly outside the sphere of the frame
ellipsoid's equatorial radius. A relative `64*2^-53/(1-e)` pericentre arithmetic
uncertainty band rejects ambiguous clearance; it adds no physical altitude
margin. This conservative sphere rule guarantees reference-shape clearance
within that numerical policy, can reject otherwise exterior ellipses, and is
not atmosphere/terrain clearance, operational altitude policy, collision
detection or exact ellipsoid intersection.

Long queries subtract an integer multiple of the rounded binary64 period
exactly before one final rounding, and use the reduced time consistently in
the solver and reconstruction. The actual requested timestamp is retained.
The root residual is separate from accumulated period/invariant phase error;
S008/tests give explicit scale-aware budgets, including period error times
revolution count. Near-period queries are never rounded to a period by policy.

Independent verification combines exact-binary analytic circles, signed and
inclined/retrograde cases, and 90-digit Decimal elliptic Kepler propagation
derived from the same admitted binary initial r/v/mu. A 110-digit recomputation
checks reference precision. Nonzero initial radial velocity, near-circular,
high-eccentricity, multiple-period and long queries are included. Position and
velocity are checked independently; energy, angular momentum, eccentricity,
short-interval recovery/reanchoring and deterministic query order supplement
them. Numerical budgets distinguish root, phase, reconstruction and reference
error. All verification inputs are synthetic, not measured spacecraft states.

Pre-commit numerical-evidence correction (2026-09-14): independent review
reproduced accepted states outside the original `vmax*eta` / `amax*eta` endpoint
budgets. The retained signed residual gives, for coherent exact coefficients,
`r_hat=r_star(t+delta)-v0*delta` and
`v_hat-v0=(R_star/R_hat)*(v_star(t+delta)-v0)`.
With V0=|v0|, eta bounding the residual plus evaluation allowance, and
`D=rp-V0*eta>0`, root contributions are `(vmax+V0)*eta` metres and
`amax*eta+V0*eta*(vmax+V0)/D` metres/second. D<=0 establishes no finite velocity
bound by this argument. Phase, rounded coefficients/vector reconstruction and
reference uncertainty remain separate; the solver tolerance is still a root
residual request. The full working budget requires `V0*eta/rp<=2^-10` and
position reconstruction allowance below D/2, separate from production admission.
The 256u arithmetic allowance remains a working policy, not a certified bound.

S008 records the two exact-binary red/green regressions and corrected signed
coverage. The prescribed 1000-case supplementary sweep has 989 accepted
endpoints within corrected budgets and 11 explicit accuracy rejections;
six accepted outputs exceeded an original budget. The original 64-case output
errors remain unchanged; their old ratios are historical. The pre-correction
3309-test full run remains historical evidence and did not detect this gap.
Fresh corrected-candidate evidence: 186 B1 tests, 124 unchanged A tests,
264 H plus V5.5 A-F tests, and one full run of 3326 passed in 179.98 seconds.
All green gates exit 0 with no skips or xfails; the two original-budget
counterexamples first failed intentionally before the correction.
No executable propagator, independent reference orbit, central-force model,
solver acceptance, input, or supplied regression tolerance changed. This
correction updates uncommitted D304; it adds no D305 or B2 approval.

Each query begins from the original initial state; there is no mutable orbital
state, cache or previous-query time. No altitude, elements, period, current
position/velocity or repeated epoch/frame is persisted in the public trajectory.
There is no context, common-world, engine, controller or checkpoint dependency,
and no physical evolution during downlink. Existing production paths and
checkpoint schema 5 remain unchanged. B2 immutable-input/run/checkpoint binding
is outstanding. B1 generates no contacts or opportunities and adds no local
orbital frame, ground-track or ADCS adapter. J2, drag, third bodies, radiation
pressure, maneuvers/delta-v, stationkeeping, propulsion ranges and final
comparative-study/long-horizon orbit adequacy remain unresolved. This decision
does not complete V5.6 or approve those later contracts.

## D305 — Content-bound coast inputs and checkpoint recomputation (2026-09-14)

The bounded B2 contract attaches frozen/slotted `CoastOrbitInputs(trajectory,
solver_config)` to one run's immutable `SimulationInputs`, using the new
keyword-only `coast_orbit: CoastOrbitInputs | None = None`. The default means
no orbit binding. It supplies no implicit orbit and preserves the original
seven positional arguments. CommonWorld and spacecraft hardware/state do not
own this per-run trajectory or a mutable propagation cache. A/B1 definitions,
propagator, admission rules and numerical budgets are unchanged.

`CoastOrbitInputs.to_dict()` / `from_dict(payload)` provide a strict portable
definition codec, separate from checkpoint state. Representation version 1 and
model discriminator `v56b1-elliptic-two-body` encode the initial Cartesian r/v,
their shared validated instant (split TT day/fraction and elapsed seconds),
complete frame kind/ellipsoid/rotation, mu and solver tolerance/iteration limit.
The rotation's epoch is explicit and must agree with the instant reference.
Ellipsoid name, all five ScalarParameters and all supported provenance are
included: parameter ID, classification, units, ordered source IDs, status,
rationale, derivation and optional lower/upper sensitivity bounds. Optional
values are explicit nulls. The graph is revalidated through A/B1 constructors
before encoding; shared position/velocity definitions cannot hide a mismatch.

Normalized finite binary64 fields use canonical `float.hex()` strings;
integers remain exact integers. Readers reject missing/extra keys, wrong types,
unknown versions/models, alternate/nonfinite numeric encodings and invalid
reconstructed domains. Text and ordered sequences are not normalized or sorted.
There is no reflection-based object codec, executable deserialization, network
access or runtime code-file hashing.

Pre-commit text correction (2026-09-14): independent review reproduced a str
subclass hiding the reserved manifest namespace, plus three Unicode identity
aliases and three JSON round-trip losses. All seven review regressions failed
intentionally against the pre-repair candidate. B2 portable text now requires
exact built-in str and strict UTF-8 encodability: no surrogate code points
U+D800-U+DFFF, including a pair stored as two Python characters. Valid non-BMP
scalars and their ordinary escaped JSON representation remain supported.
No coercion through __str__/__format__, character replacement, ASCII-only
restriction or NFC/NFD normalization is performed. A/B1 whitespace/content
rules remain in force. Both retained initial-state frames and all parameter
IDs/source IDs/units/rationale/derivation are checked after A/B1 reconstruction;
invalid velocity-frame text cannot hide behind subclass equality. The same
exact-text policy covers manifest/numerical/world identity strings before B2
namespace checks and binding comparisons, including the orbit-free path.
Shared legacy ID/provenance validators and all scientific equations are unchanged.

New regressions cover direct construction, reading, forged-object encoding,
binding and rejection before mutable restore/execution, with isolated high/low
surrogates, actual surrogate pairs and behavior-overriding subclasses. Positive
ASCII/Cyrillic/non-BMP and distinct NFC/NFD text round-trip without value or ID
loss. All 55 sampled valid pre-repair canonical payload bytes/IDs are unchanged,
as is the literal fixture below. Payload keys, float.hex values, ordering, JSON
settings, namespace, representation/binding version 1 and checkpoint schema 5
remain unchanged. The prior 3591-test full run is historical pre-correction
evidence; current corrected validation is recorded in MODEL_STATUS. This repairs
identity/portability, not orbit accuracy, authentication or full-experiment
fingerprint coverage.

Binding payload version 1 contains exactly:

- `binding_version`: 1;
- `coast_orbit`: the complete versioned definition above;
- `manifest`: schema version and all seven input/controller association IDs,
  excluding manifest_id itself;
- `numerical`: timestep_seconds, geometry_sample_seconds and
  checkpoint_interval_seconds;
- `world`: horizon_seconds and ordered event_ids.

Canonical JSON uses sorted object keys, compact separators `(',', ':')`,
`ensure_ascii=True`, `allow_nan=False`, then UTF-8 encoding without BOM.
SHA-256 of those bytes yields the value
`v56b2-coast-sha256-<64 lowercase hexadecimal characters>` in ModelManifestId.
The entire value stem `v56b2-coast` is reserved, including malformed/future
suffixes; it cannot identify orbit-free inputs. The resulting 83-character
value fits the existing 128-character StableId limit. No previous fixture used
the reserved stem. Future semantic changes require an intentional model or
representation/binding version change, not a digest incorporating Git HEAD.

Public explicit imports from `context.py` provide
`with_coast_orbit(inputs: SimulationInputs, coast_orbit: CoastOrbitInputs)
-> SimulationInputs` and
`evaluate_context_coast(context: SimulationContext) -> CartesianState`.
The historical context wildcard export list is preserved. The factory validates
the original inputs, replaces only the manifest label and coast attachment,
and preserves other associations/references. It excludes the previous label
from hashing, so equal-content rebinding does not form a hash chain. Direct
construction and dataclasses.replace must also verify current content against
the derived ID; validation never overwrites a stale caller ID. Bound content
with a legacy/arbitrary ID and missing content with a reserved ID both fail.

SimulationContext validation checks the full current input binding. Capture
uses that boundary; restore checks the supplied definitions before allocating
mutable runtime domains and then applies the existing captured-ID comparisons.
Engine complete-context validation explicitly carries the keyword attachment.
The existing checkpoint-isolated transaction kernel, precommit result and single
commit are unchanged; immutable input reference identity is preserved. Schema
5 and every checkpoint field/portable key remain unchanged because the existing
model_manifest_id carries the binding. Restore requires matching external coast
definitions; it never recovers an orbit from an ID alone. Legacy orbit-free
schema-5 checkpoints retain their existing behavior and representation.

The pure query reuses complete runtime-context validation and constructs
GeometryInstant from the bound reference TT epoch and actual simulation seconds,
then calls B1 once. Time zero maps to that epoch even when the initial orbit
sample has a nonzero elapsed time. GeometryInstant rejects unrepresentable time;
B1 span/conditioning/convergence errors remain visible. Fingerprinting a horizon
does not certify successful propagation over that horizon. No hash operation
or normal engine step performs hidden propagation. No current r/v, period,
elements, last-query time or cached orbital evidence is authoritative/persisted.
After downlink advances the clock, a later coast query does not imply that
concurrent battery, thermal or degradation evolution was modeled.

The independent literal payload fixture uses a synthetic radius-2 m circular
state with velocity 1 m/s, mu 2 m^3/s^2, sphere radius 1 m, reference TT
2451545 + 0.125, phase 0.25 rad and rotation rate -0.125 rad/s. With the explicit
fixture provenance/associations, solver (0.125 s, 8), grid (1,1,1) s and world
horizon 2 s, its fixed digest is
`5fd4b089db8e0a846b526cfedca4a16f4057d38f296b759c9d0ed90b53352125`.
The expected payload is written independently of the production encoder.
Substitution tests alter one valid semantic input at a time, including both
sensitivity endpoints and coherent scenario identity, and reject stale/stripped
bindings at construction/capture/restore/execution. Real portable restart and
all four existing engine paths compare equal direct/restarted coast evidence;
downlink retains exact delivery bookkeeping and unmodeled physical fields.
The sole legacy structural test adjustment permits only the new keyword field's
None default; all original required-field assertions remain live.

This binding is reproducibility/mismatch protection, not a digital signature.
It is not full content-addressing of hardware, flight rules, external sources or
the entire experiment; unchanged protections outside the listed payload remain
ID-only. B2 adds no contacts/opportunities, J2/drag/third bodies, maneuvers,
controller policy, operational accuracy or final model-adequacy approval.
Broader V5.6 integration and physical adequacy remain unfinished.

## D306 — Instantaneous ground-point viewing geometry (2026-09-15)

C1 adds only ops_sim/v5/orbit_geometry.py and its two test modules. It evaluates
one supplied MODEL_INERTIAL CartesianState and one explicit Earth-fixed point.
It propagates no orbit, advances no runtime state and creates no contacts,
observation opportunities, schedules, service/authorization decisions or legacy
ObservationPointing/CommonFrameBoresightDirection. Rays may be obstructed; no
occultation, ellipsoid intersection, terrain, mask, refraction, light-time,
aberration, footprint, GSD, camera roll or complete attitude is inferred.

GroundPointDefinition is frozen/slotted/default-free, with point_id (exact
GroundStationId or GroundTargetId), complete ReferenceEllipsoid, and three
ScalarParameters: latitude_rad, longitude_rad, ellipsoidal_height_m. Their
parameter IDs are orbit.ground-point.geodetic-latitude (rad),
orbit.ground-point.east-longitude (rad), and
orbit.ground-point.ellipsoidal-height (m). Each coordinate has its own explicit
provenance. geodetic_location derives A's GeodeticLocation; no parallel numeric
coordinate truth is persisted. A's original-Real checks precede normalized
storage: latitude [-pi/2,pi/2], east longitude [-pi,pi), and height
h > -a*(1-f)^2. No wrapping/default height/datum is supplied. Supported negative
height is mathematical normal-offset geometry, not terrain/exterior evidence.
Legacy GroundTarget has degrees but no datum/height/provenance; a later explicit
adapter must resolve that boundary. Typed target identity alone supplies none
of the missing geographic content.

A owns complete numeric/provenance reconstruction. B2's exact built-in str and
Unicode scalar-value policy is reused for point IDs and all known textual
metadata. Both supplied state frames are rebuilt and text-validated before
definition equality; complete point/frame ellipsoids must agree. Valid Unicode
is preserved, including non-BMP and distinct NFC/NFD. No shared validator or
A/B1/B2 implementation changes. C1 does not impose B1's elliptic-orbit admission
on a caller-supplied valid A Cartesian state.

Public evaluator:
evaluate_ground_point_geometry(point: GroundPointDefinition,
spacecraft_state: CartesianState) -> GroundPointGeometry.
The frozen/slotted result constructor accepts only those two full inputs and
computes all other fields (init=False), preventing independent contradictory
angle/direction arguments. Dataclass replacement recomputes derived evidence.

Complete computed fields: ground_state (CartesianState), ground_to_spacecraft
and spacecraft_to_ground (unit CartesianDirection), orbital_x/orbital_y/orbital_z
(unit CartesianDirection), slant_range_m, slant_range_rate_m_per_s, elevation_rad,
ground_azimuth_rad, incidence_rad, off_nadir_rad, orbital_azimuth_rad, and each
azimuth's *_projection_norm and *_resolution (dimensionless). The read-only
ground_azimuth_status and orbital_azimuth_status distinguish zero_projection,
unresolved_projection and resolved. Every Cartesian output carries the exact
evaluation instant and complete compatible inertial frame; no timeless label
is used to identify the moving orbital basis.

The matching EARTH_FIXED frame shares the full rotation and ellipsoid. A's
geodetic_position and geodetic_normal supply normal-offset position and outward
up. Fixed velocity is explicitly zero. A's transform_state gives
r_gI=R*r_gF and v_gI=Omega cross r_gI=(-omega*y,omega*x,0).
No separate rotation-angle implementation is introduced. Relative geometry is
d=r_s-r_g, rho=|d|, u=d/rho, q=-u, and rho_dot=u dot (v_s-v_g), positive for
separation, in metres and metres/second. This is simultaneous Euclidean
geometry; range rate is not a Doppler/RF model.

With geodetic phi and east lambda, fixed east=(-sin(lambda),cos(lambda),0),
north=(-sin(phi)*cos(lambda),-sin(phi)*sin(lambda),cos(phi)), and up is A's
geodetic normal. Axes are rotated into the matching inertial frame. Ground
elevation=atan2(u dot up,hypot(u dot east,u dot north)); ground azimuth is
atan2(u dot east,u dot north), north toward east. At a pole the supplied
longitude selects the local meridian convention, not a unique physical north.

The instantaneous adopted orbital convention has rhat=unit(r_s),
z=-rhat, x=unit(v_s-(v_s dot rhat)*rhat), y=z cross x.
The stable construction normalizes r and v before crossing, sets
hhat=unit(rhat cross vhat), x=unit(hhat cross rhat), y=-hhat, z=-rhat.
The identity (r cross v) cross r=|r|^2*v-(r dot v)*r proves equivalence
and fixes the signs: x follows transverse inertial motion, y completes the
right-handed basis and orbital azimuth increases x toward y. Earth-fixed
ground-track velocity is not substituted. Off-nadir is
atan2(hypot(q dot x,q dot y),q dot z). Orbital azimuth is atan2(q dot y,q dot x).
Incidence is atan2(|up cross u|,up dot u), independently distinct from off-nadir.
Ranges are elevation [-pi/2,pi/2], incidence/off-nadir [0,pi], azimuths [0,2*pi).
For the same geometric normal, incidence+elevation=pi/2 up to arithmetic error.
No legacy imaging envelope clips these angles.

Numerical domain: A's full frame/geodetic/instant and accumulated-phase limits
still apply. Finite intermediates and finite range/range rate are required.
Max-component scaling avoids avoidable squared-norm overflow/underflow; zero
spacecraft radius/velocity, zero separation and radial orbital motion reject.
Separation must exceed 64*ulp(max absolute r_s/r_g component), including
subnormal ulps. This conservative represented-coordinate resolution policy
is not a total A geodesy/B1 uncertainty estimate. Normalization/product
underflow and rounded-to-zero nonzero dot/cross cancellation explicitly reject.
For zero sums only, exact rational products test whether the represented
operands truly cancel. This guards the zero-projection classification; it
does not claim exact alignment of the underlying unrounded geographic model.

For u64=2^-53, k=|unit(r) cross unit(v)| must exceed 64*u64; smaller nonzero k
is an unresolved basis. With P the unit-ray planar projection norm, azimuth
is None when P<=b, with b=64*u64 for ENU and b=64*u64*(1+1/k) for orbital
axes. P==0 gives zero_projection; 0<P<=b gives unresolved_projection. No ray
or polar angle is changed. These are explicit working numerical policies:
scaled normalizations contribute O(3u64), cross/axis reconstruction contributes
O(40u64/k); combining two projections fits a 64u64/k reserve plus the ordinary
64u64 vector/dot reserve. They are not certified interval/libm error bounds.
Near-radial basis and near-zero azimuth projections remain ill-conditioned;
admission alone promises no small angle error. A's phase and geographic
arithmetic are separately budgeted in tests; a caller's B1 state error remains
a separate external contribution, not certified by these C1 reference comparisons.

Negative atan2 azimuths add binary64 tau. If addition rounds to tau, the
coordinate uses nextafter(tau,0), an explicit inward correction <=one ulp;
signed zero becomes positive zero. The underlying direction is unchanged.
No acos/asin clipping, Unicode/coordinate quantization or fallback axes.

Independent references include hand-solvable sphere cases, a 90/110-digit
Decimal oracle from exact binary inputs, and range-derivative refinement.
The oracle uses Q*n/sqrt(n.T*Q*n)+h*n with Q=diag(a^2,a^2,b^2), independent
complex-plane rotation and direct transverse velocity projection. Small-angle
budgets derive from vector perturbations and atan2 gradients; azimuth budgets
explicitly divide by planar-projection conditioning. Central differences use
|rho'''|<=J+6*V*A/rho_min+6*V^3/rho_min^2 and h^2*bound/6 plus roundoff.
A's phase allowance is 8*u64*(abs(theta0)+abs(omega*t)+1) radians, not a B1
root residual or a physical Earth-orientation error model. No discarded B1
v_max*eta / a_max*eta endpoint argument is reused.

S008 records verified ESA ENU and NAIF geodetic/rotation source locations.
Our atan2 choices, local-axis signs, range-rate derivative, incidence/off-nadir,
resolution policies and independent reference derivations are explicitly
adopted mathematics; no source is claimed to select our local orbital axes.
No source example supplies operational station coordinates or coefficients.

Point definitions are explicit evaluator arguments, retained in result equality,
but absent from SimulationInputs, CommonWorld, B2's version-1 binding and schema-5
checkpoints. Same IDs with changed coordinates OR provenance yield different
point evidence; B2 manifest identity does not certify those geographic inputs.
Portable restart reproduces geometry only with the same external point content.
No catalog, registry, deduplication or propagation cache is introduced. C2
temporal visibility/window work and later explicit catalog/content-binding and
service/observation adapters remain separate. All frozen releases are preserved.

## D307 — Instantaneous ellipsoid occultation and elevation gate (2026-09-15)

C2a adds only ops_sim/v5/orbit_visibility.py and two C2a test modules.
It evaluates a supplied geographic point/state/policy at one instant.
C2b temporal search, interval evidence and unresolved event boundaries remain
subsequent work. C2a propagates no orbit, samples/advances no time, creates no
contact/opportunity/window and changes no engine path or physical/checkpoint
state. It is simultaneous straight-line geometry with no terrain, atmosphere,
refraction, light-time, aberration, antenna/RF/electrical/availability model,
camera field of view, imaging envelope or full attitude. Geometric visibility
supplies no serviceability, authorization, image acquisition or data receipt.

GroundVisibilityPolicy is frozen/slotted/default-free and contains exactly
minimum_elevation_rad: ScalarParameter. Its identity is
orbit.visibility.minimum-elevation and units are rad. Both the original Real
and normalized binary64 value must lie in [-pi/2,pi/2]. There is no default
mask. Negative masks are explicit geometric policies and do not disable body
occultation. Synthetic tests use EXPLICIT MODEL ASSUMPTION provenance;
operational thresholds would require separately supplied evidence.

The evaluator signature is evaluate_ground_visibility(point:
GroundPointDefinition, spacecraft_state: CartesianState, policy:
GroundVisibilityPolicy) -> GroundVisibilityResult. The frozen/slotted result
accepts only these three inputs and computes all other fields (init=False).
Construction and dataclass replacement recompute C1 geometry from reconstructed
inputs; caller-supplied angles/ground positions are not accepted as authority.
C1 remains unchanged and validates both state frames, including scalar-Unicode
text, before definition equality. Policy validation reuses A's complete
parameter/provenance reconstruction and B2's exact built-in str/Unicode scalar
text checks. Valid Unicode is retained without normalization. C1 numeric-domain
exceptions remain explicit and uncaught; undefined azimuth is not invisibility.

Result fields retain point, spacecraft_state, policy and full geometry
(GroundPointGeometry, including exact GeometryInstant and complete frame
definitions). Component fields are line_of_sight_status, line_of_sight_reason,
elevation_status, elevation_margin_rad and elevation_allowance_rad. Final
status is GroundVisibilityStatus: VISIBLE, NOT_VISIBLE, BOUNDARY, UNRESOLVED.
LineOfSightStatus is CLEAR, BLOCKED, BOUNDARY, UNRESOLVED; ElevationStatus is
ABOVE, BELOW, BOUNDARY, UNRESOLVED. LineOfSightReason distinguishes ground
inside, spacecraft inside, surface outward/entry/tangent, segment clear,
interior penetration/tangency, spacecraft surface and numerical uncertainty.

Combination is a conjunction: either resolved failure establishes NOT_VISIBLE;
two strict passes establish VISIBLE; otherwise any unresolved component gives
UNRESOLVED; remaining exact boundary evidence gives BOUNDARY. Both components
are retained even when one determines the conjunction. No generic visible
boolean or positive-duration interpretation of BOUNDARY is provided.

Occultation diagnostics: ground_location and spacecraft_location are
BodyLocation INSIDE/SURFACE/OUTSIDE. The former is authoritative from h; the
latter is exact relative to represented spacecraft coordinates and a/f.
ground_level, spacecraft_level, quadratic_a/b, minimum_parameter,
minimum_location (GROUND_ENDPOINT/SPACECRAFT_ENDPOINT/INTERIOR), minimum_level,
ground_position_allowance_scaled, exact_axis_definition,
occultation_predicate, occultation_signed_value and occultation_allowance
record the selected case. Numeric occultation diagnostics are exact Fractions
and dimensionless except the ground_height_m predicate (metres); elevation
margin/allowance are floats in radians. The minimum and ground_level describe
the nominal predicate segment; at general h=0 they can contain geographic
rounding even though ground_location correctly remains SURFACE.

Shape authority remains a and f. b=a*(1-f) is formed in exact rational
arithmetic on their admitted binary values, never adopted as an independently
rounded input. The same-centre oblate body is x²/a²+y²/a²+z²/b²<=1.
For the adopted common z axis, Rz preserves x²+y² and leaves z unchanged,
so Rz.T*Q*Rz=Q, Q=diag(a^-2,a^-2,b^-2). The predicate can use C1's inertial
coordinates directly. This derivation does not apply to a triaxial or
arbitrarily oriented body. C1/A remain the only frame/geodesy implementations.

Dimensionless scaled vectors are P=(x/a,y/a,z/[a*(1-f)]). The segment is
P(s)=P0+s*D, D=P1-P0, 0<=s<=1, with
F(s)=A*s²+2*B*s+C, A=D.D>0, B=P0.D, C=P0.P0-1.
Exact Fraction sums/products avoid overflow, cancellation and false rounded
zeros in these predicates. The minimum is at s=0 if B>=0, s=1 if B<=-A,
otherwise s=-B/A. It is evaluated at the closest point; no production roots
or discriminant-only infinite-line test are used. A finite clear segment may
have an intersecting ray extension. No endpoint fraction is discarded.

Endpoint semantics:
- Admitted h<0 is inside the reference body and yields BLOCKED with explicit
  GROUND_INSIDE_REFERENCE_BODY. Even a tiny real negative height is retained.
- For h=0, the geographic definition imposes true C=0. The true departure
  B=P0.P1-1 follows from P0.P0=1, and F(s)=s*(A*s+2*B).
  A resolved B>0 is CLEAR despite closed-segment endpoint contact; B<0
  penetrates immediately; proven B=0 is tangent BOUNDARY. Rounded negative
  ground_level is never substituted for the exact surface identity.
- An exact spacecraft F1<0 establishes BLOCKED independently. For F1=0,
  D1=P1.(P1-P0) is half the derivative at s=1. Resolved D1>0 proves interior
  penetration immediately before arrival, overriding boundary contact.
  D1<0 is an exterior approach with endpoint-only BOUNDARY; proven zero is
  endpoint tangency. If its sign is uncertain, the result is UNRESOLVED.
- For h>0 and exterior spacecraft, the full restricted minimum governs:
  resolved negative is penetration, positive is clear, proven zero is
  interior grazing BOUNDARY, and uncertain near-zero is UNRESOLVED.

Exact geographic-axis case: latitude=longitude=initial phase=0 and either
rate=0 or elapsed time=0 imply exact P0=((a+h)/a,0,0).
This algebraic predicate uses the rational sum a+h, which may differ from
C1's rounded returned coordinate. It does not move or alter C1's geometry.
Its occultation ground allowance is zero; the exact discrepancy of C1's
returned ground position is separately included in the elevation allowance.
Other represented zeros alone are not exact geographic tangency evidence.
A rounded reduced phase of zero is insufficient for this special case.

C2a adds an explicit numerical envelope: 2^-900<=a<=2^900 m, 0<=f<=1/2,
max(abs(h),abs(spacecraft Cartesian components))/a<=2^40. A/C1 validation
and failures apply first. These are numerical restrictions, not physical
station/orbit limits. They keep scaled calculations bounded and restrict the
geodetic denominator to >=1/2; N/a<=2. Cases outside raise ValueError.

The conditional working arithmetic policy assumes absolute sin/cos error
<=2u, u=2^-53, and ordinary rounded binary64 arithmetic. It is not a certified
interval/libm bound. For f<=1/2, ratio error<=u gives relative q error<=5u;
hypot input/rounding error<=6u gives relative denominator error<=12u;
the N quotient reserve is <=14u*N<=28u*a. Carrying normal-offset/products
and longitude trig gives a loose L2 position reserve below about
128u*a+24u*abs(h); rotation trig/products and second-order terms fit within
the adopted 256u*(a+abs(h)) reserve. No coefficient is spacecraft-specific.

In units of a, set e=256u*(1+abs(h)/a), phase allowance
p=8u*(abs(theta0)+abs(omega*t)+1), as in A. General ground-position allowance
is E=e+(L1(g/a)+e)*p; ellipsoid-scaled norm allowance is delta=E/(1-f).
All these budget formulas use exact Fractions after input admission.
The phase term describes A's uniform-rotation arithmetic, not Earth orientation.
Surface-departure and endpoint-derivative allowances are delta*L1(P1).
For elevated segments, distance from the origin to a segment is 1-Lipschitz
under endpoint displacement: each segment point moves by at most delta, so
the two minima of the norm differ by at most delta even if the minimizer
moves or switches endpoint. Therefore a valid squared-level allowance is
2*L1(nominal closest point)*delta+delta². This follows from
abs(r_true²-r_nom²)<=2*r_nom*delta+delta² and L1>=L2.
Only strict separation beyond the allowance resolves a sign; an exact zero
with zero approximation allowance supplies boundary evidence.

Elevation reuses the actual C1 atan2 result and retains margin=elevation-mask.
With rho=C1 range/a and eg the C1 ground-position error/a, use
d_error=eg+8u*(rho+L1(rs/a)+L1(rg/a)); the reserve includes subtraction/hypot
and near-coincident coordinate conditioning. For rho>d_error the normalized
ray allowance is 2*d_error/(rho-d_error)+32u. Set epsilon=ray allowance+
phase allowance+64u+8u for ENU construction/normalization/projections.
For epsilon<1/8, the angular allowance is 4*epsilon+8u*(1+abs(mask)),
rounded outward. Three projections have perturbation <=sqrt(3)*epsilon;
hypot is 1-Lipschitz and the atan2 gradient has norm 1/radius, yielding
sqrt(3)*epsilon/(1-sqrt(3)*epsilon)<4*epsilon. The last reserve covers
atan2/margin subtraction. Otherwise use pi radians, leaving the margin
unresolved. There is no unexplained uniform epsilon across coordinate scales.
Only exact-axis vertical=0 with mask=0 is recognized as an exact policy
equality. Copying a rounded angle into the mask is not a proof of equality,
including binary +/-pi/2 convention endpoints. Near-equality is UNRESOLVED.

These allowances cover the declared arithmetic model only. Exact predicates
on represented spacecraft inputs do not remove an external caller's B1
position error, physical-model uncertainty, geodetic/rotation approximation
or station evidence uncertainty. No B1 root residual is a visibility bound;
no obsolete v_max*eta / a_max*eta endpoint argument is reused. No body
inflation, coordinate clipping, discriminant clipping or adaptive tolerance
loosening is introduced. No physical window/event-time certification follows.

Independent tests use hand-solved spheres/oblates and exact rational helper
cases, including near-endpoint penetration. A separate Decimal90/Decimal120
oracle builds support-surface geography from the same a/f inputs, uses
complex rotation, cross-product line distance and root-interval overlap.
Difficult reference quantities agree within 1e-60 in dimensionless/radian
units. Tests separately exercise nonaxis f=1/2, a=2^+/-900 m and large
normalized height, as well as both hemispheres, pole convention, off-axis
WGS84 h=0, genuine negative heights, finite-ray distinctions and grazing.
A deterministic 120-query grid has 98 resolved final results (34 VISIBLE,
64 NOT_VISIBLE), zero exact BOUNDARY and 22 UNRESOLVED. Exact hand cases
separately establish surface/interior/spacecraft boundary classifications.
No random cases or unexpected exceptions are discarded.

The result retains full geographic and policy content, but both remain
external to SimulationInputs/CommonWorld, B2 version-1 manifest binding and
schema-5 checkpoints. Same IDs with changed coordinates/provenance or changed
policy content yield different evidence without changing the B2 manifest.
A real JSON checkpoint round trip plus an independent coast-codec rebuild
reproduces same-runtime visibility only when the same external point AND
policy are supplied. No cache, catalog, codec expansion or persistent state.
All A/B1/B2/C1 production/tests, delivery accounting, frozen release records,
examples and submitted artifacts remain unchanged.

## D308 — V5.6C2b derives bounded adaptive temporal visibility windows

Date: 2026-09-15. Status: author-approved bounded C2b implementation contract;
candidate implementation remains subject to independent actual-source review.

`orbit_visibility_windows.py` composes exact validated SimulationInputs with
present B2-bound coast inputs, explicit B1 state evaluation and explicit C2a
instantaneous visibility. It uses no mutable context/current simulation time.
The six required search inputs are inputs, point, policy, start_seconds,
end_seconds and GroundVisibilitySearchConfig(boundary_tolerance_seconds,
max_evaluations). Frozen/slotted/default-free evidence retains these inputs.
Cells, visible_windows, evaluation_count and complete_to_tolerance are derived,
not injectable constructor fields; dataclasses.replace recomputes the search.
Point/policy receive C1/C2a complete text/provenance validation. Coast arithmetic
uses a locally reconstructed definition, including normalized accepted Real
values, while the result retains the supplied SimulationInputs reference.

Run-relative times are TT seconds under A's explicit epoch convention.
Confinement must satisfy 0<=start<end<=common-world horizon both before and after
binary64 normalization. Both endpoints must satisfy A time/rotation and B1
span/revolution admission; unsupported arithmetic raises explicitly. The point
ellipsoid must match the complete trajectory frame ellipsoid. B2 already binds
geometry_sample_seconds, which is solely an initial partition scale. Integer
multiples anchored to run time zero plus confinement endpoints produce seeds;
there is no floating t+=step accumulation or sample-only certification.

The exact adopted ellipse has central mu, radius r, velocity v and angular
momentum H=r cross v. For exact binary authoritative inputs use rational dot
products, an outward radius R_hi>=|r|, alpha_lo=2/R_hi-v.v/mu>0, a_hi=1/alpha_lo,
e_hi=sqrt_up(max(0,1-|H|²/(mu*a_hi)))<1, rp_lo=|H|²/[mu*(1+e_hi)],
ra_hi=a_hi*(1+e_hi), and vmax_hi=sqrt_up(mu*(1+e_hi)/rp_lo).
Square roots are scaled before binary64 evaluation and verified outward by
exact rational squaring. These bounds do not propagate via classical elements
and do not replace B1's existing pericentre admission. Derived unsupported or
nonfinite envelopes are rejected. With exact b=a_earth*(1-f), take Rs=ra_hi/b,
Ls=vmax_hi/b, Rg=1+abs(height)/b, Lg=abs(omega)*Rg,
Vrel=vmax_hi+abs(omega)*a_earth*Rg. Normalized radii are dimensionless, Ls/Lg
are 1/s, and Vrel is m/s. C2a's f<=1/2, radius and normalized coordinate
conditioning apply globally; this conservative global admission can reject a
trajectory whose particular queried coordinates alone would have been accepted.

The evaluated midpoint may round asymmetrically. Each cell therefore uses
w=max(midpoint-start,end-midpoint) with exact rational arithmetic, which equals
the half-width only for an exactly central representative. The global exact
model rates do not bound numerical B1 endpoint errors. C2b supplements them
with B1's corrected working position reserve, in metres:

    k=1/(1-e_hi), T_hi=sqrt_up(a_hi³/mu), u=2^-53,
    P=the B1 rounded period, span=max(abs(start-t_initial),abs(end-t_initial)),
    Epos=(vmax_hi+V0_hi)*eta
         +vmax_hi*(64u*k*span+2u*P)
         +256u*k*(a_hi+vmax_hi*T_hi).

The initial-speed term follows from the residual-retaining f/g reconstruction
r_hat=r_star(t+delta)-v0*delta. The disproved vmax*eta-only endpoint bound is
not used. eta is the accepted residual ceiling (seconds), not event-time error.
The 64u phase and 256u reconstruction policies are the reviewed B1 working
binary64/libm budgets; 2u*P encloses conversion of the exact reduced remainder.
Require V0_hi*eta/rp_lo<=2^-10 and the reconstruction reserve less than
(rp_lo-V0_hi*eta)/2. This is additional C2b certification-domain admission,
not a change to B1 acceptance. It assumes the existing working arithmetic
policy; it is not formal interval arithmetic or a physical-model error bound.

LOS uses strict margins, not a positive-duration BOUNDARY classification:

- Negative authoritative height blocks the whole cell without transition
  refinement (its representative still evaluates and retains C2a evidence).
- Endpoint S=|P1|²-1 uses ds=Ls*w+Epos/b and Eendpoint=2*Rs*ds+ds². A strict
  negative margin certifies failure; unresolved endpoint clearance prevents
  using the surface departure as though the endpoint were safely exterior.
- For height=0 and a whole-cell resolved exterior endpoint, Bsurf=P0.P1-1
  uses Esurface=(Lg*Rs+Rg*Ls)*w+Rg*Epos/b. Add C2a's surface instantaneous
  allowance delta*L1(P1); only a strict sign beyond the sum resolves LOS.
- For elevated points, distance to a finite segment is 1-Lipschitz under
  endpoint displacement. Take d=max(Lg*w+delta,Ls*w+Epos/b),
  Rseg=max(Rg,Rs) and Emin=2*Rseg*d+d². Add the C2a minimum allowance
  2*L1(nominal closest point)*delta+delta². Including the ground reserve delta
  in d as well is deliberately conservative; it covers mixed ground/B1 anchor
  errors without borrowing an endpoint derivative's allowance for a minimum.
  Only a strict signed minimum beyond the combined bound resolves LOS.

Elevation retains C1's range rho and C2a's margin m and angular allowance E0.
Its range denominator also needs a length reserve: D0=a_earth*c1_error+
8u*(rho+L1(r_spacecraft)+L1(r_ground)), in metres. The C2a setup supplies
c1_error even when the exact-axis predicate uses rational a+h but C1 returns
a rounded coordinate. Set dr=Vrel*w+Epos+D0. If dr>=rho, retain angular
uncertainty pi-up. Otherwise q=dr/(rho-dr); q>=1 likewise gives pi-up.
For q<1 use an outward q, theta_ray=2*asin(q_up)+4u and
theta_up=min(pi_up,abs(omega)*w), with Etime=min(pi_up,theta_ray+theta_up).
The 4u reserve covers the stated <=2u absolute asin libm policy after doubling;
pi_up is the next binary64 above pi. This caps an enclosure, not a state.
Strict m>E0+Etime passes and m<-(E0+Etime) fails; otherwise refine. LOS failure
OR elevation failure resolves NOT_VISIBLE; both passes resolve VISIBLE.
The public temporal allowance fields include these numerical anchor reserves
in addition to exact model motion, with LOS dimensionless and elevation radians.

Refinement is deterministic breadth first: all initial representatives precede
child representatives. A strictly interior converted midpoint is evaluated
once through B1 then C2a and cached only within this search. An unresolved cell
at or below the requested width remains BOUNDARY_TOLERANCE. A midpoint that
cannot lie strictly inside a wider cell gives TIME_RESOLUTION, without snapping.
Budget exhaustion retains EVALUATION_LIMIT uncertainty rather than raising for
unresolved events. Unexpected B1/C2a failures are not caught or converted to
NOT_VISIBLE. The budget counts expensive successful B1/C2a pairs.

Implementation refinement: after budget exhaustion, a contiguous untouched
initial-grid tail is represented as one unevaluated unresolved union, rather
than allocating up to 2^40 individual seed records. Previously evaluated cells
and pending child boundaries are preserved. The merged tail's own width
determines BOUNDARY_TOLERANCE versus EVALUATION_LIMIT; this can pessimistically
report incomplete width coverage even if each unvisited seed was already
narrow. No time or potential event is omitted, and no certification crosses
the union. Final cells exactly cover [start,end), ordered without overlap.
complete_to_tolerance means no evaluation-limit/time-resolution cell wider than
the target; it does not mean all cells resolve, or that each unresolved cell
contains just one transition. No monotonicity or endpoint-sign assumption.

Only directly adjacent resolved VISIBLE cells merge into a visible window.
Unresolved or NOT_VISIBLE cells are never bridged. Boundaries remain exact
cell edges, not AOS/LOS estimates; short passes and gaps can remain unresolved.
Boundary tolerance controls unresolved time width, not function error or
physical event accuracy. Low elevated endpoints can need substantially finer
width than surface points because the global segment bound is intentionally
loose. Independent hand cases cover hidden passes/gaps and tangent singletons;
90/120-digit independent elliptic-orbit/support-geodesy references probe both
ends, midpoint and independent interior fractions of every returned cell and
locate difficult event brackets inside retained uncertainty.

S008's already registered NAIF GF source is limitation evidence: a state-search
step can miss short events and gaps; root/convergence and input errors are
distinct. C2b does not copy GF, import CNVTOL or claim SPICE equivalence. It
adds no external physical parameter. No atmospheric refraction, terrain,
weather, RF/availability/electrical feasibility or successful receipt follows.
Point and policy remain explicit external inputs outside the B2 version-1
codec/manifest. Schema 5 persists no cells/windows/cursors/caches; matching
restart inputs and identical external point/policy/config/confinement recompute
equal same-runtime evidence. No engine-grid projection, ServiceableGroundContact,
ObservationOpportunity, scheduling, J2, maneuvers or new dynamics are supplied.
All existing production/tests, release history, examples and SIDe are preserved.

## D309 — V5.6C2c projects certified visibility onto complete engine steps

Date: 2026-09-15. Status: author-approved bounded C2c implementation contract;
candidate implementation remains subject to independent actual-source review.

`orbit_visibility_grid.py` composes the original C2b search inputs exactly once
through find_ground_visibility_windows. Its public seven-input constructor and
evaluator accept inputs, point, policy, search_start_seconds, search_end_seconds,
search_config and first_step_start_seconds. They do not accept a precomputed
search result as visibility authority. Exact SimulationInputs/B2 binding and
origin admission precede the search; C2b owns point/policy/config and original/
normalized confinement validation. Even an origin after search end still calls
C2b once. The result retains C2b's complete search result and normalized input
evidence. It performs no independent propagation or visibility predicate.

The active NumericalConfig.timestep_seconds is the sole step duration dt.
The explicit first future boundary g is an exact built-in integer satisfying
0<=g<=common-world horizon. It need not be divisible by dt or fall inside the
geometry confinement; no candidates exist before g. A huge valid engine origin
after a short geometry search gives an empty projection without converting g
to GeometryInstant or float. B2 already binds timestep and geometry sampling;
neither numerical configuration nor physical model ownership changes.

D040 defines the half-open main-engine interval [s,e). A complete step is
contained in a certified window [a,b) exactly when s>=a and e<=b, allowing
equality at either edge. For s=g+k*dt and k>=0, use exact Fractions of C2b's
admitted binary window boundaries and integer arithmetic:

    lower=max(a,g)
    k_first=max(0,ceil((lower-g)/dt))
    k_last=floor((b-g-dt)/dt)

The first inequality yields the inward lower integer index; the second yields
the inward upper index. ceil(x)=-floor(-x) implements the former exactly.
If k_last<k_first, the window contributes no full step. Otherwise first is
g+k_first*dt and count=k_last-k_first+1. There is no float boundary truncation,
tolerance, time snapping, outward rounding or AOS/LOS root estimate.

EngineGridVisibilityBlock(first_start_time_seconds,timestep_seconds,step_count,
source_window) is frozen/slotted/default-free. All three numeric fields are
exact built-in ints, excluding bool/subclasses; first>=0, dt>0, count>0. The
exact GroundVisibilityWindow is reconstructed through its existing validation
before Fraction arithmetic. Both first>=source.start and first+dt*count<=
source.end are checked. Positive dt/count then establish containment of every
represented [first+k*dt,first+(k+1)*dt). Derived last_end_time_seconds and
represented_duration_seconds use only exact integer arithmetic.

At most one block is created per source window; there is no per-step tuple,
list, cursor or cache. total_step_count is an exact integer sum. The projection
work is per certified window, independent of how many steps it represents;
C2b retains its own search workload/evaluation limits. Synthetic [0,2^40),
dt=1,g=0 yields one block with count=1099511627776, not that many objects.

Audit example: window [12,137), dt=60, g=0 admits only [60,120). The 48 seconds
before 60 and 17 seconds after 120 are excluded from represented engine time.
Those 65 seconds are not a claim about lost RF capacity: C2c creates no
serviceable contact or communications model. With g=12, the same window admits
[12,72) and [72,132), represented by one block with count=2.

Only search_result.visible_windows can create blocks. Separate windows are
never joined across unresolved or NOT_VISIBLE time. Empty visibility yields
empty blocks. all_search_cells_resolved is derived from every actual final
cell status being different from UNRESOLVED, independently of C2b's
complete_to_tolerance. Already certified blocks remain valid amid uncertainty;
this flag makes no claim that all operational opportunities were found.
All result outputs are init=False and dataclasses.replace recomputes the
complete composition from its seven original inputs.

Independent tests enumerate only small fixtures using direct Fraction step
containment, without the production floor/ceil helper. Hand cases exercise
both exact and adjacent-binary edges, fractional boundaries and nonzero phases.
Huge cases use algebraic expectations. The real C2b hidden pass demonstrates
that geometric duration differs from represented engine duration: a 60-second
step fits nowhere; a three-second grid at g=0 admits [9,12), while g=1 admits
none. Changing phase changes only projection evidence and preserves the bound
manifest. Tests rebuild/rebind numerical inputs before changing timestep.

Point, visibility policy, search config, confinement, origin and all C2b/C2c
derived evidence remain EXTERNAL to the B2 version-1 manifest content. A real
schema-5 JSON checkpoint round trip with independently decoded CoastOrbitInputs
reproduces equal same-runtime projections when all external arguments match.
No search/window/block/count/cursor is persisted; no codec, digest or portable
checkpoint key changes. C2c imports/calls no engine, checkpoint, communications,
observation or observation-feasibility implementation and changes no engine
path. No IDs, ServiceableGroundContact, ObservationOpportunity, capacity,
serviceability, imaging/downlink authorization, scheduling, J2, maneuvers or new
physics are introduced. All prior production/tests and release/SIDe artifacts
remain unchanged. No new external physical source is required.

## D310 — V5.6C3a derives geometry-only ground-station contact candidates

Date: 2026-09-15. Status: author-approved bounded C3a implementation contract;
candidate implementation remains subject to independent actual-source review.

`orbit_ground_contacts.py` adds only a semantic adapter over C2c. Its input
station is the unchanged GroundPointDefinition and must carry an exact
GroundStationId. GroundTargetId, station-ID subclasses and forged invalid ID
content are rejected, including when a search/grid would produce no blocks.
The complete original point graph is revalidated by existing C1/C2a/C2b owners
through C2c. There is no second station-definition class or parallel set of
authoritative coordinates. A station ID supplies neither coordinates, elevation
mask nor serviceability.

GroundStationContactProjection and generate_geometric_ground_contacts accept
exactly inputs, station, policy, search_start_seconds, search_end_seconds,
search_config and first_step_start_seconds. The frozen/slotted/default-free
constructor calls project_ground_visibility_to_engine_grid exactly once with
these original semantic inputs. Exact station-domain admission precedes that
call; C2c owns complete input/B2/grid admission, search and visibility proof.
C2c failures propagate unchanged, never becoming an empty contact set. C3a
performs no independent propagation, instantaneous visibility, temporal search
or interval containment calculation.

The result retains the actual C2c visibility_projection and its normalized
inputs, station, policy, confinement, search config and grid origin. Its
visibility_projection, contact_blocks, total_step_count and
all_search_cells_resolved fields are init=False; dataclasses.replace recomputes
the complete composition. There is exactly one GeometricGroundContactBlock per
C2c EngineGridVisibilityBlock, in source order. No splitting, merging, clipping,
expansion or bridging across unresolved/NOT_VISIBLE time occurs. The total step
count and resolution flag are copied directly from C2c; C3a does not infer a
stronger completeness claim from complete_to_tolerance or search cells.

GeometricGroundContactBlock(station_id, source_visibility_block) is frozen,
slotted and default-free, with no independent timing fields. It revalidates
the exact GroundStationId using existing strict ID/text policy, then reconstructs
the exact EngineGridVisibilityBlock through its owner's constructor, including
the nested source window. Source value equality and integer/binary boundary
values are preserved; reconstruction does not promise Python object identity.
The read-only first_start_time_seconds, timestep_seconds, step_count,
last_end_time_seconds and represented_duration_seconds properties each delegate
to the source block. Standalone block construction revalidates evidence without
establishing a new visibility proof or geographic association independently.
The top-level projection supplies that complete geographic/search evidence.

C3a work/storage is per source block, not per represented step. A synthetic
source with 2^40 complete steps yields one candidate with exactly 1099511627776
steps. No per-step tuple/list/range, cache or cursor is materialized. Python
integer storage scales with bit length, rather than the number of steps.

GroundStationId identifies the supplied station, never a contact. C3a generates
no GroundContactId: no UUID, hash, timestamp string, counter or station-ID reuse
as contact identity. It imports/constructs no ServiceableGroundContact and reads
no nominal downlink rate or capacity. V5.5 ServiceableGroundContact means
externally supplied serviceable contact evidence. C3a's geometric candidate
means only complete engine steps conservatively certified geometrically visible
under the supplied trajectory, ellipsoid and visibility policy. It establishes
no RF link closure, antenna compatibility, operational availability, booking,
network ownership, weather, regulatory permission, uplink/downlink availability,
communications electrical/thermal feasibility, successful acquisition/delivery
or controller selection. S007's TO RESEARCH boundary remains authoritative.
An eventual C3b serviceability promotion requires a separate approved evidence
and contact-identity contract. V5.5 semantics and tests remain unchanged.

Complete station content remains part of top-level equality: the same station
ID with changed latitude, longitude, height or provenance is different evidence
even if source timings coincide. Distinct station IDs at identical coordinates
also remain different evidence. There is no station-ID-only deduplication.
Station/policy/search config/confinement/origin and all derived C3a evidence
remain external to B2 version-1 content. Schema-5 checkpoint JSON restart with
independently decoded CoastOrbitInputs recomputes equal same-runtime evidence
when those external arguments match. No C3a block/projection/contact state is
persisted, and no portable key, codec/version or fixed digest changes.

Tests use real C2c hidden-pass geometry, exact source-value comparisons, changed
grid phase, resolved invisible geometry, and explicitly synthetic trusted C2c
seams for unresolved gaps, adjacency, coincident timing and huge-count mapping.
The seams verify domain composition only, not independent physical truth.
AST/import and runtime guards exclude contact identity, serviceable contacts,
communications capacity, engine execution and persistence. Existing V5.5
consumers reject geometric candidates as the wrong domain. No new external
physical source or spacecraft coefficient is introduced. Observation-opportunity
generation, engine/controller integration, J2, maneuvers and wider physical
fidelity remain outside C3a; all prior production/tests and release/SIDe artifacts
remain unchanged.

## D311 — V5.6C3b binds external serviceability to generated geometry

Date: 2026-09-16. Status: author-approved bounded C3b implementation contract;
candidate implementation remains subject to independent actual-source review.

V5.5 ServiceableGroundContact remains an externally supplied serviceability
declaration. C3b does not derive serviceability from geometric visibility. The
caller supplies the existing exact contact type and its GroundContactId,
GroundStationId, start_time_seconds and end_time_seconds. The existing V5.5
constructor reconstructs/revalidates this evidence without changing any of
those fields. Its existing internal ID validation is not generation of a new
contact identity; C3b invokes no ID constructor, hash/UUID/counter identity rule,
or serviceability boolean. No existing V5.5 admission policy or class changes.

GroundContactGeometryBinding and bind_serviceable_ground_contact_to_geometry
accept eight required inputs: inputs, station, policy, search_start_seconds,
search_end_seconds, search_config, first_step_start_seconds and
serviceable_contact. The frozen/slotted/default-free result derives only
geometric_projection and supporting_block, both init=False. Derived fields
cannot be injected; dataclasses.replace reruns complete composition.
No precomputed geometric result is accepted as public visibility authority.

After external-contact validation, C3b calls generate_geometric_ground_contacts
exactly once with the original seven C3a inputs. C3a owns all generated geometry,
complete input/B2 admission and normalization. Failures propagate unchanged.
C3b calls no B1/C2a/C2b/C2c physical/search/projection functions and performs no
second visibility or engine-grid calculation. The actual C3a projection and
its normalized input evidence remain in the result.

The externally supplied contact's GroundStationId must match the C3a station's
point_id. Both owners validate exact GroundStationId types; cross-class string
matching is not sufficient. Typed equality is additionally checked against
base-string content to prevent V5.5-admitted text subclasses from spoofing a
different station. Benign matching text subclasses remain accepted; external
ID objects and text are neither coerced nor rewritten.

For one C3a block [b_first,b_last), the external half-open interval [c_start,c_end)
has complete geometric support exactly when c_start>=b_first and c_end<=b_last.
Both boundaries allow equality. All four values are owner-validated built-in
integer seconds. C3b uses integer comparisons only: no floats, Fractions,
tolerances, snapping, source-window reinterpretation or outward rounding.
One block already represents contiguous complete engine steps, so an integer
subinterval need not itself be a full step or aligned to dt. Within [60,180),
dt=60, contacts [60,180), [60,120), [70,110) and [120,180) are supported;
[59,120) and [60,181) are rejected without clipping. Geometric support does not
make [70,110) executable by step_downlink; the unchanged engine separately owns
its exact [current_time,current_time+timestep) requirement.

The scan requires exactly one containing source block. No match raises an
explicit geometry-support ValueError; multiple matches raise an explicit
geometry-domain inconsistency. It never chooses the first match arbitrarily,
unions separate blocks, merges adjacent blocks, bridges unresolved/NOT_VISIBLE
time or takes a wider pass hull. The exact supporting C3a block is retained,
without reconstruction or timing changes. Work is O(number of C3a blocks)
with constant extra match storage; represented steps are never enumerated.
Synthetic tests retain one 2^40-step block and test one-second violations above
2^60 seconds, where float conversion would erase the distinction. This is an
adapter-seam numerical check, not evidence of long-horizon orbital accuracy.

Full station geography/provenance and external contact evidence determine
binding equality. Distinct actual GroundContactId text remains distinct even
when legacy text subclasses overload equality; matching actual ID text remains
equal without altering the nested V5.5 contact. Other input/projection/support
fields retain their ordinary equality. The transient binding is explicitly
unhashable, avoiding a generated hash based on caller-overloaded ID hashes.
There is no station/time-only deduplication or parallel authoritative ID/time.

The result is a wrapper, not a replacement ServiceableGroundContact. Its nested
contact remains an exact ordinary V5.5 value accepted by existing pure consumers
under their unchanged requirements; the wrapper itself is rejected by their
exact-type checks. C3b imports only the communications contact type and performs
no nominal-rate reading, capacity calculation, transmission or engine execution.
Successful binding supplies neither RF closure nor antenna compatibility, G/T,
Eb/N0, coding/FEC, atmospheric/rain loss, availability/booking, network scheduling,
regulatory approval, communications power/heat, acquisition/transmission success,
acknowledgement or operational-throughput evidence. S007's TO RESEARCH questions
remain unresolved; no new external physical source or parameter is introduced.

Station/policy/search config/confinement/origin and external serviceability
remain outside B2 version-1 content. Schema-5 JSON checkpoint/restore with an
independently decoded CoastOrbitInputs v1 and matching external arguments
recomputes equal same-runtime bindings. Changing external evidence changes the
binding (or rejects inconsistent station/geometry composition), without changing
the bound manifest. No binding, supporting block or serviceability declaration
is added to checkpoint persistence. Schema 5, portable keys, codec/version and
fixed digest remain unchanged. Existing production/tests and release/SIDe
artifacts are preserved. Observation-opportunity generation, controller/engine
integration, J2, maneuvers and wider physical fidelity remain outside C3b.

## D312 — V5.6D1a realizes one orbit-derived observation opportunity on one certified engine step

Date: 2026-09-16. Status: author-approved bounded D1a implementation contract;
candidate implementation remains subject to independent actual-source review.

D1a bridges complete GroundTargetId geographic evidence, an external
ImagingRequest, C2c whole-step visibility certification and one instantaneous
B1/C1 snapshot to one existing V5.3 ObservationOpportunity. It constructs no
ObservationOpportunityCatalog or continuous opportunity window and generates
neither request nor opportunity identity.

OrbitDerivedObservationOpportunity and
derive_observation_opportunity_for_engine_step accept ten required inputs:
inputs, target, policy, search_start_seconds, search_end_seconds, search_config,
first_step_start_seconds, step_start_seconds, request and opportunity_id.
The result is frozen/slotted/default-free. visibility_projection,
supporting_visibility_block, spacecraft_state, geometry and opportunity are
derived init=False fields; normal injection is forbidden and dataclasses.replace
recomputes the composition. No precomputed projection/state/geometry/pointing/
opportunity is accepted as public authority.

The target must be exact GroundPointDefinition carrying exact GroundTargetId.
Station IDs, subclass IDs and invalid geography/provenance reject. C2c/C1 own
complete point revalidation and normalization. No implicit legacy
GroundTarget(latitude_deg,longitude_deg) adapter is introduced: it lacks the
explicit ellipsoid, ellipsoidal height and coordinate provenance required here.

The request must be exact ImagingRequest. Existing owner constructors
revalidate its request ID, target ID and positive finite priority, while the
original caller ID objects and priority evidence are retained. The caller also
supplies exact ObservationOpportunityId, whose text is revalidated through its
existing constructor and whose original object is retained. Validation is not
identity generation. No hashes, timestamps, counters, UUIDs or derived names
generate IDs. Both request and geographic target must carry exact GroundTargetId
and have identical actual base-string content. Legacy overloaded string
equality/inequality cannot invent a match or reject matching actual content.
Benign valid legacy text subclasses remain external request/ID evidence.

Wrapper equality compares actual request/target/opportunity ID content using
base str semantics, including IDs in the nested opportunity. It retains all
remaining request, geographic/provenance, projection, snapshot and opportunity
evidence. It is explicitly unhashable, avoiding caller-controlled text hashes.
Existing V5.3 value equality/admission remains unchanged. Changing only a request
or opportunity ID changes D1a evidence without changing geometry or B2 content.

D1a calls project_ground_visibility_to_engine_grid exactly once with the
original seven visibility inputs. C2c alone certifies that complete engine
steps lie within certified windows; it owns the numerical timestep through
inputs.numerical_config. Failures propagate unchanged. D1a directly calls no
C2b search or C2a visibility evaluator and does not reinterpret floating source
windows or repeat their containment calculation.

The selected start s must be exact built-in int (not bool/subclass), with
0 <= s < common-world horizon. For active dt and a C2c block with first/last
integer boundaries, support requires s>=first, s+dt<=last, and (s-first)%dt==0.
Exactly one block must support the entire step. No match raises an explicit
visibility/engine-step ValueError; multiple matches raise explicit domain
inconsistency. Equality at either support edge is valid. No start is snapped,
no steps are enumerated, and blocks are not split, unioned, merged or bridged
across uncertainty. Work is O(number of compact blocks), with constant extra
selection storage independent of represented step_count.

Only after unique support, one explicit evaluate_two_body_state query uses
the same normalized B2 CoastOrbitInputs and GeometryInstant(initial reference
TT epoch,s). The selected s is not added to the initial state's elapsed time.
One evaluate_ground_point_geometry call then receives the normalized C2c target
and that exact state. These additional B1/C1 calls obtain instantaneous pointing;
they do not independently recertify visibility. The returned state and geometry
are retained without persistence or a query cache. A/B1 numerical envelopes
still apply; compact support does not extend the supported propagation domain.

The V5.3 pointing view angle maps geometry.off_nadir_rad; azimuth maps
geometry.orbital_azimuth_rad. C1's authoritative local basis has z toward
geocentric nadir, x along transverse inertial motion, y=z cross x, and azimuth
increasing x-to-y. Incidence, elevation and ground north/east azimuth are not
substitutes. Binary64 radian-to-degree conversion happens at this bridge.
Resolved azimuth must be present and in [0,2*pi); unresolved_projection rejects.
zero_projection permits azimuth 0.0 only when C1 off_nadir_rad is exactly zero.
At this exact modeled nadir the azimuth is coordinate-degenerate: zero is a
representation convention, not measured azimuth evidence.

Off-nadir must lie in [0,pi/2); actual pi/2 or greater rejects under the current
V5.3 representable domain. No physical-angle clipping, arbitrary tolerance or
degree quantization is introduced. If an admitted strictly interior radian
value converts exactly to excluded 90 or 360 degrees, nextafter toward zero
chooses the adjacent interior degree value, at most one ulp inward. The source
domain is checked first. This is solely binary64 coordinate representation;
adjacent boundary tests and a labeled conversion seam exercise the rule.
Configured AgilePointingConfig maximum-view feasibility remains with V5.3.

The nested value is exact existing ObservationOpportunity with caller
opportunity_id, retained request.request_id, window [s,s+dt), imaging duration
dt and derived ObservationPointing. Its sole legal full-duration start is s.
Existing V5.3 pure view-feasibility consumes that nested value normally; the
wrapper remains outside its exact-type contract. A supported D1a result can
still fail a configured view limit. D1a performs no feasibility evaluation.
It constructs no ObservationManeuverCandidate, CommonFrameBoresightDirection or
ADCSBoresightFrameId. The common-frame bridge needs a later explicit contract.

Real hidden-pass tests verify selected [9,12), dt=3, while coarse/shifted grids
and non-grid/outside starts reject before a pointing snapshot. Independent
test-code local basis/direction calculations check ordinary and multiple
azimuth quadrants, wrap-neighborhood directions and a case discriminating
off-nadir/orbital azimuth from incidence/ground azimuth. Absolute-only numerical
bounds are scoped to synthetic conditioned cases, not operational accuracy.
Real C1 nadir/unresolved cases complement trusted seams for status, compact
lookup, gaps and ambiguity. A 2^40-step seam permits direct first/middle/final
lookup without claiming long-horizon orbital accuracy.

Target/policy/search config/confinement/origin/selected-step/request/opportunity
evidence remains external to B2 v1 content. Real schema-5 JSON checkpoint/
restore with independently decoded CoastOrbitInputs v1 and matching external
arguments recomputes equal same-runtime D1a evidence. No projection/state/
geometry/opportunity is persisted. Schema 5, portable keys, B2 codec/version
and fixed digest remain unchanged.

This bridge establishes whole-step geometric visibility and local target
direction at its start. It does not establish continuous tracking, configured
view feasibility, slew readiness, common-frame maneuver separation, acquisition
success, payload footprint/strip length, resource service, storage, downlink,
schedule selection, mission-request identity binding/value or controller
authorization. There is no engine execution, catalog, ADCS/full-attitude model,
new physical source or spacecraft coefficient. Existing production/tests,
examples/dependencies, frozen audits and SIDe artifacts are preserved.
J2, maneuvers and wider orbit fidelity remain open.

## D313 — V5.6D1b binds orbit-derived target rays to concrete MODEL_INERTIAL common-frame boresights

Date: 2026-09-16. Status: author-approved bounded D1b implementation contract;
candidate implementation remains subject to independent actual-source review.

D1b adds ModelInertialBoresightFrameBinding(frame_id, frame) and
OrbitBoundObservationManeuverCandidate, plus
derive_observation_maneuver_candidate_for_engine_step. The latter two accept
the original ten D1a semantic inputs followed by the required boresight_frame.
All fields are required, frozen and slotted. orbit_observation,
common_frame_boresight and maneuver_candidate are derived init=False values.
No precomputed state/geometry/direction/opportunity/candidate is public input;
dataclasses.replace recomputes the complete composition.

The caller supplies exact ADCSBoresightFrameId, revalidated by its existing
constructor and retained as the original object. The binding requires exact
FrameDefinition, reconstructs its complete nested graph through existing A
frame owners and retains that normalized definition. Existing C1 _frame_text
also applies its B2 exact scalar-Unicode metadata guard before concrete frame
equality, including parameter/source IDs, units, rationale and derivation.
Concrete frame metadata cannot retain caller-overloaded text; valid built-in
Unicode scalar content is preserved without normalization. This guard does not
restrict the separate legacy ADCS label text subclasses. Its kind must be the
actual FrameKind.MODEL_INERTIAL member; EARTH_FIXED, local axes, bare labels
or enums are not frame authority. Complete frame content includes ellipsoid,
rotation/epoch and provenance, not only kind or label. No ID is generated,
hashed, canonicalized or registered globally.

Binding equality compares actual base-string label content and complete
FrameDefinition. Equal labels with different valid concrete definitions remain
unequal. Benign/hostile legacy str subclasses with the same actual label content
remain equal without using caller text equality/hash. Top-level equality uses
D1a hardened evidence equality, hardened binding equality and actual direction
components, avoiding legacy nested candidate/boresight ID equality. Both new
wrappers are explicitly unhashable.

Invalid independent binding fails before D1a. D1b then calls
derive_observation_opportunity_for_engine_step exactly once with the original
ten semantic inputs. D1a retains sole ownership of target/request validation,
C2c certification/step selection, B1/C1 snapshots, local pointing and the
existing ObservationOpportunity. D1a exceptions propagate unchanged. D1b
performs no direct visibility, orbit or C1 calculation.

After D1a succeeds, D1b reconstructs all position/velocity/spacecraft_to_ground
frame definitions and compares them to the complete binding. Mismatch raises
an explicit concrete/common-frame ValueError before V5.3 construction. No
different-inertial-frame transformation or general registry is introduced.
The retained position, velocity and ray GeometryInstants must agree, and
elapsed seconds must equal D1a's selected engine-step start. MODEL_INERTIAL
axes are fixed in the adopted A model; the retained instant is not erased.
The snapshot does not assert continuous direction validity through the window.

CommonFrameBoresightDirection receives the caller frame ID and C1
spacecraft_to_ground components directly, in MODEL_INERTIAL. There is no
EARTH_FIXED rotation, local-basis substitution, ground_to_spacecraft sign
reversal, angular reconstruction, new normalization, clipping or quantization.
The existing ObservationManeuverCandidate is constructed unchanged from the
exact D1a opportunity and exact D1b boresight objects.

The historical V5.3 boresight stores only its label and components; historical
C2 compares frame IDs and cannot detect collisions between concrete model
definitions. The nested candidate alone is therefore not complete V5.6 proof
of same-frame compatibility. A later pairwise V5.6 bridge MUST compare hardened
ModelInertialBoresightFrameBinding values before historical C2/C3 transition
logic. D1b performs no angular-separation, transition, slew feasibility,
sequence feasibility, schedule selection or controller authorization. It adds
no full attitude, roll, actuator, angular-rate, ADCS power/energy or operational
pointing accuracy model.

No catalog/campaign is constructed. Historical V5.3 catalog uniqueness uses
its existing ID equality/hash semantics. D1a/D1b admit caller-supplied legacy
ID text; a future bulk catalog requires its own hardened actual-text uniqueness
contract. D1b neither deduplicates nor rewrites IDs and does not alter that
frozen historical boundary.

Tests retain the real D1a hidden-pass [9,12) composition and exact object/component
identity. Independent test-only unit-sphere inertial target rays cover off-axis,
orbital quadrants, exact nadir, local-azimuth wrap and nonzero Earth rotation.
Absolute-only binary64 bounds are scoped to conditioned synthetic cases.
Test-only projection onto retained orbital axes checks local/common-frame
consistency. Same-binding V5.3 cross/dot atan2 compatibility is checked without
adding pairwise behavior to production. Colliding-label/different-definition,
hostile label text, forged graph, failure-order and replace regressions retain
the ownership boundaries. Existing C1 unresolved-cancellation rejections
propagate; they are not repaired by the adapter.

Real schema-5 capture/to_dict/JSON/from_dict/restore and independently decoded
B2 v1 CoastOrbitInputs recompute equal same-runtime D1b evidence with identical
external arguments. Label-only and equal concrete-binding representation
changes remain outside the B2 manifest. No frame binding, boresight or maneuver
candidate is persisted. Schema 5, portable keys, B2 codec/version/fixed digest,
existing production/tests and frozen audits remain unchanged.

S006 receives one bounded adapter source record; no new external physical source
or spacecraft coefficient is introduced, and D1a's S008 record is preserved.
Catalog generation, pairwise transition/sequence bridge, controller/scheduler,
engine integration, J2, maneuvers/delta-v and wider fidelity remain open.


## D314 — V5.6D1c gates pairwise boresight transition on equal concrete MODEL_INERTIAL bindings

Date: 2026-09-16

D1c accepts one exact existing AgilePointingConfig and an ordered previous/next
pair of exact OrbitBoundObservationManeuverCandidate values. Its frozen,
slotted, default-free OrbitBoundObservationTransition is transient and explicitly
unhashable; the evaluator has the same three required inputs. transition_result
is derived with init=False. No supplied separation, common frame, comparison
boresight, equality result or transition result is accepted. dataclasses.replace
recomputes the composition.

The existing AgilePointingConfig owner revalidates its three fields. Each D1b
wrapper is reconstructed through its public constructor from all eleven init
fields, ignoring orbit_observation, common_frame_boresight and maneuver_candidate
supplied as derived evidence. Exactly two D1b constructions each own one D1a
composition. The reconstructed config and both reconstructed wrappers are
retained. D1c neither imports nor calls D1a, B1, C1, visibility or grid evaluators
directly. Concrete metadata continues through D1b's existing C1/B2 exact-text
guard; D1c adds no parallel frame/text validation.

Before constructing any C2 comparison pair, D1c requires
previous.boresight_frame == next.boresight_frame through hardened D1b equality:
actual base-string ADCS label content plus complete revalidated/text-validated
FrameDefinition content. Kind-only, manifest, hash, ordinary frame-ID equality,
object identity and bare V5.3 boresights are not substitute authority. A colliding
label with different concrete frames rejects. The same concrete frame with
different actual external label text also rejects; no alias registry is implied.
Mismatch raises an explicit ValueError before C2.

After this stronger gate alone, two transient existing CommonFrameBoresightDirection
values carry previous/next retained component triples and the SAME exact
caller-owned frame_id object from the reconstructed previous binding. Historical
C2 redundantly checks legacy IDs, whose text may be a valid hostile str subclass;
sharing this already-owned object preserves C2 compatibility after hardened
admission. No ID is generated, converted or canonicalized. Neither retained D1b
wrapper nor its original boresight/label is rewritten. The temporary pair is not
authoritative frame evidence, exposed result state or persisted state.

Exactly one existing compute_boresight_transition call owns transient
normalization, cross/dot atan2 separation, anchor interpolation, settling,
zero-transition behavior and unsupported-envelope rejection. D1c retains the
exact existing BoresightTransitionResult and propagates C2 exceptions unchanged;
there is no duplicate angular/interpolation/settling law or feasibility boolean.
No hash is introduced for D1c frame admission or result equality; required
inherited config/provenance owner validation remains unchanged.

Evidence remains ordered previous -> next even though angular separation is
symmetric. No simulation-time ordering, view limit, readiness, acquisition
window fit or sequence feasibility is evaluated. Different snapshot instants
are comparable in the same complete fixed MODEL_INERTIAL definition under the
adopted V5.6 model. A retained direction is not a continuous tracking claim.
MODEL_INERTIAL is not an assertion of GCRS/J2000/ITRS identity.

Tests instrument two D1b / two nested D1a / one C2 composition, forged derived
fields, pre-C2 rejection, exact original-ID sharing, hostile external text and
inherited concrete metadata rejection. Test-only conditioned rays independently
exercise cross/dot atan2 in degrees and piecewise-linear timing in seconds with
documented absolute-only roundoff bounds; axis pairs give analytic 0/90 degrees,
and diagonal rays give 45 degrees. Those synthetic support seams do not certify
physical visibility or spacecraft slew accuracy. A separate real schema-5 JSON
restart with independently decoded B2 inputs recomputes equal ordered evidence.

No persistent state or codec keys are added: schema 5, B2 binding/representation
version 1 and its fixed digest remain unchanged. D1d view/window/sequence
composition and hardened catalog uniqueness remain absent. There is no catalog,
campaign, scheduling/controller/engine behavior, full attitude, actuator model
or slew energy; J2, maneuvers/delta-v and wider physical fidelity remain open.
S006 receives one bounded evidence-admission note, with no new physical source
or spacecraft coefficient. Existing production/tests, D313, D1b S006 and D1a S008
remain byte-identical.


## D315 — V5.6D1d preserves C3 view precedence while hardening transition-bearing sequence evaluation

Date: 2026-09-16

D1d adds OrbitBoundObservationSequenceFeasibility and its evaluator, accepting
one exact AgilePointingConfig and an ordered previous/next pair of exact D1b
OrbitBoundObservationManeuverCandidate values. All public type admission occurs
before owner reconstruction. The config is reconstructed through its existing
three-field owner, then each D1b through its eleven init fields. Supplied derived
orbit_observation, common_frame_boresight and maneuver_candidate are ignored.
D1d retains those reconstructed inputs. No direct D1a/C2c/B1/C1 composition is
introduced; each D1b remains owner of its nested D1a calculation.

The ordinary retained previous_execution is the existing
ScheduledObservationExecution(previous.maneuver_candidate,
previous.step_start_seconds). That existing owner validates the acquisition
window. D1a represents one full certified step [s,s+dt) with duration dt, so s
is the sole legal acquisition start. No alternative previous start or execution
identity is introduced, and construction of this value does not execute an
acquisition.

D1d invokes the existing public evaluate_observation_view_feasibility exactly
once for each reconstructed opportunity before branching. Previous-view failure
has precedence; next-view failure is decisive only after previous passes.
These branches skip D1c and call existing C3 once on ordinary previous execution
and next maneuver candidate. D1d requires the corresponding historical reason
and null transition_result, transition_ready_seconds and
candidate_next_start_seconds. Previous-end/latest-start evidence remains present.

Thus unsupported C2 coverage or unequal concrete frames cannot mask a supported
view-failure classification. A view-rejected pair does NOT establish frame
compatibility: transition geometry is unnecessary. No raw view-angle comparison
or duplicate view law is implemented by D1d. Invalid authoritative input still
rejects during reconstruction before view classification.

Only when both public views pass does D1d call the existing D1c evaluator once.
D1c alone owns hardened complete binding admission; D1d repeats no frame-ID,
kind, manifest, identity or hash comparison as a frame gate. D1c frame/coverage
exceptions propagate unchanged. Its additional two D1b reconstructions remain
part of the frozen owner contract.

After D1c succeeds, temporary existing CommonFrameBoresightDirection values use
the two unchanged admitted component triples and the SAME exact original
caller-owned frame-ID object from transition_evidence.previous.boresight_frame.
Temporary existing ObservationManeuverCandidate values use the corresponding
D1c-retained opportunities, and temporary ScheduledObservationExecution uses
D1c's previous certified start. These values are only C3 compatibility inputs.
Neither retained D1b evidence nor ordinary previous_execution is rewritten.
No ID is constructed/canonicalized and no temporary frame evidence is exposed
or persisted.

Exactly one existing evaluate_observation_sequence_feasibility call owns
previous-end/latest-start arithmetic, transition readiness, candidate next start,
window-fit comparison and supported reason selection. On transition-bearing
paths C3 necessarily evaluates C2 again because its frozen public API accepts
no precomputed transition. There are intentionally two C2 evaluations overall:
one inside D1c, one inside C3, and zero direct D1d C2 calls. C3 also repeats its
own view checks. No frozen owner is modified to remove this composition cost.

The exact existing C3 result is retained. On transition-bearing paths its
transition must be non-null and match D1c's complete represented transition:
actual base-string lower/upper anchor-ID text, angular separation, interpolation
fraction, slew elapsed time, settling and total time. Scalar comparisons are
exact because the same deterministic C2 owner receives the same represented
config/components; this is not a geometric approximation tolerance. A mismatch
raises a clear internal-composition ValueError.

ADCSSlewAnchorId admits legacy text subclasses, so ordinary ID/result equality
is insufficient for this check. No hash is used. Top-level equality likewise
covers all six retained fields without reintroducing legacy text equality in
anchor, ordinary execution, view or sequence IDs, while retaining D1b hardened
equality and config parameter evidence. Existing config/provenance formatting,
hash-based uniqueness and admission rules remain unchanged.

Review correction (2026-09-17): ordinary ScalarParameter/dataclass equality
could erase retained provenance differences through caller-overloaded string
equality. D1d now explicitly compares every maximum-view, settling, anchor-angle
and anchor-time parameter: exact ScalarParameter/ParameterProvenance owner types,
represented scalar value, typed parameter/source identities, classification and
status identity, units, ordered source IDs, optional rationale/derivation, and
sensitivity-range presence/type/lower/upper values. All retained provenance text
uses actual base-string content, without caller equality, inequality, hashing
or string conversion. Same actual text remains equal across owner-admitted text
subclasses; different actual text remains unequal in both directions.
This hardens D1d evidence equality only. AgilePointingConfig and
ParameterProvenance admission semantics are unchanged. No text is normalized or
rewritten; no new physical law, parameter, scheduler rule or configuration
rejection is introduced. Reconstruction, view precedence and composition order
remain unchanged.

Second independent review correction (2026-09-17): retained ScalarParameter
values and SensitivityRange lower/upper bounds still used caller-overloaded
numeric equality after the text fix. D1d now compares their local represented
numeric content, without caller equality, inequality or hash dispatch. For
built-in int/float values and their subclasses, int.__int__ / float.__float__
extract the base numeric payload. Integers keep their exact integer value,
including beyond binary64's consecutive-integer range. For wider admitted Real
implementations, Integral values use int(value), and other Real values use
float(value), following the existing ADCS temporary representation convention.
Only those resulting built-ins are compared with exact numeric equality; no
caller equality fallback, string conversion, hash, epsilon, tolerance, extra
rounding or quantization is used. Thus 1 and 1.0, and signed zeros, compare
equal. Wider Real equality means equality of those owner-style representations,
not a claim of exact rational identity beyond the existing float representation.
Sensitivity owners retain their existing raw bounds and admission comparisons;
this local equality rule neither rewrites them nor adds a physical normalization
policy. Text hardening remains unchanged. Owner admission and all composition,
view, transition-consistency, timing and persistence semantics remain unchanged.
This is D1d evidence-equality hardening only, with no new physical law or source.

The result is frozen/slotted/default-free and explicitly unhashable. Three
derived init=False fields are previous_execution, optional transition_evidence
and sequence_result. No externally supplied view/transition/execution/sequence,
next start or frame-comparison result is accepted; replace recomputes all
composition. Ordered previous -> next evidence is retained even for equal or
descending step times. D1d adds no chronological structural rejection.

For D1a's one-step opportunities next_latest_start_seconds equals the next
certified start. C3 alone applies the resulting readiness requirement. Tests
independently cover zero/adjacent steps, sufficient gaps, exact readiness and
one binary64 representable step late, fractional readiness without quantization,
reversed order, and hostile-label/anchor consistency. Unsupported coverage
cannot mask a decisive view failure; authoritative input validation still
precedes view classification. Test-only certified
support seams isolate these compositions; separate real visibility and schema-5
JSON/B2 restart cases recompute equal evidence.

No state or codec keys are added: schema 5, B2 binding/representation v1 and
the fixed digest remain unchanged. There is no catalog/campaign, hardened bulk
uniqueness, scheduling/selection/controller/engine behavior or acquisition
execution. Full attitude, actuator fidelity, slew energy, J2, maneuvers/delta-v
and wider physical fidelity remain open. S006 receives only a bounded admission
and composition note with no new external physical source or spacecraft
coefficient. D1b/D1c S006 and D1a S008 are preserved byte-for-byte.


## D316 — V5.6D1e adds hardened ordered admission for orbit-bound observation candidate catalogs

Date: 2026-09-17

D1e adds OrbitBoundObservationCandidateCatalog with one required constructor
field: an exact tuple of exact OrbitBoundObservationManeuverCandidate values.
The result is frozen/slotted/default-free and explicitly unhashable, with no
derived fields, public factory, lookup/index/cache or feasibility result.
The outer tuple and ALL item types are admitted before any D1b reconstruction.
Each item is reconstructed exactly once, in caller order, using all and only
its eleven init=True dataclass fields. Supplied derived D1b/D1a evidence is not
caller authority. Existing owner exceptions propagate unchanged; no partial
catalog returns. The reconstructed tuple is retained. Empty and singleton
tuples are valid; dataclasses.replace repeats reconstruction and uniqueness.

After every reconstruction succeeds, only ObservationOpportunityId is globally
unique inside the catalog. Its semantic identity is exact wrapper type plus
complete actual base-string content. str.__str__(identifier.value) extracts
temporary exact built-in text without caller string conversion; the exact-str
invariant is checked. The private set contains only (exact owner type, built-in
text) keys, never caller ID objects, text subclasses or D1b objects. Same actual
text is duplicate across admitted subclasses regardless of hostile equality;
different actual text remains distinct even under always-equal behavior.
Original IDs are retained unchanged. No ID generation, canonical replacement,
normalization, stripping, case conversion, encoding or sorting is introduced.
Expected uniqueness cost is O(n + total actual text length), apart from owner
reconstruction; no unconditional worst-case hash-table bound or effective
128-character bound for legacy subclasses is assumed.

Caller order is retained evidence, not execution chronology or scheduling.
Equality requires the exact catalog class, equal length and position-by-position
existing D1b semantic equality. It uses no hashes. The NEW D1e opportunity-ID
uniqueness/equality boundary avoids caller text equality, inequality, hashing,
stringification and formatting. Existing nested D1b/D1a/StableId admission
remains unchanged, including its frozen operations. D1b's other evidence
equality semantics, including inherited request-priority comparison, are not
broadened or rewritten by this collection owner.

Repeated requests, targets, selected times, windows, geography and frame labels
are valid with distinct opportunity IDs. No cross-item registry, shared-input,
shared-policy, shared-frame or chronological gate is added. D1e asserts no
mutually feasible sequence. It admits supplied evidence only; nested D1b
reconstruction still performs its existing D1a/C2c certification and B1/C1
snapshot work. D1e is therefore not geometry-free. There is no D1c/D1d or
historical V5.3 C2/C3 pairwise evaluation and no direct physical-owner call.

No legacy TargetCatalog, ImagingRequestCatalog, ObservationOpportunityCatalog
or ObservationCampaign is constructed. No GroundPointDefinition-to-GroundTarget
conversion is approved: the latter lacks ellipsoid, height and provenance.
There is no bulk generation, compact-block enumeration, automatic opportunity
identity, selection, pagination, scheduling/controller policy or engine
execution. MissionRequestId-to-ImagingRequestId binding and mission/product/
customer completion remain V5.7 responsibilities.

The catalog is transient external evidence. A real schema-5 JSON checkpoint
and independently decoded B2 v1 CoastOrbitInputs permit equal ordered catalog
recomputation with the same external arguments and distinct caller opportunity
IDs. No catalog is checkpointed, no codec key or persistent state is added,
and schema 5, B2 binding/representation v1 and the fixed digest remain unchanged.
S006 receives one bounded admission note, with no new physical source or
spacecraft coefficient. All prior production/tests, D1b/D1c/D1d S006 and D1a
S008 remain byte-identical.

## D317 — V5.6F1 adds an explicit static-axis Cartesian J2 gravity foundation

Date: 2026-09-18. Status: author-approved bounded F1 implementation scope;
the candidate remains unstaged and uncommitted for independent source review.

F1 adds only ops_sim/v5/orbit_j2_gravity.py and two dedicated test modules.
J2GravityModel(gravitational_parameter_m3_s2, j2, reference_radius_m) is frozen,
slotted and default-free. Its three exact ScalarParameter owners retain complete
reconstructed provenance. Their parameter IDs/units are respectively
orbit.gravity.gravitational-parameter (m^3/s^2), orbit.gravity.j2 (1) and
orbit.gravity.reference-radius (m). Mu and gravity radius must be positive;
finite signed synthetic J2 and explicit zero J2 are admitted without an
Earth-only magnitude cap. Existing provenance status rules remain authoritative.

The adopted instantaneous field is static and axisymmetric about the existing
MODEL_INERTIAL +z axis. With r=|position|, q=z^2/r^2 and gravity radius Rg:
Phi=-mu/r+mu*J2*Rg^2/(2*r^3)*(3*q-1), and acceleration=-grad(Phi), namely
-mu*(x,y,z)/r^3 + 3*mu*J2*Rg^2/(2*r^5)*
(x*(5*q-1),y*(5*q-1),z*(5*q-3)).
Phi is negative specific gravitational potential in m^2/s^2; acceleration is
m/s^2. The central term is included exactly once. There is no centrifugal or
Coriolis term, Earth-fixed rotation of the field, or additional harmonic.

J2 is unnormalized: J2=-C20=-sqrt(5)*normalized_C20 under the S008 convention.
The gravity reference radius is independently supplied physical authority,
not ReferenceEllipsoid.equatorial_radius, and J2 is not inferred from shape
flattening. No default Earth GM/J2/radius bundle or Earth-specific factory is
introduced. All test physical inputs are synthetic explicit assumptions.

J2GravityEvaluation(model, position) accepts only exact J2GravityModel and
CartesianPosition owners, reconstructs them, and derives three acceleration
components plus specific_potential_m2_per_s2 as init=False fields. It retains
the complete reconstructed MODEL_INERTIAL frame and exact GeometryInstant
content, with no frame conversion or time advancement. CartesianState and
EARTH_FIXED input are rejected. Both F1 evidence classes are explicitly
unhashable; no generated identity is added. dataclasses.replace recomputes all
derived outputs. evaluate_j2_gravity delegates only to this result owner.

Local exact built-in/Unicode-scalar text prechecks cover parameter IDs, units,
source IDs, optional rationale/derivation, enums and complete frame metadata
before existing scientific owners can compare or hash caller text. Existing
owners then reconstruct and validate the full provenance graph, including
sensitivity bounds. No text coercion, ID rewriting, normalization, source
sorting or shared-owner admission change occurs.

Numerical products accumulate binary mantissas/exponents without forming r^5,
Rg^2 or prematurely normalizing vector components. Explicit zero J2 bypasses
all correction arithmetic. A finite nonzero norm and representability of every
evaluated nonzero term are required. Overflow and a nonzero term rounding to
zero raise intentional ValueError; subnormal nonzero terms are admitted with
their ordinary absolute resolution. This deliberately bounded arithmetic can
reject a total whose separate terms are unsupported. There is no physical
radius floor, clipping, snapping or silent nonfinite output. Near cancellation
and subnormal scales no universal relative-error claim is made.

Independent verification uses prescribed exact-binary equatorial/axial cases,
zero-J2 central references, static-axis symmetries, 90/120-digit Decimal
differentiation of the unsimplified potential, and central finite differences
with a predeclared derivative/roundoff budget. Extreme-scale and intentional
rejection cases, complete metadata reconstruction and AST ownership guards
bound the implementation. Actual validation results belong in MODEL_STATUS.

F1 adds no trajectory propagation or solver, immutable run binding, temporal
visibility, grid projection, contact, observation, maneuver/delta-v, drag,
third-body or SRP behavior. Existing A/B1/B2 and C1/C2/C3/D1 implementations and
tests remain unchanged. Checkpoint schema 5, B2 binding/representation 1/1 and
its fixed digest remain unchanged. J2-C propagation and conservative accumulated
error enclosures are later separate successors. The accepted V5.6E Family-B
interval-view/end-ray obligation remains open; F1 closes neither Family A nor B.

## D318 — V5.6F2 adds pure origin-anchored Cartesian J2 coast evaluation

Date: 2026-09-19. Status: author-approved bounded F2 implementation scope;
the candidate remains unstaged and uncommitted for actual-source review.
Committed F1 baseline: 097c0ee2b6b28201df1dd5d4088d02f55bacbeb0,
tree 24ba322db3bbd2d7397d3c6f29a13fac4b72d349. F1 remains byte-identical.

F2 supplies NOMINAL numerical Cartesian states only. It provides no validated
accumulated state error, enclosure, event-time guarantee or visibility certificate.
F3 conservative accumulated-error work remains required before J2 certification.

Only ops_sim/v5/orbit_j2.py and its two dedicated test modules are added.
The default-free public API is J2CartesianTrajectory(initial_state, gravity_model),
J2RK4SolverConfig(step_seconds, max_steps), and
evaluate_j2_cartesian_state(trajectory, instant, solver_config) -> CartesianState.
The two configuration/authority classes are frozen and slotted. The trajectory
owns exactly the original CartesianState and exact F1 J2GravityModel; it is
unhashable. There is no separately supplied mu/J2/gravity radius, mutable anchor,
propagated state, prior-query field, process cache or generated identity.

Admission exact-checks state and both nested position/velocity owners, preflights
both complete scientific frame graphs using frozen F1 _frame_text, reconstructs
CartesianState through existing owners, requires MODEL_INERTIAL, exact-checks
and reconstructs the complete F1 model, and validates initial F1 evaluability.
Metadata is not rewritten or normalized. The existing CartesianState owner
requires equal reconstructed frames and instants for position and velocity.
General Cartesian states are admitted without B1 ellipse, pericentre, bound-orbit
or EO-validity restrictions. dataclasses.replace reruns normal admission.

The solver normalizes finite non-bool real step_seconds through the existing A
numeric owner and requires a positive result. max_steps is an exact positive
built-in int. It limits RK4 steps for one query, including any endpoint remainder.
There is no adaptive tolerance, B1 residual budget, revolution cap or new mission
horizon. Existing A time/date representation envelopes still apply.

Requested GeometryInstant is exact and rebuilt through A. Its TT reference epoch
must equal the rebuilt initial reference epoch; an equivalent absolute date with
a different reference epoch is not compatible. Both signed and zero spans, and
nonzero initial elapsed times, are supported. Fraction arithmetic computes the
exact difference of the admitted binary64 elapsed values and divides its magnitude
by the exact represented h. Each query starts from the original authority:
floor(abs(T)/h) signed full steps, then at most one signed remainder. T=25,h=10
means 10+10+5, never three redistributed steps. A remainder must round-trip exactly
through binary64; otherwise ValueError rejects before force evaluation. Full
steps plus nonzero remainder are counted before any force, including the initial
admission force check. Excess work raises with no partial integration. Zero span
still reconstructs all graphs and validates initial gravity but takes no RK4 step.

Classical four-stage explicit RK4 integrates dr/dt=v and dv/dt=F1 total gravity.
Stages use delta/2, delta/2, delta and weights (1,2,2,1)/6, with math.fsum for
weighted/additive sums. Signed delta supplies backward propagation. Every query
retains the exact reconstructed requested instant in its returned state.

F1 remains the sole physical force owner. F2 deliberately depends on committed
private _gravity and _frame_text; no J2 equation or B1 propagation is copied or
called in production. Each stage constructs an actual CartesianPosition in the
admitted MODEL_INERTIAL frame, with anchor instant for autonomous force sampling.
Static F1 gravity has no stage-time/Earth-rotation dependence. No fictitious
rounded stage-time sequence is retained. F1 potential restrictions are inherited
although F2 consumes only acceleration. Tests compare every sampled private force
with the public F1 evaluator. An admitted N-step query uses 1+4*N F1 calls.

All intermediate component products/sums must be finite. Nonzero products rounded
to zero, and nonzero increments swallowed when forming a state component, raise
ValueError. Exact cancellation is allowed; nonzero subnormals retain binary64
absolute resolution. A singular zero-position endpoint rejects. Intermediate
overflow may reject even if rearrangement could produce a finite result.
Ordinary coefficient/nonzero rounding remains: these are bounded arithmetic
guards, not formal interval arithmetic, clipping or a global error certificate.

Independent verification includes zero-J2 comparison to B1 and its independently
derived high-precision ellipse reference, separately accounting for B1 uncertainty,
F2 nominal truncation and binary64 arithmetic. Exact synthetic nonzero-J2 circles
use mu=8 m^3/s^2, r=2 m, Rg=1 m, J2=11/32: n=17/16 rad/s and speed=17/8 m/s.
Decimal trigonometric references verify signed fractional, one- and three-orbit
arcs. h/h2/h4 checks demonstrate fourth-order behavior only above the declared
arithmetic/reference floor; invariant drift and approximate reversal are separate
diagnostics. Energy uses public F1 negative potential; only axial hz conservation
is expected of the exact axisymmetric field, not the full angular-momentum vector.
Repeated/reversed queries and canonical full-step prefixes have exact same-runtime
equality. A bounded small-J2 inclined diagnostic separately checks nodal sign and
scaling against a first-order approximation, with predeclared approximation and
integration allowances. S008 records sources, assumptions and test-policy limits.

One query costs O(number of RK4 steps). Repeated independent queries repeat
prefixes. Measured owner reconstruction dominates the inexpensive force kernel;
no speculative optimization or F1 change follows. F5 temporal search is expected
to require deterministic search-local prefix reuse, which F2 does not implement.

There is no immutable run binding, manifest namespace, codec, checkpoint/restart
integration, engine change, temporal visibility, grid projection, contact,
observation adapter, maneuver/delta-v or controller behavior. F4 binding awaits F3
policy. Schema 5, B2 binding/representation 1/1 and fixed digest remain unchanged.
F2's reconstruction evidence concerns only the same explicit external arguments,
not persistence. Family B's interval-view/end-ray correction remains open;
nominal F2 propagation closes neither the full Family-A nor Family-B obligation.


## D319 — Task 06A adds a bounded accumulated J2 endpoint enclosure

Date: 2026-09-23. Status: author-authorized implementation candidate for
independent review; the numerical policy is not yet independently accepted.
Baseline is accepted Task05C f907dacdf85401904fe805cb9d153a88f218f4a6.

The additive orbit_j2_enclosure owner retains complete original F2 trajectory,
F1 gravity/frame/TT provenance, requested instant, F2 solver and explicit F3
policy. It encloses the continuous F1 IVP for represented inputs using directed
Decimal box Taylor integration (order six, remainder seven), with checked
whole-step Picard tubes excluding the singularity. Success reports separate
position/velocity infinity-norm endpoint error bounds around the unchanged F2
nominal result. Unresolved computations expose no nominal state or error bound.
Invalid input graphs remain errors. All output fields are internally recomputed.

V5_J2_ENCLOSURE.md gives the inclusion derivation, local-to-accumulated recurrence,
complete arithmetic/admission assumptions and primary source locations. Error
is distance from the independently enclosed real solution to the represented
F2 output, so its force/stage/coefficient/sum rounding and truncation are included
without treating refinement or a second nominal solver as a certificate. This
is a working enclosure implementation with a stated arithmetic contract, not a
machine-checked formal proof. Wrapping and work/domain failure remain explicit.

Policy version 1 has no constructor defaults: 40..80 decimal digits, 1..4096
steps, 1..16 Picard attempts/step, step [2^-20,1024] s and radius floor
[1e-6,1e12] m. Nonzero dynamical inputs have magnitudes [1e-100,1e100], span is
at most 86400 s, and F2 is independently capped at 4096 steps for F3 queries.
These computational limits do not narrow the standalone F2 API or imply that
all in-range queries enclose. Signed origin-anchored grids have at most one
remainder; no global cache or prior-query state exists. Runtime/result evidence
belongs to MODEL_STATUS and the external archive.

Independent verification uses rational analytic reference intervals for positive,
zero and negative J2 circles, a zero-J2 radial parabola, directed primitive and
potential-gradient checks, and metadata, arithmetic, work and fresh-process
contracts. The small synthetic inclined pilot qualifies short-arc usefulness
only, not an Earth model or flight truth. F3 closes the bounded accumulated
endpoint error obligation; F4 binding/persistence and later continuous visibility
integration remain open, including Family B's interval-view/end-ray requirement.
F1/F2 bytes, schema 5, B2 1/1/fixed digest, programs 1-7, MS accounting/controller
semantics and historical Task05C results remain unchanged. Full V5 is unfinished.


## D320 — Task 06B binds original J2 inputs and recomputes after restore

Date: 2026-09-23. Status: author-authorized implementation candidate, pending
independent review. Baseline is accepted Task06A
ff4e26c305ece6cd9ee2d117da1d1ab31f03aee5. D319 and V5_J2_ENCLOSURE.md retain
the historical F3 contract; its bounded endpoint-enclosure scope is accepted.

Use one coast_orbit slot with exact-type dispatch to the unchanged two-body
owner or the new frozen J2CoastOrbitInputs. Retain all original trajectory,
frame/TT/anchor/gravity/provenance content and both numerical policies. Explicit
J2 model, representation/binding 1/1 and F3 policy version 1 are persisted and
validated. Reserve v56f4-j2-coast for the bounded SHA-256 content identity;
exclude the previous derived label, include numerical/world context and manifest
associations. V5_J2_BINDING.md defines scope and encoding separately from the
complete ExperimentBundle input digest and code/environment checks.

Extend only the typed input allowlist. Do not persist J2EnclosureResult or its
computed Decimal bounds. Schema 5, canonical/bundle 1, the eight existing input
fields/seven positional arguments and programs 1-7 are unchanged. Legacy no-orbit
and B2 canonical bytes and fixed digest are regression guards. Validate stale,
missing, malformed and cross-namespace inputs before mutable restoration.

The explicit context query evaluates unchanged F3 at TT-epoch-relative engine
clock time with the original anchor. No integration occurs during binding,
hashing or restore; no query mutates engine state or stores a propagated cache.
Unresolved queries remain unusable for bounds. All engine paths preserve their
existing physical behavior; the two-body query/search rejects J2. Fresh-process
schema-5 and self-contained bundle continuation use existing program version 1,
including its declared legacy downlink semantics. Numerical usefulness beyond
the accepted short synthetic spans is not inferred from restart equality.

F1/F2/F3 implementation bytes and S008 are unchanged. J2 temporal visibility,
Family B interval-view/end-ray correction, long-horizon qualification, maneuvers,
orbit-driven campaigns and full V5 remain open. No 05C campaign rerun or new
hardware validation claim is authorized by this persistence task.
