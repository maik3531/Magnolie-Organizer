"""Real temporary repositories for the release storage boundary (Refs #698)."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import release_git_guard as guard


POINTER = (b"version https://git-lfs.github.com/spec/v1\n"
           b"oid sha256:" + b"a" * 64 + b"\nsize 987654321\n")


class ReleaseGitGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.name", "Storage Test")
        self.git("config", "user.email", "storage-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        self.write("source.py", "answer = 42\n")
        self.base = self.commit("trusted initial source")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

    def write(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode() if isinstance(content, str) else content)

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def check(self):
        return guard.check_range(self.repo, self.base, "HEAD")

    def test_source_only_commits_pass(self):
        self.write("source.py", "answer = 43\n")
        self.commit("source change")
        self.write("docs/release.md", "Packages go to the registry.\n")
        self.commit("documentation")
        result = self.check()
        self.assertFalse(result.violations)
        self.assertEqual(result.commits_checked, 2)

    def test_unchanged_historical_package_lfs_and_large_blob_pass(self):
        self.write("media/advertising.zip", b"existing marketing archive")
        self.write("old-lfs.bin", POINTER)
        self.write("old-large.bin", b"x" * (guard.MAX_BLOB_BYTES + 1))
        self.base = self.commit("trusted historical artifacts")
        self.write("source.py", "answer = 44\n")
        self.commit("source change only")
        self.assertFalse(self.check().violations)

    def test_package_committed_then_deleted_is_still_rejected(self):
        self.write("release/app.apk", b"synthetic package")
        introducing = self.commit("accidental package")
        (self.repo / "release/app.apk").unlink()
        self.commit("delete package again")
        violations = self.check().violations
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].commit, introducing)
        self.assertEqual(violations[0].path, "release/app.apk")

    def test_archive_and_platform_suffixes_are_case_insensitive(self):
        for index, suffix in enumerate((".oxt", ".AAB", ".deb", ".rpm", ".AppImage",
                                        ".flatpak", ".EXE", ".msi", ".zip", ".tar.zst",
                                        ".tar.custom", ".dmg", ".tgz")):
            self.write(f"release/{index}{suffix}", b"small payload")
        self.commit("package variants")
        self.assertEqual(len(self.check().violations), 13)

    def test_small_repository_metadata_and_checksums_remain_allowed(self):
        self.write("download.flatpakref", "[Flatpak Ref]\nName=org.example.App\n")
        self.write("release.tar.gz.sha256", "a" * 64 + "  release.tar.gz\n")
        self.commit("source metadata")
        self.assertFalse(self.check().violations)

    def test_changed_historical_package_is_rejected(self):
        self.write("media/historical.zip", b"old payload")
        self.base = self.commit("baseline archive")
        self.write("media/historical.zip", b"new payload")
        self.commit("replace archive in Git")
        self.assertEqual(self.check().violations[0].path, "media/historical.zip")

    def test_windows_trailing_dot_cannot_hide_installer(self):
        self.write("setup.exe.", b"small package")
        self.commit("installer with trailing dot")
        self.assertEqual(self.check().violations[0].path, "setup.exe.")

    def test_small_lfs_pointer_under_innocuous_name_is_rejected(self):
        self.write("looks-like-source.txt", POINTER)
        self.commit("LFS pointer")
        self.assertIn("LFS", self.check().violations[0].reason)

    def test_renamed_baseline_lfs_pointer_is_rejected(self):
        self.write("old-pointer.txt", POINTER)
        self.base = self.commit("baseline pointer")
        self.git("mv", "old-pointer.txt", "new-pointer.txt")
        self.commit("move pointer")
        result = self.check()
        self.assertEqual(len(result.violations), 1)
        self.assertEqual(result.violations[0].path, "new-pointer.txt")
        self.assertIn("LFS", result.violations[0].reason)

    def test_rename_of_existing_source_to_package_path_is_rejected(self):
        self.git("mv", "source.py", "source.apk")
        self.commit("mislabelled package")
        self.assertEqual(self.check().violations[0].path, "source.apk")

    def test_large_blob_cannot_hide_under_source_extension(self):
        self.write("large.py", b"x" * (guard.MAX_BLOB_BYTES + 1))
        self.commit("oversized blob")
        self.assertIn("maximum", self.check().violations[0].reason)

    def test_exact_limit_is_allowed_for_source(self):
        self.write("source.dat", b"x" * guard.MAX_BLOB_BYTES)
        self.commit("at limit")
        self.assertFalse(self.check().violations)

    def test_nonancestor_base_is_rejected(self):
        self.git("checkout", "-q", "-b", "side", self.base)
        self.write("side.py", "value = 1\n")
        unrelated = self.commit("side source")
        self.git("checkout", "-q", "main")
        self.write("main.py", "value = 2\n")
        self.commit("main source")
        with self.assertRaisesRegex(guard.GuardError, "not an ancestor"):
            guard.check_range(self.repo, unrelated, "HEAD")

    def test_merge_side_history_with_deleted_package_is_checked(self):
        self.git("checkout", "-q", "-b", "side")
        self.write("hidden.deb", b"temporary package")
        introducing = self.commit("package on side branch")
        (self.repo / "hidden.deb").unlink()
        self.write("side.py", "side = True\n")
        self.commit("side cleanup")
        self.git("checkout", "-q", "main")
        self.write("main.py", "main = True\n")
        self.commit("main source")
        self.git("merge", "--no-ff", "--no-edit", "side")
        result = self.check()
        self.assertTrue(any(v.commit == introducing and v.path == "hidden.deb"
                            for v in result.violations))

    def test_merge_does_not_reject_unchanged_baseline_archive(self):
        self.git("checkout", "-q", "-b", "side")
        self.write("side.py", "side = True\n")
        self.commit("side starts before archive baseline")
        self.git("checkout", "-q", "main")
        self.write("historical.zip", b"existing zip")
        self.base = self.commit("trusted package baseline")
        self.git("merge", "--no-ff", "--no-edit", "side")
        self.assertFalse(self.check().violations)

    def test_merged_unrelated_root_cannot_hide_deleted_package(self):
        self.git("checkout", "-q", "--orphan", "unrelated")
        self.git("rm", "-q", "-rf", ".")
        self.write("root-package.apk", b"temporary root package")
        introducing = self.commit("unrelated root with package")
        (self.repo / "root-package.apk").unlink()
        self.write("unrelated.py", "value = 3\n")
        self.commit("unrelated source replaces package")
        self.git("checkout", "-q", "main")
        self.git("merge", "--allow-unrelated-histories", "--no-ff", "--no-edit", "unrelated")
        self.assertTrue(any(v.commit == introducing for v in self.check().violations))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support required")
    def test_symlink_is_inspected_without_following_worktree_target(self):
        outside = Path(self.temp.name) / "outside"
        outside.write_bytes(b"x" * (guard.MAX_BLOB_BYTES + 1))
        (self.repo / "source-link").symlink_to(outside)
        self.commit("small symlink to external large file")
        self.assertFalse(self.check().violations)
        (self.repo / "download.apk").symlink_to(outside)
        self.commit("package-named symlink")
        self.assertEqual(self.check().violations[0].path, "download.apk")

    def test_control_characters_in_path_cannot_inject_log_lines(self):
        name = "release\n::error::pretend-success.apk"
        self.write(name, b"package")
        self.commit("path with newlines")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = guard.main(["--repo", str(self.repo), "--base", self.base, "--head", "HEAD"])
        self.assertEqual(code, 1)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(json.loads(output.getvalue())["violations"][0]["path"], name)

    def test_ref_option_injection_is_rejected(self):
        with self.assertRaises(guard.GuardError):
            guard.check_range(self.repo, "--all", "HEAD")

    def test_shallow_repository_is_rejected(self):
        self.write("more.py", "x = 1\n")
        self.commit("second source commit")
        clone = Path(self.temp.name) / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth=1", self.repo.as_uri(), str(clone)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with self.assertRaisesRegex(guard.GuardError, "shallow"):
            guard.check_range(clone, "HEAD", "HEAD")

    def test_replace_ref_cannot_hide_package_commit(self):
        self.write("bad.apk", b"package")
        bad = self.commit("package commit")
        clean_tree = self.git("rev-parse", self.base + "^{tree}")
        replacement = self.git("commit-tree", clean_tree, "-p", self.base, "-m", "replacement")
        self.git("replace", bad, replacement)
        self.assertTrue(self.check().violations)


if __name__ == "__main__":
    unittest.main()
