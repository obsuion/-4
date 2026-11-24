# M2-B4: bounded illumination windows and uncertainty refinement

Candidate on accepted M2-B3 a12c0a5a0d5be53864f46c1e9869cd0570c47985, branch m1-assembly-20260930-73347d98. Exactly six additive files; every existing owner remains unchanged. This is a conditional numerical geometry search, not an event-time estimator or physical qualification. Combined qualification is UNRESOLVED for every result.

## Input authority and reuse

IlluminationWindowRequest(coast, table, start, end, requested_resolution_seconds, policy) is frozen and slotted. Accepted B3 constructors rebuild the complete original J2 trajectory, all F4 numerical/version/provenance inputs, concrete frame, original TT epoch, interval and full Sun table. The interval is nonempty and inside the closed table domain. No deferred scenario owner is imported. Resolution accepts only finite positive built-in int/float, excludes bool/subclasses, rejects integer rounding, normalizes to binary64, and is at most 2**41 SI seconds. Input normalization invokes no propagation.

IlluminationSearchPolicy contains five exact built-in positive integer ceilings: max_trials<=16, max_integration_steps<=65536, max_geometry_cells<=65536, max_retained_evidence_units<=393216, max_arithmetic_operations<=33562624. No implicit budget defaults are selected by the production owner. Examples declare their own smaller policies.

Only enclosure_policy.step_seconds changes between trials, by exact division by two. The initial state/instant, gravity, nominal RK4 policy, enclosure max_steps/radius floor/precision/Picard limit, complete Sun/provenance, epoch and endpoints remain unchanged. A common-authority digest binds every fixed quantity. Each full numerical B3 request also has its own accepted interval_request_digest. All numerical changes and every attempt retain their immutable request/digest. No rounded state becomes a new initial state.

## Whole-cell proofs and windows

Each admitted trial calls accepted evaluate_interval_illumination exactly once; B3 owns its B2 propagation. B4 does not separately propagate, approximate a root, shrink an existing tube or evaluate nominal orbit samples. B3 cells retain their original continuous Picard/Taylor tubes, exact rational Sun bounds, dependent ray s-r, geometry bounds and reasons. M2-A's half-ray and closed ellipsoid convention remain unchanged: proved contact is OCCULTED; an interval merely straddling contact stays UNRESOLVED.

Output windows are chronological and gap-free. Reporting ownership is [start,end), with the final request endpoint included. All underlying source certificates were proved on CLOSED cells, so this reporting convention never authorizes an excluded proof endpoint. Compatible adjacent spans merge only when both assessment and reason tuple are equal. Every merged span retains an ordered list of CellSupport exact covered subintervals plus source trial/cell index and trial digest; their union covers the merged span. Complete B3 and B2 results stay available in trial history. Domain uncertainty is never relabeled as an event.

Exact step halving with the same anchor, request edges and Sun knots makes the finer temporal grid nested. A linear sweep matches each fine cell to one preceding coverage piece. For any overlapping time t, both independently validated B2 boxes contain the SAME original-authority real trajectory r(t); both B3 Sun envelopes contain the SAME affine path and correctly rounded B1 component values. Their intersections therefore contain the common values even when neither full box is a subset of the other. Restricting an older certificate to a covered subinterval preserves that certificate. B4 carries such older certified coverage across new UNRESOLVED cells, checks required box intersections, and fails atomically on opposing certificates anywhere on a closed overlap, including a shared endpoint. This is a temporal containment argument, not a claim that smaller steps universally produce nested state boxes.

Active unresolved coverage cannot replace older certified coverage. Its maximum connected width is computed across ALL consecutive UNRESOLVED pieces, even if diagnostic reasons prevent their merger. Splitting one unknown region into many narrow cells does not improve this metric. Repeated complete B3 evaluations can supply stronger evidence, but improvement or eventual classification is not guaranteed.

## Separate completion meanings and stopping

- coverage_complete means a complete whole-interval partition is published.
- all_spans_classified means no published span is UNRESOLVED.
- temporal_resolution_achieved means each maximal connected UNRESOLVED component has width<=requested_resolution_seconds (or no uncertainty remains).
- status/reason distinguishes classified, resolution_reached, budget_exhausted, numerical_limit and computational_failure.
- combined_qualification remains UNRESOLVED with B3's unchanged physical-error reasons.

An uncertainty span may contain no transition, one or several transitions, contact or a domain problem. Even resolution_reached does not assert event existence, uniqueness, ingress/egress, or event-time accuracy. No consumer/executor authorization is introduced.

Stop on all-classified coverage, the declared connected-width criterion, a global ceiling, a nonrepresentable/inadmissible further halving, or upstream/computational failure. Binary64 conversion of h/2 must equal the exact Fraction target; values below accepted F3 2**-20 s reject explicitly. Internal coverage times stay exact Fractions and are never rounded to GeometryInstant.

Budget exhaustion or a numerical step floor can retain ONLY the last completed whole-interval partition, with explicit stop status, uncertainty and resolution flag. If none exists, windows=None and coverage_complete=False. A failed B3 trial, late geometry/integration failure, integrity contradiction or unexpected upstream arithmetic/value/runtime exception yields computational_failure with windows=None; completed trial diagnostics remain. No partially computed refined partition is published. Failure does not imply no eclipse.

## Global reservations and actual counters

Before each B3 evaluation, exact time-only B2._plan counts every prefix and both signed original-anchor legs: sum(ceil(abs(span)/h)). Only admitted B2 plans enumerate their <=4096 step boundaries. B3's bounded union of those boundaries and <=1022 interior Sun knots supplies planned geometry g<=5118; a known B2 horizon/work rejection has no geometry plan and executes B3's cheap bounded rejection path once if admitted by global quotas.

Charge global reservations before evaluation, never refund a failed call:

- integration steps: planned B2 count n;
- geometry cells: g (zero for an absent geometry plan);
- B3 rational scalar operations: 512*(1+g);
- retained evidence units: n+5*g;
- Picard attempts: n*original_max_picard_iterations, a derived reservation, at most 1048576 globally.

Rejected considered plans are recorded separately and may exceed a ceiling; they consume no integration reservation or evaluation. Admitted reservations/executed work stay within every global quota. Max_trials bounds successful, failed and rejected attempts; exhausting it does not invent an additional trial.

Actual completed steps, Picard attempts (including unsuccessful attempts), geometry cells and B3 scalar operations come from returned B3/B2 diagnostics. b3_evaluation_calls counts dispatched evaluations; propagation_calls counts known returned B3 propagation diagnostics. If a call raises before returning evidence, its exception_failed attempt retains charged reservations, actual_work_accounting_complete=False, and known counters are lower bounds excluding UNKNOWN work in that call. Unknown work is not fabricated as zero.

Retained units are a conservative cell/reference accounting metric, not bytes: history contains all trial B3 geometry and B2 retained coverage cells, bounded by sum(n+g); the latest pieces, support records/references and merged windows cost at most 4*last_g. Thus sum(n+5*g) bounds the reported retained units. Failure with no published windows counts the retained trial-cell history. At most 16 trial/input records, bounded complete tables and fixed per-cell record schemas remain; no unlimited duplicate support history is built. Merge and overlay sweeps are linear. Tables and input metadata remain governed by accepted owners; these ceilings are not a low-memory or wall-time promise.

max_arithmetic_operations counts accepted B3 rational scalar operations only. F3's accepted finite expression/Picard/precision bounds are unchanged; orchestration comparisons, canonical digests, time arithmetic and sorting are separately bounded by trial/cell/input limits. Geometry operands retain B3's 16384-bit numerator/denominator ceiling. B4 exact time operands/results have a 2048-bit ceiling; valid accepted binary64 time/step envelopes fit it. No ambient Decimal context, unexplained tolerance, integration-step enlargement or root-fitting epsilon enters certification.

## Strict input-only reconstruction

Version-1 M2_ILLUMINATION_WINDOW_REQUEST uses canonical codec version1, domain m2-illumination-window-request-v1. The document binds full coast/table/provenance, original epoch/endpoints, requested resolution and all budgets. Unknown/missing/duplicate fields, wrong types/versions, noncanonical normalization, bad digests and redigested invalid authorities reject. Save is exclusive-create; loading rebuilds inputs without propagation. Derived windows, guesses, histories and cached proofs are never serialized authority. Offline evaluation recomputes from original inputs.

## Verification and examples

Final source-bound local gates passed: **195 new tests + 610 relevant existing tests**, 805 distinct tests, zero final failures/errors/skips. Gate commands, exit codes, XML, full logs and file hashes are in the external review archive. No full simulator suite was run. The final reporting contract was added after these runs; every executable/test/fixture source hash captured by either successful gate still matches the candidate. Independent analytic references use the inherited synthetic equatorial J2 circle R=2m,n=17/16s^-1 and exact whole-arc sine/cosine inequalities, plus independent ray/cross-product geometry. No convenient example value becomes spacecraft hardware data. Point witnesses may show why endpoint-only detection is insufficient; they are not the whole-interval oracle.

Tests cover wholly illuminated/occulted arcs, changing Sun with illuminated endpoints and occulted interior, real tube/uncertainty improvement, multiple-transition ambiguity and closed contact, nonaligned knots, negative/cross-anchor/exact grids, hand-calculated prefix work, domain reasons, every cumulative quota, original-authority preservation, no redundant propagation, late failures/integrity conflicts, strict documents/digests, determinism and full offline fresh-process replay.

## Open obligations

Combined physical Sun qualification, event search and event-time accuracy, finite solar disk/penumbra, physical ephemeris/interpolation/time/frame alignment error bounds, Family B, station/target visibility, environmental forcing, executor/checkpoint integration, day-scale/long-horizon usefulness and wider M2 remain open. This is neither a spacecraft winner nor full-M2/full-V5 completion. Stop for independent review.

## Measured validation and bounded examples

The initial focused gate returned 193 passed / 1 failed, exit1. Its test required OCCULTED publication at requested resolution1/256s, even though the legitimate connected uncertainty component already met that width and could contain both transitions and the occulted interior. The assertion was corrected to preserve that uncertainty, and a tighter1/512s case was added with an independent whole-arc Taylor/cross-product oracle. No tolerance or production algorithm was weakened. The source-bound failed run/log and two-case bounded diagnostic are preserved. An external preservation-helper placeholder typo initially failed Python parsing before any audit/source mutation; only that external helper was corrected.

Final new-test gate: 195 passed, exit0, pytest29.58s (process29.969089s). Adjacent B3/B2/B1/point/document/F3/F4-binding/canonical-codec gate: 610 passed, exit0, pytest52.25s (process52.684232s). These two final gates ran concurrently with separate external basetemps, so their process costs are not single-worker throughput measurements. All captured executable/test/fixture bytes were stable during each gate.

All eight short examples ran and replayed as full evidence in fresh local offline Python processes, comparing every window, support, trial identity, rational geometry bound, B2 tube, reason and work counter. Wall time is measured separately and excluded from the equality comparison. No general cross-platform bitwise guarantee, external scientific validation or day-scale usefulness follows.

| Example | Status | B3 calls | Reserved/completed integration steps | Max connected uncertainty(s) | First/replay evaluation(s) |
|---|---|---:|---:|---|---:|
| illuminated | classified | 1 | 1/1 | 0 | 0.060510/0.059957 |
| occulted | classified | 1 | 1/1 | 0 | 0.061689/0.060542 |
| refinement | resolution_reached | 6 | 63/63 | 1/1024 | 1.395606/1.400207 |
| domain | resolution_reached | 5 | 31/31 | 1/256 | 0.760170/0.783748 |
| budget-failure | budget_exhausted | 2 | 3/3 | 1/32 | 0.155212/0.155592 |
| upstream-failure | computational_failure | 1 | 2/0 | None | 0.042508/0.051007 |
| numerical-limit | numerical_limit | 1 | 1/1 | 1/1048576 | 0.061332/0.062833 |
| external | classified | 1 | 1/1 | 0 | 0.067058/0.066410 |

The refinement example covers [128,128+1/32]s. It uses six original-anchor trials, steps1/32 through1/1024s, 63 completed steps, and maximum unresolved-component width1/1024s. Its requested criterion is1/512s. It includes conditional ILLUMINATED, OCCULTED and UNRESOLVED windows; the reported occulted span is [128+15/1024,128+17/1024)s; its supporting closed certificates also establish occultation at both endpoints. This is a certified model interval, not inferred ingress/egress timing. The coarser1/256s diagnostic legitimately leaves the narrow interior uncertain. The domain example retains a Sun-vector domain ambiguity at the midpoint; it never becomes an event.

The budget example completes only two trials (1+2 steps), then retains their last full coverage and records a rejected4-step plan with zero reservation/evaluation. The numerical-floor example stops with a complete unresolved1/2**20s interval while the requested1/2**22s criterion is unmet. The upstream-work-limit example has no windows. Synthetic examples use inherited assumed mathematical values; the external example reuses the existing archived Horizons table with a synthetic orbit for ten seconds, without fetching data.

Reproduction from the source directory, with an existing environment and a fresh external <OUT>:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m examples.m2_illumination_windows_demo --kind refinement --offline --write-inputs '<OUT>/request.json'
python -B -m examples.m2_illumination_windows_demo --inputs '<OUT>/request.json' --offline
python -B -m pytest -q -ra -p no:cacheprovider --basetemp='<OUT>/pytest' tests/test_orbit_sun_windows.py tests/test_orbit_sun_windows_document.py
```

## Preservation and candidate status

The original baseline and accepted M2-B3 preservation addendum remain authoritative and unchanged. Preserve all402 accepted tracked files, both deferred scenario files, separate live HEAD/tree/branch/index, original12 pending statuses/bytes plus the accepted preserved untracked review_v53f4a_final.txt (SHA-256 eb8d923fb2985c59a01b2fca3d39564a613cb04ea2800c3bec3b66e6ecd143a9), all364 frozen fingerprints, all41 tags/peeled targets and ignored path/size/mtime inventory. The live state has13 protected pending paths; it is not asserted to match a twelve-path baseline exactly. No staging/commit/tag/push, live integration, deferred input import, campaign, process control or persistent Git configuration change is part of this candidate.
