"""Kernel-held lock; persistent inode, never a PID-based stale-lock deletion."""
from __future__ import annotations

from pathlib import Path
import os

from .data import no_links
from .errors import Refusal


class FileLock:
    def __init__(self, path):
        self.path = no_links(path)
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.stream.write(b"0"); self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close(); self.stream = None
            raise Refusal("OWNERSHIP_LOCK_HELD", self.path) from error
        return self

    def __exit__(self, *args):
        try:
            if os.name == "nt":
                import msvcrt
                self.stream.seek(0); msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()

