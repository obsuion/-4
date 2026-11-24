"""Finite aggregate resource admission; all mutations share the state transaction.

Disk promises remain reserved after a run: retained stores/backups still exist.
Measured bytes never earn a second engine-pool credit. Unknown submissions keep
their full active reservations until an authoritative settlement is supplied.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
import shutil

from .data import fields, integer
from .errors import Refusal

RESOURCE_FIELDS = ("slots", "cpu_cores", "parent_rss_bytes", "worker_rss_bytes", "native_rss_bytes",
    "supervisor_rss_bytes", "control_rss_bytes", "ram_bytes", "disk_bytes", "disk_free_floor_bytes", "per_design_disk_bytes",
    "wrapper_output_bytes", "max_owned_wall_seconds", "max_owned_cpu_seconds",
    "per_run_wall_seconds", "control_timeout_seconds", "control_wall_reserve_seconds",
    "stdout_bytes", "stderr_bytes")


def decimal(value, name="decimal", zero=False):
    if type(value) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]{0,29})(?:\.[0-9]{1,18})?", value):
        raise Refusal("EXACT_DECIMAL_STRING", name)
    try:
        d = Decimal(value)
    except InvalidOperation as error:
        raise Refusal("DECIMAL", name) from error
    if not d.is_finite() or d < 0 or not zero and d == 0:
        raise Refusal("POSITIVE_DECIMAL", name)
    return d


def admit_cost(v):
    if v is None:
        return None
    fields(v, ("rate", "unit", "currency", "cap", "setup", "engine_scenario"), "cost policy")
    if v["unit"] != "OWNED_PROCESS_HOUR" or type(v["currency"]) is not str or not re.fullmatch("[A-Z]{3}", v["currency"]):
        raise Refusal("COST_UNIT_CURRENCY")
    decimal(v["rate"], "rate", zero=True); decimal(v["setup"], "setup", zero=True)
    if v["cap"] is not None:
        decimal(v["cap"], "cap")
    if v["cap"] is not None and Decimal(v["setup"]) >= Decimal(v["cap"]):
        raise Refusal("SETUP_EXHAUSTS_COST_CAP")
    scenario = fields(v["engine_scenario"], ("rate", "unit", "currency", "cap", "setup"), "engine cost scenario")
    if scenario["unit"] != "MACHINE_HOUR" or scenario["currency"] != v["currency"]:
        raise Refusal("ENGINE_COST_UNIT_OR_CURRENCY")
    decimal(scenario["rate"], "engine machine-hour rate")
    decimal(scenario["setup"], "engine setup", zero=True)
    if scenario["cap"] is not None:
        decimal(scenario["cap"], "engine scenario cap")
        if Decimal(scenario["setup"]) >= Decimal(scenario["cap"]):
            raise Refusal("ENGINE_SETUP_EXHAUSTS_SCENARIO")
    return v


def admit_resources(v, concurrency):
    fields(v, RESOURCE_FIELDS, "resource policy")
    for name in RESOURCE_FIELDS:
        integer(v[name], name, 0 if name in ("native_rss_bytes", "disk_free_floor_bytes") else 1)
    if v["slots"] != concurrency or v["cpu_cores"] < 2 * concurrency + 2:
        raise Refusal("CPU_PARENT_AND_WORKER_CAPACITY")
    if v["ram_bytes"] < v["parent_rss_bytes"] + v["control_rss_bytes"] + concurrency * (v["supervisor_rss_bytes"] + v["worker_rss_bytes"] + v["native_rss_bytes"]):
        raise Refusal("RAM_CAPACITY")
    if v["disk_bytes"] < v["per_design_disk_bytes"] + v["wrapper_output_bytes"]:
        raise Refusal("DISK_CAPACITY")
    if v["wrapper_output_bytes"] < 8 * 2**20:
        raise Refusal("WRAPPER_METADATA_RESERVE")
    if v["max_owned_wall_seconds"] < v["per_run_wall_seconds"] + v["control_wall_reserve_seconds"]:
        raise Refusal("FINITE_WALL_RESERVATION")
    if v["max_owned_cpu_seconds"] < v["per_run_wall_seconds"]:
        raise Refusal("FINITE_CPU_RESERVATION")
    if v["stdout_bytes"] > 16 * 2**20 or v["stderr_bytes"] > 2**20 or v["control_timeout_seconds"] > 30:
        raise Refusal("PROCESS_IO_OR_CONTROL_BOUNDS")
    return v


def volume_identity(path):
    p = Path(path).resolve()
    return str(p.anchor).casefold() + ":" + str(p.stat().st_dev)


def available_ram():
    if os.name == "nt":
        import ctypes

        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                        ("page_total", ctypes.c_ulonglong), ("page_available", ctypes.c_ulonglong),
                        ("virtual_total", ctypes.c_ulonglong), ("virtual_available", ctypes.c_ulonglong),
                        ("extended", ctypes.c_ulonglong)]
        info = Memory(); info.length = ctypes.sizeof(info)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
            raise Refusal("RAM_MEASUREMENT_UNAVAILABLE")
        return info.available
    try:
        rows = Path("/proc/meminfo").read_text("ascii").splitlines()
        return int(next(row.split()[1] for row in rows if row.startswith("MemAvailable:"))) * 1024
    except (OSError, ValueError, StopIteration) as error:
        raise Refusal("RAM_MEASUREMENT_UNAVAILABLE") from error


def measure_tree(path, *, maximum_files=1000000):
    """Bounded physical measurement for reports, not reservation credit."""
    from .data import no_links
    total = count = 0
    for directory, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            p = no_links(Path(directory) / name)
            count += 1
            if count > maximum_files:
                raise Refusal("OUTPUT_FILE_POPULATION")
            if p.is_file():
                total += p.stat().st_size
    return total


def reserve(connection, study_key, design_id, intent_id, spec, study_directory, *, ram=None, free=None):
    """Called only inside State.transaction(), which serializes the global pool."""
    r = spec["resources"]
    active = connection.execute("SELECT count(*),coalesce(sum(ram),0),coalesce(sum(cpu),0) FROM leases WHERE active=1").fetchone()
    if active[0] >= r["slots"] or active[2] + 2 > r["cpu_cores"] - 2:
        raise Refusal("RESOURCE_SLOTS")
    parent = connection.execute("SELECT coalesce(sum(parent_ram),0) FROM studies WHERE parent_active=1").fetchone()[0]
    need_ram = r["supervisor_rss_bytes"] + r["worker_rss_bytes"] + r["native_rss_bytes"]
    if active[1] + parent + need_ram + r["control_rss_bytes"] > r["ram_bytes"]:
        raise Refusal("RESOURCE_RAM")
    measured_ram = available_ram() if ram is None else ram
    if measured_ram < active[1] + need_ram:
        raise Refusal("RESOURCE_RAM_MEASURED")
    total_disk = connection.execute("SELECT coalesce(sum(bytes),0) FROM disk_reservations").fetchone()[0]
    existing = connection.execute("SELECT bytes FROM disk_reservations WHERE study=? AND design=?", (study_key, design_id)).fetchone()
    disk = 0 if existing else r["per_design_disk_bytes"]
    if total_disk + disk > r["disk_bytes"]:
        raise Refusal("RESOURCE_DISK")
    actual_free = shutil.disk_usage(study_directory).free if free is None else free
    # Conservative: do not subtract materialized output from the wrapper promises.
    if total_disk + disk + r["disk_free_floor_bytes"] > actual_free:
        raise Refusal("RESOURCE_DISK_MEASURED")
    accounting = connection.execute("SELECT wall_charged,cpu_charged,control_charged,parent_unknown_wall_reserved,parent_unknown_cpu_reserved FROM studies WHERE key=?", (study_key,)).fetchone()
    unsettled = connection.execute("SELECT coalesce(sum(wall_reserved),0),coalesce(sum(cpu_reserved),0) FROM leases WHERE study=? AND active=1", (study_key,)).fetchone()
    wall = r["per_run_wall_seconds"]
    control = r["control_wall_reserve_seconds"]
    # Include the one active wrapper's remaining envelope, not just workers.
    projected_wall = accounting[0] + accounting[3] + unsettled[0] + wall * 3 + control
    projected_cpu = accounting[1] + accounting[4] + unsettled[1] + wall * 3 + control
    if projected_wall > r["max_owned_wall_seconds"] or accounting[2] >= control:
        raise Refusal("RESOURCE_WALL")
    if projected_cpu > r["max_owned_cpu_seconds"]:
        raise Refusal("RESOURCE_CPU")
    cost = spec["cost"]
    if cost is not None and cost["cap"] is not None and Decimal(projected_wall) / 3600 * Decimal(cost["rate"]) + Decimal(cost["setup"]) > Decimal(cost["cap"]):
        raise Refusal("RESOURCE_COST")
    if not existing:
        connection.execute("INSERT INTO disk_reservations VALUES(?,?,?)", (study_key, design_id, disk))
    connection.execute("INSERT INTO leases VALUES(?,?,?,?,?,?,?,?,?,1)",
        (intent_id, study_key, design_id, need_ram, 2, wall * 2, wall * 2, None, None))


def policy_candidate(*, output_bytes, simulated_progress_seconds, horizon_seconds,
                     maximum_segment_wall_seconds, overhead_bytes, backup_copies=1, headroom="1.5"):
    """A finite measured candidate only; the engine must admit the actual policy."""
    for value in (output_bytes, simulated_progress_seconds, horizon_seconds, maximum_segment_wall_seconds, overhead_bytes):
        integer(value, "pilot measurement", 1)
    integer(backup_copies, "backups", 1, 2)
    factor = decimal(headroom, "headroom")
    if factor < 1:
        raise Refusal("HEADROOM_BELOW_ONE")
    segments = (horizon_seconds + simulated_progress_seconds - 1) // simulated_progress_seconds
    per_output = int((Decimal(output_bytes) * factor).to_integral_value(rounding="ROUND_CEILING"))
    store = segments * per_output + overhead_bytes
    return {"schema": "KAZE_MEASURED_POLICY_CANDIDATE_V1", "maximum_primary_segments": segments,
            "per_segment_output_candidate_bytes": per_output, "store_reserved_bytes": store,
            "including_backups_reserved_bytes": store * (1 + backup_copies),
            "wall_candidate_seconds": segments * maximum_segment_wall_seconds,
            "engine_admission_required": True, "measurement_is_not_a_hard_bound": True}

