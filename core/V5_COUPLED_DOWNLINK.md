# Task 03A: explicit physically coupled downlink

Implemented candidate for coordinator review; no project decision or commit is
implied. The legacy `SimulationEngine.step_downlink` remains the V5.5 data-only
API. Its inputs, result type and physical non-evolution are unchanged.

## Entry point and interval ownership

`SimulationEngine.step_coupled_downlink(context, contact, *, record_id,
physical_inputs)` accepts one `ServiceableGroundContact` exactly matching
`[context.simulation_time_seconds, simulation_time_seconds + timestep_seconds)`
within the common-world horizon. Selection, chronology, partial progress,
whole-record storage release and conservative completion-at-contact-end semantics
reuse the existing V5.5 handler and Task 01 validation.

`coupled_downlink.py:CoupledDownlinkInputs` requires all of:

- `DownlinkTransmitterConfig.electrical_power_w`: a positive `ScalarParameter`,
  semantic ID `communications.transmitter-electrical-power`, units `W`, with
  source IDs or an explicit model assumption and rationale. This is bus-side
  transmitter on-state electrical demand. Existing `CommunicationsConfig` owns
  only bitrate; it is unchanged. No bitrate-to-power law is inferred.
- Seven explicit baseline component powers. `communications_w` must be zero;
  the transmitter supplies that component exactly once. Base bus, OBC, ADCS,
  payload, communications, thermal control and propulsion are all required
  loads, with no allocation priority or starvation of another component.
- Explicit `sunlit`, incidence angle in degrees, component heat routing,
  thermal sink boundaries, absorbed external heat and solar degradation forcing
  (explicit `None` means no solar degradation transition).

The direct coupled API shares the bundle codec's exact supported scalar/record
contract. Its forcing graph is reconstructed, including nested provenance and
route fractions. Boundaries and external sources must cover exactly the thermal
network nodes; routes must name configured nodes. External internal-dissipation
fields must be zero, since component routing owns those terms. Absorbed solar,
albedo and Earth-IR powers must not duplicate flux already in the effective sink.

The transmitter stays energized for the **entire step**, even when the selected
record completes before exhausting nominal data capacity. Unused capacity is
discarded; there is no early shutdown, residual wait, second record or substep.

## Authorization and atomicity

One authoritative `EPSIntervalResult` uses the existing degraded battery/solar
capability. Full service requires `unmet_load_w == 0` exactly according to the
EPS numerical contract; there is no added tolerance or fractional bitrate.
Energy and bus-side discharge-power limits both apply. Zero energy plus zero
generation denies; an empty battery with sufficient generation can authorize.

The engine prepares the existing data proposal on the transaction's private
checkpoint clone before electrical authorization, so malformed selection and
chronology remain errors even without supply. No proposal mutates the caller.
On authorization it routes the actually serviced component loads and passes the
same EPS result to thermal coupling and the shared physical-completion helper.
That helper computes throughput, temperature-dependent ageing, explicit solar
degradation and capacity reconciliation once. The existing transaction runner
validates the complete state and result before its single commit. Data, physics,
diagnostics and clock therefore describe the same interval.

`CoupledDownlinkAttempt` (exported from `coupled_downlink.py`) reports the contact,
validated forcing, EPS/capability, routed heat, transmission and `StepResult`.
Its `authorized`, `time_advanced` and `denial_reason` properties are unambiguous.
Electrical denial returns `insufficient-electrical-service`, `time_advanced=False`
and no transmission/routed-heat/step result. The diagnostic EPS proposal is **not
applied**. Physical state, custody, delivery, knowledge, diagnostics and clock
remain unchanged. Invalid input or late validation failure raises atomically.

Denial is not waiting. The example separately executes a transmitter-off
`SimulationEngine.step` with explicit baseline EPS, heat, thermal and degradation
forcing. Only this explicit wait advances one interval and delivers no data.
There is no implicit retry, planner, threshold, hysteresis or FDIR policy.

## Existing equations and independent verification

No physical formula owner is changed:

| Quantity | Existing owner and equation |
| --- | --- |
| Solar power | `solar.py`, `eps_capability.py`: retained nominal power times illumination and nonnegative cosine incidence |
| Battery | `eps.py`, `eps_system.py`: for deficit `D`, delivered power is limited by discharge rating and `E_start * eta_d / dt_h`; `E_end = E_start - P_dis * dt_h / eta_d`; loss `P_dis * dt_h * (1-eta_d)/eta_d`. Surplus uses existing charge rating, efficiency, capacity and curtailment rules |
| Component heat | `thermal_routing.py`: `Q_component = P_served * retained_heat_fraction`, accumulated by declared node |
| Battery heat | `thermal_coupling.py`: conversion loss in Wh times `3600/dt_seconds`, once at the battery node |
| Temperature | `thermal.py`: existing explicit Euler `T_next = T + dt_seconds * Q_net / C`, including configured conduction/radiation |
| Battery ageing | `degradation.py`: existing Arrhenius factors at midpoint battery temperature, calendar rate times duration plus cycling coefficient times cell-side throughput/nominal Wh |
| Capacity | `eps_capability.py`: authoritative energy is `min(EPS_end_energy, nominal_Wh * end_retention)`; unavailable reconciliation energy is recorded, not added to heat |

`examples/v5_coupled_downlink_demo.py --numerical` provides rational hand
electrical/constant-source thermal references and a 50-digit Decimal Arrhenius
reference independent of the production evaluators. Synthetic case:
36 seconds, 24 W baseline plus 36 W transmitter, 20 W solar, 80 Wh initial energy,
0.8 discharge efficiency, 100 Wh nominal capacity at 0.9 retention. Expected:

| Quantity | Expected |
| --- | ---: |
| Fully served demand / battery bus output | 60 W / 40 W |
| Cell-side throughput / conversion loss | 0.5 Wh / 0.1 Wh |
| End energy | 79.5 Wh |
| Internal bus / payload heat | 28 W / 2 W |
| Battery conversion heat | 10 W |
| Bus / battery / payload final temperature | 300.3 K / 300.11 K / 300.05 K |
| Partial service / retained allocation | exactly 9000 / 12000 equivalent bits |

The network has three isolated nonradiating nodes with C=3600 J/K. Thus each
constant-heat temperature evolution has an analytic linear solution; tests use
18 and 36 seconds. This is not evidence of general Euler stability merely from
energy conservation. Nonzero calendar/cycling coefficients and activation
energies exercise temperature dependence. A separate full degraded-battery case
exercises positive reconciliation loss without spurious heating.

Data, status, clocks, boundary authorization and same-environment restart use
exact comparisons. Numerical reporting uses at most 64 binary64 ulps of the
nonzero reference (unit scale only for expected zero), covering the short
arithmetic chain, binary representations and exp/reciprocal rounding against
the rational/Decimal reference. It is not an electrical admission tolerance.
The report emits every actual value and absolute bound in its physical units.
All coefficients are synthetic test assumptions, not KazEOSat calibration.

## Restart and compatibility

`continuation.py:CoupledDownlinkAction` explicitly carries `physical_inputs` and
requires script version 2. Version 1 still supports its original imaging and
data-only `DownlinkAction` content. Version 2 may contain both downlink types;
the action type, never the version number alone, chooses the physical path.
Unknown script versions fail closed. `advance_continuation` raises the distinct
`ContinuationElectricalDenial` on valid electrical denial; its `attempt` and
`action_id` are inspectable. Caller context, prior acquisition and executed
prefix/forcing cursor are unchanged. There is no extra persistent runner state.

Only three exact input/action records are added to `_experiment_types.py`.
Bundle/canonical/provenance versions remain 1; old canonical content is not
reinterpreted. Old readers reject the unsupported version/record tags. Physical
states and partial/completed delivery remain in unchanged checkpoint schema 5;
B2 versions/digest stay 1/1. Every new parameter, value, unit, provenance, load,
forcing, route and explicit assumption participates in input identity.
Strict source/environment compatibility remains mandatory: schema readability
does not authorize restoring an artifact captured under different source bytes.

The new demo executes imaging, coupled partial transfer, a second imaging,
completion, partial transfer and completion with nonzero ageing and explicit
solar loss. JSON-only fresh-process tests compare the full checkpoint (including
physical and knowledge states), memory, actual action choices and metrics at
all boundaries 0 through 6, including partial transfers. They forbid rebuilding
the origin fixture during restore.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m examples.v5_coupled_downlink_demo --numerical --output C:\TEMP\numerical.json
.\.venv\Scripts\python.exe -B -m examples.v5_coupled_downlink_demo --output C:\TEMP\direct.json
.\.venv\Scripts\python.exe -B -m examples.v5_coupled_downlink_demo --stop-after 2 --bundle-output C:\TEMP\partial.json --output C:\TEMP\prefix.json
.\.venv\Scripts\python.exe -B -m examples.v5_coupled_downlink_demo --resume C:\TEMP\partial.json --output C:\TEMP\resumed.json
```

Supply an existing external output directory. Remaining limitations include
declared serviceability, nominal bitrate, fixed intervals, explicit supplied
forcing and a bounded script rather than a mission controller. No RF success,
station scheduling, autonomous waiting, numerical-method deepening, Task 03B,
Task 04 or V5 completion is claimed.
