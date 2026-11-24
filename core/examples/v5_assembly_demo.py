"""Print nominal 05E mass, COM, full tensor and legacy +Y projection.

Run: python -B -m examples.v5_assembly_demo
No simulation or file writes. All distributions are explicitly assumed.
"""

from collections import Counter
import json

from ops_sim.v5.assembly import calculate_mass_properties, convert_05e_allocation
from ops_sim.v5.design_trade_design import derive_design


def main() -> None:
    rows = []
    for packs, arrays in ((2, 2), (8, 2), (2, 4), (4, 4)):
        legacy = derive_design(packs, arrays)
        conversion = convert_05e_allocation(packs, arrays)
        assembly = conversion.assembly
        properties = calculate_mass_properties(assembly)
        rows.append({
            "design_id": legacy.design_id,
            "body_frame_id": properties.body_frame_id,
            "distribution": "ASSUMED_UNIFORM_CUBOID; zero dimensions are explicit limits",
            "component_count": len(assembly.components),
            "mass_accounting_status": assembly.mass_accounting_status,
            "mount_accounting_status": assembly.mount_accounting_status,
            "legacy_accepted": conversion.accepted,
            "legacy_rejection_reasons": conversion.rejection_reasons,
            "idealizations": dict(sorted(Counter(
                c.definition.idealization for c in assembly.components).items())),
            "mass_kg": properties.total_mass_kg,
            "com_body_m": properties.center_body_m,
            "inertia_about_com_body_kg_m2": properties.inertia_com_body_kg_m2,
            "legacy_y_projection_kg_m2": properties.inertia_com_body_kg_m2[1][1],
            "legacy_scalar_y_kg_m2": legacy.inertia_y_kg_m2,
        })
    print(json.dumps(rows, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
