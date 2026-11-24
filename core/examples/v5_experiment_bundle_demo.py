"""Executable Task 02 synthetic script/restart demonstration, not a controller.

Reuses synthetic V5.4 fixture definitions. Downlink retains V5.5 bookkeeping
semantics: it advances time without concurrent EPS/thermal evolution.
"""

import argparse
from dataclasses import replace
import json
from math import cos, radians, sin
from pathlib import Path

from examples import v54_integrated_storage_demo as storage_demo
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.communications import ServiceableGroundContact
from ops_sim.v5.continuation import (
    ContinuationMemory, ContinuationProgram, ContinuationState,
    DownlinkAction, ImagingAction, advance_continuation,
)
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.ids import AcquisitionDataRecordId, GroundContactId, GroundStationId, TelemetrySnapshotId
from ops_sim.v5.knowledge import GroundKnowledgeState, TelemetrySnapshot


ROOT = Path(__file__).resolve().parents[1]


def build_demo_state():
    context = storage_demo._build_demo_context()
    configuration = context.inputs.spacecraft_configuration
    communications = replace(configuration.communications, nominal_downlink_data_rate_bps=storage_demo._parameter(
        "communications.nominal-downlink-data-rate", "bit/s", 9000.0 / 23,
    ))
    context.inputs = replace(context.inputs, spacecraft_configuration=replace(configuration, communications=communications))
    context.ground_knowledge_state = GroundKnowledgeState(
        TelemetrySnapshot(TelemetrySnapshotId("task02-origin-telemetry"), 90, 100,
                          context.spacecraft_state.battery.energy_wh,
                          context.spacecraft_state.propulsion.delta_v_remaining_m_per_s,
                          context.spacecraft_state.onboard.operational_mode), (),
    )

    def image(action_id, record_name, start, index, angle):
        execution = storage_demo._scheduled_execution(start, index, "task02")
        maneuver = execution.candidate.maneuver_candidate
        direction = CommonFrameBoresightDirection(maneuver.common_frame_boresight.frame_id, sin(radians(angle)), 0.0, cos(radians(angle)))
        execution = replace(execution, candidate=replace(execution.candidate, maneuver_candidate=replace(maneuver, common_frame_boresight=direction)))
        return ImagingAction(
            action_id, execution, AcquisitionDataRecordId(record_name),
            storage_demo._environment(), storage_demo._routing_config(),
            storage_demo._thermal_inputs(context), storage_demo._external_heat_sources(context), None,
        )

    def downlink(action_id, record_name, start):
        return DownlinkAction(action_id, ServiceableGroundContact(
            GroundContactId(action_id), GroundStationId("task02-synthetic-station"), start, start + 23,
        ), AcquisitionDataRecordId(record_name))

    previous = storage_demo._previous_execution()
    program = ContinuationProgram(
        1, 100, context.diagnostics.completed_steps, previous,
        (
            image("image-a", "task02-a", 100, 1, 0.0),
            downlink("partial-a", "task02-a", 123),
            image("image-b", "task02-b", 146, 2, 5.0),
            downlink("complete-a", "task02-a", 169),
            downlink("partial-b", "task02-b", 192),
            downlink("complete-b", "task02-b", 215),
        ),
        ("Synthetic V5.4 hardware/forcing; no spacecraft calibration claim.",
         "Explicit fixed thermal sink temperatures and per-action forcing; no external files.",
         "Contacts are declared serviceable inputs, not geometric or RF proofs.",
         "V5.5 downlink advances time without concurrent EPS/thermal evolution.",
         "Ordered script choices; no mission controller, events, queues or RNG."),
    )
    return ContinuationState(context, program, ContinuationMemory((), previous))


def summarize(state):
    checkpoint = CheckpointState.from_context(state.context).to_dict()
    deliveries = state.context.ground_data_delivery_state
    records = state.context.spacecraft_state.data_storage.stored_records
    return {
        "input_digest": experiment_input_digest(state.context.inputs, state.program),
        "checkpoint": checkpoint, "memory": canonical_content(state.memory),
        "decisions": list(state.memory.executed_action_ids),
        "metrics": {"clock_seconds": state.context.simulation_time_seconds,
                    "completed_steps": state.context.diagnostics.completed_steps,
                    "delivered_equivalent_bits": sum(x.record.stored_equivalent_bits for x in deliveries.completed_deliveries),
                    "onboard_equivalent_bits": sum(x.stored_equivalent_bits for x in records),
                    "partial_transfers": len(deliveries.partial_transfers)},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--bundle-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.resume is None:
        state = build_demo_state()
    else:
        state = ExperimentBundle.from_json(args.resume.read_text(encoding="utf-8")).restore(repository_root=ROOT)
    stop = len(state.program.actions) if args.stop_after is None else args.stop_after
    if not len(state.memory.executed_action_ids) <= stop <= len(state.program.actions):
        parser.error("stop-after must be between the current cursor and program end")
    while len(state.memory.executed_action_ids) < stop:
        state = advance_continuation(state)
    if args.bundle_output is not None:
        args.bundle_output.write_text(create_bundle(state, repository_root=ROOT).to_json(), encoding="utf-8")
    args.output.write_text(json.dumps(summarize(state), ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
