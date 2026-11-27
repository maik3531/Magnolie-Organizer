#!/usr/bin/env python3
"""Refs #783: actual Git selection and mixed-tree rejection, without a native build."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


BETA = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("candidate_sources", BETA / "tools/candidate_sources.py")
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class CandidateSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="macOS-candidate-source-")
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic source test")
        self.git("config", "user.email", "source-test@example.invalid")
        for name in source.SOURCE_PATHS:
            file = self.repo / name
            if not file.suffix:
                file /= "source.txt"
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("published source\n")
        (self.repo / "LICENSING.md").write_text("synthetic license\n")
        (self.repo / ".gitignore").write_text("Generated/\nSourceFreeze.json\n")
        self.app = self.repo / "magnolie-organizer/web/anwendung.js"
        self.app.parent.mkdir(parents=True)
        self.app.write_text('const FASSUNG = "2.0.30";\n// Published behavior\n')
        self.published = self.commit("Published synthetic desktop")
        self.app.write_text('const FASSUNG = "2.0.30";\n// Current fixed behavior\n')
        self.current = self.commit("Current source with the same visible version")

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo).decode().strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def test_same_version_proof_binds_current_commit_and_actual_bytes(self):
        proof = source.capture(self.repo, self.current)
        self.assertEqual(proof["desktopCommit"], self.current)
        self.assertEqual(proof["portCommit"], self.current)
        self.assertEqual(proof["sourcePolicy"], "current-checkout")
        self.assertFalse(proof["nativeAcceptance"])
        entry = proof["sourceFiles"]["magnolie-organizer/web/anwendung.js"]
        self.assertEqual(entry["gitBlob"], self.git("rev-parse", "HEAD:magnolie-organizer/web/anwendung.js"))
        self.assertEqual(entry["sha256"], source.hashlib.sha256(self.app.read_bytes()).hexdigest())
        source.verify(self.repo, self.current, json.loads(json.dumps(proof)))

    def test_old_recipe_restore_into_current_checkout_is_rejected(self):
        self.git("restore", "--source=" + self.published, "--", "magnolie-organizer")
        with self.assertRaisesRegex(ValueError, "mixed source build"):
            source.capture(self.repo, self.current)
        self.assertIn("Published behavior", self.app.read_text(), "Checking must not repair or replace inputs")

    def test_actual_old_checkout_and_staged_or_untracked_overlays_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "selected candidate commit"):
            source.capture(self.repo, self.published)
        self.app.write_text("altered source\n")
        self.git("add", "magnolie-organizer/web/anwendung.js")
        with self.assertRaisesRegex(ValueError, "mixed source build"):
            source.capture(self.repo, self.current)
        self.git("restore", "--source=HEAD", "--staged", "--worktree", "--", "magnolie-organizer")
        (self.app.parent / "unreviewed.js").write_text("new input\n")
        with self.assertRaisesRegex(ValueError, "mixed source build"):
            source.capture(self.repo, self.current)

    def test_later_source_or_proof_change_fails_final_verification(self):
        proof = source.capture(self.repo, self.current)
        changed = json.loads(json.dumps(proof))
        changed["sourceFiles"]["magnolie-organizer/web/anwendung.js"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "proof no longer matches"):
            source.verify(self.repo, self.current, changed)
        self.app.write_text("later source edit\n")
        with self.assertRaisesRegex(ValueError, "mixed source build"):
            source.verify(self.repo, self.current, proof)

    def test_hidden_dirty_index_flags_cannot_attest_old_bytes_as_current(self):
        original = self.app.read_bytes()
        relative = "magnolie-organizer/web/anwendung.js"
        for flag in ["assume-unchanged", "skip-worktree"]:
            with self.subTest(flag=flag):
                self.git("update-index", "--" + flag, relative)
                self.app.write_text("hidden older or altered source\n")
                self.assertEqual(self.git("status", "--porcelain", "--", relative), "")
                with self.assertRaisesRegex(ValueError, "committed Git blob"):
                    source.capture(self.repo, self.current)
                self.app.write_bytes(original)
                self.git("update-index", "--no-" + flag, relative)

    def test_ignored_generated_payload_is_separate_from_git_source_proof(self):
        proof = source.capture(self.repo, self.current)
        generated = self.repo / "Magnolie-Organizer-macOS-Beta/Generated"
        generated.mkdir()
        (generated / "anwendung.js").write_text("This is checked by project_ui.verify, not the source proof.\n")
        source.verify(self.repo, self.current, proof)
        self.assertNotIn("Magnolie-Organizer-macOS-Beta/Generated/anwendung.js", proof["sourceFiles"])

    def test_workflow_selects_current_checkouts_and_keeps_codec_reference(self):
        workflow = (BETA.parent / ".github/workflows/ports-2.0.30.yml").read_text()
        mac, tablet = workflow.split("\n  macos:\n", 1)[1].split("\n  tablet:\n", 1)
        self.assertNotIn("git restore", mac)
        self.assertIn('candidate_sources.py record --expected-commit "$GITHUB_SHA"', mac)
        self.assertIn('candidate_sources.py verify --expected-commit "$GITHUB_SHA"', mac)
        self.assertIn("tests/test_candidate_sources.py", mac)
        self.assertLess(mac.index("candidate_sources.py record"), mac.index("project_ui.py freeze"))
        self.assertLess(mac.index("candidate_sources.py verify"), mac.index("ditto -c -k"))
        self.assertNotIn("git restore", tablet)
        self.assertIn("tests/test_source_proof.py", tablet)
        self.assertIn('source-proof.py capture', tablet)
        self.assertIn('--expected-commit "$GITHUB_SHA"', tablet)
        self.assertIn("source-proof.py bind", tablet)
        self.assertLess(tablet.index("source-proof.py capture"), tablet.index("bash tools/build-beta.sh --online"))
        self.assertLess(tablet.index("bash tools/build-beta.sh --online"), tablet.index("source-proof.py bind"))
        self.assertIn('test "$(git rev-parse v2.0.30^{commit})" = "$DESKTOP_COMMIT"', tablet)
        self.assertIn("DESKTOP_COMMIT: " + source.REFERENCE_DESKTOP_COMMIT, workflow)


if __name__ == "__main__":
    unittest.main()
