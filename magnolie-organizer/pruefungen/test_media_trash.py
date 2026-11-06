"""Actual saved files enter recoverable local trash; no peer-delete ACK is faked."""
from pathlib import Path
import os
import sys
from dataclasses import replace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_media_trash import ProtectedMediaTrash
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native,bind
from test_file_desktop_receive import receiving
from test_photo_mappings import mappings,save


@pytest.fixture
def trash(mappings):
    fixture,store=mappings
    receiver,pages,association=save(fixture)
    _,records=store.commit_received(store.issue_action(),store.read(),receiver,pages)
    owner=ProtectedMediaTrash(fixture[3]._authority)
    try:yield fixture,store,association,records[0],owner
    finally:owner.close()


def prepare(fixture):
    _,mappings,association,mapping,owner=fixture
    before,_=owner.read()
    return owner.prepare_local(owner.issue_action(),before,mappings,association,mapping.protected_record_sha256)


def paths(fixture,entry):
    root=fixture[0][4]
    original=root/entry.mapping.relative_path
    return original,original.parent/entry.payload_name


def test_absent_read_creates_no_trash_and_cannot_be_a_delete_receipt(trash):
    fixture,_,_,_,owner=trash
    root=Path(fixture[0].store.root)
    before=set(root.iterdir())
    snapshot,entries=owner.read()
    assert snapshot.count==0 and not entries and set(root.iterdir())==before
    assert not (root/owner._name).exists()

def test_backup_parent_is_rejected_before_any_target_io_or_delete_evidence(trash):
    fixture,_,_,mapping,owner=trash
    _,entry=prepare(trash)
    original=fixture[4]/mapping.relative_path;before=original.read_bytes()
    # Deny-only coverage: even a historical/private caller supplying a Backup
    # parent must not get as far as opening the directory or invoking an IO gate.
    excluded=replace(entry,mapping=replace(mapping,relative_path='Backup/deep/photo.jpg'))
    def gate():pytest.fail('Excluded backup target reached native mutation admission')
    with pytest.raises(TransferError,match='media_backup_subtree_excluded'):
        with owner._target_context(excluded,gate):pytest.fail('Excluded backup context was yielded')
    assert original.read_bytes()==before and not (fixture[4]/'Backup').exists()


def test_actual_saved_bytes_move_to_trash_and_restore_without_deletion_replay(trash):
    _,_,_,mapping,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    assert original.read_bytes()==b'hello' and not payload.exists() and entry.state=='prepared'
    trashed,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert not original.exists() and payload.read_bytes()==b'hello' and entry.state=='trashed'
    assert (payload.stat().st_dev,payload.stat().st_ino)==mapping.file_key
    assert not entry.grants_write_authority and not entry.is_counterpart_ack
    restored,entry=owner.restore(owner.issue_action(),trashed,entry.operation,lambda:True)
    assert original.read_bytes()==b'hello' and not payload.exists() and entry.state=='restored'
    with pytest.raises(TransferError,match='delete_not_current'):
        owner.trash(owner.issue_action(),restored,entry.operation,lambda:True)
    with pytest.raises(TransferError,match='stale_choice'):
        owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    _,entries=owner.read()
    assert entries==(entry,)
    assert owner._db.execute('SELECT count(*) FROM events').fetchone()==(4,)
    raw=(Path(trash[0][0].store.root)/owner._name/'prefs.sqlite').read_bytes()
    assert mapping.relative_path.encode() not in raw and mapping.saved_sha256.encode() not in raw


@pytest.mark.parametrize('boundary',['prepared','moved','trashed','restore_prepared','restored_move'])
def test_restart_uses_exact_original_operation_and_preserved_bytes(trash,boundary):
    _,_,_,_,owner=trash
    class Interrupted(Exception):pass
    def stop(at):
        if at==boundary:raise Interrupted(at)
    if boundary=='prepared':
        owner._boundary=stop
        with pytest.raises(Interrupted):prepare(trash)
    else:
        snapshot,entry=prepare(trash)
        if boundary in ('restore_prepared','restored_move'):
            snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
            owner._boundary=stop
            with pytest.raises(Interrupted):owner.restore(owner.issue_action(),snapshot,entry.operation,lambda:True)
        else:
            owner._boundary=stop
            with pytest.raises(Interrupted):owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    owner.close();reopened=ProtectedMediaTrash(trash[0][3]._authority)
    try:
        snapshot,entries=reopened.read();entry=entries[0];original,payload=paths(trash,entry)
        assert original.exists() or payload.exists()
        if entry.state=='prepared':snapshot,entry=reopened.trash(reopened.issue_action(),snapshot,entry.operation,lambda:True)
        if entry.state in ('trashed','restore_prepared'):
            snapshot,entry=reopened.restore(reopened.issue_action(),snapshot,entry.operation,lambda:True)
        assert entry.state=='restored' and original.read_bytes()==b'hello' and not payload.exists()
        with pytest.raises(TransferError):reopened.trash(reopened.issue_action(),snapshot,entry.operation,lambda:True)
    finally:reopened.close()


def test_edited_original_and_revoked_native_gate_never_move_or_overwrite(trash):
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    with pytest.raises(TransferError,match='gate_revoked'):
        owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:False)
    assert original.read_bytes()==b'hello' and not payload.exists()
    original.write_bytes(b'user edit')
    with pytest.raises(TransferError,match='original_file_changed'):
        owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert original.read_bytes()==b'user edit' and not payload.exists()


def test_restore_collision_keeps_both_versions_and_blocks_old_delete(trash):
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    original.write_bytes(b'new user file');original.chmod(0o600)
    with pytest.raises(TransferError,match='move_conflict'):
        owner.restore(owner.issue_action(),snapshot,entry.operation,lambda:True)
    current,entries=owner.read()
    assert entries[0].state=='restore_prepared'
    assert original.read_bytes()==b'new user file' and payload.read_bytes()==b'hello'
    with pytest.raises(TransferError,match='delete_not_current'):
        owner.trash(owner.issue_action(),current,entry.operation,lambda:True)


def test_before_move_path_replacement_is_preserved_and_rolled_back_no_replace(trash):
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    parked=original.with_name('explicit-test-original')
    def race(at):
        if at=='before_move':
            original.rename(parked);original.write_bytes(b'raced user file');original.chmod(0o600)
    owner._boundary=race
    with pytest.raises(TransferError,match='original_file_changed'):
        owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert original.read_bytes()==b'raced user file' and parked.read_bytes()==b'hello' and not payload.exists()
    assert owner.read()[1][0].state=='prepared'


def test_replayed_or_wire_actions_and_duplicate_selection_do_not_mutate(trash):
    _,mappings,association,mapping,owner=trash
    snapshot,_=owner.read();action=owner.issue_action()
    prepared,entry=owner.prepare_local(action,snapshot,mappings,association,mapping.protected_record_sha256)
    with pytest.raises(TransferError):owner.trash(action,prepared,entry.operation,lambda:True)
    with pytest.raises(TransferError):owner.trash({'wire':True},prepared,entry.operation,lambda:True)
    with pytest.raises(TransferError,match='original_operation_required'):
        owner.prepare_local(owner.issue_action(),prepared,mappings,association,mapping.protected_record_sha256)
    original,payload=paths(trash,entry)
    assert original.read_bytes()==b'hello' and not payload.exists()


def test_actual_video_worker_saved_mapping_uses_separate_video_trash_and_restore(receiving,tmp_path,monkeypatch):
    from hashlib import sha256
    from test_file_desktop_video_album_worker import prepared_video,video_phone
    from test_file_desktop_sources import ALBUM
    from magnolie_photo_mappings import PhotoMappingAssociation
    target,batches=prepared_video(receiving,tmp_path,monkeypatch);connection=receiving[3]
    with video_phone(receiving,target,batches[:1],monkeypatch) as (_,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True,media_type='video')
        assert worker.join(60),worker.progress()
        assert not errors and worker.progress()['state']=='complete' and len(saved)==1
    association=PhotoMappingAssociation('c'*64,sha256(b'worker-photo-0').hexdigest(),'video')
    mappings=connection._mappings
    _,records=mappings.lookup((association,));record=records[0]
    assert record is not None and record.association.media_type=='video'
    assert connection._run is None and worker.io_ended
    snapshot,_=connection.inspect_media_trash(connection.issue_receive_action())
    snapshot,entry=connection.prepare_media_trash(connection.issue_receive_action(),snapshot,association,record.protected_record_sha256)
    snapshot,entry=connection.move_media_to_trash(connection.issue_receive_action(),snapshot,entry.operation)
    original=target/record.relative_path;payload=original.parent/entry.payload_name
    assert not original.exists() and payload.read_bytes()==b'hello' and not list(receiving[4].iterdir())
    # Ordinary synchronization must not resurrect the intentionally removed PC
    # file while counterpart trash propagation is still unjoined.
    with video_phone(receiving,target,batches[:1],monkeypatch) as (chunks,acks,_,_,errors):
        repeat=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True,media_type='video')
        assert repeat.join(60),repeat.progress()
        progress=repeat.progress()
        assert not errors and progress['state']=='conflicts' and not chunks and not acks,progress
        assert progress['conflicts'][0].decision=='pause_unconfirmed_absence'
    assert not original.exists() and payload.read_bytes()==b'hello'
    snapshot,entry=connection.restore_media_from_trash(connection.issue_receive_action(),snapshot,entry.operation)
    assert original.read_bytes()==b'hello' and not payload.exists() and entry.state=='restored'
    with pytest.raises(TransferError,match='delete_not_current'):
        connection.move_media_to_trash(connection.issue_receive_action(),snapshot,entry.operation)
    with video_phone(receiving,target,batches[:1],monkeypatch) as (chunks,acks,_,_,errors):
        repeat=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True,media_type='video')
        assert repeat.join(60),repeat.progress()
        assert not errors and repeat.progress()['state']=='complete' and repeat.progress()['known_files']==1
        assert not chunks and not acks and original.read_bytes()==b'hello'


@pytest.mark.parametrize('change',['event','owner','missing_event'])
def test_tampered_history_stays_preserved_and_cannot_move_file(trash,change):
    from cryptography.exceptions import InvalidTag
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    with owner._db:
        if change=='missing_event':owner._db.execute('DELETE FROM events')
        elif change=='event':
            blob=owner._db.execute('SELECT payload FROM events WHERE sequence=1').fetchone()[0]
            owner._db.execute('UPDATE events SET payload=? WHERE sequence=1',(blob[:-1]+bytes([blob[-1]^1]),))
        else:
            blob=owner._db.execute('SELECT payload FROM owner').fetchone()[0]
            owner._db.execute('UPDATE owner SET payload=?',(blob[:-1]+bytes([blob[-1]^1]),))
    before=(Path(trash[0][0].store.root)/owner._name/'prefs.sqlite').read_bytes()
    with pytest.raises((TransferError,InvalidTag)):owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert original.read_bytes()==b'hello' and not payload.exists()
    assert (Path(trash[0][0].store.root)/owner._name/'prefs.sqlite').read_bytes()==before


def test_existing_payload_name_is_never_replaced(trash):
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    payload.write_bytes(b'unfamiliar existing file');payload.chmod(0o600)
    with pytest.raises(TransferError,match='move_conflict'):
        owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert original.read_bytes()==b'hello' and payload.read_bytes()==b'unfamiliar existing file'


def test_revocation_after_move_holds_payload_without_unauthorized_rollback(trash):
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry);allowed=True
    def boundary(at):
        nonlocal allowed
        if at=='moved':allowed=False
    owner._boundary=boundary
    with pytest.raises(TransferError,match='gate_revoked'):
        owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:allowed)
    assert not original.exists() and payload.read_bytes()==b'hello'
    current,entries=owner.read();assert entries[0].state=='prepared'
    owner._boundary=lambda _:None
    current,entry=owner.trash(owner.issue_action(),current,entry.operation,lambda:True)
    current,entry=owner.restore(owner.issue_action(),current,entry.operation,lambda:True)
    assert entry.state=='restored' and original.read_bytes()==b'hello' and not payload.exists()


def test_native_connection_blocks_trash_during_receiver_and_disabled_handlers(trash,monkeypatch):
    fixture,_,association,mapping,_=trash;connection=fixture[3]
    snapshot,_=connection.inspect_media_trash(connection.issue_receive_action())
    assert connection._run is not None
    with pytest.raises(TransferError,match='receive_already_active'):
        connection.prepare_media_trash(connection.issue_receive_action(),snapshot,association,mapping.protected_record_sha256)
    monkeypatch.setattr(connection,'_data_handlers_ready',False)
    with pytest.raises(TransferError,match='data_handlers_unavailable'):
        connection.prepare_media_trash(connection.issue_receive_action(),snapshot,association,mapping.protected_record_sha256)
    assert not (Path(fixture[0].store.root)/connection._media_trash._name).exists()
    assert (fixture[4]/mapping.relative_path).read_bytes()==b'hello'


def test_history_limit_holds_new_delete_without_discarding_restored_operation(trash,monkeypatch):
    _,mappings,association,mapping,owner=trash
    monkeypatch.setattr(owner,'MAX_OPERATIONS',1)
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    snapshot,entry=owner.restore(owner.issue_action(),snapshot,entry.operation,lambda:True)
    before=(Path(trash[0][0].store.root)/owner._name/'prefs.sqlite').read_bytes()
    with pytest.raises(TransferError,match='transition_unavailable'):
        owner.prepare_local(owner.issue_action(),snapshot,mappings,association,mapping.protected_record_sha256)
    assert owner.read()==(snapshot,(entry,))
    assert (Path(trash[0][0].store.root)/owner._name/'prefs.sqlite').read_bytes()==before
    assert original.read_bytes()==b'hello' and not payload.exists()


def test_same_size_content_edit_and_symlink_are_not_trashed(trash):
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    original.write_bytes(b'world')
    with pytest.raises(TransferError,match='original_content_changed'):
        owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert original.read_bytes()==b'world' and not payload.exists()
    parked=original.with_name('explicit-test-edited-file');original.rename(parked)
    original.symlink_to(parked.name)
    with pytest.raises(OSError):owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert original.is_symlink() and parked.read_bytes()==b'world' and not payload.exists()


@pytest.mark.parametrize('missing',['journal','anchor'])
def test_missing_original_journal_or_anchor_never_becomes_empty_replacement(trash,missing):
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    root=Path(trash[0][0].store.root);name=owner._name if missing=='journal' else owner._anchor
    owner.close();parked=root/(name+'.explicit-fixture-parked');(root/name).rename(parked)
    reopened=ProtectedMediaTrash(trash[0][3]._authority)
    try:
        before=set(root.iterdir())
        with pytest.raises(TransferError,match='original_anchor_required'):reopened.read()
        assert set(root.iterdir())==before and payload.read_bytes()==b'hello' and not original.exists()
    finally:reopened.close()


def test_replaced_journal_directory_cannot_adopt_original_anchor(trash):
    import shutil
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    root=Path(trash[0][0].store.root);name=owner._name;owner.close()
    parked=root/(name+'.explicit-fixture-parked');(root/name).rename(parked)
    shutil.copytree(parked,root/name)
    reopened=ProtectedMediaTrash(trash[0][3]._authority)
    try:
        with pytest.raises(TransferError):reopened.read()
        assert original.read_bytes()==b'hello' and not payload.exists() and parked.is_dir() and (root/name).is_dir()
    finally:reopened.close()


def test_explicit_cancel_keeps_unmoved_original_and_old_delete_cannot_replay(trash):
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.cancel_prepared(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert entry.state=='canceled' and original.read_bytes()==b'hello' and not payload.exists()
    with pytest.raises(TransferError,match='delete_not_current'):
        owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert owner._db.execute('SELECT count(*) FROM events').fetchone()==(2,)


def test_post_move_crash_cannot_cancel_away_recoverable_payload(trash):
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    class Interrupted(Exception):pass
    def stop(at):
        if at=='moved':raise Interrupted()
    owner._boundary=stop
    with pytest.raises(Interrupted):owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    current,_=owner.read()
    with pytest.raises(TransferError,match='cancel_move_uncertain'):
        owner.cancel_prepared(owner.issue_action(),current,entry.operation,lambda:True)
    assert payload.read_bytes()==b'hello' and not original.exists() and owner.read()[1][0].state=='prepared'
