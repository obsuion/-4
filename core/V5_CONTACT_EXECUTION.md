# Task 04B: exact-time ordered contact execution

This explicit research path extends Task 04A without reinterpreting historical
single-record APIs or continuation versions 1-4. D094/D095 explicit Euler and
explicit numerical failures remain; D150/D285 qualification is still open.

## Contact, service and time ownership

`contact_execution.execute_contact_plan(context, plan, *, consumed_contacts,
policy, integration)` executes one already admitted `ServiceableGroundContact`.
`ContactPlan` supplies its ORIGINAL identity/interval, an explicit ordered tuple
of onboard record IDs, `CoupledDownlinkInputs`, `StandbyInputs`, and pinned
`integer-bits-rate-rational-segments-v1` semantics. No selection heuristic,
partial-record priority, controller, retry or new serviceability inference exists.
Contact start must equal the completed integer clock; end must be within horizon.

ALL selected records, including those beyond capacity, are validated before
physics: unique, currently onboard, not delivered, acquisition completed by
contact start, valid partial progress. Malformed plans raise without mutation.
An empty sequence is valid TX-off physical idle. Each service is
`bits=min(total-before, remaining_capacity)` and duration is exactly `bits/R`.
Multiple partial records follow the requested order without reordering.

Exactly integral stored bits, selected partial bits and nominal bitrate are
required. Existing integer-valued built-in floats are admitted without rounding;
nonintegral values are rejected. Selected record totals, rate and R*D are bounded
by 2**40, and at most 32 records are selected. These are explicit resource and
representability bounds, not spacecraft calibration or numerical qualification.

Task 04B-R1 validates the ORIGINAL nominal-rate parameter value before the legacy
capacity owner's float conversion: only positive built-in int or exactly integral
finite built-in float values within the bound are supported. Fraction values,
including integral Fraction, and other scalar types are unsupported. The legacy
proposal must then agree with the independently validated integer rate and exact
R*D. ScalarParameter, the codec and historical communications APIs are unchanged.

`RationalSeconds(numerator, denominator)` adds a canonical reduced exact time
token: built-in integers, numerator 0..2**96, denominator 1..2**64, value <=2**40 s.
Zero is an offset only; physical kernels require positive duration. Existing
`IntegrationPolicy(k)` chooses N=2**k subintervals per physical service/idle
segment. Each kernel receives one correctly rounded binary64 duration for its
existing equations. That approximation never owns service boundaries or bits.
Public absolute clocks remain integers.

All contact samples share denominator R*N. Exact offset numerators are
`start_bits*N + i*segment_bits`, bounded by 2**52. There is no accumulated
floating timestamp, outward rounding or adjustment of rate/data to fit a grid.
`sum(served_bits)=R*TX_on_seconds` and `TX_on_seconds+idle_seconds=D` hold exactly.
Work admission requires `(selected_count+1)*N<=4096` per contact. Programs admit
128 historical contacts and 16384 worst-case EPS evaluations, including standby
and TX proposals. Limits reject before mutation; they never imply convergence.

## Physics, protection and atomicity

ON/OFF inputs share explicit baseline loads, sunlit/incidence, routing, thermal
boundaries, external heat and solar forcing. Idle has zero payload/TX/propulsion
demand. Unsupported world events or within-contact environmental changes reject.
Solar retention_loss is a whole-contact loss distributed by exact subinterval
duration fraction, converted once to binary64; positive underflow rejects.

TX is on only during accepted record service, with no gap between immediately
successive records. After exhaustion or denial it is off for ALL remaining time.
Residual idle integrates baseline electrical demand, heat, temperatures, ageing
and reconciliation; no residual time is free, skipped or integrated twice.

Task 04A and 04B share `_physical_substep` and `_validate_physical_samples` in
`substepped_execution`. EPS, routing, thermal, degradation and engine completion
remain the equation owners. Capability evolves every subinterval; there is no
macro double-ageing or reconciliation heat. R1 exact allocation limits remain.

Each TX segment uses the current state produced by earlier accepted segments.
It calculates refined TX and required standby proposals under the accepted
03B/04A policy, checking initial/all calculated endpoints. A deficient mission
prediction stops before unsupported partial mission heat. A denied record gains
no bits: earlier successful services remain private, and residual idle starts
from the state BEFORE the denied segment. There is no mid-record retry or
partial data credit on operational denial. Predictions and actual observations
remain separate; sampled protection is not continuous-time safety.

Internal boundaries create no ground decisions or knowledge refresh. Recovery
and final NORMAL/BACKUP/activity state are recorded once for the outer action.
critical_energy_since_seconds denotes the integer outer boundary owning an
essential deficit, not a fabricated fractional threshold crossing.

Segments execute on isolated state. Data services are accumulated privately,
then applied after physical segments succeed. Result/checkpoint validation
precedes one external commit. Late exceptions roll back the WHOLE contact,
including earlier proposed service. Clock reaches the original integer contact
end; completed_steps increments once. Numerical/segment/proposal work is separate.
Contact ActionAccounting is fsum of selected segment ledgers (Wh/dimensionless
damage/integer work), checked against those ledgers. No power-admission slack
is introduced to obtain aggregate equality.

## Completion, custody and causal restart

RecordService stores before/served/after integer bits, exact offsets, completion
and public integer completion time `contact_start+ceil(exact_end_offset)`.
Integer completion stays exact; fractional completion is never reported early.
Partial records release no allocation. Completion credits a record and releases
its full allocation exactly once.

Schema 5 CompletedAcquisitionDelivery has no independent timestamp: it retains
the ORIGINAL completing contact. Its end remains the historical conservative
contact-end bound, NOT the new exact record completion time. No shortened contact
with a reused identity is fabricated. Typed version-5 outcomes own finer timing;
existing schema-5 storage/progress/completed delivery remain custody authorities.

ConsumedContacts is immutable typed causal memory of original contact identities
and intervals, including empty/denied contacts. IDs cannot repeat and intervals
cannot overlap. It is required by the executor and returned updated; it is not
Diagnostics or inferred from deliveries. Supported continuation must retain it.
Discarding it while restoring only schema 5 is not a version-5 continuation.

ContactProgram/ContactMemory/ContactState/advance_contact_continuation define
explicit version 5. Origin checkpoint, prior acquisition, initial consumed
history, ordered plans, forcing, protection, numerical and exact-time policies
are content-bound. Actual outcomes and consumed memory persist; bounded replay
checks them and the ENTIRE checkpoint, including reencoded false history.
Versions 1-4, bundle/canonical/provenance 1, checkpoint schema 5 and B2 1/1 remain.
Restart is only at completed contacts. Same-policy fresh-process JSON restoration
requires exact state/data/history/clock/metrics equality. Changed policy changes
identity. Bundles provide integrity/reproducibility, not authentication.

## Independent references and limits

The synthetic example has 3 bit/s, initially partial records and three contacts.
First contact serves 6+8+4 bits in 6 s, then idles 4 s. Its second completion is
at exact offset 14/3 s (conservative absolute timestamp 105 s from origin 100 s).
With baseline 12 W, TX 36 W, zero generation and discharge efficiency 4/5:
demand `(48*6+12*4)/3600=7/75 Wh`; extraction/throughput `7/60 Wh`; conversion
loss `7/300 Wh`. Isolated nonradiating node references use literal heat balances.
All coefficients are synthetic assumptions, not KazEOSat calibration.

Short electrical balances allow 64 reference ULPs, energy endpoints 16 ULPs at
80 Wh, isolated temperatures 32 ULPs at 300 K. These cover arithmetic only.
A separate conductive example demonstrates changed coarse/refined admission
and compares prediction with the closed ODE using a Kelvin integration bound.
Exact bit/time/restart comparisons do not use those numerical tolerances.

Task 04C still owns campaign ranges, nonlinear/stiff stability/accuracy and
method/refinement adequacy. Task 05/controller, prioritization, mid-contact
restart, J2/propulsion and permanent damage are not implemented.
