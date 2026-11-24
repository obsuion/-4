# Task 05C: sourced counterfactual MS comparison

This is an uncommitted implementation and experiment candidate for independent
review, built on accepted Task 05B commit
`6067fd13893a71ad468bb49c4ef7bf643efbdacd`. It retains the accepted version-7
controller, idealized boundary telemetry, protected physical executors, integer
MS products and causal delivery credit. It does not complete the full V5 model.

## Question and interpretation

Under one prescribed workload, how does a six-unit battery/array allocation
affect complete, on-time MS delivery, conditional on instrument/data family and
contact availability? Primary comparisons are within each family. Cross-family
comparisons depend on assumed mode power and unmodeled radiometric quality.
Ties, inactive constraints and absent ranking reversals are legitimate results.
These combinations are not flight-qualified replicas or integrated bus designs.

## Source ledger and native hardware

All values below were checked against the primary-source content on 23 September
2026. External `sources/*-retrieval*.json` records distinguish successful local
snapshots from failed downloads. A web-verified source is not falsely described
as a downloaded PDF. Public sourcing is not flight validation.

| Family | Native MS sampling | Native swath | Captured channels | Bits/sample | Published storage | Rate ceiling | Power reference |
|---|---|---|---|---:|---:|---:|---|
| D / DMAC | 5 m at 680 km | 20 km | B/G/R/NIR | 8 | 32 Gbit = 4 GB | 30 Mbit/s | 53.2 W incoming |
| H / HiRAIS | 4 m at 600 km | 12 km | B/G/R/NIR | 10 | 256 Gbit = 32 GB | 160 Mbit/s | 100 W incoming |
| J / JSS56 | 6.5 m at 630 km | 77 km | B/G/R/red-edge/NIR | 12 | 48 Gbit = 6 GB | 160 Mbit/s, separate operator source | 93 W peak simultaneous imaging/downlink |

- D/H: Al Dhafri et al., *DubaiSat-2 High Resolution Advanced Imaging System
  (HiRAIS)*, IAC-12.B4.6A.6 (2012), section 4 final Table 1; MS channel description
  for HiRAIS in section 2. [Author paper](https://www.researchgate.net/publication/262805537_DubaiSat-2_High_Resolution_Advanced_Imaging_System_HiRAIS).
- D spectral identities are directly corroborated by EIAST authors Al-Mansoori,
  Bushahab and Al-Shehhi, *Application of DubaiSat-1 imagery*, ISRS October 2012,
  first-page abstract. [Primary operator paper](https://www.researchgate.net/publication/236629336_Application_of_DubaiSat-1_imagery).
  Its Table 1 separately lists 330 W at EOL (spacecraft scope) and 64 Gbit storage.
  Those are not substituted for this task's selected 53.2 W payload reference and
  32 Gbit comparison-table entry. Storage scope/history remains an unresolved
  source discrepancy; no flight-replica claim is made. The archive's
  `sources/verification-notes.json` supplies this precise supplementary attribution
  for the frozen manifest's aggregate DMAC/HiRAIS source record. That supplementary
  paper was checked during final evidence consolidation, after protocol freeze;
  no earlier verification of it is claimed. No numerical input changed.
- J: Jena-Optronik JSS56 datasheet, April 2015, PDF page 2 performance/power
  table. [Datasheet](https://www.jena-optronik.de/products/space-optics-electronics/multi-spectral-imager.html?file=tl_files%2Fpdf%2FData+Sheet+JSS+56.pdf).
  The separate [KazEOSat-2 operator table](https://www.gharysh.kz/infrastruktura/AboutKA_DZZ22_yztp/)
  supplies the X-band rate; 5 m orthophoto output is not native 6.5 m sampling.
  Conflicting instrument/spacecraft mass scopes are not imported.
- BP8: DS1069134 rev 1.2.0, 10 April 2026, printed p1 section 1.2, p5 Table 2.2,
  p11 Table 4.1 (PDF pages 5, 9, 15): 100 Wh nominal, 86 Wh recommended range,
  23.6 V recommended minimum, 4 A discharge, 3.4 A charge, 486 g.
  [Datasheet](https://gomspace.com/wp-content/uploads/2025/08/gs-ds-nanopower-bp8-100-Wh-2.pdf).
- TSP: DS1038993 rev 3.3, 24 May 2024, p8 section 2.1.1: approximately 45 W
  illuminated reference; cell figures at 1367 W/m2, BOL, 25 C. Detailed p24
  section 7 gives 885 g; summary p9 gives 750 g. This study selects the detailed
  table and retains the conflict. [Datasheet](https://gomspace.com/wp-content/uploads/2025/09/Datasheet-NanoPower-TSP_45W.pdf).
- P80: product page Technical insights, Power Supply Module and Power Management
  Unit: up to 300 W and common 12 A input/output ceiling. The advertised up-to
  efficiency does not justify an assumed constant efficiency.
  [Product specifications](https://gomspace.com/product/nanopower-p80/).

`comparison_manifest.manifest()` exports strict machine-readable SOURCE and
ASSUMED entries, with units, source revision/location, conditions, transform and
consumer. `hardware_ledger()` adds consumer-level DERIVED entries for every
configuration. `manifest.json` and `hardware.json` are archived before main runs.
The supplemental verification notes distinguish context-only 100 Wh nominal BP8
and 750 g summary TSP values from the actual 86 Wh/885 g consumers. The external
`all-consumed-scalar-parameters.json` and `experiment-design-ledger.json` enumerate
actual scalar consumers and non-scalar design assumptions respectively.

The assumed small-angle normalization is `native * 630 / reference_altitude`.
D sampling is exactly 315/68 m, H 21/5 m, J 13/2 m; swaths are 315000/17,
12600, and 77000 m. Exact rational derivations remain in the manifest. One
binary64 conversion supplies the accepted API, without decimal rounding or a
second altitude scaling. Integer sizing charges ceiling(width/spacing) times
ceiling(length/spacing) times captured bands times bit depth. J pays for five
bands although each requested product requires only B/G/R/NIR at <=6.5 m.
MS-only use of PAN-capable references is a counterfactual assumption; no PAN,
compression, packet overhead or equal radiometric quality is inferred.

Storage availability fraction 1.0 and useful link-rate fraction 1.0 are separate
optimistic assumptions. Storage uses decimal units, with eight bits per byte.

## EPS allocation and power assumptions

| EPS | BP8 packs | TSP arrays | Working energy (Wh) | Initial energy (Wh) | Illuminated reference (W) | Battery/array partial mass (kg) |
|---|---:|---:|---:|---:|---:|---:|
| E1 | 4 | 2 | 344 | 172 | 90 | 3.714 |
| E2 | 3 | 3 | 258 | 129 | 135 | 4.113 |
| E3 | 2 | 4 | 172 | 86 | 180 | 4.512 |
| E4 | 1 | 5 | 86 | 43 | 225 | 4.911 |

The 86 Wh window is applied once, as modeled beginning-of-life usable capacity;
retention is 1.0, not 0.86. Six units are not equal cost, mass or volume. Partial
mass is reported only, never inserted into inertia or a total spacecraft mass.
Battery and array counts vary together: attribution is to the combined EPS
allocation, not exclusively battery capacity or array size.

Let n be packs, V=23.6 V, eta_c=eta_d=0.9 (ASSUMED). The existing battery API
accepts bus charging power before charging loss and supplies bus discharge power
after discharge loss. Derived constant screening limits in watts are:

```
charge_bus = min(300, V*12, V*min(3.4*n,12)/eta_c)
discharge_bus = min(300, V*min(4*n,12)*eta_d)
```

Thus discharge limits E1/E2/E3/E4 are 254.88/254.88/169.92/84.96 W, subject only
to binary64 representation. The minimum-voltage construction limits electrical
draw under the declared approximation; it is not a validation of P80 channels,
voltage conversion, bus wiring, mounting or deployment. Those remain unverified.

The **ASSUMED mode mapping** sets incremental imaging and transmitter demand each
to P_ref, in separate mutually exclusive actions. A common 12 W essential bus
baseline applies throughout. No action adds both increments. Both proxies are
multiplied by 0.5 in the sensitivity study. This is neither a demonstrated
conservative bound, flight calibration, confidence interval nor a claim that
true mode loads lie between these values.

## Shared workload and Methods draft

Each deterministic run spans 0..3600 simulation-relative seconds. Six distinct
10 km cross-track by 30 km along-track rectangles are released at 0, 300, 600,
1800, 2100 and 2400 s, with priorities 3,2,1,3,2,1 and common 300 s acquisition
windows. Acquisitions last exactly 60 s. The first and second groups have inclusive
delivery deadlines 1500 and 3500 s. Admission ends at 2700 s, followed by a 900 s
drain interval. All six requests remain in the priority denominator 12, even if
infeasible. Footprints fit the narrowest normalized swath; swath is inactive.

S1 contacts are [900,910), [1200,1210), [2700,2710), [3000,3010), [3300,3310).
S2 removes the second and fourth, identically for all configurations. Inputs,
requests, forcing, initial fractions, controller, knowledge and scoring remain
identical. These are declared serviceable synthetic intervals, without geometric
visibility, real availability, RF success or telemetry reconstruction claims.

The transparent budget is 12 Wh baseline per hour, at most 360 s incremental
imaging, and 50 s (S1) or 30 s (S2) contact duration. Raw per-product volumes are
447482976 bits D, 680299320 H and 426241440 J. Contact capacity uses each family's
declared useful rate. Transfers and unused contact standby retain the existing
duration-consistent multi-record executor; nominal capacity is not itself credit.

Independent budget arithmetic makes two inactive constraints explicit. Even all
six products occupy only 8.39%, 1.59% and 5.33% of the declared D/H/J capacities.
Under the assumed mode proxies, a fully served hour with all six acquisitions and
all 50 s transmitter time draws at most `[12 + P_ref*(360+50)/3600]/0.9` Wh from
the battery if solar generation is omitted. The largest value is 25.99 Wh (H),
below E4's initial 43 Wh. Thus energy exhaustion and published storage capacity
cannot bind in this workload. This is conditional arithmetic for specified model
inputs, not a bound on actual hardware power. Current/power service limits and
contact deadlines/capacity can bind. Separate perturbations test energy capacity,
generation and storage wiring; the main campaign does not establish their optimal
sizing or a battery-energy tradeoff. Exact budget fractions are archived in
`independent-workload-budgets.json`.

Common normalized physics is fully listed in `COMMON_ASSUMPTIONS`: initially
half working energy, empty custody, retention 1, throughput 0, temperatures
293.15 K; darkness until 1800 s then normal incidence illumination. Each of the
bus/battery/payload nodes has C=50000 J/K, emissivity 0.8, area 0.2 m2, sink 250 K,
no conductive links or external absorbed heat. Operating limits are 270..320 K,
survival 250..340 K. Electrical heat is retained on the bus except payload heat;
battery conversion heat uses the accepted owner. Thermal equality is normalization,
not a physical equality between real spacecraft or battery-pack counts. Calendar
and cycling damage rates are zero for this one-hour experiment. Delta-v is zero.
ADCS is common and held at the same prescribed nadir boresight, with an assumed
45-degree view limit, 5 s settling and 0/0 to 90deg/180s slew envelope; slew is
inactive. The unused PAN spacing is an explicitly documented positive placeholder.

The unmodified version-7 policy uses 3600 s lookahead, 300 s polling, three-action
plans, at most 32 decisions, 64 candidate evaluations and 4096 forecast EPS work
units. Every node temperature is explicitly observed at idealized zero-latency
boundaries; the temperature-estimate tuple is explicitly empty. Planning acts
only on received knowledge. Unknown future releases are not supplied as truth.
Budget exhaustion is an incomplete run, never a completed zero-score case.

Original H-E4/J-E1 pilots used 120 s acquisition windows and completed in
61.5536835/86.4875778 s. Polling could miss new releases before they closed.
The single allowed common workload adjustment widened windows to 300 s without
changing the controller or 60 s physical duration. Original pilot artifacts are
retained; adjusted pilots cover both configurations at levels 0,1,2. Runtime is
measurement of this example including replay/validation, not a hardware benchmark.

Before main rankings, the machine protocol freezes manifest/code/environment
digests, workload, policy, all levels, factor-0.5 sensitivity and contrasts.
The predeclared runtime budget is 10800 s with four independent worker processes,
not an invented conference cutoff. Conservative extrapolation treats all 216
full-matrix executions as slow as the slowest pilot. If it exceeds the budget,
the balanced D/H/J x E1/E4 subset is selected before main execution; all twelve
hardware definitions remain and omitted cases are explicit. No field or policy
branches on a desired configuration ranking.

The primary score is exact sum(priority * complete-on-time)/12. Reports retain
every request, exact rational completion/latency, raw acquired/queued/delivered
bits, partial/late statuses, actual denials and forecast rejections with causes,
resource samples and measured runtime. Raw decisions and custody are archived.

## Numerical and reproducibility evidence

Levels 0,1,2 use the existing 1,2,4 internal subdivisions, preserving physical
intervals and policy/work limits. Both nominal and factor-0.5 rolling runs are
evaluated at all levels. Each nominal finest requested sequence is also held
fixed at all three levels through the accepted protected executors; this fixed
experiment is not represented as a new rolling history. Protection is enabled.

The predeclared finest-pair screen requires identical per-request on-time credit,
maximum energy discrepancy <=0.001 configured working capacity, and maximum
corresponding node-temperature discrepancy <=0.1 K. Actual rational physical
sample times are intersected, including internal contact boundaries; there is no
index matching or interpolation. Action-sequence and exact completion-time
changes are reported separately. These engineering screens qualify only the
executed study and do not broaden Task04C into a universal timestep theorem.
Missing, failed, nonfinite or incomplete evidence fails closed.

The predeclared restart case is nominal D-E1/S1/level2 at its first actual partial
transfer. The accepted content-bound bundle is restored in a fresh process and
compared to uninterrupted final decisions, custody and physical state. The actual
910 s boundary contains 300000000 partially received bits; fresh-process execution
completed with exit 0 and exact equality of all compared authoritative fields,
including the entire physical-sample history. Wall time and the convenience
boundary-list prefix are excluded explicitly. This is a completed action boundary,
not a mid-contact restart. Matching adjusted pilots were reused with explicit
input/source/result hashes, not silently rerun.

## Executed comparison and qualification

The frozen slowest-pilot extrapolation was 8906.0868198 s against the declared
10800 s planning budget, selecting all twelve configurations before main rankings.
The full matrix completed: 144 rolling cases (12 hardware x 2 scenarios x 2 mode
factors x 3 levels), plus 72 nominal fixed requested sequences. All 216 have exit
0 and completed-horizon status; failed, missing and omitted-case inventories are
empty. Six adjusted pilots and three earlier fixed cases are explicitly reused.
Two original exploratory pilots and the additional fresh-process restart are
separate evidence, not extra hardware configurations.

The following finest-level results group ties only; all twelve hardware vectors
were executed. Entries are exact weighted score (complete on-time product count).

| Hardware | S1 nominal | S2 nominal | S1 half proxy | S2 half proxy |
|---|---:|---:|---:|---:|
| D-E1, D-E2, D-E3, D-E4 | 2/3 (3) | 1/4 (1) | 2/3 (3) | 1/4 (1) |
| H-E1, H-E2, H-E3 | 1 (6) | 11/12 (5) | 1 (6) | 11/12 (5) |
| H-E4 | 1/2 (3) | 1/2 (3) | 1 (6) | 11/12 (5) |
| J-E1, J-E2, J-E3 | 1 (6) | 1 (6) | 1 (6) | 1 (6) |
| J-E4 | 1/2 (3) | 1/2 (3) | 1 (6) | 1 (6) |

Independent integer contact-volume arithmetic gives score ceilings of 2/3 and
1/4 for D, 1 and 11/12 for H, and 1 in both scenarios for J, ignoring power and
thermal restrictions and allowing ideal request selection. The recorded outcomes
reach those ceilings except nominal H-E4/J-E4. Their three dark acquisitions are
rejected by the protected forecast: assumed bus loads 112/105 W exceed E4's
84.96 W discharge limit. The controller executes standby; actual denial events
are zero. Halving the proxies gives 62/58.5 W and closes the within-family deficit.
This is conditional evidence about the combined EPS allocation and assumed mode
mapping, not calibrated flight power or a general scheduling optimality proof.
Other allocations tie; no reversal was introduced by tuning the experiment.

All acquired records in the 48 finest rolling cases were received completely and
on time by the horizon; unacquired expired requests retain zero credit. Final
partial/late product counts and onboard backlog are zero, but 32 of those cases
have actual intermediate partial-transfer boundaries. Exact completion/latency,
allocated versus received bits, forecast causes and actual feedback are retained
in request-results.csv, campaign-results.csv and the raw histories. Forecast
rejections also include already-acquired/expired requests and are not all
protection failures. Minimum sampled battery energy is 33.35870968749998 Wh;
all sampled node temperatures lie between 290.979656922258 and
293.2320909625278 K. No sampled operating/survival violation or unmet load occurs.
This does not establish continuous safety or real thermal equivalence.

All 72 finest-pair screens passed: 24 nominal rolling, 24 half-proxy rolling and
24 nominal fixed-sequence comparisons. Maximum energy discrepancy is
4.547473508864641e-13 Wh; maximum corresponding-node temperature discrepancy is
0.0013901868808829931 K. The level-0/1 maximum temperature discrepancy is
0.0027882353198265264 K; all 72 of those comparisons also pass. Every coarse sample
time is present in its finer comparison. Per-request credit, exact completion
times, requested actions, actual protected segments, record-service bits/times
and protection reasons agree. This does not generalize beyond the executed
workload, physics and declared engineering thresholds.

Additional external checks use independent rational pixel ceilings, exact
contact-volume arithmetic, full interval/bit conservation, and an exact-rational
piecewise-constant energy reference for this zero-ageing, fixed-efficiency study.
The last comparison's maximum discrepancy is 5.32221236533865e-13 Wh. Its documented
roundoff allowance is a diagnostic, not a rigorous floating-point enclosure or a
replacement for the frozen criteria. See analytic-contact-budgets.json,
actual-action-refinement.json and physical-execution-ledger.json.

Actual per-case result runtimes are retained: rolling minimum/median/maximum
73.9554/185.7581/3150.9835 s; fixed sequences 1.03045/2.03992/9.54407 s. Long
execution hiatuses and shared-host effects are present; no timing subtraction or
performance claim is made. These are not a guaranteed bound from pilot timing.
Runtime sums overlap concurrent runs and are not coordinator elapsed time.
Original result timing remains distinct from later reuse-check invocation timing.

Final complete regression: 7103 passed, zero failures/errors/skips, exit 0, with
unchanged candidate hashes during the run. Focused adjacent checks passed 77;
the strengthened numeric-vector assertion then passed all 30 new tests before
the final complete gate. Only MODEL_STATUS.md and this reporting document changed
afterward. The 19 warnings are existing J2/JUnit notices; no test rerun was made
solely for packaging. Historical 05B validation remains separately attributed.

## Evidence inventory and remaining limits

Generated evidence belongs outside the repository: source snapshots/statuses,
source/manifest digests, pilot logs, frozen protocol, every case's exact invocation,
inputs/provenance, process exit/status, raw result, numerical reports, CSV/JSON
tables, restart bundle/comparison, PNG/PDF figures and packaging checksums.
Plotting uses actual outputs only, including zero differences and ties.

Reproduction uses existing `.venv`, `python -B`, `PYTHONDONTWRITEBYTECODE=1`:

```
python -B -m examples.v5_ms_comparison_checks --output EXTERNAL/causal-probes.json
python -B -m examples.v5_ms_comparison_study pilots --archive EXTERNAL
python -B -m examples.v5_ms_comparison_study freeze --archive EXTERNAL
python -B -m examples.v5_ms_comparison_study execute --archive EXTERNAL
python -B -m examples.v5_ms_comparison_report --archive EXTERNAL
```

No source changes are permitted between protocol freeze and execution. Completed
matching runs may be reused; different/failed evidence is preserved, not overwritten.
The final review archive supplies the actual results, final regression evidence,
reviewer-response matrix and result-specific limitations. REPRODUCE.md distinguishes
repeating the frozen protocol with explicit pilot reuse from starting a new study
whose measured runtime may select a different fallback. FIGURE_CAPTIONS.md states
the reading limits of all three PDF/PNG figure pairs. TEST_EVIDENCE.md and
reporting-commands.json preserve validation and reporting provenance.

There is no flight telemetry validation, numerical cross-simulator benchmark,
radiometric quality model, general scheduling optimality or reliability model.
Literature mentioning another simulator is not an executed Basilisk benchmark.
Full-V5 orbital integration, OBC behavior, delayed commands/telemetry and
reliability remain on the roadmap, outside Task05C. The organizers extended
revision/response submission to 24 September; its exact cutoff hour is unspecified.
The 1 October date concerns registration. No submission or acceptance is claimed.
