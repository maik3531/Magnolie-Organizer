#!/usr/bin/env python3
"""Real-Git regression tests for the tablet checkout/projection boundary (#790)."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tablet_source_proof", ROOT / "tools/source-proof.py")
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


class SourceProofTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tablet-source-proof-test-")
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.git("init", "-q")
        fixtures = {name: ("fixture " + name + "\n") for name in proof.REQUIRED}
        fixtures.update({
            ".gitignore": proof.TABLET + "/app/build/\n" + proof.TABLET + "/artifacts/\n"
                          + "magnolie-organizer/web/i18n/\n**/ignored.kt\n",
            "magnolie-organizer/po/LINGUAS": "de\n",
            "magnolie-organizer/po/de.po": "committed catalog input\n",
            "magnolie-organizer/werkzeuge/po_zu_js.py":
                "import pathlib,sys\npathlib.Path(sys.argv[3]).write_text("
                "sys.argv[1]+':'+pathlib.Path(sys.argv[2]).read_text())\n",
        })
        for name, text in fixtures.items():
            self.write(name, text)
        self.commit()
        self.old = self.git("rev-parse", "HEAD").strip()
        self.write("magnolie-organizer/web/anwendung.js", "current desktop, not the old release\n")
        self.commit()
        self.head = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), "-c", "user.name=Tablet source test",
             "-c", "user.email=tablet-source-test@example.invalid", *args],
            stderr=subprocess.PIPE, text=True)

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "isolated provenance fixture")

    def projection(self, *, catalog=False):
        inputs = {}
        for name in proof.REQUIRED:
            inputs[name] = proof.digest((self.repo / name).read_bytes())
        if catalog:
            name = "magnolie-organizer/web/i18n/de.js"
            generated = self.write(name, "de:committed catalog input\n")
            inputs[name] = proof.digest(generated.read_bytes())
        output_name = "assets/web/app.js"
        projection_root = self.repo / proof.TABLET / "app/build/generated/projection"
        output = projection_root / output_name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"generated projection output")
        value = dict(sourceHash=proof.digest(proof.encoded(inputs)), inputs=inputs,
                     outputs={output_name: proof.digest(output.read_bytes())})
        manifest = projection_root / "assets/projection.json"
        manifest.write_text(json.dumps(value))
        return manifest

    def candidate(self, manifest):
        source = proof.read_json(manifest)
        directory = self.repo / proof.TABLET / "artifacts"
        directory.mkdir(exist_ok=True)
        # Synthetic bytes exercise provenance binding; the real APK verifier
        # remains a separate mandatory stage in the product build.
        app = directory / "app.apk"
        test = directory / "test.apk"
        app.write_bytes(b"synthetic app verifier fixture")
        test.write_bytes(b"synthetic instrumentation verifier fixture")
        value = dict(name=app.name, sha256=proof.digest(app.read_bytes()),
                     testApk=test.name, testApkSha256=proof.digest(test.read_bytes()),
                     sourceHash=source["sourceHash"], stale=False,
                     apkAssetsVerified=True, instrumentationTestOnly=True)
        candidate = directory / "candidate.json"
        candidate.write_text(json.dumps(value))
        return candidate

    def test_clean_current_checkout_and_projection_bind(self):
        before = proof.snapshot(self.repo, self.head)
        manifest = self.projection()
        result = proof.bind(self.repo, before, manifest, self.candidate(manifest))
        self.assertEqual(result["portCommit"], self.head)
        self.assertEqual(result["desktopCommit"], self.head)
        self.assertFalse(result["nativeAcceptance"])
        self.assertFalse(result["productionRelease"])
        self.assertEqual(result["projectionSourceHash"], proof.read_json(manifest)["sourceHash"])

    def test_committed_tablet_additions_bind_without_historical_git_objects(self):
        additions = ("web/system-import.js", "web/system-import-i18n.json",
                     "tests/system-import.test.cjs")
        for name in additions:
            self.write(proof.TABLET + "/" + name, "new committed tablet input\n")
        self.commit()
        with tempfile.TemporaryDirectory(prefix="tablet-source-shallow-test-") as temporary:
            clone = Path(temporary) / "checkout"
            subprocess.check_call(["git", "clone", "--quiet", "--no-tags", "--depth=1",
                                   self.repo.as_uri(), str(clone)])
            self.repo = clone
            self.head = self.git("rev-parse", "HEAD").strip()
            self.assertEqual(self.git("rev-parse", "--is-shallow-repository").strip(), "true")
            with self.assertRaises(subprocess.CalledProcessError):
                self.git("cat-file", "-e", self.old)
            before = proof.snapshot(self.repo, self.head)
            manifest = self.projection(catalog=True)
            value = proof.read_json(manifest)
            for name in additions:
                source = proof.TABLET + "/" + name
                value["inputs"][source] = proof.digest((self.repo / source).read_bytes())
                self.assertIn(source, before["inputs"])
            value["sourceHash"] = proof.digest(proof.encoded(value["inputs"]))
            manifest.write_text(json.dumps(value))
            result = proof.bind(self.repo, before, manifest)
            self.assertEqual(result["projectionSourceHash"], value["sourceHash"])

    def test_clean_old_expected_commit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected current commit"):
            proof.snapshot(self.repo, self.old)

    def test_restoring_published_desktop_bytes_is_rejected(self):
        self.git("restore", "--source=" + self.old, "--", "magnolie-organizer/web/anwendung.js")
        with self.assertRaisesRegex(ValueError, "differ from the checkout"):
            proof.snapshot(self.repo, self.head)

    def test_staged_source_edit_is_rejected(self):
        self.write("magnolie-organizer/web/anwendung.js", "uncommitted source")
        self.git("add", "magnolie-organizer/web/anwendung.js")
        with self.assertRaisesRegex(ValueError, "differ from the checkout"):
            proof.snapshot(self.repo, self.head)

    def test_untracked_native_source_is_rejected(self):
        self.write(proof.TABLET + "/app/src/main/java/Unexpected.kt", "class Unexpected")
        with self.assertRaisesRegex(ValueError, "Uncommitted"):
            proof.snapshot(self.repo, self.head)

    def test_a_new_commit_invalidates_an_earlier_capture(self):
        before = proof.snapshot(self.repo, self.head)
        manifest = self.projection()
        self.write("magnolie-organizer/web/anwendung.js", "new commit")
        self.commit()
        with self.assertRaisesRegex(ValueError, "expected current commit"):
            proof.bind(self.repo, before, manifest)

    def test_projection_from_older_input_is_rejected(self):
        before = proof.snapshot(self.repo, self.head)
        manifest = self.projection()
        value = proof.read_json(manifest)
        value["inputs"]["magnolie-organizer/web/anwendung.js"] = proof.digest(b"old source")
        value["sourceHash"] = proof.digest(proof.encoded(value["inputs"]))
        manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "changed source bytes"):
            proof.bind(self.repo, before, manifest)

    def test_edited_projection_output_is_rejected(self):
        before = proof.snapshot(self.repo, self.head)
        manifest = self.projection()
        (manifest.parent / "web/app.js").write_bytes(b"different output")
        with self.assertRaisesRegex(ValueError, "projection changed"):
            proof.bind(self.repo, before, manifest)

    def test_ignored_source_cannot_be_smuggled_through_projection(self):
        before = proof.snapshot(self.repo, self.head)
        manifest = self.projection()
        name = proof.TABLET + "/app/src/main/java/ignored.kt"
        self.write(name, "class IgnoredSource")
        value = proof.read_json(manifest)
        value["inputs"][name] = proof.digest((self.repo / name).read_bytes())
        value["sourceHash"] = proof.digest(proof.encoded(value["inputs"]))
        manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "not a generated catalog"):
            proof.bind(self.repo, before, manifest)

    def test_generated_catalog_is_reproduced_from_committed_input(self):
        before = proof.snapshot(self.repo, self.head)
        manifest = self.projection(catalog=True)
        self.assertTrue(proof.bind(self.repo, before, manifest)["generatedCatalogsVerified"])

    def test_forged_generated_catalog_is_rejected(self):
        before = proof.snapshot(self.repo, self.head)
        manifest = self.projection(catalog=True)
        name = "magnolie-organizer/web/i18n/de.js"
        self.write(name, "catalog from an older source")
        value = proof.read_json(manifest)
        value["inputs"][name] = proof.digest((self.repo / name).read_bytes())
        value["sourceHash"] = proof.digest(proof.encoded(value["inputs"]))
        manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "not from the current PO"):
            proof.bind(self.repo, before, manifest)

    def test_symlink_output_is_rejected(self):
        before = proof.snapshot(self.repo, self.head)
        manifest = self.projection()
        output = manifest.parent / "web/app.js"
        other = output.with_name("other.js")
        output.rename(other)
        output.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            proof.bind(self.repo, before, manifest)

    def test_stale_candidate_is_rejected(self):
        before = proof.snapshot(self.repo, self.head)
        manifest = self.projection()
        candidate = self.candidate(manifest)
        value = proof.read_json(candidate)
        value["sourceHash"] = "0" * 64
        candidate.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "current projection"):
            proof.bind(self.repo, before, manifest, candidate)

    def test_changed_apk_bytes_are_rejected(self):
        before = proof.snapshot(self.repo, self.head)
        manifest = self.projection()
        candidate = self.candidate(manifest)
        (candidate.parent / "app.apk").write_bytes(b"replaced candidate bytes")
        with self.assertRaisesRegex(ValueError, "Candidate bytes changed"):
            proof.bind(self.repo, before, manifest, candidate)

    def test_duplicate_json_keys_are_rejected(self):
        path = self.write(proof.TABLET + "/artifacts/duplicate.json", '{"sourceHash":"old","sourceHash":"new"}')
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            proof.read_json(path)


class BuildWiringTests(unittest.TestCase):
    def test_tablet_uses_current_checkout_but_keeps_historical_oracle(self):
        workflow = (ROOT.parent / ".github/workflows/ports-2.0.30.yml").read_text()
        _, tablet = workflow.split("\n  tablet:", 1)
        self.assertNotIn("git restore", tablet)
        self.assertIn("source-proof.py capture", tablet)
        self.assertIn('--expected-commit "$GITHUB_SHA"', tablet)
        self.assertIn("source-proof.py bind", tablet)
        self.assertIn("referenceDesktopCommit", tablet)
        self.assertIn("po_zu_js.py", tablet)
        self.assertIn("RuntimeMaxSec=890", (ROOT / "tools/build-beta.sh").read_text())
        self.assertIn("MemoryMax=6G", tablet)

    def test_shared_wrapper_toolchain_uses_current_repository_plugin_versions(self):
        catalog = (ROOT.parent / "magnolie-notes/gradle/libs.versions.toml").read_text()
        versions = {name: re.search(r'^' + name + r' = "([^"]+)"$', catalog, re.M).group(1)
                    for name in ("agp", "kotlin")}
        build = (ROOT / "build.gradle.kts").read_text()
        self.assertIn('version "' + versions["agp"] + '"', build)
        self.assertIn('kotlin-gradle-plugin:' + versions["kotlin"], build)
        self.assertNotIn('id("org.jetbrains.kotlin.android")', build)
        gate = (ROOT / "tools/offline-checks.py").read_text()
        self.assertIn("magnolie-notes/gradlew", gate)

    def test_sdk_preparation_keeps_minimum_and_behavior_target(self):
        app = (ROOT / "app/build.gradle.kts").read_text()
        self.assertIn("minSdk = 26", app)
        self.assertIn("targetSdk = 35", app)
        self.assertIn("release(37) { minorApiLevel = 2 }", app)
        self.assertIn('jvmToolchain(21)', app)
        self.assertIn("JvmTarget.JVM_17", app)
        self.assertNotIn('id("org.jetbrains.kotlin.android")', app)
        self.assertNotIn("kotlinOptions", app)
        self.assertIn("prepareSharedStorageSources", app)
        for name in ("DatenDateiKrypto.kt", "DateiDauerhaft.kt"):
            self.assertIn(name, app)
        self.assertNotIn('srcDir(rootProject.file("../magnolie-notes/app/src/main/java"))', app)


if __name__ == "__main__":
    unittest.main()
