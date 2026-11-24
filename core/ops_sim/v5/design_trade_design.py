"""Declared mass/layout/electrical design screen for the separate Task 05E study.

Catalog reference values are never a claim of integrated catalog compatibility.
Each complete TSP includes its internal hinges/harness/drive. Only its excluded
connect-PCB-to-regulator harness and an assumed bus adaptor are added here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from math import ceil, dist, fsum, isfinite

from .design_trade_physics import (BoxMassComponent, ElectricalLimitError,
    ElectricalLineResult, WireSpec, constant_power_load, generated_power_line,
    mass_properties_y)


@dataclass(frozen=True, slots=True)
class DesignAssumptions:
    core_mass_kg: float = 70.0
    core_size_m: tuple[float, float, float] = (0.8, 0.8, 1.0)
    core_inertia_scale: float = 1.0
    mass_ceiling_kg: float = 78.0
    maximum_packs: int = 8
    mounts_per_side: int = 2
    deployed_span_limit_m: float = 2.8
    pack_mount_mass_kg: float = 0.02
    array_adapter_mass_kg: float = 0.06
    regulator_bank_mass_kg: float = 0.6196
    regulator_input_limit_v: float = 35.0
    regulator_bus_limit_w: float = 300.0
    regulator_current_limit_a: float = 12.0
    solar_regulator_efficiency: float = 0.95
    charge_efficiency: float = 0.9
    discharge_efficiency: float = 0.9
    load_bus_v: float = 28.0
    load_sizing_power_w: float = 160.0
    string_route_m: float = 0.6
    load_route_m: float = 0.8
    copper_resistivity_ohm_m: float = 1.724e-8
    harness_resistivity_factor: float = 1.0
    copper_density_kg_m3: float = 8960.0
    wire_areas_mm2: tuple[float, ...] = (0.08, 0.14, 0.25, 0.5, 1.0, 1.5, 2.5)
    allowed_current_density_a_mm2: float = 3.0
    allowed_drop_fraction: float = 0.03
    connector_resistance_ohm: float = 0.01
    connector_mass_kg: float = 0.002
    connector_count_per_loop: int = 2
    insulation_to_copper_mass_ratio: float = 0.3

    def __post_init__(self):
        integers = {"maximum_packs", "mounts_per_side", "connector_count_per_loop"}
        tuples = {"core_size_m", "wire_areas_mm2"}
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in integers:
                if type(value) is not int or value <= 0:
                    raise ValueError(field.name + " must be a positive built-in integer")
            elif field.name in tuples:
                if (type(value) is not tuple or not value or any(type(x) is not float
                        or not isfinite(x) or x <= 0 for x in value)):
                    raise ValueError(field.name + " must contain positive finite built-in floats")
            elif type(value) is not float or not isfinite(value) or value <= 0:
                raise ValueError(field.name + " must be a positive finite built-in float")
        if len(self.core_size_m) != 3 or self.core_mass_kg < 46.0:
            raise ValueError("core must contain the 46 kg JSS56 reference payload")
        if self.core_size_m != (0.8, 0.8, 1.0):
            raise ValueError("this bounded study fixes its declared common layout")
        if self.maximum_packs > 8 or self.mounts_per_side > 2:
            raise ValueError("the declared battery bay and mounting layout cannot grow")
        if tuple(sorted(set(self.wire_areas_mm2))) != self.wire_areas_mm2:
            raise ValueError("wire areas must be strictly increasing")
        for name in ("solar_regulator_efficiency", "charge_efficiency",
                     "discharge_efficiency", "allowed_drop_fraction"):
            if getattr(self, name) > 1:
                raise ValueError(name + " exceeds one")


@dataclass(frozen=True, slots=True)
class TradeDesign:
    design_id: str
    packs: int
    arrays: int
    assumptions: DesignAssumptions
    accepted: bool
    rejection_reasons: tuple[str, ...]
    components: tuple[BoxMassComponent, ...]
    total_mass_kg: float
    spare_mass_kg: float
    center_of_mass_m: tuple[float, float, float]
    inertia_y_kg_m2: float
    capacity_wh: float
    charge_bus_w: float
    discharge_bus_w: float
    regulator_banks: int
    deployed_span_m: float
    battery_occupied_volume_m3: float
    string_wires: tuple[WireSpec, WireSpec]
    main_wire: WireSpec


@dataclass(frozen=True, slots=True)
class SolarInput:
    nominal_power_w: float
    after_harness_w: float
    delivered_bus_w: float
    harness_heat_w: float
    converter_heat_w: float


def _routing_geometry(arrays):
    """Obstacle-clearing external routes, distinct from mass lumping below."""
    per_side = arrays // 2
    routes = []
    for row in range(per_side):
        y = (row - (per_side - 1) / 2) * 0.24
        bank_z = (row - (per_side - 1) / 2) * 0.07
        for side in (-1, 1):
            points = ((side * 0.4, y, 0.0),
                      (side * 0.34, -0.075, bank_z / 2),
                      (0.0, -0.16, bank_z))
            routes.append((f"array_{row}_{side}", points,
                           fsum(dist(p, q) for p, q in zip(points, points[1:]))))
    # One load junction below the imager box and outside the electronic box.
    # Branch distribution inside each common subsystem is included in its
    # common definition; this is the single explicitly resolved load trunk.
    main = ((0.0, -0.16, 0.0), (0.25, -0.16, 0.0), (0.25, -0.075, 0.31))
    return tuple(routes), main, fsum(dist(p, q) for p, q in zip(main, main[1:]))


def _wire(a: DesignAssumptions, voltage: float, route: float, *,
          string: bool) -> WireSpec:
    for area in a.wire_areas_mm2:
        wire = WireSpec(route, area * 1e-6,
            a.copper_resistivity_ohm_m * a.harness_resistivity_factor,
            a.copper_density_kg_m3, a.connector_resistance_ohm,
            a.connector_count_per_loop, a.connector_mass_kg,
            area * a.allowed_current_density_a_mm2, voltage * a.allowed_drop_fraction)
        try:
            if string:
                # Admission at the published maximum string current, not just
                # the lower current of the assumed net 45 W operating point.
                generated_power_line(wire, voltage, voltage * 0.510)
            else:
                constant_power_load(wire, voltage, a.load_sizing_power_w)
        except ElectricalLimitError:
            continue
        return wire
    raise ElectricalLimitError("no declared wire area admits the route")


def derive_design(packs: int, arrays: int,
                  assumptions: DesignAssumptions | None = None) -> TradeDesign:
    if type(packs) is not int or packs not in (2, 4, 6, 8):
        raise ValueError("pack count is outside the predeclared design space")
    if type(arrays) is not int or arrays not in (2, 4, 6):
        raise ValueError("array count is outside the predeclared design space")
    a = DesignAssumptions() if assumptions is None else assumptions
    if type(a) is not DesignAssumptions:
        raise TypeError("exact DesignAssumptions required")
    a = DesignAssumptions(**{f.name: getattr(a, f.name) for f in fields(a)})
    reasons = []
    if packs > a.maximum_packs:
        reasons.append("battery_bay_pack_count")
    if arrays // 2 > a.mounts_per_side:
        reasons.append("stowed_panel_mount_count")
    if a.regulator_input_limit_v < 20.80:
        reasons.append("regulator_below_published_string_open_circuit_voltage")
    span = a.core_size_m[0] + 2 * 0.930
    if span > a.deployed_span_limit_m:
        reasons.append("deployed_envelope")
    routes, _, main_minimum = _routing_geometry(arrays)
    if a.string_route_m < max(route[2] for route in routes):
        reasons.append("string_route_shorter_than_installation_path")
    if a.load_route_m < main_minimum:
        reasons.append("load_route_shorter_than_installation_path")
    # Wiring is independently sized by one common rule. A failed electrical
    # installation is rejected; no limit is clamped to conceal inadmissibility.
    wires = (_wire(a, 15.82, a.string_route_m, string=True),
             _wire(a, 18.08, a.string_route_m, string=True))
    main = _wire(a, a.load_bus_v, a.load_route_m, string=False)
    components = [BoxMassComponent("core_including_imager_and_actuator",
                                  a.core_mass_kg, a.core_size_m, (0.0, 0.0, 0.0))]
    rows = packs // 2
    for row in range(rows):
        z = (row - (rows - 1) / 2) * 0.10
        for side in (-1, 1):
            center = (side * 0.08, -0.28, z)
            name = f"battery_{row}_{side}"
            components.append(BoxMassComponent(name, 0.486, (0.0948, 0.042, 0.095), center))
            components.append(BoxMassComponent(name + "_external_mount", a.pack_mount_mass_kg,
                (0.10, 0.004, 0.10), (center[0], center[1] + 0.023, center[2])))
    per_side = arrays // 2
    for row in range(per_side):
        y = (row - (per_side - 1) / 2) * 0.24
        for side in (-1, 1):
            root = (side * 0.4, y, 0.0)
            name = f"array_{row}_{side}"
            components.append(BoxMassComponent(name + "_deployed", 0.650,
                (0.908, 0.208, 0.003), (side * (0.4 + 0.022 + 0.908 / 2), y, 0.0)))
            components.append(BoxMassComponent(name + "_catalog_root_parts", 0.235,
                (0.011, 0.208, 0.330), root))
            components.append(BoxMassComponent(name + "_external_adapter", a.array_adapter_mass_kg,
                (0.010, 0.220, 0.340), root))
            # External cables are routed inward from the connect PCB. Internal
            # wing cables, hinges, drive and cover mass are already in 885 g.
            for kind, wire in enumerate(wires):
                for number in range(3):
                    key = name + f"_external_string_{kind}_{number}"
                    bank_z = (row - (per_side - 1) / 2) * 0.07
                    cable_center = (side * 0.2, (y - 0.16) / 2, bank_z / 2)
                    components.append(BoxMassComponent(key, wire.harness_mass_kg,
                        (0.4, abs(y + 0.16), abs(bank_z)), cable_center))
                    copper_mass = wire.conductor_mass_kg
                    components.append(BoxMassComponent(key + "_insulation",
                        copper_mass * a.insulation_to_copper_mass_ratio,
                        (0.4, abs(y + 0.16), abs(bank_z)), cable_center))
    banks = ceil(arrays * 6 / 12)
    for bank in range(banks):
        # Banks fill a symmetric z stack in the reserved electronics bay.
        center = (0.0, -0.16, (bank - (banks - 1) / 2) * 0.07)
        components.append(BoxMassComponent(f"regulator_equivalent_bank_{bank}",
            a.regulator_bank_mass_kg, (0.095, 0.095, 0.065), center))
    components.append(BoxMassComponent("main_load_harness", main.harness_mass_kg,
                                       (0.30, 0.30, 0.20), (0.0, 0.0, 0.0)))
    copper_mass = main.conductor_mass_kg
    components.append(BoxMassComponent("main_load_harness_insulation",
        copper_mass * a.insulation_to_copper_mass_ratio, (0.30, 0.30, 0.20), (0.0, 0.0, 0.0)))
    properties = mass_properties_y(tuple(components))
    core_centroidal = a.core_mass_kg * (a.core_size_m[0] ** 2 + a.core_size_m[2] ** 2) / 12
    inertia = properties.inertia_y_kg_m2 + (a.core_inertia_scale - 1) * core_centroidal
    if not isfinite(inertia) or inertia <= 0:
        raise ValueError("derived inertia must be finite and positive")
    if properties.total_mass_kg > a.mass_ceiling_kg:
        reasons.append("total_mass_ceiling")
    charge = min(a.regulator_bus_limit_w, 23.6 * a.regulator_current_limit_a,
                 23.6 * min(packs * 3.4, a.regulator_current_limit_a) / a.charge_efficiency)
    discharge = min(a.regulator_bus_limit_w,
                    23.6 * min(packs * 4.0, a.regulator_current_limit_a) * a.discharge_efficiency)
    return TradeDesign(f"B{packs}-A{arrays}", packs, arrays, a, not reasons, tuple(reasons),
        tuple(components), properties.total_mass_kg, a.mass_ceiling_kg - properties.total_mass_kg,
        properties.center_m, inertia, packs * 86.0, charge, discharge, banks, span,
        packs * 0.0948 * 0.095 * 0.042, wires, main)


def enumerate_designs(assumptions: DesignAssumptions | None = None) -> tuple[TradeDesign, ...]:
    return tuple(derive_design(b, a, assumptions) for a in (2, 4, 6) for b in (2, 4, 6, 8))


def select_designs(designs: tuple[TradeDesign, ...]) -> tuple[TradeDesign, ...]:
    """Outcome-independent min/max feasible battery count at each array count."""
    if type(designs) is not tuple or any(type(d) is not TradeDesign for d in designs):
        raise TypeError("selection requires exact immutable design records")
    selected = []
    for count in sorted({d.arrays for d in designs}):
        feasible = sorted((d for d in designs if d.arrays == count and d.accepted), key=lambda d: d.packs)
        if feasible:
            selected.append(feasible[0])
            if feasible[-1] != feasible[0]:
                selected.append(feasible[-1])
    return tuple(selected)


def solar_input(design: TradeDesign, incidence: float, *, ideal_wiring: bool = False) -> SolarInput:
    if type(design) is not TradeDesign or not design.accepted:
        raise ValueError("solar calculation requires an accepted design")
    if type(incidence) not in (int, float) or not isfinite(incidence) or not 0 <= incidence <= 1:
        raise ValueError("incidence must be a finite built-in fraction")
    if type(ideal_wiring) is not bool:
        raise TypeError("ideal_wiring must be a built-in boolean")
    current = 45.0 * incidence / (3 * (15.82 + 18.08))
    source = design.arrays * 45.0 * incidence
    loss = 0.0 if ideal_wiring else design.arrays * 3 * fsum(
        generated_power_line(wire, voltage, voltage * current).loss_w
        for wire, voltage in zip(design.string_wires, (15.82, 18.08)))
    after_wire = source - loss
    delivered = after_wire * design.assumptions.solar_regulator_efficiency
    return SolarInput(source, after_wire, delivered, loss, after_wire - delivered)


def load_input(design: TradeDesign, load_w: float) -> ElectricalLineResult:
    if type(design) is not TradeDesign or not design.accepted:
        raise ValueError("load calculation requires an accepted design")
    return constant_power_load(design.main_wire, design.assumptions.load_bus_v, load_w)


def design_record(design: TradeDesign) -> dict:
    """All assumptions, component coordinates, wires and capacities are explicit."""
    if type(design) is not TradeDesign:
        raise TypeError("exact TradeDesign required")
    record = asdict(design)
    routes, main, main_minimum = _routing_geometry(design.arrays)
    record["external_routing"] = {
        "string_routes": [{"array": name, "points_m": points,
                           "minimum_one_way_length_m": minimum,
                           "service_allowance_m": design.assumptions.string_route_m - minimum}
                          for name, points, minimum in routes],
        "main_route_points_m": main,
        "main_minimum_one_way_length_m": main_minimum,
        "main_service_allowance_m": design.assumptions.load_route_m - main_minimum,
        "scope": "two-segment diagonal routing clears reserved payload/electronics; not a right-angle Manhattan route"}
    record["cost_expression"] = {
        "common_core": 1, "BP8_pack": design.packs, "TSP_complete": design.arrays,
        "regulator_bank": design.regulator_banks, "pack_mount": design.packs,
        "array_adapter": design.arrays,
        "external_harness_kg": fsum(c.mass_kg for c in design.components
            if "harness" in c.name or "external_string" in c.name),
        "meaning": "sum(count_or_mass * unknown_named_unit_cost); no sourced prices"}
    record["fixed_physical_conventions"] = {
        "pack_wh": 86.0, "pack_mass_kg": 0.486, "pack_reference_v": 23.6,
        "pack_current_charge_a": 3.4, "pack_current_discharge_a": 4.0,
        "pack_size_m": [0.0948, 0.042, 0.095], "array_total_kg": 0.885,
        "array_wing_kg": 0.650, "array_root_kg": 0.235,
        "array_wing_size_m": [0.908, 0.208, 0.003], "array_net_interface_w": 45.0,
        "string_loaded_v": [15.82, 18.08], "strings_per_kind": 3,
        "source_line_admission_a": 0.510, "array_normal_body": [0.0, 0.0, 1.0],
        "rotation_axis_body": [0.0, 1.0, 0.0], "array_root_to_tip_m": 0.930,
        "stowed_mount_footprint_m": [0.208, 0.330], "stowed_protrusion_allowance_m": 0.011,
        "battery_reserved_bay_m": [0.28, 0.05, 0.41],
        "battery_reserved_bay_center_m": [0.0, -0.28, 0.0],
        "imager_reserved_box_m": [0.641, 0.385, 0.865],
        "imager_reserved_box_center_m": [0.0, 0.14, 0.0],
        "imager_electronics_reserved_box_m": [0.280, 0.232, 0.253],
        "imager_electronics_reserved_box_center_m": [0.0, -0.22, 0.355],
        "harness_mass_distribution": "uniform projected route and central main-harness box, including distributed connector/service-loop mass; approximation",
        "core_centroidal_inertia_rule": "uniform box moment multiplied by explicit uncertainty scale",
        "battery_interface_scope": "plug/backplane included in regulator mass and existing charge/discharge efficiency",
        "regulator_scope": "assumed independent string conditioners; not catalog compatibility certification",
        "thermal_scope": "no panel temperature model; external string heat is separately exported"}
    return record
