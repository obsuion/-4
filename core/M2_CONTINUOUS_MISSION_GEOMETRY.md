# B41 continuous mission geometry and B40 corrections

Uncommitted opt-in review candidate on accepted B39. This is a bounded model
contract, not flight qualification, calibrated imagery or completion of M2/M3.

## Supported physical/data model

`mission_continuous_geometry.evaluate_continuous_geometry` consumes process-local
producer-bound evidence from the genuine B38 evaluation in
`start_environment_mission`. Input/result JSON is never propagation authority.
The accepted B39 `_source` validation checks original request, complete frame,
ancestry, trials, CLOSED SI tubes and exact full partition. A full producer
signature detects later evidence mutation. Clipping time leaves every cell's
position box unchanged. Shared endpoints belong to both CLOSED supports; no
positive-time gaps or overlaps are permitted. Zero-duration queries retain one
closed support and explicitly claim no positive-duration coverage.

Supported Earth is spherical (f=0), ground points equatorial and on the surface
(latitude=height=0), with the actual full FrameDefinition uniform +z rotation:

    theta(t) = theta0 + omega*t + east_longitude
    n(t) = (cos(theta), sin(theta), 0); g(t) = a*n(t)
    d(t) = g(t) - r(t).

Time is exact simulation-relative Fraction seconds under the bound TT epoch;
positions/ranges are metres, angle inputs radians, optical legacy pointing
still degrees. Nonzero omega is implemented. |theta|<=32 radians, finite source
span<=120 s, source/refinement steps<=256. Ellipsoid/non-equatorial/height
extensions are explicitly unsupported. This restriction is not hidden geodesy.

## Derivations and sound bounds

These are elementary derivations for the declared model, not adopted example
spacecraft coefficients or a new optical law. Existing `orbit_geometry` defines
the simultaneous dependent viewing direction/range/off-nadir, and
`orbit_visibility` defines surface-outward occultation and minimum elevation.

`_trig_bounds` uses exact rational Maclaurin sin through degree127 and cos
through degree126. For midpoint m, Lagrange remainders are bounded respectively
by |m|^129/129! and |m|^128/128! because every derivative has magnitude<=1.
Since sin/cos are globally 1-Lipschitz, add the exact argument-interval radius.
Dyadic floor/ceil at80 bits round outward. No libm point is used as a bound.
Square roots use integer isqrt on scaled rationals with exact outward ceil.

For a surface point of a convex sphere, departure n dot r - a >0 and
|r|>a prove exterior LOS. Negative departure proves penetration into the
sphere immediately after departure. Elevation >=epsilon is admitted only with
positive departure and

    departure_lower^2 > sin(epsilon)_upper^2 * |d|_upper^2.

Equal/tangent or inconclusive bounds remain UNRESOLVED. Off-nadir cosine is
(-r dot d)/(|r|*|d|), bounded conservatively; ranges use bounded |d|. Interval
operations cover dependent r,d,n; treating repeated symbols independently
can widen a result, never justify false visibility. Departure eliminates the
surface n dot g dependence analytically.

CAPTURE uses actual M1-compiled body camera axis and current held BodyAttitude.
The proof bounds exact analytic Ry(angle_y) with the same rational trig owner;
Ry preserves the declared body-axis norm exactly. Old owner binary64 direction
is retained as a nominal diagnostic, not a certified sine/cosine value.
FOV is the existing declared angular separation test expressed without acos:
positive c dot d, and

    (c dot d)_lower^2 > cos(half_FOV)_upper^2 * |c|^2 * |d|_upper^2.

End rays are r(t_end)+lambda*c in the bound MODEL_INERTIAL frame. At an exact
genuine source boundary, the complete accumulated zonotope is projected as
10^scale*(center_i +- sum(abs(generator_ji))) with exact rationals. It is not
loaded as a checkpoint, propagated anew, or narrowed by clipping. Otherwise
the whole source tube encloses position at the exact terminal time. Ray/sphere
quadratic discriminant and both positive root parameters are bounded; start
and terminal times/support/boundary IDs are explicit. There is no reuse of a
start-only local azimuth as the terminal ray. Supplied product footprint and
sample spacing remain nominal capability assumptions, not surface resolution.

## Consumption, failure and resource ownership

Explicit modes: NOMINAL_SAMPLED_J2_POINT_GRID_V1 and
CONTINUOUS_B38_SPHERE_EQUATOR_HELD_CAMERA_V1. Strict B41 input/continuation
format2 rejects the old B40 format1 rather than silently upgrading its promise.
Live checkpoint schema5 and accepted registries are unchanged.

Whole CAPTURE requires every cell VISIBLE with FOV and admitted forward rays.
Whole CONTACT requires every cell VISIBLE; availability/RF/rate remain separate
assumptions. BLOCKED/UNRESOLVED refusals occur before physical/acquisition/
receipt publication. Genuine imaging/MS/storage/contact/protection owners
remain in charge. Fractional forcing discontinuities still refuse contact.
POINT remains the accepted limited principal-body-y paid slew; it is not
three-axis dynamics. General attitude motion during capture is unsupported.

RuntimeWork keeps separate cumulative geometry_queries, geometry_operations
and geometry_control_units. Every rational arithmetic operation is charged
before execution; magnitude/bit workspace and output-bit checks are explicit.
Controls pay guarded scalar checks, interval comparisons, bounded loops,
source-record checks and retained publication work (64-byte units). Defined
work units are accounting contracts, not CPU-cycle estimates. Limits cover
512 cells/query, 64 queries, 2^22 arithmetic/control units, 32768 workspace bits,
2048 published rational bits and8 MiB/query. Computational failure publishes
no partial certificate; costs already incurred persist, including refusals.

Protection repairs: this bounded coordinator admits NORMAL activity only.
SAFE/BACKUP/emergency and pending essential-energy markers require a separate
accepted recovery owner and are rejected before paid work in input/start/
advance/save/restore. No FDIR recovery is implemented by assignment. Unsafe
contact is an atomic refusal. Ordinary contact preserves owner terminal mode,
including STANDBY idle. Returned work is charged from
outcome.evaluated_eps_substeps before refusal; exceptions without a returned
count retain reservation and record contact_work_unknown_events, not a guess.

Continuation reacquires actual B38 evidence from the original anchor and
privately replays the completed prefix. Certificates/end-rays are comparison
data. Full scientific projection includes all causal outcomes, physical,
attitude/custody/credit fields and source results; only cumulative runtime
recomputation costs are separate. Saved lower bounds prevent quota reset;
all additional geometry/orbit/physical replay work is paid.

## Qualification boundary

The bounded Family-B point visibility/FOV/terminal-ray implementation is
connected to actual acquisition and contact. External orbit/Sun accuracy,
full ellipsoidal/non-equatorial geometry, continuous thermal/protection safety,
calibrated pixel footprint/resolution, event-time accuracy, general attitude,
RF performance and day/flight qualification remain open. Uncertainty width is
not event-time accuracy. Combined qualification UNRESOLVED; B7 cause UNKNOWN.