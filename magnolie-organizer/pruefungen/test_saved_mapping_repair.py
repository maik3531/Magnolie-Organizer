"""Separate explicit repair uses complete original evidence, never target I/O."""
from pathlib import Path
from dataclasses import replace
import os
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_transfer_job_index import ProtectedTransferJobIndex
from magnolie_photo_destination import NativePhotoDestinationAction
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,reconnect,accept
from test_file_desktop_mapping_save import saved_messages
from test_photo_mappings import save


def interrupted_save(fixture,monkeypatch,*,missing='receipt'):
    connection=fixture[3];receiver,_,_=save(fixture,publish=False)
    owner=receiver._index if missing=='receipt' else connection._mappings;protect=owner._protect
    def fail(value,label):
        if (label=='mapping-receipt' if missing=='receipt' else label.startswith('mapping/')):
            raise OSError('fixture original evidence commit interrupted')
        return protect(value,label)
    monkeypatch.setattr(owner,'_protect',fail)
    with pytest.raises(OSError):connection.publish_received(connection.issue_receive_action())
    assert receiver._index.saved_receipts() and not saved_messages(fixture)
    return receiver


@pytest.mark.parametrize('change',['edited','deleted','replaced'])
def test_fresh_explicit_repair_commits_only_missing_post_receipt_then_separate_action_confirms(receiving,monkeypatch,change):
    receiver=interrupted_save(receiving,monkeypatch);local=receiver._index.saved_receipts();job=receiver.job
    target=receiving[4]/local[0].relative_path
    if change=='edited':target.write_bytes(b'keep user crop')
    elif change=='deleted':target.unlink() # Explicit simulated user deletion in fixture.
    else:
        other=target.with_name('new-user-file.jpg');other.write_bytes(b'keep replacement');other.replace(target)
    before=(target.read_bytes(),target.stat().st_ino) if target.exists() else None
    receiver._stage.cleanup()
    def forbidden(*args,**kwargs):raise AssertionError('repair must not reopen source/stage/journal/publisher or create mappings')
    for name in ('EncryptedTransferStage','ProtectedPublicationJournal','NativeFilePublisher'):
        monkeypatch.setattr('magnolie_file_receive.'+name,forbidden)
    with reconnect(receiving) as fresh:
        connection=fresh[3];monkeypatch.setattr(connection._mappings,'commit_saved_history',forbidden)
        original=connection._mappings.read()
        repaired=connection.repair_saved_mapping_receipt(connection.issue_receive_action(),job.owner)
        assert repaired.entries[0].saved_receipt_sha256==local[0].protected_record_sha256
        assert not saved_messages(fresh) and connection._run is None and connection._mappings.read()==original
        again=connection.repair_saved_mapping_receipt(connection.issue_receive_action(),job.owner)
        assert again==repaired and not saved_messages(fresh)
        connection.recover_saved_confirmation(connection.issue_receive_action(),job.owner)
        assert len(saved_messages(fresh))==1 and len(connection._catalog.jobs())==1
    assert ((target.read_bytes(),target.stat().st_ino) if target.exists() else None)==before


def test_missing_original_mapping_is_held_not_reconstructed_from_receipt(receiving,monkeypatch):
    receiver=interrupted_save(receiving,monkeypatch,missing='mapping')
    with reconnect(receiving) as fresh:
        connection=fresh[3];before=connection._mappings.read()
        with pytest.raises(TransferError,match='original_mappings_required'):
            connection.repair_saved_mapping_receipt(connection.issue_receive_action(),receiver.job.owner)
        assert connection._mappings.read()==before and before.count==0 and not saved_messages(fresh)
        with pytest.raises(TransferError,match='complete_evidence_required'):
            connection.recover_saved_confirmation(connection.issue_receive_action(),receiver.job.owner)


def test_repair_action_expiring_during_protection_cannot_commit_index_upgrade(receiving,monkeypatch):
    receiver=interrupted_save(receiving,monkeypatch);job=receiver.job
    with reconnect(receiving) as fresh:
        connection=fresh[3];clock=[1000];action=NativePhotoDestinationAction(connection,lambda:clock[0])
        protect=ProtectedTransferJobIndex._protect
        def expire(index,value,label):
            blob=protect(index,value,label)
            if label=='mapping-receipt':clock[0]+=60_000
            return blob
        monkeypatch.setattr(ProtectedTransferJobIndex,'_protect',expire)
        with pytest.raises(TransferError,match='action_not_current'):
            connection.repair_saved_mapping_receipt(action,job.owner)
        assert connection._mutation_action is None and not saved_messages(fresh)
        # No upgrade committed: the separate readonly confirmation remains held.
        with pytest.raises(TransferError,match='complete_evidence_required'):
            connection.recover_saved_confirmation(connection.issue_receive_action(),job.owner)


def test_unpublished_incomplete_job_is_not_finished_by_metadata_repair(receiving):
    receiver,_,_=save(receiving,publish=False)
    before=tuple((entry.name,entry.stat().st_ino,entry.stat().st_size) for entry in receiving[4].iterdir())
    with reconnect(receiving) as fresh:
        connection=fresh[3]
        with pytest.raises(TransferError):connection.repair_saved_mapping_receipt(connection.issue_receive_action(),receiver.job.owner)
        assert not saved_messages(fresh)
        assert tuple((entry.name,entry.stat().st_ino,entry.stat().st_size) for entry in receiving[4].iterdir())==before


@pytest.mark.parametrize('mode',['exit','revoke'])
def test_exit_or_revocation_during_repair_protection_cannot_commit_or_send(receiving,monkeypatch,mode):
    receiver=interrupted_save(receiving,monkeypatch);job=receiver.job
    with reconnect(receiving) as fresh:
        connection=fresh[3];protect=ProtectedTransferJobIndex._protect
        def stop(index,value,label):
            blob=protect(index,value,label)
            if label=='mapping-receipt':
                if mode=='exit':assert not connection.close()
                else:connection._authority.revoke()
            return blob
        monkeypatch.setattr(ProtectedTransferJobIndex,'_protect',stop)
        with pytest.raises(TransferError):connection.repair_saved_mapping_receipt(connection.issue_receive_action(),job.owner)
        assert not saved_messages(fresh) and connection._mutation_action is None
    monkeypatch.setattr(ProtectedTransferJobIndex,'_protect',protect)
    with reconnect(receiving) as final:
        with pytest.raises(TransferError,match='complete_evidence_required'):
            final[3].recover_saved_confirmation(final[3].issue_receive_action(),job.owner)
        assert not saved_messages(final)


def test_lost_repair_postcommit_sync_returns_no_success_but_fresh_original_receipt_can_be_read(receiving,monkeypatch):
    receiver=interrupted_save(receiving,monkeypatch);job=receiver.job;sync=os.fsync
    indexes=[];protect=ProtectedTransferJobIndex._protect;results=[]
    def observe(index,value,label):
        blob=protect(index,value,label)
        if label=='mapping-receipt':indexes.append(index)
        return blob
    def lost(fd):
        for index in indexes:
            if fd==index._database_fd and index._db.execute('PRAGMA user_version').fetchone()==(3,):
                raise OSError('fixture repair postcommit sync lost')
        return sync(fd)
    monkeypatch.setattr(ProtectedTransferJobIndex,'_protect',observe);monkeypatch.setattr(os,'fsync',lost)
    with reconnect(receiving) as fresh:
        connection=fresh[3]
        with pytest.raises(OSError,match='postcommit'):
            results.append(connection.repair_saved_mapping_receipt(connection.issue_receive_action(),job.owner))
        assert not results and not saved_messages(fresh) and connection._mutation_action is None
        monkeypatch.setattr(os,'fsync',sync)
        actual=connection.repair_saved_mapping_receipt(connection.issue_receive_action(),job.owner)
        assert actual is not None and not saved_messages(fresh)
        connection.recover_saved_confirmation(connection.issue_receive_action(),job.owner)
        assert len(saved_messages(fresh))==1 and len(connection._catalog.jobs())==1


def test_legacy_job_without_original_media_anchor_is_not_upgraded_from_new_defaults(receiving):
    connection=receiving[3];accept(receiving);job=connection._run.receiver.job
    assert connection._run.receiver._index.media_history is None
    with reconnect(receiving) as fresh:
        with pytest.raises(TransferError,match='original_history_required'):
            fresh[3].repair_saved_mapping_receipt(fresh[3].issue_receive_action(),job.owner)
        assert not saved_messages(fresh) and len(fresh[3]._catalog.jobs())==1


@pytest.mark.parametrize('field,value',[('job_owner','e'*32),('receipt_sha256','e'*64),('relative_path','foreign-target.jpg')])
def test_repair_rejects_native_record_with_wrong_original_context_before_index_commit(receiving,monkeypatch,field,value):
    receiver=interrupted_save(receiving,monkeypatch)
    with reconnect(receiving) as fresh:
        connection=fresh[3];lookup=connection._mappings.lookup
        def changed(associations):
            snapshot,records=lookup(associations)
            return snapshot,tuple(replace(record,**{field:value}) for record in records)
        monkeypatch.setattr(connection._mappings,'lookup',changed)
        with pytest.raises(TransferError,match='original_evidence_changed'):
            connection.repair_saved_mapping_receipt(connection.issue_receive_action(),receiver.job.owner)
        assert not saved_messages(fresh)
        with pytest.raises(TransferError,match='complete_evidence_required'):
            connection.recover_saved_confirmation(connection.issue_receive_action(),receiver.job.owner)
