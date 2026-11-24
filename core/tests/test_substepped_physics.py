"""Independent time, linear ODE and electrical/ageing references for Task 04A."""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
from math import ulp

import pytest

from examples import v5_substepped_execution_demo as demo
from ops_sim.v5.degradation import (BatteryDegradationIntervalInput, BatteryThroughputIncrement,
    compute_battery_degradation_transition)
from ops_sim.v5.eps import compute_battery_transition, compute_battery_substep_transition
from ops_sim.v5.eps_system import EPSIntervalInputs, compute_eps_interval_transition, compute_eps_substep_transition
from ops_sim.v5.integration_time import DyadicDuration, IntegrationPolicy
from ops_sim.v5.operational_protection import ProtectedRequest, StandbyAction
from ops_sim.v5.substepped_execution import TimedRequest, execute_substepped_request
from ops_sim.v5.thermal import compute_thermal_interval_transition, compute_thermal_substep_transition


@pytest.mark.parametrize("level,seconds", [(0,23.0),(1,11.5),(2,5.75),(12,23/4096)])
def test_exact_partition_with_integer_absolute_clock_and_no_accumulation(level, seconds):
    policy = IntegrationPolicy(level)
    duration = policy.duration(23)
    assert duration.seconds == seconds
    offsets = [Fraction(i*23, 2**level) for i in range(policy.substeps+1)]
    assert offsets[0] == 0 and offsets[-1] == 23
    assert all(b-a == Fraction(23,2**level) for a,b in zip(offsets,offsets[1:]))
    # Absolute integer origin can be much larger than binary64 resolution.
    t0 = 2**70
    assert (t0 + offsets[-1]) - t0 == 23


@pytest.mark.parametrize("numerator,level", [(True,0),(23,True),(23.,1),(0,1),(-1,0),(2**40+1,0),(23,-1),(23,13)])
def test_representability_and_resource_limits_are_not_silently_rounded(numerator, level):
    with pytest.raises((TypeError,ValueError)):
        DyadicDuration(numerator, level)


@pytest.mark.parametrize("bad", [True,11.5,5.75,DyadicDuration(23,2)])
def test_old_duration_apis_still_reject_fractional_values(bad):
    c, wait = demo.thermal_case()
    cfg = c.inputs.spacecraft_configuration
    with pytest.raises(TypeError):
        compute_battery_transition(c.spacecraft_state.battery,cfg.eps.battery,generation_w=0.,load_w=1.,dt_seconds=bad)
    with pytest.raises(TypeError):
        compute_eps_interval_transition(c.spacecraft_state.battery,cfg.eps,
            EPSIntervalInputs(False,0.,wait.loads),dt_seconds=bad)
    with pytest.raises(TypeError):
        compute_thermal_interval_transition(c.spacecraft_state.thermal,cfg.thermal.network,wait.thermal_inputs,dt_seconds=bad)
    with pytest.raises(TypeError):
        BatteryDegradationIntervalInput(300.,BatteryThroughputIncrement(0.,0.,0.),bad)


@pytest.mark.parametrize("kernel", ["battery", "eps", "thermal"])
def test_new_duration_requires_explicit_validated_token(kernel):
    c,wait=demo.thermal_case();cfg=c.inputs.spacecraft_configuration
    with pytest.raises(TypeError):
        if kernel=="battery":
            compute_battery_substep_transition(c.spacecraft_state.battery,cfg.eps.battery,
                                               generation_w=0.,load_w=1.,duration=5.75)
        elif kernel=="eps":
            compute_eps_substep_transition(c.spacecraft_state.battery,cfg.eps,EPSIntervalInputs(False,0.,wait.loads),duration=5.75)
        else:
            compute_thermal_substep_transition(c.spacecraft_state.thermal,cfg.thermal.network,wait.thermal_inputs,duration=5.75)


@pytest.fixture(scope="module")
def references():
    return demo.numerical_references()


def test_original_12_second_reference_preserves_legacy_but_measures_temperature_error(references):
    c,wait=demo.thermal_case()
    legacy=compute_thermal_interval_transition(c.spacecraft_state.thermal,
        c.inputs.spacecraft_configuration.thermal.network,wait.thermal_inputs,dt_seconds=12)
    legacy_t={n.node_id.value:n.end_temperature_k for n in legacy.node_transitions}
    assert (legacy_t["bus"],legacy_t["payload"])==(286.,314.)
    ref=references["original_two_node"]
    assert ref["reference_k"]==pytest.approx((300.9071795328941,299.0928204671059),abs=1e-12,rel=0)
    rows=ref["rows"]
    assert (rows[0]["bus_k"],rows[0]["payload_k"])==(286.,314.)
    # h=6 overshoots the mode; the asymptotic Euler range starts at h=3.
    # These are specified K bounds against the ODE, not admission epsilons.
    convergent=rows[2:]
    assert all(a["max_error_k"]>b["max_error_k"] for a,b in zip(convergent,convergent[1:]))
    assert rows[-1]["max_error_k"] < .00065
    for row in rows:
        assert row["physical_duration_seconds"]==12 and row["completed_steps"]==1
        # Independent closed-system energy conservation is necessary, not sufficient.
        assert abs(10*(row["bus_k"]+row["payload_k"])-6000) < 2e-9


def test_cooling_23_second_reference_does_not_qualify_coarse_recovery(references):
    ref=references["cooling_recovery"]
    assert ref["reference_k"]==pytest.approx((300.4792651133611,336.98459095216606),abs=1e-12,rel=0)
    rows=ref["rows"]
    assert rows[0]["payload_k"]==300.
    assert rows[0]["subsequent_payload_start_within_320k"]
    assert all(not r["subsequent_payload_start_within_320k"] for r in rows[1:])
    assert all(a["max_error_k"]>b["max_error_k"] for a,b in zip(rows,rows[1:]))
    assert rows[-1]["max_error_k"] < .0046
    for row in rows:
        # Exact forcing Qb=12 W integrated over the SAME 23 seconds.
        energy=3600*(row["bus_k"]-300)+23*(row["payload_k"]-400)
        assert abs(energy-276) < 1e-7


def coupled_case(*, generation=0., maximum_charge=100., maximum_discharge=200., energy=80., activation=True):
    c=demo.old.physical.reference_context();cfg=c.inputs.spacecraft_configuration
    battery=replace(cfg.eps.battery,
        max_charge_input_power_w=demo.old.physical.parameter_value(cfg.eps.battery.max_charge_input_power_w,maximum_charge),
        max_discharge_output_power_w=demo.old.physical.parameter_value(cfg.eps.battery.max_discharge_output_power_w,maximum_discharge))
    solar=replace(cfg.eps.solar_array,nominal_generation_w=demo.old.physical.parameter_value(
        cfg.eps.solar_array.nominal_generation_w,(generation or 20.)/.8))
    model=cfg.degradation.battery_ageing_model
    if not activation:
        model=replace(model,calendar_activation_energy_j_per_mol=replace(model.calendar_activation_energy_j_per_mol,value=0.),
                      cycling_activation_energy_j_per_mol=replace(model.cycling_activation_energy_j_per_mol,value=0.))
    c.inputs=replace(c.inputs,spacecraft_configuration=replace(cfg,eps=replace(cfg.eps,battery=battery,solar_array=solar),
        degradation=replace(cfg.degradation,battery_ageing_model=model)))
    c.spacecraft_state.battery.energy_wh=energy
    wait=replace(demo.old.standby(c,sunlit=generation>0),solar_degradation_forcing=None)
    return c,TimedRequest(100,123,ProtectedRequest(StandbyAction("coupled-reference"),wait))


@pytest.mark.parametrize("generation,charge_max,discharge_max,charge,discharge,unmet,curtailed", [
    (0.,100.,200.,0.,20.,0.,0.),
    (60.,100.,200.,40.,0.,0.,0.),
    (60.,7.,200.,7.,0.,0.,33.),
    (0.,100.,5.,0.,5.,15.,0.),
])
def test_fractional_coupled_energy_routed_heat_and_nonzero_arrhenius_ageing(
        generation,charge_max,discharge_max,charge,discharge,unmet,curtailed):
    c,timed=coupled_case(generation=generation,maximum_charge=charge_max,maximum_discharge=discharge_max)
    before=deepcopy(c)
    r=execute_substepped_request(c,demo.old.physical.storage._previous_execution(),timed,
                                policy=demo.old.policy(c),integration=IntegrationPolicy(2))
    a=r.outcome.accounting
    h=Fraction(23,3600)
    stored=Fraction(str(charge))*Fraction(9,10)*h
    extracted=Fraction(str(discharge))/Fraction(4,5)*h
    loss=Fraction(str(charge))*h-stored+extracted-Fraction(str(discharge))*h
    expected={"generation_wh":generation*h,"requested_load_wh":20*h,"served_load_wh":(20-unmet)*h,
        "unmet_load_wh":unmet*h,"charge_input_wh":charge*h,"discharge_output_wh":discharge*h,
        "curtailed_generation_wh":curtailed*h,"conversion_loss_wh":loss,"throughput_wh":stored+extracted,
        "unavailable_energy_wh":0.,"external_heat_wh":6*h,"routed_internal_heat_wh":(20-unmet)*h/2}
    for name,value in expected.items():
        # Short independent electrical balance, not comparison with an ODE solution.
        assert abs(getattr(a,name)-float(value)) <= 64*ulp(float(value) or 1.),name
    assert abs(c.spacecraft_state.battery.energy_wh-float(80+stored-extracted)) <= 16*ulp(80.)
    assert a.numerical_substeps==4 and all(p.eps_result.battery.dt_seconds==5.75 for p in r.substeps)
    with localcontext() as ctx:
        ctx.prec=60
        dh=Decimal(23)/4
        # Independent literal thermal balance: conversion losses only at battery;
        # +1 W external IR; C=3600 J/K. Calendar/cycling use each midpoint.
        power=Decimal(loss.numerator)/Decimal(loss.denominator)*3600/23+1
        increment=Decimal((stored+extracted).numerator)/Decimal((stored+extracted).denominator)/4
        calendar=Decimal(0);cycling=Decimal(0)
        for i in range(4):
            temp=Decimal(300)+(Decimal(i)+Decimal('.5'))*dh*power/3600
            inv=Decimal(1)/300-Decimal(1)/temp
            calendar+=Decimal('.000001')*dh*(Decimal(12000)/Decimal('8.31446261815324')*inv).exp()
            cycling+=Decimal('.002')*increment/100*(Decimal(6000)/Decimal('8.31446261815324')*inv).exp()
    assert abs(a.calendar_damage-float(calendar)) < 128*ulp(float(calendar))
    assert abs(a.cycling_damage-float(cycling)) < 128*ulp(float(cycling))
    assert abs(c.spacecraft_state.degradation.battery.usable_capacity_retention-float(Decimal('.9')-calendar-cycling))<16*ulp(.9)
    assert all(p.eps_capability_result.battery_capacity_retention == p.battery_degradation_result.start_usable_capacity_retention
               for p in r.substeps)
    assert r.substeps[-1].eps_capability_result.battery_capacity_retention < r.substeps[0].eps_capability_result.battery_capacity_retention
    assert c.inputs is before.inputs or c.inputs==before.inputs
    assert c.ground_knowledge_state==before.ground_knowledge_state


def test_capacity_reconciled_each_substep_and_never_counted_as_heat():
    c,timed=coupled_case(generation=60.,energy=90.,activation=False)
    result=execute_substepped_request(c,demo.old.physical.storage._previous_execution(),timed,
        policy=demo.old.policy(c),integration=IntegrationPolicy(2))
    a=result.outcome.accounting
    # At the current capacity on every step: no charge movement. Uniform
    # calendar loss: 100 Wh * 1e-6/s * 23 s = .0023 Wh inaccessible.
    assert a.charge_input_wh==a.throughput_wh==a.conversion_loss_wh==0.
    assert abs(a.unavailable_energy_wh-.0023)<8*ulp(90.)
    assert abs(c.spacecraft_state.battery.energy_wh-89.9977)<8*ulp(90.)
    assert all(p.battery_capacity_reconciliation_result.unavailable_energy_wh>0 for p in result.substeps)
    for p in result.substeps:
        assert all(ledger.battery_conversion_heat_w==0 for ledger in p.thermal_coupling_result.node_heat_ledgers)
    battery=next(n.temperature_k for n in c.spacecraft_state.thermal.node_states if n.node_id.value=="battery")
    assert abs(battery-(300+23/3600)) < 8*ulp(300.)  # only declared 1 W external IR


def test_capacity_limited_charging_and_empty_battery_have_independent_total_balances():
    for energy,generation in ((89.999,60.),(0.,0.)):
        c,timed=coupled_case(generation=generation,energy=energy,activation=False)
        r=execute_substepped_request(c,demo.old.physical.storage._previous_execution(),timed,
            policy=demo.old.policy(c),integration=IntegrationPolicy(2))
        a=r.outcome.accounting
        if energy:
            assert abs(a.throughput_wh-.001)<8*ulp(90.)
            assert abs(a.charge_input_wh-.001/.9)<16*ulp(90.)
            assert abs(a.conversion_loss_wh-.001*(1/.9-1))<16*ulp(90.)
            assert abs(a.unavailable_energy_wh-(.0023+.002*.001))<32*ulp(90.)
        else:
            assert a.served_load_wh==a.throughput_wh==a.conversion_loss_wh==0.
            assert a.unmet_load_wh==20*23/3600
        assert abs(c.spacecraft_state.battery.energy_wh-(energy+a.throughput_wh-a.unavailable_energy_wh))<16*ulp(90.)
