"""Native save confirmation follows durable mapping, never re-publication."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_photo_mappings import ProtectedPhotoMappings,PhotoMappingAssociation
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_photo_mappings import save


def saved_messages(fixture):
    return [call.args[0] for call in fixture[2].send.call_args_list if call.args[0]['kind']=='file_transfer.saved']


def test_actual_mapping_is_durable_and_matches_original_receipt_before_saved_socket_output(receiving):
    connection=receiving[3];receiver,pages,association=save(receiving,publish=False)
    inspected=[]
    def output(message):
        if message['kind']=='file_transfer.saved':
            snapshot,records=connection._mappings.lookup((association,))
            receipt=receiver._index.saved_receipts()[0]
            assert snapshot.count==1 and records[0].receipt_sha256==receipt.protected_record_sha256
            inspected.append(records[0])
    receiving[2].send.side_effect=output
    connection.publish_received(connection.issue_receive_action())
    assert len(inspected)==1 and len(saved_messages(receiving))==1
    assert (receiving[4]/inspected[0].relative_path).read_bytes()==b'hello'
    assert len(connection._catalog.jobs())==1


@pytest.mark.parametrize('cache',['cleared','changed'])
def test_original_protected_job_history_not_mutable_current_page_cache_supplies_mapping(receiving,cache):
    connection=receiving[3];receiver,pages,association=save(receiving,publish=False)
    connection._source_media_pages=() if cache=='cleared' else tuple(replace(page,source_epoch='e'*64) for page in pages)
    connection._source_media_entries=None
    connection.publish_received(connection.issue_receive_action())
    snapshot,records=connection._mappings.lookup((association,))
    assert snapshot.count==1 and records[0].association==association
    assert receiver._index.media_history.source_epoch==association.source_epoch
    foreign=PhotoMappingAssociation('e'*64,association.photo_id,association.media_type)
    assert connection._mappings.lookup((foreign,))[1]==(None,)
    assert len(saved_messages(receiving))==1


@pytest.mark.parametrize('state',['edited','deleted','replaced'])
def test_failed_mapping_protection_sends_no_saved_and_retry_preserves_user_changes_without_publication(receiving,monkeypatch,state):
    connection=receiving[3];receiver,pages,association=save(receiving,publish=False)
    owner=connection._mappings;protect=owner._protect
    def failed(value,label):
        if label.startswith('mapping/'):raise OSError('fixture mapping seal failed after real save')
        return protect(value,label)
    monkeypatch.setattr(owner,'_protect',failed)
    with pytest.raises(OSError,match='after real save'):connection.publish_received(connection.issue_receive_action())
    assert not saved_messages(receiving) and receiver._index.saved_receipts()
    target=receiving[4]/receiver._index.saved_receipts()[0].relative_path
    if state=='edited':target.write_bytes(b'keep PC edit')
    elif state=='deleted':target.unlink() # Explicit fixture user deletion only.
    else:
        other=target.with_name('replacement.jpg');other.write_bytes(b'keep user replacement');other.replace(target)
    before=target.read_bytes() if target.exists() else None
    def forbidden(*args,**kwargs):raise AssertionError('saved retry must never publish again')
    monkeypatch.setattr(receiver._publisher,'publish',forbidden)
    monkeypatch.setattr(owner,'_protect',protect)
    connection.send_saved_confirmation()
    snapshot,records=owner.lookup((association,))
    assert snapshot.count==1 and records[0].saved_sha256==receiver._index.saved_receipts()[0].sha256
    assert (target.read_bytes() if target.exists() else None)==before
    connection.send_saved_confirmation()
    assert owner.lookup((association,))==(snapshot,records) and len(saved_messages(receiving))==2
    assert len(connection._catalog.jobs())==1


def test_lost_mapping_postcommit_sync_requires_reopen_and_never_reports_saved_or_republishes_early(receiving,monkeypatch):
    connection=receiving[3];receiver,pages,association=save(receiving,publish=False)
    owner=connection._mappings;sync=owner._sync
    def interrupted():
        if owner._db.execute('SELECT count(*) FROM mappings').fetchone()==(1,):
            raise OSError('fixture mapping directory sync lost')
        sync()
    monkeypatch.setattr(owner,'_sync',interrupted)
    with pytest.raises(OSError,match='sync lost'):connection.publish_received(connection.issue_receive_action())
    assert owner._uncertain and not saved_messages(receiving)
    with pytest.raises(TransferError):connection.send_saved_confirmation()
    assert not saved_messages(receiving)
    target=receiving[4]/receiver._index.saved_receipts()[0].relative_path;target.write_bytes(b'edit after lost sync')
    def forbidden(*args,**kwargs):raise AssertionError('metadata recovery must not publish')
    monkeypatch.setattr(receiver._publisher,'publish',forbidden)
    # Explicit test-side native metadata reopen of the same original store; this
    # is not a production reset or a full restart/missing-store recovery API.
    original=(owner._root_key,owner._db_key,owner._lock_key);owner.close()
    connection._mappings=ProtectedPhotoMappings(connection._authority)
    connection.send_saved_confirmation()
    reopened=connection._mappings
    assert (reopened._root_key,reopened._db_key,reopened._lock_key)==original
    assert reopened.lookup((association,))[0].count==1
    assert target.read_bytes()==b'edit after lost sync' and len(saved_messages(receiving))==1
