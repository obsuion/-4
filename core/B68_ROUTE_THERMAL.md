# B68 parts and resolved routes

This adds an explicit input/model family; legacy DesignSpecification and strict
V1/V2 wire bytes retain parts-only semantics. No old advanced store is migrated.

`spacecraft_route_thermal.RouteThermalDeclaration(line_id, thermal_node_id,
specific_heat_j_per_kg_k, provenance)` is an exact immutable input. cp is a
finite built-in float in [1e-12,1e8] J/(kg K). Exactly eight canonically sorted
declarations cover the fresh M4 routes; destinations must exist. No caller mass,
capacity, tensor, audit, compiled root or executable path is an input field.

`DesignSpecificationV2(base, route_thermal,
method='B68_DECLARED_PARTS_AND_RESOLVED_ROUTE_CAPACITY_V1')` wraps the existing
parts specification. `SpacecraftProjectV3` retains that specification and the
original common mission, source, requirements, limits and title. Its separate
closed format is `KAZEOSAT_SPACECRAFT_PROJECT_V3`, version3. The optional named
initial DATA envelope is `B68_NAMED_ROUTE_THERMAL_PROJECT_ENVELOPE_V1`; neither
document nor receipt grants remote execution or checkpoint migration.

The mass owner is fresh `compile_effective_hardware`. Exact contribution sums
are checked against every route_closure row and added_mass_exact_kg. Conductors,
slack and connectors are included; zero total mass is allowed for a covered
route. One authored effective cp covers the whole route as a lumped assumption.
Capacity destination is independent of wire-loss heat destination.

The mandatory fold is:

    Cbase[n] = existing fsum(instance mass * declared part cp)
    group mass = Fraction sum of resolved route masses by (node_id, cp.hex())
    group C = float(group mass) * cp
    Croute[n] = fsum(group C in canonical sorted group order)
    Cfinal[n] = Cbase[n] + Croute[n]

All routes at BUS and one cp exactly reproduce UserDesignSpecV1's
`base_fsum + float(total_added_mass_exact)*wirecp`. There is no tolerance or
flattened per-contribution alternative. Parts/route physical mass remain
disjoint; neither fake cuboids nor inflated body cp are used.

`constructor_compile_bound(spec)` is2 for the new exact specification and1 for
legacy. `admit_design_v2` reserves both nonrefundable ledger units before work.
The first legacy pass has a private one-unit receipt nested inside that outer
prepayment. The second pass builds the new thermal network and genuinely
recompiles construction, augmentation and effective hardware. Exact mechanical
contributions/tensor and electrical branches must remain unchanged by that
capacity-only pass. No control limits are raised.

Final capacities are bound in model.configuration, simulation configuration and
study nodes; initial temperatures/usable-energy fraction remain authored.
Static admission and environment network admission are retained. Returned
RouteThermalCompilation is output evidence, never independent input authority.
It records declaration/mass identities, exact per-line/group mass, capacities
and final assembly/construction/augmentation/root bindings.

`admit_compiled_design_v2` independently recomputes and compares the COMPLETE
canonical root. Store preview and lifecycle creation prepay the exact same
two-unit count. Fresh store reopen re-admits the stored document and recompiles
with a two-unit ledger; immutable pins then retain that admission. V3 lineage
additionally binds declaration, thermal method and model. Short dispatch rejects
V2/V3 before intent/quota/job/launch. The existing JSON editor/store import,
export and revision invalidation are used; no second editor or runner is added.

The separate B68 performance change retains the existing prepared job. It stores
one admitted policy digest, guarded by owned graph and scalar pins. Each reuse
requires the current exact role, live transaction, admitted policy/baseline alias,
exact history type, constructor validation, provenance and requested clock.
Dynamic cache keys remain complete exact histories; ACTUAL/FORECAST and limit8
remain separate. Public unprepared guard/propose retain full admission; both
paths use one unchanged validated transition law with the same work/failure and
float order. Schema seals include the property accessor, helper functions and
callers. Full boundary/callback/native generation checks and CR03 remain.

Supported domain stays rigid cuboids, at most32 entries, ideal regulated star
with one aggregate PV and seven receiving branches, one camera axis/co-oriented
PV, bounded thermal graph and existing guards. New route cp is an explicit
assumption, not a material calibration or distributed wire thermal model.
REFERENCE remains default; native is explicit and needs a genuinely matching
successor build/receipt/runtime. Linux, LONG/year/15-year, physical validation
and combined qualification are not established by this coding block.
