"""Outcome-independent layout and circuit checks for the declared 05E screen."""

from dataclasses import replace
from decimal import Decimal, localcontext
from math import fsum, ulp

import pytest

from ops_sim.v5.design_trade_design import (
    DesignAssumptions, derive_design, design_record, enumerate_designs,
    load_input, select_designs, solar_input,
)
from ops_sim.v5.design_trade_physics import mass_properties_y


def test_design_space_and_selection_are_deterministic_before_mission_scores():
    designs = enumerate_designs()
    assert len(designs) == 12
    assert tuple(d.design_id for d in select_designs(designs)) == (
        "B2-A2", "B8-A2", "B2-A4", "B4-A4")
    assert select_designs(tuple(reversed(designs))) == select_designs(designs)
    assert len({d.design_id for d in designs}) == 12
    assert all(not d.accepted and "stowed_panel_mount_count" in d.rejection_reasons
               for d in designs if d.arrays == 6)
    assert all(not d.accepted and "total_mass_ceiling" in d.rejection_reasons
               for d in designs if d.arrays == 4 and d.packs in (6, 8))


@pytest.mark.parametrize("packs,arrays", [(2, 2), (8, 2), (2, 4), (4, 4)])
def test_complete_catalog_assembly_counted_once_and_explicit_spare_mass(packs, arrays):
    design = derive_design(packs, arrays)
    assert design.accepted
    catalog = tuple(c for c in design.components
        if c.name.endswith("_deployed") or c.name.endswith("_catalog_root_parts"))
    assert len(catalog) == 2 * arrays
    assert fsum(c.mass_kg for c in catalog) == pytest.approx(arrays * .885, abs=1e-15)
    assert fsum(c.mass_kg for c in design.components) == design.total_mass_kg
    assert design.spare_mass_kg == design.assumptions.mass_ceiling_kg - design.total_mass_kg
    assert design.capacity_wh == 86 * packs
    assert design.battery_occupied_volume_m3 == packs * .0948 * .095 * .042
    independent = mass_properties_y(design.components)
    assert design.inertia_y_kg_m2 == independent.inertia_y_kg_m2
    assert design.center_of_mass_m == independent.center_m
    assert design.center_of_mass_m[0] == 0
    assert design.center_of_mass_m[2] == pytest.approx(0, abs=1e-18)


def test_core_uncertainty_changes_only_centroidal_inertia():
    baseline = derive_design(4, 4)
    changed = derive_design(4, 4, replace(DesignAssumptions(), core_inertia_scale=1.25))
    assert changed.components == baseline.components
    assert changed.total_mass_kg == baseline.total_mass_kg
    assert changed.center_of_mass_m == baseline.center_of_mass_m
    independent_delta = .25 * 70 * (.8**2 + 1**2) / 12
    assert changed.inertia_y_kg_m2 - baseline.inertia_y_kg_m2 == pytest.approx(
        independent_delta, rel=1e-14)


def test_wire_rule_includes_current_and_return_route():
    design = derive_design(2, 2)
    # Decimal mm² -> binary64 m² multiplication can differ by one ULP from
    # directly rounding the equivalent decimal m² literal.
    assert abs(design.main_wire.cross_section_m2 - 2.5e-6) <= ulp(2.5e-6)
    assert all(w.cross_section_m2 == .25e-6 for w in design.string_wires)
    assert design.main_wire.loop_length_m == 1.6
    assert all(w.loop_length_m == 1.2 for w in design.string_wires)
    assert design.main_wire.current_limit_a == 7.5
    assert all(w.current_limit_a == .75 for w in design.string_wires)
    load = load_input(design, 160)
    with localcontext() as context:
        context.prec = 60
        resistance = Decimal("0.0310336")
        current = (Decimal(28) - (Decimal(784) - 4 * resistance * 160).sqrt()) / (2 * resistance)
        expected_source = 28 * current
    assert load.source_power_w == pytest.approx(float(expected_source), rel=2e-15)
    assert load.source_power_w == load.delivered_power_w + load.loss_w
    assert load.current_a < design.main_wire.current_limit_a
    assert load.voltage_drop_v < design.main_wire.max_drop_v


@pytest.mark.parametrize("incidence", [0.0, 0.5, 1.0])
def test_source_to_bus_balance_and_ideal_wiring_removes_only_harness(incidence):
    design = derive_design(2, 4)
    full = solar_input(design, incidence)
    ideal = solar_input(design, incidence, ideal_wiring=True)
    assert full.nominal_power_w == 4 * 45 * incidence
    assert full.nominal_power_w == pytest.approx(
        full.delivered_bus_w + full.harness_heat_w + full.converter_heat_w, abs=3e-14)
    assert full.after_harness_w == full.nominal_power_w - full.harness_heat_w
    assert ideal.harness_heat_w == 0
    assert ideal.nominal_power_w == full.nominal_power_w
    assert ideal.delivered_bus_w == ideal.nominal_power_w * .95
    assert full.delivered_bus_w <= ideal.delivered_bus_w


@pytest.mark.parametrize("assumptions,reason", [
    (replace(DesignAssumptions(), maximum_packs=4), "battery_bay_pack_count"),
    (replace(DesignAssumptions(), regulator_input_limit_v=20.0),
     "regulator_below_published_string_open_circuit_voltage"),
    (replace(DesignAssumptions(), deployed_span_limit_m=2.0), "deployed_envelope"),
])
def test_forbidden_configurations_remain_explicitly_rejected(assumptions, reason):
    design = derive_design(8, 2, assumptions)
    assert not design.accepted
    assert reason in design.rejection_reasons
    with pytest.raises(ValueError):
        solar_input(design, 1.0)


@pytest.mark.parametrize("field,reason", [
    ("string_route_m", "string_route_shorter_than_installation_path"),
    ("load_route_m", "load_route_shorter_than_installation_path"),
])
def test_declared_cable_cannot_be_shorter_than_obstacle_clearing_route(field, reason):
    design = derive_design(2, 2, replace(DesignAssumptions(), **{field: .1}))
    assert not design.accepted
    assert reason in design.rejection_reasons
    nominal = design_record(derive_design(2, 4))["external_routing"]
    assert all(route["service_allowance_m"] >= 0 for route in nominal["string_routes"])
    assert nominal["main_service_allowance_m"] >= 0


def test_export_retains_parameters_layout_and_unknown_cost_terms():
    design = derive_design(2, 2)
    record = design_record(design)
    assert record["fixed_physical_conventions"]["array_total_kg"] == .885
    assert record["cost_expression"]["BP8_pack"] == 2
    assert record["cost_expression"]["TSP_complete"] == 2
    assert len(record["components"]) == len(design.components)
    assert record["assumptions"]["harness_resistivity_factor"] == 1
