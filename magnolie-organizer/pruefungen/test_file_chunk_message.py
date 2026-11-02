from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import base64
import sys
import uuid
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_chunk_message import parse_request,parse_chunk,RESULT
from magnolie_file_transfer import CHUNK_BYTES,TransferError
from test_file_receive import Fixture

NOW=1_800_000_000_000

@pytest.fixture
def fixture(tmp_path):
    f=Fixture(tmp_path)
    try:yield f
    finally:f.close()

def response(request,data):
    return dict(type='message',v=1,message_id=str(uuid.uuid4()),kind=RESULT,created_ms=NOW,expires_ms=NOW+60_000,
                body=dict(request['body'],request_id=request['message_id'],data_base64=base64.b64encode(data).decode('ascii'),data_sha256=sha256(data).hexdigest()))

def request(f,data=b'hello'):
    operation=f.accept(data)
    return operation,operation.chunk_request_message(operation.job.accepted.manifest.files[0].id,0,now=NOW)

@pytest.mark.parametrize('data',[b'hello',b'a'*CHUNK_BYTES,b'a'*CHUNK_BYTES+b'tail'])
def test_actual_receiver_correlates_chunks_and_records_only_durable_readback_not_saved_receipts(fixture,data):
    op,first=request(fixture,data)
    file=op.job.accepted.manifest.files[0]
    for index in range(file.chunks):
        req=first if index==0 else op.chunk_request_message(file.id,index,now=NOW)
        reply=response(req,data[index*CHUNK_BYTES:(index+1)*CHUNK_BYTES])
        progress=op.receive_chunk_message(reply,req,now=NOW)
        assert not progress.is_saved_receipt
        assert op.receive_chunk_message(reply,req,now=NOW).verified_bytes==progress.verified_bytes
    assert op.progress().verified_bytes==len(data)
    assert op.progress().checkpoint_verified_bytes==len(data)
    assert not (fixture.destination/op.job.accepted.targets[0][1]).exists()
    assert len(fixture.catalog.jobs())==1

@pytest.mark.parametrize('key,value',[('chunk_index',True),('chunk_index','0'),('chunk_index',800),('file_id','../private'),
    ('path','/private'),('saved',True),('destination_token','old')])
def test_request_has_only_exact_member_and_accepted_native_context(fixture,key,value):
    _,req=request(fixture);req['body'][key]=value
    with pytest.raises(TransferError):parse_request(req,now=NOW)

@pytest.mark.parametrize('key,value',[('request_id','11111111-1111-4111-8111-111111111111'),('destination_token','f'*64),
    ('acceptance_sha256','e'*64),('chunk_index',True),('data_base64','aGVsbG8'),('data_base64','aGVsbG8=\n'),
    ('data_base64',''),('data_sha256','f'*64),('saved',True)])
def test_invalid_chunk_or_correlation_never_touches_native_staging(fixture,key,value):
    op,req=request(fixture);reply=response(req,b'hello');reply['body'][key]=value
    with pytest.raises(TransferError):op.receive_chunk_message(reply,req,now=NOW)
    assert op.progress().verified_bytes==0

def test_native_binding_revocation_blocks_chunk_output_requests_and_staging(fixture):
    op,req=request(fixture);reply=response(req,b'hello')
    fixture.current=replace(fixture.binding,permission_epoch='b'*64)
    with pytest.raises(TransferError):op.receive_chunk_message(reply,req,now=NOW)
    with pytest.raises(TransferError):op.chunk_request_message(op.job.accepted.manifest.files[0].id,0,now=NOW)

def test_expired_request_cannot_be_revived_by_a_fresh_response_header(fixture):
    op,req=request(fixture);reply=response(req,b'hello')
    reply['created_ms']=NOW+60_000;reply['expires_ms']=NOW+120_000
    with pytest.raises(TransferError):op.receive_chunk_message(reply,req,now=NOW+60_000)
    assert op.progress().verified_bytes==0

def test_duplicate_different_bytes_cannot_replace_a_verified_native_chunk(fixture):
    op,req=request(fixture);op.receive_chunk_message(response(req,b'hello'),req,now=NOW)
    with pytest.raises(TransferError):op.receive_chunk_message(response(req,b'HELLO'),req,now=NOW)
    assert not (fixture.destination/op.job.accepted.targets[0][1]).exists()
    assert len(fixture.catalog.jobs())==1

def test_empty_file_has_no_chunk_to_request(fixture):
    op=fixture.accept(b'')
    with pytest.raises(TransferError):op.chunk_request_message(op.job.accepted.manifest.files[0].id,0,now=NOW)
