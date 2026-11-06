"""Actual protected Saved mappings, private backup objects, versions and restore."""
from hashlib import sha256
from pathlib import Path,PurePosixPath
import os
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_media_backups import NativeMediaBackups, NativeMediaBackupLocations, NativeMediaBackupRestoreOwner,NativeMediaBackupRecoveryUi
import magnolie_media_backups as backup_module
from magnolie_media_backup_codec import NativeBackupIdlePermit, NativeBackupIdleObservation, MIN_IDLE_MS, MIN_AVAILABLE_BYTES, DAY_MS
from magnolie_media_trash import NativeMediaRetentionPermit
from magnolie_file_protection import ExistingFileTransferProtection
from magnolie_file_transfer import FileManifest, ManifestFile, TransferError, CHUNK_BYTES
from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_telefon import canonical
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

@pytest.fixture
def local_locations(tmp_path):
    root=tmp_path/'existing-private-phone';root.mkdir(mode=0o700)
    fd=os.open(root/'storage.key',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(os.urandom(32))
    default=tmp_path/'native-photo-data';default.mkdir(mode=0o700)
    parent=tmp_path/'chosen-parent';parent.mkdir(mode=0o700)
    return root,NativeAcceptedDestination.capture(default),NativeAcceptedDestination.capture(parent)

def test_local_backup_locations_passive_read_is_inert_and_choice_retains_former_parents(local_locations,tmp_path):
    root,default,parent=local_locations;scope='1'*64
    before={p.name:p.read_bytes() for p in root.iterdir()}
    with NativeMediaBackupLocations(root,scope,lambda:True) as locations:
        absent=locations.read()
        assert absent.selected is None and absent.parents==() and absent.current(default)==default
        assert before=={p.name:p.read_bytes() for p in root.iterdir()}
        chosen=locations.choose(locations.issue_action(),absent,default,parent)
        assert chosen.current(default)==parent and chosen.parents==(default,parent)
        assert not (Path(parent.path)/'Backup').exists() and not (Path(default.path)/'Backup').exists()
        same=locations.choose(locations.issue_action(),chosen,default,parent)
        assert same==chosen
        with pytest.raises(TransferError,match='cas_conflict'):
            locations.choose(locations.issue_action(),absent,default,None)
        reset=locations.choose(locations.issue_action(),same,default,None)
        assert reset.selected is None and reset.parents==chosen.parents
    # No current transport/pair/PhoneStore is available or needed for recovery metadata.
    Path(parent.path).rename(tmp_path/'offline-old-drive')
    with NativeMediaBackupLocations(root,scope,lambda:True) as reopened:
        assert reopened.read()==reset
    with NativeMediaBackupLocations(root,'2'*64,lambda:True) as videos:
        assert videos.read().parents==()
    assert (root/'storage.key').read_bytes()==before['storage.key']

def test_local_backup_locations_reject_foreign_catalog_and_backup_subtree(local_locations,tmp_path):
    root,default,parent=local_locations
    foreign=Path(parent.path)/'Backup';foreign.mkdir(mode=0o700);(foreign/'original').write_bytes(b'personal')
    with NativeMediaBackupLocations(root,'3'*64,lambda:True) as locations:
        absent=locations.read()
        with pytest.raises((OSError,TransferError)):
            locations.choose(locations.issue_action(),absent,default,parent)
        assert locations.read()==absent
        with pytest.raises(TransferError,match='subtree_excluded'):
            locations.choose(locations.issue_action(),absent,default,NativeAcceptedDestination.capture(foreign))
        assert locations.read()==absent
    assert (foreign/'original').read_bytes()==b'personal' and len(list(foreign.iterdir()))==1

def test_local_backup_locations_missing_original_and_corrupt_record_are_held(local_locations):
    from cryptography.exceptions import InvalidTag
    root,default,parent=local_locations;scope='4'*64
    with NativeMediaBackupLocations(root,scope,lambda:True) as locations:
        locations.choose(locations.issue_action(),locations.read(),default,parent)
        store=locations._store
        with store._db:
            store._db.execute('UPDATE policy SET payload=? WHERE id=1',(b'corrupt'*8,))
        with pytest.raises((TransferError,InvalidTag)):locations.read()
        name=store._name
    with NativeMediaBackupLocations(root,scope,lambda:True) as reopened:
        with pytest.raises((TransferError,InvalidTag)):reopened.read()
    (root/name).rename(root/(name+'-preserved'))
    with NativeMediaBackupLocations(root,scope,lambda:True) as reopened:
        with pytest.raises(TransferError,match='original_required'):reopened.read()
        with pytest.raises(TransferError,match='original_required'):
            reopened.choose(reopened.issue_action(),backup_module.NativeBackupLocationsSnapshot('0'*64,1,None,()),default,None)
    assert (root/(name+'-preserved')).is_dir() and not (root/name).exists()

def test_local_backup_locations_revoked_native_owner_and_expired_action_cannot_choose(local_locations):
    root,default,parent=local_locations;allowed=[True];clock=[10]
    with NativeMediaBackupLocations(root,'5'*64,lambda:allowed[0],monotonic_ms=lambda:clock[0]) as locations:
        absent=locations.read();action=locations.issue_action();clock[0]+=60000
        with pytest.raises(TransferError,match='action_not_current'):locations.choose(action,absent,default,parent)
        allowed[0]=False
        with pytest.raises(TransferError,match='local_owner_changed'):locations.read()
        assert len(list(root.iterdir()))==1

def test_local_backup_locations_close_keeps_owned_descriptors_until_active_operation_ends(local_locations):
    root,default,parent=local_locations
    locations=NativeMediaBackupLocations(root,'6'*64,lambda:True)
    chosen=locations.choose(locations.issue_action(),locations.read(),default,parent)
    store=locations._store;fd=store._db_fd
    with store._operation():
        assert locations.close() is False
        assert os.fstat(fd) and not store.local_protection._closed
    assert store.local_protection._closed and store._db_fd is None
    with NativeMediaBackupLocations(root,'6'*64,lambda:True) as reopened:assert reopened.read()==chosen

def test_local_backup_locations_replacement_parent_is_not_silently_recaptured(local_locations,tmp_path):
    root,default,parent=local_locations;scope='7'*64
    with NativeMediaBackupLocations(root,scope,lambda:True) as locations:
        chosen=locations.choose(locations.issue_action(),locations.read(),default,parent)
        Path(parent.path).rename(tmp_path/'original-parent-held');Path(parent.path).mkdir(mode=0o700)
        assert locations.read()==chosen
        with pytest.raises(TransferError,match='destination_changed'):
            locations.choose(locations.issue_action(),chosen,default,parent)
        assert not (Path(parent.path)/'Backup').exists()
        assert locations.read()==chosen

def test_alternative_storage_keeps_original_data_scope_and_old_catalog_separate(mappings,tmp_path):
    fixture,store=mappings;raw=b'original JPEG with EXIF remains unchanged'
    record=save_native(fixture,store,raw,count=1)[0]
    protection=fixture[3]._authority.protection
    with NativeMediaBackups(record.destination,protection,lambda:True,create=True) as default:
        original=default.save_from_mappings(store,record.association,record.protected_record_sha256)
        assert default.scope==sha256(canonical(record.destination.wire())).hexdigest()
    folder=fixture[4]/'Backup';before={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
    parent=tmp_path/'alternative-parent';parent.mkdir(mode=0o700)
    storage=NativeAcceptedDestination.capture(parent)
    with NativeMediaBackups(record.destination,protection,lambda:True,create=True,storage_parent=storage) as alternative:
        assert alternative.scope==sha256(canonical(storage.wire())).hexdigest() and alternative.versions()==()
        assert not list((parent/'Backup').glob('object-*'))
        saved=alternative.save_from_mappings(store,record.association,record.protected_record_sha256)
        assert saved.object_key==original.object_key and len(list((parent/'Backup').glob('object-*.raw')))==1
        assert (fixture[4]/record.relative_path).read_bytes()==raw
    assert before=={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
    with NativeMediaBackups(record.destination,protection,lambda:True,storage_parent=record.destination) as legacy:
        assert legacy.versions()==(original,) and (folder/'.owner.seal').read_bytes()==before['.owner.seal']

def test_alternative_backup_reads_and_restores_after_original_data_directory_is_gone(mappings,tmp_path):
    fixture,store=mappings;raw=b'PC original bytes for later phone recovery'
    record=save_native(fixture,store,raw,count=1)[0];protection=fixture[3]._authority.protection
    parent=tmp_path/'retained-backups';parent.mkdir(mode=0o700);storage=NativeAcceptedDestination.capture(parent)
    with NativeMediaBackups(record.destination,protection,lambda:True,create=True,storage_parent=storage) as owner:
        selected=owner.save_from_mappings(store,record.association,record.protected_record_sha256)
    data=fixture[4];moved=data.with_name(data.name+'-held-for-test');data.rename(moved)
    try:
        with pytest.raises((TransferError,FileNotFoundError)):record.destination.verify()
        with NativeMediaBackups(record.destination,protection,lambda:True,storage_parent=storage) as owner:
            assert owner.versions()==(selected,)
            target=tmp_path/'new-recovered-original.jpg'
            fd=os.open(target,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:owner.restore(selected,fd)
            finally:os.close(fd)
            assert target.read_bytes()==raw and not data.exists()
            with pytest.raises((TransferError,FileNotFoundError)):
                owner.save_from_mappings(store,record.association,record.protected_record_sha256)
    finally:moved.rename(data)
    assert (data/record.relative_path).read_bytes()==raw

def test_alternative_parent_never_adopts_foreign_backup_or_a_backup_subtree(mappings,tmp_path):
    fixture,store=mappings;record=save_native(fixture,store,b'original',count=1)[0]
    parent=tmp_path/'foreign-parent';parent.mkdir(mode=0o700);folder=parent/'Backup';folder.mkdir(mode=0o700)
    foreign=folder/'personal.jpg';foreign.write_bytes(b'foreign original')
    storage=NativeAcceptedDestination.capture(parent)
    with pytest.raises(FileExistsError):
        NativeMediaBackups(record.destination,fixture[3]._authority.protection,lambda:True,create=True,storage_parent=storage)
    with pytest.raises(TransferError,match='media_backup_subtree_excluded'):
        NativeMediaBackups(record.destination,fixture[3]._authority.protection,lambda:True,create=True,
            storage_parent=NativeAcceptedDestination.capture(folder))
    assert list(folder.iterdir())==[foreign] and foreign.read_bytes()==b'foreign original'

def test_local_backup_history_uses_exact_retained_source_offline_and_never_falls_back(mappings,tmp_path):
    fixture,store=mappings;raw=b'original recoverable after phone trash and source are gone'
    record=save_native(fixture,store,raw,count=1)[0]
    directory=fixture[3]._authority.binding.native_directory;scope='8'*64
    path=tmp_path/'historical-backup-parent';path.mkdir(mode=0o700);parent=NativeAcceptedDestination.capture(path)
    with NativeMediaBackupLocations(directory,scope,lambda:True) as locations:
        chosen=locations.choose(locations.issue_action(),locations.read(),record.destination,parent)
        with NativeMediaBackups(record.destination,fixture[3]._authority.protection,lambda:True,
                create=True,storage_parent=parent) as backups:
            version=backups.save_from_mappings(store,record.association,record.protected_record_sha256)
        reset=locations.choose(locations.issue_action(),chosen,record.destination,None)
        source_id=locations.source_id(parent)
        assert source_id!=locations.source_id(record.destination)
    fixture[3].close() # Actual transport/preference/mapping authority is gone.
    data=fixture[4];moved=data.with_name(data.name+'-held-for-local-history');data.rename(moved)
    try:
        with NativeMediaBackupLocations(directory,scope,lambda:True) as offline:
            assert offline.read()==reset
            assert (source_id,parent) in offline.sources(record.destination)
            assert offline.versions(record.destination,source_id)==(version,)
            target=tmp_path/'new-offline-recovery.jpg'
            fd=os.open(target,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:offline.restore(record.destination,source_id,version,fd)
            finally:os.close(fd)
            assert target.read_bytes()==raw and not data.exists() and offline.read()==reset
            with pytest.raises(TransferError,match='source_not_retained'):
                offline.versions(record.destination,'0'*64)
            path.rename(tmp_path/'unavailable-historical-drive')
            with pytest.raises((OSError,TransferError)):offline.versions(record.destination,source_id)
            assert offline.read()==reset
    finally:moved.rename(data)
    assert (data/record.relative_path).read_bytes()==raw

def test_native_backup_picker_preflight_and_choice_preserve_grants_and_require_exact_cas(receiving,tmp_path):
    fixture=receiving;connection=fixture[3];prepared(fixture)
    before=connection._preferences.read();grant=connection._preferences.local_grant(True).grants
    sent=fixture[2].send.call_count
    first=connection.native_backup_locations('images')
    assert first['is_default'] and first['current_path']==str(fixture[4]/'Backup')
    path=tmp_path/'native-backup-picker-selection';path.mkdir(mode=0o700)
    chosen=connection.native_backup_locations('images',operation='choose',version=first['version'],
        book_version=first['book_version'],native_path=str(path))
    assert not chosen['is_default'] and chosen['current_path']==str(path/'Backup') and len(chosen['sources'])==2
    assert not list(path.iterdir()) and not (fixture[4]/'Backup').exists()
    with pytest.raises(TransferError,match='cas_conflict'):
        connection.native_backup_locations('images',operation='default',version=first['version'],book_version=first['book_version'])
    reset=connection.native_backup_locations('images',operation='default',version=chosen['version'],book_version=chosen['book_version'])
    assert reset['is_default'] and reset['sources']==chosen['sources']
    assert connection._preferences.read()==before and connection._preferences.local_grant(True).grants==grant
    assert fixture[2].send.call_count==sent and connection._album_worker is None

def test_native_backup_picker_rejects_saved_book_turnover_during_dialog(receiving,tmp_path):
    from magnolie_media_retention import NativeMediaRetention
    from magnolie_telefon import strict_json
    connection=receiving[3];prepared(receiving)
    first=connection.native_backup_locations('images');directory=Path(connection._authority.binding.native_directory)
    with NativeMediaRetention(directory) as policy:
        token=policy.pause();policy.publish_saved(token,strict_json((directory.parent/'daten.json').read_bytes()))
    path=tmp_path/'choice-after-another-save';path.mkdir(mode=0o700)
    with pytest.raises(TransferError,match='saved_book_changed'):
        connection.native_backup_locations('images',operation='choose',version=first['version'],
            book_version=first['book_version'],native_path=str(path))
    after=connection.native_backup_locations('images')
    assert after['version']==first['version'] and after['sources']==first['sources'] and after['book_version']!=first['book_version']
    assert not list(path.iterdir())

@pytest.fixture
def local_restore(mappings,tmp_path):
    fixture,store=mappings;raw=b'original JPEG or MP4 bytes for native publication'
    record=save_native(fixture,store,raw,count=1)[0]
    directory=fixture[3]._authority.binding.native_directory;scope='9'*64
    parent_path=tmp_path/'local-restore-source';parent_path.mkdir(mode=0o700);parent=NativeAcceptedDestination.capture(parent_path)
    locations=NativeMediaBackupLocations(directory,scope,lambda:True)
    locations.choose(locations.issue_action(),locations.read(),record.destination,parent)
    with NativeMediaBackups(record.destination,fixture[3]._authority.protection,lambda:True,create=True,storage_parent=parent) as backups:
        version=backups.save_from_mappings(store,record.association,record.protected_record_sha256)
    target=tmp_path/'new-native-data-destination';target.mkdir(mode=0o700)
    try:yield fixture,record,raw,directory,scope,locations,locations.source_id(parent),version,NativeAcceptedDestination.capture(target)
    finally:locations.close()

def test_local_backup_restore_publishes_new_file_offline_with_original_lineage_and_no_overwrite(local_restore):
    fixture,record,raw,directory,scope,locations,source,version,target=local_restore
    original=Path(target.path)/Path(record.relative_path).name;original.write_bytes(b'personal edited original')
    fixture[3].close()
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as owner:
        assert owner.history()==()
        data=fixture[4];held=data.with_name(data.name+'-held-during-publication');data.rename(held)
        try:result=owner.restore(owner.issue_action(),locations,record.destination,source,version,target)
        finally:held.rename(data)
        assert result.state=='restored' and result.original_mapping==record
        assert not result.is_saved_receipt and not result.grants_write_authority
        assert (Path(target.path)/result.name).read_bytes()==raw
        assert original.read_bytes()==b'personal edited original'
        assert not list(Path(target.path).glob('.magnolie-restore-*'))
        assert owner.history()==(result,)
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as reopened:assert reopened.history()==(result,)

@pytest.mark.parametrize('stop_at',('prepared','copied','published'))
def test_local_backup_restore_resumes_exact_owned_candidate_after_interruption(local_restore,stop_at,monkeypatch):
    _,record,raw,directory,scope,locations,source,version,target=local_restore
    def boundary(phase):
        if phase==stop_at:raise RuntimeError('explicit simulated process interruption')
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True,boundary=boundary) as owner:
        with pytest.raises(RuntimeError,match='simulated'):
            owner.restore(owner.issue_action(),locations,record.destination,source,version,target)
        prepared=owner.history()[0];assert prepared.state=='prepared'
        before=tuple(Path(target.path).iterdir());assert len(before)==1
        inode=before[0].stat().st_ino
    if stop_at in ('copied','published'):
        monkeypatch.setattr(NativeMediaBackups,'restore',lambda *args:pytest.fail('Verified complete or published candidate was recopied'))
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as reopened:
        result=reopened.restore(reopened.issue_action(),locations,record.destination,source,version,target)
        assert result.operation==prepared.operation and result.file_key==prepared.file_key
        published=Path(target.path)/result.name
        assert published.stat().st_ino==inode and published.read_bytes()==raw
        assert tuple(Path(target.path).iterdir())==(published,) and reopened.history()==(result,)

def test_local_backup_restore_collision_preserves_both_foreign_target_and_prepared_bytes(local_restore):
    _,record,raw,directory,scope,locations,source,version,target=local_restore
    # Inject the collision at the filesystem boundary without any journal reentry.
    def boundary(phase):
        if phase=='copied':
            stage=next(Path(target.path).glob('.magnolie-restore-*.part'))
            operation=stage.name[len('.magnolie-restore-'):-len('.part')]
            leaf=PurePosixPath(version.name).name
            extension=PurePosixPath(leaf).suffix
            stem=leaf[:-len(extension)] if extension else leaf
            (Path(target.path)/(stem[:40]+' - restored '+operation+extension)).write_bytes(b'foreign file')
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True,boundary=boundary) as owner:
        with pytest.raises(FileExistsError):owner.restore(owner.issue_action(),locations,record.destination,source,version,target)
        assert owner.history()[0].state=='prepared'
        values=[path.read_bytes() for path in Path(target.path).iterdir()]
        assert sorted(values)==sorted([raw,b'foreign file'])

def test_local_backup_restore_replaced_stage_is_held_without_mutating_foreign_bytes(local_restore):
    _,record,_,directory,scope,locations,source,version,target=local_restore
    def boundary(phase):
        if phase=='prepared':
            stage=next(Path(target.path).glob('.magnolie-restore-*.part'))
            stage.rename(stage.with_suffix('.original-held'))
            stage.write_bytes(b'foreign replacement');stage.chmod(0o600)
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True,boundary=boundary) as owner:
        with pytest.raises(TransferError,match='original_candidate_required'):
            owner.restore(owner.issue_action(),locations,record.destination,source,version,target)
        assert owner.history()[0].state=='prepared'
    before={p.name:p.read_bytes() for p in Path(target.path).iterdir()}
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as reopened:
        with pytest.raises(TransferError,match='original_candidate_required'):
            reopened.restore(reopened.issue_action(),locations,record.destination,source,version,target)
    assert {p.name:p.read_bytes() for p in Path(target.path).iterdir()}==before

def test_local_backup_restore_revocation_stops_before_publication_and_preserves_prepared_history(local_restore):
    _,record,raw,directory,scope,locations,source,version,target=local_restore;allowed=[True]
    def boundary(phase):
        if phase=='copied':allowed[0]=False
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:allowed[0],boundary=boundary) as owner:
        with pytest.raises(TransferError,match='local_owner_changed'):
            owner.restore(owner.issue_action(),locations,record.destination,source,version,target)
    stages=tuple(Path(target.path).iterdir());assert len(stages)==1 and stages[0].suffix=='.part' and stages[0].read_bytes()==raw
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as fresh:
        assert fresh.history()[0].state=='prepared'
        result=fresh.restore(fresh.issue_action(),locations,record.destination,source,version,target)
        assert (Path(target.path)/result.name).read_bytes()==raw

def test_local_backup_restore_missing_journal_and_corrupt_lineage_are_not_reset(local_restore):
    from cryptography.exceptions import InvalidTag
    _,record,raw,directory,scope,locations,source,version,target=local_restore
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as owner:
        result=owner.restore(owner.issue_action(),locations,record.destination,source,version,target)
        journal=owner._journal;name=journal._name
        with journal._db:journal._db.execute('UPDATE policy SET payload=? WHERE id=1',(b'corrupt'*8,))
        with pytest.raises((TransferError,InvalidTag)):owner.history()
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as reopened:
        with pytest.raises((TransferError,InvalidTag)):reopened.history()
    folder=Path(directory)/name;held=folder.with_name(name+'-preserved');folder.rename(held)
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as reopened:
        with pytest.raises(TransferError,match='original_required'):reopened.history()
        with pytest.raises(TransferError,match='original_required'):
            reopened.restore(reopened.issue_action(),locations,record.destination,source,version,target)
    assert not folder.exists() and held.exists() and (Path(target.path)/result.name).read_bytes()==raw

def test_local_backup_restore_stale_version_and_expired_native_action_create_no_target(local_restore):
    from dataclasses import replace
    _,record,_,directory,scope,locations,source,version,target=local_restore;clock=[1]
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True,monotonic_ms=lambda:clock[0]) as owner:
        with pytest.raises(TransferError,match='stale_selection'):
            owner.restore(owner.issue_action(),locations,record.destination,source,replace(version,record_sha256='0'*64),target)
        action=owner.issue_action();clock[0]+=60000
        with pytest.raises(TransferError,match='action_not_current'):
            owner.restore(action,locations,record.destination,source,version,target)
        assert owner.history()==() and not list(Path(target.path).iterdir())
        assert not (Path(directory)/owner._journal._name).exists()

def test_local_backup_recovery_discovers_offline_sources_without_opening_drives_then_publishes_exact_version(local_restore,tmp_path):
    fixture,record,raw,directory,_,locations,source,version,target=local_restore
    fixture[3].close()
    data=fixture[4];held_data=data.with_name(data.name+'-offline');data.rename(held_data)
    parent=next(parent for key,parent in locations.sources(record.destination) if key==source)
    drive=Path(parent.path);held_drive=drive.with_name(drive.name+'-offline');drive.rename(held_drive)
    try:
        recovery=NativeMediaBackupRecoveryUi(directory,lambda:True)
        before=locations.read();rows=recovery.sources()
        chosen=next(row for row in rows if row['source_id']==source)
        assert chosen['path']==str(drive/'Backup') and chosen['scope']==locations._store._scope
        assert locations.read()==before
        with pytest.raises((OSError,TransferError)):recovery.versions(chosen['scope'],source)
        held_drive.rename(drive)
        page=recovery.versions(chosen['scope'],source)
        assert page['entries']==[dict(id=version.id,name=version.name,saved_ms=version.saved_ms,record_sha256=version.record_sha256)]
        assert page['next_cursor'] is None and page['total']==1
        with pytest.raises(TransferError,match='stale_selection'):
            recovery.restore(chosen['scope'],source,version.id,'0'*64,target)
        assert not list(Path(target.path).iterdir())
        result=recovery.restore(chosen['scope'],source,version.id,version.record_sha256,target)
        assert result.original_mapping==record and (Path(target.path)/result.name).read_bytes()==raw
        assert locations.read()==before
    finally:
        if held_drive.exists():held_drive.rename(drive)
        held_data.rename(data)

def test_local_backup_recovery_missing_original_anchor_is_held_not_empty_or_recreated(local_restore):
    _,_,_,directory,_,locations,_,_,_=local_restore
    anchor=Path(directory)/locations._store._anchor
    preserved=anchor.with_name(anchor.name+'-preserved');anchor.rename(preserved)
    before=set(Path(directory).iterdir())
    with pytest.raises(TransferError,match='original_required'):
        NativeMediaBackupRecoveryUi(directory,lambda:True).sources()
    assert set(Path(directory).iterdir())==before and not anchor.exists() and preserved.exists()

@pytest.mark.parametrize('empty_anchor',(False,True))
def test_local_backup_recovery_reads_legacy_default_without_pair_or_new_location_metadata(mappings,tmp_path,empty_anchor):
    fixture,store=mappings;raw=b'legacy default backup original bytes'
    record=save_native(fixture,store,raw,count=1)[0];connection=fixture[3]
    directory=connection._authority.binding.native_directory
    with NativeMediaBackups(record.destination,connection._authority.protection,lambda:True,create=True) as backups:
        version=backups.save_from_mappings(store,record.association,record.protected_record_sha256)
    outer=sha256(canonical(dict(subject=connection._preferences._subject,media_type='images'))).hexdigest()
    scope=sha256(canonical(dict(local_backup_scope=outer))).hexdigest()
    if empty_anchor:
        with NativeMediaBackupLocations(directory,outer,lambda:True) as choice:
            stale=backup_module.NativeBackupLocationsSnapshot('0'*64,1,None,())
            with pytest.raises(TransferError,match='cas_conflict'):
                choice.choose(choice.issue_action(),stale,record.destination,None)
            assert choice.read().parents==()
    connection.close()
    location_paths=tuple(Path(directory).glob('media-backup-locations-v1-*'))
    assert bool(location_paths) is empty_anchor
    before={p.name:p.read_bytes() for p in Path(directory).iterdir() if p.is_file()}
    recovery=NativeMediaBackupRecoveryUi(directory,lambda:True)
    rows=recovery.sources();row=next(row for row in rows if row['scope']==scope)
    assert row['path']==str(fixture[4]/'Backup') and before=={p.name:p.read_bytes() for p in Path(directory).iterdir() if p.is_file()}
    assert recovery.versions(scope,row['source_id'])['entries'][0]['id']==version.id
    target=tmp_path/'legacy-restored-data';target.mkdir(mode=0o700)
    result=recovery.restore(scope,row['source_id'],version.id,version.record_sha256,NativeAcceptedDestination.capture(target))
    assert (target/result.name).read_bytes()==raw and result.original_mapping==record
    assert tuple(Path(directory).glob('media-backup-locations-v1-*'))==location_paths

def test_local_backup_recovery_absent_native_root_does_not_create_keys_or_default_directories(tmp_path):
    root=tmp_path/'unconfigured-phone-root'
    assert NativeMediaBackupRecoveryUi(root,lambda:True).sources()==()
    assert not root.exists()

def test_local_backup_recovery_corrupt_legacy_policy_is_held_without_resetting_valid_catalog(local_restore):
    from cryptography.exceptions import InvalidTag
    fixture,record,raw,directory,_,locations,source,version,target=local_restore
    prefs=fixture[3]._preferences
    with prefs._db:prefs._db.execute('UPDATE policy SET payload=? WHERE id=1',(b'corrupt'*8,))
    fixture[3].close()
    recovery=NativeMediaBackupRecoveryUi(directory,lambda:True)
    with pytest.raises((TransferError,InvalidTag)):recovery.sources()
    # Explicit known anchored recovery remains independent of an unrelated
    # damaged legacy policy. Neither source gets adopted, erased or reset.
    scope=locations._store._scope
    result=recovery.restore(scope,source,version.id,version.record_sha256,target)
    assert result.original_mapping==record and (Path(target.path)/result.name).read_bytes()==raw


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


@pytest.mark.parametrize('alternative',(False,True))
def test_actual_desktop_worker_backs_up_after_end_and_unchanged_pass_does_not_copy_again(receiving,tmp_path,alternative):
    fixture=receiving;connection=fixture[3]
    # receiving supplies the actual fixed saved-book file/policy used by the
    # application, not an independent retention flag or backup permit.
    full=prepared(fixture)[0]
    connection.desktop_session()
    default=NativeAcceptedDestination.capture(fixture[4]);storage=default
    prefs=connection._preferences.read()
    if alternative:
        path=tmp_path/'actual-worker-alternative';path.mkdir(mode=0o700);storage=NativeAcceptedDestination.capture(path)
        scope=sha256(canonical(dict(subject=connection._preferences._subject,media_type='images'))).hexdigest()
        with NativeMediaBackupLocations(connection._authority.binding.native_directory,scope,lambda:True) as locations:
            locations.choose(locations.issue_action(),locations.read(),default,storage)
        assert connection._preferences.read()==prefs
    result=cycle(fixture,full)[0]
    assert result['state']=='complete',result
    folder=Path(storage.path)/'Backup';objects=tuple(folder.glob('object-*.raw'))
    assert len(objects)==1 and objects[0].read_bytes()==b'hello'
    if alternative:assert not (fixture[4]/'Backup').exists()
    association=PhotoMappingAssociation('c'*64,sha256(b'worker-photo-0').hexdigest(),'images')
    _,(record,)=connection._mappings.lookup((association,))
    with NativeMediaBackups(record.destination,connection._authority.protection,lambda:True,storage_parent=storage) as backups:
        versions=backups.versions();assert versions
    before={path.name:(path.stat().st_ino,path.stat().st_size) for path in folder.iterdir() if path.name.startswith('object-')}
    assert cycle(fixture,full)[0]['state']=='complete'
    assert {path.name:(path.stat().st_ino,path.stat().st_size) for path in folder.iterdir() if path.name.startswith('object-')}==before
    with NativeMediaBackups(record.destination,connection._authority.protection,lambda:True,storage_parent=storage) as backups:
        assert backups.versions()==versions
