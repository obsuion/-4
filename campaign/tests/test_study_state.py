from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

from kaze_study.data import canonical, write_new
from kaze_study.errors import Refusal
from kaze_study.state import State
from kaze_study.locking import FileLock
from support import prepared_state, no_submission_result, fixture_settled_result


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kaze-state-")
        self.addCleanup(self.temp.cleanup)
        self.state = prepared_state(Path(self.temp.name) / "first")
        self.state.manager_enter("owner")

    def test_single_active_chain_and_intent_before_child(self):
        intent = self.state.claim("design-0", 0, "owner", ram=2**30, free=2**40)
        self.assertEqual(self.state.design("design-0")["phase"], "SUBMIT_INTENT")
        self.assertIsNone(self.state.snapshot()["leases"][0]["wall_observed"])
        with self.assertRaisesRegex(Refusal, "NOT_DISPATCHABLE"):
            self.state.claim("design-0", 0, "owner", ram=2**30, free=2**40)

    def test_stop_reopen_requires_explicit_resume_and_stale_generation(self):
        generation = self.state.pause()
        reopened = State(self.state.directory)
        self.assertTrue(reopened.snapshot()["study"]["paused"])
        with self.assertRaisesRegex(Refusal, "CLOSED_OR_STALE"):
            reopened.claim("design-0", 0, "owner", ram=2**30, free=2**40)
        with self.assertRaisesRegex(Refusal, "STALE_GENERATION"):
            reopened.resume(generation - 1)
        next_generation = reopened.resume(generation)
        self.assertEqual(next_generation, generation + 1)

    def test_stop_after_intent_before_popen_blocks_spawn(self):
        intent = self.state.claim("design-0", 0, "owner", ram=2**30, free=2**40)
        self.state.pause()
        with self.assertRaisesRegex(Refusal, "CLOSED_OR_STALE"):
            with self.state.spawn_guard(intent):
                self.fail("Popen must not be reached")

    def test_intent_without_receipt_never_blind_retry(self):
        intent = self.state.claim("design-0", 0, "owner", ram=2**30, free=2**40)
        evidence = State(self.state.directory).reconcile()
        self.assertEqual(evidence["submission_unknown"], ["design-0"])
        self.assertEqual(self.state.design("design-0")["last_intent"], intent["intent_id"])
        self.assertEqual(self.state.snapshot()["leases"][0]["active"], 1)
        with self.assertRaisesRegex(Refusal, "NOT_DISPATCHABLE"):
            self.state.claim("design-0", 0, "owner", ram=2**30, free=2**40)

    def test_receipt_before_settlement_recovered_exactly_once(self):
        intent = self.state.claim("design-0", 0, "owner", ram=2**30, free=2**40)
        result = no_submission_result()
        self.state.record_completion(intent, result)
        receipt = dict(schema="KAZE_DISPATCH_RECEIPT_V1", intent=intent, at="synthetic-crash-cut", result=result)
        write_new(self.state.directory / "receipts" / (intent["intent_id"] + ".json"), canonical(receipt))
        State(self.state.directory).reconcile(); State(self.state.directory).reconcile()
        snapshot = self.state.snapshot()
        self.assertEqual(snapshot["leases"][0]["active"], 0)
        self.assertEqual(snapshot["study"]["wall_charged"], 1)

    def test_unknown_timeout_retains_lease_and_physical_does_not_block_other(self):
        first = self.state.claim("design-0", 0, "owner", ram=2**30, free=2**40)
        self.state.save_receipt(first, dict(outcome="TIMEOUT", parent_settled=False, safe_no_submission=False,
            process={"elapsed_seconds": 5}, summary=None, reason="TIMEOUT"))
        self.assertEqual(self.state.design("design-0")["phase"], "SUBMISSION_UNKNOWN")
        second = self.state.claim("design-1", 0, "owner", ram=2**30, free=2**40)
        self.state.save_receipt(second, fixture_settled_result(self.state, second))
        self.assertEqual(self.state.design("design-1")["phase"], "PHYSICAL")
        self.assertFalse(self.state.snapshot()["study"]["paused"])

    def test_kernel_lock_does_not_use_or_delete_pid_files(self):
        path = self.state.directory / "lock"
        with FileLock(path):
            with self.assertRaisesRegex(Refusal, "OWNERSHIP_LOCK_HELD"):
                with FileLock(path):
                    pass
        self.assertTrue(path.exists())
        with FileLock(path):
            pass

    def test_ram_disk_cost_refusals_preserve_intent_history(self):
        for kwargs, code in ((dict(ram=1, free=2**40), "RESOURCE_RAM_MEASURED"),
                             (dict(ram=2**30, free=1), "RESOURCE_DISK_MEASURED")):
            with self.subTest(code=code), self.assertRaisesRegex(Refusal, code):
                self.state.claim("design-0", 0, "owner", **kwargs)
        # No dispatch intent is committed when the global reservation refuses.
        self.assertEqual(self.state.design("design-0")["phase"], "PLANNED")
        low_cost = prepared_state(Path(self.temp.name) / "cost", alter=lambda spec: spec["cost"].update(cap="0.00001"))
        low_cost.manager_enter("cost")
        with self.assertRaisesRegex(Refusal, "RESOURCE_COST"):
            low_cost.claim("design-0", 0, "cost", ram=2**30, free=2**40)

    def test_global_pool_race_one_slot(self):
        root = Path(self.temp.name) / "race"; root.mkdir()
        def one_slot(spec):
            spec["concurrency"] = 1; spec["resources"]["slots"] = 1
        a = prepared_state(root / "a", pool=root / "shared.sqlite3", alter=one_slot)
        b = prepared_state(root / "b", pool=root / "shared.sqlite3", alter=one_slot)
        a.manager_enter("a"); b.manager_enter("b")
        barrier = threading.Barrier(2)
        def claim(state, token):
            barrier.wait()
            try:
                state.claim("design-0", 0, token, ram=2**30, free=2**40)
                return "ADMITTED"
            except Refusal as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(claim, a, "a"), executor.submit(claim, b, "b")]
            outcomes = [f.result() for f in futures]
        self.assertCountEqual(outcomes, ["ADMITTED", "RESOURCE_SLOTS"])

    def test_changed_engine_contract_cannot_reuse_binding_revision(self):
        with self.assertRaisesRegex(Refusal, "NEW_ENGINE_CONTRACT_REQUIRES_NEW_BINDING_REVISION"):
            prepared_state(Path(self.temp.name) / "changed", pool=self.state.pool,
                alter=lambda spec: spec["binding"]["runtime"].update(platform="different-runtime"))

