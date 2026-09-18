import base64
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BETA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BETA / "tools"))
import project_ui as projection
import crypto_vectors
import bridge_coverage


class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = projection.inputs()

    def test_identity_and_no_stable_workflow(self):
        with (BETA / "Resources/Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        self.assertEqual(info["CFBundleName"], "Magnolie Organizer macOS Beta")
        self.assertEqual(info["CFBundleIdentifier"], "io.gitlab.maik3531.MagnolieOrganizer.macOSBeta")
        identity = json.loads((BETA / "Resources/BetaIdentity.json").read_text())
        self.assertEqual(identity["version"], "2.0.18-beta.1")
        self.assertEqual(info["MagnolieBetaVersion"], identity["version"])
        self.assertEqual(info["CFBundleShortVersionString"], identity["bundleShortVersion"])
        self.assertEqual(info["CFBundleVersion"], identity["bundleVersion"])
        self.assertFalse((BETA / ".github/workflows").exists())
        workflow = (BETA / "ci/macos-beta-manual.yml.example").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("upload-artifact", workflow)
        self.assertNotIn("push:", workflow)
        self.assertNotIn("pull_request:", workflow)

    def test_bridge_inventory_distinguishes_partial_and_unavailable(self):
        report = bridge_coverage.report(self.snapshot)
        for command in projection.commands(self.snapshot):
            self.assertIn("| `" + command + "` |", report)
        self.assertIn("LIMITATION RESPONSE ONLY", report)
        self.assertIn("| `sync` | yes | yes | UNSUPPORTED", report)
        self.assertIn("| `kennwort_entfernen` | yes | yes | UNSUPPORTED", report)
        self.assertIn("| `drucken` | yes | yes | UNSUPPORTED", report)

    def test_projection_is_reproducible_and_full_ui(self):
        with tempfile.TemporaryDirectory(prefix="macOS-Beta-host-") as temp:
            a, b = Path(temp) / "a", Path(temp) / "b"
            projection.project(self.snapshot, a)
            projection.project(self.snapshot, b)
            self.assertEqual(projection.tree_hashes(a), projection.tree_hashes(b))
            original = projection.LINUX.relative_to(projection.REPO).as_posix() + "/web/"
            for name, data in self.snapshot.items():
                if name.startswith(original) and not name.endswith(("/index.html", "/anwendung.js")):
                    self.assertEqual((a / "web" / name.removeprefix(original)).read_bytes(), data)
            html = (a / "web/index.html").read_text()
            self.assertIn("Magnolie Organizer macOS Beta", html)
            self.assertIn("connect-src 'none'", html)
            app = (a / "web/anwendung.js").read_text()
            self.assertIn('const SPEICHER_SCHLUESSEL = "magnolie-organizer-macOSBeta-daten";', app)
            self.assertIn('const FASSUNG = "2.0.18-beta.1";', app)
            self.assertFalse(any(file.suffix.lower() in {".pem", ".key", ".pub", ".p12", ".mobileprovision"} for file in a.rglob("*")))
            for src in re.findall(r'<script src="([^"]+)"', html):
                self.assertTrue((a / "web" / src).is_file(), src)
            self.assertTrue((a / "Licenses/GPL-3.0.txt").is_file())
            self.assertEqual((a / "web/kaffee-qr.mga").read_bytes(), self.snapshot[original + "kaffee-qr.mga"])
            self.assertTrue(list((a / "web/schriften").rglob("*.otf")))
            symbols = projection.LINUX.relative_to(projection.REPO).as_posix() + "/symbole/"
            for name, data in self.snapshot.items():
                if name.startswith(symbols):
                    self.assertEqual((a / "symbole" / name.removeprefix(symbols)).read_bytes(), data)
            mobile = json.loads((a / "web/mobile-downloads.json").read_text())
            self.assertEqual(mobile["notes"]["filename"], "Magnolie-Notes.apk")
            self.assertTrue(mobile["notes"]["url"].endswith("/Magnolie-Notes.apk"))
            native = json.loads((a / "native-i18n.json").read_text())
            self.assertEqual(len(native), 19)  # plus English msgid fallback = 20 UI languages
            for locale, messages in native.items():
                for key in ["Create backup", "Restore backup", "Restore", "Cancel", "Edit", "Quit", "Undo", "Redo", "Select all"]:
                    self.assertTrue(messages.get(key), (locale, key))
            self.assertEqual(native["de"]["Restore backup"], "Sicherung wiederherstellen")
            with self.assertRaises(ValueError):
                projection.project(self.snapshot, a)

    def test_anchor_drift_refuses_instead_of_shipping_old_payload(self):
        changed = dict(self.snapshot)
        key = projection.LINUX.relative_to(projection.REPO).as_posix() + "/web/anwendung.js"
        changed[key] = changed[key].replace(b"function normalisiere(roh)", b"function differentNormalizer(roh)")
        with tempfile.TemporaryDirectory(prefix="macOS-Beta-drift-") as temp:
            with self.assertRaisesRegex(ValueError, "anchor changed"):
                projection.project(changed, Path(temp) / "UI")

    def test_freeze_and_generated_tamper_detection(self):
        with tempfile.TemporaryDirectory(prefix="macOS-Beta-freeze-test-") as temp:
            freeze, generated = Path(temp) / "freeze.json", Path(temp) / "UI"
            freeze.write_text(json.dumps({"inputs": projection.inventory(self.snapshot)}))
            projection.project(self.snapshot, generated)
            manifest = {"inputs": projection.inventory(self.snapshot), "outputs": projection.tree_hashes(generated)}
            (generated / "ProjectionManifest.json").write_text(json.dumps(manifest))
            with patch.object(projection, "FREEZE", freeze), patch.object(projection, "GENERATED", generated), \
                    patch.object(projection, "inputs", return_value=self.snapshot):
                projection.verify()
                changed = dict(self.snapshot); changed[next(iter(changed))] += b"tampered"
                with self.assertRaisesRegex(ValueError, "changed since"):
                    projection.frozen(changed)
                payload = generated / "web/anwendung.js"
                payload.write_text(payload.read_text() + "\n// hand-edited output\n")
                with self.assertRaisesRegex(ValueError, "differs"):
                    projection.verify()
                manifest["outputs"] = projection.tree_hashes(generated)
                (generated / "ProjectionManifest.json").write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, "not the reproducible"):
                    projection.verify()

    def test_explicit_freeze_required(self):
        result = subprocess.run([sys.executable, "tools/project_ui.py", "freeze"], cwd=BETA,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm-desktop-frozen required", result.stderr)

    @unittest.skipIf(platform.system() == "Darwin", "Negative Linux-only build gate")
    def test_no_linux_native_build_claim(self):
        result = subprocess.run([sys.executable, "tools/build_dev.py"], cwd=BETA, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Apple macOS host required", result.stderr)

    def javascript(self):
        runtime = os.environ.get("MACOS_BETA_JS_RUNTIME") or shutil.which("node") or shutil.which("deno")
        if not runtime:
            candidate = Path.home() / ".local/bin/deno"
            runtime = str(candidate) if candidate.is_file() else None
        if not runtime:
            self.skipTest("Node/Deno unavailable; UI host test NOT run")
        jsdom = Path(os.environ.get("MACOS_BETA_JSDOM", str(BETA.parent / "Magnolie-Organizer-Windows-2.0.0/node_modules/jsdom/lib/api.js")))
        if not jsdom.is_file():
            self.skipTest("Existing desktop jsdom dependency unavailable; no stable dependency installation performed")
        return runtime

    def test_actual_generated_ui_host_contract(self):
        runtime = self.javascript()
        with tempfile.TemporaryDirectory(prefix="macOS-Beta-ui-host-") as temp:
            target = Path(temp) / "UI"
            projection.project(self.snapshot, target)
            args = [runtime]
            if Path(runtime).name == "deno":
                args += ["run", "--unstable-detect-cjs", "--cached-only", "--allow-read", "--allow-env", "--allow-sys"]
            result = subprocess.run(args + ["tests/ui_host.mjs", str(target)], cwd=BETA,
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

    def test_current_editor_reminders_and_export(self):
        runtime = self.javascript()
        swift = os.environ.get("MACOS_BETA_SWIFT") or shutil.which("swift")
        for zone in ["UTC", "Pacific/Honolulu", "Europe/Berlin"]:
            with self.subTest(host_zone=zone):
                args = [sys.executable, "tools/check_editor.py", "--js-runtime", runtime]
                if swift and zone != "Pacific/Honolulu":
                    args += ["--swift", swift]
                result = subprocess.run(args, cwd=BETA, env=dict(os.environ, TZ=zone),
                                        capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout.strip())
        if not swift:
            print("Swift core execution NOT run in this host collection; use MACOS_BETA_SWIFT or tools/check_editor.py --swift.")

    def test_recovery_regional_keyboard_contract(self):
        runtime = self.javascript()
        with tempfile.TemporaryDirectory(prefix="macOS-Beta-recovery-host-") as temp:
            target = Path(temp) / "UI"
            projection.project(self.snapshot, target)
            args = [runtime]
            if Path(runtime).name == "deno":
                args += ["run", "--unstable-detect-cjs", "--cached-only", "--allow-read", "--allow-env", "--allow-sys"]
            result = subprocess.run(args + ["tests/recovery_regressions.mjs", str(target)], cwd=BETA,
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())


class CryptoContractTests(unittest.TestCase):
    def test_vectors_match_canonical_linux_codec(self):
        self.assertEqual(json.loads(crypto_vectors.OUTPUT.read_text()), crypto_vectors.vectors())

    def test_canonical_decrypts_whole_json_and_rejects_tampering(self):
        values = crypto_vectors.vectors()
        native = crypto_vectors.canonical()
        self.assertEqual(native["daten_entschluesseln"](values["v2"], values["password"]), values["plain"])
        with self.assertRaises(Exception):
            native["daten_entschluesseln"](values["v2"], "wrong password")
        damaged = json.loads(values["v2"])
        data = bytearray(base64.b64decode(damaged["daten"]))
        data[-1] ^= 1
        damaged["daten"] = base64.b64encode(data).decode()
        with self.assertRaises(Exception):
            native["daten_entschluesseln"](json.dumps(damaged), values["password"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
