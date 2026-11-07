"""Fresh local ownership finishes existing archival intent, never raw READ."""
from pathlib import Path
import os
import sqlite3
import threading

import pytest

from test_media_source_retirement import completed,source,mappings,receiving,native,archive_path
from test_media_source_cache import freeze
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_media_source_recovery import _NativeSourceRetirementRecovery
import magnolie_media_source_recovery as recovery_module
from magnolie_media_retention import NativeMediaRetention
from magnolie_file_transfer import TransferError


def interrupted(completed,phase='source_retirement_planned'):
    h,sender,cached,backups,version=completed
    def stop(current):
        if current==phase:owner.close()
    owner=_NativeSourceRetirement(sender,backups,version,boundary=stop)
    with pytest.raises(TransferError):owner.run()
    record=owner._journal.lookup(sender._job);assert record.body['state']=='archive_planned'
    h.source.close()
    fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    return fresh,record


def recover(completed,fresh,record,**kwargs):
    h,sender,_,backups,version=completed
    return _NativeSourceRetirementRecovery(fresh,sender._job,record.version,backups,version,**kwargs)


def run(h,owner):return owner.run(h.preferences.issue_action(),h.preferences.read())


@pytest.mark.parametrize('phase',['source_retirement_planned','source_retirement_moved'])
def test_fresh_native_owner_finishes_exact_existing_intent_without_reconstructing_sender_or_unsealing_payload(completed,phase,monkeypatch):
    h,sender,cached,_,_=completed;fresh,record=interrupted(completed,phase)
    archive=archive_path(h,sender,cached);retained=cached.directory if cached.directory.exists() else archive
    before={p.name:(p.stat().st_ino,p.read_bytes()) for p in retained.iterdir()}
    owner=recover(completed,fresh,record);unseal=h.authority.protection.unseal
    def metadata_only(cipher,domain):
        if '/chunk-' in domain:pytest.fail('Recovery decrypted original cache payload')
        return unseal(cipher,domain)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(h.authority.protection,'unseal',metadata_only)
            patch.setattr(h.channel,'send',lambda *args:pytest.fail('Local archival sent network output'))
            patch.setattr(fresh,'_file',lambda *args:pytest.fail('Recovery opened original mapped media'))
            from magnolie_media_source_reader import _NativeSourceCacheReader
            patch.setattr(_NativeSourceCacheReader,'__init__',lambda *args:pytest.fail('History reconstructed raw cache READ'))
            result=run(h,owner)
        assert result.body['state']=='archived' and not result.grants_read_authority and not result.permits_slot_reuse
        assert not cached.directory.exists() and fresh._prepared=={}
        assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before
        with pytest.raises(TransferError,match='prepared_owner_required'):
            with fresh.prepared_cache(cached.manifest.source_id):pytest.fail('Old raw READ was revived')
        h.target.write_bytes(b'fresh selection after recovered archival');next_cache=freeze(h,fresh)
        assert next_cache.manifest.source_id!=cached.manifest.source_id and next_cache.root_key!=cached.root_key
        assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before
    finally:fresh.close()


@pytest.mark.parametrize('change',['consent','intent','book','renewed_book','stale_intent','missing_intent'])
def test_recovery_history_cannot_bypass_fresh_local_rights_book_or_original_intent(completed,change,monkeypatch):
    h,sender,cached,_,_=completed;fresh,record=interrupted(completed)
    owner=recover(completed,fresh,record)
    if change=='consent':h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
    elif change=='intent':h.controller.change('enabled',False)
    elif change=='book':
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:retention.pause()
    elif change=='renewed_book':
        from magnolie_telefon import strict_json
        directory=Path(h.authority.binding.native_directory)
        with NativeMediaRetention(directory) as retention:
            token=retention.pause();retention.publish_saved(token,strict_json((directory.parent/'daten.json').read_bytes()))
    elif change=='stale_intent':owner._expected_version='f'*64
    else:
        with sqlite3.connect(h.authority.binding.store_owner.database_path) as db:
            db.execute('DELETE FROM meta WHERE key=?',(owner._journal._prefix+sender._job,))
    monkeypatch.setattr(recovery_module,'verify_encrypted_source',lambda *args:pytest.fail('Invalid current ownership reached cipher IO'))
    try:
        with pytest.raises(TransferError):run(h,owner)
        assert cached.directory.exists() and fresh._prepared=={} and not archive_path(h,sender,cached).exists()
    finally:fresh.close()


@pytest.mark.parametrize('change',['cipher','same_bytes_new_inode','unknown_child','missing_stage','foreign_collision'])
def test_recovery_never_adopts_changed_or_ambiguous_cipher_layout_from_filenames(completed,change):
    h,sender,cached,_,_=completed;fresh,record=interrupted(completed);root=cached.directory
    if change=='cipher':
        path=root/'chunk-00000000.enc';raw=path.read_bytes();path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    elif change=='same_bytes_new_inode':
        path=root/'chunk-00000000.enc';raw=path.read_bytes();path.rename(root.parent/'held-original-cipher')
        path.write_bytes(raw);path.chmod(0o600)
    elif change=='unknown_child':(root/'foreign-user-data').write_bytes(b'preserve foreign data')
    elif change=='missing_stage':root.rename(root.with_name('held-original-stage'));root=root.with_name('held-original-stage')
    else:
        archive=archive_path(h,sender,cached);archive.mkdir(mode=0o700);(archive/'foreign').write_bytes(b'keep foreign archive')
    before={p.name:p.read_bytes() for p in root.iterdir()};owner=recover(completed,fresh,record)
    try:
        with pytest.raises(TransferError):run(h,owner)
        assert owner._journal.lookup(sender._job).version==record.version
        assert {p.name:p.read_bytes() for p in root.iterdir()}==before and fresh._prepared=={}
    finally:fresh.close()


def test_actual_local_source_backup_corruption_holds_recovery_before_cache_verification_or_move(completed,monkeypatch):
    h,sender,cached,backups,version=completed;fresh,record=interrupted(completed)
    with backups._operation():obj=backups._record('objects',version.object_key)
    (Path(backups.storage_parent.path)/'Backup'/obj['name']).write_bytes(b'changed local backup')
    monkeypatch.setattr(recovery_module,'verify_encrypted_source',lambda *args:pytest.fail('Unproven backup reached local archive IO'))
    owner=recover(completed,fresh,record)
    try:
        with pytest.raises(TransferError,match='original_content_changed'):run(h,owner)
        assert cached.directory.exists() and owner._journal.lookup(sender._job).version==record.version
    finally:fresh.close()


def test_cancel_during_real_cipher_io_keeps_native_book_lane_and_never_commits_recovered_archival(completed,monkeypatch):
    h,sender,cached,_,_=completed;fresh,record=interrupted(completed);owner=recover(completed,fresh,record)
    proof=(cached.directory/'manifest.enc').stat();key=proof.st_dev,proof.st_ino;pread=os.pread
    entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[]
    def blocked(fd,size,offset):
        value=os.fstat(fd)
        if (value.st_dev,value.st_ino)==key:entered.set();assert release.wait(8)
        return pread(fd,size,offset)
    monkeypatch.setattr(os,'pread',blocked);action=h.preferences.issue_action();expected=h.preferences.read()
    def work():
        try:owner.run(action,expected)
        except BaseException as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=work);worker.start()
    try:
        assert entered.wait(5);owner.close();assert not ended.is_set()
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as lease:assert lease is None
    finally:release.set();worker.join(5);fresh.close()
    assert ended.is_set() and not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
    assert owner._journal.lookup(sender._job).version==record.version and cached.directory.exists()
    with NativeMediaRetention(h.authority.binding.native_directory) as retention:
        with retention.activity() as lease:assert lease is not None


def test_completed_peer_history_and_backup_without_existing_native_retirement_intent_never_bootstrap_recovery(completed):
    h,sender,cached,backups,version=completed;fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    owner=_NativeSourceRetirementRecovery(fresh,sender._job,'f'*64,backups,version)
    try:
        with pytest.raises(TransferError,match='original_intent_required'):run(h,owner)
        assert owner._journal.lookup(sender._job) is None and cached.directory.exists() and fresh._prepared=={}
        with pytest.raises(TransferError,match='original_intent_required'):owner._journal.write(owner,None,{})
    finally:fresh.close()


def test_recovery_needs_no_original_media_file_and_returns_no_raw_read_owner(completed):
    h,sender,cached,_,_=completed;fresh,record=interrupted(completed);h.target.unlink();owner=recover(completed,fresh,record)
    try:
        result=run(h,owner)
        assert result.body['state']=='archived' and archive_path(h,sender,cached).exists() and not h.target.exists()
        assert fresh._prepared=={} and not result.grants_read_authority
        with pytest.raises((TransferError,FileNotFoundError)):freeze(h,fresh)
        assert not cached.directory.exists()
    finally:fresh.close()


def test_cancel_during_actual_recovery_rename_preserves_planned_record_and_drains_os_ownership(completed,monkeypatch):
    h,sender,cached,_,_=completed;fresh,record=interrupted(completed);owner=recover(completed,fresh,record)
    entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[];move=recovery_module._move_no_replace
    def blocked(*args,**kwargs):entered.set();assert release.wait(8);return move(*args,**kwargs)
    monkeypatch.setattr(recovery_module,'_move_no_replace',blocked);action=h.preferences.issue_action();expected=h.preferences.read()
    def work():
        try:owner.run(action,expected)
        except BaseException as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=work);worker.start()
    try:
        assert entered.wait(5);owner.close();assert not ended.is_set()
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as lease:assert lease is None
    finally:release.set();worker.join(5);fresh.close()
    assert ended.is_set() and not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
    assert owner._journal.lookup(sender._job).version==record.version and archive_path(h,sender,cached).exists()
    with NativeMediaRetention(h.authority.binding.native_directory) as retention:
        with retention.activity() as lease:assert lease is not None
