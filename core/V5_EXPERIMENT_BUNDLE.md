# Task 02: content-bound experiment continuation

This is the implemented bounded Task 02 contract with the explicit Task 03A
coupled-action extension pending coordinator review. It adds no project decision,
checkpoint schema change, new physical formula or mission controller.

## Ownership and scope

| Authority | Actual owner | Bundle treatment |
| --- | --- | --- |
| Immutable inputs | `context.py:SimulationInputs` | Entire current field graph, reconstructed with validated constructors |
| Hardware | `configuration.py:SpacecraftConfiguration` and its subsystem contracts | All fields, parameter values, units, provenance, sensitivity ranges, IDs and ordered tuples |
| Numerical/run/world definitions | `run_config.py`, `world.py:CommonWorld`, `manifest.py:ModelManifest` | All fields, including timestep, sampling, checkpoint cadence, horizon and manifest |
| Optional supported orbit | `orbit_binding.py:CoastOrbitInputs` | Full B2 two-body trajectory, solver, Cartesian state, TT epoch, frame/ellipsoid/rotation and parameter provenance; existing B2 binding remains enforced |
| Physical and operational runtime | `state.py:SpacecraftState` | Sole persistent authority remains schema-5 checkpoint |
| Ground knowledge/delivery | `knowledge.py:GroundKnowledgeState`, `data_delivery.py:GroundDataDeliveryState` | Sole persistent authority remains checkpoint, including partial transfers and completed deliveries |
| Mission/controller/diagnostics | `mission.py:MissionState`, `controller_state.py:ControllerState`, `diagnostics.py:Diagnostics` | Existing checkpoint fields preserved; no completed planning/controller implementation is claimed |
| External execution input | `continuation.py:ContinuationProgram` | Immutable complete ordered actions, their forcing and explicit assumptions |
| External causal memory | `continuation.py:ContinuationMemory` | Executed action-ID prefix and actual `ScheduledObservationExecution` supplied as prior acquisition to the imaging/ADCS boundary |
| Implementation/environment | `experiment_provenance.py:capture_provenance` | Separate code/environment identity, actual source hashes and Git provenance |

Current `EnvironmentConfig`, `FlightRulesConfig` and `ScenarioConfig` contain
only IDs. The codec includes those actual fields; it does not pretend they
already contain detailed forcing. For this supported mode, every causal forcing
value is embedded in the program. No external file is silently represented by
its name. `paper_suite.py` is not a V5 runner. The current engine's world,
knowledge, planning, arbitration and action-selection phase hooks are no-ops.

The implemented continuation mode is a deterministic ordered script with at
most 128 actions. Supported actions invoke the existing
`SimulationEngine.step_imaging_to_storage` and `step_downlink` APIs. Script version
2 additionally supports the distinct `CoupledDownlinkAction`, invoking
`step_coupled_downlink`; see V5_COUPLED_DOWNLINK.md. The origin
is a valid completed context with empty onboard custody and ground-delivery
ledgers and an explicit prior acquisition ending no later than the origin.
Nonempty ground knowledge and other valid checkpoint domains are retained.
The origin time and initial diagnostics step count are explicit program fields.
An empty script and an empty executed prefix at the origin are valid, explicit
values; missing memory or missing prior acquisition is invalid.

Every action occupies one full fixed engine step, contiguously from the origin
and within the world horizon. Imaging actions contain execution, record ID,
EPS environment and loads, thermal boundaries, routing, external heat sources
and optional solar degradation forcing. Downlink actions contain a declared
serviceable contact and record ID. Coupled downlink additionally requires typed
transmitter demand, baseline loads, solar forcing, thermal routing/boundaries,
external heat and explicit optional solar degradation forcing. Acquisition record IDs and action IDs are
unique within the program. Downlink refers to an earlier script acquisition.
The executed prefix is also the forcing cursor: a second independently mutable
cursor is not persisted. Failed or unauthorized actions raise and do not append
an action or advance the caller's state; there is no implicit retry policy.
For valid electrical denial of a coupled action, `ContinuationElectricalDenial`
exposes its action ID and `CoupledDownlinkAttempt` with `time_advanced=False`.

Nonempty `CommonWorld.event_ids` is rejected for continuation because this
script does not implement world-event execution. The content codec still covers
that field. No queues, callbacks, controller planning, telemetry assimilation,
generic-step execution, imaging without storage, stochastic mode or external
mutable caches are supported. J2 is not yet part of `SimulationInputs`; its
standalone foundation is unchanged, not newly checkpoint-bound by this task.

## Identity and wire representation

Bundle, canonicalization and provenance versions remain **1**. Script versions
**1** and **2** are accepted; only version 2 admits `CoupledDownlinkAction`.
Version 1 retains its original semantics and canonical content; version 2 does
not promote legacy `DownlinkAction` into coupled physics. Old readers fail on
unknown version/record tags. The allowlist adds only the coupled action and its
two explicit forcing/transmitter records. Checkpoint schema stays **5**;
B2 binding/representation stay **1/1** with their existing fixed digest fixture.

`experiment_codec.py` supports only exact built-in primitive/container types,
`fractions.Fraction`, and the explicit constructor/enum allowlist in
`_experiment_types.py`. Every record has a pinned field tuple. A field addition,
removal or `init=False` change fails `check_schema_coverage`; tests also traverse
the complete current `SimulationInputs` annotation graph. Decoding calls the
actual constructors and then checks exact re-encoding. No arbitrary imports,
`repr`, object addresses, Python `hash()`, pickle or constructor bypass is used.

- Integers use exact canonical decimal strings; finite built-in floats use
  `float.hex()` strings, preserving binary64 value and signed zero. Booleans,
  integers, floats and rational values have distinct tags.
- `Fraction` uses its reduced integer numerator and positive denominator.
  It is accepted only where the underlying constructor accepts it. Immutable
  inputs preserve the exact rational value; runtime checkpoint values must also
  survive schema-5 serialization exactly, without type or precision loss.
- Text uses exact Unicode scalar content, encoded as UTF-8; no Unicode
  normalization is applied. Lone surrogates and string subclasses are rejected.
- Tuples and lists remain distinct and ordered. Dictionary keys must be exact
  strings; entries sort by Unicode code point. Mapping insertion order is not
  semantic. Enum class and member names, record class, field names, units and
  provenance are part of identity.
- Non-finite values, Decimal/numpy numerics, subclasses, unsupported records,
  unknown fields, duplicate JSON/map keys and noncanonical scalar encodings fail
  closed. Python's own integer/text/resource limits are not overridden.

For any domain and value, `content_digest(domain, value)` is SHA-256 over UTF-8
JSON of `{"domain": domain, "canonical_version": 1, "content": canonical_content(value)}`.
JSON uses sorted keys, compact separators, `ensure_ascii=False`, `allow_nan=False`.

| Digest | Domain | Covered content |
| --- | --- | --- |
| `input_digest` | `v5-experiment-input-v1` | Tuple `(SimulationInputs, ContinuationProgram, "deterministic-no-rng")` |
| `runtime_digest` | `v5-continuation-state-v1` | Object with `input_digest`, the entire `checkpoint` section and canonical `memory` section |
| provenance `compatibility_digest` | `v5-code-environment-v1` | Object with `sources` (relative source path to raw-byte SHA-256) and `environment` |
| `bundle_digest` | `v5-experiment-bundle-v1` | Every top-level bundle field except `bundle_digest` itself |

The checkpoint section has exactly `input_digest` and `schema5`. Its latter
value is the unchanged core `CheckpointState.to_dict()` wire format. Memory is
typed canonical content. All top-level sections are required, including explicit
randomness and provenance. Each digest excludes itself; the outer digest binds
the inner digest values. Advancing time changes runtime identity, not immutable
input identity. Paths, wall-clock timestamps and Git provenance do not enter
physical/input identity.

## Public boundaries and validation

- `experiment_bundle.py:experiment_input_digest(inputs, program)` computes the
  immutable content identity. It validates input/record constructors, but is
  not by itself a physical authorization or continuation-feasibility check.
- `continuation.py:ContinuationState(context, program, memory)` validates a
  completed supported boundary. `validate_continuation` checks the nested graph,
  full-step timeline, horizon, executed prefix, clock and diagnostics, prior
  acquisition and exact custody/progress/delivery consistency.
- `experiment_bundle.py:create_bundle(state, repository_root=...)` captures
  a completed boundary and actual implementation/environment provenance.
- `ExperimentBundle.from_json(text)` and `.to_json()` strictly parse/revalidate
  or serialize. The immutable authority is canonical JSON text, not aliased
  caller dictionaries. Parsing performs semantic validation but does not claim
  compatibility with the currently executing implementation.
- `ExperimentBundle.restore(repository_root=..., expected_inputs=None,
  expected_program=None)` additionally enforces code/environment compatibility,
  compares any supplied canonical inputs/program before invoking legacy restore,
  and returns a fresh `ContinuationState` built with validated constructors.
- `continuation.py:advance_continuation(state)` validates, clones the checkpoint
  and immutable inputs, invokes the actual existing engine, and returns a fresh
  validated completed boundary. Failure, including late validation failure,
  leaves caller context and memory untouched.

The data-ledger check derives expected custody and transmission progress from
the executed prefix using existing acquisition and downlink arithmetic. This is
temporary validation evidence, not a second persistent authority. The last
executed imaging action independently determines the expected external prior
acquisition. Dropping it would change the actual ADCS feasibility of the next
image; it is neither optional nor regenerated from an empty placeholder.

Legacy `CheckpointState.restore(inputs)` retains its documented ID-based
non-orbit contract, including acceptance of some same-ID hardware changes.
B2 supplies its existing bounded orbit/numerics/world content binding, not full
hardware identity. These entry points are unchanged. Only the new bundle
boundary provides full content checks. Core schema-5 parsing/restore and Task 01
chronology validation continue to execute inside that boundary.

Semantic checks are not a replay attestation of the entire physical history.
A valid changed physical state that obeys the contract is a different declared
runtime state if all digests are recomputed. A plain digest does not authenticate
against deliberate replacement of both content and checksum; no signing or
security framework is added.

## Code/environment compatibility policy

Capture requires the actual repository owning the executing V5 module. It hashes
raw Python source bytes recursively under `ops_sim/v5` and `examples`, plus
`ops_sim/__init__.py` and `requirements.txt` when present. Dirty and untracked
source bytes are included. Recorded Git fields are HEAD, whole-worktree dirty
status and each source's clean/modified/untracked status. HEAD alone never
stands for dirty code. No provenance timestamp or absolute path is persisted.

Tracked/modified classification reads `git ls-files -z` and
`git diff HEAD --name-only -z` as bytes, splits only on NUL, then decodes UTF-8
strictly. It preserves pathname whitespace/newlines and Unicode independently
of `core.quotePath`; no Git setting is changed by capture. Empty lists and the
terminal NUL are handled explicitly. Non-UTF-8 byte filenames remain unsupported
by this Unicode-content contract, and existing relative-path validation remains
unchanged.

Restore requires exact equality of the source-content/environment digest.
Environment includes the Python build/version string, implementation, OS family,
machine, byte order and all installed distribution names/versions. Distribution
names normalize `-`, `_`, `.` runs to `-` and lowercase. This is deliberately
conservative, not a scientific-equivalence claim across versions/platforms.
Git HEAD and dirty metadata are evidence, not compatibility keys: a documentation
commit with identical executing source bytes and environment can remain
compatible. Dependencies are identified by reported distribution versions, not
attested native binary hashes. This boundary assumes ordinary unmodified Python
imports; it is not authentication of monkeypatched or externally tampered code.

## Executable restart demonstration and checks

`examples/v5_experiment_bundle_demo.py` reuses explicit synthetic V5.4 fixture
hardware; no spacecraft calibration claim is made. It executes:

`image-a -> partial-a -> image-b -> complete-a -> partial-b -> complete-b`.

Two 12000-bit acquisitions use 23-second steps and declared contacts providing
9000 bits nominal capacity each. The final clock is 238 s, diagnostics count 6,
delivered content 24000 bits, storage empty and no partial transfers remain.
Ground knowledge is nonempty. Full checkpoint, input digest, external memory,
actual successful script choices and metrics are emitted as JSON.

Using the existing environment, with all output paths outside the repository:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m examples.v5_experiment_bundle_demo --output C:\TEMP\direct.json
.\.venv\Scripts\python.exe -B -m examples.v5_experiment_bundle_demo --stop-after 2 --bundle-output C:\TEMP\partial-bundle.json --output C:\TEMP\partial.json
.\.venv\Scripts\python.exe -B -m examples.v5_experiment_bundle_demo --resume C:\TEMP\partial-bundle.json --output C:\TEMP\resumed.json
```

The caller must supply an existing writable output directory. The script creates
only the explicitly named files. New tests cover literal canonical fixtures,
same-ID input changes, malformed/rehashed inconsistencies, late-failure
atomicity, graph coverage and fresh-process JSON-only continuation at action
boundaries 1, 2, 3 and 5. Restart comparisons use exact equality of the complete
checkpoint, memory, action choices and metrics under the same compatibility
policy. No numerical tolerance conceals changed events or missing memory.

The legacy downlink path and this Task 02 demonstration still advance time and
delivery bookkeeping without concurrent EPS/thermal/degradation evolution.
Tests preserve that meaning. The separate Task 03A path, contracts, numerical
reference and version-2 restart demonstration are documented in
V5_COUPLED_DOWNLINK.md. Both demonstrations remain ordered harnesses, not mission
controllers. Strict implementation provenance is unchanged for both versions.

## Task 03B operational program extension

The same bundle envelope additionally accepts the distinct `OperationalProgram`
version 3 and `OperationalMemory` pair. `ContinuationProgram` versions 1 and 2
are not reinterpreted and still reject version 3. The new program requires an
explicit sampled protection policy, thermal-role dependencies, essential standby
demand/allocation assumptions, every mission/fallback forcing input and an
immutable initial checkpoint. All enter the experiment input digest.

Each typed outcome consumes one request interval, including denial plus physical
standby. Outcome history distinguishes requested and actual action; only a
successful acquisition advances previous-acquisition memory. Current truth stays
in schema 5. Bounded deterministic replay from the immutable initial condition
checks all outcome evidence and the complete runtime checkpoint on restore.
Thus the earlier paragraph about accepting a newly declared valid runtime state
after recomputing digests applies to versions 1/2; version 3 additionally requires
agreement with its declared initial condition and request history. No digest
authenticates deliberate replacement of an entire experiment.

Bundle/canonical/provenance versions remain 1 and strict code/environment and
UTF-8 Git-path compatibility checks are unchanged. See
V5_OPERATIONAL_PROTECTION.md for public protected entry points, policy ownership,
survival observations, numerical limits and the executable version-3 example.

## Task 04A explicit action-time program extension

The unchanged version-1 envelope additionally accepts `SubsteppedProgram`
version 4, `SubsteppedMemory` and `SubsteppedState`. Explicit integer physical
intervals and a dyadic internal integration policy are separate, content-bound
inputs. Versions 1/2/3 retain their historical execution contracts.

Version 4 records actual sampled outcomes, aggregate energy/work and prior
successful acquisition memory. Bounded deterministic replay checks the whole
schema-5 completed checkpoint and memory at action boundaries. No mid-action
checkpoint is supported. Refinement changes the experiment input digest;
same-policy restart remains exact. The demonstration's separate physical-
scenario comparison digest is not a continuation identity. Strict source,
environment and schema validation remains unchanged. See
V5_SUBSTEPPED_EXECUTION.md for the constant-forcing contract, fractional APIs,
protection semantics, numerical references and deferred qualification.

## Task 04B exact-time contact program extension

The version-1 envelope additionally accepts ContactProgram version 5,
ContactMemory and ContactState. Explicit ordered contact plans, ON/OFF forcing,
integration policy and rational service-time semantics are content-bound.
Versions 1-4 retain their historical meanings. Schema 5 and B2 remain unchanged.

Memory owns actual per-record/segment outcomes, exact and conservative completion
timing, prior acquisition and typed ConsumedContacts. Completed-contact replay
validates all memory and the complete checkpoint. A consumed contact cannot be
reused after JSON restore. Mid-contact restart is unsupported. Original
completing-contact identities remain in schema 5; version-5 outcomes carry
finer completion times. See V5_CONTACT_EXECUTION.md for ownership, bounded
integer-bit/rate admission, shared physics and qualification limits.
