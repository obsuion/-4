"""Owned fixed-argv subprocesses with bounded separate pipes and finite envelopes."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from .data import digest, identity, parse
from .errors import Refusal


def process_start_token(pid):
    """Evidence only; a PID/token never grants recovery/termination authority."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            values = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(x) for x in values)):
                return None
            return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        value = Path(f"/proc/{pid}/stat").read_text("ascii")
        ticks = value[value.rfind(")") + 2:].split()[19]
        boot = Path("/proc/sys/kernel/random/boot_id").read_text("ascii").strip()
        return boot + ":" + ticks
    except (OSError, IndexError):
        return None


def process_rss(pid):
    if os.name != "nt":
        try:
            for row in Path(f"/proc/{pid}/status").read_text("ascii").splitlines():
                if row.startswith("VmRSS:"):
                    return int(row.split()[1]) * 1024
        except (OSError, ValueError):
            pass
        return None
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("peak", "working", "peak_page", "page",
                "peak_nonpage", "nonpage", "pagefile", "peak_pagefile")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        return None
    try:
        info = Counters(); info.cb = ctypes.sizeof(info)
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(info), info.cb):
            return info.working
        return None
    finally:
        kernel.CloseHandle(handle)


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    reason: str | None
    elapsed_seconds: float
    owner: dict | None
    peak_rss_bytes: int
    reaped: bool

    def evidence(self):
        return dict(returncode=self.returncode, reason=self.reason, elapsed_seconds=self.elapsed_seconds,
            owner=self.owner, peak_rss_bytes=self.peak_rss_bytes, reaped=self.reaped,
            stdout_bytes=len(self.stdout), stderr_bytes=len(self.stderr),
            stdout_sha256=digest(self.stdout), stderr_sha256=digest(self.stderr),
            stdout_text=self.stdout.decode("utf-8", errors="replace"),
            stderr_text=self.stderr.decode("utf-8", errors="replace"),
            cpu_seconds_upper_bound=self.elapsed_seconds, cpu_basis="ONE_CORE_PER_OWNED_PROCESS_ENVELOPE")


class ProcessRunner:
    def __init__(self, *, maximum_children=128):
        self.semaphore = threading.BoundedSemaphore(maximum_children)
        self.created = 0
        self.active = 0
        self.peak_active = 0
        self.total_child_seconds = 0.0
        self.lock = threading.Lock()

    def run(self, argv, *, cwd, timeout, stdout_cap, stderr_cap, rss_cap, on_spawn=None, launch_guard=None):
        if not Path(argv[0]).is_absolute() or not Path(cwd).is_absolute() or not 0 < timeout <= 365 * 86400:
            raise Refusal("ABSOLUTE_INTERPRETER_CWD_AND_TIMEOUT")
        if type(argv) is not list or any(type(v) is not str or "\x00" in v for v in argv):
            raise Refusal("ARRAY_ARGV_REQUIRED")
        with self.semaphore:
            result = self._run(argv, cwd=cwd, timeout=timeout, stdout_cap=stdout_cap,
                             stderr_cap=stderr_cap, rss_cap=rss_cap, on_spawn=on_spawn, launch_guard=launch_guard)
            log = os.environ.get("KAZE_PROCESS_LOG")
            if log and not ("unittest" in argv and "discover" in argv) and not any(str(x).endswith('affected_tests_r2.py') for x in argv):
                from .data import canonical
                from .locking import FileLock
                with FileLock(Path(log).with_suffix(".lock")):
                    with open(log, "ab") as stream:
                        stream.write(canonical(dict(argv_sha256=identity(argv), created=int(result.owner is not None),
                            elapsed_seconds=result.elapsed_seconds, reason=result.reason)) + b"\n")
                        stream.flush(); os.fsync(stream.fileno())
            return result

    def _run(self, argv, *, cwd, timeout, stdout_cap, stderr_cap, rss_cap, on_spawn, launch_guard):
        start = time.monotonic()
        # The R2 DATA gate supplies its own deadline. Nested DATA children must
        # finish cleanup before their live test parent reaches its allowance.
        # This can only shorten the caller's declared envelope.
        data_deadline=os.environ.get('KAZE_DATA_CHILD_DEADLINE')
        if data_deadline is not None and not any(str(x).endswith('affected_tests_r2.py') for x in argv):
            remaining=float(data_deadline)-start
            if not 0<remaining<86400:
                return ProcessResult(None,b'',b'DATA gate time exhausted','NOT_CREATED',0,None,0,True)
            timeout=min(timeout,remaining)
        environment = os.environ.copy()
        environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
            PYTHONUNBUFFERED="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
            NUMEXPR_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1", BLIS_NUM_THREADS="1")
        guard_failed = False
        try:
            with launch_guard() if launch_guard is not None else nullcontext(None) as recorder:
                process = subprocess.Popen(argv, cwd=cwd, env=environment, shell=False,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=os.name != "nt", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                with self.lock:
                    self.created += 1; self.active += 1; self.peak_active = max(self.peak_active, self.active)
                owner = dict(nonce=uuid.uuid4().hex, pid=process.pid, start_token=process_start_token(process.pid),
                    argv_sha256=identity(argv), interpreter=argv[0], cwd=cwd, direct_popen_handle=True,
                    authority="LIVE_PARENT_HANDLE_ONLY_NOT_PID_RECOVERY")
                if recorder is not None:
                    try:
                        recorder(owner)
                    except BaseException:
                        guard_failed = True
                        raise
        except BaseException as error:
            if "process" in locals():
                process.terminate()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
                elapsed = time.monotonic() - start
                with self.lock:
                    self.active -= 1; self.total_child_seconds += elapsed
                return ProcessResult(process.returncode, b"", str(error).encode("utf-8")[:stderr_cap],
                    "SPAWN_RECEIPT_FAILED", elapsed, locals().get("owner"), 0, process.returncode is not None)
            return ProcessResult(None, b"", str(error).encode("utf-8")[:stderr_cap], "NOT_CREATED",
                                 time.monotonic() - start, None, 0, True)
        overflow = threading.Event()
        pipe_error = threading.Event()
        outputs = [bytearray(), bytearray()]

        def drain(stream, target, cap):
            try:
                while True:
                    block = stream.read(8192)
                    if not block:
                        break
                    room = cap - len(target)
                    target.extend(block[:max(0, room)])
                    if len(block) > room:
                        overflow.set()
                        break
            except OSError:
                pipe_error.set()
            finally:
                stream.close()

        threads = [threading.Thread(target=drain, args=(stream, target, cap), daemon=True)
                   for stream, target, cap in ((process.stdout, outputs[0], stdout_cap), (process.stderr, outputs[1], stderr_cap))]
        for thread in threads:
            thread.start()
        reason = None
        peak = 0
        try:
            if on_spawn is not None:
                try:
                    on_spawn(owner)
                except BaseException:
                    reason = "SPAWN_RECEIPT_FAILED"
            while process.poll() is None and reason is None:
                rss = process_rss(process.pid)
                if rss is not None:
                    peak = max(peak, rss)
                if overflow.is_set():
                    reason = "OUTPUT_LIMIT"
                elif rss is not None and rss > rss_cap:
                    reason = "RSS_LIMIT"
                elif time.monotonic() - start >= timeout:
                    reason = "TIMEOUT"
                if reason is None:
                    try:
                        process.wait(timeout=min(0.05, max(0.001, timeout - (time.monotonic() - start))))
                    except subprocess.TimeoutExpired:
                        pass
            if reason is not None and process.poll() is None:
                # Only the exact direct child handle from this invocation is used.
                # Descendant uncertainty is retained in the scheduler lease.
                process.terminate()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        reason = "REAP_UNKNOWN"
            for thread in threads:
                thread.join(timeout=0.5)
            if any(thread.is_alive() for thread in threads):
                reason = reason or "PIPE_DESCENDANT_OWNERSHIP_UNKNOWN"
            if overflow.is_set():
                reason = "OUTPUT_LIMIT"
            if pipe_error.is_set():
                reason = reason or "PIPE_IO_ERROR"
            return ProcessResult(process.returncode, bytes(outputs[0]), bytes(outputs[1]), reason,
                                 time.monotonic() - start, owner, peak, process.returncode is not None)
        finally:
            elapsed = time.monotonic() - start
            with self.lock:
                self.active -= 1; self.total_child_seconds += elapsed

