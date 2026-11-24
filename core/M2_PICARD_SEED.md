# M2-B12: one bounded alternative Picard seed

This uncommitted proposal changes internal search only. No public schema,
policy version, radius floor, force model, time partition, arithmetic precision,
nominal propagator or downstream illumination owner changes.

## Contract and proof boundary

A trial seed is a search heuristic, not evidence that a solution exists inside
it. The original width/8 inflation and successful first-domain execution path
remain unchanged. Only the first trial's exact radius-floor rejection permits
one alternative, and only after the original full six-dimensional incoming box
passes the same domain predicate and capacity remains in the existing budget.
The rejection consumes attempt 1. The alternative is checked as attempt 2.

For incoming coordinate [lo, hi], define s=max(1, |lo|, |hi|). The alternative
padding is (hi-lo)/16+s*10^-30, with the original per-query outward rounding;
endpoints are rounded down/up. It is rebuilt from the full incoming box.
Explicit whole-box containment is required before the next trial. Nothing
shrinks, clips, projects, replaces with a nominal point, or re-anchors that box.

The unchanged radius predicate establishes separation from the singularity.
The original strict inclusion X+[min(0,h),max(0,h)]*F(T) inside the interior of
T is required to accept a tube. Together with the smooth original J2 field on
the admitted domain, these retain the original Picard existence/continuation
argument for every initial point in X. This is the existing tested numerical
enclosure argument, not a machine-checked formal proof. Seed selection alone
proves nothing. Subsequent width/8 inflation, sixth-order Taylor coefficients,
seventh-order remainder, signed time and endpoint-domain checks are unchanged.

No second alternative, padding parameter, later-domain fallback, arithmetic
retry, budget reset, or general exception recovery is introduced. Max budget 1
therefore retains the original rejection. Global arithmetic attempt accounting
and the returned per-step count include the rejected trial. Frozen downstream
reservations already allow max_picard_iterations per step.

## Local evidence and independent checks

The fixture preserves boundary3450's complete Decimal endpoints from accepted
B11 result SHA-256
a0ac2a8c910e886c8f75223e31e0ebd83861bf3d801742acf6e0419db398055f
and the complete original H5 input document, including gravity and policy
provenance. Archive SHA-256:
516c70384dd94c0eeb322f06d93fd9768c0938418fc1114471ac57aff48786bb.

It is an arbitrary supplied local numerical set for one 5-second step labelled
[17378,17383] s. It is NOT a checkpoint, accepted trajectory continuation, H5
coverage, or proof about long-horizon wrapping. Full input/trial/image/tube/
endpoint bounds and actual domain/inclusion outcomes belong to the external
source-bound probe logs. The original rejects at attempt 1 before RHS/Taylor;
the candidate's local probe accepts at attempt 2 with unchanged predicates.

Independent synthetic equatorial circular J2 dynamics use r=2 m, mu=8 m^3/s^2,
J2=11/32, reference radius=1 m and n=17/16 rad/s. The incoming set contains the
exact circular initial condition but has a nontrivial x interval that triggers
the alternative. For H=1/1024 s, exact rational sine/cosine inequalities bound
the whole signed arc, and degree-19 Taylor polynomials with exact twentieth-
derivative Lagrange bounds independently bracket the endpoint. No geometric
tolerance is guessed or widened. This checks one analytic trajectory; the
unchanged interval inclusion is what covers the entire incoming numerical set.

Budget edges, invalid incoming/alternative sets, full-set containment, strict
boundary equality, unrelated guards, arithmetic failures, later domain failures,
negative steps, hostile ambient Decimal context and atomic public failure are
tested. A preregistered 15-query short F3/B2/B3/B4/B6 corpus compares complete
results, all bounds/counters and every originally admissible first-domain trace
before and after edits. Regression commands/results are in the external package.

## Scope and limitations

No fresh H4/H5, day campaign, ownership preflight/calibration, Sun fetch or
checkpoint continuation is authorized or performed. B11 remains accepted
negative evidence. Its external review's 46 assertion groups and zero new
numerical evaluations are externally reported evidence, not B12 testing.
Combined qualification remains UNRESOLVED. B7 cause remains UNKNOWN.
A successful local seed mechanism does not establish H5 success, event-time
accuracy, physical qualification, or a solution to accumulated interval growth.

Only orbit_j2_enclosure.py changes among the 414 accepted tracked files; the
other 413 remain byte-identical. This contract, one test file and one fixture
are the only additions. Index remains empty; independent review precedes any
commit or longer numerical campaign.

