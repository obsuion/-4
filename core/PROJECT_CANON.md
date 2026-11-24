# Project canon

This document records architectural boundaries that later versions must preserve
unless a version explicitly proposes, tests, and documents a change.

## Project boundary

This project is an open, intentionally simplified KazEOSat-1-inspired
operational proxy. This project is not official KazEOSat-1 software and not a
physical digital twin. Its outputs are not validated operational forecasts.

## Public/spec-inspired assumptions

Public KazEOSat-1 values motivate selected transparent reference parameters, but
they do not calibrate or validate the simulator. The distinction between public
values, implemented proxy values, rounded assumptions, and future-only metadata
is recorded in [KAZEOSAT_PUBLIC_SPEC.md](KAZEOSAT_PUBLIC_SPEC.md).

## Contact model hierarchy

Synthetic contacts are baseline/regression controls, not the final research
direction. They remain useful for sanity checks, controlled comparisons,
backward-compatible CLI behavior, and comparability with older tests.

Geometry + `drift_proxy` is the final research direction. It is the more
realistic proxy path and the primary contact/orbit choice in the `final_v40`
research-suite profile, subject to the limitations below.

## Final research direction

The intended integrated configuration is documented in
[FINAL_CONFIG.md](FINAL_CONFIG.md). V4.0A makes it the primary `final_v40`
configuration: geometry contacts, state-aware drift-proxy orbit evolution,
explicit drift-aware stationkeeping planning, and the already implemented
bounded lifecycle/debris, autonomy, power/thermal, target/pointing, and packet
layers. `contingency_plan` is the conservative primary autonomy assumption;
`limited_maneuver_authority` is a sensitivity case.

## Research-suite architecture

V4.0A provides two explicit profiles. `final_v40` is the primary scientific
profile and uses the geometry-first complete stack. Its layer ablations compare
bounded substitutions or removals against `final_full_stack`, including one
explicitly labeled synthetic-contact control. `legacy_v30` preserves the
historical synthetic core, A/B/C/D/E ablation chain, and output families for
regression and controlled comparison. Synthetic contacts are not the primary
scientific model.

Every final core and ablation raw row records its suite profile, configuration,
experiment seed, all model selectors, and packet drop fraction. Matched runs
reuse the same stochastic catalog and packet-delivery seed. The canonical
packet drop fraction `0.10` is an explicit synthetic stress assumption, not
measured or calibrated reliability. V4.0A connects existing model layers; it
does not change simulator semantics or add spacecraft physics.

## No-contact fallback ladder

The authoritative sequence is:

`uploaded daily plan -> BACKUP -> EMERGENCY_BEACON`

The uploaded plan is valid for about 24 hours. Plan expiry leads to `BACKUP`,
and about 14 days (336 hours) without command contact leads to
`EMERGENCY_BEACON`. V3.4 autonomy does not replace the fallback ladder. The
`no_contact_timeout` autonomy trigger is a local diagnostic/fallback marker, not
the 14-day emergency mechanism.

`BACKUP` is not the terminal no-contact state; it is the fallback after daily-
plan expiry. When drift is critical, resources are sufficient, and no higher-
priority block exists, drift-aware stationkeeping may temporarily select
`MANEUVER` from `BACKUP` as a bounded onboard maintenance/safety override. This
is not live ground commanding
during a no-contact period. `EMERGENCY_BEACON` remains terminal and is never
overridden by stationkeeping; critical real-state `SAFE` and an uploaded/eligible
debris response at TCA also retain priority.

## Ground/spacecraft information separation

Ground-only warnings do not make the spacecraft aware. Lifecycle warnings do
not refresh delayed telemetry. Scheduled future events remain hidden before
`warning_hour`. A debris response can execute only when it has been uploaded and
is eligible at time of closest approach (TCA).

## Autonomy boundaries

The contingency plan is a bounded, uploaded authority envelope layered on the
fallback ladder. Autonomy uses only current real onboard state, current contact,
uploaded authority, and already uploaded spacecraft awareness. It does not
forecast catalog events, convert ground-only knowledge into onboard knowledge,
refresh telemetry, or replace the existing maneuver and debris resolvers.

## Debris/lifecycle boundaries

Lifecycle warning timing, response upload, and TCA eligibility are information-
flow proxies. Debris severity, miss distance, impact zone, and damage are
deterministic stress-test proxies. They are not collision probability,
conjunction screening, covariance analysis, or physical impact prediction.

## Geometry/orbit boundaries

Geometry uses a spherical Earth and an analytical circular-orbit proxy. The
`drift_proxy` maps bounded state errors into that geometry; it is not orbit
determination or flight dynamics. The project does not implement TLE/SGP4
propagation, J2, atmospheric drag, a radio link budget, or operational station
schedules.

## Power/eclipse and thermal boundaries

The optional `eclipse_proxy` is a deterministic orbit-phase and power-budget
proxy. It does not use a real sun vector, ephemeris, date, seasonal geometry,
solar-array model, EPS model, battery electrochemistry, or thermal balance. The
public 1200 W value is reference metadata and a sanity-check value only; it does
not calibrate the proxy generation, load, or SOC assumptions. `legacy` remains
the compatibility default and preserves the established SOC behavior.

The optional `load_stress_proxy` uses executed mode load and, when available,
the V3.6A sunlight/eclipse and net-power diagnostics to apply a small bounded
decrement to existing thermal health. With legacy power it uses mode load only
and does not invent sunlight or eclipse state. It is not a temperature,
heat-transfer, radiator, heater, seasonal, or thermal-balance model. The public
1200 W value remains reference metadata and does not calibrate thermal stress.
`legacy` remains the thermal compatibility default and adds no degradation.

## Target/scene boundaries

The optional `scene_scheduling_proxy` is a deterministic synthetic target-
opportunity proxy. It is not real mission planning, target demand, cloud or
weather modeling, observation geometry, attitude or pointing physics, real
tasking software, or a validated Earth-observation scheduling model. Public
scene size, imagery modes, revisit, resolution, and productivity values remain
metadata or sanity references and do not calibrate simulated operations.
Selected hours, priority totals, and scene-label counts describe attempted or
selected opportunities. Effective imaged-area proxy applies any bounded
pointing multiplier, while legacy pointing preserves full selected-scene area.
`legacy` remains the compatibility default and preserves established IMAGING
data generation.

## Attitude/pointing boundaries

The optional `bounded_pointing_proxy` is a deterministic stress-test constraint
that applies an additional operational multiplier on top of established
ADCS-health-based IMAGING and DOWNLINK capability, using existing ADCS health
and synthetic off-nadir, slew, and degraded-geometry penalties. It is not real
attitude dynamics, pointing control, observation geometry, a physical slew
model, ADCS flight software, or validated KazEOSat-1 operations. It does not
change policy planning, target opportunities, SOC, or the fallback ladder.
`legacy` remains the compatibility default and adds no new constraint.

## Command/telemetry packet boundaries

V3.8A's optional `packet_proxy` passively accounts for one generated
housekeeping packet per executed hour, existing telemetry refreshes, actual
daily-plan uploads, lifecycle-response uploads, and contingency-plan uploads.
With the default `packet_delivery_model=ideal`, it preserves V3.8A behavior.

V3.8B's opt-in `loss_retry_proxy` distinguishes a physical command-contact
opportunity from successful information transfer. A deterministic seeded gate
can defer telemetry refresh, daily-plan installation, lifecycle-response upload,
or contingency-authority upload until a later eligible contact. Telemetry uses
the existing latest observed-state snapshot; lifecycle and plan state use their
existing persistence. There is no general packet queue or arbitrary in-flight
arrival. Physical contact still controls the established 336-hour emergency
timer, even when a particular transfer fails.

Packet sizes and the drop fraction are explicit stress-test assumptions, not
values calibrated from the public X-band rate, QPSK, or KazEOSat-1 reliability.
Packet KB never competes with payload imagery capacity.

This is not CCSDS, a real packet protocol, a real S-band/X-band command link,
modulation simulation, a link budget, ground-network behavior, or flight
software. `legacy` remains the compatibility default and adds no accounting.
This is also not BER/FER or RF propagation. Here, delivery "delay" means retry
at a later eligible physical contact, not propagation delay.

## Remaining Useful Life boundaries

V3.9A is current-stack integration of the existing simulation-based,
horizon-censored RUL workflow. Each sample uses one catalog and one warmed
Simulator across the warm-up and absolute-hour continuation, so internal
telemetry, lifecycle, autonomy, stationkeeping, and deterministic packet context
is not reconstructed at the boundary. The sample seed also drives packet
delivery when that proxy is enabled.

V3.9B is a parallel statistical interpretation of existing `RULSample` rows; it
does not change their generation. The unconditional V2.9 statistics describe
the whole simulated population and retain zero additional RUL for warm-up
failures. Conditional V3.9B statistics include exactly samples alive at the
start year and ask how much bounded additional life remains within the common
requested horizon. When there is no eligible population, conditional scalars
are unavailable rather than an invented zero-reliability result.

Conditional survival uses simple empirical proportions with 95% Wilson
binomial intervals. The conditional censored mean is the restricted mean under
the shared administrative horizon, with a percentile bootstrap that resamples
eligible rows without rerunning the simulator. These intervals describe finite
Monte Carlo sample-estimate uncertainty only, not parameter uncertainty,
model-form uncertainty, real reliability, or KazEOSat-1 confidence intervals.
There is no extrapolation, Weibull fitting, hazard inference, component MTBF, or
Kaplan-Meier requirement. Failure tables use only existing simulated loss
reasons. Censored-survivor risk rows describe the nearest proxy risk driver,
not a predicted failure cause. V3.9B remains opt-in in standalone `rul.py`.

In V4.0B, the `final_v40` paper-suite core and RUL matrices use the same
canonical geometry-first complete-stack configuration. Each RUL sample keeps
one warmed Simulator across warm-up and continuation; its sample seed also
selects the event catalog and deterministic packet-delivery draws. The
`legacy_v30` profile retains the historical synthetic compatibility RUL path.

Whenever final-profile RUL is enabled, the paper suite applies the existing
V3.9B functions to the already-generated sample rows. It does not rerun the
simulator. Unconditional results remain the paper-score input and conditional
results remain a parallel interpretation. Bootstrap controls affect only the
row-resampling interval, not sample seeds, simulated trajectories, or the
established V2.9/V3.9 statistics.

## Research-suite validation and sensitivity boundaries

V4.0B internal validation is structural and reproducibility-oriented. It checks
selector provenance, packet-seed provenance, numeric bounds, population
accounting, conditional zero-eligible semantics, confidence-interval bounds,
and failure/risk table decomposition. A failed required check stops the final
suite. Passing these checks is not external validation, calibration, or evidence
of operational accuracy.

Public-spec sanity rows compare metadata and simple unit/reference
relationships only. Exact or rounded agreement with a public reference does not
calibrate the simulator. Reference-only quantities are explicitly marked not
comparable when no implemented proxy output has the same meaning.

Layer-sensitivity rows are computed from the existing bounded matched
ablations. Missing metrics remain unavailable rather than invented zeros. The
reported deltas are within-model sensitivity comparisons, not independently
identified physical causal effects; coupled-layer ablations must be interpreted
as coupled changes.

The RUL workflow is not a new physical lifetime model, physics-of-failure
analysis, or KazEOSat-1 lifetime prediction. Packet loss affects RUL only
through existing causal operational effects. Target and pointing constraints
describe operational productivity and are not physical failure modes by
themselves.

## What future versions may change

Future versions may refine explicitly scoped power/thermal/eclipse and pointing
proxies, packet-level command and telemetry accounting, reliability analysis,
internal validation workflows, and final synthesis. Such work may use public
values as metadata or sanity-check references while keeping proxy assumptions
explicit. It must not imply real calibration without real calibration evidence.
V4.1 owns final figures/tables/case studies/synthesis, and V4.2 owns archive,
reproducibility, and defense packaging.

## What future versions must not silently change

Future work must not silently reinterpret synthetic contacts as the final
scientific model, make scheduled events visible before warning, merge ground and
spacecraft knowledge, bypass response-upload gating, replace the canonical
fallback ladder with contingency autonomy, or present proxy values as validated
KazEOSat-1 operations. Changes to these boundaries require an explicit versioned
proposal, focused tests, and updated documentation.
