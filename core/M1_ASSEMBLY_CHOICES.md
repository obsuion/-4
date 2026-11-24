# M1-B: finite assembly choices and document version 1

Bounded implementation contract, written before implementation/testing.
Baseline: `59097aa4585b7b95d15801327d45b4c5df85f556`, branch
`m1-assembly-20260930-73347d98`. M1-A remains the mass/frame/coverage owner;
its code and twelve-allocation compatibility fixtures are unchanged.

## Authority and immutable input graph

`assembly_choices` defines an immutable `AssemblyDesign` with one body frame,
uniform-cuboid definitions, physical instances, finite placement choices,
exactly one selection per physical instance, allowed/reserved installation
regions, and one explicit nonnegative clearance in metres.

- `PhysicalInstance` binds instance ID to definition ID and explicit M1-A
  mass coverage (or `None`, meaning unspecified).
- `PlacementChoice` has a unique choice ID, definition ID, explicit nonempty
  set of compatible instance IDs, an M1-A `MountPose`, optional installation
  box/allowed-region reference, and an explicit exclusivity flag. Its pose
  must carry the same choice ID and correct body/local frame references.
- `Selection` contains only instance ID and choice ID. It contains no coordinates,
  rotations, or cached properties. Resolution always uses the catalog's pose.
  `verify_resolved_assembly` checks a supplied M1-A assembly against the resolved
  authoritative placements; a valid M1-A pose with an allowed-looking label
  is not sufficient. Comparisons after constructor validation are exact, with
  no pose-matching tolerance; numerical mass-property tolerances are separate.
- `InstallationBox` contains explicit lower/upper body-coordinate bounds in
  metres; all three extents are strictly positive. `InstallationRegion` gives
  such a box an ID. Boxes are independent of cuboid mass approximations and
  are never generated from the common core, component dimensions, or rotation.

IDs, tuples, built-in finite numbers and rotations reuse M1-A validators.
Duplicate records (even identical duplicates), conflicting IDs, unknown links,
missing/repeated selections, incompatible instance/definition/choice references,
wrong frames and malformed boxes are input errors (`TypeError`/`ValueError`).
All catalog choices, including unused ones, must have sound references. Unused
choices may violate installation rules when selected: catalog authorization and
installation admissibility are distinct. No search or placement generator.

## Installation rules fixed before tests

The caller is responsible for an envelope conservatively covering the physical
hardware at that choice. The validator checks the declaration, not that claim's
physical correctness. A mass COM need not be used as an envelope center.
No core collision solid, extra thickness, hidden clearance, or CAD is inferred.

Let `g >= 0` be the explicit global clearance, in m. All coordinates are
validated binary64 inputs. Compare **exact rational values of those binary64
inputs**, using `Fraction`, so subtracting nearly equal bounds does not require
an unexplained tolerance. Decimal inputs have their usual binary64 rounding
before comparison; this is not exact arithmetic over the original decimal text.

1. Containment: on every axis, `envelope.low - allowed.low >= g` and
   `allowed.high - envelope.high >= g`. Equality passes. At g=0 the envelope
   may touch the allowed-region boundary.
2. For two boxes A/B, the signed gap on axis i is
   `max(B.low[i]-A.high[i], A.low[i]-B.high[i])`. A pair is separated if at
   least one axis has gap >= g. Otherwise it conflicts. At g=0, face/edge/corner
   contact passes; only overlapping interiors conflict. At g>0, contact fails
   and a gap exactly g passes. This is an axis-aligned (L-infinity) clearance
   rule, not Euclidean surface distance; diagonal configurations can be more
   conservatively rejected than a Euclidean clearance test would require.
3. Every declared envelope checks every reserved region by that gap rule.
4. A pair of component envelopes checks that rule when **either** envelope
   claims exclusivity. Two explicitly nonexclusive envelopes may overlap,
   but containment/reserved-region rules still apply to each.
5. Exclusive slots and mass-coverage prefixes follow M1-A exactly, independent
   of geometric exclusivity. All pair conflicts are reported, without stopping
   after the first rule. Known conflicts are checked even in partial documents.

For well-formed but inadmissible selections, `assess_design` returns sorted,
deterministic `InstallationViolation` records with codes, affected component
IDs and corresponding choice IDs, plus region/slot IDs where relevant:
`OUTSIDE_ALLOWED_REGION`, `RESERVED_REGION_CONFLICT`,
`EXCLUSIVE_ENVELOPE_CONFLICT`, `EXCLUSIVE_SLOT_CONFLICT`,
`MASS_COVERAGE_OVERLAP`. Report all independently evaluable violations.
Malformed input is rejected before this assessment, rather than converted into
a feasible or partially evaluated design.

`installation_status` is `UNSPECIFIED`, `PARTIAL`, or `CHECKED_DECLARATIONS`
according to selected envelope coverage; each present envelope requires a
declared allowed region. `mass_accounting_status` has M1-A's same distinction.
`declared_constraints_satisfied` means no known violation; `qualified` additionally
requires complete geometry and mass declarations. Neither flag asserts hardware
truth. Missing declarations cannot produce qualification.

A resolved M1-A assembly is returned only when its slot/coverage rules permit
one. Geometric failure alone may still have valid static mass properties; the
assessment remains inadmissible. Legacy M1-A/05E APIs remain usable as before,
without new envelopes, retrofits, or installation qualification.

## Self-contained JSON and canonical identity

`assembly_document` supplies dumps/loads, exclusive-create save/load, and a
SHA-256 content digest. Version **1** is independent of simulation schema 5,
experiment-codec versions and frozen experiment fingerprints. No M1 class is
registered in the experiment type graph. Reuse only the accepted codec's pure
`object_fields`, `parse_json`, and `json_text` helpers; no pending 05F-B file or
schema change is needed.

Root fields are exactly `format`, `version`, `units`, `body_frame_id`,
`definitions`, `instances`, `choices`, `selections`, `allowed_regions`,
`reserved_regions`, `clearance_m`. Format is `M1_ASSEMBLY_DOCUMENT`; units are
explicitly mass kg, length m, inertia kg*m^2, rotation dimensionless; frames are
right-handed Cartesian as identified in definitions and mount poses. Version
is a built-in integer, not a boolean. No derived COM/tensor, validation outcome,
claimed digest, executable class name or external catalog reference is an input.

Numeric SI values and rotation entries are **canonical finite binary64 hex
strings** (`float.hex()`), following the existing orbit/experiment conventions.
Decoding requires exact canonical spelling and finiteness; JSON numeric literals
are not accepted for those fields. JSON booleans are used only for boolean
fields. Domain constructors normalize accepted Python int/float SI arguments
to floats. Signed zero is preserved in document identity. Exact Unicode scalar
text is retained, without normalization; surrogates and invalid IDs reject.

Canonical encoding: UTF-8, no BOM/newline, sorted object keys, compact separators,
`ensure_ascii=False`, `allow_nan=False`. Unordered records are sorted by ID;
instance/slot sets and mass paths are sorted; duplicate entries reject. Vector
axes, matrix rows/columns and ownership path segments remain ordered.
Digest is lowercase SHA-256 of
`b'M1-ASSEMBLY-DOCUMENT\\0v1\\0'` (the two escapes denote NUL bytes), followed
by the canonical JSON bytes. All authoritative records, including unused
choices/definitions and explicit policy flags, participate. Renaming IDs,
changing coverage/compatibility/clearance or any numeric bit changes identity.
This is a content identity, not a proof of universal physical equivalence,
catalog authorship, mechanical fit, or safe reuse in a simulation.

Loading permits JSON whitespace and reordered unordered records, then revalidates
the full graph. Duplicate JSON keys, nonfinite constants/numbers, wrong types,
missing/unknown fields at every level, unsupported versions, dangling references
and conflicting records reject. An optional caller-supplied expected digest
detects modification of an otherwise valid authoritative document. Without a
trusted expected digest, changing the choice catalog creates a different valid
document; a self-contained file cannot authenticate its own author.

Saving refuses to overwrite an existing path. Derived properties/outcomes are
recomputed after loading through M1-A. No checkpoint or execution-state input.

## Independent demonstration and verification

The synthetic example has two distinct 1 kg uniform cubes of side 1 m. Both
use the same catalog definition and disjoint physical coverage. Their COMs at
x=+/-1 m give Iyy=7/3 kg*m^2; at x=+/-2 m give Iyy=25/3 kg*m^2. Both masses
are 2 kg, COM is the origin, Ixx=1/3 kg*m^2, and the inertia difference is
6 kg*m^2. Explicit installation boxes and a 0.25 m clearance are separate
authored data. Include unauthorized-pose, overlapping-envelope and reserved
region rejection examples, and a fresh-process document reload.

Geometry boundary tests use exact comparisons/adjacent binary64 values; mass
tests retain M1-A's 2e-14 relative/absolute small-fixture tolerance. Test authority,
all independently evaluable conflicts, incomplete declarations, unchanged legacy
APIs, immutable nested inputs, malformed/tampered documents, canonical ordering,
meaningful digest changes and a stable canonical reference. Run only new tests
and relevant M1-A/05E tests; no campaign or full-suite packaging gate.

Out of scope: CAD, shape hierarchy, deployment trajectories, electrical/thermal
coupling, orbit/ADCS, checkpoint evolution, hardware-performance or mission
claims. Deliver an unstaged review candidate and stop for independent review.
