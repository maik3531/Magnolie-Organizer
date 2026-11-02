from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_receive import NativeReceiveStartError
from magnolie_file_transfer import CHUNK_BYTES, FileManifest, ManifestFile, TransferError
from test_file_receive import Fixture
from test_file_chunk_message import response, NOW

@pytest.fixture
def fixture(tmp_path):
    f=Fixture(tmp_path)
    try:yield f
    finally:f.close()

def test_next_request_comes_from_durable_reopened_checkpoint_not_progress_totals(fixture):
    f=fixture; data=b'a'*CHUNK_BYTES+b'tail'; op=f.accept(data)
    first=op.next_chunk_request_message(now=NOW)
    assert first['body']['chunk_index']==0
    op.receive_chunk_message(response(first,data[:CHUNK_BYTES]),first,now=NOW)
    job=op.job;op.close()
    resumed=f.resume(f.catalog.jobs()[0])
    assert resumed.job==job
    second=resumed.next_chunk_request_message(now=NOW)
    assert second['body']['file_id']==first['body']['file_id'] and second['body']['chunk_index']==1
    assert second['message_id']!=first['message_id']
    resumed.receive_chunk_message(response(second,b'tail'),second,now=NOW)
    assert resumed.next_chunk_request_message(now=NOW) is None
    assert not resumed.progress().is_saved_receipt
    assert not (f.destination/job.accepted.targets[0][1]).exists()
    assert len(f.catalog.jobs())==1

def test_next_request_advances_across_the_exact_manifest_and_does_not_publish(fixture):
    f=fixture
    files=tuple(ManifestFile(identifier*32,'Camera/'+label,5,sha256(data).hexdigest())
        for identifier,label,data in [('1','a.jpg',b'hello'),('2','b.jpg',b'world')])
    manifest=FileManifest('a'*32,'b'*32,f.binding.sender_id,f.binding.receiver_id,files,10)
    accepted=NativeAcceptedTransfer.capture(manifest,f.binding,{file.id:file.path for file in files},f.destination,lambda:f.current)
    op=f.accept(accepted=accepted)
    for file,data in zip(files,[b'hello',b'world']):
        req=op.next_chunk_request_message(now=NOW)
        assert req['body']['file_id']==file.id
        op.receive_chunk_message(response(req,data),req,now=NOW)
    assert op.next_chunk_request_message(now=NOW) is None
    assert op.progress().verified_bytes==10
    assert all(not (f.destination/file.path).exists() for file in files)

def test_empty_file_no_missing_bytes_is_not_a_local_save_receipt(fixture):
    op=fixture.accept(b'')
    assert op.next_chunk_request_message(now=NOW) is None
    assert not op.progress().is_saved_receipt
    assert not (fixture.destination/op.job.accepted.targets[0][1]).exists()

def test_corrupt_staged_checkpoint_member_cannot_be_skipped_as_already_received(fixture):
    f=fixture; data=b'a'*CHUNK_BYTES+b'tail';op=f.accept(data)
    req=op.next_chunk_request_message(now=NOW)
    op.receive_chunk_message(response(req,data[:CHUNK_BYTES]),req,now=NOW)
    job=op.job;parent=f.catalog.require_reserved(job);op.close()
    path=parent/('file-transfer-'+job.owner)/(req['body']['file_id']+'-0.enc')
    original=path.read_bytes();changed=original[:-1]+bytes([original[-1]^1]);path.write_bytes(changed)
    with pytest.raises(NativeReceiveStartError):f.resume(job)
    assert path.read_bytes()==changed and len(f.catalog.jobs())==1
    assert not (f.destination/job.accepted.targets[0][1]).exists()

def test_next_request_cannot_outlive_native_binding_close_or_publication(fixture):
    f=fixture;op=f.accept()
    f.current=replace(f.binding,permission_epoch='b'*64)
    with pytest.raises(TransferError):op.next_chunk_request_message(now=NOW)
    f.current=f.binding
    req=op.next_chunk_request_message(now=NOW);op.receive_chunk_message(response(req,b'hello'),req,now=NOW)
    op.publish_completed()
    with pytest.raises(TransferError):op.next_chunk_request_message(now=NOW)
    op.close()
    with pytest.raises(TransferError):op.next_chunk_request_message(now=NOW)

def test_no_second_native_request_coordinator_can_adopt_an_owned_receiver(fixture):
    f=fixture;op=f.accept()
    with pytest.raises(NativeReceiveStartError):f.resume(op.job)
    assert op.next_chunk_request_message(now=NOW)['body']['chunk_index']==0
