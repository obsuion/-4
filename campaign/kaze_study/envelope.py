"""Observe a real cgroup v2 ceiling; a wrapper PID is not an aggregate limit."""
import os
from pathlib import Path
import sys

from .errors import Refusal


def production_envelope(resources):
    if not sys.platform.startswith("linux"):
        raise Refusal("LINUX_PRODUCTION_ENVELOPE_REQUIRED")
    base = Path("/sys/fs/cgroup")
    membership = Path("/proc/self/cgroup").read_text("ascii").strip().splitlines()
    if len(membership) != 1 or not membership[0].startswith("0::"):
        raise Refusal("CGROUP_V2_MEMBERSHIP_REQUIRED")
    group = membership[0][3:]
    choices = [base, base / group.lstrip("/")]
    scope = next((p for p in choices if p.resolve().is_relative_to(base.resolve()) and (p / "cgroup.procs").is_file() and
                  str(os.getpid()) in (p / "cgroup.procs").read_text("ascii").split()), None)
    if scope is None:
        raise Refusal("CGROUP_SELF_MEMBERSHIP_UNPROVEN")
    def ceiling(name):
        value = (scope / name).read_text("ascii").strip()
        if not value.isdecimal() or int(value) <= 0:
            raise Refusal("FINITE_CGROUP_LIMIT_REQUIRED", name)
        return int(value)
    memory = ceiling("memory.max"); pids = ceiling("pids.max")
    quota = (scope / "cpu.max").read_text("ascii").split()
    if len(quota) != 2 or any(not x.isdecimal() or int(x) <= 0 for x in quota):
        raise Refusal("FINITE_CGROUP_CPU_REQUIRED")
    if memory > resources["ram_bytes"] or int(quota[0]) > resources["cpu_cores"] * int(quota[1]) or pids > 1024:
        raise Refusal("CGROUP_EXCEEDS_DECLARED_ENVELOPE")
    return dict(format="KAZE_OBSERVED_CGROUP_V2_V1", membership=group, path=str(scope),
        memory_max=memory, pids_max=pids, cpu_max=quota, observer_pid=os.getpid(),
        memory_available=max(0, memory - ceiling("memory.current")),
        scope="INHERITED_BY_SERVERCTL_AND_CORE_SESSIONS", grants_pid_recovery=False)
