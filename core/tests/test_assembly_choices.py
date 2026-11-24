"""Finite authority, declared installation geometry, and independent small cases."""

from dataclasses import FrozenInstanceError, replace
from math import inf, nan, nextafter

import pytest

from examples.m1_assembly_choices_demo import synthetic_design, unauthorized_pose_example
from ops_sim.v5.assembly import MassCoverage, assembly_from_05e, calculate_mass_properties
from ops_sim.v5.assembly_choices import (
    AssemblyDesign, InstallationBox, InstallationRegion, PhysicalInstance,
    Selection, assess_design, verify_resolved_assembly,
)


UNIT = InstallationBox((0, 0, 0), (1, 1, 1))


def geometry(a=UNIT, b=InstallationBox((3, 0, 0), (4, 1, 1)), *, clearance=0,
             exclusive=(True, True), allowed=None, reserved=()):
    base = synthetic_design()
    active = {s.choice_id for s in base.selections}
    choices = tuple(c for c in base.choices if c.choice_id in active)
    choices = tuple(replace(c, envelope=box, allowed_region_id="bay" if box is not None else None,
                            exclusive=ex) for c, box, ex in zip(choices, (a, b), exclusive, strict=True))
    allowed = InstallationBox((-10, -10, -10), (10, 10, 10)) if allowed is None else allowed
    return replace(base, choices=choices, clearance_m=clearance,
                   allowed_regions=(InstallationRegion("bay", allowed),), reserved_regions=reserved)


def codes(design):
    return [v.code for v in assess_design(design).violations]


def test_two_admissible_placements_have_hand_solved_mass_and_inertia_difference():
    results = []
    for case, iyy in (("compact", 7/3), ("spread", 25/3)):
        design = synthetic_design(case)
        assessment = assess_design(design)
        assert assessment.qualified and assessment.declared_constraints_satisfied
        result = calculate_mass_properties(assessment.assembly)
        assert result.total_mass_kg == 2
        assert result.center_body_m == (0, 0, 0)
        for actual, expected in zip(result.inertia_com_body_kg_m2,
                                    ((1/3, 0, 0), (0, iyy, 0), (0, 0, iyy)), strict=True):
            assert actual == pytest.approx(expected, abs=2e-14, rel=2e-14)
        verify_resolved_assembly(design, assessment.assembly)
        results.append(result)
    assert results[1].inertia_com_body_kg_m2[1][1] - results[0].inertia_com_body_kg_m2[1][1] == pytest.approx(6, abs=2e-14, rel=2e-14)
    assert synthetic_design("compact").instances == synthetic_design("spread").instances


def test_unauthorized_but_internally_valid_m1a_pose_rejects():
    assert unauthorized_pose_example()["rejected"]


@pytest.mark.parametrize("lower,upper,conflict", [
    ((1, 0, 0), (2, 1, 1), False),  # face contact
    ((1, 1, 0), (2, 2, 1), False),  # edge contact
    ((1, 1, 1), (2, 2, 2), False),  # corner contact
    ((nextafter(1, 0), 0, 0), (2, 1, 1), True),
    ((nextafter(1, inf), 0, 0), (2, 1, 1), False),
    ((.5, .5, .5), (1.5, 1.5, 1.5), True),
])
def test_zero_clearance_contact_semantics(lower, upper, conflict):
    result = assess_design(geometry(b=InstallationBox(lower, upper)))
    assert ("EXCLUSIVE_ENVELOPE_CONFLICT" in [v.code for v in result.violations]) is conflict
    assert result.qualified is (not conflict)


@pytest.mark.parametrize("start,conflict", [
    (1.25, False), (nextafter(1.25, 0), True), (nextafter(1.25, inf), False), (1, True),
])
def test_positive_clearance_exact_gap_and_adjacent_binary64(start, conflict):
    design = geometry(b=InstallationBox((start, 0, 0), (2.5, 1, 1)), clearance=.25)
    assert ("EXCLUSIVE_ENVELOPE_CONFLICT" in codes(design)) is conflict


def test_axis_aligned_clearance_is_not_silently_euclidean():
    # Diagonal Euclidean gap sqrt(.2^2+.2^2) > .25, but each axis gap < .25.
    design = geometry(b=InstallationBox((1.2, 1.2, 0), (2, 2, 1)), clearance=.25)
    assert "EXCLUSIVE_ENVELOPE_CONFLICT" in codes(design)


@pytest.mark.parametrize("clearance,lower,upper,conflict", [
    (0, (0, 0, 0), (1, 1, 1), False),
    (.25, (.25, .25, .25), (.75, .75, .75), False),
    (.25, (nextafter(.25, 0), .25, .25), (.75, .75, .75), True),
    (.25, (.25, .25, .25), (nextafter(.75, 1), .75, .75), True),
])
def test_containment_boundary_and_explicit_inset(clearance, lower, upper, conflict):
    design = geometry(a=InstallationBox(lower, upper), b=None, clearance=clearance, allowed=UNIT)
    assert ("OUTSIDE_ALLOWED_REGION" in codes(design)) is conflict


@pytest.mark.parametrize("gap,clearance,conflict", [(0, 0, False), (0, .25, True), (.25, .25, False)])
def test_reserved_region_boundary_rules(gap, clearance, conflict):
    reserved = InstallationRegion("reserved", InstallationBox((1+gap, 0, 0), (2+gap, 1, 1)))
    design = geometry(b=None, clearance=clearance, reserved=(reserved,))
    assert ("RESERVED_REGION_CONFLICT" in codes(design)) is conflict


@pytest.mark.parametrize("exclusive,conflict", [
    ((True, True), True), ((True, False), True), ((False, True), True), ((False, False), False),
])
def test_one_exclusive_claim_is_enough_to_forbid_pair_overlap(exclusive, conflict):
    assert ("EXCLUSIVE_ENVELOPE_CONFLICT" in codes(geometry(b=UNIT, exclusive=exclusive))) is conflict


def test_all_independent_geometry_slot_and_mass_violations_reported():
    reserved = (InstallationRegion("reserved-1", InstallationBox((.25, .25, .25), (.5, .5, .5))),
                InstallationRegion("reserved-2", InstallationBox((.5, .5, .5), (.75, .75, .75))))
    design = geometry(b=UNIT, allowed=InstallationBox((0, 0, 0), (.5, .5, .5)), reserved=reserved)
    design = replace(design,
        choices=tuple(replace(c, pose=replace(c.pose, occupied_slots=("shared",))) for c in design.choices),
        instances=(replace(design.instances[0], mass_coverage=MassCoverage((("aggregate",),))),
                   replace(design.instances[1], mass_coverage=MassCoverage((("aggregate", "child"),)))))
    result = assess_design(design)
    assert len(result.violations) == 9
    assert codes(design) == ["EXCLUSIVE_ENVELOPE_CONFLICT", "EXCLUSIVE_SLOT_CONFLICT", "MASS_COVERAGE_OVERLAP",
                            "OUTSIDE_ALLOWED_REGION", "OUTSIDE_ALLOWED_REGION",
                            "RESERVED_REGION_CONFLICT", "RESERVED_REGION_CONFLICT",
                            "RESERVED_REGION_CONFLICT", "RESERVED_REGION_CONFLICT"]
    assert result.violations[0].component_ids == ("left", "right")
    assert result.violations[0].choice_ids == ("left-near", "right-near")
    assert result.violations[1].resource_ids == ("shared",)
    assert not result.qualified and not result.declared_constraints_satisfied
    assert result.assembly is None
    reordered = replace(design, instances=tuple(reversed(design.instances)), choices=tuple(reversed(design.choices)),
                        selections=tuple(reversed(design.selections)), reserved_regions=tuple(reversed(design.reserved_regions)))
    assert assess_design(reordered) == result


def test_geometric_rejection_does_not_invalidate_static_mass_or_promote_feasibility():
    for case, expected in (("envelope-conflict", "EXCLUSIVE_ENVELOPE_CONFLICT"),
                           ("reserved-conflict", "RESERVED_REGION_CONFLICT")):
        result = assess_design(synthetic_design(case))
        assert [v.code for v in result.violations] == [expected]
        assert not result.qualified
        assert calculate_mass_properties(result.assembly).total_mass_kg == 2


def test_missing_geometry_and_mass_declarations_never_promote_qualification():
    partial = assess_design(geometry(b=None))
    assert partial.installation_status == "PARTIAL" and not partial.qualified
    assert partial.declared_constraints_satisfied
    unspecified_design = geometry(a=None, b=None)
    unspecified_design = replace(unspecified_design, allowed_regions=(),
                                instances=tuple(replace(i, mass_coverage=None) for i in unspecified_design.instances))
    unspecified = assess_design(unspecified_design)
    assert unspecified.installation_status == unspecified.mass_accounting_status == "UNSPECIFIED"
    assert not unspecified.qualified and unspecified.declared_constraints_satisfied
    assert calculate_mass_properties(unspecified.assembly).total_mass_kg == 2
    full_geometry_missing_mass = replace(geometry(), instances=(
        replace(geometry().instances[0], mass_coverage=None), geometry().instances[1]))
    assert assess_design(full_geometry_missing_mass).mass_accounting_status == "PARTIAL"
    assert not assess_design(full_geometry_missing_mass).qualified
    # Legacy rejected 05E allocation remains statically computable without envelopes.
    legacy = assembly_from_05e(8, 6)
    assert calculate_mass_properties(legacy).total_mass_kg == pytest.approx(81.8971904, rel=2e-14, abs=2e-12)
    assert not hasattr(legacy, "installation_qualified")


@pytest.mark.parametrize("bounds", [((0, 0, 0), (0, 1, 1)), ((1, 0, 0), (0, 1, 1)),
                                   ((nan, 0, 0), (1, 1, 1)), ((0, 0, 0), (inf, 1, 1))])
def test_malformed_installation_boxes_reject(bounds):
    with pytest.raises(ValueError):
        InstallationBox(*bounds)


@pytest.mark.parametrize("clearance", [-.1, inf, nan, True])
def test_invalid_clearance(clearance):
    with pytest.raises((TypeError, ValueError)):
        replace(synthetic_design(), clearance_m=clearance)


def test_choice_authority_and_reference_integrity():
    base = synthetic_design()
    with pytest.raises(ValueError, match="unknown selected choice"):
        replace(base, selections=(Selection("left", "not-authorized"), base.selections[1]))
    with pytest.raises(ValueError, match="incompatible choice"):
        replace(base, selections=(Selection("left", "right-near"), base.selections[1]))
    with pytest.raises(ValueError, match="exactly once"):
        replace(base, selections=base.selections[:1])
    with pytest.raises(ValueError, match="duplicate"):
        replace(base, definitions=base.definitions * 2)
    with pytest.raises(ValueError, match="duplicate"):
        replace(base, choices=(*base.choices, base.choices[0]))
    with pytest.raises(ValueError, match="unknown definition"):
        replace(base, instances=(replace(base.instances[0], definition_id="missing"), base.instances[1]))
    with pytest.raises(ValueError, match="unknown compatible instance"):
        replace(base, choices=(replace(base.choices[0], allowed_instance_ids=("unknown",)), *base.choices[1:]))
    with pytest.raises(ValueError, match="wrong body frame"):
        replace(base, choices=(replace(base.choices[0], pose=replace(base.choices[0].pose, body_frame_id="OTHER")), *base.choices[1:]))
    with pytest.raises(ValueError, match="unknown allowed region"):
        replace(base, allowed_regions=())
    with pytest.raises(ValueError, match="authoritative pose"):
        replace(base.choices[0], choice_id="new-label")
    with pytest.raises(TypeError):
        Selection("left", "left-near", center_body_m=(0, 0, 0))


def test_alternative_definition_cannot_masquerade_as_compatible_catalog_entry():
    base = synthetic_design()
    other = replace(base.definitions[0], definition_id="other-box", mass_kg=2)
    with pytest.raises(ValueError, match="incompatible definition"):
        replace(base, definitions=(*base.definitions, other),
                choices=(replace(base.choices[0], definition_id="other-box"), *base.choices[1:]))


def test_deep_immutability_and_tampered_nested_authority_revalidation():
    design = synthetic_design()
    for obj, field, value in ((design, "clearance_m", 0), (design.instances[0], "instance_id", "changed"),
        (design.choices[0], "exclusive", False), (design.allowed_regions[0].box, "lower_m", (0, 0, 0))):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, value)
        assert isinstance(hash(obj), int)
    with pytest.raises(TypeError):
        design.choices[0].allowed_instance_ids[0] = "changed"
    with pytest.raises(TypeError):
        design.allowed_regions[0].box.lower_m[0] = 0
    object.__setattr__(design.choices[0].pose, "rotation_body_from_local", ((-1, 0, 0), (0, 1, 0), (0, 0, 1)))
    with pytest.raises(ValueError, match="proper"):
        assess_design(design)


def test_supplied_assembly_order_and_slot_set_order_do_not_change_authorization():
    design = synthetic_design()
    design = replace(design, choices=tuple(replace(c, pose=replace(c.pose,
        occupied_slots=(c.allowed_instance_ids[0]+"-a", c.allowed_instance_ids[0]+"-b"))) for c in design.choices))
    expected = assess_design(design).assembly
    supplied = replace(expected, components=tuple(replace(c, mount_pose=replace(c.mount_pose,
        occupied_slots=tuple(reversed(c.mount_pose.occupied_slots)))) for c in reversed(expected.components)))
    verify_resolved_assembly(design, supplied)
