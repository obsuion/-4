"""Independent grid arithmetic and mission credit from real contact services."""
from dataclasses import replace
from fractions import Fraction
from math import nextafter, inf

import pytest

from examples.v5_contact_execution_demo import contact_case
from ops_sim.v5.contact_execution import execute_contact_plan, ConsumedContacts
from ops_sim.v5.ids import ImagingRequestId, GroundTargetId
from ops_sim.v5.integration_time import IntegrationPolicy
from ops_sim.v5.ms_product import (MSFootprint, size_ms_grid, MSProductSpec, MSAcquisitionPlan,
    MSAcquisitionEvidence, REQUIRED_MS_CHANNELS, assess_ms_product)
from ops_sim.v5.observation import ImagingRequest
from ops_sim.v5.payload import OpticalAcquisitionChannelSelection
from ops_sim.v5.state import DataStorageState


@pytest.mark.parametrize("width,length,nx,ny", [
    (13., 19.5, 2, 3), (nextafter(13., inf), 19.5, 3, 3),
    (nextafter(13., 0.), 19.5, 2, 3), (10000., 10000., 1539, 1539),
    (1., 1., 1, 1),
])
def test_exact_cell_cover_ceiling_without_epsilon(width, length, nx, ny):
    g = size_ms_grid(MSFootprint("rect", width, length), 6.5, 6.5, REQUIRED_MS_CHANNELS, 12)
    assert (g.nx, g.ny, g.stored_bits) == (nx, ny, nx*ny*4*12)
    assert Fraction(g.nx-1)*Fraction(6.5) < Fraction(width) <= Fraction(g.nx)*Fraction(6.5)
    assert Fraction(g.ny-1)*Fraction(6.5) < Fraction(length) <= Fraction(g.ny)*Fraction(6.5)


@pytest.mark.parametrize("bad", [True, 0, -1, inf, float("nan"), "6.5"])
def test_bad_spacing_rejected(bad):
    with pytest.raises((TypeError, ValueError)):
        size_ms_grid(MSFootprint("rect", 13., 13.), bad, 6.5, REQUIRED_MS_CHANNELS, 12)


@pytest.mark.parametrize("change", [dict(nx=3), dict(stored_bits=191), dict(version=2),
    dict(bits_per_sample=12.), dict(captured_channels=("B","G","R","PAN")), dict(nx=True)])
def test_sizing_persistence_is_recomputed_not_trusted(change):
    g = size_ms_grid(MSFootprint("rect", 13., 13.), 6.5, 6.5, REQUIRED_MS_CHANNELS, 12)
    with pytest.raises((TypeError, ValueError)):
        replace(g, **change)


def delivered(*, duration=10):
    c, p, policy = contact_case(bits=(96,), partials=(), rate=48, duration=duration)
    record = replace(c.spacecraft_state.data_storage.stored_records[0],
                     channel_selection=OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY)
    c.spacecraft_state.data_storage = DataStorageState((record,))
    request = ImagingRequest(record.imaging_request_id, GroundTargetId("target"), 2.)
    footprint = MSFootprint("rect", 13., 6.5)
    plan = MSAcquisitionPlan(1, request, "capture", size_ms_grid(footprint, 6.5, 6.5, REQUIRED_MS_CHANNELS, 12),
                             "Synthetic four-band MS-only capability.")
    evidence = MSAcquisitionEvidence(record, plan)
    product = MSProductSpec(1, request, "capture", REQUIRED_MS_CHANNELS, footprint, 0, 50, 6.5, 6.5, 105)
    result = execute_contact_plan(c, p, consumed_contacts=ConsumedContacts(()), policy=policy, integration=IntegrationPolicy(1))
    return c, product, evidence, result.outcome


@pytest.mark.parametrize("deadline,credited", [(101,0),(102,1),(105,1),(110,1)])
def test_exact_completion_not_full_contact_end_and_inclusive_deadline(deadline, credited):
    c, product, evidence, outcome = delivered()
    product = replace(product, delivery_deadline_seconds=deadline)
    a = assess_ms_product(product, (evidence,), c.ground_data_delivery_state, (outcome,), 110)
    assert a.credited_products == credited
    assert outcome.services[0].completion_time_seconds == 102
    assert c.ground_data_delivery_state.completed_deliveries[0].completing_contact.end_time_seconds == 110
    if credited:
        assert a.completion_time_seconds == Fraction(102)
        assert assess_ms_product(product, (evidence,), c.ground_data_delivery_state, (outcome,), 120) == a
    else: assert "late-delivery" in a.reasons


def test_partial_only_expiry_and_missing_service_are_not_success():
    c, p, e, o = delivered(duration=1)
    a = assess_ms_product(p, (e,), c.ground_data_delivery_state, (o,), 105)
    assert not a.credited_products and "not-delivered" in a.reasons and a.status == "expired"
    c, p, e, o = delivered()
    a = assess_ms_product(p, (e,), c.ground_data_delivery_state, (), 110)
    assert not a.credited_products and "missing-completion-service" in a.reasons
    with pytest.raises(ValueError, match="duplicate completing"):
        assess_ms_product(p, (e,), c.ground_data_delivery_state, (o,o), 110)


@pytest.mark.parametrize("change,reason", [
    ("request","wrong-request"), ("target","wrong-target"), ("group","incompatible-capture-group"),
    ("footprint","incompatible-footprint"), ("sampling","sampling-criterion-failed"),
    ("window","outside-acquisition-window"), ("channel","missing-required-channels"),
])
def test_wrong_product_inputs_cannot_earn_credit(change, reason):
    c, p, e, o = delivered()
    if change == "request": p = replace(p, request=replace(p.request, request_id=ImagingRequestId("other")))
    if change == "target": p = replace(p, request=replace(p.request, target_id=GroundTargetId("other")))
    if change == "group": p = replace(p, capture_group="other")
    if change == "footprint": p = replace(p, footprint=replace(p.footprint, region_id="other"))
    if change == "sampling": p = replace(p, maximum_spacing_x_m=6.4)
    if change == "window": p = replace(p, acquisition_start_seconds=20)
    if change == "channel": e = replace(e, plan=replace(e.plan, sizing=replace(e.plan.sizing, captured_channels=("B","G","R","X"))))
    a = assess_ms_product(p, (e,), c.ground_data_delivery_state, (o,), 110)
    assert a.credited_products == 0 and reason in a.reasons


def test_finite_contact_domain_and_fifth_band_accounting():
    f = MSFootprint("rect",10000.,10000.)
    a = size_ms_grid(f,6.5,6.5,REQUIRED_MS_CHANNELS,12)
    b = size_ms_grid(f,6.5,6.5,(*REQUIRED_MS_CHANNELS,"RE"),12)
    assert a.stored_bits == 113689008 and b.stored_bits == 142111260
    assert b.stored_bits*4 == a.stored_bits*5
    with pytest.raises(ValueError, match="domain"):
        size_ms_grid(MSFootprint("huge",1e20,1e20),1.,1.,REQUIRED_MS_CHANNELS,12)


@pytest.mark.parametrize("second_start,credit", [(1,1),(2,0)])
def test_required_bands_cannot_be_assembled_across_capture_times(second_start,credit):
    c,p,policy=contact_case(bits=(48,48),partials=(),rate=48,duration=10)
    records=c.spacecraft_state.data_storage.stored_records
    request=ImagingRequest(records[0].imaging_request_id,GroundTargetId('target'),1.)
    records=tuple(replace(r,imaging_request_id=request.request_id,
        scheduled_start_seconds=1 if i==0 else second_start,
        channel_selection=OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY) for i,r in enumerate(records))
    c.spacecraft_state.data_storage=DataStorageState(records)
    footprint=MSFootprint('rect',13.,6.5)
    evidence=tuple(MSAcquisitionEvidence(r,MSAcquisitionPlan(1,request,'capture',
        size_ms_grid(footprint,6.5,6.5,channels,12),'Synthetic co-temporal band-record fixture.'))
        for r,channels in zip(records,(('B','G'),('R','NIR'))))
    spec=MSProductSpec(1,request,'capture',REQUIRED_MS_CHANNELS,footprint,0,50,6.5,6.5,105)
    result=execute_contact_plan(c,p,consumed_contacts=ConsumedContacts(()),policy=policy,integration=IntegrationPolicy(1))
    a=assess_ms_product(spec,evidence,c.ground_data_delivery_state,(result.outcome,),110)
    assert a.credited_products==credit
    if credit:assert a.completion_time_seconds==102 and len(a.credited_record_ids)==2
    else:assert 'incompatible-capture-time' in a.reasons
