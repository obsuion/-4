"""Explicitly opt-in, bounded runnable two-design protocol demonstration."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import time
import uuid

from .catalogue import FIXTURE, project
from .contract import load_study
from .data import canonical, digest, file_digest, identity, read_bytes, write_new
from .engine_adapter import EngineAdapter
from .errors import Refusal
from .locking import FileLock
from .process import ProcessRunner
from .report import compare, export_reports, import_verified
from .scheduler import Scheduler
from .state import State


def fixture_engine():
    return Path(__file__).resolve().parents[1] / "fixtures" / "protocol_engine"


def make_fixture(output):
    out = Path(output).absolute()
    if out.exists():
        raise Refusal("NEW_FIXTURE_DIRECTORY_REQUIRED")
    out.mkdir(parents=True)
    def save(name, value, *, raw=False):
        data = value if raw else canonical(value)
        write_new(out / name, data)
        return dict(path=name, sha256=digest(data), bytes=len(data))
    raw = read_bytes(fixture_engine() / "kit" / "serverctl.py")
    manifest = {"kit/serverctl.py": dict(bytes=len(raw), sha256=digest(raw))}
    source_ref = save("source-manifest.json", manifest)
    records = []; first = None
    for index in range(2):
        body = dict(format="KAZE_SYNTHETIC_INITIAL_V1", version=1,
            inputs=dict(duration_seconds=4, hardware=dict(kind="synthetic-" + str(index)),
                world=dict(label=FIXTURE, orbit="NO_PHYSICS"), scenario=dict(label=FIXTURE, requests=4),
                controller=dict(label=FIXTURE, rule="FIXED_PROTOCOL"), accounting="INITIAL"))
        doc = dict(body, digest=identity(body))
        first = first or doc
        input_ref = save("inputs/design-" + str(index) + ".json", doc)
        records.append(dict(design_id="design-" + str(index), root_identity=doc["digest"], input=input_ref,
            assumptions=[dict(name="all fixture quantities", value="SYNTHETIC", units="1", source=FIXTURE,
                              consumer="protocol test only", status="SYNTHETIC_ACCELERATED_ASSUMED")],
            mass=dict(value_kg="1", status="ASSUMED", source=FIXTURE)))
    allowed = ["/inputs/hardware/kind"]
    catalogue = dict(schema="KAZE_DESIGN_CATALOGUE_V1", label=FIXTURE, engine_source_sha256=identity(manifest),
        baseline_design="design-0", allowed_design_paths=allowed,
        common_paths=dict(world=["/inputs/world"], scenario=["/inputs/scenario"], controller=["/inputs/controller"]),
        common_projection_sha256=identity(project(first, allowed)), original_anchor_seconds=0, bucket_seconds=2592000, designs=records)
    cat_ref = save("catalogue.json", catalogue)
    policy_ref = save("policy.json", dict(method=FIXTURE, mode=FIXTURE, maximum_primary_segments=2,
        maximum_output_bytes=262144, hard_seconds=5, maximum_observed_primary_seconds=10,
        maximum_diagnostic_seconds=0, backup_copies=1))
    spec = dict(schema="KAZE_STUDY_V1", study_id="fixture-" + uuid.uuid4().hex[:12], mode=FIXTURE,
        binding=dict(schema="KAZE_ENGINE_BINDING_V1", revision=2, freeze=FIXTURE, protocol="SERVERCTL_B63_V2",
            source_manifest=source_ref, source_sha256=identity(manifest),
            runtime=dict(python=sys.version, platform=sys.platform, executable=str(Path(sys.executable).absolute()),
                interpreter_sha256=file_digest(Path(sys.executable).resolve(), 128 * 2**20), requirements_sha256="0" * 64, dependency_versions={}),
            backend="REFERENCE", build=None, capability_sha256=None, acceptance=None, repair_evidence=None),
        catalogue=cat_ref, policy=policy_ref, horizon_seconds=4,
        deadline=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), concurrency=2,
        resources=dict(slots=2, cpu_cores=6, parent_rss_bytes=32 * 2**20, worker_rss_bytes=64 * 2**20,
            native_rss_bytes=0, supervisor_rss_bytes=16 * 2**20, control_rss_bytes=32 * 2**20,
            ram_bytes=256 * 2**20, disk_bytes=128 * 2**20, disk_free_floor_bytes=2**20,
            per_design_disk_bytes=4 * 2**20, wrapper_output_bytes=8 * 2**20,
            max_owned_wall_seconds=180, max_owned_cpu_seconds=180, per_run_wall_seconds=5,
            control_timeout_seconds=1, control_wall_reserve_seconds=60, stdout_bytes=2 * 2**20, stderr_bytes=65536),
        cost=dict(rate="0.01", unit="OWNED_PROCESS_HOUR", currency="USD", cap="10", setup="0",
            engine_scenario=dict(rate="0.01", unit="MACHINE_HOUR", currency="USD", cap="10", setup="0")),
        objective=dict(metric="credits", direction="max"), failure_policy="CONTINUE_INDEPENDENT", execution_mode="pilot")
    save("study.json", spec)
    return out / "study.json"


def demonstrate(output):
    """12 owned children total; <=2 concurrent; <=5s per child; no science."""
    output = Path(output).absolute()
    if output.exists():
        raise Refusal("NEW_DEMO_DIRECTORY_REQUIRED")
    output.mkdir(parents=True)
    manifest = make_fixture(output / "spec")
    study = load_study(manifest, protocol_fixture=True)
    state = State.create(study, output / "study", output / "pool.sqlite3",
                         engine=fixture_engine(), interpreter=sys.executable)
    runner = ProcessRunner(maximum_children=2)
    adapter = EngineAdapter(state.study, fixture_engine(), sys.executable, state=state, runner=runner, protocol_fixture=True)
    scheduler = Scheduler(state, protocol_fixture=True, adapter=adapter)
    scheduler.prepare()
    d0, d1 = state.study.catalogue.designs
    with FileLock(state.directory / "runner.lock"):
        token = uuid.uuid4().hex; start = time.monotonic(); state.manager_enter(token)
        try:
            intent = state.claim(d0.design_id, 0, token)
            with ThreadPoolExecutor(max_workers=1) as executor:
                f = executor.submit(adapter.execute, d0, state.design(d0.design_id), intent)
                expected = Path(state.design(d0.design_id)["store_path"]) / "fixture-state.json"
                limit = time.monotonic() + 2
                while not expected.exists():
                    if time.monotonic() >= limit:
                        raise Refusal("FIXTURE_START_NOT_OBSERVED")
                    time.sleep(0.01)
                stopped = scheduler.stop()
                state.save_receipt(intent, f.result(timeout=6))
        finally:
            state.manager_exit(token, time.monotonic() - start)
    reopened = State(state.directory)
    if not reopened.snapshot()["study"]["paused"] or reopened.design(d0.design_id)["phase"] != "USER":
        raise Refusal("FIXTURE_STOP_REOPEN_NOT_PRESERVED")
    stale_rejected = False
    try:
        reopened.resume(stopped["generation"] - 1)
    except Refusal as error:
        stale_rejected = error.code == "STALE_GENERATION"
    if not stale_rejected:
        raise Refusal("FIXTURE_STALE_GENERATION_ACCEPTED")
    adapter.state = reopened
    scheduler = Scheduler(reopened, protocol_fixture=True, adapter=adapter)
    completed = scheduler.run(explicit_resume_generation=stopped["generation"])
    # Query actual fixture subprocess status; this read never dispatches.
    for design in reopened.study.catalogue.designs:
        adapter.status(design, reopened.design(design.design_id))
    imports = []
    for design in reopened.study.catalogue.designs:
        record = reopened.design(design.design_id)
        result_path = Path(record["store_path"] + ".exports") / "result.zip"
        adapter.export_result(design, record, result_path)
        verified_dir = output / "verified" / design.design_id
        import_verified(adapter, design, record, result_path, verified_dir)
        imports.append(verified_dir / "verified.json")
    report = compare(imports)
    hashes = export_reports(report, output / "reports", state=reopened)
    evidence = dict(label=FIXTURE, real_engine_integration="NOT_RUN", linux_native_acceptance="NOT_RUN",
        children_created=runner.created, peak_simultaneous_children=runner.peak_active,
        total_owned_child_seconds=runner.total_child_seconds, stale_generation_rejected=stale_rejected,
        stop_reopen_explicit_resume=True, final_phases={d["design"]: d["phase"] for d in reopened.snapshot()["designs"]},
        report_hashes=hashes, report_path=str(output / "reports" / "report.json"))
    if runner.created > 12 or runner.peak_active > 2 or runner.total_child_seconds > 60:
        raise Refusal("FIXTURE_BUDGET_EXCEEDED")
    if any(phase != "TARGET" for phase in evidence["final_phases"].values()):
        raise Refusal("FIXTURE_NOT_COMPLETE")
    write_new(output / "demo-evidence.json", canonical(evidence))
    return evidence

