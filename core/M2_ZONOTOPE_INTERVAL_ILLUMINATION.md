# M2-B34 opt-in continuous zonotope illumination

Bounded candidate, not combined/physical qualification. Six additions only; all
430 accepted source files and Sun dispatch remain unchanged.

The new owner `orbit_sun_zonotope_intervals` provides frozen
ZonotopeIntervalIlluminationPolicy, Request and Result, and
`evaluate_zonotope_interval_illumination`. API identity is
`m2-zonotope-interval-illumination-v1`, version 1; geometry resource policy 1.
It accepts only the exact B33 J2ZonotopeSegmentRequest and B1 SunPositionTable.
There is no independent start: the forward interval starts at the original
Cartesian trajectory anchor. There is no checkpoint, nominal fallback, incoming
box, supplied diagnostic or late-prefix reconstruction authority.

## Admission and authority

Complete Cartesian position/velocity frames, reference ellipsoid, uniform
rotation parameters, original TT epoch, J2 gravity/provenance and policies are
validated through accepted data-only owners. A complete trajectory is never
canonical-copied or constructed through its F1-evaluating constructor. Instead,
original state/model are decomposed and checked, then the same frozen trajectory
record is filled with `object.__new__`, as in B33. Canonical normalization checks
safe original inputs only. Sun source metadata and the entire CLOSED table domain
are checked. These scans are not orbital force calls or transport work.

Input-admission scans have a 131072-node, 64-depth bound, a 4096-item container
bound and 16384-character text bound. They bound validation, not physical error.
The accepted table has 2..1024 nodes; source count is at most 4096. Admission
refuses horizon/step excess before allocating a range. Input structure failures
raise; computational query refusals return an unresolved, atomic result.

## Exact partition and unchanged whole tubes

Time grids use Fraction of the ORIGINAL accepted binary64 values, not decimal
spelling or rounded repeated addition. Divmod gives full steps and one exact
remainder. Geometry boundaries are the sorted UNION of the source boundaries
and interior Sun knots. At most 4096+1022=5118 geometry cells exist; max_cells is
in [1,5118]. Count refusal occurs before propagation, with propagation_calls=0.
For admitted geometry, B33 is entered exactly once with its one cumulative v3
ledger. No endpoint, B2/B3/B6 public evaluator or nominal solver is called.

A complete upstream result is revalidated against the exact original physical
request and fixed segment/method/kernel/publication/resource identities. Its
closed cells must match the exact admitted grid, indices and complete partition,
with finite ordered plain Decimal SI bounds. Every geometry cell references one
real B33 source cell and one adjacent Sun pair. Sun subdivisions reuse the WHOLE
unchanged source position tube; no endpoint/sampled narrowing occurs. Closed
supports share endpoints intentionally; interiors partition without gaps.
`IntervalIlluminationCell.j2_cell_index` indexes `upstream_evidence.cells`, whose
owner is B33, not legacy B2. Cells are derived evidence, never decode authority.

## Accepted geometry and assumptions

No new mathematical predicate is introduced. Frozen B3 `_shape_weights`,
`_sun_envelope` and `_geometry_cell` are reused unchanged. SI Decimal endpoints
are converted exactly to Fraction without ambient Decimal arithmetic. Before
conversion a conservative decimal-representation size guard prevents enormous
powers of ten; all actual B33 plain endpoints fall inside this guard. Rational
numerator/denominator bit lengths remain at most 16384.

The existing Sun envelope contains both the exact piecewise-affine component
range and the correctly rounded binary64 B1 provider range: monotonic rounding
places every RN(x) between rounded endpoint values. Exact and rounded component
bounds are unioned, including cancellation, zero and subnormal values. There is
no physical ephemeris/interpolation error bound.

Derived notation, inherited unchanged from B3: Q=diag(1/a^2,1/a^2,1/b^2),
d=s-r, A=d.Q.d, B=r.Q.d, C=r.Q.r-1, D=A*C-B^2. The ellipsoid polynomial on the
half-ray is A*lambda^2+2B*lambda+C, lambda>=0. These are interval expressions with
dependent d=s-r and complete tube bounds. Strict exteriority/nonzero guards and
closed-contact semantics remain unchanged. ILLUMINATED/OCCULTED/UNRESOLVED apply
only to the declared J2/affine-Sun model. A complete ambiguous cell is valid
conditional evidence, not a computational failure or event-time certificate.

## Separate resource meaning and atomic publication

The single geometry context counts actual scalar exact-rational add/sub/mul/div
operations performed by the accepted helpers. Setup has at most 512 operations;
each cell at most 512. The aggregate policy ceiling is at most
(5118+1)*512=2620928; a smaller explicit positive ceiling is allowed. Each charge
is checked before arithmetic, with the inherited bit ceiling checked as well.
Conversions, type/schema scans, bounded grid/union sorting, source validation and
finite list/publication allocation are NOT these scalar arithmetic operations.
Validation/conversion endpoints are bounded by 12*4096 for source checks and
6*5118 for cell position conversion. Input and allocation bounds are independent
of B33's numerical ledger. No geometry operation is added to v3 scalar units.

B33's complete result and its leaf/reserved/total counters are retained exactly,
without resets or top-ups. This geometry counter is not CPU time, bytes, physical
accuracy or a guarantee of successful completion. Result fields expose request,
fixed identities, status/reason, optional complete cells, optional separate
upstream evidence, planned/evaluated geometry counts, actual arithmetic work,
propagation_calls and all_cells_classified. Evaluated cells count completed
geometry calls, including those retained only privately before a late failure.

Cells are published only after every requested cell and final checks succeed.
On propagation, arithmetic, conversion, validation or late publication failure:
status=unresolved; cells=None; all_cells_classified=False. No partial durations,
windows or combined coverage certificate are published. Complete upstream orbital
enclosure may survive as separately labeled evidence; it is no restart input.
Combined qualification is always UNRESOLVED, with the five inherited unquantified
physical ephemeris/interpolation/time/frame/initial-state/gravity reasons.

## Strict document

Format M2_ZONOTOPE_INTERVAL_ILLUMINATION_REQUEST, version 1, canonical codec 1;
digest domain m2-zonotope-interval-illumination-request-v1. Only decomposed
original physical inputs, B33 policy/fixed identities and decomposed Sun
samples/provenance are serialized. No full trajectory/coast, result/cell/ledger,
private Decimal owner, certificate, callable, cache or checkpoint is accepted.
The entire tagged tree's input-only record/enum allowlist and exact field schemas
are checked before decode_content. Document text is additionally capped at 4 Mi characters before parsing. All nested maps, fixed versions/policy
identities and table schemas are checked before any constructors. Canonical
representation/normalization, embedded/expected digest and exclusive-create saves
are preserved. Loading/digest/construction perform zero setup F1/F2/propagation.

## Verification and limits

New tests use exact independent half-ray/cross-distance references, rigorous
whole-arc circular-orbit sine/cosine series, exact union grids and remainders,
whole-tube copying, hostile Decimal contexts, Sun rounding/cancellation/subnormal
cases, strict identities and atomic failure seams. Test-only supplied cells are
synthetic geometry fixtures, not model authority. Regression includes the two new
files plus the thirteen requested accepted files. Author execution/results and
preserved preparation failures are reported in the external review evidence.

Six small offline inputs: illuminated, occulted, ambiguous, split/remainder,
pre-propagation geometry refusal and upstream resource refusal. Full typed
scientific outputs retain exact Decimal tuples and hex Fraction numerator/
denominator values. Primary and fresh replay each enter the illumination owner
six times, at most 30 seconds model time per example. Four archived controls are
reproduced once separately, not counted as pytest tests or replayed again.
No H5, obstruction, hour/day study, iterative search, event-time accuracy,
physical certification, hardware performance or full-M2 completion is claimed.
