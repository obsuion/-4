"""PROTOCOL_FIXTURE_NO_SCIENCE: synthetic serverctl wire, never a real engine.

Fixed local test implementation. There are no scientific imports, native
checkpoints, acceptance receipts or production execution rights in this folder.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
import time
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from kaze_study.data import atomic_json, canonical, digest, file_digest, identity, parse, read, read_bytes, write_new
from kaze_study.locking import FileLock
from kaze_study.lineage import project_owner_source
from kaze_study.report import read_result_data, validate_view

LABEL = "PROTOCOL_FIXTURE_NO_SCIENCE"
HERE = Path(__file__).resolve().parents[1]


def runtime_identity():
    return dict(python=sys.version, platform=sys.platform, executable=str(Path(sys.executable).absolute()),
                interpreter_sha256=file_digest(Path(sys.executable).resolve(), 128 * 2**20))


def source():
    raw = read_bytes(HERE / "kit" / "serverctl.py")
    return {"kit/serverctl.py": dict(bytes=len(raw), sha256=digest(raw))}


def store_path(path):
    return path.parent / (path.stem + ".store")


def terminal(kind, clock):
    return dict(format="B59_TYPED_TERMINAL_V1", kind=kind, code=LABEL + ":" + kind,
                stage="SYNTHETIC_BOUNDARY", owner=LABEL, clock=clock,
                automatic_resume=kind in ("RESOURCE_TIME", "RESOURCE_OUTPUT"))


def contract(plan):
    return dict(format="KAZE_FIXTURE_EXECUTION_CONTRACT_V1", label=LABEL,
        root_identity=plan["root_identity"], input_sha256=plan["input_sha256"],
        source_manifest=plan["source_manifest"], source_manifest_sha256=plan["source_manifest_sha256"],
        runtime=runtime_identity(), backend_binding=plan["execution_authority"]["binding"]["backend_binding"],
        native_build=None)


def lifetime_plan(plan):
    value = dict(format="B63_ORIGINAL_ROOT_PREPARED_SERIAL_PLAN_V2", root_identity=plan["root_identity"],
        input_sha256=plan["input_sha256"], source_identity=project_owner_source(plan["source_manifest"], fixture=True), runtime=runtime_identity(),
        policy=plan["policy"], policy_identity=plan["policy_identity"], execution_contract_sha256=plan["execution_contract_sha256"],
        root_target=plan["duration_seconds"], original_anchor=0, automatic_resume=["RESOURCE_TIME", "RESOURCE_OUTPUT"],
        incomplete_is_not_coverage=True, pool_key=identity([LABEL, plan["root_identity"]]),
        execution_authority_sha256=identity(plan["execution_authority"]),
        backend_binding=plan["execution_authority"]["binding"]["backend_binding"],
        pool_inventory="B63_VERIFIED_IMMUTABLE_INITIAL_FILES_ONLY_V1")
    return dict(value, plan_identity=identity(value))


def make_plan(args):
    raw = read_bytes(args.input); original = parse(raw); policy = read(args.policy)
    if original["format"] != "KAZE_SYNTHETIC_INITIAL_V1" or policy["mode"] != LABEL or args.backend != "REFERENCE" or args.mode != "pilot" or args.build or args.acceptance:
        raise ValueError("FIXTURE_ONLY_REFUSED")
    p = args.output.absolute(); p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise ValueError("NEW_FIXTURE_PLAN_REQUIRED")
    names = dict(original=p.stem + ".original.json", duration=p.stem + ".duration.json", initial=p.stem + ".initial.json")
    initial = json.loads(raw)
    initial["inputs"]["accounting"] = LABEL + ":CUMULATIVE"
    initial["digest"] = identity({k: initial[k] for k in ("format", "version", "inputs")})
    actual = canonical(initial)
    for name, data in ((names["original"], raw), (names["duration"], raw), (names["initial"], actual)):
        write_new(p.parent / name, data)
    source_manifest = source()
    runtime = dict(python=sys.version, platform=sys.platform)
    backend = dict(format="B63_BACKEND_EXECUTION_BINDING_V1", method="B63_PREPARED_NATIVE_V1",
                   selection="REFERENCE", build_sha256=None, capability_sha256=None)
    authority = dict(format="B63_LIFETIME_EXECUTION_AUTHORITY_V1", mode="PILOT", acceptance=None,
        pilot_limits=dict(duration_seconds=86400, primary_segments=8, diagnostic_slots=2, hard_seconds=240),
        binding=dict(root_identity=initial["digest"], input_sha256=digest(actual), source_manifest_sha256=identity(source_manifest),
            runtime=runtime_identity(), execution_contract_sha256="0" * 64, policy_identity=identity(policy), backend_binding=backend,
            domain_identity=identity(original), original_anchor_seconds=0, duration_seconds=args.seconds))
    value = dict(format="B63_PREPARED_SERVER_PLAN_V2", mode="pilot", duration_seconds=args.seconds,
        root_identity=initial["digest"], original_input=names["original"], duration_input=names["duration"], input_file=names["initial"],
        original_sha256=digest(raw), duration_sha256=digest(raw), input_sha256=digest(actual),
        duration_derivation=dict(format="B62_FRESH_V7_DURATION_DERIVATION_V1", original_root_identity=original["digest"],
            original_anchor_seconds=0, duration_seconds=args.seconds, changed_fields=["inputs.duration_seconds", "digest"]),
        accounting_derivation=dict(format=LABEL, original_sha256=digest(raw), input_sha256=digest(actual)),
        policy=policy, policy_identity=identity(policy), source_manifest=source_manifest,
        source_manifest_sha256=identity(source_manifest), preparation_runtime=runtime,
        prospective_store_reservation_bytes=2 * 2**20, shared_pool_reservation_including_backup_bytes=4 * 2**20,
        cost_scenario=dict(currency=args.currency, rate_per_machine_hour=args.rate, setup=args.setup,
            maximum_estimated_compute_cost=args.max_cost, maximum_declared_seconds=10, billing_warning=LABEL),
        native_import=False, qualification=LABEL, engine_entrypoint="m8_lifetime_campaign_cli.py",
        backend="REFERENCE", native_build=None, execution_mode="PILOT", execution_authority=authority,
        execution_contract_sha256="0" * 64)
    value["execution_contract_sha256"] = identity(contract(value))
    authority["binding"]["execution_contract_sha256"] = value["execution_contract_sha256"]
    authority["identity"] = identity(authority)
    value["plan_identity"] = identity(value)
    write_new(p, canonical(value))
    return value


def load_plan(path):
    p = read(path)
    if p["source_manifest"] != source() or p["plan_identity"] != identity({k: v for k, v in p.items() if k != "plan_identity"}):
        raise ValueError("FIXTURE_PLAN_DRIFT")
    return p


def summary(path, plan):
    state = read(store_path(path) / "fixture-state.json")
    value = dict(plan_identity=lifetime_plan(plan)["plan_identity"], root_identity=plan["root_identity"],
        target_seconds=plan["duration_seconds"], source_identity=project_owner_source(plan["source_manifest"], fixture=True), runtime=runtime_identity(),
        jobs=state["jobs"], primary_jobs=state["jobs"], diagnostic_jobs=0, observed_seconds=state["observed"],
        diagnostic_observed_seconds=0, reserved_unknown_seconds=0 if not state["active"] else 5,
        clock=state["clock"], parent_job_id=state["job_id"], typed_terminal=state["terminal"],
        operator_pause=(store_path(path) / "operator-pause.json").exists(), mode=LABEL, qualification=LABEL,
        execution_authority_sha256=identity(plan["execution_authority"]),
        backend_binding=plan["execution_authority"]["binding"]["backend_binding"],
        runner_store_format="B63_FINITE_PREPARED_LIFETIME_STORE_V2")
    return value


def execute(path, plan, resume=False):
    directory = store_path(path)
    if not directory.exists():
        if resume:
            raise ValueError("NO_FIXTURE_STORE_TO_RESUME")
        directory.mkdir()
        atomic_json(directory / "fixture-state.json", dict(clock=0, jobs=0, job_id=None, terminal=None, active=False, observed=0.0))
    elif not resume:
        raise ValueError("DUPLICATE_INITIAL_FIXTURE_SUBMISSION")
    with FileLock(directory / "fixture-supervisor.lock"):
        state = read(directory / "fixture-state.json")
        if state["active"]:
            raise ValueError("UNKNOWN_PREVIOUS_FIXTURE_SUBMISSION_NO_PID_RETRY")
        if state["terminal"] is not None and state["terminal"]["kind"] not in ("USER", "RESOURCE_TIME", "RESOURCE_OUTPUT"):
            raise ValueError("FIXTURE_TERMINAL_NOT_RESUMABLE")
        marker = directory / "operator-pause.json"
        if resume and marker.exists():
            # This is an owned, exactly bound test marker, not stale-lock removal.
            if read(marker).get("plan_identity") != lifetime_plan(plan)["plan_identity"]:
                raise ValueError("FOREIGN_FIXTURE_STOP")
            marker.unlink()
        state.update(active=True, terminal=None, jobs=state["jobs"] + 1, job_id=uuid.uuid4().hex)
        atomic_json(directory / "fixture-state.json", state)
        started = time.monotonic()
        for _ in range(16):
            time.sleep(0.025)
            if marker.exists():
                state["clock"] = max(state["clock"], max(1, plan["duration_seconds"] // 2))
                state["terminal"] = terminal("USER", state["clock"])
                break
        else:
            state["clock"] = plan["duration_seconds"]
            state["terminal"] = terminal("TARGET", state["clock"])
        state["active"] = False; state["observed"] += time.monotonic() - started
        atomic_json(directory / "fixture-state.json", state)
    return dict(store=str(directory), result=summary(path, plan), billing_still_active=True)


def totals():
    return dict(credits=3, offered=4, expired=1, useful_bits=1234, priority_score=0.75,
        minimum_energy_wh=["10", "1"], end_energy_wh=["11", "1"],
        minimum_temperature_k={"battery": ["290", "1"]}, maximum_temperature_k={"battery": ["300", "1"]},
        sums=dict(unmet_load_wh=["0", "1"]), wear_end=dict(battery_retention=["99", "100"], solar_retention=["1", "1"]))


def export(path, plan, output):
    state = read(store_path(path) / "fixture-state.json")
    if state["active"] or state["terminal"] is None:
        raise ValueError("FIXTURE_EXPORT_REQUIRES_SETTLEMENT")
    if output.parent != Path(str(store_path(path)) + ".exports") or output.exists():
        raise ValueError("FIXTURE_RESERVED_EXPORT_PATH")
    output.parent.mkdir(parents=True, exist_ok=True)
    jid = state["job_id"]; scientific_name = "scientific/" + jid + ".json"
    science = canonical(dict(label=LABEL, clock=state["clock"], totals=totals(), terminal=state["terminal"]))
    view = dict(format="KAZE_PROTOCOL_FIXTURE_RESULT_V1", root_identity=plan["root_identity"], input_sha256=plan["input_sha256"],
        source_manifest_sha256=plan["source_manifest_sha256"], execution_contract_sha256=plan["execution_contract_sha256"],
        plan_identity=lifetime_plan(plan)["plan_identity"], requested_end_seconds=plan["duration_seconds"], actual_end_seconds=state["clock"],
        read_only=True, native_execution_rights=False, backup_required_for_resume=True, primary_totals=totals(),
        monthly_environment=[], monthly_actual=[dict(start_seconds=0, end_seconds=state["clock"])], cumulative_work={"label": LABEL},
        jobs=[dict(job_id=jid, role="PRIMARY", status="COMPLETED" if state["terminal"]["kind"] == "TARGET" else "CANCELLED",
            terminal=state["terminal"], clock=state["clock"], scientific_file=scientific_name, scientific_sha256=digest(science))],
        scope="LATEST_FORWARD_PRIMARY_ACTUAL_PREFIX_DIAGNOSTICS_NEVER_ADDED",
        execution_authority_sha256=identity(plan["execution_authority"]), backend_binding=plan["execution_authority"]["binding"]["backend_binding"])
    payload = {"view.json": canonical(view), "input.json": read_bytes(path.parent / plan["input_file"]),
        "execution-contract.json": canonical(contract(plan)), "plan.json": canonical(lifetime_plan(plan)),
        "execution-authority.json": canonical(plan["execution_authority"]), scientific_name: science}
    manifest = dict(format=view["format"], files={name: dict(bytes=len(raw), sha256=digest(raw)) for name, raw in payload.items()})
    with output.open("xb") as f:
        with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("MANIFEST.json", canonical(manifest))
            for name, raw in payload.items():
                z.writestr(name, raw)
    inspect(output)
    return dict(path=str(output), sha256=file_digest(output), native_execution_rights=False,
                measured_bytes=output.stat().st_size, actual_end_seconds=state["clock"])


def inspect(path):
    data = read_result_data(path); view = data["view.json"]
    validate_view(view, anchor=0, requested_end=view["requested_end_seconds"], mode=LABEL)
    c = data["execution-contract.json"]
    if (c.get("label") != LABEL or c.get("source_manifest") != source() or identity(c) != view["execution_contract_sha256"] or
            identity(data["execution-authority.json"]) != view["execution_authority_sha256"] or
            data["input.json"]["digest"] != view["root_identity"] or digest(canonical(data["input.json"])) != view["input_sha256"] or
            data["plan.json"]["plan_identity"] != view["plan_identity"]):
        raise ValueError("SYNTHETIC_INSPECTOR_LINEAGE_REFUSAL")
    with zipfile.ZipFile(path) as z:
        latest = max((j for j in view["jobs"] if j["role"] == "PRIMARY"), key=lambda j: j["clock"])
        endpoint = parse(z.read(latest["scientific_file"]))
        if endpoint["totals"] != view["primary_totals"] or endpoint["clock"] != view["actual_end_seconds"]:
            raise ValueError("SYNTHETIC_CUMULATIVE_ENDPOINT_REFUSAL")
    return view


def main():
    a = argparse.ArgumentParser(description=__doc__); a.add_argument("--engine", type=Path, required=True)
    sub = a.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("plan")
    for flag in ("input", "output", "policy"):
        p.add_argument("--" + flag, type=Path, required=True)
    p.add_argument("--seconds", type=int, required=True)
    for flag in ("rate", "currency", "max-cost", "setup", "mode", "backend"):
        p.add_argument("--" + flag, required=True)
    p.add_argument("--build", type=Path); p.add_argument("--acceptance", type=Path)
    for name in ("run", "resume", "status", "stop", "export-result"):
        p = sub.add_parser(name); p.add_argument("--plan", type=Path, required=True)
        if name == "export-result":
            p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("inspect-result"); p.add_argument("--input", type=Path, required=True)
    args = a.parse_args()
    if args.engine.resolve() != HERE:
        raise ValueError("FIXTURE_SOURCE_PATH")
    if args.command == "doctor":
        return dict(format="KAZEOSAT_SERVER_DOCTOR_V1", source_manifest_sha256=identity(source()),
                    ready_for_engine_attempt=False, science_executed=False, fixture=LABEL)
    if args.command == "plan":
        return make_plan(args)
    if args.command == "inspect-result":
        return inspect(args.input)
    path = args.plan.absolute(); plan = load_plan(path)
    if args.command in ("run", "resume"):
        return execute(path, plan, resume=args.command == "resume")
    if args.command == "stop":
        marker = store_path(path) / "operator-pause.json"
        if not marker.exists():
            write_new(marker, canonical(dict(plan_identity=lifetime_plan(plan)["plan_identity"])))
        return summary(path, plan)
    if args.command == "export-result":
        return export(path, plan, args.output.absolute())
    return summary(path, plan)


if __name__ == "__main__":
    try:
        print(json.dumps(main(), ensure_ascii=False, allow_nan=False, indent=2))
    except (ValueError, OSError, RuntimeError) as error:
        print(json.dumps(dict(status="REFUSED_OR_FAILED", reason=str(error), completion_not_established=True)), file=sys.stderr)
        raise SystemExit(2)

