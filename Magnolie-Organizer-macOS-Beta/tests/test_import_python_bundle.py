"""Host checks for #785/#802 build boundaries; never a native-Mac pass claim."""
import io
import hashlib
import json
from pathlib import Path
import plistlib
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import import_python_bundle as runtime
import build_dev


class ImportPythonBundleTests(unittest.TestCase):
    @staticmethod
    def macho(filetype):
        # Minimal little-endian arm64 mach_header_64, not executable test code.
        return struct.pack("<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, filetype, 0, 0, 0, 0)

    def helper_bundle(self, root, *, signed=True):
        bundle = root / "ImportPython.app"
        contents = bundle / "Contents"
        for name in ("MacOS", "PlugIns", "Resources/lib/python3.15/encodings"):
            (contents / name).mkdir(parents=True)
        info = {"CFBundleIdentifier": "io.gitlab.maik3531.MagnolieOrganizer.ImportPython",
                "CFBundleName": "ImportPython", "CFBundleExecutable": "python3.15",
                "CFBundlePackageType": "APPL", "CFBundleInfoDictionaryVersion": "6.0",
                "CFBundleShortVersionString": "3.15.2", "CFBundleVersion": "3.15.2",
                "LSMinimumSystemVersion": "12.7", "LSBackgroundOnly": True}
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        (contents / "MacOS/python3.15").write_bytes(self.macho(2) + b"interpreter fixture")
        (contents / "MacOS/python3.15").chmod(0o755)
        (contents / "PlugIns/_lzma.cpython-315-darwin.so").write_bytes(self.macho(8) + b"extension fixture")
        (contents / "Resources/lib/python3.15/os.py").write_bytes(b"# stdlib fixture\n")
        (contents / "Resources/lib/python3.15/encodings/__init__.py").write_bytes(b"# encoding fixture\n")
        for name in ("LICENSE-Python.txt", "LICENSE-XZ-Utils.txt", "LICENSE-liblzma-0BSD.txt"):
            (contents / "Resources" / name).write_bytes(b"license fixture\n")
        if signed:
            seal = contents / "_CodeSignature/CodeResources"
            seal.parent.mkdir()
            seal.write_bytes(plistlib.dumps({"fixture": "not a real code signature"}))
        return bundle

    @staticmethod
    def inventory(bundle):
        return {str(path.relative_to(bundle)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(bundle.rglob("*")) if path.is_file()}

    def sdk(self, root):
        bundle = self.helper_bundle(root)
        manifest = {"schema": 2, "pin": runtime.PIN, "architecture": "arm64", "minimumSystemVersion": "12.7",
                    "launcher": {"source": "tools/import_python_main.c",
                                 "sourceSHA256": runtime.sha256(runtime.BETA / "tools/import_python_main.c")},
                    "files": self.inventory(bundle),
                    "machO": {path: {"minimumOS": ["12.7"], "dependencies": ["/usr/lib/libSystem.B.dylib"]}
                              for path in ("Contents/MacOS/python3.15", "Contents/PlugIns/_lzma.cpython-315-darwin.so")},
                    "relocation": {"isolated": True, "moduleClosure": True},
                    "signing": "ad-hoc development only", "nativeUIValidated": False}
        (root / "runtime.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return bundle, manifest

    def archive(self, root, entries):
        path = root / "source.tar.xz"
        with tarfile.open(path, "w:xz") as archive:
            for name, kind, body in entries:
                member = tarfile.TarInfo(name)
                member.type = kind
                if kind == tarfile.REGTYPE:
                    member.size = len(body)
                    archive.addfile(member, io.BytesIO(body))
                else:
                    member.linkname = body.decode()
                    archive.addfile(member)
        return path

    def test_extracts_regular_source_without_using_tar_extractall(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            archive = self.archive(root, [("Python-3.15.2/LICENSE", tarfile.REGTYPE, b"license")])
            result = runtime.extract_source(archive, root / "expanded")
            self.assertEqual((result / "LICENSE").read_bytes(), b"license")

    def test_rejects_traversal_links_devices_duplicate_names_and_wrong_root_before_writing(self):
        cases = [
            ("Python-3.15.2/../../outside", tarfile.REGTYPE, b"x"),
            ("/Python-3.15.2/file", tarfile.REGTYPE, b"x"),
            ("Python-3.15.2/link", tarfile.SYMTYPE, b"../../outside"),
            ("Python-3.15.2/link", tarfile.LNKTYPE, b"Python-3.15.2/LICENSE"),
            ("Python-3.15.2/device", tarfile.CHRTYPE, b""),
            ("other/source", tarfile.REGTYPE, b"x"),
            ("Python-3.15.2/LICENSE", tarfile.REGTYPE, b"duplicate"),
        ]
        for member_name, kind, body in cases:
            with self.subTest(member=member_name, kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = self.archive(root, [("Python-3.15.2/LICENSE", tarfile.REGTYPE, b"license"), (member_name, kind, body)])
                with self.assertRaisesRegex(ValueError, "Unsafe CPython"):
                    runtime.extract_source(archive, root / "expanded")
                self.assertFalse((root / "expanded").exists())

    def test_expansion_bound_is_checked_before_extracting(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            archive = self.archive(root, [("Python-3.15.2/file", tarfile.REGTYPE, b"12345")])
            with patch.object(runtime, "MAXIMUM_EXPANDED", 4), self.assertRaisesRegex(ValueError, "expansion"):
                runtime.extract_source(archive, root / "expanded")
            self.assertFalse((root / "expanded").exists())

    def test_existing_wrong_source_is_never_replaced_or_downloaded(self):
        with tempfile.TemporaryDirectory() as name:
            source = Path(name) / "source.tar.xz"
            source.write_bytes(b"wrong source")
            with patch.object(runtime.urllib.request, "urlopen") as fetch, self.assertRaisesRegex(ValueError, "checksum"):
                runtime.fetch_archive(source)
            fetch.assert_not_called()
            self.assertEqual(source.read_bytes(), b"wrong source")

    def test_runtime_rejects_symlinks_even_when_target_is_inside(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "actual").write_bytes(b"x")
            (root / "alias").symlink_to("actual")
            with self.assertRaisesRegex(ValueError, "Linked"):
                runtime.checked_files(root)

    def test_helper_layout_separates_code_resources_and_final_signature(self):
        with tempfile.TemporaryDirectory() as name:
            bundle = self.helper_bundle(Path(name), signed=False)
            files = runtime.checked_runtime_layout(bundle)
            self.assertEqual(len(files), 8)
            self.assertIn(bundle / "Contents/MacOS/python3.15", files)
            self.assertIn(bundle / "Contents/PlugIns/_lzma.cpython-315-darwin.so", files)
            self.assertIn(bundle / "Contents/Resources/LICENSE-XZ-Utils.txt", files)
            with self.assertRaises(ValueError):
                runtime.checked_runtime_layout(bundle, signed=True)
            seal = bundle / "Contents/_CodeSignature/CodeResources"
            seal.parent.mkdir(); seal.write_bytes(b"final signature resource fixture")
            self.assertEqual(set(runtime.checked_runtime_layout(bundle, signed=True)), set(files) | {seal})

    def test_helper_layout_rejects_old_prefix_misplaced_data_and_wrong_code_types(self):
        cases = ("old-prefix", "json-in-MacOS", "license-in-PlugIns", "code-in-Resources",
                 "code-disguised-as-archive", "wrong-executable-type", "wrong-extension-type",
                 "nested-extensions", "root-data", "contents-data", "wrong-bundle-identity",
                 "resource-link", "extra-signature-file")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as name:
                bundle = self.helper_bundle(Path(name))
                contents = bundle / "Contents"
                if case == "old-prefix":
                    shutil.rmtree(contents)
                    (bundle / "bin").mkdir(); (bundle / "lib/python3.15").mkdir(parents=True)
                    (bundle / "bin/python3.15").write_bytes(self.macho(2))
                    (bundle / "runtime.json").write_bytes(b"{}")
                    (bundle / "LICENSE-XZ-Utils.txt").write_bytes(b"license")
                    (bundle / "lib/python3.15/os.py").write_bytes(b"stdlib")
                elif case == "json-in-MacOS": (contents / "MacOS/runtime.json").write_bytes(b"{}")
                elif case == "license-in-PlugIns": (contents / "PlugIns/LICENSE-XZ-Utils.txt").write_bytes(b"license")
                elif case in ("code-in-Resources", "code-disguised-as-archive"):
                    suffix = ".so" if case == "code-in-Resources" else ".a"
                    (contents / ("Resources/lib/python3.15/unreviewed" + suffix)).write_bytes(self.macho(8))
                elif case == "wrong-executable-type": (contents / "MacOS/python3.15").write_bytes(self.macho(8))
                elif case == "wrong-extension-type": (contents / "PlugIns/_lzma.cpython-315-darwin.so").write_bytes(self.macho(6))
                elif case == "nested-extensions":
                    nested = contents / "PlugIns/group"; nested.mkdir()
                    (contents / "PlugIns/_lzma.cpython-315-darwin.so").rename(nested / "_lzma.cpython-315-darwin.so")
                elif case == "root-data": (bundle / "runtime.json").write_bytes(b"{}")
                elif case == "contents-data": (contents / "runtime.json").write_bytes(b"{}")
                elif case == "wrong-bundle-identity":
                    info = plistlib.loads((contents / "Info.plist").read_bytes())
                    info["CFBundleExecutable"] = "../Resources/python3.15"
                    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
                elif case == "resource-link":
                    (contents / "Resources/alias.py").symlink_to("lib/python3.15/os.py")
                else: (contents / "_CodeSignature/unexpected").write_bytes(b"unreviewed signature data")
                message = "Mach-O code is forbidden" if case in ("code-in-Resources", "code-disguised-as-archive") else ".*"
                with self.assertRaisesRegex(ValueError, message):
                    runtime.checked_runtime_layout(bundle, signed=True)

    def test_bundle_copy_preserves_all_signed_bytes_and_keeps_manifest_outside_helper(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); sdk = root / "sdk"
            helper, manifest = self.sdk(sdk)
            before = self.inventory(helper)
            app = root / "Magnolie.app"; (app / "Contents/Resources").mkdir(parents=True)
            with patch.object(runtime.platform, "machine", return_value="arm64"), \
                 patch.object(runtime, "check_macho", return_value={"minimumOS": ["12.7"], "dependencies": ["/usr/lib/libSystem.B.dylib"]}), \
                 patch.object(runtime.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as codesign, \
                 patch.object(runtime, "verify_relocation", return_value={"isolated": True, "moduleClosure": True}) as relocation:
                result = runtime.bundle_runtime(app, sdk)
            copied = app / "Contents/Helpers/ImportPython.app"
            self.assertEqual(result, manifest)
            self.assertEqual(self.inventory(copied), before)
            self.assertEqual(self.inventory(helper), before)
            self.assertEqual((copied / "Contents/MacOS/python3.15").stat().st_mode & 0o777, 0o755)
            self.assertEqual((app / "Contents/Resources/ImportPython/runtime.json").read_bytes(), (sdk / "runtime.json").read_bytes())
            self.assertFalse((copied / "runtime.json").exists())
            self.assertFalse((copied / "Contents/Resources/runtime.json").exists())
            relocation.assert_called_with(copied)
            self.assertTrue(codesign.called)
            for call in codesign.call_args_list:
                self.assertEqual(call.args[0][0], "codesign")
                self.assertIn("--verify", call.args[0])
                self.assertNotIn("--sign", call.args[0])

    def test_bundle_copy_rejects_modified_missing_and_extra_signed_files(self):
        cases = ("interpreter", "extension", "seal", "missing-seal", "added-resource", "missing-resource", "manifest-extra")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as name:
                root = Path(name); sdk = root / "sdk"
                helper, manifest = self.sdk(sdk)
                if case == "manifest-extra":
                    manifest["files"]["../outside"] = "0" * 64
                    (sdk / "runtime.json").write_text(json.dumps(manifest))
                else:
                    paths = {"interpreter": "Contents/MacOS/python3.15",
                             "extension": "Contents/PlugIns/_lzma.cpython-315-darwin.so",
                             "seal": "Contents/_CodeSignature/CodeResources", "missing-seal": "Contents/_CodeSignature/CodeResources",
                             "added-resource": "Contents/Resources/lib/python3.15/extra.py", "missing-resource": "Contents/Resources/lib/python3.15/os.py"}
                    path = helper / paths[case]
                    if case.startswith("missing-"): path.unlink()
                    else: path.write_bytes((path.read_bytes() if path.exists() else b"") + b"changed")
                app = root / "Magnolie.app"; (app / "Contents/Resources").mkdir(parents=True)
                with patch.object(runtime.platform, "machine", return_value="arm64"), \
                     patch.object(runtime.subprocess, "run") as codesign, \
                     patch.object(runtime, "verify_relocation") as relocation, self.assertRaises(ValueError):
                    runtime.bundle_runtime(app, sdk)
                self.assertFalse((app / "Contents/Helpers/ImportPython.app").exists())
                codesign.assert_not_called(); relocation.assert_not_called()

    def test_bundle_copy_detects_resource_change_during_copy(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); sdk = root / "sdk"
            self.sdk(sdk)
            app = root / "Magnolie.app"; (app / "Contents/Resources").mkdir(parents=True)
            copytree = shutil.copytree
            def changed_copy(source, destination, *args, **kwargs):
                result = copytree(source, destination, *args, **kwargs)
                if Path(destination).name == "ImportPython.app":
                    (Path(destination) / "Contents/Resources/lib/python3.15/os.py").write_bytes(b"changed during copy")
                return result
            with patch.object(runtime.platform, "machine", return_value="arm64"), \
                 patch.object(runtime.shutil, "copytree", side_effect=changed_copy), \
                 patch.object(runtime.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
                 patch.object(runtime, "check_macho", return_value={"minimumOS": ["12.7"], "dependencies": ["/usr/lib/libSystem.B.dylib"]}), \
                 patch.object(runtime, "verify_relocation") as relocation, self.assertRaises(ValueError):
                runtime.bundle_runtime(app, sdk)
            relocation.assert_not_called()

    def test_bundle_copy_binds_the_manifest_to_the_current_launcher_and_native_identity(self):
        for case in ("schema", "pin", "architecture", "minimum", "launcher"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as name:
                root = Path(name); sdk = root / "sdk"
                _, manifest = self.sdk(sdk)
                if case == "schema": manifest["schema"] = 1
                elif case == "pin": manifest["pin"] = dict(manifest["pin"], version="unreviewed")
                elif case == "architecture": manifest["architecture"] = "x86_64"
                elif case == "minimum": manifest["minimumSystemVersion"] = "13.0"
                else: manifest["launcher"]["sourceSHA256"] = "0" * 64
                (sdk / "runtime.json").write_text(json.dumps(manifest))
                app = root / "Magnolie.app"; (app / "Contents/Resources").mkdir(parents=True)
                with patch.object(runtime.platform, "machine", return_value="arm64"), \
                     patch.object(runtime.subprocess, "run") as codesign, self.assertRaises(ValueError):
                    runtime.bundle_runtime(app, sdk)
                self.assertFalse((app / "Contents/Helpers/ImportPython.app").exists())
                codesign.assert_not_called()

    def test_bundle_copy_requires_macho_evidence_to_match_the_copied_images(self):
        for case in ("missing-image", "wrong-minimum", "wrong-dependency"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as name:
                root = Path(name); sdk = root / "sdk"
                _, manifest = self.sdk(sdk)
                image = "Contents/PlugIns/_lzma.cpython-315-darwin.so"
                if case == "missing-image": del manifest["machO"][image]
                elif case == "wrong-minimum": manifest["machO"][image]["minimumOS"] = ["14.0"]
                else: manifest["machO"][image]["dependencies"] = ["/opt/homebrew/lib/liblzma.dylib"]
                (sdk / "runtime.json").write_text(json.dumps(manifest))
                app = root / "Magnolie.app"; (app / "Contents/Resources").mkdir(parents=True)
                with patch.object(runtime.platform, "machine", return_value="arm64"), \
                     patch.object(runtime.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
                     patch.object(runtime, "check_macho", return_value={"minimumOS": ["12.7"], "dependencies": ["/usr/lib/libSystem.B.dylib"]}), \
                     patch.object(runtime, "verify_relocation") as relocation, self.assertRaises(ValueError):
                    runtime.bundle_runtime(app, sdk)
                relocation.assert_not_called()
                self.assertFalse((app / "Contents/Resources/ImportPython/runtime.json").exists())

    def test_relocation_runs_only_the_signed_helper_with_hostile_environment_and_propagates_failure(self):
        for successful in (True, False):
            with self.subTest(successful=successful), tempfile.TemporaryDirectory() as name:
                bundle = self.helper_bundle(Path(name).resolve())
                proof = {"version": "3.15.2", "isolated": True, "moduleClosure": True,
                         "bundleLayout": True, "executableBound": True}
                def probe(command, **kwargs):
                    self.assertEqual(command[0], str(bundle / "Contents/MacOS/python3.15"))
                    self.assertEqual(command[1:5], ["-I", "-S", "-B", "-c"])
                    self.assertEqual(command[6], str(bundle))
                    self.assertEqual(json.loads(command[7]), runtime.PIN["requiredModules"])
                    self.assertEqual(command[8], "3.15.2")
                    self.assertEqual(json.loads(command[9]), ["Contents/Resources/lib/python3.15", "Contents/PlugIns"])
                    self.assertEqual(command[10], "Contents/MacOS/python3.15")
                    hostile = Path(kwargs["cwd"])
                    self.assertTrue((hostile / "sitecustomize.py").is_file())
                    environment = kwargs["env"]
                    self.assertEqual(environment["PATH"], "/usr/bin:/bin:/usr/sbin:/sbin")
                    self.assertEqual(environment["PYTHONHOME"], str(hostile))
                    self.assertEqual(environment["PYTHONPATH"], str(hostile))
                    for key in ("PYTHONEXECUTABLE", "__PYVENV_LAUNCHER__"):
                        self.assertTrue(Path(environment[key]).is_relative_to(hostile))
                    if not successful: raise subprocess.CalledProcessError(1, command)
                    return json.dumps(proof)
                with patch.object(runtime.subprocess, "check_output", side_effect=probe) as child:
                    if successful: self.assertEqual(runtime.verify_relocation(bundle), proof)
                    else:
                        with self.assertRaises(subprocess.CalledProcessError): runtime.verify_relocation(bundle)
                child.assert_called_once()

    def test_cpython_build_extension_links_become_regular_runtime_files(self):
        with tempfile.TemporaryDirectory() as name:
            source = Path(name) / "Python-3.15.2"
            modules, build = source / "Modules", source / "build/lib.macosx-12.7-arm64-3.15"
            modules.mkdir(parents=True); build.mkdir(parents=True)
            generated = modules / "_lzma.cpython-315.so"
            generated.write_bytes(b"built extension bytes")
            link = build / generated.name
            link.symlink_to("../../Modules/" + generated.name)
            ordinary = build / "regular.so"
            ordinary.write_bytes(b"regular extension bytes")
            output = Path(name) / "runtime"
            output.mkdir()
            for entry in (link, ordinary):
                shutil.copy2(runtime.extension_output(entry, source), output / entry.name)
                self.assertFalse((output / entry.name).is_symlink())
                self.assertEqual((output / entry.name).read_bytes(), entry.read_bytes())
            self.assertEqual(len(runtime.checked_files(output)), 2)

    def test_extension_links_cannot_escape_rename_chain_or_replace_directories(self):
        for case in ("absolute", "foreign", "renamed", "broken", "chain", "modules-link", "build-link", "directory"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                source = root / "Python-3.15.2"
                modules, build = source / "Modules", source / "build/lib.macosx-12.7-arm64-3.15"
                modules.mkdir(parents=True); build.mkdir(parents=True)
                generated = modules / "_lzma.cpython-315.so"
                generated.write_bytes(b"built extension bytes")
                path = build / generated.name
                foreign = root / "foreign.so"; foreign.write_bytes(b"foreign")
                target = "../../Modules/" + generated.name
                if case == "absolute": target = str(generated)
                elif case == "foreign": target = str(foreign)
                elif case == "renamed":
                    (modules / "other.so").write_bytes(b"other")
                    target = "../../Modules/other.so"
                elif case == "broken": generated.unlink()
                elif case == "chain":
                    generated.unlink(); generated.symlink_to(foreign)
                elif case == "modules-link":
                    moved = source / "real-modules"; modules.rename(moved); modules.symlink_to(moved, target_is_directory=True)
                elif case == "build-link":
                    moved = source / "real-build"; build.rename(moved); build.symlink_to(moved, target_is_directory=True)
                if case == "directory": path.mkdir()
                else: path.symlink_to(target)
                with self.assertRaisesRegex(ValueError, "CPython extension"):
                    runtime.extension_output(path, source)

    def test_xz_source_has_the_same_extraction_and_hash_boundary(self):
        pin = runtime.LIBLZMA_PIN
        for bad in ("link", "outside", "wrong-root"):
            with self.subTest(case=bad), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                member = (pin["sourceRoot"] + "/COPYING", tarfile.REGTYPE, b"license")
                invalid = {
                    "link": (pin["sourceRoot"] + "/alias", tarfile.SYMTYPE, b"COPYING"),
                    "outside": (pin["sourceRoot"] + "/../outside", tarfile.REGTYPE, b"x"),
                    "wrong-root": ("other/COPYING", tarfile.REGTYPE, b"x"),
                }[bad]
                archive = self.archive(root, [member, invalid])
                with self.assertRaisesRegex(ValueError, "Unsafe XZ Utils"):
                    runtime.extract_source(archive, root / "expanded", pin)
                self.assertFalse((root / "expanded").exists())
                with self.assertRaisesRegex(ValueError, "checksum"):
                    runtime.verify_archive(archive, pin)

    def test_xz_download_keeps_https_cdn_digest_and_size_boundaries(self):
        payload = b"pinned source fixture"
        pin = dict(runtime.LIBLZMA_PIN, sourceSHA256=hashlib.sha256(payload).hexdigest())
        cases = [(pin["sourceURL"], payload, pin["maximumArchiveBytes"], True),
                 ("https://release-assets.githubusercontent.com/asset", payload, pin["maximumArchiveBytes"], True),
                 ("http://release-assets.githubusercontent.com/asset", payload, pin["maximumArchiveBytes"], False),
                 ("https://release-assets.githubusercontent.com.invalid/asset", payload, pin["maximumArchiveBytes"], False),
                 ("https://user:password@release-assets.githubusercontent.com/asset", payload, pin["maximumArchiveBytes"], False),
                 ("https://release-assets.githubusercontent.com:444/asset", payload, pin["maximumArchiveBytes"], False),
                 ("https://release-assets.githubusercontent.com/asset", b"wrong source", pin["maximumArchiveBytes"], False),
                 ("https://release-assets.githubusercontent.com/asset", payload, 1, False)]
        for url, body, limit, accepted in cases:
            with self.subTest(url=url, accepted=accepted, limit=limit), tempfile.TemporaryDirectory() as name:
                root = Path(name); target = root / "source.tar.xz"
                response = io.BytesIO(body); response.geturl = lambda: url
                with patch.object(runtime.urllib.request, "urlopen", return_value=response):
                    if accepted:
                        runtime.fetch_archive(target, dict(pin, maximumArchiveBytes=limit))
                        self.assertEqual(target.read_bytes(), payload)
                    else:
                        with self.assertRaises(ValueError):
                            runtime.fetch_archive(target, dict(pin, maximumArchiveBytes=limit))
                        self.assertEqual(list(root.iterdir()), [])

    def test_native_build_orchestration_statically_links_codec_and_copies_licenses(self):
        """Controlled compiler outputs verify composition; no native build is claimed."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            cp_root, xz_root = root / "cpython-source", root / "xz-source"
            cp_root.mkdir(); xz_root.mkdir()
            cp_archive = self.archive(cp_root, [
                ("Python-3.15.2/configure", tarfile.REGTYPE, b"configure"),
                ("Python-3.15.2/Modules/placeholder", tarfile.REGTYPE, b"module"),
                ("Python-3.15.2/Lib/os.py", tarfile.REGTYPE, b"stdlib"),
                ("Python-3.15.2/LICENSE", tarfile.REGTYPE, b"python license")])
            xz_archive = self.archive(xz_root, [
                (runtime.LIBLZMA_PIN["sourceRoot"] + "/configure", tarfile.REGTYPE, b"configure"),
                (runtime.LIBLZMA_PIN["sourceRoot"] + "/COPYING", tarfile.REGTYPE, b"xz licensing summary"),
                (runtime.LIBLZMA_PIN["sourceRoot"] + "/COPYING.0BSD", tarfile.REGTYPE, b"liblzma license")])
            observed, signing_order = {}, []
            static_bytes, extension_bytes = b"!<arch>\nstatic codec fixture", self.macho(8) + b"extension fixture"
            stock_bytes, launcher_bytes = self.macho(2) + b"stock interpreter", self.macho(2) + b"isolated launcher"

            def execute(command, **kwargs):
                if command[0].endswith("/configure"):
                    prefix = Path(next(x.split("=", 1)[1] for x in command if x.startswith("--prefix=")))
                    if Path(command[0]).parent.name == runtime.LIBLZMA_PIN["sourceRoot"]:
                        observed["xz"] = {"prefix": prefix, "cwd": Path(kwargs["cwd"]), "environment": dict(kwargs["env"])}
                        self.assertIn("--disable-shared", command)
                        self.assertIn("--enable-static", command)
                    else:
                        observed["python"] = {"source": Path(kwargs["cwd"]), "environment": dict(kwargs["env"])}
                elif command[0] == "make" and "-C" in command:
                    self.assertEqual(Path(command[2]), observed["xz"]["cwd"] / "src/liblzma")
                    if "install" in command:
                        prefix = observed["xz"]["prefix"]
                        (prefix / "lib").mkdir(parents=True); (prefix / "include").mkdir()
                        (prefix / "lib/liblzma.a").write_bytes(static_bytes)
                        (prefix / "include/lzma.h").write_bytes(b"codec headers")
                elif command[0] == "make" and "-f" in command:
                    source = observed["python"]["source"]
                    self.assertEqual(command, ["make", "-f", "Makefile", "-f", "MagnolieImport.mk", "magnolie-import-python"])
                    self.assertEqual((source / "python.exe").read_bytes(), stock_bytes)
                    self.assertEqual((source / "Programs/magnolie_import_python.c").read_bytes(),
                                     (runtime.BETA / "tools/import_python_main.c").read_bytes())
                    (source / "magnolie-import-python").write_bytes(launcher_bytes)
                    (source / "magnolie-import-python").chmod(0o755)
                    observed["launcher"] = True
                elif command[0] == "make":
                    source = observed["python"]["source"]
                    (source / "python.exe").write_bytes(stock_bytes)
                    extension = source / "Modules/_lzma.cpython-315.so"
                    extension.write_bytes(extension_bytes)
                    build = source / "build/lib.macosx-12.7-arm64-3.15"; build.mkdir(parents=True)
                    (build / extension.name).symlink_to("../../Modules/" + extension.name)
                    (build / "_sysconfigdata__darwin_.py").write_bytes(b"build settings")
                else:
                    self.assertEqual(command[0], "codesign")
                    target = Path(command[-1])
                    if "--sign" in command:
                        self.assertNotIn("--deep", command)
                        signing_order.append(target.name)
                        if target.is_file():
                            self.assertEqual(target.suffix, ".so")
                            target.write_bytes(target.read_bytes() + b"individual code signature")
                        else:
                            self.assertEqual(target.name, "ImportPython.app")
                            self.assertIn("_lzma.cpython-315.so", signing_order)
                            executable = target / "Contents/MacOS/python3.15"
                            executable.write_bytes(executable.read_bytes() + b"final helper signature")
                            seal = target / "Contents/_CodeSignature/CodeResources"
                            seal.parent.mkdir()
                            seal.write_bytes(plistlib.dumps({"fixture": "final helper resource seal"}))
                    else:
                        self.assertIn("--verify", command)
                        if target.is_dir(): self.assertTrue((target / "Contents/_CodeSignature/CodeResources").is_file())
                return subprocess.CompletedProcess(command, 0)

            def relocation(bundle):
                self.assertFalse(observed["python"]["source"].exists())
                self.assertFalse(observed["xz"]["prefix"].exists())
                self.assertEqual((bundle / "Contents/PlugIns/_lzma.cpython-315.so").read_bytes(),
                                 extension_bytes + b"individual code signature")
                self.assertEqual((bundle / "Contents/MacOS/python3.15").read_bytes(), launcher_bytes + b"final helper signature")
                runtime.checked_runtime_layout(bundle, signed=True)
                self.assertEqual(signing_order[-1], "ImportPython.app")
                return {"isolated": True, "moduleClosure": True}

            with patch.dict(runtime.PIN, sourceSHA256=runtime.sha256(cp_archive)), \
                 patch.dict(runtime.LIBLZMA_PIN, sourceSHA256=runtime.sha256(xz_archive)), \
                 patch.object(runtime.platform, "system", return_value="Darwin"), \
                 patch.object(runtime.platform, "machine", return_value="arm64"), \
                 patch.object(runtime.subprocess, "check_output", side_effect=["/mock SDK\n", "/mock tool/clang\n"]), \
                 patch.object(runtime.subprocess, "run", side_effect=execute), \
                 patch.object(runtime, "verify_relocation", side_effect=relocation), \
                 patch.object(runtime, "check_macho", return_value={"minimumOS": ["12.7"]}) as macho:
                destination = root / "runtime"
                manifest = runtime.build_runtime(cp_archive, destination, "arm64", "12.7", xz_archive)
                python_env, xz_env = observed["python"]["environment"], observed["xz"]["environment"]
                for flag in ("CC", "MACOSX_DEPLOYMENT_TARGET", "CFLAGS", "LDFLAGS"):
                    self.assertEqual(python_env[flag], xz_env[flag])
                flags = shlex.split(python_env["CFLAGS"])
                self.assertEqual(flags[flags.index("-arch") + 1], "arm64")
                self.assertIn("-mmacosx-version-min=12.7", flags)
                self.assertEqual(shlex.split(python_env["LIBLZMA_LIBS"]), [str(observed["xz"]["prefix"] / "lib/liblzma.a")])
                self.assertEqual(shlex.split(python_env["LIBLZMA_CFLAGS"]), ["-I" + str(observed["xz"]["prefix"] / "include")])
                bundle = destination / "ImportPython.app"
                self.assertTrue(observed["launcher"])
                self.assertEqual((bundle / "Contents/Resources/LICENSE-XZ-Utils.txt").read_bytes(), b"xz licensing summary")
                self.assertEqual((bundle / "Contents/Resources/LICENSE-liblzma-0BSD.txt").read_bytes(), b"liblzma license")
                self.assertIn("Contents/Resources/LICENSE-liblzma-0BSD.txt", manifest["files"])
                self.assertIn("Contents/_CodeSignature/CodeResources", manifest["files"])
                self.assertEqual(manifest["files"], self.inventory(bundle))
                self.assertEqual(json.loads((destination / "runtime.json").read_text()), manifest)
                self.assertFalse((bundle / "runtime.json").exists())
                self.assertEqual(manifest["staticDependencies"]["liblzma"]["librarySHA256"], hashlib.sha256(static_bytes).hexdigest())
                self.assertEqual(macho.call_count, 2)
                self.assertTrue(all(call.args[1:] == ("arm64", "12.7") for call in macho.call_args_list))

    def test_private_codec_sdk_rejects_shared_or_linked_or_nonarchive_outputs(self):
        for case in ("shared", "linked-header", "not-static"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as name:
                root = Path(name); source = root / "input"; source.mkdir()
                archive = self.archive(source, [(runtime.LIBLZMA_PIN["sourceRoot"] + "/configure", tarfile.REGTYPE, b"configure")])
                owned = root / "owned"

                def execute(command, **kwargs):
                    if command[0] == "make" and "install" in command:
                        prefix = owned / "liblzma-sdk"
                        (prefix / "lib").mkdir(parents=True); (prefix / "include").mkdir()
                        (prefix / "lib/liblzma.a").write_bytes(b"not an archive" if case == "not-static" else b"!<arch>\nfixture")
                        (prefix / "include/lzma.h").write_bytes(b"header")
                        if case == "shared": (prefix / "lib/liblzma.dylib").write_bytes(b"shared")
                        if case == "linked-header":
                            header = prefix / "include/lzma.h"; header.unlink(); header.symlink_to(prefix / "lib/liblzma.a")
                    return subprocess.CompletedProcess(command, 0)

                with patch.dict(runtime.LIBLZMA_PIN, sourceSHA256=runtime.sha256(archive)), \
                     patch.object(runtime.subprocess, "run", side_effect=execute), self.assertRaises(ValueError):
                    runtime.build_liblzma(archive, owned, {})

    def test_macho_rejects_newer_minimum_foreign_arch_and_external_dependencies(self):
        def run(outputs):
            with patch.object(runtime.subprocess, "check_output", side_effect=outputs):
                return runtime.check_macho(Path("test-runtime"), "arm64", "12.7")
        target = "Load command 0\n cmd LC_BUILD_VERSION\n platform MACOS\n minos 12.7\n"
        self.assertEqual(run(["arm64\n", target, "test-runtime:\n /usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n"])["minimumOS"], ["12.7"])
        for outputs in [
            ["x86_64\n"],
            ["arm64\n", target.replace("12.7", "14.0")],
            ["arm64\n", target, "test-runtime:\n /opt/homebrew/lib/liblzma.dylib (compatibility version 1.0.0)\n"],
            ["arm64\n", target, "test-runtime:\n @rpath/Python (compatibility version 1.0.0)\n"],
        ]:
            with self.subTest(outputs=outputs), self.assertRaises(ValueError):
                run(outputs)

    def test_runtime_and_outer_app_reject_foreign_missing_and_ambiguous_platforms(self):
        # Refs #806: the same CPU/minimum is not sufficient for macOS code.
        target = "Load command 0\n cmd LC_BUILD_VERSION\n platform MACOS\n minos 12.7\n"
        cases = [target.replace("MACOS", platform) for platform in
                 ("IOS", "MACCATALYST", "IOSSIMULATOR", "2", "6", "7", "999")]
        cases += [target.replace(" platform MACOS\n", ""), target.replace(" minos 12.7\n", ""),
                  target + " platform IOS\n", target + " minos 14.0\n",
                  target.replace("12.7", "12.7.invalid"),
                  " platform MACOS\n minos 12.7\n",
                  target + target.replace("command 0", "command 1"),
                  target.replace("MACOS", "IOS") + target.replace("command 0", "command 1"),
                  target + "Load command 1\n cmd LC_VERSION_MIN_MACOSX\n version 12.7\n",
                  "Load command 0\n cmd LC_VERSION_MIN_MACOSX\n version 12.7\n"]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                with patch.object(runtime.subprocess, "check_output", side_effect=["arm64\n", metadata]), \
                     self.assertRaises(ValueError):
                    runtime.check_macho(Path("test-runtime"), "arm64", "12.7")
                with patch.object(build_dev.subprocess, "check_output", return_value=metadata), \
                     self.assertRaises(ValueError):
                    build_dev.verify_macos_deployment(Path("test-app"), "12.7")

    def test_runtime_and_outer_app_keep_their_distinct_minimum_version_contracts(self):
        dependency = "test-runtime:\n /usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n"
        for platform in ("1", "macos", "MACOS"):
            for minimum in ("10.15", "12.7", "12.7.0", "13.0"):
                metadata = f"Load command 0\n cmd LC_BUILD_VERSION\n platform {platform}\n minos {minimum}\n"
                with self.subTest(platform=platform, minimum=minimum):
                    with patch.object(runtime.subprocess, "check_output", side_effect=["arm64\n", metadata, dependency]):
                        if minimum == "13.0":
                            with self.assertRaisesRegex(ValueError, "minimum macOS"):
                                runtime.check_macho(Path("test-runtime"), "arm64", "12.7")
                        else:
                            self.assertEqual(runtime.check_macho(Path("test-runtime"), "arm64", "12.7")["minimumOS"], [minimum])
                    with patch.object(build_dev.subprocess, "check_output", return_value=metadata):
                        if minimum in ("12.7", "12.7.0"):
                            self.assertEqual(build_dev.verify_macos_deployment(Path("test-app"), "12.7"), minimum)
                        else:
                            with self.assertRaisesRegex(RuntimeError, "minimum OS does not match"):
                                build_dev.verify_macos_deployment(Path("test-app"), "12.7")

    def test_build_tool_versions_are_not_runtime_or_app_deployment_versions(self):
        # Apple's vtool prints tool/version pairs inside LC_BUILD_VERSION.
        metadata = ("Load command 9\n cmd LC_BUILD_VERSION\n cmdsize 48\n platform MACOS\n"
                    " minos 12.7\n sdk 15.5\n ntools 3\n tool CLANG\n version 17.0.0\n"
                    " tool SWIFT\n version 6.1.2\n tool LD\n version 1167.5\n")
        dependency = "test-runtime:\n /usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n"
        with patch.object(runtime.subprocess, "check_output", side_effect=["arm64\n", metadata, dependency]):
            self.assertEqual(runtime.check_macho(Path("test-runtime"), "arm64", "12.7")["minimumOS"], ["12.7"])
        with patch.object(build_dev.subprocess, "check_output", return_value=metadata):
            self.assertEqual(build_dev.verify_macos_deployment(Path("test-app"), "12.7"), "12.7")
        for invalid in (metadata.replace(" minos 12.7\n", ""), metadata + " minos 12.7\n",
                        metadata.replace("platform MACOS", "platform IOS")):
            with self.subTest(metadata=invalid):
                with patch.object(runtime.subprocess, "check_output", side_effect=["arm64\n", invalid]), \
                     self.assertRaises(ValueError):
                    runtime.check_macho(Path("test-runtime"), "arm64", "12.7")
                with patch.object(build_dev.subprocess, "check_output", return_value=invalid), \
                     self.assertRaises(ValueError):
                    build_dev.verify_macos_deployment(Path("test-app"), "12.7")

    @unittest.skipUnless(sys.platform == "darwin", "Real Mach-O platform regression requires Apple's compiler and tools")
    def test_native_tools_reject_foreign_platform_in_real_macho_bytes(self):
        # Compile once; mutate only the deployment platform. This checks real
        # lipo/vtool output, without executing or signing the modified images.
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            source, image = root / "main.c", root / "native-macos"
            source.write_text("int main(void) { return 0; }\n")
            architecture = runtime.platform.machine()
            sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
            subprocess.run(["xcrun", "clang", "-arch", architecture, "-isysroot", sdk,
                            "-mmacosx-version-min=12.7", str(source), "-o", str(image)], check=True, timeout=60)
            metadata = subprocess.check_output(["xcrun", "vtool", "-show-build", str(image)], text=True)
            try:
                targets = runtime.check_macho(image, architecture, "12.7")["minimumOS"]
                self.assertEqual([runtime.version_tuple(value) for value in targets], [(12, 7, 0)])
                self.assertIn(build_dev.verify_macos_deployment(image, "12.7"), ("12.7", "12.7.0"))
            except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
                self.fail("Original native macOS image was rejected: " + str(error) + "\n" + metadata)
            original = image.read_bytes()
            self.assertEqual(original[:4], b"\xcf\xfa\xed\xfe")
            offset, builds = 32, []
            for _ in range(struct.unpack_from("<I", original, 16)[0]):
                command, size = struct.unpack_from("<II", original, offset)
                if command == 0x32:  # Apple's LC_BUILD_VERSION.
                    builds.append(offset)
                self.assertGreaterEqual(size, 8)
                offset += size
            self.assertEqual(len(builds), 1)
            self.assertEqual(struct.unpack_from("<I", original, builds[0] + 8)[0], 1)
            for platform in (2, 6, 7):  # iOS, Mac Catalyst, iOS Simulator.
                with self.subTest(platform=platform):
                    changed = bytearray(original)
                    struct.pack_into("<I", changed, builds[0] + 8, platform)
                    foreign = root / ("foreign-platform-" + str(platform))
                    foreign.write_bytes(changed)
                    with self.assertRaisesRegex(ValueError, "not built for macOS"):
                        runtime.check_macho(foreign, architecture, "12.7")
                    with self.assertRaisesRegex(ValueError, "not built for macOS"):
                        build_dev.verify_macos_deployment(foreign, "12.7")

    def test_native_build_does_not_run_on_linux(self):
        with patch.object(runtime.platform, "system", return_value="Linux"), patch.object(runtime.subprocess, "run") as execute:
            with self.assertRaisesRegex(ValueError, "Apple build host"):
                runtime.build_runtime("not-read", "not-written", "arm64", "12.7")
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
