"""Original native mapping-state minimum, not post-save anti-rollback proof."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_file_media_history import NativeMediaHistory
from magnolie_photo_mappings import ProtectedPhotoMappings
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving,offer
from test_file_desktop_mapping_witness import anchor
from test_file_media_history import admit,unpublished
from test_photo_mappings import save
from test_file_desktop_media_resume import retry_offer


def test_marked_job_anchors_actual_protected_owner_hash_before_chunks_not_absent_default(receiving):
    connection=receiving[3];witness=anchor(receiving);receiver=admit(receiving)
    history=receiver._index.media_history;minimum=history.mapping_store
    owner=connection._mappings
    assert minimum.witness==witness and minimum.revision==1 and minimum.count==0
    assert minimum.version==sha256(owner._db.execute('SELECT payload FROM owner').fetchone()[0]).hexdigest()
    assert minimum.version!=owner.read().version # Public absent-CAS sentinel is not the protected owner hash.
    assert history.wire()['format']==2 and NativeMediaHistory.parse(history.wire(),receiver._accepted)==history
    assert owner.verify_checkpoint(minimum)==minimum and not receiver._index.saved_receipts()
    unpublished(receiving,receiver)


def test_malformed_or_missing_checkpoint_in_new_history_is_not_defaulted(receiving):
    connection=receiving[3];anchor(receiving);receiver=admit(receiving)
    history=receiver._index.media_history;original=history.wire();variants=[]
    bad=deepcopy(original);del bad['mapping_store'];variants.append(bad)
    for field,value in [('revision',True),('revision',0),('count',True),('count',10_001),('version','not-a-version'),('witness',{})]:
        bad=deepcopy(original);bad['mapping_store'][field]=value;variants.append(bad)
    bad=deepcopy(original);bad['format']=1;variants.append(bad)
    for bad in variants:
        with pytest.raises(TransferError):NativeMediaHistory.parse(bad,receiver._accepted)
    assert receiver._index.media_history==history
    unpublished(receiving,receiver)


def test_later_native_save_can_advance_store_without_rewriting_original_minimum(receiving):
    connection=receiving[3];anchor(receiving);receiver,_,_=save(receiving,publish=False)
    original=receiver._index.media_history
    connection.publish_received(connection.issue_receive_action())
    current=connection._mappings.verify_checkpoint(original.mapping_store)
    assert current.revision==original.mapping_store.revision+1 and current.count==1
    connection.send_saved_confirmation()
    assert receiver._index.media_history==original


def test_same_revision_changed_owner_cipher_is_fenced_after_metadata_owner_reopen(receiving):
    connection=receiving[3];anchor(receiving);receiver=admit(receiving)
    minimum=receiver._index.media_history.mapping_store;owner=connection._mappings
    blob=owner._db.execute('SELECT payload FROM owner').fetchone()[0]
    changed=owner._protect(owner._unprotect(blob,'owner'),'owner')
    assert changed!=blob
    with owner._db:owner._db.execute('UPDATE owner SET payload=?',(changed,))
    owner.close();connection._mappings=ProtectedPhotoMappings(connection._authority)
    with pytest.raises(TransferError,match='checkpoint_changed'):
        connection._mappings.verify_checkpoint(minimum)
    assert connection._mappings._uncertain
    assert connection._mappings._db.execute('SELECT payload FROM owner').fetchone()[0]==changed
    unpublished(receiving,receiver)


def test_previously_observed_actual_store_minimum_rejects_older_native_metadata_after_reopen(receiving):
    connection=receiving[3];witness=anchor(receiving);owner=connection._mappings
    original=owner._db.execute('SELECT payload FROM owner').fetchone()[0]
    receiver,_,_=save(receiving,publish=False)
    connection.publish_received(connection.issue_receive_action())
    observed=owner.checkpoint(witness)
    assert observed.revision==2 and observed.count==1
    # Fixture-only consistent older metadata replay, preserving the actual saved
    # file and original store objects. This is not a production deletion/reset.
    with owner._db:
        owner._db.execute('DELETE FROM mappings')
        owner._db.execute('UPDATE owner SET payload=?',(original,))
    owner.close();connection._mappings=ProtectedPhotoMappings(connection._authority)
    with pytest.raises(TransferError,match='checkpoint_changed'):connection._mappings.verify_checkpoint(observed)
    assert (receiving[4]/receiver._index.saved_receipts()[0].relative_path).read_bytes()==b'hello'


def test_marked_policy_cannot_admit_legacy_offer_without_original_media_checkpoint(receiving):
    connection=receiving[3];anchor(receiving);message,_=offer(receiving)
    with pytest.raises(TransferError,match='job_mapping_checkpoint_required'):
        connection.accept_pending_offer(connection.issue_receive_action(),message['message_id'])
    assert connection._run is None and connection._catalog is None and not list(receiving[4].iterdir())


def test_marked_resume_keeps_original_store_checkpoint_while_new_page_attempt_changes(receiving):
    connection=receiving[3];anchor(receiving)
    receiver,job,original,offered=retry_offer(receiving)
    assert original.mapping_store is not None
    connection.resume_pending_offer(connection.issue_receive_action(),offered['message_id'],job.owner)
    assert connection._run.receiver._index.media_history==original
    unpublished(receiving,receiver)


def test_saved_mapping_commit_itself_fences_changed_same_revision_checkpoint_before_any_row_insert(receiving):
    connection=receiving[3];anchor(receiving)
    receiver,_,_=save(receiving) # Actual native file/receipts, no coordinator mapping/ACK yet.
    owner=connection._mappings;blob=owner._db.execute('SELECT payload FROM owner').fetchone()[0]
    changed=owner._protect(owner._unprotect(blob,'owner'),'owner')
    with owner._db:owner._db.execute('UPDATE owner SET payload=?',(changed,))
    owner.close();connection._mappings=ProtectedPhotoMappings(connection._authority)
    reopened=connection._mappings;expected=reopened.read()
    with pytest.raises(TransferError,match='checkpoint_changed'):
        reopened.commit_saved_history(reopened.issue_action(),expected,receiver)
    assert reopened._uncertain and reopened._db.execute('SELECT count(*) FROM mappings').fetchone()==(0,)
    assert reopened._db.execute('SELECT payload FROM owner').fetchone()[0]==changed
    assert (receiving[4]/receiver._index.saved_receipts()[0].relative_path).read_bytes()==b'hello'
