"""Replay CORE's actual DATA inspector against an independently pinned reader.

The result's embedded source manifest is evidence about its historical producer,
never permission to choose executable reader code. No native module is loaded.
"""
from pathlib import Path
import sys

from .data import file_digest, identity, inside, parse, read, read_bytes
from .errors import Refusal
from .process import ProcessRunner
from .protocol import B65

REFERENCE_ID = "d90243c0725645237a60ab771b6c093de3af38fb08d815a10404adc7d72f8bb1"


def inspect_data(path, *, runner=None, timeout=30, rss_cap=256 * 2**20):
    from .report import zip_metadata
    zip_metadata(path)
    if type(timeout) not in (int, float) or not 0 < timeout <= 30 or type(rss_cap) is not int or not 0 < rss_cap <= 256 * 2**20:
        raise Refusal("BOUNDED_DATA_INSPECTOR_ENVELOPE")
    base = Path(__file__).resolve().parents[1] / "fixtures" / "b66-packet"
    freeze = read(base / "SOURCE824-FREEZE.json")
    manifest = freeze["manifest"]
    if freeze["source_identity"] != REFERENCE_ID or identity(manifest) != REFERENCE_ID:
        raise Refusal("INDEPENDENT_DATA_READER_PIN")
    engine = base / "engine-reference"
    def pinned():
        actual = {p.relative_to(engine).as_posix() for p in engine.rglob("*") if p.is_file()}
        if actual != set(manifest):
            raise Refusal("DATA_READER_SOURCE_MEMBERSHIP")
        for name, item in manifest.items():
            raw = read_bytes(inside(engine, name), 16 * 2**20)
            if len(raw) != item["bytes"] or file_digest(inside(engine, name)) != item["sha256"]:
                raise Refusal("DATA_READER_SOURCE_DRIFT", name)
    pinned()
    before = file_digest(path)
    # Public read-only verb; neither local prepare nor run is reachable here.
    result = (runner or ProcessRunner(maximum_children=1)).run(
        [str(Path(sys.executable).absolute()), "-B", str(engine / "kit" / "serverctl.py"),
         "--engine", str(engine), "inspect-result", "--input", str(Path(path).absolute())],
        cwd=str(engine), timeout=timeout, stdout_cap=4 * 2**20, stderr_cap=2**20, rss_cap=rss_cap)
    pinned()
    if before != file_digest(path):
        raise Refusal("RESULT_CHANGED_DURING_DATA_INSPECTION")
    if result.returncode != 0 or result.reason is not None or not result.reaped:
        raise Refusal("AUTHORITATIVE_DATA_INSPECTOR_REFUSED", result.evidence())
    view = parse(result.stdout, 4 * 2**20)
    if view.get("format") != B65.result:
        raise Refusal("DATA_INSPECTOR_UNKNOWN_RESULT_FAMILY")
    return view, before, result.evidence()
