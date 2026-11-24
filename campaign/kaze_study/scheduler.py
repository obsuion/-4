"""Bounded designs, one existing serial engine supervisor per design/store."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from pathlib import Path
import signal
import threading
import time
import uuid

from .data import digest, read_bytes
from .engine_adapter import EngineAdapter
from .errors import Refusal
from .locking import FileLock
from .state import State


class Scheduler:
    def __init__(self, state, *, protocol_fixture=False, adapter=None, workers=None, allowed_designs=None):
        self.state = state
        self.workers=state.study.spec['concurrency']if workers is None else workers
        if type(self.workers)is not int or not 1<=self.workers<=state.study.spec['concurrency']:raise Refusal('EXPLICIT_FINITE_WORKERS')
        self.allowed_designs=None if allowed_designs is None else frozenset(allowed_designs)
        if adapter is None and state.study.spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1':
            from .year_execution import YearEngineAdapter
            adapter=YearEngineAdapter(state)
        if adapter is None and state.study.spec['schema']=='KAZE_NAMED_PROJECT_STUDY_V1':
            from .named_execution import NamedEngineAdapter
            adapter=NamedEngineAdapter(state)
        self.adapter = adapter or EngineAdapter(state.study, state.marker["engine"], state.marker["interpreter"],
            state=state, protocol_fixture=protocol_fixture)
        self.designs = {d.design_id: d for d in state.study.catalogue.designs}
        self.shutdown_event = threading.Event()

    def prepare(self):
        """Plan-only subprocesses are explicit, durable and never retried blindly."""
        self.adapter.check_execution()
        for did, design in self.designs.items():
            if self.allowed_designs is not None and did not in self.allowed_designs:continue
            if self.state.study.spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1':
                with self.state.connection()as c:
                    if c.execute('SELECT paused FROM year_design_controls WHERE study=?AND design=?',(self.state.key,did)).fetchone()[0]:continue
            header = self.state.snapshot()["study"]
            if header["paused"] or header["shutdown"]:
                break
            record = self.state.design(did)
            if record["phase"] == "READY":
                intent = self.state.claim_plan(did)
                try:
                    plan, raw_sha = self.adapter.plan(design, record["plan_path"])
                    self.state.commit_plan(did, intent, plan, raw_sha)
                except BaseException as error:
                    with self.state.transaction() as c:
                        c.execute("UPDATE designs SET phase='PLAN_UNKNOWN' WHERE study=? AND design=?", (self.state.key, did))
                        self.state._event(c, self.state.key, did, "PLAN_FAILED_PRESERVED", {"intent": intent, "error": str(error)[:8192]})
                    raise
            elif record["phase"] in ("PLAN_INTENT", "PLAN_UNKNOWN"):
                # Only the pre-existing exact output of that plan intent may be
                # reconciled. Partial files are not overwritten or cleaned up.
                if not Path(record["plan_path"]).is_file():
                    raise Refusal("PLAN_SUBMISSION_UNKNOWN_NO_RETRY", did)
                plan = self.adapter.validate_plan(record["plan_path"], design)
                self.state.commit_plan(did, self.state.intent(record["last_intent"]), plan, digest(read_bytes(record["plan_path"])))
            elif record["plan_sha"] is not None:
                self.adapter.pinned_plan(design, record)

    def stop(self):
        generation = self.state.pause()
        requests = []
        for record in self.state.snapshot()["designs"]:
            if record["phase"] in ("ACTIVE", "SUBMIT_INTENT", "SUBMISSION_UNKNOWN"):
                if not Path(record["store_path"]).exists():
                    requests.append(dict(design=record["design"], status="STORE_NOT_YET_OBSERVED_STOP_PENDING"))
                    continue
                try:
                    request = self.adapter.stop(self.designs[record["design"]], record)
                    self.state.event("ENGINE_STOP_REQUESTED", request, record["design"])
                    requests.append(dict(design=record["design"], status="REQUESTED_NOT_SETTLED"))
                except Refusal as error:
                    self.state.event("ENGINE_STOP_REQUEST_FAILED", {"error": str(error)[:8192]}, record["design"])
                    requests.append(dict(design=record["design"], status="STOP_REQUEST_FAILED", reason=str(error)))
        return dict(generation=generation, dispatch_closed=True, requests=requests, parent_settlement_claimed=False,
                    provider_billing_still_active=True)

    def run(self, *, explicit_resume_generation=None):
        self.adapter.check_execution()
        with FileLock(self.state.directory / "runner.lock"):
            token = uuid.uuid4().hex
            started = time.monotonic()
            self.state.manager_enter(token)
            previous = {}
            try:
                self.state.reconcile()
                recover=getattr(self.adapter,'recover_completed',None)
                if recover is not None:recover()
                if explicit_resume_generation is not None:
                    self.state.resume(explicit_resume_generation)
                snapshot = self.state.snapshot()
                if snapshot["study"]["paused"]:
                    return snapshot
                self.prepare()
                if threading.current_thread() is threading.main_thread():
                    def shutdown(signum, frame):
                        # The handler sets only a flag; SQLite runs in the loop.
                        self.shutdown_event.set()
                    for sig in (signal.SIGINT, signal.SIGTERM):
                        previous[sig] = signal.signal(sig, shutdown)
                return self._loop(token, started)
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
                self.state.manager_exit(token, time.monotonic() - started)

    def _loop(self, token, started):
        spec = self.state.study.spec
        limit = self.workers
        effective=getattr(self.state,'effective_deadline',None)
        endpoint=effective()if effective is not None else datetime.fromisoformat(spec["deadline"]).astimezone(timezone.utc)
        available = (endpoint - datetime.now(timezone.utc)).total_seconds()
        deadline = min(started + spec["resources"]["per_run_wall_seconds"], time.monotonic() + available)
        active = {}
        attempted = set()
        stop_sent = set()
        stop_retry_after = {}
        shutdown_saved = False
        wall_saved = False
        with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="kaze-design") as executor:
            while True:
                dynamic=getattr(self.adapter,'dispatch_limit',None)
                if dynamic is not None:
                    selected=dynamic()
                    if type(selected)is not int or not 0<=selected<=self.workers:raise Refusal('VERSIONED_RUNTIME_TARGET_BOUND')
                    # Reducing the target changes only new dispatch capacity.
                    # Existing futures retain their ordinary safe boundaries.
                    limit=selected
                if self.shutdown_event.is_set() and not shutdown_saved:
                    self.state.shutdown(); shutdown_saved = True
                if time.monotonic() >= deadline - 1 and not wall_saved:
                    self.state.pause('YEAR_OPERATION_WINDOW_END'if spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1'else'RESOURCE_WALL'); wall_saved = True
                snapshot = self.state.snapshot()
                study = snapshot["study"]
                stopped={d['design']for d in snapshot['designs']if d.get('control',{}).get('paused')}
                if study["paused"] or stopped:
                    for future, (did, intent) in list(active.items()):
                        if not study["paused"]and did not in stopped:continue
                        record = self.state.design(did)
                        if did not in stop_sent and time.monotonic() >= stop_retry_after.get(did, 0) and Path(record["store_path"]).exists():
                            try:
                                request = self.adapter.stop(self.designs[did], record)
                                self.state.event("ENGINE_STOP_REQUESTED", request, did)
                                stop_sent.add(did)
                            except Refusal as error:
                                self.state.event("ENGINE_STOP_REQUEST_FAILED", {"error": str(error)[:8192]}, did)
                                # Store directory creation precedes its admitted
                                # body. Keep the durable Stop pending until that
                                # body can accept it; never rearm dispatch.
                                stop_retry_after[did] = time.monotonic() + 1
                if not study["paused"] and not study["shutdown"]:
                    for record in snapshot["designs"]:
                        did = record["design"]
                        if did in stopped or self.allowed_designs is not None and did not in self.allowed_designs:continue
                        if len(active) >= limit:
                            break
                        if did in attempted or record["phase"] not in ("PLANNED", "USER", "RESOURCE_TIME", "RESOURCE_OUTPUT"):
                            continue
                        try:
                            # Source/input validation before reserving; a later
                            # change is caught again before OS submission.
                            self.adapter.pinned_plan(self.designs[did], record)
                            preflight = getattr(self.adapter, 'validate_dispatch', None)
                            if preflight is not None:
                                preflight(self.designs[did], record)
                            intent = self.state.claim(did, study["generation"], token)
                        except Refusal as error:
                            if error.code == "YEAR_DESIGN_PAUSED_OR_STALE":continue
                            if error.code == "RESOURCE_SLOTS":
                                break
                            self.state.pause(error.code)
                            self.state.event("DISPATCH_REFUSED", {"code": error.code, "reason": str(error)}, did)
                            break
                        attempted.add(did)
                        remaining = max(0.1, deadline - time.monotonic())
                        future = executor.submit(self.adapter.execute, self.designs[did], record, intent, remaining)
                        active[future] = (did, intent)
                if not active:
                    break
                wait_started=time.monotonic()
                completed, _ = wait(active, timeout=0.05, return_when=FIRST_COMPLETED)
                observe_wait=getattr(self.adapter,'observe_wait',None)
                if observe_wait is not None:observe_wait(time.monotonic()-wait_started)
                for future in completed:
                    did, intent = active.pop(future)
                    try:
                        result = future.result()
                    except BaseException as error:
                        # No parent settlement can be reconstructed from a
                        # Python exception. Preserve the lease and exact intent.
                        result = dict(outcome="UNKNOWN", parent_settled=False, safe_no_submission=False,
                                      process={"elapsed_seconds": None}, summary=None, reason=str(error)[:8192])
                    receipt=self.state.save_receipt(intent, result)
                    # Only a versioned adapter may admit another durably
                    # settled resource suffix. USER/unknown/failures do not
                    # acquire automatic retry rights.
                    repeat=getattr(self.adapter,'after_settlement',None)
                    if repeat is not None and repeat(did,intent,receipt):
                        attempted.discard(did)
        result = self.state.snapshot()
        result["program_shutdown"] = shutdown_saved
        return result

