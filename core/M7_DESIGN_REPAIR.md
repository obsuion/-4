# B48-R2 / B49: finite consumed design repair

Uncommitted review candidate. The physical model remains synthetic NOMINAL_LONG.
No flight calibration, global optimum, physical/day qualification or full M completion.

The declared domain is the existing compact/outboard B42 two-battery translations
and the B47 left-bracket base-bus detour. Battery envelopes retain the authored
0.06 m half-extents, rotations, mount identities, occupancy and mass ownership.
Area choices are ASSUMED 1e-10, 1e-6, 1e-8 and 1e-7 m², in that frozen order.
Two placements crossed with four areas make eight independent hardware roots.
Definitions, other conductors/materials/connectors/slack, thermal topology,
world, requests, priorities, deadlines, C40 feedback latency, initial physical
root, controller and unconfirmed command-estimator policy remain common.

## Contract and actual execution

`DesignRepairSpec` is immutable and input-only. Its strict codec has no paths,
callbacks, scores, diagnoses, cached tensors or executable result records.
Canonical spec/root/variant identities bind every manifest. A no-op is the
baseline identity; combined area/placement edits have their own label.

The bounded constructor uses accepted assembly, construction, harness-mass and
effective-hardware owners. It resolves ports, regenerates route bindings and
endpoint/slack distributions, and recomputes mass, COM and all nine tensor
entries. No spacecraft/cache is an input to candidate construction. Static
installation/mass validity does not grant mission service or product credit.

The planner consumes typed source-bound diagnosis outside the flight controller.
FORECAST electrical screening can suggest a larger conductor without claiming
an actual electrical failure. Unknown/process/timeout evidence grants no
specific physical diagnosis. Proposals never install hardware or grant receipts.

The executor uses `start_rolling` / `step_rolling`: paid slew, actual protection,
acquisition, storage, partial downlink, completed receipts and actual MS credit.
Each complete case is saved before the next begins; later failure retains earlier
files. Forecast/actual work is independently owned per root and cumulatively
reported by a new study ledger. Whole unchanged root ceilings are reserved
before each start/reconstruction; unknown failed work is not refunded or claimed
completed. Constructor reserves 16 × 2^20 control units per bounded compile.
Study ceilings permit eight catalogue runs, one confirmation and one paid
reconstruction, plus at most 256 constructor compiles; metadata ≤16 MiB and
retained scientific case/continuation evidence ≤1 GiB. Encoding work is separate
from retained bytes. These reservations are not empirical operation counts.

Requirements are declared before runs: ≥2 actually credited products, weighted
score ≥0.5, zero returned unmet load, zero actual action refusal, and returned
temperatures within operating maxima. Incomplete/failed/zero-output roots cannot
win. Among feasible completed variants select minimum mass addition, then actual
actuator plus wire-loss energy, then stable variant ID. Pareto dimensions are
added mass and that energy, both minimized after actual feasibility admission.
This means best among admitted completed variants, not an optimal satellite.

## Persistence and trust

A study packet binds catalogue/order, completed full case evidence, work,
selection and an optional in-progress paid B48 packet. Expected packet/spec/
source/output hashes are supplied outside it. Completed cases are a strict
externally trusted evidence cache; metrics are derived again from full saved
actual science. Cache reuse is not independent execution or causal replay.
In-progress physics uses only the original-root paid B48 continuation, including
pending feedback/partial transfer and prior work. A table never seeds custody.
Final scientific study equality excludes additional study/reconstruction/cache
work, which is reported separately; native per-case scientific bytes remain exact.
Same pinned environment is required. Earlier Windows/Linux angle differences
are retained, not rounded or called cross-platform bit determinism.

## Commands

From the isolated source, using the existing interpreter with `-B` and an
external TEMP/TMP:

```powershell
python -B -m examples.m7_design_repair_demo --write-input C:\TEMP\study.json
python -B -m examples.m7_design_repair_demo --input C:\TEMP\study.json --output-directory C:\TEMP\study --all-cases
python -B -m examples.m5_command_mission_demo --input C:\TEMP\study\after-07.selected.root.json --output-directory C:\TEMP\fresh-mission
```

The evidence protocol uses one bounded case per owned worker, explicit packet
hashes between workers, a substantive fresh-process paid resume and one fresh
selected-root confirmation. The archive report supplies exact executed commands,
runtime/source bindings, failures, outcomes and budgets. The commands above are
user reproduction examples, not an assertion they ran in this form.

Prior 151-pass B48 author evidence is reused only for unchanged owners. New
affected checks and actual demonstrations have their own source-bound logs.
Hot 600 s remains NOT_ESTABLISHED. Combined qualification remains UNRESOLVED;
historical B7 cause UNKNOWN. Visual CAD, general routing, other edit families,
dynamic actuator/FDIR plants, physical event-time/day qualification and remaining
M5/M6/M7/M8 obligations stay open.
# B49-R1 reporting revision

The actual-case and study output families are now V2. Metrics explicitly use
`M7_EXECUTED_POINT_BOUNDARY_METRICS_V2`: executed POINT time comes from contiguous
returned cuts and committed start/end boundaries. Refused POINT retains its
planned profile but contributes zero executed seconds. Per-action planned and
executed seconds are separate fields. Unsupported partial-POINT states reject;
atomic refusal semantics and numerical owners remain unchanged.

Historical B49 V1 outputs retain their original source and interpretation.
Corrected reporting on those exact saved scientific bytes is labelled metric
re-derivation, never a new execution or a retagged current-source study.
