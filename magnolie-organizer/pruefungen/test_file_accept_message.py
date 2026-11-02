from dataclasses import replace
from pathlib import Path
import sys
import json
import hashlib
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_accept_message import parse_acceptance, create_acceptance
from magnolie_file_offer import create_offer
from magnolie_file_transfer import TransferError
from test_file_receive import Fixture

NOW=1_800_000_000_000

@pytest.fixture
def fixture(tmp_path):
    f=Fixture(tmp_path)
    try: yield f
    finally: f.close()

def accepted_message(f):
    operation=f.accept()
    offer=create_offer(operation.job.accepted.manifest,now=NOW)
    return operation,offer,operation.acceptance_message(offer,now=NOW)

def test_actual_receive_admission_exports_only_exact_offer_and_native_destination_token(fixture):
    op,offer,message=accepted_message(fixture)
    parsed=parse_acceptance(message,now=NOW)
    assert parsed.offer_id==offer['message_id']
    assert parsed.manifest_sha256==op.job.accepted.manifest.fingerprint
    assert parsed.acceptance_sha256==op.job.accepted.fingerprint
    assert parsed.destination_token==op.job.accepted.binding.destination_token
    assert not hasattr(parsed,'path') and not hasattr(parsed,'is_saved_receipt')
    assert all(not (fixture.destination/path).exists() for _,path in op.job.accepted.targets)
    assert op.progress().verified_bytes==0

@pytest.mark.parametrize('key,value',[('format',True),('offer_id','wrong'),('manifest_sha256','short'),
    ('transfer_id','A'*32),('permission_epoch','old'),('destination_token',True),('path','/private'),('saved',True),('read_granted',True)])
def test_malformed_acceptance_never_becomes_authority_or_saved_receipt(fixture,key,value):
    _,_,message=accepted_message(fixture);message['body'][key]=value
    with pytest.raises(TransferError):parse_acceptance(message,now=NOW)

def test_acceptance_builder_requires_exact_offer_and_fresh_native_binding(fixture):
    op,offer,_=accepted_message(fixture)
    wrong=dict(offer);wrong['body']=dict(offer['body']);wrong['body']['manifest_sha256']='a'*64
    with pytest.raises(TransferError):op.acceptance_message(wrong,now=NOW)
    fixture.current=replace(fixture.binding,permission_epoch='b'*64)
    with pytest.raises(TransferError):op.acceptance_message(offer,now=NOW)

def test_closed_native_receiver_cannot_export_acceptance_or_create_a_saved_result(fixture):
    op,offer,_=accepted_message(fixture);op.close()
    with pytest.raises(TransferError):op.acceptance_message(offer,now=NOW)
    with pytest.raises(TransferError):create_acceptance({},offer,lambda:fixture.current,now=NOW)

def test_acceptance_and_offer_deadline_are_strict_and_whole_envelope_bounded(fixture):
    op,offer,message=accepted_message(fixture)
    with pytest.raises(TransferError):parse_acceptance(message,now=NOW+60_000)
    with pytest.raises(TransferError):op.acceptance_message(offer,now=NOW+60_000)
    message['body']['oversized']='x'*9000
    with pytest.raises(TransferError):parse_acceptance(message,now=NOW)

def test_shared_acceptance_golden_is_exact_canonical_metadata_without_authority():
    from magnolie_telefon import canonical
    vector=json.loads((Path(__file__).resolve().parents[2]/'contracts/file-transfer-acceptance-v1-vectors.json').read_text())
    parsed=parse_acceptance(vector['acceptance'],now=vector['now_ms'])
    wire=canonical(vector['acceptance'])
    assert len(wire)==vector['canonical_bytes']
    assert hashlib.sha256(wire).hexdigest()==vector['canonical_sha256']
    assert parsed.destination_token=='e'*64
