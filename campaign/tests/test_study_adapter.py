from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

from kaze_study.data import canonical, digest, identity, parse, read, read_bytes
from kaze_study.engine_adapter import EngineAdapter
from kaze_study.errors import Refusal
from kaze_study.fixture import fixture_engine
from kaze_study.process import ProcessResult
from support import prepared_state, fixture_module


class MemoryRunner:
    def __init__(self, result):
        self.result = result; self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs)); return self.result


def process(stdout=b"", stderr=b"", reason=None, returncode=0):
    return ProcessResult(returncode, stdout, stderr, reason, .1, {"synthetic": True}, 1, True)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kaze-adapter-"); self.addCleanup(self.temp.cleanup)
        self.state = prepared_state(Path(self.temp.name) / "путь с пробелами")
        self.design = self.state.study.catalogue.designs[0]
        self.record = self.state.design(self.design.design_id)

    def adapter(self, result):
        runner = MemoryRunner(result)
        return EngineAdapter(self.state.study, fixture_engine(), sys.executable, runner=runner, protocol_fixture=True)

    def test_entire_multiline_json_not_last_line(self):
        doc = {"format": "KAZEOSAT_SERVER_DOCTOR_V1", "source_manifest_sha256": self.state.study.spec["binding"]["source_sha256"]}
        import json
        adapter = self.adapter(process(json.dumps(doc, indent=2).encode()))
        self.assertEqual(adapter.doctor()["engine"], doc)
        for raw in (b"noise\n" + canonical(doc), canonical(doc) + b"\n{}"):
            with self.assertRaisesRegex(Refusal, "ENGINE_COMMAND_FAILED"):
                self.adapter(process(raw)).doctor()

    def test_fixed_argv_absolute_interpreter_cyrillic_and_no_store_cli(self):
        adapter = self.adapter(process())
        argv = adapter.argv("status", ["--plan", self.record["plan_path"]])
        self.assertTrue(Path(argv[0]).is_absolute()); self.assertIn("--plan", argv); self.assertNotIn("--store", argv)
        self.assertIn("путь с пробелами", argv[-1])
        with self.assertRaises(Refusal):
            adapter.argv("chain-run", [])

    def test_source_and_backend_plan_substitution(self):
        adapter = self.adapter(process())
        manifest = parse(adapter.study.source_bytes); manifest["kit/serverctl.py"]["sha256"] = "0" * 64
        adapter.study = replace(adapter.study, source_bytes=canonical(manifest))
        with self.assertRaisesRegex(Refusal, "SOURCE_DRIFT"):
            adapter.check_source()
        adapter = self.adapter(process())
        p = Path(self.record["plan_path"]); v = read(p); v["backend"] = "PREPARED_NATIVE"
        v["plan_identity"] = identity({k: x for k, x in v.items() if k != "plan_identity"}); p.write_bytes(canonical(v))
        with self.assertRaisesRegex(Refusal, "BACKEND_RUNTIME_BINDING"):
            adapter.validate_plan(p, self.design)

    def test_physical_refusal_timeout_unknown_are_distinct(self):
        module = fixture_module(); plan = read(self.record["plan_path"])
        directory = Path(self.record["store_path"]); directory.mkdir()
        from kaze_study.data import atomic_json
        atomic_json(directory / "fixture-state.json", dict(clock=2, jobs=1, job_id="1" * 32, active=False,
            observed=.1, terminal=module.terminal("PHYSICAL", 2)))
        summary = module.summary(Path(self.record["plan_path"]), plan)
        value = dict(store=self.record["store_path"], result=summary, billing_still_active=True)
        intent = dict(action="run")
        physical = self.adapter(process(canonical(value))).execute(self.design, self.record, intent)
        self.assertEqual(physical["outcome"], "PHYSICAL"); self.assertTrue(physical["parent_settled"])
        cases = [(process(reason="TIMEOUT", returncode=-1), "TIMEOUT"),
                 (process(b"not json"), "UNKNOWN"),
                 (process(stderr=canonical(dict(status="REFUSED_OR_FAILED", reason="declared refusal")), returncode=2), "ENGINE_REFUSAL")]
        for response, expected in cases:
            result = self.adapter(response).execute(self.design, self.record, intent)
            self.assertEqual(result["outcome"], expected); self.assertFalse(result["parent_settled"])

    def test_runtime_and_input_substitution(self):
        adapter = self.adapter(process())
        spec = adapter.study.spec; spec["binding"]["runtime"]["python"] = "wrong"
        adapter.study = replace(adapter.study, spec_bytes=canonical(spec)); adapter.spec = spec
        with self.assertRaisesRegex(Refusal, "RUNTIME_MISMATCH"):
            adapter.check_execution()
        p = Path(self.record["plan_path"]).parent / self.record["plan_data"]["input_file"]
        p.write_bytes(p.read_bytes() + b" ")
        with self.assertRaisesRegex(Refusal, "INPUT_DRIFT"):
            self.adapter(process()).pinned_plan(self.design, self.record)

