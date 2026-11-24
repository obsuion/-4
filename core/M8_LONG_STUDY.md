# B53 declared long-study input and sampled lighting accounting

`LifecycleStudyInput` is a separate immutable ASSUMED synthetic plant input.
It does not modify the original B52 epsilon-zero failure or the lowheat24h
fixture. `compile_study_base` is an initial-input compiler, not a restart or
advanced-state migration. `study_to_data`/`study_from_data` preserve exact
binary64 coefficients as canonical hex strings with strict physical units.
The digest covers method, domain, latency, all node coefficients and rate
sensitivity. The caller binds that digest in the submitted lifecycle root.

The common pre-run preset uses 4 W housekeeping, inherited actual payload,
transmitter and actuator owners, three role nodes with heat capacities
20000/10000/8000 J/K, areas .04/.02/.04 m² and emissivity .8. Each existing
conductive edge is .4 W/K. Its effective radiative sink is 270 K; prescribed
illuminated solar inputs are 2/1/2 W, albedo .5/.2/.3 W and Earth IR 2/.6/1 W.
These values define a reduced scenario; they are not flight-calibrated values
or a demonstrated spacecraft heat budget. Initial temperatures are 300 K,
battery energy is .8 times retained nameplate Wh, both retentions are one,
and cumulative battery throughput starts at zero. Existing protection and
operating bounds remain authoritative. Failure is a possible valid outcome.

The B53 declaration checks the rate multiplier domain [0.125,8]. Derived
absolute sensitivity limits are retained as exact hexadecimal values in the
parameter rationale, in its declared units. The nested legacy input format
does not admit the optional `SensitivityRange` record, so that optional field
is explicitly None. No legacy codec allowlist or lower physical guard is
expanded; numerical rate values and the B53 study domain remain authoritative.

The thermal equation implemented by the existing thermal owner is
`C_i dT_i/dt = Q_routed_i + Q_prescribed_i + Σ_j G_ij(T_j-T_i)
               - ε_i σ A_i (T_i^4-T_sink_i^4)`.
Prescribed heat excludes internal routed dissipation and EPS/wire losses.
`sink_includes=()` explicitly avoids claiming those prescribed radiation terms
were already included in the effective sink. Electrical PV generation remains
separate from this prescribed thermal environment. No second orientation/area
absorption term is added. A new name does not establish full physical closure.

Ageing remains enabled. Calendar damage at the reference298.15 K is
`1e-10 s^-1 * duration_s`; cycling damage is `1e-5 * throughput_Wh/nameplate_Wh`.
Both use the accepted temperature-acceleration owner with declared activation
energy20000 J/mol. At reference temperature the calendar term alone contributes
0.0002592 retention damage in30 days. This is a units/limiting-case calculation,
not a simulation or life qualification. Solar forcing1e-10/s is applied once by
the existing selected-interval solar owner. Its first-order30-day loss is also
0.0002592, while the actual stepwise multiplicative result follows that owner.
A distinct root with a predeclared positive multiplier .5 or2 supplies rate
sensitivity. Rates must not be revised after observing a failure or disabled
to make the month succeed. Common study latency is explicitly1s; legacy B52's
40s policy and its historical results retain their original identities.

`AcquiredLifecycleWorld.prepare_support_delta(a,b)` reads only already sampled
lighting support. `commit_support_delta` records exactly one contiguous selected
ACTUAL interval; `consume_support` combines these operations. Queries, rejected
trials and forecasts never add durations. Exact rational ILLUMINATED/OCCULTED/
UNRESOLVED totals partition the actual consumed prefix from the original anchor.
Cache eviction cannot erase those cumulative totals. They survive checkpoint
data restoration without orbit, Sun or eclipse evaluation. A forecast fork can
inherit the known actual prefix, labelled as inherited, and cannot extend it.

These durations describe the declared midpoint-sampled, held original lighting
grid. They do not establish continuous eclipse support, event-time accuracy or
the full durations of historical B52 cases whose complete tally was not saved.
Static admission and hash consistency do not prove dynamic reachability.
