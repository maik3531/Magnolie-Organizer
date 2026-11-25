"""Portable dependency-closure tests. These do not execute or emulate macOS."""
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import airplay_bundle as bundle


SYSTEM = "/usr/lib/libSystem.B.dylib"


def image(path, dependencies=(), rpaths=(), install_id=None, minimum="12.7"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xcf\xfa\xed\xfe" + json.dumps({
        "dependencies": dependencies, "rpaths": rpaths, "install_id": install_id,
        "minimum": minimum,
    }).encode())
    return path


class FileImageTools:
    """Manipulate synthetic load-command fixtures, never pretend to run Mach-O."""
    def __init__(self):
        self.signed = []
        self.verified = []

    def inspect(self, path):
        data = json.loads(path.read_bytes()[4:])
        if bundle.version_tuple(data["minimum"]) > bundle.version_tuple("12.7"):
            raise ValueError("newer macOS")
        return bundle.MachO(tuple(data["dependencies"]), tuple(data["rpaths"]), data["install_id"], data["minimum"], "macos")

    def replace(self, path, **values):
        data = json.loads(path.read_bytes()[4:])
        data.update(values)
        image(path, **data)

    def change(self, path, old, new):
        self.replace(path, dependencies=[new if value == old else value for value in self.inspect(path).dependencies])

    def set_id(self, path, value):
        self.replace(path, install_id=value)

    def delete_rpath(self, path, value):
        self.replace(path, rpaths=[item for item in self.inspect(path).rpaths if item != value])

    def sign(self, path):
        self.signed.append(path)

    def verify(self, path):
        self.verified.append(path)


class BundleCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sdk = self.root / "sdk"
        self.sdk.mkdir()
        self.framework = self.sdk / "GStreamer.framework"
        version = self.framework / "Versions/1.0"
        version.mkdir(parents=True)
        (self.framework / "Versions/Current").symlink_to("1.0", target_is_directory=True)
        for relative in ("lib/gstreamer-1.0", "lib/gio/modules", "lib/pkgconfig", "libexec/gstreamer-1.0"):
            (version / relative).mkdir(parents=True, exist_ok=True)
        for name in ("openssl", "libplist"):
            (self.sdk / name / "lib/pkgconfig").mkdir(parents=True)
        self.components = []
        for name, root, version in (("gstreamer", "GStreamer.framework", "1.28.9"),
                                    ("openssl", "openssl", "3.6.0"), ("libplist", "libplist", "2.7.0")):
            files = {}
            for field, suffix in (("licenseFiles", "LICENSE.txt"), ("sourceArchives", "source.tar")):
                path = self.sdk / (name + "-" + suffix)
                if suffix.endswith(".tar"):
                    with tarfile.open(path, "w"):
                        pass
                else:
                    path.write_text("Synthetic test license")
                files[field] = [{"path": path.name, "sha256": bundle.sha256(path)}]
            self.components.append(dict(name=name, root=root, version=version, license="test-fixture", **files))
        self.manifest = {"schemaVersion": 1, "components": self.components,
                         "loadPrefixMappings": {"/opt/homebrew/opt/openssl@3": "openssl"}}
        self.save_manifest()
        self.contents = self.root / "Magnolie.app/Contents"
        self.helper = image(self.root / "build/magnolie-airplay-receiver", [SYSTEM])
        self.apple = FileImageTools()

    def save_manifest(self):
        (self.sdk / "sdk.json").write_text(json.dumps(self.manifest))

    def test_transitive_plugin_dependencies_are_relocated_and_all_are_signed(self):
        crypto = image(self.sdk / "openssl/lib/libcrypto.3.dylib", [SYSTEM], install_id="/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib")
        plist = image(self.sdk / "libplist/lib/libplist-2.0.4.dylib", [str(crypto), SYSTEM])
        plugin = image(self.framework / "Versions/1.0/lib/gstreamer-1.0/libgstaudio.dylib", [str(plist), SYSTEM])
        image(self.framework / "Versions/1.0/libexec/gstreamer-1.0/gst-plugin-scanner", [str(crypto), SYSTEM])
        image(self.helper, [str(plist), SYSTEM], ["/opt/homebrew/lib"])
        sdk = bundle.SDK(self.sdk)
        binaries = bundle.copy_closure(sdk, self.helper, self.contents, self.apple)
        self.assertEqual(len(binaries), 5)
        packaged_plugin = self.contents / bundle.FRAMEWORK / plugin.relative_to(self.framework)
        self.assertTrue(all(name.startswith("@loader_path/") or name == SYSTEM for name in self.apple.inspect(packaged_plugin).dependencies))
        self.assertEqual(self.apple.inspect(self.contents / bundle.HELPER).rpaths, ())
        self.assertEqual(set(self.apple.signed), set(binaries + [self.contents / bundle.FRAMEWORK]))
        self.assertEqual(self.apple.signed[-1], self.contents / bundle.FRAMEWORK)
        self.assertIn(self.contents / bundle.FRAMEWORK, self.apple.verified)
        self.assertEqual(self.apple.inspect(crypto).install_id, "/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib")
        sdk.unchanged()  # no input SDK mutation

    def test_dependency_cycles_close_once(self):
        first = self.sdk / "openssl/lib/libfirst.dylib"
        second = self.sdk / "libplist/lib/libsecond.dylib"
        image(first, [str(second), SYSTEM]); image(second, [str(first), SYSTEM])
        image(self.helper, [str(first), SYSTEM])
        binaries = bundle.copy_closure(bundle.SDK(self.sdk), self.helper, self.contents, self.apple)
        self.assertEqual(len(binaries), 3)
        self.assertEqual(len(set(self.apple.signed)), 4)

    def test_absolute_homebrew_reference_requires_explicit_sdk_mapping(self):
        image(self.sdk / "openssl/lib/libcrypto.3.dylib", [SYSTEM])
        image(self.helper, ["/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib"])
        self.assertEqual(len(bundle.copy_closure(bundle.SDK(self.sdk), self.helper, self.contents, self.apple)), 2)

    def test_host_library_even_when_present_is_not_copied(self):
        outside = image(self.root / "host/libsecret.dylib", [SYSTEM])
        image(self.helper, [str(outside)])
        with self.assertRaisesRegex(ValueError, "Unresolved"):
            bundle.copy_closure(bundle.SDK(self.sdk), self.helper, self.contents, self.apple)
        self.assertEqual(self.apple.signed, [])

    def test_framework_absolute_install_prefix_is_relocated(self):
        image(self.framework / "Versions/1.0/lib/libglib-2.0.0.dylib", [SYSTEM])
        image(self.helper, ["/Library/Frameworks/GStreamer.framework/Versions/1.0/lib/libglib-2.0.0.dylib"])
        binaries = bundle.copy_closure(bundle.SDK(self.sdk), self.helper, self.contents, self.apple)
        self.assertEqual(len(binaries), 2)

    def test_framework_rpath_resolves_inside_supplied_sdk(self):
        image(self.framework / "Versions/1.0/GStreamer", [SYSTEM])
        image(self.helper, ["@rpath/GStreamer.framework/Versions/1.0/GStreamer"])
        binaries = bundle.copy_closure(bundle.SDK(self.sdk), self.helper, self.contents, self.apple)
        self.assertEqual(len(binaries), 2)

    def test_ambiguous_rpath_does_not_choose_first_library(self):
        for root in ("openssl", "libplist"):
            image(self.sdk / root / "lib/libsamenamed.dylib", [SYSTEM])
        image(self.helper, ["@rpath/libsamenamed.dylib"])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            bundle.copy_closure(bundle.SDK(self.sdk), self.helper, self.contents, self.apple)

    def test_loader_relative_dependency_is_closed(self):
        lib = image(self.sdk / "openssl/lib/libcrypto.3.dylib", [SYSTEM])
        image(self.sdk / "openssl/lib/libssl.3.dylib", ["@loader_path/" + lib.name])
        image(self.helper, [str(self.sdk / "openssl/lib/libssl.3.dylib")])
        self.assertEqual(len(bundle.copy_closure(bundle.SDK(self.sdk), self.helper, self.contents, self.apple)), 3)

    def test_link_to_host_or_missing_target_is_rejected_before_copy(self):
        outside = self.root / "secret"
        outside.write_text("private")
        link = self.sdk / "openssl/lib/bad.dylib"
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            bundle.SDK(self.sdk)
        link.unlink(); link.symlink_to("missing")
        with self.assertRaisesRegex(ValueError, "symlink"):
            bundle.SDK(self.sdk)
        self.assertFalse(self.contents.exists())

    def test_absolute_internal_framework_link_becomes_relative_in_bundle(self):
        current = self.framework / "Versions/Current"
        original = str(self.framework / "Versions/1.0")
        current.unlink(); current.symlink_to(original, target_is_directory=True)
        image(self.framework / "Versions/1.0/lib/libgst.dylib", [SYSTEM])
        sdk = bundle.SDK(self.sdk)
        bundle.copy_closure(sdk, self.helper, self.contents, self.apple)
        packaged = self.contents / bundle.FRAMEWORK
        self.assertEqual(bundle.os.readlink(packaged / "Versions/Current"), "1.0")
        self.assertEqual(bundle.os.readlink(current), original)
        bundle.checked_tree(packaged)
        sdk.unchanged()

    def test_newer_minimum_os_blocks_signing(self):
        library = image(self.sdk / "libplist/lib/libnew.dylib", [SYSTEM], minimum="13.0")
        image(self.helper, [str(library)])
        with self.assertRaisesRegex(ValueError, "newer macOS"):
            bundle.copy_closure(bundle.SDK(self.sdk), self.helper, self.contents, self.apple)
        self.assertEqual(self.apple.signed, [])

    def test_existing_helper_is_preserved(self):
        existing = self.contents / bundle.HELPER
        existing.parent.mkdir(parents=True)
        existing.write_text("original")
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            bundle.copy_closure(bundle.SDK(self.sdk), self.helper, self.contents, self.apple)
        self.assertEqual(existing.read_text(), "original")

    def test_missing_or_changed_license_and_source_cannot_package(self):
        self.components[0]["sourceArchives"] = []
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "sourceArchives"):
            bundle.SDK(self.sdk)
        self.components[0]["sourceArchives"] = self.components[1]["sourceArchives"]
        self.save_manifest()
        license_file = self.sdk / self.components[0]["licenseFiles"][0]["path"]
        license_file.write_text("changed")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            bundle.SDK(self.sdk)

    def test_changed_sdk_after_build_invalidates_manifest(self):
        library = image(self.sdk / "libplist/lib/libplist.dylib", [SYSTEM])
        sdk = bundle.SDK(self.sdk)
        library.write_bytes(library.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "changed during"):
            sdk.unchanged()

    def test_changed_framework_symlink_invalidates_input_identity(self):
        sdk = bundle.SDK(self.sdk)
        current = self.framework / "Versions/Current"
        current.unlink(); current.symlink_to("./1.0")
        with self.assertRaisesRegex(ValueError, "changed during"):
            sdk.unchanged()

    def test_malformed_manifest_paths_and_overlap_rejected(self):
        for path in ("../outside", "/tmp/outside", "GStreamer.framework/../openssl"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                bundle.safe_relative(self.sdk, path, directory=True)
        self.components.append(dict(self.components[1], name="overlap", root="openssl/lib"))
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            bundle.SDK(self.sdk)

    def test_runtime_audit_rejects_missing_target_and_external_runpath(self):
        self.contents.mkdir(parents=True)
        binary = image(self.contents / "Helpers/bad", ["@loader_path/../../outside.dylib"])
        with self.assertRaisesRegex(ValueError, "escaping"):
            bundle.audit_closed_bundle(self.contents, [binary], self.apple)
        image(binary, [SYSTEM], ["/usr/local/lib"])
        with self.assertRaisesRegex(ValueError, "runpath"):
            bundle.audit_closed_bundle(self.contents, [binary], self.apple)

    def test_build_environment_cannot_inherit_foreign_dependency_paths(self):
        with patch.dict(bundle.os.environ, {"PKG_CONFIG_PATH": "/private/pc", "GST_PLUGIN_PATH": "/private/plugins", "DYLD_LIBRARY_PATH": "/private/lib", "CPATH": "/private/include"}):
            environment = bundle.sdk_environment(bundle.SDK(self.sdk), "12.7")
        self.assertEqual(environment["PKG_CONFIG_PATH"], "")
        self.assertNotIn("DYLD_LIBRARY_PATH", environment)
        self.assertNotIn("GST_PLUGIN_PATH", environment)
        self.assertNotIn("CPATH", environment)
        self.assertTrue(all(path.startswith(str(self.sdk)) for path in environment["PKG_CONFIG_LIBDIR"].split(bundle.os.pathsep)))

    def test_exact_integrated_source_archive_is_reproducible(self):
        source = self.root / "Receiver"
        source.mkdir()
        (source / "main.cpp").write_text("integration source\n")
        (source / "LICENSE").write_text("license\n")
        (source / "tests/__pycache__").mkdir(parents=True)
        (source / "tests/__pycache__/test.cpython.pyc").write_bytes(b"local cache")
        (source / "build").mkdir()
        (source / "build/receiver").write_bytes(b"local compiled binary")
        first, second = self.root / "first.gz", self.root / "second.gz"
        bundle.source_archive(source, first); bundle.source_archive(source, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with tarfile.open(first) as archive:
            self.assertEqual(archive.extractfile("Magnolie-AirPlay-Receiver/main.cpp").read(), b"integration source\n")
            self.assertEqual(archive.getnames(), ["Magnolie-AirPlay-Receiver/LICENSE", "Magnolie-AirPlay-Receiver/main.cpp"])

    def test_pkgconfig_stage_relocates_only_private_copies(self):
        pc = self.framework / "Versions/1.0/lib/pkgconfig/gstreamer-1.0.pc"
        original = "prefix=/Library/Frameworks/GStreamer.framework/Versions/1.0\nlibdir=${pcfiledir}/../\n"
        pc.write_text(original)
        sdk = bundle.SDK(self.sdk)
        target = self.root / "private-pc"
        environment = bundle.prepare_pkgconfig(sdk, bundle.sdk_environment(sdk, "12.7"), target)
        self.assertEqual(environment["PKG_CONFIG_LIBDIR"], str(target))
        self.assertIn(str(self.framework), (target / pc.name).read_text())
        self.assertNotIn("${pcfiledir}", (target / pc.name).read_text())
        self.assertEqual(pc.read_text(), original)
        sdk.unchanged()

    def test_pkgconfig_path_audit_rejects_foreign_headers(self):
        sdk = bundle.SDK(self.sdk)
        with patch.object(bundle.subprocess, "check_output", return_value="-I/usr/local/include -L/usr/local/lib -lcrypto"):
            with self.assertRaisesRegex(ValueError, "outside"):
                bundle.check_pkgconfig_paths(sdk, {})
        with patch.object(bundle.subprocess, "check_output", return_value="-I" + str(self.sdk / "openssl/include") + " -L" + str(self.sdk / "openssl/lib") + " -lcrypto"):
            bundle.check_pkgconfig_paths(sdk, {})


class NativeToolContractTests(unittest.TestCase):
    def test_all_dynamic_load_kinds_and_old_target_are_checked(self):
        commands = "header\n"
        kinds = [("LC_ID_DYLIB", "@rpath/own.dylib"), ("LC_LOAD_DYLIB", SYSTEM),
                 ("LC_LOAD_WEAK_DYLIB", "/usr/local/lib/optional.dylib"),
                 ("LC_REEXPORT_DYLIB", "@rpath/export.dylib")]
        for number, (kind, name) in enumerate(kinds):
            commands += f"Load command {number}\n cmd {kind}\n cmdsize 64\n name {name} (offset 24)\n"
        commands += "Load command 4\n cmd LC_RPATH\n path /opt/build/lib (offset 12)\n"
        commands += "Load command 5\n cmd LC_VERSION_MIN_MACOSX\n version 10.15\n sdk 15.0\n"
        parsed = bundle.parse_load_commands(commands)
        self.assertEqual(parsed.install_id, "@rpath/own.dylib")
        self.assertEqual(parsed.dependencies, tuple(value for _, value in kinds[1:]))
        self.assertEqual(parsed.rpaths, ("/opt/build/lib",))
        self.assertEqual(parsed.minimum, "10.15")

    def test_wrong_architecture_and_missing_or_high_minimum_are_rejected(self):
        apple = bundle.AppleTools("x86_64", "12.7")
        with patch.object(apple, "run", return_value="arm64"), self.assertRaisesRegex(ValueError, "lacks x86_64"):
            apple.inspect(Path("synthetic"))
        for metadata in ("header", "Load command 0\n cmd LC_BUILD_VERSION\n platform 1\n minos 13.0\n"):
            with patch.object(apple, "run", side_effect=["arm64 x86_64", metadata]), self.assertRaises(ValueError):
                apple.inspect(Path("synthetic"))

    def test_arm64_ios_library_is_not_a_macos_dependency(self):
        apple = bundle.AppleTools("arm64", "12.7")
        metadata = "Load command 0\n cmd LC_BUILD_VERSION\n platform 2\n minos 12.0\n"
        with patch.object(apple, "run", side_effect=["arm64", metadata]), self.assertRaisesRegex(ValueError, "not built for macOS"):
            apple.inspect(Path("synthetic"))

    def test_only_apple_system_paths_are_exempt_from_closure(self):
        self.assertTrue(bundle.system_library(SYSTEM))
        self.assertTrue(bundle.system_library("/System/Library/Frameworks/AppKit.framework/Versions/C/AppKit"))
        for path in ("/usr/local/lib/foo.dylib", "/usr/lib/../../private/foo", "@rpath/libSystem.B.dylib", "/Library/Frameworks/GStreamer.framework/GStreamer"):
            self.assertFalse(bundle.system_library(path), path)


if __name__ == "__main__":
    unittest.main()
