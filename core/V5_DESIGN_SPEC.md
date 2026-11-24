# V5 Design Specification

Status: APPROVED V5.0A
Branch: v5-redesign
Baseline: v4.0-final
Purpose: scientific and software design contract for the V5 redesign

---

## 1. Research Question

Primary research question:

How do alternative optical LEO Earth-observation spacecraft architectures
trade mission productivity, robustness, resource preservation, and
post-design-life survivability when operated under the same professional
mission-operations controller and common environmental conditions?

V5 is a comparative engineering simulation study.

It is NOT:
- an operational forecast for KazEOSat-1
- a validated digital twin
- flight software
- a real mission planner
- telemetry reconstruction
- a claim about the remaining lifetime of any real spacecraft

KazEOSat-1 and other public EO spacecraft may provide reference values,
sanity ranges, and architectural inspiration only.

---

## 2. Primary Study Scope

Primary mission family:

- optical LEO Earth observation
- panchromatic and multispectral imaging
- geometry-constrained observation opportunities
- ground-station downlink
- finite spacecraft resources
- degradation and post-design-life operation

Primary independent variable:

- spacecraft hardware configuration

Primary control variable:

- one common professional Mission Operations Controller

Primary experiment:

12 alternative spacecraft configurations are exposed to the same mission
requests, environment, scenario definitions, and stochastic event worlds.

The configurations are engineering archetypes informed by public spacecraft
data and literature. They are not intended to be exact replicas of specific
real spacecraft.

SAR, hyperspectral, 6-DOF attitude dynamics, high-fidelity RF propagation,
and electrochemical battery models are outside the primary V5 scope.

---

## 3. Experimental Variables

### 3.1 Independent Variable

SpacecraftConfiguration.

Potential configuration differences include:

- battery energy capacity
- solar-array generation capability
- payload properties
- storage capacity
- communications capability
- ADCS agility and pointing capability
- thermal characteristics
- propulsion / delta-v capability
- redundancy / reliability characteristics
- subsystem power demands

Configurations must obey common comparison constraints.

A configuration may not become superior simply by receiving unlimited mass,
power, storage, communications, and redundancy simultaneously.

Architectural advantages must have explicit costs or trade-offs.

### 3.2 Controlled Variables

Unless an experiment explicitly varies them:

- mission request catalog
- initial orbit class
- ground network
- controller implementation
- flight rules
- simulation horizon
- environmental model
- scenario/event catalog
- stochastic random world
- numerical timestep policy

Common Random Numbers should be used where appropriate so configurations
experience equivalent stochastic worlds.

### 3.3 Dependent Variables

Primary outputs include:

- useful target area acquired
- mission value acquired
- high-priority request completion
- useful data successfully returned to ground
- observation availability
- safe-mode / backup-mode time
- battery energy and minimum SOC
- thermal excursions and thermal margin
- storage occupancy and lost data
- communication opportunity utilization
- remaining delta-v
- maneuver count
- subsystem degradation
- subsystem failure modes
- spacecraft survival
- simulated remaining mission capability / RUL where appropriate

No single scalar "best spacecraft score" is the primary scientific result.

Trade-offs and Pareto relationships are primary.

---

## 4. Model Fidelity Philosophy

V5 uses reduced-order physical models.

The governing rule is:

Use the simplest physically meaningful model that can change or explain the
research conclusions.

Do not add complexity solely to appear realistic.

Each important model parameter must be classified as one of:

- PUBLIC SPECIFICATION
- LITERATURE VALUE
- DERIVED VALUE
- EXPLICIT MODEL ASSUMPTION

Important assumptions must have a documented sensitivity range where
reasonable.

### Required V5 physical improvements

Primary V5 must replace major arbitrary proxies where practical:

- battery energy in Wh rather than mode-specific SOC deltas
- subsystem power consumption in W
- solar generation and eclipse effects
- temperature state and reduced thermal balance
- time-scaled degradation
- geographic mission targets
- orbit-derived target visibility
- geometry-derived off-nadir angle
- ADCS slew and settling constraints
- coherent payload data generation
- explicit data-product lifecycle
- storage capacity and processing
- geometry-dependent communications capability
- physical delta-v accounting
- maneuver-driven orbital-state changes
- professional planning using resource forecasts

---

## 5. Time and Numerical Model

Time is represented fundamentally in seconds.

Required engine quantities:

- simulation_time_seconds
- timestep_seconds
- timestamped events

The primary simulation timestep is not assumed in advance.

Candidate physics timesteps:

- 15 minutes
- 5 minutes
- 1 minute

The final timestep must be selected using numerical convergence tests.

Fast geometric phenomena such as ground-station contact boundaries may use
finer internal sampling than the main spacecraft physics timestep.

The architecture should permit multirate or event-boundary evaluation where
it materially improves accuracy.

Initial V5 refactoring may reproduce V4 behavior using a 3600-second
compatibility timestep.

---

## 6. State and Configuration Separation

V5 must clearly distinguish what the spacecraft IS from what is currently
happening to it.

### SpacecraftConfiguration

Immutable design / hardware parameters.

Examples:

- battery nominal capacity
- solar-array nominal power
- payload parameters
- storage capacity
- transmitter properties
- ADCS limits
- thermal coefficients
- propulsion capability

### SpacecraftState

Physical dynamic state.

Examples:

- battery energy
- temperatures
- stored data
- orbital state
- subsystem health
- remaining delta-v
- current attitude / operational status where modeled

### GroundKnowledgeState

What mission operations currently believes about the spacecraft.

Ground knowledge may be delayed or stale.

The controller must not receive perfect real spacecraft state unless a
specific experiment intentionally assumes ideal knowledge.

### MissionState

Mission requests, plans, delivered products, deadlines, observation history,
and other mission-level information.

### Diagnostics / Counters

Research logging and derived counters must not silently become physical state.

---

## 7. Mission Operations Architecture

Primary V5 uses one professional MissionOperationsController.

The controller must:

- operate on ground knowledge rather than hidden real state
- enforce hard flight rules
- forecast resource evolution
- forecast target and contact opportunities
- construct a rolling mission plan
- consider priority and deadline
- consider battery, thermal, storage, communications, ADCS, and delta-v
- replan when new information or important events arrive
- avoid knowingly violating physical constraints

Primary objective hierarchy:

1. spacecraft safety
2. mandatory protection / collision / stationkeeping requirements
3. high-priority mission requests
4. useful mission data returned to ground
5. preservation of spacecraft resources and lifetime

The planning implementation may initially use a transparent deterministic
heuristic.

The architecture must permit later constrained optimization such as
CP-SAT / MILP without rewriting the spacecraft physics.

Onboard FDIR remains logically separate from the ground controller.

The twelve historical V4 operator policies remain available only for:

- regression
- legacy reproduction
- controller sensitivity studies

They are not the primary V5 independent variable.

---

## 8. Required Causal Chain

Primary V5 should support the following causal chain:

environment / orbit
    ->
target and ground visibility
    ->
professional mission plan
    ->
slew / observation / maneuver / downlink actions
    ->
subsystem power loads
    ->
battery and thermal evolution
    ->
payload / data production
    ->
processing and storage
    ->
communications and data delivery
    ->
degradation / failure risk
    ->
future mission capability

Subsystem effects should not exist as disconnected score multipliers when a
clearer physical causal mechanism can be modeled at Level-1 fidelity.

---

## 9. Validation Requirements

V5 is not accepted because the code runs.

Required validation classes:

### Physics unit validation
Hand-calculated cases for important equations.

### Limiting cases
Examples:
- zero solar generation
- zero payload demand
- infinite/very large storage sanity case
- no ground contact
- no degradation
- depleted delta-v
- impossible target geometry

### Conservation / accounting
Where applicable:
- energy
- data
- storage
- delta-v
- event counts

### Numerical convergence
Compare candidate timesteps.

### Cross-subsystem causality
Examples:
- increased payload use -> increased load -> battery/thermal consequence
- poor geometry -> reduced observation/downlink capability
- maneuver -> delta-v loss -> orbital-state change -> geometry consequence

### Determinism
Identical configuration + seed + inputs must reproduce identical results.

### Common-random-number consistency
Compared spacecraft configurations should experience equivalent stochastic
worlds where scientifically appropriate.

---

## 10. Explicit Non-Goals for Primary V5

Primary V5 will not require:

- full spacecraft digital-twin fidelity
- FEM structural or thermal simulation
- electrochemical cell simulation
- 6-DOF spacecraft attitude integration
- complete RF link-budget / BER propagation model
- real-time global weather assimilation
- operational TLE prediction service
- exact reconstruction of KazEOSat-1 operations
- machine-learning mission control
- autonomous LLM decision-making
- realistic human personality models for operators

These may be future extensions only if scientifically justified.

---

## 11. Primary Hypotheses

H1:
No single constrained spacecraft architecture will dominate all primary
mission-performance and survivability metrics.

H2:
Architectures optimized for maximum imaging productivity will generally pay a
cost in energy, thermal, storage, communications, propulsion, reliability, or
lifetime margin.

H3:
Architectures with larger resource reserves will not necessarily maximize
delivered mission value if other bottlenecks dominate.

H4:
Environmental and operational stress will change the relative ranking of
spacecraft architectures.

H5:
A professional resource-aware controller will reduce avoidable failures and
resource violations compared with simple reactive legacy policies, while not
eliminating hardware-dependent differences.

These are hypotheses to test, not conclusions assumed by the simulator.

---

## 12. Definition of Done — V5 Model

The V5 model is considered code-complete only when:

1. Configuration and dynamic state are separated.
2. Simulation time is configurable.
3. EPS uses physical energy/power accounting.
4. Thermal state is explicitly modeled.
5. Targets use geographic/orbital geometry.
6. ADCS constraints affect observation feasibility.
7. Payload generates physically interpretable data products.
8. Storage and OBC participate causally in mission operations.
9. Communications depend on contact geometry and hardware capability.
10. Propulsion uses explicit delta-v accounting.
11. Maneuvers influence orbital state / future geometry.
12. One professional common controller operates all primary configurations.
13. Twelve constrained spacecraft configurations exist.
14. Legacy V4 policies remain reproducible outside the primary path.
15. Critical physics has hand-calculation tests.
16. Numerical timestep convergence has been evaluated.
17. Deterministic and common-random-number tests pass.
18. A multi-configuration pilot produces interpretable architectural
    trade-offs without relying on one arbitrary coefficient.
19. Full regression tests pass.
20. V4.0-final remains immutable and reproducible.

Paper production, full Monte Carlo evidence campaigns, final figures,
publication formatting, and archival packaging are subsequent research stages
and are not required for V5 code-complete status.