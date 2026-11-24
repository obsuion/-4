# M2-B16: opt-in original-anchor centered J2 enclosure

This is a bounded numerical endpoint owner for the real declared static-axis F1 field. It is an uncommitted candidate for implementation review. It does not establish useful H5 enclosure width, speed, event-time accuracy, physical qualification, or combined Sun qualification. B7's cause remains UNKNOWN.

The separately reviewed B15 design is bound to ZIP SHA-256 `51148c108287ffe597db5c6f8b2960eda470698f4e20192419d82bb3075e97d7`. Externally reported design review passed 31 static and 38 symbolic/rational assertion groups, with no orbital evaluations or pytest. Those are design checks, not validation of this implementation.

## Input and output contract

Import directly from `ops_sim.v5.orbit_j2_zonotope`; no existing export, dispatcher, policy, codec or checkpoint changes.

```
J2ZonotopePolicy(base_policy: J2EnclosurePolicy,
                 scale_exponents: tuple[int,int,int,int,int,int],
                 max_scalar_operations: int)
evaluate_j2_zonotope_enclosure(trajectory: J2CartesianTrajectory,
                             instant: GeometryInstant,
                             solver_config: J2RK4SolverConfig,
                             policy: J2ZonotopePolicy) -> J2ZonotopeResult
```

Policy/result are frozen with slots and strict admitted types. Fixed method is `m2-centered-zonotope-pb6-v1`, version 1, PB order 6, maximum 12 generators, six retained columns when compressing, rank intermediate bit ceiling 4096, scale exponents each [-32,32], primitive ceiling [1,2^24]. The old base policy retains its computational domain/precision/Picard/step limits. No adaptive parameter change or alternative solver is selected.

Order is `(r_x,r_y,r_z,v_x,v_y,v_z)` in the supplied MODEL_INERTIAL frame. Physical coordinates remain m and m/s, exact signed times are Fraction seconds relative to the existing TT epoch. Fixed diagonal D contains explicit powers-of-ten position/velocity scales; u=D^-1 x is dimensionless. Conditioning does not rotate axes or introduce Earth/Sun assumptions. The scaled upper-right Jacobian block is D_v/D_r, not generally identity.

On success, status is `enclosed` and output includes the unchanged F2 nominal state, outward SI endpoint intervals, upper binary64 distances to that nominal in m and m/s, and a frozen diagnostic center/generator state. Published Decimals are plain immutable Decimal values with no mutable ledger attached. The diagnostic set is not accepted by any restart API and is never checkpoint authority.

On numerical/domain/work rejection, status is `unresolved`, reason and work counters remain, while nominal state, endpoint intervals, distance bounds and diagnostic state remain None. Strict malformed inputs retain ordinary validation exceptions rather than receiving a fabricated successful result. All numerical success fields are published together after proof/publication work passes.

## Inclusion recurrence and derivation-to-code map

Represent the carried set as `Z=c+G[-1,1]^m`, m<=12. The invariant is that the real solution from the exact represented original input belongs to D Z at the current exact time. Each step encloses the flow of the entire Z, not only its center. Binary64 coordinates use exact Decimal.from_float; scaling shifts Decimal tuple exponents without ambient rounding. Initial G is empty.

1. `_project_box` outward-projects D Z, preserving all generator radii. `_transport_step` supplies the enclosing signed duration to the **unchanged** `_tube` containment/domain machinery. T encloses all initial points over the entire step. The legacy helper at `orbit_j2_enclosure.py:250–262` is **`_step_with_tube`**, not `_step`; the new owner reuses its coefficient/tube proof components separately. This corrects the B15 label without editing its accepted archive.
2. Center flow is enclosed with order-6 coefficients at D c and the order-7 remainder on T. Choose a nearest center c+ and retain its complete interval residual E_c. F2 is not used to reset c or G.
3. `_jacobian_box` encloses the analytic derivative of the real F1 field on T. With q=x²+y²+z², beta=3*mu*J2*Rg²/2, kappa=(1,1,3), Fi=5z²q^(-7/2)-kappa_i*q^(-5/2):

```
Kij = -mu*delta_ij*q^(-3/2) + 3*mu*xi*xj*q^(-5/2)
      + beta*(delta_ij*Fi + xi*(10*z*delta_jz*q^(-7/2)
              -35*z²*xj*q^(-9/2) + 5*kappa_i*xj*q^(-7/2)))
Jx = [[0,I],[K,0]]; Ju = D^-1*Jx*D
```

Positive q is checked before inverse powers. This is not differentiation of RK4 or rounded force code. The independent test oracle differentiates the declared potential using exact rational second-order jets.

4. `_flow_derivative_box` encloses the true time-ordered variational flow. Its Volterra series has ordered products integrated over simplex volume 1/j!. Interval powers of the whole-tube [J] enclose independently varying factors. With z>=|h| sup||[J]||_infinity, require a proved z<8, then outward-enclose every matrix entry by

```
[M] = I + sum_(j=1..6) [h]^j*[J]^j/j! + [-rho,rho]
rho = z^7 / (7!*(1-z/8))
```

The denominator is bounded positively downward. Negative h uses signed powers and the same absolute norm tail. No frozen-average exponential, matrix inverse or QR assumption is used.

5. The integral mean-value bridge gives flow(c+Gxi)-flow(c)=Mbar(xi)Gxi with Mbar in [M]. Choose point C and compute nearest Ghat=C G. Explicitly retain E_c, `([M]-C)G`, and `[CG]-Ghat`. Their rowwise absolute interval bounds become six new axis generators. Each residual encloses all rounding/truncation; no accumulated set is dropped.
6. `_reduce_generators` removes exact zero columns; above 12 columns, keeps the six highest exact rational squared norms, with deterministic birth-ID ties. For all discarded columns form outward d_i=sum|g_ij| and append diag(d). Every discarded coordinate lies in [-d_i,d_i], proving outer set inclusion, not invertible recentering. Apply the unchanged endpoint radius predicate to the final projection. The next step carries the entire reduced Z, never the exported box.

| Derivation / boundary | Implementation |
|---|---|
| Exact initialization/scaling/projection | `_initial_set`, `_shift`, `_project_box` |
| Positive-q real derivative and numerical scales | `_jacobian_box` |
| Time ordering, signed PB6 and outward tail | `_flow_derivative_box`, `_matrix_product` |
| Center/transport/rounding residuals | `_transport_step`, `_transport_generators` |
| Rank-bit admission and outer compression | `_fraction`, `_rprecheck`, `_reduce_generators` |
| Fixed original anchor and atomic publication | `J2ZonotopeResult._evaluate`, `_plain`, `_plain_set` |
| Complete per-query numerical ledger | `_Arithmetic`, `_Context`, `_D`, metadata reservations |

Births are deterministic bounded step/role/axis integers within the original input/query scope. Runtime object identity is not included in ranking/output. No local session or refinement adapter is implemented.

## F2 invocation and counter provenance

After static admission, call the unchanged F2 public evaluator exactly once, before any enclosure step. The normalized original state/model are bound into a frozen trajectory without running its force-admitting constructor; F2 owns its initial force admission. No F2 monkeypatch, duplicated RK4 or invented telemetry is used by production.

`planned_nominal_steps` and `planned_nominal_force_calls=1+4*n` are the plan from its exact fixed grid. Only after normal F2 return are `nominal_completed_steps=n` and `nominal_force_calls=1+4*n` reported with provenance `DERIVED_FROM_SUCCESSFUL_F2_FIXED_GRID`. These are source-derived completion counts, not observed force telemetry. On partial failure actual counts are None/UNKNOWN, planned counts remain, and no enclosure step runs. Defaults with provenance NOT_RUN mean no admitted plan/evaluation, not a measured zero-cost failed call. Later enclosure failure clears all success fields but retains those truthfully confirmed nominal counts.

F2 retains its own <=4096 step admission. Its internal float/metadata work is an unchanged black box with this separate accounting; Decimal leaf counts are enclosure/admission work, not alleged F2 instruction telemetry.

## Frozen charging table: changes from B15

`scalar_operations = charged_leaf_operations + reserved_control_operations`. Charge before protected work; reject a charge that exceeds remaining capacity, latch exhaustion and allow no subsequent protected operation. The counter never exceeds its ceiling. Missing context name/arity or implicit Decimal arithmetic rejects before native work.

The B15 illustrative interval weights are refined to **context/conversion/comparison/rational leaves plus separately identified conservative control reservations**. No composite is misreported as an executed leaf. Schema/resource-ledger bootstrap checks establish exact types/cap/precision before the ledger can exist; repeated policy/time/config numerical reconstruction is inside the charged admission block. Caller construction of an input policy is not a propagated proof query.

| Operation | Charged leaves / safe bound |
|---|---:|
| Binary context operation | 5: native operation+2 exact argument conversions+result finite check+endpoint wrapping |
| Unary context operation | 4: operation+argument conversion+finite check+wrapping |
| Exact point conversion | 3 |
| Query Decimal comparison | 1 per executed comparison |
| Exact copy_abs/copy_negate | 3 (copy plus wrapping) |
| Interval add / negate / subtract | 10 / 12 / 22 |
| Interval multiply | 46: eight binary context operations (40) plus six min/max comparisons |
| Interval divide | <=64, including denominator conversion/zero guards, reciprocal and multiply |
| Interval square | <=30 |
| Validated sqrt | <=190, including context neighbors, six exact Fraction conversions and two checked squares/comparisons |
| Decimal-to-Fraction conversion | 14, including pre-conversion bit admission and post-check |
| Rational add or multiply | 21, including pre/post bit checks |
| Rational comparison | 20, with cross-product bit admission before comparison |
| Exact tuple exponent shift | 7 |

Direct `ar.down`/`ar.up`/nearest methods go through the same charging proxy. Only add/subtract/multiply/divide/sqrt/next_minus/next_plus with their fixed arities are admitted. Guarded endpoints intercept legacy comparisons, absolute/sign copies and integer-ratio conversion. Implicit binary/reflected/unary Decimal arithmetic is rejected rather than silently using ambient context. Per-query directed/nearest contexts preserve the accepted exponent/trap domain.

Rank intermediates are admitted conservatively before conversion or cross-products and checked after operations, with 4096-bit ceiling. Generator birth arithmetic, scaled projection, exact signed grids, upper-float conversion/distance residuals and immutable publication are also precharged. The unit is abstract bounded work, not seconds or equal processor cost.

### Conservative control/conversion reservations

These bound legacy structural branches, integer/control work and allocations not intercepted as Decimal leaves. They are additional charged estimates, not observed counts; there is no data-dependent execution log.

| Block | Reserved units |
|---|---:|
| Static admission | 512 |
| Authority metadata structure | 512, plus dynamic schedules below |
| Initial set / diagnostic publication | 128 each |
| Each SI projection | 256 |
| New step control | 8192 |
| Whole-tube legacy control | 256+2048*16=33024 (all admitted Picard attempts, including bounded alternative) |
| Center coefficient legacy control | 16384 |
| Jacobian / PB6 | 1024 each |
| Each of five dense PB products | 512 |
| Transport / reduction | 2048 each |
| Each standalone initial/endpoint domain | 128 |
| Final distance/publication | 256 |

Metadata is not assumed small. Eleven parameter occurrences cover both frame graphs and gravity; each reserves 256. Each text reserves 64+40L (L Unicode scalars, including UTF8/strip/hash scans); source-ID lists of size n reserve 128n+32n² before iteration, then 32n*sum(L_id) before delegation to cover collision-dependent string comparisons. Type/length extraction and accumulated lengths are separately charged. These source-audited estimates bound the existing reconstruction chain without introducing an arbitrary new metadata hard limit. A large input exhausts the unchanged primitive ceiling before delegation; no budget increase occurs.

### Loop-derived bound

With m<=6, n=m+1, P=n(n+1)/2, S=m(m+1)/2, a conservative leaf bound for one nonzero-J2 legacy `_field` is

```
F(m)=46*(14P+2S+m+12n+3)+22*(14P+9n+S)
     +3*(21n+S+2m+5)+64*(m+1)+120+190+36n
F(0..6)=(2328,5314,9369,14493,20686,27948,36279)
C(order)=sum_(m=0..order-1) (F(m)+402*(m+1))
C(6)=88580; C(7)=127673
```

The 402*(m+1) term conservatively permits a divided coefficient/conversion for every six-by-(m+1) RHS slot, although the source only appends six new coefficients per order. Thus it bounds the six actual divisions without claiming those extra divisions execute. Bounds intentionally exceed attainable branches; failures execute a shorter prefix.

| Step phase | Safe leaf bound |
|---|---:|
| Whole tube, at most16 attempts including fallback/control branches | 50527 |
| Center6/remainder7, Horner and scaling | 219277 |
| Jacobian | 25000 |
| PB6 | 75000 |
| Transport | 64000 |
| Reduction | 10000 |
| Two projections | 2048 |
| Final domain / exact-time bits | 157+4 |
| Total | 446013 |

Step reservations add 66944, yielding 512957 < **C_STEP=2^19=524288**. Complete query work is conservatively bounded by dynamic metadata admission +8192 initial/final/grid overhead +N*C_STEP. Admission may reserve more than actual control execution. This is a loop-derived upper bound, not measured runtime or a promise of H5 capacity. The proposed C5 short diagnostic is NOT_RUN and its future reservation must independently fit the explicit ceiling.

## Fixed allocation schedule

Retained numeric state: one center6, <=72 generator scalars, <=12 births and one exact time; current SI box/tube each six intervals; three contexts and fixed counters. No production whole-history or support graph is retained. Tests alone may collect history to check every closed analytic tube.

Phase capacities: center coefficients6x7=42 intervals and remainder6x8=48; old coefficient/tube scratch has a conservative1024-interval allowance from fixed m<=6 loops. PB uses at most five6x6 interval matrices (180 intervals) plus32 scalar intervals. Transport has point C36, interval delta36 and M36, <=72 rounded inherited scalars plus36 axis residuals (trial<=108 scalars). Reduction handles <=18 columns without an unbounded sort; ranking holds <=18 scores plus16 rational work operands. Publication copies <=78 plain Decimal scalars. Conservative simultaneous numerical allowances are2048 interval records,384 standalone Decimal cells,128 birth/reference cells and64 Fraction cells, all independent of step count. Intermediates respect the 4096-bit checks and old exponent domain.

These are logical source-loop allocation bounds, not a measured RSS guarantee or a cap on pre-existing input metadata. Metadata traversal is dynamically work-admitted; existing input authority objects are separately held. No full retained error/event history is used to bypass these limits.

## Independent acceptance evidence and remaining gates

Focused tests use exact potential-Hessian rational jets, whole-axis Jacobian interval ranges, exact noncommuting time-ordered and affine-set examples, >12-column reduction with outer-inclusion proof, hostile ambient Decimal context, all 32 closed signed circle tubes/endpoints, and work/domain/Picard/tail/rank/publication failures. Circle authority is exactly mu8, Rg1, J2=11/32, r2, n=17/16, anchor128, state(2,0,0,0,17/8,0), targets128+/-1/2, enclosure step1/32, precision50, floor1/2, Picard12, max_steps4096, zero scaling.

Sine/cosine ranges are independently bounded with rational order100 series, a proved Lagrange remainder and monotonicity on |angle|<=17/32. All interval membership compares exact rationals; no sampled-point substitute, finite-difference-only derivative or fitted tolerance is used. F2 failure injection patches only the new module-local dependency seam, not F2 or force counters. Exact leaf weights and no native operation after rejection are tested independently.

Actual commands/results, source hashes and split invocation counts are in the external review package. Historical short F3/B2/B3/B4/B6 corpus checks complete recursively serialized results/counters and all first-domain records, not summaries. The old 417 sources remain byte-identical. This does not broaden the old numerical/physical qualification.

C5 old/new 60-second diagnostic, H5, event search, Sun/segment/local adapters, input codecs/persistence and combined qualification remain **NOT_RUN/UNRESOLVED**. No old-policy replacement, checkpoint schema change, integration campaign or performance claim follows from these analytic gates. Stop for independent review.

## B19 candidate — explicit resource policy v2

B16/v1 is committed; accepted B17 completed the bounded60s C5 comparison.
The earlier C5 NOT_RUN statements describe the frozen B16 stage. This B19
candidate changes only this contract, the zonotope module and its owner tests.
No long obstruction/H5/day query is authorized. Combined qualification remains
UNRESOLVED; H5 success unestablished; historical B7 cause UNKNOWN.

Public v2 API:

    J2ZonotopePolicyV2(base_policy, scale_exponents, max_scalar_operations)
    evaluate_j2_zonotope_enclosure_v2(trajectory, instant, solver_config, policy)
        -> J2ZonotopeResultV2

Both new records are frozen/slotted distinct dataclass types. They reuse the
v1 field definitions and proof helpers, with explicit init=False
resource_policy_version=2 in v2 only. Algorithm method_id remains
m2-centered-zonotope-pb6-v1, algorithm method_version=1. V1 records gain no
fields; v1 default ledger/cap domain stays1..2^24. V2 exact-int cap is1..2^31.
Bool/int subclasses, policy subclasses and cross-version policies are rejected
before nominal execution. Method identity and resource version are validated
at the strict structural ownership boundary; versions cannot be selected via
constructor arguments or arbitrary overridden identities.

_ArithmeticV2 has its own bounded bootstrap, with the same initial counter,
context and trap construction as v1. It inherits every accounting operation
unchanged. It does not construct then increase a v1 ledger, expose a generic
larger-ceiling argument, mutate globals, reset work or top up a running query.
One ledger owns every proof endpoint. Charge-before-work, exhaustion latch,
leaf+reserved=total, rank/rounding and atomic publication are unchanged.

The smallest factoring shares execution/counter publication and policy
normalization methods. Valid v1 and v2 inputs at the same cap execute identical
protected leaves and control reservations. Their intended differences are
the policy/result type and v2 resource-policy field. Immutable trajectory,
original-anchor accumulated uncertainty, signed exact grids, complete-set
Picard/radius predicate, Jacobian/PB6, scaling, generator limits and mandatory
independent F2 are preserved. F2/oldF3/segment/local/Sun owners, codecs,
checkpoints and package dispatch remain unchanged.

### Static resource bound after factoring

The proof helper bodies, per-step loop domains and reservations are unchanged:
446013 leaf upper +66944 control upper =512957 <C_STEP524288.

New fixed structural routing/identity work is at most64 bounded guard,
selection/call/control units; it is covered by the existing512 admission
control schedule. Exact type/version/cap checks needed to select a ledger are
bootstrap ownership guards, not uncharged Decimal proof operations. They
make no physical evaluation. Numeric policy/authority reconstruction still
starts only after the512 reservation succeeds. There is no additional
version charge or hidden subtraction from a running ledger.

A separate deliberately loose fixed-work envelope checks headroom in8192:

| Fixed phase, excluding separately admitted authority metadata | Upper units |
|---|---:|
| Admission/bootstrap/routing/grid control schedule |512|
| Exact span/grid arithmetic leaves |128|
| Initial point-set/scaling/projection/domain leaves |512|
| Initial set/projection/domain control (128+256+128) |512|
| Final <=12-column projection/distance/conversion/publication leaves |1536|
| Final projection/publication controls (256+256+128) |640|
| Total |3840|

The initial domain leaf bound157 is the same whole-set check as in the step
proof. A final projection at12 columns costs at most
6*(3+3+12*(3+3+5)+2*5+2*7)=972 leaves. Six distances contribute<=192,
two three-element maxima4, two upward binary64 conversions<=20, twelve
endpoint copies12 and center/generator publication<=78; total<=1278<1536.
Initial leaves<=512 and grid leaves<=128 cover their fixed six-coordinate and
exact-rational loops. The64-unit structural allowance fits the512 schedule;
there is no extra matrix product or unbounded version-dependent loop.
Thus3840<=8192 continues to bound fixed overhead. Dynamic metadata remains
separate; F2 has its independent nominal step limit and is not silently
included as proof-ledger Decimal work or a wall-time guarantee.

For exact C5 metadata44856, fixed metadata+overhead remains53048. Proposed
future obstruction reservation1813040952 and C_STEP524288 are unchanged.
That future query remains NOT_RUN; this source revision alone demonstrates
neither long-horizon capacity in wall time nor a solution to interval growth.

### B19 verification boundary

Owner tests cover cap/type/version boundaries, very high counters using
bounded single reservations/operations, latched rejection before context
execution, complete signed analytic circle tubes, atomic failures and
zero-span mandatory F2. Complete short scientific values and all accounting
are compared across versions, while identities remain distinct.

After the focused gate, only two fresh standalone C5 children are allowed:
one v1 then one v2 on accepted physical bytes at128..188s, same base/nominal
config/scales and cap2^24. Each gets15s execution and shared2s cleanup;
whole sequence40s, require17s remaining before launch. First failure prevents
the second. No replay, warm-up, observer or B17 evidence edits. Compare complete
v1 canonical output to saved B17 new-method output; retain v2 resource identity
and report every scientific/counter difference. Results and actual command
counts belong to external B19 evidence, not predictions in this contract.
