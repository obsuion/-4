"""Bounded strict JSON, immutable references and durable publications."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import uuid
from contextvars import ContextVar

from .errors import Refusal

MAX_JSON = 16 * 2**20
READ_OBSERVER = ContextVar('BOUNDED_IMMUTABLE_DATA_READ_OBSERVER', default=None)
DIGEST_OBSERVER = ContextVar('BOUNDED_IMMUTABLE_DATA_DIGEST_OBSERVER', default=None)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(value):
    return digest(canonical(value))


def parse(raw, limit=MAX_JSON):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise Refusal("JSON_BYTES")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refusal("DUPLICATE_JSON_KEY", key)
            result[key] = value
        return result

    def constant(value):
        raise Refusal("NONFINITE_JSON", value)

    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise Refusal("INVALID_JSON", error) from error
    todo = [(value, 0)]
    count = 0
    while todo:
        item, depth = todo.pop()
        count += 1
        if count > 2**19 or depth > 64:
            raise Refusal("JSON_GRAPH_BOUNDS")
        if type(item) is dict:
            if any(len(k.encode("utf-8")) > 4096 for k in item):
                raise Refusal("JSON_KEY_BYTES")
            todo.extend((v, depth + 1) for v in item.values())
        elif type(item) is list:
            todo.extend((v, depth + 1) for v in item)
        elif type(item) is float and not math.isfinite(item):
            raise Refusal("NONFINITE_JSON_NUMBER")
    return value


def fields(value, names, name="object"):
    if type(value) is not dict or set(value) != set(names):
        raise Refusal("EXACT_FIELDS", name)
    return value


def integer(value, name="integer", low=0, high=2**63 - 1):
    if type(value) is not int or not low <= value <= high:
        raise Refusal("EXACT_INTEGER", name)
    return value


def text(value, name="text", maximum=4096):
    if type(value) is not str or not 0 < len(value.encode("utf-8")) <= maximum or "\x00" in value:
        raise Refusal("BOUNDED_TEXT", name)
    return value


def sha(value):
    if type(value) is not str or not re.fullmatch("[0-9a-f]{64}", value):
        raise Refusal("SHA256")
    return value


def slug(value):
    if type(value) is not str or not re.fullmatch("[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise Refusal("IDENTIFIER", value)
    return value


def relative(value):
    text(value, "relative path", 960)
    p = PurePosixPath(value)
    if any(ord(c) < 32 or ord(c) == 127 or c in '<>|"*?' for c in value):
        raise Refusal("UNSAFE_PATH_CHARACTERS", value)
    if ("\\" in value or ":" in value or value.startswith("/") or
            any(x in ("", ".", "..") for x in value.split("/")) or p.as_posix() != value):
        raise Refusal("PATH_TRAVERSAL", value)
    # Portable Windows names, including alternate streams/device paths.
    for part in p.parts:
        if part.endswith((".", " ")) or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part):
            raise Refusal("UNSAFE_PATH", value)
    return value


def no_links(path):
    p = Path(path).absolute()
    for node in (p, *p.parents):
        if not node.exists() and not node.is_symlink():
            continue
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise Refusal("PATH_LINK_OR_REPARSE", node)
    return p


def inside(root, name):
    root = no_links(root).resolve()
    p = no_links(root / relative(name))
    if not p.resolve().is_relative_to(root):
        raise Refusal("PATH_ESCAPE", name)
    return p


def read_bytes(path, limit=MAX_JSON):
    p = no_links(path)
    before = p.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= limit:
        raise Refusal("BOUNDED_REGULAR_FILE", p)
    with p.open("rb") as stream:
        raw = stream.read(limit + 1)
    after = p.stat()
    if (len(raw) != before.st_size or
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
        raise Refusal("FILE_CHANGED_DURING_READ", p)
    observer=READ_OBSERVER.get()
    if observer is not None:observer(p,raw)
    return raw


def read(path, limit=MAX_JSON):
    return parse(read_bytes(path, limit), limit)


def file_digest(path, limit=512 * 2**20):
    p = no_links(path)
    before = p.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= limit:
        raise Refusal("BOUNDED_REGULAR_FILE", p)
    h = hashlib.sha256()
    with p.open("rb") as stream:
        total = 0
        for block in iter(lambda: stream.read(2**20), b""):
            total += len(block)
            if total > limit:
                raise Refusal("FILE_BYTES")
            h.update(block)
    after = p.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise Refusal("FILE_CHANGED_DURING_READ")
    result=h.hexdigest()
    observer=DIGEST_OBSERVER.get()
    if observer is not None:observer(p,before.st_size,result)
    return result


def reference(root, value, limit=MAX_JSON):
    fields(value, ("path", "sha256", "bytes"), "file reference")
    sha(value["sha256"])
    integer(value["bytes"], "reference bytes", 1, limit)
    path = inside(root, value["path"])
    raw = read_bytes(path, limit)
    if len(raw) != value["bytes"] or digest(raw) != value["sha256"]:
        raise Refusal("REFERENCE_DRIFT", value["path"])
    return path, raw


def sync_directory(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_new(path, raw):
    p = no_links(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(p.parent)


def atomic_json(path, value):
    p = no_links(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    pending = p.with_name(p.name + "." + uuid.uuid4().hex + ".pending")
    write_new(pending, canonical(value) + b"\n")
    # A Windows reader can briefly deny DELETE sharing. Keep the SAME flushed
    # publication and the caller's original lock/clock; never retry the bill.
    # Other failures and persistent sharing denial remain fatal, preserving
    # the old file and this exact pending evidence.
    delays = (0.025, 0.050, 0.100)
    for attempt in range(len(delays) + 1):
        try:
            os.replace(pending, p)
            break
        except PermissionError as error:
            if (os.name != "nt" or getattr(error, "winerror", None) not in (5, 32)
                    or attempt == len(delays)):
                raise
            time.sleep(delays[attempt])
    sync_directory(p.parent)

