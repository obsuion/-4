# Intended final research configuration

The canonical primary configuration for the `final_v40` research-suite profile
is:

```text
contact_model = geometry
orbit_evolution_model = drift_proxy
operator_view = delayed_telemetry
planning_model = risk_aware
maneuver_model = stationkeeping_proxy
stationkeeping_planning_model = drift_aware
power_model = eclipse_proxy
thermal_model = load_stress_proxy
target_model = scene_scheduling_proxy
pointing_model = bounded_pointing_proxy
packet_model = packet_proxy
packet_delivery_model = loss_retry_proxy
packet_drop_fraction_proxy = 0.10
event_lifecycle_model = warning_proxy
debris_risk_model = severity_proxy
autonomy_model = contingency_plan
```

Geometry-first is the final research direction because geometry contacts plus
state-aware `drift_proxy` evolution connect the simplified orbit state to contact
opportunities. This remains a proxy, not flight dynamics, operational ephemeris,
or validated forecasting. `contingency_plan` is the conservative primary
bounded-authority assumption. `limited_maneuver_authority` is an explicit
sensitivity case and must not silently become primary. The packet drop fraction
`0.10` is an explicit synthetic stress assumption, not measured or calibrated
link reliability.

For the explicitly labeled autonomy sensitivity comparison only:

```text
autonomy_model = contingency_plan or limited_maneuver_authority
```

This line describes the comparison range; it does not make
`limited_maneuver_authority` a primary assumption.

## Baseline and regression comparison

Controlled baseline and legacy-ablation configurations may use:

```text
contact_model = synthetic
orbit_evolution_model = fixed or drift_proxy
operator_view = omniscient
planning_model = reactive
stationkeeping_planning_model = legacy
power_model = legacy
thermal_model = legacy
target_model = legacy
pointing_model = legacy
packet_model = legacy
packet_delivery_model = ideal
```

Synthetic contacts are retained as a baseline/regression control, sanity check,
global simulator CLI default, `legacy_v30` suite profile, and old-test comparison
path. Omniscient and reactive settings remain available for legacy ablations
where needed. Synthetic is not the primary scientific contact model.

The `final_v40` paper-suite profile now prioritizes `geometry` + `drift_proxy`
while retaining a bounded, explicitly labeled synthetic-contact control.
The `legacy_v30` profile preserves the historical synthetic experiment matrix,
and global simulator CLI defaults remain backward compatible.
V3.5 makes `drift_aware` the intended stationkeeping selector for that final
geometry-first path while retaining `legacy` as the global compatibility default.
V3.6A similarly retains legacy power behavior by default while identifying the
bounded `eclipse_proxy` as the intended integrated research selector.
V3.6B retains `legacy` thermal behavior by default while identifying the bounded
`load_stress_proxy` as the intended integrated research selector.
V3.7A retains `legacy` target behavior by default while identifying the bounded
`scene_scheduling_proxy` as the intended integrated research selector.
V3.7B retains `legacy` pointing behavior by default while identifying the
bounded `bounded_pointing_proxy` as the intended integrated research selector.
V3.8A retains `legacy` packet behavior by default while identifying the passive
`packet_proxy` accounting selector for the intended integrated configuration.
V3.8B retains `ideal` packet delivery as the global compatibility default while
identifying `loss_retry_proxy` for explicitly degraded integrated experiments.
Every such experiment must report its deterministic seed and synthetic drop
fraction; neither is calibrated KazEOSat-1 communications reliability.

## V3.9 RUL integration and interpretation

The existing simulation-based, horizon-censored RUL workflow can now run either
the legacy baseline above or the complete explicitly selected current stack.
One warmed Simulator remains authoritative across each sample's warm-up and
continuation, and the sample seed also drives packet delivery when enabled.

For `final_v40`, V4.0B uses the same canonical configuration above for both the
core and RUL matrices. Each sample uses one warmed Simulator across warm-up and
continuation, and its sample seed also selects the event catalog and packet-
delivery draws. `legacy_v30` retains the historical synthetic RUL compatibility
path. Standalone `rul.py` defaults remain unchanged.

V3.9A adds no new physical lifetime model. V3.9B adds only a statistical
interpretation of existing sample rows: conditional results include exactly
samples alive at `start_year`, remain censored at the common requested horizon,
and do not replace the unconditional V2.9 statistics. In the final profile this
analysis is automatic whenever RUL is enabled and never reruns the simulator.
The unconditional results remain the RUL input to the paper score.

Wilson survival intervals and a row-resampling bootstrap for the bounded
conditional mean describe finite Monte Carlo sample uncertainty only. They are
not model or parameter uncertainty, calibrated lifetime prediction, or real
KazEOSat-1 reliability. Bootstrap controls do not change sample seeds or
simulated trajectories.

## V4.0A suite profiles

`final_v40` is the default scientific suite profile. Its core uses the canonical
configuration above, and its bounded layer ablations are compared against a
`final_full_stack` reference. `legacy_v30` is the synthetic regression/control
profile and retains the historical core, A/B/C/D/E ablations, RUL compatibility
path, and output families. V4.0A changes experiment architecture and selector
plumbing only; it adds no spacecraft physics, calibration, or operational
validation.

## V4.0B validation and sensitivity interpretation

The final profile reports internal structural checks, public-spec sanity rows,
and layer-sensitivity deltas. Internal checks verify suite provenance, numeric
bounds, RUL population accounting, and reliability-table consistency; they are
not external validation. Public-reference comparisons are exact, rounded, or
reference-only metadata checks and are not calibration. Sensitivity rows are
derived from the existing bounded matched ablations and are not physical causal
effect estimates. Missing quantities remain unavailable rather than invented
zeros.

V4.1 owns final figure, table, case-study, and narrative synthesis. V4.2 owns
archive, reproducibility, and defense packaging.
