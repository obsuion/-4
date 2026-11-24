# Task 06B: F4 J2 input binding and deterministic reconstruction

Author-authorized candidate on accepted Task 06A commit
`ff4e26c305ece6cd9ee2d117da1d1ab31f03aee5`, pending independent review.
This fulfills the persistence boundary left open by `V5_J2_ENCLOSURE.md`.
That document and D319 remain the historical F3 numerical contract. F1, F2,
F3 and S008 are unchanged; this task introduces no scientific coefficients,
new propagation algorithm, numerical qualification or visibility certificate.

## One immutable authority

`orbit_j2_binding.J2CoastOrbitInputs` contains the complete original
`J2CartesianTrajectory`, `J2RK4SolverConfig` and `J2EnclosurePolicy`. Both
position and velocity retain their concrete frames, TT epochs and original
sample instant. Gravity retains independent mu, unnormalized J2 and gravity
reference radius, including every scalar's provenance. F1/F2/F3 input owners
are reconstructed, not replaced by IDs or nominal orbit labels.

Supported persisted semantics are:

| Field | Supported value |
|---|---|
| model | `v56f-static-axis-cartesian-j2` |
| representation_version | 1 |
| binding_version | 1 |
| policy_version | 1 (the accepted F3 enclosure algorithm/policy) |

These versions are validated exact integers and exact model text, not switches
selecting unimplemented algorithms. A changed or missing version is rejected.
All three physical/numerical definitions are required; version defaults name
the sole supported format and do not supply physical coefficients or policies.

The existing keyword-only `SimulationInputs.coast_orbit` slot accepts exactly
`CoastOrbitInputs`, `J2CoastOrbitInputs`, or None. There are still seven
positional inputs and the same eight persisted field names. Use
`context.with_j2_coast_orbit(inputs, coast)` to bind J2; the original
`with_coast_orbit` remains the explicit two-body helper. Neither accepts the
other owner's type. Rebinding already valid inputs is deterministic; stale
inputs must not be used as the starting point for a helper.

## Identity and portable format

J2 reserves all manifest labels starting `v56f4-j2-coast`; its complete label
is `v56f4-j2-coast-sha256-<64 lowercase hexadecimal digits>`. No owner, the
old owner, stale content or the other namespace cannot satisfy a J2 binding.
Legacy B2 representation/binding 1/1 and its literal digest are unchanged.

The J2 binding payload contains:

- binding version and the entire typed canonical J2 input record;
- manifest schema and spacecraft/numerical/environment/flight-rules/scenario/
  world/controller ID associations;
- timestep, geometry sampling and checkpoint cadence as exact integers;
- world horizon and the ordered world event IDs.

`_binding_context` shares the existing B2 validation/encoding of the last three
items without changing its historical payload. The old derived manifest label
is validated but excluded. Hash sorted compact JSON with `ensure_ascii=True`,
`allow_nan=False`, separators `(',', ':')`, UTF-8, SHA-256. Binding is a bounded
content identity, not authentication. It does not fingerprint same-ID hardware
changes, external source-document bytes, executable code or the environment.
`ExperimentBundle` independently hashes the complete input/program graph and
checks executable/environment provenance at restore; those checks remain active.

`J2CoastOrbitInputs.to_dict/from_dict` use existing canonical-version-1 typed
records; `to_json/from_json` use its strict JSON boundary. No separate lossy
float codec is introduced. Floats use exact binary64 hex, integers canonical
decimal text, list/tuple types and order stay distinct, Unicode scalar text is
preserved without normalization. Unknown/missing fields, types, versions,
duplicate JSON keys, malformed/noncanonical/nonfinite numbers and hostile
metadata reject. Physical constructors retain their accepted positive-zero
normalization. Canonical encode/decode comparison rejects a forged/wire
negative zero that a physical constructor would normalize; generic typed float
encoding still distinguishes signed zero. No caller subclass coercion is added.

The allowlist adds only J2 gravity, trajectory, nominal solver, enclosure policy
and the new input record. `J2EnclosureResult` is deliberately excluded: its
computed fields and Decimal intervals are not authoritative portable inputs.
No arbitrary class import, init=False field exception or schema-coverage bypass
is introduced. Checkpoint schema 5, canonical/bundle versions 1 and program
versions 1-7 remain unchanged.

## Clock, restore and rejection boundaries

`context.evaluate_context_j2_enclosure(context)` first revalidates the complete
completed-step context, including its content binding. It evaluates unchanged
F3 at `GeometryInstant(original_reference_epoch, simulation_time_seconds)`.
An anchor at 128 s and clock at 100 s request the original IVP at 100 s, a
backward span of 28 s; they do not request 228 s. Original inputs never reanchor.

The query does not advance time, alter battery/thermal/propulsion/knowledge/
controller state, mutate continuation memory, or cache propagated authority.
An unresolved F3 result retains its explicit reason and no usable nominal state,
intervals or error bounds. Query spans retain all F3 admission/work limitations.

Binding, serialization, hashing and restore do no integration. Reconstructing
F2 inputs includes its existing constant-work initial-force admission, not a
long query. `_validate_inputs` and engine completed-context reconstruction
already forward the same coast slot; tests exercise that path with J2 in
generic, imaging, imaging-to-storage and legacy downlink execution. Engine
steps do not query orbit implicitly or change their existing forcing semantics.
The two-body query and temporal search explicitly reject J2. This is not a
replacement J2 search, geometry, contact or observation pipeline.

Schema-5 capture stores the existing manifest ID alongside mutable simulation
state. Restore requires matching external immutable inputs and validates them
before allocating mutable snapshot state. `ExperimentBundle` also carries the
whole J2 input graph, existing program and memory, so a fresh process can
reconstruct without the original fixture. Saved status/bounds are never read
as authority; report-only evidence is computed anew after reconstruction.

A raw schema-5 checkpoint plus externally supplied inputs provides the existing
bounded ID check, not the bundle's complete content/provenance guarantee.
Different executable code can legitimately make a historical bundle incompatible.
Historical experiments should run on their recorded code/environment. F4 does
not promise cross-code bundle restoration or physical accuracy from persistence.

## Reproduction and independent acceptance checks

The small example reuses the synthetic inclined F3 pilot trajectory and the
existing version-1 acquisition/downlink script. Initial clock is 100 s, anchor
128 s. Save after two real actions at 146 s with a partial transfer, then run
four more actions in fresh processes to 238 s. It intentionally retains the
script's legacy downlink without concurrent EPS/thermal evolution. It does not
claim that its declared observations or serviceable contacts came from J2.

PowerShell, from repository root; all output paths are external:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$task06bTemp = Join-Path $env:TEMP ('task06b-reproduce-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $task06bTemp | Out-Null
.\.venv\Scripts\python.exe -B -m examples.v5_j2_bundle_demo --output "$task06bTemp\direct.json"
.\.venv\Scripts\python.exe -B -m examples.v5_j2_bundle_demo --stop-after 2 --bundle-output "$task06bTemp\bundle.json" --schema-output "$task06bTemp\schema.json" --inputs-output "$task06bTemp\inputs.json" --output "$task06bTemp\partial.json"
.\.venv\Scripts\python.exe -B -m examples.v5_j2_bundle_demo --resume "$task06bTemp\bundle.json" --output "$task06bTemp\bundle-resumed.json"
.\.venv\Scripts\python.exe -B -m examples.v5_j2_bundle_demo --resume-schema "$task06bTemp\schema.json" --inputs "$task06bTemp\inputs.json" --output "$task06bTemp\schema-resumed.json"
.\.venv\Scripts\python.exe -B -m pytest -q -ra -p no:cacheprovider --basetemp="$task06bTemp\tests" tests/test_j2_binding.py tests/test_j2_binding_restart.py
```

Compare each resumed `initial` object with `partial.final`, and each resumed
`final` with `direct.final`. Exact same-runtime equality is required for complete
checkpoint, memory, decisions, record custody, delivery metrics, nominal state,
Decimal interval endpoints, bounds and original anchor. This is deterministic
reconstruction, not an approximate geometry tolerance or a new accuracy test.
Tests prohibit rebuilding from the origin fixture in the child process. F3's
independent analytic numerical references remain in `test_j2_enclosure.py`.

The clean pre-edit no-orbit and B2 fixture encodings are frozen by exact byte
length and SHA-256, alongside the existing B2 fixed-digest test. Same-ID value,
metadata, frame, TT/anchor, every policy field/version and numerical/world
changes must alter identity or fail validation. Namespace substitutions must
fail before mutable restoration or propagation. Changed source/environment must
still fail bundle compatibility checks. Actual commands, successful and failed
development logs, source hashes and final counts are retained externally.

The demo's frozen J2 manifest digest is
`c8c58093cd88e1ec8c26c9b5143de2a5af8dbb3292a7f75ce12bb7ba892acb53`.
It belongs only to the documented synthetic definitions and binding context.

## Open work and evidence boundaries

J2 temporal visibility, segment/continuous geometry interfaces, Family B interval
view/end-ray correction, long-horizon qualification, maneuvers, orbit-driven
campaign forcing and full V5 remain open. No new flight/hardware result, 05C
ranking or campaign result follows. Accepted 06A's 7170 passes are historical;
its Linux 67 tests, nine external probe groups and six pilot reproductions are
external review evidence, not Task 06B test runs.

The ignored-file discrepancy is a verified counting-scope difference for the
available 06A inventories: 1590 excludes `.venv`; 7868 includes its 6278 files.
Both current inventories match their respective records. A separate 06A Git
write-context enumeration reported only the 6278 environment files with existing
`.pytest_tmp` access warnings. The normal read context enumerated all 7868.
No ignored file was removed to reconcile counts, and this does not establish
the cause of the earlier unlabeled 05C assertion failure.
