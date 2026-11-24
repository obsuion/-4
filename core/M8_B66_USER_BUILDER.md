# B66 general supported spacecraft project

This is an uncommitted engineering candidate. Twelve is a possible example
population, not an ID whitelist, component limit, or a two-axis design space.
`SpacecraftProjectV2` owns immutable inputs. Its strict V2 codec is separate
from the unchanged V1 meaning of `center_body_m`, placement presets and codec.

## Authoritative inputs and consumer

`spacecraft_design.DesignSpecification` contains the M1 `AssemblyDesign`,
M4 `ConstructionConfiguration`, B46 `HarnessAugmentationInputs`, actual camera
and effective-panel axes, actuator, battery/PV module declarations, per-instance
thermal properties, initial SOC/temperatures and `FunctionalPlant`.
The latter supplies the actual optical payload, RF demand, served-power heat
routing, seven-family baseline loads and camera half-FOV. Definitions, instance
IDs, counts, mass, dimensions, local COM offsets, authored allowed mounts,
rotations, selected poses, installation declarations and wiring are editable.
No component type or design ID is inferred from a display name.

DESIGNS owns its external compiler. CORE's `admit_design(spec, common, ledger)`
is the supported composition/engine owner. `admit_compiled_design` independently
recomputes this result and compares the complete canonical proposed root; a
cached identity or caller-approved flag is insufficient. It returns an actual
`LifecycleRoot`, M4 compilation and effective full-tensor hardware. The existing
chronological executor, ADCS, EPS, thermal, acquisition, storage and delivered
product-credit paths consume these physical inputs. Construction is not credit.

The seed adapter recognizes the archived five-instance example only to provide
an explicit ASSUMED editing starter. General input admission does not use those
IDs. Its per-instance allocation and 1000 W/m2 PV rating normalization are
ASSUMED aggregate-equivalent declarations, not measured catalogue data.
SOURCE declarations require IDs, but declaring a source is not source research
or independent verification. Common battery/ageing coefficients remain TO_VERIFY.

## Derived quantities and explicit assumptions

M1 retains mount semantics `r_B = p_B + R_BC c_C`, kilograms/metres, proper
component-to-body rotations and full body-frame COM tensor. Mass/COM/tensor
are calculated, not editable inertia inputs. Cuboid COM tensors are rotated
and shifted with `m ((d.d) 1 - d d^T)`. B46 adds separately declared excluded
wire/connector mass exactly once, retaining its exact mass-distribution work.
Declared overlap, parent/child mass coverage and installation failures refuse.

For n electrically identical parallel modules, the admitted ideal internal
bank uses sum(Wh), sum(bus power limits), n times current limits, R_module/n,
and module resistance-ageing coefficient per chemical Wh divided by n. OCV,
temperature law and damage state are common. Equal SOC/temperature, ideal
internal bus and equal sharing are declared approximations. Nonidentical
electrical modules and series/converter networks need a new model owner.

Co-oriented PV normals are independently transformed from every actual mount
and must agree exactly with the effective panel axis. Origins may differ.
Generation rating is sum(active_area * declared_rating_irradiance * efficiency)
under the existing common irradiance/incidence factor. Active area is an input,
screened against the declared cuboid envelope's orthogonal projected area
`|nx| sy sz + |ny| sx sz + |nz| sx sy`; this cap is not an inferred active area.
Different reference ratings are normalized nameplate declarations, not distinct
irradiance histories. Self-shadowing, articulated/misaligned arrays, per-panel
converters and nonideal internal interconnects are not silently collapsed.

For each declared common-temperature lump, C = sum(m_i cp_i), radiating
A = sum(A_i), epsilon = sum(A_i epsilon_i)/A. Links and boundary/heat destinations
are explicit M4 inputs. The common prescribed external solar/albedo/IR forcing
is retained; it is not automatically an area/attitude-dependent heat budget.
Added harness mass has no newly inferred heat capacity: existing wire-loss-only
thermal ownership is explicit. A new thermal node requires an explicit forcing
owner and is currently refused by this bridge rather than silently omitted.

Initial E = nameplate Wh * declared capacity retention * initial usable fraction.
This operates only on the original zero-step, empty-custody boundary. It is not
an advanced-checkpoint migration, recharge, changed threshold or erased history.
Goals use the actual recurring request population; common600 offers one request.
Constructor acceptance never promises those goals will be met in a mission.

## Bounded physical domain

- Rigid uniform cuboids and authored installation envelopes; no solid CAD,
  collision/routing solver, flexible structure or arbitrary inertia inputs.
- Existing 32-entry spatial domain; ideal regulated star, one aggregate PV
  and exactly seven served load branches; one camera and one effective PV axis.
- Existing thermal/kernel caps remain 64 nodes/256 links where supported;
  this bridge retains the supplied node/forcing set and B61's narrower limits.
- One supported optical/RF functional family with explicitly declared parameter
  changes. An additional passive physical part does not invent an active load.
  This consumer requires MULTISPECTRAL support; PAN-only equipment is refused.
  The archived demo has legacy PAN metadata despite using the MS lifecycle.
  Its editable template therefore declares MS separately as ASSUMED demo
  equipment, visible in the specification provenance; common input is unchanged.
  Heat destinations must exist; the paid ADCS storage adjustment retains its
  existing full-heat BUS routing contract.
- Full inertia is not a claim of completed arbitrary actuator/3-axis hardware
  dynamics, physical calibration, continuous visibility or a flight certificate.

## Workbench and lineage

Run from this source using the existing environment, with bytecode disabled:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'
& '<existing-python>' -B -m examples.m8_workbench `
  --project-directory '<new-external-store>' `
  --design-common tests/fixtures/b66_common_initial.json
```

The general JSON editor provides template/create/edit/apply/import/export,
schema admission and real paid preview. It does not silently apply V1 presets
to V2. Refreshing the outer content digest is not permission to alter a nested
common mission or to insert a checkpoint/output/callable. Applied revisions
invalidate stale previews and run results. The general lifecycle route preserves
the project's complete common physical/numerical policies, then uses the existing
real runner. Local create/reopen independently recomputes spec-to-root binding;
repeated pins use exact raw hashes/scalar pins, without constructor replay.

The saved project document, source/spec/common/compiled-root IDs are bound in
the lifecycle store and exports. Stop/reopen/direct resume use the same root
and immutable revision. Comparison identity includes the full common root,
requirements and source; different horizons/world/controller are not comparable.
Legacy portable initial-job envelopes are unchanged and do not yet transport
the named V2 project document: that additive companion transfer remains open.

## Platform gates

`m8_lifetime_campaign_cli.py local-capability --backend REFERENCE` reports the
explicit bounded Windows reference route. Typed capability requires an actual
matching new binary/build receipt; absent build is NOT_READY, never fallback.
Linux production and LONG remain separate. The three retained native build
attempts failed in Zig with `error: Unexpected`; compiler cause is UNKNOWN.
Raw C and token-equivalence treatment proofs are retained externally. Normalized
C alone is not a compiled binary. Historical B64/B65 binaries/receipts are
retained outside the candidate, not relabelled as successor evidence.

No browser was exposed by `cua.getState` (apps=[], browsers=[]): DOM NOT_RUN.
HTTP-handler metadata checks do not establish DOM or end-to-end GUI behavior.
Combined qualification remains UNRESOLVED; full M2/V5/M/15-year work is open.
