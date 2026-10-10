import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import magnolie_content_scope as scope


def record(kind, identity, text="", notebook=""):
    return {"kind": kind, "id": identity, "state": "live", "value": {"text": text, "notebook_id": notebook}}


class PhoneContentScopeTest(unittest.TestCase):
    def test_organizer_updates_of_current_phone_notes_return_without_unrelated_content(self):
        manifest = scope.create(["mobile-note"], ["mobile-task"])
        records = [record("note", "mobile-note", "Organizer addition", "shared-book"),
                   record("note", "organizer-only", "Private organizer text", "private-book"),
                   record("task", "mobile-task"), record("task", "organizer-task"),
                   record("notebook", "shared-book"), record("notebook", "private-book")]
        selected = scope.filter_records(records, manifest)
        self.assertEqual([("note", "mobile-note"), ("task", "mobile-task"), ("notebook", "shared-book")],
                         [(item["kind"], item["id"]) for item in selected])
        self.assertEqual("Organizer addition", selected[0]["value"]["text"])

    def test_phone_removal_does_not_delete_organizer_copy_or_reintroduce_phone_copy(self):
        old = scope.create(["mobile-note"], ["mobile-task"])
        organizer = [record("note", "mobile-note", "Keep on organizer"), record("task", "mobile-task")]
        unchanged = copy.deepcopy(organizer)
        removed = scope.advance(old, [], [])
        self.assertEqual([], scope.filter_records(organizer, removed))
        self.assertEqual(unchanged, organizer)
        with self.assertRaises(ValueError):
            scope.require_current(scope.reference(old), removed)
        scope.require_current(scope.reference(removed), removed)

    def test_unchanged_membership_does_not_reset_generation(self):
        manifest = scope.create(["mobile-note"], [])
        self.assertIs(manifest, scope.advance(manifest, ["mobile-note"], []))

    def test_large_manifest_is_bounded_chunked_and_duplicate_delivery_is_idempotent(self):
        manifest = scope.create(["note-%05d" % n for n in range(1300)], ["task-%05d" % n for n in range(700)])
        chunks = scope.chunks(manifest)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk["members"]) <= 256 for chunk in chunks))
        received = list(reversed(chunks)) + [copy.deepcopy(chunks[0])]
        self.assertEqual(manifest, scope.assemble(received))
        with self.assertRaises(ValueError):
            scope.assemble(chunks[:-1])

    def test_mixed_generations_and_conflicting_parts_are_rejected(self):
        manifest = scope.create(["note-%03d" % n for n in range(100)], [])
        chunks = scope.chunks(manifest, 32)
        newer = scope.chunks(scope.advance(manifest, ["different"], []), 32)
        with self.assertRaises(ValueError):
            scope.assemble([chunks[0], newer[0]])
        changed = copy.deepcopy(chunks[0]); changed["members"][0]["id"] = "aaa-different"
        with self.assertRaises(ValueError):
            scope.assemble(chunks + [changed])

    def test_scope_hash_order_identity_and_reference_types_are_strict(self):
        manifest = scope.create(["\ue000", "😀", "mobile-note"], [])
        self.assertEqual(["mobile-note", "\ue000", "😀"], manifest["members"]["notes"])
        self.assertEqual(manifest, scope.assemble(scope.chunks(manifest)))
        wrong = copy.deepcopy(manifest); wrong["members"]["notes"].reverse()
        with self.assertRaises(ValueError):
            scope.validate(wrong)
        wrong = scope.reference(manifest); wrong["scope_revision"] = True
        with self.assertRaises(ValueError):
            scope.require_current(wrong, manifest)

    def test_excluded_content_is_not_read_or_materialized(self):
        class PrivateRecord(dict):
            def get(self, key, default=None):
                if key == "value":
                    raise AssertionError("Excluded organizer content accessed")
                return super().get(key, default)
        records = [PrivateRecord(kind="note", id="organizer-only", state="live"), record("note", "mobile-note", "Shared")]
        self.assertEqual([records[1]], scope.filter_records(records, scope.create(["mobile-note"], [])))

    def test_empty_scope_does_not_authorize_whole_library(self):
        manifest = scope.create([], [])
        self.assertEqual([], scope.filter_records([record("note", "organizer-only"), record("task", "organizer-only")], manifest))
        self.assertEqual(manifest, scope.assemble(scope.chunks(manifest)))

    def test_deleted_records_never_return_even_when_a_live_record_has_same_id(self):
        live = record("note", "mobile-note", "Current")
        removed = {"kind": "note", "id": "mobile-note", "state": "deleted"}
        self.assertEqual([live], scope.filter_records([live, removed], scope.create(["mobile-note"], [])))

    def test_session_requires_complete_current_generation_and_connection_binding(self):
        binding = ("peer", "public-key", "connection-1")
        session = scope.ScopeSession(binding)
        first = scope.create(["note-%03d" % n for n in range(100)], [])
        pieces = scope.chunks(first, 32)
        self.assertIsNone(session.receive(binding, pieces[-1]))
        with self.assertRaises(PermissionError):
            session.current(binding, scope.reference(first))
        for part in pieces[:-1]:
            session.receive(binding, part)
        self.assertEqual(first, session.current(binding, scope.reference(first)))
        with self.assertRaises(PermissionError):
            session.current(("peer", "public-key", "connection-2"), scope.reference(first))
        second = scope.advance(first, ["updated-%03d" % n for n in range(100)], [])
        updated = scope.chunks(second, 32)
        self.assertIsNone(session.receive(binding, updated[0]))
        with self.assertRaises(PermissionError):
            session.current(binding, scope.reference(first))
        self.assertIsNone(session.receive(binding, pieces[0]))
        for part in updated[1:]:
            session.receive(binding, part)
        self.assertEqual(second, session.current(binding, scope.reference(second)))
        exposed = session.current(binding, scope.reference(second)); exposed["members"]["notes"].clear()
        self.assertEqual(second, session.current(binding, scope.reference(second)))

    def test_conflicting_session_frame_closes_gate_until_new_connection(self):
        binding = ("peer", "key", "connection")
        session = scope.ScopeSession(binding)
        first = scope.create(["mobile-note"], [])
        part = scope.chunks(first)[0]; session.receive(binding, part)
        tampered = copy.deepcopy(part); tampered["members"][0]["id"] = "foreign-note"
        with self.assertRaises(ValueError):
            session.receive(binding, tampered)
        with self.assertRaises(PermissionError):
            session.current(binding, scope.reference(first))
        with self.assertRaises(ValueError):
            session.receive(binding, part)
        fresh = scope.ScopeSession(("peer", "key", "new-connection"))
        self.assertEqual(first, fresh.receive(fresh.binding, part))


if __name__ == "__main__":
    unittest.main()
