from types import SimpleNamespace
import unittest
from kaze_study.errors import Refusal
from kaze_study.ninety_owned_aux import effective_spec


class PublicPackagingTests(unittest.TestCase):
    def test_original_direct_store_is_never_dispatched_without_private_authority(self):
        state = SimpleNamespace(study=SimpleNamespace(spec={"ninety_contract": {"direct_main_version": "DIRECT90D_USER_SCOPE_V1"}}))
        with self.assertRaisesRegex(Refusal, "PRIVATE_DIRECT90D_AUTHORITY"):
            effective_spec(state)
