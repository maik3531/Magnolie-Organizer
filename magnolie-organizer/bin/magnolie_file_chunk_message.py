"""Correlated source chunk messages, not checkpoints or publication receipts."""
import base64
from hashlib import sha256
import uuid

from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_control import MAX_TTL_MS, _hex
from magnolie_file_sources import _body
from magnolie_file_transfer import CHUNK_BYTES, MAX_FILE_BYTES, TransferError
from magnolie_telefon import APPLICATION_MAX, canonical, now_ms

REQUEST='file_transfer.chunk.request'
RESULT='file_transfer.chunk'
FIELDS={'format','transfer_id','manifest_sha256','acceptance_sha256','permission_epoch','destination_token','file_id','chunk_index'}

def parse_request(message,*,now=None):
    body=_body(message,REQUEST,now_ms() if now is None else now)
    if (set(body)!=FIELDS or any(not _hex(body[key]) for key in ('manifest_sha256','acceptance_sha256','permission_epoch','destination_token'))
            or any(type(body[key]) is not str or len(body[key])!=32 or any(ch not in '0123456789abcdef' for ch in body[key]) for key in ('transfer_id','file_id'))
            or type(body['chunk_index']) is not int or not 0<=body['chunk_index']<MAX_FILE_BYTES//CHUNK_BYTES):
        raise TransferError('file_chunk_invalid_request')
    return dict(body)

def _context(body,accepted,current_binding):
    if type(accepted) is not NativeAcceptedTransfer:raise TransferError('file_chunk_native_context_required')
    accepted.verify(current_binding)
    expected=dict(transfer_id=accepted.manifest.transfer_id,manifest_sha256=accepted.manifest.fingerprint,
                  acceptance_sha256=accepted.fingerprint,permission_epoch=accepted.binding.permission_epoch,
                  destination_token=accepted.binding.destination_token)
    if any(body[key]!=value for key,value in expected.items()):raise TransferError('file_chunk_acceptance_changed')
    file=next((entry for entry in accepted.manifest.files if entry.id==body['file_id']),None)
    if file is None or body['chunk_index']>=file.chunks:raise TransferError('file_chunk_member_not_accepted')
    return file

def create_request(accepted,current_binding,file_id,chunk_index,*,now=None,message_id=None):
    if type(accepted) is not NativeAcceptedTransfer:raise TransferError('file_chunk_native_context_required')
    at=now_ms() if now is None else now
    body=dict(format=1,transfer_id=accepted.manifest.transfer_id,manifest_sha256=accepted.manifest.fingerprint,
              acceptance_sha256=accepted.fingerprint,permission_epoch=accepted.binding.permission_epoch,
              destination_token=accepted.binding.destination_token,file_id=file_id,chunk_index=chunk_index)
    message=dict(type='message',v=1,message_id=str(uuid.uuid4()) if message_id is None else message_id,kind=REQUEST,
                 created_ms=at,expires_ms=at+MAX_TTL_MS,body=body)
    parse_request(message,now=at);_context(body,accepted,current_binding)
    return message

def parse_chunk(message,request,accepted,current_binding,*,now=None):
    at=now_ms() if now is None else now
    expected=parse_request(request,now=at)
    if type(message) is not dict or type(message.get('body')) is not dict or len(canonical(message))>APPLICATION_MAX:
        raise TransferError('file_chunk_invalid_response')
    body=message['body']
    if set(body)!=FIELDS|{'request_id','data_base64','data_sha256'}:raise TransferError('file_chunk_invalid_response')
    # Keep the ordinary strict header checks while applying the larger complete
    # application budget to chunk data, not the source-metadata 8192-byte budget.
    shadow=dict(message,body={key:value for key,value in body.items() if key!='data_base64'})
    _body(shadow,RESULT,at)
    if body['request_id']!=request['message_id'] or any(body[key]!=value or type(body[key]) is not type(value) for key,value in expected.items()):
        raise TransferError('file_chunk_request_changed')
    file=_context(expected,accepted,current_binding)
    if type(body['data_base64']) is not str or not _hex(body['data_sha256']):raise TransferError('file_chunk_invalid_response')
    try:data=base64.b64decode(body['data_base64'],validate=True)
    except (ValueError,TypeError) as error:raise TransferError('file_chunk_invalid_response') from error
    expected_size=min(CHUNK_BYTES,file.size-body['chunk_index']*CHUNK_BYTES)
    if (len(data)!=expected_size or base64.b64encode(data).decode('ascii')!=body['data_base64']
            or sha256(data).hexdigest()!=body['data_sha256']):raise TransferError('file_chunk_invalid_response')
    accepted.verify(current_binding)
    return data
