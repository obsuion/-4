# B43 general Earth continuous geometry and spatial mission

This opt-in candidate completes a bounded general ground-geometry consumer,
not physical, day, event-time, wider M2/M3 or flight qualification. Combined
qualification remains UNRESOLVED; historical B7 cause remains UNKNOWN. B42's
historical late-launch gate remains FAIL/UNKNOWN, independently of accepted code.

## Input and frame contract

`mission_general_geometry.GeneralGeometryPolicy` and
`CONTINUOUS_B38_GEODETIC_ELLIPSOID_HELD_3D_V1` are explicit new identities.
The actual `environment_mission_3d` coordinator admits this mode separately.
Its old B42 default, sphere/equator method, V3 inputs and packets stay unchanged.
New input/continuation domains are V4; there is no silent V3 migration.

Accepted complete `FrameDefinition`, `ReferenceEllipsoid`,
`GroundPointDefinition`, provenance, IDs and units remain authoritative.
The bounded domain is equatorial radius 6,000,000–7,000,000 m, flattening
0–0.01, geodetic latitude including both poles, east longitude in the accepted
half-open convention, and normal ellipsoidal height −100,000–1,000,000 m.
Source position coordinates have absolute magnitude at most 2^30 m.
This is an Earth-scale oblate/spherical model, not arbitrary planetary geometry.
Opaque reference ellipsoid, no terrain/geoid/refraction/light-time or pose errors.

Exact simulation-relative TT elapsed seconds bind the original epoch/anchor.
Uniform active +z rotation maps Earth-fixed to MODEL_INERTIAL; combined longitude
is lambda+theta0+omega*t, with absolute phase <=32 rad throughout the domain.
Epoch does not silently determine Earth phase or UTC/EOP. Signed/zero rates are
admitted within that phase domain. At poles the supplied longitude declares a
meridian; azimuth is undefined, and the owner never divides by cos(latitude).
Binary input angles define exact real radians, including the finite binary
representations of the accepted pole endpoints. Nominal C1 retains its own
explicit azimuth diagnostics; it is steering/comparison data, never proof.

WGS84 shape is reused from `orbit_config.wgs84_reference_ellipsoid()` and S008
in `V5_SOURCE_REGISTER.md`: a=6378137 m and f=1/298.257223563, with the existing
verified/derived provenance. The nominal mean Earth rate factory is sourced;
holding it constant with a chosen phase in these synthetic cases is an assumption.
Synthetic Cartesian anchors, J2 coefficients, assembly/actuator, Sun table,
thermal forcing, power values, products, station availability/RF and bitrate
remain separately declared assumptions; they do not establish flight performance.

## Charged derivation

Let b=a(1−f), e²=f(2−f), N=a/sqrt(1−e² sin²(phi)). Earth-fixed normal and surface
point are n=(cos(phi)cos(lambda),cos(phi)sin(lambda),sin(phi)) and
g0=(N cos(phi)cos(lambda),N cos(phi)sin(lambda),N(1−e²)sin(phi)).
Ground g=g0+h n; rotation is incorporated in longitude. This is a geodetic
normal, not normalized geocentric g. The constant latitude/curvature preparation
is charged once per query, and every rotating cell is charged separately.

The unchanged B41 rational arithmetic/trig/root primitives bound sin/cos using
finite Taylor remainders and global Lipschitz radii, then exact outward dyadic
floor/ceil. Roots use integer square roots at 80 fractional bits. No libm point
becomes a bound. All declared binary coefficients become exact rationals.
Dependency widening may refuse a case; it cannot authorize a false clear case.

For D=diag(1/a²,1/a²,1/b²), v=r−g, the segment g+u v (0<=u<=1) has
F−1=A u²+2B u+C, A=v^T D v, B=g^T D v, C=g^T D g−1.
The dependent identity g0^T D n=N/a² gives
C=2hN/a²+h²[1/a²+(1/b²−1/a²)sin²(phi)]. At h=0, C is analytically exactly zero.
Independent interval products of g do not reinterpret a surface point as buried.

Sufficient whole-clear tests require a proven outside spacecraft, A_lo>0 and:
surface C=0 with B_lo>0; elevated C_lo>0 with B_lo>=0; or
C_lo−max(B²)/A_lo>0. If A_hi+B_hi<=0, the segment is monotonically inward and
its proven outside spacecraft endpoint is its minimum. All use strict margins.
Ground/spacecraft wholly inside are explicitly blocked. For surface B_hi<0,
the right derivative proves interior entry. A bounded fixed rational witness
u=min(1/2,floor80(−B_hi/A_hi)) is retained when positive; its polynomial upper
is negative. Underflow of this optional witness does not remove the derivative
proof. Elevated cases test 1/4,1/2,3/4 and a bounded fixed midpoint-vertex witness;
an upper polynomial value below zero proves penetration throughout that cell.
Exact interior tangency, uncertain endpoint/vertex and unresolved boundaries are
UNRESOLVED. Arithmetic/hull/bit failures raise computational errors, not occultation.

BLOCKED means at least one complete cell uniformly violates the required action
interval; it does not claim every time is blocked. VISIBLE requires every closed
cell clear and above the declared geodetic elevation threshold. Signed elevation
uses n dot (r−g)/|r−g| against bounded sin(minimum elevation), so negative thresholds
and sign guards are explicit. Camera direction uses g−r. Its positive dot and
norm-scaled squared cone test certifies the full held-FOV interval. Slant range is
metres; off-nadir cosine is explicitly geocentric nadir. Intersecting its interval
with [−1,1] is an analytic cosine-domain intersection, not uncertainty clipping.

## Source, rays and resource ownership

Only an acquired process-local genuine B38 binding is accepted. Complete source
signature, full ancestry and authority validation, original anchor, whole SI tubes
and exact CLOSED union partition are retained. Splitting time never narrows the
source position box; no per-cell orbit propagation, diagnostic-box checkpoint,
saved-certificate decoder or result-file proof authority exists.

Actual B42 mounted camera and canonical full quaternion use the unchanged charged
exact homogeneous transform. Terminal origin is the complete accumulated boundary
projection at a genuine boundary, otherwise the full original closed tube at the
exact requested time. With held c, ray r+l c has Ar=c^T D c, Br=r^T D c,
Cr=r^T D r−1 and discriminant Br²−ArCr. Outside/inward/strict positive discriminant
guards precede outward sqrt/division and ordered positive first/second roots.
Grazing, no intersection, away-facing, source-inside and uncertainty are explicit.
Height target LOS/FOV and reference-ellipsoid intersection are distinct objects:
a proved elevated target does not require a reference-body hit. Neither a ray
intersection nor supplied footprint/spacing claims terrain geolocation or calibrated GSD.

Per query: maximum 512 cells, cell width 1/64–5 s, 64 queries, 2^22 arithmetic
operations and controls, 32768 workspace bits, 2048 publication bits, 8 MiB retained
payload. Conservative pre-publication record admission bounds allocation. Witness
selection/publication is dyadic-bounded; it never enlarges an operation tolerance.
The coordinator's existing cumulative limits are separate and unchanged. Failed
attempt costs already paid stay in RuntimeWork; no partial certificate is published.
Geometry gates precede physical/custody publication. R1–R3, EPS, thermal, ageing,
full assembly tensor/pose/slew and contact protection/rollback remain their owners.

## Codec, continuation, verification and external evidence

V4 has a fixed input-only whitelist, complete bounded tree and canonical binding.
Full world/source/shape/latitude/height/elevation/pose/method/policy enter identities
and complete scientific output. Result classes are output data, never input authority.
Fresh continuation reconstructs original-anchor B38 and privately replays the
completed history. Full orientation/cells/rays/physical state/receipts must agree;
paid reconstruction delta and prior lower bounds remain separate. No reset or
double receipt. Legacy schema 5 and experiment registry are unchanged.

New tests cover independent 100-digit geodetic series, exact ellipse quadratic/root
references, surface identity, signed guards, full-tube refinement, real southern
and near-pole sources, negative height, exact mode/codec, finite quota refusal,
late primitive rollback, connected acquisition/contact and full replay equality.
The external B43 evidence contains source-bound targeted gates, actual old-V3
control, WGS84 positive/placement comparison, interior trap and fresh-process resume.
Failed initial attempts remain in that evidence; repeated passes are not summed.
Old unchanged B42 final 55-pass evidence and reviewer evidence are reused separately.

The external launch variant rejects completion observed after its execution deadline
even with exit 0, checks whole envelopes, and reaps only its private Job with one
finite shared cleanup allowance. Host suspension cannot guarantee timely interruption;
late data is diagnostic-only with no downstream acceptance, and cause stays UNKNOWN.
Task budgets distinguish declared reservations from observed envelopes and actual
B38 entries. This block admits no H5/day campaign or mathematical optimization.
