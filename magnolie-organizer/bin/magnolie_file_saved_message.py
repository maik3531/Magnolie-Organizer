"""Projection of protected local saved receipts; remote metadata is not a grant."""
from dataclasses import dataclass
import uuid

from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_receipt import NativeSavedFileReceipt
from magnolie_file_sources import _body
from magnolie_file_control import MAX_TTL_MS, _hex
from magnolie_file_transfer import FileManifest, TransferError
from magnolie_telefon import APPLICATION_MAX, canonical, now_ms

KIND='file_transfer.saved'

@dataclass(frozen=True)
class RemoteSavedMember:
    file_id: str
    size: int
    sha256: str
    receipt_sha256: str

@dataclass(frozen=True)
class RemoteSavedConfirmation:
    transfer_id: str
    manifest_sha256: str
    acceptance_sha256: str
    permission_epoch: str
    destination_token: str
    receipts: tuple

def parse_saved(message,manifest,*,now=None):
    if (type(manifest) is not FileManifest or type(message) is not dict or type(message.get('body')) is not dict
            or len(canonical(message))>APPLICATION_MAX):raise TransferError('file_saved_invalid_confirmation')
    body=message['body']
    if set(body)!={'format','transfer_id','manifest_sha256','acceptance_sha256','permission_epoch','destination_token','receipts'}:
        raise TransferError('file_saved_invalid_confirmation')
    _body(dict(message,body={key:value for key,value in body.items() if key!='receipts'}),KIND,now_ms() if now is None else now)
    if (body['transfer_id']!=manifest.transfer_id or body['manifest_sha256']!=manifest.fingerprint
            or any(not _hex(body[key]) for key in ('acceptance_sha256','permission_epoch','destination_token'))
            or type(body['receipts']) is not list or len(body['receipts'])!=len(manifest.files)):
        raise TransferError('file_saved_invalid_confirmation')
    receipts=[]
    for raw,file in zip(body['receipts'],manifest.files):
        if (type(raw) is not dict or set(raw)!={'file_id','size','sha256','receipt_sha256'} or raw['file_id']!=file.id
                or type(raw['size']) is not int or raw['size']!=file.size or raw['sha256']!=file.sha256 or not _hex(raw['receipt_sha256'])):
            raise TransferError('file_saved_invalid_confirmation')
        receipts.append(RemoteSavedMember(file.id,file.size,file.sha256,raw['receipt_sha256']))
    return RemoteSavedConfirmation(manifest.transfer_id,manifest.fingerprint,body['acceptance_sha256'],body['permission_epoch'],body['destination_token'],tuple(receipts))

def create_saved(accepted,receipts,current_binding,owner,*,now=None,message_id=None):
    if type(accepted) is not NativeAcceptedTransfer or type(receipts) is not tuple:
        raise TransferError('file_saved_native_context_required')
    accepted.verify(current_binding)
    if any(type(receipt) is not NativeSavedFileReceipt for receipt in receipts):raise TransferError('file_saved_native_context_required')
    indexed={receipt.file_id:receipt for receipt in receipts}
    if len(indexed)!=len(receipts) or set(indexed)!={file.id for file in accepted.manifest.files}:
        raise TransferError('file_saved_incomplete_native_receipts')
    members=[]
    for file in accepted.manifest.files:
        receipt=indexed[file.id]
        if (receipt.owner!=owner or receipt.manifest_sha256!=accepted.manifest.fingerprint or receipt.accepted_sha256!=accepted.fingerprint
                or receipt.relative_path!=dict(accepted.targets)[file.id] or receipt.size!=file.size or receipt.sha256!=file.sha256):
            raise TransferError('file_saved_native_receipt_changed')
        members.append(dict(file_id=file.id,size=file.size,sha256=file.sha256,receipt_sha256=receipt.protected_record_sha256))
    at=now_ms() if now is None else now
    body=dict(format=1,transfer_id=accepted.manifest.transfer_id,manifest_sha256=accepted.manifest.fingerprint,
              acceptance_sha256=accepted.fingerprint,permission_epoch=accepted.binding.permission_epoch,
              destination_token=accepted.binding.destination_token,receipts=members)
    message=dict(type='message',v=1,message_id=str(uuid.uuid4()) if message_id is None else message_id,kind=KIND,
                 created_ms=at,expires_ms=at+MAX_TTL_MS,body=body)
    parse_saved(message,accepted.manifest,now=at)
    accepted.verify(current_binding)
    return message
