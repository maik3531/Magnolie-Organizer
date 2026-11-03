"""Durable post-mapping receipts precede actual native saved socket output."""
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_file_desktop_mapping_save import saved_messages
from test_photo_mappings import save


def reopen(receiver):
    old=receiver._index
    return ProtectedTransferJobIndex(old._parent,old._expected_manifest,old._binding,old._current,
        old._seal,old._unseal,owner=receiver.job.owner)


def test_protected_mapping_receipt_exists_before_socket_and_reopens_with_original_history(receiving):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False);seen=[]
    def output(message):
        if message['kind']=='file_transfer.saved':
            seen.append(receiver._index.saved_mapping_receipt())
            assert seen[-1] is not None
    receiving[2].send.side_effect=output
    connection.publish_received(connection.issue_receive_action())
    index=receiver._index
    assert index._schema_version==3 and index._context['format']==4 and len(seen)==1
    history=index.media_history;receipts=index.saved_receipts();receiver.close()
    with_index=reopen(receiver)
    try:
        assert with_index.saved_mapping_receipt()==seen[0]
        assert with_index.media_history==history and with_index.saved_receipts()==receipts
    finally:with_index.close()


@pytest.mark.parametrize('change',['missing-row','changed-blob','missing-table','downgraded-schema'])
def test_mapping_receipt_loss_is_not_absence_or_permission_to_ack_after_reopen(receiving,change):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action());index=receiver._index
    with index._db:
        if change=='missing-row':index._db.execute('DELETE FROM mapping_receipt')
        elif change=='changed-blob':index._db.execute('UPDATE mapping_receipt SET payload=?',(b'preserve damaged receipt',))
        elif change=='missing-table':index._db.execute('DROP TABLE mapping_receipt')
        else:index._db.execute('PRAGMA user_version=2')
    before=len(saved_messages(receiving))
    with pytest.raises(TransferError):connection.send_saved_confirmation()
    assert len(saved_messages(receiving))==before
    receiver.close()
    with pytest.raises(TransferError):reopen(receiver)


def test_failed_receipt_seal_sends_no_saved_retry_preserves_pc_edit_and_does_not_publish(receiving,monkeypatch):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False);index=receiver._index;protect=index._protect
    def fail(value,label):
        if label=='mapping-receipt':raise OSError('fixture post-mapping seal failure')
        return protect(value,label)
    monkeypatch.setattr(index,'_protect',fail)
    with pytest.raises(OSError,match='post-mapping'):connection.publish_received(connection.issue_receive_action())
    assert not saved_messages(receiving) and index.saved_mapping_receipt() is None
    receipts=index.saved_receipts();target=receiving[4]/receipts[0].relative_path;target.write_bytes(b'keep newer crop')
    def forbidden(*args,**kwargs):raise AssertionError('receipt retry must not publish')
    monkeypatch.setattr(receiver._publisher,'publish',forbidden);monkeypatch.setattr(index,'_protect',protect)
    connection.send_saved_confirmation();original=index.saved_mapping_receipt()
    blob=index._db.execute('SELECT payload FROM mapping_receipt').fetchone()[0]
    connection.send_saved_confirmation()
    assert index.saved_mapping_receipt()==original and index._db.execute('SELECT payload FROM mapping_receipt').fetchone()[0]==blob
    assert target.read_bytes()==b'keep newer crop' and index.saved_receipts()==receipts
    assert len(saved_messages(receiving))==2 and len(connection._catalog.jobs())==1


def test_lost_postcommit_sync_fences_old_worker_fresh_open_reads_original_receipt(receiving,monkeypatch):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False);index=receiver._index;sync=os.fsync
    def interrupted(fd):
        if fd==index._database_fd and index._db.execute('PRAGMA user_version').fetchone()==(3,):
            raise OSError('fixture mapping receipt postcommit sync lost')
        sync(fd)
    monkeypatch.setattr(os,'fsync',interrupted)
    with pytest.raises(OSError,match='postcommit'):connection.publish_received(connection.issue_receive_action())
    assert index._uncertain and not saved_messages(receiving)
    with pytest.raises(TransferError):connection.send_saved_confirmation()
    monkeypatch.setattr(os,'fsync',sync);receiver.close();opened=reopen(receiver)
    try:assert opened.saved_mapping_receipt() is not None
    finally:opened.close()


def test_mapping_receipt_schema_upgrade_requires_exact_active_receiver_lease(receiving):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    with pytest.raises(TransferError,match='worker_required'):receiver._index.commit_saved_mapping((),None,object())
    assert receiver._index._schema_version==1 and not saved_messages(receiving)


def test_saved_retry_with_durable_mapping_receipt_uses_readonly_history_no_mapping_commit(receiving,monkeypatch):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action());original=receiver._index.saved_mapping_receipt()
    def forbidden(*args,**kwargs):raise AssertionError('historical retry must not recreate mappings')
    monkeypatch.setattr(connection._mappings,'commit_saved_history',forbidden)
    connection.send_saved_confirmation()
    assert receiver._index.saved_mapping_receipt()==original and len(saved_messages(receiving))==2


def test_revocation_during_receipt_protection_cannot_upgrade_schema_or_send_saved(receiving,monkeypatch):
    connection=receiving[3];receiver,_,_=save(receiving,publish=False);index=receiver._index;protect=index._protect
    def revoke(value,label):
        result=protect(value,label)
        if label=='mapping-receipt':connection._authority.revoke()
        return result
    monkeypatch.setattr(index,'_protect',revoke)
    with pytest.raises(TransferError):connection.publish_received(connection.issue_receive_action())
    assert not saved_messages(receiving)
    assert index._db.execute('PRAGMA user_version').fetchone()==(2,)
    assert not index._db.execute("SELECT name FROM sqlite_master WHERE name='mapping_receipt'").fetchall()


def test_sql_abort_rolls_back_mapping_receipt_and_owner_upgrade_together(receiving,monkeypatch):
    import sqlite3
    connection=receiving[3];receiver,_,_=save(receiving,publish=False);index=receiver._index;protect=index._protect;original=[]
    def interrupt(value,label):
        blob=protect(value,label)
        if label=='mapping-receipt':
            original.append(index._owner_cipher)
            index._db.set_authorizer(lambda action,*args:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_UPDATE and args[0]=='meta' else sqlite3.SQLITE_OK)
        return blob
    monkeypatch.setattr(index,'_protect',interrupt)
    with pytest.raises(sqlite3.DatabaseError):connection.publish_received(connection.issue_receive_action())
    index._db.set_authorizer(None)
    assert index._uncertain and not saved_messages(receiving)
    assert index._db.execute('PRAGMA user_version').fetchone()==(2,)
    assert index._db.execute('SELECT payload FROM meta').fetchone()[0]==original[0]
    assert not index._db.execute("SELECT name FROM sqlite_master WHERE name='mapping_receipt'").fetchall()
    receiver.close();opened=reopen(receiver)
    try:assert opened.saved_mapping_receipt() is None and opened.saved_receipts()
    finally:opened.close()
