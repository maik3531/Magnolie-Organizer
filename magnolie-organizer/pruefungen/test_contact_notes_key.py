"""Existing-key adapter: owned synthetic files only, no PhoneStore or keyring."""
import hashlib
import hmac
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from test_contact_notes_consent import Harness, native
from magnolie_contact_notes_key import NativeNotesExistingJournalKey


def seed(root, key=b'S' * 32):
    root.mkdir(mode=0o700)
    (root / 'storage.key').write_bytes(key); (root / 'storage.key').chmod(0o600)
    (root / 'identity.json').write_bytes(b'Never read or reconstruct this synthetic identity')
    return root / 'storage.key'


@pytest.mark.parametrize('mode', ['missing-root', 'missing-key', 'stable', 'short', 'long', 'shared-root', 'shared-key',
    'symlink-root', 'symlink-key', 'hardlink-key', 'fifo-key', 'directory-key', 'changed-read', 'deleted-read', 'same-key-replaced', 'raw-clearing',
    'root-ownership', 'key-ownership', 'changed-root'])
def test_read_only_key_backend_does_not_create_or_repair_state_and_holds_unsafe_inputs(tmp_path, monkeypatch, mode):
    root = tmp_path / 'phone'
    backend = NativeNotesExistingJournalKey(str(root))
    if mode == 'missing-root':
        assert backend.read_existing() is None and not root.exists()
        return
    key = seed(root)
    if mode == 'missing-key':
        key.unlink(); before = set(root.iterdir())
        assert backend.read_existing() is None and set(root.iterdir()) == before
        return
    if mode == 'short': key.write_bytes(b'S' * 31)
    if mode == 'long': key.write_bytes(b'S' * 33)
    if mode == 'shared-root': root.chmod(0o750)
    if mode == 'shared-key': key.chmod(0o640)
    if mode == 'symlink-root':
        real = tmp_path / 'other-owned-phone'; root.rename(real); root.symlink_to(real, target_is_directory=True)
    if mode == 'symlink-key':
        real = root / 'other-owned-key'; key.rename(real); key.symlink_to(real)
    if mode == 'hardlink-key': os.link(key, root / 'other-owned-key')
    if mode == 'fifo-key': key.unlink(); os.mkfifo(key, 0o600)
    if mode == 'directory-key': key.unlink(); key.mkdir(mode=0o700)
    if mode in ('root-ownership', 'key-ownership'):
        # Synthetic stat mismatch only; never chown a real file or need privilege.
        inode = (root if mode == 'root-ownership' else key).stat().st_ino
        fstat = os.fstat
        def wrong_owner(fd):
            value = fstat(fd)
            if value.st_ino != inode: return value
            changed = SimpleNamespace(**{name: getattr(value, name) for name in ('st_mode', 'st_nlink', 'st_uid', 'st_dev',
                'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')})
            changed.st_uid += 100000
            return changed
        monkeypatch.setattr(os, 'fstat', wrong_owner)
    captured = []
    derive = HKDF.derive
    def derive_and_capture(self, value):
        captured.append(value)
        result = derive(self, value)
        if mode == 'deleted-read': key.unlink()
        if mode in ('changed-read', 'same-key-replaced'):
            other = root / 'replacement-owned-key'
            other.write_bytes(b'K' * 32 if mode == 'changed-read' else b'S' * 32); other.chmod(0o600)
            os.replace(other, key)
        if mode == 'changed-root':
            root.rename(tmp_path / 'old-owned-phone'); seed(root)
        return result
    monkeypatch.setattr(HKDF, 'derive', derive_and_capture)
    before_fds = len(os.listdir('/proc/self/fd'))
    if mode in ('stable', 'raw-clearing'):
        first = backend.read_existing(); second = backend.read_existing()
        extracted = hmac.new(b'\0' * 32, b'S' * 32, hashlib.sha256).digest()
        expected = hmac.new(extracted, NativeNotesExistingJournalKey.DOMAIN + b'\1', hashlib.sha256).digest()
        assert first == second == expected and first != b'S' * 32 and first is not second
        assert {p.name for p in root.iterdir()} == {'storage.key', 'identity.json'}
        assert key.read_bytes() == b'S' * 32
    else:
        with pytest.raises((PermissionError, OSError)): backend.read_existing()
    assert len(os.listdir('/proc/self/fd')) == before_fds
    assert all(bytes(value) == b'\0' * 32 for value in captured), 'Adapter retained an owned raw-secret buffer'
    assert not (root / 'phone.db').exists() and not (root / 'identity.key').exists() and not (root / '.lock').exists()


@pytest.mark.parametrize('change', ['loss', 'replacement'])
def test_existing_journal_history_is_not_adopted_or_released_after_phone_key_change(native, monkeypatch, tmp_path, change):
    from magnolie_contact_notes_requests import NativeNotesRequestIntents
    h = Harness(native, tmp_path)
    try:
        h.configure()
        root = tmp_path / 'owned-native-phone'; key = seed(root)
        backend = NativeNotesExistingJournalKey(str(root))
        requests = NativeNotesRequestIntents(tmp_path / 'requests', backend.read_existing)
        proof = requests.seal(h.choice.pending())
        before = {p.name: p.read_bytes() for p in (tmp_path / 'requests').iterdir() if p.name != '.lock'}
        if change == 'loss': key.unlink()
        else: key.write_bytes(b'K' * 32)
        with pytest.raises(PermissionError): requests.load_held(proof.key)
        assert {p.name: p.read_bytes() for p in (tmp_path / 'requests').iterdir() if p.name != '.lock'} == before
        assert not (root / 'phone.db').exists()
        if change == 'loss': assert not key.exists()
    finally:
        h.service.anhalten()


def test_key_backend_rejects_implicit_root_and_is_shipped_by_existing_manifests():
    for value in ('relative-profile', '~/phone', '.', '/native/../phone', None):
        with pytest.raises(TypeError): NativeNotesExistingJournalKey(value)
    root = Path(__file__).resolve().parents[1]
    for name in ('debian/install', 'rpm/magnolie-organizer.spec', 'werkzeuge/appimage_bauen.sh',
            'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json'):
        assert 'magnolie_contact_notes_key.py' in (root / name).read_text()
    json.loads((root / 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json').read_text())
