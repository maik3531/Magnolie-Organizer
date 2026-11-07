"""Private published-row readback codec (#413), NEVER Saved or write rights.

Encoding metadata does not prove native provider work. Only the separate actual
Android producer can send this after a fresh owned original readback. This codec
is not registered in production dispatch or native source completion handling.
"""
from dataclasses import dataclass,asdict
from hashlib import sha256
import copy
import re

from magnolie_file_control import _hex
from magnolie_file_transfer import NativeTransferBinding,TransferError,MAX_FILE_BYTES
from magnolie_file_sources import _body
from magnolie_file_offer import validate_offer
from magnolie_telefon import canonical,now_ms,valid_uuid

KIND='file_transfer.published.readback'
CONTEXT=frozenset(('format','offer_id','manifest_sha256','transfer_id','source_id','file_id','size','sha256','media_type',
    'mime_type','publication_sha256','row_sha256','permission_epoch','readback_nonce'))
DESTINATION_DOMAIN='magnolie-published-readback-destination-v1\0'
BINDING_DOMAIN='magnolie-published-readback-binding-v1\0'
READBACK_DOMAIN='magnolie-published-readback-v1\0'


def _fail():raise TransferError('file_published_readback_invalid')
def _digest(domain,value):return sha256(domain.encode('utf-8')+canonical(value)).hexdigest()


def _context(value):
    if (type(value) is not dict or set(value)!=CONTEXT or type(value['format']) is not int or value['format']!=1
            or not valid_uuid(value['offer_id'],version=4) or type(value['size']) is not int or not 1<=value['size']<=MAX_FILE_BYTES
            or type(value['media_type']) is not str or value['media_type'] not in ('images','video')
            or type(value['mime_type']) is not str
            or not re.fullmatch(('image/' if value['media_type']=='images' else 'video/')+r'[a-z0-9.+-]{1,80}',value['mime_type'])):_fail()
    for name in ('manifest_sha256','sha256','publication_sha256','row_sha256','permission_epoch','readback_nonce'):
        if not _hex(value[name]):_fail()
    for name in ('transfer_id','source_id','file_id'):
        if type(value[name]) is not str or not re.fullmatch('[0-9a-f]{32}',value[name]):_fail()
    return value


def destination_token(context):return _digest(DESTINATION_DOMAIN,_context(context))


def encode_body(context,binding):
    """Pure metadata codec; NOT a native readback/receipt factory."""
    context=copy.deepcopy(_context(context))
    if (type(binding) is not NativeTransferBinding or binding.permission_epoch!=context['permission_epoch']
            or binding.destination_token!=destination_token(context)):_fail()
    body=dict(context,destination_token=binding.destination_token,binding_sha256=_digest(BINDING_DOMAIN,asdict(binding)))
    return dict(body,readback_sha256=_digest(READBACK_DOMAIN,body))


@dataclass(frozen=True)
class RemotePublishedReadback:
    _body: dict
    @property
    def body(self):return copy.deepcopy(self._body)
    @property
    def grants_write_authority(self):return False
    @property
    def is_saved_receipt(self):return False
    @property
    def allows_chunk_output(self):return False


def parse_readback(message,offer,binding,kind,*,now=None):
    at=now_ms() if now is None else now
    if type(binding) is not NativeTransferBinding or kind not in ('images','video'):_fail()
    body=_body(message,KIND,at)
    if set(body)!=CONTEXT|{'destination_token','binding_sha256','readback_sha256'}:_fail()
    context={name:body[name] for name in CONTEXT}
    if encode_body(context,binding)!=body:_fail()
    manifest=validate_offer(offer,sender_id=binding.sender_id,receiver_id=binding.receiver_id,now=at)
    if (len(manifest.files)!=1 or at<offer['created_ms'] or at>=offer['expires_ms']
            or message['created_ms']<offer['created_ms'] or message['expires_ms']>offer['expires_ms']
            or body['offer_id']!=offer['message_id'] or body['manifest_sha256']!=manifest.fingerprint
            or body['transfer_id']!=manifest.transfer_id or body['source_id']!=manifest.source_id
            or body['file_id']!=manifest.files[0].id or body['size']!=manifest.files[0].size
            or body['sha256']!=manifest.files[0].sha256 or body['media_type']!=kind):_fail()
    return RemotePublishedReadback(copy.deepcopy(body))
