# B56 paid solar attitude candidate

This additive candidate is an ASSUMED reduced operational model, not flight
control, a wheel plant, attitude accuracy qualification or a hardware winner.
Legacy roots have `energy_attitude_policy=None`: original input/native/scientific
wires remain distinct. B56 input V5 and native V5 bind the new policy and state;
there is no migration of an old B55 experiment into the new source.

## Physical contract

SI metres, kilograms, seconds, joules, watts; battery/report energy Wh. Hamilton
scalar-first unit quaternion maps BODY to the declared MODEL_INERTIAL frame.
The real M1 mount-derived panel normal is the commanded BODY axis. Camera axis
and hardware are never replaced. Supported hardware has one effective panel
normal. Sun is a typed inertial target with world/role/clock/frame/epoch binding,
derived by separate charged orbit and model-Sun queries. Exact model knowledge
of Sun and rested pose is an explicit sensor assumption, not a flight sensor.

The constructive M3/B46 rest-to-rest triangular slew is reused with an explicit
axis: full harness-augmented tensor I, H=I*omega, tau=I*alpha+omega cross H.
Rational whole-phase bounds enforce declared component torque/rate/momentum
limits; 80-bit square-root bounds and a 2^-40 s upward time grid determine the
finite plan. Nominal quaternion interpolation uses the accepted libm algorithm.
Parallel turn is zero; antiparallel chooses the least-aligned Cartesian basis
with deterministic index/sign ties. No roll is optimized. Duration <=120 s.
Existing coupled actuator/EPS/harness/thermal owners pay the real motion and
heat. A hold fixes the inertial quaternion. Eclipse/shadow and incidence still
belong to the existing forcing/PV owners; pointing does not create sunlight.

## Frozen operational assumptions

Common onboard autonomous policy: enter at 50% current usable capacity; exit at
75%, after >=600 s dwell. Existing B55 SAFE10/high30 policy is unchanged. A turn
requires a zero-PV battery reserve of V_bus*I_bus*(slew_seconds+60)/(3600*eta_d)
plus the existing hard-SAFE energy floor. The declared 28 V/20 A bus ceiling
motivates preventive entry above the example 20%; values are frozen before
actual runs and are not fitted to credits. Repoint check >=1800 s; turn only
when actual panel-to-current-model-Sun angle >=10 degrees. Every query and turn
is paid; this is not continuous free tracking. Exhausted/SAFE/OFF remains passive.

Existing pending science/contact finishes at its original paid boundary; custody,
partial bits and issued ground intents are never deleted. Charge actions have
separate lineage and no mission credit or early received ground ACK. Deadlines
and opportunity loss continue. Ground planning uses only powered delayed
observations and its own paid physical catch-up with a separate forecast world,
state, cache and ledger. Received pending solar plan is immutable data; future
forecast queries create FORECAST targets and cannot become ACTUAL authority.
Loss during unsupported moving dynamics retains original pose/phase/paid prefix
and a typed refusal; it does not teleport into a rested target.

## State, reporting and execution

Policy identity, charge phase/dwell/cadence, held Sun target, pending original
slew, cumulative attempts/refusals/time/actuator Wh/hold and positive-charge
seconds persist through the fixed native registry. Actual/received/estimated
views remain separate. Last incidence/illumination describes only the last
returned selected support. Positive-charge hold duration is a sampled selected
support measure, not continuous safety. No voltage chart or battery R is added.

The separately source-bound B56 resource controller admits exact 668 worker
members plus its separate controller SHA (669 total files), current runtime and
policy. Old R2 controller and 659-worker authority remain unchanged. Settled
TIME/OUTPUT can continue automatically within <=5 primaries, 8 jobs/1536 MiB,
128 MiB/job; hard1550/soft1250/reserve300 seconds. UserStop pauses; unknown forced
suffix blocks. Costs include failed/obsolete actual attempts, never refunded.

CLI `examples/m8_lifecycle.py create/configure` accepts
`--energy-attitude-policy B56_ONBOARD_PREVENTIVE_SOLAR_ATTITUDE_V1` together with
the explicit B55 service policy. `chain-create --maximum-primary-segments 5`
selects the new trusted controller. Workbench selector compiles the same root;
its progress views display actual/received/estimated solar state and true costs.

## Predeclared verification screens and limits

Geometric goal residual <=3e-14 per unit-vector component (nominal floating
quaternion rounding); exact Fraction actuator bounds and exact terminal zero
kinetic energy. Independent Euler algebra checks use 5e-15 W absolute rounding
screen in the bounded short fixture, not physical model accuracy. Same-root,
same-runtime fresh continuation requires full canonical scientific equality,
zero observed RESTORE prefix calls; admission is separately charged. Quiet vs
1 s detailed short physical screens retain <=0.005 Wh /0.05 K from B53; exact
action/custody/credit equality is not inferred across different numerical methods.

Actual experiment roots freeze before launches: common short7200 s/45 Wh for
old/new and compact/outboard policy comparisons; only policy or declared
placements differ in the respective pairs. Full new month uses the exact B55-R2
hardware/world/workload/initial80 Wh (nominal capacity100 Wh)/numerics/heat/ageing/deadlines and original
[128,2592128] s authority. Only explicit B56 policy/version/output bindings differ.
The saved negative old month is reused. No desirable result is required.
One month does not imply a year, 15-year lifetime, M2 physical validation or full V5.
