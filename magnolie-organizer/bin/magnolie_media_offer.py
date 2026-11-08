"""Strict media metadata bridge; no native grant, provider action or dispatcher.

The ordinary offer remains unchanged. Its ID/manifest survive reconstruction so
the existing acceptance/chunk/Saved validators keep their original correlation.
"""
from dataclasses import dataclass
import copy
import re

from magnolie_file_offer import create_offer, validate_offer, KIND as FILE_OFFER
from magnolie_file_transfer import TransferError, MAX_FILE_BYTES
from magnolie_media_sync import validate_start, requested_for, effective
from magnolie_telefon import APPLICATION_MAX, canonical, now_ms

KIND = 'file_transfer.media_offer'
REFERENCE_FIELDS = frozenset(('source_epoch','photo_id','media_type','manifest_sha256','file_id','original_size','original_sha256','receipt_sha256'))


@dataclass(frozen=True)
class NativeMediaOffer:
    offer: dict
    manifest: object
    settings: dict
    media_type: str
    mime_types: dict
    originals: dict


def create_media_offer(manifest, settings, media_type, mime_types, originals, *, now=None, message_id=None):
    now = now_ms() if now is None else now
    message = create_offer(manifest, now=now, message_id=message_id)
    message['kind'] = KIND
    message['body'] = dict(format=1, offer=message['body'], settings=copy.deepcopy(settings),
        media_type=media_type, mime_types=copy.deepcopy(mime_types), originals=copy.deepcopy(originals))
    validate_media_offer(message, manifest.sender_id, manifest.receiver_id, now=now)
    return message


def validate_media_offer(message, sender_id, receiver_id, *, now=None):
    def fail():raise TransferError('media_offer_invalid_envelope')
    now = now_ms() if now is None else now
    try:encoded = canonical(message)
    except (ValueError, TypeError) as error:raise TransferError('media_offer_invalid_envelope') from error
    if (type(message) is not dict or message.get('kind') != KIND or len(encoded) > APPLICATION_MAX
            or type(message.get('expires_ms')) is not int or now >= message['expires_ms']):fail()
    body = message.get('body')
    if (type(body) is not dict or set(body) != {'format','offer','settings','media_type','mime_types','originals'}
            or type(body['format']) is not int or body['format'] != 1):fail()
    offer = copy.deepcopy(message);offer['kind'] = FILE_OFFER;offer['body'] = copy.deepcopy(body['offer'])
    manifest = validate_offer(offer, sender_id, receiver_id, now=now)
    try:validate_start(dict(format=1, settings=body['settings']))
    except ValueError as error:raise TransferError('media_offer_complete_settings_required') from error
    kind = body['media_type']
    if kind not in ('images','video') or not requested_for(body['settings'], kind, to_phone=True):fail()
    ids = {file.id for file in manifest.files};mime = body['mime_types'];originals = body['originals']
    if (type(mime) is not dict or set(mime) != ids or type(originals) is not dict or not set(originals) <= ids
            or effective(body['settings'])['collection_mode'] == 'phone_inventory' and set(originals) != ids):fail()
    prefix = 'image' if kind == 'images' else 'video'
    if any(type(value) is not str or re.fullmatch(prefix + r'/[a-z0-9][a-z0-9.+-]{0,126}', value) is None for value in mime.values()):fail()
    known = set()
    for reference in originals.values():
        if (type(reference) is not dict or set(reference) != REFERENCE_FIELDS or reference['media_type'] != kind
                or type(reference['file_id']) is not str or re.fullmatch('[0-9a-f]{32}', reference['file_id']) is None
                or type(reference['original_size']) is not int or not 1 <= reference['original_size'] <= MAX_FILE_BYTES
                or any(type(reference[field]) is not str or re.fullmatch('[0-9a-f]{64}', reference[field]) is None
                    for field in ('source_epoch','photo_id','manifest_sha256','original_sha256','receipt_sha256'))):fail()
        encoded = canonical(reference)
        if encoded in known:fail()
        known.add(encoded)
    return NativeMediaOffer(offer, manifest, copy.deepcopy(body['settings']), kind, copy.deepcopy(mime), copy.deepcopy(originals))
