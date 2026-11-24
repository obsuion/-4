# M1-A-R1: immutable assembly inputs and mass properties

Review candidate; no production campaign uses this module. Baseline is detached
`08a79ef8ffaa745a8f1c3633fa22df3bc0065438` (accepted 05F-A). No pending 05F-B
file is needed. The original M0 report is supplied unchanged in the review
package, as a planning document, not independent acceptance. The author's M1-A
decisions narrow M0's proposal: no mount hierarchy, collision engine,
arbitrary intrinsic tensors, or new catalog. These are deliberate exclusions.
R1 adds the subsequently delivered mount/ownership contract and all twelve
nominal compatibility fixtures. These are bounded additions, not findings
against the original scope. The author reports external independent review of
the original archive: 126 tests, all twelve allocation comparisons, and 24
additional 3D cases against an independent 80-digit volume-quadrature oracle.
Those are external evidence, not local R1 test results or acceptance of R1.

## Inputs, outputs and frames

`ops_sim.v5.assembly` separates:

- `UniformCuboid`: immutable definition ID, local frame ID, positive mass in kg,
  dimensions in m along local x/y/z, local mass-center coordinates in m, and
  the required literal `ASSUMED_UNIFORM_CUBOID`. No charge or temperature.
- `ComponentPlacement`: unique physical instance ID, definition, body frame ID,
  COM position in m in that body frame, and a 3x3 component-to-body rotation;
  optional explicit mass coverage and mount provenance, defaulting to unspecified.
- `MountPose`: selected mount/choice IDs, body/local frame IDs, mount origin
  in body coordinates, rotation, and declared exclusive occupied slots.
- `MassCoverage`: nonempty tuple of physical ownership paths, independent
  of component display names, catalog IDs, and mounting slots.
- `SpacecraftAssembly`: body frame ID and nonempty tuple of placements.
- `calculate_mass_properties`: derives mass (kg), COM (m) relative to the
  original body datum, and a symmetric inertia tensor (kg m^2) about that COM,
  expressed along the body axes. Output is not accepted as authoritative state.

All frames are right-handed Cartesian. `R` rows are matrix rows; its columns
are local basis vectors expressed in body coordinates. `v_B = R v_C` and
`p_B = center_body + R (p_C - center_local)`. The placement is **of the COM**,
not of the local origin. Changing only the local coordinate origin does not
move the component. The assembly body origin is never silently moved to COM.
No Euler convention, orbit transform, attitude state or camera axis is inferred.

### Mount-based construction without changing direct-COM semantics

`ComponentPlacement.from_mount(component_id, definition, mount_pose,
mass_coverage=...)` explicitly identifies the definition's local frame C as
the local mount frame. `mount_pose.origin_body_m` is p_B;
`definition.center_local_m` is c_C, measured from that local mount origin;
`mount_pose.rotation_body_from_local` is R_BC. It derives **r_B = p_B + R_BC c_C**
and returns the same direct-COM placement type. No offset is applied again in
the inertia calculation. Mount provenance is retained and revalidated to
reproduce the stored direct-COM coordinates/rotation/frame exactly; it cannot
silently become stale after replacing a field. Rebuild through `from_mount`
when changing an authored mount or local COM.

For p_B=(4,5,6) m, c_C=(1,2,3) m, and rows of R_BC
`((0.6,-0.8,0),(0.8,0.6,0),(0,0,1))`, the derived COM is (3,7,9) m.
The original direct constructor with `center_body_m=(3,7,9)` still places the
COM there regardless of a nonzero local COM reference. No origin is reinterpreted.

Mount/choice IDs record the selected authored choice, not membership in an
invented catalog of mechanically qualified options. `occupied_slots` is an
explicit tuple of exclusive assembly-scoped slot IDs; intersecting claims are
rejected even for different mount/choice/component IDs. An empty tuple explicitly
claims no exclusive slots. A direct placement with `mount_pose=None` is
unspecified. `mount_accounting_status` is `UNSPECIFIED`, `PARTIAL`, or
`CHECKED_DECLARATIONS` according to how many components declare poses. Only
declared occupancy is checked: no geometric overlap, allowable-load, collision,
hierarchy or installation-fit inference. The 05E adapter leaves poses unspecified
rather than deriving mount origins from old COM boxes.

### Declared physical mass ownership

`MassCoverage.paths` consists of immutable nonempty tuples of exact text
segments. A path claims an entire physical ownership subtree: `('bus',)`
overlaps `('bus','payload')`, in either order, even if component/catalog IDs
differ. Sibling paths are disjoint; textual prefixes in individual segments
have no significance. Duplicate/ancestor/descendant claims are rejected both
within one declaration and across components. These are logical accounting
partitions, not an assembly geometry hierarchy. Repeated catalog items are
permitted when each physical instance declares different coverage paths.

`mass_coverage=None` explicitly means unspecified, not an empty checked claim.
Empty declarations are rejected. `mass_accounting_status` is `UNSPECIFIED` for
none declared, `PARTIAL` for a mixture, or `CHECKED_DECLARATIONS` when every
component declares coverage. Known overlaps are rejected even in partial mode.
Missing/false declarations are not discovered: checked accounting validates
the author's partition vocabulary, not undocumented hardware truth. Renaming a
component never changes coverage. The derived tensor has no feasibility or
accounting acceptance flag; inspect the assembly and conversion metadata.

Exact immutable tuple shapes and built-in finite int/float scalars are required;
bool and subclasses are rejected. IDs are nonblank UTF-8 strings without NUL.
Instances have distinct IDs; a reused definition ID must denote identical data.
IDs are assembly-scoped authored names, not global catalog revision identities
or content hashes. Cross-run experiment identity is outside this slice.
Every placement must name the assembly body frame. Frames are authored labels,
not independently verified geometry. Nested records are revalidated at each
assembly/calculation boundary. Frozen records prevent normal/nested mutation;
deliberate Python `object.__setattr__` tampering is not a security boundary.

Rotation admission, fixed before testing: max entry residual of `R^T R - I`
and `abs(det(R)-1)` must each be <= `64*2^-53` (about 7.11e-15).
Nonfinite values, reflections, scale/shear outside that representation tolerance
are rejected; no normalization or orthogonalization. This is binary64 admission
precision, not a physical pointing tolerance. No physical angular uncertainty is
invented. All finite authored positions/proper orientations are allowed; this
API does not certify mount compatibility or mechanical fit.

The distribution is uniform over the declared cuboid, centered at the local
COM. `idealization` explicitly reports `cuboid`, `plate`, `line` or `point`
according to the number of positive dimensions. Zero dimensions are limiting
mass distributions with specified mass; no density or missing thickness is
inferred. Local COM is not a second parallel-axis offset.

## Tensor derivation and numerical policy

From `I = integral(((r dot r) identity - outer(r,r)) dm)`, symmetry about the
local centroid eliminates first moments. For local dimensions `(a,b,c)`, the
centroidal tensor is `m/12 * diag(b^2+c^2, a^2+c^2, a^2+b^2)`. Rotation and
translation then give the defining calculation:

```
M = sum(m_i)
c = sum(m_i * center_body_i) / M
d_i = center_body_i - c
I = sum(R_i * I_local_i * transpose(R_i)
        + m_i * ((d_i dot d_i) * identity - outer(d_i, d_i)))
```

Off-diagonal entries are tensor terms `-integral(x*y dm)`, not unsigned
products of inertia. Diagonal shifts sum the other two squared coordinates
directly to avoid subtractive cancellation. Entries are summed with `math.fsum`
in stable component-ID order; the upper triangle is mirrored exactly.
Overflow/nonfinite arithmetic fails explicitly. This is ordinary binary64,
not an interval enclosure or a guarantee at arbitrary scales. Underflow and
loss of small offsets near huge coordinate origins remain floating-point limits.

Test tolerances declared before first comparison, with `abs(error) <=
max(absolute_bound, relative_bound * abs(reference))`:

| Check | Absolute bound | Relative bound |
|---|---:|---:|
| Small analytic fixtures, mass/COM/tensor | 2e-14 in the respective SI unit | 2e-14 |
| Twelve nominal 05E masses | 2e-12 kg | 2e-14 |
| Twelve nominal 05E COM coordinates | 2e-14 m | 2e-14 |
| Twelve nominal 05E Iyy projections | 2e-12 kg m^2 | 2e-14 |

Exactly representable hand cases also assert exact results. Analytic oracles
use rational second moments (including rotated off-diagonal terms), independent
of the production tensor formula. The small fixtures have coordinates <=10 m
and no ill-conditioned large-origin subtraction; ~100 unit roundoffs give
~1.11e-14 relative arithmetic allowance, rounded up to 2e-14, with an absolute
floor for cancellation. The twelve archived nominal inventories reach
**81.8971904 kg and 112 components** (B8-A6); |position|<1 m. The unchanged
2e-12 absolute budget corresponds to about 220 unit roundoffs at an 81.90 kg
or 81.90 kg m^2 scale. `fsum` avoids a naive linear accumulation error in
the longer sums. The allowance covers two reductions, centroid/offset
propagation and product ordering; COM permits ~180 roundoffs at 1 m.
These are fixed regression budgets for these fixtures, not physical accuracy
or a global forward-error theorem. No tolerance was increased for R1. The
mount example uses the same small-fixture tolerance and exact COM expectation.

## Narrow 05E adapter and accounting

`assembly_from_05e(packs, arrays, assumptions=None)` calls the unchanged
`design_trade_design.derive_design`; no second catalog or copied layout table.
It uses every component exactly once, with identity rotation and zero local
COM. The original core-centered datum is `(0,0,0)`; +Y is the legacy maneuver
axis, deployment is along +/-X and array normals are +Z
(`V5_DESIGN_TRADE_SOURCES.md:76-105`, `design_trade_design.py:187-234`).
The Y projection through assembly COM is simply tensor entry `[1][1]`.
`convert_05e_allocation` returns immutable `AllocationAssembly(design_id,
assembly, accepted, rejection_reasons)` retaining the unchanged owner's flags
and ordered reasons. `assembly_from_05e` remains a compatible static-only view.
The matrix is packs in {2,4,6,8}, arrays in {2,4,6}: all twelve allocations,
including rejected designs. A computable static tensor does not make a rejected
allocation feasible. The portable `tests/fixtures/assembly_05e_nominal.json`
copies archived mass, COM, Iyy, flags and reasons from `study/protocol.json`
(SHA-256 `b79dee06ef2b62cb2414212770e3afe8bbb94f40c137c10f6be7981fe24feed7`).
Mass, Iyy, flags and reasons also cross-check the archived `study/designs.csv`
(SHA-256 `98c7e156cafbae953026e3d8c9235bf7b1188cf76586c1c4996cca17224d9e8d`).
Tests need no external Windows path, archived campaign, or current-run output.

The aggregate core already includes payload/imager and common actuator mass.
The complete array is partitioned into wing and root parts; its internal wiring
is included there. Battery mounts, array external adapters, external harness,
insulation and regulator equivalents remain distinct inventory entries. Battery
plug/backplane is already included in regulator-equivalent mass
(`V5_DESIGN_TRADE_SOURCES.md:159`). No additional payload, actuator or complete
array is added. Core/cable boxes are mass approximations, not certified solids.
The adapter joins an explicit ownership ledger to the unchanged authoritative
inventory IDs. It does not parse display names or guess coverage from their text.
Unknown/missing inventory IDs fail closed, without fallback claims. This is
coverage metadata only; no catalog masses/dimensions are maintained twice.

All paths below begin with `('05E',...)`. Array/battery row and side, wire kind
and number, and regulator bank are text segments, each identifying an instance:

| Owner | Declared coverage after the 05E prefix |
|---|---|
| Common core | `('core',)` including payload, actuator and internal distribution |
| Battery pack / external mount | `('battery',row,side)` / `('battery_external_mount',row,side)` |
| Array catalog wing / root mass | `('array',row,side,'wing')` / `('array',row,side,'root_parts')` |
| Array external adapter | `('array_external_adapter',row,side)` |
| External string wire / insulation | `('external_string',row,side,kind,number,'conductors_and_connectors')` / same prefix + `'insulation'` |
| Regulator bank | `('regulator',bank)` including battery plug/backplane |
| Main harness / insulation | `('main_harness','conductors_and_connectors')` / `('main_harness','insulation')` |

A complete catalog array claims the parent array path and conflicts with its
wing/root children. The internal harness is already within those catalog
partitions, not a new sibling mass. An unsplit internal-harness claim must name
both possible wing/root subpaths (`...,'wing','internal_harness'` and
`...,'root_parts','internal_harness'`); no mass split/location is invented.
External string harnesses are separate declared paths. Incorrect aliases or
an invented sibling for included hardware evade the declaration's meaning,
not a hardware-truth check. The author must use the stated ownership vocabulary.

Only `core_inertia_scale == 1` is supported. A non-unit value raises
`UnsupportedLegacyInertiaScale`; no clamp or guessed 3-D extension. The scale
is validated/rejected before evaluating the old scalar inertia, so even
a finite but extremely large scale receives the explicit unsupported-case error.
The existing scalar uncertainty calculation/tests remain unchanged. Later support requires
a physically specified distribution or explicitly declared tensor uncertainty.
The adapter can describe a rejected legacy allocation's mass inventory; it
does not override `derive_design.accepted` or its rejection reasons.

## Integration boundaries and reproduction

Run from the isolated worktree with the existing environment:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
& '<live-repo>\.venv\Scripts\python.exe' -B -m examples.v5_assembly_demo
& '<live-repo>\.venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider `
  --basetemp='<new external TEMP directory>' tests/test_assembly.py tests/test_assembly_inputs.py `
  tests/test_design_trade_physics.py tests/test_design_trade_design.py
```

No executor, persistence schema, fingerprint policy or electrical/thermal
owner is changed. WireSpec/derive_design still own route/mass/electrical
calculations; thermal configuration/coupling still owns capacities, links and
heat. Moving a component here does not update a cable route or thermal link.
No installation, CAD, flight-fidelity, month-qualification, 3-axis dynamics,
M0-B or full Version M claim follows. Required later decisions include
nonuniform/uncertain mass inputs and explicit mappings from assemblies to
electrical/thermal owners, persistence and dynamic attitude. None blocks this
static uniform-cuboid slice.
