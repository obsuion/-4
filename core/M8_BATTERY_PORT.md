# B58 reduced pack port and connected lifecycle

All pack coefficients are **ASSUMED**, not spacecraft/cell measurements or
flight calibration. SOC_proxy is stored Wh/current usable Wh, not Ah-SOC.
The 28 V regulated construction bus remains a separate ideal converter port.
None keeps the legacy fixed-efficiency Wh law and old input/native formats.

## Physical contract

Positive current discharges. With r>=0, discharge solves P=I(Voc-Ir) on the
low-current branch using 2P/(Voc+sqrt(Voc²-4rP)). Charge uses current -J,
P=J(Voc+Jr), and 2P/(Voc+sqrt(Voc²+4rP)). At r=0 current=P/Voc. D=0 is an
explicit algebraic boundary; negative D is unavailable, never clamped.
Independent tests use the other quadratic form in 80-digit Decimal and
Kirchhoff/power residuals with stated binary64 rounding allowances.

Discharge terminal power=delivered bus W/eta_d; chemical W=Voc I.
Charge terminal power=accepted bus W eta_c; chemical W=Voc J.
Stored Wh changes by chemical W dt/3600. Ohmic heat=I²r; residual converter
loss is separate. The new eta=.95/.95 are explicit residual-converter
assumptions, not a claim that legacy lumped losses excluded internal heat.
Wire losses remain on the unchanged nonlinear construction branches.
`conversion_loss_wh` in the new neutral result denotes total irreversible
Ohmic plus converter loss; its type is never BatterySubstepTransition.

OCV is piecewise linear at energy fractions 0,.2,.8,1 and 26,28,32,33 V,
with -.002 V/K temperature coefficient about 298.15 K. R=.12 Ohm times
(1+D_R), exp(.02*(298.15-T)), and (1+.25*(1-SOC_proxy)²).
Port domain:230..360 K, R<=100 Ohm, D_R<=64, terminal22..35.5 V,
discharge<=8 A/200 bus W, charge<=4 A/120 bus W, plus original bus/current
and battery power limits. Feasibility is prospective, including available
chemical Wh and charging headroom. At most eight nextafter-to-zero power
reductions repair floating feasibility before publication; no energy clamp.
Excess PV is curtailed. Unsupported moving loss retains paid pose/pending.

Selected history adds exp(ln(2)/10*(T_rep-298.15)) times
(1e-8 dt +1e-5 chemical-throughput-Wh) to D_R. T_rep is accepted thermal
start/end midpoint. Time-weighted seconds and chemical throughput are also
stored. This is a bounded empirical assumption, independent of the unchanged
capacity-retention ageing law. Exponent/domain failures are typed refusals.
Declared aged input D_R=31 means a different initial experiment, not 15 lived
years. Coefficients are fixed before outcome inspection.

## Transaction and knowledge

The new transaction uses pure accepted wire, thermal, capacity-degradation,
solar-degradation and capacity-reconciliation owners. Ohmic heat goes once
to the configured battery node; converter heat once to configured BUS.
No legacy fixed-eta EPS carrier is fabricated. Private context is validated
before publication. Only selected cuts advance resistance history; rejected
allocation, quiet, wait/TX proposals retain paid work and publish no history.
All action paths use the allocation owner, including passive OFF and boot/TM.
Functional acquisition/radio/OBC grants require actual full component service.

The onboard BMS is explicitly an exact sampled-model sensor assumption.
Ground receives port history only in powered delayed observations; paid
catch-up owns separate forecast state/work. Current hidden actual values do
not become ground knowledge. The common 50%->75% preventive solar policy,
hardware, workload, harness and thermal forcing remain unchanged.

## Numerics, persistence and diagnostics

V6 input/native and fixed graph registry preserve policy/state/history,
queued observations, paid pending motion and custody. No checkpoint migration.
Unit-aware B58 quiet tolerances: .01 V, .001 A,1e-5 Ohm,1e-8 D_R,.01 weighted
seconds, alongside original Wh/K/retention tolerances. Port heat uses Wh.
Unknown port units reject. Voltage/current/discriminant/service/capacity
boundaries force detailed fallback. Quiet comparisons are local nominal
screens, not continuous safety proofs.

Predeclared short quiet/detailed/finer physical screens: .005 Wh,.05 K,
.05 V,.001 Ohm at supported shared endpoints, before day/month. Actual
campaign refinement, delivery and restart results belong to external
source-bound evidence, not these assumptions. No ranking is required.

Reports show selected start-held V/I/R, cumulative Ohmic/converter Wh and
limits with actual/received/estimated lineage. Extrema are sampled only.
Legacy pack voltage is UNAVAILABLE. Summary/CSV/progress never authorize
restore. A separately versioned controller admits exact worker membership
and its own SHA; CLI and Workbench use the same input/service/runner paths.

F1 admits strict count/index/byte constraints before whole-store work and
streams actual file inventory with O(1) additional memory. Raw/compact,
unexpected-file rejection and pinned-prefix semantics are retained.

## Source boundaries

PyBaMM's [Thevenin documentation](https://docs.pybamm.org/en/latest/source/api/models/equivalent_circuit/thevenin.html)
(description and options, retrieved17 October2026) describes OCV, resistance
and optional RC elements with thermal coupling. Its
[resistor implementation](https://docs.pybamm.org/en/latest/_modules/pybamm/models/submodels/equivalent_circuit_elements/resistor_element.html)
(`get_coupled_variables`) uses current-squared resistance heat. B58 takes
only this reduced architectural pattern; it does not install PyBaMM or
implement RC relaxation.

[NASA2006 charging brief](https://ntrs.nasa.gov/citations/20100014167)
(record abstract) motivates distinguishing terminal voltage and internal
drop; its charging protocol and coefficients are not adopted.
[NASA2018 calendar-ageing presentation](https://ntrs.nasa.gov/citations/20180003308)
(record abstract) concerns particular cell models and test conditions, not
a universal resistance/capacity lifetime law. No public hardware numbers
from these sources are used as B58 pack coefficients.

Full electrochemistry, relaxation, calibration, complete actuator plant,
year/15-year campaigns and full O5/Version M remain open. Combined
qualification UNRESOLVED; historical B7 cause UNKNOWN. The historical
preservation FAIL_UNEXPLAINED_NO_EXCEPTION remains unresolved.
