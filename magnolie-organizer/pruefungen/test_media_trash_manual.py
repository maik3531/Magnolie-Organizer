"""Explicit selected-entry purge; never/manual is not automatic expiry consent."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_media_trash import ProtectedMediaTrash,NativeMediaRetentionPermit,NativeMediaPurgeLocation
from magnolie_media_trash_ui import NativeMediaTrashUi
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native,bind
from test_file_desktop_receive import receiving
from test_photo_mappings import mappings
from test_media_trash import trash,prepare,paths


def deleted(trash):
    owner=trash[4];snapshot,entry=prepare(trash)
    return owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)


def test_explicit_manual_confirmation_releases_unexpired_bytes_and_preserves_new_original(trash):
    owner=trash[4];snapshot,entry=deleted(trash);original,payload=paths(trash,entry)
    assert not entry.expired(365,entry.trashed_ms)
    original.write_bytes(b'new user file');original.chmod(0o600)
    snapshot,done=owner.purge_manual(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert done.state=='purged' and done.purge.manual and done.purge.retention_days==0
    assert not payload.exists() and original.read_bytes()==b'new user file'
    assert (original.parent/done.purge.name/'payload').stat().st_size==0
    assert owner.read()==(snapshot,(done,)) and owner._db.execute('SELECT count(*) FROM events').fetchone()==(4,)
    with pytest.raises(TransferError):owner.restore(owner.issue_action(),snapshot,entry.operation,lambda:True)


def test_manual_confirmation_withdrawal_holds_bytes_and_never_setting_cannot_resume_it(trash):
    owner=trash[4];snapshot,entry=deleted(trash);original,payload=paths(trash,entry);allowed=[True]
    def revoke(at):
        if at=='before_purge_bytes':allowed[0]=False
    owner._boundary=revoke
    with pytest.raises(TransferError,match='confirmation_changed'):
        owner.purge_manual(owner.issue_action(),snapshot,entry.operation,lambda:allowed[0])
    snapshot,entries=owner.read();entry=entries[0]
    marker=original.parent/entry.purge.name/'payload'
    assert entry.state=='purge_prepared' and marker.read_bytes()==b'hello'
    owner._boundary=lambda at:None
    assert owner.purge_expired(owner.issue_action(),snapshot,entry.operation,NativeMediaRetentionPermit(0,lambda:0))==(snapshot,entry)
    assert marker.read_bytes()==b'hello'
    snapshot,entry=owner.restore(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert entry.state=='restored' and original.read_bytes()==b'hello' and not payload.exists()


@pytest.mark.parametrize('phase',['purge_prepared','purge_moved','purge_bytes_released'])
def test_interrupted_manual_cleanup_needs_fresh_native_confirmation_to_resume(trash,phase):
    owner=trash[4];snapshot,entry=deleted(trash);original,payload=paths(trash,entry)
    class Interrupted(Exception):pass
    def stop(at):
        if at==phase:raise Interrupted()
    owner._boundary=stop
    with pytest.raises(Interrupted):owner.purge_manual(owner.issue_action(),snapshot,entry.operation,lambda:True)
    owner.close()
    with_owner=ProtectedMediaTrash(trash[0][3]._authority)
    try:
        current,entries=with_owner.read();assert entries[0].purge.manual
        with pytest.raises(TransferError,match='confirmation_changed'):
            with_owner.purge_manual(with_owner.issue_action(),current,entry.operation,lambda:False)
        current,done=with_owner.purge_manual(with_owner.issue_action(),current,entry.operation,lambda:True)
        assert done.state=='purged' and not payload.exists() and not original.exists()
        assert (original.parent/done.purge.name/'payload').stat().st_size==0
    finally:with_owner.close()


def test_native_facade_manual_purge_uses_exact_version_and_opaque_confirmation_only(trash):
    owner=trash[4];snapshot,entry=deleted(trash);original,payload=paths(trash,entry)
    root=str(trash[0][0].store.root);sent=trash[0][2].send.call_count
    ui=NativeMediaTrashUi(root,lambda:True)
    listed=ui.handle(dict(cmd='medien_papierkorb',request_id='manual_list_fixture',action='list'))
    row=listed['entries'][0]
    request=dict(cmd='medien_papierkorb',request_id='manual_purge_fixture',action='purge',confirmed=True,
        **{key:row[key] for key in ('scope','operation','version')})
    for confirmation in (False,1,'true',None):
        with pytest.raises(TransferError,match='invalid_request'):ui.handle(dict(request,confirmed=confirmation))
    with pytest.raises(TransferError,match='invalid_request'):ui.handle(dict(request,path=str(payload)))
    with pytest.raises(TransferError,match='stale_choice'):ui.handle(dict(request,version='0'*64))
    assert payload.read_bytes()==b'hello'
    result=ui.handle(request)
    assert result['completed']==dict(scope=row['scope'],operation=entry.operation,state='purged')
    assert not payload.exists() and not original.exists() and ui.handle(dict(cmd='medien_papierkorb',request_id='manual_list_again',action='list'))['total']==0
    assert trash[0][2].send.call_count==sent


def test_prepared_original_or_boolean_gate_cannot_be_permanently_deleted(trash):
    owner=trash[4];snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    with pytest.raises(TransferError,match='confirmation_required'):
        owner.purge_manual(owner.issue_action(),snapshot,entry.operation,True)
    with pytest.raises(TransferError,match='purge_not_current'):
        owner.purge_manual(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert original.read_bytes()==b'hello' and not payload.exists()


def test_manual_purge_marker_requires_explicit_zero_day_manual_shape(trash):
    _,entry=prepare(trash);mapping=entry.mapping
    value=dict(name='.magnolie-purge-'+entry.operation,key=list(mapping.file_key),retention_days=0)
    for extra in ({},{'manual':False},{'manual':1},{'manual':'true'},{'manual':True,'retention_days':7}):
        with pytest.raises(TransferError,match='invalid_purge_location'):
            NativeMediaPurgeLocation.parse(dict(value,**extra),entry.operation,mapping)
    assert NativeMediaPurgeLocation.parse(dict(value,manual=True),entry.operation,mapping).manual


def test_manual_removal_of_legacy_undated_trash_never_fabricates_expiry(trash):
    owner=trash[4];snapshot,entry=deleted(trash);original,payload=paths(trash,entry)
    # Authenticated legacy-v1 fixture, not an inferred filesystem deletion date.
    with owner._db:
        for sequence,blob in owner._db.execute('SELECT sequence,payload FROM events').fetchall():
            value=owner._unprotect(blob,'event/'+str(sequence));value.pop('changed_ms')
            owner._db.execute('UPDATE events SET payload=? WHERE sequence=?',(owner._protect(value,'event/'+str(sequence)),sequence))
        entries,total,digest=owner._entries()
        head=dict(revision=total+1,count=len(entries),events=total,events_sha256=digest,pairing_epoch=owner._peer().pairing_epoch)
        owner._db.execute('UPDATE owner SET payload=?',(owner._protect(head,'owner'),))
    owner.close();reopened=ProtectedMediaTrash(trash[0][3]._authority)
    try:
        snapshot,entries=reopened.read();entry=entries[0]
        assert entry.trashed_ms is None and not entry.expired(7,253402300799999)
        snapshot,done=reopened.purge_manual(reopened.issue_action(),snapshot,entry.operation,lambda:True)
        assert done.state=='purged' and done.trashed_ms is None and done.purge.manual and not payload.exists()
        assert (original.parent/done.purge.name/'payload').stat().st_size==0
    finally:reopened.close()
