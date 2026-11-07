"""Private PC readback completion over actual secure sockets.

Peer envelopes here are SYNTHETIC codec inputs, not an actual Android provider
or cross-process phone producer. Native phone producer/runtime proofs are413/414.
"""
from dataclasses import replace
from hashlib import sha256

import pytest

from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_source_sender import offered,handshake,deliver,message
from test_media_source_retry import original_bytes,fresh_acceptance
from test_media_source_cache import freeze
from test_media_source_backup import open_backup
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_file_published_readback import KIND,destination_token,encode_body
from magnolie_file_offer import create_offer
from magnolie_file_transfer import TransferError
from magnolie_media_source_backup import backup_prepared_source
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_media_source_retirement import _NativeSourceRetirementJournal
from magnolie_media_source_recovery import _NativeSourceRetirementRecovery
from magnolie_media_source import NativeMappedMediaSource


def readback(sender,cached,offer,*,change=None):
    binding=sender._binding or sender._controls.binding('0'*64,sender_is_local=True)
    file=cached.manifest.files[0]
    context=dict(format=1,offer_id=offer['message_id'],manifest_sha256=cached.manifest.fingerprint,
        transfer_id=cached.manifest.transfer_id,source_id=cached.manifest.source_id,file_id=file.id,size=file.size,sha256=file.sha256,
        media_type=cached.original_references[file.id]['media_type'],mime_type='image/png',publication_sha256='d'*64,row_sha256='e'*64,
        permission_epoch=binding.permission_epoch,readback_nonce='1'*64)
    if change:change(context)
    binding=replace(binding,destination_token=destination_token(context))
    return message(KIND,encode_body(context,binding),offer['expires_ms'])


def retry_offered(h):
    old,cached,original_offer=offered(h)
    sender=_NativeMediaSourceSender.retry(h.source,cached.manifest.source_id,old.observation().version)
    handshake(h,sender);offer=sender.send_offer();assert h.wire.receive()==offer
    return old,sender,cached,original_offer,offer


@pytest.fixture
def readback_completed(source):
    h=source;old,sender,cached,original_offer,offer=retry_offered(h)
    try:
        proof=readback(sender,cached,offer);deliver(h,sender,proof)
        with open_backup(h) as backups:
            version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
            yield h,old,sender,cached,backups,version,proof
    finally:sender.close();old.close()


def test_actual_private_readback_completion_has_no_acceptance_or_new_chunks_and_archives_exact_proof(source,monkeypatch):
    h=source;old,sender,cached,_,offer=retry_offered(h);before=original_bytes(h,old)
    cache={p.name:(p.stat().st_ino,p.read_bytes()) for p in cached.directory.iterdir()}
    try:
        proof=readback(sender,cached,offer)
        from magnolie_media_source_reader import _NativeSourceCacheReader
        with monkeypatch.context() as patch:
            patch.setattr(_NativeSourceCacheReader,'read_chunk',lambda *args:pytest.fail('Readback completion reopened raw source payload'))
            deliver(h,sender,proof)
        state=sender.observation();body=state.body
        assert body['format']==2 and body['phase']=='peer_readback' and body['peer_readback']==proof
        assert body['acceptance'] is None and body['peer_saved'] is None and body['sent_bits']==0 and body['pending_chunk'] is None
        assert not state.is_saved_receipt and not state.grants_read_authority and not state.permits_retirement
        assert original_bytes(h,old)==before
        with open_backup(h) as backups:
            version=backup_prepared_source(backups,h.source,cached.manifest.source_id)
            retired=_NativeSourceRetirement(sender,backups,version).run()
        assert retired.body['retry_version']==state.version and retired.body['exchange_version']==old.observation().version
        archive=cached.directory.parent/retired.body['archive']
        assert {p.name:(p.stat().st_ino,p.read_bytes()) for p in archive.iterdir()}==cache
        second=freeze(h);assert second.manifest.source_id!=cached.manifest.source_id
        assert original_bytes(h,old)==before
    finally:sender.close();old.close()


@pytest.mark.parametrize('phase',['source_retirement_planned','source_retirement_moved'])
def test_distinct_readback_archive_recovers_metadata_only_without_inventing_saved_or_raw_reader(readback_completed,phase,monkeypatch):
    h,_,sender,cached,backups,version,proof=readback_completed
    def stop(current):
        if current==phase:owner.close()
    owner=_NativeSourceRetirement(sender,backups,version,boundary=stop)
    with pytest.raises(TransferError):owner.run()
    record=owner._journal.lookup(sender._job);h.source.close();fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    try:
        from magnolie_media_source_reader import _NativeSourceCacheReader
        unseal=h.authority.protection.unseal
        def metadata_only(cipher,domain):
            if '/chunk-' in domain:pytest.fail('Archive recovery decrypted raw cache payload')
            return unseal(cipher,domain)
        with monkeypatch.context() as patch:
            patch.setattr(_NativeSourceCacheReader,'__init__',lambda *args:pytest.fail('Metadata archive recovery invented raw READ'))
            patch.setattr(h.channel,'send',lambda *args:pytest.fail('Local archive recovery emitted network output'))
            patch.setattr(h.authority.protection,'unseal',metadata_only)
            recovery=_NativeSourceRetirementRecovery(fresh,sender._job,record.version,backups,version)
            result=recovery.run(h.preferences.issue_action(),h.preferences.read())
        assert result.body==dict(record.body,state='archived') and fresh._prepared=={}
        state=sender.observation().body
        assert state['peer_readback']==proof and state['peer_saved'] is None and state['acceptance'] is None and state['sent_bits']==0
        assert (cached.directory.parent/result.body['archive']).exists()
        second=freeze(h,fresh);assert second.manifest.source_id!=cached.manifest.source_id
    finally:fresh.close()


def test_completed_readback_cannot_restart_retry_reaccept_input_or_enter_original_exchange_schema(source):
    h=source;old,sender,cached,_,offer=retry_offered(h)
    try:
        proof=readback(sender,cached,offer);deliver(h,sender,proof);before=sender.observation()
        with pytest.raises(TransferError,match='completed_held'):
            _NativeMediaSourceSender.retry(h.source,cached.manifest.source_id,old.observation().version,sender._journal.history().version)
        with pytest.raises(TransferError,match='readback_offer_required'):deliver(h,sender,proof)
        with pytest.raises(TransferError,match='invalid_record'):
            old._journal._validate(before.body,sender._jobs._database_key)
        assert sender.observation()==before and before.body['sent_bits']==0 and before.body['peer_saved'] is None
        assert cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:sender.close();old.close()


@pytest.mark.parametrize('change',['old_offer','manifest','source','size','kind','binding','digest','channel'])
def test_wrong_readback_context_never_completes_or_changes_actual_retry(source,change):
    h=source;old,sender,cached,original_offer,offer=retry_offered(h);before=sender.observation()
    def mutate(context):
        if change=='manifest':context['manifest_sha256']='a'*64
        elif change=='source':context['source_id']='f'*32
        elif change=='size':context['size']+=1
        elif change=='kind':context.update(media_type='video',mime_type='video/mp4')
    proof=readback(sender,cached,original_offer if change=='old_offer' else offer,change=mutate)
    if change=='binding':proof['body']['binding_sha256']='f'*64
    elif change=='digest':proof['body']['readback_sha256']='a'*64
    try:
        with pytest.raises(TransferError):
            if change=='channel':sender.observe(object(),proof)
            else:deliver(h,sender,proof)
        assert sender.observation()==before and before.body['format']==1 and before.body['phase']=='offer_sent'
        assert cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:sender.close();old.close()


@pytest.mark.parametrize('state',['original','no_offer','accepted'])
def test_only_empty_actually_offered_retry_can_accept_readback_and_never_convert_ordinary_saved(source,state):
    h=source;old,cached,offer=offered(h);sender=old
    if state!='original':
        sender=_NativeMediaSourceSender.retry(h.source,cached.manifest.source_id,old.observation().version);handshake(h,sender)
        offer=create_offer(cached.manifest)
        if state=='accepted':
            offer=sender.send_offer();h.wire.receive();deliver(h,sender,fresh_acceptance(sender,cached,offer))
    before=sender.observation();proof=readback(sender,cached,offer)
    try:
        with pytest.raises(TransferError,match='readback_offer_required'):deliver(h,sender,proof)
        assert sender.observation()==before and cached.directory.exists()
    finally:sender.close();old.close()


@pytest.mark.parametrize('change',['consent','intent'])
def test_current_native_source_rights_are_required_even_for_self_consistent_peer_readback(source,change):
    h=source;old,sender,cached,_,offer=retry_offered(h);proof=readback(sender,cached,offer);before=sender.observation()
    if change=='consent':h.preferences.configure_sending(h.preferences.issue_action(),h.preferences.read(),photos=False,videos=False)
    else:h.controller.change('enabled',False)
    try:
        with pytest.raises(TransferError):deliver(h,sender,proof)
        assert sender.observation()==before and cached.directory.exists() and h.target.read_bytes()==b'hello'
    finally:sender.close();old.close()


@pytest.mark.parametrize('change',['frame_kind','proof_digest','source_reencoded','saved_conversion','new_bits'])
def test_authenticated_but_semantically_changed_readback_history_cannot_approve_archive_recovery(readback_completed,change):
    from magnolie_telefon import canonical,strict_json
    from magnolie_file_published_readback import CONTEXT
    from test_media_source_sender import acceptance
    h,_,sender,cached,backups,version,_=readback_completed
    def stop(phase):
        if phase=='source_retirement_planned':owner.close()
    owner=_NativeSourceRetirement(sender,backups,version,boundary=stop)
    with pytest.raises(TransferError):owner.run()
    record=owner._journal.lookup(sender._job);h.source.close()
    jobs=sender._jobs;name=sender._journal._key;retirement_name=jobs._catalog._retirement+sender._job
    with jobs._database() as (db,key):
        db.execute('BEGIN IMMEDIATE');head=jobs._catalog.verify(db,key)
        cipher=db.execute('SELECT value FROM meta WHERE key=?',(name,)).fetchone()[0]
        value=strict_json(h.authority.protection.unseal(cipher,name));body=value['attempts'][-1]['record'];proof=body['peer_readback']
        if change=='frame_kind':proof['kind']='file_transfer.saved'
        elif change=='proof_digest':proof['body']['readback_sha256']='a'*64
        elif change=='source_reencoded':
            context={field:proof['body'][field] for field in CONTEXT};context['source_id']='f'*32
            binding=replace(sender._binding,destination_token=destination_token(context));proof['body']=encode_body(context,binding)
        elif change=='saved_conversion':
            body.update(format=1,phase='peer_saved',acceptance=acceptance(sender,cached,body['offer']),peer_saved=proof,
                sent_bits=(1<<cached.manifest.files[0].chunks)-1)
            body.pop('peer_readback')
        else:body['sent_bits']=1
        changed=h.authority.protection.seal(canonical(value),name)
        db.execute('UPDATE meta SET value=? WHERE key=?',(changed,name))
        approval=dict(record.body,retry_version=sha256(changed).hexdigest())
        db.execute('UPDATE meta SET value=? WHERE key=?',(h.authority.protection.seal(canonical(approval),retirement_name),retirement_name))
        # Authenticated semantic boundary fixture, NOT physical rollback evidence.
        # Even an updated exact head pin cannot replace valid protocol semantics.
        jobs._catalog.advance(db,key,head)
    selected=_NativeSourceRetirementJournal(jobs).lookup(sender._job)
    before={p.name:p.read_bytes() for p in cached.directory.iterdir()};fresh=NativeMappedMediaSource(h.preferences,h.mappings,h.controller)
    try:
        recovery=_NativeSourceRetirementRecovery(fresh,sender._job,selected.version,backups,version)
        with pytest.raises(TransferError):recovery.run(h.preferences.issue_action(),h.preferences.read())
        assert fresh._prepared=={} and {p.name:p.read_bytes() for p in cached.directory.iterdir()}==before
        assert _NativeSourceRetirementJournal(jobs).lookup(sender._job)==selected
    finally:fresh.close()
