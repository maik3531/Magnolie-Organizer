"""Restart observations read actual original destination bytes, never apply."""
from dataclasses import replace
from pathlib import Path
import os
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_file_publish import inspect_publication_destination
from magnolie_file_transfer import TransferError
from magnolie_publication_journal import ProtectedPublicationJournal
from test_file_transfer_stage import FixtureCipher
from test_file_publish import Fixture


class RecoveryFixture(Fixture):
    def __init__(self, root):
        super().__init__(root)
        self.journal_parent = root / "journals"
        self.journal_parent.mkdir(mode=0o700)
        self.cipher = FixtureCipher()
        self.targets = {self.file.id: self.file.path}
        self.journal = self.open_journal(create=True)
        self.open(journal=self.journal)

    def open_journal(self, create=False):
        return ProtectedPublicationJournal(self.journal_parent, self.manifest, self.binding, self.targets,
            self.cipher.seal, self.cipher.open, owner="1" * 32, create=create)

    def restart(self):
        self.publisher.close()
        self.journal.close()
        self.journal = self.open_journal()

    def inspect(self, **options):
        args = dict(destination=self.destination, manifest=self.manifest, binding=self.binding, targets=self.targets,
            journal=self.journal, file_id=self.file.id, current_binding=lambda: self.current)
        args.update(options)
        return inspect_publication_destination(**args)

    def close(self):
        self.journal.close()
        super().close()


@pytest.fixture
def fixture(tmp_path):
    f = RecoveryFixture(tmp_path)
    try:
        yield f
    finally:
        f.close()


@pytest.mark.parametrize("keep_cache", [True, False])
def test_restart_original_readback_without_source_or_journal_mutation(fixture, keep_cache):
    f = fixture
    f.publish()
    if not keep_cache:
        f.publisher.discard_owned_cache()
    f.restart()
    before = {p.name: p.read_bytes() for p in f.journal_parent.glob("*/*")}
    # Staged source removal must not cause a live-source reopen or fallback.
    f.stage.cleanup()
    result = f.inspect()
    assert result.state == "original_present" and result.journal_phase == "verified"
    assert not result.is_saved_receipt and not result.grants_write_authority
    assert before == {p.name: p.read_bytes() for p in f.journal_parent.glob("*/*")}
    assert f.target.read_bytes() == b"hello"


@pytest.mark.parametrize("state", ["absent", "same-bytes-new-inode", "edited", "parent-swap", "symlink", "extra-hardlink", "missing-root"])
def test_restart_missing_or_changed_destination_is_preserved_and_never_repaired(fixture, state):
    f = fixture
    f.publish()
    f.publisher.discard_owned_cache()
    f.restart()
    if state == "absent":
        f.target.rename(f.root / "held-personal.jpg")
    elif state == "same-bytes-new-inode":
        f.target.rename(f.root / "held-personal.jpg")
        f.target.write_bytes(b"hello"); f.target.chmod(0o600)
    elif state == "edited":
        f.target.write_bytes(b"other")
    elif state == "parent-swap":
        f.target.parent.rename(f.destination / "original-photos")
        f.target.parent.mkdir(mode=0o700)
        f.target.write_bytes(b"hello"); f.target.chmod(0o600)
    elif state == "symlink":
        held = f.root / "held-personal.jpg"
        f.target.rename(held)
        f.target.symlink_to(held)
    elif state == "extra-hardlink":
        os.link(f.target, f.root / "extra-link.jpg")
        os.link(f.target, f.root / "second-extra-link.jpg")
    else:
        f.destination.rename(f.root / "held-destination")
    result = f.inspect()
    assert result.state == ("unconfirmed_absence" if state in {"absent", "missing-root"} else "conflict_preserved")
    assert not result.is_saved_receipt and not result.grants_write_authority
    assert not f.cache.exists()
    if state == "edited":
        assert f.target.read_bytes() == b"other"
    elif state in {"absent", "missing-root"}:
        assert not f.target.exists()


@pytest.mark.parametrize("phase", ["prepared-only", "prepared-with-real-link", "linked"])
def test_incomplete_journal_never_implies_a_link_did_not_happen(fixture, monkeypatch, phase):
    f = fixture
    original_append = f.journal.append
    def append(actual, witness):
        if actual == {"prepared-only": "linked", "prepared-with-real-link": "linked", "linked": "verified"}[phase]:
            raise OSError("synthetic journal interruption")
        return original_append(actual, witness)
    monkeypatch.setattr(f.journal, "append", append)
    if phase == "prepared-only":
        def gate(_, action):
            # Only this test's publication link is stopped: parent mkdir has
            # already been completed before this replacement gate is installed.
            raise OSError("synthetic journal interruption")
        f.target.parent.mkdir(mode=0o700)
        f.gate = gate
    with pytest.raises(OSError, match="synthetic"):
        f.publish()
    f.restart()
    result = f.inspect()
    assert result.journal_phase == ("linked" if phase == "linked" else "prepared")
    assert result.state == ("unconfirmed_absence" if phase == "prepared-only" else "original_present")
    assert not result.is_saved_receipt and not result.grants_write_authority


def test_no_record_is_not_permission_to_publish_and_scope_mismatch_is_rejected(fixture):
    f = fixture
    result = f.inspect()
    assert result.state == "no_record" and result.journal_phase is None and not f.target.exists()
    with pytest.raises(TransferError, match="context_mismatch"):
        f.inspect(binding=replace(f.binding, permission_epoch="a" * 64))
    with pytest.raises(TransferError, match="context_mismatch"):
        f.inspect(targets={f.file.id: "other.jpg"})


def test_revocation_before_or_during_observation_never_returns_stale_evidence(fixture, monkeypatch):
    f = fixture
    f.publish()
    f.restart()
    f.current = None
    with pytest.raises(TransferError, match="binding_revoked"):
        f.inspect()
    f.current = f.binding
    original_read = __import__("magnolie_file_publish")._read_original_data
    def read(*args, **kwargs):
        result = original_read(*args, **kwargs)
        f.current = None
        return result
    monkeypatch.setattr("magnolie_file_publish._read_original_data", read)
    with pytest.raises(TransferError, match="binding_revoked"):
        f.inspect()


def test_relative_destination_is_rejected_even_if_missing(fixture):
    f = fixture
    f.publish()
    f.restart()
    with pytest.raises(TransferError, match="canonical_destination_required"):
        f.inspect(destination=Path("not-a-native-absolute-destination"))
