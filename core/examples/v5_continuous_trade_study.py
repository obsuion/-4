"""Task05F-A bounded readiness runner with continuous physical state and evidence.

Run with python -B -m examples.v5_continuous_trade_study --help. Outputs must be
outside the checkout. The immutable world is 30 days; this runner stops at no
more than 72 hours and does not authorize a month production campaign.
"""

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

from ops_sim.v5.continuous_trade import (
    ContinuousSpec, HORIZON, PERIOD, advance_continuous, start_continuous, summary,
)
from ops_sim.v5.continuous_trade_io import (
    EvidenceStream, input_fingerprint, restore_continuous, runtime_fingerprint,
    verify_evidence, write_checkpoint,
)
from ops_sim.v5.design_trade_design import design_record
from ops_sim.v5.experiment_codec import canonical_content, parse_json


ROOT = Path(__file__).resolve().parents[1]
READINESS_LIMIT_SECONDS = 259200


def stamp():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      indent=2) + "\n"


def digest(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def sealed(value):
    return dict(value, sha256=digest(value))


def read_sealed(path):
    value = parse_json(Path(path).read_text(encoding="utf-8"))
    if type(value) is not dict or "sha256" not in value:
        raise ValueError("missing integrity envelope: " + str(path))
    claimed = value.pop("sha256")
    if claimed != digest(value):
        raise ValueError("integrity envelope mismatch: " + str(path))
    return value


def atomic_text(path, text):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def source_snapshot():
    """All production files plus this entry point, outside the advance loop."""
    paths = sorted((ROOT / "ops_sim").rglob("*.py")) + [Path(__file__).resolve()]
    hashes = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in paths}
    return {"files": hashes, "sha256": digest(hashes)}


def peak_resident_bytes():
    """OS process peak resident memory, including startup and any earlier work."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                    "PagefileUsage", "PeakPagefileUsage")]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counters.PeakWorkingSetSize)
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def output_bytes(directory):
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())


def append_line(stream, value):
    stream.write(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
    stream.flush()


def checked_output(value):
    directory = Path(value).resolve()
    if directory == ROOT or ROOT in directory.parents:
        raise ValueError("readiness evidence must be outside the repository")
    return directory


def checkpoint_at(directory, state, evidence):
    now = state.context.simulation_time_seconds
    archive = directory / "checkpoints" / (f"at-{now:010d}-a{state.advances:08d}.json")
    write_checkpoint(archive, state, evidence=evidence)
    # Copy already validated bytes; do not reconstruct immutable inputs twice.
    atomic_text(directory / "checkpoint.json", archive.read_text(encoding="utf-8"))
    return archive


def matching_manifest(directory, spec, source, runtime):
    manifest = read_sealed(directory / "manifest.json")
    if (manifest.get("version") != 1 or manifest.get("spec") != spec.to_dict()
            or manifest.get("source") != source or manifest.get("runtime") != runtime):
        raise ValueError("existing run differs in immutable spec, source or runtime; use a new output directory")
    inputs = directory / "inputs.json"
    if hashlib.sha256(inputs.read_bytes()).hexdigest() != manifest["inputs_file_sha256"]:
        raise ValueError("saved immutable input evidence differs from manifest")
    return manifest


def checked_prior(directory, manifest):
    previous = read_sealed(directory / "result.json")
    if previous.get("manifest_sha256") != digest(manifest):
        raise ValueError("previous result is not bound to this manifest")
    return previous


def reused_result(directory, spec, source, runtime, stop):
    manifest = matching_manifest(directory, spec, source, runtime)
    result = checked_prior(directory, manifest)
    if result.get("status") != "completed-pilot" or result.get("requested_stop_seconds") != stop:
        raise ValueError("existing output is not this completed stop; use --resume to continue a checkpoint")
    checkpoint = directory / "checkpoint.json"
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != result["checkpoint_sha256"]:
        raise ValueError("completed run checkpoint differs from result")
    state = restore_continuous(checkpoint.read_text(encoding="utf-8"))
    if (state.spec != spec or state.context.simulation_time_seconds != stop
            or input_fingerprint(state) != manifest["input_digest"]
            or (state.event_count, state.event_digest) !=
            (result["summary"]["event_count"], result["summary"]["event_digest"])):
        raise ValueError("completed checkpoint differs from the requested case")
    verify_evidence(directory / "events.jsonl", event_count=state.event_count, event_digest=state.event_digest)
    return result


def run_case(args):
    started = time.perf_counter()
    started_utc = stamp()
    spec = ContinuousSpec(args.design, workload=args.workload, numerical=args.numerical)
    directory = checked_output(args.output)
    source, runtime = source_snapshot(), runtime_fingerprint()
    if directory.exists() and args.resume is None:
        result = reused_result(directory, spec, source, runtime, args.stop_seconds)
        print(encode({"status": result["status"], "reused": True, "output": str(directory),
                      "seconds": args.stop_seconds, "elapsed_seconds": result["elapsed_seconds"]}), flush=True)
        return 0
    if args.resume is not None and not directory.is_dir():
        raise ValueError("resume requires the existing evidence directory")
    state, evidence, manifest = None, None, None
    previous = None
    status, reason = "failed", "initialization-failed"
    failure = None
    session_number = 1
    prior_elapsed = 0.
    prior_peak = 0
    origin_metrics = None
    # All resume identity checks precede any output replacement or log append.
    if args.resume is not None:
        manifest = matching_manifest(directory, spec, source, runtime)
        previous = checked_prior(directory, manifest)
        resume = Path(args.resume).resolve()
        if directory not in resume.parents or not resume.is_file():
            raise ValueError("resume checkpoint must belong to this evidence directory")
        checkpoint_text = resume.read_text(encoding="utf-8")
        if hashlib.sha256(resume.read_bytes()).hexdigest() != previous["checkpoint_sha256"]:
            raise ValueError("resume must preserve the latest recorded execution and origin metrics")
        state = restore_continuous(checkpoint_text)
        if state.spec != spec or input_fingerprint(state) != manifest["input_digest"]:
            raise ValueError("restored input differs from requested immutable case")
        if args.stop_seconds <= state.context.simulation_time_seconds:
            raise ValueError("resume stop must be later than the checkpoint clock")
        prior_elapsed = previous["elapsed_seconds"]
        prior_peak = previous["peak_resident_bytes"]
        session_number = previous["session_number"] + 1
        origin_metrics = previous.get("origin_metrics") or {
            "seconds": previous["summary"]["seconds"], "status": previous["status"],
            "elapsed_seconds": prior_elapsed, "peak_resident_bytes": prior_peak,
            "output_bytes": previous["output_bytes"],
            "result_sha256": digest(previous), "checkpoint_sha256": previous["checkpoint_sha256"]}
        evidence = EvidenceStream(directory / "events.jsonl", event_count=state.event_count,
                                  event_digest=state.event_digest, resume=True)
    else:
        directory.mkdir(parents=True, exist_ok=False)
    (directory / "checkpoints").mkdir(exist_ok=True)
    (directory / "sessions").mkdir(exist_ok=True)
    stream_mode = "a" if args.resume is not None else "x"
    with (directory / "run.log").open(stream_mode, encoding="utf-8", newline="\n") as log:
        try:
            if args.resume is None:
                state = start_continuous(spec)
                input_digest = input_fingerprint(state)
                input_text = encode({"input_digest": input_digest,
                    "inputs": canonical_content(state.context.inputs),
                    "program": canonical_content(state.program),
                    "template_spec": state.template_spec.to_dict(), "design": design_record(state.design)})
                atomic_text(directory / "inputs.json", input_text)
                manifest = {"version": 1, "created_utc": started_utc, "spec": spec.to_dict(),
                    "input_digest": input_digest, "source": source, "runtime": runtime,
                    "inputs_file_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
                    "initial_stop_seconds": args.stop_seconds, "readiness_limit_seconds": READINESS_LIMIT_SECONDS,
                    "memory_measure": "OS process peak resident bytes; includes startup; resumed peak is maximum across processes",
                    "wall_measure": "sum of measured invocation seconds; excludes time between resume invocations",
                    "qualification": "engineering pilot only; no month result or numerical qualification implied"}
                atomic_text(directory / "manifest.json", encode(sealed(manifest)))
            session_start_seconds = state.context.simulation_time_seconds
            append_line(log, {"kind": "session-start", "utc": started_utc, "session": session_number,
                "start_seconds": session_start_seconds, "requested_stop_seconds": args.stop_seconds,
                "wall_budget_seconds": args.wall_budget_seconds, "resume": args.resume})
            if evidence is None:
                evidence = EvidenceStream(directory / "events.jsonl", event_count=state.event_count,
                                          event_digest=state.event_digest)
            if args.resume is None:
                checkpoint_at(directory, state, evidence)
            cycle_started = time.perf_counter()
            cycle_start_seconds = state.context.simulation_time_seconds
            with (directory / "cycles.jsonl").open(stream_mode, encoding="utf-8", newline="\n") as cycles:
                while state.context.simulation_time_seconds < args.stop_seconds:
                    if time.perf_counter() - started >= args.wall_budget_seconds:
                        status, reason = "incomplete", "wall-budget-exhausted-at-completed-boundary"
                        break
                    advanced = advance_continuous(state, stop_seconds=args.stop_seconds)
                    event_count, event_digest = evidence.append_events(advanced.last_events)
                    state = replace(advanced, event_count=event_count, event_digest=event_digest, last_events=())
                    now = state.context.simulation_time_seconds
                    if now % PERIOD == 0:
                        checkpoint_at(directory, state, evidence)
                        clock = time.perf_counter()
                        row = {"session": session_number, "seconds": now,
                            "segment_start_seconds": cycle_start_seconds,
                            "segment_elapsed_seconds": clock - cycle_started,
                            "invocation_elapsed_seconds": clock - started,
                            "cumulative_elapsed_seconds": prior_elapsed + clock - started,
                            "retained_completed_records": len(state.context.ground_data_delivery_state.completed_deliveries),
                            "retained_onboard_records": len(state.context.spacecraft_state.data_storage.stored_records),
                            "partial_records": len(state.context.ground_data_delivery_state.partial_transfers),
                            "events": state.event_count, "advances": state.advances,
                            "physical_substeps": state.accounting["numerical_substeps"],
                            "forecast_substeps": state.accounting["forecast_substeps"],
                            "peak_resident_bytes": peak_resident_bytes(), "output_bytes": output_bytes(directory)}
                        append_line(cycles, row)
                        append_line(log, dict(row, kind="cycle-complete", utc=stamp()))
                        print(json.dumps({"status": "cycle-complete", "seconds": now,
                            "elapsed_seconds": row["cumulative_elapsed_seconds"],
                            "retained_completed_records": row["retained_completed_records"]}), flush=True)
                        cycle_started, cycle_start_seconds = clock, now
                else:
                    status, reason = "completed-pilot", "requested-stop-reached"
        except KeyboardInterrupt:
            status, reason = "incomplete", "interrupted-at-last-completed-boundary"
            failure = traceback.format_exc()
        except Exception:
            status, reason = "failed", "execution-or-evidence-error"
            failure = traceback.format_exc()
        finally:
            if source_snapshot() != source:
                status, reason = "failed", "production-source-changed-during-invocation"
                failure = (failure or "") + "\nSource bytes differ from the starting manifest.\n"
            checkpoint_sha256 = None
            final_summary = None
            if state is not None and reason != "production-source-changed-during-invocation":
                try:
                    if evidence is not None:
                        checkpoint_at(directory, state, evidence)
                        checkpoint_sha256 = hashlib.sha256((directory / "checkpoint.json").read_bytes()).hexdigest()
                    final_summary = summary(state)
                    atomic_text(directory / "summary.json", encode(final_summary))
                except Exception:
                    status, reason = "failed", "final-checkpoint-or-summary-error"
                    failure = (failure or "") + "\n" + traceback.format_exc()
            if evidence is not None:
                evidence.close()
            elapsed = time.perf_counter() - started
            append_line(log, {"kind": "session-end", "utc": stamp(), "session": session_number,
                "status": status, "reason": reason, "elapsed_seconds": elapsed,
                "completed_seconds": None if state is None else state.context.simulation_time_seconds,
                "traceback": failure})
            result = {"version": 1, "status": status, "reason": reason, "session_number": session_number,
                "started_utc": started_utc, "finished_utc": stamp(),
                "requested_stop_seconds": args.stop_seconds, "immutable_horizon_seconds": HORIZON,
                "session_start_seconds": locals().get("session_start_seconds"),
                "session_elapsed_seconds": elapsed, "elapsed_seconds": prior_elapsed + elapsed,
                "peak_resident_bytes": max(prior_peak, peak_resident_bytes()),
                "origin_metrics": origin_metrics, "manifest_sha256": None if manifest is None else digest(manifest),
                "checkpoint_sha256": checkpoint_sha256, "summary": final_summary,
                "incomplete_inventory": [] if status == "completed-pilot" else [{"reason": reason,
                    "requested_stop_seconds": args.stop_seconds,
                    "completed_seconds": None if state is None else state.context.simulation_time_seconds,
                    "remaining_seconds": None if state is None else args.stop_seconds - state.context.simulation_time_seconds}],
                "traceback": failure, "output_bytes": 0}
            session_path = directory / "sessions" / f"session-{session_number:04d}.json"
            # Include both result copies in measured bytes without a self-size discrepancy.
            for _ in range(4):
                text = encode(sealed(result))
                atomic_text(session_path, text)
                atomic_text(directory / "result.json", text)
                measured = output_bytes(directory)
                if result["output_bytes"] == measured:
                    break
                result["output_bytes"] = measured
    print(encode({"status": status, "reason": reason, "output": str(directory),
                  "elapsed_seconds": result["elapsed_seconds"], "seconds":
                  None if state is None else state.context.simulation_time_seconds}), flush=True)
    return 0 if status == "completed-pilot" else 2 if status == "incomplete" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", choices=("B8-A2", "B4-A4"), required=True)
    parser.add_argument("--numerical", choices=("coarse", "fine"), default="coarse")
    parser.add_argument("--workload", choices=("regular", "burst"), default="regular")
    parser.add_argument("--output", required=True)
    parser.add_argument("--stop-seconds", type=int, default=86400)
    parser.add_argument("--wall-budget-seconds", type=float, default=3600.)
    parser.add_argument("--resume", help="Latest checkpoint inside the same evidence directory")
    parser.add_argument("--debug-phase-stop", action="store_true",
                        help="Allow an explicit completed action/contact boundary for restart tests")
    args = parser.parse_args(argv)
    if not 0 < args.stop_seconds <= READINESS_LIMIT_SECONDS:
        parser.error("readiness stops must be positive and at most 259200 seconds (72 h)")
    if not args.debug_phase_stop and args.stop_seconds % PERIOD:
        parser.error("stop must be a 5400-second cycle boundary unless --debug-phase-stop is explicit")
    if not math.isfinite(args.wall_budget_seconds) or args.wall_budget_seconds <= 0:
        parser.error("wall budget must be finite and positive")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        return run_case(args)
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
