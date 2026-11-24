"""Bounded R1 input additions; independent expected placements/accounting cases."""

from dataclasses import FrozenInstanceError, replace
from math import inf, nan

import pytest

from ops_sim.v5.assembly import (
    ComponentPlacement, IDENTITY, MassCoverage, MountPose,
    SpacecraftAssembly, UNIFORM_CUBOID, UniformCuboid, assembly_from_05e,
    calculate_mass_properties, convert_05e_allocation,
)


R = ((.6, -.8, 0), (.8, .6, 0), (0, 0, 1))


def box():
    return UniformCuboid("catalog-box", "LOCAL_MOUNT", 12, (2, 4, 6), (1, 2, 3), UNIFORM_CUBOID)


def mount(*, slots=("bay-A",)):
    return MountPose("mount-A", "oblique-choice", "BODY", "LOCAL_MOUNT", (4, 5, 6), R, slots)


def direct(key="component", coverage=None):
    return ComponentPlacement(key, box(), "BODY", (3, 7, 9), R, coverage)


def checked(key, *paths):
    return direct(key, MassCoverage(paths))


def assembly(*parts):
    return SpacecraftAssembly("BODY", parts)


def test_mount_origin_plus_rotated_local_offset_once_with_oblique_rotation():
    # p=(4,5,6), c=(1,2,3); R c=(-1,2,3) -> r=(3,7,9).
    mounted = ComponentPlacement.from_mount("component", box(), mount())
    assert mounted.center_body_m == (3, 7, 9)
    assert mounted.definition.center_local_m == (1, 2, 3)
    assert mounted.mount_pose.origin_body_m == (4, 5, 6)
    result = calculate_mass_properties(assembly(mounted))
    expected = calculate_mass_properties(assembly(direct()))
    assert result == expected
    # Independent box expectations: rotating diag(52,40,20) yields xy=5.76.
    for actual, row in zip(result.inertia_com_body_kg_m2,
                           ((44.32, 5.76, 0), (5.76, 47.68, 0), (0, 0, 20)), strict=True):
        assert actual == pytest.approx(row, rel=2e-14, abs=2e-14)
    assert result.center_body_m == (3, 7, 9)  # no second offset in the calculator
    assert assembly(mounted).mount_accounting_status == "CHECKED_DECLARATIONS"
    # Removing mount provenance retains the preexisting direct-COM interpretation.
    changed_local_origin = replace(direct(), definition=replace(box(), center_local_m=(9, 8, 7)))
    assert calculate_mass_properties(assembly(changed_local_origin)) == expected


def test_mount_zero_offset_and_choice_are_explicit_not_guessed():
    origin_box = replace(box(), definition_id="catalog-box-centered", center_local_m=(0, 0, 0))
    chosen = replace(mount(slots=()), choice_id="authored-free-placement")
    mounted = ComponentPlacement.from_mount("component", origin_box, chosen)
    assert mounted.center_body_m == chosen.origin_body_m
    assert mounted.mount_pose.choice_id == "authored-free-placement"
    assert mounted.mount_pose.occupied_slots == ()
    assert direct().mount_pose is None
    assert assembly(direct()).mount_accounting_status == "UNSPECIFIED"
    assert assembly(mounted, direct("other")).mount_accounting_status == "PARTIAL"


@pytest.mark.parametrize("change", [
    {"local_frame_id": "WRONG"}, {"origin_body_m": (inf, 0, 0)},
    {"rotation_body_from_local": ((-1, 0, 0), (0, 1, 0), (0, 0, 1))},
    {"choice_id": ""}, {"occupied_slots": ("bay", "bay")},
])
def test_invalid_mounts_and_local_frame_mismatch(change):
    with pytest.raises(ValueError):
        ComponentPlacement.from_mount("component", box(), replace(mount(), **change))


@pytest.mark.parametrize("change", [
    {"origin_body_m": [0, 0, 0]}, {"occupied_slots": ["bay"]},
    {"rotation_body_from_local": list(IDENTITY)}, {"mount_id": 1},
])
def test_mount_rejects_mutable_or_wrong_types(change):
    with pytest.raises(TypeError):
        replace(mount(), **change)


@pytest.mark.parametrize("change", [
    {"center_body_m": (0, 0, 0)}, {"rotation_body_from_local": IDENTITY},
    {"body_frame_id": "OTHER"}, {"definition": replace(box(), center_local_m=(0, 0, 0))},
])
def test_mount_metadata_cannot_become_stale(change):
    placed = ComponentPlacement.from_mount("component", box(), mount())
    with pytest.raises(ValueError, match="mount metadata"):
        replace(placed, **change)


def test_mount_overflow_rejected_without_clamping():
    huge = replace(box(), center_local_m=(1e308, 1e308, 1e308))
    with pytest.raises(ValueError):
        ComponentPlacement.from_mount("component", huge, replace(
            mount(), origin_body_m=(1e308, 1e308, 1e308), rotation_body_from_local=IDENTITY))


def test_declared_occupancy_conflict_and_disjoint_slots():
    a = ComponentPlacement.from_mount("one", box(), mount())
    b = ComponentPlacement.from_mount("two", box(), replace(mount(), choice_id="other-choice"))
    with pytest.raises(ValueError, match="occupancy"):
        assembly(a, b)
    b = ComponentPlacement.from_mount("two", box(), replace(
        mount(slots=("bay-B",)), mount_id="mount-B", origin_body_m=(-4, 5, 6)))
    assert assembly(a, b).mount_accounting_status == "CHECKED_DECLARATIONS"


@pytest.mark.parametrize("paths", [
    (("bus",), ("bus",)), (("bus",), ("bus", "payload")),
    (("bus", "payload"), ("bus",)), (("bus", "a"), ("bus", "a", "wire")),
])
def test_internally_overlapping_coverage_rejected(paths):
    with pytest.raises(ValueError, match="overlapping mass"):
        MassCoverage(paths)


@pytest.mark.parametrize("paths,exception", [
    ((), TypeError), ([], TypeError), (((),), TypeError), ((["bus"],), TypeError),
    ((("",),), ValueError), (((nan,),), TypeError), ((("bad\x00id",),), ValueError),
])
def test_invalid_coverage_inputs(paths, exception):
    with pytest.raises(exception):
        MassCoverage(paths)


@pytest.mark.parametrize("left,right", [
    (("bus",), ("bus",)), (("bus",), ("bus", "payload")),
    (("bus", "payload"), ("bus",)),
    (("array-1",), ("array-1", "root", "hinge")),
])
def test_different_component_ids_do_not_bypass_mass_overlap(left, right):
    # No overlap inference from component IDs or shared catalog definitions.
    with pytest.raises(ValueError, match="overlapping mass claims"):
        assembly(checked("arbitrary-A", left), checked("unrelated-display-B", right))


def test_valid_disjoint_claims_and_repeated_catalog_instances():
    # Identical definition reused by distinct physical instances, both checked.
    a, b = checked("one", ("serial-A",)), checked("two", ("serial-B",))
    assert a.definition == b.definition
    result = assembly(a, b)
    assert result.mass_accounting_status == "CHECKED_DECLARATIONS"
    assert calculate_mass_properties(result).total_mass_kg == 24
    # Siblings and segments with similar text are not prefixes of each other.
    assert assembly(checked("a", ("bus", "payload")), checked("b", ("bus", "avionics")),
                    checked("c", ("bus-other",))).mass_accounting_status == "CHECKED_DECLARATIONS"


def test_partial_versus_unspecified_never_claims_checked_accounting():
    assert assembly(direct()).mass_accounting_status == "UNSPECIFIED"
    partial = assembly(checked("a", ("bus",)), direct("b"))
    assert partial.mass_accounting_status == "PARTIAL"
    with pytest.raises(ValueError, match="overlapping mass"):
        assembly(*partial.components, checked("c", ("bus", "payload")))
    # Renaming a component leaves its declared physical coverage untouched.
    a = checked("first", ("bus",))
    with pytest.raises(ValueError, match="overlapping mass"):
        assembly(a, replace(a, component_id="renamed"))


def test_new_inputs_are_deeply_immutable_and_revalidated_at_calculation():
    coverage = MassCoverage((("serial-A", "part"),))
    pose = mount()
    placed = ComponentPlacement.from_mount("one", box(), pose, mass_coverage=coverage)
    for obj, field, value in ((coverage, "paths", ()), (pose, "choice_id", "changed")):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)
        assert isinstance(hash(obj), int)
    for nested in (coverage.paths, coverage.paths[0], pose.occupied_slots,
                   pose.origin_body_m, pose.rotation_body_from_local[0]):
        with pytest.raises(TypeError):
            nested[0] = "changed"
    prepared = assembly(placed)
    object.__setattr__(prepared.components[0].mount_pose, "origin_body_m", (0, 0, 0))
    with pytest.raises(ValueError, match="mount metadata"):
        calculate_mass_properties(prepared)
    prepared = assembly(checked("a", ("one",)), checked("b", ("two",)))
    object.__setattr__(prepared.components[1].mass_coverage, "paths", (("one",),))
    with pytest.raises(ValueError, match="overlapping mass"):
        calculate_mass_properties(prepared)


@pytest.mark.parametrize("path", [
    ("05E", "core", "payload"), ("05E", "core", "actuator"),
    ("05E", "core", "internal_distribution"),
    ("05E", "array", "0", "-1"),  # complete catalog array duplicates both parts
    ("05E", "array", "0", "-1", "root_parts", "hinge"),
    ("05E", "array", "0", "-1", "wing", "internal_harness"),
    ("05E", "regulator", "0", "battery_backplane"),
    ("05E", "external_string", "0", "-1", "0", "0"),
])
def test_05e_accounting_boundaries_reject_extra_included_hardware(path):
    legacy = assembly_from_05e(2, 2)
    extra = replace(checked("extra-unrelated-id", path), body_frame_id=legacy.body_frame_id)
    with pytest.raises(ValueError, match="overlapping mass"):
        SpacecraftAssembly(legacy.body_frame_id, (*legacy.components, extra))


def test_05e_internal_harness_is_not_a_second_unsplit_catalog_mass():
    legacy = assembly_from_05e(2, 2)
    # No mass split/location of the internal harness is invented. An unsplit
    # claim declares both possible partitions it covers; either overlaps.
    claim = MassCoverage((("05E", "array", "0", "-1", "wing", "internal_harness"),
                          ("05E", "array", "0", "-1", "root_parts", "internal_harness")))
    extra = replace(direct("internal-cable", claim), body_frame_id=legacy.body_frame_id)
    with pytest.raises(ValueError, match="overlapping mass"):
        SpacecraftAssembly(legacy.body_frame_id, (*legacy.components, extra))


def test_05e_external_components_are_disjoint_and_payload_not_added_again():
    converted = convert_05e_allocation(8, 6)
    assert not converted.accepted
    assert converted.assembly.mass_accounting_status == "CHECKED_DECLARATIONS"
    assert len(converted.assembly.components) == 112
    claims = {p for c in converted.assembly.components for p in c.mass_coverage.paths}
    assert ("05E", "core") in claims
    assert ("05E", "battery_external_mount", "0", "-1") in claims
    assert ("05E", "array_external_adapter", "0", "-1") in claims
    assert ("05E", "main_harness", "insulation") in claims
    assert calculate_mass_properties(converted.assembly).total_mass_kg == pytest.approx(
        81.8971904, rel=2e-14, abs=2e-12)
    with pytest.raises(FrozenInstanceError):
        converted.accepted = True
    with pytest.raises(TypeError):
        converted.rejection_reasons[0] = "changed"
    with pytest.raises(ValueError, match="accepted"):
        replace(converted, accepted=True)
    with pytest.raises(TypeError):
        replace(converted, rejection_reasons=list(converted.rejection_reasons))


def test_05e_coverage_ledger_fails_closed_if_inventory_owner_changes(monkeypatch):
    import ops_sim.v5.assembly as owner
    original = owner.derive_design

    def changed_inventory(*args):
        design = original(*args)
        components = (replace(design.components[0], name="new-inventory-id"), *design.components[1:])
        return replace(design, components=components)

    monkeypatch.setattr(owner, "derive_design", changed_inventory)
    with pytest.raises(ValueError, match="ownership ledger"):
        owner.convert_05e_allocation(2, 2)
