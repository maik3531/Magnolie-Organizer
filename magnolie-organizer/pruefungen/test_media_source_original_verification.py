"""Original-completed readback-only verification (#419), synthetic peer inputs."""
import pytest

from test_media_source_retirement import completed
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_source_sender import handshake,deliver,acceptance,request,saved
from test_media_source_readback import readback
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_media_source_recovery import _NativeSourceRetirementRecovery
from magnolie_file_transfer import TransferError


def fresh_original(case):
    h,old,cached,_,_=case;version=old.observation().version;h.source.close()
    fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    fresh.reprepare(h.preferences.issue_action(),h.preferences.read(),h.association,h.record.protected_record_sha256,
        cached.manifest.source_id,cached._job_version)
    return fresh,version


def test_completed_original_can_only_gain_fresh_readback_verification_not_ordinary_retry_after_lease_loss(completed):
    h,old,cached,backups,backup_version=completed;original=old.observation()
    with pytest.raises(TransferError,match='fresh_repreparation_required'):
        _NativeMediaSourceSender.verify_published(h.source,cached.manifest.source_id,original.version)
    fresh,version=fresh_original(completed)
    try:
        with pytest.raises(TransferError,match='completed_held'):
            _NativeMediaSourceSender.retry(fresh,cached.manifest.source_id,version)
        verifier=_NativeMediaSourceSender.verify_published(fresh,cached.manifest.source_id,version)
        try:
            handshake(h,verifier);offer=verifier.send_offer();h.wire.receive()
            assert verifier.observation().body['format']==3 and verifier._journal.history().body['attempts'][0]['previous_head'] is None
            deliver(h,verifier,readback(verifier,cached,offer))
            retired=_NativeSourceRetirement(verifier,backups,backup_version).run()
            assert retired.body['exchange_version']==original.version and old.observation()==original
            assert (cached.directory.parent/retired.body['archive']).exists() and h.target.read_bytes()==b'hello'
        finally:verifier.close()
    finally:fresh.close()


@pytest.mark.parametrize('change',['saved_kind','missing_bits','wrong_accepted_offer','not_completed'])
def test_authenticated_original_phase_saved_alone_never_qualifies_readback_verification(completed,change):
    from magnolie_telefon import canonical,strict_json
    h,old,cached,_,_=completed;fresh,_=fresh_original(completed);jobs=old._jobs;name=old._journal._key
    try:
        with jobs._database() as (db,key):
            db.execute('BEGIN IMMEDIATE');catalog=jobs._catalog.verify(db,key)
            cipher=db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()[0]
            body=strict_json(h.authority.protection.unseal(cipher,name))
            if change=='saved_kind':body['peer_saved']['kind']='file_transfer.published.readback'
            elif change=='missing_bits':body['sent_bits']=0
            elif change=='not_completed':body['phase']='accepted'
            else:body['acceptance']['body']['offer_id']='ffffffff-ffff-4fff-8fff-ffffffffffff'
            db.execute('UPDATE meta SET value=? WHERE key=?',(h.authority.protection.seal(canonical(body),name),name))
            jobs._catalog.advance(db,key,catalog)
        selected=old.observation();before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
        with pytest.raises(TransferError):
            _NativeMediaSourceSender.verify_published(fresh,cached.manifest.source_id,selected.version)
        assert old.observation()==selected and {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before
        assert not any(member[0].startswith(jobs._catalog._retry) for member in jobs._catalog.lookup().body['members'])
    finally:fresh.close()


@pytest.mark.parametrize('phase',['source_retirement_planned','source_retirement_moved'])
def test_original_based_verification_archive_recovery_is_metadata_only_and_retains_original_completion(completed,phase,monkeypatch):
    h,old,cached,backups,backup_version=completed;original=old.observation();fresh,version=fresh_original(completed)
    verifier=_NativeMediaSourceSender.verify_published(fresh,cached.manifest.source_id,version)
    try:
        handshake(h,verifier);offer=verifier.send_offer();h.wire.receive();deliver(h,verifier,readback(verifier,cached,offer))
        def stop(current):
            if current==phase:owner.close()
        owner=_NativeSourceRetirement(verifier,backups,backup_version,boundary=stop)
        with pytest.raises(TransferError):owner.run()
        record=owner._journal.lookup(verifier._job);fresh.close()
        recovery_source=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
        try:
            from magnolie_media_source_reader import _NativeSourceCacheReader
            unseal=h.authority.protection.unseal
            def metadata_only(cipher,domain):
                if '/chunk-' in domain:pytest.fail('Recovery decrypted raw payload')
                return unseal(cipher,domain)
            with monkeypatch.context() as patch:
                patch.setattr(_NativeSourceCacheReader,'__init__',lambda *a:pytest.fail('Recovery invented raw cache READ'))
                patch.setattr(h.channel,'send',lambda *a:pytest.fail('Recovery sent network output'))
                patch.setattr(h.authority.protection,'unseal',metadata_only)
                recovery=_NativeSourceRetirementRecovery(recovery_source,verifier._job,record.version,backups,backup_version)
                result=recovery.run(h.preferences.issue_action(),h.preferences.read())
            assert result.body==dict(record.body,state='archived') and recovery_source._prepared=={}
            assert old.observation()==original and (cached.directory.parent/result.body['archive']).exists()
        finally:recovery_source.close()
    finally:verifier.close();fresh.close()


@pytest.mark.parametrize('change',['consent','book'])
def test_original_completion_cannot_supply_current_verification_rights_or_book_witness(completed,change):
    from magnolie_media_retention import NativeMediaRetention
    h,old,cached,_,_=completed;fresh,version=fresh_original(completed)
    verifier=_NativeMediaSourceSender.verify_published(fresh,cached.manifest.source_id,version)
    try:
        if change=='consent':h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
        else:
            with NativeMediaRetention(h.authority.binding.native_directory) as retention:retention.pause()
        with pytest.raises(TransferError):verifier.send_controls()
        assert verifier._journal.history() is None and old.observation().version==version
        assert cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:verifier.close();fresh.close()


def test_reauthenticated_original_and_retry_pins_cannot_hide_invalid_old_saved_during_recovery(completed):
    from hashlib import sha256
    from magnolie_telefon import canonical,strict_json
    from magnolie_media_source_retirement import _NativeSourceRetirementJournal
    h,old,cached,backups,backup_version=completed;fresh,version=fresh_original(completed)
    verifier=_NativeMediaSourceSender.verify_published(fresh,cached.manifest.source_id,version)
    try:
        handshake(h,verifier);offer=verifier.send_offer();h.wire.receive();deliver(h,verifier,readback(verifier,cached,offer))
        def stop(phase):
            if phase=='source_retirement_planned':owner.close()
        owner=_NativeSourceRetirement(verifier,backups,backup_version,boundary=stop)
        with pytest.raises(TransferError):owner.run()
        record=owner._journal.lookup(verifier._job);fresh.close();jobs=verifier._jobs
        original_key=old._journal._key;retry_key=verifier._journal._key;approval_key=jobs._catalog._retirement+verifier._job
        with jobs._database() as (db,key):
            db.execute('BEGIN IMMEDIATE');catalog=jobs._catalog.verify(db,key)
            def body(name):
                cipher=db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()[0]
                return strict_json(h.authority.protection.unseal(cipher,name))
            def write(name,value):
                cipher=h.authority.protection.seal(canonical(value),name)
                db.execute('UPDATE meta SET value=? WHERE key=?',(cipher,name));return sha256(cipher).hexdigest()
            original=body(original_key);original['peer_saved']['kind']='file_transfer.published.readback'
            original_version=write(original_key,original)
            retry=body(retry_key);retry['original_exchange_version']=original_version;retry_version=write(retry_key,retry)
            write(approval_key,dict(record.body,exchange_version=original_version,retry_version=retry_version))
            jobs._catalog.advance(db,key,catalog)
        selected=_NativeSourceRetirementJournal(jobs).lookup(verifier._job)
        recovery_source=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
        before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
        try:
            recovery=_NativeSourceRetirementRecovery(recovery_source,verifier._job,selected.version,backups,backup_version)
            with pytest.raises(TransferError):recovery.run(h.preferences.issue_action(),h.preferences.read())
            assert recovery_source._prepared=={} and {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before
        finally:recovery_source.close()
    finally:verifier.close();fresh.close()


@pytest.mark.parametrize('kind',['accept','chunk','saved'])
def test_original_completion_does_not_reopen_acceptance_chunk_or_saved_handlers(completed,kind):
    h,old,cached,_,_=completed;original=old.observation();fresh,version=fresh_original(completed)
    verifier=_NativeMediaSourceSender.verify_published(fresh,cached.manifest.source_id,version)
    try:
        handshake(h,verifier);offer=verifier.send_offer();h.wire.receive();before=verifier.observation()
        accepted=acceptance(verifier,cached,offer)
        packet={'accept':accepted,'chunk':request(accepted,cached),'saved':saved(accepted,cached)}[kind]
        with pytest.raises(TransferError,match='verification_readback_only'):deliver(h,verifier,packet)
        assert verifier.observation()==before and old.observation()==original
        assert verifier._prepared.failed.is_set() and cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:verifier.close();fresh.close()
