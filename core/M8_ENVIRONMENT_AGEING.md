# B61 connected environment ageing candidate

This is an uncalibrated reduced engineering model. All rate/asymptote values
are ASSUMED; the 1e-6/s preset is SYNTHETIC_ACCELERATED_ASSUMED, not five or
fifteen years of flight. The slower UI preset is also ASSUMED, not sourced.

For a selected physical cut [a,b), dt=b-a uses exact Fraction clocks. At the
admitted midpoint incidence and the same held/slew-midpoint quaternion as
EPS forcing, Xpv+=float(dt)*sunlit*max(0,cos(theta_deg*pi/180)). Xthermal adds
float(dt)*sunlit. These are effective illumination seconds, not UV dose,
particle fluence, AO or surface ray tracing. Thermal properties may declare
per-node/link exposure factors. Calendar increments exact dt independently.

For x=kc*calendar_seconds+kx*exposure_seconds, each property follows
v=v0+(v_asymptote-v0)*x/(1+x). PV asymptote is original retention times a
strict positive floor fraction; epsilon asymptotes lie in [0,1], G>0.
Coefficients have 1/s units; factors are dimensionless. Nonnegative rates
and finite domains (calendar/exposure <=1e12 s, rates <=1/s) make the rational
law bounded with no clamping, exponential underflow or inferred flight age.
Initial calendar/exposure values are explicitly ASSUMED state, not computed
history. PV law REPLACES the old uniform solar decrement, once. Battery
capacity/calendar/cycling and resistance owners remain separate and unchanged.

Start-of-cut retained/effective properties drive this cut's generation and
thermal solve. Proposed history commits once with the selected private cut;
end properties affect the next cut. All rejected forecast/full/TX/idle trials
retain paid work but never become actual history. Full/two-half quiet compares
exposure seconds, dimensionless retention/emissivity and G W/K with explicit
unit-aware scales; selected halves own their complete physical history.

The immutable baseline cfg/network/assembly/harness remains authority. A pure
explicit validated effective record changes only node epsilon/link G through
the accepted pure thermal API. C, A, mass, IDs, role support and temperature
thresholds are fixed. Wire/internal/Ohmic/converter heat stays counted once.
External solar/albedo/IR node heat is still prescribed; alpha and optical
heat closure are NOT modeled here. Changing epsilon/G is not material physics.

Exact graph domain: policy <=16 nodes, <=32 links; exact known records, ordered
unique IDs <=128 ASCII characters; finite scalars; bounded 128-bit rational
clocks. No generic graph cache admission. Dynamic state/effective properties
are NOT cached as immutable FAST truth. Work reserves before each proposal;
all failed/rejected attempts stay paid. Restore derives only current effective
values with separately reported bounded validation; no solar prefix replay.

New roots use B61_EXPLICIT_ENVIRONMENT_AGEING_INPUT_V7 and native
B61_EXPOSURE_THERMAL_CHECKPOINT_V8. Older roots retain original wires and bytes;
no V7/B60-native or cross-source/runtime migration. Global live schema5/B2
are untouched. Portable new-law contracts explicitly bind policy and native
format and exact source membership; fresh machine starts at initial root.

NASA SmallSat Thermal Control sec7.1 equation1 and sec7.2.1 discuss emissivity,
absorption/conduction and BOL/EOL optical change:
https://www.nasa.gov/smallsat-institute/sst-soa/thermal-control/
NASA NTRS19930001403 describes multiple LDEF PV damage mechanisms:
https://ntrs.nasa.gov/citations/19930001403
Neither source supplies this empirical equation, its rates, asymptotes, G law
or a spacecraft calibration. No example spacecraft coefficients are adopted.

PL-R1 keeps direct retained Popen cleanup available after monitor failure;
unproved descendants remain UNKNOWN. Fake tests are not actual Linux acceptance.
No Linux runtime is installed for this task. Combined qualification UNRESOLVED;
B7 UNKNOWN; historical preservation FAIL_UNEXPLAINED_NO_EXCEPTION and
UI_INCOMPLETE persist unless separately evidenced. No full15-year result.

The last paid estimate retains its exact observation state and receipt clock;
a newer resource packet does not silently update that old estimate. Reports
label those two lineages separately. effective_networks counts minted consumer
bindings; control_units are declared bounded budget credits, not measured
Python/scalar-operation counts. See the source-bound external work contract.

Final strict admission also turns oversized exact integers into typed domain
refusals before float conversion; accepted bounded inputs/equations are unchanged.
The new B61 producer is selected for the declared FiniteCampaignPolicy path,
including ordinary Workbench and portable roots. Legacy runner contracts are
not silently migrated. The B60 producer and exact membership stay unchanged.
