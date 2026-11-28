"""Durable readback evidence for the original PC source exchange.

Keep the original offer, acceptance, delivery bits and Saved unchanged. The
separate challenge and fresh binding must never be confused with that attempt.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256

from magnolie_file_transfer import FileManifest, NativeTransferBinding, TransferError
from magnolie_media_saved_readback import _require_pending_original, require_reply
from magnolie_telefon import canonical


def verify_recovered_pc_exchange(record, ready, local_key, peer_key):
    recovery = record.get('recovery')
    if (type(recovery) is not dict or set(recovery) != {'request', 'binding'}
            or record['phase'] != 'peer_readback' or type(record['peer_readback']) is not dict):
        raise TransferError('media_saved_readback_durable_proof_required')
    request, binding = recovery['request'], recovery['binding']
    packet = record['peer_readback']
    if (type(request) is not dict or type(request.get('body')) is not dict
            or set(request['body']) != {'format', 'binding_sha256', 'nonce'}
            or type(binding) is not dict or set(binding) != set(NativeTransferBinding.__dataclass_fields__)
            or type(packet.get('body')) is not dict):
        raise TransferError('media_saved_readback_durable_proof_invalid')
    manifest = FileManifest.parse(ready['manifest'])
    # Validate the original separately, without treating the new reply as part
    # of its header lifetime or original permission epoch.
    _require_pending_original(ready, dict(record, peer_readback=None), manifest)
    requested = NativeTransferBinding(**binding)
    if (requested.sender_identity_sha256 != local_key or requested.receiver_identity_sha256 != peer_key
            or requested.sender_id != manifest.sender_id or requested.receiver_id != manifest.receiver_id):
        raise TransferError('media_saved_readback_durable_proof_invalid')
    reply_binding = replace(requested, destination_token=packet['body'].get('destination_token'))
    original = dict(request, body=dict(request['body'], offer=record['offer'], saved=record['peer_saved']))
    require_reply(packet, original, requested, reply_binding, packet.get('created_ms'))


def record_recovered_pc_exchange(jobs, ready, previous, binding, request, response, current):
    """CAS the exact visible original version, storing no duplicate media data."""
    from magnolie_media_source_exchange import _NativeSourceExchange, _read_source_exchange
    from magnolie_media_source_retirement import _NativeSourceRetirementJournal

    current()
    job = ready.body['job_id']
    if (previous.body['phase'] != 'peer_saved' or request['body']['offer'] != previous.body['offer']
            or request['body']['saved'] != previous.body['peer_saved']):
        raise TransferError('media_saved_readback_original_exchange_required')
    challenge = dict(request, body={name: value for name, value in request['body'].items()
                                   if name not in ('offer', 'saved')})
    updated = dict(previous.body, phase='peer_readback', peer_readback=deepcopy(response),
                   recovery=dict(request=challenge, binding=asdict(binding)))
    peer = jobs._authority.current_peer()
    if peer is None or ready.body['pairing_epoch'] != peer.pairing_epoch:
        raise TransferError('media_saved_readback_original_exchange_required')
    verify_recovered_pc_exchange(updated, ready.body, jobs._authority.identity.receiver_identity_sha256,
                                 peer.identity_sha256)
    encoded = canonical(updated)
    max_bytes = _NativeSourceExchange.BATCH_MAX_BYTES if updated['format'] == 5 else _NativeSourceExchange.MAX_BYTES
    if len(encoded) > max_bytes:
        raise TransferError('media_source_exchange_record_size')
    name = jobs._catalog._exchange + job
    cipher = jobs._authority.protection.seal(encoded, name)
    with jobs._database() as (db, key):
        db.execute('BEGIN IMMEDIATE')
        catalog = jobs._catalog.verify(db, key)
        if (jobs._read(db, key, job) != ready or _read_source_exchange(jobs, db, key, job, ready) != previous
                or _NativeSourceRetirementJournal(jobs)._read(db, key, job) is not None):
            raise TransferError('media_saved_readback_original_exchange_required')
        current()
        db.execute('UPDATE meta SET value=? WHERE key=?', (cipher, name))
        result = _read_source_exchange(jobs, db, key, job, ready)
        if result is None or result.version != sha256(cipher).hexdigest():
            raise TransferError('media_source_exchange_readback_failed')
        jobs._catalog.advance(db, key, catalog)
        current()
    return result
