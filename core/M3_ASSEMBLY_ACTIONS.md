# First bounded M3 assembly-aware actions

The real accepted M1 `assess_design` and `calculate_mass_properties` are consumed
by `compile_assembly_hardware`. Checked declared mass coverage and installation
envelopes are required. Catalog cuboids, authored placements and derived mass,
COM and full tensor remain distinct. This does not implement full 3-axis ADCS.

Camera boresight and panel normal are explicit local unit axes bound to component
ID/local frame. Body directions are R_BC*u_C from the actual MountPose, then
R_IB*u_B from the time-stamped active body-y attitude. The demo mounts camera
local +z to body +x and panel local +z to body -x. Ry(theta) is the conventional
active matrix [[cos,0,sin],[0,1,0],[-sin,0,cos]]. The target gate and solar generation
consume those derived inertial directions; caller profile incidence is replaced
by the derived value on each declared numerical cell.

The supported rest-to-rest axis is body +y. Full I_COM is inspected: the norm
of (Ixy,Izy) must be <= the declared very small relative numerical allowance
multiplied by the maximum tensor component. Unsupported nonprincipal tensors
or directions outside the y-rotation plane fail explicitly; Iyy is never used
to disguise ignored cross-axis dynamics. The tolerance addresses arithmetic
rounding and is not a physical small-coupling approximation. The example has
zero cross terms by construction.

The existing `SlewProfile` owns bang/coast/bang duration with alpha=T/I,
rate cap=min(omega_max,H_max/I), and explicit rotor inertia, efficiency,
electronics and settling assumptions. Derived motion is rounded conservatively
to the next integer rest boundary, then declared settling is paid. Internal
phase/certificate/profile cuts retain exact Fraction representations of the
profile's binary64 times. Zero-angle commands still pay declared settling.
Angles smaller than 2^-45 rad collapse to zero only as the stated binary64
angular comparison convention, not a flight pointing requirement.

Mechanical energy is derived (same accepted 05E reduction):
K = (I*omega^2)/2 + (I*omega)^2/(2*J_rotor).
For each exact physical cell, dK/dt is paid by electronics + max(dK/dt,0)/eta.
Routed internal heat is electrical demand - dK/dt. Deceleration releases heat;
there is no regeneration. The independent heat test telescopes dK over the
rest-to-rest trajectory and separately checks battery conversion losses.

The editable compact/outboard documents use two identical 1 kg battery lumps
at x=+-0.25 / +-0.70 m. Other components/mounts/coverage/envelopes stay equal.
M1 therefore changes Iyy by 2*(0.70^2-0.25^2) kg m^2, which changes paid duration
and acquisition-window admission. No hardcoded slew durations are supplied.
The declared 4 kg core includes actuator/support/internal harness mass as an
ASSUMED aggregate, disjoint from camera/panel/two batteries; rotor inertia is
an assumed actuator property, not an additional mass component. No duplicate
harness mass or mass closure is claimed. Calculated M1-C electrical/thermal
interfaces stay static owners; new routes are explicit subsystem assumptions,
not a hidden routing/cable-loss engine. Dynamic interface coupling remains M4.

Reference gates cover independent local/body/inertial axes, parallel-axis
inertia, analytic triangular time, torque/rate/momentum and zero-angle settling,
nonprincipal refusal, paid physical loads, energy/heat/custody and fresh restart.
The demonstration proves a bounded causal construction-to-mission path only.
B41 adds bounded continuous target/FOV/end-ray consumption for spherical
equatorial geometry and held body-y attitude. Full M3 and broader Family B/
external physical/event-time qualification remain open.
