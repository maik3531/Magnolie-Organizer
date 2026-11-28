"""Refs #330: existing source controls/channel/journal, one native batch root."""
import base64
from hashlib import sha256
import pytest

from test_media_source_batch import pc, source, mappings, receiving, native, select
from test_media_source_sender import handshake, acceptance, request, saved, deliver, message
from magnolie_media_source_sender import _NativeMediaSourceSender
from magnolie_media_source_retirement import _NativeSourceRetirement
from magnolie_file_published_batch_readback import destination_token, encode_body, KIND
from magnolie_file_transfer import TransferError


def prepared(h,*,short_acceptance=False):
    raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC')
    h.pc_file.write_bytes(raw);(h.pc_file.parent/'second.png').write_bytes(raw)
    batch=select(h);cache=batch.freeze_cache()
    sender=_NativeMediaSourceSender(h.source,batch._id,_batch=batch)
    handshake(h,sender);offer=sender.send_media_offer();assert h.wire.receive()==offer
    accepted=acceptance(sender,cache,offer)
    if short_acceptance:accepted['expires_ms']-=1000
    deliver(h,sender,accepted)
    return batch,cache,sender,offer,accepted,raw


def all_saved(accepted,cache):
    packet=saved(accepted,cache)
    packet['body']['receipts']=[dict(file_id=f.id,size=f.size,sha256=f.sha256,receipt_sha256=sha256(f.id.encode()).hexdigest()) for f in cache.manifest.files]
    return packet


def chunks(h,sender,cache,accepted,raw,*,only_first=False):
    for f in cache.manifest.files[:1] if only_first else cache.manifest.files:
        packet=request(accepted,cache);packet['body']['file_id']=f.id
        deliver(h,sender,packet);response=h.wire.receive()
        assert response['body']['file_id']==f.id and base64.b64decode(response['body']['data_base64'])==raw


def readback(sender,cache,offer,accepted,receipt):
    publications={r['file_id']:r['receipt_sha256'] for r in receipt['body']['receipts']}
    context=dict(format=2,offer_id=offer['message_id'],manifest_sha256=cache.manifest.fingerprint,
        transfer_id=cache.manifest.transfer_id,source_id=cache.manifest.source_id,media_type=offer['body']['media_type'],
        members={f.id:dict(size=f.size,sha256=f.sha256,mime_type=offer['body']['mime_types'][f.id],publication_sha256=publications[f.id],
            row_sha256=sha256(('row/'+f.id).encode()).hexdigest()) for f in cache.manifest.files},
        permission_epoch=accepted['body']['permission_epoch'],readback_nonce='e'*64)
    binding=sender._controls.binding(destination_token(context),sender_is_local=True)
    return message(KIND,encode_body(context,binding),offer['expires_ms'])


@pytest.mark.parametrize('extended',[None,'saved','readback'],ids=['complete','saved-deadline','readback-deadline'])
def test_existing_sender_sends_one_full_offer_exact_file_chunks_and_requires_complete_saved_and_v2_readback(pc,extended):
    h=pc;batch,cache,sender,offer,accepted,raw=prepared(h,short_acceptance=True)
    assert offer['body']['format']==3
    assert len(offer['body']['offer']['manifest']['files'])==2
    assert set(offer['body']['pc_origins'])=={f.id for f in cache.manifest.files}
    chunks(h,sender,cache,accepted,raw)
    receipt=all_saved(accepted,cache)
    if extended=='saved':
        with pytest.raises(TransferError,match='batch_acceptance_deadline_changed'):
            deliver(h,sender,dict(receipt,expires_ms=offer['expires_ms']))
        assert sender.observation().body['phase']=='accepted'
        with pytest.raises(TransferError,match='sender_retired'):deliver(h,sender,receipt)
        sender.close();batch.close();return
    deliver(h,sender,receipt)
    proof=readback(sender,cache,offer,accepted,receipt)
    if extended=='readback':
        with pytest.raises(TransferError,match='batch_acceptance_deadline_changed'):deliver(h,sender,proof)
        assert sender.observation().body['phase']=='peer_saved'
        with pytest.raises(TransferError,match='sender_retired'):deliver(h,sender,dict(proof,expires_ms=accepted['expires_ms']))
        sender.close();batch.close();return
    deliver(h,sender,dict(proof,expires_ms=accepted['expires_ms']))
    result=sender.observation()
    assert result.body['format']==5 and result.body['phase']=='peer_readback'
    assert result.body['sent_bits']=={f.id:1 for f in cache.manifest.files}
    assert result.body['offer']==offer and result.body['acceptance']==accepted
    assert result.body['peer_saved']==receipt and result.body['pending_chunk'] is None
    assert not result.permits_retirement and not result.is_saved_receipt
    with pytest.raises(TransferError,match='whole_batch_retirement'): _NativeSourceRetirement(sender,None,None)
    assert cache.directory.exists() and all(lease._owned for lease in batch._leases.values())
    sender.close();batch.close()


@pytest.mark.parametrize('fault',['unsent-second','subset-saved','subset-readback','wrong-file'])
def test_first_file_or_forged_member_cannot_complete_the_original_batch(pc,fault):
    h=pc;batch,cache,sender,offer,accepted,raw=prepared(h)
    if fault=='wrong-file':
        packet=request(accepted,cache);packet['body']['file_id']='f'*32
        with pytest.raises(TransferError):deliver(h,sender,packet)
        assert sender.observation().body['sent_bits']=={f.id:0 for f in cache.manifest.files}
    else:
        chunks(h,sender,cache,accepted,raw,only_first=fault=='unsent-second')
        receipt=all_saved(accepted,cache)
        if fault=='subset-saved':receipt['body']['receipts'].pop()
        if fault=='subset-readback':
            deliver(h,sender,receipt);packet=readback(sender,cache,offer,accepted,receipt)
            # Even a syntactically rehashed subset gets a different binding and
            # must fail exact manifest membership, not merely the wire digest.
            context={k:v for k,v in packet['body'].items() if k not in ('destination_token','binding_sha256','readback_sha256')}
            context['members'].pop(next(iter(context['members'])))
            binding=sender._controls.binding(destination_token(context),sender_is_local=True)
            packet['body']=encode_body(context,binding)
            with pytest.raises(TransferError):deliver(h,sender,packet)
            assert sender.observation().body['phase']=='peer_saved'
        else:
            with pytest.raises(TransferError):deliver(h,sender,receipt)
            assert sender.observation().body['phase']=='accepted'
    assert cache.directory.exists() and all((h.pc_file.parent/e['path']).read_bytes()==raw for e in batch._entries.values())
    sender.close();batch.close()


def test_actual_batch_socket_output_cancellation_preserves_earlier_file_bits_and_pending_member_until_drain(pc,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import os
    import threading
    from magnolie_media_retention import NativeMediaRetention
    h=pc;batch,cache,sender,offer,accepted,raw=prepared(h)
    chunks(h,sender,cache,accepted,raw,only_first=True)
    entered=threading.Event();release=threading.Event();actual=h.channel.send
    target=cache.manifest.files[1]
    def blocked(packet):
        if packet.get('kind')=='file_transfer.chunk':
            entered.set();assert release.wait(5)
        return actual(packet)
    monkeypatch.setattr(h.channel,'send',blocked)
    packet=request(accepted,cache);packet['body']['file_id']=target.id
    with ThreadPoolExecutor(max_workers=1) as pool:
        attempt=pool.submit(deliver,h,sender,packet)
        try:
            assert entered.wait(15);sender.close()
            assert not attempt.done() and h.source._gate.locked()
            state=sender.observation().body
            assert state['sent_bits']=={cache.manifest.files[0].id:1,target.id:0}
            assert state['pending_chunk']['file_id']==target.id and state['pending_chunk']['chunk_index']==0
            for lease in batch._leases.values():os.fstat(lease._owned[-1])
            with NativeMediaRetention(h.authority.binding.native_directory) as retention:
                with retention.activity(lambda:True,exclusive=True) as competing:assert competing is None
        finally:release.set()
        with pytest.raises(TransferError):attempt.result(timeout=15)
    response=h.wire.receive();assert response['body']['file_id']==target.id
    state=sender.observation().body
    assert state['sent_bits'][cache.manifest.files[0].id]==1 and state['sent_bits'][target.id]==0
    assert state['pending_chunk']['file_id']==target.id and state['peer_saved'] is None
    assert batch._root is None and all(not lease._owned for lease in batch._leases.values())
    batch.close()


@pytest.mark.parametrize('fault',['skip-output','other-file','clear-earlier','change-saved','remove-pending'])
def test_batch_root_transition_metadata_cannot_skip_pending_output_or_rewrite_earlier_member(fault):
    # Pure journal-shape tests, NOT native socket output or retirement proof.
    from copy import deepcopy
    from magnolie_media_source_exchange import _batch_transition
    before=dict(phase='accepted',sent_bits={'first':1,'second':0},pending_chunk=None,peer_saved=None)
    after=deepcopy(before)
    if fault=='skip-output':after.update(phase='peer_saved',sent_bits={'first':1,'second':1})
    elif fault in ('other-file','clear-earlier','remove-pending'):
        before['pending_chunk']=dict(file_id='second',chunk_index=0)
        after['pending_chunk']=None
        if fault=='other-file':after['sent_bits']={'first':3,'second':0}
        elif fault=='clear-earlier':after['sent_bits']={'first':0,'second':1}
    else:
        before.update(phase='peer_saved',peer_saved={'original':'saved'})
        after.update(phase='peer_readback',peer_saved={'foreign':'saved'})
    with pytest.raises(TransferError):_batch_transition(before,after)
