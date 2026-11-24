# Task 05D: predeclared supplemental EPS stress study

This separate, synthetic mechanism study starts on accepted Task06B commit
`a3fb674f8ff12acac3ba3dce935dd28d653c18be`, parent
`ff4e26c305ece6cd9ee2d117da1d1ab31f03aee5`, following accepted Task05C
`f907dacdf85401904fe805cb9d153a88f218f4a6`. All earlier source/tests, archives
and SIDe files remain unchanged. Accepted 05C remains the manuscript baseline.
This supplement cannot delay the revision and does not complete V5.

## Predeclared question and common inputs

Does a late dark workload or low initial reserve during generation expose the
reserve/generation trade left inactive in 05C? Only J-E1, J-E2, J-E3 and J-E4
are compared, all four, chosen before outcomes. Their accepted hardware
configuration objects are reused exactly from `comparison_campaign` and the
source-traceable `comparison_manifest`: efficiencies, power/current ceilings,
thermal normalization, sampling, swath, five acquired channels, bit depth,
storage and useful link-rate assumptions are unchanged. Hardware retains its
accepted 05C identity namespace because those definitions are unchanged.
New workload/environment/world/manifest and product identities identify 05D.

The reference manifest is explicitly historical hardware/source context: its
05C half-charge entry is not the active initial condition of scenario B.
The exported protocol separately records actual initial fractions/energies;
each canonical input/program export contains the actual initial checkpoint.
The changed forcing and workload descriptions are supplied afresh, without
05C's one-hour, staggered-release, changing-illumination or multiple-contact claims.

Both scenarios publish six distinct 10 km by 30 km products at t=0. Required
channels are B/G/R/NIR; integer storage charges B/G/R/red-edge/NIR at 6.5 m and
12 bit/sample: ceil(10000/6.5)*ceil(30000/6.5)*5*12 = 426241440 bits each.
Priorities are 3,2,1,3,2,1 and all requests remain in denominator 12.
Acquisitions last 60 physical seconds. Known future windows are legitimate
published information, unlike 05C's staggered request release schedule.

The common accepted controller uses program version 7 and policy version 1:
14400 s lookahead, 1800 s standby polling, three-action plans, 32 decisions,
64 candidate evaluations and 4096 forecast EPS work units. It can wait until
known event boundaries without waiting for the full polling interval. All node
temperatures are observed under the same idealized zero-latency boundary mode.
Protection, causal replay and all constructor/execution work limits remain on.
No controller tuning by hardware, new program/schema, optimizer or new physics.

There is a common 12 W baseline. The 93 W reference maps by assumption to
separate mutually exclusive imaging and transmitter increments; both factors
1 and 0.5 are retained. These are not calibrated values, uncertainty limits or
a demonstrated conservative bound. Battery/array combinations are not equal
mass/cost designs. No new source research or spacecraft coefficient is introduced.

| Scenario | A: unavailable generation, late workload | B: low initial charge, generated power |
|---|---|---|
| Horizon (s) | 14400 | 600 |
| Initial fraction of working capacity | 0.5 | 0.01 |
| Illumination | No generation throughout | Sunlit throughout, incidence 60 degrees |
| Acquisition starts (s) | 10800,11100,11400,11700,12000,12300 | 0,60,120,180,240,300 |
| Window width (s) | 300 | 60 |
| Declared serviceable contact | [13000,13030) | [360,390) |
| Inclusive delivery deadline (s) | 13200 | 500 |

Retention is 1, initial throughput and custody are zero, all nodes start at
293.15 K. Simulation continues through the horizon after delivery or reserve
depletion under existing protected behavior. A is an artificial four-hour
no-generation interval, not a realistic LEO eclipse. B's 1% is a stress fraction
of the recommended working-energy window, not electrochemical state or flight
advice. Contacts are declared synthetic serviceability, not RF/orbit reconstruction.

## Independent arithmetic before pilots

Use exact rational values for explanatory budgets: Wh = W*s/(3600*eta_d),
eta_d=9/10. A's baseline alone removes 12*10800/(3600*.9)=40 Wh by the first
window. Initial E1..E4 energies are 172,129,86,43 Wh. E4 has only 3 Wh left
under that baseline; separately its nominal dark 105 W imaging load exceeds
its 84.96 W discharge ceiling. The factor-0.5 case is essential for separating
that instantaneous limit from reserve exhaustion.

B's initial values are 3.44,2.58,1.72,0.86 Wh. Ideal half-reference generation
is 45,67.5,90,112.5 W. Six contiguous fully served nominal 105 W acquisitions
would remove 20/3,25/6,5/3,0 Wh from the battery. This excludes rejected actions,
later standby/transmission, charge limits and actual binary64 cosine. Admission
exports the actual accepted cosine consumer's decimal and hex output and its
generated watts, rather than silently replacing it with exact 1/2.

All six records total 2557448640 bits; 160000000 bit/s times 30 s permits
4800000000 bits. Full raw storage is 48 billion bits and each footprint fits
the 77 km swath. These independent capacity margins do not themselves establish
delivery or inactivity of other constraints; executed custody, received bits,
forecast rejections and protected physical intervals remain the evidence.

## Admission, pilots and freeze

The complete matrix is declared before either pilot: 4 allocations x 2 scenarios
x 2 mode factors x 2 numerical levels = 32 rolling runs. Eight fixed controls
hold the finest nominal rolling requested sequence for E1/E4 in each scenario
at levels 1 and 2, with protection enabled. They preserve requested intervals,
record IDs and elapsed time even if actual protection outcomes differ. They
are numerical controls, not a competing controller benchmark.

The only runtime pilots are J-E4/A/factor0.5/level2 and J-E1/B/factor1/level2.
They run in two subprocesses after input, origin, knowledge and work admission
checks. Runtime includes accepted causal replay and evidence generation. An
incomplete, nonfinite, error or exceeded-work result stops the supplement,
preserving evidence; zero credit with a completed horizon is valid. Do not
redesign admission, protection, policies or workloads to recover a pilot.

The hard budget is four hours from task start. The execution deadline is 45
minutes before that. Before viewing main results, use the slower pilot's wall
time for all 40 cases, divide by two workers, multiply by two for uncertainty,
and add 600 seconds for validation tests. Reusing the two matching pilots does
not reduce this conservative estimate. If the projection cannot fit before
the reserve, retain the pilots/protocol and stop; do not select configurations.
The multiplier acknowledges unknown workload and contention differences, not a
guaranteed runtime bound. Subprocess timeouts enforce the execution deadline.

After successful pilots/budget screening, freeze the protocol plus input and
source/environment digests. No Python source changes follow freeze. Reuse the
two matching pilot outputs only with explicit input/source/result digest checks.
Every run retains canonical inputs, invocation/provenance, raw outcomes/memory,
physical samples, actual energy ledgers, custody, progress, logs and exit status
outside the repository. Failed/missing cases are never silently assigned zero.

## Qualification and reporting

Sixteen rolling and four fixed finest-pair comparisons require identical
per-request credit, energy discrepancy <=0.001*working capacity, and maximum
corresponding-node temperature discrepancy <=0.1 K. Align exact rational sample
times, never indexes or interpolated values. Report unmatched times, requested
actions, actual kinds/intervals, exact completion and protection causes separately.
For identical requested intervals every coarse sample must exist on the fine
grid. If actions differ, the resource screen concerns only exact common times;
that limited interpretation must accompany the action differences.

Export actual served/generated/curtailed/unmet energy, initial/min/final battery
energy, first sampled zero energy and forecast/actual denial times, thermal
extrema, acquired/delivered/on-time products, exact completion/deadline status,
full/partial custody and received bits. Forecast rejection logs are distinct
from executed protection. An unavailable nominal action does not consume its
forecast energy in the actual ledger. Long-standby thermal behavior is checked
at both levels. No general convergence, continuous safety or extended 04C
qualification follows. Ties and absence of reversal remain legitimate findings.

The external Methods/results supplement must explicitly say whether the full
qualified extension is fit to include. If not, retain accepted 05C as the paper
baseline and preserve complete/incomplete inventory. At most one compact figure
may be produced from actual results; no SIDe manuscript file is edited here.

## Reproduction

Use the existing environment, disabled bytecode and pytest cache, external
basetemp and outputs. Choose a fresh external directory and record the actual
task-start UTC timestamp; never restart the budget to admit a slow run.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:GIT_OPTIONAL_LOCKS='0'
$study = Join-Path $env:TEMP ('task05d-reproduce-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -B -m pytest -q -ra -p no:cacheprovider --basetemp="$study-tests" tests/test_eps_stress.py
.\.venv\Scripts\python.exe -B -m examples.v5_eps_stress_study predeclare --archive "$study" --budget-anchor '<actual task-start UTC, ISO 8601>'
.\.venv\Scripts\python.exe -B -m examples.v5_eps_stress_study admission --archive "$study"
.\.venv\Scripts\python.exe -B -m examples.v5_eps_stress_study pilots --archive "$study"
.\.venv\Scripts\python.exe -B -m examples.v5_eps_stress_study freeze --archive "$study"
.\.venv\Scripts\python.exe -B -m examples.v5_eps_stress_study execute --archive "$study"
.\.venv\Scripts\python.exe -B -m examples.v5_eps_stress_report --archive "$study"
```

Stop after any failing phase. A source-bound 7290-pass historical gate covers
unchanged accepted production; it is not a regression of these new study files.
New builder/reporting tests and the full matrix supply the supplemental evidence.
No original 216-case campaign is rerun. J2 visibility, maneuvers, OBC/failures,
remaining numerical work and full V5 remain outside this task.
