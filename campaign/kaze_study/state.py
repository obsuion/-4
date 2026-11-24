"""Transactional study journal, dispatch intents, receipts and shared reservations.

SQLite FULL synchronous commits atomically publish each state head AND its event
and pool lease. Input snapshots are installed before the immutable study marker;
failed initialization leaves explicit orphan files and never dispatches. No
multi-file atomicity is claimed. A receipt is written before the settlement
transaction, so a crash there has recoverable, exactly bound evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import shutil
import time
import uuid

from .contract import acceptance_references, load_study
from .data import canonical, digest, fields, identity, inside, no_links, parse, read, read_bytes, reference, slug, write_new
from .errors import Refusal
from .resources import reserve, volume_identity

DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS bindings(
 protocol TEXT NOT NULL, revision INTEGER NOT NULL, identity TEXT NOT NULL,
 PRIMARY KEY(protocol,revision));
CREATE TABLE IF NOT EXISTS studies(
 key TEXT PRIMARY KEY, study_id TEXT UNIQUE NOT NULL, directory TEXT UNIQUE NOT NULL,
 manifest TEXT NOT NULL, spec BLOB NOT NULL, paused INTEGER NOT NULL DEFAULT 0,
 generation INTEGER NOT NULL DEFAULT 0, shutdown INTEGER NOT NULL DEFAULT 0,
 parent_active INTEGER NOT NULL DEFAULT 0, parent_token TEXT, parent_ram INTEGER NOT NULL,
 wall_charged INTEGER NOT NULL DEFAULT 0, cpu_charged INTEGER NOT NULL DEFAULT 0,
 control_charged INTEGER NOT NULL DEFAULT 0, halt_reason TEXT,
 parent_unknown_wall_reserved INTEGER NOT NULL DEFAULT 0,
 parent_unknown_cpu_reserved INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS designs(
 study TEXT NOT NULL, design TEXT NOT NULL, root TEXT NOT NULL, input_sha TEXT NOT NULL,
 phase TEXT NOT NULL, plan_path TEXT NOT NULL, store_path TEXT UNIQUE NOT NULL,
 plan_sha TEXT, plan_data BLOB, last_intent TEXT, last_receipt BLOB,
 PRIMARY KEY(study,design), FOREIGN KEY(study) REFERENCES studies(key));
CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, study TEXT NOT NULL, design TEXT,
 kind TEXT NOT NULL, at TEXT NOT NULL, payload BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS intents(
 id TEXT PRIMARY KEY, study TEXT NOT NULL, design TEXT NOT NULL, generation INTEGER NOT NULL,
 action TEXT NOT NULL, data BLOB NOT NULL, receipt_sha TEXT, owner BLOB);
CREATE TABLE IF NOT EXISTS completions(
 intent TEXT PRIMARY KEY, result_sha TEXT NOT NULL, owner_sha TEXT, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leases(
 intent TEXT PRIMARY KEY, study TEXT NOT NULL, design TEXT NOT NULL, ram INTEGER NOT NULL,
 cpu INTEGER NOT NULL, wall_reserved INTEGER NOT NULL, cpu_reserved INTEGER NOT NULL,
 wall_observed INTEGER, cpu_observed INTEGER, active INTEGER NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS sole_active_design ON leases(study,design) WHERE active=1;
CREATE TABLE IF NOT EXISTS disk_reservations(
 study TEXT NOT NULL, design TEXT NOT NULL, bytes INTEGER NOT NULL, PRIMARY KEY(study,design));
CREATE TABLE IF NOT EXISTS publications(
 study TEXT NOT NULL, directory TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
 reserved_bytes INTEGER NOT NULL, measured_bytes INTEGER, phase TEXT NOT NULL,
 PRIMARY KEY(study,directory));
"""


def utc():
    return datetime.now(timezone.utc).isoformat()


class State:
    def effective_deadline(self):
        """Original immutable deadline, unless an exact private N90 ACK exists."""
        if self.study.spec.get('ninety_contract',{}).get('direct_main_version')=='DIRECT90D_USER_SCOPE_V1':
            from . import ninety_budget as budget
            value=budget._read(budget.PATH);long=value.get('long');ref=self.study.spec['ninety_contract']['direct_plan']
            if long is None or long.get('acceptance_version')!='DIRECT90D_USER_SCOPE_V1'or long['plan_sha256']!=ref['sha256']:
                raise Refusal('DIRECT90D_SAME_PRIVATE_LONG_DEADLINE')
            original=datetime.fromisoformat(self.study.spec['deadline']).astimezone(timezone.utc)
            if value.get('operator_pass')is not None:
                from .ninety_current import operator_deadline
                return operator_deadline(self,value)
            if long['deadline_utc']is None:
                window=budget.launch_entry_window_authority(value,full=False)
                if window is None:return original
                from .ninety_unused_grant_transition import preanchor_deadline
                return preanchor_deadline(self,value,window)
            # This exact DIRECT contract already owns its single48h clock.
            # The immutable study timestamp remains historical input; neither
            # it nor a later preparation window may truncate the actual clock.
            if long.get('first_dispatch_utc')is None or long.get('first_actual_launch')is None:
                raise Refusal('DIRECT90D_ACTUAL_MAIN_ANCHOR_REQUIRED_FOR_DEADLINE')
            end=budget._date(long['deadline_utc'])
            if end!=budget._date(long['first_dispatch_utc'])+timedelta(hours=48):
                raise Refusal('DIRECT90D_SINGLE_48H_DEADLINE_NO_RECONNECT_RESET')
            # The caller independently verifies the full financial/technical
            # history. A deadline read joins only its exact immutable launch
            # and current anchor, without re-entering that historical DAG.
            launch=budget._pinned(long['first_actual_launch'],2**20)
            anchors=[e for e in value['events']if e['action']=='FIRST_LONG_DISPATCH_ANCHOR']
            if (long.get('plan',{}).get('schema')!=budget.DIRECT_PLAN or identity(long['plan'])!=long['plan_sha256']or
                launch.get('schema')!='KAZE_DIRECT90D_ACTUAL_MAIN_LAUNCH_V1'or launch.get('scope')!=budget.SCOPE or
                launch.get('design_id')!=budget.DIRECT_DESIGNS[0]or launch.get('role')!='PRIMARY'or
                any(launch.get(k)is not True for k in('actual_numerical_launch','constructor_returned','assigned_before_execution'))or
                launch.get('binding')!=long['plan']['binding']or launch.get('launched_utc')!=long['first_dispatch_utc']or
                not budget._date(launch['launched_utc'])<=budget._now()or len(anchors)!=1 or
                anchors[0]['data']!=dict(start_utc=long['first_dispatch_utc'],deadline_utc=long['deadline_utc'],actual_launch=long['first_actual_launch'])):
                raise Refusal('DIRECT90D_EXACT_ACTUAL_MAIN_DEADLINE_ANCHOR')
            budget._verify_raw(launch['owner_receipt'],2**20)
            return end
        if self.study.spec.get('ninety_contract',{}).get('scope')=='CAMPAIGN-90D-K5':
            from .ninety_runtime_deadline import effective_deadline
            return effective_deadline(self)
        return datetime.fromisoformat(self.study.spec['deadline']).astimezone(timezone.utc)

    def __init__(self, directory):
        self.directory = no_links(directory).resolve()
        self.marker = fields(read(self.directory / "study.json"),
            ("schema", "key", "manifest_sha256", "pool", "mode", "engine", "interpreter"), "study marker")
        if self.marker["schema"] != "KAZE_STUDY_STATE_V1":
            raise Refusal("STATE_SCHEMA")
        self.pool = no_links(self.marker["pool"]).resolve()
        if not self.pool.is_file() or volume_identity(self.directory) != volume_identity(self.pool.parent):
            raise Refusal("SHARED_POOL_SAME_VOLUME_REQUIRED")
        self.key = self.marker["key"]
        from .project_receipts import ReceiptAuthority
        specpath=self.directory/'contract/study-input.json'
        saved_spec=parse(read_bytes(specpath))
        cat_schema=parse(reference(specpath.parent,saved_spec['catalogue'])[1]).get('schema')
        ninety=saved_spec.get('ninety_contract',{}).get('scope')=='CAMPAIGN-90D-K5'and cat_schema=='KAZE_NINETY_COMPILED_CATALOGUE_V1'
        authority=ReceiptAuthority(self.pool) if ninety or cat_schema in ('KAZE_PROJECT_EXECUTION_CATALOGUE_V1','KAZE_VERIFIED_NAMED_PROJECT_CATALOGUE_V1') else None
        self.study = load_study(self.directory / "contract" / "study-input.json",
            protocol_fixture=self.marker["mode"] == "PROTOCOL_FIXTURE_NO_SCIENCE",authority=authority)
        if self.study.manifest_sha256 != self.marker["manifest_sha256"]:
            raise Refusal("IMMUTABLE_STUDY_DRIFT")
        with self.connection() as c:
            row = c.execute("SELECT manifest,directory FROM studies WHERE key=?", (self.key,)).fetchone()
            if row is None or row[0] != self.study.manifest_sha256 or row[1] != str(self.directory):
                raise Refusal("STATE_DATABASE_BINDING")

    @classmethod
    def create(cls, study, directory, pool, *, engine, interpreter):
        if study.spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1':
            from .year_study import create_state
            return create_state(cls,study,directory,pool,engine,interpreter)
        if study.spec['schema']=='KAZE_NAMED_PROJECT_STUDY_V1':
            from .named_execution import create_state
            return create_state(cls,study,directory,pool,engine,interpreter)
        directory = no_links(directory).absolute()
        if directory.exists():
            raise Refusal("NEW_STUDY_DIRECTORY_REQUIRED", directory)
        pool = no_links(pool).absolute()
        if pool.is_relative_to(directory):
            raise Refusal("SHARED_POOL_OUTSIDE_STUDY_DIRECTORY")
        pool.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir(parents=True)
        if volume_identity(directory) != volume_identity(pool.parent):
            raise Refusal("SHARED_POOL_SAME_VOLUME_REQUIRED")
        root = directory / "contract"
        root.mkdir()
        snapshots = {"study-input.json": study.raw}
        spec = study.spec
        for ref in (spec["catalogue"], spec["policy"], spec["binding"]["source_manifest"],
                    spec["binding"]["build"], spec["binding"]["repair_evidence"],
                    spec["binding"].get("core_handoff"),
                    *acceptance_references(spec["binding"]["acceptance"])):
            if ref is not None:
                _, raw = reference(study.root, ref)
                if ref["path"] in snapshots and snapshots[ref["path"]] != raw:
                    raise Refusal("CONTRACT_SNAPSHOT_PATH_COLLISION")
                snapshots[ref["path"]] = raw
        repair = spec["binding"]["repair_evidence"]
        if spec["binding"]["freeze"] == "FROZEN_B64" and repair is not None:
            handoff = parse(reference(study.root, repair)[1])
            for ref in handoff["evidence"]:
                _, raw = reference(study.root, ref)
                if ref["path"] in snapshots and snapshots[ref["path"]] != raw:
                    raise Refusal("CONTRACT_SNAPSHOT_PATH_COLLISION")
                snapshots[ref["path"]] = raw
        cat = parse(study.catalogue.original_bytes)
        if cat.get('schema')=='KAZE_PROJECT_EXECUTION_CATALOGUE_V1':
            from .projects import execution_references
            if study.authority is None or study.authority.pool!=pool.resolve():raise Refusal('EXECUTION_OWNED_POOL_BINDING')
            for name,raw in execution_references(study.root,spec['catalogue'],authority=study.authority).items():
                if name in snapshots and snapshots[name]!=raw:raise Refusal('CONTRACT_SNAPSHOT_PATH_COLLISION')
                snapshots[name]=raw
        for record in cat.get("designs",[]):
            _, raw = reference(study.root, record["input"], 8 * 2**20)
            if record["input"]["path"] in snapshots and snapshots[record["input"]["path"]] != raw:
                raise Refusal("CONTRACT_SNAPSHOT_PATH_COLLISION")
            snapshots[record["input"]["path"]] = raw
            if "project" in record:
                for kind in ("spec", "compiler"):
                    ref = record["project"][kind]
                    _, raw = reference(study.root, ref, 2 * 2**20)
                    if ref["path"] in snapshots and snapshots[ref["path"]] != raw:
                        raise Refusal("CONTRACT_SNAPSHOT_PATH_COLLISION")
                    snapshots[ref["path"]] = raw
        for name, raw in snapshots.items():
            write_new(inside(root, name), raw)
        # Re-admit copied bytes, not the caller's mutable files.
        frozen = load_study(root / "study-input.json", protocol_fixture=spec["mode"] == "PROTOCOL_FIXTURE_NO_SCIENCE",authority=study.authority)
        key = uuid.uuid4().hex
        marker = dict(schema="KAZE_STUDY_STATE_V1", key=key, manifest_sha256=frozen.manifest_sha256,
                      pool=str(pool), mode=spec["mode"], engine=str(no_links(engine).resolve()),
                      interpreter=str(Path(interpreter).absolute()))
        no_links(Path(interpreter).resolve())
        global_config = {k: spec["resources"][k] for k in ("slots", "cpu_cores", "ram_bytes", "disk_bytes", "disk_free_floor_bytes", "control_rss_bytes")}
        global_config["volume"] = volume_identity(directory)
        c = sqlite3.connect(pool, timeout=5, isolation_level=None)
        try:
            c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=FULL")
            c.execute("PRAGMA foreign_keys=ON"); c.executescript(DDL)
            c.execute("BEGIN IMMEDIATE")
            prior = c.execute("SELECT value FROM meta WHERE key='pool_config'").fetchone()
            if prior is not None and bytes(prior[0]) != canonical(global_config):
                raise Refusal("GLOBAL_POOL_CAPACITY_MISMATCH")
            c.execute("INSERT OR IGNORE INTO meta VALUES('pool_config',?)", (canonical(global_config),))
            binding = spec["binding"]
            old_binding = c.execute("SELECT identity FROM bindings WHERE protocol=? AND revision=?", (binding["protocol"], binding["revision"])).fetchone()
            if old_binding is not None and old_binding[0] != identity(binding):
                raise Refusal("NEW_ENGINE_CONTRACT_REQUIRES_NEW_BINDING_REVISION")
            c.execute("INSERT OR IGNORE INTO bindings VALUES(?,?,?)", (binding["protocol"], binding["revision"], identity(binding)))
            disk_promised = c.execute("SELECT coalesce(sum(bytes),0) FROM disk_reservations").fetchone()[0] + spec["resources"]["wrapper_output_bytes"]
            if disk_promised > spec["resources"]["disk_bytes"] or disk_promised + spec["resources"]["disk_free_floor_bytes"] > shutil.disk_usage(directory).free:
                raise Refusal("RESOURCE_WRAPPER_DISK")
            c.execute("INSERT INTO studies(key,study_id,directory,manifest,spec,parent_ram) VALUES(?,?,?,?,?,?)",
                      (key, spec["study_id"], str(directory.resolve()), frozen.manifest_sha256, frozen.spec_bytes, spec["resources"]["parent_rss_bytes"]))
            c.execute("INSERT INTO disk_reservations VALUES(?,?,?)", (key, "__wrapper__", spec["resources"]["wrapper_output_bytes"]))
            for design in frozen.catalogue.designs:
                plan = directory.resolve() / "plans" / (design.design_id + ".json")
                c.execute("INSERT INTO designs(study,design,root,input_sha,phase,plan_path,store_path) VALUES(?,?,?,?,?,?,?)",
                    (key, design.design_id, design.root_identity, design.original_sha256, "READY", str(plan), str(plan.with_name(plan.stem + ".store"))))
            cls._event(c, key, None, "STUDY_REGISTERED", {"manifest": frozen.manifest_sha256, "marker": marker})
            # Marker may survive a failed DB commit: it is explicit orphan evidence.
            write_new(directory / "study.json", canonical(marker))
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()
        return cls(directory)

    @contextmanager
    def connection(self, writable=False):
        no_links(self.pool)
        if writable:
            c = sqlite3.connect(self.pool, timeout=5, isolation_level=None)
            c.execute("PRAGMA synchronous=FULL")
            c.execute("PRAGMA wal_autocheckpoint=64")
            c.execute("PRAGMA journal_size_limit=262144")
            reserved = c.execute("SELECT coalesce(sum(bytes),0) FROM disk_reservations WHERE design IN ('__wrapper__','__queue__')").fetchone()[0]
            page_size = c.execute("PRAGMA page_size").fetchone()[0]
            # One third for the DB, one third for its bounded WAL/transaction
            # duplication, and one third for frozen files/receipts per study.
            maximum_pages = max(64, reserved // 3 // page_size)
            if c.execute("PRAGMA page_count").fetchone()[0] > maximum_pages:
                c.close()
                raise Refusal("RESOURCE_WRAPPER_DATABASE")
            c.execute("PRAGMA max_page_count=" + str(maximum_pages))
        else:
            c = sqlite3.connect(self.pool.as_uri() + "?mode=ro", uri=True, timeout=5, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def transaction(self):
        with self.connection(True) as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

    @staticmethod
    def _event(c, key, design, kind, payload):
        raw = canonical(payload)
        spec_row = c.execute("SELECT spec FROM studies WHERE key=?", (key,)).fetchone()
        if spec_row is not None:
            budget = parse(bytes(spec_row[0]))["resources"]["wrapper_output_bytes"] // 6
            count, used = c.execute("SELECT count(*),coalesce(sum(length(payload)),0) FROM events WHERE study=?", (key,)).fetchone()
            critical = kind in ("STOP_REQUESTED", "PROGRAM_SHUTDOWN_REQUESTED", "PARENT_SETTLEMENT", "UNSETTLED_RECEIPT", "MANAGER_CLOSED")
            if len(raw) > 128 * 2**10 or count >= (8192 if critical else 8128) or used + len(raw) > budget - (0 if critical else 65536):
                raise Refusal("RESOURCE_WRAPPER_JOURNAL")
        c.execute("INSERT INTO events(study,design,kind,at,payload) VALUES(?,?,?,?,?)",
                  (key, design, kind, utc(), raw))

    def metadata_capacity(self, extra_bytes=0):
        """Measure only wrapper owners; engine store/export/backup bytes keep
        their separate full reservations and receive no materialization credit.
        """
        excluded = set()
        publications = []
        with self.connection() as c:
            for row in c.execute("SELECT store_path FROM designs WHERE study=?", (self.key,)):
                base = Path(row[0])
                excluded.update((base, Path(str(base) + ".exports"), Path(str(base) + ".initial.zip"),
                                 Path(str(base) + ".backup-2")))
            publications = [Path(row[0]) for row in c.execute("SELECT directory FROM publications WHERE study=?", (self.key,))]
            excluded.update(publications)
        total = 0; count = 0
        for directory, dirs, files in os.walk(self.directory, followlinks=False):
            parent = Path(directory)
            dirs[:] = [name for name in dirs if parent / name not in excluded]
            for name in files:
                p = no_links(parent / name)
                if p in excluded:
                    continue
                total += p.stat().st_size; count += 1
                if count > 100000:
                    raise Refusal("RESOURCE_WRAPPER_FILES")
        from .resources import measure_tree
        for directory in publications:
            if directory.exists():
                total += measure_tree(directory, maximum_files=100000)
        metadata_cap = self.study.spec["resources"]["wrapper_output_bytes"] // 3
        if self.study.spec.get('ninety_contract')is not None:
            from . import ninety_budget as budget
            from .ninety_operator_pass import state_metadata_cap
            current=state_metadata_cap(budget,budget._read(budget.PATH),self)
            if current is not None:metadata_cap=current
        if total + extra_bytes + 65536 > metadata_cap:
            raise Refusal("RESOURCE_WRAPPER_OUTPUT")
        return total

    def reserve_publication(self, directory, kind, maximum_bytes):
        directory = no_links(directory).absolute()
        parent = directory.parent
        while not parent.exists():
            parent = parent.parent
        if volume_identity(parent) != volume_identity(self.directory):
            raise Refusal("PUBLICATION_SHARED_VOLUME_REQUIRED")
        if directory.exists() or type(maximum_bytes) is not int or maximum_bytes <= 0:
            raise Refusal("NEW_BOUNDED_PUBLICATION_REQUIRED")
        measured = self.metadata_capacity()
        with self.transaction() as c:
            reserved = c.execute("SELECT coalesce(sum(reserved_bytes),0) FROM publications WHERE study=?", (self.key,)).fetchone()[0]
            # No materialized-file credit: the reserve remains conservative.
            if measured + reserved + maximum_bytes + 65536 > self.study.spec["resources"]["wrapper_output_bytes"] // 3:
                raise Refusal("RESOURCE_PUBLICATION_OUTPUT")
            c.execute("INSERT INTO publications VALUES(?,?,?,?,NULL,'RESERVED')", (self.key, str(directory), kind, maximum_bytes))
            self._event(c, self.key, None, "PUBLICATION_INTENT", {"directory": str(directory), "kind": kind, "reserved_bytes": maximum_bytes})

    def finish_publication(self, directory):
        from .resources import measure_tree
        directory = no_links(directory).absolute()
        measured = measure_tree(directory, maximum_files=100000)
        with self.transaction() as c:
            row = c.execute("SELECT reserved_bytes FROM publications WHERE study=? AND directory=?", (self.key, str(directory))).fetchone()
            if row is None or measured > row[0]:
                raise Refusal("PUBLICATION_RESERVATION_EXCEEDED")
            c.execute("UPDATE publications SET measured_bytes=?,phase='PUBLISHED' WHERE study=? AND directory=?", (measured, self.key, str(directory)))
            self._event(c, self.key, None, "PUBLICATION_SETTLED", {"directory": str(directory), "measured_bytes": measured, "reserved_bytes": row[0]})

    def event(self, kind, payload, design=None):
        with self.transaction() as c:
            self._event(c, self.key, design, kind, payload)

    def snapshot(self):
        with self.connection() as c:
            c.execute("BEGIN")
            row = dict(c.execute("SELECT * FROM studies WHERE key=?", (self.key,)).fetchone())
            del row["spec"]
            designs = []
            for d in c.execute("SELECT * FROM designs WHERE study=? ORDER BY design", (self.key,)):
                value = dict(d)
                for name in ("plan_data", "last_receipt"):
                    value[name] = None if value[name] is None else parse(bytes(value[name]))
                designs.append(value)
            if self.study.spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1':
                controls={r['design']:dict(r)for r in c.execute('SELECT * FROM year_design_controls WHERE study=?',(self.key,))}
                for d in designs:d['control']=controls[d['design']]
            leases = [dict(x) for x in c.execute("SELECT * FROM leases WHERE study=?", (self.key,))]
            events = c.execute("SELECT count(*) FROM events WHERE study=?", (self.key,)).fetchone()[0]
            disk = c.execute("SELECT coalesce(sum(bytes),0) FROM disk_reservations WHERE study=?", (self.key,)).fetchone()[0]
            return dict(schema="KAZE_STUDY_STATUS_V1", study=row, designs=designs, leases=leases,
                events=events, reserved_disk_bytes=disk, measured_disk_bytes=None,
                dispatch=False, provider_billing_still_active=True)

    def design(self, design_id):
        with self.connection() as c:
            row = c.execute("SELECT * FROM designs WHERE study=? AND design=?", (self.key, design_id)).fetchone()
            if row is None:
                raise Refusal("UNKNOWN_DESIGN", design_id)
            value = dict(row)
            value["plan_data"] = None if value["plan_data"] is None else parse(bytes(value["plan_data"]))
            return value

    def manager_enter(self, token):
        # Caller holds the kernel study runner lock. Kernel ownership, not PID
        # absence, permits replacement of a crashed wrapper's parent reservation.
        with self.transaction() as c:
            old = c.execute("SELECT * FROM studies WHERE key=?", (self.key,)).fetchone()
            total = c.execute("SELECT coalesce(sum(parent_ram),0) FROM studies WHERE parent_active=1 AND key!=?", (self.key,)).fetchone()[0]
            workers = c.execute("SELECT coalesce(sum(ram),0) FROM leases WHERE active=1").fetchone()[0]
            if total + workers + old["parent_ram"] + self.study.spec["resources"]["control_rss_bytes"] > self.study.spec["resources"]["ram_bytes"]:
                raise Refusal("RESOURCE_PARENT_RAM")
            c.execute("UPDATE studies SET parent_active=1,parent_token=?,shutdown=0 WHERE key=?", (token, self.key))
            if old["parent_active"]:
                # A missing parent close receipt is an unknown owned interval.
                # Reacquiring its kernel lock proves exclusive wrapper access,
                # not how much wall/CPU the lost parent actually consumed.
                r = self.study.spec["resources"]
                c.execute("UPDATE studies SET parent_unknown_wall_reserved=?,parent_unknown_cpu_reserved=? WHERE key=?",
                    (max(old["parent_unknown_wall_reserved"], r["max_owned_wall_seconds"] - old["wall_charged"]),
                     max(old["parent_unknown_cpu_reserved"], r["max_owned_cpu_seconds"] - old["cpu_charged"]), self.key))
            self._event(c, self.key, None, "MANAGER_OPEN", {"token": token, "replaced_parent_token": old["parent_token"],
                "lost_parent_interval": bool(old["parent_active"]), "unknown_parent_budget_held": bool(old["parent_active"])})

    def manager_exit(self, token, elapsed):
        with self.transaction() as c:
            row = c.execute("SELECT parent_token FROM studies WHERE key=?", (self.key,)).fetchone()
            if row[0] != token:
                raise Refusal("MANAGER_OWNER_MISMATCH")
            seconds = math.ceil(elapsed)
            c.execute("UPDATE studies SET parent_active=0,wall_charged=wall_charged+?,cpu_charged=cpu_charged+? WHERE key=?", (seconds, seconds, self.key))
            self._event(c, self.key, None, "MANAGER_CLOSED", {"token": token, "owned_wall_seconds": seconds,
                "cpu_upper_seconds": seconds, "science_stop": False})

    def pause(self, reason="OPERATOR_STOP"):
        with self.transaction() as c:
            c.execute("UPDATE studies SET paused=1,generation=generation+1,halt_reason=? WHERE key=?", (reason, self.key))
            generation = c.execute("SELECT generation FROM studies WHERE key=?", (self.key,)).fetchone()[0]
            self._event(c, self.key, None, "STOP_REQUESTED", {"generation": generation, "reason": reason, "settled": False})
            return generation

    def shutdown(self):
        with self.transaction() as c:
            c.execute("UPDATE studies SET shutdown=1,generation=generation+1 WHERE key=?", (self.key,))
            self._event(c, self.key, None, "PROGRAM_SHUTDOWN_REQUESTED", {"scientific_stop": False})

    def resume(self, expected_generation):
        with self.transaction() as c:
            row = c.execute("SELECT * FROM studies WHERE key=?", (self.key,)).fetchone()
            if type(expected_generation) is not int or row["generation"] != expected_generation:
                raise Refusal("STALE_GENERATION")
            if row["halt_reason"] is not None and row["halt_reason"].startswith("RESOURCE_"):
                # New immutable policy/study is needed if a hard budget is spent.
                raise Refusal("RESOURCE_REFUSAL_REQUIRES_REVIEW", row["halt_reason"])
            c.execute("UPDATE studies SET paused=0,shutdown=0,halt_reason=NULL,generation=generation+1 WHERE key=?", (self.key,))
            self._event(c, self.key, None, "EXPLICIT_RESUME", {"previous_generation": expected_generation, "generation": expected_generation + 1})
            return expected_generation + 1

    def claim_plan(self, did):
        with self.transaction() as c:
            row = c.execute("SELECT * FROM designs WHERE study=? AND design=?", (self.key, did)).fetchone()
            if row["phase"] != "READY":
                raise Refusal("PLAN_ALREADY_CLAIMED")
            iid = uuid.uuid4().hex
            data = dict(intent_id=iid, action="plan", study=self.key, design=did,
                        manifest=self.study.manifest_sha256, input_sha256=row["input_sha"],
                        plan=row["plan_path"], store=row["store_path"])
            c.execute("INSERT INTO intents(id,study,design,generation,action,data) VALUES(?,?,?,?,?,?)",
                      (iid, self.key, did, 0, "plan", canonical(data)))
            c.execute("UPDATE designs SET phase='PLAN_INTENT',last_intent=? WHERE study=? AND design=?", (iid, self.key, did))
            self._event(c, self.key, did, "PLAN_INTENT", data)
            return data

    def commit_plan(self, did, intent, plan, raw_sha):
        with self.transaction() as c:
            row = c.execute("SELECT * FROM designs WHERE study=? AND design=?", (self.key, did)).fetchone()
            if row["phase"] not in ("PLAN_INTENT", "PLAN_UNKNOWN") or row["last_intent"] != intent["intent_id"]:
                raise Refusal("PLAN_INTENT_MISMATCH")
            c.execute("UPDATE designs SET phase='PLANNED',plan_sha=?,plan_data=? WHERE study=? AND design=?",
                      (raw_sha, canonical(plan), self.key, did))
            self._event(c, self.key, did, "PLAN_COMMITTED", {"intent": intent["intent_id"], "sha256": raw_sha, "plan_identity": plan["plan_identity"]})

    def claim(self, did, generation, token, *, ram=None, free=None):
        if getattr(self,'read_only_history',False):raise Refusal('READ_ONLY_HISTORY_CANNOT_DISPATCH')
        self.metadata_capacity()
        if self.study.spec["mode"] != "PROTOCOL_FIXTURE_NO_SCIENCE":
            from .envelope import production_envelope
            from .resources import available_ram
            if self.study.spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1':
                from .year_execution import observe
                observed=observe(self.study)
            elif self.study.spec['schema']=='KAZE_NAMED_PROJECT_STUDY_V1':
                from .named_execution import observe
                observed=observe(self.study)
            else:observed = production_envelope(self.study.spec["resources"])
            ram = min(available_ram() if ram is None else ram, observed["memory_available"])
        # Verify private administrative metadata before taking the writer lock;
        # the helper opens independent read-only authority connections.
        effective_deadline = self.effective_deadline()
        from .ninety_owned_aux import effective_spec
        resource_spec=effective_spec(self)
        with self.transaction() as c:
            study = c.execute("SELECT * FROM studies WHERE key=?", (self.key,)).fetchone()
            if study["paused"] or study["shutdown"] or study["generation"] != generation:
                raise Refusal("DISPATCH_CLOSED_OR_STALE_GENERATION")
            if study["parent_token"] != token or not study["parent_active"]:
                raise Refusal("DISPATCH_MANAGER_OWNERSHIP")
            if datetime.now(timezone.utc) >= effective_deadline:
                raise Refusal("DEADLINE_REACHED")
            row = c.execute("SELECT * FROM designs WHERE study=? AND design=?", (self.key, did)).fetchone()
            if row["phase"] not in ("PLANNED", "USER", "RESOURCE_TIME", "RESOURCE_OUTPUT"):
                raise Refusal("DESIGN_NOT_DISPATCHABLE", row["phase"])
            action = "run" if row["phase"] == "PLANNED" else "resume"
            design_generation=None
            if self.study.spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1':
                control=c.execute('SELECT paused,generation FROM year_design_controls WHERE study=?AND design=?',(self.key,did)).fetchone()
                if control['paused']:raise Refusal('YEAR_DESIGN_PAUSED_OR_STALE')
                design_generation=control['generation']
            if action == "run" and Path(row["store_path"]).exists() and self.study.spec['schema']!='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1':
                raise Refusal("NEW_INITIAL_STORE_ALREADY_EXISTS_NO_OWNERSHIP_ADOPTION")
            iid = uuid.uuid4().hex
            data = dict(intent_id=iid, study=self.key, design=did, action=action, generation=generation,
                manifest=self.study.manifest_sha256, plan=row["plan_path"], plan_sha256=row["plan_sha"],
                store=row["store_path"], binding_sha256=identity(self.study.spec["binding"]),
                manager_token=token, at=utc(), reserved_wall_seconds=self.study.spec["resources"]["per_run_wall_seconds"])
            prior_receipt = None if row["last_receipt"] is None else parse(bytes(row["last_receipt"]))
            data["prior_cleanup"] = {} if prior_receipt is None else prior_receipt["result"]["process"].get("core_cleanup", {})
            data["input_sha256"] = row["input_sha"]
            data["root_identity"] = row["root"]
            if design_generation is not None:data["design_generation"]=design_generation
            if self.study.spec.get('ninety_contract'):
                data['observer_directory']=str(self.directory/'ninety-restore-watch'/iid)
            data["source_sha256"] = self.study.spec["binding"]["source_sha256"]
            reserve(c, self.key, did, iid, resource_spec, self.directory, ram=ram, free=free)
            c.execute("INSERT INTO intents(id,study,design,generation,action,data) VALUES(?,?,?,?,?,?)",
                      (iid, self.key, did, generation, action, canonical(data)))
            c.execute("UPDATE designs SET phase='SUBMIT_INTENT',last_intent=? WHERE study=? AND design=?", (iid, self.key, did))
            self._event(c, self.key, did, "DISPATCH_INTENT", data)
            return data

    def record_spawn(self, intent, owner):
        with self.transaction() as c:
            row = c.execute("SELECT owner FROM intents WHERE id=? AND study=?", (intent["intent_id"], self.key)).fetchone()
            if row is None or row[0] is not None:
                raise Refusal("SPAWN_RECEIPT_MISMATCH")
            c.execute("UPDATE intents SET owner=? WHERE id=?", (canonical(owner), intent["intent_id"]))
            c.execute("UPDATE designs SET phase='ACTIVE' WHERE study=? AND design=? AND last_intent=?",
                      (self.key, intent["design"], intent["intent_id"]))
            self._event(c, self.key, intent["design"], "OWNED_PROCESS_CREATED", {"intent_id": intent["intent_id"], "owner": owner})

    @contextmanager
    def spawn_guard(self, intent):
        if getattr(self,'read_only_history',False):raise Refusal('READ_ONLY_HISTORY_CANNOT_DISPATCH')
        """Linearize OS submission with Stop's generation transaction."""
        with self.transaction() as c:
            study = c.execute("SELECT * FROM studies WHERE key=?", (self.key,)).fetchone()
            d = c.execute("SELECT phase,last_intent FROM designs WHERE study=? AND design=?", (self.key, intent["design"])).fetchone()
            if (study["paused"] or study["shutdown"] or study["generation"] != intent["generation"] or
                    d["phase"] not in (("SUBMIT_INTENT","ACTIVE")if self.study.spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1'else("SUBMIT_INTENT",)) or d["last_intent"] != intent["intent_id"]):
                raise Refusal("DISPATCH_CLOSED_OR_STALE_GENERATION")
            year=self.study.spec['schema']=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1'
            if year:
                control=c.execute('SELECT paused,generation FROM year_design_controls WHERE study=?AND design=?',(self.key,intent['design'])).fetchone()
                if control['paused']or control['generation']!=intent.get('design_generation'):raise Refusal('YEAR_DESIGN_PAUSED_OR_STALE')
                expected=next(x for x in self.study.spec['prepared']if x['design_id']==intent['design'])
                if self.study.spec.get('ninety_contract'):
                    from .ninety_study import verify_store_owner
                    verify_store_owner(self,c,intent,expected)
                    if intent.get('observer_directory')!=str(self.directory/'ninety-restore-watch'/intent['intent_id']):raise Refusal('NINETY_PRIVATE_OBSERVER_DIRECTORY_BINDING')
                elif read(Path(intent['store'])/'year-state-owner.json')!=dict(study=self.key,design=intent['design'],manifest=self.study.manifest_sha256,preparation=expected['request']['preparation_identity']):raise Refusal('YEAR_EXACT_PREPARED_STORE_OWNER')
            if intent["action"] == "run" and Path(intent["store"]).exists() and not year:
                if self.study.spec['schema']!='KAZE_NAMED_PROJECT_STUDY_V1':
                    raise Refusal("NEW_INITIAL_STORE_ALREADY_EXISTS_NO_OWNERSHIP_ADOPTION")
                pin=read(Path(intent['store'])/'campaign-intent.json')
                if pin!=dict(intent_id=intent['intent_id'],study=self.key,manifest=self.study.manifest_sha256):
                    raise Refusal('NAMED_STORE_NOT_CREATED_BY_THIS_EXACT_INTENT')

            def record(owner):
                if year:
                    prior=c.execute('SELECT owner FROM intents WHERE id=?',(intent['intent_id'],)).fetchone()[0]
                    if prior is not None and bytes(prior)!=canonical(owner):raise Refusal('YEAR_IMMUTABLE_LIFETIME_OWNER_CALLBACK')
                c.execute("UPDATE intents SET owner=? WHERE id=? AND owner IS NULL", (canonical(owner), intent["intent_id"]))
                c.execute("UPDATE designs SET phase='ACTIVE' WHERE study=? AND design=?", (self.key, intent["design"]))
                self._event(c, self.key, intent["design"], "OWNED_PROCESS_CREATED", {"intent_id": intent["intent_id"], "owner": owner})
            yield record

    def save_receipt(self, intent, result):
        try:
            self.record_completion(intent, result)
        except Refusal as error:
            # Preserve malformed live evidence; never free its reservation.
            result = dict(result, parent_settled=False, safe_no_submission=False, outcome="UNKNOWN",
                          reason="INVALID_SETTLEMENT_PROOF:" + str(error)[:4096])
            self.record_completion(intent, result)
        receipt = dict(schema="KAZE_DISPATCH_RECEIPT_V1", intent=intent, result=result, at=utc())
        raw = canonical(receipt)
        self.metadata_capacity(len(raw))
        path = self.directory / "receipts" / (intent["intent_id"] + ".json")
        write_new(path, raw)
        self.settle(receipt, digest(raw))
        return receipt

    def record_completion(self, intent, result):
        """Live-parent publication, before receipt creation; never called by reopen."""
        from .settlement import validate_completion
        with self.transaction() as c:
            row = c.execute("SELECT * FROM intents WHERE id=? AND study=?", (intent["intent_id"], self.key)).fetchone()
            if row is None or bytes(row["data"]) != canonical(intent):
                raise Refusal("EXACT_INTENT_COMPLETION_BINDING")
            owner = None if row["owner"] is None else parse(bytes(row["owner"]))
            record = dict(c.execute("SELECT * FROM designs WHERE study=? AND design=?", (self.key, intent["design"])).fetchone())
            validate_completion(self.study, record, intent, result, owner)
            pin = identity(result)
            prior = c.execute("SELECT result_sha FROM completions WHERE intent=?", (intent["intent_id"],)).fetchone()
            if prior is not None and prior[0] != pin:
                raise Refusal("IMMUTABLE_COMPLETION_PIN")
            c.execute("INSERT OR IGNORE INTO completions VALUES(?,?,?,?)", (intent["intent_id"], pin, None if owner is None else identity(owner), utc()))
            self._event(c, self.key, intent["design"], "COMPLETION_PINNED_BEFORE_RECEIPT", {"intent": intent["intent_id"], "result_sha256": pin})

    def settle(self, receipt, raw_sha):
        fields(receipt, ("schema", "intent", "result", "at"), "dispatch receipt")
        if receipt["schema"] != "KAZE_DISPATCH_RECEIPT_V1":
            raise Refusal("RECEIPT_SCHEMA")
        intent, result = receipt["intent"], receipt["result"]
        fields(result, ("outcome", "parent_settled", "safe_no_submission", "process", "summary", "reason"), "process result")
        if type(result["parent_settled"]) is not bool or type(result["safe_no_submission"]) is not bool:
            raise Refusal("EXACT_RECEIPT_SETTLEMENT_FLAGS")
        with self.transaction() as c:
            row = c.execute("SELECT * FROM intents WHERE id=? AND study=?", (intent["intent_id"], self.key)).fetchone()
            if row is None or bytes(row["data"]) != canonical(intent):
                raise Refusal("EXACT_INTENT_RECEIPT_BINDING")
            table = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='completions'").fetchone()
            pin = None if table is None else c.execute("SELECT * FROM completions WHERE intent=?", (intent["intent_id"],)).fetchone()
            owner = None if row["owner"] is None else parse(bytes(row["owner"]))
            if pin is None or pin["result_sha"] != identity(result) or pin["owner_sha"] != (None if owner is None else identity(owner)):
                raise Refusal("INDEPENDENT_COMPLETION_JOURNAL_PIN_REQUIRED")
            from .settlement import validate_completion
            record = dict(c.execute("SELECT * FROM designs WHERE study=? AND design=?", (self.key, intent["design"])).fetchone())
            settled = validate_completion(self.study, record, intent, result, owner)
            if row["receipt_sha"] is not None:
                if row["receipt_sha"] != raw_sha:
                    raise Refusal("RECEIPT_SUBSTITUTION")
                return
            phase = result["outcome"] if settled else "SUBMISSION_UNKNOWN"
            known = {"TARGET", "PHYSICAL", "MODEL", "UNSUPPORTED", "ENGINE_REFUSAL", "RESOURCE_TIME", "RESOURCE_OUTPUT", "USER", "PROCESS_FAILURE", "UNKNOWN", "TIMEOUT", "OUTPUT_LIMIT"}
            if result["outcome"] not in known:
                raise Refusal("TYPED_OUTCOME")
            process = result["process"]
            observed = process.get("elapsed_seconds")
            reserve_row = c.execute("SELECT * FROM leases WHERE intent=?", (intent["intent_id"],)).fetchone()
            # One supervisor plus one nested serial worker, even if the worker
            # was idle. This is a conservative owned-process cost envelope.
            charged = reserve_row["wall_reserved"] if type(observed) not in (int, float) or not math.isfinite(observed) or observed < 0 else min(reserve_row["wall_reserved"], math.ceil(2 * observed))
            if settled:
                c.execute("UPDATE leases SET active=0,wall_observed=?,cpu_observed=? WHERE intent=?", (charged, charged, intent["intent_id"]))
                c.execute("UPDATE studies SET wall_charged=wall_charged+?,cpu_charged=cpu_charged+? WHERE key=?", (charged, charged, self.key))
            c.execute("UPDATE intents SET receipt_sha=? WHERE id=?", (raw_sha, intent["intent_id"]))
            c.execute("UPDATE designs SET phase=?,last_receipt=? WHERE study=? AND design=? AND last_intent=?",
                      (phase, canonical(receipt), self.key, intent["design"], intent["intent_id"]))
            self._event(c, self.key, intent["design"], "PARENT_SETTLEMENT" if settled else "UNSETTLED_RECEIPT",
                        {"intent_id": intent["intent_id"], "receipt_sha256": raw_sha, "outcome": result["outcome"], "charged_seconds": charged})

    def reconcile(self):
        recovered, uncertain = [], []
        snapshot = self.snapshot()
        for d in snapshot["designs"]:
            if d["phase"] not in ("SUBMIT_INTENT", "ACTIVE", "SUBMISSION_UNKNOWN"):
                continue
            path = self.directory / "receipts" / (d["last_intent"] + ".json")
            if path.exists():
                try:
                    raw = read_bytes(path)
                    self.settle(parse(raw), digest(raw))
                    if self.design(d["design"])["phase"] != "SUBMISSION_UNKNOWN":
                        recovered.append(d["design"])
                        continue
                except (Refusal, OSError, KeyError, TypeError) as error:
                    self.event("INVALID_RECOVERY_PROOF", {"intent_id": d["last_intent"], "reason": str(error)[:4096]}, d["design"])
            # Exact intent and plan remain pinned; no PID inference and no retry.
            with self.transaction() as c:
                c.execute("UPDATE designs SET phase='SUBMISSION_UNKNOWN' WHERE study=? AND design=? AND last_intent=?",
                          (self.key, d["design"], d["last_intent"]))
                self._event(c, self.key, d["design"], "SUBMISSION_UNKNOWN", {"intent_id": d["last_intent"],
                    "plan_sha256": d["plan_sha"], "store": d["store_path"], "automatic_retry": False})
            uncertain.append(d["design"])
        return dict(recovered=recovered, submission_unknown=uncertain, dispatch=False)

    def charge_control(self, seconds, kind):
        with self.transaction() as c:
            r = self.study.spec["resources"]
            row = c.execute("SELECT control_charged FROM studies WHERE key=?", (self.key,)).fetchone()
            if row[0] + seconds > r["control_wall_reserve_seconds"]:
                raise Refusal("RESOURCE_CONTROL_WALL")
            c.execute("UPDATE studies SET control_charged=control_charged+?,wall_charged=wall_charged+?,cpu_charged=cpu_charged+? WHERE key=?", (seconds, seconds, seconds, self.key))
            self._event(c, self.key, None, "CONTROL_RESERVED", {"kind": kind, "seconds": seconds})

    def rearm_ninety_abi6_cold_no_launch(self, proof):
        """Exact reconciled d66 DATA ACK; existing costs and lease stay unchanged."""
        if getattr(self,'read_only_history',False):raise Refusal('READ_ONLY_HISTORY_CANNOT_RECOVER_EXECUTION')
        from .ninety_cold_recovery import record_state_ack
        return record_state_ack(self,proof)

    def recover_direct_completed_return(self,request):
        """Explicit CURRENT metadata ACK of a genuinely ended original return."""
        if getattr(self,'read_only_history',False):raise Refusal('READ_ONLY_HISTORY_CANNOT_RECOVER_EXECUTION')
        from .ninety_completed_return import recover
        return recover(self,request)

    def rearm_ninety_abi6_no_launch(self, proof):
        """Exact35 administrative ACK; old UNKNOWN, fees and receipt stay raw."""
        if getattr(self,'read_only_history',False):raise Refusal('READ_ONLY_HISTORY_CANNOT_RECOVER_EXECUTION')
        from .ninety_no_launch import record_state_ack
        return record_state_ack(self,proof)

    def rearm_ninety_abi6_no_submission(self, proof):
        """One exact administrative transition; no submission or expense refund.

        The original failure/intent/completion/lease stay immutable. A recovery
        row and events retain the previous halt before advancing its typed head.
        A later dispatch makes this operation ineligible even on a repeat call.
        """
        if getattr(self,'read_only_history',False):raise Refusal('READ_ONLY_HISTORY_CANNOT_RECOVER_EXECUTION')
        from .ninety_path_recovery import validate_owner_proof
        validate_owner_proof(self, proof)
        failed='095f6b575c614a42b4299a8d3a11e89c'
        receipt_sha='4be8cf557b66a18ca81018b22d0265890dfb1dcf5c7f3da4c2b347e5066749be'
        grant_id='7e57189ae6c844ca92163b7523da1f88'
        if (proof.get('schema')!='KAZE_NINETY_ABI6_PATH_NO_SUBMISSION_RECOVERY_V1' or
            proof.get('failed_intent')!=failed or proof.get('study')!=self.key or proof.get('design')!='D1_BALANCED' or
            proof.get('receipt',{}).get('sha256')!=receipt_sha or proof.get('execution_authority')is not False):
            raise Refusal('DIRECT90D_ABI6_EXACT_RECOVERY_AUTHORITY')
        receipt_raw=read_bytes(proof['receipt']['path'],2**20);receipt=parse(receipt_raw)
        grant_raw=read_bytes(proof['original_grant']['path'],2**20);grant=parse(grant_raw)
        if digest(receipt_raw)!=receipt_sha or digest(grant_raw)!=proof['original_grant']['sha256'] or grant.get('id')!=grant_id:
            raise Refusal('DIRECT90D_ABI6_ORIGINAL_RAW_RECOVERY_PINS')
        path=self.directory/'ninety-path-recoveries'/failed/'ACK.json'
        self.metadata_capacity(32768)
        with self.transaction()as c:
            c.execute('CREATE TABLE IF NOT EXISTS ninety_abi6_path_recoveries('
                'study TEXT NOT NULL,design TEXT NOT NULL,failed_intent TEXT PRIMARY KEY,owner TEXT NOT NULL,'
                'path TEXT UNIQUE NOT NULL,sha256 TEXT NOT NULL,body BLOB NOT NULL)')
            head=c.execute('SELECT *FROM studies WHERE key=?',(self.key,)).fetchone()
            design=c.execute('SELECT *FROM designs WHERE study=?AND design=?',(self.key,proof['design'])).fetchone()
            intent=c.execute('SELECT *FROM intents WHERE id=?AND study=?',(failed,self.key)).fetchone()
            completion=c.execute('SELECT *FROM completions WHERE intent=?',(failed,)).fetchone()
            lease=c.execute('SELECT *FROM leases WHERE intent=?',(failed,)).fetchone()
            control=c.execute('SELECT *FROM year_design_controls WHERE study=?AND design=?',(self.key,proof['design'])).fetchone()
            halt=c.execute('SELECT reason,detail FROM chain_halts WHERE study=?AND design=?',(self.key,proof['design'])).fetchone()
            private=c.execute('SELECT *FROM chain_grants WHERE id=?',(grant_id,)).fetchone()
            prior=c.execute('SELECT *FROM ninety_abi6_path_recoveries WHERE failed_intent=?',(failed,)).fetchone()
            if (any(row is None for row in(head,design,intent,completion,lease,control,halt,private)) or
                head['parent_active'] or head['paused'] or head['shutdown'] or
                c.execute('SELECT 1 FROM leases WHERE active=1').fetchone() or
                c.execute('SELECT 1 FROM studies WHERE parent_active=1').fetchone() or
                c.execute('SELECT 1 FROM chain_entries WHERE study=?',(self.key,)).fetchone() or
                [row[0]for row in c.execute("SELECT id FROM intents WHERE study=?AND design=?AND action IN('run','resume')",(self.key,proof['design']))]!=[failed]):
                raise Refusal('DIRECT90D_ABI6_RECOVERY_QUIESCENT_FIRST_UNSUBMITTED_INTENT')
            if (intent['owner']is not None or intent['action']!='run' or bytes(intent['data'])!=canonical(proof['intent']) or
                receipt['intent']!=proof['intent'] or intent['receipt_sha']!=receipt_sha or
                completion['owner_sha']is not None or completion['result_sha']!=identity(receipt['result']) or
                proof['result_sha256']!=completion['result_sha'] or lease['active'] or
                lease['wall_observed']is None or lease['cpu_observed']is None or design['last_intent']!=failed or
                bytes(design['last_receipt'])!=canonical(receipt) or design['plan_sha']!=proof['plan']['sha256'] or
                design['root']!=proof['root_identity'] or design['input_sha']!=proof['input_sha256'] or
                design['store_path']!=proof['store'] or head['manifest']!=proof['manifest'] or control['paused'] or
                head['generation']!=proof['intent']['generation']):
                raise Refusal('DIRECT90D_ABI6_RECOVERY_EXACT_COMPLETION_AND_STATE_BINDING')
            if (private['owner']!=grant['owner'] or private['path']!=proof['original_grant']['path'] or
                private['sha256']!=digest(grant_raw) or bytes(private['body'])!=grant_raw or
                self.study.authority is None or private['owner']!=self.study.authority.owner or
                any(private[k]!=0 for k in('entries','wall','cpu','output')) or grant['study']!=self.key):
                raise Refusal('DIRECT90D_ABI6_RECOVERY_UNUSED_EXACT_ORIGINAL_GRANT')
            for other in c.execute('SELECT id,body FROM chain_grants WHERE revoked=0 AND id!=?',(grant_id,)):
                if parse(bytes(other['body'])).get('study')==self.key:
                    raise Refusal('DIRECT90D_ABI6_RECOVERY_AMBIGUOUS_ACTIVE_GRANT')
            jobs=no_links(Path(proof['store'])/'jobs')
            if jobs.exists()and(not jobs.is_dir()or any(jobs.iterdir())):
                raise Refusal('DIRECT90D_ABI6_RECOVERY_NATIVE_JOB_APPEARED')
            if prior is not None:
                ack=parse(bytes(prior['body']))
                if (ack.get('proof')!=proof or prior['path']!=str(path) or prior['sha256']!=digest(bytes(prior['body'])) or
                    read_bytes(path,2**20)!=bytes(prior['body']) or design['phase']!='PLANNED' or
                    control['generation']!=proof['expected_design_generation']+1 or private['revoked']!=1 or
                    halt['reason']!='RECOVERED_NO_SUBMISSION_REQUIRES_NEW_RUN'):
                    raise Refusal('DIRECT90D_ABI6_RECOVERY_ALREADY_ADVANCED_NO_REPLAY')
                return dict(path=str(path),sha256=prior['sha256'],bytes=len(bytes(prior['body'])))
            if (design['phase']!='PROCESS_FAILURE' or control['generation']!=proof['expected_design_generation'] or private['revoked']!=0 or
                halt['reason']!='UNKNOWN_OR_PROCESS_FAILURE' or halt['detail']!='Refusal: YEAR_WINDOWS_WORKER_TEMP_PATH_ENVELOPE: 253'):
                raise Refusal('DIRECT90D_ABI6_RECOVERY_EXACT_ORIGINAL_FAILURE_HEAD')
            ack=dict(schema='KAZE_NINETY_ABI6_PATH_NO_SUBMISSION_RECOVERY_ACK_V1',scope='CAMPAIGN-90D-K5',study=self.key,
                design=proof['design'],failed_intent=failed,owner=grant['owner'],proof=proof,original_halt=dict(halt),
                from_phase='PROCESS_FAILURE',to_phase='PLANNED',old_design_generation=control['generation'],
                new_design_generation=control['generation']+1,revoked_grant_id=grant_id,recorded_utc=utc(),
                preserved_lease=dict(lease),preserved_wall_charged=head['wall_charged'],preserved_cpu_charged=head['cpu_charged'],
                execution_authority=False,science_entries=0,expenses_refunded=False)
            if path.exists():
                orphan_raw=read_bytes(path,2**20);orphan=parse(orphan_raw)
                if (dict(orphan,recorded_utc=ack['recorded_utc'])!=ack or
                    not datetime.fromisoformat(orphan['recorded_utc'])<=datetime.now(timezone.utc)):
                    raise Refusal('DIRECT90D_ABI6_ORPHAN_ACK_NOT_EXACT_ORIGINAL_STATE')
                ack=orphan;raw=orphan_raw
            else:
                raw=canonical(ack);write_new(path,raw)
            pin=digest(raw)
            c.execute('INSERT INTO ninety_abi6_path_recoveries VALUES(?,?,?,?,?,?,?)',
                (self.key,proof['design'],failed,grant['owner'],str(path),pin,raw))
            c.execute("UPDATE designs SET phase='PLANNED'WHERE study=?AND design=?",(self.key,proof['design']))
            c.execute("UPDATE year_design_controls SET generation=generation+1,reason='ABI6_EXACT_NO_SUBMISSION_RECOVERY'WHERE study=?AND design=?",(self.key,proof['design']))
            c.execute('UPDATE chain_grants SET revoked=1 WHERE id=?',(grant_id,))
            c.execute("UPDATE chain_halts SET reason='RECOVERED_NO_SUBMISSION_REQUIRES_NEW_RUN',detail=?WHERE study=?AND design=?",
                (str(path)+':'+pin,self.key,proof['design']))
            self._event(c,self.key,proof['design'],'ABI6_EXACT_NO_SUBMISSION_RECOVERED',dict(ack=dict(path=str(path),sha256=pin),
                failed_intent=failed,original_halt=ack['original_halt'],original_receipt_sha256=receipt_sha,
                original_phase='PROCESS_FAILURE',expenses_refunded=False,execution_authority=False))
            self._event(c,self.key,proof['design'],'ABI6_UNUSED_ORIGINAL_GRANT_REVOKED',dict(grant=grant_id,ack_sha256=pin,expenses_refunded=False))
            return dict(path=str(path),sha256=pin,bytes=len(raw))

    def intent(self, iid):
        with self.connection() as c:
            row = c.execute("SELECT data FROM intents WHERE id=? AND study=?", (iid, self.key)).fetchone()
            if row is None:
                raise Refusal("INTENT_NOT_FOUND")
            return parse(bytes(row[0]))

