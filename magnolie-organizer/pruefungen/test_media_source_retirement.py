"""Actual completed sender + local version proof to no-loss private archival."""
from dataclasses import replace
from pathlib import Path
import os
import sqlite3
import threading

import pytest

from test_media_source_cache import freeze
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_source_sender import offered,acceptance,request,saved,deliver
from test_media_source_backup import open_backup,restore
from magnolie_media_source_backup import backup_prepared_source
from magnolie_media_source_retirement import _NativeSourceRetirement
import magnolie_media_source_retirement as retirement_module
from magnolie_media_source import NativeMappedMediaSource
from magnolie_file_transfer import TransferError
from magnolie_media_retention import NativeMediaRetention
from magnolie_photo_destination import media_path_is_excluded


@pytest.fixture
def completed(source):
    h=source;sender,cached,offer=offered(h)
    accepted=acceptance(sender,cached,offer);deliver(h,sender,accepted)
    deliver(h,sender,request(accepted,cached));assert h.wire.receive()['kind']=='file_transfer.chunk'
    deliver(h,sender,saved(accepted,cached))
    with open_backup(h) as backups:
        version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
        try:yield h,sender,cached,backups,version
        finally:sender.close()


def archive_path(h,sender,cached):
    return cached.directory.with_name('.magnolie-source-'+sender._jobs._scope[:32]+'-'+cached.manifest.source_id+'.retired')


def test_completed_native_sender_and_verified_backup_archive_without_loss_then_admit_a_new_explicit_job(completed,tmp_path):
    h,sender,cached,backups,version=completed;before={p.name:(p.stat().st_ino,p.read_bytes()) for p in cached.directory.iterdir()}
    owner=_NativeSourceRetirement(sender,backups,version);result=owner.run();archive=archive_path(h,sender,cached)
    assert result.body['state']=='archived' and not cached.directory.exists()
    assert (archive.stat().st_dev,archive.stat().st_ino)==cached.root_key
    assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before
    assert not result.grants_read_authority and not result.is_saved_receipt and not result.permits_deletion and not result.permits_slot_reuse
    assert media_path_is_excluded(archive) and media_path_is_excluded(archive/'nested'/'original.jpg')
    with pytest.raises(TransferError,match='prepared_owner_required'):
        with h.source.prepared_cache(cached.manifest.source_id):pytest.fail('Archived preparation regained READ')
    h.target.write_bytes(b'explicitly selected second PC version');second=freeze(h)
    assert second.manifest.source_id!=cached.manifest.source_id and second.manifest.transfer_id!=cached.manifest.transfer_id
    assert second.root_key!=cached.root_key and second.original_references=={second.manifest.files[0].id:h.record.phone_original_reference()}
    assert sender._jobs.lookup(cached.manifest.source_id).version==cached._job_version
    assert len(sender._jobs._catalog.lookup().body['members'])==4 # Old job, exchange, retirement and new job.
    restore(backups,version,tmp_path/'first-source-version.jpg');assert (tmp_path/'first-source-version.jpg').read_bytes()==b'hello'
    assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before


def test_local_backup_alone_cannot_retire_a_sender_without_actual_correlated_peer_completion(source):
    h=source;sender,cached,offer=offered(h)
    try:
        with open_backup(h) as backups:
            version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
            owner=_NativeSourceRetirement(sender,backups,version)
            with pytest.raises(TransferError,match='actual_completed_sender_required'):owner.run()
            assert owner._journal.lookup(sender._job) is None and cached.directory.exists()
    finally:sender.close()


@pytest.mark.parametrize('change',['old_saved_mapping','stale_source_version'])
def test_peer_saved_is_not_a_local_backup_and_stale_or_saved_only_proof_cannot_retire(completed,change):
    h,sender,cached,backups,version=completed
    if change=='old_saved_mapping':version=backups.save_from_mappings(h.mappings,h.association,h.record.protected_record_sha256)
    else:version=replace(version,record_sha256='f'*64)
    owner=_NativeSourceRetirement(sender,backups,version)
    with pytest.raises(TransferError):owner.run()
    assert owner._journal.lookup(sender._job) is None and cached.directory.exists() and h.target.read_bytes()==b'hello'


def test_copied_partner_completion_metadata_is_not_a_native_retirement_owner(completed):
    _,sender,cached,backups,version=completed
    with pytest.raises(TransferError,match='native_completed_owner_required'):_NativeSourceRetirement(sender.observation(),backups,version)
    assert cached.directory.exists()


@pytest.mark.parametrize('phase',['source_retirement_planned','source_retirement_moved'])
def test_interrupted_retirement_keeps_all_bytes_and_holds_before_any_second_source_job(completed,phase):
    h,sender,cached,backups,version=completed;before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    def stop(current):
        if current==phase:owner.close()
    owner=_NativeSourceRetirement(sender,backups,version,boundary=stop)
    with pytest.raises(TransferError,match='live_lease_required'):owner.run()
    assert owner._journal.lookup(sender._job).body['state']=='archive_planned'
    retained=cached.directory if phase=='source_retirement_planned' else archive_path(h,sender,cached)
    assert {p.name:p.read_bytes() for p in retained.iterdir()}==before
    other=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    try:
        with pytest.raises(TransferError,match='cache_existing_hold|slot_pending_job'):freeze(h,other)
    finally:other.close()
    assert {p.name:p.read_bytes() for p in retained.iterdir()}==before


def test_foreign_archive_collision_never_overwrites_either_foreign_bytes_or_original_cache(completed):
    h,sender,cached,backups,version=completed;before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    archive=archive_path(h,sender,cached);archive.mkdir(mode=0o700);foreign=archive/'personal-data';foreign.write_bytes(b'keep foreign bytes')
    owner=_NativeSourceRetirement(sender,backups,version)
    with pytest.raises(FileExistsError):owner.run()
    assert owner._journal.lookup(sender._job).body['state']=='archive_planned'
    assert foreign.read_bytes()==b'keep foreign bytes' and {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before


@pytest.mark.parametrize('change',['missing_archive','changed_proof','missing_member','missing_exchange','linked_chunk','changed_approved_exchange'])
def test_completed_archive_history_is_not_adopted_when_physical_or_catalog_evidence_is_lost(completed,change):
    h,sender,cached,backups,version=completed;owner=_NativeSourceRetirement(sender,backups,version);owner.run()
    archive=archive_path(h,sender,cached)
    if change=='missing_archive':archive.rename(archive.with_name('held-original-archive'))
    elif change=='changed_proof':
        path=archive/'manifest.enc';raw=path.read_bytes();path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    elif change=='linked_chunk':os.link(archive/'chunk-00000000.enc',archive.parent/'held-extra-cipher-link')
    elif change=='changed_approved_exchange':
        jobs=sender._jobs;key_name=sender._journal._key
        with jobs._database() as (db,key):
            db.execute('BEGIN IMMEDIATE');catalog=jobs._catalog.verify(db,key)
            cipher=db.execute('SELECT value FROM meta WHERE key=?',(key_name,)).fetchone()[0]
            plain=h.authority.protection.unseal(cipher,key_name)
            db.execute('UPDATE meta SET value=? WHERE key=?',(h.authority.protection.seal(plain,key_name),key_name))
            jobs._catalog.advance(db,key,catalog)
    else:
        with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
            key=sender._journal._key if change=='missing_exchange' else owner._journal._prefix+sender._job
            db.execute('DELETE FROM meta WHERE key=?',(key,))
    h.target.write_bytes(b'a second source must remain held')
    with pytest.raises(TransferError):freeze(h)
    assert not cached.directory.exists() and h.target.read_bytes()==b'a second source must remain held'


def test_cancel_during_native_archive_move_keeps_book_os_lane_until_the_real_move_ends(completed,monkeypatch):
    h,sender,cached,backups,version=completed;entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[]
    move=retirement_module._move_no_replace
    def blocked(*args,**kwargs):entered.set();assert release.wait(8);return move(*args,**kwargs)
    monkeypatch.setattr(retirement_module,'_move_no_replace',blocked)
    owner=_NativeSourceRetirement(sender,backups,version)
    def run():
        try:owner.run()
        except BaseException as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=run);worker.start()
    try:
        assert entered.wait(5);owner.close();assert not ended.is_set()
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as lease:assert lease is None
    finally:release.set();worker.join(5)
    assert ended.is_set() and not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
    assert owner._journal.lookup(sender._job).body['state']=='archive_planned' and archive_path(h,sender,cached).exists()
    with NativeMediaRetention(h.authority.binding.native_directory) as retention:
        with retention.activity() as lease:assert lease is not None


def test_native_source_consent_withdrawal_after_retirement_intent_stops_before_archive_move(completed):
    h,sender,cached,backups,version=completed
    def revoke(phase):
        if phase=='source_retirement_planned':
            h.preferences.configure_sending(h.preferences.issue_action(),h.policy,photos=False,videos=False)
    owner=_NativeSourceRetirement(sender,backups,version,boundary=revoke)
    with pytest.raises(TransferError,match='local_consent_required'):owner.run()
    assert cached.directory.exists() and not archive_path(h,sender,cached).exists()
    assert owner._journal.lookup(sender._job).body['state']=='archive_planned'


def test_backup_changed_during_retirement_never_completes_slot_release_and_keeps_original_archive(completed):
    h,sender,cached,backups,version=completed;before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    def corrupt(phase):
        if phase=='source_retirement_planned':
            with backups._operation():obj=backups._record('objects',version.object_key)
            (Path(backups.storage_parent.path)/'Backup'/obj['name']).write_bytes(b'corrupted fixture bytes')
    owner=_NativeSourceRetirement(sender,backups,version,boundary=corrupt)
    with pytest.raises(TransferError,match='original_content_changed'):owner.run()
    archive=archive_path(h,sender,cached)
    assert {p.name:p.read_bytes() for p in archive.iterdir()}==before
    assert owner._journal.lookup(sender._job).body['state']=='archive_planned'
    with pytest.raises(TransferError,match='slot_pending_job'):freeze(h)
    assert not cached.directory.exists() and h.target.read_bytes()==b'hello'


def test_disappeared_complete_stage_is_not_a_free_slot_without_native_retirement_record(source):
    h=source;cached=freeze(h);held=cached.directory.with_name('held-complete-source-with-no-retirement')
    cached.directory.rename(held);before={p.name:p.read_bytes() for p in held.iterdir()}
    with pytest.raises(TransferError,match='slot_pending_job'):freeze(h)
    assert not cached.directory.exists() and {p.name:p.read_bytes() for p in held.iterdir()}==before


def test_unknown_scoped_archive_is_not_inventory_or_permission_to_initialize_another_job(source):
    from magnolie_media_source_jobs import _NativeSourceJobs
    h=source;jobs=_NativeSourceJobs(h.authority);root=Path(h.authority.binding.native_directory)
    foreign=root/('.magnolie-source-'+jobs._scope[:32]+'-'+'e'*32+'.retired')
    foreign.mkdir(mode=0o700);(foreign/'personal-data').write_bytes(b'keep unknown original bytes')
    with pytest.raises(TransferError,match='slot_unknown_stage'):freeze(h)
    assert (foreign/'personal-data').read_bytes()==b'keep unknown original bytes' and jobs._catalog.lookup() is None
    assert not list(root.glob('.magnolie-source-*.part'))


def test_recoverable_pending_source_intent_sharing_a_complete_saved_object_is_not_completed_backup_approval(completed):
    from magnolie_telefon import canonical
    h,sender,cached,backups,version=completed
    original=backups.save_from_mappings(h.mappings,h.association,h.record.protected_record_sha256)
    # Construct a correctly authenticated pending-only catalog state. This is
    # a semantic boundary fixture, not a claim of a physical catalog rollback.
    # Unlike an interrupted source read, it does not revoke the live sender.
    with backups._operation():
        body=backups._record('versions',version.id);revision=backups._verify()
        blob=backups.protection.seal(canonical(body),backups._domain+'pending/'+version.id)
        backups._db.execute('BEGIN IMMEDIATE')
        try:
            backups._db.execute('DELETE FROM versions WHERE id=?',(version.id,))
            backups._db.execute('INSERT INTO meta VALUES(?,?)',('pending-'+version.id,blob))
            backups._write_membership(revision+1);backups._db.commit();backups._verify()
        except BaseException:backups._db.rollback();raise
    pending=backups.pending_recovery_versions()
    assert pending==(version,) and backups.versions()==(original,) and pending[0].object_key==original.object_key
    assert not h.source._prepared[sender._job].failed.is_set()
    owner=_NativeSourceRetirement(sender,backups,pending[0])
    with pytest.raises(TransferError,match='complete_local_backup_required'):owner.run()
    assert owner._journal.lookup(sender._job) is None and cached.directory.exists()
