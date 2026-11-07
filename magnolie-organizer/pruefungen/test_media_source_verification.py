"""Fresh readback-only verification after completed retry lease loss (#417).

PC-side native tests use synthetic peer envelopes, not paired Android output.
"""
import pytest
import threading

from test_media_source_readback import readback_completed,readback
from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_source_sender import handshake,deliver,acceptance,request,saved
from magnolie_media_source import NativeMappedMediaSource
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_media_source_recovery import _NativeSourceRetirementRecovery
from magnolie_file_transfer import TransferError
from magnolie_media_retention import NativeMediaRetention


def fresh_verifier(case):
    h,old,sender,cached,_,_,_=case;head=sender._journal.history();h.source.close()
    fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    fresh.reprepare(h.preferences.issue_action(),h.preferences.read(),h.association,h.record.protected_record_sha256,
        cached.manifest.source_id,cached._job_version)
    verifier=_NativeMediaSourceSender.verify_published(fresh,cached.manifest.source_id,old.observation().version,head.version)
    return fresh,verifier,head


def test_completed_retry_requires_fresh_original_preparation_and_new_readback_before_local_archive(readback_completed):
    h,old,sender,cached,backups,version,old_proof=readback_completed
    with pytest.raises(TransferError,match='fresh_repreparation_required'):
        _NativeMediaSourceSender.verify_published(h.source,cached.manifest.source_id,old.observation().version,sender._journal.history().version)
    fresh,verifier,head=fresh_verifier(readback_completed)
    try:
        handshake(h,verifier);offer=verifier.send_offer();h.wire.receive()
        state=verifier.observation().body
        assert state['format']==3 and state['purpose']=='published_verification' and state['peer_readback'] is None
        proof=readback(verifier,cached,offer);deliver(h,verifier,proof)
        assert verifier._journal.history().body['attempts'][:-1]==head.body['attempts']
        archived=_NativeSourceRetirement(verifier,backups,version).run()
        assert (cached.directory.parent/archived.body['archive']).exists() and h.target.read_bytes()==b'hello'
    finally:verifier.close();fresh.close()


@pytest.mark.parametrize('kind',['accept','chunk','saved','old_proof'])
def test_verification_rejects_accept_chunk_and_saved_without_changing_state_or_opening_new_transfer(readback_completed,kind):
    h,old,_,cached,_,_,old_proof=readback_completed;fresh,verifier,head=fresh_verifier(readback_completed)
    try:
        handshake(h,verifier);offer=verifier.send_offer();h.wire.receive();before=verifier.observation()
        accepted=acceptance(verifier,cached,offer)
        packet={'accept':accepted,'chunk':request(accepted,cached),'saved':saved(accepted,cached),'old_proof':old_proof}[kind]
        with pytest.raises(TransferError):deliver(h,verifier,packet)
        assert verifier.observation()==before
        assert verifier._prepared.failed.is_set()
        with pytest.raises(TransferError,match='sender_retired'):
            deliver(h,verifier,readback(verifier,cached,offer))
        with pytest.raises(TransferError,match='completed_held'):
            _NativeMediaSourceSender.retry(fresh,cached.manifest.source_id,old.observation().version,verifier._journal.history().version)
        assert cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:verifier.close();fresh.close()


@pytest.mark.parametrize('phase',['source_retirement_planned','source_retirement_moved'])
def test_verification_archive_recovery_remains_metadata_only_with_exact_purpose_and_head(readback_completed,phase,monkeypatch):
    h,_,_,cached,backups,version,_=readback_completed;fresh,verifier,head=fresh_verifier(readback_completed)
    try:
        handshake(h,verifier);offer=verifier.send_offer();h.wire.receive();deliver(h,verifier,readback(verifier,cached,offer))
        def stop(current):
            if current==phase:owner.close()
        owner=_NativeSourceRetirement(verifier,backups,version,boundary=stop)
        with pytest.raises(TransferError):owner.run()
        record=owner._journal.lookup(verifier._job);fresh.close()
        recovery_source=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
        try:
            from magnolie_media_source_reader import _NativeSourceCacheReader
            unseal=h.authority.protection.unseal
            def metadata_only(cipher,domain):
                if '/chunk-' in domain:pytest.fail('Recovery decrypted original payload')
                return unseal(cipher,domain)
            with monkeypatch.context() as patch:
                patch.setattr(_NativeSourceCacheReader,'__init__',lambda *a:pytest.fail('Recovery invented Raw READ'))
                patch.setattr(h.channel,'send',lambda *a:pytest.fail('Recovery emitted network output'))
                patch.setattr(h.authority.protection,'unseal',metadata_only)
                recovery=_NativeSourceRetirementRecovery(recovery_source,verifier._job,record.version,backups,version)
                result=recovery.run(h.preferences.issue_action(),h.preferences.read())
            assert result.body==dict(record.body,state='archived') and recovery_source._prepared=={}
            assert (cached.directory.parent/result.body['archive']).exists()
            assert verifier._journal.history().body['attempts'][:-1]==head.body['attempts']
        finally:recovery_source.close()
    finally:verifier.close();fresh.close()


@pytest.mark.parametrize('change',['purpose','bits','missing_predecessor','ordinary_after_completed'])
def test_authenticated_changed_verification_semantics_never_become_local_archive_approval(readback_completed,change):
    from hashlib import sha256
    from magnolie_telefon import canonical,strict_json
    from magnolie_media_source_retirement import _NativeSourceRetirementJournal
    h,_,_,cached,backups,version,_=readback_completed;fresh,verifier,_=fresh_verifier(readback_completed)
    try:
        handshake(h,verifier);offer=verifier.send_offer();h.wire.receive();deliver(h,verifier,readback(verifier,cached,offer))
        def stop(phase):
            if phase=='source_retirement_planned':owner.close()
        owner=_NativeSourceRetirement(verifier,backups,version,boundary=stop)
        with pytest.raises(TransferError):owner.run()
        record=owner._journal.lookup(verifier._job);fresh.close();jobs=verifier._jobs;name=verifier._journal._key
        approval_key=jobs._catalog._retirement+verifier._job
        with jobs._database() as (db,key):
            db.execute('BEGIN IMMEDIATE');catalog=jobs._catalog.verify(db,key)
            cipher=db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()[0]
            value=strict_json(h.authority.protection.unseal(cipher,name));body=value['attempts'][-1]['record']
            if change=='purpose':body['purpose']='ordinary_transfer'
            elif change=='bits':body['sent_bits']=1
            elif change=='ordinary_after_completed':body['format']=2;body.pop('purpose')
            else:value['attempts']=[dict(value['attempts'][-1],previous_head=None)]
            changed=h.authority.protection.seal(canonical(value),name)
            db.execute('UPDATE meta SET value=? WHERE key=?',(changed,name))
            approval=dict(record.body,retry_version=sha256(changed).hexdigest())
            db.execute('UPDATE meta SET value=? WHERE key=?',(h.authority.protection.seal(canonical(approval),approval_key),approval_key))
            jobs._catalog.advance(db,key,catalog)
        selected=_NativeSourceRetirementJournal(jobs).lookup(verifier._job)
        before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
        recovery_source=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
        try:
            recovery=_NativeSourceRetirementRecovery(recovery_source,verifier._job,selected.version,backups,version)
            with pytest.raises(TransferError):recovery.run(h.preferences.issue_action(),h.preferences.read())
            assert recovery_source._prepared=={} and {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before
        finally:recovery_source.close()
    finally:verifier.close();fresh.close()


@pytest.mark.parametrize('change',['consent','intent','book'])
def test_verification_history_never_bypasses_current_source_rights_or_exact_original_book(readback_completed,change):
    h,_,_,cached,_,_,_=readback_completed;fresh,verifier,head=fresh_verifier(readback_completed)
    try:
        if change=='consent':h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
        elif change=='intent':h.controller.change('enabled',False)
        else:
            with NativeMediaRetention(h.authority.binding.native_directory) as retention:retention.pause()
        with pytest.raises(TransferError):verifier.send_controls()
        assert verifier._journal.history()==head and cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:verifier.close();fresh.close()


@pytest.mark.parametrize('change',['copied_cache','old_original','old_head'])
def test_verifier_requires_exact_actual_reprepared_cache_and_selected_historical_heads(readback_completed,change):
    from dataclasses import replace
    h,old,_,cached,_,_,_=readback_completed;fresh,verifier,head=fresh_verifier(readback_completed)
    try:
        if change=='copied_cache':
            prepared=fresh._prepared[cached.manifest.source_id]
            fresh._prepared[cached.manifest.source_id]=replace(prepared,cache=replace(prepared.cache))
        with pytest.raises(TransferError):
            _NativeMediaSourceSender.verify_published(fresh,cached.manifest.source_id,
                'f'*64 if change=='old_original' else old.observation().version,'e'*64 if change=='old_head' else head.version)
        assert verifier._journal.history()==head and cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:verifier.close();fresh.close()


def test_cancel_during_actual_verification_offer_output_keeps_book_os_lane_until_socket_drains(readback_completed,monkeypatch):
    h,_,_,cached,_,_,_=readback_completed;fresh,verifier,_=fresh_verifier(readback_completed)
    entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[];send=h.channel.send
    def blocked(packet):
        if packet.get('kind')=='file_transfer.offer':entered.set();assert release.wait(8)
        return send(packet)
    monkeypatch.setattr(h.channel,'send',blocked)
    def work():
        try:verifier.send_offer()
        except BaseException as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=work)
    try:
        handshake(h,verifier);worker.start()
        try:
            assert entered.wait(5);verifier.close();assert not ended.is_set()
            with NativeMediaRetention(h.authority.binding.native_directory) as retention:
                with retention.activity() as lease:assert lease is None
        finally:release.set();worker.join(5)
        assert ended.is_set() and not worker.is_alive() and len(errors)==1 and isinstance(errors[0],TransferError)
        state=verifier.observation().body
        assert state['format']==3 and state['phase']=='offer_planned' and state['peer_readback'] is None and state['sent_bits']==0
        assert cached.directory.exists() and h.target.read_bytes()==b'hello'
        with NativeMediaRetention(h.authority.binding.native_directory) as retention:
            with retention.activity() as lease:assert lease is not None
    finally:release.set();verifier.close();fresh.close()
