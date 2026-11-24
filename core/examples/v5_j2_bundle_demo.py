"""Task 06B fresh-process J2 reconstruction using existing program version 1.

Synthetic F3 pilot inputs and the unchanged Task 02 imaging/downlink script.
The script's legacy downlink does not evolve EPS/thermal state. Orbit is queried
separately, never used to authorize these declared opportunities or contacts.
Write all outputs outside the repository. See V5_J2_BINDING.md for commands.
"""

import argparse
from dataclasses import replace
from pathlib import Path

from examples.v5_experiment_bundle_demo import ROOT, build_demo_state, summarize
from examples.v5_j2_enclosure_pilot import inputs as pilot_trajectory
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.context import evaluate_context_j2_enclosure, with_j2_coast_orbit
from ops_sim.v5.continuation import ContinuationState, advance_continuation
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle
from ops_sim.v5.experiment_codec import (
    canonical_content, decode_content, json_text, object_fields, parse_json,
)
from ops_sim.v5.orbit_j2 import J2RK4SolverConfig
from ops_sim.v5.orbit_j2_binding import J2CoastOrbitInputs
from ops_sim.v5.orbit_j2_enclosure import J2EnclosurePolicy


def build_j2_demo_state():
    state = build_demo_state()
    coast = J2CoastOrbitInputs(pilot_trajectory(False), J2RK4SolverConfig(10, 256),
                              J2EnclosurePolicy(10, 256, 6000000, 50, 12))
    context = replace(state.context, inputs=with_j2_coast_orbit(state.context.inputs, coast))
    return ContinuationState(context, state.program, state.memory)


def enclosure_evidence(context):
    """Report-only evidence: never accepted by a restore path as authority."""
    result = evaluate_context_j2_enclosure(context)
    return {
        "status": result.status, "reason": result.reason,
        "clock_seconds": context.simulation_time_seconds,
        "anchor_seconds": result.trajectory.initial_state.position.instant.elapsed_seconds,
        "policy_version": result.policy_version,
        "nominal_state": canonical_content(result.nominal_state),
        "endpoint_intervals": None if result.endpoint_intervals is None else
            [[str(lo), str(hi)] for lo, hi in result.endpoint_intervals],
        "position_error_bound_m": result.position_error_bound_m,
        "velocity_error_bound_m_per_s": result.velocity_error_bound_m_per_s,
        "enclosure_steps": result.enclosure_steps, "nominal_steps": result.nominal_steps,
        "picard_attempts": result.picard_attempts,
    }


def summary(state):
    return {**summarize(state), "j2": enclosure_evidence(state.context)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    resume = parser.add_mutually_exclusive_group()
    resume.add_argument("--resume", type=Path, help="self-contained ExperimentBundle")
    resume.add_argument("--resume-schema", type=Path, help="schema-5 checkpoint plus existing program/memory")
    parser.add_argument("--inputs", type=Path, help="matching external immutable inputs for schema-5 restore")
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--bundle-output", type=Path)
    parser.add_argument("--schema-output", type=Path)
    parser.add_argument("--inputs-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (args.resume_schema is not None) != (args.inputs is not None):
        parser.error("--resume-schema requires --inputs (only on that path)")
    if args.resume is not None:
        state = ExperimentBundle.from_json(args.resume.read_text(encoding="utf-8")).restore(repository_root=ROOT)
    elif args.resume_schema is not None:
        inputs = decode_content(parse_json(args.inputs.read_text(encoding="utf-8")))
        saved = object_fields(parse_json(args.resume_schema.read_text(encoding="utf-8")),
                              ("checkpoint", "program", "memory"))
        state = ContinuationState(CheckpointState.from_dict(saved["checkpoint"]).restore(inputs),
                                  decode_content(saved["program"]), decode_content(saved["memory"]))
    else:
        state = build_j2_demo_state()
    initial = summary(state)
    stop = len(state.program.actions) if args.stop_after is None else args.stop_after
    if not len(state.memory.executed_action_ids) <= stop <= len(state.program.actions):
        parser.error("stop-after must be between current cursor and program end")
    while len(state.memory.executed_action_ids) < stop:
        state = advance_continuation(state)
    if args.bundle_output is not None:
        args.bundle_output.write_text(create_bundle(state, repository_root=ROOT).to_json(), encoding="utf-8")
    if args.schema_output is not None:
        args.schema_output.write_text(json_text({
            "checkpoint": CheckpointState.from_context(state.context).to_dict(),
            "program": canonical_content(state.program), "memory": canonical_content(state.memory),
        }), encoding="utf-8")
    if args.inputs_output is not None:
        args.inputs_output.write_text(json_text(canonical_content(state.context.inputs)), encoding="utf-8")
    args.output.write_text(json_text({"initial": initial, "final": summary(state)}), encoding="utf-8")


if __name__ == "__main__":
    main()
