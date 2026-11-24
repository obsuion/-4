# V5 Source Register

Status: ACTIVE

Every scientifically important V5 parameter must have traceable provenance.

Allowed provenance classes:

- PUBLIC SPECIFICATION
- LITERATURE VALUE
- DERIVED VALUE
- EXPLICIT MODEL ASSUMPTION

---

## Required Record Format

Each parameter or parameter family should record:

| Field | Meaning |
|---|---|
| ID | Stable source/parameter identifier |
| Subsystem | EPS / thermal / payload / ADCS / communications / etc. |
| Parameter | Quantity being supported |
| Value / Range | Numerical value or range |
| Units | Physical units |
| Provenance Class | Public spec / literature / derived / assumption |
| Source | Document, paper, manufacturer, agency, standard, etc. |
| Access / Publication Date | When relevant |
| Interpretation | How the source is used in V5 |
| Uncertainty / Sensitivity | Range to test if relevant |
| Status | TO VERIFY / VERIFIED / REJECTED / SUPERSEDED |

---

## Initial Source Families

### S001 — KazEOSat-1 public reference specifications

Purpose:
Reference and sanity metadata only.

Potential quantities:
- orbit altitude
- inclination
- spacecraft mass
- spacecraft dimensions
- stated spacecraft power
- optical resolution
- scene dimensions
- downlink metadata
- revisit/productivity metadata

Status:
TO VERIFY individually before V5 use.

Important:
Public KazEOSat-1 specifications do not make V5 a KazEOSat-1 digital twin.

#### V5.2D2A source-specific public-value audit

The primary Airbus Defence and Space, *KazEOSat-1 Technical and Product
ordering Description Sheet* (April 2019) records a 2.1 m x 3.7 m body,
830 kg launch mass, 7.25-year design lifetime, 750 km sun-synchronous orbit,
98.56 degree inclination, acquisition capacity up to 228,000 km^2/day,
1 m PAN and 4 m MS resolution, 20 km swath, and 270 Mbit/s X-band instrument
telemetry. The sheet does not provide a 1200 W spacecraft-power value.

Public records conflict and must remain source-specific. WMO OSCAR currently
lists 918 kg launch mass, 830 kg dry mass, 759 km altitude, and 1200 W, while
its KazEOSat programme page states a 7 years design lifetime. An earlier
non-contractual Airbus marketing sheet reports 220,000 km^2/day, a 630 km
altitude, and mission lifetime greater than 7 years. Secondary catalogues also
report values such as 820 kg and 220,000 km^2/day. Consequently, 820 kg,
220,000 km^2/day, and 7 years are not uncontested primary values. The generic
7-year record does not override Airbus's source-specific 7.25-year figure, and
1200 W may be retained only with its own explicit source provenance. D2A does
not silently rewrite historical V4 reference metadata or freeze any of these
values into a V5 production configuration.

Sources:

- Airbus Defence and Space, *KazEOSat-1 Technical and Product ordering
  Description Sheet*, April 2019,
  `r53192_9_kazeosat-1-technical-descriptionsheet-180419.pdf`.
- WMO OSCAR/Space, *Satellite: KazEOSat-1* and *Satellite Programme:
  KazEOSat*, source-specific catalogue records.
- Airbus Defence and Space, *KazEOSat-1 Superior Image Quality, Tackling
  Challenging Acquisitions*, ADS/024/0216, non-contractual marketing sheet.

#### V5.5A nominal X-band rate and externally supplied serviceable contacts

The April 2019 Airbus technical sheet is assigned source record
`s001-airbus-kazeosat-1-technical-sheet-2019`. It reports the KazEOSat-1
instrument telemetry link as X-band at 270 Mbit/s, identifies Astana,
Kazakhstan as the main receiving station, and identifies Astana as the S-band
uplink station. V5.5A maps only the numerical link-rate claim to
`communications.nominal-downlink-data-rate = 270_000_000.0 bit/s`, classified
PUBLIC SPECIFICATION and VERIFIED in the KazEOSat-like reference fixture.

The value means nominal X-band data-link rate during an externally supplied
serviceable contact. It is not detector generation, recorder write, RF symbol,
protocol- or coding-adjusted net, measured useful, or guaranteed operational
throughput. It supplies no efficiency, link-budget, weather, or communications-
power model.

---

### S002 — Optical EO spacecraft architecture survey

Purpose:
Establish realistic ranges for the twelve V5 spacecraft configurations.

Needed quantities may include:
- spacecraft mass class
- available electrical power
- battery capacity / endurance
- payload power
- storage capacity
- downlink capability
- pointing agility
- off-nadir limits
- propulsion / delta-v capability
- design lifetime

Status:
TO RESEARCH

---

### S003 — Spacecraft EPS literature

Purpose:
Support reduced-order solar-array, battery-energy, efficiency, charge/discharge,
and degradation models.

Status:
TO RESEARCH

#### V5.1A battery parameter requirements

V5.1A defines the physical semantics and units of these parameters without
freezing numerical values for any real or reference spacecraft configuration:

- `eps.battery.nominal-energy` (`Wh`)
- `eps.battery.charge-efficiency` (`1`)
- `eps.battery.discharge-efficiency` (`1`)
- `eps.battery.max-charge-input-power` (`W`)
- `eps.battery.max-discharge-output-power` (`W`)

Final configuration values require resolution as PUBLIC SPECIFICATION,
LITERATURE VALUE, DERIVED VALUE, or a documented EXPLICIT MODEL ASSUMPTION.
Sensitivity ranges are required wherever conclusions depend materially on a
parameter.

#### V5.1B electrical-load composition requirements

V5.1B defines bus-side load-composition semantics but does not freeze power
magnitudes for the spacecraft/base bus, OBC/data handling, ADCS, payload,
communications, thermal control, or propulsion ownership families.

A runtime `PowerLoadBreakdown` is a derived physical ledger, not itself a
sourced hardware parameter. Future load-producing models must derive its
contributions from parameters classified as PUBLIC SPECIFICATION, LITERATURE
VALUE, DERIVED VALUE, or documented EXPLICIT MODEL ASSUMPTION. Sensitivity
analysis is required wherever assumed subsystem power materially changes
architectural conclusions.

V5.2C2 keeps requested component load separate from explicitly supplied
served component power. Aggregate `unmet_load_w` does not identify which
components were served, so C2 introduces no inferred priority, proportional
curtailment, or other load-shedding allocation. Future service-allocation
logic requires its own operational evidence and decisions.

#### V5.1C solar-generation requirements

`eps.solar-array.nominal-generation` remains the owning hardware parameter in
W. V5.1C interprets it as nominal bus-side generation under full direct
illumination and zero-degree incidence, before later degradation or
temperature modifiers. This slice freezes no real or reference numerical
value.

The one-sided cosine-incidence Level-1 relationship requires scientific
support and documentation before final model freeze. Runtime `sunlit` and
`incidence_angle_deg` values are environment inputs, not spacecraft hardware
parameters; their calculation belongs to the later orbit/illumination model.
Degradation and temperature modifiers require their own sourced or explicit
assumption parameters. Sensitivity analysis is required if the simplified
solar response materially affects architectural conclusions.

#### V5.2D1 physical degradation state and initial conditions

V5.2D1 defines the following configuration-owned initial-condition parameter
families without freezing a numerical value for any real spacecraft:

- `degradation.battery.initial-usable-capacity-retention` (`1`)
- `degradation.solar.initial-generation-retention` (`1`)
- `degradation.battery.initial-energy-throughput` (`Wh`)

The corresponding runtime truth is battery usable-capacity retention,
cumulative battery energy throughput, and solar-generation retention. Future
effective capability relationships are documented as:

`E_usable_max(t) = E_nominal * r_capacity(t)`

`P_solar_capability(t) = P_nominal * r_solar(t)`

Both retention variables are physical property-retention quantities with
`0 < r <= 1`. Cumulative battery energy throughput is physical operating
history. Equivalent full cycles are not authoritative state in D1 and may be
derived later only after a capacity basis is defined.

These relationships do not modify V5.1 EPS or solar output in D1. No
ageing-rate law or Arrhenius coefficient or value is introduced. Ageing laws,
rates, and coefficients require literature review, explicit provenance, and
sensitivity analysis before V5.2D2 may freeze or evolve ageing behavior.

#### V5.2E1 EPS-to-thermal engine integration

V5.2E1 evaluates the existing EPS proposal and thermal coupling together. EPS
and thermal use the same engine interval. The current EPS interval result is
passed directly to thermal coupling; no EPS or thermal equation, ageing law,
numerical spacecraft parameter, or same-step thermal feedback into EPS is
introduced. Physical degradation state remains unchanged by this integration
slice.

#### V5.2D2A battery degradation physics

D2A uses a **LINEARIZED LEVEL-1 DAMAGE ACCUMULATION** model. It separates
calendar and cycling damage and applies independently provenance-backed
normalized Arrhenius temperature factors:

`A(T) = exp[-(E_a / R) (1/T - 1/T_ref)]`

with the exact molar gas constant
`R = 8.31446261815324 J mol^-1 K^-1`. The NIST 2022 CODATA listing records
`R = N_A k` as exact. No universal activation energy is implied.

Battery-side interval energy throughput is:

`delta_E_throughput = eta_charge P_charge_input dt_h + (P_discharge_output / eta_discharge) dt_h`

using actual V5 EPS charge input and discharge output. It is absolute stored
plus extracted energy movement. Curtailed generation, unmet load, raw solar
generation, requested load, net bus load, and battery conversion loss are not
added separately.

V5 cumulative throughput is measured in Wh. Many battery-ageing studies use
charge throughput `integral |I| dt` in Ah; those quantities are not identical,
so an Ah-based empirical coefficient must not be copied into the V5 Wh law.
The D2A calendar and cycling coefficients are explicit reduced-order modeling
choices requiring provenance and sensitivity analysis, not literature values
transferred from a particular cell chemistry.

Battery temperature is an explicit representative interval input. D2A does
not choose start, endpoint, or interval-average temperature and does not
integrate degradation into the engine; that numerical coupling choice belongs
to D2B. D2A freezes no real spacecraft ageing coefficient or rate.

The configuration parameter families are:

- `degradation.battery.reference-temperature` (`K`)
- `degradation.battery.calendar-damage-rate-at-reference` (`1/s`)
- `degradation.battery.calendar-activation-energy` (`J/mol`)
- `degradation.battery.cycling-damage-per-normalized-throughput-at-reference`
  (`1`)
- `degradation.battery.cycling-activation-energy` (`J/mol`)

Schmalstieg, J.; Käbitz, S.; Ecker, M.; Sauer, D. U. (2014), "A holistic
aging model for Li(NiMnCo)O2 based 18650 lithium-ion batteries," *Journal of
Power Sources* 257, 325-334, DOI
`10.1016/j.jpowsour.2014.02.012`, supports separating calendar and cycling
ageing and recognizing temperature, SOC/voltage, depth/range, and throughput
stress. Its chemistry, fitted coefficients, and Ah-oriented usage semantics
are not automatically transferable to V5.

#### V5.2D2B1 configuration ownership

`BatteryAgeingModelConfig` is an immutable model definition owned by
`DegradationConfig` together with degradation initial conditions. Its
independent module depends only on parameter and identity contracts, allowing
the spacecraft configuration graph to own the definition while pure
degradation physics consumes both it and `BatteryConfig` without a circular
dependency.

Schema 3 remains unchanged. Checkpoints preserve mutable degradation truth;
the immutable ageing model remains part of the externally supplied
`SimulationInputs` used for restore. This ownership cleanup introduces no new
law, source, coefficient, parameter value, runtime evolution, or EPS capability
coupling.

#### V5.2D2B2 transactional degradation evolution

For a complete coupled interval, D2B2 derives battery-side throughput from the
same EPS interval result and the active `BatteryConfig` used to compute that
result. The configuration-owned `BatteryAgeingModelConfig` then drives one
pure battery degradation proposal. No alternate battery configuration,
duplicated throughput equation, new ageing coefficient, or current-interval
capability feedback is introduced.

Battery degradation does not evolve on the EPS-only compatibility path because
that path supplies no battery thermal endpoint. Zero damage coefficients keep
capacity retention constant but do not erase actual cumulative battery energy
throughput.

#### V5.2E2 degradation-aware EPS capability coupling

E2 applies authoritative start-of-interval retention through the reduced-order
relationships `C_usable = C_nominal r_battery` and
`P_solar_capability = P_nominal r_solar`. Battery retention changes the usable
energy ceiling but introduces no charge- or discharge-power fade and no
efficiency change. Solar retention modifies nominal generation once before
the existing illumination and incidence geometry.

After coupled degradation is proposed, explicit reconciliation compares the
raw EPS endpoint with the new usable capacity. Energy above that capacity is
reported as unavailable energy: a loss of modeled usable stored-energy
availability, not bus load, curtailment, conversion loss, unmet demand, or
thermal heat. Stored energy at or below the new capacity is not proportionally
rescaled.

E2 adds no new literature value, ageing law, radiation relationship, or
chemistry-specific battery claim. Existing parameter provenance and later
sensitivity requirements remain unchanged.

#### V5.3E1 optical-acquisition EPS resource evaluation

V5.3E1 adds no new physical source or value. For a V5.3D-feasible acquisition,
it treats the B2 acquisition power as constant or interval-average Level-1
electrical demand over the exact acquisition duration. That demand is added
exactly once to the caller-supplied non-acquisition payload load; `payload_w`
may already contain nonzero standby or background demand.

E1 reuses the start-of-interval degradation-aware EPS capability and existing
EPS interval transition exactly once. Solar retention is therefore applied
once before existing illumination geometry, while battery retention changes
usable energy capacity without adding charge- or discharge-power fade. E1
does not evolve degradation or reconcile an authoritative endpoint.

Aggregate EPS service provides no component allocation. With acquisition
request `A`, aggregate requested load `R`, aggregate served load `S`, and all
other requested load `B = R - A`, the allocation-free bounds are
`P_acq,min = max(0, S - B)` and `P_acq,max = min(A, S)`. For the independent
allocation-required example `A = 90 W`, `B = 100 W`, and `S = 150 W`, these
give `max(0 W, 150 W - 100 W) = 50 W` and `min(90 W, 150 W) = 90 W`.
Energy bounds multiply each power bound by the same duration and divide by
3600. They are bounds, not an inferred actual served energy.

No priority, proportional-curtailment, or load-shedding law is introduced.
Requested energy is not automatically served energy, and neither bounded
partial service nor aggregate shortfall creates a partial-image or data-scaling
law. Thermal, storage, downlink, engine, and mutable-state coupling remain
outside E1.

#### V5.3F2 exact electrical authorization

V5.3F2 adds no new physical source or value. It computes E1 exactly once from
the active context's agile-pointing, optical-acquisition, EPS, battery, and
degradation snapshot. Exact `FULLY_SERVED` status and zero unmet aggregate load
are both required before thermal composition.

Under exact zero unmet load and the existing per-component constraint that
served power cannot exceed requested power, all seven components are uniquely
`served=requested`. The resulting complete ledger is a derived special case,
not a priority, proportional, shedding, or other shortfall rule. F2 makes no
shortfall allocation, no degradation evolution or capacity reconciliation, and
no authoritative commit.

#### V5.3F3A transaction-kernel refactor

V5.3F3A adds no new physical source or value and changes no physical or
numerical equation. Generic EPS capability and interval-transition semantics
remain unchanged, while the existing battery-throughput, degradation, and
capacity-reconciliation sequence gains one private owner inside one engine
transaction kernel. Checkpoint schema 3 and persistent state remain unchanged.

#### V5.3F3B authorized imaging resource transaction

V5.3F3B adds no new physical source or value, introduces no new equation, and
adds no new literature. It reuses the exact EPS interval
and EPS capability proposals produced internally by F2 rather than recomputing
generic EPS integration. Supported sequence or electrical nonauthorization
causes no physical commit.

For authorized imaging, the existing shared degradation and capacity-
reconciliation tail executes once. Start-of-interval capability semantics and
optional endpoint solar-degradation semantics remain unchanged, and the
successful result means only that one resource-served imaging interval was
committed through the existing physical/runtime transaction.

---

### S004 — Spacecraft thermal-control literature

Purpose:
Support reduced-order thermal capacitance, heat-generation, heat-rejection,
and operational-temperature models.

#### V5.2A1 thermal configuration requirements

V5.2A1 defines the semantic ownership and units of the following node
parameter families without freezing numerical values:

- `thermal.node.<node>.heat-capacity` (`J/K`)
- `thermal.node.<node>.emissivity` (`1`)
- `thermal.node.<node>.radiating-area` (`m^2`)
- `thermal.node.<node>.operating-min-temperature` (`K`)
- `thermal.node.<node>.operating-max-temperature` (`K`)
- `thermal.node.<node>.survival-min-temperature` (`K`)
- `thermal.node.<node>.survival-max-temperature` (`K`)

Each effective conductive link owns
`thermal.link.<link>.conductance` (`W/K`). A1 freezes these semantics and
units, not numerical values. Final values require resolution as PUBLIC
SPECIFICATION, LITERATURE VALUE, DERIVED VALUE, or a documented EXPLICIT
MODEL ASSUMPTION. Sensitivity ranges are required wherever assumptions
materially affect architecture conclusions.

Effective lumped-node and link parameters are reduced-order model quantities,
not claims of detailed spacecraft thermal geometry.

#### V5.2B thermal-physics relationships

V5.2B uses the reduced-order lumped-node energy balance:

`C_i dT_i/dt = sum Q_i`

Each undirected effective conductive link is evaluated once using:

`Q_a_to_b = G_ab (T_a - T_b)`

Each node exchanges radiation with an explicit effective sink boundary using:

`Q_rad_into = epsilon sigma A (T_sink^4 - T^4)`

The Stefan-Boltzmann constant is
`sigma = 5.670374419e-8 W m^-2 K^-4`, from the NIST 2018 CODATA
recommended value and exact under the post-2019 SI definition.

Effective conductance `G` is a reduced-order parameter requiring later
resolution as a literature value, derived value, or documented explicit model
assumption. Emissivity and effective radiating area retain the V5.2A1
provenance ownership described above. `radiative_sink_temperature_k` is a
transient boundary input, not spacecraft hardware or automatically assumed
deep-space, Earth, or orbital temperature.

This model does not claim detailed surface, view-factor, or orbital thermal
geometry. Explicit Euler is a transparent numerical model choice that requires
later timestep-convergence evidence; it is not a physical law.

#### V5.2C1 explicit heat forcing and EPS coupling

The source-aware node energy balance admits explicit applied heat:

`C_i dT_i/dt = Q_cond,i + Q_rad,i + Q_applied,i`

V5.2C1 decomposes applied heat as:

`Q_applied = Q_internal + Q_absorbed_solar + Q_absorbed_albedo + Q_absorbed_earth_ir + Q_battery_conversion_loss`

V5.1 battery conversion-loss energy is interpreted as Level-1 thermal
dissipation at the configured battery thermal role. Its interval-average heat
power is:

`P_battery_conversion_heat = E_conversion_loss_Wh * 3600 / dt_s`

Internal subsystem dissipation remains an explicit transient input. C1 does
not equate requested or served electrical load with waste heat, because some
electrical energy may leave as RF, mechanical, propulsive, or other exported
energy and component-level service allocation is not yet defined. Sourced
component heat-deposition fractions are deferred to V5.2C2.

Absorbed solar, albedo, and Earth-IR powers are explicit transient forcing
inputs already assigned to thermal nodes. C1 claims no orbit, surface,
view-factor, or environmental absorption model. The effective radiative sink
boundary and explicit absorbed forcing must describe non-overlapping terms; a
caller must not encode the same incoming radiation in both.

This slice introduces no real spacecraft numerical value.

#### V5.2C2 served-power heat routing

For each electrical load component k, retained internal heat is modeled as:

`P_heat,k = P_served,k * f_heat,k`

with `0 <= f_heat,k <= 1`. Served component power must be supplied explicitly;
C2 does not infer component service from aggregate unmet power. The retained
heat fraction is a reduced-order routing parameter describing the share of
served electrical power that remains inside the modeled thermal network. Its
complement is not assigned one specific physical destination by C2.

Every `thermal.routing.<component>.retained-heat-fraction` value requires
literature, derivation, or documented explicit-assumption provenance.
Sensitivity ranges are required wherever a retained-heat fraction materially
affects conclusions. C2 freezes no real spacecraft fraction or power value.

Battery conversion heat remains separate V5.2C1 bookkeeping and is not an
eighth routed subsystem-load component. C2 adds no detailed RF, motor,
propulsion, payload, heater-control, or temperature-dependent efficiency
model.

#### V5.2E1 transactional engine coupling

The engine supplies the same `dt_seconds` to the existing EPS transition and
thermal coupling APIs. Battery conversion loss from the current EPS interval
therefore enters the current thermal interval exactly once, while the thermal
proposal evaluates every node from start-of-interval temperatures.

E1 introduces no same-step thermal-to-EPS feedback. Explicit per-node heat
source inputs remain the caller's responsibility, including any upstream C2
served-power routing. E1 itself introduced no degradation evolution; D2B2 now
consumes the existing coupled proposal without changing its EPS or thermal
equations or numerical spacecraft parameters.

#### V5.2D2B2 representative battery temperature

The degradation interval uses the configured battery thermal role, identified
by `ThermalNodeId`, and the endpoint arithmetic mean
`T_rep = T_start + (T_end - T_start) / 2`. This is a Level-1 trapezoidal
representative-temperature approximation. It does not assert that temperature
varied linearly within the interval and remains subject to timestep and
convergence study. The current thermal endpoint does not feed back into the
current EPS proposal.

#### V5.2F2 numerical release audit

F2 applies fixed-physical-time timestep refinement to the completed coupled
V5.2 chain and compares the explicit-Euler thermal solver with an independent
two-node conduction solution. This is numerical verification, not physical
calibration, and it establishes no universal timestep or convergence order.

Explicit Euler remains a transparent Level-1 solver choice. F2 adds no new
source or value and changes no physical relationship. V5.8 retains ownership
of broader numerical methodology, timestep selection, and convergence gates.

#### V5.2D2A battery conversion-heat limitation

V5.2C1 maps V5.1 battery conversion loss to battery-node heat as a Level-1
irreversible-loss heat proxy.
It is not a complete Li-ion battery heat-generation model. Detailed battery
thermal physics may also include
reversible entropic heat, whose sign and magnitude can depend on chemistry,
SOC, current direction, and temperature, in addition to irreversible ohmic
and overpotential heat. That electrothermal treatment is deferred to the
post-V5.6 thermal-deepening gate unless earlier sensitivity evidence requires
it. D2A does not modify C1 physics.

#### V5.3E2 acquisition single-interval thermal composition

V5.3E2 adds no new physical source or value. It requires an explicit complete
component-level `ServedPowerLedger`; it derives no allocation from E1 service
bounds, status, or aggregate served and unmet power. Because E1 combines
acquisition and background payload demand, served `PAYLOAD` is total served
payload power and is not necessarily exact served acquisition power.

E2 reuses the V5.2 relationship
`P_heat,k = P_served,k * f_heat,k` through the existing explicit routing
configuration and its unchanged provenance, unit, and range contracts. Routed
internal heat replaces supplied internal-dissipation placeholders rather than
being added to them, while absorbed solar, albedo, and Earth-IR heat are
preserved. The existing EPS/thermal coupling remains the sole owner of adding
battery conversion-loss heat exactly once.

The exact E1 EPS interval duration, already equal to acquisition duration, is
also the E2 thermal interval; E2 exposes no independent timestep, including no
independent thermal dt, and no substeps.
The result is one explicit-Euler interval proposal, not evidence of numerical
adequacy, convergence, stability, continuous-time exactness, or operational
thermal feasibility. Operating and survival ranges remain metadata rather than
new imaging flight rules, and V5.8 retains numerical-methodology ownership.

E2 mutates no authoritative state and does not commit thermal evolution or
change the nested acquisition result. F remains the owner of transaction,
commit, rollback, and runtime integration.

#### V5.3F2 conditional current-step thermal proposal

V5.3F2 adds no new physical source or value. Only after exact electrical
authorization does it compute E2 exactly once using the active context thermal
state and thermal network together with the explicit routing, boundary, and
external-heat inputs. The E2 duration remains the acquisition duration and
configured timestep; F2 introduces no independent thermal timestep or substep.

Numerically valid E2 output remains a transient proposal. Operating and
survival ranges do not add an authorization classification, and F2 performs no
thermal-state mutation or engine commit.

#### V5.3F3A thermal transaction refactor

V5.3F3A adds no new physical source or value and changes no physical or
numerical equation. Generic thermal coupling, heat-source, interval, and
explicit-Euler semantics remain unchanged; the refactor only routes their
existing result through the one private transaction kernel and unchanged
degradation/reconciliation tail.

#### V5.3F3B authorized imaging thermal transaction

V5.3F3B adds no new physical source or value, introduces no new equation, and
adds no new literature. Authorized imaging reuses the exact
F2 E2 thermal-coupling proposal without a second generic EPS or thermal
calculation, then invokes the shared degradation/reconciliation tail once.
Supported nonauthorization produces no thermal-state or other physical commit.

Thermal operating and survival ranges remain reportable metadata rather than a
new imaging flight rule. A numerically valid positive endpoint outside those
ranges retains the existing transaction semantics.

Status:
TO RESEARCH

---

### S005 — EO payload and imaging literature

Purpose:
Support relationships among:
- resolution
- swath / scene dimensions
- imaging duration
- payload power
- data volume
- panchromatic vs multispectral operation

#### V5.3A KazEOSat-1 public payload evidence

Airbus Defence and Space, *KazEOSat-1 Technical and Product Ordering
Description Sheet*, April 2019, is recorded as PUBLIC SPECIFICATION evidence.
It describes a nominal 20 km strip swath, strip lengths from 20 to 2000 km,
and area and stereo acquisition modes. It reports 1 m panchromatic resolution,
four 4 m multispectral bands, acquisition of all five bands simultaneously,
and a 12 bits/pixel acquisition dynamic range.

V5.3A records these semantics without implementing acquisition modes, imaging
duration, payload power, or data-volume physics. In particular, the
simultaneous five-band statement must be resolved in V5.3B before existing
PAN/MS product labels are interpreted as independent physical acquisitions.

#### V5.3B1 optical acquisition configuration evidence

The April 2019 Airbus mission-specific sheet identifies the NAOMI optical
instrument, one PAN and four MS bands always acquired simultaneously, 1 m PAN
and 4 m MS spatial resolution, a 20 km nadir swath, 12 bits/sample acquisition,
and 20-2000 km strip lengths. Its 270 Mbit/s X-band instrument telemetry link
is not a detector data-generation rate. A delivered 16-bit GeoTIFF container
likewise does not replace the documented onboard acquisition bit depth.

The WMO OSCAR NAOMI (KazEOSat) instrument record provides a 90 W instrument
power candidate. B1 treats that as a LITERATURE VALUE requiring verification,
not as a 180 W model and not as evidence for separate 90 W imaging and 90 W
thermal-control loads. Acquisition power represents requested payload
electrical power only; C2 served-power routing remains the owner of any later
retained-heat fraction.

The official GISTDA THEOS-2 NAOMI guide provides heritage evidence for one
camera with multiple focal-plane retinas, PAN and four MS channels,
simultaneous acquisition, 12-bit digitization, compression capability, and
pointing-dependent effective swath and along-track sampling. It does not
establish the exact KazEOSat detector assembly, line rate, compression ratio,
or off-nadir sampling law.

The mission-specific Airbus 20 km nadir swath takes priority for a future
KazEOSat-like reference over generic WMO addressable-swath wording. Published
1 m and 4 m resolution may be used only as a DERIVED LEVEL-1 reference sample
spacing proxy, not exact detector pitch, raw GSD, or off-nadir sampling. B1
freezes no compression algorithm, compression ratio, packet/file overhead, or
stored-data reduction factor.

#### V5.3B2 derived optical acquisition relationships

B2 applies the following DERIVED LEVEL-1 relationships to an explicitly
supplied effective footprint and duration:

`A = W_eff * L_eff`

`N_pan = A / s_pan^2`

`N_ms,per-band = A / s_ms^2`

`N_ms,total = n_ms * N_ms,per-band`

`N_total = N_pan,acquired + N_ms,total,acquired`

`D_uncompressed,bits = b * N_total`

`D_uncompressed,bytes = D_uncompressed,bits / 8`

`E_requested = P_requested * t / 3600`

The physical channel selection determines which sample-grid terms contribute.
Counts remain continuous and unrounded. Data excludes compression, telemetry
framing, packet and file overhead, and container-width conversion. Energy is
requested payload electrical energy only, not proof of EPS service and not a
thermal-heat input. Effective width is not clipped to reference nadir swath,
and duration is not converted into length by an orbit or ground-speed law.

For the KazEOSat-like arithmetic check, a 20 km by 20 km simultaneous PAN plus
four-MS-band footprint with 1 m and 4 m reference spacings and 12 bits/sample
gives 6,000,000,000 bits: 15 Mbit/km^2 and 750 MB in decimal units. This is a
DERIVED LEVEL-1 SAMPLE-GRID PROXY, not a measured onboard data volume or file
size. B2 adds no new literature source or adopted spacecraft parameter.

Agile Earth-observation scheduling literature commonly treats mission target
requests as having candidate observation opportunities or windows from which
a feasible schedule is selected. V5.3A adopts only that explicit input
abstraction. It introduces no optimization algorithm, scheduling heuristic,
or literature numerical parameter.

#### V5.3D observation-acquisition composition

V5.3D adds no new physical source or value. It requires exact identity between
the observation-opportunity imaging duration used by C3 and the acquisition
input duration used by B2. Effective cross-track width and along-track length
remain explicit caller-supplied inputs; D derives neither from observation or
orbit geometry and does not treat reference nadir swath as a feasibility cap.

Within this composition, C3 sequence feasibility must succeed before B2 is
evaluated. The B2 result is computed internally from the active optical
configuration and candidate acquisition input. Its Level-1 sample-grid proxy,
uncompressed data, requested payload electrical power, and requested energy
semantics remain unchanged. No compression or 270 Mbit/s acquisition-generation
relationship is introduced, and the result does not claim EPS service, storage
capacity, or thermal conversion.

V5.3E1 retains this full-request acquisition and sample-grid description while
adding allocation-free EPS service bounds; it does not reinterpret bounded
electrical service as partial image or data production.

V5.3E2 preserves the same acquisition samples, bits, bytes, and requested-energy
semantics; its thermal proposal adds no partial-image, storage, or downlink law.

#### V5.3F1 scheduled acquisition execution contracts

V5.3F1 adds no new physical source or value.
`ScheduledObservationAcquisitionExecution` preserves one existing acquisition
candidate and an exact nonnegative integer scheduled start, while it reuses
`ScheduledObservationExecution` for observation-window legality. The nested
`ImagingRequestId` and `ObservationOpportunityId` remain distinct from
`MissionRequestId`; no new execution identity or implicit mission-request
bridge is introduced. A conceptual `MissionImagingRequestBinding` remains
deferred to V5.7.

F1 is context-independent. It establishes neither equality to a current
engine-step boundary nor acquisition-duration/configured-timestep compatibility,
and it makes no sequence, resource-service, thermal, engine-commit,
mission-completion, product, or storage claim. It adds no new persistent state
or checkpoint field.

#### V5.3F2 current-step imaging authorization

V5.3F2 adds no new physical source or value, and no new literature is
introduced. It requires the selected start to equal the active context's
current engine-step boundary and acquisition duration to equal the configured
timestep exactly. There is no duty-cycle conversion, no averaging or energy
rescaling, and no implicit substep.

F2 computes E1 internally exactly once. For a D-feasible result it also requires
the selected start to be no earlier than the exact C3
`candidate_next_start_seconds`, with no rounding of fractional readiness.
Supported sequence infeasibility and electrical shortfall remain explicit
non-authorization results; only exact full service and zero unmet load reach an
internally computed E2 proposal.

F2 preserves F1's nested imaging and opportunity identities, creates no
MissionRequestId conversion and no mission-request bridge, and does not scale
or store the requested image. `AUTHORIZED` is transient prerequisite evidence,
not an engine commit, mission completion, or product success. F2 performs no
degradation evolution and adds no persistent or checkpoint state.

#### V5.3F3A imaging-free engine seam

V5.3F3A adds no new physical source or value, changes no physical or numerical
equation, and introduces no new literature. It adds one private engine
transaction kernel and physical-handler seam only: there is no imaging
execution, imaging import, imaging API, product state, or persistent state yet,
and checkpoint schema 3 remains unchanged.

#### V5.3F3B resource-served imaging interval commit

V5.3F3B adds no new physical source or value, introduces no new equation, and
adds no new literature. It runs F2 on the restored working context,
reuses the exact F2 E1/E2 proposals, and commits the existing physical/runtime
domains only after the shared degradation/reconciliation tail and transaction
validation succeed. Supported nonauthorization means no physical commit.

A successful result means a resource-served imaging interval was committed; it
does not mean mission completion, request completion, product creation, storage
success, downlink, or delivery. The nested B2 samples, bits, and bytes remain
acquisition-equivalent Level-1 sample-grid quantities associated with that
interval and are not scaled or reinterpreted as stored or delivered data.

F3B adds no variable-duration averaging, partial step, substep, duty cycle, or
event splitting. Imaging-attempt evidence remains transient, replay requires
the caller to resupply its inputs, and checkpoint schema 3 remains unchanged.

#### V5.3F4A integrated imaging release demonstration

V5.3F4A adds no new physical source or value, introduces no new equation, and
adds no new literature. One deterministic executable example uses the reviewed
public V5.3 APIs and explicitly sourced model assumptions to demonstrate the
complete imaging chain. Independent equivalent start contexts demonstrate an
authorized resource-served interval commit, supported sequence infeasibility,
full-service impossibility, and service-allocation-required shortfall; each
nonauthorized case produces no physical commit.

The separate 20 km by 20 km simultaneous PAN-plus-four-MS-band reference check
gives 400,000,000 PAN samples, 25,000,000 samples per MS band, 100,000,000 MS
samples, 500,000,000 total samples, 6,000,000,000 bits, 750,000,000 decimal
bytes, and 15 Mbit/km². This remains a DERIVED LEVEL-1 SAMPLE-GRID PROXY, not a
measured onboard file size or stored, downlinked, or delivered data.

Direct, repeated, and checkpoint-restored runs require caller-resupplied
imaging inputs and demonstrate deterministic equality while checkpoint schema
remains 3. The demonstration adds no production state or physics, mission or
product completion, storage capacity, controller or scheduling policy, orbit
conversion, duty-cycle averaging, substep, or variable-duration behavior.

#### V5.3F4B release verification and freeze

V5.3F4B is verification and freeze evidence only. It introduces no new
literature or source and adopts no new physical value, equation, parameter, or
production behavior. In release-slice terms, it adds no new physical source or
value to the model. The mission-specific Airbus evidence and the separate WMO
instrument record retain their existing provenance and are not silently merged.
The audit newly transcribes non-adopted metadata from that already registered
WMO record; this is source verification, not a new production parameter.
Public Airbus and WMO provenance remains distinct: the Airbus 20 km nadir
swath, 1 m PAN, four 4 m MS bands, simultaneous acquisition, 12 bit/sample,
20–2000 km strip range, viewing envelope, and agility statement remain distinct
from the WMO NAOMI pushbroom description, its 7000 PAN and 1750 MS line-pixel
metadata, and its 90 W candidate. These WMO-specific values are not silently
combined with the Airbus mission-specific configuration. The published
270 Mbit/s value remains instrument telemetry, not a detector data-generation
law.

The audited 20 km by 20 km arithmetic remains a DERIVED LEVEL-1 SAMPLE-GRID
PROXY, not compressed, packetized, stored, downlinked, delivered, or product
data truth. S003's allocation-free EPS bounds, S004's explicit-Euler thermal
and explicit served-power routing limitations, and S006's boresight-only
configured maneuver envelope remain unchanged. Thermal integration remains
explicit Euler with the limited V5.2 numerical evidence; F4B makes no new
convergence claim. F4B adds no shortfall
allocation, thermal flight rule, mission completion, request-identity bridge,
storage or controller mutation, orbit-to-frame conversion, or variable-duration
integration. Checkpoint schema 3 and caller-resupplied imaging replay semantics
also remain unchanged.

Status:
TO RESEARCH

---

### S006 — ADCS / agile EO literature

Purpose:
Support:
- slew rates
- settling time
- pointing accuracy
- maximum off-nadir operation
- agility constraints

#### V5.3A KazEOSat-1 public viewing and agility evidence

The April 2019 Airbus description sheet records a 750 km sun-synchronous orbit,
98.56 degree inclination, and 100 minute period. It describes viewing up to
approximately 35 degrees using off-nadir/incidence wording in any direction,
and a pointing-agility anchor of a 60 degree slew in 90 seconds.

V5.3A does not hardcode the approximate viewing envelope into generic
observation geometry, equate spacecraft off-nadir angle with surface incidence,
or interpret 60 degrees in 90 seconds as a constant slew-rate law. The public
sheet does not by itself provide settling-time behavior or a complete slew law;
those capability models remain to be researched and configuration-owned.

#### V5.3C1 agile-ADCS configuration evidence and limits

The April 2019 Airbus mission sheet remains the mission-specific evidence for
viewing up to approximately 35 degrees and the 60 degree in 90 seconds agility
anchor. It provides neither a complete angle-to-time maneuver law nor a
post-slew settling value. C1 therefore treats the public maneuver statement as
one possible configuration anchor, not a constant rate or a source for
interpolation or extrapolation.

ECSS-E-ST-60-10C, *Space engineering — Control performance*, 15 November
2008, distinguishes absolute performance error
(APE), relative performance error (RPE), performance drift error (PDE), and
absolute knowledge error (AKE) when applied to pointing. ECSS-E-HB-60-10A,
*Space engineering — Control performance guidelines*, 14 December 2010,
separately defines performance error between actual and desired states and
knowledge error between estimated and actual states. These distinctions prevent
C1 from relabeling product location accuracy as ADCS pointing performance or
knowledge accuracy.

Chen, J.; Chen, M.; Wen, J.; He, L.; Liu, X. (2022), "A Heuristic
Construction Neural Network Method for the Time-Dependent Agile Earth
Observation Satellite Scheduling Problem," *Mathematics* 10(19), 3498, DOI
`10.3390/math10193498`, describes attitude transition as staged acceleration,
constant-speed motion, and deceleration, counts stabilization separately, and
uses a piecewise-linear transition-time approximation. This supports separate
settling ownership and an anchor-envelope abstraction, but its numerical law is
not adopted for KazEOSat or generic V5 use.

Kim, J.; Ahn, J. (2021), "Integrated Framework for Task Scheduling and
Attitude Control of Multiple Agile Satellites," *Journal of Aerospace
Information Systems* 18(8), 539-552, DOI `10.2514/1.I010910`, uses a quaternion
feedback attitude-control module to generate a transition-time database for
initial and final attitude pairs. This supports configuration data derived from
control analysis instead of a universal constant-rate assumption; C1 does not
adopt that paper's controller, quaternion model, or numerical results.

C1 is deliberately boresight-only. Angular separation requires both boresight
directions in one common frame, which later C2/V5.6 work must supply. C1 defines
no interpolation function, and later evaluation must reject separations beyond
the configured anchor envelope rather than extrapolate them.

#### V5.3C2 common-frame boresight geometry and transition timing

C2 requires both nonzero boresight vectors to carry the same explicit common
Cartesian comparison-frame identity. It normalizes their magnitudes only for
direction comparison and performs no frame conversion. The DERIVED
mathematical implementation evaluates angular separation as
`gamma = atan2(||u_start × u_end||, u_start · u_end)` and converts the result
to degrees. The `atan2` cross-and-dot form avoids inverse-cosine domain clipping
and introduces no tolerance-based angle repair.

C2 applies piecewise-linear interpolation only between the explicitly
configured C1 separation/time anchors. Exact anchor matches retain the exact
configured elapsed time, and separation beyond the final anchor fails with no
extrapolation. Configured settling remains separate and is added exactly once
after a nonzero slew; zero angular change has zero settling and transition
time. The maximum view angle is not used because the arbitrary common frame
contains no nadir or observation-feasibility meaning.

C2 adds no new physical source or spacecraft value. It introduces no
opportunity or orbit conversion, quaternion or actuator model, ADCS energy
relationship, or full attitude dynamics.

#### V5.3C3 observation and transition feasibility composition

C3 checks each opportunity's local view angle against the configured maximum
with `view_angle_from_nadir_deg <= maximum_view_angle_from_nadir_deg`. It keeps
that local-envelope check distinct from C2 common-frame maneuver separation.
The caller supplies each candidate's common-frame boresight; C3 performs no
opportunity-to-frame transformation.

For a scheduled previous acquisition, C3 applies the DERIVED LEVEL-1 temporal
relationships `t_previous,end = t_previous,start + duration_previous`,
`t_transition,ready = t_previous,end + t_transition,total`, and
`t_next,candidate = max(t_next,window-start, t_transition,ready)`. The next
acquisition fits when this candidate time is no later than window end minus its
imaging duration, with no rounding or timestep quantization.

Different-frame inputs remain invalid composition and propagate C2 failure.
Separation beyond the configured C2 anchor envelope remains unsupported timing
coverage rather than known physical infeasibility. C3 adds no new physical
source or value and no payload, resource, scheduler, controller, or engine
behavior.

#### V5.6D1b concrete MODEL_INERTIAL boresight binding

D313 adds a bounded adapter, with no new external physical source or spacecraft
coefficient. S006's existing common-frame/ADCS literature remains authoritative.
MODEL_INERTIAL is the already-adopted V5.6 model frame, not GCRS/J2000/ITRS.
The adapter calls D1a once and uses its C1 spacecraft_to_ground vector evidence
directly in the existing V5.3 CommonFrameBoresightDirection semantics. It
constructs the existing ObservationManeuverCandidate while retaining the complete
revalidated FrameDefinition and originating instantaneous D1a evidence.
Existing C1/B2 exact scalar-Unicode admission also validates all concrete frame
metadata before equality; it neither rewrites metadata nor restricts the
separately supplied legacy ADCS frame label.

The caller-owned ADCSBoresightFrameId is a label, not global physical-axis
identity. Equal actual label text does not imply equal concrete frames.
A future pairwise V5.6 bridge must compare hardened concrete frame bindings
before historical C2/C3 transition logic, whose bare V5.3 boresights carry only
frame IDs. This adapter evaluates no transition or sequence. It does not resolve
full attitude, roll, actuator dynamics, pointing accuracy, slew energy,
continuous tracking or operational ADCS adequacy. Those S006 limitations remain
open. The D1a S008 subsection and all earlier source text remain unchanged.

Status:
TO RESEARCH

#### V5.6D1c concrete-frame admission for pairwise C2 transition

D314 adds only a frame-evidence admission adapter around the existing S006 C2
transition literature/model; it introduces no new external physical source or
spacecraft coefficient. Two D1b snapshots are reconstructed and their complete
hardened MODEL_INERTIAL bindings must compare equal before C2. Equal labels
alone are insufficient, and different actual labels remain distinct bindings
even when their concrete frames agree. MODEL_INERTIAL remains the adopted V5.6
model frame, not GCRS/J2000/ITRS.

Only after that gate, temporary existing boresights share the previous binding's
exact caller-owned frame-ID object to satisfy historical C2's redundant label
comparison. Their components come directly from retained D1b evidence; no frame
transform, new identity or rewrite of retained labels occurs. Existing C2 owns
all normalization, angular separation, anchor interpolation and settling.
No new slew law, operational ADCS validation, full attitude or slew-energy model
is introduced. View/window/sequence feasibility, catalog uniqueness and
controller/engine integration remain deferred. These transient results add no
persistence or B2 content; schema 5 and B2 v1 are unchanged. Earlier S006 content,
including the D1b subsection, and all S008 content remain preserved.

#### V5.6D1d view-first orbit-derived C3 sequence/window composition

D315 leaves the historical S006 C3 view/transition/window model unchanged.
D1d changes only admission/composition around reconstructed orbit-derived D1b
evidence; it adds no external physical source or spacecraft coefficient.
The existing public view evaluator preclassifies both local views, preserving
previous-view then next-view failure precedence exactly. Such failures require
no transition and assert no pairwise concrete-frame compatibility.

Every transition-bearing path first requires D1c's hardened complete-frame
evidence. Temporary C3 inputs then share one original caller-owned frame ID,
without rewriting retained evidence. C3 still owns all sequence/window timing
and necessarily recomputes its C2 transition. D1d checks complete represented
transition consistency using actual anchor-ID text and exact scalar values.
This consistency check introduces no second physical law.

There is no new slew law, view law, scheduler law or operational ADCS validation.
MODEL_INERTIAL remains the adopted model frame, not GCRS/J2000/ITRS. Full attitude,
actuators, tracking and slew energy remain outside this bridge. No catalog,
selection, execution, controller/engine behavior or persistent state is added.
Schema 5 and B2 v1 remain unchanged; prior D1b/D1c S006 and D1a S008 text remains
preserved.

#### V5.6D1e ordered orbit-bound candidate admission

D316 introduces identity/admission composition only, with no new external
physical source or spacecraft coefficient. Supplied exact D1b candidates are
reconstructed through their existing owner before actual-text opportunity-ID
uniqueness is checked using temporary built-in text keys. Caller order and
original identities remain evidence; the legacy V5.3 collection behavior is
not rewritten. The new uniqueness/equality boundary avoids caller ID-text
comparison/hash/stringification hooks; unchanged nested owner admission retains
its existing operations.

D1b reconstruction still performs its D1a/C2c/B1/C1 composition. There is no new
slew, view or visibility law, pairwise feasibility, geographic conversion,
automatic generation, selection, scheduling or execution. Existing D1b/D1c/D1d
physical/source interpretations and earlier S006 text remain unchanged. Catalog
evidence is external/recomputed; schema 5, B2 v1 and S008 remain unchanged.

---

### S007 — Ground communications literature

Purpose:
Support reduced-order geometry-dependent communication capability and
realistic EO downlink ranges.

#### V5.5A contact-capacity evidence

Source record `s007-wmo-oscar-kazeosat-programme`, classified PUBLIC
SPECIFICATION, is the WMO OSCAR/Space KazEOSat programme record. It provides
independent institutional corroboration that KazEOSat data are downlinked in
X-band through the Kazcosmos receiving station in Astana. It does not provide
an independent numerical link-rate value.

Source record `s007-syzdykov-et-al-2023`, classified LITERATURE VALUE, is
Syzdykov et al. (2023), *Algorithm for finding maximum power point tracking
when shadowing or failure of solar panel photo cells on satellites using low
orbits*. Section 1, Figure 1, printed page 66 (PDF page 2) identifies S-band
and X-band communications, Mass Memory, DCU-X, QPSK Mod, TWT, and S-band
transponders in the KazEOSat-1 electrical architecture. Those architecture
labels do not establish net useful throughput, protocol efficiency, weather
loss, contact geometry, an RF link budget, or communications power.

V5.5A classifies `nominal contact capacity = nominal data-link rate ×
serviceable contact duration` as a DERIVED VALUE. Declaring a contact
serviceable is an EXPLICIT MODEL ASSUMPTION owned outside this calculation;
V5.5A derives no orbit, AOS/LOS, visibility, elevation, or station geometry.

The following remain TO RESEARCH: RF power, antenna gain and pattern, G/T,
coding/FEC, packet or file overhead, minimum elevation, atmospheric or rain
loss, effective measured throughput, operational pass duration,
communications power and heat, acknowledgement/retry behavior, multiple-record
allocation, and ground processing or storage.

Sources:

- WMO OSCAR/Space, *Satellite Programme: KazEOSat*.
- Syzdykov et al., *Algorithm for finding maximum power point tracking when
  shadowing or failure of solar panel photo cells on satellites using low
  orbits*, 2023, DOI `10.31489/2023No1/65-72` (Section 1, Figure 1, printed
  page 66, PDF page 2).

Status:
TO RESEARCH

#### V5.6C3b external serviceability bound to geometric support (2026-09-16)

No new external physical source or parameter is introduced. D311 adds a derived
consistency/binding rule between the existing externally declared V5.5
ServiceableGroundContact and one C3a geometry-only candidate (S008/D310).
The existing external-serviceability assumption remains authoritative;
geometry does not generate that declaration, contact identity or RF availability.
The preceding S007 RF/link-budget/availability and communications TO RESEARCH
items remain unresolved. The S008 C3a source record is unchanged.

Exactly one C3a composition supplies the geometric evidence. Typed station
identity and actual station text must agree; the unchanged integer contact
interval must fit inside exactly one source block, with equality allowed at
both edges. No clipping, union, adjacency merging or uncertainty-gap bridging
is permitted. No floating arithmetic or independent visibility calculation is
introduced. Sub-step integer contacts can have geometric support while failing
the unchanged engine's full-current-step alignment requirement.

Caller-supplied IDs and boundaries remain unchanged V5.5 evidence. Binding
equality uses actual external ID text to prevent legacy equality overloads from
erasing distinct contacts; the transient wrapper is explicitly unhashable.
It adds no RF closure, antenna/G/T/Eb/N0/FEC model, atmospheric/weather loss,
availability/booking, regulatory permission, power/heat, capacity, transmission,
acknowledgement or throughput claim. Existing consumers accept its nested
ordinary contact under their own requirements; C3b executes none of them.

Real hidden-pass/sub-step cases, independently enumerated small integer
intervals and explicitly synthetic gap/adjacency/ambiguity/huge-count seams
verify only this binding rule. Schema-5 JSON restart and independent coast-v1
decoding recompute equal same-runtime evidence with identical external inputs.
Station/search/serviceability inputs remain outside B2 content, with no new
persistent binding state, checkpoint keys, codec or physical law.

---

### S008 — Orbit and propulsion literature

Purpose:
Support:
- reduced orbital evolution
- J2 relevance
- stationkeeping
- maneuver delta-v bookkeeping
- propulsion capability ranges

Status:
TO RESEARCH

#### V5.6A verified TT, reference shape, and elementary frame groundwork

Access verified on 2026-09-13. This subsection resolves only the coordinate
and time groundwork below. The reduced orbital evolution, J2 relevance,
stationkeeping, maneuver delta-v, and propulsion ranges listed above remain
TO RESEARCH. No spacecraft orbit or station coordinates are adopted here.

| Record ID | Primary source and precise location | Verified content and V5.6A use |
|---|---|---|
| `nga-wgs84-defining-parameters` | [NGA WGS84](https://earth-info.nga.mil/?action=wgs84&dir=wgs84), World Geodetic System 1984 Reference System, **Defining Parameters** table | Equatorial radius `a = 6_378_137.0 m`; reciprocal flattening `1/f = 298.257223563`; nominal mean angular velocity `7292115 x 10^-11 rad/s = 7.292115e-5 rad/s`. The table's flattening row explicitly gives `1/f`. |
| `naif-georec-coordinate-definitions` | [JPL/NAIF georec_c](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/georec_c.html), **Detailed_Input**, **Detailed_Output**, **Particulars** | East longitude runs from +X toward +Y; geodetic latitude follows the reference-surface normal; altitude and equatorial radius use the same length units; `f = (re-rp)/re`. A selects metres and explicit ellipsoidal height. NAIF's unrestricted angular input is not A's canonical-range policy. |
| `naif-rotation-derivatives` | [JPL/NAIF Rotation Required Reading](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/rotation.html), **A word of warning**, **Constructing a coordinate axis rotation matrix**, **Differentiating rotations**, **State transformations**, **Time-dependent coordinate transformations** | Coordinate/passive and vector/active rotations have different signs. Differentiating a time-dependent component transform gives `R*v + Rdot*r`; rotating a velocity alone omits a term. A derives signs from its approved active matrix, not from `rotate_c`'s passive convention. |
| `naif-labelled-tt-dates` | [JPL/NAIF Time Required Reading](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/time.html), **Terrestrial Time (TT)**, **The Relationship between TT and TDB**, **In the Toolkit ET Means TDB**, **Julian Date**, **The abbreviation JD**, **Function to convert between uniform time scales** | TT, UTC and TDB labels matter; bare JD is ambiguous. The document identifies TT/TDT and JDTDT separately from TDB/ET. A uses a TT-specific type and the noon-based Julian-date convention; it implements none of SPICE's parsing or scale conversions. |
| `iers-earth-rotation-ut1` | [IERS: How is the CEO used?](https://www.iers.org/iers/en/service/faqs/theicrs/ceo-use), answer paragraph immediately below the title | Actual Earth Rotation Angle is proportional to UT1. A's constant-rate phase driven by elapsed TT seconds is an approximate model, not an ERA/UT1 or Earth-orientation implementation. |

Parameter classification and ownership:

- `orbit.earth.equatorial-radius` (m) and
  `orbit.rotation.angular-rate` (rad/s), from the named NGA factories:
  PUBLIC SPECIFICATION / VERIFIED. Verification is of conventional reference
  values, not spacecraft calibration or measured instantaneous Earth rate.
- `orbit.earth.flattening` (dimensionless): DERIVED VALUE / VERIFIED,
  `f = 1 / 298.257223563`, with the NGA source ID and reciprocal derivation
  carried by `ScalarParameter` / `ParameterProvenance`. Only `a` and `f`
  persist; polar radius and eccentricity are derived.
- Uniform positive-z rotation: EXPLICIT MODEL ASSUMPTION adopted by D303.
  The general rate is caller-supplied, signed, and may be zero. The named
  published rate does not make the constant-rate model exact. Initial phase
  is an explicit provenance-bearing caller parameter; the TT epoch is an
  explicit structural input. Neither is inferred from the date or system clock.
- Synthetic spheres, rates, phases, dates, locations, and states in the tests
  are verification inputs, not Earth/station/spacecraft measurements.

Equations are DERIVED from the adopted geodetic and active-axis conventions:
`e2=f*(2-f)`, `N=a/sqrt(1-e2*sin(phi)^2)`, and
`rF=((N+h)*cos(phi)*cos(lambda), (N+h)*cos(phi)*sin(lambda),
(N*(1-e2)+h)*sin(phi))`. The outward reference normal is
`(cos(phi)*cos(lambda), cos(phi)*sin(lambda), sin(phi))`; it is generally not
the normalized geocentric position. For stable evaluation A uses
`q=(1-f)^2` and `sqrt(cos(phi)^2+q*sin(phi)^2)` via `hypot`.

The active matrix is `Rz(theta)=((c,-s,0),(s,c,0),(0,0,1))` with
`theta=theta0+omega*t`. Therefore `rI=R*rF`, `rF=R.T*rI`,
`vI=R*vF+Omega cross rI`, and `vF=R.T*(vI-Omega cross rI)`.
Differentiating this matrix establishes the positive forward cross term.
These model frames are not GCRS/ITRS, a particular ITRF realization, TEME,
or SPICE J2000. WGS84 shape does not supply gravity, J2, or full orientation.

Numerical domain choices are explicit implementation limits, not sourced
physical laws: `abs(JD integer)<=2**31-1`, `abs(elapsed)<=2**40 s`,
`abs(omega*t)<=2**20 rad`, and `(1-f)^2>=2**-40` with finite positive derived
radii. The inward normal-coordinate domain is `h > -a*(1-f)^2`;
`a*(1-f)^2` is the minimum meridional curvature radius (at the equator),
derived from `M=a*q/(cos(phi)^2+q*sin(phi)^2)^(3/2)`. This permits negative
ellipsoidal heights while excluding folds and degeneracy. It is not a NAIF
height restriction or a station-height policy.

Independent verification uses 90-digit stdlib Decimal support-function
geometry: for `Q=diag(a^2,a^2,b^2)`, surface point
`s=Q*n/sqrt(n.T*Q*n)`, then `r=s+h*n`. This follows from the ellipsoid
constraint and gradient parallel to `n`, independently of the implemented
prime-vertical-radius evaluation. Binary input values are converted exactly
with `Decimal.from_float`; Taylor sine/cosine terms stop below `1e-85`.
Fixtures use WGS84, latitude `0.731 rad`, longitude `-1.117 rad`, and heights
`1234.5 m` / `-350.25 m`. A separate Decimal100 complex-derivative reference
uses `zI=exp(i*theta)*zF`, `zI'=exp(i*theta)*(vF+i*omega*zF)`, true pi from
Machin's formula, and times `12345.6789 s` / `1000000000.125 s`.

Reference fixtures and a reproducible support-function generator live in
`tests/test_v56a_frame_transforms.py`. Short-time Earth-scale budgets are
`2e-8 m`, `3e-12 m/s`, and `2e-15` dimensionless, based on binary64 operation
count and reference precision. With `u=2^-53`, long-time tests add a phase
budget `8*u*(abs(theta0)+abs(omega*t)+1) rad` times the relevant position or
velocity scale, accounting for product/addition and binary-tau reduction.
All approximate checks disable default relative tolerance. Extreme accepted
ellipsoids require shape/scale-dependent error assessment; these numerical
budgets are not real-world orbit, contact, or Earth-orientation accuracy.

#### V5.6B1 verified central-force foundation and independent coast references

Access verified on 2026-09-14. D304 adopts only bounded standalone coast
evaluation. The S008 family remains TO RESEARCH for broader fidelity, J2
relevance, maneuvers, stationkeeping, propulsion and long-horizon adequacy.
The preceding A subsection is historical evidence of A's narrower boundary.

| Record / reference | Primary location verified | B1 use and limitation |
|---|---|---|
| R1, existing `nga-wgs84-defining-parameters` | [NGA WGS84](https://earth-info.nga.mil/?action=wgs84&dir=wgs84), **World Geodetic System 1984 Reference System → Defining Parameters**, geocentric gravitational-constant row and immediately following `**` footnote | General geocentric GM, including atmospheric mass, is `3.986004418e14 m^3/s^2`. The separate GPS-user footnote value `3.9860050e14` is not adopted. `orbit.gravity.gravitational-parameter`, units `m^3/s^2`, is PUBLIC_SPECIFICATION / VERIFIED only for the named conventional factory value. |
| R2, `naif-cartesian-two-body` | [JPL/NAIF prop2b_c](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/prop2b_c.html), **Detailed_Input / Detailed_Output**; **Exceptions** 1–5; **Particulars**; **Examples** 1 and 2; **Restrictions** 1 | Supports initial Cartesian state plus central GM and relative duration, consistent units, universal-variable approach, and explicit degeneracy/arithmetic checks. Examples discuss circular motion and element conditioning near a parabola. B1 independently implements a restricted elliptic solver; it inherits neither SPICE robustness nor its full conic domain. No example GM/radius/orbit is adopted and no SPICE installation is required. |
| R3, `esa-two-body-kepler` | [ESA Navipedia, Two-body Problem](https://gssc.esa.int/navipedia/index.php/Two-body_Problem), J. Sanz Subirana, J. M. Juan Zornoza and M. Hernandez-Pajares (2011), **equation (1)**, elliptic-motion definitions including circular degeneracy, **equation (3)** | Central-force ODE and elliptic `M=n*(t-T0)=E-e*sin(E)`, `n=sqrt(mu/a_orbit^3)` support the adopted model and independent reference. They do not establish real-spacecraft orbit accuracy. |

Classification separates the published mu above from DERIVED_VALUE orbital
relations below. Central force/no perturbations and the exterior-sphere rule
are EXPLICIT MODEL ASSUMPTIONS adopted in D304; conditioning limits and solver
tolerances are numerical implementation choices. All initial states, orbital
elements used to construct test inputs, and synthetic mu/shape/rotation values
are synthetic verification assumptions, not KazEOSat calibration. General
trajectories receive their initial state and provenance-bearing mu explicitly.

Derived universal-variable equations (R2 does not print these equations):
with `alpha=2/R0-|v0|^2/mu`, introduce `dchi/dt=sqrt(mu)/R`. Energy conservation
gives `d2R/dchi2=1-alpha*R`, with initial `R0` and
`dR/dchi=(r0 dot v0)/sqrt(mu)=sigma`. Solving that linear radius equation and
integrating `dt/dchi=R/sqrt(mu)` gives
`sqrt(mu)*dt=R0*chi+sigma*chi^2*C+(1-alpha*R0)*chi^3*S`,
where `z=alpha*chi^2`, `C=(1-cos(sqrt(z)))/z`,
`S=(sqrt(z)-sin(sqrt(z)))/z^(3/2)`, with limits `1/2` and `1/6`.
The dimensional residual F is the right side minus `sqrt(mu)*dt`.

Lagrange reconstruction is `r=fL*r0+gL*v0`,
`fL=1-chi^2*C/R0`, `gL=dt-chi^3*S/sqrt(mu)`. Differentiating with
`chi_dot=sqrt(mu)/R` yields
`fdotL=sqrt(mu)*(alpha*chi^3*S-chi)/(R*R0)`,
`gdotL=1-chi^2*C/R`, and `v=fdotL*r0+gdotL*v0`; these obey the central-force
equation and initial r/v conditions. fL and gdotL are dimensionless, gL is
seconds, fdotL is inverse seconds. Earth flattening is a separate quantity.

Implementation scales `V=sqrt(mu/R0)`, `T=R0/V`, `u=v0/V`,
`beta=alpha*R0=2-u dot u`, `b=(rhat dot u)*sqrt(beta)`, `k=1-beta`,
`q=sqrt(alpha)*chi`, `n=beta^(3/2)/T`. The root becomes
`H=beta*q+b*(1-cos(q))+k*(q-sin(q))-n*dt`, and `F/sqrt(mu)=H/n` seconds.
Its derivative is `alpha*R=1+b*sin(q)-k*cos(q)>0`, bounded by `1+-e`,
`e=hypot(k,b)`. Integrating those derivative bounds from zero provides one
analytic bracket; `q=n*dt-b+b*cos(q)+k*sin(q)` provides another with amplitude
e. Their intersection, rounded outward, safeguards bounded Newton/bisection.
`n*gL=b*(1-cos(q))+beta*sin(q)-H` retains the signed residual while avoiding
whole-period cancellation. Small-z C/S use 18 bounded Taylor terms; at z<=1,
the truncation remainder is below `1/38!`. Larger z uses a half-angle C and
well-conditioned S. There is one solver/reconstruction path, no element route.

Admitted numerical domain: `e<=1-2^-8`; `R0,V,T` in `[2^-128,2^128]` in SI;
finite supported derived quantities; signed `abs(dt)<=2^40 s` and
`abs(dt/period)<=2^20`. Pericentre `rp=p/(1+e)`,
`p=R0*|rhat cross u|^2`, must clear the equatorial-radius sphere. Numerical
ambiguity within `64*u_machine*rp/(1-e)` rejects, with no physical altitude
margin. This is conservative reference-ellipsoid clearance, not terrain,
atmosphere, an operational altitude rule, collision detection or an exact
ellipsoid-intersection calculation. Not every finite ellipse/time is supported.

Acceptance requires `abs(H/n)+roundoff_seconds<=time_tolerance_seconds`.
The working H-evaluation allowance is `64*u_machine*sum(abs(terms))+8*ulp(H)`;
terms are scaled to the actual reduced duration so tiny queries are not rejected
by a fixed epsilon-period floor. Bracket width/equal iterates never substitute
for residual acceptance. Ambiguous residual signs are not used to update a
bracket. Unresolved accuracy, stagnation and exhausted work raise explicit
errors. The allowance assumes ordinary binary64/libm accuracy, not certified
interval arithmetic or proof of mathematical unattainability.

Period reduction uses exact rational subtraction of the rounded binary period,
then one rounding, consistently in the solver/reconstruction. The requested
instant is retained. A separate phase-time budget is
`64*u_machine*abs(dt)/(1-e)` plus reduction roundoff, including period error
times revolution count and sensitivity of n to rounded initial invariants.
Norm/division/sqrt/scaling receive about 8u; the three squared velocity terms
give about 16u absolute beta allowance. Since beta>=1-e, n's relative error
allowance is below `32u/(1-e)`; 64u leaves room for tau/period/reduction.
This root residual is not a global endpoint or mission-accuracy guarantee.

Independent verification in `tests/test_v56b1_two_body_propagation.py` uses
exact-binary analytic circles and 90-digit Decimal elliptic Kepler solutions,
with reproducible Machin pi and bounded sine/cosine/atan series. The reference
rederives a/e/ellipse axes from `Decimal.from_float(r0,v0,mu)` before solving
equation (3); it never compares different rounded initial orbits. A 110-digit
recomputation differs by less than `1e-60` in the tested SI outputs. Synthetic
rotated, nonzero-radial-velocity, near-circular and eccentric cases reach
`e=1-2^-8-1e-12`, with signed, nonzero-initial-time and billion-second queries.

Independent source review reproduced incomplete residual-to-endpoint accounting
in the original B1 verification. Its `vmax*eta` / `amax*eta` root conversions
did not bound all tested residual-retaining reconstructions. This pre-commit
correction changes numerical evidence/documentation, not the executable coast
propagator, its acceptance rule, the central-force model or B2 scope.

For coherent exact coefficients, let `delta=t(q)-t`, `eta>=abs(delta)`,
`V0=|v0|`, `rp=pericentre`, with orbit-wide speed/acceleration bounds vmax/amax.
The implemented `-H` in g gives `r_hat=r_star(t+delta)-v0*delta`. Both velocity
coefficient changes have the reconstructed radius in their denominator, so
`v_hat-v0=(R_star/R_hat)*(v_star(t+delta)-v0)`.
Thus `E_r_root<=(vmax+V0)*eta`. Since `abs(R_hat-R_star)<=V0*eta`,
`R_hat>=D=rp-V0*eta`; when D>0,
`E_v_root<=amax*eta+V0*eta*(vmax+V0)/D`.
For D<=0 this argument establishes no finite velocity bound; it becomes loose
as D approaches zero. Circular half-period position error tends to `2V*abs(delta)`
and quarter-period velocity error to `sqrt(2)*A*abs(delta)`, independently
showing why a pure time-shift conversion was insufficient.

Endpoint budgets remain explicit absolute norms in m and m/s, relative
tolerance zero. The configured eta already includes the accepted root residual
and its evaluation allowance; that allowance is not added twice. Phase uses
the separate previously defined phi: `vmax*phi`, `amax*phi`. Rounded coefficients
need not describe one coherent exact orbit; their working reconstruction terms
remain `256u/(1-e)*(a_orbit+vmax/n)` and
`256u/(1-e)*(vmax+amax/n)`. The 256u reserves four 64u operation groups for
coefficients, Stumpff/trigonometry, vector reconstruction, and norm/derivatives.
Independent-reference uncertainty remains a separate `1e-60` contribution;
90/110-digit checks now also cover pericentre and initial-speed metadata.
Budget arithmetic uses Decimal and rounds final binary64 totals outward.

The full working budget additionally requires `V0*eta/rp<=2^-10`, giving
`rp/D<=1024/1023`, and reconstruction position allowance below D/2. This
predeclared verification conditioning guard does not change production
acceptance or select sweep outcomes, and is not proof of the existing 256u
policy for arbitrary tolerances. Root-only bounds apply for any D>0; the
complete floating-point working budget claims only its documented domain.

The unchanged seeded 5601 sweep covers 64 states with
`e in (1e-7,.99)`, pericentre `[6.5e6,2e7] m`, and signed queries up to `1e9 s`.
At root tolerance `1e-6 s`, observed maxima are `0.004460515164542437 m` and
`1.825927294311695e-6 m/s`. Its historical OLD-budget ratios were 0.550 and
0.229; corrected-budget ratios are 0.277092 and 0.069703. Outputs did not
become more accurate: these are the same production errors under a corrected
definition of the budget.

The exact-binary review regressions reproduce position error
`0.011131649812549438 m` against old `0.007546607453548639 m` (case P), and
velocity error `1.6352014703355476e-7 m/s` against old
`1.1154954121566455e-7 m/s` (case V). Their corrected respective budgets are
`0.015092660743656183 m` and `3.221037661167249e-7 m/s`. These decimals are
runtime observations, not cross-platform golden values. Separate component
assertions, signed material-residual cases and Decimal circular reconstruction
identities preserve the evidence without changing inputs or root tolerances.

The prescribed supplementary seed-20260914, 1000-case sweep draws e, rp, E0,
duration and tolerance in that order, with `e in [1e-6,.9959]`,
`rp in [6.5e6,2e7] m`, duration within +/-1.5 nominal periods and tolerances
from `10^-9` to `10^-3 s`. Actual results: 989 accepted queries, 11 explicit
unresolved-accuracy rejections, six accepted states exceeding an OLD budget,
and 79 accepted residuals at least one quarter of their tolerance. All accepted
states satisfy corrected budgets; rejections are not endpoint successes.
Measured maxima are `3.284896090361144 m` and `0.003625595933950055 m/s`,
with corrected-budget ratios 0.776389 and 0.648982. Maximum `V0*eta/rp` is
`7.57689192727244e-7`, well below the predeclared working-budget guard.
Only the specific production unresolved-accuracy error is counted; unexpected
exceptions remain failures. These observations concern synthetic tested cases,
not all admitted scales or physical fidelity. Energy, angular momentum and eccentricity-vector
checks supplement the independent endpoints. Short recovery/reanchoring uses
the central-force Jacobian and an explicitly scaled Gronwall error bound.

Corrected-candidate validation: 186 B1 tests, 124 unchanged A tests, 264 H plus
V5.5 A-F tests, and one full suite of 3326 passed in 179.98 seconds, all exit 0
with no skips or xfails. The earlier 3309-test B1 full run is pre-correction
evidence. Two intentional original-budget failures preserve the independent
review finding; the corrected endpoint regressions pass without changing
production outputs or tolerance values.

#### V5.6C1 instantaneous ground-point geometry verification (2026-09-15)

C1 uses explicit point parameters with IDs
orbit.ground-point.geodetic-latitude (rad), orbit.ground-point.east-longitude
(rad), orbit.ground-point.ellipsoidal-height (m). Values and independent
provenance are caller inputs. Tests use EXPLICIT MODEL ASSUMPTION synthetic
coordinates, never inferred antenna/city locations or operational station data.
WGS84 shape continues to use the existing NGA source records; no new spacecraft
coefficient, gravity model, ephemeris or dependency is adopted.

Verified primary-source locations:

| Source record | Precise location | Supported content and boundary |
|---|---|---|
| R1, `esa-ecef-enu-coordinates` | [ESA Navipedia, Transformations between ECEF and ENU coordinates](https://gssc.esa.int/navipedia/index.php/Transformations_between_ECEF_and_ENU_coordinates), Sanz Subirana, Juan Zornoza, Hernandez-Pajares (2011), equation (4), equations (8)-(11), ellipsoidal-normal note immediately after (4) and below Figure 2; verified 2026-09-15 | ENU axes, receiver-to-spacecraft ray and elevation/azimuth projections; ellipsoidal up is normal rather than geocentric radial. C1 selects equivalent atan2 formulas and full quadrant/range handling; these are not quoted as the source's implementation. |
| R2, existing `naif-georec-coordinate-definitions` | [JPL/NAIF georec_c](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/georec_c.html), Detailed_Input and Particulars; rechecked 2026-09-15 | East longitude, normal-based latitude, height relative to the reference spheroid and body-fixed interpretation. A's canonical angle/inward-height domain remains its own bounded policy. C1 calls A rather than importing SPICE. |
| R3, existing `naif-rotation-derivatives` | [JPL/NAIF Rotation Required Reading](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/rotation.html), Rotation derivatives / Differentiating rotations / State transformations; rechecked 2026-09-15 | Differentiating pN=R*pI gives vN=R*vI+Rdot*pI. A's adopted active Rz signs determine the fixed-to-inertial specialization; C1 reuses it, including omega cross r for a stationary ground point. |

Explicit C1 derivations, not source-selected conventions:
rho_dot=unit(r_s-r_g) dot (v_s-v_g), positive separating; local z=-unit(r_s),
x follows transverse INERTIAL velocity, y=z cross x. Cross-product construction
is equivalent by the vector triple-product identity. Incidence uses normal/u
cross-and-dot atan2, separately from geocentric off-nadir. Ground azimuth runs
north-to-east; orbital azimuth runs x-to-y. At poles, longitude defines the
chosen meridian. None of these instantaneous quantities proves unobstructed
visibility, successful acquisition/receipt or service availability.

D306 and the module document finite-intermediate and zero/unresolved geometry
rejections, separation >64 position ulps, cross-norm >64u, u=2^-53, and the
two azimuth projection floors 64u and 64u*(1+1/k). Product/normalization
underflow or rounded nonzero cancellation cannot masquerade as exact alignment.
These working resolution policies preserve the ray and distinguish exact
represented-vector zero from unresolved nonzero projection. They do not bound
A phase/geodesy, a caller's B1 endpoint error or physical model uncertainty.
At the half-open azimuth endpoint, nextafter(tau,0) handles rounding to tau
with <=one ulp coordinate change; no direction is quantized.

Independent oracle: Decimal90 and Decimal110 exact binary inputs; support
surface Q*n/sqrt(n.T*Q*n), complex rotation using Machin pi/Taylor trig, and
direct transverse projection. Reference agreement is <1e-60 in all tested
quantities. SI/dimensionless absolute errors use separate A geodesy and phase
allowances, normalized-ray perturbation bounds, 1/k basis conditioning and
1/P azimuth conditioning. The phase term grows as
8u*(abs(theta0)+abs(omega*t)+1), subject to A's accumulated-phase envelope.
Finite-difference refinement also checks the analytically bounded third
range derivative and central-difference truncation plus roundoff.

Synthetic off-axis WGS84 verification uses phi=.731 rad, lambda=-1.117 rad,
h=1234.5 m, theta0=.271 rad, omega=7.292115e-5 rad/s and supplied Cartesian
r=(7200000,1300000,2500000) m, v=(-1400,6800,1800) m/s.
At t=12345.6789 s, observed range/range-rate errors are
6.381560981504528e-10 m / 1.6922360753498417e-12 m/s, against independently
scaled budgets 6.325951072625561e-8 m / 3.141067012892563e-10 m/s.
At t=1e9 s they are 1.4778741045995863e-5 m / 1.9908901564549466e-8 m/s,
against 4.1263148192606714e-4 m / 5.577829462778065e-7 m/s.
The corresponding ground-azimuth errors are 1.7358828033537523e-16 and
7.658967905778905e-12 rad; budgets 7.041678448721596e-14 and
3.0887183117045506e-10 rad. These are observed model-equation results under
this runtime, not operational accuracy or a universal admitted-domain claim.
Other per-quantity errors/budgets are printed by the two C1 reference tests.

Geographic content remains outside B2 manifest coverage and checkpoint state.
The same external point definition is required for repeatable geometry after
restart. C2 windows, content-bound catalogs and explicit legacy/service adapters
remain future contracts, without expanding current B2 identities.

#### V5.6C2a instantaneous ellipsoid and elevation gate (2026-09-15)

This bounded subsection verifies the source definitions used by C2a, not
temporal windows or physical station access. Geographic coordinates and
minimum elevation policies remain explicit provenance-bearing inputs outside
B2 manifest coverage. No station mask value, spacecraft coefficient,
ephemeris or new dependency is adopted.

| Source record | Verified primary location | Supported content and limit |
|---|---|---|
| R1, `naif-surfpt-aligned-ellipsoid-ray` | [JPL/NAIF surfpt_c](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/surfpt_c.html), Detailed_Input, Detailed_Output, Particulars; checked 2026-09-15 | Observer relative to the ellipsoid centre, aligned semi-axes and the first intersection of an emanating ray. The routine's ray contract does not implement this project's finite-segment, surface-endpoint or uncertainty semantics. No SPICE installation. |
| R2, existing `esa-ecef-enu-coordinates` | [ESA ENU transformations](https://gssc.esa.int/navipedia/index.php/Transformations_between_ECEF_and_ENU_coordinates), equation (4), normal note, equations (8)-(10); rechecked 2026-09-15 | Reference-surface normal, receiver-to-spacecraft direction and elevation projection. C1's selected atan2 convention is reused. No operational elevation threshold follows from this source. |
| Future C2b only, `naif-gf-temporal-search-limitations` | [JPL/NAIF Geometry Finder Required Reading](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/gf.html), Search step size, Binary state step size selection problems, Search convergence, Result windows are approximate; checked 2026-09-15 | Sampling can miss events/gaps; root-refinement and input/arithmetic errors leave approximate endpoints. This is future-search limitation evidence. C2a implements no finder and imports no SPICE time tolerance. |

Project derivations (D307), not claims about surfpt_c's implementation:
scale coordinates by (a,a,a*(1-f)); the finite segment gives
F(s)=A*s²+2*B*s+C with s in [0,1]. Convexity restricts the minimum to an
endpoint or -B/A. Exact rational arithmetic retains the original binary a/f
authority; a separately rounded polar radius is not a new body definition.
The oblate common-z body is invariant under the adopted Rz because x²+y²
and z are preserved. This does not extend to arbitrary triaxial orientations.

An authoritative negative ellipsoidal height is inside. At h=0, true C=0
and B=P0.P1-1 distinguishes outward contact from immediate entry; exact
tangent departure is boundary. At an exact spacecraft surface endpoint the
half derivative P1.(P1-P0) distinguishes exterior arrival from preceding
penetration. An elevated ground point requires the full segment minimum.
A clear below-horizontal ray may pass a negative explicit mask and fail
zero elevation, independently of occultation. No contact is inferred.

D307 declares f<=1/2, 2^-900<=a<=2^900 m and normalized coordinate/height
scale<=2^40. Its conditional 256u*(a+abs(h)) geodesy/rotation arithmetic
reserve is based on denominator conditioning and operation count, with
absolute sin/cos error<=2u assumed. A's accumulated-phase allowance is
separate. This is a working numerical policy, not certified libm intervals
or a bound on external B1/physical errors. Closest-segment distance is
1-Lipschitz in endpoint displacement; the squared-minimum allowance follows.
Elevation allowances include relative-position subtraction and ENU/atan2
conditioning. Ambiguous signs are UNRESOLVED, never repaired by clipping,
body inflation or silently loosened tolerances.

The exact geographic-axis predicate can use rational a+h and zero
occultation ground allowance while retaining C1's rounded point unchanged.
C1's position discrepancy still contributes to elevation uncertainty.
General rounded zeros and copied atan2 angles do not establish exact
boundaries. Binary +/-pi/2 masks are not symbolic equality certificates.

Independent evidence: exact hand/rational spheres and oblates, Decimal90/120
support-function geography plus complex rotation, cross-product line distance
and root-overlap checks; reference agreement <1e-60 dimensionless/rad.
The 120-query deterministic grid yields VISIBLE=34, NOT_VISIBLE=64,
BOUNDARY=0, UNRESOLVED=22; LOS CLEAR=54, BLOCKED=48, BOUNDARY=0,
UNRESOLVED=18. Maximum observed elevation error is
7.06119118522391e-11 rad (largest error/allowance ratio
0.006984961826766829); maximum selected-predicate error is
4.934046689353065e-13 dimensionless (largest ratio
0.0037027227166028793). These maxima need not occur in the same cases.
No cases were discarded. Separate exact hand cases establish boundaries.

The nonaxis rotated interior-grazing test at t=1e9 s gives nominal minimum
-5.123563695931523e-12, independent error 5.123548371721354e-12 and allowance
2.493447530226904e-10, all dimensionless: UNRESOLVED. Perturbing the independent
fixture's transverse component by +/-1e-6 resolves BLOCKED/CLEAR; these are
model-equation checks, not physical visibility or certified event times.
C2b temporal search, interval evidence, catalogs, generated contacts and
observation/service adapters remain subsequent explicitly bounded work.

#### V5.6C2b bounded adaptive temporal windows (2026-09-15)

The preceding C2a record is preserved historical scope. C2b now implements
bounded temporal model visibility; catalogs and service/observation adapters
remain deferred. Reverified the existing source ID
`naif-gf-temporal-search-limitations` at
[JPL/NAIF Geometry Finder Required Reading](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/gf.html):
Search step size; Binary state step size selection problems; Search convergence;
Result windows are approximate; Missed events. The source warns that state
sampling can miss short events/gaps and distinguishes time convergence from
function error and physical input accuracy. No CNVTOL value is adopted.
C2b is not SPICE GF and claims none of its implementation guarantees.

D308 derives this implementation's separate method: geometry_sample_seconds
only seeds a run-zero grid. Exact-input ellipse invariants bound apocentre and
speed; uniform rotation bounds ground motion. Strict whole-cell surface,
endpoint, finite-segment minimum and elevation variation enclosures certify
cells. Otherwise breadth-first refinement retains explicit unresolved evidence.
The derivations use B1's already reviewed two-body equations and corrected
residual-retaining position budget, plus C2a's geodesy/arithmetic policies;
no new external physical parameter or spacecraft coefficient is introduced.

Numerical details are explicit in D308: outward invariant square roots; exact
polar-axis arithmetic; actual larger edge reach of rounded midpoints; corrected
(vmax+V0)*eta anchor reserve with its conditioning restrictions; C1 range
construction reserve in the elevation denominator; and conservative extra
ground reserve for elevated segment minima. These are working binary64/libm
enclosures under the declared numerical policy, not formal intervals or real
ephemeris uncertainty. Unsupported envelopes raise rather than loosening bounds.

Only fully resolved adjacent VISIBLE cells form windows. Their endpoints are
cell boundaries, not event-root estimates. boundary_tolerance_seconds targets
unresolved-cell width, not physical timing or function-value accuracy. Budget
exhaustion preserves all time as uncertainty, including a compact untouched
seed-tail union; this may conservatively report incomplete width coverage.
Tests independently exercise circular hidden passes/gaps, singleton tangency,
refinement, signed/nonzero-epoch queries, scale changes, resource limits and
off-axis WGS84 orbit/geodesy at 90/120 Decimal digits. Oracle positions remain
high precision through geometry, with <1e-60 agreement in tested SI positions,
dimensionless predicates and radians. Returned certified cells are probed at
both endpoints, midpoint and independent interior fractions; event brackets
are required to remain inside unresolved coverage, not equal returned windows.

No serviceability, engine-step adapter, contacts/opportunities, atmospheric
refraction, terrain, RF, availability, weather, electrical feasibility or
physical AOS/LOS accuracy is established. B2 binding still excludes point and
policy; schema-5 restart recomputes with identical external inputs. No state,
codec expansion, persistent cache, J2, maneuver or broader propulsion model.

#### V5.6C2c conservative engine-grid projection (2026-09-15)

This subsection records derived temporal/discrete arithmetic, with no new
external physical source or parameter. Its owners are D040's half-open engine
intervals, B2's active NumericalConfig and the reviewed C2b certified windows.
The preceding C2b record remains historical scope; C2c now supplies projection
only, with service/observation adapters and engine integration still absent.

D309 derives exact inward integer indices for each certified window [a,b):
candidate starts are g+k*dt, k>=0, with start>=a and start+dt<=b. Exact Fraction
boundaries give k_first=max(0,ceil((max(a,g)-g)/dt)) and
k_last=floor((b-g-dt)/dt). Equality at either containment boundary is admitted.
No event roots, outward rounding, floating tolerance or independent visibility
predicate is used. Original C2b inputs compose exactly one search; its active
timestep and certified windows alone determine the projection.

At most one compact arithmetic-progression block represents each source window;
step counts and derived duration/end are exact Python integers. Synthetic large
windows test trillion-step counts algebraically without per-step allocation.
This bounds projection representation, not the separate C2b search workload.
Independent small-case enumeration and exact/adjacent-binary boundary fixtures
verify containment. [12,137), dt=60, first boundary 0 produces only [60,120).
The excluded 65 seconds carry no RF-capacity claim.

Unresolved/NOT_VISIBLE time never creates or bridges blocks.
all_search_cells_resolved examines C2b final statuses, independently of
complete_to_tolerance; no exhaustive operational-access claim follows.
Real C2b hidden-pass/gap composition, changed grid phase and schema-5 JSON
restart verify the integration boundary. Point/policy/search config/confinement/
origin remain external to B2 manifest content; no projection state is persisted.
No new physics, IDs, contacts/opportunities, serviceability, communications
capacity, engine execution or scheduling is supplied.

#### V5.6C3a geometric ground-station contact candidates (2026-09-15)

This bounded subsection records derived domain composition, with no new
external physical source, spacecraft coefficient or parameter. D310 composes
C1's complete station geographic/provenance evidence, C2a's visibility policy,
C2b's bounded certified windows, C2c's complete engine-grid projection and
existing typed GroundStationId semantics. The station must carry exact
GroundStationId; targets and invalid/subclass IDs are not station evidence.

One C2c call supplies the complete proof. Each compact source block becomes one
GeometricGroundContactBlock, retaining source order and exact timing/window
values through the existing nested constructor validation. The five timing
properties delegate to the source. No interval calculation, per-step allocation,
block merging, clipping or bridging is introduced. A 2^40-step source remains
one candidate; counts and the resolution flag copy C2c without a stronger
completeness claim. Full station content remains top-level equality evidence
even when station IDs or source timing alone coincide.

This geometric candidate is distinct from V5.5's externally supplied
ServiceableGroundContact. No GroundContactId is generated and no serviceable
contact, rate/capacity, RF availability, station booking/availability, weather,
electrical feasibility, delivery or controller claim is established. S007's
external serviceability assumption and RF/link/communications TO RESEARCH items
remain authoritative and unchanged. A future promotion requires an explicitly
approved serviceability and contact-identity contract.

Real hidden-pass/grid-phase and invisible cases verify owner composition.
Explicitly synthetic C2c seams verify gaps, adjacency, coincident timing and
compact huge counts without pretending to supply additional physical evidence.
Station/policy/search config/confinement/origin remain outside B2 version-1
manifest content; schema-5 JSON restart plus independent coast decoding
recomputes equal same-runtime evidence for identical external arguments.
No candidate state, codec, checkpoint key or physics changes. Observation
opportunities, engine integration, J2, maneuvers and wider fidelity remain open.

#### V5.6D1a one certified-step observation opportunity (2026-09-16)

D312 adds a bounded domain bridge with no new external physical source,
spacecraft coefficient or parameter. It composes the C1 orbital-basis convention
documented above, C2c complete-step certification and existing V5.3
ObservationPointing/ObservationOpportunity semantics. S005/S006 historical
records remain unchanged; S006 remains the source owner for later ADCS/
common-frame work. D1a resolves no full-attitude or ADCS literature question.

The target is complete GroundPointDefinition with exact GroundTargetId, explicit
ellipsoid, ellipsoidal height and coordinate provenance. There is no implicit
conversion from legacy degree-only GroundTarget. The external ImagingRequest
must match actual target ID content; ObservationOpportunityId remains caller
supplied. Base-string identity comparisons avoid legacy overloaded equality
without generating or rewriting external IDs.

One C2c composition certifies visibility; integer bounds/modulo select exactly
one represented full step in exactly one compact block. One additional B1/C1
snapshot at its exact start supplies off-nadir and local orbital x-to-y azimuth,
converted from radians to V5.3 degrees. Unresolved azimuth rejects; only exact
modeled nadir may use azimuth zero as a coordinate convention. Strict source
radian limits precede any <=1-ulp inward degree-endpoint representation
correction. No incidence/ground-azimuth substitution, physical clipping,
visibility recertification or per-step enumeration occurs.

The existing nested opportunity has [s,s+dt) window and dt duration, hence one
legal full-duration start. It does not assert continuous tracking or configured
view feasibility. No catalog, common-frame boresight, ADCS transition, scheduling,
mission binding, payload acquisition, resource service, storage/downlink or
engine execution follows. Synthetic analytic/local-basis tests and real C1
status cases verify this mapping; labeled compact-block/conversion seams test
adapter behavior without claiming additional physical truth.

Target/request/opportunity and other external search/selection evidence remain
outside B2 v1 content. Matching external evidence recomputes after schema-5
restart with independent coast decoding. No new checkpoint state, portable key
or codec/version is introduced. J2, maneuvers and wider fidelity remain open.

#### V5.6F1 static-axis Cartesian J2 gravity foundation (2026-09-18)

This bounded addition verifies only the instantaneous physical convention.
Earlier S008 subsections remain historical evidence. Broader orbit adequacy,
J2 propagation/certification, stationkeeping and propulsion remain unresolved.

| Record ID | Primary source and precise location | Verified F1 use and limitation |
|---|---|---|
| `iers-j2-potential-normalization` | [IERS Conventions Chapter 6, updated 2018-02-01](https://iers-conventions.obspm.fr/content/chapter6/icc6.pdf), PDF p.1 equations 6.1, 6.2a/b and 6.3; section 6.1; PDF p.2 equation 6.4 and Table 6.2; section 6.2.2 | The normalized harmonic expansion carries its own GM and gravity reference radius. For n=2,m=0 the normalization factor is sqrt(5), so unnormalized C20=sqrt(5)*normalized_C20 and J2=-C20. The source distinguishes TT-compatible scaling, coefficient reference epoch/secular variation, and zero-tide versus tide-free conventions. F1 adopts the degree-two convention only, with explicit unnormalized J2 and independent Rg; it adopts no numerical Earth bundle. |
| `orekit-j2-cartesian-acceleration` | [Orekit J2OnlyPerturbation.java](https://www.orekit.org/static/jacoco/org.orekit.forces.gravity/J2OnlyPerturbation.java.html), class documentation lines 38-48; unnormalized-provider constructor lines 109-116; computeAccelerationInJ2Frame lines 190-202 | Independent maintained implementation identifies correction-only gravity and J2=-C20; the Cartesian correction has factors x*(5q-1), y*(5q-1), z*(5q-3) and 3*mu*J2*Rg^2/(2*r^5). F1 adds the central term once. No Orekit dependency, example coefficient or spacecraft parameter is adopted. |

Source content was checked on 2026-09-18. IERS PDF content was directly read.
The relevant Orekit primary-source code/documentation was retrieved through
indexed source text; direct page opening returned an access/bot barrier. This
access distinction does not turn unrelated search summaries into force-law
evidence. No source library was installed or copied into the repository.

The project's negative specific potential is Phi=-V for the positive harmonic
potential convention: Phi=-mu/r+mu*J2*Rg^2/(2*r^3)*(3*z^2/r^2-1).
Differentiation gives the total Cartesian acceleration recorded in D317,
with acceleration=-grad(Phi). This differentiation is DERIVED_VALUE evidence.
The fixed MODEL_INERTIAL +z symmetry axis, static coefficient and truncation to
central plus degree two are EXPLICIT_MODEL_ASSUMPTION choices, not a full IERS
gravity/Earth-orientation model. No centrifugal/Coriolis acceleration is added.

J2GravityModel requires provenance-bearing mu, unnormalized J2 and Rg under
orbit.gravity.gravitational-parameter (m^3/s^2), orbit.gravity.j2 (1) and
orbit.gravity.reference-radius (m). ReferenceEllipsoid shape is separate:
neither its radius nor flattening silently supplies a gravity parameter.
A future Earth bundle must explicitly select consistent normalization, radius,
GM/time scaling, tide convention, epoch and any constant-coefficient
approximation. No such bundle or default value is introduced here.

F1 evaluates one supplied CartesianPosition at its unchanged explicit instant
and concrete MODEL_INERTIAL frame. Numerical products use frexp/ldexp exponent
accounting, avoiding explicit large radius powers and premature unit-component
underflow. Zero J2 bypasses correction arithmetic. Every evaluated nonzero term
must remain representable; intentional ValueError covers overflow, lost
nonzero terms and unsupported norms. Subnormal nonzero outputs have absolute
binary64 resolution; cancellation does not receive a relative-accuracy claim.
These are numerical implementation limits, not mission or physical radius
bounds, and supply no temporal certificate.

Independent tests derive gradients from the unsimplified potential
-mu/r+A*(3*z*z/r^5-1/r^3), A=mu*J2*Rg^2/2, using exact binary inputs in
90-digit Decimal and a 120-digit reference-precision check. Absolute comparison
budgets reserve 128u for the bounded norm/product/quotient/angular operations
and eight output ulps, scaled by uncancelled terms; default relative tolerance
is not used. These are scoped working arithmetic budgets, not formal intervals.

Central finite differences use the synthetic point (3,4,12) m, coordinate
directions and h=2^-12 m. The entire segment has r>12 m. Product-rule bounds
give M3=24*mu/rho^4+1110*mu*abs(J2)*Rg^2/rho^6, rho=12 m, as a conservative
third-directional-derivative allowance. The predeclared error budget is
h^2*M3/6+64u*S/h+128u*S/rho, S=mu/rho*(1+abs(J2)*(Rg/rho)^2), u=2^-53.
It separates truncation from potential/comparison rounding. Exact-binary hand
fixtures use mu=8, Rg=1 and J2=1/16: position (2,0,0) gives acceleration
(-131/64,0,0) m/s^2 and Phi=-129/32 m^2/s^2; position (0,0,2) gives
(0,0,-61/32) and Phi=-63/16. These are synthetic verification assumptions.

Zero-J2 independent central references, z reflection, quarter-turn z-axis
symmetry, signed J2, extreme scales, unsupported arithmetic and metadata/AST
guards supplement the gradient checks. No propagation, RK4 or validated-IVP
source record is added in F1. No binding, visibility, contact, observation,
maneuver, schema or B2 version change follows. Family A's propagation/enclosure
successors and Family B's interval-view/end-ray successor remain separate.

#### V5.6F2 nominal origin-anchored Cartesian J2 coast (2026-09-19)

F2 is nominal fixed-step RK4 only: no validated accumulated-error enclosure,
guaranteed event time or J2 visibility certificate. F3 literature/models are not
adopted here. The entire preceding F1 subsection remains byte-identical.

| Record ID | Verified primary source and exact location | Bounded use |
|---|---|---|
| `hairer-wanner-introduction-analyse-numerique-rk4` | Ernst Hairer and Gerhard Wanner, [Introduction à l'Analyse Numérique](https://www.unige.ch/~hairer/poly/poly.pdf), Université de Genève, June 2005; chapter III.2, equation (2.6), printed p.61; Definition 2.2/equation (2.8) and Table III.1 left, p.62; III.3 Theorem 3.1/equation (3.4), p.63, and Lemma 3.2/equation (3.8), p.65 | Classical explicit four-stage tableau, local fifth-order defect and formal global fourth-order convergence on fixed sufficiently smooth/Lipschitz intervals for sufficiently small steps. This verifies method/order, not a computed validated global enclosure. |
| `nasa-rickman-2020-j2-nodal-diagnostic` | Steven L. Rickman, [Introduction to Orbital Mechanics and Spacecraft Attitudes for Thermal Engineers](https://tfaws.nasa.gov/wp-content/uploads/Rickman-Presentation.pdf), NASA/NESC TFAWS, August 18-20, 2020, slides 105-106 (PDF indices 104-105); approximation context slide 4 | First-order nodal precession and its inclination-dependent sign, used only as a small-J2 approximation diagnostic. No Earth numerical coefficient or exact Cartesian trajectory is adopted. |

Both PDFs were directly checked on 2026-09-19. Hairer/Wanner is the verified
two-author lecture text, not the differently authored three-author monograph.
The RK4 tableau has c=(0,1/2,1/2,1), a21=a32=1/2, a43=1 and b=(1,2,2,1)/6.
Fixed h, max_steps, original-authority restart, canonical prefix and exactly
representable endpoint remainder are project numerical policy, not source claims.
F1 private _gravity is the sole force-law dependency; stage CartesianPosition
objects use the anchor instant because the force is static/autonomous.

Independent DERIVED_VALUE circle evidence: equatorial radial force requires
n^2=mu/r^3*(1+3*J2*(Rg/r)^2/2). Synthetic mu=8, r=2, Rg=1, J2=11/32 give
exact binary n=17/16 and speed=17/8. Thus r(t)=2*(cos(nt),sin(nt),0), with its
analytic velocity, is an independent nonzero-J2 trajectory reference with no
rounded initial-speed discrepancy. Decimal 90/110-digit references agree within
1e-60 SI outputs. Test spans use the exact represented requested-minus-initial
seconds; pi/trigonometry never secretly redefines the requested endpoint.

Zero-J2 comparisons separately retain B1's existing root/phase/reconstruction
working budget and its independent Decimal reference. F2 refinement uses
h=1/32,1/64,1/128 seconds on selected smooth arcs. The scoped nominal truncation
health envelope is 8*(1+n*abs(T))^2*(n*h)^4 times the position/velocity scale;
binary64 reserve is 256*u*N*(1+n*abs(T))*scale, u=2^-53. These are declared
verification policies, not global certificates. Adjacent error ratios use the
12..20 fourth-order band only when the finer error exceeds ten times the
reference/arithmetic reserve; at least one resolved pair is required, with
monotonic improvement and accuracy envelopes still checked at all three levels.
No tolerance is reduced to force a roundoff-limited order claim. Independent
energy/hz and forward/backward diagnostics do not substitute for endpoint checks.

The small-J2 test uses synthetic mu=1, r=1, Rg=0.5, initial velocity (0,0.6,0.8),
J2=2^-18 or 2^-17 and spans 16 or 32 nominal periods. Epsilon=J2*(Rg/r)^2
is at most 2^-19; n*T at most 64*pi. The first-order prediction is
DeltaOmega=-1.5*epsilon*n*cos(i)*T, with Omega from atan2(hx,-hy).
Direct circular torque integration yields the periodic correction
+0.75*epsilon*cos(i)*sin(2*n*T), bounded relative to secular drift by 1/(2*n*T).
The predeclared approximation-only allowance is 2%: the periodic envelope plus
a declared 20*epsilon*n*T higher-order diagnostic reserve is below 2%.
The latter reserve is an explicit small-parameter test policy, NOT a proven
remainder bound. Separate h=0.05,0.025,0.0125 refinement requires the final
nodal difference below 0.1% of predicted drift. Doubling J2/time comparisons
combine their individual absolute allowances. All of these inputs are synthetic.

Finite sums/products, nonzero-underflow and swallowed-increment checks bound
binary64 arithmetic; they supply no validated trajectory enclosure. No binding,
checkpoint, engine, C2/C3/D1, Earth default or schema change follows. F3/F4 and
Family B's interval-view/end-ray correction remain absent/open. F5 search-local
deterministic prefix reuse is expected later and is not implemented by F2.


#### Task 06A accumulated J2 endpoint error policy (2026-09-23)

Primary sources checked in this task:

| Record ID | Exact primary location | Bounded use |
|---|---|---|
| `neher-jackson-nedialkov-direct-enclosure-2005` | [On Taylor model based integration of ODEs, Karlsruhe preprint 05/21](https://publikationen.bibliothek.kit.edu/1000004610/1003614), section 2.1.2 p.3; section 4 p.7 equations (4.1)-(4.5); section 5.1 pp.8-9 | Outward interval arithmetic, coarse whole-step containment and direct Taylor endpoint/remainder recurrence; wrapping limitations. This candidate implements the direct box method, not Lohner or multivariate Taylor models. |
| `cowlishaw-decimal-directed-arithmetic-1.70` | [General Decimal Arithmetic v1.70, arithmetic operation rules](https://speleotrove.com/decimal/daops.html), general rules and add/subtract, divide, multiply, next-minus/next-plus, square-root subsections; [Python Decimal](https://docs.python.org/3/library/decimal.html), Decimal.from_float, Context, rounding modes and copy operations | Exact represented-input conversion and directed basic operations under the stated runtime contract. Neighbor square-root bounds receive an exact rational squared check; ambient context is not trusted. Sources do not certify this code. |

The specialized interval J2 coefficient recurrence, signed strict-Picard first-exit
argument, endpoint-distance accounting of all nominal F2 arithmetic and explicit
admission/work limits are project DERIVED method/policy, detailed in
V5_J2_ENCLOSURE.md and D319. They use the same complete F1 gravity authority;
no physical constant, new Earth bundle or fitted numerical multiplier is added.
The field enclosed is the real F1 IVP of represented inputs, not uncertain flight
truth. This tested floating-point enclosure implementation is not a formal
machine-checked proof. Unsupported computations return no usable bound.

Independent reference intervals use exact rational Taylor polynomials plus
analytic sin/cos remainders, not agreement of approximate solvers. Exact synthetic
circle and parabolic values are DERIVED test constructions. Inclined pilot
physical values are EXPLICIT_MODEL_ASSUMPTIONs, not sourced Earth coefficients.
No new visibility, checkpoint/binding, MS campaign or hardware claim follows.
Earlier S008 F1/F2 text is preserved as historical evidence.

---

### S009 — Spacecraft degradation / reliability literature

Purpose:
Support aging and degradation assumptions and their sensitivity ranges.

#### V5.2D1 research requirements

D1 records named physical capability retention and cumulative battery energy
throughput, not generic health or an arbitrary cycle count. Later work must
research battery calendar and cycling degradation, solar-array radiation and
environmental degradation, applicable operating-condition dependencies, and
uncertainty ranges before selecting any law or coefficient.

Any later numerical ageing relationship must distinguish sourced physical
quantities from explicit model assumptions and include sensitivity analysis.
D1 itself freezes no real spacecraft degradation value or rate.

#### V5.2D2A literature interpretation and deferred fidelity

Schmalstieg, J.; Käbitz, S.; Ecker, M.; Sauer, D. U. (2014), "A holistic
aging model for Li(NiMnCo)O2 based 18650 lithium-ion batteries," *Journal of
Power Sources* 257, 325-334, DOI
`10.1016/j.jpowsour.2014.02.012`. This peer-reviewed cell study supports the
conceptual separation of calendar and cycle ageing and their dependence on
temperature and operating stress. Its cell chemistry and fitted coefficients
are not automatically transferable, and its throughput semantics are not
identical to V5 battery-side energy throughput in Wh.

Borthomieu, Y.; Ma, C. (Saft), *Performances of SAFT VES16 Lithium-Ion Cells
in LEO/GEO Cycling*, NASA Aerospace Battery Workshop, Huntsville, Alabama,
14-17 November 2016. The VES16 life-test programme examines temperature,
DoD/charge current, end-of-charge voltage, and pulse effects under LEO cycling.
It is space-cell sanity evidence, not a KazEOSat-1 battery identity claim or a
source of generic V5 coefficients.

Summers, G. P.; Burke, E. A.; Shapiro, P.; Statler, R.; Messenger, S. R.;
Walters, R. J., *The Use of Displacement Damage Dose to Correlate Degradation
in Solar Cells Exposed to Different Radiations*, NASA record N95-20523. The
equivalent-fluence/displacement-damage framework requires a radiation
environment and cell-response evidence. V5 does not yet own either, so D2A
implements no automatic elapsed-time, radiation-dose, or fixed-percent-per-year
solar ageing law; solar retention loss remains explicit external forcing.

D2A deliberately omits SOC- and storage-voltage-dependent calendar stress,
DoD-dependent cycling stress, current/C-rate effects, chemistry-specific
electrochemical mechanisms, resistance growth, power fade, low-temperature
lithium plating, detailed reversible entropic heat, and radiation-driven solar
degradation. The post-V5.6 deepening gate revisits these mechanisms after the
orbit/environment and payload, ADCS, communications, propulsion, and improved
thermal-exposure models exist. The V5.12 pilot sensitivity study determines
whether more fidelity is required before the V5.13 physics freeze.

#### V5.2D2B2 engine and restart semantics

D2B2 applies the D2A battery law once after the current EPS and thermal
proposals are available. The endpoint is transactionally committed with the
other physical state, but it has no same-step effect on EPS or thermal
capability. Schema 3 already preserves the mutable retention and cumulative
throughput truth, so JSON checkpoint continuation requires no migration.

Solar retention changes only from explicit solar degradation forcing supplied
with a complete coupled interval. No forcing means exactly no solar loss; no
automatic radiation, elapsed-time, or percent-per-year relationship is added.

Status:
TO RESEARCH

---

### S010 — Onboard data, storage, and OBC evidence

Purpose:
Support future onboard equivalent-volume bookkeeping, storage configuration,
storage state, compression evidence, recorder throughput, and OBC/data-handling
boundaries.

#### V5.4A1 continuous equivalent-bit proposal

V5.4A1 adopts no new physical source or numerical spacecraft value. The V5.3
`uncompressed_equivalent_bits` quantity remains a DERIVED LEVEL-1 SAMPLE-GRID
PROXY. A1 carries that exact value into an identity/no-reduction proposal; this
is not detector truth, file size, stored state, downlink, or product truth. The
identity means only that the initial model applies no volume reduction and does
not claim that compression is absent from real spacecraft hardware.

Mission-specific capacity, compression, recorder throughput, packet/file
overhead, and storage/OBC power remain TO RESEARCH. Airbus telemetry, the WMO
90 W candidate, and other-mission NAOMI memory values are not transferred into
production.

#### V5.4A2 explicit acquisition-data record identity

V5.4A2 adopts no new physical source or spacecraft numerical value. Explicit
record identity is a model-architecture decision:
`AcquisitionDataRecordId` is supplied by the caller and is not a
`DataProductId`. The immutable eight-field record carries Level-1 request and
opportunity lineage plus continuous equivalent-bit quantities under the A1
identity/no-reduction rule. It does not claim a real file, container, or packet
format, downlink, or mission/product completion.

Capacity, compression, recorder throughput, packet/file overhead, storage/OBC
power, and recorder hardware remain TO RESEARCH.

#### V5.4B1 decimal-GB whole-record storage admission

V5.4B1 adopts no new spacecraft numerical storage value. It interprets the
existing `GB` configuration unit as decimal GB, with 1 GB equal to
8,000,000,000 bits, for canonical continuous equivalent-bit bookkeeping.
Deterministic occupancy summation and whole-record admission are model-
architecture decisions, not real file, packet, container, or filesystem
semantics.

B1 adds no compression model, overwrite or eviction policy, recorder
throughput, storage/OBC power, or persistent storage behavior. KazEOSat storage
capacity remains TO RESEARCH.

#### V5.4B2 persistent storage state and checkpoint schema 4

V5.4B2 adopts no new physical source or spacecraft numerical value. Persistent
storage state, insertion-order preservation, exact equivalent-bit quantity
persistence, duplicate-record-ID rejection, active configuration capacity
validation, and checkpoint schema 4 are model-architecture decisions. Capacity
remains supplied by the existing explicit `StorageConfig`. Occupancy continues
to use the B1 decimal-GB and complete ordered-sequence `math.fsum` semantics; no
capacity or redundant total is stored in `DataStorageState`.

The current parser accepts schema 4 only. It rejects schema 3 rather than
silently assuming that unknown historical onboard storage was empty. B2 adds no
record creation from imaging, append or removal transaction, compression,
overwrite or eviction policy, recorder throughput, storage/OBC power,
communications or downlink, or mission/product completion. KazEOSat storage
capacity and recorder hardware remain TO RESEARCH.

#### V5.4C pure imaging/storage authorization composition

V5.4C adopts no new physical source or numerical spacecraft value. Its pure
composition reuses the existing V5.3 acquisition, EPS, and thermal evidence,
then preserves the A1 Level-1 equivalent-bit semantics while applying B1
whole-record admission to current persistent B2 storage truth. Storage
capacity remains explicit configuration; C establishes no recorder hardware
truth.

C adds no append, downlink, compression, throughput, or power model. It also
adds no record removal, engine commit, communications behavior, or mission and
product completion.

Status:
TO RESEARCH

---

## Rule for Explicit Assumptions

If no defensible public value exists, V5 may use an explicit assumption.

The assumption must:
1. be labeled EXPLICIT MODEL ASSUMPTION,
2. have physical units,
3. have a stated rationale,
4. have a reasonable sensitivity range,
5. not be presented as a real KazEOSat-1 property.
