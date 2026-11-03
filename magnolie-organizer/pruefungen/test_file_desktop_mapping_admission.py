"""Known historical associations fence actual coordinator admission, not files."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_photo_mappings import save


def committed(fixture):
    connection=fixture[3]
    receiver,pages,association=save(fixture)
    owner=connection._mappings
    snapshot,records=owner.commit_received(owner.issue_action(),owner.read(),receiver,pages)
    # Simulate another explicit admission attempt, retaining the exact native
    # offer and historical receipt proof. No production state reset is exposed.
    receiver.close()
    connection._run=None
    return snapshot,records,association


@pytest.mark.parametrize('state',['original','edited','deleted','replaced'])
@pytest.mark.parametrize('operation',['accept','resume'])
def test_known_native_mapping_holds_before_reservation_even_if_original_is_changed_or_missing(receiving,monkeypatch,state,operation):
    connection=receiving[3]
    snapshot,records,association=committed(receiving)
    target=receiving[4]/records[0].relative_path
    if state=='edited':target.write_bytes(b'keep my crop')
    elif state=='deleted':target.unlink() # Explicit fixture user action, not sync.
    elif state=='replaced':
        replacement=target.with_name('user-replacement.jpg');replacement.write_bytes(b'keep replacement')
        replacement.replace(target)
    before=target.read_bytes() if target.exists() else None
    jobs=connection._catalog.jobs()
    def forbidden(*args,**kwargs):raise AssertionError('mapping hold must precede catalog/reservation')
    monkeypatch.setattr(connection,'_open_catalog',forbidden)
    with pytest.raises(TransferError,match='photo_mapping_requires_reconcile'):
        action=connection.issue_receive_action();offer_id=connection._offer['message_id']
        if operation=='accept':connection.accept_pending_offer(action,offer_id)
        else:connection.resume_pending_offer(action,offer_id,records[0].job_owner)
    assert connection._run is None and connection._catalog.jobs()==jobs
    assert (target.read_bytes() if target.exists() else None)==before
    assert connection._mappings.lookup((association,))==(snapshot,records)


def test_missing_media_cannot_bypass_existing_history_via_legacy_offer(receiving,monkeypatch):
    connection=receiving[3];committed(receiving)
    connection._source_media_pages=();connection._source_media_entries=None
    with pytest.raises(TransferError,match='photo_mapping_media_required'):
        connection.accept_pending_offer(connection.issue_receive_action(),connection._offer['message_id'])
    assert connection._run is None


def test_mapping_corruption_blocks_admission_without_erasing_metadata_or_creating_another_job(receiving):
    connection=receiving[3];_,records,_=committed(receiving)
    owner=connection._mappings
    blob=owner._db.execute('SELECT payload FROM mappings').fetchone()[0]
    broken=blob[:-1]+bytes([blob[-1]^1])
    with owner._db:owner._db.execute('UPDATE mappings SET payload=?',(broken,))
    with pytest.raises(TransferError,match='photo_mappings_members_changed'):
        owner.lookup(())
    # With mandatory original-root binding, native availability fences this
    # observed corruption before a new acceptance can reach historical lookup.
    with pytest.raises(TransferError,match='receive_controls_not_agreed'):
        connection.accept_pending_offer(connection.issue_receive_action(),connection._offer['message_id'])
    assert connection._run is None and owner._uncertain
    assert owner._db.execute('SELECT payload FROM mappings').fetchone()[0]==broken
    assert (receiving[4]/records[0].relative_path).read_bytes()==b'hello'
