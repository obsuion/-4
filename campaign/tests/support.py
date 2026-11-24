"""Pure-data fixture helpers: no subprocess/science/constructor compilation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile

from kaze_study.contract import load_study
from kaze_study.data import digest, read_bytes
from kaze_study.fixture import fixture_engine, make_fixture
from kaze_study.state import State


def fixture_module():
    spec = importlib.util.spec_from_file_location("kaze_test_protocol_data", fixture_engine() / "kit" / "serverctl.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def prepared_state(root, *, pool=None, alter=None):
    from kaze_study.data import canonical, read
    p = make_fixture(Path(root) / "spec")
    if alter is not None:
        value = read(p); alter(value); p.write_bytes(canonical(value))
    study = load_study(p, protocol_fixture=True)
    state = State.create(study, Path(root) / "study", pool or Path(root) / "pool.sqlite3", engine=fixture_engine(), interpreter=sys.executable)
    module = fixture_module()
    for design in state.study.catalogue.designs:
        record = state.design(design.design_id); intent = state.claim_plan(design.design_id)
        args = SimpleNamespace(input=Path(design.input_path), output=Path(record["plan_path"]),
            policy=Path(state.study.root) / "policy.json", backend="REFERENCE", mode="pilot", build=None,
            acceptance=None, seconds=4, rate="0.01", currency="USD", max_cost="10", setup="0")
        value = module.make_plan(args)
        state.commit_plan(design.design_id, intent, value, digest(read_bytes(record["plan_path"])))
    return state


def no_submission_result():
    from kaze_study.process import ProcessResult
    return dict(outcome="PROCESS_FAILURE", parent_settled=False, safe_no_submission=True,
        process=ProcessResult(None, b"", b"", "NOT_CREATED", .1, None, 0, True).evidence(),
        summary=None, reason="NOT_CREATED")


def fixture_settled_result(state, intent, kind="PHYSICAL", clock=2):
    """Typed, bound in-memory protocol evidence; never engine/science evidence."""
    from kaze_study.data import atomic_json, canonical, read
    from kaze_study.process import ProcessResult
    row = state.design(intent["design"]); plan = read(row["plan_path"])
    directory = Path(row["store_path"]); directory.mkdir(exist_ok=True)
    module = fixture_module()
    atomic_json(directory / "fixture-state.json", dict(clock=clock, jobs=1, job_id="1" * 32, active=False,
        observed=.1, terminal=module.terminal(kind, clock)))
    summary = module.summary(Path(row["plan_path"]), plan)
    owner = dict(nonce="synthetic-test-owner", pid=1, start_token="synthetic", direct_popen_handle=True)
    state.record_spawn(intent, owner)
    value = dict(store=row["store_path"], result=summary, billing_still_active=True)
    return dict(outcome=kind, parent_settled=True, safe_no_submission=False,
        process=ProcessResult(0, canonical(value), b"", None, .1, owner, 1, True).evidence(), summary=summary, reason=None)

