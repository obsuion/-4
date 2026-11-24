from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from kaze_study.data import canonical, identity, write_new
from kaze_study.errors import Refusal
from kaze_study.state import State
from support import prepared_state, no_submission_result, fixture_settled_result


class RecoveryR1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kaze-recovery-r1-"); self.addCleanup(self.tmp.cleanup)
        self.state = prepared_state(Path(self.tmp.name) / "state"); self.state.manager_enter("owner")
        self.intent = self.state.claim("design-0", 0, "owner", ram=2**30, free=2**40)

    def crash_receipt(self, result):
        write_new(self.state.directory / "receipts" / (self.intent["intent_id"] + ".json"),
            canonical(dict(schema="KAZE_DISPATCH_RECEIPT_V1", intent=self.intent, result=result, at="crash-test")))

    def assert_unknown(self):
        State(self.state.directory).reconcile()
        self.assertEqual(self.state.design("design-0")["phase"], "SUBMISSION_UNKNOWN")
        self.assertEqual(self.state.snapshot()["leases"][0]["active"], 1)

    def test_boolean_target_without_summary_process_or_completion_is_unknown(self):
        self.crash_receipt(dict(outcome="TARGET", parent_settled=True, safe_no_submission=False, summary=None, process={}, reason=None))
        self.assert_unknown()

    def test_not_created_with_an_owner_cannot_release(self):
        value = no_submission_result(); value["process"]["owner"] = {"pid": 123}
        self.crash_receipt(value); self.assert_unknown()

    def test_initial_store_appearing_after_intent_cannot_be_adopted_at_spawn(self):
        Path(self.intent["store"]).mkdir()
        with self.assertRaisesRegex(Refusal, "NO_OWNERSHIP_ADOPTION"):
            with self.state.spawn_guard(self.intent):
                self.fail("foreign/orphan store cannot become initial dispatch")
        self.assertEqual(self.state.snapshot()["leases"][0]["active"], 1)

    def test_receipt_rewritten_after_independent_completion_pin_is_unknown(self):
        value = no_submission_result(); self.state.record_completion(self.intent, value)
        value["outcome"] = "TARGET"; value["safe_no_submission"] = False; value["parent_settled"] = True
        self.crash_receipt(value); self.assert_unknown()

    def test_valid_owner_terminal_completion_survives_stop_and_reopen(self):
        value = fixture_settled_result(self.state, self.intent)
        self.state.record_completion(self.intent, value); self.state.pause()
        self.crash_receipt(value); recovered = State(self.state.directory).reconcile()
        self.assertEqual(recovered["recovered"], ["design-0"])
        self.assertEqual(self.state.design("design-0")["phase"], "PHYSICAL")
        self.assertTrue(self.state.snapshot()["study"]["paused"])

    def test_unknown_suffix_or_owner_substitution_cannot_pin_settlement(self):
        base = fixture_settled_result(self.state, self.intent)
        for mutate in (lambda v: v["summary"].update(reserved_unknown_seconds=1),
                       lambda v: v["process"].update(owner={"pid": 999}),
                       lambda v: v["process"].update(reaped=False)):
            value = deepcopy(base); mutate(value)
            with self.assertRaises(Refusal): self.state.record_completion(self.intent, value)
        self.assertEqual(self.state.snapshot()["leases"][0]["active"], 1)
