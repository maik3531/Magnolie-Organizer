"""Host checks for the #785 build boundary; never a native-Mac pass claim."""
import io
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import import_python_bundle as runtime


class ImportPythonBundleTests(unittest.TestCase):
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
            observed = {}
            static_bytes, extension_bytes = b"!<arch>\nstatic codec fixture", b"\xcf\xfa\xed\xfeextension fixture"

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
                elif command[0] == "make":
                    source = observed["python"]["source"]
                    (source / "python.exe").write_bytes(b"\xcf\xfa\xed\xfeexecutable fixture")
                    extension = source / "Modules/_lzma.cpython-315.so"
                    extension.write_bytes(extension_bytes)
                    build = source / "build/lib.macosx-12.7-arm64-3.15"; build.mkdir(parents=True)
                    (build / extension.name).symlink_to("../../Modules/" + extension.name)
                    (build / "_sysconfigdata__darwin_.py").write_bytes(b"build settings")
                else:
                    self.assertEqual(command[0], "codesign")
                return subprocess.CompletedProcess(command, 0)

            def relocation(destination):
                self.assertFalse(observed["python"]["source"].exists())
                self.assertFalse(observed["xz"]["prefix"].exists())
                self.assertEqual((destination / "lib/python3.15/lib-dynload/_lzma.cpython-315.so").read_bytes(), extension_bytes)
                runtime.checked_files(destination)
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
                self.assertEqual((destination / "LICENSE-XZ-Utils.txt").read_bytes(), b"xz licensing summary")
                self.assertEqual((destination / "LICENSE-liblzma-0BSD.txt").read_bytes(), b"liblzma license")
                self.assertIn("LICENSE-liblzma-0BSD.txt", manifest["files"])
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
        self.assertEqual(run(["arm64\n", " minos 12.7\n", "test-runtime:\n /usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n"])["minimumOS"], ["12.7"])
        for outputs in [
            ["x86_64\n"],
            ["arm64\n", " minos 14.0\n"],
            ["arm64\n", " minos 12.7\n", "test-runtime:\n /opt/homebrew/lib/liblzma.dylib (compatibility version 1.0.0)\n"],
            ["arm64\n", " minos 12.7\n", "test-runtime:\n @rpath/Python (compatibility version 1.0.0)\n"],
        ]:
            with self.subTest(outputs=outputs), self.assertRaises(ValueError):
                run(outputs)

    def test_native_build_does_not_run_on_linux(self):
        with patch.object(runtime.platform, "system", return_value="Linux"), patch.object(runtime.subprocess, "run") as execute:
            with self.assertRaisesRegex(ValueError, "Apple build host"):
                runtime.build_runtime("not-read", "not-written", "arm64", "12.7")
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
