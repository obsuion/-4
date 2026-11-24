"""Verified data-only result import and a reducer with one cumulative tip/design."""
from __future__ import annotations

import csv
from decimal import Decimal, localcontext
from fractions import Fraction
import html
import io
import json
import os
from pathlib import Path
import stat
import struct
import zipfile

from .catalogue import FIXTURE
from .data import canonical, digest, fields, file_digest, identity, inside, integer, no_links, parse, read, read_bytes, sha, write_new
from .engine_adapter import FIXTURE_RESULT, RESULT_FORMAT, backend_binding
from .errors import Refusal
from .lineage import project_owner_source
from .protocol import B65, family

SCOPE = "LATEST_FORWARD_PRIMARY_ACTUAL_PREFIX_DIAGNOSTICS_NEVER_ADDED"
MAX_ZIP = 512 * 2**20
MAX_MEMBERS = 16384
MAX_COMPARISON_RECEIPT_BYTES = 32 * 2**20
VIEW_FIELDS = {"format", "root_identity", "input_sha256", "source_manifest_sha256", "execution_contract_sha256",
    "plan_identity", "requested_end_seconds", "actual_end_seconds", "read_only", "native_execution_rights",
    "backup_required_for_resume", "primary_totals", "monthly_environment", "monthly_actual", "cumulative_work",
    "jobs", "scope", "execution_authority_sha256", "backend_binding"}


def zip_metadata(path):
    """Bound the real central directory before ZipFile allocates entry objects."""
    path = no_links(path)
    size = path.stat().st_size
    if not 22 <= size <= MAX_ZIP:
        raise Refusal("RESULT_ZIP_BYTES")
    with path.open("rb") as f:
        f.seek(-22, 2)
        signature, disk, startdisk, n_disk, n, cd_bytes, offset, comment = struct.unpack("<4s4H2LH", f.read(22))
        if (signature != b"PK\x05\x06" or disk or startdisk or n_disk != n or comment or
                not 2 <= n <= MAX_MEMBERS or cd_bytes > 16 * 2**20 or offset + cd_bytes != size - 22):
            raise Refusal("CLASSIC_BOUNDED_RESULT_ZIP")
        f.seek(offset)
        for _ in range(n):
            record = f.read(46)
            if len(record) != 46 or record[:4] != b"PK\x01\x02":
                raise Refusal("ZIP_DIRECTORY_RECORD")
            name, extra, note = struct.unpack_from("<3H", record, 28)
            if not 1 <= name <= 960 or f.tell() + name + extra + note > offset + cd_bytes:
                raise Refusal("ZIP_DIRECTORY_BOUND")
            f.seek(name + extra + note, 1)
        if f.tell() != offset + cd_bytes:
            raise Refusal("ZIP_DIRECTORY_ACTUAL_POPULATION")


def read_result_data(path, *, verify_members=True):
    """No extraction, unpickling, materializers, scientific replay or execution."""
    from .data import relative
    zip_metadata(path)
    with zipfile.ZipFile(path) as archive:
        seen = set(); total = 0
        for member in archive.infolist():
            relative(member.filename)
            key = member.filename.casefold()
            if key in seen or member.is_dir() or member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16):
                raise Refusal("ZIP_DUPLICATE_LINK_OR_ENCRYPTION")
            seen.add(key)
            total += member.file_size
            if member.file_size > 64 * 2**20 or total > MAX_ZIP:
                raise Refusal("ZIP_EXPANDED_BYTES")
        if "MANIFEST.json" not in archive.namelist() or archive.getinfo("MANIFEST.json").file_size > 8 * 2**20:
            raise Refusal("RESULT_MANIFEST_REQUIRED")
        manifest = fields(parse(archive.read("MANIFEST.json"), 8 * 2**20), ("format", "files"), "result manifest")
        if type(manifest["files"]) is not dict or set(manifest["files"]) | {"MANIFEST.json"} != set(archive.namelist()):
            raise Refusal("RESULT_MANIFEST_MEMBERSHIP")
        import hashlib
        for name, entry in manifest["files"].items():
            fields(entry, ("bytes", "sha256"), "result member")
            integer(entry["bytes"], "result member size", 1, 64 * 2**20); sha(entry["sha256"])
            if archive.getinfo(name).file_size != entry["bytes"]:
                raise Refusal("RESULT_MEMBER_SIZE")
            if verify_members:
                h = hashlib.sha256()
                with archive.open(name) as stream:
                    for block in iter(lambda: stream.read(2**20), b""):
                        h.update(block)
                if h.hexdigest() != entry["sha256"]:
                    raise Refusal("RESULT_MEMBER_HASH")
        data = {}
        for name, cap in (("view.json", 16 * 2**20), ("input.json", 8 * 2**20),
                          ("execution-contract.json", 2 * 2**20), ("plan.json", 65536),
                          ("execution-authority.json", 16384)):
            if name not in manifest["files"] or archive.getinfo(name).file_size > cap:
                raise Refusal("RESULT_AUTHORITY_METADATA", name)
            data[name] = parse(archive.read(name), cap)
        if manifest["format"] != data["view.json"]["format"]:
            raise Refusal("RESULT_MANIFEST_VIEW_FORMAT")
        return data


def validate_view(view, *, anchor, requested_end, mode):
    fields(view, VIEW_FIELDS, "verified lifetime view")
    if view["format"] not in ((FIXTURE_RESULT,) if mode == FIXTURE else (RESULT_FORMAT, B65.result)):
        raise Refusal("RESULT_MODE_OR_SCHEMA")
    if (view["scope"] != SCOPE or view["read_only"] is not True or
            view["native_execution_rights"] is not False or view["backup_required_for_resume"] is not True):
        raise Refusal("RESULT_READ_ONLY_OR_CUMULATIVE_SCOPE")
    integer(view["requested_end_seconds"], "requested end", requested_end, requested_end)
    integer(view["actual_end_seconds"], "actual end", anchor, requested_end)
    rows = view["monthly_actual"]
    if type(rows) is not list or len(rows) > 185:
        raise Refusal("REPORT_BUCKET_POPULATION")
    cursor = anchor
    for row in rows:
        if type(row) is not dict:
            raise Refusal("REPORT_BUCKET_ROW")
        a = integer(row.get("start_seconds"), "bucket start", anchor, view["actual_end_seconds"])
        b = integer(row.get("end_seconds"), "bucket end", a + 1, view["actual_end_seconds"])
        if a != cursor:
            raise Refusal("MONTHLY_SUPPORT_GAP_OR_OVERLAP")
        cursor = b
    if cursor != view["actual_end_seconds"]:
        raise Refusal("MONTHLY_SUPPORT_INCOMPLETE")
    if type(view["jobs"]) is not list or len(view["jobs"]) > 8200:
        raise Refusal("RESULT_JOB_POPULATION")
    seen = set(); primary_clocks = []
    for job in view["jobs"]:
        fields(job, ("job_id", "role", "status", "terminal", "clock", "scientific_file", "scientific_sha256"), "result job")
        jid = job["job_id"]
        if type(jid) is not str or len(jid) != 32 or any(c not in "0123456789abcdef" for c in jid) or jid in seen:
            raise Refusal("RESULT_JOB_IDENTITY")
        seen.add(jid)
        if job["role"] not in ("PRIMARY", "DIAGNOSTIC") or job["status"] not in ("COMPLETED", "INCOMPLETE", "CANCELLED", "REFUSED", "PROCESS_FAILED", "UNKNOWN"):
            raise Refusal("RESULT_JOB_ROLE_OR_SETTLEMENT")
        if job["role"] == "PRIMARY" and job["scientific_file"] is not None:
            primary_clocks.append(integer(job["clock"], "primary clock", anchor, view["actual_end_seconds"]))
    if len(primary_clocks) != len(set(primary_clocks)):
        raise Refusal("DUPLICATE_CUMULATIVE_PRIMARY_ENDPOINT")
    if primary_clocks and max(primary_clocks) != view["actual_end_seconds"]:
        raise Refusal("PRIMARY_TIP_SUPPORT")
    if view["actual_end_seconds"] > anchor and not primary_clocks:
        raise Refusal("NO_PRIMARY_COVERAGE_AUTHORITY")
    totals = view["primary_totals"]
    if totals is not None:
        for key in ("credits", "offered", "expired", "useful_bits"):
            integer(totals.get(key), key)
    elif view["actual_end_seconds"] > anchor:
        raise Refusal("MISSING_CUMULATIVE_TOTALS")
    return view


def verify_lineage(view, data, study, design, plan):
    spec = study.spec
    if spec["mode"] != FIXTURE and view["format"] != family(spec["binding"]["protocol"]).result:
        raise Refusal("RESULT_EXACT_VERSIONED_FAMILY")
    validate_view(view, anchor=study.catalogue.anchor_seconds,
                  requested_end=study.catalogue.anchor_seconds + spec["horizon_seconds"], mode=spec["mode"])
    expected = {"root_identity": plan["root_identity"], "input_sha256": plan["input_sha256"],
        "source_manifest_sha256": spec["binding"]["source_sha256"],
        "execution_contract_sha256": plan["execution_contract_sha256"],
        "execution_authority_sha256": identity(plan["execution_authority"]),
        "backend_binding": plan["execution_authority"]["binding"]["backend_binding"]}
    if any(view[k] != v for k, v in expected.items()):
        raise Refusal("RESULT_INPUT_SOURCE_BACKEND_AUTHORITY_SUBSTITUTION")
    c = data["execution-contract.json"]
    store_plan = data["plan.json"]
    if (identity(c) != view["execution_contract_sha256"] or c.get("runtime") != plan["execution_authority"]["binding"]["runtime"] or
            c.get("source_manifest_sha256") != spec["binding"]["source_sha256"] or
            store_plan.get("plan_identity") != view["plan_identity"] or
            store_plan.get("policy_identity") != plan["policy_identity"] or
            identity(data["execution-authority.json"]) != view["execution_authority_sha256"]):
        raise Refusal("RESULT_CONTRACT_RUNTIME_POLICY_LINEAGE")
    if store_plan.get("source_identity") != project_owner_source(plan["source_manifest"], fixture=spec["mode"] == FIXTURE):
        raise Refusal("RESULT_M8_OWNER_SOURCE_LINEAGE")
    if design.original_sha256 != plan["original_sha256"] or design.root_identity != plan["duration_derivation"]["original_root_identity"]:
        raise Refusal("RESULT_ORIGINAL_DESIGN_LINEAGE")
    if (plan["source_manifest_sha256"] != spec["binding"]["source_sha256"] or
            canonical(plan["source_manifest"]) != study.source_bytes or plan["policy_identity"] != identity(parse(reference_policy(study))) or
            plan["backend"] != spec["binding"]["backend"] or
            plan["plan_identity"] != identity({k: x for k, x in plan.items() if k != "plan_identity"})):
        raise Refusal("RESULT_TRUSTED_PLAN_SOURCE_POLICY_BINDING")


def reference_policy(study):
    from .data import reference
    return reference(study.root, study.spec["policy"], 65536)[1]


def verify_initial_result_lineage(view, data, study, design):
    """Import already computed DATA without creating an execution plan/store.

    This route accepts only the exact canonical initial root supplied by the
    compiler. Derived duration/accounting inputs need their pinned server plan.
    """
    from .data import reference
    spec = study.spec; binding = spec["binding"]
    validate_view(view, anchor=study.catalogue.anchor_seconds,
        requested_end=study.catalogue.anchor_seconds + spec["horizon_seconds"], mode=spec["mode"])
    c = data["execution-contract.json"]; store_plan = data["plan.json"]; authority = data["execution-authority.json"]
    expected_backend = backend_binding(spec)
    if binding["build"] is not None:
        expected_backend["build_sha256"] = identity(parse(reference(study.root, binding["build"], 65536)[1]))
    runtime = {k: binding["runtime"][k] for k in ("python", "platform", "executable", "interpreter_sha256")}
    if (view["format"] != family(binding["protocol"]).result or view["root_identity"] != design.root_identity or
            view["input_sha256"] != design.original_sha256 or canonical(data["input.json"]) != design.input_bytes or
            view["source_manifest_sha256"] != binding["source_sha256"] or canonical(c["source_manifest"]) != study.source_bytes or
            c["runtime"] != runtime or view["backend_binding"] != expected_backend or
            store_plan["policy_identity"] != identity(parse(reference_policy(study))) or
            store_plan["source_identity"] != project_owner_source(parse(study.source_bytes)) or
            authority["mode"] != spec["execution_mode"].upper()):
        raise Refusal("READ_ONLY_EXACT_INITIAL_PROJECT_BINDING")


def import_verified(adapter, design, record, input_path, output):
    """Only the engine inspector can admit an engine result for the first time."""
    plan = None if record["plan_sha"] is None and not adapter.fixture else adapter.pinned_plan(design, record)
    view, raw_sha, process = adapter.inspect_result(input_path)
    data = read_result_data(input_path)
    if canonical(view) != canonical(data["view.json"]):
        raise Refusal("INSPECTOR_VIEW_RAW_RESULT_MISMATCH")
    if plan is None:
        verify_initial_result_lineage(view, data, adapter.study, design)
    else:
        verify_lineage(view, data, adapter.study, design, plan)
    out = no_links(output)
    if out.exists():
        raise Refusal("NEW_VERIFIED_IMPORT_REQUIRED")
    count = Path(input_path).stat().st_size
    receipt = dict(schema="KAZE_VERIFIED_RESULT_V2", label=adapter.spec["mode"],
        authority="ENGINE_INSPECTOR_DATA_ONLY", native_resume_authority=False,
        study_manifest_sha256=adapter.study.manifest_sha256, design_id=design.design_id,
        original_root_identity=design.root_identity, original_input_sha256=design.original_sha256,
        common_projection_sha256=adapter.study.catalogue.common_sha256,
        anchor_seconds=adapter.study.catalogue.anchor_seconds, bucket_seconds=adapter.study.catalogue.bucket_seconds,
        binding=adapter.spec["binding"], objective=adapter.spec["objective"],
        assumptions=design.assumptions, mass=design.mass, result=dict(path="result.zip", sha256=raw_sha, bytes=count),
        inspector_process=process, view=view, server_plan=plan, case_identity=design.pins,
        compute=design_compute(adapter.state, design.design_id) if adapter.state is not None else None)
    receipt_bytes = canonical(receipt)
    if len(receipt_bytes) > 16 * 2**20:
        raise Refusal("VERIFIED_RECEIPT_BYTES")
    if adapter.state is not None:
        adapter.state.reserve_publication(out, "VERIFIED_READ_ONLY_RESULT", count + len(receipt_bytes) + 65536)
    out.mkdir(parents=True)
    copied = out / "result.zip"
    with Path(input_path).open("rb") as src, copied.open("xb") as dst:
        actual_count = 0
        while True:
            block = src.read(2**20)
            if not block:
                break
            actual_count += len(block)
            if actual_count > count:
                raise Refusal("RESULT_COPY_BOUND")
            dst.write(block)
        dst.flush(); os.fsync(dst.fileno())
    if actual_count != count or file_digest(copied) != raw_sha:
        raise Refusal("RESULT_COPY_HASH")
    write_new(out / "verified.json", receipt_bytes)
    verify_saved(out / "verified.json", state=adapter.state, inspector=adapter.inspect_result)
    if adapter.state is not None:
        adapter.state.finish_publication(out)
    return receipt


def verify_saved(path, *, state=None, inspector=None):
    """Reinspect arbitrary production ZIPs; bind labels to a selected frozen study.

    A receipt cannot select its own trusted study or reader. The explicit
    synthetic fixture branch remains protocol evidence only.
    """
    path = Path(path).absolute()
    v = read(path)
    expected = {"schema", "label", "authority", "native_resume_authority", "study_manifest_sha256",
        "design_id", "original_root_identity", "original_input_sha256", "common_projection_sha256",
        "anchor_seconds", "bucket_seconds", "binding", "objective", "assumptions", "mass", "result",
        "inspector_process", "view", "server_plan", "compute"}
    if v.get("schema") == "KAZE_VERIFIED_RESULT_V2":
        expected.add("case_identity")
    fields(v, expected, "verified result receipt")
    if v["schema"] not in ("KAZE_VERIFIED_RESULT_V1", "KAZE_VERIFIED_RESULT_V2") or v["authority"] != "ENGINE_INSPECTOR_DATA_ONLY" or v["native_resume_authority"] is not False:
        raise Refusal("VERIFIED_RESULT_RECEIPT")
    p = inside(path.parent, v["result"]["path"])
    if file_digest(p) != sha(v["result"]["sha256"]) or p.stat().st_size != v["result"]["bytes"]:
        raise Refusal("SAVED_RESULT_DRIFT")
    if v["label"] != FIXTURE:
        if state is None:
            raise Refusal("INDEPENDENT_FROZEN_STUDY_REQUIRED_FOR_SAVED_PROVENANCE")
        study = state.study
        design = next((d for d in study.catalogue.designs if d.design_id == v["design_id"]), None)
        if design is None:
            raise Refusal("SAVED_DESIGN_NOT_IN_FROZEN_MANIFEST")
        expected_pins = dict(label=study.spec["mode"], study_manifest_sha256=study.manifest_sha256,
            original_root_identity=design.root_identity, original_input_sha256=design.original_sha256,
            common_projection_sha256=study.catalogue.common_sha256, anchor_seconds=study.catalogue.anchor_seconds,
            bucket_seconds=study.catalogue.bucket_seconds, binding=study.spec["binding"], objective=study.spec["objective"],
            assumptions=design.assumptions, mass=design.mass, case_identity=design.pins)
        if any(v.get(k) != value for k, value in expected_pins.items()):
            raise Refusal("SAVED_FROZEN_CASE_PROVENANCE_SUBSTITUTION")
        record = state.design(design.design_id)
        if v["server_plan"] is not None:
            trusted_raw = read_bytes(record["plan_path"])
            if digest(trusted_raw) != record["plan_sha"] or parse(trusted_raw) != v["server_plan"]:
                raise Refusal("SAVED_INDEPENDENT_PLAN_PIN")
        from .inspection import inspect_data
        if inspector is None:
            r = study.spec["resources"]
            state.charge_control(r["control_timeout_seconds"], "SAVED_DATA_REINSPECTION")
            from .locking import FileLock
            with FileLock(state.pool.with_suffix(".control.lock")):
                fresh_view, fresh_sha, _ = inspect_data(p, timeout=r["control_timeout_seconds"], rss_cap=min(256 * 2**20, r["control_rss_bytes"]))
        else:
            fresh_view, fresh_sha, _ = inspector(p)
        if fresh_sha != v["result"]["sha256"] or fresh_view != v["view"]:
            raise Refusal("SAVED_AUTHORITATIVE_REINSPECTION_MISMATCH")
    process = v["inspector_process"]
    if process.get("returncode") != 0 or process.get("reason") is not None or process.get("reaped") is not True:
        raise Refusal("INSPECTOR_NOT_SUCCESSFULLY_REAPED")
    stdout = process["stdout_text"].encode("utf-8")
    if digest(stdout) != process["stdout_sha256"] or len(stdout) != process["stdout_bytes"] or canonical(parse(stdout)) != canonical(v["view"]):
        raise Refusal("INSPECTOR_SAVED_OUTPUT_BINDING")
    data = read_result_data(p)
    if canonical(data["view.json"]) != canonical(v["view"]):
        raise Refusal("SAVED_INSPECTOR_VIEW_SUBSTITUTION")
    validate_view(v["view"], anchor=v["anchor_seconds"], requested_end=v["view"]["requested_end_seconds"], mode=v["label"])
    view, plan = v["view"], v["server_plan"]
    if plan is None:
        if v["label"] == FIXTURE:
            raise Refusal("FIXTURE_REQUIRES_PROTOCOL_PLAN")
        verify_initial_result_lineage(view, data, study, design)
        return v
    if (view["source_manifest_sha256"] != v["binding"]["source_sha256"] or view["root_identity"] != plan["root_identity"] or
            view["input_sha256"] != plan["input_sha256"] or plan["original_sha256"] != v["original_input_sha256"] or
            plan["duration_derivation"].get("original_root_identity") != v["original_root_identity"] or
            view["backend_binding"] != plan["execution_authority"]["binding"]["backend_binding"] or
            identity(data["execution-contract.json"]) != view["execution_contract_sha256"]):
        raise Refusal("SAVED_LINEAGE_SUBSTITUTION")
    if v["label"] != FIXTURE:
        verify_lineage(view, data, study, design, plan)
    return v


def design_compute(state, design_id):
    snapshot = state.snapshot()
    known = unknown = 0
    for lease in snapshot["leases"]:
        if lease["design"] != design_id:
            continue
        if lease["active"]:
            unknown += lease["wall_reserved"]
        else:
            known += lease["wall_observed"] or 0
    cost = state.study.spec["cost"]
    return dict(owned_worker_wall_seconds=known, unknown_reserved_worker_seconds=unknown,
        parent_and_controls="REPORTED_AT_STUDY_LEVEL_NOT_SILENTLY_ALLOCATED",
        compute_envelope_cost=None if cost is None else str(Decimal(known + unknown) / 3600 * Decimal(cost["rate"])),
        currency=None if cost is None else cost["currency"], provider_cap=False)


def number(value):
    if value is None:
        return None
    if type(value) is list and len(value) == 2 and all(type(x) is str and len(x) <= 1235 for x in value):
        try:
            q = Fraction(int(value[0]), int(value[1]))
            if [str(q.numerator), str(q.denominator)] != value:
                raise ValueError("noncanonical rational")
            with localcontext() as ctx:
                ctx.prec = 28
                return str(Decimal(q.numerator) / Decimal(q.denominator))
        except (ValueError, ZeroDivisionError) as error:
            raise Refusal("REPORT_RATIONAL") from error
    if type(value) in (int, float, str):
        return value
    if type(value) is dict:
        return {key: number(x) for key, x in value.items()}
    raise Refusal("REPORT_METRIC_TYPE")


def reduce_result(record):
    view = record["view"]; totals = view["primary_totals"] or {}
    primary = [j for j in view["jobs"] if j["role"] == "PRIMARY" and j["scientific_file"] is not None]
    latest = max(primary, key=lambda j: j["clock"]) if primary else None
    terminal = None if latest is None else latest["terminal"]
    sums = totals.get("sums", {}); wear = totals.get("wear_end", {})
    return dict(design_id=record["design_id"], label=record["label"],
        actual_start_seconds=record["anchor_seconds"], actual_end_seconds=view["actual_end_seconds"],
        actual_duration_seconds=view["actual_end_seconds"] - record["anchor_seconds"],
        requested_end_seconds=view["requested_end_seconds"],
        complete_horizon=view["actual_end_seconds"] == view["requested_end_seconds"] and terminal is not None and terminal["kind"] == "TARGET",
        actual_support_reaches_requested_end=view["actual_end_seconds"] == view["requested_end_seconds"],
        terminal=terminal, on_time_credits=totals.get("credits"), delivered_useful_bits=totals.get("useful_bits"),
        total_delivered_including_late=None, expired=totals.get("expired"), offered=totals.get("offered"),
        priority_score=totals.get("priority_score"), energy_min_wh=number(totals.get("minimum_energy_wh")),
        energy_end_wh=number(totals.get("end_energy_wh")), unmet_load_wh=number(sums.get("unmet_load_wh")),
        temperature_min_k=number(totals.get("minimum_temperature_k")), temperature_max_k=number(totals.get("maximum_temperature_k")),
        ageing=number(wear), mass=record["mass"], assumptions=record["assumptions"], compute=record["compute"],
        fixed_bucket_seconds=record["bucket_seconds"], bucket_calendar="FIXED_DURATION_NOT_GREGORIAN_MONTH",
        monthly_actual=view["monthly_actual"], monthly_environment=view["monthly_environment"],
        cumulative_work=view["cumulative_work"], primary_segments=len(primary),
        excluded_diagnostic_jobs=sum(j["role"] == "DIAGNOSTIC" for j in view["jobs"]),
        credit_rule=SCOPE, root_identity=view["root_identity"], source_manifest_sha256=view["source_manifest_sha256"],
        backend_binding=view["backend_binding"], result_sha256=record["result"]["sha256"],
        case_identity=record.get("case_identity"),
        project_metadata=(record.get("case_identity") or {}).get('project_metadata'))


def compare(paths, *, state=None):
    paths = list(paths)
    if not 1 <= len(paths) <= 128:
        raise Refusal("COMPARISON_POPULATION")
    # Bound aggregate in-memory DATA before decoding all per-design views.
    if sum(no_links(path).stat().st_size for path in paths if Path(path).exists()) > MAX_COMPARISON_RECEIPT_BYTES:
        raise Refusal("COMPARISON_DATA_BYTES")
    records = [verify_saved(path, state=state) for path in paths]
    if not records:
        raise Refusal("NO_VERIFIED_RESULTS")
    first = records[0]; ids = set(); histories = set(); inputs = set()
    for record in records:
        if record["design_id"] in ids:
            raise Refusal("CUMULATIVE_ENDPOINT_DOUBLE_COUNT", record["design_id"])
        ids.add(record["design_id"])
        view = record["view"]
        # A causal history is identified by bound execution/input/job provenance,
        # not the editable presentation label or scientific totals alone.
        input_pin = (record.get("original_root_identity", view["root_identity"]), record.get("original_input_sha256", view["input_sha256"]), view["source_manifest_sha256"])
        if input_pin in inputs:
            raise Refusal("DUPLICATE_CAUSAL_INPUT_PROVENANCE")
        inputs.add(input_pin)
        for job in view["jobs"]:
            causal = (view["input_sha256"], view["execution_contract_sha256"], job["job_id"])
            if causal in histories:
                raise Refusal("DUPLICATE_OR_OVERLAPPING_CAUSAL_HISTORY")
            histories.add(causal)
        if any(record[key] != first[key] for key in ("label", "common_projection_sha256", "binding", "objective", "anchor_seconds", "bucket_seconds")):
            raise Refusal("INCOMPARABLE_WORLD_SOURCE_RUNTIME_BACKEND_OR_OBJECTIVE")
    rows = [reduce_result(record) for record in records]
    common = len({(row["actual_start_seconds"], row["actual_end_seconds"]) for row in rows}) == 1
    objective = first["objective"]
    ranking = None
    if objective is not None and common:
        key = {"credits": "on_time_credits", "useful_bits": "delivered_useful_bits", "priority_score": "priority_score"}[objective["metric"]]
        if all(row[key] is not None for row in rows):
            ranking = sorted([dict(design_id=row["design_id"], value=row[key]) for row in rows],
                             key=lambda row: Decimal(str(row["value"])), reverse=objective["direction"] == "max")
    return dict(schema="KAZE_STUDY_REPORT_V1", label=first["label"], rows=rows,
        common_support=common, declared_objective=objective, ranking=ranking,
        ranking_scope="DECLARED_OBJECTIVE_ON_IDENTICAL_ACTUAL_SUPPORT_ONLY",
        hardware_winner_claimed=False, scientific_completion_claimed=False,
        native_resume_authority=False, source_manifest_sha256=first["binding"]["source_sha256"],
        common_projection_sha256=first["common_projection_sha256"], study_manifest_sha256=first.get("study_manifest_sha256"),
        missing_metric_note="total_delivered_including_late is unavailable in the current engine view; no inferred total",
        provider_warning="Software Stop does not stop VM billing; these are owned compute envelopes, not provider spend caps.")


def export_reports(report, output, *, state=None):
    output = no_links(output)
    if output.exists():
        raise Refusal("NEW_REPORT_DIRECTORY_REQUIRED")
    report_bytes = canonical(report)
    if len(report_bytes) > MAX_COMPARISON_RECEIPT_BYTES:
        raise Refusal("REPORT_DATA_BYTES")
    columns = ("design_id", "label", "actual_duration_seconds", "actual_end_seconds", "requested_end_seconds",
               "complete_horizon", "on_time_credits", "delivered_useful_bits", "expired", "energy_min_wh", "energy_end_wh",
               "unmet_load_wh", "temperature_min_k", "temperature_max_k", "ageing", "mass", "compute", "terminal",
               "case_identity", "project_metadata")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns); writer.writeheader()
    for row in report["rows"]:
        flat = {key: json.dumps(row[key], ensure_ascii=False, sort_keys=True) if type(row[key]) in (dict, list) else row[key] for key in columns}
        # Stop spreadsheet formula evaluation for untrusted text cells.
        flat = {key: "'" + value if type(value) is str and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for key, value in flat.items()}
        writer.writerow(flat)
    csv_bytes = stream.getvalue().encode("utf-8-sig")
    head = "".join("<th>" + html.escape(key) + "</th>" for key in columns)
    body = []
    for row in report["rows"]:
        body.append("<tr>" + "".join("<td>" + html.escape(str(row[key])) + "</td>" for key in columns) + "</tr>")
    document = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
    document += '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
    document += '<title>KazEOSat study report</title><style>body{font:15px system-ui;margin:2em;background:#fafafa;color:#18212b}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.45em;vertical-align:top}th{background:#dfe9ef}pre{white-space:pre-wrap;overflow-wrap:anywhere}.scroll{overflow:auto}</style>'
    document += "<h1>KazEOSat — " + html.escape(report["label"]) + "</h1><p>" + html.escape(report["ranking_scope"]) + "</p>"
    document += "<p>30-day buckets are fixed durations, not Gregorian months. Incomplete prefixes and physical terminals remain visible.</p>"
    document += '<div class="scroll"><table><thead><tr>' + head + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    # Stream the large provenance section; escaping cannot multiply the entire
    # report into several simultaneous in-memory copies.
    def html_chunks():
        yield document.encode("utf-8")
        yield "<h2>Полные данные и provenance</h2><pre>".encode("utf-8")
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False, indent=2).iterencode(report):
            yield html.escape(chunk).encode("utf-8")
        yield b"</pre></html>"
    expected_output = len(report_bytes) + len(csv_bytes)
    for chunk in html_chunks():
        expected_output += len(chunk)
        if expected_output > 256 * 2**20:
            raise Refusal("REPORT_OUTPUT_BYTES")
    if state is not None:
        state.reserve_publication(output, "REPORT_CSV_JSON_HTML", expected_output + 65536)
    output.mkdir(parents=True)
    write_new(output / "report.json", report_bytes)
    write_new(output / "report.csv", csv_bytes)
    with (output / "report.html").open("xb") as stream:
        for chunk in html_chunks():
            stream.write(chunk)
        stream.flush(); os.fsync(stream.fileno())
    if state is not None:
        state.finish_publication(output)
    return {name: file_digest(output / name) for name in ("report.json", "report.csv", "report.html")}

