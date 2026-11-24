"""Task 05B synthetic multi-request rolling control, not hardware comparison."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

from examples.v5_ms_mission_demo import build_demo_state as mission_fixture
from ops_sim.v5.campaign_contract import (ReleasedMSRequest, MSOpportunity, CampaignForcing,
    BoundaryKnowledgeMode, RollingPolicy, MSCampaignProgram)
from ops_sim.v5.campaign_continuation import start_campaign, advance_campaign, campaign_summary
from ops_sim.v5.campaign_controller import CampaignBudgetExceeded
from ops_sim.v5.checkpoint import ThermalNodeStateSnapshot
from ops_sim.v5.communications import ServiceableGroundContact
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle
from ops_sim.v5.ids import ImagingRequestId, GroundTargetId, ObservationOpportunityId, GroundContactId
from ops_sim.v5.ms_product import MSFootprint, size_ms_grid


ROOT = Path(__file__).resolve().parents[1]


def campaign_from_manifest(inputs, program):
    """Task05C seam: caller supplies actual hardware, requests and contact scenario.

    No configuration-name branch, architecture tuning or fixture replacement.
    """
    return start_campaign(inputs, program)


def build_demo_state(*, denial=False, level=0):
    base = mission_fixture(level=level, hot=denial)
    p = base.program
    inputs = replace(base.context.inputs, common_world=replace(base.context.inputs.common_world, horizon_seconds=380))
    source = p.actions[0]
    requests, opportunities = [], []
    for name, priority, release, start, end, deadline, width in (
            ("a", 3., 100, 100, 160, 300, 10000.),
            ("b", 2., 100, 100, 160, 320, 3250.),
            ("c", 1., 125, 130, 200, 360, 6500.)):
        request = replace(p.product.request, request_id=ImagingRequestId("ms7-"+name),
            target_id=GroundTargetId("synthetic-"+name), priority_weight=priority)
        footprint = MSFootprint("synthetic-region-"+name, width, width)
        product = replace(p.product, request=request, capture_group="capture-"+name, footprint=footprint,
            acquisition_start_seconds=start, acquisition_end_seconds=end, delivery_deadline_seconds=deadline)
        grid = size_ms_grid(footprint, 6.5, 6.5, source.acquisition.sizing.captured_channels, 12)
        association = replace(source.acquisition, request=request, capture_group=product.capture_group, sizing=grid)
        candidate = source.timed.request.action.execution.candidate
        o = replace(candidate.maneuver_candidate.opportunity, opportunity_id=ObservationOpportunityId("op-"+name),
            request_id=request.request_id, window_start_seconds=start, window_end_seconds=end)
        candidate = replace(candidate, maneuver_candidate=replace(candidate.maneuver_candidate, opportunity=o),
            acquisition_input=replace(candidate.acquisition_input, effective_cross_track_width_m=width,
                                      effective_along_track_length_m=width))
        requests.append(ReleasedMSRequest(product, release))
        opportunities.append(MSOpportunity(candidate, association))
    tx, wait = p.actions[2].tx_inputs, p.actions[2].idle_inputs
    contacts = tuple(ServiceableGroundContact(GroundContactId(name), p.actions[2].contact.ground_station_id, start, end)
        for name, start, end in (("ms7-partial", 140, 180), ("ms7-completing", 200, 360)))
    nodes = tuple(n.node_id for n in inputs.spacecraft_configuration.thermal.network.nodes)
    estimated = ()
    if denial:
        payload = inputs.spacecraft_configuration.thermal.network.payload_node_id
        nodes = tuple(n for n in nodes if n != payload)
        estimated = (ThermalNodeStateSnapshot(payload, 300.),)
    knowledge = BoundaryKnowledgeMode("idealized-boundary-telemetry-v1", nodes, estimated,
        "Zero latency and perfect action/service acknowledgement. " +
        ("Payload temperature is unobserved and explicitly estimated at 300 K at each boundary; actual initial 330 K."
         if denial else "All model temperatures observed; no real communications or hardware accuracy claim."))
    program = MSCampaignProgram(7, p.initial_checkpoint, p.initial_attitude, tuple(requests), tuple(opportunities), contacts,
        (CampaignForcing(100, 200, wait, tx.transmitter), CampaignForcing(200, 380, wait, tx.transmitter)),
        p.policy, p.integration, RollingPolicy(), knowledge,
        (p.assumptions[0], p.assumptions[2], "Rolling greedy common policy, explicit boundary telemetry, held pointing, no world events.",
         "Same accepted synthetic Task05A hardware fixture; level is functional only, no campaign qualification."))
    return campaign_from_manifest(inputs, program)


def run(state, *, stop_after=None):
    reason = None
    while state.context.simulation_time_seconds < state.context.inputs.common_world.horizon_seconds:
        if stop_after is not None and len(state.memory.decisions) >= stop_after:
            reason = "requested-boundary-pause"
            break
        try:
            state = advance_campaign(state)
        except CampaignBudgetExceeded as error:
            reason = str(error)
            break
    return state, reason


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--bundle-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--denial", action="store_true")
    args = parser.parse_args(argv)
    started = perf_counter()
    state = (build_demo_state(denial=args.denial) if args.resume is None else
        ExperimentBundle.from_json(args.resume.read_text(encoding="utf-8")).restore(repository_root=ROOT))
    if args.stop_after is not None and args.stop_after < len(state.memory.decisions):
        parser.error("stop-after cannot precede the restored boundary")
    state, reason = run(state, stop_after=args.stop_after)
    report = campaign_summary(state)
    report["stop_reason"] = reason
    if args.bundle_output:
        args.bundle_output.write_text(create_bundle(state, repository_root=ROOT).to_json(), encoding="utf-8")
    report["execution_wall_seconds"] = perf_counter()-started
    report["timing_scope"] = "example including validation/replay/optional bundle; not a performance benchmark"
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 2 if reason is not None and reason != "requested-boundary-pause" else 0


if __name__ == "__main__":
    raise SystemExit(main())
