"""Private encrypted publication records: actual files, keys and restart reads."""
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import json

from cryptography.exceptions import InvalidTag
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_transfer import TransferError
from magnolie_publication_journal import ProtectedPublicationJournal, PublicationWitness
from test_file_transfer_stage import FixtureCipher, binding, description
from test_file_publish import Fixture as PublisherFixture


class Fixture:
    def __init__(self, root):
        self.parent = root / "private-journals"
        self.parent.mkdir(mode=0o700)
        self.manifest = description()
        self.binding = binding()
        self.targets = {file.id: file.path for file in self.manifest.files}
        self.cipher = FixtureCipher()
        self.owner = "1" * 32
        self.witness = PublicationWitness(self.manifest.files[0].id, 12, 34, ((56, 78), (90, 12)))
        self.journals = []

    @property
    def root(self):
        return self.parent / (ProtectedPublicationJournal.PREFIX + self.owner)

    def open(self, create=False, **options):
        args = dict(parent=self.parent, manifest=self.manifest, binding=self.binding, targets=self.targets,
            seal=self.cipher.seal, unseal=self.cipher.open, owner=self.owner, create=create)
        args.update(options)
        journal = ProtectedPublicationJournal(**args)
        self.journals.append(journal)
        return journal

    def record(self, journal, until="verified"):
        result = None
        for phase in ProtectedPublicationJournal.PHASES:
            result = journal.append(phase, self.witness)
            if phase == until:
                return result

    def close(self):
        for journal in self.journals:
            journal.close()


@pytest.fixture
def fixture(tmp_path):
    fixture = Fixture(tmp_path)
    try:
        yield fixture
    finally:
        fixture.close()


@pytest.mark.parametrize("phase", ["prepared", "linked", "verified"])
def test_actual_durable_ciphertext_restart_is_inspection_only_not_saved_ack(fixture, phase):
    f = fixture
    journal = f.open(create=True)
    result = f.record(journal, phase)
    before = {p.name: p.read_bytes() for p in f.root.iterdir()}
    assert all(b"Photos" not in raw and b"Bl\xc3\xbcte" not in raw for raw in before.values())
    assert not result.is_saved_receipt and not result.grants_write_authority
    journal.close()
    reopened = f.open()
    assert reopened.inspect(f.witness.file_id) == result
    with pytest.raises(TransferError, match="recovery_read_only"):
        reopened.append(phase, f.witness)
    assert before == {p.name: p.read_bytes() for p in f.root.iterdir()}


def test_same_phase_is_idempotent_but_skipped_backward_and_changed_witness_are_not(fixture):
    f = fixture
    journal = f.open(create=True)
    for phase in ("linked", "verified"):
        with pytest.raises(TransferError, match="invalid_transition"):
            journal.append(phase, f.witness)
    first = journal.append("prepared", f.witness)
    before = {p.name: p.read_bytes() for p in f.root.iterdir()}
    assert journal.append("prepared", f.witness) == first
    with pytest.raises(TransferError, match="invalid_transition"):
        journal.append("linked", replace(f.witness, source_inode=35))
    assert before == {p.name: p.read_bytes() for p in f.root.iterdir()}
    journal.append("linked", f.witness)
    with pytest.raises(TransferError, match="invalid_transition"):
        journal.append("prepared", f.witness)
    assert journal.append("verified", f.witness).phase == "verified"


@pytest.mark.parametrize("change", ["key", "binding", "mapping", "manifest"])
def test_wrong_key_context_or_mapping_never_adopts_or_resets_originals(fixture, change):
    f = fixture
    f.record(f.open(create=True))
    original = {p.name: p.read_bytes() for p in f.root.iterdir()}
    options = {}
    if change == "key":
        options["unseal"] = FixtureCipher().open
    elif change == "binding":
        options["binding"] = replace(f.binding, permission_epoch="a" * 64)
    elif change == "mapping":
        options["targets"] = {f.witness.file_id: "other.jpg"}
    else:
        options["manifest"] = replace(f.manifest, source_id="2" * 32)
    with pytest.raises((TransferError, InvalidTag)):
        f.open(**options)
    assert original == {p.name: p.read_bytes() for p in f.root.iterdir()}
    with pytest.raises(FileExistsError):
        f.open(create=True)


@pytest.mark.parametrize("change", ["copied-record", "symlink", "hardlink", "unknown", "phase-gap", "corrupt"])
def test_unknown_and_modified_records_are_preserved_not_repaired_by_guessing(fixture, change):
    f = fixture
    journal = f.open(create=True)
    f.record(journal)
    path = f.root / ("linked-" + f.witness.file_id + ".enc")
    if change == "unknown":
        (f.root / "unknown").write_bytes(b"keep")
    elif change == "phase-gap":
        (f.root / ("prepared-" + f.witness.file_id + ".enc")).rename(f.parent / "held-original.enc")
    elif change == "corrupt":
        raw = bytearray(path.read_bytes()); raw[-1] ^= 1; path.write_bytes(raw)
    else:
        path.rename(f.parent / "held-original.enc")
        if change == "copied-record":
            path.write_bytes((f.parent / "held-original.enc").read_bytes())
            path.chmod(0o600)
        elif change == "symlink":
            path.symlink_to(f.parent / "held-original.enc")
        else:
            os.link(f.parent / "held-original.enc", path)
    with pytest.raises((TransferError, InvalidTag)):
        journal.inspect(f.witness.file_id)
    assert path.exists()
    # Reopening cannot erase original-file identity or authenticate a phase gap.
    with pytest.raises((TransferError, InvalidTag)):
        f.open().inspect(f.witness.file_id)
    assert path.exists()


@pytest.mark.parametrize("change", ["parent", "root"])
def test_swapped_directory_does_not_adopt_replacement(fixture, change):
    f = fixture
    journal = f.open(create=True)
    f.record(journal, "prepared")
    path = f.parent if change == "parent" else f.root
    path.rename(path.with_name(path.name + "-original"))
    path.mkdir(mode=0o700)
    (path / "unknown").write_bytes(b"keep")
    with pytest.raises(TransferError, match="changed|unsafe"):
        journal.inspect(f.witness.file_id)
    assert (path / "unknown").read_bytes() == b"keep"


@pytest.mark.parametrize("failure", ["seal", "write", "fsync", "readback"])
def test_failed_append_holds_original_files_and_blocks_further_mutations(fixture, monkeypatch, failure):
    f = fixture
    journal = f.open(create=True)
    original = {p.name: p.read_bytes() for p in f.root.iterdir()}
    def fault(*_):
        raise OSError("synthetic journal fault")
    if failure == "seal":
        monkeypatch.setattr(journal, "_seal", fault)
    elif failure == "write":
        monkeypatch.setattr(os, "write", fault)
    elif failure == "fsync":
        monkeypatch.setattr(os, "fsync", fault)
    else:
        monkeypatch.setattr(journal, "_unseal", fault)
    with pytest.raises(OSError, match="synthetic"):
        journal.append("prepared", f.witness)
    with pytest.raises(TransferError, match="recovery_read_only"):
        journal.append("prepared", f.witness)
    assert all((f.root / name).read_bytes() == raw for name, raw in original.items())
    assert (f.root / ("prepared-" + f.witness.file_id + ".enc")).exists()


def test_fresh_process_reads_protected_records_without_destination_or_transfer_permissions(fixture):
    f = fixture
    expected = f.record(f.open(create=True), "linked")
    f.close()
    script = r'''
import json, sys, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
value = json.loads(sys.stdin.read())
sys.path.insert(0, value["bin"])
from magnolie_file_transfer import FileManifest, NativeTransferBinding
from magnolie_publication_journal import ProtectedPublicationJournal
key = AESGCM(bytes.fromhex(value["key"]))
def unseal(blob, domain): return key.decrypt(blob[:12], blob[12:], domain.encode())
def no_seal(*args): raise AssertionError("inspection must not write or mint keys")
with ProtectedPublicationJournal(value["parent"], FileManifest.parse(value["manifest"]), NativeTransferBinding(**value["binding"]),
        value["targets"], no_seal, unseal, owner=value["owner"]) as journal:
    result = journal.inspect(value["file_id"])
    print(json.dumps({"phase": result.phase, "hash": result.protected_record_sha256, "saved": result.is_saved_receipt}))
'''
    process = subprocess.run([sys.executable, "-c", script], input=json.dumps({"bin": str(Path(__file__).resolve().parents[1] / "bin"),
        "key": f.cipher.raw_key.hex(), "parent": str(f.parent), "manifest": f.manifest.wire(), "binding": vars(f.binding),
        "targets": f.targets, "owner": f.owner, "file_id": f.witness.file_id}), text=True, capture_output=True, check=True, timeout=20)
    assert json.loads(process.stdout) == {"phase": "linked", "hash": expected.protected_record_sha256, "saved": False}


def test_missing_key_never_creates_replacement_defaults_or_deletes_held_data(fixture):
    f = fixture
    f.record(f.open(create=True), "prepared")
    original = {p.name: p.read_bytes() for p in f.root.iterdir()}
    with pytest.raises(TransferError, match="invalid_protection"):
        f.open(unseal=lambda *_: None)
    assert original == {p.name: p.read_bytes() for p in f.root.iterdir()}


def test_witnesses_are_strict_and_do_not_accept_boolean_or_wrong_depth_keys(fixture):
    f = fixture
    for options in ({"source_device": True}, {"source_inode": 0}, {"parent_keys": ((1, True),)}, {"parent_keys": []}):
        with pytest.raises(TransferError, match="invalid_witness"):
            replace(f.witness, **options)
    journal = f.open(create=True)
    with pytest.raises(TransferError, match="invalid_transition"):
        journal.append("prepared", replace(f.witness, parent_keys=((1, 2),)))
    assert [path.name for path in f.root.iterdir()] == ["owner.enc"]


def test_actual_publisher_records_native_original_witnesses_before_and_after_link(tmp_path):
    f = Fixture(tmp_path)
    publisher = PublisherFixture(tmp_path)
    try:
        journal = f.open(create=True)
        publisher.open(journal=journal)
        phases = []
        original_append = journal.append
        def append(phase, witness):
            phases.append((phase, publisher.target.exists()))
            return original_append(phase, witness)
        journal.append = append
        result = publisher.publish()
        assert phases == [("prepared", False), ("linked", True), ("verified", True)]
        evidence = journal.inspect(f.witness.file_id)
        assert evidence.phase == "verified"
        assert evidence.witness.source_inode == result.inode and evidence.witness.source_device == result.device
        assert evidence.witness.parent_keys == tuple((path.stat().st_dev, path.stat().st_ino)
            for path in (publisher.destination, publisher.target.parent))
        assert not result.is_saved_receipt and not evidence.is_saved_receipt
        publisher.publisher.discard_owned_cache()
        journal.close()
        assert f.open().inspect(f.witness.file_id) == evidence
        assert publisher.target.read_bytes() == b"hello"
    finally:
        publisher.close()
        f.close()


@pytest.mark.parametrize("phase", ["prepared", "linked", "verified"])
def test_journal_commit_fault_preserves_actual_publication_boundary(tmp_path, monkeypatch, phase):
    f = Fixture(tmp_path)
    publisher = PublisherFixture(tmp_path)
    try:
        journal = f.open(create=True)
        publisher.open(journal=journal)
        original_write = journal._write
        def write(name, payload):
            if name.startswith(phase + "-"):
                raise OSError("synthetic journal publication fault")
            return original_write(name, payload)
        monkeypatch.setattr(journal, "_write", write)
        with pytest.raises(OSError, match="synthetic"):
            publisher.publish()
        assert publisher.target.exists() == (phase != "prepared")
        if phase != "prepared":
            with pytest.raises(TransferError, match="repair_pending"):
                publisher.publish()
            assert publisher.target.read_bytes() == b"hello"
        publisher.current = None
        publisher.publisher.discard_owned_cache()
        journal.close()
        observed = f.open().inspect(f.witness.file_id)
        assert (observed.phase if observed else None) == {"prepared": None, "linked": "prepared", "verified": "linked"}[phase]
    finally:
        publisher.close()
        f.close()


def test_reopened_or_wrong_scope_journal_cannot_be_attached_to_new_publisher(tmp_path):
    f = Fixture(tmp_path)
    publisher = PublisherFixture(tmp_path)
    try:
        journal = f.open(create=True)
        with pytest.raises(TransferError, match="operation_mismatch"):
            publisher.open(journal=f.open(create=True, owner="2" * 32))
        journal.close()
        with pytest.raises(TransferError, match="operation_mismatch"):
            publisher.open(journal=f.open())
        assert not publisher.cache.exists()
    finally:
        publisher.close()
        f.close()
