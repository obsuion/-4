# Task 05B: bounded multi-request MS rolling campaign

This candidate adds program version 7; accepted versions 1-6 keep their meanings.
It implements the transparent common heuristic permitted by V5_DESIGN_SPEC
sections 6-7 and D016, with the deliberately ideal knowledge experiment permitted
by that specification. D026/D063 separation still applies: physical truth changes
do not silently refresh legacy ground knowledge. No new physical law, hardware
architecture, numerical qualification or Task 05C comparison is introduced.

## Owners and identity

`campaign_contract.MSCampaignProgram` binds the origin schema-5 checkpoint,
actual initial attitude, released MS product definitions, acquisition opportunity
windows/associations, declared serviceable contacts, piecewise forcing,
protection/integration settings, knowledge assumptions and version-1 policy.
`SimulationInputs` supplies the caller's unchanged hardware/configuration/world.
The existing experiment input digest binds both, including all contents and
provenance, not only IDs. Inputs are copied through the existing canonical codec.

`MSCampaignMemory` holds one initial feedback message and immutable decision
events. Each event records the forecast plan, actual accepted-executor outcome
and the explicit received feedback. It does not maintain second mutable custody,
credit, prior-attitude or consumed-contact ledgers. Those are reconstructed from
acknowledged events; product assessments are derived using the accepted Task 05A
owner and actual schema-5 custody plus completing RecordService evidence.

Schema 5 remains authoritative for physical state, stored records, partial bits
and delivered custody. Its historical ground knowledge, MissionState and
ControllerState fields retain their old values/semantics. They are not aliases
for version-7 knowledge, request status or replan counts, and the new planner
does not read them. Diagnostics remain observations. Checkpoint-only restore
cannot restore campaign causality; a version-7 bundle is required.

Bundle/canonical/provenance versions remain 1; B2 remains 1/1. New types have
explicit pinned canonical field schemas. Old artifacts are not migrated and old
code fingerprints do not pass the existing implementation compatibility check.

## Explicit idealized boundary telemetry

The only supported mode is `idealized-boundary-telemetry-v1`: an initial sample
and one sample after each completed physical action/contact. Each entire typed
BoundaryFeedback message declares `sampled_at_seconds` and `received_at_seconds`,
equal to the current integer boundary. All its resource/status fields share
these timestamps. Zero telemetry and command latency, perfect acknowledgements
and exact exposed model values are experimental assumptions, not RF or real
operations claims. No internal integration endpoint refreshes ground knowledge.

Exposed fields are exactly:

* Battery energy (Wh), usable-capacity retention, solar generation retention,
  cumulative battery throughput (Wh), and the explicitly selected node
  temperatures (K), with node identities.
* Activity mode, FDIR state and critical-energy start timestamp, needed by the
  accepted protected forecast executor.
* Acknowledged onboard acquisition records and partial-transfer bit counts.
* Acknowledged actual action kind and protection reasons; the new acquisition
  association, if successful; original completed contact and its RecordServices.

RecordServices carry exact offsets and bits. Ground receipt knowledge enters
only through this acknowledgement at contact END, even when the actual record
completed earlier inside the contact. Assessment compares the accepted exact
service-completion Fraction with the inclusive product deadline. It does not
replace physical completion with acknowledgement time or contact end.

Every model thermal node must have either an explicit observation or a declared
constant boundary estimate; the two sets are disjoint. An unobserved estimate is
reset at each real decision boundary, then evolved by the accepted thermal model
inside that forecast. The normal example observes all temperatures. The denial
fixture explicitly estimates the unobserved payload at 300 K while actual initial
truth is 330 K. Its predictive error creates an actual protected denial.

Planning reconstruction uses only these received values, immutable inputs and
declared estimates. No live SimulationContext, complete checkpoint, diagnostics,
origin truth, scoring ledger or future execution result is passed to the planner.
Unused propulsion delta-v is explicitly estimated as zero in isolated planning
state; authority, old knowledge/mission fields and counters are empty local
placeholders. None influences the supported imaging/contact/standby forecasts.
Actual attitude starts from supplied InitialAttitudeEvidence; held pointing is
the existing explicit assumption. Successful acquisition acknowledgements supply
subsequent prior execution and timing, using the accepted ADCS transition owner.

## Exact common policy

One version-1 policy applies to all caller-supplied configurations, without
configuration-name branches or architecture-specific tuning:

1. Rank released requests by descending priority weight, ascending delivery
   deadline, then exact stable request ID.
2. At the ORIGINAL contact start, try acknowledged, still-useful onboard backlog,
   ordered by request rank then record ID. Prefer this contact if its isolated
   physical forecast transmits data. Consumed contacts never re-enter selection.
3. Otherwise take the highest-ranked physically feasible full acquisition.
   Equivalent opportunities use window start then stable opportunity identity.
   One compatible full-band acquisition suffices per request, so it is not
   acquired again while waiting for delivery. An actually denied opportunity
   is not retried; another declared opportunity can be considered later.
4. Otherwise physically wait to the next known opportunity/contact/forcing,
   attitude-readiness/deadline boundary or the bounded standby poll/horizon.

Rejection reasons describe the actual selection boundary; the forecast suffix
records its own action-selection reasons. The planner evolves an isolated
battery/thermal/storage/timing state for several
actions up to its lookahead/action/work limits. It uses the accepted MS and atomic
contact executors, including protection forecasts. Only the first action executes
on truth. Its feedback crosses the boundary; the entire plan is rebuilt. This is
not an input action script. Onboard protection independently checks actual state;
a denied imaging request evolves accepted physical standby for its FULL duration.

The adapter releases request contents only at a real received boundary with
release time <= now. The forecast uses that fixed released set, even for later
projected actions. Future request contents and release clocks cannot steer an
earlier plan. A request released during imaging/contact/standby becomes actionable
at the next decision boundary. Bounded standby polling handles unknown arrivals.

The capacity screen sums declared, nonoverlapping contact rate-times-duration
inside lookahead and before the deadline, after the proposed acquisition. It
subtracts ALL already queued remaining bits, even lower-priority/expired backlog.
Insufficiency when the deadline is beyond forecast visibility is UNKNOWN and
does not reject the acquisition. When visibility covers the deadline it screens
the candidate under this conservative backlog approximation. This is not a proof
of physical deliverability or global impossibility: protection, later arrivals,
contact preemption and model estimates can alter the result. There is no optimum
or guaranteed-delivery claim. Already expired records remain stored, with no
automatic deletion policy; they cease to be useful downlink selections.

## Physical boundaries and bounded work

CampaignForcing intervals consecutively cover the entire common horizon. Standby
ends at forcing boundaries. An acquisition crossing a boundary is screened, never
shortened. A declared contact crossing a boundary rejects the campaign input;
contacts cannot be truncated, entered late, overlapped or resumed internally.
All other gaps execute positive-duration standby. Whole-segment solar retention
loss, when supplied, is explicitly uniformly apportioned by exact duration ratio
then rounded once for the accepted input; positive underflow rejects.

At most 16 requests, 64 opportunities, 64 nonoverlapping contacts and 64 forcing
intervals are admitted. Policy bounds: 2-8 forecast actions, <=128 candidate
physical evaluations per decision, <=16384 forecast EPS evaluations per decision,
and <=128 completed decisions. Program admission additionally limits the product
of decision count and forecast-work budget to 131072, worst-case actual execution
to 16384 EPS evaluations, and per-contact physical work to 4096. A validation
replay therefore has a declared finite work bound. Repeated public advances and
bundle validation replay prefixes, so wall cost exceeds execution alone.

Budget exhaustion raises CampaignBudgetExceeded without committing a new boundary;
the runner reports incomplete and exits 2. Reaching an arbitrary action count is
not campaign completion. Only physical arrival at the common horizon earns
`completed-horizon`, regardless of product success. Numerical failures propagate
explicitly; sampled protection is not a continuous-time safety proof.

## Restart, outputs and demonstration

Restore reconstructs every input/memory from JSON, replays the bounded prefix,
rebuilds every plan/acknowledgement and compares the entire checkpoint and causal
memory. Correctly rehashed false telemetry, plans, services or histories still
reject. This provides content integrity/reproducibility, not authentication.

`python -B -m examples.v5_ms_campaign_demo --output <external.json>` uses the
accepted synthetic Task 05A hardware fixture: requests a/b/c have competing
windows, priorities 3/2/1 and deadlines 300/320/360 s; c is released at 125 s.
The policy chooses acquisitions [100,110), [110,120), waits to 140, uses contact
[140,180), acquires c at [180,190), waits to 200, uses [200,360), then physically
waits to horizon 380. First-contact transmission is 40000000 bits of a's
113689008-bit record. Its completion is 273.689008 s; b and c follow in rank order.
The default integration level is 0 (one internal subdivision per physical
segment), a declared functional fixture setting without an accuracy claim.

`--stop-after 4 --bundle-output <external-bundle.json>` saves a completed contact
with a partial record. `--resume <external-bundle.json> --output <external.json>`
continues without rebuilding the fixture. `--denial` selects the explicit thermal
estimate-error fixture. JSON includes selected/forecast actions, reasons,
sample/receipt timestamps, acquisition IDs/integer bits, exact completion,
deadline result, partial/late/expired status and separate acquired/delivered/on-time
counts. Example wall duration includes validation/replay and optional bundling;
it is reported only as execution evidence, never a performance benchmark.

`campaign_from_manifest(inputs, program)` is the parameterized Task 05C seam.
The caller supplies prepared hardware and either baseline or reduced declared
contacts with the same requests. This task neither invents the hardware manifest
nor runs or qualifies those future comparison campaigns. Orbit/environment
generation, real communications delays/uncertainty, collision/stationkeeping,
optimization, deletion, mosaics, mid-contact restart, unsupported world events
and campaign-wide numerical qualification remain outside this candidate.
