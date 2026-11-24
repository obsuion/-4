"""M1-A independent rational/hand references and bounded 05E compatibility.

Predeclared tolerances: see M1_ASSEMBLY.md. No campaign execution here.
"""

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction as F
import json
import math
from pathlib import Path

import pytest

from ops_sim.v5.assembly import (
    ComponentPlacement, IDENTITY, LEGACY_BODY_FRAME,
    ROTATION_RESIDUAL_LIMIT, SpacecraftAssembly, UNIFORM_CUBOID, UniformCuboid,
    UnsupportedLegacyInertiaScale, assembly_from_05e, calculate_mass_properties,
    convert_05e_allocation,
)
from ops_sim.v5.design_trade_design import DesignAssumptions, derive_design


ANALYTIC_ABS = 2e-14
REL = 2e-14
COMPAT_MASS_ABS_KG = 2e-12
COMPAT_COM_ABS_M = 2e-14
COMPAT_INERTIA_ABS_KG_M2 = 2e-12
RZ90 = ((0, -1, 0), (1, 0, 0), (0, 0, 1))
RZ_OBLIQUE = ((.6, -.8, 0), (.8, .6, 0), (0, 0, 1))


def definition(*, mass=12, size=(2, 4, 6), center=(0, 0, 0), key="box"):
    return UniformCuboid(key, key + "/LOCAL", mass, size, center, UNIFORM_CUBOID)


def placement(key="one", *, mass=12, size=(2, 4, 6), center=(0, 0, 0),
              rotation=IDENTITY, local_center=(0, 0, 0)):
    return ComponentPlacement(key, definition(mass=mass, size=size, center=local_center,
                                               key="definition/" + key),
                              "BODY", center, rotation)


def evaluate(*components):
    return calculate_mass_properties(SpacecraftAssembly("BODY", components))


def near(value, absolute=ANALYTIC_ABS):
    return pytest.approx(value, rel=REL, abs=absolute)


def assert_tensor(actual, expected):
    for row, reference in zip(actual, expected, strict=True):
        assert row == near(tuple(float(x) for x in reference))
    assert all(actual[i][j] == actual[j][i] for i in range(3) for j in range(3))


def rational_raw_moment_oracle(components):
    """Independent integration of second moments about the original datum.

    For each uniform local coordinate, E[u]=0, E[u^2]=length^2/12.
    Integrate body-coordinate products, then remove M*c*c^T and form inertia
    from the central second moment. No production mass/tensor helper is used.
    Binary64 inputs are converted exactly to rational numbers.
    """
    total = sum(F(c.definition.mass_kg) for c in components)
    first = [sum(F(c.definition.mass_kg) * F(c.center_body_m[i]) for c in components)
             for i in range(3)]
    center = [x / total for x in first]
    moments = [[sum(F(c.definition.mass_kg) * (
        F(c.center_body_m[i]) * F(c.center_body_m[j]) + sum(
            F(c.rotation_body_from_local[i][k]) * F(c.rotation_body_from_local[j][k])
            * F(c.definition.size_m[k])**2 / 12 for k in range(3)))
        for c in components) - total * center[i] * center[j]
        for j in range(3)] for i in range(3)]
    trace = sum(moments[i][i] for i in range(3))
    tensor = [[(trace if i == j else 0) - moments[i][j]
               for j in range(3)] for i in range(3)]
    return total, center, tensor


def test_single_cuboid_exact_and_local_reference_is_not_a_second_shift():
    p = placement(center=(3, 2, 1), local_center=(7, -5, 4))
    result = evaluate(p)
    assert result.total_mass_kg == 12
    assert result.center_body_m == (3, 2, 1)
    assert result.inertia_com_body_kg_m2 == ((52, 0, 0), (0, 40, 0), (0, 0, 20))
    renamed_origin = replace(p, definition=replace(p.definition, center_local_m=(-8, 2, 0)))
    assert evaluate(renamed_origin) == result


def test_rotated_asymmetric_box_signed_permutation_exact():
    result = evaluate(placement(rotation=RZ90))
    assert result.inertia_com_body_kg_m2 == ((40, 0, 0), (0, 52, 0), (0, 0, 20))


def test_oblique_asymmetric_cuboid_has_signed_off_diagonal_terms():
    result = evaluate(placement(rotation=RZ_OBLIQUE, local_center=(3, 7, 2)))
    # Rational 3-4-5 rotation of diag(52,40,20): xy=(52-40)*12/25.
    assert_tensor(result.inertia_com_body_kg_m2,
                  ((F(1108, 25), F(144, 25), 0),
                   (F(144, 25), F(1192, 25), 0), (0, 0, 20)))


def test_symmetric_points_parallel_axis_off_diagonal_sign_and_translation():
    components = (placement("a", mass=1, size=(0, 0, 0), center=(1, 2, 0)),
                  placement("b", mass=1, size=(0, 0, 0), center=(-1, -2, 0)))
    result = evaluate(*components)
    assert result.total_mass_kg == 2
    assert result.center_body_m == (0, 0, 0)
    assert result.inertia_com_body_kg_m2 == ((8, -4, 0), (-4, 2, 0), (0, 0, 10))
    shift = (7, 5, -3)
    shifted = evaluate(*(replace(c, center_body_m=tuple(c.center_body_m[i] + shift[i]
                                  for i in range(3))) for c in components))
    assert shifted.center_body_m == shift
    assert shifted.inertia_com_body_kg_m2 == result.inertia_com_body_kg_m2


def test_asymmetric_mass_center_is_not_the_body_datum():
    result = evaluate(placement("a", mass=1, size=(0, 0, 0)),
                      placement("b", mass=3, size=(0, 0, 0), center=(4, 0, 0)))
    assert result.total_mass_kg == 4
    assert result.center_body_m == (3, 0, 0)
    assert result.inertia_com_body_kg_m2 == ((0, 0, 0), (0, 12, 0), (0, 0, 12))


def test_rational_integration_oracle_for_mixed_oriented_and_degenerate_bodies():
    components = (placement("a", mass=3, size=(2, 3, 4), center=(1, -2, 3),
                            rotation=RZ_OBLIQUE),
                  placement("b", mass=7, size=(1, 0, 2), center=(-2, 3, 1),
                            rotation=((0, 0, 1), (1, 0, 0), (0, 1, 0))),
                  placement("c", mass=1, size=(0, 0, 0), center=(4, 1, -3)))
    result = evaluate(*components)
    mass, center, tensor = rational_raw_moment_oracle(components)
    assert result.total_mass_kg == float(mass)
    assert result.center_body_m == near(tuple(float(x) for x in center))
    assert_tensor(result.inertia_com_body_kg_m2, tensor)


def test_common_rotation_covariance_and_nonbinary_translation():
    components = (placement("a", mass=3, size=(2, 3, 4), center=(1, -2, 3),
                            rotation=RZ_OBLIQUE),
                  placement("b", mass=7, size=(1, 0, 2), center=(-2, 3, 1)))
    original = evaluate(*components)
    # Proper cyclic permutation of all body coordinates (x,y,z)->(z,x,y).
    axes = (2, 0, 1)
    rotated = tuple(replace(c, center_body_m=tuple(c.center_body_m[i] for i in axes),
        rotation_body_from_local=tuple(c.rotation_body_from_local[i] for i in axes))
        for c in components)
    result = evaluate(*rotated)
    assert result.center_body_m == near(tuple(original.center_body_m[i] for i in axes))
    assert_tensor(result.inertia_com_body_kg_m2,
                  tuple(tuple(original.inertia_com_body_kg_m2[i][j] for j in axes)
                        for i in axes))
    shift = (.1, .3, -.7)
    shifted = evaluate(*(replace(c, center_body_m=tuple(c.center_body_m[i] + shift[i]
                                  for i in range(3))) for c in components))
    assert shifted.center_body_m == near(tuple(original.center_body_m[i] + shift[i]
                                               for i in range(3)))
    assert_tensor(shifted.inertia_com_body_kg_m2, original.inertia_com_body_kg_m2)


def test_component_order_and_repeatability_and_changed_placement():
    components = (placement("z", mass=1, center=(1, 2, 3)),
                  placement("a", mass=7, center=(-2, 1, 3)),
                  placement("m", mass=3, center=(-1, 2, 1)))
    original = evaluate(*components)
    assert evaluate(*reversed(components)) == original
    assert evaluate(*components) == original
    moved = evaluate(replace(components[0], center_body_m=(2, 3, 4)), *components[1:])
    assert moved.total_mass_kg == original.total_mass_kg
    assert moved.center_body_m != original.center_body_m
    assert moved.inertia_com_body_kg_m2 != original.inertia_com_body_kg_m2


@pytest.mark.parametrize("size,kind,tensor", [
    ((0, 0, 0), "point", ((0, 0, 0), (0, 0, 0), (0, 0, 0))),
    ((2, 0, 0), "line", ((0, 0, 0), (0, 4, 0), (0, 0, 4))),
    ((2, 4, 0), "plate", ((16, 0, 0), (0, 4, 0), (0, 0, 20))),
    ((2, 4, 6), "cuboid", ((52, 0, 0), (0, 40, 0), (0, 0, 20))),
])
def test_declared_zero_dimension_limits(size, kind, tensor):
    p = placement(size=size)
    assert p.definition.idealization == kind
    assert evaluate(p).inertia_com_body_kg_m2 == tensor


@pytest.mark.parametrize("rotation", [
    ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),  # reflection, Gram alone would pass
    ((1, .01, 0), (0, 1, 0), (0, 0, 1)),  # unit determinant shear
    ((2, 0, 0), (0, .5, 0), (0, 0, 1)),  # unit determinant scaling
    ((0, 0, 0), (0, 0, 0), (0, 0, 0)),
    ((math.nan, 0, 0), (0, 1, 0), (0, 0, 1)),
    ((math.inf, 0, 0), (0, 1, 0), (0, 0, 1)),
    ((1e300, 0, 0), (0, 1, 0), (0, 0, 1)),
    ((1 + ROTATION_RESIDUAL_LIMIT, 0, 0), (0, 1, 0), (0, 0, 1)),
])
def test_invalid_rotation_rejected(rotation):
    with pytest.raises(ValueError):
        placement(rotation=rotation)


def test_rotation_tolerance_is_admission_only_without_repair():
    r = ((math.nextafter(1, 2), 0, 0), (0, 1, 0), (0, 0, 1))
    admitted = placement(rotation=r)
    assert admitted.rotation_body_from_local == r
    assert admitted.rotation_body_from_local != IDENTITY


@pytest.mark.parametrize("rotation", [list(IDENTITY), ((1, 0, 0),),
    ((1, 0, 0), [0, 1, 0], (0, 0, 1)), ((True, 0, 0), (0, 1, 0), (0, 0, 1))])
def test_mutable_or_malformed_rotation_rejected(rotation):
    with pytest.raises(TypeError):
        placement(rotation=rotation)


@pytest.mark.parametrize("changes", [
    {"mass_kg": 0}, {"mass_kg": -1}, {"mass_kg": math.nan},
    {"mass_kg": math.inf}, {"mass_kg": 10**400}, {"size_m": (-1, 2, 3)},
    {"size_m": (1, math.inf, 3)}, {"center_local_m": (0, math.nan, 0)},
    {"mass_distribution": "measured_solid"}, {"definition_id": " "},
    {"local_frame_id": ""}, {"definition_id": "bad\x00id"},
    {"definition_id": "\ud800"},
])
def test_invalid_definition_values_rejected(changes):
    with pytest.raises(ValueError):
        replace(definition(), **changes)


class HostileFloat(float):
    def __eq__(self, other):
        return True


@pytest.mark.parametrize("changes", [
    {"mass_kg": True}, {"mass_kg": HostileFloat(1)}, {"mass_kg": "1"},
    {"size_m": [1, 2, 3]}, {"center_local_m": [0, 0, 0]},
    {"size_m": (1, 2)}, {"mass_distribution": None}, {"definition_id": 1},
])
def test_definition_rejects_wrong_types_and_hostile_numeric_equality(changes):
    with pytest.raises(TypeError):
        replace(definition(), **changes)


@pytest.mark.parametrize("changes,exception", [
    ({"component_id": ""}, ValueError), ({"component_id": 1}, TypeError),
    ({"body_frame_id": ""}, ValueError),
    ({"center_body_m": (0, 0, math.inf)}, ValueError),
    ({"center_body_m": [0, 0, 0]}, TypeError),
    ({"definition": None}, TypeError),
])
def test_invalid_placement(changes, exception):
    with pytest.raises(exception):
        replace(placement(), **changes)


def test_duplicate_instances_and_inconsistent_definition_identity_rejected():
    p = placement()
    with pytest.raises(ValueError, match="unique"):
        evaluate(p, p)
    changed_definition = replace(p.definition, mass_kg=8)
    with pytest.raises(ValueError, match="definition ID"):
        evaluate(p, replace(p, component_id="two", definition=changed_definition))
    # Reuse of identical catalog data is allowed for distinct physical instances.
    assert evaluate(p, replace(p, component_id="two")).total_mass_kg == 24


def test_invalid_assembly_and_frame_mismatch():
    for bad in ([], (), [placement()], (None,)):
        with pytest.raises(TypeError):
            SpacecraftAssembly("BODY", bad)
    with pytest.raises(ValueError, match="body frame"):
        SpacecraftAssembly("OTHER", (placement(),))
    with pytest.raises(TypeError):
        calculate_mass_properties((placement(),))


def test_all_records_and_nested_values_immutable_and_hashable():
    assembly = SpacecraftAssembly("BODY", (placement(),))
    p = assembly.components[0]
    result = calculate_mass_properties(assembly)
    for item, field, value in ((assembly, "body_frame_id", "OTHER"),
                               (p, "component_id", "other"),
                               (p.definition, "mass_kg", 10),
                               (result, "total_mass_kg", 10)):
        with pytest.raises(FrozenInstanceError):
            setattr(item, field, value)
        assert isinstance(hash(item), int)
    for nested in (assembly.components, p.center_body_m, p.rotation_body_from_local,
                   p.rotation_body_from_local[0], p.definition.size_m,
                   p.definition.center_local_m, result.center_body_m,
                   result.inertia_com_body_kg_m2, result.inertia_com_body_kg_m2[0]):
        with pytest.raises(TypeError):
            nested[0] = 0


def test_calculation_revalidates_tampered_nested_records():
    assembly = SpacecraftAssembly("BODY", (placement(),))
    object.__setattr__(assembly.components[0].definition, "mass_kg", math.nan)
    with pytest.raises(ValueError, match="finite"):
        calculate_mass_properties(assembly)
    assembly = SpacecraftAssembly("BODY", (placement(),))
    object.__setattr__(assembly.components[0], "rotation_body_from_local",
                       ((-1, 0, 0), (0, 1, 0), (0, 0, 1)))
    with pytest.raises(ValueError, match="proper"):
        calculate_mass_properties(assembly)


@pytest.mark.parametrize("components", [
    (placement(size=(1e200, 1, 1)),),
    (placement("a", mass=1e308), placement("b", mass=1e308)),
    (placement(mass=1e308, center=(1e308, 0, 0)),),
])
def test_unrepresentable_derived_arithmetic_fails(components):
    with pytest.raises(ValueError):
        evaluate(*components)


# Portable archived values: includes COM and rejection reasons from protocol.json.
# Provenance and original SHA-256 identities are stored alongside the 12 rows.
NOMINAL_05E = json.loads((Path(__file__).parent / "fixtures" /
                         "assembly_05e_nominal.json").read_text(encoding="utf-8"))["allocations"]


def test_archived_fixture_covers_exactly_all_twelve_allocations():
    assert len(NOMINAL_05E) == 12
    assert {(r["packs"], r["arrays"]) for r in NOMINAL_05E} == {
        (packs, arrays) for packs in (2, 4, 6, 8) for arrays in (2, 4, 6)}
    assert max(r["total_mass_kg"] for r in NOMINAL_05E) == 81.8971904
    assert max(r["component_count"] for r in NOMINAL_05E) == 112


@pytest.mark.parametrize("reference", NOMINAL_05E, ids=lambda r: r["design_id"])
def test_nominal_05e_compatibility_and_complete_inventory(reference):
    packs, arrays = reference["packs"], reference["arrays"]
    legacy = derive_design(packs, arrays)
    conversion = convert_05e_allocation(packs, arrays)
    assembly = conversion.assembly
    assert assembly_from_05e(packs, arrays) == assembly
    result = calculate_mass_properties(assembly)
    assert conversion.design_id == reference["design_id"] == legacy.design_id
    assert conversion.accepted is reference["accepted"] is legacy.accepted
    assert conversion.rejection_reasons == tuple(reference["rejection_reasons"]) == legacy.rejection_reasons
    assert assembly.mass_accounting_status == "CHECKED_DECLARATIONS"
    assert assembly.mount_accounting_status == "UNSPECIFIED"
    assert result.body_frame_id == LEGACY_BODY_FRAME
    assert result.total_mass_kg == near(reference["total_mass_kg"], COMPAT_MASS_ABS_KG)
    assert result.total_mass_kg == near(legacy.total_mass_kg, COMPAT_MASS_ABS_KG)
    assert result.center_body_m == near(reference["center_of_mass_m"], COMPAT_COM_ABS_M)
    assert result.center_body_m == near(legacy.center_of_mass_m, COMPAT_COM_ABS_M)
    assert result.inertia_com_body_kg_m2[1][1] == near(reference["inertia_y_kg_m2"], COMPAT_INERTIA_ABS_KG_M2)
    assert result.inertia_com_body_kg_m2[1][1] == near(
        legacy.inertia_y_kg_m2, COMPAT_INERTIA_ABS_KG_M2)
    assert len(assembly.components) == len(legacy.components) == reference["component_count"]
    for new, old in zip(assembly.components, legacy.components, strict=True):
        assert new.component_id == old.name
        assert new.definition.mass_kg == old.mass_kg
        assert new.definition.size_m == old.size_m
        assert new.center_body_m == old.center_m
        assert new.definition.center_local_m == (0, 0, 0)
        assert new.rotation_body_from_local == IDENTITY
        assert new.definition.mass_distribution == UNIFORM_CUBOID
    core = [c for c in assembly.components if c.component_id == "core_including_imager_and_actuator"]
    assert len(core) == 1 and core[0].definition.mass_kg == 70
    complete_array_parts = [c for c in assembly.components if
        c.component_id.endswith(("_deployed", "_catalog_root_parts"))]
    assert len(complete_array_parts) == 2 * arrays
    assert math.fsum(c.definition.mass_kg for c in complete_array_parts) == near(.885 * arrays)
    assert any(c.definition.idealization == "plate" for c in assembly.components) == (arrays in (2, 6))
    independent_mass, independent_center, independent_tensor = rational_raw_moment_oracle(
        assembly.components)
    assert result.total_mass_kg == near(float(independent_mass), COMPAT_MASS_ABS_KG)
    assert result.center_body_m == near(tuple(float(x) for x in independent_center),
                                        COMPAT_COM_ABS_M)
    assert_tensor(result.inertia_com_body_kg_m2, independent_tensor)


@pytest.mark.parametrize("scale", [.75, 1.25, math.nextafter(1, 2)])
def test_nonunit_core_scale_explicitly_unsupported_and_scalar_path_preserved(scale):
    assumptions = replace(DesignAssumptions(), core_inertia_scale=scale)
    legacy = derive_design(4, 4, assumptions)
    nominal = derive_design(4, 4)
    assert legacy.components == nominal.components
    assert legacy.total_mass_kg == nominal.total_mass_kg
    if scale != math.nextafter(1, 2):
        assert legacy.inertia_y_kg_m2 != nominal.inertia_y_kg_m2
    with pytest.raises(UnsupportedLegacyInertiaScale, match="core_inertia_scale == 1"):
        assembly_from_05e(4, 4, assumptions)


def test_adapter_does_not_promote_rejected_legacy_design_to_feasible():
    legacy = derive_design(8, 4)
    assert not legacy.accepted and "total_mass_ceiling" in legacy.rejection_reasons
    result = calculate_mass_properties(assembly_from_05e(8, 4))
    assert result.total_mass_kg == near(legacy.total_mass_kg, COMPAT_MASS_ABS_KG)
    assert not hasattr(result, "accepted")


def test_nonunit_scale_rejection_precedes_unrepresentable_scalar_inertia():
    # A valid finite legacy input need not produce representable scalar inertia.
    # The full-tensor adapter still diagnoses its unsupported distribution first.
    assumptions = replace(DesignAssumptions(), core_inertia_scale=1e308)
    with pytest.raises(UnsupportedLegacyInertiaScale):
        assembly_from_05e(4, 4, assumptions)


def test_adapter_revalidates_assumptions_and_uses_legacy_count_validation():
    with pytest.raises(TypeError, match="DesignAssumptions"):
        assembly_from_05e(4, 4, {})
    assumptions = DesignAssumptions()
    object.__setattr__(assumptions, "core_inertia_scale", HostileFloat(1))
    with pytest.raises(ValueError, match="core_inertia_scale"):
        assembly_from_05e(4, 4, assumptions)
    with pytest.raises(ValueError, match="pack count"):
        assembly_from_05e(3, 4)


def test_example_reports_all_four_without_a_campaign(capsys):
    from examples.v5_assembly_demo import main
    main()
    rows = json.loads(capsys.readouterr().out)
    assert [r["design_id"] for r in rows] == ["B2-A2", "B8-A2", "B2-A4", "B4-A4"]
    for row in rows:
        assert row["legacy_y_projection_kg_m2"] == row["inertia_about_com_body_kg_m2"][1][1]
        assert row["legacy_y_projection_kg_m2"] == near(row["legacy_scalar_y_kg_m2"],
                                                       COMPAT_INERTIA_ABS_KG_M2)
