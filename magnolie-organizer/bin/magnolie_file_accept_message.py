"""Exact accepted-offer metadata; no wire token confers native write authority."""
from dataclasses import dataclass
import uuid

from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_offer import validate_offer
from magnolie_file_sources import _body
from magnolie_file_control import MAX_TTL_MS, _hex
from magnolie_file_transfer import TransferError
from magnolie_telefon import now_ms, valid_uuid

KIND = 'file_transfer.accept'

@dataclass(frozen=True)
class RemoteFileAcceptance:
    offer_id: str
    manifest_sha256: str
    transfer_id: str
    acceptance_sha256: str
    permission_epoch: str
    destination_token: str

def parse_acceptance(message, *, now=None):
    body = _body(message, KIND, now_ms() if now is None else now)
    if (set(body) != {'format','offer_id','manifest_sha256','transfer_id','acceptance_sha256','permission_epoch','destination_token'}
            or not valid_uuid(body['offer_id'],version=4) or type(body['transfer_id']) is not str
            or len(body['transfer_id']) != 32 or any(value not in '0123456789abcdef' for value in body['transfer_id'])
            or any(not _hex(body[key]) for key in ('manifest_sha256','acceptance_sha256','permission_epoch','destination_token'))):
        raise TransferError('file_accept_invalid_envelope')
    return RemoteFileAcceptance(body['offer_id'],body['manifest_sha256'],body['transfer_id'],
                                body['acceptance_sha256'],body['permission_epoch'],body['destination_token'])

def create_acceptance(accepted, offer, current_binding, *, now=None, message_id=None):
    if type(accepted) is not NativeAcceptedTransfer:
        raise TransferError('file_accept_native_context_required')
    at=now_ms() if now is None else now
    accepted.verify(current_binding)
    manifest=validate_offer(offer,sender_id=accepted.binding.sender_id,receiver_id=accepted.binding.receiver_id,now=at)
    if manifest != accepted.manifest or at >= offer['expires_ms']:
        raise TransferError('file_accept_offer_changed')
    body=dict(format=1,offer_id=offer['message_id'],manifest_sha256=manifest.fingerprint,transfer_id=manifest.transfer_id,
              acceptance_sha256=accepted.fingerprint,permission_epoch=accepted.binding.permission_epoch,
              destination_token=accepted.binding.destination_token)
    message=dict(type='message',v=1,message_id=str(uuid.uuid4()) if message_id is None else message_id,kind=KIND,
                 created_ms=at,expires_ms=at+min(MAX_TTL_MS,offer['expires_ms']-at),body=body)
    parse_acceptance(message,now=at)
    accepted.verify(current_binding)
    return message
