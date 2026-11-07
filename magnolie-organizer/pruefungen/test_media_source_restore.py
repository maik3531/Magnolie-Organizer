"""Existing native recovery publication of distinct source-version lineage."""
from hashlib import sha256

import pytest

from test_media_source_cache import freeze
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_source_backup import open_backup
from magnolie_media_source_backup import backup_prepared_source
from magnolie_media_backups import NativeMediaBackupLocations,NativeMediaBackupRestoreOwner,NativeMediaBackupRecoveryUi
from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_transfer import TransferError
from magnolie_telefon import canonical


def prepare(h):
    raw=b'PC edited version distinct from old phone Saved\x00'*1800;h.target.write_bytes(raw);cached=freeze(h)
    with open_backup(h) as backups:version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
    scope='d'*64;directory=h.authority.binding.native_directory;default=h.record.destination
    with NativeMediaBackupLocations(directory,scope,lambda:True) as locations:
        locations.choose(locations.issue_action(),locations.read(),default,None)
    return raw,version,scope,directory,default


def test_existing_recovery_ui_publishes_source_version_offline_and_exports_only_original_completed_lineage(source,tmp_path):
    h=source;raw,version,scope,directory,default=prepare(h);h.source.close();h.target.unlink()
    internal=sha256(canonical(dict(local_backup_scope=scope))).hexdigest();source_id=NativeMediaBackupLocations.source_id(default)
    recovery=NativeMediaBackupRecoveryUi(directory,lambda:True);page=recovery.versions(internal,source_id)
    assert [entry['id'] for entry in page['entries']]==[version.id]
    assert recovery.selection(internal,source_id,version.id,version.record_sha256)==(version,h.record)
    destination=tmp_path/'restore';destination.mkdir(mode=0o700)
    result=recovery.restore(internal,source_id,version.id,version.record_sha256,NativeAcceptedDestination.capture(destination))
    assert result.state=='restored' and (destination/result.name).read_bytes()==raw
    assert result.original_mapping==h.record and result.source_version['id']==version.id and not result.is_saved_receipt
    assert result.file_key!=h.record.file_key and not result.grants_write_authority
    copy=result.source_version;copy['source']['original_mapping']['saved_sha256']='e'*64
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as journal:
        assert journal.history()==(result,)
        assert journal.phone_original_reference(result.operation)==h.record.phone_original_reference()


@pytest.mark.parametrize('phase',['prepared','published'])
def test_source_restore_resumes_exact_candidate_without_duplicating_or_replacing_original_lineage(source,tmp_path,phase):
    h=source;raw,version,scope,directory,default=prepare(h);h.source.close()
    destination=tmp_path/'restore';destination.mkdir(mode=0o700);target=NativeAcceptedDestination.capture(destination)
    def stop(current):
        if current==phase:raise RuntimeError('explicit source restore interruption')
    with NativeMediaBackupLocations(directory,scope,lambda:True) as locations:
        source_id=locations.source_id(default)
        with NativeMediaBackupRestoreOwner(directory,scope,lambda:True,boundary=stop) as owner:
            with pytest.raises(RuntimeError,match='source restore interruption'):
                owner.restore(owner.issue_action(),locations,default,source_id,version,target)
            before=owner.history();assert len(before)==1 and before[0].state=='prepared'
            with pytest.raises(TransferError,match='completed_history_required'):owner.phone_original_reference(before[0].operation)
        with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as resumed:
            result=resumed.restore(resumed.issue_action(),locations,default,source_id,version,target)
            assert result.operation==before[0].operation and result.file_key==before[0].file_key
            assert result.original_mapping==h.record and result.source_version==before[0].source_version
            assert resumed.history()==(result,) and (destination/result.name).read_bytes()==raw
        assert len(list(destination.iterdir()))==1


def test_source_restore_foreign_name_collision_preserves_foreign_file_and_registered_candidate(source,tmp_path):
    h=source;raw,version,scope,directory,default=prepare(h)
    destination=tmp_path/'restore';destination.mkdir(mode=0o700);target=NativeAcceptedDestination.capture(destination)
    def collide(phase):
        if phase=='copied':
            staged=next(destination.glob('.magnolie-restore-*.part'))
            operation=staged.name[len('.magnolie-restore-'):-len('.part')]
            from pathlib import PurePosixPath
            leaf=PurePosixPath(version.name).name;extension=PurePosixPath(leaf).suffix
            stem=leaf[:-len(extension)] if extension else leaf
            (destination/(stem[:40]+' - restored '+operation+extension)).write_bytes(b'foreign file must remain')
    with NativeMediaBackupLocations(directory,scope,lambda:True) as locations:
        with NativeMediaBackupRestoreOwner(directory,scope,lambda:True,boundary=collide) as owner:
            with pytest.raises((FileExistsError,TransferError)):
                owner.restore(owner.issue_action(),locations,default,locations.source_id(default),version,target)
            record=owner.history()[0]
            assert record.state=='prepared' and (destination/record.name).read_bytes()==b'foreign file must remain'
            assert next(destination.glob('.magnolie-restore-*.part')).read_bytes()==raw


@pytest.mark.parametrize('change',['content','lineage'])
def test_source_restore_history_cannot_change_current_bytes_or_original_source_version_proof(source,tmp_path,change):
    h=source;raw,version,scope,directory,default=prepare(h)
    destination=tmp_path/'restore';destination.mkdir(mode=0o700);target=NativeAcceptedDestination.capture(destination)
    with NativeMediaBackupLocations(directory,scope,lambda:True) as locations:
        with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as owner:
            result=owner.restore(owner.issue_action(),locations,default,locations.source_id(default),version,target)
            journal=owner._journal;_,events,_=journal._snapshot()
            for event in events:
                if change=='content':event['sha256']='f'*64
                else:event['source_version']['source']['proof_sha256']='f'*64
            # Even a correctly resealed but semantically changed native record
            # cannot bypass exact source-version identity/content validation.
            blob=journal._protect(events,'restores')
            head=journal._protect(dict(revision=len(events)+1,restores_sha256=sha256(blob).hexdigest()),'owner')
            with journal._db:
                journal._db.execute('UPDATE policy SET payload=? WHERE id=1',(blob,))
                journal._db.execute('UPDATE owner SET payload=? WHERE id=1',(head,))
            with pytest.raises(TransferError):owner.history()
            with pytest.raises(TransferError):owner.phone_original_reference(result.operation)
            assert (destination/result.name).read_bytes()==raw
