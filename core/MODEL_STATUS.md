# Model status

## Current Task 05F-A continuous trade readiness candidate (pending independent review)

The accepted Task05E baseline is a80f34c46e1392efece190d3be5287d99a0bc6be
on v5-redesign, parent 2f17716bb82e0ae84b9c72a21f2d16ba692f1dc6.
Its 7502-pass regression and 64-case study are historical evidence for the
accepted bytes, not validation of this new candidate.

Task05F-A adds a separate versioned periodic coordinator with a real 2592000 s
world horizon, published per-cycle requests, paid forecast/actual maneuvers,
integer acquisition and delivery, retained custody, streamed evidence and
source/runtime-bound schema-5 continuation without historical execution replay.
The accepted physical, protection, MS and contact owners remain authoritative.
The shared profile owner gains optional exact forcing breakpoints; its default
partition, bounded 4096-substep limit and archived 05E semantics are preserved.
See V5_CONTINUOUS_TRADE.md for the frozen pre-score assumptions and limits.

The primary hardware pair is B8-A2/B4-A4 at 50 percent working capacity.
Regular demand is primary, with a fixed synthetic 5400 s light/shadow cycle,
six 60 s images and a declared adequate contact. The independent pre-score
budget predicts an energy deficit for B8-A2 and possible charging thermal
protection for B4-A4. These are analytical screens, not mission results or
flight-calibrated performance. Burst remains an optional timing stress case.

Validation: the focused/adjacent gate passed 281 tests in 119.51 s. The single
frozen-candidate full regression passed 7616 tests in 843.40 s, with zero skipped,
failed or errored tests and exit 0. All 358 source snapshot files were unchanged
during the gate; this validation-reporting update followed it. Checks include
partial-custody fresh-process continuation, physical discontinuities, forecast
isolation and independent energy/bit conservation.

Both nominal/finer 24-hour pilot pairs completed and passed the predeclared
numerical screens. B8-A2 credited 96/96 products and B4-A4 92/96 under both
policies. The eligible continuous B8-A2 extension reached 72 hours with 288/288
credited products, but ended at zero battery energy with 1.5514694889949563 Wh
unmet load and two actual hold denials. This is not sustained-safe-operation
evidence. Fresh-process continuation across a saved 48-hour boundary matched
the uninterrupted checkpoint and 1188 event records exactly under the same
source/runtime and action partition. Retained-history execution cost grew;
the measured scaling projections do not fit the required qualified month pair
within the allocated work budget. No month production campaign was run.

Changes remain unstaged and uncommitted, pending independent review. Accepted
05E remains the article baseline; these are preliminary engineering pilots.
Full V5, J2 temporal visibility and long-horizon qualification remain open.
A readiness pilot is not the month comparison or hardware-life validation.

## Historical Task 06B J2 input binding candidate (subsequently accepted and committed)

Task06A was independently accepted and committed at
ff4e26c305ece6cd9ee2d117da1d1ab31f03aee5, parent
f907dacdf85401904fe805cb9d153a88f218f4a6, on v5-redesign. Its 7170-pass full
regression is historical evidence. The 67 Linux tests, nine probe groups and
six pilot reproductions are external independent review, not Task06B runs.

Task06B adds a frozen complete J2 coast/policy input owner in the existing
keyword-only coast_orbit slot, a separate versioned content-derived identity,
strict portable typed definitions and an explicit nonmutating F3 context query.
Schema-5 checkpoints use matching external inputs; self-contained bundles
reconstruct the same graph without an origin fixture. No propagated state or
saved enclosure result becomes authoritative. See V5_J2_BINDING.md and D320.

The original anchor is preserved; simulation clock seconds are relative to the
declared TT epoch. The small version-1 script demonstrates save at 146 s and
fresh-process continuation to 238 s, with original anchor 128 s. It retains
legacy downlink execution semantics and declared observations/contacts; it is
not a J2-driven campaign or proof of physical contact serviceability.

Validation: the focused/adjacent gate passed 1076 tests, including all 120 new
F4 checks, in 46.92 s, exit 0, with executable/test hashes unchanged. Both
fresh-process restore routes match uninterrupted continuation exactly. Four
standalone demo processes also exited 0: save at 146 s, continue to 238 s,
six completed actions, 24000 delivered equivalent bits, no remaining records
or partial transfer. Recomputed F3 at 238 s is enclosed; original anchor is
128 s. This demonstrates deterministic persistence only. The retained first
development run had 111 passes and five fixture errors (inconsistent paired
epochs and an incorrect version attribute); corrected fixtures preserve the
accepted owner contracts. The single final full regression passed 7290 tests,
0 failed/errors/skipped, exit 0, in 883.70 s (runner wall 885.04 s). All 327
candidate raw file hashes matched before/after. Existing .venv, python -B,
PYTHONDONTWRITEBYTECODE=1, disabled pytest cache and external basetemp/log/XML
were used. Afterward only this validation paragraph changed; executable,
test, example and contract/decision bytes remain bound to that full run.

Baseline was clean at the accepted HEAD/tree with an empty index and 41 tag
mappings including peeled targets. The available ignored-file inventories
agree when counted on the same scope: 1590 outside .venv, plus 6278 inside,
equals 7868 total. Existing ignored files are preserved; the earlier unlabeled
05C failure cause remains unestablished. F1/F2/F3 and S008 stay byte-identical;
schema 5, B2 1/1/fixed digest, canonical/bundle 1 and program 1-7 semantics remain.
J2 temporal visibility, Family B interval viewing, long-horizon qualification,
maneuvers and full V5 remain open. Changes are unstaged and uncommitted.

## Historical Task 06A accumulated J2 error candidate (subsequently accepted and committed)

Task05C was subsequently accepted and committed at
f907dacdf85401904fe805cb9d153a88f218f4a6, parent
6067fd13893a71ad468bb49c4ef7bf643efbdacd, on v5-redesign. Its 7103-pass
regression and 216-case campaign remain historical evidence; they were not rerun
to start this task. The independent review probes/Linux run are external evidence.
The original candidate report below is retained as historical text.

Task06A adds orbit_j2_enclosure.py, a focused test module, a small reproducible
pilot and V5_J2_ENCLOSURE.md, with D319 and one bounded S008 addition. Complete
original state/frame/TT/gravity and both solver policies bind each recomputed
result. Directed Decimal Taylor boxes, checked continuous Picard tubes and
endpoint distance to the exact unchanged F2 output provide separate position
and velocity infinity-norm bounds, or explicit unresolved/no-bound results.
See the derivation for the admitted domain, arithmetic assumptions, local defect
accumulation and wrapping limitations. No formal machine-checked proof is claimed.

The six-case pilot completed successfully. The assumed inclined LEO-scale case
at 600 s with 10 s steps reports 3.6919105529499417e-4 m and
5.990285321152896e-7 m/s bounds in 1.1291 s; 5 s steps report
2.2990218749689134e-5 m and 3.736394667562831e-8 m/s in 2.3385 s. These are short-arc
numerical results under a synthetic force specification, not hardware/flight
accuracy or a qualified visibility tolerance. Initial failed tube-search evidence
is retained externally; the search was corrected without relaxing inclusion.

Validation: the focused and adjacent A/B1/B2/F1/F2 gate passed 1477 tests,
including all 67 new enclosure checks, exit 0, in 61.68 s. Source hashes were
unchanged during that gate. The single final full repository regression passed
7170 tests, 0 failed/errors/skipped, exit 0, in 764.30 s (runner wall 765.56 s).
All 322 candidate raw file hashes matched before/after. Python 3.14.7 / pytest
9.1.1 used the existing .venv, python -B, disabled bytecode/cache, external
basetemp/log/XML and legacy JUnit metadata. Afterward only this validation text
and D319's heading encoding changed; production, tests, example, derivation and
S008 remain byte-identical to the full-suite candidate. No campaign rerun occurred.
A retained collection error was caused by pytest attempting to generate an ID
from the hostile-text test fixture; explicit test IDs corrected collection.
The accepted 7103-pass result must not be attributed to this new implementation.

Baseline integrity matched the accepted Task05C archive/source hashes and all
41 tag mappings. The retrieved 05C failure was the ignored-file set assertion
at stdin line 25; its log contained no differing names, so its cause is not
established. The immediate diagnostic and full labeled recheck both passed;
this task also found no source/tag/ignored-file discrepancy before editing.
Raw historical failure/recheck events are retained in the external evidence.

F3's bounded accumulated endpoint error obligation is implemented for review.
F4 content binding/persistence and later J2 continuous visibility integration
remain open, as does Family B's interval-view/end-ray correction. F1/F2 public
behavior and bytes, schema 5, B2 1/1/fixed digest, programs 1-7 and accepted
MS/controller/comparison semantics remain unchanged. No orbit-driven MS campaign,
maneuver or full-V5 completion is claimed. Changes are unstaged and uncommitted.

## Historical Task 05C candidate report (subsequently accepted and committed)

Task05C adds source-traceable counterfactual D/H/J instrument families and four
BP8/TSP allocations, a fresh shared prescribed workload, and external experiment
orchestration/reporting around the accepted version-7 controller and protected
physical executors. No accepted controller, MS-credit, checkpoint or physical-owner
semantics change. All twelve hardware definitions are explicit. Published source
power and assumed mutually exclusive mode proxies remain distinct; the proxies
are neither calibrated nor demonstrated conservative bounds. See
`V5_MS_COMPARISON.md` for source locations, normalization, assumptions and Methods.

The protocol was frozen after corrected common-window pilots at levels 0/1/2,
selecting all twelve hardware configurations before main rankings. All 216 planned
cases completed with exit 0: 144 rolling cases (two scenarios, two mode factors,
three levels) and 72 nominal fixed requested sequences. Six matching adjusted
pilots and three earlier fixed cases were explicitly reused; no hardware was
omitted, and no planned case failed or remains missing. Original exploratory
pilots and development failures remain external.

All 72 finest-pair engineering screens passed: maximum battery discrepancy
4.547473508864641e-13 Wh and corresponding-node temperature discrepancy
0.0013901868808829931 K. Per-request credit, exact completion times, requested
actions, actual protected segments and record services agree. These are bounded
study results, not a general convergence or flight-accuracy claim. A real
D-E1/S1/level2 partial-transfer boundary at 910 s was restored in a fresh process;
checkpoint, decisions, custody, complete physical samples and product outcomes
match uninterrupted execution exactly.

Nominal S1/S2 weighted delivery scores are D-E1..E4: 2/3 and 1/4;
H-E1..E3: 1 and 11/12; J-E1..E3: 1 and 1; H-E4 and J-E4: 1/2 in both.
Halving the assumed mode increments removes the E4 delivery deficit within each
family; other scores are unchanged. The recorded dark-acquisition forecast
rejections support the conditional power-limit explanation. No ranking reversal
was manufactured. Storage, swath and energy exhaustion are inactive in this
workload; it does not establish energy-optimal EPS sizing. Exact request metrics,
source/assumption ledgers, numerical evidence, three PDF/PNG figure pairs and a
reviewer-response matrix are in the external review archive.

Validation: focused adjacent regression 77 passed (exit 0), followed by 30 Task05C
checks after strengthening numeric-vector identity independently of labels. The
single final complete repository run passed 7103 tests, 0 failures/errors/skips,
exit 0; all candidate raw file hashes matched before/after. Its 19 warnings are
existing J2 record_property/JUnit xunit2 notices. Python 3.14.7 / pytest 9.1.1,
existing .venv, python -B, disabled bytecode/cache and external basetemp/log/XML
were used. Observed wall duration 5522.65 s includes a long execution hiatus and
shared-host work; it is not a performance benchmark. Subsequent changes are only
reporting in this file and V5_MS_COMPARISON.md. The accepted 05B result of 7073
passed remains historical; its separate 18-check review is external evidence.

This uncommitted candidate starts at accepted Task05B commit
6067fd13893a71ad468bb49c4ef7bf643efbdacd on v5-redesign. Full-V5 orbital integration,
OBC, delayed command/telemetry and reliability requirements remain on the roadmap.
No flight telemetry, numerical cross-simulator benchmark, radiometric quality,
general scheduling optimality or full-model completion is claimed.

## Historical Task 05B candidate report (subsequently accepted and committed)

Task 05B adds version-7 multi-request MS campaign continuation and one version-1
deterministic resource-aware rolling policy. Its explicitly named idealized
boundary-telemetry mode separates received planning knowledge from physical truth
and onboard protection, declares sample/receipt times and optional temperature
estimates, and acknowledges actual acquisition/contact results. Forecasts use
isolated accepted physical executors; only their first selected action executes.
Request releases, full atomic contacts, forcing boundaries, physical standby,
denial feedback and work limits are explicit. No action script controls selection.

Schema 5, B2 1/1, accepted program versions 1-6 and canonical/bundle/provenance 1
retain their contracts. New immutable decision/feedback events own campaign
causality; release sets, prior attitude, consumed contacts and product assessment
are derived, with bounded replay validation of checkpoint and every decision.
Legacy ground knowledge and mission/controller placeholders keep their semantics.
See `V5_MS_CAMPAIGN.md` and `examples/v5_ms_campaign_demo.py`.

The synthetic example reuses the Task 05A hardware fixture with three competing
requests, partial transmission over two contacts and a final physical horizon
of 380 s. A separate explicit unobserved-temperature estimate fixture produces
an actual denial followed by full-duration standby and replanning. Integer bits,
exact completing RecordService evidence and inclusive deadline credit retain
their accepted owners. Task 05C hardware manifests/scenarios, flight validation
and campaign-wide numerical qualification remain outside this candidate.

Validation completed: the focused campaign/MS/contact/codec/protection/restart
regression passed 426 tests (exit 0); two additional forcing-boundary checks
passed (exit 0). The single final full repository run passed 7073 tests,
0 failed/errors/skipped, exit 0, in 751.61 s, including all 47 new campaign cases.
Its 19 warnings concern existing J2 record_property/JUnit xunit2 metadata.
Python 3.14.7 / pytest 9.1.1 used the existing .venv, python -B, disabled bytecode
and pytest cache, with external logs/JUnit/basetemp. All 309 candidate raw file
hashes matched before/after the full run; only this validation text changed later.
The accepted Task 05A 7026-pass result remains historical evidence.

Retained development runs: 21 passed/1 failed (test expected nine decisions,
actual correct trace has eight), then 42 passed/1 failed (test expected an
unreduced representation of the correct exact completion Fraction). Both
expectations were corrected; failures were not skipped or suppressed.
Final continuous, partial-save, fresh-process resume and denial CLI commands all
exited 0. Continuous and resumed decisions/checkpoint/custody/metrics match exactly,
excluding measured wall duration. The normal example completed three products
on time in eight decisions; its measured example duration was about 15.09 s,
including validation/replay, not a benchmark. The explicit estimate-error fixture
completed the horizon with 13 decisions and no products, demonstrating actual
denial/physical standby/replanning without fabricated success.

The starting branch is v5-redesign at accepted Task 05A commit
83076fe40eb3f2936dcdc546e8c338cf14c68696. This candidate remains unstaged and
uncommitted for independent review; no release tag or comparison campaign is made.

## Historical Task 05A candidate report (subsequently accepted and committed)

Task 05A adds an explicit version-1 B/G/R/NIR product and integer rectangular
cell-grid acquisition policy, plus a bounded version-6 fixed-script continuation.
The new opt-in path sizes records before storage admission and shares the accepted
protected physical transaction. Continuous-equivalent legacy outputs, schema 5,
program versions 1-5, bundle/canonical/provenance 1 and B2 1/1 remain unchanged.
Product credit requires actual compatible delivered acquisitions and exact
completing RecordService evidence, with an inclusive deadline and idempotent
ledger. Initial attitude is explicit evidence, not a fabricated prior image.
See `V5_MS_MISSION.md` and `examples/v5_ms_mission_demo.py`.

The synthetic 10000 m square / 6.5 m / four-band / 12-bit fixture creates
113689008 integer bits (1539 by 1539 cells), delivers 40000000 bits partially,
and completes at 228.689008 s within deadline 229, before its full contact ends
at 300. A fifth acquired band incurs its full additional storage/transmission.
Physical standby covers both explicit gaps. All spectral/mode/load and coverage
assumptions remain synthetic; no hardware, orbit or numeric GSD standard is frozen.

Validation completed on the candidate. The first new-test run reported 53 passed / 1 failed:
one test supplied fractional bits/sample to a constructor that correctly rejects
them before execution. That fixture was corrected to a valid integral but
incompatible configuration; its original failure log is retained externally.
The focused acquisition/protection/contact/codec/restart regression then passed
529 tests, exit 0. The final full repository regression passed 7026 tests,
0 failed/errors/skipped, exit 0, including all 60 new Task 05A cases. Its 19
warnings concern existing J2 tests' record_property/JUnit xunit2 metadata.
Python 3.14.7 / pytest 9.1.1 used the existing .venv, python -B, disabled bytecode
and pytest cache, and external logs/JUnit/basetemp. Actual CLI partial-save,
fresh-process JSON resume and continuous execution also matched exactly.
Only this validation-reporting text changed after the full candidate was tested;
production/tests/example/contract bytes remain those of the passing full run.
No old result is presented as a newly executed test; no commit or tag was made.

Task 04C is a closed EXTERNAL bounded numerical study, not new repository physics:
seven synthetic cases met its frozen criteria, C3 remained unresolved under its
strict refinement rule and U remained unsupported by exact EPS/thermal arithmetic.
Its 27 external checks passed; the 6966-test and 115-test results below were reused
historical evidence in 04C. No global campaign subdivision policy follows from it.
Task 05B rolling control/multi-request scheduling and Task 05C sourced hardware
comparison/campaign qualification remain deferred. Nothing in this candidate is
a new release or an independently accepted implementation.

## Historical Task 04B/R1 accepted review and commit closeout

The coordinator accepted Task 04B-R1 within its documented scope: the raw-rate
validation defect is closed, with no new blocking defect found in the reviewed
area. Closeout verified the supplied R1 ZIP SHA-256, CRC, all 147 members and
146 manifest hashes, all 294 current source hashes, and the full-run environment.
The 6966-pass R1 full regression below is REUSED, not newly executed for closeout.
Only this current reporting section changes after the reviewed candidate.
The coordinator independently passed 115 contact/R1 tests, 130 adjacent tests
and 18 additional checks; five unavailable historical-object prerequisites were
not counted as passed. The coordinator did not repeat the full repository suite.
The author authorizes one local commit: feat(v5): add exact multi-record contact
execution. Its actual identity and post-commit verification belong in the
external closeout report; no future commit hash is asserted here.

Task 04B-R1 preserves the reviewed uncommitted candidate and corrects only the
new contact boundary: validate the ORIGINAL rate parameter as a bounded positive
built-in int or integral finite built-in float before historical capacity float
conversion, then cross-check nominal rate/capacity against the exact integers.
Fraction (including integral Fraction) and other raw scalar types are unsupported.
Legacy communications, ScalarParameter, codec, physics and versions 1-4 remain.
R1 validation: both reviewed Fraction cases failed before repair (2 failed,
exit 1) and passed afterward (2 passed, exit 0). The two complete contact test
modules passed 115 tests (48.58 s); 11 adjacent time/capacity/bundle/codec/shared
physics modules passed 342 tests (116.44 s), both exit 0 without failures/skips.
The initial external reproduction collection encountered a Windows directory
access error; explicit external rootdir resolved collection, with both original
failures preserved. The one complete R1 repository regression passed 6966 tests
(605.13 s, exit 0), with zero failures/errors/skips. All 294 candidate hashes
matched before/after full; afterward only this validation-reporting text changed.
Existing .venv, Python 3.14.7 / pytest 9.1.1, python -B, disabled bytecode/pytest
cache and external logs/JUnit/basetemp were used; dependencies stayed unchanged.
One extra EOF LF in test_contact_restart was removed separately; its AST
including source locations is identical. Cumulative and R1-only patches pass
strict whitespace checks and reconstruct all changed/new files outside Git.
The Task 04B results below describe the pre-R1 reviewed candidate.

Task 04B starts from verified clean v5-redesign at
086eaaaa62840a64cb9df969cee9c232516631db, parent
d9b970225d654c1e1624477468222ee6a02c996e, tree
9ffffd0420e0e8593bf0882ddf4fc36a285947ca. Task 04A closeout ZIP SHA-256,
CRC/member hashes, all 288 baseline working files and environment matched.
The 6851-pass full and 267-pass post-commit results are historical evidence,
not new baseline runs.

The separate version-5 contact executor consumes explicit ordered onboard
record IDs, continues partial records and uses remaining contact capacity for
subsequent records. Integer-bit/rate rational boundaries govern service time;
binary64 physics cannot round those boundaries or change data. TX is on only
during accepted service, with physical TX-off residual idle. Every segment
uses the same Task 04A EPS/thermal/degradation owner and current calculated
state. A later valid denial preserves earlier service in the isolated proposal;
malformed input or late exception rolls back the whole outer contact.

One outer contact advances the integer clock and completed-step counter once.
Schema-5 custody retains original completing contacts; typed outcomes carry
exact completion offsets and conservative ceil timestamps. Version-5 memory
persists consumed contact identities/intervals, actual outcomes and prior
acquisition. Completed-contact replay and bundle identity include this memory
and the exact-time/numerical contracts. Versions 1-4, schema 5, B2 1/1 and fixed
digest remain. See V5_CONTACT_EXECUTION.md and the version-5 bundle extension.

Task 04B validation reporting: the one complete repository regression passed
6947 tests (603.17 s, exit 0), with zero failures/errors/skips. All 294 candidate
file hashes matched before/after that run; only this validation-reporting
paragraph changed afterward. Existing .venv, python -B, disabled bytecode/pytest
cache and external logs/JUnit/basetemp were used. Python 3.14.7 / pytest 9.1.1
and the dependency map remained unchanged. The first focused new/compatibility
run recorded 255 passed, 1 failed, exit 1. The new legacy
comparison fixture set timestep=10 while retaining checkpoint interval=36;
the unchanged NumericalConfig validator correctly rejected that mismatch.
The fixture now explicitly sets both legacy intervals to 10; no admission
assertion or production integer-time validation was weakened. Original logs,
JUnit and source inventories remain external.
The corrected focused run passed 256 tests (121.50 s, exit 0). The final
focused/adjacent gate passed 861 tests (235.34 s, exit 0), including all 96 new
checks, with zero failures/errors/skips. Seven standalone demo commands passed:
independent exact bit/time/energy references, four policies with identical
physical scenario content and distinct numerical identity, and JSON-only
fresh-process continuation with consumed-contact replay rejection. A separate
constant-forcing conductive reference documents changed coarse/refined sampled
admission; its level-10 predicted endpoint error is 0.001085 K against the
independent closed ODE, below the declared 0.002 K bound. This is local evidence,
not campaign qualification. Physical equation-owner files are byte-identical
to Task 04A; the extracted shared substep preserves its composition statements.
No historical test or assertion was changed, skipped or weakened.

This candidate does not implement Task 04C campaign qualification, Task 05 or
controller selection, priorities, mid-contact restart, J2/propulsion extensions
or permanent damage. Sampled protection is not continuous safety. Constant
contact forcing, exact R1 representability limits and bounded work admission
remain explicit. The earlier implementation-stage no-staging/no-commit boundary
is superseded only for this accepted one-commit closeout. Tags, pushes, amendments,
resets and history rewriting remain unauthorized. Task 04C is next, not started.
The accepted Task 04A and earlier sections below are historical stage records;
their original validation claims remain preserved.

## Current Task 04A accepted review and commit closeout

Task 04A starts from the verified clean v5-redesign Task 03B/R1 commit
d9b970225d654c1e1624477468222ee6a02c996e, parent
4f03cad9ca4070ebd19e8244c9c19940f6086294, tree
31870bb89f5d124888505565d25905e13cf5a11a. The supplied closeout ZIP hash,
CRC and all 32 member hashes were verified; all 280 baseline working-file
hashes matched its final inventory. Its 6765-pass full regression and 300-pass
post-commit regression are historical evidence, not new baseline runs.

The new explicit version-4 mode separates an integer physical action interval
from a bounded dyadic numerical partition. It reuses the existing EPS, routing,
thermal, degradation and reconciliation arithmetic beneath preserved legacy
integer APIs. Every substep updates capability and physical state. One external
action commits data, completed clock and step count once. Refined sampled
protection checks initial/all calculated endpoints; denied actions select
full-duration standby from the original state. Predicted/actual traces, actual
numerical work and outer decision boundaries remain distinct. No fractional
observation is silently stored as an integer threshold-crossing time.

Separate SubsteppedProgram version 4 and its memory persist all required
completed-action outcome/prior-acquisition history. Integration policy,
physical intervals and forcing are content-bound. Bounded replay and fresh-
process JSON checks retain schema 5 and strict provenance. Versions 1/2/3,
B2 1/1 and fixed digest, prior release objects and project history are unchanged.
See V5_SUBSTEPPED_EXECUTION.md and the version-4 bundle extension.

The mandatory 12-second and 23-second linear thermal references refine toward
their independently derived analytical solutions with unchanged physical
timelines. The 23-second coarse Euler cooling endpoint is not qualified
recovery; refined prediction can deny the unchanged next request. Charging,
discharging, capacity/power constraints, routed heat, nonzero ageing, sampled
protection, late-failure rollback and same-policy restart are checked separately.
Positive energy underflow is an explicit integration-specific rejection; the
accepted R1 service-allocation boundaries are preserved without tolerance.

Task 04A validation reporting: full regression passed. Initial owner
tests recorded 297 passed/3 failed (architecture import/call-location checks).
The first new-test run recorded 68 passed/10 failed/2 errors: the new thermal
fixture used a conductance ParameterId inconsistent with its declared link ID.
The fixture was corrected without changing configuration validation. The next
focused/owner gate passed 380 tests. Expanded compatibility recorded 2885
passed/1 failed: another architecture check needed to follow the shared EPS
helper. All original logs/JUnit and source inventories are retained externally.
The final pre-full focused/compatibility gate passed 682 tests (187.66 s,
exit 0), including all 86 new checks, with zero failures/errors/skips. Seven
standalone demonstration commands returned exit 0: four subdivision policies
retain one physical-scenario digest and four numerical experiment digests;
JSON-only fresh-process resume exactly equals its uninterrupted same-policy
run. Both mandatory analytical reference sweeps through 4096 substeps passed.
No assertion is disabled, skipped or relaxed; no baseline full suite was rerun.
The ONE complete repository regression passed 6851 tests (975.44 s, exit 0),
with zero failures/errors/skips. All 288 candidate file hashes matched before
and after that run; only this validation reporting changed afterward. The
executing production/test/example and contract documentation bytes are those
tested by the full suite. Existing .venv: Python 3.14.7, pytest 9.1.1;
python -B, PYTHONDONTWRITEBYTECODE=1, disabled pytest cache, external logs/JUnit
and unique basetemp with its parent created first. Final inventories, original
failure logs and numerical/restart evidence are retained in the Task 04A
review archive. No staging, commit, tag or push occurred at implementation
handoff.

Coordinator review accepted Task 04A within its documented bounded scope,
with no blocking defect. The coordinator verified the ZIP and reconstructed
288/288 candidate files, inspected the shared physical owners and legacy
architecture checks, and independently exercised physics, execution, selected
fresh-process restart and additional numerical references. Export checks that
needed unavailable original Git objects were not represented as successful
original-history checks. The coordinator inspected the genuine 6851-test
JUnit but did not independently repeat that full suite.

Commit closeout verified reviewed ZIP SHA-256
0dee5e04c3f1ae6502a661c1a92b8f5e96f0e531c0215d7069d88be3f840b9a0,
CRC/member hashes, all 288 working-file hashes and the exact source/environment
provenance. The 6851-pass result above is REUSED, not newly executed in
closeout. Only this current status/reporting section changes after acceptance;
production, tests, examples and execution contracts remain reviewed bytes.
The author authorizes one local Task 04A commit. Actual commit identity and
the required post-commit seven-module result belong in the external closeout
report, without a subsequent tracked-document edit.

This candidate does not implement Task 04B multi-record/early-TX-off execution,
Task 04C campaign-wide qualification, controller planning, orbit/J2 extensions,
propulsion or damage. Level 12 is a reference refinement level, not an approved
campaign timestep. Tags, push, amend and history rewriting remain unauthorized.
The accepted Task 03B/R1 section below is historical;
its original validation claims are preserved at their own stage boundary.

## Current Task 03B/R1 accepted review and commit closeout

Task 03B starts from clean v5-redesign at Task 03A commit
4f03cad9ca4070ebd19e8244c9c19940f6086294 (parent
11ac9aaa5f9ada8465c7c87572f17878fb4af724). The Task 03A closeout ZIP SHA-256,
CRC/member hashes, 273 working-file baseline and 41 tag mappings were verified.
The historical 6642-test full regression and actual 177-test post-commit check
are baseline evidence, not a new unchanged-baseline run.

The new explicit execute_protected_request/evaluate_action_availability boundary
uses required thermal role mappings, existing inclusive operating/survival
limits, current onboard truth and explicit interval forcing. Nominal start/end
predictive admission reuses isolated completed physical proposals. A valid
denial executes one payload/transmitter/propulsion-off physical standby step;
malformed input or late failure commits nothing. Existing EPS, heat routing,
thermal, ageing, reconciliation and engine transaction owners remain unchanged.

All explicitly declared standby loads are essential, with an explicit component
service order for deficient-power heat allocation. Mission-action insufficiency
is separate from essential-power loss. Sampled NORMAL/BACKUP and activity-mode
updates are reversible; critical_energy_since_seconds records a sampled first
essential deficit, not a continuous crossing. Actual survival observations are
separate from discarded predictions and imply no death or damage model.
Ground knowledge never refreshes implicitly; diagnostics are non-causal.

Separate OperationalProgram version 3 consumes requests with typed outcomes,
preserves prior successful acquisition across denials and rejects structurally
invalid references. Bounded replay from immutable initial conditions validates
outcomes and complete checkpoint truth, including rehashed inconsistencies.
Versions 1/2 and all legacy kernel behaviors remain unchanged. Checkpoint schema
5, bundle/canonical/provenance version 1 and B2 versions/fixed digest remain.
See V5_OPERATIONAL_PROTECTION.md and the bundle extension documentation.

Pre-R1 validation history (not validation of the repaired candidate): initial
focused run recorded 39 passed, 8 failed (exit 1).
Seven new-fixture failures attempted forbidden zero nominal solar hardware;
zero generation is now represented by explicit eclipse forcing. One recovery
fixture omitted the effect of its declared solar degradation on an exactly
matched supply; it now explicitly supplies adequate generation. A second run
passed 81 tests (61.81 s, exit 0). The first expanded focused/adjacent run
recorded 643 passed, 1 failed (113.37 s, exit 1): the new readiness fixture used
zero angular separation, for which the established ADCS contract needs no slew
or settling; the fixture now explicitly requests a different direction. All
old tests in that run passed. The final focused/adjacent gate passed 645 tests
(113.42 s, exit 0), with zero failures/errors/skips, including 94 new checks.
The independent numerical standby reference and direct/save/fresh-process
resume demonstration passed. The ONE complete repository regression passed
6736 tests (458.63 s, exit 0), with zero failures/errors/skips. All 279 candidate
file hashes were identical before and after that run; only this validation
reporting changed afterward. Existing .venv: Python 3.14.7, pytest 9.1.1;
python -B, PYTHONDONTWRITEBYTECODE=1, disabled pytest cache, external log/JUnit
and unique basetemp with its parent created first. Tested source hashes and all
earlier failures are retained externally under
kazeosat-review-archive/task03b-20260921T181019Z. Existing tests and historical
assertions were not weakened; no skips/xfails/ignores/deselections were used.

Task 03B-R1 preserves that reviewed uncommitted candidate and repairs only its
local standby service composition. The reviewed ZIP SHA-256 was verified as
ac909e0885166568d696dd62cf5e35accd23bebda00a37432b0ed4d0a7eb8ab6;
all 279 pre-R1 working-file hashes matched its final inventory. The four
qualified decimal reproductions failed before repair while their independent
ledgers passed the unchanged thermal owner. Full service now preserves original
demands; deficient service uses exact-binary priority arithmetic and a bounded
search for an exactly reconciling partial component in the owner's sequential
enum-order arithmetic. No EPS, thermal, global numeric or persistent contract
was changed. See V5_OPERATIONAL_PROTECTION.md for precise rejection boundaries.

R1 validation reporting: the first focused run recorded 122 passed, 1 failed
(115.87 s, exit 1). The new unsupported-case test initially specified the wrong
adjacent binary64 pair for its independent gap proof; the fixture was corrected
from an explicit arithmetic calculation, with original test/log retained.
No production change resulted from that fixture correction. Final focused
validation passed 123 tests (113.87 s, exit 0), including 29 R1 and 94 original
Task 03B checks. Adjacent EPS/routing, atomicity, Task 03A, bundle and provenance
validation passed 858 tests (69.91 s, exit 0). Both had zero failures/errors/skips.
The numerical reference and direct/save/fresh-process demonstration passed.
The ONE complete R1 repository regression passed 6765 tests (652.80 s, exit 0),
with zero failures/errors/skips. All tested production/test/example/contract
bytes remain unchanged; only this validation reporting changed after the run.
Commands, before/after reproductions, original fixture failure, log/JUnit,
SHA-256 inventories and fractional JSON restart outputs are retained in the
Task 03B-R1 review archive. At the R1 review handoff, HEAD, index bytes, Git
configuration and all 41 tag mappings were unchanged. R1 changed three
pre-existing candidate files and added one test module; that handoff performed
no staging or commit.

The 23-second cooling trace is a discrete policy demonstration, not physically
validated recovery time. Its declared two-node ODE has exact endpoints about
300.4792651133611 K (bus), 336.98459095216606 K (payload); the current single
Euler step gives payload 300 K. Numerical qualification remains a Task 04
dependency. R1 neither changes the integrator nor starts Task 04.

The coordinator accepted Task 03B including R1 within its documented numerical
boundaries: the original blocker is closed and no new blocker was found in
the reviewed scope. The author authorized one local commit for this closeout.
The accepted R1 ZIP SHA-256 is
4fad1830f9b82d593d19dc089dbc1edc12f8c0aa62aadf26429d72d8f6496983.
Closeout verified its CRC and all 93 member hashes, all 280 current files against
the final inventory, and the full-run inventory (only the documented later
MODEL_STATUS validation reporting differs). Python, dependency versions and
source/environment compatibility match the recorded full R1 run. The 6765-pass
full regression is reused evidence, not a new closeout run.

Coordinator-reported independent verification passed 123 Task 03B/R1 tests,
318 adjacent tests and 35 additional tests; 384 witnessed allocations across
all 24 meaningful priority orders agreed with an independent nextafter oracle.
Six fresh-process restart boundaries in a different partial-delivery/fractional
load/deficit/recovery scenario passed; an old-code negative control reproduced
all four original failures. The coordinator inspected the delivered 6765-pass
log/JUnit but did not independently rerun that full suite. Temporary source
fixtures were not represented as the author's original historical repository.

Incompatible full-demand aggregation (including .1/.2/.3 W), unrepresentable
fixed-prefix partial service and sampled rather than continuous thermal safety
remain explicit boundaries. This closeout makes no code, test, example or
contract-documentation changes. The required nine complete post-commit modules,
actual commit identity and results are recorded externally; tracked documents
are not edited afterward merely to append those results.

All numeric demonstration choices and perfect sampled onboard observation are
model assumptions, not spacecraft calibration or lifetime/reliability claims.
No continuous thermal safety, permanent damage, reserve rule, beacon, redundancy
switchover, full FDIR or V5 completion is claimed. Task 04 and the full ground
controller are not started. Only the accepted eleven-path local commit is
authorized for this closeout; tags, pushes and history rewriting are excluded.
The next task is Task 04, not started here.

## Historical Task 03A accepted review and commit closeout

Task 03A starts from clean v5-redesign at committed Task 02/R1
11ac9aaa5f9ada8465c7c87572f17878fb4af724 (parent
99fef04f17662f3b7f3a5dbbb7cfe5515a5579fb). The Task 02 closeout ZIP hash,
source bytes and Python/dependency environment were verified. Its historical
6570-test full regression and 105-test post-commit gate are baseline evidence,
not tests rerun merely to start Task 03A.

The separate step_coupled_downlink entry point requires explicit transmitter
watts, baseline component demand, solar forcing, heat routing/boundaries,
external heat and optional solar degradation forcing. All components require
full electrical service over one full engine step; both energy and discharge
power limits apply. One authoritative EPS result feeds routing, thermal coupling,
throughput, temperature-dependent ageing and capacity reconciliation through
the existing shared completion helper. Data, physical state, diagnostics and
time commit in one existing transaction. Transmitter demand persists for the
whole interval, including unused data capacity; reconciliation loss is not heat.

Electrical denial returns an explicit reason with time_advanced=False and no
caller-state mutation. Invalid input and late failure raise atomically. The
example separately demonstrates caller-selected transmitter-off physical waiting.
No autonomous retry, FDIR, mission controller or new physical law is introduced.

Continuation version 2 adds a distinct content-bound CoupledDownlinkAction;
version 1 and legacy DownlinkAction remain data-only on downlink. Bundle,
canonicalization and provenance versions stay 1, checkpoint schema stays 5,
and B2 versions/fixed digest and strict implementation provenance are unchanged.
V4, J2, prior scientific formulas, decision/source history and SIDe artifacts
are unchanged. See V5_COUPLED_DOWNLINK.md and V5_EXPERIMENT_BUNDLE.md.

Validation reporting: the final focused/adjacent gate passed 882 tests in
43.99 s (exit 0), including 72 new checks. The ONE complete repository gate
passed 6642 tests in 390.44 s (exit 0); JUnit confirms zero failures, errors and
skips for both final gates. No xfails/xpasses/deselections were reported. Tests
used the existing .venv (Python 3.14.7, pytest 9.1.1), python -B,
PYTHONDONTWRITEBYTECODE=1, disabled pytest cache and external logs/JUnit/unique
basetemp. The independent numerical/denial-wait demonstration passed, and a
separate direct/save/fresh-process-resume execution matched exactly. During
and after the full suite all production, tests, examples and contract bytes
stayed fixed; only this validation-reporting paragraph changed afterward.
Durable review evidence is under kazeosat-review-archive/task03a-20260921T162514Z.
The first new-test run recorded 60 passed, 4 failed (exit 1): two new fixture
references used an incorrect transmission-result field name, and two fault
injections targeted a slotted engine instance instead of its class. These test/
example errors were corrected; a subsequent new-test gate passed 64 tests.
An adjacent run recorded 807 passed, 3 failed (exit 1): existing architecture
guards require EPS authorization/thermal resource composition outside engine.py.
The pure composition was moved into the new resource owner, matching the imaging
pattern; the transaction kernel and all old tests stayed unchanged. Additional
precommit-evidence checks bring the new coverage to 72. All failure evidence is
preserved externally; no skips/xfails or old assertion changes were introduced.
At the implementation handoff, no project staging, commit, tag or push had been
performed. Independent coordinator review has now accepted Task 03A within its
documented bounded scope with no blocking defect. The author has authorized one
local closeout commit; tags, pushes, amendments and history rewriting remain
unauthorized. Task 03B is next and has not started; Task 04 has not started.

Closeout verified the reviewed ZIP SHA-256 and all 273 candidate file hashes
against the before/pre-full/final evidence, including unchanged production,
tests, examples, configuration and dependency inputs. The current source bytes
and Python/dependency environment match the recorded full run. The verified
6642 passed, zero failures/errors/skips, exit-0 full regression is reused;
it is not a new closeout run. Only this current status records the accepted
review and commit authorization; historical records and limitations are retained.

Coordinator-reported independent verification passed 72 new Task 03A tests,
262 relevant existing physics/chronology/checkpoint tests, 105 Task 02/R1 tests
and 59 additional checks. The coordinator inspected the supplied complete
6642-test log/JUnit but did not independently rerun the full suite. Actual
commit identity and post-commit verification belong in the external closeout
report; no future commit hash or unexecuted result is asserted here.

## Historical Task 02 content identity and reproducible continuation (committed baseline)

Task 02 starts from committed Task 01 at
99fef04f17662f3b7f3a5dbbb7cfe5515a5579fb on v5-redesign, with a clean
worktree/index. Task 01 closeout evidence is preserved as baseline evidence;
its unchanged complete suite was not rerun merely to start this task.

The new separately versioned experiment bundle binds the complete current
SimulationInputs graph, explicit action/forcing program and assumptions by
canonical content. Runtime checkpoint and external causal memory have a separate
digest; code/environment provenance includes actual dirty/new source bytes.
The codec uses an explicit field/constructor allowlist with coverage checks,
typed exact numeric representations, strict fields and validated constructors.
Legacy checkpoint restore retains its existing ID-based non-orbit contract.

Supported continuation is a bounded deterministic script of existing full-step
imaging-to-storage and V5.5 downlink actions, with explicit prior acquisition
and executed-prefix/forcing position. Completed boundaries check chronology,
clock, diagnostics, prior action and custody/delivery consistency. Restore and
advance return fresh state. No production V5 mission runner or common controller
is claimed; existing mission/controller state remains owned by checkpoint.
See V5_EXPERIMENT_BUNDLE.md for the implemented scope, public APIs, compatibility
policy, numeric representation and unsupported modes.

Checkpoint schema 5, B2 versions/digest, existing physical formulas, J2, V4,
Task 01 chronology, source records and decision history are unchanged. Downlink
still advances time without concurrent EPS/thermal evolution. Task 03A has not
started. Independent coordinator review accepted Task 02 including R1 with no
blocking defect in the reviewed scope. The author has authorized one local
commit for this closeout; tags, pushes and history rewriting remain unauthorized.

Task 02-R1 corrects Git pathname classification in provenance capture. Both
tracked and modified paths now use NUL-delimited binary Git output with strict
UTF-8 decoding, preserving path characters independently of core.quotePath.
Source hashing, provenance format and clean/dirty validation are unchanged.
Real disposable Git fixtures reproduce the original clean Unicode-path failure
and modified-path misclassification before the repair. New checks cover both
quotePath settings, clean/modified/untracked files, spaces and parser-only
newline/control-character cases. At the R1 handoff, no Task 03A work or project
staging/commit/tag/push had been performed.

R1 validation used the same Python 3.14.7 / pytest 9.1.1 environment with
python -B, PYTHONDONTWRITEBYTECODE=1, disabled pytest cache and external
logs/JUnit/unique basetemp. The repaired focused gate passed 105 tests in
25.54 s (17 R1 checks plus the original 88 Task 02 tests); adjacent checks passed
361 tests in 3.32 s. The ONE complete R1 repository suite passed 6570 tests in
430.42 s. All three exited 0 with no failures/errors/skips or xfails/xpasses/
deselections. Pre-repair evidence retains the initial fixture setup failure
(2 passed, 6 failed), followed by the confirmed production reproducer
(5 passed, 3 failed); both exited 1. The fixture/import and Windows diagnostic
encoding corrections are documented separately from the R1 production defect.
Production/tests/contract bytes stayed fixed throughout and after the full run;
only this validation reporting changed afterward. Durable R1 evidence is under
kazeosat-review-archive/task02-r1-20260921T135757Z outside the repository.

Closeout verified the reviewed R1 ZIP hash and all 268 current source-file hashes
against final-sha256.json and pre-full-sha256.json, including unchanged production,
tests, examples and configuration/dependency inputs. The recorded Python and
dependency environment matches. The existing R1 full regression (6570 passed,
0 failed/errors/skipped, exit 0) is reused, not newly executed for closeout.
Coordinator-reported independent checks passed 105 Task 02/R1 tests, 148 existing
tests and 11 additional checks; a pre-R1 negative control reproduced the original
three failures. The coordinator inspected the full log/JUnit but did not rerun
all 6570 tests. Production/tests and the reviewed contract remain byte-identical;
only this current status records accepted review and commit authorization.
The actual commit identity and post-commit verification belong in the external
closeout report. Task 03A remains not started.

Original Task 02 validation, before R1, used the existing .venv (Python 3.14.7, pytest 9.1.1), python -B,
PYTHONDONTWRITEBYTECODE=1, disabled pytest cache and external logs/JUnit/basetemp.
The final focused gate passed 899 tests in 20.49 s, including all 88 new tests;
the ONE complete repository suite passed 6553 tests in 412.42 s. Both exited 0,
with 0 failed, 0 errors and 0 skipped; no xfails/xpasses/deselections were reported.
The first focused gate had 86 passed and 1 failed: a new test wrongly expected
schema-5 integer-to-float normalization. The corrected check verifies preserved
integers, with separate rejection checks for lossy Fraction and unknown state.
All initial failure evidence is retained. Fresh-process restart tests pass at
four boundaries; standalone direct/save/resume outputs also match exactly.
Production/tests and the contract document stayed byte-identical during and
after the full suite; only this validation-reporting paragraph changed afterward.
Durable evidence and the review ZIP are outside the repository under
kazeosat-review-archive/task02-20260921T053956Z. No dependencies were changed.

## Historical Task 01 data-chronology correction and committed closeout

The actual baseline is committed V5.6F2 at
332a7f480ce9508349bc7ebc9879bf5228035a91 on v5-redesign. The worktree and index
were clean before Task 01. This section records the reviewed Task 01 correction
and its author-authorized local-commit closeout.

Completed runtime states now require every onboard acquisition to end no later
than simulation time. Partial and complete transmissions require acquisition
end no later than the serviced contact start; equality is valid. A shared
data-delivery contract covers context/checkpoint construction and revalidation,
and both transmission evaluation and result validation. Standalone future
records remain valid. Imaging-to-storage retains its existing transaction:
the new record is checked after the clock advances, before committing state.
Rejected operations do not repair timestamps or mutate the original context.

Five precise portability fixes use the active sys.executable for the storage
demo subprocess and accept the specific TypeError/ValueError init=False rejection
from dataclasses.replace across Python versions. Constructor rejection checks
and subsequent assertions remain intact. Older incompatible timestamp fixtures
are corrected without removing their behavioral assertions.

V4, numerical formulas, J2, public engine signatures, checkpoint schema 5,
B2 versions/digest and release tags are unchanged. Coupled downlink physics and
other features remain outside Task 01. No decision or source record is added.

Implementation validation used the existing .venv (Python 3.14.7, pytest 9.1.1), with external
logs/JUnit/basetemp and bytecode/pytest cache writes disabled. The affected and
adjacent gate passed 1446 tests in 59.95 s; the final chronology module passed
22 tests in 0.74 s. Both exited 0. The ONE complete repository pytest run passed
6465 tests in 398.34 s, with 0 failed, 0 errors and 0 skipped, exit 0. No xfails,
xpasses or deselections were reported. Earlier focused runs exposed the three
incompatible timestamp-fixture groups; their logs and corrections are retained
in the external report. Production/tests remained unchanged during the full run;
only this validation-reporting text changed afterward. Historical F2 counts
below are retained, not reused as Task 01 results. No commit/tag/push was made
at that implementation handoff.

Closeout review found no blocking defect in the reviewed scope. Independent
results reported by the author were 22 chronology checks and 165 additional
checks passed; an adjacent-module export run had 777 passed and 45 failures at
unavailable original Git-history prerequisites. An old-code negative control
had 18 failures and 4 passes. These review results are distinct from local
full-suite evidence.

Fresh closeout verification used the actual repository and original Git history:
ONE complete pytest run passed 6465 tests in 414.92 s, with 0 failed, 0 errors,
0 skipped and exit 0. No xfails, xpasses or deselections were reported. Python
3.14.7 / pytest 9.1.1, python -B, PYTHONDONTWRITEBYTECODE=1 and disabled pytest
cache were used. Full stdout/stderr, JUnit, commands and source inventories are
saved in the durable kazeosat-review-archive directory outside the repository.
The reviewed production/test bytes remained unchanged throughout closeout;
only this current status section changed after the fresh gate. The author
authorized one local commit; no tag or push is authorized. Task 02 is not started.

## Historical V5.6F2 candidate status (superseded by the committed baseline above)

F1 is committed at 097c0ee2b6b28201df1dd5d4088d02f55bacbeb0, tree
24ba322db3bbd2d7397d3c6f29a13fac4b72d349. F1 production/tests and source records
remain byte-identical. F2 adds only ops_sim/v5/orbit_j2.py and two dedicated
test modules, D318 and one bounded S008 subsection. V5.6 remains IN PROGRESS.

F2 is NOMINAL Cartesian J2 propagation only. J2CartesianTrajectory owns an exact
reconstructed original CartesianState and exact F1 J2GravityModel; both complete
frames receive the existing F1 scientific-text preflight before shared-owner
equality. MODEL_INERTIAL and the same explicit TT reference epoch are required.
J2RK4SolverConfig requires finite positive non-bool step_seconds and exact
positive-int max_steps. There are no defaults, mutable propagated state or cache.

evaluate_j2_cartesian_state uses classical signed fixed-step RK4 and F1's sole
force kernel. Fraction arithmetic on admitted binary64 elapsed times determines
canonical full steps and at most one remainder; the remainder must be exactly
representable as binary64. Exact work counting precedes every force evaluation.
Each query restarts from original authority. Zero span validates graphs/gravity
but takes zero RK4 steps. Returned states retain the reconstructed requested
instant. Static stage force sampling uses genuine CartesianPosition evidence at
the anchor instant; it introduces no rotating J2 field or stage-clock error claim.

Independent numerical evidence includes B1/Decimal zero-J2 references, an exact
synthetic nonzero-J2 circle, h/h2/h4 refinement, energy using public F1 potential,
axial hz, approximate reversal, query-order/prefix identity, hostile metadata and
bounded arithmetic/work admission. Small-J2 nodal sign/scaling is a separately
budgeted approximation diagnostic. No invariant residual certifies endpoints.

There is NO F3 accumulated-error enclosure, F4 binding/checkpoint integration,
J2 temporal visibility or J2 contact/observation adapter. Family B's interval-view/
end-ray obligation remains open. Schema 5, B2 binding/representation 1/1 and digest
5fd4b089db8e0a846b526cfedca4a16f4057d38f296b759c9d0ed90b53352125 remain unchanged.
Nothing is staged or committed for F2.

External bounded measurements found one initial F1 check plus four force calls
per RK4 step. Synthetic 20/100/400-step queries took about 0.009/0.042/0.169 seconds.
A 5000-call profile measured F1 kernel 0.047 s, CartesianPosition reconstruction
0.421 s, actual F2 stage boundary 0.500 s and public F1 evaluator 0.898 s.
Owner reconstruction dominates this microbenchmark; no F1 change or speculative
optimization follows. Query cost is O(steps); repeated queries repeat prefixes.
F5 is expected to require deterministic search-local prefix reuse, absent here.

Validation reporting: all focused gates passed with zero failures, errors,
skips, xfails or xpasses and exit 0: A, 193 F2 tests in 51.11 s; B, 262 F1
tests in 0.70 s; C, 955 A/B1/B2 tests in 8.41 s; D, 826 C1/C2 tests in
34.80 s; E, 1191 C3/D1 tests in 115.17 s; F, 264 H/V5.5 tests in 53.58 s.
The six focused gates ran concurrently with separate external temporary roots.

The ONE complete repository suite passed 6443 tests with 0 failed, 0 skipped
and 0 errors in 354.70 s, exit 0. No xfails, xpasses or deselections were
reported. All six candidate files remained byte-identical throughout the run.
Every pytest invocation used the existing .venv, python -B, inherited
PYTHONDONTWRITEBYTECODE=1, -p no:cacheprovider, -q -ra and unique external
system TEMP/basetemp, log, JUnit XML and durable exit records. The external
runner selected legacy JUnit format to retain numeric evidence properties
without the development run's record_property/xunit2 compatibility warnings.
Only this validation-reporting text changed after the full suite; production,
both tests, D318 and S008 remain byte-identical to the final tested candidate.

One focused read-only self-review found no blockers in RK4/signs, exact
grid/work/remainder semantics, F1 ownership, endpoint/invariant evidence,
determinism or nominal-only documentation. Earlier external read-only probes
also checked independent Decimal circle references, secular diagnostics and
78 ownership/work/force-boundary checks. No new architecture review was started
after the resume instruction. Those probes are supplemental evidence; none
supplies a certified state error.

Development runs are not final gates.
The first contracts run had 162 passed and two test-helper failures: requests
were accidentally built through a deliberately forged state. The helper now
constructs an independent valid request. The next F2 run had 179 passed and
14 refinement-policy failures: the finest error was below ten times the
unchanged declared arithmetic reserve, so forcing its ratio contradicted the
floor policy. The corrected check requires at least one resolved fourth-order
pair and preserves all-level monotonicity/accuracy checks; it makes no order
claim below that floor. No production correction or loosened error budget occurred.
Logs/results and all scratch/probes are outside the repository.

## Historical V5.6F1 candidate record (now committed)

D1e is committed at a5ba82a15ab2264c51674f9073c0e53410b00500, tree
36f9b71e80e4868a51234b8ca979da1cb3efa562. The accepted V5.6E adequacy gate
found Family A (orbital approximation) and Family B (start-only viewing) require
successors. The subsequent read-only architecture audit selected J2-C.

The F1 candidate adds only ops_sim/v5/orbit_j2_gravity.py, two dedicated tests,
D317 and a bounded S008 source record. J2GravityModel contains explicit
provenance-bearing mu, unnormalized J2 and an independent gravity reference
radius. J2GravityEvaluation/evaluate_j2_gravity derive instantaneous total
Cartesian acceleration and negative specific potential for an exact supplied
MODEL_INERTIAL CartesianPosition. Complete frame/instant evidence is retained;
there is no time advancement. Local exact-text checks and existing owner
reconstruction preserve scientific metadata without changing shared owners.

The static axis is MODEL_INERTIAL +z. Central gravity is included once; no
centrifugal/Coriolis term, shape-derived J2/radius or Earth parameter default is
introduced. Exponent-scaled products avoid explicit radius powers and premature
component underflow. Unsupported arithmetic raises; zero J2 bypasses every
correction calculation. Independent synthetic references verify the force law,
potential derivative, symmetries and admitted numerical scales.

F2 propagation and F3 conservative accumulated-error enclosures remain absent.
F1 establishes no J2 temporal visibility, binding, contacts or observations.
Family B's interval-view/end-ray obligation remains open. Existing production
and tests, schema 5, B2 binding/representation 1/1 and its fixed digest are
unchanged. V5.6 remains IN PROGRESS. Nothing is staged or committed for F1.

F1 focused validation passed with zero failures, errors, skips, xfails or
xpasses and exit 0 in all six gates: A, 262 F1 tests in 0.84 seconds; B, 955
A/B1/B2 tests in 20.44 seconds; C, 826 C1/C2a/C2b/C2c tests in 89.49 seconds;
D, 171 C3a/C3b tests in 92.58 seconds; E, 1020 D1a-D1e tests in 185.09 seconds;
F, 264 H/V5.5 A-F tests in 107.84 seconds. Gates B-F ran concurrently.
Requested C2a/C2c geometry filenames were resolved to the actual unchanged
test_v56c2a_ellipsoid_visibility.py and test_v56c2c_engine_grid_projection.py.

Early F1 test-harness runs had one collection error from automatic formatting
of hostile text test IDs, then 49 helper argument-collision failures (213
passed). Both were corrected solely in the new tests before the green gates;
no production correction was required. These are retained development evidence,
not passing validation results.

Both independent read-only actual-source reviews passed with no blockers.
The physics/numerics reviewer inspected the complete production/tests/D317/S008
and independently checked 1825 synthetic cases: 661 admitted, 1164 intentional
arithmetic rejections, 2644 Decimal-gradient comparisons and five exact checks
passed, exit 0. Maximum observed error/budget fraction was 0.030694; a separate
underflow-boundary probe also passed. The ownership/provenance reviewer
confirmed exact public owners, complete metadata prechecks/reconstruction,
frame/instant retention, allowed dependencies and accurate bounded source/docs.

The ONE complete repository suite on the reviewed candidate passed 6250 tests,
with 0 failed, 0 skipped and 0 errors in 486.87 seconds, exit 0. No xfails,
xpasses or deselections were reported. All six candidate files remained
byte-identical throughout that run.
Logs, JUnit results and durable exit records are outside the repository. Every
pytest invocation uses the existing .venv, python -B, inherited
PYTHONDONTWRITEBYTECODE=1, -p no:cacheprovider, -q -ra and a unique external
system TEMP basetemp. Only this MODEL_STATUS validation-reporting portion changed after the full
suite. Production, both tests, D317 and S008 remain byte-identical to the
reviewed/tested candidate. The suite was not rerun for reporting alone.

## Historical V5.6D1e candidate record (now committed)

D1d is committed at 2fc3d2a1d385afca3a5e422dddb2e79219a988b6, tree
f18e551c4d2a96a9758d4b4d18a8c10a322c2f49. D1e adds one admission-only
OrbitBoundObservationCandidateCatalog in ops_sim/v5/orbit_observation_catalog.py,
two new test modules, D316 and one bounded S006 note. Prior production/tests,
including D1a-D1d and the legacy V5.3 collections/StableId, remain unchanged.

The sole input is an exact tuple of exact D1b candidates. Every item type is
checked before any reconstruction. Each item is rebuilt once from its eleven
D1b init inputs; supplied derived evidence is ignored. All reconstruction
succeeds before uniqueness is checked. Only opportunity IDs are globally unique:
exact wrapper type plus complete actual base-string content, extracted with
str.__str__ into temporary built-in text keys. The private set never receives
caller IDs or text subclasses. Original IDs and caller order remain unchanged;
equality is ordered existing D1b semantic equality, and the catalog is unhashable.

The new D1e identity/uniqueness/equality boundary invokes no caller opportunity-ID
text equality, inequality, hashing, stringification or formatting. Existing
nested owner admission is unchanged. Reconstruction still performs D1b's
D1a/C2c/B1/C1 work; this is not a geometry-free container. No pairwise D1c/D1d or
historical V5.3 C2/C3 evaluation, common-frame gate or chronology is introduced.
Actual-text bulk uniqueness is now supplied without rewriting legacy catalogs.
No legacy catalog/campaign or lossy geographic conversion is constructed.

There is no automatic opportunity/ID generation, compact-block enumeration,
sorting, selection, scheduler/controller/engine integration or acquisition
execution. Mission identity binding and completion remain V5.7 responsibilities.
The catalog remains external/recomputed; schema 5, B2 binding/representation v1
and its fixed digest are unchanged. J2, maneuvers/delta-v, full attitude, actuator
fidelity, slew energy and wider physical fidelity remain open.

D1e is now committed at a5ba82a15ab2264c51674f9073c0e53410b00500.
The following validation describes its reviewed pre-commit candidate.

D1e validation: all eight focused gates passed with zero failures, skips or
errors and exit 0: A, 87 D1e tests in 12.17 seconds; B, 576 D1d tests in
60.78 seconds; C, 82 D1c tests in 8.12 seconds; D, 164 D1b tests in 5.77 seconds;
E, 111 D1a tests in 52.39 seconds; F, 242 legacy V5.3 observation/ADCS/release
tests in 6.63 seconds; G, 1377 orbit-foundation/contact-compatibility tests in
54.08 seconds; H, 264 H/V5.5 A-F tests in 83.92 seconds.

Both independent read-only actual-source reviews passed with no blockers.
The identity reviewer independently passed 113 cases and 265 assertions,
exit 0, with zero caller hooks at the new boundary. Traps were armed after
the final D1b reconstruction, distinguishing unchanged owner admission from
D1e uniqueness/equality. Cases included hostile equality, unhashable/hash/
string/format traps, long actual text, nonadjacent duplicates, original ID
retention, ordered/non-ID evidence and failure ordering. The composition
reviewer confirmed one D1b reconstruction per item, ignored supplied derived
evidence, preserved nested ownership, no legacy/pairwise/generation/policy
or persistence behavior, and real schema-5/B2 restart with distinct IDs.

The ONE complete repository suite on this reviewed production/tests/D316/S006
candidate passed 5988 tests, with 0 failed, 0 skipped and 0 errors in
485.98 seconds, exit 0. No xfails, xpasses or deselections were reported.
Every pytest run used the existing .venv, python -B, inherited
PYTHONDONTWRITEBYTECODE=1, -p no:cacheprovider, -q -ra and a unique external
system TEMP basetemp. Logs, JUnit results and durable exit records are outside
the repository. No production or test correction was needed.

Only this MODEL_STATUS validation-reporting portion changed after the full
suite; production, both D1e tests, D316 and S006 remain byte-identical to the
reviewed/tested candidate. The suite was not rerun for reporting alone. Earlier
D1d and other counts below remain historical evidence, not new D1e runs.

## Historical V5.6D1d candidate record (now committed)

D1c is committed at 274d5eb22ead84d37e1e6c0e1e17cdab950b21e9, tree
0b77e1ce1a9cabe25486bf8f3a230871ba0dd31c. D1d supplies bounded orbit-derived
V5.3 C3 sequence/window evidence in ops_sim/v5/orbit_observation_sequence.py,
with two new tests, D315 and one bounded S006 addition. All prior production/
tests, D1b/D1c S006 and D1a S008 remain unchanged.

All three exact public types are admitted before reconstruction. The config and
both D1b wrappers are reconstructed through their existing owners; supplied
derived D1b fields are ignored. Ordinary previous_execution is constructed at
the previous certified D1a start, using the existing window-legality owner.

Two public view prechecks preserve historical C3 previous-view then next-view
failure precedence. A decisive view failure skips D1c/C2 and retains C3's
supported failure with null transition/readiness/candidate-start evidence.
It asserts no frame compatibility. If both views pass, D1c is mandatory before
temporary C3 inputs share the exact original previous frame-ID object.
Retained D1b labels, rays and ordinary execution remain unchanged.

One C3 call owns all sequence/window timing. Its frozen API repeats C2, so a
transition-bearing evaluation contains one D1c-owned and one C3-owned C2 call,
with no direct D1d transition arithmetic. Complete transition consistency uses
actual lower/upper anchor text and all five scalar fields exactly. Legacy text
subclasses remain subject to unchanged owner admission. The frozen/slotted,
default-free wrapper is unhashable and equality covers all retained evidence;
replace recomputes composition without accepting supplied results.

D1a's full-step opportunities make the next certified start its latest legal
start, as evaluated by C3. No chronological structural gate, readiness snapping
or timestep quantization is added. This supplies feasibility evidence only:
catalog generation/hardened bulk uniqueness, scheduling/selection/controller,
engine integration and acquisition execution remain absent. J2, maneuvers/
delta-v, full attitude, actuators, slew energy and wider fidelity remain open.
No persistence is added; schema 5 and B2 binding/representation v1 are unchanged.

V5.6 is **IN PROGRESS through the D1d candidate**. Nothing is staged or committed.

Independent actual-source review found a blocker in retained configuration
equality: ordinary ScalarParameter/dataclass comparison could hide different
actual rationale, units, parameter-ID, derivation and source-ID text behind
caller-overloaded string equality. D1d now compares complete represented
parameter/provenance evidence with actual base-string text equality. Identical
text remains equal across admitted subclasses; different text remains unequal
in both directions. Existing AgilePointingConfig/ParameterProvenance admission,
input reconstruction, view precedence and composition are unchanged. No new
rejection, physical law, parameter or scheduler rule is introduced. D315 records
the correction; S006 is unchanged.

A second independent actual-source review found remaining caller-overloaded
numeric equality in retained ScalarParameter values and SensitivityRange bounds.
D1d now extracts base int/float payloads, and uses the existing ADCS Integral-to-
int / other-Real-to-float representation convention for wider admitted Real
implementations. It compares those built-ins exactly without caller equality,
inequality or hash dispatch. No tolerance, physical normalization policy or
admission change is introduced. Text hardening, composition/view/timing and
persistence boundaries are unchanged. D315 records the exact local comparison
rule; S006 remains unchanged.

Historical PRE-TEXT-CORRECTION evidence: the former 5441-pass full suite had
0 failed, 0 skipped, 0 errors and exit 0 in 289.69 seconds.
Historical PRE-NUMERIC-CORRECTION evidence: the text-corrected candidate's full
suite had 5690 passed, 0 failed, 0 skipped, 0 errors and exit 0 in 508.38 seconds.
Neither full run is final evidence for this numeric correction.

Numeric correction validation: 211 new numeric regressions establish unchanged
owner admission before D1d equality. The red selection against pre-numeric
production had 207 failed, 10 passed and 359 deselected in 26.03 seconds, exit 1;
it included all 211 new cases and six prior transition-consistency cases.
Separate admitted-config probes confirmed false symmetric equality for different
scalar values and both sensitivity bounds, with four hostile __eq__ calls per
probe. The corrected first D1d gate passed 576 tests in 50.13 seconds, exit 0.
All 249 prior text/provenance regressions and hostile anchor-ID checks remain
unchanged and green. Numeric cases cover every configuration parameter, scalar
values and both bounds, always-equal/never-equal float/int subclasses, symmetry,
post-admission method traps, exact large integers, signed zero, adjacent floats
and the documented wider Real representation rule.

Fresh post-numeric-correction focused gates passed:
A, 576 D1d tests in 63.16 seconds; B, 82 D1c tests in 13.17 seconds;
C, 164 D1b tests in 9.92 seconds; D, 111 D1a tests in 46.63 seconds;
E, 242 V5.3 observation/ADCS/C3/release tests in 6.49 seconds;
F, 1206 A/B1/B2/C1 foundation tests in 11.86 seconds;
G, 171 C3a/C3b tests in 54.58 seconds;
H, 264 H/V5.5 A-F tests in 92.43 seconds.
The corrected initial gate and all eight fresh gates exited 0 with zero failures,
skips or errors.

Both independent read-only actual-source reviews passed before the replacement
full suite. The semantic reviewer independently passed 278 cases and 1112
symmetric equality/inequality assertions, exit 0, covering hostile values and
bounds, builtin conversion overrides, large integers, wider Real representations,
retained evidence and text rechecks. After admission and trap resets, D1d
equality invoked no caller numeric equality, inequality or hash methods.
The composition reviewer confirmed unchanged view precedence, conditional D1c,
safe C3 bridge, one C3 call, zero direct C2 calls, transition consistency,
timing and restart/schema/B2 boundaries. The complete __post_init__, text
helpers, transition comparison, timing/restart test file and S006 remain
byte-identical to the pre-numeric candidate. Neither review found a blocker.

The ONE replacement complete repository suite on the final numeric-corrected
production/tests/D315/S006 candidate collected 5901 tests:
5901 passed, 0 failed, 0 skipped and 0 errors in 410.28 seconds, exit 0;
no xfails, xpasses or deselections were reported.
All pytest runs used the existing .venv, python -B, inherited
PYTHONDONTWRITEBYTECODE=1, disabled pytest cache and unique external system TEMP
basetemp. Logs, JUnit results and durable exit records remain outside the repo.

Only this MODEL_STATUS validation-reporting portion changed after the numeric
replacement full suite. Production, both D1d test modules, D315 and S006 remain
byte-identical to that reviewed/tested candidate. No second numeric replacement
suite was run for this reporting-only edit. The 5441-pass pre-text and 5690-pass
pre-numeric runs remain historical evidence; neither is final post-numeric-fix
validation. Historical D1c and earlier results below are not new runs.

## Historical V5.6D1c candidate record (now committed)

D1b is committed at cf45eb19af985a871ba1397cd576a9f506bef2ae, tree
e332a404d7c762d48a445cf47b3863eac0cd253a. D1c adds one ordered pairwise adapter
in ops_sim/v5/orbit_observation_transition.py, two new test modules, D314,
one bounded S006 subsection and this current-status record. Existing production
and tests, D1b S006 and D1a S008 remain unchanged.

The exact existing AgilePointingConfig is reconstructed through its owner.
Two exact D1b wrappers are reconstructed from their eleven init fields, ignoring
all supplied derived fields; each owns one D1a composition. Hardened D1b binding
equality establishes equal actual ADCS label text and complete concrete
MODEL_INERTIAL frame content before C2. Equal labels with different frames and
equal frames with different labels both reject. D1b retains ownership of
concrete metadata text admission.

After that gate, two temporary legacy boresights use the original previous
binding's exact frame-ID object and the two retained component triples. No ID
is created or canonicalized and neither retained label/direction is rewritten.
One existing V5.3 C2 call owns all separation, interpolation and settling,
including zero-transition and unsupported-envelope behavior. The frozen/slotted,
default-free result is unhashable; replace recomputes the complete composition.

The evidence preserves previous -> next order without requiring chronological
order. Fixed MODEL_INERTIAL axes permit comparison at different snapshot times;
this does not establish continuous pointing, view/window fit, transition
readiness or sequence feasibility. D1d sequence/window composition and hardened
catalog uniqueness remain absent. Full attitude, actuator dynamics, slew energy,
J2, maneuvers/delta-v, controller/scheduler and engine integration remain open.
Schema 5 and B2 binding/representation v1 remain unchanged; transition evidence
and temporary comparison boresights are external and recomputed after restart.

V5.6 is **IN PROGRESS through the D1c candidate**. Nothing is staged or committed.

D1c validation: the corrected development gate passed 82 tests in 5.74 seconds,
exit 0. The initial gate had 73 passed and nine failures in 4.21 seconds, exit 1:
five fixture cases used velocities whose pericentres violated B1's existing
outside-Earth domain, three compared evidence from different synthetic support
seams, and one used an incorrect ImagingRequest field name. The new test
fixtures now use circular perpendicular velocities, consistent support evidence
and priority_weight. No production correction was needed.

Final focused gates passed: A, 82 D1c tests in 5.76 seconds; B, 164 D1b tests in
4.07 seconds; C, 111 D1a tests in 26.78 seconds; D, 152 V5.3 ADCS/C3/final-audit
tests in 3.42 seconds; E, 1206 A/B1/B2/C1 foundation tests in 7.81 seconds;
F, 171 C3a/C3b tests in 30.70 seconds; G, 264 H/V5.5 A-F tests in 45.74 seconds.
All seven gates exited 0 with zero failures or skips. Both independent read-only
actual-source reviews (frame/contracts and geometry/references/documents)
reported PASS with no blockers before the full suite.

The ONE complete repository suite on that final production/tests/D314/S006
candidate collected 5325 tests: 5325 passed, 0 failed, 0 skipped and 0 errors
in 261.43 seconds, exit 0; there were no xfails, xpasses or deselections.
Every run used the existing .venv with python -B, inherited
PYTHONDONTWRITEBYTECODE=1, disabled pytest cache and a unique external system
TEMP basetemp. Logs, JUnit counts and durable exit records are outside the repo.

Only this MODEL_STATUS validation-reporting portion changed after the full
suite; production, both D1c test files, D314 and the bounded S006 addition remain
byte-identical to the reviewed/tested candidate. No repeat full suite was run
for this reporting-only edit. Historical D1b and earlier validation below are
not new D1c test runs.

## Historical V5.6D1b candidate record (now committed)

D1a is committed at 7fecab300b87cf4784846ea5e22ef268ab19ed6f, tree
d7e5b90ae002153c71457aa40fbdefaf4b994977. D1b introduces the first orbit-derived
V5.3 CommonFrameBoresightDirection and ObservationManeuverCandidate while
retaining complete concrete FrameDefinition evidence. The candidate is confined
to ops_sim/v5/orbit_observation_boresight.py, two new tests, D313, one bounded
S006 addition and this current-status record. Existing production/tests and the
D1a S008 subsection remain unchanged.

The caller supplies an exact ADCSBoresightFrameId bound to a fully revalidated
MODEL_INERTIAL FrameDefinition. The binding retains the original label object;
actual base-string content and complete concrete frame content determine
equality. Concrete metadata also passes C1/B2 exact scalar-Unicode admission
before comparison; this does not restrict valid legacy ADCS label subclasses.
Both new frozen/slotted/default-free wrappers are unhashable.
The label is not globally unique model-axis authority and no ID is generated.

Exactly one D1a call owns certified-step selection, B1/C1 snapshots, local
pointing and the existing opportunity. D1b checks position/velocity/target-ray
concrete frames and instants, then directly maps the already-computed
spacecraft_to_ground MODEL_INERTIAL components into the existing V5.3 boresight.
No orbit/visibility/C1 calculation or angle-to-vector reconstruction is repeated.
The nested existing maneuver candidate retains the exact D1a opportunity and
D1b boresight; the wrapper preserves the originating instantaneous evidence.

A bare nested V5.3 candidate is not complete proof of frame compatibility with
another independently produced candidate. A later pairwise V5.6 bridge must
compare hardened concrete bindings before historical C2/C3 transition logic.
That pairwise transition/sequence bridge remains absent. Catalog generation
also remains absent: D1a/D1b permit legacy caller ID text and the historical
bulk catalog requires a separate hardened actual-text uniqueness boundary.
There is no global frame registry, continuous tracking, full attitude/roll,
actuator state, angular rate, ADCS power/energy or operational accuracy claim.
J2, maneuvers/delta-v, controller/scheduler and engine integration, and wider
physical fidelity remain open. Schema 5 and B2 binding/codec v1 are unchanged;
all D1b binding/boresight/candidate evidence remains external and recomputed.

V5.6 is **IN PROGRESS through the D1b candidate**.
The pre-correction focused gates passed 98 D1b tests in 3.73 seconds, 111 D1a
tests in 28.59 seconds, 1781 orbit-foundation tests in 37.36 seconds, 242 V5.3
tests in 3.53 seconds, 171 C3a/C3b tests in 31.48 seconds, and 264 H/V5.5 tests
in 50.09 seconds, all exit 0. One full suite passed 5177 tests in 281.31 seconds,
exit 0. That full-suite result predates the concrete-frame metadata correction
and is not final-candidate full-suite evidence.

A late frame/identity review withdrew its initial PASS after finding that A
frame reconstruction alone retains hostile provenance text. Three new red
regressions reproduced rationale-equality, units and parameter-ID bypasses
(3 failed, 148 deselected, 1.16 seconds, exit 1). D1b now reuses the existing
C1/B2 frame-text guard before frame equality. The first expanded gate had
156 passed and eight source-ID fixture failures in 4.56 seconds, exit 1:
the unchanged provenance owner hashes source IDs before its subsequent text
guard. Those metadata fixtures now permit that existing owner validation while
retaining hostile equality; separate ADCS-label hash traps are unchanged.
The corrected expanded D1b gate passed 164 tests in 4.25 seconds, exit 0.
Final post-correction focused gates passed 164 D1b tests in 4.25 seconds,
111 D1a tests in 28.50 seconds, 1781 orbit-foundation tests in 37.97 seconds,
242 V5.3 observation/ADCS/final-release-audit tests in 6.73 seconds,
171 C3a/C3b tests in 52.79 seconds, and 264 H/V5.5 tests in 89.08 seconds.
All six gates exited 0, with no skipped or failed tests. Both independent
actual-source reviewers re-reviewed the metadata correction and report PASS,
with no remaining source blockers. The late frame/identity blocker is resolved.
The author-authorized replacement complete repository suite collected
5243 tests: 5243 passed, 0 failed, 0 skipped and 0 xfailed, in
395.64 seconds, exit 0 (also zero xpasses, errors or deselections).
This replacement run is the final corrected-candidate full-suite evidence.
The prior 5177-test full-suite result remains historical PRE-CORRECTION evidence;
the late production correction hardened complete-frame comparison against
hostile provenance text, reproduced first by the three red regressions above.
All final post-correction focused gates and both corrected-source reviewer
passes remain as recorded above.

Only validation-reporting text in MODEL_STATUS.md changed after the replacement
full suite. Production, both D1b tests, D313 and the D1b S006 subsection remain
byte-identical to the tested corrected candidate. No tests were rerun after
this reporting-only edit.

The first D1b development gate had 93 passed and three
failed tests in 4.54 seconds, exit 1. One fixture used object.__new__ for a
str-backed enum; two axis-aligned vector cases reached the existing C1 exact
cancellation guard. The fixture now uses str.__new__; those C1 cases explicitly
assert unchanged rejection, while conditioned quadrant cases check the vector
reference. Production was unchanged. The initial corrected gate passed 98 tests in
3.73 seconds, exit 0. Historical D1a validation below is not a new D1b run.

## Historical V5.6D1a candidate record (now committed)

C3b is committed at 208b1d4c07a1a4e25caad215ed27fbdf4ae4fa53, tree
676dbd293fef76c0ddfc8e7944958285df331aa0. D1a introduces the first orbit-derived
V5.3 ObservationOpportunity realization for one certified engine step in
ops_sim/v5/orbit_observation_opportunity.py. D312 and one bounded S008 subsection
record this bridge; existing production/tests and S005/S006/S007 are unchanged.

The complete GroundPointDefinition must carry exact GroundTargetId. There is
no implicit conversion from legacy degree-only GroundTarget. External exact
ImagingRequest and ObservationOpportunityId are revalidated without changing
caller IDs. Request/target matching and wrapper identity equality compare actual
base-string content, preserving valid legacy text subclasses while preventing
overloaded equality from inventing identity. The transient wrapper is unhashable.

Exactly one C2c projection certifies visibility. Exact integer bounds and modulo
select one represented engine step in exactly one compact block. No snapping,
merging, uncertainty bridging or per-step enumeration occurs. One additional
B1/C1 snapshot at the selected simulation-relative start derives local pointing
only, using the coast initial state's reference TT epoch without adding its
initial elapsed time. The existing V5.3 opportunity window is [s,s+dt) and its
imaging duration is dt, so s is its sole legal full-duration scheduled start.

Pointing maps C1 off-nadir and local orbital x-to-y azimuth from radians to
degrees. Unresolved azimuth rejects. Exact modeled nadir alone admits azimuth
zero as a coordinate convention, not measured azimuth. Strict radian domains
precede any at-most-one-ulp inward degree-endpoint representation correction.
This snapshot does not establish continuous pointing/tracking, configured
off-nadir feasibility, common-frame maneuver separation, slew readiness,
acquisition success, footprint, resource service, storage, downlink, scheduling,
mission value or controller authorization.

V5.6 is **IN PROGRESS through the D1a candidate**. The committed-C3b baseline
passed 94 tests in 35.39 seconds. Final focused gates passed 111 D1a tests in
142.76 seconds, 1781 C2c/C2b/C2a/C1/A/B1/B2 tests in 186.65 seconds,
215 V5.3 observation/ADCS/scheduled-execution tests in 5.18 seconds,
171 C3a/C3b tests in 89.88 seconds, and 264 H plus V5.5 A-F tests in
105.60 seconds. The single complete-repository gate passed **5079 tests in
1710.77 seconds**, with zero skips, failures or xfails. All baseline/final
focused/full gates exited 0. Both independent read-only actual-source reviews
(observation domain and orbit/geometry) passed with no remaining blockers.
Only this validation reporting text changed after the full suite; production,
both tests, D312 and the S008 addition remain byte-identical to the tested
candidate. All six raw hashes matched the recorded candidate before that edit.

The first D1a development gate had 110 passed and one failed restart-test
expectation in 89.36 seconds, exit 1: raising synthetic target height by 0.01m
removed selected-step C2c support, while the test expected every changed
external variant to succeed. The test now inspects matching C2c evidence and
requires the same support rejection before pointing on both restart paths;
production was not changed. Following geometry-review feedback, the hidden-pass
test's case-specific residual-to-endpoint error explanation was refined without
changing its numerical bound.
The 4968-test full-suite result below remains historical C3b evidence.

Target/policy/search/confinement/origin/selected-step/request/opportunity evidence
remains external to B2 v1 content. Matching external inputs and independently
decoded coast inputs recompute equal same-runtime evidence after schema-5 JSON
restart. No projection, state, geometry or opportunity is persisted; schema,
portable keys, codec/version and fixed digest are unchanged. Catalog generation,
common-frame boresight and full attitude remain absent. Controller/engine
integration, J2, maneuvers and wider orbit fidelity remain open. The candidate
is unstaged and uncommitted for independent actual-source review.

## Preserved C3b implementation and pre-commit review status

C3a is committed at `4ccdab2e2daee160e344261a465db717f10a7307`, tree
`7255503d512507342221d067c93f4a0d0108d44e`. C3b adds a bounded binding of
externally supplied V5.5 ServiceableGroundContact evidence to generated C3a
geometry in `ops_sim/v5/orbit_contact_serviceability.py`. It does not derive
serviceability. Exactly one C3a composition supplies normalized geographic/search
evidence; the external station must match and the complete integer contact
interval must fit inside exactly one source block, allowing edge equality.
No clipping, union, adjacency merging, gap bridging or per-step enumeration occurs.
D311 and the bounded S007 subsection record the contract; S008 is unchanged.

GroundContactId, GroundStationId and both contact boundaries remain the caller's
unchanged evidence, revalidated through the existing V5.5 constructor. Station
matching checks actual text as well as typed identity, preventing overloaded
legacy text equality from inventing a match. Binding equality likewise preserves
distinct actual contact IDs without rewriting external fields. The transient
binding is explicitly unhashable, avoiding reliance on caller-defined ID hashes.

V5.6 is **IN PROGRESS through the C3b candidate**. The committed-C3a baseline
passed 77 tests in 17.80 seconds. Final focused gates passed 94 C3b tests in
32.31 seconds, 1858 C3a/C2c/C2b/C2a/C1/A/B1/B2 tests in 73.69 seconds,
153 V5.5 contact/capacity/transmission/downlink-engine compatibility tests in
2.34 seconds, and 264 H plus V5.5 A-F tests in 86.77 seconds. The single
complete-repository gate passed **4968 tests in 538.52 seconds**, with zero
skips, failures or xfails. All baseline/focused/full gates exited 0. Both
independent read-only actual-source reviews (communications/domain semantics
and geometry/time ownership) passed with no remaining blockers. Only this
validation reporting text changed after the full suite; production, both tests,
D311 and S007 remain byte-identical to the tested candidate.

The first C3b development gate passed 92 tests in 25.09 seconds, exit 0, before
adding the domain reviewer's contact-ID equality regressions and corresponding
fix. There were no intermediate test failures. The 4874-test result below
remains historical C3a evidence, not a C3b execution.

Supported integer sub-step contacts, such as [9,11) within C3a's [9,12), are
geometry evidence only. The unchanged step_downlink still requires its exact
current full engine step. Pure V5.5 consumers accept the nested ordinary contact;
the wrapper remains outside their exact contact type. C3b performs no capacity
calculation or engine/downlink execution. RF/link budget, availability/booking,
network scheduling, regulatory permission, communications power/heat, successful
transmission/acknowledgement and operational throughput remain unestablished.
No external contact ID or serviceability declaration is generated from geometry.

Station/policy/search config/confinement/grid origin and external serviceability
remain outside B2 version-1 content. Schema 5 and portable keys remain unchanged;
JSON restart with independently decoded coast inputs and matching external
arguments recomputes equal same-runtime evidence. No binding/supporting-block
state is persisted. Existing A/B1/B2/C1/C2a/C2b/C2c/C3a and V5.5 production/tests
are unchanged. Observation opportunities, controller/engine integration, J2,
maneuvers and wider physical fidelity remain open. The candidate is unstaged
and uncommitted for independent actual-source review.

## Preserved C3a implementation and pre-commit review status

C2c is committed at `ef5c2853d357bbd56f420bff27194bc657ba94af`, tree
`f2b2f076cb33804df9df86c9b626911f479e0a12`. C3a adds station-typed,
geometry-only contact candidates in `ops_sim/v5/orbit_ground_contacts.py`.
One C2c composition retains its complete normalized geographic/search evidence
and wraps each compact visibility block with its explicit GroundStationId.
Exact station ownership excludes GroundTargetId, including empty projections.
All timing properties delegate to the revalidated source block; there is no
timing modification, per-step materialization or generated GroundContactId.
D310 records this bounded domain adapter, with no new physical law or parameter.

V5.6 is **IN PROGRESS through the C3a candidate**. Fresh committed-C2c baseline:
125 passed in 8.86 seconds. Final focused gates passed 77 C3a tests in 12.38
seconds, 1781 unchanged C2c/C2b/C2a/C1/A/B1/B2 tests in 35.32 seconds,
268 ID/contact-capacity/downlink/engine-domain tests in 1.74 seconds, and
264 H plus V5.5 A-F tests in 47.86 seconds. The single complete-repository
gate passed **4874 tests in 215.17 seconds**, with no skips or xfails. All
baseline/final gates exited 0. Both independent read-only actual-source reviews
(domain/identity and composition/reproducibility) passed with no blockers.
Only this validation reporting text changed after the full suite; production,
both tests, D310 and S008 remain byte-identical to the tested candidate.

The first C3a development run had 76 passed and one failed test expectation
(exit 1): the current Python runtime raises TypeError when dataclasses.replace
receives an init=False field. The assertion was corrected without changing
production admission. There were no other intermediate test failures. The
4797-test result below is historical C2c evidence, not a fresh C3a run.

GeometricGroundContactBlock denotes only conservatively certified geometric
visibility on complete engine steps under the supplied orbit/ellipsoid/elevation
policy. V5.5 ServiceableGroundContact remains externally supplied serviceable
contact evidence; V5.6-generated ServiceableGroundContact remains absent.
RF closure, antenna compatibility, station availability, allocation/network
ownership, weather, regulatory authorization, uplink/downlink availability,
electrical/thermal feasibility and successful acquisition/delivery are not
established. S007's RF/serviceability TO RESEARCH boundary remains unchanged.
A later C3b promotion contract requires explicit serviceability evidence first.

There is no communications capacity calculation, engine integration, controller
selection or observation-opportunity generation. Station/policy/search config,
confinement and grid origin remain external to B2 version-1 manifest content.
Schema 5 and portable keys remain unchanged; matching external inputs recompute
equal same-runtime evidence after JSON restart and independent coast decoding.
No C3a evidence is persisted. A/B1/B2/C1/C2a/C2b/C2c and existing production/tests
remain unchanged. J2, maneuvers and wider physical fidelity remain open. The
candidate remains unstaged and uncommitted for independent actual-source review.

## Preserved C2c implementation and pre-commit review status

C2b is committed at `f211eb634f11b7a74993905f36a818b0641a9ea3`, tree
`6a5f3810ab56a1781149789505c92478ec3128ef`. C2c adds conservative projection
of C2b-certified windows onto complete integer-second engine intervals in
`ops_sim/v5/orbit_visibility_grid.py`. One C2b search supplies visibility;
exact Fraction/integer containment supplies compact blocks on the active
NumericalConfig timestep and an explicit first future engine boundary.
No per-step list is materialized. D309 records the arithmetic and ownership.

V5.6 is **IN PROGRESS through the C2c candidate**. Fresh committed-C2b baseline:
180 passed in 20.41 seconds. Final focused gates passed 125 C2c tests in
8.79 seconds, 1656 unchanged C2b/C2a/C1/A/B1/B2 tests in 27.14 seconds,
361 engine-time/configuration/context/numeric compatibility tests in 1.67
seconds and 264 H plus V5.5 A-F tests in 47.73 seconds. The single complete-
repository gate passed **4797 tests in 202.90 seconds**, with no skips or
xfails. All runs exited 0; there were no intermediate test failures. The
initial C2c gate passed 124 tests in 9.07 seconds before adding the isolated
unresolved-only gap regression recommended by ownership review. Both independent
actual-source reviews passed with no remaining blockers. Only this validation
reporting text changed after the full suite; production, tests, D309 and S008
match the tested candidate. The 4672-test result below remains historical C2b
evidence, not a C2c execution.

Unresolved C2b time generates no block and is never bridged. The explicit
all_search_cells_resolved flag checks actual cell statuses; a search complete
to its width tolerance may still leave this flag false. A grid projection is
only geometric containment, without serviceability, capacity or authorization.
Generated ServiceableGroundContact and ObservationOpportunity remain absent;
there is no engine integration or execution. Point/policy/search config,
confinement and grid origin remain outside B2 manifest content. Schema 5 and
portable keys remain unchanged, with no persisted projection/search evidence.
All existing production/tests, including A/B1/B2/C1/C2a/C2b, are unchanged.
J2, maneuvers and wider physical fidelity remain open. The candidate is
unstaged and uncommitted for independent actual-source review.

## Preserved C2b implementation and pre-commit review status

C2a is committed at `a45bc0db91d83d7c7bd31e561ac4f8098bb59d58`, tree
`e54b54516f01c67837849ba26f5e02b754b5ed1d`. C2b adds bounded adaptive temporal
visibility evidence in `ops_sim/v5/orbit_visibility_windows.py`. The B2-bound
geometry sample grid seeds a breadth-first search; every resolved cell needs
a whole-cell motion bound plus instantaneous and numerical anchor reserves.
Uncertified cells remain UNRESOLVED with a width, evaluation-limit or time-
resolution reason. Adjacent fully VISIBLE cells alone form conservative windows;
their boundaries are cell edges, never estimated event roots. D308 records the
working arithmetic policy, explicit conditioning limits and compressed untouched
seed tails after budget exhaustion.

V5.6 is **IN PROGRESS through the C2b candidate**. Fresh C2a baseline: 270 passed
in 2.29 seconds. Final focused gates passed 180 C2b tests in 20.48 seconds,
1476 unchanged A/B1/B2/C1/C2a tests in 10.08 seconds, 505 compatibility tests
in 3.08 seconds and 264 H plus V5.5 A-F tests in 53.03 seconds. The single
complete-repository gate passed **4672 tests in 193.88 seconds**, with no skips
or xfails. All these runs exited 0. Both independent actual-source reviews
passed after fixing normalized-coast arithmetic ownership and bounding the
untouched seed tail after budget exhaustion. The implementation, tests, D308
and S008 match the full-suite candidate; only this reporting text changed
afterward. The 4492-test result below remains historical C2a evidence.

The first C2b development run had 169 passed and two failed expectations:
coarse unresolved-cell tolerance and low elevated ground clearance do not
guarantee any certified visible cell. Tests now retain that uncertainty and
separately verify finer-width recovery. These were test expectation corrections,
without loosening the production enclosures. The next development run passed
179 tests in 18.59 seconds; explicit interior-event assertions and a real
coincident-geometry exception regression preceded the final 180-test gate.

Point and visibility policy remain externally supplied and outside B2 version-1
manifest content. Identical external inputs/config/confinement recompute equal
same-runtime evidence after schema-5 JSON restart; cells/windows/caches are not
persisted. Generated ServiceableGroundContact and ObservationOpportunity remain
absent, with no engine-grid projection or scheduling adapter. Checkpoint schema
5, codec coverage and all A/B1/B2/C1/C2a production/tests are unchanged. Numerical
reserves do not establish real ephemeris, Earth-orientation, station, RF,
availability, weather or electrical adequacy. J2, maneuvers and wider fidelity
remain unresolved. This candidate is unstaged and uncommitted for source review.

## Preserved C2a implementation and pre-commit review status

C1 is committed at `b0065ba593d71fdec4cf46fe2e09d2534a2793d9`, tree
`7fb4c5e8142c66c992b8e6f84520e371e2f355a2`. The C2a candidate adds
instantaneous finite-segment ellipsoid occultation and an explicit elevation
policy in `ops_sim/v5/orbit_visibility.py`. Its immutable evidence retains
complete point/state/policy inputs and C1 geometry, independently reports
line-of-sight and elevation classifications, and combines them as VISIBLE,
NOT_VISIBLE, BOUNDARY or UNRESOLVED. Surface-endpoint contact, genuine negative
height, interior grazing and spacecraft endpoints have explicit D307 rules.

Numerical allowances distinguish exact geographic identities, represented
Cartesian predicates, A geodesy/phase arithmetic and unresolved conditioning.
They do not certify external B1 endpoint errors or physical-model adequacy.
Geographic and policy inputs remain outside B2 manifest binding. A/B1/B2/C1
production and tests remain unchanged, with checkpoint schema 5 and unchanged
portable keys. Temporal windows, generated contacts and observation/service
adapters remain absent. RF/availability/electrical feasibility and full
attitude are not supplied by C2a. J2, maneuvers and wider physical adequacy
remain open.

V5.6 is **IN PROGRESS through the C2a candidate**. Fresh validation passed:
251 C1 baseline tests; final focused gates of 270 C2a, 1206 unchanged
A/B1/B2/C1, 407 observation/provenance/numeric and 264 H plus V5.5 A-F tests,
all exit 0. Both independent actual-source reviews have no remaining findings
after adding general nonaxis/extreme-domain and interior-grazing references
and clarifying evidence units. The single complete-repository gate passed
4492 tests in 178.20 seconds, exit 0, with no skips or xfails. This result
applies to the final implementation; only this reporting text changed after it.

Intermediate failures were confined to this authorized scope: the first run
had two collection errors from a new source-ID fixture using uppercase text;
that fixture was corrected. A later compatibility gate had 406 passed and
one failure because an existing production AST guard prohibits the identifier
epsilon; the new local variable was renamed projection_error without changing
its arithmetic, then the affected focused gates passed. Earlier successful
C2a development runs passed 263 and 270 tests. The 4222-test full result below
remains historical C1 evidence. The C2a candidate is unstaged and uncommitted.

## Preserved C1 implementation and pre-commit review status

B2 is committed at `b989862913cba581cbbc7512304a7f916bcd3dff`, with tree
`51cb103016d469097d68d81dd23078bcf948abf4`. V5.6 is **IN PROGRESS through the
C1 candidate**. `ops_sim/v5/orbit_geometry.py` adds explicit provenance-bearing
geographic points and instantaneous geometry from a supplied MODEL_INERTIAL
Cartesian state. Derived evidence retains the full point/state and evaluation
instant, includes rotational ground velocity, signed slant-range rate, ENU
elevation/azimuth, surface incidence and a distinct geocentric off-nadir/local
orbital azimuth. The instantaneous local basis is not full spacecraft attitude.

Undefined and numerically unresolved azimuth projections have explicit None,
projection magnitudes, resolution policies and distinct status properties.
Directions are not snapped to zenith/nadir. D306/S008 document numerical-domain
rejections, conditioning, independent analytic/Decimal references and the
separate A phase-error contribution. These are model-equation checks, not
universal angular accuracy, Earth-orientation fidelity or pass-timing evidence.

Geographic point content remains outside B2's manifest binding. C1 supplies no
visibility/occultation test, geometric window, generated contact, observation
opportunity, serviceability, authorization or legacy degree-based adapter.
All A/B1/B2 production and tests remain unchanged; checkpoint schema stays 5.
J2, maneuvers, broader orbit fidelity and model adequacy remain open. C2 owns
later temporal geometry; catalog/content binding and service/observation adapters
need explicit later contracts. No runtime state advances during this evaluator.

Fresh validation passed: 645 baseline B2 tests; final focused gates of 251 C1,
955 unchanged A/B1/B2, 378 observation/ADCS/provenance and 264 H plus V5.5 A-F
tests. The single complete-repository run passed 4222 tests in 184.59 seconds,
exit 0, with no skips or xfails. The first C1 run had 232 passed and one failed
test: its overflow fixture incorrectly assumed sqrt(3)*1e308 exceeded binary64.
The fixture was corrected to 1.5e308 components; subsequent development runs
passed 244 and 251 tests. Independent mathematical and ownership reviews have
no remaining findings after conditioning/derivative coverage and documentation
corrections. The corrected B2 full suite of 3971 remains historical evidence.
No snapshot establishes visibility over an interval, and these numerical checks
do not certify external B1 endpoint errors or physical model adequacy.
The C1 candidate remains unstaged and uncommitted for independent source review.

## Preserved B2 implementation and pre-commit review status

V5.4 is preserved at the annotated `v5.4-final` tag, which peels to commit
`526d131a8ca2df7fdce25d90619f5545806eac1d`.
V5.5 is preserved at the annotated `v5.5-final` tag, object
`20cec2eb34266a20c96a9411e60d45c63c96abdf`, whose direct and peeled target is
F commit `430e87cfc9f1e7781151f97e3dccd1d1d267fe8c`. Preparation H is committed
at `292bcf209ab52f9af4872f24617bcf79a5b398fc`; it preserves frozen release
history while allowing successor files, decisions, and source records.

V5.6 is **IN PROGRESS through the B2 candidate**. V5.6A is committed at
`b3dcd0deb76199523092bbea3c4d688dfd73cf83`; it supplies immutable TT
epochs, fractional geometry instants,
WGS84 reference-ellipsoid definitions, explicit geodetic coordinates, complete
model Earth-fixed/inertial frame definitions, and pure position/direction/state
transforms in `orbit_config.py` and `frames.py`. Uniform rotation has explicit
initial phase and signed rate; the TT date does not imply Earth orientation.
A's historical boundary propagated no orbit. B1 is committed at
`1d01bc481e514b9639ba444b532417b00b9b1232` and supplies pure standalone
Cartesian two-body coast evaluation in `ops_sim/v5/orbit.py`, from explicit
initial state/mu to a requested signed TT instant in the same model-inertial
axes. It supports conditioned bound ellipses, including circles, with a
conservative pericentre-outside-equatorial-sphere admission rule. The scaled
universal-variable solver has explicit residual, arithmetic and duration
limits; S008/D304 describe its assumptions and independent references.

The B2 candidate binds per-run immutable coast definitions and solver policy
to a content-derived manifest ID, checked at construction, context validation,
checkpoint capture/restore and engine execution. Its portable definition codec
is separate from schema-5 checkpoints, whose existing manifest ID field carries
the binding. Pure explicit queries recompute orbit evidence at the current
runtime clock; no propagated state is cached and engine steps do not query the
orbit implicitly. Orbit-free legacy inputs keep their seven positional arguments.
No contact or observation opportunity is generated; no perturbation or maneuver
is added. Downlink still models no concurrent battery/thermal/degradation
evolution. J2 and broader orbit fidelity, maneuvers/delta-v, stationkeeping,
propulsion ranges and long-horizon model adequacy remain open. The digest covers
only D305's specified coast/manifest/numerical/world inputs, not the complete
hardware/experiment content, external sources, authentication or model adequacy.

Independent review found incomplete residual-to-endpoint accounting in B1's
original numerical budgets. Corrected root contributions include initial
velocity and the reconstructed-radius denominator; phase, reconstruction and
reference errors remain separate. Executable propagation and output accuracy
are unchanged. Corrected focused B1 checks pass 186 tests. The prescribed
1000-case review sweep has 989 accepted endpoints within corrected budgets
and 11 explicit accuracy rejections, with six OLD-budget exceedances. B1 uses
independent analytic and Decimal elliptic endpoint references, supplemented by
invariants and deterministic query/recovery checks. These are internal software
checks of the bounded model, not operational accuracy, sun-synchronous
evolution, spacecraft calibration/lifetime, an integration release or V5.6
completion. The earlier 3140-test full-suite result belongs to the committed
A candidate. The pre-correction B1 run passed 3309 tests in 576.30 seconds;
it is historical evidence and did not detect the incomplete budget. The corrected
B1 candidate passed 186 B1 tests, 124 unchanged A tests and 264 H plus V5.5 A-F
tests. Its one corrected full-suite run passed 3326 tests in 179.98 seconds,
exit 0, with no skips or xfails. These are historical B1 results, not B2 gates.

Independent review found two B2 text-boundary defects: str subclasses could
hide the reserved manifest namespace, and surrogate-bearing Python strings
could alias valid Unicode identities and change value across JSON round trips.
The correction requires exact built-in str and Unicode scalar-value text at
B2's portable/known-identity boundaries. Surrogates and subclasses are rejected;
valid Unicode, including non-BMP characters and distinct NFC/NFD spellings, is
preserved without normalization. Seven pre-repair review regressions failed
intentionally. All 55 sampled valid canonical payload bytes/IDs and the fixed
literal fixture remain unchanged. Format/version, schema 5 and physics are
unchanged; this is no improvement in orbit accuracy or authentication coverage.

The prior B2 full run of 3591 passed in 171.16 seconds is historical
pre-correction evidence. The seven intentional red regressions failed in 0.79
seconds (exit 1); their corrected counterparts passed in 0.84 seconds. Corrected
focused gates passed 645 B2 tests, 310 unchanged A/B1 tests, 209 existing
context/checkpoint/transaction tests and 264 H plus V5.5 A-F tests. The single
corrected full-suite run passed 3971 tests in 179.40 seconds, exit 0. All green
gates exited 0 with no skips or xfails; no unexpected test failure occurred.
Direct/portable-restart continuations and all four engine paths remain covered.
The candidate stays unstaged and uncommitted for independent source review;
these checks do not complete V5.6 or establish broader physical model adequacy.

## Preserved V5.5 implementation and audit-writing history

At audit-writing time F described the release as RELEASE-CANDIDATE COMPLETE,
pending human review and explicit tag creation. That pre-tag wording in the
frozen audit is historical; the actual final release tag now exists as recorded
above. V5.5A is committed at
`b6c42a79c7ed28c6abb6685692e0a117cbdd26dc`; it adds typed externally supplied
serviceable ground contacts, makes the nominal downlink data rate a required
communications configuration parameter, and provides the pure Level-1
relationship `nominal contact capacity = nominal downlink data rate ×
serviceable contact duration`.

V5.5B is committed at `aeba9d10493fcf7d5dd36d31556ad42f5f825d7a`.
It adds authoritative top-level delivery/progress state for strictly positive
partial transfers and completed acquisition deliveries, plus checkpoint schema
5 persistence and deterministic restart. V5.5C is committed at
`f1b655c85965168aac4f694f28bdc73e78762b82`; it adds pure partial/complete
transmission arithmetic for one selected onboard acquisition record and one
externally supplied serviceable contact.

V5.5D is committed at `2a6674b3b48b34f68d9c2e34be97d63d0c2b2066`.
It adds atomic `SimulationEngine.step_downlink` execution for exactly one
caller-selected record per aligned full-step contact. PARTIAL updates or
appends persistent transfer progress while retaining the full onboard record.
COMPLETE removes the full record from onboard storage, removes its partial
progress if present, and appends completed-delivery ground-custody truth,
thereby releasing storage. Unused contact capacity is not automatically
reassigned to another record. The live checkpoint remains schema 5.

V5.5E is committed at `96ffc1f2db7759e5b373afd3b2e5d14195a5f556`.
It adds integrated release demonstration evidence only; production behavior
is frozen through V5.5D and the live checkpoint remains schema 5. Its synthetic
four-contact scenario services one caller-selected record per interval,
demonstrates schema-5 JSON restart and deterministic repeat equality, and
produces the sequence PARTIAL/PARTIAL/COMPLETE/COMPLETE. Partial records retain
their full onboard storage. Completed records release their entire stored
volume, and unused capacity is not automatically reassigned to another record.

V5.5F is final audit and freeze evidence only. It adds no production or example
behavior and changes no equation, configuration value, state contract,
checkpoint schema, runtime behavior, public API, physical source, literature
value, or spacecraft numerical value. Completion of the frozen release means
internal software evidence for the bounded implemented scope; it does not mean
external calibration, real delivered-throughput validation, flight
qualification, operational validation or readiness, or digital-twin status.

Communications power and concurrent physical evolution are not modeled during
V5.5 downlink bookkeeping. Completion here is modeled link-service completion
of one acquisition record, not mission, product, or customer completion. V5.5
still adds no orbit-derived contact generation, scheduling or controller
policy, and no mission, product, or customer completion behavior.

The KazEOSat-like reference configuration uses the Airbus public-specification
nominal X-band rate of 270 Mbit/s. This is a nominal data-link rate, not a
detector-generation rate, recorder-write rate, protocol-adjusted or measured
net throughput, or guaranteed operational throughput. Contact serviceability
is supplied by an external owner; V5.5A derives no contact geometry, AOS/LOS,
visibility, elevation, RF link budget, coding, weather loss, or arbitrary
efficiency factor.

V5.4 carries the exact V5.3 acquisition sample-grid proxy into continuous
equivalent-bit bookkeeping, gives each immutable acquisition-data record a
caller-supplied identity, evaluates decimal-GB whole-record capacity with
complete-sequence `math.fsum`, and preserves insertion-ordered records as
explicit persistent spacecraft truth in checkpoint schema 4. Pure
imaging/storage authorization composes existing physical authorization with
storage admission without mutation. D1 constructs completion evidence before
authoritative commit, and the public D2 transaction atomically commits the
exact V5.3 physical endpoint and exactly one C-proposed record. Supported
imaging or storage nonauthorization commits neither; duplicate record identity
and ordinary transaction failures propagate with complete rollback.

Schema 4 preserves ordered storage truth and rejects schema 3 without silently
inventing an empty historical recorder. E demonstrates twelve consecutive
successful public transactions, 144,000 derived equivalent bits,
direct-versus-schema-4 JSON restart equality across a checkpoint split after
six successes, an exact-full 36,000-bit synthetic capacity boundary at the
third record, and atomic rejection of the fourth. Occupancy remains derived
from stored records; no byte count or redundant occupancy field is
authoritative storage truth. The frozen V5.4 checkpoint remains schema 4 at its
tag; V5.5A preserved that live schema before B advanced it to schema 5.

V5.5B introduced delivery state and persistence. V5.5C and V5.5D subsequently
added pure transmission arithmetic and atomic downlink execution, including
whole-record removal on completed delivery. Communications power and concurrent
physical evolution, controller or scheduling policy, and
mission/product/customer completion remain outside this release. Completed
acquisition delivery is modeled custody truth; it is not customer, product, or
mission completion.

Major deferred boundaries remain explicit:

- compression algorithms or factors, packet/file overhead, recorder
  throughput, storage/OBC power or heat, record removal, overwrite or eviction,
  and further onboard data-handling fidelity remain outside the frozen V5.4
  scope; KazEOSat recorder capacity and hardware remain uncalibrated and TO
  RESEARCH;
- communications electrical-power and heat coupling, RF/link-budget effects,
  protocol overhead, and non-ideal link-service behavior remain deferred beyond
  the frozen V5.5 scope;
- V5.6 owns orbit-derived opportunities, opportunity-to-common-frame
  conversion, and deeper orbit/attitude/environment coupling;
- V5.7 owns `MissionRequestId`-to-`ImagingRequestId` binding, mission/product
  completion, and controller or scheduling policy; and
- V5.8 owns variable-duration execution, substeps, multirate/event methods,
  general timestep refinement, and convergence gates.

Full quaternion/actuator and reaction-wheel dynamics, ADCS slew-energy,
off-nadir GSD/swath, ground-speed duration, payload brownout/partial-image
behavior, and thermal operating-range flight rules also remain outside the
implemented scope.

## Historical status at the 2026-08-31 handoff

The following table describes the repository at commit `a588fcd` on
`v5-redesign`. Its milestone wording and validation counts are preserved as a
historical handoff snapshot rather than silently rewritten after the V5.2 and
V5.3 work. "Validated" means covered by the stated internal tests or accounting
checks; it does not mean externally calibrated, flight-qualified, or
operationally validated.

| Subsystem / capability | Status | Current fidelity | Validated? | Key files | Next work |
|---|---|---|---|---|---|
| V4 operational baseline | **COMPLETE** | Hourly, intentionally simplified operational proxy with geometry, contacts, planning, lifecycle/debris, autonomy, power/thermal stress, targets/pointing, packets, manoeuvre, and RUL layers | Yes — internal regression and reproducibility at `v4.0-final`; no external operational validation | `run.py`, `ops_sim/simulator.py`, `ops_sim/policies.py`, `paper_suite.py`, `PROJECT_CANON.md`, `FINAL_CONFIG.md` | Reproduce from `v4.0-final`; do not silently alter its semantics |
| V5 architecture | **COMPLETE** | Stable identities and provenance; immutable input graph; separated mutable runtime domains; seconds-based fixed phases; atomic completed steps; schema-3 checkpoints | Yes — type/invariant, identity, rollback, deterministic checkpoint, and JSON round-trip tests | `ops_sim/v5/ids.py`, `provenance.py`, `configuration.py`, `state.py`, `context.py`, `checkpoint.py`, `engine.py` | Preserve contracts while adding missing subsystem physics |
| EPS | **IMPLEMENTED / NOT FINAL** | Bus-side W/Wh model with component loads, cosine-incidence solar proxy, battery efficiency and power/capacity limits, curtailment, unmet load, and conservation ledger | Yes — hand cases, limiting cases, conservation, numeric hardening, transaction, and repeated-run tests | `ops_sim/v5/eps.py`, `eps_system.py`, `eps_validation.py`, `power_loads.py`, `solar.py` | E2 must apply retained battery and solar capability; F2 must finish timestep/release audit |
| Thermal | **IMPLEMENTED / NOT FINAL** | Generic lumped nodes and conductive links; explicit sink radiation, explicit applied heat, and explicit-Euler interval transitions | Yes — conduction/radiation hand calculations, sign and identity ledgers, node-order independence, limiting cases, and numeric guards | `ops_sim/v5/thermal_config.py`, `thermal.py`, `state.py` | F2 convergence evidence; post-V5.6 forcing, node, radiator/view-factor, attitude, and heater review |
| Thermal coupling | **IMPLEMENTED / NOT FINAL** | One EPS proposal feeds current-interval battery conversion heat into one thermal proposal; explicit source inputs and caller-resolved served-power heat routing | Yes — same-duration coupling, no double counting, by-ID update, rollback, conservation, restart, and repeated execution | `ops_sim/v5/thermal_coupling.py`, `thermal_routing.py`, `engine.py` | Keep routing allocation explicit; reassess electrothermal coupling after D2B/E2 and at F2 |
| Degradation state | **COMPLETE** | Named battery usable-capacity retention, cumulative battery-side Wh throughput, and solar-generation retention with configuration initial conditions and schema-3 persistence | Yes — bounds, context reconstruction, checkpoint/JSON restart, fresh identity, and no unintended telemetry/evolution | `ops_sim/v5/state.py`, `configuration.py`, `checkpoint.py` | D2B must evolve the state transactionally |
| Degradation physics | **IMPLEMENTED / NOT FINAL** | Pure D2A throughput plus linearized calendar/cycling damage with separate normalized Arrhenius factors and explicit representative temperature | Yes — 52-case D2A gate including hand calculations, limits, overflow/underflow, no clipping, purity, and numeric interoperability | `ops_sim/v5/degradation.py`, `tests/test_v52d2a_degradation_physics.py` | D2B engine integration, provenance-backed coefficients, sensitivity ranges, then deeper post-V5.6 ageing if justified |
| Solar degradation | **FOUNDATION ONLY** | Retention state plus a pure explicit external retention-loss transition; no radiation or elapsed-time law | Yes — state/checkpoint and explicit zero, nonzero, invalid, and excessive-loss cases | `ops_sim/v5/state.py`, `configuration.py`, `degradation.py` | E2 applies retention to solar capability; later add radiation/NIEL response only after environment and cell evidence exist |
| Payload | **FOUNDATION ONLY** | Payload family and supported-mode configuration identity; no V5 payload power, observation, data-generation, or quality physics | Structural contracts only | `ops_sim/v5/configuration.py`, `mission.py`, `ids.py` | Implement sourced optical-EO payload and data-product causality |
| ADCS | **FOUNDATION ONLY** | Subsystem configuration identity only; no V5 attitude state, slew, settling, pointing, or feasibility physics | Structural contracts only | `ops_sim/v5/configuration.py`, `ids.py` | Implement reduced-order attitude/pointing constraints and connect them to payload feasibility and thermal exposure |
| Communications | **FOUNDATION ONLY** | Subsystem configuration identity only; no V5 link, contact-capacity, or delivery physics | Structural contracts only | `ops_sim/v5/configuration.py`, `knowledge.py`, `ids.py` | Implement geometry-dependent communications and explicit data delivery |
| Orbit / propulsion | **FOUNDATION ONLY** | Common-world identity/horizon plus initial and remaining delta-v state; no V5 orbit propagation or manoeuvre transition | Structural state/configuration contracts only | `ops_sim/v5/world.py`, `configuration.py`, `state.py`, `ids.py` | Implement orbit/environment geometry, physical delta-v accounting, and manoeuvre-driven future geometry |
| Controller | **FOUNDATION ONLY** | Controller identity and mutable plan/replan memory behind fixed engine phase hooks; no professional `MissionOperationsController` implementation | Structural, phase-order, checkpoint, and hidden-state-boundary tests only | `ops_sim/v5/controller_state.py`, `engine.py`, `knowledge.py`, `mission.py` | Implement the common ground-knowledge-based rolling planner and flight rules |
| Numerical convergence | **NOT STARTED** | Configurable seconds-based timestep and hardened finite arithmetic exist, but no accepted timestep or convergence campaign exists | No — arithmetic and timestep contracts are tested, convergence is not | `ops_sim/v5/run_config.py`, `engine.py`, `eps.py`, `thermal.py`, `degradation.py` | F2 immediate V5.2 audit; V5.8 broader numerical/convergence gate |

## Historical release interpretation at that handoff

V5.2 must remain **IMPLEMENTED / NOT FINAL** until D2B, E2, and F2 pass. Only
then should `v5.2-final` be created. Later subsystem rows must not be promoted
from **FOUNDATION ONLY** merely because corresponding V4 proxy logic exists;
V4 and V5 have separate model contracts.
