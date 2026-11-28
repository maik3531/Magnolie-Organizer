"""Whole-original-offer readback metadata codec (Refs #330).

Separate from v1 on purpose: a member or an old single-file consumer must
never stand in for complete batch readback/retirement. No native rights here.
"""
from dataclasses import dataclass, asdict
from hashlib import sha256
import copy
import re

from magnolie_file_control import _hex, MAX_TTL_MS
from magnolie_file_transfer import NativeTransferBinding, TransferError, MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES
from magnolie_file_offer import validate_offer
from magnolie_telefon import APPLICATION_MAX, canonical, now_ms, valid_uuid, CLOCK_SKEW_MS

KIND = 'file_transfer.published.readback'
CONTEXT = frozenset(('format', 'offer_id', 'manifest_sha256', 'transfer_id', 'source_id',
    'media_type', 'members', 'permission_epoch', 'readback_nonce'))
MEMBER = frozenset(('size', 'sha256', 'mime_type', 'publication_sha256', 'row_sha256'))
DESTINATION_DOMAIN = 'magnolie-published-readback-destination-v2\0'
BINDING_DOMAIN = 'magnolie-published-readback-binding-v2\0'
READBACK_DOMAIN = 'magnolie-published-readback-v2\0'


def _fail(): raise TransferError('file_published_batch_readback_invalid')
def _digest(domain, value): return sha256(domain.encode('utf-8') + canonical(value)).hexdigest()


def _context(value):
    if (type(value) is not dict or set(value) != CONTEXT or type(value['format']) is not int or value['format'] != 2
            or not valid_uuid(value['offer_id'], version=4) or value['media_type'] not in ('images', 'video')
            or type(value['members']) is not dict or not 1 <= len(value['members']) <= MAX_FILES): _fail()
    for key in ('manifest_sha256', 'permission_epoch', 'readback_nonce'):
        if not _hex(value[key]): _fail()
    for key in ('transfer_id', 'source_id'):
        if type(value[key]) is not str or not re.fullmatch('[0-9a-f]{32}', value[key]): _fail()
    publications, rows, total = set(), set(), 0
    for file_id, member in value['members'].items():
        if (type(file_id) is not str or not re.fullmatch('[0-9a-f]{32}', file_id) or type(member) is not dict
                or set(member) != MEMBER or type(member['size']) is not int or not 1 <= member['size'] <= MAX_FILE_BYTES
                or type(member['mime_type']) is not str or not re.fullmatch(
                    ('image/' if value['media_type'] == 'images' else 'video/') + r'[a-z0-9.+-]{1,80}', member['mime_type'])): _fail()
        for key in ('sha256', 'publication_sha256', 'row_sha256'):
            if not _hex(member[key]): _fail()
        if member['publication_sha256'] in publications or member['row_sha256'] in rows: _fail()
        publications.add(member['publication_sha256']); rows.add(member['row_sha256']); total += member['size']
    if total > MAX_TOTAL_BYTES: _fail()
    return value


def destination_token(context): return _digest(DESTINATION_DOMAIN, _context(context))


def encode_body(context, binding):
    """Pure bounded metadata codec, never a native completion permit."""
    context = copy.deepcopy(_context(context))
    if (type(binding) is not NativeTransferBinding or binding.permission_epoch != context['permission_epoch']
            or binding.destination_token != destination_token(context)): _fail()
    body = dict(context, destination_token=binding.destination_token, binding_sha256=_digest(BINDING_DOMAIN, asdict(binding)))
    return dict(body, readback_sha256=_digest(READBACK_DOMAIN, body))


@dataclass(frozen=True)
class RemotePublishedBatchReadback:
    _body: dict
    @property
    def body(self): return copy.deepcopy(self._body)
    @property
    def grants_write_authority(self): return False
    @property
    def is_saved_receipt(self): return False
    @property
    def allows_chunk_output(self): return False


def parse_batch_readback(message, offer, binding, kind, *, now=None):
    at = now_ms() if now is None else now
    if type(binding) is not NativeTransferBinding or kind not in ('images', 'video'): _fail()
    # The v1 sources._body intentionally accepts only format=1. Do not relax
    # that shared single-file gate or rewrite the original packet to pass it.
    if (type(at) is not int or type(message) is not dict or set(message) != {
            'type', 'v', 'message_id', 'kind', 'created_ms', 'expires_ms', 'body'}
            or message['type'] != 'message' or type(message['v']) is not int or message['v'] != 1
            or not valid_uuid(message['message_id'], version=4) or message['kind'] != KIND
            or type(message['created_ms']) is not int or not 0 <= message['created_ms'] <= 253_402_300_799_999
            or type(message['expires_ms']) is not int or not 1 <= message['expires_ms'] - message['created_ms'] <= MAX_TTL_MS
            or at >= message['expires_ms'] or message['created_ms'] > at + CLOCK_SKEW_MS
            or type(message['body']) is not dict or len(canonical(message)) > APPLICATION_MAX): _fail()
    body = message['body']
    if set(body) != CONTEXT | {'destination_token', 'binding_sha256', 'readback_sha256'}: _fail()
    if encode_body({key: body[key] for key in CONTEXT}, binding) != body: _fail()
    manifest = validate_offer(offer, sender_id=binding.sender_id, receiver_id=binding.receiver_id, now=at)
    if (at < offer['created_ms'] or at >= offer['expires_ms'] or message['created_ms'] < offer['created_ms']
            or message['expires_ms'] > offer['expires_ms'] or body['offer_id'] != offer['message_id']
            or body['manifest_sha256'] != manifest.fingerprint or body['transfer_id'] != manifest.transfer_id
            or body['source_id'] != manifest.source_id or body['media_type'] != kind
            or set(body['members']) != {file.id for file in manifest.files}): _fail()
    for file in manifest.files:
        member = body['members'][file.id]
        if member['size'] != file.size or member['sha256'] != file.sha256: _fail()
    return RemotePublishedBatchReadback(copy.deepcopy(body))
