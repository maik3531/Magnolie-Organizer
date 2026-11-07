"""Exact actual completed retry -> no-loss archive / metadata-only recovery."""
import threading

import pytest

from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_source_sender import offered,handshake,deliver,request,saved
from test_media_source_retry import fresh_acceptance,original_bytes
from test_media_source_cache import freeze
from test_media_source_backup import open_backup
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_media_source_backup import backup_prepared_source
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_media_source_recovery import _NativeSourceRetirementRecovery
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_retention import NativeMediaRetention
from magnolie_file_transfer import TransferError
import magnolie_media_source_retirement as retirement_module


@pytest.fixture
def retry_completed(source):
    h=source;old,cached,_=offered(h)
    sender=_NativeMediaSourceSender.retry(h.source,cached.manifest.source_id,old.observation().version)
    try:
        handshake(h,sender);offer=sender.send_offer();h.wire.receive();accepted=fresh_acceptance(sender,cached,offer)
        deliver(h,sender,accepted);deliver(h,sender,request(accepted,cached));h.wire.receive();deliver(h,sender,saved(accepted,cached))
        with open_backup(h) as backups:
            version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
            yield h,old,sender,cached,backups,version
    finally:sender.close();old.close()


def interrupt(case,phase):
    h,_,sender,_,backups,version=case
    def stop(current):
        if current==phase:owner.close()
    owner=_NativeSourceRetirement(sender,backups,version,boundary=stop)
    with pytest.raises(TransferError):owner.run()
    record=owner._journal.lookup(sender._job)
    assert record.body['format']==2 and record.body['state']=='archive_planned'
    h.source.close();fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    return fresh,record


def recovery(case,fresh,record):
    _,_,sender,_,backups,version=case
    return _NativeSourceRetirementRecovery(fresh,sender._job,record.version,backups,version)


def run(h,owner):return owner.run(h.preferences.issue_action(),h.preferences.read())


def test_actual_completed_retry_archives_exact_history_and_all_cipher_bytes_then_allows_fresh_job(retry_completed):
    h,old,sender,cached,backups,version=retry_completed
    before={p.name:(p.stat().st_ino,p.read_bytes()) for p in cached.directory.iterdir()};original=original_bytes(h,old)
    retry=sender._journal.history();result=_NativeSourceRetirement(sender,backups,version).run();body=result.body
    archive=cached.directory.parent/body['archive']
    assert body['format']==2 and body['retry_version']==retry.version and body['retry_attempt_id']==sender._journal._attempt
    assert body['exchange_version']==old.observation().version and original_bytes(h,old)==original
    assert sender._journal.history()==retry and {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before
    assert not cached.directory.exists() and not result.grants_read_authority and not result.permits_slot_reuse
    second=freeze(h);assert second.manifest.source_id!=cached.manifest.source_id
    assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before


@pytest.mark.parametrize('phase',['source_retirement_planned','source_retirement_moved'])
def test_fresh_metadata_only_recovery_preserves_retry_pins_without_reconstructing_sender_or_raw_read(retry_completed,phase,monkeypatch):
    h,_,sender,cached,_,_=retry_completed;fresh,record=interrupt(retry_completed,phase)
    retained=cached.directory if cached.directory.exists() else cached.directory.parent/record.body['archive']
    before={p.name:(p.stat().st_ino,p.read_bytes()) for p in retained.iterdir()}
    try:
        from magnolie_media_source_reader import _NativeSourceCacheReader
        unseal=h.authority.protection.unseal
        def metadata_only(cipher,domain):
            if '/chunk-' in domain:pytest.fail('Recovery decrypted original cache payload')
            return unseal(cipher,domain)
        with monkeypatch.context() as patch:
            patch.setattr(_NativeSourceCacheReader,'__init__',lambda *args:pytest.fail('Recovery reconstructed raw cache READ'))
            patch.setattr(h.channel,'send',lambda *args:pytest.fail('Recovery emitted network output'))
            patch.setattr(h.authority.protection,'unseal',metadata_only)
            result=run(h,recovery(retry_completed,fresh,record))
        assert result.body==dict(record.body,state='archived') and fresh._prepared=={}
        archive=cached.directory.parent/result.body['archive']
        assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==before
        with pytest.raises(TransferError,match='retirement_held'):sender._journal.require_owner()
        second=freeze(h,fresh);assert second.manifest.source_id!=cached.manifest.source_id
    finally:fresh.close()


@pytest.mark.parametrize('change',['retry_resealed','retry_missing','other_attempt','original_only_approval'])
def test_changed_or_missing_retry_pins_never_become_archive_recovery_or_new_slot(retry_completed,change):
    from magnolie_telefon import canonical,strict_json
    h,_,sender,cached,_,_=retry_completed;fresh,record=interrupt(retry_completed,'source_retirement_planned')
    jobs=sender._jobs;name=sender._journal._key if change.startswith('retry_') else jobs._catalog._retirement+sender._job
    with jobs._database() as (db,key):
        db.execute('BEGIN IMMEDIATE');head=jobs._catalog.verify(db,key)
        if change=='retry_missing':db.execute('DELETE FROM meta WHERE key=?',(name,))
        else:
            cipher=db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()[0]
            plain=h.authority.protection.unseal(cipher,name)
            if change in ('other_attempt','original_only_approval'):
                body=strict_json(plain)
                if change=='other_attempt':body['retry_attempt_id']='f'*32
                else:body['format']=1;body.pop('retry_attempt_id');body.pop('retry_version')
                plain=canonical(body)
            db.execute('UPDATE meta SET value=? WHERE key=?',(h.authority.protection.seal(plain,name),name))
        # Correctly authenticate semantic test state, not a physical rollback claim.
        jobs._catalog.advance(db,key,head)
    selected=record if change.startswith('retry_') else retirement_module._NativeSourceRetirementJournal(jobs).lookup(sender._job)
    before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    try:
        with pytest.raises(TransferError):run(h,recovery(retry_completed,fresh,selected))
        assert fresh._prepared=={} and {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before
        with pytest.raises(TransferError):freeze(h,fresh)
    finally:fresh.close()


def test_cancel_during_actual_retry_archive_move_holds_os_lane_until_real_io_ends(retry_completed,monkeypatch):
    h,_,sender,cached,backups,version=retry_completed
    entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[];move=retirement_module._move_no_replace
    def blocked(*args,**kwargs):entered.set();assert release.wait(8);return move(*args,**kwargs)
    monkeypatch.setattr(retirement_module,'_move_no_replace',blocked);owner=_NativeSourceRetirement(sender,backups,version)
    def work():
        try:owner.run()
        except BaseException as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=work);worker.start()
    try:
        assert entered.wait(5);owner.close();assert not ended.is_set()
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as lease:assert lease is None
    finally:release.set();worker.join(5)
    assert ended.is_set() and not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
    record=owner._journal.lookup(sender._job)
    assert record.body['state']=='archive_planned' and (cached.directory.parent/record.body['archive']).exists()
    with pytest.raises(TransferError,match='retirement_held'):sender._journal.require_owner()


def test_pending_only_local_source_backup_cannot_approve_completed_retry_even_when_bytes_deduplicate(retry_completed):
    from magnolie_telefon import canonical
    h,_,sender,cached,backups,version=retry_completed
    original=backups.save_from_mappings(h.mappings,h.association,h.record.protected_record_sha256)
    # Authenticated semantic pending-only fixture, not physical rollback evidence.
    with backups._operation():
        value=backups._record('versions',version.id);revision=backups._verify()
        cipher=backups.protection.seal(canonical(value),backups._domain+'pending/'+version.id)
        backups._db.execute('BEGIN IMMEDIATE')
        try:
            backups._db.execute('DELETE FROM versions WHERE id=?',(version.id,))
            backups._db.execute('INSERT INTO meta VALUES(?,?)',('pending-'+version.id,cipher))
            backups._write_membership(revision+1);backups._db.commit();backups._verify()
        except BaseException:backups._db.rollback();raise
    assert backups.pending_recovery_versions()==(version,) and version.object_key==original.object_key
    owner=_NativeSourceRetirement(sender,backups,version)
    with pytest.raises(TransferError,match='complete_local_backup_required'):owner.run()
    assert owner._journal.lookup(sender._job) is None and cached.directory.exists()


def test_foreign_archive_collision_preserves_both_cache_and_foreign_bytes_and_cannot_reuse_active_permit(retry_completed):
    h,_,sender,cached,backups,version=retry_completed
    archive=cached.directory.with_name('.magnolie-source-'+sender._jobs._scope[:32]+'-'+sender._job+'.retired')
    archive.mkdir(mode=0o700);(archive/'personal-data').write_bytes(b'preserve foreign bytes')
    before={p.name:p.read_bytes() for p in cached.directory.iterdir()};owner=_NativeSourceRetirement(sender,backups,version)
    with pytest.raises(FileExistsError):owner.run()
    record=owner._journal.lookup(sender._job)
    assert record.body['state']=='archive_planned' and not owner._permits_retry_record(record)
    # Even the same old typed object cannot revive a permit after actual drain.
    sender._active.retirement=owner
    try:
        with pytest.raises(TransferError,match='retirement_held'):sender._journal.require_owner()
    finally:sender._active.retirement=None
    assert {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before
    assert (archive/'personal-data').read_bytes()==b'preserve foreign bytes'


def test_second_original_repreparation_checks_earlier_exact_retry_archive_without_rebuilding_sender(retry_completed):
    h,_,sender,cached,backups,version=retry_completed
    result=_NativeSourceRetirement(sender,backups,version).run();archive=cached.directory.parent/result.body['archive']
    before={p.name:p.read_bytes() for p in archive.iterdir()}
    h.target.write_bytes(b'new explicit second original');second=freeze(h);h.source.close()
    fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    try:
        renewed=fresh.reprepare(h.preferences.issue_action(),h.preferences.read(),h.association,h.record.protected_record_sha256,
            second.manifest.source_id,second._job_version)
        with fresh.prepared_cache(renewed.manifest.source_id) as reader:assert reader.read_chunk(0)==b'new explicit second original'
        assert {p.name:p.read_bytes() for p in archive.iterdir()}==before
    finally:fresh.close()
