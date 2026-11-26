"""Host checks for the #785 build boundary; never a native-Mac pass claim."""
import io
import json
from pathlib import Path
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
