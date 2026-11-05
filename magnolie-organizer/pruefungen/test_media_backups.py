"""Actual protected Saved mappings, private backup objects, versions and restore."""
from hashlib import sha256
from pathlib import Path
import os
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_media_backups import NativeMediaBackups
import magnolie_media_backups as backup_module
from magnolie_media_backup_codec import NativeBackupIdlePermit, NativeBackupIdleObservation, MIN_IDLE_MS, MIN_AVAILABLE_BYTES, DAY_MS
from magnolie_media_trash import NativeMediaRetentionPermit
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import FileManifest, ManifestFile, TransferError, CHUNK_BYTES
from magnolie_photo_mappings import PhotoMappingAssociation
from test_file_authenticated_desktop import native, bind
from test_file_desktop_receive import receiving, chunk
from test_file_desktop_sources import ready_source
from test_file_desktop_media import collect, send_offer, dispatch
from test_photo_mappings import mappings
from test_file_desktop_album_worker import prepared
from test_photo_version_workflow import cycle, changed


def save_native(fixture, store, raw, count=2):
    connection = fixture[3]; ready_source(fixture)
    full = FileManifest('1' * 32, '2' * 32, fixture[1]['device_id'], fixture[0].store.identity['device_id'],
        tuple(ManifestFile(f'{index + 1:032x}', f'Camera/photo{index}.jpg', len(raw), sha256(raw).hexdigest()) for index in range(count)), len(raw) * count)
    collect(fixture, full); offered, result = send_offer(fixture, full); dispatch(fixture, result)
    connection.accept_pending_offer(connection.issue_receive_action(), offered['message_id'])
    for file in full.files:
        for offset in range(0, len(raw), CHUNK_BYTES):
            dispatch(fixture, chunk(connection.request_next_chunk(), raw[offset:offset + CHUNK_BYTES]))
    action = connection.issue_receive_action(); connection._take_action(action); connection._mutation_action = action
    try:
        receiver = connection._run.receiver
        receiver.publish_completed(); receiver.commit_saved_receipts()
    finally: connection._mutation_action = None
    _, records = store.commit_received(store.issue_action(), store.read(), receiver, connection._source_media_pages)
    return records


def idle():
    return NativeBackupIdlePermit(lambda: NativeBackupIdleObservation(MIN_IDLE_MS, 0, MIN_AVAILABLE_BYTES), lambda: True)


@pytest.fixture
def vault(mappings, request):
    fixture, store = mappings
    raw = os.urandom(48 * 1024) if getattr(request, 'param', None) == 'random' else b'original JPEG bytes including EXIF\0' * 1600
    records = save_native(fixture, store, raw)
    now = [1_800_000_000_000]
    owner = NativeMediaBackups(records[0].destination, fixture[3]._authority.protection, lambda: True, create=True, clock_ms=lambda: now[0])
    try: yield fixture, store, records, owner, raw, now
    finally: owner.close()


def add_all(vault):
    _, mappings, records, owner, _, _ = vault
    return tuple(owner.save_from_mappings(mappings, record.association, record.protected_record_sha256) for record in records)


def test_identical_saved_files_with_different_names_share_one_verified_object_and_keep_versions(vault):
    fixture, mappings, records, owner, raw, now = vault
    versions = add_all(vault)
    assert len(owner.versions()) == len(versions) == 2
    assert versions[0].object_key == versions[1].object_key and versions[0].id != versions[1].id
    folder = fixture[4] / 'Backup'
    objects = list(folder.glob('object-*.raw'))
    assert len(objects) == 1 and objects[0].read_bytes() == raw
    assert objects[0].stat().st_nlink == 1
    assert all(objects[0].stat().st_ino != (fixture[4] / record.relative_path).stat().st_ino for record in records)
    now[0] += DAY_MS
    assert owner.save_from_mappings(mappings, records[0].association, records[0].protected_record_sha256) == versions[0]
    assert len(list(folder.glob('object-*.raw'))) == 1 and owner.versions() == tuple(sorted(versions, key=lambda item: item.id))
    assert versions[0].saved_ms != now[0] and not versions[0].grants_write_authority


def test_old_verified_objects_compress_once_and_all_versions_restore_without_overwrite(vault, tmp_path):
    fixture, _, records, owner, raw, now = vault
    versions = add_all(vault); before = owner.versions()
    now[0] += 31 * DAY_MS
    assert owner.compress_one(versions[0].object_key, idle(), NativeMediaRetentionPermit(90, lambda: 90))
    assert owner.versions() == before
    folder = fixture[4] / 'Backup'
    assert list(folder.glob('object-*.raw'))[0].stat().st_size == 0
    assert len(list(folder.glob('object-*.xz'))) == 1
    for index, version in enumerate(versions):
        target = tmp_path / f'restored-{index}.jpg'
        fd = os.open(target, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            result = owner.restore(version, fd)
            assert result.codec == 'raw' and not result.grants_write_authority
            assert target.read_bytes() == raw
            with pytest.raises(TransferError): owner.restore(version, fd)
        finally: os.close(fd)
    assert all((fixture[4] / record.relative_path).read_bytes() == raw for record in records)


@pytest.mark.parametrize('days,age,expected', [(0, 31, True), (90, 30, False), (30, 31, False), (7, 31, False), (90, 91, False)])
def test_age_retention_never_and_expired_versions_do_not_get_confused(vault, days, age, expected):
    _, _, _, owner, _, now = vault
    versions = add_all(vault); now[0] += age * DAY_MS
    assert owner.compress_one(versions[0].object_key, idle(), NativeMediaRetentionPermit(days, lambda: days)) is expected
    assert owner.versions() == tuple(sorted(versions, key=lambda item: item.id))


@pytest.mark.parametrize('vault', ['random'], indirect=True)
def test_unprofitable_original_is_retained_and_never_retried_endlessly(vault):
    fixture, _, _, owner, raw, now = vault
    versions = add_all(vault); now[0] += 31 * DAY_MS
    retention = NativeMediaRetentionPermit(0, lambda: 0)
    assert not owner.compress_one(versions[0].object_key, idle(), retention)
    folder = fixture[4] / 'Backup'; names = {path.name for path in folder.iterdir()}
    assert not owner.compress_one(versions[0].object_key, idle(), retention)
    assert {path.name for path in folder.iterdir()} == names
    assert list(folder.glob('object-*.raw'))[0].read_bytes() == raw


def test_changed_saved_original_is_not_backed_up_as_an_old_unchanged_version(vault):
    fixture, mappings, records, owner, _, _ = vault
    original = fixture[4] / records[0].relative_path
    original.write_bytes(b'new PC edit is kept')
    with pytest.raises(TransferError): owner.save_from_mappings(mappings, records[0].association, records[0].protected_record_sha256)
    assert not owner.versions() and original.read_bytes() == b'new PC edit is kept'


def test_compressed_local_history_reopens_without_the_original_connection_or_source_files(vault, tmp_path):
    fixture, _, records, owner, raw, now = vault
    versions = add_all(vault); now[0] += 31 * DAY_MS
    owner.compress_one(versions[0].object_key, idle(), NativeMediaRetentionPermit(0, lambda: 0))
    destination = records[0].destination; owner.close()
    fixture[0]._end_native_file_connection(fixture[2])
    for record in records: (fixture[4] / record.relative_path).unlink()  # Synthetic test files only.
    with ExistingFileTransferProtection(fixture[0].store.root) as protection:
        with NativeMediaBackups(destination, protection, lambda: True) as reopened:
            assert reopened.versions() == tuple(sorted(versions, key=lambda item: item.id))
            target = tmp_path / 'local-restore.jpg'
            fd = os.open(target, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                reopened.restore(versions[1], fd); assert target.read_bytes() == raw
            finally: os.close(fd)


def test_corrupt_shared_object_is_not_silently_replaced_or_copied_to_restore_target(vault, tmp_path):
    fixture, mappings, records, owner, _, now = vault
    versions = add_all(vault); now[0] += 31 * DAY_MS
    owner.compress_one(versions[0].object_key, idle(), NativeMediaRetentionPermit(0, lambda: 0))
    encoded = next((fixture[4] / 'Backup').glob('object-*.xz'))
    data = bytearray(encoded.read_bytes()); data[len(data) // 2] ^= 1; encoded.write_bytes(data)
    with pytest.raises(Exception): owner.save_from_mappings(mappings, records[0].association, records[0].protected_record_sha256)
    fd = os.open(tmp_path / 'empty-restore', os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with pytest.raises(Exception): owner.restore(versions[1], fd)
        assert os.fstat(fd).st_size == 0 and encoded.read_bytes() == data
    finally: os.close(fd)


def test_unknown_backup_folder_or_missing_anchor_is_never_adopted(vault):
    fixture, _, records, owner, _, _ = vault
    protection = fixture[3]._authority.protection
    with pytest.raises(FileExistsError): NativeMediaBackups(records[0].destination, protection, lambda: True, create=True)
    folder = fixture[4] / 'Backup'; owner.close()
    before = {path.name for path in folder.iterdir()}
    (folder / '.owner.seal').rename(folder / '.owner-preserved-test')
    with pytest.raises(FileNotFoundError): NativeMediaBackups(records[0].destination, protection, lambda: True)
    assert {path.name for path in folder.iterdir()} == before - {'.owner.seal'} | {'.owner-preserved-test'}


def test_interrupted_initial_copy_recovers_only_its_registered_inode_without_copying_again(vault, monkeypatch):
    fixture, mappings, records, owner, raw, _ = vault
    original = backup_module.copy_unique
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise TransferError('fixture_copy_finished_before_version_commit')
    with monkeypatch.context() as patch:
        patch.setattr(backup_module, 'copy_unique', interrupted)
        with pytest.raises(TransferError): owner.save_from_mappings(mappings, records[0].association, records[0].protected_record_sha256)
    assert not owner.versions()
    folder = fixture[4] / 'Backup'; payload = next(folder.glob('object-*.raw')); key = payload.stat().st_ino
    assert payload.read_bytes() == raw
    with monkeypatch.context() as patch:
        patch.setattr(backup_module, 'copy_unique', lambda *args, **kwargs: pytest.fail('Completed prepared object copied again'))
        version = owner.save_from_mappings(mappings, records[0].association, records[0].protected_record_sha256)
    assert version in owner.versions() and payload.stat().st_ino == key
    assert len(list(folder.glob('object-*.raw'))) == 1


def test_interrupted_encoding_reuses_only_its_owned_candidate_and_keeps_all_versions(vault, monkeypatch):
    fixture, _, _, owner, raw, now = vault
    versions = add_all(vault); now[0] += 31 * DAY_MS
    original = backup_module.compress_candidate
    def interrupted(*args, **kwargs):
        result = original(*args, **kwargs); assert result
        raise TransferError('fixture_before_compressed_catalog_commit')
    with monkeypatch.context() as patch:
        patch.setattr(backup_module, 'compress_candidate', interrupted)
        with pytest.raises(TransferError): owner.compress_one(versions[0].object_key, idle(), NativeMediaRetentionPermit(0, lambda: 0))
    folder = fixture[4] / 'Backup'; candidate = next(folder.glob('object-*.xz')); key = candidate.stat().st_ino
    assert next(folder.glob('object-*.raw')).read_bytes() == raw
    assert owner.versions() == tuple(sorted(versions, key=lambda item: item.id))
    assert owner.compress_one(versions[0].object_key, idle(), NativeMediaRetentionPermit(0, lambda: 0))
    assert len(list(folder.glob('object-*.xz'))) == 1 and candidate.stat().st_ino == key


def test_activity_after_compressed_commit_keeps_raw_until_new_idle_attempt_finishes(vault, monkeypatch):
    fixture, _, _, owner, raw, now = vault
    versions = add_all(vault); now[0] += 31 * DAY_MS
    active = [True]
    native_idle = NativeBackupIdlePermit(lambda: NativeBackupIdleObservation(MIN_IDLE_MS, 0, MIN_AVAILABLE_BYTES), lambda: active[0])
    original = owner._verify_object
    def pause(obj):
        result = original(obj)
        if obj['codec'] == 'xz': active[0] = False
        return result
    with monkeypatch.context() as patch:
        patch.setattr(owner, '_verify_object', pause)
        with pytest.raises(TransferError): owner.compress_one(versions[0].object_key, native_idle, NativeMediaRetentionPermit(0, lambda: 0))
    folder = fixture[4] / 'Backup'
    assert next(folder.glob('object-*.raw')).read_bytes() == raw
    names = {path.name for path in folder.glob('object-*')}
    assert owner.compress_one(versions[0].object_key, idle(), NativeMediaRetentionPermit(0, lambda: 0))
    assert {path.name for path in folder.glob('object-*')} == names
    assert next(folder.glob('object-*.raw')).stat().st_size == 0


def test_close_does_not_release_native_file_descriptors_while_io_is_still_owned(vault):
    _, mappings, records, owner, _, _ = vault
    entered = threading.Event(); release = threading.Event(); errors = []
    def gate():
        if threading.current_thread() is not threading.main_thread():
            entered.set(); assert release.wait(5)
        return True
    owner._native_gate = gate
    def copy():
        try: owner.save_from_mappings(mappings, records[0].association, records[0].protected_record_sha256)
        except BaseException as error: errors.append(error)
    thread = threading.Thread(target=copy)
    try:
        thread.start(); assert entered.wait(5)
        with pytest.raises(TransferError, match='busy'): owner.close()
        with pytest.raises(TransferError, match='busy'): owner.versions()
        assert not owner._closed
    finally: release.set(); thread.join(10)
    assert not thread.is_alive() and not errors
    assert owner.versions()


def test_actual_changed_versions_remain_backuppable_after_mapping_head_advanced(receiving, tmp_path):
    fixture = receiving; connection = fixture[3]
    full = prepared(fixture)[0]
    assert cycle(fixture, full)[0]['state'] == 'complete'
    association = PhotoMappingAssociation('c' * 64, sha256(b'worker-photo-0').hexdigest(), 'images')
    _, (original,) = connection._mappings.lookup((association,))
    newer = changed(full, 'c', b'world')
    assert cycle(fixture, newer, b'world')[0]['state'] == 'complete'
    _, (current,) = connection._mappings.lookup((association,))
    assert original != current
    with NativeMediaBackups(original.destination, connection._authority.protection, lambda: True, create=True) as owner:
        old_version = owner.save_from_mappings(connection._mappings, association, original.protected_record_sha256)
        new_version = owner.save_from_mappings(connection._mappings, association, current.protected_record_sha256)
        assert old_version.object_key != new_version.object_key and len(owner.versions()) == 2
        for index, (selected, data) in enumerate(((old_version, b'hello'), (new_version, b'world'))):
            fd = os.open(tmp_path / f'version-{index}', os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                owner.restore(selected, fd); assert os.pread(fd, 10, 0) == data
            finally: os.close(fd)
        assert (fixture[4] / original.relative_path).read_bytes() == b'hello'
        assert (fixture[4] / current.relative_path).read_bytes() == b'world'
        _, (still_current,) = connection._mappings.lookup((association,))
        assert still_current == current  # Historical backup never rewinds a live mapping.


def test_existing_catalog_rejects_symlink_sidecar_without_touching_foreign_file(vault, tmp_path):
    fixture, _, records, owner, _, _ = vault
    add_all(vault); owner.close()
    foreign = tmp_path / 'unrelated-user-file'; foreign.write_bytes(b'never change this')
    sidecar = fixture[4] / 'Backup' / 'catalog.sqlite3-wal'
    assert not sidecar.exists(); sidecar.symlink_to(foreign)
    with pytest.raises(TransferError): NativeMediaBackups(records[0].destination, fixture[3]._authority.protection, lambda: True)
    assert sidecar.is_symlink() and foreign.read_bytes() == b'never change this'


def test_truncated_existing_database_is_not_silently_reinitialized(vault):
    fixture, _, records, owner, raw, _ = vault
    add_all(vault); owner.close()
    folder = fixture[4] / 'Backup'; database = folder / 'catalog.sqlite3'
    database.write_bytes(b'')
    before = {path.name for path in folder.iterdir()}
    with pytest.raises(TransferError): NativeMediaBackups(records[0].destination, fixture[3]._authority.protection, lambda: True)
    assert database.read_bytes() == b''
    assert {path.name for path in folder.iterdir()} == before
    assert all((fixture[4] / record.relative_path).read_bytes() == raw for record in records)


def test_saved_book_revocation_is_sticky_and_never_destroys_backup_records(vault):
    fixture, _, records, owner, _, _ = vault
    versions = add_all(vault); active = [True]; owner._native_gate = lambda: active[0]
    active[0] = False
    with pytest.raises(TransferError): owner.versions()
    active[0] = True
    with pytest.raises(TransferError): owner.versions()
    owner.close()
    with NativeMediaBackups(records[0].destination, fixture[3]._authority.protection, lambda: True) as fresh:
        assert fresh.versions() == tuple(sorted(versions, key=lambda item: item.id))


def test_actual_desktop_worker_backs_up_after_end_and_unchanged_pass_does_not_copy_again(receiving):
    fixture=receiving;connection=fixture[3]
    # receiving supplies the actual fixed saved-book file/policy used by the
    # application, not an independent retention flag or backup permit.
    full=prepared(fixture)[0]
    connection.desktop_session()
    result=cycle(fixture,full)[0]
    assert result['state']=='complete',result
    folder=fixture[4]/'Backup';objects=tuple(folder.glob('object-*.raw'))
    assert len(objects)==1 and objects[0].read_bytes()==b'hello'
    association=PhotoMappingAssociation('c'*64,sha256(b'worker-photo-0').hexdigest(),'images')
    _,(record,)=connection._mappings.lookup((association,))
    with NativeMediaBackups(record.destination,connection._authority.protection,lambda:True) as backups:
        versions=backups.versions();assert versions
    before={path.name:(path.stat().st_ino,path.stat().st_size) for path in folder.iterdir() if path.name.startswith('object-')}
    assert cycle(fixture,full)[0]['state']=='complete'
    assert {path.name:(path.stat().st_ino,path.stat().st_size) for path in folder.iterdir() if path.name.startswith('object-')}==before
    with NativeMediaBackups(record.destination,connection._authority.protection,lambda:True) as backups:
        assert backups.versions()==versions
