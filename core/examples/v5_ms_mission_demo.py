"""Task05A synthetic fixed MS acquisition -> partial -> completed delivery.

No flight calibration, rolling controller or campaign-step qualification.
The 6.5 m grid is an explicit verification input, not a mission standard.
"""

import argparse
from dataclasses import replace
import json
from pathlib import Path

from examples import v5_coupled_downlink_demo as physical
from examples import v5_operational_protection_demo as protection
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.communications import ServiceableGroundContact
from ops_sim.v5.contact_execution import ContactPlan, ConsumedContacts
from ops_sim.v5.continuation import ImagingAction
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.ids import (AcquisitionDataRecordId, ADCSBoresightFrameId, GroundContactId,
                           GroundStationId, GroundTargetId, ImagingRequestId, ObservationOpportunityId)
from ops_sim.v5.imaging_execution import ScheduledObservationAcquisitionExecution
from ops_sim.v5.imaging_feasibility import ObservationAcquisitionCandidate
from ops_sim.v5.imaging_resources import AcquisitionEPSIntervalEnvironment
from ops_sim.v5.integration_time import IntegrationPolicy
from ops_sim.v5.ms_acquisition import InitialAttitudeEvidence
from ops_sim.v5.ms_continuation import MSMissionProgram, MSPhysicalRequest, start_ms_mission, advance_ms_mission
from ops_sim.v5.ms_product import MSFootprint, MSProductSpec, MSAcquisitionPlan, size_ms_grid, REQUIRED_MS_CHANNELS
from ops_sim.v5.observation import ImagingRequest, ObservationOpportunity, ObservationPointing
from ops_sim.v5.observation_feasibility import ObservationManeuverCandidate
from ops_sim.v5.operational_protection import ProtectedRequest, StandbyAction, StandbyInputs
from ops_sim.v5.payload import OpticalAcquisitionInput, OpticalAcquisitionChannelSelection
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.substepped_execution import TimedRequest


ROOT = Path(__file__).resolve().parents[1]


def parameter(p, value):
    return replace(p, value=value, provenance=replace(p.provenance,
        rationale="Synthetic Task05A verification coefficient, not flight hardware evidence."))


def build_demo_state(*, channels=REQUIRED_MS_CHANNELS, deadline=229, level=2, hot=False,
                     width_m=10000., length_m=10000., spacing_m=6.5):
    c = physical.configure_physics(physical.storage._build_demo_context())
    cfg = c.inputs.spacecraft_configuration
    optical = cfg.payload.optical_acquisition
    optical = replace(optical, simultaneous_pan_and_multispectral=False,
        multispectral_reference_sample_spacing_m=parameter(optical.multispectral_reference_sample_spacing_m, spacing_m),
        multispectral_band_count=parameter(optical.multispectral_band_count, float(len(channels))),
        acquisition_bits_per_sample=parameter(optical.acquisition_bits_per_sample, 12.),
        acquisition_power_w=parameter(optical.acquisition_power_w, 20.))
    c.inputs = replace(c.inputs, spacecraft_configuration=replace(cfg,
        payload=replace(cfg.payload, optical_acquisition=optical),
        storage=replace(cfg.storage, usable_capacity_gb=parameter(cfg.storage.usable_capacity_gb, 1.)),
        communications=replace(cfg.communications,
            nominal_downlink_data_rate_bps=parameter(cfg.communications.nominal_downlink_data_rate_bps, 1000000.))))
    if hot:
        for n in c.spacecraft_state.thermal.node_states:
            if n.node_id.value == "payload": n.temperature_k = 330.
    request = ImagingRequest(ImagingRequestId("task05a-ms"), GroundTargetId("synthetic-target"), 1.)
    footprint = MSFootprint("synthetic-rectangular-region", width_m, length_m)
    grid = size_ms_grid(footprint, spacing_m, spacing_m, channels, 12)
    product = MSProductSpec(1, request, "capture-1", REQUIRED_MS_CHANNELS, footprint, 100, 110, spacing_m, spacing_m, deadline)
    association = MSAcquisitionPlan(1, request, "capture-1", grid,
        "Synthetic MS-only mode with explicitly declared channel identities; no inference that a real instrument disables PAN/bands.")
    direction = CommonFrameBoresightDirection(ADCSBoresightFrameId("synthetic-fixed-common-frame"), 0., 0., 1.)
    initial = InitialAttitudeEvidence(100, direction,
        "Synthetic known settled boresight at origin; held between actions; no prior acquisition or initial image.")
    opportunity = ObservationOpportunity(ObservationOpportunityId("task05a-opportunity"), request.request_id,
        100, 110, 10, ObservationPointing(0., 0.))
    execution = ScheduledObservationAcquisitionExecution(ObservationAcquisitionCandidate(
        ObservationManeuverCandidate(opportunity, direction), OpticalAcquisitionInput(width_m, length_m, 10,
            OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY)), 100)
    tx = replace(physical.physical_inputs(c, sunlit=False),
        baseline_loads=PowerLoadBreakdown(12., 0., 0., 0., 0., 0., 0.), solar_degradation_forcing=None)
    wait = StandbyInputs(tx.baseline_loads, tx.sunlit, tx.incidence_angle_deg, tx.routing_config,
        tx.thermal_inputs, tx.external_heat_sources, None, "Synthetic positive 12 W essential baseline, TX/payload off.")
    record_id = AcquisitionDataRecordId("task05a-ms-record")
    image = ImagingAction("acquire-ms", execution, record_id,
        AcquisitionEPSIntervalEnvironment(False, 0., tx.baseline_loads), tx.routing_config,
        tx.thermal_inputs, tx.external_heat_sources, None)
    def idle(start, end, name):
        return MSPhysicalRequest(TimedRequest(start, end, ProtectedRequest(StandbyAction(name), wait)), None)
    def contact(start, end, name):
        return ContactPlan(ServiceableGroundContact(GroundContactId(name), GroundStationId("synthetic-station"),
            start, end), (record_id,), tx, wait)
    actions = (MSPhysicalRequest(TimedRequest(100, 110, ProtectedRequest(image, wait)), association),
        idle(110, 112, "pre-contact-idle"), contact(112, 152, "partial-contact"),
        idle(152, 155, "between-contacts-idle"), contact(155, 300, "completion-contact"))
    program = MSMissionProgram(6, product, CheckpointState.from_context(c), initial, ConsumedContacts(()),
        protection.policy(c), IntegrationPolicy(level), actions, (
            "Synthetic MS mode, spectral mapping, powers and rectangular coverage proxy; no calibrated hardware/orbit claim.",
            "Fixed physical timeline and declared serviceable contacts; no rolling controller, RF proof or hidden time advancement.",
            "Integer cell sizing with fractional edge cells charged in full; no compression/packet overhead or mosaicking.",
            "Explicit Euler/sampled protection; this level is a functional fixture, not a globally qualified campaign policy.",
        ))
    return start_ms_mission(c.inputs, program)


def summarize(state):
    return {"input_digest": experiment_input_digest(state.context.inputs, state.program),
        "checkpoint": CheckpointState.from_context(state.context).to_dict(),
        "memory": canonical_content(state.memory),
        "metrics": {"clock_seconds": state.context.simulation_time_seconds,
            "outer_steps": state.context.diagnostics.completed_steps,
            "acquisitions": len(state.memory.acquisitions),
            "onboard_records": len(state.context.spacecraft_state.data_storage.stored_records),
            "partial_transfers": len(state.context.ground_data_delivery_state.partial_transfers),
            "consumed_contacts": len(state.memory.consumed_contacts.contacts),
            "credited_products": state.memory.assessment.credited_products,
            "credited_priority_weight": state.program.product.request.priority_weight * state.memory.assessment.credited_products,
            "completion_seconds": str(state.memory.assessment.completion_time_seconds),
            "status": state.memory.assessment.status, "reasons": state.memory.assessment.reasons}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--bundle-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    state = (build_demo_state() if args.resume is None else
        ExperimentBundle.from_json(args.resume.read_text(encoding="utf-8")).restore(repository_root=ROOT))
    stop = len(state.program.actions) if args.stop_after is None else args.stop_after
    if not len(state.memory.outcomes) <= stop <= len(state.program.actions):
        parser.error("stop-after must be a remaining completed-action boundary")
    while len(state.memory.outcomes) < stop:
        state = advance_ms_mission(state)
    if args.bundle_output:
        args.bundle_output.write_text(create_bundle(state, repository_root=ROOT).to_json(), encoding="utf-8")
    args.output.write_text(json.dumps(summarize(state), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
