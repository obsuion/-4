# Task 05A: explicit MS product and fixed acquisition-to-delivery execution

Task 05A implements one auditable B/G/R/NIR product and a bounded, controller-free
script. It does not select flight hardware, orbit, footprint, a universal GSD or
integration level. Task 04C remains a bounded synthetic numerical study, including
its unresolved C3 criterion and unsupported U input; this task does not expand
that qualification. PAN, hardware comparison, rolling scheduling and full campaign
qualification remain outside this implementation.

## Product and acquisition authority

`ms_product.MSProductSpec` version 1 binds the existing `ImagingRequest` (request,
target and priority), required B/G/R/NIR identities, capture group, exact declared
rectangular region/footprint, acquisition window, maximum sample spacing in two
axes and inclusive integer delivery deadline. Spacing is a declared sampling
proxy, not a derived orbital GSD, optical resolution or reconstructed image quality.

`MSAcquisitionPlan` version 1 declares the actually captured spectral identities
and an explicit capability/provenance rationale. The synthetic example declares an
MS-only instrument/mode assumption. Channel names are not measured bandpasses;
the final hardware study must source actual band identities and supported modes.
No real instrument's ability to switch off PAN or individual bands is inferred.
The existing `simultaneous_pan_and_multispectral` semantics remain unchanged:
the mission path requires explicit MS-only selection and a configuration that
already admits it. Reference nadir swath remains a reference, not a new feasibility
bound. Geography/coverage is explicitly declared, not derived from orbit here.

## Version-1 integer grid convention

For positive width W, length L and spacing sx,sy, `MSGridSizing` persists:

    Nx = ceil(W/sx), Ny = ceil(L/sy)
    stored_bits = Nx * Ny * len(actually_captured_channels) * integer_bits_per_sample

Ceil is evaluated on exact rational representations of the supplied finite built-in
numbers. No binary64 quotient rounding or epsilon chooses the grid boundary.
Cells are anchored at the declared rectangle edge; any partly covered final cell
is charged in full. This cell-cover proxy is not a detector readout model. There
is no compression, packet/file overhead, mosaicking, resampling or image fusion.
All actually captured bands incur storage and transmission, including a fifth band
that adds no fifth required product. Positive counts/bits are bounded to 2**40,
the accepted contact domain; integral bits/sample and channel/config counts match.
The current optical owner supplies one isotropic MS spacing, so both grid axes must
match that configured spacing; the product can declare distinct acceptance limits.

`execute_ms_request` opts into this sizing at record creation, BEFORE whole-record
storage admission. It shares the protected substepped transaction, EPS, thermal,
ageing and commit/rollback owners. It does not modify records after execution.
The continuous optical owner and legacy acquisition paths retain their outputs.
Grid bits are represented losslessly as a float in the unchanged schema-5 record;
the new versioned manifest retains integer counts, convention and inputs.

For W=L=10000 m, sx=sy=6.5 m, four bands and12 bit/sample:
legacy equivalent volume is113609467.4556213 bits; the explicit grid is1539x1539,
113689008 integer bits. Five actual bands require142111260 bits. These are
synthetic verification inputs, not an adopted630 km/6.5 m flight standard.

## Credit and fine delivery time

Successful acquisition creates `MSAcquisitionEvidence`: the actual stored record
plus its plan. Unsuccessful/denied acquisition creates no record or association.
Credit reads actual delivered custody AND completing `RecordService` evidence;
there is no caller-supplied delivered flag. The exact completion is
`contact.start_time_seconds + service.end_offset.fraction`, compared inclusively
to the integer deadline. The schema-5 completing contact remains the original
full interval; its end is not substituted for record completion time.

Records must match request, target, capture group, footprint, acquisition window
and sampling limits. Complementary bands can combine only for exactly the same
acquisition start/duration and declared footprint/group, never across time or
geographic mosaics. The earliest compatible, fully delivered required channel set
earns one product. `MSProductAssessment` is an idempotent ledger projection with
pending/expired/credited status, rejection reasons, credited record identities
and exact Fraction completion. Re-evaluation cannot multiply credit. Request
priority stays owned by `ImagingRequest`; no second reward model is invented.
Storage custody, partial transfer and product credit remain separate authorities.

The pure assessment checks associations; the continuation replay establishes
their causal execution provenance. As with existing bundles, this is content
integrity/reproducibility, not authentication against wholesale experiment replacement.

## Initial attitude, physical time and versioned restart

`InitialAttitudeEvidence` is a declared settled common-frame direction at an
instant, with provenance rationale. It is not a scheduled fictitious observation
or initial image. The first acquisition checks the actual next-view envelope and
existing common-frame slew/settling timing from this direction. It is explicitly
assumed held between fixed-script actions; no new attitude dynamics or slew-energy
model is introduced. After success the actual `ScheduledObservationExecution`
owns prior-pointing history; standby and contacts preserve it.

`MSMissionProgram` version6, `MSMissionMemory` and `MSMissionState` carry one product,
initial checkpoint/attitude/consumed history, fixed ordered MS requests, physical
standby requests and existing `ContactPlan`s. Origin data custody must be empty.
There is no scheduler, retry policy, action selection or controller state machine.
All intervals must be consecutive; gaps require physically executed standby.
Contacts are never invented to advance a clock. A denied acquisition leaves real
standby evolution and no image; a subsequent fixed contact selecting that absent
record remains an atomic unsupported request under the existing contact contract.
Choosing an alternative action after denial belongs to Task05B.

The owner preserves the128 action/history,4096 per-action/contact physical-work
and16384 worst-case program EPS-work bounds. World events and undeclared internal
forcing changes remain unsupported. Existing sampled protection is not a proof
of continuous-time safety. Numeric policy is explicit/content-bound.

The canonical allowlist explicitly pins all new fields. Bundle/canonical versions
remain1, checkpoint schema remains5, B2 remains1/1, and program versions1-5 keep
their semantics. Version6 is an additive program/memory owner; an old decoder
does not know these new types. Existing provenance compatibility checks continue
to reject old-code bundles when the actual source fingerprint differs.
Checkpoint-only restoration cannot restore mission causality. Bundle restore
reconstructs inputs and memories exclusively from JSON, then bounded-replays the
entire prefix and compares the full checkpoint and all causal metadata/credit.
Restart is only at completed actions/contacts, never in the middle of a service.
Schema-5 `MissionState` placeholders are not silently repurposed as the new ledger.

## Executable example and Task05B boundary

`python -B -m examples.v5_ms_mission_demo --output <external-path>` executes:

* acquisition[100,110), starting without onboard/delivered target data;
* physical standby[110,112);
* partial contact[112,152), sending40000000 bits at1000000 bit/s;
* physical standby[152,155);
* completing contact[155,300), then residual transmitter-off idle.

The default four-band record completes at228.689008 s and satisfies deadline229,
although the full contact ends at300. `--stop-after 3 --bundle-output <path>` saves
after partial transmission; `--resume <path> --output <path>` resumes without a
fixture-builder call. The explicit MS power20 W, baseline12 W, transmitter36 W,
thermal/ageing coefficients, declared contacts and level2 are synthetic functional
fixtures. Their numerical accuracy is not claimed as a campaign qualification.

Task05B must add author-approved controller/action-selection semantics, feedback
after denial, multiple requests/queues and campaign identity, environmental change
boundaries, contact/opportunity selection and any interaction with schema-5 mission
placeholders. It should reuse grid/acquisition associations, exact completing-service
evidence and consumed/prior-execution memories rather than infer them from counters.
Task05C must source hardware spectral/mode/load capabilities, orbit and footprint
assumptions, freeze the comparison manifest and error criteria, and qualify the
resulting schedules and numerical/resource/replay costs. Neither task is implemented here.
