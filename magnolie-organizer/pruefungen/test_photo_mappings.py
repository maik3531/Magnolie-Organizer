"""Historical mappings only from actual protected native save receipts."""
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_photo_mappings import ProtectedPhotoMappings,PhotoMappingAssociation
from cryptography.exceptions import InvalidTag
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native,bind
from test_file_desktop_receive import receiving,chunk
from test_file_desktop_sources import ready_source
from test_file_desktop_media import manifest,collect,send_offer,dispatch
import magnolie_telefon as phone


@pytest.fixture
def mappings(receiving):
    # Use the actual coordinator owner so its held-I/O validation lease is the
    # same native object that projects the now-mandatory original-root policy.
    owner=receiving[3]._mappings
    try:yield receiving,owner
    finally:owner.close()


def save(fixture,*,count=1,publish=True):
    connection=fixture[3]
    ready_source(fixture);full=manifest(fixture,count);collect(fixture,full)
    offered,result=send_offer(fixture,full);dispatch(fixture,result)
    connection.accept_pending_offer(connection.issue_receive_action(),offered['message_id'])
    for file in full.files:dispatch(fixture,chunk(connection.request_next_chunk(),b'hello'))
    if publish:
        # Standalone mapping-store tests stop after native publication + receipt
        # readback, before coordinator mapping/ACK. Keep its actual native gate.
        action=connection.issue_receive_action();connection._take_action(action)
        connection._mutation_action=action
        try:
            connection._run.receiver.publish_completed()
            connection._run.receiver.commit_saved_receipts()
        finally:connection._mutation_action=None
    pages=connection._source_media_pages
    association=PhotoMappingAssociation(pages[0].source_epoch,pages[0].entries[0].photo_id,pages[0].media_type)
    return connection._run.receiver,pages,association


def test_passive_mapping_lookup_is_absent_without_creating_store_or_file_consent(mappings):
    fixture,owner=mappings
    root=Path(fixture[0].store.root)
    before={path.name:path.read_bytes() for path in root.iterdir() if path.is_file()}
    association=PhotoMappingAssociation('a'*64,'b'*64,'images')
    snapshot,found=owner.lookup((association,))
    assert snapshot.count==0 and found==(None,) and not (root/owner._name).exists()
    assert owner.read()==snapshot
    assert before=={path.name:path.read_bytes() for path in root.iterdir() if path.is_file()}
    with pytest.raises(TransferError):owner.local_grant(True)


def test_actual_saved_receiver_commits_encrypted_original_mapping_and_exact_retry_is_idempotent(mappings):
    fixture,owner=mappings
    receiver,pages,association=save(fixture)
    photo_policy=fixture[3]._preferences.read()
    saved,records=owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    assert saved.associated and saved.count==1 and saved.revision==2
    record=records[0]
    assert record.association==association and record.relative_path==receiver._index.saved_receipts()[0].relative_path
    assert record.file_key==receiver._index.saved_receipts()[0].file_key
    assert record.receipt_sha256==receiver._index.saved_receipts()[0].protected_record_sha256
    assert not record.grants_write_authority and not record.is_saved_receipt
    assert owner.lookup((association,))==(saved,records)
    assert owner.commit_received(owner.issue_action(),saved,receiver,pages)==(saved,records)
    assert fixture[3]._preferences.read()==photo_policy
    data=(Path(fixture[0].store.root)/owner._name/'prefs.sqlite').read_bytes()
    assert record.relative_path.encode() not in data and record.receipt_sha256.encode() not in data


def test_reopened_mapping_keeps_original_location_after_pc_edit_without_claiming_current_presence(mappings):
    fixture,owner=mappings
    receiver,pages,association=save(fixture)
    saved,records=owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    target=fixture[4]/records[0].relative_path
    target.write_bytes(b'PC crop kept at original target')
    owner.close();reopened=ProtectedPhotoMappings(fixture[3]._authority);fixture[3]._mappings=reopened
    try:
        assert reopened.lookup((association,))==(saved,records)
        assert target.read_bytes()==b'PC crop kept at original target'
        assert records[0].saved_sha256!=receiver.observe_saved_photo(records[0].source_file_id).observation.content.sha256
    finally:reopened.close()


def test_no_saved_receipt_or_incomplete_actual_receipt_set_cannot_create_mappings(mappings):
    fixture,owner=mappings
    receiver,pages,_=save(fixture,count=2,publish=False)
    original=owner.read()
    with pytest.raises(TransferError,match='complete_saved_receipts_required'):
        owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    assert owner.read()==original and original.count==0
    connection=fixture[3];action=connection.issue_receive_action();connection._take_action(action)
    connection._mutation_action=action
    try:receiver.publish_completed();receiver.commit_saved_receipts()
    finally:connection._mutation_action=None
    receipts=receiver._index.saved_receipts()
    with receiver._index._db:receiver._index._db.execute('DELETE FROM receipts WHERE file_id=?',(receipts[1].file_id,))
    with pytest.raises(TransferError,match='complete_saved_receipts_required'):
        owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    assert owner.read()==original
    assert all((fixture[4]/receipt.relative_path).read_bytes()==b'hello' for receipt in receipts)


def test_wire_foreign_and_replayed_actions_or_stale_snapshots_do_not_overwrite_original_mapping(mappings):
    fixture,owner=mappings
    receiver,pages,association=save(fixture)
    old=owner.read();action=owner.issue_action()
    saved,records=owner.commit_received(action,old,receiver,pages)
    with pytest.raises(TransferError):owner.commit_received(action,saved,receiver,pages)
    with pytest.raises(TransferError,match='cas_conflict'):owner.commit_received(owner.issue_action(),old,receiver,pages)
    with pytest.raises(TransferError):owner.commit_received({'token':'wire'},saved,receiver,pages)
    with pytest.raises(TransferError):owner.commit_received(fixture[3]._preferences.issue_action(),saved,receiver,pages)
    with pytest.raises(TransferError):owner.commit_received(owner.issue_action(),saved,{'saved':True},pages)
    assert owner.lookup((association,))==(saved,records)


def test_mapping_survives_checkbox_changes_and_missing_target_without_becoming_permission_to_recreate(mappings):
    fixture,owner=mappings
    receiver,pages,association=save(fixture)
    saved,records=owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    target=fixture[4]/records[0].relative_path
    target.unlink() # Explicit fixture user deletion, never performed by mapping lookup.
    prefs=fixture[3]._preferences
    prefs.configure(prefs.issue_action(),prefs.read(),enabled=True,mode='manual',separate_animations=True,separate_own_recordings=True)
    assert owner.lookup((association,))==(saved,records)
    assert not target.exists() and not records[0].grants_write_authority
    assert not (fixture[4]/'Animationen').exists() and not (fixture[4]/'Eigene Aufnahmen').exists()


@pytest.mark.parametrize('change',['mapping','owner','missing-row','unknown-entry'])
def test_changed_metadata_is_preserved_and_fenced_instead_of_reset_or_empty_lookup(mappings,change):
    fixture,owner=mappings
    receiver,pages,association=save(fixture)
    _,records=owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    if change=='mapping':
        row=owner._db.execute('SELECT payload FROM mappings').fetchone()[0]
        broken=row[:-1]+bytes([row[-1]^1])
        with owner._db:owner._db.execute('UPDATE mappings SET payload=?',(broken,))
    elif change=='owner':
        row=owner._db.execute('SELECT payload FROM owner').fetchone()[0]
        broken=row[:-1]+bytes([row[-1]^1])
        with owner._db:owner._db.execute('UPDATE owner SET payload=?',(broken,))
    elif change=='missing-row':
        with owner._db:owner._db.execute('DELETE FROM mappings')
    else:
        extra=Path(fixture[0].store.root)/owner._name/'unknown-user-metadata'
        extra.write_bytes(b'preserve');extra.chmod(0o600)
    with pytest.raises((TransferError,InvalidTag)):owner.lookup((association,))
    assert owner._uncertain and (fixture[4]/records[0].relative_path).read_bytes()==b'hello'
    if change in ('mapping','owner'):
        table='mappings' if change=='mapping' else 'owner'
        assert owner._db.execute('SELECT payload FROM '+table).fetchone()[0]==broken
        with owner._db:owner._db.execute('UPDATE '+table+' SET payload=?',(row,))
        with pytest.raises(TransferError):owner.lookup((association,)) # No silent revival after observed corruption.
    elif change=='unknown-entry':assert extra.read_bytes()==b'preserve'


def test_post_commit_sync_failure_reports_no_success_and_reopen_authenticates_the_actual_mapping(mappings,monkeypatch):
    fixture,owner=mappings
    receiver,pages,association=save(fixture)
    sync=owner._sync;calls=[]
    def fail_after_commit():
        calls.append(1)
        if not owner._db.in_transaction and owner._db.execute('SELECT count(*) FROM mappings').fetchone()==(1,):
            raise OSError('fixture lost post-commit mapping directory sync')
        sync()
    monkeypatch.setattr(owner,'_sync',fail_after_commit)
    with pytest.raises(OSError,match='post-commit'):
        owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    assert owner._uncertain
    owner.close();reopened=ProtectedPhotoMappings(fixture[3]._authority);fixture[3]._mappings=reopened
    try:
        recovered,records=reopened.lookup((association,))
        assert recovered.count==1 and recovered.revision==2 and records[0] is not None
        assert reopened.commit_received(reopened.issue_action(),recovered,receiver,pages)==(recovered,records)
        assert (fixture[4]/records[0].relative_path).read_bytes()==b'hello'
    finally:reopened.close()


def test_initial_mapping_seal_failure_does_not_fabricate_saved_rows_or_overwrite_photo_preferences(mappings,monkeypatch):
    fixture,owner=mappings
    receiver,pages,association=save(fixture)
    policy=fixture[3]._preferences.read();protect=owner._protect
    def failed(value,label):
        if label.startswith('mapping/'):raise OSError('fixture mapping protection failed')
        return protect(value,label)
    monkeypatch.setattr(owner,'_protect',failed)
    with pytest.raises(OSError):owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    assert owner.lookup((association,))[1]==(None,)
    assert fixture[3]._preferences.read()==policy and receiver._index.saved_receipts()
    monkeypatch.setattr(owner,'_protect',protect)
    assert owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)[0].count==1


def test_bounded_mapping_capacity_never_commits_a_partial_file_set(mappings,monkeypatch):
    fixture,owner=mappings
    receiver,pages,_=save(fixture,count=2)
    monkeypatch.setattr(owner,'MAX_MAPPINGS',1)
    with pytest.raises(TransferError,match='photo_mappings_limit'):
        owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    assert owner.read().count==0
    assert all((fixture[4]/file.path).read_bytes()==b'hello' for file in receiver._accepted.manifest.files)


def test_mapping_close_during_native_seal_keeps_its_descriptors_until_actual_io_ends(mappings,monkeypatch):
    fixture,owner=mappings
    receiver,pages,_=save(fixture)
    entered=threading.Event();release=threading.Event();ended=threading.Event();errors=[]
    protect=owner._protect
    def blocked(value,label):
        if label.startswith('mapping/'):
            entered.set();assert release.wait(5)
        return protect(value,label)
    monkeypatch.setattr(owner,'_protect',blocked)
    def commit():
        try:owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
        except Exception as error:errors.append(error)
        finally:ended.set()
    worker=threading.Thread(target=commit);worker.start()
    try:
        assert entered.wait(5)
        assert owner.close() is False and owner._db is not None
        assert not fixture[3]._authority.protection._closed
        release.set();assert ended.wait(5);worker.join(5)
        assert len(errors)==1 and isinstance(errors[0],TransferError) and owner._db is None
        assert not fixture[3]._authority.protection._closed
    finally:
        release.set();worker.join(5)
        assert not worker.is_alive()


def test_same_key_repairing_preserves_old_mapping_without_normalizing_its_owner_or_renewing_authority(mappings):
    fixture,owner=mappings
    receiver,pages,association=save(fixture)
    _,records=owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    original=owner._db.execute('SELECT payload FROM owner').fetchone()[0]
    service=fixture[0];peer=service.store.peers[0]
    peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([4])*32)
    service.store.save_peers();channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    reopened=ProtectedPhotoMappings(authority)
    try:
        snapshot,found=reopened.lookup((association,))
        assert not snapshot.associated and snapshot.count==1 and found==records
        assert reopened._db.execute('SELECT payload FROM owner').fetchone()[0]==original
        with pytest.raises(TransferError):reopened.commit_received(reopened.issue_action(),snapshot,receiver,pages)
        assert reopened.lookup((association,))[1]==records
        assert (fixture[4]/records[0].relative_path).read_bytes()==b'hello'
    finally:reopened.close();authority.close()


def test_observed_mapping_owner_rollback_is_sticky_and_keeps_all_actual_files(mappings,monkeypatch):
    fixture,owner=mappings
    receiver,pages,association=save(fixture)
    protect=owner._protect;owners=[owner._db.execute('SELECT payload FROM owner').fetchone()[0]]
    def capture(value,label):
        blob=protect(value,label)
        if label=='owner':owners.append(blob)
        return blob
    monkeypatch.setattr(owner,'_protect',capture)
    owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    assert len(owners)==2
    with owner._db:
        owner._db.execute('DELETE FROM mappings')
        owner._db.execute('UPDATE owner SET payload=?',(owners[0],))
    with pytest.raises(TransferError,match='owner_rollback'):owner.lookup((association,))
    assert owner._uncertain and (fixture[4]/receiver._accepted.manifest.files[0].path).read_bytes()==b'hello'


def test_missing_original_mapping_directory_is_not_treated_as_fresh_empty_store_by_its_live_owner(mappings):
    fixture,owner=mappings
    receiver,pages,association=save(fixture)
    _,records=owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    original=Path(fixture[0].store.root)/owner._name
    held=original.with_name(original.name+'-held-original')
    original.rename(held)
    try:
        with pytest.raises((TransferError,OSError)):owner.lookup((association,))
        assert owner._uncertain and not original.exists() and held.is_dir()
        assert (fixture[4]/records[0].relative_path).read_bytes()==b'hello'
    finally:held.rename(original)
