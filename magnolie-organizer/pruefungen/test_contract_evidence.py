"""Refs #787: release contracts exclude the two published Mac evidence trees."""

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "werkzeuge"))
import release_sources


class ContractEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="magnolie-contract-evidence-")
        self.addCleanup(temporary.cleanup)
        self.temp = Path(temporary.name)
        self.source = self.temp / "standalone"
        self.source.mkdir()

    def contracts(self, shared=False):
        folder = self.temp / "contracts" if shared else self.source / "contracts"
        folder.mkdir()
        (folder / "vectors.json").write_bytes(b'{"immutableGolden":true}')
        return folder

    def check_evidence_excluded(self, shared):
        contracts = self.contracts(shared)
        expected = {"vectors.json": b'{"immutableGolden":true}',
                    "lifecycle.md": b"# Public protocol lifecycle",
                    "nested/future-contract.json": b'{"newReviewedContract":true}'}
        for name, data in expected.items():
            path = contracts / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for directory in ("macos-issue-publication-2026-11-26", "macos-verification-2026-11-26"):
            for name in ("archive.bundle", "patches/change.patch.gz", "host-final.log",
                         "SHA256SUMS", "README.md", "manifest.json"):
                path = contracts / directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"Synthetic handoff evidence, not a product contract")
        release_sources.sync_contracts(self.source)
        self.assertEqual({relative.as_posix(): path.read_bytes() for relative, path in
                          release_sources.source_files(self.source / "contracts")}, expected)
        # Record, copy and standalone validation must use the same selection.
        record = {"contracts/" + relative.as_posix(): release_sources.source_identity(path)
                  for relative, path in release_sources.projection_files(contracts)}
        self.assertEqual(set(record), {"contracts/" + name for name in expected})
        release_sources.verify_projection(record, "contracts", contracts)
        release_sources.verify_projection(record, "magnolie-organizer", self.source)

    def test_shared_evidence_is_excluded_without_dropping_new_contracts(self):
        self.check_evidence_excluded(shared=True)

    def test_standalone_evidence_is_excluded_without_dropping_new_contracts(self):
        self.check_evidence_excluded(shared=False)

    def test_similar_nested_or_future_evidence_paths_remain_errors(self):
        contracts = self.contracts()
        for directory in ("macos-verification-2026-11-26-copy", "macos-verification-2026-11-27",
                          "nested/macos-verification-2026-11-26"):
            with self.subTest(directory=directory):
                path = contracts / directory / "unexpected.log"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Not an approved evidence directory", encoding="utf-8")
                try:
                    with self.assertRaisesRegex(ValueError, "contracts"):
                        release_sources.sync_contracts(self.source)
                finally:
                    path.unlink()

    def test_unsupported_contract_and_malformed_content_remain_errors(self):
        contracts = self.contracts()
        for name, data in (("unexpected.sh", "not a contract"),
                           ("invalid.json", "not JSON"), ("empty.md", "")):
            with self.subTest(name=name):
                path = contracts / name
                path.write_text(data, encoding="utf-8")
                try:
                    with self.assertRaises(ValueError):
                        release_sources.sync_contracts(self.source)
                finally:
                    path.unlink()

    def test_evidence_directory_symlink_is_rejected(self):
        contracts = self.contracts()
        outside = self.temp / "outside"
        outside.mkdir()
        (contracts / "macos-issue-publication-2026-11-26").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "directory symlink"):
            release_sources.sync_contracts(self.source)

    def test_exclusion_does_not_hide_an_ordinary_file_with_the_directory_name(self):
        contracts = self.contracts()
        (contracts / "macos-verification-2026-11-26").write_text("Not a directory", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "contracts"):
            release_sources.sync_contracts(self.source)

    def test_contract_symlink_and_private_material_remain_errors(self):
        contracts = self.contracts()
        outside = self.temp / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        link = contracts / "linked.json"
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "Non-regular source"):
            release_sources.sync_contracts(self.source)
        link.unlink()
        (contracts / "vectors.json").write_bytes(b"-----BEGIN PRIVATE KEY-----\nSYNTHETIC TEST MARKER\n")
        with self.assertRaisesRegex(ValueError, "Private material"):
            release_sources.sync_contracts(self.source)


if __name__ == "__main__":
    unittest.main()
