"""Synthetic static assembly choices; no simulation or hardware claims.

python -B -m examples.m1_assembly_choices_demo --output-dir <new external dir>
python -B -m examples.m1_assembly_choices_demo --load <document> --expected-digest <sha256>
"""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path

from ops_sim.v5.assembly import (
    ComponentPlacement, IDENTITY, MassCoverage, MountPose, SpacecraftAssembly,
    UNIFORM_CUBOID, UniformCuboid, calculate_mass_properties,
)
from ops_sim.v5.assembly_choices import (
    AssemblyDesign, InstallationBox, InstallationRegion, PhysicalInstance,
    PlacementChoice, Selection, assess_design, verify_resolved_assembly,
)
from ops_sim.v5.assembly_document import (
    assembly_document_digest, load_assembly_document, save_assembly_document,
)


def synthetic_design(case: str = "compact") -> AssemblyDesign:
    definition = UniformCuboid("unit-cube", "UNIT_MOUNT", 1, (1, 1, 1), (0, 0, 0), UNIFORM_CUBOID)
    instances = tuple(PhysicalInstance(i, definition.definition_id, MassCoverage((("synthetic", i),)))
                      for i in ("left", "right"))

    def choice(key, instance, x):
        return PlacementChoice(key, definition.definition_id, (instance,),
            MountPose(instance + "-mount", key, "SYNTHETIC_BODY", "UNIT_MOUNT", (x, 0, 0),
                      IDENTITY, (instance + "-slot",)),
            InstallationBox((x-.5, -.5, -.5), (x+.5, .5, .5)), "bay", True)

    choices = (choice("left-near", "left", -1), choice("left-far", "left", -2),
               choice("right-near", "right", 1), choice("right-far", "right", 2),
               choice("left-overlap", "left", 1), choice("left-blocked", "left", 0))
    selections = {
        "compact": ("left-near", "right-near"),
        "spread": ("left-far", "right-far"),
        "envelope-conflict": ("left-overlap", "right-near"),
        "reserved-conflict": ("left-blocked", "right-far"),
    }
    if case not in selections:
        raise ValueError("unknown synthetic case")
    return AssemblyDesign("SYNTHETIC_BODY", (definition,), instances, choices,
        tuple(Selection(i, c) for i, c in zip(("left", "right"), selections[case], strict=True)),
        (InstallationRegion("bay", InstallationBox((-3, -1, -1), (3, 1, 1))),),
        (InstallationRegion("reserved-center", InstallationBox((-.25, -.5, -.5), (.25, .5, .5))),), .25)


def summary(design):
    assessment = assess_design(design)
    properties = None if assessment.assembly is None else asdict(calculate_mass_properties(assessment.assembly))
    return {"synthetic": True, "digest": assembly_document_digest(design),
            "selections": [asdict(s) for s in design.selections],
            "qualified": assessment.qualified,
            "installation_status": assessment.installation_status,
            "mass_accounting_status": assessment.mass_accounting_status,
            "violations": [asdict(v) for v in assessment.violations], "properties": properties}


def unauthorized_pose_example():
    design = synthetic_design()
    assembly = assess_design(design).assembly
    first, *rest = assembly.components
    changed_pose = replace(first.mount_pose, origin_body_m=(-1.125, 0, 0))
    masquerading = ComponentPlacement.from_mount(first.component_id, first.definition,
        changed_pose, mass_coverage=first.mass_coverage)
    candidate = SpacecraftAssembly(assembly.body_frame_id, (masquerading, *rest))
    try:
        verify_resolved_assembly(design, candidate)
    except ValueError as exc:
        return {"rejected": True, "reason": str(exc), "retained_choice_id": changed_pose.choice_id}
    raise AssertionError("unauthorized pose unexpectedly passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output-dir", type=Path)
    mode.add_argument("--load", type=Path)
    parser.add_argument("--expected-digest")
    args = parser.parse_args()
    if args.load is not None:
        result = summary(load_assembly_document(args.load, expected_digest=args.expected_digest))
    else:
        if args.expected_digest is not None:
            parser.error("--expected-digest requires --load")
        args.output_dir.mkdir(parents=True, exist_ok=False)
        result = {}
        for case in ("compact", "spread", "envelope-conflict", "reserved-conflict"):
            design = synthetic_design(case)
            save_assembly_document(design, args.output_dir / (case + ".json"))
            result[case] = summary(design)
        result["unauthorized-pose"] = unauthorized_pose_example()
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
