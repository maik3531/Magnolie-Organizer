"""Synthetic release transactions against a persistent in-memory GitLab model.

The authorization callback below is test data, never production release approval.
No network requests, published packages, credentials or signing keys are used.
"""

import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gitlab_release_storage as storage
from gitlab_storage_api import GitLabAPIError


PROJECT = "maik3531/mint-forgs"
PACKAGE = "synthetic-release"
METADATA = "release-storage/current.json"
CHECKSUMS = "release-storage/current.sha256"


def file_hash(data):
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


class FakeGitLab:
    """Persistent remote objects, immutable Git snapshots and atomic file CAS."""

    def __init__(self):
        self.project_path = PROJECT
        self.project_id = 78301901
        self.statistics = {"repository_size": 1024, "lfs_objects_size": 0, "packages_size": 0}
        self.commit_number = 1
        self.current_head = "%040x" % self.commit_number
        self.snapshots = {self.current_head: {}}
        self.registry = {}
        self.next_package = 10
        self.next_file = 1000
        self.events = []
        self.commits = []
        self.after_upload = None
        self.after_active = None
        self.fail_upload_name = None
        self.ambiguous_commits = set()
        self.interrupt_delete_after_removal = False
        self.interrupt_delete_before_removal = False
        self.defer_deletion = False
        self.before_commit = None

    def project(self):
        return {"id": self.project_id, "path_with_namespace": self.project_path,
                "statistics": copy.deepcopy(self.statistics)}

    def head(self, branch):
        assert branch == "main"
        return self.current_head

    def file(self, path, ref):
        tree = self.snapshots[self.current_head if ref == "main" else ref]
        row = tree.get(path)
        if row is None:
            return None
        data = row["data"]
        return {"file_path": path, "encoding": "base64", "content": base64.b64encode(data).decode(),
                "size": len(data), "content_sha256": hashlib.sha256(data).hexdigest(),
                "last_commit_id": row["last_commit_id"]}

    def bytes_at(self, path):
        row = self.snapshots[self.current_head].get(path)
        return row["data"] if row else None

    def state(self):
        data = self.bytes_at(storage.STATE_PATH)
        return json.loads(data) if data is not None else None

    def _write_commit(self, changes):
        self.commit_number += 1
        commit = "%040x" % self.commit_number
        tree = copy.deepcopy(self.snapshots[self.current_head])
        for path, data in changes.items():
            if data is None:
                tree.pop(path, None)
            else:
                tree[path] = {"data": data, "last_commit_id": commit}
        self.snapshots[commit] = tree
        self.current_head = commit
        return commit

    def external_commit(self, changes):
        return self._write_commit(changes)

    def commit(self, branch, actions, message):
        assert branch == "main"
        if self.before_commit is not None:
            callback, self.before_commit = self.before_commit, None
            callback(self, actions)
        tree = self.snapshots[self.current_head]
        changes = {}
        for action in actions:
            path = action["file_path"]
            row = tree.get(path)
            if action["action"] == "create":
                if row is not None:
                    raise GitLabAPIError("Synthetic create conflict", 409)
            elif action["action"] == "update":
                if row is None or row["last_commit_id"] != action.get("last_commit_id"):
                    raise GitLabAPIError("Synthetic file CAS conflict", 400)
            else:
                raise AssertionError("Unexpected mutation action")
            assert action["encoding"] == "base64"
            changes[path] = base64.b64decode(action["content"], validate=True)
        result = self._write_commit(changes)
        phase = (self.state().get("operation") or {}).get("phase")
        self.events.append(("commit", phase, tuple(changes)))
        self.commits.append(copy.deepcopy(actions))
        if phase == "active" and self.after_active is not None:
            callback, self.after_active = self.after_active, None
            callback(self)
        if phase in self.ambiguous_commits:
            self.ambiguous_commits.remove(phase)
            raise GitLabAPIError("Synthetic lost commit response")
        return result

    def add_package(self, name, version, payloads=None, status="default"):
        identifier = self.next_package
        self.next_package += 1
        self.registry[identifier] = {"id": identifier, "name": name, "version": version,
                                     "package_type": "generic", "status": status, "payloads": []}
        for filename, data in (payloads or {}).items():
            self.add_file(identifier, filename, data)
        return identifier

    def add_file(self, identifier, filename, data):
        row = {"id": self.next_file, "file_name": filename, "data": data}
        self.next_file += 1
        self.registry[identifier]["payloads"].append(row)
        self.statistics["packages_size"] += len(data)
        return row

    def packages(self, name):
        return [copy.deepcopy({key: value for key, value in row.items() if key != "payloads"})
                for row in sorted(self.registry.values(), key=lambda row: row["id"]) if row["name"] == name]

    def package(self, identifier):
        row = self.registry.get(identifier)
        if row is None or row["status"] not in {"default", "deprecated"}:
            return None
        return copy.deepcopy({key: value for key, value in row.items() if key != "payloads"})

    def files(self, identifier):
        if identifier not in self.registry:
            raise GitLabAPIError("Synthetic package missing", 404)
        return [{"id": row["id"], "file_name": row["file_name"],
                 "file_sha256": row.get("reported_hash", hashlib.sha256(row["data"]).hexdigest()),
                 "size": len(row["data"])} for row in self.registry[identifier]["payloads"]]

    def target(self, name, version):
        rows = [row for row in self.registry.values() if row["name"] == name and row["version"] == version]
        if len(rows) != 1:
            raise GitLabAPIError("Synthetic missing or ambiguous package", 404)
        return rows[0]

    def upload(self, name, version, filename, path):
        self.events.append(("upload", version, filename))
        if self.fail_upload_name == filename:
            self.fail_upload_name = None
            raise GitLabAPIError("Synthetic interrupted upload")
        rows = [row for row in self.registry.values() if row["name"] == name and row["version"] == version]
        identifier = rows[0]["id"] if rows else self.add_package(name, version)
        self.add_file(identifier, filename, Path(path).read_bytes())
        if self.after_upload is not None:
            self.after_upload(self, identifier, filename)

    def verify_download(self, name, version, filename, expected):
        self.events.append(("verify", version, filename))
        rows = [row for row in self.target(name, version)["payloads"] if row["file_name"] == filename]
        if len(rows) != 1 or file_hash(rows[0]["data"]) != expected:
            raise GitLabAPIError("Synthetic remote bytes did not verify")

    def delete_package(self, identifier):
        self.events.append(("delete", identifier))
        if self.interrupt_delete_before_removal:
            self.interrupt_delete_before_removal = False
            raise KeyboardInterrupt("Synthetic interrupted deletion")
        if self.defer_deletion and identifier in self.registry:
            self.registry[identifier]["status"] = "pending_destruction"
            return
        row = self.registry.pop(identifier, None)
        if row is None:
            raise GitLabAPIError("Synthetic package missing", 404)
        self.statistics["packages_size"] -= sum(len(item["data"]) for item in row["payloads"])
        if self.interrupt_delete_after_removal:
            self.interrupt_delete_after_removal = False
            raise KeyboardInterrupt("Synthetic lost delete response")

    def mutations(self):
        return [row for row in self.events if row[0] in {"commit", "upload", "delete"}]


class ReleaseStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.api = FakeGitLab()
        self.authorizations = 0

    def authorize(self):
        # Deliberately synthetic; never passed to the production CLI or GitLab.
        self.authorizations += 1
        self.api.events.append(("synthetic_authorize",))

    def candidate(self, version):
        directory = self.root / version
        directory.mkdir(exist_ok=True)
        artifact = ("synthetic package %s\n" % version).encode() * 40
        manifest = storage.canonical({"synthetic": True, "version": version,
                                      "sha256": hashlib.sha256(artifact).hexdigest()})
        checksums = (hashlib.sha256(artifact).hexdigest() + "  artifact.bin\n").encode()
        values = {"artifact.bin": artifact, "manifest.json": manifest, "checksums.txt": checksums}
        for name, value in values.items():
            (directory / name).write_bytes(value)
        spec = {"schema": storage.SPEC_SCHEMA, "project": PROJECT, "branch": "main",
                "package": PACKAGE, "version": version,
                "files": {name: file_hash(value) for name, value in values.items()},
                "metadata": {METADATA: "manifest.json", CHECKSUMS: "checksums.txt"}}
        return spec, directory

    def plan(self, version):
        spec, directory = self.candidate(version)
        plan = storage.build_plan(self.api, spec, directory, self.authorize)
        return plan, directory

    def apply(self, plan, directory, *, reports=None, execution_id=None, previous_report=None):
        options = {"report": reports.append if reports is not None else None}
        if execution_id is not None:
            options["execution_id"] = execution_id
        if previous_report is not None:
            options["previous_report"] = previous_report
        return storage.apply_plan(self.api, plan, directory, storage.identity(plan), self.authorize, **options)

    def publish(self, version="1.0.0"):
        plan, directory = self.plan(version)
        reports = []
        result = self.apply(plan, directory, reports=reports)
        return plan, directory, result, reports

    def assert_no_activation_or_delete(self, metadata_before):
        self.assertFalse(any(row[0] == "delete" or row[:2] == ("commit", "active") for row in self.api.events))
        for path, value in metadata_before.items():
            self.assertEqual(self.api.bytes_at(path), value)

    def test_first_publish_plan_is_read_only_and_activation_follows_full_verification(self):
        plan, directory = self.plan("1.0.0")
        self.assertEqual(self.api.mutations(), [])
        self.assertEqual(plan["delete"], [])
        self.assertEqual(plan["expected_upload_bytes"], sum(value["bytes"] for value in plan["spec"]["files"].values()))
        reports = []
        result = self.apply(plan, directory, reports=reports)
        self.assertEqual(result["status"], "complete")
        self.assertIsNone(result["physical_freed_bytes"])
        self.assertEqual(result["confirmed_deleted_object_bytes"], 0)
        self.assertEqual(len(self.api.packages(PACKAGE)), 1)
        self.assertIsNone(self.api.state()["operation"])
        self.assertEqual(self.api.state()["channels"][PACKAGE]["version"], "1.0.0")
        activation = next(index for index, row in enumerate(self.api.events) if row[:2] == ("commit", "active"))
        verified = {row[2] for row in self.api.events[:activation] if row[0] == "verify"}
        self.assertEqual(verified, set(plan["spec"]["files"]))
        for path, source in plan["spec"]["metadata"].items():
            self.assertEqual(self.api.bytes_at(path), (directory / source).read_bytes())
        self.assertEqual({item["file_path"] for commit in self.api.commits for item in commit},
                         {storage.STATE_PATH, METADATA, CHECKSUMS})
        self.assertEqual([row[1] for row in self.api.events if row[0] == "commit"], ["uploading", "active", None])
        self.assertGreaterEqual(self.authorizations, 3)
        self.assertEqual(reports[-1], result)
        self.assertRegex(result["execution_id"], r"^[0-9a-f]{32}$")

    def test_private_resume_identity_is_never_written_to_public_state(self):
        plan, directory = self.plan("1.0.0")
        self.api.fail_upload_name = "manifest.json"
        reports = []
        with self.assertRaises(GitLabAPIError):
            self.apply(plan, directory, reports=reports)
        nonce = reports[-1]["execution_id"]
        public = self.api.bytes_at(storage.STATE_PATH)
        self.assertNotIn(nonce.encode(), public)
        self.assertEqual(self.api.state()["operation"]["execution_sha256"],
                         hashlib.sha256(nonce.encode()).hexdigest())

    def test_desktop_adapter_cannot_publish_checksums_as_update_manifest(self):
        spec, _ = self.candidate("1.0.0")
        spec["package"] = "magnolie-desktop"
        spec["files"]["update.xml"] = file_hash(b"synthetic manifest; actual signature verified separately")
        spec["metadata"] = {"Magnolie-Organitzer/update.xml": "update.xml"}
        storage.desktop_spec(spec)
        for mapping in ({"Magnolie-Organitzer/update.xml": "checksums.txt"},
                        {"Magnolie-Organitzer/README.md": "manifest.json"},
                        {"another-directory/update.xml": "update.xml"},
                        {"Magnolie-Organitzer/update.xml": "update.xml", "foreign/current.json": "manifest.json"}):
            with self.subTest(mapping=mapping):
                invalid = copy.deepcopy(spec)
                invalid["metadata"] = mapping
                with self.assertRaises(ValueError):
                    storage.desktop_spec(invalid)

    def test_second_publish_deletes_exact_previous_only_after_activation(self):
        fdroid = self.api.add_package("fdroid-reference", "1.0.21", {"reference.apk": b"synthetic reference"})
        other = self.api.add_package("different-project-channel", "9.0.0", {"other.bin": b"synthetic other"})
        _, _, first, _ = self.publish()
        old_id = self.api.state()["channels"][PACKAGE]["package_id"]
        old_size = sum(len(row["data"]) for row in self.api.registry[old_id]["payloads"])
        untouched = {identifier: copy.deepcopy(self.api.registry[identifier]) for identifier in (fdroid, other)}
        self.api.events.clear()
        _, _, result, _ = self.publish("1.0.1")
        self.assertEqual(result["deleted_ids"], [old_id])
        self.assertEqual(result["confirmed_deleted_object_bytes"], old_size)
        self.assertIsNone(result["physical_freed_bytes"])
        self.assertNotIn(old_id, self.api.registry)
        self.assertEqual({identifier: self.api.registry[identifier] for identifier in (fdroid, other)}, untouched)
        self.assertEqual([row["version"] for row in self.api.packages(PACKAGE)], ["1.0.1"])
        activation = next(index for index, row in enumerate(self.api.events) if row[:2] == ("commit", "active"))
        deletion = next(index for index, row in enumerate(self.api.events) if row[0] == "delete")
        self.assertLess(activation, deletion)
        self.assertTrue(any(row[0] == "verify" for row in self.api.events[activation + 1:deletion]))

    def test_upload_failure_preserves_active_metadata_then_resumes_without_duplicate_upload(self):
        self.publish()
        before = {path: self.api.bytes_at(path) for path in (METADATA, CHECKSUMS)}
        old_id = self.api.state()["channels"][PACKAGE]["package_id"]
        plan, directory = self.plan("1.0.1")
        self.api.events.clear()
        self.api.fail_upload_name = "manifest.json"
        reports = []
        with self.assertRaises(GitLabAPIError):
            self.apply(plan, directory, reports=reports)
        self.assertEqual(reports[-1]["status"], "failed")
        self.assert_no_activation_or_delete(before)
        self.assertEqual(self.api.state()["channels"][PACKAGE]["package_id"], old_id)
        result = self.apply(plan, directory, reports=reports, execution_id=reports[-1]["execution_id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.api.events.count(("upload", "1.0.1", "artifact.bin")), 1)
        self.assertEqual(self.api.events.count(("upload", "1.0.1", "manifest.json")), 2)
        self.assertNotIn(old_id, self.api.registry)

    def test_same_plan_with_another_execution_id_cannot_take_over(self):
        plan, directory = self.plan("1.0.0")
        self.api.fail_upload_name = "manifest.json"
        reports = []
        with self.assertRaises(GitLabAPIError):
            self.apply(plan, directory, reports=reports)
        before = copy.deepcopy(self.api.mutations())
        with self.assertRaises(ValueError):
            self.apply(plan, directory, execution_id="f" * 32)
        self.assertEqual(self.api.mutations(), before)
        with self.assertRaises(ValueError):
            self.apply(plan, directory)
        self.assertEqual(self.api.mutations(), before)

    def test_resume_budget_counts_only_bytes_still_missing(self):
        spec, directory = self.candidate("1.0.0")
        total = sum(value["bytes"] for value in spec["files"].values())
        with patch.dict(storage.POLICY, {"registry_budget_bytes": total + 110,
                                         "registry_reserve_bytes": 100}):
            plan = storage.build_plan(self.api, spec, directory, self.authorize)
            self.api.fail_upload_name = "manifest.json"
            reports = []
            with self.assertRaises(GitLabAPIError):
                self.apply(plan, directory, reports=reports)
            result = self.apply(plan, directory, reports=reports, execution_id=reports[-1]["execution_id"])
            self.assertEqual(result["status"], "complete")
            self.assertEqual(self.api.events.count(("upload", "1.0.0", "artifact.bin")), 1)

    def test_failed_remote_validation_never_activates_or_deletes(self):
        for case in ("bad_hash", "extra", "missing", "duplicate_file", "duplicate_package", "processing"):
            with self.subTest(case=case):
                self.api = FakeGitLab()
                self.publish()
                before = {path: self.api.bytes_at(path) for path in (METADATA, CHECKSUMS)}
                old_id = self.api.state()["channels"][PACKAGE]["package_id"]
                plan, directory = self.plan("1.0.1")
                self.api.events.clear()
                def corrupt(api, identifier, filename):
                    api.after_upload = None
                    row = api.registry[identifier]["payloads"][0]
                    if case == "bad_hash":
                        row["reported_hash"] = hashlib.sha256(row["data"]).hexdigest()
                        row["data"] = b"X" * len(row["data"])
                    elif case == "extra":
                        api.add_file(identifier, "unapproved.bin", b"unapproved")
                    elif case == "missing":
                        api.registry[identifier]["payloads"].clear()
                    elif case == "duplicate_file":
                        api.add_file(identifier, filename, row["data"])
                    elif case == "duplicate_package":
                        api.add_package(PACKAGE, "1.0.1", {filename: row["data"]})
                    else:
                        api.registry[identifier]["status"] = "processing"
                self.api.after_upload = corrupt
                with self.assertRaises((ValueError, GitLabAPIError)):
                    self.apply(plan, directory)
                self.assert_no_activation_or_delete(before)
                self.assertIn(old_id, self.api.registry)

    def test_stale_or_invalid_plan_inputs_stop_before_any_mutation(self):
        for case in ("head", "state", "inventory", "statistics", "git_budget", "registry_budget",
                     "project", "local_hash", "plan_hash", "changed_spec"):
            with self.subTest(case=case):
                self.api = FakeGitLab()
                plan, directory = self.plan("1.0.0")
                accepted = storage.identity(plan)
                if case == "head":
                    self.api.external_commit({"unrelated.txt": b"external change"})
                elif case == "state":
                    value = {"schema": storage.STATE_SCHEMA, "project": PROJECT,
                             "channels": {}, "operation": {"plan_sha256": "f" * 64, "phase": "uploading"}}
                    self.api.external_commit({storage.STATE_PATH: storage.canonical(value)})
                elif case == "inventory":
                    self.api.add_package(PACKAGE, "0.9.0", {"old.bin": b"other release"})
                elif case == "statistics":
                    self.api.statistics.pop("lfs_objects_size")
                elif case == "git_budget":
                    self.api.statistics["repository_size"] = storage.POLICY["git_lfs_limit_bytes"]
                elif case == "registry_budget":
                    self.api.statistics["packages_size"] = storage.POLICY["registry_budget_bytes"]
                elif case == "project":
                    self.api.project_path = "maik3531/dictation"
                elif case == "local_hash":
                    path = directory / "artifact.bin"
                    path.write_bytes(b"X" * path.stat().st_size)
                elif case == "plan_hash":
                    accepted = "f" * 64
                else:
                    plan["spec"]["version"] = "1.0.1"
                self.api.events.clear()
                with self.assertRaises((ValueError, GitLabAPIError)):
                    storage.apply_plan(self.api, plan, directory, accepted, self.authorize)
                self.assertEqual(self.api.mutations(), [])

    def test_interrupted_cleanup_resumes_with_no_upload_or_rollback(self):
        for after_removal in (False, True):
            with self.subTest(after_removal=after_removal):
                self.api = FakeGitLab()
                self.publish()
                old_id = self.api.state()["channels"][PACKAGE]["package_id"]
                plan, directory = self.plan("1.0.1")
                self.api.interrupt_delete_after_removal = after_removal
                self.api.interrupt_delete_before_removal = not after_removal
                reports = []
                with self.assertRaises(KeyboardInterrupt):
                    self.apply(plan, directory, reports=reports)
                self.assertEqual(reports[-1]["status"], "interrupted")
                self.assertEqual(self.api.state()["channels"][PACKAGE]["version"], "1.0.1")
                self.assertEqual(self.api.bytes_at(METADATA), (directory / "manifest.json").read_bytes())
                self.api.events.clear()
                result = self.apply(plan, directory, reports=reports, execution_id=reports[-1]["execution_id"])
                self.assertEqual(result["status"], "complete")
                self.assertFalse(any(row[0] == "upload" for row in self.api.events))
                self.assertFalse(any(row[:2] == ("commit", "active") for row in self.api.events))
                self.assertNotIn(old_id, self.api.registry)
                self.assertEqual(result["already_absent_ids"], [old_id] if after_removal else [])
                self.assertEqual(result["deleted_ids"], [] if after_removal else [old_id])

    def test_same_project_path_with_replacement_numeric_id_stops_before_mutation(self):
        plan, directory = self.plan("1.0.0")
        self.api.project_id += 1
        self.api.events.clear()
        with self.assertRaisesRegex(ValueError, "project ID changed"):
            self.apply(plan, directory)
        self.assertEqual(self.api.mutations(), [])

    def test_report_failure_after_confirmed_deletion_preserves_evidence_on_resume(self):
        self.publish()
        old_id = self.api.state()["channels"][PACKAGE]["package_id"]
        old_bytes = sum(len(row["data"]) for row in self.api.registry[old_id]["payloads"])
        plan, directory = self.plan("1.0.1")
        reports = []
        failed_once = []
        def report(value):
            if value["status"] == "complete" and not failed_once:
                failed_once.append(True)
                raise OSError("Synthetic completion-report write failure")
            reports.append(copy.deepcopy(value))
        with self.assertRaisesRegex(OSError, "completion-report"):
            storage.apply_plan(self.api, plan, directory, storage.identity(plan), self.authorize, report)
        previous = copy.deepcopy(reports[-1])
        self.assertEqual(previous["status"], "failed")
        self.assertEqual(previous["deleted_ids"], [old_id])
        self.assertEqual(previous["confirmed_deleted_object_bytes"], old_bytes)
        self.assertNotIn(old_id, self.api.registry)
        self.assertIsNone(self.api.state()["operation"])
        # Counts are recomputed from the bound plan, not trusted from a journal.
        previous["confirmed_deleted_object_bytes"] = 999999999
        self.api.events.clear()
        result = self.apply(plan, directory, reports=reports, execution_id=previous["execution_id"],
                            previous_report=previous)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["deleted_ids"], [old_id])
        self.assertEqual(result["delete_requested_ids"], [old_id])
        self.assertEqual(result["already_absent_ids"], [])
        self.assertEqual(result["confirmed_deleted_object_bytes"], old_bytes)
        self.assertIsNone(result["physical_freed_bytes"])
        self.assertEqual(self.api.mutations(), [])

    def test_ambiguous_successful_commits_are_recovered_by_readback(self):
        for phase in ("uploading", "active", None):
            with self.subTest(phase=phase):
                self.api = FakeGitLab()
                self.api.ambiguous_commits.add(phase)
                _, _, result, _ = self.publish()
                self.assertEqual(result["status"], "complete")
                self.assertEqual(len(self.api.commits), 3)
                self.assertIsNone(self.api.state()["operation"])

    def test_metadata_changed_during_upload_stops_further_mutation(self):
        self.publish()
        plan, directory = self.plan("1.0.1")
        self.api.events.clear()
        def replace_metadata(api, identifier, filename):
            api.after_upload = None
            api.external_commit({METADATA: b'{"synthetic":"external change"}\n'})
        self.api.after_upload = replace_metadata
        with self.assertRaises(ValueError):
            self.apply(plan, directory)
        self.assertFalse(any(row[0] == "delete" or row[:2] == ("commit", "active") for row in self.api.events))
        self.assertEqual(len([row for row in self.api.events if row[0] == "upload"]), 1)
        self.assertEqual(self.api.bytes_at(METADATA), b'{"synthetic":"external change"}\n')

    def test_changed_deletion_inventory_after_activation_is_not_deleted(self):
        self.publish()
        old_id = self.api.state()["channels"][PACKAGE]["package_id"]
        plan, directory = self.plan("1.0.1")
        self.api.events.clear()
        self.api.after_active = lambda api: api.add_file(old_id, "unexpected.bin", b"externally added")
        with self.assertRaisesRegex(ValueError, "Deletion inventory changed"):
            self.apply(plan, directory)
        self.assertIn(old_id, self.api.registry)
        self.assertFalse(any(row[0] == "delete" for row in self.api.events))
        self.assertEqual(self.api.state()["channels"][PACKAGE]["version"], "1.0.1")
        self.assertEqual(self.api.bytes_at(METADATA), (directory / "manifest.json").read_bytes())

    def test_active_package_changed_after_activation_prevents_old_deletion(self):
        self.publish()
        old_id = self.api.state()["channels"][PACKAGE]["package_id"]
        plan, directory = self.plan("1.0.1")
        self.api.events.clear()
        def change_active(api):
            row = api.target(PACKAGE, "1.0.1")["payloads"][0]
            row["data"] = b"X" * len(row["data"])
        self.api.after_active = change_active
        with self.assertRaises((ValueError, GitLabAPIError)):
            self.apply(plan, directory)
        self.assertIn(old_id, self.api.registry)
        self.assertFalse(any(row[0] == "delete" for row in self.api.events))

    def test_detail_404_during_pending_deletion_is_not_reported_as_freed(self):
        self.publish()
        old_id = self.api.state()["channels"][PACKAGE]["package_id"]
        plan, directory = self.plan("1.0.1")
        self.api.defer_deletion = True
        reports = []
        with self.assertRaisesRegex(ValueError, "Deletion is not yet complete"):
            self.apply(plan, directory, reports=reports)
        self.assertIsNone(self.api.package(old_id))
        self.assertIn(old_id, [row["id"] for row in self.api.packages(PACKAGE)])
        self.assertEqual(reports[-1]["deleted_ids"], [])
        self.assertEqual(reports[-1]["delete_requested_ids"], [old_id])
        self.assertEqual(reports[-1]["confirmed_deleted_object_bytes"], 0)
        self.assertIsNone(reports[-1]["physical_freed_bytes"])
        self.assertEqual(self.api.state()["operation"]["phase"], "active")
        row = self.api.registry.pop(old_id)  # Synthetic asynchronous server completion.
        self.api.statistics["packages_size"] -= sum(len(item["data"]) for item in row["payloads"])
        self.api.events.clear()
        result = self.apply(plan, directory, reports=reports, execution_id=reports[-1]["execution_id"])
        self.assertEqual(result["already_absent_ids"], [old_id])
        self.assertEqual(result["status"], "complete")
        self.assertFalse(any(row[0] in {"upload", "delete"} for row in self.api.events))

    def test_existing_release_authorization_is_rechecked_before_activation(self):
        self.publish()
        before = {path: self.api.bytes_at(path) for path in (METADATA, CHECKSUMS)}
        spec, directory = self.candidate("1.0.1")
        calls = []
        def synthetic_gate():
            calls.append("checked")
            if len(calls) == 3:
                raise ValueError("Synthetic revoked approval or invalid signature")
        plan = storage.build_plan(self.api, spec, directory, synthetic_gate)
        self.api.events.clear()
        with self.assertRaisesRegex(ValueError, "revoked approval"):
            storage.apply_plan(self.api, plan, directory, storage.identity(plan), synthetic_gate)
        self.assertEqual(len(calls), 3)
        self.assertTrue(any(row[0] == "upload" for row in self.api.events))
        self.assert_no_activation_or_delete(before)

    def test_unknown_old_versions_are_never_automatically_adopted(self):
        self.api.add_package(PACKAGE, "0.9.0", {"old.bin": b"unmanaged old bytes"})
        spec, directory = self.candidate("1.0.0")
        with self.assertRaisesRegex(ValueError, "Unmanaged versions"):
            storage.build_plan(self.api, spec, directory, self.authorize)
        self.assertEqual(self.api.mutations(), [])

    def test_every_prior_metadata_path_is_required_and_owned(self):
        self.publish()
        spec, directory = self.candidate("1.0.1")
        del spec["metadata"][CHECKSUMS]
        self.api.events.clear()
        with self.assertRaisesRegex(ValueError, "every managed metadata"):
            storage.build_plan(self.api, spec, directory, self.authorize)
        self.assertEqual(self.api.mutations(), [])

    def test_completed_plan_replay_is_read_only(self):
        plan, directory, _, _ = self.publish()
        self.api.events.clear()
        self.assertEqual(self.apply(plan, directory)["status"], "complete")
        self.assertEqual(self.api.mutations(), [])

    def test_state_compare_and_swap_conflict_cannot_activate(self):
        plan, directory = self.plan("1.0.0")
        def competing_lease(api, actions):
            foreign = {"schema": storage.STATE_SCHEMA, "project": PROJECT, "channels": {},
                       "operation": {"plan_sha256": "e" * 64, "phase": "uploading"}}
            api.external_commit({storage.STATE_PATH: storage.canonical(foreign)})
        self.api.before_commit = competing_lease
        with self.assertRaises(GitLabAPIError):
            self.apply(plan, directory)
        self.assertEqual(self.api.mutations(), [])
        self.assertIsNone(self.api.bytes_at(METADATA))


if __name__ == "__main__":
    unittest.main()
