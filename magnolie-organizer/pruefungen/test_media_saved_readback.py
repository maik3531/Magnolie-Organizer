from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

import magnolie_file_published_batch_readback as batch_readback
import magnolie_file_published_readback as single_readback
from magnolie_file_transfer import FileManifest, NativeTransferBinding, TransferError
from magnolie_media_offer import create_media_offer
from magnolie_media_saved_readback import create_request, read_request, require_reply
from magnolie_media_sync import change, create


def _fixture(batch):
    sender, receiver = str(uuid4()), str(uuid4())
    settings = create(sender)
    for field, value in (('enabled', True), ('videos_enabled', True),
                         ('direction', 'pc_to_phone'), ('collection_mode', 'entire_collection')):
        settings = change(settings, sender, receiver, field, value)
    count = 2 if batch else 1
    kind, mime, suffix = ('images', 'image/png', 'png') if batch else ('video', 'video/mp4', 'mp4')
    manifest = FileManifest.parse(dict(format=1, chunk_bytes=65536, total_bytes=count * 512,
        transfer_id='3' * 32, source_id='4' * 32, sender_id=sender, receiver_id=receiver,
        files=[dict(id=f'{i:032x}', path=f'original-{i}.{suffix}', size=512, sha256='a' * 64)
               for i in range(count)]))
    origin = {file.id: dict(format=1, origin_sha256=f'{i:064x}', previous_publication_sha256=None)
              for i, file in enumerate(manifest.files)}
    offer = create_media_offer(manifest, settings, kind, {file.id: mime for file in manifest.files}, {},
                               now=1000, pc_origins=origin, pc_batch=batch)
    meta = {file.id: dict(size=file.size, sha256=file.sha256, mime_type=mime,
                          publication_sha256=f'{i+8:064x}', row_sha256=f'{i+16:064x}')
            for i, file in enumerate(manifest.files)}
    saved = dict(type='message', v=1, message_id=str(uuid4()), kind='file_transfer.saved',
                 created_ms=2000, expires_ms=3000,
                 body=dict(format=1, transfer_id=manifest.transfer_id, manifest_sha256=manifest.fingerprint,
                           acceptance_sha256='a' * 64, permission_epoch='b' * 64, destination_token='c' * 64,
                           receipts=[dict(file_id=file.id, size=file.size, sha256=file.sha256,
                                          receipt_sha256=meta[file.id]['publication_sha256'])
                                     for file in manifest.files]))
    binding = NativeTransferBinding(sender, receiver, 'd' * 64, 'e' * 64, 'f' * 64, manifest.fingerprint)
    now = offer['expires_ms'] + 1000
    request = create_request(offer, saved, binding, now)
    context = dict(format=2 if batch else 1, offer_id=offer['message_id'], manifest_sha256=manifest.fingerprint,
                   transfer_id=manifest.transfer_id, source_id=manifest.source_id, media_type=kind,
                   permission_epoch=binding.permission_epoch, readback_nonce=request['body']['nonce'])
    if batch:
        context['members'] = meta
    else:
        file_id, member = next(iter(meta.items()))
        context.update(file_id=file_id, **member)
    return request, binding, context, now


def _reply(request, binding, context, now):
    codec = batch_readback if context['format'] == 2 else single_readback
    reply_binding = replace(binding, destination_token=codec.destination_token(context))
    return dict(type='message', v=1, message_id=str(uuid4()), kind=single_readback.KIND,
                created_ms=now, expires_ms=request['expires_ms'], body=codec.encode_body(context, reply_binding)), reply_binding


@pytest.mark.parametrize('batch', [False, True])
def test_fresh_reply_uses_expired_original_exact_members_and_new_controls(batch):
    request, binding, context, now = _fixture(batch)
    media, saved = read_request(request, binding, now)
    message, reply_binding = _reply(request, binding, context, now)
    assert request['body']['offer']['expires_ms'] < message['created_ms']
    assert saved.permission_epoch != reply_binding.permission_epoch
    require_reply(message, request, binding, reply_binding, now)
    original_parser = batch_readback.parse_batch_readback if batch else single_readback.parse_readback
    with pytest.raises(TransferError):
        original_parser(message, media.offer, reply_binding, media.media_type, now=now)


@pytest.mark.parametrize('change_name', ['different-nonce', 'foreign-epoch', 'late-deadline', 'future',
                                         'missing-member', 'digest-matched-wrong-receipt'])
def test_fresh_batch_reply_rejects_rebound_wrong_readbacks(change_name):
    request, binding, context, now = _fixture(True)
    key = next(iter(context['members']))
    reply_base = binding
    if change_name == 'different-nonce':
        context['readback_nonce'] = '0' * 64
    elif change_name == 'foreign-epoch':
        context['permission_epoch'] = '0' * 64
        reply_base = replace(binding, permission_epoch=context['permission_epoch'])
    elif change_name == 'missing-member':
        del context['members'][key]
    elif change_name == 'digest-matched-wrong-receipt':
        context['members'][key]['publication_sha256'] = 'a' * 64
    message, reply_binding = _reply(request, reply_base, context, now)
    if change_name == 'late-deadline':
        message['expires_ms'] += 1
    elif change_name == 'future':
        message['created_ms'] += 1
    with pytest.raises(TransferError):
        require_reply(message, request, binding, reply_binding, now)


@pytest.mark.parametrize('change_name', ['foreign-receiver', 'replaced-original', 'non-pc-offer', 'incomplete-saved', 'expired'])
def test_current_control_and_complete_original_saved_are_separate(change_name):
    request, binding, _, now = _fixture(True)
    request = deepcopy(request)
    if change_name == 'foreign-receiver':
        binding = replace(binding, receiver_identity_sha256='0' * 64)
    elif change_name == 'replaced-original':
        origins = request['body']['offer']['body']['pc_origins']
        next(iter(origins.values()))['previous_publication_sha256'] = '0' * 64
    elif change_name == 'non-pc-offer':
        request['body']['offer']['body']['pc_origins'].clear()
    elif change_name == 'incomplete-saved':
        request['body']['saved']['body']['receipts'].pop()
    else:
        now = request['expires_ms']
    with pytest.raises(TransferError):
        read_request(request, binding, now)
