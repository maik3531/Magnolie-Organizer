"""Exact post-mapping evidence from actual native receiver/store objects."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_photo_mapping_receipt import SavedPhotoMappingReceipt
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_photo_mappings import save


def evidence(fixture):
    connection=fixture[3];receiver,pages,association=save(fixture,publish=False)
    connection.publish_received(connection.issue_receive_action())
    owner=connection._mappings;snapshot,records=owner.lookup((association,))
    checkpoint=owner.checkpoint(owner._store_witness())
    assert snapshot.version==checkpoint.version
    return receiver,receiver._index.media_history,receiver._index.saved_receipts(),records,checkpoint


def test_actual_saved_mapping_evidence_roundtrips_without_claiming_presence_authority_or_book_ack(receiving):
    receiver,history,receipts,records,checkpoint=evidence(receiving)
    value=SavedPhotoMappingReceipt.capture(receiver._accepted,history,receiver.job.owner,receipts,records,checkpoint)
    assert value.entries[0].saved_receipt_sha256==receipts[0].protected_record_sha256
    assert value.entries[0].mapping_record_sha256==records[0].protected_record_sha256
    assert SavedPhotoMappingReceipt.parse(value.wire(),receiver._accepted,history,receiver.job.owner,receipts)==value
    assert not value.grants_write_authority and not value.is_saved_receipt and not value.is_book_save_ack


@pytest.mark.parametrize('field',['owner','accepted_sha256','history_sha256','entries','store','extra'])
def test_changed_post_mapping_context_is_rejected_not_normalized(receiving,field):
    receiver,history,receipts,records,checkpoint=evidence(receiving)
    original=SavedPhotoMappingReceipt.capture(receiver._accepted,history,receiver.job.owner,receipts,records,checkpoint)
    wire=deepcopy(original.wire())
    if field=='entries':wire[field][0]['saved_receipt_sha256']='e'*64
    elif field=='store':wire[field]['count']=True
    elif field=='extra':wire[field]=True
    else:wire[field]='f'*64
    with pytest.raises(TransferError):SavedPhotoMappingReceipt.parse(wire,receiver._accepted,history,receiver.job.owner,receipts)


def test_historical_evidence_keeps_original_hashes_after_pc_edit_without_rewriting_file(receiving):
    receiver,history,receipts,records,checkpoint=evidence(receiving)
    target=receiving[4]/receipts[0].relative_path;target.write_bytes(b'preserve newer PC crop')
    value=SavedPhotoMappingReceipt.capture(receiver._accepted,history,receiver.job.owner,receipts,records,checkpoint)
    assert value.entries[0].saved_receipt_sha256==receipts[0].protected_record_sha256
    assert target.read_bytes()==b'preserve newer PC crop'


@pytest.mark.parametrize('change',['association','receipt','target','job','manifest'])
def test_mapping_from_another_original_association_or_receipt_is_not_post_commit_evidence(receiving,change):
    receiver,history,receipts,records,checkpoint=evidence(receiving);record=records[0]
    if change=='association':record=replace(record,association=replace(record.association,photo_id='e'*64))
    elif change=='receipt':record=replace(record,receipt_sha256='e'*64)
    elif change=='target':record=replace(record,relative_path='another-target.jpg')
    elif change=='job':record=replace(record,job_owner='e'*32)
    else:record=replace(record,manifest_sha256='e'*64)
    with pytest.raises(TransferError):
        SavedPhotoMappingReceipt.capture(receiver._accepted,history,receiver.job.owner,receipts,(record,),checkpoint)
