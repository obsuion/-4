# User design project in the existing Workbench

Start the existing local application from this candidate source using the
existing environment. The directory must be new or an existing store bound to
this exact source; no historical store is migrated:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m examples.m8_workbench --project-directory C:\path\outside-source\my-designs --design-common C:\path\common-initial.json
```

`--design-common` is a strict canonical initial `LifecycleRoot`, not a saved
checkpoint or computed result. Its complete world, scenario, controller,
numerical policies and horizon remain the design's immutable common mission.
Without this option the UI explicitly labels its inherited 600-second legacy
ASSUMED starter. A template is editable input, not a hardware recommendation.

In **Пользовательская сборка · V2**, create a JSON template or import a saved V2
document through **Загрузить**. The JSON contains `common`, `specification`,
`source_identity`, title, requirements and limits. The specification holds the
general M1 assembly, M4 configuration and explicit electrical, thermal and
functional declarations. Supported poses and composition are not selected from
a design-ID whitelist. The currently supported bank, PV, circuit and geometry
domain is checked by the engine owner and refusals are displayed as errors.

**Проверить schema и применить новую revision** strictly decodes the input and
updates only the outer document checksum to acknowledge the user's edit. It
does not repair nested common-root checksums, add physical declarations or
convert unsupported circuits/orientations into a convenient equivalent.
Each accepted edit is a new immutable revision. Previous results and previews
retain their old revision. **Пересчитать сборку** pays the existing constructor
ledger and renders actual mounted cuboids, routes, COM, full tensor and the
declared battery/PV composition. Legacy V1 preset controls are disabled for V2.

**Зафиксировать actual lifecycle root** compiles the applied specification
using its existing common mission. It retains the canonical project document
as `design-project-input.json`, with raw hash, source identity, specification
identity, common identity, project revision and compiled-root identity bound in
the immutable store. Reopen and every dispatch pin check re-admit these input
bindings without recompilation or numerical replay. The normal chronological
mission's **Начать**, **Стоп**, **Direct resume**, diagnostic and export routes
consume that root. Creating a root does not launch a worker. Stop/reopen never
reconstruct process ownership from a PID. Result exports include the bound
design document. A store already tied to a different revision is never retagged.

This is a schema-validated numerical builder, not CAD, collision/routing
optimization, arbitrary circuit simulation or completed general three-axis
attitude dynamics. Actual mission verification and browser DOM verification
must be reported separately; metadata/API tests do not demonstrate either.
