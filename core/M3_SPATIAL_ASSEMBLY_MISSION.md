# B42 opt-in spatial assembly mission, model version 1

This additive family consumes the accepted M1 uniform-cuboid builder and B38
original-anchor continuous sources. It does not alter the principal-body-Y
wheel API, assembly mass calculation, EPS, thermal, contact owners or schema 5.
All example hardware, Sun, torque, forcing and optical/RF values are ASSUMED
synthetic inputs, not KazEOSat calibration. This is a prescribed nominal action
model with conditional geometric certificates, not flight-qualified dynamics.

## Inputs, frames and numerical domain

`compile_assembly_hardware_3d` calls real `assess_design` and
`calculate_mass_properties`, retains mass, body COM and every entry of the
COM-body tensor, and binds the complete assembly document digest and actual
component/local-frame/mount capability axes. Definitions, instances, choices,
selections and installation region arrays each have at most 32 entries in this
opt-in family. Both camera and panel need explicit actual mounts. No caller
scalar inertia, JSON mass result or implicit default camera is authority.

The M1 binary tensor is retained exactly as rational coefficients. Numerical
symmetry admission permits max |Iij-Iji| <= 2^-40 max |Iij|. Exact Sylvester
minors of its symmetric quadratic form must exceed 2^-40 scale^k for k=1,2,3.
The symmetric form is used ONLY for SPD admission: no authoritative tensor
averaging, zeroing or substitute is published or used in Euler torque. This
allows M1 multiplication roundoff without declaring a new mass owner. Singular,
indefinite, appreciably nonsymmetric and unsupported ill-conditioned cases fail.
Mass is positive <=2^20 kg; individual tensor magnitudes <=2^30 kg m^2.

Right-handed `BodyAttitude3D` uses scalar-first Hamilton homogeneous quaternion
q=(w,x,y,z), an ACTIVE body-to-MODEL_INERTIAL rotation. In `q1*q2`, q2 acts first.
The inverse matrix is the transpose. q and -q, including signed zeros, share
one representation. Divide by max absolute component and make first nonzero
positive; this avoids square-root normalization drift and is idempotent.
Finite builtin float components have max magnitude between 2^-200 and 2^200;
all-zero, nonfinite/overflow, foreign frame kind and future rest times fail.
Timestamp/rest_since are exact Fraction seconds, <=128-bit numerator/denominator.
Units: m, kg, kg m^2, s, rad, rad/s, rad/s^2, N m, N m s, J, W, Wh and K.

Verified primary convention reference: NAIF [Rotations and their
representation](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/rotation.html),
sections 'Quaternions', 'Representing rotations', and 'Rotation matrices and
coordinate transformations'; active Rodrigues formula and Hamilton matrix.
NAIF's coordinate-frame elementary rotations use the passive sign: this family
explicitly uses active vectors, not those passive angle matrices.

## Prescribed shortest-axis rest-to-rest model

`plan_target_slew_3d` rotates the mounted camera toward the complete nominal
original-orbit target direction, preserving prior roll via a shortest body-axis
rotation. Axis from cross(camera, R(q0)^T target); angle atan2(cross norm,dot).
At angle <2^-45 rad choose zero. At near antiparallel (<2^-45 cross norm), choose
the least-aligned coordinate basis (index breaks ties), cross with camera and
canonicalize axis sign, then use pi. This is an explicit nominal numerical
half-turn convention, not flight pointing accuracy or an optimizer.

For stored axis v, define s=v.v, u=v/sqrt(s), L=Iv/sqrt(s),
G=(v cross Iv)/s, Ieff=(v.Iv)/s. Rational 80-bit outward sqrt bounds provide
upper |u_i|, |L_i|. Construction reserves HALF of each torque limit for inertial
acceleration and HALF for gyroscopic torque:

alpha_cap=min_i tau_i/(2 |L_i|upper),
w_cap=min_i(rate_i/|u_i|upper, H_i/|L_i|upper,
              sqrt_lower(tau_i/(2 |G_i|))).

Omit exactly zero denominators. Choose Ta >= max(sqrt_upper(theta/alpha_cap),
theta/w_cap), rounding UP on a 2^-40 s grid. Set alpha=theta/Ta^2 and
peak=theta/Ta. Acceleration/braking each last Ta; no coast is needed. Whole-phase
bounds are |tau_i| <= |L_i|upper alpha + |G_i| peak^2,
|omega_i| <= |u_i|upper peak and |H_i| <= |L_i|upper peak. Check those exact
rational inequalities before accepting; motion+round-up rest+settling <=120 s.
There is no iterative search. Root inputs <=2048 rational bits, root precision80.

Euler relationship: omega=u theta_dot, alpha_body=u theta_ddot,
H=I omega, tau_net=I alpha_body + omega cross H, K=Ieff theta_dot^2/2.
The gyro term is stored in each actual physical midpoint diagnostic; it is not
replaced by three independent torque/inertia ratios. Dot(omega, omega cross H)=0
and tau.omega=Ieff theta_dot theta_ddot=dK/dt on each smooth phase. At exact
switches the right-hand phase is selected; one-sided torque discontinuities
are explicit. Initial/final rate and K are zero. Quaternion interpolation is
q0 * (cos(theta/2),u sin(theta/2)). Libm interpolation/direction diagnostics are
nominal binary calculations. The declared held endpoint below is exact and
separate from physical attitude error, which is not modeled.

Verified primary mechanics reference: NASA NTRS
[Attitude Determination and Control Systems, Starin and Eterno](https://ntrs.nasa.gov/api/citations/20110007876/downloads/20110007876.pdf),
second PDF page, equations1-4, Euler equations Hdot=T-omega cross H, H=I omega+h. This family assumes
constant I and no internal-wheel h, giving the stated net torque relation.

`NetTorqueActuatorPolicy` declares finite positive per-axis torque, rate and BODY
momentum envelopes, electronics draw, drive efficiency and settling. This is an
IDEAL NET-BODY-TORQUE PORT. Its body H bound is not wheel storage. The actuator's
external/equivalent angular momentum closure, rotor dynamics, disturbances,
dumps, sensors, filter and free-flight control plant are outside this contract.
The accepted old principal-Y wheel family keeps its separate rotor assumptions.

## Paid execution and actual consumers

`start_environment_mission`/`advance_environment_mission` in the NEW
`environment_mission_3d` own action-boundary private transactions. Supported
NORMAL activity only; SAFE/BACKUP/emergency/pending critical-energy markers fail
BEFORE paid work; there is no arbitrary FDIR reset. Stored old context aliases
and foreign input/frame/state/cursor/action IDs fail. No partial product or
receipt is published after late failure. Work already returned remains spent;
exceptions with no returned physical/contact count have separately retained
UNKNOWN-event counters, not guessed or refunded counts.

Partition is the exact union of B38/forcing cuts, acceleration/braking/rest cuts
and bounded physical subdivisions. Fractional phases are paid. Outer integer
ceil motion+settling includes paid extra rest. Every midpoint uses actual
quaternion-mounted panel and camera, original F2 orbit and accepted Sun s-r.
Panel incidence changes real generation; EPS served/routing/conversion loss,
thermal, battery ageing, solar loss and custody stay with accepted owners.
For each cut, electrical draw is electronics+max(deltaK/dt,0)/eta, signed heat
adjustment -deltaK/dt goes to the fully routed bus. No regeneration; braking
release dissipates; no second motor-loss term. Cuts retain exact rational K,
nominal omega/alpha/H/torque/gyro and pose. Thermal limits at finite physical
endpoints do not prove continuous thermal safety.

`exact_held_camera` uses all admitted quaternion/body-axis binary numbers as
EXACT rationals. Its homogeneous Hamilton matrix entries are quadratic/norm^2;
no libm direction is a certificate. The transform uses the accepted bounded
geometry arithmetic with cumulative charges. It then calls B41
`evaluate_continuous_geometry` through its DECLARED-VECTOR branch, with genuine
process-local B38 producer authority/full ancestry/whole tubes and actual CLOSED
start/end rays. Exact norm is preserved; camera FOV concerns this ideal held pose,
not sensor/hardware uncertainty. Nominal sampled observations remain pointing
and optical inputs; never substitute for continuous CAPTURE/CONTACT admission.
Earth remains the accepted spherical/equatorial model with explicit uniform
rotation; general ellipsoid/latitude/height is deferred.

CAPTURE first checks the common acquisition window; then whole-interval
visibility/FOV and existing legacy MS grid/storage. CONTACT checks whole-interval
station geometry plus SEPARATE declared availability/RF/rate before delegating to
accepted contact execution. Existing constant integral-contact forcing limits
remain explicit; unsupported fractional contact cuts refuse. Actual product,
partial transfer, receipt, deadline and final credit are genuine legacy outputs.

## Bounded work and strict persistence

New runtime spatial reservations are conservative CONTROL/WORKSPACE units,
not claims about CPU seconds or arithmetic-owner operation ledgers. Each bounded
<=32-entry M1 compilation reserves65536 units, with a second65536 for the
planner's stale-hardware recomputation; bounded fixed-axis construction reserves
2048; each orientation/pose forcing reserves128. Input validation is static
admission, distinct from paid execution. Default cumulative cap2^20; reservation
failure precedes the corresponding paid call. Exact camera transform separately
charges actual geometry operations and controls before operations. Source,
geometry, physical, nominal queries and reconstruction quotas remain cumulative.
No unlimited search, loss of original-anchor uncertainty or hidden interval
replacement. Source/world <=120s, initial+refinement source steps<=256,
program<=16, action cuts<=512, physical reservation<=4096 by default.

Strict INPUT-ONLY format `B42_SPATIAL_ENVIRONMENT_MISSION_INPUT_V3` whitelists
new actuator/limits/action/capabilities and existing immutable input families;
separate accepted M1/environment documents retain their own identities. No
callbacks/result construction or registry/schema5 modification. Tree/depth/node
and16MiB document bounds apply. Pose/method/actuator/mount/world/policies/quotas
are in the input digest.

`B42_SPATIAL_ACTION_BOUNDARY_CONTINUATION_V3` requires external packet SHA256
and input digest. Full pose, checkpoint, complete outcomes/source/torques/energy/
rays/custody/receipts are comparison DATA. Fresh restore really calls B38 from
the ORIGINAL anchor, privately replays the prefix, compares FULL predeclared
scientific projection exactly in the same runtime, then charges exact extra
work delta. It never imports a saved source result as proof or publishes the
acquisition twice. Supplied prior quotas must cover measured prefix costs;
reconstruction cannot reset work. Cross-platform exact equality is not claimed.

## Runnable evidence and validation

`python -B -m examples.m3_spatial_constructor_mission_demo --variant compact
--output <external/science.json> --write-input <external/input.json>` runs the
real path; --stop-after2/--checkpoint-output export a boundary; --resume with
--packet-sha256/--input-digest continues in a fresh process. Outboard differs
ONLY in declared battery mount origins/envelopes; all world/product/controller/
capabilities/actuator/initial pose are common. Example Earth rotation1e-5 rad/s
is ASSUMED and nonzero. Electrical-negative sets max discharge output1W.

Independent hand-reference tests derive the full cuboid tensor and parallel
axis shifts, principal-axis K/torque and nonprincipal cross products. Exact
rational identities use equality. Nominal unit-vector/quaternion comparisons
use3e-14 absolute, approximately135 binary epsilons for the bounded fixed
normalization/matrix/composition chain; mechanical tests use explicit3e-13 J
absolute for sums of <=512 bounded binary cuts. These are numerical limits,
not tolerances transferred to exact delivered-bit accounting or flight accuracy.

Final case findings, exact commands/source bindings, failure history, restart
PID/equality/work delta and source-bound selected pytest counts are provided in
the external B42 review package. Prior B41 author582 and reviewer11groups/
4entries/0pytest are reused separately; no repeated-pass summation. Combined
qualification is UNRESOLVED, historical B7 cause UNKNOWN, H5/day/event/physical
qualification, general Earth, real actuator/control plant and M4 dynamic
assembly electrical/thermal topology remain open.
