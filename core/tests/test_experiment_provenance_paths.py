"""Real Git pathname regressions; all fixture commits stay under pytest tmp_path."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ops_sim.v5.experiment_provenance import capture_provenance, validate_provenance


ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = (
    "ascii.py", "проверка.py", "source with spaces.py", "проверка с пробелами.py",
)


def fixture_command(root, *args):
    result = subprocess.run(
        args, cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"},
        capture_output=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize("quote_path", [True, False])
@pytest.mark.parametrize("state", ["clean", "modified", "untracked"])
def test_real_git_source_path_classification_in_fresh_process(tmp_path, quote_path, state):
    repository = tmp_path / "fixture repository"
    repository.mkdir()
    # Keep the actual package initializer and its legacy imports intact.
    shutil.copytree(ROOT / "ops_sim", repository / "ops_sim",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    examples = repository / "examples"
    examples.mkdir()
    for name in SOURCE_NAMES:
        (examples / name).write_text("VALUE = 1\n", encoding="utf-8")
    fixture_command(repository, "git", "init", "--quiet")
    # Local settings and commits affect only this disposable real repository.
    fixture_command(repository, "git", "config", "core.quotePath", str(quote_path).lower())
    fixture_command(repository, "git", "add", "--", "ops_sim", "examples")
    fixture_command(repository, "git", "-c", "user.name=Task 02 R1 fixture",
                    "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
                    "commit", "--quiet", "-m", "Disposable provenance fixture")
    assert fixture_command(repository, "git", "status", "--porcelain=v1") == ""
    expected = {"examples/" + name: "clean" for name in SOURCE_NAMES}
    if state == "modified":
        for name in SOURCE_NAMES:
            (examples / name).write_text("VALUE = 2\n", encoding="utf-8")
            expected["examples/" + name] = "modified"
    elif state == "untracked":
        for name in ("новый.py", "новый с пробелами.py"):
            (examples / name).write_text("VALUE = 3\n", encoding="utf-8")
            expected["examples/" + name] = "untracked"
    output = fixture_command(repository, sys.executable, "-B", "-c", "\n".join([
        "import json",
        "from pathlib import Path",
        "import ops_sim.v5.experiment_provenance as module",
        "assert Path(module.__file__).resolve().parents[2] == Path.cwd().resolve()",
        "print(json.dumps(module.capture_provenance(Path.cwd()), ensure_ascii=True))",
    ]))
    provenance = json.loads(output)
    assert provenance["git_dirty"] is (state != "clean")
    for path, status in expected.items():
        assert provenance["source_status"][path] == status
        assert provenance["source_sha256"][path] == hashlib.sha256((repository / path).read_bytes()).hexdigest()


@pytest.mark.parametrize("status", ["modified", "untracked"])
def test_genuinely_inconsistent_clean_provenance_is_still_rejected(status):
    provenance = deepcopy(capture_provenance(ROOT))
    provenance["git_dirty"] = False
    provenance["source_status"] = {path: "clean" for path in provenance["source_sha256"]}
    provenance["source_status"]["ops_sim/v5/experiment_provenance.py"] = status
    with pytest.raises(ValueError, match="dirty/new sources cannot be represented as clean HEAD"):
        validate_provenance(provenance)


@pytest.mark.parametrize("names", [
    (), ("examples/ascii.py",),
    ("examples/проверка.py", "examples/ source with spaces .py"),
    ("examples/line\nfeed.py", "examples/carriage\rreturn.py", "examples/crlf\r\nname.py"),
    ("examples/tab\tname.py", 'examples/"quoted".py', "examples/back\\slash.py"),
])
def test_nul_parser_preserves_path_characters_including_non_windows_names(names):
    from ops_sim.v5.experiment_provenance import _git_pathnames
    raw = b"".join(name.encode("utf-8") + b"\0" for name in names)
    assert _git_pathnames(raw) == set(names)


@pytest.mark.parametrize("raw", [b"unterminated.py", b"\0", b"a.py\0\0", b"\xff.py\0"])
def test_nul_parser_rejects_malformed_or_non_utf8_pathnames(raw):
    from ops_sim.v5.experiment_provenance import _git_pathnames
    with pytest.raises(ValueError):
        _git_pathnames(raw)
