"""Independent ledger and discrete/continuous qualification report references."""

from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from examples.v5_design_trade_report import energy_checks, qualify_pair, selection


def hand_ledger():
    # Bus: 10 Wh PV + 8 Wh battery output = 15 Wh served + 1 Wh charge
    # input + 2 Wh curtailed. Each converter has eta=.9. Thus initial 50 Wh
    # becomes 50+.9-8/.9 Wh. Conversion heat is separate from routed load heat.
    with localcontext() as context:
        context.prec = 60
        initial, eta = Decimal(50), Decimal(".9")
        final = initial + eta - Decimal(8)/eta
        conversion = Decimal(1)-eta + Decimal(8)/eta-Decimal(8)
    return {
        "case": {"case_id": "independent-ledger"},
        "design": {"capacity_wh": 100.},
        "summary": {
            "spec": {"initial_fraction": .5, "assumptions": {
                "charge_efficiency": .9, "discharge_efficiency": .9}},
            "final_energy_wh": float(final),
            "accounting": {
                "generation_wh": 10., "requested_load_wh": 15., "served_load_wh": 15.,
                "charge_input_wh": 1., "discharge_output_wh": 8.,
                "curtailed_generation_wh": 2., "conversion_loss_wh": float(conversion),
                "unavailable_energy_wh": 0., "routed_internal_heat_wh": 15.,
                "numerical_substeps": 1},
            "diagnostic_energy_wh": {
                "solar_source_wh": 12., "solar_bus_wh": 10., "solar_wire_loss_wh": 1.,
                "solar_converter_loss_wh": 1., "terminal_load_wh": 14.,
                "load_wire_loss_wh": 1., "actuator_heat_adjustment_wh": 0.},
        },
    }


def test_independent_charge_discharge_bus_and_source_ledger_closes():
    result = energy_checks(hand_ledger())
    assert result["passed"]
    assert result["source_split_wh"] == 0
    assert result["solar_eps_wh"] == 0
    assert result["load_eps_wh"] == 0
    assert result["bus_balance_wh"] == 0
    assert result["retained_internal_heat_wh"] == 0
    assert abs(result["battery_balance_wh"]) <= 2e-14


def test_battery_conversion_heat_must_not_be_counted_twice_as_routed_heat():
    result = hand_ledger()
    accounts = result["summary"]["accounting"]
    accounts["routed_internal_heat_wh"] += accounts["conversion_loss_wh"]
    checked = energy_checks(result)
    assert not checked["passed"]
    assert checked["retained_internal_heat_wh"] == pytest.approx(
        accounts["conversion_loss_wh"], abs=2e-15)


@pytest.mark.parametrize("owner,field", [
    ("diagnostic_energy_wh", "solar_source_wh"),
    ("diagnostic_energy_wh", "solar_bus_wh"),
    ("diagnostic_energy_wh", "terminal_load_wh"),
    ("diagnostic_energy_wh", "actuator_heat_adjustment_wh"),
    ("accounting", "curtailed_generation_wh"),
    ("accounting", "routed_internal_heat_wh"),
    ("accounting", "unavailable_energy_wh"),
])
def test_one_micro_wh_ledger_error_exceeds_roundoff_screen(owner, field):
    result = hand_ledger()
    result["summary"][owner][field] += 1e-6
    assert not energy_checks(result)["passed"]


def numerical_result(level):
    return {"case": {"case_id": f"nominal__B2-A2__close__FULL__L{level}"},
        "design": {"capacity_wh": 100.}, "summary": {
            "weighted_credit": [1, 1],
            "requests": [{"request_id": "request", "credited_products": 1,
                "exact_completion_seconds": [13, 2], "reasons": []}],
            "phase_seconds": {"motion": 1, "imaging": 1},
            "events": [{"phase": "motion", "start_seconds": 0, "end_seconds": 1,
                "request_id": None, "start_angle_hex": 0.0.hex(), "end_angle_hex": 0.5.hex()}],
            "rejections": [],
            "physical_samples": [
                {"time": [0, 1], "energy_wh": 50., "temperatures_k": {"bus": 300., "battery": 301.}},
                {"time": [1, 1], "energy_wh": 49., "temperatures_k": {"bus": 300.01, "battery": 301.02}},
            ],
        }}


def test_continuous_differences_use_bounds_at_matching_exact_times():
    low, high = numerical_result(1), numerical_result(2)
    high["summary"]["physical_samples"].insert(1, {
        "time": [1, 2], "energy_wh": 49.5, "temperatures_k": {"bus": 300., "battery": 301.}})
    high["summary"]["physical_samples"][-1]["energy_wh"] += .05
    high["summary"]["physical_samples"][-1]["temperatures_k"]["bus"] += .05
    check = qualify_pair(low, high)
    assert check["passed"] and check["common_samples"] == 2
    assert check["exact_credit"] and check["exact_requests"] and check["exact_decisions"]
    high["summary"]["physical_samples"][-1]["energy_wh"] += .1
    assert not qualify_pair(low, high)["passed"]


@pytest.mark.parametrize("change", ["completion", "event-time", "rejection", "missing-time", "temperature"])
def test_changed_discrete_decision_or_unqualified_physics_cannot_hide_behind_same_score(change):
    low, high = numerical_result(1), numerical_result(2)
    summary = high["summary"]
    if change == "completion":
        summary["requests"][0]["exact_completion_seconds"] = [6500001, 1000000]
    elif change == "event-time":
        summary["events"][0]["end_seconds"] = 2
    elif change == "rejection":
        summary["rejections"] = [["request", "different-decision"]]
    elif change == "missing-time":
        summary["physical_samples"][-1]["time"] = [3, 2]
    else:
        summary["physical_samples"][-1]["temperatures_k"]["bus"] += .2
    check = qualify_pair(low, high)
    assert check["exact_credit"]
    assert not check["passed"]


def preference_result(design, variant, credit):
    return {"case": {"group": "nominal", "spec": {"design_id": design,
        "variant": variant, "workload": "close", "level": 2}},
        "summary": {"weighted_credit": [credit.numerator, credit.denominator]}}


def test_resource_ties_preserved_and_full_selection_loss_reports_both_extremes():
    rows = []
    for design, full, simple in (
            ("A", Fraction(1), Fraction(1)),
            ("B", Fraction(1, 2), Fraction(1)),
            ("C", Fraction(3, 4), Fraction(1, 2))):
        rows += [preference_result(design, "FULL", full),
                 preference_result(design, "RESOURCE_ONLY", simple)]
    result = selection(rows, "nominal", "close")
    assert result["full_best_designs"] == ["A"]
    assert result["resource_preferred_designs"] == ["A", "B"]
    assert result["selection_loss_range"] == ["0", "1/2"]
    assert result["full_credit_of_resource_preferred"] == {"A": "1", "B": "1/2"}
    assert selection(list(reversed(rows)), "nominal", "close") == result


def test_preference_requires_the_same_full_and_counterfactual_design_set():
    rows = [preference_result("A", "FULL", Fraction(1)),
            preference_result("B", "RESOURCE_ONLY", Fraction(1))]
    with pytest.raises(ValueError, match="incomplete paired"):
        selection(rows, "nominal", "close")
