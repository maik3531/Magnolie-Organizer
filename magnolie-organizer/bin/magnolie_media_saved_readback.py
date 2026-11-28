"""Metadata for an explicit read-only check of a PC original already Saved.

The old offer and Saved are historical inputs. Neither is sent to an offer
dispatcher nor used to derive the current native data grant.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from secrets import token_hex
from uuid import uuid4

from magnolie_file_control import MAX_TTL_MS, _hex
import magnolie_file_published_batch_readback as batch_readback
import magnolie_file_published_readback as single_readback
from magnolie_file_accept_message import parse_acceptance
from magnolie_file_saved_message import parse_saved
from magnolie_file_transfer import FileManifest, NativeTransferBinding, TransferError
from magnolie_media_offer import validate_media_offer
from magnolie_telefon import APPLICATION_MAX, canonical, valid_uuid

REQUEST = 'file_transfer.published.recover'
_HEADER = {'type', 'v', 'message_id', 'kind', 'created_ms', 'expires_ms', 'body'}
_FIELDS = {'format', 'binding_sha256', 'nonce', 'offer', 'saved'}
_MAX_WALL = 253_402_300_799_999


def _binding_digest(binding):
    if type(binding) is not NativeTransferBinding:
        raise TransferError('media_saved_readback_binding_required')
    return sha256(b'magnolie-pc-saved-readback-control-v1\0' + canonical(asdict(binding))).hexdigest()


def _body(message, kind, now):
    if (type(message) is not dict or set(message) != _HEADER or message['type'] != 'message'
            or type(message['v']) is not int or message['v'] != 1 or message['kind'] != kind
            or not valid_uuid(message['message_id'], version=4)
            or type(now) is not int or type(message['created_ms']) is not int or type(message['expires_ms']) is not int
            or not 0 <= message['created_ms'] <= now < message['expires_ms'] <= _MAX_WALL
            or message['expires_ms'] - message['created_ms'] > MAX_TTL_MS
            or type(message['body']) is not dict or len(canonical(message)) > APPLICATION_MAX):
        raise TransferError('media_saved_readback_invalid_envelope')
    return message['body']


def read_request(request, binding, now):
    """Check wire format and historical content, without granting I/O."""
    body = _body(request, REQUEST, now)
    if (set(body) != _FIELDS or type(body['format']) is not int or body['format'] != 1 or not _hex(body['nonce'])
            or body['binding_sha256'] != _binding_digest(binding)
            or type(body['offer']) is not dict or type(body['saved']) is not dict):
        raise TransferError('media_saved_readback_invalid_request')
    offer, saved = body['offer'], body['saved']
    media = validate_media_offer(offer, binding.sender_id, binding.receiver_id,
        now=offer.get('created_ms'), allow_pc_batch=True)
    manifest = media.manifest
    if media.pc_batch:
        typed = media.media_type == 'images'
    else:
        typed = (media.media_type == 'video' and len(manifest.files) == 1
            and manifest.files[0].size > 0 and media.mime_types[manifest.files[0].id] == 'video/mp4')
    if (binding.destination_token != manifest.fingerprint or media.originals
            or set(media.pc_origins) != {file.id for file in manifest.files}
            or any(origin['previous_publication_sha256'] is not None for origin in media.pc_origins.values())
            or not typed):
        raise TransferError('media_saved_readback_original_pc_media_required')
    receipt = parse_saved(saved, manifest, now=saved.get('created_ms'))
    if (not offer['created_ms'] <= saved['created_ms'] < saved['expires_ms'] <= offer['expires_ms']
            or saved['created_ms'] > request['created_ms']
            or len({member.receipt_sha256 for member in receipt.receipts}) != len(manifest.files)):
        raise TransferError('media_saved_readback_original_saved_required')
    return media, receipt


def create_request(offer, saved, binding, now):
    body = dict(format=1, binding_sha256=_binding_digest(binding), nonce=token_hex(32),
        offer=deepcopy(offer), saved=deepcopy(saved))
    request = dict(type='message', v=1, message_id=str(uuid4()), kind=REQUEST,
        created_ms=now, expires_ms=now+MAX_TTL_MS, body=body)
    read_request(request, binding, now)
    return request


def require_reply(message, request, request_binding, reply_binding, now):
    """Authenticate v1 MP4 or complete v2 photo metadata on the fresh reader.

    The caller binds both controls to the same native session. Nothing here
    recognizes an ordinary publication reply as a reconnect proof.
    """
    media, saved = read_request(request, request_binding, now)
    body = _body(message, single_readback.KIND, now)
    codec = batch_readback if media.pc_batch else single_readback
    manifest = media.manifest
    if (set(body) != codec.CONTEXT | {'destination_token', 'binding_sha256', 'readback_sha256'}
            or not _hex(body['destination_token'])
            or reply_binding != replace(request_binding, destination_token=body['destination_token'])
            or request['message_id'] == message['message_id']
            or not request['created_ms'] <= message['created_ms'] < message['expires_ms'] <= request['expires_ms']
            or body['readback_nonce'] != request['body']['nonce']
            or body['offer_id'] != media.offer['message_id'] or body['manifest_sha256'] != manifest.fingerprint
            or body['transfer_id'] != manifest.transfer_id or body['source_id'] != manifest.source_id
            or body['media_type'] != media.media_type
            or codec.encode_body({name: body[name] for name in codec.CONTEXT}, reply_binding) != body):
        raise TransferError('media_saved_readback_invalid_reply')
    members = body['members'] if media.pc_batch else {body['file_id']: body}
    if set(members) != {file.id for file in manifest.files}:
        raise TransferError('media_saved_readback_original_members_required')
    for member in saved.receipts:
        observed = members[member.file_id]
        if (observed['size'] != member.size or observed['sha256'] != member.sha256
                or observed['mime_type'] != media.mime_types[member.file_id]
                or observed['publication_sha256'] != member.receipt_sha256):
            raise TransferError('media_saved_readback_original_members_required')


def pending_original(jobs, kinds):
    """Locate the one protected PC Saved job before completion of native END."""
    from magnolie_media_source_exchange import _read_source_exchange
    from magnolie_media_source_lineage import _NativeSourceLineage
    from magnolie_media_source_retirement import _NativeSourceRetirementJournal

    with jobs._database() as (db, key):
        db.execute('BEGIN')
        catalog = jobs._catalog.verify(db, key)
        history = _NativeSourceLineage(jobs).inspect(db, key, catalog).records
        result = None
        if history:
            ready = history[-1]
            body = ready.body
            kind = body.get('media_type')
            job = body['job_id']
            if (ready.state == 'cache_ready' and (body['format'], kind) in ((3, 'video'), (4, 'images'))
                    and kind in kinds and _NativeSourceRetirementJournal(jobs)._read(db, key, job) is None):
                exchange = _read_source_exchange(jobs, db, key, job, ready)
                if exchange is not None and exchange.body['phase'] == 'peer_saved':
                    manifest = FileManifest.parse(body['manifest'])
                    _require_pending_original(body, exchange.body, manifest)
                    result = ready, exchange, manifest
                elif exchange is not None and 'recovery' in exchange.body:
                    result = ready, exchange, FileManifest.parse(body['manifest'])
    jobs._catalog.observe(catalog)
    return result


def _require_pending_original(ready, exchange, manifest):
    batch = ready['format'] == 4
    if (exchange['format'] != (5 if batch else 4) or exchange['peer_readback'] is not None
            or exchange['pending_chunk'] is not None
            or any(type(exchange[name]) is not dict for name in ('offer', 'acceptance', 'peer_saved'))):
        raise TransferError('media_saved_readback_original_exchange_required')
    offer, accepted, saved = (exchange[name] for name in ('offer', 'acceptance', 'peer_saved'))
    media = validate_media_offer(offer, manifest.sender_id, manifest.receiver_id,
        now=offer.get('created_ms'), allow_pc_batch=batch)
    bits = {file.id: (1 << file.chunks) - 1 for file in manifest.files}
    origins = {file.id: ready['members'][file.id]['local_origin'] if batch else ready['local_origin']
               for file in manifest.files}
    pc_origins = {fid: dict(format=1, origin_sha256=sha256(
        b'magnolie-pc-media-origin-v1\0' + canonical(origin)).hexdigest(), previous_publication_sha256=None)
        for fid, origin in origins.items()}
    if (media.manifest != manifest or media.pc_batch is not batch or media.media_type != ready['media_type']
            or media.originals or media.pc_origins != pc_origins
            or exchange['sent_bits'] != (bits if batch else next(iter(bits.values())))
            or batch and any(value is not None for value in ready['predecessors'].values())):
        raise TransferError('media_saved_readback_original_exchange_required')
    admission = parse_acceptance(accepted, now=accepted.get('created_ms'))
    receipt = parse_saved(saved, manifest, now=saved.get('created_ms'))
    if (admission.offer_id != offer['message_id'] or admission.permission_epoch != exchange['permission_epoch']
            or not offer['created_ms'] <= accepted['created_ms'] <= saved['created_ms']
            or not saved['expires_ms'] <= accepted['expires_ms'] <= offer['expires_ms']
            or any(getattr(admission, name) != getattr(receipt, name) for name in
                ('transfer_id', 'manifest_sha256', 'acceptance_sha256', 'permission_epoch', 'destination_token'))):
        raise TransferError('media_saved_readback_original_exchange_required')
