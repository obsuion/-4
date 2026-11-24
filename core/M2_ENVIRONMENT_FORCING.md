# M2-B39: conditional illumination to nominal EPS/thermal forcing

B39 is an additive opt-in adapter and pure transition consumer on accepted B38.
It does not change the engine, mission executors, checkpoints, registries,
propagators, arithmetic or scientific resource ledgers. M2 is not complete.

## Public contract and trust boundary

`environment_forcing.EnvironmentForcingRequest` owns an input-only B38 request
binding, exact Fraction start/end, declared thermal node IDs, a piecewise-constant
profile and independent `ForcingPolicy`. `adapt_environment_forcing(source,
request)` accepts only a completed typed B38 result with classified,
resolution_reached or complete budget_exhausted status and no failed ledger.
It checks input/authority identities, the entire original-domain partition,
windows/supports, rooted boundary/step/trial ancestry and whole support domains
before constructing any schedule. This is structural validation of trusted
in-process owner evidence; manually fabricated Python objects are not
cryptographically authenticated or numerically re-proved. A result must come
from the actual owner in real use. Documents cannot load a result certificate.

All times remain exact simulation-relative Fractions referenced to the original
TT/frame/orbit authority in the nested B38 request. There is no midpoint reset,
new propagation or certificate tightening. Schedule cells use the sorted union
of illumination and profile boundaries. A split retains a reference to the
entire original geometry support and original ancestry, with CLOSED geometry
support and LEFT_CLOSED_RIGHT_OPEN_FINAL_END_INCLUDED partition conventions.
At a shared boundary the right-hand partition piece applies; the source's final
end is included. A zero-length request produces one supported boundary cell and
zero physical calls/energy. A clipped subinterval is not a new orbital solution.

Own limits: at most128 profile entries,64 distinct thermal nodes,8192 forcing
cells and16384 total source pieces/windows/boundaries/steps/geometry/trials.
Smaller caller limits may refuse admission. This is bounded adapter bookkeeping,
not a CPU promise, arithmetic prepayment or extension of B38 proof budgets.
The physical consumer admits at most64 nodes and2016 links before legacy network validation.
Physical durations use existing RationalSeconds.from_fraction/checked_duration;
non-dyadic positive fractions are supported, and existing rational domain limits
remain authoritative. For integer cells the existing integer interval APIs are
used; otherwise the existing rational substep APIs are used. Boundary ownership
never depends on rounded floating clocks. Kernels retain their existing one-time
binary64 duration conversion and nominal Euler thermal integration.

## Supplied physical inputs and heat ownership

Each profile supplies panel incidence in degrees[0,180], electrical component
loads in W, effective sink temperatures in K, and internal/direct-solar/albedo/
Earth-IR absorbed powers in W per exact configured node set. All radiative and
internal powers are nonnegative finite built-in numbers; sinks are positive.
ILLUMINATED supplies sunlit=True and caller illuminated solar heat. OCCULTED
supplies sunlit=False and zero direct solar heat only. Albedo, Earth IR, internal
heat and effective sinks are independently supplied and retained in eclipse.
No inertial-Sun-to-panel orientation, attitude controller or flight calibration
is inferred. Nominal generation capability belongs to caller EPS configuration
or an existing supplied EPSCapabilityResult.

The caller explicitly declares which radiative sources are already in its sink.
A nonzero explicit matching source is rejected. A required non-overlap assumption
records the caller's remaining modelling claim; undeclared double counting
cannot be detected. Internal dissipation cannot declare included EPS conversion
loss: thermal_coupling already owns conversion_loss_wh*3600/duration exactly once,
assigned to its configured battery node. Load is bus demand, not automatically
internal heat; configurations and caller provenance retain their existing owners.

UNRESOLVED is retained with two sunlit/dark input cases. These are not certified
battery/temperature extremes or trajectory bounds. No branch tree is solved.

## Physical execution and publication

`environment_physics.compute_environment_transition(source, request,
battery_state, eps_config, thermal_state, thermal_config, capability=None)` first
builds and preflights the whole schedule and validates physical node/config/state
compatibility. Any positive-measure unresolved cell returns status unresolved,
source regions and input alternatives, with final_proposal=None and trajectory=None.
A wholly certified requested subinterval remains executable even if uncertainty
exists elsewhere in the original domain.

The certified path calls existing eps_system.compute_eps_interval_transition or
compute_eps_substep_transition, then thermal_coupling.compute_eps_thermal_interval_transition
or compute_eps_thermal_substep_transition, with matching exact durations. Fresh
BatteryState/ThermalState proposals are constructed from the actual end-energy
and end-temperature fields. Caller states and contexts are never modified.
The immutable final proposal can explicitly create fresh existing states through
`to_states()`. Late primitive failure returns physical_failure, failed cell and
separate diagnostic_prefix only; no accepted final state or partial trajectory
is published. Invalid static inputs raise before execution.

These proposals are nominal physics, not a mission power grant, protection
acceptance, degradation evolution, thermal error enclosure or physical accuracy
certificate. Existing SimulationEngine.step accepts explicit EPS/thermal/heat
inputs, but B39 does not register an automatic provider or claim old
WORLD_ENVIRONMENT dispatch performs M2 environmental evaluation. Mission-action
binding and persistence/restart integration are later work.

## Input-only persistence

`environment_forcing_document` format M2_ENVIRONMENT_FORCING_REQUEST version1
contains only forcing inputs and the nested accepted B38 input-only document.
Strict complete field sets, duplicate-key rejection, finite profile/node/count
limits,8MiB UTF-8 text limit,64 levels,262144 tree nodes and canonical rational
strings precede the nested physical input decoder. No arbitrary class/import/
hook names, derived illumination results, physical trajectories or checkpoints
are accepted. Loading performs no B38 evaluation/executor invocation; scientific
recomputation requires an explicit owner call. Files are created exclusively and
never overwrite earlier inputs. Input digest and exact schedule coverage ID are
identities, not proofs of flight truth.

## Verification and demonstrations

Tests use labelled trusted synthetic typed partitions, with no fresh B38 public
entries. They exercise support splitting, exact non-dyadic time, boundaries,
uncertainty, whole-source rejection, missing/duplicate/foreign nodes, convention
conflicts, hostile wire fields before decode, caller-state preservation and atomic
late physical overflow. Independent constant-rate reference: for ideal battery,
E_end=E_start+(P_gen-P_load)*dt/3600 Wh. For an isolated nonradiating1000J/K node,
T_end=T_start+Q*dt/1000 K. These are elementary derivations under the explicitly
supplied demonstration model, not general mission equations. Binary64 reference
comparisons allow at most2 final-value ULPs for existing duration/product/division/
addition rounding; primitive compatibility on identical segments is exact.

The example CLI makes exactly two bounded real B38 entries (certified light and
eclipse), then feeds them to the physical consumer. It additionally labels a
synthetic mixed partition with an internal breakpoint and an unresolved refusal;
a finite supplied late heat overflow demonstrates atomic failure. The synthetic
partitions do not prove orbital accuracy. A separate successful fresh-process
offline replay compares complete canonical outputs. Source-bound commands,
actual counts, failures and selected regression results live in the review ZIP.
B38's426 author tests and independently reported reviewer probes are historical,
not new B39 validation. No H5/day campaign is run here.

## Remaining scope

Conditional illumination remains conditional on the original J2/Sun/frame
assumptions; incidence/heating remain caller assumptions. Combined qualification
UNRESOLVED; H5v2 refinement and Family B open; historical B7 cause UNKNOWN.
Target/station adapters, persistent environment-to-mission/checkpoint bindings
remain M2 work. Assembly-derived inertia/mounts and orientation/actions remain
M3 work. This patch does not complete M2, M3 or the full simulator.
