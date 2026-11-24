"""Task05C reference arithmetic, causal seams and fail-closed reporting."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
from math import ceil, ulp

import pytest

from ops_sim.v5.comparison_manifest import manifest, load_manifest, derive_hardware
from ops_sim.v5.comparison_campaign import build_inputs_program, parameter
from ops_sim.v5.comparison_evidence import weighted_score, qualify_pair
from ops_sim.v5.campaign_continuation import start_campaign, planning_boundary
from ops_sim.v5.campaign_controller import execute_selected
from ops_sim.v5.campaign_contract import PlannedAction
from ops_sim.v5.contact_execution import ConsumedContacts
from ops_sim.v5.experiment_codec import canonical_content


@pytest.mark.parametrize("identity,energy,solar,mass,discharge",[
    ("D-E1",344,90,3.714,254.88),("D-E2",258,135,4.113,254.88),
    ("D-E3",172,180,4.512,169.92),("D-E4",86,225,4.911,84.96)])
def test_independent_eps_reference(identity,energy,solar,mass,discharge):
    h = derive_hardware(manifest(),identity)
    assert h["working_energy_wh"] == energy
    assert h["initial_energy_wh"] == energy/2
    assert h["solar_w"] == solar
    assert h["partial_mass_kg"] == mass
    # At most four binary64 roundings in the literal reference conversion/product.
    assert abs(h["discharge_bus_w"]-discharge) <= 4*ulp(discharge)
    assert h["charge_bus_w"] <= 283.2+4*ulp(283.2)
    # Explicit battery-side current checks, correct opposite efficiency sides.
    assert h["charge_bus_w"]*.9/23.6 <= min(h["packs"]*3.4,12)+2e-15
    assert h["discharge_bus_w"]/.9/23.6 <= min(h["packs"]*4,12)+2e-15


@pytest.mark.parametrize("family,spacing,swath,bits,gb",[
    ("D",Fraction(315,68),Fraction(315000,17),8,4),
    ("H",Fraction(21,5),Fraction(12600),10,32),
    ("J",Fraction(13,2),Fraction(77000),12,6)])
def test_native_normalization_and_integer_grid(family,spacing,swath,bits,gb):
    h = derive_hardware(manifest(),family+"-E1")
    assert Fraction(h["sampling_exact"]) == spacing
    assert Fraction(h["swath_exact"]) == swath
    inputs,p = build_inputs_program(family+"-E1")
    s = p.opportunities[0].acquisition.sizing
    # Literal independent ceiling calculation from native paper values.
    assert s.stored_bits == ceil(Fraction(10000)/spacing)*ceil(Fraction(30000)/spacing)*(5 if family=="J" else 4)*bits
    assert inputs.spacecraft_configuration.storage.usable_capacity_gb.value == gb
    assert inputs.spacecraft_configuration.payload.optical_acquisition.multispectral_reference_sample_spacing_m.value == float(spacing)
    assert s.spacing_x_m == float(spacing)


def test_twelve_vectors_and_shared_causal_inputs():
    vectors,programs,numeric_vectors = [],[],[]
    for f in "DHJ":
        for i in range(1,5):
            inputs,p = build_inputs_program(f+f"-E{i}")
            vectors.append(canonical_content(inputs.spacecraft_configuration))
            programs.append(p)
            c=inputs.spacecraft_configuration
            numeric_vectors.append((c.eps.battery.nominal_energy_wh.value,c.eps.solar_array.nominal_generation_w.value,
                c.payload.optical_acquisition.multispectral_reference_sample_spacing_m.value,
                c.payload.optical_acquisition.multispectral_band_count.value,
                c.payload.optical_acquisition.acquisition_bits_per_sample.value,
                c.storage.usable_capacity_gb.value,c.communications.nominal_downlink_data_rate_bps.value))
    assert len({json.dumps(x,sort_keys=True) for x in vectors}) == 12
    assert len(set(numeric_vectors)) == 12  # Excludes all labels/IDs/scenarios/seeds.
    origin = programs[0]
    for p in programs:
        assert p.requests == origin.requests
        assert p.policy == origin.policy
        assert p.knowledge == origin.knowledge
        assert p.contacts == origin.contacts
        assert p.initial_checkpoint.spacecraft.degradation == origin.initial_checkpoint.spacecraft.degradation


def test_s2_changes_only_contacts_and_refinement_only_integration():
    x,a = build_inputs_program("H-E2","S1")
    y,b = build_inputs_program("H-E2","S2")
    assert x == y
    assert replace(a,contacts=b.contacts) == b
    assert len(a.contacts)==5 and len(b.contacts)==3 and set(b.contacts)<set(a.contacts)
    _,c = build_inputs_program("H-E2","S1",level=2)
    assert replace(a,integration=c.integration)==c


@pytest.mark.parametrize("mutation",[
    lambda m:m.update(extra=1),lambda m:m.update(version=True),
    lambda m:m["families"]["D"]["native_sampling_m"].update(units="km"),
    lambda m:m["families"]["J"]["reference_power_w"].update(value=float("nan")),
    lambda m:m["assumptions"]["charge_efficiency"].update(value=1.1),
    lambda m:m["allocations"]["E1"].update(packs=True),
    lambda m:m["assumptions"]["baseline_w"].update(kind="SOURCE"),
    lambda m:m["families"]["J"]["channels"].update(value=["B","G","R","NIR","NIR"]),
])
def test_strict_manifest_rejects_mutations(mutation):
    m=manifest(); mutation(m)
    with pytest.raises(ValueError): load_manifest(json.dumps(m))


def test_manifest_duplicate_keys_and_source_scope():
    with pytest.raises(ValueError): load_manifest('{"version":1,"version":1}')
    m=load_manifest(json.dumps(manifest()))
    assert m["families"]["J"]["reference_rate_mbps"]["source"] == "KGS"
    assert m["families"]["J"]["reference_power_w"]["conditions"] == "Peak simultaneous imaging/downlink"
    assert m["technology"]["array_mass_kg"]["value"] == .885
    assert m["technology"]["array_summary_mass_kg"]["value"] == .750
    assert m["assumptions"]["mode_factors"]["kind"] == "ASSUMED"


def image(identity="H-E1",factor=1.,storage_gb=None):
    inputs,p=build_inputs_program(identity,mode_factor=factor)
    if storage_gb is not None:
        c=inputs.spacecraft_configuration
        inputs=replace(inputs,spacecraft_configuration=replace(c,storage=replace(c.storage,
            usable_capacity_gb=parameter("storage.usable-capacity","GB",storage_gb))))
    state=start_campaign(inputs,p)
    view,_=planning_boundary(inputs,p,state.memory)
    action=PlannedAction("imaging","task05c-op0",0,60,(),"focused wiring probe")
    result=execute_selected(state.context,view,action,p.initial_attitude,ConsumedContacts(()))
    return state.context,result


def test_actual_protected_power_and_storage_wiring():
    context,result=image()
    low,powerhalf=image(factor=.5)
    constrained,denied=image(storage_gb=.001)
    assert result[1] is not None and powerhalf[1] is not None
    assert denied[1] is None and constrained.spacecraft_state.data_storage.stored_records == ()
    assert result[1].plan.sizing.stored_bits == 680299320
    # Same 60 s dark interval: mode difference 50 W / .9 efficiency / 60 h.
    assert low.spacecraft_state.battery.energy_wh-context.spacecraft_state.battery.energy_wh == pytest.approx(50/54,abs=4e-14)
    _,limited=image("H-E4")
    assert limited[1] is None  # 112 W exceeds 84.96 W battery bus output.
    _,half=image("H-E4",.5)
    assert half[1] is not None # 62 W is within that limit.


def test_exact_score_includes_infeasible_and_no_double_count():
    requests=[dict(request_id="a",credited_products=1),dict(request_id="b",credited_products=0)]
    assert weighted_score(requests,{"a":3.,"b":2.})["exact_score"] == "3/5"
    with pytest.raises(ValueError): weighted_score(requests[:1],{"a":3.,"b":2.})
    with pytest.raises(ValueError): weighted_score([requests[0],requests[0]],{"a":3.,"b":2.})


def evidence():
    return dict(status="completed-horizon",requests=[dict(request_id="r",credited_products=1)],selected_actions=["a"],
        boundaries=[dict(seconds=t,energy_wh=50.,temperatures_k={"bus":293.}) for t in (0,60)])


@pytest.mark.parametrize("failure",["energy","temperature","credit","incomplete","missing","nan"])
def test_numerical_report_does_not_hide_failure(failure):
    a,b=evidence(),evidence()
    if failure=="energy": b["boundaries"][-1]["energy_wh"]+=.101
    if failure=="temperature": b["boundaries"][-1]["temperatures_k"]["bus"]+=.101
    if failure=="credit": b["requests"][0]["credited_products"]=0
    if failure=="incomplete": b["status"]="incomplete"
    if failure=="missing": b["boundaries"]=[]
    if failure=="nan": b["boundaries"][-1]["energy_wh"]=float("nan")
    assert not qualify_pair(a,b,100.)["qualified"]


def test_numerical_comparison_aligns_physical_times_not_indices():
    a,b=evidence(),evidence()
    b["boundaries"].insert(1,dict(seconds=30,energy_wh=999.,temperatures_k={"bus":999.}))
    b["selected_actions"]=["different"]
    q=qualify_pair(a,b,100.)
    assert q["qualified"] and q["common_times_seconds"]==["0","60"] and not q["actions_equal"]


def test_internal_physical_samples_are_included_in_screen():
    a,b=evidence(),evidence()
    a["physical_samples"]=deepcopy(a["boundaries"])
    b["physical_samples"]=deepcopy(b["boundaries"])
    for r in (a,b):
        r["physical_samples"].insert(1,dict(seconds="1/3",energy_wh=50.,temperatures_k={"bus":293.}))
    b["physical_samples"][1]["temperatures_k"]["bus"]+=.2
    assert not qualify_pair(a,b,100.)["qualified"]


def test_manifest_order_is_not_identity_and_source_copies_are_independent():
    m=manifest(); m["allocations"]=dict(reversed(list(m["allocations"].items())))
    assert derive_hardware(load_manifest(json.dumps(m)),"D-E4")["working_energy_wh"]==86
    m["sources"]["BP8"]["title"]="changed local copy"
    assert manifest()["sources"]["BP8"]["title"]!="changed local copy"


def test_focused_causal_measurements_cover_all_active_field_owners():
    from examples.v5_ms_comparison_checks import checks
    report=checks()
    assert report["status"]=="passed"
    assert set(report["rows"])=={"sizing","storage","rate","generation","capacity","power-limit"}
