"""Fixed serverctl consumer. Physical authority stays in the frozen engine.

B63 is a parser/source reference, never an accepted execution release. A new
freeze is a new immutable binding revision; no backend fallback or store retag.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import importlib.metadata
from pathlib import Path
import re
import sys

from .catalogue import FIXTURE
from .contract import B63_SOURCE, PENDING, acceptance_references, admit_binding, design_acceptance
from .data import canonical, digest, fields, file_digest, identity, inside, integer, no_links, parse, read, read_bytes, reference, sha
from .errors import Refusal
from .locking import FileLock
from .lineage import project_owner_source
from .process import ProcessRunner
from .protocol import B65, family

PLAN_FORMAT = "B63_PREPARED_SERVER_PLAN_V2"
RESULT_FORMAT = "B63_READ_ONLY_PREPARED_LIFETIME_RESULT_V2"
FIXTURE_RESULT = "KAZE_PROTOCOL_FIXTURE_RESULT_V1"
TERMINAL = {"TARGET", "RESOURCE_TIME", "RESOURCE_OUTPUT", "USER", "PHYSICAL", "MODEL", "UNSUPPORTED", "PROCESS_FAILURE", "UNKNOWN"}
BASE_PLAN_FIELDS = {"format", "mode", "duration_seconds", "root_identity", "original_input", "duration_input", "input_file",
    "original_sha256", "duration_sha256", "input_sha256", "duration_derivation", "accounting_derivation", "policy", "policy_identity",
    "source_manifest", "source_manifest_sha256", "preparation_runtime", "prospective_store_reservation_bytes",
    "shared_pool_reservation_including_backup_bytes", "cost_scenario", "native_import", "qualification", "engine_entrypoint",
    "backend", "native_build", "execution_mode", "execution_authority", "execution_contract_sha256", "plan_identity"}
SUMMARY_FIELDS = {"plan_identity", "root_identity", "target_seconds", "source_identity", "runtime", "jobs", "primary_jobs",
    "diagnostic_jobs", "observed_seconds", "diagnostic_observed_seconds", "reserved_unknown_seconds", "clock", "parent_job_id",
    "typed_terminal", "operator_pause", "mode", "qualification", "execution_authority_sha256", "backend_binding", "runner_store_format"}


def backend_binding(spec):
    b = spec["binding"]
    wire = family(b["protocol"])
    build = None
    if b["build"] is not None:
        # Receipt canonical identity differs from the transport raw hash.
        build = b["build"]
    return dict(format=wire.backend_format, method=wire.backend_method,
                selection=b["backend"], build_sha256=None if build is None else build.get("canonical_sha256", build["sha256"]),
                capability_sha256=b["capability_sha256"])


def validate_summary_data(value, plan, study):
    fields(value, SUMMARY_FIELDS, "serverctl V2 summary")
    b = study.spec["binding"]
    owner_source = project_owner_source(parse(study.source_bytes), fixture=study.spec["mode"] == FIXTURE)
    if (value["root_identity"] != plan["root_identity"] or value["source_identity"] != owner_source or
            value["target_seconds"] != study.catalogue.anchor_seconds + study.spec["horizon_seconds"] or
            value["execution_authority_sha256"] != identity(plan["execution_authority"]) or
            value["backend_binding"] != plan["execution_authority"]["binding"]["backend_binding"]):
        raise Refusal("STATUS_LINEAGE_MISMATCH")
    expected_runtime = plan["execution_authority"]["binding"].get("runtime")
    if value["runtime"] != expected_runtime:
        raise Refusal("STATUS_RUNTIME_MISMATCH")
    integer(value["clock"], "actual prefix", study.catalogue.anchor_seconds, value["target_seconds"])
    for name in ("jobs", "primary_jobs", "diagnostic_jobs", "reserved_unknown_seconds"):
        integer(value[name], name)
    if value["jobs"] != value["primary_jobs"] + value["diagnostic_jobs"]:
        raise Refusal("STATUS_JOB_COUNTS")
    terminal = value["typed_terminal"]
    if type(value["operator_pause"]) is not bool or value["mode"] != plan["policy"]["mode"]:
        raise Refusal("STATUS_POLICY_OR_PAUSE_TYPE")
    if terminal is not None:
        fields(terminal, ("format", "kind", "code", "stage", "owner", "clock", "automatic_resume"), "typed terminal")
        if terminal["format"] != "B59_TYPED_TERMINAL_V1" or terminal["kind"] not in TERMINAL:
            raise Refusal("TYPED_TERMINAL_PROTOCOL")
        if terminal["automatic_resume"] is not (terminal["kind"] in ("RESOURCE_TIME", "RESOURCE_OUTPUT")):
            raise Refusal("TYPED_TERMINAL_CONTINUATION")
        if terminal["clock"] is not None and terminal["clock"] != value["clock"]:
            raise Refusal("TERMINAL_CLOCK_MISMATCH")
        if terminal["kind"] == "TARGET" and value["clock"] != value["target_seconds"]:
            raise Refusal("TARGET_WITHOUT_FULL_ACTUAL_PREFIX")
    return value



class EngineAdapter:
    def __init__(self, study, engine, interpreter, *, state=None, runner=None, protocol_fixture=False):
        self.study = study; self.spec = study.spec; self.state = state
        self.wire = family(self.spec["binding"]["protocol"])
        self.engine = no_links(engine).resolve()
        # Executable is an explicit trusted CLI path, including a venv symlink.
        # Preserve its exact argv/runtime name; hash its resolved binary target.
        self.interpreter = Path(interpreter).absolute()
        no_links(self.interpreter.resolve())
        if not self.interpreter.is_file():
            raise Refusal("ABSOLUTE_INTERPRETER_NOT_FOUND")
        self.fixture = self.spec["mode"] == FIXTURE
        if self.fixture != protocol_fixture:
            raise Refusal("EXPLICIT_PROTOCOL_FIXTURE_OPT_IN_REQUIRED")
        if self.fixture:
            expected = Path(__file__).resolve().parents[1] / "fixtures" / "protocol_engine"
            if self.engine != expected:
                raise Refusal("FIXED_PROTOCOL_FIXTURE_ENTRYPOINT_ONLY")
        self.entrypoint = self.engine / "kit" / "serverctl.py"
        if not self.entrypoint.is_file():
            raise Refusal("ENGINE_SERVERCTL_NOT_FOUND")
        self.runner = runner or ProcessRunner(maximum_children=2 if self.fixture else self.spec["concurrency"] + 1)
        self._checked = False

    def check_source(self):
        expected = parse(self.study.source_bytes)
        actual_names = set()
        for path in self.engine.rglob("*"):
            no_links(path)
            if path.is_file():
                actual_names.add(path.relative_to(self.engine).as_posix())
                if len(actual_names) > 2000:
                    raise Refusal("ENGINE_SOURCE_POPULATION")
        if actual_names != set(expected):
            raise Refusal("ENGINE_SOURCE_MEMBERSHIP_DRIFT")
        for name, record in expected.items():
            raw = read_bytes(inside(self.engine, name), 16 * 2**20)
            if len(raw) != record["bytes"] or digest(raw) != record["sha256"]:
                raise Refusal("ENGINE_SOURCE_DRIFT", name)
        self._checked = True

    def check_execution(self):
        self.check_source()
        if self.study.manifest_path and read_bytes(self.study.manifest_path) != self.study.raw:
            raise Refusal("STUDY_MANIFEST_DRIFT")
        for ref in (self.spec["catalogue"], self.spec["policy"], self.spec["binding"]["source_manifest"]):
            reference(self.study.root, ref)
        binding = self.spec["binding"]
        admit_binding(binding, self.study.root, self.spec["mode"])
        if not self.fixture and (binding["freeze"] not in ("FROZEN_B64", "FROZEN_B65") or binding["source_sha256"] == B63_SOURCE):
            raise Refusal("FROZEN_B65_TARGET_BINDING_REQUIRED" if self.wire == B65 else PENDING)
        if Path(sys.executable).absolute() != self.interpreter:
            # Run this companion under the bound interpreter so metadata checks
            # below observe the same runtime that will host serverctl.
            raise Refusal("RUN_COMPANION_WITH_BOUND_INTERPRETER")
        expected = binding["runtime"]
        if expected["python"] != sys.version or expected["platform"] != sys.platform:
            raise Refusal("ENGINE_RUNTIME_MISMATCH")
        if expected["executable"] != str(self.interpreter) or expected["interpreter_sha256"] != file_digest(self.interpreter.resolve(), 128 * 2**20):
            raise Refusal("ENGINE_INTERPRETER_IDENTITY_MISMATCH")
        if not self.fixture and not sys.platform.startswith("linux"):
            raise Refusal("LINUX_RUNTIME_REQUIRED")
        if not self.fixture:
            requirements_raw = read_bytes(self.engine / "requirements.txt")
            if digest(requirements_raw) != expected["requirements_sha256"]:
                raise Refusal("RUNTIME_REQUIREMENTS_DRIFT")
            requirements_text = requirements_raw.decode("utf-16") if requirements_raw.startswith((b"\xff\xfe", b"\xfe\xff")) else requirements_raw.decode("utf-8-sig")
            pins = {}
            for line in requirements_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
                if match is None or match[1].lower() in pins:
                    raise Refusal("EXACT_RUNTIME_DEPENDENCY_PINS_REQUIRED")
                pins[match[1].lower()] = match[2]
            if pins != expected["dependency_versions"]:
                raise Refusal("RUNTIME_DEPENDENCY_CATALOGUE_MISMATCH")
            for name, version in expected["dependency_versions"].items():
                try:
                    observed = importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError:
                    observed = None
                if observed != version:
                    raise Refusal("PINNED_DEPENDENCY_MISMATCH", name)
            if self.spec["execution_mode"] == "long" and binding["acceptance"] is None:
                raise Refusal("GENUINE_LINUX_ACCEPTANCE_REQUIRED")
        for ref in (binding["build"], binding["repair_evidence"], *acceptance_references(binding["acceptance"])):
            if ref is not None:
                reference(self.study.root, ref)
        if not self.fixture:
            from .envelope import production_envelope
            self.envelope = production_envelope(self.spec["resources"])
            if self.wire == B65:
                self.typed_capability()

    def argv(self, command, args):
        allowed = {"doctor", "typed-capability", "qualify-protocol", "estimate", "plan", "run", "status", "stop", "resume", "export-result", "inspect-result"}
        if command not in allowed:
            raise Refusal("FIXED_ENGINE_COMMAND_ONLY")
        return [str(self.interpreter), "-B", str(self.entrypoint), "--engine", str(self.engine), command, *map(str, args)]

    def _command(self, command, args, *, dispatch=False, on_spawn=None, launch_guard=None, timeout=None):
        if dispatch:
            self.check_execution()
        else:
            self.check_source()
        r = self.spec["resources"]
        duration = timeout if timeout is not None else r["control_timeout_seconds"]
        if not dispatch and self.state is not None:
            self.state.charge_control(duration, command)
        def invoke():
            return self.runner.run(self.argv(command, args), cwd=str(self.engine), timeout=duration,
                stdout_cap=r["stdout_bytes"], stderr_cap=r["stderr_bytes"],
                # This samples the direct supervisor only. Aggregate enforcement
                # is supplied by the observed cgroup, not this PID measurement.
                rss_cap=128 * 2**20 if self.fixture else r["supervisor_rss_bytes"] if dispatch else r["control_rss_bytes"],
                on_spawn=on_spawn, launch_guard=launch_guard)
        if not dispatch and self.state is not None:
            with FileLock(self.state.pool.with_suffix(".control.lock")):
                result = invoke()
        else:
            result = invoke()
        if result.reason is not None or result.returncode != 0:
            return result, None
        # Parse the ENTIRE stdout. Any prefix/suffix/noise/second JSON is refused.
        try:
            value = parse(result.stdout, r["stdout_bytes"])
        except Refusal:
            return result, None
        if type(value) is not dict:
            return result, None
        return result, value

    @staticmethod
    def require_ok(result, value):
        if value is None:
            raise Refusal("ENGINE_COMMAND_FAILED", result.evidence())
        return value

    def doctor(self):
        result, value = self._command("doctor", [])
        value = self.require_ok(result, value)
        if value.get("format") != "KAZEOSAT_SERVER_DOCTOR_V1" or value.get("source_manifest_sha256") != self.spec["binding"]["source_sha256"]:
            raise Refusal("DOCTOR_SOURCE_OR_PROTOCOL_MISMATCH")
        return dict(engine=value, compatibility=self.spec["binding"]["freeze"],
                    science_executed=False, long_acceptance=False)

    def typed_capability(self):
        if self.wire != B65 or self.fixture:
            raise Refusal("TYPED_CAPABILITY_REQUIRES_B65")
        build_path, raw = reference(self.study.root, self.spec["binding"]["build"], 65536)
        build = parse(raw)
        result, value = self._command("typed-capability", ["--build", str(build_path)])
        v = self.require_ok(result, value)
        fields(v, ("format", "backend", "profile", "source_manifest_sha256", "runtime", "build_sha256", "artifact", "caps",
            "current_native_entry_counts", "doctor", "ready_for_pilot", "long_dispatch", "long_requires", "checkpoint_migration", "physical_qualification"), "actual typed capability")
        if (v["format"] != "B65_TYPED_SERVER_CAPABILITY_V1" or v["backend"] != B65.backend_method or
                v["source_manifest_sha256"] != self.spec["binding"]["source_sha256"] or
                v["build_sha256"] != identity(build) or v["runtime"] != build["runtime"] or
                v["artifact"] != build["artifact"] or v["caps"] != build["capabilities"]["limits"] or
                v["profile"] != "B65_LINUX_X86_64_CPYTHON314_GCC_V1" or v["profile"] != build["profile"] or
                v["ready_for_pilot"] is not True or v["long_dispatch"] is not False or
                v["long_requires"] != "PER_DESIGN_GENUINE_TARGET_DAY_REFERENCE_AND_NATIVE_CONTINUATION_EVIDENCE" or
                v["checkpoint_migration"] is not False or v["physical_qualification"] is not False):
            raise Refusal("ACTUAL_TYPED_CAPABILITY_OR_PERMISSION_MISMATCH")
        doctor = v["doctor"]
        if (doctor.get("source_manifest_sha256") != v["source_manifest_sha256"] or
                doctor.get("ready_for_engine_attempt") is not True or not doctor.get("checks") or
                any(x is not True for x in doctor["checks"].values()) or
                doctor.get("runtime") != {k: self.spec["binding"]["runtime"][k] for k in ("python", "platform", "executable")}):
            raise Refusal("ACTUAL_CAPABILITY_DOCTOR_BINDING")
        monitor = v["current_native_entry_counts"]
        fields(monitor, ("format", "method", "limit", "total", "counts", "exhausted", "gil_held", "reset_available",
            "python_implementation", "python_cache_tag", "python_version", "platform", "module_basename", "source_binding", "scope"), "B65 actual native monitor")
        counts = monitor.get("counts") if type(monitor) is dict else None
        if (type(counts) is not dict or set(counts) != set(build["capabilities"]["entry_monitor"]["names"]) or
                monitor.get("format") != "B65_MONOTONE_TYPED_ENTRY_COUNTS_V2" or
                monitor.get("method") != "B65_TYPED_NUMERICAL_ENTRY_MONITOR_V2" or monitor.get("limit") != 2**56 or
                monitor.get("exhausted") is not False or monitor.get("gil_held") is not True or monitor.get("reset_available") is not False or
                monitor.get("source_binding") != "ACTUAL_EXTENSION_AND_SOURCE_BUILD_RECEIPT_REQUIRED" or
                monitor.get("scope") != "OPERATIONAL_ENTRY_ATTEMPTS_NOT_SCIENTIFIC_WORK_OR_DYNAMIC_STATE" or
                any(monitor.get(k) != expected for k, expected in dict(python_implementation=build["runtime"]["implementation"],
                    python_cache_tag=build["runtime"]["cache_tag"], python_version=build["runtime"]["python"],
                    platform=build["runtime"]["platform"], module_basename=Path(build["artifact"]["path"]).name).items())):
            raise Refusal("ACTUAL_NATIVE_ENTRY_COUNTERS")
        for count in counts.values():
            integer(count, "actual native entries", 0, 2**56)
        if monitor.get("total") != sum(counts.values()):
            raise Refusal("ACTUAL_NATIVE_ENTRY_BALANCE")
        if self.state is not None:
            self.state.event("ACTUAL_TYPED_CAPABILITY", {"value": v, "process": result.evidence(), "long_acceptance": False})
        return v

    def qualify_protocol(self, output):
        # Explicit caller only. Never called by doctor, open, status or planning.
        self.check_execution()
        result, value = self._command("qualify-protocol", ["--output", str(Path(output).absolute())])
        return self.require_ok(result, value)

    def estimate(self, *, years, designs, parallel, rate, setup="0", speedup="1"):
        result, value = self._command("estimate", ["--years", years, "--designs", designs, "--parallel", parallel,
            "--rate", rate, "--setup", setup, "--speedup", speedup])
        value = self.require_ok(result, value)
        if value.get("format") != "KAZEOSAT_CONDITIONAL_COST_SCENARIO_V1":
            raise Refusal("ESTIMATE_PROTOCOL")
        return value

    def plan(self, design, output):
        self.check_execution()
        p = Path(output).absolute()
        if p.exists():
            raise Refusal("NEW_ENGINE_PLAN_REQUIRED")
        if digest(read_bytes(design.input_path, 8 * 2**20)) != design.original_sha256:
            raise Refusal("INPUT_DRIFT_BEFORE_ENGINE_PLAN")
        cost_policy = self.spec["cost"]
        if cost_policy is None:
            raise Refusal("ENGINE_PLAN_REQUIRES_EXPLICIT_RATE_AND_ESTIMATE_CAP")
        cost = cost_policy["engine_scenario"]
        _, policy_raw = reference(self.study.root, self.spec["policy"], 65536)
        policy = parse(policy_raw)
        from .resources import decimal
        decimal(cost["rate"], "serverctl positive scenario rate")
        plan_cap = cost["cap"]
        if plan_cap is None:
            declared_wall = policy.get("maximum_observed_primary_seconds", 0) + policy.get("maximum_diagnostic_seconds", 0)
            # A derived per-plan scenario bound is not a user/provider spend cap.
            plan_cap = str(Decimal(declared_wall) / 3600 * Decimal(cost["rate"]) + Decimal(cost["setup"]) + Decimal("0.000000001"))
        args = ["--input", design.input_path, "--output", p, "--seconds", self.spec["horizon_seconds"],
            "--policy", reference(self.study.root, self.spec["policy"], 65536)[0], "--rate", cost["rate"],
            "--currency", cost["currency"], "--max-cost", plan_cap, "--setup", cost["setup"],
            "--mode", self.spec["execution_mode"], "--backend", self.spec["binding"]["backend"]]
        if self.spec["binding"]["build"] is not None:
            args.extend(("--build", reference(self.study.root, self.spec["binding"]["build"])[0]))
        acceptance = design_acceptance(self.spec["binding"], design.design_id) if self.spec["execution_mode"] == "long" else None
        if acceptance is not None:
            args.extend(("--acceptance", reference(self.study.root, acceptance)[0]))
        result, value = self._command("plan", args)
        self.require_ok(result, value)
        raw = read_bytes(p)
        saved = self.validate_plan(p, design)
        if canonical(value) != canonical(saved):
            raise Refusal("PLAN_STDOUT_SAVED_MISMATCH")
        return saved, digest(raw)

    def validate_plan(self, path, design):
        p = Path(path).absolute(); v = read(p)
        fields(v, BASE_PLAN_FIELDS, "serverctl V2 plan")
        if v["format"] != self.wire.plan or v["plan_identity"] != identity({k: x for k, x in v.items() if k != "plan_identity"}):
            raise Refusal("PLAN_FORMAT_OR_IDENTITY")
        if (v["source_manifest_sha256"] != self.spec["binding"]["source_sha256"] or
                canonical(v["source_manifest"]) != self.study.source_bytes or v["original_sha256"] != design.original_sha256 or
                v["backend"] != self.spec["binding"]["backend"] or v["mode"] != self.spec["execution_mode"] or
                v["execution_mode"] != self.spec["execution_mode"].upper() or v["duration_seconds"] != self.spec["horizon_seconds"] or
                v["preparation_runtime"] != dict(python=self.spec["binding"]["runtime"]["python"], platform=self.spec["binding"]["runtime"]["platform"])):
            raise Refusal("EXACT_PLAN_SOURCE_INPUT_BACKEND_RUNTIME_BINDING")
        if v["duration_derivation"].get("original_root_identity") != design.root_identity:
            raise Refusal("ORIGINAL_ROOT_IDENTITY_MISMATCH")
        if v["engine_entrypoint"] != "m8_lifetime_campaign_cli.py" or v["native_import"] is not False:
            raise Refusal("PLAN_EXECUTION_ENTRYPOINT")
        if v["duration_derivation"].get("original_anchor_seconds") != self.study.catalogue.anchor_seconds:
            raise Refusal("PLAN_ORIGINAL_ANCHOR")
        for name, pin in (("original_input", "original_sha256"), ("duration_input", "duration_sha256"), ("input_file", "input_sha256")):
            if type(v[name]) is not str or "/" in v[name] or "\\" in v[name]:
                raise Refusal("PLAN_INPUT_PATH")
            if digest(read_bytes(inside(p.parent, v[name]), 8 * 2**20)) != sha(v[pin]):
                raise Refusal("PLAN_INPUT_DRIFT")
        _, policy = reference(self.study.root, self.spec["policy"], 65536)
        if canonical(v["policy"]) != canonical(parse(policy)) or v["policy_identity"] != identity(v["policy"]):
            raise Refusal("PLAN_POLICY_MISMATCH")
        expected_build = None if self.spec["binding"]["build"] is None else parse(reference(self.study.root, self.spec["binding"]["build"])[1])
        if v["native_build"] != expected_build:
            raise Refusal("PLAN_BUILD_MISMATCH")
        authority = v["execution_authority"]
        fields(authority, ("format", "mode", "binding", "acceptance", "pilot_limits", "identity"), "execution authority")
        if authority["format"] != "B63_LIFETIME_EXECUTION_AUTHORITY_V1" or authority.get("mode") != self.spec["execution_mode"].upper():
            raise Refusal("PLAN_AUTHORITY_MODE")
        if authority["identity"] != identity({k: x for k, x in authority.items() if k != "identity"}):
            raise Refusal("PLAN_AUTHORITY_IDENTITY")
        if authority["pilot_limits"] != dict(duration_seconds=86400, primary_segments=8, diagnostic_slots=2, hard_seconds=240):
            raise Refusal("PLAN_AUTHORITY_PILOT_LIMITS")
        body = fields(authority["binding"], ("root_identity", "input_sha256", "source_manifest_sha256", "runtime",
            "execution_contract_sha256", "policy_identity", "backend_binding", "domain_identity", "original_anchor_seconds", "duration_seconds"), "authority binding")
        expected_runtime = {k: self.spec["binding"]["runtime"][k] for k in ("python", "platform", "executable", "interpreter_sha256")}
        expected_backend = backend_binding(self.spec)
        if expected_build is not None:
            expected_backend["build_sha256"] = identity(expected_build)
        if (body.get("input_sha256") != v["input_sha256"] or body.get("root_identity") != v["root_identity"] or
                body.get("source_manifest_sha256") != v["source_manifest_sha256"] or
                body.get("execution_contract_sha256") != v["execution_contract_sha256"] or
                body.get("backend_binding") != expected_backend or body["runtime"] != expected_runtime or
                body["policy_identity"] != v["policy_identity"] or body["duration_seconds"] != self.spec["horizon_seconds"] or
                body["original_anchor_seconds"] != self.study.catalogue.anchor_seconds):
            raise Refusal("PLAN_AUTHORITY_BINDING")
        sha(body["domain_identity"])
        acceptance = design_acceptance(self.spec["binding"], design.design_id) if self.spec["execution_mode"] == "long" else None
        expected_acceptance = None if acceptance is None else dict(path=str(reference(self.study.root, acceptance)[0].absolute()),
            sha256=acceptance["sha256"], bytes=acceptance["bytes"])
        if authority["acceptance"] != expected_acceptance:
            raise Refusal("PLAN_ACCEPTANCE_REFERENCE_MISMATCH")
        integer(v["shared_pool_reservation_including_backup_bytes"], "engine pool reserve", 1)
        if not self.fixture:
            policy = v["policy"]
            if policy.get("method") != "B63_SERIAL_LIFETIME_STORE_POLICY_V2" or policy.get("mode") != "LINUX_PRODUCTION":
                raise Refusal("EXPLICIT_V2_PRODUCTION_POLICY_REQUIRED")
            store_bytes = (policy["maximum_primary_segments"] + policy["reserved_diagnostic_slots"]) * policy["maximum_output_bytes"] + policy["maximum_metadata_bytes"] + policy["initial_package_reserve_bytes"]
            if (v["prospective_store_reservation_bytes"] != store_bytes or
                    v["shared_pool_reservation_including_backup_bytes"] != store_bytes * (1 + policy["backup_copies"])):
                raise Refusal("ENGINE_POLICY_RESERVATION_MISMATCH")
        if v["shared_pool_reservation_including_backup_bytes"] > self.spec["resources"]["per_design_disk_bytes"]:
            raise Refusal("ENGINE_POOL_EXCEEDS_WRAPPER_PROMISE")
        return v

    def pinned_plan(self, design, record):
        if digest(read_bytes(design.input_path, 8 * 2**20)) != design.original_sha256:
            raise Refusal("ORIGINAL_INPUT_DRIFT")
        if digest(read_bytes(record["plan_path"])) != record["plan_sha"]:
            raise Refusal("IMMUTABLE_ENGINE_PLAN_DRIFT")
        return self.validate_plan(record["plan_path"], design)

    def validate_summary(self, value, plan):
        return validate_summary_data(value, plan, self.study)

    def status(self, design, record):
        plan = self.pinned_plan(design, record)
        result, value = self._command("status", ["--plan", record["plan_path"]])
        return self.validate_summary(self.require_ok(result, value), plan)

    def stop(self, design, record):
        plan = self.pinned_plan(design, record)
        result, value = self._command("stop", ["--plan", record["plan_path"]])
        # This is a request receipt, never a parent-settlement receipt.
        return dict(summary=self.validate_summary(self.require_ok(result, value), plan),
                    stop_requested=True, parent_settled=False, process=result.evidence())

    def execute(self, design, record, intent, timeout=None):
        plan = self.pinned_plan(design, record)
        result, value = self._command(intent["action"], ["--plan", record["plan_path"]], dispatch=True,
            launch_guard=None if self.state is None else lambda: self.state.spawn_guard(intent),
            timeout=timeout or self.spec["resources"]["per_run_wall_seconds"])
        outcome = "UNKNOWN"; settled = False; summary = None; reason = result.reason
        safe = result.reason == "NOT_CREATED"
        if safe:
            outcome = "PROCESS_FAILURE"
        elif result.reason == "TIMEOUT":
            outcome = "TIMEOUT"
        elif result.reason in ("OUTPUT_LIMIT", "RSS_LIMIT"):
            outcome = "OUTPUT_LIMIT" if result.reason == "OUTPUT_LIMIT" else "PROCESS_FAILURE"
        elif value is not None:
            try:
                fields(value, ("store", "result", "billing_still_active"), "serverctl run response")
                if Path(value["store"]).resolve() != Path(record["store_path"]).resolve() or value["billing_still_active"] is not True:
                    raise Refusal("RUN_STORE_MISMATCH")
                summary = self.validate_summary(value["result"], plan)
                terminal = summary["typed_terminal"]
                outcome = "UNKNOWN" if terminal is None else terminal["kind"]
                # Successful normal engine return includes its own close/settle
                # checks. UNKNOWN or an unobserved suffix grants no settlement.
                settled = terminal is not None and outcome not in ("UNKNOWN", "PROCESS_FAILURE") and summary["reserved_unknown_seconds"] == 0 and result.reaped
            except (Refusal, TypeError, KeyError) as error:
                reason = str(error)
        elif result.returncode not in (0, None) and result.reason is None:
            try:
                error = parse(result.stderr)
                if error.get("status") == "REFUSED_OR_FAILED":
                    outcome = "ENGINE_REFUSAL"; reason = error.get("reason")
                else:
                    outcome = "PROCESS_FAILURE"
            except (Refusal, AttributeError):
                outcome = "PROCESS_FAILURE"
            # A generic refusal may follow partial submission: keep ownership.
        process = result.evidence()
        if settled and not self.fixture:
            try:
                from .settlement import core_cleanup
                process["core_cleanup"] = core_cleanup(record["store_path"], summary, plan, result.owner, intent.get("prior_cleanup", {}))
                process["envelope"] = self.envelope
            except (Refusal, OSError, KeyError, TypeError) as error:
                settled = False; reason = str(error)
        return dict(outcome=outcome, parent_settled=settled, safe_no_submission=safe,
                    process=process, summary=summary, reason=reason)

    def export_result(self, design, record, output):
        self.pinned_plan(design, record)
        expected_parent = Path(record["store_path"] + ".exports")
        p = Path(output).absolute()
        if p.parent.resolve() != expected_parent.resolve() or p.suffix.lower() != ".zip" or p.exists():
            raise Refusal("ENGINE_RESERVED_EXPORT_DIRECTORY_REQUIRED", expected_parent)
        result, value = self._command("export-result", ["--plan", record["plan_path"], "--output", p])
        value = self.require_ok(result, value)
        if file_digest(p) != value.get("sha256"):
            raise Refusal("EXPORT_RAW_HASH")
        return value

    def inspect_result(self, path):
        raw_hash = file_digest(path)
        result, value = self._command("inspect-result", ["--input", str(Path(path).absolute())])
        value = self.require_ok(result, value)
        expected = FIXTURE_RESULT if self.fixture else self.wire.result
        if value.get("format") != expected:
            raise Refusal("RESULT_FORMAT_OR_FIXTURE_MODE")
        if file_digest(path) != raw_hash:
            raise Refusal("RESULT_CHANGED_DURING_INSPECTION")
        return value, raw_hash, result.evidence()

