from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_acceptance import NativeAcceptedTransfer
from magnolie_file_saved_message import parse_saved
from magnolie_file_transfer import FileManifest,ManifestFile,TransferError
from test_file_receive import Fixture,feed
from test_file_chunk_message import NOW

@pytest.fixture
def fixture(tmp_path):
    f=Fixture(tmp_path)
    try:yield f
    finally:f.close()

def saved(f,data=b'hello'):
    op=f.accept(data);feed(op,data);op.publish_completed();op.commit_saved_receipts()
    return op,op.saved_receipt_message(now=NOW)

@pytest.mark.parametrize('data',[b'hello',b''])
def test_only_durable_native_receipt_readback_exports_complete_pathless_historical_confirmation(fixture,data):
    op,message=saved(fixture,data)
    native=op.commit_saved_receipts()[0]
    remote=parse_saved(message,op.job.accepted.manifest,now=NOW)
    assert remote.receipts[0].receipt_sha256==native.protected_record_sha256
    assert remote.receipts[0].size==len(data)
    assert not hasattr(remote,'is_saved_receipt') and not hasattr(remote,'quota_retired')
    assert 'relative_path' not in message['body']['receipts'][0] and 'file_key' not in message['body']['receipts'][0]
    assert len(fixture.catalog.jobs())==1

def test_verified_bytes_and_physical_publication_alone_never_export_saved_receipts(fixture):
    op=fixture.accept()
    with pytest.raises(TransferError):op.saved_receipt_message(now=NOW)
    feed(op,b'hello')
    with pytest.raises(TransferError):op.saved_receipt_message(now=NOW)
    op.publish_completed()
    with pytest.raises(TransferError):op.saved_receipt_message(now=NOW)
    op.commit_saved_receipts();assert parse_saved(op.saved_receipt_message(now=NOW),op.job.accepted.manifest,now=NOW).receipts

@pytest.mark.parametrize('field,value',[('receipts',[]),('receipts',[{}]),('success',True),('quota_retired',True),
    ('path','/private'),('manifest_sha256','a'*64),('acceptance_sha256',True),('permission_epoch','old')])
def test_remote_confirmation_is_exact_full_manifest_metadata_not_authority(fixture,field,value):
    op,message=saved(fixture);message['body'][field]=value
    with pytest.raises(TransferError):parse_saved(message,op.job.accepted.manifest,now=NOW)

def test_reopened_historical_receipts_do_not_republish_or_overwrite_later_pc_edits(fixture):
    f=fixture;op,message=saved(f);job=op.job
    target=f.destination/job.accepted.targets[0][1];target.write_bytes(b'my later PC edit');inode=target.stat().st_ino
    op.close();resumed=f.resume(job)
    again=resumed.saved_receipt_message(now=NOW)
    assert again['body']==message['body']
    assert target.read_bytes()==b'my later PC edit' and target.stat().st_ino==inode
    with pytest.raises(TransferError):resumed.publish_completed()
    assert len(f.catalog.jobs())==1

def test_partial_protected_receipt_commit_cannot_be_projected_as_complete_batch(fixture,monkeypatch):
    f=fixture
    files=tuple(ManifestFile(str(index)*32,'Camera/'+label,5,sha256(data).hexdigest())
        for index,label,data in [(1,'a.jpg',b'hello'),(2,'b.jpg',b'world')])
    manifest=FileManifest('a'*32,'b'*32,f.binding.sender_id,f.binding.receiver_id,files,10)
    accepted=NativeAcceptedTransfer.capture(manifest,f.binding,{file.id:file.path for file in files},f.destination,lambda:f.current)
    op=f.accept(accepted=accepted)
    for file,data in zip(files,[b'hello',b'world']):op.receive_chunk(file.id,0,data)
    op.publish_completed();original=op._index.commit_saved_file;calls=0
    def interrupted(*args):
        nonlocal calls
        calls+=1
        if calls==2:raise OSError('synthetic receipt commit interruption')
        return original(*args)
    monkeypatch.setattr(op._index,'commit_saved_file',interrupted)
    with pytest.raises(OSError):op.commit_saved_receipts()
    job=op.job;op.close();resumed=f.resume(job)
    with pytest.raises(TransferError):resumed.saved_receipt_message(now=NOW)
    assert all((f.destination/file.path).exists() for file in files) and len(f.catalog.jobs())==1

def test_confirmation_still_requires_current_native_binding_and_strict_deadline(fixture):
    f=fixture;op,message=saved(f)
    with pytest.raises(TransferError):parse_saved(message,op.job.accepted.manifest,now=NOW+60_000)
    f.current=replace(f.binding,permission_epoch='b'*64)
    with pytest.raises(TransferError):op.saved_receipt_message(now=NOW)
