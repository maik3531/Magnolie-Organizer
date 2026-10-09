import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_shared_sync as shared

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
C = "33333333-3333-4333-8333-333333333333"


class SharedFunctionSettingsTest(unittest.TestCase):
    def pair(self):
        a, b = shared.create(A), shared.create(B)
        return shared.merge(a, b, A, B), shared.merge(b, a, B, A)

    def converge(self, a, b):
        return shared.merge(a, b, A, B), shared.merge(b, a, B, A)

    def test_one_choice_on_either_side_updates_the_common_content_scope(self):
        a, b = self.pair()
        a = shared.change(a, A, B, "content_mode", "two_way")
        a, b = self.converge(a, b)
        self.assertEqual("two_way", shared.effective(b)["content_mode"])
        b = shared.change(b, B, A, "content_mode", "phone_scope")
        a, b = self.converge(a, b)
        self.assertEqual("phone_scope", shared.effective(a)["content_mode"])
        self.assertEqual(shared.effective(a), shared.effective(b))
        self.assertEqual(a, shared.merge(a, b, A, B), "Echo created new revisions or a feedback loop")

    def test_independent_settings_and_time_direction_are_not_overwritten(self):
        a, b = self.pair()
        a = shared.change(a, A, B, "auto_mode", "connection")
        b = shared.change(b, B, A, "time_mode", "two_way")
        a, b = self.converge(a, b)
        value = shared.effective(a)
        self.assertEqual("connection", value["auto_mode"])
        self.assertEqual("two_way", value["time_mode"])
        self.assertEqual("phone_scope", value["content_mode"])
        self.assertFalse(value["custom_enabled"])
        self.assertEqual(value, shared.effective(b))

    def test_concurrent_same_setting_converges_and_can_be_changed_once_afterwards(self):
        a, b = self.pair()
        a = shared.change(a, A, B, "content_mode", "two_way")
        b = shared.change(b, B, A, "content_mode", "phone_scope")
        a, b = self.converge(a, b)
        self.assertEqual("phone_scope", shared.effective(a)["content_mode"])
        self.assertEqual(shared.effective(a), shared.effective(b))
        b = shared.change(b, B, A, "content_mode", "two_way")
        a, b = self.converge(a, b)
        self.assertEqual("two_way", shared.effective(a)["content_mode"])
        self.assertEqual(shared.effective(a), shared.effective(b))

    def test_stale_replay_and_reopened_state_do_not_restore_older_preferences(self):
        a, b = self.pair()
        old = copy.deepcopy(b)
        b = shared.change(b, B, A, "skip_deletions", False)
        b = shared.change(b, B, A, "skip_deletions", True)
        a, b = self.converge(a, b)
        reopened = copy.deepcopy(a)
        self.assertEqual(reopened, shared.merge(reopened, old, A, B))
        self.assertTrue(shared.effective(reopened)["skip_deletions"])

    def test_other_peer_and_forged_local_echo_are_rejected_atomically(self):
        a, b = self.pair()
        original = copy.deepcopy(a)
        with self.assertRaises(ValueError):
            shared.merge(a, shared.create(C), A, B)
        b["settings"]["auto_mode"][B] = {"counter": 1, "value": "connection"}
        b["settings"]["content_mode"][A] = {"counter": 1, "value": "two_way"}
        with self.assertRaises(ValueError):
            shared.merge(a, b, A, B)
        self.assertEqual(original, a, "A rejected multi-setting message partially changed state")

    def test_schema_and_same_actor_same_clock_conflicts_are_rejected(self):
        a, b = self.pair()
        for field, value in (("unknown", True), ("custom_enabled", 1), ("content_mode", "invalid")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                shared.change(a, A, B, field, value)
        b["settings"]["content_mode"][B]["value"] = "two_way"
        with self.assertRaises(ValueError):
            shared.merge(a, b, A, B)
        b["settings"]["content_mode"][B]["counter"] = 1.0
        with self.assertRaises(ValueError):
            shared.validate(b)

    def test_legacy_wifi_migration_never_implies_transport_free_automation(self):
        a = shared.create(A, {"auto_mode": "wifi"})
        b = shared.create(B)
        a, b = self.converge(a, b)
        self.assertEqual("wifi", shared.effective(a)["auto_mode"])
        self.assertEqual(shared.effective(a), shared.effective(b))


if __name__ == "__main__":
    unittest.main()
