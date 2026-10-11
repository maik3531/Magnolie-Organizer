import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_personal_sync as sync


class AutoSyncNegotiationTest(unittest.TestCase):
    def setUp(self):
        self.items = {"personal_notes_sync": {"available": True, "versions": [1, 2, 3, 5, 8]},
                      "personal_tasks_sync": {"available": True, "versions": [1, 2, 3, 4, 6, 7, 8]}}

    def test_both_implementations_must_support_the_automatic_transport_contract(self):
        self.assertTrue(sync.auto_connection_supported(self.items, self.items))
        old = copy.deepcopy(self.items)
        old["personal_tasks_sync"]["versions"] = [1, 2, 3]
        self.assertFalse(sync.auto_connection_supported(self.items, old))
        self.assertFalse(sync.auto_connection_supported(old, self.items))
        old["personal_tasks_sync"]["versions"] = [8]
        old["personal_notes_sync"]["available"] = False
        self.assertFalse(sync.auto_connection_supported(self.items, old))
        self.assertFalse(sync.auto_connection_supported(None, self.items))

    def test_untyped_or_missing_markers_do_not_negotiate_the_new_contract(self):
        for versions in (["8"], [8.0], None, [], [True]):
            with self.subTest(versions=versions):
                broken = copy.deepcopy(self.items)
                broken["personal_notes_sync"]["versions"] = versions
                self.assertFalse(sync.auto_connection_supported(self.items, broken))

    def test_legacy_wifi_only_and_new_automatic_runs_are_distinct(self):
        self.assertEqual("auto_wifi", sync.automatic_trigger("wifi", False))
        self.assertIsNone(sync.automatic_trigger("bluetooth", False))
        self.assertEqual("auto_connection", sync.automatic_trigger("wifi", True))
        self.assertEqual("auto_connection", sync.automatic_trigger("bluetooth", True))
        self.assertIsNone(sync.automatic_trigger("unknown", True))
        self.assertFalse(sync.sync_trigger_allowed("auto_connection", False))
        self.assertTrue(sync.sync_trigger_allowed("auto_connection", True))
        self.assertTrue(sync.sync_trigger_allowed("manual", False))
        self.assertTrue(sync.sync_trigger_allowed("auto_wifi", False))
        self.assertFalse(sync.sync_trigger_allowed("unknown", True))


if __name__ == "__main__":
    unittest.main()
