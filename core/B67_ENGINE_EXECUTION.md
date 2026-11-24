# B67 general-project execution candidate

This is a bounded local engine integration and performance candidate. It is
not a new physical model, hardware calibration, Linux qualification, LONG
acceptance, or completion of Version M.

`SpacecraftProjectV2` must enter `LifecycleWorkspace.create_design_project`.
The legacy short `ProjectRunner.submit`, `ProjectStore.prepare_job`, and
worker entry refuse it before creating intents, reservations, jobs, or a
scientific launch. V1 retains its separate short contract.

The optional `execution=GeneralProjectExecution(policy, build_bytes)` selects
the existing full B65 native execution domain. It binds the complete composed
LifecycleRoot, original common mission, strict current source/runtime/build,
and existing PILOT execution authority to the named project store. It does not
convert the root to its rolling base. The original public LifecycleRunner,
Stop, settled direct MAIN and diagnostic paths consume that store. Missing or
stale successor artifacts refuse execution; there is no historical binary
fallback. Store backend/source identities cannot be migrated in place.

The additive `dumps_named_project` / `loads_named_project` envelope carries
only the initial project and explicit execution DATA. It is canonical and
bounded. Receipt DATA is not a permission to launch or a checkpoint. Actual
composition equality and all existing runtime/native/authority gates still
run at store creation and worker admission. No remote launcher is introduced.

The two performance changes preserve the wire and numerical equations:

* One finite PreparedInputCodec scope covers a complete general-project
  decode and constructor-normalized roundtrip, including common input and
  explicit design declarations. Full registry and unused-owner checks remain
  at entry/exit; used constructors remain checked. No global monkeypatch or
  cached dynamic state is introduced.
* Supported port/service report folds read exact selected returned records
  directly. The existing prepared and unprepared paths share rational sums,
  binary64 operation order, selected-only traversal and delivery witnesses.
  The caller still publishes only its validated atomic report clone.

CR03 independent generation sealing and full static boundary hooks remain
mandatory. Any later seal acceleration needs its own measurements and mutation
evidence. A complete inertia tensor remains static mass data, not arbitrary
three-axis attitude dynamics.

Composition uses the unchanged B66 physics policy: thermal capacities are
the sum of explicitly declared physical instance mass times declared specific
heat. Calculated harness mass is separately added to mechanical properties;
no undocumented harness specific heat is invented or silently merged. A
DESIGNS declaration that includes harness mass times cp in BUS is a different
model policy and cannot be relabelled as this one. `admit_compiled_design`
retains complete canonical root equality. DESIGNS owns external mapping;
CAMPAIGN owns manifest import. No fixed design-ID whitelist is added.

Numerical equality, actual native use, public timings and restart outcomes
must be read from the source-bound final evidence. Until those gates finish,
speedup is UNPROVEN and native scientific readiness is UNRESOLVED. Historical
preservation failures and B66 failures are not waived by this candidate.
