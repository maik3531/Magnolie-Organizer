"""Portable resolver tests; no KDE session or user data is accessed."""
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launcher import FIELDS, closure, package_db, select_backend
import launcher
from profiles import PROFILES, artifacts


def package(name, version="1", **fields):
    result = dict.fromkeys(FIELDS, "")
    result.update(Package=name, Architecture="amd64", Status="install ok installed", Version=version)
    result.update(fields)
    return result


class LauncherTests(unittest.TestCase):
    def test_configured_only_including_hold(self):
        packages = [package("good"), package("held", Status="hold ok installed"),
                    package("unpacked", Status="install ok unpacked"),
                    package("broken", Status="install reinstreq installed")]
        text = "\n".join("\t".join(p[f] for f in FIELDS) for p in packages)
        self.assertEqual([p["Package"] for p in package_db(text)], ["good", "held"])

    def test_provides_uses_provided_not_provider_version(self):
        packages = [package("provider", "999", Provides="virtual (= 2), unversioned")]
        closure("virtual (>= 2), unversioned", packages)
        for dependency in ("virtual (>= 3)", "unversioned (>= 1)"):
            with self.assertRaises(ValueError):
                closure(dependency, packages)

    def test_versions_use_dpkg_epochs_tildes_and_revisions(self):
        closure("native (>> 1:2~rc1-1), native (<= 1:2-2)", [package("native", "1:2-2")])
        with self.assertRaises(ValueError):
            closure("native (>= 1:2)", [package("native", "1:2~rc1")])

    def test_full_transitive_and_pre_depends_closure(self):
        packages = [package("core", Depends="qt"), package("qt", **{"Pre-Depends": "base (>= 2)"}), package("base", "1")]
        with self.assertRaises(ValueError):
            closure("core", packages)
        packages[-1]["Version"] = "2"
        self.assertEqual(set(closure("core", packages)), {"core:amd64", "qt:amd64", "base:amd64"})

    def test_cycles_and_broken_alternatives_do_not_leak(self):
        packages = [package("a", Depends="b, missing"), package("b", Depends="a"), package("good")]
        self.assertEqual(set(closure("a | good", packages)), {"good:amd64"})
        with self.assertRaises(ValueError):
            closure("a | b", packages)
        packages[0]["Depends"] = "b"
        self.assertEqual(len(closure("a", packages)), 2)

    def test_architecture_not_just_package_name(self):
        foreign = package("core", Architecture="i386")
        with self.assertRaises(ValueError):
            closure("core", [foreign])
        foreign["Multi-Arch"] = "foreign"
        closure("core", [foreign])
        with self.assertRaises(ValueError):
            closure("core:native", [foreign])
        foreign["Multi-Arch"] = "allowed"
        closure("core:any", [foreign])

    def test_selector_requires_exact_abi_full_closure_and_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for target, profile in PROFILES.items():
                (root / target).mkdir()
                (root / target / "backend").write_bytes(b"fixture")
                (root / target / "manifest.json").write_text(json.dumps({
                    "schema": "magnolie-kde-backend-v1", "target": target, "abi": profile["abi"],
                    "requirements": "akonadi-server, core (>= 2)", "sha256": hashlib.sha256(b"fixture").hexdigest()}))
            for target, profile in PROFILES.items():
                packages = [package("akonadi-server"), package("core", "2", Provides=profile["abi"], Depends="qt"), package("qt")]
                self.assertEqual(select_backend(root, packages)[1]["target"], target)
                for broken in (packages[1:], packages[:-1], [packages[0], package("core", "2"), packages[2]]):
                    with self.assertRaises(ValueError):
                        select_backend(root, broken)
            packages[1]["Provides"] += ", " + PROFILES["debian13"]["abi"]
            with self.assertRaises(ValueError):
                select_backend(root, packages)
            packages[1]["Provides"] = profile["abi"]
            (root / target / "backend").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                select_backend(root, packages)

    def test_single_artifact_inventory_and_no_transition(self):
        names = artifacts("2.0.18")
        self.assertEqual(sum(n.endswith(".deb") for n in names), 1)
        self.assertFalse(any("akonadi" in n for n in names))
        self.assertEqual(sum(n.endswith(".dsc") for n in names), 1)

    def test_test_candidate_version_order_is_explicit(self):
        # These were distributed test candidates, NOT a released upgrade line.
        for target in PROFILES:
            self.assertEqual(subprocess.call(["dpkg", "--compare-versions", "2.0.18." + target, "gt", "2.0.18"]), 0)
        self.assertEqual(subprocess.call(["dpkg", "--compare-versions", "2.0.18", "gt", "1.0.0"]), 0)

    def test_control_keeps_only_launcher_baseline_unconditional(self):
        control = (Path(__file__).resolve().parents[1] / "debian/control").read_text()
        self.assertEqual(control.count("\nPackage:"), 1)
        depends = next(line for line in control.splitlines() if line.startswith("Depends:"))
        self.assertNotIn("akonadi", depends)
        self.assertNotIn("shlibs", depends)
        self.assertIn("Suggests: akonadi-server, kdepim-runtime", control)
        for relation in ("Provides", "Breaks", "Replaces"):
            self.assertIn(relation + ": magnolie-organizer-akonadi (", control)

    def test_malformed_missing_and_loader_failures_are_protocol_errors(self):
        for error in (FileNotFoundError("missing manifest"), TypeError("bad requirements"),
                      AttributeError("bad manifest shape"), subprocess.TimeoutExpired("self-check", 10)):
            output = io.StringIO()
            with patch.object(launcher.subprocess, "check_output", return_value=""), \
                    patch.object(launcher, "select_backend", side_effect=error), redirect_stdout(output):
                self.assertEqual(launcher.main(), 1)
            reply = json.loads(output.getvalue())
            self.assertIs(reply["ok"], False)
            self.assertTrue(reply["error"])
            self.assertNotIn("items", reply)


if __name__ == "__main__":
    unittest.main()
